from __future__ import annotations

import pytest

from pg_migration_lint.jvm import lex
from pg_migration_lint.liquibase import applies_to_postgresql
from pg_migration_lint.rules import RULES, SEVERITIES, parse_rule_list
from pg_migration_lint.scanner import findings_for, suppressed_rules
from pg_migration_lint.sql import SqlText, check_sql, lex_sql

# Chapter and section titles exactly as they appear in the book's headings.
BOOK_HEADINGS = {
    'Chapter 2, "Type-system traps"': {
        "Null still has a type",
        "The timestamp exception",
        "Boolean versus `char(1)`, `Y/N`, and `0/1`",
    },
    'Chapter 4, "SQL and query traps"': {
        "Empty collections",
        "Null elements",
        "PostgreSQL arrays",
        "Unknown literals are not typed parameters",
    },
    'Chapter 5, "JSON, LOB, and text"': {"Bind JSON as JSON, not “a string that looks right”"},
    'Chapter 6, "Liquibase cross-database traps"': {"Preconditions are guards, not repairs"},
    'Chapter 8, "Debugging playbook"': {"Worked example: null native-query timestamp"},
}


def kinds(sql: str) -> list[tuple[str, str]]:
    return [(t.kind, t.text) for t in lex_sql(sql)]


def test_rule_catalog_is_complete():
    assert sorted(RULES) == [f"PGM00{i}" for i in range(1, 9)]
    for rule in RULES.values():
        assert rule.severity in SEVERITIES
        assert rule.evidence.startswith(("EXECUTED", "OFFICIAL_DOC_VERIFIED"))
        assert rule.fix and rule.why and rule.title
        for ref in rule.refs:
            assert ref.section in BOOK_HEADINGS[ref.chapter]


def test_parse_rule_list():
    assert parse_rule_list(["pgm001, PGM002", "PGM002"]) == {"PGM001", "PGM002"}
    with pytest.raises(ValueError):
        parse_rule_list(["PGM001,NOPE"])


def test_sql_lexer_skips_comments_and_strings():
    toks = kinds("select 'a''b', E'x\\'y', $$ in () $$, $tag$ ? $tag$ /* ? /* nested */ ? */ -- ?\n from t")
    assert ("ph", "?") not in toks
    assert [k for k, _ in toks].count("str") == 4


def test_sql_lexer_placeholders():
    toks = kinds("where a = ? and b = ?1 and c = :name and d::text = $1 and e ?? 'k' and f[1:n]")
    phs = [t for k, t in toks if k == "ph"]
    assert phs == ["?", "?1", ":name", "$1"]
    assert ("op", "::") in toks and ("op", "??") in toks


def test_cast_column_is_not_named_placeholder():
    st = SqlText("select * from t where payload::text is null", origin="jvm", context="native", named=True)
    assert check_sql(st) == []


def test_pgm002_respects_placeholder_style_per_context():
    sql = "select * from t where (:p is null or c = :p) and (?1 is null) and (? is null)"
    native = SqlText(sql, origin="jvm", context="native", bare_q=True, numbered=True, named=True)
    unknown = SqlText(sql, origin="jvm", context="unknown", bare_q=True)
    assert len([h for h in check_sql(native) if h.rule == "PGM002"]) == 3
    assert len([h for h in check_sql(unknown) if h.rule == "PGM002"]) == 1


def test_enabled_filter_in_sql_checks():
    st = SqlText("select case x when null then 1 end from t where id in ()", origin="sqlfile", context="sqlfile")
    assert {h.rule for h in check_sql(st)} == {"PGM003", "PGM005"}
    assert {h.rule for h in check_sql(st, {"PGM005"})} == {"PGM005"}


def test_java_lexer_strings_text_blocks_and_chars():
    src = 'char q = \'"\'; String a = "x\\"y"; String b = """\n  in ()\n  """; // "not a string"\n'
    strs = [t.text for t in lex(src).toks if t.kind == "str"]
    assert strs == ['x"y', "  in ()\n  "]


def test_kotlin_templates_become_runtime_parts():
    src = 'val s = "id in (${ids.joinToString { "\\"$it\\"" }}) and x = $y"'
    strs = [t for t in lex(src, kotlin=True).toks if t.kind == "str"]
    assert len(strs) == 1
    assert strs[0].text.count("") == 2


def test_suppression_requires_a_comment():
    assert suppressed_rules("x(); // pgmig-lint: ignore[PGM001, pgm003]") == {"PGM001", "PGM003"}
    assert suppressed_rules('s = "pgmig-lint: ignore[PGM001]";') == set()
    assert suppressed_rules("select 1; -- pgmig-lint: ignore[PGM005]") == {"PGM005"}
    assert suppressed_rules("<x/> <!-- pgmig-lint: ignore[PGM006] -->") == {"PGM006"}
    assert suppressed_rules("key: v # pgmig-lint: ignore[PGM007]") == {"PGM007"}


@pytest.mark.parametrize(
    "dbms, applies",
    [
        (None, True), ("postgresql", True), ("oracle", False), ("oracle, postgresql", True),
        ("!postgresql", False), ("!h2", True), ("all", True), ("none", False), ("${db}", True),
    ],
)
def test_dbms_filter(dbms, applies):
    assert applies_to_postgresql(dbms) is applies


def test_unparseable_changelog_is_reported_and_skipped(capsys):
    data = b"<databaseChangeLog><changeSet></databaseChangeLog>"
    assert findings_for("broken.xml", data) == []
    assert "could not parse broken.xml" in capsys.readouterr().err


def test_non_utf8_input_does_not_crash():
    data = "select * from t where name = 'café' and id in ();".encode("latin-1")
    found = findings_for("q.sql", data)
    assert [f.rule.id for f in found] == ["PGM003"]


def test_xml_columns_with_multibyte_text():
    data = (
        '<databaseChangeLog>\n'
        '  <changeSet id="éé" author="中">\n'
        '    <sql>select 1 from t where id in ()</sql>\n'
        '  </changeSet>\n'
        '</databaseChangeLog>\n'
    ).encode("utf-8")
    (f,) = findings_for("c.xml", data)
    assert (f.line, f.column) == (3, data.decode("utf-8").splitlines()[2].index("in (") + 1)

"""Rule catalog.

Every rule is backed by behavior that was executed on PostgreSQL 18.4 / 16.15
with pgJDBC 42.7.13 and Liquibase 5.0.4, or by official documentation, as
recorded for the book "PostgreSQL Migration Survival Guide for Java Teams".
The ``evidence`` field names that record so a reader can check the claim.
"""

from __future__ import annotations

from dataclasses import dataclass

BOOK_TITLE = "PostgreSQL Migration Survival Guide for Java Teams"

SEVERITIES = ("info", "warning", "error")
SEVERITY_RANK = {"info": 0, "warning": 1, "error": 2}


@dataclass(frozen=True)
class BookRef:
    chapter: str
    section: str

    def render(self) -> str:
        return f"{self.chapter} > \"{self.section}\""


@dataclass(frozen=True)
class Rule:
    id: str
    name: str
    severity: str
    title: str
    why: str
    fix: str
    refs: tuple[BookRef, ...]
    evidence: str

    @property
    def learn_more(self) -> str:
        return f"{BOOK_TITLE}: " + "; ".join(r.render() for r in self.refs)


CH2 = 'Chapter 2, "Type-system traps"'
CH4 = 'Chapter 4, "SQL and query traps"'
CH6 = 'Chapter 6, "Liquibase cross-database traps"'
CH8 = 'Chapter 8, "Debugging playbook"'

RULES: dict[str, Rule] = {}


def _add(rule: Rule) -> None:
    RULES[rule.id] = rule


_add(Rule(
    id="PGM001",
    name="untyped-null-binding",
    severity="warning",
    title="Null bound with Types.NULL carries no SQL type",
    why=(
        "setNull(i, Types.NULL) sends a null with no SQL type. Where the SQL gives "
        "the placeholder no type context, for example `? is null`, PostgreSQL rejects "
        "the statement with SQLSTATE 42P18 (could not determine data type of parameter)."
    ),
    fix=(
        "Bind the null with the intended SQL type, e.g. setNull(i, Types.BIGINT) for a "
        "bigint value (tested to work in `? is null`)."
    ),
    refs=(BookRef(CH2, "Null still has a type"),),
    evidence="EXECUTED: untyped null (Types.NULL) in `? is null` fails with 42P18 (case 3e); "
             "setNull(Types.BIGINT) in `? is null` works (case 3a).",
))

_add(Rule(
    id="PGM002",
    name="untyped-optional-filter",
    severity="warning",
    title="Optional-filter placeholder `? is null` has no type context",
    why=(
        "A bare placeholder in `? is null` gives PostgreSQL nothing to infer the "
        "parameter type from. With pgJDBC 42.7.13 a null bound with Types.NULL fails "
        "there with SQLSTATE 42P18, and so does setNull(i, Types.TIMESTAMP_WITH_TIMEZONE) "
        "in `? is null or col >= ?`; setNull(i, Types.BIGINT) works."
    ),
    fix=(
        "Prefer a separate query form when the filter is absent. If one statement must "
        "stay, type the placeholder in SQL: `cast(? as timestamptz) is null` (use the "
        "column's type; tested to work with the same null bindings)."
    ),
    refs=(
        BookRef(CH2, "The timestamp exception"),
        BookRef(CH8, "Worked example: null native-query timestamp"),
    ),
    evidence="EXECUTED: Types.NULL in `? is null` -> 42P18 (3e); setNull(TIMESTAMP_WITH_TIMEZONE) "
             "in `? is null or col >= ?` -> 42P18 (3b); setNull(BIGINT) works (3a); "
             "`cast(? as timestamptz) is null` works (3g). DERIVED_GUIDANCE: separate query forms.",
))

_add(Rule(
    id="PGM003",
    name="empty-in-list",
    severity="error",
    title="Empty `IN ()` list",
    why="`in ()` with an empty list is invalid SQL in PostgreSQL: syntax error, SQLSTATE 42601.",
    fix=(
        "Decide what an empty list means before building SQL: return no rows without "
        "querying, drop the predicate, or reject the input."
    ),
    refs=(BookRef(CH4, "Empty collections"),),
    evidence="EXECUTED: `in ()` is a syntax error (42601) (case Xb).",
))

_add(Rule(
    id="PGM004",
    name="runtime-built-in-list",
    severity="warning",
    title="IN list filled in at runtime can become `in ()`",
    why=(
        "The contents of an IN list are inserted into the SQL text at runtime. When the "
        "collection is empty the statement becomes `in ()`, which PostgreSQL rejects with "
        "SQLSTATE 42601."
    ),
    fix=(
        "Handle the empty collection before building SQL, or bind one typed array: "
        "`col = any (?::bigint[])` with ps.setArray(i, conn.createArrayOf(\"bigint\", ids)) "
        "(tested). Never concatenate values into SQL."
    ),
    refs=(
        BookRef(CH4, "Empty collections"),
        BookRef(CH4, "PostgreSQL arrays"),
    ),
    evidence="EXECUTED: `in ()` is a syntax error (42601) (Xb); `= any (?::bigint[])` with "
             "createArrayOf(\"bigint\", ...) works (Xa).",
))

_add(Rule(
    id="PGM005",
    name="simple-case-when-null",
    severity="error",
    title="Simple `CASE x WHEN NULL` never matches",
    why=(
        "A simple CASE compares with `=`, and `x = null` is never true, so the "
        "`WHEN NULL` branch can never match. Null inputs fall through to ELSE "
        "(or to NULL when there is no ELSE)."
    ),
    fix="Use a searched CASE: `CASE WHEN x IS NULL THEN ... WHEN x = 'Y' THEN ... END`.",
    refs=(BookRef(CH2, "Boolean versus `char(1)`, `Y/N`, and `0/1`"),),
    evidence="EXECUTED: simple `CASE x WHEN NULL` never matches (case 4c); searched-CASE "
             "backfill maps Y/N/null correctly (4d).",
))

_add(Rule(
    id="PGM006",
    name="liquibase-mark-ran-name-only",
    severity="warning",
    title="Liquibase MARK_RAN guarded only by an object name",
    why=(
        "With onFail=\"MARK_RAN\", a precondition that only checks that an object with a "
        "given name does not exist lets any same-named object skip the change set: "
        "Liquibase records it as MARK_RAN and never retries it, so the real change is "
        "skipped permanently."
    ),
    fix=(
        "Prefer onFail=\"HALT\" with an onFailMessage, or make the precondition prove the "
        "full postcondition (columns, types, uniqueness), e.g. with a sqlCheck against the "
        "catalog."
    ),
    refs=(BookRef(CH6, "Preconditions are guards, not repairs"),),
    evidence="EXECUTED: MARK_RAN with a name-only precondition records the change set and "
             "permanently skips the real change (Liquibase case 8). OFFICIAL_DOC_VERIFIED: "
             "onFail/onError MARK_RAN = recorded as executed, not retried.",
))

_add(Rule(
    id="PGM007",
    name="stringtype-unspecified",
    severity="info",
    title="pgJDBC `stringtype=unspecified` is a temporary bridge",
    why=(
        "stringtype=unspecified makes pgJDBC send setString values untyped so the server "
        "infers their type. It changes every setString on the connection, including correct "
        "ones, and hides setter/column mismatches: setString(\"42\") against a bigint column "
        "no longer fails with 42883."
    ),
    fix=(
        "Keep it only as a migration bridge with a removal date: fix the setters (setLong, "
        "PGobject or `?::jsonb` for JSON), then remove the parameter."
    ),
    refs=(
        BookRef(CH4, "Unknown literals are not typed parameters"),
        BookRef('Chapter 5, "JSON, LOB, and text"', "Bind JSON as JSON, not “a string that looks right”"),
    ),
    evidence="EXECUTED: stringtype=unspecified makes setString resolve against bigint and jsonb "
             "(cases 2g, 5e); setString(\"42\") vs bigint fails with 42883 without it (2f). "
             "OFFICIAL_DOC_VERIFIED: pgJDBC stringtype parameter. DERIVED_GUIDANCE: temporary bridge.",
))

_add(Rule(
    id="PGM008",
    name="null-in-in-list",
    severity="warning",
    title="NULL element in `IN (...)` never matches NULL rows",
    why=(
        "IN follows SQL three-valued logic: a NULL element is not a request for IS NULL, "
        "so rows where the column is NULL are not returned."
    ),
    fix=(
        "If NULL rows are wanted, say so: `col in (...) or col is null`; otherwise remove "
        "the NULL element."
    ),
    refs=(BookRef(CH4, "Null elements"),),
    evidence="EXECUTED: null element in IN does not match null rows (case Xc).",
))


def parse_rule_list(values: list[str] | None) -> set[str]:
    """Parse repeated/comma-separated rule ids. Raises ValueError on unknown ids."""
    out: set[str] = set()
    for value in values or []:
        for part in value.split(","):
            rid = part.strip().upper()
            if not rid:
                continue
            if rid not in RULES:
                raise ValueError(f"unknown rule id: {part.strip()}")
            out.add(rid)
    return out

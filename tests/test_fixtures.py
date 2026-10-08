"""Fixture-driven tests.

Each fixture marks the findings it expects on the reported line with
``expect[PGMxxx]`` inside a comment. Formats that cannot carry a trailing
comment (JSON, .properties) use a ``<file>.expect`` sidecar with
``RULE LINE`` pairs. The set of findings must match exactly, so an
unexpected finding (a false positive) fails the test.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from pg_migration_lint.rules import RULES
from pg_migration_lint.scanner import EXTENSIONS, findings_for

FIXTURES = Path(__file__).parent / "fixtures"
EXPECT = re.compile(r"expect\[([A-Za-z0-9,\s]+)\]")


def fixture_files() -> list[Path]:
    return sorted(p for p in FIXTURES.rglob("*") if p.is_file() and p.suffix in EXTENSIONS)


def expected(path: Path) -> list[tuple[str, int]]:
    sidecar = path.with_name(path.name + ".expect")
    out: list[tuple[str, int]] = []
    if sidecar.exists():
        for line in sidecar.read_text(encoding="utf-8").splitlines():
            if line.strip():
                rule, lineno = line.split()
                out.append((rule, int(lineno)))
        return sorted(out)
    for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        for m in EXPECT.finditer(line):
            for rid in m.group(1).split(","):
                out.append((rid.strip().upper(), lineno))
    return sorted(out)


def found(path: Path) -> list[tuple[str, int]]:
    return sorted((f.rule.id, f.line) for f in findings_for(str(path), path.read_bytes()))


@pytest.mark.parametrize("path", fixture_files(), ids=lambda p: p.relative_to(FIXTURES).as_posix())
def test_fixture_findings_match_expectations(path: Path) -> None:
    assert found(path) == expected(path)


@pytest.mark.parametrize("rule_id", sorted(RULES))
def test_every_rule_has_positive_and_negative_fixtures(rule_id: str) -> None:
    rule_dir = FIXTURES / "rules" / rule_id.lower()
    bad = [p for p in (rule_dir / "bad").iterdir() if p.suffix in EXTENSIONS]
    good = [p for p in (rule_dir / "good").iterdir() if p.suffix in EXTENSIONS]
    assert bad and good
    assert any(rule_id == r for p in bad for r, _ in expected(p)), "no positive case for the rule"
    for p in good:
        assert expected(p) == [], f"{p.name} is a negative fixture and must expect nothing"


def test_limits_fixtures_document_false_negatives() -> None:
    files = [p for p in (FIXTURES / "limits").iterdir() if p.suffix in EXTENSIONS]
    assert files
    for p in files:
        assert found(p) == []


def test_columns_point_at_the_construct() -> None:
    path = FIXTURES / "rules" / "pgm003" / "bad" / "EmptyIn.java"
    line = path.read_text(encoding="utf-8").splitlines()[7]
    finding = findings_for(str(path), path.read_bytes())[0]
    assert finding.line == 8
    assert line[finding.column - 1 : finding.column + 1] == "in"


def test_finding_inside_concatenation_maps_to_second_literal() -> None:
    path = FIXTURES / "rules" / "pgm002" / "bad" / "OptionalFilter.java"
    lines = path.read_text(encoding="utf-8").splitlines()
    hits = [f for f in findings_for(str(path), path.read_bytes()) if f.line == 35]
    assert len(hits) == 1
    assert lines[34][hits[0].column - 1] == "?"

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from pg_migration_lint import __version__
from pg_migration_lint.cli import main
from pg_migration_lint.rules import RULES

ROOT = Path(__file__).resolve().parent.parent
FIX = Path(__file__).parent / "fixtures" / "rules"

ERROR_FILE = FIX / "pgm003" / "bad" / "empty_in.sql"  # errors only
WARNING_FILE = FIX / "pgm002" / "bad" / "optional_filter.sql"  # one warning
INFO_FILE = FIX / "pgm007" / "bad" / "application.yml"  # info only
CLEAN_DIR = FIX / "pgm005" / "good"
MIXED_FILE = FIX / "pgm006" / "bad" / "changelog.yaml"  # PGM003, PGM005, PGM006


def run(capsys, *args: str) -> tuple[int, str, str]:
    code = main([str(a) for a in args])
    captured = capsys.readouterr()
    return code, captured.out, captured.err


def test_default_fails_on_error(capsys):
    code, out, _ = run(capsys, ERROR_FILE)
    assert code == 1
    assert "PGM003 [error]" in out


def test_warning_does_not_fail_by_default(capsys):
    code, out, _ = run(capsys, WARNING_FILE)
    assert code == 0
    assert "PGM002 [warning]" in out


def test_fail_on_warning(capsys):
    assert run(capsys, "--fail-on", "warning", WARNING_FILE)[0] == 1
    assert run(capsys, "--fail-on", "warning", INFO_FILE)[0] == 0


def test_fail_on_info(capsys):
    assert run(capsys, INFO_FILE)[0] == 0
    assert run(capsys, "--fail-on", "info", INFO_FILE)[0] == 1


def test_fail_on_never(capsys):
    assert run(capsys, "--fail-on", "never", ERROR_FILE)[0] == 0


def test_clean_directory(capsys):
    code, out, _ = run(capsys, CLEAN_DIR)
    assert code == 0
    assert "No findings in 1 file scanned." in out


def test_text_output_has_location_fix_and_book_pointer(capsys):
    _, out, _ = run(capsys, ERROR_FILE)
    first = out.splitlines()[0]
    assert first.startswith(f"{os.path.relpath(ERROR_FILE)}:1:")
    assert "    fix: " in out
    assert 'learn more: PostgreSQL Migration Survival Guide for Java Teams: Chapter 4, "SQL and query traps"' in out
    assert out.rstrip().endswith("in 1 file scanned.")


def test_select_and_ignore(capsys):
    _, out, _ = run(capsys, "--format", "json", "--select", "PGM006", MIXED_FILE)
    assert {f["rule"] for f in json.loads(out)["findings"]} == {"PGM006"}
    _, out, _ = run(capsys, "--format", "json", "--select", "pgm003,PGM005", MIXED_FILE)
    assert {f["rule"] for f in json.loads(out)["findings"]} == {"PGM003", "PGM005"}
    _, out, _ = run(capsys, "--format", "json", "--ignore", "PGM003", "--ignore", "PGM005", MIXED_FILE)
    assert {f["rule"] for f in json.loads(out)["findings"]} == {"PGM006"}


def test_ignoring_the_only_error_changes_exit_code(capsys):
    assert run(capsys, MIXED_FILE)[0] == 1
    assert run(capsys, "--ignore", "PGM003,PGM005", MIXED_FILE)[0] == 0


def test_unknown_rule_is_usage_error(capsys):
    code, _, err = run(capsys, "--select", "PGM999", ERROR_FILE)
    assert code == 2
    assert "unknown rule id: PGM999" in err


def test_missing_path_is_usage_error(capsys):
    code, _, err = run(capsys, "does/not/exist")
    assert code == 2
    assert "no such file or directory" in err


def test_json_output(capsys):
    code, out, _ = run(capsys, "--format", "json", MIXED_FILE)
    assert code == 1
    doc = json.loads(out)
    assert doc["version"] == __version__
    assert doc["files_scanned"] == 1
    assert doc["summary"] == {"error": 2, "warning": 1, "info": 0}
    f = doc["findings"][0]
    assert set(f) == {"rule", "name", "severity", "path", "line", "column", "message", "fix", "learn_more"}
    assert [x["line"] for x in doc["findings"]] == sorted(x["line"] for x in doc["findings"])


def test_sarif_output(capsys):
    code, out, _ = run(capsys, "--format", "sarif", MIXED_FILE)
    assert code == 1
    doc = json.loads(out)
    assert doc["version"] == "2.1.0"
    assert doc["$schema"].endswith("sarif-2.1.0.json")
    run0 = doc["runs"][0]
    driver = run0["tool"]["driver"]
    assert driver["name"] == "pg-migration-lint"
    assert driver["version"] == __version__
    rule_ids = [r["id"] for r in driver["rules"]]
    assert rule_ids == sorted(RULES)
    for r in driver["rules"]:
        assert r["defaultConfiguration"]["level"] in ("error", "warning", "note")
        assert "Learn more" in r["help"]["text"]
        assert r["help"]["markdown"]
    levels = {res["ruleId"]: res["level"] for res in run0["results"]}
    assert levels == {"PGM003": "error", "PGM005": "error", "PGM006": "warning"}
    for res in run0["results"]:
        assert rule_ids[res["ruleIndex"]] == res["ruleId"]
        loc = res["locations"][0]["physicalLocation"]
        assert loc["artifactLocation"]["uriBaseId"] == "%SRCROOT%"
        assert not loc["artifactLocation"]["uri"].startswith("/")
        assert "\\" not in loc["artifactLocation"]["uri"]
        assert loc["region"]["startLine"] >= 1 and loc["region"]["startColumn"] >= 1
    assert run0["originalUriBaseIds"]["%SRCROOT%"]["uri"].startswith("file://")


def test_sarif_info_level_is_note(capsys):
    _, out, _ = run(capsys, "--format", "sarif", INFO_FILE)
    results = json.loads(out)["runs"][0]["results"]
    assert results and {r["level"] for r in results} == {"note"}


def test_sarif_without_findings_is_valid(capsys):
    code, out, _ = run(capsys, "--format", "sarif", CLEAN_DIR)
    assert code == 0
    assert json.loads(out)["runs"][0]["results"] == []


def test_output_file(capsys, tmp_path):
    target = tmp_path / "report.sarif"
    code, out, _ = run(capsys, "--format", "sarif", "--output", target, ERROR_FILE)
    assert code == 1
    assert out == ""
    assert json.loads(target.read_text(encoding="utf-8"))["version"] == "2.1.0"


def test_exclude(capsys):
    code, out, _ = run(capsys, "--exclude", "*.sql", FIX / "pgm003" / "bad")
    assert code == 1  # EmptyIn.java still scanned
    assert "empty_in.sql" not in out
    code, out, _ = run(capsys, "--exclude", "bad", FIX / "pgm003")
    assert code == 0


def test_directory_walk_skips_build_dirs(capsys, tmp_path):
    (tmp_path / "target").mkdir()
    (tmp_path / "target" / "gen.sql").write_text("select * from t where id in ();\n")
    (tmp_path / "q.sql").write_text("select * from t where id in ();\n")
    code, out, _ = run(capsys, "--format", "json", tmp_path)
    doc = json.loads(out)
    assert doc["files_scanned"] == 1
    assert [f["path"].endswith("q.sql") for f in doc["findings"]] == [True]


def test_list_rules(capsys):
    code, out, _ = run(capsys, "--list-rules")
    assert code == 0
    for rid in RULES:
        assert rid in out


def test_version(capsys):
    with pytest.raises(SystemExit) as exc:
        main(["--version"])
    assert exc.value.code == 0
    assert __version__ in capsys.readouterr().out


def test_module_entry_point():
    env = dict(os.environ, PYTHONPATH=str(ROOT / "src"))
    proc = subprocess.run(
        [sys.executable, "-m", "pg_migration_lint", "--format", "json", str(ERROR_FILE)],
        capture_output=True, text=True, env=env, check=False,
    )
    assert proc.returncode == 1
    assert json.loads(proc.stdout)["summary"]["error"] == 2

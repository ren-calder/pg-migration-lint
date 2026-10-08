"""Text, JSON and SARIF 2.1.0 output."""

from __future__ import annotations

import json
import os
from pathlib import Path

from . import __version__
from .rules import BOOK_TITLE, RULES, Rule
from .scanner import Finding

SARIF_SCHEMA = "https://json.schemastore.org/sarif-2.1.0.json"
SARIF_LEVEL = {"error": "error", "warning": "warning", "info": "note"}
PROBLEM_SEVERITY = {"error": "error", "warning": "warning", "info": "recommendation"}


def _summary(findings: list[Finding]) -> dict[str, int]:
    counts = {"error": 0, "warning": 0, "info": 0}
    for f in findings:
        counts[f.severity] += 1
    return counts


def format_text(findings: list[Finding], files_scanned: int) -> str:
    lines: list[str] = []
    for f in findings:
        lines.append(f"{f.path}:{f.line}:{f.column}: {f.rule.id} [{f.severity}] {f.message}")
        lines.append(f"    fix: {f.rule.fix}")
        lines.append(f"    learn more: {f.rule.learn_more}")
    counts = _summary(findings)
    files = "file" if files_scanned == 1 else "files"
    if findings:
        lines.append(
            f"Found {len(findings)} finding{'s' if len(findings) != 1 else ''} "
            f"({counts['error']} error, {counts['warning']} warning, {counts['info']} info) "
            f"in {files_scanned} {files} scanned."
        )
    else:
        lines.append(f"No findings in {files_scanned} {files} scanned.")
    return "\n".join(lines) + "\n"


def format_json(findings: list[Finding], files_scanned: int) -> str:
    doc = {
        "tool": "pg-migration-lint",
        "version": __version__,
        "files_scanned": files_scanned,
        "summary": _summary(findings),
        "findings": [
            {
                "rule": f.rule.id,
                "name": f.rule.name,
                "severity": f.severity,
                "path": f.path.replace(os.sep, "/"),
                "line": f.line,
                "column": f.column,
                "message": f.message,
                "fix": f.rule.fix,
                "learn_more": f.rule.learn_more,
            }
            for f in findings
        ],
    }
    return json.dumps(doc, indent=2, ensure_ascii=False) + "\n"


def _sarif_rule(rule: Rule) -> dict:
    refs = "\n".join(f"- {r.render()}" for r in rule.refs)
    markdown = (
        f"**{rule.title}**\n\n{rule.why}\n\n**Fix:** {rule.fix}\n\n"
        f"**Learn more:** *{BOOK_TITLE}*\n{refs}\n\n**Evidence:** {rule.evidence}\n"
    )
    return {
        "id": rule.id,
        "name": rule.name,
        "shortDescription": {"text": rule.title},
        "fullDescription": {"text": rule.why},
        "help": {
            "text": f"{rule.why}\nFix: {rule.fix}\nLearn more: {rule.learn_more}",
            "markdown": markdown,
        },
        "defaultConfiguration": {"level": SARIF_LEVEL[rule.severity]},
        "properties": {
            "tags": ["postgresql", "migration", "correctness"],
            "precision": "high",
            "problem.severity": PROBLEM_SEVERITY[rule.severity],
        },
    }


def _artifact(path: str) -> dict:
    if os.path.isabs(path):
        return {"uri": Path(path).as_uri()}
    return {"uri": path.replace(os.sep, "/"), "uriBaseId": "%SRCROOT%"}


def format_sarif(findings: list[Finding], files_scanned: int) -> str:
    rule_ids = sorted(RULES)
    index = {rid: i for i, rid in enumerate(rule_ids)}
    results = []
    for f in findings:
        results.append({
            "ruleId": f.rule.id,
            "ruleIndex": index[f.rule.id],
            "level": SARIF_LEVEL[f.severity],
            "message": {"text": f.message},
            "locations": [{
                "physicalLocation": {
                    "artifactLocation": _artifact(f.path),
                    "region": {"startLine": f.line, "startColumn": f.column},
                }
            }],
        })
    cwd_uri = Path(os.getcwd()).as_uri().rstrip("/") + "/"
    doc = {
        "$schema": SARIF_SCHEMA,
        "version": "2.1.0",
        "runs": [{
            "tool": {
                "driver": {
                    "name": "pg-migration-lint",
                    "version": __version__,
                    "semanticVersion": __version__,
                    "rules": [_sarif_rule(RULES[rid]) for rid in rule_ids],
                }
            },
            "originalUriBaseIds": {"%SRCROOT%": {"uri": cwd_uri}},
            "columnKind": "unicodeCodePoints",
            "results": results,
            "properties": {"filesScanned": files_scanned},
        }],
    }
    return json.dumps(doc, indent=2, ensure_ascii=False) + "\n"


FORMATTERS = {"text": format_text, "json": format_json, "sarif": format_sarif}

"""File discovery, dispatch to the per-language scanners, suppressions."""

from __future__ import annotations

import fnmatch
import os
import re
import sys
import xml.parsers.expat
from dataclasses import dataclass

from .base import RawFinding
from .config import stringtype_findings
from .jvm import scan_jvm
from .liquibase import scan_liquibase_json, scan_liquibase_xml, scan_liquibase_yaml
from .rules import RULES, Rule
from .sql import SqlText, check_sql

EXTENSIONS = {".java", ".kt", ".sql", ".xml", ".yaml", ".yml", ".json", ".properties"}
DEFAULT_EXCLUDED_DIRS = {
    ".git", ".hg", ".svn", "node_modules", "target", "build", "out", ".gradle", ".idea",
    ".mvn", ".venv", "venv", "__pycache__", ".tox", "dist", ".pytest_cache",
}
MAX_FILE_BYTES = 5 * 1024 * 1024

_SUPPRESS = re.compile(r"pgmig-lint:\s*ignore\[([A-Za-z0-9,\s]+)\]")
_COMMENT_INTRO = ("//", "--", "#", "/*", "<!--")


@dataclass
class Finding:
    rule: Rule
    path: str
    line: int
    column: int
    message: str

    @property
    def severity(self) -> str:
        return self.rule.severity


class LineIndex:
    def __init__(self, text: str):
        self.text = text
        self.starts = [0]
        for m in re.finditer("\n", text):
            self.starts.append(m.end())

    def linecol(self, offset: int) -> tuple[int, int]:
        lo, hi = 0, len(self.starts) - 1
        while lo < hi:
            mid = (lo + hi + 1) // 2
            if self.starts[mid] <= offset:
                lo = mid
            else:
                hi = mid - 1
        return lo + 1, offset - self.starts[lo] + 1

    def line_text(self, line: int) -> str:
        start = self.starts[line - 1]
        end = self.starts[line] - 1 if line < len(self.starts) else len(self.text)
        return self.text[start:end]


def suppressed_rules(line_text: str) -> set[str]:
    out: set[str] = set()
    for m in _SUPPRESS.finditer(line_text):
        before = line_text[: m.start()]
        if not any(intro in before for intro in _COMMENT_INTRO):
            continue
        for part in m.group(1).split(","):
            if part.strip():
                out.add(part.strip().upper())
    return out


def _blank_regions(text: str, pattern: re.Pattern[str]) -> str:
    def repl(m: re.Match[str]) -> str:
        return "".join("\n" if c == "\n" else " " for c in m.group(0))

    return pattern.sub(repl, text)


_XML_COMMENT = re.compile(r"<!--.*?-->", re.S)
_PROPS_COMMENT = re.compile(r"(?m)^[ \t]*[#!].*$")
_YAML_COMMENT = re.compile(r"(?m)(?:^|(?<=\s))#.*$")


def scan_text(path: str, data: bytes, enabled: set[str] | None = None) -> list[RawFinding]:
    """Scan one file's contents. ``path`` is only used for its extension."""
    ext = os.path.splitext(path)[1].lower()
    text = data.decode("utf-8", errors="replace")

    def on(rule: str) -> bool:
        return enabled is None or rule in enabled

    raw: list[RawFinding] = []
    if ext in (".java", ".kt"):
        raw = scan_jvm(text, kotlin=ext == ".kt", enabled=enabled)
    elif ext == ".sql":
        st = SqlText(text, origin="sqlfile", context="sqlfile", bare_q=True)
        raw = [RawFinding(h.rule, h.index, h.message) for h in check_sql(st, enabled)]
    elif ext == ".xml":
        if "databaseChangeLog" in text:
            try:
                raw.extend(scan_liquibase_xml(data, text, enabled))
            except xml.parsers.expat.ExpatError as exc:
                print(f"pgmig-lint: warning: could not parse {path}: {exc}", file=sys.stderr)
        if on("PGM007"):
            raw.extend(stringtype_findings(_blank_regions(text, _XML_COMMENT), "xml"))
    elif ext in (".yaml", ".yml"):
        raw.extend(scan_liquibase_yaml(text, enabled))
        if on("PGM007"):
            raw.extend(stringtype_findings(_blank_regions(text, _YAML_COMMENT), "yaml"))
    elif ext == ".json":
        raw.extend(scan_liquibase_json(text, enabled))
        if on("PGM007"):
            raw.extend(stringtype_findings(text, "json"))
    elif ext == ".properties":
        if on("PGM007"):
            raw.extend(stringtype_findings(_blank_regions(text, _PROPS_COMMENT), "properties"))
    return raw


def findings_for(display_path: str, data: bytes, enabled: set[str] | None = None) -> list[Finding]:
    text = data.decode("utf-8", errors="replace")
    index = LineIndex(text)
    seen: set[tuple[str, int]] = set()
    out: list[Finding] = []
    for rf in scan_text(display_path, data, enabled):
        if enabled is not None and rf.rule not in enabled:
            continue
        key = (rf.rule, rf.offset)
        if key in seen:
            continue
        seen.add(key)
        line, col = index.linecol(rf.offset)
        if rf.rule in suppressed_rules(index.line_text(line)):
            continue
        out.append(Finding(RULES[rf.rule], display_path, line, col, rf.message))
    out.sort(key=lambda f: (f.line, f.column, f.rule.id))
    return out


def _excluded(path: str, patterns: list[str]) -> bool:
    norm = path.replace(os.sep, "/")
    base = os.path.basename(path)
    return any(fnmatch.fnmatch(norm, p) or fnmatch.fnmatch(base, p) for p in patterns)


def iter_files(paths: list[str], exclude: list[str] | None = None):
    exclude = exclude or []
    for root in paths:
        if os.path.isfile(root):
            yield root
            continue
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = sorted(
                d for d in dirnames
                if d not in DEFAULT_EXCLUDED_DIRS and not _excluded(os.path.join(dirpath, d), exclude)
            )
            for name in sorted(filenames):
                full = os.path.join(dirpath, name)
                if os.path.splitext(name)[1].lower() not in EXTENSIONS:
                    continue
                if _excluded(full, exclude):
                    continue
                yield full


def display_path(path: str) -> str:
    try:
        rel = os.path.relpath(path)
    except ValueError:
        return path
    if rel.startswith(".." + os.sep) or rel == "..":
        return os.path.abspath(path)
    return rel


def scan_paths(
    paths: list[str], enabled: set[str] | None = None, exclude: list[str] | None = None
) -> tuple[list[Finding], int]:
    findings: list[Finding] = []
    count = 0
    for path in iter_files(paths, exclude):
        try:
            if os.path.getsize(path) > MAX_FILE_BYTES:
                continue
            with open(path, "rb") as fh:
                data = fh.read()
        except OSError as exc:
            print(f"pgmig-lint: warning: cannot read {path}: {exc}", file=sys.stderr)
            continue
        count += 1
        findings.extend(findings_for(display_path(path), data, enabled))
    findings.sort(key=lambda f: (f.path, f.line, f.column, f.rule.id))
    return findings, count

"""PGM007: pgJDBC ``stringtype=unspecified`` in configuration and code.

Only configuration shapes are matched (a URL parameter, a property/YAML key,
a key/value pair, the data-source setter), so prose that merely mentions the
setting, such as a log message or a comment, is not reported.
"""

from __future__ import annotations

import re

from .base import RawFinding

PGM007_MESSAGE = (
    "pgJDBC stringtype=unspecified sends setString values untyped so the server infers their "
    "type (tested: setString then resolves against bigint and jsonb). It applies to every "
    "setString on the connection and hides setter/column mismatches that would otherwise fail "
    "with 42883."
)

URL_PARAM = re.compile(r"(?i)(?<=[?&;])stringtype=unspecified(?![\w-])")
PROPERTIES_KEY = re.compile(r"(?im)^[ \t]*[\w.\-\[\]]*?\bstringtype[ \t]*[=:][ \t]*unspecified[ \t]*$")
YAML_KEY = re.compile(
    r"(?im)^[ \t]*(?:-[ \t]+)?[\"']?stringtype[\"']?[ \t]*:[ \t]*[\"']?unspecified[\"']?[ \t]*$"
)
XML_PAIR = re.compile(r"(?i)name\s*=\s*[\"']stringtype[\"']\s+value\s*=\s*[\"']unspecified[\"']")
JSON_PAIR = re.compile(r"(?i)\"stringtype\"\s*:\s*\"unspecified\"")
CODE_PAIR = re.compile(r"(?i)[\"']stringtype[\"']\s*(?:,|\bto\b)\s*[\"']unspecified[\"']")
CODE_SETTER = re.compile(r"\bsetStringType\s*\(\s*\"unspecified\"\s*\)")
LITERAL_WHOLE = re.compile(r"(?i)^stringtype=unspecified(?:$|[&;])")

PATTERNS = {
    "properties": (URL_PARAM, PROPERTIES_KEY),
    "yaml": (URL_PARAM, YAML_KEY),
    "xml": (URL_PARAM, XML_PAIR),
    "json": (URL_PARAM, JSON_PAIR),
    "code": (CODE_PAIR, CODE_SETTER),
}


def stringtype_findings(text: str, kind: str) -> list[RawFinding]:
    """Scan text whose comments are already blanked. One finding per line."""
    out: list[RawFinding] = []
    seen_lines: set[int] = set()
    hits: list[int] = []
    for pat in PATTERNS[kind]:
        for m in pat.finditer(text):
            start = m.start()
            sub = m.group(0)
            low = sub.lower()
            if "stringtype" in low and not low.startswith("stringtype"):
                start += low.index("stringtype")
            hits.append(start)
    for start in sorted(hits):
        line = text.count("\n", 0, start)
        if line in seen_lines:
            continue
        seen_lines.add(line)
        out.append(RawFinding("PGM007", start, PGM007_MESSAGE))
    return out


def literal_stringtype(content: str) -> int | None:
    """Index of a stringtype=unspecified parameter inside a string literal's content."""
    m = URL_PARAM.search(content)
    if m:
        return m.start()
    m = LITERAL_WHOLE.match(content)
    if m:
        return 0
    return None

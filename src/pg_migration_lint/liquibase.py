"""Liquibase changelogs (XML, YAML, JSON).

* PGM006: a change set whose preconditions use onFail/onError="MARK_RAN" and
  whose only real guard is a negated existence check by name
  (``not indexExists``, ``not tableExists``, ...). Liquibase case 8 in the
  book's verification shows a same-named but different object makes the
  change set MARK_RAN and the real change is never applied.
* SQL embedded in ``<sql>``, ``<sqlCheck>``, ``<createView>``, ``<where>``
  and ``<rollback>`` is checked with the SQL-text rules.

Change sets or changes limited to other databases with ``dbms=`` are skipped.
"""

from __future__ import annotations

import json
import re
import xml.parsers.expat
from dataclasses import dataclass, field

from .base import RawFinding
from .sql import SqlText, check_sql

EXISTENCE_CHECKS = {
    "tableExists": ("tableName",),
    "columnExists": ("tableName", "columnName"),
    "indexExists": ("indexName", "tableName", "columnNames"),
    "viewExists": ("viewName",),
    "sequenceExists": ("sequenceName",),
    "foreignKeyConstraintExists": ("foreignKeyName", "foreignKeyTableName"),
    "primaryKeyExists": ("primaryKeyName", "tableName"),
    "uniqueConstraintExists": ("constraintName", "tableName"),
}
# Checks that can prove more than a name; their presence disables PGM006.
PROVING_CHECKS = {"sqlCheck", "customPrecondition"}
SQL_ELEMENTS = {"sql", "sqlCheck", "createView", "where", "rollback"}
SQL_YAML_KEYS = {"sql", "selectQuery", "where"}


def applies_to_postgresql(dbms: str | None) -> bool:
    if not dbms:
        return True
    if "${" in dbms:
        return True
    items = [x.strip().lower() for x in dbms.split(",") if x.strip()]
    if "none" in items or "!postgresql" in items:
        return False
    positive = [x for x in items if not x.startswith("!")]
    if not positive:
        return True
    return "postgresql" in positive or "all" in positive


def _object_name(check: str, attrs: dict[str, str]) -> str:
    for key in EXISTENCE_CHECKS.get(check, ()):
        if attrs.get(key):
            if check == "columnExists" and key == "tableName" and attrs.get("columnName"):
                return f"{attrs['tableName']}.{attrs['columnName']}"
            return str(attrs[key])
    return ""


def _mark_ran_message(on_fail: bool, check: str, name: str) -> str:
    what = f"not {check} {name}".strip()
    if on_fail:
        return (
            f"onFail=\"MARK_RAN\" guarded only by a name check (`{what}`): if an object with that "
            "name already exists but is not what this change set creates, Liquibase records the "
            "change set as MARK_RAN and never retries it, so the real change is skipped "
            "permanently (tested on Liquibase 5.0.4)."
        )
    return (
        f"onError=\"MARK_RAN\" guarded only by a name check (`{what}`): if the check errors, "
        "Liquibase records the change set as executed and does not retry it (Liquibase docs); "
        "a name check does not prove the intended object exists."
    )


def _evaluate_preconditions(
    on_fail: str | None,
    on_error: str | None,
    checks: list[tuple[str, dict[str, str], int]],
) -> str | None:
    """checks: (element name, attributes, number of enclosing `not`)."""
    mark_fail = (on_fail or "").strip().upper() == "MARK_RAN"
    mark_error = (on_error or "").strip().upper() == "MARK_RAN"
    if not (mark_fail or mark_error):
        return None
    if any(name in PROVING_CHECKS for name, _, _ in checks):
        return None
    for name, attrs, nots in checks:
        if name in EXISTENCE_CHECKS and nots % 2 == 1:
            return _mark_ran_message(mark_fail, name, _object_name(name, attrs))
    return None


# ---------------------------------------------------------------------------
# XML
# ---------------------------------------------------------------------------


@dataclass
class XEl:
    name: str
    attrs: dict[str, str]
    start_b: int
    end_b: int | None = None
    children: list["XEl"] = field(default_factory=list)
    parent: "XEl | None" = None


def _local(name: str) -> str:
    return name.rsplit(":", 1)[-1].rsplit(" ", 1)[-1]


def parse_xml(data: bytes) -> XEl | None:
    parser = xml.parsers.expat.ParserCreate()
    try:
        parser.SetParamEntityParsing(xml.parsers.expat.XML_PARAM_ENTITY_PARSING_NEVER)
    except AttributeError:  # pragma: no cover
        pass
    stack: list[XEl] = []
    root: list[XEl] = []

    def start(name: str, attrs: dict[str, str]) -> None:
        el = XEl(_local(name), {_local(k): v for k, v in attrs.items()}, parser.CurrentByteIndex)
        if stack:
            el.parent = stack[-1]
            stack[-1].children.append(el)
        else:
            root.append(el)
        stack.append(el)

    def end(name: str) -> None:
        el = stack.pop()
        el.end_b = parser.CurrentByteIndex

    parser.StartElementHandler = start
    parser.EndElementHandler = end
    parser.Parse(data, True)
    return root[0] if root else None


class _ByteMap:
    """Maps byte offsets of UTF-8 data to character offsets of the decoded text."""

    def __init__(self, data: bytes, text: str):
        self.identity = len(data) == len(text)
        self.table: list[int] = []
        if not self.identity:
            table = []
            for ci, ch in enumerate(text):
                width = len(ch.encode("utf-8", errors="replace"))
                table.extend([ci] * width)
            table.append(len(text))
            self.table = table

    def __call__(self, b: int) -> int:
        if self.identity:
            return b
        if b < len(self.table):
            return self.table[b]
        return self.table[-1] if self.table else b


_ENTITY = re.compile(r"&(#x[0-9A-Fa-f]+|#[0-9]+|lt|gt|amp|quot|apos);")
_ENTITY_CHARS = {"lt": "<", "gt": ">", "amp": "&", "quot": '"', "apos": "'"}


def _sanitize_xml_content(raw: str) -> str:
    """Blank markup, CDATA delimiters and comments; decode entities in place.

    Output has the same length as the input, so offsets stay aligned.
    """
    out: list[str] = []
    i = 0
    n = len(raw)

    def blank(s: str) -> str:
        return "".join("\n" if c == "\n" else " " for c in s)

    while i < n:
        if raw.startswith("<![CDATA[", i):
            end = raw.find("]]>", i + 9)
            end = n if end < 0 else end
            out.append(" " * 9)
            out.append(raw[i + 9 : end])
            if end < n:
                out.append("   ")
            i = end + 3
            continue
        if raw.startswith("<!--", i):
            end = raw.find("-->", i + 4)
            end = n if end < 0 else end + 3
            out.append(blank(raw[i:end]))
            i = end
            continue
        c = raw[i]
        if c == "<":
            end = raw.find(">", i)
            end = n if end < 0 else end + 1
            out.append(blank(raw[i:end]))
            i = end
            continue
        if c == "&":
            m = _ENTITY.match(raw, i)
            if m:
                ent = m.group(1)
                if ent.startswith("#x"):
                    ch = chr(int(ent[2:], 16))
                elif ent.startswith("#"):
                    ch = chr(int(ent[1:]))
                else:
                    ch = _ENTITY_CHARS[ent]
                out.append(ch + " " * (len(m.group(0)) - 1))
                i = m.end()
                continue
        out.append(c)
        i += 1
    return "".join(out)


def _start_tag_end(text: str, start: int) -> int:
    quote = None
    for k in range(start, len(text)):
        c = text[k]
        if quote:
            if c == quote:
                quote = None
        elif c in "\"'":
            quote = c
        elif c == ">":
            return k + 1
    return len(text)


def _iter(el: XEl):
    yield el
    for c in el.children:
        yield from _iter(c)


def _xml_applies(el: XEl) -> bool:
    node: XEl | None = el
    while node is not None:
        if not applies_to_postgresql(node.attrs.get("dbms")):
            return False
        node = node.parent
    return True


def scan_liquibase_xml(data: bytes, text: str, enabled: set[str] | None = None) -> list[RawFinding]:
    root = parse_xml(data)
    if root is None or root.name != "databaseChangeLog":
        return []
    bmap = _ByteMap(data, text)
    out: list[RawFinding] = []

    def on(rule: str) -> bool:
        return enabled is None or rule in enabled

    if on("PGM006"):
        for el in _iter(root):
            if el.name != "changeSet" or not _xml_applies(el):
                continue
            for pc in el.children:
                if pc.name != "preConditions":
                    continue
                checks: list[tuple[str, dict[str, str], int]] = []

                def walk(node: XEl, nots: int) -> None:
                    for child in node.children:
                        checks.append((child.name, child.attrs, nots))
                        walk(child, nots + (1 if child.name == "not" else 0))

                walk(pc, 0)
                msg = _evaluate_preconditions(pc.attrs.get("onFail"), pc.attrs.get("onError"), checks)
                if msg:
                    out.append(RawFinding("PGM006", bmap(pc.start_b), msg))

    sql_rules = {"PGM003", "PGM005", "PGM008"}
    if enabled is None or enabled & sql_rules:
        for el in _iter(root):
            if el.name not in SQL_ELEMENTS or not _xml_applies(el):
                continue
            if el.name == "rollback" and el.children:
                continue
            start_c = bmap(el.start_b)
            content_start = _start_tag_end(text, start_c)
            if el.end_b is None:
                continue
            content_end = bmap(el.end_b)
            if content_end <= content_start:
                continue  # self-closing
            content = _sanitize_xml_content(text[content_start:content_end])
            st = SqlText(content, origin="liquibase", context="liquibase", bare_q=False)
            for hit in check_sql(st, enabled):
                if hit.rule in sql_rules:
                    out.append(RawFinding(hit.rule, content_start + hit.index, hit.message))
    return out


# ---------------------------------------------------------------------------
# YAML (block style only; no YAML library needed)
# ---------------------------------------------------------------------------

_YAML_NODE = re.compile(
    r"^(?P<indent>[ ]*)(?P<dashes>(?:-[ ]+)*)(?P<key>[A-Za-z_][\w.-]*)[ ]*:(?:[ ]+(?P<value>.*?))?[ ]*$"
)
_BLOCK_SCALAR = re.compile(r"^[|>][-+0-9]*$")


@dataclass
class YNode:
    line: int
    keycol: int
    key: str
    value: str
    offset: int  # character offset of the key
    value_offset: int
    parent: "YNode | None" = None
    children: list["YNode"] = field(default_factory=list)
    block: tuple[int, int] | None = None  # (first line, last line) of a block scalar


def _strip_yaml_comment(value: str) -> str:
    if not value:
        return value
    if value[0] in "\"'":
        return value
    m = re.search(r"(^|\s)#", value)
    return value[: m.start()].rstrip() if m else value


def _unquote(value: str) -> tuple[str, int]:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        return value[1:-1], 1
    return value, 0


def parse_yaml_nodes(text: str) -> list[YNode]:
    lines = text.split("\n")
    starts = [0]
    for ln in lines[:-1]:
        starts.append(starts[-1] + len(ln) + 1)
    nodes: list[YNode] = []
    stack: list[YNode] = []
    i = 0
    while i < len(lines):
        raw = lines[i].rstrip("\r")
        stripped = raw.strip()
        if not stripped or stripped.startswith("#") or stripped in ("---", "..."):
            i += 1
            continue
        m = _YAML_NODE.match(raw)
        if not m:
            i += 1
            continue
        keycol = len(m.group("indent")) + len(m.group("dashes"))
        value_raw = m.group("value") or ""
        value = _strip_yaml_comment(value_raw)
        value_col = m.start("value") if m.group("value") is not None else len(raw)
        node = YNode(i, keycol, m.group("key"), value, starts[i] + keycol, starts[i] + value_col)
        while stack and stack[-1].keycol >= keycol:
            stack.pop()
        if stack:
            node.parent = stack[-1]
            stack[-1].children.append(node)
        nodes.append(node)
        stack.append(node)
        i += 1
        if _BLOCK_SCALAR.match(value):
            first = i
            last = i - 1
            while i < len(lines):
                ln = lines[i].rstrip("\r")
                if ln.strip() == "":
                    i += 1
                    continue
                indent = len(ln) - len(ln.lstrip(" "))
                if indent <= keycol:
                    break
                last = i
                i += 1
            node.block = (first, last)
    return nodes


def _yaml_applies(node: YNode) -> bool:
    cur: YNode | None = node.parent
    while cur is not None:
        for child in cur.children:
            if child.key == "dbms" and not applies_to_postgresql(_unquote(child.value)[0]):
                return False
        cur = cur.parent
    return True


def _yaml_descendants(node: YNode, nots: int = 0):
    for child in node.children:
        yield child, nots
        yield from _yaml_descendants(child, nots + (1 if child.key == "not" else 0))


def scan_liquibase_yaml(text: str, enabled: set[str] | None = None) -> list[RawFinding]:
    if not re.search(r"(?m)^databaseChangeLog\s*:", text):
        return []
    nodes = parse_yaml_nodes(text)
    out: list[RawFinding] = []
    lines = text.split("\n")
    starts = [0]
    for ln in lines[:-1]:
        starts.append(starts[-1] + len(ln) + 1)

    def on(rule: str) -> bool:
        return enabled is None or rule in enabled

    if on("PGM006"):
        for node in nodes:
            if node.key != "preConditions" or node.parent is None or node.parent.key != "changeSet":
                continue
            if not _yaml_applies(node.parent) or not _yaml_applies(node):
                continue
            on_fail = on_error = None
            checks: list[tuple[str, dict[str, str], int]] = []
            for desc, nots in _yaml_descendants(node):
                if desc.key == "onFail":
                    on_fail = _unquote(desc.value)[0]
                elif desc.key == "onError":
                    on_error = _unquote(desc.value)[0]
                else:
                    attrs = {c.key: _unquote(c.value)[0] for c in desc.children}
                    checks.append((desc.key, attrs, nots))
            msg = _evaluate_preconditions(on_fail, on_error, checks)
            if msg:
                out.append(RawFinding("PGM006", node.offset, msg))

    sql_rules = {"PGM003", "PGM005", "PGM008"}
    if enabled is None or enabled & sql_rules:
        for node in nodes:
            if node.key not in SQL_YAML_KEYS or not _yaml_applies(node):
                continue
            if node.block is not None:
                first, last = node.block
                if last < first:
                    continue
                base = starts[first]
                end = starts[last] + len(lines[last])
                content, content_start = text[base:end], base
            elif node.value:
                content, shift = _unquote(node.value)
                content_start = node.value_offset + shift
            else:
                continue
            st = SqlText(content, origin="liquibase", context="liquibase", bare_q=False)
            for hit in check_sql(st, enabled):
                if hit.rule in sql_rules:
                    out.append(RawFinding(hit.rule, content_start + hit.index, hit.message))
    return out


# ---------------------------------------------------------------------------
# JSON
# ---------------------------------------------------------------------------

_JSON_PRECOND = re.compile(r'"preConditions"\s*:')
_JSON_SQL = re.compile(r'"(sql|selectQuery|where)"\s*:\s*"')
_JSON_ESC = {'"': '"', "\\": "\\", "/": "/", "b": "\b", "f": "\f", "n": "\n", "r": "\r", "t": "\t"}


def _json_string_at(text: str, i: int) -> tuple[str, list[int]]:
    """Decode the JSON string whose opening quote is at text[i]."""
    chars: list[str] = []
    pos: list[int] = []
    j = i + 1
    n = len(text)
    while j < n:
        c = text[j]
        if c == '"':
            break
        if c == "\\" and j + 1 < n:
            e = text[j + 1]
            if e == "u":
                try:
                    chars.append(chr(int(text[j + 2 : j + 6], 16)))
                except ValueError:
                    chars.append("?")
                pos.append(j)
                j += 6
                continue
            chars.append(_JSON_ESC.get(e, e))
            pos.append(j)
            j += 2
            continue
        chars.append(c)
        pos.append(j)
        j += 1
    return "".join(chars), pos


def scan_liquibase_json(text: str, enabled: set[str] | None = None) -> list[RawFinding]:
    if '"databaseChangeLog"' not in text:
        return []
    try:
        doc = json.loads(text)
    except ValueError:
        return []
    out: list[RawFinding] = []

    def on(rule: str) -> bool:
        return enabled is None or rule in enabled

    if on("PGM006"):
        # Every "preConditions" key in document order, paired with its text offset.
        offsets = [m.start() for m in _JSON_PRECOND.finditer(text)]
        found: list[tuple[object, bool, bool]] = []  # (value, in_changeset, applies)

        def visit(obj: object, parent_key: str | None, applies: bool) -> None:
            if isinstance(obj, dict):
                here = applies and applies_to_postgresql(obj.get("dbms") if isinstance(obj.get("dbms"), str) else None)
                for k, v in obj.items():
                    if k == "preConditions":
                        found.append((v, parent_key == "changeSet", here))
                    visit(v, k, here)
            elif isinstance(obj, list):
                for v in obj:
                    visit(v, parent_key, applies)

        visit(doc, None, True)

        def collect(obj: object, nots: int, acc: dict) -> None:
            items: list[tuple[str, object]] = []
            if isinstance(obj, dict):
                items = list(obj.items())
            elif isinstance(obj, list):
                for v in obj:
                    collect(v, nots, acc)
                return
            for k, v in items:
                if k == "onFail" and isinstance(v, str):
                    acc["onFail"] = v
                elif k == "onError" and isinstance(v, str):
                    acc["onError"] = v
                else:
                    attrs = {ak: str(av) for ak, av in v.items()} if isinstance(v, dict) else {}
                    acc["checks"].append((k, attrs, nots))
                    if isinstance(v, (dict, list)):
                        collect(v, nots + (1 if k == "not" else 0), acc)

        for idx, (value, in_changeset, applies) in enumerate(found):
            if not in_changeset or not applies or idx >= len(offsets):
                continue
            acc: dict = {"onFail": None, "onError": None, "checks": []}
            collect(value, 0, acc)
            msg = _evaluate_preconditions(acc["onFail"], acc["onError"], acc["checks"])
            if msg:
                out.append(RawFinding("PGM006", offsets[idx] + 1, msg))

    sql_rules = {"PGM003", "PGM005", "PGM008"}
    if enabled is None or enabled & sql_rules:
        # SQL strings that only run on other databases (dbms=...), by value.
        skipped: set[str] = set()
        kept: set[str] = set()

        def collect_sql(obj: object, applies: bool) -> None:
            if isinstance(obj, dict):
                dbms = obj.get("dbms")
                here = applies and applies_to_postgresql(dbms if isinstance(dbms, str) else None)
                for k, v in obj.items():
                    if k in SQL_YAML_KEYS and isinstance(v, str):
                        (kept if here else skipped).add(v)
                    collect_sql(v, here)
            elif isinstance(obj, list):
                for v in obj:
                    collect_sql(v, applies)

        collect_sql(doc, True)
        for m in _JSON_SQL.finditer(text):
            content, pos = _json_string_at(text, m.end() - 1)
            if content in skipped and content not in kept:
                continue
            st = SqlText(content, origin="liquibase", context="liquibase", bare_q=False)
            for hit in check_sql(st, enabled):
                if hit.rule in sql_rules and hit.index < len(pos):
                    out.append(RawFinding(hit.rule, pos[hit.index], hit.message))
    return out

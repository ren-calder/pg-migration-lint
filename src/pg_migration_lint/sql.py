"""A small, forgiving SQL lexer and the SQL-text rules.

This is deliberately not a SQL parser. It tokenizes enough of PostgreSQL's
lexical structure (comments, string literals, dollar quotes, quoted
identifiers, placeholders) that the rules never match inside a comment or a
string, and then looks for a handful of exact token shapes.

SQL may come from a Java/Kotlin string expression; pieces of that expression
that are only known at runtime (a concatenated variable, a Kotlin template)
are represented by the sentinel character ``DYN``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

DYN = ""


@dataclass
class DynInfo:
    """What a DYN sentinel stands for."""

    kind: str  # "expr", "template", "const"
    const_text: str | None = None  # resolved text when kind == "const"


@dataclass
class SqlText:
    text: str
    origin: str  # "jvm", "sqlfile", "liquibase"
    context: str  # "native", "unknown", "r2dbc", "sqlfile", "liquibase"
    bare_q: bool = True  # `?` is a bind placeholder
    numbered: bool = False  # `?1` is a bind placeholder
    named: bool = False  # `:name` is a bind placeholder
    dyn: dict[int, DynInfo] = field(default_factory=dict)


@dataclass
class SqlTok:
    kind: str  # word, str, qident, ph, num, punct, op, dyn
    text: str
    start: int
    end: int

    @property
    def low(self) -> str:
        return self.text.lower()


@dataclass
class SqlHit:
    rule: str
    index: int  # index into SqlText.text
    message: str


_DOLLAR_TAG = re.compile(r"\$([A-Za-z_][A-Za-z_0-9]*)?\$")
_DOLLAR_PARAM = re.compile(r"\$\d+")


def _is_word_start(c: str) -> bool:
    return c != DYN and (c.isalpha() or c == "_")


def _is_word_char(c: str) -> bool:
    return c != DYN and (c.isalnum() or c == "_" or c == "$")


def lex_sql(text: str) -> list[SqlTok]:
    toks: list[SqlTok] = []
    i = 0
    n = len(text)
    while i < n:
        c = text[i]
        if c == DYN:
            toks.append(SqlTok("dyn", c, i, i + 1))
            i += 1
            continue
        if c.isspace():
            i += 1
            continue
        if c == "-" and text.startswith("--", i):
            j = text.find("\n", i)
            i = n if j < 0 else j + 1
            continue
        if c == "/" and text.startswith("/*", i):
            depth = 0
            j = i
            while j < n:
                if text.startswith("/*", j):
                    depth += 1
                    j += 2
                elif text.startswith("*/", j):
                    depth -= 1
                    j += 2
                    if depth == 0:
                        break
                else:
                    j += 1
            i = j
            continue
        if c == "'":
            escape = i > 0 and text[i - 1] in "eE" and (i < 2 or not _is_word_char(text[i - 2]))
            j = i + 1
            while j < n:
                ch = text[j]
                if escape and ch == "\\":
                    j += 2
                    continue
                if ch == "'":
                    if j + 1 < n and text[j + 1] == "'":
                        j += 2
                        continue
                    j += 1
                    break
                j += 1
            toks.append(SqlTok("str", text[i:j], i, j))
            i = j
            continue
        if c == '"':
            j = i + 1
            while j < n:
                if text[j] == '"':
                    if j + 1 < n and text[j + 1] == '"':
                        j += 2
                        continue
                    j += 1
                    break
                j += 1
            toks.append(SqlTok("qident", text[i:j], i, j))
            i = j
            continue
        if c == "$":
            prev_word = i > 0 and _is_word_char(text[i - 1])
            m = None if prev_word else _DOLLAR_TAG.match(text, i)
            if m:
                tag = m.group(0)
                close = text.find(tag, m.end())
                j = n if close < 0 else close + len(tag)
                toks.append(SqlTok("str", text[i:j], i, j))
                i = j
                continue
            m2 = _DOLLAR_PARAM.match(text, i)
            if m2 and not prev_word:
                toks.append(SqlTok("ph", m2.group(0), i, m2.end()))
                i = m2.end()
                continue
            toks.append(SqlTok("punct", c, i, i + 1))
            i += 1
            continue
        if c == "?":
            if i + 1 < n and text[i + 1] == "?":
                toks.append(SqlTok("op", "??", i, i + 2))
                i += 2
                continue
            j = i + 1
            while j < n and text[j].isdigit():
                j += 1
            toks.append(SqlTok("ph", text[i:j], i, j))
            i = j
            continue
        if c == ":":
            if i + 1 < n and text[i + 1] == ":":
                toks.append(SqlTok("op", "::", i, i + 2))
                i += 2
                continue
            prev = text[i - 1] if i > 0 else " "
            if i + 1 < n and _is_word_start(text[i + 1]) and not (_is_word_char(prev) or prev in ":])"):
                j = i + 2
                while j < n and (text[j].isalnum() or text[j] == "_"):
                    j += 1
                toks.append(SqlTok("ph", text[i:j], i, j))
                i = j
                continue
            toks.append(SqlTok("punct", c, i, i + 1))
            i += 1
            continue
        if _is_word_start(c):
            j = i + 1
            while j < n and _is_word_char(text[j]):
                j += 1
            toks.append(SqlTok("word", text[i:j], i, j))
            i = j
            continue
        if c.isdigit():
            j = i + 1
            while j < n and (text[j].isalnum() or text[j] in "._"):
                j += 1
            toks.append(SqlTok("num", text[i:j], i, j))
            i = j
            continue
        toks.append(SqlTok("punct", c, i, i + 1))
        i += 1
    return toks


_SQLISH = re.compile(
    r"(?i)\b(select|insert|update|delete|merge|where|from|join|having|values|returning|and|or|on|set)\b"
)


def looks_like_sql(text: str) -> bool:
    return bool(_SQLISH.search(text.replace(DYN, " ")))


# Words that cannot be the left operand of IN; used to avoid matching English.
_NOT_OPERAND = {
    "and", "or", "not", "where", "select", "on", "when", "then", "else", "set", "having",
    "from", "join", "by", "in", "is", "case", "values", "with", "as", "using", "returning",
    "logged", "signed", "log", "sign", "plug", "plugged", "built", "check", "checked",
}


def _match_paren(toks: list[SqlTok], open_idx: int) -> int | None:
    depth = 0
    for k in range(open_idx, len(toks)):
        t = toks[k]
        if t.kind == "punct" and t.text == "(":
            depth += 1
        elif t.kind == "punct" and t.text == ")":
            depth -= 1
            if depth == 0:
                return k
    return None


def _split_top(inner: list[SqlTok]) -> list[list[SqlTok]]:
    parts: list[list[SqlTok]] = [[]]
    depth = 0
    for t in inner:
        if t.kind == "punct" and t.text in "([":
            depth += 1
        elif t.kind == "punct" and t.text in ")]":
            depth -= 1
        if depth == 0 and t.kind == "punct" and t.text == ",":
            parts.append([])
            continue
        parts[-1].append(t)
    return parts


def _ph_allowed(t: SqlTok, st: SqlText) -> bool:
    if t.text == "?":
        return st.bare_q
    if t.text.startswith("?"):
        return st.numbered
    if t.text.startswith(":"):
        return st.named
    return False


def _in_operand_ok(toks: list[SqlTok], in_idx: int) -> bool:
    j = in_idx - 1
    if j >= 0 and toks[j].kind == "word" and toks[j].low == "not":
        j -= 1
    if j < 0:
        return True  # fragment starts at IN; the operand is elsewhere
    t = toks[j]
    if t.kind in ("qident", "dyn", "ph", "num", "str"):
        return True
    if t.kind == "punct" and t.text in ")]":
        return True
    if t.kind == "word" and t.low not in _NOT_OPERAND:
        return True
    return False


def _runtime_in(inner: list[SqlTok], unterminated: bool, st: SqlText) -> str | None:
    """Describe how an IN list is produced at runtime, or None if it is not."""
    if inner and all(t.kind == "dyn" for t in inner):
        infos = [st.dyn.get(t.start) for t in inner]
        consts = [i for i in infos if i is not None and i.kind == "const"]
        if consts and len(consts) == len(infos):
            texts = [(c.const_text or "").strip() for c in consts]
            if all(texts):
                return None  # resolved to a non-empty constant list or subquery
        for info in infos:
            if info is not None and info.kind == "const":
                low = (info.const_text or "").strip().lower()
                if low.startswith(("select", "with", "values")):
                    return None
        if any(i is not None and i.kind == "template" for i in infos):
            return "Kotlin string template"
        return "string concatenation"
    if unterminated and not inner:
        return "the SQL text ends at `in (` and the list is appended later"
    if (
        not unterminated
        and len(inner) == 2
        and inner[0].kind == "punct"
        and inner[0].text == "%"
        and inner[1].kind == "word"
        and inner[1].text == "s"
    ):
        return "format specifier %s"
    return None


def check_sql(st: SqlText, enabled: set[str] | None = None) -> list[SqlHit]:
    """Run the SQL-text rules over one piece of SQL."""
    toks = lex_sql(st.text)
    n = len(toks)
    hits: list[SqlHit] = []
    trusted = st.context in ("native", "sqlfile", "liquibase")
    sqlish_cache: list[bool] = []

    def sqlish() -> bool:
        if trusted:
            return True
        if not sqlish_cache:
            sqlish_cache.append(looks_like_sql(st.text))
        return sqlish_cache[0]

    def word(i: int, *words: str) -> bool:
        return 0 <= i < n and toks[i].kind == "word" and toks[i].low in words

    def punct(i: int, ch: str) -> bool:
        return 0 <= i < n and toks[i].kind == "punct" and toks[i].text == ch

    def on(rule: str) -> bool:
        return enabled is None or rule in enabled

    # PGM002: bare placeholder directly followed by IS NULL.
    if on("PGM002"):
        for i, t in enumerate(toks):
            if t.kind != "ph" or not _ph_allowed(t, st):
                continue
            if not (word(i + 1, "is") and word(i + 2, "null")):
                continue
            if i > 0 and toks[i - 1].kind == "op" and toks[i - 1].text == "::":
                continue
            if not trusted and not (
                sqlish() or word(i + 3, "or", "and", "then") or punct(i + 3, ")")
            ):
                continue
            msg = (
                f"`{t.text} is null` gives PostgreSQL no type for this parameter. With pgJDBC "
                "42.7.13 a null bound with Types.NULL fails here with SQLSTATE 42P18, and so does "
                "setNull(i, Types.TIMESTAMP_WITH_TIMEZONE) in `? is null or col >= ?`; "
                "setNull(i, Types.BIGINT) works."
            )
            if t.text != "?":
                msg += " Observed through plain JDBC; the ORM's null binding was not tested."
            hits.append(SqlHit("PGM002", t.start, msg))

    # IN-list rules: PGM003, PGM004, PGM008.
    for i, t in enumerate(toks):
        if not (word(i, "in") and punct(i + 1, "(")):
            continue
        if not _in_operand_ok(toks, i):
            continue
        close = _match_paren(toks, i + 1)
        inner = toks[i + 2 : close] if close is not None else toks[i + 2 :]
        negated = word(i - 1, "not")
        if close is not None and not inner:
            if on("PGM003") and sqlish():
                hits.append(SqlHit(
                    "PGM003", t.start,
                    "`in ()` with an empty list is a syntax error in PostgreSQL (SQLSTATE 42601).",
                ))
            continue
        if st.origin == "jvm":
            how = _runtime_in(inner, close is None, st)
            if how:
                if on("PGM004") and sqlish():
                    hits.append(SqlHit(
                        "PGM004", t.start,
                        f"IN list is filled in at runtime ({how}). When the collection is empty the "
                        "statement becomes `in ()`, which PostgreSQL rejects with SQLSTATE 42601.",
                    ))
                continue
        if negated or close is None or not on("PGM008") or not sqlish():
            continue
        if inner and inner[0].kind == "word" and inner[0].low in ("select", "with", "values"):
            continue
        for elem in _split_top(inner):
            if len(elem) == 1 and elem[0].kind == "word" and elem[0].low == "null":
                hits.append(SqlHit(
                    "PGM008", elem[0].start,
                    "A NULL element in `IN (...)` never matches rows where the column is NULL "
                    "(tested: `in ('Y', null)` skips the null row).",
                ))
                break

    # PGM005: simple CASE with WHEN NULL.
    if on("PGM005"):
        stack: list[tuple[bool, int]] = []  # (is_simple, paren depth at CASE)
        depth = 0
        for i, t in enumerate(toks):
            if t.kind == "punct" and t.text == "(":
                depth += 1
            elif t.kind == "punct" and t.text == ")":
                depth -= 1
                while stack and stack[-1][1] > depth:
                    stack.pop()
            elif word(i, "case"):
                stack.append((not word(i + 1, "when"), depth))
            elif word(i, "end"):
                if stack and stack[-1][1] == depth:
                    stack.pop()
            elif word(i, "when") and stack and stack[-1][1] == depth and stack[-1][0]:
                nxt = i + 1
                if word(nxt, "null") and (
                    word(nxt + 1, "then") or (nxt + 1 < n and toks[nxt + 1].text == "::")
                ):
                    hits.append(SqlHit(
                        "PGM005", t.start,
                        "Simple CASE compares with `=`, so `WHEN NULL` never matches (tested); null "
                        "inputs fall through to ELSE, or to NULL when there is no ELSE.",
                    ))
    return hits

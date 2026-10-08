"""Java and Kotlin sources: string literals that hold SQL, plus JDBC calls.

The lexer understands comments, char literals, string literals, Java text
blocks and Kotlin raw strings/templates. String literals joined with ``+``
are analyzed as one piece of SQL; operands that are not literals become the
``DYN`` sentinel.

Each piece of SQL gets a query context:

* ``native``  - argument of createNativeQuery(...), @Query(nativeQuery = true),
  @NativeQuery, @NamedNativeQuery, or Spring Data JDBC @Query;
* ``jpql``    - argument of createQuery(...), JPA @Query, @NamedQuery. JPQL is
  translated by the ORM, so it is skipped entirely;
* ``unknown`` - anything else (plain JDBC, JdbcTemplate, constants).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from .base import RawFinding
from .config import PGM007_MESSAGE, literal_stringtype, stringtype_findings
from .sql import DYN, DynInfo, SqlText, check_sql

NATIVE_CALLS = {"createNativeQuery", "createSQLQuery", "createNativeMutationQuery"}
JPQL_CALLS = {"createQuery", "createSelectionQuery", "createMutationQuery"}
NATIVE_ANNOTATIONS = {"NativeQuery", "NamedNativeQuery"}
JPQL_ANNOTATIONS = {"NamedQuery"}

_PUNCT_MULTI = (
    ">>>=", "<<=", ">>=", ">>>", "...", "!==", "===", "?.", "?:", "::", "->", "++", "--",
    "+=", "-=", "*=", "/=", "%=", "==", "!=", "<=", ">=", "&&", "||", "!!",
)


@dataclass
class JTok:
    kind: str  # str, ident, punct, num, char
    text: str
    start: int
    end: int
    pos: list[int] | None = None  # str: source offset of each content char
    dyn: dict[int, DynInfo] | None = None  # str: Kotlin template positions


@dataclass
class Lexed:
    toks: list[JTok]
    comments: list[tuple[int, int]] = field(default_factory=list)


_SIMPLE_ESC = {
    "b": "\b", "t": "\t", "n": "\n", "f": "\f", "r": "\r", "s": " ",
    '"': '"', "'": "'", "\\": "\\", "$": "$",
}


def _escape(src: str, i: int) -> tuple[str, int]:
    """Decode the escape sequence starting at src[i] == '\\'."""
    n = len(src)
    if i + 1 >= n:
        return "\\", i + 1
    c = src[i + 1]
    if c in _SIMPLE_ESC:
        return _SIMPLE_ESC[c], i + 2
    if c == "u":
        j = i + 1
        while j < n and src[j] == "u":
            j += 1
        hexpart = src[j : j + 4]
        try:
            return chr(int(hexpart, 16)), j + 4
        except ValueError:
            return "u", i + 2
    if c in "01234567":
        j = i + 1
        limit = i + 4 if c in "0123" else i + 3
        while j < n and j < limit and src[j] in "01234567":
            j += 1
        return chr(int(src[i + 1 : j], 8)), j
    if c == "\n":
        return "", i + 2
    if c == "\r":
        return "", i + 3 if src.startswith("\r\n", i + 1) else i + 2
    return c, i + 2


class _Lexer:
    def __init__(self, src: str, kotlin: bool):
        self.src = src
        self.n = len(src)
        self.kotlin = kotlin
        self.comments: list[tuple[int, int]] = []

    # -- strings ---------------------------------------------------------
    def _template(self, i: int, chars: list[str], pos: list[int], dyn: dict[int, DynInfo]) -> int:
        """Handle a Kotlin `$` at src[i]; return the new index."""
        src, n = self.src, self.n
        if i + 1 < n and src[i + 1] == "{":
            j = self._skip_template_expr(i + 2)
            dyn[len(chars)] = DynInfo("template")
            chars.append(DYN)
            pos.append(i)
            return j
        if i + 1 < n and (src[i + 1].isalpha() or src[i + 1] == "_"):
            j = i + 2
            while j < n and (src[j].isalnum() or src[j] == "_"):
                j += 1
            dyn[len(chars)] = DynInfo("template")
            chars.append(DYN)
            pos.append(i)
            return j
        chars.append("$")
        pos.append(i)
        return i + 1

    def _skip_template_expr(self, i: int) -> int:
        src, n = self.src, self.n
        depth = 1
        while i < n:
            c = src[i]
            if c == "{":
                depth += 1
            elif c == "}":
                depth -= 1
                if depth == 0:
                    return i + 1
            elif c == '"':
                tok = self._string(i)
                i = tok.end
                continue
            elif c == "'":
                i = self._char_or_punct(i)[1]
                continue
            elif src.startswith("//", i) or src.startswith("/*", i):
                i = self._comment(i)
                continue
            i += 1
        return n

    def _string(self, i: int) -> JTok:
        src = self.src
        if src.startswith('"""', i):
            return self._raw_kotlin(i) if self.kotlin else self._text_block(i)
        chars: list[str] = []
        pos: list[int] = []
        dyn: dict[int, DynInfo] = {}
        j = i + 1
        n = self.n
        while j < n:
            c = src[j]
            if c == '"':
                j += 1
                break
            if c == "\n":
                break
            if c == "\\":
                s, k = _escape(src, j)
                for ch in s:
                    chars.append(ch)
                    pos.append(j)
                j = k
                continue
            if self.kotlin and c == "$":
                j = self._template(j, chars, pos, dyn)
                continue
            chars.append(c)
            pos.append(j)
            j += 1
        return JTok("str", "".join(chars), i, j, pos, dyn)

    def _text_block(self, i: int) -> JTok:
        src, n = self.src, self.n
        j = i + 3
        while j < n and src[j] in " \t\f":
            j += 1
        if j < n and src[j] == "\r":
            j += 1
        if j < n and src[j] == "\n":
            j += 1
        chars: list[str] = []
        pos: list[int] = []
        while j < n:
            if src.startswith('"""', j):
                j += 3
                break
            c = src[j]
            if c == "\\":
                s, k = _escape(src, j)
                for ch in s:
                    chars.append(ch)
                    pos.append(j)
                j = k
                continue
            chars.append(c)
            pos.append(j)
            j += 1
        return JTok("str", "".join(chars), i, j, pos, {})

    def _raw_kotlin(self, i: int) -> JTok:
        src, n = self.src, self.n
        j = i + 3
        chars: list[str] = []
        pos: list[int] = []
        dyn: dict[int, DynInfo] = {}
        while j < n:
            if src.startswith('"""', j):
                # A run of more than three quotes ends with the last three.
                k = j + 3
                while k < n and src[k] == '"':
                    k += 1
                for q in range(j, k - 3):
                    chars.append('"')
                    pos.append(q)
                j = k
                break
            c = src[j]
            if c == "$":
                j = self._template(j, chars, pos, dyn)
                continue
            chars.append(c)
            pos.append(j)
            j += 1
        return JTok("str", "".join(chars), i, j, pos, dyn)

    def _char_or_punct(self, i: int) -> tuple[JTok, int]:
        src, n = self.src, self.n
        j = i + 1
        if j < n and src[j] == "\\":
            j += 2
        else:
            j += 1
        limit = min(n, i + 12)
        while j < limit and src[j] not in "'\n":
            j += 1
        if j < n and src[j] == "'":
            return JTok("char", src[i : j + 1], i, j + 1), j + 1
        return JTok("punct", "'", i, i + 1), i + 1

    def _comment(self, i: int) -> int:
        src, n = self.src, self.n
        if src.startswith("//", i):
            j = src.find("\n", i)
            end = n if j < 0 else j
        else:
            if self.kotlin:
                depth = 0
                j = i
                while j < n:
                    if src.startswith("/*", j):
                        depth += 1
                        j += 2
                    elif src.startswith("*/", j):
                        depth -= 1
                        j += 2
                        if depth == 0:
                            break
                    else:
                        j += 1
                end = j
            else:
                j = src.find("*/", i + 2)
                end = n if j < 0 else j + 2
        self.comments.append((i, end))
        return end

    # -- main loop -------------------------------------------------------
    def run(self) -> Lexed:
        src, n = self.src, self.n
        toks: list[JTok] = []
        i = 0
        while i < n:
            c = src[i]
            if c.isspace():
                i += 1
                continue
            if c == "/" and (src.startswith("//", i) or src.startswith("/*", i)):
                i = self._comment(i)
                continue
            if c == '"':
                tok = self._string(i)
                toks.append(tok)
                i = tok.end
                continue
            if c == "'":
                tok, i = self._char_or_punct(i)
                toks.append(tok)
                continue
            if c == "`" and self.kotlin:
                j = src.find("`", i + 1)
                j = n if j < 0 else j + 1
                toks.append(JTok("ident", src[i + 1 : j - 1], i, j))
                i = j
                continue
            if c.isalpha() or c in "_$":
                j = i + 1
                while j < n and (src[j].isalnum() or src[j] in "_$"):
                    j += 1
                toks.append(JTok("ident", src[i:j], i, j))
                i = j
                continue
            if c.isdigit():
                j = i + 1
                while j < n and (src[j].isalnum() or src[j] == "_" or (src[j] == "." and j + 1 < n and src[j + 1].isdigit())):
                    j += 1
                toks.append(JTok("num", src[i:j], i, j))
                i = j
                continue
            for op in _PUNCT_MULTI:
                if src.startswith(op, i):
                    toks.append(JTok("punct", op, i, i + len(op)))
                    i += len(op)
                    break
            else:
                toks.append(JTok("punct", c, i, i + 1))
                i += 1
        return Lexed(toks, self.comments)


def lex(src: str, kotlin: bool = False) -> Lexed:
    return _Lexer(src, kotlin).run()


# ---------------------------------------------------------------------------
# Structure: paren groups, string chains, declarations
# ---------------------------------------------------------------------------


@dataclass
class Group:
    callee: str | None
    is_annotation: bool
    open_idx: int
    close_idx: int | None
    parent: int | None


@dataclass
class Chain:
    first: int  # token index of the first string literal
    last: int  # token index of the last token consumed
    text: str
    pos: list[int]
    dyn: dict[int, DynInfo]
    pure: bool  # only literals, no runtime parts
    decl: str | None = None


def _is_punct(t: JTok, text: str) -> bool:
    return t.kind == "punct" and t.text == text


def _groups(toks: list[JTok]) -> tuple[list[Group], list[int | None]]:
    groups: list[Group] = []
    enclosing: list[int | None] = [None] * len(toks)
    stack: list[int] = []
    for idx, t in enumerate(toks):
        enclosing[idx] = stack[-1] if stack else None
        if _is_punct(t, "("):
            callee = None
            is_annot = False
            j = idx - 1
            if j >= 0 and toks[j].kind == "ident":
                callee = toks[j].text
                k = j
                while k - 2 >= 0 and _is_punct(toks[k - 1], ".") and toks[k - 2].kind == "ident":
                    k -= 2
                is_annot = k - 1 >= 0 and _is_punct(toks[k - 1], "@")
            groups.append(Group(callee, is_annot, idx, None, stack[-1] if stack else None))
            stack.append(len(groups) - 1)
        elif _is_punct(t, ")") and stack:
            groups[stack.pop()].close_idx = idx
    return groups, enclosing


_OPERAND_STOP = {"+", ",", ";", "=", "?", ":", "->", "?:", "==", "!=", "&&", "||", "+=", "-="}


def _scan_operand(toks: list[JTok], k: int) -> int:
    depth = 0
    n = len(toks)
    while k < n:
        t = toks[k]
        if t.kind == "punct":
            if t.text in ("(", "[", "{"):
                depth += 1
            elif t.text in (")", "]", "}"):
                if depth == 0:
                    break
                depth -= 1
            elif depth == 0 and t.text in _OPERAND_STOP:
                break
        k += 1
    return k


def _chains(toks: list[JTok], consts: dict[str, str]) -> list[Chain]:
    chains: list[Chain] = []
    consumed: set[int] = set()
    n = len(toks)
    for i, t in enumerate(toks):
        if t.kind != "str" or i in consumed:
            continue
        chars: list[str] = []
        pos: list[int] = []
        dyn: dict[int, DynInfo] = {}
        pure = True

        def add_dyn(at: int, info: DynInfo) -> None:
            dyn[len(chars)] = info
            chars.append(DYN)
            pos.append(at)

        def add_str(tok: JTok) -> None:
            base = len(chars)
            for k, info in (tok.dyn or {}).items():
                dyn[base + k] = info
            chars.extend(tok.text)
            pos.extend(tok.pos or [])

        if i > 0 and _is_punct(toks[i - 1], "+"):
            add_dyn(toks[i - 1].start, DynInfo("expr"))
            pure = False
        add_str(t)
        if t.dyn:
            pure = False
        j = i + 1
        last = i
        while j < n and _is_punct(toks[j], "+"):
            k = j + 1
            if k < n and toks[k].kind == "str" and not (k + 1 < n and _is_punct(toks[k + 1], ".")):
                consumed.add(k)
                add_str(toks[k])
                if toks[k].dyn:
                    pure = False
                last = k
                j = k + 1
                continue
            end = _scan_operand(toks, k)
            if end == k:
                break
            pure = False
            if end == k + 1 and toks[k].kind == "ident" and toks[k].text in consts:
                add_dyn(toks[k].start, DynInfo("const", consts[toks[k].text]))
            else:
                add_dyn(toks[k].start, DynInfo("expr"))
            last = end - 1
            j = end
        decl = None
        if i >= 2 and _is_punct(toks[i - 1], "=") and toks[i - 2].kind == "ident":
            decl = toks[i - 2].text
            if i >= 4 and _is_punct(toks[i - 3], ":") and toks[i - 4].kind == "ident":
                decl = toks[i - 4].text  # Kotlin: val name: String = "..."
        chains.append(Chain(i, last, "".join(chars), pos, dyn, pure, decl))
    return chains


_IMPORT = re.compile(r"^\s*import\s+(?:static\s+)?([\w.]+(?:\.\*)?)", re.M)

_EMPTY_GUARD = re.compile(
    r"\b(?:isEmpty|isNotEmpty|isNullOrEmpty|ifEmpty|notEmpty|isEmptyOrNull)\s*\("
    r"|\.(?:size|length|count)\s*(?:\(\s*\))?\s*(?:==|!=|>=|<=|>|<)\s*[01]\b"
    r"|\.(?:none|isEmpty|isNotEmpty)\s*\("
)
_GUARD_WINDOW = 30

_NOT_FUNCTION_CALLEES = {"if", "for", "while", "switch", "catch", "synchronized", "when", "try"}
_TYPE_TOKENS = {".", ",", "<", ">", "?", ":", "[", "]", "&", "@"}


def _function_body_start(
    toks: list[JTok], groups: list[Group], enclosing: list[int | None], idx: int, kotlin: bool = False
) -> int | None:
    """Token index of the `{` opening the method/function body around idx."""
    depth = 0
    for k in range(idx - 1, -1, -1):
        t = toks[k]
        if t.kind != "punct":
            continue
        if t.text == "}":
            depth += 1
        elif t.text == "{":
            if depth > 0:
                depth -= 1
                continue
            # `{` of a block that contains idx: is it a function body?
            j = k - 1
            while j >= 0 and (
                (toks[j].kind == "ident" and toks[j].text not in ("else", "try", "finally", "do", "new"))
                or (toks[j].kind == "punct" and toks[j].text in _TYPE_TOKENS)
            ):
                j -= 1
            if j < 0 or not _is_punct(toks[j], ")"):
                if j >= 0 and toks[j].kind == "ident" and toks[j].text in ("class", "interface", "object", "enum"):
                    return None
                continue
            g_idx = enclosing[j]
            if g_idx is None:
                continue
            g = groups[g_idx]
            callee_idx = g.open_idx - 1
            if g.callee is None or g.callee in _NOT_FUNCTION_CALLEES:
                continue
            if kotlin:
                head = toks[max(0, callee_idx - 8) : callee_idx]
                if not any(h.kind == "ident" and h.text == "fun" for h in head):
                    continue  # e.g. a call followed by a trailing lambda on the next line
            elif callee_idx - 1 >= 0 and toks[callee_idx - 1].text in ("new", "."):
                continue  # anonymous class or a method call
            return k
    return None


def _previous_kotlin_fun(toks: list[JTok], idx: int) -> int | None:
    for k in range(idx - 1, -1, -1):
        if toks[k].kind == "ident" and toks[k].text == "fun":
            return k
    return None


def _context_of(
    chain: Chain,
    toks: list[JTok],
    groups: list[Group],
    enclosing: list[int | None],
    imports: set[str],
    chains_by_decl: dict[str, list[Chain]],
    ident_index: dict[str, list[int]],
) -> str:
    def annotation_context(g: Group) -> str | None:
        name = g.callee
        if name in NATIVE_ANNOTATIONS:
            return "native"
        if name in JPQL_ANNOTATIONS:
            return "jpql"
        if name == "Query":
            close = g.close_idx if g.close_idx is not None else len(toks) - 1
            for k in range(g.open_idx, close):
                if (
                    toks[k].kind == "ident"
                    and toks[k].text == "nativeQuery"
                    and k + 2 <= close
                    and _is_punct(toks[k + 1], "=")
                    and toks[k + 2].text == "true"
                ):
                    return "native"
            if any(i.startswith("org.springframework.data.jdbc.repository.query.") for i in imports):
                return "native"
            if any(i.startswith("org.springframework.data.r2dbc.repository.") for i in imports):
                return "r2dbc"
            return "jpql"
        return None

    def group_context(g_idx: int | None) -> str | None:
        while g_idx is not None:
            g = groups[g_idx]
            if g.is_annotation:
                ctx = annotation_context(g)
                if ctx:
                    return ctx
            elif g.callee in NATIVE_CALLS:
                return "native"
            elif g.callee in JPQL_CALLS:
                return "jpql"
            g_idx = g.parent
        return None

    ctx = group_context(enclosing[chain.first])
    if ctx:
        return ctx
    if chain.decl:
        found: set[str] = set()
        decls = chains_by_decl.get(chain.decl, [])
        for u in ident_index.get(chain.decl, ()):
            if u + 1 < len(toks) and _is_punct(toks[u + 1], "="):
                continue  # another declaration/assignment
            g_idx = enclosing[u]
            if g_idx is None:
                continue
            uctx = group_context(g_idx)
            if not uctx:
                continue
            before = [d for d in decls if d.first < u]
            target = before[-1] if before else (decls[0] if decls else None)
            if target is chain:
                found.add(uctx)
        if "native" in found:
            return "native"
        if "jpql" in found:
            return "jpql"
        if "r2dbc" in found:
            return "r2dbc"
    return "unknown"


def scan_jvm(src: str, kotlin: bool = False, enabled: set[str] | None = None) -> list[RawFinding]:
    lexed = lex(src, kotlin)
    toks = lexed.toks
    out: list[RawFinding] = []

    def on(rule: str) -> bool:
        return enabled is None or rule in enabled

    code_view = list(src)
    for a, b in lexed.comments:
        for k in range(a, b):
            if code_view[k] != "\n":
                code_view[k] = " "
    code = "".join(code_view)
    imports = set(_IMPORT.findall(code))
    named_jdbc = any(
        i.startswith("org.springframework.jdbc.core.namedparam")
        or i == "org.springframework.jdbc.core.simple.JdbcClient"
        or i == "org.springframework.jdbc.core.simple.*"
        for i in imports
    )

    groups, enclosing = _groups(toks)

    # Pass 1: chains without constant resolution, to learn pure string constants.
    consts: dict[str, str] = {}
    for ch in _chains(toks, {}):
        if ch.decl and ch.pure:
            g = enclosing[ch.first]
            if g is None or not groups[g].is_annotation:
                consts.setdefault(ch.decl, ch.text)
    chains = _chains(toks, consts)
    chains_by_decl: dict[str, list[Chain]] = {}
    for ch in chains:
        if ch.decl:
            chains_by_decl.setdefault(ch.decl, []).append(ch)
    ident_index: dict[str, list[int]] = {}
    for idx, tk in enumerate(toks):
        if tk.kind == "ident" and tk.text in chains_by_decl:
            ident_index.setdefault(tk.text, []).append(idx)

    lines = src.split("\n")
    line_starts = [0]
    for ln in lines[:-1]:
        line_starts.append(line_starts[-1] + len(ln) + 1)

    def line_of(offset: int) -> int:
        lo, hi = 0, len(line_starts) - 1
        while lo < hi:
            mid = (lo + hi + 1) // 2
            if line_starts[mid] <= offset:
                lo = mid
            else:
                hi = mid - 1
        return lo

    def guarded(offset: int, tok_idx: int) -> bool:
        """Is there an emptiness check earlier in the same function?"""
        ln = line_of(offset)
        end = line_starts[ln] + len(lines[ln])
        body = _function_body_start(toks, groups, enclosing, tok_idx, kotlin)
        if body is not None:
            start = toks[body].start
        else:
            start = line_starts[max(0, ln - _GUARD_WINDOW)]
            fun = _previous_kotlin_fun(toks, tok_idx) if kotlin else None
            if fun is not None:
                start = max(start, toks[fun].start)
        return bool(_EMPTY_GUARD.search(code[start:end]))

    sql_rules = {"PGM002", "PGM003", "PGM004", "PGM005", "PGM008"}
    if enabled is None or enabled & sql_rules:
        for ch in chains:
            ctx = _context_of(ch, toks, groups, enclosing, imports, chains_by_decl, ident_index)
            if ctx == "jpql":
                continue
            st = SqlText(
                text=ch.text,
                origin="jvm",
                context=ctx,
                bare_q=ctx in ("native", "unknown"),
                numbered=ctx == "native",
                named=ctx == "native" or (ctx == "unknown" and named_jdbc),
                dyn=ch.dyn,
            )
            for hit in check_sql(st, enabled):
                if hit.index < len(ch.pos):
                    offset = ch.pos[hit.index]
                else:
                    offset = toks[ch.last].start
                if hit.rule == "PGM004" and guarded(offset, ch.first):
                    continue
                out.append(RawFinding(hit.rule, offset, hit.message))

    if on("PGM001"):
        for i, t in enumerate(toks):
            if t.kind != "ident" or t.text != "setNull":
                continue
            if i + 1 >= len(toks) or not _is_punct(toks[i + 1], "("):
                continue
            g_idx = enclosing[i + 2] if i + 2 < len(toks) else None
            if g_idx is None:
                continue
            close = groups[g_idx].close_idx
            if close is None:
                continue
            args: list[list[JTok]] = [[]]
            depth = 0
            for k in range(i + 2, close):
                tk = toks[k]
                if tk.kind == "punct" and tk.text in ("(", "[", "{"):
                    depth += 1
                elif tk.kind == "punct" and tk.text in (")", "]", "}"):
                    depth -= 1
                if depth == 0 and _is_punct(tk, ","):
                    args.append([])
                    continue
                args[-1].append(tk)
            if len(args) >= 2 and "".join(a.text for a in args[1]) in ("Types.NULL", "java.sql.Types.NULL"):
                out.append(RawFinding(
                    "PGM001", t.start,
                    "setNull(..., Types.NULL) binds a null with no SQL type. Where the SQL gives the "
                    "placeholder no type context (e.g. `? is null`), PostgreSQL rejects the statement "
                    "with SQLSTATE 42P18 (could not determine data type of parameter).",
                ))

    if on("PGM007"):
        for t in toks:
            if t.kind == "str" and t.pos:
                idx = literal_stringtype(t.text)
                if idx is not None and idx < len(t.pos):
                    out.append(RawFinding("PGM007", t.pos[idx], PGM007_MESSAGE))
        out.extend(stringtype_findings(code, "code"))
    return out

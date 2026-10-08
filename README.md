# pg-migration-lint

A small static checker for Java codebases moving to PostgreSQL. It looks for a
handful of migration pitfalls in JDBC code, native SQL, `.sql` files and
Liquibase changelogs.

Each rule describes a behavior that was reproduced on a real PostgreSQL server
or is documented by Liquibase or pgJDBC. None of them is a style opinion.
Fewer findings you can trust beat a long list you learn to ignore, so the
rules only match narrow, specific shapes.

```text
$ pgmig-lint tests/fixtures/rules/pgm006/bad/changelog.yaml
tests/fixtures/rules/pgm006/bad/changelog.yaml:5:7: PGM006 [warning] onFail="MARK_RAN" guarded only by a name check (`not indexExists ux_account_ref`): if an object with that name already exists but is not what this change set creates, Liquibase records the change set as MARK_RAN and never retries it, so the real change is skipped permanently (tested on Liquibase 5.0.4).
    fix: Prefer onFail="HALT" with an onFailMessage, or make the precondition prove the full postcondition (columns, types, uniqueness), e.g. with a sqlCheck against the catalog.
    learn more: PostgreSQL Migration Survival Guide for Java Teams: Chapter 6, "Liquibase cross-database traps" > "Preconditions are guards, not repairs"
tests/fixtures/rules/pgm006/bad/changelog.yaml:26:17: PGM005 [error] Simple CASE compares with `=`, so `WHEN NULL` never matches (tested); null inputs fall through to ELSE, or to NULL when there is no ELSE.
    fix: Use a searched CASE: `CASE WHEN x IS NULL THEN ... WHEN x = 'Y' THEN ... END`.
    learn more: PostgreSQL Migration Survival Guide for Java Teams: Chapter 2, "Type-system traps" > "Boolean versus `char(1)`, `Y/N`, and `0/1`"
tests/fixtures/rules/pgm006/bad/changelog.yaml:29:47: PGM003 [error] `in ()` with an empty list is a syntax error in PostgreSQL (SQLSTATE 42601).
    fix: Decide what an empty list means before building SQL: return no rows without querying, drop the predicate, or reject the input.
    learn more: PostgreSQL Migration Survival Guide for Java Teams: Chapter 4, "SQL and query traps" > "Empty collections"
Found 3 findings (2 error, 1 warning, 0 info) in 1 file scanned.
```

## What it catches

| Rule | What | Why | Fix |
|---|---|---|---|
| **PGM001** (warning) | `setNull(i, Types.NULL)` | The null has no SQL type. Where the SQL gives the placeholder no type context (`? is null`), PostgreSQL fails with `42P18`. | Bind the real type: `setNull(i, Types.BIGINT)`. |
| **PGM002** (warning) | Optional filters `? is null` / `:p is null` in JDBC SQL, native queries and `.sql` files | No type context for the parameter: `42P18` with an untyped null, and also with `setNull(i, Types.TIMESTAMP_WITH_TIMEZONE)` in `? is null or col >= ?`. | Use a separate query form when the filter is absent, or type it in SQL: `cast(? as timestamptz) is null`. |
| **PGM003** (error) | Literal `in ()` | Syntax error, `42601`. | Decide what an empty list means before querying: no rows, no predicate, or reject the input. |
| **PGM004** (warning) | IN list contents spliced in at runtime: `"in (" + ids + ")"`, `in (%s)`, Kotlin `in (${...})`, or SQL text ending in `in (` | An empty collection produces `in ()`, which fails with `42601`. | Handle the empty case first, or bind one array: `col = any (?::bigint[])` with `createArrayOf("bigint", ids)`. |
| **PGM005** (error) | Simple `CASE x WHEN NULL THEN ...` | A simple CASE compares with `=`, so this branch never matches and nulls fall through to `ELSE`. | Use a searched CASE: `CASE WHEN x IS NULL THEN ...`. |
| **PGM006** (warning) | Liquibase `onFail="MARK_RAN"` (or `onError`) where the only guard is `not tableExists` / `indexExists` / `columnExists` / ... by name | A same-named but different object makes Liquibase record the change set as `MARK_RAN`. It is never retried, so the real change is skipped for good. | Use `onFail="HALT"` with an `onFailMessage`, or prove the full postcondition with a `sqlCheck`. |
| **PGM007** (info) | pgJDBC `stringtype=unspecified` in a JDBC URL, properties, YAML, XML or code | Every `setString` on the connection is sent untyped, which hides setter/column mismatches (no more `42883`). | Treat it as a temporary bridge: fix the setters, then remove it. |
| **PGM008** (warning) | A `NULL` element in `IN (...)` | `IN` never matches NULL rows. | Write `col in (...) or col is null`. |

### Where the rules come from

The behaviors behind these rules were run on PostgreSQL 18.4 and 16.15 with
pgJDBC 42.7.13, Liquibase 5.0.4 and Java 21, or checked against the
Liquibase and pgJDBC documentation. The SQLSTATEs in the messages are the
ones observed there. Other versions can behave differently, so rerun the
checks on the stack you ship. `pgmig-lint --list-rules` prints the catalog,
and each SARIF rule's help text includes its evidence.

## What it scans

| Files | What is checked |
|---|---|
| `*.java`, `*.kt` | String literals that hold SQL, including `+` concatenations, Java text blocks, Kotlin raw strings and templates; `setNull` calls; pgJDBC settings in code |
| `*.sql` | The SQL rules (`?` placeholders only; `:name` is treated as a psql variable) |
| `*.xml`, `*.yaml`, `*.yml`, `*.json` | Liquibase changelogs: preconditions plus the SQL in `sql`, `sqlCheck`, `createView`, `where` and `rollback` |
| `*.properties`, `*.yml`, `*.yaml`, `*.xml` | JDBC URLs and data-source properties for PGM007 |

Directories such as `.git`, `target`, `build`, `node_modules` and `.gradle`
are skipped. Changesets and `<sql>` blocks restricted to other databases with
`dbms="..."` are skipped.

SQL in Java and Kotlin is checked according to where it is used:

- **Native SQL** (`createNativeQuery(...)`, `@Query(..., nativeQuery = true)`,
  `@NativeQuery`, `@NamedNativeQuery`, Spring Data JDBC `@Query`): `?`, `?1`
  and `:name` placeholders are all checked.
- **JPQL/HQL** (`createQuery(...)`, JPA `@Query`, `@NamedQuery`): skipped.
  The ORM translates it and types its parameters.
- **Anything else** (plain JDBC, `JdbcTemplate`, constants): `?` placeholders.
  `:name` placeholders are checked only when the file imports Spring's
  `NamedParameterJdbcTemplate` or `JdbcClient`.

A constant or local variable defined in the same file and passed to one of
these calls gets that call's context.

## Install

```bash
pipx install "git+https://github.com/ren-calder/pg-migration-lint"
# or: pip install "git+https://github.com/ren-calder/pg-migration-lint"
```

Requires Python 3.10 or newer. No runtime dependencies.

## Usage

```bash
pgmig-lint [paths...] [--format text|json|sarif] [--select RULES] [--ignore RULES]
           [--fail-on error|warning|info|never] [--exclude GLOB] [--output FILE]
```

```bash
pgmig-lint                                   # scan the current directory
pgmig-lint src/main db/changelog             # scan specific paths
pgmig-lint --select PGM003,PGM005 .          # only these rules
pgmig-lint --ignore PGM007 .                 # everything except these
pgmig-lint --fail-on warning .               # stricter gate
pgmig-lint --format json . > findings.json
pgmig-lint --format sarif --output pgmig-lint.sarif .
pgmig-lint --list-rules
```

| Option | Meaning |
|---|---|
| `--format` | `text` (default), `json`, or `sarif` (SARIF 2.1.0) |
| `--select RULES` | Run only these rules. Comma-separated, repeatable. |
| `--ignore RULES` | Skip these rules. Comma-separated, repeatable. |
| `--fail-on LEVEL` | Exit 1 when a finding at or above `LEVEL` exists. Default: `error`. Use `never` to always exit 0. |
| `--exclude GLOB` | Skip matching files or directories. Matched against the path and the base name; repeatable. |
| `--output FILE` | Write the report to a file instead of stdout. |

Exit codes: `0` when no finding reaches `--fail-on`, `1` when one does, `2` for
usage errors such as an unknown rule id or a missing path.

### Suppressing a finding

Put `pgmig-lint: ignore[RULE]` in a comment on the reported line. Several
rules can be listed, separated by commas:

```java
ps.setNull(1, Types.NULL); // pgmig-lint: ignore[PGM001] the statement is an insert into a typed column
```

```xml
<preConditions onFail="MARK_RAN"> <!-- pgmig-lint: ignore[PGM006] -->
```

Inside a Java text block or a `.sql` file, use an SQL comment
(`-- pgmig-lint: ignore[PGM002]`). The marker only counts when it follows a
comment start (`//`, `/*`, `--`, `#` or `<!--`) on that line. A
precondition finding is reported on the `preConditions` line.

## CI: GitHub code scanning

```yaml
name: pgmig-lint
on: [push, pull_request]

jobs:
  pgmig-lint:
    runs-on: ubuntu-latest
    permissions:
      contents: read
      security-events: write   # needed to upload SARIF
    steps:
      - uses: actions/checkout@v7
      - uses: actions/setup-python@v7
        with:
          python-version: "3.12"
      - run: pip install "git+https://github.com/ren-calder/pg-migration-lint"
      - name: Lint to SARIF
        run: pgmig-lint --format sarif --output pgmig-lint.sarif --fail-on never .
      - uses: github/codeql-action/upload-sarif@v4
        with:
          sarif_file: pgmig-lint.sarif
          category: pgmig-lint
      - name: Fail the build on errors
        run: pgmig-lint .
```

Code scanning must be available for the repository for the upload to work.
Without it, keep only the last step. It prints the text report and fails on
`error` findings.

## Limitations

- **Heuristics, not a parser.** The tool tokenizes SQL so it never matches
  inside comments or string literals, then looks for specific token shapes.
  It does not parse full SQL, Java or Kotlin, and it does not know column
  types. Mismatches that depend on the schema are out of reach, such as
  `setString` into `jsonb` (`42804`), `setLong` against `varchar` (`42883`)
  or `char(1) = true` (`42883`).
- **Hibernate/JPQL is not analyzed.** JPQL and HQL are skipped. Hibernate
  behavior was not executed for the book, so there are no Hibernate-specific
  rules. Findings on named parameters in native queries say their evidence
  comes from plain JDBC.
- **PGM002 cannot see how a null is bound.** It reports the SQL shape that
  fails with untyped and timestamp-family nulls. With a typed non-timestamp
  `setNull` the same SQL works. In that case, suppress the finding or give the
  placeholder a cast.
- **PGM004 uses an emptiness check as a hint.** It stays quiet when
  `isEmpty()`, `size() > 0` or similar appears earlier in the same method,
  without proving that the check guards this SQL. Named collection parameters
  such as `IN (:ids)` are not reported, because how frameworks expand an empty
  collection was not tested.
- **SQL is seen as written in one file.** SQL assembled across methods or
  files is checked piece by piece, and the query context of a string is only
  known when the native/JPQL call or annotation is in the same file.
- **Not reported because the behavior was not executed:**
  `setObject(i, null)` and `NOT IN (..., NULL)`.
- **Not scanned:** PL/pgSQL bodies inside dollar quotes, MyBatis and other
  XML mappers, Liquibase formatted-SQL preconditions, and YAML flow style
  (`{ ... }`) in changelogs.

## Background

The rules come from the book *PostgreSQL Migration Survival Guide for Java
Teams* by Ren Calder. Each finding's "learn more" line names the chapter and
section that explains the failure and the repair options.

- Leanpub: https://leanpub.com/postgresql-migration-java

## Development

```bash
python -m pip install -e ".[test]"
python -m pytest -q
pgmig-lint --exclude tests .     # the test fixtures contain deliberate findings
```

Test fixtures live in `tests/fixtures`. A fixture marks each expected finding
with `expect[PGMxxx]` in a comment on the reported line, or in a
`<file>.expect` sidecar for formats without trailing comments. The tests
require the exact set, so any extra finding fails.

## License

MIT. See [LICENSE](LICENSE).

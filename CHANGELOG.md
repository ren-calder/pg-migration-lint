# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[Semantic Versioning](https://semver.org/).

## [0.1.0] - 2026-10-08

First version.

### Added

- `pgmig-lint` command with `--format text|json|sarif`, `--select`, `--ignore`,
  `--fail-on error|warning|info|never`, `--exclude`, `--output` and `--list-rules`.
- Scans `*.java`, `*.kt`, `*.sql`, Liquibase changelogs (`*.xml`, `*.yaml`, `*.yml`,
  `*.json`) and JDBC settings in `*.properties`, `*.yml`, `*.yaml` and `*.xml`.
- Rules:
  - `PGM001` untyped null binding with `setNull(i, Types.NULL)`.
  - `PGM002` optional-filter placeholder `? is null` / `:p is null` without a type.
  - `PGM003` literal empty `in ()`.
  - `PGM004` IN list filled in at runtime that becomes `in ()` for an empty collection.
  - `PGM005` simple `CASE x WHEN NULL`, which never matches.
  - `PGM006` Liquibase `MARK_RAN` guarded only by a name check.
  - `PGM007` pgJDBC `stringtype=unspecified`.
  - `PGM008` `NULL` element inside `IN (...)`.
- Inline suppression with `pgmig-lint: ignore[PGM00x]` in a comment on the reported line.
- SARIF 2.1.0 output for GitHub code scanning.

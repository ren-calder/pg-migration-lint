"""Command-line entry point: ``pgmig-lint``."""

from __future__ import annotations

import argparse
import os
import sys

from . import __version__
from .output import FORMATTERS
from .rules import RULES, SEVERITY_RANK, parse_rule_list
from .scanner import scan_paths

EXIT_OK = 0
EXIT_FINDINGS = 1
EXIT_USAGE = 2


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="pgmig-lint",
        description=(
            "Find Java-to-PostgreSQL migration pitfalls in JDBC code, native SQL, "
            "SQL files and Liquibase changelogs."
        ),
    )
    p.add_argument("paths", nargs="*", default=["."], help="files or directories to scan (default: .)")
    p.add_argument("--format", choices=sorted(FORMATTERS), default="text", help="output format (default: text)")
    p.add_argument("--select", action="append", metavar="RULES",
                   help="only run these rules (comma-separated, repeatable), e.g. PGM001,PGM003")
    p.add_argument("--ignore", action="append", metavar="RULES",
                   help="skip these rules (comma-separated, repeatable)")
    p.add_argument("--fail-on", choices=["error", "warning", "info", "never"], default="error",
                   help="exit 1 when a finding at or above this severity exists (default: error)")
    p.add_argument("--exclude", action="append", default=[], metavar="GLOB",
                   help="skip files or directories matching this glob (repeatable)")
    p.add_argument("-o", "--output", metavar="FILE", help="write the report to FILE instead of stdout")
    p.add_argument("--list-rules", action="store_true", help="print the rule catalog and exit")
    p.add_argument("--version", action="version", version=f"pgmig-lint {__version__}")
    return p


def _list_rules() -> str:
    lines = []
    for rid in sorted(RULES):
        r = RULES[rid]
        lines.append(f"{r.id}  {r.severity:<7}  {r.name}: {r.title}")
        lines.append(f"    learn more: {r.learn_more}")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.list_rules:
        sys.stdout.write(_list_rules())
        return EXIT_OK

    try:
        selected = parse_rule_list(args.select) if args.select else set(RULES)
        ignored = parse_rule_list(args.ignore)
    except ValueError as exc:
        parser.print_usage(sys.stderr)
        print(f"pgmig-lint: error: {exc}", file=sys.stderr)
        return EXIT_USAGE
    enabled = selected - ignored

    missing = [p for p in args.paths if not os.path.exists(p)]
    if missing:
        for p in missing:
            print(f"pgmig-lint: error: no such file or directory: {p}", file=sys.stderr)
        return EXIT_USAGE

    findings, files_scanned = scan_paths(args.paths, enabled, args.exclude)
    report = FORMATTERS[args.format](findings, files_scanned)
    if args.output:
        with open(args.output, "w", encoding="utf-8") as fh:
            fh.write(report)
    else:
        sys.stdout.write(report)

    if args.fail_on == "never":
        return EXIT_OK
    threshold = SEVERITY_RANK[args.fail_on]
    if any(SEVERITY_RANK[f.severity] >= threshold for f in findings):
        return EXIT_FINDINGS
    return EXIT_OK


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())

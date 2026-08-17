from __future__ import annotations

import argparse
import json
from datetime import date
from pathlib import Path

from .collector import parse_weekly_dates
from .models import SourceCandidate
from .pipeline import (
    build_site,
    ingest_local,
    rebuild_extracted_data,
    refresh_catalog,
    scan,
)


def _candidate_from_args(args: argparse.Namespace) -> SourceCandidate:
    if args.report_type == "weekly_compstat":
        dates = parse_weekly_dates(args.title)
        if not dates:
            raise SystemExit("Weekly title must contain 'Month D through Month D, YYYY'")
        start, end = dates
        year = end.year
    else:
        if not args.year:
            raise SystemExit("--year is required for year-end report types")
        year = args.year
        start, end = date(year, 1, 1), date(year, 12, 31)
    return SourceCandidate(
        title=args.title,
        url=args.url,
        report_type=args.report_type,
        report_start=start,
        report_end=end,
        report_year=year,
        discovery_page=args.url,
        discovery_method="manual_local_ingest",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="compstat-archive")
    subparsers = parser.add_subparsers(dest="command", required=True)

    scan_parser = subparsers.add_parser("scan", help="Scan City pages and archive changes")
    scan_parser.add_argument("--root", type=Path, default=Path.cwd())

    ingest_parser = subparsers.add_parser("ingest", help="Ingest a local source PDF")
    ingest_parser.add_argument("--root", type=Path, default=Path.cwd())
    ingest_parser.add_argument("--pdf", type=Path, required=True)
    ingest_parser.add_argument("--title", required=True)
    ingest_parser.add_argument("--url", required=True)
    ingest_parser.add_argument(
        "--report-type",
        required=True,
        choices=("weekly_compstat", "year_end_compstat", "wpd_year_end_report"),
    )
    ingest_parser.add_argument("--year", type=int)

    site_parser = subparsers.add_parser("build-site", help="Build the static research site")
    site_parser.add_argument("--root", type=Path, default=Path.cwd())
    site_parser.add_argument("--output", type=Path)
    refresh_parser = subparsers.add_parser(
        "refresh-catalog", help="Refresh catalog fields from archived manifests"
    )
    refresh_parser.add_argument("--root", type=Path, default=Path.cwd())
    rebuild_parser = subparsers.add_parser(
        "rebuild-data",
        help="Reparse archived CompStat PDFs with the current extraction contract",
    )
    rebuild_parser.add_argument("--root", type=Path, default=Path.cwd())
    return parser


def main() -> int:
    args = build_parser().parse_args()
    if args.command == "scan":
        result = scan(args.root)
    elif args.command == "ingest":
        result = ingest_local(args.root, args.pdf, _candidate_from_args(args))
    elif args.command == "build-site":
        result = {"site": str(build_site(args.root, args.output))}
    elif args.command == "refresh-catalog":
        result = {"refreshed_reports": refresh_catalog(args.root)}
    else:
        result = rebuild_extracted_data(args.root)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

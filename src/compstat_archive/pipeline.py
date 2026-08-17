from __future__ import annotations

import csv
import gzip
import hashlib
import json
import os
import re
import shutil
import sqlite3
import tempfile
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable

from pypdf import PdfReader

from .collector import CityClient, document_url_parts
from .config import EXTRACTION_VERSION, OBSERVATION_FIELDS, REPORT_FIELDS
from .models import SourceCandidate, ValidationResult
from .parser import parse_compstat_pdf
from .validator import validate_parsed_report


def _json_dump(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _write_csv(path: Path, rows: Iterable[dict[str, Any]], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field) for field in fields})


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")


def _report_key(candidate: SourceCandidate) -> str:
    if candidate.report_type == "weekly_compstat":
        assert candidate.report_end is not None
        return f"weekly:{candidate.report_end.isoformat()}"
    assert candidate.report_year is not None
    return f"{candidate.report_type}:{candidate.report_year}"


def _identity_slug(candidate: SourceCandidate) -> str:
    if candidate.report_type == "weekly_compstat":
        assert candidate.report_end is not None
        return f"weekly-{candidate.report_end.isoformat()}"
    assert candidate.report_year is not None
    return f"{candidate.report_type.replace('_', '-')}-{candidate.report_year}"


def _data_path(candidate: SourceCandidate, revision: int) -> Path:
    if candidate.report_type == "weekly_compstat":
        assert candidate.report_end is not None
        return Path("data") / "weekly" / str(candidate.report_end.year) / (
            f"{candidate.report_end.isoformat()}-r{revision}.csv"
        )
    assert candidate.report_year is not None
    return Path("data") / "year_end_compstat" / f"{candidate.report_year}-r{revision}.csv"


def _manifest_path(candidate: SourceCandidate, revision: int) -> Path:
    if candidate.report_type == "weekly_compstat":
        assert candidate.report_end is not None
        return Path("archive") / "weekly" / str(candidate.report_end.year) / (
            f"{candidate.report_end.isoformat()}-r{revision}.json"
        )
    assert candidate.report_year is not None
    folder = candidate.report_type
    return Path("archive") / folder / f"{candidate.report_year}-r{revision}.json"


def _source_path(candidate: SourceCandidate, revision: int) -> Path:
    """Return the stable, Git-tracked path for an unmodified source PDF."""
    if candidate.report_type == "weekly_compstat":
        assert candidate.report_end is not None
        return Path("sources") / "weekly" / str(candidate.report_end.year) / (
            f"{candidate.report_end.isoformat()}-r{revision}.pdf"
        )
    assert candidate.report_year is not None
    return (
        Path("sources")
        / candidate.report_type
        / f"{candidate.report_year}-r{revision}.pdf"
    )


def _preserve_source_pdf(root: Path, relative_path: Path, pdf_bytes: bytes) -> None:
    """Write a byte-identical source once, refusing an inconsistent overwrite."""
    destination = root / relative_path
    if destination.exists():
        if destination.read_bytes() != pdf_bytes:
            raise ValueError(
                f"Tracked source path already contains different bytes: {relative_path}"
            )
        return
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(pdf_bytes)


def load_reports(root: Path) -> list[dict[str, Any]]:
    path = root / "catalog" / "reports.json"
    if not path.exists():
        return []
    return json.loads(path.read_text(encoding="utf-8"))


def _page_count(pdf_path: Path) -> int:
    return len(PdfReader(str(pdf_path)).pages)


def _release_url(tag: str, asset: str) -> str:
    repository = os.environ.get("GITHUB_REPOSITORY", "")
    if not repository:
        return ""
    return f"https://github.com/{repository}/releases/download/{tag}/{asset}"


def _stage_release(
    root: Path,
    candidate: SourceCandidate,
    pdf_bytes: bytes,
    manifest: dict[str, Any],
) -> dict[str, Any]:
    tag = manifest["release_tag"]
    asset = manifest["release_asset"]
    directory = root / "dist" / "releases" / tag
    directory.mkdir(parents=True, exist_ok=True)
    (directory / asset).write_bytes(pdf_bytes)
    source_path = directory / "source.json"
    _json_dump(source_path, manifest)
    checksums = {
        asset: hashlib.sha256(pdf_bytes).hexdigest(),
        "source.json": hashlib.sha256(source_path.read_bytes()).hexdigest(),
    }
    (directory / "SHA256SUMS").write_text(
        "".join(f"{digest}  {name}\n" for name, digest in checksums.items()),
        encoding="ascii",
    )
    notes = [
        f"# {candidate.title}",
        "",
        f"- Collection: `{candidate.report_type}`",
        f"- Source: {candidate.url}",
        f"- Retrieved: {manifest['fetched_at']}",
        f"- SHA-256: `{manifest['source_sha256']}`",
        f"- Validation: `{manifest['validation_status']}`",
    ]
    if manifest.get("validation_warnings"):
        notes.extend(["", "## Source/extraction warnings", ""])
        notes.extend(f"- {warning}" for warning in manifest["validation_warnings"])
    (directory / "RELEASE_NOTES.md").write_text("\n".join(notes) + "\n", encoding="utf-8")
    return {
        "tag": tag,
        "title": candidate.title + f" (revision {manifest['revision']})",
        "directory": str(directory.relative_to(root)).replace("\\", "/"),
        "notes": str((directory / "RELEASE_NOTES.md").relative_to(root)).replace("\\", "/"),
        "assets": [asset, "source.json", "SHA256SUMS"],
    }


def process_candidate(
    root: Path,
    candidate: SourceCandidate,
    pdf_bytes: bytes,
    fetch_method: str,
    reports: list[dict[str, Any]],
    fetched_at: str | None = None,
) -> tuple[dict[str, Any] | None, dict[str, Any] | None, dict[str, Any] | None]:
    sha256 = hashlib.sha256(pdf_bytes).hexdigest()
    report_key = _report_key(candidate)
    if any(
        report["report_key"] == report_key and report["source_sha256"] == sha256
        for report in reports
    ):
        return None, None, None

    revisions = [
        int(report["revision"]) for report in reports if report["report_key"] == report_key
    ]
    revision = max(revisions, default=0) + 1
    identity = _identity_slug(candidate)
    report_id = f"{identity}-r{revision}"
    release_tag = f"source-{report_id}"
    safe_title = _slug(candidate.title)[:100]
    release_asset = f"{safe_title}-r{revision}.pdf"
    fetched_at = fetched_at or datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    document_id, source_token = document_url_parts(candidate.url)

    tmp_dir = root / "tmp" / "pdfs"
    tmp_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        prefix=report_id + "-", suffix=".pdf", dir=tmp_dir, delete=False
    ) as stream:
        stream.write(pdf_bytes)
        pdf_path = Path(stream.name)

    validation = ValidationResult(status="not_applicable")
    parsed = None
    data_path = ""
    volume = None
    issue_number = None
    page_count = 0
    extraction_error: str | None = None
    try:
        page_count = _page_count(pdf_path)
        if candidate.report_type in {"weekly_compstat", "year_end_compstat"}:
            try:
                parsed = parse_compstat_pdf(pdf_path, candidate.report_type)
                validation = validate_parsed_report(parsed)
                if candidate.report_start and parsed.report_start != candidate.report_start:
                    validation.errors.append(
                        f"Link start date {candidate.report_start} differs from PDF {parsed.report_start}"
                    )
                    validation.status = "failed"
                if candidate.report_end and parsed.report_end != candidate.report_end:
                    validation.errors.append(
                        f"Link end date {candidate.report_end} differs from PDF {parsed.report_end}"
                    )
                    validation.status = "failed"
                volume, issue_number = parsed.volume, parsed.issue_number
            except Exception as error:  # Preserve raw source even when layout changes.
                extraction_error = f"{type(error).__name__}: {error}"
                validation = ValidationResult(status="failed", errors=[extraction_error])
        else:
            validation = ValidationResult(
                status="archived_source_only",
                checks={"page_count": page_count},
            )
    finally:
        pdf_path.unlink(missing_ok=True)

    manifest: dict[str, Any] = {
        "report_id": report_id,
        "report_key": report_key,
        "report_type": candidate.report_type,
        "report_start": candidate.report_start.isoformat() if candidate.report_start else "",
        "report_end": candidate.report_end.isoformat() if candidate.report_end else "",
        "report_year": candidate.report_year or "",
        "revision": revision,
        "title": candidate.title,
        "source_url": candidate.url,
        "source_document_id": document_id or "",
        "source_token": source_token or "",
        "source_path": str(_source_path(candidate, revision)).replace("\\", "/"),
        "source_sha256": sha256,
        "source_size_bytes": len(pdf_bytes),
        "fetched_at": fetched_at,
        "fetch_method": fetch_method,
        "discovery_page": candidate.discovery_page,
        "discovery_method": candidate.discovery_method,
        "page_count": page_count,
        "volume": volume or "",
        "issue_number": issue_number or "",
        "validation_status": validation.status,
        "validation_warning_count": len(validation.warnings),
        "validation_error_count": len(validation.errors),
        "validation_checks": validation.checks,
        "validation_errors": validation.errors,
        "validation_warnings": validation.warnings,
        "extraction_error": extraction_error or "",
        "extraction_version": EXTRACTION_VERSION
        if candidate.report_type in {"weekly_compstat", "year_end_compstat"}
        else "",
        "data_path": "",
        "release_tag": release_tag,
        "release_asset": release_asset,
        "release_url": _release_url(release_tag, release_asset),
    }

    if parsed is not None and validation.status == "validated":
        relative_data_path = _data_path(candidate, revision)
        data_path = str(relative_data_path).replace("\\", "/")
        manifest["data_path"] = data_path
        for observation in parsed.observations:
            observation.update(
                {
                    "report_id": report_id,
                    "report_type": candidate.report_type,
                    "report_start": parsed.report_start.isoformat(),
                    "report_end": parsed.report_end.isoformat(),
                    "report_revision": revision,
                    "source_sha256": sha256,
                    "validation_status": "validated",
                }
            )
        _write_csv(root / relative_data_path, parsed.observations, OBSERVATION_FIELDS)

    manifest_path = _manifest_path(candidate, revision)
    manifest["manifest_path"] = str(manifest_path).replace("\\", "/")
    _preserve_source_pdf(root, _source_path(candidate, revision), pdf_bytes)
    _json_dump(root / manifest_path, manifest)
    release_plan = _stage_release(root, candidate, pdf_bytes, manifest)

    report = {field: manifest.get(field, "") for field in REPORT_FIELDS}
    event_type = "source_revised" if revision > 1 else "report_added"
    event = {
        "event_id": f"{fetched_at}-{report_id}-{event_type}",
        "event_type": event_type,
        "occurred_at": fetched_at,
        "report_id": report_id,
        "report_key": report_key,
        "report_type": candidate.report_type,
        "revision": revision,
        "source_sha256": sha256,
        "previous_sha256": next(
            (
                report["source_sha256"]
                for report in sorted(reports, key=lambda row: int(row["revision"]), reverse=True)
                if report["report_key"] == report_key
            ),
            "",
        ),
        "validation_status": validation.status,
        "warning_count": len(validation.warnings),
        "error_count": len(validation.errors),
        "manifest_path": str(manifest_path).replace("\\", "/"),
        "data_path": data_path,
        "release_tag": release_tag,
    }
    return report, event, release_plan


def _append_events(path: Path, events: list[dict[str, Any]]) -> None:
    if not events:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    existing = path.read_text(encoding="utf-8") if path.exists() else ""
    if existing and not existing.endswith("\n"):
        existing += "\n"
    addition = "".join(json.dumps(event, sort_keys=True) + "\n" for event in events)
    path.write_text(existing + addition, encoding="utf-8")


def load_events(root: Path) -> list[dict[str, Any]]:
    path = root / "catalog" / "events.ndjson"
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def rebuild_changelog(root: Path) -> None:
    events = load_events(root)
    lines = [
        "# Changelog",
        "",
        "Generated from `catalog/events.ndjson`. Source revisions and extraction status",
        "are recorded separately so researchers can identify the exact evidence used.",
        "",
    ]
    if not events:
        lines.extend(["## Unreleased", "", "- No archived reports yet."])
    else:
        by_date: dict[str, list[dict[str, Any]]] = {}
        for event in reversed(events):
            by_date.setdefault(event["occurred_at"][:10], []).append(event)
        for event_date, date_events in by_date.items():
            lines.extend([f"## {event_date}", ""])
            for event in date_events:
                verb = "Added" if event["event_type"] == "report_added" else "Revised"
                detail = (
                    f"{verb} `{event['report_id']}`; SHA-256 "
                    f"`{event['source_sha256']}`; validation "
                    f"`{event['validation_status']}`"
                )
                if event.get("warning_count"):
                    detail += f"; {event['warning_count']} warning(s)"
                lines.append(f"- {detail}.")
            lines.append("")
    (root / "CHANGELOG.md").write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def rebuild_coverage(root: Path, reports: list[dict[str, Any]]) -> None:
    weekly = sorted(
        [report for report in reports if report["report_type"] == "weekly_compstat"],
        key=lambda row: (row["report_end"], int(row["revision"])),
    )
    latest_by_end: dict[str, dict[str, Any]] = {}
    for report in weekly:
        latest_by_end[report["report_end"]] = report
    rows = []
    if latest_by_end:
        first = date.fromisoformat(min(latest_by_end))
        last = date.fromisoformat(max(latest_by_end))
        cursor = first
        while cursor <= last:
            start = cursor - timedelta(days=6)
            report = latest_by_end.get(cursor.isoformat())
            rows.append(
                {
                    "week_start": start.isoformat(),
                    "week_end": cursor.isoformat(),
                    "status": "present" if report else "missing",
                    "report_id": report["report_id"] if report else "",
                    "notes": "" if report else "No source located; data not inferred",
                }
            )
            cursor += timedelta(days=7)
    _write_csv(
        root / "catalog" / "coverage.csv",
        rows,
        ["week_start", "week_end", "status", "report_id", "notes"],
    )


def _write_catalogs(root: Path, reports: list[dict[str, Any]]) -> None:
    reports.sort(
        key=lambda row: (
            row.get("report_end", ""),
            row.get("report_type", ""),
            int(row.get("revision", 0)),
        ),
        reverse=True,
    )
    _json_dump(root / "catalog" / "reports.json", reports)
    _write_csv(root / "catalog" / "reports.csv", reports, REPORT_FIELDS)
    rebuild_coverage(root, reports)


def refresh_catalog(root: Path) -> int:
    root = root.resolve()
    reports = load_reports(root)
    updated = 0
    for report in reports:
        if report["report_type"] == "weekly_compstat":
            candidate = SourceCandidate(
                title=report["title"],
                url=report["source_url"],
                report_type=report["report_type"],
                report_start=date.fromisoformat(report["report_start"]),
                report_end=date.fromisoformat(report["report_end"]),
                report_year=int(report["report_year"]),
            )
        else:
            year = int(report["report_year"])
            candidate = SourceCandidate(
                title=report["title"],
                url=report["source_url"],
                report_type=report["report_type"],
                report_start=date(year, 1, 1),
                report_end=date(year, 12, 31),
                report_year=year,
            )
        relative_path = _manifest_path(candidate, int(report["revision"]))
        manifest_path = root / relative_path
        if not manifest_path.exists():
            continue
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["manifest_path"] = str(relative_path).replace("\\", "/")
        manifest["source_path"] = str(
            _source_path(candidate, int(report["revision"]))
        ).replace("\\", "/")
        manifest["validation_warning_count"] = len(manifest.get("validation_warnings", []))
        manifest["validation_error_count"] = len(manifest.get("validation_errors", []))
        _json_dump(manifest_path, manifest)
        for field in (
            "manifest_path",
            "source_path",
            "validation_warning_count",
            "validation_error_count",
        ):
            report[field] = manifest[field]
        updated += 1
    _write_catalogs(root, reports)
    return updated


def scan(root: Path) -> dict[str, Any]:
    root = root.resolve()
    reports = load_reports(root)
    repository = os.environ.get("GITHUB_REPOSITORY", "")
    catalog_changed = False
    if repository:
        for existing_report in reports:
            expected_url = (
                f"https://github.com/{repository}/releases/download/"
                f"{existing_report['release_tag']}/{existing_report['release_asset']}"
            )
            if existing_report.get("release_url") != expected_url:
                existing_report["release_url"] = expected_url
                catalog_changed = True
    added_reports: list[dict[str, Any]] = []
    events: list[dict[str, Any]] = []
    release_plans: list[dict[str, Any]] = []
    fetch_methods: dict[str, str] = {}
    failures: list[dict[str, str]] = []

    with CityClient() as client:
        candidates, discovery_methods = client.discover()
        fetch_methods.update(discovery_methods)
        for candidate in candidates:
            try:
                pdf_bytes, fetch_method = client.download_pdf(candidate)
                report, event, release_plan = process_candidate(
                    root, candidate, pdf_bytes, fetch_method, reports + added_reports
                )
                if report is not None:
                    added_reports.append(report)
                    assert event is not None and release_plan is not None
                    events.append(event)
                    release_plans.append(release_plan)
                elif os.environ.get("COMPSTAT_BOOTSTRAP_RELEASES") == "1":
                    digest = hashlib.sha256(pdf_bytes).hexdigest()
                    existing = next(
                        (
                            item
                            for item in reports + added_reports
                            if item["report_key"] == _report_key(candidate)
                            and item["source_sha256"] == digest
                        ),
                        None,
                    )
                    if existing is not None:
                        manifest_path = _manifest_path(candidate, int(existing["revision"]))
                        manifest = json.loads((root / manifest_path).read_text(encoding="utf-8"))
                        if repository:
                            manifest["release_url"] = existing["release_url"]
                            _json_dump(root / manifest_path, manifest)
                            catalog_changed = True
                        release_plans.append(
                            _stage_release(root, candidate, pdf_bytes, manifest)
                        )
            except Exception as error:
                failures.append(
                    {
                        "title": candidate.title,
                        "url": candidate.url,
                        "error": f"{type(error).__name__}: {error}",
                    }
                )

    all_reports = reports + added_reports
    if added_reports or catalog_changed:
        _write_catalogs(root, all_reports)
    if added_reports:
        _append_events(root / "catalog" / "events.ndjson", events)
        rebuild_changelog(root)

    plan = {"releases": release_plans}
    _json_dump(root / "dist" / "release-plan.json", plan)
    summary = {
        "checked_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "candidate_count": len(candidates),
        "new_report_count": len(added_reports),
        "release_count": len(release_plans),
        "fetch_methods": fetch_methods,
        "failures": failures,
        "validation_failures": [
            report["report_id"]
            for report in added_reports
            if report["validation_status"] == "failed"
        ],
    }
    _json_dump(root / "dist" / "run-summary.json", summary)
    status_path = root / "catalog" / "status.json"
    previous_status = (
        json.loads(status_path.read_text(encoding="utf-8")) if status_path.exists() else {}
    )
    current_month = summary["checked_at"][:7]
    if previous_status.get("heartbeat_month") != current_month:
        _json_dump(
            status_path,
            {
                "heartbeat_month": current_month,
                "last_successful_scan": summary["checked_at"],
                "candidate_count": summary["candidate_count"],
                "latest_report_id": all_reports[0]["report_id"] if all_reports else "",
            },
        )
    return summary


def ingest_local(
    root: Path,
    pdf_path: Path,
    candidate: SourceCandidate,
) -> dict[str, Any]:
    root = root.resolve()
    reports = load_reports(root)
    report, event, release_plan = process_candidate(
        root,
        candidate,
        pdf_path.read_bytes(),
        "local_ingest",
        reports,
    )
    if report is None:
        summary = {"new_report_count": 0, "message": "Source hash already archived"}
    else:
        reports.append(report)
        _write_catalogs(root, reports)
        assert event is not None and release_plan is not None
        _append_events(root / "catalog" / "events.ndjson", [event])
        rebuild_changelog(root)
        _json_dump(root / "dist" / "release-plan.json", {"releases": [release_plan]})
        summary = {
            "new_report_count": 1,
            "report_id": report["report_id"],
            "validation_status": report["validation_status"],
        }
    _json_dump(root / "dist" / "run-summary.json", summary)
    return summary


def build_site(root: Path, output: Path | None = None) -> Path:
    root = root.resolve()
    output = (output or (root / "_site")).resolve()
    if output == root or output == Path(output.anchor):
        raise ValueError(f"Refusing to build over unsafe output directory: {output}")
    output.mkdir(parents=True, exist_ok=True)
    shutil.copytree(root / "site", output, dirs_exist_ok=True)
    # PDFs stay versioned in Git and are linked through raw.githubusercontent.com.
    # Excluding them here prevents the Pages artifact from duplicating the archive.
    for name in ("catalog", "data", "archive", "schemas"):
        source = root / name
        if source.exists():
            shutil.copytree(source, output / name, dirs_exist_ok=True)
    shutil.copy2(root / "CHANGELOG.md", output / "CHANGELOG.md")
    build_bulk_datasets(root, output / "bulk")
    return output


def _combine_csv_files(files: list[Path], output: Path) -> int:
    output.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with gzip.open(output, "wt", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=OBSERVATION_FIELDS)
        writer.writeheader()
        for path in files:
            with path.open(newline="", encoding="utf-8") as source:
                for row in csv.DictReader(source):
                    writer.writerow({field: row.get(field, "") for field in OBSERVATION_FIELDS})
                    count += 1
    return count


def build_bulk_datasets(root: Path, output: Path) -> dict[str, int]:
    output.mkdir(parents=True, exist_ok=True)
    weekly_files = sorted((root / "data" / "weekly").glob("**/*.csv"))
    annual_files = sorted((root / "data" / "year_end_compstat").glob("*.csv"))
    weekly_count = _combine_csv_files(
        weekly_files, output / "weekly-observations.csv.gz"
    )
    annual_count = _combine_csv_files(
        annual_files, output / "year-end-compstat-observations.csv.gz"
    )

    database_path = output / "compstat.sqlite"
    database_path.unlink(missing_ok=True)
    connection = sqlite3.connect(database_path)
    try:
        numeric_types = {
            "report_revision": "INTEGER",
            "source_page": "INTEGER",
            "observation_year": "INTEGER",
            "comparison_year": "INTEGER",
            "comparison_lag_years": "INTEGER",
            "value_numeric": "REAL",
        }
        connection.execute(
            "CREATE TABLE observations ("
            + ", ".join(
                f'"{field}" {numeric_types.get(field, "TEXT")}'
                for field in OBSERVATION_FIELDS
            )
            + ")"
        )
        placeholders = ",".join("?" for _ in OBSERVATION_FIELDS)
        for path in weekly_files + annual_files:
            with path.open(newline="", encoding="utf-8") as source:
                rows = csv.DictReader(source)
                connection.executemany(
                    f"INSERT INTO observations VALUES ({placeholders})",
                    (
                        [
                            None
                            if field in numeric_types and row.get(field, "") == ""
                            else row.get(field, "")
                            for field in OBSERVATION_FIELDS
                        ]
                        for row in rows
                    ),
                )
        connection.execute("CREATE INDEX observations_report ON observations(report_id)")
        connection.execute(
            "CREATE INDEX observations_analysis ON observations("
            "report_type, geography_code, offense_code, period, statistic)"
        )
        connection.commit()
    finally:
        connection.close()
    return {"weekly_observations": weekly_count, "year_end_observations": annual_count}

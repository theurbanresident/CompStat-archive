from __future__ import annotations

import re
from datetime import date, datetime
from pathlib import Path
from typing import Any, Iterable

import pdfplumber

from .config import EXTRACTION_VERSION, OFFENSES
from .models import ParsedReport


DATE_RANGE_RE = re.compile(
    r"(\d{1,2}/\d{1,2}/\d{2,4})\s+Through\s+(\d{1,2}/\d{1,2}/\d{2,4})",
    re.IGNORECASE,
)
VOLUME_RE = re.compile(
    r"Volume\s+(\d+)(?:\s+Number\s+(\d+))?\s+"
    r"(Citywide|Sector\s+\d+|District\s+\d+)",
    re.IGNORECASE,
)
YEAR_HEADER_RE = re.compile(
    r"\b(20\d{2})\s+(20\d{2})\s+%CHG\s+"
    r"(20\d{2})\s+(20\d{2})\s+%CHG\s+"
    r"(20\d{2})\s+(20\d{2})\s+%CHG",
    re.IGNORECASE,
)
VALUE_RE = re.compile(r"^(?:\*|-?\d+%?)$")


def normalize_text(value: str) -> str:
    replacements = {
        "\u2010": "-",
        "\u2011": "-",
        "\u2012": "-",
        "\u2013": "-",
        "\u2212": "-",
        "\u00a0": " ",
    }
    for old, new in replacements.items():
        value = value.replace(old, new)
    return " ".join(value.split())


def group_words_into_lines(words: Iterable[dict[str, Any]], tolerance: float = 2.5) -> list[str]:
    grouped: list[list[dict[str, Any]]] = []
    tops: list[float] = []
    for word in sorted(words, key=lambda item: (float(item["top"]), float(item["x0"]))):
        top = float(word["top"])
        target = None
        for index, existing_top in enumerate(tops):
            if abs(top - existing_top) <= tolerance:
                target = index
                break
        if target is None:
            tops.append(top)
            grouped.append([word])
        else:
            grouped[target].append(word)
            count = len(grouped[target])
            tops[target] = ((tops[target] * (count - 1)) + top) / count
    ordered = sorted(zip(tops, grouped), key=lambda pair: pair[0])
    return [
        normalize_text(" ".join(str(word["text"]) for word in sorted(row, key=lambda item: float(item["x0"]))))
        for _, row in ordered
    ]


def _parse_pdf_date(value: str) -> date:
    for fmt in ("%m/%d/%y", "%m/%d/%Y"):
        try:
            return datetime.strptime(value, fmt).date()
        except ValueError:
            pass
    raise ValueError(f"Unsupported PDF date: {value}")


def _parse_value(value: str) -> tuple[int | float | None, str | None]:
    if value == "*":
        return None, "undefined_zero_denominator"
    if value.endswith("%"):
        return float(value[:-1]), None
    return int(value), None


def _geography(geography_label: str) -> tuple[str, str]:
    normalized = geography_label.lower().replace(" ", "_")
    if normalized == "citywide":
        return "citywide", "citywide"
    if normalized.startswith("sector_"):
        return "sector", normalized
    if normalized.startswith("district_"):
        return "district", normalized
    raise ValueError(f"Unknown geography: {geography_label}")


def parse_source_row(line: str) -> tuple[str, str, list[str]] | None:
    for label, code in sorted(OFFENSES.items(), key=lambda item: len(item[0]), reverse=True):
        if not line.startswith(label + " "):
            continue
        values = line[len(label) :].strip().split()
        if len(values) != 14 or any(not VALUE_RE.match(value) for value in values):
            raise ValueError(
                f"Expected 14 table values for {label}; found {len(values)} in {line!r}"
            )
        return label, code, values
    return None


def _append_observation(
    observations: list[dict[str, Any]],
    *,
    page_number: int,
    geography_type: str,
    geography_code: str,
    geography_label: str,
    offense_code: str,
    offense_label: str,
    period: str,
    statistic: str,
    observation_year: int | None,
    comparison_year: int | None,
    lag: int | None,
    value: str,
) -> None:
    numeric, null_reason = _parse_value(value)
    observations.append(
        {
            "source_page": page_number,
            "geography_type": geography_type,
            "geography_code": geography_code,
            "geography_label": geography_label,
            "offense_code": offense_code,
            "offense_label": offense_label,
            "period": period,
            "statistic": statistic,
            "observation_year": observation_year,
            "comparison_year": comparison_year,
            "comparison_lag_years": lag,
            "value_numeric": numeric,
            "value_reported": value,
            "null_reason": null_reason,
            "extraction_version": EXTRACTION_VERSION,
            "validation_status": "pending",
        }
    )


def values_to_observations(
    values: list[str],
    *,
    reference_year: int,
    page_number: int,
    geography_type: str,
    geography_code: str,
    geography_label: str,
    offense_code: str,
    offense_label: str,
) -> list[dict[str, Any]]:
    observations: list[dict[str, Any]] = []
    windows = (
        ("last_7_days", values[0:3]),
        ("last_28_days", values[3:6]),
        ("year_to_date", values[6:9]),
    )
    for period, cells in windows:
        _append_observation(
            observations,
            page_number=page_number,
            geography_type=geography_type,
            geography_code=geography_code,
            geography_label=geography_label,
            offense_code=offense_code,
            offense_label=offense_label,
            period=period,
            statistic="count",
            observation_year=reference_year,
            comparison_year=None,
            lag=None,
            value=cells[0],
        )
        _append_observation(
            observations,
            page_number=page_number,
            geography_type=geography_type,
            geography_code=geography_code,
            geography_label=geography_label,
            offense_code=offense_code,
            offense_label=offense_label,
            period=period,
            statistic="count",
            observation_year=reference_year - 1,
            comparison_year=None,
            lag=None,
            value=cells[1],
        )
        _append_observation(
            observations,
            page_number=page_number,
            geography_type=geography_type,
            geography_code=geography_code,
            geography_label=geography_label,
            offense_code=offense_code,
            offense_label=offense_label,
            period=period,
            statistic="percent_change",
            observation_year=reference_year,
            comparison_year=reference_year - 1,
            lag=1,
            value=cells[2],
        )
    for lag, value in enumerate(values[9:14], start=2):
        _append_observation(
            observations,
            page_number=page_number,
            geography_type=geography_type,
            geography_code=geography_code,
            geography_label=geography_label,
            offense_code=offense_code,
            offense_label=offense_label,
            period="year_to_date",
            statistic="percent_change",
            observation_year=reference_year,
            comparison_year=reference_year - lag,
            lag=lag,
            value=value,
        )
    return observations


def parse_compstat_pdf(path: str | Path, report_type: str) -> ParsedReport:
    path = Path(path)
    if report_type not in {"weekly_compstat", "year_end_compstat"}:
        raise ValueError(f"Table extraction is not defined for {report_type}")

    source_rows: list[dict[str, Any]] = []
    observations: list[dict[str, Any]] = []
    report_start: date | None = None
    report_end: date | None = None
    reference_year: int | None = None
    volume: int | None = None
    issue_number: int | None = None
    table_page_count = 0

    with pdfplumber.open(path) as pdf:
        page_count = len(pdf.pages)
        for page_number, page in enumerate(pdf.pages, start=1):
            words = page.extract_words(
                x_tolerance=2,
                y_tolerance=3,
                keep_blank_chars=False,
                use_text_flow=False,
            )
            lines = group_words_into_lines(words)
            full_text = "\n".join(lines)
            if "CRIME COMPLAINTS" not in full_text:
                continue
            table_page_count += 1

            geography_match = VOLUME_RE.search(full_text)
            if not geography_match:
                raise ValueError(f"Could not identify geography on page {page_number}")
            page_volume, page_issue, geography_label = geography_match.groups()
            volume = volume or int(page_volume)
            if page_issue:
                issue_number = issue_number or int(page_issue)
            geography_label = normalize_text(geography_label).title()
            geography_type, geography_code = _geography(geography_label)

            date_match = DATE_RANGE_RE.search(full_text)
            if date_match:
                page_start = _parse_pdf_date(date_match.group(1))
                page_end = _parse_pdf_date(date_match.group(2))
            elif report_type == "year_end_compstat":
                year_match = YEAR_HEADER_RE.search(full_text)
                if not year_match:
                    raise ValueError(f"Could not identify report year on page {page_number}")
                page_year = int(year_match.group(1))
                page_start, page_end = date(page_year, 1, 1), date(page_year, 12, 31)
            else:
                raise ValueError(f"Could not identify report dates on page {page_number}")

            if report_start is None:
                report_start, report_end = page_start, page_end
                reference_year = page_end.year
            elif (report_start, report_end) != (page_start, page_end):
                raise ValueError(f"Inconsistent report dates on page {page_number}")

            page_source_rows = 0
            for line in lines:
                parsed = parse_source_row(line)
                if parsed is None:
                    continue
                offense_label, offense_code, values = parsed
                page_source_rows += 1
                source_rows.append(
                    {
                        "source_page": page_number,
                        "geography_type": geography_type,
                        "geography_code": geography_code,
                        "geography_label": geography_label,
                        "offense_code": offense_code,
                        "offense_label": offense_label,
                        "values": values,
                    }
                )
                assert reference_year is not None
                observations.extend(
                    values_to_observations(
                        values,
                        reference_year=reference_year,
                        page_number=page_number,
                        geography_type=geography_type,
                        geography_code=geography_code,
                        geography_label=geography_label,
                        offense_code=offense_code,
                        offense_label=offense_label,
                    )
                )
            if page_source_rows != len(OFFENSES):
                raise ValueError(
                    f"Expected {len(OFFENSES)} offense rows on page {page_number}; "
                    f"found {page_source_rows}"
                )

    if report_start is None or report_end is None or reference_year is None:
        raise ValueError("No CompStat statistical tables were found")
    return ParsedReport(
        report_start=report_start,
        report_end=report_end,
        reference_year=reference_year,
        volume=volume,
        issue_number=issue_number,
        page_count=page_count,
        table_page_count=table_page_count,
        source_rows=source_rows,
        observations=observations,
    )

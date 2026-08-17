from __future__ import annotations

from collections import defaultdict
from typing import Any

from .config import CURRENT_TEMPLATE, GEOGRAPHY_PARENT, MAJOR_CRIME_CODES, OFFENSES
from .models import ParsedReport, ValidationResult


def _count_index(observations: list[dict[str, Any]]) -> dict[tuple[Any, ...], int]:
    result: dict[tuple[Any, ...], int] = {}
    for row in observations:
        if row["statistic"] != "count" or row["value_numeric"] is None:
            continue
        key = (
            row["geography_code"],
            row["offense_code"],
            row["period"],
            row["observation_year"],
        )
        result[key] = int(row["value_numeric"])
    return result


def validate_parsed_report(parsed: ParsedReport) -> ValidationResult:
    errors: list[str] = []
    warnings: list[str] = []
    checks: dict[str, Any] = {}
    geographies = {row["geography_code"] for row in parsed.source_rows}

    expectations = {
        "page_count": (parsed.page_count, CURRENT_TEMPLATE.page_count),
        "table_page_count": (parsed.table_page_count, CURRENT_TEMPLATE.table_page_count),
        "geography_count": (len(geographies), CURRENT_TEMPLATE.geography_count),
        "source_row_count": (
            len(parsed.source_rows),
            CURRENT_TEMPLATE.geography_count * CURRENT_TEMPLATE.offense_count,
        ),
        "observation_count": (
            len(parsed.observations),
            CURRENT_TEMPLATE.geography_count * CURRENT_TEMPLATE.offense_count * 14,
        ),
    }
    for name, (actual, expected) in expectations.items():
        checks[name] = {"actual": actual, "expected": expected}
        if actual != expected:
            errors.append(f"{name}: expected {expected}, found {actual}")

    expected_offenses = set(OFFENSES.values())
    for geography in sorted(geographies):
        found = {
            row["offense_code"]
            for row in parsed.source_rows
            if row["geography_code"] == geography
        }
        if found != expected_offenses:
            errors.append(
                f"{geography}: offense set differs; missing={sorted(expected_offenses-found)}, "
                f"extra={sorted(found-expected_offenses)}"
            )

    counts = _count_index(parsed.observations)
    total_checks = 0
    for geography in geographies:
        for period in ("last_7_days", "last_28_days", "year_to_date"):
            for year in (parsed.reference_year, parsed.reference_year - 1):
                component_keys = [(geography, code, period, year) for code in MAJOR_CRIME_CODES]
                total_key = (geography, "major_crime_total", period, year)
                if all(key in counts for key in component_keys) and total_key in counts:
                    total_checks += 1
                    calculated = sum(counts[key] for key in component_keys)
                    if calculated != counts[total_key]:
                        errors.append(
                            f"{geography} {period} {year}: major crime total "
                            f"reported {counts[total_key]}, calculated {calculated}"
                        )
    checks["major_crime_total_checks"] = total_checks

    rollup_checks = 0
    children: dict[str, list[str]] = defaultdict(list)
    for child, parent in GEOGRAPHY_PARENT.items():
        if child in geographies and parent in geographies:
            children[parent].append(child)
    for parent, child_codes in children.items():
        for offense in OFFENSES.values():
            for period in ("last_7_days", "last_28_days", "year_to_date"):
                for year in (parsed.reference_year, parsed.reference_year - 1):
                    parent_key = (parent, offense, period, year)
                    child_keys = [(child, offense, period, year) for child in child_codes]
                    if parent_key in counts and all(key in counts for key in child_keys):
                        rollup_checks += 1
                        calculated = sum(counts[key] for key in child_keys)
                        if calculated != counts[parent_key]:
                            errors.append(
                                f"{parent} {offense} {period} {year}: rollup "
                                f"reported {counts[parent_key]}, calculated {calculated}"
                            )
    checks["geography_rollup_checks"] = rollup_checks

    percent_checks = 0
    for row in parsed.observations:
        if row["statistic"] != "percent_change" or row["comparison_lag_years"] != 1:
            continue
        current_key = (
            row["geography_code"],
            row["offense_code"],
            row["period"],
            parsed.reference_year,
        )
        prior_key = (
            row["geography_code"],
            row["offense_code"],
            row["period"],
            parsed.reference_year - 1,
        )
        if current_key not in counts or prior_key not in counts:
            continue
        current, prior = counts[current_key], counts[prior_key]
        percent_checks += 1
        if prior == 0:
            if row["value_reported"] not in {"*", "0%"}:
                warnings.append(
                    f"{row['geography_code']} {row['offense_code']} {row['period']}: "
                    f"prior is zero but source prints {row['value_reported']}"
                )
            continue
        calculated = ((current - prior) / prior) * 100
        reported = row["value_numeric"]
        if reported is None or abs(float(reported) - calculated) > 1.0:
            warnings.append(
                f"{row['geography_code']} {row['offense_code']} {row['period']}: "
                f"source percent reported {row['value_reported']}, "
                f"calculated {calculated:.2f}%"
            )
    checks["one_year_percent_checks"] = percent_checks

    return ValidationResult(
        status="validated" if not errors else "failed",
        errors=errors,
        warnings=warnings,
        checks=checks,
    )

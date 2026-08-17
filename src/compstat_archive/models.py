from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date
from typing import Any


@dataclass(frozen=True)
class SourceCandidate:
    title: str
    url: str
    report_type: str
    report_start: date | None = None
    report_end: date | None = None
    report_year: int | None = None
    discovery_page: str | None = None
    discovery_method: str = "live_city_page"

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        for key in ("report_start", "report_end"):
            if value[key] is not None:
                value[key] = value[key].isoformat()
        return value


@dataclass
class ParsedReport:
    report_start: date
    report_end: date
    reference_year: int
    volume: int | None
    issue_number: int | None
    page_count: int
    table_page_count: int
    source_rows: list[dict[str, Any]] = field(default_factory=list)
    observations: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class ValidationResult:
    status: str
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    checks: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


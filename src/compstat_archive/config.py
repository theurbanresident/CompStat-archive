from __future__ import annotations

from dataclasses import dataclass


COMPSTAT_PAGE = (
    "https://www.wilmingtonde.gov/government/public-safety/"
    "wilmington-police-department/compstat-reports"
)
YEAR_END_PAGE = (
    "https://www.wilmingtonde.gov/government/public-safety/"
    "wilmington-police-department/wpd-year-end-report"
)
BASE_URL = "https://www.wilmingtonde.gov"
EXTRACTION_VERSION = "wilmington-compstat-v1"
USER_AGENT = (
    "WilmingtonCompStatArchive/0.1 "
    "(+https://github.com/OWNER/wilmington-compstat-archive; research archive)"
)

OFFENSES = {
    "Murder": "murder",
    "Rape": "rape",
    "Robbery": "robbery",
    "Agg. Assault": "aggravated_assault",
    "Burglary": "burglary",
    "Felony Theft": "felony_theft",
    "Auto Theft": "auto_theft",
    "TOTAL": "major_crime_total",
    "Shooting Incidents": "shooting_incidents",
    "Shooting Victims": "shooting_victims",
    "*Juv Shooting Incidents": "juvenile_shooting_incidents",
    "*Juv Shooting Victims": "juvenile_shooting_victims",
    "Theft (Misdemeanor)": "misdemeanor_theft",
}

MAJOR_CRIME_CODES = (
    "murder",
    "rape",
    "robbery",
    "aggravated_assault",
    "burglary",
    "felony_theft",
    "auto_theft",
)

GEOGRAPHY_PARENT = {
    "sector_1": "citywide",
    "district_12": "sector_1",
    "district_13": "sector_1",
    "district_14": "sector_1",
    "sector_2": "citywide",
    "district_10": "sector_2",
    "district_11": "sector_2",
    "district_16": "sector_2",
    "sector_3": "citywide",
    "district_17": "sector_3",
    "district_18": "sector_3",
    "district_19": "sector_3",
}

OBSERVATION_FIELDS = [
    "report_id",
    "report_type",
    "report_start",
    "report_end",
    "report_revision",
    "source_sha256",
    "source_page",
    "geography_type",
    "geography_code",
    "geography_label",
    "offense_code",
    "offense_label",
    "period",
    "statistic",
    "observation_year",
    "comparison_year",
    "comparison_lag_years",
    "value_numeric",
    "value_reported",
    "null_reason",
    "extraction_version",
    "validation_status",
]

REPORT_FIELDS = [
    "report_id",
    "report_key",
    "report_type",
    "report_start",
    "report_end",
    "report_year",
    "revision",
    "title",
    "source_url",
    "source_document_id",
    "source_token",
    "source_path",
    "source_sha256",
    "source_size_bytes",
    "fetched_at",
    "page_count",
    "volume",
    "issue_number",
    "validation_status",
    "validation_warning_count",
    "validation_error_count",
    "extraction_version",
    "data_path",
    "manifest_path",
    "release_tag",
    "release_asset",
    "release_url",
]


@dataclass(frozen=True)
class TemplateExpectation:
    page_count: int = 25
    table_page_count: int = 13
    geography_count: int = 13
    offense_count: int = 13
    values_per_source_row: int = 14


CURRENT_TEMPLATE = TemplateExpectation()

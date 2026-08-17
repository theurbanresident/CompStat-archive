# Wilmington CompStat Archive

Public archive of [Wilmington Police Department CompStat reports](https://www.wilmingtonde.gov/government/public-safety/wilmington-police-department/compstat-reports), including the original PDFs and research-ready CSV data.

[Browse the archive](https://theurbanresident.github.io/CompStat-archive/) · [View releases](https://github.com/theurbanresident/CompStat-archive/releases) · [Read the changelog](CHANGELOG.md)

## Data

- [Counts-only running tally](data/compiled/count-tallies.csv): one row per report, geography, and offense, with 7-day, 28-day, and year-to-date counts. Weekly snapshots are `weekly_running`; year-end snapshots are `year_end_final`.
- [Weekly observations](data/weekly/): normalized weekly counts and reported percentage changes.
- [Calendar year-end observations](data/year_end_compstat/): normalized final-year snapshots.
- [Report catalog](catalog/reports.csv): report dates, source URLs, hashes, validation status, and file locations.
- [Original PDFs](sources/): weekly, calendar year-end CompStat, and narrative WPD year-end reports.

Schemas and code dictionaries are in [`schemas/`](schemas/) and [`data/dictionaries/`](data/dictionaries/). Bulk compressed CSVs and SQLite are available through the [archive site](https://theurbanresident.github.io/CompStat-archive/).

## Quality and provenance

Each PDF is stored unchanged and identified by SHA-256. Extracted values retain the printed value in `value_reported`. Counts and percentages are distinguished by `value_unit`; percentages also include a normalized `value_ratio`.

When a reported percentage can be checked from displayed counts, the result is stored in `calculated_value_numeric`. Source arithmetic discrepancies are preserved and marked `source_arithmetic_mismatch` and `source_warning`; they are not silently corrected.

CompStat figures are preliminary and may be revised. Categories reflect Delaware criminal codes and are not interchangeable with FBI Uniform Crime Reporting categories.

## Automation

GitHub Actions scans the City source Monday evening and Wednesday morning in New York time. New or revised PDFs, CSVs, catalogs, the counts tally, and the changelog are committed automatically. Extraction failures are archived and reported without publishing unvalidated rows.

## Run locally

Python 3.11 or later is required.

```powershell
python -m pip install -e .
python -m playwright install chromium
compstat-archive scan --root .
compstat-archive rebuild-data --root .
compstat-archive build-site --root .
python -m unittest discover -s tests -v
```

This is an independent, unofficial research archive. Original documents are attributed to the City of Wilmington, Delaware.

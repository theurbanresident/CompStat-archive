# Wilmington CompStat Archive

This repository preserves Wilmington Police Department CompStat PDFs and
converts their statistical tables into documented, research-ready data.

The pipeline treats the source PDF as evidence and the extracted tables as a
versioned interpretation:

1. Discover weekly, calendar year-end CompStat, and narrative WPD year-end
   report links from the City's two official landing pages.
2. Download with a polite HTTP client and fall back to a real browser when the
   City's CDN rejects scripted requests.
3. Identify every source revision by SHA-256. A reused City document ID or URL
   is never treated as proof that a file is unchanged.
4. Commit the exact, byte-identical PDF under `sources/` and stage a redundant
   copy with source metadata and checksums for an immutable GitHub Release.
5. Extract embedded PDF words into a fixed, versioned table model.
6. Validate row structure, arithmetic, geography rollups, dates, and reported
   percentages before publishing tabular data.
7. Update the machine-readable catalog, append-only event log, human
   changelog, and accessible GitHub Pages site.

## Collections

- `weekly_compstat`: weekly citywide, sector, and district tables.
- `year_end_compstat`: calendar year-end CompStat tables, kept separate from
  weekly reports even though the layout is similar.
- `wpd_year_end_report`: narrative annual reports, cataloged separately and
  not passed through the CompStat table parser.

## Run locally

Python 3.11 or later is required.

```powershell
python -m pip install -e .
python -m playwright install chromium
compstat-archive scan --root .
compstat-archive build-site --root .
python -m unittest discover -s tests -v
```

To test a local PDF without contacting the City:

```powershell
compstat-archive ingest --root . --pdf path\to\report.pdf `
  --title "WPD CompStat Report - August 3 through August 9, 2026" `
  --url "https://www.wilmingtonde.gov/..." --report-type weekly_compstat
```

Original PDFs are committed under `sources/` so every Git revision remains a
self-contained research archive. Release files are also staged under
`dist/releases/`, which is excluded from Git, and published by GitHub Actions
as a redundant download channel. The Pages site links to the Git-tracked PDFs
through `raw.githubusercontent.com`; it does not duplicate them in the Pages
deployment artifact.

## Research entry points

- `catalog/reports.csv` and `catalog/reports.json`: one record per source
  revision.
- `catalog/events.ndjson`: append-only archive activity.
- `catalog/coverage.csv`: expected and observed weekly coverage.
- `sources/weekly/`: original weekly PDFs, organized by report-ending year.
- `sources/year_end_compstat/`: original calendar year-end CompStat PDFs.
- `sources/wpd_year_end_report/`: original narrative annual PDFs.
- `data/weekly/`: normalized weekly observations.
- `data/year_end_compstat/`: normalized annual snapshots.
- `schemas/observations.schema.json`: field-level contract.
- `data/dictionaries/`: stable offense and geography codes.

`value_reported` always preserves the printed cell. A printed `*` becomes an
empty `value_numeric` with `null_reason=undefined_zero_denominator`; it is not
silently converted to zero.

## Automation behavior

The scheduled workflow scans Monday evening and Wednesday morning in New York
time. Unchanged hashes cause a clean no-op. A structurally valid PDF is still
archived if extraction fails, but unvalidated table rows are not published.
Failures create or update a GitHub issue with diagnostics. A monthly heartbeat
records successful monitoring so GitHub does not disable the scheduled
workflow for repository inactivity.

While the repository is private, collection, validation, Git commits, private
release assets, and issue reporting continue normally. Pages configuration,
artifact upload, and deployment are skipped automatically. After the repository
becomes public, the next workflow run enables the Pages portion of the pipeline.

Before enabling public Pages:

1. Enable GitHub Pages with **GitHub Actions** as the source.
2. Enable immutable releases in repository settings.
3. Permit Actions to create and approve repository content, releases, Pages
   deployments, and issues as configured in the workflow.
4. Run the workflow manually once with **bootstrap_releases** enabled. This
   redownloads the cataloged seed documents and publishes their immutable
   source releases. The PDFs remain available directly in Git as well.

The current source collection is small enough for ordinary Git storage. If the
archive later approaches GitHub's repository-size limits, migrate the PDF
download channel to releases or external object storage. Git LFS is not used
because GitHub Pages cannot serve LFS objects directly.

## Limits and responsible use

The monitor makes only a few requests per scheduled run, identifies itself,
and uses retry/backoff. Do not increase the schedule to a high-frequency
crawler. Historical backfill must record whether a file came from the live
City site, a City news page, or a web archive; missing weeks are recorded as
gaps and never inferred.

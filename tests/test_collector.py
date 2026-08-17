from __future__ import annotations

import unittest
from datetime import date

from compstat_archive.collector import (
    classify_link,
    discover_from_html,
    document_url_parts,
    parse_weekly_dates,
)
from compstat_archive.config import COMPSTAT_PAGE, YEAR_END_PAGE


class CollectorTests(unittest.TestCase):
    def test_weekly_date_range(self) -> None:
        self.assertEqual(
            parse_weekly_dates("WPD CompStat Report - August 3 through August 9, 2026"),
            (date(2026, 8, 3), date(2026, 8, 9)),
        )

    def test_weekly_date_range_crosses_year(self) -> None:
        self.assertEqual(
            parse_weekly_dates("WPD CompStat Report - December 28 through January 3, 2027"),
            (date(2026, 12, 28), date(2027, 1, 3)),
        )

    def test_discovery_separates_collections(self) -> None:
        html = """
        <a href="/home/showpublisheddocument/8310/123">WPD CompStat Report - August 3 through August 9, 2026</a>
        <a href="/home/showpublisheddocument/14006/456">The 2025 Calendar Year-End CompStat report can be accessed here</a>
        """
        candidates = discover_from_html(html, COMPSTAT_PAGE)
        self.assertEqual([item.report_type for item in candidates], [
            "weekly_compstat", "year_end_compstat"
        ])
        self.assertEqual(candidates[0].report_end, date(2026, 8, 9))
        self.assertEqual(candidates[1].report_year, 2025)

    def test_narrative_year_end_classification(self) -> None:
        candidate = classify_link(
            "/home/showpublisheddocument/13762/123",
            "Click here to download the WPD's 2025 Year-End Report",
            YEAR_END_PAGE,
        )
        self.assertIsNotNone(candidate)
        self.assertEqual(candidate.report_type, "wpd_year_end_report")

    def test_document_url_parts(self) -> None:
        self.assertEqual(
            document_url_parts("https://example.test/home/showpublisheddocument/8310/639219"),
            ("8310", "639219"),
        )


if __name__ == "__main__":
    unittest.main()


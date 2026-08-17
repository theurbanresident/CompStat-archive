from __future__ import annotations

import os
import unittest
from datetime import date
from pathlib import Path

from compstat_archive.parser import (
    group_words_into_lines,
    parse_compstat_pdf,
    parse_source_row,
    values_to_observations,
)
from compstat_archive.models import ParsedReport
from compstat_archive.validator import validate_parsed_report


class ParserTests(unittest.TestCase):
    def test_source_row_parses_fourteen_values(self) -> None:
        parsed = parse_source_row(
            "Robbery 6 6 0% 17 25 -32% 132 119 11% 27% 13% 4% 22% -14%"
        )
        self.assertIsNotNone(parsed)
        label, code, values = parsed
        self.assertEqual((label, code), ("Robbery", "robbery"))
        self.assertEqual(len(values), 14)

    def test_star_is_preserved_as_explained_null(self) -> None:
        rows = values_to_observations(
            ["0", "0", "*", "0", "0", "*", "0", "0", "*", "*", "*", "*", "*", "*"],
            reference_year=2026,
            page_number=1,
            geography_type="citywide",
            geography_code="citywide",
            geography_label="Citywide",
            offense_code="murder",
            offense_label="Murder",
        )
        percent = next(row for row in rows if row["statistic"] == "percent_change")
        self.assertEqual(percent["value_reported"], "*")
        self.assertIsNone(percent["value_numeric"])
        self.assertEqual(percent["value_unit"], "percent")
        self.assertIsNone(percent["value_ratio"])
        self.assertEqual(percent["null_reason"], "undefined_zero_denominator")

    def test_source_percent_mismatch_is_preserved_and_flagged(self) -> None:
        rows = values_to_observations(
            ["0", "0", "*", "0", "2", "-40%", "6", "11", "-45%", "-40%", "-57%", "-67%", "-60%", "-76%"],
            reference_year=2026,
            page_number=9,
            geography_type="district",
            geography_code="district_14",
            geography_label="District 14",
            offense_code="robbery",
            offense_label="Robbery",
        )
        parsed = ParsedReport(
            report_start=date(2026, 8, 3),
            report_end=date(2026, 8, 9),
            reference_year=2026,
            volume=10,
            issue_number=32,
            page_count=1,
            table_page_count=1,
            source_rows=[{"geography_code": "district_14", "offense_code": "robbery"}],
            observations=rows,
        )
        result = validate_parsed_report(parsed)
        target = next(
            row
            for row in rows
            if row["period"] == "last_28_days"
            and row["statistic"] == "percent_change"
        )
        self.assertEqual(target["value_reported"], "-40%")
        self.assertEqual(target["value_numeric"], -40.0)
        self.assertEqual(target["value_ratio"], -0.4)
        self.assertEqual(target["calculated_value_numeric"], -100.0)
        self.assertEqual(target["calculation_status"], "source_mismatch")
        self.assertEqual(target["quality_flag"], "source_arithmetic_mismatch")
        self.assertEqual(target["validation_status"], "source_warning")
        self.assertTrue(any("calculated -100.00%" in warning for warning in result.warnings))

    def test_word_lines_use_coordinates_not_input_order(self) -> None:
        words = [
            {"text": "2", "top": 20.1, "x0": 100},
            {"text": "Robbery", "top": 20.0, "x0": 10},
            {"text": "Murder", "top": 10.0, "x0": 10},
            {"text": "0", "top": 10.2, "x0": 100},
        ]
        self.assertEqual(group_words_into_lines(words), ["Murder 0", "Robbery 2"])

    @unittest.skipUnless(os.environ.get("COMPSTAT_TEST_PDF"), "No integration PDF configured")
    def test_real_pdf_fixture(self) -> None:
        parsed = parse_compstat_pdf(Path(os.environ["COMPSTAT_TEST_PDF"]), "weekly_compstat")
        result = validate_parsed_report(parsed)
        self.assertIn(result.status, {"validated", "validated_with_warnings"}, result.errors)
        self.assertEqual(len(parsed.source_rows), 169)
        self.assertEqual(len(parsed.observations), 2366)


if __name__ == "__main__":
    unittest.main()

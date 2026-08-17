from __future__ import annotations

import os
import unittest
from pathlib import Path

from compstat_archive.parser import (
    group_words_into_lines,
    parse_compstat_pdf,
    parse_source_row,
    values_to_observations,
)
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
        self.assertEqual(percent["null_reason"], "undefined_zero_denominator")

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
        self.assertEqual(result.status, "validated", result.errors)
        self.assertEqual(len(parsed.source_rows), 169)
        self.assertEqual(len(parsed.observations), 2366)


if __name__ == "__main__":
    unittest.main()


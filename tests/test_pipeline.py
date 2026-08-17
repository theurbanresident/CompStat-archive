from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from compstat_archive.pipeline import build_site


class PipelineTests(unittest.TestCase):
    def test_static_site_contains_catalog(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "site"
            root = Path(__file__).resolve().parents[1]
            built = build_site(root, output)
            self.assertTrue((built / "index.html").exists())
            catalog = json.loads((built / "catalog" / "reports.json").read_text())
            self.assertIsInstance(catalog, list)
            self.assertTrue((built / "schemas" / "observations.schema.json").exists())
            self.assertTrue((built / "bulk" / "weekly-observations.csv.gz").exists())
            self.assertTrue((built / "bulk" / "compstat.sqlite").exists())


if __name__ == "__main__":
    unittest.main()

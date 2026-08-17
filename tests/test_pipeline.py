from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from compstat_archive.pipeline import _release_url, build_site


class PipelineTests(unittest.TestCase):
    def test_private_repository_has_no_unpublished_release_url(self) -> None:
        with patch.dict(
            "os.environ",
            {
                "GITHUB_REPOSITORY": "owner/archive",
                "COMPSTAT_REPOSITORY_VISIBILITY": "private",
            },
            clear=True,
        ):
            self.assertEqual(_release_url("source-example", "example.pdf"), "")

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
            for report in catalog:
                source = root / report["source_path"]
                self.assertTrue(source.exists(), report["source_path"])
                self.assertFalse((built / report["source_path"]).exists())
                self.assertEqual(
                    hashlib.sha256(source.read_bytes()).hexdigest(),
                    report["source_sha256"],
                )


if __name__ == "__main__":
    unittest.main()

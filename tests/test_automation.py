from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from compstat_archive.automation import publish_releases


class AutomationTests(unittest.TestCase):
    def test_release_uses_default_branch_target(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            release_dir = root / "dist" / "releases" / "source-example-r1"
            release_dir.mkdir(parents=True)
            for name in ("example.pdf", "source.json", "SHA256SUMS", "RELEASE_NOTES.md"):
                (release_dir / name).write_text("fixture", encoding="utf-8")
            plan = {
                "releases": [
                    {
                        "tag": "source-example-r1",
                        "title": "Example (revision 1)",
                        "directory": "dist/releases/source-example-r1",
                        "notes": "dist/releases/source-example-r1/RELEASE_NOTES.md",
                        "assets": ["example.pdf", "source.json", "SHA256SUMS"],
                    }
                ]
            }
            (root / "dist" / "release-plan.json").write_text(
                json.dumps(plan), encoding="utf-8"
            )

            calls: list[list[str]] = []

            def fake_run(args: list[str], *, check: bool = True):
                calls.append(args)
                return subprocess.CompletedProcess(
                    args, 1 if args[:3] == ["gh", "release", "view"] else 0, "", ""
                )

            with patch("compstat_archive.automation._run", side_effect=fake_run):
                self.assertEqual(publish_releases(root), 0)

            create = next(args for args in calls if args[:3] == ["gh", "release", "create"])
            self.assertNotIn("--target", create)


if __name__ == "__main__":
    unittest.main()

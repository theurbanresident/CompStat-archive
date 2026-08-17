from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path
from typing import Any


def _run(args: list[str], *, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, check=check, text=True, capture_output=True)


def publish_releases(root: Path) -> int:
    plan_path = root / "dist" / "release-plan.json"
    if not plan_path.exists():
        print("No release plan found")
        return 0
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    for release in plan.get("releases", []):
        tag = release["tag"]
        if _run(["gh", "release", "view", tag], check=False).returncode == 0:
            print(f"Release {tag} already exists; leaving it unchanged")
            continue
        directory = root / release["directory"]
        assets = [str(directory / asset) for asset in release["assets"]]
        command = [
            "gh",
            "release",
            "create",
            tag,
            *assets,
            "--draft",
            "--title",
            release["title"],
            "--notes-file",
            str(root / release["notes"]),
            "--target",
            "HEAD",
        ]
        _run(command)
        _run(["gh", "release", "edit", tag, "--draft=false"])
        print(f"Published {tag}")
    return 0


def _issue_body(summary: dict[str, Any]) -> str:
    lines = [
        "The scheduled archive run preserved any valid source PDFs but found conditions that need review.",
        "",
    ]
    for failure in summary.get("failures", []):
        lines.extend(
            [
                f"- **Download/discovery:** {failure['title']}",
                f"  - URL: {failure['url']}",
                f"  - Error: `{failure['error']}`",
            ]
        )
    for report_id in summary.get("validation_failures", []):
        lines.append(f"- **Extraction validation failed:** `{report_id}`")
    lines.extend(
        [
            "",
            f"Run timestamp: `{summary.get('checked_at', 'unknown')}`",
            "",
            "Review the archived manifest and workflow logs. Do not manually edit published CSV rows; fix the parser or validation rule and reprocess with a new extraction version.",
        ]
    )
    return "\n".join(lines)


def report_failures(root: Path) -> int:
    summary_path = root / "dist" / "run-summary.json"
    if not summary_path.exists():
        return 0
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    if not summary.get("failures") and not summary.get("validation_failures"):
        print("No pipeline issue required")
        return 0
    title = "CompStat archive pipeline needs attention"
    _run(
        [
            "gh",
            "label",
            "create",
            "pipeline-failure",
            "--color",
            "B60205",
            "--description",
            "Automated archive download, extraction, or validation failure",
            "--force",
        ],
        check=False,
    )
    result = _run(
        [
            "gh",
            "issue",
            "list",
            "--state",
            "open",
            "--label",
            "pipeline-failure",
            "--search",
            f"{title} in:title",
            "--json",
            "number",
            "--jq",
            ".[0].number",
        ],
        check=False,
    )
    body = _issue_body(summary)
    issue_number = result.stdout.strip()
    if issue_number:
        _run(["gh", "issue", "comment", issue_number, "--body", body])
        print(f"Updated issue #{issue_number}")
    else:
        _run(
            [
                "gh",
                "issue",
                "create",
                "--title",
                title,
                "--label",
                "pipeline-failure",
                "--body",
                body,
            ]
        )
        print("Created pipeline issue")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("publish-releases", "report-failures"))
    parser.add_argument("--root", type=Path, default=Path.cwd())
    args = parser.parse_args()
    if args.command == "publish-releases":
        return publish_releases(args.root.resolve())
    return report_failures(args.root.resolve())


if __name__ == "__main__":
    raise SystemExit(main())

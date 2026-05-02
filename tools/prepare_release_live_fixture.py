from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools.export_release_ci_artifacts import (
    _SYNTHETIC_RELEASE_DIR,
    _prepare_release_fixture,
    _prepare_runtime_reports,
)


def write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def write_markdown(path: Path, payload: dict[str, object]) -> None:
    lines = [
        "# Release Live Fixture",
        "",
        f"- Status: {'passed' if payload.get('ok') else 'blocked'}",
        f"- Channel: {payload.get('channel')}",
        f"- Manifest: {payload.get('manifest_path')}",
        f"- Build: {payload.get('build_id') or ''}",
        "",
        "| Artifact | Path |",
        "| --- | --- |",
    ]
    for item in list(payload.get("runtime_reports") or []):
        lines.append(f"| runtime_report | {item} |")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def build_preview(channel: str, report_path: str, markdown_path: str) -> dict[str, object]:
    return {
        "ok": True,
        "preview": True,
        "channel": channel,
        "report_path": report_path,
        "markdown_path": markdown_path,
        "release_dir": str(_SYNTHETIC_RELEASE_DIR).replace("\\", "/"),
        "manifest_path": "api_server/static/dist/release_manifest.json",
        "runtime_reports": [
            "logs/reports/doctor_self_check.json",
            "logs/reports/clean_machine_bootstrap.json",
            "logs/reports/full_live_validation.json",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Prepare a synthetic local release-live fixture.")
    parser.add_argument("--channel", default="release", help="Release channel for the synthetic fixture.")
    parser.add_argument("--report-path", default="logs/reports/release_live_fixture.json", help="Path for fixture JSON evidence.")
    parser.add_argument("--markdown-path", default="logs/reports/release_live_fixture.md", help="Path for fixture Markdown evidence.")
    parser.add_argument("--preview", action="store_true", help="Print planned fixture paths without writing files.")
    args = parser.parse_args()
    report_path = Path(args.report_path)
    markdown_path = Path(args.markdown_path)

    if args.preview:
        print(json.dumps(build_preview(args.channel, str(report_path), str(markdown_path)), ensure_ascii=False, indent=2))
        return 0

    manifest = _prepare_release_fixture(channel=args.channel)
    _prepare_runtime_reports(manifest)
    payload = {
        "schema_version": "1.0",
        "ok": True,
        "preview": False,
        "channel": args.channel,
        "build_id": manifest.get("build_id"),
        "version": manifest.get("version"),
        "report_path": str(report_path),
        "markdown_path": str(markdown_path),
        "manifest_path": "api_server/static/dist/release_manifest.json",
        "release_manifest_path": manifest.get("release_manifest_path"),
        "runtime_reports": [
            "logs/reports/doctor_self_check.json",
            "logs/reports/clean_machine_bootstrap.json",
            "logs/reports/full_live_validation.json",
        ],
    }
    write_json(report_path, payload)
    write_markdown(markdown_path, payload)
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

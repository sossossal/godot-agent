from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

SYNTHETIC_RELEASE_DIR = Path("api_server/static/dist/web_release_validation_ci")
STABLE_RELEASE_MANIFEST_PATH = Path("api_server/static/dist/release_manifest.json")


def write_json(path: Path, payload: dict[str, Any]) -> None:
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


def build_release_manifest(channel: str) -> dict[str, Any]:
    return {
        "schema_version": "1.0",
        "build_id": f"web-{channel}-ci-001",
        "version": f"0.1.0-{channel}+ci1",
        "channel": channel,
        "preset_name": "Web",
        "platform": "web",
        "generated_at": "2026-04-15T09:00:00Z",
        "output_path": "api_server/static/dist/web_release_validation_ci/index.html",
        "release_dir": "api_server/static/dist/web_release_validation_ci",
        "release_url": "/portal/dist/index.html",
        "versioned_release_url": "/portal/dist/web_release_validation_ci/index.html",
        "build_log_path": "api_server/static/dist/web_release_validation_ci/build.log",
        "release_notes_path": "api_server/static/dist/web_release_validation_ci/release_notes.md",
        "release_manifest_path": "api_server/static/dist/web_release_validation_ci/release_manifest.json",
        "feature": {
            "schema_version": "1.0",
            "feature_id": "feature-ci-release",
            "owner": "release_engineer",
            "priority": "high",
            "risk": "medium",
            "feature_status": "approved",
        },
        "change_summary": ["ci preflight release fixture"],
        "acceptance_checklist": [{"label": "preflight manifest", "status": "ready"}],
        "quality_gate": {
            "schema_version": "1.0",
            "passed": True,
            "channel": channel,
            "preset_name": "Web",
            "checks": [{"name": "preflight_fixture", "status": "passed", "message": "ok"}],
            "blocked_checks": [],
            "warning_checks": [],
            "metrics": {},
        },
        "qa_evidence": {
            "schema_version": "1.0",
            "smoke_status": "passed",
            "smoke_message": "preflight fixture only",
        },
        "files": [
            {"path": "index.html", "size": 13, "sha256": "abc"},
            {"path": "release_notes.md", "size": 16, "sha256": "def"},
        ],
        "rollback_hint": "restore web_release_validation_ci",
    }


def prepare_preflight_fixture(channel: str) -> dict[str, Any]:
    release_dir = (REPO_ROOT / SYNTHETIC_RELEASE_DIR).resolve()
    dist_dir = (REPO_ROOT / "api_server" / "static" / "dist").resolve()
    release_dir.mkdir(parents=True, exist_ok=True)
    dist_dir.mkdir(parents=True, exist_ok=True)

    manifest = build_release_manifest(channel)
    write_json(release_dir / "release_manifest.json", manifest)
    write_json(REPO_ROOT / STABLE_RELEASE_MANIFEST_PATH, manifest)
    (release_dir / "index.html").write_text("<html></html>\n", encoding="utf-8")
    (release_dir / "build.log").write_text("build ok\n", encoding="utf-8")
    (release_dir / "release_notes.md").write_text("# Release Validation Notes\n", encoding="utf-8")
    (dist_dir / "release_notes.md").write_text("# Stable Release Validation Notes\n", encoding="utf-8")
    return manifest


def prepare_full_fixture(channel: str) -> dict[str, Any]:
    from tools.export_release_ci_artifacts import _prepare_release_fixture, _prepare_runtime_reports

    manifest = _prepare_release_fixture(channel=channel)
    _prepare_runtime_reports(manifest)
    return manifest


def build_preview(channel: str, scope: str, report_path: str, markdown_path: str) -> dict[str, object]:
    return {
        "ok": True,
        "preview": True,
        "channel": channel,
        "fixture_scope": scope,
        "report_path": report_path,
        "markdown_path": markdown_path,
        "release_dir": str(SYNTHETIC_RELEASE_DIR).replace("\\", "/"),
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
    parser.add_argument(
        "--scope",
        choices=("preflight", "full"),
        default="full",
        help="Use 'preflight' to write only the manifest files required by live preflight.",
    )
    parser.add_argument("--report-path", default="logs/reports/release_live_fixture.json", help="Path for fixture JSON evidence.")
    parser.add_argument("--markdown-path", default="logs/reports/release_live_fixture.md", help="Path for fixture Markdown evidence.")
    parser.add_argument("--preview", action="store_true", help="Print planned fixture paths without writing files.")
    args = parser.parse_args()
    report_path = Path(args.report_path)
    markdown_path = Path(args.markdown_path)

    if args.preview:
        print(json.dumps(build_preview(args.channel, args.scope, str(report_path), str(markdown_path)), ensure_ascii=False, indent=2))
        return 0

    manifest = prepare_preflight_fixture(args.channel) if args.scope == "preflight" else prepare_full_fixture(args.channel)
    payload = {
        "schema_version": "1.0",
        "ok": True,
        "preview": False,
        "channel": args.channel,
        "fixture_scope": args.scope,
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

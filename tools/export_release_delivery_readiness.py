from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from agent_system.tools.release_delivery_readiness import export_release_delivery_readiness  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Export release delivery readiness JSON and Markdown reports.")
    parser.add_argument("--project-root", default=".", help="Project root containing deployment manifests.")
    parser.add_argument("--runtime-root", default="", help="Runtime root containing logs/reports. Defaults to project root.")
    parser.add_argument("--channel", default="release", help="Target release channel.")
    parser.add_argument("--target-environment", default="", help="Target environment label. Defaults from the channel.")
    parser.add_argument("--artifact-dir", default="logs/reports/release_live_ci", help="Runtime-root-relative live CI artifact directory.")
    parser.add_argument("--workflow", default="", help="Release live workflow name or path.")
    parser.add_argument("--repo", default="", help="Optional GitHub owner/repo for dispatch preflight.")
    parser.add_argument("--ref", default="", help="Optional Git ref for dispatch preflight.")
    parser.add_argument("--token-env-names", default="", help="Comma-separated token env var names checked by dispatch preflight.")
    parser.add_argument("--report-path", default="", help="Optional runtime-root-relative JSON report path.")
    parser.add_argument("--markdown-path", default="", help="Optional runtime-root-relative Markdown report path.")
    parser.add_argument("--fail-on-blockers", action="store_true", help="Return a non-zero exit code when readiness is blocked.")
    args = parser.parse_args(argv)

    payload = export_release_delivery_readiness(
        args.project_root,
        runtime_root=args.runtime_root or args.project_root,
        target_channel=args.channel,
        target_environment=args.target_environment,
        artifact_dir=args.artifact_dir,
        workflow=args.workflow or "release-live-gates.yml",
        repo=args.repo,
        ref=args.ref,
        token_env_names=[item.strip() for item in args.token_env_names.split(",") if item.strip()] or "",
        report_path=args.report_path,
        markdown_path=args.markdown_path,
    )
    print(
        json.dumps(
            {
                "ok": True,
                "status": payload.get("status"),
                "summary": payload.get("summary"),
                "target_channel": payload.get("target_channel"),
                "target_environment": payload.get("target_environment"),
                "report_path": payload.get("report_path"),
                "report_markdown_path": payload.get("report_markdown_path"),
                "next_action_count": len(list(payload.get("next_actions") or [])),
                "blocking_checks": payload.get("blocking_checks"),
                "warning_checks": payload.get("warning_checks"),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    if args.fail_on_blockers and str(payload.get("status") or "").strip().lower() == "blocked":
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

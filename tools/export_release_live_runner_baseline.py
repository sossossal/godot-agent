from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from agent_system.tools.release_live_runner_baseline import (  # noqa: E402
    build_release_live_runner_baseline,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Export a release-live Windows runner baseline report.")
    parser.add_argument("--project-root", default=str(REPO_ROOT), help="Project root containing scripts and config.yaml.")
    parser.add_argument("--runtime-root", default=str(REPO_ROOT), help="Runtime root containing logs/reports and release artifacts.")
    parser.add_argument("--channel", default="release", help="Target release channel.")
    parser.add_argument("--target-environment", default="production", help="Target environment label.")
    parser.add_argument("--release-manifest-path", default="api_server/static/dist/release_manifest.json", help="Runtime-root-relative release manifest path.")
    parser.add_argument("--report-path", default="", help="Optional runtime-root-relative report path override.")
    parser.add_argument("--browser-path", default="", help="Optional explicit Chrome/Edge executable path.")
    parser.add_argument("--config-path", default="config.yaml", help="Project-root-relative config.yaml path.")
    parser.add_argument("--runner-profile-path", default="deployment/release_live_runner_profile.json", help="Project-root-relative runner profile manifest path.")
    parser.add_argument("--declared-runner-labels", default="", help="Optional JSON array or comma-separated runner labels declared by the workflow.")
    parser.add_argument("--fail-on-blockers", action="store_true", help="Return a non-zero exit code when the baseline is blocked.")
    args = parser.parse_args(argv)

    payload = build_release_live_runner_baseline(
        args.project_root,
        runtime_root=args.runtime_root,
        target_channel=args.channel,
        target_environment=args.target_environment,
        release_manifest_path=args.release_manifest_path,
        report_path=args.report_path,
        browser_path=args.browser_path,
        config_path=args.config_path,
        runner_profile_path=args.runner_profile_path,
        declared_runner_labels=args.declared_runner_labels,
    )
    print(
        json.dumps(
            {
                "ok": True,
                "status": payload.get("status"),
                "summary": payload.get("summary"),
                "report_path": payload.get("report_path"),
                "blocking_checks": payload.get("blocking_checks"),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    if args.fail_on_blockers and str(payload.get("status") or "") == "blocked":
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

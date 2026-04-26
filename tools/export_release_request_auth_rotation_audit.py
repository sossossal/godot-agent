from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agent_system.tools.release_request_auth import export_release_request_auth_rotation_audit_report


def main() -> int:
    parser = argparse.ArgumentParser(description="Export a redacted release request auth rotation audit.")
    parser.add_argument("--project-root", default=".", help="Project root containing deployment/release_request_auth.json.")
    parser.add_argument("--runtime-root", default="", help="Runtime root where logs/reports should be written. Defaults to project root.")
    parser.add_argument("--channel", default="staging", help="Target channel to evaluate.")
    parser.add_argument("--target-environment", default="", help="Target environment to evaluate.")
    parser.add_argument("--action", action="append", default=[], help="Release write action to audit; repeat or omit to use defaults.")
    parser.add_argument("--output-path", default="", help="Optional runtime-root-relative output path override.")
    args = parser.parse_args()

    runtime_root = args.runtime_root or args.project_root
    payload = export_release_request_auth_rotation_audit_report(
        args.project_root,
        runtime_root=runtime_root,
        target_channel=args.channel,
        target_environment=args.target_environment,
        actions=args.action or None,
        output_path=args.output_path,
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

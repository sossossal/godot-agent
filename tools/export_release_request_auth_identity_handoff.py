from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from agent_system.tools.release_request_auth import export_release_request_auth_identity_handoff  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Export a redacted identity/session/secret-rotation handoff package.")
    parser.add_argument("--project-root", default=".", help="Project root containing deployment manifests.")
    parser.add_argument("--runtime-root", default="", help="Runtime root for logs/reports outputs. Defaults to project root.")
    parser.add_argument("--channel", default="staging", help="Target release channel.")
    parser.add_argument("--target-environment", default="", help="Target environment label. Defaults from the channel.")
    parser.add_argument("--actions", default="", help="Comma-separated release write actions. Defaults to promotion_record,release_execution.")
    parser.add_argument("--auth-path", default="", help="Optional project-root-relative release_request_auth manifest path.")
    parser.add_argument("--identity-path", default="", help="Optional project-root-relative release_identity_registry manifest path.")
    parser.add_argument("--release-manifest-path", default="", help="Optional runtime-root-relative release manifest path to bind into the handoff metadata.")
    args = parser.parse_args(argv)

    payload = export_release_request_auth_identity_handoff(
        args.project_root,
        runtime_root=args.runtime_root or args.project_root,
        target_channel=args.channel,
        target_environment=args.target_environment,
        actions=[item.strip() for item in args.actions.split(",") if item.strip()],
        auth_path=args.auth_path,
        identity_path=args.identity_path,
        release_manifest_path=args.release_manifest_path,
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

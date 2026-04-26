from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agent_system.tools.release_distribution import record_release_distribution_publish_receipt


def main() -> int:
    parser = argparse.ArgumentParser(description="Record an external publish receipt for a verified release distribution bundle.")
    parser.add_argument("--project-root", default=".", help="Project root containing deployment/release_distribution_delivery.json.")
    parser.add_argument("--runtime-root", default="", help="Runtime root containing the exported release bundle. Defaults to project root.")
    parser.add_argument("--channel", default="staging", help="Target promotion channel.")
    parser.add_argument("--target-environment", default="", help="Target environment label.")
    parser.add_argument("--release-manifest-path", default="", help="Optional runtime-root-relative release manifest path override.")
    parser.add_argument("--report-path", default="", help="Optional runtime-root-relative distribution bundle report path override.")
    parser.add_argument("--target-id", required=True, help="Publish target id declared in release_distribution_delivery.json.")
    parser.add_argument("--status", default="published", help="Receipt status, for example published / verified / failed.")
    parser.add_argument("--external-reference", default="", help="External release or distribution reference id.")
    parser.add_argument("--artifact-url", default="", help="External URL for the published artifact.")
    parser.add_argument("--operator", default="", help="Operator or system that completed the publish step.")
    parser.add_argument("--published-at", default="", help="Optional ISO timestamp override.")
    parser.add_argument("--notes", action="append", default=[], help="Optional note line. Can be repeated.")
    args = parser.parse_args()

    runtime_root = args.runtime_root or args.project_root
    payload = record_release_distribution_publish_receipt(
        args.project_root,
        runtime_root=runtime_root,
        target_channel=args.channel,
        target_environment=args.target_environment,
        release_manifest_path=args.release_manifest_path,
        report_path=args.report_path,
        target_id=args.target_id,
        status=args.status,
        external_reference=args.external_reference,
        artifact_url=args.artifact_url,
        operator=args.operator,
        published_at=args.published_at,
        notes=list(args.notes or []),
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

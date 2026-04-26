from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agent_system.tools.release_distribution import export_release_distribution_archive


def main() -> int:
    parser = argparse.ArgumentParser(description="Export a zip archive for a verified release distribution bundle.")
    parser.add_argument("--project-root", default=".", help="Project root containing docs/支持矩阵与分发说明.md.")
    parser.add_argument("--runtime-root", default="", help="Runtime root containing the exported release bundle. Defaults to project root.")
    parser.add_argument("--channel", default="staging", help="Target promotion channel.")
    parser.add_argument("--target-environment", default="", help="Target environment label.")
    parser.add_argument("--release-manifest-path", default="", help="Optional runtime-root-relative release manifest path override.")
    parser.add_argument("--report-path", default="", help="Optional runtime-root-relative distribution bundle report path override.")
    args = parser.parse_args()

    runtime_root = args.runtime_root or args.project_root
    payload = export_release_distribution_archive(
        args.project_root,
        runtime_root=runtime_root,
        target_channel=args.channel,
        target_environment=args.target_environment,
        release_manifest_path=args.release_manifest_path,
        report_path=args.report_path,
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

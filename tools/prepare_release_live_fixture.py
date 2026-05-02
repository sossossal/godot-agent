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


def build_preview(channel: str) -> dict[str, object]:
    return {
        "ok": True,
        "preview": True,
        "channel": channel,
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
    parser.add_argument("--preview", action="store_true", help="Print planned fixture paths without writing files.")
    args = parser.parse_args()

    if args.preview:
        print(json.dumps(build_preview(args.channel), ensure_ascii=False, indent=2))
        return 0

    manifest = _prepare_release_fixture(channel=args.channel)
    _prepare_runtime_reports(manifest)
    print(
        json.dumps(
            {
                "ok": True,
                "preview": False,
                "channel": args.channel,
                "build_id": manifest.get("build_id"),
                "version": manifest.get("version"),
                "manifest_path": "api_server/static/dist/release_manifest.json",
                "release_manifest_path": manifest.get("release_manifest_path"),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import List

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agent_system.tools.release_request_auth import build_release_request_token_spec


def _split_list(raw_value: str) -> List[str]:
    return [item.strip() for item in str(raw_value or "").split(",") if item.strip()]


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate a release_request_auth manifest token digest entry.")
    parser.add_argument("--token-id", required=True, help="Stable token identifier to store in the manifest.")
    parser.add_argument("--token-value", required=True, help="Plaintext token to hash into token_sha256.")
    parser.add_argument("--action", action="append", default=[], help="Allowed action; repeat or pass comma-separated values.")
    parser.add_argument("--channel", action="append", default=[], help="Allowed channel; repeat or pass comma-separated values.")
    parser.add_argument("--target-environment", action="append", default=[], help="Allowed target environment; repeat or pass comma-separated values.")
    parser.add_argument("--actor-id", action="append", default=[], help="Allowed executed_by actor; repeat or pass comma-separated values.")
    parser.add_argument("--expires-at", default="", help="Optional ISO-8601 expiry timestamp.")
    parser.add_argument("--session-id", default="", help="Optional session identifier for auditable release sessions.")
    parser.add_argument("--issued-by", default="", help="Optional issuer for the session-backed token.")
    parser.add_argument("--issued-at", default="", help="Optional ISO-8601 issued_at timestamp for the session-backed token.")
    args = parser.parse_args()

    spec = build_release_request_token_spec(
        token_id=args.token_id,
        token_value=args.token_value,
        actions=[item for raw in args.action for item in _split_list(raw)],
        channels=[item for raw in args.channel for item in _split_list(raw)],
        target_environments=[item for raw in args.target_environment for item in _split_list(raw)],
        actor_ids=[item for raw in args.actor_id for item in _split_list(raw)],
        expires_at=args.expires_at,
        session_id=args.session_id,
        issued_by=args.issued_by,
        issued_at=args.issued_at,
    )
    print(json.dumps(spec, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

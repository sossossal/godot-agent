from __future__ import annotations

import json
import shutil
import unittest
from pathlib import Path

from tools.run_portal_browser_click_smoke import (
    _build_execution_browser_summary,
    _build_history_browser_summary,
    _seed_temp_project_release_control_plane,
)


project_root = Path(__file__).resolve().parents[1]


class PortalBrowserClickSmokeTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_project = project_root / "tests" / ".tmp_portal_click_smoke_project"
        shutil.rmtree(self.temp_project, ignore_errors=True)
        self.temp_project.mkdir(parents=True, exist_ok=True)

    def tearDown(self) -> None:
        shutil.rmtree(self.temp_project, ignore_errors=True)

    def test_seed_temp_project_release_control_plane_writes_minimal_release_manifests(self) -> None:
        _seed_temp_project_release_control_plane(self.temp_project)

        deployment_dir = self.temp_project / "deployment"
        access_policy = json.loads((deployment_dir / "release_access_policy.json").read_text(encoding="utf-8"))
        request_auth = json.loads((deployment_dir / "release_request_auth.json").read_text(encoding="utf-8"))
        identity_boundary = json.loads((deployment_dir / "release_identity_boundary.json").read_text(encoding="utf-8"))

        self.assertEqual(access_policy["schema_version"], "1.0")
        self.assertIn(
            "promotion_record",
            {str(item.get("action") or "") for item in access_policy["rules"]},
        )
        execution_rules = [
            item for item in access_policy["rules"]
            if str(item.get("action") or "") == "release_execution"
        ]
        self.assertTrue(any("canary" in list(item.get("operations") or []) for item in execution_rules))
        self.assertTrue(any("full_rollout" in list(item.get("operations") or []) for item in execution_rules))
        self.assertTrue(any("rollback" in list(item.get("operations") or []) for item in execution_rules))

        self.assertTrue(request_auth["allow_local_without_token"])
        self.assertEqual(request_auth["tokens"], [])

        profiles = list(identity_boundary.get("profiles") or [])
        self.assertEqual(len(profiles), 1)
        self.assertEqual(profiles[0]["profile_id"], "staging_identity_boundary")
        self.assertFalse(profiles[0]["session_policy"]["required"])

    def test_build_history_browser_summary_keeps_only_portal_fields(self) -> None:
        summary = _build_history_browser_summary(
            {
                "visible_count": 3,
                "latest_record": {
                    "decision": "approved",
                    "executed_by": "release_manager",
                    "target_channel": "staging",
                    "target_environment": "staging",
                    "release_live_ci_status": "passed",
                    "distribution_status": "completed",
                    "extra_field": "ignored",
                },
                "records": [{"decision": "approved"}],
            }
        )

        self.assertEqual(summary["visible_count"], 3)
        self.assertEqual(summary["latest_record"]["decision"], "approved")
        self.assertEqual(summary["latest_record"]["executed_by"], "release_manager")
        self.assertNotIn("records", summary)
        self.assertNotIn("extra_field", summary["latest_record"])

    def test_build_execution_browser_summary_keeps_only_portal_fields(self) -> None:
        summary = _build_execution_browser_summary(
            {
                "channel_count": 1,
                "latest_execution": {
                    "operation": "rollback",
                    "target_channel": "staging",
                    "target_environment": "staging",
                    "execution_status": "completed",
                    "extra_field": "ignored",
                },
                "channel_entries": [
                    {
                        "channel_id": "staging",
                        "rollout_stage": "rolled_back",
                        "rollout_percentage": 15,
                        "active_public_url": "/portal/dist/web_123/index.html",
                        "extra_field": "ignored",
                    }
                ],
            }
        )

        self.assertEqual(summary["channel_count"], 1)
        self.assertEqual(summary["latest_execution"]["operation"], "rollback")
        self.assertEqual(len(summary["channel_entries"]), 1)
        self.assertEqual(summary["channel_entries"][0]["rollout_stage"], "rolled_back")
        self.assertNotIn("extra_field", summary["latest_execution"])
        self.assertNotIn("extra_field", summary["channel_entries"][0])


if __name__ == "__main__":
    unittest.main()

import json
import shutil
import sys
import unittest
from pathlib import Path


project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from agent_system.tools.release_capability_policy import (  # noqa: E402
    build_release_capability_policy,
    build_release_capability_policy_report,
)
from agent_system.tools.release_request_auth import build_release_request_token_spec  # noqa: E402


class ReleaseCapabilityPolicyTestCase(unittest.TestCase):
    def setUp(self):
        self.project_dir = project_root / "tests" / ".tmp_release_capability_policy_project"
        self.runtime_dir = project_root / "tests" / ".tmp_release_capability_policy_runtime"
        shutil.rmtree(self.project_dir, ignore_errors=True)
        shutil.rmtree(self.runtime_dir, ignore_errors=True)
        self.project_dir.mkdir(parents=True, exist_ok=True)
        self.runtime_dir.mkdir(parents=True, exist_ok=True)

    def tearDown(self):
        shutil.rmtree(self.project_dir, ignore_errors=True)
        shutil.rmtree(self.runtime_dir, ignore_errors=True)

    def _write_registry(self):
        registry_path = self.project_dir / "deployment" / "release_capability_registry.json"
        registry_path.parent.mkdir(parents=True, exist_ok=True)
        registry_path.write_text(
            json.dumps(
                {
                    "schema_version": "1.0",
                    "registry_id": "release_control_plane_capabilities",
                    "capabilities": [
                        {
                            "capability_id": "release_execution_rollout_write",
                            "label": "Release Execution Rollout",
                            "group": "release_control_plane",
                            "surface_types": ["command", "gateway_method"],
                            "risk_level": "critical",
                            "requires_actor": True,
                            "requires_request_auth": True,
                            "default_enabled": True,
                            "optional_heavy": False,
                            "sandbox_profile": "release_write",
                            "artifact_contracts": ["release_execution_status"],
                            "entrypoints": ["/release-execution/run"],
                            "policy_action": "release_execution",
                            "policy_operation": "canary",
                            "owners": ["release_manager", "ops"],
                        },
                        {
                            "capability_id": "portal_browser_click_smoke_run",
                            "label": "Portal Click Smoke",
                            "group": "release_runtime",
                            "surface_types": ["tool", "command"],
                            "risk_level": "medium",
                            "requires_actor": False,
                            "requires_request_auth": False,
                            "default_enabled": False,
                            "optional_heavy": True,
                            "sandbox_profile": "browser_automation",
                            "artifact_contracts": ["release_live_ci_summary", "release_artifact_manifest"],
                            "entrypoints": [
                                "python tools/run_portal_browser_click_smoke.py",
                                "/release-artifact-manifest",
                            ],
                            "owners": ["qa_lead"],
                        },
                    ],
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

    def _write_access_policy(self):
        policy_path = self.project_dir / "deployment" / "release_access_policy.json"
        policy_path.parent.mkdir(parents=True, exist_ok=True)
        policy_path.write_text(
            json.dumps(
                {
                    "schema_version": "1.0",
                    "actors": [
                        {"actor_id": "release_manager", "roles": ["release_manager"]},
                    ],
                    "rules": [
                        {
                            "rule_id": "execution_rollout_qa_staging",
                            "action": "release_execution",
                            "operations": ["canary", "full_rollout"],
                            "channels": ["qa", "staging"],
                            "roles": ["release_manager"],
                        }
                    ],
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

    def _write_request_auth_manifest(self):
        auth_path = self.project_dir / "deployment" / "release_request_auth.json"
        auth_path.parent.mkdir(parents=True, exist_ok=True)
        spec = build_release_request_token_spec(
            token_id="staging_release_manager",
            token_value="manifest-release-secret",
            actions=["release_execution"],
            channels=["staging"],
            target_environments=["staging"],
            actor_ids=["release_manager"],
            expires_at="2099-01-01T00:00:00Z",
        )
        auth_path.write_text(
            json.dumps(
                {
                    "schema_version": "1.0",
                    "allow_local_without_token": False,
                    "tokens": [spec],
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

    def _write_identity_boundary(self):
        manifest_path = self.project_dir / "deployment" / "release_identity_boundary.json"
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        manifest_path.write_text(
            json.dumps(
                {
                    "schema_version": "1.0",
                    "profiles": [
                        {
                            "profile_id": "staging_identity_boundary",
                            "target_channels": ["staging"],
                            "target_environments": ["staging"],
                            "provider_mode": "project_manifest",
                            "provider_id": "local_manifest",
                            "session_policy": {
                                "required": False,
                                "backend": "manifest",
                                "max_session_age_hours": 0,
                            },
                            "secret_rotation": {
                                "required": False,
                                "backend": "manifest",
                                "owner": "ops",
                                "rotation_window_days": 30,
                            },
                        }
                    ],
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

    def test_portal_route_allows_rollout_when_actor_and_posture_are_valid(self):
        self._write_registry()
        self._write_access_policy()
        self._write_request_auth_manifest()
        self._write_identity_boundary()

        payload = build_release_capability_policy(
            self.project_dir,
            runtime_root=self.runtime_dir,
            route_kind="portal",
            target_channel="staging",
            target_environment="staging",
            actor_id="release_manager",
        )

        self.assertEqual(payload["status"], "blocked")
        self.assertEqual(payload["allowed_count"], 1)
        self.assertEqual(payload["denied_count"], 1)
        rollout = next(
            item for item in payload["capabilities"]
            if item["capability_id"] == "release_execution_rollout_write"
        )
        browser = next(
            item for item in payload["capabilities"]
            if item["capability_id"] == "portal_browser_click_smoke_run"
        )
        self.assertEqual(rollout["policy_status"], "passed")
        self.assertTrue(rollout["invocation_allowed"])
        self.assertEqual(rollout["authorization_status"], "passed")
        self.assertEqual(rollout["request_auth_posture_status"], "passed")
        self.assertEqual(browser["policy_status"], "blocked")
        self.assertIn("release_artifact_manifest", browser["artifact_contracts"])
        self.assertIn("/release-artifact-manifest", browser["entrypoints"])
        self.assertIn("optional_heavy_disabled", browser["denial_reasons"])
        self.assertIn("browser_automation_disabled", browser["denial_reasons"])

    def test_local_replay_route_blocks_release_write_but_allows_browser_optional_heavy(self):
        self._write_registry()
        self._write_access_policy()
        self._write_request_auth_manifest()
        self._write_identity_boundary()

        payload = build_release_capability_policy(
            self.project_dir,
            runtime_root=self.runtime_dir,
            route_kind="local_replay",
            target_channel="staging",
            target_environment="staging",
            actor_id="release_manager",
        )

        self.assertEqual(payload["warning_count"], 0)
        self.assertEqual(payload["allowed_count"], 1)
        self.assertEqual(payload["denied_count"], 1)

        browser = next(
            item for item in payload["capabilities"]
            if item["capability_id"] == "portal_browser_click_smoke_run"
        )
        rollout = next(
            item for item in payload["capabilities"]
            if item["capability_id"] == "release_execution_rollout_write"
        )
        self.assertEqual(browser["policy_status"], "passed")
        self.assertTrue(browser["invocation_allowed"])
        self.assertEqual(rollout["policy_status"], "blocked")
        self.assertIn("release_write_disabled", rollout["denial_reasons"])

    def test_policy_warns_and_blocks_invocation_when_registry_capability_has_manifest_gap(self):
        registry_path = self.project_dir / "deployment" / "release_capability_registry.json"
        registry_path.parent.mkdir(parents=True, exist_ok=True)
        registry_path.write_text(
            json.dumps(
                {
                    "schema_version": "1.0",
                    "registry_id": "release_control_plane_capabilities",
                    "capabilities": [
                        {
                            "capability_id": "release_delivery_readiness_read",
                            "label": "Release Delivery Readiness",
                            "group": "release_governance",
                            "surface_types": ["command", "gateway_method"],
                            "risk_level": "medium",
                            "requires_actor": False,
                            "requires_request_auth": False,
                            "default_enabled": True,
                            "optional_heavy": False,
                            "sandbox_profile": "read_only",
                            "artifact_contracts": ["release_delivery_readiness", "release_live_ci_summary"],
                            "entrypoints": ["/release-delivery-readiness"],
                            "owners": ["ops"],
                        },
                    ],
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

        payload = build_release_capability_policy(
            self.project_dir,
            runtime_root=self.runtime_dir,
            route_kind="portal",
            target_channel="staging",
            target_environment="staging",
            actor_id="release_manager",
        )
        capability = payload["capabilities"][0]

        self.assertEqual(payload["status"], "warning")
        self.assertEqual(payload["allowed_count"], 0)
        self.assertEqual(payload["warning_count"], 1)
        self.assertEqual(capability["policy_status"], "warning")
        self.assertFalse(capability["invocation_allowed"])
        self.assertIn("capability_registry_warning", capability["warning_reasons"])
        self.assertIn("release_artifact_manifest", capability["missing_fields"])

    def test_report_surfaces_denial_and_route_profile(self):
        self._write_registry()
        payload = build_release_capability_policy(
            self.project_dir,
            runtime_root=self.runtime_dir,
            route_kind="portal",
            target_channel="staging",
            target_environment="staging",
            actor_id="",
        )
        report = build_release_capability_policy_report(payload)

        self.assertIn("# Release Capability Policy", report)
        self.assertIn("Route Profile:", report)
        self.assertIn("contracts=release_live_ci_summary,release_artifact_manifest", report)
        self.assertIn("entrypoints=python tools/run_portal_browser_click_smoke.py,/release-artifact-manifest", report)
        self.assertIn("browser_automation_disabled", report)
        self.assertIn("actor_required", report)


if __name__ == "__main__":
    unittest.main()

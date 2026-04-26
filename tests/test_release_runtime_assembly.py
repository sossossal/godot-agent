import json
import shutil
import sys
import unittest
from pathlib import Path


project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from agent_system.tools.release_request_auth import build_release_request_token_spec  # noqa: E402
from agent_system.tools.release_runtime_assembly import (  # noqa: E402
    build_release_runtime_assembly_report_lines,
    build_release_runtime_assembly_snapshot,
)


class ReleaseRuntimeAssemblyTestCase(unittest.TestCase):
    def setUp(self):
        self.project_dir = project_root / "tests" / ".tmp_release_runtime_assembly_project"
        self.runtime_dir = project_root / "tests" / ".tmp_release_runtime_assembly_runtime"
        shutil.rmtree(self.project_dir, ignore_errors=True)
        shutil.rmtree(self.runtime_dir, ignore_errors=True)
        self.project_dir.mkdir(parents=True, exist_ok=True)
        self.runtime_dir.mkdir(parents=True, exist_ok=True)

    def tearDown(self):
        shutil.rmtree(self.project_dir, ignore_errors=True)
        shutil.rmtree(self.runtime_dir, ignore_errors=True)

    def _write_registry(self):
        manifest_path = self.project_dir / "deployment" / "release_capability_registry.json"
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        manifest_path.write_text(
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
                            "entrypoints": ["python tools/run_portal_browser_click_smoke.py"],
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
        manifest_path = self.project_dir / "deployment" / "release_access_policy.json"
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        manifest_path.write_text(
            json.dumps(
                {
                    "schema_version": "1.0",
                    "actors": [{"actor_id": "release_manager", "roles": ["release_manager"]}],
                    "rules": [
                        {
                            "rule_id": "execution_rollout_staging",
                            "action": "release_execution",
                            "operations": ["canary"],
                            "channels": ["staging"],
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
        spec = build_release_request_token_spec(
            token_id="staging_release_manager",
            token_value="manifest-release-secret",
            actions=["release_execution"],
            channels=["staging"],
            target_environments=["staging"],
            actor_ids=["release_manager"],
            expires_at="2099-01-01T00:00:00Z",
        )
        manifest_path = self.project_dir / "deployment" / "release_request_auth.json"
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        manifest_path.write_text(
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

    def test_snapshot_summarizes_route_capabilities_identity_and_runner_profile(self):
        self._write_registry()
        self._write_access_policy()
        self._write_request_auth_manifest()
        self._write_identity_boundary()

        snapshot = build_release_runtime_assembly_snapshot(
            self.project_dir,
            runtime_root=self.runtime_dir,
            route_kind="github_workflow",
            target_channel="staging",
            target_environment="staging",
            actor_id="release_manager",
            invocation_source="github_workflow",
            session_id="web-staging-001",
            runner_baseline={
                "status": "passed",
                "runner_profile_path": "deployment/release_live_runner_profile.json",
                "runner_profile_id": "release_windows_runner",
                "runner_name": "godot-release-01",
                "runner_os": "Windows",
                "runner_arch": "x64",
                "declared_runner_labels": ["self-hosted", "windows", "godot"],
            },
        )

        self.assertEqual(snapshot["route_kind"], "github_workflow")
        self.assertEqual(snapshot["invocation_source"], "github_workflow")
        self.assertEqual(snapshot["runner_profile"]["profile_id"], "release_windows_runner")
        self.assertEqual(snapshot["identity_boundary"]["profile_id"], "staging_identity_boundary")
        self.assertEqual(snapshot["allowed_count"], 1)
        self.assertEqual(snapshot["denied_count"], 1)
        self.assertEqual(snapshot["auth_profile"]["request_auth_required_count"], 1)
        self.assertIn("portal_browser_click_smoke_run", snapshot["allowed_capability_ids"])
        self.assertIn("release_execution_rollout_write", snapshot["denied_capability_ids"])
        self.assertIn("browser_automation", snapshot["enabled_sandbox_profiles"])
        self.assertIn("release_write", snapshot["denied_sandbox_profiles"])
        browser = next(
            item for item in snapshot["capabilities"]
            if item["capability_id"] == "portal_browser_click_smoke_run"
        )
        self.assertIn("release_artifact_manifest", browser["artifact_contracts"])
        self.assertIn("python tools/run_portal_browser_click_smoke.py", browser["entrypoints"])

    def test_snapshot_preserves_policy_warning_from_registry_manifest_gap(self):
        manifest_path = self.project_dir / "deployment" / "release_capability_registry.json"
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        manifest_path.write_text(
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
        self._write_identity_boundary()

        snapshot = build_release_runtime_assembly_snapshot(
            self.project_dir,
            runtime_root=self.runtime_dir,
            route_kind="portal",
            target_channel="staging",
            target_environment="staging",
            actor_id="release_manager",
        )
        capability = snapshot["capabilities"][0]

        self.assertEqual(snapshot["status"], "warning")
        self.assertEqual(snapshot["allowed_count"], 0)
        self.assertEqual(snapshot["warning_count"], 1)
        self.assertIn("release_delivery_readiness_read", snapshot["warning_capability_ids"])
        self.assertIn("read_only", snapshot["warning_sandbox_profiles"])
        self.assertEqual(capability["policy_status"], "warning")
        self.assertIn("capability_registry_warning", capability["warning_reasons"])

    def test_report_lines_surface_runtime_assembly_summary(self):
        report_lines = build_release_runtime_assembly_report_lines(
            {
                "status": "warning",
                "summary": "route=local_replay / actor=- / allowed=3 / warning=0 / blocked=1 / identity=passed",
                "route_kind": "local_replay",
                "route_id": "local_replay:staging:staging",
                "session_id": "web-staging-001",
                "invocation_source": "local_replay",
                "target_channel": "staging",
                "target_environment": "staging",
                "actor_id": "",
                "enabled_surface_types": ["tool", "command"],
                "denied_surface_types": ["gateway_method"],
                "enabled_sandbox_profiles": ["browser_automation"],
                "denied_sandbox_profiles": ["release_write"],
                "auth_profile": {
                    "actor_present": False,
                    "requires_actor_count": 2,
                    "request_auth_required_count": 1,
                    "authorization_blocked_capability_ids": ["release_execution_rollout_write"],
                    "request_auth_warning_capability_ids": ["release_execution_rollout_write"],
                },
                "identity_boundary": {
                    "status": "passed",
                    "profile_id": "staging_identity_boundary",
                    "provider_mode": "project_manifest",
                    "session_required": False,
                    "external_handoff_target_id": "",
                },
                "runner_profile": {
                    "status": "passed",
                    "profile_id": "release_windows_runner",
                    "runner_name": "godot-release-01",
                    "runner_os": "Windows",
                    "runner_arch": "x64",
                    "runner_labels": ["self-hosted", "windows", "godot"],
                },
                "capabilities": [
                    {
                        "capability_id": "release_execution_rollout_write",
                        "policy_status": "blocked",
                        "sandbox_profile": "release_write",
                        "surface_types": ["command", "gateway_method"],
                        "artifact_contracts": ["release_execution_status", "release_artifact_manifest"],
                        "entrypoints": ["/release-execution/run", "/release-artifact-manifest"],
                        "denial_reasons": ["release_write_disabled"],
                    }
                ],
            }
        )

        report = "\n".join(report_lines)
        self.assertIn("Route: local_replay / route_id=local_replay:staging:staging", report)
        self.assertIn("Identity Boundary: status=passed / profile=staging_identity_boundary", report)
        self.assertIn("Runner Profile: status=passed / profile=release_windows_runner", report)
        self.assertIn("Capability (release_execution_rollout_write): status=blocked", report)
        self.assertIn("contracts=release_execution_status, release_artifact_manifest", report)
        self.assertIn("entrypoints=/release-execution/run, /release-artifact-manifest", report)


if __name__ == "__main__":
    unittest.main()

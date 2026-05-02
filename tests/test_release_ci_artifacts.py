import json
import shutil
import subprocess
import sys
import unittest
from pathlib import Path
from unittest import mock


project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

import tools.export_release_ci_artifacts as export_ci
from tools.export_release_ci_artifacts import export_artifacts, _run_bootstrap_preview


class ReleaseCiArtifactsTestCase(unittest.TestCase):
    def setUp(self):
        self.output_dir = project_root / "tests" / ".tmp_release_ci_artifacts"
        shutil.rmtree(self.output_dir, ignore_errors=True)

    def tearDown(self):
        shutil.rmtree(self.output_dir, ignore_errors=True)

    def _write_fast_export_fixtures(self, release_manifest: dict) -> None:
        reports_dir = project_root / "logs" / "reports"
        reports_dir.mkdir(parents=True, exist_ok=True)
        release_binding = {
            "status": "passed",
            "manifest_path": "api_server/static/dist/release_manifest.json",
            "build_id": "web-staging-ci-001",
            "version": str(release_manifest.get("version") or "0.1.0-staging+ci1"),
            "channel": "staging",
        }
        export_ci._write_json(
            reports_dir / "doctor_self_check.json",
            {
                "ok": True,
                "action_item_count": 0,
                "report_path": "logs/reports/doctor_self_check.json",
            },
        )
        export_ci._write_json(
            reports_dir / "clean_machine_bootstrap.json",
            {
                "ok": True,
                "doctor_report": {
                    "path": "logs/reports/doctor_self_check.json",
                    "exists": True,
                },
            },
        )
        lane_path = export_ci._write_full_live_validation_lane_report(
            reports_dir,
            lane_id="portal_click_smoke",
            label="Portal Click Smoke",
            status="passed",
            summary="Portal click smoke passed",
            executed_at="2026-04-15T09:15:00Z",
            artifact_paths=["logs/test_artifacts/portal_click_chrome_8014.out"],
            release_binding=release_binding,
            flow_statuses={
                "flow": "passed",
                "release_promotion_history_report_flow": "passed",
            },
        )
        export_ci._write_json(
            reports_dir / "full_live_validation.json",
            {
                "schema_version": "1.1",
                "ok": True,
                "release_binding": release_binding,
                "steps": [
                    {
                        "id": "portal_click_smoke",
                        "label": "Portal Click Smoke",
                        "status": "passed",
                        "summary": "Portal click smoke passed",
                        "report_path": lane_path,
                        "details": {
                            "report_path": lane_path,
                            "flow_statuses": {
                                "release_promotion_history_report_flow": "passed",
                            },
                        },
                    }
                ],
            },
        )

        deployment_dir = project_root / "deployment"
        export_ci._write_json(deployment_dir / "release_live_runner_profile.json", {"profile_id": "release_windows_runner"})
        export_ci._write_json(deployment_dir / "release_distribution_delivery.json", {"schema_version": "1.0"})
        export_ci._write_json(deployment_dir / "release_identity_boundary.json", {"profile_id": "staging_identity_boundary"})
        export_ci._write_json(deployment_dir / "release_identity_registry.json", {"schema_version": "1.0"})
        export_ci._write_json(deployment_dir / "release_access_policy.json", {"schema_version": "1.0"})
        export_ci._write_json(deployment_dir / "release_channels.json", {"schema_version": "1.0", "channels": []})
        export_ci._write_json(deployment_dir / "release_promotion_history.json", {"schema_version": "1.0", "items": []})
        export_ci._write_json(deployment_dir / "release_execution_status.json", {"schema_version": "1.0", "items": []})

        handoff_dir = project_root / export_ci.default_release_distribution_handoff_dir(
            target_channel="staging",
            build_id="web-staging-ci-001",
        )
        export_ci._write_text(handoff_dir / "install_release_handoff.ps1", "Write-Output 'install'\n")

        publish_dir = project_root / export_ci.default_release_distribution_publish_handoff_dir(
            target_channel="staging",
            build_id="web-staging-ci-001",
        )
        export_ci._write_json(
            publish_dir / "distribution_publish_manifest.json",
            {"schema_version": "1.0", "publish_targets": ["staging_ci_artifact"]},
        )

        receipts_dir = project_root / export_ci.default_release_distribution_publish_receipts_dir(
            target_channel="staging",
            build_id="web-staging-ci-001",
        )
        export_ci._write_json(
            receipts_dir / "publish_receipts_manifest.json",
            {"schema_version": "1.0", "receipt_count": 1},
        )

        identity_handoff_dir = project_root / export_ci.default_release_request_auth_identity_handoff_dir(
            target_channel="staging",
            target_environment="staging",
        )
        export_ci._write_json(
            identity_handoff_dir / "identity_boundary_handoff_manifest.json",
            {"schema_version": "1.0", "profile_id": "staging_identity_boundary"},
        )

    def _fake_execution_result(self) -> dict:
        portal_lane_artifact = {
            "lane_id": "portal_click_smoke",
            "label": "Portal Click Smoke",
            "status": "passed",
            "summary": "Portal click smoke passed",
            "report_path": "logs/reports/full_live_validation_lanes/portal_click_smoke.json",
            "flow_statuses": {
                "release_promotion_history_report_flow": "passed",
            },
        }
        return {
            "execution": {"should_block": False, "blocking_checks": []},
            "execution_status": {
                "latest_execution": {
                    "executed_at": "2026-04-15T09:25:00Z",
                    "release_delivery_readiness_status": "warning",
                    "release_delivery_readiness_summary": "ready with manual follow-up",
                    "release_delivery_readiness_next_action_count": 1,
                    "release_delivery_readiness_next_actions": [
                        {"action_id": "publish_receipts_review"}
                    ],
                },
                "release_candidate_checklist": {
                    "release_summary": {
                        "build_id": "web-staging-ci-001",
                        "version": "0.1.0-staging+ci1",
                        "channel": "staging",
                    }
                },
                "release_live_ci_summary": {
                    "details": {
                        "ci_gate": {
                            "status": "passed",
                            "should_block": False,
                            "blocking_checks": [],
                            "warning_checks": [],
                        }
                    }
                },
                "full_live_validation": {
                    "status": "passed",
                    "details": {
                        "lane_artifacts": [
                            {
                                "lane_id": "godot_live_sandbox",
                                "label": "Godot Live Sandbox",
                                "status": "passed",
                                "summary": "Godot live sandbox passed",
                                "report_path": "logs/reports/full_live_validation_lanes/godot_live_sandbox.json",
                                "flow_statuses": {},
                            },
                            {
                                "lane_id": "portal_dom_smoke",
                                "label": "Portal DOM Smoke",
                                "status": "passed",
                                "summary": "Portal DOM smoke passed",
                                "report_path": "logs/reports/full_live_validation_lanes/portal_dom_smoke.json",
                                "flow_statuses": {},
                            },
                            portal_lane_artifact,
                        ],
                    },
                },
            },
        }

    def test_bootstrap_preview_timeout_returns_warning_payload(self):
        with mock.patch(
            "tools.export_release_ci_artifacts.subprocess.run",
            side_effect=subprocess.TimeoutExpired(cmd=["powershell"], timeout=30, output="stdout", stderr="stderr"),
        ):
            payload = _run_bootstrap_preview(self.output_dir / "bootstrap_fixture")

        self.assertEqual(payload["status"], "warning")
        self.assertFalse(payload["ok"])
        self.assertIn("bootstrap_preview_timeout", payload["warning_checks"])
        self.assertIn("stdout", payload["stdout_excerpt"])

    def test_export_artifacts_snapshots_full_live_validation_lane_reports(self):
        with (
            mock.patch("tools.export_release_ci_artifacts._run_bootstrap_preview", return_value={"status": "passed", "ok": True}),
            mock.patch("tools.export_release_ci_artifacts._prepare_runtime_reports", side_effect=self._write_fast_export_fixtures),
            mock.patch("tools.export_release_ci_artifacts.build_release_promotion_plan", return_value={"should_block": False, "blocking_checks": []}),
            mock.patch("tools.export_release_ci_artifacts.build_release_promotion_evidence_report", return_value="# Evidence\n"),
            mock.patch("tools.export_release_ci_artifacts.build_release_review_bundle_report", return_value="# Review\n"),
            mock.patch("tools.export_release_ci_artifacts.build_deployment_rehearsal_report", return_value="# Deployment\n"),
            mock.patch("tools.export_release_ci_artifacts.build_rollback_rehearsal_report", return_value="# Rollback\n"),
            mock.patch("tools.export_release_ci_artifacts.record_release_promotion_event", return_value={"status": "recorded"}),
            mock.patch("tools.export_release_ci_artifacts.build_release_promotion_history", return_value={"items": []}),
            mock.patch("tools.export_release_ci_artifacts.build_release_promotion_history_report", return_value="# Release Promotion History\n"),
            mock.patch("tools.export_release_ci_artifacts.run_release_execution", return_value=self._fake_execution_result()),
            mock.patch("tools.export_release_ci_artifacts.build_release_execution_report", return_value="# Release Execution\n"),
            mock.patch(
                "tools.export_release_ci_artifacts.build_release_runtime_assembly_snapshot",
                return_value={
                    "route_kind": "ci_rehearsal",
                    "actor_id": "ci_release",
                    "invocation_source": "release_validation_workflow",
                    "target_channel": "staging",
                    "capabilities": [
                        {
                            "capability_id": "release_live_ci_summary_read",
                            "artifact_contracts": ["release_artifact_manifest"],
                            "entrypoints": ["/release-artifact-manifest"],
                        }
                    ],
                },
            ),
        ):
            generated_files = export_artifacts(self.output_dir)

        bootstrap_report_path = self.output_dir / "runtime_reports" / "clean_machine_bootstrap.json"
        doctor_report_path = self.output_dir / "runtime_reports" / "doctor_self_check.json"
        full_report_path = self.output_dir / "runtime_reports" / "full_live_validation.json"
        lane_report_path = self.output_dir / "runtime_reports" / "full_live_validation_lanes" / "portal_click_smoke.json"
        handoff_install_path = self.output_dir / "release_distribution_handoff" / "install_release_handoff.ps1"
        publish_handoff_manifest_path = self.output_dir / "release_distribution_publish" / "distribution_publish_manifest.json"
        publish_receipts_manifest_path = self.output_dir / "release_distribution_publish_receipts" / "publish_receipts_manifest.json"
        promotion_history_report_path = self.output_dir / "release_promotion_history.md"
        identity_handoff_manifest_path = self.output_dir / "release_request_auth_identity_handoff" / "identity_boundary_handoff_manifest.json"
        runner_profile_path = self.output_dir / "deployment" / "release_live_runner_profile.json"
        distribution_delivery_path = self.output_dir / "deployment" / "release_distribution_delivery.json"
        identity_boundary_path = self.output_dir / "deployment" / "release_identity_boundary.json"

        self.assertTrue(bootstrap_report_path.exists())
        self.assertTrue(doctor_report_path.exists())
        self.assertTrue(full_report_path.exists())
        self.assertTrue(lane_report_path.exists())
        self.assertTrue(handoff_install_path.exists())
        self.assertTrue(publish_handoff_manifest_path.exists())
        self.assertTrue(publish_receipts_manifest_path.exists())
        self.assertTrue(promotion_history_report_path.exists())
        self.assertTrue(identity_handoff_manifest_path.exists())
        self.assertTrue(runner_profile_path.exists())
        self.assertTrue(distribution_delivery_path.exists())
        self.assertTrue(identity_boundary_path.exists())
        self.assertIn(lane_report_path, generated_files)
        self.assertIn(doctor_report_path, generated_files)

        bootstrap_payload = json.loads(bootstrap_report_path.read_text(encoding="utf-8"))
        self.assertEqual(bootstrap_payload["doctor_report"]["path"], "logs/reports/doctor_self_check.json")
        self.assertTrue(bootstrap_payload["doctor_report"]["exists"])

        full_report_payload = json.loads(full_report_path.read_text(encoding="utf-8"))
        portal_click_step = next(
            item for item in full_report_payload["steps"] if item["id"] == "portal_click_smoke"
        )
        self.assertEqual(
            portal_click_step["details"]["report_path"],
            "logs/reports/full_live_validation_lanes/portal_click_smoke.json",
        )

        lane_report_payload = json.loads(lane_report_path.read_text(encoding="utf-8"))
        self.assertEqual(lane_report_payload["lane_id"], "portal_click_smoke")
        self.assertEqual(lane_report_payload["status"], "passed")
        self.assertEqual(
            lane_report_payload["report_path"],
            "logs/reports/full_live_validation_lanes/portal_click_smoke.json",
        )
        self.assertEqual(lane_report_payload["release_binding"]["build_id"], "web-staging-ci-001")
        self.assertEqual(
            lane_report_payload["details"]["flow_statuses"]["release_promotion_history_report_flow"],
            "passed",
        )

        doctor_report_payload = json.loads(doctor_report_path.read_text(encoding="utf-8"))
        self.assertTrue(doctor_report_payload["ok"])
        self.assertEqual(doctor_report_payload["action_item_count"], 0)
        self.assertEqual(doctor_report_payload["report_path"], "logs/reports/doctor_self_check.json")
        self.assertIn("# Release Promotion History", promotion_history_report_path.read_text(encoding="utf-8"))

        artifact_manifest_payload = json.loads((self.output_dir / "artifact_manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(artifact_manifest_payload["schema_version"], "1.0")
        self.assertEqual(
            artifact_manifest_payload["contract_versions"]["release_artifact_manifest"],
            "1.0",
        )
        self.assertEqual(
            artifact_manifest_payload["runtime_lanes"]["full_live_validation"][2]["flow_statuses"]["release_promotion_history_report_flow"],
            "passed",
        )
        self.assertEqual(artifact_manifest_payload["runtime_assembly"]["route_kind"], "ci_rehearsal")
        self.assertEqual(artifact_manifest_payload["runtime_assembly"]["actor_id"], "ci_release")
        runtime_capabilities = artifact_manifest_payload["runtime_assembly"]["capabilities"]
        live_summary_capability = next(
            item for item in runtime_capabilities
            if item["capability_id"] == "release_live_ci_summary_read"
        )
        self.assertIn("release_artifact_manifest", live_summary_capability["artifact_contracts"])
        self.assertIn("/release-artifact-manifest", live_summary_capability["entrypoints"])
        self.assertEqual(
            artifact_manifest_payload["runtime_assembly"]["invocation_source"],
            "release_validation_workflow",
        )
        self.assertEqual(artifact_manifest_payload["runtime_assembly"]["target_channel"], "staging")
        self.assertEqual(artifact_manifest_payload["release_build_id"], "web-staging-ci-001")
        self.assertEqual(artifact_manifest_payload["release_channel"], "staging")
        self.assertEqual(artifact_manifest_payload["release_summary"]["build_id"], "web-staging-ci-001")
        self.assertEqual(artifact_manifest_payload["event_stream"]["route_kind"], "ci_rehearsal")
        self.assertEqual(artifact_manifest_payload["event_stream"]["path"], "release_live_ci_events.json")
        self.assertEqual(artifact_manifest_payload["event_stream"]["latest_event_type"], "run_finished")
        self.assertIn(
            artifact_manifest_payload["execution_delivery_readiness"]["status"],
            {"passed", "warning", "blocked"},
        )
        self.assertNotIn(
            "distribution_signing_handoff",
            artifact_manifest_payload["execution_delivery_readiness"]["next_action_ids"],
        )
        self.assertEqual(
            artifact_manifest_payload["execution_delivery_readiness"]["next_action_count"],
            len(artifact_manifest_payload["execution_delivery_readiness"]["next_action_ids"]),
        )


if __name__ == "__main__":
    unittest.main()

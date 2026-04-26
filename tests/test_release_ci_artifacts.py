import json
import json
import shutil
import subprocess
import sys
import unittest
from pathlib import Path
from unittest import mock


project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from tools.export_release_ci_artifacts import export_artifacts, _run_bootstrap_preview


class ReleaseCiArtifactsTestCase(unittest.TestCase):
    def setUp(self):
        self.output_dir = project_root / "tests" / ".tmp_release_ci_artifacts"
        shutil.rmtree(self.output_dir, ignore_errors=True)

    def tearDown(self):
        shutil.rmtree(self.output_dir, ignore_errors=True)

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

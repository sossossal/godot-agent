import json
import shutil
import subprocess
import sys
import unittest
from pathlib import Path


project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from agent_system.tools.release_delivery_readiness import (  # noqa: E402
    build_release_delivery_readiness,
    build_release_delivery_readiness_report,
    export_release_delivery_readiness,
)


class ReleaseDeliveryReadinessTestCase(unittest.TestCase):
    def setUp(self):
        self.project_dir = project_root / "tests" / ".tmp_release_delivery_project"
        self.runtime_dir = project_root / "tests" / ".tmp_release_delivery_runtime"
        shutil.rmtree(self.project_dir, ignore_errors=True)
        shutil.rmtree(self.runtime_dir, ignore_errors=True)
        self.project_dir.mkdir(parents=True, exist_ok=True)
        self.runtime_dir.mkdir(parents=True, exist_ok=True)

    def tearDown(self):
        shutil.rmtree(self.project_dir, ignore_errors=True)
        shutil.rmtree(self.runtime_dir, ignore_errors=True)

    def _write_identity_manifests(self) -> None:
        deployment_dir = self.project_dir / "deployment"
        deployment_dir.mkdir(parents=True, exist_ok=True)
        (deployment_dir / "release_request_auth.json").write_text(
            json.dumps(
                {
                    "schema_version": "1.0",
                    "allow_local_without_token": False,
                    "tokens": [],
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        (deployment_dir / "release_identity_registry.json").write_text(
            json.dumps(
                {
                    "schema_version": "1.0",
                    "issuers": [
                        {
                            "issuer_id": "ops_release",
                            "status": "active",
                            "channels": ["release"],
                            "target_environments": ["production"],
                            "subject_actor_ids": ["release_manager", "ops_a"],
                            "session_required": True,
                            "max_session_age_hours": 24,
                        }
                    ],
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        (deployment_dir / "release_identity_boundary.json").write_text(
            json.dumps(
                {
                    "schema_version": "1.0",
                    "profiles": [
                        {
                            "profile_id": "release_identity_boundary",
                            "target_channels": ["release"],
                            "target_environments": ["production"],
                            "provider_mode": "external_provider",
                            "provider_id": "entra_id",
                            "session_policy": {
                                "required": True,
                                "backend": "external_session",
                                "max_session_age_hours": 24,
                            },
                            "secret_rotation": {
                                "required": True,
                                "backend": "vault",
                                "owner": "ops_release",
                                "rotation_window_days": 30,
                            },
                            "external_handoff": {
                                "required": True,
                                "mode": "external_intake",
                                "target_id": "release_identity_intake",
                                "owner": "security_ops",
                            },
                        }
                    ],
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

    def _write_runtime_reports(self) -> None:
        reports_dir = self.runtime_dir / "logs" / "reports"
        (reports_dir / "release_live_ci").mkdir(parents=True, exist_ok=True)
        (reports_dir / "release_distribution_bundle_release.json").write_text(
            json.dumps(
                {
                    "schema_version": "1.0",
                    "status": "warning",
                    "summary": "delivery=warning / signing=warning / publish=warning / receipts=skipped",
                    "report_path": "logs/reports/release_distribution_bundle_release.json",
                    "delivery_profile_id": "release_delivery",
                    "delivery_status": "warning",
                    "delivery_primary_installer": "portable_handoff",
                    "delivery_signing_required": True,
                    "delivery_signing_mode": "manual_pending",
                    "signing_handoff_status": "warning",
                    "publish_handoff_status": "warning",
                    "publish_receipts_status": "skipped",
                    "publish_receipts_target_count": 2,
                    "publish_receipts_recorded_target_count": 0,
                    "publish_receipts_completed_targets": [],
                    "publish_receipts_missing_targets": ["itch", "steam"],
                    "publish_receipts_failed_targets": [],
                    "recommendations": ["complete signing handoff"],
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        (reports_dir / "release_live_runner_baseline_release.json").write_text(
            json.dumps(
                {
                    "schema_version": "1.0",
                    "status": "passed",
                    "summary": "runner ok",
                    "runner_profile_id": "release_windows_runner",
                    "runner_name": "godot-release-01",
                    "declared_runner_labels": ["self-hosted", "windows", "godot"],
                    "report_path": "logs/reports/release_live_runner_baseline_release.json",
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        (reports_dir / "release_live_ci" / "release_live_ci_summary.json").write_text(
            json.dumps(
                {
                    "schema_version": "1.0",
                    "status": "warning",
                    "summary": "ci_gate=passed / source=local_replay",
                    "target_channel": "release",
                    "target_environment": "production",
                    "release_build_id": "web-release-001",
                    "release_version": "1.0.0",
                    "ci_gate": {
                        "status": "passed",
                        "should_block": False,
                    },
                    "runtime_gates": {
                        "release_live_runner_baseline_status": "passed",
                        "distribution_bundle_status": "warning",
                        "distribution_signing_handoff_status": "warning",
                        "distribution_publish_handoff_status": "warning",
                        "distribution_publish_receipts_status": "skipped",
                        "identity_handoff_status": "passed",
                    },
                    "invocation": {
                        "source": "local_replay",
                    },
                    "report_files": {
                        "summary_markdown": "release_live_ci_summary.md",
                    },
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        (reports_dir / "release_live_ci" / "release_live_dispatch.json").write_text(
            json.dumps(
                {
                    "schema_version": "1.0",
                    "status": "warning",
                    "summary": "dispatch pending real GitHub workflow",
                    "path": "logs/reports/release_live_ci/release_live_dispatch.json",
                    "workflow": "release-live-gates.yml",
                    "repo": "owner/repo",
                    "ref": "main",
                    "target_channel": "release",
                    "target_environment": "production",
                    "ready": True,
                    "dispatch_attempted": True,
                    "dispatch_completed": False,
                    "follow_up_required": True,
                    "run": {
                        "status": "queued",
                        "conclusion": "",
                    },
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

    def test_build_release_delivery_readiness_summarizes_remaining_delivery_tracks(self):
        self._write_identity_manifests()
        self._write_runtime_reports()

        payload = build_release_delivery_readiness(
            self.project_dir,
            runtime_root=self.runtime_dir,
            target_channel="release",
            target_environment="production",
        )

        self.assertEqual(payload["schema_version"], "1.1")
        self.assertEqual(payload["component_count"], 3)
        self.assertIn(payload["status"], {"warning", "blocked"})
        self.assertEqual(payload["identity_boundary"]["component_id"], "identity_boundary")
        self.assertEqual(payload["workflow_release"]["component_id"], "workflow_release")
        self.assertEqual(payload["distribution_delivery"]["component_id"], "distribution_delivery")
        self.assertTrue(any(item["action_id"] == "self_hosted_release_workflow" for item in payload["next_actions"]))
        self.assertTrue(any(item["action_id"] == "distribution_signing_handoff" for item in payload["next_actions"]))
        self.assertTrue(any(item["action_id"] == "distribution_publish_handoff" for item in payload["next_actions"]))
        self.assertTrue(any(item["action_id"] == "distribution_publish_receipts" for item in payload["next_actions"]))
        workflow_action = next(item for item in payload["next_actions"] if item["action_id"] == "self_hosted_release_workflow")
        self.assertEqual(workflow_action["dependency"], "github_actions_self_hosted_windows_runner")
        self.assertEqual(workflow_action["eta"], "before_release_gate")
        self.assertEqual(workflow_action["validation_method"], "release_live_dispatch_audit_and_release_live_ci_summary")
        self.assertTrue(workflow_action["blockers"])
        receipts_action = next(item for item in payload["next_actions"] if item["action_id"] == "distribution_publish_receipts")
        self.assertEqual(receipts_action["dependency"], "publish_target_receipts")
        self.assertEqual(receipts_action["validation_method"], "publish_receipts_manifest_and_target_receipts")
        self.assertIn("missing_receipt:itch", receipts_action["blockers"])
        self.assertTrue(payload["distribution_delivery"]["follow_up_required"])
        self.assertIn("distribution_publish_receipts_incomplete", payload["distribution_delivery"]["warning_checks"])
        self.assertEqual(payload["distribution_delivery"]["details"]["publish_receipts_missing_targets"], ["itch", "steam"])
        self.assertIn("github_workflow_not_observed", payload["workflow_release"]["warning_checks"])

    def test_build_release_delivery_readiness_does_not_require_optional_signing_handoff(self):
        self._write_identity_manifests()
        self._write_runtime_reports()
        reports_dir = self.runtime_dir / "logs" / "reports"
        (reports_dir / "release_distribution_bundle_release.json").write_text(
            json.dumps(
                {
                    "schema_version": "1.0",
                    "status": "passed",
                    "summary": "delivery=passed / signing=skipped / publish=passed / receipts=passed",
                    "report_path": "logs/reports/release_distribution_bundle_release.json",
                    "delivery_profile_id": "staging_internal_windows",
                    "delivery_status": "passed",
                    "delivery_primary_installer": "portable_handoff",
                    "delivery_signing_required": False,
                    "delivery_signing_mode": "sha256_only",
                    "signing_handoff_status": "skipped",
                    "publish_handoff_status": "passed",
                    "publish_receipts_status": "passed",
                    "publish_receipts_target_count": 1,
                    "publish_receipts_recorded_target_count": 1,
                    "publish_receipts_completed_targets": ["staging_ci_artifact"],
                    "publish_receipts_missing_targets": [],
                    "publish_receipts_failed_targets": [],
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

        payload = build_release_delivery_readiness(
            self.project_dir,
            runtime_root=self.runtime_dir,
            target_channel="release",
            target_environment="production",
        )

        self.assertNotIn(
            "distribution_signing_handoff_incomplete",
            payload["distribution_delivery"]["warning_checks"],
        )
        self.assertFalse(any(
            item["action_id"] == "distribution_signing_handoff"
            for item in payload["next_actions"]
        ))
        self.assertFalse(any("export_release_distribution_signing_handoff.py" in item for item in payload["recommendations"]))
        self.assertFalse(any("export_release_distribution_publish_handoff.py" in item for item in payload["recommendations"]))

    def test_release_delivery_readiness_report_mentions_components_and_next_actions(self):
        self._write_identity_manifests()
        self._write_runtime_reports()

        report = build_release_delivery_readiness_report(
            build_release_delivery_readiness(
                self.project_dir,
                runtime_root=self.runtime_dir,
                target_channel="release",
                target_environment="production",
            )
        )

        self.assertIn("# Release Delivery Readiness", report)
        self.assertIn("## Components", report)
        self.assertIn("External Identity Boundary", report)
        self.assertIn("Self-Hosted Workflow Release", report)
        self.assertIn("External Distribution Delivery", report)
        self.assertIn("## Next Actions", report)
        self.assertIn("self_hosted_release_workflow", report)
        self.assertIn("distribution_signing_handoff", report)
        self.assertIn("distribution_publish_receipts", report)
        self.assertIn("dependency=github_actions_self_hosted_windows_runner", report)
        self.assertIn("validation=release_live_dispatch_audit_and_release_live_ci_summary", report)
        self.assertIn("publish_receipts_target_count=2", report)

    def test_release_delivery_readiness_lines_include_next_actions_when_given_full_snapshot(self):
        from agent_system.tools.release_delivery_readiness import build_release_delivery_readiness_report_lines

        self._write_identity_manifests()
        self._write_runtime_reports()

        lines = build_release_delivery_readiness_report_lines(
            build_release_delivery_readiness(
                self.project_dir,
                runtime_root=self.runtime_dir,
                target_channel="release",
                target_environment="production",
            )
        )
        report = "\n".join(lines)

        self.assertIn("Release Delivery Readiness: status=", report)
        self.assertIn("Next Actions:", report)
        self.assertIn("distribution_signing_handoff", report)
        self.assertIn("distribution_publish_handoff", report)
        self.assertIn("distribution_publish_receipts", report)
        self.assertIn("missing_receipt:itch", report)

    def test_export_release_delivery_readiness_writes_json_and_markdown_reports(self):
        self._write_identity_manifests()
        self._write_runtime_reports()

        payload = export_release_delivery_readiness(
            self.project_dir,
            runtime_root=self.runtime_dir,
            target_channel="release",
            target_environment="production",
        )

        json_path = self.runtime_dir / "logs" / "reports" / "release_delivery_readiness_release.json"
        markdown_path = self.runtime_dir / "logs" / "reports" / "release_delivery_readiness_release.md"
        self.assertTrue(json_path.exists())
        self.assertTrue(markdown_path.exists())
        self.assertEqual(payload["report_path"], "logs/reports/release_delivery_readiness_release.json")
        self.assertEqual(payload["report_markdown_path"], "logs/reports/release_delivery_readiness_release.md")
        exported = json.loads(json_path.read_text(encoding="utf-8"))
        self.assertEqual(exported["schema_version"], "1.1")
        self.assertEqual(exported["next_actions"][0]["action_id"], payload["next_actions"][0]["action_id"])
        self.assertIn("# Release Delivery Readiness", markdown_path.read_text(encoding="utf-8"))

    def test_export_release_delivery_readiness_cli_can_fail_on_blockers(self):
        self._write_identity_manifests()
        self._write_runtime_reports()

        result = subprocess.run(
            [
                sys.executable,
                "tools/export_release_delivery_readiness.py",
                "--project-root",
                str(self.project_dir),
                "--runtime-root",
                str(self.runtime_dir),
                "--channel",
                "release",
                "--target-environment",
                "production",
                "--fail-on-blockers",
            ],
            cwd=project_root,
            text=True,
            capture_output=True,
            check=False,
        )

        self.assertEqual(result.returncode, 1)
        self.assertIn('"status": "blocked"', result.stdout)
        self.assertTrue((self.runtime_dir / "logs" / "reports" / "release_delivery_readiness_release.json").exists())

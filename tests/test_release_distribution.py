import json
import subprocess
import shutil
import sys
import unittest
from pathlib import Path
from unittest import mock


project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from agent_system.tools.release_distribution import (
    build_release_distribution_bundle,
    export_release_distribution_archive,
    export_release_distribution_bundle,
    export_release_distribution_channel_index,
    export_release_distribution_handoff,
    export_release_distribution_publish_handoff,
    export_release_distribution_signing_handoff,
    export_release_distribution_install_smoke,
    _run_powershell_script,
    record_release_distribution_publish_receipt,
)


class ReleaseDistributionBundleTestCase(unittest.TestCase):
    def setUp(self):
        self.project_dir = project_root / "tests" / ".tmp_release_distribution_project"
        self.runtime_dir = project_root / "tests" / ".tmp_release_distribution_runtime"
        shutil.rmtree(self.project_dir, ignore_errors=True)
        shutil.rmtree(self.runtime_dir, ignore_errors=True)
        self.project_dir.mkdir(parents=True, exist_ok=True)
        self.runtime_dir.mkdir(parents=True, exist_ok=True)

    def tearDown(self):
        shutil.rmtree(self.project_dir, ignore_errors=True)
        shutil.rmtree(self.runtime_dir, ignore_errors=True)

    def test_run_powershell_script_timeout_returns_diagnostic_result(self):
        with mock.patch(
            "agent_system.tools.release_distribution.subprocess.run",
            side_effect=subprocess.TimeoutExpired(cmd=["powershell"], timeout=30, output="stdout"),
        ):
            result = _run_powershell_script("powershell", self.runtime_dir / "script.ps1", [])

        self.assertEqual(result["returncode"], 124)
        self.assertIn("stdout", result["stdout"])
        self.assertIn("timed out", result["stderr"])

    def _prepare_runtime(self, *, channel: str = "staging") -> None:
        (self.project_dir / "project.godot").write_text("; test project\n", encoding="utf-8")
        (self.project_dir / "deployment").mkdir(parents=True, exist_ok=True)
        (self.project_dir / "docs").mkdir(parents=True, exist_ok=True)
        (self.project_dir / "tools").mkdir(parents=True, exist_ok=True)
        (self.project_dir / "docs" / "支持矩阵与分发说明.md").write_text(
            "# Support Matrix\n\n- staging distribution bundle fixture\n",
            encoding="utf-8",
        )
        (self.project_dir / "tools" / "bootstrap_clean_machine.ps1").write_text(
            "Write-Output 'bootstrap fixture'\n",
            encoding="utf-8",
        )

        dist_dir = self.runtime_dir / "api_server" / "static" / "dist"
        dist_dir.mkdir(parents=True, exist_ok=True)
        release_dir = dist_dir / "web_20260416"
        release_dir.mkdir(parents=True, exist_ok=True)
        (release_dir / "qa_gate_report.md").write_text("# QA Gate\n", encoding="utf-8")
        (release_dir / "release_notes.md").write_text("# Release Notes\n", encoding="utf-8")
        (release_dir / "build.log").write_text("build ok\n", encoding="utf-8")
        (release_dir / "index.html").write_text("<html></html>\n", encoding="utf-8")

        manifest = {
            "schema_version": "1.0",
            "build_id": f"web-{channel}-001",
            "version": f"0.1.0-{channel}+1",
            "channel": channel,
            "preset_name": "Web",
            "platform": "web",
            "generated_at": "2026-04-16T10:00:00Z",
            "output_path": "api_server/static/dist/web_20260416/index.html",
            "release_dir": "api_server/static/dist/web_20260416",
            "release_url": "/portal/dist/index.html",
            "versioned_release_url": "/portal/dist/web_20260416/index.html",
            "build_log_path": "api_server/static/dist/web_20260416/build.log",
            "release_notes_path": "api_server/static/dist/web_20260416/release_notes.md",
            "release_manifest_path": "api_server/static/dist/web_20260416/release_manifest.json",
            "feature": {
                "schema_version": "1.0",
                "feature_id": "feature-distribution",
                "owner": "release_engineer",
                "priority": "high",
                "risk": "medium",
                "feature_status": "approved",
            },
            "change_summary": ["prepare distribution bundle"],
            "acceptance_checklist": [{"label": "smoke", "status": "ready"}],
            "quality_gate": {
                "schema_version": "1.0",
                "passed": True,
                "channel": channel,
                "preset_name": "Web",
                "checks": [{"name": "smoke_test", "status": "passed", "message": "ok"}],
                "blocked_checks": [],
                "warning_checks": [],
            },
            "files": [{"path": "index.html", "size": 13, "sha256": "abc"}],
            "rollback_hint": "restore web_20260416",
        }
        manifest_text = json.dumps(manifest, ensure_ascii=False, indent=2)
        (release_dir / "release_manifest.json").write_text(manifest_text, encoding="utf-8")
        (dist_dir / "release_manifest.json").write_text(manifest_text, encoding="utf-8")

    def _write_delivery_manifest(self, *, channel: str, environment: str) -> None:
        (self.project_dir / "deployment" / "release_distribution_delivery.json").write_text(
            json.dumps(
                {
                    "schema_version": "1.0",
                    "profiles": [
                        {
                            "profile_id": f"{channel}_delivery",
                            "target_channels": [channel],
                            "target_environments": [environment],
                            "primary_installer": "portable_handoff",
                            "installer_types": ["portable_handoff", "archive_zip"],
                            "signing": {
                                "required": channel == "release",
                                "mode": "manual_pending" if channel == "release" else "sha256_only",
                                "profile_id": "windows_release_codesign" if channel == "release" else "",
                            },
                            "publish_targets": [{"target_id": f"{channel}_artifact", "kind": "ci_artifact"}],
                            "first_run_bootstrap": "doctor_self_check",
                            "upgrade_strategy": "in_place_backup",
                            "uninstall_strategy": "scripted_cleanup",
                        }
                    ],
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

    def test_build_release_distribution_bundle_warns_before_export(self):
        self._prepare_runtime(channel="staging")

        payload = build_release_distribution_bundle(
            self.project_dir,
            runtime_root=self.runtime_dir,
            target_channel="staging",
            target_environment="staging",
            release_manifest_path="api_server/static/dist/release_manifest.json",
        )

        self.assertEqual(payload["status"], "warning")
        self.assertEqual(payload["build_id"], "web-staging-001")
        self.assertEqual(payload["bundle_dir"], "logs/reports/release_distribution/staging/web-staging-001")
        self.assertIn("distribution_manifest", payload["bundle_missing_items"])
        self.assertIn("install_script", payload["bundle_missing_items"])
        self.assertIn("release_payload", payload["bundle_missing_items"])
        self.assertFalse(payload["bundle_exists"])
        self.assertFalse(payload["delivery_manifest_exists"])
        self.assertEqual(payload["delivery_status"], "warning")

    def test_build_release_distribution_bundle_loads_external_delivery_profile(self):
        self._prepare_runtime(channel="release")
        self._write_delivery_manifest(channel="release", environment="production")

        payload = build_release_distribution_bundle(
            self.project_dir,
            runtime_root=self.runtime_dir,
            target_channel="release",
            target_environment="production",
            release_manifest_path="api_server/static/dist/release_manifest.json",
        )

        self.assertTrue(payload["delivery_manifest_exists"])
        self.assertEqual(payload["delivery_profile_id"], "release_delivery")
        self.assertEqual(payload["delivery_primary_installer"], "portable_handoff")
        self.assertEqual(payload["delivery_installer_status"], "passed")
        self.assertEqual(payload["delivery_signing_status"], "warning")
        self.assertEqual(payload["delivery_publish_status"], "passed")
        self.assertEqual(payload["delivery_publish_targets"], ["release_artifact"])
        self.assertEqual(payload["signing_handoff_status"], "skipped")
        self.assertEqual(payload["publish_handoff_status"], "skipped")

    def test_export_release_distribution_bundle_writes_versioned_payload_and_scripts(self):
        self._prepare_runtime(channel="release")

        payload = export_release_distribution_bundle(
            self.project_dir,
            runtime_root=self.runtime_dir,
            target_channel="release",
            target_environment="production",
            release_manifest_path="api_server/static/dist/release_manifest.json",
        )

        self.assertEqual(payload["status"], "warning")
        self.assertTrue(payload["bundle_exists"])
        self.assertTrue(payload["payload_exists"])
        self.assertTrue(payload["distribution_manifest_exists"])
        self.assertTrue(payload["install_script_exists"])
        self.assertTrue(payload["upgrade_script_exists"])
        self.assertTrue(payload["uninstall_script_exists"])
        self.assertTrue(payload["support_matrix_exists"])
        self.assertTrue(payload["state_manifest_exists"])
        self.assertEqual(payload["install_smoke_status"], "warning")
        self.assertFalse(payload["install_smoke_report_exists"])
        self.assertGreater(payload["payload_file_count"], 0)
        self.assertTrue(payload["report_exists"])

        bundle_dir = self.runtime_dir / payload["bundle_dir"]
        manifest_path = self.runtime_dir / payload["distribution_manifest_path"]
        install_script_path = self.runtime_dir / payload["install_script_path"]
        upgrade_script_path = self.runtime_dir / payload["upgrade_script_path"]
        uninstall_script_path = self.runtime_dir / payload["uninstall_script_path"]
        payload_index = self.runtime_dir / payload["payload_dir"] / "index.html"

        self.assertTrue(bundle_dir.exists())
        self.assertTrue(manifest_path.exists())
        self.assertTrue(install_script_path.exists())
        self.assertTrue(upgrade_script_path.exists())
        self.assertTrue(uninstall_script_path.exists())
        self.assertTrue(payload_index.exists())

        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        self.assertEqual(manifest["build_id"], "web-release-001")
        self.assertEqual(manifest["payload_path"], "release_payload")
        self.assertEqual(manifest["install_script_path"], "install_release_bundle.ps1")
        self.assertEqual(manifest["state_manifest_path"], "installed_release.example.json")
        self.assertIn("installed_release.json", install_script_path.read_text(encoding="utf-8"))
        self.assertIn("previous_build_id", install_script_path.read_text(encoding="utf-8"))
        self.assertIn("backup_dir", upgrade_script_path.read_text(encoding="utf-8"))
        self.assertIn("removed_version", uninstall_script_path.read_text(encoding="utf-8"))

    @unittest.skipUnless(sys.platform.startswith("win"), "requires PowerShell")
    def test_export_release_distribution_install_smoke_runs_generated_scripts(self):
        self._prepare_runtime(channel="release")

        report = export_release_distribution_install_smoke(
            self.project_dir,
            runtime_root=self.runtime_dir,
            target_channel="release",
            target_environment="production",
            release_manifest_path="api_server/static/dist/release_manifest.json",
        )
        payload = build_release_distribution_bundle(
            self.project_dir,
            runtime_root=self.runtime_dir,
            target_channel="release",
            target_environment="production",
            release_manifest_path="api_server/static/dist/release_manifest.json",
        )

        self.assertEqual(report["status"], "passed")
        self.assertGreaterEqual(report["backup_count"], 1)
        self.assertTrue(report["marker_preserved_in_backup"])
        self.assertTrue(any(step["step"] == "install" and step["status"] == "passed" for step in report["step_statuses"]))
        self.assertTrue(any(step["step"] == "upgrade" and step["status"] == "passed" for step in report["step_statuses"]))
        self.assertTrue(any(step["step"] == "uninstall" and step["status"] == "passed" for step in report["step_statuses"]))
        self.assertEqual(report["install_result"]["build_id"], "web-release-001")
        self.assertEqual(report["upgrade_result"]["previous_build_id"], "web-release-001")
        self.assertTrue(str(report["upgrade_result"]["backup_dir"]).strip())
        self.assertEqual(report["uninstall_result"]["removed_build_id"], "web-release-001")
        self.assertEqual(report["uninstall_result"]["removed_version"], "0.1.0-release+1")
        self.assertEqual(payload["status"], "warning")
        self.assertEqual(payload["install_smoke_status"], "passed")
        self.assertTrue(payload["install_smoke_report_exists"])
        self.assertTrue(payload["install_smoke_marker_preserved"])
        self.assertTrue(payload["install_smoke_state_removed"])
        self.assertEqual(payload["install_smoke_state_path"], report["state_path"])
        self.assertEqual(payload["install_smoke_installed_build_id"], "web-release-001")
        self.assertEqual(payload["install_smoke_installed_version"], "0.1.0-release+1")
        self.assertEqual(payload["install_smoke_previous_build_id"], "web-release-001")
        self.assertTrue(str(payload["install_smoke_backup_dir"]).strip())
        self.assertEqual(payload["install_smoke_removed_build_id"], "web-release-001")
        self.assertEqual(payload["install_smoke_removed_version"], "0.1.0-release+1")
        self.assertEqual(payload["archive_status"], "warning")
        self.assertEqual(payload["channel_index_status"], "skipped")
        self.assertFalse(payload["archive_file_exists"])
        bundle_report = json.loads(
            (self.runtime_dir / "logs" / "reports" / "release_distribution_bundle_release.json").read_text(encoding="utf-8")
        )
        self.assertEqual(bundle_report["install_smoke_status"], "passed")
        self.assertEqual(bundle_report["status"], "warning")
        self.assertEqual(bundle_report["channel_index_status"], "skipped")

    @unittest.skipUnless(sys.platform.startswith("win"), "requires PowerShell")
    def test_distribution_bundle_warns_when_install_smoke_report_targets_other_build(self):
        self._prepare_runtime(channel="release")
        export_release_distribution_install_smoke(
            self.project_dir,
            runtime_root=self.runtime_dir,
            target_channel="release",
            target_environment="production",
            release_manifest_path="api_server/static/dist/release_manifest.json",
        )
        report_path = self.runtime_dir / "logs" / "reports" / "release_distribution_install_smoke_release.json"
        report_payload = json.loads(report_path.read_text(encoding="utf-8"))
        report_payload["build_id"] = "other-build"
        report_path.write_text(json.dumps(report_payload, ensure_ascii=False, indent=2), encoding="utf-8")

        payload = build_release_distribution_bundle(
            self.project_dir,
            runtime_root=self.runtime_dir,
            target_channel="release",
            target_environment="production",
            release_manifest_path="api_server/static/dist/release_manifest.json",
        )

        self.assertEqual(payload["status"], "warning")
        self.assertEqual(payload["install_smoke_status"], "warning")
        self.assertEqual(payload["install_smoke_summary"], "distribution install smoke report does not match current bundle")

    @unittest.skipUnless(sys.platform.startswith("win"), "requires PowerShell")
    def test_export_release_distribution_archive_writes_zip_and_checksum(self):
        self._prepare_runtime(channel="release")

        payload = export_release_distribution_archive(
            self.project_dir,
            runtime_root=self.runtime_dir,
            target_channel="release",
            target_environment="production",
            release_manifest_path="api_server/static/dist/release_manifest.json",
        )

        archive_path = self.runtime_dir / payload["archive_path"]
        archive_sha256_path = self.runtime_dir / payload["archive_sha256_path"]

        self.assertEqual(payload["status"], "warning")
        self.assertEqual(payload["archive_status"], "passed")
        self.assertTrue(payload["archive_exists"])
        self.assertTrue(payload["archive_file_exists"])
        self.assertTrue(payload["archive_sha256_exists"])
        self.assertGreater(payload["archive_size_bytes"], 0)
        self.assertEqual(payload["channel_index_status"], "warning")
        self.assertTrue(archive_path.exists())
        self.assertTrue(archive_sha256_path.exists())
        self.assertIn("release_distribution_bundle.zip", archive_sha256_path.read_text(encoding="utf-8"))
        bundle_report = json.loads(
            (self.runtime_dir / "logs" / "reports" / "release_distribution_bundle_release.json").read_text(encoding="utf-8")
        )
        self.assertEqual(bundle_report["archive_status"], "passed")
        self.assertTrue(bundle_report["archive_file_exists"])
        self.assertEqual(bundle_report["channel_index_status"], "warning")
        self.assertEqual(bundle_report["status"], "warning")

    @unittest.skipUnless(sys.platform.startswith("win"), "requires PowerShell")
    def test_export_release_distribution_channel_index_writes_latest_and_releases(self):
        self._prepare_runtime(channel="release")

        payload = export_release_distribution_channel_index(
            self.project_dir,
            runtime_root=self.runtime_dir,
            target_channel="release",
            target_environment="production",
            release_manifest_path="api_server/static/dist/release_manifest.json",
        )

        latest_path = self.runtime_dir / payload["channel_index_latest_path"]
        releases_path = self.runtime_dir / payload["channel_index_releases_path"]

        self.assertEqual(payload["status"], "passed")
        self.assertEqual(payload["archive_status"], "passed")
        self.assertEqual(payload["channel_index_status"], "passed")
        self.assertTrue(payload["channel_index_report_exists"])
        self.assertTrue(payload["channel_index_latest_exists"])
        self.assertTrue(payload["channel_index_releases_exists"])
        self.assertTrue(payload["channel_index_latest_matches_current"])
        self.assertEqual(payload["channel_index_latest_build_id"], "web-release-001")
        self.assertEqual(payload["channel_index_release_count"], 1)
        self.assertTrue(latest_path.exists())
        self.assertTrue(releases_path.exists())
        latest_payload = json.loads(latest_path.read_text(encoding="utf-8"))
        releases_payload = json.loads(releases_path.read_text(encoding="utf-8"))
        self.assertEqual(latest_payload["build_id"], "web-release-001")
        self.assertEqual(latest_payload["archive_path"], payload["archive_path"])
        self.assertEqual(releases_payload["latest_build_id"], "web-release-001")
        self.assertEqual(len(releases_payload["items"]), 1)
        bundle_report = json.loads(
            (self.runtime_dir / "logs" / "reports" / "release_distribution_bundle_release.json").read_text(encoding="utf-8")
        )
        self.assertEqual(bundle_report["channel_index_status"], "passed")
        self.assertTrue(bundle_report["channel_index_latest_exists"])
        self.assertEqual(bundle_report["status"], "passed")

    @unittest.skipUnless(sys.platform.startswith("win"), "requires PowerShell")
    def test_export_release_distribution_handoff_writes_portable_package(self):
        self._prepare_runtime(channel="release")

        payload = export_release_distribution_handoff(
            self.project_dir,
            runtime_root=self.runtime_dir,
            target_channel="release",
            target_environment="production",
            release_manifest_path="api_server/static/dist/release_manifest.json",
        )

        handoff_dir = self.runtime_dir / payload["handoff_dir"]
        handoff_manifest_path = self.runtime_dir / payload["handoff_manifest_path"]
        handoff_install_script_path = self.runtime_dir / payload["handoff_install_script_path"]
        handoff_upgrade_script_path = self.runtime_dir / payload["handoff_upgrade_script_path"]
        handoff_uninstall_script_path = self.runtime_dir / payload["handoff_uninstall_script_path"]
        handoff_archive_path = self.runtime_dir / payload["handoff_archive_path"]
        handoff_latest_path = self.runtime_dir / payload["handoff_channel_latest_path"]

        self.assertEqual(payload["status"], "passed")
        self.assertEqual(payload["handoff_status"], "passed")
        self.assertTrue(payload["handoff_exists"])
        self.assertTrue(payload["handoff_manifest_exists"])
        self.assertTrue(payload["handoff_install_script_exists"])
        self.assertTrue(payload["handoff_upgrade_script_exists"])
        self.assertTrue(payload["handoff_uninstall_script_exists"])
        self.assertTrue(payload["handoff_archive_exists"])
        self.assertTrue(payload["handoff_channel_latest_exists"])
        self.assertGreater(payload["handoff_file_count"], 0)
        self.assertTrue(handoff_dir.exists())
        self.assertTrue(handoff_manifest_path.exists())
        self.assertTrue(handoff_install_script_path.exists())
        self.assertTrue(handoff_upgrade_script_path.exists())
        self.assertTrue(handoff_uninstall_script_path.exists())
        self.assertTrue(handoff_archive_path.exists())
        self.assertTrue(handoff_latest_path.exists())

        handoff_manifest = json.loads(handoff_manifest_path.read_text(encoding="utf-8"))
        self.assertEqual(handoff_manifest["build_id"], "web-release-001")
        self.assertEqual(handoff_manifest["package_archive_path"], "packages/release_distribution_bundle.zip")
        self.assertEqual(handoff_manifest["channel_latest_path"], "channel/latest.json")
        self.assertEqual(handoff_manifest["install_script_path"], "install_release_handoff.ps1")

    @unittest.skipUnless(sys.platform.startswith("win"), "requires PowerShell")
    def test_export_release_distribution_signing_handoff_writes_external_signing_package(self):
        self._prepare_runtime(channel="release")
        self._write_delivery_manifest(channel="release", environment="production")

        payload = export_release_distribution_signing_handoff(
            self.project_dir,
            runtime_root=self.runtime_dir,
            target_channel="release",
            target_environment="production",
            release_manifest_path="api_server/static/dist/release_manifest.json",
        )

        signing_dir = self.runtime_dir / payload["signing_handoff_dir"]
        signing_manifest_path = self.runtime_dir / payload["signing_handoff_manifest_path"]
        instructions_path = self.runtime_dir / payload["signing_handoff_instructions_path"]
        unsigned_archive_path = self.runtime_dir / payload["signing_handoff_unsigned_archive_path"]
        unsigned_archive_sha256_path = self.runtime_dir / payload["signing_handoff_unsigned_archive_sha256_path"]

        self.assertEqual(payload["status"], "passed")
        self.assertEqual(payload["delivery_signing_status"], "warning")
        self.assertEqual(payload["signing_handoff_status"], "passed")
        self.assertTrue(payload["signing_handoff_exists"])
        self.assertTrue(payload["signing_handoff_manifest_exists"])
        self.assertTrue(payload["signing_handoff_instructions_exists"])
        self.assertTrue(payload["signing_handoff_unsigned_archive_exists"])
        self.assertTrue(payload["signing_handoff_unsigned_archive_sha256_exists"])
        self.assertGreater(payload["signing_handoff_file_count"], 0)
        self.assertTrue(signing_dir.exists())
        self.assertTrue(signing_manifest_path.exists())
        self.assertTrue(instructions_path.exists())
        self.assertTrue(unsigned_archive_path.exists())
        self.assertTrue(unsigned_archive_sha256_path.exists())

        signing_manifest = json.loads(signing_manifest_path.read_text(encoding="utf-8"))
        self.assertEqual(signing_manifest["build_id"], "web-release-001")
        self.assertEqual(signing_manifest["delivery_profile_id"], "release_delivery")
        self.assertEqual(signing_manifest["signing_profile_id"], "windows_release_codesign")
        self.assertEqual(signing_manifest["unsigned_archive_path"], "unsigned/release_distribution_bundle.zip")
        self.assertEqual(signing_manifest["publish_targets"], ["release_artifact"])
        self.assertIn("Signing Profile: windows_release_codesign", instructions_path.read_text(encoding="utf-8"))

    @unittest.skipUnless(sys.platform.startswith("win"), "requires PowerShell")
    def test_export_release_distribution_publish_handoff_writes_external_publish_package(self):
        self._prepare_runtime(channel="release")
        self._write_delivery_manifest(channel="release", environment="production")

        payload = export_release_distribution_publish_handoff(
            self.project_dir,
            runtime_root=self.runtime_dir,
            target_channel="release",
            target_environment="production",
            release_manifest_path="api_server/static/dist/release_manifest.json",
        )

        publish_dir = self.runtime_dir / payload["publish_handoff_dir"]
        publish_manifest_path = self.runtime_dir / payload["publish_handoff_manifest_path"]
        instructions_path = self.runtime_dir / payload["publish_handoff_instructions_path"]
        publish_archive_path = self.runtime_dir / payload["publish_handoff_archive_path"]
        publish_archive_sha256_path = self.runtime_dir / payload["publish_handoff_archive_sha256_path"]
        publish_targets_path = publish_dir / "targets" / "publish_targets.json"
        signing_manifest_copy_path = publish_dir / "inputs" / "distribution_signing_manifest.json"

        self.assertEqual(payload["status"], "passed")
        self.assertEqual(payload["publish_handoff_status"], "passed")
        self.assertTrue(payload["publish_handoff_exists"])
        self.assertTrue(payload["publish_handoff_manifest_exists"])
        self.assertTrue(payload["publish_handoff_instructions_exists"])
        self.assertTrue(payload["publish_handoff_archive_exists"])
        self.assertTrue(payload["publish_handoff_archive_sha256_exists"])
        self.assertTrue(payload["publish_handoff_channel_latest_exists"])
        self.assertTrue(payload["publish_handoff_channel_releases_exists"])
        self.assertGreater(payload["publish_handoff_file_count"], 0)
        self.assertTrue(publish_dir.exists())
        self.assertTrue(publish_manifest_path.exists())
        self.assertTrue(instructions_path.exists())
        self.assertTrue(publish_archive_path.exists())
        self.assertTrue(publish_archive_sha256_path.exists())
        self.assertTrue(publish_targets_path.exists())
        self.assertTrue(signing_manifest_copy_path.exists())

        publish_manifest = json.loads(publish_manifest_path.read_text(encoding="utf-8"))
        publish_targets_payload = json.loads(publish_targets_path.read_text(encoding="utf-8"))
        self.assertEqual(publish_manifest["build_id"], "web-release-001")
        self.assertEqual(publish_manifest["delivery_profile_id"], "release_delivery")
        self.assertEqual(publish_manifest["publish_targets"], ["release_artifact"])
        self.assertEqual(publish_manifest["archive_path"], "payload/release_distribution_bundle.zip")
        self.assertEqual(publish_manifest["distribution_signing_manifest_path"], "inputs/distribution_signing_manifest.json")
        self.assertEqual(
            publish_targets_payload["publish_targets"],
            [{"target_id": "release_artifact", "sequence": 1}],
        )
        self.assertIn("Publish Targets: release_artifact", instructions_path.read_text(encoding="utf-8"))

    @unittest.skipUnless(sys.platform.startswith("win"), "requires PowerShell")
    def test_record_release_distribution_publish_receipt_closes_publish_receipts_loop(self):
        self._prepare_runtime(channel="release")
        self._write_delivery_manifest(channel="release", environment="production")

        payload = record_release_distribution_publish_receipt(
            self.project_dir,
            runtime_root=self.runtime_dir,
            target_channel="release",
            target_environment="production",
            release_manifest_path="api_server/static/dist/release_manifest.json",
            target_id="release_artifact",
            status="published",
            external_reference="release-artifact-001",
            artifact_url="https://example.invalid/releases/web-release-001.zip",
            operator="ops_release",
            published_at="2026-04-18T10:00:00Z",
            notes=["external publish completed"],
        )

        receipts_dir = self.runtime_dir / payload["publish_receipts_dir"]
        manifest_path = self.runtime_dir / payload["publish_receipts_manifest_path"]
        receipt_path = receipts_dir / "receipts" / "release_artifact.json"

        self.assertEqual(payload["publish_receipts_status"], "passed")
        self.assertTrue(payload["publish_receipts_exists"])
        self.assertTrue(payload["publish_receipts_manifest_exists"])
        self.assertTrue(payload["publish_receipts_manifest_matches_current"])
        self.assertEqual(payload["publish_receipts_target_count"], 1)
        self.assertEqual(payload["publish_receipts_recorded_target_count"], 1)
        self.assertEqual(payload["publish_receipts_completed_targets"], ["release_artifact"])
        self.assertEqual(payload["publish_receipts_missing_targets"], [])
        self.assertTrue(receipts_dir.exists())
        self.assertTrue(manifest_path.exists())
        self.assertTrue(receipt_path.exists())

        manifest_payload = json.loads(manifest_path.read_text(encoding="utf-8"))
        receipt_payload = json.loads(receipt_path.read_text(encoding="utf-8"))
        self.assertEqual(manifest_payload["publish_targets"], ["release_artifact"])
        self.assertEqual(manifest_payload["receipt_count"], 1)
        self.assertEqual(manifest_payload["receipts"][0]["external_reference"], "release-artifact-001")
        self.assertEqual(receipt_payload["target_id"], "release_artifact")
        self.assertEqual(receipt_payload["status"], "published")
        self.assertEqual(receipt_payload["operator"], "ops_release")

    @unittest.skipUnless(sys.platform.startswith("win"), "requires PowerShell")
    def test_release_distribution_handoff_scripts_install_upgrade_uninstall_from_portable_package(self):
        self._prepare_runtime(channel="release")

        payload = export_release_distribution_handoff(
            self.project_dir,
            runtime_root=self.runtime_dir,
            target_channel="release",
            target_environment="production",
            release_manifest_path="api_server/static/dist/release_manifest.json",
        )

        target_root = self.runtime_dir / "handoff_installed_release"
        temp_root = self.runtime_dir / "handoff_temp"
        current_dir = target_root / "current"
        install_script_path = self.runtime_dir / payload["handoff_install_script_path"]
        upgrade_script_path = self.runtime_dir / payload["handoff_upgrade_script_path"]
        uninstall_script_path = self.runtime_dir / payload["handoff_uninstall_script_path"]

        install_run = subprocess.run(
            [
                "powershell",
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(install_script_path),
                "-TargetRoot",
                str(target_root),
                "-TempRoot",
                str(temp_root),
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
        self.assertEqual(install_run.returncode, 0)
        install_payload = json.loads(install_run.stdout)
        self.assertEqual(install_payload["status"], "passed")
        self.assertEqual(install_payload["inner_result"]["build_id"], "web-release-001")
        self.assertTrue((target_root / "web-release-001" / "index.html").exists())
        self.assertTrue((current_dir / "index.html").exists())

        marker_path = current_dir / "__handoff_upgrade_marker.txt"
        marker_path.write_text("handoff-marker", encoding="utf-8")

        upgrade_run = subprocess.run(
            [
                "powershell",
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(upgrade_script_path),
                "-TargetRoot",
                str(target_root),
                "-TempRoot",
                str(temp_root),
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
        self.assertEqual(upgrade_run.returncode, 0)
        upgrade_payload = json.loads(upgrade_run.stdout)
        self.assertEqual(upgrade_payload["status"], "passed")
        self.assertEqual(upgrade_payload["inner_result"]["previous_build_id"], "web-release-001")
        self.assertTrue(str(upgrade_payload["inner_result"]["backup_dir"]).strip())
        self.assertTrue((Path(upgrade_payload["inner_result"]["backup_dir"]) / "__handoff_upgrade_marker.txt").exists())

        uninstall_run = subprocess.run(
            [
                "powershell",
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(uninstall_script_path),
                "-TargetRoot",
                str(target_root),
                "-TempRoot",
                str(temp_root),
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
        self.assertEqual(uninstall_run.returncode, 0)
        uninstall_payload = json.loads(uninstall_run.stdout)
        self.assertEqual(uninstall_payload["status"], "passed")
        self.assertEqual(uninstall_payload["inner_result"]["removed_build_id"], "web-release-001")
        self.assertFalse((target_root / "web-release-001").exists())
        self.assertFalse(current_dir.exists())

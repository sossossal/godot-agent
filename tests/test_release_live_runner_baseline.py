import json
import shutil
import sys
import unittest
from pathlib import Path
from unittest.mock import patch


project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from agent_system.tools import release_live_runner_baseline as baseline_module
from tools.export_release_live_runner_baseline import main


class ReleaseLiveRunnerBaselineTestCase(unittest.TestCase):
    def setUp(self):
        self.project_dir = project_root / "tests" / ".tmp_release_live_runner_project"
        self.runtime_dir = project_root / "tests" / ".tmp_release_live_runner_runtime"
        shutil.rmtree(self.project_dir, ignore_errors=True)
        shutil.rmtree(self.runtime_dir, ignore_errors=True)
        self.project_dir.mkdir(parents=True, exist_ok=True)
        self.runtime_dir.mkdir(parents=True, exist_ok=True)

    def tearDown(self):
        shutil.rmtree(self.project_dir, ignore_errors=True)
        shutil.rmtree(self.runtime_dir, ignore_errors=True)

    def _prepare_project_files(self) -> tuple[Path, Path]:
        tools_dir = self.project_dir / "tools"
        tools_dir.mkdir(parents=True, exist_ok=True)
        deployment_dir = self.project_dir / "deployment"
        deployment_dir.mkdir(parents=True, exist_ok=True)
        for relative_path in (
            "tools/run_full_live_validation.ps1",
            "tools/run_portal_browser_smoke.ps1",
            "tools/run_portal_browser_click_smoke.py",
            "tools/run_remote_mcp_live_smoke.ps1",
            "tools/export_release_live_ci_artifacts.py",
        ):
            path = self.project_dir / relative_path
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("# fixture\n", encoding="utf-8")

        godot_executable = self.project_dir / "fake_godot.exe"
        browser_executable = self.project_dir / "fake_chrome.exe"
        godot_executable.write_text("godot", encoding="utf-8")
        browser_executable.write_text("chrome", encoding="utf-8")
        (self.project_dir / "config.yaml").write_text(
            f"godot:\n  executable_path: \"{godot_executable}\"\n",
            encoding="utf-8",
        )
        (deployment_dir / "release_live_runner_profile.json").write_text(
            json.dumps(
                {
                    "schema_version": "1.0",
                    "profiles": [
                        {
                            "profile_id": "release_windows_runner",
                            "target_channels": ["release"],
                            "target_environments": ["production"],
                            "required_runner_os": "Windows",
                            "required_runner_arches": ["x64"],
                            "required_runner_labels": ["self-hosted", "windows", "godot"],
                            "allowed_runner_names": [],
                        }
                    ],
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

        manifest_path = self.runtime_dir / "api_server" / "static" / "dist" / "release_manifest.json"
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        manifest_path.write_text(
            json.dumps({"build_id": "web-release-001", "version": "0.1.0", "channel": "release"}, ensure_ascii=False),
            encoding="utf-8",
        )
        return godot_executable, browser_executable

    def test_build_release_live_runner_baseline_writes_passed_report(self):
        _, browser_executable = self._prepare_project_files()

        with patch.dict(baseline_module.os.environ, {"RUNNER_OS": "Windows", "RUNNER_ARCH": "X64"}, clear=False):
            with patch.object(baseline_module.sys, "platform", "win32"):
                with patch.object(
                    baseline_module,
                    "_resolve_powershell_executable",
                    return_value={"path": "powershell", "source": "path", "source_label": "powershell"},
                ):
                    payload = baseline_module.build_release_live_runner_baseline(
                        self.project_dir,
                        runtime_root=self.runtime_dir,
                        target_channel="release",
                        target_environment="production",
                        release_manifest_path="api_server/static/dist/release_manifest.json",
                        browser_path=str(browser_executable),
                        declared_runner_labels='["self-hosted","windows","godot"]',
                    )

        self.assertEqual(payload["status"], "passed")
        self.assertEqual(payload["blocking_checks"], [])
        self.assertEqual(payload["check_count"], 15)
        self.assertTrue((self.runtime_dir / payload["report_path"]).exists())
        self.assertEqual(payload["runner_profile_id"], "release_windows_runner")
        self.assertEqual(payload["runner_os"], "Windows")
        self.assertEqual(payload["runner_arch"], "x64")
        self.assertEqual(payload["declared_runner_labels"], ["self-hosted", "windows", "godot"])
        self.assertEqual(payload["detected_tools"]["browser_executable"], str(browser_executable.resolve()))

    def test_main_returns_nonzero_when_runner_baseline_blocks(self):
        self._prepare_project_files()
        manifest_path = self.runtime_dir / "api_server" / "static" / "dist" / "release_manifest.json"
        manifest_path.unlink()

        with patch.object(baseline_module.sys, "platform", "win32"):
            with patch.object(
                baseline_module,
                "_resolve_powershell_executable",
                return_value={"path": "powershell", "source": "path", "source_label": "powershell"},
            ):
                with patch.object(
                    baseline_module,
                    "_resolve_chromium_browser",
                    return_value={"path": "", "source": "", "source_label": ""},
                ):
                    exit_code = main(
                        [
                            "--project-root",
                            str(self.project_dir),
                            "--runtime-root",
                            str(self.runtime_dir),
                            "--channel",
                            "release",
                            "--target-environment",
                            "production",
                            "--release-manifest-path",
                            "api_server/static/dist/release_manifest.json",
                            "--fail-on-blockers",
                        ]
                    )

        self.assertEqual(exit_code, 1)
        report_path = self.runtime_dir / baseline_module.default_release_live_runner_baseline_report_path(target_channel="release")
        payload = json.loads(report_path.read_text(encoding="utf-8"))
        self.assertEqual(payload["status"], "blocked")
        self.assertIn("chromium_browser", payload["blocking_checks"])
        self.assertIn("release_manifest_present", payload["blocking_checks"])

    def test_build_release_live_runner_baseline_blocks_when_runner_name_violates_profile(self):
        _, browser_executable = self._prepare_project_files()
        profile_path = self.project_dir / "deployment" / "release_live_runner_profile.json"
        profile_payload = json.loads(profile_path.read_text(encoding="utf-8"))
        profile_payload["profiles"][0]["allowed_runner_names"] = ["godot-release-01"]
        profile_path.write_text(json.dumps(profile_payload, ensure_ascii=False, indent=2), encoding="utf-8")

        with patch.dict(
            baseline_module.os.environ,
            {"RUNNER_OS": "Windows", "RUNNER_ARCH": "X64", "RUNNER_NAME": "godot-release-02"},
            clear=False,
        ):
            with patch.object(baseline_module.sys, "platform", "win32"):
                with patch.object(
                    baseline_module,
                    "_resolve_powershell_executable",
                    return_value={"path": "powershell", "source": "path", "source_label": "powershell"},
                ):
                    payload = baseline_module.build_release_live_runner_baseline(
                        self.project_dir,
                        runtime_root=self.runtime_dir,
                        target_channel="release",
                        target_environment="production",
                        release_manifest_path="api_server/static/dist/release_manifest.json",
                        browser_path=str(browser_executable),
                        declared_runner_labels='["self-hosted","windows","godot"]',
                    )

        self.assertEqual(payload["status"], "blocked")
        self.assertIn("runner_name_match", payload["blocking_checks"])
        self.assertEqual(payload["runner_name"], "godot-release-02")

    def test_build_release_live_runner_baseline_blocks_when_runner_labels_violate_profile(self):
        _, browser_executable = self._prepare_project_files()

        with patch.dict(
            baseline_module.os.environ,
            {"RUNNER_OS": "Windows", "RUNNER_ARCH": "X64", "RUNNER_NAME": "godot-release-01"},
            clear=False,
        ):
            with patch.object(baseline_module.sys, "platform", "win32"):
                with patch.object(
                    baseline_module,
                    "_resolve_powershell_executable",
                    return_value={"path": "powershell", "source": "path", "source_label": "powershell"},
                ):
                    payload = baseline_module.build_release_live_runner_baseline(
                        self.project_dir,
                        runtime_root=self.runtime_dir,
                        target_channel="release",
                        target_environment="production",
                        release_manifest_path="api_server/static/dist/release_manifest.json",
                        browser_path=str(browser_executable),
                        declared_runner_labels='["self-hosted","windows"]',
                    )

        self.assertEqual(payload["status"], "blocked")
        self.assertIn("runner_labels_match", payload["blocking_checks"])
        self.assertEqual(payload["declared_runner_labels"], ["self-hosted", "windows"])


if __name__ == "__main__":
    unittest.main()

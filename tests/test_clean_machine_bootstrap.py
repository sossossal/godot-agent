import json
import os
import shutil
import subprocess
import unittest
from pathlib import Path


project_root = Path(__file__).parent.parent
script_path = project_root / "tools" / "bootstrap_clean_machine.ps1"


@unittest.skipUnless(os.name == "nt", "PowerShell bootstrap script test requires Windows")
class CleanMachineBootstrapScriptTestCase(unittest.TestCase):
    def setUp(self):
        self.repo_dir = project_root / "tests" / ".tmp_clean_machine_bootstrap"
        shutil.rmtree(self.repo_dir, ignore_errors=True)
        (self.repo_dir / "tools").mkdir(parents=True, exist_ok=True)
        (self.repo_dir / "addons" / "godot_agent").mkdir(parents=True, exist_ok=True)
        (self.repo_dir / "tests").mkdir(parents=True, exist_ok=True)
        (self.repo_dir / "requirements.txt").write_text("pytest==7.4.4\n", encoding="utf-8")
        (self.repo_dir / "config.yaml").write_text("godot:\n  executable_path: \"\"\n", encoding="utf-8")
        (self.repo_dir / "tools" / "sync_plugin.ps1").write_text(
            "[ordered]@{ ok = $true } | ConvertTo-Json -Depth 3\n",
            encoding="utf-8",
        )
        for relative_path in (
            "tests/test_godot_cli.py",
            "tests/test_cli.py",
            "tests/test_agent_compatibility.py",
            "tests/test_api.py",
        ):
            (self.repo_dir / relative_path).write_text("pass\n", encoding="utf-8")

    def tearDown(self):
        shutil.rmtree(self.repo_dir, ignore_errors=True)

    def _run_script(self, *extra_args: str) -> dict:
        completed = subprocess.run(
            [
                "powershell",
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(script_path),
                "-RepoRoot",
                str(self.repo_dir),
                *extra_args,
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
        if completed.returncode != 0:
            self.fail(f"bootstrap script failed: {completed.stdout}\n{completed.stderr}")
        return json.loads(completed.stdout)

    def test_preview_lists_default_bootstrap_steps_and_report_target(self):
        payload = self._run_script("-Preview")

        self.assertTrue(payload["ok"])
        self.assertTrue(payload["preview"])
        self.assertTrue(payload["python"]["uses_virtualenv"])
        self.assertFalse(payload["python"]["virtualenv_ready"])
        self.assertTrue(payload["report_path"].endswith("logs\\reports\\clean_machine_bootstrap.json"))
        self.assertTrue(payload["doctor_report_path"].endswith("logs\\reports\\doctor_self_check.json"))
        self.assertTrue(payload["temp_root"].endswith("logs\\test_artifacts\\bootstrap_tmp"))
        self.assertEqual(
            [step["id"] for step in payload["steps"] if step["enabled"]],
            ["create_venv", "install_requirements", "sync_plugin", "doctor"],
        )
        doctor_step = next(step for step in payload["steps"] if step["id"] == "doctor")
        self.assertIn("--report-path", doctor_step["command"])
        self.assertIn("doctor_self_check.json", doctor_step["command"])

    def test_preview_surfaces_missing_sync_script_and_optional_smoke_step(self):
        (self.repo_dir / "tools" / "sync_plugin.ps1").unlink()

        payload = self._run_script("-Preview", "-IncludeSmoke")

        self.assertFalse(payload["ok"])
        self.assertIn("missing_sync_script", {item["code"] for item in payload["blocking_issues"]})
        smoke_step = next(step for step in payload["steps"] if step["id"] == "bootstrap_smoke")
        self.assertTrue(smoke_step["enabled"])
        self.assertIn("pytest", smoke_step["command"])

    def test_preview_clears_partial_virtualenv_before_recreating_it(self):
        partial_scripts = self.repo_dir / ".venv" / "Scripts"
        partial_scripts.mkdir(parents=True, exist_ok=True)
        (partial_scripts / "python.exe").write_text("stub\n", encoding="utf-8")
        (self.repo_dir / ".venv" / "pyvenv.cfg").write_text("home = C:/Python312\n", encoding="utf-8")

        payload = self._run_script("-Preview")

        self.assertFalse(payload["python"]["virtualenv_ready"])
        create_step = next(step for step in payload["steps"] if step["id"] == "create_venv")
        self.assertIn("--clear", create_step["arguments"])


if __name__ == "__main__":
    unittest.main()

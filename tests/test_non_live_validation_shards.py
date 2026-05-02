from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path


project_root = Path(__file__).resolve().parents[1]
script_path = project_root / "tools" / "run_non_live_validation_shards.ps1"
gate_script_path = project_root / "tools" / "run_pr_release_gate.ps1"


class NonLiveValidationShardsTestCase(unittest.TestCase):
    @unittest.skipUnless(sys.platform.startswith("win"), "requires PowerShell")
    def test_preview_supports_release_profile_and_slow_threshold(self):
        completed = subprocess.run(
            [
                "powershell",
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(script_path),
                "-PythonCommand",
                sys.executable,
                "-Profile",
                "release",
                "-SlowShardSeconds",
                "1",
                "-Preview",
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )

        self.assertEqual(completed.returncode, 0, completed.stderr)
        payload = json.loads(completed.stdout)
        self.assertTrue(payload["ok"])
        self.assertTrue(payload["preview"])
        self.assertEqual(payload["profile"], "release")
        self.assertEqual(payload["slow_shard_threshold_seconds"], 1)
        shard_ids = [item["id"] for item in payload["shards"]]
        self.assertIn("release_live_ci", shard_ids)
        self.assertIn("promotion_history", shard_ids)
        self.assertNotIn("api", shard_ids)

    @unittest.skipUnless(sys.platform.startswith("win"), "requires PowerShell")
    def test_pr_release_gate_preview_maps_stages_to_profiles(self):
        completed = subprocess.run(
            [
                "powershell",
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(gate_script_path),
                "-Stage",
                "release",
                "-Mode",
                "full",
                "-PythonCommand",
                sys.executable,
                "-Preview",
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )

        self.assertEqual(completed.returncode, 0, completed.stderr)
        payload = json.loads(completed.stdout)
        self.assertTrue(payload["ok"])
        self.assertTrue(payload["preview"])
        self.assertEqual(payload["stage"], "release")
        self.assertEqual(payload["mode"], "full")
        self.assertEqual(payload["non_live_profile"], "release")
        step_ids = [item["id"] for item in payload["steps"]]
        self.assertEqual(step_ids, ["git_diff_check", "non_live_validation", "release_live_preflight"])

    @unittest.skipUnless(sys.platform.startswith("win"), "requires PowerShell")
    def test_pr_release_gate_preflight_mode_skips_non_live_shards(self):
        completed = subprocess.run(
            [
                "powershell",
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(gate_script_path),
                "-Stage",
                "customer",
                "-Mode",
                "preflight",
                "-PythonCommand",
                sys.executable,
                "-Preview",
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )

        self.assertEqual(completed.returncode, 0, completed.stderr)
        payload = json.loads(completed.stdout)
        self.assertEqual(payload["mode"], "preflight")
        self.assertEqual(payload["non_live_profile"], "customer")
        step_ids = [item["id"] for item in payload["steps"]]
        self.assertEqual(step_ids, ["release_live_preflight"])


if __name__ == "__main__":
    unittest.main()

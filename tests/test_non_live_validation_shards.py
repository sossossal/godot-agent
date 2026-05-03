from __future__ import annotations

import json
import shutil
import subprocess
import sys
import unittest
from pathlib import Path


project_root = Path(__file__).resolve().parents[1]
script_path = project_root / "tools" / "run_non_live_validation_shards.ps1"
gate_script_path = project_root / "tools" / "run_pr_release_gate.ps1"
gate_workflow_path = project_root / ".github" / "workflows" / "pr-release-gate.yml"
release_live_workflow_path = project_root / ".github" / "workflows" / "release-live-gates.yml"
customer_bundle_script_path = project_root / "tools" / "export_customer_trial_bundle.ps1"
fixture_script_path = project_root / "tools" / "prepare_release_live_fixture.py"


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
                "-FailOnSlowShards",
                "-PrepareReleaseFixture",
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
        self.assertTrue(payload["fail_on_slow_shards"])
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
                "-FailOnSlowShards",
                "-PrepareReleaseFixture",
                "-RestorePreparedFixture",
                "-ContinueOnFailure",
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
        self.assertTrue(payload["fail_on_slow_shards"])
        self.assertTrue(payload["continue_on_failure"])
        self.assertTrue(payload["prepare_release_fixture"])
        self.assertTrue(payload["restore_prepared_fixture"])
        self.assertTrue(payload["prepared_release_fixture_state_root"].endswith("prepared_fixture_state"))
        self.assertTrue(payload["prepared_release_fixture_report_path"].endswith("release_live_fixture.json"))
        self.assertTrue(payload["prepared_release_fixture_markdown_path"].endswith("release_live_fixture.md"))
        self.assertEqual(payload["prepared_release_fixture_scope"], "full")
        step_ids = [item["id"] for item in payload["steps"]]
        self.assertEqual(step_ids, ["git_diff_check", "prepare_release_fixture", "non_live_validation", "release_live_preflight"])
        fixture_step = payload["steps"][1]
        self.assertIn("--scope", fixture_step["arguments"])
        self.assertIn("full", fixture_step["arguments"])
        self.assertIn("--report-path", fixture_step["arguments"])
        non_live_step = payload["steps"][2]
        self.assertIn("-FailOnSlowShards", non_live_step["arguments"])

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

    @unittest.skipUnless(sys.platform.startswith("win"), "requires PowerShell")
    def test_pr_release_gate_preflight_fixture_uses_lightweight_scope(self):
        completed = subprocess.run(
            [
                "powershell",
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(gate_script_path),
                "-Stage",
                "merge",
                "-Mode",
                "preflight",
                "-PythonCommand",
                sys.executable,
                "-PrepareReleaseFixture",
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
        self.assertEqual(payload["prepared_release_fixture_scope"], "preflight")
        fixture_step = payload["steps"][1]
        self.assertEqual(fixture_step["id"], "prepare_release_fixture")
        self.assertIn("--scope", fixture_step["arguments"])
        self.assertIn("preflight", fixture_step["arguments"])

    def test_prepare_release_live_fixture_preflight_scope_uses_stdlib_only(self):
        output_dir = project_root / "tests" / ".tmp_preflight_fixture"
        managed_paths = [
            project_root / "api_server" / "static" / "dist" / "release_manifest.json",
            project_root / "api_server" / "static" / "dist" / "release_notes.md",
            project_root / "api_server" / "static" / "dist" / "web_release_validation_ci",
        ]
        backups = []
        for path in managed_paths:
            backup = output_dir / "backup" / path.relative_to(project_root)
            backups.append((path, backup, path.exists(), path.is_dir() if path.exists() else False))
        shutil.rmtree(output_dir, ignore_errors=True)
        try:
            for path, backup, exists, is_dir in backups:
                if not exists:
                    continue
                backup.parent.mkdir(parents=True, exist_ok=True)
                if is_dir:
                    shutil.copytree(path, backup)
                else:
                    shutil.copy2(path, backup)

            completed = subprocess.run(
                [
                    sys.executable,
                    "-S",
                    str(fixture_script_path),
                    "--scope",
                    "preflight",
                    "--report-path",
                    str(output_dir / "release_live_fixture.json"),
                    "--markdown-path",
                    str(output_dir / "release_live_fixture.md"),
                ],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                check=False,
            )

            self.assertEqual(completed.returncode, 0, completed.stderr)
            payload = json.loads((output_dir / "release_live_fixture.json").read_text(encoding="utf-8"))
            self.assertEqual(payload["fixture_scope"], "preflight")
            self.assertEqual(payload["manifest_path"], "api_server/static/dist/release_manifest.json")
        finally:
            for path, backup, exists, is_dir in reversed(backups):
                if path.exists():
                    if path.is_dir():
                        shutil.rmtree(path, ignore_errors=True)
                    else:
                        path.unlink()
                if exists and backup.exists():
                    path.parent.mkdir(parents=True, exist_ok=True)
                    if is_dir:
                        shutil.copytree(backup, path)
                    else:
                        shutil.copy2(backup, path)
            shutil.rmtree(output_dir, ignore_errors=True)

    def test_pr_release_gate_workflow_uses_lightweight_pr_preflight(self):
        workflow = gate_workflow_path.read_text(encoding="utf-8")

        self.assertIn("name: pr-release-gate", workflow)
        self.assertIn("pull_request:", workflow)
        self.assertIn("$stage = \"pr\"", workflow)
        self.assertIn("$mode = \"preflight\"", workflow)
        self.assertIn("$gateParams = @{", workflow)
        self.assertIn("Stage = $env:GATE_STAGE", workflow)
        self.assertIn(".\\tools\\run_pr_release_gate.ps1 @gateParams", workflow)
        self.assertNotIn("@args", workflow)
        self.assertIn("logs/reports/pr_release_gate", workflow)
        self.assertIn("fail_on_slow_shards", workflow)
        self.assertIn("$gateParams.FailOnSlowShards = $true", workflow)
        self.assertIn('$prepareReleaseFixture = "false"', workflow)
        self.assertIn('$prepareReleaseFixture = "true"', workflow)
        self.assertIn('if ($stage -in @("merge", "release", "customer")) { $prepareReleaseFixture = "true" }', workflow)
        self.assertIn("PREPARE_RELEASE_FIXTURE", workflow)
        self.assertIn("$gateParams.PrepareReleaseFixture = $true", workflow)
        self.assertIn("Install dependencies for full gate", workflow)
        self.assertIn("if: steps.gate_inputs.outputs.mode == 'full'", workflow)
        gate_script = gate_script_path.read_text(encoding="utf-8")
        self.assertIn("- Prepared fixture report:", gate_script)
        self.assertIn("- Prepared fixture markdown:", gate_script)

    def test_release_live_workflow_uses_full_fixture_script(self):
        workflow = release_live_workflow_path.read_text(encoding="utf-8")

        self.assertIn("tools\\prepare_release_live_fixture.py", workflow)
        self.assertIn("--scope full", workflow)
        self.assertIn("release_live_fixture.json", workflow)
        self.assertIn("release_live_fixture.md", workflow)
        self.assertIn("step_id = 'prepare_release_fixture'", workflow)
        self.assertIn("outcome = '${{ steps.prepare_release_fixture.outcome }}'", workflow)
        self.assertNotIn("python -c \"from tools.export_release_ci_artifacts", workflow)

    @unittest.skipUnless(sys.platform.startswith("win"), "requires PowerShell")
    def test_customer_trial_bundle_preview_runs_doctor_and_customer_gate(self):
        completed = subprocess.run(
            [
                "powershell",
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(customer_bundle_script_path),
                "-PythonCommand",
                sys.executable,
                "-GateMode",
                "preflight",
                "-ReleaseManifestPath",
                "trial/release_manifest.json",
                "-BrowserPath",
                "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe",
                "-PrepareReleaseFixture",
                "-RestorePreparedFixture",
                "-SyncPluginBeforeDoctor",
                "-FailOnNeedsAttention",
                "-ContinueOnFailure",
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
        self.assertEqual(payload["gate_mode"], "preflight")
        self.assertEqual(payload["release_manifest_path"], "trial/release_manifest.json")
        self.assertEqual(payload["browser_path"], "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe")
        self.assertTrue(payload["fail_on_needs_attention"])
        self.assertTrue(payload["continue_on_failure"])
        self.assertTrue(payload["prepare_release_fixture"])
        self.assertTrue(payload["restore_prepared_fixture"])
        self.assertTrue(payload["sync_plugin_before_doctor"])
        self.assertTrue(payload["manifest_path"].endswith("customer_trial_bundle_manifest.json"))
        self.assertTrue(payload["rerun_script_path"].endswith("rerun_customer_trial.ps1"))
        self.assertTrue(payload["command_manifest_path"].endswith("customer_trial_commands.json"))
        self.assertTrue(payload["readiness_summary_path"].endswith("customer_trial_readiness.json"))
        self.assertEqual([item["id"] for item in payload["command_records"]], ["sync_plugin", "doctor", "customer_gate"])
        step_ids = [item["id"] for item in payload["steps"]]
        self.assertEqual(step_ids, ["sync_plugin", "doctor", "customer_gate"])
        sync_step = payload["steps"][0]
        self.assertIn("sync_plugin.ps1", sync_step["arguments"][4])
        gate_step = payload["steps"][2]
        self.assertIn("-Stage", gate_step["arguments"])
        self.assertIn("customer", gate_step["arguments"])
        self.assertIn("-Mode", gate_step["arguments"])
        self.assertIn("preflight", gate_step["arguments"])
        self.assertIn("-ReleaseManifestPath", gate_step["arguments"])
        self.assertIn("trial/release_manifest.json", gate_step["arguments"])
        self.assertIn("-BrowserPath", gate_step["arguments"])
        self.assertIn("C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe", gate_step["arguments"])
        self.assertIn("-PrepareReleaseFixture", gate_step["arguments"])
        self.assertIn("-RestorePreparedFixture", gate_step["arguments"])

    def test_prepare_release_live_fixture_preview_lists_manifest_and_reports(self):
        completed = subprocess.run(
            [
                sys.executable,
                str(fixture_script_path),
                "--channel",
                "release",
                "--preview",
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
        self.assertEqual(payload["manifest_path"], "api_server/static/dist/release_manifest.json")
        self.assertTrue(payload["report_path"].endswith("release_live_fixture.json"))
        self.assertIn("logs/reports/full_live_validation.json", payload["runtime_reports"])

    @unittest.skipUnless(sys.platform.startswith("win"), "requires PowerShell")
    def test_customer_trial_bundle_collects_recommended_actions_when_blocked(self):
        output_dir = project_root / "tests" / ".tmp_customer_trial_bundle"
        shutil.rmtree(output_dir, ignore_errors=True)
        try:
            completed = subprocess.run(
                [
                    "powershell",
                    "-NoProfile",
                    "-ExecutionPolicy",
                    "Bypass",
                    "-File",
                    str(customer_bundle_script_path),
                    "-PythonCommand",
                    sys.executable,
                    "-GateMode",
                    "preflight",
                    "-OutputDir",
                    str(output_dir),
                    "-ReleaseManifestPath",
                    "missing/release_manifest.json",
                    "-ContinueOnFailure",
                ],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                check=False,
            )

            self.assertEqual(completed.returncode, 1)
            manifest_path = output_dir / "customer_trial_bundle_manifest.json"
            self.assertTrue(manifest_path.exists())
            payload = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
            self.assertIn("recommended_actions", payload)
            self.assertTrue(payload["recommended_actions"])
            self.assertIn("recommended_action_items", payload)
            self.assertTrue(payload["recommended_action_items"])
            self.assertEqual(payload["recommended_action_items"][0]["source"], "release_live_preflight")
            self.assertEqual(payload["release_manifest_path"], "missing/release_manifest.json")
            self.assertTrue(payload["continue_on_failure"])
            markdown_path = output_dir / "customer_trial_bundle.md"
            self.assertTrue(markdown_path.exists())
            markdown = markdown_path.read_text(encoding="utf-8-sig")
            self.assertIn("## Recommended Actions", markdown)
            self.assertIn("- Release manifest: missing/release_manifest.json", markdown)
            self.assertIn("- Continue on failure: True", markdown)
            self.assertIn("[release_live_preflight/", markdown)
            self.assertIn("## Rerun Commands", markdown)
            self.assertIn("customer_gate", markdown)
            self.assertIn("## Blocked Step Output", markdown)
            self.assertIn("## Evidence Files", markdown)
            self.assertIn("- Missing: None", markdown)
            gate_markdown = output_dir / "gate" / "gate_summary.md"
            self.assertTrue(gate_markdown.exists())
            gate_summary = gate_markdown.read_text(encoding="utf-8-sig")
            self.assertIn("## Step Diagnostics", gate_summary)
            self.assertIn("- Warnings:", gate_summary)
            self.assertIn("- Continue on failure: True", gate_summary)
            self.assertIn("Live preflight blocked checks: release_manifest", gate_summary)
            self.assertIn("- Command:", gate_summary)
            rerun_script = output_dir / "rerun_customer_trial.ps1"
            self.assertTrue(rerun_script.exists())
            rerun_text = rerun_script.read_text(encoding="utf-8-sig")
            self.assertIn(f"Set-Location {project_root}", rerun_text)
            self.assertIn("Run customer trial gate", rerun_text)
            self.assertIn("-ReleaseManifestPath missing/release_manifest.json", rerun_text)
            command_manifest = output_dir / "customer_trial_commands.json"
            self.assertTrue(command_manifest.exists())
            command_payload = json.loads(command_manifest.read_text(encoding="utf-8-sig"))
            self.assertEqual(command_payload["schema_version"], "1.0")
            self.assertEqual(command_payload["commands"][-1]["id"], "customer_gate")
            self.assertIn("-ReleaseManifestPath missing/release_manifest.json", command_payload["commands"][-1]["command_line"])
            readiness_path = output_dir / "customer_trial_readiness.json"
            self.assertTrue(readiness_path.exists())
            readiness_payload = json.loads(readiness_path.read_text(encoding="utf-8-sig"))
            self.assertEqual(readiness_payload["status"], "blocked")
            self.assertEqual(readiness_payload["readiness_level"], "blocked")
            self.assertEqual(readiness_payload["release_manifest_path"], "missing/release_manifest.json")
            self.assertTrue(readiness_payload["continue_on_failure"])
            self.assertFalse(readiness_payload["fail_on_needs_attention"])
            self.assertFalse(readiness_payload["should_fail_on_needs_attention"])
            self.assertTrue(readiness_payload["recommended_action_items"])
            self.assertEqual(readiness_payload["recommended_action_items"][0]["action"], payload["recommended_actions"][0])
            self.assertIn("customer_gate", readiness_payload["blocked_steps"])
            self.assertEqual(readiness_payload["command_count"], 2)
            readiness_evidence_paths = [item["relative_path"] for item in readiness_payload["evidence_files"]]
            self.assertEqual(readiness_payload["evidence_file_count"], len(readiness_evidence_paths))
            self.assertEqual(readiness_payload["missing_evidence_files"], [])
            for item in readiness_payload["evidence_files"]:
                self.assertTrue(Path(item["path"]).exists(), item)
            self.assertIn("gate/gate_summary.json", readiness_evidence_paths)
            self.assertIn("gate/release_live_preflight.json", readiness_evidence_paths)
            self.assertIn("customer_trial_commands.json", readiness_evidence_paths)
            self.assertIn("customer_trial_readiness.json", readiness_evidence_paths)
            evidence_paths = [item["relative_path"] for item in payload["evidence_files"]]
            self.assertEqual(payload["evidence_file_count"], len(evidence_paths))
            self.assertEqual(payload["missing_evidence_files"], [])
            for item in payload["evidence_files"]:
                self.assertTrue(Path(item["path"]).exists(), item)
            self.assertIn("customer_trial_commands.json", evidence_paths)
            self.assertIn("customer_trial_readiness.json", evidence_paths)
            self.assertIn(f"- Count: {payload['evidence_file_count']}", markdown)
        finally:
            shutil.rmtree(output_dir, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()

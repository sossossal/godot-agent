import json
import shutil
import sys
import unittest
from pathlib import Path

from fastapi.testclient import TestClient


project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from agent_system.tools.release_candidate import build_release_candidate_checklist
from api_server.main import app


class ReleaseCandidateChecklistTestCase(unittest.TestCase):
    def setUp(self):
        self.project_dir = project_root / "tests" / ".tmp_release_candidate_project"
        self.runtime_dir = project_root / "tests" / ".tmp_release_candidate_runtime"
        shutil.rmtree(self.project_dir, ignore_errors=True)
        shutil.rmtree(self.runtime_dir, ignore_errors=True)
        self.project_dir.mkdir(parents=True, exist_ok=True)
        self.runtime_dir.mkdir(parents=True, exist_ok=True)

    def tearDown(self):
        shutil.rmtree(self.project_dir, ignore_errors=True)
        shutil.rmtree(self.runtime_dir, ignore_errors=True)

    def _prepare_release_candidate_runtime(
        self,
        *,
        feature_status: str = "approved",
        channel: str = "release",
        acceptance_status: str = "ready",
        qa_evidence_ready: bool = True,
    ) -> None:
        (self.project_dir / "project.godot").write_text("; test project\n", encoding="utf-8")
        (self.project_dir / "README.md").write_text("# temp project\n", encoding="utf-8")
        (self.project_dir / "tests").mkdir(parents=True, exist_ok=True)
        for relative in ["scenes", "scripts"]:
            (self.project_dir / relative).mkdir(parents=True, exist_ok=True)
        (self.runtime_dir / "tests" / "baselines" / "performance").mkdir(parents=True, exist_ok=True)

        dist_dir = self.runtime_dir / "api_server" / "static" / "dist"
        dist_dir.mkdir(parents=True, exist_ok=True)
        release_dir = dist_dir / "web_20260413"
        release_dir.mkdir(parents=True, exist_ok=True)

        qa_report_path = release_dir / "qa_gate_report.md"
        notes_path = release_dir / "release_notes.md"
        build_log_path = release_dir / "build.log"
        output_path = release_dir / "index.html"
        qa_report_path.write_text("# QA Gate\n", encoding="utf-8")
        notes_path.write_text("# Release Notes\n", encoding="utf-8")
        build_log_path.write_text("build ok\n", encoding="utf-8")
        output_path.write_text("<html></html>", encoding="utf-8")

        manifest = {
            "schema_version": "1.0",
            "build_id": "web-release-001",
            "version": "0.1.0-release+1",
            "channel": channel,
            "preset_name": "Web",
            "platform": "web",
            "generated_at": "2026-04-13T10:00:00Z",
            "task_id": "task-001",
            "task_prompt": "发布 RC",
            "output_path": "api_server/static/dist/web_20260413/index.html",
            "release_dir": "api_server/static/dist/web_20260413",
            "release_url": "/portal/dist/index.html",
            "versioned_release_url": "/portal/dist/web_20260413/index.html",
            "build_log_path": "api_server/static/dist/web_20260413/build.log",
            "release_notes_path": "api_server/static/dist/web_20260413/release_notes.md",
            "release_manifest_path": "api_server/static/dist/web_20260413/release_manifest.json",
            "feature": {
                "schema_version": "1.0",
                "feature_id": "feature-001",
                "owner": "producer",
                "priority": "high",
                "risk": "medium",
                "feature_status": feature_status,
            },
            "change_summary": ["生成 RC 包"],
            "acceptance_checklist": [{"label": "冒烟通过", "status": acceptance_status}],
            "known_risks": [],
            "quality_gate": {
                "schema_version": "1.0",
                "passed": True,
                "channel": channel,
                "preset_name": "Web",
                "checks": [
                    {"name": "feature_status", "status": "passed", "message": "ok"},
                    {"name": "smoke_test", "status": "passed", "message": "ok"},
                    {"name": "performance_budget", "status": "passed", "message": "ok"},
                    {"name": "draw_call_budget", "status": "passed", "message": "ok"},
                    {"name": "telemetry_health", "status": "passed", "message": "ok"},
                ],
                "blocked_checks": [],
                "metrics": {"scene_load_ms": 320, "draw_call_count": 200},
            },
            "qa_evidence": {
                "scene_path": "res://scenes/release_gate.tscn",
                "smoke_status": "passed",
                "smoke_message": "scene ok",
                "assertion_status": "passed" if qa_evidence_ready else "skipped",
                "assertion_message": "assertions ok" if qa_evidence_ready else "未记录断言型 QA",
                "assertion_node_count": 2 if qa_evidence_ready else 0,
                "asserted_nodes": ["Player", "HUD"] if qa_evidence_ready else [],
                "screenshot_status": "passed" if qa_evidence_ready else "skipped",
                "screenshot_message": "visual ok" if qa_evidence_ready else "未记录 screenshot diff",
                "screenshot_path": "logs/test_artifacts/release_gate.png" if qa_evidence_ready else "",
                "screenshot_diff_ratio": 0.0125 if qa_evidence_ready else None,
                "max_screenshot_diff_ratio": 0.05 if qa_evidence_ready else None,
                "metrics": {"scene_load_ms": 320, "fps": 60.0, "memory_peak_mb": 144.0},
            },
            "files": [
                {"path": "index.html", "size": 13, "sha256": "abc"},
                {"path": "release_notes.md", "size": 16, "sha256": "def"},
            ],
            "rollback_hint": "恢复 web_20260413 到 latest",
        }
        manifest_text = json.dumps(manifest, ensure_ascii=False, indent=2)
        (release_dir / "release_manifest.json").write_text(manifest_text, encoding="utf-8")
        (dist_dir / "release_manifest.json").write_text(manifest_text, encoding="utf-8")
        (dist_dir / "release_notes.md").write_text("# Stable Release Notes\n", encoding="utf-8")
        (dist_dir / "qa_gate_report.md").write_text("# Stable QA Gate\n", encoding="utf-8")

    def test_repository_sample_builds_release_candidate_checklist(self):
        payload = build_release_candidate_checklist(project_root, runtime_root=project_root)

        self.assertEqual(payload["schema_version"], "1.0")
        self.assertIn(payload["release_manifest_source"], {"stable", "versioned_fallback", "missing"})
        self.assertIn(payload["status"], {"passed", "warning", "blocked"})
        if payload["release_manifest_source"] == "missing":
            self.assertIn("release_manifest", payload["blocking_checks"])
        else:
            self.assertTrue(str(payload["release_summary"]["build_id"]).startswith("web-"))
        self.assertTrue(any(item["item_id"] == "quality_gate" for item in payload["checklist"]))
        if payload["release_manifest_source"] != "missing":
            self.assertTrue(any(item["item_id"] == "performance_gate" for item in payload["checklist"]))
            self.assertTrue(any(item["item_id"] == "telemetry_gate" for item in payload["checklist"]))

    def test_release_candidate_blocks_when_manifest_is_missing(self):
        payload = build_release_candidate_checklist(self.project_dir, runtime_root=self.runtime_dir)

        self.assertEqual(payload["status"], "blocked")
        self.assertTrue(payload["should_block"])
        self.assertIn("release_manifest", payload["blocking_checks"])

    def test_release_candidate_passes_when_release_bundle_is_complete(self):
        self._prepare_release_candidate_runtime()

        payload = build_release_candidate_checklist(self.project_dir, runtime_root=self.runtime_dir)

        self.assertEqual(payload["status"], "warning")
        self.assertTrue(payload["should_block"])
        self.assertEqual(payload["release_summary"]["feature"]["feature_status"], "approved")
        self.assertEqual(payload["quality_gate"]["passed"], True)
        self.assertEqual(payload["mode"], "strict")
        self.assertTrue(payload["fail_on_warnings"])
        self.assertEqual(payload["release_summary"]["qa_evidence"]["assertion_status"], "passed")
        self.assertIn("production_gate", payload["warning_checks"])
        self.assertNotIn("quality_gate", payload["blocking_checks"])
        self.assertEqual(payload["release_manifest_path"], "api_server/static/dist/release_manifest.json")

    def test_release_candidate_blocks_unapproved_feature(self):
        self._prepare_release_candidate_runtime(feature_status="pending_acceptance", channel="release")

        payload = build_release_candidate_checklist(self.project_dir, runtime_root=self.runtime_dir)

        self.assertEqual(payload["status"], "blocked")
        self.assertIn("feature_approval", payload["blocking_checks"])

    def test_release_candidate_blocks_pending_acceptance_checklist_for_release_channel(self):
        self._prepare_release_candidate_runtime(acceptance_status="pending", channel="release")

        payload = build_release_candidate_checklist(self.project_dir, runtime_root=self.runtime_dir)

        self.assertEqual(payload["status"], "blocked")
        self.assertIn("acceptance_checklist", payload["blocking_checks"])

    def test_release_candidate_blocks_missing_assertion_and_visual_evidence_for_release_channel(self):
        self._prepare_release_candidate_runtime(channel="release", qa_evidence_ready=False)

        payload = build_release_candidate_checklist(self.project_dir, runtime_root=self.runtime_dir)

        self.assertEqual(payload["status"], "blocked")
        self.assertIn("qa_assertions", payload["blocking_checks"])
        self.assertIn("visual_regression", payload["blocking_checks"])

    def test_release_candidate_api_shape(self):
        self._prepare_release_candidate_runtime()

        client = TestClient(app)
        response = client.post(
            "/release-candidate/checklist",
            json={
                "project_path": str(self.project_dir),
                "mode": "advisory",
                "fail_on_warnings": False,
            },
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["schema_version"], "1.0")
        self.assertEqual(payload["project_path"], f"{self.project_dir.resolve().as_posix()}/")
        self.assertEqual(payload["mode"], "advisory")
        self.assertIn(payload["release_manifest_source"], {"stable", "versioned_fallback", "missing"})
        self.assertTrue(any(item["item_id"] == "production_gate" for item in payload["checklist"]))


if __name__ == "__main__":
    unittest.main()

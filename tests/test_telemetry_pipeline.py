import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import json


project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from agent_system.models import Task, TaskStatus, ToolResult
from agent_system.skills.resource.telemetry_skill import TelemetryPipelineSkill


class MockGodotCLI:
    def __init__(self, executable_path=None, project_path=None):
        self.executable = "godot"
        self.project_path = project_path

    def is_available(self):
        return True

    def run_headless(self, script_path, args=None):
        return ToolResult(True, "OK")

    def run_scene(self, scene_path):
        return ToolResult(True, "OK")

    def execute_editor_script(self, script_content):
        return ToolResult(True, "OK")

    def export_project(self, preset_name, output_path, release=True):
        return ToolResult(True, "OK")

    def get_version(self):
        return "4.2.0"


class TelemetryPipelineTestCase(unittest.TestCase):
    def setUp(self):
        self.project_dir = project_root / "tests" / ".tmp_telemetry_pipeline"
        shutil.rmtree(self.project_dir, ignore_errors=True)
        self.project_dir.mkdir(parents=True, exist_ok=True)
        self.history_file = tempfile.mktemp(suffix=".json")

    def tearDown(self):
        shutil.rmtree(self.project_dir, ignore_errors=True)
        if os.path.exists(self.history_file):
            os.remove(self.history_file)

    def test_telemetry_template_writes_event_catalog(self):
        skill = TelemetryPipelineSkill(MockGodotCLI(project_path=str(self.project_dir)))
        task = Task(prompt="新建遥测事件字典模板", context={"feature_id": "feature-telemetry"})
        result = skill.execute(task, {"action": "template"})

        catalog_path = self.project_dir / "telemetry" / "event_catalog.json"
        self.assertTrue(result.success)
        self.assertTrue(catalog_path.exists())
        self.assertEqual(task.context["contract_versions"]["telemetry_summary"], "1.4")
        self.assertEqual(task.context["telemetry_summary"]["schema_version"], "1.4")
        self.assertIn("session_start", catalog_path.read_text(encoding="utf-8"))
        self.assertIn("session_end", catalog_path.read_text(encoding="utf-8"))

    def test_telemetry_apply_blocks_uncataloged_events(self):
        skill = TelemetryPipelineSkill(MockGodotCLI(project_path=str(self.project_dir)))
        task = Task(prompt="导入遥测会话回流")
        result = skill.execute(task, {
            "action": "apply",
            "catalog_entries": [
                {
                    "event_name": "session_start",
                    "category": "session",
                    "description": "开始会话",
                    "privacy_level": "anonymous",
                    "fields": [{"name": "build_id", "type": "string", "required": True, "pii": False}],
                }
            ],
            "events": [
                {
                    "event_name": "session_start",
                    "session_id": "s1",
                    "timestamp": "2026-04-10T10:00:00Z",
                    "payload": {"build_id": "web-preview-1"},
                },
                {
                    "event_name": "level_complete",
                    "session_id": "s1",
                    "timestamp": "2026-04-10T10:01:00Z",
                    "payload": {"level_id": "level_01"},
                },
            ],
        })

        self.assertFalse(result.success)
        self.assertTrue(any("未登记的遥测事件" in issue for issue in task.context["telemetry_summary"]["issues"]))
        self.assertFalse((self.project_dir / "telemetry" / "sessions").exists())

    def test_telemetry_analyze_builds_retention_funnel_and_crash_taxonomy(self):
        liveops_dir = self.project_dir / "liveops"
        liveops_dir.mkdir(parents=True, exist_ok=True)
        (liveops_dir / "experiments.json").write_text(
            json.dumps({
                "schema_version": "1.0",
                "liveops_type": "experiment_catalog",
                "items": [
                    {
                        "experiment_id": "tutorial_branch_test",
                        "status": "running",
                        "target_metrics": ["d1_retention", "tutorial_completion_rate"],
                        "rollout_percentage": 50,
                        "owner": "product_ops",
                        "variants": [{"variant_id": "control", "weight": 50}, {"variant_id": "short_path", "weight": 50}],
                    }
                ],
            }, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        skill = TelemetryPipelineSkill(MockGodotCLI(project_path=str(self.project_dir)))
        task = Task(prompt="分析遥测留存与 crash taxonomy")
        result = skill.execute(task, {
            "action": "analyze",
            "catalog_entries": [
                {
                    "event_name": "session_start",
                    "category": "session",
                    "description": "开始会话",
                    "privacy_level": "anonymous",
                    "fields": [{"name": "build_id", "type": "string", "required": True, "pii": False}],
                },
                {
                    "event_name": "level_start",
                    "category": "gameplay",
                    "description": "开始关卡",
                    "privacy_level": "anonymous",
                    "fields": [],
                },
                {
                    "event_name": "level_complete",
                    "category": "gameplay",
                    "description": "完成关卡",
                    "privacy_level": "anonymous",
                    "fields": [],
                },
                {
                    "event_name": "session_end",
                    "category": "session",
                    "description": "结束会话",
                    "privacy_level": "anonymous",
                    "fields": [],
                },
                {
                    "event_name": "crash",
                    "category": "error",
                    "description": "崩溃",
                    "privacy_level": "restricted",
                    "fields": [{"name": "error_code", "type": "string", "required": True, "pii": False}],
                },
            ],
            "events": [
                {
                    "event_name": "session_start",
                    "session_id": "s1",
                    "timestamp": "2026-04-10T10:00:00Z",
                    "payload": {"build_id": "web-preview-1", "player_id": "p1"},
                },
                {"event_name": "level_start", "session_id": "s1", "timestamp": "2026-04-10T10:00:05Z", "payload": {}},
                {"event_name": "level_complete", "session_id": "s1", "timestamp": "2026-04-10T10:03:00Z", "payload": {}},
                {"event_name": "session_end", "session_id": "s1", "timestamp": "2026-04-10T10:04:00Z", "payload": {"player_id": "p1"}},
                {
                    "event_name": "session_start",
                    "session_id": "s2",
                    "timestamp": "2026-04-11T10:00:00Z",
                    "payload": {"build_id": "web-preview-1", "player_id": "p1"},
                },
                {
                    "event_name": "crash",
                    "session_id": "s2",
                    "timestamp": "2026-04-11T10:01:00Z",
                    "payload": {
                        "error_code": "native_sigsegv",
                        "crash_type": "native",
                        "stack_hash": "stack_native_sigsegv_player_controller",
                        "crash_signature": "player_controller_native_sigsegv",
                    },
                },
                {"event_name": "session_end", "session_id": "s2", "timestamp": "2026-04-11T10:02:00Z", "payload": {"player_id": "p1"}},
            ],
        })

        self.assertTrue(result.success)
        summary = task.context["telemetry_summary"]
        self.assertTrue(summary["privacy_gate_passed"])
        self.assertEqual(summary["pii_violation_count"], 0)
        self.assertEqual(summary["retention_user_count"], 1)
        self.assertEqual(summary["retention_cohorts"][0]["window"], "d1")
        self.assertEqual(summary["retention_cohorts"][0]["retention_rate"], 1.0)
        self.assertEqual(summary["funnel_breakdown"][0]["event_name"], "session_start")
        self.assertEqual(summary["crash_taxonomy"][0]["crash_type"], "native")
        self.assertEqual(summary["crash_clusters"][0]["cluster_id"], "stack_native_sigsegv_player_controller")
        self.assertEqual(summary["crash_clusters"][0]["sample_session_id"], "s2")
        self.assertEqual(summary["crash_regression_dashboard"]["affected_build_count"], 1)
        self.assertEqual(summary["crash_regression_dashboard"]["scene_regressions"][0]["scene_path"], "unknown_scene")
        self.assertEqual(summary["retention_funnel_dashboard"]["largest_dropoff_step"], "level_start")
        self.assertEqual(summary["retention_funnel_dashboard"]["largest_dropoff_count"], 1)
        self.assertEqual(summary["retention_funnel_trend_dashboard"]["day_count"], 2)
        self.assertEqual(summary["retention_funnel_trend_dashboard"]["top_build_id"], "web-preview-1")
        self.assertEqual(summary["liveops_impact_dashboard"]["running_experiment_count"], 1)
        self.assertEqual(summary["liveops_impact_dashboard"]["matched_metric_count"], 2)
        crash_report_artifact = next(
            artifact for artifact in result.artifacts
            if artifact.metadata.get("report_kind") == "crash_clusters"
        )
        crash_dashboard_artifact = next(
            artifact for artifact in result.artifacts
            if artifact.metadata.get("report_kind") == "crash_dashboard"
        )
        retention_dashboard_artifact = next(
            artifact for artifact in result.artifacts
            if artifact.metadata.get("report_kind") == "retention_funnel_dashboard"
        )
        trend_dashboard_artifact = next(
            artifact for artifact in result.artifacts
            if artifact.metadata.get("report_kind") == "retention_funnel_trends"
        )
        liveops_impact_artifact = next(
            artifact for artifact in result.artifacts
            if artifact.metadata.get("report_kind") == "liveops_impact"
        )
        crash_report_payload = json.loads(next(
            artifact.content for artifact in result.artifacts
            if artifact.name == "telemetry_summary.json"
        ))
        self.assertIn("# Crash Cluster Report", crash_report_artifact.content or "")
        self.assertIn("# Crash Regression Dashboard", crash_dashboard_artifact.content or "")
        self.assertIn("# Retention Funnel Dashboard", retention_dashboard_artifact.content or "")
        self.assertIn("# Retention Funnel Trend Dashboard", trend_dashboard_artifact.content or "")
        self.assertIn("# LiveOps Impact Dashboard", liveops_impact_artifact.content or "")
        self.assertEqual(crash_report_payload["crash_clusters"][0]["cluster_id"], "stack_native_sigsegv_player_controller")

    def test_telemetry_apply_blocks_unauthorized_pii_payload(self):
        skill = TelemetryPipelineSkill(MockGodotCLI(project_path=str(self.project_dir)))
        task = Task(prompt="导入含敏感字段的遥测会话回流")
        result = skill.execute(task, {
            "action": "apply",
            "catalog_entries": [
                {
                    "event_name": "session_start",
                    "category": "session",
                    "description": "开始会话",
                    "privacy_level": "anonymous",
                    "fields": [{"name": "build_id", "type": "string", "required": True, "pii": False}],
                }
            ],
            "events": [
                {
                    "event_name": "session_start",
                    "session_id": "s1",
                    "timestamp": "2026-04-10T10:00:00Z",
                    "payload": {"build_id": "web-preview-1", "email": "test@example.com"},
                }
            ],
        })

        self.assertFalse(result.success)
        self.assertEqual(task.context["telemetry_summary"]["pii_violation_count"], 1)
        self.assertFalse(task.context["telemetry_summary"]["privacy_gate_passed"])
        self.assertTrue(any("未授权敏感字段" in issue for issue in task.context["telemetry_summary"]["issues"]))

    @patch("agent_system.router.GodotCLI", MockGodotCLI)
    def test_router_routes_telemetry_prompt_and_records_skill_result(self):
        from agent_system.router import GodotAgentRouter

        router = GodotAgentRouter(godot_project_path=str(self.project_dir), history_file=self.history_file)
        task = router.execute(
            "分析遥测会话回流",
            context={
                "telemetry_catalog_entries": [
                    {
                        "event_name": "session_start",
                        "category": "session",
                        "description": "开始会话",
                        "privacy_level": "anonymous",
                        "fields": [{"name": "build_id", "type": "string", "required": True, "pii": False}],
                    },
                    {
                        "event_name": "session_end",
                        "category": "session",
                        "description": "结束会话",
                        "privacy_level": "anonymous",
                        "fields": [],
                    },
                ],
                "telemetry_events": [
                    {
                        "event_name": "session_start",
                        "session_id": "s1",
                        "timestamp": "2026-04-10T10:00:00Z",
                        "payload": {"build_id": "web-preview-1"},
                    },
                    {
                        "event_name": "session_end",
                        "session_id": "s1",
                        "timestamp": "2026-04-10T10:05:00Z",
                        "payload": {},
                    },
                ],
            },
            confirm=True,
        )

        self.assertEqual(task.status, TaskStatus.SUCCESS)
        self.assertEqual(task.steps[0].role, "resource_manager")
        self.assertEqual(task.context["last_skill_result"]["skill_name"], "manage_game_telemetry")
        self.assertEqual(task.context["last_skill_result"]["validation"]["passed"], True)
        self.assertEqual(task.context["telemetry_summary"]["session_count"], 1)


if __name__ == "__main__":
    unittest.main()

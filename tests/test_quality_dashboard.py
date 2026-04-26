import json
import shutil
import sys
import unittest
from pathlib import Path

from fastapi.testclient import TestClient


project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from agent_system.tools.quality_dashboard import build_quality_dashboard
from api_server.main import app


class QualityDashboardTestCase(unittest.TestCase):
    def setUp(self):
        self.project_dir = project_root / "tests" / ".tmp_quality_project"
        self.runtime_dir = project_root / "tests" / ".tmp_quality_runtime"
        shutil.rmtree(self.project_dir, ignore_errors=True)
        shutil.rmtree(self.runtime_dir, ignore_errors=True)
        self.project_dir.mkdir(parents=True, exist_ok=True)
        self.runtime_dir.mkdir(parents=True, exist_ok=True)

    def tearDown(self):
        shutil.rmtree(self.project_dir, ignore_errors=True)
        shutil.rmtree(self.runtime_dir, ignore_errors=True)

    def test_dashboard_returns_all_p2_sections(self):
        dashboard = build_quality_dashboard(self.project_dir, runtime_root=self.runtime_dir)

        self.assertEqual(dashboard["schema_version"], "1.0")
        self.assertTrue(dashboard["passed"])
        section_names = {section["name"] for section in dashboard["sections"]}
        self.assertEqual(section_names, {
            "contracts",
            "project_layout",
            "templates",
            "skill_coverage",
            "telemetry",
            "performance",
            "migrations",
        })
        self.assertEqual(dashboard["blocked_count"], 0)

    def test_dashboard_blocks_invalid_performance_baseline(self):
        baseline_dir = self.runtime_dir / "tests" / "baselines" / "performance"
        baseline_dir.mkdir(parents=True, exist_ok=True)
        (baseline_dir / "bad.json").write_text(
            json.dumps({"schema_version": "1.0", "metrics": {}}),
            encoding="utf-8",
        )

        dashboard = build_quality_dashboard(self.project_dir, runtime_root=self.runtime_dir)
        performance = next(section for section in dashboard["sections"] if section["name"] == "performance")

        self.assertFalse(dashboard["passed"])
        self.assertEqual(performance["status"], "blocked")
        self.assertGreater(performance["issue_count"], 0)

    def test_dashboard_surfaces_telemetry_retention_and_privacy_metrics(self):
        telemetry_dir = self.project_dir / "telemetry"
        sessions_dir = telemetry_dir / "sessions"
        liveops_dir = self.project_dir / "liveops"
        sessions_dir.mkdir(parents=True, exist_ok=True)
        liveops_dir.mkdir(parents=True, exist_ok=True)
        (telemetry_dir / "event_catalog.json").write_text(
            json.dumps({
                "events": [
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
            }, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        (sessions_dir / "session_001.jsonl").write_text(
            '{"event_name":"session_start","session_id":"s1","timestamp":"2026-04-10T10:00:00Z","payload":{"build_id":"web-preview-1","player_id":"p1"}}\n'
            '{"event_name":"session_end","session_id":"s1","timestamp":"2026-04-10T10:05:00Z","payload":{"player_id":"p1"}}\n'
            '{"event_name":"session_start","session_id":"s2","timestamp":"2026-04-11T10:00:00Z","payload":{"build_id":"web-preview-1","player_id":"p1"}}\n'
            '{"event_name":"session_end","session_id":"s2","timestamp":"2026-04-11T10:05:00Z","payload":{"player_id":"p1"}}\n',
            encoding="utf-8",
        )
        (liveops_dir / "remote_config.json").write_text(
            json.dumps({
                "schema_version": "1.0",
                "liveops_type": "remote_config",
                "items": [{
                    "config_key": "tutorial_skip_hint",
                    "value_type": "bool",
                    "default_value": True,
                    "owner": "design_ops",
                    "enabled": True,
                    "requires_restart": False,
                    "environments": ["qa"],
                    "rollout_strategy": "percentage",
                    "rollout_percentage": 50,
                    "audience_segments": ["new_players"],
                    "tags": ["tutorial"],
                    "acceptance_checks": ["owner_declared"],
                    "notes": "教程提示实验",
                }],
            }, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        (liveops_dir / "experiments.json").write_text(
            json.dumps({
                "schema_version": "1.0",
                "liveops_type": "experiment_catalog",
                "items": [{
                    "experiment_id": "tutorial_short_path",
                    "status": "running",
                    "hypothesis": "缩短教程提升留存",
                    "owner": "product_ops",
                    "audience_segments": ["new_players"],
                    "target_metrics": ["d1_retention", "funnel_completion_rate"],
                    "rollout_percentage": 50,
                    "rollback_rule": "d1_retention 下降 3% 回滚",
                    "variants": [
                        {"variant_id": "control", "weight": 50, "config_overrides": {}},
                        {"variant_id": "short_path", "weight": 50, "config_overrides": {"tutorial_step_count": 3}},
                    ],
                    "acceptance_checks": ["metrics_declared"],
                    "notes": "教程实验",
                }],
            }, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        dashboard = build_quality_dashboard(self.project_dir, runtime_root=self.runtime_dir)
        telemetry = next(section for section in dashboard["sections"] if section["name"] == "telemetry")

        self.assertEqual(telemetry["status"], "passed")
        self.assertEqual(telemetry["metrics"]["pii_violation_count"], 0)
        self.assertTrue(telemetry["metrics"]["privacy_gate_passed"])
        self.assertEqual(telemetry["metrics"]["crash_cluster_count"], 0)
        self.assertEqual(telemetry["metrics"]["retention_user_count"], 1)
        self.assertEqual(telemetry["metrics"]["d1_retention_rate"], 1.0)
        self.assertEqual(telemetry["metrics"]["largest_dropoff_step"], "level_start")
        self.assertEqual(telemetry["metrics"]["lowest_retention_window"], "d1")
        self.assertEqual(telemetry["metrics"]["trend_day_count"], 2)
        self.assertEqual(telemetry["metrics"]["liveops_running_experiment_count"], 1)
        self.assertEqual(telemetry["metrics"]["liveops_matched_metric_count"], 2)

    def test_dashboard_surfaces_crash_regression_metrics(self):
        telemetry_dir = self.project_dir / "telemetry"
        sessions_dir = telemetry_dir / "sessions"
        sessions_dir.mkdir(parents=True, exist_ok=True)
        (telemetry_dir / "event_catalog.json").write_text(
            json.dumps({
                "schema_version": "1.3",
                "events": [
                    {
                        "event_name": "crash",
                        "category": "error",
                        "description": "崩溃",
                        "privacy_level": "restricted",
                        "fields": [{"name": "error_code", "type": "string", "required": True, "pii": False}],
                    },
                ],
            }, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        (sessions_dir / "session_001.jsonl").write_text(
            '{"event_name":"crash","session_id":"s1","timestamp":"2026-04-10T10:00:00Z","build_id":"web-preview-7","payload":{"error_code":"native_sigsegv","crash_type":"native","stack_hash":"stack_native_sigsegv_player_controller","scene_path":"res://scenes/levels/level_07.tscn"}}\n',
            encoding="utf-8",
        )

        dashboard = build_quality_dashboard(self.project_dir, runtime_root=self.runtime_dir)
        telemetry = next(section for section in dashboard["sections"] if section["name"] == "telemetry")

        self.assertEqual(telemetry["metrics"]["crash_cluster_count"], 1)
        self.assertEqual(telemetry["metrics"]["affected_build_count"], 1)
        self.assertEqual(telemetry["metrics"]["affected_scene_count"], 1)
        self.assertEqual(
            telemetry["details"]["summary"]["crash_regression_dashboard"]["top_cluster_id"],
            "stack_native_sigsegv_player_controller",
        )

    def test_quality_dashboard_api_shape(self):
        client = TestClient(app)
        response = client.get("/quality/dashboard", params={"project_path": str(self.project_dir)})

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["schema_version"], "1.0")
        self.assertEqual(payload["project_path"], f"{self.project_dir.resolve().as_posix()}/")
        self.assertTrue(any(section["name"] == "migrations" for section in payload["sections"]))

    def test_dashboard_surfaces_frame_breakdown_and_memory_growth_metrics(self):
        baseline_dir = self.runtime_dir / "tests" / "baselines" / "performance"
        baseline_dir.mkdir(parents=True, exist_ok=True)
        (baseline_dir / "rich_perf.json").write_text(
            json.dumps({
                "schema_version": "1.1",
                "scene_path": "res://scenes/Main.tscn",
                "metrics": {
                    "draw_call_count": 180,
                    "fps": 60,
                    "memory_peak_mb": 128,
                },
                "frame_breakdown": [
                    {"stage": "render", "ms": 7.5, "budget_ms": 8.0},
                    {"stage": "script", "ms": 2.2, "budget_ms": 4.0},
                ],
                "memory_trend": {
                    "sample_count": 4,
                    "min_mb": 112,
                    "max_mb": 128,
                    "avg_mb": 120,
                    "growth_mb": 16,
                    "trend_status": "growing",
                },
            }, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        dashboard = build_quality_dashboard(self.project_dir, runtime_root=self.runtime_dir)
        performance = next(section for section in dashboard["sections"] if section["name"] == "performance")

        self.assertEqual(performance["status"], "passed")
        self.assertEqual(performance["metrics"]["top_frame_stage"], "render")
        self.assertEqual(performance["metrics"]["max_memory_growth_mb"], 16.0)

    def test_migrations_status_api_shape(self):
        client = TestClient(app)
        response = client.get("/migrations/status", params={"project_path": str(self.project_dir)})

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["schema_version"], "1.0")
        self.assertEqual(payload["migration_count"], 4)
        self.assertEqual(payload["project_path"], f"{self.project_dir.resolve().as_posix()}/")


if __name__ == "__main__":
    unittest.main()

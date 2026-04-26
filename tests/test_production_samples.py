import json
import sys
import unittest
from pathlib import Path


project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from agent_system.tools.performance_analysis import GamePerformanceAnalyzer
from agent_system.tools.production_scale import build_production_readiness
from agent_system.tools.quality_dashboard import build_quality_dashboard
from agent_system.tools.telemetry_analysis import (
    TelemetryAnalyzer,
    build_crash_cluster_report,
    build_liveops_impact_report,
    build_retention_funnel_dashboard_report,
    build_retention_funnel_trend_report,
)
from agent_system.tools.template_registry import GenreTemplateRegistry


class ProductionSamplesTestCase(unittest.TestCase):
    def test_project_template_override_is_registered_and_valid(self):
        marketplace = GenreTemplateRegistry(project_path=str(project_root)).build_marketplace_manifest()
        project_templates = [
            item for item in marketplace["items"]
            if item.get("source_scope") == "project"
        ]

        self.assertGreaterEqual(len(project_templates), 1)
        self.assertTrue(marketplace["validation"]["passed"])
        self.assertTrue(any(item["template_id"] == "platformer_production" for item in project_templates))

    def test_repository_telemetry_sample_analyzes_without_issues(self):
        summary = TelemetryAnalyzer(project_root).analyze()

        self.assertTrue(summary["passed"])
        self.assertEqual(summary["catalog_entry_count"], 5)
        self.assertEqual(summary["session_count"], 5)
        self.assertEqual(summary["event_count"], 19)
        self.assertEqual(summary["crash_count"], 1)
        self.assertEqual(summary["funnel_completion_rate"], 0.8)
        self.assertEqual(summary["retention_user_count"], 2)
        self.assertTrue(summary["privacy_gate_passed"])
        self.assertEqual(summary["pii_violation_count"], 0)
        self.assertEqual(summary["retention_cohorts"][0]["window"], "d1")
        self.assertEqual(summary["retention_cohorts"][0]["retention_rate"], 0.5)
        self.assertEqual(summary["retention_cohorts"][1]["window"], "d3")
        self.assertEqual(summary["retention_cohorts"][1]["retention_rate"], 0.5)
        self.assertEqual(summary["retention_cohorts"][2]["window"], "d7")
        self.assertEqual(summary["retention_cohorts"][2]["retention_rate"], 0.5)
        self.assertEqual(summary["retention_funnel_dashboard"]["completion_rate"], 0.8)
        self.assertEqual(summary["retention_funnel_dashboard"]["largest_dropoff_step"], "level_complete")
        self.assertEqual(summary["retention_funnel_dashboard"]["largest_dropoff_count"], 1)
        self.assertEqual(summary["retention_funnel_dashboard"]["lowest_retention_window"], "d1")
        self.assertEqual(summary["crash_taxonomy"][0]["crash_type"], "native")
        self.assertEqual(summary["crash_taxonomy"][0]["count"], 1)
        self.assertEqual(summary["crash_clusters"][0]["cluster_id"], "stack_native_sigsegv_player_controller")
        self.assertEqual(summary["crash_clusters"][0]["sample_session_id"], "sample_vertical_slice_002")
        self.assertEqual(summary["crash_clusters"][0]["builds"], ["web-preview-1"])
        self.assertEqual(summary["crash_regression_dashboard"]["affected_build_count"], 1)
        self.assertEqual(summary["crash_regression_dashboard"]["affected_scene_count"], 1)
        self.assertEqual(summary["crash_regression_dashboard"]["top_cluster_id"], "stack_native_sigsegv_player_controller")
        self.assertEqual(summary["retention_funnel_trend_dashboard"]["day_count"], 4)
        self.assertEqual(summary["retention_funnel_trend_dashboard"]["top_build_id"], "web-preview-1")
        self.assertEqual(summary["liveops_impact_dashboard"]["running_experiment_count"], 1)
        self.assertEqual(summary["liveops_impact_dashboard"]["matched_metric_count"], 2)
        self.assertEqual(summary["issues"], [])
        report = build_crash_cluster_report(summary)
        retention_report = build_retention_funnel_dashboard_report(summary)
        trend_report = build_retention_funnel_trend_report(summary)
        liveops_report = build_liveops_impact_report(summary)
        self.assertIn("# Crash Cluster Report", report)
        self.assertIn("# Retention Funnel Dashboard", retention_report)
        self.assertIn("# Retention Funnel Trend Dashboard", trend_report)
        self.assertIn("# LiveOps Impact Dashboard", liveops_report)
        self.assertIn("stack_native_sigsegv_player_controller", report)

    def test_repository_performance_baseline_includes_richer_budget_metrics(self):
        analyzer = GamePerformanceAnalyzer(project_root, runtime_root=project_root)
        baseline_path = project_root / "tests" / "baselines" / "performance" / "vertical_slice_sample_performance.json"
        baseline_payload = json.loads(baseline_path.read_text(encoding="utf-8"))
        summary = analyzer.analyze(
            scene_path="res://scenes/Main.tscn",
            baseline_path="tests/baselines/performance/vertical_slice_sample_performance.json",
            baseline_metrics=baseline_payload["metrics"],
            profile_metrics={
                **baseline_payload["metrics"],
                "frame_breakdown": baseline_payload.get("frame_breakdown", []),
                "memory_trend": baseline_payload.get("memory_trend", {}),
            },
            budget_overrides=baseline_payload["budgets"],
        )

        self.assertTrue(summary["passed"])
        self.assertEqual(summary["metrics"]["fps"], 60)
        self.assertEqual(summary["metrics"]["memory_peak_mb"], 128)
        self.assertEqual(summary["metrics"]["screenshot_diff_ratio"], 0.012)
        self.assertEqual(summary["budgets"]["max_screenshot_diff_ratio"], 0.035)
        self.assertEqual(summary["metrics"]["top_frame_stage"], "render")
        self.assertEqual(summary["memory_trend"]["growth_mb"], 12.0)

    def test_quality_dashboard_and_p5_strict_have_no_sample_blockers(self):
        dashboard = build_quality_dashboard(project_root, runtime_root=project_root)
        readiness = build_production_readiness(
            project_root,
            runtime_root=project_root,
            scenario_id="vertical_slice_2d",
            evidence={"contract": True, "tests": True, "docs": True, "quality_dashboard": True},
            changed_paths=["scenes/Main.tscn", "scripts/player_controller.gd", "README.md"],
            mode="strict",
        )

        self.assertTrue(dashboard["passed"])
        self.assertEqual(dashboard["status"], "passed")
        self.assertTrue(readiness["passed"])
        self.assertEqual(readiness["readiness_status"], "passed")
        self.assertEqual(readiness["blocking_checks"], [])


if __name__ == "__main__":
    unittest.main()

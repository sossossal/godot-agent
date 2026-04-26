import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from agent_system.models import Task, TaskStatus, ToolResult
from agent_system.skills.resource.performance_skill import PerformancePipelineSkill


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


class PerformancePipelineTestCase(unittest.TestCase):
    def setUp(self):
        self.project_dir = project_root / "tests" / ".tmp_performance_pipeline"
        shutil.rmtree(self.project_dir, ignore_errors=True)
        self.project_dir.mkdir(parents=True, exist_ok=True)
        self.history_file = tempfile.mktemp(suffix=".json")
        self.cleanup_paths = []

    def tearDown(self):
        shutil.rmtree(self.project_dir, ignore_errors=True)
        for target in self.cleanup_paths:
            if target:
                Path(target).unlink(missing_ok=True)
        if os.path.exists(self.history_file):
            os.remove(self.history_file)

    def test_performance_baseline_writes_runtime_baseline_file(self):
        skill = PerformancePipelineSkill(MockGodotCLI(project_path=str(self.project_dir)))
        task = Task(prompt="保存性能基线")
        baseline_path = "tests/baselines/performance/perf_pipeline_test_baseline.json"
        result = skill.execute(task, {
            "action": "baseline",
            "scene_path": "res://scenes/main_scene.tscn",
            "baseline_path": baseline_path,
            "profile_metrics": {
                "scene_load_ms": 420,
                "fps": 60,
                "memory_peak_mb": 128,
                "draw_call_count": 280,
                "node_count": 180,
                "texture_memory_mb": 96,
                "frame_spike_ms": 11,
            },
            "budget_overrides": {
                "max_scene_load_ms": 900,
                "min_fps": 55,
                "max_draw_call_count": 400,
            },
        })

        resolved_baseline_path = project_root / baseline_path
        self.cleanup_paths.extend([
            str(resolved_baseline_path),
            task.context.get("performance_report_path", ""),
        ])

        self.assertTrue(result.success)
        self.assertTrue(resolved_baseline_path.exists())
        self.assertEqual(task.context["contract_versions"]["performance_summary"], "1.1")
        self.assertEqual(task.context["performance_summary"]["schema_version"], "1.1")
        self.assertEqual(task.context["performance_summary"]["metrics"]["draw_call_count"], 280)
        self.assertEqual(result.metadata["skill_result"]["skill_name"], "manage_game_performance")

    def test_performance_analyze_flags_budget_overflow_and_regression(self):
        skill = PerformancePipelineSkill(MockGodotCLI(project_path=str(self.project_dir)))
        baseline_path = "tests/baselines/performance/perf_pipeline_regression_baseline.json"
        resolved_baseline_path = project_root / baseline_path
        resolved_baseline_path.parent.mkdir(parents=True, exist_ok=True)
        resolved_baseline_path.write_text(
            '{\n'
            '  "schema_version": "1.0",\n'
            '  "scene_path": "res://scenes/main_scene.tscn",\n'
            '  "metrics": {\n'
            '    "scene_load_ms": 320,\n'
            '    "fps": 60,\n'
            '    "memory_peak_mb": 120,\n'
            '    "draw_call_count": 220,\n'
            '    "node_count": 160,\n'
            '    "texture_memory_mb": 80,\n'
            '    "frame_spike_ms": 10\n'
            '  }\n'
            '}\n',
            encoding="utf-8",
        )
        self.cleanup_paths.append(str(resolved_baseline_path))

        task = Task(prompt="分析性能画像")
        result = skill.execute(task, {
            "action": "analyze",
            "scene_path": "res://scenes/main_scene.tscn",
            "baseline_path": baseline_path,
            "profile_metrics": {
                "scene_load_ms": 480,
                "fps": 48,
                "memory_peak_mb": 160,
                "draw_call_count": 520,
                "node_count": 340,
                "texture_memory_mb": 140,
                "frame_spike_ms": 26,
                "frame_breakdown": [
                    {"stage": "render", "ms": 9.5},
                    {"stage": "script", "ms": 5.0},
                ],
                "memory_samples_mb": [118, 126, 142, 160],
            },
            "budget_overrides": {
                "max_scene_load_ms": 1000,
                "min_fps": 55,
                "max_memory_peak_mb": 200,
                "max_draw_call_count": 400,
                "max_node_count": 260,
                "max_texture_memory_mb": 110,
                "max_frame_spike_ms": 18,
            },
        })

        self.cleanup_paths.extend([
            task.context.get("performance_report_path", ""),
            task.context.get("performance_profile_path", ""),
        ])

        self.assertFalse(result.success)
        self.assertEqual(task.context["contract_versions"]["performance_summary"], "1.1")
        self.assertTrue(any("Draw Call" in issue for issue in task.context["performance_summary"]["issues"]))
        self.assertTrue(any(
            check["name"] == "draw_call_budget" and check["status"] == "blocked"
            for check in task.context["performance_summary"]["checks"]
        ))
        self.assertTrue(any(
            check["name"] == "draw_call_regression" and check["status"] == "blocked"
            for check in task.context["performance_summary"]["checks"]
        ))
        self.assertEqual(task.context["performance_summary"]["metrics"]["top_frame_stage"], "render")
        self.assertEqual(task.context["performance_summary"]["memory_trend"]["growth_mb"], 42.0)
        self.assertTrue(Path(task.context["performance_profile_path"]).exists())

    def test_inline_performance_analyze_ignores_disk_baseline_without_explicit_path(self):
        skill = PerformancePipelineSkill(MockGodotCLI(project_path=str(self.project_dir)))
        inline_baseline_path = project_root / "tests" / "baselines" / "performance" / "_inline_profile_performance.json"
        inline_baseline_path.parent.mkdir(parents=True, exist_ok=True)
        inline_baseline_path.write_text(
            '{\n'
            '  "schema_version": "1.0",\n'
            '  "metrics": {\n'
            '    "fps": 60,\n'
            '    "memory_peak_mb": 210,\n'
            '    "draw_call_count": 240,\n'
            '    "node_count": 180,\n'
            '    "frame_spike_ms": 12\n'
            '  },\n'
            '  "budgets": {\n'
            '    "max_memory_peak_mb": 260,\n'
            '    "max_frame_spike_ms": 20\n'
            '  }\n'
            '}\n',
            encoding="utf-8",
        )
        self.cleanup_paths.append(str(inline_baseline_path))

        task = Task(prompt="分析性能画像")
        result = skill.execute(task, {
            "action": "analyze",
            "profile_metrics": {
                "draw_call_count": 280,
                "node_count": 180,
                "fps": 60,
            },
            "budget_overrides": {
                "max_draw_call_count": 320,
                "max_node_count": 220,
                "min_fps": 55,
            },
        })

        self.cleanup_paths.extend([
            task.context.get("performance_report_path", ""),
            task.context.get("performance_profile_path", ""),
        ])

        self.assertTrue(result.success)
        self.assertEqual(task.context["performance_summary"]["issues"], [])
        self.assertNotIn("baseline_memory_peak_mb", task.context["performance_summary"]["metrics"])

    def test_performance_analyze_normalizes_frame_breakdown_and_memory_trend(self):
        skill = PerformancePipelineSkill(MockGodotCLI(project_path=str(self.project_dir)))
        task = Task(prompt="分析性能画像")

        result = skill.execute(task, {
            "action": "analyze",
            "scene_path": "res://scenes/main_scene.tscn",
            "profile_metrics": {
                "draw_call_count": 260,
                "node_count": 190,
                "fps": 59,
                "memory_peak_mb": 144,
                "cpu_ms": 4.2,
                "render_ms": 7.1,
                "memory_samples_mb": [132, 136, 140, 144],
            },
            "budget_overrides": {
                "max_draw_call_count": 320,
                "max_node_count": 220,
                "min_fps": 55,
                "max_memory_peak_mb": 180,
            },
        })

        self.cleanup_paths.extend([
            task.context.get("performance_report_path", ""),
            task.context.get("performance_profile_path", ""),
        ])

        self.assertTrue(result.success)
        self.assertEqual(task.context["performance_summary"]["metrics"]["top_frame_stage"], "render")
        self.assertEqual(task.context["performance_summary"]["metrics"]["memory_growth_mb"], 12.0)
        self.assertEqual(task.context["performance_summary"]["memory_trend"]["trend_status"], "growing")
        self.assertEqual(task.context["performance_summary"]["frame_breakdown"][0]["stage"], "cpu")

    @patch("agent_system.router.GodotCLI", MockGodotCLI)
    def test_router_routes_performance_prompt_and_records_skill_result(self):
        from agent_system.router import GodotAgentRouter

        router = GodotAgentRouter(godot_project_path=str(self.project_dir), history_file=self.history_file)
        task = router.execute(
            "分析性能画像",
            context={
                "performance_profile_metrics": {
                    "draw_call_count": 280,
                    "node_count": 180,
                    "fps": 60,
                },
                "performance_budget": {
                    "max_draw_call_count": 320,
                    "max_node_count": 220,
                    "min_fps": 55,
                },
            },
            confirm=True,
        )

        self.cleanup_paths.extend([
            task.context.get("performance_report_path", ""),
            task.context.get("performance_profile_path", ""),
        ])

        self.assertEqual(task.status, TaskStatus.SUCCESS)
        self.assertEqual(task.steps[0].role, "resource_manager")
        self.assertEqual(task.context["last_skill_result"]["skill_name"], "manage_game_performance")
        self.assertEqual(task.context["last_skill_result"]["validation"]["passed"], True)
        self.assertEqual(task.context["performance_summary"]["metrics"]["draw_call_count"], 280)


if __name__ == "__main__":
    unittest.main()

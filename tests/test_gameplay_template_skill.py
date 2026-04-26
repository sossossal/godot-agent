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
from agent_system.skills.architect.gameplay_template_skill import GameplayTemplateSkill
from agent_system.tools.blueprint_manager import BlueprintManager


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


class GameplayTemplateSkillTestCase(unittest.TestCase):
    def setUp(self):
        self.project_dir = project_root / "tests" / ".tmp_gameplay_template_skill"
        shutil.rmtree(self.project_dir, ignore_errors=True)
        self.project_dir.mkdir(parents=True, exist_ok=True)
        self.history_file = tempfile.mktemp(suffix=".json")

    def tearDown(self):
        shutil.rmtree(self.project_dir, ignore_errors=True)
        if os.path.exists(self.history_file):
            os.remove(self.history_file)

    def test_preview_returns_filtered_snapshot_and_report(self):
        skill = GameplayTemplateSkill(MockGodotCLI(project_path=str(self.project_dir)))
        task = Task(prompt="预览 platformer 玩法模板")
        result = skill.execute(task, {
            "action": "preview",
            "template_id": "platformer",
            "include_system_ids": ["player_controller", "camera_follow"],
            "notes": "P9 preview smoke",
        })

        self.assertTrue(result.success)
        self.assertEqual(result.metadata["skill_result"]["skill_name"], "manage_gameplay_template")
        self.assertTrue(result.metadata["skill_result"]["validation"]["passed"])
        self.assertEqual(task.context["gameplay_template_id"], "platformer")
        self.assertEqual(task.context["gameplay_system_count"], 2)
        snapshot = result.data["gameplay_template"]
        self.assertEqual(snapshot["schema_version"], "1.0")
        self.assertEqual(snapshot["template_id"], "platformer")
        self.assertEqual(snapshot["system_count"], 2)
        self.assertEqual(
            [system["system_id"] for system in snapshot["starter_gameplay_systems"]],
            ["player_controller", "camera_follow"],
        )
        report_artifact = next(artifact for artifact in result.artifacts if artifact.type == "report")
        self.assertTrue(Path(report_artifact.path).exists())

    def test_apply_seeds_blueprint_features_and_project_template(self):
        skill = GameplayTemplateSkill(MockGodotCLI(project_path=str(self.project_dir)))
        blueprint_manager = BlueprintManager(str(self.project_dir))
        task = Task(
            prompt="应用 visual_novel 玩法模板",
            context={"blueprint_manager": blueprint_manager},
        )
        result = skill.execute(task, {
            "action": "apply",
            "template_id": "visual_novel",
        })

        self.assertTrue(result.success)
        self.assertTrue(task.context["gameplay_template_applied"])
        self.assertEqual(task.context["gameplay_template_id"], "visual_novel")
        self.assertGreaterEqual(len(task.context["gameplay_seeded_features"]), 1)
        self.assertEqual(blueprint_manager.blueprint.project_template["template_id"], "visual_novel")
        self.assertEqual(blueprint_manager.blueprint.gameplay_template_id, "visual_novel")
        self.assertGreaterEqual(len(blueprint_manager.blueprint.starter_gameplay_systems), 6)
        self.assertTrue(all(
            feature_name in blueprint_manager.blueprint.features
            for feature_name in result.data["seeded_feature_names"]
        ))
        self.assertTrue(all(
            blueprint_manager.blueprint.features[feature_name].status == "planned"
            for feature_name in result.data["seeded_feature_names"]
        ))

    @patch("agent_system.router.GodotCLI", MockGodotCLI)
    def test_router_routes_gameplay_template_prompt_and_records_skill_result(self):
        from agent_system.router import GodotAgentRouter

        router = GodotAgentRouter(godot_project_path=str(self.project_dir), history_file=self.history_file)
        task = router.execute("应用 roguelike 玩法模板并初始化核心系统", confirm=True)

        self.assertEqual(task.status, TaskStatus.SUCCESS)
        self.assertEqual(task.steps[0].role, "architect")
        self.assertEqual(task.context["last_skill_result"]["skill_name"], "manage_gameplay_template")
        self.assertEqual(task.context["gameplay_template_id"], "roguelike")
        self.assertTrue(task.context["gameplay_template_applied"])
        self.assertGreaterEqual(task.context["gameplay_system_count"], 6)
        self.assertGreaterEqual(len(router.blueprint_manager.blueprint.features), 6)


if __name__ == "__main__":
    unittest.main()

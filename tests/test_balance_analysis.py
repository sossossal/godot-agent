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
from agent_system.skills.resource.balance_analysis_skill import BalanceAnalysisSkill


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


class BalanceAnalysisTestCase(unittest.TestCase):
    def setUp(self):
        self.project_dir = project_root / "tests" / ".tmp_balance_analysis"
        shutil.rmtree(self.project_dir, ignore_errors=True)
        self.project_dir.mkdir(parents=True, exist_ok=True)
        self.history_file = tempfile.mktemp(suffix=".json")

    def tearDown(self):
        shutil.rmtree(self.project_dir, ignore_errors=True)
        if os.path.exists(self.history_file):
            os.remove(self.history_file)

    def test_balance_analysis_skill_flags_missing_loot_links_and_probability_overflow(self):
        skill = BalanceAnalysisSkill(MockGodotCLI(project_path=str(self.project_dir)))
        task = Task(prompt="分析敌人和掉落数值平衡")
        result = skill.execute(task, {
            "enemy_rows": [
                {"enemy_id": "slime_elite", "name": "Elite Slime", "hp": "18", "attack": "12", "move_speed": "110", "loot_table_id": "loot_missing"},
            ],
            "loot_rows": [
                {"loot_id": "loot_common", "item_id": "coin", "drop_rate": "0.8", "quantity": "2"},
                {"loot_id": "loot_common", "item_id": "gem", "drop_rate": "0.5", "quantity": "1"},
            ],
            "quest_rows": [
                {"quest_id": "quest_intro", "title": "清理史莱姆", "description": "消灭 2 只史莱姆", "target_count": "2", "reward_gold": "60", "next_quest_id": ""},
            ],
        })

        self.assertFalse(result.success)
        self.assertEqual(task.context["balance_analysis"]["schema_version"], "1.0")
        self.assertEqual(task.context["contract_versions"]["balance_analysis"], "1.0")
        self.assertEqual(result.metadata["skill_result"]["skill_name"], "analyze_game_balance")
        self.assertEqual(result.metadata["skill_result"]["validation"]["passed"], False)
        self.assertTrue(any("不存在的掉落表" in issue for issue in task.context["balance_analysis"]["issues"]))
        self.assertTrue(any("总概率超过 1.0" in issue for issue in task.context["balance_analysis"]["issues"]))
        self.assertTrue(any(artifact.type == "report" for artifact in result.artifacts))

    @patch("agent_system.router.GodotCLI", MockGodotCLI)
    def test_router_routes_balance_prompt_and_records_skill_result(self):
        from agent_system.router import GodotAgentRouter

        router = GodotAgentRouter(godot_project_path=str(self.project_dir), history_file=self.history_file)
        task = router.execute(
            "做一次敌人强度和掉落分析",
            context={
                "balance_enemy_rows": [
                    {"enemy_id": "slime_basic", "name": "Slime", "hp": "30", "attack": "5", "move_speed": "100", "loot_table_id": "loot_slime"},
                ],
                "balance_loot_rows": [
                    {"loot_id": "loot_slime", "item_id": "coin", "drop_rate": "0.5", "quantity": "2"},
                ],
                "balance_quest_rows": [
                    {"quest_id": "quest_slime", "title": "清理史莱姆", "description": "消灭 3 只史莱姆", "target_count": "3", "reward_gold": "90", "next_quest_id": ""},
                ],
            },
            confirm=True,
        )

        self.assertEqual(task.status, TaskStatus.SUCCESS)
        self.assertEqual(task.steps[0].role, "resource_manager")
        self.assertEqual(task.context["last_skill_result"]["skill_name"], "analyze_game_balance")
        self.assertEqual(task.context["last_skill_result"]["validation"]["passed"], True)
        self.assertGreater(task.context["balance_analysis_score"], 0)


if __name__ == "__main__":
    unittest.main()

"""
数据表驱动内容管线回归测试
"""

import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from agent_system.models import ToolResult, TaskStatus


class MockGodotCLI:
    def __init__(self, executable_path=None, project_path=None):
        self.executable = "godot"
        self.project_path = project_path

    def is_available(self): return True
    def run_headless(self, script_path, args=None): return ToolResult(True, "OK")
    def run_scene(self, scene_path): return ToolResult(True, "OK")
    def execute_editor_script(self, script_content): return ToolResult(True, "OK")
    def export_project(self, preset_name, output_path, release=True): return ToolResult(True, "OK")
    def get_version(self): return "4.2.0"


class TestDataTablePipeline(unittest.TestCase):
    @patch('agent_system.router.GodotCLI', MockGodotCLI)
    def setUp(self):
        from agent_system.router import GodotAgentRouter
        self.history_file = tempfile.mktemp(suffix=".json")
        self.project_dir = project_root / "tests" / ".tmp_data_pipeline"
        shutil.rmtree(self.project_dir, ignore_errors=True)
        self.project_dir.mkdir(parents=True, exist_ok=True)
        self.router = GodotAgentRouter(godot_project_path=str(self.project_dir), history_file=self.history_file)

    def tearDown(self):
        shutil.rmtree(self.project_dir, ignore_errors=True)
        if os.path.exists(self.history_file):
            os.remove(self.history_file)

    def test_data_table_template_generation_creates_dialogue_csv(self):
        task = self.router.execute("新建对白数据表模板", confirm=True)

        table_path = self.project_dir / "data_tables" / "dialogue.csv"
        self.assertEqual(task.status, TaskStatus.SUCCESS)
        self.assertEqual(task.steps[0].role, "resource_manager")
        self.assertTrue(table_path.exists())
        self.assertIn("dialogue_id,speaker,text,emotion,next_id", table_path.read_text(encoding="utf-8"))
        self.assertEqual(task.context.get("data_table_type"), "dialogue")
        self.assertEqual(task.context.get("data_table_action"), "template")
        self.assertEqual(task.context["contract_versions"]["skill_result"], "1.0")
        self.assertEqual(task.context["last_skill_result"]["skill_name"], "manage_game_data_tables")
        self.assertTrue(any(artifact.metadata.get("skill_name") == "manage_game_data_tables" for artifact in task.artifacts))

    def test_data_table_apply_writes_quest_rows(self):
        task = self.router.execute(
            "导入任务数据表",
            context={
                "data_table_action": "apply",
                "data_table_rows": [
                    {
                        "quest_id": "quest_collect",
                        "title": "收集蘑菇",
                        "description": "收集 3 个蘑菇",
                        "target_count": "3",
                        "reward_gold": "50",
                        "next_quest_id": "",
                    }
                ],
            },
            confirm=True,
        )

        table_path = self.project_dir / "data_tables" / "quests.csv"
        self.assertEqual(task.status, TaskStatus.SUCCESS)
        self.assertTrue(table_path.exists())
        self.assertIn("quest_collect", table_path.read_text(encoding="utf-8"))
        self.assertEqual(task.context.get("data_table_issue_count"), 0)
        self.assertTrue(any(artifact.name == "quests.csv" for artifact in task.artifacts))
        self.assertEqual(task.context["last_skill_result"]["validation"]["passed"], True)
        self.assertEqual(task.context["skill_runs"][-1]["skill_name"], "manage_game_data_tables")

    def test_data_table_validation_blocks_invalid_loot_rows(self):
        task = self.router.execute(
            "校验掉落数据表",
            context={
                "data_table_rows": [
                    {"loot_id": "loot_dup", "item_id": "coin", "drop_rate": "1.2", "quantity": "0"},
                    {"loot_id": "loot_dup", "item_id": "gem", "drop_rate": "0.4", "quantity": "1"},
                ],
            },
            confirm=True,
        )

        self.assertEqual(task.status, TaskStatus.FAILED)
        self.assertEqual(task.context.get("data_table_type"), "loot")
        self.assertGreaterEqual(task.context.get("data_table_issue_count", 0), 2)
        self.assertTrue(any("drop_rate" in log or "重复" in log for log in task.logs))

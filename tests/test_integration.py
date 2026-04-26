"""
Godot Agent 集成测试 (Task API 适配版)
"""

import unittest
import sys
from pathlib import Path
from unittest.mock import patch

# 添加项目路径
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from agent_system.router import GodotAgentRouter
from agent_system.models import Task, TaskStatus, ToolResult

class MockGodotCLI:
    def __init__(self, executable_path=None, project_path=None):
        self.executable = "godot"
        self.project_path = project_path
    def is_available(self): return True
    def run_headless(self, script_path, args=None): return ToolResult(True, "OK")
    def run_scene(self, scene_path): return ToolResult(True, "OK")
    def execute_editor_script(self, script_content): return ToolResult(True, "OK")
    def export_project(self, preset_name, output_path, release=True):
        output_file = Path(output_path)
        output_file.parent.mkdir(parents=True, exist_ok=True)
        if output_file.suffix.lower() == ".html":
            output_file.write_text("<html><body>mock export</body></html>", encoding="utf-8")
        else:
            output_file.write_bytes(b"mock-binary")
        return ToolResult(True, "OK")
    def get_version(self): return "4.2.0"

class TestIntegration(unittest.TestCase):
    @patch('agent_system.router.GodotCLI', MockGodotCLI)
    def setUp(self):
        self.router = GodotAgentRouter()

    def test_multi_step_workflow(self):
        # 这是一个多步骤任务
        task = self.router.execute("创建一个场景并生成脚本", confirm=True)
        self.assertEqual(task.status, TaskStatus.SUCCESS)
        self.assertTrue(len(task.steps) >= 2)

    def test_create_generate_and_test_workflow(self):
        task = self.router.execute("创建一个场景并生成脚本并运行测试", confirm=True)
        self.assertEqual(task.status, TaskStatus.SUCCESS)
        self.assertEqual([step.role for step in task.steps], ["developer", "code_generator", "tester"])

if __name__ == "__main__":
    unittest.main()

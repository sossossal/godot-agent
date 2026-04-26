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
from agent_system.skills.resource.liveops_skill import LiveOpsPipelineSkill


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


class LiveOpsPipelineSkillTestCase(unittest.TestCase):
    def setUp(self):
        self.project_dir = project_root / "tests" / ".tmp_liveops_pipeline_skill"
        shutil.rmtree(self.project_dir, ignore_errors=True)
        self.project_dir.mkdir(parents=True, exist_ok=True)
        (self.project_dir / "project.godot").write_text(
            '[application]\nconfig/name="LiveOps Pipeline Sandbox"\n',
            encoding="utf-8",
        )
        self.history_file = tempfile.mktemp(suffix=".json")

    def tearDown(self):
        shutil.rmtree(self.project_dir, ignore_errors=True)
        if os.path.exists(self.history_file):
            os.remove(self.history_file)

    def test_template_remote_config_writes_manifest_and_context(self):
        skill = LiveOpsPipelineSkill(MockGodotCLI(project_path=str(self.project_dir)))
        task = Task(prompt="新建 Remote Config 模板 combat_spawn_multiplier")
        result = skill.execute(task, {
            "action": "template",
            "liveops_type": "remote_config",
            "entry_id": "combat_spawn_multiplier",
        })

        manifest_path = self.project_dir / "liveops" / "remote_config.json"
        self.assertTrue(result.success)
        self.assertTrue(manifest_path.exists())
        self.assertEqual(result.metadata["skill_result"]["skill_name"], "manage_liveops_pipeline")
        self.assertTrue(result.metadata["skill_result"]["validation"]["passed"])
        self.assertEqual(task.context["contract_versions"]["liveops_profile"], "1.0")
        self.assertEqual(task.context["liveops_type"], "remote_config")
        self.assertEqual(task.context["liveops_profile"]["entry_count"], 1)
        self.assertEqual(task.context["liveops_profile"]["entries"][0]["config_key"], "combat_spawn_multiplier")
        self.assertTrue(task.context["liveops_written"])

    def test_preview_experiment_catalog_reports_invalid_variant_weights(self):
        skill = LiveOpsPipelineSkill(MockGodotCLI(project_path=str(self.project_dir)))
        task = Task(prompt="预览 Experiment Catalog invalid_variant_weights")
        result = skill.execute(task, {
            "action": "preview",
            "liveops_type": "experiment_catalog",
            "entries": [{
                "experiment_id": "tutorial_branch_test",
                "status": "running",
                "hypothesis": "更短教程会提升完成率",
                "owner": "product_ops",
                "target_metrics": ["tutorial_completion_rate"],
                "rollout_percentage": 20,
                "rollback_rule": "tutorial_completion_rate 下降回滚",
                "variants": [
                    {"variant_id": "control", "weight": 60},
                    {"variant_id": "short_path", "weight": 30},
                ],
            }],
        })

        self.assertFalse(result.success)
        self.assertEqual(result.metadata["skill_result"]["skill_name"], "manage_liveops_pipeline")
        self.assertFalse(result.metadata["skill_result"]["validation"]["passed"])
        self.assertEqual(result.data["liveops_profile"]["liveops_type"], "experiment_catalog")
        self.assertTrue(any("weight 总和必须为 100" in issue for issue in result.data["liveops_profile"]["issues"]))

    @patch("agent_system.router.GodotCLI", MockGodotCLI)
    def test_router_routes_liveops_prompt_and_records_skill_result(self):
        from agent_system.router import GodotAgentRouter

        router = GodotAgentRouter(godot_project_path=str(self.project_dir), history_file=self.history_file)
        task = router.execute("新建 remote config 模板", confirm=True)

        self.assertEqual(task.status, TaskStatus.SUCCESS)
        self.assertEqual(task.context["last_skill_result"]["skill_name"], "manage_liveops_pipeline")
        self.assertEqual(task.context["liveops_type"], "remote_config")
        self.assertTrue((self.project_dir / "liveops" / "remote_config.json").exists())


if __name__ == "__main__":
    unittest.main()

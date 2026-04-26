import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from agent_system.models import Task, TaskStatus
from agent_system.skills.resource.platform_delivery_skill import PlatformDeliverySkill


class MockGodotCLI:
    def __init__(self, executable_path=None, project_path=None):
        self.executable = "godot"
        self.project_path = project_path

    def is_available(self):
        return True

    def run_headless(self, script_path, args=None):
        return None

    def run_scene(self, scene_path):
        return None

    def execute_editor_script(self, script_content):
        return None

    def export_project(self, preset_name, output_path, release=True):
        return None

    def get_version(self):
        return "4.2.0"


class PlatformDeliverySkillTestCase(unittest.TestCase):
    def setUp(self):
        self.project_dir = project_root / "tests" / ".tmp_platform_delivery_skill"
        shutil.rmtree(self.project_dir, ignore_errors=True)
        self.project_dir.mkdir(parents=True, exist_ok=True)
        self.history_file = tempfile.mktemp(suffix=".json")

    def tearDown(self):
        shutil.rmtree(self.project_dir, ignore_errors=True)
        if os.path.exists(self.history_file):
            os.remove(self.history_file)

    def test_platform_delivery_template_writes_manifest(self):
        skill = PlatformDeliverySkill(MockGodotCLI(project_path=str(self.project_dir)))
        task = Task(prompt="生成平台交付模板")

        result = skill.execute(task, {"action": "template"})

        manifest_path = self.project_dir / "deployment" / "platform_delivery.json"
        self.assertTrue(result.success)
        self.assertTrue(manifest_path.exists())
        self.assertEqual(task.context["contract_versions"]["platform_delivery_profile"], "1.0")
        self.assertEqual(task.context["platform_delivery_profile"]["platform_count"], 2)
        self.assertIn("profile_save", manifest_path.read_text(encoding="utf-8"))

    def test_platform_delivery_validate_blocks_invalid_multiplayer_and_cloud_save(self):
        skill = PlatformDeliverySkill(MockGodotCLI(project_path=str(self.project_dir)))
        task = Task(prompt="校验平台交付 baseline")

        result = skill.execute(task, {
            "action": "validate",
            "platforms": [{
                "platform_id": "web",
                "store": "web",
                "preset_name": "Web",
                "output_path": "builds/web/index.html",
            }],
            "savegame": {
                "schema_id": "profile_save",
                "version": "1.0.0",
                "save_mode": "offline",
                "slot_count": 1,
                "fields": [{"name": "player_level", "type": "int", "required": True, "default": 1}],
            },
            "services": {
                "cloud_save": True,
                "analytics": True,
            },
            "multiplayer": {
                "enabled": True,
                "mode": "coop",
                "transport": "offline",
                "max_players": 1,
                "rollback_supported": False,
            },
        })

        self.assertFalse(result.success)
        self.assertIn("启用 cloud_save", result.message + " " + (result.error or ""))
        self.assertTrue(any("transport 不能为 offline" in issue for issue in result.metadata["skill_result"]["validation"]["issues"]))

    @patch("agent_system.router.GodotCLI", MockGodotCLI)
    def test_router_routes_platform_delivery_prompt(self):
        from agent_system.router import GodotAgentRouter

        router = GodotAgentRouter(godot_project_path=str(self.project_dir), history_file=self.history_file)
        task = router.execute(
            "生成平台交付 baseline 模板和存档 schema",
            context={"platform_delivery_action": "template"},
            confirm=True,
        )

        self.assertEqual(task.status, TaskStatus.SUCCESS)
        self.assertEqual(task.steps[0].role, "resource_manager")
        self.assertEqual(task.context["last_skill_result"]["skill_name"], "manage_platform_delivery")
        self.assertEqual(task.context["platform_delivery_profile"]["platform_count"], 2)


if __name__ == "__main__":
    unittest.main()

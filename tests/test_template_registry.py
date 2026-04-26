import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient


project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from api_server.main import app
from agent_system.router import GodotAgentRouter
from agent_system.tools.template_registry import DEFAULT_GENRE_TEMPLATE_ID, GenreTemplateRegistry


class MockGodotCLI:
    def __init__(self, executable_path=None, project_path=None):
        self.executable = "godot"
        self.project_path = project_path

    def is_available(self): return True
    def run_headless(self, script_path, args=None): return None
    def run_scene(self, scene_path): return None
    def execute_editor_script(self, script_content): return None
    def export_project(self, preset_name, output_path, release=True): return None
    def get_version(self): return "4.2.0"


class TemplateRegistryTestCase(unittest.TestCase):
    def setUp(self):
        self.project_dir = project_root / "tests" / ".tmp_template_registry"
        shutil.rmtree(self.project_dir, ignore_errors=True)
        self.project_dir.mkdir(parents=True, exist_ok=True)
        self.history_file = tempfile.mktemp(suffix=".json")

    def tearDown(self):
        shutil.rmtree(self.project_dir, ignore_errors=True)
        history_path = Path(self.history_file)
        if history_path.exists():
            history_path.unlink()

    def test_registry_lists_builtin_templates(self):
        registry = GenreTemplateRegistry(project_path=str(self.project_dir))
        items = registry.list_genre_templates()

        self.assertGreaterEqual(len(items), 7)
        self.assertEqual(items[0]["schema_version"], "1.0")
        self.assertTrue(any(item["template_id"] == DEFAULT_GENRE_TEMPLATE_ID for item in items))
        self.assertTrue(all(item["source_scope"] in {"builtin", "project"} for item in items))
        self.assertTrue(all(isinstance(item.get("starter_gameplay_systems"), list) for item in items))

    def test_gameplay_template_snapshot_filters_systems(self):
        registry = GenreTemplateRegistry(project_path=str(self.project_dir))
        snapshot = registry.build_gameplay_template_snapshot(
            "survival_crafting",
            include_system_ids=["inventory_core", "crafting_recipes"],
        )

        self.assertIsNotNone(snapshot)
        self.assertEqual(snapshot["schema_version"], "1.0")
        self.assertEqual(snapshot["template_id"], "survival_crafting")
        self.assertEqual(snapshot["system_count"], 2)
        self.assertEqual(
            [system["system_id"] for system in snapshot["starter_gameplay_systems"]],
            ["inventory_core", "crafting_recipes"],
        )
        self.assertGreaterEqual(snapshot["acceptance_check_count"], 2)

    def test_marketplace_manifest_reports_template_validation(self):
        registry = GenreTemplateRegistry(project_path=str(self.project_dir))
        manifest = registry.build_marketplace_manifest()

        self.assertEqual(manifest["schema_version"], "1.0")
        self.assertTrue(manifest["validation"]["passed"])
        self.assertGreaterEqual(manifest["count"], 7)
        platformer = next(item for item in manifest["items"] if item["template_id"] == "platformer")
        self.assertEqual(platformer["validation"]["issue_count"], 0)
        self.assertEqual(platformer["install_state"], "installed")

    @patch("agent_system.router.GodotCLI", MockGodotCLI)
    def test_init_blueprint_uses_template_registry_and_creates_directories(self):
        router = GodotAgentRouter(godot_project_path=str(self.project_dir), history_file=self.history_file)
        task = router.execute("开始制作 platformer 游戏", confirm=True)

        self.assertEqual(task.status.value, "success")
        self.assertEqual(task.context["project_template"]["template_id"], "platformer")
        self.assertIn("data_tables", task.context["project_template_directories"])
        self.assertEqual(task.context["performance_budget"]["min_fps"], 60)
        self.assertEqual(task.context["performance_budget"]["max_draw_call_count"], 350)
        self.assertEqual(task.context["gameplay_template_id"], "platformer")
        self.assertGreaterEqual(len(task.context["starter_gameplay_systems"]), 6)
        self.assertIn("platformer_player_controller", task.context["gameplay_seeded_features"])
        self.assertEqual(task.context["contract_versions"]["skill_result"], "1.0")
        self.assertEqual(task.context["last_skill_result"]["skill_name"], "init_game_blueprint")
        self.assertEqual(task.context["last_skill_result"]["status"], "success")

        blueprint = router.blueprint_manager.blueprint
        self.assertEqual(blueprint.project_template["template_id"], "platformer")
        self.assertEqual(blueprint.gameplay_template_id, "platformer")
        self.assertGreaterEqual(len(blueprint.starter_gameplay_systems), 6)
        self.assertIn("platformer_player_controller", blueprint.features)
        self.assertTrue((self.project_dir / "scenes" / "platformer").exists())
        self.assertTrue((self.project_dir / "agent_templates" / "genres").exists())

    def test_genre_templates_endpoint_returns_registry_items(self):
        client = TestClient(app)
        response = client.get("/genre-templates", params={"project_path": "default"})

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["default_template_id"], DEFAULT_GENRE_TEMPLATE_ID)
        self.assertTrue(any(item["template_id"] == "visual_novel" for item in payload["items"]))

    def test_genre_template_marketplace_endpoint_returns_manifest(self):
        client = TestClient(app)
        response = client.get("/genre-templates/marketplace", params={"project_path": "default"})

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["schema_version"], "1.0")
        self.assertTrue(payload["validation"]["passed"])
        self.assertTrue(any(item["source_path"].endswith("visual_novel.json") for item in payload["items"]))


if __name__ == "__main__":
    unittest.main()

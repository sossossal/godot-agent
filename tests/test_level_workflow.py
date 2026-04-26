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
from agent_system.skills.dev.level_workflow_skill import LevelWorkflowSkill


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


class LevelWorkflowTestCase(unittest.TestCase):
    def setUp(self):
        self.project_dir = project_root / "tests" / ".tmp_level_workflow"
        shutil.rmtree(self.project_dir, ignore_errors=True)
        self.project_dir.mkdir(parents=True, exist_ok=True)
        (self.project_dir / "project.godot").write_text(
            '[application]\nconfig/name="Level Workflow Sandbox"\n',
            encoding="utf-8",
        )
        self.history_file = tempfile.mktemp(suffix=".json")
        self.runtime_snapshot_dir = project_root / "logs" / "test_artifacts"
        self.runtime_snapshot_dir.mkdir(parents=True, exist_ok=True)

    def tearDown(self):
        shutil.rmtree(self.project_dir, ignore_errors=True)
        if os.path.exists(self.history_file):
            os.remove(self.history_file)
        for snapshot_name in (
            "forest_gateway_snapshot_a.json",
            "forest_gateway_snapshot_b.json",
            "route_hub_snapshot.json",
        ):
            (self.runtime_snapshot_dir / snapshot_name).unlink(missing_ok=True)

    def test_level_workflow_template_writes_p8_scene_manifest_and_report(self):
        skill = LevelWorkflowSkill(MockGodotCLI(project_path=str(self.project_dir)))
        task = Task(prompt="为关卡 forest_gateway 生成关卡模板")
        result = skill.execute(task, {
            "action": "template",
            "level_name": "forest_gateway",
            "level_type": "combat",
        })

        scene_path = self.project_dir / "scenes" / "levels" / "forest_gateway.tscn"
        manifest_path = self.project_dir / "data_tables" / "levels" / "forest_gateway.json"
        manifest_payload = manifest_path.read_text(encoding="utf-8")
        scene_payload = scene_path.read_text(encoding="utf-8")

        self.assertTrue(result.success)
        self.assertTrue(scene_path.exists())
        self.assertTrue(manifest_path.exists())
        self.assertEqual(task.context["scene_path"], "res://scenes/levels/forest_gateway.tscn")
        self.assertEqual(task.context["level_manifest_path"], "res://data_tables/levels/forest_gateway.json")
        self.assertEqual(result.metadata["skill_result"]["skill_name"], "manage_level_workflow")
        self.assertTrue(result.metadata["skill_result"]["validation"]["passed"])
        self.assertTrue(result.metadata["skill_result"]["rollback"]["available"])
        self.assertEqual(result.data["level_manifest"]["schema_version"], "1.1")
        self.assertIn('"schema_version": "1.1"', manifest_payload)
        self.assertIn('"navigation_agents"', manifest_payload)
        self.assertIn('"tile_layers"', manifest_payload)
        self.assertIn('"trigger_zones"', manifest_payload)
        self.assertIn('"level_bounds"', manifest_payload)
        self.assertIn('[node name="EnemyNavigationAgent" type="NavigationAgent2D" parent="."]', scene_payload)
        self.assertIn('[node name="TileLayerGround" type="TileMap" parent="."]', scene_payload)
        self.assertIn('[node name="TriggerLevelExit" type="Area2D" parent="."]', scene_payload)
        self.assertIn('[node name="LevelBounds" type="Node" parent="."]', scene_payload)

    def test_level_workflow_audit_detects_missing_p8_nodes(self):
        scene_path = self.project_dir / "scenes" / "levels" / "broken_level.tscn"
        manifest_path = self.project_dir / "data_tables" / "levels" / "broken_level.json"
        scene_path.parent.mkdir(parents=True, exist_ok=True)
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        scene_path.write_text(
            '[gd_scene format=3]\n'
            '\n'
            '[node name="BrokenLevel" type="Node2D"]\n'
            '[node name="PlayerSpawn" type="Marker2D" parent="."]\n'
            '[node name="LevelExit" type="Marker2D" parent="."]\n'
            '[node name="NavigationZoneMain" type="NavigationRegion2D" parent="."]\n'
            '[node name="CollisionProfileWorld" type="Node" parent="."]\n',
            encoding="utf-8",
        )
        manifest_path.write_text(
            '{\n'
            '  "schema_version": "1.1",\n'
            '  "level_id": "broken_level",\n'
            '  "level_type": "combat",\n'
            '  "scene_path": "res://scenes/levels/broken_level.tscn",\n'
            '  "spawn_points": [{"id": "player_spawn", "node_path": "PlayerSpawn", "kind": "spawn"}],\n'
            '  "interaction_points": [{"id": "level_exit", "node_path": "LevelExit", "kind": "exit"}],\n'
            '  "checkpoints": [],\n'
            '  "navigation_zones": [{"id": "main_route", "node_path": "NavigationZoneMain", "kind": "walkable"}],\n'
            '  "navigation_agents": [{"id": "enemy_agent", "node_path": "EnemyNavigationAgent", "kind": "enemy"}],\n'
            '  "tile_layers": [{"id": "ground", "node_path": "TileLayerGround", "kind": "ground"}],\n'
            '  "trigger_zones": [{"id": "exit_trigger", "node_path": "TriggerLevelExit", "kind": "exit"}],\n'
            '  "collision_layers": [{"name": "world", "layer": 1}],\n'
            '  "level_bounds": {"min": [0, 0], "max": [1024, 512]},\n'
            '  "critical_path": ["player_spawn", "level_exit"]\n'
            '}\n',
            encoding="utf-8",
        )

        skill = LevelWorkflowSkill(MockGodotCLI(project_path=str(self.project_dir)))
        task = Task(prompt="审计关卡 broken_level")
        result = skill.execute(task, {
            "action": "audit",
            "level_name": "broken_level",
            "scene_path": "res://scenes/levels/broken_level.tscn",
            "manifest_path": "data_tables/levels/broken_level.json",
        })

        issues = result.metadata["skill_result"]["validation"]["issues"]
        self.assertFalse(result.success)
        self.assertEqual(result.metadata["skill_result"]["skill_name"], "manage_level_workflow")
        self.assertFalse(result.metadata["skill_result"]["validation"]["passed"])
        self.assertTrue(any("EnemyNavigationAgent" in issue for issue in issues))
        self.assertTrue(any("TileLayerGround" in issue for issue in issues))
        self.assertTrue(any("TriggerLevelExit" in issue for issue in issues))
        self.assertTrue(any("LevelBounds" in issue for issue in issues))
        self.assertTrue(any(artifact.type == "report" for artifact in result.artifacts))

    def test_level_workflow_snapshot_and_diff_capture_scene_changes(self):
        skill = LevelWorkflowSkill(MockGodotCLI(project_path=str(self.project_dir)))
        template_task = Task(prompt="生成关卡 route_hub 模板")
        template_result = skill.execute(template_task, {
            "action": "template",
            "level_name": "route_hub",
            "level_type": "hub",
        })
        self.assertTrue(template_result.success)

        scene_path = self.project_dir / "scenes" / "levels" / "route_hub.tscn"
        snapshot_a = self.runtime_snapshot_dir / "route_hub_snapshot.json"
        snapshot_b = self.runtime_snapshot_dir / "forest_gateway_snapshot_b.json"

        snapshot_result = skill.execute(Task(prompt="生成 route_hub 快照"), {
            "action": "snapshot",
            "level_name": "route_hub",
            "level_type": "hub",
            "snapshot_path": str(snapshot_a),
        })
        self.assertTrue(snapshot_result.success)
        self.assertTrue(snapshot_a.exists())
        self.assertEqual(snapshot_result.data["snapshot"]["node_count"], len(snapshot_result.data["snapshot"]["scene_nodes"]))

        scene_text = scene_path.read_text(encoding="utf-8")
        scene_text += '[node name="BonusTrigger" type="Area2D" parent="."]\n\n'
        scene_path.write_text(scene_text, encoding="utf-8")

        diff_result = skill.execute(Task(prompt="对比 route_hub 快照"), {
            "action": "diff",
            "level_name": "route_hub",
            "level_type": "hub",
            "snapshot_path": str(snapshot_b),
            "compare_snapshot_path": str(snapshot_a),
        })

        self.assertTrue(diff_result.success)
        self.assertTrue(snapshot_b.exists())
        self.assertEqual(diff_result.data["diff"]["status"], "changed")
        self.assertTrue(any(node["path"] == "BonusTrigger" for node in diff_result.data["diff"]["added_nodes"]))
        self.assertTrue(any(artifact.type == "report" for artifact in diff_result.artifacts))

    @patch("agent_system.router.GodotCLI", MockGodotCLI)
    def test_router_routes_level_prompt_and_records_skill_result(self):
        from agent_system.router import GodotAgentRouter

        router = GodotAgentRouter(godot_project_path=str(self.project_dir), history_file=self.history_file)
        task = router.execute("为关卡 forest_gateway 生成关卡模板并初始化出生点和交互点", confirm=True)

        self.assertEqual(task.status, TaskStatus.SUCCESS)
        self.assertEqual(task.steps[0].role, "developer")
        self.assertEqual(task.context["last_skill_result"]["skill_name"], "manage_level_workflow")
        self.assertTrue(task.context["last_skill_result"]["validation"]["passed"])
        self.assertTrue((self.project_dir / "scenes" / "levels" / "forest_gateway.tscn").exists())
        self.assertTrue((self.project_dir / "data_tables" / "levels" / "forest_gateway.json").exists())


if __name__ == "__main__":
    unittest.main()

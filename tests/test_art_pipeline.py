import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from agent_system.models import Task, ToolResult, TaskStatus
from agent_system.skills.resource.art_asset_skill import ArtAssetPipelineSkill


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


class ArtAssetPipelineTestCase(unittest.TestCase):
    def setUp(self):
        self.project_dir = project_root / "tests" / ".tmp_art_pipeline"
        shutil.rmtree(self.project_dir, ignore_errors=True)
        self.project_dir.mkdir(parents=True, exist_ok=True)
        (self.project_dir / "raw_assets").mkdir(parents=True, exist_ok=True)
        self.history_file = tempfile.mktemp(suffix=".json")

    def tearDown(self):
        shutil.rmtree(self.project_dir, ignore_errors=True)
        if os.path.exists(self.history_file):
            os.remove(self.history_file)

    def test_art_asset_skill_apply_copies_asset_and_writes_manifest(self):
        source_file = self.project_dir / "raw_assets" / "main_menu_logo.png"
        source_file.write_bytes(b"fake-ui-png")

        skill = ArtAssetPipelineSkill(MockGodotCLI(project_path=str(self.project_dir)))
        task = Task(prompt="导入 UI 图标")
        result = skill.execute(task, {
            "action": "apply",
            "asset_type": "ui",
            "source_path": "res://raw_assets/main_menu_logo.png",
            "width": 512,
            "height": 256,
            "tags": ["ui", "menu"],
        })

        manifest_path = self.project_dir / "assets" / "manifests" / "ui_assets.json"
        target_path = self.project_dir / "assets" / "ui" / "main_menu_logo.png"
        self.assertTrue(result.success)
        self.assertTrue(manifest_path.exists())
        self.assertTrue(target_path.exists())
        self.assertEqual(target_path.read_bytes(), b"fake-ui-png")
        self.assertEqual(result.metadata["skill_result"]["skill_name"], "manage_art_asset_pipeline")
        self.assertEqual(result.metadata["skill_result"]["validation"]["passed"], True)
        manifest_payload = manifest_path.read_text(encoding="utf-8")
        self.assertIn('"asset_id": "main_menu_logo"', manifest_payload)
        self.assertIn('"schema_version": "1.1"', manifest_payload)

    def test_art_asset_skill_preview_blocks_budget_violation(self):
        source_file = self.project_dir / "raw_assets" / "boss_sheet.png"
        source_file.write_bytes(b"fake-sheet-png")

        skill = ArtAssetPipelineSkill(MockGodotCLI(project_path=str(self.project_dir)))
        task = Task(prompt="预览精灵表")
        result = skill.execute(task, {
            "action": "preview",
            "asset_type": "spritesheet",
            "source_path": "res://raw_assets/boss_sheet.png",
            "width": 8192,
            "height": 4096,
            "frame_width": 128,
            "frame_height": 128,
        })

        self.assertFalse(result.success)
        self.assertEqual(result.metadata["skill_result"]["skill_name"], "manage_art_asset_pipeline")
        self.assertEqual(result.metadata["skill_result"]["validation"]["passed"], False)
        self.assertTrue(any("超出预算" in issue for issue in result.metadata["skill_result"]["validation"]["issues"]))
        self.assertTrue(any(artifact.type == "report" for artifact in result.artifacts))

    def test_art_asset_skill_builds_spritesheet_atlas_plan(self):
        source_file = self.project_dir / "raw_assets" / "runner_sheet.png"
        source_file.write_bytes(b"fake-runner-sheet")

        skill = ArtAssetPipelineSkill(MockGodotCLI(project_path=str(self.project_dir)))
        task = Task(prompt="预览精灵表图集计划")
        result = skill.execute(task, {
            "action": "preview",
            "asset_type": "spritesheet",
            "asset_id": "runner_sheet",
            "source_path": "res://raw_assets/runner_sheet.png",
            "width": 512,
            "height": 256,
            "frame_width": 128,
            "frame_height": 128,
        })

        self.assertTrue(result.success)
        atlas_plan = task.context["art_asset_atlas_plan"]
        self.assertEqual(atlas_plan["status"], "passed")
        self.assertEqual(atlas_plan["entry_count"], 1)
        self.assertEqual(atlas_plan["total_frame_count"], 8)
        self.assertEqual(task.context["art_asset_atlas_frame_count"], 8)
        self.assertEqual(task.context["art_asset_profile"]["entries"][0]["atlas"]["columns"], 4)
        self.assertIn("runner_sheet.atlas.json", task.context["art_asset_profile"]["entries"][0]["atlas"]["atlas_path"])

    def test_art_asset_skill_audits_material_resource_links(self):
        material_file = self.project_dir / "raw_assets" / "materials" / "stone_wall.tres"
        albedo_file = self.project_dir / "raw_assets" / "materials" / "stone_wall_albedo.png"
        normal_file = self.project_dir / "raw_assets" / "materials" / "stone_wall_normal.png"
        orm_file = self.project_dir / "raw_assets" / "materials" / "stone_wall_orm.png"
        material_file.parent.mkdir(parents=True, exist_ok=True)
        material_file.write_bytes(b"fake-material")
        albedo_file.write_bytes(b"fake-albedo")
        normal_file.write_bytes(b"fake-normal")
        orm_file.write_bytes(b"fake-orm")

        skill = ArtAssetPipelineSkill(MockGodotCLI(project_path=str(self.project_dir)))
        task = Task(prompt="预览材质资源链接")
        result = skill.execute(task, {
            "action": "preview",
            "asset_type": "material",
            "asset_id": "stone_wall_material",
            "source_path": "res://raw_assets/materials/stone_wall.tres",
            "target_path": "res://assets/materials/stone_wall.tres",
            "source_dependency_paths": [
                "res://raw_assets/materials/stone_wall_albedo.png",
                "res://raw_assets/materials/stone_wall_normal.png",
                "res://raw_assets/materials/stone_wall_orm.png",
            ],
            "target_dependency_paths": [
                "res://assets/materials/stone_wall_albedo.png",
                "res://assets/materials/stone_wall_normal.png",
                "res://assets/materials/stone_wall_orm.png",
            ],
        })

        self.assertTrue(result.success)
        audit = task.context["art_asset_material_link_audit"]
        self.assertEqual(audit["status"], "passed")
        self.assertEqual(audit["linked_texture_count"], 3)
        self.assertEqual(task.context["art_asset_material_link_issue_count"], 0)
        self.assertEqual(audit["entries"][0]["channels"]["albedo"], ["res://assets/materials/stone_wall_albedo.png"])
        self.assertEqual(audit["entries"][0]["missing_channels"], [])

    def test_art_asset_skill_apply_model_profile_copies_dependencies_and_records_profile_fields(self):
        source_file = self.project_dir / "raw_assets" / "models" / "hero_knight.blend"
        albedo_file = self.project_dir / "raw_assets" / "models" / "hero_knight_albedo.png"
        normal_file = self.project_dir / "raw_assets" / "models" / "hero_knight_normal.png"
        source_file.parent.mkdir(parents=True, exist_ok=True)
        source_file.write_bytes(b"fake-blend")
        albedo_file.write_bytes(b"fake-albedo")
        normal_file.write_bytes(b"fake-normal")

        skill = ArtAssetPipelineSkill(MockGodotCLI(project_path=str(self.project_dir)))
        task = Task(prompt="导入 Blender GLTF 模型")
        result = skill.execute(task, {
            "action": "apply",
            "asset_type": "model",
            "asset_id": "hero_knight_model",
            "source_path": "res://raw_assets/models/hero_knight.blend",
            "target_path": "res://assets/models/hero_knight.glb",
            "source_tool": "blender",
            "lod_count": 3,
            "source_dependency_paths": [
                "res://raw_assets/models/hero_knight_albedo.png",
                "res://raw_assets/models/hero_knight_normal.png",
            ],
            "target_dependency_paths": [
                "res://assets/models/hero_knight_albedo.png",
                "res://assets/models/hero_knight_normal.png",
            ],
            "estimated_memory_mb": 18.0,
        })

        manifest_path = self.project_dir / "assets" / "manifests" / "model_assets.json"
        target_path = self.project_dir / "assets" / "models" / "hero_knight.glb"
        self.assertTrue(result.success)
        self.assertTrue(manifest_path.exists())
        self.assertTrue(target_path.exists())
        self.assertTrue((self.project_dir / "assets" / "models" / "hero_knight_albedo.png").exists())
        self.assertTrue((self.project_dir / "assets" / "models" / "hero_knight_normal.png").exists())
        self.assertEqual(task.context["art_asset_source_tool"], "blender")
        self.assertEqual(task.context["art_asset_lod_count"], 3)
        self.assertEqual(task.context["art_asset_copy_count"], 3)
        manifest_payload = manifest_path.read_text(encoding="utf-8")
        self.assertIn('"dependency_targets"', manifest_payload)
        self.assertIn('"source_tool": "blender"', manifest_payload)

    def test_art_asset_skill_preview_blocks_outsource_package_without_metadata(self):
        source_file = self.project_dir / "raw_assets" / "outsource" / "npc_vendor_delivery.zip"
        source_file.parent.mkdir(parents=True, exist_ok=True)
        source_file.write_bytes(b"fake-zip")

        skill = ArtAssetPipelineSkill(MockGodotCLI(project_path=str(self.project_dir)))
        task = Task(prompt="预览外包交付包")
        result = skill.execute(task, {
            "action": "preview",
            "asset_type": "outsource",
            "source_path": "res://raw_assets/outsource/npc_vendor_delivery.zip",
        })

        self.assertFalse(result.success)
        self.assertEqual(result.metadata["skill_result"]["skill_name"], "manage_art_asset_pipeline")
        self.assertFalse(result.metadata["skill_result"]["validation"]["passed"])
        self.assertTrue(any("package_version" in issue for issue in result.metadata["skill_result"]["validation"]["issues"]))
        self.assertTrue(any("license_name" in issue for issue in result.metadata["skill_result"]["validation"]["issues"]))

    @patch("agent_system.router.GodotCLI", MockGodotCLI)
    def test_router_routes_art_asset_prompt_and_records_skill_result(self):
        from agent_system.router import GodotAgentRouter

        source_file = self.project_dir / "raw_assets" / "ui_icon.png"
        source_file.write_bytes(b"fake-ui-icon")

        router = GodotAgentRouter(godot_project_path=str(self.project_dir), history_file=self.history_file)
        task = router.execute("导入 UI 图标 res://raw_assets/ui_icon.png 尺寸 256x128", confirm=True)

        self.assertEqual(task.status, TaskStatus.SUCCESS)
        self.assertEqual(task.steps[0].role, "resource_manager")
        self.assertEqual(task.context["last_skill_result"]["skill_name"], "manage_art_asset_pipeline")
        self.assertEqual(task.context["last_skill_result"]["validation"]["passed"], True)
        self.assertTrue((self.project_dir / "assets" / "ui" / "ui_icon.png").exists())
        self.assertTrue((self.project_dir / "assets" / "manifests" / "ui_assets.json").exists())

    @patch("agent_system.router.GodotCLI", MockGodotCLI)
    def test_router_routes_blender_model_prompt_and_records_skill_result(self):
        from agent_system.router import GodotAgentRouter

        source_file = self.project_dir / "raw_assets" / "models" / "mech_guard.blend"
        texture_file = self.project_dir / "raw_assets" / "models" / "mech_guard_albedo.png"
        source_file.parent.mkdir(parents=True, exist_ok=True)
        source_file.write_bytes(b"fake-mech-blend")
        texture_file.write_bytes(b"fake-mech-albedo")

        router = GodotAgentRouter(godot_project_path=str(self.project_dir), history_file=self.history_file)
        task = router.execute(
            "同步 Blender GLTF 模型 资产ID mech_guard res://raw_assets/models/mech_guard.blend 到 res://assets/models/mech_guard.glb LOD 2",
            confirm=True,
        )

        self.assertEqual(task.status, TaskStatus.SUCCESS)
        self.assertEqual(task.context["last_skill_result"]["skill_name"], "manage_art_asset_pipeline")
        self.assertEqual(task.context["art_asset_type"], "model")
        self.assertEqual(task.context["art_asset_source_tool"], "blender")
        self.assertTrue((self.project_dir / "assets" / "models" / "mech_guard.glb").exists())
        self.assertTrue((self.project_dir / "assets" / "manifests" / "model_assets.json").exists())


if __name__ == "__main__":
    unittest.main()

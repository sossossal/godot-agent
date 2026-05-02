import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path


project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from agent_system.models import Task
from agent_system.skills.code.ai_skill import AIBehaviorSkill
from agent_system.skills.code.animation_skill import TweenAnimationSkill
from agent_system.skills.code.dialogue_skill import DialogueSystemSkill
from agent_system.skills.code.movement_skill import GenerateMovementSkill
from agent_system.skills.code.signal_bus_skill import SignalBusSkill
from agent_system.skills.code.wiring_skill import SignalWiringSkill
from agent_system.skills.dev.attach_script_skill import AttachScriptSkill
from agent_system.skills.dev.create_scene_skill import CreateSceneSkill
from agent_system.skills.dev.input_skill import InputMappingSkill
from agent_system.skills.dev.instantiate_skill import InstantiateSkill
from agent_system.skills.dev.physics_skill import PhysicsConfigSkill
from agent_system.skills.dev.setup_3d_skill import Setup3DEnvironmentSkill
from agent_system.skills.resource.data_table_skill import DataTablePipelineSkill
from agent_system.skills.resource.export_skill import ExportProjectSkill
from agent_system.tools.doctor import SystemDoctor
from agent_system.validations import ProjectLayoutValidator


class MockGodotCLI:
    def __init__(self, executable_path=None, project_path=None):
        self.executable = "godot"
        self.project_path = project_path

    def is_available(self): return True
    def run_headless(self, script_path, args=None): return None
    def run_scene(self, scene_path): return None
    def execute_editor_script(self, script_content): return None
    def export_project(self, preset_name, output_path, release=True):
        from agent_system.models import ToolResult
        return ToolResult(True, "OK", data={"stdout": "", "stderr": ""})
    def get_version(self): return "4.2.0"


class ProjectLayoutTestCase(unittest.TestCase):
    def setUp(self):
        self.project_dir = project_root / "tests" / ".tmp_project_layout"
        shutil.rmtree(self.project_dir, ignore_errors=True)
        self.project_dir.mkdir(parents=True, exist_ok=True)

    def tearDown(self):
        shutil.rmtree(self.project_dir, ignore_errors=True)

    def test_validator_accepts_standard_data_table_path(self):
        validator = ProjectLayoutValidator(project_root=self.project_dir, runtime_root=project_root)
        result = validator.validate_managed_path(self.project_dir / "data_tables" / "quests.csv", "data_table")

        self.assertTrue(result["passed"])
        self.assertEqual(result["schema_version"], "1.0")

    def test_validator_accepts_asset_manifest_and_art_asset_paths(self):
        validator = ProjectLayoutValidator(project_root=self.project_dir, runtime_root=project_root)
        manifest_result = validator.validate_managed_path(
            self.project_dir / "assets" / "manifests" / "ui_assets.json",
            "asset_manifest",
        )
        asset_result = validator.validate_managed_path(
            self.project_dir / "assets" / "ui" / "main_menu_logo.png",
            "art_asset",
        )

        self.assertTrue(manifest_result["passed"])
        self.assertTrue(asset_result["passed"])

    def test_validator_accepts_telemetry_catalog_and_session_paths(self):
        validator = ProjectLayoutValidator(project_root=self.project_dir, runtime_root=project_root)
        catalog_result = validator.validate_managed_path(
            self.project_dir / "telemetry" / "event_catalog.json",
            "telemetry_catalog",
        )
        session_result = validator.validate_managed_path(
            self.project_dir / "telemetry" / "sessions" / "session_001.jsonl",
            "telemetry_session",
        )

        self.assertTrue(catalog_result["passed"])
        self.assertTrue(session_result["passed"])

    def test_validator_accepts_liveops_manifest_paths(self):
        validator = ProjectLayoutValidator(project_root=self.project_dir, runtime_root=project_root)
        remote_config_result = validator.validate_managed_path(
            self.project_dir / "liveops" / "remote_config.json",
            "liveops_manifest",
        )
        experiment_result = validator.validate_managed_path(
            self.project_dir / "liveops" / "experiments.json",
            "liveops_manifest",
        )

        self.assertTrue(remote_config_result["passed"])
        self.assertTrue(experiment_result["passed"])

    def test_validator_accepts_platform_delivery_manifest_path(self):
        validator = ProjectLayoutValidator(project_root=self.project_dir, runtime_root=project_root)
        result = validator.validate_managed_path(
            self.project_dir / "deployment" / "platform_delivery.json",
            "platform_delivery_manifest",
        )

        self.assertTrue(result["passed"])

    def test_validator_accepts_scene_ownership_manifest_path(self):
        validator = ProjectLayoutValidator(project_root=self.project_dir, runtime_root=project_root)
        result = validator.validate_managed_path(
            self.project_dir / "scenes" / "scene_ownership_board.json",
            "scene_ownership_manifest",
        )

        self.assertTrue(result["passed"])

    def test_validator_accepts_project_config_path(self):
        validator = ProjectLayoutValidator(project_root=self.project_dir, runtime_root=project_root)
        result = validator.validate_managed_path(self.project_dir / "project.godot", "project_config")

        self.assertTrue(result["passed"])

    def test_validator_returns_repair_preview_for_invalid_script_path(self):
        validator = ProjectLayoutValidator(project_root=self.project_dir, runtime_root=project_root)
        result = validator.validate_managed_path(self.project_dir / "scripts" / "Bad Name.txt", "generated_script")

        self.assertFalse(result["passed"])
        preview = result["repair_preview"]
        self.assertTrue(preview["available"])
        self.assertEqual(preview["apply_mode"], "preview_only")
        self.assertEqual(preview["suggested_relative_path"], "scripts/bad_name.gd")
        self.assertIn("wrong_extension", preview["issue_codes"])
        self.assertIn("wrong_name", preview["issue_codes"])

    def test_validator_returns_repair_preview_for_wrong_scene_directory(self):
        validator = ProjectLayoutValidator(project_root=self.project_dir, runtime_root=project_root)
        result = validator.validate_managed_path(self.project_dir / "levels" / "Bad Scene.txt", "generated_scene")

        self.assertFalse(result["passed"])
        preview = result["repair_preview"]
        self.assertEqual(preview["suggested_relative_path"], "scenes/Bad_Scene.tscn")
        self.assertTrue(any(item["field"] == "directory" for item in preview["changes"]))
        self.assertTrue(any(item["field"] == "file_name" for item in preview["changes"]))

    def test_validator_returns_repair_preview_for_project_config(self):
        validator = ProjectLayoutValidator(project_root=self.project_dir, runtime_root=project_root)
        result = validator.validate_managed_path(self.project_dir / "config" / "project.txt", "project_config")

        self.assertFalse(result["passed"])
        self.assertEqual(result["repair_preview"]["suggested_relative_path"], "project.godot")

    def test_validator_accepts_release_promotion_history_manifest_path(self):
        validator = ProjectLayoutValidator(project_root=self.project_dir, runtime_root=project_root)
        result = validator.validate_managed_path(
            self.project_dir / "deployment" / "release_promotion_history.json",
            "release_promotion_history_manifest",
        )

        self.assertTrue(result["passed"])

    def test_validator_accepts_release_request_auth_manifest_path(self):
        validator = ProjectLayoutValidator(project_root=self.project_dir, runtime_root=project_root)
        result = validator.validate_managed_path(
            self.project_dir / "deployment" / "release_request_auth.json",
            "release_request_auth_manifest",
        )

        self.assertTrue(result["passed"])

    def test_validator_accepts_release_identity_registry_manifest_path(self):
        validator = ProjectLayoutValidator(project_root=self.project_dir, runtime_root=project_root)
        result = validator.validate_managed_path(
            self.project_dir / "deployment" / "release_identity_registry.json",
            "release_identity_registry_manifest",
        )

        self.assertTrue(result["passed"])

    def test_validator_accepts_release_execution_status_and_channel_manifest_paths(self):
        validator = ProjectLayoutValidator(project_root=self.project_dir, runtime_root=project_root)
        status_result = validator.validate_managed_path(
            self.project_dir / "deployment" / "release_execution_status.json",
            "release_execution_status_manifest",
        )
        channel_result = validator.validate_managed_path(
            self.project_dir / "deployment" / "release_channels.json",
            "release_channel_manifest",
        )

        self.assertTrue(status_result["passed"])
        self.assertTrue(channel_result["passed"])

    def test_data_table_skill_blocks_non_managed_table_path(self):
        skill = DataTablePipelineSkill(MockGodotCLI(project_path=str(self.project_dir)))
        task = Task(prompt="导入任务数据表")
        result = skill.execute(task, {
            "action": "apply",
            "table_type": "quest",
            "table_path": "scripts/quests.csv",
            "rows": [
                {
                    "quest_id": "quest_collect",
                    "title": "收集蘑菇",
                    "description": "收集 3 个蘑菇",
                    "target_count": "3",
                    "reward_gold": "50",
                    "next_quest_id": "",
                }
            ],
        })

        self.assertFalse(result.success)
        self.assertIn("文件树规范", result.message)
        self.assertFalse((self.project_dir / "scripts" / "quests.csv").exists())

    def test_movement_skill_blocks_invalid_generated_script_name(self):
        skill = GenerateMovementSkill(MockGodotCLI(project_path=str(self.project_dir)))
        task = Task(prompt="生成移动脚本")
        result = skill.execute(task, {
            "script_name": "bad name.gd",
            "is_3d": False,
        })

        self.assertFalse(result.success)
        self.assertIn("文件树规范", result.message)
        self.assertEqual(result.error, "project_layout_validation_failed")
        layout_check = result.metadata["skill_result"]["validation"]["layout_check"]
        self.assertFalse(layout_check["passed"])
        self.assertEqual(layout_check["repair_preview"]["suggested_relative_path"], "agent_modules/scripts/bad_name.gd")
        self.assertFalse((self.project_dir / "agent_modules" / "scripts" / "bad name.gd").exists())

    def test_ai_skill_blocks_script_path_escape_before_write(self):
        skill = AIBehaviorSkill(MockGodotCLI(project_path=str(self.project_dir)))
        task = Task(prompt="生成 AI 脚本")
        result = skill.execute(task, {
            "target_node_name": "Enemy",
            "target_script_name": "../enemy_ai.gd",
        })

        self.assertFalse(result.success)
        self.assertIn("文件树规范", result.message)
        layout_check = result.metadata["skill_result"]["validation"]["layout_check"]
        self.assertFalse(layout_check["passed"])
        self.assertFalse((self.project_dir / "enemy_ai.gd").exists())

    def test_dialogue_skill_blocks_invalid_generated_script_name(self):
        skill = DialogueSystemSkill(MockGodotCLI(project_path=str(self.project_dir)))
        task = Task(prompt="生成对话系统")
        result = skill.execute(task, {
            "dialogue_name": "intro story",
            "lines": [{"character": "NPC", "text": "hello", "options": []}],
        })

        self.assertFalse(result.success)
        self.assertIn("文件树规范", result.message)
        layout_check = result.metadata["skill_result"]["validation"]["layout_check"]
        self.assertFalse(layout_check["passed"])
        self.assertFalse((self.project_dir / "scripts" / "intro story_controller.gd").exists())

    def test_wiring_skill_blocks_invalid_target_script_before_write(self):
        target = self.project_dir / "scripts" / "bad name.gd"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("extends Node\n", encoding="utf-8")
        skill = SignalWiringSkill(MockGodotCLI(project_path=str(self.project_dir)))
        task = Task(prompt="连接信号")
        result = skill.execute(task, {
            "target_script": "res://scripts/bad name.gd",
            "signal_name": "score_changed",
            "callback_name": "_on_score_changed",
        })

        self.assertFalse(result.success)
        self.assertIn("文件树规范", result.message)
        layout_check = result.metadata["skill_result"]["validation"]["layout_check"]
        self.assertFalse(layout_check["passed"])
        self.assertNotIn("score_changed", target.read_text(encoding="utf-8"))

    def test_animation_skill_blocks_invalid_target_script_before_write(self):
        target = self.project_dir / "scripts" / "bad name.gd"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("extends Control\n", encoding="utf-8")
        skill = TweenAnimationSkill(MockGodotCLI(project_path=str(self.project_dir)))
        task = Task(prompt="添加动画")
        result = skill.execute(task, {
            "target_script": "res://scripts/bad name.gd",
            "animation_type": "fade_in",
        })

        self.assertFalse(result.success)
        self.assertIn("文件树规范", result.message)
        layout_check = result.metadata["skill_result"]["validation"]["layout_check"]
        self.assertFalse(layout_check["passed"])
        self.assertNotIn("play_fade_in", target.read_text(encoding="utf-8"))

    def test_signal_bus_skill_records_layout_check_for_managed_script(self):
        (self.project_dir / "project.godot").write_text("[application]\n", encoding="utf-8")
        skill = SignalBusSkill(MockGodotCLI(project_path=str(self.project_dir)))
        task = Task(prompt="维护信号总线")
        result = skill.execute(task, {"signal_name": "score_changed"})

        self.assertTrue(result.success)
        layout_check = result.metadata["skill_result"]["validation"]["layout_check"]
        self.assertTrue(layout_check["passed"])
        self.assertTrue((self.project_dir / "scripts" / "signal_bus.gd").exists())

    def test_input_skill_records_project_config_layout_check(self):
        (self.project_dir / "project.godot").write_text("[application]\n", encoding="utf-8")
        skill = InputMappingSkill(MockGodotCLI(project_path=str(self.project_dir)))
        task = Task(prompt="配置输入")
        result = skill.execute(task, {"action_name": "jump", "key_code": "Space"})

        self.assertTrue(result.success)
        layout_check = result.metadata["skill_result"]["validation"]["layout_check"]
        self.assertTrue(layout_check["passed"])
        self.assertIn("jump=", (self.project_dir / "project.godot").read_text(encoding="utf-8"))

    def test_create_scene_skill_blocks_invalid_scene_name_before_dispatch(self):
        skill = CreateSceneSkill(MockGodotCLI(project_path=str(self.project_dir)))
        task = Task(prompt="创建场景")
        result = skill.execute(task, {"scene_name": "bad scene", "root_type": "Node2D"})

        self.assertFalse(result.success)
        self.assertIn("文件树规范", result.message)
        layout_check = result.metadata["skill_result"]["validation"]["layout_check"]
        self.assertFalse(layout_check["passed"])
        self.assertNotIn("scene_path", task.context)

    def test_attach_script_skill_blocks_invalid_script_path_before_dispatch(self):
        skill = AttachScriptSkill(MockGodotCLI(project_path=str(self.project_dir)))
        task = Task(prompt="挂载脚本", context={"editor_state": {"is_active": True}})
        result = skill.execute(task, {
            "target_node_path": "Player",
            "script_path": "res://scripts/bad name.gd",
        })

        self.assertFalse(result.success)
        self.assertIn("文件树规范", result.message)
        layout_check = result.metadata["skill_result"]["validation"]["layout_check"]
        self.assertFalse(layout_check["passed"])

    def test_setup_3d_skill_blocks_invalid_scene_name_before_dispatch(self):
        skill = Setup3DEnvironmentSkill(MockGodotCLI(project_path=str(self.project_dir)))
        task = Task(prompt="创建 3D 场景")
        result = skill.execute(task, {"scene_name": "Main 3D"})

        self.assertFalse(result.success)
        self.assertIn("文件树规范", result.message)
        layout_check = result.metadata["skill_result"]["validation"]["layout_check"]
        self.assertFalse(layout_check["passed"])

    def test_instantiate_skill_blocks_invalid_prefab_scene_before_dispatch(self):
        skill = InstantiateSkill(MockGodotCLI(project_path=str(self.project_dir)))
        task = Task(prompt="实例化预制件", context={"editor_state": {"is_active": True}})
        result = skill.execute(task, {"instance_scene_path": "res://scenes/bad scene.tscn"})

        self.assertFalse(result.success)
        self.assertIn("文件树规范", result.message)
        layout_check = result.metadata["skill_result"]["validation"]["layout_check"]
        self.assertFalse(layout_check["passed"])

    def test_physics_skill_blocks_invalid_target_scene_before_headless_bake(self):
        skill = PhysicsConfigSkill(MockGodotCLI(project_path=str(self.project_dir)))
        task = Task(prompt="配置物理碰撞", context={"scene_path": "res://scenes/bad scene.tscn"})
        result = skill.execute(task, {"target_node_path": "Player", "is_3d": False})

        self.assertFalse(result.success)
        self.assertIn("文件树规范", result.message)
        layout_check = result.metadata["skill_result"]["validation"]["layout_check"]
        self.assertFalse(layout_check["passed"])

    def test_export_skill_blocks_output_outside_release_directory(self):
        skill = ExportProjectSkill(MockGodotCLI(project_path=str(self.project_dir)))
        task = Task(prompt="发布试玩 Web 项目", context={"feature_status": "approved"})
        result = skill.execute(task, {
            "preset_name": "Web",
            "output_path": str(self.project_dir / "builds" / "index.html"),
        })

        self.assertFalse(result.success)
        self.assertIn("文件树规范", result.message)
        self.assertFalse((self.project_dir / "builds").exists())

    def test_doctor_reports_invalid_managed_file_name(self):
        temp_repo = project_root / "tests" / ".tmp_doctor_layout"
        shutil.rmtree(temp_repo, ignore_errors=True)
        cwd = os.getcwd()
        try:
            (temp_repo / "scripts").mkdir(parents=True, exist_ok=True)
            (temp_repo / "scripts" / "bad name.gd").write_text("extends Node\n", encoding="utf-8")

            os.chdir(temp_repo)
            doctor = SystemDoctor()
            doctor._check_project_layout()

            self.assertFalse(doctor.results[0]["passed"])
            self.assertIn("文件树规范", doctor.results[0]["name"])
            self.assertIn("bad name.gd", doctor.results[0]["message"])
        finally:
            os.chdir(cwd)
            shutil.rmtree(temp_repo, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()

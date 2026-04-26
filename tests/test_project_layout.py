import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path


project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from agent_system.models import Task
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

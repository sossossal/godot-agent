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
from agent_system.skills.resource.presentation_skill import PresentationPipelineSkill
from agent_system.tools.blueprint_manager import BlueprintManager


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


class PresentationPipelineSkillTestCase(unittest.TestCase):
    def setUp(self):
        self.project_dir = project_root / "tests" / ".tmp_presentation_pipeline_skill"
        shutil.rmtree(self.project_dir, ignore_errors=True)
        self.project_dir.mkdir(parents=True, exist_ok=True)
        (self.project_dir / "project.godot").write_text(
            '[application]\nconfig/name="Presentation Pipeline Sandbox"\n',
            encoding="utf-8",
        )
        self.history_file = tempfile.mktemp(suffix=".json")

    def tearDown(self):
        shutil.rmtree(self.project_dir, ignore_errors=True)
        if os.path.exists(self.history_file):
            os.remove(self.history_file)

    def test_preview_shader_profile_returns_snapshot_and_preview_artifacts(self):
        skill = PresentationPipelineSkill(MockGodotCLI(project_path=str(self.project_dir)))
        task = Task(prompt="预览 shader 表现层模板 heat_wave")
        result = skill.execute(task, {
            "action": "preview",
            "presentation_type": "shader",
            "profile_id": "heat_wave",
            "shader_mode": "canvas_item",
            "shader_params": {
                "wave_strength": 0.25,
                "scroll_speed": 0.4,
                "tint_color": "#44aaff",
            },
            "notes": "P10 preview smoke",
        })

        self.assertTrue(result.success)
        self.assertEqual(result.metadata["skill_result"]["skill_name"], "manage_presentation_pipeline")
        self.assertTrue(result.metadata["skill_result"]["validation"]["passed"])
        self.assertEqual(task.context["presentation_type"], "shader")
        self.assertEqual(task.context["presentation_action"], "preview")
        snapshot = result.data["presentation_profile"]
        self.assertEqual(snapshot["schema_version"], "1.0")
        self.assertEqual(snapshot["presentation_type"], "shader")
        self.assertEqual(snapshot["entry_count"], 1)
        self.assertEqual(snapshot["generated_path_count"], 2)
        self.assertEqual(snapshot["entries"][0]["profile_id"], "heat_wave")
        self.assertTrue(any(path.endswith("heat_wave.gdshader") for path in snapshot["generated_paths"]))
        self.assertFalse((self.project_dir / "assets" / "manifests" / "shader_profiles.json").exists())
        self.assertTrue(any(artifact.type == "report" for artifact in result.artifacts))
        self.assertTrue(any(artifact.path.endswith("heat_wave.gdshader") for artifact in result.artifacts))

    def test_apply_audio_profile_writes_manifest_script_and_blueprint_feature(self):
        skill = PresentationPipelineSkill(MockGodotCLI(project_path=str(self.project_dir)))
        blueprint_manager = BlueprintManager(str(self.project_dir))
        task = Task(
            prompt="应用音频表现模板 boss_warning",
            context={"blueprint_manager": blueprint_manager},
        )
        result = skill.execute(task, {
            "action": "apply",
            "presentation_type": "audio",
            "profile_id": "boss_warning",
            "audio_role": "sfx",
            "event_name": "boss_warning",
            "bus_name": "SFX",
            "audio_stream_path": "res://assets/audio/boss_warning.ogg",
            "autoplay": False,
        })

        manifest_path = self.project_dir / "assets" / "manifests" / "audio_profiles.json"
        script_path = self.project_dir / "scripts" / "audio" / "boss_warning_audio_router.gd"

        self.assertTrue(result.success)
        self.assertTrue(manifest_path.exists())
        self.assertTrue(script_path.exists())
        self.assertTrue(task.context["presentation_written"])
        self.assertEqual(task.context["presentation_type"], "audio")
        self.assertEqual(task.context["presentation_generated_path_count"], 1)
        self.assertIn("res://scripts/audio/boss_warning_audio_router.gd", task.context["presentation_generated_paths"])
        self.assertTrue(result.metadata["skill_result"]["rollback"]["available"])
        self.assertIn("boss_warning", manifest_path.read_text(encoding="utf-8"))
        self.assertIn('"boss_warning": "SFX"', script_path.read_text(encoding="utf-8"))
        self.assertIn("presentation_boss_warning", blueprint_manager.blueprint.features)
        self.assertEqual(blueprint_manager.blueprint.features["presentation_boss_warning"].status, "planned")

    @patch("agent_system.router.GodotCLI", MockGodotCLI)
    def test_router_routes_presentation_prompt_and_records_skill_result(self):
        from agent_system.router import GodotAgentRouter

        router = GodotAgentRouter(godot_project_path=str(self.project_dir), history_file=self.history_file)
        task = router.execute("应用 shader profile heat_wave 并生成材质", confirm=True)

        self.assertEqual(task.status, TaskStatus.SUCCESS)
        self.assertEqual(task.context["last_skill_result"]["skill_name"], "manage_presentation_pipeline")
        self.assertEqual(task.context["presentation_type"], "shader")
        self.assertTrue((self.project_dir / "assets" / "manifests" / "shader_profiles.json").exists())
        self.assertTrue((self.project_dir / "assets" / "shaders" / "heat_wave.gdshader").exists())
        self.assertTrue((self.project_dir / "assets" / "materials" / "heat_wave_material.tres").exists())


if __name__ == "__main__":
    unittest.main()

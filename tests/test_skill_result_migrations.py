"""
Additional skill result contract regressions for migrated dev/code skills.
"""

import os
import base64
import re
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from agent_system.models import TaskStatus, ToolResult
from agent_system.contracts import record_skill_result_on_task
from agent_system.skills.registry import SkillRegistry
from agent_system.tools.blueprint_manager import Feature


class SkillMigrationGodotCLI:
    def __init__(self, executable_path=None, project_path=None):
        self.executable = "godot"
        self.project_path = project_path

    def is_available(self):
        return True

    def run_headless(self, script_path, args=None):
        return ToolResult(True, "OK")

    def run_headless_script(self, script_content):
        screenshot_match = re.search(r'save_png\("([^"]+)"\)', script_content)
        if screenshot_match:
            screenshot_path = Path(screenshot_match.group(1))
            screenshot_path.parent.mkdir(parents=True, exist_ok=True)
            screenshot_path.write_bytes(b"fake-png")
        return ToolResult(True, "OK")

    def run_scene(self, scene_path):
        return ToolResult(True, "OK")

    def execute_editor_script(self, script_content):
        return ToolResult(True, "OK")

    def export_project(self, preset_name, output_path, release=True):
        return ToolResult(True, "OK")

    def get_version(self):
        return "4.2.0"


class SkillResultMigrationTestCase(unittest.TestCase):
    @patch("agent_system.router.GodotCLI", SkillMigrationGodotCLI)
    def setUp(self):
        from agent_system.router import GodotAgentRouter

        self.history_file = tempfile.mktemp(suffix=".json")
        self.project_dir = project_root / "tests" / ".tmp_skill_result_migrations"
        shutil.rmtree(self.project_dir, ignore_errors=True)
        self.project_dir.mkdir(parents=True, exist_ok=True)
        (self.project_dir / "scripts").mkdir(parents=True, exist_ok=True)
        (self.project_dir / "scenes").mkdir(parents=True, exist_ok=True)
        (self.project_dir / "project.godot").write_text(
            '[application]\nconfig/name="Skill Migration Sandbox"\n',
            encoding="utf-8",
        )
        (self.project_dir / "scripts" / "ui.gd").write_text(
            "extends Control\n\nfunc _ready():\n\tpass\n",
            encoding="utf-8",
        )
        (self.project_dir / "scenes" / "main_scene.tscn").write_text(
            '[gd_scene load_steps=1 format=3 uid="uid://skill_migration_scene"]\n'
            '\n'
            '[node name="Main" type="Node3D"]\n'
            '[node name="Player" type="Node3D" parent="."]\n',
            encoding="utf-8",
        )
        self.router = GodotAgentRouter(
            godot_project_path=str(self.project_dir),
            history_file=self.history_file,
        )

    def tearDown(self):
        shutil.rmtree(self.project_dir, ignore_errors=True)
        if os.path.exists(self.history_file):
            os.remove(self.history_file)
        feedback_dir = project_root / "logs" / "visual_feedback"
        for screenshot_file in feedback_dir.glob("feedback_*.png"):
            screenshot_file.unlink(missing_ok=True)

    def _run_skill_directly(self, skill_name, prompt, params):
        task = self.router.plan(prompt, context={})
        task.context["blueprint_manager"] = self.router.blueprint_manager
        skill = SkillRegistry.get_skill(skill_name, self.router.godot_cli, self.router.index_service)
        self.assertIsNotNone(skill)
        result = skill.execute(task, params)
        task.artifacts.extend(result.artifacts)
        record_skill_result_on_task(task, dict(result.metadata or {}).get("skill_result"))
        task.status = TaskStatus.SUCCESS if result.success else TaskStatus.FAILED
        return task, result

    def test_input_mapping_records_skill_result_contract(self):
        task = self.router.execute("把动作 jump 绑定到按键 Space", confirm=True)

        project_text = (self.project_dir / "project.godot").read_text(encoding="utf-8")
        self.assertEqual(task.status, TaskStatus.SUCCESS)
        self.assertEqual(task.steps[0].role, "developer")
        self.assertEqual(task.context["last_skill_result"]["skill_name"], "manage_input_mapping")
        self.assertEqual(task.context["last_skill_result"]["validation"]["passed"], True)
        self.assertTrue(task.context["last_skill_result"]["rollback"]["available"])
        self.assertIn('jump={"deadzone":0.5', project_text)
        self.assertTrue(any(backup.original_path.endswith("project.godot") for backup in task.backups))
        self.assertTrue(any(
            artifact.type == "config" and artifact.metadata.get("skill_name") == "manage_input_mapping"
            for artifact in task.artifacts
        ))

    def test_inject_node_records_skill_result_contract(self):
        task = self.router.execute(
            "在当前节点下添加一个 Sprite2D 节点",
            context={
                "editor_state": {
                    "is_active": True,
                    "selected_node_paths": ["player/weapon_slot"],
                }
            },
            confirm=True,
        )

        self.assertEqual(task.status, TaskStatus.WAITING_ACK)
        self.assertEqual(task.context["last_skill_result"]["skill_name"], "inject_godot_node")
        self.assertEqual(task.context["last_skill_result"]["validation"]["passed"], True)
        self.assertEqual(task.context["last_skill_result"]["rollback"]["strategy"], "wait_for_editor_confirmation")
        self.assertTrue(any(
            artifact.type == "editor_script" and artifact.metadata.get("skill_name") == "inject_godot_node"
            for artifact in task.artifacts
        ))

    def test_ui_layout_records_skill_result_contract(self):
        task = self.router.execute(
            "创建一个带标题和开始按钮的 UI 布局",
            context={"editor_state": {"is_active": True}},
            confirm=True,
        )

        self.assertEqual(task.status, TaskStatus.WAITING_ACK)
        self.assertEqual(task.context["last_skill_result"]["skill_name"], "auto_layout_ui")
        self.assertEqual(task.context["last_skill_result"]["validation"]["passed"], True)
        self.assertTrue(any(
            artifact.type == "editor_script" and artifact.metadata.get("skill_name") == "auto_layout_ui"
            for artifact in task.artifacts
        ))

    def test_instantiate_prefab_records_skill_result_contract(self):
        task = self.router.execute(
            "实例化 res://scenes/main_scene.tscn 预制件",
            context={"editor_state": {"is_active": True}},
            confirm=True,
        )

        self.assertEqual(task.status, TaskStatus.WAITING_ACK)
        self.assertEqual(task.context["last_skill_result"]["skill_name"], "instantiate_scene_prefab")
        self.assertEqual(task.context["last_skill_result"]["validation"]["passed"], True)
        self.assertTrue(any(
            artifact.type == "editor_script" and artifact.metadata.get("skill_name") == "instantiate_scene_prefab"
            for artifact in task.artifacts
        ))

    def test_physics_config_records_skill_result_contract(self):
        task = self.router.execute(
            "给 Player 节点配置物理碰撞",
            context={"scene_path": "res://scenes/main_scene.tscn"},
            confirm=True,
        )

        self.assertEqual(task.status, TaskStatus.SUCCESS)
        self.assertEqual(task.context["last_skill_result"]["skill_name"], "configure_physics_collision")
        self.assertEqual(task.context["last_skill_result"]["validation"]["passed"], True)
        self.assertTrue(any(
            artifact.type == "headless_script" and artifact.metadata.get("skill_name") == "configure_physics_collision"
            for artifact in task.artifacts
        ))

    def test_setup_3d_environment_records_skill_result_contract(self):
        task = self.router.execute(
            "搭建3D环境",
            context={"editor_state": {"is_active": True}},
            confirm=True,
        )

        self.assertEqual(task.status, TaskStatus.WAITING_ACK)
        self.assertEqual(task.context["last_skill_result"]["skill_name"], "setup_3d_environment")
        self.assertEqual(task.context["last_skill_result"]["validation"]["passed"], True)
        self.assertTrue(any(
            artifact.type == "editor_script" and artifact.metadata.get("skill_name") == "setup_3d_environment"
            for artifact in task.artifacts
        ))

    def test_inject_3d_primitive_records_skill_result_contract(self):
        task = self.router.execute(
            "添加一个立方体",
            context={"editor_state": {"is_active": True}},
            confirm=True,
        )

        self.assertEqual(task.status, TaskStatus.WAITING_ACK)
        self.assertEqual(task.context["last_skill_result"]["skill_name"], "inject_3d_primitive")
        self.assertEqual(task.context["last_skill_result"]["validation"]["passed"], True)
        self.assertTrue(any(
            artifact.type == "editor_script" and artifact.metadata.get("skill_name") == "inject_3d_primitive"
            for artifact in task.artifacts
        ))

    def test_vfx_injection_records_skill_result_contract(self):
        task = self.router.execute(
            "添加爆炸特效",
            context={"editor_state": {"is_active": True}},
            confirm=True,
        )

        self.assertEqual(task.status, TaskStatus.WAITING_ACK)
        self.assertEqual(task.context["last_skill_result"]["skill_name"], "inject_vfx_particle")
        self.assertEqual(task.context["last_skill_result"]["validation"]["passed"], True)
        self.assertTrue(any(
            artifact.type == "editor_script" and artifact.metadata.get("skill_name") == "inject_vfx_particle"
            for artifact in task.artifacts
        ))

    def test_signal_bus_records_skill_result_contract(self):
        task = self.router.execute("注册全局信号 score_changed", confirm=True)

        signal_bus_path = self.project_dir / "scripts" / "signal_bus.gd"
        project_text = (self.project_dir / "project.godot").read_text(encoding="utf-8")
        self.assertEqual(task.status, TaskStatus.SUCCESS)
        self.assertEqual(task.context["last_skill_result"]["skill_name"], "manage_signal_bus")
        self.assertEqual(task.context["last_skill_result"]["validation"]["passed"], True)
        self.assertTrue(task.context["last_skill_result"]["rollback"]["available"])
        self.assertTrue(signal_bus_path.exists())
        self.assertIn("signal score_changed", signal_bus_path.read_text(encoding="utf-8"))
        self.assertIn('SignalBus="*res://scripts/signal_bus.gd"', project_text)
        self.assertTrue(any(
            artifact.path == "res://scripts/signal_bus.gd" and artifact.metadata.get("skill_name") == "manage_signal_bus"
            for artifact in task.artifacts
        ))

    def test_signal_wiring_records_skill_result_contract(self):
        task = self.router.execute(
            "连接信号 score_changed 到 res://scripts/ui.gd 的函数 _on_score_changed",
            confirm=True,
        )

        script_text = (self.project_dir / "scripts" / "ui.gd").read_text(encoding="utf-8")
        self.assertEqual(task.status, TaskStatus.SUCCESS)
        self.assertEqual(task.context["last_skill_result"]["skill_name"], "wire_signal_connection")
        self.assertEqual(task.context["last_skill_result"]["validation"]["passed"], True)
        self.assertTrue(task.context["last_skill_result"]["rollback"]["available"])
        self.assertIn("SignalBus.score_changed.connect(_on_score_changed)", script_text)
        self.assertIn("func _on_score_changed(args = None):", script_text)
        self.assertTrue(any(
            artifact.path == "res://scripts/ui.gd" and artifact.metadata.get("skill_name") == "wire_signal_connection"
            for artifact in task.artifacts
        ))

    def test_dialogue_skill_records_skill_result_contract_via_code_role(self):
        task = self.router.execute(
            '生成对话系统 intro_story，并显示“你好”“再见”',
            confirm=True,
        )

        dialogue_path = self.project_dir / "scripts" / "intro_story_controller.gd"
        self.assertEqual(task.status, TaskStatus.SUCCESS)
        self.assertEqual(task.steps[0].role, "code_generator")
        self.assertEqual(task.context["last_skill_result"]["skill_name"], "generate_dialogue_system")
        self.assertEqual(task.context["last_skill_result"]["validation"]["passed"], True)
        self.assertTrue(dialogue_path.exists())
        self.assertIn("var dialogue_data =", dialogue_path.read_text(encoding="utf-8"))
        self.assertTrue(any(
            artifact.path == "res://scripts/intro_story_controller.gd" and artifact.metadata.get("skill_name") == "generate_dialogue_system"
            for artifact in task.artifacts
        ))

    def test_animation_skill_records_skill_result_contract_via_code_role(self):
        task = self.router.execute(
            "给 res://scripts/ui.gd 添加淡入动画",
            confirm=True,
        )

        script_text = (self.project_dir / "scripts" / "ui.gd").read_text(encoding="utf-8")
        self.assertEqual(task.status, TaskStatus.SUCCESS)
        self.assertEqual(task.steps[0].role, "code_generator")
        self.assertEqual(task.context["last_skill_result"]["skill_name"], "apply_tween_animation")
        self.assertEqual(task.context["last_skill_result"]["validation"]["passed"], True)
        self.assertTrue(task.context["last_skill_result"]["rollback"]["available"])
        self.assertIn("func play_fade_in():", script_text)
        self.assertTrue(any(
            artifact.path == "res://scripts/ui.gd" and artifact.metadata.get("skill_name") == "apply_tween_animation"
            for artifact in task.artifacts
        ))

    def test_quick_capture_records_skill_result_contract_via_tester_role(self):
        task = self.router.execute(
            "截图当前场景",
            context={"scene_path": "res://scenes/main_scene.tscn"},
            confirm=True,
        )

        self.assertEqual(task.status, TaskStatus.SUCCESS)
        self.assertEqual(task.steps[0].role, "tester")
        self.assertEqual(task.context["last_skill_result"]["skill_name"], "quick_capture_scene")
        self.assertEqual(task.context["last_skill_result"]["validation"]["passed"], True)
        screenshot_artifact = next(artifact for artifact in task.artifacts if artifact.type == "screenshot")
        self.assertTrue(Path(screenshot_artifact.path).exists())
        self.assertEqual(screenshot_artifact.metadata.get("skill_name"), "quick_capture_scene")

    def test_quick_capture_uses_editor_state_snapshot_before_headless(self):
        task = self.router.execute(
            "截图当前场景",
            context={
                "scene_path": "res://scenes/main_scene.tscn",
                "editor_state": {"screenshot": base64.b64encode(b"fake-editor-jpg").decode("ascii")},
            },
            confirm=True,
        )

        self.assertEqual(task.status, TaskStatus.SUCCESS)
        self.assertEqual(task.context["quick_capture_mode"], "editor_state")
        screenshot_artifact = next(artifact for artifact in task.artifacts if artifact.type == "screenshot")
        self.assertEqual(Path(screenshot_artifact.path).read_bytes(), b"fake-editor-jpg")
        self.assertEqual(screenshot_artifact.metadata.get("capture_mode"), "editor_state")

    def test_ai_skill_records_skill_result_contract_via_ai_role_fallback(self):
        task = self.router.execute(
            "为 Enemy 生成 AI 脚本，包含 idle chase attack 状态",
            confirm=True,
        )

        ai_path = self.project_dir / "scripts" / "enemy_ai.gd"
        self.assertEqual(task.status, TaskStatus.SUCCESS)
        self.assertEqual(task.steps[0].role, "ai_controller")
        self.assertEqual(task.context["last_skill_result"]["skill_name"], "generate_ai_behavior")
        self.assertEqual(task.context["last_skill_result"]["validation"]["passed"], True)
        self.assertTrue(ai_path.exists())
        self.assertIn("enum STATE", ai_path.read_text(encoding="utf-8"))
        self.assertTrue(any(
            artifact.path == "res://scripts/enemy_ai.gd" and artifact.metadata.get("skill_name") == "generate_ai_behavior"
            for artifact in task.artifacts
        ))

    def test_scenario_chain_test_records_skill_result_contract(self):
        self.router.blueprint_manager.blueprint.scene_topology = [
            {"from": "boot", "trigger": "start", "to": "main"},
            {"from": "main", "trigger": "boss_gate", "to": "boss"},
        ]

        task = self.router.execute("测试流程", confirm=True)

        self.assertEqual(task.status, TaskStatus.SUCCESS)
        self.assertEqual(task.context["last_skill_result"]["skill_name"], "run_scenario_chain_test")
        self.assertEqual(task.context["last_skill_result"]["validation"]["passed"], True)
        self.assertTrue(any(
            artifact.type == "test_script" and artifact.metadata.get("skill_name") == "run_scenario_chain_test"
            for artifact in task.artifacts
        ))

    def test_auto_debug_records_skill_result_contract_via_tester_role(self):
        broken_script = self.project_dir / "scripts" / "broken.gd"
        broken_script.write_text(
            "extends Node\n\nfunc _ready():\n\tmissing_symbol()\n",
            encoding="utf-8",
        )
        cli = self.router.roles["tester"].godot_cli
        cli.run_scene = lambda scene_path: ToolResult(
            True,
            "场景运行结束",
            data={
                "stdout": "SCRIPT ERROR: Invalid call. Nonexistent function 'missing_symbol' in base 'Node'.\n At: res://scripts/broken.gd:3\n",
                "stderr": "",
            },
        )

        task = self.router.execute("调试 res://scenes/main_scene.tscn 并修复", confirm=True)

        self.assertEqual(task.status, TaskStatus.FAILED)
        self.assertEqual(task.steps[0].role, "tester")
        self.assertEqual(task.context["last_skill_result"]["skill_name"], "auto_debug_runtime")
        self.assertEqual(task.context["last_skill_result"]["validation"]["passed"], False)
        self.assertTrue(any(
            artifact.type == "report" and artifact.metadata.get("skill_name") == "auto_debug_runtime"
            for artifact in task.artifacts
        ))

    def test_logic_audit_records_skill_result_contract_via_tester_role(self):
        (self.project_dir / "scripts" / "signal_bus.gd").write_text(
            "extends Node\nsignal score_changed(new_score)\n",
            encoding="utf-8",
        )
        (self.project_dir / "scripts" / "hud.gd").write_text(
            "extends Control\n\nfunc _ready():\n\tSignalBus.missing_signal.connect(_on_missing_signal)\n",
            encoding="utf-8",
        )
        (self.project_dir / "scripts" / "broken_syntax.gd").write_text(
            "extends Node\nfunc _ready()\n\tpass\n",
            encoding="utf-8",
        )
        cli = self.router.roles["tester"].godot_cli
        original_run_headless_script = cli.run_headless_script

        def patched_run_headless_script(script_content):
            if "broken_syntax.gd" in script_content:
                return ToolResult(False, "执行失败", error="Parse Error: expected ':' after function signature")
            return original_run_headless_script(script_content)

        cli.run_headless_script = patched_run_headless_script

        task = self.router.execute("逻辑审计", confirm=True)

        self.assertEqual(task.status, TaskStatus.FAILED)
        self.assertEqual(task.steps[0].role, "tester")
        self.assertEqual(task.context["last_skill_result"]["skill_name"], "audit_logic_errors")
        self.assertEqual(task.context["last_skill_result"]["validation"]["passed"], False)
        report_artifact = next(artifact for artifact in task.artifacts if artifact.type == "report")
        self.assertEqual(report_artifact.metadata.get("skill_name"), "audit_logic_errors")
        self.assertIn("[BROKEN_SIGNAL]", report_artifact.content)
        self.assertIn("[SYNTAX]", report_artifact.content)

    def test_resource_audit_records_skill_result_contract_via_resource_manager(self):
        assets_dir = self.project_dir / "assets"
        assets_dir.mkdir(parents=True, exist_ok=True)
        (assets_dir / "Bad Name.png").write_text("mock", encoding="utf-8")

        task = self.router.execute("审计项目资源命名", confirm=True)

        self.assertEqual(task.status, TaskStatus.SUCCESS)
        self.assertEqual(task.steps[0].role, "resource_manager")
        self.assertEqual(task.context["last_skill_result"]["skill_name"], "audit_godot_resources")
        self.assertEqual(task.context["last_skill_result"]["validation"]["passed"], False)
        report_artifact = next(artifact for artifact in task.artifacts if artifact.type == "report")
        self.assertEqual(report_artifact.metadata.get("skill_name"), "audit_godot_resources")

    def test_resource_fix_preview_records_skill_result_contract_via_resource_manager(self):
        assets_dir = self.project_dir / "assets"
        assets_dir.mkdir(parents=True, exist_ok=True)
        (assets_dir / "Bad Name.png").write_text("mock", encoding="utf-8")

        task = self.router.execute("预览修复项目资源命名", confirm=True)

        self.assertEqual(task.status, TaskStatus.SUCCESS)
        self.assertEqual(task.steps[0].role, "resource_manager")
        self.assertEqual(task.context["last_skill_result"]["skill_name"], "preview_resource_audit_fixes")
        self.assertEqual(task.context["last_skill_result"]["validation"]["passed"], False)
        fix_report = next(artifact for artifact in task.artifacts if artifact.type == "fix_report")
        self.assertEqual(fix_report.metadata.get("skill_name"), "preview_resource_audit_fixes")

    def test_resource_fix_apply_records_skill_result_contract_via_resource_manager(self):
        assets_dir = self.project_dir / "assets"
        assets_dir.mkdir(parents=True, exist_ok=True)
        (assets_dir / "Bad Name.png").write_text("mock", encoding="utf-8")

        task = self.router.execute("修复项目资源命名", confirm=True)

        self.assertEqual(task.status, TaskStatus.SUCCESS)
        self.assertEqual(task.steps[0].role, "resource_manager")
        self.assertEqual(task.context["last_skill_result"]["skill_name"], "apply_resource_audit_fixes")
        self.assertTrue((assets_dir / "bad_name.png").exists())
        fix_report = next(artifact for artifact in task.artifacts if artifact.type == "fix_report")
        self.assertEqual(fix_report.metadata.get("skill_name"), "apply_resource_audit_fixes")

    def test_self_heal_records_skill_result_contract_and_plan_artifact(self):
        self.router.blueprint_manager.add_feature(Feature(
            name="MissingMovement",
            description="Missing generated movement script",
            files=["res://scripts/missing_movement.gd"],
            creation_skill="generate_movement_script",
            creation_params={"script_name": "missing_movement.gd", "is_3d": False},
        ))

        task = self.router.execute("自愈项目", confirm=True)

        self.assertEqual(task.status, TaskStatus.SUCCESS)
        self.assertTrue(any(run["skill_name"] == "self_heal_project" for run in task.context["skill_runs"]))
        self.assertTrue(any(
            artifact.type == "plan" and artifact.metadata.get("skill_name") == "self_heal_project"
            for artifact in task.artifacts
        ))

    def test_plan_feature_records_skill_result_contract(self):
        task, result = self._run_skill_directly(
            "plan_game_feature",
            "规划功能 JumpSystem",
            {
                "feature_name": "JumpSystem",
                "description": "Player jump loop",
                "dependencies": ["MovementSystem"],
            },
        )

        self.assertTrue(result.success)
        self.assertEqual(task.context["last_skill_result"]["skill_name"], "plan_game_feature")
        self.assertEqual(task.context["last_skill_result"]["validation"]["passed"], True)
        self.assertIn("JumpSystem", self.router.blueprint_manager.blueprint.features)

    def test_define_game_flow_records_skill_result_contract(self):
        task, result = self._run_skill_directly(
            "define_game_flow",
            "定义游戏流程",
            {
                "from_scene": "boot",
                "trigger": "start",
                "to_scene": "main",
            },
        )

        self.assertTrue(result.success)
        self.assertEqual(task.context["last_skill_result"]["skill_name"], "define_game_flow")
        self.assertEqual(task.context["last_skill_result"]["validation"]["passed"], True)
        self.assertEqual(self.router.blueprint_manager.blueprint.scene_topology[-1]["to"], "main")

    def test_set_ui_style_records_skill_result_contract(self):
        task, result = self._run_skill_directly(
            "set_ui_style",
            "设置 UI 风格",
            {
                "primary_color": "#22c55e",
                "corner_radius": 12,
                "font_size": 18,
            },
        )

        self.assertTrue(result.success)
        self.assertEqual(task.context["last_skill_result"]["skill_name"], "set_ui_style")
        self.assertEqual(task.context["last_skill_result"]["validation"]["passed"], True)
        self.assertEqual(self.router.blueprint_manager.blueprint.ui_styles["primary_color"], "#22c55e")

    def test_export_blueprint_doc_records_skill_result_contract(self):
        output_name = "BLUEPRINT_TEST.md"
        output_path = self.project_dir / output_name
        output_path.write_text("old", encoding="utf-8")

        task, result = self._run_skill_directly(
            "export_blueprint_doc",
            "导出报告",
            {"file_name": output_name},
        )

        self.assertTrue(result.success)
        self.assertEqual(task.context["last_skill_result"]["skill_name"], "export_blueprint_doc")
        self.assertEqual(task.context["last_skill_result"]["validation"]["passed"], True)
        self.assertTrue(output_path.exists())
        self.assertTrue(any(
            artifact.type == "report" and artifact.metadata.get("skill_name") == "export_blueprint_doc"
            for artifact in task.artifacts
        ))
        self.assertTrue(task.context["last_skill_result"]["rollback"]["available"])

    def test_audit_project_records_skill_result_contract(self):
        self.router.blueprint_manager.add_feature(Feature(
            name="MissingFeature",
            description="Missing file",
            files=["res://scripts/missing_feature.gd"],
            creation_skill="generate_movement_script",
            creation_params={"script_name": "missing_feature.gd", "is_3d": False},
        ))

        task, result = self._run_skill_directly(
            "audit_project_consistency",
            "检查进度",
            {},
        )

        self.assertTrue(result.success)
        self.assertEqual(task.context["last_skill_result"]["skill_name"], "audit_project_consistency")
        self.assertEqual(task.context["last_skill_result"]["validation"]["passed"], False)
        report_artifact = next(artifact for artifact in task.artifacts if artifact.type == "report")
        self.assertEqual(report_artifact.metadata.get("skill_name"), "audit_project_consistency")

    def test_apply_pattern_records_skill_result_contract_and_plan_artifact(self):
        task, result = self._run_skill_directly(
            "apply_design_pattern",
            "应用设计模式 HealthSystem",
            {
                "pattern_name": "HealthSystem",
                "overrides": {"scene_name": "BossHealth"},
            },
        )

        self.assertTrue(result.success)
        self.assertEqual(task.context["last_skill_result"]["skill_name"], "apply_design_pattern")
        self.assertEqual(task.context["last_skill_result"]["validation"]["passed"], True)
        self.assertGreater(len(task.context.get("pending_pattern_steps") or []), 0)
        self.assertTrue(any(
            artifact.type == "plan" and artifact.metadata.get("skill_name") == "apply_design_pattern"
            for artifact in task.artifacts
        ))

    def test_blueprint_snapshot_records_skill_result_contract(self):
        task, result = self._run_skill_directly(
            "manage_blueprint_snapshots",
            "保存快照",
            {"action": "save", "label": "test"},
        )

        self.assertTrue(result.success)
        self.assertEqual(task.context["last_skill_result"]["skill_name"], "manage_blueprint_snapshots")
        self.assertEqual(task.context["last_skill_result"]["validation"]["passed"], True)
        self.assertTrue(any(
            artifact.type == "snapshot" and artifact.metadata.get("skill_name") == "manage_blueprint_snapshots"
            for artifact in task.artifacts
        ))


if __name__ == "__main__":
    unittest.main()

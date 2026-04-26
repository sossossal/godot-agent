"""
Godot Agent 单元测试 (隔离完善版)
"""

import unittest
import sys
import os
import re
import tempfile
import shutil
from pathlib import Path
from unittest.mock import patch

# 添加项目路径
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

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


class GateAwareGodotCLI(MockGodotCLI):
    scene_load_ms = 320
    fps = 58.0
    memory_peak_mb = 96.0
    screenshot_diff_ratio = 0.01
    screenshot_bytes = b"fake-gate-png"

    def __init__(self, executable_path=None, project_path=None):
        super().__init__(executable_path=executable_path, project_path=project_path)
        self.export_calls = []

    def run_headless(self, script_path, args=None):
        script_content = Path(script_path).read_text(encoding="utf-8")
        stdout_lines = [
            f"GODOT_AGENT_SCENE_LOAD_MS={self.scene_load_ms}",
            f"GODOT_AGENT_FPS={self.fps:.2f}",
            f"GODOT_AGENT_MEMORY_PEAK_MB={self.memory_peak_mb:.2f}",
        ]
        screenshot_match = re.search(r'save_png\("([^"]+)"\)', script_content)
        if screenshot_match:
            screenshot_path = Path(screenshot_match.group(1))
            screenshot_path.parent.mkdir(parents=True, exist_ok=True)
            screenshot_path.write_bytes(self.screenshot_bytes)
            stdout_lines.append(f"GODOT_AGENT_SCREENSHOT_PATH={screenshot_path.as_posix()}")
            if self.screenshot_diff_ratio is not None:
                stdout_lines.append(f"GODOT_AGENT_SCREENSHOT_DIFF_RATIO={self.screenshot_diff_ratio:.4f}")
        return ToolResult(
            True,
            "OK",
            data={"stdout": "\n".join(stdout_lines) + "\n", "stderr": ""},
        )

    def export_project(self, preset_name, output_path, release=True):
        self.export_calls.append((preset_name, output_path, release))
        return super().export_project(preset_name, output_path, release=release)


class SlowGateGodotCLI(GateAwareGodotCLI):
    scene_load_ms = 3200


class LowFpsGateGodotCLI(GateAwareGodotCLI):
    fps = 12.0


class HighMemoryGateGodotCLI(GateAwareGodotCLI):
    memory_peak_mb = 640.0


class HighDiffGateGodotCLI(GateAwareGodotCLI):
    screenshot_diff_ratio = 0.35


class TrackingGodotCLI(MockGodotCLI):
    def __init__(self, executable_path=None, project_path=None):
        super().__init__(executable_path=executable_path, project_path=project_path)
        self.last_scene_path = None

    def run_scene(self, scene_path):
        self.last_scene_path = scene_path
        return ToolResult(True, "OK")


class SceneTrackingGodotCLI(MockGodotCLI):
    def __init__(self, executable_path=None, project_path=None):
        super().__init__(executable_path=executable_path, project_path=project_path)
        self.execute_editor_script_calls = 0

    def execute_editor_script(self, script_content):
        self.execute_editor_script_calls += 1
        return ToolResult(True, "OK")


class HealingAwareCodeRole:
    def get_capabilities(self):
        return ["生成并重试代码"]

    def __init__(self):
        self.prompts = []

    def execute(self, task):
        self.prompts.append(task.prompt)
        if not task.context.get("healed"):
            task.status = TaskStatus.FAILED
            task.add_log("ERROR: No export template found")
            return task
        task.status = TaskStatus.SUCCESS
        task.add_log("SUCCESS: 原始步骤在自愈后重试成功")
        return task


class HealingResourceRole:
    def get_capabilities(self):
        return ["执行自愈修复"]

    def __init__(self):
        self.prompts = []

    def execute(self, task):
        self.prompts.append(task.prompt)
        task.context["healed"] = True
        task.status = TaskStatus.SUCCESS
        task.add_log("SUCCESS: 自愈步骤执行成功")
        return task

class TestGodotAgentRouter(unittest.TestCase):
    @patch('agent_system.router.GodotCLI', MockGodotCLI)
    def setUp(self):
        from agent_system.router import GodotAgentRouter
        # 使用临时历史文件以确保测试隔离
        self.test_hist_file = tempfile.mktemp(suffix=".json")
        self.agent = GodotAgentRouter(history_file=self.test_hist_file)
    
    def tearDown(self):
        if os.path.exists(self.test_hist_file):
            os.remove(self.test_hist_file)

    def test_router_initialization(self):
        self.assertEqual(len(self.agent.roles), 5)
    
    def test_execute_flow(self):
        task = self.agent.execute("生成代码", confirm=True)
        self.assertEqual(task.status, TaskStatus.SUCCESS)
        self.assertGreater(len(task.steps), 0)

    def test_export_routes_to_resource_manager(self):
        task = self.agent.plan("导出 Web 项目")
        self.assertEqual(task.steps[0].role, "resource_manager")

    def test_validate_routes_to_tester(self):
        task = self.agent.execute("验证玩家跳跃功能", confirm=True)
        self.assertEqual(task.status, TaskStatus.SUCCESS)
        self.assertEqual(task.steps[0].role, "tester")
        self.assertEqual(task.context["last_skill_result"]["skill_name"], "smoke_test_scene")
        self.assertEqual(task.context["last_skill_result"]["validation"]["passed"], True)

    def test_movement_script_records_skill_result_contract(self):
        task = self.agent.execute("生成一个玩家移动控制脚本", confirm=True)
        self.assertEqual(task.status, TaskStatus.SUCCESS)
        self.assertEqual(task.steps[0].role, "code_generator")
        self.assertEqual(task.context["last_skill_result"]["skill_name"], "generate_movement_script")
        self.assertEqual(task.context["last_skill_result"]["validation"]["passed"], True)
        self.assertEqual(task.context["skill_runs"][-1]["skill_name"], "generate_movement_script")
        self.assertTrue(any(
            artifact.type == "script" and artifact.metadata.get("skill_name") == "generate_movement_script"
            for artifact in task.artifacts
        ))

    def test_attach_script_records_skill_result_contract(self):
        task = self.agent.execute(
            "给 Player 节点挂载 res://scripts/player.gd 脚本",
            context={"editor_state": {"is_active": True}, "scene_path": "res://scenes/main_scene.tscn"},
            confirm=True
        )
        self.assertEqual(task.status, TaskStatus.WAITING_ACK)
        self.assertEqual(task.steps[0].role, "developer")
        self.assertEqual(task.context["last_skill_result"]["skill_name"], "attach_script_to_node")
        self.assertEqual(task.context["last_skill_result"]["validation"]["passed"], True)
        self.assertTrue(any(
            artifact.type == "editor_script" and artifact.metadata.get("skill_name") == "attach_script_to_node"
            for artifact in task.artifacts
        ))

    @patch('agent_system.router.GodotCLI', TrackingGodotCLI)
    def test_tester_uses_current_scene_from_editor_state_when_prompt_has_no_path(self):
        from agent_system.router import GodotAgentRouter

        project_dir = project_root / "tests" / ".tmp_current_scene_test"
        shutil.rmtree(project_dir, ignore_errors=True)
        try:
            scenes_dir = project_dir / "scenes"
            scenes_dir.mkdir(parents=True, exist_ok=True)
            (scenes_dir / "main_scene.tscn").write_text(
                '[gd_scene load_steps=1 format=3 uid="uid://main_scene_uid"]\n'
                '\n'
                '[node name="main_scene" type="Node2D"]\n',
                encoding="utf-8"
            )

            router = GodotAgentRouter(godot_project_path=str(project_dir), history_file=self.test_hist_file)
            task = router.execute(
                "测试当前场景",
                context={
                    "editor_state": {
                        "current_scene": "res://scenes/main_scene.tscn"
                    }
                },
                confirm=True
            )

            self.assertEqual(task.status, TaskStatus.SUCCESS)
            self.assertEqual(task.steps[0].role, "tester")
            self.assertEqual(task.context.get("scene_path"), "res://scenes/main_scene.tscn")
            self.assertEqual(task.context.get("scene_path_source"), "editor_state")
            self.assertEqual(task.context.get("test_scene_path"), "res://scenes/main_scene.tscn")
            self.assertEqual(task.context.get("test_scene_source"), "context")
            self.assertEqual(router.roles["tester"].godot_cli.last_scene_path, "res://scenes/main_scene.tscn")
        finally:
            shutil.rmtree(project_dir, ignore_errors=True)

    def test_developer_prefers_selected_node_paths_for_live_injection(self):
        task = self.agent.execute(
            "在当前节点下添加一个 Sprite2D 节点",
            context={
                "editor_state": {
                    "is_active": True,
                    "selected_nodes": ["weapon_slot"],
                    "selected_node_paths": ["player/weapon_slot"],
                }
            },
            confirm=True
        )
        self.assertEqual(task.status, TaskStatus.WAITING_ACK)
        self.assertEqual(task.steps[0].role, "developer")
        self.assertEqual(task.steps[0].status, TaskStatus.WAITING_ACK)
        editor_script = next(artifact for artifact in task.artifacts if artifact.type == "editor_script")
        self.assertIn('get_node_or_null(NodePath("player/weapon_slot"))', editor_script.content)
        self.assertNotIn('find_child("weapon_slot"', editor_script.content)

    @patch('agent_system.router.GodotCLI', SceneTrackingGodotCLI)
    def test_create_scene_uses_editor_script_when_editor_is_online(self):
        from agent_system.router import GodotAgentRouter

        router = GodotAgentRouter(history_file=self.test_hist_file)
        task = router.execute(
            "创建一个名为 LiveTestScene 的 2D 场景",
            context={"editor_state": {"is_active": True}},
            confirm=True
        )

        self.assertEqual(task.status, TaskStatus.WAITING_ACK)
        self.assertEqual(task.steps[0].role, "developer")
        self.assertEqual(task.steps[0].status, TaskStatus.WAITING_ACK)
        self.assertEqual(task.context.get("scene_path"), "res://scenes/LiveTestScene.tscn")
        self.assertEqual(task.context.get("scene_path_source"), "developer")
        self.assertEqual(router.roles["developer"].godot_cli.execute_editor_script_calls, 0)
        self.assertEqual(task.context["last_skill_result"]["skill_name"], "create_godot_scene")
        self.assertEqual(task.context["last_skill_result"]["validation"]["passed"], True)
        editor_script = next(artifact for artifact in task.artifacts if artifact.type == "editor_script")
        self.assertIn('open_scene_from_path(path)', editor_script.content)
        self.assertEqual(editor_script.metadata.get("skill_name"), "create_godot_scene")
        self.assertTrue(any(artifact.type == "scene" and artifact.path == "res://scenes/LiveTestScene.tscn" for artifact in task.artifacts))

    @patch('agent_system.router.GodotCLI', MockGodotCLI)
    def test_e2e_test_generates_headless_script_and_optional_screenshot_artifact(self):
        from agent_system.router import GodotAgentRouter

        project_dir = project_root / "tests" / ".tmp_e2e_test"
        shutil.rmtree(project_dir, ignore_errors=True)
        try:
            scenes_dir = project_dir / "scenes"
            scenes_dir.mkdir(parents=True, exist_ok=True)
            (scenes_dir / "main_scene.tscn").write_text(
                '[gd_scene load_steps=1 format=3 uid="uid://main_scene_uid"]\n'
                '\n'
                '[node name="main_scene" type="Node2D"]\n',
                encoding="utf-8"
            )

            router = GodotAgentRouter(godot_project_path=str(project_dir), history_file=self.test_hist_file)
            task = router.execute("端到端测试 res://scenes/main_scene.tscn 并向右跳跃后截图", confirm=True)

            self.assertEqual(task.status, TaskStatus.SUCCESS)
            self.assertEqual(task.steps[0].role, "tester")
            self.assertEqual(task.context.get("e2e_scene_path"), "res://scenes/main_scene.tscn")
            self.assertEqual(task.context.get("e2e_playback_action_count"), 2)
            self.assertTrue(task.context.get("e2e_screenshot_requested"))
            self.assertEqual(task.context["last_skill_result"]["skill_name"], "e2e_test_scene")
            self.assertEqual(task.context["last_skill_result"]["validation"]["passed"], True)
            harness = next(artifact for artifact in task.artifacts if artifact.type == "test_script")
            self.assertIn('load("res://scenes/main_scene.tscn")', harness.content)
            self.assertIn('Input.action_press("ui_right")', harness.content)
            self.assertIn('Input.action_press("ui_accept")', harness.content)
            self.assertEqual(harness.metadata.get("skill_name"), "e2e_test_scene")
            self.assertTrue(any(artifact.type == "screenshot" for artifact in task.artifacts))
        finally:
            shutil.rmtree(project_dir, ignore_errors=True)

    @patch('agent_system.router.GodotCLI', MockGodotCLI)
    def test_e2e_test_can_materialize_screenshot_from_editor_state_snapshot(self):
        from agent_system.router import GodotAgentRouter

        project_dir = project_root / "tests" / ".tmp_e2e_editor_snapshot"
        shutil.rmtree(project_dir, ignore_errors=True)
        try:
            scene_file = project_dir / "sandbox_main.tscn"
            project_dir.mkdir(parents=True, exist_ok=True)
            scene_file.write_text(
                '[gd_scene load_steps=1 format=3 uid="uid://snapshot_scene_uid"]\n'
                '\n'
                '[node name="sandbox_main" type="Node2D"]\n',
                encoding="utf-8"
            )

            router = GodotAgentRouter(godot_project_path=str(project_dir), history_file=self.test_hist_file)
            task = router.execute(
                "端到端测试 res://sandbox_main.tscn 并截图",
                context={
                    "editor_state": {
                        "is_active": True,
                        "screenshot": "ZmFrZS1qcGVn"
                    }
                },
                confirm=True
            )

            self.assertEqual(task.status, TaskStatus.SUCCESS)
            self.assertEqual(task.context.get("e2e_screenshot_mode"), "editor_state")
            self.assertEqual(task.context["last_skill_result"]["skill_name"], "e2e_test_scene")
            screenshot_artifact = next(artifact for artifact in task.artifacts if artifact.type == "screenshot")
            self.assertTrue(Path(screenshot_artifact.path).exists())
            self.assertEqual(screenshot_artifact.metadata.get("skill_name"), "e2e_test_scene")
            self.assertEqual(Path(screenshot_artifact.path).read_bytes(), b"fake-jpeg")
        finally:
            screenshot_dir = project_root / "logs" / "test_artifacts"
            for screenshot_file in screenshot_dir.glob("e2e_capture_*.jpg"):
                screenshot_file.unlink(missing_ok=True)
            shutil.rmtree(project_dir, ignore_errors=True)

    def test_export_flow_sets_release_url(self):
        task = self.agent.execute("导出 Web 项目", confirm=True)
        self.assertEqual(task.status, TaskStatus.SUCCESS)
        self.assertEqual(task.steps[0].role, "resource_manager")
        self.assertEqual(task.context.get("release_url"), "/portal/dist/index.html")
        self.assertTrue(task.context.get("release_build_id", "").startswith("web-preview-"))
        self.assertTrue(task.context.get("release_version", "").startswith("0.1.0-preview+"))
        self.assertEqual(task.context.get("release_channel"), "preview")
        self.assertTrue(task.context.get("release_notes_path", "").endswith("release_notes.md"))
        self.assertTrue(task.context.get("release_manifest_path", "").endswith("release_manifest.json"))
        self.assertEqual(task.context["contract_versions"]["quality_gate"], "1.0")
        self.assertEqual(task.context["contract_versions"]["release_summary"], "1.0")
        self.assertEqual(task.context["contract_versions"]["skill_result"], "1.0")
        self.assertEqual(task.context["last_skill_result"]["skill_name"], "export_godot_project")
        self.assertEqual(task.context["last_skill_result"]["quality_gate"]["passed"], True)
        self.assertIn("build_id", task.context.get("release_summary", {}))
        self.assertEqual(task.context["release_summary"]["schema_version"], "1.0")
        self.assertEqual(task.context["release_summary"]["quality_gate"]["schema_version"], "1.0")
        self.assertTrue(any(artifact.name == "Release Notes" for artifact in task.artifacts))
        self.assertTrue(any(artifact.name == "Release Manifest" for artifact in task.artifacts))
        self.assertTrue(any(
            artifact.type == "release"
            and artifact.metadata.get("build_id") == task.context.get("release_build_id")
            and artifact.metadata.get("skill_name") == "export_godot_project"
            for artifact in task.artifacts
        ))

    @patch('agent_system.router.GodotCLI', GateAwareGodotCLI)
    def test_preview_export_records_quality_gate_summary(self):
        from agent_system.router import GodotAgentRouter

        project_dir = project_root / "tests" / ".tmp_preview_release_gate"
        shutil.rmtree(project_dir, ignore_errors=True)
        try:
            scenes_dir = project_dir / "scenes"
            scenes_dir.mkdir(parents=True, exist_ok=True)
            (scenes_dir / "main_scene.tscn").write_text(
                '[gd_scene load_steps=1 format=3 uid="uid://preview_gate_scene"]\n\n[node name="Main" type="Node2D"]\n',
                encoding="utf-8",
            )

            router = GodotAgentRouter(godot_project_path=str(project_dir), history_file=self.test_hist_file)
            task = router.execute(
                "发布试玩 Web 项目",
                context={"feature_status": "pending_acceptance", "performance_budget": {"max_scene_load_ms": 1000}},
                confirm=True,
            )

            self.assertEqual(task.status, TaskStatus.SUCCESS)
            self.assertTrue(task.context["release_quality_gate"]["passed"])
            self.assertTrue(any(check["name"] == "smoke_test" and check["status"] == "passed" for check in task.context["release_quality_gate"]["checks"]))
            self.assertTrue(any(check["name"] == "performance_budget" and check["status"] == "passed" for check in task.context["release_quality_gate"]["checks"]))
            self.assertTrue(any(artifact.name == "QA Gate Report" for artifact in task.artifacts))
        finally:
            shutil.rmtree(project_dir, ignore_errors=True)

    @patch('agent_system.router.GodotCLI', GateAwareGodotCLI)
    def test_release_export_blocks_when_feature_not_approved(self):
        from agent_system.router import GodotAgentRouter

        project_dir = project_root / "tests" / ".tmp_release_feature_gate"
        shutil.rmtree(project_dir, ignore_errors=True)
        try:
            scenes_dir = project_dir / "scenes"
            scenes_dir.mkdir(parents=True, exist_ok=True)
            (scenes_dir / "main_scene.tscn").write_text(
                '[gd_scene load_steps=1 format=3 uid="uid://release_gate_scene"]\n\n[node name="Main" type="Node2D"]\n',
                encoding="utf-8",
            )

            router = GodotAgentRouter(godot_project_path=str(project_dir), history_file=self.test_hist_file)
            task = router.execute(
                "发布正式版 Web 项目",
                context={"feature_status": "pending_acceptance", "performance_budget": {"max_scene_load_ms": 1000}},
                confirm=True,
            )

            self.assertEqual(task.status, TaskStatus.FAILED)
            self.assertFalse(task.context["release_quality_gate"]["passed"])
            self.assertIn("feature_status", task.context["release_quality_gate"]["blocked_checks"])
            self.assertEqual(router.roles["resource_manager"].godot_cli.export_calls, [])
        finally:
            shutil.rmtree(project_dir, ignore_errors=True)

    @patch('agent_system.router.GodotCLI', SlowGateGodotCLI)
    def test_qa_export_blocks_when_performance_budget_is_exceeded(self):
        from agent_system.router import GodotAgentRouter

        project_dir = project_root / "tests" / ".tmp_release_perf_gate"
        shutil.rmtree(project_dir, ignore_errors=True)
        try:
            scenes_dir = project_dir / "scenes"
            scenes_dir.mkdir(parents=True, exist_ok=True)
            (scenes_dir / "main_scene.tscn").write_text(
                '[gd_scene load_steps=1 format=3 uid="uid://perf_gate_scene"]\n\n[node name="Main" type="Node2D"]\n',
                encoding="utf-8",
            )

            router = GodotAgentRouter(godot_project_path=str(project_dir), history_file=self.test_hist_file)
            task = router.execute(
                "发布 QA Web 项目",
                context={"feature_status": "approved", "performance_budget": {"max_scene_load_ms": 1000}},
                confirm=True,
            )

            self.assertEqual(task.status, TaskStatus.FAILED)
            self.assertIn("performance_budget", task.context["release_quality_gate"]["blocked_checks"])
            self.assertEqual(router.roles["resource_manager"].godot_cli.export_calls, [])
        finally:
            shutil.rmtree(project_dir, ignore_errors=True)

    @patch('agent_system.router.GodotCLI', GateAwareGodotCLI)
    def test_qa_export_blocks_when_balance_analysis_finds_issues(self):
        from agent_system.router import GodotAgentRouter

        project_dir = project_root / "tests" / ".tmp_release_balance_gate"
        shutil.rmtree(project_dir, ignore_errors=True)
        try:
            scenes_dir = project_dir / "scenes"
            data_tables_dir = project_dir / "data_tables"
            scenes_dir.mkdir(parents=True, exist_ok=True)
            data_tables_dir.mkdir(parents=True, exist_ok=True)
            (scenes_dir / "main_scene.tscn").write_text(
                '[gd_scene load_steps=1 format=3 uid="uid://balance_gate_scene"]\n\n[node name="Main" type="Node2D"]\n',
                encoding="utf-8",
            )
            (data_tables_dir / "enemies.csv").write_text(
                "enemy_id,name,hp,attack,move_speed,loot_table_id\n"
                "slime_elite,Elite Slime,18,12,110,loot_missing\n",
                encoding="utf-8",
            )
            (data_tables_dir / "loot_tables.csv").write_text(
                "loot_id,item_id,drop_rate,quantity\n"
                "loot_common,coin,0.8,2\n"
                "loot_common,gem,0.5,1\n",
                encoding="utf-8",
            )
            (data_tables_dir / "quests.csv").write_text(
                "quest_id,title,description,target_count,reward_gold,next_quest_id\n"
                "quest_intro,清理史莱姆,消灭 2 只史莱姆,2,60,\n",
                encoding="utf-8",
            )

            router = GodotAgentRouter(godot_project_path=str(project_dir), history_file=self.test_hist_file)
            task = router.execute(
                "发布 QA Web 项目",
                context={"feature_status": "approved", "performance_budget": {"max_scene_load_ms": 1000}},
                confirm=True,
            )

            self.assertEqual(task.status, TaskStatus.FAILED)
            self.assertFalse(task.context["release_quality_gate"]["passed"])
            self.assertIn("balance_analysis", task.context["release_quality_gate"]["blocked_checks"])
            self.assertEqual(task.context["balance_analysis"]["schema_version"], "1.0")
            self.assertEqual(task.context["contract_versions"]["balance_analysis"], "1.0")
            self.assertEqual(router.roles["resource_manager"].godot_cli.export_calls, [])
        finally:
            shutil.rmtree(project_dir, ignore_errors=True)

    @patch('agent_system.router.GodotCLI', GateAwareGodotCLI)
    def test_qa_export_blocks_when_telemetry_summary_finds_issues(self):
        from agent_system.router import GodotAgentRouter

        project_dir = project_root / "tests" / ".tmp_release_telemetry_gate"
        shutil.rmtree(project_dir, ignore_errors=True)
        try:
            scenes_dir = project_dir / "scenes"
            telemetry_dir = project_dir / "telemetry"
            sessions_dir = telemetry_dir / "sessions"
            scenes_dir.mkdir(parents=True, exist_ok=True)
            sessions_dir.mkdir(parents=True, exist_ok=True)
            (scenes_dir / "main_scene.tscn").write_text(
                '[gd_scene load_steps=1 format=3 uid="uid://telemetry_gate_scene"]\n\n[node name="Main" type="Node2D"]\n',
                encoding="utf-8",
            )
            (telemetry_dir / "event_catalog.json").write_text(
                '{\n'
                '  "events": [\n'
                '    {\n'
                '      "event_name": "session_start",\n'
                '      "category": "session",\n'
                '      "description": "开始会话",\n'
                '      "privacy_level": "anonymous",\n'
                '      "fields": [{"name": "build_id", "type": "string", "required": true, "pii": false}]\n'
                '    }\n'
                '  ]\n'
                '}\n',
                encoding="utf-8",
            )
            (sessions_dir / "session_001.jsonl").write_text(
                '{"event_name":"session_start","session_id":"s1","timestamp":"2026-04-10T10:00:00Z","payload":{"build_id":"web-preview-1"}}\n'
                '{"event_name":"level_complete","session_id":"s1","timestamp":"2026-04-10T10:01:00Z","payload":{"level_id":"level_01"}}\n',
                encoding="utf-8",
            )

            router = GodotAgentRouter(godot_project_path=str(project_dir), history_file=self.test_hist_file)
            task = router.execute(
                "发布 QA Web 项目",
                context={"feature_status": "approved", "performance_budget": {"max_scene_load_ms": 1000}},
                confirm=True,
            )

            self.assertEqual(task.status, TaskStatus.FAILED)
            self.assertFalse(task.context["release_quality_gate"]["passed"])
            self.assertIn("telemetry_health", task.context["release_quality_gate"]["blocked_checks"])
            self.assertEqual(task.context["telemetry_summary"]["schema_version"], "1.4")
            self.assertEqual(task.context["contract_versions"]["telemetry_summary"], "1.4")
            self.assertEqual(router.roles["resource_manager"].godot_cli.export_calls, [])
        finally:
            shutil.rmtree(project_dir, ignore_errors=True)

    @patch('agent_system.router.GodotCLI', GateAwareGodotCLI)
    def test_qa_export_blocks_telemetry_pii_violations(self):
        from agent_system.router import GodotAgentRouter

        project_dir = project_root / "tests" / ".tmp_release_telemetry_privacy_gate"
        shutil.rmtree(project_dir, ignore_errors=True)
        try:
            scenes_dir = project_dir / "scenes"
            telemetry_dir = project_dir / "telemetry"
            sessions_dir = telemetry_dir / "sessions"
            scenes_dir.mkdir(parents=True, exist_ok=True)
            sessions_dir.mkdir(parents=True, exist_ok=True)
            (scenes_dir / "main_scene.tscn").write_text(
                '[gd_scene load_steps=1 format=3 uid="uid://telemetry_privacy_scene"]\n\n[node name="Main" type="Node2D"]\n',
                encoding="utf-8",
            )
            (telemetry_dir / "event_catalog.json").write_text(
                '{\n'
                '  "events": [\n'
                '    {\n'
                '      "event_name": "session_start",\n'
                '      "category": "session",\n'
                '      "description": "开始会话",\n'
                '      "privacy_level": "anonymous",\n'
                '      "fields": [{"name": "build_id", "type": "string", "required": true, "pii": false}]\n'
                '    }\n'
                '  ]\n'
                '}\n',
                encoding="utf-8",
            )
            (sessions_dir / "session_001.jsonl").write_text(
                '{"event_name":"session_start","session_id":"s1","timestamp":"2026-04-10T10:00:00Z","payload":{"build_id":"web-preview-1","email":"qa@example.com"}}\n',
                encoding="utf-8",
            )

            router = GodotAgentRouter(godot_project_path=str(project_dir), history_file=self.test_hist_file)
            task = router.execute(
                "发布 QA Web 项目",
                context={"feature_status": "approved", "performance_budget": {"max_scene_load_ms": 1000}},
                confirm=True,
            )

            self.assertEqual(task.status, TaskStatus.FAILED)
            self.assertFalse(task.context["release_quality_gate"]["passed"])
            self.assertEqual(task.context["telemetry_summary"]["pii_violation_count"], 1)
            self.assertFalse(task.context["telemetry_summary"]["privacy_gate_passed"])
            telemetry_check = next(
                check for check in task.context["release_quality_gate"]["checks"]
                if check["name"] == "telemetry_health"
            )
            self.assertEqual(telemetry_check["status"], "blocked")
            self.assertEqual(telemetry_check["pii_violation_count"], 1)
            self.assertFalse(task.context["release_quality_gate"]["metrics"]["telemetry_privacy_gate_passed"])
        finally:
            shutil.rmtree(project_dir, ignore_errors=True)

    @patch('agent_system.router.GodotCLI', GateAwareGodotCLI)
    def test_qa_export_records_fps_memory_and_screenshot_diff_metrics(self):
        from agent_system.router import GodotAgentRouter

        project_dir = project_root / "tests" / ".tmp_release_visual_gate"
        shutil.rmtree(project_dir, ignore_errors=True)
        try:
            scenes_dir = project_dir / "scenes"
            qa_dir = project_dir / "qa"
            scenes_dir.mkdir(parents=True, exist_ok=True)
            qa_dir.mkdir(parents=True, exist_ok=True)
            (scenes_dir / "main_scene.tscn").write_text(
                '[gd_scene load_steps=1 format=3 uid="uid://visual_gate_scene"]\n\n[node name="Main" type="Node2D"]\n',
                encoding="utf-8",
            )
            baseline_path = qa_dir / "baseline.png"
            baseline_path.write_bytes(b"baseline")

            router = GodotAgentRouter(godot_project_path=str(project_dir), history_file=self.test_hist_file)
            task = router.execute(
                "发布 QA Web 项目",
                context={
                    "feature_status": "approved",
                    "performance_budget": {
                        "max_scene_load_ms": 1000,
                        "min_fps": 30,
                        "max_memory_peak_mb": 256,
                        "baseline_screenshot_path": str(baseline_path),
                        "max_screenshot_diff_ratio": 0.05,
                    },
                },
                confirm=True,
            )

            self.assertEqual(task.status, TaskStatus.SUCCESS)
            self.assertTrue(task.context["release_quality_gate"]["passed"])
            self.assertEqual(task.context["release_quality_gate"]["metrics"]["scene_load_ms"], 320)
            self.assertEqual(task.context["release_quality_gate"]["metrics"]["fps"], 58.0)
            self.assertEqual(task.context["release_quality_gate"]["metrics"]["memory_peak_mb"], 96.0)
            self.assertTrue(any(check["name"] == "fps_budget" and check["status"] == "passed" for check in task.context["release_quality_gate"]["checks"]))
            self.assertTrue(any(check["name"] == "memory_peak_budget" and check["status"] == "passed" for check in task.context["release_quality_gate"]["checks"]))
            self.assertTrue(any(check["name"] == "screenshot_diff" and check["status"] == "passed" for check in task.context["release_quality_gate"]["checks"]))
            self.assertTrue(any(artifact.type == "screenshot" and artifact.metadata.get("gate") == "quality_gate" for artifact in task.artifacts))
        finally:
            shutil.rmtree(project_dir, ignore_errors=True)

    @patch('agent_system.router.GodotCLI', LowFpsGateGodotCLI)
    def test_qa_export_blocks_when_fps_budget_is_not_met(self):
        from agent_system.router import GodotAgentRouter

        project_dir = project_root / "tests" / ".tmp_release_fps_gate"
        shutil.rmtree(project_dir, ignore_errors=True)
        try:
            scenes_dir = project_dir / "scenes"
            scenes_dir.mkdir(parents=True, exist_ok=True)
            (scenes_dir / "main_scene.tscn").write_text(
                '[gd_scene load_steps=1 format=3 uid="uid://fps_gate_scene"]\n\n[node name="Main" type="Node2D"]\n',
                encoding="utf-8",
            )

            router = GodotAgentRouter(godot_project_path=str(project_dir), history_file=self.test_hist_file)
            task = router.execute(
                "发布 QA Web 项目",
                context={
                    "feature_status": "approved",
                    "performance_budget": {
                        "max_scene_load_ms": 1000,
                        "min_fps": 30,
                    },
                },
                confirm=True,
            )

            self.assertEqual(task.status, TaskStatus.FAILED)
            self.assertIn("fps_budget", task.context["release_quality_gate"]["blocked_checks"])
            self.assertEqual(router.roles["resource_manager"].godot_cli.export_calls, [])
        finally:
            shutil.rmtree(project_dir, ignore_errors=True)

    @patch('agent_system.router.GodotCLI', HighMemoryGateGodotCLI)
    def test_qa_export_blocks_when_memory_peak_budget_is_exceeded(self):
        from agent_system.router import GodotAgentRouter

        project_dir = project_root / "tests" / ".tmp_release_memory_gate"
        shutil.rmtree(project_dir, ignore_errors=True)
        try:
            scenes_dir = project_dir / "scenes"
            scenes_dir.mkdir(parents=True, exist_ok=True)
            (scenes_dir / "main_scene.tscn").write_text(
                '[gd_scene load_steps=1 format=3 uid="uid://memory_gate_scene"]\n\n[node name="Main" type="Node2D"]\n',
                encoding="utf-8",
            )

            router = GodotAgentRouter(godot_project_path=str(project_dir), history_file=self.test_hist_file)
            task = router.execute(
                "发布 QA Web 项目",
                context={
                    "feature_status": "approved",
                    "performance_budget": {
                        "max_scene_load_ms": 1000,
                        "max_memory_peak_mb": 256,
                    },
                },
                confirm=True,
            )

            self.assertEqual(task.status, TaskStatus.FAILED)
            self.assertIn("memory_peak_budget", task.context["release_quality_gate"]["blocked_checks"])
            self.assertEqual(router.roles["resource_manager"].godot_cli.export_calls, [])
        finally:
            shutil.rmtree(project_dir, ignore_errors=True)

    @patch('agent_system.router.GodotCLI', GateAwareGodotCLI)
    def test_qa_export_records_richer_performance_metrics_from_performance_summary(self):
        from agent_system.router import GodotAgentRouter

        project_dir = project_root / "tests" / ".tmp_release_richer_perf_gate"
        shutil.rmtree(project_dir, ignore_errors=True)
        try:
            scenes_dir = project_dir / "scenes"
            scenes_dir.mkdir(parents=True, exist_ok=True)
            (scenes_dir / "main_scene.tscn").write_text(
                '[gd_scene load_steps=1 format=3 uid="uid://richer_perf_gate_scene"]\n\n[node name="Main" type="Node2D"]\n',
                encoding="utf-8",
            )

            router = GodotAgentRouter(godot_project_path=str(project_dir), history_file=self.test_hist_file)
            task = router.execute(
                "发布 QA Web 项目",
                context={
                    "feature_status": "approved",
                    "performance_budget": {
                        "max_scene_load_ms": 1000,
                        "max_draw_call_count": 320,
                        "max_node_count": 220,
                        "max_texture_memory_mb": 128,
                        "max_frame_spike_ms": 18,
                    },
                    "performance_summary": {
                        "passed": True,
                        "scene_path": "res://scenes/main_scene.tscn",
                        "baseline_path": "tests/baselines/performance/main_scene.json",
                        "profile_path": "logs/test_artifacts/performance_profile_main_scene.json",
                        "checks": [
                            {"name": "draw_call_budget", "status": "passed", "message": "Draw Call 280 / 预算 320"},
                            {"name": "node_count_budget", "status": "passed", "message": "节点数 180 / 预算 220"},
                            {"name": "texture_memory_budget", "status": "passed", "message": "纹理内存 96MB / 预算 128MB"},
                            {"name": "frame_spike_budget", "status": "passed", "message": "帧尖峰 12ms / 预算 18ms"},
                            {"name": "draw_call_regression", "status": "passed", "message": "Draw Call 相比基线改善"},
                        ],
                        "metrics": {
                            "draw_call_count": 280,
                            "node_count": 180,
                            "texture_memory_mb": 96,
                            "frame_spike_ms": 12,
                        },
                        "budgets": {
                            "max_draw_call_count": 320,
                            "max_node_count": 220,
                            "max_texture_memory_mb": 128,
                            "max_frame_spike_ms": 18,
                        },
                    },
                },
                confirm=True,
            )

            self.assertEqual(task.status, TaskStatus.SUCCESS)
            self.assertTrue(task.context["release_quality_gate"]["passed"])
            self.assertEqual(task.context["contract_versions"]["performance_summary"], "1.1")
            self.assertEqual(task.context["release_quality_gate"]["metrics"]["draw_call_count"], 280)
            self.assertEqual(task.context["release_quality_gate"]["metrics"]["node_count"], 180)
            self.assertTrue(any(check["name"] == "draw_call_budget" and check["status"] == "passed" for check in task.context["release_quality_gate"]["checks"]))
            self.assertTrue(any(check["name"] == "frame_spike_budget" and check["status"] == "passed" for check in task.context["release_quality_gate"]["checks"]))
        finally:
            shutil.rmtree(project_dir, ignore_errors=True)

    @patch('agent_system.router.GodotCLI', GateAwareGodotCLI)
    def test_qa_export_blocks_when_draw_call_budget_in_performance_summary_is_exceeded(self):
        from agent_system.router import GodotAgentRouter

        project_dir = project_root / "tests" / ".tmp_release_draw_call_gate"
        shutil.rmtree(project_dir, ignore_errors=True)
        try:
            scenes_dir = project_dir / "scenes"
            scenes_dir.mkdir(parents=True, exist_ok=True)
            (scenes_dir / "main_scene.tscn").write_text(
                '[gd_scene load_steps=1 format=3 uid="uid://draw_call_gate_scene"]\n\n[node name="Main" type="Node2D"]\n',
                encoding="utf-8",
            )

            router = GodotAgentRouter(godot_project_path=str(project_dir), history_file=self.test_hist_file)
            task = router.execute(
                "发布 QA Web 项目",
                context={
                    "feature_status": "approved",
                    "performance_budget": {
                        "max_scene_load_ms": 1000,
                        "max_draw_call_count": 320,
                    },
                    "performance_summary": {
                        "passed": False,
                        "scene_path": "res://scenes/main_scene.tscn",
                        "checks": [
                            {"name": "draw_call_budget", "status": "blocked", "message": "Draw Call 520 超出预算 320"},
                            {"name": "draw_call_regression", "status": "blocked", "message": "Draw Call 相比基线回退 35%"},
                        ],
                        "issues": ["Draw Call 520 超出预算 320"],
                        "metrics": {"draw_call_count": 520},
                        "budgets": {"max_draw_call_count": 320},
                    },
                },
                confirm=True,
            )

            self.assertEqual(task.status, TaskStatus.FAILED)
            self.assertFalse(task.context["release_quality_gate"]["passed"])
            self.assertIn("draw_call_budget", task.context["release_quality_gate"]["blocked_checks"])
            self.assertEqual(router.roles["resource_manager"].godot_cli.export_calls, [])
        finally:
            shutil.rmtree(project_dir, ignore_errors=True)

    def test_self_healing_injects_fix_step_without_outer_rollback(self):
        self.agent.roles["code_generator"] = HealingAwareCodeRole()
        self.agent.roles["resource_manager"] = HealingResourceRole()

        task = self.agent.execute("生成代码", confirm=True)

        self.assertEqual(task.status, TaskStatus.SUCCESS)
        self.assertTrue(task.context.get("healed"))
        self.assertEqual(self.agent.roles["code_generator"].prompts, ["生成代码", "生成代码"])
        self.assertEqual(self.agent.roles["resource_manager"].prompts, ["审计并初始化导出环境"])
        self.assertTrue(any(step.name.startswith("AutoFix-") and step.status == TaskStatus.SUCCESS for step in task.steps))
        self.assertFalse(any("启动回滚机制..." in log for log in task.logs))

    def test_inventory_template_generation(self):
        task = self.agent.execute("生成库存系统", confirm=True)
        self.assertEqual(task.status, TaskStatus.SUCCESS)
        self.assertEqual(task.artifacts[0].name, "inventory_system.gd")
        self.assertIn("class_name InventorySystem", task.artifacts[0].content)

    def test_dialogue_command_routes_to_code_generator(self):
        task = self.agent.plan("为NPC添加对话系统")
        self.assertEqual([step.role for step in task.steps], ["code_generator"])

    @patch('agent_system.router.GodotCLI', MockGodotCLI)
    def test_safe_refactor_can_rename_current_function_from_editor_context(self):
        from agent_system.router import GodotAgentRouter

        project_dir = project_root / "tests" / ".tmp_current_function_refactor"
        shutil.rmtree(project_dir, ignore_errors=True)
        try:
            scripts_dir = project_dir / "scripts"
            scripts_dir.mkdir(parents=True, exist_ok=True)
            target_file = scripts_dir / "player_controller.gd"
            target_file.write_text(
                'extends Node\n'
                'class_name PlayerController\n'
                '\n'
                'func move_player() -> void:\n'
                '    pass\n'
                '\n'
                'func _ready() -> void:\n'
                '    move_player()\n',
                encoding="utf-8"
            )

            router = GodotAgentRouter(godot_project_path=str(project_dir), history_file=self.test_hist_file)
            task = router.execute(
                "重命名当前函数为 move_character",
                context={
                    "editor_state": {
                        "current_script_path": "res://scripts/player_controller.gd",
                        "current_script_line": 4,
                    }
                },
                confirm=True
            )

            self.assertEqual(task.status, TaskStatus.SUCCESS)
            self.assertEqual(task.steps[0].role, "code_generator")
            updated = target_file.read_text(encoding="utf-8")
            self.assertIn("func move_character()", updated)
            self.assertIn("move_character()", updated)
            self.assertNotIn("move_player()", updated)
            self.assertEqual(task.context.get("target_script_path"), "res://scripts/player_controller.gd")
            self.assertEqual(task.context.get("current_script_symbol_name"), "move_player")
            self.assertEqual(task.context.get("refactor_old_name"), "move_player")
            self.assertEqual(task.context.get("refactor_new_name"), "move_character")
            self.assertEqual(task.context.get("refactor_target_script_path"), "res://scripts/player_controller.gd")
        finally:
            shutil.rmtree(project_dir, ignore_errors=True)

    @patch('agent_system.router.GodotCLI', MockGodotCLI)
    def test_safe_refactor_class_rename_updates_gdscript_references(self):
        from agent_system.router import GodotAgentRouter

        project_dir = project_root / "tests" / ".tmp_class_refactor"
        shutil.rmtree(project_dir, ignore_errors=True)
        try:
            scripts_dir = project_dir / "scripts"
            scripts_dir.mkdir(parents=True, exist_ok=True)
            (scripts_dir / "player_controller.gd").write_text(
                'extends Node\n'
                'class_name PlayerController\n',
                encoding="utf-8"
            )
            target_file = scripts_dir / "spawn_manager.gd"
            target_file.write_text(
                'extends Node\n'
                'var controller: PlayerController = PlayerController.new()\n',
                encoding="utf-8"
            )

            router = GodotAgentRouter(godot_project_path=str(project_dir), history_file=self.test_hist_file)
            task = router.execute("重命名类 PlayerController 为 HeroController", confirm=True)

            self.assertEqual(task.status, TaskStatus.SUCCESS)
            self.assertEqual(task.steps[0].role, "code_generator")
            updated = target_file.read_text(encoding="utf-8")
            self.assertIn("HeroController", updated)
            self.assertNotIn("PlayerController", updated)
            self.assertEqual(task.context.get("refactor_symbol_type"), "类")
        finally:
            shutil.rmtree(project_dir, ignore_errors=True)

    @patch('agent_system.router.GodotCLI', MockGodotCLI)
    def test_safe_refactor_function_rename_updates_calls_and_callable_strings(self):
        from agent_system.router import GodotAgentRouter

        project_dir = project_root / "tests" / ".tmp_function_refactor"
        shutil.rmtree(project_dir, ignore_errors=True)
        try:
            scripts_dir = project_dir / "scripts"
            scripts_dir.mkdir(parents=True, exist_ok=True)
            target_file = scripts_dir / "player_controller.gd"
            target_file.write_text(
                'extends Node\n'
                '\n'
                'func move_player() -> void:\n'
                '    pass\n'
                '\n'
                'func _ready() -> void:\n'
                '    move_player()\n'
                '    self.move_player()\n'
                '    call("move_player")\n'
                '    if has_method("move_player"):\n'
                '        Callable(self, "move_player")\n',
                encoding="utf-8"
            )

            router = GodotAgentRouter(godot_project_path=str(project_dir), history_file=self.test_hist_file)
            task = router.execute("重命名函数 move_player 为 move_character", confirm=True)

            self.assertEqual(task.status, TaskStatus.SUCCESS)
            updated = target_file.read_text(encoding="utf-8")
            self.assertIn("func move_character()", updated)
            self.assertIn("move_character()", updated)
            self.assertIn('call("move_character")', updated)
            self.assertIn('has_method("move_character")', updated)
            self.assertIn('Callable(self, "move_character")', updated)
            self.assertNotIn("move_player", updated)
            self.assertEqual(task.context.get("refactor_symbol_type"), "函数")
        finally:
            shutil.rmtree(project_dir, ignore_errors=True)

    @patch('agent_system.router.GodotCLI', MockGodotCLI)
    def test_safe_refactor_function_rename_respects_local_shadowing(self):
        from agent_system.router import GodotAgentRouter

        project_dir = project_root / "tests" / ".tmp_function_shadow_refactor"
        shutil.rmtree(project_dir, ignore_errors=True)
        try:
            scripts_dir = project_dir / "scripts"
            scripts_dir.mkdir(parents=True, exist_ok=True)
            target_file = scripts_dir / "player_controller.gd"
            target_file.write_text(
                'extends Node\n'
                '\n'
                'func move_player() -> void:\n'
                '    pass\n'
                '\n'
                'func _ready() -> void:\n'
                '    var move_player = Callable(self, "_ready")\n'
                '    move_player.call()\n'
                '    self.move_player()\n',
                encoding="utf-8"
            )

            router = GodotAgentRouter(godot_project_path=str(project_dir), history_file=self.test_hist_file)
            task = router.execute("重命名函数 move_player 为 move_character", confirm=True)

            self.assertEqual(task.status, TaskStatus.SUCCESS)
            updated = target_file.read_text(encoding="utf-8")
            self.assertIn("func move_character()", updated)
            self.assertIn('var move_player = Callable(self, "_ready")', updated)
            self.assertIn("move_player.call()", updated)
            self.assertIn("self.move_character()", updated)
            self.assertNotIn("self.move_player()", updated)
        finally:
            shutil.rmtree(project_dir, ignore_errors=True)

    @patch('agent_system.router.GodotCLI', MockGodotCLI)
    def test_safe_refactor_signal_rename_updates_signal_references(self):
        from agent_system.router import GodotAgentRouter

        project_dir = project_root / "tests" / ".tmp_signal_refactor"
        shutil.rmtree(project_dir, ignore_errors=True)
        try:
            scripts_dir = project_dir / "scripts"
            scripts_dir.mkdir(parents=True, exist_ok=True)
            target_file = scripts_dir / "player_controller.gd"
            target_file.write_text(
                'extends Node\n'
                'signal jumped(height)\n'
                '\n'
                'func _ready() -> void:\n'
                '    jumped.connect(_on_jumped)\n'
                '    emit_signal("jumped", 2)\n'
                '    connect("jumped", Callable(self, "_on_jumped"))\n'
                '    jumped.emit(2)\n',
                encoding="utf-8"
            )

            router = GodotAgentRouter(godot_project_path=str(project_dir), history_file=self.test_hist_file)
            task = router.execute("重命名信号 jumped 为 landed", confirm=True)

            self.assertEqual(task.status, TaskStatus.SUCCESS)
            updated = target_file.read_text(encoding="utf-8")
            self.assertIn("signal landed(height)", updated)
            self.assertIn("landed.connect", updated)
            self.assertIn('emit_signal("landed", 2)', updated)
            self.assertIn('connect("landed", Callable(self, "_on_jumped"))', updated)
            self.assertIn("landed.emit(2)", updated)
            self.assertNotIn("signal jumped", updated)
            self.assertEqual(task.context.get("refactor_symbol_type"), "信号")
        finally:
            shutil.rmtree(project_dir, ignore_errors=True)

    def test_alert_ai_template_generation(self):
        task = self.agent.execute("生成警戒 AI", confirm=True)
        self.assertEqual(task.status, TaskStatus.SUCCESS)
        self.assertEqual(task.artifacts[0].name, "alert_ai.gd")
        self.assertIn("is_alerted", task.artifacts[0].content)

    def test_task_message_prefers_error_over_rollback_log(self):
        task = Task(prompt="test", status=TaskStatus.ROLLED_BACK)
        task.add_log("ERROR: 场景创建失败")
        task.add_log("DETAIL: 未找到 Godot 可执行文件")
        task.add_log("启动回滚机制...")
        self.assertEqual(task.get_message(), "场景创建失败: 未找到 Godot 可执行文件")
        self.assertEqual(task.message, "场景创建失败: 未找到 Godot 可执行文件")
        self.assertEqual(task.to_dict()["message"], "场景创建失败: 未找到 Godot 可执行文件")

    @patch('agent_system.router.GodotCLI', MockGodotCLI)
    def test_resource_audit_generates_report(self):
        from agent_system.router import GodotAgentRouter

        project_dir = project_root / "tests" / ".tmp_resource_audit"
        shutil.rmtree(project_dir, ignore_errors=True)
        try:
            assets_dir = project_dir / "assets"
            scenes_dir = project_dir / "scenes"
            imported_dir = project_dir / ".godot" / "imported"
            assets_dir.mkdir(parents=True, exist_ok=True)
            scenes_dir.mkdir(parents=True, exist_ok=True)
            imported_dir.mkdir(parents=True, exist_ok=True)
            bad_file = assets_dir / "Bad Name.png"
            bad_file.write_text("mock", encoding="utf-8")
            (imported_dir / "Bad Name.png-good.ctex").write_text("mock", encoding="utf-8")
            (assets_dir / "Bad Name.png.import").write_text(
                '[remap]\nimporter="texture"\ntype="CompressedTexture2D"\n\n[deps]\nsource_file="res://assets/Bad Name.png"\ndest_files=["res://.godot/imported/Bad Name.png-good.ctex"]\n',
                encoding="utf-8"
            )
            (assets_dir / "hero_icon.png.import").write_text(
                '[remap]\nimporter="texture"\ntype="CompressedTexture2D"\n\n[deps]\nsource_file="res://assets/wrong_name.png"\ndest_files=["res://.godot/imported/hero_icon.png-missing.ctex"]\n',
                encoding="utf-8"
            )
            (scenes_dir / "demo_scene.tscn").write_text(
                '[gd_scene format=3]\n'
                '\n'
                '[ext_resource type="Texture2D" path="res://assets/missing_texture.png" id="1_tex"]\n'
                '[sub_resource type="SpriteFrames" id="sprite_frames"]\n'
                '\n'
                '[node name="Hero Root" type="Node2D"]\n'
                'texture = ExtResource("missing_ext")\n'
                'frames = SubResource("missing_anim")\n'
                '\n'
                '[node name="weapon_slot" type="Node2D" parent="."]\n',
                encoding="utf-8"
            )

            router = GodotAgentRouter(godot_project_path=str(project_dir), history_file=self.test_hist_file)
            task = router.execute("审计项目资源命名", confirm=True)
        finally:
            shutil.rmtree(project_dir, ignore_errors=True)

        self.assertEqual(task.status, TaskStatus.SUCCESS)
        self.assertEqual(task.steps[0].role, "resource_manager")
        self.assertGreater(task.context.get("audit_issue_count", 0), 0)
        self.assertGreater(task.context.get("audit_error_count", 0), 0)
        self.assertGreater(task.context.get("audit_warning_count", 0), 0)
        self.assertEqual(task.context.get("audit_highest_severity"), "error")
        self.assertGreater(task.context.get("audit_scene_issue_count", 0), 0)
        self.assertGreater(task.context.get("audit_scene_header_issue_count", 0), 0)
        self.assertGreater(task.context.get("audit_scene_reference_issue_count", 0), 0)
        self.assertGreater(task.context.get("audit_import_issue_count", 0), 0)
        self.assertGreater(task.context.get("audit_import_config_issue_count", 0), 0)
        self.assertGreater(task.context.get("audit_import_artifact_issue_count", 0), 0)
        self.assertTrue(any(artifact.type == "report" for artifact in task.artifacts))
        self.assertIn("- Errors:", task.artifacts[0].content)
        self.assertIn("- Warnings:", task.artifacts[0].content)
        self.assertIn("[ERROR]", task.artifacts[0].content)
        self.assertIn("[WARNING]", task.artifacts[0].content)
        self.assertIn("Bad Name.png", task.artifacts[0].content)
        self.assertIn("Hero Root", task.artifacts[0].content)
        self.assertIn(".import::source_file", task.artifacts[0].content)
        self.assertIn("missing_scene_uid", task.artifacts[0].content)
        self.assertIn("unknown_ext_resource_reference", task.artifacts[0].content)
        self.assertIn("source_file_mismatch", task.artifacts[0].content)
        self.assertIn("missing_dest_target", task.artifacts[0].content)

    @patch('agent_system.router.GodotCLI', MockGodotCLI)
    def test_resource_audit_detects_duplicate_scene_uids_and_ext_resource_paths(self):
        from agent_system.router import GodotAgentRouter

        project_dir = project_root / "tests" / ".tmp_scene_uid_audit"
        shutil.rmtree(project_dir, ignore_errors=True)
        try:
            scenes_dir = project_dir / "scenes"
            scenes_dir.mkdir(parents=True, exist_ok=True)

            shared_uid = "uid://shared_scene_uid"
            (scenes_dir / "shared_scene.tscn").write_text(
                f'[gd_scene load_steps=1 format=3 uid="{shared_uid}"]\n'
                '\n'
                '[node name="shared_scene" type="Node2D"]\n',
                encoding="utf-8"
            )
            (scenes_dir / "duplicate_scene.tscn").write_text(
                f'[gd_scene load_steps=1 format=3 uid="{shared_uid}"]\n'
                '\n'
                '[node name="duplicate_scene" type="Node2D"]\n',
                encoding="utf-8"
            )
            (scenes_dir / "main_scene.tscn").write_text(
                '[gd_scene load_steps=3 format=3 uid="uid://main_scene_uid"]\n'
                '\n'
                '[ext_resource type="PackedScene" uid="uid://wrong_scene_uid" path="res://scenes/shared_scene.tscn" id="1_shared"]\n'
                '[ext_resource type="PackedScene" path="res://scenes/shared_scene.tscn" id="2_shared"]\n'
                '\n'
                '[node name="main_scene" type="Node2D"]\n',
                encoding="utf-8"
            )

            router = GodotAgentRouter(godot_project_path=str(project_dir), history_file=self.test_hist_file)
            task = router.execute("审计项目资源命名", confirm=True)
        finally:
            shutil.rmtree(project_dir, ignore_errors=True)

        self.assertEqual(task.status, TaskStatus.SUCCESS)
        self.assertGreater(task.context.get("audit_scene_header_issue_count", 0), 0)
        self.assertGreater(task.context.get("audit_scene_reference_issue_count", 0), 0)
        self.assertIn("duplicate_scene_uid", task.artifacts[0].content)
        self.assertIn("ext_resource_uid_mismatch", task.artifacts[0].content)
        self.assertIn("duplicate_ext_resource_path", task.artifacts[0].content)

    @patch('agent_system.router.GodotCLI', MockGodotCLI)
    def test_resource_audit_detects_resource_headers_and_cross_file_uid_conflicts(self):
        from agent_system.router import GodotAgentRouter

        project_dir = project_root / "tests" / ".tmp_text_resource_audit"
        shutil.rmtree(project_dir, ignore_errors=True)
        try:
            scenes_dir = project_dir / "scenes"
            assets_dir = project_dir / "assets"
            scenes_dir.mkdir(parents=True, exist_ok=True)
            assets_dir.mkdir(parents=True, exist_ok=True)

            shared_uid = "uid://shared_asset_uid"
            (scenes_dir / "host_scene.tscn").write_text(
                f'[gd_scene load_steps=1 format=3 uid="{shared_uid}"]\n'
                '\n'
                '[node name="host_scene" type="Node2D"]\n',
                encoding="utf-8"
            )
            (assets_dir / "player_profile.tres").write_text(
                f'[gd_resource type="Resource" load_steps=1 format=3 uid="{shared_uid}"]\n'
                '\n'
                '[resource]\n',
                encoding="utf-8"
            )
            (assets_dir / "broken_profile.res").write_text(
                '[gd_resource format=3 uid="bad_uid"]\n'
                '\n'
                '[resource]\n',
                encoding="utf-8"
            )
            (scenes_dir / "reference_scene.tscn").write_text(
                '[gd_scene load_steps=2 format=3 uid="uid://reference_scene_uid"]\n'
                '\n'
                '[ext_resource type="Resource" uid="uid://wrong_profile_uid" path="res://assets/player_profile.tres" id="1_profile"]\n'
                '\n'
                '[node name="reference_scene" type="Node2D"]\n',
                encoding="utf-8"
            )

            router = GodotAgentRouter(godot_project_path=str(project_dir), history_file=self.test_hist_file)
            task = router.execute("审计项目资源命名", confirm=True)
        finally:
            shutil.rmtree(project_dir, ignore_errors=True)

        self.assertEqual(task.status, TaskStatus.SUCCESS)
        self.assertGreater(task.context.get("audit_resource_issue_count", 0), 0)
        self.assertGreater(task.context.get("audit_resource_header_issue_count", 0), 0)
        self.assertGreater(task.context.get("audit_scene_header_issue_count", 0), 0)
        self.assertGreater(task.context.get("audit_scene_reference_issue_count", 0), 0)
        self.assertIn("duplicate_resource_uid", task.artifacts[0].content)
        self.assertIn("duplicate_scene_uid", task.artifacts[0].content)
        self.assertIn("missing_resource_type", task.artifacts[0].content)
        self.assertIn("invalid_resource_uid", task.artifacts[0].content)
        self.assertIn("ext_resource_uid_mismatch", task.artifacts[0].content)

    @patch('agent_system.router.GodotCLI', MockGodotCLI)
    def test_resource_audit_detects_text_resource_references(self):
        from agent_system.router import GodotAgentRouter

        project_dir = project_root / "tests" / ".tmp_resource_reference_audit"
        shutil.rmtree(project_dir, ignore_errors=True)
        try:
            assets_dir = project_dir / "assets"
            assets_dir.mkdir(parents=True, exist_ok=True)

            (assets_dir / "base_profile.tres").write_text(
                '[gd_resource type="Resource" load_steps=1 format=3 uid="uid://base_profile_uid"]\n'
                '\n'
                '[resource]\n',
                encoding="utf-8"
            )
            (assets_dir / "inventory_profile.tres").write_text(
                '[gd_resource type="Resource" load_steps=3 format=3 uid="uid://inventory_profile_uid"]\n'
                '\n'
                '[ext_resource type="Resource" uid="uid://wrong_profile_uid" path="res://assets/base_profile.tres" id="1_base"]\n'
                '[ext_resource type="Resource" path="res://assets/base_profile.tres" id="2_base"]\n'
                '[sub_resource type="Resource" id="cache_profile"]\n'
                '\n'
                '[resource]\n'
                'profile = ExtResource("missing_profile")\n'
                'cache = SubResource("missing_cache")\n',
                encoding="utf-8"
            )

            router = GodotAgentRouter(godot_project_path=str(project_dir), history_file=self.test_hist_file)
            task = router.execute("审计项目资源命名", confirm=True)
        finally:
            shutil.rmtree(project_dir, ignore_errors=True)

        self.assertEqual(task.status, TaskStatus.SUCCESS)
        self.assertGreater(task.context.get("audit_resource_issue_count", 0), 0)
        self.assertGreater(task.context.get("audit_resource_reference_issue_count", 0), 0)
        self.assertIn("Resource Reference Issues", task.artifacts[0].content)
        self.assertIn("duplicate_ext_resource_path", task.artifacts[0].content)
        self.assertIn("ext_resource_uid_mismatch", task.artifacts[0].content)
        self.assertIn("unknown_ext_resource_reference", task.artifacts[0].content)
        self.assertIn("unknown_sub_resource_reference", task.artifacts[0].content)

    @patch('agent_system.router.GodotCLI', MockGodotCLI)
    def test_resource_audit_detects_binary_res_files(self):
        from agent_system.router import GodotAgentRouter

        project_dir = project_root / "tests" / ".tmp_binary_res_audit"
        shutil.rmtree(project_dir, ignore_errors=True)
        try:
            assets_dir = project_dir / "assets"
            assets_dir.mkdir(parents=True, exist_ok=True)
            (assets_dir / "cache_blob.res").write_bytes(b"RSRC\x00\x01\x02\x03binary")

            router = GodotAgentRouter(godot_project_path=str(project_dir), history_file=self.test_hist_file)
            task = router.execute("审计项目资源命名", confirm=True)
        finally:
            shutil.rmtree(project_dir, ignore_errors=True)

        self.assertEqual(task.status, TaskStatus.SUCCESS)
        self.assertGreater(task.context.get("audit_binary_resource_issue_count", 0), 0)
        self.assertGreater(task.context.get("audit_info_count", 0), 0)
        self.assertIn("Binary Resource Issues", task.artifacts[0].content)
        self.assertIn("[INFO]", task.artifacts[0].content)
        self.assertIn("binary_resource_skipped", task.artifacts[0].content)

    @patch('agent_system.router.GodotCLI', MockGodotCLI)
    def test_resource_audit_detects_reference_cycles(self):
        from agent_system.router import GodotAgentRouter

        project_dir = project_root / "tests" / ".tmp_resource_cycle_audit"
        shutil.rmtree(project_dir, ignore_errors=True)
        try:
            assets_dir = project_dir / "assets"
            assets_dir.mkdir(parents=True, exist_ok=True)

            (assets_dir / "cycle_a.tres").write_text(
                '[gd_resource type="Resource" load_steps=3 format=3 uid="uid://cycle_a_uid"]\n'
                '\n'
                '[ext_resource type="Resource" path="res://assets/cycle_b.tres" id="1_b"]\n'
                '[ext_resource type="Resource" path="res://assets/cycle_c.tres" id="2_c"]\n'
                '\n'
                '[resource]\n',
                encoding="utf-8"
            )
            (assets_dir / "cycle_b.tres").write_text(
                '[gd_resource type="Resource" load_steps=2 format=3 uid="uid://cycle_b_uid"]\n'
                '\n'
                '[ext_resource type="Resource" path="res://assets/cycle_a.tres" id="1_a"]\n'
                '\n'
                '[resource]\n',
                encoding="utf-8"
            )
            (assets_dir / "cycle_c.tres").write_text(
                '[gd_resource type="Resource" load_steps=2 format=3 uid="uid://cycle_c_uid"]\n'
                '\n'
                '[ext_resource type="Resource" path="res://assets/cycle_a.tres" id="1_a"]\n'
                '\n'
                '[resource]\n',
                encoding="utf-8"
            )

            router = GodotAgentRouter(godot_project_path=str(project_dir), history_file=self.test_hist_file)
            task = router.execute("审计项目资源命名", confirm=True)
        finally:
            shutil.rmtree(project_dir, ignore_errors=True)

        self.assertEqual(task.status, TaskStatus.SUCCESS)
        self.assertGreater(task.context.get("audit_cycle_issue_count", 0), 0)
        self.assertIn("Resource Cycle Issues", task.artifacts[0].content)
        self.assertIn("reference_cycle", task.artifacts[0].content)
        self.assertIn("cycle_a.tres", task.artifacts[0].content)
        self.assertIn("cycle_b.tres", task.artifacts[0].content)
        self.assertIn("assets/cycle_a.tres -> assets/cycle_b.tres -> assets/cycle_a.tres", task.artifacts[0].content)
        self.assertIn("remove or redirect ext_resource at assets/cycle_a.tres:3 pointing to assets/cycle_b.tres", task.artifacts[0].content)

    @patch('agent_system.router.GodotCLI', MockGodotCLI)
    def test_resource_fix_preview_plans_low_risk_changes_without_modifying_files(self):
        from agent_system.router import GodotAgentRouter

        project_dir = project_root / "tests" / ".tmp_resource_fix_preview"
        shutil.rmtree(project_dir, ignore_errors=True)
        try:
            assets_dir = project_dir / "assets"
            scenes_dir = project_dir / "scenes"
            imported_dir = project_dir / ".godot" / "imported"
            assets_dir.mkdir(parents=True, exist_ok=True)
            scenes_dir.mkdir(parents=True, exist_ok=True)
            imported_dir.mkdir(parents=True, exist_ok=True)

            (assets_dir / "Bad Name.png").write_text("mock", encoding="utf-8")
            (assets_dir / "hero_icon.png").write_text("mock", encoding="utf-8")
            (imported_dir / "Bad Name.png-good.ctex").write_text("cache", encoding="utf-8")
            (imported_dir / "hero_icon.png-good.ctex").write_text("cache", encoding="utf-8")
            (assets_dir / "Bad Name.png.import").write_text(
                '[remap]\n'
                'importer="texture"\n'
                'type="CompressedTexture2D"\n'
                '\n'
                '[deps]\n'
                'source_file="res://assets/Bad Name.png"\n'
                'dest_files=["res://.godot/imported/Bad Name.png-good.ctex"]\n',
                encoding="utf-8"
            )
            (assets_dir / "hero_icon.png.import").write_text(
                '[remap]\n'
                'importer="texture"\n'
                'type="CompressedTexture2D"\n'
                '\n'
                '[deps]\n'
                'source_file="res://assets/wrong_name.png"\n'
                'dest_files=["res://.godot/imported/hero_icon.png-good.ctex"]\n',
                encoding="utf-8"
            )
            (scenes_dir / "main_scene.tscn").write_text(
                '[gd_scene load_steps=2 format=3 uid="uid://main_scene_uid"]\n'
                '\n'
                '[ext_resource type="Texture2D" path="res://assets/Bad Name.png" id="1_tex"]\n'
                '\n'
                '[node name="main_scene" type="Node2D"]\n',
                encoding="utf-8"
            )

            router = GodotAgentRouter(godot_project_path=str(project_dir), history_file=self.test_hist_file)
            task = router.execute("预览修复项目资源命名", confirm=True)
        finally:
            shutil.rmtree(project_dir, ignore_errors=True)

        self.assertEqual(task.status, TaskStatus.SUCCESS)
        self.assertEqual(task.steps[0].role, "resource_manager")
        self.assertEqual(task.context.get("audit_fix_mode"), "preview")
        self.assertGreater(task.context.get("audit_fix_change_count", 0), 0)
        self.assertTrue(any(artifact.type == "fix_report" for artifact in task.artifacts))
        self.assertIn("Planned Renames", task.artifacts[0].content)
        self.assertIn("Bad Name.png", task.artifacts[0].content)
        self.assertIn("bad_name.png", task.artifacts[0].content)

    @patch('agent_system.router.GodotCLI', MockGodotCLI)
    def test_resource_fix_apply_renames_files_and_updates_import_references(self):
        from agent_system.router import GodotAgentRouter

        project_dir = project_root / "tests" / ".tmp_resource_fix_apply"
        shutil.rmtree(project_dir, ignore_errors=True)
        try:
            assets_dir = project_dir / "assets"
            scenes_dir = project_dir / "scenes"
            imported_dir = project_dir / ".godot" / "imported"
            assets_dir.mkdir(parents=True, exist_ok=True)
            scenes_dir.mkdir(parents=True, exist_ok=True)
            imported_dir.mkdir(parents=True, exist_ok=True)

            (assets_dir / "Bad Name.png").write_text("mock", encoding="utf-8")
            (assets_dir / "hero_icon.png").write_text("mock", encoding="utf-8")
            (imported_dir / "Bad Name.png-good.ctex").write_text("cache", encoding="utf-8")
            (imported_dir / "hero_icon.png-good.ctex").write_text("cache", encoding="utf-8")
            (assets_dir / "Bad Name.png.import").write_text(
                '[remap]\n'
                'importer="texture"\n'
                'type="CompressedTexture2D"\n'
                '\n'
                '[deps]\n'
                'source_file="res://assets/Bad Name.png"\n'
                'dest_files=["res://.godot/imported/Bad Name.png-good.ctex"]\n',
                encoding="utf-8"
            )
            (assets_dir / "hero_icon.png.import").write_text(
                '[remap]\n'
                'importer="texture"\n'
                'type="CompressedTexture2D"\n'
                '\n'
                '[deps]\n'
                'source_file="res://assets/wrong_name.png"\n'
                'dest_files=["res://.godot/imported/hero_icon.png-good.ctex"]\n',
                encoding="utf-8"
            )
            (scenes_dir / "main_scene.tscn").write_text(
                '[gd_scene load_steps=2 format=3 uid="uid://main_scene_uid"]\n'
                '\n'
                '[ext_resource type="Texture2D" path="res://assets/Bad Name.png" id="1_tex"]\n'
                '\n'
                '[node name="main_scene" type="Node2D"]\n',
                encoding="utf-8"
            )

            router = GodotAgentRouter(godot_project_path=str(project_dir), history_file=self.test_hist_file)
            task = router.execute("修复项目资源命名", confirm=True)

            self.assertEqual(task.status, TaskStatus.SUCCESS)
            self.assertEqual(task.steps[0].role, "resource_manager")
            self.assertEqual(task.context.get("audit_fix_mode"), "apply")
            self.assertGreater(task.context.get("audit_fix_applied_count", 0), 0)
            self.assertEqual(task.context.get("audit_issue_count"), 0)
            self.assertTrue((assets_dir / "bad_name.png").exists())
            self.assertFalse((assets_dir / "Bad Name.png").exists())
            self.assertTrue((assets_dir / "bad_name.png.import").exists())
            self.assertFalse((assets_dir / "Bad Name.png.import").exists())
            self.assertTrue((imported_dir / "bad_name.png-good.ctex").exists())
            self.assertFalse((imported_dir / "Bad Name.png-good.ctex").exists())
            self.assertIn('path="res://assets/bad_name.png"', (scenes_dir / "main_scene.tscn").read_text(encoding="utf-8"))
            self.assertIn('source_file="res://assets/bad_name.png"', (assets_dir / "bad_name.png.import").read_text(encoding="utf-8"))
            self.assertIn('dest_files=["res://.godot/imported/bad_name.png-good.ctex"]', (assets_dir / "bad_name.png.import").read_text(encoding="utf-8"))
            self.assertIn('source_file="res://assets/hero_icon.png"', (assets_dir / "hero_icon.png.import").read_text(encoding="utf-8"))
            self.assertTrue(any(artifact.type == "fix_report" for artifact in task.artifacts))
        finally:
            shutil.rmtree(project_dir, ignore_errors=True)

    def test_history_loading(self):
        # 1. 第一次执行并持久化
        prompt = "Unique History Test"
        self.agent.execute(prompt, confirm=True)
        
        # 2. 重新初始化路由器,验证是否能从文件加载
        from agent_system.router import GodotAgentRouter
        new_agent = GodotAgentRouter(history_file=self.test_hist_file)
        
        history = new_agent.get_history(limit=1)
        self.assertEqual(len(history), 1)
        self.assertEqual(history[0]['prompt'], prompt)

if __name__ == "__main__":
    unittest.main()

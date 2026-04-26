"""
API 返回结构测试
"""

import sys
import json
import shutil
import threading
import unittest
import asyncio
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

# 添加项目路径
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from agent_system.models import Task, TaskStatus, Artifact, TaskStep, ToolResult
from api_server.main import app, manager
from tools.dispatch_release_live_gates import write_release_live_dispatch_audit


class FakeRouter:
    def execute(self, command, context=None, confirm=True):
        task = Task(prompt=command, status=TaskStatus.SUCCESS, context=context or {})
        task.add_log("SUCCESS: 代码生成成功: player_movement_2d.gd")
        return task


class FakeLaunchCLI:
    def __init__(self, launch_callback=None):
        self.launch_callback = launch_callback

    def launch_editor(self, scene_path=None):
        if self.launch_callback:
            self.launch_callback(scene_path)
        return ToolResult(
            True,
            "Godot 编辑器启动中",
            data={
                "pid": 4321,
                "command": ["godot", "-e"],
                "scene_path": scene_path,
                "executable_source": "env",
                "executable_source_label": "GODOT",
            },
        )


class FakeEditorExecutionRouter:
    def __init__(self, launch_callback=None):
        self.godot_cli = FakeLaunchCLI(launch_callback=launch_callback)

    def execute(self, command, context=None, confirm=True):
        task = Task(prompt=command, status=TaskStatus.SUCCESS, context=context or {})
        task.artifacts.append(Artifact(
            name="inject.gd",
            path="internal://",
            type="editor_script",
            content="func _run(plugin):\n    pass\n",
        ))
        task.add_log("SUCCESS: 已生成编辑器脚本")
        return task


class FakeAuditRouter:
    def execute(self, command, context=None, confirm=True):
        task = Task(prompt=command, status=TaskStatus.SUCCESS, context=context or {})
        task.context.update({
            "audit_issue_count": 4,
            "audit_error_count": 2,
            "audit_warning_count": 1,
            "audit_info_count": 1,
            "audit_highest_severity": "error"
        })
        task.add_log("SUCCESS: 审计完成")
        return task


class FakeArtifactRouter:
    def get_history(self, limit=10):
        task = Task(prompt="生成 2D 玩家移动脚本", status=TaskStatus.SUCCESS)
        task.task_id = "task-1"
        task.created_at = 100.0
        task.add_log("SUCCESS: 代码生成成功: player_movement_2d.gd")
        task.artifacts.append(Artifact(
            name="player_movement_2d.gd",
            path="res://scripts/player_movement_2d.gd",
            type="script",
            content="extends CharacterBody2D\n",
            metadata={}
        ))
        task.artifacts.append(Artifact(
            name="resource_audit_1.md",
            path="logs/reports/resource_audit_1.md",
            type="report",
            content="# Resource Audit\n",
            metadata={}
        ))
        return [task.to_dict()]


class FakeRuntimeRouter:
    def __init__(self):
        self.godot_cli = type(
            "FakeRuntimeCLI",
            (),
            {
                "executable": "C:/Godot/godot4.exe",
                "executable_source": "env",
                "executable_source_label": "GODOT",
            },
        )()


class FakePlanRouter:
    def __init__(self):
        self.last_execute_task = None
        self.last_plan_context = None
        self.held_task = None

    def plan(self, command, context=None):
        self.last_plan_context = context or {}
        task = Task(prompt=command, status=TaskStatus.AWAITING_CONFIRMATION, context=context or {})
        task.task_id = "plan-1"
        task.role = "developer"
        task.steps = [
            TaskStep(name="Structure", description="构建场景节点", role="developer"),
            TaskStep(name="Logic", description="处理逻辑或属性", role="code_generator"),
        ]
        self.held_task = task
        return task

    def execute_plan(self, task):
        self.last_execute_task = task
        for step in task.steps:
            step.status = TaskStatus.SUCCESS
        task.status = TaskStatus.SUCCESS
        task.add_log(f"SUCCESS: 已执行 {len(task.steps)} 个步骤")
        self.held_task = task
        return task

    def get_task(self, task_id):
        return self.held_task if self.held_task and task_id == self.held_task.task_id else None

    def get_history(self, limit=10):
        return [self.held_task.to_dict()] if self.held_task else []

    @property
    def roles(self):
        return {
            "developer": object(),
            "code_generator": object(),
            "tester": object(),
            "ai_controller": object(),
            "resource_manager": object(),
        }


class FakeHistoryRouter:
    def __init__(self):
        approved = Task(prompt="完成功能 A", status=TaskStatus.SUCCESS, context={
            "feature_id": "feature-a",
            "feature_status": "approved",
            "owner": "producer-a",
        })
        approved.task_id = "task-a"
        approved.created_at = 200.0
        approved.add_log("SUCCESS: 功能 A 完成")

        pending = Task(prompt="完成功能 B", status=TaskStatus.SUCCESS, context={
            "feature_id": "feature-b",
            "feature_status": "pending_acceptance",
            "owner": "producer-b",
        })
        pending.task_id = "task-b"
        pending.created_at = 100.0
        pending.add_log("SUCCESS: 功能 B 完成")

        pending_extra = Task(prompt="完成功能 C", status=TaskStatus.SUCCESS, context={
            "feature_id": "feature-c",
            "feature_status": "pending_acceptance",
            "owner": "producer-b",
        })
        pending_extra.task_id = "task-c"
        pending_extra.created_at = 50.0
        pending_extra.add_log("SUCCESS: 功能 C 完成")

        self.items = [approved, pending, pending_extra]
        self.tasks = {task.task_id: task for task in self.items}
        self.saved_task = None

    def get_history(self, limit=10):
        tasks = sorted(self.items, key=lambda item: item.created_at, reverse=True)
        return [task.to_dict() for task in tasks[:limit]]

    def get_task(self, task_id):
        return self.tasks.get(task_id)

    def rollback(self, task):
        task.status = TaskStatus.ROLLED_BACK
        task.add_log("执行回滚...")
        self.saved_task = task

    def _save_task(self, task):
        self.saved_task = task


class ApiDataTableGodotCLI:
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
        output_file = Path(output_path)
        output_file.parent.mkdir(parents=True, exist_ok=True)
        output_file.write_text("<html></html>", encoding="utf-8")
        return ToolResult(True, "OK")

    def get_version(self):
        return "4.2.0"


class TestAPI(unittest.TestCase):
    def setUp(self):
        manager.editor_states.clear()
        manager.command_queues.clear()
        manager.last_screenshots.clear()
        manager.last_editor_events.clear()
        manager.editor_event_counters.clear()
        manager.last_editor_launches.clear()
        manager.command_counters.clear()
        manager.command_acks.clear()
        manager.active_websockets.clear()
        manager.portal_websockets.clear()
        manager.commands.clear()

    def test_execute_returns_message(self):
        with patch("api_server.main.manager.get_router", return_value=FakeRouter()):
            client = TestClient(app)
            response = client.post("/execute", json={"command": "生成 2D 玩家移动脚本"})

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["status"], "success")
        self.assertEqual(payload["message"], "代码生成成功: player_movement_2d.gd")

    def test_portal_websocket_receives_health_update(self):
        temp_project = project_root / "tests" / ".tmp_portal_ws_health"
        shutil.rmtree(temp_project, ignore_errors=True)
        temp_project.mkdir(parents=True, exist_ok=True)
        try:
            with patch("api_server.main.manager.get_router", return_value=FakeRuntimeRouter()):
                client = TestClient(app)
                with client.websocket_connect("/ws/portal?project_path=default") as websocket:
                    initial = websocket.receive_json()
                    self.assertEqual(initial["type"], "health_update")

                    manager.editor_states[str(temp_project)] = {
                        "is_active": True,
                        "project_path": str(temp_project),
                        "current_scene": "res://scenes/main_scene.tscn",
                    }
                    manager.last_screenshots[str(temp_project)] = "ZmFrZQ=="
                    asyncio.run(manager.broadcast_health_update(str(temp_project)))

                    update = websocket.receive_json()
        finally:
            shutil.rmtree(temp_project, ignore_errors=True)

        self.assertEqual(update["type"], "health_update")
        self.assertEqual(update["project_path"], f"{temp_project.resolve().as_posix()}/")
        self.assertEqual(update["editor_state"]["current_scene"], "res://scenes/main_scene.tscn")
        self.assertEqual(update["screenshot"], "ZmFrZQ==")

    def test_execute_returns_audit_severity_context(self):
        with patch("api_server.main.manager.get_router", return_value=FakeAuditRouter()):
            client = TestClient(app)
            response = client.post("/execute", json={"command": "审计项目资源命名"})

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["context"]["audit_issue_count"], 4)
        self.assertEqual(payload["context"]["audit_error_count"], 2)
        self.assertEqual(payload["context"]["audit_warning_count"], 1)
        self.assertEqual(payload["context"]["audit_info_count"], 1)
        self.assertEqual(payload["context"]["audit_highest_severity"], "error")

    def test_artifacts_returns_recent_flattened_items(self):
        with patch("api_server.main.manager.get_router", return_value=FakeArtifactRouter()):
            client = TestClient(app)
            response = client.get("/artifacts", params={"project_path": "default", "limit": 5})

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["count"], 2)
        self.assertEqual(payload["items"][0]["name"], "resource_audit_1.md")
        self.assertEqual(payload["items"][0]["type"], "report")
        self.assertEqual(payload["items"][0]["task_prompt"], "生成 2D 玩家移动脚本")
        self.assertEqual(payload["items"][1]["name"], "player_movement_2d.gd")
        self.assertFalse(payload["items"][1]["is_internal"])

    def test_plan_returns_editable_task(self):
        fake_router = FakePlanRouter()
        with patch("api_server.main.manager.get_router", return_value=fake_router):
            client = TestClient(app)
            response = client.post("/plan", json={"command": "创建一个玩家场景并生成脚本"})

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["status"], "awaiting_confirmation")
        self.assertEqual(payload["task_id"], "plan-1")
        self.assertEqual([step["role"] for step in payload["steps"]], ["developer", "code_generator"])
        self.assertEqual(payload["context"]["feature_status"], "pending_review")
        self.assertEqual(payload["context"]["contract_versions"]["feature_context"], "1.5")
        self.assertTrue(payload["context"]["feature_id"].startswith("feature-"))
        self.assertGreaterEqual(len(payload["context"]["acceptance_criteria"]), 1)
        self.assertIn("validation_method", payload["context"])
        self.assertIn("blockers", payload["context"])
        self.assertIn("artifact_links", payload["context"])
        self.assertIn("feature_lifecycle_events", payload["context"])
        self.assertIn("editor_state", fake_router.last_plan_context)

    def test_execute_plan_accepts_edited_steps(self):
        fake_router = FakePlanRouter()
        with patch("api_server.main.manager.get_router", return_value=fake_router):
            client = TestClient(app)
            response = client.post(
                "/execute-plan",
                json={
                    "project_path": "default",
                    "task_id": "plan-1",
                    "prompt": "创建一个玩家场景并生成脚本",
                    "context": {
                        "foo": "bar",
                        "owner": "producer",
                        "priority": "high",
                        "risk": "medium",
                        "dependency": "art_pack",
                        "eta": "2026-05-01",
                        "validation_method": "portal smoke",
                        "blockers": ["补截图复审"],
                        "feature_status": "returned",
                        "required_followups": ["补截图复审"],
                        "acceptance_criteria": [
                            "逻辑接入完成",
                            "资源整理完成",
                        ],
                    },
                    "steps": [
                        {"name": "Logic", "description": "处理逻辑", "role": "code_generator", "status": "success"},
                        {
                            "name": "Review follow-up: 补截图复审",
                            "description": "Resolve returned review follow-up: 补截图复审",
                            "role": "tester",
                            "metadata": {"review_followup": True, "review_round": "r2"},
                        },
                    ]
                }
            )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["status"], "success")
        self.assertEqual([step["role"] for step in payload["steps"]], ["code_generator", "tester"])
        self.assertTrue(fake_router.last_execute_task.steps[1].metadata["review_followup"])
        self.assertEqual(fake_router.last_execute_task.steps[1].metadata["review_round"], "r2")
        self.assertEqual(fake_router.last_execute_task.role, "code_generator")
        self.assertEqual(fake_router.last_execute_task.context["foo"], "bar")
        self.assertEqual(fake_router.last_execute_task.context["owner"], "producer")
        self.assertEqual(payload["context"]["feature_status"], "pending_acceptance")
        self.assertEqual(payload["context"]["priority"], "high")
        self.assertEqual(payload["context"]["risk"], "medium")
        self.assertEqual(payload["context"]["dependency"], "art_pack")
        self.assertEqual(payload["context"]["eta"], "2026-05-01")
        self.assertEqual(payload["context"]["validation_method"], "portal smoke")
        self.assertEqual(payload["context"]["blockers"], [])
        self.assertEqual(payload["context"]["required_followups"], [])
        self.assertEqual(payload["context"]["feature_lifecycle_events"][-1]["event_type"], "review_followups_completed")
        self.assertEqual(payload["context"]["acceptance_checklist"][0]["label"], "逻辑接入完成")
        self.assertEqual(payload["context"]["acceptance_checklist"][0]["validation_method"], "portal smoke")
        self.assertEqual(payload["context"]["acceptance_checklist"][0]["blockers"], [])
        self.assertEqual(payload["context"]["artifact_links"], [])
        self.assertTrue(any("完成步骤 2/2" in line for line in payload["context"]["change_summary"]))
        self.assertIn("editor_state", fake_router.last_execute_task.context)

    def test_feature_review_endpoint_updates_status_and_note(self):
        fake_router = FakePlanRouter()
        task = Task(prompt="创建一个玩家场景并生成脚本", status=TaskStatus.SUCCESS, context={
            "feature_id": "feature-plan1",
            "feature_status": "pending_acceptance",
            "acceptance_criteria": ["逻辑接入完成"],
            "dependency": "qa_capture",
            "validation_method": "manual screenshot review",
        })
        task.task_id = "plan-1"
        task.steps = [
            TaskStep(name="Logic", description="处理逻辑", role="code_generator", status=TaskStatus.SUCCESS),
        ]
        fake_router.held_task = task

        with patch("api_server.main.manager.get_router", return_value=fake_router):
            client = TestClient(app)
            response = client.post(
                "/history/plan-1/feature-review",
                params={"project_path": "default"},
                json={
                    "feature_status": "returned",
                    "review_note": "需要补充验收截图",
                    "reviewer": "qa_lead",
                    "review_round": "r2",
                    "required_followups": ["补截图复审"],
                    "eta": "2026-05-02",
                    "blockers": ["缺验收截图"],
                    "external_links": [
                        {"label": "验收截图", "url": "https://example.test/review/screenshot", "type": "screenshot", "status": "passed"},
                    ],
                }
            )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["context"]["feature_status"], "returned")
        self.assertEqual(payload["context"]["feature_review_note"], "需要补充验收截图")
        self.assertEqual(payload["context"]["dependency"], "qa_capture")
        self.assertEqual(payload["context"]["eta"], "2026-05-02")
        self.assertEqual(payload["context"]["validation_method"], "manual screenshot review")
        self.assertEqual(payload["context"]["blockers"], ["缺验收截图", "补截图复审"])
        self.assertEqual(payload["context"]["reviewer"], "qa_lead")
        self.assertEqual(payload["context"]["review_round"], "r2")
        self.assertEqual(payload["context"]["required_followups"], ["补截图复审"])
        self.assertEqual(payload["context"]["external_links"][0]["label"], "验收截图")
        self.assertEqual(payload["context"]["external_links"][0]["type"], "screenshot")
        self.assertEqual(payload["context"]["feature_review_history"][-1]["feature_status"], "returned")
        self.assertEqual(payload["context"]["feature_review_history"][-1]["reviewer"], "qa_lead")
        self.assertEqual(payload["context"]["feature_review_history"][-1]["review_round"], "r2")
        self.assertEqual(payload["context"]["feature_review_history"][-1]["required_followups"], ["补截图复审"])
        lifecycle_event_types = [item["event_type"] for item in payload["context"]["feature_lifecycle_events"]]
        self.assertIn("review_returned", lifecycle_event_types)
        self.assertEqual(payload["context"]["feature_lifecycle_events"][-1]["event_type"], "review_followups_planned")
        self.assertIn("1 个复审待办步骤", payload["context"]["feature_lifecycle_events"][-1]["summary"])
        self.assertEqual(payload["context"]["contract_versions"]["feature_context"], "1.5")
        self.assertIn("需要补充验收截图", payload["logs"][-1])
        self.assertEqual(payload["steps"][-1]["name"], "Review follow-up: 补截图复审")
        self.assertEqual(payload["steps"][-1]["role"], "tester")
        self.assertTrue(payload["steps"][-1]["metadata"]["review_followup"])
        self.assertEqual(payload["steps"][-1]["metadata"]["review_round"], "r2")

    def test_feature_review_batch_updates_pending_acceptance_tasks(self):
        fake_router = FakeHistoryRouter()
        with patch("api_server.main.manager.get_router", return_value=fake_router):
            client = TestClient(app)
            response = client.post(
                "/history/feature-review-batch",
                params={"project_path": "default"},
                json={
                    "task_ids": ["task-b", "task-c"],
                    "feature_status": "approved",
                    "review_note": "批量二次验收通过",
                    "reviewer": "qa_lead",
                    "review_round": "batch-r2",
                },
            )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["requested_count"], 2)
        self.assertEqual(payload["selected_count"], 2)
        self.assertEqual(payload["updated_count"], 2)
        self.assertEqual(payload["error_count"], 0)
        self.assertFalse(payload["dry_run"])
        self.assertEqual(fake_router.tasks["task-b"].context["feature_status"], "approved")
        self.assertEqual(fake_router.tasks["task-c"].context["feature_status"], "approved")
        self.assertEqual(fake_router.tasks["task-b"].context["blockers"], [])
        self.assertEqual(fake_router.tasks["task-b"].context["feature_review_history"][-1]["reviewer"], "qa_lead")
        self.assertEqual(fake_router.tasks["task-b"].context["feature_review_history"][-1]["review_round"], "batch-r2")
        self.assertEqual(fake_router.tasks["task-b"].context["feature_lifecycle_events"][-1]["event_type"], "review_approved")

    def test_feature_review_batch_can_preview_filtered_tasks(self):
        fake_router = FakeHistoryRouter()
        with patch("api_server.main.manager.get_router", return_value=fake_router):
            client = TestClient(app)
            response = client.post(
                "/history/feature-review-batch",
                params={"project_path": "default"},
                json={
                    "feature_status": "returned",
                    "source_feature_status": "pending_acceptance",
                    "owner": "producer-b",
                    "limit": 1,
                    "dry_run": True,
                },
            )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["dry_run"])
        self.assertEqual(payload["requested_count"], 1)
        self.assertEqual(payload["selected_count"], 1)
        self.assertEqual(payload["updated_count"], 0)
        self.assertEqual(payload["filters"]["owner"], "producer-b")
        self.assertEqual(payload["items"][0]["task_id"], "task-b")
        self.assertEqual(fake_router.tasks["task-b"].context["feature_status"], "pending_acceptance")

    def test_feature_review_batch_rejects_invalid_source_status(self):
        with patch("api_server.main.manager.get_router", return_value=FakeHistoryRouter()):
            client = TestClient(app)
            response = client.post(
                "/history/feature-review-batch",
                params={"project_path": "default"},
                json={
                    "feature_status": "approved",
                    "source_feature_status": "unknown",
                },
            )

        self.assertEqual(response.status_code, 400)

    def test_history_endpoint_returns_feature_status_context(self):
        fake_router = FakeHistoryRouter()
        with patch("api_server.main.manager.get_router", return_value=fake_router):
            client = TestClient(app)
            response = client.get("/history", params={"project_path": "default", "limit": 10})

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["count"], 3)
        self.assertEqual(payload["matched_count"], 3)
        self.assertEqual(payload["items"][0]["task_id"], "task-a")
        self.assertEqual(payload["items"][0]["context"]["feature_status"], "approved")
        self.assertEqual(payload["items"][1]["context"]["feature_status"], "pending_acceptance")
        self.assertEqual(payload["items"][2]["context"]["feature_status"], "pending_acceptance")

    def test_history_endpoint_filters_by_feature_fields(self):
        fake_router = FakeHistoryRouter()
        with patch("api_server.main.manager.get_router", return_value=fake_router):
            client = TestClient(app)
            response = client.get(
                "/history",
                params={
                    "project_path": "default",
                    "limit": 1,
                    "feature_status": "pending_acceptance",
                    "owner": "producer-b",
                },
            )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["count"], 1)
        self.assertEqual(payload["matched_count"], 2)
        self.assertEqual(payload["items"][0]["task_id"], "task-b")
        self.assertEqual(payload["filters"]["feature_status"], "pending_acceptance")
        self.assertEqual(payload["filters"]["owner"], "producer-b")

    def test_history_endpoint_supports_offset_pagination(self):
        fake_router = FakeHistoryRouter()
        with patch("api_server.main.manager.get_router", return_value=fake_router):
            client = TestClient(app)
            response = client.get(
                "/history",
                params={"project_path": "default", "limit": 1, "offset": 1},
            )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["count"], 1)
        self.assertEqual(payload["matched_count"], 3)
        self.assertEqual(payload["offset"], 1)
        self.assertEqual(payload["limit"], 1)
        self.assertTrue(payload["has_more"])
        self.assertEqual(payload["prev_offset"], 0)
        self.assertEqual(payload["next_offset"], 2)
        self.assertEqual(payload["items"][0]["task_id"], "task-b")

    def test_history_endpoint_rejects_invalid_feature_status_filter(self):
        fake_router = FakeHistoryRouter()
        with patch("api_server.main.manager.get_router", return_value=fake_router):
            client = TestClient(app)
            response = client.get(
                "/history",
                params={"project_path": "default", "feature_status": "done"},
            )

        self.assertEqual(response.status_code, 400)
        self.assertIn("Unsupported feature_status", response.json()["detail"])

    def test_rollback_endpoint_persists_review_context(self):
        fake_router = FakeHistoryRouter()
        with patch("api_server.main.manager.get_router", return_value=fake_router):
            client = TestClient(app)
            response = client.post("/history/task-a/rollback", params={"project_path": "default"})

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["ok"])
        self.assertIsNotNone(fake_router.saved_task)
        self.assertEqual(fake_router.saved_task.status, TaskStatus.ROLLED_BACK)
        self.assertEqual(fake_router.saved_task.context["feature_id"], "feature-a")
        self.assertEqual(fake_router.saved_task.context["feature_lifecycle_events"][-1]["event_type"], "rollback")
        self.assertEqual(response.json()["task"]["context"]["feature_lifecycle_events"][-1]["event_type"], "rollback")

    def test_retry_endpoint_preserves_feature_timeline(self):
        fake_router = FakePlanRouter()
        task = Task(prompt="创建一个玩家场景并生成脚本", status=TaskStatus.SUCCESS, context={
            "feature_id": "feature-plan1",
            "feature_status": "returned",
            "feature_review_history": [{"feature_status": "returned", "review_note": "补测"}],
        })
        task.task_id = "plan-1"
        task.steps = [
            TaskStep(name="Logic", description="处理逻辑", role="code_generator", status=TaskStatus.FAILED),
        ]
        fake_router.held_task = task

        with patch("api_server.main.manager.get_router", return_value=fake_router):
            client = TestClient(app)
            response = client.post("/history/plan-1/retry", params={"project_path": "default"})

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["context"]["feature_id"], "feature-plan1")
        self.assertEqual(payload["context"]["feature_review_history"][-1]["feature_status"], "returned")
        self.assertEqual(payload["context"]["feature_lifecycle_events"][-1]["event_type"], "retry")

    @patch("agent_system.router.GodotCLI", ApiDataTableGodotCLI)
    def test_data_tables_endpoint_returns_catalog(self):
        from agent_system.router import GodotAgentRouter

        temp_project = project_root / "tests" / ".tmp_api_data_tables_catalog"
        shutil.rmtree(temp_project, ignore_errors=True)
        try:
            data_dir = temp_project / "data_tables"
            data_dir.mkdir(parents=True, exist_ok=True)
            (data_dir / "dialogue.csv").write_text(
                "dialogue_id,speaker,text,emotion,next_id\n"
                "dlg_intro,Guide,欢迎,smile,\n",
                encoding="utf-8",
            )

            router = GodotAgentRouter(godot_project_path=str(temp_project))
            with patch("api_server.main.manager.get_router", return_value=router):
                client = TestClient(app)
                response = client.get("/data-tables", params={"project_path": str(temp_project)})
        finally:
            shutil.rmtree(temp_project, ignore_errors=True)

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["default_table_type"], "dialogue")
        self.assertEqual(len(payload["items"]), 5)
        dialogue_item = next(item for item in payload["items"] if item["table_type"] == "dialogue")
        self.assertTrue(dialogue_item["exists"])
        self.assertEqual(dialogue_item["row_count"], 1)
        self.assertEqual(dialogue_item["label"], "对白表")

    @patch("agent_system.router.GodotCLI", ApiDataTableGodotCLI)
    def test_data_table_table_endpoint_returns_rows_and_schema(self):
        from agent_system.router import GodotAgentRouter

        temp_project = project_root / "tests" / ".tmp_api_data_tables_table"
        shutil.rmtree(temp_project, ignore_errors=True)
        try:
            data_dir = temp_project / "data_tables"
            data_dir.mkdir(parents=True, exist_ok=True)
            (data_dir / "quests.csv").write_text(
                "quest_id,title,description,target_count,reward_gold,next_quest_id\n"
                "quest_intro,收集金币,收集 5 枚金币,5,100,\n",
                encoding="utf-8",
            )

            router = GodotAgentRouter(godot_project_path=str(temp_project))
            with patch("api_server.main.manager.get_router", return_value=router):
                client = TestClient(app)
                response = client.get(
                    "/data-tables/table",
                    params={"project_path": str(temp_project), "table_type": "quest"},
                )
        finally:
            shutil.rmtree(temp_project, ignore_errors=True)

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["table_type"], "quest")
        self.assertTrue(payload["exists"])
        self.assertEqual(payload["row_count"], 1)
        self.assertEqual(payload["rows"][0]["quest_id"], "quest_intro")
        self.assertEqual(payload["columns"][0], "quest_id")

    @patch("agent_system.router.GodotCLI", ApiDataTableGodotCLI)
    def test_manage_data_table_endpoint_can_preview_and_apply_rows(self):
        from agent_system.router import GodotAgentRouter

        temp_project = project_root / "tests" / ".tmp_api_data_tables_manage"
        shutil.rmtree(temp_project, ignore_errors=True)
        try:
            router = GodotAgentRouter(godot_project_path=str(temp_project))
            with patch("api_server.main.manager.get_router", return_value=router):
                client = TestClient(app)
                preview_response = client.post(
                    "/data-tables/manage",
                    json={
                        "project_path": str(temp_project),
                        "action": "preview",
                        "table_type": "loot",
                        "rows": [
                            {"loot_id": "loot_coin", "item_id": "coin", "drop_rate": "0.5", "quantity": "2"},
                        ],
                    },
                )
                apply_response = client.post(
                    "/data-tables/manage",
                    json={
                        "project_path": str(temp_project),
                        "action": "apply",
                        "table_type": "localization",
                        "rows": [
                            {"key": "ui.start", "zh_CN": "开始", "en_US": "Start", "notes": "主菜单"},
                        ],
                    },
                )
        finally:
            applied_path = temp_project / "data_tables" / "localization.csv"
            applied_exists = applied_path.exists()
            applied_content = applied_path.read_text(encoding="utf-8") if applied_exists else ""
            shutil.rmtree(temp_project, ignore_errors=True)

        self.assertEqual(preview_response.status_code, 200)
        preview_payload = preview_response.json()
        self.assertEqual(preview_payload["status"], "success")
        self.assertEqual(preview_payload["context"]["data_table_type"], "loot")
        self.assertEqual(preview_payload["data_table"]["row_count"], 1)
        self.assertEqual(preview_payload["data_table"]["rows"][0]["loot_id"], "loot_coin")

        self.assertEqual(apply_response.status_code, 200)
        apply_payload = apply_response.json()
        self.assertEqual(apply_payload["status"], "success")
        self.assertTrue(apply_payload["context"]["data_table_written"])
        self.assertEqual(apply_payload["data_table"]["table_type"], "localization")
        self.assertTrue(applied_exists)
        self.assertIn("ui.start", applied_content)

    @patch("agent_system.router.GodotCLI", ApiDataTableGodotCLI)
    def test_manage_level_workflow_endpoint_can_template_snapshot_and_diff(self):
        from agent_system.router import GodotAgentRouter

        temp_project = project_root / "tests" / ".tmp_api_level_workflow_manage"
        snapshot_a = project_root / "logs" / "test_artifacts" / "api_level_snapshot_a.json"
        snapshot_b = project_root / "logs" / "test_artifacts" / "api_level_snapshot_b.json"
        shutil.rmtree(temp_project, ignore_errors=True)
        snapshot_a.unlink(missing_ok=True)
        snapshot_b.unlink(missing_ok=True)
        try:
            router = GodotAgentRouter(godot_project_path=str(temp_project))
            with patch("api_server.main.manager.get_router", return_value=router):
                client = TestClient(app)
                template_response = client.post(
                    "/levels/manage",
                    json={
                        "project_path": str(temp_project),
                        "action": "template",
                        "level_name": "api_route",
                        "level_type": "hub",
                    },
                )
                snapshot_response = client.post(
                    "/levels/manage",
                    json={
                        "project_path": str(temp_project),
                        "action": "snapshot",
                        "level_name": "api_route",
                        "level_type": "hub",
                        "snapshot_path": str(snapshot_a),
                    },
                )
                scene_path = temp_project / "scenes" / "levels" / "api_route.tscn"
                scene_path.write_text(
                    scene_path.read_text(encoding="utf-8") + '[node name="ExtraCheckpoint" type="Marker2D" parent="."]\n\n',
                    encoding="utf-8",
                )
                diff_response = client.post(
                    "/levels/manage",
                    json={
                        "project_path": str(temp_project),
                        "action": "diff",
                        "level_name": "api_route",
                        "level_type": "hub",
                        "snapshot_path": str(snapshot_b),
                        "compare_snapshot_path": str(snapshot_a),
                    },
                )
        finally:
            snapshot_a.unlink(missing_ok=True)
            snapshot_b.unlink(missing_ok=True)
            shutil.rmtree(temp_project, ignore_errors=True)

        self.assertEqual(template_response.status_code, 200)
        template_payload = template_response.json()
        self.assertEqual(template_payload["status"], "success")
        self.assertEqual(template_payload["context"]["last_skill_result"]["skill_name"], "manage_level_workflow")
        self.assertEqual(template_payload["level_workflow"]["level_manifest"]["schema_version"], "1.1")
        self.assertEqual(template_payload["level_workflow"]["level_manifest"]["level_type"], "hub")

        self.assertEqual(snapshot_response.status_code, 200)
        snapshot_payload = snapshot_response.json()
        self.assertEqual(snapshot_payload["status"], "success")
        self.assertGreater(snapshot_payload["level_workflow"]["snapshot"]["node_count"], 0)

        self.assertEqual(diff_response.status_code, 200)
        diff_payload = diff_response.json()
        self.assertEqual(diff_payload["status"], "success")
        self.assertEqual(diff_payload["level_workflow"]["diff"]["status"], "changed")
        self.assertTrue(any(
            node["path"] == "ExtraCheckpoint"
            for node in diff_payload["level_workflow"]["diff"]["added_nodes"]
        ))

    @patch("agent_system.router.GodotCLI", ApiDataTableGodotCLI)
    def test_manage_level_workflow_endpoint_surfaces_audit_failures(self):
        from agent_system.router import GodotAgentRouter

        temp_project = project_root / "tests" / ".tmp_api_level_workflow_audit"
        shutil.rmtree(temp_project, ignore_errors=True)
        try:
            scene_path = temp_project / "scenes" / "levels" / "broken_level.tscn"
            manifest_path = temp_project / "data_tables" / "levels" / "broken_level.json"
            scene_path.parent.mkdir(parents=True, exist_ok=True)
            manifest_path.parent.mkdir(parents=True, exist_ok=True)
            scene_path.write_text(
                '[gd_scene format=3]\n'
                '\n'
                '[node name="BrokenLevel" type="Node2D"]\n'
                '[node name="PlayerSpawn" type="Marker2D" parent="."]\n'
                '[node name="LevelExit" type="Marker2D" parent="."]\n',
                encoding="utf-8",
            )
            manifest_path.write_text(
                json.dumps({
                    "schema_version": "1.1",
                    "level_id": "broken_level",
                    "level_type": "combat",
                    "scene_path": "res://scenes/levels/broken_level.tscn",
                    "spawn_points": [{"id": "player_spawn", "node_path": "PlayerSpawn", "kind": "spawn"}],
                    "interaction_points": [{"id": "level_exit", "node_path": "LevelExit", "kind": "exit"}],
                    "checkpoints": [],
                    "navigation_zones": [],
                    "navigation_agents": [{"id": "enemy_agent", "node_path": "EnemyNavigationAgent", "kind": "enemy"}],
                    "tile_layers": [{"id": "ground", "node_path": "TileLayerGround", "kind": "ground"}],
                    "trigger_zones": [{"id": "exit_trigger", "node_path": "TriggerLevelExit", "kind": "exit"}],
                    "collision_layers": [],
                    "level_bounds": {"min": [0, 0], "max": [100, 100]},
                    "critical_path": ["player_spawn", "level_exit"],
                }, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )

            router = GodotAgentRouter(godot_project_path=str(temp_project))
            with patch("api_server.main.manager.get_router", return_value=router):
                client = TestClient(app)
                response = client.post(
                    "/levels/manage",
                    json={
                        "project_path": str(temp_project),
                        "action": "audit",
                        "level_name": "broken_level",
                        "scene_path": "res://scenes/levels/broken_level.tscn",
                        "manifest_path": "data_tables/levels/broken_level.json",
                    },
                )
        finally:
            shutil.rmtree(temp_project, ignore_errors=True)

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["status"], "failed")
        self.assertEqual(payload["context"]["last_skill_result"]["skill_name"], "manage_level_workflow")
        self.assertFalse(payload["context"]["last_skill_result"]["validation"]["passed"])
        self.assertTrue(any("EnemyNavigationAgent" in issue for issue in payload["level_workflow"]["audit"]["issues"]))

    def test_art_asset_profiles_endpoint_returns_snapshots(self):
        client = TestClient(app)
        list_response = client.get("/art-assets/profiles", params={"project_path": "default"})
        detail_response = client.get(
            "/art-assets/profiles",
            params={"project_path": "default", "asset_type": "model"},
        )

        self.assertEqual(list_response.status_code, 200)
        list_payload = list_response.json()
        self.assertGreaterEqual(list_payload["count"], 10)
        self.assertTrue(any(item["asset_type"] == "model" for item in list_payload["items"]))
        self.assertTrue(any(item["asset_type"] == "outsource" for item in list_payload["items"]))

        self.assertEqual(detail_response.status_code, 200)
        detail_payload = detail_response.json()
        self.assertEqual(detail_payload["asset_type"], "model")
        self.assertEqual(detail_payload["schema_version"], "1.1")
        self.assertEqual(detail_payload["display_path"], "assets/manifests/model_assets.json")
        self.assertEqual(detail_payload["entry_count"], 0)

    def test_portal_index_exposes_art_asset_intake_panel(self):
        client = TestClient(app)
        response = client.get("/portal/index.html")

        self.assertEqual(response.status_code, 200)
        self.assertIn("美术资产 Intake", response.text)
        self.assertIn("art-asset-type-select", response.text)
        self.assertIn("/art-assets/manage", response.text)

    def test_portal_index_exposes_outsource_delivery_gate_panel(self):
        client = TestClient(app)
        response = client.get("/portal/index.html")

        self.assertEqual(response.status_code, 200)
        self.assertIn("外包交付 Gate", response.text)
        self.assertIn("outsource-gate-manifest-input", response.text)
        self.assertIn("/outsource-delivery/gate", response.text)

    def test_portal_index_exposes_asset_review_panel(self):
        client = TestClient(app)
        response = client.get("/portal/index.html")

        self.assertEqual(response.status_code, 200)
        self.assertIn("资产评审", response.text)
        self.assertIn("asset-review-type-select", response.text)
        self.assertIn("/asset-reviews/workflow", response.text)
        self.assertIn("/asset-reviews/manage", response.text)

    def test_portal_index_exposes_scene_ownership_panel(self):
        client = TestClient(app)
        response = client.get("/portal/index.html")

        self.assertEqual(response.status_code, 200)
        self.assertIn("场景归属 / 锁定", response.text)
        self.assertIn("scene-ownership-board-input", response.text)
        self.assertIn("/scene-ownership/board", response.text)
        self.assertIn("/scene-ownership/manage", response.text)

    def test_portal_index_exposes_presentation_pipeline_panel(self):
        client = TestClient(app)
        response = client.get("/portal/index.html")

        self.assertEqual(response.status_code, 200)
        self.assertIn("表现层 Pipeline", response.text)
        self.assertIn("presentation-type-select", response.text)
        self.assertIn("/presentation/manage", response.text)

    def test_portal_index_exposes_telemetry_panel(self):
        client = TestClient(app)
        response = client.get("/portal/index.html")

        self.assertEqual(response.status_code, 200)
        self.assertIn("遥测回流", response.text)
        self.assertIn("telemetry-catalog-path-input", response.text)
        self.assertIn("/telemetry/manage", response.text)
        self.assertIn("Privacy Gate", response.text)
        self.assertIn("Crash Clusters", response.text)
        self.assertIn("Retention / Funnel Dashboard", response.text)
        self.assertIn("Retention / Funnel Trends", response.text)
        self.assertIn("LiveOps Impact", response.text)
        self.assertIn("导出留存漏斗报告", response.text)
        self.assertIn("导出趋势报告", response.text)
        self.assertIn("导出 Crash 报告", response.text)
        self.assertIn("/telemetry/retention-dashboard", response.text)
        self.assertIn("/telemetry/trends", response.text)
        self.assertIn("/telemetry/crash-dashboard", response.text)

    def test_portal_index_exposes_performance_panel(self):
        client = TestClient(app)
        response = client.get("/portal/index.html")

        self.assertEqual(response.status_code, 200)
        self.assertIn("性能分析", response.text)
        self.assertIn("performance-scene-path-input", response.text)
        self.assertIn("Frame Breakdown", response.text)
        self.assertIn("Memory Trend", response.text)
        self.assertIn("导出画像报告", response.text)
        self.assertIn("/performance/dashboard", response.text)
        self.assertIn("/performance/manage", response.text)

    def test_portal_index_exposes_liveops_panel(self):
        client = TestClient(app)
        response = client.get("/portal/index.html")

        self.assertEqual(response.status_code, 200)
        self.assertIn("运营配置 / LiveOps", response.text)
        self.assertIn("liveops-type-select", response.text)
        self.assertIn("影响报告", response.text)
        self.assertIn("/liveops/impact-dashboard", response.text)
        self.assertIn("/liveops/manage", response.text)

    def test_portal_index_exposes_platform_delivery_panel(self):
        client = TestClient(app)
        response = client.get("/portal/index.html")

        self.assertEqual(response.status_code, 200)
        self.assertIn("平台交付 / Savegame", response.text)
        self.assertIn("platform-delivery-manifest-input", response.text)
        self.assertIn("/platform-delivery/profile", response.text)
        self.assertIn("/platform-delivery/manage", response.text)

    def test_portal_index_exposes_release_candidate_panel(self):
        client = TestClient(app)
        response = client.get("/portal/index.html")

        self.assertEqual(response.status_code, 200)
        self.assertIn("Release Candidate", response.text)
        self.assertIn("Assertion QA", response.text)
        self.assertIn("Visual Regression", response.text)
        self.assertIn("release-candidate-manifest-input", response.text)
        self.assertIn("/release-candidate/checklist", response.text)

    def test_portal_index_exposes_build_run_matrix_panel(self):
        client = TestClient(app)
        response = client.get("/portal/index.html")

        self.assertEqual(response.status_code, 200)
        self.assertIn("Build / Run Matrix", response.text)
        self.assertIn("build-run-matrix-manifest-input", response.text)
        self.assertIn("/build-run/matrix", response.text)

    def test_portal_index_exposes_release_promotion_panel(self):
        client = TestClient(app)
        response = client.get("/portal/index.html")

        self.assertEqual(response.status_code, 200)
        self.assertIn("Release Promotion", response.text)
        self.assertIn("release-promotion-target-select", response.text)
        self.assertIn("release-promotion-decision-select", response.text)
        self.assertIn("release-promotion-history-path-input", response.text)
        self.assertIn("release-promotion-history-live-ci-select", response.text)
        self.assertIn("release-promotion-history-readiness-select", response.text)
        self.assertIn("release-promotion-history-readiness-action-input", response.text)
        self.assertIn("release-promotion-history-dispatch-select", response.text)
        self.assertIn("release-promotion-history-dispatch-follow-up-select", response.text)
        self.assertIn("release-promotion-history-dispatch-run-status-select", response.text)
        self.assertIn("release-promotion-history-dispatch-conclusion-input", response.text)
        self.assertIn("release-promotion-history-step-input", response.text)
        self.assertIn("release-promotion-history-list", response.text)
        self.assertIn("/release-promotion/plan", response.text)
        self.assertIn("/release-promotion/review-bundle", response.text)
        self.assertIn("/release-promotion/evidence-report", response.text)
        self.assertIn("syncReleaseChannelPolicy", response.text)
        self.assertIn("/release-promotion/deployment-rehearsal", response.text)
        self.assertIn("/release-promotion/rollback-rehearsal", response.text)
        self.assertIn("/release-promotion/history", response.text)
        self.assertIn("/release-promotion/history-report", response.text)
        self.assertIn("live_ci_status", response.text)
        self.assertIn("delivery_readiness_status", response.text)
        self.assertIn("readiness_action", response.text)
        self.assertIn("failed_workflow_step", response.text)
        self.assertIn("/release-promotion/record", response.text)
        self.assertIn("导出 History Report", response.text)
        self.assertIn("Live CI:", response.text)
        self.assertIn("failed_steps=", response.text)
        self.assertIn("workflow_results=", response.text)
        self.assertIn("review_followup_actions", response.text)
        self.assertIn("Review Follow-up Actions", response.text)
        self.assertIn("review_followups=", response.text)
        self.assertIn("release_delivery_readiness_next_actions", response.text)
        self.assertIn("Delivery Readiness:", response.text)
        self.assertIn("Readiness Filter:", response.text)
        self.assertIn("readiness_actions=", response.text)
        self.assertIn("执行复审待办", response.text)
        self.assertIn("reviewFollowupsOnly", response.text)
        self.assertIn("'cancelled'", response.text)
        self.assertIn("/history/feature-review-batch", response.text)
        self.assertIn("当前页待验收全通过", response.text)
        self.assertIn("submitHistoryFeatureReviewBatch", response.text)
        self.assertIn("source_feature_status", response.text)
        self.assertIn("dry_run", response.text)
        self.assertIn("window.confirm", response.text)
        self.assertIn("metadata: { ...(step.metadata || {}) }", response.text)
        self.assertIn("dispatch=", response.text)
        self.assertIn("dispatch_follow_up=", response.text)
        self.assertIn("historyDispatchSelect.value = state.history_dispatch_status || ''", response.text)
        self.assertIn("historyReadinessSelect.value = state.history_delivery_readiness_status || ''", response.text)
        self.assertIn("historyReadinessActionInput.value = state.history_readiness_action || ''", response.text)
        self.assertIn("historyDispatchFollowUpSelect.value = state.history_dispatch_follow_up || ''", response.text)
        self.assertIn("historyDispatchRunStatusSelect.value = state.history_dispatch_run_status || ''", response.text)
        self.assertIn("historyDispatchConclusionInput.value = state.history_dispatch_run_conclusion || ''", response.text)

    def test_portal_index_exposes_release_capability_registry_panel(self):
        client = TestClient(app)
        response = client.get("/portal/index.html")

        self.assertEqual(response.status_code, 200)
        self.assertIn("Release Capability Registry", response.text)
        self.assertIn("release-capability-registry-path-input", response.text)
        self.assertIn("/release-capability-registry", response.text)
        self.assertIn("/release-capability-registry/report", response.text)
        self.assertIn("导出 Capability Report", response.text)

    def test_portal_index_exposes_release_capability_policy_panel(self):
        client = TestClient(app)
        response = client.get("/portal/index.html")

        self.assertEqual(response.status_code, 200)
        self.assertIn("Release Capability Policy", response.text)
        self.assertIn("release-capability-policy-route-select", response.text)
        self.assertIn("release-capability-policy-target-select", response.text)
        self.assertIn("release-capability-policy-actor-input", response.text)
        self.assertIn("/release-capability-policy", response.text)
        self.assertIn("/release-capability-policy/report", response.text)
        self.assertIn("contracts=${escapeHtml((item.artifact_contracts", response.text)
        self.assertIn("entrypoints=${escapeHtml((item.entrypoints", response.text)
        self.assertIn("导出 Capability Policy", response.text)

    def test_portal_index_exposes_release_delivery_readiness_panel(self):
        client = TestClient(app)
        response = client.get("/portal/index.html")

        self.assertEqual(response.status_code, 200)
        self.assertIn("Release Delivery Readiness", response.text)
        self.assertIn("release-delivery-readiness-target-select", response.text)
        self.assertIn("release-delivery-readiness-artifact-dir-input", response.text)
        self.assertIn("/release-delivery-readiness", response.text)
        self.assertIn("/release-delivery-readiness/report", response.text)
        self.assertIn("导出 Delivery Readiness", response.text)

    def test_portal_index_exposes_release_execution_panel(self):
        client = TestClient(app)
        response = client.get("/portal/index.html")

        self.assertEqual(response.status_code, 200)
        self.assertIn("Release Execution", response.text)
        self.assertIn("release-execution-target-select", response.text)
        self.assertIn("release-execution-status-path-input", response.text)
        self.assertIn("/release-execution/status", response.text)
        self.assertIn("/release-execution/report", response.text)
        self.assertIn("/release-execution/run", response.text)
        self.assertIn("/release-execution/rollback", response.text)
        self.assertIn("导出 Execution Report", response.text)
        self.assertIn("review_followup_actions", response.text)
        self.assertIn("Review Follow-up Actions", response.text)
        self.assertIn("release_delivery_readiness", response.text)
        self.assertIn("Release Delivery Readiness", response.text)
        self.assertIn("Delivery Readiness:", response.text)
        self.assertIn("Latest Execution Readiness:", response.text)
        self.assertIn("delivery_readiness=", response.text)
        self.assertIn("readiness_actions=", response.text)
        self.assertIn("next_actions=", response.text)

    def test_portal_index_exposes_release_live_ci_panel(self):
        client = TestClient(app)
        response = client.get("/portal/index.html")

        self.assertEqual(response.status_code, 200)
        self.assertIn("Release Live CI", response.text)
        self.assertIn("release-live-ci-artifact-dir-input", response.text)
        self.assertIn("release-live-ci-dispatch-workflow-input", response.text)
        self.assertIn("release-live-ci-dispatch-token-env-input", response.text)
        self.assertIn("/release-live-ci/summary", response.text)
        self.assertIn("/release-artifact-manifest", response.text)
        self.assertIn("/release-live-ci/events", response.text)
        self.assertIn("/release-live-ci/summary-report", response.text)
        self.assertIn("/release-live-ci/dispatch-audit", response.text)
        self.assertIn("/release-live-ci/dispatch-preflight", response.text)
        self.assertIn("/release-live-ci/dispatch", response.text)
        self.assertIn("Runtime Assembly", response.text)
        self.assertIn("Capability Contracts", response.text)
        self.assertIn("artifact_contracts", response.text)
        self.assertIn("Artifact Manifest", response.text)
        self.assertIn("releaseArtifactManifest", response.text)
        self.assertIn("Event Stream", response.text)
        self.assertIn("Workflow Dispatch Preflight", response.text)
        self.assertIn("Workflow Dispatch Audit", response.text)
        self.assertIn("触发 Workflow Dispatch", response.text)
        self.assertIn("导出 Live CI Summary", response.text)

    def test_release_capability_registry_report_endpoint_returns_markdown(self):
        temp_project = project_root / "tests" / ".tmp_api_release_capability_registry"
        shutil.rmtree(temp_project, ignore_errors=True)
        try:
            manifest_path = temp_project / "deployment" / "release_capability_registry.json"
            manifest_path.parent.mkdir(parents=True, exist_ok=True)
            manifest_path.write_text(
                json.dumps(
                    {
                        "schema_version": "1.0",
                        "registry_id": "release_control_plane_capabilities",
                        "capabilities": [
                            {
                                "capability_id": "release_promotion_record_write",
                                "label": "Release Promotion Record",
                                "group": "release_control_plane",
                                "surface_types": ["command", "gateway_method"],
                                "risk_level": "high",
                                "requires_actor": True,
                                "requires_request_auth": True,
                                "default_enabled": True,
                                "optional_heavy": False,
                                "sandbox_profile": "release_write",
                                "artifact_contracts": ["release_promotion_history"],
                                "entrypoints": ["/release-promotion/record"],
                                "owners": ["ops", "release_manager"],
                            },
                            {
                                "capability_id": "portal_browser_click_smoke_run",
                                "label": "Portal Click Smoke",
                                "group": "release_runtime",
                                "surface_types": ["tool", "command"],
                                "risk_level": "medium",
                                "requires_actor": False,
                                "requires_request_auth": False,
                                "default_enabled": False,
                                "optional_heavy": True,
                                "sandbox_profile": "browser_automation",
                                "artifact_contracts": ["release_live_ci_summary", "release_artifact_manifest"],
                                "entrypoints": [
                                    "python tools/run_portal_browser_click_smoke.py",
                                    "/release-artifact-manifest",
                                ],
                                "owners": ["qa_lead"],
                            },
                        ],
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )

            client = TestClient(app)
            response = client.get(
                "/release-capability-registry/report",
                params={
                    "project_path": str(temp_project),
                    "registry_path": "deployment/release_capability_registry.json",
                },
            )

            self.assertEqual(response.status_code, 200)
            payload = response.json()
            self.assertEqual(payload["report_name"], "release_capability_registry.md")
            self.assertEqual(payload["registry"]["capability_count"], 2)
            self.assertEqual(payload["registry"]["surface_counts"]["command"], 2)
            self.assertIn("# Release Capability Registry", payload["report_content"])
            self.assertIn("`release_promotion_record_write` [passed]", payload["report_content"])
            self.assertIn("sandbox=browser_automation", payload["report_content"])
            self.assertIn("contracts=release_live_ci_summary,release_artifact_manifest", payload["report_content"])
            self.assertIn(
                "entrypoints=python tools/run_portal_browser_click_smoke.py,/release-artifact-manifest",
                payload["report_content"],
            )
        finally:
            shutil.rmtree(temp_project, ignore_errors=True)

    def test_release_capability_policy_report_endpoint_returns_markdown(self):
        temp_project = project_root / "tests" / ".tmp_api_release_capability_policy"
        shutil.rmtree(temp_project, ignore_errors=True)
        try:
            deployment_dir = temp_project / "deployment"
            deployment_dir.mkdir(parents=True, exist_ok=True)
            (deployment_dir / "release_capability_registry.json").write_text(
                json.dumps(
                    {
                        "schema_version": "1.0",
                        "registry_id": "release_control_plane_capabilities",
                        "capabilities": [
                            {
                                "capability_id": "release_execution_rollout_write",
                                "label": "Release Execution Rollout",
                                "group": "release_control_plane",
                                "surface_types": ["command", "gateway_method"],
                                "risk_level": "critical",
                                "requires_actor": True,
                                "requires_request_auth": True,
                                "default_enabled": True,
                                "optional_heavy": False,
                                "sandbox_profile": "release_write",
                                "artifact_contracts": ["release_execution_status"],
                                "entrypoints": ["/release-execution/run"],
                                "policy_action": "release_execution",
                                "policy_operation": "canary",
                                "owners": ["release_manager"],
                            },
                            {
                                "capability_id": "release_live_ci_summary_read",
                                "label": "Release Live CI Summary",
                                "group": "release_runtime",
                                "surface_types": ["command", "gateway_method"],
                                "risk_level": "medium",
                                "requires_actor": False,
                                "requires_request_auth": False,
                                "default_enabled": True,
                                "optional_heavy": False,
                                "sandbox_profile": "read_only",
                                "artifact_contracts": ["release_live_ci_summary", "release_artifact_manifest"],
                                "entrypoints": ["/release-live-ci/summary", "/release-artifact-manifest"],
                                "owners": ["qa_lead"],
                            }
                        ],
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )
            (deployment_dir / "release_access_policy.json").write_text(
                json.dumps(
                    {
                        "schema_version": "1.0",
                        "actors": [{"actor_id": "release_manager", "roles": ["release_manager"]}],
                        "rules": [
                            {
                                "rule_id": "execution_rollout_qa_staging",
                                "action": "release_execution",
                                "operations": ["canary", "full_rollout"],
                                "channels": ["qa", "staging"],
                                "roles": ["release_manager"],
                            }
                        ],
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )
            (deployment_dir / "release_request_auth.json").write_text(
                json.dumps(
                    {
                        "schema_version": "1.0",
                        "allow_local_without_token": True,
                        "tokens": [],
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )
            (deployment_dir / "release_identity_boundary.json").write_text(
                json.dumps(
                    {
                        "schema_version": "1.0",
                        "profiles": [
                            {
                                "profile_id": "staging_identity_boundary",
                                "target_channels": ["staging"],
                                "target_environments": ["staging"],
                                "provider_mode": "project_manifest",
                                "provider_id": "local_manifest",
                                "session_policy": {"required": False, "backend": "manifest", "max_session_age_hours": 0},
                                "secret_rotation": {"required": False, "backend": "manifest", "owner": "ops", "rotation_window_days": 30},
                            }
                        ],
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )

            client = TestClient(app)
            response = client.get(
                "/release-capability-policy/report",
                params={
                    "project_path": str(temp_project),
                    "route_kind": "portal",
                    "target_channel": "staging",
                    "target_environment": "staging",
                    "actor_id": "release_manager",
                },
            )

            self.assertEqual(response.status_code, 200)
            payload = response.json()
            self.assertEqual(payload["report_name"], "release_capability_policy.md")
            self.assertEqual(payload["policy"]["status"], "warning")
            self.assertEqual(payload["policy"]["allowed_count"], 1)
            self.assertEqual(payload["policy"]["warning_count"], 1)
            self.assertIn("# Release Capability Policy", payload["report_content"])
            self.assertIn("`release_execution_rollout_write` [warning]", payload["report_content"])
            self.assertIn("`release_live_ci_summary_read` [passed]", payload["report_content"])
            self.assertIn("request_auth_posture=warning", payload["report_content"])
            self.assertIn(
                "contracts=release_live_ci_summary,release_artifact_manifest",
                payload["report_content"],
            )
            self.assertIn(
                "entrypoints=/release-live-ci/summary,/release-artifact-manifest",
                payload["report_content"],
            )
        finally:
            shutil.rmtree(temp_project, ignore_errors=True)

    def test_release_delivery_readiness_report_endpoint_returns_markdown(self):
        temp_project = project_root / "tests" / ".tmp_api_release_delivery_readiness"
        shutil.rmtree(temp_project, ignore_errors=True)
        try:
            deployment_dir = temp_project / "deployment"
            reports_dir = temp_project / "logs" / "reports"
            live_ci_dir = reports_dir / "release_live_ci"
            deployment_dir.mkdir(parents=True, exist_ok=True)
            live_ci_dir.mkdir(parents=True, exist_ok=True)
            (deployment_dir / "release_request_auth.json").write_text(
                json.dumps({"schema_version": "1.0", "allow_local_without_token": False, "tokens": []}, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            (deployment_dir / "release_identity_registry.json").write_text(
                json.dumps(
                    {
                        "schema_version": "1.0",
                        "issuers": [
                            {
                                "issuer_id": "ops_release",
                                "status": "active",
                                "channels": ["release"],
                                "target_environments": ["production"],
                                "subject_actor_ids": ["release_manager"],
                                "session_required": True,
                                "max_session_age_hours": 24,
                            }
                        ],
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )
            (deployment_dir / "release_identity_boundary.json").write_text(
                json.dumps(
                    {
                        "schema_version": "1.0",
                        "profiles": [
                            {
                                "profile_id": "release_identity_boundary",
                                "target_channels": ["release"],
                                "target_environments": ["production"],
                                "provider_mode": "external_provider",
                                "provider_id": "entra_id",
                                "session_policy": {"required": True, "backend": "external_session", "max_session_age_hours": 24},
                                "secret_rotation": {"required": True, "backend": "vault", "owner": "ops_release", "rotation_window_days": 30},
                                "external_handoff": {"required": True, "mode": "external_intake", "target_id": "release_identity_intake", "owner": "security_ops"},
                            }
                        ],
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )
            (reports_dir / "release_distribution_bundle_release.json").write_text(
                json.dumps(
                    {
                        "schema_version": "1.0",
                        "status": "warning",
                        "summary": "delivery=warning / signing=warning / publish=warning / receipts=skipped",
                        "delivery_profile_id": "release_delivery",
                        "delivery_status": "warning",
                        "signing_handoff_status": "warning",
                        "publish_handoff_status": "warning",
                        "publish_receipts_status": "skipped",
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )
            (reports_dir / "release_live_runner_baseline_release.json").write_text(
                json.dumps(
                    {
                        "schema_version": "1.0",
                        "status": "passed",
                        "summary": "runner ok",
                        "runner_profile_id": "release_windows_runner",
                        "runner_name": "godot-release-01",
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )
            (live_ci_dir / "release_live_ci_summary.json").write_text(
                json.dumps(
                    {
                        "schema_version": "1.0",
                        "status": "warning",
                        "summary": "ci_gate=passed / source=local_replay",
                        "ci_gate": {"status": "passed", "should_block": False},
                        "runtime_gates": {
                            "release_live_runner_baseline_status": "passed",
                            "distribution_bundle_status": "warning",
                            "distribution_signing_handoff_status": "warning",
                            "distribution_publish_handoff_status": "warning",
                            "distribution_publish_receipts_status": "skipped",
                            "identity_handoff_status": "passed",
                        },
                        "invocation": {"source": "local_replay"},
                        "report_files": {"summary_markdown": "release_live_ci_summary.md"},
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )

            client = TestClient(app)
            response = client.get(
                "/release-delivery-readiness/report",
                params={
                    "project_path": str(temp_project),
                    "target_channel": "release",
                    "target_environment": "production",
                },
            )

            self.assertEqual(response.status_code, 200)
            payload = response.json()
            self.assertEqual(payload["report_name"], "release_delivery_readiness.md")
            self.assertIn("# Release Delivery Readiness", payload["report_content"])
            self.assertIn("## Components", payload["report_content"])
            self.assertIn("Self-Hosted Workflow Release", payload["report_content"])
            self.assertEqual(payload["readiness"]["component_count"], 3)
        finally:
            shutil.rmtree(temp_project, ignore_errors=True)

    def test_release_live_ci_summary_report_endpoint_returns_markdown(self):
        temp_project = project_root / "tests" / ".tmp_api_release_live_ci"
        shutil.rmtree(temp_project, ignore_errors=True)
        try:
            artifact_dir = temp_project / "logs" / "reports" / "release_live_ci"
            artifact_dir.mkdir(parents=True, exist_ok=True)
            (artifact_dir / "release_live_ci_summary.json").write_text(
                json.dumps(
                    {
                        "schema_version": "1.0",
                        "generated_at": "2026-04-18T10:00:00Z",
                        "target_channel": "release",
                        "target_environment": "production",
                        "release_manifest_path": "api_server/static/dist/release_manifest.json",
                        "release_build_id": "web-release-001",
                        "release_version": "1.0.0",
                        "release_channel": "release",
                        "invocation": {
                            "source": "github_workflow",
                            "providers": ["codex"],
                            "approvers": ["qa_lead", "tech_lead", "producer", "ops"],
                            "mode": "strict",
                            "fail_on_warnings": True,
                        },
                        "runtime_assembly": {
                            "schema_version": "1.0",
                            "status": "warning",
                            "summary": (
                                "route=github_workflow / actor=- / allowed=3 / warning=0 / "
                                "blocked=1 / identity=passed / runner_profile=release_windows_runner"
                            ),
                            "route_kind": "github_workflow",
                            "route_id": "github_workflow:release:production",
                            "session_id": "web-release-001",
                            "invocation_source": "github_workflow",
                            "actor_id": "",
                            "target_channel": "release",
                            "target_environment": "production",
                            "capability_count": 4,
                            "allowed_count": 3,
                            "warning_count": 0,
                            "denied_count": 1,
                            "skipped_count": 0,
                            "registry_path": "deployment/release_capability_registry.json",
                            "registry_status": "passed",
                            "route_profile": {
                                "interactive": False,
                                "live_runtime": True,
                                "requires_runner_profile": True,
                                "write_operations_enabled": False,
                            },
                            "auth_profile": {
                                "actor_present": False,
                                "requires_actor_count": 1,
                                "request_auth_required_count": 1,
                                "authorization_blocked_capability_ids": ["release_execution_rollout_write"],
                                "request_auth_warning_capability_ids": ["release_execution_rollout_write"],
                            },
                            "identity_boundary": {
                                "status": "passed",
                                "profile_id": "release_identity_boundary",
                                "provider_mode": "project_manifest",
                                "session_required": True,
                                "external_handoff_target_id": "release_identity_intake",
                            },
                            "runner_profile": {
                                "status": "passed",
                                "profile_id": "release_windows_runner",
                                "runner_name": "godot-release-01",
                                "runner_os": "Windows",
                                "runner_arch": "x64",
                                "runner_labels": ["self-hosted", "windows", "godot"],
                            },
                            "enabled_surface_types": ["tool", "command"],
                            "denied_surface_types": ["gateway_method"],
                            "enabled_sandbox_profiles": ["browser_automation"],
                            "denied_sandbox_profiles": ["release_write"],
                            "capabilities": [
                                {
                                    "capability_id": "release_execution_rollout_write",
                                    "policy_status": "blocked",
                                    "sandbox_profile": "release_write",
                                    "surface_types": ["command", "gateway_method"],
                                    "artifact_contracts": ["release_execution_status"],
                                    "entrypoints": ["/release-execution/run"],
                                    "denial_reasons": ["release_write_disabled"],
                                },
                                {
                                    "capability_id": "release_live_ci_summary_read",
                                    "policy_status": "passed",
                                    "sandbox_profile": "read_only",
                                    "surface_types": ["command", "gateway_method"],
                                    "artifact_contracts": ["release_live_ci_summary", "release_artifact_manifest"],
                                    "entrypoints": [
                                        "/release-live-ci/summary",
                                        "/release-live-ci/summary-report",
                                        "/release-artifact-manifest",
                                    ],
                                    "denial_reasons": [],
                                }
                            ],
                        },
                        "event_stream": {
                            "status": "warning",
                            "path": "release_live_ci_events.json",
                            "summary": "events=5 / blocked=1 / warning=1 / latest=run_finished",
                            "source": "live_ci_export",
                            "generated_at": "2026-04-18T10:00:00Z",
                            "route_kind": "github_workflow",
                            "route_id": "github_workflow:release:production",
                            "invocation_source": "github_workflow",
                            "release_build_id": "web-release-001",
                            "release_version": "1.0.0",
                            "release_channel": "release",
                            "target_channel": "release",
                            "target_environment": "production",
                            "event_count": 5,
                            "blocked_event_count": 1,
                            "warning_event_count": 1,
                            "latest_event_type": "run_finished",
                            "latest_event_status": "warning",
                            "events": [
                                {
                                    "event_id": "run_started_1",
                                    "event_type": "run_started",
                                    "scope": "run",
                                    "order": 1,
                                    "status": "passed",
                                    "occurred_at": "2026-04-18T10:00:00Z",
                                    "summary": "route=github_workflow",
                                },
                                {
                                    "event_id": "step_finished_2",
                                    "event_type": "step_finished",
                                    "scope": "workflow_step",
                                    "order": 2,
                                    "status": "blocked",
                                    "occurred_at": "2026-04-18T10:01:00Z",
                                    "step_id": "run_full_live_validation",
                                    "summary": "run_full_live_validation [blocked]",
                                },
                            ],
                        },
                        "ci_gate": {
                            "status": "passed",
                            "should_block": False,
                            "fail_on_warnings": True,
                            "blocking_checks": [],
                            "warning_checks": [],
                            "evaluated_check_count": 2,
                            "evaluated_checks": [],
                        },
                        "runtime_gates": {
                            "release_live_runner_baseline_status": "passed",
                            "full_live_validation_status": "passed",
                            "distribution_bundle_status": "passed",
                            "distribution_signing_handoff_status": "passed",
                            "distribution_publish_handoff_status": "passed",
                            "distribution_publish_receipts_status": "warning",
                            "identity_handoff_status": "passed",
                        },
                        "runtime_lanes": {
                            "full_live_validation": [
                                {
                                    "lane_id": "portal_click_smoke",
                                    "label": "Portal Click Smoke",
                                    "status": "passed",
                                    "summary": "click ok",
                                    "report_path": "logs/reports/full_live_validation_lanes/portal_click_smoke.json",
                                    "artifact_paths": ["logs/test_artifacts/portal_click_chrome_8014.out"],
                                    "flow_statuses": {
                                        "release_promotion_history_report_flow": "passed",
                                    },
                                }
                            ]
                        },
                        "workflow_steps": [
                            {
                                "step_id": "export_runner_baseline",
                                "label": "Export release-live runner baseline",
                                "status": "passed",
                                "outcome": "success",
                                "always_run": False,
                                "message": "",
                            },
                            {
                                "step_id": "run_full_live_validation",
                                "label": "Run full live validation",
                                "status": "blocked",
                                "outcome": "failure",
                                "always_run": False,
                                "message": "portal click smoke failed",
                            },
                        ],
                        "human_signoffs": {
                            "status": "warning",
                            "required_signoffs": ["qa_lead", "tech_lead", "producer", "ops"],
                            "provided_signoffs": [],
                            "missing_signoffs": ["qa_lead", "tech_lead", "producer", "ops"],
                        },
                        "report_files": {
                            "summary_markdown": "release_live_ci_summary.md",
                        },
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )
            (artifact_dir / "release_live_ci_summary.md").write_text(
                (
                    "# Release Live CI Summary\n\n"
                    "## Runtime Assembly\n"
                    "- Route: github_workflow / route_id=github_workflow:release:production / "
                    "session_id=web-release-001 / invocation=github_workflow\n"
                    "- Runner Profile: status=passed / profile=release_windows_runner / "
                    "name=godot-release-01 / os=Windows / arch=x64 / labels=self-hosted, windows, godot\n\n"
                    "## Event Stream\n"
                    "- Path: release_live_ci_events.json / source=live_ci_export / generated_at=2026-04-18T10:00:00Z\n"
                    "- Event (2): step_finished [blocked] / scope=workflow_step / step=run_full_live_validation / lane=- / summary=run_full_live_validation [blocked]\n\n"
                    "## Workflow Steps\n"
                    "- run_full_live_validation [blocked]\n\n"
                    "- portal_click_smoke [passed]\n"
                    "- release_promotion_history_report_flow=passed\n"
                ),
                encoding="utf-8",
            )
            (artifact_dir / "artifact_manifest.json").write_text(
                json.dumps(
                    {
                        "schema_version": "1.0",
                        "project_root": ".",
                        "runtime_root": ".",
                        "target_channel": "release",
                        "target_environment": "production",
                        "mode": "live_release_ci",
                        "release_build_id": "web-release-001",
                        "release_version": "1.0.0",
                        "release_channel": "release",
                        "release_summary": {"build_id": "web-release-001", "version": "1.0.0", "channel": "release"},
                        "runtime_assembly": {"route_kind": "github_workflow", "target_channel": "release"},
                        "event_stream": {"status": "passed", "path": "release_live_ci_events.json"},
                        "execution_delivery_readiness": {
                            "status": "warning",
                            "next_action_ids": ["external_distribution_delivery"],
                        },
                        "runtime_lanes": {"full_live_validation": [{"lane_id": "portal_click_smoke", "status": "passed"}]},
                        "generated_files": ["release_live_ci_summary.json"],
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )
            write_release_live_dispatch_audit(
                temp_project,
                artifact_dir="logs/reports/release_live_ci",
                preflight={
                    "schema_version": "1.0",
                    "status": "passed",
                    "ready": True,
                    "workflow": "release-live-gates.yml",
                    "repo": "sossossal/cim-comm-soc",
                    "ref": "main",
                    "dispatch_inputs": {
                        "target_channel": "release",
                        "target_environment": "production",
                    },
                },
                dispatch_result={
                    "schema_version": "1.0",
                    "ok": True,
                    "status": "warning",
                    "summary": "workflow_dispatch accepted for sossossal/cim-comm-soc@main",
                    "repo": "sossossal/cim-comm-soc",
                    "workflow": "release-live-gates.yml",
                    "ref": "main",
                    "wait": True,
                    "token_source": "GH_TOKEN",
                    "run": {
                        "id": 9001,
                        "number": 42,
                        "status": "completed",
                        "conclusion": "success",
                        "html_url": "https://github.com/sossossal/cim-comm-soc/actions/runs/9001",
                    },
                },
                request_auth={
                    "status": "passed",
                    "actor_id": "release_manager",
                    "token_id": "token-001",
                    "reason": "accepted",
                },
                triggered_by="release_manager",
            )

            client = TestClient(app)
            response = client.get(
                "/release-live-ci/summary-report",
                params={
                    "project_path": str(temp_project),
                    "artifact_dir": "logs/reports/release_live_ci",
                },
            )

            self.assertEqual(response.status_code, 200)
            payload = response.json()
            self.assertEqual(payload["report_name"], "release_live_ci_summary.md")
            self.assertEqual(payload["summary"]["release_build_id"], "web-release-001")
            self.assertEqual(payload["summary"]["artifact_dir"], "logs/reports/release_live_ci")
            self.assertTrue(payload["summary"]["summary_markdown_exists"])
            self.assertEqual(payload["summary"]["runtime_assembly"]["route_kind"], "github_workflow")
            self.assertEqual(
                payload["summary"]["runtime_assembly"]["runner_profile"]["profile_id"],
                "release_windows_runner",
            )
            live_summary_capability = next(
                item for item in payload["summary"]["runtime_assembly"]["capabilities"]
                if item["capability_id"] == "release_live_ci_summary_read"
            )
            self.assertIn("release_artifact_manifest", live_summary_capability["artifact_contracts"])
            self.assertIn("/release-artifact-manifest", live_summary_capability["entrypoints"])
            self.assertEqual(
                payload["summary"]["runtime_lanes"]["full_live_validation"][0]["flow_statuses"]["release_promotion_history_report_flow"],
                "passed",
            )
            self.assertEqual(payload["summary"]["event_stream"]["path"], "release_live_ci_events.json")
            self.assertEqual(payload["summary"]["event_stream"]["latest_event_type"], "run_finished")
            self.assertEqual(payload["summary"]["workflow_steps"][1]["status"], "blocked")
            self.assertEqual(payload["summary"]["dispatch_audit"]["path"], "logs/reports/release_live_ci/release_live_dispatch.json")
            self.assertEqual(payload["summary"]["artifact_manifest"]["release_build_id"], "web-release-001")
            self.assertIn("# Release Live CI Summary", payload["report_content"])
            self.assertIn("## Runtime Assembly", payload["report_content"])
            self.assertIn("## Event Stream", payload["report_content"])
            self.assertIn("## Workflow Dispatch Audit", payload["report_content"])
            self.assertIn("## Artifact Manifest", payload["report_content"])
            self.assertIn("Execution Delivery Readiness: status=warning", payload["report_content"])
            self.assertIn("Dispatch Summary: workflow_dispatch accepted for sossossal/cim-comm-soc@main", payload["report_content"])
            self.assertIn("Path: release_live_ci_events.json / source=live_ci_export", payload["report_content"])
            self.assertIn("route_id=github_workflow:release:production", payload["report_content"])
            self.assertIn("contracts=release_live_ci_summary, release_artifact_manifest", payload["report_content"])
            self.assertIn("entrypoints=/release-live-ci/summary, /release-live-ci/summary-report, /release-artifact-manifest", payload["report_content"])
            self.assertIn("release_promotion_history_report_flow=passed", payload["report_content"])
            self.assertIn("## Workflow Steps", payload["report_content"])
            self.assertIn("run_full_live_validation [blocked]", payload["report_content"])
        finally:
            shutil.rmtree(temp_project, ignore_errors=True)

    def test_release_live_ci_dispatch_preflight_endpoint_returns_readiness_snapshot(self):
        temp_project = project_root / "tests" / ".tmp_api_release_live_ci_dispatch_preflight"
        shutil.rmtree(temp_project, ignore_errors=True)
        try:
            workflow_path = temp_project / ".github" / "workflows" / "release-live-gates.yml"
            workflow_path.parent.mkdir(parents=True, exist_ok=True)
            workflow_path.write_text("on:\n  workflow_dispatch:\n", encoding="utf-8")

            client = TestClient(app)
            with patch.dict("os.environ", {"GH_TOKEN": "secret-token"}, clear=False):
                response = client.get(
                    "/release-live-ci/dispatch-preflight",
                    params={
                        "project_path": str(temp_project),
                        "repo": "sossossal/cim-comm-soc",
                        "ref": "main",
                        "workflow": "release-live-gates.yml",
                        "target_channel": "staging",
                        "target_environment": "staging",
                    },
                )

            self.assertEqual(response.status_code, 200)
            payload = response.json()
            self.assertEqual(payload["repo"], "sossossal/cim-comm-soc")
            self.assertEqual(payload["ref"], "main")
            self.assertTrue(payload["ready"])
            self.assertTrue(payload["workflow_exists"])
            self.assertTrue(payload["workflow_dispatch_enabled"])
            self.assertTrue(payload["token_present"])
            self.assertEqual(payload["dispatch_inputs"]["target_channel"], "staging")
        finally:
            shutil.rmtree(temp_project, ignore_errors=True)

    def test_release_live_ci_dispatch_endpoint_returns_dispatch_result(self):
        temp_project = project_root / "tests" / ".tmp_api_release_live_ci_dispatch"
        shutil.rmtree(temp_project, ignore_errors=True)
        try:
            workflow_path = temp_project / ".github" / "workflows" / "release-live-gates.yml"
            workflow_path.parent.mkdir(parents=True, exist_ok=True)
            workflow_path.write_text("on:\n  workflow_dispatch:\n", encoding="utf-8")

            client = TestClient(app)
            with patch("api_server.main._build_release_write_request_auth") as auth_mock, \
                 patch("api_server.main.dispatch_release_live_gates_request") as dispatch_mock:
                auth_mock.return_value = {
                    "status": "passed",
                    "actor_id": "release_manager",
                    "token_id": "token-001",
                    "reason": "accepted",
                }
                dispatch_mock.return_value = {
                    "schema_version": "1.0",
                    "ok": True,
                    "status": "passed",
                    "summary": "workflow_dispatch accepted for sossossal/cim-comm-soc@main",
                    "repo": "sossossal/cim-comm-soc",
                    "workflow": "release-live-gates.yml",
                    "ref": "main",
                    "wait": True,
                    "token_source": "GH_TOKEN",
                    "preflight": {
                        "status": "passed",
                        "ready": True,
                        "repo": "sossossal/cim-comm-soc",
                        "ref": "main",
                    },
                    "run": {
                        "id": 9001,
                        "number": 42,
                        "status": "completed",
                        "conclusion": "success",
                        "html_url": "https://github.com/sossossal/cim-comm-soc/actions/runs/9001",
                    },
                }

                response = client.post(
                    "/release-live-ci/dispatch",
                    json={
                        "project_path": str(temp_project),
                        "repo": "sossossal/cim-comm-soc",
                        "ref": "main",
                        "workflow": "release-live-gates.yml",
                        "target_channel": "staging",
                        "target_environment": "staging",
                        "triggered_by": "release_manager",
                        "wait": True,
                    },
                )

            self.assertEqual(response.status_code, 200)
            payload = response.json()
            self.assertTrue(payload["ok"])
            self.assertEqual(payload["run"]["id"], 9001)
            self.assertEqual(payload["run"]["number"], 42)
            self.assertEqual(payload["path"], "logs/reports/release_live_ci/release_live_dispatch.json")
            self.assertEqual(payload["request_auth"]["actor_id"], "release_manager")
            self.assertTrue((temp_project / "logs" / "reports" / "release_live_ci" / "release_live_dispatch.json").exists())
            dispatch_mock.assert_called_once()
        finally:
            shutil.rmtree(temp_project, ignore_errors=True)

    def test_release_live_ci_dispatch_audit_endpoint_returns_persisted_audit(self):
        temp_project = project_root / "tests" / ".tmp_api_release_live_ci_dispatch_audit"
        shutil.rmtree(temp_project, ignore_errors=True)
        try:
            artifact_dir = temp_project / "logs" / "reports" / "release_live_ci"
            artifact_dir.mkdir(parents=True, exist_ok=True)
            (artifact_dir / "release_live_dispatch.json").write_text(
                json.dumps(
                    {
                        "schema_version": "1.0",
                        "status": "warning",
                        "summary": "workflow_dispatch accepted for sossossal/cim-comm-soc@main",
                        "path": "logs/reports/release_live_ci/release_live_dispatch.json",
                        "artifact_dir": "logs/reports/release_live_ci",
                        "recorded_at": "2026-04-23T10:00:00Z",
                        "triggered_by": "release_manager",
                        "workflow": "release-live-gates.yml",
                        "repo": "sossossal/cim-comm-soc",
                        "ref": "main",
                        "ready": True,
                        "dispatch_attempted": True,
                        "dispatch_completed": False,
                        "wait": True,
                        "run": {
                            "id": 9001,
                            "number": 42,
                            "status": "in_progress",
                            "conclusion": "",
                            "html_url": "https://github.com/sossossal/cim-comm-soc/actions/runs/9001",
                        },
                        "request_auth": {
                            "status": "passed",
                            "actor_id": "release_manager",
                            "token_id": "token-001",
                        },
                        "preflight": {
                            "schema_version": "1.0",
                            "status": "passed",
                            "ready": True,
                            "workflow": "release-live-gates.yml",
                            "repo": "sossossal/cim-comm-soc",
                            "ref": "main",
                            "dispatch_inputs": {
                                "target_channel": "staging",
                                "target_environment": "staging",
                            },
                        },
                        "dispatch_result": {
                            "schema_version": "1.0",
                            "ok": True,
                            "status": "warning",
                            "summary": "workflow_dispatch accepted for sossossal/cim-comm-soc@main",
                            "repo": "sossossal/cim-comm-soc",
                            "workflow": "release-live-gates.yml",
                            "ref": "main",
                            "wait": True,
                            "run": {
                                "id": 9001,
                                "number": 42,
                                "status": "in_progress",
                                "conclusion": "",
                                "html_url": "https://github.com/sossossal/cim-comm-soc/actions/runs/9001",
                            },
                        },
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )

            client = TestClient(app)
            response = client.get(
                "/release-live-ci/dispatch-audit",
                params={
                    "project_path": str(temp_project),
                    "artifact_dir": "logs/reports/release_live_ci",
                },
            )

            self.assertEqual(response.status_code, 200)
            payload = response.json()
            self.assertEqual(payload["status"], "warning")
            self.assertTrue(payload["dispatch_attempted"])
            self.assertEqual(payload["run"]["id"], 9001)
            self.assertEqual(payload["path"], "logs/reports/release_live_ci/release_live_dispatch.json")
        finally:
            shutil.rmtree(temp_project, ignore_errors=True)

    def test_release_artifact_manifest_endpoint_returns_normalized_contract(self):
        temp_project = project_root / "tests" / ".tmp_api_release_artifact_manifest"
        shutil.rmtree(temp_project, ignore_errors=True)
        try:
            artifact_dir = temp_project / "logs" / "reports" / "release_live_ci"
            artifact_dir.mkdir(parents=True, exist_ok=True)
            (artifact_dir / "artifact_manifest.json").write_text(
                json.dumps(
                    {
                        "project_root": ".",
                        "runtime_root": ".",
                        "target_channel": "release",
                        "target_environment": "production",
                        "mode": "live_release_ci",
                        "release_build_id": "web-release-001",
                        "release_version": "0.1.0-release+1",
                        "release_channel": "release",
                        "release_summary": {
                            "build_id": "web-release-001",
                            "version": "0.1.0-release+1",
                            "channel": "release",
                        },
                        "runtime_assembly": {"route_kind": "github_workflow", "target_channel": "release"},
                        "event_stream": {"status": "passed", "path": "release_live_ci_events.json"},
                        "execution_delivery_readiness": {
                            "status": "warning",
                            "next_action_ids": ["external_distribution_delivery"],
                        },
                        "runtime_lanes": {
                            "full_live_validation": [
                                {"lane_id": "portal_click_smoke", "status": "passed"}
                            ]
                        },
                        "generated_files": ["release_live_ci_summary.json"],
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )

            client = TestClient(app)
            response = client.get(
                "/release-artifact-manifest",
                params={
                    "project_path": str(temp_project),
                    "artifact_dir": "logs/reports/release_live_ci",
                },
            )

            self.assertEqual(response.status_code, 200)
            payload = response.json()
            self.assertEqual(payload["schema_version"], "1.0")
            self.assertEqual(payload["contract_versions"]["release_artifact_manifest"], "1.0")
            self.assertEqual(payload["release_build_id"], "web-release-001")
            self.assertEqual(payload["release_summary"]["schema_version"], "1.0")
            self.assertEqual(payload["runtime_assembly"]["route_kind"], "github_workflow")
            self.assertEqual(payload["event_stream"]["path"], "release_live_ci_events.json")
            self.assertEqual(
                payload["execution_delivery_readiness"]["next_action_ids"],
                ["external_distribution_delivery"],
            )
            self.assertEqual(payload["runtime_lanes"]["full_live_validation"][0]["lane_id"], "portal_click_smoke")
            self.assertEqual(payload["manifest_path"], "logs/reports/release_live_ci/artifact_manifest.json")
            self.assertTrue(payload["manifest_exists"])
        finally:
            shutil.rmtree(temp_project, ignore_errors=True)

    def test_release_live_ci_events_endpoint_returns_filtered_timeline(self):
        temp_project = project_root / "tests" / ".tmp_api_release_live_ci_events"
        shutil.rmtree(temp_project, ignore_errors=True)
        try:
            artifact_dir = temp_project / "logs" / "reports" / "release_live_ci"
            artifact_dir.mkdir(parents=True, exist_ok=True)
            (artifact_dir / "release_live_ci_summary.json").write_text(
                json.dumps(
                    {
                        "schema_version": "1.0",
                        "event_stream": {
                            "status": "warning",
                            "path": "release_live_ci_events.json",
                            "summary": "events=4 / blocked=1 / warning=1 / latest=run_finished",
                            "source": "live_ci_export",
                            "generated_at": "2026-04-18T10:00:00Z",
                            "route_kind": "github_workflow",
                            "route_id": "github_workflow:release:production",
                            "invocation_source": "github_workflow",
                            "event_count": 4,
                            "blocked_event_count": 1,
                            "warning_event_count": 1,
                            "latest_event_type": "run_finished",
                            "latest_event_status": "warning",
                            "events": [
                                {
                                    "event_id": "run_started_1",
                                    "event_type": "run_started",
                                    "scope": "run",
                                    "order": 1,
                                    "status": "passed",
                                    "occurred_at": "2026-04-18T10:00:00Z",
                                    "summary": "route=github_workflow",
                                },
                                {
                                    "event_id": "step_finished_2",
                                    "event_type": "step_finished",
                                    "scope": "workflow_step",
                                    "order": 2,
                                    "status": "blocked",
                                    "occurred_at": "2026-04-18T10:01:00Z",
                                    "step_id": "run_full_live_validation",
                                    "summary": "run_full_live_validation [blocked]",
                                },
                                {
                                    "event_id": "lane_reported_3",
                                    "event_type": "lane_reported",
                                    "scope": "runtime_lane",
                                    "order": 3,
                                    "status": "passed",
                                    "occurred_at": "2026-04-18T10:02:00Z",
                                    "lane_id": "portal_click_smoke",
                                    "summary": "portal_click_smoke [passed]",
                                },
                                {
                                    "event_id": "run_finished_4",
                                    "event_type": "run_finished",
                                    "scope": "run",
                                    "order": 4,
                                    "status": "warning",
                                    "occurred_at": "2026-04-18T10:03:00Z",
                                    "summary": "automation=passed / signoffs=warning",
                                },
                            ],
                        },
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )

            client = TestClient(app)
            response = client.get(
                "/release-live-ci/events",
                params={
                    "project_path": str(temp_project),
                    "artifact_dir": "logs/reports/release_live_ci",
                    "status": "blocked",
                    "step_id": "run_full_live_validation",
                    "limit": 5,
                },
            )

            self.assertEqual(response.status_code, 200)
            payload = response.json()
            self.assertEqual(payload["matched_count"], 1)
            self.assertEqual(payload["visible_count"], 1)
            self.assertEqual(payload["event_stream"]["path"], "release_live_ci_events.json")
            self.assertEqual(payload["event_stream"]["events"][0]["event_type"], "step_finished")
            self.assertEqual(payload["event_stream"]["events"][0]["step_id"], "run_full_live_validation")
        finally:
            shutil.rmtree(temp_project, ignore_errors=True)

    @patch("agent_system.router.GodotCLI", ApiDataTableGodotCLI)
    def test_manage_art_asset_pipeline_endpoint_can_preview_and_apply(self):
        from agent_system.router import GodotAgentRouter

        temp_project = project_root / "tests" / ".tmp_api_art_asset_manage"
        shutil.rmtree(temp_project, ignore_errors=True)
        try:
            raw_model_dir = temp_project / "raw_assets" / "models"
            raw_model_dir.mkdir(parents=True, exist_ok=True)
            (raw_model_dir / "hero_knight.blend").write_bytes(b"fake-blend")
            (raw_model_dir / "hero_knight_albedo.png").write_bytes(b"fake-albedo")
            (raw_model_dir / "hero_knight_normal.png").write_bytes(b"fake-normal")

            router = GodotAgentRouter(godot_project_path=str(temp_project))
            with patch("api_server.main.manager.get_router", return_value=router):
                client = TestClient(app)
                preview_response = client.post(
                    "/art-assets/manage",
                    json={
                        "project_path": str(temp_project),
                        "action": "preview",
                        "asset_type": "model",
                        "asset_id": "hero_knight_model",
                        "source_path": "res://raw_assets/models/hero_knight.blend",
                        "target_path": "res://assets/models/hero_knight.glb",
                        "source_tool": "blender",
                        "lod_count": 3,
                    },
                )
                apply_response = client.post(
                    "/art-assets/manage",
                    json={
                        "project_path": str(temp_project),
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
                    },
                )
        finally:
            manifest_path = temp_project / "assets" / "manifests" / "model_assets.json"
            target_model = temp_project / "assets" / "models" / "hero_knight.glb"
            target_albedo = temp_project / "assets" / "models" / "hero_knight_albedo.png"
            manifest_exists = manifest_path.exists()
            model_exists = target_model.exists()
            albedo_exists = target_albedo.exists()
            manifest_content = manifest_path.read_text(encoding="utf-8") if manifest_exists else ""
            shutil.rmtree(temp_project, ignore_errors=True)

        self.assertEqual(preview_response.status_code, 200)
        preview_payload = preview_response.json()
        self.assertEqual(preview_payload["status"], "success")
        self.assertEqual(preview_payload["context"]["last_skill_result"]["skill_name"], "manage_art_asset_pipeline")
        self.assertEqual(preview_payload["art_asset_profile"]["asset_type"], "model")
        self.assertEqual(preview_payload["art_asset_profile"]["entry_count"], 1)
        self.assertEqual(preview_payload["art_asset_profile"]["copied_target_count"], 1)

        self.assertEqual(apply_response.status_code, 200)
        apply_payload = apply_response.json()
        self.assertEqual(apply_payload["status"], "success")
        self.assertEqual(apply_payload["context"]["art_asset_type"], "model")
        self.assertEqual(apply_payload["context"]["art_asset_source_tool"], "blender")
        self.assertTrue(manifest_exists)
        self.assertTrue(model_exists)
        self.assertTrue(albedo_exists)
        self.assertIn('"dependency_targets"', manifest_content)

    @patch("agent_system.router.GodotCLI", ApiDataTableGodotCLI)
    def test_manage_art_asset_pipeline_endpoint_reports_validation_failures(self):
        from agent_system.router import GodotAgentRouter

        temp_project = project_root / "tests" / ".tmp_api_art_asset_invalid"
        shutil.rmtree(temp_project, ignore_errors=True)
        try:
            raw_outsource_dir = temp_project / "raw_assets" / "outsource"
            raw_outsource_dir.mkdir(parents=True, exist_ok=True)
            (raw_outsource_dir / "npc_vendor_delivery.zip").write_bytes(b"fake-zip")

            router = GodotAgentRouter(godot_project_path=str(temp_project))
            with patch("api_server.main.manager.get_router", return_value=router):
                client = TestClient(app)
                response = client.post(
                    "/art-assets/manage",
                    json={
                        "project_path": str(temp_project),
                        "action": "preview",
                        "asset_type": "outsource",
                        "asset_id": "npc_vendor_delivery",
                        "source_path": "res://raw_assets/outsource/npc_vendor_delivery.zip",
                        "source_tool": "outsource_delivery",
                    },
                )
        finally:
            shutil.rmtree(temp_project, ignore_errors=True)

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["status"], "failed")
        self.assertEqual(payload["context"]["last_skill_result"]["skill_name"], "manage_art_asset_pipeline")
        self.assertFalse(payload["context"]["last_skill_result"]["validation"]["passed"])
        self.assertEqual(payload["art_asset_profile"]["asset_type"], "outsource")
        self.assertTrue(any("package_version" in issue for issue in payload["context"]["last_skill_result"]["validation"]["issues"]))
        self.assertTrue(any("license_name" in issue for issue in payload["context"]["last_skill_result"]["validation"]["issues"]))

    def test_gameplay_templates_endpoint_returns_snapshots(self):
        client = TestClient(app)
        list_response = client.get("/gameplay/templates", params={"project_path": "default"})
        detail_response = client.get(
            "/gameplay/templates",
            params={"project_path": "default", "template_id": "platformer"},
        )

        self.assertEqual(list_response.status_code, 200)
        list_payload = list_response.json()
        self.assertGreaterEqual(list_payload["count"], 7)
        self.assertTrue(any(item["template_id"] == "platformer" for item in list_payload["items"]))
        self.assertTrue(any(item["template_id"] == "platformer_production" for item in list_payload["items"]))

        self.assertEqual(detail_response.status_code, 200)
        detail_payload = detail_response.json()
        self.assertEqual(detail_payload["template_id"], "platformer")
        self.assertEqual(detail_payload["schema_version"], "1.0")
        self.assertGreaterEqual(detail_payload["system_count"], 6)

    @patch("agent_system.router.GodotCLI", ApiDataTableGodotCLI)
    def test_manage_gameplay_template_endpoint_can_preview_and_apply(self):
        from agent_system.router import GodotAgentRouter

        temp_project = project_root / "tests" / ".tmp_api_gameplay_template_manage"
        shutil.rmtree(temp_project, ignore_errors=True)
        try:
            router = GodotAgentRouter(godot_project_path=str(temp_project))
            with patch("api_server.main.manager.get_router", return_value=router):
                client = TestClient(app)
                preview_response = client.post(
                    "/gameplay/manage",
                    json={
                        "project_path": str(temp_project),
                        "action": "preview",
                        "template_id": "tower_defense",
                        "include_system_ids": ["wave_spawner", "tower_build_system"],
                    },
                )
                apply_response = client.post(
                    "/gameplay/manage",
                    json={
                        "project_path": str(temp_project),
                        "action": "apply",
                        "template_id": "tower_defense",
                    },
                )
        finally:
            shutil.rmtree(temp_project, ignore_errors=True)

        self.assertEqual(preview_response.status_code, 200)
        preview_payload = preview_response.json()
        self.assertEqual(preview_payload["status"], "success")
        self.assertEqual(preview_payload["context"]["last_skill_result"]["skill_name"], "manage_gameplay_template")
        self.assertEqual(preview_payload["gameplay_template"]["template_id"], "tower_defense")
        self.assertEqual(preview_payload["gameplay_template"]["system_count"], 2)

        self.assertEqual(apply_response.status_code, 200)
        apply_payload = apply_response.json()
        self.assertEqual(apply_payload["status"], "success")
        self.assertTrue(apply_payload["context"]["gameplay_template_applied"])
        self.assertEqual(apply_payload["context"]["gameplay_template_id"], "tower_defense")
        self.assertGreaterEqual(len(apply_payload["context"]["gameplay_seeded_features"]), 1)
        self.assertEqual(router.blueprint_manager.blueprint.project_template["template_id"], "tower_defense")
        self.assertEqual(router.blueprint_manager.blueprint.gameplay_template_id, "tower_defense")

    @patch("agent_system.router.GodotCLI", ApiDataTableGodotCLI)
    def test_manage_gameplay_template_endpoint_reports_missing_template(self):
        from agent_system.router import GodotAgentRouter

        temp_project = project_root / "tests" / ".tmp_api_gameplay_template_missing"
        shutil.rmtree(temp_project, ignore_errors=True)
        try:
            router = GodotAgentRouter(godot_project_path=str(temp_project))
            with patch("api_server.main.manager.get_router", return_value=router):
                client = TestClient(app)
                response = client.post(
                    "/gameplay/manage",
                    json={
                        "project_path": str(temp_project),
                        "action": "apply",
                        "template_id": "missing_template",
                    },
                )
        finally:
            shutil.rmtree(temp_project, ignore_errors=True)

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["status"], "failed")
        self.assertEqual(payload["context"]["last_skill_result"]["skill_name"], "manage_gameplay_template")
        self.assertFalse(payload["context"]["last_skill_result"]["validation"]["passed"])
        self.assertEqual(payload["gameplay_template"]["template_id"], "missing_template")
        self.assertEqual(payload["gameplay_template"]["system_count"], 0)

    def test_presentation_profiles_endpoint_returns_snapshots(self):
        client = TestClient(app)
        list_response = client.get("/presentation/profiles", params={"project_path": "default"})
        detail_response = client.get(
            "/presentation/profiles",
            params={"project_path": "default", "presentation_type": "shader"},
        )

        self.assertEqual(list_response.status_code, 200)
        list_payload = list_response.json()
        self.assertGreaterEqual(list_payload["count"], 4)
        self.assertTrue(any(item["presentation_type"] == "shader" for item in list_payload["items"]))
        self.assertTrue(any(item["presentation_type"] == "audio" for item in list_payload["items"]))

        self.assertEqual(detail_response.status_code, 200)
        detail_payload = detail_response.json()
        self.assertEqual(detail_payload["presentation_type"], "shader")
        self.assertEqual(detail_payload["schema_version"], "1.0")
        self.assertEqual(detail_payload["display_path"], "assets/manifests/shader_profiles.json")
        self.assertEqual(detail_payload["entry_count"], 0)

    @patch("agent_system.router.GodotCLI", ApiDataTableGodotCLI)
    def test_manage_presentation_pipeline_endpoint_can_preview_and_apply(self):
        from agent_system.router import GodotAgentRouter

        temp_project = project_root / "tests" / ".tmp_api_presentation_manage"
        shutil.rmtree(temp_project, ignore_errors=True)
        try:
            router = GodotAgentRouter(godot_project_path=str(temp_project))
            with patch("api_server.main.manager.get_router", return_value=router):
                client = TestClient(app)
                preview_response = client.post(
                    "/presentation/manage",
                    json={
                        "project_path": str(temp_project),
                        "action": "preview",
                        "presentation_type": "shader",
                        "profile_id": "heat_wave",
                        "shader_mode": "canvas_item",
                        "shader_params": {
                            "wave_strength": 0.2,
                            "scroll_speed": 0.35,
                            "tint_color": "#44aaff",
                        },
                    },
                )
                apply_response = client.post(
                    "/presentation/manage",
                    json={
                        "project_path": str(temp_project),
                        "action": "apply",
                        "presentation_type": "audio",
                        "profile_id": "boss_warning",
                        "audio_role": "sfx",
                        "event_name": "boss_warning",
                        "bus_name": "SFX",
                        "audio_stream_path": "res://assets/audio/boss_warning.ogg",
                    },
                )
        finally:
            shader_manifest = temp_project / "assets" / "manifests" / "shader_profiles.json"
            audio_manifest = temp_project / "assets" / "manifests" / "audio_profiles.json"
            audio_script = temp_project / "scripts" / "audio" / "boss_warning_audio_router.gd"
            shader_exists = shader_manifest.exists()
            audio_exists = audio_manifest.exists()
            script_exists = audio_script.exists()
            script_content = audio_script.read_text(encoding="utf-8") if script_exists else ""
            shutil.rmtree(temp_project, ignore_errors=True)

        self.assertEqual(preview_response.status_code, 200)
        preview_payload = preview_response.json()
        self.assertEqual(preview_payload["status"], "success")
        self.assertEqual(preview_payload["context"]["last_skill_result"]["skill_name"], "manage_presentation_pipeline")
        self.assertEqual(preview_payload["presentation_profile"]["presentation_type"], "shader")
        self.assertEqual(preview_payload["presentation_profile"]["entry_count"], 1)
        self.assertEqual(preview_payload["presentation_profile"]["generated_path_count"], 2)
        self.assertFalse(shader_exists)

        self.assertEqual(apply_response.status_code, 200)
        apply_payload = apply_response.json()
        self.assertEqual(apply_payload["status"], "success")
        self.assertTrue(apply_payload["context"]["presentation_written"])
        self.assertEqual(apply_payload["context"]["presentation_type"], "audio")
        self.assertTrue(audio_exists)
        self.assertTrue(script_exists)
        self.assertIn('"boss_warning": "SFX"', script_content)
        self.assertIn("presentation_boss_warning", router.blueprint_manager.blueprint.features)

    @patch("agent_system.router.GodotCLI", ApiDataTableGodotCLI)
    def test_manage_presentation_pipeline_endpoint_reports_validation_failures(self):
        from agent_system.router import GodotAgentRouter

        temp_project = project_root / "tests" / ".tmp_api_presentation_invalid"
        shutil.rmtree(temp_project, ignore_errors=True)
        try:
            router = GodotAgentRouter(godot_project_path=str(temp_project))
            with patch("api_server.main.manager.get_router", return_value=router):
                client = TestClient(app)
                response = client.post(
                    "/presentation/manage",
                    json={
                        "project_path": str(temp_project),
                        "action": "preview",
                        "presentation_type": "vfx",
                        "profile_id": "broken_fx",
                        "amount": 0,
                        "lifetime_seconds": 0,
                        "color_hex": "#123",
                    },
                )
        finally:
            shutil.rmtree(temp_project, ignore_errors=True)

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["status"], "failed")
        self.assertEqual(payload["context"]["last_skill_result"]["skill_name"], "manage_presentation_pipeline")
        self.assertFalse(payload["context"]["last_skill_result"]["validation"]["passed"])
        self.assertEqual(payload["presentation_profile"]["presentation_type"], "vfx")
        self.assertGreaterEqual(len(payload["context"]["last_skill_result"]["validation"]["issues"]), 2)

    def test_liveops_profiles_endpoint_returns_snapshots(self):
        client = TestClient(app)
        list_response = client.get("/liveops/profiles", params={"project_path": "default"})
        detail_response = client.get(
            "/liveops/profiles",
            params={"project_path": "default", "liveops_type": "remote_config"},
        )

        self.assertEqual(list_response.status_code, 200)
        list_payload = list_response.json()
        self.assertEqual(list_payload["count"], 2)
        self.assertTrue(any(item["liveops_type"] == "remote_config" for item in list_payload["items"]))
        self.assertTrue(any(item["liveops_type"] == "experiment_catalog" for item in list_payload["items"]))

        self.assertEqual(detail_response.status_code, 200)
        detail_payload = detail_response.json()
        self.assertEqual(detail_payload["liveops_type"], "remote_config")
        self.assertEqual(detail_payload["schema_version"], "1.0")
        self.assertEqual(detail_payload["display_path"], "liveops/remote_config.json")
        self.assertEqual(detail_payload["entry_count"], 1)

    @patch("agent_system.router.GodotCLI", ApiDataTableGodotCLI)
    def test_manage_liveops_pipeline_endpoint_can_template_preview_and_apply(self):
        from agent_system.router import GodotAgentRouter

        temp_project = project_root / "tests" / ".tmp_api_liveops_manage"
        shutil.rmtree(temp_project, ignore_errors=True)
        try:
            router = GodotAgentRouter(godot_project_path=str(temp_project))
            with patch("api_server.main.manager.get_router", return_value=router):
                client = TestClient(app)
                template_response = client.post(
                    "/liveops/manage",
                    json={
                        "project_path": str(temp_project),
                        "action": "template",
                        "liveops_type": "remote_config",
                        "entry_id": "combat_spawn_multiplier",
                    },
                )
                preview_response = client.post(
                    "/liveops/manage",
                    json={
                        "project_path": str(temp_project),
                        "action": "preview",
                        "liveops_type": "experiment_catalog",
                        "entries": [{
                            "experiment_id": "tutorial_short_path",
                            "status": "running",
                            "hypothesis": "更短教程提升完成率",
                            "owner": "product_ops",
                            "target_metrics": ["tutorial_completion_rate", "d1_retention"],
                            "rollout_percentage": 30,
                            "rollback_rule": "tutorial_completion_rate 下降 3% 回滚",
                            "variants": [
                                {"variant_id": "control", "weight": 50},
                                {"variant_id": "short_path", "weight": 50},
                            ],
                        }],
                    },
                )
                apply_response = client.post(
                    "/liveops/manage",
                    json={
                        "project_path": str(temp_project),
                        "action": "apply",
                        "liveops_type": "experiment_catalog",
                        "entries": [{
                            "experiment_id": "tutorial_short_path",
                            "status": "running",
                            "hypothesis": "更短教程提升完成率",
                            "owner": "product_ops",
                            "target_metrics": ["tutorial_completion_rate", "d1_retention"],
                            "rollout_percentage": 30,
                            "rollback_rule": "tutorial_completion_rate 下降 3% 回滚",
                            "variants": [
                                {"variant_id": "control", "weight": 50},
                                {"variant_id": "short_path", "weight": 50},
                            ],
                        }],
                    },
                )
        finally:
            remote_config_manifest = temp_project / "liveops" / "remote_config.json"
            experiments_manifest = temp_project / "liveops" / "experiments.json"
            remote_exists = remote_config_manifest.exists()
            experiments_exists = experiments_manifest.exists()
            experiments_content = experiments_manifest.read_text(encoding="utf-8") if experiments_exists else ""
            shutil.rmtree(temp_project, ignore_errors=True)

        self.assertEqual(template_response.status_code, 200)
        template_payload = template_response.json()
        self.assertEqual(template_payload["status"], "success")
        self.assertEqual(template_payload["context"]["last_skill_result"]["skill_name"], "manage_liveops_pipeline")
        self.assertEqual(template_payload["liveops_profile"]["liveops_type"], "remote_config")
        self.assertTrue(remote_exists)

        self.assertEqual(preview_response.status_code, 200)
        preview_payload = preview_response.json()
        self.assertEqual(preview_payload["status"], "success")
        self.assertEqual(preview_payload["liveops_profile"]["liveops_type"], "experiment_catalog")
        self.assertEqual(preview_payload["liveops_profile"]["variant_count"], 2)

        self.assertEqual(apply_response.status_code, 200)
        apply_payload = apply_response.json()
        self.assertEqual(apply_payload["status"], "success")
        self.assertTrue(apply_payload["context"]["liveops_written"])
        self.assertEqual(apply_payload["context"]["liveops_type"], "experiment_catalog")
        self.assertTrue(experiments_exists)
        self.assertIn('"experiment_id": "tutorial_short_path"', experiments_content)

    @patch("agent_system.router.GodotCLI", ApiDataTableGodotCLI)
    def test_manage_liveops_pipeline_endpoint_reports_validation_failures(self):
        from agent_system.router import GodotAgentRouter

        temp_project = project_root / "tests" / ".tmp_api_liveops_invalid"
        shutil.rmtree(temp_project, ignore_errors=True)
        try:
            router = GodotAgentRouter(godot_project_path=str(temp_project))
            with patch("api_server.main.manager.get_router", return_value=router):
                client = TestClient(app)
                response = client.post(
                    "/liveops/manage",
                    json={
                        "project_path": str(temp_project),
                        "action": "preview",
                        "liveops_type": "experiment_catalog",
                        "entries": [{
                            "experiment_id": "bad_experiment",
                            "status": "running",
                            "hypothesis": "坏实验",
                            "target_metrics": ["tutorial_completion_rate"],
                            "rollout_percentage": 20,
                            "variants": [
                                {"variant_id": "control", "weight": 80},
                                {"variant_id": "variant_a", "weight": 10},
                            ],
                        }],
                    },
                )
        finally:
            shutil.rmtree(temp_project, ignore_errors=True)

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["status"], "failed")
        self.assertEqual(payload["context"]["last_skill_result"]["skill_name"], "manage_liveops_pipeline")
        self.assertFalse(payload["context"]["last_skill_result"]["validation"]["passed"])
        self.assertEqual(payload["liveops_profile"]["liveops_type"], "experiment_catalog")
        self.assertTrue(any("weight 总和必须为 100" in issue for issue in payload["liveops_profile"]["issues"]))

    @patch("agent_system.router.GodotCLI", ApiDataTableGodotCLI)
    def test_telemetry_endpoint_returns_snapshot(self):
        from agent_system.router import GodotAgentRouter

        temp_project = project_root / "tests" / ".tmp_api_telemetry_snapshot"
        shutil.rmtree(temp_project, ignore_errors=True)
        try:
            telemetry_dir = temp_project / "telemetry"
            telemetry_dir.mkdir(parents=True, exist_ok=True)
            (telemetry_dir / "event_catalog.json").write_text(
                json.dumps({
                    "events": [
                        {
                            "event_name": "session_start",
                            "category": "session",
                            "description": "开始会话",
                            "privacy_level": "anonymous",
                            "fields": [{"name": "build_id", "type": "string", "required": True, "pii": False}],
                        }
                    ]
                }, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            sessions_dir = telemetry_dir / "sessions"
            sessions_dir.mkdir(parents=True, exist_ok=True)
            (sessions_dir / "session_001.jsonl").write_text(
                json.dumps({
                    "event_name": "session_start",
                    "session_id": "s1",
                    "timestamp": "2026-04-10T10:00:00Z",
                    "payload": {"build_id": "web-preview-1"},
                }, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )

            router = GodotAgentRouter(godot_project_path=str(temp_project))
            with patch("api_server.main.manager.get_router", return_value=router):
                client = TestClient(app)
                response = client.get("/telemetry", params={"project_path": str(temp_project)})
        finally:
            shutil.rmtree(temp_project, ignore_errors=True)

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["default_catalog_path"], "telemetry/event_catalog.json")
        self.assertEqual(payload["telemetry"]["catalog_entry_count"], 1)
        self.assertEqual(payload["telemetry"]["summary"]["session_count"], 1)
        self.assertEqual(payload["telemetry"]["summary"]["event_count"], 1)
        self.assertEqual(payload["telemetry"]["summary"]["pii_violation_count"], 0)
        self.assertTrue(payload["telemetry"]["summary"]["privacy_gate_passed"])

    @patch("agent_system.router.GodotCLI", ApiDataTableGodotCLI)
    def test_manage_telemetry_endpoint_can_template_and_analyze(self):
        from agent_system.router import GodotAgentRouter

        temp_project = project_root / "tests" / ".tmp_api_telemetry_manage"
        shutil.rmtree(temp_project, ignore_errors=True)
        try:
            router = GodotAgentRouter(godot_project_path=str(temp_project))
            with patch("api_server.main.manager.get_router", return_value=router):
                client = TestClient(app)
                template_response = client.post(
                    "/telemetry/manage",
                    json={
                        "project_path": str(temp_project),
                        "action": "template",
                    },
                )
                analyze_response = client.post(
                    "/telemetry/manage",
                    json={
                        "project_path": str(temp_project),
                        "action": "analyze",
                        "catalog_entries": [
                            {
                                "event_name": "session_start",
                                "category": "session",
                                "description": "开始会话",
                                "privacy_level": "anonymous",
                                "fields": [{"name": "build_id", "type": "string", "required": True, "pii": False}],
                            },
                            {
                                "event_name": "level_start",
                                "category": "gameplay",
                                "description": "开始关卡",
                                "privacy_level": "anonymous",
                                "fields": [],
                            },
                            {
                                "event_name": "level_complete",
                                "category": "gameplay",
                                "description": "完成关卡",
                                "privacy_level": "anonymous",
                                "fields": [],
                            },
                            {
                                "event_name": "session_end",
                                "category": "session",
                                "description": "结束会话",
                                "privacy_level": "anonymous",
                                "fields": [],
                            },
                        ],
                        "events": [
                            {
                                "event_name": "session_start",
                                "session_id": "s1",
                                "timestamp": "2026-04-10T10:00:00Z",
                                "payload": {"build_id": "web-preview-1", "player_id": "p1"},
                            },
                            {
                                "event_name": "level_start",
                                "session_id": "s1",
                                "timestamp": "2026-04-10T10:01:00Z",
                                "payload": {},
                            },
                            {
                                "event_name": "level_complete",
                                "session_id": "s1",
                                "timestamp": "2026-04-10T10:02:00Z",
                                "payload": {},
                            },
                            {
                                "event_name": "session_end",
                                "session_id": "s1",
                                "timestamp": "2026-04-10T10:05:00Z",
                                "payload": {"player_id": "p1"},
                            },
                            {
                                "event_name": "session_start",
                                "session_id": "s2",
                                "timestamp": "2026-04-11T10:00:00Z",
                                "payload": {"build_id": "web-preview-1", "player_id": "p1"},
                            },
                            {
                                "event_name": "session_end",
                                "session_id": "s2",
                                "timestamp": "2026-04-11T10:05:00Z",
                                "payload": {"player_id": "p1"},
                            },
                        ],
                    },
                )
        finally:
            catalog_path = temp_project / "telemetry" / "event_catalog.json"
            catalog_exists = catalog_path.exists()
            catalog_content = catalog_path.read_text(encoding="utf-8") if catalog_exists else ""
            shutil.rmtree(temp_project, ignore_errors=True)

        self.assertEqual(template_response.status_code, 200)
        template_payload = template_response.json()
        self.assertEqual(template_payload["status"], "success")
        self.assertEqual(template_payload["telemetry"]["summary"]["catalog_entry_count"], 6)
        self.assertTrue(catalog_exists)
        self.assertIn("session_start", catalog_content)

        self.assertEqual(analyze_response.status_code, 200)
        analyze_payload = analyze_response.json()
        self.assertEqual(analyze_payload["status"], "success")
        self.assertTrue(analyze_payload["context"]["telemetry_passed"])
        self.assertEqual(analyze_payload["telemetry"]["summary"]["session_count"], 2)
        self.assertEqual(analyze_payload["telemetry"]["summary"]["retention_user_count"], 1)
        self.assertTrue(analyze_payload["telemetry"]["summary"]["privacy_gate_passed"])
        self.assertEqual(analyze_payload["telemetry"]["summary"]["retention_cohorts"][0]["window"], "d1")

    @patch("agent_system.router.GodotCLI", ApiDataTableGodotCLI)
    def test_manage_telemetry_endpoint_reports_privacy_gate_failures(self):
        from agent_system.router import GodotAgentRouter

        temp_project = project_root / "tests" / ".tmp_api_telemetry_privacy_gate"
        shutil.rmtree(temp_project, ignore_errors=True)
        try:
            router = GodotAgentRouter(godot_project_path=str(temp_project))
            with patch("api_server.main.manager.get_router", return_value=router):
                client = TestClient(app)
                response = client.post(
                    "/telemetry/manage",
                    json={
                        "project_path": str(temp_project),
                        "action": "analyze",
                        "catalog_entries": [
                            {
                                "event_name": "session_start",
                                "category": "session",
                                "description": "开始会话",
                                "privacy_level": "anonymous",
                                "fields": [{"name": "build_id", "type": "string", "required": True, "pii": False}],
                            },
                        ],
                        "events": [
                            {
                                "event_name": "session_start",
                                "session_id": "s1",
                                "timestamp": "2026-04-10T10:00:00Z",
                                "payload": {"build_id": "web-preview-1", "email": "qa@example.com"},
                            },
                        ],
                    },
                )
        finally:
            shutil.rmtree(temp_project, ignore_errors=True)

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["status"], "failed")
        self.assertEqual(payload["telemetry"]["summary"]["pii_violation_count"], 1)
        self.assertFalse(payload["telemetry"]["summary"]["privacy_gate_passed"])

    @patch("agent_system.router.GodotCLI", ApiDataTableGodotCLI)
    def test_telemetry_crash_clusters_endpoint_returns_report(self):
        from agent_system.router import GodotAgentRouter

        temp_project = project_root / "tests" / ".tmp_api_telemetry_crash_clusters"
        shutil.rmtree(temp_project, ignore_errors=True)
        try:
            telemetry_dir = temp_project / "telemetry"
            sessions_dir = telemetry_dir / "sessions"
            sessions_dir.mkdir(parents=True, exist_ok=True)
            (telemetry_dir / "event_catalog.json").write_text(
                json.dumps({
                    "schema_version": "1.3",
                    "events": [
                        {
                            "event_name": "crash",
                            "category": "error",
                            "description": "崩溃",
                            "privacy_level": "restricted",
                            "fields": [{"name": "error_code", "type": "string", "required": True, "pii": False}],
                        }
                    ],
                }, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            (sessions_dir / "session_001.jsonl").write_text(
                json.dumps({
                    "event_name": "crash",
                    "session_id": "s1",
                    "timestamp": "2026-04-10T10:00:00Z",
                    "payload": {
                        "error_code": "native_sigsegv",
                        "crash_type": "native",
                        "stack_hash": "stack_native_sigsegv_player_controller",
                        "crash_signature": "player_controller_native_sigsegv",
                    },
                }, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )

            router = GodotAgentRouter(godot_project_path=str(temp_project))
            with patch("api_server.main.manager.get_router", return_value=router):
                client = TestClient(app)
                response = client.get("/telemetry/crash-clusters", params={"project_path": str(temp_project)})
        finally:
            shutil.rmtree(temp_project, ignore_errors=True)

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["crash_cluster_count"], 1)
        self.assertEqual(payload["crash_clusters"][0]["cluster_id"], "stack_native_sigsegv_player_controller")
        self.assertIn("# Crash Cluster Report", payload["report_content"])

    @patch("agent_system.router.GodotCLI", ApiDataTableGodotCLI)
    def test_telemetry_crash_dashboard_endpoint_returns_build_and_scene_regressions(self):
        from agent_system.router import GodotAgentRouter

        temp_project = project_root / "tests" / ".tmp_api_telemetry_crash_dashboard"
        shutil.rmtree(temp_project, ignore_errors=True)
        try:
            telemetry_dir = temp_project / "telemetry"
            sessions_dir = telemetry_dir / "sessions"
            sessions_dir.mkdir(parents=True, exist_ok=True)
            (telemetry_dir / "event_catalog.json").write_text(
                json.dumps({
                    "schema_version": "1.3",
                    "events": [
                        {
                            "event_name": "crash",
                            "category": "error",
                            "description": "崩溃",
                            "privacy_level": "restricted",
                            "fields": [{"name": "error_code", "type": "string", "required": True, "pii": False}],
                        }
                    ],
                }, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            (sessions_dir / "session_001.jsonl").write_text(
                json.dumps({
                    "event_name": "crash",
                    "session_id": "s1",
                    "timestamp": "2026-04-10T10:00:00Z",
                    "build_id": "web-preview-9",
                    "payload": {
                        "error_code": "native_sigsegv",
                        "crash_type": "native",
                        "stack_hash": "stack_native_sigsegv_player_controller",
                        "scene_path": "res://scenes/levels/level_09.tscn",
                    },
                }, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )

            router = GodotAgentRouter(godot_project_path=str(temp_project))
            with patch("api_server.main.manager.get_router", return_value=router):
                client = TestClient(app)
                response = client.get("/telemetry/crash-dashboard", params={"project_path": str(temp_project)})
        finally:
            shutil.rmtree(temp_project, ignore_errors=True)

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["dashboard"]["affected_build_count"], 1)
        self.assertEqual(payload["dashboard"]["affected_scene_count"], 1)
        self.assertEqual(payload["dashboard"]["build_regressions"][0]["build_id"], "web-preview-9")
        self.assertEqual(payload["dashboard"]["scene_regressions"][0]["scene_path"], "res://scenes/levels/level_09.tscn")
        self.assertIn("# Crash Regression Dashboard", payload["report_content"])

    @patch("agent_system.router.GodotCLI", ApiDataTableGodotCLI)
    def test_telemetry_retention_dashboard_endpoint_returns_dropoff_summary(self):
        from agent_system.router import GodotAgentRouter

        temp_project = project_root / "tests" / ".tmp_api_telemetry_retention_dashboard"
        shutil.rmtree(temp_project, ignore_errors=True)
        try:
            telemetry_dir = temp_project / "telemetry"
            sessions_dir = telemetry_dir / "sessions"
            sessions_dir.mkdir(parents=True, exist_ok=True)
            (telemetry_dir / "event_catalog.json").write_text(
                json.dumps({
                    "schema_version": "1.1",
                    "events": [
                        {
                            "event_name": "session_start",
                            "category": "session",
                            "description": "开始会话",
                            "privacy_level": "anonymous",
                            "fields": [{"name": "player_id", "type": "string", "required": True, "pii": False}],
                        },
                        {
                            "event_name": "level_start",
                            "category": "gameplay",
                            "description": "开始关卡",
                            "privacy_level": "anonymous",
                            "fields": [],
                        },
                        {
                            "event_name": "level_complete",
                            "category": "gameplay",
                            "description": "完成关卡",
                            "privacy_level": "anonymous",
                            "fields": [],
                        },
                        {
                            "event_name": "session_end",
                            "category": "session",
                            "description": "结束会话",
                            "privacy_level": "anonymous",
                            "fields": [{"name": "player_id", "type": "string", "required": True, "pii": False}],
                        },
                    ],
                }, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            (sessions_dir / "session_001.jsonl").write_text(
                (
                    json.dumps({
                        "event_name": "session_start",
                        "session_id": "s1",
                        "timestamp": "2026-04-10T10:00:00Z",
                        "payload": {"player_id": "p1"},
                    }, ensure_ascii=False) + "\n" +
                    json.dumps({
                        "event_name": "level_start",
                        "session_id": "s1",
                        "timestamp": "2026-04-10T10:01:00Z",
                        "payload": {},
                    }, ensure_ascii=False) + "\n" +
                    json.dumps({
                        "event_name": "level_complete",
                        "session_id": "s1",
                        "timestamp": "2026-04-10T10:02:00Z",
                        "payload": {},
                    }, ensure_ascii=False) + "\n" +
                    json.dumps({
                        "event_name": "session_end",
                        "session_id": "s1",
                        "timestamp": "2026-04-10T10:04:00Z",
                        "payload": {"player_id": "p1"},
                    }, ensure_ascii=False) + "\n" +
                    json.dumps({
                        "event_name": "session_start",
                        "session_id": "s2",
                        "timestamp": "2026-04-11T10:00:00Z",
                        "payload": {"player_id": "p1"},
                    }, ensure_ascii=False) + "\n" +
                    json.dumps({
                        "event_name": "session_end",
                        "session_id": "s2",
                        "timestamp": "2026-04-11T10:02:00Z",
                        "payload": {"player_id": "p1"},
                    }, ensure_ascii=False) + "\n"
                ),
                encoding="utf-8",
            )

            router = GodotAgentRouter(godot_project_path=str(temp_project))
            with patch("api_server.main.manager.get_router", return_value=router):
                client = TestClient(app)
                response = client.get("/telemetry/retention-dashboard", params={"project_path": str(temp_project)})
        finally:
            shutil.rmtree(temp_project, ignore_errors=True)

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["dashboard"]["completion_rate"], 0.5)
        self.assertEqual(payload["dashboard"]["largest_dropoff_step"], "level_start")
        self.assertEqual(payload["dashboard"]["largest_dropoff_count"], 1)
        self.assertEqual(payload["dashboard"]["lowest_retention_window"], "d1")
        self.assertIn("# Retention Funnel Dashboard", payload["report_content"])

    @patch("agent_system.router.GodotCLI", ApiDataTableGodotCLI)
    def test_telemetry_trends_endpoint_returns_daily_build_channel_summary(self):
        from agent_system.router import GodotAgentRouter

        temp_project = project_root / "tests" / ".tmp_api_telemetry_trends"
        shutil.rmtree(temp_project, ignore_errors=True)
        try:
            telemetry_dir = temp_project / "telemetry"
            sessions_dir = telemetry_dir / "sessions"
            sessions_dir.mkdir(parents=True, exist_ok=True)
            (telemetry_dir / "event_catalog.json").write_text(
                json.dumps({
                    "schema_version": "1.1",
                    "events": [
                        {"event_name": "session_start", "category": "session", "description": "开始会话", "privacy_level": "anonymous", "fields": [{"name": "player_id", "type": "string", "required": True, "pii": False}]},
                        {"event_name": "level_start", "category": "gameplay", "description": "开始关卡", "privacy_level": "anonymous", "fields": []},
                        {"event_name": "level_complete", "category": "gameplay", "description": "完成关卡", "privacy_level": "anonymous", "fields": []},
                        {"event_name": "session_end", "category": "session", "description": "结束会话", "privacy_level": "anonymous", "fields": [{"name": "player_id", "type": "string", "required": True, "pii": False}]},
                    ],
                }, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            (sessions_dir / "session_001.jsonl").write_text(
                (
                    json.dumps({"event_name": "session_start", "session_id": "s1", "timestamp": "2026-04-10T10:00:00Z", "build_id": "web-preview-1", "channel": "qa", "payload": {"player_id": "p1"}}, ensure_ascii=False) + "\n" +
                    json.dumps({"event_name": "level_start", "session_id": "s1", "timestamp": "2026-04-10T10:01:00Z", "payload": {}}, ensure_ascii=False) + "\n" +
                    json.dumps({"event_name": "level_complete", "session_id": "s1", "timestamp": "2026-04-10T10:02:00Z", "payload": {}}, ensure_ascii=False) + "\n" +
                    json.dumps({"event_name": "session_end", "session_id": "s1", "timestamp": "2026-04-10T10:03:00Z", "payload": {"player_id": "p1"}}, ensure_ascii=False) + "\n"
                ),
                encoding="utf-8",
            )

            router = GodotAgentRouter(godot_project_path=str(temp_project))
            with patch("api_server.main.manager.get_router", return_value=router):
                client = TestClient(app)
                response = client.get("/telemetry/trends", params={"project_path": str(temp_project)})
        finally:
            shutil.rmtree(temp_project, ignore_errors=True)

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["dashboard"]["day_count"], 1)
        self.assertEqual(payload["dashboard"]["top_build_id"], "web-preview-1")
        self.assertEqual(payload["dashboard"]["channel_rows"][0]["channel"], "qa")
        self.assertIn("# Retention Funnel Trend Dashboard", payload["report_content"])

    @patch("agent_system.router.GodotCLI", ApiDataTableGodotCLI)
    def test_liveops_impact_dashboard_endpoint_returns_metric_matches(self):
        from agent_system.router import GodotAgentRouter

        temp_project = project_root / "tests" / ".tmp_api_liveops_impact"
        shutil.rmtree(temp_project, ignore_errors=True)
        try:
            telemetry_dir = temp_project / "telemetry"
            sessions_dir = telemetry_dir / "sessions"
            liveops_dir = temp_project / "liveops"
            sessions_dir.mkdir(parents=True, exist_ok=True)
            liveops_dir.mkdir(parents=True, exist_ok=True)
            (telemetry_dir / "event_catalog.json").write_text(
                json.dumps({
                    "schema_version": "1.1",
                    "events": [
                        {"event_name": "session_start", "category": "session", "description": "开始会话", "privacy_level": "anonymous", "fields": [{"name": "player_id", "type": "string", "required": True, "pii": False}]},
                        {"event_name": "session_end", "category": "session", "description": "结束会话", "privacy_level": "anonymous", "fields": [{"name": "player_id", "type": "string", "required": True, "pii": False}]},
                    ],
                }, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            (sessions_dir / "session_001.jsonl").write_text(
                (
                    json.dumps({"event_name": "session_start", "session_id": "s1", "timestamp": "2026-04-10T10:00:00Z", "payload": {"player_id": "p1"}}, ensure_ascii=False) + "\n" +
                    json.dumps({"event_name": "session_end", "session_id": "s1", "timestamp": "2026-04-11T10:00:00Z", "payload": {"player_id": "p1"}}, ensure_ascii=False) + "\n"
                ),
                encoding="utf-8",
            )
            (liveops_dir / "experiments.json").write_text(
                json.dumps({
                    "schema_version": "1.0",
                    "liveops_type": "experiment_catalog",
                    "items": [
                        {"experiment_id": "tutorial_branch_test", "status": "running", "owner": "product_ops", "rollout_percentage": 50, "target_metrics": ["d1_retention", "tutorial_completion_rate"], "variants": [{"variant_id": "control", "weight": 50}, {"variant_id": "branch", "weight": 50}]}
                    ],
                }, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )

            router = GodotAgentRouter(godot_project_path=str(temp_project))
            with patch("api_server.main.manager.get_router", return_value=router):
                client = TestClient(app)
                response = client.get("/liveops/impact-dashboard", params={"project_path": str(temp_project)})
        finally:
            shutil.rmtree(temp_project, ignore_errors=True)

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["dashboard"]["running_experiment_count"], 1)
        self.assertEqual(payload["dashboard"]["matched_metric_count"], 2)
        self.assertIn("# LiveOps Impact Dashboard", payload["report_content"])

    @patch("agent_system.router.GodotCLI", ApiDataTableGodotCLI)
    def test_performance_endpoint_returns_snapshot(self):
        baseline_path = project_root / "tests" / "baselines" / "performance" / "api_perf_snapshot_baseline.json"
        baseline_path.parent.mkdir(parents=True, exist_ok=True)
        baseline_path.write_text(
            json.dumps({
                "schema_version": "1.0",
                "scene_path": "res://scenes/main_scene.tscn",
                "metrics": {
                    "draw_call_count": 220,
                    "fps": 60,
                },
            }, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        try:
            client = TestClient(app)
            response = client.get(
                "/performance/profile",
                params={
                    "project_path": "default",
                    "scene_path": "res://scenes/main_scene.tscn",
                    "baseline_path": "tests/baselines/performance/api_perf_snapshot_baseline.json",
                },
            )
        finally:
            baseline_path.unlink(missing_ok=True)

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["baseline_display_path"], "tests/baselines/performance/api_perf_snapshot_baseline.json")
        self.assertTrue(payload["baseline_exists"])
        self.assertEqual(payload["baseline_metrics"]["draw_call_count"], 220)

    @patch("agent_system.router.GodotCLI", ApiDataTableGodotCLI)
    def test_performance_dashboard_endpoint_returns_frame_breakdown_and_memory_trend(self):
        profile_path = project_root / "logs" / "test_artifacts" / "api_perf_dashboard_profile.json"
        profile_path.parent.mkdir(parents=True, exist_ok=True)
        profile_path.write_text(
            json.dumps({
                "schema_version": "1.1",
                "scene_path": "res://scenes/main_scene.tscn",
                "metrics": {
                    "draw_call_count": 240,
                    "fps": 58,
                    "memory_peak_mb": 150,
                },
                "frame_breakdown": [
                    {"stage": "render", "ms": 7.5},
                    {"stage": "script", "ms": 3.0},
                ],
                "memory_trend": {
                    "sample_count": 4,
                    "min_mb": 120,
                    "max_mb": 150,
                    "avg_mb": 135,
                    "growth_mb": 30,
                    "trend_status": "growing",
                },
            }, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        try:
            client = TestClient(app)
            response = client.get(
                "/performance/dashboard",
                params={
                    "project_path": "default",
                    "scene_path": "res://scenes/main_scene.tscn",
                    "profile_path": "logs/test_artifacts/api_perf_dashboard_profile.json",
                },
            )
        finally:
            profile_path.unlink(missing_ok=True)

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["summary"]["metrics"]["top_frame_stage"], "render")
        self.assertEqual(payload["summary"]["memory_trend"]["growth_mb"], 30.0)
        self.assertIn("# Performance Analysis Report", payload["report_content"])

    @patch("agent_system.router.GodotCLI", ApiDataTableGodotCLI)
    def test_manage_performance_endpoint_can_baseline_and_analyze(self):
        from agent_system.router import GodotAgentRouter

        temp_project = project_root / "tests" / ".tmp_api_performance_manage"
        baseline_rel = "tests/baselines/performance/api_perf_manage_baseline.json"
        baseline_path = project_root / baseline_rel
        baseline_exists = False
        report_path = ""
        profile_path = ""
        shutil.rmtree(temp_project, ignore_errors=True)
        baseline_path.unlink(missing_ok=True)
        try:
            router = GodotAgentRouter(godot_project_path=str(temp_project))
            with patch("api_server.main.manager.get_router", return_value=router):
                client = TestClient(app)
                baseline_response = client.post(
                    "/performance/manage",
                    json={
                        "project_path": str(temp_project),
                        "action": "baseline",
                        "scene_path": "res://scenes/main_scene.tscn",
                        "baseline_path": baseline_rel,
                        "profile_metrics": {
                            "draw_call_count": 240,
                            "node_count": 180,
                            "fps": 60,
                        },
                        "budget_overrides": {
                            "max_draw_call_count": 320,
                            "max_node_count": 220,
                            "min_fps": 55,
                        },
                    },
                )
                baseline_exists = baseline_path.exists()
                analyze_response = client.post(
                    "/performance/manage",
                    json={
                        "project_path": str(temp_project),
                        "action": "analyze",
                        "scene_path": "res://scenes/main_scene.tscn",
                        "baseline_path": baseline_rel,
                        "profile_metrics": {
                            "draw_call_count": 280,
                            "node_count": 200,
                            "fps": 58,
                        },
                        "budget_overrides": {
                            "max_draw_call_count": 320,
                            "max_node_count": 220,
                            "min_fps": 55,
                        },
                    },
                )
                analyze_payload = analyze_response.json()
                report_path = analyze_payload.get("context", {}).get("performance_report_path", "")
                profile_path = analyze_payload.get("context", {}).get("performance_profile_path", "")
        finally:
            if report_path:
                Path(report_path).unlink(missing_ok=True)
            if profile_path:
                Path(profile_path).unlink(missing_ok=True)
            baseline_path.unlink(missing_ok=True)
            shutil.rmtree(temp_project, ignore_errors=True)

        self.assertEqual(baseline_response.status_code, 200)
        baseline_payload = baseline_response.json()
        self.assertEqual(baseline_payload["status"], "success")
        self.assertTrue(baseline_exists)
        self.assertEqual(baseline_payload["context"]["performance_summary"]["metrics"]["draw_call_count"], 240)

        self.assertEqual(analyze_response.status_code, 200)
        self.assertEqual(analyze_payload["status"], "success")
        self.assertTrue(analyze_payload["context"]["performance_passed"])
        self.assertEqual(analyze_payload["performance"]["summary"]["metrics"]["draw_call_count"], 280)

    @patch("agent_system.router.GodotCLI", ApiDataTableGodotCLI)
    def test_manage_platform_delivery_endpoint_can_template_and_validate(self):
        from agent_system.router import GodotAgentRouter

        temp_project = project_root / "tests" / ".tmp_api_platform_delivery"
        shutil.rmtree(temp_project, ignore_errors=True)
        try:
            router = GodotAgentRouter(godot_project_path=str(temp_project))
            with patch("api_server.main.manager.get_router", return_value=router):
                client = TestClient(app)
                template_response = client.post(
                    "/platform-delivery/manage",
                    json={
                        "project_path": str(temp_project),
                        "action": "template",
                    },
                )
                validate_response = client.post(
                    "/platform-delivery/manage",
                    json={
                        "project_path": str(temp_project),
                        "action": "validate",
                        "platforms": [{
                            "platform_id": "windows_desktop",
                            "store": "itch",
                            "preset_name": "Windows Desktop",
                            "output_path": "builds/windows/game.exe",
                            "arch": "x86_64",
                            "feature_flags": ["cloud_save", "analytics"],
                        }],
                        "savegame": {
                            "schema_id": "profile_save",
                            "version": "1.0.0",
                            "save_mode": "cloud_optional",
                            "slot_count": 3,
                            "fields": [{"name": "player_level", "type": "int", "required": True, "default": 1}],
                        },
                        "services": {
                            "cloud_save": True,
                            "achievements": True,
                            "leaderboard": False,
                            "analytics": True,
                        },
                        "multiplayer": {
                            "enabled": True,
                            "mode": "coop",
                            "transport": "enet",
                            "max_players": 4,
                            "rollback_supported": True,
                        },
                    },
                )
                manifest_path = temp_project / "deployment" / "platform_delivery.json"
                manifest_exists = manifest_path.exists()
                manifest_content = manifest_path.read_text(encoding="utf-8") if manifest_exists else ""
        finally:
            shutil.rmtree(temp_project, ignore_errors=True)

        self.assertEqual(template_response.status_code, 200)
        template_payload = template_response.json()
        self.assertEqual(template_payload["status"], "success")
        self.assertEqual(template_payload["context"]["last_skill_result"]["skill_name"], "manage_platform_delivery")
        self.assertEqual(template_payload["platform_delivery_profile"]["platform_count"], 2)
        self.assertTrue(manifest_exists)
        self.assertIn('"schema_id": "profile_save"', manifest_content)

        self.assertEqual(validate_response.status_code, 200)
        validate_payload = validate_response.json()
        self.assertEqual(validate_payload["status"], "success")
        self.assertEqual(validate_payload["platform_delivery_profile"]["platform_count"], 1)
        self.assertTrue(validate_payload["context"]["last_skill_result"]["validation"]["passed"])

    def test_mcp_onboarding_endpoint_returns_codex_gemini_and_ide_guidance(self):
        temp_skills_root = project_root / "tests" / ".tmp_codex_skills_root"
        shutil.rmtree(temp_skills_root, ignore_errors=True)
        try:
            with patch("api_server.main._resolve_codex_skill_root", return_value=temp_skills_root):
                client = TestClient(app)
                response = client.get("/mcp/onboarding", params={"project_path": "default"})
        finally:
            shutil.rmtree(temp_skills_root, ignore_errors=True)

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["server_name"], "godot")
        self.assertIn("codex mcp add godot", payload["codex"]["mcp_add_command"])
        self.assertIn("[mcp_servers.godot]", payload["codex"]["config_toml_snippet"])
        self.assertEqual(payload["codex"]["skill_name"], "closure-first-engineer")
        self.assertFalse(payload["codex"]["skill_installed"])
        self.assertIn("\"mcpServers\"", payload["gemini"]["settings_json"])
        self.assertIn("vscode_agent.py", payload["ide"]["vscode_agent_command"])
        self.assertTrue(payload["ide"]["guide_url"].startswith("/artifact-file"))

    def test_install_codex_skill_endpoint_syncs_repo_skill_to_global_dir(self):
        temp_skills_root = project_root / "tests" / ".tmp_codex_skills_install"
        shutil.rmtree(temp_skills_root, ignore_errors=True)
        try:
            with patch("api_server.main._resolve_codex_skill_root", return_value=temp_skills_root):
                client = TestClient(app)
                response = client.post("/mcp/install-codex-skill", json={"project_path": "default"})

                installed_skill = temp_skills_root / "closure-first-engineer" / "SKILL.md"
                installed_exists = installed_skill.exists()
                installed_content = installed_skill.read_text(encoding="utf-8") if installed_exists else ""
        finally:
            shutil.rmtree(temp_skills_root, ignore_errors=True)

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["install_result"]["ok"])
        self.assertTrue(payload["codex"]["skill_installed"])
        self.assertTrue(installed_exists)
        self.assertIn("closure-first-engineer", installed_content)

    def test_contract_versions_endpoint_returns_catalog(self):
        client = TestClient(app)
        response = client.get("/contracts/versions", params={"project_path": "default"})

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["schema_version"], "1.0")
        contract_names = {item["contract_name"] for item in payload["contracts"]}
        self.assertEqual(contract_names, {
            "balance_analysis",
            "build_run_matrix",
            "change_admission",
            "feature_context",
            "governance_enforcement",
            "governance_policy",
            "agent_provider_compatibility",
            "asset_review_workflow",
            "liveops_profile",
            "outsource_delivery_gate",
            "performance_summary",
            "platform_delivery_profile",
            "presentation_profile",
            "release_candidate_checklist",
            "release_capability_registry",
            "release_capability_policy",
            "release_runtime_assembly_snapshot",
            "release_delivery_readiness",
            "release_artifact_manifest",
            "release_live_event_stream",
            "release_live_dispatch_preflight",
            "release_live_dispatch_audit",
            "release_execution_status",
            "release_promotion_history",
            "release_promotion_plan",
            "release_review_bundle",
            "production_readiness",
            "production_scenarios",
            "quality_gate",
            "release_qa_evidence",
            "release_summary",
            "scene_ownership_board",
            "skill_result",
            "telemetry_summary",
        })
        self.assertTrue(any(
            item["entrypoint"] == "build_task_feature_context"
            for item in payload["contracts"]
        ))
        artifact_manifest_contract = next(
            item for item in payload["contracts"]
            if item["contract_name"] == "release_artifact_manifest"
        )
        self.assertEqual(artifact_manifest_contract["entrypoint"], "normalize_release_artifact_manifest")
        self.assertEqual(artifact_manifest_contract["normalization_strategy"], "normalize_on_read")

    def test_report_file_returns_markdown(self):
        report_path = project_root / "logs" / "reports" / "test_api_report.md"
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text("# API Report\n\nhello\n", encoding="utf-8")

        try:
            client = TestClient(app)
            response = client.get("/report-file", params={"path": "logs/reports/test_api_report.md"})
        finally:
            report_path.unlink(missing_ok=True)

        self.assertEqual(response.status_code, 200)
        self.assertIn("# API Report", response.text)

    def test_artifact_file_returns_project_file(self):
        temp_project = project_root / "tests" / ".tmp_api_artifact_file"
        shutil.rmtree(temp_project, ignore_errors=True)
        try:
            scripts_dir = temp_project / "scripts"
            scripts_dir.mkdir(parents=True, exist_ok=True)
            script_file = scripts_dir / "player_controller.gd"
            script_file.write_text("extends Node\n", encoding="utf-8")

            client = TestClient(app)
            response = client.get(
                "/artifact-file",
                params={
                    "project_path": str(temp_project),
                    "path": "res://scripts/player_controller.gd"
                }
            )
        finally:
            shutil.rmtree(temp_project, ignore_errors=True)

        self.assertEqual(response.status_code, 200)
        self.assertIn("extends Node", response.text)

    def test_source_preview_returns_snippet(self):
        temp_project = project_root / "tests" / ".tmp_api_source_preview"
        shutil.rmtree(temp_project, ignore_errors=True)
        try:
            scene_dir = temp_project / "scenes"
            scene_dir.mkdir(parents=True, exist_ok=True)
            scene_file = scene_dir / "demo_scene.tscn"
            scene_file.write_text(
                "[gd_scene format=3]\n\n[node name=\"demo\" type=\"Node2D\"]\nposition = Vector2(0, 0)\n",
                encoding="utf-8"
            )

            client = TestClient(app)
            response = client.get(
                "/source-preview",
                params={
                    "project_path": str(temp_project),
                    "path": "scenes/demo_scene.tscn",
                    "line": 3
                }
            )
        finally:
            shutil.rmtree(temp_project, ignore_errors=True)

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["path"], "scenes/demo_scene.tscn")
        self.assertEqual(payload["line"], 3)
        self.assertTrue(any(line["number"] == 3 for line in payload["lines"]))
        self.assertEqual(payload["scene_node_name"], "demo")
        self.assertEqual(payload["scene_node_path"], ".")
        self.assertEqual(payload["scene_node_line"], 3)
        self.assertIn("节点: demo", payload["preview_context_label"])

    def test_source_preview_returns_gdscript_context(self):
        temp_project = project_root / "tests" / ".tmp_api_source_preview_gdscript"
        shutil.rmtree(temp_project, ignore_errors=True)
        try:
            scripts_dir = temp_project / "scripts"
            scripts_dir.mkdir(parents=True, exist_ok=True)
            script_file = scripts_dir / "player_controller.gd"
            script_file.write_text(
                'extends CharacterBody2D\n'
                'class_name PlayerController\n'
                '\n'
                'signal jumped(height)\n'
                '\n'
                'func _ready():\n'
                '    pass\n'
                '\n'
                'func _physics_process(delta):\n'
                '    velocity.x = delta * 100.0\n',
                encoding="utf-8"
            )

            client = TestClient(app)
            response = client.get(
                "/source-preview",
                params={
                    "project_path": str(temp_project),
                    "path": "scripts/player_controller.gd",
                    "line": 10
                }
            )
        finally:
            shutil.rmtree(temp_project, ignore_errors=True)

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["path"], "scripts/player_controller.gd")
        self.assertEqual(payload["script_class_name"], "PlayerController")
        self.assertEqual(payload["script_class_line"], 2)
        self.assertEqual(payload["script_symbol_kind"], "func")
        self.assertEqual(payload["script_symbol_name"], "_physics_process")
        self.assertEqual(payload["script_symbol_signature"], "_physics_process(delta)")
        self.assertEqual(payload["script_symbol_line"], 9)
        self.assertIn("类: PlayerController", payload["preview_context_label"])
        self.assertIn("函数: _physics_process(delta)", payload["preview_context_label"])

    def test_open_resource_queues_editor_command(self):
        temp_project = project_root / "tests" / ".tmp_api_open_resource"
        shutil.rmtree(temp_project, ignore_errors=True)
        try:
            scenes_dir = temp_project / "scenes"
            scenes_dir.mkdir(parents=True, exist_ok=True)
            scene_file = scenes_dir / "demo_scene.tscn"
            scene_file.write_text(
                '[gd_scene load_steps=1 format=3 uid="uid://demo_scene_uid"]\n'
                '\n'
                '[node name="demo_scene" type="Node2D"]\n'
                '[node name="weapon_slot" type="Node2D" parent="."]\n'
                'position = Vector2(12, 18)\n',
                encoding="utf-8"
            )

            manager.editor_states[str(temp_project)] = {"is_active": True}
            client = TestClient(app)
            response = client.post(
                "/editor/open-resource",
                json={
                    "project_path": str(temp_project),
                    "path": "scenes/demo_scene.tscn:line3"
                }
            )
        finally:
            shutil.rmtree(temp_project, ignore_errors=True)

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["path"], "scenes/demo_scene.tscn")
        self.assertEqual(payload["resource_path"], "res://scenes/demo_scene.tscn")
        self.assertEqual(payload["line"], 3)
        self.assertEqual(payload["scene_node_name"], "demo_scene")
        self.assertEqual(payload["scene_node_path"], ".")

        queue = manager.get_queue(str(temp_project))
        self.assertEqual(len(queue), 1)
        self.assertEqual(queue[0]["type"], "open_resource")
        self.assertEqual(queue[0]["path"], "res://scenes/demo_scene.tscn")
        self.assertEqual(queue[0]["line"], 3)
        self.assertEqual(queue[0]["scene_node_name"], "demo_scene")
        self.assertEqual(queue[0]["scene_node_path"], ".")

    def test_editor_operation_queues_typed_command(self):
        temp_project = project_root / "tests" / ".tmp_api_editor_operation"
        shutil.rmtree(temp_project, ignore_errors=True)
        temp_project.mkdir(parents=True, exist_ok=True)
        try:
            manager.editor_states[str(temp_project)] = {"is_active": True}
            client = TestClient(app)
            response = client.post(
                "/editor/operation",
                json={
                    "project_path": str(temp_project),
                    "operation": "set_node_property",
                    "node_path": "Player",
                    "property_name": "position",
                    "value": [32, 48],
                    "value_type": "vector2",
                    "wait_for_editor_event": False,
                }
            )
        finally:
            shutil.rmtree(temp_project, ignore_errors=True)

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["operation"], "set_node_property")
        self.assertEqual(payload["schema_version"], "1.1")
        self.assertEqual(payload["audit"]["operation"], "set_node_property")
        self.assertEqual(payload["audit"]["rollback_anchor"]["kind"], "editor_operation")
        self.assertTrue(payload["queued"])

        queue = manager.get_queue(str(temp_project))
        self.assertEqual(len(queue), 1)
        self.assertEqual(queue[0]["type"], "editor_operation")
        self.assertEqual(queue[0]["schema_version"], "1.1")
        self.assertEqual(queue[0]["operation"], "set_node_property")
        self.assertEqual(queue[0]["node_path"], "Player")
        self.assertEqual(queue[0]["property_name"], "position")
        self.assertEqual(queue[0]["value"], [32, 48])
        self.assertEqual(queue[0]["value_type"], "vector2")
        self.assertEqual(queue[0]["audit"]["audit_id"], payload["audit"]["audit_id"])

    def test_editor_operation_queues_p7_batch_command(self):
        temp_project = project_root / "tests" / ".tmp_api_editor_operation_batch"
        shutil.rmtree(temp_project, ignore_errors=True)
        temp_project.mkdir(parents=True, exist_ok=True)
        try:
            manager.editor_states[str(temp_project)] = {"is_active": True}
            client = TestClient(app)
            response = client.post(
                "/editor/operation",
                json={
                    "project_path": str(temp_project),
                    "operation": "batch_create_nodes",
                    "items": [
                        {"parent_path": ".", "node_type": "Node2D", "node_name": "Rooms"},
                        {"parent_path": "Rooms", "node_type": "Marker2D", "node_name": "SpawnA"},
                    ],
                    "wait_for_editor_event": False,
                }
            )
        finally:
            shutil.rmtree(temp_project, ignore_errors=True)

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["operation"], "batch_create_nodes")
        self.assertEqual(payload["schema_version"], "1.1")
        self.assertEqual(payload["audit"]["operation"], "batch_create_nodes")

        queue = manager.get_queue(str(temp_project))
        self.assertEqual(len(queue), 1)
        self.assertEqual(queue[0]["operation"], "batch_create_nodes")
        self.assertEqual(queue[0]["items"][1]["node_name"], "SpawnA")
        self.assertEqual(queue[0]["audit"]["rollback_anchor"]["operation"], "batch_create_nodes")

    def test_editor_operation_can_wait_for_command_ack(self):
        temp_project = project_root / "tests" / ".tmp_api_editor_operation_wait"
        shutil.rmtree(temp_project, ignore_errors=True)
        temp_project.mkdir(parents=True, exist_ok=True)
        try:
            manager.editor_states[str(temp_project)] = {"is_active": True}
            timer = threading.Timer(
                0.1,
                lambda: manager.record_editor_event(
                    str(temp_project),
                    {
                        "kind": "editor_operation",
                        "operation": "select_node",
                        "status": "success",
                        "message": "已选中节点 Player",
                        "command_id": "cmd_fixed",
                    }
                )
            )
            timer.start()
            with patch.object(manager, "next_command_id", return_value="cmd_fixed"):
                client = TestClient(app)
                response = client.post(
                    "/editor/operation",
                    json={
                        "project_path": str(temp_project),
                        "operation": "select_node",
                        "node_name": "Player",
                        "wait_for_editor_event": True,
                        "editor_event_timeout": 2,
                    }
                )
            timer.join(timeout=1)
        finally:
            shutil.rmtree(temp_project, ignore_errors=True)

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["command_id"], "cmd_fixed")
        self.assertEqual(payload["editor_event"]["kind"], "editor_operation")
        self.assertEqual(payload["editor_event"]["operation"], "select_node")
        self.assertEqual(payload["editor_event"]["status"], "success")

    def test_editor_operation_rejects_unknown_operation(self):
        temp_project = project_root / "tests" / ".tmp_api_editor_operation_invalid"
        shutil.rmtree(temp_project, ignore_errors=True)
        temp_project.mkdir(parents=True, exist_ok=True)
        try:
            manager.editor_states[str(temp_project)] = {"is_active": True}
            client = TestClient(app)
            response = client.post(
                "/editor/operation",
                json={
                    "project_path": str(temp_project),
                    "operation": "teleport_editor",
                    "wait_for_editor_event": False,
                }
            )
        finally:
            shutil.rmtree(temp_project, ignore_errors=True)

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["detail"], "Unsupported editor operation")

    def test_editor_operation_validates_required_p7_fields(self):
        temp_project = project_root / "tests" / ".tmp_api_editor_operation_missing_fields"
        shutil.rmtree(temp_project, ignore_errors=True)
        temp_project.mkdir(parents=True, exist_ok=True)
        try:
            manager.editor_states[str(temp_project)] = {"is_active": True}
            client = TestClient(app)
            response = client.post(
                "/editor/operation",
                json={
                    "project_path": str(temp_project),
                    "operation": "save_scene_as",
                    "wait_for_editor_event": False,
                }
            )
        finally:
            shutil.rmtree(temp_project, ignore_errors=True)

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["detail"], "Missing scene_path")

    def test_editor_operation_requires_active_editor(self):
        temp_project = project_root / "tests" / ".tmp_api_editor_operation_offline"
        shutil.rmtree(temp_project, ignore_errors=True)
        temp_project.mkdir(parents=True, exist_ok=True)
        try:
            client = TestClient(app)
            response = client.post(
                "/editor/operation",
                json={
                    "project_path": str(temp_project),
                    "operation": "get_scene_tree",
                    "wait_for_editor_event": False,
                }
            )
        finally:
            shutil.rmtree(temp_project, ignore_errors=True)

        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["detail"], "Editor is offline")

    def test_launch_editor_endpoint_returns_launch_metadata(self):
        temp_project = project_root / "tests" / ".tmp_api_launch_editor"
        shutil.rmtree(temp_project, ignore_errors=True)
        temp_project.mkdir(parents=True, exist_ok=True)
        try:
            fake_router = FakeEditorExecutionRouter(
                launch_callback=lambda _scene_path: manager.editor_states.__setitem__(
                    str(temp_project),
                    {"is_active": True, "project_path": str(temp_project)}
                )
            )
            with patch("api_server.main.manager.get_router", return_value=fake_router):
                client = TestClient(app)
                response = client.post(
                    "/editor/launch",
                    json={
                        "project_path": str(temp_project),
                        "wait_for_editor": True
                    }
                )
        finally:
            shutil.rmtree(temp_project, ignore_errors=True)

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["ok"])
        self.assertTrue(payload["editor_online"])
        self.assertEqual(payload["launch"]["status"], "launching")
        self.assertEqual(payload["launch"]["pid"], 4321)
        self.assertEqual(payload["launch"]["executable_source"], "env")
        self.assertEqual(payload["launch"]["executable_source_label"], "GODOT")
        self.assertTrue(payload["editor_state"]["is_active"])

    def test_execute_auto_launches_editor_and_queues_editor_script(self):
        temp_project = project_root / "tests" / ".tmp_api_execute_auto_launch"
        shutil.rmtree(temp_project, ignore_errors=True)
        temp_project.mkdir(parents=True, exist_ok=True)
        try:
            fake_router = FakeEditorExecutionRouter(
                launch_callback=lambda _scene_path: manager.editor_states.__setitem__(
                    str(temp_project),
                    {"is_active": True, "project_path": str(temp_project)}
                )
            )
            with patch("api_server.main.manager.get_router", return_value=fake_router):
                client = TestClient(app)
                response = client.post(
                    "/execute",
                    json={
                        "project_path": str(temp_project),
                        "command": "在当前节点下添加一个 Sprite2D 节点",
                        "auto_launch_editor": True,
                        "wait_for_editor": True
                    }
                )
        finally:
            shutil.rmtree(temp_project, ignore_errors=True)

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["status"], "success")
        self.assertEqual(payload["context"]["editor_launch"]["status"], "launching")
        self.assertEqual(payload["context"]["editor_launch"]["pid"], 4321)
        self.assertEqual(payload["context"]["editor_launch"]["executable_source"], "env")
        self.assertEqual(payload["context"]["editor_launch"]["executable_source_label"], "GODOT")

        queue = manager.get_queue(str(temp_project))
        self.assertEqual(len(queue), 1)
        self.assertEqual(queue[0]["type"], "execute_script")

    def test_resume_task_matches_waiting_step_by_step_id(self):
        temp_project = project_root / "tests" / ".tmp_api_resume_task_step_id"
        shutil.rmtree(temp_project, ignore_errors=True)
        temp_project.mkdir(parents=True, exist_ok=True)
        try:
            task = Task(prompt="生成代码", status=TaskStatus.WAITING_ACK)
            step_a = TaskStep(name="First", description="第一步", role="developer", status=TaskStatus.WAITING_ACK)
            step_b = TaskStep(name="Second", description="第二步", role="code_generator", status=TaskStatus.WAITING_ACK)
            task.steps = [step_a, step_b]

            class ResumeRouter:
                def __init__(self, held_task):
                    self.held_task = held_task
                    self.resume_calls = 0

                def get_task(self, task_id):
                    return self.held_task if task_id == self.held_task.task_id else None

                def execute_plan(self, incoming_task):
                    self.resume_calls += 1
                    return incoming_task

            fake_router = ResumeRouter(task)
            cmd_id = manager.next_command_id(str(temp_project))
            manager.register_command(
                str(temp_project),
                {
                    "command_id": cmd_id,
                    "task_id": task.task_id,
                    "step_id": step_b.step_id,
                    "type": "execute_script",
                }
            )

            with patch("api_server.main.manager.get_router", return_value=fake_router):
                manager.record_editor_event(
                    str(temp_project),
                    {
                        "kind": "execute_script",
                        "status": "success",
                        "message": "Godot 内部脚本执行完成",
                        "command_id": cmd_id,
                    }
                )
        finally:
            shutil.rmtree(temp_project, ignore_errors=True)

        self.assertEqual(step_a.status, TaskStatus.WAITING_ACK)
        self.assertEqual(step_b.status, TaskStatus.SUCCESS)
        self.assertEqual(fake_router.resume_calls, 1)

    def test_wait_editor_event_endpoint_returns_new_event(self):
        temp_project = project_root / "tests" / ".tmp_api_wait_event"
        shutil.rmtree(temp_project, ignore_errors=True)
        temp_project.mkdir(parents=True, exist_ok=True)
        try:
            seed_event = manager.record_editor_event(
                str(temp_project),
                {
                    "kind": "execute_script",
                    "status": "success",
                    "message": "旧回执",
                }
            )
            timer = threading.Timer(
                0.1,
                lambda: manager.record_editor_event(
                    str(temp_project),
                    {
                        "kind": "open_resource",
                        "status": "success",
                        "message": "新回执",
                    }
                )
            )
            timer.start()
            client = TestClient(app)
            response = client.post(
                "/editor/wait-event",
                json={
                    "project_path": str(temp_project),
                    "after_event_id": seed_event["event_id"],
                    "kind": "open_resource",
                    "timeout": 2,
                }
            )
            timer.join(timeout=1)
        finally:
            shutil.rmtree(temp_project, ignore_errors=True)

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["event"]["event_id"], 2)
        self.assertEqual(payload["event"]["kind"], "open_resource")
        self.assertEqual(payload["event"]["message"], "新回执")

    def test_execute_can_wait_for_editor_event(self):
        temp_project = project_root / "tests" / ".tmp_api_execute_wait_event"
        shutil.rmtree(temp_project, ignore_errors=True)
        temp_project.mkdir(parents=True, exist_ok=True)
        try:
            manager.editor_states[str(temp_project)] = {"is_active": True}
            timer = threading.Timer(
                0.1,
                lambda: manager.record_editor_event(
                    str(temp_project),
                    {
                        "kind": "execute_script",
                        "status": "success",
                        "message": "Godot 内部脚本执行完成",
                    }
                )
            )
            timer.start()
            with patch("api_server.main.manager.get_router", return_value=FakeEditorExecutionRouter()):
                client = TestClient(app)
                response = client.post(
                    "/execute",
                    json={
                        "project_path": str(temp_project),
                        "command": "在当前节点下添加一个 Sprite2D 节点",
                        "wait_for_editor_event": True,
                        "editor_event_timeout": 2,
                    }
                )
            timer.join(timeout=1)
        finally:
            shutil.rmtree(temp_project, ignore_errors=True)

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["editor_event"]["kind"], "execute_script")
        self.assertEqual(payload["editor_event"]["status"], "success")
        self.assertEqual(payload["context"]["editor_event"]["message"], "Godot 内部脚本执行完成")

    def test_execute_wait_for_editor_event_ignores_stale_command_ack(self):
        temp_project = project_root / "tests" / ".tmp_api_execute_wait_event_stale"
        shutil.rmtree(temp_project, ignore_errors=True)
        temp_project.mkdir(parents=True, exist_ok=True)
        try:
            manager.editor_states[str(temp_project)] = {"is_active": True}
            stale_event = manager.record_editor_event(
                str(temp_project),
                {
                    "kind": "execute_script",
                    "status": "success",
                    "message": "旧回执",
                    "command_id": "cmd_old",
                }
            )
            timer = threading.Timer(
                0.1,
                lambda: manager.record_editor_event(
                    str(temp_project),
                    {
                        "kind": "execute_script",
                        "status": "success",
                        "message": "新回执",
                    }
                )
            )
            timer.start()
            with patch("api_server.main.manager.get_router", return_value=FakeEditorExecutionRouter()):
                client = TestClient(app)
                response = client.post(
                    "/execute",
                    json={
                        "project_path": str(temp_project),
                        "command": "在当前节点下添加一个 Sprite2D 节点",
                        "wait_for_editor_event": True,
                        "editor_event_timeout": 2,
                    }
                )
            timer.join(timeout=1)
        finally:
            shutil.rmtree(temp_project, ignore_errors=True)

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertNotEqual(payload["editor_event"].get("command_id"), stale_event["command_id"])
        self.assertEqual(payload["editor_event"]["message"], "新回执")

    def test_open_resource_scene_property_line_targets_nearest_node(self):
        temp_project = project_root / "tests" / ".tmp_api_open_resource_scene_hint"
        shutil.rmtree(temp_project, ignore_errors=True)
        try:
            scenes_dir = temp_project / "scenes"
            scenes_dir.mkdir(parents=True, exist_ok=True)
            scene_file = scenes_dir / "demo_scene.tscn"
            scene_file.write_text(
                '[gd_scene load_steps=1 format=3 uid="uid://demo_scene_uid"]\n'
                '\n'
                '[node name="demo_scene" type="Node2D"]\n'
                '[node name="weapon_slot" type="Node2D" parent="."]\n'
                'position = Vector2(12, 18)\n',
                encoding="utf-8"
            )

            manager.editor_states[str(temp_project)] = {"is_active": True}
            client = TestClient(app)
            response = client.post(
                "/editor/open-resource",
                json={
                    "project_path": str(temp_project),
                    "path": "scenes/demo_scene.tscn:line5"
                }
            )
        finally:
            shutil.rmtree(temp_project, ignore_errors=True)

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["line"], 5)
        self.assertEqual(payload["scene_node_name"], "weapon_slot")
        self.assertEqual(payload["scene_node_path"], "weapon_slot")
        self.assertEqual(payload["scene_node_line"], 4)
        self.assertIn("节点: weapon_slot", payload["message"])

        queue = manager.get_queue(str(temp_project))
        self.assertEqual(queue[0]["scene_node_name"], "weapon_slot")
        self.assertEqual(queue[0]["scene_node_path"], "weapon_slot")

    def test_open_resource_duplicate_scene_node_names_report_full_path(self):
        temp_project = project_root / "tests" / ".tmp_api_open_resource_duplicate_names"
        shutil.rmtree(temp_project, ignore_errors=True)
        try:
            scenes_dir = temp_project / "scenes"
            scenes_dir.mkdir(parents=True, exist_ok=True)
            scene_file = scenes_dir / "demo_scene.tscn"
            scene_file.write_text(
                '[gd_scene load_steps=1 format=3 uid="uid://demo_scene_uid"]\n'
                '\n'
                '[node name="demo_scene" type="Node2D"]\n'
                '[node name="player" type="Node2D" parent="."]\n'
                '[node name="weapon_slot" type="Node2D" parent="player"]\n'
                '[node name="enemy" type="Node2D" parent="."]\n'
                '[node name="weapon_slot" type="Node2D" parent="enemy"]\n'
                'position = Vector2(42, 24)\n',
                encoding="utf-8"
            )

            manager.editor_states[str(temp_project)] = {"is_active": True}
            client = TestClient(app)
            response = client.post(
                "/editor/open-resource",
                json={
                    "project_path": str(temp_project),
                    "path": "scenes/demo_scene.tscn:line7"
                }
            )
        finally:
            shutil.rmtree(temp_project, ignore_errors=True)

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["scene_node_name"], "weapon_slot")
        self.assertEqual(payload["scene_node_path"], "enemy/weapon_slot")
        self.assertIn("路径: enemy/weapon_slot", payload["message"])

        queue = manager.get_queue(str(temp_project))
        self.assertEqual(queue[0]["scene_node_path"], "enemy/weapon_slot")

    def test_open_resource_can_wait_for_editor_event(self):
        temp_project = project_root / "tests" / ".tmp_api_open_resource_wait_event"
        shutil.rmtree(temp_project, ignore_errors=True)
        try:
            scenes_dir = temp_project / "scenes"
            scenes_dir.mkdir(parents=True, exist_ok=True)
            scene_file = scenes_dir / "demo_scene.tscn"
            scene_file.write_text(
                '[gd_scene load_steps=1 format=3 uid="uid://demo_scene_uid"]\n'
                '\n'
                '[node name="demo_scene" type="Node2D"]\n',
                encoding="utf-8"
            )

            manager.editor_states[str(temp_project)] = {"is_active": True}
            timer = threading.Timer(
                0.1,
                lambda: manager.record_editor_event(
                    str(temp_project),
                    {
                        "kind": "open_resource",
                        "status": "success",
                        "message": "Godot 已打开场景 res://scenes/demo_scene.tscn 并选中节点 demo_scene (.)",
                        "path": "res://scenes/demo_scene.tscn",
                    }
                )
            )
            timer.start()
            client = TestClient(app)
            response = client.post(
                "/editor/open-resource",
                json={
                    "project_path": str(temp_project),
                    "path": "scenes/demo_scene.tscn:line3",
                    "wait_for_editor_event": True,
                    "editor_event_timeout": 2,
                }
            )
            timer.join(timeout=1)
        finally:
            shutil.rmtree(temp_project, ignore_errors=True)

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["editor_event"]["kind"], "open_resource")
        self.assertEqual(payload["editor_event"]["status"], "success")
        self.assertIn("Godot 已打开场景", payload["editor_event"]["message"])

    def test_open_resource_scene_instance_branch_reports_instance_source(self):
        temp_project = project_root / "tests" / ".tmp_api_open_resource_instance_branch"
        shutil.rmtree(temp_project, ignore_errors=True)
        try:
            scenes_dir = temp_project / "scenes"
            actors_dir = temp_project / "actors"
            scenes_dir.mkdir(parents=True, exist_ok=True)
            actors_dir.mkdir(parents=True, exist_ok=True)
            (actors_dir / "enemy.tscn").write_text(
                '[gd_scene load_steps=1 format=3 uid="uid://enemy_scene_uid"]\n'
                '\n'
                '[node name="enemy_root" type="Node2D"]\n',
                encoding="utf-8"
            )
            (scenes_dir / "battle_scene.tscn").write_text(
                '[gd_scene load_steps=2 format=3 uid="uid://battle_scene_uid"]\n'
                '\n'
                '[ext_resource type="PackedScene" path="res://actors/enemy.tscn" id="1_enemy"]\n'
                '\n'
                '[node name="battle_scene" type="Node2D"]\n'
                '[node name="enemy_spawn" parent="." instance=ExtResource("1_enemy")]\n'
                '[node name="weapon_slot" type="Node2D" parent="enemy_spawn" owner="battle_scene"]\n'
                'position = Vector2(64, 16)\n',
                encoding="utf-8"
            )

            manager.editor_states[str(temp_project)] = {"is_active": True}
            client = TestClient(app)
            response = client.post(
                "/editor/open-resource",
                json={
                    "project_path": str(temp_project),
                    "path": "scenes/battle_scene.tscn:line7"
                }
            )
        finally:
            shutil.rmtree(temp_project, ignore_errors=True)

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["scene_node_name"], "weapon_slot")
        self.assertEqual(payload["scene_node_path"], "enemy_spawn/weapon_slot")
        self.assertEqual(payload["scene_owner_path"], "battle_scene")
        self.assertEqual(payload["scene_instance_root_path"], "enemy_spawn")
        self.assertEqual(payload["scene_instance_source"], "res://actors/enemy.tscn")
        self.assertIn("实例源: actors/enemy.tscn", payload["message"])

        queue = manager.get_queue(str(temp_project))
        self.assertEqual(queue[0]["scene_instance_root_path"], "enemy_spawn")
        self.assertEqual(queue[0]["scene_instance_source"], "res://actors/enemy.tscn")

    def test_open_resource_gdscript_line_reports_function_and_class(self):
        temp_project = project_root / "tests" / ".tmp_api_open_resource_script_symbol"
        shutil.rmtree(temp_project, ignore_errors=True)
        try:
            scripts_dir = temp_project / "scripts"
            scripts_dir.mkdir(parents=True, exist_ok=True)
            (scripts_dir / "player_controller.gd").write_text(
                'extends CharacterBody2D\n'
                'class_name PlayerController\n'
                '\n'
                'signal jumped(height)\n'
                '\n'
                'func _ready():\n'
                '    pass\n'
                '\n'
                'func _physics_process(delta):\n'
                '    velocity.x = delta * 100.0\n',
                encoding="utf-8"
            )

            manager.editor_states[str(temp_project)] = {"is_active": True}
            client = TestClient(app)
            response = client.post(
                "/editor/open-resource",
                json={
                    "project_path": str(temp_project),
                    "path": "scripts/player_controller.gd:line10"
                }
            )
        finally:
            shutil.rmtree(temp_project, ignore_errors=True)

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["resource_path"], "res://scripts/player_controller.gd")
        self.assertEqual(payload["script_class_name"], "PlayerController")
        self.assertEqual(payload["script_class_line"], 2)
        self.assertEqual(payload["script_symbol_kind"], "func")
        self.assertEqual(payload["script_symbol_name"], "_physics_process")
        self.assertEqual(payload["script_symbol_signature"], "_physics_process(delta)")
        self.assertEqual(payload["script_symbol_line"], 9)
        self.assertIn("类: PlayerController", payload["message"])
        self.assertIn("函数: _physics_process(delta)", payload["message"])

        queue = manager.get_queue(str(temp_project))
        self.assertEqual(queue[0]["script_class_name"], "PlayerController")
        self.assertEqual(queue[0]["script_symbol_kind"], "func")
        self.assertEqual(queue[0]["script_symbol_signature"], "_physics_process(delta)")

    def test_open_resource_gdscript_signal_line_reports_signal_context(self):
        temp_project = project_root / "tests" / ".tmp_api_open_resource_script_signal"
        shutil.rmtree(temp_project, ignore_errors=True)
        try:
            scripts_dir = temp_project / "scripts"
            scripts_dir.mkdir(parents=True, exist_ok=True)
            (scripts_dir / "player_controller.gd").write_text(
                'extends CharacterBody2D\n'
                'class_name PlayerController\n'
                '\n'
                'signal jumped(height)\n'
                '\n'
                'func _ready():\n'
                '    pass\n',
                encoding="utf-8"
            )

            manager.editor_states[str(temp_project)] = {"is_active": True}
            client = TestClient(app)
            response = client.post(
                "/editor/open-resource",
                json={
                    "project_path": str(temp_project),
                    "path": "scripts/player_controller.gd:line4"
                }
            )
        finally:
            shutil.rmtree(temp_project, ignore_errors=True)

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["script_class_name"], "PlayerController")
        self.assertEqual(payload["script_class_line"], 2)
        self.assertEqual(payload["script_symbol_kind"], "signal")
        self.assertEqual(payload["script_symbol_name"], "jumped")
        self.assertEqual(payload["script_symbol_signature"], "jumped(height)")
        self.assertEqual(payload["script_symbol_line"], 4)
        self.assertIn("信号: jumped(height)", payload["message"])

        queue = manager.get_queue(str(temp_project))
        self.assertEqual(queue[0]["script_symbol_kind"], "signal")
        self.assertEqual(queue[0]["script_symbol_signature"], "jumped(height)")

    def test_open_resource_import_path_remaps_to_source_asset(self):
        temp_project = project_root / "tests" / ".tmp_api_open_resource_import"
        shutil.rmtree(temp_project, ignore_errors=True)
        try:
            assets_dir = temp_project / "assets"
            assets_dir.mkdir(parents=True, exist_ok=True)
            (assets_dir / "hero_icon.png").write_text("png", encoding="utf-8")
            (assets_dir / "hero_icon.png.import").write_text(
                '[remap]\n'
                'importer="texture"\n'
                '\n'
                '[deps]\n'
                'source_file="res://assets/hero_icon.png"\n',
                encoding="utf-8"
            )

            manager.editor_states[str(temp_project)] = {"is_active": True}
            client = TestClient(app)
            response = client.post(
                "/editor/open-resource",
                json={
                    "project_path": str(temp_project),
                    "path": "assets/hero_icon.png.import"
                }
            )
        finally:
            shutil.rmtree(temp_project, ignore_errors=True)

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["path"], "assets/hero_icon.png.import")
        self.assertEqual(payload["opened_path"], "assets/hero_icon.png")
        self.assertEqual(payload["resource_path"], "res://assets/hero_icon.png")
        self.assertTrue(payload["remapped_from_import"])
        self.assertIn("hero_icon.png.import -> assets/hero_icon.png", payload["message"])

        queue = manager.get_queue(str(temp_project))
        self.assertEqual(queue[0]["path"], "res://assets/hero_icon.png")
        self.assertEqual(queue[0]["line"], -1)

    def test_open_resource_accepts_res_scheme_paths(self):
        temp_project = project_root / "tests" / ".tmp_api_open_resource_res_scheme"
        shutil.rmtree(temp_project, ignore_errors=True)
        try:
            scripts_dir = temp_project / "scripts"
            scripts_dir.mkdir(parents=True, exist_ok=True)
            (scripts_dir / "player_controller.gd").write_text(
                'extends CharacterBody2D\n'
                'class_name PlayerController\n'
                '\n'
                'func _ready():\n'
                '    pass\n',
                encoding="utf-8"
            )

            manager.editor_states[str(temp_project)] = {"is_active": True}
            client = TestClient(app)
            response = client.post(
                "/editor/open-resource",
                json={
                    "project_path": str(temp_project),
                    "path": "res://scripts/player_controller.gd:line4"
                }
            )
        finally:
            shutil.rmtree(temp_project, ignore_errors=True)

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["path"], "scripts/player_controller.gd")
        self.assertEqual(payload["resource_path"], "res://scripts/player_controller.gd")
        self.assertEqual(payload["line"], 4)
        self.assertEqual(payload["script_class_line"], 2)
        self.assertEqual(payload["script_symbol_line"], 4)

        queue = manager.get_queue(str(temp_project))
        self.assertEqual(queue[0]["path"], "res://scripts/player_controller.gd")
        self.assertEqual(queue[0]["line"], 4)

    def test_open_resource_requires_active_editor(self):
        temp_project = project_root / "tests" / ".tmp_api_open_resource_offline"
        shutil.rmtree(temp_project, ignore_errors=True)
        try:
            scenes_dir = temp_project / "scenes"
            scenes_dir.mkdir(parents=True, exist_ok=True)
            (scenes_dir / "demo_scene.tscn").write_text(
                '[gd_scene load_steps=1 format=3 uid="uid://demo_scene_uid"]\n'
                '\n'
                '[node name="demo_scene" type="Node2D"]\n',
                encoding="utf-8"
            )

            client = TestClient(app)
            response = client.post(
                "/editor/open-resource",
                json={
                    "project_path": str(temp_project),
                    "path": "scenes/demo_scene.tscn"
                }
            )
        finally:
            shutil.rmtree(temp_project, ignore_errors=True)

        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["detail"], "Editor is offline")

    def test_plugin_event_is_visible_in_health(self):
        temp_project = project_root / "tests" / ".tmp_api_plugin_event"
        shutil.rmtree(temp_project, ignore_errors=True)
        temp_project.mkdir(parents=True, exist_ok=True)
        try:
            manager.editor_states[str(temp_project)] = {"is_active": True}
            client = TestClient(app)
            event_response = client.post(
                "/plugin/event",
                json={
                    "project_path": str(temp_project),
                    "event": {
                        "kind": "open_resource",
                        "status": "success",
                        "message": "Godot 已打开脚本 res://scripts/player.gd:12",
                        "path": "res://scripts/player.gd",
                        "line": 12,
                    }
                }
            )
            health_response = client.get("/health", params={"project_path": str(temp_project)})
        finally:
            shutil.rmtree(temp_project, ignore_errors=True)

        self.assertEqual(event_response.status_code, 200)
        self.assertEqual(health_response.status_code, 200)

        event_payload = event_response.json()["event"]
        health_payload = health_response.json()
        self.assertEqual(event_payload["event_id"], 1)
        self.assertEqual(event_payload["status"], "success")
        self.assertEqual(event_payload["path"], "res://scripts/player.gd")
        self.assertEqual(event_payload["line"], 12)
        self.assertEqual(health_payload["last_editor_event"]["event_id"], 1)
        self.assertEqual(
            health_payload["last_editor_event"]["message"],
            "Godot 已打开脚本 res://scripts/player.gd:12"
        )

    def test_poll_can_record_editor_events_without_plugin_event_endpoint(self):
        temp_project = project_root / "tests" / ".tmp_api_poll_editor_event"
        shutil.rmtree(temp_project, ignore_errors=True)
        temp_project.mkdir(parents=True, exist_ok=True)
        try:
            client = TestClient(app)
            poll_response = client.post(
                "/plugin/poll",
                json={
                    "project_path": str(temp_project),
                    "state": {
                        "is_active": True,
                        "project_path": str(temp_project),
                        "events": [
                            {
                                "kind": "execute_script",
                                "status": "success",
                                "message": "Godot 内部脚本执行完成",
                            }
                        ]
                    }
                }
            )
            health_response = client.get("/health", params={"project_path": str(temp_project)})
        finally:
            shutil.rmtree(temp_project, ignore_errors=True)

        self.assertEqual(poll_response.status_code, 200)
        self.assertEqual(health_response.status_code, 200)
        payload = health_response.json()
        self.assertEqual(payload["last_editor_event"]["event_id"], 1)
        self.assertEqual(payload["last_editor_event"]["kind"], "execute_script")
        self.assertEqual(payload["last_editor_event"]["message"], "Godot 内部脚本执行完成")

    def test_health_returns_compact_editor_state(self):
        temp_project = project_root / "tests" / ".tmp_api_health_editor_state"
        shutil.rmtree(temp_project, ignore_errors=True)
        temp_project.mkdir(parents=True, exist_ok=True)
        try:
            manager.editor_states[str(temp_project)] = {
                "is_active": True,
                "project_path": str(temp_project),
                "current_scene": "res://scenes/main_scene.tscn",
                "selected_nodes": ["weapon_slot"],
                "selected_node_paths": ["player/weapon_slot"],
                "selected_node_count": 1,
                "selected_node_details": [
                    {
                        "name": "weapon_slot",
                        "path": "player/weapon_slot",
                        "type": "Node2D",
                        "script_path": "res://scripts/weapon_slot.gd",
                    }
                ],
                "current_script_path": "res://scripts/player_controller.gd",
                "current_script_line": 42,
                "current_script_column": 5,
                "inspector_object_type": "Resource",
                "inspector_resource_path": "res://assets/ui/main_theme.tres",
                "inspector_resource_type": "Theme",
                "screenshot": "BASE64-DATA"
            }
            client = TestClient(app)
            response = client.get("/health", params={"project_path": str(temp_project)})
        finally:
            shutil.rmtree(temp_project, ignore_errors=True)

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertIn("editor_state", payload)
        self.assertEqual(payload["editor_state"]["current_scene"], "res://scenes/main_scene.tscn")
        self.assertEqual(payload["editor_state"]["selected_node_paths"], ["player/weapon_slot"])
        self.assertEqual(payload["editor_state"]["current_script_line"], 42)
        self.assertEqual(payload["editor_state"]["inspector_resource_path"], "res://assets/ui/main_theme.tres")
        self.assertNotIn("screenshot", payload["editor_state"])

    def test_health_returns_godot_runtime_source(self):
        with patch("api_server.main.manager.get_router", return_value=FakeRuntimeRouter()):
            client = TestClient(app)
            response = client.get("/health", params={"project_path": "default"})

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["godot_runtime"]["available"])
        self.assertEqual(payload["godot_runtime"]["executable"], "C:/Godot/godot4.exe")
        self.assertEqual(payload["godot_runtime"]["source"], "env")
        self.assertEqual(payload["godot_runtime"]["source_label"], "GODOT")

    def test_poll_enriches_editor_state_with_current_script_context(self):
        temp_project = project_root / "tests" / ".tmp_api_poll_script_context"
        shutil.rmtree(temp_project, ignore_errors=True)
        try:
            scripts_dir = temp_project / "scripts"
            scripts_dir.mkdir(parents=True, exist_ok=True)
            (scripts_dir / "player_controller.gd").write_text(
                'extends CharacterBody2D\n'
                'class_name PlayerController\n'
                '\n'
                'signal jumped(height)\n'
                '\n'
                'func _ready():\n'
                '    pass\n'
                '\n'
                'func _physics_process(delta):\n'
                '    velocity.x = delta * 100.0\n',
                encoding="utf-8"
            )

            client = TestClient(app)
            poll_response = client.post(
                "/plugin/poll",
                json={
                    "project_path": str(temp_project),
                    "state": {
                        "is_active": True,
                        "project_path": str(temp_project),
                        "current_script_path": "res://scripts/player_controller.gd",
                        "current_script_line": 10,
                    }
                }
            )
            health_response = client.get("/health", params={"project_path": str(temp_project)})
        finally:
            shutil.rmtree(temp_project, ignore_errors=True)

        self.assertEqual(poll_response.status_code, 200)
        self.assertEqual(health_response.status_code, 200)
        payload = health_response.json()
        self.assertEqual(payload["editor_state"]["current_script_class_name"], "PlayerController")
        self.assertEqual(payload["editor_state"]["current_script_symbol_kind"], "func")
        self.assertEqual(payload["editor_state"]["current_script_symbol_name"], "_physics_process")
        self.assertEqual(payload["editor_state"]["current_script_symbol_signature"], "_physics_process(delta)")
        self.assertEqual(payload["editor_state"]["current_script_symbol_line"], 9)


if __name__ == "__main__":
    unittest.main()

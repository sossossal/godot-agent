from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

import pytest

from agent_system.models import Artifact, Task, TaskStatus, ToolResult
from bridge import mcp_server


def _task_with_status(status: TaskStatus, message: str, artifacts=None) -> Task:
    task = Task(prompt="demo", status=status)
    task.artifacts.extend(artifacts or [])
    prefix = "SUCCESS" if status == TaskStatus.SUCCESS else "ERROR"
    task.add_log(f"{prefix}: {message}")
    return task


@contextmanager
def _workspace_image(name: str, content: bytes):
    path = Path("tests/.tmp_mcp_server") / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    try:
        yield path
    finally:
        path.unlink(missing_ok=True)
        if path.parent.exists() and not any(path.parent.iterdir()):
            path.parent.rmdir()


@pytest.mark.asyncio
async def test_handle_call_tool_returns_error_while_router_initializing(monkeypatch):
    monkeypatch.setattr(mcp_server, "router", None)

    result = await mcp_server.handle_call_tool("godot_status", {})

    assert result.isError is True
    assert "初始化中" in result.content[0].text


@pytest.mark.asyncio
async def test_godot_make_failed_task_sets_is_error(monkeypatch):
    failed_task = _task_with_status(TaskStatus.FAILED, "执行失败")
    fake_router = SimpleNamespace(execute=lambda prompt, confirm=True: failed_task)
    monkeypatch.setattr(mcp_server, "router", fake_router)

    result = await mcp_server.handle_call_tool("godot_make", {"prompt": "坏指令"})

    assert result.isError is True
    assert result.structuredContent["status"] == "failed"
    assert "执行失败" in result.content[0].text


@pytest.mark.asyncio
async def test_godot_make_uses_image_mime_from_artifact_extension(monkeypatch):
    with _workspace_image("capture.jpg", b"fake-jpeg") as screenshot_path:
        task = _task_with_status(
            TaskStatus.SUCCESS,
            "截图完成",
            artifacts=[Artifact(name="capture", path=str(screenshot_path), type="screenshot")],
        )
        fake_router = SimpleNamespace(execute=lambda prompt, confirm=True: task)
        monkeypatch.setattr(mcp_server, "router", fake_router)

        result = await mcp_server.handle_call_tool("godot_make", {"prompt": "截图一下"})
        image = next(item for item in result.content if getattr(item, "type", None) == "image")

        assert result.isError is False
        assert image.mimeType == "image/jpeg"


@pytest.mark.asyncio
async def test_godot_capture_uses_quick_capture_skill(monkeypatch):
    with _workspace_image("feedback.png", b"fake-png") as screenshot_path:
        calls = []

        class FakeSkill:
            def execute(self, task, params):
                calls.append((task.prompt, params, dict(task.context)))
                return ToolResult(
                    success=True,
                    message="已生成截图",
                    artifacts=[Artifact(name="feedback", path=str(screenshot_path), type="screenshot")],
                )

        fake_router = SimpleNamespace(godot_cli=object(), index_service=object())
        monkeypatch.setattr(mcp_server, "router", fake_router)
        monkeypatch.setattr(mcp_server.SkillRegistry, "get_skill", lambda *args, **kwargs: FakeSkill())

        result = await mcp_server.handle_call_tool(
            "godot_capture",
            {"scene_path": "res://sandbox_main.tscn"},
        )

        assert result.isError is False
        assert calls == [
            (
                "godot_capture",
                {"scene_path": "res://sandbox_main.tscn"},
                {"scene_path": "res://sandbox_main.tscn"},
            )
        ]
        assert any(getattr(item, "type", None) == "image" for item in result.content)


@pytest.mark.asyncio
async def test_godot_status_returns_structured_summary(monkeypatch):
    fake_router = SimpleNamespace(
        blueprint_manager=SimpleNamespace(get_context_summary=lambda: "项目摘要"),
        project_path="D:/project",
        generated_root="agent_modules",
    )
    monkeypatch.setattr(mcp_server, "router", fake_router)

    result = await mcp_server.handle_call_tool("godot_status", {})

    assert result.isError is False
    assert result.structuredContent == {
        "summary": "项目摘要",
        "project_path": "D:/project",
        "generated_root": "agent_modules",
    }


@pytest.mark.asyncio
async def test_godot_production_validate_returns_structured_gate(monkeypatch):
    fake_router = SimpleNamespace(project_path=str(Path.cwd()))
    monkeypatch.setattr(mcp_server, "router", fake_router)

    result = await mcp_server.handle_call_tool(
        "godot_production_validate",
        {
            "scenario_id": "vertical_slice_2d",
            "evidence": {"contract": True, "tests": True, "docs": True, "quality_dashboard": True},
            "changed_paths": ["scenes/Main.tscn", "scripts/player_controller.gd", "README.md"],
            "mode": "strict",
        },
    )

    assert result.isError is False
    assert result.structuredContent["schema_version"] == "1.0"
    assert result.structuredContent["scenario_id"] == "vertical_slice_2d"
    assert result.structuredContent["exit_code"] == 0


@pytest.mark.asyncio
async def test_godot_agent_compat_returns_structured_matrix(monkeypatch):
    fake_router = SimpleNamespace(project_path=str(Path.cwd()))
    monkeypatch.setattr(mcp_server, "router", fake_router)

    result = await mcp_server.handle_call_tool("godot_agent_compat", {"providers": ["codex"]})

    assert result.isError is False
    assert result.structuredContent["schema_version"] == "1.0"
    assert result.structuredContent["providers"][0]["provider_id"] == "codex"
    assert result.structuredContent["passed"] is True


@pytest.mark.asyncio
async def test_godot_create_game_plan_returns_structured_plan(monkeypatch, tmp_path):
    fake_router = SimpleNamespace(project_path=str(tmp_path))
    monkeypatch.setattr(mcp_server, "router", fake_router)

    result = await mcp_server.handle_call_tool(
        "godot_create_game_plan",
        {"title": "Demo Runner", "features": ["jump"], "target_platforms": ["web"]},
    )

    assert result.isError is False
    assert result.structuredContent["schema_version"] == "1.0"
    assert result.structuredContent["game_id"] == "demo_runner"
    assert result.structuredContent["manifest_path"] == "data_tables/game_creation/game_creation_profile.json"
    assert "scenes/Main.tscn" in result.structuredContent["artifact_paths"]


@pytest.mark.asyncio
async def test_godot_apply_game_plan_writes_scaffold(monkeypatch, tmp_path):
    fake_router = SimpleNamespace(project_path=str(tmp_path))
    monkeypatch.setattr(mcp_server, "router", fake_router)

    result = await mcp_server.handle_call_tool(
        "godot_apply_game_plan",
        {"title": "Demo Runner", "target_platforms": ["desktop"], "overwrite": True},
    )

    assert result.isError is False
    assert result.structuredContent["ready"] is True
    assert (tmp_path / "scenes" / "Main.tscn").exists()
    assert (tmp_path / "scripts" / "player_controller.gd").exists()
    assert (tmp_path / "data_tables" / "game_creation" / "game_creation_profile.json").exists()


@pytest.mark.asyncio
async def test_godot_audit_game_scene_graph_reports_generated_scaffold(monkeypatch, tmp_path):
    fake_router = SimpleNamespace(project_path=str(tmp_path))
    monkeypatch.setattr(mcp_server, "router", fake_router)
    await mcp_server.handle_call_tool(
        "godot_apply_game_plan",
        {"title": "Demo Runner", "target_platforms": ["desktop"], "overwrite": True},
    )

    result = await mcp_server.handle_call_tool(
        "godot_audit_game_scene_graph",
        {"write_report": True},
    )

    assert result.isError is False
    assert result.structuredContent["status"] == "passed"
    assert result.structuredContent["node_count"] > 0
    assert (tmp_path / "data_tables" / "game_creation" / "scene_graph_audit.json").exists()


@pytest.mark.asyncio
async def test_godot_review_game_creation_reports_acceptance(monkeypatch, tmp_path):
    fake_router = SimpleNamespace(project_path=str(tmp_path))
    monkeypatch.setattr(mcp_server, "router", fake_router)
    await mcp_server.handle_call_tool(
        "godot_apply_game_plan",
        {"title": "Demo Runner", "target_platforms": ["desktop"], "overwrite": True},
    )

    result = await mcp_server.handle_call_tool(
        "godot_review_game_creation",
        {"write_reports": True},
    )

    assert result.isError is False
    assert result.structuredContent["status"] == "passed"
    assert result.structuredContent["ready_for_acceptance"] is True
    assert (tmp_path / "data_tables" / "game_creation" / "game_creation_review.json").exists()
    assert (tmp_path / "docs" / "game_creation_review.md").exists()


@pytest.mark.asyncio
async def test_godot_plan_game_template_migration_reports_strategy(monkeypatch, tmp_path):
    fake_router = SimpleNamespace(project_path=str(tmp_path))
    monkeypatch.setattr(mcp_server, "router", fake_router)
    await mcp_server.handle_call_tool(
        "godot_apply_game_plan",
        {"title": "Demo Runner", "template_id": "platformer_2d", "overwrite": True},
    )

    result = await mcp_server.handle_call_tool(
        "godot_plan_game_template_migration",
        {"to_template_id": "arpg", "write_report": True},
    )

    assert result.isError is False
    assert result.structuredContent["status"] == "passed"
    assert result.structuredContent["from_template_id"] == "platformer_2d"
    assert result.structuredContent["to_template_id"] == "arpg_2d"
    assert result.structuredContent["validation_plan"]
    assert (tmp_path / "data_tables" / "game_creation" / "template_migration_plan.json").exists()

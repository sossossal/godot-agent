"""
Godot Agent MCP Server
职责: 将 Godot Agent 的核心能力暴露给 Gemini CLI (基于 MCP 协议)
"""

import asyncio
import os
import base64
import mimetypes
import sys
from pathlib import Path
from typing import List, Dict, Any, Optional

# 将项目根目录添加到 sys.path
sys.path.append(str(Path(__file__).parent.parent))

from mcp.server.stdio import stdio_server
from mcp.server import Server
from mcp.types import CallToolResult, Tool, TextContent, ImageContent

from agent_system.router import GodotAgentRouter
from agent_system.models import Task, TaskStatus
from agent_system.skills.registry import SkillRegistry
from agent_system.tools.agent_compatibility import build_agent_compatibility_matrix
from agent_system.tools.production_scale import build_production_readiness
from bridge.tool_contracts import list_tool_definitions

server = Server("godot-agent")
router: Optional[GodotAgentRouter] = None
ERROR_STATUSES = {
    TaskStatus.FAILED,
    TaskStatus.ROLLED_BACK,
    TaskStatus.CANCELLED,
    TaskStatus.BLOCKED,
}


def _text_content(text: str) -> TextContent:
    return TextContent(type="text", text=text)


def _error_result(message: str, structured: Optional[Dict[str, Any]] = None) -> CallToolResult:
    return CallToolResult(
        content=[_text_content(message)],
        structuredContent=structured,
        isError=True,
    )


def _artifact_text(artifact) -> str:
    return f"产物已生成: {artifact.name} ({artifact.path})"


def _image_content(path: str) -> Optional[ImageContent]:
    if not path or not os.path.exists(path):
        return None
    mime_type, _ = mimetypes.guess_type(path)
    if not mime_type or not mime_type.startswith("image/"):
        mime_type = "image/png"
    with open(path, "rb") as handle:
        data = base64.b64encode(handle.read()).decode("utf-8")
    return ImageContent(type="image", data=data, mimeType=mime_type)


def _task_result(task: Task) -> CallToolResult:
    lines = [
        f"### 任务执行结果: {task.status.value.upper()}",
        f"- **摘要**: {task.get_message()}",
    ]
    if task.logs:
        lines.append("")
        lines.append("#### 执行日志:")
        lines.extend(f"- {log}" for log in task.logs[-5:])

    content = [_text_content("\n".join(lines))]
    for artifact in task.artifacts:
        image = _image_content(artifact.path) if artifact.type == "screenshot" else None
        content.append(image or _text_content(_artifact_text(artifact)))

    return CallToolResult(
        content=content,
        structuredContent=task.to_dict(),
        isError=task.status in ERROR_STATUSES,
    )


def _status_result(current_router: GodotAgentRouter) -> CallToolResult:
    summary = current_router.blueprint_manager.get_context_summary()
    return CallToolResult(
        content=[_text_content(summary)],
        structuredContent={
            "summary": summary,
            "project_path": current_router.project_path,
            "generated_root": current_router.generated_root,
        },
        isError=False,
    )


def _structured_json_result(title: str, payload: Dict[str, Any], *, is_error: bool = False) -> CallToolResult:
    return CallToolResult(
        content=[_text_content(f"### {title}\n```json\n{_json_dumps(payload)}\n```")],
        structuredContent=payload,
        isError=is_error,
    )


def _json_dumps(payload: Dict[str, Any]) -> str:
    import json

    return json.dumps(payload, indent=2, ensure_ascii=False)


def _capture_task(current_router: GodotAgentRouter, scene_path: Optional[str]) -> Task:
    skill = SkillRegistry.get_skill(
        "quick_capture_scene",
        current_router.godot_cli,
        current_router.index_service,
    )
    task = Task(prompt="godot_capture", role="tester")
    if scene_path:
        task.context["scene_path"] = scene_path
    if skill is None:
        task.status = TaskStatus.FAILED
        task.add_log("ERROR: 未找到 quick_capture_scene 技能")
        return task

    result = skill.execute(task, {"scene_path": scene_path} if scene_path else {})
    task.artifacts.extend(result.artifacts)
    task.status = TaskStatus.SUCCESS if result.success else TaskStatus.FAILED
    log_prefix = "SUCCESS" if result.success else "ERROR"
    task.add_log(f"{log_prefix}: {result.message}")
    return task


def execute_mcp_tool(current_router: GodotAgentRouter, name: str, arguments: Optional[Dict[str, Any]]) -> CallToolResult:
    arguments = arguments or {}

    if name == "godot_make":
        prompt = arguments.get("prompt")
        if not isinstance(prompt, str) or not prompt.strip():
            return _error_result("`prompt` 不能为空。")
        task = current_router.execute(prompt, confirm=True)
        return _task_result(task)

    if name == "godot_status":
        return _status_result(current_router)

    if name == "godot_capture":
        scene = arguments.get("scene_path")
        task = _capture_task(current_router, scene if isinstance(scene, str) and scene else None)
        return _task_result(task)

    if name == "godot_production_validate":
        project_path = arguments.get("project_path") or getattr(current_router, "project_path", None) or Path.cwd()
        evidence = arguments.get("evidence") if isinstance(arguments.get("evidence"), dict) else {}
        changed_paths = arguments.get("changed_paths") if isinstance(arguments.get("changed_paths"), list) else []
        payload = build_production_readiness(
            project_path,
            runtime_root=Path.cwd(),
            scenario_id=str(arguments.get("scenario_id") or "vertical_slice_2d"),
            evidence=evidence,
            changed_paths=[str(path) for path in changed_paths],
            mode=str(arguments.get("mode") or "strict"),
            fail_on_warnings=bool(arguments.get("fail_on_warnings")),
        )
        return _structured_json_result("P5 Production Readiness", payload, is_error=bool(payload.get("should_block")))

    if name == "godot_agent_compat":
        project_path = arguments.get("project_path") or getattr(current_router, "project_path", None) or Path.cwd()
        raw_providers = arguments.get("providers")
        providers = [str(item) for item in raw_providers] if isinstance(raw_providers, list) else None
        payload = build_agent_compatibility_matrix(project_path, runtime_root=Path.cwd(), providers=providers)
        return _structured_json_result("P6 Agent Compatibility", payload, is_error=not bool(payload.get("passed")))

    return _error_result(f"Unknown tool: {name}")

@server.list_tools()
async def handle_list_tools() -> List[Tool]:
    """列出可用的 Godot 开发工具"""
    return [Tool(**definition) for definition in list_tool_definitions()]

@server.call_tool()
async def handle_call_tool(name: str, arguments: Optional[Dict[str, Any]]) -> CallToolResult:
    """处理工具调用"""
    current_router = router
    if current_router is None:
        return _error_result("### 错误: Godot Agent 正在后台初始化中, 请稍候再试 (约需 5-10 秒)。")
    return execute_mcp_tool(current_router, name, arguments)

async def main():
    async with stdio_server() as (read_stream, write_stream):
        # 延迟初始化 router, 允许服务器先启动并响应 initialize 请求
        async def delayed_init():
            global router
            await asyncio.sleep(0.1) # 给 MCP 启动留一点喘息空间
            sys.stderr.write("[MCP] 正在后台初始化 GodotAgentRouter...\n")
            router = GodotAgentRouter()
            sys.stderr.write("[MCP] GodotAgentRouter 已就绪。\n")

        # 启动后台初始化任务
        init_task = asyncio.create_task(delayed_init())
        
        await server.run(
            read_stream,
            write_stream,
            server.create_initialization_options()
        )

if __name__ == "__main__":
    asyncio.run(main())

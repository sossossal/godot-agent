"""Shared tool contracts for stdio MCP, remote bridge, and API onboarding."""

from __future__ import annotations

from typing import Any, Dict, List


MCP_TOOL_DEFINITIONS: List[Dict[str, Any]] = [
    {
        "name": "godot_make",
        "description": "执行自然语言 Godot 开发指令。支持创建场景、编写脚本、添加 UI、配置物理、注入特效等。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "prompt": {"type": "string", "description": "开发指令, 如 '创建一个横版玩家并添加移动脚本'"}
            },
            "required": ["prompt"],
        },
    },
    {
        "name": "godot_status",
        "description": "获取当前项目的蓝图状态摘要, 包括已实现功能、场景拓扑和全局设置。",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "godot_capture",
        "description": "触发 Godot 编辑器实时截图并返回视觉反馈。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "scene_path": {"type": "string", "description": "可选: 指定截图场景路径"}
            },
        },
    },
    {
        "name": "godot_production_validate",
        "description": "执行 P5 生产规模验证, 检查 required paths、质量面板、迁移兼容和治理证据。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "scenario_id": {
                    "type": "string",
                    "description": "生产验证场景: vertical_slice_2d / content_pipeline / release_candidate",
                    "default": "vertical_slice_2d",
                },
                "evidence": {
                    "type": "object",
                    "description": "治理 evidence map, 例如 {\"contract\": true, \"tests\": true}",
                },
                "changed_paths": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "本次变更涉及的受管路径列表",
                },
                "mode": {
                    "type": "string",
                    "enum": ["strict", "advisory"],
                    "default": "strict",
                },
                "fail_on_warnings": {"type": "boolean", "default": False},
                "project_path": {"type": "string", "description": "可选: 覆盖当前 router project_path"},
            },
        },
    },
    {
        "name": "godot_agent_compat",
        "description": "执行 P6 多 Agent/API 兼容矩阵, 检查 contracts、skills、MCP、API、governance 和 file tree surface。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "providers": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "可选 provider 列表, 如 codex / openai_api / gemini",
                },
                "project_path": {"type": "string", "description": "可选: 覆盖当前 router project_path"},
            },
        },
    },
]


def list_tool_definitions() -> List[Dict[str, Any]]:
    return [
        {
            "name": str(item["name"]),
            "description": str(item["description"]),
            "inputSchema": dict(item["inputSchema"]),
        }
        for item in MCP_TOOL_DEFINITIONS
    ]

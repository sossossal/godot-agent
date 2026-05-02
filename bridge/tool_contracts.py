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
    {
        "name": "godot_create_game_plan",
        "description": "生成从零制作可玩 2D 游戏原型的结构化计划, 不写入文件。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "title": {"type": "string", "default": "Platformer Prototype"},
                "genre": {"type": "string", "default": "platformer_2d"},
                "template_id": {"type": "string", "default": "platformer_2d"},
                "features": {"type": "array", "items": {"type": "string"}},
                "target_platforms": {"type": "array", "items": {"type": "string"}},
                "notes": {"type": "string"},
                "project_path": {"type": "string", "description": "可选: 覆盖当前 router project_path"},
            },
        },
    },
    {
        "name": "godot_apply_game_plan",
        "description": "按 2D 游戏原型计划写入 Godot 项目脚手架文件, 包括场景、脚本、输入映射和 manifest。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "title": {"type": "string", "default": "Platformer Prototype"},
                "genre": {"type": "string", "default": "platformer_2d"},
                "template_id": {"type": "string", "default": "platformer_2d"},
                "features": {"type": "array", "items": {"type": "string"}},
                "target_platforms": {"type": "array", "items": {"type": "string"}},
                "notes": {"type": "string"},
                "overwrite": {"type": "boolean", "default": False},
                "project_path": {"type": "string", "description": "可选: 覆盖当前 router project_path"},
            },
        },
    },
    {
        "name": "godot_audit_game_scene_graph",
        "description": "根据 game_creation_profile 审计 Godot 场景树、节点、脚本、信号与触发响应是否符合计划。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "manifest_path": {
                    "type": "string",
                    "default": "data_tables/game_creation/game_creation_profile.json",
                },
                "write_report": {"type": "boolean", "default": False},
                "project_path": {"type": "string", "description": "可选: 覆盖当前 router project_path"},
            },
        },
    },
    {
        "name": "godot_review_game_creation",
        "description": "生成游戏创建验收摘要, 汇总 acceptance checklist、模块状态、场景树审计和阻断项。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "manifest_path": {
                    "type": "string",
                    "default": "data_tables/game_creation/game_creation_profile.json",
                },
                "write_reports": {"type": "boolean", "default": False},
                "project_path": {"type": "string", "description": "可选: 覆盖当前 router project_path"},
            },
        },
    },
    {
        "name": "godot_plan_game_template_migration",
        "description": "规划 P19 游戏创建模板迁移策略, 输出兼容检查、文件操作、数据表迁移、验证计划和 rollback 计划；不直接改写项目。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "manifest_path": {
                    "type": "string",
                    "default": "data_tables/game_creation/game_creation_profile.json",
                },
                "from_template_id": {"type": "string", "description": "源模板；为空时从 manifest 读取"},
                "to_template_id": {"type": "string", "default": "platformer_2d"},
                "write_report": {"type": "boolean", "default": False},
                "report_path": {
                    "type": "string",
                    "default": "data_tables/game_creation/template_migration_plan.json",
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

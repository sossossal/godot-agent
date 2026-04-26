"""
Godot Agent API 服务器 (视觉桥梁版)
职责: 维护多客户端状态隔离、中转异步命令、分发实时截图
"""

from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from pydantic import BaseModel
from typing import Optional, Dict, List, Any
import asyncio
import time
import uvicorn
from pathlib import Path
import re
import sys
import os
import json
import shutil
from datetime import datetime, timezone
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, Response

# 添加项目路径
sys.path.append(str(Path(__file__).parent.parent))

from agent_system.router import GodotAgentRouter
from agent_system.models import Task, TaskStatus, TaskStep
from agent_system.contracts import (
    build_contract_catalog,
    build_feature_lifecycle_event,
    build_feature_review_entry,
    normalize_release_live_dispatch_audit,
    normalize_release_live_dispatch_preflight,
    normalize_release_artifact_manifest,
    build_task_feature_context,
    normalize_feature_external_links,
    normalize_release_live_event_stream,
    normalize_review_history,
    normalize_feature_lifecycle_events,
    record_skill_result_on_task,
)
from agent_system.migrations import MigrationRunner
from agent_system.skills.registry import SkillRegistry
from agent_system.skills.resource.art_asset_skill import ART_ASSET_SCHEMAS, ART_ASSET_TYPE_LABELS
from agent_system.skills.resource.data_table_skill import TABLE_SCHEMAS, TABLE_TYPE_LABELS
from agent_system.skills.resource.liveops_skill import LIVEOPS_SCHEMAS, LIVEOPS_TYPE_LABELS
from agent_system.skills.resource.presentation_skill import PRESENTATION_SCHEMAS, PRESENTATION_TYPE_LABELS
from agent_system.tools.agent_compatibility import build_agent_compatibility_matrix, list_agent_provider_profiles
from agent_system.tools.governance import build_change_admission, build_governance_enforcement, build_governance_policy
from agent_system.tools.performance_analysis import DEFAULT_PERFORMANCE_BASELINE_DIR
from agent_system.tools.asset_review import (
    DEFAULT_ASSET_REVIEW_MANIFEST_PATH,
    apply_asset_review_decision,
    build_asset_review_workflow,
)
from agent_system.tools.build_run_matrix import (
    DEFAULT_PLATFORM_DELIVERY_MANIFEST_PATH,
    build_build_run_matrix,
)
from agent_system.tools.outsource_delivery import (
    DEFAULT_OUTSOURCE_MANIFEST_PATH,
    DEFAULT_OUTSOURCE_PACKAGE_ROOT,
    build_outsource_delivery_gate,
)
from agent_system.tools.performance_analysis import build_performance_report
from agent_system.tools.production_scale import build_production_readiness, list_production_scenarios
from agent_system.tools.quality_dashboard import build_quality_dashboard
from agent_system.tools.release_candidate import build_release_candidate_checklist
from agent_system.tools.release_capability_registry import (
    DEFAULT_RELEASE_CAPABILITY_REGISTRY_PATH,
    build_release_capability_registry,
    build_release_capability_registry_report,
)
from agent_system.tools.release_capability_policy import (
    build_release_capability_policy,
    build_release_capability_policy_report,
)
from agent_system.tools.release_delivery_readiness import (
    DEFAULT_RELEASE_DELIVERY_ARTIFACT_DIR,
    build_release_delivery_readiness,
    build_release_delivery_readiness_report,
)
from agent_system.tools.release_promotion import (
    build_deployment_rehearsal_report,
    build_release_promotion_evidence_report,
    build_release_promotion_plan,
    build_release_review_bundle_report,
    build_rollback_rehearsal_report,
)
from agent_system.tools.release_promotion_history import (
    DEFAULT_RELEASE_PROMOTION_HISTORY_PATH,
    build_release_promotion_history,
    build_release_promotion_history_report,
    record_release_promotion_event,
)
from agent_system.tools.release_execution import (
    DEFAULT_RELEASE_CHANNELS_PATH,
    DEFAULT_RELEASE_EXECUTION_STATUS_PATH,
    build_release_execution_report,
    build_release_execution_status,
    rollback_release_execution,
    run_release_execution,
)
from agent_system.tools.release_request_auth import authorize_release_request
from tools.export_release_live_ci_artifacts import (  # noqa: E402
    _build_release_live_ci_summary_markdown as build_release_live_ci_summary_markdown,
)
from tools.dispatch_release_live_gates import (  # noqa: E402
    DEFAULT_TOKEN_ENV_NAMES as DEFAULT_RELEASE_LIVE_DISPATCH_TOKEN_ENV_NAMES,
    DEFAULT_WORKFLOW as DEFAULT_RELEASE_LIVE_DISPATCH_WORKFLOW,
    build_release_live_dispatch_preflight,
    dispatch_release_live_gates_request,
    load_release_live_dispatch_audit,
    write_release_live_dispatch_audit,
)
from agent_system.tools.scene_ownership import (
    DEFAULT_SCENE_OWNERSHIP_BOARD_PATH,
    apply_scene_ownership_update,
    build_scene_ownership_board,
)
from agent_system.tools.telemetry_analysis import (
    DEFAULT_TELEMETRY_CATALOG_PATH,
    build_crash_cluster_report,
    build_crash_regression_dashboard_report,
    build_liveops_impact_report,
    build_retention_funnel_dashboard_report,
    build_retention_funnel_trend_report,
)
from agent_system.tools.template_registry import DEFAULT_GENRE_TEMPLATE_ID, GenreTemplateRegistry
from bridge.tool_contracts import list_tool_definitions


app = FastAPI(title="Godot Agent API (Visual Bridge)", version="1.3.5")


def _get_env_str(name: str, default: str) -> str:
    value = os.environ.get(name, "").strip()
    return value or default


def _get_env_int(name: str, default: int) -> int:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


API_BIND_HOST = _get_env_str("GODOT_AGENT_API_BIND_HOST", "0.0.0.0")
API_HOST = _get_env_str("GODOT_AGENT_API_HOST", "127.0.0.1")
API_PORT = _get_env_int("GODOT_AGENT_API_PORT", 8000)

def _build_release_write_request_auth(
    request: Request,
    *,
    project_root: str | Path,
    actor_id: str = "",
    action: str,
    target_channel: str,
    target_environment: str,
) -> Dict[str, Any]:
    return authorize_release_request(
        project_root,
        runtime_root=REPO_ROOT,
        client_host=str((request.client.host if request.client else "") or "").strip(),
        authorization_header=str(request.headers.get("authorization") or "").strip(),
        custom_token_header=str(request.headers.get("x-godot-agent-release-token") or "").strip(),
        actor_id=actor_id,
        action=action,
        target_channel=target_channel,
        target_environment=target_environment,
    )


def _normalize_project_key(project_path: Optional[str]) -> str:
    # 🆕 强力修复: 如果 project_path 为空或包含特殊字符，或者当前只有一个活跃会话，默认指向该会话
    if not project_path or project_path == "default":
        return "default"
    
    # 如果当前活跃的项目列表中只有一个，且请求路径看起来像是一个乱码路径，则强制归一化
    normalized = Path(project_path).expanduser().resolve().as_posix().rstrip("/")
    return f"{normalized}/"


def _candidate_project_keys(project_path: Optional[str]) -> List[str]:
    candidates: List[str] = []
    if project_path is None:
        return candidates

    raw_value = str(project_path)
    candidates.append(raw_value)

    stripped_value = raw_value.rstrip("/\\")
    if stripped_value and stripped_value not in candidates:
        candidates.append(stripped_value)

    try:
        resolved_path = Path(raw_value).expanduser().resolve()
    except Exception:
        resolved_path = None

    if resolved_path is not None:
        for variant in (
            str(resolved_path),
            resolved_path.as_posix(),
            f"{resolved_path.as_posix().rstrip('/')}/",
        ):
            if variant and variant not in candidates:
                candidates.append(variant)

    normalized_value = _normalize_project_key(raw_value)
    if normalized_value not in candidates:
        candidates.append(normalized_value)
    normalized_stripped = normalized_value.rstrip("/")
    if normalized_stripped and normalized_stripped not in candidates:
        candidates.append(normalized_stripped)

    return candidates


def _lookup_project_mapping(mapping: Dict[str, Any], project_path: Optional[str], default: Any = None) -> Any:
    fallback = default
    for candidate in _candidate_project_keys(project_path):
        if candidate in mapping:
            value = mapping[candidate]
            if isinstance(value, dict) and value.get("is_active"):
                return value
            if fallback is default:
                fallback = value
    return fallback


def _resolve_mcp_server_script() -> Path:
    return (REPO_ROOT / "bridge" / "mcp_server.py").resolve()


def _resolve_remote_mcp_server_script() -> Path:
    return (REPO_ROOT / "bridge" / "remote_mcp_server.py").resolve()


def _resolve_repo_skill_dir(skill_name: Optional[str] = None) -> Path:
    resolved_skill_name = skill_name or CODEX_SKILL_NAME
    return (REPO_ROOT / ".codex" / "skills" / resolved_skill_name).resolve()


def _resolve_codex_skill_root() -> Path:
    return (Path.home() / ".codex" / "skills").resolve()


def _resolve_global_skill_dir(skill_name: Optional[str] = None) -> Path:
    resolved_skill_name = skill_name or CODEX_SKILL_NAME
    return (_resolve_codex_skill_root() / resolved_skill_name).resolve()


def _build_file_hash_map(directory_path: Path) -> Dict[str, str]:
    result: Dict[str, str] = {}
    if not directory_path.exists():
        return result

    root = directory_path.resolve()
    for file_path in sorted(path for path in root.rglob("*") if path.is_file()):
        relative_path = file_path.relative_to(root).as_posix()
        result[relative_path] = str(file_path.stat().st_size) + ":" + str(int(file_path.stat().st_mtime_ns))
    return result


def _directories_match(source_dir: Path, target_dir: Path) -> bool:
    if not target_dir.exists():
        return False
    return _build_file_hash_map(source_dir) == _build_file_hash_map(target_dir)


def _sync_directory(source_dir: Path, target_dir: Path) -> bool:
    changed = not _directories_match(source_dir, target_dir)
    if not changed:
        return False

    target_dir.parent.mkdir(parents=True, exist_ok=True)
    if target_dir.exists():
        shutil.rmtree(target_dir)
    shutil.copytree(source_dir, target_dir)
    return True


def _build_codex_mcp_add_command() -> str:
    python_executable = str(Path(sys.executable).resolve())
    server_script = str(_resolve_mcp_server_script())
    return f'codex mcp add {MCP_SERVER_NAME} -- "{python_executable}" "{server_script}"'


def _build_codex_mcp_config() -> str:
    python_executable = str(Path(sys.executable).resolve()).replace("\\", "\\\\")
    server_script = str(_resolve_mcp_server_script()).replace("\\", "\\\\")
    return (
        f"[mcp_servers.{MCP_SERVER_NAME}]\n"
        f"command = '{python_executable}'\n"
        f"args = ['{server_script}']\n"
    )


def _build_gemini_mcp_config() -> str:
    config = {
        "mcpServers": {
            MCP_SERVER_NAME: {
                "command": str(Path(sys.executable).resolve()),
                "args": [str(_resolve_mcp_server_script())],
            }
        }
    }
    return json.dumps(config, ensure_ascii=False, indent=2)


def _build_remote_mcp_manifest_payload(project_path: str) -> Dict[str, Any]:
    remote_script = _resolve_remote_mcp_server_script()
    return {
        "schema_version": "1.0",
        "project_path": project_path,
        "server_name": f"{MCP_SERVER_NAME}-remote",
        "transport": "http",
        "host": "127.0.0.1",
        "port": 8765,
        "remote_server_path": str(remote_script),
        "python_executable": str(Path(sys.executable).resolve()),
        "launch_command": f'python "{remote_script}"',
        "health_url": "http://127.0.0.1:8765/health",
        "manifest_url": "http://127.0.0.1:8765/mcp/manifest",
        "tool_call_pattern": "http://127.0.0.1:8765/tools/{tool_name}",
        "tools": list_tool_definitions(),
        "security_notes": [
            "默认只建议绑定 127.0.0.1。",
            "如果要暴露到局域网或云端网关，请先加鉴权、限流和项目路径白名单。",
        ],
    }


def _build_mcp_onboarding_payload(project_path: str) -> Dict[str, Any]:
    repo_skill_dir = _resolve_repo_skill_dir()
    global_skill_dir = _resolve_global_skill_dir()
    gemini_settings_path = (REPO_ROOT / ".gemini" / "settings.json").resolve()
    ide_guide_path = (REPO_ROOT / "docs" / "IDE集成指南.md").resolve()
    vscode_agent_path = (REPO_ROOT / "ide_integration" / "vscode_agent.py").resolve()
    godot_controller_path = (REPO_ROOT / "ide_integration" / "godot_controller.py").resolve()

    return {
        "project_path": project_path,
        "repo_root": str(REPO_ROOT),
        "server_name": MCP_SERVER_NAME,
        "mcp_server_path": str(_resolve_mcp_server_script()),
        "python_executable": str(Path(sys.executable).resolve()),
        "codex": {
            "cli_available": bool(shutil.which("codex")),
            "mcp_add_command": _build_codex_mcp_add_command(),
            "config_toml_snippet": _build_codex_mcp_config(),
            "skill_name": CODEX_SKILL_NAME,
            "skill_repo_path": str(repo_skill_dir),
            "skill_global_path": str(global_skill_dir),
            "skill_install_command": ".\\tools\\install_codex_skill.ps1",
            "skill_preview_command": ".\\tools\\install_codex_skill.ps1 -Preview",
            "skill_installed": _directories_match(repo_skill_dir, global_skill_dir),
        },
        "gemini": {
            "settings_path": str(gemini_settings_path),
            "settings_exists": gemini_settings_path.exists(),
            "settings_json": _build_gemini_mcp_config(),
        },
        "ide": {
            "guide_path": str(ide_guide_path),
            "guide_exists": ide_guide_path.exists(),
            "guide_url": f"/artifact-file?project_path={project_path}&path={Path('docs/IDE集成指南.md').as_posix()}",
            "vscode_agent_command": f'python "{vscode_agent_path}" "生成 2D 玩家移动脚本"',
            "godot_controller_command": f'python "{godot_controller_path}" status',
        },
        "remote_mcp": _build_remote_mcp_manifest_payload(project_path),
    }


# 核心状态管理器
class SessionManager:
    def __init__(self):
        self.routers: Dict[str, GodotAgentRouter] = {}
        self.editor_states: Dict[str, Dict] = {} 
        self.command_queues: Dict[str, List] = {}
        self.last_screenshots: Dict[str, str] = {} # project_path -> base64_image
        self.last_editor_events: Dict[str, Dict[str, Any]] = {}
        self.editor_event_counters: Dict[str, int] = {}
        self.last_editor_launches: Dict[str, Dict[str, Any]] = {}
        self.command_counters: Dict[str, int] = {}
        self.command_acks: Dict[str, Dict[str, Dict[str, Any]]] = {} # project_path -> {command_id -> event}
        
        self.active_websockets: Dict[str, List[WebSocket]] = {} # project_path -> [WebSocket]
        self.portal_websockets: Dict[str, List[WebSocket]] = {} # project_path -> [WebSocket]
        self.commands: Dict[str, Dict[str, Dict[str, Any]]] = {} # project_path -> {command_id -> state}

    def get_router(self, path: str) -> GodotAgentRouter:
        path = _normalize_project_key(path)
        if path not in self.routers:
            self.routers[path] = GodotAgentRouter(godot_project_path=path if path != "default" else None)
        return self.routers[path]

    def get_queue(self, path: str) -> List:
        path = _normalize_project_key(path)
        if path not in self.command_queues: self.command_queues[path] = []
        return self.command_queues[path]

    def next_command_id(self, path: str) -> str:
        path = _normalize_project_key(path)
        count = self.command_counters.get(path, 0) + 1
        self.command_counters[path] = count
        return f"cmd_{int(time.time())}_{count}"

    def register_command(self, path: str, command: Dict[str, Any]):
        path = _normalize_project_key(path)
        cmd_id = command.get("command_id")
        if not cmd_id:
            return
        if path not in self.commands:
            self.commands[path] = {}
        self.commands[path][cmd_id] = {
            "command_id": cmd_id,
            "status": "queued",
            "payload": command,
            "created_at": time.time(),
            "updated_at": time.time()
        }

    async def dispatch_commands(self, path: str, commands: List[Dict[str, Any]]):
        if not commands:
            return
            
        # 🆕 强力广播: 忽略 path，向所有已连接的插件发送指令
        all_websockets = []
        for ws_list in self.active_websockets.values():
            all_websockets.extend(ws_list)
            
        if not all_websockets:
            print("⚠️ No active WebSockets to broadcast to")
            return

        dead_sockets = []
        for ws in all_websockets:
            try:
                await ws.send_json({"commands": commands})
                print(f"✅ Dispatched {len(commands)} commands to a plugin")
            except Exception:
                dead_sockets.append(ws)
                
        # 清理失效连接
        for path_key, ws_list in self.active_websockets.items():
            for dead in dead_sockets:
                if dead in ws_list: ws_list.remove(dead)

    def connect(self, path: str, ws: WebSocket):
        path = _normalize_project_key(path)
        if path not in self.active_websockets:
            self.active_websockets[path] = []
        self.active_websockets[path].append(ws)

    def disconnect(self, path: str, ws: WebSocket):
        path = _normalize_project_key(path)
        if path in self.active_websockets and ws in self.active_websockets[path]:
            self.active_websockets[path].remove(ws)

    def connect_portal(self, path: str, ws: WebSocket):
        path = _normalize_project_key(path)
        if path not in self.portal_websockets:
            self.portal_websockets[path] = []
        self.portal_websockets[path].append(ws)

    def disconnect_portal(self, path: str, ws: WebSocket):
        path = _normalize_project_key(path)
        if path in self.portal_websockets and ws in self.portal_websockets[path]:
            self.portal_websockets[path].remove(ws)

    async def _broadcast_to_mapping(self, mapping: Dict[str, List[WebSocket]], path: str, payload: Dict[str, Any]):
        normalized_path = _normalize_project_key(path)
        target_paths = {normalized_path}
        if normalized_path != "default":
            target_paths.add("default")

        dead_sockets: List[tuple[str, WebSocket]] = []
        for target_path in target_paths:
            for ws in mapping.get(target_path, []):
                try:
                    await ws.send_json(payload)
                except Exception:
                    dead_sockets.append((target_path, ws))

        for target_path, ws in dead_sockets:
            if mapping is self.portal_websockets:
                self.disconnect_portal(target_path, ws)
            else:
                self.disconnect(target_path, ws)

    async def broadcast_task_update(self, path: str, task: Dict[str, Any]):
        normalized_path = _normalize_project_key(path)
        await self._broadcast_to_mapping(self.active_websockets, normalized_path, {"task_update": task})
        await self._broadcast_to_mapping(
            self.portal_websockets,
            normalized_path,
            {"type": "task_update", "task_update": task},
        )

    async def broadcast_health_update(self, path: str):
        normalized_path = _normalize_project_key(path)
        payload = _build_health_payload(normalized_path)
        payload["type"] = "health_update"
        await self._broadcast_to_mapping(self.portal_websockets, normalized_path, payload)

    async def broadcast_editor_event(self, path: str, event: Dict[str, Any]):
        normalized_path = _normalize_project_key(path)
        await self._broadcast_to_mapping(
            self.portal_websockets,
            normalized_path,
            {"type": "editor_event", "editor_event": event},
        )

    def record_editor_event(self, path: str, event: Dict[str, Any]) -> Dict[str, Any]:
        path = _normalize_project_key(path)
        event_id = self.editor_event_counters.get(path, 0) + 1
        self.editor_event_counters[path] = event_id
        stored_event = dict(event)
        stored_event["event_id"] = event_id
        stored_event["project_path"] = path
        stored_event["timestamp"] = datetime.now(timezone.utc).isoformat()
        self.last_editor_events[path] = stored_event
        
        # 如果事件包含 command_id，记录到 acks 中
        cmd_id = event.get("command_id")
        if cmd_id:
            if path not in self.command_acks:
                self.command_acks[path] = {}
            self.command_acks[path][str(cmd_id)] = stored_event
            
            # 更新 commands 状态并尝试推进任务
            if path in self.commands and str(cmd_id) in self.commands[path]:
                cmd_record = self.commands[path][str(cmd_id)]
                status = event.get("status", "success")
                cmd_record["status"] = "acked" if status == "success" else "failed"
                cmd_record["updated_at"] = time.time()
                cmd_record["result"] = stored_event
                
                # 尝试推进关联的任务
                task_id = cmd_record.get("payload", {}).get("task_id")
                if task_id:
                    self.resume_task(path, task_id, str(cmd_id), stored_event)
            
        return stored_event

    def resume_task(self, path: str, task_id: str, command_id: str, event: Dict[str, Any]):
        """推进任务状态机"""
        router = self.get_router(path)
        get_task = getattr(router, "get_task", None)
        task = get_task(task_id) if callable(get_task) else None
        if not task:
            return None

        cmd_record = self.commands.get(path, {}).get(command_id, {})
        target_step_id = cmd_record.get("payload", {}).get("step_id")

        waiting_steps = [step for step in task.steps if step.status == TaskStatus.WAITING_ACK]
        if target_step_id:
            step = next((item for item in waiting_steps if item.step_id == target_step_id), None)
        else:
            step = waiting_steps[0] if waiting_steps else None

        if not step:
            return None

        status = event.get("status", "success")
        if status == "success":
            step.status = TaskStatus.SUCCESS
            step.end_time = time.time()
            task.add_log(f"收到回执，步骤 {step.name} 推进成功")
        else:
            step.status = TaskStatus.FAILED
            step.error = event.get("message", "编辑器执行失败")
            task.status = TaskStatus.FAILED
            task.add_log(f"收到失败回执: {step.error}")

        return router.execute_plan(task)

    def get_command_ack(self, path: str, command_id: str) -> Optional[Dict[str, Any]]:
        path = _normalize_project_key(path)
        return self.command_acks.get(path, {}).get(str(command_id))

    def get_last_editor_event(self, path: str) -> Optional[Dict[str, Any]]:
        path = _normalize_project_key(path)
        return _lookup_project_mapping(self.last_editor_events, path)

    def launch_editor(self, path: str, scene_path: Optional[str] = None) -> Dict[str, Any]:
        path = _normalize_project_key(path)
        state = _lookup_project_mapping(self.editor_states, path, {})
        if state.get("is_active"):
            launch_info = {
                "status": "already_online",
                "message": "Godot 编辑器已在线",
                "project_path": path,
                "scene_path": scene_path,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
            self.last_editor_launches[path] = launch_info
            return launch_info

        router = self.get_router(path)
        result = router.godot_cli.launch_editor(scene_path=scene_path)
        if not result.success:
            raise HTTPException(status_code=503, detail=result.error or result.message)

        launch_info = {
            "status": "launching",
            "message": result.message,
            "project_path": path,
            "scene_path": scene_path,
            "pid": (result.data or {}).get("pid"),
            "command": (result.data or {}).get("command"),
            "executable_source": (result.data or {}).get("executable_source"),
            "executable_source_label": (result.data or {}).get("executable_source_label"),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        self.last_editor_launches[path] = launch_info
        return launch_info

manager = SessionManager()

# 静态文件定位 (基于当前文件位置)
BASE_DIR = Path(__file__).parent
STATIC_DIR = BASE_DIR / "static"
REPO_ROOT = BASE_DIR.parent.resolve()
STATIC_DIR.mkdir(exist_ok=True)
CODEX_SKILL_NAME = "closure-first-engineer"
MCP_SERVER_NAME = "godot"
SECTION_ATTR_RE = re.compile(r'(\w+)="([^"]*)"')
IMPORT_SOURCE_RE = re.compile(r'source_file="([^"]+)"')
NODE_INSTANCE_RE = re.compile(r'instance=ExtResource\("([^"]+)"\)')
SCRIPT_CLASS_RE = re.compile(r'^\s*class_name\s+([A-Za-z_]\w*)')
SCRIPT_SIGNAL_RE = re.compile(r'^\s*signal\s+([A-Za-z_]\w*)(?:\(([^)]*)\))?')
SCRIPT_FUNC_RE = re.compile(r'^\s*(?:static\s+)?func\s+([A-Za-z_]\w*)\s*\(([^)]*)\)\s*(?:->\s*([^:]+))?:?')
EDITOR_OPERATION_SCHEMA_VERSION = "1.1"
EDITOR_OPERATION_ALLOWED = {
    "get_scene_tree",
    "select_node",
    "set_node_property",
    "create_node",
    "delete_node",
    "save_scene",
    "save_scene_as",
    "reload_scene",
    "duplicate_node",
    "reparent_node",
    "rename_node",
    "move_node_order",
    "batch_set_properties",
    "batch_create_nodes",
    "attach_script",
    "detach_script",
    "instantiate_scene",
}

app.mount("/portal", StaticFiles(directory=str(STATIC_DIR)), name="portal")


def _resolve_project_root(project_path: str) -> Path:
    normalized = _normalize_project_key(project_path)
    return REPO_ROOT if normalized == "default" else Path(normalized).resolve()


def _resolve_under(base_dir: Path, relative_path: str) -> Path:
    candidate = (base_dir / Path(relative_path.replace("\\", "/"))).resolve()
    try:
        candidate.relative_to(base_dir.resolve())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Path escapes allowed root") from exc
    return candidate


def _parse_source_reference(path_value: str, line: Optional[int]) -> tuple[str, Optional[int]]:
    normalized = path_value.replace("\\", "/")
    if "::" in normalized:
        normalized = normalized.split("::", 1)[0]

    match = re.match(r"^(.*):line(\d+)$", normalized)
    if match:
        normalized = match.group(1)
        if line is None:
            line = int(match.group(2))

    if normalized.startswith("res://"):
        normalized = normalized[len("res://"):]

    return normalized, line


def _to_godot_resource_path(project_root: Path, resolved_path: Path) -> str:
    relative_path = resolved_path.relative_to(project_root.resolve()).as_posix()
    return f"res://{relative_path}"


def _to_project_relative_path(project_root: Path, resolved_path: Path) -> str:
    return resolved_path.relative_to(project_root.resolve()).as_posix()


def _read_text_lines(path: Path) -> Optional[List[str]]:
    try:
        return path.read_text(encoding="utf-8").splitlines()
    except UnicodeDecodeError:
        return None


def _display_project_path(project_root: Path, resolved_path: Path) -> str:
    try:
        return _to_project_relative_path(project_root, resolved_path)
    except Exception:
        return str(resolved_path.resolve())


def _resolve_res_path(project_root: Path, res_path: str) -> Optional[Path]:
    if not res_path.startswith("res://"):
        return None
    return _resolve_under(project_root, res_path[len("res://"):])


def _resolve_import_source_path(project_root: Path, resolved_path: Path) -> Optional[Path]:
    if resolved_path.suffix.lower() != ".import":
        return None

    lines = _read_text_lines(resolved_path)
    if not lines:
        return None

    for raw_line in lines:
        match = IMPORT_SOURCE_RE.search(raw_line)
        if not match:
            continue
        candidate = _resolve_res_path(project_root, match.group(1))
        if candidate and candidate.exists() and candidate.is_file():
            return candidate
    return None


def _normalize_scene_path(raw_path: Optional[str]) -> str:
    if not raw_path or raw_path == ".":
        return "."

    parts: List[str] = []
    for segment in raw_path.split("/"):
        segment = segment.strip()
        if not segment or segment == ".":
            continue
        if segment == "..":
            if parts:
                parts.pop()
            continue
        parts.append(segment)

    return "/".join(parts) if parts else "."


def _resolve_scene_node_path(parent_path: Optional[str], node_name: str) -> str:
    if parent_path is None:
        return "."

    normalized_parent = _normalize_scene_path(parent_path)
    if normalized_parent == ".":
        return node_name
    return f"{normalized_parent}/{node_name}"


def _build_scene_node_sections(lines: List[str]) -> List[Dict[str, Any]]:
    ext_resource_map = _build_ext_resource_map(lines)
    sections: List[Dict[str, Any]] = []
    for index, raw_line in enumerate(lines, start=1):
        stripped = raw_line.strip()
        if not stripped.startswith("[node ") or not stripped.endswith("]"):
            continue

        attrs = {match.group(1): match.group(2) for match in SECTION_ATTR_RE.finditer(stripped)}
        node_name = attrs.get("name")
        if not node_name:
            continue

        scene_node_path = _resolve_scene_node_path(attrs.get("parent"), node_name)
        owner_path = None
        if "owner" in attrs:
            owner_path = _normalize_scene_path(attrs.get("owner"))

        instance_ref = None
        instance_match = NODE_INSTANCE_RE.search(stripped)
        if instance_match:
            instance_ref = instance_match.group(1)

        sections.append({
            "line": index,
            "scene_node_name": node_name,
            "scene_node_path": scene_node_path,
            "scene_owner_path": owner_path,
            "scene_instance_ref": instance_ref,
        })

    instance_roots: Dict[str, str] = {}
    for section in sections:
        instance_ref = section.get("scene_instance_ref")
        if not instance_ref:
            continue
        ext_resource = ext_resource_map.get(instance_ref)
        if not ext_resource:
            continue
        instance_path = ext_resource.get("path")
        if not instance_path:
            continue
        section["scene_instance_source"] = instance_path
        section["scene_instance_root_path"] = section["scene_node_path"]
        instance_roots[section["scene_node_path"]] = instance_path

    for section in sections:
        if section.get("scene_instance_source"):
            continue
        inherited_instance_root, inherited_instance_source = _find_scene_instance_context(
            section["scene_node_path"],
            instance_roots,
        )
        if inherited_instance_source:
            section["scene_instance_root_path"] = inherited_instance_root
            section["scene_instance_source"] = inherited_instance_source
    return sections


def _build_ext_resource_map(lines: List[str]) -> Dict[str, Dict[str, str]]:
    ext_resources: Dict[str, Dict[str, str]] = {}
    for raw_line in lines:
        stripped = raw_line.strip()
        if not stripped.startswith("[ext_resource ") or not stripped.endswith("]"):
            continue
        attrs = {match.group(1): match.group(2) for match in SECTION_ATTR_RE.finditer(stripped)}
        ext_id = attrs.get("id")
        if ext_id:
            ext_resources[ext_id] = attrs
    return ext_resources


def _find_scene_instance_context(scene_node_path: str, instance_roots: Dict[str, str]) -> tuple[Optional[str], Optional[str]]:
    normalized_path = _normalize_scene_path(scene_node_path)
    candidates: List[str] = []
    if normalized_path == ".":
        candidates.append(".")
    else:
        parts = normalized_path.split("/")
        for length in range(len(parts), 0, -1):
            candidates.append("/".join(parts[:length]))
        candidates.append(".")

    for candidate in candidates:
        if candidate in instance_roots:
            return candidate, instance_roots[candidate]
    return None, None


def _format_scene_target_message(
    scene_node_name: Optional[str],
    scene_node_path: Optional[str],
    scene_instance_source: Optional[str] = None,
) -> str:
    if not scene_node_name:
        return ""
    parts: List[str] = []
    if scene_node_path and scene_node_path not in (".", scene_node_name):
        parts.append(f"节点: {scene_node_name}")
        parts.append(f"路径: {scene_node_path}")
    elif scene_node_path == ".":
        parts.append(f"节点: {scene_node_name}")
        parts.append("路径: .")
    else:
        parts.append(f"节点: {scene_node_name}")

    if scene_instance_source:
        parts.append(f"实例源: {scene_instance_source.replace('res://', '')}")
    return "，".join(parts)


def _extract_scene_open_hint(resolved_path: Path, line: Optional[int]) -> Dict[str, Any]:
    if line is None or resolved_path.suffix.lower() != ".tscn":
        return {}

    lines = _read_text_lines(resolved_path)
    if not lines:
        return {}

    focus_line = max(1, min(line, len(lines)))
    current_hint: Dict[str, Any] = {}
    for section in _build_scene_node_sections(lines):
        if section["line"] > focus_line:
            break
        current_hint = {
            "scene_node_name": section["scene_node_name"],
            "scene_node_path": section["scene_node_path"],
            "scene_node_line": section["line"],
        }
        if section.get("scene_owner_path"):
            current_hint["scene_owner_path"] = section["scene_owner_path"]
        if section.get("scene_instance_root_path"):
            current_hint["scene_instance_root_path"] = section["scene_instance_root_path"]
        if section.get("scene_instance_source"):
            current_hint["scene_instance_source"] = section["scene_instance_source"]
    return current_hint


def _build_script_symbol_display(kind: str, name: str, args: Optional[str] = None, return_type: Optional[str] = None) -> str:
    if kind == "func":
        signature = f"{name}({args or ''})"
        if return_type:
            signature += f" -> {return_type.strip()}"
        return signature
    if kind == "signal":
        return f"{name}({args or ''})"
    return name


def _format_script_target_message(
    script_class_name: Optional[str],
    script_symbol_kind: Optional[str],
    script_symbol_display: Optional[str],
) -> str:
    parts: List[str] = []
    if script_class_name:
        parts.append(f"类: {script_class_name}")
    if script_symbol_kind and script_symbol_display:
        label_map = {"func": "函数", "signal": "信号"}
        parts.append(f"{label_map.get(script_symbol_kind, '符号')}: {script_symbol_display}")
    return "，".join(parts)


def _extract_gdscript_open_hint(resolved_path: Path, line: Optional[int]) -> Dict[str, Any]:
    if resolved_path.suffix.lower() != ".gd":
        return {}

    lines = _read_text_lines(resolved_path)
    if not lines:
        return {}

    focus_line = max(1, min(line or 1, len(lines)))
    script_class_name: Optional[str] = None
    script_class_line: Optional[int] = None
    current_symbol: Optional[Dict[str, Any]] = None

    for index, raw_line in enumerate(lines, start=1):
        class_match = SCRIPT_CLASS_RE.match(raw_line)
        if class_match and not script_class_name:
            script_class_name = class_match.group(1)
            script_class_line = index

        signal_match = SCRIPT_SIGNAL_RE.match(raw_line)
        if signal_match and index <= focus_line:
            current_symbol = {
                "script_symbol_kind": "signal",
                "script_symbol_name": signal_match.group(1),
                "script_symbol_signature": _build_script_symbol_display(
                    "signal",
                    signal_match.group(1),
                    signal_match.group(2),
                ),
                "script_symbol_line": index,
            }

        func_match = SCRIPT_FUNC_RE.match(raw_line)
        if func_match and index <= focus_line:
            current_symbol = {
                "script_symbol_kind": "func",
                "script_symbol_name": func_match.group(1),
                "script_symbol_signature": _build_script_symbol_display(
                    "func",
                    func_match.group(1),
                    func_match.group(2),
                    func_match.group(3),
                ),
                "script_symbol_line": index,
            }

    hint: Dict[str, Any] = {}
    if script_class_name:
        hint["script_class_name"] = script_class_name
        if script_class_line is not None:
            hint["script_class_line"] = script_class_line
    if current_symbol:
        hint.update(current_symbol)
    return hint


def _extract_source_preview_context(resolved_path: Path, line: int) -> Dict[str, Any]:
    context: Dict[str, Any] = {}

    scene_hint = _extract_scene_open_hint(resolved_path, line)
    if scene_hint:
        context.update(scene_hint)
        context["preview_context_label"] = _format_scene_target_message(
            scene_hint.get("scene_node_name"),
            scene_hint.get("scene_node_path"),
            scene_hint.get("scene_instance_source"),
        )
        return context

    script_hint = _extract_gdscript_open_hint(resolved_path, line)
    if script_hint:
        context.update(script_hint)
        context["preview_context_label"] = _format_script_target_message(
            script_hint.get("script_class_name"),
            script_hint.get("script_symbol_kind"),
            script_hint.get("script_symbol_signature"),
        )
        return context

    return context


def _enrich_editor_state(project_path: str, state: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    normalized_project_path = _normalize_project_key(project_path)
    enriched = dict(state or {})
    enriched["project_path"] = normalized_project_path
    current_scene = enriched.get("current_scene")
    if current_scene in {"", "None"}:
        enriched.pop("current_scene", None)

    try:
        project_root = _resolve_project_root(normalized_project_path)
    except Exception:
        return enriched

    if not project_root.exists():
        return enriched

    current_script_path = enriched.get("current_script_path")
    current_script_line = enriched.get("current_script_line")
    if (
        isinstance(current_script_path, str)
        and current_script_path.startswith("res://")
        and (
            not enriched.get("current_script_class_name")
            or not enriched.get("current_script_symbol_name")
        )
    ):
        resolved_script = _resolve_res_path(project_root, current_script_path)
        if resolved_script and resolved_script.exists() and resolved_script.is_file():
            script_hint = _extract_gdscript_open_hint(resolved_script, current_script_line)
            if script_hint:
                enriched.update({
                    f"current_{key}": value
                    for key, value in script_hint.items()
                })

    return enriched


def _get_editor_state_for_project(project_path: str) -> Dict[str, Any]:
    normalized_project_path = _normalize_project_key(project_path)
    state = _lookup_project_mapping(manager.editor_states, normalized_project_path, {"is_active": False})
    enriched_state = _enrich_editor_state(normalized_project_path, state)
    if enriched_state != state:
        manager.editor_states[normalized_project_path] = enriched_state
    elif normalized_project_path not in manager.editor_states and state is not None:
        manager.editor_states[normalized_project_path] = enriched_state
    return enriched_state


def _build_open_resource_command(project_root: Path, normalized_path: str, resolved_path: Path, line: Optional[int], column: int) -> Dict[str, Any]:
    effective_path = resolved_path
    effective_line = line
    remapped_from_import = False

    import_source_path = _resolve_import_source_path(project_root, resolved_path)
    if import_source_path:
        effective_path = import_source_path
        effective_line = None
        remapped_from_import = True

    opened_path = _to_project_relative_path(project_root, effective_path)
    resource_path = _to_godot_resource_path(project_root, effective_path)
    command = {
        "type": "open_resource",
        "path": resource_path,
        "line": effective_line if effective_line is not None else -1,
        "column": max(0, column),
    }
    command.update(_extract_scene_open_hint(effective_path, effective_line))
    command.update(_extract_gdscript_open_hint(effective_path, effective_line))

    response: Dict[str, Any] = {
        "ok": True,
        "path": normalized_path,
        "opened_path": opened_path,
        "resource_path": resource_path,
        "line": effective_line,
        "column": max(0, column),
        "remapped_from_import": remapped_from_import,
        "message": f"已发送到 Godot: {opened_path}{f':{effective_line}' if effective_line else ''}",
    }
    if remapped_from_import:
        response["message"] = f"已发送到 Godot: {normalized_path} -> {opened_path}"
    if command.get("scene_node_name"):
        response["scene_node_name"] = command["scene_node_name"]
        response["scene_node_path"] = command["scene_node_path"]
        if command.get("scene_node_line") is not None:
            response["scene_node_line"] = command["scene_node_line"]
        if command.get("scene_owner_path"):
            response["scene_owner_path"] = command["scene_owner_path"]
        if command.get("scene_instance_root_path"):
            response["scene_instance_root_path"] = command["scene_instance_root_path"]
        if command.get("scene_instance_source"):
            response["scene_instance_source"] = command["scene_instance_source"]
        response["message"] += f" ({_format_scene_target_message(command['scene_node_name'], command['scene_node_path'], command.get('scene_instance_source'))})"
    if command.get("script_class_name"):
        response["script_class_name"] = command["script_class_name"]
        if command.get("script_class_line") is not None:
            response["script_class_line"] = command["script_class_line"]
    if command.get("script_symbol_kind"):
        response["script_symbol_kind"] = command["script_symbol_kind"]
        response["script_symbol_name"] = command["script_symbol_name"]
        response["script_symbol_signature"] = command["script_symbol_signature"]
        if command.get("script_symbol_line") is not None:
            response["script_symbol_line"] = command["script_symbol_line"]
    script_message = _format_script_target_message(
        command.get("script_class_name"),
        command.get("script_symbol_kind"),
        command.get("script_symbol_signature"),
    )
    if script_message:
        response["message"] += f" ({script_message})"

    return {"command": command, "response": response}


def _build_editor_operation_command(req: "EditorOperationRequest", operation: str, command_id: str) -> Dict[str, Any]:
    max_depth = max(0, min(int(req.max_depth), 16))
    max_nodes = max(1, min(int(req.max_nodes), 1000))
    requested_at = datetime.now(timezone.utc).isoformat()
    audit = {
        "schema_version": EDITOR_OPERATION_SCHEMA_VERSION,
        "audit_id": f"editor-op-{command_id}",
        "source": "api",
        "operation": operation,
        "command_id": command_id,
        "project_path": req.project_path,
        "requested_at": requested_at,
        "rollback_anchor": {
            "kind": "editor_operation",
            "command_id": command_id,
            "operation": operation,
        },
    }
    command: Dict[str, Any] = {
        "type": "editor_operation",
        "schema_version": EDITOR_OPERATION_SCHEMA_VERSION,
        "operation": operation,
        "command_id": command_id,
        "node_path": req.node_path or "",
        "node_name": req.node_name or "",
        "parent_path": req.parent_path or ".",
        "target_parent_path": req.target_parent_path or "",
        "node_type": req.node_type or "Node2D",
        "property_name": req.property_name or "",
        "value": req.value,
        "value_type": req.value_type or "",
        "new_name": req.new_name or "",
        "scene_path": req.scene_path or "",
        "script_path": req.script_path or "",
        "index": req.index,
        "items": list(req.items or []),
        "preserve_global_transform": bool(req.preserve_global_transform),
        "max_depth": max_depth,
        "max_nodes": max_nodes,
        "select_created": bool(req.select_created),
        "audit": audit,
    }
    return command


def _validate_editor_operation_request(req: "EditorOperationRequest", operation: str) -> None:
    if operation in {"set_node_property"} and not str(req.property_name or "").strip():
        raise HTTPException(status_code=400, detail="Missing property_name")
    if operation in {"save_scene_as", "instantiate_scene"} and not str(req.scene_path or "").strip():
        raise HTTPException(status_code=400, detail="Missing scene_path")
    if operation == "attach_script" and not str(req.script_path or "").strip():
        raise HTTPException(status_code=400, detail="Missing script_path")
    if operation == "rename_node" and not str(req.new_name or "").strip():
        raise HTTPException(status_code=400, detail="Missing new_name")
    if operation == "move_node_order" and req.index is None:
        raise HTTPException(status_code=400, detail="Missing index")
    if operation in {"batch_set_properties", "batch_create_nodes"} and not req.items:
        raise HTTPException(status_code=400, detail="Missing items")


async def _queue_and_dispatch_editor_command(project_path: str, command: Dict[str, Any]) -> None:
    manager.register_command(project_path, command)
    queue = manager.get_queue(project_path)
    queue.append(command)
    if queue and manager.active_websockets.get(project_path):
        commands = list(queue)
        queue.clear()
        await manager.dispatch_commands(project_path, commands)


def _flatten_recent_artifacts(router: GodotAgentRouter, limit: int) -> List[Dict[str, Any]]:
    flattened: List[Dict[str, Any]] = []
    history = list(router.get_history(limit=max(limit, 1)))
    history.sort(key=lambda task: task.get("created_at", 0), reverse=True)

    for task in history:
        for index, artifact in enumerate(task.get("artifacts", [])):
            item = dict(artifact)
            item["artifact_index"] = index
            item["task_id"] = task.get("task_id")
            item["task_prompt"] = task.get("prompt")
            item["task_status"] = task.get("status")
            item["task_message"] = task.get("message")
            item["task_created_at"] = task.get("created_at")
            item["is_internal"] = str(item.get("path", "")).startswith("internal://")
            flattened.append(item)

    flattened.sort(
        key=lambda item: (
            item.get("task_created_at", 0),
            item.get("artifact_index", 0),
        ),
        reverse=True
    )
    return flattened[:limit]


def _resolve_artifact_path(project_path: str, artifact_path: str) -> Path:
    if not artifact_path:
        raise HTTPException(status_code=400, detail="Missing artifact path")
    if artifact_path.startswith("internal://"):
        raise HTTPException(status_code=400, detail="Internal artifact is not file-backed")

    project_root = _resolve_project_root(project_path)
    normalized = artifact_path.replace("\\", "/")

    if normalized.startswith("res://"):
        return _resolve_under(project_root, normalized[len("res://"):])
    if normalized.startswith("/portal/"):
        return _resolve_under(STATIC_DIR, normalized[len("/portal/"):])
    if normalized.startswith("portal/"):
        return _resolve_under(STATIC_DIR, normalized[len("portal/"):])

    candidate = Path(normalized)
    if candidate.is_absolute():
        resolved = candidate.resolve()
        for base_dir in (project_root.resolve(), REPO_ROOT.resolve()):
            try:
                resolved.relative_to(base_dir)
                return resolved
            except ValueError:
                continue
        raise HTTPException(status_code=400, detail="Path escapes allowed roots")

    repo_candidate = _resolve_under(REPO_ROOT, normalized)
    if repo_candidate.exists():
        return repo_candidate

    return _resolve_under(project_root, normalized)


def _compact_editor_state(state: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    source = dict(state or {})
    selected_node_details = source.get("selected_node_details") or []
    compact_state = {
        "is_active": bool(source.get("is_active")),
        "project_path": source.get("project_path"),
        "current_scene": source.get("current_scene"),
        "edited_scene_root_name": source.get("edited_scene_root_name"),
        "selected_nodes": source.get("selected_nodes", []),
        "selected_node_paths": source.get("selected_node_paths", []),
        "selected_node_count": source.get("selected_node_count", len(source.get("selected_nodes", []))),
        "selected_node_details": selected_node_details[:5],
        "current_script_path": source.get("current_script_path"),
        "current_script_line": source.get("current_script_line"),
        "current_script_column": source.get("current_script_column"),
        "current_script_class_name": source.get("current_script_class_name"),
        "current_script_symbol_kind": source.get("current_script_symbol_kind"),
        "current_script_symbol_name": source.get("current_script_symbol_name"),
        "current_script_symbol_signature": source.get("current_script_symbol_signature"),
        "current_script_symbol_line": source.get("current_script_symbol_line"),
        "inspector_resource_path": source.get("inspector_resource_path"),
        "inspector_resource_type": source.get("inspector_resource_type"),
        "inspector_object_type": source.get("inspector_object_type"),
        "inspector_node_name": source.get("inspector_node_name"),
        "inspector_node_path": source.get("inspector_node_path"),
    }
    return {key: value for key, value in compact_state.items() if value not in (None, "", [], {})}


def _build_godot_runtime_info(project_path: str) -> Dict[str, Any]:
    router = manager.get_router(project_path)
    executable = getattr(router.godot_cli, "executable", None)
    source = getattr(router.godot_cli, "executable_source", None)
    source_label = getattr(router.godot_cli, "executable_source_label", None)
    runtime_info = {
        "available": bool(executable),
        "executable": executable,
        "source": source,
        "source_label": source_label,
    }
    return {key: value for key, value in runtime_info.items() if value not in (None, "", [], {})}


def _serialize_task_for_api(task: Task) -> Dict[str, Any]:
    payload = task.to_dict()
    context = dict(payload.get("context") or {})
    editor_state = context.get("editor_state")
    if isinstance(editor_state, dict):
        context["editor_state"] = _compact_editor_state(editor_state)
    payload["context"] = context
    return payload


def _last_editor_event_id(project_path: str) -> int:
    event = manager.get_last_editor_event(project_path)
    return int(event.get("event_id", 0) or 0) if event else 0


async def _wait_for_editor_event(
    project_path: str,
    timeout: int,
    after_event_id: Optional[int] = None,
    kind: Optional[str] = None,
    command_id: Optional[str] = None,
) -> Dict[str, Any]:
    normalized_project_path = _normalize_project_key(project_path)
    deadline = time.monotonic() + max(1, timeout)
    if after_event_id is None:
        seed_event = manager.get_last_editor_event(normalized_project_path)
        baseline_event_id = int(seed_event.get("event_id", 0) or 0) if seed_event else 0
    else:
        baseline_event_id = after_event_id

    while time.monotonic() < deadline:
        # 1. 尝试通过 command_id 匹配 (强回执)
        if command_id:
            ack = manager.get_command_ack(normalized_project_path, command_id)
            if ack:
                return ack
        
        # 2. 尝试通过 kind + event_id 匹配 (兼容性兜底)
        event = manager.get_last_editor_event(normalized_project_path)
        if event:
            event_id = int(event.get("event_id", 0) or 0)
            event_command_id = event.get("command_id")
            command_matches = (
                not command_id
                or not event_command_id
                or str(event_command_id) == str(command_id)
            )
            if event_id > baseline_event_id and command_matches and (kind is None or event.get("kind") == kind):
                return event
        
        await asyncio.sleep(0.2)

    target_text = f"command_id={command_id}" if command_id else f"kind={kind}"
    raise HTTPException(status_code=504, detail=f"等待 Godot 编辑器回执超时 ({target_text})")


async def _broadcast_post_event_updates(project_path: str, stored_event: Dict[str, Any]):
    await manager.broadcast_editor_event(project_path, stored_event)
    await manager.broadcast_health_update(project_path)

    command_id = stored_event.get("command_id")
    if not command_id:
        return

    normalized_project_path = _normalize_project_key(project_path)
    cmd_record = manager.commands.get(normalized_project_path, {}).get(str(command_id), {})
    task_id = cmd_record.get("payload", {}).get("task_id")
    if not task_id:
        return

    router = manager.get_router(normalized_project_path)
    task = _safe_get_router_task(router, task_id)
    if task:
        await manager.broadcast_task_update(normalized_project_path, _serialize_task_for_api(task))


async def _wait_for_editor_online(project_path: str, timeout: int) -> Dict[str, Any]:
    deadline = time.monotonic() + max(1, timeout)
    while time.monotonic() < deadline:
        state = _get_editor_state_for_project(project_path)
        if state.get("is_active"):
            return state
        await asyncio.sleep(0.5)
    raise HTTPException(status_code=504, detail="Godot 编辑器启动后插件未在超时时间内上线")


async def _ensure_editor_state(
    project_path: str,
    auto_launch_editor: bool,
    wait_for_editor: bool,
    editor_timeout: int,
    scene_path: Optional[str] = None,
) -> tuple[Dict[str, Any], Optional[Dict[str, Any]]]:
    state = _get_editor_state_for_project(project_path)
    launch_info = None
    if state.get("is_active") or not auto_launch_editor:
        return state, launch_info

    launch_info = manager.launch_editor(project_path, scene_path=scene_path)
    if wait_for_editor:
        state = await _wait_for_editor_online(project_path, editor_timeout)
    else:
        state = _get_editor_state_for_project(project_path)
    return state, launch_info

@app.get("/")
async def read_index():
    index_file = STATIC_DIR / "index.html"
    if not index_file.exists():
        return {"error": "Frontend UI (index.html) not found in api_server/static/"}
    return FileResponse(str(index_file))

class CommandRequest(BaseModel):
    command: str
    context: Optional[Dict] = None
    project_path: str = "default"
    auto_launch_editor: bool = False
    wait_for_editor: bool = True
    editor_timeout: int = 25
    wait_for_editor_event: bool = False
    editor_event_timeout: int = 10


class EditablePlanStep(BaseModel):
    name: str
    description: str
    role: str
    depends_on: List[str] = []
    status: str = "pending"
    requires_confirmation: bool = False
    metadata: Dict[str, Any] = {}


class PlanRequest(BaseModel):
    command: str
    context: Optional[Dict] = None
    project_path: str = "default"


class ExecutePlanRequest(BaseModel):
    prompt: str
    steps: List[EditablePlanStep]
    task_id: Optional[str] = None
    context: Optional[Dict] = None
    project_path: str = "default"
    auto_launch_editor: bool = False
    wait_for_editor: bool = True
    editor_timeout: int = 25
    wait_for_editor_event: bool = False
    editor_event_timeout: int = 10


class OpenResourceRequest(BaseModel):
    path: str
    project_path: str = "default"
    line: Optional[int] = None
    column: int = 0
    auto_launch_editor: bool = False
    wait_for_editor: bool = True
    editor_timeout: int = 25
    wait_for_editor_event: bool = False
    editor_event_timeout: int = 10


class EditorOperationRequest(BaseModel):
    operation: str
    project_path: str = "default"
    node_path: Optional[str] = None
    node_name: Optional[str] = None
    target_parent_path: Optional[str] = None
    parent_path: str = "."
    node_type: str = "Node2D"
    property_name: Optional[str] = None
    value: Any = None
    value_type: Optional[str] = None
    new_name: Optional[str] = None
    scene_path: Optional[str] = None
    script_path: Optional[str] = None
    index: Optional[int] = None
    items: List[Dict[str, Any]] = []
    preserve_global_transform: bool = True
    max_depth: int = 4
    max_nodes: int = 200
    select_created: bool = True
    auto_launch_editor: bool = False
    wait_for_editor: bool = True
    editor_timeout: int = 25
    wait_for_editor_event: bool = True
    editor_event_timeout: int = 10


class LaunchEditorRequest(BaseModel):
    project_path: str = "default"
    scene_path: Optional[str] = None
    wait_for_editor: bool = True
    editor_timeout: int = 25


class PluginEventRequest(BaseModel):
    project_path: str
    event: Dict[str, Any]


class WaitEditorEventRequest(BaseModel):
    project_path: str = "default"
    after_event_id: Optional[int] = None
    kind: Optional[str] = None
    timeout: int = 10


class FeatureReviewRequest(BaseModel):
    feature_status: str
    review_note: str = ""
    reviewer: str = ""
    review_round: str = ""
    required_followups: Optional[List[str]] = None
    dependency: str = ""
    eta: str = ""
    validation_method: str = ""
    blockers: Optional[List[str]] = None
    external_links: Optional[List[Dict[str, Any]]] = None


class FeatureReviewBatchRequest(FeatureReviewRequest):
    task_ids: List[str] = []
    source_feature_status: str = "pending_acceptance"
    feature_id: str = ""
    owner: str = ""
    limit: int = 30
    offset: int = 0
    dry_run: bool = False


class DataTableManageRequest(BaseModel):
    action: str = "preview"
    table_type: str = "dialogue"
    table_path: Optional[str] = None
    content: Optional[str] = None
    rows: List[Dict[str, Any]] = []
    project_path: str = "default"


class LevelWorkflowManageRequest(BaseModel):
    action: str = "template"
    level_name: str = "level_01"
    level_type: str = "combat"
    root_type: str = "Node2D"
    scene_path: Optional[str] = None
    manifest_path: Optional[str] = None
    snapshot_path: Optional[str] = None
    compare_snapshot_path: Optional[str] = None
    template_id: Optional[str] = None
    spawn_points: List[Dict[str, Any]] = []
    interaction_points: List[Dict[str, Any]] = []
    checkpoints: List[Dict[str, Any]] = []
    navigation_zones: List[Dict[str, Any]] = []
    navigation_agents: List[Dict[str, Any]] = []
    tile_layers: List[Dict[str, Any]] = []
    trigger_zones: List[Dict[str, Any]] = []
    collision_layers: List[Dict[str, Any]] = []
    critical_path: List[str] = []
    level_bounds: Dict[str, Any] = {}
    notes: str = ""
    project_path: str = "default"


class GameplayTemplateManageRequest(BaseModel):
    action: str = "preview"
    template_id: Optional[str] = None
    game_genre: Optional[str] = None
    include_system_ids: List[str] = []
    notes: str = ""
    project_path: str = "default"


class ArtAssetManageRequest(BaseModel):
    action: str = "preview"
    asset_type: str = "texture"
    asset_id: Optional[str] = None
    source_path: Optional[str] = None
    target_path: Optional[str] = None
    manifest_path: Optional[str] = None
    source_tool: Optional[str] = None
    width: Optional[int] = None
    height: Optional[int] = None
    frame_width: Optional[int] = None
    frame_height: Optional[int] = None
    lod_count: Optional[int] = None
    texture_set: Optional[str] = None
    package_version: Optional[str] = None
    license_name: Optional[str] = None
    source_dependency_paths: List[str] = []
    target_dependency_paths: List[str] = []
    estimated_memory_mb: Optional[float] = None
    tags: List[str] = []
    notes: str = ""
    entries: List[Dict[str, Any]] = []
    project_path: str = "default"


class PresentationManageRequest(BaseModel):
    action: str = "preview"
    presentation_type: str = "animation"
    profile_id: Optional[str] = None
    manifest_path: Optional[str] = None
    target_script_path: Optional[str] = None
    target_scene_path: Optional[str] = None
    target_shader_path: Optional[str] = None
    target_material_path: Optional[str] = None
    target_node_path: str = ""
    animation_mode: Optional[str] = None
    animation_clips: List[str] = []
    state_machine_states: List[str] = []
    particle_mode: Optional[str] = None
    amount: Optional[int] = None
    lifetime_seconds: Optional[float] = None
    one_shot: bool = False
    texture_path: Optional[str] = None
    color_hex: str = "#ffffff"
    shader_mode: Optional[str] = None
    shader_params: Dict[str, Any] = {}
    audio_role: Optional[str] = None
    event_name: Optional[str] = None
    bus_name: Optional[str] = None
    audio_stream_path: Optional[str] = None
    autoplay: bool = False
    acceptance_checks: List[str] = []
    notes: str = ""
    entries: List[Dict[str, Any]] = []
    project_path: str = "default"


class LiveOpsManageRequest(BaseModel):
    action: str = "preview"
    liveops_type: str = "remote_config"
    manifest_path: Optional[str] = None
    entry_id: Optional[str] = None
    owner: Optional[str] = None
    value_type: Optional[str] = None
    default_value: Any = None
    enabled: bool = True
    requires_restart: bool = False
    environments: List[str] = []
    rollout_strategy: Optional[str] = None
    rollout_percentage: Optional[float] = None
    audience_segments: List[str] = []
    tags: List[str] = []
    hypothesis: str = ""
    status: Optional[str] = None
    target_metrics: List[str] = []
    variants: List[Dict[str, Any]] = []
    rollback_rule: str = ""
    acceptance_checks: List[str] = []
    notes: str = ""
    entries: List[Dict[str, Any]] = []
    project_path: str = "default"


class TelemetryManageRequest(BaseModel):
    action: str = "analyze"
    catalog_path: Optional[str] = None
    session_path: Optional[str] = None
    catalog_entries: List[Dict[str, Any]] = []
    events: List[Dict[str, Any]] = []
    project_path: str = "default"


class PerformanceManageRequest(BaseModel):
    action: str = "analyze"
    scene_path: Optional[str] = None
    baseline_path: Optional[str] = None
    profile_path: Optional[str] = None
    baseline_metrics: Dict[str, Any] = {}
    profile_metrics: Dict[str, Any] = {}
    budget_overrides: Dict[str, Any] = {}
    project_path: str = "default"


class PlatformDeliveryManageRequest(BaseModel):
    action: str = "preview"
    manifest_path: Optional[str] = None
    platforms: List[Dict[str, Any]] = []
    savegame: Dict[str, Any] = {}
    services: Dict[str, Any] = {}
    multiplayer: Dict[str, Any] = {}
    project_path: str = "default"


class MigrationApplyRequest(BaseModel):
    project_path: str = "default"


class GovernanceAdmissionRequest(BaseModel):
    change_type: str = "feature"
    evidence: Dict[str, Any] = {}
    changed_paths: List[str] = []
    notes: str = ""
    project_path: str = "default"


class GovernanceEnforceRequest(GovernanceAdmissionRequest):
    mode: str = "strict"
    fail_on_warnings: bool = False


class ProductionValidateRequest(BaseModel):
    scenario_id: str = "vertical_slice_2d"
    evidence: Dict[str, Any] = {}
    changed_paths: List[str] = []
    notes: str = ""
    mode: str = "strict"
    fail_on_warnings: bool = False
    project_path: str = "default"


class BuildRunMatrixRequest(BaseModel):
    manifest_path: str = ""
    scenario_ids: List[str] = []
    mode: str = "strict"
    fail_on_warnings: bool = False
    project_path: str = "default"


class ReleaseCandidateChecklistRequest(BaseModel):
    release_manifest_path: str = ""
    evidence: Dict[str, Any] = {}
    changed_paths: List[str] = []
    mode: str = "strict"
    fail_on_warnings: bool = False
    project_path: str = "default"


class ReleasePromotionPlanRequest(BaseModel):
    target_channel: str = "staging"
    target_environment: str = ""
    release_manifest_path: str = ""
    approvers: List[str] = []
    providers: List[str] = []
    mode: str = "strict"
    fail_on_warnings: bool = False
    project_path: str = "default"


class ReleasePromotionRecordRequest(BaseModel):
    history_path: str = ""
    target_channel: str = "staging"
    target_environment: str = ""
    release_manifest_path: str = ""
    approvers: List[str] = []
    providers: List[str] = []
    mode: str = "strict"
    fail_on_warnings: bool = False
    decision: str = "planned"
    executed_by: str = ""
    note: str = ""
    signoff_source: str = ""
    project_path: str = "default"


class ReleaseExecutionRunRequest(BaseModel):
    status_path: str = ""
    channels_path: str = ""
    history_path: str = ""
    target_channel: str = "staging"
    target_environment: str = ""
    release_manifest_path: str = ""
    approvers: List[str] = []
    providers: List[str] = []
    mode: str = "strict"
    fail_on_warnings: bool = False
    operation: str = "dry_run"
    rollout_percentage: int = 10
    executed_by: str = ""
    note: str = ""
    project_path: str = "default"


class ReleaseExecutionRollbackRequest(BaseModel):
    status_path: str = ""
    channels_path: str = ""
    history_path: str = ""
    target_channel: str = "staging"
    target_environment: str = ""
    release_manifest_path: str = ""
    approvers: List[str] = []
    providers: List[str] = []
    mode: str = "strict"
    fail_on_warnings: bool = False
    executed_by: str = ""
    note: str = ""
    rollback_target_url: str = ""
    project_path: str = "default"


class ReleaseLiveCiDispatchRequest(BaseModel):
    repo: str = ""
    ref: str = ""
    workflow: str = DEFAULT_RELEASE_LIVE_DISPATCH_WORKFLOW
    runner_labels: str = '["self-hosted","windows","godot"]'
    target_channel: str = "staging"
    target_environment: str = "staging"
    release_manifest_path: str = "api_server/static/dist/web_release_validation_ci/release_manifest.json"
    runner_profile_path: str = "deployment/release_live_runner_profile.json"
    approvers: List[str] = []
    providers: List[str] = []
    artifact_dir: str = "logs/reports/release_live_ci"
    fail_on_warnings: bool = False
    wait: bool = False
    poll_interval: float = 15.0
    wait_timeout: float = 7200.0
    dispatch_timeout: float = 30.0
    triggered_by: str = ""
    token_env_names: List[str] = list(DEFAULT_RELEASE_LIVE_DISPATCH_TOKEN_ENV_NAMES)
    project_path: str = "default"


class OutsourceDeliveryGateRequest(BaseModel):
    manifest_path: str = ""
    package_root: str = ""
    required_license_names: List[str] = []
    mode: str = "strict"
    fail_on_warnings: bool = False
    project_path: str = "default"


class AssetReviewManageRequest(BaseModel):
    action: str = "snapshot"
    asset_type: str = "outsource"
    asset_manifest_path: str = ""
    review_manifest_path: str = ""
    asset_ids: List[str] = []
    reviewer: str = ""
    review_status: str = "approved"
    review_note: str = ""
    mode: str = "strict"
    fail_on_warnings: bool = False
    project_path: str = "default"


class SceneOwnershipManageRequest(BaseModel):
    action: str = "snapshot"
    board_path: str = ""
    scene_paths: List[str] = []
    scene_category: str = ""
    owner: str = ""
    feature_id: str = ""
    lock_state: str = "hinted"
    note: str = ""
    clear_owner: bool = False
    clear_feature_id: bool = False
    mode: str = "strict"
    fail_on_warnings: bool = False
    project_path: str = "default"


class AgentCompatibilityRequest(BaseModel):
    providers: List[str] = []
    project_path: str = "default"


class InstallCodexSkillRequest(BaseModel):
    project_path: str = "default"


def _build_task_from_editable_plan(router: GodotAgentRouter, req: ExecutePlanRequest, editor_state: Dict[str, Any]) -> Task:
    if not req.steps:
        raise HTTPException(status_code=400, detail="Plan must contain at least one step")

    invalid_roles = sorted({step.role for step in req.steps if step.role not in router.roles})
    if invalid_roles:
        raise HTTPException(status_code=400, detail=f"Unknown roles in plan: {', '.join(invalid_roles)}")

    task = Task(
        prompt=req.prompt,
        task_id=req.task_id or Task(prompt=req.prompt).task_id,
        context=dict(req.context or {})
    )
    task.context["editor_state"] = editor_state
    task_status_values = {item.value for item in TaskStatus}
    task.steps = [
        TaskStep(
            name=step.name,
            description=step.description,
            role=step.role,
            depends_on=list(step.depends_on or []),
            status=TaskStatus(step.status) if step.status in task_status_values else TaskStatus.PENDING,
            requires_confirmation=bool(step.requires_confirmation),
            metadata=dict(step.metadata or {}),
        )
        for step in req.steps
    ]
    task.role = task.steps[0].role
    task.status = TaskStatus.AWAITING_CONFIRMATION
    return task


def _safe_get_router_task(router: Any, task_id: str) -> Optional[Task]:
    get_task = getattr(router, "get_task", None)
    if not callable(get_task):
        return None
    return get_task(task_id)


def _persist_router_task(router: Any, task: Task) -> None:
    save_task = getattr(router, "_save_task", None)
    if callable(save_task):
        save_task(task)


def _append_feature_lifecycle_event(context: Dict[str, Any], event_type: str, summary: str) -> Dict[str, Any]:
    updated = dict(context or {})
    events = normalize_feature_lifecycle_events(updated.get("feature_lifecycle_events"))
    events.append(build_feature_lifecycle_event(event_type, summary, datetime.now(timezone.utc).isoformat()))
    updated["feature_lifecycle_events"] = events[-50:]
    return updated


def _append_review_followup_steps(task: Task, followups: List[str], *, reviewer: str, review_round: str) -> int:
    existing_keys = {
        str(step.metadata.get("review_followup_key") or "").strip().lower()
        for step in task.steps
        if isinstance(step.metadata, dict)
    }
    added = 0
    for followup in [str(item).strip() for item in followups if str(item).strip()]:
        key = f"{review_round or 'review'}:{followup}".lower()
        if key in existing_keys:
            continue
        task.steps.append(TaskStep(
            name=f"Review follow-up: {followup}",
            description=f"Resolve returned review follow-up: {followup}",
            role="tester",
            status=TaskStatus.PENDING,
            metadata={
                "review_followup": True,
                "review_followup_key": key,
                "reviewer": str(reviewer or "").strip(),
                "review_round": str(review_round or "").strip(),
                "source": "feature_review",
            },
        ))
        existing_keys.add(key)
        added += 1
    return added


def _close_completed_review_followups(task: Task) -> None:
    review_steps = [
        step for step in task.steps
        if isinstance(step.metadata, dict) and step.metadata.get("review_followup")
    ]
    if not review_steps or any(step.status != TaskStatus.SUCCESS for step in review_steps):
        return

    context = dict(task.context or {})
    followups = [str(item).strip() for item in list(context.get("required_followups") or []) if str(item).strip()]
    if str(context.get("feature_status") or "").strip().lower() == "pending_acceptance" and not followups:
        return

    if followups:
        context["blockers"] = [
            item for item in [str(value).strip() for value in list(context.get("blockers") or [])]
            if item and item not in set(followups)
        ]
    context["required_followups"] = []
    context["feature_status"] = "pending_acceptance"
    task.context = _append_feature_lifecycle_event(
        context,
        "review_followups_completed",
        f"已完成 {len(review_steps)} 个复审待办，等待二次验收",
    )


def _apply_feature_review_to_task(task: Task, req: FeatureReviewRequest) -> str:
    feature_status = str(req.feature_status or "").strip().lower()
    if feature_status not in {"approved", "returned", "pending_review", "pending_acceptance"}:
        raise HTTPException(status_code=400, detail="Unsupported feature_status")

    note = str(req.review_note or "").strip()
    context = dict(task.context or {})
    review_history = normalize_review_history(context.get("feature_review_history"))
    review_history.append(build_feature_review_entry(
        feature_status=feature_status,
        review_note=note,
        timestamp=datetime.now(timezone.utc).isoformat(),
        reviewer=req.reviewer,
        review_round=req.review_round,
        required_followups=req.required_followups,
    ))

    status_label = {
        "approved": "已通过",
        "returned": "已退回",
        "pending_review": "待评审",
        "pending_acceptance": "待验收",
    }[feature_status]
    context = _append_feature_lifecycle_event(
        context,
        f"review_{feature_status}",
        status_label + (f" - {note}" if note else ""),
    )
    context["feature_status"] = feature_status
    context["feature_review_note"] = note
    context["feature_review_history"] = review_history[-20:]
    followups = [str(item).strip() for item in list(req.required_followups or []) if str(item).strip()]
    context["reviewer"] = str(req.reviewer or "").strip()
    context["review_round"] = str(req.review_round or "").strip()
    context["required_followups"] = followups
    for field in ("dependency", "eta", "validation_method"):
        value = str(getattr(req, field, "") or "").strip()
        if value:
            context[field] = value
    if req.blockers is not None or "blockers" in context:
        context["blockers"] = [str(item).strip() for item in list(req.blockers or []) if str(item).strip()]
    if req.external_links is not None:
        context["external_links"] = normalize_feature_external_links(req.external_links)
    if feature_status == "returned" and note and not context.get("blockers"):
        context["blockers"] = [note]
    if feature_status == "returned" and followups:
        context["blockers"] = list(dict.fromkeys(list(context.get("blockers") or []) + followups))
        added_steps = _append_review_followup_steps(
            task,
            followups,
            reviewer=req.reviewer,
            review_round=req.review_round,
        )
        if added_steps:
            context = _append_feature_lifecycle_event(
                context,
                "review_followups_planned",
                f"已生成 {added_steps} 个复审待办步骤",
            )
    if feature_status == "approved" and req.blockers is None:
        context["blockers"] = []
    task.context = build_task_feature_context(
        prompt=task.prompt,
        task_id=task.task_id,
        task_status=task.status,
        context=context,
        steps=task.steps,
        artifacts=task.artifacts,
        message=task.message,
    )
    task.add_log(f"FEATURE_REVIEW: {status_label}" + (f" - {note}" if note else ""))
    return status_label


def _normalize_history_query(value: Optional[str]) -> str:
    return str(value or "").strip().lower()


def _history_item_matches(
    item: Dict[str, Any],
    feature_status: str,
    feature_id_query: str,
    owner_query: str,
) -> bool:
    context = item.get("context") or {}
    item_feature_status = _normalize_history_query(context.get("feature_status"))
    item_feature_id = _normalize_history_query(context.get("feature_id"))
    item_owner = _normalize_history_query(context.get("owner"))

    if feature_status and item_feature_status != feature_status:
        return False
    if feature_id_query and feature_id_query not in item_feature_id:
        return False
    if owner_query and owner_query not in item_owner:
        return False
    return True


def _load_history_items(router: Any, limit: Optional[int] = None) -> List[Dict[str, Any]]:
    tasks = getattr(router, "tasks", None)
    if isinstance(tasks, dict):
        items = [
            task.to_dict()
            for task in sorted(tasks.values(), key=lambda item: item.created_at, reverse=True)
        ]
        return items if limit is None else items[:limit]

    get_history = getattr(router, "get_history", None)
    if callable(get_history):
        effective_limit = 100 if limit is None else limit
        return list(get_history(limit=effective_limit))
    return []


def _get_data_table_skill(project_path: str):
    router = manager.get_router(project_path)
    skill = SkillRegistry.get_skill(
        "manage_game_data_tables",
        router.godot_cli,
        getattr(router, "index_service", None),
    )
    if skill is None:
        raise HTTPException(status_code=500, detail="Data table skill is unavailable")
    return router, skill


def _get_art_asset_skill(project_path: str):
    router = manager.get_router(project_path)
    skill = SkillRegistry.get_skill(
        "manage_art_asset_pipeline",
        router.godot_cli,
        getattr(router, "index_service", None),
    )
    if skill is None:
        raise HTTPException(status_code=500, detail="Art asset skill is unavailable")
    return router, skill


def _get_level_workflow_skill(project_path: str):
    router = manager.get_router(project_path)
    skill = SkillRegistry.get_skill(
        "manage_level_workflow",
        router.godot_cli,
        getattr(router, "index_service", None),
    )
    if skill is None:
        raise HTTPException(status_code=500, detail="Level workflow skill is unavailable")
    return router, skill


def _get_gameplay_template_skill(project_path: str):
    router = manager.get_router(project_path)
    skill = SkillRegistry.get_skill(
        "manage_gameplay_template",
        router.godot_cli,
        getattr(router, "index_service", None),
    )
    if skill is None:
        raise HTTPException(status_code=500, detail="Gameplay template skill is unavailable")
    return router, skill


def _get_presentation_skill(project_path: str):
    router = manager.get_router(project_path)
    skill = SkillRegistry.get_skill(
        "manage_presentation_pipeline",
        router.godot_cli,
        getattr(router, "index_service", None),
    )
    if skill is None:
        raise HTTPException(status_code=500, detail="Presentation pipeline skill is unavailable")
    return router, skill


def _get_liveops_skill(project_path: str):
    router = manager.get_router(project_path)
    skill = SkillRegistry.get_skill(
        "manage_liveops_pipeline",
        router.godot_cli,
        getattr(router, "index_service", None),
    )
    if skill is None:
        raise HTTPException(status_code=500, detail="LiveOps pipeline skill is unavailable")
    return router, skill


def _get_platform_delivery_skill(project_path: str):
    router = manager.get_router(project_path)
    skill = SkillRegistry.get_skill(
        "manage_platform_delivery",
        router.godot_cli,
        getattr(router, "index_service", None),
    )
    if skill is None:
        raise HTTPException(status_code=500, detail="Platform delivery skill is unavailable")
    return router, skill


def _get_telemetry_skill(project_path: str):
    router = manager.get_router(project_path)
    skill = SkillRegistry.get_skill(
        "manage_game_telemetry",
        router.godot_cli,
        getattr(router, "index_service", None),
    )
    if skill is None:
        raise HTTPException(status_code=500, detail="Telemetry skill is unavailable")
    return router, skill


def _get_performance_skill(project_path: str):
    router = manager.get_router(project_path)
    skill = SkillRegistry.get_skill(
        "manage_game_performance",
        router.godot_cli,
        getattr(router, "index_service", None),
    )
    if skill is None:
        raise HTTPException(status_code=500, detail="Performance skill is unavailable")
    return router, skill


def _build_data_table_catalog(project_path: str) -> List[Dict[str, Any]]:
    _, skill = _get_data_table_skill(project_path)
    project_root = _resolve_project_root(project_path).resolve()
    items: List[Dict[str, Any]] = []
    for table_type, schema in TABLE_SCHEMAS.items():
        snapshot = skill.get_table_snapshot(table_type)
        resolved_table_path = Path(snapshot["table_path"]).resolve()
        try:
            display_path = resolved_table_path.relative_to(project_root).as_posix()
        except ValueError:
            display_path = snapshot["table_path"]
        items.append({
            "table_type": table_type,
            "label": TABLE_TYPE_LABELS.get(table_type, table_type),
            "default_path": schema["default_path"],
            "columns": schema["columns"],
            "sample_rows": list(schema.get("sample_rows") or []),
            "exists": snapshot["exists"],
            "row_count": snapshot["row_count"],
            "issue_count": snapshot["issue_count"],
            "table_path": snapshot["table_path"],
            "display_path": display_path,
        })
    return items


def _build_data_table_snapshot(
    project_path: str,
    table_type: str,
    table_path: Optional[str] = None,
    rows: Optional[List[Dict[str, Any]]] = None,
    content: Optional[str] = None,
) -> Dict[str, Any]:
    _, skill = _get_data_table_skill(project_path)
    snapshot = skill.get_table_snapshot(table_type, table_path=table_path, rows=rows, content=content)
    project_root = _resolve_project_root(project_path).resolve()
    resolved_table_path = Path(snapshot["table_path"]).resolve()
    try:
        snapshot["display_path"] = resolved_table_path.relative_to(project_root).as_posix()
    except ValueError:
        snapshot["display_path"] = snapshot["table_path"]
    snapshot["project_path"] = project_path
    return snapshot


def _build_art_asset_catalog(project_path: str) -> List[Dict[str, Any]]:
    _, skill = _get_art_asset_skill(project_path)
    items: List[Dict[str, Any]] = []
    for asset_type, schema in ART_ASSET_SCHEMAS.items():
        snapshot = skill.get_snapshot(
            asset_type=asset_type,
            manifest_path=schema.get("manifest_path"),
        )
        manifest_res_path = str(snapshot.get("manifest_path") or f"res://{schema['manifest_path']}")
        items.append({
            "asset_type": asset_type,
            "label": ART_ASSET_TYPE_LABELS.get(asset_type, asset_type),
            "default_directory": schema.get("default_directory"),
            "default_manifest_path": "res://" + str(schema.get("manifest_path") or "").replace("\\", "/"),
            "sample_entries": list(schema.get("sample_entries") or []),
            "entry_count": snapshot.get("entry_count", 0),
            "copied_target_count": snapshot.get("copied_target_count", 0),
            "manifest_path": manifest_res_path,
            "display_path": manifest_res_path.replace("res://", "", 1),
        })
    return items


def _build_art_asset_snapshot(
    project_path: str,
    asset_type: str,
    manifest_path: Optional[str] = None,
    asset_id: Optional[str] = None,
) -> Dict[str, Any]:
    _, skill = _get_art_asset_skill(project_path)
    snapshot = skill.get_snapshot(
        asset_type=asset_type,
        manifest_path=manifest_path,
        asset_id=asset_id,
    )
    manifest_res_path = str(snapshot.get("manifest_path") or "")
    snapshot["display_path"] = manifest_res_path.replace("res://", "", 1)
    snapshot["project_path"] = project_path
    return snapshot


def _build_outsource_delivery_gate_snapshot(
    project_path: str,
    *,
    manifest_path: Optional[str] = None,
    package_root: Optional[str] = None,
    required_license_names: Optional[List[str]] = None,
    mode: str = "strict",
    fail_on_warnings: bool = False,
) -> Dict[str, Any]:
    project_root = _resolve_project_root(project_path)
    payload = build_outsource_delivery_gate(
        project_root,
        runtime_root=REPO_ROOT,
        manifest_path=manifest_path or DEFAULT_OUTSOURCE_MANIFEST_PATH,
        package_root=package_root or DEFAULT_OUTSOURCE_PACKAGE_ROOT,
        required_license_names=required_license_names or None,
        mode=mode,
        fail_on_warnings=fail_on_warnings,
    )
    payload["project_path"] = project_path
    return payload


def _build_asset_review_workflow_snapshot(
    project_path: str,
    *,
    asset_type: str = "outsource",
    asset_manifest_path: Optional[str] = None,
    review_manifest_path: Optional[str] = None,
    asset_ids: Optional[List[str]] = None,
    mode: str = "strict",
    fail_on_warnings: bool = False,
) -> Dict[str, Any]:
    project_root = _resolve_project_root(project_path)
    payload = build_asset_review_workflow(
        project_root,
        runtime_root=REPO_ROOT,
        asset_type=asset_type,
        asset_manifest_path=asset_manifest_path or "",
        review_manifest_path=review_manifest_path or DEFAULT_ASSET_REVIEW_MANIFEST_PATH,
        asset_ids=asset_ids,
        mode=mode,
        fail_on_warnings=fail_on_warnings,
    )
    payload["project_path"] = project_path
    return payload


def _build_scene_ownership_board_snapshot(
    project_path: str,
    *,
    board_path: Optional[str] = None,
    scene_paths: Optional[List[str]] = None,
    scene_category: str = "",
    mode: str = "strict",
    fail_on_warnings: bool = False,
) -> Dict[str, Any]:
    project_root = _resolve_project_root(project_path)
    payload = build_scene_ownership_board(
        project_root,
        runtime_root=REPO_ROOT,
        board_path=board_path or DEFAULT_SCENE_OWNERSHIP_BOARD_PATH,
        scene_paths=scene_paths or None,
        scene_category=scene_category,
        mode=mode,
        fail_on_warnings=fail_on_warnings,
    )
    payload["project_path"] = project_path
    return payload


def _build_build_run_matrix_snapshot(
    project_path: str,
    *,
    manifest_path: Optional[str] = None,
    scenario_ids: Optional[List[str]] = None,
    mode: str = "strict",
    fail_on_warnings: bool = False,
) -> Dict[str, Any]:
    project_root = _resolve_project_root(project_path)
    payload = build_build_run_matrix(
        project_root,
        runtime_root=REPO_ROOT,
        manifest_path=manifest_path or DEFAULT_PLATFORM_DELIVERY_MANIFEST_PATH,
        scenario_ids=scenario_ids or None,
        mode=mode,
        fail_on_warnings=fail_on_warnings,
    )
    payload["project_path"] = project_path
    return payload


def _build_release_capability_registry_snapshot(
    project_path: str,
    *,
    registry_path: str = "",
) -> Dict[str, Any]:
    project_root = _resolve_project_root(project_path)
    payload = build_release_capability_registry(
        project_root,
        registry_path=registry_path or DEFAULT_RELEASE_CAPABILITY_REGISTRY_PATH,
    )
    payload["project_path"] = project_path
    return payload


def _build_release_capability_registry_export(
    project_path: str,
    *,
    registry_path: str = "",
) -> Dict[str, Any]:
    registry = _build_release_capability_registry_snapshot(
        project_path,
        registry_path=registry_path or DEFAULT_RELEASE_CAPABILITY_REGISTRY_PATH,
    )
    return {
        "project_path": project_path,
        "registry": registry,
        "report_name": "release_capability_registry.md",
        "report_content": build_release_capability_registry_report(registry),
    }


def _build_release_capability_policy_snapshot(
    project_path: str,
    *,
    registry_path: str = "",
    route_kind: str = "portal",
    target_channel: str = "staging",
    target_environment: str = "",
    actor_id: str = "",
) -> Dict[str, Any]:
    project_root = _resolve_project_root(project_path)
    payload = build_release_capability_policy(
        project_root,
        runtime_root=REPO_ROOT,
        registry_path=registry_path or DEFAULT_RELEASE_CAPABILITY_REGISTRY_PATH,
        route_kind=route_kind,
        target_channel=target_channel or "staging",
        target_environment=target_environment,
        actor_id=actor_id,
    )
    payload["project_path"] = project_path
    return payload


def _build_release_capability_policy_export(
    project_path: str,
    *,
    registry_path: str = "",
    route_kind: str = "portal",
    target_channel: str = "staging",
    target_environment: str = "",
    actor_id: str = "",
) -> Dict[str, Any]:
    policy = _build_release_capability_policy_snapshot(
        project_path,
        registry_path=registry_path or DEFAULT_RELEASE_CAPABILITY_REGISTRY_PATH,
        route_kind=route_kind,
        target_channel=target_channel or "staging",
        target_environment=target_environment,
        actor_id=actor_id,
    )
    return {
        "project_path": project_path,
        "policy": policy,
        "report_name": "release_capability_policy.md",
        "report_content": build_release_capability_policy_report(policy),
    }


def _build_release_delivery_readiness_snapshot(
    project_path: str,
    *,
    target_channel: str = "release",
    target_environment: str = "",
    artifact_dir: str = DEFAULT_RELEASE_DELIVERY_ARTIFACT_DIR,
    workflow: str = DEFAULT_RELEASE_LIVE_DISPATCH_WORKFLOW,
    repo: str = "",
    ref: str = "",
    token_env_names: str = ",".join(DEFAULT_RELEASE_LIVE_DISPATCH_TOKEN_ENV_NAMES),
) -> Dict[str, Any]:
    project_root = _resolve_project_root(project_path)
    token_names = [item.strip() for item in token_env_names.split(",") if item.strip()] if token_env_names else list(DEFAULT_RELEASE_LIVE_DISPATCH_TOKEN_ENV_NAMES)
    payload = build_release_delivery_readiness(
        project_root,
        runtime_root=REPO_ROOT,
        target_channel=target_channel or "release",
        target_environment=target_environment,
        artifact_dir=artifact_dir or DEFAULT_RELEASE_DELIVERY_ARTIFACT_DIR,
        workflow=workflow or DEFAULT_RELEASE_LIVE_DISPATCH_WORKFLOW,
        repo=repo,
        ref=ref,
        token_env_names=token_names,
    )
    payload["project_path"] = project_path
    return payload


def _build_release_delivery_readiness_export(
    project_path: str,
    *,
    target_channel: str = "release",
    target_environment: str = "",
    artifact_dir: str = DEFAULT_RELEASE_DELIVERY_ARTIFACT_DIR,
    workflow: str = DEFAULT_RELEASE_LIVE_DISPATCH_WORKFLOW,
    repo: str = "",
    ref: str = "",
    token_env_names: str = ",".join(DEFAULT_RELEASE_LIVE_DISPATCH_TOKEN_ENV_NAMES),
) -> Dict[str, Any]:
    readiness = _build_release_delivery_readiness_snapshot(
        project_path,
        target_channel=target_channel or "release",
        target_environment=target_environment,
        artifact_dir=artifact_dir or DEFAULT_RELEASE_DELIVERY_ARTIFACT_DIR,
        workflow=workflow or DEFAULT_RELEASE_LIVE_DISPATCH_WORKFLOW,
        repo=repo,
        ref=ref,
        token_env_names=token_env_names,
    )
    return {
        "project_path": project_path,
        "readiness": readiness,
        "report_name": "release_delivery_readiness.md",
        "report_content": build_release_delivery_readiness_report(readiness),
    }


def _build_release_promotion_plan_snapshot(
    project_path: str,
    *,
    target_channel: str = "staging",
    target_environment: str = "",
    release_manifest_path: str = "",
    approvers: Optional[List[str]] = None,
    providers: Optional[List[str]] = None,
    mode: str = "strict",
    fail_on_warnings: bool = False,
) -> Dict[str, Any]:
    project_root = _resolve_project_root(project_path)
    payload = build_release_promotion_plan(
        project_root,
        runtime_root=REPO_ROOT,
        target_channel=target_channel,
        target_environment=target_environment,
        release_manifest_path=release_manifest_path,
        approvers=approvers or None,
        providers=providers or None,
        mode=mode,
        fail_on_warnings=fail_on_warnings,
    )
    payload["project_path"] = project_path
    return payload


def _build_release_promotion_evidence_export(
    project_path: str,
    *,
    target_channel: str = "staging",
    target_environment: str = "",
    release_manifest_path: str = "",
    approvers: Optional[List[str]] = None,
    providers: Optional[List[str]] = None,
    mode: str = "strict",
    fail_on_warnings: bool = False,
) -> Dict[str, Any]:
    plan = _build_release_promotion_plan_snapshot(
        project_path,
        target_channel=target_channel,
        target_environment=target_environment,
        release_manifest_path=release_manifest_path,
        approvers=approvers,
        providers=providers,
        mode=mode,
        fail_on_warnings=fail_on_warnings,
    )
    return {
        "project_path": project_path,
        "evidence_bundle": dict(plan.get("evidence_bundle") or {}),
        "report_name": "release_promotion_evidence_bundle.md",
        "report_content": build_release_promotion_evidence_report(plan),
        "plan": plan,
    }


def _build_release_promotion_deployment_export(
    project_path: str,
    *,
    target_channel: str = "staging",
    target_environment: str = "",
    release_manifest_path: str = "",
    approvers: Optional[List[str]] = None,
    providers: Optional[List[str]] = None,
    mode: str = "strict",
    fail_on_warnings: bool = False,
) -> Dict[str, Any]:
    plan = _build_release_promotion_plan_snapshot(
        project_path,
        target_channel=target_channel,
        target_environment=target_environment,
        release_manifest_path=release_manifest_path,
        approvers=approvers,
        providers=providers,
        mode=mode,
        fail_on_warnings=fail_on_warnings,
    )
    return {
        "project_path": project_path,
        "deployment_rehearsal": dict(plan.get("deployment_rehearsal") or {}),
        "report_name": "release_promotion_deployment_rehearsal.md",
        "report_content": build_deployment_rehearsal_report(plan),
        "plan": plan,
    }


def _build_release_promotion_review_bundle_export(
    project_path: str,
    *,
    target_channel: str = "staging",
    target_environment: str = "",
    release_manifest_path: str = "",
    approvers: Optional[List[str]] = None,
    providers: Optional[List[str]] = None,
    mode: str = "strict",
    fail_on_warnings: bool = False,
) -> Dict[str, Any]:
    plan = _build_release_promotion_plan_snapshot(
        project_path,
        target_channel=target_channel,
        target_environment=target_environment,
        release_manifest_path=release_manifest_path,
        approvers=approvers,
        providers=providers,
        mode=mode,
        fail_on_warnings=fail_on_warnings,
    )
    return {
        "project_path": project_path,
        "review_bundle": dict(plan.get("review_bundle") or {}),
        "report_name": "release_review_bundle.md",
        "report_content": build_release_review_bundle_report(plan),
        "plan": plan,
    }


def _build_release_promotion_rollback_export(
    project_path: str,
    *,
    target_channel: str = "staging",
    target_environment: str = "",
    release_manifest_path: str = "",
    approvers: Optional[List[str]] = None,
    providers: Optional[List[str]] = None,
    mode: str = "strict",
    fail_on_warnings: bool = False,
) -> Dict[str, Any]:
    plan = _build_release_promotion_plan_snapshot(
        project_path,
        target_channel=target_channel,
        target_environment=target_environment,
        release_manifest_path=release_manifest_path,
        approvers=approvers,
        providers=providers,
        mode=mode,
        fail_on_warnings=fail_on_warnings,
    )
    return {
        "project_path": project_path,
        "rollback_rehearsal": dict(plan.get("rollback_rehearsal") or {}),
        "report_name": "release_promotion_rollback_rehearsal.md",
        "report_content": build_rollback_rehearsal_report(plan),
        "plan": plan,
    }


def _build_release_promotion_history_snapshot(
    project_path: str,
    *,
    history_path: str = "",
    decision: str = "",
    target_channel: str = "",
    executed_by: str = "",
    live_ci_status: str = "",
    dispatch_status: str = "",
    dispatch_follow_up: str = "",
    dispatch_run_status: str = "",
    dispatch_run_conclusion: str = "",
    failed_workflow_step: str = "",
    delivery_readiness_status: str = "",
    readiness_action: str = "",
    offset: int = 0,
    limit: int = 20,
) -> Dict[str, Any]:
    project_root = _resolve_project_root(project_path)
    payload = build_release_promotion_history(
        project_root,
        runtime_root=REPO_ROOT,
        history_path=history_path or DEFAULT_RELEASE_PROMOTION_HISTORY_PATH,
        decision=decision,
        target_channel=target_channel,
        executed_by=executed_by,
        live_ci_status=live_ci_status,
        dispatch_status=dispatch_status,
        dispatch_follow_up=dispatch_follow_up,
        dispatch_run_status=dispatch_run_status,
        dispatch_run_conclusion=dispatch_run_conclusion,
        failed_workflow_step=failed_workflow_step,
        delivery_readiness_status=delivery_readiness_status,
        readiness_action=readiness_action,
        offset=offset,
        limit=limit,
    )
    payload["project_path"] = project_path
    return payload


def _build_release_promotion_history_export(
    project_path: str,
    *,
    history_path: str = "",
    decision: str = "",
    target_channel: str = "",
    executed_by: str = "",
    live_ci_status: str = "",
    dispatch_status: str = "",
    dispatch_follow_up: str = "",
    dispatch_run_status: str = "",
    dispatch_run_conclusion: str = "",
    failed_workflow_step: str = "",
    delivery_readiness_status: str = "",
    readiness_action: str = "",
    offset: int = 0,
    limit: int = 20,
) -> Dict[str, Any]:
    history = _build_release_promotion_history_snapshot(
        project_path,
        history_path=history_path,
        decision=decision,
        target_channel=target_channel,
        executed_by=executed_by,
        live_ci_status=live_ci_status,
        dispatch_status=dispatch_status,
        dispatch_follow_up=dispatch_follow_up,
        dispatch_run_status=dispatch_run_status,
        dispatch_run_conclusion=dispatch_run_conclusion,
        failed_workflow_step=failed_workflow_step,
        delivery_readiness_status=delivery_readiness_status,
        readiness_action=readiness_action,
        offset=offset,
        limit=limit,
    )
    return {
        "project_path": project_path,
        "history": history,
        "report_name": "release_promotion_history.md",
        "report_content": build_release_promotion_history_report(history),
    }


def _build_release_execution_status_snapshot(
    project_path: str,
    *,
    status_path: str = "",
    channels_path: str = "",
    history_path: str = "",
    operation: str = "",
    target_channel: str = "",
    executed_by: str = "",
    offset: int = 0,
    limit: int = 20,
) -> Dict[str, Any]:
    project_root = _resolve_project_root(project_path)
    payload = build_release_execution_status(
        project_root,
        runtime_root=REPO_ROOT,
        status_path=status_path or DEFAULT_RELEASE_EXECUTION_STATUS_PATH,
        channels_path=channels_path or DEFAULT_RELEASE_CHANNELS_PATH,
        history_path=history_path or DEFAULT_RELEASE_PROMOTION_HISTORY_PATH,
        operation=operation,
        target_channel=target_channel,
        executed_by=executed_by,
        offset=offset,
        limit=limit,
    )
    payload["project_path"] = project_path
    return payload


def _build_release_live_ci_summary_snapshot(
    project_path: str,
    *,
    artifact_dir: str = "logs/reports/release_live_ci",
) -> Dict[str, Any]:
    project_root = _resolve_project_root(project_path)
    resolved_artifact_dir = _resolve_under(project_root, artifact_dir or "logs/reports/release_live_ci")
    summary_path = resolved_artifact_dir / "release_live_ci_summary.json"
    if not summary_path.exists():
        raise HTTPException(status_code=404, detail="release live ci summary not found")

    try:
        payload = json.loads(summary_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=500, detail="release live ci summary is unreadable") from exc
    if not isinstance(payload, dict):
        raise HTTPException(status_code=500, detail="release live ci summary payload is invalid")

    payload["event_stream"] = normalize_release_live_event_stream(payload.get("event_stream"))
    dispatch_audit = load_release_live_dispatch_audit(project_root, artifact_dir=artifact_dir)
    if dispatch_audit:
        payload["dispatch_audit"] = normalize_release_live_dispatch_audit(dispatch_audit)
    payload["project_path"] = project_path
    payload["artifact_dir"] = _display_project_path(project_root, resolved_artifact_dir)
    payload["summary_path"] = _display_project_path(project_root, summary_path)
    summary_markdown_path = resolved_artifact_dir / "release_live_ci_summary.md"
    payload["summary_markdown_path"] = _display_project_path(project_root, summary_markdown_path)
    payload["summary_markdown_exists"] = summary_markdown_path.exists()
    return payload


def _build_release_artifact_manifest_snapshot(
    project_path: str,
    *,
    artifact_dir: str = "logs/reports/release_live_ci",
) -> Dict[str, Any]:
    project_root = _resolve_project_root(project_path)
    resolved_artifact_dir = _resolve_under(project_root, artifact_dir or "logs/reports/release_live_ci")
    manifest_path = resolved_artifact_dir / "artifact_manifest.json"
    if not manifest_path.exists():
        raise HTTPException(status_code=404, detail="release artifact manifest not found")

    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=500, detail="release artifact manifest is unreadable") from exc
    if not isinstance(payload, dict):
        raise HTTPException(status_code=500, detail="release artifact manifest payload is invalid")

    normalized = normalize_release_artifact_manifest(payload)
    normalized["project_path"] = project_path
    normalized["artifact_dir"] = _display_project_path(project_root, resolved_artifact_dir)
    normalized["manifest_path"] = _display_project_path(project_root, manifest_path)
    normalized["manifest_exists"] = True
    return normalized


def _build_release_live_ci_event_stream_snapshot(
    project_path: str,
    *,
    artifact_dir: str = "logs/reports/release_live_ci",
    event_type: str = "",
    status: str = "",
    step_id: str = "",
    lane_id: str = "",
    offset: int = 0,
    limit: int = 20,
) -> Dict[str, Any]:
    summary = _build_release_live_ci_summary_snapshot(
        project_path,
        artifact_dir=artifact_dir,
    )
    normalized_event_type = str(event_type or "").strip()
    normalized_status = str(status or "").strip().lower()
    normalized_step_id = str(step_id or "").strip()
    normalized_lane_id = str(lane_id or "").strip()
    normalized_offset = max(int(offset or 0), 0)
    normalized_limit = max(int(limit or 20), 1)

    event_stream = normalize_release_live_event_stream(summary.get("event_stream"))
    all_events = [dict(item) for item in list(event_stream.get("events") or []) if isinstance(item, dict)]
    filtered_events = [
        item for item in all_events
        if (not normalized_event_type or str(item.get("event_type") or "").strip() == normalized_event_type)
        and (not normalized_status or str(item.get("status") or "").strip().lower() == normalized_status)
        and (not normalized_step_id or str(item.get("step_id") or "").strip() == normalized_step_id)
        and (not normalized_lane_id or str(item.get("lane_id") or "").strip() == normalized_lane_id)
    ]
    visible_events = filtered_events[normalized_offset:normalized_offset + normalized_limit]
    next_offset = normalized_offset + normalized_limit if normalized_offset + normalized_limit < len(filtered_events) else None
    prev_offset = normalized_offset - normalized_limit if normalized_offset > 0 else None
    paged_stream = dict(event_stream)
    paged_stream["events"] = visible_events

    return {
        "project_path": project_path,
        "artifact_dir": summary.get("artifact_dir") or artifact_dir,
        "summary_path": summary.get("summary_path") or "",
        "event_type_filter": normalized_event_type,
        "status_filter": normalized_status,
        "step_id_filter": normalized_step_id,
        "lane_id_filter": normalized_lane_id,
        "offset": normalized_offset,
        "limit": normalized_limit,
        "matched_count": len(filtered_events),
        "visible_count": len(visible_events),
        "next_offset": next_offset,
        "prev_offset": prev_offset,
        "event_stream": paged_stream,
    }


def _build_release_live_ci_summary_export(
    project_path: str,
    *,
    artifact_dir: str = "logs/reports/release_live_ci",
) -> Dict[str, Any]:
    summary = _build_release_live_ci_summary_snapshot(
        project_path,
        artifact_dir=artifact_dir,
    )
    try:
        summary["artifact_manifest"] = _build_release_artifact_manifest_snapshot(
            project_path,
            artifact_dir=artifact_dir,
        )
    except HTTPException as exc:
        if exc.status_code != 404:
            raise
    report_content = build_release_live_ci_summary_markdown(summary)
    return {
        "project_path": project_path,
        "artifact_dir": summary.get("artifact_dir") or artifact_dir,
        "summary": summary,
        "report_name": "release_live_ci_summary.md",
        "report_content": report_content,
    }


def _build_release_live_ci_dispatch_audit_snapshot(
    project_path: str,
    *,
    artifact_dir: str = "logs/reports/release_live_ci",
) -> Dict[str, Any]:
    project_root = _resolve_project_root(project_path)
    resolved_artifact_dir = _resolve_under(project_root, artifact_dir or "logs/reports/release_live_ci")
    payload = load_release_live_dispatch_audit(project_root, artifact_dir=artifact_dir)
    if not payload:
        raise HTTPException(status_code=404, detail="release live dispatch audit not found")
    normalized = normalize_release_live_dispatch_audit(payload)
    normalized["project_path"] = project_path
    normalized["artifact_dir"] = _display_project_path(project_root, resolved_artifact_dir)
    normalized["path"] = _display_project_path(project_root, _resolve_under(project_root, normalized.get("path") or artifact_dir))
    return normalized


def _build_release_live_ci_dispatch_preflight_snapshot(
    project_path: str,
    *,
    repo: str = "",
    ref: str = "",
    workflow: str = DEFAULT_RELEASE_LIVE_DISPATCH_WORKFLOW,
    runner_labels: str = '["self-hosted","windows","godot"]',
    target_channel: str = "staging",
    target_environment: str = "staging",
    release_manifest_path: str = "api_server/static/dist/web_release_validation_ci/release_manifest.json",
    runner_profile_path: str = "deployment/release_live_runner_profile.json",
    approvers: str = "",
    providers: str = "codex,openai_api",
    artifact_dir: str = "logs/reports/release_live_ci",
    fail_on_warnings: bool = False,
    token_env_names: str = ",".join(DEFAULT_RELEASE_LIVE_DISPATCH_TOKEN_ENV_NAMES),
) -> Dict[str, Any]:
    project_root = _resolve_project_root(project_path)
    preflight = build_release_live_dispatch_preflight(
        project_root,
        repo=repo,
        ref=ref,
        workflow=workflow,
        runner_labels=runner_labels,
        target_channel=target_channel,
        target_environment=target_environment,
        release_manifest_path=release_manifest_path,
        runner_profile_path=runner_profile_path,
        approvers=approvers,
        providers=providers,
        artifact_dir=artifact_dir,
        fail_on_warnings=fail_on_warnings,
        token_env_names=token_env_names,
    )
    payload = normalize_release_live_dispatch_preflight(preflight)
    payload["project_path"] = project_path
    return payload


def _build_release_execution_report_export(
    project_path: str,
    *,
    status_path: str = "",
    channels_path: str = "",
    history_path: str = "",
    operation: str = "",
    target_channel: str = "",
    executed_by: str = "",
    offset: int = 0,
    limit: int = 20,
) -> Dict[str, Any]:
    execution_status = _build_release_execution_status_snapshot(
        project_path,
        status_path=status_path,
        channels_path=channels_path,
        history_path=history_path,
        operation=operation,
        target_channel=target_channel,
        executed_by=executed_by,
        offset=offset,
        limit=limit,
    )
    return {
        "project_path": project_path,
        "execution_status": execution_status,
        "report_name": "release_execution_report.md",
        "report_content": build_release_execution_report(execution_status),
    }


def _build_telemetry_snapshot(
    project_path: str,
    catalog_path: Optional[str] = None,
    session_path: Optional[str] = None,
    catalog_entries: Optional[List[Dict[str, Any]]] = None,
    events: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    _, skill = _get_telemetry_skill(project_path)
    snapshot = skill.get_snapshot(
        catalog_path=catalog_path,
        session_path=session_path,
        catalog_entries=catalog_entries,
        events=events,
    )
    project_root = _resolve_project_root(project_path).resolve()
    resolved_catalog_path = Path(snapshot["catalog_path"]).resolve()
    try:
        snapshot["catalog_display_path"] = resolved_catalog_path.relative_to(project_root).as_posix()
    except ValueError:
        snapshot["catalog_display_path"] = snapshot["catalog_path"]
    if snapshot.get("session_path"):
        resolved_session_path = Path(snapshot["session_path"]).resolve()
        try:
            snapshot["session_display_path"] = resolved_session_path.relative_to(project_root).as_posix()
        except ValueError:
            snapshot["session_display_path"] = snapshot["session_path"]
    else:
        snapshot["session_display_path"] = ""
    snapshot["project_path"] = project_path
    return snapshot


def _build_telemetry_crash_cluster_export(
    project_path: str,
    catalog_path: Optional[str] = None,
    session_path: Optional[str] = None,
    catalog_entries: Optional[List[Dict[str, Any]]] = None,
    events: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    snapshot = _build_telemetry_snapshot(
        project_path,
        catalog_path=catalog_path,
        session_path=session_path,
        catalog_entries=catalog_entries,
        events=events,
    )
    summary = dict(snapshot.get("summary") or {})
    report_content = build_crash_cluster_report(summary)
    return {
        "project_path": project_path,
        "catalog_path": snapshot.get("catalog_display_path") or snapshot.get("catalog_path") or "",
        "session_path": snapshot.get("session_display_path") or snapshot.get("session_path") or "",
        "crash_clusters": list(summary.get("crash_clusters") or []),
        "crash_cluster_count": len(summary.get("crash_clusters") or []),
        "report_name": "telemetry_crash_clusters.md",
        "report_content": report_content,
        "telemetry": snapshot,
    }


def _build_telemetry_crash_dashboard_export(
    project_path: str,
    catalog_path: Optional[str] = None,
    session_path: Optional[str] = None,
    catalog_entries: Optional[List[Dict[str, Any]]] = None,
    events: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    snapshot = _build_telemetry_snapshot(
        project_path,
        catalog_path=catalog_path,
        session_path=session_path,
        catalog_entries=catalog_entries,
        events=events,
    )
    summary = dict(snapshot.get("summary") or {})
    dashboard = dict(summary.get("crash_regression_dashboard") or {})
    report_content = build_crash_regression_dashboard_report(summary)
    return {
        "project_path": project_path,
        "catalog_path": snapshot.get("catalog_display_path") or snapshot.get("catalog_path") or "",
        "session_path": snapshot.get("session_display_path") or snapshot.get("session_path") or "",
        "dashboard": dashboard,
        "report_name": "telemetry_crash_dashboard.md",
        "report_content": report_content,
        "telemetry": snapshot,
    }


def _build_telemetry_retention_dashboard_export(
    project_path: str,
    catalog_path: Optional[str] = None,
    session_path: Optional[str] = None,
    catalog_entries: Optional[List[Dict[str, Any]]] = None,
    events: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    snapshot = _build_telemetry_snapshot(
        project_path,
        catalog_path=catalog_path,
        session_path=session_path,
        catalog_entries=catalog_entries,
        events=events,
    )
    summary = dict(snapshot.get("summary") or {})
    dashboard = dict(summary.get("retention_funnel_dashboard") or {})
    report_content = build_retention_funnel_dashboard_report(summary)
    return {
        "project_path": project_path,
        "catalog_path": snapshot.get("catalog_display_path") or snapshot.get("catalog_path") or "",
        "session_path": snapshot.get("session_display_path") or snapshot.get("session_path") or "",
        "dashboard": dashboard,
        "report_name": "telemetry_retention_dashboard.md",
        "report_content": report_content,
        "telemetry": snapshot,
    }


def _build_telemetry_trend_export(
    project_path: str,
    catalog_path: Optional[str] = None,
    session_path: Optional[str] = None,
    catalog_entries: Optional[List[Dict[str, Any]]] = None,
    events: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    snapshot = _build_telemetry_snapshot(
        project_path,
        catalog_path=catalog_path,
        session_path=session_path,
        catalog_entries=catalog_entries,
        events=events,
    )
    summary = dict(snapshot.get("summary") or {})
    dashboard = dict(summary.get("retention_funnel_trend_dashboard") or {})
    report_content = build_retention_funnel_trend_report(summary)
    return {
        "project_path": project_path,
        "catalog_path": snapshot.get("catalog_display_path") or snapshot.get("catalog_path") or "",
        "session_path": snapshot.get("session_display_path") or snapshot.get("session_path") or "",
        "dashboard": dashboard,
        "report_name": "telemetry_retention_trends.md",
        "report_content": report_content,
        "telemetry": snapshot,
    }


def _build_liveops_impact_export(
    project_path: str,
    catalog_path: Optional[str] = None,
    session_path: Optional[str] = None,
    catalog_entries: Optional[List[Dict[str, Any]]] = None,
    events: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    snapshot = _build_telemetry_snapshot(
        project_path,
        catalog_path=catalog_path,
        session_path=session_path,
        catalog_entries=catalog_entries,
        events=events,
    )
    summary = dict(snapshot.get("summary") or {})
    dashboard = dict(summary.get("liveops_impact_dashboard") or {})
    report_content = build_liveops_impact_report(summary)
    return {
        "project_path": project_path,
        "catalog_path": snapshot.get("catalog_display_path") or snapshot.get("catalog_path") or "",
        "session_path": snapshot.get("session_display_path") or snapshot.get("session_path") or "",
        "dashboard": dashboard,
        "report_name": "liveops_impact_dashboard.md",
        "report_content": report_content,
        "telemetry": snapshot,
    }


def _build_presentation_catalog(project_path: str) -> List[Dict[str, Any]]:
    _, skill = _get_presentation_skill(project_path)
    items: List[Dict[str, Any]] = []
    for presentation_type, schema in PRESENTATION_SCHEMAS.items():
        snapshot = skill.get_snapshot(
            presentation_type=presentation_type,
            manifest_path=schema.get("manifest_path"),
        )
        manifest_res_path = str(snapshot.get("manifest_path") or f"res://{schema['manifest_path']}")
        default_manifest_path = "res://" + str(schema.get("manifest_path") or "").replace("\\", "/")
        items.append({
            "presentation_type": presentation_type,
            "label": PRESENTATION_TYPE_LABELS.get(presentation_type, presentation_type),
            "default_manifest_path": default_manifest_path,
            "sample_entries": list(schema.get("sample_entries") or []),
            "entry_count": snapshot.get("entry_count", 0),
            "generated_path_count": snapshot.get("generated_path_count", 0),
            "manifest_path": manifest_res_path,
            "display_path": manifest_res_path.replace("res://", "", 1),
        })
    return items


def _build_presentation_snapshot(
    project_path: str,
    presentation_type: str,
    manifest_path: Optional[str] = None,
    profile_id: Optional[str] = None,
) -> Dict[str, Any]:
    _, skill = _get_presentation_skill(project_path)
    snapshot = skill.get_snapshot(
        presentation_type=presentation_type,
        manifest_path=manifest_path,
        profile_id=profile_id,
    )
    manifest_res_path = str(snapshot.get("manifest_path") or "")
    snapshot["display_path"] = manifest_res_path.replace("res://", "", 1)
    snapshot["project_path"] = project_path
    return snapshot


def _build_liveops_catalog(project_path: str) -> List[Dict[str, Any]]:
    _, skill = _get_liveops_skill(project_path)
    items: List[Dict[str, Any]] = []
    for liveops_type, schema in LIVEOPS_SCHEMAS.items():
        snapshot = skill.get_snapshot(
            liveops_type=liveops_type,
            manifest_path=schema.get("manifest_path"),
        )
        manifest_res_path = str(snapshot.get("manifest_path") or f"res://{schema['manifest_path']}")
        items.append({
            "liveops_type": liveops_type,
            "label": LIVEOPS_TYPE_LABELS.get(liveops_type, liveops_type),
            "default_manifest_path": "res://" + str(schema.get("manifest_path") or "").replace("\\", "/"),
            "sample_entries": list(schema.get("sample_entries") or []),
            "entry_count": snapshot.get("entry_count", 0),
            "active_entry_count": snapshot.get("active_entry_count", 0),
            "rollout_count": snapshot.get("rollout_count", 0),
            "variant_count": snapshot.get("variant_count", 0),
            "target_metric_count": snapshot.get("target_metric_count", 0),
            "manifest_path": manifest_res_path,
            "display_path": manifest_res_path.replace("res://", "", 1),
        })
    return items


def _build_liveops_snapshot(
    project_path: str,
    liveops_type: str,
    manifest_path: Optional[str] = None,
) -> Dict[str, Any]:
    _, skill = _get_liveops_skill(project_path)
    snapshot = skill.get_snapshot(
        liveops_type=liveops_type,
        manifest_path=manifest_path,
    )
    manifest_res_path = str(snapshot.get("manifest_path") or "")
    snapshot["display_path"] = manifest_res_path.replace("res://", "", 1)
    snapshot["project_path"] = project_path
    return snapshot


def _build_platform_delivery_snapshot(
    project_path: str,
    manifest_path: Optional[str] = None,
) -> Dict[str, Any]:
    _, skill = _get_platform_delivery_skill(project_path)
    snapshot = skill.get_snapshot(manifest_path=manifest_path)
    manifest_res_path = str(snapshot.get("manifest_path") or "")
    snapshot["display_path"] = manifest_res_path.replace("res://", "", 1)
    snapshot["project_path"] = project_path
    return snapshot


def _build_performance_snapshot(
    project_path: str,
    scene_path: Optional[str] = None,
    baseline_path: Optional[str] = None,
    profile_path: Optional[str] = None,
    baseline_metrics: Optional[Dict[str, Any]] = None,
    profile_metrics: Optional[Dict[str, Any]] = None,
    budget_overrides: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    _, skill = _get_performance_skill(project_path)
    snapshot = skill.get_snapshot(
        scene_path=scene_path,
        baseline_path=baseline_path,
        profile_path=profile_path,
        baseline_metrics=baseline_metrics,
        profile_metrics=profile_metrics,
        budget_overrides=budget_overrides,
    )
    runtime_root = REPO_ROOT.resolve()
    baseline_candidate = str(snapshot.get("baseline_path") or "")
    profile_candidate = str(snapshot.get("profile_path") or "")
    if baseline_candidate:
        baseline_resolved = Path(baseline_candidate).resolve()
        try:
            snapshot["baseline_display_path"] = baseline_resolved.relative_to(runtime_root).as_posix()
        except ValueError:
            snapshot["baseline_display_path"] = baseline_candidate
    else:
        snapshot["baseline_display_path"] = ""
    if profile_candidate:
        profile_resolved = Path(profile_candidate).resolve()
        try:
            snapshot["profile_display_path"] = profile_resolved.relative_to(runtime_root).as_posix()
        except ValueError:
            snapshot["profile_display_path"] = profile_candidate
    else:
        snapshot["profile_display_path"] = ""
    snapshot["project_path"] = project_path
    return snapshot


def _build_performance_dashboard_export(
    project_path: str,
    scene_path: Optional[str] = None,
    baseline_path: Optional[str] = None,
    profile_path: Optional[str] = None,
    baseline_metrics: Optional[Dict[str, Any]] = None,
    profile_metrics: Optional[Dict[str, Any]] = None,
    budget_overrides: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    snapshot = _build_performance_snapshot(
        project_path,
        scene_path=scene_path,
        baseline_path=baseline_path,
        profile_path=profile_path,
        baseline_metrics=baseline_metrics,
        profile_metrics=profile_metrics,
        budget_overrides=budget_overrides,
    )
    summary = dict(snapshot.get("summary") or {})
    report_content = build_performance_report(summary) if summary else ""
    return {
        "project_path": project_path,
        "scene_path": snapshot.get("scene_path") or "",
        "baseline_path": snapshot.get("baseline_display_path") or snapshot.get("baseline_path") or "",
        "profile_path": snapshot.get("profile_display_path") or snapshot.get("profile_path") or "",
        "summary": summary,
        "report_name": "performance_dashboard.md",
        "report_content": report_content,
        "performance": snapshot,
    }


def _build_data_table_command(action: str, table_type: str) -> str:
    normalized_action = str(action or "preview").strip().lower()
    normalized_type = str(table_type or "dialogue").strip().lower()
    label = TABLE_TYPE_LABELS.get(normalized_type, normalized_type)
    if normalized_action == "template":
        return f"新建{label}数据表模板"
    if normalized_action == "apply":
        return f"导入{label}数据表"
    if normalized_action == "validate":
        return f"校验{label}数据表"
    return f"预览{label}数据表"


def _build_level_workflow_command(action: str, level_name: str, level_type: str) -> str:
    normalized_action = str(action or "template").strip().lower()
    normalized_level_name = str(level_name or "level_01").strip() or "level_01"
    normalized_level_type = str(level_type or "combat").strip().lower() or "combat"
    level_label = {
        "combat": "战斗",
        "puzzle": "解谜",
        "hub": "Hub",
        "boss": "Boss",
    }.get(normalized_level_type, normalized_level_type)
    if normalized_action == "audit":
        return f"审计{level_label}关卡 {normalized_level_name}"
    if normalized_action == "preview":
        return f"预览{level_label}关卡模板 {normalized_level_name}"
    if normalized_action == "snapshot":
        return f"生成{level_label}关卡快照 {normalized_level_name}"
    if normalized_action == "diff":
        return f"对比{level_label}关卡快照 {normalized_level_name}"
    return f"生成{level_label}关卡模板 {normalized_level_name}"


def _build_gameplay_template_command(action: str, template_id: str) -> str:
    normalized_action = str(action or "preview").strip().lower()
    normalized_template_id = str(template_id or "platformer").strip().lower() or "platformer"
    if normalized_action == "apply":
        return f"应用玩法模板 {normalized_template_id}"
    return f"预览玩法模板 {normalized_template_id}"


def _build_art_asset_command(action: str, asset_type: str, asset_id: str) -> str:
    normalized_action = str(action or "preview").strip().lower()
    normalized_type = str(asset_type or "texture").strip().lower() or "texture"
    normalized_asset_id = str(asset_id or f"{normalized_type}_asset").strip() or f"{normalized_type}_asset"
    label = ART_ASSET_TYPE_LABELS.get(normalized_type, normalized_type)
    if normalized_action == "template":
        return f"新建{label}模板 {normalized_asset_id}"
    if normalized_action == "apply":
        return f"导入{label} {normalized_asset_id}"
    if normalized_action == "validate":
        return f"校验{label} {normalized_asset_id}"
    return f"预览{label} {normalized_asset_id}"


def _build_presentation_command(action: str, presentation_type: str, profile_id: str) -> str:
    normalized_action = str(action or "preview").strip().lower()
    normalized_type = str(presentation_type or "animation").strip().lower() or "animation"
    normalized_profile_id = str(profile_id or f"{normalized_type}_profile").strip() or f"{normalized_type}_profile"
    label = PRESENTATION_TYPE_LABELS.get(normalized_type, normalized_type)
    if normalized_action == "template":
        return f"新建{label}模板 {normalized_profile_id}"
    if normalized_action == "apply":
        return f"应用{label}模板 {normalized_profile_id}"
    if normalized_action == "validate":
        return f"校验{label}模板 {normalized_profile_id}"
    return f"预览{label}模板 {normalized_profile_id}"


def _build_liveops_command(action: str, liveops_type: str, entry_id: str) -> str:
    normalized_action = str(action or "preview").strip().lower()
    normalized_type = str(liveops_type or "remote_config").strip().lower() or "remote_config"
    normalized_entry_id = str(entry_id or f"{normalized_type}_entry").strip() or f"{normalized_type}_entry"
    label = LIVEOPS_TYPE_LABELS.get(normalized_type, normalized_type)
    if normalized_action == "template":
        return f"新建{label}模板 {normalized_entry_id}"
    if normalized_action == "apply":
        return f"应用{label} {normalized_entry_id}"
    if normalized_action == "validate":
        return f"校验{label} {normalized_entry_id}"
    return f"预览{label} {normalized_entry_id}"


def _build_platform_delivery_command(action: str) -> str:
    normalized_action = str(action or "preview").strip().lower()
    if normalized_action == "template":
        return "新建平台交付 baseline"
    if normalized_action == "apply":
        return "应用平台交付 baseline"
    if normalized_action == "validate":
        return "校验平台交付 baseline"
    return "预览平台交付 baseline"


def _build_telemetry_command(action: str) -> str:
    normalized_action = str(action or "analyze").strip().lower()
    if normalized_action == "template":
        return "新建遥测事件字典模板"
    if normalized_action == "apply":
        return "导入遥测会话回流"
    if normalized_action == "validate":
        return "校验遥测事件字典"
    return "分析遥测会话回流"


def _build_performance_command(action: str) -> str:
    normalized_action = str(action or "analyze").strip().lower()
    if normalized_action == "baseline":
        return "保存性能基线"
    if normalized_action == "validate":
        return "校验性能预算"
    return "分析性能画像"

@app.websocket("/ws/plugin")
async def websocket_plugin(websocket: WebSocket, project_path: str = "default"):
    project_path = _normalize_project_key(project_path)
    await websocket.accept()
    manager.connect(project_path, websocket)
    
    # 连接成功后，发送一次当前积压的命令
    queue = manager.get_queue(project_path)
    if queue:
        commands = list(queue)
        queue.clear()
        await manager.dispatch_commands(project_path, commands)

    try:
        while True:
            data = await websocket.receive_json()
            
            # 1. 处理状态同步和事件
            if "state" in data:
                incoming_state = dict(data["state"] or {})
                incoming_events = incoming_state.pop("events", [])
                manager.editor_states[project_path] = _enrich_editor_state(project_path, incoming_state)
                if "screenshot" in incoming_state:
                    manager.last_screenshots[project_path] = incoming_state["screenshot"]
                await manager.broadcast_health_update(project_path)
                if isinstance(incoming_events, list):
                    for event in incoming_events:
                        if isinstance(event, dict):
                            stored_event = manager.record_editor_event(project_path, event)
                            await _broadcast_post_event_updates(project_path, stored_event)
            
            # 2. 处理来自 Godot 插件的交互行为 (user_action)
            if "event" in data and data["event"].get("kind") == "user_action":
                action_data = data["event"]
                task_id = action_data.get("task_id")
                action = action_data.get("action")
                
                if action == "confirm_step" and task_id:
                    step_id = action_data.get("step_id")
                    # 模拟调用确认 API 逻辑
                    router = manager.get_router(project_path)
                    task = router.get_task(task_id)
                    if task:
                        step = next((s for s in task.steps if s.step_id == step_id), None)
                        if step and step.status == TaskStatus.AWAITING_CONFIRMATION:
                            step.status = TaskStatus.PENDING
                            step.requires_confirmation = False
                            task.add_log(f"👤 人工在 Godot 插件中确认了步骤: {step.name}")
                            router.execute_plan(task)
                            await manager.broadcast_task_update(project_path, _serialize_task_for_api(task))
                
                elif action == "rollback" and task_id:
                    router = manager.get_router(project_path)
                    task = router.get_task(task_id)
                    if task:
                        router.rollback(task)
                        await manager.broadcast_task_update(project_path, _serialize_task_for_api(task))

            elif "event" in data:
                stored_event = manager.record_editor_event(project_path, data["event"])
                await _broadcast_post_event_updates(project_path, stored_event)
                
    except WebSocketDisconnect:
        manager.disconnect(project_path, websocket)
        manager.editor_states[project_path] = _enrich_editor_state(project_path, {"is_active": False, "project_path": project_path})
        await manager.broadcast_health_update(project_path)
    except Exception as e:
        print(f"WebSocket error for {project_path}: {e}")
        manager.disconnect(project_path, websocket)
        manager.editor_states[project_path] = _enrich_editor_state(project_path, {"is_active": False, "project_path": project_path})
        await manager.broadcast_health_update(project_path)


@app.websocket("/ws/portal")
async def websocket_portal(websocket: WebSocket, project_path: str = "default"):
    subscribed_project = _normalize_project_key(project_path)
    await websocket.accept()
    manager.connect_portal(subscribed_project, websocket)
    await websocket.send_json({**_build_health_payload(subscribed_project), "type": "health_update"})

    try:
        while True:
            data = await websocket.receive_json()
            if data.get("action") != "subscribe":
                continue

            next_project = _normalize_project_key(data.get("project_path") or "default")
            if next_project == subscribed_project:
                await websocket.send_json({**_build_health_payload(subscribed_project), "type": "health_update"})
                continue

            manager.disconnect_portal(subscribed_project, websocket)
            subscribed_project = next_project
            manager.connect_portal(subscribed_project, websocket)
            await websocket.send_json({**_build_health_payload(subscribed_project), "type": "health_update"})
    except WebSocketDisconnect:
        manager.disconnect_portal(subscribed_project, websocket)
    except Exception:
        manager.disconnect_portal(subscribed_project, websocket)

@app.post("/execute")
async def execute(req: CommandRequest):
    project_path = _normalize_project_key(req.project_path)
    router = manager.get_router(project_path)
    ctx = req.context or {}
    state, launch_info = await _ensure_editor_state(
        project_path,
        auto_launch_editor=req.auto_launch_editor,
        wait_for_editor=req.wait_for_editor,
        editor_timeout=req.editor_timeout,
    )
    ctx["editor_state"] = state
    
    task = router.execute(req.command, ctx)
    if launch_info:
        task.context["editor_launch"] = launch_info

    last_command_id = None
    after_event_id = _last_editor_event_id(project_path) if req.wait_for_editor_event else None
    if task.status in {TaskStatus.SUCCESS, TaskStatus.RUNNING, TaskStatus.WAITING_ACK} and state.get("is_active"):
        queue = manager.get_queue(project_path)
        for art in task.artifacts:
            if art.type == "editor_script" and not art.metadata.get("dispatched"):
                cmd_id = manager.next_command_id(project_path)
                cmd_payload = {
                    "type": "execute_script", 
                    "script": art.content, 
                    "command_id": cmd_id,
                    "task_id": task.task_id,
                    "step_id": art.metadata.get("step_id"),
                }
                manager.register_command(project_path, cmd_payload)
                queue.append(cmd_payload)
                art.metadata["dispatched"] = True
                last_command_id = cmd_id
        
        if queue and manager.active_websockets.get(project_path):
            commands = list(queue)
            queue.clear()
            await manager.dispatch_commands(project_path, commands)

    payload = _serialize_task_for_api(task)
    # 广播更新给插件 UI
    await manager.broadcast_task_update(project_path, payload)
    
    if req.wait_for_editor_event and last_command_id:
        editor_event = await _wait_for_editor_event(
            project_path,
            timeout=req.editor_event_timeout,
            after_event_id=after_event_id,
            command_id=last_command_id,
        )
        latest_task = _safe_get_router_task(router, task.task_id) or task
        payload = _serialize_task_for_api(latest_task)
        payload["editor_event"] = editor_event
        payload.setdefault("context", {})["editor_event"] = editor_event
    return payload


@app.post("/plan")
async def plan(req: PlanRequest):
    project_path = _normalize_project_key(req.project_path)
    router = manager.get_router(project_path)
    ctx = req.context or {}
    state = _get_editor_state_for_project(project_path)
    ctx["editor_state"] = state
    task = router.plan(req.command, ctx)
    return _serialize_task_for_api(task)


@app.post("/execute-plan")
async def execute_plan(req: ExecutePlanRequest):
    project_path = _normalize_project_key(req.project_path)
    router = manager.get_router(project_path)
    state, launch_info = await _ensure_editor_state(
        project_path,
        auto_launch_editor=req.auto_launch_editor,
        wait_for_editor=req.wait_for_editor,
        editor_timeout=req.editor_timeout,
    )
    task = _build_task_from_editable_plan(router, req, state)
    task = router.execute_plan(task)
    _close_completed_review_followups(task)
    if launch_info:
        task.context["editor_launch"] = launch_info

    last_command_id = None
    if task.status in {TaskStatus.SUCCESS, TaskStatus.RUNNING, TaskStatus.WAITING_ACK} and state.get("is_active"):
        queue = manager.get_queue(project_path)
        for art in task.artifacts:
            if art.type == "editor_script" and not art.metadata.get("dispatched"):
                cmd_id = manager.next_command_id(project_path)
                cmd_payload = {
                    "type": "execute_script", 
                    "script": art.content, 
                    "id": task.task_id,
                    "task_id": task.task_id,
                    "command_id": cmd_id,
                    "step_id": art.metadata.get("step_id"),
                }
                manager.register_command(project_path, cmd_payload)
                queue.append(cmd_payload)
                art.metadata["dispatched"] = True
                last_command_id = cmd_id

        if queue and manager.active_websockets.get(project_path):
            commands = list(queue)
            queue.clear()
            await manager.dispatch_commands(project_path, commands)

    payload = _serialize_task_for_api(task)
    if req.wait_for_editor_event and last_command_id:
        editor_event = await _wait_for_editor_event(
            project_path,
            timeout=req.editor_event_timeout,
            command_id=last_command_id,
        )
        latest_task = _safe_get_router_task(router, task.task_id) or task
        payload = _serialize_task_for_api(latest_task)
        payload["editor_event"] = editor_event
        payload.setdefault("context", {})["editor_event"] = editor_event
    return payload


@app.get("/data-tables")
async def list_data_tables(project_path: str = "default"):
    project_path = _normalize_project_key(project_path)
    return {
        "project_path": project_path,
        "default_table_type": "dialogue",
        "items": _build_data_table_catalog(project_path),
    }


@app.get("/art-assets/profiles")
async def list_art_asset_profiles(
    project_path: str = "default",
    asset_type: str = "",
    asset_id: str = "",
    manifest_path: str = "",
):
    project_path = _normalize_project_key(project_path)
    normalized_type = str(asset_type or "").strip().lower()
    if normalized_type:
        payload = _build_art_asset_snapshot(
            project_path,
            asset_type=normalized_type,
            manifest_path=manifest_path or None,
            asset_id=asset_id or None,
        )
        payload["project_root"] = str(_resolve_project_root(project_path))
        return payload

    items = _build_art_asset_catalog(project_path)
    return {
        "project_path": project_path,
        "project_root": str(_resolve_project_root(project_path)),
        "default_asset_type": "texture",
        "count": len(items),
        "items": items,
    }


@app.get("/genre-templates")
async def list_genre_templates(project_path: str = "default"):
    project_path = _normalize_project_key(project_path)
    project_root = _resolve_project_root(project_path)
    registry = GenreTemplateRegistry(project_path=str(project_root))
    return {
        "project_path": project_path,
        "project_root": str(project_root),
        "default_template_id": DEFAULT_GENRE_TEMPLATE_ID,
        "items": registry.list_genre_templates(),
    }


@app.get("/genre-templates/marketplace")
async def get_genre_template_marketplace(project_path: str = "default"):
    project_path = _normalize_project_key(project_path)
    project_root = _resolve_project_root(project_path)
    registry = GenreTemplateRegistry(project_path=str(project_root))
    payload = registry.build_marketplace_manifest()
    payload["project_path"] = project_path
    payload["project_root"] = str(project_root)
    return payload


@app.get("/gameplay/templates")
async def list_gameplay_templates(project_path: str = "default", template_id: str = ""):
    project_path = _normalize_project_key(project_path)
    project_root = _resolve_project_root(project_path)
    registry = GenreTemplateRegistry(project_path=str(project_root))
    normalized_template_id = str(template_id or "").strip()
    if normalized_template_id:
        payload = registry.build_gameplay_template_snapshot(normalized_template_id)
        if not payload:
            raise HTTPException(status_code=404, detail="Gameplay template not found")
        payload["project_path"] = project_path
        payload["project_root"] = str(project_root)
        return payload

    items = []
    for template in registry.list_genre_templates():
        snapshot = registry.build_gameplay_template_snapshot(template["template_id"])
        if snapshot:
            items.append(snapshot)
    return {
        "project_path": project_path,
        "project_root": str(project_root),
        "count": len(items),
        "items": items,
    }


@app.get("/presentation/profiles")
async def list_presentation_profiles(
    project_path: str = "default",
    presentation_type: str = "",
    profile_id: str = "",
    manifest_path: str = "",
):
    project_path = _normalize_project_key(project_path)
    normalized_type = str(presentation_type or "").strip().lower()
    if normalized_type:
        payload = _build_presentation_snapshot(
            project_path,
            presentation_type=normalized_type,
            manifest_path=manifest_path or None,
            profile_id=profile_id or None,
        )
        payload["project_root"] = str(_resolve_project_root(project_path))
        return payload

    items = _build_presentation_catalog(project_path)
    return {
        "project_path": project_path,
        "project_root": str(_resolve_project_root(project_path)),
        "default_presentation_type": "animation",
        "count": len(items),
        "items": items,
    }


@app.get("/liveops/profiles")
async def list_liveops_profiles(
    project_path: str = "default",
    liveops_type: str = "",
    manifest_path: str = "",
):
    project_path = _normalize_project_key(project_path)
    normalized_type = str(liveops_type or "").strip().lower()
    if normalized_type:
        payload = _build_liveops_snapshot(
            project_path,
            liveops_type=normalized_type,
            manifest_path=manifest_path or None,
        )
        payload["project_root"] = str(_resolve_project_root(project_path))
        return payload

    items = _build_liveops_catalog(project_path)
    return {
        "project_path": project_path,
        "project_root": str(_resolve_project_root(project_path)),
        "default_liveops_type": "remote_config",
        "count": len(items),
        "items": items,
    }


@app.get("/platform-delivery/profile")
async def get_platform_delivery_profile(
    project_path: str = "default",
    manifest_path: str = "",
):
    project_path = _normalize_project_key(project_path)
    return _build_platform_delivery_snapshot(
        project_path,
        manifest_path=manifest_path or None,
    )


@app.get("/contracts/versions")
async def get_contract_versions(project_path: str = "default"):
    project_path = _normalize_project_key(project_path)
    payload = build_contract_catalog()
    payload["project_path"] = project_path
    return payload


@app.get("/migrations/status")
async def get_migration_status(project_path: str = "default"):
    project_path = _normalize_project_key(project_path)
    project_root = _resolve_project_root(project_path)
    payload = MigrationRunner(project_root, runtime_root=REPO_ROOT).build_migration_status()
    payload["project_path"] = project_path
    return payload


@app.post("/migrations/apply")
async def apply_migrations(req: Optional[MigrationApplyRequest] = None):
    req = req or MigrationApplyRequest()
    project_path = _normalize_project_key(req.project_path)
    project_root = _resolve_project_root(project_path)
    payload = MigrationRunner(project_root, runtime_root=REPO_ROOT).apply_pending()
    payload["project_path"] = project_path
    return payload


@app.get("/quality/dashboard")
async def get_quality_dashboard(project_path: str = "default"):
    project_path = _normalize_project_key(project_path)
    project_root = _resolve_project_root(project_path)
    payload = build_quality_dashboard(project_root, runtime_root=REPO_ROOT)
    payload["project_path"] = project_path
    return payload


@app.get("/governance/policy")
async def get_governance_policy(project_path: str = "default"):
    project_path = _normalize_project_key(project_path)
    payload = build_governance_policy()
    payload["project_path"] = project_path
    return payload


@app.get("/governance/admission")
async def get_governance_admission(
    project_path: str = "default",
    change_type: str = "feature",
):
    project_path = _normalize_project_key(project_path)
    project_root = _resolve_project_root(project_path)
    payload = build_change_admission(project_root, runtime_root=REPO_ROOT, change_type=change_type)
    payload["project_path"] = project_path
    return payload


@app.post("/governance/admission")
async def post_governance_admission(req: GovernanceAdmissionRequest):
    project_path = _normalize_project_key(req.project_path)
    project_root = _resolve_project_root(project_path)
    payload = build_change_admission(
        project_root,
        runtime_root=REPO_ROOT,
        change_type=req.change_type,
        evidence=req.evidence,
        changed_paths=req.changed_paths,
        notes=req.notes,
    )
    payload["project_path"] = project_path
    return payload


@app.post("/governance/enforce")
async def post_governance_enforce(req: GovernanceEnforceRequest):
    project_path = _normalize_project_key(req.project_path)
    project_root = _resolve_project_root(project_path)
    payload = build_governance_enforcement(
        project_root,
        runtime_root=REPO_ROOT,
        change_type=req.change_type,
        evidence=req.evidence,
        changed_paths=req.changed_paths,
        notes=req.notes,
        mode=req.mode,
        fail_on_warnings=req.fail_on_warnings,
    )
    payload["project_path"] = project_path
    return payload


@app.get("/production/scenarios")
async def get_production_scenarios(project_path: str = "default"):
    project_path = _normalize_project_key(project_path)
    payload = list_production_scenarios()
    payload["project_path"] = project_path
    return payload


@app.post("/production/validate")
async def post_production_validate(req: ProductionValidateRequest):
    project_path = _normalize_project_key(req.project_path)
    project_root = _resolve_project_root(project_path)
    payload = build_production_readiness(
        project_root,
        runtime_root=REPO_ROOT,
        scenario_id=req.scenario_id,
        evidence=req.evidence,
        changed_paths=req.changed_paths,
        notes=req.notes,
        mode=req.mode,
        fail_on_warnings=req.fail_on_warnings,
    )
    payload["project_path"] = project_path
    return payload


@app.get("/build-run/matrix")
async def get_build_run_matrix(
    project_path: str = "default",
    manifest_path: str = "",
    scenario_ids: str = "",
    mode: str = "strict",
    fail_on_warnings: bool = False,
):
    project_path = _normalize_project_key(project_path)
    selected_scenario_ids = [item.strip() for item in scenario_ids.split(",") if item.strip()] if scenario_ids else []
    return _build_build_run_matrix_snapshot(
        project_path,
        manifest_path=manifest_path or None,
        scenario_ids=selected_scenario_ids or None,
        mode=mode,
        fail_on_warnings=fail_on_warnings,
    )


@app.post("/build-run/matrix")
async def post_build_run_matrix(req: BuildRunMatrixRequest):
    project_path = _normalize_project_key(req.project_path)
    return _build_build_run_matrix_snapshot(
        project_path,
        manifest_path=req.manifest_path or None,
        scenario_ids=req.scenario_ids or None,
        mode=req.mode,
        fail_on_warnings=req.fail_on_warnings,
    )


@app.get("/release-capability-registry")
async def get_release_capability_registry(
    project_path: str = "default",
    registry_path: str = DEFAULT_RELEASE_CAPABILITY_REGISTRY_PATH,
):
    project_path = _normalize_project_key(project_path)
    return _build_release_capability_registry_snapshot(
        project_path,
        registry_path=registry_path or DEFAULT_RELEASE_CAPABILITY_REGISTRY_PATH,
    )


@app.get("/release-capability-registry/report")
async def get_release_capability_registry_report(
    project_path: str = "default",
    registry_path: str = DEFAULT_RELEASE_CAPABILITY_REGISTRY_PATH,
):
    project_path = _normalize_project_key(project_path)
    return _build_release_capability_registry_export(
        project_path,
        registry_path=registry_path or DEFAULT_RELEASE_CAPABILITY_REGISTRY_PATH,
    )


@app.get("/release-capability-policy")
async def get_release_capability_policy(
    project_path: str = "default",
    registry_path: str = DEFAULT_RELEASE_CAPABILITY_REGISTRY_PATH,
    route_kind: str = "portal",
    target_channel: str = "staging",
    target_environment: str = "",
    actor_id: str = "",
):
    project_path = _normalize_project_key(project_path)
    return _build_release_capability_policy_snapshot(
        project_path,
        registry_path=registry_path or DEFAULT_RELEASE_CAPABILITY_REGISTRY_PATH,
        route_kind=route_kind or "portal",
        target_channel=target_channel or "staging",
        target_environment=target_environment,
        actor_id=actor_id,
    )


@app.get("/release-capability-policy/report")
async def get_release_capability_policy_report(
    project_path: str = "default",
    registry_path: str = DEFAULT_RELEASE_CAPABILITY_REGISTRY_PATH,
    route_kind: str = "portal",
    target_channel: str = "staging",
    target_environment: str = "",
    actor_id: str = "",
):
    project_path = _normalize_project_key(project_path)
    return _build_release_capability_policy_export(
        project_path,
        registry_path=registry_path or DEFAULT_RELEASE_CAPABILITY_REGISTRY_PATH,
        route_kind=route_kind or "portal",
        target_channel=target_channel or "staging",
        target_environment=target_environment,
        actor_id=actor_id,
    )


@app.get("/release-delivery-readiness")
async def get_release_delivery_readiness(
    project_path: str = "default",
    target_channel: str = "release",
    target_environment: str = "",
    artifact_dir: str = DEFAULT_RELEASE_DELIVERY_ARTIFACT_DIR,
    workflow: str = DEFAULT_RELEASE_LIVE_DISPATCH_WORKFLOW,
    repo: str = "",
    ref: str = "",
    token_env_names: str = ",".join(DEFAULT_RELEASE_LIVE_DISPATCH_TOKEN_ENV_NAMES),
):
    project_path = _normalize_project_key(project_path)
    return _build_release_delivery_readiness_snapshot(
        project_path,
        target_channel=target_channel or "release",
        target_environment=target_environment,
        artifact_dir=artifact_dir or DEFAULT_RELEASE_DELIVERY_ARTIFACT_DIR,
        workflow=workflow or DEFAULT_RELEASE_LIVE_DISPATCH_WORKFLOW,
        repo=repo,
        ref=ref,
        token_env_names=token_env_names,
    )


@app.get("/release-delivery-readiness/report")
async def get_release_delivery_readiness_report(
    project_path: str = "default",
    target_channel: str = "release",
    target_environment: str = "",
    artifact_dir: str = DEFAULT_RELEASE_DELIVERY_ARTIFACT_DIR,
    workflow: str = DEFAULT_RELEASE_LIVE_DISPATCH_WORKFLOW,
    repo: str = "",
    ref: str = "",
    token_env_names: str = ",".join(DEFAULT_RELEASE_LIVE_DISPATCH_TOKEN_ENV_NAMES),
):
    project_path = _normalize_project_key(project_path)
    return _build_release_delivery_readiness_export(
        project_path,
        target_channel=target_channel or "release",
        target_environment=target_environment,
        artifact_dir=artifact_dir or DEFAULT_RELEASE_DELIVERY_ARTIFACT_DIR,
        workflow=workflow or DEFAULT_RELEASE_LIVE_DISPATCH_WORKFLOW,
        repo=repo,
        ref=ref,
        token_env_names=token_env_names,
    )


@app.get("/release-candidate/checklist")
async def get_release_candidate_checklist(
    project_path: str = "default",
    release_manifest_path: str = "",
    mode: str = "strict",
    fail_on_warnings: bool = False,
):
    project_path = _normalize_project_key(project_path)
    project_root = _resolve_project_root(project_path)
    payload = build_release_candidate_checklist(
        project_root,
        runtime_root=REPO_ROOT,
        release_manifest_path=release_manifest_path,
        mode=mode,
        fail_on_warnings=fail_on_warnings,
    )
    payload["project_path"] = project_path
    return payload


@app.post("/release-candidate/checklist")
async def post_release_candidate_checklist(req: ReleaseCandidateChecklistRequest):
    project_path = _normalize_project_key(req.project_path)
    project_root = _resolve_project_root(project_path)
    payload = build_release_candidate_checklist(
        project_root,
        runtime_root=REPO_ROOT,
        release_manifest_path=req.release_manifest_path,
        evidence=req.evidence,
        changed_paths=req.changed_paths,
        mode=req.mode,
        fail_on_warnings=req.fail_on_warnings,
    )
    payload["project_path"] = project_path
    return payload


@app.get("/release-promotion/plan")
async def get_release_promotion_plan(
    project_path: str = "default",
    target_channel: str = "staging",
    target_environment: str = "",
    release_manifest_path: str = "",
    approvers: str = "",
    providers: str = "",
    mode: str = "strict",
    fail_on_warnings: bool = False,
):
    project_path = _normalize_project_key(project_path)
    approver_list = [item.strip() for item in approvers.split(",") if item.strip()] if approvers else []
    provider_list = [item.strip() for item in providers.split(",") if item.strip()] if providers else []
    return _build_release_promotion_plan_snapshot(
        project_path,
        target_channel=target_channel or "staging",
        target_environment=target_environment,
        release_manifest_path=release_manifest_path,
        approvers=approver_list or None,
        providers=provider_list or None,
        mode=mode,
        fail_on_warnings=fail_on_warnings,
    )


@app.post("/release-promotion/plan")
async def post_release_promotion_plan(req: ReleasePromotionPlanRequest):
    project_path = _normalize_project_key(req.project_path)
    return _build_release_promotion_plan_snapshot(
        project_path,
        target_channel=req.target_channel or "staging",
        target_environment=req.target_environment,
        release_manifest_path=req.release_manifest_path,
        approvers=req.approvers or None,
        providers=req.providers or None,
        mode=req.mode,
        fail_on_warnings=req.fail_on_warnings,
    )


@app.get("/release-promotion/evidence-report")
async def get_release_promotion_evidence_report(
    project_path: str = "default",
    target_channel: str = "staging",
    target_environment: str = "",
    release_manifest_path: str = "",
    approvers: str = "",
    providers: str = "",
    mode: str = "strict",
    fail_on_warnings: bool = False,
):
    project_path = _normalize_project_key(project_path)
    approver_list = [item.strip() for item in approvers.split(",") if item.strip()] if approvers else []
    provider_list = [item.strip() for item in providers.split(",") if item.strip()] if providers else []
    return _build_release_promotion_evidence_export(
        project_path,
        target_channel=target_channel or "staging",
        target_environment=target_environment,
        release_manifest_path=release_manifest_path,
        approvers=approver_list or None,
        providers=provider_list or None,
        mode=mode,
        fail_on_warnings=fail_on_warnings,
    )


@app.get("/release-promotion/deployment-rehearsal")
async def get_release_promotion_deployment_rehearsal(
    project_path: str = "default",
    target_channel: str = "staging",
    target_environment: str = "",
    release_manifest_path: str = "",
    approvers: str = "",
    providers: str = "",
    mode: str = "strict",
    fail_on_warnings: bool = False,
):
    project_path = _normalize_project_key(project_path)
    approver_list = [item.strip() for item in approvers.split(",") if item.strip()] if approvers else []
    provider_list = [item.strip() for item in providers.split(",") if item.strip()] if providers else []
    return _build_release_promotion_deployment_export(
        project_path,
        target_channel=target_channel or "staging",
        target_environment=target_environment,
        release_manifest_path=release_manifest_path,
        approvers=approver_list or None,
        providers=provider_list or None,
        mode=mode,
        fail_on_warnings=fail_on_warnings,
    )


@app.get("/release-promotion/review-bundle")
async def get_release_promotion_review_bundle(
    project_path: str = "default",
    target_channel: str = "staging",
    target_environment: str = "",
    release_manifest_path: str = "",
    approvers: str = "",
    providers: str = "",
    mode: str = "strict",
    fail_on_warnings: bool = False,
):
    project_path = _normalize_project_key(project_path)
    approver_list = [item.strip() for item in approvers.split(",") if item.strip()] if approvers else []
    provider_list = [item.strip() for item in providers.split(",") if item.strip()] if providers else []
    return _build_release_promotion_review_bundle_export(
        project_path,
        target_channel=target_channel or "staging",
        target_environment=target_environment,
        release_manifest_path=release_manifest_path,
        approvers=approver_list or None,
        providers=provider_list or None,
        mode=mode,
        fail_on_warnings=fail_on_warnings,
    )


@app.get("/release-promotion/rollback-rehearsal")
async def get_release_promotion_rollback_rehearsal(
    project_path: str = "default",
    target_channel: str = "staging",
    target_environment: str = "",
    release_manifest_path: str = "",
    approvers: str = "",
    providers: str = "",
    mode: str = "strict",
    fail_on_warnings: bool = False,
):
    project_path = _normalize_project_key(project_path)
    approver_list = [item.strip() for item in approvers.split(",") if item.strip()] if approvers else []
    provider_list = [item.strip() for item in providers.split(",") if item.strip()] if providers else []
    return _build_release_promotion_rollback_export(
        project_path,
        target_channel=target_channel or "staging",
        target_environment=target_environment,
        release_manifest_path=release_manifest_path,
        approvers=approver_list or None,
        providers=provider_list or None,
        mode=mode,
        fail_on_warnings=fail_on_warnings,
    )


@app.get("/release-promotion/history")
async def get_release_promotion_history(
    project_path: str = "default",
    history_path: str = "",
    decision: str = "",
    target_channel: str = "",
    executed_by: str = "",
    live_ci_status: str = "",
    dispatch_status: str = "",
    dispatch_follow_up: str = "",
    dispatch_run_status: str = "",
    dispatch_run_conclusion: str = "",
    failed_workflow_step: str = "",
    delivery_readiness_status: str = "",
    readiness_action: str = "",
    offset: int = 0,
    limit: int = 20,
):
    project_path = _normalize_project_key(project_path)
    return _build_release_promotion_history_snapshot(
        project_path,
        history_path=history_path or DEFAULT_RELEASE_PROMOTION_HISTORY_PATH,
        decision=decision,
        target_channel=target_channel,
        executed_by=executed_by,
        live_ci_status=live_ci_status,
        dispatch_status=dispatch_status,
        dispatch_follow_up=dispatch_follow_up,
        dispatch_run_status=dispatch_run_status,
        dispatch_run_conclusion=dispatch_run_conclusion,
        failed_workflow_step=failed_workflow_step,
        delivery_readiness_status=delivery_readiness_status,
        readiness_action=readiness_action,
        offset=offset,
        limit=limit,
    )


@app.get("/release-promotion/history-report")
async def get_release_promotion_history_report(
    project_path: str = "default",
    history_path: str = "",
    decision: str = "",
    target_channel: str = "",
    executed_by: str = "",
    live_ci_status: str = "",
    dispatch_status: str = "",
    dispatch_follow_up: str = "",
    dispatch_run_status: str = "",
    dispatch_run_conclusion: str = "",
    failed_workflow_step: str = "",
    delivery_readiness_status: str = "",
    readiness_action: str = "",
    offset: int = 0,
    limit: int = 20,
):
    project_path = _normalize_project_key(project_path)
    return _build_release_promotion_history_export(
        project_path,
        history_path=history_path or DEFAULT_RELEASE_PROMOTION_HISTORY_PATH,
        decision=decision,
        target_channel=target_channel,
        executed_by=executed_by,
        live_ci_status=live_ci_status,
        dispatch_status=dispatch_status,
        dispatch_follow_up=dispatch_follow_up,
        dispatch_run_status=dispatch_run_status,
        dispatch_run_conclusion=dispatch_run_conclusion,
        failed_workflow_step=failed_workflow_step,
        delivery_readiness_status=delivery_readiness_status,
        readiness_action=readiness_action,
        offset=offset,
        limit=limit,
    )


@app.post("/release-promotion/record")
async def post_release_promotion_record(req: ReleasePromotionRecordRequest, request: Request):
    project_path = _normalize_project_key(req.project_path)
    project_root = _resolve_project_root(project_path)
    request_auth = _build_release_write_request_auth(
        request,
        project_root=project_root,
        actor_id=req.executed_by,
        action="promotion_record",
        target_channel=req.target_channel or "staging",
        target_environment=req.target_environment,
    )
    if str(request_auth.get("status") or "") == "blocked":
        raise HTTPException(status_code=400, detail=f"release write request authentication failed: {request_auth.get('reason') or 'blocked'}")
    try:
        payload = record_release_promotion_event(
            project_root,
            runtime_root=REPO_ROOT,
            history_path=req.history_path or DEFAULT_RELEASE_PROMOTION_HISTORY_PATH,
            target_channel=req.target_channel or "staging",
            target_environment=req.target_environment,
            release_manifest_path=req.release_manifest_path,
            approvers=req.approvers or None,
            providers=req.providers or None,
            mode=req.mode,
            fail_on_warnings=req.fail_on_warnings,
            decision=req.decision,
            executed_by=req.executed_by,
            note=req.note,
            signoff_source=req.signoff_source,
            request_auth=request_auth,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    payload["project_path"] = project_path
    return payload


@app.get("/release-execution/status")
async def get_release_execution_status(
    project_path: str = "default",
    status_path: str = "",
    channels_path: str = "",
    history_path: str = "",
    operation: str = "",
    target_channel: str = "",
    executed_by: str = "",
    offset: int = 0,
    limit: int = 20,
):
    project_path = _normalize_project_key(project_path)
    return _build_release_execution_status_snapshot(
        project_path,
        status_path=status_path or DEFAULT_RELEASE_EXECUTION_STATUS_PATH,
        channels_path=channels_path or DEFAULT_RELEASE_CHANNELS_PATH,
        history_path=history_path or DEFAULT_RELEASE_PROMOTION_HISTORY_PATH,
        operation=operation,
        target_channel=target_channel,
        executed_by=executed_by,
        offset=offset,
        limit=limit,
    )


@app.get("/release-execution/report")
async def get_release_execution_report(
    project_path: str = "default",
    status_path: str = "",
    channels_path: str = "",
    history_path: str = "",
    operation: str = "",
    target_channel: str = "",
    executed_by: str = "",
    offset: int = 0,
    limit: int = 20,
):
    project_path = _normalize_project_key(project_path)
    return _build_release_execution_report_export(
        project_path,
        status_path=status_path or DEFAULT_RELEASE_EXECUTION_STATUS_PATH,
        channels_path=channels_path or DEFAULT_RELEASE_CHANNELS_PATH,
        history_path=history_path or DEFAULT_RELEASE_PROMOTION_HISTORY_PATH,
        operation=operation,
        target_channel=target_channel,
        executed_by=executed_by,
        offset=offset,
        limit=limit,
    )


@app.get("/release-live-ci/summary")
async def get_release_live_ci_summary(
    project_path: str = "default",
    artifact_dir: str = "logs/reports/release_live_ci",
):
    project_path = _normalize_project_key(project_path)
    return _build_release_live_ci_summary_snapshot(
        project_path,
        artifact_dir=artifact_dir or "logs/reports/release_live_ci",
    )


@app.get("/release-artifact-manifest")
async def get_release_artifact_manifest(
    project_path: str = "default",
    artifact_dir: str = "logs/reports/release_live_ci",
):
    project_path = _normalize_project_key(project_path)
    return _build_release_artifact_manifest_snapshot(
        project_path,
        artifact_dir=artifact_dir or "logs/reports/release_live_ci",
    )


@app.get("/release-live-ci/events")
async def get_release_live_ci_events(
    project_path: str = "default",
    artifact_dir: str = "logs/reports/release_live_ci",
    event_type: str = "",
    status: str = "",
    step_id: str = "",
    lane_id: str = "",
    offset: int = 0,
    limit: int = 20,
):
    project_path = _normalize_project_key(project_path)
    return _build_release_live_ci_event_stream_snapshot(
        project_path,
        artifact_dir=artifact_dir or "logs/reports/release_live_ci",
        event_type=event_type,
        status=status,
        step_id=step_id,
        lane_id=lane_id,
        offset=offset,
        limit=limit,
    )


@app.get("/release-live-ci/summary-report")
async def get_release_live_ci_summary_report(
    project_path: str = "default",
    artifact_dir: str = "logs/reports/release_live_ci",
):
    project_path = _normalize_project_key(project_path)
    return _build_release_live_ci_summary_export(
        project_path,
        artifact_dir=artifact_dir or "logs/reports/release_live_ci",
    )


@app.get("/release-live-ci/dispatch-audit")
async def get_release_live_ci_dispatch_audit(
    project_path: str = "default",
    artifact_dir: str = "logs/reports/release_live_ci",
):
    project_path = _normalize_project_key(project_path)
    return _build_release_live_ci_dispatch_audit_snapshot(
        project_path,
        artifact_dir=artifact_dir or "logs/reports/release_live_ci",
    )


@app.get("/release-live-ci/dispatch-preflight")
async def get_release_live_ci_dispatch_preflight(
    project_path: str = "default",
    repo: str = "",
    ref: str = "",
    workflow: str = DEFAULT_RELEASE_LIVE_DISPATCH_WORKFLOW,
    runner_labels: str = '["self-hosted","windows","godot"]',
    target_channel: str = "staging",
    target_environment: str = "staging",
    release_manifest_path: str = "api_server/static/dist/web_release_validation_ci/release_manifest.json",
    runner_profile_path: str = "deployment/release_live_runner_profile.json",
    approvers: str = "",
    providers: str = "codex,openai_api",
    artifact_dir: str = "logs/reports/release_live_ci",
    fail_on_warnings: bool = False,
    token_env_names: str = ",".join(DEFAULT_RELEASE_LIVE_DISPATCH_TOKEN_ENV_NAMES),
):
    project_path = _normalize_project_key(project_path)
    return _build_release_live_ci_dispatch_preflight_snapshot(
        project_path,
        repo=repo,
        ref=ref,
        workflow=workflow,
        runner_labels=runner_labels,
        target_channel=target_channel,
        target_environment=target_environment,
        release_manifest_path=release_manifest_path,
        runner_profile_path=runner_profile_path,
        approvers=approvers,
        providers=providers,
        artifact_dir=artifact_dir,
        fail_on_warnings=fail_on_warnings,
        token_env_names=token_env_names,
    )


@app.post("/release-live-ci/dispatch")
async def post_release_live_ci_dispatch(req: ReleaseLiveCiDispatchRequest, request: Request):
    project_path = _normalize_project_key(req.project_path)
    project_root = _resolve_project_root(project_path)
    normalized_artifact_dir = req.artifact_dir or "logs/reports/release_live_ci"
    preflight = _build_release_live_ci_dispatch_preflight_snapshot(
        project_path,
        repo=req.repo,
        ref=req.ref,
        workflow=req.workflow or DEFAULT_RELEASE_LIVE_DISPATCH_WORKFLOW,
        runner_labels=req.runner_labels,
        target_channel=req.target_channel or "staging",
        target_environment=req.target_environment or "staging",
        release_manifest_path=req.release_manifest_path or "api_server/static/dist/web_release_validation_ci/release_manifest.json",
        runner_profile_path=req.runner_profile_path or "deployment/release_live_runner_profile.json",
        approvers=",".join(req.approvers or []),
        providers=",".join(req.providers or []),
        artifact_dir=normalized_artifact_dir,
        fail_on_warnings=req.fail_on_warnings,
        token_env_names=",".join(req.token_env_names or list(DEFAULT_RELEASE_LIVE_DISPATCH_TOKEN_ENV_NAMES)),
    )
    request_auth = _build_release_write_request_auth(
        request,
        project_root=project_root,
        actor_id=req.triggered_by,
        action="release_execution",
        target_channel=req.target_channel or "staging",
        target_environment=req.target_environment,
    )
    if str(request_auth.get("status") or "") == "blocked":
        audit_payload = write_release_live_dispatch_audit(
            project_root,
            artifact_dir=normalized_artifact_dir,
            preflight=preflight,
            request_auth=request_auth,
            triggered_by=req.triggered_by,
            error=f"release write request authentication failed: {request_auth.get('reason') or 'blocked'}",
            error_type="request_auth_blocked",
        )
        raise HTTPException(status_code=400, detail=f"release write request authentication failed: {request_auth.get('reason') or 'blocked'}")
    try:
        payload = dispatch_release_live_gates_request(
            project_root,
            repo=req.repo,
            ref=req.ref,
            workflow=req.workflow or DEFAULT_RELEASE_LIVE_DISPATCH_WORKFLOW,
            runner_labels=req.runner_labels,
            target_channel=req.target_channel or "staging",
            target_environment=req.target_environment or "staging",
            release_manifest_path=req.release_manifest_path or "api_server/static/dist/web_release_validation_ci/release_manifest.json",
            runner_profile_path=req.runner_profile_path or "deployment/release_live_runner_profile.json",
            approvers=req.approvers,
            providers=req.providers,
            artifact_dir=req.artifact_dir or "logs/reports/release_live_ci",
            fail_on_warnings=req.fail_on_warnings,
            wait=req.wait,
            poll_interval=req.poll_interval,
            wait_timeout=req.wait_timeout,
            dispatch_timeout=req.dispatch_timeout,
            token_env_names=req.token_env_names,
        )
        audit_payload = write_release_live_dispatch_audit(
            project_root,
            artifact_dir=normalized_artifact_dir,
            preflight=payload.get("preflight") or preflight,
            dispatch_result=payload,
            request_auth=request_auth,
            triggered_by=req.triggered_by,
        )
    except ValueError as exc:
        write_release_live_dispatch_audit(
            project_root,
            artifact_dir=normalized_artifact_dir,
            preflight=preflight,
            request_auth=request_auth,
            triggered_by=req.triggered_by,
            error=str(exc),
            error_type=type(exc).__name__,
        )
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        detail = str(exc)
        write_release_live_dispatch_audit(
            project_root,
            artifact_dir=normalized_artifact_dir,
            preflight=preflight,
            request_auth=request_auth,
            triggered_by=req.triggered_by,
            error=detail,
            error_type=type(exc).__name__,
        )
        status_code = 400 if any(marker in detail for marker in [
            "preflight blocked",
            "No GitHub token found",
            "Cannot infer owner/repo",
            "runner_labels",
        ]) else 502
        raise HTTPException(status_code=status_code, detail=detail) from exc
    payload = normalize_release_live_dispatch_audit(audit_payload)
    payload["project_path"] = project_path
    payload["request_auth"] = request_auth
    return payload


@app.post("/release-execution/run")
async def post_release_execution_run(req: ReleaseExecutionRunRequest, request: Request):
    project_path = _normalize_project_key(req.project_path)
    project_root = _resolve_project_root(project_path)
    request_auth = _build_release_write_request_auth(
        request,
        project_root=project_root,
        actor_id=req.executed_by,
        action="release_execution",
        target_channel=req.target_channel or "staging",
        target_environment=req.target_environment,
    )
    if str(request_auth.get("status") or "") == "blocked":
        raise HTTPException(status_code=400, detail=f"release write request authentication failed: {request_auth.get('reason') or 'blocked'}")
    try:
        payload = run_release_execution(
            project_root,
            runtime_root=REPO_ROOT,
            status_path=req.status_path or DEFAULT_RELEASE_EXECUTION_STATUS_PATH,
            channels_path=req.channels_path or DEFAULT_RELEASE_CHANNELS_PATH,
            history_path=req.history_path or DEFAULT_RELEASE_PROMOTION_HISTORY_PATH,
            target_channel=req.target_channel or "staging",
            target_environment=req.target_environment,
            release_manifest_path=req.release_manifest_path,
            approvers=req.approvers or None,
            providers=req.providers or None,
            mode=req.mode,
            fail_on_warnings=req.fail_on_warnings,
            operation=req.operation,
            rollout_percentage=req.rollout_percentage,
            executed_by=req.executed_by,
            note=req.note,
            request_auth=request_auth,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    payload["project_path"] = project_path
    return payload


@app.post("/release-execution/rollback")
async def post_release_execution_rollback(req: ReleaseExecutionRollbackRequest, request: Request):
    project_path = _normalize_project_key(req.project_path)
    project_root = _resolve_project_root(project_path)
    request_auth = _build_release_write_request_auth(
        request,
        project_root=project_root,
        actor_id=req.executed_by,
        action="release_execution",
        target_channel=req.target_channel or "staging",
        target_environment=req.target_environment,
    )
    if str(request_auth.get("status") or "") == "blocked":
        raise HTTPException(status_code=400, detail=f"release write request authentication failed: {request_auth.get('reason') or 'blocked'}")
    try:
        payload = rollback_release_execution(
            project_root,
            runtime_root=REPO_ROOT,
            status_path=req.status_path or DEFAULT_RELEASE_EXECUTION_STATUS_PATH,
            channels_path=req.channels_path or DEFAULT_RELEASE_CHANNELS_PATH,
            history_path=req.history_path or DEFAULT_RELEASE_PROMOTION_HISTORY_PATH,
            target_channel=req.target_channel or "staging",
            target_environment=req.target_environment,
            release_manifest_path=req.release_manifest_path,
            approvers=req.approvers or None,
            providers=req.providers or None,
            mode=req.mode,
            fail_on_warnings=req.fail_on_warnings,
            executed_by=req.executed_by,
            note=req.note,
            rollback_target_url=req.rollback_target_url,
            request_auth=request_auth,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    payload["project_path"] = project_path
    return payload


@app.get("/outsource-delivery/gate")
async def get_outsource_delivery_gate(
    project_path: str = "default",
    manifest_path: str = "",
    package_root: str = "",
    required_license_names: str = "",
    mode: str = "strict",
    fail_on_warnings: bool = False,
):
    project_path = _normalize_project_key(project_path)
    licenses = [item.strip() for item in required_license_names.split(",") if item.strip()] if required_license_names else []
    return _build_outsource_delivery_gate_snapshot(
        project_path,
        manifest_path=manifest_path or None,
        package_root=package_root or None,
        required_license_names=licenses,
        mode=mode,
        fail_on_warnings=fail_on_warnings,
    )


@app.post("/outsource-delivery/gate")
async def post_outsource_delivery_gate(req: OutsourceDeliveryGateRequest):
    project_path = _normalize_project_key(req.project_path)
    return _build_outsource_delivery_gate_snapshot(
        project_path,
        manifest_path=req.manifest_path or None,
        package_root=req.package_root or None,
        required_license_names=req.required_license_names,
        mode=req.mode,
        fail_on_warnings=req.fail_on_warnings,
    )


@app.get("/asset-reviews/workflow")
async def get_asset_review_workflow(
    project_path: str = "default",
    asset_type: str = "outsource",
    asset_manifest_path: str = "",
    review_manifest_path: str = "",
    asset_ids: str = "",
    mode: str = "strict",
    fail_on_warnings: bool = False,
):
    project_path = _normalize_project_key(project_path)
    selected_asset_ids = [item.strip() for item in asset_ids.split(",") if item.strip()] if asset_ids else []
    return _build_asset_review_workflow_snapshot(
        project_path,
        asset_type=asset_type or "outsource",
        asset_manifest_path=asset_manifest_path or None,
        review_manifest_path=review_manifest_path or None,
        asset_ids=selected_asset_ids or None,
        mode=mode,
        fail_on_warnings=fail_on_warnings,
    )


@app.post("/asset-reviews/manage")
async def post_asset_review_manage(req: AssetReviewManageRequest):
    project_path = _normalize_project_key(req.project_path)
    action = str(req.action or "snapshot").strip().lower() or "snapshot"
    if action == "snapshot":
        return _build_asset_review_workflow_snapshot(
            project_path,
            asset_type=req.asset_type or "outsource",
            asset_manifest_path=req.asset_manifest_path or None,
            review_manifest_path=req.review_manifest_path or None,
            asset_ids=req.asset_ids or None,
            mode=req.mode,
            fail_on_warnings=req.fail_on_warnings,
        )
    if action != "apply":
        raise HTTPException(status_code=400, detail="Unsupported asset review action")

    project_root = _resolve_project_root(project_path)
    try:
        payload = apply_asset_review_decision(
            project_root,
            runtime_root=REPO_ROOT,
            asset_type=req.asset_type or "outsource",
            asset_manifest_path=req.asset_manifest_path or "",
            review_manifest_path=req.review_manifest_path or DEFAULT_ASSET_REVIEW_MANIFEST_PATH,
            asset_ids=req.asset_ids or None,
            reviewer=req.reviewer,
            review_status=req.review_status,
            review_note=req.review_note,
            mode=req.mode,
            fail_on_warnings=req.fail_on_warnings,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    payload["project_path"] = project_path
    return payload


@app.get("/scene-ownership/board")
async def get_scene_ownership_board(
    project_path: str = "default",
    board_path: str = "",
    scene_paths: str = "",
    scene_category: str = "",
    mode: str = "strict",
    fail_on_warnings: bool = False,
):
    project_path = _normalize_project_key(project_path)
    selected_scene_paths = [item.strip() for item in scene_paths.split(",") if item.strip()] if scene_paths else []
    return _build_scene_ownership_board_snapshot(
        project_path,
        board_path=board_path or None,
        scene_paths=selected_scene_paths or None,
        scene_category=scene_category,
        mode=mode,
        fail_on_warnings=fail_on_warnings,
    )


@app.post("/scene-ownership/manage")
async def post_scene_ownership_manage(req: SceneOwnershipManageRequest):
    project_path = _normalize_project_key(req.project_path)
    action = str(req.action or "snapshot").strip().lower() or "snapshot"
    if action == "snapshot":
        return _build_scene_ownership_board_snapshot(
            project_path,
            board_path=req.board_path or None,
            scene_paths=req.scene_paths or None,
            scene_category=req.scene_category,
            mode=req.mode,
            fail_on_warnings=req.fail_on_warnings,
        )

    project_root = _resolve_project_root(project_path)
    normalized_owner = req.owner
    normalized_feature_id = req.feature_id
    normalized_lock_state = req.lock_state
    clear_owner = req.clear_owner
    clear_feature_id = req.clear_feature_id
    if action == "claim":
        normalized_lock_state = req.lock_state or "locked"
    elif action == "release":
        normalized_lock_state = "available"
        clear_owner = True
        clear_feature_id = True
    elif action != "apply":
        raise HTTPException(status_code=400, detail="Unsupported scene ownership action")

    try:
        payload = apply_scene_ownership_update(
            project_root,
            runtime_root=REPO_ROOT,
            board_path=req.board_path or DEFAULT_SCENE_OWNERSHIP_BOARD_PATH,
            scene_paths=req.scene_paths or None,
            scene_category=req.scene_category,
            owner=normalized_owner,
            feature_id=normalized_feature_id,
            lock_state=normalized_lock_state,
            note=req.note,
            clear_owner=clear_owner,
            clear_feature_id=clear_feature_id,
            mode=req.mode,
            fail_on_warnings=req.fail_on_warnings,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    payload["project_path"] = project_path
    return payload


@app.get("/agent-compat/providers")
async def get_agent_compat_providers(project_path: str = "default"):
    project_path = _normalize_project_key(project_path)
    payload = list_agent_provider_profiles()
    payload["project_path"] = project_path
    return payload


@app.get("/agent-compat/matrix")
async def get_agent_compat_matrix(project_path: str = "default", providers: str = ""):
    project_path = _normalize_project_key(project_path)
    project_root = _resolve_project_root(project_path)
    provider_list = [item.strip() for item in providers.split(",") if item.strip()] if providers else []
    payload = build_agent_compatibility_matrix(project_root, runtime_root=REPO_ROOT, providers=provider_list or None)
    payload["project_path"] = project_path
    return payload


@app.post("/agent-compat/matrix")
async def post_agent_compat_matrix(req: AgentCompatibilityRequest):
    project_path = _normalize_project_key(req.project_path)
    project_root = _resolve_project_root(project_path)
    payload = build_agent_compatibility_matrix(
        project_root,
        runtime_root=REPO_ROOT,
        providers=req.providers or None,
    )
    payload["project_path"] = project_path
    return payload


@app.get("/data-tables/table")
async def get_data_table(
    project_path: str = "default",
    table_type: str = "dialogue",
    table_path: str = "",
):
    project_path = _normalize_project_key(project_path)
    return _build_data_table_snapshot(
        project_path,
        table_type=table_type,
        table_path=table_path or None,
    )


@app.post("/levels/manage")
async def manage_level_workflow(req: LevelWorkflowManageRequest):
    project_path = _normalize_project_key(req.project_path)
    router, skill = _get_level_workflow_skill(project_path)
    task = Task(
        prompt=_build_level_workflow_command(req.action, req.level_name, req.level_type),
        status=TaskStatus.RUNNING,
        context={
            "level_workflow_action": req.action,
            "level_name": req.level_name,
            "level_type": req.level_type,
            "editor_state": _get_editor_state_for_project(project_path),
        },
    )

    params = req.model_dump()
    params.pop("project_path", None)
    result = skill.execute(task, params)
    task.artifacts.extend(result.artifacts)
    for log_line in result.logs:
        task.add_log(log_line)
    record_skill_result_on_task(task, dict(result.metadata or {}).get("skill_result"))
    task.status = TaskStatus.SUCCESS if result.success else TaskStatus.FAILED
    if result.success:
        task.add_log(f"SUCCESS: {result.message}")
    else:
        task.add_log(f"ERROR: {result.message}")
        if result.error:
            task.add_log(f"DETAIL: {result.error}")

    task.context = build_task_feature_context(
        prompt=task.prompt,
        task_id=task.task_id,
        task_status=task.status,
        context=task.context,
        steps=task.steps,
        artifacts=task.artifacts,
        message=result.message,
    )
    _persist_router_task(router, task)

    payload = _serialize_task_for_api(task)
    payload["level_workflow"] = result.data or {
        "level_name": task.context.get("level_name"),
        "scene_path": task.context.get("level_scene_path"),
        "manifest_path": task.context.get("level_manifest_path"),
        "schema_version": task.context.get("level_schema_version"),
    }
    await manager.broadcast_task_update(project_path, payload)
    return payload


@app.post("/gameplay/manage")
async def manage_gameplay_template(req: GameplayTemplateManageRequest):
    project_path = _normalize_project_key(req.project_path)
    router, skill = _get_gameplay_template_skill(project_path)
    blueprint_manager = getattr(router, "blueprint_manager", None)
    blueprint = getattr(blueprint_manager, "blueprint", None)
    project_template = dict(getattr(blueprint, "project_template", {}) or {}) if blueprint else {}
    resolved_template_id = (
        req.template_id
        or req.game_genre
        or project_template.get("template_id")
        or DEFAULT_GENRE_TEMPLATE_ID
    )
    task = Task(
        prompt=_build_gameplay_template_command(req.action, resolved_template_id),
        status=TaskStatus.RUNNING,
        context={
            "gameplay_action": req.action,
            "gameplay_template_id": resolved_template_id,
            "project_template": project_template,
            "blueprint_manager": blueprint_manager,
            "editor_state": _get_editor_state_for_project(project_path),
        },
    )

    params = req.model_dump()
    params.pop("project_path", None)
    result = skill.execute(task, params)
    task.artifacts.extend(result.artifacts)
    for log_line in result.logs:
        task.add_log(log_line)
    record_skill_result_on_task(task, dict(result.metadata or {}).get("skill_result"))
    task.status = TaskStatus.SUCCESS if result.success else TaskStatus.FAILED
    if result.success:
        task.add_log(f"SUCCESS: {result.message}")
    else:
        task.add_log(f"ERROR: {result.message}")
        if result.error:
            task.add_log(f"DETAIL: {result.error}")

    task.context = build_task_feature_context(
        prompt=task.prompt,
        task_id=task.task_id,
        task_status=task.status,
        context=task.context,
        steps=task.steps,
        artifacts=task.artifacts,
        message=result.message,
    )
    _persist_router_task(router, task)

    payload = _serialize_task_for_api(task)
    payload["gameplay_template"] = (result.data or {}).get("gameplay_template") if isinstance(result.data, dict) else None
    if payload["gameplay_template"] is None:
        payload["gameplay_template"] = {
            "template_id": task.context.get("gameplay_template_id"),
            "system_count": task.context.get("gameplay_system_count", 0),
            "starter_gameplay_systems": list(task.context.get("starter_gameplay_systems") or []),
        }
    await manager.broadcast_task_update(project_path, payload)
    return payload


@app.post("/art-assets/manage")
async def manage_art_asset_pipeline(req: ArtAssetManageRequest):
    project_path = _normalize_project_key(req.project_path)
    router, skill = _get_art_asset_skill(project_path)
    resolved_type = str(req.asset_type or "texture").strip().lower() or "texture"
    resolved_asset_id = (
        req.asset_id
        or (req.entries[0].get("asset_id") if req.entries and isinstance(req.entries[0], dict) else None)
        or f"{resolved_type}_asset"
    )
    task = Task(
        prompt=_build_art_asset_command(req.action, resolved_type, str(resolved_asset_id)),
        status=TaskStatus.RUNNING,
        context={
            "art_asset_action": req.action,
            "art_asset_type": resolved_type,
            "art_asset_id": resolved_asset_id,
            "editor_state": _get_editor_state_for_project(project_path),
        },
    )

    params = req.model_dump()
    params.pop("project_path", None)
    result = skill.execute(task, params)
    task.artifacts.extend(result.artifacts)
    for log_line in result.logs:
        task.add_log(log_line)
    record_skill_result_on_task(task, dict(result.metadata or {}).get("skill_result"))
    task.status = TaskStatus.SUCCESS if result.success else TaskStatus.FAILED
    if result.success:
        task.add_log(f"SUCCESS: {result.message}")
    else:
        task.add_log(f"ERROR: {result.message}")
        if result.error:
            task.add_log(f"DETAIL: {result.error}")

    task.context = build_task_feature_context(
        prompt=task.prompt,
        task_id=task.task_id,
        task_status=task.status,
        context=task.context,
        steps=task.steps,
        artifacts=task.artifacts,
        message=result.message,
    )
    _persist_router_task(router, task)

    payload = _serialize_task_for_api(task)
    payload["art_asset_profile"] = (result.data or {}).get("art_asset_profile") if isinstance(result.data, dict) else None
    if payload["art_asset_profile"] is None:
        payload["art_asset_profile"] = {
            "asset_type": task.context.get("art_asset_type"),
            "manifest_path": task.context.get("art_asset_manifest_path"),
            "entry_count": task.context.get("art_asset_entry_count", 0),
            "copied_target_count": task.context.get("art_asset_copy_count", 0),
        }
    await manager.broadcast_task_update(project_path, payload)
    return payload


@app.post("/presentation/manage")
async def manage_presentation_pipeline(req: PresentationManageRequest):
    project_path = _normalize_project_key(req.project_path)
    router, skill = _get_presentation_skill(project_path)
    blueprint_manager = getattr(router, "blueprint_manager", None)
    resolved_type = str(req.presentation_type or "animation").strip().lower() or "animation"
    resolved_profile_id = (
        req.profile_id
        or (req.entries[0].get("profile_id") if req.entries and isinstance(req.entries[0], dict) else None)
        or f"{resolved_type}_profile"
    )
    task = Task(
        prompt=_build_presentation_command(req.action, resolved_type, str(resolved_profile_id)),
        status=TaskStatus.RUNNING,
        context={
            "presentation_action": req.action,
            "presentation_type": resolved_type,
            "presentation_profile_id": resolved_profile_id,
            "blueprint_manager": blueprint_manager,
            "editor_state": _get_editor_state_for_project(project_path),
        },
    )

    params = req.model_dump()
    params.pop("project_path", None)
    result = skill.execute(task, params)
    task.artifacts.extend(result.artifacts)
    for log_line in result.logs:
        task.add_log(log_line)
    record_skill_result_on_task(task, dict(result.metadata or {}).get("skill_result"))
    task.status = TaskStatus.SUCCESS if result.success else TaskStatus.FAILED
    if result.success:
        task.add_log(f"SUCCESS: {result.message}")
    else:
        task.add_log(f"ERROR: {result.message}")
        if result.error:
            task.add_log(f"DETAIL: {result.error}")

    task.context = build_task_feature_context(
        prompt=task.prompt,
        task_id=task.task_id,
        task_status=task.status,
        context=task.context,
        steps=task.steps,
        artifacts=task.artifacts,
        message=result.message,
    )
    _persist_router_task(router, task)

    payload = _serialize_task_for_api(task)
    payload["presentation_profile"] = (result.data or {}).get("presentation_profile") if isinstance(result.data, dict) else None
    if payload["presentation_profile"] is None:
        payload["presentation_profile"] = {
            "presentation_type": task.context.get("presentation_type"),
            "manifest_path": task.context.get("presentation_manifest_path"),
            "entry_count": task.context.get("presentation_entry_count", 0),
            "generated_path_count": task.context.get("presentation_generated_path_count", 0),
            "generated_paths": list(task.context.get("presentation_generated_paths") or []),
        }
    await manager.broadcast_task_update(project_path, payload)
    return payload


@app.post("/liveops/manage")
async def manage_liveops_pipeline(req: LiveOpsManageRequest):
    project_path = _normalize_project_key(req.project_path)
    router, skill = _get_liveops_skill(project_path)
    resolved_type = str(req.liveops_type or "remote_config").strip().lower() or "remote_config"
    resolved_entry_id = (
        req.entry_id
        or (
            req.entries[0].get("config_key")
            if req.entries and isinstance(req.entries[0], dict) and resolved_type == "remote_config"
            else None
        )
        or (
            req.entries[0].get("experiment_id")
            if req.entries and isinstance(req.entries[0], dict) and resolved_type == "experiment_catalog"
            else None
        )
        or f"{resolved_type}_entry"
    )
    task = Task(
        prompt=_build_liveops_command(req.action, resolved_type, str(resolved_entry_id)),
        status=TaskStatus.RUNNING,
        context={
            "liveops_action": req.action,
            "liveops_type": resolved_type,
            "liveops_entry_id": resolved_entry_id,
            "editor_state": _get_editor_state_for_project(project_path),
        },
    )

    params = req.model_dump()
    params.pop("project_path", None)
    result = skill.execute(task, params)
    task.artifacts.extend(result.artifacts)
    for log_line in result.logs:
        task.add_log(log_line)
    record_skill_result_on_task(task, dict(result.metadata or {}).get("skill_result"))
    task.status = TaskStatus.SUCCESS if result.success else TaskStatus.FAILED
    if result.success:
        task.add_log(f"SUCCESS: {result.message}")
    else:
        task.add_log(f"ERROR: {result.message}")
        if result.error:
            task.add_log(f"DETAIL: {result.error}")

    task.context = build_task_feature_context(
        prompt=task.prompt,
        task_id=task.task_id,
        task_status=task.status,
        context=task.context,
        steps=task.steps,
        artifacts=task.artifacts,
        message=result.message,
    )
    _persist_router_task(router, task)

    payload = _serialize_task_for_api(task)
    payload["liveops_profile"] = (result.data or {}).get("liveops_profile") if isinstance(result.data, dict) else None
    if payload["liveops_profile"] is None:
        payload["liveops_profile"] = {
            "liveops_type": task.context.get("liveops_type"),
            "manifest_path": task.context.get("liveops_manifest_path"),
            "entry_count": task.context.get("liveops_entry_count", 0),
            "active_entry_count": task.context.get("liveops_active_entry_count", 0),
            "rollout_count": task.context.get("liveops_rollout_count", 0),
            "variant_count": task.context.get("liveops_variant_count", 0),
            "target_metric_count": task.context.get("liveops_target_metric_count", 0),
        }
    await manager.broadcast_task_update(project_path, payload)
    return payload


@app.post("/platform-delivery/manage")
async def manage_platform_delivery(req: PlatformDeliveryManageRequest):
    project_path = _normalize_project_key(req.project_path)
    router, skill = _get_platform_delivery_skill(project_path)
    task = Task(
        prompt=_build_platform_delivery_command(req.action),
        status=TaskStatus.RUNNING,
        context={
            "platform_delivery_action": req.action,
            "editor_state": _get_editor_state_for_project(project_path),
        },
    )

    params = req.model_dump()
    params.pop("project_path", None)
    result = skill.execute(task, params)
    task.artifacts.extend(result.artifacts)
    for log_line in result.logs:
        task.add_log(log_line)
    record_skill_result_on_task(task, dict(result.metadata or {}).get("skill_result"))
    task.status = TaskStatus.SUCCESS if result.success else TaskStatus.FAILED
    if result.success:
        task.add_log(f"SUCCESS: {result.message}")
    else:
        task.add_log(f"ERROR: {result.message}")
        if result.error:
            task.add_log(f"DETAIL: {result.error}")

    task.context = build_task_feature_context(
        prompt=task.prompt,
        task_id=task.task_id,
        task_status=task.status,
        context=task.context,
        steps=task.steps,
        artifacts=task.artifacts,
        message=result.message,
    )
    _persist_router_task(router, task)

    payload = _serialize_task_for_api(task)
    payload["platform_delivery_profile"] = (result.data or {}).get("platform_delivery_profile") if isinstance(result.data, dict) else None
    if payload["platform_delivery_profile"] is None:
        payload["platform_delivery_profile"] = _build_platform_delivery_snapshot(
            project_path,
            manifest_path=req.manifest_path,
        )
    await manager.broadcast_task_update(project_path, payload)
    return payload


@app.post("/data-tables/manage")
async def manage_data_table(req: DataTableManageRequest):
    project_path = _normalize_project_key(req.project_path)
    router, _ = _get_data_table_skill(project_path)
    context = {
        "data_table_action": req.action,
        "data_table_type": req.table_type,
    }
    if req.table_path:
        context["data_table_path"] = req.table_path
    if req.content not in (None, ""):
        context["data_table_content"] = req.content
    if req.rows:
        context["data_table_rows"] = req.rows

    task = router.execute(_build_data_table_command(req.action, req.table_type), context)
    payload = _serialize_task_for_api(task)
    payload["data_table"] = _build_data_table_snapshot(
        project_path,
        table_type=req.table_type,
        table_path=req.table_path,
        rows=req.rows if req.rows else None,
        content=req.content,
    )
    await manager.broadcast_task_update(project_path, payload)
    return payload


@app.get("/telemetry")
async def get_telemetry(project_path: str = "default"):
    project_path = _normalize_project_key(project_path)
    return {
        "project_path": project_path,
        "default_catalog_path": DEFAULT_TELEMETRY_CATALOG_PATH,
        "telemetry": _build_telemetry_snapshot(project_path),
    }


@app.get("/telemetry/catalog")
async def get_telemetry_catalog(
    project_path: str = "default",
    catalog_path: str = "",
    session_path: str = "",
):
    project_path = _normalize_project_key(project_path)
    return _build_telemetry_snapshot(
        project_path,
        catalog_path=catalog_path or None,
        session_path=session_path or None,
    )


@app.get("/telemetry/crash-clusters")
async def get_telemetry_crash_clusters(
    project_path: str = "default",
    catalog_path: str = "",
    session_path: str = "",
):
    project_path = _normalize_project_key(project_path)
    return _build_telemetry_crash_cluster_export(
        project_path,
        catalog_path=catalog_path or None,
        session_path=session_path or None,
    )


@app.get("/telemetry/crash-dashboard")
async def get_telemetry_crash_dashboard(
    project_path: str = "default",
    catalog_path: str = "",
    session_path: str = "",
):
    project_path = _normalize_project_key(project_path)
    return _build_telemetry_crash_dashboard_export(
        project_path,
        catalog_path=catalog_path or None,
        session_path=session_path or None,
    )


@app.get("/telemetry/retention-dashboard")
async def get_telemetry_retention_dashboard(
    project_path: str = "default",
    catalog_path: str = "",
    session_path: str = "",
):
    project_path = _normalize_project_key(project_path)
    return _build_telemetry_retention_dashboard_export(
        project_path,
        catalog_path=catalog_path or None,
        session_path=session_path or None,
    )


@app.get("/telemetry/trends")
async def get_telemetry_trends(
    project_path: str = "default",
    catalog_path: str = "",
    session_path: str = "",
):
    project_path = _normalize_project_key(project_path)
    return _build_telemetry_trend_export(
        project_path,
        catalog_path=catalog_path or None,
        session_path=session_path or None,
    )


@app.get("/liveops/impact-dashboard")
async def get_liveops_impact_dashboard(
    project_path: str = "default",
    catalog_path: str = "",
    session_path: str = "",
):
    project_path = _normalize_project_key(project_path)
    return _build_liveops_impact_export(
        project_path,
        catalog_path=catalog_path or None,
        session_path=session_path or None,
    )


@app.post("/telemetry/manage")
async def manage_telemetry(req: TelemetryManageRequest):
    project_path = _normalize_project_key(req.project_path)
    router, _ = _get_telemetry_skill(project_path)
    context = {
        "telemetry_action": req.action,
    }
    if req.catalog_path:
        context["telemetry_catalog_path"] = req.catalog_path
    if req.session_path:
        context["telemetry_session_path"] = req.session_path
    if req.catalog_entries:
        context["telemetry_catalog_entries"] = req.catalog_entries
    if req.events:
        context["telemetry_events"] = req.events

    task = router.execute(_build_telemetry_command(req.action), context)
    payload = _serialize_task_for_api(task)
    payload["telemetry"] = _build_telemetry_snapshot(
        project_path,
        catalog_path=req.catalog_path,
        session_path=req.session_path,
        catalog_entries=req.catalog_entries if req.catalog_entries else None,
        events=req.events if req.events else None,
    )
    await manager.broadcast_task_update(project_path, payload)
    return payload


@app.get("/performance")
async def get_performance(project_path: str = "default"):
    project_path = _normalize_project_key(project_path)
    return {
        "project_path": project_path,
        "default_baseline_dir": DEFAULT_PERFORMANCE_BASELINE_DIR,
        "performance": _build_performance_snapshot(project_path),
    }


@app.get("/performance/profile")
async def get_performance_profile(
    project_path: str = "default",
    scene_path: str = "",
    baseline_path: str = "",
    profile_path: str = "",
):
    project_path = _normalize_project_key(project_path)
    return _build_performance_snapshot(
        project_path,
        scene_path=scene_path or None,
        baseline_path=baseline_path or None,
        profile_path=profile_path or None,
    )


@app.get("/performance/dashboard")
async def get_performance_dashboard(
    project_path: str = "default",
    scene_path: str = "",
    baseline_path: str = "",
    profile_path: str = "",
):
    project_path = _normalize_project_key(project_path)
    return _build_performance_dashboard_export(
        project_path,
        scene_path=scene_path or None,
        baseline_path=baseline_path or None,
        profile_path=profile_path or None,
    )


@app.post("/performance/manage")
async def manage_performance(req: PerformanceManageRequest):
    project_path = _normalize_project_key(req.project_path)
    router, _ = _get_performance_skill(project_path)
    context = {
        "performance_action": req.action,
    }
    if req.scene_path:
        context["performance_scene_path"] = req.scene_path
    if req.baseline_path:
        context["performance_baseline_path"] = req.baseline_path
    if req.profile_path:
        context["performance_profile_path"] = req.profile_path
    if req.baseline_metrics:
        context["performance_baseline_metrics"] = req.baseline_metrics
    if req.profile_metrics:
        context["performance_profile_metrics"] = req.profile_metrics
    if req.budget_overrides:
        context["performance_budget"] = req.budget_overrides

    task = router.execute(_build_performance_command(req.action), context)
    payload = _serialize_task_for_api(task)
    payload["performance"] = _build_performance_snapshot(
        project_path,
        scene_path=req.scene_path,
        baseline_path=req.baseline_path,
        profile_path=req.profile_path,
        baseline_metrics=req.baseline_metrics if req.baseline_metrics else None,
        profile_metrics=req.profile_metrics if req.profile_metrics else None,
        budget_overrides=req.budget_overrides if req.budget_overrides else None,
    )
    await manager.broadcast_task_update(project_path, payload)
    return payload


@app.get("/mcp/onboarding")
async def get_mcp_onboarding(project_path: str = "default"):
    project_path = _normalize_project_key(project_path)
    return _build_mcp_onboarding_payload(project_path)


@app.get("/mcp/remote-manifest")
async def get_mcp_remote_manifest(project_path: str = "default"):
    project_path = _normalize_project_key(project_path)
    return _build_remote_mcp_manifest_payload(project_path)


@app.post("/mcp/install-codex-skill")
async def install_codex_skill(req: InstallCodexSkillRequest):
    project_path = _normalize_project_key(req.project_path)
    source_dir = _resolve_repo_skill_dir()
    target_dir = _resolve_global_skill_dir()
    if not source_dir.exists():
        raise HTTPException(status_code=404, detail="Repo skill package not found")

    changed = _sync_directory(source_dir, target_dir)
    payload = _build_mcp_onboarding_payload(project_path)
    payload["install_result"] = {
        "ok": _directories_match(source_dir, target_dir),
        "changed": changed,
        "source": str(source_dir),
        "destination": str(target_dir),
    }
    return payload


@app.post("/editor/launch")
async def launch_editor(req: LaunchEditorRequest):
    project_path = _normalize_project_key(req.project_path)
    state, launch_info = await _ensure_editor_state(
        project_path,
        auto_launch_editor=True,
        wait_for_editor=req.wait_for_editor,
        editor_timeout=req.editor_timeout,
        scene_path=req.scene_path,
    )
    response = {
        "ok": True,
        "project_path": project_path,
        "editor_online": bool(state.get("is_active")),
        "launch": launch_info or manager.last_editor_launches.get(project_path),
        "editor_state": _compact_editor_state(state),
    }
    await manager.broadcast_health_update(project_path)
    return response


@app.post("/editor/operation")
async def editor_operation(req: EditorOperationRequest):
    project_path = _normalize_project_key(req.project_path)
    operation = str(req.operation or "").strip().lower()
    if operation not in EDITOR_OPERATION_ALLOWED:
        raise HTTPException(status_code=400, detail="Unsupported editor operation")
    _validate_editor_operation_request(req, operation)

    state, launch_info = await _ensure_editor_state(
        project_path,
        auto_launch_editor=req.auto_launch_editor,
        wait_for_editor=req.wait_for_editor,
        editor_timeout=req.editor_timeout,
    )
    if not state.get("is_active"):
        raise HTTPException(status_code=409, detail="Editor is offline")

    after_event_id = _last_editor_event_id(project_path) if req.wait_for_editor_event else None
    cmd_id = manager.next_command_id(project_path)
    command = _build_editor_operation_command(req, operation, cmd_id)
    await _queue_and_dispatch_editor_command(project_path, command)
    audit = dict(command.get("audit") or {})

    response: Dict[str, Any] = {
        "ok": True,
        "project_path": project_path,
        "schema_version": EDITOR_OPERATION_SCHEMA_VERSION,
        "operation": operation,
        "command_id": cmd_id,
        "audit": audit,
        "queued": True,
        "message": f"已发送到 Godot 实时操作: {operation}",
    }
    if launch_info:
        response["launch"] = launch_info
    if req.wait_for_editor_event:
        response["editor_event"] = await _wait_for_editor_event(
            project_path,
            timeout=req.editor_event_timeout,
            after_event_id=after_event_id,
            kind="editor_operation",
            command_id=cmd_id,
        )
    return response


@app.get("/history")
async def list_history(
    project_path: str = "default",
    limit: int = 30,
    offset: int = 0,
    feature_status: str = "",
    feature_id: str = "",
    owner: str = "",
):
    project_path = _normalize_project_key(project_path)
    router = manager.get_router(project_path)
    clamped_limit = max(1, min(limit, 100))
    clamped_offset = max(0, min(offset, 5000))
    status_query = _normalize_history_query(feature_status)
    feature_id_query = _normalize_history_query(feature_id)
    owner_query = _normalize_history_query(owner)
    if status_query and status_query not in {"pending_review", "pending_acceptance", "approved", "returned"}:
        raise HTTPException(status_code=400, detail="Unsupported feature_status")

    has_filters = bool(status_query or feature_id_query or owner_query)
    requested_end = clamped_offset + clamped_limit
    scan_limit = requested_end if not has_filters else max(requested_end, min(max(requested_end * 5, 100), 500))
    history = _load_history_items(
        router,
        None if isinstance(getattr(router, "tasks", None), dict) else scan_limit,
    )
    if has_filters:
        history = [
            item for item in history
            if _history_item_matches(item, status_query, feature_id_query, owner_query)
        ]
    matched_count = len(history)
    has_more = clamped_offset + clamped_limit < matched_count
    prev_offset = max(0, clamped_offset - clamped_limit) if clamped_offset > 0 else None
    next_offset = clamped_offset + clamped_limit if has_more else None
    history = history[clamped_offset:clamped_offset + clamped_limit]
    return {
        "project_path": project_path,
        "items": history,
        "count": len(history),
        "matched_count": matched_count,
        "offset": clamped_offset,
        "limit": clamped_limit,
        "has_more": has_more,
        "next_offset": next_offset,
        "prev_offset": prev_offset,
        "filters": {
            "feature_status": status_query,
            "feature_id": feature_id_query,
            "owner": owner_query,
        },
    }


@app.post("/history/{task_id}/rollback")
async def rollback_task(task_id: str, project_path: str = "default"):
    project_path = _normalize_project_key(project_path)
    router = manager.get_router(project_path)
    
    # 在历史记录中查找任务
    history = router.get_history(limit=100)
    task_data = next((t for t in history if t.get("task_id") == task_id), None)
    if not task_data:
        raise HTTPException(status_code=404, detail="Task not found in recent history")
    
    # 重构 Task 对象以进行回滚
    from agent_system.models import Task, TaskStatus, TaskStep, Artifact, Backup
    task = Task(
        task_id=task_data["task_id"],
        prompt=task_data["prompt"],
        context=_append_feature_lifecycle_event(
            task_data.get("context", {}),
            "rollback",
            "任务从历史记录触发回滚",
        ),
        status=TaskStatus(task_data["status"])
    )
    task.backups = [
        Backup(original_path=b["original_path"], backup_path=b["backup_path"])
        for b in task_data.get("backups", [])
    ]
    task.steps = [
        TaskStep(
            name=s["name"],
            description=s["description"],
            role=s["role"],
            depends_on=s.get("depends_on", []),
            status=TaskStatus(s.get("status", "pending")),
            metadata=s.get("metadata", {}),
        )
        for s in task_data.get("steps", [])
    ]
    task.artifacts = [
        Artifact(
            name=a["name"],
            path=a["path"],
            type=a["type"],
            content=a.get("content"),
            metadata=a.get("metadata", {}),
        )
        for a in task_data.get("artifacts", [])
    ]
    
    try:
        router.rollback(task)
        task.context = build_task_feature_context(
            prompt=task.prompt,
            task_id=task.task_id,
            task_status=task.status,
            context=task.context,
            steps=task.steps,
            artifacts=task.artifacts,
            message=task.message,
        )
        _persist_router_task(router, task)
        payload = _serialize_task_for_api(task)
        return {"ok": True, "message": f"任务 {task_id} 已成功回滚", "task": payload}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"回滚失败: {str(e)}")


@app.post("/history/{task_id}/retry")
async def retry_task(task_id: str, project_path: str = "default"):
    project_path = _normalize_project_key(project_path)
    router = manager.get_router(project_path)
    
    # 在历史记录中查找任务
    history = router.get_history(limit=100)
    task_data = next((t for t in history if t.get("task_id") == task_id), None)
    if not task_data:
        raise HTTPException(status_code=404, detail="Task not found in recent history")
    
    # 重构 Task 对象以进行重试
    from agent_system.models import Task, TaskStatus, TaskStep, Artifact
    task = Task(
        task_id=task_id, # 保持原 ID 或生成新的？通常重试建议保持 ID 以便追踪轨迹
        prompt=task_data["prompt"],
        context=_append_feature_lifecycle_event(
            task_data.get("context", {}),
            "retry",
            "任务从历史记录触发重试",
        )
    )
    task.steps = [
        TaskStep(
            name=s["name"],
            description=s["description"],
            role=s["role"],
            depends_on=s.get("depends_on", []),
            status=TaskStatus.PENDING
        )
        for s in task_data.get("steps", [])
    ]
    task.status = TaskStatus.AWAITING_CONFIRMATION
    
    # 获取最新的编辑器状态
    state = _get_editor_state_for_project(project_path)
    task.context["editor_state"] = state
    
    # 执行
    task = router.execute_plan(task)
    return _serialize_task_for_api(task)


@app.get("/history/{task_id}/diff/{artifact_index}")
async def get_artifact_diff(task_id: str, artifact_index: int, project_path: str = "default"):
    import difflib
    project_path = _normalize_project_key(project_path)
    router = manager.get_router(project_path)
    
    # 在历史记录中查找任务
    history = router.get_history(limit=100)
    task_data = next((t for t in history if t.get("task_id") == task_id), None)
    if not task_data:
        raise HTTPException(status_code=404, detail="Task not found")
    
    artifacts = task_data.get("artifacts", [])
    if artifact_index < 0 or artifact_index >= len(artifacts):
        raise HTTPException(status_code=404, detail="Artifact index out of range")
    
    artifact = artifacts[artifact_index]
    art_path = artifact.get("path", "")
    if not art_path.startswith("res://"):
        raise HTTPException(status_code=400, detail="Only res:// artifacts support diff")
        
    # 查找对应的备份
    backups = task_data.get("backups", [])
    # 尝试匹配路径
    project_root = _resolve_project_root(project_path)
    full_art_path = _resolve_under(project_root, art_path[len("res://"):])
    
    backup = next((b for b in backups if Path(b["original_path"]).resolve() == full_art_path.resolve()), None)
    if not backup:
        # 如果是重命名产物，可能备份的是原始路径
        if artifact.get("type") == "rename_target":
            original_source = artifact.get("metadata", {}).get("original_source")
            if original_source:
                full_orig_path = _resolve_under(project_root, original_source)
                backup = next((b for b in backups if Path(b["original_path"]).resolve() == full_orig_path.resolve()), None)

    if not backup:
        raise HTTPException(status_code=404, detail="No backup found for this artifact to compare against")
        
    try:
        old_content = Path(backup["backup_path"]).read_text(encoding="utf-8")
        # 如果当前文件存在，使用当前文件内容；否则使用 artifact.content（如果有）
        if full_art_path.exists():
            new_content = full_art_path.read_text(encoding="utf-8")
        else:
            new_content = artifact.get("content", "")
            
        diff = difflib.unified_diff(
            old_content.splitlines(),
            new_content.splitlines(),
            fromfile=f"a/{backup['original_path']}",
            tofile=f"b/{art_path}",
            lineterm=""
        )
        return {"ok": True, "diff": "\n".join(list(diff))}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"生成差异失败: {str(e)}")


@app.post("/history/{task_id}/confirm-step/{step_id}")
async def confirm_task_step(task_id: str, step_id: str, project_path: str = "default"):
    project_path = _normalize_project_key(project_path)
    router = manager.get_router(project_path)
    
    task = router.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
        
    # 查找匹配的步骤
    step = next((s for s in task.steps if s.step_id == step_id), None)
    if not step:
        raise HTTPException(status_code=404, detail="Step not found")
        
    if step.status != TaskStatus.AWAITING_CONFIRMATION:
        raise HTTPException(status_code=400, detail=f"Step is not awaiting confirmation (current: {step.status.value})")
        
    # 推进状态
    step.status = TaskStatus.PENDING
    step.requires_confirmation = False
    task.add_log(f"👤 人工已确认步骤: {step.name}")
    
    # 触发执行流
    task = router.execute_plan(task)
    return _serialize_task_for_api(task)


@app.post("/history/{task_id}/feature-review")
async def review_feature_task(task_id: str, req: FeatureReviewRequest, project_path: str = "default"):
    project_path = _normalize_project_key(project_path)
    router = manager.get_router(project_path)
    task = _safe_get_router_task(router, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    _apply_feature_review_to_task(task, req)
    _persist_router_task(router, task)

    payload = _serialize_task_for_api(task)
    await manager.broadcast_task_update(project_path, payload)
    return payload


@app.post("/history/feature-review-batch")
async def review_feature_tasks_batch(req: FeatureReviewBatchRequest, project_path: str = "default"):
    project_path = _normalize_project_key(project_path)
    router = manager.get_router(project_path)
    task_ids = list(dict.fromkeys(str(item).strip() for item in req.task_ids if str(item).strip()))
    filters = {
        "feature_status": _normalize_history_query(req.source_feature_status),
        "feature_id": _normalize_history_query(req.feature_id),
        "owner": _normalize_history_query(req.owner),
        "limit": max(1, min(int(req.limit or 30), 100)),
        "offset": max(0, min(int(req.offset or 0), 5000)),
    }
    if filters["feature_status"] and filters["feature_status"] not in {"pending_review", "pending_acceptance", "approved", "returned"}:
        raise HTTPException(status_code=400, detail="Unsupported source_feature_status")
    if not task_ids:
        history = _load_history_items(router, None if isinstance(getattr(router, "tasks", None), dict) else 500)
        matched = [
            str(item.get("task_id") or "").strip()
            for item in history
            if _history_item_matches(item, filters["feature_status"], filters["feature_id"], filters["owner"])
        ]
        task_ids = list(dict.fromkeys(item for item in matched if item))[filters["offset"]:filters["offset"] + filters["limit"]]
    if not task_ids:
        raise HTTPException(status_code=400, detail="task_ids required")

    items: List[Dict[str, Any]] = []
    errors: List[Dict[str, str]] = []
    for task_id in task_ids:
        task = _safe_get_router_task(router, task_id)
        if not task:
            errors.append({"task_id": task_id, "error": "Task not found"})
            continue
        if req.dry_run:
            items.append(_serialize_task_for_api(task))
            continue
        _apply_feature_review_to_task(task, req)
        _persist_router_task(router, task)
        payload = _serialize_task_for_api(task)
        items.append(payload)
        await manager.broadcast_task_update(project_path, payload)

    return {
        "project_path": project_path,
        "requested_count": len(task_ids),
        "selected_count": len(items),
        "updated_count": 0 if req.dry_run else len(items),
        "error_count": len(errors),
        "dry_run": bool(req.dry_run),
        "filters": filters,
        "items": items,
        "errors": errors,
    }


@app.get("/artifacts")
async def list_artifacts(project_path: str = "default", limit: int = 30):
    project_path = _normalize_project_key(project_path)
    router = manager.get_router(project_path)
    clamped_limit = max(1, min(limit, 100))
    artifacts = _flatten_recent_artifacts(router, clamped_limit)
    return {
        "project_path": project_path,
        "items": artifacts,
        "count": len(artifacts),
    }


@app.get("/report-file")
async def report_file(path: str):
    resolved_path = _resolve_under(REPO_ROOT, path)
    if not resolved_path.exists() or not resolved_path.is_file():
        raise HTTPException(status_code=404, detail="Report not found")
    return FileResponse(str(resolved_path), media_type="text/markdown")


@app.get("/artifact-file")
async def artifact_file(project_path: str = "default", path: str = ""):
    project_path = _normalize_project_key(project_path)
    resolved_path = _resolve_artifact_path(project_path, path)
    if not resolved_path.exists() or not resolved_path.is_file():
        raise HTTPException(status_code=404, detail="Artifact not found")
    return FileResponse(str(resolved_path))


@app.get("/source-preview")
async def source_preview(project_path: str = "default", path: str = "", line: Optional[int] = None, context_lines: int = 3):
    project_path = _normalize_project_key(project_path)
    if not path:
        raise HTTPException(status_code=400, detail="Missing path")

    resolved_project_root = _resolve_project_root(project_path)
    if not resolved_project_root.exists():
        raise HTTPException(status_code=404, detail="Project root not found")

    normalized_path, parsed_line = _parse_source_reference(path, line)
    resolved_path = _resolve_under(resolved_project_root, normalized_path)
    if not resolved_path.exists() or not resolved_path.is_file():
        raise HTTPException(status_code=404, detail="Source file not found")

    try:
        content = resolved_path.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        raise HTTPException(status_code=415, detail="Binary file preview is not supported") from exc

    lines = content.splitlines()
    total_lines = len(lines)
    focus_line = parsed_line or 1
    focus_line = max(1, min(focus_line, total_lines if total_lines else 1))
    span = max(1, min(context_lines, 20))
    start_line = max(1, focus_line - span)
    end_line = min(total_lines, focus_line + span)

    preview_lines = [
        {"number": index, "text": lines[index - 1]}
        for index in range(start_line, end_line + 1)
    ]

    response = {
        "path": normalized_path,
        "resolved_path": str(resolved_path),
        "line": focus_line,
        "start_line": start_line,
        "end_line": end_line,
        "lines": preview_lines,
    }
    response.update(_extract_source_preview_context(resolved_path, focus_line))
    return response


@app.post("/editor/open-resource")
async def open_resource(req: OpenResourceRequest):
    project_path = _normalize_project_key(req.project_path)
    if not req.path:
        raise HTTPException(status_code=400, detail="Missing path")

    state, launch_info = await _ensure_editor_state(
        project_path,
        auto_launch_editor=req.auto_launch_editor,
        wait_for_editor=req.wait_for_editor,
        editor_timeout=req.editor_timeout,
    )
    if not state.get("is_active"):
        raise HTTPException(status_code=409, detail="Editor is offline")

    project_root = _resolve_project_root(project_path)
    if not project_root.exists():
        raise HTTPException(status_code=404, detail="Project root not found")

    normalized_path, parsed_line = _parse_source_reference(req.path, req.line)
    resolved_path = _resolve_under(project_root, normalized_path)
    if not resolved_path.exists() or not resolved_path.is_file():
        raise HTTPException(status_code=404, detail="Source file not found")

    after_event_id = _last_editor_event_id(project_path) if req.wait_for_editor_event else None
    cmd_id = manager.next_command_id(project_path)
    payload = _build_open_resource_command(
        project_root=project_root,
        normalized_path=normalized_path,
        resolved_path=resolved_path,
        line=parsed_line,
        column=req.column,
    )
    
    command = payload["command"]
    command["command_id"] = cmd_id
    manager.register_command(project_path, command)
    queue = manager.get_queue(project_path)
    queue.append(command)
    if queue and manager.active_websockets.get(project_path):
        commands = list(queue)
        queue.clear()
        await manager.dispatch_commands(project_path, commands)
    
    response = payload["response"]
    response["command_id"] = cmd_id
    if launch_info:
        response["launch"] = launch_info
    if req.wait_for_editor_event:
        response["editor_event"] = await _wait_for_editor_event(
            project_path,
            timeout=req.editor_event_timeout,
            after_event_id=after_event_id,
            command_id=cmd_id,
        )
    return response

class PollRequest(BaseModel):
    project_path: str
    state: Dict[str, Any]

@app.post("/plugin/poll")
async def poll(req: PollRequest):
    project_path = _normalize_project_key(req.project_path)
    incoming_state = dict(req.state or {})
    incoming_events = incoming_state.pop("events", [])
    manager.editor_states[project_path] = _enrich_editor_state(project_path, incoming_state)
    # 提取截图并缓存
    if "screenshot" in incoming_state:
        manager.last_screenshots[project_path] = incoming_state["screenshot"]

    if isinstance(incoming_events, list):
        for event in incoming_events:
            if isinstance(event, dict):
                manager.record_editor_event(project_path, event)
    
    queue = manager.get_queue(project_path)
    commands = list(queue)
    queue.clear()
    return {"commands": commands}


@app.post("/plugin/event")
async def plugin_event(req: PluginEventRequest):
    stored_event = manager.record_editor_event(req.project_path, req.event)
    await _broadcast_post_event_updates(req.project_path, stored_event)
    return {"ok": True, "event": stored_event}


@app.post("/editor/wait-event")
async def wait_editor_event(req: WaitEditorEventRequest):
    project_path = _normalize_project_key(req.project_path)
    event = await _wait_for_editor_event(
        project_path,
        timeout=req.timeout,
        after_event_id=req.after_event_id,
        kind=req.kind,
    )
    return {
        "ok": True,
        "project_path": project_path,
        "event": event,
    }

@app.get("/screenshot")
async def get_screenshot(project_path: str = "default"):
    """获取指定项目的最新截图"""
    import base64
    project_path = _normalize_project_key(project_path)
    img_data = manager.last_screenshots.get(project_path)
    if not img_data:
        raise HTTPException(status_code=404, detail="No screenshot available")
    
    # 转换为二进制返回
    return Response(content=base64.b64decode(img_data), media_type="image/jpeg")


def _build_health_payload(project_path: str = "default") -> Dict[str, Any]:
    requested_project = _normalize_project_key(project_path)
    if requested_project == "default" and manager.editor_states:
        requested_project = next(iter(manager.editor_states.keys()))

    editor_state = _get_editor_state_for_project(requested_project)
    screenshot_data = _lookup_project_mapping(manager.last_screenshots, requested_project)

    payload = {
        "status": "ok",
        "project_path": requested_project,
        "active_projects": list(manager.editor_states.keys()),
        "has_screenshot": bool(screenshot_data),
        "screenshot": screenshot_data,
        "api_host": API_HOST,
        "api_port": API_PORT,
        "godot_runtime": _build_godot_runtime_info(requested_project),
        "last_editor_launch": manager.last_editor_launches.get(requested_project),
        "last_editor_event": manager.get_last_editor_event(requested_project),
        "editor_state": _compact_editor_state(editor_state),
    }
    return payload


@app.get("/health")
async def health(project_path: str = "default"):
    return _build_health_payload(project_path)

if __name__ == "__main__":
    uvicorn.run(app, host=API_BIND_HOST, port=API_PORT)

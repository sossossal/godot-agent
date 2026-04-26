"""
Platform delivery baseline skill.
"""

from __future__ import annotations

import difflib
import json
import re
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from pydantic import BaseModel, Field

from ..base import BaseSkill, SkillMetadata
from ...contracts import PLATFORM_DELIVERY_PROFILE_SCHEMA_VERSION, normalize_platform_delivery_profile
from ...models import Artifact, Task, ToolResult
from ...validations import ProjectLayoutValidator


PLATFORM_DELIVERY_SCHEMA: Dict[str, Any] = {
    "manifest_path": "deployment/platform_delivery.json",
    "sample_platforms": [
        {
            "platform_id": "windows_desktop",
            "store": "itch",
            "preset_name": "Windows Desktop",
            "output_path": "builds/windows/game.exe",
            "arch": "x86_64",
            "feature_flags": ["cloud_save", "analytics", "achievements"],
        },
        {
            "platform_id": "web",
            "store": "web",
            "preset_name": "Web",
            "output_path": "builds/web/index.html",
            "arch": "wasm32",
            "feature_flags": ["analytics", "leaderboard"],
        },
    ],
    "sample_savegame": {
        "schema_id": "profile_save",
        "version": "1.0.0",
        "save_mode": "cloud_optional",
        "slot_count": 3,
        "fields": [
            {"name": "player_level", "type": "int", "required": True, "default": 1},
            {"name": "inventory_items", "type": "json", "required": True, "default": []},
            {"name": "checkpoint_id", "type": "string", "required": False, "default": ""},
        ],
    },
    "sample_services": {
        "cloud_save": True,
        "achievements": True,
        "leaderboard": True,
        "analytics": True,
    },
    "sample_multiplayer": {
        "enabled": False,
        "mode": "offline",
        "transport": "offline",
        "max_players": 1,
        "rollback_supported": False,
    },
}

_SNAKE_CASE_RE = re.compile(r"^[a-z0-9_]+$")
_FIELD_TYPE_VALUES = {"int", "float", "bool", "string", "json"}
_SAVE_MODES = {"offline", "cloud_optional", "cloud_required"}
_TRANSPORTS = {"offline", "enet", "websocket", "steam"}


class PlatformDeliveryParams(BaseModel):
    action: str = Field(default="preview", description="template | validate | preview | apply")
    manifest_path: Optional[str] = Field(default=None)
    platforms: List[Dict[str, Any]] = Field(default_factory=list)
    savegame: Dict[str, Any] = Field(default_factory=dict)
    services: Dict[str, Any] = Field(default_factory=dict)
    multiplayer: Dict[str, Any] = Field(default_factory=dict)


class PlatformDeliverySkill(BaseSkill):
    metadata = SkillMetadata(
        name="manage_platform_delivery",
        description="管理平台交付 baseline，统一覆盖平台档案、存档 schema、服务开关和多人模式",
        category="resource",
        tags=["platform", "savegame", "deployment", "multiplayer", "release"],
    )

    input_model = PlatformDeliveryParams

    def get_snapshot(self, *, manifest_path: Optional[str] = None) -> Dict[str, Any]:
        project_root = Path(getattr(self.godot_cli, "project_path", ".") or ".").resolve()
        resolved_manifest = self._resolve_manifest_path(project_root, manifest_path)
        payload = self._load_manifest(resolved_manifest)
        return normalize_platform_delivery_profile({
            "manifest_path": f"res://{resolved_manifest.relative_to(project_root).as_posix()}",
            "platforms": list(payload.get("platforms") or []),
            "savegame": dict(payload.get("savegame") or {}),
            "services": dict(payload.get("services") or {}),
            "multiplayer": dict(payload.get("multiplayer") or {}),
            "issues": [],
            "warnings": [],
            "notes": [],
        })

    def execute(self, task: Task, params: Dict[str, Any]) -> ToolResult:
        p = PlatformDeliveryParams(**params)
        action = self._normalize_action(p.action)
        project_root = Path(getattr(self.godot_cli, "project_path", ".") or ".").resolve()
        layout_validator = ProjectLayoutValidator(project_root=project_root, runtime_root=Path.cwd())
        manifest_path = self._resolve_manifest_path(project_root, p.manifest_path)

        manifest_layout = layout_validator.validate_managed_path(manifest_path, "platform_delivery_manifest")
        if not manifest_layout["passed"]:
            return self.build_result(
                success=False,
                message="平台交付 manifest 路径不符合文件树规范",
                params=self.dump_model(p),
                error="; ".join(issue["message"] for issue in manifest_layout["issues"]),
                validation={"passed": False, "issues": [issue["code"] for issue in manifest_layout["issues"]]},
            )

        current_payload = self._load_manifest(manifest_path)
        if action == "template":
            raw_payload = {
                "platforms": list(PLATFORM_DELIVERY_SCHEMA["sample_platforms"]),
                "savegame": dict(PLATFORM_DELIVERY_SCHEMA["sample_savegame"]),
                "services": dict(PLATFORM_DELIVERY_SCHEMA["sample_services"]),
                "multiplayer": dict(PLATFORM_DELIVERY_SCHEMA["sample_multiplayer"]),
            }
        else:
            raw_payload = {
                "platforms": list(p.platforms or current_payload.get("platforms") or []),
                "savegame": dict(p.savegame or current_payload.get("savegame") or {}),
                "services": dict(p.services or current_payload.get("services") or {}),
                "multiplayer": dict(p.multiplayer or current_payload.get("multiplayer") or {}),
            }

        normalized_payload, issues, warnings = self._normalize_payload(raw_payload)
        snapshot = normalize_platform_delivery_profile({
            "manifest_path": f"res://{manifest_path.relative_to(project_root).as_posix()}",
            "platforms": normalized_payload["platforms"],
            "savegame": normalized_payload["savegame"],
            "services": normalized_payload["services"],
            "multiplayer": normalized_payload["multiplayer"],
            "issues": issues,
            "warnings": warnings,
            "notes": [f"manifest: res://{manifest_path.relative_to(project_root).as_posix()}"],
        })

        manifest_content = json.dumps({
            "schema_version": PLATFORM_DELIVERY_PROFILE_SCHEMA_VERSION,
            **normalized_payload,
        }, ensure_ascii=False, indent=2)
        current_content = manifest_path.read_text(encoding="utf-8") if manifest_path.exists() else ""
        diff_text = "\n".join(difflib.unified_diff(
            current_content.splitlines(),
            manifest_content.splitlines(),
            fromfile=str(manifest_path),
            tofile=str(manifest_path),
            lineterm="",
        ))
        report_path = Path("logs/reports") / f"platform_delivery_{action}_{int(time.time())}.md"
        report_layout = layout_validator.validate_managed_path(report_path, "runtime_report")
        if not report_layout["passed"]:
            return self.build_result(
                success=False,
                message="平台交付报告路径不符合文件树规范",
                params=self.dump_model(p),
                error="; ".join(issue["message"] for issue in report_layout["issues"]),
                validation={"passed": False, "issues": [issue["code"] for issue in report_layout["issues"]]},
            )
        report_content = self._build_report(snapshot, action, diff_text)
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(report_content, encoding="utf-8")

        task.context.setdefault("contract_versions", {})["platform_delivery_profile"] = PLATFORM_DELIVERY_PROFILE_SCHEMA_VERSION
        task.context.update({
            "platform_delivery_manifest_path": f"res://{manifest_path.relative_to(project_root).as_posix()}",
            "platform_delivery_profile": snapshot,
            "platform_delivery_platform_count": snapshot["platform_count"],
            "platform_delivery_service_count": snapshot["service_count"],
        })

        artifacts = [
            Artifact(
                name=manifest_path.name,
                path=str(manifest_path),
                type="resource",
                content=manifest_content,
                metadata={"platform_delivery": True, "action": action},
            ),
            Artifact(
                name=report_path.name,
                path=str(report_path),
                type="report",
                content=report_content,
                metadata={"schema_version": PLATFORM_DELIVERY_PROFILE_SCHEMA_VERSION, "action": action},
            ),
        ]

        if issues and action in {"validate", "preview", "apply"}:
            return self.build_result(
                success=False,
                message="平台交付 baseline 校验失败",
                params=self.dump_model(p),
                error="; ".join(issues),
                artifacts=artifacts,
                data={"platform_delivery_profile": snapshot},
                validation={"passed": False, "issues": issues, "checks": [{"name": "platform_delivery_validation", "status": "failed"}]},
                rollback={"available": False, "strategy": "validation_failed_no_write"},
            )

        if action == "validate":
            return self.build_result(
                success=True,
                message="平台交付 baseline 校验通过",
                params=self.dump_model(p),
                artifacts=artifacts,
                data={"platform_delivery_profile": snapshot},
                validation={"passed": True, "checks": [{"name": "platform_delivery_validation", "status": "passed"}]},
                rollback={"available": False, "strategy": "validate_only"},
            )

        if action == "preview":
            return self.build_result(
                success=True,
                message="平台交付 baseline 预览完成",
                params=self.dump_model(p),
                artifacts=artifacts,
                data={"platform_delivery_profile": snapshot},
                validation={"passed": True, "checks": [{"name": "platform_delivery_validation", "status": "passed"}]},
                rollback={"available": False, "strategy": "preview_only"},
            )

        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        manifest_backup = self.backup_existing_file(task, str(manifest_path))
        manifest_path.write_text(manifest_content, encoding="utf-8")
        rollback_paths = [backup.backup_path for backup in task.backups]
        if manifest_backup and manifest_backup not in rollback_paths:
            rollback_paths.append(manifest_backup)
        return self.build_result(
            success=True,
            message="平台交付 baseline 已写入",
            params=self.dump_model(p),
            artifacts=artifacts,
            data={"platform_delivery_profile": snapshot},
            validation={"passed": True, "checks": [{"name": "platform_delivery_validation", "status": "passed"}]},
            rollback={"available": True, "strategy": "restore_platform_delivery_manifest_backup", "backup_paths": rollback_paths},
        )

    def _normalize_action(self, value: str) -> str:
        normalized = str(value or "preview").strip().lower()
        return normalized if normalized in {"template", "validate", "preview", "apply"} else "preview"

    def _resolve_manifest_path(self, project_root: Path, raw_path: Optional[str]) -> Path:
        relative = str(raw_path or PLATFORM_DELIVERY_SCHEMA["manifest_path"]).strip()
        if relative.startswith("res://"):
            relative = relative.replace("res://", "", 1)
        return (project_root / relative).resolve()

    def _load_manifest(self, manifest_path: Path) -> Dict[str, Any]:
        if not manifest_path.exists():
            return {}
        try:
            payload = json.loads(manifest_path.read_text(encoding="utf-8"))
        except Exception:
            return {}
        return dict(payload) if isinstance(payload, dict) else {}

    def _normalize_payload(self, payload: Dict[str, Any]) -> Tuple[Dict[str, Any], List[str], List[str]]:
        issues: List[str] = []
        warnings: List[str] = []

        platforms: List[Dict[str, Any]] = []
        for raw_platform in list(payload.get("platforms") or []):
            item = dict(raw_platform) if isinstance(raw_platform, dict) else {}
            platform_id = str(item.get("platform_id") or "").strip().lower()
            if not platform_id:
                issues.append("平台条目缺少 platform_id")
            elif not _SNAKE_CASE_RE.match(platform_id):
                issues.append(f"platform_id 必须使用 snake_case: {platform_id}")
            preset_name = str(item.get("preset_name") or "").strip()
            output_path = str(item.get("output_path") or "").strip()
            if not preset_name:
                issues.append(f"平台 {platform_id or 'unnamed'} 缺少 preset_name")
            if not output_path:
                issues.append(f"平台 {platform_id or 'unnamed'} 缺少 output_path")
            platforms.append({
                "platform_id": platform_id,
                "store": str(item.get("store") or "").strip(),
                "preset_name": preset_name,
                "output_path": output_path,
                "arch": str(item.get("arch") or "").strip(),
                "feature_flags": [str(flag).strip() for flag in list(item.get("feature_flags") or []) if str(flag).strip()],
            })

        if not platforms:
            issues.append("至少需要 1 个平台导出条目")

        raw_savegame = dict(payload.get("savegame") or {})
        save_mode = str(raw_savegame.get("save_mode") or "offline").strip().lower()
        if save_mode not in _SAVE_MODES:
            save_mode = "offline"
        fields: List[Dict[str, Any]] = []
        for raw_field in list(raw_savegame.get("fields") or []):
            item = dict(raw_field) if isinstance(raw_field, dict) else {}
            field_name = str(item.get("name") or "").strip().lower()
            field_type = str(item.get("type") or "").strip().lower() or "string"
            if not field_name:
                issues.append("savegame field 缺少 name")
            elif not _SNAKE_CASE_RE.match(field_name):
                issues.append(f"savegame field name 必须使用 snake_case: {field_name}")
            if field_type not in _FIELD_TYPE_VALUES:
                issues.append(f"savegame field {field_name or 'unnamed'} type 不受支持: {field_type}")
                field_type = "string"
            fields.append({
                "name": field_name,
                "type": field_type,
                "required": bool(item.get("required")),
                "default": item.get("default"),
            })
        savegame = {
            "schema_id": str(raw_savegame.get("schema_id") or "").strip().lower(),
            "version": str(raw_savegame.get("version") or "").strip(),
            "save_mode": save_mode,
            "slot_count": int(raw_savegame.get("slot_count") or 0),
            "fields": fields,
        }
        if not savegame["schema_id"]:
            issues.append("savegame 缺少 schema_id")
        elif not _SNAKE_CASE_RE.match(savegame["schema_id"]):
            issues.append(f"savegame schema_id 必须使用 snake_case: {savegame['schema_id']}")
        if savegame["slot_count"] <= 0:
            issues.append("savegame slot_count 必须大于 0")
        if not fields:
            issues.append("savegame 至少需要 1 个字段")

        raw_services = dict(payload.get("services") or {})
        services = {
            "cloud_save": bool(raw_services.get("cloud_save")),
            "achievements": bool(raw_services.get("achievements")),
            "leaderboard": bool(raw_services.get("leaderboard")),
            "analytics": bool(raw_services.get("analytics", True)),
        }
        if services["cloud_save"] and savegame["save_mode"] == "offline":
            issues.append("启用 cloud_save 时，save_mode 不能为 offline")

        raw_multiplayer = dict(payload.get("multiplayer") or {})
        transport = str(raw_multiplayer.get("transport") or "offline").strip().lower()
        if transport not in _TRANSPORTS:
            transport = "offline"
        multiplayer = {
            "enabled": bool(raw_multiplayer.get("enabled")),
            "mode": str(raw_multiplayer.get("mode") or "offline").strip().lower() or "offline",
            "transport": transport,
            "max_players": int(raw_multiplayer.get("max_players") or 1),
            "rollback_supported": bool(raw_multiplayer.get("rollback_supported")),
        }
        if multiplayer["enabled"]:
            if multiplayer["transport"] == "offline":
                issues.append("multiplayer 启用时 transport 不能为 offline")
            if multiplayer["max_players"] < 2:
                issues.append("multiplayer 启用时 max_players 必须大于等于 2")
        elif multiplayer["transport"] != "offline":
            warnings.append("multiplayer 未启用，但 transport 已配置，后续接入时请确认是否保留")

        return {
            "platforms": platforms,
            "savegame": savegame,
            "services": services,
            "multiplayer": multiplayer,
        }, issues, warnings

    def _build_report(self, snapshot: Dict[str, Any], action: str, diff_text: str) -> str:
        lines = [
            "# Platform Delivery Report",
            "",
            f"- Action: {action}",
            f"- Manifest: {snapshot.get('manifest_path') or '-'}",
            f"- Platform Count: {snapshot.get('platform_count', 0)}",
            f"- Service Count: {snapshot.get('service_count', 0)}",
            f"- Multiplayer Enabled: {snapshot.get('multiplayer', {}).get('enabled', False)}",
            "",
            "## Issues",
            "",
        ]
        lines.extend([f"- {item}" for item in snapshot.get("issues", [])] or ["- none"])
        lines.extend(["", "## Warnings", ""])
        lines.extend([f"- {item}" for item in snapshot.get("warnings", [])] or ["- none"])
        lines.extend(["", "## Platforms", ""])
        lines.extend([
            f"- {item['platform_id']}: preset={item['preset_name']} output={item['output_path']} store={item['store'] or '-'} arch={item['arch'] or '-'}"
            for item in snapshot.get("platforms", [])
        ] or ["- none"])
        savegame = snapshot.get("savegame", {})
        lines.extend([
            "",
            "## Savegame",
            "",
            f"- schema_id: {savegame.get('schema_id') or '-'}",
            f"- version: {savegame.get('version') or '-'}",
            f"- save_mode: {savegame.get('save_mode') or '-'}",
            f"- slot_count: {savegame.get('slot_count', 0)}",
        ])
        fields = savegame.get("fields", [])
        lines.extend([
            f"- field {item['name']}: type={item['type']} required={item['required']}"
            for item in fields
        ] or ["- field none"])
        services = snapshot.get("services", {})
        multiplayer = snapshot.get("multiplayer", {})
        lines.extend([
            "",
            "## Services",
            "",
            f"- cloud_save: {services.get('cloud_save', False)}",
            f"- achievements: {services.get('achievements', False)}",
            f"- leaderboard: {services.get('leaderboard', False)}",
            f"- analytics: {services.get('analytics', False)}",
            "",
            "## Multiplayer",
            "",
            f"- enabled: {multiplayer.get('enabled', False)}",
            f"- mode: {multiplayer.get('mode') or '-'}",
            f"- transport: {multiplayer.get('transport') or '-'}",
            f"- max_players: {multiplayer.get('max_players', 1)}",
            f"- rollback_supported: {multiplayer.get('rollback_supported', False)}",
            "",
            "## Diff",
            "",
        ])
        lines.append(diff_text or "- none")
        lines.append("")
        return "\n".join(lines)

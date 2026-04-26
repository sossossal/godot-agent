"""
Scene ownership and lock board builder.

P15 adds a durable per-scene collaboration board so ownership hints and lock
state survive across Portal, API, and multi-agent handoff.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

from agent_system.contracts import (
    SCENE_OWNERSHIP_BOARD_SCHEMA_VERSION,
    normalize_scene_ownership_board,
)
from agent_system.validations import ProjectLayoutValidator


DEFAULT_SCENE_OWNERSHIP_BOARD_PATH = "scenes/scene_ownership_board.json"
_LOCK_STATE_VALUES = {"available", "hinted", "locked", "shared"}
_SCENE_CATEGORY_VALUES = {"level", "ui", "module", "scene"}
_SCENE_SCAN_ROOTS = ("scenes", "agent_modules/scenes")


def build_scene_ownership_board(
    project_root: str | Path,
    runtime_root: Optional[str | Path] = None,
    *,
    board_path: str = "",
    scene_paths: Optional[List[str]] = None,
    scene_category: str = "",
    mode: str = "strict",
    fail_on_warnings: bool = False,
    updated_count: int = 0,
) -> Dict[str, Any]:
    resolved_project_root = Path(project_root).resolve()
    resolved_runtime_root = Path(runtime_root or Path.cwd()).resolve()
    resolved_board_path = _resolve_project_path(
        resolved_project_root,
        board_path or DEFAULT_SCENE_OWNERSHIP_BOARD_PATH,
    )
    normalized_scene_category = _normalize_scene_category(scene_category)
    selected_scene_paths = _normalize_scene_paths(scene_paths)

    layout_validator = ProjectLayoutValidator(project_root=resolved_project_root, runtime_root=resolved_runtime_root)
    board_layout = layout_validator.validate_managed_path(resolved_board_path, "scene_ownership_manifest")

    all_scene_entries = _scan_scene_entries(
        resolved_project_root,
        scene_paths=[],
        scene_category="",
    )
    scene_entries = (
        all_scene_entries
        if not selected_scene_paths and not normalized_scene_category
        else _scan_scene_entries(
            resolved_project_root,
            scene_paths=selected_scene_paths,
            scene_category=normalized_scene_category,
        )
    )
    board_exists = resolved_board_path.exists()
    board_records, orphan_count = _load_board_records(
        resolved_board_path,
        known_scene_paths={entry["scene_path"] for entry in all_scene_entries},
    )
    scene_entries = _merge_board_records(scene_entries, board_records)

    missing_owner_count = sum(1 for item in scene_entries if not item["owner"])
    missing_feature_count = sum(1 for item in scene_entries if item["owner"] and not item["feature_id"])
    locked_without_owner_count = sum(1 for item in scene_entries if item["lock_state"] == "locked" and not item["owner"])
    level_missing_manifest_count = sum(
        1 for item in scene_entries
        if item["scene_category"] == "level" and not item["source_manifest_exists"]
    )
    assigned_count = sum(1 for item in scene_entries if item["owner"])
    locked_count = sum(1 for item in scene_entries if item["lock_state"] == "locked")
    shared_count = sum(1 for item in scene_entries if item["lock_state"] == "shared")
    hinted_count = sum(1 for item in scene_entries if item["lock_state"] == "hinted")
    available_count = sum(1 for item in scene_entries if item["lock_state"] == "available")

    checklist = [
        _item(
            "board_path",
            "Board Path",
            "passed" if board_layout["passed"] else "blocked",
            (
                f"Board path 已受管: {_relative_to_root(resolved_board_path, resolved_project_root)}"
                if board_layout["passed"]
                else "; ".join(issue["message"] for issue in board_layout["issues"])
            ),
            required=True,
            details={"board_path": _relative_to_root(resolved_board_path, resolved_project_root)},
        ),
        _item(
            "scene_scan",
            "Scene Scan",
            "passed" if scene_entries else "blocked",
            f"Scanned scenes: {len(scene_entries)}",
            required=True,
            details={"scene_count": len(scene_entries)},
        ),
        _item(
            "owner_coverage",
            "Owner Coverage",
            "warning" if missing_owner_count else "passed",
            (
                f"{missing_owner_count} 个场景尚未声明 owner"
                if missing_owner_count
                else "所有扫描到的场景都已声明 owner"
            ),
            required=False,
            details={"missing_owner_count": missing_owner_count},
        ),
        _item(
            "feature_linkage",
            "Feature Linkage",
            "warning" if missing_feature_count else "passed",
            (
                f"{missing_feature_count} 个已归属场景缺少 feature_id"
                if missing_feature_count
                else "已归属场景都已关联 feature_id"
            ),
            required=False,
            details={"missing_feature_count": missing_feature_count},
        ),
        _item(
            "locked_without_owner",
            "Locked Without Owner",
            "blocked" if locked_without_owner_count else "passed",
            (
                f"{locked_without_owner_count} 个锁定场景缺少 owner"
                if locked_without_owner_count
                else "锁定场景都已绑定 owner"
            ),
            required=True,
            details={"locked_without_owner_count": locked_without_owner_count},
        ),
        _item(
            "level_manifest_linkage",
            "Level Manifest Linkage",
            "warning" if level_missing_manifest_count else "passed",
            (
                f"{level_missing_manifest_count} 个关卡场景未找到对应 level manifest"
                if level_missing_manifest_count
                else "关卡场景都已关联 level manifest"
            ),
            required=False,
            details={"level_missing_manifest_count": level_missing_manifest_count},
        ),
        _item(
            "orphan_board_entries",
            "Orphan Board Entries",
            "warning" if orphan_count else "passed",
            (
                f"发现 {orphan_count} 条场景 board 孤立记录"
                if orphan_count
                else "board 与当前场景目录一致"
            ),
            required=False,
            details={"orphan_count": orphan_count},
        ),
    ]

    return normalize_scene_ownership_board({
        "project_root": str(resolved_project_root),
        "runtime_root": str(resolved_runtime_root),
        "board_path": _relative_to_root(resolved_board_path, resolved_project_root),
        "board_exists": board_exists,
        "scene_category": normalized_scene_category,
        "selected_scene_paths": selected_scene_paths,
        "mode": mode,
        "fail_on_warnings": fail_on_warnings,
        "scene_count": len(scene_entries),
        "assigned_count": assigned_count,
        "locked_count": locked_count,
        "shared_count": shared_count,
        "hinted_count": hinted_count,
        "available_count": available_count,
        "updated_count": updated_count,
        "orphan_count": orphan_count,
        "missing_owner_count": missing_owner_count,
        "missing_feature_count": missing_feature_count,
        "checklist": checklist,
        "scene_entries": scene_entries,
        "notes": [
            "scene ownership board 以扫描到的 .tscn 为基线，再叠加持久化 owner/lock hint。",
        ],
        "recommendations": _build_recommendations(checklist, scene_entries),
        "contract_versions": {
            "scene_ownership_board": SCENE_OWNERSHIP_BOARD_SCHEMA_VERSION,
        },
    })


def apply_scene_ownership_update(
    project_root: str | Path,
    runtime_root: Optional[str | Path] = None,
    *,
    board_path: str = "",
    scene_paths: Optional[List[str]] = None,
    scene_category: str = "",
    owner: str = "",
    feature_id: str = "",
    lock_state: str = "hinted",
    note: str = "",
    clear_owner: bool = False,
    clear_feature_id: bool = False,
    mode: str = "strict",
    fail_on_warnings: bool = False,
) -> Dict[str, Any]:
    resolved_project_root = Path(project_root).resolve()
    resolved_runtime_root = Path(runtime_root or Path.cwd()).resolve()
    resolved_board_path = _resolve_project_path(
        resolved_project_root,
        board_path or DEFAULT_SCENE_OWNERSHIP_BOARD_PATH,
    )
    normalized_scene_paths = _normalize_scene_paths(scene_paths)
    if not normalized_scene_paths:
        raise ValueError("scene_paths is required")

    normalized_lock_state = _normalize_lock_state(lock_state)
    normalized_owner = "" if clear_owner else str(owner or "").strip()
    normalized_feature_id = "" if clear_feature_id else str(feature_id or "").strip()
    normalized_note = str(note or "").strip()
    normalized_scene_category = _normalize_scene_category(scene_category)
    if normalized_lock_state == "locked" and not normalized_owner:
        raise ValueError("owner is required when lock_state is locked")

    current_board = build_scene_ownership_board(
        resolved_project_root,
        runtime_root=resolved_runtime_root,
        board_path=_relative_to_root(resolved_board_path, resolved_project_root),
        scene_paths=normalized_scene_paths,
        scene_category=normalized_scene_category,
        mode=mode,
        fail_on_warnings=fail_on_warnings,
    )
    current_entries = list(current_board.get("scene_entries") or [])
    if not current_entries:
        raise ValueError("selected scene_paths do not match any managed scene")

    raw_manifest = _load_raw_board_manifest(resolved_board_path)
    all_items = [dict(item) for item in list(raw_manifest.get("items") or []) if isinstance(item, dict)]
    board_index = {
        str(item.get("scene_path") or "").strip(): dict(item)
        for item in all_items
        if str(item.get("scene_path") or "").strip()
    }

    updated_at = datetime.now(timezone.utc).isoformat()
    updated_count = 0
    for entry in current_entries:
        scene_path = str(entry.get("scene_path") or "").strip()
        board_entry = dict(board_index.get(scene_path) or {})
        board_entry.update({
            "scene_path": scene_path,
            "scene_name": str(entry.get("scene_name") or "").strip(),
            "scene_category": normalized_scene_category or str(entry.get("scene_category") or "scene").strip(),
            "source_manifest_path": str(entry.get("source_manifest_path") or "").strip(),
            "owner": normalized_owner,
            "feature_id": normalized_feature_id,
            "lock_state": normalized_lock_state,
            "note": normalized_note,
            "updated_at": updated_at,
        })
        board_index[scene_path] = board_entry
        updated_count += 1

    resolved_board_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_payload = {
        "schema_version": SCENE_OWNERSHIP_BOARD_SCHEMA_VERSION,
        "items": [
            board_index[key]
            for key in sorted(board_index.keys())
        ],
    }
    resolved_board_path.write_text(json.dumps(manifest_payload, ensure_ascii=False, indent=2), encoding="utf-8")

    return build_scene_ownership_board(
        resolved_project_root,
        runtime_root=resolved_runtime_root,
        board_path=_relative_to_root(resolved_board_path, resolved_project_root),
        scene_paths=normalized_scene_paths,
        scene_category=normalized_scene_category,
        mode=mode,
        fail_on_warnings=fail_on_warnings,
        updated_count=updated_count,
    )


def _scan_scene_entries(
    project_root: Path,
    *,
    scene_paths: List[str],
    scene_category: str,
) -> List[Dict[str, Any]]:
    selected = set(scene_paths)
    entries: List[Dict[str, Any]] = []
    for root_relative in _SCENE_SCAN_ROOTS:
        root_path = (project_root / root_relative).resolve()
        if not root_path.exists():
            continue
        for scene_path in sorted(root_path.rglob("*.tscn")):
            res_path = f"res://{scene_path.relative_to(project_root).as_posix()}"
            derived_category = _derive_scene_category(project_root, scene_path)
            if selected and res_path not in selected:
                continue
            if scene_category and derived_category != scene_category:
                continue
            source_manifest_path = _derive_source_manifest_path(project_root, scene_path, derived_category)
            entries.append({
                "scene_path": res_path,
                "scene_name": scene_path.stem,
                "scene_category": derived_category,
                "status": "warning",
                "owner": "",
                "feature_id": "",
                "lock_state": "available",
                "source_manifest_path": source_manifest_path,
                "source_manifest_exists": bool(source_manifest_path),
                "exists": True,
                "derived_from_level_manifest": bool(source_manifest_path and derived_category == "level"),
                "note": "",
                "updated_at": "",
            })
    return entries


def _merge_board_records(
    scene_entries: List[Dict[str, Any]],
    board_records: Dict[str, Dict[str, Any]],
) -> List[Dict[str, Any]]:
    merged: List[Dict[str, Any]] = []
    for entry in scene_entries:
        board_record = dict(board_records.get(entry["scene_path"]) or {})
        owner = str(board_record.get("owner") or "").strip()
        feature_id = str(board_record.get("feature_id") or "").strip()
        lock_state = _normalize_lock_state(board_record.get("lock_state"))
        note = str(board_record.get("note") or "").strip()
        updated_at = str(board_record.get("updated_at") or "").strip()
        status = "passed"
        if lock_state == "locked" and not owner:
            status = "blocked"
        elif not owner or (owner and not feature_id):
            status = "warning"
        merged.append({
            **entry,
            "scene_category": _normalize_scene_category(board_record.get("scene_category")) or entry["scene_category"],
            "owner": owner,
            "feature_id": feature_id,
            "lock_state": lock_state,
            "note": note,
            "updated_at": updated_at,
            "status": status,
        })
    return merged


def _load_board_records(board_path: Path, known_scene_paths: Set[str]) -> Tuple[Dict[str, Dict[str, Any]], int]:
    if not board_path.exists():
        return {}, 0
    try:
        payload = json.loads(board_path.read_text(encoding="utf-8"))
    except Exception:
        return {}, 0
    items = [dict(item) for item in list(payload.get("items") or []) if isinstance(item, dict)]
    records = {
        str(item.get("scene_path") or "").strip(): item
        for item in items
        if str(item.get("scene_path") or "").strip()
    }
    orphan_count = sum(1 for scene_path in records.keys() if scene_path not in known_scene_paths)
    return records, orphan_count


def _load_raw_board_manifest(board_path: Path) -> Dict[str, Any]:
    if not board_path.exists():
        return {"schema_version": SCENE_OWNERSHIP_BOARD_SCHEMA_VERSION, "items": []}
    try:
        payload = json.loads(board_path.read_text(encoding="utf-8"))
        if isinstance(payload, dict):
            return payload
    except Exception:
        pass
    return {"schema_version": SCENE_OWNERSHIP_BOARD_SCHEMA_VERSION, "items": []}


def _resolve_project_path(project_root: Path, raw_path: str) -> Path:
    relative = str(raw_path or DEFAULT_SCENE_OWNERSHIP_BOARD_PATH).strip().replace("\\", "/")
    if relative.startswith("res://"):
        relative = relative[6:]
    return (project_root / relative).resolve()


def _normalize_scene_paths(scene_paths: Optional[List[str]]) -> List[str]:
    result: List[str] = []
    seen = set()
    for item in list(scene_paths or []):
        raw = str(item or "").strip().replace("\\", "/")
        if not raw:
            continue
        if not raw.startswith("res://"):
            raw = f"res://{raw.lstrip('/')}"
        if raw not in seen:
            result.append(raw)
            seen.add(raw)
    return result


def _normalize_scene_category(value: Any) -> str:
    normalized = str(value or "").strip().lower()
    return normalized if normalized in _SCENE_CATEGORY_VALUES else ""


def _normalize_lock_state(value: Any) -> str:
    normalized = str(value or "").strip().lower()
    return normalized if normalized in _LOCK_STATE_VALUES else "available"


def _derive_scene_category(project_root: Path, scene_path: Path) -> str:
    relative = scene_path.relative_to(project_root).as_posix()
    if relative.startswith("scenes/levels/"):
        return "level"
    if relative.startswith("scenes/ui/"):
        return "ui"
    if relative.startswith("agent_modules/scenes/"):
        return "module"
    return "scene"


def _derive_source_manifest_path(project_root: Path, scene_path: Path, scene_category: str) -> str:
    if scene_category != "level":
        return ""
    manifest_path = project_root / "data_tables" / "levels" / f"{scene_path.stem}.json"
    if manifest_path.exists():
        return manifest_path.relative_to(project_root).as_posix()
    return ""


def _relative_to_root(path: Path, root: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return path.as_posix()


def _item(
    item_id: str,
    label: str,
    status: str,
    message: str,
    *,
    required: bool,
    details: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    return {
        "item_id": item_id,
        "label": label,
        "status": status,
        "required": required,
        "message": message,
        "details": details or {},
    }


def _build_recommendations(checklist: List[Dict[str, Any]], scene_entries: List[Dict[str, Any]]) -> List[str]:
    recommendations: List[str] = []
    if any(item["item_id"] == "owner_coverage" and item["status"] == "warning" for item in checklist):
        recommendations.append("优先为高频协作场景声明 owner，至少先覆盖 levels 和 agent_modules/scenes。")
    if any(item["item_id"] == "feature_linkage" and item["status"] == "warning" for item in checklist):
        recommendations.append("已归属场景需要同步 feature_id，避免后续发布和回滚时无法定位责任边界。")
    if any(item["item_id"] == "locked_without_owner" and item["status"] == "blocked" for item in checklist):
        recommendations.append("不要保留无 owner 的 locked 场景；先补 owner 再允许锁定。")
    if not recommendations and scene_entries:
        recommendations.append("把长期共享的场景设为 shared，把短期独占修改的场景设为 locked。")
    return recommendations

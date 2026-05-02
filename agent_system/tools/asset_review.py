"""
Asset review workflow builder.

P15 introduces a durable review board for managed art assets so approval state
survives across Portal, API, release gates, and multi-agent handoff.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from agent_system.contracts import (
    ASSET_REVIEW_WORKFLOW_SCHEMA_VERSION,
    normalize_asset_review_workflow,
)
from agent_system.skills.resource.art_asset_skill import ART_ASSET_SCHEMAS, ART_ASSET_TYPE_LABELS
from agent_system.validations import ProjectLayoutValidator


DEFAULT_ASSET_REVIEW_MANIFEST_PATH = "assets/manifests/asset_review_board.json"
_REVIEW_STATUS_VALUES = {"pending_review", "approved", "returned"}


def build_asset_review_workflow(
    project_root: str | Path,
    runtime_root: Optional[str | Path] = None,
    *,
    asset_type: str = "outsource",
    asset_manifest_path: str = "",
    review_manifest_path: str = "",
    asset_ids: Optional[List[str]] = None,
    mode: str = "strict",
    fail_on_warnings: bool = False,
    updated_count: int = 0,
) -> Dict[str, Any]:
    resolved_project_root = Path(project_root).resolve()
    resolved_runtime_root = Path(runtime_root or Path.cwd()).resolve()
    normalized_asset_type = _normalize_asset_type(asset_type)
    schema = ART_ASSET_SCHEMAS[normalized_asset_type]
    resolved_source_manifest_path = _resolve_project_path(
        resolved_project_root,
        asset_manifest_path or str(schema.get("manifest_path") or ""),
    )
    resolved_review_manifest_path = _resolve_project_path(
        resolved_project_root,
        review_manifest_path or DEFAULT_ASSET_REVIEW_MANIFEST_PATH,
    )
    normalized_asset_ids = _clean_text_list(asset_ids)

    layout_validator = ProjectLayoutValidator(project_root=resolved_project_root, runtime_root=resolved_runtime_root)
    source_manifest_layout = layout_validator.validate_managed_path(resolved_source_manifest_path, "asset_manifest")
    review_manifest_layout = layout_validator.validate_managed_path(resolved_review_manifest_path, "asset_manifest")

    source_manifest_exists = resolved_source_manifest_path.exists()
    source_manifest_schema_version = ""
    source_entries: List[Dict[str, Any]] = []
    source_manifest_error = ""
    if source_manifest_exists:
        try:
            raw_manifest = json.loads(resolved_source_manifest_path.read_text(encoding="utf-8"))
            if isinstance(raw_manifest, dict):
                source_manifest_schema_version = str(raw_manifest.get("schema_version") or "").strip()
                source_entries = [dict(item) for item in list(raw_manifest.get("entries") or []) if isinstance(item, dict)]
            elif isinstance(raw_manifest, list):
                source_entries = [dict(item) for item in raw_manifest if isinstance(item, dict)]
            else:
                source_manifest_error = "asset manifest 必须是 JSON object 或 array"
        except Exception as exc:
            source_manifest_error = str(exc)

    review_manifest_exists = resolved_review_manifest_path.exists()
    review_manifest_schema_version = ""
    review_records, orphan_review_count = _load_review_records(
        resolved_review_manifest_path,
        asset_type=normalized_asset_type,
        known_asset_ids={str(item.get("asset_id") or "").strip() for item in source_entries if item.get("asset_id")},
    )
    if review_manifest_exists:
        try:
            raw_review = json.loads(resolved_review_manifest_path.read_text(encoding="utf-8"))
            if isinstance(raw_review, dict):
                review_manifest_schema_version = str(raw_review.get("schema_version") or "").strip()
        except Exception:
            pass

    review_entries = _build_review_entries(
        asset_type=normalized_asset_type,
        asset_label=ART_ASSET_TYPE_LABELS.get(normalized_asset_type, normalized_asset_type),
        source_manifest_path=_relative_to_root(resolved_source_manifest_path, resolved_project_root),
        source_entries=source_entries,
        review_records=review_records,
        filtered_asset_ids=normalized_asset_ids,
    )
    provenance_summary = _build_provenance_summary(review_entries)

    pending_review_count = sum(1 for item in review_entries if item["review_status"] == "pending_review")
    approved_count = sum(1 for item in review_entries if item["review_status"] == "approved")
    returned_count = sum(1 for item in review_entries if item["review_status"] == "returned")

    checklist = [
        _item(
            "source_manifest_path",
            "Source Manifest Path",
            "passed" if source_manifest_layout["passed"] else "blocked",
            (
                f"Source manifest path 已受管: {_relative_to_root(resolved_source_manifest_path, resolved_project_root)}"
                if source_manifest_layout["passed"]
                else "; ".join(issue["message"] for issue in source_manifest_layout["issues"])
            ),
            required=True,
            details={"source_manifest_path": _relative_to_root(resolved_source_manifest_path, resolved_project_root)},
        ),
        _item(
            "source_manifest_available",
            "Source Manifest Available",
            "blocked" if (not source_manifest_exists or source_manifest_error) else "passed",
            (
                f"Asset manifest 已加载，entries={len(source_entries)}"
                if source_manifest_exists and not source_manifest_error
                else (f"asset manifest 解析失败: {source_manifest_error}" if source_manifest_error else "未找到 asset manifest")
            ),
            required=True,
            details={
                "source_manifest_exists": source_manifest_exists,
                "source_manifest_schema_version": source_manifest_schema_version,
            },
        ),
        _item(
            "review_manifest_path",
            "Review Manifest Path",
            "passed" if review_manifest_layout["passed"] else "blocked",
            (
                f"Review board path 已受管: {_relative_to_root(resolved_review_manifest_path, resolved_project_root)}"
                if review_manifest_layout["passed"]
                else "; ".join(issue["message"] for issue in review_manifest_layout["issues"])
            ),
            required=True,
            details={"review_manifest_path": _relative_to_root(resolved_review_manifest_path, resolved_project_root)},
        ),
        _item(
            "reviewable_entries",
            "Reviewable Entries",
            "blocked" if not review_entries else "passed",
            f"Reviewable entries: {len(review_entries)}",
            required=True,
            details={"reviewable_count": len(review_entries)},
        ),
        _item(
            "pending_review",
            "Pending Review",
            "warning" if pending_review_count else "passed",
            (
                f"{pending_review_count} 个资产仍待评审"
                if pending_review_count
                else "当前过滤范围内资产都已有评审结论"
            ),
            required=False,
            details={"pending_review_count": pending_review_count},
        ),
        _item(
            "returned_assets",
            "Returned Assets",
            "warning" if returned_count else "passed",
            (
                f"{returned_count} 个资产被退回"
                if returned_count
                else "当前过滤范围内没有退回资产"
            ),
            required=False,
            details={"returned_count": returned_count},
        ),
        _item(
            "approved_coverage",
            "Approved Coverage",
            (
                "passed"
                if review_entries and approved_count == len(review_entries)
                else ("warning" if review_entries else "skipped")
            ),
            (
                f"approved {approved_count}/{len(review_entries)}"
                if review_entries
                else "等待有效 asset manifest 后再统计"
            ),
            required=False,
            details={"approved_count": approved_count},
        ),
        _item(
            "review_manifest_consistency",
            "Review Manifest Consistency",
            "warning" if orphan_review_count else "passed",
            (
                f"发现 {orphan_review_count} 条孤立 review record"
                if orphan_review_count
                else "review board 与当前 asset manifest 一致"
            ),
            required=False,
            details={"orphan_review_count": orphan_review_count},
        ),
        _item(
            "asset_provenance",
            "Asset Provenance",
            "warning" if provenance_summary["issue_count"] else "passed",
            (
                f"provenance issues={provenance_summary['issue_count']}, "
                f"license coverage={provenance_summary['license_coverage_ratio']}"
            ),
            required=False,
            details=provenance_summary,
        ),
    ]

    return normalize_asset_review_workflow({
        "project_root": str(resolved_project_root),
        "runtime_root": str(resolved_runtime_root),
        "asset_type": normalized_asset_type,
        "asset_label": ART_ASSET_TYPE_LABELS.get(normalized_asset_type, normalized_asset_type),
        "source_manifest_path": _relative_to_root(resolved_source_manifest_path, resolved_project_root),
        "review_manifest_path": _relative_to_root(resolved_review_manifest_path, resolved_project_root),
        "source_manifest_exists": source_manifest_exists,
        "review_manifest_exists": review_manifest_exists,
        "source_manifest_schema_version": source_manifest_schema_version,
        "review_manifest_schema_version": review_manifest_schema_version,
        "mode": mode,
        "fail_on_warnings": fail_on_warnings,
        "asset_ids": normalized_asset_ids,
        "reviewable_count": len(review_entries),
        "pending_review_count": pending_review_count,
        "approved_count": approved_count,
        "returned_count": returned_count,
        "updated_count": updated_count,
        "orphan_review_count": orphan_review_count,
        "provenance_summary": provenance_summary,
        "checklist": checklist,
        "review_entries": review_entries,
        "notes": [
            "asset review workflow 复用 art intake manifest 作为唯一 source of truth。",
        ],
        "recommendations": _build_recommendations(checklist, review_entries),
        "contract_versions": {
            "asset_review_workflow": ASSET_REVIEW_WORKFLOW_SCHEMA_VERSION,
        },
    })


def apply_asset_review_decision(
    project_root: str | Path,
    runtime_root: Optional[str | Path] = None,
    *,
    asset_type: str = "outsource",
    asset_manifest_path: str = "",
    review_manifest_path: str = "",
    asset_ids: Optional[List[str]] = None,
    reviewer: str = "",
    review_status: str = "approved",
    review_note: str = "",
    mode: str = "strict",
    fail_on_warnings: bool = False,
) -> Dict[str, Any]:
    resolved_project_root = Path(project_root).resolve()
    resolved_runtime_root = Path(runtime_root or Path.cwd()).resolve()
    normalized_asset_type = _normalize_asset_type(asset_type)
    normalized_review_status = _normalize_review_status(review_status)
    normalized_reviewer = str(reviewer or "").strip()
    normalized_review_note = str(review_note or "").strip()
    if normalized_review_status in {"approved", "returned"} and not normalized_reviewer:
        raise ValueError("reviewer is required when review_status is approved or returned")

    schema = ART_ASSET_SCHEMAS[normalized_asset_type]
    resolved_source_manifest_path = _resolve_project_path(
        resolved_project_root,
        asset_manifest_path or str(schema.get("manifest_path") or ""),
    )
    resolved_review_manifest_path = _resolve_project_path(
        resolved_project_root,
        review_manifest_path or DEFAULT_ASSET_REVIEW_MANIFEST_PATH,
    )
    source_entries = _load_source_entries(resolved_source_manifest_path)
    if not source_entries:
        raise ValueError("asset manifest has no reviewable entries")

    normalized_asset_ids = _clean_text_list(asset_ids)
    if normalized_asset_ids:
        source_entries = [
            entry
            for entry in source_entries
            if str(entry.get("asset_id") or "").strip() in set(normalized_asset_ids)
        ]
    if not source_entries:
        raise ValueError("selected asset_ids do not match any asset manifest entries")

    raw_review_manifest = _load_raw_review_manifest(resolved_review_manifest_path)
    all_items = [dict(item) for item in list(raw_review_manifest.get("items") or []) if isinstance(item, dict)]
    review_index = {
        (str(item.get("asset_type") or "").strip() or "texture", str(item.get("asset_id") or "").strip()): dict(item)
        for item in all_items
        if item.get("asset_id")
    }

    updated_count = 0
    reviewed_at = "" if normalized_review_status == "pending_review" else datetime.now(timezone.utc).isoformat()
    for entry in source_entries:
        asset_id = str(entry.get("asset_id") or "").strip()
        if not asset_id:
            continue
        key = (normalized_asset_type, asset_id)
        review_record = dict(review_index.get(key) or {})
        review_record.update({
            "asset_type": normalized_asset_type,
            "asset_id": asset_id,
            "source_manifest_path": _relative_to_root(resolved_source_manifest_path, resolved_project_root),
            "source_path": str(entry.get("source_path") or "").strip(),
            "target_path": str(entry.get("target_path") or "").strip(),
            "source_tool": str(entry.get("source_tool") or "").strip(),
            "package_version": str(entry.get("package_version") or "").strip(),
            "license_name": str(entry.get("license_name") or "").strip(),
            "tags": list(entry.get("tags") or []),
            "review_status": normalized_review_status,
            "reviewer": normalized_reviewer if normalized_review_status != "pending_review" else "",
            "review_note": normalized_review_note,
            "reviewed_at": reviewed_at,
        })
        review_index[key] = review_record
        updated_count += 1

    persisted_items = [
        review_index[key]
        for key in sorted(review_index.keys(), key=lambda item: (item[0], item[1]))
    ]
    resolved_review_manifest_path.parent.mkdir(parents=True, exist_ok=True)
    resolved_review_manifest_path.write_text(
        json.dumps({
            "schema_version": ASSET_REVIEW_WORKFLOW_SCHEMA_VERSION,
            "items": persisted_items,
        }, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    return build_asset_review_workflow(
        resolved_project_root,
        runtime_root=resolved_runtime_root,
        asset_type=normalized_asset_type,
        asset_manifest_path=_relative_to_root(resolved_source_manifest_path, resolved_project_root),
        review_manifest_path=_relative_to_root(resolved_review_manifest_path, resolved_project_root),
        asset_ids=normalized_asset_ids or [str(item.get("asset_id") or "").strip() for item in source_entries],
        mode=mode,
        fail_on_warnings=fail_on_warnings,
        updated_count=updated_count,
    )


def _build_review_entries(
    *,
    asset_type: str,
    asset_label: str,
    source_manifest_path: str,
    source_entries: List[Dict[str, Any]],
    review_records: Dict[str, Dict[str, Any]],
    filtered_asset_ids: List[str],
) -> List[Dict[str, Any]]:
    wanted_ids = set(filtered_asset_ids)
    entries: List[Dict[str, Any]] = []
    for raw_entry in source_entries:
        asset_id = str(raw_entry.get("asset_id") or "").strip()
        if not asset_id:
            continue
        if wanted_ids and asset_id not in wanted_ids:
            continue
        review_record = dict(review_records.get(asset_id) or {})
        review_status = _normalize_review_status(review_record.get("review_status") or "pending_review")
        issues: List[str] = []
        warnings: List[str] = []
        if not str(raw_entry.get("target_path") or "").strip():
            issues.append(f"{asset_id} 缺少 target_path")
        if review_status in {"approved", "returned"} and not str(review_record.get("reviewer") or "").strip():
            warnings.append(f"{asset_id} 缺少 reviewer")
        status = "blocked" if issues else ("warning" if warnings or review_status in {"pending_review", "returned"} else "passed")
        entries.append({
            "asset_type": asset_type,
            "asset_label": asset_label,
            "asset_id": asset_id,
            "status": status,
            "review_status": review_status,
            "source_manifest_path": source_manifest_path,
            "source_path": str(raw_entry.get("source_path") or "").strip(),
            "target_path": str(raw_entry.get("target_path") or "").strip(),
            "source_tool": str(raw_entry.get("source_tool") or "").strip(),
            "package_version": str(raw_entry.get("package_version") or "").strip(),
            "license_name": str(raw_entry.get("license_name") or "").strip(),
            "source_dependency_paths": _clean_text_list(raw_entry.get("source_dependency_paths")),
            "target_dependency_paths": _clean_text_list(raw_entry.get("target_dependency_paths")),
            "reviewer": str(review_record.get("reviewer") or "").strip(),
            "review_note": str(review_record.get("review_note") or "").strip(),
            "reviewed_at": str(review_record.get("reviewed_at") or "").strip(),
            "tags": _clean_text_list(raw_entry.get("tags")),
            "issue_count": len(issues),
            "warning_count": len(warnings),
            "issues": issues,
            "warnings": warnings,
        })
    return entries


def _build_provenance_summary(review_entries: List[Dict[str, Any]]) -> Dict[str, Any]:
    issue_assets: List[str] = []
    missing_source_assets: List[str] = []
    missing_target_assets: List[str] = []
    missing_tool_assets: List[str] = []
    missing_license_assets: List[str] = []
    dependency_assets: List[str] = []
    source_dependency_count = 0
    target_dependency_count = 0

    for entry in review_entries:
        asset_id = str(entry.get("asset_id") or "unnamed_asset").strip()
        if not str(entry.get("source_path") or "").strip():
            missing_source_assets.append(asset_id)
        if not str(entry.get("target_path") or "").strip():
            missing_target_assets.append(asset_id)
        if not str(entry.get("source_tool") or "").strip():
            missing_tool_assets.append(asset_id)
        if not str(entry.get("license_name") or "").strip():
            missing_license_assets.append(asset_id)
        source_deps = _clean_text_list(entry.get("source_dependency_paths"))
        target_deps = _clean_text_list(entry.get("target_dependency_paths"))
        source_dependency_count += len(source_deps)
        target_dependency_count += len(target_deps)
        if source_deps or target_deps:
            dependency_assets.append(asset_id)

    for collection in (missing_source_assets, missing_target_assets, missing_tool_assets, missing_license_assets):
        for asset_id in collection:
            if asset_id not in issue_assets:
                issue_assets.append(asset_id)

    total = len(review_entries)
    license_coverage = 1.0 if total == 0 else (total - len(missing_license_assets)) / float(total)
    source_tool_coverage = 1.0 if total == 0 else (total - len(missing_tool_assets)) / float(total)
    dependency_coverage = 0.0 if total == 0 else len(set(dependency_assets)) / float(total)
    return {
        "asset_count": total,
        "issue_count": len(issue_assets),
        "issue_assets": issue_assets,
        "missing_source_assets": missing_source_assets,
        "missing_target_assets": missing_target_assets,
        "missing_tool_assets": missing_tool_assets,
        "missing_license_assets": missing_license_assets,
        "license_coverage_ratio": round(license_coverage, 4),
        "source_tool_coverage_ratio": round(source_tool_coverage, 4),
        "dependency_coverage_ratio": round(dependency_coverage, 4),
        "source_dependency_count": source_dependency_count,
        "target_dependency_count": target_dependency_count,
    }


def _build_recommendations(checklist: List[Dict[str, Any]], review_entries: List[Dict[str, Any]]) -> List[str]:
    recommendations: List[str] = []
    for item in checklist:
        if item["status"] == "blocked":
            recommendations.append(f"先修复 `{item['item_id']}`: {item['message']}")
        elif item["status"] == "warning":
            recommendations.append(f"复核 `{item['item_id']}`: {item['message']}")
    for entry in review_entries:
        if entry["review_status"] == "pending_review":
            recommendations.append(f"为 `{entry['asset_id']}` 补充 reviewer 并给出 approval/return 决议。")
        elif entry["review_status"] == "returned":
            recommendations.append(f"`{entry['asset_id']}` 已退回，处理备注后再重新评审。")
    deduped: List[str] = []
    seen = set()
    for item in recommendations:
        text = str(item or "").strip()
        if text and text not in seen:
            deduped.append(text)
            seen.add(text)
    return deduped[:10]


def _load_source_entries(source_manifest_path: Path) -> List[Dict[str, Any]]:
    if not source_manifest_path.exists():
        return []
    try:
        raw_manifest = json.loads(source_manifest_path.read_text(encoding="utf-8"))
    except Exception:
        return []
    if isinstance(raw_manifest, dict):
        items = raw_manifest.get("entries") or []
    elif isinstance(raw_manifest, list):
        items = raw_manifest
    else:
        items = []
    return [dict(item) for item in items if isinstance(item, dict)]


def _load_raw_review_manifest(review_manifest_path: Path) -> Dict[str, Any]:
    if not review_manifest_path.exists():
        return {"schema_version": ASSET_REVIEW_WORKFLOW_SCHEMA_VERSION, "items": []}
    try:
        payload = json.loads(review_manifest_path.read_text(encoding="utf-8"))
    except Exception:
        return {"schema_version": ASSET_REVIEW_WORKFLOW_SCHEMA_VERSION, "items": []}
    return payload if isinstance(payload, dict) else {"schema_version": ASSET_REVIEW_WORKFLOW_SCHEMA_VERSION, "items": []}


def _load_review_records(
    review_manifest_path: Path,
    *,
    asset_type: str,
    known_asset_ids: set[str],
) -> Tuple[Dict[str, Dict[str, Any]], int]:
    raw_manifest = _load_raw_review_manifest(review_manifest_path)
    review_records: Dict[str, Dict[str, Any]] = {}
    orphan_count = 0
    for item in list(raw_manifest.get("items") or []):
        if not isinstance(item, dict):
            continue
        record_asset_type = str(item.get("asset_type") or "").strip() or "texture"
        asset_id = str(item.get("asset_id") or "").strip()
        if not asset_id or record_asset_type != asset_type:
            continue
        review_records[asset_id] = dict(item)
        if known_asset_ids and asset_id not in known_asset_ids:
            orphan_count += 1
    return review_records, orphan_count


def _normalize_asset_type(asset_type: Any) -> str:
    normalized = str(asset_type or "").strip().lower() or "outsource"
    if normalized not in ART_ASSET_SCHEMAS:
        return "outsource"
    return normalized


def _normalize_review_status(review_status: Any) -> str:
    normalized = str(review_status or "").strip().lower() or "pending_review"
    if normalized not in _REVIEW_STATUS_VALUES:
        return "pending_review"
    return normalized


def _resolve_project_path(project_root: Path, raw_path: str) -> Path:
    text = str(raw_path or "").strip().replace("\\", "/")
    if not text:
        return project_root
    if text.startswith("res://"):
        return (project_root / text.replace("res://", "", 1)).resolve()
    candidate = Path(text)
    if candidate.is_absolute():
        return candidate.resolve()
    return (project_root / text).resolve()


def _relative_to_root(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except Exception:
        return str(path.resolve())


def _clean_text_list(value: Any) -> List[str]:
    if isinstance(value, str):
        parts = value.replace("\r", "\n").replace(";", "\n").split("\n")
    elif isinstance(value, (list, tuple, set)):
        parts = list(value)
    else:
        return []

    cleaned: List[str] = []
    seen = set()
    for item in parts:
        text = str(item).strip()
        if not text or text in seen:
            continue
        cleaned.append(text)
        seen.add(text)
    return cleaned


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
        "details": dict(details or {}),
    }

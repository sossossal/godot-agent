"""
Outsource delivery gate builder.

P15 extends the existing art intake manifest into a dedicated delivery gate so
Portal, API, and external agents can validate vendor package readiness against
the managed file tree and metadata contract.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

from agent_system.contracts import (
    OUTSOURCE_DELIVERY_GATE_SCHEMA_VERSION,
    normalize_outsource_delivery_gate,
)


DEFAULT_OUTSOURCE_MANIFEST_PATH = "assets/manifests/outsource_assets.json"
DEFAULT_OUTSOURCE_PACKAGE_ROOT = "assets/packages/outsource"
_ALLOWED_SOURCE_TOOLS = {"outsource", "outsource_delivery"}
_PACKAGE_VERSION_RE = re.compile(r"^(v?\d+\.\d+\.\d+|v?\d{4}[_-]\d{2}(?:[_-]\d{2})?)$", re.IGNORECASE)


def build_outsource_delivery_gate(
    project_root: str | Path,
    runtime_root: Optional[str | Path] = None,
    *,
    manifest_path: str = "",
    package_root: str = "",
    required_license_names: Optional[List[str]] = None,
    mode: str = "strict",
    fail_on_warnings: bool = False,
) -> Dict[str, Any]:
    resolved_project_root = Path(project_root).resolve()
    resolved_runtime_root = Path(runtime_root or Path.cwd()).resolve()
    resolved_manifest_path = _resolve_project_path(
        resolved_project_root,
        manifest_path or DEFAULT_OUTSOURCE_MANIFEST_PATH,
    )
    resolved_package_root = _resolve_project_path(
        resolved_project_root,
        package_root or DEFAULT_OUTSOURCE_PACKAGE_ROOT,
    )
    normalized_required_licenses = _clean_text_list(required_license_names)

    manifest_exists = resolved_manifest_path.exists()
    package_root_exists = resolved_package_root.exists()
    manifest_entries: List[Dict[str, Any]] = []
    manifest_schema_version = ""
    manifest_asset_type = ""
    manifest_error = ""

    if manifest_exists:
        try:
            raw_manifest = json.loads(resolved_manifest_path.read_text(encoding="utf-8"))
            if isinstance(raw_manifest, dict):
                manifest_schema_version = str(raw_manifest.get("schema_version") or "").strip()
                manifest_asset_type = str(raw_manifest.get("asset_type") or "").strip().lower()
                manifest_entries = [dict(item) for item in list(raw_manifest.get("entries") or []) if isinstance(item, dict)]
            elif isinstance(raw_manifest, list):
                manifest_entries = [dict(item) for item in raw_manifest if isinstance(item, dict)]
            else:
                manifest_error = "manifest 必须是 JSON object 或 array"
        except Exception as exc:
            manifest_error = str(exc)

    deliveries = [
        _build_delivery_row(
            resolved_project_root,
            resolved_package_root,
            raw_entry,
            required_license_names=normalized_required_licenses,
        )
        for raw_entry in manifest_entries
    ]

    metadata_blocked = [row for row in deliveries if _has_any_issue(row, ("package_version", "license_name", "source_tool"))]
    file_blocked = [row for row in deliveries if _has_any_issue(row, ("target_path", "target_exists", "package_file"))]
    traceability_warnings = [row for row in deliveries if _has_any_warning(row, ("source_path", "source_missing", "notes", "tags"))]
    budget_warnings = [row for row in deliveries if _has_any_warning(row, ("estimated_memory_mb", "package_size"))]
    license_blocked = [row for row in deliveries if _has_any_issue(row, ("required_license_names",))]

    checklist = [
        _item(
            "manifest_available",
            "Manifest Available",
            "blocked" if (not manifest_exists or manifest_error) else "passed",
            (
                f"外包 manifest 已加载: {_relative_to_root(resolved_manifest_path, resolved_project_root)}"
                if manifest_exists and not manifest_error
                else (f"manifest 解析失败: {manifest_error}" if manifest_error else "未找到 assets/manifests/outsource_assets.json")
            ),
            required=True,
            details={
                "manifest_path": _relative_to_root(resolved_manifest_path, resolved_project_root),
                "manifest_exists": manifest_exists,
                "manifest_error": manifest_error,
            },
        ),
        _item(
            "manifest_contract",
            "Manifest Contract",
            (
                "skipped"
                if (not manifest_exists or manifest_error)
                else (
                    "blocked"
                    if manifest_asset_type not in {"", "outsource"}
                    else ("warning" if not manifest_schema_version else "passed")
                )
            ),
            (
                f"asset_type={manifest_asset_type or 'outsource'} / schema={manifest_schema_version or 'missing'}"
                if manifest_exists and not manifest_error
                else "等待有效 manifest 后再校验 contract"
            ),
            required=True,
            details={
                "manifest_schema_version": manifest_schema_version,
                "manifest_asset_type": manifest_asset_type,
            },
        ),
        _item(
            "package_root",
            "Package Root",
            "passed" if package_root_exists else "blocked",
            (
                f"Package root 已就绪: {_relative_to_root(resolved_package_root, resolved_project_root)}"
                if package_root_exists
                else f"缺少 package root: {_relative_to_root(resolved_package_root, resolved_project_root)}"
            ),
            required=True,
            details={"package_root": _relative_to_root(resolved_package_root, resolved_project_root)},
        ),
        _item(
            "delivery_entries",
            "Delivery Entries",
            "passed" if deliveries else "blocked",
            f"Manifest entries: {len(deliveries)}",
            required=True,
            details={"delivery_count": len(deliveries)},
        ),
        _item(
            "delivery_metadata",
            "Delivery Metadata",
            "blocked" if metadata_blocked else "passed",
            (
                "全部交付包已声明 package_version / license_name / source_tool"
                if not metadata_blocked
                else f"{len(metadata_blocked)} 个交付包缺少关键 metadata"
            ),
            required=True,
            details={"blocked_assets": [item["asset_id"] for item in metadata_blocked]},
        ),
        _item(
            "package_files",
            "Package Files",
            "blocked" if file_blocked else "passed",
            (
                "全部 target package 已落在受管目录并可读取"
                if not file_blocked
                else f"{len(file_blocked)} 个交付包 target 缺失或不在受管目录"
            ),
            required=True,
            details={"blocked_assets": [item["asset_id"] for item in file_blocked]},
        ),
        _item(
            "license_scope",
            "License Scope",
            "blocked" if license_blocked else ("warning" if not normalized_required_licenses else "passed"),
            (
                f"license 白名单: {', '.join(normalized_required_licenses)}"
                if normalized_required_licenses
                else "未指定 required_license_names，当前只检查字段存在性"
            ),
            required=False,
            details={
                "required_license_names": normalized_required_licenses,
                "blocked_assets": [item["asset_id"] for item in license_blocked],
            },
        ),
        _item(
            "source_traceability",
            "Source Traceability",
            "warning" if traceability_warnings else "passed",
            (
                "source_path / tags / notes 已形成可追溯记录"
                if not traceability_warnings
                else f"{len(traceability_warnings)} 个交付包缺少 source_path、notes 或 tags"
            ),
            required=False,
            details={"warning_assets": [item["asset_id"] for item in traceability_warnings]},
        ),
        _item(
            "package_budget",
            "Package Budget",
            "warning" if budget_warnings else "passed",
            (
                "package size 与 estimated_memory_mb 基本一致"
                if not budget_warnings
                else f"{len(budget_warnings)} 个交付包缺少预算或 size 偏差较大"
            ),
            required=False,
            details={"warning_assets": [item["asset_id"] for item in budget_warnings]},
        ),
    ]

    gate = normalize_outsource_delivery_gate({
        "project_root": str(resolved_project_root),
        "runtime_root": str(resolved_runtime_root),
        "manifest_path": _relative_to_root(resolved_manifest_path, resolved_project_root),
        "package_root": _relative_to_root(resolved_package_root, resolved_project_root),
        "manifest_exists": manifest_exists,
        "package_root_exists": package_root_exists,
        "manifest_schema_version": manifest_schema_version,
        "manifest_asset_type": manifest_asset_type,
        "required_license_names": normalized_required_licenses,
        "mode": mode,
        "fail_on_warnings": fail_on_warnings,
        "delivery_count": len(deliveries),
        "checklist": checklist,
        "deliveries": deliveries,
        "notes": [
            "外包交付 gate 复用 assets/manifests/outsource_assets.json 作为唯一 manifest 来源。",
        ],
        "recommendations": _build_recommendations(checklist, deliveries),
        "contract_versions": {
            "outsource_delivery_gate": OUTSOURCE_DELIVERY_GATE_SCHEMA_VERSION,
        },
    })
    return gate


def _build_delivery_row(
    project_root: Path,
    package_root: Path,
    raw_entry: Dict[str, Any],
    *,
    required_license_names: List[str],
) -> Dict[str, Any]:
    asset_id = str(raw_entry.get("asset_id") or "").strip() or "unnamed_delivery"
    source_path_raw = str(raw_entry.get("source_path") or "").strip()
    target_path_raw = str(raw_entry.get("target_path") or "").strip()
    source_tool = str(raw_entry.get("source_tool") or "").strip().lower()
    package_version = str(raw_entry.get("package_version") or "").strip()
    license_name = str(raw_entry.get("license_name") or "").strip()
    estimated_memory_mb = _normalize_float(raw_entry.get("estimated_memory_mb"))
    notes = str(raw_entry.get("notes") or "").strip()
    tags = _clean_text_list(raw_entry.get("tags"))

    target_path = _resolve_project_path(project_root, target_path_raw) if target_path_raw else None
    source_path = _resolve_project_path(project_root, source_path_raw) if source_path_raw else None
    issues: List[str] = []
    warnings: List[str] = []

    if not target_path_raw:
        issues.append("target_path_missing: target_path 不能为空")
    elif target_path is None or not _is_relative_to(target_path, package_root):
        issues.append(f"target_path_scope: {asset_id} target_path 必须位于 res://{DEFAULT_OUTSOURCE_PACKAGE_ROOT}/")
    elif target_path.suffix.lower() != ".zip":
        issues.append(f"target_path_extension: {asset_id} target_path 必须使用 .zip")

    target_exists = bool(target_path and target_path.exists())
    target_size_mb = round(((target_path.stat().st_size / (1024 * 1024)) if target_exists else 0.0), 4)
    if target_path and not target_exists:
        issues.append(f"target_exists_missing: {asset_id} target package 不存在")
    elif target_exists and target_path and target_path.stat().st_size <= 0:
        issues.append(f"package_file_empty: {asset_id} target package 大小为 0")

    if not package_version:
        issues.append(f"package_version_missing: {asset_id} 缺少 package_version")
    elif not _PACKAGE_VERSION_RE.match(package_version):
        warnings.append(f"package_version_format: {asset_id} package_version 建议使用 semver 或 vYYYY_MM")

    if not license_name:
        issues.append(f"license_name_missing: {asset_id} 缺少 license_name")
    elif required_license_names and license_name not in required_license_names:
        issues.append(
            f"required_license_names_mismatch: {asset_id} license_name={license_name} 不在允许列表 {', '.join(required_license_names)}"
        )

    if source_tool not in _ALLOWED_SOURCE_TOOLS:
        issues.append(f"source_tool_invalid: {asset_id} source_tool 必须是 outsource 或 outsource_delivery")

    if not source_path_raw:
        warnings.append(f"source_path_missing: {asset_id} 缺少 source_path，可追溯性不足")
    elif source_path is None or not source_path.exists():
        warnings.append(f"source_missing: {asset_id} source_path 当前不可访问")
    elif source_path.suffix.lower() != ".zip":
        warnings.append(f"source_extension: {asset_id} source_path 建议保留为 zip 交付包")

    if not notes:
        warnings.append(f"notes_missing: {asset_id} 缺少交付说明 notes")
    if not tags:
        warnings.append(f"tags_missing: {asset_id} 缺少 tags")
    if estimated_memory_mb is None:
        warnings.append(f"estimated_memory_mb_missing: {asset_id} 缺少 estimated_memory_mb")
    elif target_exists and target_size_mb > estimated_memory_mb * 1.25:
        warnings.append(
            f"package_size_vs_estimate: {asset_id} target_size_mb={target_size_mb:.2f} 超出 estimated_memory_mb={estimated_memory_mb:.2f}"
        )

    status = "blocked" if issues else ("warning" if warnings else "passed")
    return {
        "asset_id": asset_id,
        "status": status,
        "package_version": package_version,
        "license_name": license_name,
        "source_tool": source_tool,
        "source_path": source_path_raw,
        "target_path": target_path_raw,
        "target_exists": target_exists,
        "target_size_mb": target_size_mb,
        "estimated_memory_mb": estimated_memory_mb,
        "issue_count": len(issues),
        "warning_count": len(warnings),
        "issues": issues,
        "warnings": warnings,
        "tags": tags,
        "notes": notes,
    }


def _build_recommendations(checklist: List[Dict[str, Any]], deliveries: List[Dict[str, Any]]) -> List[str]:
    recommendations: List[str] = []
    for item in checklist:
        if item["status"] == "blocked":
            recommendations.append(f"先修复 `{item['item_id']}`: {item['message']}")
        elif item["status"] == "warning":
            recommendations.append(f"复核 `{item['item_id']}`: {item['message']}")
    for delivery in deliveries:
        if delivery["status"] == "blocked":
            recommendations.append(f"交付包 `{delivery['asset_id']}` 仍未就绪，先补齐 metadata 和 target package。")
        elif delivery["status"] == "warning":
            recommendations.append(f"交付包 `{delivery['asset_id']}` 建议补 source_path / notes / tags 或预算说明。")

    deduped: List[str] = []
    seen = set()
    for item in recommendations:
        text = str(item or "").strip()
        if text and text not in seen:
            deduped.append(text)
            seen.add(text)
    return deduped[:10]


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


def _normalize_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return round(float(value), 4)
    except (TypeError, ValueError):
        return None


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


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except Exception:
        return False


def _has_any_issue(delivery: Dict[str, Any], prefixes: tuple[str, ...]) -> bool:
    return any(str(item).startswith(prefixes) for item in list(delivery.get("issues") or []))


def _has_any_warning(delivery: Dict[str, Any], prefixes: tuple[str, ...]) -> bool:
    return any(str(item).startswith(prefixes) for item in list(delivery.get("warnings") or []))

"""
Release candidate checklist builder.

P15 turns release manifests, QA gates, production readiness, and rollback
anchors into a single RC checklist contract for Portal, API, and MCP callers.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from agent_system.contracts import (
    RELEASE_CANDIDATE_CHECKLIST_SCHEMA_VERSION,
    normalize_release_candidate_checklist,
    normalize_release_summary,
)
from agent_system.tools.production_scale import build_production_readiness


DEFAULT_RELEASE_MANIFEST_PATH = "api_server/static/dist/release_manifest.json"

_PERFORMANCE_CHECK_NAMES = {
    "performance_budget",
    "fps_budget",
    "memory_peak_budget",
    "screenshot_diff",
    "draw_call_budget",
    "node_count_budget",
    "texture_memory_budget",
    "frame_spike_budget",
    "draw_call_regression",
}
_TELEMETRY_CHECK_NAMES = {"telemetry_health"}


def build_release_candidate_checklist(
    project_root: str | Path,
    runtime_root: Optional[str | Path] = None,
    *,
    release_manifest_path: str = "",
    evidence: Optional[Dict[str, Any]] = None,
    changed_paths: Optional[List[str]] = None,
    mode: str = "strict",
    fail_on_warnings: bool = False,
) -> Dict[str, Any]:
    resolved_project_root = Path(project_root).resolve()
    resolved_runtime_root = Path(runtime_root or Path.cwd()).resolve()
    manifest_state = _load_release_summary(resolved_runtime_root, release_manifest_path)
    release_summary = manifest_state["release_summary"]
    release_channel = str(release_summary.get("channel") or "").strip().lower()
    strict_release = release_channel == "release"
    effective_mode = "strict" if strict_release else mode
    effective_fail_on_warnings = True if strict_release else fail_on_warnings
    effective_evidence = _build_effective_evidence(
        resolved_project_root,
        manifest_state,
        release_summary,
        evidence=evidence,
    )
    effective_changed_paths = _build_effective_changed_paths(
        resolved_project_root,
        resolved_runtime_root,
        manifest_state,
        release_summary,
        changed_paths=changed_paths,
    )
    production_readiness = build_production_readiness(
        resolved_project_root,
        runtime_root=resolved_runtime_root,
        scenario_id="release_candidate",
        evidence=effective_evidence,
        changed_paths=effective_changed_paths,
        notes="release_candidate_checklist",
        mode=effective_mode,
        fail_on_warnings=effective_fail_on_warnings,
    )

    quality_gate = dict(release_summary.get("quality_gate") or {})
    release_dir_path = manifest_state.get("release_dir_path")
    release_dir_relative = _relative_to_root(release_dir_path, resolved_runtime_root)
    notes = []
    if manifest_state["manifest_source"] == "versioned_fallback":
        notes.append("Stable release_manifest.json 缺失，当前使用最近一次 versioned manifest 生成 RC 清单。")
    if strict_release and (
        str(mode or "strict").strip().lower() != "strict"
        or not bool(fail_on_warnings)
    ):
        notes.append("release 渠道已强制启用 strict + fail_on_warnings，缺失 QA 证据会直接阻断 RC。")

    items = [
        _item(
            "release_manifest",
            "Release Manifest",
            "blocked" if not manifest_state["manifest_exists"] else (
                "warning" if manifest_state["manifest_source"] == "versioned_fallback" else "passed"
            ),
            "Release manifest 已加载"
            if manifest_state["manifest_exists"]
            else "未找到可用的 release_manifest.json",
            required=True,
            details={
                "manifest_path": manifest_state["manifest_path"],
                "manifest_source": manifest_state["manifest_source"],
            },
        ),
        _item(
            "build_metadata",
            "Build Metadata",
            "passed" if _has_build_metadata(release_summary) else "blocked",
            _build_metadata_message(release_summary),
            required=True,
            details={
                "build_id": release_summary.get("build_id"),
                "version": release_summary.get("version"),
                "channel": release_summary.get("channel"),
            },
        ),
        _item(
            "release_notes",
            "Release Notes",
            "passed" if manifest_state["release_notes_exists"] else "blocked",
            "Release notes 已生成" if manifest_state["release_notes_exists"] else "release_notes.md 缺失",
            required=True,
            details={"release_notes_path": manifest_state["release_notes_path"]},
        ),
        _item(
            "qa_gate_report",
            "QA Gate Report",
            "passed" if manifest_state["qa_gate_report_exists"] else "blocked",
            "QA gate report 已生成" if manifest_state["qa_gate_report_exists"] else "qa_gate_report.md 缺失",
            required=True,
            details={"qa_gate_report_path": manifest_state["qa_gate_report_path"]},
        ),
        _item(
            "release_outputs",
            "Release Outputs",
            "passed" if (manifest_state["build_log_exists"] and release_dir_path and release_dir_path.exists()) else "blocked",
            _build_release_output_message(release_dir_relative, manifest_state, release_summary),
            required=True,
            details={
                "release_dir": release_dir_relative or release_summary.get("release_dir") or "",
                "file_count": len(release_summary.get("files") or []),
                "build_log_path": manifest_state["build_log_path"],
            },
        ),
        _item(
            "feature_approval",
            "Feature Approval",
            "passed" if _feature_status(release_summary) == "approved" else "blocked",
            f"Feature status: {_feature_status(release_summary) or 'unknown'}",
            required=True,
            details={"feature_status": _feature_status(release_summary)},
        ),
        _item(
            "acceptance_checklist",
            "Acceptance Checklist",
            *_summarize_acceptance_checklist(release_summary),
        ),
        _item(
            "qa_assertions",
            "Assertion QA",
            *_summarize_qa_assertions(release_summary),
        ),
        _item(
            "visual_regression",
            "Visual Regression",
            *_summarize_visual_regression(release_summary),
        ),
        _item(
            "quality_gate",
            "Quality Gate",
            *_summarize_quality_gate(quality_gate),
        ),
        _item(
            "performance_gate",
            "Performance Gate",
            *_summarize_named_checks(quality_gate, _PERFORMANCE_CHECK_NAMES, "性能预算与回归门禁"),
        ),
        _item(
            "telemetry_gate",
            "Telemetry Gate",
            *_summarize_named_checks(quality_gate, _TELEMETRY_CHECK_NAMES, "Telemetry/隐私门禁"),
        ),
        _item(
            "rollback_ready",
            "Rollback Ready",
            "passed" if bool(release_summary.get("rollback_hint")) and bool(release_dir_path and release_dir_path.exists()) else "blocked",
            release_summary.get("rollback_hint") or "未声明 rollback_hint",
            required=True,
            details={"rollback_hint": release_summary.get("rollback_hint") or ""},
        ),
        _item(
            "channel_ready",
            "Channel Readiness",
            "passed" if str(release_summary.get("channel") or "").strip().lower() == "release" else "warning",
            f"当前渠道: {release_summary.get('channel') or 'unknown'}",
            required=False,
            details={"channel": release_summary.get("channel") or ""},
        ),
        _item(
            "production_gate",
            "Production Gate",
            _map_stage_status(production_readiness.get("readiness_status")),
            str(production_readiness.get("message") or "production readiness evaluated"),
            required=True,
            details={
                "scenario_id": production_readiness.get("scenario_id"),
                "blocking_checks": list(production_readiness.get("blocking_checks") or []),
                "warning_checks": list(production_readiness.get("warning_checks") or []),
                "exit_code": production_readiness.get("exit_code"),
            },
        ),
    ]

    recommendations = _build_recommendations(items, production_readiness)
    payload = normalize_release_candidate_checklist({
        "project_root": str(resolved_project_root),
        "runtime_root": str(resolved_runtime_root),
        "release_manifest_path": manifest_state["manifest_path"],
        "release_manifest_source": manifest_state["manifest_source"],
        "release_notes_path": manifest_state["release_notes_path"],
        "qa_gate_report_path": manifest_state["qa_gate_report_path"],
        "build_log_path": manifest_state["build_log_path"],
        "release_summary": release_summary,
        "quality_gate": quality_gate,
        "production_readiness": production_readiness,
        "checklist": items,
        "recommendations": recommendations,
        "notes": notes,
        "contract_versions": {
            "release_candidate_checklist": RELEASE_CANDIDATE_CHECKLIST_SCHEMA_VERSION,
            "release_summary": release_summary.get("schema_version", ""),
            "quality_gate": quality_gate.get("schema_version", ""),
            "production_readiness": production_readiness.get("schema_version", ""),
        },
        "mode": str(production_readiness.get("mode") or effective_mode),
        "fail_on_warnings": bool(production_readiness.get("fail_on_warnings") or effective_fail_on_warnings),
        "derived_evidence": effective_evidence,
        "changed_paths": effective_changed_paths,
    })
    return payload


def _load_release_summary(runtime_root: Path, explicit_manifest_path: str) -> Dict[str, Any]:
    manifest_path, manifest_source, stable_manifest_path = _resolve_manifest_path(runtime_root, explicit_manifest_path)
    manifest_exists = bool(manifest_path and manifest_path.exists())
    release_summary = normalize_release_summary({})
    manifest_error = ""
    if manifest_exists and manifest_path is not None:
        try:
            release_summary = normalize_release_summary(json.loads(manifest_path.read_text(encoding="utf-8")))
        except Exception as exc:
            manifest_error = str(exc)
    release_dir_path = _resolve_runtime_path(runtime_root, release_summary.get("release_dir")) if manifest_exists else None
    release_notes_path = _resolve_runtime_path(
        runtime_root,
        release_summary.get("release_notes_path"),
        fallback=(release_dir_path / "release_notes.md") if release_dir_path else None,
    )
    qa_gate_report_path = _resolve_runtime_path(
        runtime_root,
        "",
        fallback=(release_dir_path / "qa_gate_report.md") if release_dir_path else None,
    )
    build_log_path = _resolve_runtime_path(
        runtime_root,
        release_summary.get("build_log_path"),
        fallback=(release_dir_path / "build.log") if release_dir_path else None,
    )
    return {
        "manifest_path": _relative_to_root(manifest_path, runtime_root) if manifest_path else (explicit_manifest_path or DEFAULT_RELEASE_MANIFEST_PATH),
        "manifest_source": manifest_source,
        "manifest_exists": manifest_exists,
        "manifest_error": manifest_error,
        "stable_manifest_exists": stable_manifest_path.exists(),
        "release_summary": release_summary,
        "release_dir_path": release_dir_path,
        "release_notes_path": _relative_to_root(release_notes_path, runtime_root),
        "release_notes_exists": bool(release_notes_path and release_notes_path.exists()),
        "qa_gate_report_path": _relative_to_root(qa_gate_report_path, runtime_root),
        "qa_gate_report_exists": bool(qa_gate_report_path and qa_gate_report_path.exists()),
        "build_log_path": _relative_to_root(build_log_path, runtime_root),
        "build_log_exists": bool(build_log_path and build_log_path.exists()),
    }


def _resolve_manifest_path(runtime_root: Path, explicit_manifest_path: str) -> tuple[Optional[Path], str, Path]:
    stable_manifest_path = (runtime_root / DEFAULT_RELEASE_MANIFEST_PATH).resolve()
    if explicit_manifest_path:
        explicit_path = _resolve_runtime_path(runtime_root, explicit_manifest_path)
        return explicit_path, "explicit", stable_manifest_path
    if stable_manifest_path.exists():
        return stable_manifest_path, "stable", stable_manifest_path
    versioned_manifests = sorted(
        (runtime_root / "api_server" / "static" / "dist").glob("*/release_manifest.json"),
        key=lambda path: path.stat().st_mtime_ns,
        reverse=True,
    )
    if versioned_manifests:
        return versioned_manifests[0].resolve(), "versioned_fallback", stable_manifest_path
    return stable_manifest_path, "missing", stable_manifest_path


def _resolve_runtime_path(runtime_root: Path, raw_path: Any, fallback: Optional[Path] = None) -> Optional[Path]:
    text = str(raw_path or "").strip()
    if not text:
        return fallback.resolve() if fallback else None
    normalized = text.replace("\\", "/")
    candidate = Path(normalized)
    if candidate.is_absolute():
        return candidate.resolve()
    return (runtime_root / normalized).resolve()


def _relative_to_root(path: Optional[Path], runtime_root: Path) -> str:
    if path is None:
        return ""
    try:
        return path.resolve().relative_to(runtime_root.resolve()).as_posix()
    except Exception:
        return str(path.resolve())


def _build_effective_evidence(
    project_root: Path,
    manifest_state: Dict[str, Any],
    release_summary: Dict[str, Any],
    *,
    evidence: Optional[Dict[str, Any]],
) -> Dict[str, bool]:
    qa_evidence = dict(release_summary.get("qa_evidence") or {})
    derived = {
        "feature_approval": _feature_status(release_summary) == "approved",
        "quality_gate": bool(release_summary.get("quality_gate")),
        "qa_evidence": bool(
            qa_evidence.get("scene_path")
            or int(qa_evidence.get("assertion_node_count") or 0) > 0
            or str(qa_evidence.get("smoke_status") or "").strip().lower() != "skipped"
            or str(qa_evidence.get("screenshot_path") or "").strip()
        ),
        "release_manifest": bool(manifest_state.get("manifest_exists")),
        "rollback": bool(release_summary.get("rollback_hint")),
        "tests": (project_root / "tests").exists(),
        "docs": (project_root / "README.md").exists() and bool(manifest_state.get("release_notes_exists")),
    }
    for key, value in dict(evidence or {}).items():
        normalized = str(key or "").strip().lower()
        if not normalized:
            continue
        if isinstance(value, bool):
            derived[normalized] = value
        else:
            derived[normalized] = bool(str(value or "").strip())
    return derived


def _build_effective_changed_paths(
    project_root: Path,
    runtime_root: Path,
    manifest_state: Dict[str, Any],
    release_summary: Dict[str, Any],
    *,
    changed_paths: Optional[List[str]],
) -> List[str]:
    explicit = []
    seen = set()
    for raw_path in list(changed_paths or []):
        text = str(raw_path or "").strip().replace("\\", "/").strip("/")
        if text and text not in seen:
            explicit.append(text)
            seen.add(text)
    if explicit:
        return explicit

    derived: List[str] = []
    for relative in (
        manifest_state.get("manifest_path"),
        manifest_state.get("release_notes_path"),
        manifest_state.get("qa_gate_report_path"),
        manifest_state.get("build_log_path"),
    ):
        text = str(relative or "").strip().replace("\\", "/").strip("/")
        if text and text not in seen:
            derived.append(text)
            seen.add(text)
    for candidate in (
        "README.md" if (project_root / "README.md").exists() else "",
        "tests/baselines/performance" if (runtime_root / "tests" / "baselines" / "performance").exists() else "",
    ):
        text = str(candidate or "").strip().replace("\\", "/").strip("/")
        if text and text not in seen:
            derived.append(text)
            seen.add(text)
    if not derived:
        derived.append(DEFAULT_RELEASE_MANIFEST_PATH)
    return derived


def _has_build_metadata(release_summary: Dict[str, Any]) -> bool:
    return all(
        str(release_summary.get(key) or "").strip()
        for key in ("build_id", "version", "channel", "release_dir")
    )


def _build_metadata_message(release_summary: Dict[str, Any]) -> str:
    if _has_build_metadata(release_summary):
        return (
            f"Build `{release_summary.get('build_id')}` / "
            f"version `{release_summary.get('version')}` / "
            f"channel `{release_summary.get('channel')}`"
        )
    return "build_id / version / channel / release_dir 至少缺少一项"


def _build_release_output_message(
    release_dir_relative: str,
    manifest_state: Dict[str, Any],
    release_summary: Dict[str, Any],
) -> str:
    file_count = len(release_summary.get("files") or [])
    if manifest_state["build_log_exists"] and release_dir_relative:
        return f"Release 目录 `{release_dir_relative}` 已准备完成，记录文件 {file_count} 个"
    return "release_dir 或 build.log 缺失"


def _feature_status(release_summary: Dict[str, Any]) -> str:
    feature = dict(release_summary.get("feature") or {})
    return str(feature.get("feature_status") or "").strip().lower()


def _summarize_acceptance_checklist(release_summary: Dict[str, Any]) -> tuple[str, str, bool, Dict[str, Any]]:
    checklist = list(release_summary.get("acceptance_checklist") or [])
    channel = str(release_summary.get("channel") or "").strip().lower()
    strict_release = channel == "release"
    if not checklist:
        return (
            "blocked" if strict_release else "warning",
            "release 渠道未记录 acceptance_checklist" if strict_release else "未记录 acceptance_checklist",
            False,
            {"checklist_count": 0, "channel": channel},
        )

    blocked = [item for item in checklist if str(item.get("status") or "").strip().lower() == "blocked"]
    pending = [item for item in checklist if str(item.get("status") or "").strip().lower() == "pending"]
    if blocked:
        status = "blocked"
        message = f"{len(blocked)} 个验收项仍被阻断"
    elif pending:
        status = "blocked" if strict_release else "warning"
        message = (
            f"release 渠道仍有 {len(pending)} 个验收项待确认"
            if strict_release
            else f"{len(pending)} 个验收项仍待确认"
        )
    else:
        status = "passed"
        message = f"{len(checklist)} 个验收项已就绪"
    return status, message, False, {"checklist_count": len(checklist), "channel": channel}


def _summarize_quality_gate(quality_gate: Dict[str, Any]) -> tuple[str, str, bool, Dict[str, Any]]:
    if not quality_gate:
        return "blocked", "未找到 quality_gate", True, {}
    if quality_gate.get("passed"):
        return (
            "passed",
            f"Quality gate 通过，checks={len(quality_gate.get('checks') or [])}",
            True,
            {"blocked_checks": list(quality_gate.get("blocked_checks") or [])},
        )
    blocked_checks = list(quality_gate.get("blocked_checks") or [])
    message = (
        f"Quality gate 阻断: {', '.join(blocked_checks)}"
        if blocked_checks
        else "Quality gate 未通过"
    )
    return "blocked", message, True, {"blocked_checks": blocked_checks}


def _summarize_qa_assertions(release_summary: Dict[str, Any]) -> tuple[str, str, bool, Dict[str, Any]]:
    qa_evidence = dict(release_summary.get("qa_evidence") or {})
    channel = str(release_summary.get("channel") or "").strip().lower()
    strict_release = channel == "release"
    assertion_status = str(qa_evidence.get("assertion_status") or "skipped").strip().lower() or "skipped"
    assertion_count = int(qa_evidence.get("assertion_node_count") or 0)
    if assertion_status == "passed" and assertion_count > 0:
        return "passed", f"已记录 {assertion_count} 个断言节点", True, {
            "assertion_node_count": assertion_count,
            "asserted_nodes": list(qa_evidence.get("asserted_nodes") or []),
            "scene_path": qa_evidence.get("scene_path") or "",
        }

    if assertion_status in {"blocked", "warning"}:
        status = "blocked" if strict_release else assertion_status
        message = str(qa_evidence.get("assertion_message") or "断言型 QA 未通过").strip()
    else:
        status = "blocked" if strict_release else "warning"
        message = "release 渠道未记录断言型 QA" if strict_release else "未记录断言型 QA"
        if assertion_count > 0:
            message = f"已记录 {assertion_count} 个断言节点，但断言结果仍未收口"
    return status, message, True, {
        "assertion_node_count": assertion_count,
        "asserted_nodes": list(qa_evidence.get("asserted_nodes") or []),
        "scene_path": qa_evidence.get("scene_path") or "",
    }


def _summarize_visual_regression(release_summary: Dict[str, Any]) -> tuple[str, str, bool, Dict[str, Any]]:
    qa_evidence = dict(release_summary.get("qa_evidence") or {})
    channel = str(release_summary.get("channel") or "").strip().lower()
    strict_release = channel == "release"
    screenshot_status = str(qa_evidence.get("screenshot_status") or "skipped").strip().lower() or "skipped"
    screenshot_path = str(qa_evidence.get("screenshot_path") or "").strip()
    diff_ratio = qa_evidence.get("screenshot_diff_ratio")
    threshold = qa_evidence.get("max_screenshot_diff_ratio")

    if screenshot_status == "passed" and screenshot_path:
        message = f"已记录截图证据 {screenshot_path}"
        if diff_ratio is not None and threshold is not None:
            message = f"截图 diff {float(diff_ratio):.4f} / 阈值 {float(threshold):.4f}"
        return "passed", message, True, {
            "screenshot_path": screenshot_path,
            "screenshot_diff_ratio": diff_ratio,
            "max_screenshot_diff_ratio": threshold,
            "scene_path": qa_evidence.get("scene_path") or "",
        }

    if screenshot_status in {"blocked", "warning"}:
        status = "blocked" if strict_release and screenshot_status != "blocked" else screenshot_status
        message = str(qa_evidence.get("screenshot_message") or "visual regression 未通过").strip()
    else:
        status = "blocked" if strict_release else "warning"
        message = "release 渠道未记录 screenshot diff / visual regression 证据" if strict_release else "未记录 screenshot diff / visual regression 证据"
        if screenshot_path:
            message = f"已记录截图 {screenshot_path}，但未产出可复核的 diff 结论"
    return status, message, True, {
        "screenshot_path": screenshot_path,
        "screenshot_diff_ratio": diff_ratio,
        "max_screenshot_diff_ratio": threshold,
        "scene_path": qa_evidence.get("scene_path") or "",
    }


def _summarize_named_checks(
    quality_gate: Dict[str, Any],
    check_names: set[str],
    label: str,
) -> tuple[str, str, bool, Dict[str, Any]]:
    checks = [
        check for check in list(quality_gate.get("checks") or [])
        if str(check.get("name") or "") in check_names
    ]
    if not checks:
        return "warning", f"{label}: 未记录相关 checks", False, {"check_count": 0}

    blocked = [check for check in checks if check.get("status") == "blocked"]
    warnings = [check for check in checks if check.get("status") == "warning"]
    skipped = [check for check in checks if check.get("status") == "skipped"]
    if blocked:
        status = "blocked"
        message = f"{label}: {', '.join(str(check.get('name') or '') for check in blocked)}"
    elif warnings:
        status = "warning"
        message = f"{label}: {', '.join(str(check.get('name') or '') for check in warnings)}"
    elif skipped:
        status = "warning"
        message = f"{label}: {', '.join(str(check.get('name') or '') for check in skipped)} 仍为 skipped"
    else:
        status = "passed"
        message = f"{label}: {len(checks)} 项通过"
    return status, message, False, {"check_names": [str(check.get("name") or "") for check in checks]}


def _map_stage_status(status: Any) -> str:
    normalized = str(status or "").strip().lower()
    if normalized in {"blocked", "warning", "passed"}:
        return normalized
    return "warning" if normalized else "blocked"


def _item(
    item_id: str,
    label: str,
    status: str,
    message: str,
    required: bool = True,
    details: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    return {
        "item_id": item_id,
        "label": label,
        "status": status,
        "required": bool(required),
        "message": message,
        "details": dict(details or {}),
    }


def _build_recommendations(items: List[Dict[str, Any]], production_readiness: Dict[str, Any]) -> List[str]:
    recommendations: List[str] = []
    for item in items:
        if item["status"] == "blocked":
            recommendations.append(f"先修复 `{item['item_id']}`: {item['message']}")
        elif item["status"] == "warning":
            recommendations.append(f"复核 `{item['item_id']}`: {item['message']}")
    recommendations.extend(str(item) for item in list(production_readiness.get("recommendations") or []))

    deduped: List[str] = []
    seen = set()
    for item in recommendations:
        text = str(item or "").strip()
        if text and text not in seen:
            deduped.append(text)
            seen.add(text)
    return deduped[:10]

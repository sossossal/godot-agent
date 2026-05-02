"""
Unified skill result contract.
"""

from __future__ import annotations

from typing import Any, Dict, List


SKILL_RESULT_SCHEMA_VERSION = "1.0"


def _normalize_dict(value: Any) -> Dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _artifact_summary(artifacts: List[Any]) -> Dict[str, Any]:
    by_type: Dict[str, int] = {}
    paths: List[str] = []
    for artifact in artifacts or []:
        artifact_type = str(getattr(artifact, "type", "") or "").strip() or "artifact"
        artifact_path = str(getattr(artifact, "path", "") or "").strip()
        by_type[artifact_type] = by_type.get(artifact_type, 0) + 1
        if artifact_path:
            paths.append(artifact_path)
    return {
        "count": len(artifacts or []),
        "by_type": by_type,
        "paths": paths[:10],
    }


def normalize_skill_validation(value: Any) -> Dict[str, Any]:
    raw = _normalize_dict(value)
    checks = list(raw.get("checks") or [])
    issues = [str(item).strip() for item in list(raw.get("issues") or []) if str(item).strip()]
    payload = {
        "passed": bool(raw.get("passed", not issues)),
        "issues": issues,
        "checks": checks,
    }
    layout_check = raw.get("layout_check")
    if isinstance(layout_check, dict):
        payload["layout_check"] = dict(layout_check)
    return payload


def normalize_skill_rollback(value: Any) -> Dict[str, Any]:
    raw = _normalize_dict(value)
    backup_paths = [str(item).strip() for item in list(raw.get("backup_paths") or []) if str(item).strip()]
    return {
        "available": bool(raw.get("available")),
        "strategy": str(raw.get("strategy") or "").strip(),
        "backup_paths": backup_paths,
    }


def build_skill_result_envelope(
    *,
    skill_name: str,
    skill_category: str,
    skill_version: str,
    success: bool,
    message: str,
    params: Dict[str, Any] | None,
    artifacts: List[Any] | None,
    validation: Dict[str, Any] | None = None,
    rollback: Dict[str, Any] | None = None,
    quality_gate: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    normalized_validation = normalize_skill_validation(validation)
    normalized_rollback = normalize_skill_rollback(rollback)
    return {
        "schema_version": SKILL_RESULT_SCHEMA_VERSION,
        "skill_name": skill_name,
        "skill_category": skill_category,
        "skill_version": skill_version,
        "status": "success" if success else "failed",
        "summary": {
            "message": str(message or "").strip(),
            "artifact_summary": _artifact_summary(list(artifacts or [])),
        },
        "params": dict(params or {}),
        "validation": normalized_validation,
        "rollback": normalized_rollback,
        "quality_gate": dict(quality_gate or {}),
    }


def record_skill_result_on_task(task: Any, skill_result: Dict[str, Any] | None) -> None:
    if not skill_result:
        return
    context = dict(getattr(task, "context", {}) or {})
    history = list(context.get("skill_runs") or [])
    history.append(skill_result)
    context["last_skill_result"] = skill_result
    context["skill_runs"] = history[-20:]
    context.setdefault("contract_versions", {})
    context["contract_versions"]["skill_result"] = SKILL_RESULT_SCHEMA_VERSION
    task.context = context

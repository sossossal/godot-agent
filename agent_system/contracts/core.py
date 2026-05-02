"""
统一契约层核心定义。

当前先覆盖:
- Task feature context
- Feature review history
- Release quality gate
- Release summary
- Telemetry summary
- Performance summary
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List


FEATURE_CONTEXT_SCHEMA_VERSION = "1.5"
QUALITY_GATE_SCHEMA_VERSION = "1.0"
RELEASE_SUMMARY_SCHEMA_VERSION = "1.0"
RELEASE_QA_EVIDENCE_SCHEMA_VERSION = "1.0"
BALANCE_ANALYSIS_SCHEMA_VERSION = "1.0"
BALANCE_VERSION_COMPARE_SCHEMA_VERSION = "1.0"
TELEMETRY_SUMMARY_SCHEMA_VERSION = "1.4"
PERFORMANCE_SUMMARY_SCHEMA_VERSION = "1.1"
PRESENTATION_PROFILE_SCHEMA_VERSION = "1.0"
LIVEOPS_PROFILE_SCHEMA_VERSION = "1.0"
GAME_CREATION_PROFILE_SCHEMA_VERSION = "1.0"
SCENE_GRAPH_AUDIT_SCHEMA_VERSION = "1.0"
GAME_CREATION_REVIEW_SCHEMA_VERSION = "1.0"
GAME_CREATION_REPLAY_SCHEMA_VERSION = "1.0"
GAME_CREATION_TEMPLATE_MIGRATION_SCHEMA_VERSION = "1.0"
SCENE_GRAPH_SNAPSHOT_SCHEMA_VERSION = "1.0"
ROADMAP_STATUS_SCHEMA_VERSION = "1.0"
GOVERNANCE_POLICY_SCHEMA_VERSION = "1.0"
CHANGE_ADMISSION_SCHEMA_VERSION = "1.0"
GOVERNANCE_ENFORCEMENT_SCHEMA_VERSION = "1.0"
PRODUCTION_SCENARIO_SCHEMA_VERSION = "1.0"
PRODUCTION_READINESS_SCHEMA_VERSION = "1.0"
RELEASE_CANDIDATE_CHECKLIST_SCHEMA_VERSION = "1.0"
AGENT_PROVIDER_COMPAT_SCHEMA_VERSION = "1.0"
RELEASE_REVIEW_BUNDLE_SCHEMA_VERSION = "1.5"
RELEASE_DISTRIBUTION_BUNDLE_SCHEMA_VERSION = "1.0"
RELEASE_CAPABILITY_REGISTRY_SCHEMA_VERSION = "1.0"
RELEASE_CAPABILITY_POLICY_SCHEMA_VERSION = "1.0"
RELEASE_RUNTIME_ASSEMBLY_SCHEMA_VERSION = "1.0"
RELEASE_DELIVERY_READINESS_SCHEMA_VERSION = "1.1"
RELEASE_LIVE_EVENT_STREAM_SCHEMA_VERSION = "1.0"
RELEASE_LIVE_DISPATCH_PREFLIGHT_SCHEMA_VERSION = "1.0"
RELEASE_LIVE_DISPATCH_RESULT_SCHEMA_VERSION = "1.0"
RELEASE_LIVE_DISPATCH_AUDIT_SCHEMA_VERSION = "1.0"
RELEASE_ARTIFACT_MANIFEST_SCHEMA_VERSION = "1.0"

FEATURE_STATUS_VALUES = {"pending_review", "pending_acceptance", "approved", "returned"}
FEATURE_PRIORITY_VALUES = {"low", "medium", "high", "critical"}
FEATURE_RISK_VALUES = {"low", "medium", "high"}
QUALITY_GATE_CHECK_STATUSES = {"passed", "warning", "blocked", "skipped"}
CHECKLIST_STATUS_VALUES = {"ready", "blocked", "pending"}
BALANCE_ANALYSIS_TABLE_TYPES = {"enemy", "loot", "quest"}
TELEMETRY_PRIVACY_LEVELS = {"anonymous", "internal", "restricted"}
PRESENTATION_TYPES = {"animation", "vfx", "shader", "audio"}
LIVEOPS_TYPES = {"remote_config", "experiment_catalog"}
LIVEOPS_ENVIRONMENTS = {"dev", "qa", "live"}
LIVEOPS_ROLLOUT_STRATEGIES = {"global", "percentage", "segment", "whitelist"}
LIVEOPS_CONFIG_VALUE_TYPES = {"bool", "int", "float", "string", "json"}
LIVEOPS_EXPERIMENT_STATUSES = {"draft", "running", "paused", "completed", "archived"}
PLATFORM_DELIVERY_PROFILE_SCHEMA_VERSION = "1.0"
OUTSOURCE_DELIVERY_GATE_SCHEMA_VERSION = "1.0"
ASSET_REVIEW_WORKFLOW_SCHEMA_VERSION = "1.0"
BUILD_RUN_MATRIX_SCHEMA_VERSION = "1.0"
SCENE_OWNERSHIP_BOARD_SCHEMA_VERSION = "1.0"
RELEASE_PROMOTION_PLAN_SCHEMA_VERSION = "1.1"
RELEASE_PROMOTION_HISTORY_SCHEMA_VERSION = "1.0"
RELEASE_EXECUTION_STATUS_SCHEMA_VERSION = "1.1"
PLATFORM_DELIVERY_MODES = {"offline", "cloud_optional", "cloud_required"}
PLATFORM_DELIVERY_TRANSPORTS = {"offline", "enet", "websocket", "steam"}
ASSET_REVIEW_STATUS_VALUES = {"pending_review", "approved", "returned"}
RELEASE_CAPABILITY_SURFACE_TYPES = {"tool", "command", "gateway_method", "hook"}
RELEASE_CAPABILITY_RISK_LEVELS = {"low", "medium", "high", "critical"}
RELEASE_CAPABILITY_SANDBOX_PROFILES = {
    "read_only",
    "workspace_write",
    "local_process",
    "browser_automation",
    "godot_gui",
    "network_bridge",
    "release_write",
}
RELEASE_CAPABILITY_POLICY_ROUTE_KINDS = {
    "portal",
    "api",
    "ci_rehearsal",
    "local_replay",
    "github_workflow",
}


def _normalize_choice(value: Any, allowed: set[str], default: str) -> str:
    if value is None:
        return default
    normalized = str(value).strip().lower()
    return normalized if normalized in allowed else default


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


def _as_dict(value: Any) -> Dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _normalize_flow_statuses(value: Any) -> Dict[str, str]:
    if not isinstance(value, dict):
        return {}

    normalized: Dict[str, str] = {}
    for raw_key, raw_value in value.items():
        key = str(raw_key).strip()
        if not key or (key != "flow" and not key.endswith("_flow")):
            continue
        status = str(raw_value).strip().lower()
        if status in QUALITY_GATE_CHECK_STATUSES:
            normalized[key] = status
    return normalized


def _normalize_count_map(value: Any) -> Dict[str, int]:
    if not isinstance(value, dict):
        return {}
    normalized: Dict[str, int] = {}
    for raw_key, raw_value in value.items():
        key = str(raw_key).strip()
        if not key:
            continue
        try:
            count = max(int(raw_value or 0), 0)
        except (TypeError, ValueError):
            count = 0
        if count:
            normalized[key] = count
    return normalized


def _worst_gate_status(statuses: List[str], *, default: str = "passed") -> str:
    priorities = {"blocked": 3, "warning": 2, "passed": 1, "skipped": 0}
    worst = default
    worst_priority = priorities.get(default, 1)
    for raw_status in statuses:
        status = _normalize_choice(raw_status, QUALITY_GATE_CHECK_STATUSES, "warning")
        priority = priorities.get(status, priorities["warning"])
        if priority > worst_priority:
            worst = status
            worst_priority = priority
    return worst


def _get_field(value: Any, name: str, default: Any = None) -> Any:
    if isinstance(value, dict):
        return value.get(name, default)
    return getattr(value, name, default)


def _normalize_status_value(value: Any) -> str:
    if hasattr(value, "value"):
        return str(value.value)
    return str(value or "").strip().lower()


def _default_acceptance_criteria(prompt: str, steps: List[Any]) -> List[str]:
    criteria: List[str] = []
    for step in steps[:5]:
        description = str(_get_field(step, "description", "") or "").strip()
        name = str(_get_field(step, "name", "") or "").strip()
        label = description or name
        if label:
            criteria.append(f"{name or '步骤'} 可验证: {label}")
    if criteria:
        return criteria
    normalized_prompt = str(prompt or "").strip()
    return [f"任务结果可复核: {normalized_prompt or '当前任务'}"]


def _build_change_summary(status_value: str, steps: List[Any], artifacts: List[Any], message: str) -> List[str]:
    if status_value in {"pending", "planning", "awaiting_confirmation"}:
        return []

    lines: List[str] = []
    if steps:
        completed_steps = [
            str(_get_field(step, "name", "") or "").strip()
            for step in steps
            if _normalize_status_value(_get_field(step, "status")) == "success"
        ]
        lines.append(
            f"完成步骤 {len(completed_steps)}/{len(steps)}: {', '.join(item for item in completed_steps if item) if completed_steps else '暂无'}"
        )

    if artifacts:
        artifact_counts: Dict[str, int] = {}
        for artifact in artifacts:
            artifact_type = str(_get_field(artifact, "type", "") or "").strip() or "artifact"
            artifact_counts[artifact_type] = artifact_counts.get(artifact_type, 0) + 1
        summary = ", ".join(f"{artifact_type} x{count}" for artifact_type, count in sorted(artifact_counts.items()))
        lines.append(f"新增产物: {summary}")

    if message and message != status_value:
        lines.append(f"当前结果: {message}")

    return lines


def _build_feature_artifact_links(artifacts: List[Any]) -> List[Dict[str, Any]]:
    links: List[Dict[str, Any]] = []
    for index, artifact in enumerate(artifacts, start=1):
        path = str(_get_field(artifact, "path", "") or "").strip()
        name = str(_get_field(artifact, "name", "") or "").strip() or path or f"artifact_{index}"
        artifact_type = str(_get_field(artifact, "type", "") or "").strip() or "artifact"
        metadata = _as_dict(_get_field(artifact, "metadata", {}))
        links.append({
            "artifact_id": str(metadata.get("artifact_id") or name or f"artifact_{index}").strip(),
            "label": name,
            "status": _normalize_choice(metadata.get("status"), QUALITY_GATE_CHECK_STATUSES, "passed"),
            "required": bool(metadata.get("required", True)),
            "path": path,
            "kind": artifact_type,
            "summary": str(metadata.get("summary") or "").strip(),
            "details": dict(metadata),
        })
    return links


def normalize_feature_external_links(value: Any) -> List[Dict[str, str]]:
    links = value if isinstance(value, list) else []
    normalized: List[Dict[str, str]] = []
    for index, item in enumerate(links, start=1):
        raw = _as_dict(item)
        url = str(raw.get("url") or raw.get("href") or raw.get("path") or "").strip()
        if not url:
            continue
        link_type = str(raw.get("type") or raw.get("kind") or "reference").strip().lower() or "reference"
        normalized.append({
            "link_id": str(raw.get("link_id") or raw.get("id") or f"external_link_{index}").strip() or f"external_link_{index}",
            "label": str(raw.get("label") or raw.get("title") or link_type).strip() or link_type,
            "url": url,
            "type": link_type,
            "status": _normalize_choice(raw.get("status"), QUALITY_GATE_CHECK_STATUSES, "skipped"),
            "summary": str(raw.get("summary") or raw.get("note") or "").strip(),
        })
    return normalized[-20:]


def _derive_feature_status(task_status: str, current_status: Any) -> str:
    normalized = _normalize_choice(current_status, FEATURE_STATUS_VALUES, "pending_review")
    if task_status == "success":
        return normalized if normalized in {"approved", "returned"} else "pending_acceptance"
    if task_status in {"failed", "rolled_back", "cancelled"}:
        return "returned"
    return normalized


def _normalize_acceptance_checklist_item(
    item: Any,
    *,
    default_validation_method: str = "",
    default_blockers: List[str] | None = None,
) -> Dict[str, Any]:
    raw = _as_dict(item)
    return {
        "label": str(raw.get("label") or "").strip(),
        "status": _normalize_choice(raw.get("status"), CHECKLIST_STATUS_VALUES, "pending"),
        "validation_method": str(raw.get("validation_method") or default_validation_method or "").strip(),
        "blockers": _clean_text_list(raw.get("blockers")) or list(default_blockers or []),
    }


def _build_acceptance_checklist(
    task_status: str,
    steps: List[Any],
    criteria: List[str],
    *,
    validation_method: str = "",
    blockers: List[str] | None = None,
) -> List[Dict[str, Any]]:
    if task_status == "success":
        item_status = "ready"
    elif task_status in {"failed", "rolled_back", "cancelled"}:
        item_status = "blocked"
    else:
        item_status = "pending"

    checklist = [
        _normalize_acceptance_checklist_item(
            {"label": criterion, "status": item_status},
            default_validation_method=validation_method,
            default_blockers=blockers,
        )
        for criterion in criteria
    ]
    if steps:
        completed_steps = sum(1 for step in steps if _normalize_status_value(_get_field(step, "status")) == "success")
        checklist.append(
            _normalize_acceptance_checklist_item(
                {"label": f"计划步骤完成度 {completed_steps}/{len(steps)}", "status": item_status},
                default_validation_method=validation_method,
                default_blockers=blockers,
            )
        )
    return checklist


def normalize_review_history(value: Any) -> List[Dict[str, Any]]:
    history = value if isinstance(value, list) else []
    normalized: List[Dict[str, Any]] = []
    for item in history:
        raw = _as_dict(item)
        normalized.append({
            "feature_status": _normalize_choice(raw.get("feature_status"), FEATURE_STATUS_VALUES, "pending_review"),
            "review_note": str(raw.get("review_note") or "").strip(),
            "reviewer": str(raw.get("reviewer") or "").strip(),
            "review_round": str(raw.get("review_round") or raw.get("round") or "").strip(),
            "required_followups": _clean_text_list(raw.get("required_followups") or raw.get("followups")),
            "timestamp": str(raw.get("timestamp") or "").strip() or datetime.now(timezone.utc).isoformat(),
        })
    return normalized[-20:]


def build_feature_review_entry(
    feature_status: str,
    review_note: str,
    timestamp: str | None = None,
    *,
    reviewer: str = "",
    review_round: str = "",
    required_followups: Any = None,
) -> Dict[str, Any]:
    return {
        "feature_status": _normalize_choice(feature_status, FEATURE_STATUS_VALUES, "pending_review"),
        "review_note": str(review_note or "").strip(),
        "reviewer": str(reviewer or "").strip(),
        "review_round": str(review_round or "").strip(),
        "required_followups": _clean_text_list(required_followups),
        "timestamp": str(timestamp or "").strip() or datetime.now(timezone.utc).isoformat(),
    }


def normalize_feature_lifecycle_events(value: Any) -> List[Dict[str, str]]:
    events = value if isinstance(value, list) else []
    normalized: List[Dict[str, str]] = []
    for item in events:
        raw = _as_dict(item)
        event_type = str(raw.get("event_type") or "").strip().lower()
        if not event_type:
            continue
        normalized.append({
            "event_type": event_type,
            "summary": str(raw.get("summary") or "").strip(),
            "timestamp": str(raw.get("timestamp") or "").strip() or datetime.now(timezone.utc).isoformat(),
        })
    return normalized[-50:]


def build_feature_lifecycle_event(event_type: str, summary: str = "", timestamp: str | None = None) -> Dict[str, str]:
    return {
        "event_type": str(event_type or "").strip().lower(),
        "summary": str(summary or "").strip(),
        "timestamp": str(timestamp or "").strip() or datetime.now(timezone.utc).isoformat(),
    }


def build_task_feature_context(
    *,
    prompt: str,
    task_id: str,
    task_status: Any,
    context: Dict[str, Any] | None,
    steps: List[Any] | None,
    artifacts: List[Any] | None,
    message: str,
) -> Dict[str, Any]:
    normalized_context = dict(context or {})
    status_value = _normalize_status_value(task_status)
    step_list = list(steps or [])
    artifact_list = list(artifacts or [])
    feature_id = str(normalized_context.get("feature_id") or "").strip() or f"feature-{str(task_id)[:8]}"
    owner = str(normalized_context.get("owner") or "").strip()
    priority = _normalize_choice(normalized_context.get("priority"), FEATURE_PRIORITY_VALUES, "medium")
    risk = _normalize_choice(normalized_context.get("risk"), FEATURE_RISK_VALUES, "medium")
    dependency = str(normalized_context.get("dependency") or "").strip()
    eta = str(normalized_context.get("eta") or "").strip()
    validation_method = str(normalized_context.get("validation_method") or "").strip()
    blockers = _clean_text_list(normalized_context.get("blockers"))
    required_followups = _clean_text_list(normalized_context.get("required_followups"))
    criteria = _clean_text_list(normalized_context.get("acceptance_criteria")) or _default_acceptance_criteria(prompt, step_list)
    review_note = str(normalized_context.get("feature_review_note") or "").strip()
    review_history = normalize_review_history(normalized_context.get("feature_review_history"))
    lifecycle_events = normalize_feature_lifecycle_events(normalized_context.get("feature_lifecycle_events"))
    external_links = normalize_feature_external_links(normalized_context.get("external_links"))

    contract_versions = dict(_as_dict(normalized_context.get("contract_versions")))
    contract_versions["feature_context"] = FEATURE_CONTEXT_SCHEMA_VERSION

    normalized_context["feature_id"] = feature_id
    normalized_context["owner"] = owner
    normalized_context["priority"] = priority
    normalized_context["risk"] = risk
    normalized_context["dependency"] = dependency
    normalized_context["eta"] = eta
    normalized_context["validation_method"] = validation_method
    normalized_context["blockers"] = blockers
    normalized_context["required_followups"] = required_followups
    normalized_context["acceptance_criteria"] = criteria
    normalized_context["feature_status"] = _derive_feature_status(status_value, normalized_context.get("feature_status"))
    normalized_context["feature_review_note"] = review_note
    normalized_context["feature_review_history"] = review_history
    normalized_context["feature_lifecycle_events"] = lifecycle_events
    normalized_context["external_links"] = external_links
    normalized_context["completed_step_count"] = sum(
        1 for step in step_list if _normalize_status_value(_get_field(step, "status")) == "success"
    )
    normalized_context["step_count"] = len(step_list)
    normalized_context["change_summary"] = _build_change_summary(status_value, step_list, artifact_list, message)
    normalized_context["acceptance_checklist"] = _build_acceptance_checklist(
        status_value,
        step_list,
        criteria,
        validation_method=validation_method,
        blockers=blockers,
    )
    normalized_context["artifact_links"] = _build_feature_artifact_links(artifact_list)
    normalized_context["contract_versions"] = contract_versions
    return normalized_context


def build_release_feature_snapshot(context: Dict[str, Any] | None) -> Dict[str, Any]:
    normalized_context = dict(context or {})
    return {
        "schema_version": FEATURE_CONTEXT_SCHEMA_VERSION,
        "feature_id": str(normalized_context.get("feature_id") or "").strip(),
        "owner": str(normalized_context.get("owner") or "").strip(),
        "priority": _normalize_choice(normalized_context.get("priority"), FEATURE_PRIORITY_VALUES, "medium"),
        "risk": _normalize_choice(normalized_context.get("risk"), FEATURE_RISK_VALUES, "medium"),
        "dependency": str(normalized_context.get("dependency") or "").strip(),
        "eta": str(normalized_context.get("eta") or "").strip(),
        "validation_method": str(normalized_context.get("validation_method") or "").strip(),
        "blockers": _clean_text_list(normalized_context.get("blockers")),
        "reviewer": str(normalized_context.get("reviewer") or "").strip(),
        "review_round": str(normalized_context.get("review_round") or "").strip(),
        "required_followups": _clean_text_list(normalized_context.get("required_followups")),
        "artifact_links": _normalize_release_promotion_artifacts(normalized_context.get("artifact_links")),
        "feature_review_history": normalize_review_history(normalized_context.get("feature_review_history")),
        "feature_lifecycle_events": normalize_feature_lifecycle_events(normalized_context.get("feature_lifecycle_events")),
        "external_links": normalize_feature_external_links(normalized_context.get("external_links")),
        "feature_status": _normalize_choice(normalized_context.get("feature_status"), FEATURE_STATUS_VALUES, "pending_review"),
    }


def normalize_quality_gate(gate: Dict[str, Any] | None) -> Dict[str, Any]:
    source = dict(gate or {})
    checks: List[Dict[str, Any]] = []
    for item in list(source.get("checks") or []):
        raw = _as_dict(item)
        checks.append({
            **raw,
            "name": str(raw.get("name") or "").strip() or "unnamed_check",
            "status": _normalize_choice(raw.get("status"), QUALITY_GATE_CHECK_STATUSES, "skipped"),
            "message": str(raw.get("message") or "").strip(),
        })

    blocked_checks = [check["name"] for check in checks if check["status"] == "blocked"]
    return {
        "schema_version": QUALITY_GATE_SCHEMA_VERSION,
        "passed": bool(source.get("passed")),
        "channel": str(source.get("channel") or "").strip(),
        "preset_name": str(source.get("preset_name") or "").strip(),
        "checks": checks,
        "blocked_checks": list(source.get("blocked_checks") or blocked_checks),
        "metrics": dict(_as_dict(source.get("metrics"))),
    }


def build_compact_quality_gate(gate: Dict[str, Any] | None) -> Dict[str, Any]:
    normalized = normalize_quality_gate(gate)
    return {
        "schema_version": normalized["schema_version"],
        "passed": normalized["passed"],
        "blocked_checks": list(normalized["blocked_checks"]),
        "metrics": dict(normalized["metrics"]),
    }


def _normalize_release_qa_check(
    check_id: str,
    label: str,
    status: Any,
    message: Any,
    *,
    details: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    return {
        "check_id": str(check_id or "").strip() or "unnamed_check",
        "label": str(label or "").strip() or "Unnamed Check",
        "status": _normalize_choice(status, QUALITY_GATE_CHECK_STATUSES, "skipped"),
        "message": str(message or "").strip(),
        "details": dict(details or {}),
    }


def _merge_release_qa_details(base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
    merged = dict(base)
    for key, value in dict(override or {}).items():
        if value not in (None, "", [], {}):
            merged[key] = value
    return merged


def normalize_release_qa_evidence(
    summary: Dict[str, Any] | None,
    quality_gate: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    source = dict(summary or {})
    normalized_gate = normalize_quality_gate(quality_gate or source.get("quality_gate"))
    gate_checks = {
        str(item.get("name") or "").strip(): dict(item)
        for item in list(normalized_gate.get("checks") or [])
        if str(item.get("name") or "").strip()
    }
    gate_metrics = dict(_as_dict(normalized_gate.get("metrics")))
    raw_metrics = dict(_as_dict(source.get("metrics")))

    provided_checks: Dict[str, Dict[str, Any]] = {}
    extra_checks: List[Dict[str, Any]] = []
    for item in list(source.get("checks") or []):
        raw = _as_dict(item)
        normalized = _normalize_release_qa_check(
            str(raw.get("check_id") or raw.get("name") or "").strip(),
            raw.get("label") or raw.get("check_id") or raw.get("name"),
            raw.get("status"),
            raw.get("message") or raw.get("summary"),
            details=_as_dict(raw.get("details")),
        )
        check_id = normalized["check_id"]
        if check_id in {"smoke_test", "qa_assertions", "visual_regression"}:
            provided_checks[check_id] = normalized
        else:
            extra_checks.append(normalized)

    scene_path = str(
        source.get("scene_path")
        or gate_checks.get("smoke_test", {}).get("scene_path")
        or gate_checks.get("performance_budget", {}).get("scene_path")
        or gate_checks.get("screenshot_diff", {}).get("scene_path")
        or ""
    ).strip()
    asserted_nodes = _clean_text_list(source.get("asserted_nodes"))
    assertion_node_count = int(source.get("assertion_node_count") or len(asserted_nodes))
    action_count = int(source.get("action_count") or 0)

    metrics = {
        "scene_load_ms": int(raw_metrics.get("scene_load_ms") or gate_metrics.get("scene_load_ms") or 0) or None,
        "fps": (
            round(float(raw_metrics.get("fps") or gate_metrics.get("fps") or 0.0), 2)
            if (raw_metrics.get("fps") or gate_metrics.get("fps")) not in (None, "")
            else None
        ),
        "memory_peak_mb": (
            round(float(raw_metrics.get("memory_peak_mb") or gate_metrics.get("memory_peak_mb") or 0.0), 2)
            if (raw_metrics.get("memory_peak_mb") or gate_metrics.get("memory_peak_mb")) not in (None, "")
            else None
        ),
    }
    screenshot_path = str(source.get("screenshot_path") or gate_metrics.get("screenshot_path") or "").strip()
    screenshot_diff_ratio = (
        round(float(source.get("screenshot_diff_ratio") or gate_metrics.get("screenshot_diff_ratio") or 0.0), 4)
        if (source.get("screenshot_diff_ratio") or gate_metrics.get("screenshot_diff_ratio")) not in (None, "")
        else None
    )
    max_screenshot_diff_ratio = (
        round(float(source.get("max_screenshot_diff_ratio") or gate_metrics.get("max_screenshot_diff_ratio") or 0.0), 4)
        if (source.get("max_screenshot_diff_ratio") or gate_metrics.get("max_screenshot_diff_ratio")) not in (None, "")
        else None
    )
    screenshot_diff_error = str(source.get("screenshot_diff_error") or gate_metrics.get("screenshot_diff_error") or "").strip()

    smoke_message = str(
        source.get("smoke_message")
        or provided_checks.get("smoke_test", {}).get("message")
        or gate_checks.get("smoke_test", {}).get("message")
        or ("未记录 smoke_test 结果" if not gate_checks.get("smoke_test") else "")
    ).strip()
    smoke_check = _normalize_release_qa_check(
        "smoke_test",
        "Smoke Test",
        source.get("smoke_status")
        or provided_checks.get("smoke_test", {}).get("status")
        or gate_checks.get("smoke_test", {}).get("status"),
        smoke_message,
        details=_merge_release_qa_details(
            {"scene_path": scene_path},
            {
                **gate_checks.get("smoke_test", {}),
                **provided_checks.get("smoke_test", {}).get("details", {}),
            },
        ),
    )

    raw_assertion_status = source.get("assertion_status") or provided_checks.get("qa_assertions", {}).get("status")
    default_assertion_message = (
        f"记录了 {assertion_node_count} 个断言节点"
        if assertion_node_count > 0 and raw_assertion_status == "passed"
        else ("未记录断言型 QA" if assertion_node_count <= 0 else "")
    )
    assertion_message = str(
        source.get("assertion_message")
        or provided_checks.get("qa_assertions", {}).get("message")
        or default_assertion_message
    ).strip()
    assertion_check = _normalize_release_qa_check(
        "qa_assertions",
        "Assertion QA",
        source.get("assertion_status") or provided_checks.get("qa_assertions", {}).get("status"),
        assertion_message,
        details=_merge_release_qa_details(
            {
                "scene_path": scene_path,
                "assertion_node_count": assertion_node_count,
                "asserted_nodes": asserted_nodes,
                "action_count": action_count,
            },
            provided_checks.get("qa_assertions", {}).get("details", {}),
        ),
    )

    if screenshot_diff_ratio is not None and max_screenshot_diff_ratio is not None:
        default_visual_message = f"截图 diff {screenshot_diff_ratio:.4f} / 阈值 {max_screenshot_diff_ratio:.4f}"
    elif screenshot_path:
        default_visual_message = f"已记录截图证据: {screenshot_path}"
    elif screenshot_diff_error:
        default_visual_message = screenshot_diff_error
    else:
        default_visual_message = "未记录 visual regression 结果"
    screenshot_message = str(
        source.get("screenshot_message")
        or provided_checks.get("visual_regression", {}).get("message")
        or gate_checks.get("screenshot_diff", {}).get("message")
        or default_visual_message
    ).strip()
    screenshot_check = _normalize_release_qa_check(
        "visual_regression",
        "Visual Regression",
        source.get("screenshot_status")
        or provided_checks.get("visual_regression", {}).get("status")
        or gate_checks.get("screenshot_diff", {}).get("status"),
        screenshot_message,
        details=_merge_release_qa_details(
            {
                "scene_path": scene_path,
                "screenshot_path": screenshot_path,
                "screenshot_diff_ratio": screenshot_diff_ratio,
                "max_screenshot_diff_ratio": max_screenshot_diff_ratio,
                "screenshot_diff_error": screenshot_diff_error,
            },
            provided_checks.get("visual_regression", {}).get("details", {}),
        ),
    )

    checks = [smoke_check, assertion_check, screenshot_check, *extra_checks]
    blocked_checks = [check["check_id"] for check in checks if check["status"] == "blocked"]
    warning_checks = [check["check_id"] for check in checks if check["status"] == "warning"]
    status = "blocked" if blocked_checks else ("warning" if warning_checks else ("passed" if any(check["status"] == "passed" for check in checks) else "skipped"))

    notes = _clean_text_list(source.get("notes"))
    if screenshot_diff_error and screenshot_diff_error not in notes:
        notes.append(screenshot_diff_error)

    contract_versions = dict(_as_dict(source.get("contract_versions")))
    contract_versions["release_qa_evidence"] = RELEASE_QA_EVIDENCE_SCHEMA_VERSION
    if normalized_gate.get("schema_version"):
        contract_versions["quality_gate"] = normalized_gate["schema_version"]

    return {
        "schema_version": RELEASE_QA_EVIDENCE_SCHEMA_VERSION,
        "contract_versions": contract_versions,
        "status": status,
        "passed": status != "blocked",
        "scene_path": scene_path,
        "check_count": len(checks),
        "smoke_status": smoke_check["status"],
        "smoke_message": smoke_check["message"],
        "assertion_status": assertion_check["status"],
        "assertion_message": assertion_check["message"],
        "assertion_node_count": assertion_node_count,
        "asserted_nodes": asserted_nodes,
        "action_count": action_count,
        "screenshot_status": screenshot_check["status"],
        "screenshot_message": screenshot_check["message"],
        "screenshot_path": screenshot_path,
        "screenshot_diff_ratio": screenshot_diff_ratio,
        "max_screenshot_diff_ratio": max_screenshot_diff_ratio,
        "screenshot_diff_error": screenshot_diff_error,
        "metrics": metrics,
        "checks": checks,
        "blocked_checks": blocked_checks,
        "warning_checks": warning_checks,
        "notes": notes,
    }


def normalize_balance_analysis(analysis: Dict[str, Any] | None) -> Dict[str, Any]:
    source = dict(analysis or {})
    checks: List[Dict[str, Any]] = []
    for item in list(source.get("checks") or []):
        raw = _as_dict(item)
        checks.append({
            **raw,
            "name": str(raw.get("name") or "").strip() or "unnamed_check",
            "status": _normalize_choice(raw.get("status"), QUALITY_GATE_CHECK_STATUSES, "skipped"),
            "message": str(raw.get("message") or "").strip(),
        })

    issues = _clean_text_list(source.get("issues"))
    warnings = _clean_text_list(source.get("warnings"))
    summary = _clean_text_list(source.get("summary"))

    table_types: List[str] = []
    for item in list(source.get("table_types") or []):
        normalized = str(item or "").strip().lower()
        if normalized and normalized in BALANCE_ANALYSIS_TABLE_TYPES and normalized not in table_types:
            table_types.append(normalized)

    return {
        "schema_version": BALANCE_ANALYSIS_SCHEMA_VERSION,
        "passed": bool(source.get("passed")),
        "score": round(float(source.get("score") or 0.0), 2),
        "issue_count": int(source.get("issue_count") or len(issues)),
        "warning_count": int(source.get("warning_count") or len(warnings)),
        "table_types": table_types,
        "issues": issues,
        "warnings": warnings,
        "checks": checks,
        "metrics": dict(_as_dict(source.get("metrics"))),
        "summary": summary,
    }


def normalize_balance_version_compare(compare: Dict[str, Any] | None) -> Dict[str, Any]:
    source = dict(compare or {})
    issues = _clean_text_list(source.get("issues"))
    warnings = _clean_text_list(source.get("warnings"))
    summary = _clean_text_list(source.get("summary"))

    table_types: List[str] = []
    for item in list(source.get("table_types") or []):
        normalized = str(item or "").strip().lower()
        if normalized and normalized in BALANCE_ANALYSIS_TABLE_TYPES and normalized not in table_types:
            table_types.append(normalized)

    checks: List[Dict[str, Any]] = []
    for item in list(source.get("checks") or []):
        raw = _as_dict(item)
        checks.append({
            **raw,
            "name": str(raw.get("name") or "").strip() or "unnamed_check",
            "status": _normalize_choice(raw.get("status"), QUALITY_GATE_CHECK_STATUSES, "skipped"),
            "message": str(raw.get("message") or "").strip(),
        })

    metric_deltas: Dict[str, Dict[str, Any]] = {}
    for key, value in dict(_as_dict(source.get("metric_deltas"))).items():
        raw = _as_dict(value)
        delta = raw.get("delta")
        delta_percent = raw.get("delta_percent")
        metric_deltas[str(key)] = {
            "baseline": raw.get("baseline"),
            "candidate": raw.get("candidate"),
            "delta": round(float(delta), 4) if isinstance(delta, (int, float)) else None,
            "delta_percent": round(float(delta_percent), 4) if isinstance(delta_percent, (int, float)) else None,
            "status": _normalize_choice(raw.get("status"), QUALITY_GATE_CHECK_STATUSES, "skipped"),
        }

    score_delta = float(source.get("score_delta") or 0.0)
    return {
        "schema_version": BALANCE_VERSION_COMPARE_SCHEMA_VERSION,
        "passed": bool(source.get("passed")),
        "baseline_score": round(float(source.get("baseline_score") or 0.0), 2),
        "candidate_score": round(float(source.get("candidate_score") or 0.0), 2),
        "score_delta": round(score_delta, 2),
        "baseline_issue_count": int(source.get("baseline_issue_count") or 0),
        "candidate_issue_count": int(source.get("candidate_issue_count") or 0),
        "issue_delta": int(source.get("issue_delta") or 0),
        "baseline_warning_count": int(source.get("baseline_warning_count") or 0),
        "candidate_warning_count": int(source.get("candidate_warning_count") or 0),
        "warning_delta": int(source.get("warning_delta") or 0),
        "table_types": table_types,
        "changed_metric_count": int(source.get("changed_metric_count") or len(metric_deltas)),
        "metric_deltas": metric_deltas,
        "checks": checks,
        "issues": issues,
        "warnings": warnings,
        "summary": summary,
    }


def normalize_telemetry_summary(summary: Dict[str, Any] | None) -> Dict[str, Any]:
    source = dict(summary or {})
    issues = _clean_text_list(source.get("issues"))
    warnings = _clean_text_list(source.get("warnings"))
    notes = _clean_text_list(source.get("notes"))

    catalog_entries: List[Dict[str, Any]] = []
    for item in list(source.get("catalog_entries") or []):
        raw = _as_dict(item)
        fields: List[Dict[str, Any]] = []
        for field in list(raw.get("fields") or []):
            field_raw = _as_dict(field)
            fields.append({
                "name": str(field_raw.get("name") or "").strip(),
                "type": str(field_raw.get("type") or "").strip() or "string",
                "required": bool(field_raw.get("required")),
                "pii": bool(field_raw.get("pii")),
            })
        catalog_entries.append({
            "event_name": str(raw.get("event_name") or "").strip(),
            "category": str(raw.get("category") or "").strip() or "gameplay",
            "description": str(raw.get("description") or "").strip(),
            "feature_id": str(raw.get("feature_id") or "").strip(),
            "privacy_level": _normalize_choice(raw.get("privacy_level"), TELEMETRY_PRIVACY_LEVELS, "anonymous"),
            "fields": fields,
        })

    sessions: List[Dict[str, Any]] = []
    for item in list(source.get("sessions") or []):
        raw = _as_dict(item)
        sessions.append({
            "session_id": str(raw.get("session_id") or "").strip(),
            "event_count": int(raw.get("event_count") or 0),
            "first_event_at": str(raw.get("first_event_at") or "").strip(),
            "last_event_at": str(raw.get("last_event_at") or "").strip(),
            "build_id": str(raw.get("build_id") or "").strip(),
            "channel": str(raw.get("channel") or "").strip(),
        })

    checks: List[Dict[str, Any]] = []
    for item in list(source.get("checks") or []):
        raw = _as_dict(item)
        checks.append({
            **raw,
            "name": str(raw.get("name") or "").strip() or "unnamed_check",
            "status": _normalize_choice(raw.get("status"), QUALITY_GATE_CHECK_STATUSES, "skipped"),
            "message": str(raw.get("message") or "").strip(),
        })

    retention_cohorts: List[Dict[str, Any]] = []
    for item in list(source.get("retention_cohorts") or []):
        raw = _as_dict(item)
        retention_cohorts.append({
            "window": str(raw.get("window") or "").strip().lower(),
            "day_offset": int(raw.get("day_offset") or 0),
            "eligible_users": int(raw.get("eligible_users") or 0),
            "retained_users": int(raw.get("retained_users") or 0),
            "retention_rate": round(float(raw.get("retention_rate") or 0.0), 4),
        })

    funnel_breakdown: List[Dict[str, Any]] = []
    for item in list(source.get("funnel_breakdown") or []):
        raw = _as_dict(item)
        funnel_breakdown.append({
            "step_index": int(raw.get("step_index") or 0),
            "step": str(raw.get("step") or raw.get("event_name") or "").strip(),
            "event_name": str(raw.get("event_name") or raw.get("step") or "").strip(),
            "session_count": int(raw.get("session_count") or 0),
            "conversion_rate": round(float(raw.get("conversion_rate") or 0.0), 4),
        })

    crash_taxonomy: List[Dict[str, Any]] = []
    for item in list(source.get("crash_taxonomy") or []):
        raw = _as_dict(item)
        crash_taxonomy.append({
            "crash_type": str(raw.get("crash_type") or "").strip() or "unknown",
            "count": int(raw.get("count") or 0),
            "session_count": int(raw.get("session_count") or 0),
        })

    crash_clusters: List[Dict[str, Any]] = []
    for item in list(source.get("crash_clusters") or []):
        raw = _as_dict(item)
        crash_clusters.append({
            "cluster_id": str(raw.get("cluster_id") or "").strip() or "unknown_cluster",
            "signature": str(raw.get("signature") or "").strip() or "unknown",
            "crash_type": str(raw.get("crash_type") or "").strip() or "unknown",
            "error_code": str(raw.get("error_code") or "").strip(),
            "stack_hash": str(raw.get("stack_hash") or "").strip(),
            "count": int(raw.get("count") or 0),
            "session_count": int(raw.get("session_count") or 0),
            "latest_seen_at": str(raw.get("latest_seen_at") or "").strip(),
            "sample_session_id": str(raw.get("sample_session_id") or "").strip(),
            "sample_scene_path": str(raw.get("sample_scene_path") or "").strip(),
            "builds": _clean_text_list(raw.get("builds")),
        })

    crash_regression_raw = _as_dict(source.get("crash_regression_dashboard"))
    build_regressions: List[Dict[str, Any]] = []
    for item in list(crash_regression_raw.get("build_regressions") or []):
        raw = _as_dict(item)
        build_regressions.append({
            "build_id": str(raw.get("build_id") or "").strip() or "unknown_build",
            "crash_count": int(raw.get("crash_count") or 0),
            "cluster_count": int(raw.get("cluster_count") or 0),
            "latest_seen_at": str(raw.get("latest_seen_at") or "").strip(),
            "top_cluster_id": str(raw.get("top_cluster_id") or "").strip(),
        })

    scene_regressions: List[Dict[str, Any]] = []
    for item in list(crash_regression_raw.get("scene_regressions") or []):
        raw = _as_dict(item)
        scene_regressions.append({
            "scene_path": str(raw.get("scene_path") or "").strip() or "unknown_scene",
            "crash_count": int(raw.get("crash_count") or 0),
            "cluster_count": int(raw.get("cluster_count") or 0),
            "affected_build_count": int(raw.get("affected_build_count") or 0),
            "latest_seen_at": str(raw.get("latest_seen_at") or "").strip(),
            "top_cluster_id": str(raw.get("top_cluster_id") or "").strip(),
        })

    crash_regression_dashboard = {
        "affected_build_count": int(crash_regression_raw.get("affected_build_count") or len(build_regressions)),
        "affected_scene_count": int(crash_regression_raw.get("affected_scene_count") or len(scene_regressions)),
        "top_cluster_id": str(crash_regression_raw.get("top_cluster_id") or "").strip(),
        "top_cluster_count": int(crash_regression_raw.get("top_cluster_count") or 0),
        "build_regressions": build_regressions,
        "scene_regressions": scene_regressions,
        "recommendations": _clean_text_list(crash_regression_raw.get("recommendations")),
    }

    retention_dashboard_raw = _as_dict(source.get("retention_funnel_dashboard"))
    retention_windows_input = list(retention_dashboard_raw.get("retention_windows") or [])
    if not retention_windows_input:
        retention_windows_input = [
            {
                "window": item.get("window"),
                "day_offset": item.get("day_offset"),
                "eligible_users": item.get("eligible_users"),
                "retained_users": item.get("retained_users"),
                "retention_rate": item.get("retention_rate"),
            }
            for item in retention_cohorts
        ]
    retention_windows: List[Dict[str, Any]] = []
    for item in retention_windows_input:
        raw = _as_dict(item)
        retention_windows.append({
            "window": str(raw.get("window") or "").strip().lower(),
            "day_offset": int(raw.get("day_offset") or 0),
            "eligible_users": int(raw.get("eligible_users") or 0),
            "retained_users": int(raw.get("retained_users") or 0),
            "retention_rate": round(float(raw.get("retention_rate") or 0.0), 4),
        })

    funnel_dropoffs_input = list(retention_dashboard_raw.get("funnel_dropoffs") or [])
    if not funnel_dropoffs_input and funnel_breakdown:
        previous_step = ""
        previous_event_name = ""
        previous_session_count = 0
        for item in funnel_breakdown:
            session_count = int(item.get("session_count") or 0)
            if previous_session_count == 0:
                dropoff_count = 0
                dropoff_rate = 0.0
            else:
                dropoff_count = max(previous_session_count - session_count, 0)
                dropoff_rate = round(dropoff_count / float(previous_session_count), 4) if previous_session_count else 0.0
            funnel_dropoffs_input.append({
                "step_index": item.get("step_index"),
                "step": item.get("step"),
                "event_name": item.get("event_name"),
                "previous_step": previous_step,
                "previous_event_name": previous_event_name,
                "previous_session_count": previous_session_count,
                "session_count": session_count,
                "dropoff_count": dropoff_count,
                "dropoff_rate": dropoff_rate,
            })
            previous_step = str(item.get("step") or "").strip()
            previous_event_name = str(item.get("event_name") or "").strip()
            previous_session_count = session_count

    funnel_dropoffs: List[Dict[str, Any]] = []
    for item in funnel_dropoffs_input:
        raw = _as_dict(item)
        funnel_dropoffs.append({
            "step_index": int(raw.get("step_index") or 0),
            "step": str(raw.get("step") or raw.get("event_name") or "").strip(),
            "event_name": str(raw.get("event_name") or raw.get("step") or "").strip(),
            "previous_step": str(raw.get("previous_step") or raw.get("previous_event_name") or "").strip(),
            "previous_event_name": str(raw.get("previous_event_name") or raw.get("previous_step") or "").strip(),
            "previous_session_count": int(raw.get("previous_session_count") or 0),
            "session_count": int(raw.get("session_count") or 0),
            "dropoff_count": int(raw.get("dropoff_count") or 0),
            "dropoff_rate": round(float(raw.get("dropoff_rate") or 0.0), 4),
        })

    lowest_retention_window = ""
    lowest_retention_rate = 0.0
    eligible_retention_windows = [item for item in retention_windows if int(item.get("eligible_users") or 0) > 0]
    if eligible_retention_windows:
        lowest_retention = min(
            eligible_retention_windows,
            key=lambda item: (float(item.get("retention_rate") or 0.0), int(item.get("day_offset") or 0)),
        )
        lowest_retention_window = str(lowest_retention.get("window") or "").strip().lower()
        lowest_retention_rate = round(float(lowest_retention.get("retention_rate") or 0.0), 4)

    largest_dropoff_step = ""
    largest_dropoff_count = 0
    largest_dropoff_rate = 0.0
    actionable_dropoffs = [item for item in funnel_dropoffs if int(item.get("step_index") or 0) > 1]
    if actionable_dropoffs:
        largest_dropoff = max(
            actionable_dropoffs,
            key=lambda item: (int(item.get("dropoff_count") or 0), float(item.get("dropoff_rate") or 0.0)),
        )
        largest_dropoff_step = str(largest_dropoff.get("event_name") or largest_dropoff.get("step") or "").strip()
        largest_dropoff_count = int(largest_dropoff.get("dropoff_count") or 0)
        largest_dropoff_rate = round(float(largest_dropoff.get("dropoff_rate") or 0.0), 4)

    retention_funnel_dashboard = {
        "completion_rate": round(float(retention_dashboard_raw.get("completion_rate") or source.get("funnel_completion_rate") or 0.0), 4),
        "lowest_retention_window": str(retention_dashboard_raw.get("lowest_retention_window") or lowest_retention_window).strip().lower(),
        "lowest_retention_rate": round(float(retention_dashboard_raw.get("lowest_retention_rate") or lowest_retention_rate or 0.0), 4),
        "largest_dropoff_step": str(retention_dashboard_raw.get("largest_dropoff_step") or largest_dropoff_step).strip(),
        "largest_dropoff_count": int(retention_dashboard_raw.get("largest_dropoff_count") or largest_dropoff_count or 0),
        "largest_dropoff_rate": round(float(retention_dashboard_raw.get("largest_dropoff_rate") or largest_dropoff_rate or 0.0), 4),
        "retention_windows": retention_windows,
        "funnel_dropoffs": funnel_dropoffs,
        "recommendations": _clean_text_list(retention_dashboard_raw.get("recommendations")),
    }

    trend_raw = _as_dict(source.get("retention_funnel_trend_dashboard"))
    day_rows: List[Dict[str, Any]] = []
    for item in list(trend_raw.get("day_rows") or []):
        raw = _as_dict(item)
        day_rows.append({
            "date": str(raw.get("date") or "").strip(),
            "session_count": int(raw.get("session_count") or 0),
            "event_count": int(raw.get("event_count") or 0),
            "active_user_count": int(raw.get("active_user_count") or 0),
            "new_user_count": int(raw.get("new_user_count") or 0),
            "returning_user_count": int(raw.get("returning_user_count") or 0),
            "completed_session_count": int(raw.get("completed_session_count") or 0),
            "completion_rate": round(float(raw.get("completion_rate") or 0.0), 4),
            "crash_count": int(raw.get("crash_count") or 0),
        })

    build_rows: List[Dict[str, Any]] = []
    for item in list(trend_raw.get("build_rows") or []):
        raw = _as_dict(item)
        build_rows.append({
            "build_id": str(raw.get("build_id") or "").strip() or "unknown_build",
            "session_count": int(raw.get("session_count") or 0),
            "event_count": int(raw.get("event_count") or 0),
            "completion_rate": round(float(raw.get("completion_rate") or 0.0), 4),
            "crash_count": int(raw.get("crash_count") or 0),
        })

    channel_rows: List[Dict[str, Any]] = []
    for item in list(trend_raw.get("channel_rows") or []):
        raw = _as_dict(item)
        channel_rows.append({
            "channel": str(raw.get("channel") or "").strip() or "unknown",
            "session_count": int(raw.get("session_count") or 0),
            "event_count": int(raw.get("event_count") or 0),
            "completion_rate": round(float(raw.get("completion_rate") or 0.0), 4),
            "crash_count": int(raw.get("crash_count") or 0),
        })

    retention_funnel_trend_dashboard = {
        "day_count": int(trend_raw.get("day_count") or len(day_rows)),
        "top_build_id": str(trend_raw.get("top_build_id") or "").strip(),
        "top_channel": str(trend_raw.get("top_channel") or "").strip(),
        "highest_crash_day": str(trend_raw.get("highest_crash_day") or "").strip(),
        "day_rows": day_rows,
        "build_rows": build_rows,
        "channel_rows": channel_rows,
        "recommendations": _clean_text_list(trend_raw.get("recommendations")),
    }

    liveops_impact_raw = _as_dict(source.get("liveops_impact_dashboard"))
    active_entries: List[Dict[str, Any]] = []
    for item in list(liveops_impact_raw.get("active_entries") or []):
        raw = _as_dict(item)
        active_entries.append({
            "entry_type": str(raw.get("entry_type") or "").strip() or "unknown",
            "entry_id": str(raw.get("entry_id") or "").strip() or "unnamed",
            "owner": str(raw.get("owner") or "").strip(),
            "status": str(raw.get("status") or "").strip(),
            "rollout_percentage": round(float(raw.get("rollout_percentage") or 0.0), 2),
            "matched_metrics": _clean_text_list(raw.get("matched_metrics")),
            "target_metrics": _clean_text_list(raw.get("target_metrics")),
        })

    metric_matches: List[Dict[str, Any]] = []
    for item in list(liveops_impact_raw.get("metric_matches") or []):
        raw = _as_dict(item)
        metric_matches.append({
            "target_metric": str(raw.get("target_metric") or "").strip(),
            "matched_metric": str(raw.get("matched_metric") or "").strip(),
            "source": str(raw.get("source") or "").strip(),
        })

    liveops_impact_dashboard = {
        "active_remote_config_count": int(liveops_impact_raw.get("active_remote_config_count") or 0),
        "running_experiment_count": int(liveops_impact_raw.get("running_experiment_count") or 0),
        "tracked_metric_count": int(liveops_impact_raw.get("tracked_metric_count") or 0),
        "matched_metric_count": int(liveops_impact_raw.get("matched_metric_count") or len(metric_matches)),
        "available_metric_count": int(liveops_impact_raw.get("available_metric_count") or 0),
        "tracked_metrics": _clean_text_list(liveops_impact_raw.get("tracked_metrics")),
        "available_metrics": _clean_text_list(liveops_impact_raw.get("available_metrics")),
        "unmatched_target_metrics": _clean_text_list(liveops_impact_raw.get("unmatched_target_metrics")),
        "metric_matches": metric_matches,
        "active_entries": active_entries,
        "recommendations": _clean_text_list(liveops_impact_raw.get("recommendations")),
    }

    return {
        "schema_version": TELEMETRY_SUMMARY_SCHEMA_VERSION,
        "passed": bool(source.get("passed")),
        "catalog_path": str(source.get("catalog_path") or "").strip(),
        "session_path": str(source.get("session_path") or "").strip(),
        "catalog_entry_count": int(source.get("catalog_entry_count") or len(catalog_entries)),
        "session_count": int(source.get("session_count") or len(sessions)),
        "event_count": int(source.get("event_count") or 0),
        "crash_count": int(source.get("crash_count") or 0),
        "uncataloged_event_count": int(source.get("uncataloged_event_count") or 0),
        "pii_violation_count": int(source.get("pii_violation_count") or 0),
        "privacy_gate_passed": bool(source.get("privacy_gate_passed", True)),
        "retention_user_count": int(source.get("retention_user_count") or 0),
        "funnel_completion_rate": round(float(source.get("funnel_completion_rate") or 0.0), 4),
        "issues": issues,
        "warnings": warnings,
        "notes": notes,
        "catalog_entries": catalog_entries,
        "sessions": sessions,
        "checks": checks,
        "retention_cohorts": retention_cohorts,
        "funnel_breakdown": funnel_breakdown,
        "crash_taxonomy": crash_taxonomy,
        "crash_clusters": crash_clusters,
        "crash_regression_dashboard": crash_regression_dashboard,
        "retention_funnel_dashboard": retention_funnel_dashboard,
        "retention_funnel_trend_dashboard": retention_funnel_trend_dashboard,
        "liveops_impact_dashboard": liveops_impact_dashboard,
        "metrics": dict(_as_dict(source.get("metrics"))),
    }


def normalize_platform_delivery_profile(summary: Dict[str, Any] | None) -> Dict[str, Any]:
    source = dict(summary or {})
    issues = _clean_text_list(source.get("issues"))
    warnings = _clean_text_list(source.get("warnings"))
    notes = _clean_text_list(source.get("notes"))

    platforms: List[Dict[str, Any]] = []
    for item in list(source.get("platforms") or []):
        raw = _as_dict(item)
        platforms.append({
            "platform_id": str(raw.get("platform_id") or "").strip(),
            "store": str(raw.get("store") or "").strip(),
            "preset_name": str(raw.get("preset_name") or "").strip(),
            "output_path": str(raw.get("output_path") or "").strip(),
            "arch": str(raw.get("arch") or "").strip(),
            "feature_flags": _clean_text_list(raw.get("feature_flags")),
        })

    fields: List[Dict[str, Any]] = []
    savegame_raw = _as_dict(source.get("savegame"))
    for item in list(savegame_raw.get("fields") or []):
        raw = _as_dict(item)
        fields.append({
            "name": str(raw.get("name") or "").strip(),
            "type": str(raw.get("type") or "").strip() or "string",
            "required": bool(raw.get("required")),
            "default": raw.get("default"),
        })

    savegame = {
        "schema_id": str(savegame_raw.get("schema_id") or "").strip(),
        "version": str(savegame_raw.get("version") or "").strip(),
        "save_mode": _normalize_choice(savegame_raw.get("save_mode"), PLATFORM_DELIVERY_MODES, "offline"),
        "slot_count": int(savegame_raw.get("slot_count") or 0),
        "fields": fields,
    }

    services_raw = _as_dict(source.get("services"))
    services = {
        "cloud_save": bool(services_raw.get("cloud_save")),
        "achievements": bool(services_raw.get("achievements")),
        "leaderboard": bool(services_raw.get("leaderboard")),
        "analytics": bool(services_raw.get("analytics", True)),
    }

    multiplayer_raw = _as_dict(source.get("multiplayer"))
    multiplayer = {
        "enabled": bool(multiplayer_raw.get("enabled")),
        "mode": str(multiplayer_raw.get("mode") or "").strip() or "offline",
        "transport": _normalize_choice(multiplayer_raw.get("transport"), PLATFORM_DELIVERY_TRANSPORTS, "offline"),
        "max_players": int(multiplayer_raw.get("max_players") or 1),
        "rollback_supported": bool(multiplayer_raw.get("rollback_supported")),
    }

    return {
        "schema_version": PLATFORM_DELIVERY_PROFILE_SCHEMA_VERSION,
        "manifest_path": str(source.get("manifest_path") or "").strip(),
        "platform_count": int(source.get("platform_count") or len(platforms)),
        "service_count": int(source.get("service_count") or sum(1 for value in services.values() if value)),
        "platforms": platforms,
        "savegame": savegame,
        "services": services,
        "multiplayer": multiplayer,
        "issues": issues,
        "warnings": warnings,
        "notes": notes,
    }


def normalize_outsource_delivery_gate(summary: Dict[str, Any] | None) -> Dict[str, Any]:
    source = dict(summary or {})
    notes = _clean_text_list(source.get("notes"))
    recommendations = _clean_text_list(source.get("recommendations"))
    required_license_names = _clean_text_list(source.get("required_license_names"))

    checklist: List[Dict[str, Any]] = []
    for item in list(source.get("checklist") or []):
        raw = _as_dict(item)
        checklist.append({
            "item_id": str(raw.get("item_id") or raw.get("name") or "").strip() or "unnamed_item",
            "label": str(raw.get("label") or raw.get("item_id") or "").strip() or "Unnamed Item",
            "status": _normalize_choice(raw.get("status"), QUALITY_GATE_CHECK_STATUSES, "skipped"),
            "required": bool(raw.get("required", True)),
            "message": str(raw.get("message") or raw.get("summary") or "").strip(),
            "details": dict(_as_dict(raw.get("details"))),
        })

    deliveries: List[Dict[str, Any]] = []
    for item in list(source.get("deliveries") or []):
        raw = _as_dict(item)
        issues = _clean_text_list(raw.get("issues"))
        warnings = _clean_text_list(raw.get("warnings"))
        deliveries.append({
            "asset_id": str(raw.get("asset_id") or "").strip() or "unnamed_delivery",
            "status": _normalize_choice(raw.get("status"), QUALITY_GATE_CHECK_STATUSES, "skipped"),
            "package_version": str(raw.get("package_version") or "").strip(),
            "license_name": str(raw.get("license_name") or "").strip(),
            "source_tool": str(raw.get("source_tool") or "").strip(),
            "source_path": str(raw.get("source_path") or "").strip(),
            "target_path": str(raw.get("target_path") or "").strip(),
            "target_exists": bool(raw.get("target_exists")),
            "target_size_mb": round(float(raw.get("target_size_mb") or 0.0), 4),
            "estimated_memory_mb": (
                round(float(raw.get("estimated_memory_mb") or 0.0), 4)
                if raw.get("estimated_memory_mb") not in (None, "")
                else None
            ),
            "issue_count": int(raw.get("issue_count") or len(issues)),
            "warning_count": int(raw.get("warning_count") or len(warnings)),
            "issues": issues,
            "warnings": warnings,
            "tags": _clean_text_list(raw.get("tags")),
            "notes": str(raw.get("notes") or "").strip(),
        })

    blocked_checks = [item["item_id"] for item in checklist if item["status"] == "blocked"]
    warning_checks = [item["item_id"] for item in checklist if item["status"] == "warning"]
    mode = str(source.get("mode") or "strict").strip().lower() or "strict"
    fail_on_warnings = bool(source.get("fail_on_warnings"))
    should_block = bool(blocked_checks) or (fail_on_warnings and bool(warning_checks))
    if mode == "advisory":
        should_block = False

    passed_delivery_count = sum(1 for item in deliveries if item["status"] == "passed")
    warning_delivery_count = sum(1 for item in deliveries if item["status"] == "warning")
    blocked_delivery_count = sum(1 for item in deliveries if item["status"] == "blocked")

    contract_versions = dict(_as_dict(source.get("contract_versions")))
    contract_versions["outsource_delivery_gate"] = OUTSOURCE_DELIVERY_GATE_SCHEMA_VERSION

    return {
        "schema_version": OUTSOURCE_DELIVERY_GATE_SCHEMA_VERSION,
        "contract_versions": contract_versions,
        "project_root": str(source.get("project_root") or "").strip(),
        "runtime_root": str(source.get("runtime_root") or "").strip(),
        "manifest_path": str(source.get("manifest_path") or "").strip(),
        "package_root": str(source.get("package_root") or "").strip(),
        "manifest_exists": bool(source.get("manifest_exists")),
        "package_root_exists": bool(source.get("package_root_exists")),
        "manifest_schema_version": str(source.get("manifest_schema_version") or "").strip(),
        "manifest_asset_type": str(source.get("manifest_asset_type") or "").strip(),
        "required_license_names": required_license_names,
        "mode": "advisory" if mode == "advisory" else "strict",
        "fail_on_warnings": fail_on_warnings,
        "passed": not should_block,
        "status": "blocked" if blocked_checks else ("warning" if warning_checks else "passed"),
        "should_block": should_block,
        "delivery_count": int(source.get("delivery_count") or len(deliveries)),
        "passed_delivery_count": int(source.get("passed_delivery_count") or passed_delivery_count),
        "warning_delivery_count": int(source.get("warning_delivery_count") or warning_delivery_count),
        "blocked_delivery_count": int(source.get("blocked_delivery_count") or blocked_delivery_count),
        "item_count": len(checklist),
        "warning_count": len(warning_checks),
        "blocked_count": len(blocked_checks),
        "blocking_checks": blocked_checks,
        "warning_checks": warning_checks,
        "checklist": checklist,
        "deliveries": deliveries,
        "notes": notes,
        "recommendations": recommendations,
    }


def normalize_asset_review_workflow(summary: Dict[str, Any] | None) -> Dict[str, Any]:
    source = dict(summary or {})
    notes = _clean_text_list(source.get("notes"))
    recommendations = _clean_text_list(source.get("recommendations"))
    asset_ids = _clean_text_list(source.get("asset_ids"))

    checklist: List[Dict[str, Any]] = []
    for item in list(source.get("checklist") or []):
        raw = _as_dict(item)
        checklist.append({
            "item_id": str(raw.get("item_id") or raw.get("name") or "").strip() or "unnamed_item",
            "label": str(raw.get("label") or raw.get("item_id") or "").strip() or "Unnamed Item",
            "status": _normalize_choice(raw.get("status"), QUALITY_GATE_CHECK_STATUSES, "skipped"),
            "required": bool(raw.get("required", True)),
            "message": str(raw.get("message") or raw.get("summary") or "").strip(),
            "details": dict(_as_dict(raw.get("details"))),
        })

    review_entries: List[Dict[str, Any]] = []
    for item in list(source.get("review_entries") or []):
        raw = _as_dict(item)
        review_entries.append({
            "asset_type": str(raw.get("asset_type") or "").strip() or "texture",
            "asset_id": str(raw.get("asset_id") or "").strip() or "unnamed_asset",
            "status": _normalize_choice(raw.get("status"), QUALITY_GATE_CHECK_STATUSES, "skipped"),
            "review_status": _normalize_choice(raw.get("review_status"), ASSET_REVIEW_STATUS_VALUES, "pending_review"),
            "source_manifest_path": str(raw.get("source_manifest_path") or "").strip(),
            "source_path": str(raw.get("source_path") or "").strip(),
            "target_path": str(raw.get("target_path") or "").strip(),
            "source_tool": str(raw.get("source_tool") or "").strip(),
            "package_version": str(raw.get("package_version") or "").strip(),
            "license_name": str(raw.get("license_name") or "").strip(),
            "source_dependency_paths": _clean_text_list(raw.get("source_dependency_paths")),
            "target_dependency_paths": _clean_text_list(raw.get("target_dependency_paths")),
            "reviewer": str(raw.get("reviewer") or "").strip(),
            "review_note": str(raw.get("review_note") or "").strip(),
            "reviewed_at": str(raw.get("reviewed_at") or "").strip(),
            "tags": _clean_text_list(raw.get("tags")),
            "issue_count": int(raw.get("issue_count") or len(_clean_text_list(raw.get("issues")))),
            "warning_count": int(raw.get("warning_count") or len(_clean_text_list(raw.get("warnings")))),
            "issues": _clean_text_list(raw.get("issues")),
            "warnings": _clean_text_list(raw.get("warnings")),
        })

    blocked_checks = [item["item_id"] for item in checklist if item["status"] == "blocked"]
    warning_checks = [item["item_id"] for item in checklist if item["status"] == "warning"]
    mode = str(source.get("mode") or "strict").strip().lower() or "strict"
    fail_on_warnings = bool(source.get("fail_on_warnings"))
    should_block = bool(blocked_checks) or (fail_on_warnings and bool(warning_checks))
    if mode == "advisory":
        should_block = False

    pending_review_count = sum(1 for item in review_entries if item["review_status"] == "pending_review")
    approved_count = sum(1 for item in review_entries if item["review_status"] == "approved")
    returned_count = sum(1 for item in review_entries if item["review_status"] == "returned")
    provenance_raw = _as_dict(source.get("provenance_summary"))
    provenance_summary = {
        "asset_count": int(provenance_raw.get("asset_count") or len(review_entries)),
        "issue_count": int(provenance_raw.get("issue_count") or 0),
        "issue_assets": _clean_text_list(provenance_raw.get("issue_assets")),
        "missing_source_assets": _clean_text_list(provenance_raw.get("missing_source_assets")),
        "missing_target_assets": _clean_text_list(provenance_raw.get("missing_target_assets")),
        "missing_tool_assets": _clean_text_list(provenance_raw.get("missing_tool_assets")),
        "missing_license_assets": _clean_text_list(provenance_raw.get("missing_license_assets")),
        "license_coverage_ratio": round(float(provenance_raw.get("license_coverage_ratio") or 0.0), 4),
        "source_tool_coverage_ratio": round(float(provenance_raw.get("source_tool_coverage_ratio") or 0.0), 4),
        "dependency_coverage_ratio": round(float(provenance_raw.get("dependency_coverage_ratio") or 0.0), 4),
        "source_dependency_count": int(provenance_raw.get("source_dependency_count") or 0),
        "target_dependency_count": int(provenance_raw.get("target_dependency_count") or 0),
    }

    contract_versions = dict(_as_dict(source.get("contract_versions")))
    contract_versions["asset_review_workflow"] = ASSET_REVIEW_WORKFLOW_SCHEMA_VERSION

    return {
        "schema_version": ASSET_REVIEW_WORKFLOW_SCHEMA_VERSION,
        "contract_versions": contract_versions,
        "project_root": str(source.get("project_root") or "").strip(),
        "runtime_root": str(source.get("runtime_root") or "").strip(),
        "asset_type": str(source.get("asset_type") or "").strip() or "texture",
        "asset_label": str(source.get("asset_label") or "").strip(),
        "source_manifest_path": str(source.get("source_manifest_path") or "").strip(),
        "review_manifest_path": str(source.get("review_manifest_path") or "").strip(),
        "source_manifest_exists": bool(source.get("source_manifest_exists")),
        "review_manifest_exists": bool(source.get("review_manifest_exists")),
        "source_manifest_schema_version": str(source.get("source_manifest_schema_version") or "").strip(),
        "review_manifest_schema_version": str(source.get("review_manifest_schema_version") or "").strip(),
        "mode": "advisory" if mode == "advisory" else "strict",
        "fail_on_warnings": fail_on_warnings,
        "passed": not should_block,
        "status": "blocked" if blocked_checks else ("warning" if warning_checks else "passed"),
        "should_block": should_block,
        "asset_ids": asset_ids,
        "reviewable_count": int(source.get("reviewable_count") or len(review_entries)),
        "pending_review_count": int(source.get("pending_review_count") or pending_review_count),
        "approved_count": int(source.get("approved_count") or approved_count),
        "returned_count": int(source.get("returned_count") or returned_count),
        "updated_count": int(source.get("updated_count") or 0),
        "orphan_review_count": int(source.get("orphan_review_count") or 0),
        "provenance_summary": provenance_summary,
        "provenance_issue_count": provenance_summary["issue_count"],
        "license_coverage_ratio": provenance_summary["license_coverage_ratio"],
        "item_count": len(checklist),
        "warning_count": len(warning_checks),
        "blocked_count": len(blocked_checks),
        "blocking_checks": blocked_checks,
        "warning_checks": warning_checks,
        "checklist": checklist,
        "review_entries": review_entries,
        "notes": notes,
        "recommendations": recommendations,
    }


def normalize_build_run_matrix(summary: Dict[str, Any] | None) -> Dict[str, Any]:
    source = dict(summary or {})
    notes = _clean_text_list(source.get("notes"))
    recommendations = _clean_text_list(source.get("recommendations"))
    selected_scenario_ids = _clean_text_list(source.get("selected_scenario_ids"))
    default_sequence = _clean_text_list(source.get("default_sequence"))

    scenarios: List[Dict[str, Any]] = []
    for item in list(source.get("scenarios") or []):
        raw = _as_dict(item)
        scenarios.append({
            "scenario_id": str(raw.get("scenario_id") or "").strip() or "vertical_slice_2d",
            "label": str(raw.get("label") or raw.get("scenario_id") or "").strip() or "Vertical Slice 2D",
            "change_type": str(raw.get("change_type") or "").strip() or "feature",
            "description": str(raw.get("description") or "").strip(),
            "required_evidence": _clean_text_list(raw.get("required_evidence")),
            "required_project_paths": _clean_text_list(raw.get("required_project_paths")),
            "required_runtime_paths": _clean_text_list(raw.get("required_runtime_paths")),
            "recommended_changed_paths": _clean_text_list(raw.get("recommended_changed_paths")),
            "gate_focus": _clean_text_list(raw.get("gate_focus")),
        })

    rows: List[Dict[str, Any]] = []
    for item in list(source.get("rows") or []):
        raw = _as_dict(item)
        rows.append({
            "row_id": str(raw.get("row_id") or raw.get("name") or "").strip() or "unnamed_row",
            "row_type": _normalize_choice(raw.get("row_type"), {"build", "gate", "run"}, "run"),
            "label": str(raw.get("label") or raw.get("row_id") or "").strip() or "Unnamed Row",
            "status": _normalize_choice(raw.get("status"), QUALITY_GATE_CHECK_STATUSES, "skipped"),
            "required": bool(raw.get("required", True)),
            "default_selected": bool(raw.get("default_selected")),
            "platform_id": str(raw.get("platform_id") or "").strip(),
            "platform_label": str(raw.get("platform_label") or "").strip(),
            "scenario_ids": _clean_text_list(raw.get("scenario_ids")),
            "execution_mode": str(raw.get("execution_mode") or "").strip() or "non_live",
            "command": str(raw.get("command") or "").strip(),
            "endpoint": str(raw.get("endpoint") or "").strip(),
            "script_path": str(raw.get("script_path") or "").strip(),
            "summary": str(raw.get("summary") or raw.get("message") or "").strip(),
            "details": dict(_as_dict(raw.get("details"))),
            "notes": _clean_text_list(raw.get("notes")),
            "blocking_reasons": _clean_text_list(raw.get("blocking_reasons")),
            "warning_reasons": _clean_text_list(raw.get("warning_reasons")),
        })

    blocked_rows = [row["row_id"] for row in rows if row["status"] == "blocked"]
    warning_rows = [row["row_id"] for row in rows if row["status"] == "warning"]
    required_blocked_rows = [row["row_id"] for row in rows if row["required"] and row["status"] == "blocked"]
    required_warning_rows = [row["row_id"] for row in rows if row["required"] and row["status"] == "warning"]
    mode = str(source.get("mode") or "strict").strip().lower() or "strict"
    fail_on_warnings = bool(source.get("fail_on_warnings"))
    should_block = bool(required_blocked_rows) or (fail_on_warnings and bool(required_warning_rows))
    if mode == "advisory":
        should_block = False

    contract_versions = dict(_as_dict(source.get("contract_versions")))
    contract_versions["build_run_matrix"] = BUILD_RUN_MATRIX_SCHEMA_VERSION

    platform_delivery_profile = normalize_platform_delivery_profile(source.get("platform_delivery_profile"))
    release_candidate_checklist = normalize_release_candidate_checklist(source.get("release_candidate_checklist"))

    build_count = sum(1 for row in rows if row["row_type"] == "build")
    gate_count = sum(1 for row in rows if row["row_type"] == "gate")
    run_count = sum(1 for row in rows if row["row_type"] == "run")
    default_selected_count = sum(1 for row in rows if row["default_selected"])

    return {
        "schema_version": BUILD_RUN_MATRIX_SCHEMA_VERSION,
        "contract_versions": contract_versions,
        "project_root": str(source.get("project_root") or "").strip(),
        "runtime_root": str(source.get("runtime_root") or "").strip(),
        "manifest_path": str(source.get("manifest_path") or "").strip(),
        "mode": "advisory" if mode == "advisory" else "strict",
        "fail_on_warnings": fail_on_warnings,
        "passed": not should_block,
        "status": "blocked" if blocked_rows else ("warning" if warning_rows else "passed"),
        "should_block": should_block,
        "platform_delivery_profile": platform_delivery_profile,
        "release_candidate_checklist": release_candidate_checklist,
        "selected_scenario_ids": selected_scenario_ids,
        "scenarios": scenarios,
        "row_count": int(source.get("row_count") or len(rows)),
        "build_count": int(source.get("build_count") or build_count),
        "gate_count": int(source.get("gate_count") or gate_count),
        "run_count": int(source.get("run_count") or run_count),
        "platform_count": int(source.get("platform_count") or platform_delivery_profile.get("platform_count", 0)),
        "scenario_count": int(source.get("scenario_count") or len(scenarios)),
        "default_selected_count": int(source.get("default_selected_count") or default_selected_count),
        "required_row_count": int(source.get("required_row_count") or sum(1 for row in rows if row["required"])),
        "warning_count": int(source.get("warning_count") or len(warning_rows)),
        "blocked_count": int(source.get("blocked_count") or len(blocked_rows)),
        "blocking_rows": blocked_rows,
        "warning_rows": warning_rows,
        "default_sequence": default_sequence,
        "rows": rows,
        "notes": notes,
        "recommendations": recommendations,
    }


def _normalize_release_capability_entry(summary: Dict[str, Any] | None, *, index: int) -> Dict[str, Any]:
    source = _as_dict(summary)
    surface_types = _clean_text_list(source.get("surface_types") or source.get("surfaces"))
    normalized_surface_types: List[str] = []
    for item in surface_types:
        surface_type = _normalize_choice(item, RELEASE_CAPABILITY_SURFACE_TYPES, "")
        if surface_type and surface_type not in normalized_surface_types:
            normalized_surface_types.append(surface_type)
    capability_id = str(source.get("capability_id") or source.get("id") or f"capability_{index}").strip() or f"capability_{index}"
    artifact_contracts = _clean_text_list(source.get("artifact_contracts"))
    entrypoints = _clean_text_list(source.get("entrypoints"))
    missing_fields = _clean_text_list(source.get("missing_fields"))
    recommendations = _clean_text_list(source.get("recommendations"))
    consumes_live_summary = "release_live_ci_summary" in artifact_contracts
    if consumes_live_summary and "release_artifact_manifest" not in artifact_contracts:
        missing_fields = _clean_text_list([*missing_fields, "release_artifact_manifest"])
        recommendations = _clean_text_list([
            *recommendations,
            (
                f"为 {capability_id} 同步声明 release_artifact_manifest，"
                "保持 live CI summary 和 artifact manifest 边界一致。"
            ),
        ])
    if (
        consumes_live_summary
        and capability_id.endswith("_read")
        and "gateway_method" in normalized_surface_types
        and "/release-artifact-manifest" not in entrypoints
    ):
        missing_fields = _clean_text_list([*missing_fields, "release_artifact_manifest_entrypoint"])
        recommendations = _clean_text_list([
            *recommendations,
            f"为 {capability_id} 绑定 /release-artifact-manifest 只读入口。",
        ])
    status = _normalize_choice(source.get("status"), QUALITY_GATE_CHECK_STATUSES, "warning")
    if missing_fields:
        status = _worst_gate_status([status, "warning"], default="warning")

    return {
        "capability_id": capability_id,
        "label": str(source.get("label") or source.get("name") or source.get("capability_id") or f"capability_{index}").strip() or f"capability_{index}",
        "group": str(source.get("group") or "").strip().lower().replace(" ", "_"),
        "surface_types": normalized_surface_types,
        "risk_level": _normalize_choice(source.get("risk_level"), RELEASE_CAPABILITY_RISK_LEVELS, ""),
        "requires_actor": bool(source.get("requires_actor")),
        "requires_request_auth": bool(source.get("requires_request_auth")),
        "default_enabled": bool(source.get("default_enabled", True)),
        "optional_heavy": bool(source.get("optional_heavy")),
        "sandbox_profile": _normalize_choice(source.get("sandbox_profile"), RELEASE_CAPABILITY_SANDBOX_PROFILES, ""),
        "artifact_contracts": artifact_contracts,
        "entrypoints": entrypoints,
        "policy_action": str(source.get("policy_action") or "").strip().lower(),
        "policy_decision": str(source.get("policy_decision") or "").strip().lower(),
        "policy_operation": str(source.get("policy_operation") or "").strip().lower(),
        "target_channels": _clean_text_list(source.get("target_channels")),
        "target_environments": _clean_text_list(source.get("target_environments")),
        "owners": _clean_text_list(source.get("owners")),
        "notes": _clean_text_list(source.get("notes")),
        "status": status,
        "missing_fields": missing_fields,
        "summary": str(source.get("summary") or "").strip(),
        "recommendations": recommendations,
    }


def normalize_release_capability_registry(summary: Dict[str, Any] | None) -> Dict[str, Any]:
    source = _as_dict(summary)
    items = [
        _normalize_release_capability_entry(item, index=index)
        for index, item in enumerate(list(source.get("capabilities") or []), start=1)
    ]

    surface_counts = _normalize_count_map(source.get("surface_counts"))
    risk_counts = _normalize_count_map(source.get("risk_counts"))
    group_counts = _normalize_count_map(source.get("group_counts"))
    if not surface_counts:
        for item in items:
            for surface_type in item["surface_types"]:
                surface_counts[surface_type] = surface_counts.get(surface_type, 0) + 1
    if not risk_counts:
        for item in items:
            risk_level = item["risk_level"]
            if risk_level:
                risk_counts[risk_level] = risk_counts.get(risk_level, 0) + 1
    if not group_counts:
        for item in items:
            group = item["group"]
            if group:
                group_counts[group] = group_counts.get(group, 0) + 1

    status = _normalize_choice(source.get("status"), QUALITY_GATE_CHECK_STATUSES, "")
    if not status:
        if not bool(source.get("registry_exists", source.get("exists", False))) or not items:
            status = "warning"
        else:
            status = _worst_gate_status([item["status"] for item in items], default="passed")

    contract_versions = dict(_as_dict(source.get("contract_versions")))
    contract_versions["release_capability_registry"] = RELEASE_CAPABILITY_REGISTRY_SCHEMA_VERSION

    return {
        "schema_version": RELEASE_CAPABILITY_REGISTRY_SCHEMA_VERSION,
        "contract_versions": contract_versions,
        "registry_id": str(source.get("registry_id") or "").strip(),
        "registry_path": str(source.get("registry_path") or source.get("path") or "").strip(),
        "registry_exists": bool(source.get("registry_exists", source.get("exists", False))),
        "valid": bool(source.get("valid")),
        "status": status,
        "summary": str(source.get("summary") or "").strip(),
        "capability_count": max(int(source.get("capability_count") or len(items)), 0),
        "default_enabled_count": max(int(source.get("default_enabled_count") or sum(1 for item in items if item["default_enabled"])), 0),
        "optional_heavy_count": max(int(source.get("optional_heavy_count") or sum(1 for item in items if item["optional_heavy"])), 0),
        "actor_scoped_count": max(int(source.get("actor_scoped_count") or sum(1 for item in items if item["requires_actor"])), 0),
        "request_auth_count": max(int(source.get("request_auth_count") or sum(1 for item in items if item["requires_request_auth"])), 0),
        "surface_counts": surface_counts,
        "risk_counts": risk_counts,
        "group_counts": group_counts,
        "capabilities": items,
        "recommendations": _clean_text_list(source.get("recommendations")),
    }


def normalize_release_capability_policy(summary: Dict[str, Any] | None) -> Dict[str, Any]:
    source = _as_dict(summary)
    capabilities = [
        {
            **_normalize_release_capability_entry(item, index=index),
            "route_kind": _normalize_choice(_as_dict(item).get("route_kind"), RELEASE_CAPABILITY_POLICY_ROUTE_KINDS, "portal"),
            "applicable": bool(_as_dict(item).get("applicable", True)),
            "invocation_allowed": bool(_as_dict(item).get("invocation_allowed")),
            "policy_status": _normalize_choice(_as_dict(item).get("policy_status"), QUALITY_GATE_CHECK_STATUSES, "warning"),
            "authorization_status": _normalize_choice(_as_dict(item).get("authorization_status"), QUALITY_GATE_CHECK_STATUSES, ""),
            "authorization_reason": str(_as_dict(item).get("authorization_reason") or "").strip(),
            "request_auth_posture_status": _normalize_choice(_as_dict(item).get("request_auth_posture_status"), QUALITY_GATE_CHECK_STATUSES, ""),
            "request_auth_posture_summary": str(_as_dict(item).get("request_auth_posture_summary") or "").strip(),
            "denial_reasons": _clean_text_list(_as_dict(item).get("denial_reasons")),
            "warning_reasons": _clean_text_list(_as_dict(item).get("warning_reasons")),
        }
        for index, item in enumerate(list(source.get("capabilities") or []), start=1)
    ]
    route_profile_raw = _as_dict(source.get("route_profile"))
    route_profile = {
        "allow_workspace_write": bool(route_profile_raw.get("allow_workspace_write")),
        "allow_release_write": bool(route_profile_raw.get("allow_release_write")),
        "allow_local_process": bool(route_profile_raw.get("allow_local_process")),
        "allow_optional_heavy": bool(route_profile_raw.get("allow_optional_heavy")),
        "allow_browser_automation": bool(route_profile_raw.get("allow_browser_automation")),
        "allow_godot_gui": bool(route_profile_raw.get("allow_godot_gui")),
        "allow_network_bridge": bool(route_profile_raw.get("allow_network_bridge")),
    }
    contract_versions = dict(_as_dict(source.get("contract_versions")))
    contract_versions["release_capability_policy"] = RELEASE_CAPABILITY_POLICY_SCHEMA_VERSION
    if source.get("registry_status") or source.get("registry_path") or source.get("registry_id"):
        contract_versions["release_capability_registry"] = str(contract_versions.get("release_capability_registry") or "")
    return {
        "schema_version": RELEASE_CAPABILITY_POLICY_SCHEMA_VERSION,
        "contract_versions": contract_versions,
        "status": _normalize_choice(source.get("status"), QUALITY_GATE_CHECK_STATUSES, "warning"),
        "summary": str(source.get("summary") or "").strip(),
        "route_kind": _normalize_choice(source.get("route_kind"), RELEASE_CAPABILITY_POLICY_ROUTE_KINDS, "portal"),
        "target_channel": str(source.get("target_channel") or "").strip().lower() or "staging",
        "target_environment": str(source.get("target_environment") or "").strip(),
        "actor_id": str(source.get("actor_id") or "").strip(),
        "registry_status": _normalize_choice(source.get("registry_status"), QUALITY_GATE_CHECK_STATUSES, "warning"),
        "registry_path": str(source.get("registry_path") or "").strip(),
        "registry_id": str(source.get("registry_id") or "").strip(),
        "route_profile": route_profile,
        "capability_count": max(int(source.get("capability_count") or len(capabilities)), 0),
        "allowed_count": max(int(source.get("allowed_count") or sum(1 for item in capabilities if item["policy_status"] == "passed")), 0),
        "warning_count": max(int(source.get("warning_count") or sum(1 for item in capabilities if item["policy_status"] == "warning")), 0),
        "denied_count": max(int(source.get("denied_count") or sum(1 for item in capabilities if item["policy_status"] == "blocked")), 0),
        "skipped_count": max(int(source.get("skipped_count") or sum(1 for item in capabilities if item["policy_status"] == "skipped")), 0),
        "allowed_capability_ids": _clean_text_list(source.get("allowed_capability_ids")),
        "warning_capability_ids": _clean_text_list(source.get("warning_capability_ids")),
        "denied_capability_ids": _clean_text_list(source.get("denied_capability_ids")),
        "skipped_capability_ids": _clean_text_list(source.get("skipped_capability_ids")),
        "group_counts": _normalize_count_map(source.get("group_counts")),
        "denial_reason_counts": _normalize_count_map(source.get("denial_reason_counts")),
        "capabilities": capabilities,
        "recommendations": _clean_text_list(source.get("recommendations")),
    }


def normalize_release_runtime_assembly_snapshot(summary: Dict[str, Any] | None) -> Dict[str, Any]:
    source = _as_dict(summary)
    route_profile_raw = _as_dict(source.get("route_profile"))
    auth_profile_raw = _as_dict(source.get("auth_profile"))
    identity_boundary_raw = _as_dict(source.get("identity_boundary"))
    runner_profile_raw = _as_dict(source.get("runner_profile"))

    capabilities: List[Dict[str, Any]] = []
    for item in list(source.get("capabilities") or []):
        raw = _as_dict(item)
        capabilities.append({
            "capability_id": str(raw.get("capability_id") or "").strip(),
            "label": str(raw.get("label") or "").strip(),
            "group": str(raw.get("group") or "").strip(),
            "policy_status": _normalize_choice(raw.get("policy_status"), QUALITY_GATE_CHECK_STATUSES, "skipped"),
            "sandbox_profile": _normalize_choice(raw.get("sandbox_profile"), RELEASE_CAPABILITY_SANDBOX_PROFILES, "read_only"),
            "surface_types": [
                _normalize_choice(surface_type, RELEASE_CAPABILITY_SURFACE_TYPES, "command")
                for surface_type in _clean_text_list(raw.get("surface_types"))
            ],
            "artifact_contracts": _clean_text_list(raw.get("artifact_contracts")),
            "entrypoints": _clean_text_list(raw.get("entrypoints")),
            "requires_actor": bool(raw.get("requires_actor")),
            "requires_request_auth": bool(raw.get("requires_request_auth")),
            "authorization_status": _normalize_choice(raw.get("authorization_status"), QUALITY_GATE_CHECK_STATUSES, "skipped"),
            "request_auth_posture_status": _normalize_choice(raw.get("request_auth_posture_status"), QUALITY_GATE_CHECK_STATUSES, "skipped"),
            "denial_reasons": _clean_text_list(raw.get("denial_reasons")),
            "warning_reasons": _clean_text_list(raw.get("warning_reasons")),
        })

    contract_versions = dict(_as_dict(source.get("contract_versions")))
    contract_versions["release_runtime_assembly_snapshot"] = RELEASE_RUNTIME_ASSEMBLY_SCHEMA_VERSION
    contract_versions["release_capability_policy"] = str(
        contract_versions.get("release_capability_policy")
        or RELEASE_CAPABILITY_POLICY_SCHEMA_VERSION
    )

    def capability_ids_for(status: str) -> List[str]:
        return _clean_text_list([
            item.get("capability_id")
            for item in capabilities
            if item.get("policy_status") == status
        ])

    def sandbox_profiles_for(status: str) -> List[str]:
        return _clean_text_list([
            item.get("sandbox_profile")
            for item in capabilities
            if item.get("policy_status") == status
        ])

    def surface_types_for(status: str) -> List[str]:
        values: List[str] = []
        for item in capabilities:
            if item.get("policy_status") == status:
                values.extend(list(item.get("surface_types") or []))
        return _clean_text_list(values)

    allowed_capability_ids = _clean_text_list(source.get("allowed_capability_ids")) or capability_ids_for("passed")
    warning_capability_ids = _clean_text_list(source.get("warning_capability_ids")) or capability_ids_for("warning")
    denied_capability_ids = _clean_text_list(source.get("denied_capability_ids")) or capability_ids_for("blocked")
    skipped_capability_ids = _clean_text_list(source.get("skipped_capability_ids")) or capability_ids_for("skipped")
    enabled_sandbox_profiles = _clean_text_list(source.get("enabled_sandbox_profiles")) or sandbox_profiles_for("passed")
    warning_sandbox_profiles = _clean_text_list(source.get("warning_sandbox_profiles")) or sandbox_profiles_for("warning")
    denied_sandbox_profiles = _clean_text_list(source.get("denied_sandbox_profiles")) or sandbox_profiles_for("blocked")
    enabled_surface_types = _clean_text_list(source.get("enabled_surface_types")) or surface_types_for("passed")
    denied_surface_types = _clean_text_list(source.get("denied_surface_types")) or surface_types_for("blocked")

    return {
        "schema_version": RELEASE_RUNTIME_ASSEMBLY_SCHEMA_VERSION,
        "contract_versions": contract_versions,
        "status": _normalize_choice(source.get("status"), QUALITY_GATE_CHECK_STATUSES, "warning"),
        "summary": str(source.get("summary") or "").strip(),
        "route_kind": _normalize_choice(source.get("route_kind"), RELEASE_CAPABILITY_POLICY_ROUTE_KINDS, "portal"),
        "route_id": str(source.get("route_id") or "").strip(),
        "session_id": str(source.get("session_id") or "").strip(),
        "invocation_source": str(source.get("invocation_source") or "").strip(),
        "actor_id": str(source.get("actor_id") or "").strip(),
        "target_channel": str(source.get("target_channel") or "").strip(),
        "target_environment": str(source.get("target_environment") or "").strip(),
        "registry_id": str(source.get("registry_id") or "").strip(),
        "registry_path": str(source.get("registry_path") or "").strip(),
        "registry_status": _normalize_choice(source.get("registry_status"), QUALITY_GATE_CHECK_STATUSES, "warning"),
        "policy_status": _normalize_choice(source.get("policy_status"), QUALITY_GATE_CHECK_STATUSES, "warning"),
        "route_profile": {
            "allow_workspace_write": bool(route_profile_raw.get("allow_workspace_write")),
            "allow_release_write": bool(route_profile_raw.get("allow_release_write")),
            "allow_local_process": bool(route_profile_raw.get("allow_local_process")),
            "allow_optional_heavy": bool(route_profile_raw.get("allow_optional_heavy")),
            "allow_browser_automation": bool(route_profile_raw.get("allow_browser_automation")),
            "allow_godot_gui": bool(route_profile_raw.get("allow_godot_gui")),
            "allow_network_bridge": bool(route_profile_raw.get("allow_network_bridge")),
        },
        "capability_count": max(int(source.get("capability_count") or len(capabilities)), 0),
        "allowed_count": max(int(source.get("allowed_count") or len(allowed_capability_ids)), 0),
        "warning_count": max(int(source.get("warning_count") or len(warning_capability_ids)), 0),
        "denied_count": max(int(source.get("denied_count") or len(denied_capability_ids)), 0),
        "skipped_count": max(int(source.get("skipped_count") or len(skipped_capability_ids)), 0),
        "allowed_capability_ids": allowed_capability_ids,
        "warning_capability_ids": warning_capability_ids,
        "denied_capability_ids": denied_capability_ids,
        "skipped_capability_ids": skipped_capability_ids,
        "enabled_sandbox_profiles": enabled_sandbox_profiles,
        "warning_sandbox_profiles": warning_sandbox_profiles,
        "denied_sandbox_profiles": denied_sandbox_profiles,
        "enabled_surface_types": enabled_surface_types,
        "denied_surface_types": denied_surface_types,
        "auth_profile": {
            "actor_present": bool(auth_profile_raw.get("actor_present")),
            "requires_actor_count": max(int(auth_profile_raw.get("requires_actor_count") or 0), 0),
            "request_auth_required_count": max(int(auth_profile_raw.get("request_auth_required_count") or 0), 0),
            "actor_required_capability_ids": _clean_text_list(auth_profile_raw.get("actor_required_capability_ids")),
            "request_auth_required_capability_ids": _clean_text_list(auth_profile_raw.get("request_auth_required_capability_ids")),
            "authorization_blocked_capability_ids": _clean_text_list(auth_profile_raw.get("authorization_blocked_capability_ids")),
            "authorization_warning_capability_ids": _clean_text_list(auth_profile_raw.get("authorization_warning_capability_ids")),
            "request_auth_blocked_capability_ids": _clean_text_list(auth_profile_raw.get("request_auth_blocked_capability_ids")),
            "request_auth_warning_capability_ids": _clean_text_list(auth_profile_raw.get("request_auth_warning_capability_ids")),
        },
        "identity_boundary": {
            "status": _normalize_choice(identity_boundary_raw.get("status"), QUALITY_GATE_CHECK_STATUSES, "skipped"),
            "path": str(identity_boundary_raw.get("path") or "").strip(),
            "profile_id": str(identity_boundary_raw.get("profile_id") or "").strip(),
            "provider_mode": str(identity_boundary_raw.get("provider_mode") or "").strip(),
            "provider_id": str(identity_boundary_raw.get("provider_id") or "").strip(),
            "session_required": bool(identity_boundary_raw.get("session_required")),
            "session_backend": str(identity_boundary_raw.get("session_backend") or "").strip(),
            "max_session_age_hours": max(int(identity_boundary_raw.get("max_session_age_hours") or 0), 0),
            "secret_rotation_required": bool(identity_boundary_raw.get("secret_rotation_required")),
            "secret_backend": str(identity_boundary_raw.get("secret_backend") or "").strip(),
            "rotation_owner": str(identity_boundary_raw.get("rotation_owner") or "").strip(),
            "rotation_window_days": max(int(identity_boundary_raw.get("rotation_window_days") or 0), 0),
            "external_handoff_required": bool(identity_boundary_raw.get("external_handoff_required")),
            "external_handoff_mode": str(identity_boundary_raw.get("external_handoff_mode") or "").strip(),
            "external_handoff_target_id": str(identity_boundary_raw.get("external_handoff_target_id") or "").strip(),
            "external_handoff_owner": str(identity_boundary_raw.get("external_handoff_owner") or "").strip(),
        },
        "runner_profile": {
            "status": _normalize_choice(runner_profile_raw.get("status"), QUALITY_GATE_CHECK_STATUSES, "skipped"),
            "report_path": str(runner_profile_raw.get("report_path") or "").strip(),
            "path": str(runner_profile_raw.get("path") or "").strip(),
            "profile_id": str(runner_profile_raw.get("profile_id") or "").strip(),
            "runner_name": str(runner_profile_raw.get("runner_name") or "").strip(),
            "runner_os": str(runner_profile_raw.get("runner_os") or "").strip(),
            "runner_arch": str(runner_profile_raw.get("runner_arch") or "").strip(),
            "runner_labels": _clean_text_list(runner_profile_raw.get("runner_labels")),
            "github_workflow": str(runner_profile_raw.get("github_workflow") or "").strip(),
            "github_job": str(runner_profile_raw.get("github_job") or "").strip(),
            "github_run_id": str(runner_profile_raw.get("github_run_id") or "").strip(),
            "github_run_attempt": str(runner_profile_raw.get("github_run_attempt") or "").strip(),
        },
        "capabilities": capabilities,
        "recommendations": _clean_text_list(source.get("recommendations")),
    }


def normalize_release_live_event_stream(summary: Dict[str, Any] | None) -> Dict[str, Any]:
    source = _as_dict(summary)

    events: List[Dict[str, Any]] = []
    for index, item in enumerate(list(source.get("events") or []), start=1):
        raw = _as_dict(item)
        events.append({
            "event_id": str(raw.get("event_id") or f"event_{index}").strip() or f"event_{index}",
            "event_type": str(raw.get("event_type") or "").strip(),
            "scope": str(raw.get("scope") or "").strip(),
            "order": max(int(raw.get("order") or index), 1),
            "status": _normalize_choice(raw.get("status"), QUALITY_GATE_CHECK_STATUSES, "warning"),
            "occurred_at": str(raw.get("occurred_at") or "").strip(),
            "step_id": str(raw.get("step_id") or "").strip(),
            "lane_id": str(raw.get("lane_id") or "").strip(),
            "summary": str(raw.get("summary") or "").strip(),
            "message": str(raw.get("message") or "").strip(),
            "details": _as_dict(raw.get("details")),
        })

    contract_versions = dict(_as_dict(source.get("contract_versions")))
    contract_versions["release_live_event_stream"] = RELEASE_LIVE_EVENT_STREAM_SCHEMA_VERSION

    return {
        "schema_version": RELEASE_LIVE_EVENT_STREAM_SCHEMA_VERSION,
        "contract_versions": contract_versions,
        "status": _normalize_choice(source.get("status"), QUALITY_GATE_CHECK_STATUSES, "warning"),
        "summary": str(source.get("summary") or "").strip(),
        "path": str(source.get("path") or "").strip(),
        "source": str(source.get("source") or "").strip(),
        "generated_at": str(source.get("generated_at") or "").strip(),
        "target_channel": str(source.get("target_channel") or "").strip(),
        "target_environment": str(source.get("target_environment") or "").strip(),
        "release_build_id": str(source.get("release_build_id") or "").strip(),
        "release_version": str(source.get("release_version") or "").strip(),
        "release_channel": str(source.get("release_channel") or "").strip(),
        "route_kind": _normalize_choice(source.get("route_kind"), RELEASE_CAPABILITY_POLICY_ROUTE_KINDS, "portal"),
        "route_id": str(source.get("route_id") or "").strip(),
        "invocation_source": str(source.get("invocation_source") or "").strip(),
        "event_count": max(int(source.get("event_count") or len(events)), 0),
        "blocked_event_count": max(int(source.get("blocked_event_count") or 0), 0),
        "warning_event_count": max(int(source.get("warning_event_count") or 0), 0),
        "latest_event_type": str(source.get("latest_event_type") or "").strip(),
        "latest_event_status": _normalize_choice(source.get("latest_event_status"), QUALITY_GATE_CHECK_STATUSES, "skipped"),
        "events": events,
    }


def normalize_release_live_dispatch_preflight(summary: Dict[str, Any] | None) -> Dict[str, Any]:
    source = _as_dict(summary)
    dispatch_inputs_raw = _as_dict(source.get("dispatch_inputs"))
    blocking_checks = _clean_text_list(source.get("blocking_checks"))
    warning_checks = _clean_text_list(source.get("warning_checks"))
    contract_versions = dict(_as_dict(source.get("contract_versions")))
    contract_versions["release_live_dispatch_preflight"] = RELEASE_LIVE_DISPATCH_PREFLIGHT_SCHEMA_VERSION
    ready = bool(source.get("ready")) and not blocking_checks
    default_status = "blocked" if blocking_checks else ("warning" if warning_checks else "passed")

    return {
        "schema_version": RELEASE_LIVE_DISPATCH_PREFLIGHT_SCHEMA_VERSION,
        "contract_versions": contract_versions,
        "status": _normalize_choice(source.get("status"), QUALITY_GATE_CHECK_STATUSES, default_status),
        "summary": str(source.get("summary") or "").strip(),
        "ready": ready,
        "project_root": str(source.get("project_root") or "").strip(),
        "workflow": str(source.get("workflow") or "").strip(),
        "workflow_path": str(source.get("workflow_path") or "").strip(),
        "workflow_exists": bool(source.get("workflow_exists")),
        "workflow_dispatch_enabled": bool(source.get("workflow_dispatch_enabled")),
        "repo": str(source.get("repo") or "").strip(),
        "repo_source": str(source.get("repo_source") or "").strip(),
        "origin_remote_url": str(source.get("origin_remote_url") or "").strip(),
        "ref": str(source.get("ref") or "").strip(),
        "ref_source": str(source.get("ref_source") or "").strip(),
        "token_env_names": _clean_text_list(source.get("token_env_names")),
        "token_present": bool(source.get("token_present")),
        "token_source": str(source.get("token_source") or "").strip(),
        "gh_cli_installed": bool(source.get("gh_cli_installed")),
        "gh_cli_path": str(source.get("gh_cli_path") or "").strip(),
        "runner_labels": _clean_text_list(source.get("runner_labels")),
        "dispatch_inputs": {
            "runner_labels": str(dispatch_inputs_raw.get("runner_labels") or "").strip(),
            "target_channel": str(dispatch_inputs_raw.get("target_channel") or "").strip(),
            "target_environment": str(dispatch_inputs_raw.get("target_environment") or "").strip(),
            "release_manifest_path": str(dispatch_inputs_raw.get("release_manifest_path") or "").strip(),
            "runner_profile_path": str(dispatch_inputs_raw.get("runner_profile_path") or "").strip(),
            "approvers": str(dispatch_inputs_raw.get("approvers") or "").strip(),
            "providers": str(dispatch_inputs_raw.get("providers") or "").strip(),
            "artifact_dir": str(dispatch_inputs_raw.get("artifact_dir") or "").strip(),
            "fail_on_warnings": str(dispatch_inputs_raw.get("fail_on_warnings") or "").strip(),
        },
        "blocking_checks": blocking_checks,
        "warning_checks": warning_checks,
        "recommendations": _clean_text_list(source.get("recommendations")),
    }


def _normalize_release_live_dispatch_result(summary: Dict[str, Any] | None) -> Dict[str, Any]:
    source = _as_dict(summary)
    if not source:
        return {
            "schema_version": RELEASE_LIVE_DISPATCH_RESULT_SCHEMA_VERSION,
            "status": "skipped",
            "ok": False,
            "summary": "",
            "repo": "",
            "workflow": "",
            "ref": "",
            "dispatched_at": "",
            "token_source": "",
            "inputs": {},
            "wait": False,
            "run": {
                "id": None,
                "number": None,
                "status": "",
                "conclusion": "",
                "html_url": "",
                "created_at": "",
                "updated_at": "",
                "head_branch": "",
            },
            "error": "",
            "error_type": "",
        }
    run_raw = _as_dict(source.get("run"))
    inputs = {
        str(key).strip(): str(value).strip()
        for key, value in _as_dict(source.get("inputs")).items()
        if str(key).strip()
    }
    status = _normalize_choice(source.get("status"), QUALITY_GATE_CHECK_STATUSES, "")
    if not status:
        if bool(source.get("ok")):
            status = "passed"
        elif str(source.get("summary") or source.get("error") or "").strip():
            status = "blocked"
        else:
            status = "warning"
    return {
        "schema_version": str(source.get("schema_version") or RELEASE_LIVE_DISPATCH_RESULT_SCHEMA_VERSION).strip()
        or RELEASE_LIVE_DISPATCH_RESULT_SCHEMA_VERSION,
        "status": status,
        "ok": bool(source.get("ok")),
        "summary": str(source.get("summary") or "").strip(),
        "repo": str(source.get("repo") or "").strip(),
        "workflow": str(source.get("workflow") or "").strip(),
        "ref": str(source.get("ref") or "").strip(),
        "dispatched_at": str(source.get("dispatched_at") or "").strip(),
        "token_source": str(source.get("token_source") or "").strip(),
        "inputs": inputs,
        "wait": bool(source.get("wait")),
        "run": {
            "id": run_raw.get("id"),
            "number": run_raw.get("number"),
            "status": str(run_raw.get("status") or "").strip(),
            "conclusion": str(run_raw.get("conclusion") or "").strip(),
            "html_url": str(run_raw.get("html_url") or "").strip(),
            "created_at": str(run_raw.get("created_at") or "").strip(),
            "updated_at": str(run_raw.get("updated_at") or "").strip(),
            "head_branch": str(run_raw.get("head_branch") or "").strip(),
        },
        "error": str(source.get("error") or "").strip(),
        "error_type": str(source.get("error_type") or "").strip(),
    }


def normalize_release_live_dispatch_audit(summary: Dict[str, Any] | None) -> Dict[str, Any]:
    source = _as_dict(summary)
    if not source:
        return {
            "schema_version": RELEASE_LIVE_DISPATCH_AUDIT_SCHEMA_VERSION,
            "contract_versions": {
                "release_live_dispatch_audit": RELEASE_LIVE_DISPATCH_AUDIT_SCHEMA_VERSION,
                "release_live_dispatch_preflight": RELEASE_LIVE_DISPATCH_PREFLIGHT_SCHEMA_VERSION,
                "release_live_dispatch_result": RELEASE_LIVE_DISPATCH_RESULT_SCHEMA_VERSION,
            },
            "status": "skipped",
            "summary": "",
            "path": "",
            "artifact_dir": "",
            "project_root": "",
            "recorded_at": "",
            "triggered_by": "",
            "workflow": "",
            "repo": "",
            "ref": "",
            "target_channel": "",
            "target_environment": "",
            "ready": False,
            "ok": False,
            "wait": False,
            "dispatch_attempted": False,
            "dispatch_completed": False,
            "follow_up_required": False,
            "token_source": "",
            "inputs": {},
            "run": _normalize_release_live_dispatch_result({}).get("run"),
            "error": "",
            "error_type": "",
            "blocking_checks": [],
            "warning_checks": [],
            "recommendations": [],
            "request_auth": _normalize_release_request_auth({}),
            "preflight": normalize_release_live_dispatch_preflight({}),
            "dispatch_result": _normalize_release_live_dispatch_result({}),
        }
    preflight = normalize_release_live_dispatch_preflight(source.get("preflight"))
    dispatch_result = _normalize_release_live_dispatch_result(source.get("dispatch_result") or source.get("result"))
    request_auth = _normalize_release_request_auth(source.get("request_auth"))
    run = dict(dispatch_result.get("run") or {})
    if not any(run.values()):
        run = dict(_normalize_release_live_dispatch_result({"run": source.get("run")}).get("run") or {})
    blocking_checks = _clean_text_list(source.get("blocking_checks")) or list(preflight.get("blocking_checks") or [])
    warning_checks = _clean_text_list(source.get("warning_checks")) or list(preflight.get("warning_checks") or [])
    ready = bool(source.get("ready")) if "ready" in source else bool(preflight.get("ready"))
    dispatch_attempted = bool(source.get("dispatch_attempted")) or bool(
        dispatch_result.get("summary") or dispatch_result.get("dispatched_at") or run.get("id")
    )
    dispatch_completed = bool(source.get("dispatch_completed")) or str(run.get("status") or "").strip().lower() == "completed"
    status = _normalize_choice(source.get("status"), QUALITY_GATE_CHECK_STATUSES, "")
    if not status:
        request_auth_status = str(request_auth.get("status") or "").strip().lower()
        if request_auth_status == "blocked" or blocking_checks or str(dispatch_result.get("status") or "").strip().lower() == "blocked":
            status = "blocked"
        elif request_auth_status == "warning" or warning_checks or str(preflight.get("status") or "").strip().lower() == "warning":
            status = "warning"
        elif bool(dispatch_result.get("ok")):
            status = "passed"
        else:
            status = "warning"
    follow_up_required = bool(source.get("follow_up_required"))
    if not follow_up_required:
        follow_up_required = bool(blocking_checks) or (dispatch_attempted and bool(dispatch_result.get("wait")) and not dispatch_completed)

    contract_versions = dict(_as_dict(source.get("contract_versions")))
    contract_versions["release_live_dispatch_audit"] = RELEASE_LIVE_DISPATCH_AUDIT_SCHEMA_VERSION
    contract_versions["release_live_dispatch_preflight"] = str(
        contract_versions.get("release_live_dispatch_preflight")
        or preflight.get("schema_version")
        or RELEASE_LIVE_DISPATCH_PREFLIGHT_SCHEMA_VERSION
    )
    contract_versions["release_live_dispatch_result"] = str(
        contract_versions.get("release_live_dispatch_result")
        or dispatch_result.get("schema_version")
        or RELEASE_LIVE_DISPATCH_RESULT_SCHEMA_VERSION
    )

    return {
        "schema_version": RELEASE_LIVE_DISPATCH_AUDIT_SCHEMA_VERSION,
        "contract_versions": contract_versions,
        "status": status,
        "summary": str(source.get("summary") or dispatch_result.get("summary") or preflight.get("summary") or "").strip(),
        "path": str(source.get("path") or "").strip(),
        "artifact_dir": str(source.get("artifact_dir") or "").strip(),
        "project_root": str(source.get("project_root") or "").strip(),
        "recorded_at": str(source.get("recorded_at") or "").strip(),
        "triggered_by": str(source.get("triggered_by") or request_auth.get("actor_id") or "").strip(),
        "workflow": str(source.get("workflow") or dispatch_result.get("workflow") or preflight.get("workflow") or "").strip(),
        "repo": str(source.get("repo") or dispatch_result.get("repo") or preflight.get("repo") or "").strip(),
        "ref": str(source.get("ref") or dispatch_result.get("ref") or preflight.get("ref") or "").strip(),
        "target_channel": str(
            source.get("target_channel")
            or dispatch_result.get("inputs", {}).get("target_channel")
            or preflight.get("dispatch_inputs", {}).get("target_channel")
            or ""
        ).strip(),
        "target_environment": str(
            source.get("target_environment")
            or dispatch_result.get("inputs", {}).get("target_environment")
            or preflight.get("dispatch_inputs", {}).get("target_environment")
            or ""
        ).strip(),
        "ready": ready,
        "ok": bool(source.get("ok")) if "ok" in source else bool(dispatch_result.get("ok")) and status == "passed",
        "wait": bool(source.get("wait")) if "wait" in source else bool(dispatch_result.get("wait")),
        "dispatch_attempted": dispatch_attempted,
        "dispatch_completed": dispatch_completed,
        "follow_up_required": follow_up_required,
        "token_source": str(source.get("token_source") or dispatch_result.get("token_source") or preflight.get("token_source") or "").strip(),
        "inputs": dict(dispatch_result.get("inputs") or preflight.get("dispatch_inputs") or {}),
        "run": run,
        "error": str(source.get("error") or dispatch_result.get("error") or "").strip(),
        "error_type": str(source.get("error_type") or dispatch_result.get("error_type") or "").strip(),
        "blocking_checks": blocking_checks,
        "warning_checks": warning_checks,
        "recommendations": _clean_text_list(source.get("recommendations")) or list(preflight.get("recommendations") or []),
        "request_auth": request_auth,
        "preflight": preflight,
        "dispatch_result": dispatch_result,
    }


def _normalize_release_delivery_readiness_component(summary: Dict[str, Any] | None) -> Dict[str, Any]:
    source = _as_dict(summary)
    paths_raw = _as_dict(source.get("paths"))
    details_raw = _as_dict(source.get("details"))
    return {
        "component_id": str(source.get("component_id") or "").strip(),
        "label": str(source.get("label") or "").strip(),
        "status": _normalize_choice(source.get("status"), QUALITY_GATE_CHECK_STATUSES, "warning"),
        "required": bool(source.get("required", True)),
        "ready": bool(source.get("ready")),
        "follow_up_required": bool(source.get("follow_up_required")),
        "summary": str(source.get("summary") or "").strip(),
        "blocking_checks": _clean_text_list(source.get("blocking_checks")),
        "warning_checks": _clean_text_list(source.get("warning_checks")),
        "paths": {
            str(key).strip(): str(value).strip()
            for key, value in paths_raw.items()
            if str(key).strip() and str(value).strip()
        },
        "details": {
            str(key).strip(): value
            for key, value in details_raw.items()
            if str(key).strip()
        },
        "notes": _clean_text_list(source.get("notes")),
        "recommendations": _clean_text_list(source.get("recommendations")),
    }


def _normalize_release_delivery_readiness_action(summary: Dict[str, Any] | None) -> Dict[str, Any]:
    source = _as_dict(summary)
    return {
        "action_id": str(source.get("action_id") or "").strip(),
        "label": str(source.get("label") or "").strip(),
        "status": _normalize_choice(source.get("status"), QUALITY_GATE_CHECK_STATUSES, "warning"),
        "owner_hint": str(source.get("owner_hint") or "").strip(),
        "dependency": str(source.get("dependency") or "").strip(),
        "eta": str(source.get("eta") or "").strip(),
        "validation_method": str(source.get("validation_method") or "").strip(),
        "blockers": _clean_text_list(source.get("blockers")),
        "summary": str(source.get("summary") or "").strip(),
        "entrypoint": str(source.get("entrypoint") or "").strip(),
        "blocking_reason": str(source.get("blocking_reason") or "").strip(),
    }


def normalize_release_delivery_readiness(summary: Dict[str, Any] | None) -> Dict[str, Any]:
    source = _as_dict(summary)
    components = [
        _normalize_release_delivery_readiness_component(item)
        for item in list(source.get("components") or [])
        if isinstance(item, dict)
    ]
    if not components:
        for key in ("identity_boundary", "workflow_release", "distribution_delivery"):
            raw_component = _as_dict(source.get(key))
            if not raw_component:
                continue
            raw_component.setdefault("component_id", key)
            components.append(_normalize_release_delivery_readiness_component(raw_component))
    component_lookup = {
        str(item.get("component_id") or "").strip(): item
        for item in components
        if str(item.get("component_id") or "").strip()
    }
    next_actions = [
        _normalize_release_delivery_readiness_action(item)
        for item in list(source.get("next_actions") or [])
        if isinstance(item, dict)
    ]
    blocking_checks = _clean_text_list(source.get("blocking_checks")) or [
        item
        for component in components
        for item in list(component.get("blocking_checks") or [])
    ]
    warning_checks = _clean_text_list(source.get("warning_checks")) or [
        item
        for component in components
        for item in list(component.get("warning_checks") or [])
    ]
    passed_count = max(
        int(source.get("passed_count") or sum(1 for item in components if item.get("status") == "passed")),
        0,
    )
    warning_count = max(
        int(source.get("warning_count") or sum(1 for item in components if item.get("status") == "warning")),
        0,
    )
    blocked_count = max(
        int(source.get("blocked_count") or sum(1 for item in components if item.get("status") == "blocked")),
        0,
    )
    contract_versions = dict(_as_dict(source.get("contract_versions")))
    contract_versions["release_delivery_readiness"] = RELEASE_DELIVERY_READINESS_SCHEMA_VERSION

    return {
        "schema_version": RELEASE_DELIVERY_READINESS_SCHEMA_VERSION,
        "contract_versions": contract_versions,
        "project_root": str(source.get("project_root") or "").strip(),
        "runtime_root": str(source.get("runtime_root") or "").strip(),
        "target_channel": str(source.get("target_channel") or "").strip() or "release",
        "target_environment": str(source.get("target_environment") or "").strip(),
        "artifact_dir": str(source.get("artifact_dir") or "").strip(),
        "workflow": str(source.get("workflow") or "").strip(),
        "repo": str(source.get("repo") or "").strip(),
        "ref": str(source.get("ref") or "").strip(),
        "status": _normalize_choice(
            source.get("status"),
            QUALITY_GATE_CHECK_STATUSES,
            "blocked" if blocked_count else ("warning" if warning_count else ("passed" if components else "warning")),
        ),
        "summary": str(source.get("summary") or "").strip(),
        "component_count": max(int(source.get("component_count") or len(components)), 0),
        "passed_count": passed_count,
        "warning_count": warning_count,
        "blocked_count": blocked_count,
        "blocking_checks": blocking_checks,
        "warning_checks": warning_checks,
        "identity_boundary": component_lookup.get("identity_boundary", _normalize_release_delivery_readiness_component({})),
        "workflow_release": component_lookup.get("workflow_release", _normalize_release_delivery_readiness_component({})),
        "distribution_delivery": component_lookup.get("distribution_delivery", _normalize_release_delivery_readiness_component({})),
        "components": components,
        "next_actions": next_actions,
        "notes": _clean_text_list(source.get("notes")),
        "recommendations": _clean_text_list(source.get("recommendations")),
    }


def normalize_scene_ownership_board(summary: Dict[str, Any] | None) -> Dict[str, Any]:
    source = dict(summary or {})
    notes = _clean_text_list(source.get("notes"))
    recommendations = _clean_text_list(source.get("recommendations"))
    selected_scene_paths = _clean_text_list(source.get("selected_scene_paths"))

    checklist: List[Dict[str, Any]] = []
    for item in list(source.get("checklist") or []):
        raw = _as_dict(item)
        checklist.append({
            "item_id": str(raw.get("item_id") or raw.get("name") or "").strip() or "unnamed_item",
            "label": str(raw.get("label") or raw.get("item_id") or "").strip() or "Unnamed Item",
            "status": _normalize_choice(raw.get("status"), QUALITY_GATE_CHECK_STATUSES, "skipped"),
            "required": bool(raw.get("required", True)),
            "message": str(raw.get("message") or raw.get("summary") or "").strip(),
            "details": dict(_as_dict(raw.get("details"))),
        })

    scene_entries: List[Dict[str, Any]] = []
    for item in list(source.get("scene_entries") or []):
        raw = _as_dict(item)
        scene_entries.append({
            "scene_path": str(raw.get("scene_path") or "").strip() or "res://scenes/unnamed_scene.tscn",
            "scene_name": str(raw.get("scene_name") or "").strip() or "unnamed_scene",
            "scene_category": _normalize_choice(raw.get("scene_category"), {"level", "ui", "module", "scene"}, "scene"),
            "status": _normalize_choice(raw.get("status"), QUALITY_GATE_CHECK_STATUSES, "skipped"),
            "owner": str(raw.get("owner") or "").strip(),
            "feature_id": str(raw.get("feature_id") or "").strip(),
            "lock_state": _normalize_choice(raw.get("lock_state"), {"available", "hinted", "locked", "shared"}, "available"),
            "source_manifest_path": str(raw.get("source_manifest_path") or "").strip(),
            "source_manifest_exists": bool(raw.get("source_manifest_exists")),
            "exists": bool(raw.get("exists", True)),
            "derived_from_level_manifest": bool(raw.get("derived_from_level_manifest")),
            "note": str(raw.get("note") or "").strip(),
            "updated_at": str(raw.get("updated_at") or "").strip(),
        })

    blocked_checks = [item["item_id"] for item in checklist if item["status"] == "blocked"]
    warning_checks = [item["item_id"] for item in checklist if item["status"] == "warning"]
    mode = str(source.get("mode") or "strict").strip().lower() or "strict"
    fail_on_warnings = bool(source.get("fail_on_warnings"))
    should_block = bool(blocked_checks) or (fail_on_warnings and bool(warning_checks))
    if mode == "advisory":
        should_block = False

    contract_versions = dict(_as_dict(source.get("contract_versions")))
    contract_versions["scene_ownership_board"] = SCENE_OWNERSHIP_BOARD_SCHEMA_VERSION

    scene_count = len(scene_entries)
    assigned_count = sum(1 for item in scene_entries if item["owner"])
    locked_count = sum(1 for item in scene_entries if item["lock_state"] == "locked")
    shared_count = sum(1 for item in scene_entries if item["lock_state"] == "shared")
    hinted_count = sum(1 for item in scene_entries if item["lock_state"] == "hinted")
    available_count = sum(1 for item in scene_entries if item["lock_state"] == "available")
    missing_owner_count = sum(1 for item in scene_entries if not item["owner"])
    missing_feature_count = sum(1 for item in scene_entries if item["owner"] and not item["feature_id"])

    return {
        "schema_version": SCENE_OWNERSHIP_BOARD_SCHEMA_VERSION,
        "contract_versions": contract_versions,
        "project_root": str(source.get("project_root") or "").strip(),
        "runtime_root": str(source.get("runtime_root") or "").strip(),
        "board_path": str(source.get("board_path") or "").strip(),
        "board_exists": bool(source.get("board_exists")),
        "scene_category": str(source.get("scene_category") or "").strip(),
        "selected_scene_paths": selected_scene_paths,
        "mode": "advisory" if mode == "advisory" else "strict",
        "fail_on_warnings": fail_on_warnings,
        "passed": not should_block,
        "status": "blocked" if blocked_checks else ("warning" if warning_checks else "passed"),
        "should_block": should_block,
        "scene_count": int(source.get("scene_count") or scene_count),
        "assigned_count": int(source.get("assigned_count") or assigned_count),
        "locked_count": int(source.get("locked_count") or locked_count),
        "shared_count": int(source.get("shared_count") or shared_count),
        "hinted_count": int(source.get("hinted_count") or hinted_count),
        "available_count": int(source.get("available_count") or available_count),
        "updated_count": int(source.get("updated_count") or 0),
        "orphan_count": int(source.get("orphan_count") or 0),
        "missing_owner_count": int(source.get("missing_owner_count") or missing_owner_count),
        "missing_feature_count": int(source.get("missing_feature_count") or missing_feature_count),
        "warning_count": len(warning_checks),
        "blocked_count": len(blocked_checks),
        "blocking_checks": blocked_checks,
        "warning_checks": warning_checks,
        "checklist": checklist,
        "scene_entries": scene_entries,
        "notes": notes,
        "recommendations": recommendations,
    }


def _normalize_release_promotion_artifacts(value: Any) -> List[Dict[str, Any]]:
    artifacts: List[Dict[str, Any]] = []
    for index, item in enumerate(list(value or []), start=1):
        raw = _as_dict(item)
        artifacts.append({
            "artifact_id": str(raw.get("artifact_id") or raw.get("item_id") or f"artifact_{index}").strip() or f"artifact_{index}",
            "label": str(raw.get("label") or raw.get("artifact_id") or "").strip() or f"Artifact {index}",
            "status": _normalize_choice(raw.get("status"), QUALITY_GATE_CHECK_STATUSES, "skipped"),
            "required": bool(raw.get("required", True)),
            "path": str(raw.get("path") or "").strip(),
            "kind": str(raw.get("kind") or "artifact").strip() or "artifact",
            "summary": str(raw.get("summary") or raw.get("message") or "").strip(),
            "details": dict(_as_dict(raw.get("details"))),
        })
    return artifacts


def _normalize_release_promotion_checks(value: Any) -> List[Dict[str, Any]]:
    checks: List[Dict[str, Any]] = []
    for index, item in enumerate(list(value or []), start=1):
        raw = _as_dict(item)
        checks.append({
            "check_id": str(raw.get("check_id") or raw.get("item_id") or f"check_{index}").strip() or f"check_{index}",
            "label": str(raw.get("label") or raw.get("check_id") or "").strip() or f"Check {index}",
            "status": _normalize_choice(raw.get("status"), QUALITY_GATE_CHECK_STATUSES, "skipped"),
            "required": bool(raw.get("required", True)),
            "message": str(raw.get("message") or raw.get("summary") or "").strip(),
            "details": dict(_as_dict(raw.get("details"))),
        })
    return checks


def _normalize_review_bundle_audiences(value: Any) -> List[Dict[str, Any]]:
    audiences: List[Dict[str, Any]] = []
    for index, item in enumerate(list(value or []), start=1):
        raw = _as_dict(item)
        audiences.append({
            "audience_id": str(raw.get("audience_id") or f"audience_{index}").strip() or f"audience_{index}",
            "label": str(raw.get("label") or raw.get("audience_id") or "").strip() or f"Audience {index}",
            "summary_lines": _clean_text_list(raw.get("summary_lines") or raw.get("lines") or raw.get("summary")),
        })
    return audiences


def _build_change_scope_summary(changed_paths: List[str]) -> Dict[str, Any]:
    scene_exts = {".tscn", ".scn"}
    resource_exts = {".tres", ".res", ".import", ".png", ".jpg", ".jpeg", ".webp", ".svg", ".aseprite", ".glb", ".gltf", ".wav", ".ogg", ".mp3"}
    code_exts = {".gd", ".cs", ".py", ".js", ".ts", ".tsx", ".html", ".css", ".json", ".yml", ".yaml", ".ps1", ".sh"}
    docs_exts = {".md", ".rst", ".txt"}

    def select(*, prefixes: tuple[str, ...] = (), suffixes: set[str] | None = None) -> List[str]:
        selected: List[str] = []
        for path in changed_paths:
            normalized = path.replace("\\", "/").lower()
            suffix = Path(normalized).suffix
            if (prefixes and normalized.startswith(prefixes)) or (suffixes and suffix in suffixes):
                selected.append(path)
        return selected

    scene_paths = select(prefixes=("scenes/", "agent_modules/scenes/"), suffixes=scene_exts)
    resource_paths = [path for path in select(prefixes=("assets/", "materials/", "textures/", "sounds/"), suffixes=resource_exts) if path not in scene_paths]
    code_paths = [path for path in select(prefixes=("agent_system/", "api_server/", "scripts/", "tools/", "tests/"), suffixes=code_exts) if path not in scene_paths and path not in resource_paths]
    docs_paths = [path for path in select(prefixes=("docs/",), suffixes=docs_exts) if path not in code_paths]
    other_paths = [path for path in changed_paths if path not in scene_paths and path not in resource_paths and path not in code_paths and path not in docs_paths]
    return {
        "file_count": len(changed_paths),
        "scene_count": len(scene_paths),
        "resource_count": len(resource_paths),
        "code_count": len(code_paths),
        "docs_count": len(docs_paths),
        "other_count": len(other_paths),
        "scene_paths": scene_paths,
        "resource_paths": resource_paths,
        "code_paths": code_paths,
        "docs_paths": docs_paths,
        "other_paths": other_paths,
    }


def _review_record_status(status: Any) -> str:
    normalized = str(status or "").strip().lower()
    if normalized == "ready":
        return "passed"
    if normalized == "pending":
        return "warning"
    return _normalize_choice(normalized, QUALITY_GATE_CHECK_STATUSES, "skipped")


def _build_validation_records(
    explicit_records: Any,
    acceptance_checklist: List[Dict[str, Any]],
    artifact_links: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    records: List[Dict[str, Any]] = []

    for index, item in enumerate(list(explicit_records or []), start=1):
        raw = _as_dict(item)
        records.append({
            "record_id": str(raw.get("record_id") or raw.get("id") or f"validation_{index}").strip() or f"validation_{index}",
            "label": str(raw.get("label") or raw.get("record_id") or "").strip() or f"Validation {index}",
            "status": _review_record_status(raw.get("status")),
            "source": str(raw.get("source") or "manual").strip() or "manual",
            "validation_method": str(raw.get("validation_method") or raw.get("method") or "").strip(),
            "path": str(raw.get("path") or "").strip(),
            "summary": str(raw.get("summary") or raw.get("message") or "").strip(),
            "details": dict(_as_dict(raw.get("details"))),
        })

    for index, item in enumerate(acceptance_checklist, start=1):
        records.append({
            "record_id": f"acceptance_{index}",
            "label": str(item.get("label") or f"Acceptance {index}").strip(),
            "status": _review_record_status(item.get("status")),
            "source": "acceptance_checklist",
            "validation_method": str(item.get("validation_method") or "").strip(),
            "path": "",
            "summary": ", ".join(list(item.get("blockers") or [])),
            "details": {"blockers": list(item.get("blockers") or [])},
        })

    for item in artifact_links:
        record_id = str(item.get("artifact_id") or "").strip()
        if not record_id:
            continue
        records.append({
            "record_id": f"artifact_{record_id}",
            "label": str(item.get("label") or record_id).strip(),
            "status": _review_record_status(item.get("status")),
            "source": "artifact_links",
            "validation_method": str(item.get("kind") or "").strip(),
            "path": str(item.get("path") or "").strip(),
            "summary": str(item.get("summary") or "").strip(),
            "details": dict(_as_dict(item.get("details"))),
        })

    deduped: Dict[str, Dict[str, Any]] = {}
    for item in records:
        deduped[item["record_id"]] = item
    return list(deduped.values())[-80:]


def _build_review_risk_summary(
    feature: Dict[str, Any],
    known_issues: List[str],
    blocking_items: List[str],
    warning_items: List[str],
) -> Dict[str, Any]:
    feature_blockers = _clean_text_list(feature.get("blockers"))
    return {
        "risk_level": str(feature.get("risk") or "medium").strip() or "medium",
        "feature_status": str(feature.get("feature_status") or "pending_review").strip() or "pending_review",
        "known_issue_count": len(known_issues),
        "feature_blocker_count": len(feature_blockers),
        "blocking_count": len(blocking_items),
        "warning_count": len(warning_items),
        "known_issues": known_issues,
        "feature_blockers": feature_blockers,
        "blocking_items": blocking_items,
        "warning_items": warning_items,
        "should_block": bool(blocking_items),
    }


def _build_signoff_records(
    required_signoffs: List[str],
    provided_signoffs: List[str],
    missing_signoffs: List[str],
) -> List[Dict[str, Any]]:
    records: List[Dict[str, Any]] = []
    seen = set()
    missing = set(missing_signoffs)
    provided = set(provided_signoffs)

    for actor in required_signoffs:
        if actor in seen:
            continue
        seen.add(actor)
        records.append({
            "actor": actor,
            "status": "missing" if actor in missing or actor not in provided else "approved",
            "required": True,
            "source": "missing_signoffs" if actor in missing or actor not in provided else "provided_signoffs",
        })

    for actor in provided_signoffs:
        if actor in seen:
            continue
        seen.add(actor)
        records.append({
            "actor": actor,
            "status": "approved",
            "required": False,
            "source": "provided_signoffs",
        })
    return records


def _review_followup_owner(item_id: str) -> str:
    if "signoff" in item_id:
        return "producer"
    if item_id.startswith("release_request_auth"):
        return "release_engineering"
    if item_id.startswith("release_distribution"):
        return "release_ops"
    if item_id in {"qa_evidence", "acceptance_checklist", "full_live_validation"}:
        return "qa_lead"
    if item_id in {"feature_status", "feature_blockers"}:
        return "feature_owner"
    return "release_engineering"


def _build_review_followup_actions(
    blocking_items: List[str],
    warning_items: List[str],
    signoff_records: List[Dict[str, Any]],
    validation_records: List[Dict[str, Any]],
    risk_summary: Dict[str, Any],
) -> List[Dict[str, Any]]:
    actions: Dict[str, Dict[str, Any]] = {}

    def add(action_id: str, source: str, status: str, blockers: List[str] | None = None) -> None:
        action_id = str(action_id or "").strip()
        if not action_id:
            return
        actions[action_id] = {
            "action_id": action_id,
            "label": action_id.replace("_", " "),
            "status": _normalize_choice(status, QUALITY_GATE_CHECK_STATUSES, "warning"),
            "source": source,
            "owner_hint": _review_followup_owner(action_id),
            "dependency": source,
            "eta": "before_release_gate",
            "validation_method": f"resolve_{action_id}",
            "blockers": _clean_text_list(blockers) or [action_id],
        }

    for item in blocking_items:
        add(item, "blocking_items", "blocked")
    for item in warning_items:
        add(item, "warning_items", "warning")
    for item in signoff_records:
        if item.get("status") == "missing":
            add(f"signoff_{item.get('actor')}", "signoff_records", "warning", [str(item.get("actor") or "")])
    for item in validation_records:
        if item.get("status") in {"blocked", "warning"}:
            add(f"validation_{item.get('record_id')}", "validation_records", str(item.get("status") or "warning"), [str(item.get("label") or item.get("record_id") or "")])
    if risk_summary.get("feature_blockers"):
        add("feature_blockers", "risk_summary", "blocked" if risk_summary.get("should_block") else "warning", list(risk_summary.get("feature_blockers") or []))
    return list(actions.values())[:80]


def _normalize_review_followup_actions(value: Any) -> List[Dict[str, Any]]:
    actions: List[Dict[str, Any]] = []
    for index, item in enumerate(list(value or []), start=1):
        raw = _as_dict(item)
        action_id = str(raw.get("action_id") or raw.get("id") or f"review_followup_{index}").strip() or f"review_followup_{index}"
        actions.append({
            "action_id": action_id,
            "label": str(raw.get("label") or action_id.replace("_", " ")).strip(),
            "status": _normalize_choice(raw.get("status"), QUALITY_GATE_CHECK_STATUSES, "warning"),
            "source": str(raw.get("source") or "review_bundle").strip() or "review_bundle",
            "owner_hint": str(raw.get("owner_hint") or "").strip(),
            "dependency": str(raw.get("dependency") or "").strip(),
            "eta": str(raw.get("eta") or "").strip(),
            "validation_method": str(raw.get("validation_method") or "").strip(),
            "blockers": _clean_text_list(raw.get("blockers")),
        })
    return actions[-80:]


def normalize_release_review_bundle(summary: Dict[str, Any] | None) -> Dict[str, Any]:
    source = dict(summary or {})
    if not source:
        return {
            "schema_version": RELEASE_REVIEW_BUNDLE_SCHEMA_VERSION,
            "contract_versions": {"release_review_bundle": RELEASE_REVIEW_BUNDLE_SCHEMA_VERSION},
            "project_root": "",
            "runtime_root": "",
            "target_channel": "",
            "target_environment": "",
            "promotion_target_label": "",
            "build_id": "",
            "version": "",
            "release_channel": "",
            "generated_at": "",
            "release_manifest_path": "",
            "feature": build_release_feature_snapshot({}),
            "change_summary": [],
            "changed_paths": [],
            "change_scope_summary": _build_change_scope_summary([]),
            "change_scope_count": 0,
            "acceptance_checklist": [],
            "acceptance_total_count": 0,
            "acceptance_ready_count": 0,
            "acceptance_pending_count": 0,
            "acceptance_blocked_count": 0,
            "known_issues": [],
            "artifact_links": [],
            "artifact_count": 0,
            "validation_records": [],
            "validation_record_count": 0,
            "risk_summary": _build_review_risk_summary(build_release_feature_snapshot({}), [], [], []),
            "audience_summaries": [],
            "audience_count": 0,
            "required_signoffs": [],
            "provided_signoffs": [],
            "missing_signoffs": [],
            "signoff_records": [],
            "signoff_record_count": 0,
            "review_followup_actions": [],
            "review_followup_action_count": 0,
            "status": "skipped",
            "should_block": False,
            "blocking_items": [],
            "warning_items": [],
            "notes": [],
            "recommendations": [],
        }

    contract_versions = dict(_as_dict(source.get("contract_versions")))
    contract_versions["release_review_bundle"] = RELEASE_REVIEW_BUNDLE_SCHEMA_VERSION

    feature = build_release_feature_snapshot(source.get("feature"))
    change_summary = _clean_text_list(source.get("change_summary"))
    changed_paths = _clean_text_list(source.get("changed_paths"))
    change_scope_summary = _build_change_scope_summary(changed_paths)
    known_issues = _clean_text_list(source.get("known_issues") or source.get("known_risks"))

    acceptance_checklist: List[Dict[str, Any]] = []
    for item in list(source.get("acceptance_checklist") or []):
        acceptance_checklist.append(_normalize_acceptance_checklist_item(item))

    ready_count = sum(1 for item in acceptance_checklist if item["status"] == "ready")
    pending_count = sum(1 for item in acceptance_checklist if item["status"] == "pending")
    blocked_count = sum(1 for item in acceptance_checklist if item["status"] == "blocked")

    artifact_links = _normalize_release_promotion_artifacts(source.get("artifact_links") or feature.get("artifact_links") or source.get("artifacts"))
    validation_records = _build_validation_records(source.get("validation_records"), acceptance_checklist, artifact_links)
    audience_summaries = _normalize_review_bundle_audiences(source.get("audience_summaries"))
    required_signoffs = _clean_text_list(source.get("required_signoffs"))
    provided_signoffs = _clean_text_list(source.get("provided_signoffs"))
    missing_signoffs = _clean_text_list(source.get("missing_signoffs")) or [
        item for item in required_signoffs if item not in provided_signoffs
    ]
    signoff_records = _build_signoff_records(required_signoffs, provided_signoffs, missing_signoffs)

    blocking_items = _clean_text_list(source.get("blocking_items"))
    if not blocking_items:
        feature_blockers = _clean_text_list(feature.get("blockers"))
        if feature.get("feature_status") == "returned":
            blocking_items.append("feature_status")
        if feature_blockers:
            blocking_items.append("feature_blockers")
        if not change_summary:
            blocking_items.append("change_summary")
        if not acceptance_checklist or blocked_count:
            blocking_items.append("acceptance_checklist")
        blocking_items.extend(
            item["artifact_id"]
            for item in artifact_links
            if item["required"] and item["status"] == "blocked" and item["artifact_id"] not in blocking_items
        )

    warning_items = _clean_text_list(source.get("warning_items"))
    if not warning_items:
        if pending_count and "acceptance_checklist" not in blocking_items:
            warning_items.append("acceptance_checklist")
        if not changed_paths:
            warning_items.append("changed_paths")
        if missing_signoffs:
            warning_items.append("signoffs")
        warning_items.extend(
            item["artifact_id"]
            for item in artifact_links
            if item["status"] == "warning" and item["artifact_id"] not in warning_items
        )
    risk_summary = _build_review_risk_summary(feature, known_issues, blocking_items, warning_items)
    review_followup_actions = _build_review_followup_actions(
        blocking_items,
        warning_items,
        signoff_records,
        validation_records,
        risk_summary,
    )

    return {
        "schema_version": RELEASE_REVIEW_BUNDLE_SCHEMA_VERSION,
        "contract_versions": contract_versions,
        "project_root": str(source.get("project_root") or "").strip(),
        "runtime_root": str(source.get("runtime_root") or "").strip(),
        "target_channel": str(source.get("target_channel") or "").strip(),
        "target_environment": str(source.get("target_environment") or "").strip(),
        "promotion_target_label": str(source.get("promotion_target_label") or "").strip(),
        "build_id": str(source.get("build_id") or "").strip(),
        "version": str(source.get("version") or "").strip(),
        "release_channel": str(source.get("release_channel") or "").strip(),
        "generated_at": str(source.get("generated_at") or "").strip(),
        "release_manifest_path": str(source.get("release_manifest_path") or "").strip(),
        "feature": feature,
        "change_summary": change_summary,
        "changed_paths": changed_paths,
        "change_scope_summary": change_scope_summary,
        "change_scope_count": int(source.get("change_scope_count") or len(changed_paths)),
        "acceptance_checklist": acceptance_checklist,
        "acceptance_total_count": int(source.get("acceptance_total_count") or len(acceptance_checklist)),
        "acceptance_ready_count": int(source.get("acceptance_ready_count") or ready_count),
        "acceptance_pending_count": int(source.get("acceptance_pending_count") or pending_count),
        "acceptance_blocked_count": int(source.get("acceptance_blocked_count") or blocked_count),
        "known_issues": known_issues,
        "artifact_links": artifact_links,
        "artifact_count": int(source.get("artifact_count") or len(artifact_links)),
        "validation_records": validation_records,
        "validation_record_count": int(source.get("validation_record_count") or len(validation_records)),
        "risk_summary": risk_summary,
        "audience_summaries": audience_summaries,
        "audience_count": int(source.get("audience_count") or len(audience_summaries)),
        "required_signoffs": required_signoffs,
        "provided_signoffs": provided_signoffs,
        "missing_signoffs": missing_signoffs,
        "signoff_records": signoff_records,
        "signoff_record_count": int(source.get("signoff_record_count") or len(signoff_records)),
        "review_followup_actions": review_followup_actions,
        "review_followup_action_count": int(source.get("review_followup_action_count") or len(review_followup_actions)),
        "status": "blocked" if blocking_items else ("warning" if warning_items else "passed"),
        "should_block": bool(source.get("should_block")) or bool(blocking_items),
        "blocking_items": blocking_items,
        "warning_items": warning_items,
        "notes": _clean_text_list(source.get("notes")),
        "recommendations": _clean_text_list(source.get("recommendations")),
    }


def normalize_release_promotion_plan(summary: Dict[str, Any] | None) -> Dict[str, Any]:
    source = dict(summary or {})
    notes = _clean_text_list(source.get("notes"))
    recommendations = _clean_text_list(source.get("recommendations"))
    promotion_steps = _clean_text_list(source.get("promotion_steps"))
    selected_scenario_ids = _clean_text_list(source.get("selected_scenario_ids"))
    selected_provider_ids = _clean_text_list(source.get("selected_provider_ids"))
    required_signoffs = _clean_text_list(source.get("required_signoffs"))
    provided_signoffs = _clean_text_list(source.get("provided_signoffs") or source.get("approvers"))
    missing_signoffs = _clean_text_list(source.get("missing_signoffs"))

    checklist: List[Dict[str, Any]] = []
    for item in list(source.get("checklist") or []):
        raw = _as_dict(item)
        checklist.append({
            "item_id": str(raw.get("item_id") or raw.get("name") or "").strip() or "unnamed_item",
            "label": str(raw.get("label") or raw.get("item_id") or "").strip() or "Unnamed Item",
            "status": _normalize_choice(raw.get("status"), QUALITY_GATE_CHECK_STATUSES, "skipped"),
            "required": bool(raw.get("required", True)),
            "message": str(raw.get("message") or raw.get("summary") or "").strip(),
            "details": dict(_as_dict(raw.get("details"))),
        })

    blocked_checks = [item["item_id"] for item in checklist if item["status"] == "blocked"]
    warning_checks = [item["item_id"] for item in checklist if item["status"] == "warning"]
    mode = str(source.get("mode") or "strict").strip().lower() or "strict"
    fail_on_warnings = bool(source.get("fail_on_warnings"))
    should_block = bool(blocked_checks) or (fail_on_warnings and bool(warning_checks))
    if mode == "advisory":
        should_block = False

    contract_versions = dict(_as_dict(source.get("contract_versions")))
    contract_versions["release_promotion_plan"] = RELEASE_PROMOTION_PLAN_SCHEMA_VERSION

    release_candidate_checklist = normalize_release_candidate_checklist(source.get("release_candidate_checklist"))
    build_run_matrix = normalize_build_run_matrix(source.get("build_run_matrix"))
    scene_ownership_board = normalize_scene_ownership_board(source.get("scene_ownership_board"))
    release_live_runner_baseline = _normalize_release_live_runner_baseline_summary(
        source.get("release_live_runner_baseline"),
        target_channel=str(source.get("target_channel") or "").strip() or "staging",
    )
    release_live_ci_summary = _normalize_release_live_ci_summary(source.get("release_live_ci_summary"))
    runtime_assembly_snapshot = normalize_release_runtime_assembly_snapshot(
        source.get("runtime_assembly_snapshot")
        or release_live_ci_summary.get("details", {}).get("runtime_assembly")
    )
    request_auth_posture = _normalize_release_request_auth_posture(source.get("request_auth_posture"))
    request_auth_rotation_audit = _normalize_release_request_auth_rotation_audit(source.get("request_auth_rotation_audit"))
    request_auth_identity_audit = _normalize_release_request_auth_identity_audit(source.get("request_auth_identity_audit"))
    release_distribution_bundle = _normalize_release_distribution_bundle(source.get("release_distribution_bundle"))
    release_delivery_readiness = normalize_release_delivery_readiness(source.get("release_delivery_readiness"))

    compat_raw = _as_dict(source.get("agent_compatibility_summary"))
    agent_compatibility_summary = {
        "schema_version": str(compat_raw.get("schema_version") or AGENT_PROVIDER_COMPAT_SCHEMA_VERSION).strip() or AGENT_PROVIDER_COMPAT_SCHEMA_VERSION,
        "passed": bool(compat_raw.get("passed")),
        "status": _normalize_choice(compat_raw.get("status"), QUALITY_GATE_CHECK_STATUSES, "skipped"),
        "provider_count": int(compat_raw.get("provider_count") or 0),
        "surface_count": int(compat_raw.get("surface_count") or 0),
        "blocked_providers": _clean_text_list(compat_raw.get("blocked_providers")),
        "warning_providers": _clean_text_list(compat_raw.get("warning_providers")),
        "blocked_surfaces": _clean_text_list(compat_raw.get("blocked_surfaces")),
    }

    evidence_raw = _as_dict(source.get("evidence_bundle"))
    evidence_artifacts = _normalize_release_promotion_artifacts(evidence_raw.get("artifacts"))
    evidence_missing = _clean_text_list(evidence_raw.get("missing_artifacts")) or [item["artifact_id"] for item in evidence_artifacts if item["status"] == "blocked"]
    evidence_warning = _clean_text_list(evidence_raw.get("warning_artifacts")) or [item["artifact_id"] for item in evidence_artifacts if item["status"] == "warning"]
    evidence_bundle = {
        "status": _normalize_choice(
            evidence_raw.get("status"),
            QUALITY_GATE_CHECK_STATUSES,
            "blocked" if evidence_missing else ("warning" if evidence_warning else ("passed" if evidence_artifacts else "skipped")),
        ),
        "should_block": bool(evidence_raw.get("should_block")) or bool(evidence_missing),
        "artifact_count": int(evidence_raw.get("artifact_count") or len(evidence_artifacts)),
        "artifacts": evidence_artifacts,
        "missing_artifacts": evidence_missing,
        "warning_artifacts": evidence_warning,
        "release_metadata": dict(_as_dict(evidence_raw.get("release_metadata"))),
        "notes": _clean_text_list(evidence_raw.get("notes")),
    }

    deployment_raw = _as_dict(source.get("deployment_rehearsal"))
    deployment_checks = _normalize_release_promotion_checks(deployment_raw.get("preflight_checks"))
    deployment_blocking = _clean_text_list(deployment_raw.get("blocking_checks")) or [item["check_id"] for item in deployment_checks if item["status"] == "blocked"]
    deployment_warning = _clean_text_list(deployment_raw.get("warning_checks")) or [item["check_id"] for item in deployment_checks if item["status"] == "warning"]
    deployment_rehearsal = {
        "status": _normalize_choice(
            deployment_raw.get("status"),
            QUALITY_GATE_CHECK_STATUSES,
            "blocked" if deployment_blocking else ("warning" if deployment_warning else ("passed" if deployment_checks else "skipped")),
        ),
        "should_block": bool(deployment_raw.get("should_block")) or bool(deployment_blocking),
        "target_channel": str(deployment_raw.get("target_channel") or source.get("target_channel") or "").strip(),
        "target_environment": str(deployment_raw.get("target_environment") or source.get("target_environment") or "").strip(),
        "lane_sequence": _clean_text_list(deployment_raw.get("lane_sequence")),
        "preflight_checks": deployment_checks,
        "blocking_checks": deployment_blocking,
        "warning_checks": deployment_warning,
        "verification_targets": dict(_as_dict(deployment_raw.get("verification_targets"))),
        "verification_steps": _clean_text_list(deployment_raw.get("verification_steps")),
        "cutover_steps": _clean_text_list(deployment_raw.get("cutover_steps")),
        "notes": _clean_text_list(deployment_raw.get("notes")),
    }

    rollback_raw = _as_dict(source.get("rollback_rehearsal"))
    rollback_assets = _normalize_release_promotion_artifacts(rollback_raw.get("assets"))
    rollback_checks = _normalize_release_promotion_checks(rollback_raw.get("verification_checks"))
    rollback_blocking = _clean_text_list(rollback_raw.get("blocking_checks")) or [item["check_id"] for item in rollback_checks if item["status"] == "blocked"]
    rollback_warning = _clean_text_list(rollback_raw.get("warning_checks")) or [item["check_id"] for item in rollback_checks if item["status"] == "warning"]
    rollback_rehearsal = {
        "status": _normalize_choice(
            rollback_raw.get("status"),
            QUALITY_GATE_CHECK_STATUSES,
            "blocked" if rollback_blocking else ("warning" if rollback_warning else ("passed" if rollback_assets or rollback_checks else "skipped")),
        ),
        "should_block": bool(rollback_raw.get("should_block")) or bool(rollback_blocking),
        "target_channel": str(rollback_raw.get("target_channel") or source.get("target_channel") or "").strip(),
        "target_environment": str(rollback_raw.get("target_environment") or source.get("target_environment") or "").strip(),
        "rollback_hint": str(rollback_raw.get("rollback_hint") or "").strip(),
        "restore_target": str(rollback_raw.get("restore_target") or "").strip(),
        "asset_count": int(rollback_raw.get("asset_count") or len(rollback_assets)),
        "assets": rollback_assets,
        "verification_checks": rollback_checks,
        "blocking_checks": rollback_blocking,
        "warning_checks": rollback_warning,
        "rehearsal_steps": _clean_text_list(rollback_raw.get("rehearsal_steps")),
        "notes": _clean_text_list(rollback_raw.get("notes")),
    }
    has_review_bundle = "review_bundle" in source and source.get("review_bundle") is not None
    review_bundle = normalize_release_review_bundle(source.get("review_bundle"))

    if not missing_signoffs and required_signoffs:
        missing_signoffs = [item for item in required_signoffs if item not in provided_signoffs]
    if has_review_bundle:
        contract_versions["release_review_bundle"] = review_bundle["schema_version"]

    return {
        "schema_version": RELEASE_PROMOTION_PLAN_SCHEMA_VERSION,
        "contract_versions": contract_versions,
        "project_root": str(source.get("project_root") or "").strip(),
        "runtime_root": str(source.get("runtime_root") or "").strip(),
        "target_channel": str(source.get("target_channel") or "").strip() or "staging",
        "target_environment": str(source.get("target_environment") or "").strip() or "staging",
        "promotion_target_label": str(source.get("promotion_target_label") or "").strip(),
        "release_manifest_path": str(source.get("release_manifest_path") or "").strip(),
        "mode": "advisory" if mode == "advisory" else "strict",
        "fail_on_warnings": fail_on_warnings,
        "passed": not should_block,
        "status": "blocked" if blocked_checks else ("warning" if warning_checks else "passed"),
        "should_block": should_block,
        "selected_scenario_ids": selected_scenario_ids,
        "selected_provider_ids": selected_provider_ids,
        "required_signoffs": required_signoffs,
        "provided_signoffs": provided_signoffs,
        "missing_signoffs": missing_signoffs,
        "item_count": len(checklist),
        "warning_count": len(warning_checks),
        "blocked_count": len(blocked_checks),
        "blocking_checks": blocked_checks,
        "warning_checks": warning_checks,
        "release_candidate_checklist": release_candidate_checklist,
        "build_run_matrix": build_run_matrix,
        "scene_ownership_board": scene_ownership_board,
        "agent_compatibility_summary": agent_compatibility_summary,
        "release_live_runner_baseline": release_live_runner_baseline,
        "release_live_ci_summary": release_live_ci_summary,
        "runtime_assembly_snapshot": runtime_assembly_snapshot,
        "request_auth_posture": request_auth_posture,
        "request_auth_rotation_audit": request_auth_rotation_audit,
        "request_auth_identity_audit": request_auth_identity_audit,
        "release_distribution_bundle": release_distribution_bundle,
        "release_delivery_readiness": release_delivery_readiness,
        "checklist": checklist,
        "evidence_bundle": evidence_bundle,
        "deployment_rehearsal": deployment_rehearsal,
        "rollback_rehearsal": rollback_rehearsal,
        "review_bundle": review_bundle,
        "promotion_steps": promotion_steps,
        "notes": notes,
        "recommendations": recommendations,
    }


def _normalize_release_authorization(summary: Dict[str, Any] | None, *, default_status: str = "skipped") -> Dict[str, Any]:
    source = _as_dict(summary)
    return {
        "status": _normalize_choice(source.get("status"), QUALITY_GATE_CHECK_STATUSES, default_status),
        "required": bool(source.get("required")),
        "policy_path": str(source.get("policy_path") or "").strip(),
        "policy_source": str(source.get("policy_source") or "").strip(),
        "actor_id": str(source.get("actor_id") or "").strip(),
        "actor_roles": _clean_text_list(source.get("actor_roles")),
        "action": str(source.get("action") or "").strip(),
        "target_channel": str(source.get("target_channel") or "").strip(),
        "target_environment": str(source.get("target_environment") or "").strip(),
        "decision": str(source.get("decision") or "").strip(),
        "operation": str(source.get("operation") or "").strip(),
        "matched_rule_id": str(source.get("matched_rule_id") or "").strip(),
        "required_roles": _clean_text_list(source.get("required_roles")),
        "reason": str(source.get("reason") or "").strip(),
    }


def _normalize_release_request_auth(summary: Dict[str, Any] | None, *, default_status: str = "skipped") -> Dict[str, Any]:
    source = _as_dict(summary)
    return {
        "status": _normalize_choice(source.get("status"), QUALITY_GATE_CHECK_STATUSES, default_status),
        "required": bool(source.get("required")),
        "auth_path": str(source.get("auth_path") or "").strip(),
        "mode": str(source.get("mode") or "").strip(),
        "client_host": str(source.get("client_host") or "").strip(),
        "actor_id": str(source.get("actor_id") or "").strip(),
        "action": str(source.get("action") or "").strip(),
        "target_channel": str(source.get("target_channel") or "").strip(),
        "target_environment": str(source.get("target_environment") or "").strip(),
        "header_name": str(source.get("header_name") or "").strip(),
        "scheme": str(source.get("scheme") or "").strip(),
        "token_configured": bool(source.get("token_configured")),
        "token_present": bool(source.get("token_present")),
        "token_id": str(source.get("token_id") or "").strip(),
        "token_source": str(source.get("token_source") or "").strip(),
        "session_id": str(source.get("session_id") or "").strip(),
        "issued_by": str(source.get("issued_by") or "").strip(),
        "issued_at": str(source.get("issued_at") or "").strip(),
        "session_tracked": bool(source.get("session_tracked")),
        "identity_path": str(source.get("identity_path") or "").strip(),
        "identity_registry_exists": bool(source.get("identity_registry_exists")),
        "issuer_registered": bool(source.get("issuer_registered")),
        "issuer_status": str(source.get("issuer_status") or "").strip(),
        "issuer_subject_actor_ids": _clean_text_list(source.get("issuer_subject_actor_ids")),
        "max_session_age_hours": max(int(source.get("max_session_age_hours") or 0), 0),
        "required_actor_ids": _clean_text_list(source.get("required_actor_ids")),
        "reason": str(source.get("reason") or "").strip(),
    }


def _normalize_release_request_auth_posture(summary: Dict[str, Any] | None, *, default_status: str = "skipped") -> Dict[str, Any]:
    source = _as_dict(summary)
    return {
        "schema_version": str(source.get("schema_version") or "1.0").strip() or "1.0",
        "status": _normalize_choice(source.get("status"), QUALITY_GATE_CHECK_STATUSES, default_status),
        "path": str(source.get("path") or "").strip(),
        "manifest_path": str(source.get("manifest_path") or source.get("path") or "").strip(),
        "report_path": str(source.get("report_path") or "").strip(),
        "report_exists": bool(source.get("report_exists")),
        "manifest_exists": bool(source.get("manifest_exists")),
        "identity_registry_path": str(source.get("identity_registry_path") or "").strip(),
        "identity_registry_exists": bool(source.get("identity_registry_exists")),
        "identity_boundary_path": str(source.get("identity_boundary_path") or "").strip(),
        "identity_boundary_exists": bool(source.get("identity_boundary_exists")),
        "identity_boundary_profile_id": str(source.get("identity_boundary_profile_id") or "").strip(),
        "identity_boundary_status": _normalize_choice(source.get("identity_boundary_status"), QUALITY_GATE_CHECK_STATUSES, "warning"),
        "identity_boundary_summary": str(source.get("identity_boundary_summary") or "").strip(),
        "identity_provider_mode": str(source.get("identity_provider_mode") or "").strip(),
        "identity_provider_id": str(source.get("identity_provider_id") or "").strip(),
        "identity_provider_status": _normalize_choice(source.get("identity_provider_status"), QUALITY_GATE_CHECK_STATUSES, "warning"),
        "identity_session_policy_status": _normalize_choice(source.get("identity_session_policy_status"), QUALITY_GATE_CHECK_STATUSES, "warning"),
        "identity_session_required": bool(source.get("identity_session_required")),
        "identity_max_session_age_hours": max(int(source.get("identity_max_session_age_hours") or 0), 0),
        "identity_session_backend": str(source.get("identity_session_backend") or "").strip(),
        "identity_secret_rotation_status": _normalize_choice(source.get("identity_secret_rotation_status"), QUALITY_GATE_CHECK_STATUSES, "warning"),
        "identity_secret_rotation_required": bool(source.get("identity_secret_rotation_required")),
        "identity_secret_backend": str(source.get("identity_secret_backend") or "").strip(),
        "identity_rotation_owner": str(source.get("identity_rotation_owner") or "").strip(),
        "identity_rotation_window_days": max(int(source.get("identity_rotation_window_days") or 0), 0),
        "identity_handoff_required": bool(source.get("identity_handoff_required")),
        "identity_handoff_mode": str(source.get("identity_handoff_mode") or "").strip(),
        "identity_handoff_target_id": str(source.get("identity_handoff_target_id") or "").strip(),
        "identity_handoff_owner": str(source.get("identity_handoff_owner") or "").strip(),
        "identity_handoff_config_status": _normalize_choice(source.get("identity_handoff_config_status"), QUALITY_GATE_CHECK_STATUSES, "skipped"),
        "action": str(source.get("action") or "").strip(),
        "target_channel": str(source.get("target_channel") or "").strip(),
        "target_environment": str(source.get("target_environment") or "").strip(),
        "summary": str(source.get("summary") or "").strip(),
        "allow_local_without_token": bool(source.get("allow_local_without_token")),
        "env_fallback_configured": bool(source.get("env_fallback_configured")),
        "rotation_window_days": max(int(source.get("rotation_window_days") or 30), 0),
        "token_count": max(int(source.get("token_count") or 0), 0),
        "active_token_count": max(int(source.get("active_token_count") or 0), 0),
        "matching_token_count": max(int(source.get("matching_token_count") or 0), 0),
        "matching_bound_token_count": max(int(source.get("matching_bound_token_count") or 0), 0),
        "matching_unbound_token_count": max(int(source.get("matching_unbound_token_count") or 0), 0),
        "matching_session_token_count": max(int(source.get("matching_session_token_count") or 0), 0),
        "issuer_count": max(int(source.get("issuer_count") or 0), 0),
        "active_issuer_count": max(int(source.get("active_issuer_count") or 0), 0),
        "matching_registered_issuer_token_count": max(int(source.get("matching_registered_issuer_token_count") or 0), 0),
        "matching_unknown_issuer_token_count": max(int(source.get("matching_unknown_issuer_token_count") or 0), 0),
        "matching_inactive_issuer_token_count": max(int(source.get("matching_inactive_issuer_token_count") or 0), 0),
        "matching_unscoped_issuer_token_count": max(int(source.get("matching_unscoped_issuer_token_count") or 0), 0),
        "matching_subject_out_of_registry_count": max(int(source.get("matching_subject_out_of_registry_count") or 0), 0),
        "matching_stale_session_token_count": max(int(source.get("matching_stale_session_token_count") or 0), 0),
        "revoked_token_count": max(int(source.get("revoked_token_count") or 0), 0),
        "expired_token_count": max(int(source.get("expired_token_count") or 0), 0),
        "invalid_expiry_token_count": max(int(source.get("invalid_expiry_token_count") or 0), 0),
        "invalid_issued_at_token_count": max(int(source.get("invalid_issued_at_token_count") or 0), 0),
        "tokens_without_expiry_count": max(int(source.get("tokens_without_expiry_count") or 0), 0),
        "tokens_expiring_soon_count": max(int(source.get("tokens_expiring_soon_count") or 0), 0),
        "tokens_without_session_id_count": max(int(source.get("tokens_without_session_id_count") or 0), 0),
        "tokens_without_issued_by_count": max(int(source.get("tokens_without_issued_by_count") or 0), 0),
        "tokens_without_issued_at_count": max(int(source.get("tokens_without_issued_at_count") or 0), 0),
        "duplicate_token_id_count": max(int(source.get("duplicate_token_id_count") or 0), 0),
        "matching_token_ids": _clean_text_list(source.get("matching_token_ids")),
        "duplicate_token_ids": _clean_text_list(source.get("duplicate_token_ids")),
        "notes": _clean_text_list(source.get("notes")),
        "recommendations": _clean_text_list(source.get("recommendations")),
    }


def _normalize_release_request_auth_rotation_audit(summary: Dict[str, Any] | None, *, default_status: str = "skipped") -> Dict[str, Any]:
    source = _as_dict(summary)
    coverage = [
        _normalize_release_request_auth_posture(item)
        for item in list(source.get("coverage") or [])
        if isinstance(item, dict)
    ]
    return {
        "schema_version": str(source.get("schema_version") or "1.0").strip() or "1.0",
        "status": _normalize_choice(source.get("status"), QUALITY_GATE_CHECK_STATUSES, default_status),
        "summary": str(source.get("summary") or "").strip(),
        "auth_path": str(source.get("auth_path") or "").strip(),
        "manifest_exists": bool(source.get("manifest_exists")),
        "target_channel": str(source.get("target_channel") or "").strip(),
        "target_environment": str(source.get("target_environment") or "").strip(),
        "actions": _clean_text_list(source.get("actions")),
        "action_count": max(int(source.get("action_count") or len(coverage)), 0),
        "passed_action_count": max(int(source.get("passed_action_count") or 0), 0),
        "warning_action_count": max(int(source.get("warning_action_count") or 0), 0),
        "blocked_action_count": max(int(source.get("blocked_action_count") or 0), 0),
        "report_path": str(source.get("report_path") or "").strip(),
        "report_exists": bool(source.get("report_exists")),
        "coverage": coverage,
        "identity_handoff_required": bool(source.get("identity_handoff_required")),
        "identity_handoff_mode": str(source.get("identity_handoff_mode") or "").strip(),
        "identity_handoff_target_id": str(source.get("identity_handoff_target_id") or "").strip(),
        "identity_handoff_owner": str(source.get("identity_handoff_owner") or "").strip(),
        "identity_handoff_config_status": _normalize_choice(source.get("identity_handoff_config_status"), QUALITY_GATE_CHECK_STATUSES, "skipped"),
        "identity_handoff_dir": str(source.get("identity_handoff_dir") or "").strip(),
        "identity_handoff_exists": bool(source.get("identity_handoff_exists")),
        "identity_handoff_file_count": max(int(source.get("identity_handoff_file_count") or 0), 0),
        "identity_handoff_manifest_path": str(source.get("identity_handoff_manifest_path") or "").strip(),
        "identity_handoff_manifest_exists": bool(source.get("identity_handoff_manifest_exists")),
        "identity_handoff_instructions_path": str(source.get("identity_handoff_instructions_path") or "").strip(),
        "identity_handoff_instructions_exists": bool(source.get("identity_handoff_instructions_exists")),
        "identity_handoff_boundary_manifest_path": str(source.get("identity_handoff_boundary_manifest_path") or "").strip(),
        "identity_handoff_boundary_manifest_exists": bool(source.get("identity_handoff_boundary_manifest_exists")),
        "identity_handoff_registry_manifest_path": str(source.get("identity_handoff_registry_manifest_path") or "").strip(),
        "identity_handoff_registry_manifest_exists": bool(source.get("identity_handoff_registry_manifest_exists")),
        "identity_handoff_status": _normalize_choice(source.get("identity_handoff_status"), QUALITY_GATE_CHECK_STATUSES, "skipped"),
        "identity_handoff_summary": str(source.get("identity_handoff_summary") or "").strip(),
        "identity_handoff_missing_items": _clean_text_list(source.get("identity_handoff_missing_items")),
        "notes": _clean_text_list(source.get("notes")),
        "recommendations": _clean_text_list(source.get("recommendations")),
    }


def _normalize_release_request_auth_identity_audit(summary: Dict[str, Any] | None, *, default_status: str = "skipped") -> Dict[str, Any]:
    source = _as_dict(summary)
    coverage = [
        _normalize_release_request_auth_posture(item)
        for item in list(source.get("coverage") or [])
        if isinstance(item, dict)
    ]
    return {
        "schema_version": str(source.get("schema_version") or "1.0").strip() or "1.0",
        "status": _normalize_choice(source.get("status"), QUALITY_GATE_CHECK_STATUSES, default_status),
        "summary": str(source.get("summary") or "").strip(),
        "auth_path": str(source.get("auth_path") or "").strip(),
        "manifest_exists": bool(source.get("manifest_exists")),
        "identity_path": str(source.get("identity_path") or "").strip(),
        "identity_registry_exists": bool(source.get("identity_registry_exists")),
        "target_channel": str(source.get("target_channel") or "").strip(),
        "target_environment": str(source.get("target_environment") or "").strip(),
        "identity_boundary_profile_id": str(source.get("identity_boundary_profile_id") or "").strip(),
        "identity_boundary_status": _normalize_choice(source.get("identity_boundary_status"), QUALITY_GATE_CHECK_STATUSES, "warning"),
        "identity_provider_mode": str(source.get("identity_provider_mode") or "").strip(),
        "identity_provider_id": str(source.get("identity_provider_id") or "").strip(),
        "identity_session_required": bool(source.get("identity_session_required")),
        "identity_max_session_age_hours": max(int(source.get("identity_max_session_age_hours") or 0), 0),
        "identity_session_backend": str(source.get("identity_session_backend") or "").strip(),
        "identity_secret_rotation_required": bool(source.get("identity_secret_rotation_required")),
        "identity_secret_backend": str(source.get("identity_secret_backend") or "").strip(),
        "identity_rotation_owner": str(source.get("identity_rotation_owner") or "").strip(),
        "identity_rotation_window_days": max(int(source.get("identity_rotation_window_days") or 0), 0),
        "actions": _clean_text_list(source.get("actions")),
        "action_count": max(int(source.get("action_count") or len(coverage)), 0),
        "passed_action_count": max(int(source.get("passed_action_count") or 0), 0),
        "warning_action_count": max(int(source.get("warning_action_count") or 0), 0),
        "blocked_action_count": max(int(source.get("blocked_action_count") or 0), 0),
        "issuer_count": max(int(source.get("issuer_count") or 0), 0),
        "active_issuer_count": max(int(source.get("active_issuer_count") or 0), 0),
        "scoped_issuer_count": max(int(source.get("scoped_issuer_count") or 0), 0),
        "session_required_issuer_count": max(int(source.get("session_required_issuer_count") or 0), 0),
        "session_windowed_issuer_count": max(int(source.get("session_windowed_issuer_count") or 0), 0),
        "unbound_issuer_count": max(int(source.get("unbound_issuer_count") or 0), 0),
        "duplicate_issuer_id_count": max(int(source.get("duplicate_issuer_id_count") or 0), 0),
        "duplicate_issuer_ids": _clean_text_list(source.get("duplicate_issuer_ids")),
        "matching_registered_issuer_token_count": max(int(source.get("matching_registered_issuer_token_count") or 0), 0),
        "matching_unknown_issuer_token_count": max(int(source.get("matching_unknown_issuer_token_count") or 0), 0),
        "matching_inactive_issuer_token_count": max(int(source.get("matching_inactive_issuer_token_count") or 0), 0),
        "matching_unscoped_issuer_token_count": max(int(source.get("matching_unscoped_issuer_token_count") or 0), 0),
        "matching_subject_out_of_registry_count": max(int(source.get("matching_subject_out_of_registry_count") or 0), 0),
        "matching_stale_session_token_count": max(int(source.get("matching_stale_session_token_count") or 0), 0),
        "matching_session_token_count": max(int(source.get("matching_session_token_count") or 0), 0),
        "release_issuers_without_session_requirement_count": max(int(source.get("release_issuers_without_session_requirement_count") or 0), 0),
        "release_issuers_without_session_window_count": max(int(source.get("release_issuers_without_session_window_count") or 0), 0),
        "report_path": str(source.get("report_path") or "").strip(),
        "report_exists": bool(source.get("report_exists")),
        "coverage": coverage,
        "notes": _clean_text_list(source.get("notes")),
        "recommendations": _clean_text_list(source.get("recommendations")),
    }


def _normalize_release_distribution_bundle(summary: Dict[str, Any] | None, *, default_status: str = "skipped") -> Dict[str, Any]:
    source = _as_dict(summary)
    return {
        "schema_version": str(source.get("schema_version") or RELEASE_DISTRIBUTION_BUNDLE_SCHEMA_VERSION).strip() or RELEASE_DISTRIBUTION_BUNDLE_SCHEMA_VERSION,
        "status": _normalize_choice(source.get("status"), QUALITY_GATE_CHECK_STATUSES, default_status),
        "summary": str(source.get("summary") or "").strip(),
        "target_channel": str(source.get("target_channel") or "").strip(),
        "target_environment": str(source.get("target_environment") or "").strip(),
        "build_id": str(source.get("build_id") or "").strip(),
        "version": str(source.get("version") or "").strip(),
        "release_channel": str(source.get("release_channel") or "").strip(),
        "release_manifest_path": str(source.get("release_manifest_path") or "").strip(),
        "release_manifest_source": str(source.get("release_manifest_source") or "").strip(),
        "release_notes_path": str(source.get("release_notes_path") or "").strip(),
        "qa_gate_report_path": str(source.get("qa_gate_report_path") or "").strip(),
        "build_log_path": str(source.get("build_log_path") or "").strip(),
        "release_dir": str(source.get("release_dir") or "").strip(),
        "output_path": str(source.get("output_path") or "").strip(),
        "release_url": str(source.get("release_url") or "").strip(),
        "versioned_release_url": str(source.get("versioned_release_url") or "").strip(),
        "bundle_root": str(source.get("bundle_root") or "").strip(),
        "bundle_dir": str(source.get("bundle_dir") or "").strip(),
        "bundle_exists": bool(source.get("bundle_exists")),
        "bundle_file_count": max(int(source.get("bundle_file_count") or 0), 0),
        "payload_dir": str(source.get("payload_dir") or "").strip(),
        "payload_exists": bool(source.get("payload_exists")),
        "payload_file_count": max(int(source.get("payload_file_count") or 0), 0),
        "distribution_manifest_path": str(source.get("distribution_manifest_path") or "").strip(),
        "distribution_manifest_exists": bool(source.get("distribution_manifest_exists")),
        "install_script_path": str(source.get("install_script_path") or "").strip(),
        "install_script_exists": bool(source.get("install_script_exists")),
        "upgrade_script_path": str(source.get("upgrade_script_path") or "").strip(),
        "upgrade_script_exists": bool(source.get("upgrade_script_exists")),
        "uninstall_script_path": str(source.get("uninstall_script_path") or "").strip(),
        "uninstall_script_exists": bool(source.get("uninstall_script_exists")),
        "support_matrix_source_path": str(source.get("support_matrix_source_path") or "").strip(),
        "support_matrix_path": str(source.get("support_matrix_path") or "").strip(),
        "support_matrix_exists": bool(source.get("support_matrix_exists")),
        "bootstrap_script_source_path": str(source.get("bootstrap_script_source_path") or "").strip(),
        "bundle_manifest_copy_path": str(source.get("bundle_manifest_copy_path") or "").strip(),
        "bundle_manifest_copy_exists": bool(source.get("bundle_manifest_copy_exists")),
        "bundle_release_notes_path": str(source.get("bundle_release_notes_path") or "").strip(),
        "bundle_release_notes_exists": bool(source.get("bundle_release_notes_exists")),
        "bundle_qa_gate_report_path": str(source.get("bundle_qa_gate_report_path") or "").strip(),
        "bundle_qa_gate_report_exists": bool(source.get("bundle_qa_gate_report_exists")),
        "state_manifest_path": str(source.get("state_manifest_path") or "").strip(),
        "state_manifest_exists": bool(source.get("state_manifest_exists")),
        "report_path": str(source.get("report_path") or "").strip(),
        "report_exists": bool(source.get("report_exists")),
        "install_smoke_report_path": str(source.get("install_smoke_report_path") or "").strip(),
        "install_smoke_report_exists": bool(source.get("install_smoke_report_exists")),
        "install_smoke_status": _normalize_choice(source.get("install_smoke_status"), QUALITY_GATE_CHECK_STATUSES, "skipped"),
        "install_smoke_summary": str(source.get("install_smoke_summary") or "").strip(),
        "install_smoke_target_root": str(source.get("install_smoke_target_root") or "").strip(),
        "install_smoke_state_path": str(source.get("install_smoke_state_path") or "").strip(),
        "install_smoke_backup_count": max(int(source.get("install_smoke_backup_count") or 0), 0),
        "install_smoke_marker_preserved": bool(source.get("install_smoke_marker_preserved")),
        "install_smoke_current_exists": bool(source.get("install_smoke_current_exists")),
        "install_smoke_state_written": bool(source.get("install_smoke_state_written")),
        "install_smoke_state_removed": bool(source.get("install_smoke_state_removed")),
        "install_smoke_installed_build_id": str(source.get("install_smoke_installed_build_id") or "").strip(),
        "install_smoke_installed_version": str(source.get("install_smoke_installed_version") or "").strip(),
        "install_smoke_previous_build_id": str(source.get("install_smoke_previous_build_id") or "").strip(),
        "install_smoke_backup_dir": str(source.get("install_smoke_backup_dir") or "").strip(),
        "install_smoke_removed_build_id": str(source.get("install_smoke_removed_build_id") or "").strip(),
        "install_smoke_removed_version": str(source.get("install_smoke_removed_version") or "").strip(),
        "archive_dir": str(source.get("archive_dir") or "").strip(),
        "archive_exists": bool(source.get("archive_exists")),
        "archive_path": str(source.get("archive_path") or "").strip(),
        "archive_file_exists": bool(source.get("archive_file_exists")),
        "archive_sha256_path": str(source.get("archive_sha256_path") or "").strip(),
        "archive_sha256_exists": bool(source.get("archive_sha256_exists")),
        "archive_size_bytes": max(int(source.get("archive_size_bytes") or 0), 0),
        "archive_status": _normalize_choice(source.get("archive_status"), QUALITY_GATE_CHECK_STATUSES, "skipped"),
        "archive_summary": str(source.get("archive_summary") or "").strip(),
        "channel_index_dir": str(source.get("channel_index_dir") or "").strip(),
        "channel_index_exists": bool(source.get("channel_index_exists")),
        "channel_index_report_path": str(source.get("channel_index_report_path") or "").strip(),
        "channel_index_report_exists": bool(source.get("channel_index_report_exists")),
        "channel_index_latest_path": str(source.get("channel_index_latest_path") or "").strip(),
        "channel_index_latest_exists": bool(source.get("channel_index_latest_exists")),
        "channel_index_releases_path": str(source.get("channel_index_releases_path") or "").strip(),
        "channel_index_releases_exists": bool(source.get("channel_index_releases_exists")),
        "channel_index_release_count": max(int(source.get("channel_index_release_count") or 0), 0),
        "channel_index_latest_build_id": str(source.get("channel_index_latest_build_id") or "").strip(),
        "channel_index_latest_matches_current": bool(source.get("channel_index_latest_matches_current")),
        "channel_index_status": _normalize_choice(source.get("channel_index_status"), QUALITY_GATE_CHECK_STATUSES, "skipped"),
        "channel_index_summary": str(source.get("channel_index_summary") or "").strip(),
        "handoff_dir": str(source.get("handoff_dir") or "").strip(),
        "handoff_exists": bool(source.get("handoff_exists")),
        "handoff_file_count": max(int(source.get("handoff_file_count") or 0), 0),
        "handoff_manifest_path": str(source.get("handoff_manifest_path") or "").strip(),
        "handoff_manifest_exists": bool(source.get("handoff_manifest_exists")),
        "handoff_install_script_path": str(source.get("handoff_install_script_path") or "").strip(),
        "handoff_install_script_exists": bool(source.get("handoff_install_script_exists")),
        "handoff_upgrade_script_path": str(source.get("handoff_upgrade_script_path") or "").strip(),
        "handoff_upgrade_script_exists": bool(source.get("handoff_upgrade_script_exists")),
        "handoff_uninstall_script_path": str(source.get("handoff_uninstall_script_path") or "").strip(),
        "handoff_uninstall_script_exists": bool(source.get("handoff_uninstall_script_exists")),
        "handoff_archive_path": str(source.get("handoff_archive_path") or "").strip(),
        "handoff_archive_exists": bool(source.get("handoff_archive_exists")),
        "handoff_archive_sha256_path": str(source.get("handoff_archive_sha256_path") or "").strip(),
        "handoff_archive_sha256_exists": bool(source.get("handoff_archive_sha256_exists")),
        "handoff_channel_latest_path": str(source.get("handoff_channel_latest_path") or "").strip(),
        "handoff_channel_latest_exists": bool(source.get("handoff_channel_latest_exists")),
        "handoff_channel_releases_path": str(source.get("handoff_channel_releases_path") or "").strip(),
        "handoff_channel_releases_exists": bool(source.get("handoff_channel_releases_exists")),
        "handoff_status": _normalize_choice(source.get("handoff_status"), QUALITY_GATE_CHECK_STATUSES, "skipped"),
        "handoff_summary": str(source.get("handoff_summary") or "").strip(),
        "signing_handoff_dir": str(source.get("signing_handoff_dir") or "").strip(),
        "signing_handoff_exists": bool(source.get("signing_handoff_exists")),
        "signing_handoff_file_count": max(int(source.get("signing_handoff_file_count") or 0), 0),
        "signing_handoff_manifest_path": str(source.get("signing_handoff_manifest_path") or "").strip(),
        "signing_handoff_manifest_exists": bool(source.get("signing_handoff_manifest_exists")),
        "signing_handoff_instructions_path": str(source.get("signing_handoff_instructions_path") or "").strip(),
        "signing_handoff_instructions_exists": bool(source.get("signing_handoff_instructions_exists")),
        "signing_handoff_unsigned_archive_path": str(source.get("signing_handoff_unsigned_archive_path") or "").strip(),
        "signing_handoff_unsigned_archive_exists": bool(source.get("signing_handoff_unsigned_archive_exists")),
        "signing_handoff_unsigned_archive_sha256_path": str(source.get("signing_handoff_unsigned_archive_sha256_path") or "").strip(),
        "signing_handoff_unsigned_archive_sha256_exists": bool(source.get("signing_handoff_unsigned_archive_sha256_exists")),
        "signing_handoff_status": _normalize_choice(source.get("signing_handoff_status"), QUALITY_GATE_CHECK_STATUSES, "skipped"),
        "signing_handoff_summary": str(source.get("signing_handoff_summary") or "").strip(),
        "publish_handoff_dir": str(source.get("publish_handoff_dir") or "").strip(),
        "publish_handoff_exists": bool(source.get("publish_handoff_exists")),
        "publish_handoff_file_count": max(int(source.get("publish_handoff_file_count") or 0), 0),
        "publish_handoff_manifest_path": str(source.get("publish_handoff_manifest_path") or "").strip(),
        "publish_handoff_manifest_exists": bool(source.get("publish_handoff_manifest_exists")),
        "publish_handoff_instructions_path": str(source.get("publish_handoff_instructions_path") or "").strip(),
        "publish_handoff_instructions_exists": bool(source.get("publish_handoff_instructions_exists")),
        "publish_handoff_archive_path": str(source.get("publish_handoff_archive_path") or "").strip(),
        "publish_handoff_archive_exists": bool(source.get("publish_handoff_archive_exists")),
        "publish_handoff_archive_sha256_path": str(source.get("publish_handoff_archive_sha256_path") or "").strip(),
        "publish_handoff_archive_sha256_exists": bool(source.get("publish_handoff_archive_sha256_exists")),
        "publish_handoff_channel_latest_path": str(source.get("publish_handoff_channel_latest_path") or "").strip(),
        "publish_handoff_channel_latest_exists": bool(source.get("publish_handoff_channel_latest_exists")),
        "publish_handoff_channel_releases_path": str(source.get("publish_handoff_channel_releases_path") or "").strip(),
        "publish_handoff_channel_releases_exists": bool(source.get("publish_handoff_channel_releases_exists")),
        "publish_handoff_status": _normalize_choice(source.get("publish_handoff_status"), QUALITY_GATE_CHECK_STATUSES, "skipped"),
        "publish_handoff_summary": str(source.get("publish_handoff_summary") or "").strip(),
        "publish_receipts_dir": str(source.get("publish_receipts_dir") or "").strip(),
        "publish_receipts_exists": bool(source.get("publish_receipts_exists")),
        "publish_receipts_file_count": max(int(source.get("publish_receipts_file_count") or 0), 0),
        "publish_receipts_manifest_path": str(source.get("publish_receipts_manifest_path") or "").strip(),
        "publish_receipts_manifest_exists": bool(source.get("publish_receipts_manifest_exists")),
        "publish_receipts_target_count": max(int(source.get("publish_receipts_target_count") or 0), 0),
        "publish_receipts_recorded_target_count": max(int(source.get("publish_receipts_recorded_target_count") or 0), 0),
        "publish_receipts_completed_targets": _clean_text_list(source.get("publish_receipts_completed_targets")),
        "publish_receipts_failed_targets": _clean_text_list(source.get("publish_receipts_failed_targets")),
        "publish_receipts_missing_targets": _clean_text_list(source.get("publish_receipts_missing_targets")),
        "publish_receipts_manifest_matches_current": bool(source.get("publish_receipts_manifest_matches_current")),
        "publish_receipts_status": _normalize_choice(source.get("publish_receipts_status"), QUALITY_GATE_CHECK_STATUSES, "skipped"),
        "publish_receipts_summary": str(source.get("publish_receipts_summary") or "").strip(),
        "delivery_manifest_path": str(source.get("delivery_manifest_path") or "").strip(),
        "delivery_manifest_exists": bool(source.get("delivery_manifest_exists")),
        "delivery_profile_id": str(source.get("delivery_profile_id") or "").strip(),
        "delivery_status": _normalize_choice(source.get("delivery_status"), QUALITY_GATE_CHECK_STATUSES, "warning"),
        "delivery_summary": str(source.get("delivery_summary") or "").strip(),
        "delivery_primary_installer": str(source.get("delivery_primary_installer") or "").strip(),
        "delivery_installer_types": _clean_text_list(source.get("delivery_installer_types")),
        "delivery_installer_status": _normalize_choice(source.get("delivery_installer_status"), QUALITY_GATE_CHECK_STATUSES, "warning"),
        "delivery_signing_required": bool(source.get("delivery_signing_required")),
        "delivery_signing_mode": str(source.get("delivery_signing_mode") or "").strip(),
        "delivery_signing_profile_id": str(source.get("delivery_signing_profile_id") or "").strip(),
        "delivery_signing_status": _normalize_choice(source.get("delivery_signing_status"), QUALITY_GATE_CHECK_STATUSES, "warning"),
        "delivery_publish_targets": _clean_text_list(source.get("delivery_publish_targets")),
        "delivery_publish_target_count": max(int(source.get("delivery_publish_target_count") or 0), 0),
        "delivery_publish_status": _normalize_choice(source.get("delivery_publish_status"), QUALITY_GATE_CHECK_STATUSES, "warning"),
        "delivery_first_run_bootstrap": str(source.get("delivery_first_run_bootstrap") or "").strip(),
        "delivery_upgrade_strategy": str(source.get("delivery_upgrade_strategy") or "").strip(),
        "delivery_uninstall_strategy": str(source.get("delivery_uninstall_strategy") or "").strip(),
        "source_missing_items": _clean_text_list(source.get("source_missing_items")),
        "bundle_missing_items": _clean_text_list(source.get("bundle_missing_items")),
        "handoff_missing_items": _clean_text_list(source.get("handoff_missing_items")),
        "signing_handoff_missing_items": _clean_text_list(source.get("signing_handoff_missing_items")),
        "publish_handoff_missing_items": _clean_text_list(source.get("publish_handoff_missing_items")),
        "exported_files": _clean_text_list(source.get("exported_files")),
        "notes": _clean_text_list(source.get("notes")),
        "recommendations": _clean_text_list(source.get("recommendations")),
    }


def normalize_release_promotion_history(summary: Dict[str, Any] | None) -> Dict[str, Any]:
    source = dict(summary or {})
    decision_values = {"planned", "approved", "promoted", "blocked", "rolled_back", "aborted"}
    notes = _clean_text_list(source.get("notes"))
    recommendations = _clean_text_list(source.get("recommendations"))
    decision_filter = str(source.get("decision_filter") or "").strip().lower()
    target_channel_filter = str(source.get("target_channel_filter") or "").strip().lower()
    executor_filter = str(source.get("executor_filter") or "").strip()
    live_ci_status_filter = _normalize_choice(source.get("live_ci_status_filter"), QUALITY_GATE_CHECK_STATUSES, "")
    dispatch_status_filter = _normalize_choice(source.get("dispatch_status_filter"), QUALITY_GATE_CHECK_STATUSES, "")
    dispatch_follow_up_filter = str(source.get("dispatch_follow_up_filter") or "").strip().lower()
    dispatch_run_status_filter = str(source.get("dispatch_run_status_filter") or "").strip().lower()
    dispatch_run_conclusion_filter = str(source.get("dispatch_run_conclusion_filter") or "").strip().lower()
    failed_workflow_step_filter = str(source.get("failed_workflow_step_filter") or "").strip()
    delivery_readiness_status_filter = _normalize_choice(source.get("delivery_readiness_status_filter"), QUALITY_GATE_CHECK_STATUSES, "")
    readiness_action_filter = str(source.get("readiness_action_filter") or "").strip()
    offset = max(int(source.get("offset") or 0), 0)
    limit = max(int(source.get("limit") or 20), 1)

    items: List[Dict[str, Any]] = []
    for index, item in enumerate(list(source.get("items") or source.get("records") or []), start=1):
        raw = _as_dict(item)
        plan_snapshot = normalize_release_promotion_plan(raw.get("plan_snapshot"))
        review_bundle = dict(plan_snapshot.get("review_bundle") or {})
        review_followup_actions = _normalize_review_followup_actions(
            raw.get("review_followup_actions") or review_bundle.get("review_followup_actions")
        )
        release_summary = dict(plan_snapshot.get("release_candidate_checklist", {}).get("release_summary") or {})
        evidence_bundle = dict(plan_snapshot.get("evidence_bundle") or {})
        deployment_rehearsal = dict(plan_snapshot.get("deployment_rehearsal") or {})
        rollback_rehearsal = dict(plan_snapshot.get("rollback_rehearsal") or {})
        release_distribution_bundle = _normalize_release_distribution_bundle(plan_snapshot.get("release_distribution_bundle"))
        release_delivery_readiness = normalize_release_delivery_readiness(
            raw.get("release_delivery_readiness") or plan_snapshot.get("release_delivery_readiness")
        )
        release_delivery_readiness_next_actions = [
            _normalize_release_delivery_readiness_action(item)
            for item in list(
                raw.get("release_delivery_readiness_next_actions")
                or release_delivery_readiness.get("next_actions")
                or []
            )
            if isinstance(item, dict)
        ]
        release_live_ci_summary = _normalize_release_live_ci_summary(plan_snapshot.get("release_live_ci_summary"))
        release_live_ci_details = dict(release_live_ci_summary.get("details") or {})
        release_live_dispatch_audit = normalize_release_live_dispatch_audit(
            raw.get("release_live_dispatch_audit")
            or release_live_ci_details.get("dispatch_audit")
        )
        release_live_ci_runtime_assembly = normalize_release_runtime_assembly_snapshot(
            raw.get("release_live_ci_runtime_assembly")
            or plan_snapshot.get("runtime_assembly_snapshot")
            or release_live_ci_details.get("runtime_assembly")
        )
        release_live_ci_event_stream = normalize_release_live_event_stream(
            raw.get("release_live_ci_event_stream")
            or release_live_ci_details.get("event_stream")
        )
        release_live_ci_workflow_steps = [
            {
                "step_id": str(_as_dict(step).get("step_id") or "").strip(),
                "label": str(_as_dict(step).get("label") or "").strip(),
                "status": _normalize_choice(_as_dict(step).get("status"), QUALITY_GATE_CHECK_STATUSES, "skipped"),
                "outcome": str(_as_dict(step).get("outcome") or "").strip(),
                "always_run": bool(_as_dict(step).get("always_run")),
                "message": str(_as_dict(step).get("message") or "").strip(),
            }
            for step in list(raw.get("release_live_ci_workflow_steps") or release_live_ci_details.get("workflow_steps") or [])
            if isinstance(step, dict)
        ]
        release_live_ci_failed_workflow_steps = _clean_text_list(
            raw.get("release_live_ci_failed_workflow_steps")
            or [
                str(step.get("step_id") or step.get("label") or "").strip()
                for step in release_live_ci_workflow_steps
                if str(step.get("status") or "").strip().lower() in {"warning", "blocked"}
            ]
        )
        items.append({
            "record_id": str(raw.get("record_id") or f"promotion_record_{index}").strip() or f"promotion_record_{index}",
            "recorded_at": str(raw.get("recorded_at") or "").strip(),
            "decision": _normalize_choice(raw.get("decision"), decision_values, "planned"),
            "target_channel": str(raw.get("target_channel") or plan_snapshot.get("target_channel") or "").strip() or "staging",
            "target_environment": str(raw.get("target_environment") or plan_snapshot.get("target_environment") or "").strip() or "staging",
            "promotion_target_label": str(raw.get("promotion_target_label") or plan_snapshot.get("promotion_target_label") or "").strip(),
            "executed_by": str(raw.get("executed_by") or "").strip(),
            "note": str(raw.get("note") or "").strip(),
            "signoff_source": str(raw.get("signoff_source") or "").strip(),
            "plan_status": _normalize_choice(raw.get("plan_status") or plan_snapshot.get("status"), QUALITY_GATE_CHECK_STATUSES, "skipped"),
            "should_block": bool(raw.get("should_block")) or bool(plan_snapshot.get("should_block")),
            "blocking_checks": _clean_text_list(raw.get("blocking_checks")) or list(plan_snapshot.get("blocking_checks") or []),
            "warning_checks": _clean_text_list(raw.get("warning_checks")) or list(plan_snapshot.get("warning_checks") or []),
            "missing_signoffs": _clean_text_list(raw.get("missing_signoffs")) or list(plan_snapshot.get("missing_signoffs") or []),
            "review_followup_actions": review_followup_actions,
            "review_followup_action_count": int(raw.get("review_followup_action_count") or len(review_followup_actions)),
            "authorization": _normalize_release_authorization(raw.get("authorization")),
            "request_auth": _normalize_release_request_auth(raw.get("request_auth")),
            "selected_scenario_ids": _clean_text_list(raw.get("selected_scenario_ids")) or list(plan_snapshot.get("selected_scenario_ids") or []),
            "selected_provider_ids": _clean_text_list(raw.get("selected_provider_ids")) or list(plan_snapshot.get("selected_provider_ids") or []),
            "release_manifest_path": str(raw.get("release_manifest_path") or plan_snapshot.get("release_manifest_path") or "").strip(),
            "release_build_id": str(raw.get("release_build_id") or release_summary.get("build_id") or "").strip(),
            "release_version": str(raw.get("release_version") or release_summary.get("version") or "").strip(),
            "release_channel": str(raw.get("release_channel") or release_summary.get("channel") or "").strip(),
            "evidence_status": _normalize_choice(raw.get("evidence_status") or evidence_bundle.get("status"), QUALITY_GATE_CHECK_STATUSES, "skipped"),
            "evidence_artifact_count": int(raw.get("evidence_artifact_count") or evidence_bundle.get("artifact_count") or 0),
            "distribution_status": _normalize_choice(
                raw.get("distribution_status") or release_distribution_bundle.get("status"),
                QUALITY_GATE_CHECK_STATUSES,
                "skipped",
            ),
            "distribution_summary": str(
                raw.get("distribution_summary")
                or release_distribution_bundle.get("summary")
                or ""
            ).strip(),
            "distribution_publish_receipts_status": _normalize_choice(
                raw.get("distribution_publish_receipts_status") or release_distribution_bundle.get("publish_receipts_status"),
                QUALITY_GATE_CHECK_STATUSES,
                "skipped",
            ),
            "distribution_publish_receipts_summary": str(
                raw.get("distribution_publish_receipts_summary")
                or release_distribution_bundle.get("publish_receipts_summary")
                or ""
            ).strip(),
            "distribution_publish_receipts_manifest_path": str(
                raw.get("distribution_publish_receipts_manifest_path")
                or release_distribution_bundle.get("publish_receipts_manifest_path")
                or ""
            ).strip(),
            "distribution_publish_receipts_target_count": int(
                raw.get("distribution_publish_receipts_target_count")
                or release_distribution_bundle.get("publish_receipts_target_count")
                or 0
            ),
            "distribution_publish_receipts_completed_targets": _clean_text_list(
                raw.get("distribution_publish_receipts_completed_targets")
                or release_distribution_bundle.get("publish_receipts_completed_targets")
            ),
            "distribution_publish_receipts_failed_targets": _clean_text_list(
                raw.get("distribution_publish_receipts_failed_targets")
                or release_distribution_bundle.get("publish_receipts_failed_targets")
            ),
            "distribution_publish_receipts_missing_targets": _clean_text_list(
                raw.get("distribution_publish_receipts_missing_targets")
                or release_distribution_bundle.get("publish_receipts_missing_targets")
            ),
            "distribution_publish_receipts_follow_up_required": bool(raw.get("distribution_publish_receipts_follow_up_required")) or (
                bool(list(release_distribution_bundle.get("publish_receipts_failed_targets") or []))
                or (
                    bool(release_distribution_bundle.get("publish_receipts_manifest_exists"))
                    and not bool(release_distribution_bundle.get("publish_receipts_manifest_matches_current"))
                )
                or (
                    int(release_distribution_bundle.get("publish_receipts_recorded_target_count") or 0) > 0
                    and bool(list(release_distribution_bundle.get("publish_receipts_missing_targets") or []))
                )
            ),
            "release_delivery_readiness": release_delivery_readiness,
            "release_delivery_readiness_status": _normalize_choice(
                raw.get("release_delivery_readiness_status") or release_delivery_readiness.get("status"),
                QUALITY_GATE_CHECK_STATUSES,
                "warning",
            ),
            "release_delivery_readiness_summary": str(
                raw.get("release_delivery_readiness_summary")
                or release_delivery_readiness.get("summary")
                or ""
            ).strip(),
            "release_delivery_readiness_next_actions": release_delivery_readiness_next_actions,
            "release_delivery_readiness_next_action_count": int(
                raw.get("release_delivery_readiness_next_action_count")
                or len(release_delivery_readiness_next_actions)
            ),
            "release_delivery_readiness_blocking_checks": _clean_text_list(
                raw.get("release_delivery_readiness_blocking_checks")
                or release_delivery_readiness.get("blocking_checks")
            ),
            "release_delivery_readiness_warning_checks": _clean_text_list(
                raw.get("release_delivery_readiness_warning_checks")
                or release_delivery_readiness.get("warning_checks")
            ),
            "release_live_ci_status": _normalize_choice(
                raw.get("release_live_ci_status") or release_live_ci_summary.get("status"),
                QUALITY_GATE_CHECK_STATUSES,
                "skipped",
            ),
            "release_live_ci_path": str(
                raw.get("release_live_ci_path")
                or release_live_ci_summary.get("path")
                or ""
            ).strip(),
            "release_live_ci_summary": str(
                raw.get("release_live_ci_summary")
                or release_live_ci_summary.get("summary")
                or ""
            ).strip(),
            "release_live_ci_summary_markdown_path": str(
                raw.get("release_live_ci_summary_markdown_path")
                or release_live_ci_details.get("summary_markdown_path")
                or ""
            ).strip(),
            "release_live_dispatch_audit": release_live_dispatch_audit,
            "release_live_dispatch_status": _normalize_choice(
                raw.get("release_live_dispatch_status") or release_live_dispatch_audit.get("status"),
                QUALITY_GATE_CHECK_STATUSES,
                "skipped",
            ),
            "release_live_dispatch_summary": str(
                raw.get("release_live_dispatch_summary")
                or release_live_dispatch_audit.get("summary")
                or ""
            ).strip(),
            "release_live_dispatch_path": str(
                raw.get("release_live_dispatch_path")
                or release_live_dispatch_audit.get("path")
                or ""
            ).strip(),
            "release_live_dispatch_recorded_at": str(
                raw.get("release_live_dispatch_recorded_at")
                or release_live_dispatch_audit.get("recorded_at")
                or ""
            ).strip(),
            "release_live_dispatch_triggered_by": str(
                raw.get("release_live_dispatch_triggered_by")
                or release_live_dispatch_audit.get("triggered_by")
                or ""
            ).strip(),
            "release_live_dispatch_follow_up_required": bool(raw.get("release_live_dispatch_follow_up_required"))
            or bool(release_live_dispatch_audit.get("follow_up_required")),
            "release_live_dispatch_run_status": str(
                raw.get("release_live_dispatch_run_status")
                or dict(release_live_dispatch_audit.get("run") or {}).get("status")
                or ""
            ).strip(),
            "release_live_dispatch_run_conclusion": str(
                raw.get("release_live_dispatch_run_conclusion")
                or dict(release_live_dispatch_audit.get("run") or {}).get("conclusion")
                or ""
            ).strip(),
            "release_live_dispatch_run_url": str(
                raw.get("release_live_dispatch_run_url")
                or dict(release_live_dispatch_audit.get("run") or {}).get("html_url")
                or ""
            ).strip(),
            "release_live_ci_runtime_assembly": release_live_ci_runtime_assembly,
            "release_live_ci_event_stream": release_live_ci_event_stream,
            "release_live_ci_event_stream_path": str(
                raw.get("release_live_ci_event_stream_path")
                or release_live_ci_event_stream.get("path")
                or ""
            ).strip(),
            "release_live_ci_event_stream_status": _normalize_choice(
                raw.get("release_live_ci_event_stream_status") or release_live_ci_event_stream.get("status"),
                QUALITY_GATE_CHECK_STATUSES,
                "skipped",
            ),
            "release_live_ci_event_count": max(
                int(raw.get("release_live_ci_event_count") or release_live_ci_event_stream.get("event_count") or 0),
                0,
            ),
            "release_live_ci_latest_event_type": str(
                raw.get("release_live_ci_latest_event_type")
                or release_live_ci_event_stream.get("latest_event_type")
                or ""
            ).strip(),
            "release_live_ci_latest_event_status": _normalize_choice(
                raw.get("release_live_ci_latest_event_status") or release_live_ci_event_stream.get("latest_event_status"),
                QUALITY_GATE_CHECK_STATUSES,
                "skipped",
            ),
            "release_live_ci_workflow_step_results_path": str(
                raw.get("release_live_ci_workflow_step_results_path")
                or release_live_ci_details.get("workflow_step_results_path")
                or ""
            ).strip(),
            "release_live_ci_workflow_steps": release_live_ci_workflow_steps,
            "release_live_ci_failed_workflow_steps": release_live_ci_failed_workflow_steps,
            "release_live_ci_follow_up_required": bool(raw.get("release_live_ci_follow_up_required"))
            or bool(release_live_ci_failed_workflow_steps)
            or str(raw.get("release_live_ci_status") or release_live_ci_summary.get("status") or "").strip().lower() in {"warning", "blocked"},
            "deployment_status": _normalize_choice(raw.get("deployment_status") or deployment_rehearsal.get("status"), QUALITY_GATE_CHECK_STATUSES, "skipped"),
            "rollback_status": _normalize_choice(raw.get("rollback_status") or rollback_rehearsal.get("status"), QUALITY_GATE_CHECK_STATUSES, "skipped"),
            "plan_snapshot": plan_snapshot,
        })

    decision_counts: Dict[str, int] = {}
    for item in items:
        decision = str(item.get("decision") or "planned")
        decision_counts[decision] = decision_counts.get(decision, 0) + 1

    contract_versions = dict(_as_dict(source.get("contract_versions")))
    contract_versions["release_promotion_history"] = RELEASE_PROMOTION_HISTORY_SCHEMA_VERSION
    if items:
        contract_versions["release_promotion_plan"] = items[0]["plan_snapshot"].get("schema_version", "")
        latest_review_bundle = dict(items[0]["plan_snapshot"].get("review_bundle") or {})
        contract_versions["release_review_bundle"] = latest_review_bundle.get("schema_version", "")
    latest_dispatch_audit = normalize_release_live_dispatch_audit(
        source.get("latest_dispatch_audit")
        or (items[0].get("release_live_dispatch_audit") if items else {})
    )
    if latest_dispatch_audit.get("schema_version"):
        contract_versions["release_live_dispatch_audit"] = str(
            contract_versions.get("release_live_dispatch_audit")
            or latest_dispatch_audit.get("schema_version")
            or RELEASE_LIVE_DISPATCH_AUDIT_SCHEMA_VERSION
        )
    matched_count = int(source.get("matched_count") or len(items))
    total_count = int(source.get("total_count") or len(items))
    visible_count = int(source.get("visible_count") or len(items))
    latest_record = items[0] if items else {}

    return {
        "schema_version": RELEASE_PROMOTION_HISTORY_SCHEMA_VERSION,
        "contract_versions": contract_versions,
        "project_root": str(source.get("project_root") or "").strip(),
        "runtime_root": str(source.get("runtime_root") or "").strip(),
        "history_path": str(source.get("history_path") or "").strip(),
        "history_exists": bool(source.get("history_exists")),
        "decision_filter": decision_filter,
        "target_channel_filter": target_channel_filter,
        "executor_filter": executor_filter,
        "live_ci_status_filter": live_ci_status_filter,
        "dispatch_status_filter": dispatch_status_filter,
        "dispatch_follow_up_filter": dispatch_follow_up_filter,
        "dispatch_run_status_filter": dispatch_run_status_filter,
        "dispatch_run_conclusion_filter": dispatch_run_conclusion_filter,
        "failed_workflow_step_filter": failed_workflow_step_filter,
        "delivery_readiness_status_filter": delivery_readiness_status_filter,
        "readiness_action_filter": readiness_action_filter,
        "offset": offset,
        "limit": limit,
        "total_count": total_count,
        "matched_count": matched_count,
        "visible_count": visible_count,
        "next_offset": source.get("next_offset"),
        "prev_offset": source.get("prev_offset"),
        "decision_counts": decision_counts,
        "latest_record": latest_record,
        "latest_dispatch_audit": latest_dispatch_audit,
        "items": items,
        "notes": notes,
        "recommendations": recommendations,
    }


def _normalize_clean_machine_bootstrap_summary(summary: Dict[str, Any] | None, *, target_channel: str) -> Dict[str, Any]:
    source = _as_dict(summary)
    details = _as_dict(source.get("details"))
    default_status = "blocked" if target_channel == "release" else "warning"
    step_statuses: List[Dict[str, str]] = []
    for item in list(details.get("step_statuses") or []):
        raw = _as_dict(item)
        step_statuses.append({
            "id": str(raw.get("id") or "").strip() or f"step_{len(step_statuses) + 1}",
            "status": _normalize_choice(raw.get("status"), QUALITY_GATE_CHECK_STATUSES, "skipped"),
        })

    return {
        "status": _normalize_choice(source.get("status"), QUALITY_GATE_CHECK_STATUSES, default_status),
        "path": str(source.get("path") or "").strip(),
        "summary": str(source.get("summary") or "").strip(),
        "details": {
            "ok": bool(details.get("ok")),
            "preview": bool(details.get("preview")),
            "step_count": max(int(details.get("step_count") or 0), 0),
            "blocking_issue_count": max(int(details.get("blocking_issue_count") or 0), 0),
            "blocking_issue_codes": _clean_text_list(details.get("blocking_issue_codes")),
            "doctor_report_path": str(details.get("doctor_report_path") or "").strip(),
            "doctor_report_exists": bool(details.get("doctor_report_exists")) or bool(str(details.get("doctor_report_path") or "").strip()),
            "doctor_ok": bool(details.get("doctor_ok")),
            "doctor_summary": str(details.get("doctor_summary") or "").strip(),
            "doctor_check_count": max(int(details.get("doctor_check_count") or 0), 0),
            "doctor_failed_check_count": max(int(details.get("doctor_failed_check_count") or 0), 0),
            "doctor_action_item_count": max(int(details.get("doctor_action_item_count") or 0), 0),
            "doctor_blocking_checks": _clean_text_list(details.get("doctor_blocking_checks")),
            "step_statuses": step_statuses,
        },
    }


def _normalize_release_live_runner_baseline_summary(summary: Dict[str, Any] | None, *, target_channel: str) -> Dict[str, Any]:
    source = _as_dict(summary)
    details = _as_dict(source.get("details"))
    default_status = "blocked" if target_channel == "release" else "warning"
    checks: List[Dict[str, Any]] = []
    for item in list(details.get("checks") or []):
        raw = _as_dict(item)
        checks.append({
            "check_id": str(raw.get("check_id") or "").strip() or f"check_{len(checks) + 1}",
            "label": str(raw.get("label") or raw.get("check_id") or "").strip() or f"Check {len(checks) + 1}",
            "status": _normalize_choice(raw.get("status"), QUALITY_GATE_CHECK_STATUSES, "skipped"),
            "required": bool(raw.get("required", True)),
            "message": str(raw.get("message") or "").strip(),
        })

    return {
        "status": _normalize_choice(source.get("status"), QUALITY_GATE_CHECK_STATUSES, default_status),
        "path": str(source.get("path") or "").strip(),
        "summary": str(source.get("summary") or "").strip(),
        "details": {
            "target_channel": str(details.get("target_channel") or target_channel).strip(),
            "target_environment": str(details.get("target_environment") or "").strip(),
            "report_path": str(details.get("report_path") or "").strip(),
            "runner_profile_path": str(details.get("runner_profile_path") or "").strip(),
            "runner_profile_id": str(details.get("runner_profile_id") or "").strip(),
            "runner_name": str(details.get("runner_name") or "").strip(),
            "runner_os": str(details.get("runner_os") or "").strip(),
            "runner_arch": str(details.get("runner_arch") or "").strip(),
            "declared_runner_labels": _clean_text_list(details.get("declared_runner_labels")),
            "github_actions": bool(details.get("github_actions")),
            "github_workflow": str(details.get("github_workflow") or "").strip(),
            "github_job": str(details.get("github_job") or "").strip(),
            "github_run_id": str(details.get("github_run_id") or "").strip(),
            "github_run_attempt": str(details.get("github_run_attempt") or "").strip(),
            "python_version": str(details.get("python_version") or "").strip(),
            "required_runner_os": str(details.get("required_runner_os") or "").strip(),
            "required_runner_arches": _clean_text_list(details.get("required_runner_arches")),
            "required_runner_labels": _clean_text_list(details.get("required_runner_labels")),
            "allowed_runner_names": _clean_text_list(details.get("allowed_runner_names")),
            "check_count": max(int(details.get("check_count") or len(checks)), 0),
            "passed_check_count": max(int(details.get("passed_check_count") or 0), 0),
            "warning_check_count": max(int(details.get("warning_check_count") or 0), 0),
            "blocked_check_count": max(int(details.get("blocked_check_count") or 0), 0),
            "blocking_checks": _clean_text_list(details.get("blocking_checks")),
            "warning_checks": _clean_text_list(details.get("warning_checks")),
            "checks": checks,
            "recommendations": _clean_text_list(details.get("recommendations")),
            "powershell_executable": str(details.get("powershell_executable") or "").strip(),
            "godot_executable": str(details.get("godot_executable") or "").strip(),
            "browser_executable": str(details.get("browser_executable") or "").strip(),
        },
    }


def _normalize_full_live_validation_summary(summary: Dict[str, Any] | None, *, target_channel: str) -> Dict[str, Any]:
    source = _as_dict(summary)
    details = _as_dict(source.get("details"))
    default_status = "blocked" if target_channel == "release" else "warning"
    step_statuses: List[Dict[str, Any]] = []
    for item in list(details.get("step_statuses") or []):
        raw = _as_dict(item)
        step_statuses.append({
            "id": str(raw.get("id") or "").strip() or f"lane_{len(step_statuses) + 1}",
            "label": str(raw.get("label") or raw.get("id") or "").strip() or f"Lane {len(step_statuses) + 1}",
            "status": _normalize_choice(raw.get("status"), QUALITY_GATE_CHECK_STATUSES, "skipped"),
            "summary": str(raw.get("summary") or "").strip(),
            "artifact_paths": _clean_text_list(raw.get("artifact_paths")),
            "report_path": str(raw.get("report_path") or "").strip(),
            "flow_statuses": _normalize_flow_statuses(raw.get("flow_statuses")),
        })

    lane_artifacts: List[Dict[str, Any]] = []
    raw_lane_artifacts = list(details.get("lane_artifacts") or [])
    if not raw_lane_artifacts:
        raw_lane_artifacts = [
            {
                "lane_id": str(item.get("id") or "").strip(),
                "label": str(item.get("label") or item.get("id") or "").strip(),
                "status": str(item.get("status") or "").strip(),
                "summary": str(item.get("summary") or "").strip(),
                "executed_at": str(details.get("executed_at") or "").strip(),
                "report_path": str(item.get("report_path") or "").strip(),
                "artifact_paths": list(item.get("artifact_paths") or []),
                "build_id": str(details.get("report_release_build_id") or details.get("release_build_id") or "").strip(),
                "version": str(details.get("report_release_version") or details.get("release_version") or "").strip(),
                "channel": str(details.get("report_release_channel") or details.get("release_channel") or "").strip(),
                "release_manifest_path": str(
                    details.get("report_release_manifest_path") or details.get("release_manifest_path") or ""
                ).strip(),
                "release_url": str(details.get("report_release_url") or "").strip(),
                "versioned_release_url": str(details.get("report_versioned_release_url") or "").strip(),
                "release_binding_status": str(details.get("release_binding_status") or "").strip(),
                "release_binding_mismatches": list(details.get("release_binding_mismatches") or []),
                "flow_statuses": _normalize_flow_statuses(item.get("flow_statuses")),
            }
            for item in step_statuses
        ]
    for index, item in enumerate(raw_lane_artifacts, start=1):
        raw = _as_dict(item)
        lane_artifacts.append({
            "lane_id": str(raw.get("lane_id") or raw.get("id") or f"lane_{index}").strip() or f"lane_{index}",
            "label": str(raw.get("label") or raw.get("lane_id") or raw.get("id") or "").strip() or f"Lane {index}",
            "status": _normalize_choice(raw.get("status"), QUALITY_GATE_CHECK_STATUSES, "skipped"),
            "summary": str(raw.get("summary") or "").strip(),
            "executed_at": str(raw.get("executed_at") or details.get("executed_at") or "").strip(),
            "report_path": str(raw.get("report_path") or "").strip(),
            "report_exists": bool(raw.get("report_exists")) or bool(str(raw.get("report_path") or "").strip()),
            "artifact_paths": _clean_text_list(raw.get("artifact_paths")),
            "build_id": str(raw.get("build_id") or details.get("report_release_build_id") or details.get("release_build_id") or "").strip(),
            "version": str(raw.get("version") or details.get("report_release_version") or details.get("release_version") or "").strip(),
            "channel": str(raw.get("channel") or details.get("report_release_channel") or details.get("release_channel") or "").strip(),
            "release_manifest_path": str(
                raw.get("release_manifest_path")
                or details.get("report_release_manifest_path")
                or details.get("release_manifest_path")
                or ""
            ).strip(),
            "release_url": str(raw.get("release_url") or details.get("report_release_url") or "").strip(),
            "versioned_release_url": str(
                raw.get("versioned_release_url") or details.get("report_versioned_release_url") or ""
            ).strip(),
            "release_binding_status": _normalize_choice(
                raw.get("release_binding_status") or details.get("release_binding_status"),
                QUALITY_GATE_CHECK_STATUSES,
                default_status,
            ),
            "release_binding_mismatches": _clean_text_list(
                raw.get("release_binding_mismatches") or details.get("release_binding_mismatches")
            ),
            "expected_build_id": str(raw.get("expected_build_id") or "").strip(),
            "expected_version": str(raw.get("expected_version") or "").strip(),
            "expected_channel": str(raw.get("expected_channel") or "").strip(),
            "expected_release_manifest_path": str(raw.get("expected_release_manifest_path") or "").strip(),
            "flow_statuses": _normalize_flow_statuses(raw.get("flow_statuses")),
        })

    return {
        "status": _normalize_choice(source.get("status"), QUALITY_GATE_CHECK_STATUSES, default_status),
        "path": str(source.get("path") or "").strip(),
        "summary": str(source.get("summary") or "").strip(),
        "details": {
            "ok": bool(details.get("ok")),
            "executed_at": str(details.get("executed_at") or "").strip(),
            "lane_count": max(int(details.get("lane_count") or 0), 0),
            "passed_lane_count": max(int(details.get("passed_lane_count") or 0), 0),
            "warning_lane_count": max(int(details.get("warning_lane_count") or 0), 0),
            "blocked_lane_count": max(int(details.get("blocked_lane_count") or 0), 0),
            "blocking_issue_count": max(int(details.get("blocking_issue_count") or 0), 0),
            "blocking_issue_codes": _clean_text_list(details.get("blocking_issue_codes")),
            "report_release_binding_status": _normalize_choice(details.get("report_release_binding_status"), QUALITY_GATE_CHECK_STATUSES, default_status),
            "report_release_manifest_source": str(details.get("report_release_manifest_source") or "").strip(),
            "report_release_build_id": str(details.get("report_release_build_id") or "").strip(),
            "report_release_version": str(details.get("report_release_version") or "").strip(),
            "report_release_channel": str(details.get("report_release_channel") or "").strip(),
            "report_release_manifest_path": str(details.get("report_release_manifest_path") or "").strip(),
            "report_release_dir": str(details.get("report_release_dir") or "").strip(),
            "report_output_path": str(details.get("report_output_path") or "").strip(),
            "report_release_url": str(details.get("report_release_url") or "").strip(),
            "report_versioned_release_url": str(details.get("report_versioned_release_url") or "").strip(),
            "release_build_id": str(details.get("release_build_id") or "").strip(),
            "release_version": str(details.get("release_version") or "").strip(),
            "release_channel": str(details.get("release_channel") or "").strip(),
            "release_manifest_path": str(details.get("release_manifest_path") or "").strip(),
            "release_binding_status": _normalize_choice(details.get("release_binding_status"), QUALITY_GATE_CHECK_STATUSES, default_status),
            "release_binding_mismatches": _clean_text_list(details.get("release_binding_mismatches")),
            "lane_artifact_count": max(int(details.get("lane_artifact_count") or len(lane_artifacts)), 0),
            "lane_artifacts": lane_artifacts,
            "step_statuses": step_statuses,
        },
    }


def _normalize_release_live_ci_summary(summary: Dict[str, Any] | None) -> Dict[str, Any]:
    source = _as_dict(summary)
    details = _as_dict(source.get("details"))
    runtime_assembly = normalize_release_runtime_assembly_snapshot(
        details.get("runtime_assembly") or source.get("runtime_assembly")
    )
    event_stream = normalize_release_live_event_stream(
        details.get("event_stream") or source.get("event_stream")
    )
    dispatch_audit = normalize_release_live_dispatch_audit(
        details.get("dispatch_audit") or source.get("dispatch_audit")
    )
    invocation_raw = _as_dict(details.get("invocation"))
    ci_gate_raw = _as_dict(details.get("ci_gate"))
    runtime_gates_raw = _as_dict(details.get("runtime_gates"))
    human_signoffs_raw = _as_dict(details.get("human_signoffs"))
    runtime_lanes_raw = _as_dict(details.get("runtime_lanes"))
    workflow_steps_raw = list(details.get("workflow_steps") or [])

    full_live_validation_lanes: List[Dict[str, Any]] = []
    for index, item in enumerate(list(runtime_lanes_raw.get("full_live_validation") or []), start=1):
        raw = _as_dict(item)
        full_live_validation_lanes.append({
            "lane_id": str(raw.get("lane_id") or f"lane_{index}").strip() or f"lane_{index}",
            "label": str(raw.get("label") or raw.get("lane_id") or "").strip() or f"Lane {index}",
            "status": _normalize_choice(raw.get("status"), QUALITY_GATE_CHECK_STATUSES, "skipped"),
            "summary": str(raw.get("summary") or "").strip(),
            "report_path": str(raw.get("report_path") or "").strip(),
            "artifact_paths": _clean_text_list(raw.get("artifact_paths")),
            "flow_statuses": _normalize_flow_statuses(raw.get("flow_statuses")),
        })

    workflow_steps: List[Dict[str, Any]] = []
    for index, item in enumerate(workflow_steps_raw, start=1):
        raw = _as_dict(item)
        workflow_steps.append({
            "step_id": str(raw.get("step_id") or raw.get("id") or f"step_{index}").strip() or f"step_{index}",
            "label": str(raw.get("label") or raw.get("step_id") or "").strip() or f"Step {index}",
            "status": _normalize_choice(raw.get("status"), QUALITY_GATE_CHECK_STATUSES, "skipped"),
            "outcome": str(raw.get("outcome") or "").strip(),
            "always_run": bool(raw.get("always_run")),
            "message": str(raw.get("message") or "").strip(),
        })

    ci_gate_status = _normalize_choice(
        ci_gate_raw.get("status") or source.get("status"),
        QUALITY_GATE_CHECK_STATUSES,
        "warning",
    )

    return {
        "status": ci_gate_status,
        "path": str(source.get("path") or "").strip(),
        "summary": str(source.get("summary") or "").strip(),
        "details": {
            "artifact_dir": str(details.get("artifact_dir") or "").strip(),
            "generated_at": str(details.get("generated_at") or "").strip(),
            "target_channel": str(details.get("target_channel") or "").strip(),
            "target_environment": str(details.get("target_environment") or "").strip(),
            "release_build_id": str(details.get("release_build_id") or "").strip(),
            "release_version": str(details.get("release_version") or "").strip(),
            "release_channel": str(details.get("release_channel") or "").strip(),
            "release_manifest_path": str(details.get("release_manifest_path") or "").strip(),
            "summary_markdown_path": str(details.get("summary_markdown_path") or "").strip(),
            "summary_markdown_exists": bool(details.get("summary_markdown_exists")) or bool(str(details.get("summary_markdown_path") or "").strip()),
            "workflow_step_results_path": str(details.get("workflow_step_results_path") or "").strip(),
            "runtime_assembly": runtime_assembly,
            "event_stream": event_stream,
            "dispatch_audit": dispatch_audit,
            "invocation": {
                "source": str(invocation_raw.get("source") or "").strip(),
                "mode": str(invocation_raw.get("mode") or "").strip(),
                "fail_on_warnings": bool(invocation_raw.get("fail_on_warnings")),
                "providers": _clean_text_list(invocation_raw.get("providers")),
                "approvers": _clean_text_list(invocation_raw.get("approvers")),
                "executed_by": str(invocation_raw.get("executed_by") or "").strip(),
                "note": str(invocation_raw.get("note") or "").strip(),
            },
            "ci_gate": {
                "status": ci_gate_status,
                "should_block": bool(ci_gate_raw.get("should_block")),
                "fail_on_warnings": bool(ci_gate_raw.get("fail_on_warnings")),
                "blocking_checks": _clean_text_list(ci_gate_raw.get("blocking_checks")),
                "warning_checks": _clean_text_list(ci_gate_raw.get("warning_checks")),
                "evaluated_check_count": max(int(ci_gate_raw.get("evaluated_check_count") or 0), 0),
            },
            "runtime_gates": {
                "release_live_runner_baseline_status": _normalize_choice(runtime_gates_raw.get("release_live_runner_baseline_status"), QUALITY_GATE_CHECK_STATUSES, "skipped"),
                "full_live_validation_status": _normalize_choice(runtime_gates_raw.get("full_live_validation_status"), QUALITY_GATE_CHECK_STATUSES, "skipped"),
                "distribution_bundle_status": _normalize_choice(runtime_gates_raw.get("distribution_bundle_status"), QUALITY_GATE_CHECK_STATUSES, "skipped"),
                "distribution_signing_handoff_status": _normalize_choice(runtime_gates_raw.get("distribution_signing_handoff_status"), QUALITY_GATE_CHECK_STATUSES, "skipped"),
                "distribution_publish_handoff_status": _normalize_choice(runtime_gates_raw.get("distribution_publish_handoff_status"), QUALITY_GATE_CHECK_STATUSES, "skipped"),
                "distribution_publish_receipts_status": _normalize_choice(runtime_gates_raw.get("distribution_publish_receipts_status"), QUALITY_GATE_CHECK_STATUSES, "skipped"),
                "identity_handoff_status": _normalize_choice(runtime_gates_raw.get("identity_handoff_status"), QUALITY_GATE_CHECK_STATUSES, "skipped"),
            },
            "runtime_lanes": {
                "full_live_validation": full_live_validation_lanes,
            },
            "workflow_steps": workflow_steps,
            "human_signoffs": {
                "status": _normalize_choice(human_signoffs_raw.get("status"), QUALITY_GATE_CHECK_STATUSES, "skipped"),
                "required_signoffs": _clean_text_list(human_signoffs_raw.get("required_signoffs")),
                "provided_signoffs": _clean_text_list(human_signoffs_raw.get("provided_signoffs")),
                "missing_signoffs": _clean_text_list(human_signoffs_raw.get("missing_signoffs")),
            },
        },
    }


def _normalize_release_artifact_manifest_lane(raw: Dict[str, Any], index: int) -> Dict[str, Any]:
    lane_id = str(raw.get("lane_id") or raw.get("id") or f"lane_{index}").strip() or f"lane_{index}"
    return {
        "lane_id": lane_id,
        "label": str(raw.get("label") or raw.get("lane_id") or raw.get("id") or lane_id).strip() or lane_id,
        "status": _normalize_choice(raw.get("status"), QUALITY_GATE_CHECK_STATUSES, "skipped"),
        "summary": str(raw.get("summary") or "").strip(),
        "report_path": str(raw.get("report_path") or "").strip(),
        "artifact_paths": _clean_text_list(raw.get("artifact_paths")),
        "flow_statuses": _normalize_flow_statuses(raw.get("flow_statuses")),
    }


def _normalize_release_artifact_manifest_readiness(value: Any) -> Dict[str, Any]:
    source = _as_dict(value)
    next_action_ids = _clean_text_list(source.get("next_action_ids"))
    return {
        "status": _normalize_choice(source.get("status"), QUALITY_GATE_CHECK_STATUSES, "warning"),
        "summary": str(source.get("summary") or "").strip(),
        "next_action_count": max(int(source.get("next_action_count") or len(next_action_ids)), 0),
        "next_action_ids": next_action_ids,
        "blocking_checks": _clean_text_list(source.get("blocking_checks")),
        "warning_checks": _clean_text_list(source.get("warning_checks")),
    }


def normalize_release_artifact_manifest(summary: Dict[str, Any] | None) -> Dict[str, Any]:
    source = _as_dict(summary)
    runtime_lanes_raw = _as_dict(source.get("runtime_lanes"))
    full_live_validation = [
        _normalize_release_artifact_manifest_lane(_as_dict(item), index)
        for index, item in enumerate(list(runtime_lanes_raw.get("full_live_validation") or []), start=1)
    ]
    release_summary = normalize_release_summary(source.get("release_summary") or {
        "build_id": source.get("release_build_id"),
        "version": source.get("release_version"),
        "channel": source.get("release_channel") or source.get("target_channel"),
        "release_manifest_path": source.get("release_manifest_path"),
    })
    contract_versions = dict(_as_dict(source.get("contract_versions")))
    contract_versions["release_artifact_manifest"] = RELEASE_ARTIFACT_MANIFEST_SCHEMA_VERSION
    contract_versions["release_summary"] = RELEASE_SUMMARY_SCHEMA_VERSION

    return {
        "schema_version": RELEASE_ARTIFACT_MANIFEST_SCHEMA_VERSION,
        "contract_versions": contract_versions,
        "project_root": str(source.get("project_root") or "").strip(),
        "runtime_root": str(source.get("runtime_root") or "").strip(),
        "target_channel": str(source.get("target_channel") or "").strip(),
        "target_environment": str(source.get("target_environment") or "").strip(),
        "mode": str(source.get("mode") or source.get("ci_mode") or "").strip(),
        "ci_mode": str(source.get("ci_mode") or source.get("mode") or "").strip(),
        "generated_at": str(source.get("generated_at") or "").strip(),
        "synthetic_release_dir": str(source.get("synthetic_release_dir") or "").strip(),
        "release_manifest_path": str(source.get("release_manifest_path") or "").strip(),
        "release_build_id": str(source.get("release_build_id") or release_summary.get("build_id") or "").strip(),
        "release_version": str(source.get("release_version") or release_summary.get("version") or "").strip(),
        "release_channel": str(source.get("release_channel") or release_summary.get("channel") or "").strip(),
        "release_summary": release_summary,
        "runtime_assembly": normalize_release_runtime_assembly_snapshot(source.get("runtime_assembly")),
        "event_stream": normalize_release_live_event_stream(source.get("event_stream")),
        "release_delivery_readiness": normalize_release_delivery_readiness(
            source.get("release_delivery_readiness")
        ),
        "execution_delivery_readiness": _normalize_release_artifact_manifest_readiness(
            source.get("execution_delivery_readiness")
        ),
        "runtime_lanes": {
            "full_live_validation": full_live_validation,
        },
        "generated_files": _clean_text_list(source.get("generated_files")),
    }


def normalize_release_execution_status(summary: Dict[str, Any] | None) -> Dict[str, Any]:
    source = dict(summary or {})
    operation_values = {"dry_run", "canary", "full_rollout", "rollback"}
    rollout_stage_values = {"idle", "dry_run", "canary", "full_rollout", "rolled_back"}
    notes = _clean_text_list(source.get("notes"))
    recommendations = _clean_text_list(source.get("recommendations"))
    operation_filter = _normalize_choice(source.get("operation_filter"), operation_values, "")
    target_channel_filter = str(source.get("target_channel_filter") or "").strip().lower()
    executor_filter = str(source.get("executor_filter") or "").strip()
    offset = max(int(source.get("offset") or 0), 0)
    limit = max(int(source.get("limit") or 20), 1)

    items: List[Dict[str, Any]] = []
    for index, item in enumerate(list(source.get("items") or source.get("executions") or []), start=1):
        raw = _as_dict(item)
        plan_snapshot = normalize_release_promotion_plan(raw.get("plan_snapshot"))
        execution_delivery_readiness = normalize_release_delivery_readiness(
            raw.get("release_delivery_readiness") or plan_snapshot.get("release_delivery_readiness")
        )
        execution_delivery_readiness_next_actions = [
            _normalize_release_delivery_readiness_action(action)
            for action in list(
                raw.get("release_delivery_readiness_next_actions")
                or execution_delivery_readiness.get("next_actions")
                or []
            )
            if isinstance(action, dict)
        ]
        checklist: List[Dict[str, Any]] = []
        for raw_check in list(raw.get("checklist") or []):
            check = _as_dict(raw_check)
            checklist.append({
                "item_id": str(check.get("item_id") or check.get("name") or "").strip() or f"check_{len(checklist) + 1}",
                "label": str(check.get("label") or check.get("item_id") or "").strip() or f"Check {len(checklist) + 1}",
                "status": _normalize_choice(check.get("status"), QUALITY_GATE_CHECK_STATUSES, "skipped"),
                "required": bool(check.get("required", True)),
                "message": str(check.get("message") or check.get("summary") or "").strip(),
                "details": dict(_as_dict(check.get("details"))),
            })
        blocking_checks = _clean_text_list(raw.get("blocking_checks")) or [
            check["item_id"] for check in checklist if check["status"] == "blocked"
        ]
        warning_checks = _clean_text_list(raw.get("warning_checks")) or [
            check["item_id"] for check in checklist if check["status"] == "warning"
        ]
        items.append({
            "execution_id": str(raw.get("execution_id") or f"release_execution_{index}").strip() or f"release_execution_{index}",
            "recorded_at": str(raw.get("recorded_at") or "").strip(),
            "operation": _normalize_choice(raw.get("operation"), operation_values, "dry_run"),
            "target_channel": str(raw.get("target_channel") or plan_snapshot.get("target_channel") or "").strip() or "staging",
            "target_environment": str(raw.get("target_environment") or plan_snapshot.get("target_environment") or "").strip() or "staging",
            "promotion_target_label": str(raw.get("promotion_target_label") or plan_snapshot.get("promotion_target_label") or "").strip(),
            "execution_status": _normalize_choice(raw.get("execution_status"), QUALITY_GATE_CHECK_STATUSES, "skipped"),
            "should_block": bool(raw.get("should_block")),
            "executed_by": str(raw.get("executed_by") or "").strip(),
            "note": str(raw.get("note") or "").strip(),
            "rollout_stage": _normalize_choice(raw.get("rollout_stage"), rollout_stage_values, "idle"),
            "rollout_percentage": max(min(int(raw.get("rollout_percentage") or 0), 100), 0),
            "channel_binding_changed": bool(raw.get("channel_binding_changed")),
            "release_manifest_path": str(raw.get("release_manifest_path") or plan_snapshot.get("release_manifest_path") or "").strip(),
            "release_build_id": str(raw.get("release_build_id") or plan_snapshot.get("release_candidate_checklist", {}).get("release_summary", {}).get("build_id") or "").strip(),
            "release_version": str(raw.get("release_version") or plan_snapshot.get("release_candidate_checklist", {}).get("release_summary", {}).get("version") or "").strip(),
            "release_channel": str(raw.get("release_channel") or plan_snapshot.get("release_candidate_checklist", {}).get("release_summary", {}).get("channel") or "").strip(),
            "public_url": str(raw.get("public_url") or "").strip(),
            "versioned_release_url": str(raw.get("versioned_release_url") or plan_snapshot.get("release_candidate_checklist", {}).get("release_summary", {}).get("versioned_release_url") or "").strip(),
            "rollback_url": str(raw.get("rollback_url") or "").strip(),
            "promotion_record_id": str(raw.get("promotion_record_id") or "").strip(),
            "promotion_decision": str(raw.get("promotion_decision") or "").strip(),
            "promotion_executor": str(raw.get("promotion_executor") or "").strip(),
            "promotion_recorded_at": str(raw.get("promotion_recorded_at") or "").strip(),
            "release_delivery_readiness_status": _normalize_choice(
                raw.get("release_delivery_readiness_status") or execution_delivery_readiness.get("status"),
                QUALITY_GATE_CHECK_STATUSES,
                "warning",
            ),
            "release_delivery_readiness_summary": str(
                raw.get("release_delivery_readiness_summary")
                or execution_delivery_readiness.get("summary")
                or ""
            ).strip(),
            "release_delivery_readiness_next_actions": execution_delivery_readiness_next_actions,
            "release_delivery_readiness_next_action_count": int(
                raw.get("release_delivery_readiness_next_action_count")
                or len(execution_delivery_readiness_next_actions)
            ),
            "release_delivery_readiness_blocking_checks": _clean_text_list(
                raw.get("release_delivery_readiness_blocking_checks")
                or execution_delivery_readiness.get("blocking_checks")
            ),
            "release_delivery_readiness_warning_checks": _clean_text_list(
                raw.get("release_delivery_readiness_warning_checks")
                or execution_delivery_readiness.get("warning_checks")
            ),
            "previous_public_url": str(raw.get("previous_public_url") or "").strip(),
            "authorization": _normalize_release_authorization(raw.get("authorization")),
            "request_auth": _normalize_release_request_auth(raw.get("request_auth")),
            "checklist": checklist,
            "blocking_checks": blocking_checks,
            "warning_checks": warning_checks,
            "plan_snapshot": plan_snapshot,
        })

    channel_entries: List[Dict[str, Any]] = []
    for index, item in enumerate(list(source.get("channel_entries") or source.get("channels") or []), start=1):
        raw = _as_dict(item)
        channel_entries.append({
            "channel_id": str(raw.get("channel_id") or raw.get("target_channel") or f"channel_{index}").strip() or f"channel_{index}",
            "target_environment": str(raw.get("target_environment") or "").strip() or "staging",
            "binding_status": _normalize_choice(raw.get("binding_status"), QUALITY_GATE_CHECK_STATUSES, "skipped"),
            "rollout_stage": _normalize_choice(raw.get("rollout_stage"), rollout_stage_values, "idle"),
            "rollout_percentage": max(min(int(raw.get("rollout_percentage") or 0), 100), 0),
            "active_release_manifest_path": str(raw.get("active_release_manifest_path") or "").strip(),
            "active_build_id": str(raw.get("active_build_id") or "").strip(),
            "active_version": str(raw.get("active_version") or "").strip(),
            "active_release_channel": str(raw.get("active_release_channel") or "").strip(),
            "active_public_url": str(raw.get("active_public_url") or "").strip(),
            "active_versioned_url": str(raw.get("active_versioned_url") or "").strip(),
            "rollback_public_url": str(raw.get("rollback_public_url") or "").strip(),
            "previous_public_url": str(raw.get("previous_public_url") or "").strip(),
            "last_execution_id": str(raw.get("last_execution_id") or "").strip(),
            "updated_at": str(raw.get("updated_at") or "").strip(),
            "executed_by": str(raw.get("executed_by") or "").strip(),
            "notes": _clean_text_list(raw.get("notes")),
        })

    operation_counts: Dict[str, int] = {}
    for item in items:
        operation = str(item.get("operation") or "dry_run")
        operation_counts[operation] = operation_counts.get(operation, 0) + 1

    latest_execution = items[0] if items else {}
    latest_status = str(latest_execution.get("execution_status") or "").strip()
    if not latest_status and channel_entries:
        latest_status = str(channel_entries[0].get("binding_status") or "skipped").strip()
    latest_status = latest_status or "skipped"
    bootstrap_target_channel = (
        target_channel_filter
        or str(latest_execution.get("target_channel") or "").strip().lower()
        or str((channel_entries[0] if channel_entries else {}).get("channel_id") or "").strip().lower()
        or "staging"
    )
    clean_machine_bootstrap = _normalize_clean_machine_bootstrap_summary(
        source.get("clean_machine_bootstrap"),
        target_channel=bootstrap_target_channel,
    )
    release_live_runner_baseline = _normalize_release_live_runner_baseline_summary(
        source.get("release_live_runner_baseline"),
        target_channel=bootstrap_target_channel,
    )
    full_live_validation = _normalize_full_live_validation_summary(
        source.get("full_live_validation"),
        target_channel=bootstrap_target_channel,
    )
    release_live_ci_summary = _normalize_release_live_ci_summary(source.get("release_live_ci_summary"))
    runtime_assembly_snapshot = normalize_release_runtime_assembly_snapshot(
        source.get("runtime_assembly_snapshot")
        or release_live_ci_summary.get("details", {}).get("runtime_assembly")
    )
    latest_review_bundle = dict(latest_execution.get("plan_snapshot", {}).get("review_bundle") or {})
    review_followup_actions = _normalize_review_followup_actions(
        source.get("review_followup_actions") or latest_review_bundle.get("review_followup_actions")
    )
    request_auth_posture = _normalize_release_request_auth_posture(source.get("request_auth_posture"))
    request_auth_rotation_audit = _normalize_release_request_auth_rotation_audit(source.get("request_auth_rotation_audit"))
    request_auth_identity_audit = _normalize_release_request_auth_identity_audit(source.get("request_auth_identity_audit"))
    release_distribution_bundle = _normalize_release_distribution_bundle(source.get("release_distribution_bundle"))
    release_delivery_readiness = normalize_release_delivery_readiness(source.get("release_delivery_readiness"))

    contract_versions = dict(_as_dict(source.get("contract_versions")))
    contract_versions["release_execution_status"] = RELEASE_EXECUTION_STATUS_SCHEMA_VERSION
    if items:
        contract_versions["release_promotion_plan"] = items[0]["plan_snapshot"].get("schema_version", "")
        contract_versions["release_review_bundle"] = latest_review_bundle.get("schema_version", "")

    return {
        "schema_version": RELEASE_EXECUTION_STATUS_SCHEMA_VERSION,
        "contract_versions": contract_versions,
        "project_root": str(source.get("project_root") or "").strip(),
        "runtime_root": str(source.get("runtime_root") or "").strip(),
        "status_path": str(source.get("status_path") or "").strip(),
        "channels_path": str(source.get("channels_path") or "").strip(),
        "history_path": str(source.get("history_path") or "").strip(),
        "status_exists": bool(source.get("status_exists")),
        "channels_exist": bool(source.get("channels_exist")),
        "operation_filter": operation_filter,
        "target_channel_filter": target_channel_filter,
        "executor_filter": executor_filter,
        "offset": offset,
        "limit": limit,
        "status": latest_status,
        "should_block": bool(latest_execution.get("should_block")),
        "execution_count": int(source.get("execution_count") or len(items)),
        "matched_execution_count": int(source.get("matched_execution_count") or len(items)),
        "visible_execution_count": int(source.get("visible_execution_count") or len(items)),
        "channel_count": int(source.get("channel_count") or len(channel_entries)),
        "active_channel_count": int(source.get("active_channel_count") or sum(1 for item in channel_entries if item["active_build_id"])),
        "next_offset": source.get("next_offset"),
        "prev_offset": source.get("prev_offset"),
        "operation_counts": operation_counts,
        "clean_machine_bootstrap": clean_machine_bootstrap,
        "release_live_runner_baseline": release_live_runner_baseline,
        "full_live_validation": full_live_validation,
        "release_live_ci_summary": release_live_ci_summary,
        "runtime_assembly_snapshot": runtime_assembly_snapshot,
        "review_followup_actions": review_followup_actions,
        "review_followup_action_count": int(source.get("review_followup_action_count") or len(review_followup_actions)),
        "request_auth_posture": request_auth_posture,
        "request_auth_rotation_audit": request_auth_rotation_audit,
        "request_auth_identity_audit": request_auth_identity_audit,
        "release_distribution_bundle": release_distribution_bundle,
        "release_delivery_readiness": release_delivery_readiness,
        "latest_execution": latest_execution,
        "items": items,
        "channel_entries": channel_entries,
        "notes": notes,
        "recommendations": recommendations,
    }


def normalize_release_distribution_bundle(summary: Dict[str, Any] | None) -> Dict[str, Any]:
    return _normalize_release_distribution_bundle(summary)


def normalize_performance_summary(summary: Dict[str, Any] | None) -> Dict[str, Any]:
    source = dict(summary or {})
    issues = _clean_text_list(source.get("issues"))
    warnings = _clean_text_list(source.get("warnings"))
    notes = _clean_text_list(source.get("notes"))

    checks: List[Dict[str, Any]] = []
    for item in list(source.get("checks") or []):
        raw = _as_dict(item)
        checks.append({
            **raw,
            "name": str(raw.get("name") or "").strip() or "unnamed_check",
            "status": _normalize_choice(raw.get("status"), QUALITY_GATE_CHECK_STATUSES, "skipped"),
            "message": str(raw.get("message") or "").strip(),
        })

    baselines: List[Dict[str, Any]] = []
    for item in list(source.get("baselines") or []):
        raw = _as_dict(item)
        baselines.append({
            "scene_path": str(raw.get("scene_path") or "").strip(),
            "baseline_path": str(raw.get("baseline_path") or "").strip(),
            "profile_path": str(raw.get("profile_path") or "").strip(),
        })

    metrics = dict(_as_dict(source.get("metrics")))
    budgets = dict(_as_dict(source.get("budgets")))

    frame_breakdown: List[Dict[str, Any]] = []
    for item in list(source.get("frame_breakdown") or []):
        raw = _as_dict(item)
        frame_breakdown.append({
            "stage": str(raw.get("stage") or "").strip() or "unknown_stage",
            "ms": round(float(raw.get("ms") or 0.0), 4),
            "budget_ms": round(float(raw.get("budget_ms") or 0.0), 4) if raw.get("budget_ms") not in (None, "") else None,
        })

    memory_trend_raw = _as_dict(source.get("memory_trend"))
    memory_trend = {
        "sample_count": int(memory_trend_raw.get("sample_count") or 0),
        "min_mb": round(float(memory_trend_raw.get("min_mb") or 0.0), 4),
        "max_mb": round(float(memory_trend_raw.get("max_mb") or 0.0), 4),
        "avg_mb": round(float(memory_trend_raw.get("avg_mb") or 0.0), 4),
        "growth_mb": round(float(memory_trend_raw.get("growth_mb") or 0.0), 4),
        "trend_status": str(memory_trend_raw.get("trend_status") or "").strip() or "stable",
    }
    memory_regression = dict(_as_dict(source.get("memory_regression")))
    screenshot_compare = dict(_as_dict(source.get("screenshot_compare")))

    return {
        "schema_version": PERFORMANCE_SUMMARY_SCHEMA_VERSION,
        "passed": bool(source.get("passed")),
        "scene_path": str(source.get("scene_path") or "").strip(),
        "baseline_path": str(source.get("baseline_path") or "").strip(),
        "profile_path": str(source.get("profile_path") or "").strip(),
        "issues": issues,
        "warnings": warnings,
        "notes": notes,
        "checks": checks,
        "metrics": metrics,
        "budgets": budgets,
        "frame_breakdown": frame_breakdown,
        "memory_trend": memory_trend,
        "memory_regression": memory_regression,
        "screenshot_compare": screenshot_compare,
        "baselines": baselines,
    }


def normalize_presentation_profile(summary: Dict[str, Any] | None) -> Dict[str, Any]:
    source = dict(summary or {})
    presentation_type = _normalize_choice(source.get("presentation_type"), PRESENTATION_TYPES, "animation")
    entries: List[Dict[str, Any]] = []
    for item in list(source.get("entries") or []):
        raw = _as_dict(item)
        normalized = {key: value for key, value in raw.items() if value not in (None, "", [], {})}
        normalized["profile_id"] = str(raw.get("profile_id") or "").strip()
        normalized["presentation_type"] = _normalize_choice(
            raw.get("presentation_type") or presentation_type,
            PRESENTATION_TYPES,
            presentation_type,
        )
        normalized["generation_targets"] = _clean_text_list(raw.get("generation_targets"))
        normalized["acceptance_checks"] = _clean_text_list(raw.get("acceptance_checks"))
        entries.append(normalized)

    generated_paths = _clean_text_list(source.get("generated_paths"))
    return {
        "schema_version": PRESENTATION_PROFILE_SCHEMA_VERSION,
        "presentation_type": presentation_type,
        "manifest_path": str(source.get("manifest_path") or "").strip(),
        "entry_count": int(source.get("entry_count") or len(entries)),
        "generated_path_count": int(source.get("generated_path_count") or len(generated_paths)),
        "generated_paths": generated_paths,
        "entries": entries,
    }


def normalize_liveops_profile(summary: Dict[str, Any] | None) -> Dict[str, Any]:
    source = dict(summary or {})
    liveops_type = _normalize_choice(source.get("liveops_type"), LIVEOPS_TYPES, "remote_config")
    issues = _clean_text_list(source.get("issues"))
    warnings = _clean_text_list(source.get("warnings"))
    notes = _clean_text_list(source.get("notes"))

    entries: List[Dict[str, Any]] = []
    for item in list(source.get("entries") or []):
        raw = _as_dict(item)
        normalized = {key: value for key, value in raw.items() if value not in (None, "", [], {})}
        normalized["liveops_type"] = _normalize_choice(
            raw.get("liveops_type") or liveops_type,
            LIVEOPS_TYPES,
            liveops_type,
        )
        if normalized["liveops_type"] == "remote_config":
            normalized["config_key"] = str(raw.get("config_key") or raw.get("entry_id") or "").strip()
            normalized["value_type"] = _normalize_choice(raw.get("value_type"), LIVEOPS_CONFIG_VALUE_TYPES, "string")
            normalized["owner"] = str(raw.get("owner") or "").strip()
            normalized["enabled"] = bool(raw.get("enabled"))
            normalized["requires_restart"] = bool(raw.get("requires_restart"))
            normalized["rollout_strategy"] = _normalize_choice(
                raw.get("rollout_strategy"),
                LIVEOPS_ROLLOUT_STRATEGIES,
                "global",
            )
            normalized["rollout_percentage"] = round(float(raw.get("rollout_percentage") or 0.0), 2)
            normalized["environments"] = [
                item
                for item in _clean_text_list(raw.get("environments"))
                if item in LIVEOPS_ENVIRONMENTS
            ]
            normalized["audience_segments"] = _clean_text_list(raw.get("audience_segments"))
            normalized["acceptance_checks"] = _clean_text_list(raw.get("acceptance_checks"))
            normalized["tags"] = _clean_text_list(raw.get("tags"))
            normalized["notes"] = str(raw.get("notes") or "").strip()
            normalized["default_value"] = raw.get("default_value")
        else:
            normalized["experiment_id"] = str(raw.get("experiment_id") or raw.get("entry_id") or "").strip()
            normalized["status"] = _normalize_choice(
                raw.get("status"),
                LIVEOPS_EXPERIMENT_STATUSES,
                "draft",
            )
            normalized["hypothesis"] = str(raw.get("hypothesis") or "").strip()
            normalized["owner"] = str(raw.get("owner") or "").strip()
            normalized["rollout_percentage"] = round(float(raw.get("rollout_percentage") or 0.0), 2)
            normalized["rollback_rule"] = str(raw.get("rollback_rule") or "").strip()
            normalized["target_metrics"] = _clean_text_list(raw.get("target_metrics"))
            normalized["audience_segments"] = _clean_text_list(raw.get("audience_segments"))
            normalized["acceptance_checks"] = _clean_text_list(raw.get("acceptance_checks"))
            normalized["notes"] = str(raw.get("notes") or "").strip()
            variants: List[Dict[str, Any]] = []
            for variant in list(raw.get("variants") or []):
                variant_raw = _as_dict(variant)
                variants.append({
                    "variant_id": str(variant_raw.get("variant_id") or "").strip(),
                    "weight": round(float(variant_raw.get("weight") or 0.0), 2),
                    "config_overrides": dict(_as_dict(variant_raw.get("config_overrides"))),
                })
            normalized["variants"] = variants
        entries.append(normalized)

    return {
        "schema_version": LIVEOPS_PROFILE_SCHEMA_VERSION,
        "liveops_type": liveops_type,
        "manifest_path": str(source.get("manifest_path") or "").strip(),
        "entry_count": int(source.get("entry_count") or len(entries)),
        "active_entry_count": int(source.get("active_entry_count") or 0),
        "rollout_count": int(source.get("rollout_count") or 0),
        "variant_count": int(source.get("variant_count") or 0),
        "target_metric_count": int(source.get("target_metric_count") or 0),
        "entries": entries,
        "issues": issues,
        "warnings": warnings,
        "notes": notes,
    }


def normalize_game_creation_profile(summary: Dict[str, Any] | None) -> Dict[str, Any]:
    source = dict(summary or {})
    blocking_checks = _clean_text_list(source.get("blocking_checks") or source.get("issues"))
    warning_checks = _clean_text_list(source.get("warning_checks") or source.get("warnings"))
    status = _normalize_choice(source.get("status"), QUALITY_GATE_CHECK_STATUSES, "")
    if not status:
        status = "blocked" if blocking_checks else "warning" if warning_checks else "passed"

    contract_versions = dict(_as_dict(source.get("contract_versions")))
    contract_versions["game_creation_profile"] = GAME_CREATION_PROFILE_SCHEMA_VERSION

    generated_files = _clean_text_list(source.get("generated_files"))
    skipped_files = _clean_text_list(source.get("skipped_files"))
    layout_checks = list(source.get("layout_checks") or [])
    layout_blocking_checks = _clean_text_list(source.get("layout_blocking_checks"))
    governance_enforcement = dict(_as_dict(source.get("governance_enforcement")))
    governance_admission = dict(_as_dict(source.get("governance_admission") or governance_enforcement.get("admission")))
    governance_blocking_checks = _clean_text_list(
        source.get("governance_blocking_checks")
        or governance_enforcement.get("blocking_checks")
        or governance_admission.get("blocked_checks")
    )
    artifact_paths = _clean_text_list(source.get("artifact_paths")) or generated_files
    title = str(source.get("title") or "").strip() or "Untitled Game"
    template_id = str(source.get("template_id") or source.get("genre") or "platformer_2d").strip().lower()

    return {
        "schema_version": GAME_CREATION_PROFILE_SCHEMA_VERSION,
        "contract_versions": contract_versions,
        "game_id": str(source.get("game_id") or "").strip(),
        "title": title,
        "genre": str(source.get("genre") or template_id).strip().lower() or "platformer_2d",
        "template_id": template_id or "platformer_2d",
        "target_platforms": _clean_text_list(source.get("target_platforms")) or ["desktop"],
        "features": _clean_text_list(source.get("features")),
        "scene_plan": list(source.get("scene_plan") or []),
        "input_map": dict(_as_dict(source.get("input_map"))),
        "asset_plan": list(source.get("asset_plan") or []),
        "module_plan": list(source.get("module_plan") or []),
        "skill_binding_plan": list(source.get("skill_binding_plan") or []),
        "block_diagram": str(source.get("block_diagram") or "").strip(),
        "godot_response_map": list(source.get("godot_response_map") or []),
        "data_tables": list(source.get("data_tables") or []),
        "playtest_plan": _clean_text_list(source.get("playtest_plan")),
        "input_replay_plan": list(source.get("input_replay_plan") or []),
        "golden_screenshot_plan": dict(_as_dict(source.get("golden_screenshot_plan"))),
        "template_migration_plan": dict(_as_dict(source.get("template_migration_plan"))),
        "export_plan": dict(_as_dict(source.get("export_plan"))),
        "acceptance_criteria": _clean_text_list(source.get("acceptance_criteria")),
        "artifact_paths": artifact_paths,
        "generated_files": generated_files,
        "skipped_files": skipped_files,
        "layout_checks": layout_checks,
        "layout_check_count": int(source.get("layout_check_count") or len(layout_checks)),
        "layout_passed": bool(source.get("layout_passed", not layout_blocking_checks)),
        "layout_blocking_checks": layout_blocking_checks,
        "governance_enforcement": governance_enforcement,
        "governance_admission": governance_admission,
        "governance_passed": bool(source.get("governance_passed", not governance_blocking_checks)),
        "governance_blocking_checks": governance_blocking_checks,
        "blocking_checks": blocking_checks,
        "warning_checks": warning_checks,
        "status": status,
        "ready": status == "passed",
        "should_block": status == "blocked",
        "message": str(source.get("message") or "").strip(),
        "manifest_path": str(source.get("manifest_path") or "").strip(),
        "project_root": str(source.get("project_root") or "").strip(),
    }


def normalize_game_creation_template_migration(summary: Dict[str, Any] | None) -> Dict[str, Any]:
    source = dict(summary or {})
    blocking_checks = _clean_text_list(source.get("blocking_checks") or source.get("issues"))
    warning_checks = _clean_text_list(source.get("warning_checks") or source.get("warnings"))
    status = _normalize_choice(source.get("status"), QUALITY_GATE_CHECK_STATUSES, "")
    if not status:
        status = "blocked" if blocking_checks else "warning" if warning_checks else "passed"

    contract_versions = dict(_as_dict(source.get("contract_versions")))
    contract_versions["game_creation_template_migration"] = GAME_CREATION_TEMPLATE_MIGRATION_SCHEMA_VERSION

    return {
        "schema_version": GAME_CREATION_TEMPLATE_MIGRATION_SCHEMA_VERSION,
        "contract_versions": contract_versions,
        "project_root": str(source.get("project_root") or "").strip(),
        "manifest_path": str(source.get("manifest_path") or "").strip(),
        "manifest_exists": bool(source.get("manifest_exists")),
        "report_path": str(source.get("report_path") or "").strip(),
        "from_template_id": str(source.get("from_template_id") or "").strip().lower(),
        "to_template_id": str(source.get("to_template_id") or "").strip().lower(),
        "strategy": str(source.get("strategy") or "plan_only").strip() or "plan_only",
        "compatibility_checks": list(source.get("compatibility_checks") or []),
        "migration_steps": list(source.get("migration_steps") or []),
        "file_operations": list(source.get("file_operations") or []),
        "data_migrations": list(source.get("data_migrations") or []),
        "validation_plan": list(source.get("validation_plan") or []),
        "rollback_plan": list(source.get("rollback_plan") or []),
        "skill_constraints": list(source.get("skill_constraints") or []),
        "blocking_checks": blocking_checks,
        "warning_checks": warning_checks,
        "status": status,
        "ready": status == "passed",
        "should_block": status == "blocked",
        "message": str(source.get("message") or "").strip(),
        "generated_at": str(source.get("generated_at") or "").strip(),
    }


def normalize_scene_graph_audit(summary: Dict[str, Any] | None) -> Dict[str, Any]:
    source = dict(summary or {})
    blocking_checks = _clean_text_list(source.get("blocking_checks") or source.get("issues"))
    warning_checks = _clean_text_list(source.get("warning_checks") or source.get("warnings"))
    status = _normalize_choice(source.get("status"), QUALITY_GATE_CHECK_STATUSES, "")
    if not status:
        status = "blocked" if blocking_checks else "warning" if warning_checks else "passed"

    contract_versions = dict(_as_dict(source.get("contract_versions")))
    contract_versions["scene_graph_audit"] = SCENE_GRAPH_AUDIT_SCHEMA_VERSION

    scene_graph = list(source.get("scene_graph") or [])
    module_checks = list(source.get("module_checks") or [])
    response_checks = list(source.get("response_checks") or [])
    live_snapshot = dict(_as_dict(source.get("live_snapshot")))

    return {
        "schema_version": SCENE_GRAPH_AUDIT_SCHEMA_VERSION,
        "contract_versions": contract_versions,
        "project_root": str(source.get("project_root") or "").strip(),
        "manifest_path": str(source.get("manifest_path") or "").strip(),
        "manifest_exists": bool(source.get("manifest_exists")),
        "generated_at": str(source.get("generated_at") or "").strip(),
        "scene_graph": scene_graph,
        "scene_count": int(source.get("scene_count") or len(scene_graph)),
        "node_count": int(source.get("node_count") or 0),
        "live_snapshot_used": bool(source.get("live_snapshot_used") or live_snapshot),
        "live_snapshot": live_snapshot,
        "live_snapshot_source": str(source.get("live_snapshot_source") or live_snapshot.get("source") or "").strip(),
        "live_snapshot_scene_path": str(source.get("live_snapshot_scene_path") or live_snapshot.get("scene_path") or "").strip(),
        "live_snapshot_node_count": int(source.get("live_snapshot_node_count") or live_snapshot.get("node_count") or 0),
        "expected_module_count": int(source.get("expected_module_count") or len(module_checks)),
        "module_checks": module_checks,
        "response_checks": response_checks,
        "missing_scenes": _clean_text_list(source.get("missing_scenes")),
        "missing_scripts": _clean_text_list(source.get("missing_scripts")),
        "missing_nodes": _clean_text_list(source.get("missing_nodes")),
        "missing_signals": _clean_text_list(source.get("missing_signals")),
        "blocking_checks": blocking_checks,
        "warning_checks": warning_checks,
        "status": status,
        "passed": status == "passed",
        "ready": status == "passed",
        "should_block": status == "blocked",
        "message": str(source.get("message") or "").strip(),
    }


def normalize_scene_graph_snapshot(summary: Dict[str, Any] | None) -> Dict[str, Any]:
    source = dict(summary or {})
    nodes = list(source.get("nodes") or [])
    contract_versions = dict(_as_dict(source.get("contract_versions")))
    contract_versions["scene_graph_snapshot"] = SCENE_GRAPH_SNAPSHOT_SCHEMA_VERSION
    return {
        "schema_version": SCENE_GRAPH_SNAPSHOT_SCHEMA_VERSION,
        "contract_versions": contract_versions,
        "project_path": str(source.get("project_path") or "").strip(),
        "scene_path": str(source.get("scene_path") or source.get("current_scene") or "").strip(),
        "root_node": str(source.get("root_node") or source.get("edited_scene_root_name") or "").strip(),
        "captured_at": str(source.get("captured_at") or "").strip(),
        "source": str(source.get("source") or "godot_plugin").strip(),
        "nodes": nodes,
        "node_count": int(source.get("node_count") or len(nodes)),
        "node_types": _clean_text_list(source.get("node_types")) or sorted({
            str(item.get("type") or "").strip()
            for item in nodes
            if isinstance(item, dict) and str(item.get("type") or "").strip()
        }),
        "node_names": _clean_text_list(source.get("node_names")) or sorted({
            str(item.get("name") or "").strip()
            for item in nodes
            if isinstance(item, dict) and str(item.get("name") or "").strip()
        }),
        "script_paths": _clean_text_list(source.get("script_paths")) or sorted({
            str(item.get("script_path") or "").strip().removeprefix("res://")
            for item in nodes
            if isinstance(item, dict) and str(item.get("script_path") or "").strip()
        }),
        "instance_paths": _clean_text_list(source.get("instance_paths")) or sorted({
            str(item.get("instance_path") or "").strip().removeprefix("res://")
            for item in nodes
            if isinstance(item, dict) and str(item.get("instance_path") or "").strip()
        }),
    }


def normalize_game_creation_review(summary: Dict[str, Any] | None) -> Dict[str, Any]:
    source = dict(summary or {})
    blocking_checks = _clean_text_list(source.get("blocking_checks") or source.get("issues"))
    warning_checks = _clean_text_list(source.get("warning_checks") or source.get("warnings"))
    status = _normalize_choice(source.get("status"), QUALITY_GATE_CHECK_STATUSES, "")
    if not status:
        status = "blocked" if blocking_checks else "warning" if warning_checks else "passed"

    contract_versions = dict(_as_dict(source.get("contract_versions")))
    contract_versions["game_creation_review"] = GAME_CREATION_REVIEW_SCHEMA_VERSION

    acceptance_checklist = list(source.get("acceptance_checklist") or [])
    module_review = list(source.get("module_review") or [])
    data_table_review = list(source.get("data_table_review") or [])
    audit_summary = dict(_as_dict(source.get("audit_summary")))
    ready_for_acceptance = status == "passed" and all(
        str(item.get("status") or "").strip().lower() == "ready"
        for item in acceptance_checklist
    )

    return {
        "schema_version": GAME_CREATION_REVIEW_SCHEMA_VERSION,
        "contract_versions": contract_versions,
        "project_root": str(source.get("project_root") or "").strip(),
        "manifest_path": str(source.get("manifest_path") or "").strip(),
        "generated_at": str(source.get("generated_at") or "").strip(),
        "game_id": str(source.get("game_id") or "").strip(),
        "title": str(source.get("title") or "").strip(),
        "template_id": str(source.get("template_id") or "").strip(),
        "review_round": str(source.get("review_round") or "").strip() or "generated_playable_review",
        "acceptance_checklist": acceptance_checklist,
        "acceptance_count": int(source.get("acceptance_count") or len(acceptance_checklist)),
        "ready_acceptance_count": int(
            source.get("ready_acceptance_count")
            or sum(1 for item in acceptance_checklist if str(item.get("status") or "") == "ready")
        ),
        "module_review": module_review,
        "module_count": int(source.get("module_count") or len(module_review)),
        "passed_module_count": int(
            source.get("passed_module_count")
            or sum(1 for item in module_review if str(item.get("status") or "") == "passed")
        ),
        "data_table_review": data_table_review,
        "data_table_count": int(source.get("data_table_count") or len(data_table_review)),
        "passed_data_table_count": int(
            source.get("passed_data_table_count")
            or sum(1 for item in data_table_review if str(item.get("status") or "") == "passed")
        ),
        "audit_summary": audit_summary,
        "artifact_paths": _clean_text_list(source.get("artifact_paths")),
        "blocking_checks": blocking_checks,
        "warning_checks": warning_checks,
        "status": status,
        "ready_for_acceptance": ready_for_acceptance,
        "passed": ready_for_acceptance,
        "should_block": status == "blocked",
        "message": str(source.get("message") or "").strip(),
    }


def normalize_game_creation_replay(summary: Dict[str, Any] | None) -> Dict[str, Any]:
    source = dict(summary or {})
    blocking_checks = _clean_text_list(source.get("blocking_checks") or source.get("issues"))
    warning_checks = _clean_text_list(source.get("warning_checks") or source.get("warnings"))
    status = _normalize_choice(source.get("status"), QUALITY_GATE_CHECK_STATUSES, "")
    if not status:
        status = "blocked" if blocking_checks else "warning" if warning_checks else "passed"

    contract_versions = dict(_as_dict(source.get("contract_versions")))
    contract_versions["game_creation_replay"] = GAME_CREATION_REPLAY_SCHEMA_VERSION
    replay_steps = list(source.get("replay_steps") or [])
    action_checks = list(source.get("action_checks") or [])
    node_checks = list(source.get("node_checks") or [])
    screenshot_capture_mode = str(source.get("screenshot_capture_mode") or "").strip()
    viewport_baseline_status = str(source.get("viewport_baseline_status") or "").strip()
    if not viewport_baseline_status:
        if bool(source.get("viewport_baseline_ready")):
            viewport_baseline_status = "passed"
        elif source.get("runtime_capture_path"):
            viewport_baseline_status = "unknown"
        else:
            viewport_baseline_status = "not_applicable"

    return {
        "schema_version": GAME_CREATION_REPLAY_SCHEMA_VERSION,
        "contract_versions": contract_versions,
        "project_root": str(source.get("project_root") or "").strip(),
        "manifest_path": str(source.get("manifest_path") or "").strip(),
        "input_replay_path": str(source.get("input_replay_path") or "").strip(),
        "report_path": str(source.get("report_path") or "").strip(),
        "script_path": str(source.get("script_path") or "").strip(),
        "generated_at": str(source.get("generated_at") or "").strip(),
        "template_id": str(source.get("template_id") or "").strip(),
        "scene_path": str(source.get("scene_path") or "").strip(),
        "runtime_capture_path": str(source.get("runtime_capture_path") or "").strip(),
        "baseline_path": str(source.get("baseline_path") or "").strip(),
        "baseline_source_path": str(source.get("baseline_source_path") or "").strip(),
        "baseline_exists": bool(source.get("baseline_exists")),
        "baseline_promoted": bool(source.get("baseline_promoted")),
        "baseline_promoted_at": str(source.get("baseline_promoted_at") or "").strip(),
        "max_diff_ratio": float(source.get("max_diff_ratio") or 0.0),
        "replay_steps": replay_steps,
        "replay_step_count": int(source.get("replay_step_count") or len(replay_steps)),
        "action_checks": action_checks,
        "passed_action_count": int(
            source.get("passed_action_count")
            or sum(1 for item in action_checks if str(item.get("status") or "") == "passed")
        ),
        "node_checks": node_checks,
        "passed_node_count": int(
            source.get("passed_node_count")
            or sum(1 for item in node_checks if str(item.get("status") or "") == "passed")
        ),
        "execution_mode": str(source.get("execution_mode") or "headless_script").strip(),
        "replay_render_mode": str(source.get("replay_render_mode") or "").strip() or "headless",
        "execution_status": str(source.get("execution_status") or "").strip(),
        "executed": bool(source.get("executed")),
        "execution_message": str(source.get("execution_message") or "").strip(),
        "execution_error": str(source.get("execution_error") or "").strip(),
        "stdout": str(source.get("stdout") or "").strip(),
        "stderr": str(source.get("stderr") or "").strip(),
        "screenshot_exists": bool(source.get("screenshot_exists")),
        "screenshot_capture_mode": screenshot_capture_mode,
        "viewport_baseline_status": viewport_baseline_status,
        "viewport_baseline_ready": bool(source.get("viewport_baseline_ready")),
        "viewport_baseline_message": str(source.get("viewport_baseline_message") or "").strip(),
        "blocking_checks": blocking_checks,
        "warning_checks": warning_checks,
        "status": status,
        "passed": status == "passed",
        "ready": status == "passed",
        "should_block": status == "blocked",
        "message": str(source.get("message") or "").strip(),
    }


def normalize_roadmap_status(summary: Dict[str, Any] | None) -> Dict[str, Any]:
    source = dict(summary or {})
    items = list(source.get("items") or [])
    status_counts = {"done": 0, "partial": 0, "pending": 0}
    normalized_items: List[Dict[str, Any]] = []
    for item in items:
        raw = _as_dict(item)
        status = str(raw.get("status") or "pending").strip().lower()
        if status not in status_counts:
            status = "pending"
        status_counts[status] += 1
        normalized_items.append({
            "item_id": str(raw.get("item_id") or "").strip(),
            "phase": str(raw.get("phase") or "").strip(),
            "title": str(raw.get("title") or "").strip(),
            "status": status,
            "summary": str(raw.get("summary") or "").strip(),
            "remaining_work": _clean_text_list(raw.get("remaining_work")),
            "next_action": str(raw.get("next_action") or "").strip(),
            "evidence": _clean_text_list(raw.get("evidence")),
            "risk": str(raw.get("risk") or "").strip(),
        })

    total_count = int(source.get("total_count") or len(normalized_items))
    remaining_items = [item for item in normalized_items if item["status"] != "done"]
    done_count = int(source.get("done_count") or status_counts["done"])
    remaining_count = int(source.get("remaining_count") or len(remaining_items))
    completion_percent = float(source.get("completion_percent") or 0.0)
    if total_count:
        completion_percent = round(done_count / total_count * 100, 2)

    return {
        "schema_version": ROADMAP_STATUS_SCHEMA_VERSION,
        "source_doc": str(source.get("source_doc") or "docs/游戏开发标准化增强路线图.md").strip(),
        "generated_at": str(source.get("generated_at") or "").strip(),
        "total_count": total_count,
        "done_count": done_count,
        "partial_count": int(source.get("partial_count") or status_counts["partial"]),
        "pending_count": int(source.get("pending_count") or status_counts["pending"]),
        "remaining_count": remaining_count,
        "completion_percent": completion_percent,
        "items": normalized_items,
        "remaining_items": remaining_items,
        "next_recommended_actions": _clean_text_list(source.get("next_recommended_actions")),
        "status": "passed" if remaining_count == 0 else "warning",
        "message": str(source.get("message") or "").strip(),
    }


def normalize_release_summary(summary: Dict[str, Any] | None) -> Dict[str, Any]:
    source = dict(summary or {})
    normalized_feature = build_release_feature_snapshot(source.get("feature"))
    normalized_gate = normalize_quality_gate(source.get("quality_gate"))
    normalized_qa_evidence = normalize_release_qa_evidence(source.get("qa_evidence"), normalized_gate)
    known_issues = _clean_text_list(source.get("known_issues") or source.get("known_risks")) or ["未登记已知风险"]
    change_summary = _clean_text_list(source.get("change_summary"))
    contract_versions = dict(_as_dict(source.get("contract_versions")))
    contract_versions["release_summary"] = RELEASE_SUMMARY_SCHEMA_VERSION
    if normalized_gate.get("schema_version"):
        contract_versions["quality_gate"] = normalized_gate["schema_version"]
    if normalized_qa_evidence.get("schema_version"):
        contract_versions["release_qa_evidence"] = normalized_qa_evidence["schema_version"]

    acceptance_checklist: List[Dict[str, Any]] = []
    for item in list(source.get("acceptance_checklist") or []):
        acceptance_checklist.append(_normalize_acceptance_checklist_item(item))

    files: List[Dict[str, Any]] = []
    for item in list(source.get("files") or []):
        raw = _as_dict(item)
        files.append({
            "path": str(raw.get("path") or "").strip(),
            "size": int(raw.get("size") or 0),
            "sha256": str(raw.get("sha256") or "").strip(),
        })

    return {
        **source,
        "schema_version": RELEASE_SUMMARY_SCHEMA_VERSION,
        "build_id": str(source.get("build_id") or "").strip(),
        "version": str(source.get("version") or "").strip(),
        "channel": str(source.get("channel") or "").strip(),
        "preset_name": str(source.get("preset_name") or "").strip(),
        "platform": str(source.get("platform") or "").strip(),
        "generated_at": str(source.get("generated_at") or "").strip(),
        "task_id": str(source.get("task_id") or "").strip(),
        "task_prompt": str(source.get("task_prompt") or "").strip(),
        "output_path": str(source.get("output_path") or "").strip(),
        "release_dir": str(source.get("release_dir") or "").strip(),
        "release_url": str(source.get("release_url") or "").strip(),
        "versioned_release_url": str(source.get("versioned_release_url") or "").strip(),
        "build_log_path": str(source.get("build_log_path") or "").strip(),
        "release_notes_path": str(source.get("release_notes_path") or "").strip(),
        "release_manifest_path": str(source.get("release_manifest_path") or "").strip(),
        "feature": normalized_feature,
        "change_summary": change_summary,
        "acceptance_checklist": acceptance_checklist,
        "known_risks": known_issues,
        "known_issues": known_issues,
        "quality_gate": normalized_gate,
        "qa_evidence": normalized_qa_evidence,
        "files": files,
        "rollback_hint": str(source.get("rollback_hint") or "").strip(),
        "contract_versions": contract_versions,
    }


def normalize_release_candidate_checklist(summary: Dict[str, Any] | None) -> Dict[str, Any]:
    source = dict(summary or {})
    release_summary = normalize_release_summary(source.get("release_summary"))
    quality_gate = normalize_quality_gate(source.get("quality_gate") or release_summary.get("quality_gate"))
    production_readiness = _as_dict(source.get("production_readiness"))
    notes = _clean_text_list(source.get("notes"))
    recommendations = _clean_text_list(source.get("recommendations"))
    changed_paths = _clean_text_list(source.get("changed_paths"))

    checklist: List[Dict[str, Any]] = []
    for item in list(source.get("checklist") or []):
        raw = _as_dict(item)
        checklist.append({
            "item_id": str(raw.get("item_id") or raw.get("name") or "").strip() or "unnamed_item",
            "label": str(raw.get("label") or raw.get("item_id") or "").strip() or "Unnamed Item",
            "status": _normalize_choice(raw.get("status"), QUALITY_GATE_CHECK_STATUSES, "skipped"),
            "required": bool(raw.get("required", True)),
            "message": str(raw.get("message") or raw.get("summary") or "").strip(),
            "details": dict(_as_dict(raw.get("details"))),
        })

    blocked_checks = [item["item_id"] for item in checklist if item["status"] == "blocked"]
    warning_checks = [item["item_id"] for item in checklist if item["status"] == "warning"]
    status = "blocked" if blocked_checks else ("warning" if warning_checks else "passed")
    fail_on_warnings = bool(source.get("fail_on_warnings"))
    mode = str(source.get("mode") or "strict").strip().lower() or "strict"
    should_block = bool(blocked_checks) or (fail_on_warnings and bool(warning_checks))
    if mode == "advisory":
        should_block = False

    contract_versions = dict(_as_dict(source.get("contract_versions")))
    contract_versions["release_candidate_checklist"] = RELEASE_CANDIDATE_CHECKLIST_SCHEMA_VERSION
    if quality_gate.get("schema_version"):
        contract_versions["quality_gate"] = quality_gate["schema_version"]
    if release_summary.get("schema_version"):
        contract_versions["release_summary"] = release_summary["schema_version"]
    if production_readiness.get("schema_version"):
        contract_versions["production_readiness"] = production_readiness["schema_version"]

    return {
        "schema_version": RELEASE_CANDIDATE_CHECKLIST_SCHEMA_VERSION,
        "contract_versions": contract_versions,
        "project_root": str(source.get("project_root") or "").strip(),
        "runtime_root": str(source.get("runtime_root") or "").strip(),
        "release_manifest_path": str(source.get("release_manifest_path") or "").strip(),
        "release_manifest_source": str(source.get("release_manifest_source") or "").strip() or "missing",
        "release_notes_path": str(source.get("release_notes_path") or "").strip(),
        "qa_gate_report_path": str(source.get("qa_gate_report_path") or "").strip(),
        "build_log_path": str(source.get("build_log_path") or "").strip(),
        "mode": "advisory" if mode == "advisory" else "strict",
        "fail_on_warnings": fail_on_warnings,
        "passed": not should_block,
        "status": status,
        "should_block": should_block,
        "checklist": checklist,
        "item_count": len(checklist),
        "passed_count": sum(1 for item in checklist if item["status"] == "passed"),
        "warning_count": len(warning_checks),
        "blocked_count": len(blocked_checks),
        "blocking_checks": blocked_checks,
        "warning_checks": warning_checks,
        "notes": notes,
        "recommendations": recommendations,
        "changed_paths": changed_paths,
        "derived_evidence": dict(_as_dict(source.get("derived_evidence"))),
        "release_summary": release_summary,
        "quality_gate": quality_gate,
        "production_readiness": production_readiness,
    }

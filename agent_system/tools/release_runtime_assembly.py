from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List

from .release_boundary import load_release_identity_boundary_profile
from .release_capability_policy import (
    CAPABILITY_POLICY_ROUTE_KINDS,
    RELEASE_CAPABILITY_POLICY_SCHEMA_VERSION,
    build_release_capability_policy,
)


RELEASE_RUNTIME_ASSEMBLY_SCHEMA_VERSION = "1.0"


def build_release_runtime_assembly_snapshot(
    project_root: str | Path,
    runtime_root: str | Path | None = None,
    *,
    route_kind: str = "portal",
    target_channel: str = "staging",
    target_environment: str = "",
    actor_id: str = "",
    invocation_source: str = "",
    route_id: str = "",
    session_id: str = "",
    runner_baseline: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    resolved_project_root = Path(project_root).resolve()
    resolved_runtime_root = Path(runtime_root or Path.cwd()).resolve()
    normalized_route_kind = _normalize_choice(route_kind, CAPABILITY_POLICY_ROUTE_KINDS, "portal")
    normalized_target_channel = str(target_channel or "staging").strip().lower() or "staging"
    normalized_target_environment = str(target_environment or "").strip() or (
        "production" if normalized_target_channel == "release" else normalized_target_channel
    )
    normalized_actor_id = str(actor_id or "").strip()
    normalized_invocation_source = str(invocation_source or "").strip() or normalized_route_kind

    capability_policy = build_release_capability_policy(
        resolved_project_root,
        runtime_root=resolved_runtime_root,
        route_kind=normalized_route_kind,
        target_channel=normalized_target_channel,
        target_environment=normalized_target_environment,
        actor_id=normalized_actor_id,
    )
    identity_boundary = load_release_identity_boundary_profile(
        resolved_project_root,
        target_channel=normalized_target_channel,
        target_environment=normalized_target_environment,
    )
    normalized_runner_baseline = _normalize_runner_baseline(runner_baseline)
    capability_items = [
        _normalize_capability_snapshot(item)
        for item in list(capability_policy.get("capabilities") or [])
        if isinstance(item, dict)
    ]

    auth_profile = _build_auth_profile(capability_items, actor_id=normalized_actor_id)
    status = _worst_status(
        [
            capability_policy.get("status"),
            identity_boundary.get("status") if auth_profile["request_auth_required_count"] else "skipped",
            normalized_runner_baseline.get("status") if normalized_runner_baseline.get("profile_id") else "skipped",
        ]
    )
    allowed_capability_ids = _clean_text_list(capability_policy.get("allowed_capability_ids"))
    warning_capability_ids = _clean_text_list(capability_policy.get("warning_capability_ids"))
    denied_capability_ids = _clean_text_list(capability_policy.get("denied_capability_ids"))
    skipped_capability_ids = _clean_text_list(capability_policy.get("skipped_capability_ids"))
    enabled_sandbox_profiles = _collect_dimension_values(capability_items, "sandbox_profile", {"passed"})
    warning_sandbox_profiles = _collect_dimension_values(capability_items, "sandbox_profile", {"warning"})
    denied_sandbox_profiles = _collect_dimension_values(capability_items, "sandbox_profile", {"blocked"})
    enabled_surface_types = _collect_surface_types(capability_items, {"passed"})
    denied_surface_types = _collect_surface_types(capability_items, {"blocked"})
    normalized_route_id = str(route_id or "").strip() or (
        f"{normalized_route_kind}:{normalized_target_channel}:{normalized_target_environment}"
    )
    normalized_session_id = str(session_id or "").strip() or str(normalized_runner_baseline.get("github_run_id") or "").strip()

    summary = (
        f"route={normalized_route_kind} / actor={normalized_actor_id or '-'} / "
        f"allowed={len(allowed_capability_ids)} / warning={len(warning_capability_ids)} / "
        f"blocked={len(denied_capability_ids)} / identity={identity_boundary.get('status') or 'skipped'}"
    )
    if normalized_runner_baseline.get("profile_id"):
        summary += f" / runner_profile={normalized_runner_baseline.get('profile_id') or '-'}"

    recommendations = _dedupe_text_list(
        list(capability_policy.get("recommendations") or [])
        + list(identity_boundary.get("recommendations") or [])
        + list(normalized_runner_baseline.get("recommendations") or [])
    )

    return {
        "schema_version": RELEASE_RUNTIME_ASSEMBLY_SCHEMA_VERSION,
        "contract_versions": {
            "release_runtime_assembly_snapshot": RELEASE_RUNTIME_ASSEMBLY_SCHEMA_VERSION,
            "release_capability_policy": RELEASE_CAPABILITY_POLICY_SCHEMA_VERSION,
        },
        "status": status,
        "summary": summary,
        "route_kind": normalized_route_kind,
        "route_id": normalized_route_id,
        "session_id": normalized_session_id,
        "invocation_source": normalized_invocation_source,
        "actor_id": normalized_actor_id,
        "target_channel": normalized_target_channel,
        "target_environment": normalized_target_environment,
        "registry_id": str(capability_policy.get("registry_id") or "").strip(),
        "registry_path": str(capability_policy.get("registry_path") or "").strip(),
        "registry_status": str(capability_policy.get("registry_status") or "").strip(),
        "policy_status": str(capability_policy.get("status") or "").strip(),
        "route_profile": dict(capability_policy.get("route_profile") or {}),
        "capability_count": len(capability_items),
        "allowed_count": len(allowed_capability_ids),
        "warning_count": len(warning_capability_ids),
        "denied_count": len(denied_capability_ids),
        "skipped_count": len(skipped_capability_ids),
        "allowed_capability_ids": allowed_capability_ids,
        "warning_capability_ids": warning_capability_ids,
        "denied_capability_ids": denied_capability_ids,
        "skipped_capability_ids": skipped_capability_ids,
        "enabled_sandbox_profiles": enabled_sandbox_profiles,
        "warning_sandbox_profiles": warning_sandbox_profiles,
        "denied_sandbox_profiles": denied_sandbox_profiles,
        "enabled_surface_types": enabled_surface_types,
        "denied_surface_types": denied_surface_types,
        "auth_profile": auth_profile,
        "identity_boundary": _normalize_identity_boundary(identity_boundary),
        "runner_profile": normalized_runner_baseline,
        "capabilities": capability_items,
        "recommendations": recommendations,
    }


def build_release_runtime_assembly_report_lines(summary: Dict[str, Any] | None) -> List[str]:
    normalized = dict(summary or {})
    route_profile = dict(normalized.get("route_profile") or {})
    auth_profile = dict(normalized.get("auth_profile") or {})
    identity_boundary = dict(normalized.get("identity_boundary") or {})
    runner_profile = dict(normalized.get("runner_profile") or {})
    capabilities = [dict(item) for item in list(normalized.get("capabilities") or []) if isinstance(item, dict)]

    lines = [
        f"- Status: {normalized.get('status') or 'warning'}",
        f"- Summary: {normalized.get('summary') or '-'}",
        (
            f"- Route: {normalized.get('route_kind') or '-'} / "
            f"route_id={normalized.get('route_id') or '-'} / "
            f"session_id={normalized.get('session_id') or '-'} / "
            f"invocation={normalized.get('invocation_source') or '-'}"
        ),
        (
            f"- Target: {normalized.get('target_channel') or '-'} -> "
            f"{normalized.get('target_environment') or '-'} / "
            f"actor={normalized.get('actor_id') or '-'}"
        ),
        (
            f"- Counts: total={int(normalized.get('capability_count') or 0)} / "
            f"allowed={int(normalized.get('allowed_count') or 0)} / "
            f"warning={int(normalized.get('warning_count') or 0)} / "
            f"blocked={int(normalized.get('denied_count') or 0)} / "
            f"skipped={int(normalized.get('skipped_count') or 0)}"
        ),
        f"- Registry: {normalized.get('registry_path') or '-'} ({normalized.get('registry_status') or '-'})",
        f"- Route Profile: {_format_bool_map(route_profile) or '-'}",
        (
            f"- Auth Profile: actor_present={'yes' if auth_profile.get('actor_present') else 'no'} / "
            f"actor_required={int(auth_profile.get('requires_actor_count') or 0)} / "
            f"request_auth_required={int(auth_profile.get('request_auth_required_count') or 0)} / "
            f"authorization_blocked={_render_list(auth_profile.get('authorization_blocked_capability_ids'))} / "
            f"request_auth_warning={_render_list(auth_profile.get('request_auth_warning_capability_ids'))}"
        ),
        (
            f"- Identity Boundary: status={identity_boundary.get('status') or '-'} / "
            f"profile={identity_boundary.get('profile_id') or '-'} / "
            f"provider={identity_boundary.get('provider_mode') or '-'} / "
            f"session_required={bool(identity_boundary.get('session_required'))} / "
            f"handoff={identity_boundary.get('external_handoff_target_id') or '-'}"
        ),
        (
            f"- Runner Profile: status={runner_profile.get('status') or '-'} / "
            f"profile={runner_profile.get('profile_id') or '-'} / "
            f"name={runner_profile.get('runner_name') or '-'} / "
            f"os={runner_profile.get('runner_os') or '-'} / "
            f"arch={runner_profile.get('runner_arch') or '-'} / "
            f"labels={_render_list(runner_profile.get('runner_labels'))}"
        ),
        (
            f"- Enabled Surfaces: {_render_list(normalized.get('enabled_surface_types'))} / "
            f"Denied Surfaces: {_render_list(normalized.get('denied_surface_types'))}"
        ),
        (
            f"- Enabled Sandboxes: {_render_list(normalized.get('enabled_sandbox_profiles'))} / "
            f"Denied Sandboxes: {_render_list(normalized.get('denied_sandbox_profiles'))}"
        ),
    ]
    for capability in capabilities[:8]:
        lines.append(
            f"- Capability ({capability.get('capability_id') or 'capability'}): "
            f"status={capability.get('policy_status') or '-'} / "
            f"sandbox={capability.get('sandbox_profile') or '-'} / "
            f"surface={','.join(list(capability.get('surface_types') or [])) or '-'} / "
            f"contracts={_render_list(capability.get('artifact_contracts'))} / "
            f"entrypoints={_render_list(capability.get('entrypoints'))} / "
            f"reasons={_render_list(capability.get('denial_reasons') or capability.get('warning_reasons'))}"
        )
    return lines


def _normalize_capability_snapshot(value: Dict[str, Any]) -> Dict[str, Any]:
    raw = dict(value or {})
    return {
        "capability_id": str(raw.get("capability_id") or "").strip(),
        "label": str(raw.get("label") or "").strip(),
        "group": str(raw.get("group") or "").strip(),
        "policy_status": str(raw.get("policy_status") or "").strip(),
        "sandbox_profile": str(raw.get("sandbox_profile") or "").strip(),
        "surface_types": _clean_text_list(raw.get("surface_types")),
        "artifact_contracts": _clean_text_list(raw.get("artifact_contracts")),
        "entrypoints": _clean_text_list(raw.get("entrypoints")),
        "requires_actor": bool(raw.get("requires_actor")),
        "requires_request_auth": bool(raw.get("requires_request_auth")),
        "authorization_status": str(raw.get("authorization_status") or "").strip(),
        "request_auth_posture_status": str(raw.get("request_auth_posture_status") or "").strip(),
        "denial_reasons": _clean_text_list(raw.get("denial_reasons")),
        "warning_reasons": _clean_text_list(raw.get("warning_reasons")),
    }


def _build_auth_profile(capabilities: List[Dict[str, Any]], *, actor_id: str) -> Dict[str, Any]:
    return {
        "actor_present": bool(actor_id),
        "requires_actor_count": sum(1 for item in capabilities if bool(item.get("requires_actor"))),
        "request_auth_required_count": sum(1 for item in capabilities if bool(item.get("requires_request_auth"))),
        "actor_required_capability_ids": [
            str(item.get("capability_id") or "").strip()
            for item in capabilities
            if bool(item.get("requires_actor"))
        ],
        "request_auth_required_capability_ids": [
            str(item.get("capability_id") or "").strip()
            for item in capabilities
            if bool(item.get("requires_request_auth"))
        ],
        "authorization_blocked_capability_ids": [
            str(item.get("capability_id") or "").strip()
            for item in capabilities
            if str(item.get("authorization_status") or "").strip().lower() == "blocked"
        ],
        "authorization_warning_capability_ids": [
            str(item.get("capability_id") or "").strip()
            for item in capabilities
            if str(item.get("authorization_status") or "").strip().lower() == "warning"
        ],
        "request_auth_blocked_capability_ids": [
            str(item.get("capability_id") or "").strip()
            for item in capabilities
            if str(item.get("request_auth_posture_status") or "").strip().lower() == "blocked"
        ],
        "request_auth_warning_capability_ids": [
            str(item.get("capability_id") or "").strip()
            for item in capabilities
            if str(item.get("request_auth_posture_status") or "").strip().lower() == "warning"
        ],
    }


def _normalize_identity_boundary(value: Dict[str, Any]) -> Dict[str, Any]:
    raw = dict(value or {})
    return {
        "status": str(raw.get("status") or "").strip(),
        "path": str(raw.get("path") or "").strip(),
        "profile_id": str(raw.get("profile_id") or "").strip(),
        "provider_mode": str(raw.get("provider_mode") or "").strip(),
        "provider_id": str(raw.get("provider_id") or "").strip(),
        "session_required": bool(raw.get("session_required")),
        "session_backend": str(raw.get("session_backend") or "").strip(),
        "max_session_age_hours": max(int(raw.get("max_session_age_hours") or 0), 0),
        "secret_rotation_required": bool(raw.get("secret_rotation_required")),
        "secret_backend": str(raw.get("secret_backend") or "").strip(),
        "rotation_owner": str(raw.get("rotation_owner") or "").strip(),
        "rotation_window_days": max(int(raw.get("rotation_window_days") or 0), 0),
        "external_handoff_required": bool(raw.get("external_handoff_required")),
        "external_handoff_mode": str(raw.get("external_handoff_mode") or "").strip(),
        "external_handoff_target_id": str(raw.get("external_handoff_target_id") or "").strip(),
        "external_handoff_owner": str(raw.get("external_handoff_owner") or "").strip(),
    }


def _normalize_runner_baseline(value: Dict[str, Any] | None) -> Dict[str, Any]:
    raw = dict(value or {})
    return {
        "status": str(raw.get("status") or "").strip(),
        "report_path": str(raw.get("report_path") or "").strip(),
        "path": str(raw.get("runner_profile_path") or "").strip(),
        "profile_id": str(raw.get("runner_profile_id") or "").strip(),
        "runner_name": str(raw.get("runner_name") or "").strip(),
        "runner_os": str(raw.get("runner_os") or "").strip(),
        "runner_arch": str(raw.get("runner_arch") or "").strip(),
        "runner_labels": _clean_text_list(raw.get("declared_runner_labels") or raw.get("required_runner_labels")),
        "github_workflow": str(raw.get("github_workflow") or "").strip(),
        "github_job": str(raw.get("github_job") or "").strip(),
        "github_run_id": str(raw.get("github_run_id") or "").strip(),
        "github_run_attempt": str(raw.get("github_run_attempt") or "").strip(),
        "recommendations": _clean_text_list(raw.get("recommendations")),
    }


def _collect_dimension_values(capabilities: List[Dict[str, Any]], key: str, statuses: set[str]) -> List[str]:
    values: List[str] = []
    for item in capabilities:
        if str(item.get("policy_status") or "").strip().lower() not in statuses:
            continue
        value = str(item.get(key) or "").strip()
        if value and value not in values:
            values.append(value)
    return values


def _collect_surface_types(capabilities: List[Dict[str, Any]], statuses: set[str]) -> List[str]:
    values: List[str] = []
    for item in capabilities:
        if str(item.get("policy_status") or "").strip().lower() not in statuses:
            continue
        for surface_type in _clean_text_list(item.get("surface_types")):
            if surface_type not in values:
                values.append(surface_type)
    return values


def _worst_status(values: List[Any]) -> str:
    priorities = {"blocked": 3, "warning": 2, "passed": 1, "skipped": 0}
    worst = "passed"
    worst_priority = priorities[worst]
    for raw_value in values:
        value = str(raw_value or "").strip().lower()
        if not value:
            continue
        priority = priorities.get(value, priorities["warning"])
        if priority > worst_priority:
            worst = value if value in priorities else "warning"
            worst_priority = priority
    return worst


def _normalize_choice(value: Any, allowed: set[str], default: str) -> str:
    normalized = str(value or "").strip().lower()
    return normalized if normalized in allowed else default


def _clean_text_list(values: Any) -> List[str]:
    result: List[str] = []
    for raw in list(values or []):
        value = str(raw or "").strip()
        if value and value not in result:
            result.append(value)
    return result


def _dedupe_text_list(values: List[str]) -> List[str]:
    return _clean_text_list(values)


def _format_bool_map(value: Dict[str, Any]) -> str:
    if not isinstance(value, dict):
        return ""
    parts = []
    for key in sorted(value):
        parts.append(f"{key}={'yes' if value.get(key) else 'no'}")
    return ", ".join(parts)


def _render_list(value: Any) -> str:
    cleaned = _clean_text_list(value)
    return ", ".join(cleaned) if cleaned else "-"

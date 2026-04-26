from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List

from .release_access_policy import authorize_release_operation
from .release_capability_registry import (
    build_release_capability_registry,
    default_release_capability_registry_path,
)
from .release_request_auth import build_release_request_auth_posture


RELEASE_CAPABILITY_POLICY_SCHEMA_VERSION = "1.0"
CAPABILITY_POLICY_ROUTE_KINDS = {
    "portal",
    "api",
    "ci_rehearsal",
    "local_replay",
    "github_workflow",
}

_ROUTE_PROFILES: Dict[str, Dict[str, Any]] = {
    "portal": {
        "allow_workspace_write": True,
        "allow_release_write": True,
        "allow_local_process": False,
        "allow_optional_heavy": False,
        "allow_browser_automation": False,
        "allow_godot_gui": False,
        "allow_network_bridge": False,
    },
    "api": {
        "allow_workspace_write": True,
        "allow_release_write": True,
        "allow_local_process": False,
        "allow_optional_heavy": False,
        "allow_browser_automation": False,
        "allow_godot_gui": False,
        "allow_network_bridge": False,
    },
    "ci_rehearsal": {
        "allow_workspace_write": True,
        "allow_release_write": False,
        "allow_local_process": True,
        "allow_optional_heavy": False,
        "allow_browser_automation": False,
        "allow_godot_gui": False,
        "allow_network_bridge": False,
    },
    "local_replay": {
        "allow_workspace_write": True,
        "allow_release_write": False,
        "allow_local_process": True,
        "allow_optional_heavy": True,
        "allow_browser_automation": True,
        "allow_godot_gui": True,
        "allow_network_bridge": True,
    },
    "github_workflow": {
        "allow_workspace_write": True,
        "allow_release_write": False,
        "allow_local_process": True,
        "allow_optional_heavy": True,
        "allow_browser_automation": True,
        "allow_godot_gui": True,
        "allow_network_bridge": True,
    },
}


def build_release_capability_policy(
    project_root: str | Path,
    runtime_root: str | Path | None = None,
    *,
    registry_path: str = "",
    route_kind: str = "portal",
    target_channel: str = "staging",
    target_environment: str = "",
    actor_id: str = "",
) -> Dict[str, Any]:
    resolved_project_root = Path(project_root).resolve()
    resolved_runtime_root = Path(runtime_root or Path.cwd()).resolve()
    normalized_route_kind = _normalize_choice(route_kind, CAPABILITY_POLICY_ROUTE_KINDS, "portal")
    normalized_target_channel = str(target_channel or "staging").strip().lower() or "staging"
    normalized_target_environment = str(target_environment or "").strip() or (
        "production" if normalized_target_channel == "release" else normalized_target_channel
    )
    normalized_actor_id = str(actor_id or "").strip()

    registry = build_release_capability_registry(
        resolved_project_root,
        registry_path=registry_path or default_release_capability_registry_path(),
    )
    route_profile = dict(_ROUTE_PROFILES.get(normalized_route_kind, _ROUTE_PROFILES["portal"]))

    items: List[Dict[str, Any]] = []
    allowed_capability_ids: List[str] = []
    warning_capability_ids: List[str] = []
    denied_capability_ids: List[str] = []
    skipped_capability_ids: List[str] = []
    group_counts: Dict[str, int] = {}
    denial_reason_counts: Dict[str, int] = {}

    for raw_item in list(registry.get("capabilities") or []):
        capability = _evaluate_capability_policy(
            raw_item,
            project_root=resolved_project_root,
            runtime_root=resolved_runtime_root,
            route_kind=normalized_route_kind,
            route_profile=route_profile,
            target_channel=normalized_target_channel,
            target_environment=normalized_target_environment,
            actor_id=normalized_actor_id,
        )
        items.append(capability)
        group = str(capability.get("group") or "").strip()
        if group:
            group_counts[group] = group_counts.get(group, 0) + 1
        for reason in list(capability.get("denial_reasons") or []):
            denial_reason_counts[reason] = denial_reason_counts.get(reason, 0) + 1
        policy_status = str(capability.get("policy_status") or "warning").strip().lower()
        capability_id = str(capability.get("capability_id") or "").strip()
        if policy_status == "passed":
            allowed_capability_ids.append(capability_id)
        elif policy_status == "warning":
            warning_capability_ids.append(capability_id)
        elif policy_status == "blocked":
            denied_capability_ids.append(capability_id)
        else:
            skipped_capability_ids.append(capability_id)

    status = _worst_status(
        [registry.get("status")] + [item.get("policy_status") for item in items if item.get("policy_status") != "skipped"]
    )
    summary = (
        f"route={normalized_route_kind} / channel={normalized_target_channel} / env={normalized_target_environment} / "
        f"allowed={len(allowed_capability_ids)} / warning={len(warning_capability_ids)} / "
        f"blocked={len(denied_capability_ids)} / skipped={len(skipped_capability_ids)}"
    )

    recommendations: List[str] = []
    for item in items:
        recommendations.extend(list(item.get("recommendations") or []))

    return {
        "schema_version": RELEASE_CAPABILITY_POLICY_SCHEMA_VERSION,
        "contract_versions": {
            "release_capability_policy": RELEASE_CAPABILITY_POLICY_SCHEMA_VERSION,
            "release_capability_registry": str(registry.get("schema_version") or ""),
        },
        "status": status,
        "summary": summary,
        "route_kind": normalized_route_kind,
        "target_channel": normalized_target_channel,
        "target_environment": normalized_target_environment,
        "actor_id": normalized_actor_id,
        "registry_status": str(registry.get("status") or "warning").strip(),
        "registry_path": str(registry.get("registry_path") or "").strip(),
        "registry_id": str(registry.get("registry_id") or "").strip(),
        "route_profile": route_profile,
        "capability_count": len(items),
        "allowed_count": len(allowed_capability_ids),
        "warning_count": len(warning_capability_ids),
        "denied_count": len(denied_capability_ids),
        "skipped_count": len(skipped_capability_ids),
        "allowed_capability_ids": allowed_capability_ids,
        "warning_capability_ids": warning_capability_ids,
        "denied_capability_ids": denied_capability_ids,
        "skipped_capability_ids": skipped_capability_ids,
        "group_counts": group_counts,
        "denial_reason_counts": denial_reason_counts,
        "capabilities": items,
        "recommendations": _dedupe_text_list(recommendations),
    }


def build_release_capability_policy_report(summary: Dict[str, Any] | None) -> str:
    policy = dict(summary or {})
    lines = [
        "# Release Capability Policy",
        "",
        f"- Status: {policy.get('status') or 'warning'}",
        f"- Summary: {policy.get('summary') or '-'}",
        f"- Registry: {policy.get('registry_path') or '-'} ({policy.get('registry_status') or '-'})",
        f"- Route: {policy.get('route_kind') or '-'} / actor={policy.get('actor_id') or '-'}",
        f"- Target: {policy.get('target_channel') or '-'} -> {policy.get('target_environment') or '-'}",
        (
            f"- Counts: total={int(policy.get('capability_count') or 0)} / "
            f"allowed={int(policy.get('allowed_count') or 0)} / "
            f"warning={int(policy.get('warning_count') or 0)} / "
            f"blocked={int(policy.get('denied_count') or 0)} / "
            f"skipped={int(policy.get('skipped_count') or 0)}"
        ),
        f"- Route Profile: {_format_countless_map(policy.get('route_profile')) or '-'}",
        f"- Denials: {_format_count_map(policy.get('denial_reason_counts')) or '-'}",
        "",
        "## Capabilities",
        "",
    ]
    for item in list(policy.get("capabilities") or []):
        lines.extend([
            f"- `{item.get('capability_id') or 'capability'}` [{item.get('policy_status') or 'warning'}] {item.get('label') or '-'}",
            (
                "  "
                f"surface={','.join(item.get('surface_types') or []) or '-'} / "
                f"risk={item.get('risk_level') or '-'} / sandbox={item.get('sandbox_profile') or '-'} / "
                f"allowed={'yes' if item.get('invocation_allowed') else 'no'} / "
                f"applicable={'yes' if item.get('applicable') else 'no'}"
            ),
            (
                "  "
                f"policy_action={item.get('policy_action') or '-'} / "
                f"policy_decision={item.get('policy_decision') or '-'} / "
                f"policy_operation={item.get('policy_operation') or '-'}"
            ),
            (
                "  "
                f"authorization={item.get('authorization_status') or '-'} / "
                f"request_auth_posture={item.get('request_auth_posture_status') or '-'}"
            ),
            (
                "  "
                f"contracts={','.join(item.get('artifact_contracts') or []) or '-'} / "
                f"entrypoints={','.join(item.get('entrypoints') or []) or '-'}"
            ),
            f"  reasons={', '.join(item.get('denial_reasons') or item.get('warning_reasons') or ['none'])}",
            f"  summary={item.get('summary') or '-'}",
        ])
    recommendations = list(policy.get("recommendations") or [])
    if recommendations:
        lines.extend(["", "## Recommendations", ""])
        lines.extend(f"- {item}" for item in recommendations)
    return "\n".join(lines).strip() + "\n"


def _evaluate_capability_policy(
    capability: Dict[str, Any],
    *,
    project_root: Path,
    runtime_root: Path,
    route_kind: str,
    route_profile: Dict[str, Any],
    target_channel: str,
    target_environment: str,
    actor_id: str,
) -> Dict[str, Any]:
    item = dict(capability)
    denial_reasons: List[str] = []
    warning_reasons: List[str] = []
    recommendations: List[str] = []

    target_channels = list(item.get("target_channels") or [])
    target_environments = list(item.get("target_environments") or [])
    applicable = (not target_channels or target_channel in target_channels) and (
        not target_environments or target_environment in target_environments
    )
    if not applicable:
        policy_status = "skipped"
        invocation_allowed = False
    else:
        policy_status = "passed"
        invocation_allowed = True

    sandbox_profile = str(item.get("sandbox_profile") or "").strip()
    if applicable:
        capability_registry_status = str(item.get("status") or "passed").strip().lower()
        if capability_registry_status == "blocked":
            denial_reasons.append("capability_registry_blocked")
        elif capability_registry_status == "warning":
            warning_reasons.append("capability_registry_warning")
        if bool(item.get("optional_heavy")) and not bool(route_profile.get("allow_optional_heavy")):
            denial_reasons.append("optional_heavy_disabled")
        if sandbox_profile == "workspace_write" and not bool(route_profile.get("allow_workspace_write")):
            denial_reasons.append("workspace_write_disabled")
        if sandbox_profile == "release_write" and not bool(route_profile.get("allow_release_write")):
            denial_reasons.append("release_write_disabled")
        if sandbox_profile == "local_process" and not bool(route_profile.get("allow_local_process")):
            denial_reasons.append("local_process_disabled")
        if sandbox_profile == "browser_automation" and not bool(route_profile.get("allow_browser_automation")):
            denial_reasons.append("browser_automation_disabled")
        if sandbox_profile == "godot_gui" and not bool(route_profile.get("allow_godot_gui")):
            denial_reasons.append("godot_gui_disabled")
        if sandbox_profile == "network_bridge" and not bool(route_profile.get("allow_network_bridge")):
            denial_reasons.append("network_bridge_disabled")
        if bool(item.get("requires_actor")) and not actor_id:
            denial_reasons.append("actor_required")

    authorization: Dict[str, Any] = {}
    authorization_status = ""
    if applicable and str(item.get("policy_action") or "").strip():
        authorization = authorize_release_operation(
            project_root,
            runtime_root=runtime_root,
            actor_id=actor_id,
            action=str(item.get("policy_action") or "").strip(),
            target_channel=target_channel,
            target_environment=target_environment,
            decision=str(item.get("policy_decision") or "").strip(),
            operation=str(item.get("policy_operation") or "").strip(),
            required=True,
        )
        authorization_status = str(authorization.get("status") or "").strip()
        if authorization_status == "blocked":
            denial_reasons.append("authorization_blocked")
            recommendations.append(str(authorization.get("reason") or ""))
        elif authorization_status == "warning":
            warning_reasons.append("authorization_warning")
            recommendations.append(str(authorization.get("reason") or ""))
        elif authorization_status == "skipped":
            warning_reasons.append("authorization_skipped")

    request_auth_posture: Dict[str, Any] = {}
    request_auth_posture_status = ""
    if applicable and bool(item.get("requires_request_auth")) and str(item.get("policy_action") or "").strip():
        request_auth_posture = build_release_request_auth_posture(
            project_root,
            runtime_root=runtime_root,
            action=str(item.get("policy_action") or "").strip(),
            target_channel=target_channel,
            target_environment=target_environment,
        )
        request_auth_posture_status = str(request_auth_posture.get("status") or "").strip()
        if request_auth_posture_status == "blocked":
            denial_reasons.append("request_auth_posture_blocked")
            recommendations.extend(list(request_auth_posture.get("recommendations") or []))
        elif request_auth_posture_status == "warning":
            warning_reasons.append("request_auth_posture_warning")
            recommendations.extend(list(request_auth_posture.get("recommendations") or []))

    if denial_reasons:
        policy_status = "blocked"
        invocation_allowed = False
    elif applicable and warning_reasons:
        policy_status = "warning"
        invocation_allowed = False

    return {
        **item,
        "route_kind": route_kind,
        "applicable": applicable,
        "invocation_allowed": invocation_allowed,
        "policy_status": policy_status,
        "authorization_status": authorization_status,
        "authorization_reason": str(authorization.get("reason") or "").strip(),
        "request_auth_posture_status": request_auth_posture_status,
        "request_auth_posture_summary": str(request_auth_posture.get("summary") or "").strip(),
        "denial_reasons": _dedupe_text_list(denial_reasons),
        "warning_reasons": _dedupe_text_list(warning_reasons),
        "recommendations": _dedupe_text_list(
            recommendations
            + list(item.get("recommendations") or [])
        ),
        "summary": _build_capability_policy_summary(
            item,
            policy_status=policy_status,
            applicable=applicable,
            authorization_status=authorization_status,
            request_auth_posture_status=request_auth_posture_status,
        ),
    }


def _build_capability_policy_summary(
    capability: Dict[str, Any],
    *,
    policy_status: str,
    applicable: bool,
    authorization_status: str,
    request_auth_posture_status: str,
) -> str:
    return (
        f"policy={policy_status or '-'} / "
        f"applicable={'yes' if applicable else 'no'} / "
        f"authorization={authorization_status or '-'} / "
        f"request_auth_posture={request_auth_posture_status or '-'} / "
        f"sandbox={capability.get('sandbox_profile') or '-'}"
    )


def _format_count_map(value: Any) -> str:
    if not isinstance(value, dict):
        return ""
    parts = []
    for key in sorted(value):
        count = int(value.get(key) or 0)
        if count <= 0:
            continue
        parts.append(f"{key}={count}")
    return ", ".join(parts)


def _format_countless_map(value: Any) -> str:
    if not isinstance(value, dict):
        return ""
    parts = []
    for key in sorted(value):
        parts.append(f"{key}={'yes' if value.get(key) else 'no'}")
    return ", ".join(parts)


def _normalize_choice(value: Any, allowed: set[str], default: str) -> str:
    normalized = str(value or "").strip().lower()
    return normalized if normalized in allowed else default


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


def _dedupe_text_list(values: List[str]) -> List[str]:
    cleaned: List[str] = []
    seen = set()
    for item in values:
        text = str(item).strip()
        if not text or text in seen:
            continue
        cleaned.append(text)
        seen.add(text)
    return cleaned

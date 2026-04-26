from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Iterable, List

from agent_system.contracts import (
    RELEASE_DELIVERY_READINESS_SCHEMA_VERSION,
    normalize_release_delivery_readiness,
    normalize_release_distribution_bundle,
    normalize_release_live_dispatch_audit,
    normalize_release_live_dispatch_preflight,
)
from agent_system.tools.release_distribution import (
    build_release_distribution_bundle,
    default_release_distribution_report_path,
)
from agent_system.tools.release_live_runner_baseline import (
    default_release_live_runner_baseline_report_path,
)
from agent_system.tools.release_request_auth import build_release_request_auth_identity_audit
from tools.dispatch_release_live_gates import (
    DEFAULT_TOKEN_ENV_NAMES,
    DEFAULT_WORKFLOW,
    build_release_live_dispatch_preflight,
    load_release_live_dispatch_audit,
)


DEFAULT_RELEASE_DELIVERY_ARTIFACT_DIR = "logs/reports/release_live_ci"
DEFAULT_RELEASE_DELIVERY_READINESS_REPORT_TEMPLATE = "logs/reports/release_delivery_readiness_{channel}.json"
DEFAULT_RELEASE_DELIVERY_READINESS_MARKDOWN_TEMPLATE = "logs/reports/release_delivery_readiness_{channel}.md"
_STATUS_VALUES = {"passed", "warning", "blocked", "skipped"}


def build_release_delivery_readiness(
    project_root: str | Path,
    runtime_root: str | Path | None = None,
    *,
    target_channel: str = "release",
    target_environment: str = "",
    artifact_dir: str = DEFAULT_RELEASE_DELIVERY_ARTIFACT_DIR,
    workflow: str = DEFAULT_WORKFLOW,
    repo: str = "",
    ref: str = "",
    token_env_names: Iterable[str] | str = DEFAULT_TOKEN_ENV_NAMES,
) -> Dict[str, Any]:
    resolved_project_root = Path(project_root).resolve()
    resolved_runtime_root = Path(runtime_root or Path.cwd()).resolve()
    normalized_target_channel = str(target_channel or "release").strip().lower() or "release"
    normalized_target_environment = str(target_environment or "").strip() or (
        "production" if normalized_target_channel == "release" else normalized_target_channel
    )
    normalized_artifact_dir = str(artifact_dir or DEFAULT_RELEASE_DELIVERY_ARTIFACT_DIR).strip() or DEFAULT_RELEASE_DELIVERY_ARTIFACT_DIR
    normalized_workflow = str(workflow or DEFAULT_WORKFLOW).strip() or DEFAULT_WORKFLOW

    identity_audit = build_release_request_auth_identity_audit(
        resolved_project_root,
        runtime_root=resolved_runtime_root,
        target_channel=normalized_target_channel,
        target_environment=normalized_target_environment,
    )
    distribution_bundle = _load_release_distribution_bundle(
        resolved_project_root,
        resolved_runtime_root,
        target_channel=normalized_target_channel,
        target_environment=normalized_target_environment,
    )
    dispatch_preflight = normalize_release_live_dispatch_preflight(
        build_release_live_dispatch_preflight(
            resolved_project_root,
            repo=repo,
            ref=ref,
            workflow=normalized_workflow,
            target_channel=normalized_target_channel,
            target_environment=normalized_target_environment,
            artifact_dir=normalized_artifact_dir,
            token_env_names=token_env_names,
        )
    )
    dispatch_audit = _load_release_live_dispatch_audit(
        resolved_project_root,
        resolved_runtime_root,
        artifact_dir=normalized_artifact_dir,
    )
    live_ci_summary = _load_release_live_ci_summary(
        resolved_project_root,
        resolved_runtime_root,
        artifact_dir=normalized_artifact_dir,
    )
    runner_baseline = _load_release_live_runner_baseline(
        resolved_project_root,
        resolved_runtime_root,
        target_channel=normalized_target_channel,
    )

    identity_boundary = _build_identity_boundary_component(identity_audit)
    workflow_release = _build_workflow_release_component(
        dispatch_preflight=dispatch_preflight,
        dispatch_audit=dispatch_audit,
        live_ci_summary=live_ci_summary,
        runner_baseline=runner_baseline,
    )
    distribution_delivery = _build_distribution_delivery_component(distribution_bundle)
    components = [identity_boundary, workflow_release, distribution_delivery]

    next_actions = _build_next_actions(
        target_channel=normalized_target_channel,
        target_environment=normalized_target_environment,
        components=components,
    )
    blocking_checks = _dedupe_text_list(
        item
        for component in components
        for item in list(component.get("blocking_checks") or [])
    )
    warning_checks = _dedupe_text_list(
        item
        for component in components
        for item in list(component.get("warning_checks") or [])
    )
    recommendations = _dedupe_text_list(
        [
            action.get("entrypoint") or ""
            for action in next_actions
            if str(action.get("status") or "").strip().lower() != "passed"
        ]
        + [
            item
            for component in components
            if str(component.get("status") or "").strip().lower() != "passed"
            for item in list(component.get("recommendations") or [])
        ]
    )
    notes = _dedupe_text_list(
        item
        for component in components
        for item in list(component.get("notes") or [])
    )
    status = _worst_status([component.get("status") for component in components], default="warning")
    status_counts = {
        value: sum(1 for component in components if str(component.get("status") or "") == value)
        for value in _STATUS_VALUES
    }
    summary = (
        f"identity={identity_boundary.get('status') or 'warning'} / "
        f"workflow={workflow_release.get('status') or 'warning'} / "
        f"distribution={distribution_delivery.get('status') or 'warning'} / "
        f"next_actions={len(next_actions)}"
    )

    return normalize_release_delivery_readiness(
        {
            "schema_version": RELEASE_DELIVERY_READINESS_SCHEMA_VERSION,
            "contract_versions": {
                "release_delivery_readiness": RELEASE_DELIVERY_READINESS_SCHEMA_VERSION,
                "release_live_dispatch_preflight": str(dispatch_preflight.get("schema_version") or ""),
                "release_live_dispatch_audit": str(dispatch_audit.get("schema_version") or ""),
                "release_distribution_bundle": str(distribution_bundle.get("schema_version") or ""),
                "release_request_auth_identity_audit": str(identity_audit.get("schema_version") or ""),
            },
            "project_root": str(resolved_project_root),
            "runtime_root": str(resolved_runtime_root),
            "target_channel": normalized_target_channel,
            "target_environment": normalized_target_environment,
            "artifact_dir": normalized_artifact_dir,
            "workflow": normalized_workflow,
            "repo": str(dispatch_preflight.get("repo") or ""),
            "ref": str(dispatch_preflight.get("ref") or ""),
            "status": status,
            "summary": summary,
            "component_count": len(components),
            "passed_count": status_counts["passed"],
            "warning_count": status_counts["warning"],
            "blocked_count": status_counts["blocked"],
            "blocking_checks": blocking_checks,
            "warning_checks": warning_checks,
            "identity_boundary": identity_boundary,
            "workflow_release": workflow_release,
            "distribution_delivery": distribution_delivery,
            "components": components,
            "next_actions": next_actions,
            "notes": notes,
            "recommendations": recommendations,
        }
    )


def build_release_delivery_readiness_report(summary: Dict[str, Any] | None) -> str:
    readiness = normalize_release_delivery_readiness(summary)
    lines = [
        "# Release Delivery Readiness",
        "",
        f"- Status: {readiness.get('status') or 'warning'}",
        f"- Summary: {readiness.get('summary') or '-'}",
        f"- Target: {readiness.get('target_channel') or '-'} -> {readiness.get('target_environment') or '-'}",
        f"- Workflow: {readiness.get('workflow') or '-'} / repo={readiness.get('repo') or '-'} / ref={readiness.get('ref') or '-'}",
        (
            f"- Counts: components={int(readiness.get('component_count') or 0)} / "
            f"passed={int(readiness.get('passed_count') or 0)} / "
            f"warning={int(readiness.get('warning_count') or 0)} / "
            f"blocked={int(readiness.get('blocked_count') or 0)}"
        ),
        f"- Blocking Checks: {', '.join(list(readiness.get('blocking_checks') or [])) or 'none'}",
        f"- Warning Checks: {', '.join(list(readiness.get('warning_checks') or [])) or 'none'}",
        "",
        "## Components",
        "",
    ]
    for component in list(readiness.get("components") or []):
        lines.extend(build_release_delivery_readiness_report_lines(component))
    lines.extend(["", "## Next Actions", ""])
    for action in list(readiness.get("next_actions") or []):
        lines.extend(
            [
                f"- `{action.get('action_id') or 'action'}` [{action.get('status') or 'warning'}] {action.get('label') or '-'}",
                (
                    "  "
                    f"owner={action.get('owner_hint') or '-'} / "
                    f"dependency={action.get('dependency') or '-'} / "
                    f"eta={action.get('eta') or '-'} / "
                    f"validation={action.get('validation_method') or '-'} / "
                    f"entrypoint={action.get('entrypoint') or '-'}"
                ),
                f"  blockers={', '.join(list(action.get('blockers') or [])) or 'none'}",
                f"  summary={action.get('summary') or '-'}",
            ]
        )
    if not list(readiness.get("next_actions") or []):
        lines.append("- none")
    recommendations = list(readiness.get("recommendations") or [])
    if recommendations:
        lines.extend(["", "## Recommendations", ""])
        lines.extend(f"- {item}" for item in recommendations)
    return "\n".join(lines).strip() + "\n"


def export_release_delivery_readiness(
    project_root: str | Path,
    runtime_root: str | Path | None = None,
    *,
    target_channel: str = "release",
    target_environment: str = "",
    artifact_dir: str = DEFAULT_RELEASE_DELIVERY_ARTIFACT_DIR,
    workflow: str = DEFAULT_WORKFLOW,
    repo: str = "",
    ref: str = "",
    token_env_names: Iterable[str] | str = DEFAULT_TOKEN_ENV_NAMES,
    report_path: str = "",
    markdown_path: str = "",
) -> Dict[str, Any]:
    resolved_runtime_root = Path(runtime_root or project_root).resolve()
    normalized_channel = str(target_channel or "release").strip().lower() or "release"
    json_path = _resolve_runtime_output_path(
        resolved_runtime_root,
        report_path or DEFAULT_RELEASE_DELIVERY_READINESS_REPORT_TEMPLATE.format(channel=normalized_channel),
    )
    md_path = _resolve_runtime_output_path(
        resolved_runtime_root,
        markdown_path or DEFAULT_RELEASE_DELIVERY_READINESS_MARKDOWN_TEMPLATE.format(channel=normalized_channel),
    )
    payload = build_release_delivery_readiness(
        project_root,
        runtime_root=resolved_runtime_root,
        target_channel=normalized_channel,
        target_environment=target_environment,
        artifact_dir=artifact_dir,
        workflow=workflow,
        repo=repo,
        ref=ref,
        token_env_names=token_env_names,
    )
    payload["report_path"] = _display_path(json_path, resolved_runtime_root)
    payload["report_markdown_path"] = _display_path(md_path, resolved_runtime_root)
    json_path.parent.mkdir(parents=True, exist_ok=True)
    md_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    md_path.write_text(build_release_delivery_readiness_report(payload), encoding="utf-8")
    return payload


def build_release_delivery_readiness_report_lines(summary: Dict[str, Any] | None) -> List[str]:
    component = dict(summary or {})
    if list(component.get("components") or []) or list(component.get("next_actions") or []):
        lines = [
            (
                f"- Release Delivery Readiness: status={component.get('status') or 'warning'} / "
                f"summary={component.get('summary') or '-'}"
            )
        ]
        for item in list(component.get("components") or []):
            lines.extend(build_release_delivery_readiness_report_lines(item))
        next_actions = list(component.get("next_actions") or [])
        if next_actions:
            lines.append("- Next Actions:")
            for action in next_actions:
                blockers = ", ".join(list(action.get("blockers") or [])) or "none"
                lines.append(
                    "  "
                    f"- `{action.get('action_id') or 'action'}` [{action.get('status') or 'warning'}] "
                    f"owner={action.get('owner_hint') or '-'} / "
                    f"dependency={action.get('dependency') or '-'} / "
                    f"eta={action.get('eta') or '-'} / "
                    f"validation={action.get('validation_method') or '-'} / "
                    f"blockers={blockers}"
                )
                if str(action.get("entrypoint") or "").strip():
                    lines.append(f"    entrypoint={action.get('entrypoint')}")
        return lines

    paths = dict(component.get("paths") or {})
    details = dict(component.get("details") or {})
    lines = [
        f"- {component.get('label') or component.get('component_id') or 'component'}: status={component.get('status') or 'warning'} / required={bool(component.get('required'))} / summary={component.get('summary') or '-'}",
    ]
    if paths:
        lines.append(
            "- Paths: "
            + ", ".join(f"{key}={value}" for key, value in paths.items() if str(value or "").strip())
        )
    if details:
        important_details = []
        for key in (
            "profile_id",
            "provider_mode",
            "handoff_status",
            "handoff_target_id",
            "preflight_status",
            "dispatch_status",
            "dispatch_run_status",
            "dispatch_run_conclusion",
            "github_workflow_observed",
            "ci_gate_status",
            "ci_gate_should_block",
            "invocation_source",
            "runner_baseline_status",
            "delivery_profile_id",
            "delivery_status",
            "delivery_primary_installer",
            "signing_handoff_status",
            "publish_handoff_status",
            "publish_receipts_status",
            "publish_receipts_target_count",
            "publish_receipts_recorded_target_count",
        ):
            value = details.get(key)
            if value in (None, "", [], {}):
                continue
            important_details.append(f"{key}={value}")
        if important_details:
            lines.append("- Details: " + " / ".join(important_details))
    if list(component.get("blocking_checks") or []):
        lines.append(f"- Blocking Checks: {', '.join(list(component.get('blocking_checks') or []))}")
    if list(component.get("warning_checks") or []):
        lines.append(f"- Warning Checks: {', '.join(list(component.get('warning_checks') or []))}")
    return lines


def _build_identity_boundary_component(identity_audit: Dict[str, Any]) -> Dict[str, Any]:
    status = _normalize_status(identity_audit.get("status"), default="warning")
    return {
        "component_id": "identity_boundary",
        "label": "External Identity Boundary",
        "required": True,
        "status": status,
        "summary": str(identity_audit.get("summary") or "").strip()
        or f"profile={identity_audit.get('identity_boundary_profile_id') or '-'} / handoff={identity_audit.get('identity_handoff_status') or '-'}",
        "blocking_checks": ["identity_boundary_blocked"] if status == "blocked" else [],
        "warning_checks": ["identity_boundary_incomplete"] if status == "warning" else [],
        "paths": {
            "report_path": str(identity_audit.get("report_path") or "").strip(),
            "identity_handoff_manifest_path": str(identity_audit.get("identity_handoff_manifest_path") or "").strip(),
            "identity_handoff_dir": str(identity_audit.get("identity_handoff_dir") or "").strip(),
        },
        "details": {
            "profile_id": str(identity_audit.get("identity_boundary_profile_id") or "").strip(),
            "provider_mode": str(identity_audit.get("identity_provider_mode") or "").strip(),
            "provider_id": str(identity_audit.get("identity_provider_id") or "").strip(),
            "handoff_status": str(identity_audit.get("identity_handoff_status") or "").strip(),
            "handoff_target_id": str(identity_audit.get("identity_handoff_target_id") or "").strip(),
            "session_required": bool(identity_audit.get("identity_session_required")),
            "session_backend": str(identity_audit.get("identity_session_backend") or "").strip(),
            "secret_rotation_required": bool(identity_audit.get("identity_secret_rotation_required")),
            "secret_backend": str(identity_audit.get("identity_secret_backend") or "").strip(),
            "action_count": max(int(identity_audit.get("action_count") or 0), 0),
            "blocked_action_count": max(int(identity_audit.get("blocked_action_count") or 0), 0),
        },
        "notes": list(identity_audit.get("notes") or []),
        "recommendations": list(identity_audit.get("recommendations") or []),
    }


def _build_workflow_release_component(
    *,
    dispatch_preflight: Dict[str, Any],
    dispatch_audit: Dict[str, Any],
    live_ci_summary: Dict[str, Any],
    runner_baseline: Dict[str, Any],
) -> Dict[str, Any]:
    preflight_status = _normalize_status(dispatch_preflight.get("status"), default="warning")
    dispatch_status = _normalize_status(dispatch_audit.get("status"), default="skipped")
    live_ci_status = _normalize_status(live_ci_summary.get("status"), default="warning")
    runner_status = _normalize_status(runner_baseline.get("status"), default="warning")
    dispatch_run = dict(dispatch_audit.get("run") or {})
    github_workflow_observed = bool(
        str(live_ci_summary.get("invocation_source") or "").strip() == "github_workflow"
        or dispatch_run.get("id")
        or dispatch_run.get("number")
    )
    blocking_checks = _dedupe_text_list(
        [
            *list(dispatch_preflight.get("blocking_checks") or []),
            *list(dispatch_audit.get("blocking_checks") or []),
            *(["release_live_ci_gate_blocked"] if bool(live_ci_summary.get("ci_gate_should_block")) else []),
            *(
                ["dispatch_run_not_success"]
                if str(dispatch_run.get("status") or "").strip() == "completed"
                and str(dispatch_run.get("conclusion") or "").strip()
                and str(dispatch_run.get("conclusion") or "").strip() != "success"
                else []
            ),
        ]
    )
    warning_checks = _dedupe_text_list(
        [
            *list(dispatch_preflight.get("warning_checks") or []),
            *list(dispatch_audit.get("warning_checks") or []),
            *(["github_workflow_not_observed"] if not github_workflow_observed else []),
            *(
                ["dispatch_run_pending"]
                if str(dispatch_run.get("status") or "").strip() in {"queued", "in_progress"}
                else []
            ),
            *(["release_live_ci_warning"] if live_ci_status == "warning" else []),
            *(["runner_baseline_warning"] if runner_status == "warning" else []),
        ]
    )
    status = "blocked" if blocking_checks else ("warning" if warning_checks else "passed")
    recommendations = list(dispatch_preflight.get("recommendations") or []) + list(dispatch_audit.get("recommendations") or [])
    if not github_workflow_observed:
        recommendations.append(
            "恢复 GitHub 认证后触发真实 .github/workflows/release-live-gates.yml，并保留第一份 github_workflow summary。"
        )
    if bool(live_ci_summary.get("ci_gate_should_block")):
        recommendations.append(
            "先修复 release_live_ci_summary 的 blocking_checks，再把真实 GitHub workflow 当成交付级 release 证据。"
        )
    summary = (
        f"preflight={preflight_status} / dispatch={dispatch_status} / "
        f"run={str(dispatch_run.get('status') or '-').strip() or '-'} / "
        f"live_ci={live_ci_status} / source={live_ci_summary.get('invocation_source') or '-'}"
    )
    return {
        "component_id": "workflow_release",
        "label": "Self-Hosted Workflow Release",
        "required": True,
        "status": status,
        "summary": summary,
        "blocking_checks": blocking_checks,
        "warning_checks": warning_checks,
        "paths": {
            "dispatch_audit_path": str(dispatch_audit.get("path") or "").strip(),
            "summary_path": str(live_ci_summary.get("path") or "").strip(),
            "summary_markdown_path": str(live_ci_summary.get("summary_markdown_path") or "").strip(),
            "runner_baseline_path": str(runner_baseline.get("path") or "").strip(),
            "workflow_path": str(dispatch_preflight.get("workflow_path") or "").strip(),
        },
        "details": {
            "preflight_status": preflight_status,
            "dispatch_status": dispatch_status,
            "dispatch_run_status": str(dispatch_run.get("status") or "").strip(),
            "dispatch_run_conclusion": str(dispatch_run.get("conclusion") or "").strip(),
            "github_workflow_observed": github_workflow_observed,
            "ci_gate_status": str(live_ci_summary.get("ci_gate_status") or "").strip(),
            "ci_gate_should_block": bool(live_ci_summary.get("ci_gate_should_block")),
            "invocation_source": str(live_ci_summary.get("invocation_source") or "").strip(),
            "runner_baseline_status": runner_status,
            "token_present": bool(dispatch_preflight.get("token_present")),
            "workflow_dispatch_enabled": bool(dispatch_preflight.get("workflow_dispatch_enabled")),
        },
        "notes": [],
        "recommendations": _dedupe_text_list(recommendations),
    }


def _build_distribution_delivery_component(distribution_bundle: Dict[str, Any]) -> Dict[str, Any]:
    status = _normalize_status(distribution_bundle.get("status"), default="warning")
    signing_status = _normalize_status(distribution_bundle.get("signing_handoff_status"), default="skipped")
    publish_status = _normalize_status(distribution_bundle.get("publish_handoff_status"), default="skipped")
    receipts_status = _normalize_status(distribution_bundle.get("publish_receipts_status"), default="skipped")
    signing_required = distribution_bundle.get("delivery_signing_required") is not False
    summary = (
        f"delivery={distribution_bundle.get('delivery_status') or '-'} / "
        f"signing={signing_status} / "
        f"publish={publish_status} / "
        f"receipts={receipts_status}"
    )
    blocking_checks = []
    warning_checks = []
    if status == "blocked":
        blocking_checks.append("distribution_bundle_blocked")
    if status == "warning":
        warning_checks.append("distribution_bundle_incomplete")
    if signing_status == "blocked":
        blocking_checks.append("distribution_signing_handoff_blocked")
    elif signing_required and signing_status in {"warning", "skipped"}:
        warning_checks.append("distribution_signing_handoff_incomplete")
    if publish_status == "blocked":
        blocking_checks.append("distribution_publish_handoff_blocked")
    elif publish_status in {"warning", "skipped"}:
        warning_checks.append("distribution_publish_handoff_incomplete")
    if receipts_status == "blocked":
        blocking_checks.append("distribution_publish_receipts_blocked")
    elif receipts_status in {"warning", "skipped"}:
        warning_checks.append("distribution_publish_receipts_incomplete")
    component_status = "blocked" if blocking_checks else ("warning" if warning_checks else status)
    return {
        "component_id": "distribution_delivery",
        "label": "External Distribution Delivery",
        "required": True,
        "status": component_status,
        "ready": component_status == "passed",
        "follow_up_required": component_status != "passed",
        "summary": summary,
        "blocking_checks": blocking_checks,
        "warning_checks": warning_checks,
        "paths": {
            "report_path": str(distribution_bundle.get("report_path") or "").strip(),
            "distribution_manifest_path": str(distribution_bundle.get("distribution_manifest_path") or "").strip(),
            "signing_handoff_manifest_path": str(distribution_bundle.get("signing_handoff_manifest_path") or "").strip(),
            "publish_handoff_manifest_path": str(distribution_bundle.get("publish_handoff_manifest_path") or "").strip(),
            "publish_receipts_manifest_path": str(distribution_bundle.get("publish_receipts_manifest_path") or "").strip(),
        },
        "details": {
            "delivery_profile_id": str(distribution_bundle.get("delivery_profile_id") or "").strip(),
            "delivery_primary_installer": str(distribution_bundle.get("delivery_primary_installer") or "").strip(),
            "delivery_signing_required": signing_required,
            "delivery_signing_mode": str(distribution_bundle.get("delivery_signing_mode") or "").strip(),
            "signing_handoff_status": signing_status,
            "publish_handoff_status": publish_status,
            "publish_receipts_status": receipts_status,
            "publish_receipts_target_count": int(distribution_bundle.get("publish_receipts_target_count") or 0),
            "publish_receipts_recorded_target_count": int(distribution_bundle.get("publish_receipts_recorded_target_count") or 0),
            "publish_receipts_completed_targets": list(distribution_bundle.get("publish_receipts_completed_targets") or []),
            "publish_receipts_missing_targets": list(distribution_bundle.get("publish_receipts_missing_targets") or []),
            "publish_receipts_failed_targets": list(distribution_bundle.get("publish_receipts_failed_targets") or []),
        },
        "notes": list(distribution_bundle.get("notes") or []),
        "recommendations": list(distribution_bundle.get("recommendations") or []),
    }


def _build_next_actions(
    *,
    target_channel: str,
    target_environment: str,
    components: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    lookup = {str(item.get("component_id") or ""): item for item in components}
    actions = [
        {
            "action_id": "external_identity_boundary",
            "label": "完成外部 identity/session/secret rotation 收口",
            "status": str(lookup["identity_boundary"].get("status") or "warning"),
            "owner_hint": "ops/security",
            "dependency": "external_identity_provider",
            "eta": "before_release_promotion",
            "validation_method": "identity_handoff_manifest_and_request_auth_identity_audit",
            "blockers": _action_blockers(lookup["identity_boundary"]),
            "summary": str(lookup["identity_boundary"].get("summary") or ""),
            "entrypoint": (
                "python .\\tools\\export_release_request_auth_identity_handoff.py "
                f"--project-root . --runtime-root . --channel {target_channel} --target-environment {target_environment}"
            ),
        },
        {
            "action_id": "self_hosted_release_workflow",
            "label": "在固定 self-hosted Windows runner 上跑通真实 release-live-gates",
            "status": str(lookup["workflow_release"].get("status") or "warning"),
            "owner_hint": "release_engineering",
            "dependency": "github_actions_self_hosted_windows_runner",
            "eta": "before_release_gate",
            "validation_method": "release_live_dispatch_audit_and_release_live_ci_summary",
            "blockers": _action_blockers(lookup["workflow_release"]),
            "summary": str(lookup["workflow_release"].get("summary") or ""),
            "entrypoint": (
                "python .\\tools\\dispatch_release_live_gates.py "
                f"--target-channel {target_channel} --target-environment {target_environment} --wait"
            ),
        },
        {
            "action_id": "external_distribution_delivery",
            "label": "把 distribution 链推进到真实签名安装器与渠道分发",
            "status": str(lookup["distribution_delivery"].get("status") or "warning"),
            "owner_hint": "ops/release_manager",
            "dependency": "external_signing_and_publish_targets",
            "eta": "before_public_distribution",
            "validation_method": "distribution_signing_publish_handoff_and_publish_receipts",
            "blockers": _action_blockers(lookup["distribution_delivery"]),
            "summary": str(lookup["distribution_delivery"].get("summary") or ""),
            "entrypoint": (
                "python .\\tools\\export_release_distribution_publish_handoff.py "
                f"--project-root . --runtime-root . --channel {target_channel} --target-environment {target_environment}"
            ),
        },
    ]
    actions.extend(_build_distribution_delivery_next_actions(lookup["distribution_delivery"], target_channel, target_environment))
    return actions


def _build_distribution_delivery_next_actions(
    component: Dict[str, Any],
    target_channel: str,
    target_environment: str,
) -> List[Dict[str, Any]]:
    details = dict(component.get("details") or {})
    summary = str(component.get("summary") or "")
    status_specs = [
        (
            "distribution_signing_handoff",
            "完成外部签名 handoff intake",
            "signing_handoff_status",
            "signing_provider_or_release_manager",
            "distribution_signing_handoff_manifest",
            "python .\\tools\\export_release_distribution_signing_handoff.py "
            f"--project-root . --runtime-root . --channel {target_channel} --target-environment {target_environment}",
        ),
        (
            "distribution_publish_handoff",
            "完成外部分发 publish handoff intake",
            "publish_handoff_status",
            "publish_targets",
            "distribution_publish_handoff_manifest",
            "python .\\tools\\export_release_distribution_publish_handoff.py "
            f"--project-root . --runtime-root . --channel {target_channel} --target-environment {target_environment}",
        ),
        (
            "distribution_publish_receipts",
            "回写外部分发 publish receipts",
            "publish_receipts_status",
            "publish_target_receipts",
            "publish_receipts_manifest_and_target_receipts",
            "python .\\tools\\record_release_distribution_publish_receipt.py "
            f"--project-root . --runtime-root . --channel {target_channel} --target-environment {target_environment}",
        ),
    ]
    actions = []
    for action_id, label, status_key, dependency, validation, entrypoint in status_specs:
        if action_id == "distribution_signing_handoff" and not bool(details.get("delivery_signing_required")):
            continue
        status = _normalize_status(details.get(status_key), default="skipped")
        if status == "passed":
            continue
        blockers = [f"{action_id}_{'blocked' if status == 'blocked' else 'incomplete'}"]
        if action_id == "distribution_publish_receipts":
            missing = [str(item).strip() for item in list(details.get("publish_receipts_missing_targets") or []) if str(item).strip()]
            failed = [str(item).strip() for item in list(details.get("publish_receipts_failed_targets") or []) if str(item).strip()]
            blockers.extend([f"missing_receipt:{item}" for item in missing])
            blockers.extend([f"failed_receipt:{item}" for item in failed])
        actions.append({
            "action_id": action_id,
            "label": label,
            "status": status,
            "owner_hint": "ops/release_manager",
            "dependency": dependency,
            "eta": "before_public_distribution",
            "validation_method": validation,
            "blockers": _dedupe_text_list(blockers),
            "summary": summary,
            "entrypoint": entrypoint,
        })
    return actions


def _action_blockers(component: Dict[str, Any]) -> List[str]:
    blockers = list(component.get("blocking_checks") or [])
    if blockers:
        return _dedupe_text_list(blockers)
    if str(component.get("status") or "").strip().lower() == "passed":
        return []
    return _dedupe_text_list(component.get("warning_checks") or [])


def _load_release_distribution_bundle(
    project_root: Path,
    runtime_root: Path,
    *,
    target_channel: str,
    target_environment: str,
) -> Dict[str, Any]:
    relative_report_path = default_release_distribution_report_path(target_channel=target_channel)
    for root in (project_root, runtime_root):
        candidate = (root / relative_report_path).resolve()
        if not candidate.exists():
            continue
        payload = _read_json(candidate)
        if isinstance(payload, dict):
            normalized = normalize_release_distribution_bundle(payload)
            normalized["report_path"] = _display_path(candidate, project_root, runtime_root)
            normalized["report_exists"] = True
            return normalized
    normalized = normalize_release_distribution_bundle(
        build_release_distribution_bundle(
            project_root,
            runtime_root=runtime_root,
            target_channel=target_channel,
            target_environment=target_environment,
        )
    )
    if str(normalized.get("report_path") or "").strip():
        normalized["report_path"] = _display_text_path(str(normalized.get("report_path") or "").strip(), project_root, runtime_root)
    return normalized


def _load_release_live_dispatch_audit(project_root: Path, runtime_root: Path, *, artifact_dir: str) -> Dict[str, Any]:
    for root in (project_root, runtime_root):
        payload = load_release_live_dispatch_audit(root, artifact_dir=artifact_dir)
        if isinstance(payload, dict) and payload:
            normalized = normalize_release_live_dispatch_audit(payload)
            normalized["path"] = _display_text_path(str(normalized.get("path") or "").strip(), project_root, runtime_root)
            return normalized
    return normalize_release_live_dispatch_audit({})


def _load_release_live_runner_baseline(project_root: Path, runtime_root: Path, *, target_channel: str) -> Dict[str, Any]:
    relative_report_path = default_release_live_runner_baseline_report_path(target_channel=target_channel)
    default_status = "blocked" if target_channel == "release" else "warning"
    for root in (project_root, runtime_root):
        candidate = (root / relative_report_path).resolve()
        payload = _read_json(candidate)
        if not isinstance(payload, dict):
            continue
        recommendations = _clean_text_list(payload.get("recommendations"))
        return {
            "status": _normalize_status(payload.get("status"), default=default_status),
            "summary": str(payload.get("summary") or "").strip() or "release live runner baseline loaded",
            "path": _display_path(candidate, project_root, runtime_root),
            "runner_profile_id": str(payload.get("runner_profile_id") or "").strip(),
            "runner_name": str(payload.get("runner_name") or "").strip(),
            "runner_labels": _clean_text_list(payload.get("declared_runner_labels")),
            "blocking_checks": _clean_text_list(payload.get("blocking_checks")),
            "warning_checks": _clean_text_list(payload.get("warning_checks")),
            "recommendations": recommendations,
        }
    return {
        "status": default_status,
        "summary": "release live runner baseline report missing",
        "path": "",
        "runner_profile_id": "",
        "runner_name": "",
        "runner_labels": [],
        "blocking_checks": ["missing_release_live_runner_baseline"] if default_status == "blocked" else [],
        "warning_checks": ["missing_release_live_runner_baseline"] if default_status != "blocked" else [],
        "recommendations": [
            "先生成 release_live_runner_baseline_<channel>.json，确认 self-hosted Windows runner 已具备真实 release gate 依赖。"
        ],
    }


def _load_release_live_ci_summary(project_root: Path, runtime_root: Path, *, artifact_dir: str) -> Dict[str, Any]:
    normalized_artifact_dir = str(artifact_dir or DEFAULT_RELEASE_DELIVERY_ARTIFACT_DIR).strip() or DEFAULT_RELEASE_DELIVERY_ARTIFACT_DIR
    for root in (project_root, runtime_root):
        candidate = (root / normalized_artifact_dir / "release_live_ci_summary.json").resolve()
        payload = _read_json(candidate)
        if not isinstance(payload, dict):
            continue
        ci_gate = dict(payload.get("ci_gate") or {})
        runtime_gates = dict(payload.get("runtime_gates") or {})
        invocation = dict(payload.get("invocation") or {})
        report_files = dict(payload.get("report_files") or {})
        summary_markdown_name = str(report_files.get("summary_markdown") or "release_live_ci_summary.md").strip() or "release_live_ci_summary.md"
        summary_markdown_path = candidate.parent / summary_markdown_name
        return {
            "status": _normalize_status(payload.get("status") or ci_gate.get("status"), default="warning"),
            "summary": str(payload.get("summary") or "").strip()
            or (
                f"ci_gate={_normalize_status(ci_gate.get('status'), default='warning')} / "
                f"source={str(invocation.get('source') or '').strip() or '-'}"
            ),
            "path": _display_path(candidate, project_root, runtime_root),
            "summary_markdown_path": _display_path(summary_markdown_path, project_root, runtime_root),
            "ci_gate_status": _normalize_status(ci_gate.get("status"), default="warning"),
            "ci_gate_should_block": bool(ci_gate.get("should_block")),
            "invocation_source": str(invocation.get("source") or "").strip(),
            "release_build_id": str(payload.get("release_build_id") or "").strip(),
            "release_version": str(payload.get("release_version") or "").strip(),
            "runner_baseline_status": str(runtime_gates.get("release_live_runner_baseline_status") or "").strip(),
            "distribution_bundle_status": str(runtime_gates.get("distribution_bundle_status") or "").strip(),
            "distribution_signing_handoff_status": str(runtime_gates.get("distribution_signing_handoff_status") or "").strip(),
            "distribution_publish_handoff_status": str(runtime_gates.get("distribution_publish_handoff_status") or "").strip(),
            "distribution_publish_receipts_status": str(runtime_gates.get("distribution_publish_receipts_status") or "").strip(),
            "identity_handoff_status": str(runtime_gates.get("identity_handoff_status") or "").strip(),
        }
    return {
        "status": "warning",
        "summary": "release_live_ci_summary.json not found",
        "path": "",
        "summary_markdown_path": "",
        "ci_gate_status": "warning",
        "ci_gate_should_block": False,
        "invocation_source": "",
        "release_build_id": "",
        "release_version": "",
        "runner_baseline_status": "",
        "distribution_bundle_status": "",
        "distribution_signing_handoff_status": "",
        "distribution_publish_handoff_status": "",
        "distribution_publish_receipts_status": "",
        "identity_handoff_status": "",
    }


def _read_json(path: Path) -> Dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _resolve_runtime_output_path(runtime_root: Path, raw_path: str) -> Path:
    candidate = Path(str(raw_path or "").strip())
    if candidate.is_absolute():
        return candidate
    return runtime_root / candidate


def _display_path(path: Path, *roots: Path) -> str:
    resolved = path.resolve()
    for root in roots:
        try:
            return resolved.relative_to(root.resolve()).as_posix()
        except Exception:
            continue
    return str(resolved)


def _display_text_path(value: str, *roots: Path) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    candidate = Path(text)
    if candidate.is_absolute():
        return _display_path(candidate, *roots)
    for root in roots:
        combined = (root / candidate).resolve()
        if combined.exists():
            return _display_path(combined, *roots)
    return text.replace("\\", "/")


def _normalize_status(value: Any, *, default: str) -> str:
    normalized = str(value or "").strip().lower()
    return normalized if normalized in _STATUS_VALUES else default


def _worst_status(statuses: Iterable[Any], *, default: str = "warning") -> str:
    priorities = {"blocked": 3, "warning": 2, "passed": 1, "skipped": 0}
    worst = default
    worst_priority = priorities.get(default, 2)
    for raw_status in statuses:
        status = _normalize_status(raw_status, default="warning")
        priority = priorities.get(status, 2)
        if priority > worst_priority:
            worst = status
            worst_priority = priority
    return worst


def _clean_text_list(value: Any) -> List[str]:
    if isinstance(value, str):
        parts = value.replace("\r", "\n").replace(",", "\n").replace(";", "\n").split("\n")
    elif isinstance(value, (list, tuple, set)):
        parts = list(value)
    else:
        return []
    return _dedupe_text_list(parts)


def _dedupe_text_list(values: Iterable[Any]) -> List[str]:
    items: List[str] = []
    seen: set[str] = set()
    for raw in values:
        text = str(raw or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        items.append(text)
    return items

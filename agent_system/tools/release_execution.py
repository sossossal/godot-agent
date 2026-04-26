"""
Release execution controller.

P18 converts promotion intent into governed rollout state.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from agent_system.contracts import (
    RELEASE_EXECUTION_STATUS_SCHEMA_VERSION,
    normalize_release_execution_status,
)
from agent_system.tools.release_access_policy import authorize_release_operation
from agent_system.tools.release_distribution import (
    build_release_distribution_bundle,
    build_release_distribution_bundle_report_lines,
)
from agent_system.tools.release_delivery_readiness import (
    build_release_delivery_readiness,
    build_release_delivery_readiness_report_lines,
)
from agent_system.tools.release_promotion import (
    _bind_full_live_validation_to_release,
    _build_clean_machine_bootstrap_report_lines,
    _build_full_live_validation_report_lines,
    _build_release_distribution_publish_receipts_summary,
    _display_path,
    _build_release_live_runner_baseline_report_lines,
    _extract_full_live_validation_artifact,
    _extract_release_live_runner_baseline_artifact,
    _load_clean_machine_bootstrap_report,
    _load_full_live_validation_report,
    _load_release_live_runner_baseline_report,
    _release_distribution_publish_receipts_follow_up_required,
    build_release_promotion_plan,
)
from agent_system.tools.release_candidate import DEFAULT_RELEASE_MANIFEST_PATH
from agent_system.tools.release_promotion_history import (
    DEFAULT_RELEASE_PROMOTION_HISTORY_PATH,
    build_release_promotion_history,
)
from agent_system.tools.release_request_auth import (
    build_release_request_auth_identity_audit,
    build_release_request_auth_identity_audit_report_lines,
    build_release_request_auth_posture,
    build_release_request_auth_posture_report_lines,
    build_release_request_auth_rotation_audit,
    build_release_request_auth_rotation_audit_report_lines,
)
from agent_system.tools.release_live_event_stream import (
    build_release_live_event_stream_report_lines,
)
from agent_system.tools.release_runtime_assembly import (
    build_release_runtime_assembly_report_lines,
)
from tools.dispatch_release_live_gates import (
    build_release_live_dispatch_audit_report_lines,
    load_release_live_dispatch_audit,
)
from agent_system.validations import ProjectLayoutValidator


DEFAULT_RELEASE_EXECUTION_STATUS_PATH = "deployment/release_execution_status.json"
DEFAULT_RELEASE_CHANNELS_PATH = "deployment/release_channels.json"
_EXECUTION_OPERATIONS = {"dry_run", "canary", "full_rollout", "rollback"}
_ROLLOUT_STAGES = {"idle", "dry_run", "canary", "full_rollout", "rolled_back"}
_READY_PROMOTION_DECISIONS = {"approved", "promoted"}
_QUALITY_GATE_STATUSES = {"passed", "warning", "blocked", "skipped"}


def build_release_execution_status(
    project_root: str | Path,
    runtime_root: Optional[str | Path] = None,
    *,
    status_path: str = "",
    channels_path: str = "",
    history_path: str = "",
    operation: str = "",
    target_channel: str = "",
    executed_by: str = "",
    offset: int = 0,
    limit: int = 20,
) -> Dict[str, Any]:
    resolved_project_root, resolved_runtime_root, resolved_status_path, resolved_channels_path, resolved_history_path = _resolve_execution_paths(
        project_root,
        runtime_root=runtime_root,
        status_path=status_path,
        channels_path=channels_path,
        history_path=history_path,
    )
    layout_validator = ProjectLayoutValidator(project_root=resolved_project_root, runtime_root=resolved_runtime_root)
    status_layout = layout_validator.validate_managed_path(resolved_status_path, "release_execution_status_manifest")
    channels_layout = layout_validator.validate_managed_path(resolved_channels_path, "release_channel_manifest")

    normalized_operation = _normalize_operation(operation, allow_empty=True)
    normalized_target_channel = str(target_channel or "").strip().lower()
    normalized_executor = str(executed_by or "").strip()
    raw_status_manifest, status_error = _load_manifest(resolved_status_path, default_key="executions")
    raw_channels_manifest, channels_error = _load_manifest(resolved_channels_path, default_key="channels")
    raw_items = [dict(item) for item in list(raw_status_manifest.get("executions") or []) if isinstance(item, dict)]
    raw_channels = [dict(item) for item in list(raw_channels_manifest.get("channels") or []) if isinstance(item, dict)]

    filtered_items = [
        item for item in raw_items
        if (not normalized_operation or str(item.get("operation") or "").strip().lower() == normalized_operation)
        and (not normalized_target_channel or str(item.get("target_channel") or "").strip().lower() == normalized_target_channel)
        and (not normalized_executor or str(item.get("executed_by") or "").strip() == normalized_executor)
    ]
    normalized_offset = max(int(offset or 0), 0)
    normalized_limit = max(int(limit or 20), 1)
    visible_items = filtered_items[normalized_offset:normalized_offset + normalized_limit]
    next_offset = normalized_offset + normalized_limit if normalized_offset + normalized_limit < len(filtered_items) else None
    prev_offset = normalized_offset - normalized_limit if normalized_offset > 0 else None
    report_target_channel = _resolve_clean_machine_bootstrap_target(
        normalized_target_channel,
        visible_items,
        filtered_items,
        raw_items,
        raw_channels,
    )
    clean_machine_bootstrap = _load_clean_machine_bootstrap_report(
        resolved_project_root,
        resolved_runtime_root,
        target_channel=report_target_channel,
    )
    release_live_runner_baseline = _load_release_live_runner_baseline_report(
        resolved_project_root,
        resolved_runtime_root,
        target_channel=report_target_channel,
    )
    full_live_validation = _load_full_live_validation_report(
        resolved_project_root,
        resolved_runtime_root,
        target_channel=report_target_channel,
    )
    full_live_validation = _bind_full_live_validation_to_release(
        full_live_validation,
        _resolve_full_live_validation_release_binding(
            resolved_project_root,
            resolved_runtime_root,
            report_target_channel,
            visible_items,
            filtered_items,
            raw_items,
            raw_channels,
        ),
        target_channel=report_target_channel,
        project_root=resolved_project_root,
        runtime_root=resolved_runtime_root,
    )
    release_live_ci_summary = _load_release_live_ci_summary(
        resolved_project_root,
        resolved_runtime_root,
        target_channel=report_target_channel,
    )
    request_auth_target_environment = _resolve_request_auth_target_environment(visible_items, filtered_items, raw_items, raw_channels)
    request_auth_posture = build_release_request_auth_posture(
        resolved_project_root,
        runtime_root=resolved_runtime_root,
        action="release_execution",
        target_channel=report_target_channel,
        target_environment=request_auth_target_environment,
    )
    request_auth_rotation_audit = build_release_request_auth_rotation_audit(
        resolved_project_root,
        runtime_root=resolved_runtime_root,
        target_channel=report_target_channel,
        target_environment=request_auth_target_environment,
    )
    request_auth_identity_audit = build_release_request_auth_identity_audit(
        resolved_project_root,
        runtime_root=resolved_runtime_root,
        target_channel=report_target_channel,
        target_environment=request_auth_target_environment,
    )
    release_distribution_bundle = build_release_distribution_bundle(
        resolved_project_root,
        runtime_root=resolved_runtime_root,
        target_channel=report_target_channel,
        target_environment=request_auth_target_environment,
        release_manifest_path=DEFAULT_RELEASE_MANIFEST_PATH,
    )
    release_delivery_readiness = build_release_delivery_readiness(
        resolved_project_root,
        runtime_root=resolved_runtime_root,
        target_channel=report_target_channel,
        target_environment=request_auth_target_environment,
    )
    latest_authorization = _extract_latest_execution_authorization(visible_items, filtered_items, raw_items)

    notes = []
    recommendations = []
    if not status_layout["passed"]:
        notes.append("release execution status path 未通过文件树规范校验。")
        recommendations.append("将 execution status 固定落到 deployment/release_execution_status.json。")
    if not channels_layout["passed"]:
        notes.append("release channel manifest path 未通过文件树规范校验。")
        recommendations.append("将 release channel manifest 固定落到 deployment/release_channels.json。")
    if status_error:
        notes.append(f"execution status manifest 解析失败: {status_error}")
        recommendations.append("先修复 release execution status manifest 的 JSON 格式。")
    if channels_error:
        notes.append(f"release channel manifest 解析失败: {channels_error}")
        recommendations.append("先修复 release channel manifest 的 JSON 格式。")
    if not raw_items and not status_error:
        notes.append("当前还没有 release execution 记录。")
        recommendations.append("先执行 dry run、canary 或 full rollout，把 rollout 状态沉淀到 execution ledger。")
    if not raw_channels and not channels_error:
        notes.append("当前还没有 active release channel 绑定。")
        recommendations.append("执行 canary 或 full rollout 后再检查 channel binding。")
    if str(clean_machine_bootstrap.get("status") or "").strip().lower() in {"warning", "blocked"}:
        notes.append(f"clean machine bootstrap: {clean_machine_bootstrap.get('summary') or 'missing'}")
        recommendations.append("补跑 clean machine bootstrap，并保留 logs/reports/clean_machine_bootstrap.json 供 release execution / report 复核。")
    if str(release_live_runner_baseline.get("status") or "").strip().lower() in {"warning", "blocked"}:
        notes.append(f"release live runner baseline: {release_live_runner_baseline.get('summary') or 'missing'}")
        recommendations.extend(list(release_live_runner_baseline.get("details", {}).get("recommendations") or []))
    if str(full_live_validation.get("status") or "").strip().lower() in {"warning", "blocked"}:
        notes.append(f"full live validation: {full_live_validation.get('summary') or 'missing'}")
        recommendations.append("补跑 full live validation，并保留 logs/reports/full_live_validation.json 供 release execution / report 复核。")
    release_live_ci_gate = dict(release_live_ci_summary.get("details", {}).get("ci_gate") or {})
    release_live_ci_signoffs = dict(release_live_ci_summary.get("details", {}).get("human_signoffs") or {})
    if str(release_live_ci_summary.get("status") or "").strip().lower() in {"warning", "blocked"}:
        notes.append(f"release live ci summary: {release_live_ci_summary.get('summary') or 'missing'}")
    if bool(release_live_ci_gate.get("should_block")):
        recommendations.append(
            "补跑 tools/run_release_live_gates_locally.ps1 或 self-hosted Windows runner 上的 .github/workflows/release-live-gates.yml，并保留 logs/reports/release_live_ci/release_live_ci_summary.json。"
        )
    missing_signoffs = list(release_live_ci_signoffs.get("missing_signoffs") or [])
    if missing_signoffs:
        recommendations.append(f"补齐 release live CI 人工 signoff: {', '.join(missing_signoffs)}。")
    if str(latest_authorization.get("status") or "").strip().lower() in {"warning", "blocked"}:
        notes.append(f"release authorization: {latest_authorization.get('reason') or latest_authorization.get('status')}")
        recommendations.append("更新 deployment/release_access_policy.json，并确认 executed_by 与 actor role 绑定后再执行高风险发布动作。")
    if str(request_auth_posture.get("status") or "").strip().lower() in {"warning", "blocked"}:
        notes.append(f"release request auth posture: {request_auth_posture.get('summary') or request_auth_posture.get('status')}")
        recommendations.extend(list(request_auth_posture.get("recommendations") or []))
    if str(request_auth_rotation_audit.get("status") or "").strip().lower() in {"warning", "blocked"}:
        notes.append(
            f"release request auth rotation audit: {request_auth_rotation_audit.get('summary') or request_auth_rotation_audit.get('status')}"
        )
        recommendations.extend(list(request_auth_rotation_audit.get("recommendations") or []))
    if str(request_auth_identity_audit.get("status") or "").strip().lower() in {"warning", "blocked"}:
        notes.append(
            f"release request auth identity audit: {request_auth_identity_audit.get('summary') or request_auth_identity_audit.get('status')}"
        )
        recommendations.extend(list(request_auth_identity_audit.get("recommendations") or []))
    if str(release_distribution_bundle.get("status") or "").strip().lower() in {"warning", "blocked"}:
        notes.append(
            f"release distribution bundle: {release_distribution_bundle.get('summary') or release_distribution_bundle.get('status')}"
        )
        recommendations.extend(list(release_distribution_bundle.get("recommendations") or []))
    if str(release_delivery_readiness.get("status") or "").strip().lower() in {"warning", "blocked"}:
        notes.append(f"release delivery readiness: {release_delivery_readiness.get('summary') or release_delivery_readiness.get('status')}")
        recommendations.extend(list(release_delivery_readiness.get("recommendations") or []))
    if _release_distribution_publish_receipts_follow_up_required(release_distribution_bundle):
        notes.append(
            f"distribution publish receipts: {_build_release_distribution_publish_receipts_summary(release_distribution_bundle)}"
        )
        if list(release_distribution_bundle.get("publish_receipts_failed_targets") or []):
            recommendations.append(
                "修复失败的 publish target，然后重新写回 release_distribution_publish_receipts/... 下的 receipt，避免 release execution 只看到部分外部分发结果。"
            )
        if (
            int(release_distribution_bundle.get("publish_receipts_recorded_target_count") or 0) > 0
            and bool(list(release_distribution_bundle.get("publish_receipts_missing_targets") or []))
        ):
            recommendations.append(
                "补齐剩余 publish target 的 receipt，确保 release execution / review bundle 能看到完整的外部分发完成状态。"
            )
        if (
            bool(release_distribution_bundle.get("publish_receipts_manifest_exists"))
            and not bool(release_distribution_bundle.get("publish_receipts_manifest_matches_current"))
        ):
            recommendations.append(
                "清理与当前 build/version/channel 不匹配的 publish_receipts manifest，然后重新记录当前发布的 receipt。"
            )

    return normalize_release_execution_status({
        "project_root": str(resolved_project_root),
        "runtime_root": str(resolved_runtime_root),
        "status_path": _relative_to_root(resolved_status_path, resolved_project_root),
        "channels_path": _relative_to_root(resolved_channels_path, resolved_project_root),
        "history_path": _relative_to_root(resolved_history_path, resolved_project_root),
        "status_exists": resolved_status_path.exists(),
        "channels_exist": resolved_channels_path.exists(),
        "operation_filter": normalized_operation,
        "target_channel_filter": normalized_target_channel,
        "executor_filter": normalized_executor,
        "offset": normalized_offset,
        "limit": normalized_limit,
        "execution_count": len(raw_items),
        "matched_execution_count": len(filtered_items),
        "visible_execution_count": len(visible_items),
        "channel_count": len(raw_channels),
        "active_channel_count": sum(1 for item in raw_channels if str(item.get("active_build_id") or "").strip()),
        "next_offset": next_offset,
        "prev_offset": prev_offset,
        "items": visible_items,
        "channel_entries": raw_channels,
        "clean_machine_bootstrap": clean_machine_bootstrap,
        "release_live_runner_baseline": release_live_runner_baseline,
        "full_live_validation": full_live_validation,
        "release_live_ci_summary": release_live_ci_summary,
        "runtime_assembly_snapshot": dict(release_live_ci_summary.get("details", {}).get("runtime_assembly") or {}),
        "request_auth_posture": request_auth_posture,
        "request_auth_rotation_audit": request_auth_rotation_audit,
        "request_auth_identity_audit": request_auth_identity_audit,
        "release_distribution_bundle": release_distribution_bundle,
        "release_delivery_readiness": release_delivery_readiness,
        "notes": notes,
        "recommendations": recommendations,
        "contract_versions": {
            "release_execution_status": RELEASE_EXECUTION_STATUS_SCHEMA_VERSION,
            "release_delivery_readiness": str(release_delivery_readiness.get("schema_version") or ""),
        },
    })


def build_release_execution_report(summary: Dict[str, Any] | None) -> str:
    normalized = normalize_release_execution_status(summary)
    latest_execution = dict(normalized.get("latest_execution") or {})
    clean_machine_bootstrap = dict(normalized.get("clean_machine_bootstrap") or {})
    release_live_runner_baseline = dict(normalized.get("release_live_runner_baseline") or {})
    full_live_validation = dict(normalized.get("full_live_validation") or {})
    release_live_ci_summary = dict(normalized.get("release_live_ci_summary") or {})
    review_followup_actions = list(normalized.get("review_followup_actions") or [])
    request_auth_posture = dict(normalized.get("request_auth_posture") or {})
    request_auth_rotation_audit = dict(normalized.get("request_auth_rotation_audit") or {})
    request_auth_identity_audit = dict(normalized.get("request_auth_identity_audit") or {})
    release_distribution_bundle = dict(normalized.get("release_distribution_bundle") or {})
    release_delivery_readiness = dict(normalized.get("release_delivery_readiness") or {})
    if not full_live_validation.get("path"):
        latest_plan_snapshot = dict(latest_execution.get("plan_snapshot") or {})
        full_live_validation = _extract_full_live_validation_artifact(dict(latest_plan_snapshot.get("evidence_bundle") or {}))
    if not release_live_runner_baseline.get("path"):
        latest_plan_snapshot = dict(latest_execution.get("plan_snapshot") or {})
        release_live_runner_baseline = _extract_release_live_runner_baseline_artifact(dict(latest_plan_snapshot.get("evidence_bundle") or {}))
    lines = [
        "# Release Execution Report",
        "",
        f"- Status: {normalized.get('status') or 'skipped'}",
        f"- Should Block: {bool(normalized.get('should_block'))}",
        f"- Target Filter: {normalized.get('target_channel_filter') or '-'}",
        f"- Operation Filter: {normalized.get('operation_filter') or '-'}",
        f"- Executor Filter: {normalized.get('executor_filter') or '-'}",
        f"- Execution Ledger: {normalized.get('visible_execution_count') or 0}/{normalized.get('matched_execution_count') or 0}",
        f"- Active Channels: {normalized.get('active_channel_count') or 0}/{normalized.get('channel_count') or 0}",
        f"- Status Path: {normalized.get('status_path') or '-'}",
        f"- Channels Path: {normalized.get('channels_path') or '-'}",
        (
            "- Latest Execution Delivery Readiness: "
            f"{latest_execution.get('release_delivery_readiness_status') or 'warning'} / "
            f"next_actions={latest_execution.get('release_delivery_readiness_next_action_count') or len(list(latest_execution.get('release_delivery_readiness_next_actions') or []))} / "
            f"summary={latest_execution.get('release_delivery_readiness_summary') or '-'}"
        ),
        (
            "- Distribution Publish Receipts: "
            f"{release_distribution_bundle.get('publish_receipts_status') or 'skipped'} / "
            f"completed={len(list(release_distribution_bundle.get('publish_receipts_completed_targets') or []))}/"
            f"{release_distribution_bundle.get('publish_receipts_target_count') or 0} / "
            f"missing={', '.join(list(release_distribution_bundle.get('publish_receipts_missing_targets') or [])) or 'none'} / "
            f"path={release_distribution_bundle.get('publish_receipts_manifest_path') or release_distribution_bundle.get('publish_receipts_dir') or '-'}"
        ),
        "",
        "## Clean Machine Bootstrap",
        *_build_clean_machine_bootstrap_report_lines(clean_machine_bootstrap),
        "",
        "## Release Live Runner Baseline",
        *_build_release_live_runner_baseline_report_lines(release_live_runner_baseline),
        "",
        "## Full Live Validation",
        *_build_full_live_validation_report_lines(full_live_validation),
        "",
        "## Release Live CI Summary",
        *_build_release_live_ci_summary_report_lines(release_live_ci_summary),
        "",
        "## Review Follow-up Actions",
    ]
    if review_followup_actions:
        for item in review_followup_actions:
            blockers = list(item.get("blockers") or [])
            lines.append(
                f"- {item.get('action_id') or '-'}: status={item.get('status') or 'warning'} "
                f"owner={item.get('owner_hint') or '-'} dependency={item.get('dependency') or '-'} "
                f"eta={item.get('eta') or '-'} validation={item.get('validation_method') or '-'}"
            )
            if blockers:
                lines.append(f"  - blockers={', '.join(blockers)}")
    else:
        lines.append("- none")
    latest_readiness_actions = [dict(item) for item in list(latest_execution.get("release_delivery_readiness_next_actions") or [])]
    lines.extend(["", "## Latest Execution Delivery Readiness Actions"])
    if latest_readiness_actions:
        for item in latest_readiness_actions:
            blockers = list(item.get("blockers") or [])
            lines.append(
                f"- {item.get('action_id') or '-'}: status={item.get('status') or 'warning'} "
                f"owner={item.get('owner_hint') or '-'} dependency={item.get('dependency') or '-'} "
                f"eta={item.get('eta') or '-'} validation={item.get('validation_method') or '-'}"
            )
            if blockers:
                lines.append(f"  - blockers={', '.join(blockers)}")
    else:
        lines.append("- none")
    lines.extend([
        "",
        "## Release Request Auth Posture",
        *build_release_request_auth_posture_report_lines(request_auth_posture),
        "",
        "## Release Request Auth Rotation Audit",
        *build_release_request_auth_rotation_audit_report_lines(request_auth_rotation_audit),
        "",
        "## Release Request Auth Identity Audit",
        *build_release_request_auth_identity_audit_report_lines(request_auth_identity_audit),
        "",
        "## Release Distribution Bundle",
        *build_release_distribution_bundle_report_lines(release_distribution_bundle),
        "",
        "## Release Delivery Readiness",
        *build_release_delivery_readiness_report_lines(release_delivery_readiness),
        "",
        "## Latest Execution",
    ])

    if latest_execution.get("execution_id"):
        authorization = dict(latest_execution.get("authorization") or {})
        request_auth = dict(latest_execution.get("request_auth") or {})
        lines.extend([
            f"- Execution ID: {latest_execution.get('execution_id') or '-'}",
            f"- Operation: {latest_execution.get('operation') or '-'}",
            f"- Target: {_build_execution_target_label(latest_execution)}",
            f"- Status: {latest_execution.get('execution_status') or 'skipped'} / should_block={bool(latest_execution.get('should_block'))}",
            f"- Rollout: {latest_execution.get('rollout_stage') or '-'} / {latest_execution.get('rollout_percentage') or 0}%",
            f"- Build: {latest_execution.get('release_build_id') or '-'} / version={latest_execution.get('release_version') or '-'} / channel={latest_execution.get('release_channel') or '-'}",
            f"- Public URL: {latest_execution.get('public_url') or '-'}",
            f"- Rollback URL: {latest_execution.get('rollback_url') or '-'}",
            f"- Executor: {latest_execution.get('executed_by') or '-'}",
            f"- Promotion Record: {latest_execution.get('promotion_record_id') or '-'} / decision={latest_execution.get('promotion_decision') or '-'}",
            (
                f"- Delivery Readiness: {latest_execution.get('release_delivery_readiness_status') or 'warning'} / "
                f"next_actions={latest_execution.get('release_delivery_readiness_next_action_count') or len(list(latest_execution.get('release_delivery_readiness_next_actions') or []))}"
            ),
            f"- Note: {latest_execution.get('note') or '-'}",
        ])
        if request_auth:
            lines.append(
                f"- Request Auth: {request_auth.get('status') or 'skipped'} / "
                f"mode={request_auth.get('mode') or '-'} / "
                f"source={request_auth.get('token_source') or '-'} / "
                f"token={request_auth.get('token_id') or '-'} / "
                f"session={request_auth.get('session_id') or '-'} / "
                f"issued_by={request_auth.get('issued_by') or '-'} / "
                f"issuer_registered={bool(request_auth.get('issuer_registered'))}"
            )
        if authorization:
            lines.append(
                f"- Authorization: {authorization.get('status') or 'skipped'} / "
                f"actor={authorization.get('actor_id') or '-'} / "
                f"roles={', '.join(list(authorization.get('actor_roles') or [])) or '-'} / "
                f"rule={authorization.get('matched_rule_id') or '-'}"
            )
    else:
        lines.append("- No execution records found.")

    checklist = list(latest_execution.get("checklist") or [])
    if checklist:
        lines.extend(["", "## Latest Checklist"])
        for item in checklist:
            lines.append(
                f"- [{item.get('status') or 'skipped'}] {item.get('label') or item.get('item_id') or 'item'}: {item.get('message') or '-'}"
            )

    channel_entries = [dict(item) for item in list(normalized.get("channel_entries") or [])]
    if channel_entries:
        lines.extend(["", "## Active Channels"])
        for item in channel_entries[:6]:
            lines.append(
                f"- {item.get('channel_id') or 'channel'}: status={item.get('binding_status') or 'skipped'} / "
                f"stage={item.get('rollout_stage') or '-'} / rollout={item.get('rollout_percentage') or 0}% / "
                f"active={item.get('active_public_url') or '-'} / rollback={item.get('rollback_public_url') or '-'}"
            )

    executions = [dict(item) for item in list(normalized.get("items") or [])]
    if executions:
        lines.extend(["", "## Recent Executions"])
        for item in executions[:8]:
            lines.append(
                f"- {item.get('execution_id') or 'execution'}: {item.get('operation') or '-'} / "
                f"{item.get('execution_status') or 'skipped'} / target={item.get('target_channel') or '-'} / "
                f"executor={item.get('executed_by') or '-'} / "
                f"delivery_readiness={item.get('release_delivery_readiness_status') or 'warning'} / "
                f"readiness_actions={item.get('release_delivery_readiness_next_action_count') or len(list(item.get('release_delivery_readiness_next_actions') or []))} / "
                f"public={item.get('public_url') or '-'}"
            )

    notes = list(normalized.get("notes") or [])
    if notes:
        lines.extend(["", "## Notes"])
        lines.extend(f"- {item}" for item in notes)

    recommendations = list(normalized.get("recommendations") or [])
    if recommendations:
        lines.extend(["", "## Recommendations"])
        lines.extend(f"- {item}" for item in recommendations)

    return "\n".join(lines).strip() + "\n"


def run_release_execution(
    project_root: str | Path,
    runtime_root: Optional[str | Path] = None,
    *,
    status_path: str = "",
    channels_path: str = "",
    history_path: str = "",
    target_channel: str = "staging",
    target_environment: str = "",
    release_manifest_path: str = "",
    approvers: Optional[List[str]] = None,
    providers: Optional[List[str]] = None,
    mode: str = "strict",
    fail_on_warnings: bool = False,
    operation: str = "dry_run",
    rollout_percentage: int = 10,
    executed_by: str = "",
    note: str = "",
    access_policy_path: str = "",
    request_auth: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    resolved_project_root, resolved_runtime_root, resolved_status_path, resolved_channels_path, resolved_history_path = _resolve_execution_paths(
        project_root,
        runtime_root=runtime_root,
        status_path=status_path,
        channels_path=channels_path,
        history_path=history_path,
    )
    _validate_execution_manifests(
        resolved_project_root,
        resolved_runtime_root,
        resolved_status_path,
        resolved_channels_path,
    )

    normalized_operation = _normalize_operation(operation)
    normalized_target_channel = str(target_channel or "staging").strip().lower() or "staging"
    normalized_rollout_percentage = _normalize_rollout_percentage(normalized_operation, rollout_percentage)
    normalized_executor = str(executed_by or "").strip()
    normalized_note = str(note or "").strip()
    normalized_request_auth = _normalize_request_auth_payload(
        request_auth,
        action="release_execution",
        target_channel=normalized_target_channel,
        target_environment=str(target_environment or "").strip(),
    )
    effective_mode = "strict" if normalized_target_channel == "release" else mode
    effective_fail_on_warnings = True if normalized_target_channel == "release" else fail_on_warnings
    plan = build_release_promotion_plan(
        resolved_project_root,
        runtime_root=resolved_runtime_root,
        target_channel=normalized_target_channel,
        target_environment=target_environment,
        release_manifest_path=release_manifest_path,
        approvers=approvers,
        providers=providers,
        mode=effective_mode,
        fail_on_warnings=effective_fail_on_warnings,
    )
    history = build_release_promotion_history(
        resolved_project_root,
        runtime_root=resolved_runtime_root,
        history_path=_relative_to_root(resolved_history_path, resolved_project_root),
        target_channel=normalized_target_channel,
        limit=10,
    )
    promotion_record = _select_promotion_record(history)
    release_delivery_readiness = dict(plan.get("release_delivery_readiness") or {})
    release_summary = dict(plan.get("release_candidate_checklist", {}).get("release_summary") or {})
    release_url = str(release_summary.get("release_url") or "").strip()
    versioned_release_url = str(release_summary.get("versioned_release_url") or "").strip()
    rollback_url = str(plan.get("rollback_rehearsal", {}).get("restore_target") or versioned_release_url or release_url).strip()
    public_url = release_url if normalized_operation == "full_rollout" else (versioned_release_url or release_url)
    authorization = authorize_release_operation(
        resolved_project_root,
        runtime_root=resolved_runtime_root,
        policy_path=access_policy_path,
        actor_id=normalized_executor,
        action="release_execution",
        target_channel=normalized_target_channel,
        target_environment=str(plan.get("target_environment") or target_environment or "").strip(),
        operation=normalized_operation,
        required=normalized_operation != "dry_run",
    )
    if normalized_operation != "dry_run" and str(authorization.get("status") or "") == "blocked":
        raise ValueError(f"release execution authorization failed: {authorization.get('reason') or 'blocked'}")

    checklist = [
        _item(
            "promotion_plan_ready",
            "Promotion Plan Ready",
            _status_from_plan(plan),
            f"promotion status={plan.get('status') or '-'} / should_block={bool(plan.get('should_block'))}",
            required=True,
            details={"blocking_checks": list(plan.get("blocking_checks") or [])},
        ),
        _build_promotion_history_item(promotion_record, normalized_operation),
        _item(
            "execution_actor",
            "Execution Actor",
            "passed" if normalized_executor else ("warning" if normalized_operation == "dry_run" else "blocked"),
            f"executed_by={normalized_executor or '-'}",
            required=normalized_operation != "dry_run",
        ),
        _item(
            "authorization_gate",
            "Release Authorization",
            str(authorization.get("status") or "skipped"),
            str(authorization.get("reason") or "authorization not evaluated"),
            required=bool(authorization.get("required")),
            details=dict(authorization),
        ),
        _item(
            "rollout_target",
            "Rollout Target",
            "passed" if public_url else "blocked",
            f"public_url={public_url or '-'} / versioned={versioned_release_url or '-'}",
            required=True,
            details={"release_url": release_url, "versioned_release_url": versioned_release_url},
        ),
        _item(
            "rollback_anchor",
            "Rollback Anchor",
            "passed" if rollback_url else "blocked",
            rollback_url or "缺少 rollback anchor",
            required=True,
        ),
        _item(
            "channel_binding",
            "Channel Binding",
            "skipped" if normalized_operation == "dry_run" else "passed",
            "dry run 不修改 channel binding" if normalized_operation == "dry_run" else f"{normalized_target_channel} rollout={normalized_rollout_percentage}%",
            required=False,
        ),
    ]
    should_block, execution_status, blocking_checks, warning_checks = _summarize_checklist(
        checklist,
        mode=effective_mode,
        fail_on_warnings=effective_fail_on_warnings,
    )

    raw_status_manifest, _ = _load_manifest(resolved_status_path, default_key="executions")
    raw_channels_manifest, _ = _load_manifest(resolved_channels_path, default_key="channels")
    executions = [dict(item) for item in list(raw_status_manifest.get("executions") or []) if isinstance(item, dict)]
    channels = [dict(item) for item in list(raw_channels_manifest.get("channels") or []) if isinstance(item, dict)]
    existing_channel = _find_channel_entry(channels, normalized_target_channel)
    updated_channel = None
    channel_binding_changed = False

    if not should_block and normalized_operation != "dry_run":
        updated_channel = _apply_channel_binding(
            existing_channel,
            target_channel=normalized_target_channel,
            target_environment=str(plan.get("target_environment") or target_environment or "").strip() or "staging",
            rollout_stage="full_rollout" if normalized_operation == "full_rollout" else "canary",
            rollout_percentage=normalized_rollout_percentage,
            execution_status=execution_status,
            release_manifest_path=str(plan.get("release_manifest_path") or release_manifest_path or "").strip(),
            release_build_id=str(release_summary.get("build_id") or "").strip(),
            release_version=str(release_summary.get("version") or "").strip(),
            release_channel=str(release_summary.get("channel") or "").strip(),
            public_url=public_url,
            versioned_release_url=versioned_release_url,
            rollback_url=str((existing_channel or {}).get("active_public_url") or rollback_url).strip(),
            executed_by=normalized_executor,
            note=normalized_note,
        )
        _upsert_channel_entry(channels, updated_channel)
        channel_binding_changed = True

    recorded_at = datetime.now(timezone.utc).isoformat()
    execution_record = {
        "execution_id": _build_execution_id(recorded_at, normalized_operation, normalized_target_channel),
        "recorded_at": recorded_at,
        "operation": normalized_operation,
        "target_channel": normalized_target_channel,
        "target_environment": str(plan.get("target_environment") or target_environment or "").strip() or "staging",
        "promotion_target_label": str(plan.get("promotion_target_label") or "").strip(),
        "execution_status": execution_status,
        "should_block": should_block,
        "executed_by": normalized_executor,
        "note": normalized_note,
        "rollout_stage": "full_rollout" if normalized_operation == "full_rollout" else ("canary" if normalized_operation == "canary" else "dry_run"),
        "rollout_percentage": normalized_rollout_percentage,
        "channel_binding_changed": channel_binding_changed,
        "authorization": authorization,
        "request_auth": normalized_request_auth,
        "release_manifest_path": str(plan.get("release_manifest_path") or release_manifest_path or "").strip(),
        "release_build_id": str(release_summary.get("build_id") or "").strip(),
        "release_version": str(release_summary.get("version") or "").strip(),
        "release_channel": str(release_summary.get("channel") or "").strip(),
        "public_url": public_url,
        "versioned_release_url": versioned_release_url,
        "rollback_url": str((updated_channel or existing_channel or {}).get("rollback_public_url") or rollback_url).strip(),
        "promotion_record_id": str(promotion_record.get("record_id") or "").strip(),
        "promotion_decision": str(promotion_record.get("decision") or "").strip(),
        "promotion_executor": str(promotion_record.get("executed_by") or "").strip(),
        "promotion_recorded_at": str(promotion_record.get("recorded_at") or "").strip(),
        "release_delivery_readiness_status": str(release_delivery_readiness.get("status") or "").strip(),
        "release_delivery_readiness_summary": str(release_delivery_readiness.get("summary") or "").strip(),
        "release_delivery_readiness_next_actions": list(release_delivery_readiness.get("next_actions") or []),
        "release_delivery_readiness_next_action_count": len(list(release_delivery_readiness.get("next_actions") or [])),
        "release_delivery_readiness_blocking_checks": list(release_delivery_readiness.get("blocking_checks") or []),
        "release_delivery_readiness_warning_checks": list(release_delivery_readiness.get("warning_checks") or []),
        "previous_public_url": str((existing_channel or {}).get("active_public_url") or "").strip(),
        "checklist": checklist,
        "blocking_checks": blocking_checks,
        "warning_checks": warning_checks,
        "plan_snapshot": plan,
    }
    if updated_channel is not None:
        updated_channel["last_execution_id"] = execution_record["execution_id"]
        _upsert_channel_entry(channels, updated_channel)
    executions.insert(0, execution_record)
    _write_manifest(resolved_status_path, {"schema_version": RELEASE_EXECUTION_STATUS_SCHEMA_VERSION, "executions": executions})
    _write_manifest(resolved_channels_path, {"schema_version": RELEASE_EXECUTION_STATUS_SCHEMA_VERSION, "channels": channels})
    return _build_result_payload(
        resolved_project_root,
        resolved_runtime_root,
        resolved_status_path,
        resolved_channels_path,
        resolved_history_path,
        normalized_target_channel,
        plan,
        history,
    )


def rollback_release_execution(
    project_root: str | Path,
    runtime_root: Optional[str | Path] = None,
    *,
    status_path: str = "",
    channels_path: str = "",
    history_path: str = "",
    target_channel: str = "staging",
    target_environment: str = "",
    release_manifest_path: str = "",
    approvers: Optional[List[str]] = None,
    providers: Optional[List[str]] = None,
    mode: str = "strict",
    fail_on_warnings: bool = False,
    executed_by: str = "",
    note: str = "",
    rollback_target_url: str = "",
    access_policy_path: str = "",
    request_auth: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    resolved_project_root, resolved_runtime_root, resolved_status_path, resolved_channels_path, resolved_history_path = _resolve_execution_paths(
        project_root,
        runtime_root=runtime_root,
        status_path=status_path,
        channels_path=channels_path,
        history_path=history_path,
    )
    _validate_execution_manifests(
        resolved_project_root,
        resolved_runtime_root,
        resolved_status_path,
        resolved_channels_path,
    )

    normalized_target_channel = str(target_channel or "staging").strip().lower() or "staging"
    normalized_executor = str(executed_by or "").strip()
    normalized_note = str(note or "").strip()
    normalized_request_auth = _normalize_request_auth_payload(
        request_auth,
        action="release_execution",
        target_channel=normalized_target_channel,
        target_environment=str(target_environment or "").strip(),
    )
    effective_mode = "strict" if normalized_target_channel == "release" else mode
    effective_fail_on_warnings = True if normalized_target_channel == "release" else fail_on_warnings
    plan = build_release_promotion_plan(
        resolved_project_root,
        runtime_root=resolved_runtime_root,
        target_channel=normalized_target_channel,
        target_environment=target_environment,
        release_manifest_path=release_manifest_path,
        approvers=approvers,
        providers=providers,
        mode=effective_mode,
        fail_on_warnings=effective_fail_on_warnings,
    )
    history = build_release_promotion_history(
        resolved_project_root,
        runtime_root=resolved_runtime_root,
        history_path=_relative_to_root(resolved_history_path, resolved_project_root),
        target_channel=normalized_target_channel,
        limit=10,
    )
    promotion_record = _select_promotion_record(history)
    release_delivery_readiness = dict(plan.get("release_delivery_readiness") or {})
    raw_status_manifest, _ = _load_manifest(resolved_status_path, default_key="executions")
    raw_channels_manifest, _ = _load_manifest(resolved_channels_path, default_key="channels")
    executions = [dict(item) for item in list(raw_status_manifest.get("executions") or []) if isinstance(item, dict)]
    channels = [dict(item) for item in list(raw_channels_manifest.get("channels") or []) if isinstance(item, dict)]
    existing_channel = _find_channel_entry(channels, normalized_target_channel)
    latest_execution = _find_latest_execution(executions, normalized_target_channel)
    rollback_url = str(rollback_target_url or "").strip()
    if not rollback_url:
        rollback_url = str((existing_channel or {}).get("rollback_public_url") or "").strip()
    if not rollback_url:
        rollback_url = str((latest_execution or {}).get("rollback_url") or "").strip()
    if not rollback_url:
        rollback_url = str(plan.get("rollback_rehearsal", {}).get("restore_target") or "").strip()
    authorization = authorize_release_operation(
        resolved_project_root,
        runtime_root=resolved_runtime_root,
        policy_path=access_policy_path,
        actor_id=normalized_executor,
        action="release_execution",
        target_channel=normalized_target_channel,
        target_environment=str(plan.get("target_environment") or target_environment or "").strip(),
        operation="rollback",
        required=True,
    )
    if str(authorization.get("status") or "") == "blocked":
        raise ValueError(f"release execution authorization failed: {authorization.get('reason') or 'blocked'}")

    checklist = [
        _item(
            "execution_actor",
            "Execution Actor",
            "passed" if normalized_executor else "blocked",
            f"executed_by={normalized_executor or '-'}",
            required=True,
        ),
        _item(
            "authorization_gate",
            "Release Authorization",
            str(authorization.get("status") or "skipped"),
            str(authorization.get("reason") or "authorization not evaluated"),
            required=bool(authorization.get("required")),
            details=dict(authorization),
        ),
        _item(
            "channel_binding_exists",
            "Channel Binding Exists",
            "passed" if existing_channel or latest_execution else "blocked",
            f"channel={normalized_target_channel}" if existing_channel or latest_execution else "当前没有可回滚的 execution/channel 记录",
            required=True,
        ),
        _item(
            "rollback_target",
            "Rollback Target",
            "passed" if rollback_url else "blocked",
            rollback_url or "缺少 rollback target",
            required=True,
        ),
        _item(
            "rollback_rehearsal",
            "Rollback Rehearsal",
            str(plan.get("rollback_rehearsal", {}).get("status") or "skipped"),
            str(plan.get("rollback_rehearsal", {}).get("rollback_hint") or rollback_url or "-"),
            required=False,
        ),
    ]
    should_block, execution_status, blocking_checks, warning_checks = _summarize_checklist(
        checklist,
        mode=effective_mode,
        fail_on_warnings=effective_fail_on_warnings,
    )

    updated_channel = None
    channel_binding_changed = False
    if not should_block:
        updated_channel = _apply_channel_binding(
            existing_channel,
            target_channel=normalized_target_channel,
            target_environment=str(plan.get("target_environment") or target_environment or "").strip() or "staging",
            rollout_stage="rolled_back",
            rollout_percentage=100,
            execution_status="warning",
            release_manifest_path=str((existing_channel or {}).get("active_release_manifest_path") or plan.get("release_manifest_path") or release_manifest_path or "").strip(),
            release_build_id=str((existing_channel or {}).get("active_build_id") or "").strip(),
            release_version=str((existing_channel or {}).get("active_version") or "").strip(),
            release_channel=str((existing_channel or {}).get("active_release_channel") or "").strip(),
            public_url=rollback_url,
            versioned_release_url=str((existing_channel or {}).get("active_versioned_url") or (latest_execution or {}).get("versioned_release_url") or "").strip(),
            rollback_url=rollback_url,
            executed_by=normalized_executor,
            note=normalized_note or "rollback_trigger",
        )
        _upsert_channel_entry(channels, updated_channel)
        channel_binding_changed = True

    recorded_at = datetime.now(timezone.utc).isoformat()
    execution_record = {
        "execution_id": _build_execution_id(recorded_at, "rollback", normalized_target_channel),
        "recorded_at": recorded_at,
        "operation": "rollback",
        "target_channel": normalized_target_channel,
        "target_environment": str(plan.get("target_environment") or target_environment or "").strip() or "staging",
        "promotion_target_label": str(plan.get("promotion_target_label") or "").strip(),
        "execution_status": execution_status,
        "should_block": should_block,
        "executed_by": normalized_executor,
        "note": normalized_note,
        "rollout_stage": "rolled_back",
        "rollout_percentage": 100,
        "channel_binding_changed": channel_binding_changed,
        "authorization": authorization,
        "request_auth": normalized_request_auth,
        "release_manifest_path": str((updated_channel or existing_channel or {}).get("active_release_manifest_path") or plan.get("release_manifest_path") or "").strip(),
        "release_build_id": str((updated_channel or existing_channel or {}).get("active_build_id") or "").strip(),
        "release_version": str((updated_channel or existing_channel or {}).get("active_version") or "").strip(),
        "release_channel": str((updated_channel or existing_channel or {}).get("active_release_channel") or "").strip(),
        "public_url": rollback_url,
        "versioned_release_url": str((updated_channel or existing_channel or {}).get("active_versioned_url") or (latest_execution or {}).get("versioned_release_url") or "").strip(),
        "rollback_url": rollback_url,
        "promotion_record_id": str(promotion_record.get("record_id") or "").strip(),
        "promotion_decision": str(promotion_record.get("decision") or "").strip(),
        "promotion_executor": str(promotion_record.get("executed_by") or "").strip(),
        "promotion_recorded_at": str(promotion_record.get("recorded_at") or "").strip(),
        "release_delivery_readiness_status": str(release_delivery_readiness.get("status") or "").strip(),
        "release_delivery_readiness_summary": str(release_delivery_readiness.get("summary") or "").strip(),
        "release_delivery_readiness_next_actions": list(release_delivery_readiness.get("next_actions") or []),
        "release_delivery_readiness_next_action_count": len(list(release_delivery_readiness.get("next_actions") or [])),
        "release_delivery_readiness_blocking_checks": list(release_delivery_readiness.get("blocking_checks") or []),
        "release_delivery_readiness_warning_checks": list(release_delivery_readiness.get("warning_checks") or []),
        "previous_public_url": str((existing_channel or {}).get("active_public_url") or "").strip(),
        "checklist": checklist,
        "blocking_checks": blocking_checks,
        "warning_checks": warning_checks,
        "plan_snapshot": plan,
    }
    if updated_channel is not None:
        updated_channel["last_execution_id"] = execution_record["execution_id"]
        _upsert_channel_entry(channels, updated_channel)
    executions.insert(0, execution_record)
    _write_manifest(resolved_status_path, {"schema_version": RELEASE_EXECUTION_STATUS_SCHEMA_VERSION, "executions": executions})
    _write_manifest(resolved_channels_path, {"schema_version": RELEASE_EXECUTION_STATUS_SCHEMA_VERSION, "channels": channels})
    return _build_result_payload(
        resolved_project_root,
        resolved_runtime_root,
        resolved_status_path,
        resolved_channels_path,
        resolved_history_path,
        normalized_target_channel,
        plan,
        history,
    )


def _build_result_payload(
    project_root: Path,
    runtime_root: Path,
    status_path: Path,
    channels_path: Path,
    history_path: Path,
    target_channel: str,
    plan: Dict[str, Any],
    history: Dict[str, Any],
) -> Dict[str, Any]:
    execution_status_payload = build_release_execution_status(
        project_root,
        runtime_root=runtime_root,
        status_path=_relative_to_root(status_path, project_root),
        channels_path=_relative_to_root(channels_path, project_root),
        history_path=_relative_to_root(history_path, project_root),
        limit=10,
    )
    return {
        "project_root": str(project_root),
        "status_path": _relative_to_root(status_path, project_root),
        "channels_path": _relative_to_root(channels_path, project_root),
        "execution": dict(execution_status_payload.get("latest_execution") or {}),
        "execution_status": execution_status_payload,
        "channel_entry": _find_channel_entry(execution_status_payload.get("channel_entries") or [], target_channel) or {},
        "plan": plan,
        "promotion_history": history,
    }


def _resolve_execution_paths(
    project_root: str | Path,
    *,
    runtime_root: Optional[str | Path] = None,
    status_path: str = "",
    channels_path: str = "",
    history_path: str = "",
) -> Tuple[Path, Path, Path, Path, Path]:
    resolved_project_root = Path(project_root).resolve()
    resolved_runtime_root = Path(runtime_root or Path.cwd()).resolve()
    resolved_status_path = _resolve_project_path(resolved_project_root, status_path or DEFAULT_RELEASE_EXECUTION_STATUS_PATH)
    resolved_channels_path = _resolve_project_path(resolved_project_root, channels_path or DEFAULT_RELEASE_CHANNELS_PATH)
    resolved_history_path = _resolve_project_path(resolved_project_root, history_path or DEFAULT_RELEASE_PROMOTION_HISTORY_PATH)
    return resolved_project_root, resolved_runtime_root, resolved_status_path, resolved_channels_path, resolved_history_path


def _resolve_clean_machine_bootstrap_target(
    target_channel: str,
    visible_items: List[Dict[str, Any]],
    filtered_items: List[Dict[str, Any]],
    raw_items: List[Dict[str, Any]],
    raw_channels: List[Dict[str, Any]],
) -> str:
    candidates = [
        str(target_channel or "").strip().lower(),
        str((visible_items[0] if visible_items else {}).get("target_channel") or "").strip().lower(),
        str((filtered_items[0] if filtered_items else {}).get("target_channel") or "").strip().lower(),
        str((raw_items[0] if raw_items else {}).get("target_channel") or "").strip().lower(),
        str((raw_channels[0] if raw_channels else {}).get("channel_id") or (raw_channels[0] if raw_channels else {}).get("target_channel") or "").strip().lower(),
    ]
    for candidate in candidates:
        if candidate in {"qa", "staging", "release"}:
            return candidate
    return "staging"


def _resolve_request_auth_target_environment(
    visible_items: List[Dict[str, Any]],
    filtered_items: List[Dict[str, Any]],
    raw_items: List[Dict[str, Any]],
    raw_channels: List[Dict[str, Any]],
) -> str:
    candidates = [
        str((visible_items[0] if visible_items else {}).get("target_environment") or "").strip(),
        str((filtered_items[0] if filtered_items else {}).get("target_environment") or "").strip(),
        str((raw_items[0] if raw_items else {}).get("target_environment") or "").strip(),
        str((raw_channels[0] if raw_channels else {}).get("target_environment") or "").strip(),
    ]
    for candidate in candidates:
        if candidate:
            return candidate
    return ""


def _extract_latest_execution_authorization(*execution_groups: List[Dict[str, Any]]) -> Dict[str, Any]:
    for group in execution_groups:
        if not group:
            continue
        authorization = dict((group[0] or {}).get("authorization") or {})
        if authorization:
            return authorization
    return {}


def _resolve_full_live_validation_release_binding(
    project_root: Path,
    runtime_root: Path,
    target_channel: str,
    visible_items: List[Dict[str, Any]],
    filtered_items: List[Dict[str, Any]],
    raw_items: List[Dict[str, Any]],
    raw_channels: List[Dict[str, Any]],
) -> Dict[str, str]:
    candidates = [
        _extract_release_binding_from_execution_source(visible_items[0] if visible_items else {}),
        _extract_release_binding_from_execution_source(filtered_items[0] if filtered_items else {}),
        _extract_release_binding_from_execution_source(raw_items[0] if raw_items else {}),
        _extract_release_binding_from_channel_source(_find_channel_entry(raw_channels, target_channel) or {}),
        _extract_release_binding_from_channel_source(raw_channels[0] if raw_channels else {}),
        _load_release_manifest_binding(project_root, runtime_root),
    ]
    resolved = {
        "build_id": "",
        "version": "",
        "channel": "",
        "release_manifest_path": "",
    }
    for candidate in candidates:
        if not candidate:
            continue
        for field_name in ("build_id", "version", "channel", "release_manifest_path"):
            if not resolved[field_name]:
                resolved[field_name] = str(candidate.get(field_name) or "").strip()
    if not resolved["channel"]:
        resolved["channel"] = str(target_channel or "").strip().lower()
    return resolved


def _load_release_manifest_binding(project_root: Path, runtime_root: Path) -> Dict[str, str]:
    candidates: List[Path] = []
    seen = set()
    for root in (runtime_root, project_root):
        candidate = (root / DEFAULT_RELEASE_MANIFEST_PATH).resolve()
        candidate_key = str(candidate)
        if candidate_key in seen:
            continue
        seen.add(candidate_key)
        candidates.append(candidate)

    for candidate in candidates:
        if not candidate.exists():
            continue
        try:
            payload = json.loads(candidate.read_text(encoding="utf-8-sig"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(payload, dict):
            continue
        return {
            "build_id": str(payload.get("build_id") or "").strip(),
            "version": str(payload.get("version") or "").strip(),
            "channel": str(payload.get("channel") or "").strip(),
            "release_manifest_path": DEFAULT_RELEASE_MANIFEST_PATH,
        }

    return {}


def _extract_release_binding_from_execution_source(source: Dict[str, Any]) -> Dict[str, str]:
    raw = dict(source or {})
    plan_snapshot = dict(raw.get("plan_snapshot") or {})
    release_summary = dict(plan_snapshot.get("release_candidate_checklist", {}).get("release_summary") or {})
    return {
        "build_id": str(raw.get("release_build_id") or release_summary.get("build_id") or "").strip(),
        "version": str(raw.get("release_version") or release_summary.get("version") or "").strip(),
        "channel": str(raw.get("release_channel") or raw.get("target_channel") or release_summary.get("channel") or "").strip(),
        "release_manifest_path": str(
            raw.get("release_manifest_path") or plan_snapshot.get("release_manifest_path") or release_summary.get("release_manifest_path") or ""
        ).strip(),
    }


def _extract_release_binding_from_channel_source(source: Dict[str, Any]) -> Dict[str, str]:
    raw = dict(source or {})
    return {
        "build_id": str(raw.get("active_build_id") or "").strip(),
        "version": str(raw.get("active_version") or "").strip(),
        "channel": str(raw.get("active_release_channel") or raw.get("channel_id") or raw.get("target_channel") or "").strip(),
        "release_manifest_path": str(raw.get("active_release_manifest_path") or "").strip(),
    }


def _validate_execution_manifests(project_root: Path, runtime_root: Path, status_path: Path, channels_path: Path) -> None:
    layout_validator = ProjectLayoutValidator(project_root=project_root, runtime_root=runtime_root)
    status_layout = layout_validator.validate_managed_path(status_path, "release_execution_status_manifest")
    channel_layout = layout_validator.validate_managed_path(channels_path, "release_channel_manifest")
    issues = [*status_layout["issues"], *channel_layout["issues"]]
    if issues:
        raise ValueError("; ".join(issue["message"] for issue in issues))


def _load_manifest(path: Path, *, default_key: str) -> Tuple[Dict[str, Any], str]:
    if not path.exists():
        return {"schema_version": RELEASE_EXECUTION_STATUS_SCHEMA_VERSION, default_key: []}, ""
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(payload, dict):
            return payload, ""
        return {"schema_version": RELEASE_EXECUTION_STATUS_SCHEMA_VERSION, default_key: []}, "manifest must be a JSON object"
    except Exception as exc:
        return {"schema_version": RELEASE_EXECUTION_STATUS_SCHEMA_VERSION, default_key: []}, str(exc)


def _write_manifest(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _normalize_quality_status(value: Any, default: str = "skipped") -> str:
    normalized = str(value or "").strip().lower()
    return normalized if normalized in _QUALITY_GATE_STATUSES else default


def _normalize_text_list(value: Any) -> List[str]:
    if isinstance(value, str):
        parts = value.replace("\r", "\n").replace(";", "\n").replace(",", "\n").split("\n")
    elif isinstance(value, (list, tuple, set)):
        parts = list(value)
    else:
        return []

    cleaned: List[str] = []
    seen = set()
    for item in parts:
        text = str(item or "").strip()
        if not text or text in seen:
            continue
        cleaned.append(text)
        seen.add(text)
    return cleaned


def _load_release_live_ci_summary(
    project_root: Path,
    runtime_root: Path,
    *,
    target_channel: str,
) -> Dict[str, Any]:
    dispatch_audit: Dict[str, Any] = {}
    for root in (runtime_root, project_root):
        payload = load_release_live_dispatch_audit(root, artifact_dir="logs/reports/release_live_ci")
        if isinstance(payload, dict) and payload:
            dispatch_audit = payload
            break

    candidates: List[Path] = []
    seen = set()
    for root in (runtime_root, project_root):
        candidate = root / "logs" / "reports" / "release_live_ci" / "release_live_ci_summary.json"
        key = str(candidate.resolve())
        if key in seen:
            continue
        seen.add(key)
        candidates.append(candidate)

    for candidate in candidates:
        if not candidate.exists():
            continue
        try:
            payload = json.loads(candidate.read_text(encoding="utf-8-sig"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(payload, dict):
            continue

        ci_gate = dict(payload.get("ci_gate") or {})
        runtime_gates = dict(payload.get("runtime_gates") or {})
        invocation = dict(payload.get("invocation") or {})
        human_signoffs = dict(payload.get("human_signoffs") or {})
        runtime_lanes = dict(payload.get("runtime_lanes") or {})
        runtime_assembly = dict(payload.get("runtime_assembly") or {})
        event_stream = dict(payload.get("event_stream") or {})
        workflow_steps = [dict(item) for item in list(payload.get("workflow_steps") or []) if isinstance(item, dict)]
        full_live_lanes = [dict(item) for item in list(runtime_lanes.get("full_live_validation") or []) if isinstance(item, dict)]
        report_files = dict(payload.get("report_files") or {})
        summary_markdown_name = str(report_files.get("summary_markdown") or "release_live_ci_summary.md").strip() or "release_live_ci_summary.md"
        summary_markdown_path = candidate.parent / summary_markdown_name
        workflow_step_results_name = str(report_files.get("workflow_step_results") or "").strip()
        workflow_step_results_path = candidate.parent / workflow_step_results_name if workflow_step_results_name else None
        ci_gate_status = _normalize_quality_status(ci_gate.get("status"), "warning")
        return {
            "status": ci_gate_status,
            "path": _display_path(candidate, runtime_root, project_root),
            "summary": (
                f"ci_gate={ci_gate_status} / lanes={len(full_live_lanes)} / "
                f"signoffs={_normalize_quality_status(human_signoffs.get('status'), 'skipped')}"
            ),
            "details": {
                "artifact_dir": _display_path(candidate.parent, runtime_root, project_root),
                "generated_at": str(payload.get("generated_at") or "").strip(),
                "target_channel": str(payload.get("target_channel") or target_channel).strip(),
                "target_environment": str(payload.get("target_environment") or "").strip(),
                "release_build_id": str(payload.get("release_build_id") or "").strip(),
                "release_version": str(payload.get("release_version") or "").strip(),
                "release_channel": str(payload.get("release_channel") or "").strip(),
                "release_manifest_path": str(payload.get("release_manifest_path") or "").strip(),
                "summary_markdown_path": _display_path(summary_markdown_path, runtime_root, project_root),
                "summary_markdown_exists": summary_markdown_path.exists(),
                "workflow_step_results_path": _display_path(workflow_step_results_path, runtime_root, project_root) if workflow_step_results_path else "",
                "runtime_assembly": runtime_assembly,
                "event_stream": event_stream,
                "dispatch_audit": dispatch_audit,
                "invocation": invocation,
                "ci_gate": ci_gate,
                "runtime_gates": runtime_gates,
                "runtime_lanes": runtime_lanes,
                "workflow_steps": workflow_steps,
                "human_signoffs": human_signoffs,
            },
        }

    return {
        "status": "warning",
        "path": "",
        "summary": "release_live_ci_summary.json not found",
        "details": {
            "artifact_dir": "logs/reports/release_live_ci",
            "generated_at": "",
            "target_channel": str(target_channel or "").strip(),
            "target_environment": "",
            "release_build_id": "",
            "release_version": "",
            "release_channel": "",
            "release_manifest_path": "",
            "summary_markdown_path": "logs/reports/release_live_ci/release_live_ci_summary.md",
            "summary_markdown_exists": False,
            "workflow_step_results_path": "",
            "runtime_assembly": {},
            "event_stream": {},
            "dispatch_audit": dispatch_audit,
            "invocation": {},
            "ci_gate": {
                "status": "warning",
                "should_block": False,
                "fail_on_warnings": False,
                "blocking_checks": [],
                "warning_checks": ["missing_release_live_ci_summary"],
                "evaluated_check_count": 0,
            },
            "runtime_gates": {},
            "runtime_lanes": {"full_live_validation": []},
            "workflow_steps": [],
            "human_signoffs": {
                "status": "skipped",
                "required_signoffs": [],
                "provided_signoffs": [],
                "missing_signoffs": [],
            },
        },
    }


def _build_release_live_ci_summary_report_lines(summary: Dict[str, Any]) -> List[str]:
    details = dict(summary.get("details") or {})
    ci_gate = dict(details.get("ci_gate") or {})
    runtime_gates = dict(details.get("runtime_gates") or {})
    invocation = dict(details.get("invocation") or {})
    human_signoffs = dict(details.get("human_signoffs") or {})
    runtime_lanes = dict(details.get("runtime_lanes") or {})
    runtime_assembly = dict(details.get("runtime_assembly") or {})
    event_stream = dict(details.get("event_stream") or {})
    dispatch_audit = dict(details.get("dispatch_audit") or {})
    workflow_steps = [dict(item) for item in list(details.get("workflow_steps") or []) if isinstance(item, dict)]
    full_live_lanes = [dict(item) for item in list(runtime_lanes.get("full_live_validation") or []) if isinstance(item, dict)]

    lines = [
        f"- Status: {summary.get('status') or 'warning'}",
        f"- Summary: {summary.get('summary') or '-'}",
        f"- Path: {summary.get('path') or '-'}",
        (
            f"- Artifact Dir: {details.get('artifact_dir') or '-'} / "
            f"Generated At: {details.get('generated_at') or '-'} / "
            f"Summary Markdown: {details.get('summary_markdown_path') or '-'} "
            f"(exists={'yes' if details.get('summary_markdown_exists') else 'no'})"
        ),
        f"- Workflow Step Results: {details.get('workflow_step_results_path') or '-'}",
        (
            f"- Build: {details.get('release_build_id') or '-'} / "
            f"version={details.get('release_version') or '-'} / "
            f"channel={details.get('release_channel') or '-'}"
        ),
        (
            f"- Target: {details.get('target_channel') or '-'} -> "
            f"{details.get('target_environment') or '-'} / "
            f"manifest={details.get('release_manifest_path') or '-'}"
        ),
        (
            f"- Invocation: source={invocation.get('source') or '-'} / "
            f"mode={invocation.get('mode') or '-'} / "
            f"fail_on_warnings={bool(invocation.get('fail_on_warnings'))} / "
            f"providers={','.join(_normalize_text_list(invocation.get('providers'))) or '-'} / "
            f"approvers={','.join(_normalize_text_list(invocation.get('approvers'))) or '-'}"
        ),
    ]
    lines.extend(build_release_runtime_assembly_report_lines(runtime_assembly))
    lines.extend(build_release_live_event_stream_report_lines(event_stream))
    lines.extend(build_release_live_dispatch_audit_report_lines(dispatch_audit))
    lines.extend([
        (
            f"- CI Gate: status={ci_gate.get('status') or '-'} / "
            f"should_block={bool(ci_gate.get('should_block'))} / "
            f"blocking={','.join(_normalize_text_list(ci_gate.get('blocking_checks'))) or 'none'} / "
            f"warning={','.join(_normalize_text_list(ci_gate.get('warning_checks'))) or 'none'}"
        ),
        (
            f"- Runtime Gates: runner_baseline={runtime_gates.get('release_live_runner_baseline_status') or '-'} / "
            f"full_live={runtime_gates.get('full_live_validation_status') or '-'} / "
            f"distribution={runtime_gates.get('distribution_bundle_status') or '-'} / "
            f"signing={runtime_gates.get('distribution_signing_handoff_status') or '-'} / "
            f"publish={runtime_gates.get('distribution_publish_handoff_status') or '-'} / "
            f"receipts={runtime_gates.get('distribution_publish_receipts_status') or '-'} / "
            f"identity={runtime_gates.get('identity_handoff_status') or '-'}"
        ),
        (
            f"- Human Signoffs: status={human_signoffs.get('status') or '-'} / "
            f"provided={','.join(_normalize_text_list(human_signoffs.get('provided_signoffs'))) or 'none'} / "
            f"missing={','.join(_normalize_text_list(human_signoffs.get('missing_signoffs'))) or 'none'}"
        ),
    ])
    for lane in full_live_lanes[:6]:
        lines.append(
            f"- Lane ({lane.get('lane_id') or lane.get('label') or 'lane'}): "
            f"status={lane.get('status') or '-'} / "
            f"summary={lane.get('summary') or '-'} / "
            f"report={lane.get('report_path') or '-'} / "
            f"flows={', '.join(f'{key}={value}' for key, value in dict(lane.get('flow_statuses') or {}).items()) or 'none'}"
        )
    for step in workflow_steps[:8]:
        lines.append(
            f"- Workflow Step ({step.get('step_id') or step.get('label') or 'step'}): "
            f"status={step.get('status') or '-'} / "
            f"outcome={step.get('outcome') or '-'} / "
            f"always_run={'yes' if step.get('always_run') else 'no'} / "
            f"message={step.get('message') or '-'}"
        )
    return lines


def _normalize_operation(value: str, *, allow_empty: bool = False) -> str:
    normalized = str(value or "").strip().lower()
    if not normalized and allow_empty:
        return ""
    return normalized if normalized in _EXECUTION_OPERATIONS else "dry_run"


def _normalize_rollout_percentage(operation: str, value: int) -> int:
    if operation == "dry_run":
        return 0
    if operation == "full_rollout":
        return 100
    try:
        numeric = int(value)
    except Exception:
        numeric = 10
    return max(min(numeric, 99), 1)


def _resolve_project_path(project_root: Path, raw_path: str) -> Path:
    relative = str(raw_path or "").strip()
    if relative.startswith("res://"):
        relative = relative[6:]
    return (project_root / relative).resolve()


def _relative_to_root(path: Path, project_root: Path) -> str:
    try:
        return path.resolve().relative_to(project_root.resolve()).as_posix()
    except Exception:
        return str(path.resolve())


def _status_from_plan(plan: Dict[str, Any]) -> str:
    status = str(plan.get("status") or "").strip().lower()
    if status in {"passed", "warning", "blocked"}:
        return status
    return "blocked" if bool(plan.get("should_block")) else "warning"


def _item(
    item_id: str,
    label: str,
    status: str,
    message: str,
    *,
    required: bool = True,
    details: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    normalized_status = status if status in {"passed", "warning", "blocked", "skipped"} else "skipped"
    return {
        "item_id": item_id,
        "label": label,
        "status": normalized_status,
        "required": required,
        "message": message,
        "details": dict(details or {}),
    }


def _summarize_checklist(checklist: List[Dict[str, Any]], *, mode: str, fail_on_warnings: bool) -> Tuple[bool, str, List[str], List[str]]:
    blocked_checks = [item["item_id"] for item in checklist if item["status"] == "blocked"]
    warning_checks = [item["item_id"] for item in checklist if item["status"] == "warning"]
    normalized_mode = str(mode or "strict").strip().lower() or "strict"
    should_block = bool(blocked_checks) or (fail_on_warnings and bool(warning_checks))
    if normalized_mode == "advisory":
        should_block = False
    status = "blocked" if blocked_checks else ("warning" if warning_checks else "passed")
    return should_block, status, blocked_checks, warning_checks


def _select_promotion_record(history: Dict[str, Any]) -> Dict[str, Any]:
    items = [dict(item) for item in list(history.get("items") or []) if isinstance(item, dict)]
    return items[0] if items else {}


def _build_promotion_history_item(promotion_record: Dict[str, Any], operation: str) -> Dict[str, Any]:
    latest_decision = str(promotion_record.get("decision") or "").strip().lower()
    latest_should_block = bool(promotion_record.get("should_block"))
    if operation == "dry_run":
        if latest_decision in _READY_PROMOTION_DECISIONS and not latest_should_block:
            return _item("promotion_history_ready", "Promotion History", "passed", f"latest={latest_decision}")
        if latest_decision:
            return _item("promotion_history_ready", "Promotion History", "warning", f"dry run on latest decision={latest_decision}", required=False)
        return _item("promotion_history_ready", "Promotion History", "warning", "dry run 未找到 promotion history，继续以 rehearsal 方式执行", required=False)
    if latest_decision in _READY_PROMOTION_DECISIONS and not latest_should_block:
        return _item("promotion_history_ready", "Promotion History", "passed", f"latest={latest_decision}", required=True)
    if latest_decision:
        return _item("promotion_history_ready", "Promotion History", "blocked", f"latest promotion decision={latest_decision}，不能执行 {operation}", required=True)
    return _item("promotion_history_ready", "Promotion History", "blocked", f"执行 {operation} 前缺少 approved/promoted promotion history", required=True)


def _find_channel_entry(entries: List[Dict[str, Any]], channel_id: str) -> Optional[Dict[str, Any]]:
    for item in entries:
        if str(item.get("channel_id") or item.get("target_channel") or "").strip().lower() == channel_id:
            return dict(item)
    return None


def _find_latest_execution(executions: List[Dict[str, Any]], channel_id: str) -> Optional[Dict[str, Any]]:
    for item in executions:
        if str(item.get("target_channel") or "").strip().lower() == channel_id:
            return dict(item)
    return None


def _upsert_channel_entry(entries: List[Dict[str, Any]], updated: Dict[str, Any]) -> None:
    channel_id = str(updated.get("channel_id") or "").strip().lower()
    for index, item in enumerate(entries):
        if str(item.get("channel_id") or item.get("target_channel") or "").strip().lower() == channel_id:
            entries[index] = updated
            return
    entries.append(updated)


def _apply_channel_binding(
    existing: Optional[Dict[str, Any]],
    *,
    target_channel: str,
    target_environment: str,
    rollout_stage: str,
    rollout_percentage: int,
    execution_status: str,
    release_manifest_path: str,
    release_build_id: str,
    release_version: str,
    release_channel: str,
    public_url: str,
    versioned_release_url: str,
    rollback_url: str,
    executed_by: str,
    note: str,
) -> Dict[str, Any]:
    previous = dict(existing or {})
    previous_public_url = str(previous.get("active_public_url") or "").strip()
    notes = [item for item in [note] if str(item or "").strip()]
    return {
        "channel_id": target_channel,
        "target_environment": target_environment,
        "binding_status": execution_status if execution_status in {"passed", "warning"} else "warning",
        "rollout_stage": rollout_stage if rollout_stage in _ROLLOUT_STAGES else "idle",
        "rollout_percentage": rollout_percentage,
        "active_release_manifest_path": release_manifest_path,
        "active_build_id": release_build_id,
        "active_version": release_version,
        "active_release_channel": release_channel,
        "active_public_url": public_url,
        "active_versioned_url": versioned_release_url or public_url,
        "rollback_public_url": rollback_url or previous_public_url or versioned_release_url or public_url,
        "previous_public_url": previous_public_url,
        "last_execution_id": "",
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "executed_by": executed_by,
        "notes": notes,
    }


def _build_execution_id(recorded_at: str, operation: str, channel_id: str) -> str:
    compact = recorded_at.replace("-", "").replace(":", "").replace(".", "").replace("+00:00", "Z")
    return f"release_execution_{compact}_{operation}_{channel_id}"


def _build_execution_target_label(item: Dict[str, Any]) -> str:
    label = str(item.get("promotion_target_label") or "").strip()
    if label:
        return label
    target_channel = str(item.get("target_channel") or "").strip() or "-"
    target_environment = str(item.get("target_environment") or "").strip() or "-"
    return f"{target_channel} -> {target_environment}"


def _normalize_request_auth_payload(
    payload: Optional[Dict[str, Any]],
    *,
    action: str,
    target_channel: str,
    target_environment: str,
) -> Dict[str, Any]:
    normalized = dict(payload or {})
    if not normalized:
        return {
            "status": "skipped",
            "required": False,
            "auth_path": "",
            "mode": "direct_tool",
            "client_host": "",
            "actor_id": "",
            "action": action,
            "target_channel": target_channel,
            "target_environment": target_environment,
            "header_name": "",
            "scheme": "direct_tool",
            "token_configured": False,
            "token_present": False,
            "token_id": "",
            "token_source": "",
            "session_id": "",
            "issued_by": "",
            "issued_at": "",
            "session_tracked": False,
            "identity_path": "",
            "identity_registry_exists": False,
            "issuer_registered": False,
            "issuer_status": "",
            "issuer_subject_actor_ids": [],
            "max_session_age_hours": 0,
            "required_actor_ids": [],
            "reason": "request auth not evaluated for direct tool invocation",
        }
    normalized["action"] = str(normalized.get("action") or action).strip()
    normalized["target_channel"] = str(normalized.get("target_channel") or target_channel).strip()
    normalized["target_environment"] = str(normalized.get("target_environment") or target_environment).strip()
    return normalized

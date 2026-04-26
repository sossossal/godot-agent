"""
Release promotion history builder.

P17 adds a durable promotion ledger so actual release decisions, operators,
signoff source, and the plan snapshot survive across Portal, API, and audit
handoff.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from agent_system.contracts import (
    RELEASE_PROMOTION_HISTORY_SCHEMA_VERSION,
    normalize_release_delivery_readiness,
    normalize_release_live_dispatch_audit,
    normalize_release_promotion_history,
)
from agent_system.tools.release_runtime_assembly import (
    build_release_runtime_assembly_report_lines,
)
from agent_system.tools.release_live_event_stream import (
    build_release_live_event_stream_report_lines,
)
from agent_system.tools.release_access_policy import authorize_release_operation
from agent_system.tools.release_promotion import (
    _build_release_distribution_publish_receipts_summary,
    _release_distribution_publish_receipts_follow_up_required,
    build_release_promotion_plan,
)
from agent_system.validations import ProjectLayoutValidator
from tools.dispatch_release_live_gates import load_release_live_dispatch_audit


DEFAULT_RELEASE_PROMOTION_HISTORY_PATH = "deployment/release_promotion_history.json"
_DECISION_VALUES = {"planned", "approved", "promoted", "blocked", "rolled_back", "aborted"}
_EXECUTED_DECISIONS = {"approved", "promoted", "blocked", "rolled_back", "aborted"}
_NON_BLOCKING_DECISIONS = {"approved", "promoted"}
_LIVE_CI_STATUS_VALUES = {"passed", "warning", "blocked", "skipped"}


def build_release_promotion_history(
    project_root: str | Path,
    runtime_root: Optional[str | Path] = None,
    *,
    history_path: str = "",
    decision: str = "",
    target_channel: str = "",
    executed_by: str = "",
    live_ci_status: str = "",
    dispatch_status: str = "",
    dispatch_follow_up: str = "",
    dispatch_run_status: str = "",
    dispatch_run_conclusion: str = "",
    failed_workflow_step: str = "",
    delivery_readiness_status: str = "",
    readiness_action: str = "",
    offset: int = 0,
    limit: int = 20,
) -> Dict[str, Any]:
    resolved_project_root = Path(project_root).resolve()
    resolved_runtime_root = Path(runtime_root or Path.cwd()).resolve()
    resolved_history_path = _resolve_project_path(
        resolved_project_root,
        history_path or DEFAULT_RELEASE_PROMOTION_HISTORY_PATH,
    )

    layout_validator = ProjectLayoutValidator(project_root=resolved_project_root, runtime_root=resolved_runtime_root)
    layout_result = layout_validator.validate_managed_path(resolved_history_path, "release_promotion_history_manifest")
    normalized_decision = _normalize_decision(decision, allow_empty=True)
    normalized_target_channel = str(target_channel or "").strip().lower()
    normalized_executor = str(executed_by or "").strip()
    normalized_live_ci_status = _normalize_live_ci_status(live_ci_status, allow_empty=True)
    normalized_dispatch_status = _normalize_dispatch_status(dispatch_status, allow_empty=True)
    normalized_dispatch_follow_up = _normalize_dispatch_follow_up(dispatch_follow_up, allow_empty=True)
    normalized_dispatch_run_status = _normalize_dispatch_run_status(dispatch_run_status, allow_empty=True)
    normalized_dispatch_run_conclusion = _normalize_dispatch_run_conclusion(dispatch_run_conclusion, allow_empty=True)
    normalized_failed_workflow_step = str(failed_workflow_step or "").strip()
    normalized_delivery_readiness_status = _normalize_live_ci_status(delivery_readiness_status, allow_empty=True)
    normalized_readiness_action = str(readiness_action or "").strip()

    manifest_exists = resolved_history_path.exists()
    manifest_error = ""
    raw_items: List[Dict[str, Any]] = []
    if manifest_exists:
        try:
            payload = json.loads(resolved_history_path.read_text(encoding="utf-8"))
            if isinstance(payload, dict):
                raw_items = [dict(item) for item in list(payload.get("items") or []) if isinstance(item, dict)]
            else:
                manifest_error = "release promotion history manifest must be a JSON object"
        except Exception as exc:
            manifest_error = str(exc)

    if manifest_error:
        raw_items = [{
            "record_id": "history_manifest_error",
            "recorded_at": "",
            "decision": "blocked",
            "executed_by": "",
            "note": manifest_error,
        }]

    filtered_items = [
        item for item in raw_items
        if (not normalized_decision or str(item.get("decision") or "").strip().lower() == normalized_decision)
        and (not normalized_target_channel or str(item.get("target_channel") or "").strip().lower() == normalized_target_channel)
        and (not normalized_executor or str(item.get("executed_by") or "").strip() == normalized_executor)
        and (not normalized_live_ci_status or _extract_live_ci_status(item) == normalized_live_ci_status)
        and (not normalized_dispatch_status or _extract_dispatch_status(item) == normalized_dispatch_status)
        and (not normalized_dispatch_follow_up or _extract_dispatch_follow_up(item) == normalized_dispatch_follow_up)
        and (not normalized_dispatch_run_status or _extract_dispatch_run_status(item) == normalized_dispatch_run_status)
        and (not normalized_dispatch_run_conclusion or _extract_dispatch_run_conclusion(item) == normalized_dispatch_run_conclusion)
        and (not normalized_failed_workflow_step or normalized_failed_workflow_step in _extract_failed_workflow_steps(item))
        and (not normalized_delivery_readiness_status or _extract_delivery_readiness_status(item) == normalized_delivery_readiness_status)
        and (not normalized_readiness_action or normalized_readiness_action in _extract_delivery_readiness_actions(item))
    ]
    normalized_offset = max(int(offset or 0), 0)
    normalized_limit = max(int(limit or 20), 1)
    visible_items = filtered_items[normalized_offset:normalized_offset + normalized_limit]
    next_offset = normalized_offset + normalized_limit if normalized_offset + normalized_limit < len(filtered_items) else None
    prev_offset = normalized_offset - normalized_limit if normalized_offset > 0 else None

    notes = []
    recommendations = []
    if not layout_result["passed"]:
        notes.append("history_path 未通过文件树规范校验。")
        recommendations.append("将 release promotion history 固定落到 deployment/release_promotion_history.json。")
    if manifest_error:
        notes.append(f"history manifest 解析失败: {manifest_error}")
        recommendations.append("先修复 release promotion history manifest 的 JSON 格式。")
    if not raw_items and not manifest_error:
        notes.append("当前还没有已记录的 promotion history。")
        recommendations.append("在 Portal 或 API 中至少记录一次 approved/promoted/blocked 结果，避免晋级结果只留在聊天记录。")
    latest_receipts_state = _build_distribution_publish_receipts_history_snapshot(visible_items[0] if visible_items else {})
    if latest_receipts_state.get("follow_up_required"):
        notes.append(f"latest promotion publish receipts: {latest_receipts_state.get('summary') or 'follow-up required'}")
        recommendations.append(
            "为 latest promotion 补齐 publish receipt 回流，确保 promotion history 不只是记录已批准/已晋级，还能说明哪些外部分发 target 已真正完成。"
        )
    latest_live_ci_state = _build_release_live_ci_history_snapshot(visible_items[0] if visible_items else {})
    latest_dispatch_audit = load_release_live_dispatch_audit(
        resolved_project_root,
        artifact_dir="logs/reports/release_live_ci",
    )
    if not latest_dispatch_audit:
        latest_dispatch_audit = dict(_build_release_live_dispatch_history_snapshot(visible_items[0] if visible_items else {}).get("audit") or {})
    if latest_live_ci_state.get("follow_up_required"):
        notes.append(f"latest promotion live ci: {latest_live_ci_state.get('summary') or 'follow-up required'}")
        recommendations.append(
            "为 latest promotion 补齐 release-live-gates 产物，确保 promotion history 能直接指出 fixed runner 卡在 baseline、distribution 还是 full live validation。"
        )
    elif latest_dispatch_audit and str(latest_dispatch_audit.get("status") or "").strip().lower() in {"warning", "blocked"}:
        notes.append(f"latest dispatch audit: {latest_dispatch_audit.get('summary') or latest_dispatch_audit.get('status')}")
        recommendations.append(
            "先修复最新的 workflow dispatch preflight / request_auth / GitHub run 失败，再回到 release-live-gates 产物闭环，避免 history 只看到 live ci 缺失。"
        )

    return normalize_release_promotion_history({
        "project_root": str(resolved_project_root),
        "runtime_root": str(resolved_runtime_root),
        "history_path": _relative_to_root(resolved_history_path, resolved_project_root),
        "history_exists": manifest_exists,
        "decision_filter": normalized_decision,
        "target_channel_filter": normalized_target_channel,
        "executor_filter": normalized_executor,
        "live_ci_status_filter": normalized_live_ci_status,
        "dispatch_status_filter": normalized_dispatch_status,
        "dispatch_follow_up_filter": normalized_dispatch_follow_up,
        "dispatch_run_status_filter": normalized_dispatch_run_status,
        "dispatch_run_conclusion_filter": normalized_dispatch_run_conclusion,
        "failed_workflow_step_filter": normalized_failed_workflow_step,
        "delivery_readiness_status_filter": normalized_delivery_readiness_status,
        "readiness_action_filter": normalized_readiness_action,
        "offset": normalized_offset,
        "limit": normalized_limit,
        "total_count": len(raw_items),
        "matched_count": len(filtered_items),
        "visible_count": len(visible_items),
        "next_offset": next_offset,
        "prev_offset": prev_offset,
        "latest_dispatch_audit": latest_dispatch_audit,
        "items": visible_items,
        "notes": notes,
        "recommendations": recommendations,
        "contract_versions": {
            "release_promotion_history": RELEASE_PROMOTION_HISTORY_SCHEMA_VERSION,
        },
    })


def build_release_promotion_history_report(summary: Dict[str, Any] | None) -> str:
    normalized = normalize_release_promotion_history(summary)
    latest_record = dict(normalized.get("latest_record") or {})
    latest_dispatch_audit = dict(normalized.get("latest_dispatch_audit") or {})
    lines = [
        "# Release Promotion History",
        "",
        f"- History Path: {normalized.get('history_path') or '-'}",
        (
            "- Filters: "
            f"decision={normalized.get('decision_filter') or '-'} / "
            f"target_channel={normalized.get('target_channel_filter') or '-'} / "
            f"executed_by={normalized.get('executor_filter') or '-'} / "
            f"live_ci_status={normalized.get('live_ci_status_filter') or '-'} / "
            f"dispatch_status={normalized.get('dispatch_status_filter') or '-'} / "
            f"dispatch_follow_up={normalized.get('dispatch_follow_up_filter') or '-'} / "
            f"dispatch_run_status={normalized.get('dispatch_run_status_filter') or '-'} / "
            f"dispatch_run_conclusion={normalized.get('dispatch_run_conclusion_filter') or '-'} / "
            f"failed_workflow_step={normalized.get('failed_workflow_step_filter') or '-'} / "
            f"delivery_readiness_status={normalized.get('delivery_readiness_status_filter') or '-'} / "
            f"readiness_action={normalized.get('readiness_action_filter') or '-'}"
        ),
        (
            "- Records: "
            f"visible={normalized.get('visible_count') or 0} / "
            f"matched={normalized.get('matched_count') or 0} / "
            f"total={normalized.get('total_count') or 0}"
        ),
        "",
        "## Latest Record",
    ]

    if latest_record.get("record_id"):
        latest_runtime_assembly = dict(
            latest_record.get("release_live_ci_runtime_assembly")
            or dict(_build_release_live_ci_history_snapshot(latest_record).get("runtime_assembly") or {})
        )
        latest_event_stream = dict(
            latest_record.get("release_live_ci_event_stream")
            or dict(_build_release_live_ci_history_snapshot(latest_record).get("event_stream") or {})
        )
        lines.extend([
            f"- Record ID: {latest_record.get('record_id') or '-'}",
            f"- Recorded At: {latest_record.get('recorded_at') or '-'}",
            f"- Decision: {latest_record.get('decision') or '-'} / plan_status={latest_record.get('plan_status') or '-'} / should_block={bool(latest_record.get('should_block'))}",
            f"- Target: {latest_record.get('promotion_target_label') or (str(latest_record.get('target_channel') or '-') + ' -> ' + str(latest_record.get('target_environment') or '-'))}",
            f"- Release: {latest_record.get('release_build_id') or '-'} / version={latest_record.get('release_version') or '-'} / channel={latest_record.get('release_channel') or '-'}",
            f"- Executor: {latest_record.get('executed_by') or '-'} / signoff_source={latest_record.get('signoff_source') or '-'}",
            f"- Note: {latest_record.get('note') or '-'}",
            f"- Blocking Checks: {', '.join(list(latest_record.get('blocking_checks') or [])) or 'none'}",
            f"- Warning Checks: {', '.join(list(latest_record.get('warning_checks') or [])) or 'none'}",
            f"- Missing Signoffs: {', '.join(list(latest_record.get('missing_signoffs') or [])) or 'none'}",
            f"- Review Follow-up Actions: {latest_record.get('review_followup_action_count') or len(list(latest_record.get('review_followup_actions') or []))}",
            (
                f"- Release Delivery Readiness: {latest_record.get('release_delivery_readiness_status') or 'warning'} / "
                f"next_actions={latest_record.get('release_delivery_readiness_next_action_count') or len(list(latest_record.get('release_delivery_readiness_next_actions') or []))} / "
                f"summary={latest_record.get('release_delivery_readiness_summary') or '-'}"
            ),
            "",
            "## Distribution",
            "",
            f"- Distribution Status: {latest_record.get('distribution_status') or 'skipped'} / summary={latest_record.get('distribution_summary') or '-'}",
            (
                "- Distribution Publish Receipts: "
                f"{latest_record.get('distribution_publish_receipts_status') or 'skipped'} / "
                f"completed={len(list(latest_record.get('distribution_publish_receipts_completed_targets') or []))}/"
                f"{latest_record.get('distribution_publish_receipts_target_count') or 0} / "
                f"missing={', '.join(list(latest_record.get('distribution_publish_receipts_missing_targets') or [])) or 'none'} / "
                f"failed={', '.join(list(latest_record.get('distribution_publish_receipts_failed_targets') or [])) or 'none'}"
            ),
            f"- Publish Receipt Manifest: {latest_record.get('distribution_publish_receipts_manifest_path') or '-'}",
            f"- Publish Receipt Summary: {latest_record.get('distribution_publish_receipts_summary') or '-'}",
            f"- Publish Receipt Follow-up Required: {bool(latest_record.get('distribution_publish_receipts_follow_up_required'))}",
            "",
            "## Latest Live CI",
            "",
            f"- Release Live CI: {latest_record.get('release_live_ci_status') or 'skipped'} / summary={latest_record.get('release_live_ci_summary') or '-'}",
            f"- Release Live CI Summary Path: {latest_record.get('release_live_ci_path') or '-'}",
            f"- Release Live CI Markdown: {latest_record.get('release_live_ci_summary_markdown_path') or '-'}",
            (
                f"- Release Live Dispatch: {latest_record.get('release_live_dispatch_status') or 'skipped'} / "
                f"summary={latest_record.get('release_live_dispatch_summary') or '-'}"
            ),
            (
                f"- Release Live Dispatch Path: {latest_record.get('release_live_dispatch_path') or '-'} / "
                f"run={latest_record.get('release_live_dispatch_run_status') or '-'} / "
                f"conclusion={latest_record.get('release_live_dispatch_run_conclusion') or '-'}"
            ),
            f"- Workflow Step Results: {latest_record.get('release_live_ci_workflow_step_results_path') or '-'}",
            (
                "- Live CI Failed Workflow Steps: "
                f"{', '.join(list(latest_record.get('release_live_ci_failed_workflow_steps') or [])) or 'none'}"
            ),
            f"- Live CI Follow-up Required: {bool(latest_record.get('release_live_ci_follow_up_required'))}",
            "",
            "## Authorization",
            "",
            (
                f"- Authorization: {dict(latest_record.get('authorization') or {}).get('status') or 'skipped'} / "
                f"actor={dict(latest_record.get('authorization') or {}).get('actor_id') or '-'} / "
                f"rule={dict(latest_record.get('authorization') or {}).get('matched_rule_id') or '-'}"
            ),
            (
                f"- Request Auth: {dict(latest_record.get('request_auth') or {}).get('status') or 'skipped'} / "
                f"mode={dict(latest_record.get('request_auth') or {}).get('mode') or '-'} / "
                f"token={dict(latest_record.get('request_auth') or {}).get('token_id') or '-'} / "
                f"issuer={dict(latest_record.get('request_auth') or {}).get('issued_by') or '-'}"
            ),
        ])
        if latest_runtime_assembly:
            lines.extend(["", "## Live CI Runtime Assembly", ""])
            lines.extend(build_release_runtime_assembly_report_lines(latest_runtime_assembly))
        if latest_event_stream:
            lines.extend(["", "## Live CI Event Stream", ""])
            lines.extend(build_release_live_event_stream_report_lines(latest_event_stream))
        followup_actions = [dict(item) for item in list(latest_record.get("review_followup_actions") or [])]
        if followup_actions:
            lines.extend(["", "## Review Follow-up Actions", ""])
            for item in followup_actions:
                lines.append(
                    f"- {item.get('action_id') or 'action'}: "
                    f"status={item.get('status') or '-'} / "
                    f"owner={item.get('owner_hint') or '-'} / "
                    f"dependency={item.get('dependency') or '-'} / "
                    f"eta={item.get('eta') or '-'} / "
                    f"validation={item.get('validation_method') or '-'} / "
                    f"blockers={', '.join(list(item.get('blockers') or [])) or 'none'}"
                )
        readiness_actions = [dict(item) for item in list(latest_record.get("release_delivery_readiness_next_actions") or [])]
        if readiness_actions:
            lines.extend(["", "## Delivery Readiness Next Actions", ""])
            for item in readiness_actions:
                lines.append(
                    f"- {item.get('action_id') or 'action'}: "
                    f"status={item.get('status') or '-'} / "
                    f"owner={item.get('owner_hint') or '-'} / "
                    f"dependency={item.get('dependency') or '-'} / "
                    f"eta={item.get('eta') or '-'} / "
                    f"validation={item.get('validation_method') or '-'} / "
                    f"blockers={', '.join(list(item.get('blockers') or [])) or 'none'}"
                )
        for step in list(latest_record.get("release_live_ci_workflow_steps") or [])[:6]:
            step_entry = dict(step or {})
            lines.append(
                f"- Workflow Step ({step_entry.get('step_id') or 'step'}): "
                f"status={step_entry.get('status') or 'skipped'} / "
                f"outcome={step_entry.get('outcome') or '-'} / "
                f"always_run={bool(step_entry.get('always_run'))} / "
                f"message={step_entry.get('message') or '-'}"
            )
    else:
        lines.extend(["- No promotion history records found."])

    if latest_dispatch_audit.get("summary"):
        dispatch_request_auth = dict(latest_dispatch_audit.get("request_auth") or {})
        dispatch_run = dict(latest_dispatch_audit.get("run") or {})
        lines.extend([
            "",
            "## Latest Dispatch Audit",
            "",
            f"- Status: {latest_dispatch_audit.get('status') or 'skipped'} / summary={latest_dispatch_audit.get('summary') or '-'}",
            f"- Recorded At: {latest_dispatch_audit.get('recorded_at') or '-'} / triggered_by={latest_dispatch_audit.get('triggered_by') or '-'}",
            (
                f"- Workflow: {latest_dispatch_audit.get('workflow') or '-'} / "
                f"repo={latest_dispatch_audit.get('repo') or '-'} / ref={latest_dispatch_audit.get('ref') or '-'}"
            ),
            (
                f"- Dispatch: ready={bool(latest_dispatch_audit.get('ready'))} / "
                f"attempted={bool(latest_dispatch_audit.get('dispatch_attempted'))} / "
                f"completed={bool(latest_dispatch_audit.get('dispatch_completed'))} / "
                f"follow_up={bool(latest_dispatch_audit.get('follow_up_required'))}"
            ),
            (
                f"- Run: {dispatch_run.get('number') or dispatch_run.get('id') or '-'} / "
                f"status={dispatch_run.get('status') or '-'} / "
                f"conclusion={dispatch_run.get('conclusion') or '-'} / "
                f"url={dispatch_run.get('html_url') or '-'}"
            ),
            (
                f"- Request Auth: {dispatch_request_auth.get('status') or 'skipped'} / "
                f"actor={dispatch_request_auth.get('actor_id') or '-'} / "
                f"token={dispatch_request_auth.get('token_id') or '-'} / "
                f"reason={dispatch_request_auth.get('reason') or '-'}"
            ),
            (
                f"- Checks: blocking={', '.join(list(latest_dispatch_audit.get('blocking_checks') or [])) or 'none'} / "
                f"warning={', '.join(list(latest_dispatch_audit.get('warning_checks') or [])) or 'none'}"
            ),
            f"- Audit Path: {latest_dispatch_audit.get('path') or '-'}",
        ])

    items = [dict(item) for item in list(normalized.get("items") or [])]
    if items:
        lines.extend(["", "## Recent Records"])
        for item in items[:8]:
            lines.append(
                f"- {item.get('record_id') or 'record'}: {item.get('decision') or '-'} / "
                f"target={item.get('target_channel') or '-'} / "
                f"executor={item.get('executed_by') or '-'} / "
                f"delivery_readiness={item.get('release_delivery_readiness_status') or 'warning'} / "
                f"readiness_actions={item.get('release_delivery_readiness_next_action_count') or len(list(item.get('release_delivery_readiness_next_actions') or []))} / "
                f"distribution={item.get('distribution_status') or 'skipped'} / "
                f"publish_receipts={item.get('distribution_publish_receipts_status') or 'skipped'} / "
                f"live_ci={item.get('release_live_ci_status') or 'skipped'} / "
                f"dispatch={item.get('release_live_dispatch_status') or 'skipped'}"
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


def record_release_promotion_event(
    project_root: str | Path,
    runtime_root: Optional[str | Path] = None,
    *,
    history_path: str = "",
    target_channel: str = "staging",
    target_environment: str = "",
    release_manifest_path: str = "",
    approvers: Optional[List[str]] = None,
    providers: Optional[List[str]] = None,
    mode: str = "strict",
    fail_on_warnings: bool = False,
    decision: str = "planned",
    executed_by: str = "",
    note: str = "",
    signoff_source: str = "",
    access_policy_path: str = "",
    request_auth: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    resolved_project_root = Path(project_root).resolve()
    resolved_runtime_root = Path(runtime_root or Path.cwd()).resolve()
    resolved_history_path = _resolve_project_path(
        resolved_project_root,
        history_path or DEFAULT_RELEASE_PROMOTION_HISTORY_PATH,
    )
    layout_validator = ProjectLayoutValidator(project_root=resolved_project_root, runtime_root=resolved_runtime_root)
    layout_result = layout_validator.validate_managed_path(resolved_history_path, "release_promotion_history_manifest")
    if not layout_result["passed"]:
        raise ValueError("; ".join(issue["message"] for issue in layout_result["issues"]) or "invalid history_path")

    normalized_decision = _normalize_decision(decision)
    normalized_executor = str(executed_by or "").strip()
    normalized_note = str(note or "").strip()
    normalized_signoff_source = str(signoff_source or "").strip()
    normalized_request_auth = _normalize_request_auth_payload(
        request_auth,
        action="promotion_record",
        target_channel=str(target_channel or "staging").strip().lower() or "staging",
        target_environment=str(target_environment or "").strip(),
    )
    if normalized_decision in _EXECUTED_DECISIONS and not normalized_executor:
        raise ValueError("executed_by is required for non-planned promotion decisions")

    plan = build_release_promotion_plan(
        resolved_project_root,
        runtime_root=resolved_runtime_root,
        target_channel=target_channel,
        target_environment=target_environment,
        release_manifest_path=release_manifest_path,
        approvers=approvers,
        providers=providers,
        mode=mode,
        fail_on_warnings=fail_on_warnings,
    )
    if normalized_decision in _NON_BLOCKING_DECISIONS and bool(plan.get("should_block")):
        raise ValueError("cannot record approved/promoted while release promotion plan should_block is true")
    authorization = authorize_release_operation(
        resolved_project_root,
        runtime_root=resolved_runtime_root,
        policy_path=access_policy_path,
        actor_id=normalized_executor,
        action="promotion_record",
        target_channel=str(plan.get("target_channel") or target_channel or "").strip().lower(),
        target_environment=str(plan.get("target_environment") or target_environment or "").strip(),
        decision=normalized_decision,
        required=normalized_decision in _EXECUTED_DECISIONS,
    )
    if normalized_decision in _EXECUTED_DECISIONS and str(authorization.get("status") or "") == "blocked":
        raise ValueError(f"release promotion authorization failed: {authorization.get('reason') or 'blocked'}")

    raw_manifest = _load_raw_history_manifest(resolved_history_path)
    all_items = [dict(item) for item in list(raw_manifest.get("items") or []) if isinstance(item, dict)]
    release_summary = dict(plan.get("release_candidate_checklist", {}).get("release_summary") or {})
    evidence_bundle = dict(plan.get("evidence_bundle") or {})
    review_bundle = dict(plan.get("review_bundle") or {})
    deployment_rehearsal = dict(plan.get("deployment_rehearsal") or {})
    rollback_rehearsal = dict(plan.get("rollback_rehearsal") or {})
    release_distribution_bundle = dict(plan.get("release_distribution_bundle") or {})
    release_delivery_readiness = normalize_release_delivery_readiness(plan.get("release_delivery_readiness"))
    release_live_ci_summary = dict(plan.get("release_live_ci_summary") or {})
    release_live_ci_details = dict(release_live_ci_summary.get("details") or {})
    release_live_dispatch_audit = dict(release_live_ci_details.get("dispatch_audit") or {})
    release_live_ci_runtime_assembly = dict(
        release_live_ci_details.get("runtime_assembly")
        or plan.get("runtime_assembly_snapshot")
        or {}
    )
    release_live_ci_event_stream = dict(release_live_ci_details.get("event_stream") or {})
    release_live_ci_workflow_steps = [
        {
            "step_id": str(dict(item).get("step_id") or "").strip(),
            "label": str(dict(item).get("label") or "").strip(),
            "status": str(dict(item).get("status") or "").strip(),
            "outcome": str(dict(item).get("outcome") or "").strip(),
            "always_run": bool(dict(item).get("always_run")),
            "message": str(dict(item).get("message") or "").strip(),
        }
        for item in list(release_live_ci_details.get("workflow_steps") or [])
        if isinstance(item, dict)
    ]
    release_live_ci_failed_workflow_steps = [
        str(step.get("step_id") or step.get("label") or "").strip()
        for step in release_live_ci_workflow_steps
        if str(step.get("status") or "").strip().lower() in {"warning", "blocked"}
    ]
    recorded_at = datetime.now(timezone.utc).isoformat()
    record = {
        "record_id": _build_record_id(recorded_at, normalized_decision),
        "recorded_at": recorded_at,
        "decision": normalized_decision,
        "target_channel": str(plan.get("target_channel") or target_channel or "").strip(),
        "target_environment": str(plan.get("target_environment") or target_environment or "").strip(),
        "promotion_target_label": str(plan.get("promotion_target_label") or "").strip(),
        "executed_by": normalized_executor,
        "note": normalized_note,
        "signoff_source": normalized_signoff_source,
        "plan_status": str(plan.get("status") or "").strip(),
        "should_block": bool(plan.get("should_block")),
        "blocking_checks": list(plan.get("blocking_checks") or []),
        "warning_checks": list(plan.get("warning_checks") or []),
        "missing_signoffs": list(plan.get("missing_signoffs") or []),
        "review_followup_actions": list(review_bundle.get("review_followup_actions") or []),
        "review_followup_action_count": int(review_bundle.get("review_followup_action_count") or 0),
        "selected_scenario_ids": list(plan.get("selected_scenario_ids") or []),
        "selected_provider_ids": list(plan.get("selected_provider_ids") or []),
        "release_manifest_path": str(plan.get("release_manifest_path") or ""),
        "release_build_id": str(release_summary.get("build_id") or ""),
        "release_version": str(release_summary.get("version") or ""),
        "release_channel": str(release_summary.get("channel") or ""),
        "evidence_status": str(evidence_bundle.get("status") or ""),
        "evidence_artifact_count": int(evidence_bundle.get("artifact_count") or 0),
        "distribution_status": str(release_distribution_bundle.get("status") or ""),
        "distribution_summary": str(release_distribution_bundle.get("summary") or ""),
        "distribution_publish_receipts_status": str(release_distribution_bundle.get("publish_receipts_status") or ""),
        "distribution_publish_receipts_summary": _build_release_distribution_publish_receipts_summary(release_distribution_bundle),
        "distribution_publish_receipts_manifest_path": str(release_distribution_bundle.get("publish_receipts_manifest_path") or ""),
        "distribution_publish_receipts_target_count": int(release_distribution_bundle.get("publish_receipts_target_count") or 0),
        "distribution_publish_receipts_completed_targets": list(release_distribution_bundle.get("publish_receipts_completed_targets") or []),
        "distribution_publish_receipts_failed_targets": list(release_distribution_bundle.get("publish_receipts_failed_targets") or []),
        "distribution_publish_receipts_missing_targets": list(release_distribution_bundle.get("publish_receipts_missing_targets") or []),
        "distribution_publish_receipts_follow_up_required": _release_distribution_publish_receipts_follow_up_required(
            release_distribution_bundle
        ),
        "release_delivery_readiness": release_delivery_readiness,
        "release_delivery_readiness_status": str(release_delivery_readiness.get("status") or ""),
        "release_delivery_readiness_summary": str(release_delivery_readiness.get("summary") or ""),
        "release_delivery_readiness_next_actions": list(release_delivery_readiness.get("next_actions") or []),
        "release_delivery_readiness_next_action_count": len(list(release_delivery_readiness.get("next_actions") or [])),
        "release_delivery_readiness_blocking_checks": list(release_delivery_readiness.get("blocking_checks") or []),
        "release_delivery_readiness_warning_checks": list(release_delivery_readiness.get("warning_checks") or []),
        "release_live_ci_status": str(release_live_ci_summary.get("status") or ""),
        "release_live_ci_path": str(release_live_ci_summary.get("path") or ""),
        "release_live_ci_summary": str(release_live_ci_summary.get("summary") or ""),
        "release_live_ci_summary_markdown_path": str(release_live_ci_details.get("summary_markdown_path") or ""),
        "release_live_dispatch_audit": release_live_dispatch_audit,
        "release_live_dispatch_status": str(release_live_dispatch_audit.get("status") or ""),
        "release_live_dispatch_summary": str(release_live_dispatch_audit.get("summary") or ""),
        "release_live_dispatch_path": str(release_live_dispatch_audit.get("path") or ""),
        "release_live_dispatch_recorded_at": str(release_live_dispatch_audit.get("recorded_at") or ""),
        "release_live_dispatch_triggered_by": str(release_live_dispatch_audit.get("triggered_by") or ""),
        "release_live_dispatch_follow_up_required": bool(release_live_dispatch_audit.get("follow_up_required")),
        "release_live_dispatch_run_status": str(dict(release_live_dispatch_audit.get("run") or {}).get("status") or ""),
        "release_live_dispatch_run_conclusion": str(dict(release_live_dispatch_audit.get("run") or {}).get("conclusion") or ""),
        "release_live_dispatch_run_url": str(dict(release_live_dispatch_audit.get("run") or {}).get("html_url") or ""),
        "release_live_ci_runtime_assembly": release_live_ci_runtime_assembly,
        "release_live_ci_event_stream": release_live_ci_event_stream,
        "release_live_ci_event_stream_path": str(release_live_ci_event_stream.get("path") or ""),
        "release_live_ci_event_stream_status": str(release_live_ci_event_stream.get("status") or ""),
        "release_live_ci_event_count": int(release_live_ci_event_stream.get("event_count") or 0),
        "release_live_ci_latest_event_type": str(release_live_ci_event_stream.get("latest_event_type") or ""),
        "release_live_ci_latest_event_status": str(release_live_ci_event_stream.get("latest_event_status") or ""),
        "release_live_ci_workflow_step_results_path": str(release_live_ci_details.get("workflow_step_results_path") or ""),
        "release_live_ci_workflow_steps": release_live_ci_workflow_steps,
        "release_live_ci_failed_workflow_steps": release_live_ci_failed_workflow_steps,
        "release_live_ci_follow_up_required": bool(release_live_ci_failed_workflow_steps)
        or str(release_live_ci_summary.get("status") or "").strip().lower() in {"warning", "blocked"},
        "deployment_status": str(deployment_rehearsal.get("status") or ""),
        "rollback_status": str(rollback_rehearsal.get("status") or ""),
        "authorization": authorization,
        "request_auth": normalized_request_auth,
        "plan_snapshot": plan,
    }
    all_items.insert(0, record)
    resolved_history_path.parent.mkdir(parents=True, exist_ok=True)
    resolved_history_path.write_text(
        json.dumps({
            "schema_version": RELEASE_PROMOTION_HISTORY_SCHEMA_VERSION,
            "items": all_items,
        }, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    history = build_release_promotion_history(
        resolved_project_root,
        runtime_root=resolved_runtime_root,
        history_path=_relative_to_root(resolved_history_path, resolved_project_root),
        limit=10,
    )
    return {
        "project_root": str(resolved_project_root),
        "history_path": _relative_to_root(resolved_history_path, resolved_project_root),
        "record": dict(history.get("latest_record") or {}),
        "history": history,
        "plan": plan,
    }


def _normalize_decision(value: str, *, allow_empty: bool = False) -> str:
    normalized = str(value or "").strip().lower()
    if not normalized and allow_empty:
        return ""
    return normalized if normalized in _DECISION_VALUES else "planned"


def _normalize_live_ci_status(value: str, *, allow_empty: bool = False) -> str:
    normalized = str(value or "").strip().lower()
    if not normalized and allow_empty:
        return ""
    return normalized if normalized in _LIVE_CI_STATUS_VALUES else "skipped"


def _normalize_dispatch_status(value: str, *, allow_empty: bool = False) -> str:
    normalized = str(value or "").strip().lower()
    if not normalized and allow_empty:
        return ""
    return normalized if normalized in _LIVE_CI_STATUS_VALUES else "skipped"


def _normalize_dispatch_follow_up(value: str, *, allow_empty: bool = False) -> str:
    normalized = str(value or "").strip().lower()
    if not normalized and allow_empty:
        return ""
    if normalized in {"required", "true", "yes"}:
        return "required"
    if normalized in {"clear", "false", "no"}:
        return "clear"
    return "clear"


def _normalize_dispatch_run_status(value: str, *, allow_empty: bool = False) -> str:
    normalized = str(value or "").strip().lower()
    if not normalized and allow_empty:
        return ""
    return normalized


def _normalize_dispatch_run_conclusion(value: str, *, allow_empty: bool = False) -> str:
    normalized = str(value or "").strip().lower()
    if not normalized and allow_empty:
        return ""
    return normalized


def _resolve_project_path(project_root: Path, raw_path: str) -> Path:
    relative = str(raw_path or DEFAULT_RELEASE_PROMOTION_HISTORY_PATH).strip()
    if relative.startswith("res://"):
        relative = relative[6:]
    return (project_root / relative).resolve()


def _relative_to_root(path: Path, project_root: Path) -> str:
    try:
        return path.resolve().relative_to(project_root.resolve()).as_posix()
    except Exception:
        return str(path.resolve())


def _load_raw_history_manifest(history_path: Path) -> Dict[str, Any]:
    if not history_path.exists():
        return {"schema_version": RELEASE_PROMOTION_HISTORY_SCHEMA_VERSION, "items": []}
    try:
        payload = json.loads(history_path.read_text(encoding="utf-8"))
        if isinstance(payload, dict):
            return payload
    except Exception:
        pass
    return {"schema_version": RELEASE_PROMOTION_HISTORY_SCHEMA_VERSION, "items": []}


def _extract_live_ci_status(record: Dict[str, Any] | None) -> str:
    raw = dict(record or {})
    if str(raw.get("release_live_ci_status") or "").strip():
        return _normalize_live_ci_status(str(raw.get("release_live_ci_status") or ""), allow_empty=True)
    plan_snapshot = dict(raw.get("plan_snapshot") or {})
    release_live_ci_summary = dict(plan_snapshot.get("release_live_ci_summary") or {})
    return _normalize_live_ci_status(str(release_live_ci_summary.get("status") or ""), allow_empty=True)


def _extract_dispatch_status(record: Dict[str, Any] | None) -> str:
    raw = dict(record or {})
    if str(raw.get("release_live_dispatch_status") or "").strip():
        return _normalize_dispatch_status(str(raw.get("release_live_dispatch_status") or ""), allow_empty=True)
    plan_snapshot = dict(raw.get("plan_snapshot") or {})
    release_live_ci_summary = dict(plan_snapshot.get("release_live_ci_summary") or {})
    release_live_ci_details = dict(release_live_ci_summary.get("details") or {})
    dispatch_audit = dict(release_live_ci_details.get("dispatch_audit") or {})
    return _normalize_dispatch_status(str(dispatch_audit.get("status") or ""), allow_empty=True)


def _extract_dispatch_follow_up(record: Dict[str, Any] | None) -> str:
    raw = dict(record or {})
    if "release_live_dispatch_follow_up_required" in raw:
        return "required" if bool(raw.get("release_live_dispatch_follow_up_required")) else "clear"
    plan_snapshot = dict(raw.get("plan_snapshot") or {})
    release_live_ci_summary = dict(plan_snapshot.get("release_live_ci_summary") or {})
    release_live_ci_details = dict(release_live_ci_summary.get("details") or {})
    dispatch_audit = dict(release_live_ci_details.get("dispatch_audit") or {})
    return "required" if bool(dispatch_audit.get("follow_up_required")) else "clear"


def _extract_dispatch_run_status(record: Dict[str, Any] | None) -> str:
    raw = dict(record or {})
    if str(raw.get("release_live_dispatch_run_status") or "").strip():
        return _normalize_dispatch_run_status(str(raw.get("release_live_dispatch_run_status") or ""), allow_empty=True)
    plan_snapshot = dict(raw.get("plan_snapshot") or {})
    release_live_ci_summary = dict(plan_snapshot.get("release_live_ci_summary") or {})
    release_live_ci_details = dict(release_live_ci_summary.get("details") or {})
    dispatch_audit = dict(release_live_ci_details.get("dispatch_audit") or {})
    run = dict(dispatch_audit.get("run") or {})
    return _normalize_dispatch_run_status(str(run.get("status") or ""), allow_empty=True)


def _extract_dispatch_run_conclusion(record: Dict[str, Any] | None) -> str:
    raw = dict(record or {})
    if str(raw.get("release_live_dispatch_run_conclusion") or "").strip():
        return _normalize_dispatch_run_conclusion(str(raw.get("release_live_dispatch_run_conclusion") or ""), allow_empty=True)
    plan_snapshot = dict(raw.get("plan_snapshot") or {})
    release_live_ci_summary = dict(plan_snapshot.get("release_live_ci_summary") or {})
    release_live_ci_details = dict(release_live_ci_summary.get("details") or {})
    dispatch_audit = dict(release_live_ci_details.get("dispatch_audit") or {})
    run = dict(dispatch_audit.get("run") or {})
    return _normalize_dispatch_run_conclusion(str(run.get("conclusion") or ""), allow_empty=True)


def _extract_failed_workflow_steps(record: Dict[str, Any] | None) -> List[str]:
    raw = dict(record or {})
    failed_steps = [
        str(item).strip()
        for item in list(raw.get("release_live_ci_failed_workflow_steps") or [])
        if str(item).strip()
    ]
    if failed_steps:
        return failed_steps
    plan_snapshot = dict(raw.get("plan_snapshot") or {})
    release_live_ci_summary = dict(plan_snapshot.get("release_live_ci_summary") or {})
    release_live_ci_details = dict(release_live_ci_summary.get("details") or {})
    workflow_steps = list(raw.get("release_live_ci_workflow_steps") or release_live_ci_details.get("workflow_steps") or [])
    return [
        str(dict(item).get("step_id") or dict(item).get("label") or "").strip()
        for item in workflow_steps
        if isinstance(item, dict)
        and str(dict(item).get("status") or "").strip().lower() in {"warning", "blocked"}
        and str(dict(item).get("step_id") or dict(item).get("label") or "").strip()
    ]


def _extract_delivery_readiness_status(record: Dict[str, Any] | None) -> str:
    raw = dict(record or {})
    if str(raw.get("release_delivery_readiness_status") or "").strip():
        return _normalize_live_ci_status(str(raw.get("release_delivery_readiness_status") or ""), allow_empty=True)
    readiness = dict(raw.get("release_delivery_readiness") or dict(raw.get("plan_snapshot") or {}).get("release_delivery_readiness") or {})
    return _normalize_live_ci_status(str(readiness.get("status") or ""), allow_empty=True)


def _extract_delivery_readiness_actions(record: Dict[str, Any] | None) -> List[str]:
    raw = dict(record or {})
    readiness = dict(raw.get("release_delivery_readiness") or dict(raw.get("plan_snapshot") or {}).get("release_delivery_readiness") or {})
    actions = list(raw.get("release_delivery_readiness_next_actions") or readiness.get("next_actions") or [])
    return [
        str(dict(item).get("action_id") or dict(item).get("id") or "").strip()
        for item in actions
        if isinstance(item, dict) and str(dict(item).get("action_id") or dict(item).get("id") or "").strip()
    ]


def _build_record_id(recorded_at: str, decision: str) -> str:
    compact = recorded_at.replace("-", "").replace(":", "").replace(".", "").replace("+00:00", "Z")
    return f"promotion_{compact}_{decision}"


def _build_distribution_publish_receipts_history_snapshot(record: Dict[str, Any] | None) -> Dict[str, Any]:
    raw = dict(record or {})
    plan_snapshot = dict(raw.get("plan_snapshot") or {})
    release_distribution_bundle = dict(raw.get("release_distribution_bundle") or plan_snapshot.get("release_distribution_bundle") or {})
    completed_targets = list(
        raw.get("distribution_publish_receipts_completed_targets")
        or release_distribution_bundle.get("publish_receipts_completed_targets")
        or []
    )
    failed_targets = list(
        raw.get("distribution_publish_receipts_failed_targets")
        or release_distribution_bundle.get("publish_receipts_failed_targets")
        or []
    )
    missing_targets = list(
        raw.get("distribution_publish_receipts_missing_targets")
        or release_distribution_bundle.get("publish_receipts_missing_targets")
        or []
    )
    summary = str(raw.get("distribution_publish_receipts_summary") or "").strip() or _build_release_distribution_publish_receipts_summary(
        release_distribution_bundle
    )
    follow_up_required = bool(raw.get("distribution_publish_receipts_follow_up_required"))
    if not follow_up_required:
        follow_up_required = _release_distribution_publish_receipts_follow_up_required(release_distribution_bundle)
    status = str(
        raw.get("distribution_publish_receipts_status")
        or release_distribution_bundle.get("publish_receipts_status")
        or ""
    ).strip().lower()
    return {
        "status": status or "skipped",
        "summary": summary,
        "completed_targets": completed_targets,
        "failed_targets": failed_targets,
        "missing_targets": missing_targets,
        "follow_up_required": follow_up_required,
    }


def _build_release_live_ci_history_snapshot(record: Dict[str, Any] | None) -> Dict[str, Any]:
    raw = dict(record or {})
    plan_snapshot = dict(raw.get("plan_snapshot") or {})
    release_live_ci_summary = dict(plan_snapshot.get("release_live_ci_summary") or {})
    release_live_ci_details = dict(release_live_ci_summary.get("details") or {})
    runtime_assembly = dict(
        raw.get("release_live_ci_runtime_assembly")
        or plan_snapshot.get("runtime_assembly_snapshot")
        or release_live_ci_details.get("runtime_assembly")
        or {}
    )
    event_stream = dict(
        raw.get("release_live_ci_event_stream")
        or release_live_ci_details.get("event_stream")
        or {}
    )
    failed_workflow_steps = _extract_failed_workflow_steps(raw)
    status = str(raw.get("release_live_ci_status") or release_live_ci_summary.get("status") or "").strip().lower()
    summary = str(raw.get("release_live_ci_summary") or release_live_ci_summary.get("summary") or "").strip()
    return {
        "status": status or "skipped",
        "summary": summary,
        "runtime_assembly": runtime_assembly,
        "event_stream": event_stream,
        "workflow_step_results_path": str(
            raw.get("release_live_ci_workflow_step_results_path")
            or release_live_ci_details.get("workflow_step_results_path")
            or ""
        ).strip(),
        "failed_workflow_steps": failed_workflow_steps,
        "follow_up_required": bool(raw.get("release_live_ci_follow_up_required"))
        or bool(failed_workflow_steps)
        or status in {"warning", "blocked"},
    }


def _build_release_live_dispatch_history_snapshot(record: Dict[str, Any] | None) -> Dict[str, Any]:
    raw = dict(record or {})
    plan_snapshot = dict(raw.get("plan_snapshot") or {})
    release_live_ci_summary = dict(plan_snapshot.get("release_live_ci_summary") or {})
    release_live_ci_details = dict(release_live_ci_summary.get("details") or {})
    audit = normalize_release_live_dispatch_audit(
        raw.get("release_live_dispatch_audit")
        or release_live_ci_details.get("dispatch_audit")
    )
    return {
        "audit": audit,
        "status": str(raw.get("release_live_dispatch_status") or audit.get("status") or "").strip().lower() or "skipped",
        "summary": str(raw.get("release_live_dispatch_summary") or audit.get("summary") or "").strip(),
        "path": str(raw.get("release_live_dispatch_path") or audit.get("path") or "").strip(),
        "follow_up_required": bool(raw.get("release_live_dispatch_follow_up_required")) or bool(audit.get("follow_up_required")),
    }


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

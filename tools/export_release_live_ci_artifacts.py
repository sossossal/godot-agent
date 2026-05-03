from __future__ import annotations

import argparse
import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from agent_system.tools.doctor import default_doctor_report_path  # noqa: E402
from agent_system.tools.release_distribution import (  # noqa: E402
    default_release_distribution_channel_dir,
    default_release_distribution_publish_handoff_dir,
    default_release_distribution_publish_receipts_dir,
    default_release_distribution_signing_handoff_dir,
    default_release_distribution_channel_report_path,
    default_release_distribution_install_smoke_report_path,
    default_release_distribution_report_path,
)
from agent_system.tools.release_boundary import (  # noqa: E402
    default_release_distribution_delivery_path,
    default_release_identity_boundary_path,
)
from agent_system.tools.release_live_runner_baseline import (  # noqa: E402
    default_release_live_runner_baseline_report_path,
    default_release_live_runner_profile_path,
)
from agent_system.tools.release_execution import (  # noqa: E402
    build_release_execution_report,
    run_release_execution,
)
from agent_system.tools.release_promotion import (  # noqa: E402
    build_deployment_rehearsal_report,
    build_release_promotion_evidence_report,
    build_release_review_bundle_report,
    build_rollback_rehearsal_report,
)
from agent_system.tools.release_promotion_history import (  # noqa: E402
    DEFAULT_RELEASE_PROMOTION_HISTORY_PATH,
    build_release_promotion_history,
    build_release_promotion_history_report,
)
from agent_system.tools.release_request_auth import (  # noqa: E402
    default_release_request_auth_identity_handoff_dir,
    default_release_request_auth_identity_audit_report_path,
    default_release_request_auth_posture_report_path,
    default_release_request_auth_rotation_audit_report_path,
)
from agent_system.tools.release_delivery_readiness import export_release_delivery_readiness  # noqa: E402
from agent_system.tools.release_live_event_stream import (  # noqa: E402
    build_release_live_event_stream,
    build_release_live_event_stream_report_lines,
)
from agent_system.tools.release_runtime_assembly import (  # noqa: E402
    build_release_runtime_assembly_report_lines,
    build_release_runtime_assembly_snapshot,
)
from tools.dispatch_release_live_gates import (  # noqa: E402
    build_release_live_dispatch_audit_report_lines,
    load_release_live_dispatch_audit,
)
from agent_system.contracts import normalize_release_artifact_manifest  # noqa: E402


_AUTOMATED_PROMOTION_CHECK_IDS = {
    "request_auth_posture_gate",
    "request_auth_rotation_audit_gate",
    "request_auth_identity_audit_gate",
    "release_distribution_bundle_gate",
}
_AUTOMATED_PREFLIGHT_CHECK_IDS = {
    "promotion_target",
    "deployment_targets",
    "full_live_validation_lane",
    "release_live_runner_baseline_gate",
}


def _clean_text_list(value: Any) -> list[str]:
    if isinstance(value, str):
        parts = value.replace("\r", "\n").replace(";", "\n").replace(",", "\n").split("\n")
    elif isinstance(value, (list, tuple, set)):
        parts = list(value)
    else:
        return []

    cleaned: list[str] = []
    seen: set[str] = set()
    for item in parts:
        text = str(item).strip()
        if not text or text in seen:
            continue
        cleaned.append(text)
        seen.add(text)
    return cleaned


def _resolve_relative_to(root: Path, raw_path: str) -> Path:
    candidate = Path(str(raw_path or "").strip())
    if not str(candidate):
        return root.resolve()
    if candidate.is_absolute():
        return candidate.resolve()
    return (root / candidate).resolve()


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _load_json_if_exists(path: Path) -> dict[str, Any]:
    if not path.exists() or not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def _load_json_value_if_exists(path: Path) -> Any:
    if not path.exists() or not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception:
        return None


def _copy_file(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)


def _copy_tree(source: Path, destination: Path) -> None:
    if destination.exists():
        shutil.rmtree(destination, ignore_errors=True)
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(source, destination)


def _status_rank(status: str) -> int:
    normalized = str(status or "").strip().lower()
    if normalized == "blocked":
        return 3
    if normalized == "warning":
        return 2
    if normalized == "passed":
        return 1
    return 0


def _worst_status(statuses: list[str]) -> str:
    if not statuses:
        return "skipped"
    return max(statuses, key=_status_rank)


def _copy_if_exists(source: Path, destination: Path, generated_files: list[Path]) -> bool:
    if source.exists() and source.is_file():
        _copy_file(source, destination)
        generated_files.append(destination)
        return True
    return False


def _copy_tree_if_exists(source: Path, destination: Path, generated_files: list[Path]) -> None:
    if source.exists() and source.is_dir():
        _copy_tree(source, destination)
        generated_files.extend(path for path in destination.rglob("*") if path.is_file())


def _render_list(values: Any) -> str:
    cleaned = _clean_text_list(values)
    return ", ".join(cleaned) if cleaned else "-"


def _normalize_flow_statuses(value: Any) -> dict[str, str]:
    if not isinstance(value, dict):
        return {}

    normalized: dict[str, str] = {}
    for raw_key, raw_value in value.items():
        key = str(raw_key).strip()
        if not key or (key != "flow" and not key.endswith("_flow")):
            continue
        status = str(raw_value).strip().lower()
        if status in {"passed", "warning", "blocked", "skipped"}:
            normalized[key] = status
    return normalized


def _normalize_workflow_step_status(raw_status: Any, raw_outcome: Any) -> str:
    status = str(raw_status or "").strip().lower()
    if status in {"passed", "warning", "blocked", "skipped", "pending"}:
        return status

    outcome = str(raw_outcome or "").strip().lower()
    if outcome in {"success", "passed", "completed"}:
        return "passed"
    if outcome in {"failure", "failed", "cancelled", "timed_out"}:
        return "blocked"
    if outcome in {"skipped"}:
        return "skipped"
    if outcome in {"pending", "queued", "in_progress", "running"}:
        return "pending"
    return "skipped"


def _normalize_workflow_steps(value: Any) -> list[dict[str, Any]]:
    raw_items: list[Any]
    if isinstance(value, dict):
        raw_items = list(value.get("steps") or [])
    elif isinstance(value, list):
        raw_items = value
    else:
        return []

    steps: list[dict[str, Any]] = []
    for index, item in enumerate(raw_items, start=1):
        if not isinstance(item, dict):
            continue
        raw = dict(item)
        step_id = str(raw.get("step_id") or raw.get("id") or f"step_{index}").strip() or f"step_{index}"
        outcome = str(raw.get("outcome") or raw.get("conclusion") or "").strip().lower()
        steps.append({
            "step_id": step_id,
            "label": str(raw.get("label") or raw.get("name") or step_id).strip() or step_id,
            "status": _normalize_workflow_step_status(raw.get("status"), outcome),
            "outcome": outcome or "",
            "always_run": bool(raw.get("always_run")),
            "message": str(raw.get("message") or raw.get("error") or "").strip(),
        })
    return steps


def _route_kind_for_live_invocation(invocation_source: str) -> str:
    normalized = str(invocation_source or "").strip().lower()
    if normalized == "github_workflow":
        return "github_workflow"
    return "local_replay"


def _build_runtime_lane_summaries(full_live_validation: dict[str, Any]) -> list[dict[str, Any]]:
    details = dict(full_live_validation.get("details") or {})
    raw_items = list(details.get("lane_artifacts") or [])
    if not raw_items:
        raw_items = list(details.get("step_statuses") or [])

    lanes: list[dict[str, Any]] = []
    for index, item in enumerate(raw_items, start=1):
        if not isinstance(item, dict):
            continue
        raw = dict(item)
        lane_id = str(raw.get("lane_id") or raw.get("id") or f"lane_{index}").strip() or f"lane_{index}"
        lanes.append({
            "lane_id": lane_id,
            "label": str(raw.get("label") or raw.get("lane_id") or raw.get("id") or lane_id).strip() or lane_id,
            "status": str(raw.get("status") or "skipped").strip() or "skipped",
            "summary": str(raw.get("summary") or "").strip(),
            "report_path": str(raw.get("report_path") or "").strip(),
            "artifact_paths": _clean_text_list(raw.get("artifact_paths")),
            "flow_statuses": _normalize_flow_statuses(raw.get("flow_statuses")),
        })
    return lanes


def _build_execution_readiness_summary(execution_status: dict[str, Any]) -> dict[str, Any]:
    latest_execution = dict(execution_status.get("latest_execution") or {})
    actions = [dict(item) for item in list(latest_execution.get("release_delivery_readiness_next_actions") or [])]
    return {
        "status": str(latest_execution.get("release_delivery_readiness_status") or "warning"),
        "summary": str(latest_execution.get("release_delivery_readiness_summary") or ""),
        "next_action_count": int(latest_execution.get("release_delivery_readiness_next_action_count") or len(actions)),
        "next_action_ids": [
            str(item.get("action_id") or "").strip()
            for item in actions
            if str(item.get("action_id") or "").strip()
        ],
        "blocking_checks": [
            str(item).strip()
            for item in list(latest_execution.get("release_delivery_readiness_blocking_checks") or [])
            if str(item).strip()
        ],
        "warning_checks": [
            str(item).strip()
            for item in list(latest_execution.get("release_delivery_readiness_warning_checks") or [])
            if str(item).strip()
        ],
    }


def _collect_automated_gate(
    plan: dict[str, Any],
    *,
    fail_on_warnings: bool,
) -> dict[str, Any]:
    evaluated_checks: list[dict[str, Any]] = []
    seen: set[str] = set()

    for item in list(plan.get("checklist") or []):
        check_id = str(item.get("item_id") or "").strip()
        if check_id not in _AUTOMATED_PROMOTION_CHECK_IDS or check_id in seen:
            continue
        seen.add(check_id)
        evaluated_checks.append({
            "check_id": check_id,
            "label": str(item.get("label") or check_id),
            "status": str(item.get("status") or "skipped"),
            "source": "promotion_checklist",
            "required": bool(item.get("required")),
            "message": str(item.get("message") or ""),
        })

    for item in list(plan.get("deployment_rehearsal", {}).get("preflight_checks") or []):
        check_id = str(item.get("check_id") or "").strip()
        if check_id not in _AUTOMATED_PREFLIGHT_CHECK_IDS or check_id in seen:
            continue
        seen.add(check_id)
        evaluated_checks.append({
            "check_id": check_id,
            "label": str(item.get("label") or check_id),
            "status": str(item.get("status") or "skipped"),
            "source": "deployment_preflight",
            "required": bool(item.get("required")),
            "message": str(item.get("message") or ""),
        })

    blocked_checks = [
        str(item.get("check_id") or "")
        for item in evaluated_checks
        if str(item.get("status") or "").strip().lower() == "blocked"
    ]
    warning_checks = [
        str(item.get("check_id") or "")
        for item in evaluated_checks
        if str(item.get("status") or "").strip().lower() == "warning"
    ]
    status = "blocked" if blocked_checks else ("warning" if warning_checks else "passed")
    should_block = bool(blocked_checks) or (fail_on_warnings and bool(warning_checks))
    if should_block and not blocked_checks and warning_checks:
        status = "warning"

    return {
        "status": status,
        "should_block": should_block,
        "fail_on_warnings": bool(fail_on_warnings),
        "blocking_checks": blocked_checks,
        "warning_checks": warning_checks,
        "evaluated_check_count": len(evaluated_checks),
        "evaluated_checks": evaluated_checks,
    }


def _build_release_live_ci_summary_markdown(summary: dict[str, Any]) -> str:
    ci_gate = dict(summary.get("ci_gate") or {})
    promotion = dict(summary.get("promotion") or {})
    execution = dict(summary.get("execution") or {})
    runtime_gates = dict(summary.get("runtime_gates") or {})
    runtime_lanes = dict(summary.get("runtime_lanes") or {})
    workflow_steps = list(summary.get("workflow_steps") or [])
    human_signoffs = dict(summary.get("human_signoffs") or {})
    invocation = dict(summary.get("invocation") or {})
    runtime_assembly = dict(summary.get("runtime_assembly") or {})
    event_stream = dict(summary.get("event_stream") or {})
    dispatch_audit = dict(summary.get("dispatch_audit") or {})
    artifact_manifest = dict(summary.get("artifact_manifest") or {})
    manifest_readiness = dict(artifact_manifest.get("execution_delivery_readiness") or {})
    manifest_lanes = list(dict(artifact_manifest.get("runtime_lanes") or {}).get("full_live_validation") or [])
    report_files = dict(summary.get("report_files") or {})
    snapshot_paths = dict(summary.get("snapshot_paths") or {})

    lines = [
        "# Release Live CI Summary",
        "",
        "## Release",
        f"- Generated At: {summary.get('generated_at') or '-'}",
        (
            f"- Build: {summary.get('release_build_id') or '-'} / "
            f"Version: {summary.get('release_version') or '-'} / "
            f"Channel: {summary.get('release_channel') or summary.get('target_channel') or '-'}"
        ),
        (
            f"- Target: channel={summary.get('target_channel') or '-'} / "
            f"environment={summary.get('target_environment') or '-'}"
        ),
        f"- Manifest: {summary.get('release_manifest_path') or '-'}",
        "",
        "## Invocation",
        (
            f"- Source: {invocation.get('source') or '-'} / "
            f"mode={invocation.get('mode') or '-'} / "
            f"fail_on_warnings={bool(invocation.get('fail_on_warnings'))}"
        ),
        (
            f"- Executed By: {invocation.get('executed_by') or '-'} / "
            f"note={invocation.get('note') or '-'}"
        ),
        f"- Providers: {_render_list(invocation.get('providers'))}",
        f"- Approvers: {_render_list(invocation.get('approvers'))}",
        "",
        "## Runtime Assembly",
    ]
    lines.extend(build_release_runtime_assembly_report_lines(runtime_assembly))
    lines.extend([
        "",
        "## Event Stream",
    ])
    lines.extend(build_release_live_event_stream_report_lines(event_stream))
    dispatch_audit_lines = build_release_live_dispatch_audit_report_lines(dispatch_audit)
    if dispatch_audit_lines:
        lines.extend([
            "",
            "## Workflow Dispatch Audit",
        ])
        lines.extend(dispatch_audit_lines)
    if artifact_manifest:
        lines.extend([
            "",
            "## Artifact Manifest",
            (
                f"- Contract: {artifact_manifest.get('schema_version') or '-'} / "
                f"build={artifact_manifest.get('release_build_id') or '-'} / "
                f"version={artifact_manifest.get('release_version') or '-'} / "
                f"channel={artifact_manifest.get('release_channel') or '-'}"
            ),
            f"- Manifest Path: {artifact_manifest.get('manifest_path') or 'artifact_manifest.json'}",
            (
                f"- Generated Files: {len(list(artifact_manifest.get('generated_files') or []))} / "
                f"full_live_validation_lanes={len(manifest_lanes)}"
            ),
            (
                f"- Execution Delivery Readiness: status={manifest_readiness.get('status') or '-'} / "
                f"next_actions={manifest_readiness.get('next_action_count') if manifest_readiness.get('next_action_count') is not None else len(list(manifest_readiness.get('next_action_ids') or []))} / "
                f"ids={_render_list(manifest_readiness.get('next_action_ids'))}"
            ),
            f"- Blocking Checks: {_render_list(manifest_readiness.get('blocking_checks'))}",
            f"- Warning Checks: {_render_list(manifest_readiness.get('warning_checks'))}",
        ])
    lines.extend([
        "",
        "## Automated Gate",
        (
            f"- CI Gate: status={ci_gate.get('status') or '-'} / "
            f"should_block={bool(ci_gate.get('should_block'))} / "
            f"fail_on_warnings={bool(ci_gate.get('fail_on_warnings'))}"
        ),
        f"- Blocking Checks: {_render_list(ci_gate.get('blocking_checks'))}",
        f"- Warning Checks: {_render_list(ci_gate.get('warning_checks'))}",
        f"- Evaluated Check Count: {int(ci_gate.get('evaluated_check_count') or 0)}",
        "",
        "## Runtime Gates",
        (
            f"- Runner Baseline: {runtime_gates.get('release_live_runner_baseline_status') or '-'} "
            f"(profile={runtime_gates.get('release_live_runner_profile_id') or '-'} / "
            f"name={runtime_gates.get('release_live_runner_name') or '-'} / "
            f"os={runtime_gates.get('release_live_runner_os') or '-'} / "
            f"arch={runtime_gates.get('release_live_runner_arch') or '-'} / "
            f"labels={_render_list(runtime_gates.get('release_live_runner_labels'))})"
        ),
        f"- Clean Machine Bootstrap: {runtime_gates.get('clean_machine_bootstrap_status') or '-'}",
        f"- Full Live Validation: {runtime_gates.get('full_live_validation_status') or '-'}",
        (
            f"- Distribution: bundle={runtime_gates.get('distribution_bundle_status') or '-'} / "
            f"install_smoke={runtime_gates.get('distribution_install_smoke_status') or '-'} / "
            f"archive={runtime_gates.get('distribution_archive_status') or '-'} / "
            f"channel_index={runtime_gates.get('distribution_channel_index_status') or '-'} / "
            f"signing_handoff={runtime_gates.get('distribution_signing_handoff_status') or '-'} / "
            f"publish_handoff={runtime_gates.get('distribution_publish_handoff_status') or '-'} / "
            f"publish_receipts={runtime_gates.get('distribution_publish_receipts_status') or '-'} / "
            f"delivery={runtime_gates.get('distribution_delivery_status') or '-'} "
            f"(profile={runtime_gates.get('distribution_delivery_profile_id') or '-'})"
        ),
        (
            f"- Request Auth: posture={runtime_gates.get('request_auth_posture_status') or '-'} / "
            f"rotation_audit={runtime_gates.get('request_auth_rotation_audit_status') or '-'} / "
            f"identity_audit={runtime_gates.get('request_auth_identity_audit_status') or '-'} / "
            f"identity_boundary={runtime_gates.get('identity_boundary_status') or '-'} "
            f"(profile={runtime_gates.get('identity_boundary_profile_id') or '-'}) / "
            f"identity_handoff={runtime_gates.get('identity_handoff_status') or '-'} "
            f"(target={runtime_gates.get('identity_handoff_target_id') or '-'})"
        ),
        "",
        "## Promotion And Execution",
        (
            f"- Promotion: status={promotion.get('status') or '-'} / "
            f"should_block={bool(promotion.get('should_block'))} / "
            f"blocking_checks={_render_list(promotion.get('blocking_checks'))} / "
            f"warning_checks={_render_list(promotion.get('warning_checks'))}"
        ),
        (
            f"- Execution: status={execution.get('status') or '-'} / "
            f"should_block={bool(execution.get('should_block'))} / "
            f"operation={execution.get('operation') or '-'} / "
            f"execution_id={execution.get('execution_id') or '-'}"
        ),
        "",
        "## Human Signoffs",
        f"- Status: {human_signoffs.get('status') or '-'}",
        f"- Required: {_render_list(human_signoffs.get('required_signoffs'))}",
        f"- Provided: {_render_list(human_signoffs.get('provided_signoffs'))}",
        f"- Missing: {_render_list(human_signoffs.get('missing_signoffs'))}",
        "",
        "## Live Validation Lanes",
    ])

    full_live_lanes = list(runtime_lanes.get("full_live_validation") or [])
    if full_live_lanes:
        for item in full_live_lanes:
            lines.append(
                "- "
                f"{item.get('lane_id') or '-'} "
                f"[{item.get('status') or '-'}] "
                f"label={item.get('label') or '-'} / "
                f"report={item.get('report_path') or '-'} / "
                f"summary={item.get('summary') or '-'}"
            )
            flow_statuses = _normalize_flow_statuses(item.get("flow_statuses"))
            if flow_statuses:
                lines.append(
                    f"- flows: {', '.join(f'{key}={value}' for key, value in sorted(flow_statuses.items()))}"
                )
    else:
        lines.append("- none")

    lines.extend([
        "",
        "## Workflow Steps",
    ])

    if workflow_steps:
        for item in workflow_steps:
            lines.append(
                "- "
                f"{item.get('step_id') or '-'} "
                f"[{item.get('status') or '-'}] "
                f"label={item.get('label') or '-'} / "
                f"outcome={item.get('outcome') or '-'} / "
                f"always_run={bool(item.get('always_run'))} / "
                f"message={item.get('message') or '-'}"
            )
    else:
        lines.append("- none")

    lines.extend([
        "",
        "## Evaluated Checks",
    ])

    evaluated_checks = list(ci_gate.get("evaluated_checks") or [])
    if evaluated_checks:
        for item in evaluated_checks:
            lines.append(
                "- "
                f"{item.get('check_id') or '-'} "
                f"[{item.get('status') or '-'}] "
                f"source={item.get('source') or '-'} / "
                f"label={item.get('label') or '-'} / "
                f"message={item.get('message') or '-'}"
            )
    else:
        lines.append("- No automated checks evaluated")

    lines.extend([
        "",
        "## Artifact Bundle",
        f"- Reports: {_render_list(report_files.values())}",
        f"- Snapshots: {_render_list(snapshot_paths.values())}",
    ])
    return "\n".join(lines) + "\n"


def export_live_ci_artifacts(
    output_dir: Path,
    *,
    project_root: str | Path,
    runtime_root: str | Path,
    target_channel: str,
    target_environment: str,
    release_manifest_path: str,
    approvers: list[str] | None = None,
    providers: list[str] | None = None,
    mode: str = "strict",
    fail_on_warnings: bool = True,
    executed_by: str = "",
    note: str = "ci live gate dry run",
    invocation_source: str = "cli",
    workflow_step_results_path: str | Path | None = None,
) -> dict[str, Any]:
    resolved_project_root = Path(project_root).resolve()
    resolved_runtime_root = Path(runtime_root).resolve()
    normalized_target_channel = str(target_channel or "release").strip().lower() or "release"
    normalized_target_environment = str(target_environment or "").strip() or (
        "production" if normalized_target_channel == "release" else normalized_target_channel
    )
    normalized_approvers = _clean_text_list(approvers or [])
    normalized_providers = _clean_text_list(providers or []) or ["codex", "openai_api"]
    normalized_invocation_source = str(invocation_source or "cli").strip() or "cli"
    route_kind = _route_kind_for_live_invocation(normalized_invocation_source)
    resolved_workflow_step_results_path = (
        _resolve_relative_to(resolved_runtime_root, str(workflow_step_results_path))
        if workflow_step_results_path
        else None
    )
    workflow_steps = _normalize_workflow_steps(
        _load_json_value_if_exists(resolved_workflow_step_results_path)
    ) if resolved_workflow_step_results_path else []

    if output_dir.exists():
        if output_dir.is_dir():
            shutil.rmtree(output_dir, ignore_errors=True)
        else:
            output_dir.unlink()
    output_dir.mkdir(parents=True, exist_ok=True)

    execution_result = run_release_execution(
        resolved_project_root,
        runtime_root=resolved_runtime_root,
        target_channel=normalized_target_channel,
        target_environment=normalized_target_environment,
        release_manifest_path=release_manifest_path,
        approvers=normalized_approvers,
        providers=normalized_providers,
        mode=mode,
        fail_on_warnings=fail_on_warnings,
        operation="dry_run",
        executed_by=executed_by,
        note=note,
    )
    plan = dict(execution_result.get("plan") or {})
    execution_status = dict(execution_result.get("execution_status") or {})
    latest_execution = dict(execution_result.get("execution") or {})
    execution_readiness_summary = _build_execution_readiness_summary(execution_status)
    release_summary = dict(plan.get("release_candidate_checklist", {}).get("release_summary") or {})
    release_distribution_bundle = dict(plan.get("release_distribution_bundle") or {})
    full_live_validation = dict(execution_status.get("full_live_validation") or {})
    runtime_lane_summaries = _build_runtime_lane_summaries(full_live_validation)
    clean_machine_bootstrap = dict(execution_status.get("clean_machine_bootstrap") or {})
    runner_baseline_report_path = _resolve_relative_to(
        resolved_runtime_root,
        default_release_live_runner_baseline_report_path(target_channel=normalized_target_channel),
    )
    runner_baseline = _load_json_if_exists(runner_baseline_report_path)
    request_auth_identity_audit_report = _load_json_if_exists(
        _resolve_relative_to(
            resolved_runtime_root,
            default_release_request_auth_identity_audit_report_path(target_channel=normalized_target_channel),
        )
    )
    request_auth_identity_audit = dict(plan.get("request_auth_identity_audit") or {})
    promotion_history = build_release_promotion_history(
        resolved_project_root,
        runtime_root=resolved_runtime_root,
        history_path=DEFAULT_RELEASE_PROMOTION_HISTORY_PATH,
        target_channel=normalized_target_channel,
        limit=10,
    )

    generated_files: list[Path] = []

    plan_path = output_dir / "release_promotion_plan.json"
    _write_json(plan_path, plan)
    generated_files.append(plan_path)

    evidence_report_path = output_dir / "release_promotion_evidence_bundle.md"
    _write_text(evidence_report_path, build_release_promotion_evidence_report(plan))
    generated_files.append(evidence_report_path)

    review_bundle_path = output_dir / "release_review_bundle.md"
    _write_text(review_bundle_path, build_release_review_bundle_report(plan))
    generated_files.append(review_bundle_path)

    deployment_report_path = output_dir / "release_promotion_deployment_rehearsal.md"
    _write_text(deployment_report_path, build_deployment_rehearsal_report(plan))
    generated_files.append(deployment_report_path)

    rollback_report_path = output_dir / "release_promotion_rollback_rehearsal.md"
    _write_text(rollback_report_path, build_rollback_rehearsal_report(plan))
    generated_files.append(rollback_report_path)

    execution_status_path = output_dir / "release_execution_status.json"
    _write_json(execution_status_path, execution_result)
    generated_files.append(execution_status_path)

    promotion_history_path = output_dir / "release_promotion_history.json"
    _write_json(promotion_history_path, promotion_history)
    generated_files.append(promotion_history_path)

    promotion_history_report_path = output_dir / "release_promotion_history.md"
    _write_text(
        promotion_history_report_path,
        build_release_promotion_history_report(promotion_history),
    )
    generated_files.append(promotion_history_report_path)

    execution_report_path = output_dir / "release_execution_report.md"
    _write_text(execution_report_path, build_release_execution_report(execution_status))
    generated_files.append(execution_report_path)

    runtime_report_mappings = [
        (
            _resolve_relative_to(resolved_runtime_root, "logs/reports/clean_machine_bootstrap.json"),
            output_dir / "runtime_reports" / "clean_machine_bootstrap.json",
        ),
        (
            _resolve_relative_to(resolved_runtime_root, default_doctor_report_path()),
            output_dir / "runtime_reports" / "doctor_self_check.json",
        ),
        (
            _resolve_relative_to(resolved_runtime_root, "logs/reports/full_live_validation.json"),
            output_dir / "runtime_reports" / "full_live_validation.json",
        ),
        (
            runner_baseline_report_path,
            output_dir / "runtime_reports" / f"release_live_runner_baseline_{normalized_target_channel}.json",
        ),
        (
            _resolve_relative_to(
                resolved_runtime_root,
                default_release_request_auth_identity_audit_report_path(target_channel=normalized_target_channel),
            ),
            output_dir / "runtime_reports" / f"release_request_auth_identity_audit_{normalized_target_channel}.json",
        ),
        (
            _resolve_relative_to(
                resolved_runtime_root,
                default_release_request_auth_rotation_audit_report_path(target_channel=normalized_target_channel),
            ),
            output_dir / "runtime_reports" / f"release_request_auth_rotation_audit_{normalized_target_channel}.json",
        ),
        (
            _resolve_relative_to(
                resolved_runtime_root,
                default_release_request_auth_posture_report_path(
                    action="promotion_record",
                    target_channel=normalized_target_channel,
                ),
            ),
            output_dir / "runtime_reports" / f"release_request_auth_posture_promotion_record_{normalized_target_channel}.json",
        ),
        (
            _resolve_relative_to(
                resolved_runtime_root,
                default_release_request_auth_posture_report_path(
                    action="release_execution",
                    target_channel=normalized_target_channel,
                ),
            ),
            output_dir / "runtime_reports" / f"release_request_auth_posture_release_execution_{normalized_target_channel}.json",
        ),
        (
            _resolve_relative_to(
                resolved_runtime_root,
                default_release_distribution_report_path(target_channel=normalized_target_channel),
            ),
            output_dir / "runtime_reports" / f"release_distribution_bundle_{normalized_target_channel}.json",
        ),
        (
            _resolve_relative_to(
                resolved_runtime_root,
                default_release_distribution_install_smoke_report_path(target_channel=normalized_target_channel),
            ),
            output_dir / "runtime_reports" / f"release_distribution_install_smoke_{normalized_target_channel}.json",
        ),
        (
            _resolve_relative_to(
                resolved_runtime_root,
                default_release_distribution_channel_report_path(target_channel=normalized_target_channel),
            ),
            output_dir / "runtime_reports" / f"release_distribution_channel_{normalized_target_channel}.json",
        ),
        (
            _resolve_relative_to(resolved_runtime_root, release_manifest_path),
            output_dir / "runtime_reports" / "release_manifest.json",
        ),
        (
            _resolve_relative_to(
                resolved_runtime_root,
                str(release_summary.get("release_notes_path") or ""),
            ),
            output_dir / "runtime_reports" / "release_notes.md",
        ),
        (
            _resolve_relative_to(
                resolved_runtime_root,
                str(release_summary.get("qa_gate_report_path") or ""),
            ),
            output_dir / "runtime_reports" / "qa_gate_report.md",
        ),
    ]
    for source, destination in runtime_report_mappings:
        _copy_if_exists(source, destination, generated_files)

    full_live_lane_report_dir = _resolve_relative_to(resolved_runtime_root, "logs/reports/full_live_validation_lanes")
    _copy_tree_if_exists(
        full_live_lane_report_dir,
        output_dir / "runtime_reports" / "full_live_validation_lanes",
        generated_files,
    )

    release_dir = str(release_summary.get("release_dir") or "").strip()
    if release_dir:
        _copy_tree_if_exists(
            _resolve_relative_to(resolved_runtime_root, release_dir),
            output_dir / "release_bundle",
            generated_files,
        )

    bundle_dir = str(release_distribution_bundle.get("bundle_dir") or "").strip()
    if bundle_dir:
        _copy_tree_if_exists(
            _resolve_relative_to(resolved_runtime_root, bundle_dir),
            output_dir / "release_distribution_bundle",
            generated_files,
        )

    archive_dir = str(release_distribution_bundle.get("archive_dir") or "").strip()
    if archive_dir:
        _copy_tree_if_exists(
            _resolve_relative_to(resolved_runtime_root, archive_dir),
            output_dir / "release_distribution_archive",
            generated_files,
        )

    channel_dir = str(release_distribution_bundle.get("channel_index_dir") or "").strip() or default_release_distribution_channel_dir(
        target_channel=normalized_target_channel,
    )
    _copy_tree_if_exists(
        _resolve_relative_to(resolved_runtime_root, channel_dir),
        output_dir / "release_distribution_channel",
        generated_files,
    )
    handoff_dir = str(release_distribution_bundle.get("handoff_dir") or "").strip()
    if handoff_dir:
        _copy_tree_if_exists(
            _resolve_relative_to(resolved_runtime_root, handoff_dir),
            output_dir / "release_distribution_handoff",
            generated_files,
        )
    signing_handoff_dir = str(release_distribution_bundle.get("signing_handoff_dir") or "").strip() or default_release_distribution_signing_handoff_dir(
        target_channel=normalized_target_channel,
        build_id=str(release_distribution_bundle.get("build_id") or ""),
    )
    _copy_tree_if_exists(
        _resolve_relative_to(resolved_runtime_root, signing_handoff_dir),
        output_dir / "release_distribution_signing",
        generated_files,
    )
    publish_handoff_dir = str(release_distribution_bundle.get("publish_handoff_dir") or "").strip() or default_release_distribution_publish_handoff_dir(
        target_channel=normalized_target_channel,
        build_id=str(release_distribution_bundle.get("build_id") or ""),
    )
    _copy_tree_if_exists(
        _resolve_relative_to(resolved_runtime_root, publish_handoff_dir),
        output_dir / "release_distribution_publish",
        generated_files,
    )
    publish_receipts_dir = str(release_distribution_bundle.get("publish_receipts_dir") or "").strip() or default_release_distribution_publish_receipts_dir(
        target_channel=normalized_target_channel,
        build_id=str(release_distribution_bundle.get("build_id") or ""),
    )
    _copy_tree_if_exists(
        _resolve_relative_to(resolved_runtime_root, publish_receipts_dir),
        output_dir / "release_distribution_publish_receipts",
        generated_files,
    )
    identity_handoff_dir = str(request_auth_identity_audit.get("identity_handoff_dir") or request_auth_identity_audit_report.get("identity_handoff_dir") or "").strip() or default_release_request_auth_identity_handoff_dir(
        target_channel=normalized_target_channel,
        target_environment=normalized_target_environment,
    )
    _copy_tree_if_exists(
        _resolve_relative_to(resolved_runtime_root, identity_handoff_dir),
        output_dir / "release_request_auth_identity_handoff",
        generated_files,
    )

    deployment_mappings = [
        (
            resolved_project_root / default_release_live_runner_profile_path(),
            output_dir / "deployment" / "release_live_runner_profile.json",
        ),
        (
            resolved_project_root / "deployment" / "release_identity_registry.json",
            output_dir / "deployment" / "release_identity_registry.json",
        ),
        (
            resolved_project_root / default_release_identity_boundary_path(),
            output_dir / "deployment" / "release_identity_boundary.json",
        ),
        (
            resolved_project_root / "deployment" / "release_access_policy.json",
            output_dir / "deployment" / "release_access_policy.json",
        ),
        (
            resolved_project_root / default_release_distribution_delivery_path(),
            output_dir / "deployment" / "release_distribution_delivery.json",
        ),
        (
            resolved_project_root / "deployment" / "release_promotion_history.json",
            output_dir / "deployment" / "release_promotion_history.json",
        ),
        (
            resolved_project_root / "deployment" / "release_execution_status.json",
            output_dir / "deployment" / "release_execution_status.json",
        ),
        (
            resolved_project_root / "deployment" / "release_channels.json",
            output_dir / "deployment" / "release_channels.json",
        ),
    ]
    for source, destination in deployment_mappings:
        _copy_if_exists(source, destination, generated_files)
    if resolved_workflow_step_results_path and resolved_workflow_step_results_path.exists():
        _copy_if_exists(
            resolved_workflow_step_results_path,
            output_dir / "release_live_ci_workflow_steps.json",
            generated_files,
        )
    for source_path, destination in (
        (
            resolved_runtime_root / "logs" / "reports" / "release_live_fixture.json",
            output_dir / "release_live_fixture.json",
        ),
        (
            resolved_runtime_root / "logs" / "reports" / "release_live_fixture.md",
            output_dir / "release_live_fixture.md",
        ),
    ):
        _copy_if_exists(source_path, destination, generated_files)

    ci_gate = _collect_automated_gate(
        plan,
        fail_on_warnings=fail_on_warnings,
    )
    human_signoffs = {
        "status": "passed" if not list(plan.get("missing_signoffs") or []) else "warning",
        "required_signoffs": list(plan.get("required_signoffs") or []),
        "provided_signoffs": list(plan.get("provided_signoffs") or []),
        "missing_signoffs": list(plan.get("missing_signoffs") or []),
    }
    runtime_assembly = build_release_runtime_assembly_snapshot(
        resolved_project_root,
        runtime_root=resolved_runtime_root,
        route_kind=route_kind,
        target_channel=normalized_target_channel,
        target_environment=normalized_target_environment,
        actor_id=str(executed_by or "").strip(),
        invocation_source=normalized_invocation_source,
        route_id=f"{route_kind}:{normalized_target_channel}:{normalized_target_environment}",
        session_id=str(release_summary.get("build_id") or "").strip(),
        runner_baseline=runner_baseline,
    )
    generated_at = datetime.now(timezone.utc).isoformat()
    dispatch_audit = {}
    for source_path, root in (
        (resolved_runtime_root / "logs" / "reports" / "release_live_ci" / "release_live_dispatch.json", resolved_runtime_root),
        (resolved_project_root / "logs" / "reports" / "release_live_ci" / "release_live_dispatch.json", resolved_project_root),
    ):
        if not source_path.exists():
            continue
        loaded_audit = load_release_live_dispatch_audit(root, artifact_dir="logs/reports/release_live_ci")
        if not loaded_audit:
            continue
        dispatch_audit = dict(loaded_audit)
        dispatch_audit["path"] = "release_live_dispatch.json"
        _copy_if_exists(source_path, output_dir / "release_live_dispatch.json", generated_files)
        break

    dispatch_preflight_report = ""
    dispatch_preflight_markdown = ""
    for source_path, destination in (
        (
            resolved_runtime_root / "logs" / "reports" / "release_live_ci" / "release_live_dispatch_preflight.json",
            output_dir / "release_live_dispatch_preflight.json",
        ),
        (
            resolved_runtime_root / "logs" / "reports" / "release_live_ci" / "release_live_dispatch_preflight.md",
            output_dir / "release_live_dispatch_preflight.md",
        ),
    ):
        if _copy_if_exists(source_path, destination, generated_files):
            if destination.suffix == ".json":
                dispatch_preflight_report = destination.name
            else:
                dispatch_preflight_markdown = destination.name

    event_stream = build_release_live_event_stream(
        generated_at=generated_at,
        target_channel=normalized_target_channel,
        target_environment=normalized_target_environment,
        release_build_id=str(release_summary.get("build_id") or "").strip(),
        release_version=str(release_summary.get("version") or "").strip(),
        release_channel=str(release_summary.get("channel") or "").strip(),
        invocation={
            "source": normalized_invocation_source,
            "approvers": normalized_approvers,
            "providers": normalized_providers,
            "mode": str(mode or "strict").strip() or "strict",
            "fail_on_warnings": bool(fail_on_warnings),
            "executed_by": str(executed_by or "").strip(),
            "note": str(note or "").strip(),
        },
        runtime_assembly=runtime_assembly,
        ci_gate=ci_gate,
        runtime_lanes={
            "full_live_validation": runtime_lane_summaries,
        },
        workflow_steps=workflow_steps,
        human_signoffs=human_signoffs,
        path="release_live_ci_events.json",
        source="live_ci_export",
    )

    summary_payload = {
        "schema_version": "1.0",
        "generated_at": generated_at,
        "project_root": str(resolved_project_root),
        "runtime_root": str(resolved_runtime_root),
        "output_dir": str(output_dir),
        "target_channel": normalized_target_channel,
        "target_environment": normalized_target_environment,
        "release_manifest_path": str(plan.get("release_manifest_path") or release_manifest_path or "").strip(),
        "release_build_id": str(release_summary.get("build_id") or "").strip(),
        "release_version": str(release_summary.get("version") or "").strip(),
        "release_channel": str(release_summary.get("channel") or "").strip(),
        "runtime_assembly": runtime_assembly,
        "event_stream": event_stream,
        "dispatch_audit": dispatch_audit,
        "invocation": {
            "source": normalized_invocation_source,
            "approvers": normalized_approvers,
            "providers": normalized_providers,
            "mode": str(mode or "strict").strip() or "strict",
            "fail_on_warnings": bool(fail_on_warnings),
            "executed_by": str(executed_by or "").strip(),
            "note": str(note or "").strip(),
        },
        "promotion": {
            "status": str(plan.get("status") or "skipped"),
            "should_block": bool(plan.get("should_block")),
            "blocking_checks": list(plan.get("blocking_checks") or []),
            "warning_checks": list(plan.get("warning_checks") or []),
        },
        "execution": {
            "status": str(latest_execution.get("execution_status") or "skipped"),
            "should_block": bool(latest_execution.get("should_block")),
            "blocking_checks": list(latest_execution.get("blocking_checks") or []),
            "warning_checks": list(latest_execution.get("warning_checks") or []),
            "execution_id": str(latest_execution.get("execution_id") or ""),
            "operation": str(latest_execution.get("operation") or "dry_run"),
        },
        "runtime_gates": {
            "release_live_runner_baseline_status": str(runner_baseline.get("status") or ""),
            "release_live_runner_profile_id": str(runner_baseline.get("runner_profile_id") or ""),
            "release_live_runner_name": str(runner_baseline.get("runner_name") or ""),
            "release_live_runner_os": str(runner_baseline.get("runner_os") or ""),
            "release_live_runner_arch": str(runner_baseline.get("runner_arch") or ""),
            "release_live_runner_labels": list(runner_baseline.get("declared_runner_labels") or []),
            "clean_machine_bootstrap_status": str(clean_machine_bootstrap.get("status") or ""),
            "full_live_validation_status": str(full_live_validation.get("status") or ""),
            "distribution_bundle_status": str(release_distribution_bundle.get("status") or ""),
            "distribution_install_smoke_status": str(release_distribution_bundle.get("install_smoke_status") or ""),
            "distribution_archive_status": str(release_distribution_bundle.get("archive_status") or ""),
            "distribution_channel_index_status": str(release_distribution_bundle.get("channel_index_status") or ""),
            "distribution_signing_handoff_status": str(release_distribution_bundle.get("signing_handoff_status") or ""),
            "distribution_publish_handoff_status": str(release_distribution_bundle.get("publish_handoff_status") or ""),
            "distribution_publish_receipts_status": str(release_distribution_bundle.get("publish_receipts_status") or ""),
            "distribution_delivery_status": str(release_distribution_bundle.get("delivery_status") or ""),
            "distribution_delivery_profile_id": str(release_distribution_bundle.get("delivery_profile_id") or ""),
            "request_auth_posture_status": str(plan.get("request_auth_posture", {}).get("status") or ""),
            "request_auth_rotation_audit_status": str(plan.get("request_auth_rotation_audit", {}).get("status") or ""),
            "request_auth_identity_audit_status": str(request_auth_identity_audit.get("status") or request_auth_identity_audit_report.get("status") or ""),
            "identity_boundary_status": str(plan.get("request_auth_posture", {}).get("identity_boundary_status") or ""),
            "identity_boundary_profile_id": str(plan.get("request_auth_posture", {}).get("identity_boundary_profile_id") or ""),
            "identity_handoff_status": str(request_auth_identity_audit.get("identity_handoff_status") or request_auth_identity_audit_report.get("identity_handoff_status") or ""),
            "identity_handoff_target_id": str(request_auth_identity_audit.get("identity_handoff_target_id") or request_auth_identity_audit_report.get("identity_handoff_target_id") or ""),
        },
        "runtime_lanes": {
            "full_live_validation": runtime_lane_summaries,
        },
        "workflow_steps": workflow_steps,
        "human_signoffs": human_signoffs,
        "ci_gate": ci_gate,
        "report_files": {
            "promotion_plan": "release_promotion_plan.json",
            "evidence_bundle": "release_promotion_evidence_bundle.md",
            "review_bundle": "release_review_bundle.md",
            "deployment_rehearsal": "release_promotion_deployment_rehearsal.md",
            "rollback_rehearsal": "release_promotion_rollback_rehearsal.md",
            "promotion_history": "release_promotion_history.json",
            "promotion_history_report": "release_promotion_history.md",
            "execution_status": "release_execution_status.json",
            "execution_report": "release_execution_report.md",
            "summary_markdown": "release_live_ci_summary.md",
            "event_stream": "release_live_ci_events.json",
            "workflow_step_results": "release_live_ci_workflow_steps.json" if workflow_steps else "",
            "release_live_fixture": "release_live_fixture.json" if (output_dir / "release_live_fixture.json").exists() else "",
            "release_live_fixture_report": "release_live_fixture.md" if (output_dir / "release_live_fixture.md").exists() else "",
            "dispatch_audit": "release_live_dispatch.json" if dispatch_audit else "",
            "dispatch_preflight": dispatch_preflight_report,
            "dispatch_preflight_report": dispatch_preflight_markdown,
        },
        "snapshot_paths": {
            "runtime_reports": "runtime_reports",
            "deployment": "deployment",
            "release_bundle": "release_bundle",
            "release_distribution_bundle": "release_distribution_bundle",
            "release_distribution_archive": "release_distribution_archive",
            "release_distribution_channel": "release_distribution_channel",
            "release_distribution_handoff": "release_distribution_handoff",
            "release_distribution_signing": "release_distribution_signing",
            "release_distribution_publish": "release_distribution_publish",
            "release_distribution_publish_receipts": "release_distribution_publish_receipts",
            "release_request_auth_identity_handoff": "release_request_auth_identity_handoff",
        },
    }

    artifact_manifest_path = output_dir / "artifact_manifest.json"
    artifact_manifest_payload = normalize_release_artifact_manifest({
        "project_root": str(resolved_project_root),
        "runtime_root": str(resolved_runtime_root),
        "target_channel": normalized_target_channel,
        "target_environment": normalized_target_environment,
        "mode": "live_release_ci",
        "generated_at": summary_payload["generated_at"],
        "release_build_id": str(release_summary.get("build_id") or "").strip(),
        "release_version": str(release_summary.get("version") or "").strip(),
        "release_channel": str(release_summary.get("channel") or "").strip(),
        "release_summary": release_summary,
        "runtime_assembly": runtime_assembly,
        "event_stream": event_stream,
        "execution_delivery_readiness": execution_readiness_summary,
        "runtime_lanes": {
            "full_live_validation": runtime_lane_summaries,
        },
        "generated_files": [],
    })
    _write_json(
        artifact_manifest_path,
        artifact_manifest_payload,
    )
    summary_payload["artifact_manifest"] = artifact_manifest_payload
    generated_files.append(artifact_manifest_path)

    summary_markdown_path = output_dir / "release_live_ci_summary.md"
    _write_text(summary_markdown_path, _build_release_live_ci_summary_markdown(summary_payload))
    generated_files.append(summary_markdown_path)

    event_stream_path = output_dir / "release_live_ci_events.json"
    _write_json(event_stream_path, event_stream)
    generated_files.append(event_stream_path)

    summary_path = output_dir / "release_live_ci_summary.json"
    summary_payload["generated_files"] = [
        str(path.relative_to(output_dir)).replace("\\", "/")
        for path in generated_files
        if path.exists()
    ]
    _write_json(summary_path, summary_payload)
    generated_files.append(summary_path)

    release_delivery_readiness_json = output_dir / f"release_delivery_readiness_{normalized_target_channel}.json"
    release_delivery_readiness_markdown = output_dir / f"release_delivery_readiness_{normalized_target_channel}.md"
    release_delivery_readiness = export_release_delivery_readiness(
        resolved_project_root,
        runtime_root=resolved_runtime_root,
        target_channel=normalized_target_channel,
        target_environment=normalized_target_environment,
        artifact_dir=str(output_dir),
        report_path=str(release_delivery_readiness_json),
        markdown_path=str(release_delivery_readiness_markdown),
    )
    summary_payload["release_delivery_readiness"] = release_delivery_readiness
    summary_payload["report_files"]["release_delivery_readiness"] = release_delivery_readiness_json.name
    summary_payload["report_files"]["release_delivery_readiness_report"] = release_delivery_readiness_markdown.name
    generated_files.extend([release_delivery_readiness_json, release_delivery_readiness_markdown])

    artifact_manifest_payload = normalize_release_artifact_manifest({
        "project_root": str(resolved_project_root),
        "runtime_root": str(resolved_runtime_root),
        "target_channel": normalized_target_channel,
        "target_environment": normalized_target_environment,
        "mode": "live_release_ci",
        "generated_at": summary_payload["generated_at"],
        "release_build_id": str(release_summary.get("build_id") or "").strip(),
        "release_version": str(release_summary.get("version") or "").strip(),
        "release_channel": str(release_summary.get("channel") or "").strip(),
        "release_summary": release_summary,
        "runtime_assembly": runtime_assembly,
        "event_stream": event_stream,
        "release_delivery_readiness": release_delivery_readiness,
        "execution_delivery_readiness": execution_readiness_summary,
        "runtime_lanes": {
            "full_live_validation": runtime_lane_summaries,
        },
        "generated_files": [
            str(path.relative_to(output_dir)).replace("\\", "/")
            for path in generated_files
            if path.exists()
        ],
    })
    _write_json(artifact_manifest_path, artifact_manifest_payload)
    summary_payload["artifact_manifest"] = artifact_manifest_payload

    summary_payload["generated_files"] = [
        str(path.relative_to(output_dir)).replace("\\", "/")
        for path in generated_files
        if path.exists()
    ]
    _write_text(summary_markdown_path, _build_release_live_ci_summary_markdown(summary_payload))
    _write_json(summary_path, summary_payload)
    return {
        "output_dir": str(output_dir),
        "generated_files": generated_files,
        "summary_path": str(summary_path),
        "summary_markdown_path": str(summary_markdown_path),
        "summary": summary_payload,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Export real live/browser/release CI artifacts from the current runtime.")
    parser.add_argument("--project-root", default=str(REPO_ROOT), help="Project root containing deployment manifests.")
    parser.add_argument("--runtime-root", default=str(REPO_ROOT), help="Runtime root containing logs/reports and api_server/static/dist.")
    parser.add_argument("--output-dir", default=str(REPO_ROOT / "logs" / "reports" / "release_live_ci"), help="Directory to write exported live CI artifacts into.")
    parser.add_argument("--channel", default="release", help="Target promotion channel.")
    parser.add_argument("--target-environment", default="production", help="Target environment label.")
    parser.add_argument("--release-manifest-path", default="api_server/static/dist/release_manifest.json", help="Runtime-root-relative release manifest path.")
    parser.add_argument("--approvers", default="", help="Comma-separated approver ids to fold into the promotion plan.")
    parser.add_argument("--providers", default="codex,openai_api", help="Comma-separated provider ids for agent compatibility.")
    parser.add_argument("--mode", default="strict", help="Promotion mode passed into dry-run execution.")
    parser.add_argument("--fail-on-warnings", action="store_true", help="Treat automated warning checks as CI blockers.")
    parser.add_argument("--fail-on-blockers", action="store_true", help="Return a non-zero exit code when the automated CI gate should block.")
    parser.add_argument("--executed-by", default="", help="Optional executor label to record on the dry-run execution.")
    parser.add_argument("--note", default="ci live gate dry run", help="Optional note to persist on the dry-run execution record.")
    parser.add_argument("--invocation-source", default="cli", help="Label describing how this live CI export was invoked.")
    parser.add_argument("--workflow-step-results-path", default="", help="Optional JSON file describing workflow/local replay step outcomes to embed into the live CI summary.")
    args = parser.parse_args(argv)

    result = export_live_ci_artifacts(
        Path(args.output_dir).resolve(),
        project_root=args.project_root,
        runtime_root=args.runtime_root,
        target_channel=args.channel,
        target_environment=args.target_environment,
        release_manifest_path=args.release_manifest_path,
        approvers=_clean_text_list(args.approvers),
        providers=_clean_text_list(args.providers),
        mode=args.mode,
        fail_on_warnings=bool(args.fail_on_warnings),
        executed_by=args.executed_by,
        note=args.note,
        invocation_source=args.invocation_source,
        workflow_step_results_path=args.workflow_step_results_path,
    )
    summary = dict(result.get("summary") or {})
    print(
        json.dumps(
            {
                "ok": True,
                "output_dir": result.get("output_dir"),
                "summary_path": result.get("summary_path"),
                "summary_markdown_path": result.get("summary_markdown_path"),
                "file_count": len(list(result.get("generated_files") or [])),
                "ci_gate_status": summary.get("ci_gate", {}).get("status"),
                "ci_gate_should_block": bool(summary.get("ci_gate", {}).get("should_block")),
                "human_signoff_status": summary.get("human_signoffs", {}).get("status"),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    if args.fail_on_blockers and bool(summary.get("ci_gate", {}).get("should_block")):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

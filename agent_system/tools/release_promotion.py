"""
Release promotion plan builder.

P16 turns the completed RC, matrix, compatibility, collaboration, evidence, and
rehearsal gates into one promotion decision surface for Portal, API, and
external agents.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from agent_system.contracts import (
    RELEASE_PROMOTION_PLAN_SCHEMA_VERSION,
    normalize_release_promotion_plan,
    normalize_release_review_bundle,
)
from agent_system.tools.agent_compatibility import build_agent_compatibility_matrix
from agent_system.tools.build_run_matrix import build_build_run_matrix
from agent_system.tools.doctor import default_doctor_report_path
from agent_system.tools.release_candidate import (
    DEFAULT_RELEASE_MANIFEST_PATH,
    build_release_candidate_checklist,
)
from agent_system.tools.release_distribution import (
    build_release_distribution_bundle,
    build_release_distribution_bundle_report_lines,
)
from agent_system.tools.release_delivery_readiness import (
    build_release_delivery_readiness,
    build_release_delivery_readiness_report_lines,
)
from agent_system.tools.release_live_runner_baseline import (
    default_release_live_runner_baseline_report_path,
    default_release_live_runner_profile_path,
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
from agent_system.tools.scene_ownership import build_scene_ownership_board
from tools.dispatch_release_live_gates import (
    build_release_live_dispatch_audit_report_lines,
    load_release_live_dispatch_audit,
)


DEFAULT_PROMOTION_TARGET_CHANNEL = "staging"
_PROMOTION_CHANNELS = {"qa", "staging", "release"}
_PROMOTION_ENVIRONMENTS = {
    "qa": "internal_qa",
    "staging": "staging",
    "release": "production",
}
_FULL_LIVE_VALIDATION_LANE_REPORT_DIR = "logs/reports/full_live_validation_lanes"
_REQUIRED_SIGNOFFS = {
    "qa": ["qa_lead", "tech_lead"],
    "staging": ["qa_lead", "tech_lead", "producer"],
    "release": ["qa_lead", "tech_lead", "producer", "ops"],
}
_SCENARIOS_BY_CHANNEL = {
    "qa": ["content_pipeline", "release_candidate"],
    "staging": ["vertical_slice_2d", "content_pipeline", "release_candidate"],
    "release": ["vertical_slice_2d", "content_pipeline", "release_candidate"],
}
_DEFAULT_PROVIDER_IDS = ["codex", "openai_api"]


def build_release_promotion_plan(
    project_root: str | Path,
    runtime_root: Optional[str | Path] = None,
    *,
    target_channel: str = "",
    target_environment: str = "",
    release_manifest_path: str = "",
    approvers: Optional[List[str]] = None,
    providers: Optional[List[str]] = None,
    mode: str = "strict",
    fail_on_warnings: bool = False,
) -> Dict[str, Any]:
    resolved_project_root = Path(project_root).resolve()
    resolved_runtime_root = Path(runtime_root or Path.cwd()).resolve()
    normalized_mode = _normalize_mode(mode)
    normalized_target_channel = _normalize_channel(target_channel)
    normalized_target_environment = _normalize_environment(target_environment, normalized_target_channel)
    effective_mode = "strict" if normalized_target_channel == "release" else normalized_mode
    effective_fail_on_warnings = True if normalized_target_channel == "release" else fail_on_warnings
    normalized_approvers = _clean_text_list(approvers)
    normalized_providers = _clean_text_list(providers) or list(_DEFAULT_PROVIDER_IDS)
    selected_scenario_ids = list(_SCENARIOS_BY_CHANNEL[normalized_target_channel])

    release_candidate = build_release_candidate_checklist(
        resolved_project_root,
        runtime_root=resolved_runtime_root,
        release_manifest_path=release_manifest_path or DEFAULT_RELEASE_MANIFEST_PATH,
        mode=effective_mode,
        fail_on_warnings=effective_fail_on_warnings,
    )
    build_run_matrix = build_build_run_matrix(
        resolved_project_root,
        runtime_root=resolved_runtime_root,
        scenario_ids=selected_scenario_ids,
        mode=effective_mode,
        fail_on_warnings=effective_fail_on_warnings,
    )
    scene_ownership_board = build_scene_ownership_board(
        resolved_project_root,
        runtime_root=resolved_runtime_root,
        mode=effective_mode,
        fail_on_warnings=effective_fail_on_warnings,
    )
    agent_compatibility = build_agent_compatibility_matrix(
        resolved_project_root,
        runtime_root=resolved_runtime_root,
        providers=normalized_providers,
    )
    request_auth_posture = build_release_request_auth_posture(
        resolved_project_root,
        runtime_root=resolved_runtime_root,
        action="promotion_record",
        target_channel=normalized_target_channel,
        target_environment=normalized_target_environment,
    )
    request_auth_rotation_audit = build_release_request_auth_rotation_audit(
        resolved_project_root,
        runtime_root=resolved_runtime_root,
        target_channel=normalized_target_channel,
        target_environment=normalized_target_environment,
    )
    request_auth_identity_audit = build_release_request_auth_identity_audit(
        resolved_project_root,
        runtime_root=resolved_runtime_root,
        target_channel=normalized_target_channel,
        target_environment=normalized_target_environment,
    )
    release_distribution_bundle = build_release_distribution_bundle(
        resolved_project_root,
        runtime_root=resolved_runtime_root,
        target_channel=normalized_target_channel,
        target_environment=normalized_target_environment,
        release_manifest_path=release_manifest_path or DEFAULT_RELEASE_MANIFEST_PATH,
    )
    release_live_runner_baseline = _load_release_live_runner_baseline_report(
        resolved_project_root,
        resolved_runtime_root,
        target_channel=normalized_target_channel,
    )
    release_live_ci_summary = _load_release_live_ci_summary(
        resolved_project_root,
        resolved_runtime_root,
        target_channel=normalized_target_channel,
    )
    release_delivery_readiness = build_release_delivery_readiness(
        resolved_project_root,
        runtime_root=resolved_runtime_root,
        target_channel=normalized_target_channel,
        target_environment=normalized_target_environment,
    )

    required_signoffs = list(_REQUIRED_SIGNOFFS[normalized_target_channel])
    missing_signoffs = [item for item in required_signoffs if item not in normalized_approvers]
    release_channel = str(release_candidate.get("release_summary", {}).get("channel") or "").strip().lower()

    evidence_bundle = _build_evidence_bundle(
        resolved_project_root,
        resolved_runtime_root,
        normalized_target_channel,
        normalized_target_environment,
        normalized_approvers,
        missing_signoffs,
        release_candidate,
        build_run_matrix,
        scene_ownership_board,
        release_live_runner_baseline,
        release_live_ci_summary,
        request_auth_posture,
        request_auth_rotation_audit,
        request_auth_identity_audit,
        release_distribution_bundle,
    )
    deployment_rehearsal = _build_deployment_rehearsal(
        resolved_project_root,
        resolved_runtime_root,
        normalized_target_channel,
        normalized_target_environment,
        normalized_approvers,
        missing_signoffs,
        release_candidate,
        build_run_matrix,
        scene_ownership_board,
        release_live_runner_baseline,
        release_live_ci_summary,
        request_auth_posture,
        request_auth_rotation_audit,
        request_auth_identity_audit,
        release_distribution_bundle,
    )
    rollback_rehearsal = _build_rollback_rehearsal(
        normalized_target_channel,
        normalized_target_environment,
        release_candidate,
        build_run_matrix,
    )
    review_bundle = _build_review_bundle(
        resolved_project_root,
        resolved_runtime_root,
        normalized_target_channel,
        normalized_target_environment,
        required_signoffs,
        normalized_approvers,
        missing_signoffs,
        release_candidate,
        release_live_runner_baseline,
        release_live_ci_summary,
        request_auth_posture,
        request_auth_rotation_audit,
        request_auth_identity_audit,
        release_distribution_bundle,
    )

    checklist = [
        _item(
            "release_candidate_gate",
            "Release Candidate Gate",
            _status_from_contract(release_candidate),
            f"RC status: {release_candidate.get('status') or 'unknown'} / should_block={bool(release_candidate.get('should_block'))}",
            required=True,
            details={
                "blocking_checks": list(release_candidate.get("blocking_checks") or []),
                "warning_checks": list(release_candidate.get("warning_checks") or []),
            },
        ),
        _item(
            "build_run_matrix_gate",
            "Build / Run Matrix",
            _status_from_contract(build_run_matrix),
            f"Matrix rows: {build_run_matrix.get('row_count') or 0} / default sequence: {', '.join(list(build_run_matrix.get('default_sequence') or [])) or '-'}",
            required=True,
            details={
                "blocking_rows": list(build_run_matrix.get("blocking_rows") or []),
                "warning_rows": list(build_run_matrix.get("warning_rows") or []),
            },
        ),
        _item(
            "agent_compatibility_gate",
            "Agent Compatibility",
            _status_from_agent_compat(agent_compatibility),
            f"Providers: {agent_compatibility.get('provider_count') or 0} / status: {agent_compatibility.get('status') or 'unknown'}",
            required=True,
            details={
                "blocked_providers": list(agent_compatibility.get("blocked_providers") or []),
                "warning_providers": list(agent_compatibility.get("warning_providers") or []),
                "blocked_surfaces": list(agent_compatibility.get("blocked_surfaces") or []),
            },
        ),
        _item(
            "release_live_runner_baseline_gate",
            "Release Live Runner Baseline",
            _release_live_runner_baseline_gate_status(
                release_live_runner_baseline,
                target_channel=normalized_target_channel,
            ),
            str(release_live_runner_baseline.get("summary") or "release live runner baseline not evaluated"),
            required=normalized_target_channel == "release",
            details=dict(release_live_runner_baseline),
        ),
        _item(
            "release_live_ci_summary_gate",
            "Release Live CI Summary",
            _release_live_ci_summary_gate_status(
                release_live_ci_summary,
                target_channel=normalized_target_channel,
            ),
            str(release_live_ci_summary.get("summary") or "release live ci summary not evaluated"),
            required=normalized_target_channel == "release",
            details=dict(release_live_ci_summary),
        ),
        _item(
            "request_auth_posture_gate",
            "Release Request Auth Posture",
            _request_auth_posture_gate_status(request_auth_posture, target_channel=normalized_target_channel),
            str(request_auth_posture.get("summary") or "release request auth posture not evaluated"),
            required=normalized_target_channel == "release",
            details=dict(request_auth_posture),
        ),
        _item(
            "request_auth_rotation_audit_gate",
            "Release Request Auth Rotation Audit",
            _request_auth_rotation_audit_gate_status(
                request_auth_rotation_audit,
                target_channel=normalized_target_channel,
            ),
            str(request_auth_rotation_audit.get("summary") or "release request auth rotation audit not evaluated"),
            required=normalized_target_channel == "release",
            details=dict(request_auth_rotation_audit),
        ),
        _item(
            "request_auth_identity_audit_gate",
            "Release Request Auth Identity Audit",
            _request_auth_identity_audit_gate_status(
                request_auth_identity_audit,
                target_channel=normalized_target_channel,
            ),
            str(request_auth_identity_audit.get("summary") or "release request auth identity audit not evaluated"),
            required=normalized_target_channel == "release",
            details=dict(request_auth_identity_audit),
        ),
        _item(
            "release_distribution_bundle_gate",
            "Release Distribution Bundle",
            _release_distribution_bundle_gate_status(
                release_distribution_bundle,
                target_channel=normalized_target_channel,
            ),
            str(release_distribution_bundle.get("summary") or "release distribution bundle not evaluated"),
            required=normalized_target_channel == "release",
            details=dict(release_distribution_bundle),
        ),
        _item(
            "scene_collaboration_gate",
            "Scene Collaboration",
            _status_from_scene_ownership(scene_ownership_board),
            (
                f"Scenes={scene_ownership_board.get('scene_count') or 0} / missing_owner={scene_ownership_board.get('missing_owner_count') or 0} / locked={scene_ownership_board.get('locked_count') or 0}"
                if int(scene_ownership_board.get("scene_count") or 0) > 0
                else "No managed scenes detected for collaboration board"
            ),
            required=False,
            details={
                "scene_count": int(scene_ownership_board.get("scene_count") or 0),
                "missing_owner_count": int(scene_ownership_board.get("missing_owner_count") or 0),
                "blocking_checks": list(scene_ownership_board.get("blocking_checks") or []),
                "warning_checks": list(scene_ownership_board.get("warning_checks") or []),
            },
        ),
        _item(
            "signoff_gate",
            "Promotion Signoffs",
            "blocked" if missing_signoffs else "passed",
            (
                f"Missing signoffs: {', '.join(missing_signoffs)}"
                if missing_signoffs
                else f"All required signoffs collected: {', '.join(required_signoffs)}"
            ),
            required=True,
            details={
                "required_signoffs": required_signoffs,
                "provided_signoffs": normalized_approvers,
                "missing_signoffs": missing_signoffs,
            },
        ),
        _item(
            "promotion_evidence_bundle",
            "Promotion Evidence Bundle",
            str(evidence_bundle.get("status") or "skipped"),
            (
                f"artifacts={evidence_bundle.get('artifact_count') or 0} / missing={', '.join(list(evidence_bundle.get('missing_artifacts') or [])) or 'none'}"
            ),
            required=True,
            details={
                "missing_artifacts": list(evidence_bundle.get("missing_artifacts") or []),
                "warning_artifacts": list(evidence_bundle.get("warning_artifacts") or []),
            },
        ),
        _item(
            "review_bundle",
            "Release Review Bundle",
            str(review_bundle.get("status") or "skipped"),
            (
                f"scope={review_bundle.get('change_scope_count') or 0} / pending={review_bundle.get('acceptance_pending_count') or 0} / issues={len(list(review_bundle.get('known_issues') or []))}"
            ),
            required=True,
            details={
                "blocking_items": list(review_bundle.get("blocking_items") or []),
                "warning_items": list(review_bundle.get("warning_items") or []),
            },
        ),
        _item(
            "deployment_rehearsal",
            "Deployment Rehearsal",
            str(deployment_rehearsal.get("status") or "skipped"),
            f"lane_sequence={', '.join(list(deployment_rehearsal.get('lane_sequence') or [])) or 'none'}",
            required=True,
            details={
                "blocking_checks": list(deployment_rehearsal.get("blocking_checks") or []),
                "warning_checks": list(deployment_rehearsal.get("warning_checks") or []),
            },
        ),
        _item(
            "rollback_rehearsal",
            "Rollback Rehearsal",
            str(rollback_rehearsal.get("status") or "skipped"),
            rollback_rehearsal.get("rollback_hint") or f"restore_target={rollback_rehearsal.get('restore_target') or '-'}",
            required=True,
            details={
                "restore_target": rollback_rehearsal.get("restore_target") or "",
                "blocking_checks": list(rollback_rehearsal.get("blocking_checks") or []),
                "warning_checks": list(rollback_rehearsal.get("warning_checks") or []),
            },
        ),
        _item(
            "channel_alignment",
            "Channel Alignment",
            "warning" if release_channel and release_channel != normalized_target_channel else "passed",
            (
                f"Build channel={release_channel or '-'} -> target={normalized_target_channel}"
                if release_channel
                else f"Target channel={normalized_target_channel}"
            ),
            required=False,
            details={
                "release_channel": release_channel,
                "target_channel": normalized_target_channel,
            },
        ),
    ]

    promotion_steps = _build_promotion_steps(
        normalized_target_channel,
        normalized_target_environment,
        required_signoffs,
        missing_signoffs,
        build_run_matrix,
        release_candidate,
    )
    recommendations = _build_recommendations(
        checklist,
        build_run_matrix,
        release_candidate,
        scene_ownership_board,
        evidence_bundle,
        review_bundle,
        deployment_rehearsal,
        rollback_rehearsal,
    )
    if str(release_live_runner_baseline.get("status") or "").strip().lower() in {"warning", "blocked"}:
        recommendations.extend(list(release_live_runner_baseline.get("details", {}).get("recommendations") or []))
    release_live_ci_signoffs = dict(release_live_ci_summary.get("details", {}).get("human_signoffs") or {})
    if bool(dict(release_live_ci_summary.get("details", {}).get("ci_gate") or {}).get("should_block")):
        recommendations.append(
            "先补跑 release live CI summary，再推进 promotion；不要在没有最新 release-live-gates 汇总的情况下做最终晋级判断。"
        )
    if list(release_live_ci_signoffs.get("missing_signoffs") or []):
        recommendations.append(
            f"补齐 release live CI signoff: {', '.join(list(release_live_ci_signoffs.get('missing_signoffs') or []))}。"
        )
    if str(request_auth_posture.get("status") or "").strip().lower() in {"warning", "blocked"}:
        recommendations.extend(list(request_auth_posture.get("recommendations") or []))
    if str(request_auth_rotation_audit.get("status") or "").strip().lower() in {"warning", "blocked"}:
        recommendations.extend(list(request_auth_rotation_audit.get("recommendations") or []))
    if str(request_auth_identity_audit.get("status") or "").strip().lower() in {"warning", "blocked"}:
        recommendations.extend(list(request_auth_identity_audit.get("recommendations") or []))
    if str(release_distribution_bundle.get("status") or "").strip().lower() in {"warning", "blocked"}:
        recommendations.extend(list(release_distribution_bundle.get("recommendations") or []))
    if str(release_delivery_readiness.get("status") or "").strip().lower() in {"warning", "blocked"}:
        recommendations.extend(list(release_delivery_readiness.get("recommendations") or []))

    return normalize_release_promotion_plan({
        "project_root": str(resolved_project_root),
        "runtime_root": str(resolved_runtime_root),
        "target_channel": normalized_target_channel,
        "target_environment": normalized_target_environment,
        "promotion_target_label": f"{normalized_target_channel} -> {normalized_target_environment}",
        "release_manifest_path": str(release_candidate.get("release_manifest_path") or release_manifest_path or DEFAULT_RELEASE_MANIFEST_PATH),
        "selected_scenario_ids": selected_scenario_ids,
        "selected_provider_ids": normalized_providers,
        "required_signoffs": required_signoffs,
        "provided_signoffs": normalized_approvers,
        "missing_signoffs": missing_signoffs,
        "mode": effective_mode,
        "fail_on_warnings": effective_fail_on_warnings,
        "release_candidate_checklist": release_candidate,
        "build_run_matrix": build_run_matrix,
        "scene_ownership_board": scene_ownership_board,
        "agent_compatibility_summary": {
            "schema_version": str(agent_compatibility.get("schema_version") or ""),
            "passed": bool(agent_compatibility.get("passed")),
            "status": str(agent_compatibility.get("status") or ""),
            "provider_count": int(agent_compatibility.get("provider_count") or 0),
            "surface_count": int(agent_compatibility.get("surface_count") or 0),
            "blocked_providers": list(agent_compatibility.get("blocked_providers") or []),
            "warning_providers": list(agent_compatibility.get("warning_providers") or []),
            "blocked_surfaces": list(agent_compatibility.get("blocked_surfaces") or []),
        },
        "release_live_runner_baseline": release_live_runner_baseline,
        "release_live_ci_summary": release_live_ci_summary,
        "runtime_assembly_snapshot": dict(release_live_ci_summary.get("details", {}).get("runtime_assembly") or {}),
        "request_auth_posture": request_auth_posture,
        "request_auth_rotation_audit": request_auth_rotation_audit,
        "request_auth_identity_audit": request_auth_identity_audit,
        "release_distribution_bundle": release_distribution_bundle,
        "release_delivery_readiness": release_delivery_readiness,
        "checklist": checklist,
        "evidence_bundle": evidence_bundle,
        "review_bundle": review_bundle,
        "deployment_rehearsal": deployment_rehearsal,
        "rollback_rehearsal": rollback_rehearsal,
        "promotion_steps": promotion_steps,
        "notes": [
            "release promotion plan 把 RC、matrix、兼容性、signoff、evidence bundle 和 rehearsal 收敛成一次晋级决策，不直接执行真实部署。",
            *[str(item) for item in list(request_auth_posture.get("notes") or [])],
            *[str(item) for item in list(request_auth_rotation_audit.get("notes") or [])],
            *[str(item) for item in list(request_auth_identity_audit.get("notes") or [])],
            *[str(item) for item in list(release_distribution_bundle.get("notes") or [])],
            f"Release delivery readiness: {release_delivery_readiness.get('summary') or 'missing'}",
            f"Release live runner baseline: {release_live_runner_baseline.get('summary') or 'missing'}",
            f"Release live CI summary: {release_live_ci_summary.get('summary') or 'missing'}",
            *(
                ["target_channel=release 时已强制启用 strict + fail_on_warnings。"]
                if normalized_target_channel == "release" and (normalized_mode != "strict" or not fail_on_warnings)
                else []
            ),
        ],
        "recommendations": recommendations,
        "contract_versions": {
            "release_promotion_plan": RELEASE_PROMOTION_PLAN_SCHEMA_VERSION,
            "release_candidate_checklist": str(release_candidate.get("schema_version") or ""),
            "build_run_matrix": str(build_run_matrix.get("schema_version") or ""),
            "scene_ownership_board": str(scene_ownership_board.get("schema_version") or ""),
            "agent_provider_compatibility": str(agent_compatibility.get("schema_version") or ""),
            "release_live_runner_baseline": "1.0",
            "release_live_ci_summary": "1.0",
            "release_distribution_bundle": str(release_distribution_bundle.get("schema_version") or ""),
            "release_delivery_readiness": str(release_delivery_readiness.get("schema_version") or ""),
            "release_review_bundle": str(review_bundle.get("schema_version") or ""),
        },
    })


def build_release_promotion_evidence_report(plan: Dict[str, Any]) -> str:
    normalized = normalize_release_promotion_plan(plan)
    evidence = dict(normalized.get("evidence_bundle") or {})
    release_summary = dict(normalized.get("release_candidate_checklist", {}).get("release_summary") or {})
    qa_evidence = dict(release_summary.get("qa_evidence") or {})
    clean_machine_bootstrap = _extract_clean_machine_bootstrap_artifact(evidence)
    full_live_validation = _extract_full_live_validation_artifact(evidence)
    release_live_runner_baseline = dict(normalized.get("release_live_runner_baseline") or {})
    release_live_ci_summary = dict(normalized.get("release_live_ci_summary") or {})
    if not release_live_runner_baseline.get("path"):
        release_live_runner_baseline = _extract_release_live_runner_baseline_artifact(evidence)
    request_auth_posture = dict(normalized.get("request_auth_posture") or {})
    request_auth_rotation_audit = dict(normalized.get("request_auth_rotation_audit") or {})
    request_auth_identity_audit = dict(normalized.get("request_auth_identity_audit") or {})
    release_distribution_bundle = dict(normalized.get("release_distribution_bundle") or {})
    release_delivery_readiness = dict(normalized.get("release_delivery_readiness") or {})
    target_label = normalized.get("promotion_target_label") or f"{normalized.get('target_channel') or '-'} -> {normalized.get('target_environment') or '-'}"
    lines = [
        "# Release Promotion Evidence Bundle",
        "",
        f"- Target: {target_label}",
        f"- Status: {evidence.get('status') or '-'}",
        f"- Build: {release_summary.get('build_id') or '-'} / Version: {release_summary.get('version') or '-'} / Channel: {release_summary.get('channel') or '-'}",
        f"- Artifact Count: {evidence.get('artifact_count') or 0}",
        f"- Missing Artifacts: {', '.join(list(evidence.get('missing_artifacts') or [])) or 'none'}",
        "",
        "## Artifacts",
        "",
    ]
    for item in list(evidence.get("artifacts") or []):
        lines.append(
            f"- {item.get('artifact_id')}: status={item.get('status')} required={item.get('required')} path={item.get('path') or '-'}"
        )
        if item.get("summary"):
            lines.append(f"  - {item.get('summary')}")
    if not list(evidence.get("artifacts") or []):
        lines.append("- none")
    lines.extend([
        "",
        "## Signoffs",
        "",
        f"- Required: {', '.join(list(normalized.get('required_signoffs') or [])) or 'none'}",
        f"- Provided: {', '.join(list(normalized.get('provided_signoffs') or [])) or 'none'}",
        f"- Missing: {', '.join(list(normalized.get('missing_signoffs') or [])) or 'none'}",
        "",
        "## QA Evidence",
        "",
    ])
    lines.extend(_build_release_qa_evidence_report_lines(qa_evidence))
    lines.extend([
        "",
        "## Clean Machine Bootstrap",
        "",
    ])
    lines.extend(_build_clean_machine_bootstrap_report_lines(clean_machine_bootstrap))
    lines.extend([
        "",
        "## Full Live Validation",
        "",
    ])
    lines.extend(_build_full_live_validation_report_lines(full_live_validation))
    lines.extend([
        "",
        "## Release Live CI Summary",
        "",
    ])
    lines.extend(_build_release_live_ci_summary_report_lines(release_live_ci_summary))
    lines.extend([
        "",
        "## Release Live Runner Baseline",
        "",
    ])
    lines.extend(_build_release_live_runner_baseline_report_lines(release_live_runner_baseline))
    lines.extend([
        "",
        "## Release Request Auth Posture",
        "",
    ])
    lines.extend(build_release_request_auth_posture_report_lines(request_auth_posture))
    lines.extend([
        "",
        "## Release Request Auth Rotation Audit",
        "",
    ])
    lines.extend(build_release_request_auth_rotation_audit_report_lines(request_auth_rotation_audit))
    lines.extend([
        "",
        "## Release Request Auth Identity Audit",
        "",
    ])
    lines.extend(build_release_request_auth_identity_audit_report_lines(request_auth_identity_audit))
    lines.extend([
        "",
        "## Release Distribution Bundle",
        "",
    ])
    lines.extend(build_release_distribution_bundle_report_lines(release_distribution_bundle))
    lines.extend([
        "",
        "## Release Delivery Readiness",
        "",
    ])
    lines.extend(build_release_delivery_readiness_report_lines(release_delivery_readiness))
    lines.extend([
        "",
        "## Notes",
        "",
    ])
    lines.extend([f"- {item}" for item in list(evidence.get("notes") or [])] or ["- none"])
    lines.append("")
    return "\n".join(lines)


def build_release_review_bundle(plan: Dict[str, Any]) -> Dict[str, Any]:
    normalized = normalize_release_promotion_plan(plan)
    existing = dict(normalized.get("review_bundle") or {})
    if list(existing.get("artifact_links") or []):
        return normalize_release_review_bundle(existing)
    return _build_review_bundle(
        Path(str(normalized.get("project_root") or ".")).resolve(),
        Path(str(normalized.get("runtime_root") or ".")).resolve(),
        str(normalized.get("target_channel") or ""),
        str(normalized.get("target_environment") or ""),
        list(normalized.get("required_signoffs") or []),
        list(normalized.get("provided_signoffs") or []),
        list(normalized.get("missing_signoffs") or []),
        dict(normalized.get("release_candidate_checklist") or {}),
        dict(normalized.get("release_live_runner_baseline") or {}),
        dict(normalized.get("release_live_ci_summary") or {}),
        dict(normalized.get("request_auth_posture") or {}),
        dict(normalized.get("request_auth_rotation_audit") or {}),
        dict(normalized.get("request_auth_identity_audit") or {}),
        dict(normalized.get("release_distribution_bundle") or {}),
    )


def build_release_review_bundle_report(plan: Dict[str, Any]) -> str:
    normalized_plan = normalize_release_promotion_plan(plan)
    bundle = build_release_review_bundle(plan)
    feature = dict(bundle.get("feature") or {})
    artifact_links = list(bundle.get("artifact_links") or [])
    validation_records = list(bundle.get("validation_records") or [])
    risk_summary = dict(bundle.get("risk_summary") or {})
    signoff_records = list(bundle.get("signoff_records") or [])
    followup_actions = list(bundle.get("review_followup_actions") or [])
    audience_summaries = list(bundle.get("audience_summaries") or [])
    qa_evidence = dict(normalized_plan.get("release_candidate_checklist", {}).get("release_summary", {}).get("qa_evidence") or {})
    clean_machine_bootstrap = _extract_clean_machine_bootstrap_artifact(dict(normalized_plan.get("evidence_bundle") or {}))
    full_live_validation = _extract_full_live_validation_artifact(dict(normalized_plan.get("evidence_bundle") or {}))
    release_live_runner_baseline = dict(normalized_plan.get("release_live_runner_baseline") or {})
    release_live_ci_summary = dict(normalized_plan.get("release_live_ci_summary") or {})
    if not release_live_runner_baseline.get("path"):
        release_live_runner_baseline = _extract_release_live_runner_baseline_artifact(dict(normalized_plan.get("evidence_bundle") or {}))
    request_auth_posture = dict(normalized_plan.get("request_auth_posture") or {})
    request_auth_rotation_audit = dict(normalized_plan.get("request_auth_rotation_audit") or {})
    request_auth_identity_audit = dict(normalized_plan.get("request_auth_identity_audit") or {})
    release_distribution_bundle = dict(normalized_plan.get("release_distribution_bundle") or {})
    release_delivery_readiness = dict(normalized_plan.get("release_delivery_readiness") or {})
    target_label = bundle.get("promotion_target_label") or f"{bundle.get('target_channel') or '-'} -> {bundle.get('target_environment') or '-'}"
    lines = [
        "# Release Review Bundle",
        "",
        f"- Target: {target_label}",
        f"- Status: {bundle.get('status') or '-'} / should_block={bool(bundle.get('should_block'))}",
        f"- Build: {bundle.get('build_id') or '-'} / Version: {bundle.get('version') or '-'} / Channel: {bundle.get('release_channel') or '-'}",
        f"- Feature: {feature.get('feature_id') or '-'} / Owner: {feature.get('owner') or '-'} / Status: {feature.get('feature_status') or '-'}",
        f"- Acceptance: ready={bundle.get('acceptance_ready_count') or 0} pending={bundle.get('acceptance_pending_count') or 0} blocked={bundle.get('acceptance_blocked_count') or 0}",
        f"- Scope: {bundle.get('change_scope_count') or 0} changed paths / {bundle.get('artifact_count') or 0} linked artifacts",
        f"- Missing Signoffs: {', '.join(list(bundle.get('missing_signoffs') or [])) or 'none'}",
        "",
        "## Change Summary",
        "",
    ]
    lines.extend([f"- {item}" for item in list(bundle.get("change_summary") or [])] or ["- No structured change summary recorded"])
    lines.extend(["", "## Signoff Records", ""])
    for item in signoff_records:
        lines.append(
            f"- {item.get('actor') or '-'}: status={item.get('status') or 'missing'} "
            f"required={bool(item.get('required'))} source={item.get('source') or '-'}"
        )
    if not signoff_records:
        lines.append("- none")
    lines.extend(["", "## Review Follow-up Actions", ""])
    for item in followup_actions:
        blockers = list(item.get("blockers") or [])
        lines.append(
            f"- {item.get('action_id') or '-'}: status={item.get('status') or 'warning'} "
            f"owner={item.get('owner_hint') or '-'} dependency={item.get('dependency') or '-'} "
            f"eta={item.get('eta') or '-'} validation={item.get('validation_method') or '-'}"
        )
        if blockers:
            lines.append(f"  - blockers={', '.join(blockers)}")
    if not followup_actions:
        lines.append("- none")
    lines.extend(["", "## Change Scope", ""])
    scope_summary = dict(bundle.get("change_scope_summary") or {})
    if scope_summary:
        lines.append(
            "- Summary: "
            f"files={scope_summary.get('file_count') or 0} / "
            f"code={scope_summary.get('code_count') or 0} / "
            f"scenes={scope_summary.get('scene_count') or 0} / "
            f"resources={scope_summary.get('resource_count') or 0} / "
            f"docs={scope_summary.get('docs_count') or 0} / "
            f"other={scope_summary.get('other_count') or 0}"
        )
        for label, key in (
            ("Code", "code_paths"),
            ("Scenes", "scene_paths"),
            ("Resources", "resource_paths"),
            ("Docs", "docs_paths"),
            ("Other", "other_paths"),
        ):
            paths = list(scope_summary.get(key) or [])
            if paths:
                lines.append(f"- {label}: {', '.join(paths)}")
    lines.extend([f"- {item}" for item in list(bundle.get("changed_paths") or [])] or ["- No changed paths recorded"])
    lines.extend(["", "## Acceptance Checklist", ""])
    lines.extend(
        [
            f"- [{item.get('status', 'pending')}] {item.get('label', '')}"
            + (f" / validation={item.get('validation_method')}" if item.get("validation_method") else "")
            + (f" / blockers={', '.join(list(item.get('blockers') or []))}" if item.get("blockers") else "")
            for item in list(bundle.get("acceptance_checklist") or [])
        ]
        or ["- No acceptance checklist recorded"]
    )
    lines.extend(["", "## Validation Records", ""])
    for item in validation_records:
        lines.append(
            f"- {item.get('record_id')}: status={item.get('status') or 'skipped'} source={item.get('source') or '-'}"
            + (f" method={item.get('validation_method')}" if item.get("validation_method") else "")
            + (f" path={item.get('path')}" if item.get("path") else "")
        )
        if item.get("summary"):
            lines.append(f"  - {item.get('summary')}")
    if not validation_records:
        lines.append("- none")
    feature_blockers = list(feature.get("blockers") or [])
    feature_events = list(feature.get("feature_lifecycle_events") or [])
    feature_reviews = list(feature.get("feature_review_history") or [])
    feature_external_links = list(feature.get("external_links") or [])
    lines.extend(["", "## Feature Timeline", ""])
    lines.extend([f"- Blocker: {item}" for item in feature_blockers] or ["- No feature blockers recorded"])
    for item in feature_events[-10:]:
        lines.append(f"- Event `{item.get('event_type') or 'event'}`: {item.get('summary') or '-'} ({item.get('timestamp') or '-'})")
    for item in feature_reviews[-10:]:
        review_meta = " / ".join(
            part
            for part in [
                f"reviewer={item.get('reviewer')}" if item.get("reviewer") else "",
                f"round={item.get('review_round')}" if item.get("review_round") else "",
            ]
            if part
        )
        followups = list(item.get("required_followups") or [])
        lines.append(
            f"- Review `{item.get('feature_status') or 'pending_review'}`: {item.get('review_note') or '-'}"
            + (f" [{review_meta}]" if review_meta else "")
            + (f" / followups={', '.join(followups)}" if followups else "")
            + f" ({item.get('timestamp') or '-'})"
        )
    lines.extend(["", "## External Review Links", ""])
    for item in feature_external_links:
        lines.append(
            f"- {item.get('label') or item.get('link_id')}: type={item.get('type') or 'reference'} status={item.get('status') or 'skipped'} url={item.get('url') or '-'}"
        )
        if item.get("summary"):
            lines.append(f"  - {item.get('summary')}")
    if not feature_external_links:
        lines.append("- none")
    lines.extend(["", "## Risk Summary", ""])
    if risk_summary:
        lines.append(
            f"- Level: {risk_summary.get('risk_level') or '-'} / "
            f"feature_status={risk_summary.get('feature_status') or '-'} / "
            f"should_block={bool(risk_summary.get('should_block'))}"
        )
        lines.append(
            f"- Counts: known_issues={risk_summary.get('known_issue_count') or 0} / "
            f"feature_blockers={risk_summary.get('feature_blocker_count') or 0} / "
            f"blocking={risk_summary.get('blocking_count') or 0} / "
            f"warnings={risk_summary.get('warning_count') or 0}"
        )
        for label, key in (
            ("Blocking", "blocking_items"),
            ("Warnings", "warning_items"),
            ("Feature Blockers", "feature_blockers"),
            ("Known Issues", "known_issues"),
        ):
            values = list(risk_summary.get(key) or [])
            if values:
                lines.append(f"- {label}: {', '.join(values)}")
    else:
        lines.append("- none")
    lines.extend(["", "## QA Evidence", ""])
    lines.extend(_build_release_qa_evidence_report_lines(qa_evidence))
    lines.extend(["", "## Clean Machine Bootstrap", ""])
    lines.extend(_build_clean_machine_bootstrap_report_lines(clean_machine_bootstrap))
    lines.extend(["", "## Full Live Validation", ""])
    lines.extend(_build_full_live_validation_report_lines(full_live_validation))
    lines.extend(["", "## Release Live CI Summary", ""])
    lines.extend(_build_release_live_ci_summary_report_lines(release_live_ci_summary))
    lines.extend(["", "## Release Live Runner Baseline", ""])
    lines.extend(_build_release_live_runner_baseline_report_lines(release_live_runner_baseline))
    lines.extend(["", "## Release Request Auth Posture", ""])
    lines.extend(build_release_request_auth_posture_report_lines(request_auth_posture))
    lines.extend(["", "## Release Request Auth Rotation Audit", ""])
    lines.extend(build_release_request_auth_rotation_audit_report_lines(request_auth_rotation_audit))
    lines.extend(["", "## Release Request Auth Identity Audit", ""])
    lines.extend(build_release_request_auth_identity_audit_report_lines(request_auth_identity_audit))
    lines.extend(["", "## Release Distribution Bundle", ""])
    lines.extend(build_release_distribution_bundle_report_lines(release_distribution_bundle))
    lines.extend(["", "## Release Delivery Readiness", ""])
    lines.extend(build_release_delivery_readiness_report_lines(release_delivery_readiness))
    lines.extend(["", "## Known Issues", ""])
    lines.extend([f"- {item}" for item in list(bundle.get("known_issues") or [])] or ["- None"])
    lines.extend(["", "## Artifact Links", ""])
    for item in artifact_links:
        lines.append(
            f"- {item.get('artifact_id')}: status={item.get('status')} required={item.get('required')} path={item.get('path') or '-'}"
        )
        if item.get("summary"):
            lines.append(f"  - {item.get('summary')}")
    if not artifact_links:
        lines.append("- none")
    lines.extend(["", "## Audience Views", ""])
    for item in audience_summaries:
        lines.append(f"### {item.get('label') or item.get('audience_id') or 'Audience'}")
        lines.append("")
        lines.extend([f"- {line}" for line in list(item.get("summary_lines") or [])] or ["- none"])
        lines.append("")
    if not audience_summaries:
        lines.extend(["- none", ""])
    lines.extend(["## Notes", ""])
    lines.extend([f"- {item}" for item in list(bundle.get("notes") or [])] or ["- none"])
    lines.extend(["", "## Recommendations", ""])
    lines.extend([f"- {item}" for item in list(bundle.get("recommendations") or [])] or ["- none"])
    lines.append("")
    return "\n".join(lines)


def build_deployment_rehearsal_report(plan: Dict[str, Any]) -> str:
    normalized = normalize_release_promotion_plan(plan)
    rehearsal = dict(normalized.get("deployment_rehearsal") or {})
    release_live_runner_baseline = dict(normalized.get("release_live_runner_baseline") or {})
    release_live_ci_summary = dict(normalized.get("release_live_ci_summary") or {})
    request_auth_posture = dict(normalized.get("request_auth_posture") or {})
    request_auth_rotation_audit = dict(normalized.get("request_auth_rotation_audit") or {})
    request_auth_identity_audit = dict(normalized.get("request_auth_identity_audit") or {})
    release_distribution_bundle = dict(normalized.get("release_distribution_bundle") or {})
    release_delivery_readiness = dict(normalized.get("release_delivery_readiness") or {})
    release_summary = dict(normalized.get("release_candidate_checklist", {}).get("release_summary") or {})
    target_label = normalized.get("promotion_target_label") or f"{normalized.get('target_channel') or '-'} -> {normalized.get('target_environment') or '-'}"
    lines = [
        "# Release Promotion Deployment Rehearsal",
        "",
        f"- Target: {target_label}",
        f"- Status: {rehearsal.get('status') or '-'}",
        f"- Output: {release_summary.get('output_path') or release_summary.get('release_dir') or '-'}",
        f"- Release URL: {release_summary.get('release_url') or '-'}",
        f"- Versioned Release URL: {release_summary.get('versioned_release_url') or '-'}",
        "",
        "## Preflight Checks",
        "",
    ]
    for item in list(rehearsal.get("preflight_checks") or []):
        lines.append(
            f"- {item.get('check_id')}: status={item.get('status')} required={item.get('required')} message={item.get('message') or '-'}"
        )
    if not list(rehearsal.get("preflight_checks") or []):
        lines.append("- none")
    lines.extend(["", "## Lane Sequence", ""])
    lines.extend([f"- {item}" for item in list(rehearsal.get("lane_sequence") or [])] or ["- none"])
    lines.extend(["", "## Verification Steps", ""])
    lines.extend([f"- {item}" for item in list(rehearsal.get("verification_steps") or [])] or ["- none"])
    lines.extend(["", "## Release Live Runner Baseline", ""])
    lines.extend(_build_release_live_runner_baseline_report_lines(release_live_runner_baseline))
    lines.extend(["", "## Release Live CI Summary", ""])
    lines.extend(_build_release_live_ci_summary_report_lines(release_live_ci_summary))
    lines.extend(["", "## Release Request Auth Posture", ""])
    lines.extend(build_release_request_auth_posture_report_lines(request_auth_posture))
    lines.extend(["", "## Release Request Auth Rotation Audit", ""])
    lines.extend(build_release_request_auth_rotation_audit_report_lines(request_auth_rotation_audit))
    lines.extend(["", "## Release Request Auth Identity Audit", ""])
    lines.extend(build_release_request_auth_identity_audit_report_lines(request_auth_identity_audit))
    lines.extend(["", "## Release Distribution Bundle", ""])
    lines.extend(build_release_distribution_bundle_report_lines(release_distribution_bundle))
    lines.extend(["", "## Release Delivery Readiness", ""])
    lines.extend(build_release_delivery_readiness_report_lines(release_delivery_readiness))
    lines.extend(["", "## Cutover Steps", ""])
    lines.extend([f"- {item}" for item in list(rehearsal.get("cutover_steps") or [])] or ["- none"])
    lines.extend(["", "## Notes", ""])
    lines.extend([f"- {item}" for item in list(rehearsal.get("notes") or [])] or ["- none"])
    lines.append("")
    return "\n".join(lines)


def build_rollback_rehearsal_report(plan: Dict[str, Any]) -> str:
    normalized = normalize_release_promotion_plan(plan)
    rehearsal = dict(normalized.get("rollback_rehearsal") or {})
    target_label = normalized.get("promotion_target_label") or f"{normalized.get('target_channel') or '-'} -> {normalized.get('target_environment') or '-'}"
    lines = [
        "# Release Promotion Rollback Rehearsal",
        "",
        f"- Target: {target_label}",
        f"- Status: {rehearsal.get('status') or '-'}",
        f"- Restore Target: {rehearsal.get('restore_target') or '-'}",
        f"- Rollback Hint: {rehearsal.get('rollback_hint') or '-'}",
        "",
        "## Assets",
        "",
    ]
    for item in list(rehearsal.get("assets") or []):
        lines.append(
            f"- {item.get('artifact_id')}: status={item.get('status')} required={item.get('required')} path={item.get('path') or '-'}"
        )
        if item.get("summary"):
            lines.append(f"  - {item.get('summary')}")
    if not list(rehearsal.get("assets") or []):
        lines.append("- none")
    lines.extend(["", "## Verification Checks", ""])
    for item in list(rehearsal.get("verification_checks") or []):
        lines.append(
            f"- {item.get('check_id')}: status={item.get('status')} required={item.get('required')} message={item.get('message') or '-'}"
        )
    if not list(rehearsal.get("verification_checks") or []):
        lines.append("- none")
    lines.extend(["", "## Rehearsal Steps", ""])
    lines.extend([f"- {item}" for item in list(rehearsal.get("rehearsal_steps") or [])] or ["- none"])
    lines.extend(["", "## Notes", ""])
    lines.extend([f"- {item}" for item in list(rehearsal.get("notes") or [])] or ["- none"])
    lines.append("")
    return "\n".join(lines)


def _normalize_channel(value: str) -> str:
    normalized = str(value or "").strip().lower()
    return normalized if normalized in _PROMOTION_CHANNELS else DEFAULT_PROMOTION_TARGET_CHANNEL


def _normalize_environment(value: str, target_channel: str) -> str:
    normalized = str(value or "").strip()
    return normalized or _PROMOTION_ENVIRONMENTS.get(target_channel, "staging")


def _normalize_mode(value: str) -> str:
    normalized = str(value or "strict").strip().lower()
    return normalized if normalized in {"strict", "advisory"} else "strict"


def _clean_text_list(value: Optional[List[str]]) -> List[str]:
    result: List[str] = []
    seen = set()
    for item in list(value or []):
        text = str(item or "").strip()
        if not text or text in seen:
            continue
        result.append(text)
        seen.add(text)
    return result


def _normalize_flow_statuses(value: Any) -> Dict[str, str]:
    if not isinstance(value, dict):
        return {}

    normalized: Dict[str, str] = {}
    for raw_key, raw_value in value.items():
        key = str(raw_key).strip()
        if not key or (key != "flow" and not key.endswith("_flow")):
            continue
        status = str(raw_value).strip().lower()
        if status in {"passed", "warning", "blocked", "skipped"}:
            normalized[key] = status
    return normalized


def _extract_full_live_validation_flow_statuses(raw_details: Dict[str, Any]) -> Dict[str, str]:
    direct = _normalize_flow_statuses(raw_details.get("flow_statuses"))
    if direct:
        return direct
    direct = _normalize_flow_statuses(raw_details.get("result"))
    if direct:
        return direct
    structured_content = raw_details.get("structured_content")
    if isinstance(structured_content, dict):
        return _normalize_flow_statuses(structured_content.get("result"))
    return {}


def _normalize_release_qa_status(value: Any, *, target_channel: str = "") -> str:
    normalized = str(value or "").strip().lower() or "skipped"
    if normalized not in {"passed", "warning", "blocked", "skipped"}:
        normalized = "skipped"
    if normalized == "skipped":
        return "blocked" if target_channel == "release" else "warning"
    return normalized


def _build_release_qa_summary(qa_evidence: Dict[str, Any]) -> str:
    return (
        f"smoke={qa_evidence.get('smoke_status') or 'skipped'} / "
        f"assertions={qa_evidence.get('assertion_status') or 'skipped'} / "
        f"visual={qa_evidence.get('screenshot_status') or 'skipped'}"
    )


def _build_release_qa_evidence_report_lines(qa_evidence: Dict[str, Any]) -> List[str]:
    if not qa_evidence:
        return ["- none"]
    lines = [
        f"- Status: {qa_evidence.get('status') or 'skipped'}",
        f"- Scene: {qa_evidence.get('scene_path') or '-'}",
        f"- Summary: {_build_release_qa_summary(qa_evidence)}",
        (
            f"- Metrics: scene_load_ms={qa_evidence.get('metrics', {}).get('scene_load_ms') or '-'} / "
            f"fps={qa_evidence.get('metrics', {}).get('fps') or '-'} / "
            f"memory_peak_mb={qa_evidence.get('metrics', {}).get('memory_peak_mb') or '-'}"
        ),
        f"- Assertion Nodes: {qa_evidence.get('assertion_node_count') or 0}",
        f"- Screenshot: {qa_evidence.get('screenshot_path') or '-'}",
    ]
    if qa_evidence.get("screenshot_diff_ratio") is not None:
        threshold = qa_evidence.get("max_screenshot_diff_ratio")
        lines.append(
            f"- Screenshot Diff: {float(qa_evidence.get('screenshot_diff_ratio')):.4f} / threshold={float(threshold):.4f}" if threshold is not None else f"- Screenshot Diff: {float(qa_evidence.get('screenshot_diff_ratio')):.4f}"
        )
    if list(qa_evidence.get("notes") or []):
        lines.extend([f"- Note: {item}" for item in list(qa_evidence.get("notes") or [])[:3]])
    return lines


def _display_path(path: Path, *roots: Path) -> str:
    resolved = path.resolve()
    for root in roots:
        try:
            return resolved.relative_to(root.resolve()).as_posix()
        except ValueError:
            continue
    return str(resolved)


def _normalize_path_text(value: Any) -> str:
    text = str(value or "").strip().replace("\\", "/")
    if text.startswith("res://"):
        return text[6:]
    return text


def _normalize_binding_path(value: Any, *roots: Path) -> str:
    text = _normalize_path_text(value)
    if not text:
        return ""
    candidate = Path(text)
    if not candidate.is_absolute():
        return text
    absolute = candidate.absolute()
    for root in roots:
        try:
            return absolute.relative_to(root.absolute()).as_posix()
        except ValueError:
            continue
    return absolute.as_posix()


def _slugify_live_validation_lane_id(value: Any) -> str:
    normalized = _normalize_path_text(value).lower()
    characters: List[str] = []
    previous_was_separator = False
    for char in normalized:
        if char.isalnum():
            characters.append(char)
            previous_was_separator = False
            continue
        if char in {"-", "_"}:
            if not previous_was_separator:
                characters.append("_")
                previous_was_separator = True
            continue
        if not previous_was_separator:
            characters.append("_")
            previous_was_separator = True
    slug = "".join(characters).strip("_")
    return slug or "lane"


def _default_full_live_validation_lane_report_path(lane_id: Any) -> str:
    return f"{_FULL_LIVE_VALIDATION_LANE_REPORT_DIR}/{_slugify_live_validation_lane_id(lane_id)}.json"


def _resolve_full_live_validation_lane_report_path(
    *,
    raw_path: Any,
    lane_id: Any,
    runtime_root: Path,
    project_root: Path,
) -> str:
    normalized = _normalize_path_text(raw_path)
    if normalized:
        return normalized

    candidate_relative = _default_full_live_validation_lane_report_path(lane_id)
    for root in (runtime_root, project_root):
        if (root / candidate_relative).exists():
            return candidate_relative
    return ""


def _merge_status(current: str, incoming: str) -> str:
    order = {"passed": 0, "skipped": 0, "warning": 1, "blocked": 2}
    normalized_current = current if current in order else "warning"
    normalized_incoming = incoming if incoming in order else "warning"
    return normalized_current if order[normalized_current] >= order[normalized_incoming] else normalized_incoming


def _load_clean_machine_bootstrap_report(
    project_root: Path,
    runtime_root: Path,
    *,
    target_channel: str,
) -> Dict[str, Any]:
    default_doctor_path = default_doctor_report_path()
    candidates: List[Path] = []
    seen = set()
    for root in (runtime_root, project_root):
        candidate = root / "logs" / "reports" / "clean_machine_bootstrap.json"
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
        steps = list(payload.get("steps") or [])
        blocking_issues = list(payload.get("blocking_issues") or [])
        raw_doctor_report = payload.get("doctor_report") if isinstance(payload.get("doctor_report"), dict) else {}
        doctor_report_path = _normalize_path_text(
            raw_doctor_report.get("path")
            or payload.get("doctor_report_path")
            or default_doctor_path
        )
        doctor_report_exists = False
        doctor_report_payload: Dict[str, Any] = {}
        if doctor_report_path:
            for root in (runtime_root, project_root):
                doctor_candidate = root / doctor_report_path
                if not doctor_candidate.exists():
                    continue
                doctor_report_exists = True
                try:
                    loaded_doctor_payload = json.loads(doctor_candidate.read_text(encoding="utf-8-sig"))
                except (OSError, json.JSONDecodeError):
                    loaded_doctor_payload = {}
                if isinstance(loaded_doctor_payload, dict):
                    doctor_report_payload = loaded_doctor_payload
                break
        doctor_ok_value = doctor_report_payload.get("ok")
        if doctor_ok_value is None:
            doctor_ok_value = raw_doctor_report.get("ok")
        doctor_summary_value = doctor_report_payload.get("summary")
        if not doctor_summary_value:
            doctor_summary_value = raw_doctor_report.get("summary")
        doctor_check_count_value = doctor_report_payload.get("check_count")
        if doctor_check_count_value in (None, ""):
            doctor_check_count_value = raw_doctor_report.get("check_count")
        doctor_failed_check_count_value = doctor_report_payload.get("failed_check_count")
        if doctor_failed_check_count_value in (None, ""):
            doctor_failed_check_count_value = raw_doctor_report.get("failed_check_count")
        doctor_action_item_count_value = doctor_report_payload.get("action_item_count")
        if doctor_action_item_count_value in (None, ""):
            doctor_action_item_count_value = raw_doctor_report.get("action_item_count")
        doctor_blocking_checks_value = doctor_report_payload.get("blocking_checks")
        if not doctor_blocking_checks_value:
            doctor_blocking_checks_value = raw_doctor_report.get("blocking_checks")
        status = "passed" if payload.get("ok") else ("blocked" if target_channel == "release" else "warning")
        return {
            "status": status,
            "path": _display_path(candidate, runtime_root, project_root),
            "summary": (
                f"ok={bool(payload.get('ok'))} / preview={bool(payload.get('preview'))} / "
                f"steps={len(steps)} / blocking_issues={len(blocking_issues)}"
            ),
            "details": {
                "ok": bool(payload.get("ok")),
                "preview": bool(payload.get("preview")),
                "step_count": len(steps),
                "blocking_issue_count": len(blocking_issues),
                "blocking_issue_codes": _clean_text_list([item.get("code") for item in blocking_issues if isinstance(item, dict)]),
                "doctor_report_path": doctor_report_path,
                "doctor_report_exists": doctor_report_exists or bool(raw_doctor_report.get("exists")),
                "doctor_ok": bool(doctor_ok_value),
                "doctor_summary": str(doctor_summary_value or "").strip(),
                "doctor_check_count": max(int(doctor_check_count_value or 0), 0),
                "doctor_failed_check_count": max(int(doctor_failed_check_count_value or 0), 0),
                "doctor_action_item_count": max(int(doctor_action_item_count_value or 0), 0),
                "doctor_blocking_checks": _clean_text_list(doctor_blocking_checks_value),
                "step_statuses": [
                    {
                        "id": str(item.get("id") or ""),
                        "status": str(item.get("status") or ""),
                    }
                    for item in steps[:8]
                    if isinstance(item, dict)
                ],
            },
        }

    return {
        "status": "blocked" if target_channel == "release" else "warning",
        "path": "",
        "summary": "clean_machine_bootstrap.json not found",
        "details": {
            "ok": False,
            "preview": False,
            "step_count": 0,
            "blocking_issue_count": 1,
            "blocking_issue_codes": ["missing_clean_machine_bootstrap"],
            "doctor_report_path": default_doctor_path,
            "doctor_report_exists": False,
            "doctor_ok": False,
            "doctor_summary": "",
            "doctor_check_count": 0,
            "doctor_failed_check_count": 0,
            "doctor_action_item_count": 0,
            "doctor_blocking_checks": [],
            "step_statuses": [],
        },
    }


def _extract_clean_machine_bootstrap_artifact(evidence_bundle: Dict[str, Any]) -> Dict[str, Any]:
    for item in list(evidence_bundle.get("artifacts") or []):
        if str(item.get("artifact_id") or "") == "clean_machine_bootstrap":
            return {
                "status": str(item.get("status") or "warning"),
                "path": str(item.get("path") or ""),
                "summary": str(item.get("summary") or ""),
                "details": dict(item.get("details") or {}),
            }
    return {
        "status": "warning",
        "path": "",
        "summary": "clean_machine_bootstrap artifact missing",
        "details": {
            "ok": False,
            "preview": False,
            "step_count": 0,
            "blocking_issue_count": 1,
            "blocking_issue_codes": ["missing_clean_machine_bootstrap"],
            "doctor_report_path": default_doctor_report_path(),
            "doctor_report_exists": False,
            "doctor_ok": False,
            "doctor_summary": "",
            "doctor_check_count": 0,
            "doctor_failed_check_count": 0,
            "doctor_action_item_count": 0,
            "doctor_blocking_checks": [],
            "step_statuses": [],
        },
    }


def _build_clean_machine_bootstrap_report_lines(bootstrap: Dict[str, Any]) -> List[str]:
    details = dict(bootstrap.get("details") or {})
    lines = [
        f"- Status: {bootstrap.get('status') or 'warning'}",
        f"- Report Path: {bootstrap.get('path') or '-'}",
        f"- Summary: {bootstrap.get('summary') or '-'}",
        f"- ok={bool(details.get('ok'))} / preview={bool(details.get('preview'))}",
        f"- Steps: {details.get('step_count') or 0}",
        f"- Blocking Issues: {details.get('blocking_issue_count') or 0}",
    ]
    issue_codes = list(details.get("blocking_issue_codes") or [])
    if issue_codes:
        lines.append(f"- Blocking Issue Codes: {', '.join(issue_codes)}")
    if details.get("doctor_report_path") or details.get("doctor_report_exists"):
        lines.append(
            f"- Doctor Report: path={details.get('doctor_report_path') or '-'} / "
            f"exported={'yes' if details.get('doctor_report_exists') else 'no'} / "
            f"ok={bool(details.get('doctor_ok'))} / "
            f"failed_checks={details.get('doctor_failed_check_count') or 0} / "
            f"action_items={details.get('doctor_action_item_count') or 0}"
        )
    if details.get("doctor_summary"):
        lines.append(f"- Doctor Summary: {details.get('doctor_summary')}")
    doctor_blocking_checks = list(details.get("doctor_blocking_checks") or [])
    if doctor_blocking_checks:
        lines.append(f"- Doctor Blocking Checks: {', '.join(doctor_blocking_checks)}")
    step_statuses = list(details.get("step_statuses") or [])
    if step_statuses:
        lines.append(
            "- Step Statuses: " + ", ".join(
                f"{item.get('id') or 'step'}={item.get('status') or 'unknown'}"
                for item in step_statuses
            )
        )
    return lines


def _load_release_live_runner_baseline_report(
    project_root: Path,
    runtime_root: Path,
    *,
    target_channel: str,
) -> Dict[str, Any]:
    relative_report_path = default_release_live_runner_baseline_report_path(target_channel=target_channel)
    candidates: List[Path] = []
    seen = set()
    for root in (runtime_root, project_root):
        candidate = root / relative_report_path
        key = str(candidate.resolve())
        if key in seen:
            continue
        seen.add(key)
        candidates.append(candidate)

    default_status = "blocked" if target_channel == "release" else "warning"
    for candidate in candidates:
        if not candidate.exists():
            continue
        try:
            payload = json.loads(candidate.read_text(encoding="utf-8-sig"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(payload, dict):
            continue

        checks: List[Dict[str, Any]] = []
        for item in list(payload.get("checks") or []):
            if not isinstance(item, dict):
                continue
            checks.append({
                "check_id": str(item.get("check_id") or "").strip(),
                "label": str(item.get("label") or item.get("check_id") or "").strip(),
                "status": str(item.get("status") or "").strip().lower() or "skipped",
                "required": bool(item.get("required", True)),
                "message": str(item.get("message") or "").strip(),
            })

        return {
            "status": str(payload.get("status") or default_status).strip().lower() or default_status,
            "path": _display_path(candidate, runtime_root, project_root),
            "summary": str(payload.get("summary") or "").strip() or "release live runner baseline loaded",
            "details": {
                "target_channel": str(payload.get("target_channel") or target_channel).strip(),
                "target_environment": str(payload.get("target_environment") or "").strip(),
                "report_path": str(payload.get("report_path") or relative_report_path).strip(),
                "runner_profile_path": str(payload.get("runner_profile_path") or "").strip(),
                "runner_profile_id": str(payload.get("runner_profile_id") or "").strip(),
                "runner_name": str(payload.get("runner_name") or "").strip(),
                "runner_os": str(payload.get("runner_os") or "").strip(),
                "runner_arch": str(payload.get("runner_arch") or "").strip(),
                "declared_runner_labels": _clean_text_list(payload.get("declared_runner_labels")),
                "github_actions": bool(payload.get("github_actions")),
                "github_workflow": str(payload.get("github_workflow") or "").strip(),
                "github_job": str(payload.get("github_job") or "").strip(),
                "github_run_id": str(payload.get("github_run_id") or "").strip(),
                "github_run_attempt": str(payload.get("github_run_attempt") or "").strip(),
                "python_version": str(payload.get("python_version") or "").strip(),
                "required_runner_os": str(payload.get("runner_profile", {}).get("required_runner_os") or "").strip(),
                "required_runner_arches": _clean_text_list(payload.get("runner_profile", {}).get("required_runner_arches")),
                "required_runner_labels": _clean_text_list(payload.get("runner_profile", {}).get("required_runner_labels")),
                "allowed_runner_names": _clean_text_list(payload.get("runner_profile", {}).get("allowed_runner_names")),
                "check_count": max(int(payload.get("check_count") or len(checks)), 0),
                "passed_check_count": max(int(payload.get("passed_check_count") or 0), 0),
                "warning_check_count": max(int(payload.get("warning_check_count") or 0), 0),
                "blocked_check_count": max(int(payload.get("blocked_check_count") or 0), 0),
                "blocking_checks": _clean_text_list(payload.get("blocking_checks")),
                "warning_checks": _clean_text_list(payload.get("warning_checks")),
                "checks": checks,
                "recommendations": _clean_text_list(payload.get("recommendations")),
                "powershell_executable": str(payload.get("detected_tools", {}).get("powershell_executable") or "").strip(),
                "godot_executable": str(payload.get("detected_tools", {}).get("godot_executable") or "").strip(),
                "browser_executable": str(payload.get("detected_tools", {}).get("browser_executable") or "").strip(),
            },
        }

    return {
        "status": default_status,
        "path": "",
        "summary": "release live runner baseline report missing",
        "details": {
            "target_channel": target_channel,
            "target_environment": "",
            "report_path": relative_report_path,
            "runner_profile_path": default_release_live_runner_profile_path(),
            "runner_profile_id": "",
            "runner_name": "",
            "runner_os": "",
            "runner_arch": "",
            "declared_runner_labels": [],
            "github_actions": False,
            "github_workflow": "",
            "github_job": "",
            "github_run_id": "",
            "github_run_attempt": "",
            "python_version": "",
            "required_runner_os": "",
            "required_runner_arches": [],
            "required_runner_labels": [],
            "allowed_runner_names": [],
            "check_count": 0,
            "passed_check_count": 0,
            "warning_check_count": 0,
            "blocked_check_count": 1 if target_channel == "release" else 0,
            "blocking_checks": ["missing_release_live_runner_baseline"] if target_channel == "release" else [],
            "warning_checks": ["missing_release_live_runner_baseline"] if target_channel != "release" else [],
            "checks": [],
            "recommendations": [
                "先生成 release_live_runner_baseline_<channel>.json，确认 self-hosted Windows runner 已具备 PowerShell / Godot / Chromium / live scripts / release manifest。"
            ],
            "powershell_executable": "",
            "godot_executable": "",
            "browser_executable": "",
        },
    }


def _extract_release_live_runner_baseline_artifact(evidence_bundle: Dict[str, Any]) -> Dict[str, Any]:
    for item in list(evidence_bundle.get("artifacts") or []):
        if str(item.get("artifact_id") or "") == "release_live_runner_baseline":
            return {
                "status": str(item.get("status") or "warning"),
                "path": str(item.get("path") or ""),
                "summary": str(item.get("summary") or ""),
                "details": dict(item.get("details") or {}),
            }
    return {
        "status": "warning",
        "path": "",
        "summary": "release live runner baseline artifact missing",
        "details": {
            "target_channel": "",
            "target_environment": "",
            "report_path": default_release_live_runner_baseline_report_path(target_channel="release"),
            "runner_profile_path": default_release_live_runner_profile_path(),
            "runner_profile_id": "",
            "runner_name": "",
            "runner_os": "",
            "runner_arch": "",
            "declared_runner_labels": [],
            "github_actions": False,
            "github_workflow": "",
            "github_job": "",
            "github_run_id": "",
            "github_run_attempt": "",
            "python_version": "",
            "required_runner_os": "",
            "required_runner_arches": [],
            "required_runner_labels": [],
            "allowed_runner_names": [],
            "check_count": 0,
            "passed_check_count": 0,
            "warning_check_count": 0,
            "blocked_check_count": 1,
            "blocking_checks": ["missing_release_live_runner_baseline"],
            "warning_checks": [],
            "checks": [],
            "recommendations": [
                "补齐 release_live_runner_baseline_<channel>.json，再把 runner 环境当成 release 证据的一部分。"
            ],
            "powershell_executable": "",
            "godot_executable": "",
            "browser_executable": "",
        },
    }


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
        full_live_validation_lanes: List[Dict[str, Any]] = []
        for item in list(runtime_lanes.get("full_live_validation") or []):
            if not isinstance(item, dict):
                continue
            full_live_validation_lanes.append({
                "lane_id": str(item.get("lane_id") or "").strip(),
                "label": str(item.get("label") or item.get("lane_id") or "").strip(),
                "status": str(item.get("status") or "").strip().lower(),
                "summary": str(item.get("summary") or "").strip(),
                "report_path": _normalize_path_text(item.get("report_path")),
                "artifact_paths": _clean_text_list([_normalize_path_text(path) for path in list(item.get("artifact_paths") or [])]),
                "flow_statuses": _normalize_flow_statuses(item.get("flow_statuses")),
            })

        report_files = dict(payload.get("report_files") or {})
        summary_markdown_name = str(report_files.get("summary_markdown") or "release_live_ci_summary.md").strip() or "release_live_ci_summary.md"
        summary_markdown_path = candidate.parent / summary_markdown_name
        workflow_step_results_name = str(report_files.get("workflow_step_results") or "").strip()
        workflow_step_results_path = candidate.parent / workflow_step_results_name if workflow_step_results_name else None
        status = str(ci_gate.get("status") or payload.get("status") or "warning").strip().lower()
        if status not in {"passed", "warning", "blocked", "skipped"}:
            status = "warning"
        return {
            "status": status,
            "path": _display_path(candidate, runtime_root, project_root),
            "summary": (
                f"ci_gate={status} / lanes={len(full_live_validation_lanes)} / "
                f"signoffs={str(human_signoffs.get('status') or 'skipped').strip().lower() or 'skipped'}"
            ),
            "details": {
                "artifact_dir": _display_path(candidate.parent, runtime_root, project_root),
                "generated_at": str(payload.get("generated_at") or "").strip(),
                "target_channel": str(payload.get("target_channel") or target_channel).strip(),
                "target_environment": str(payload.get("target_environment") or "").strip(),
                "release_build_id": str(payload.get("release_build_id") or "").strip(),
                "release_version": str(payload.get("release_version") or "").strip(),
                "release_channel": str(payload.get("release_channel") or "").strip(),
                "release_manifest_path": _normalize_path_text(payload.get("release_manifest_path")),
                "summary_markdown_path": _display_path(summary_markdown_path, runtime_root, project_root),
                "summary_markdown_exists": summary_markdown_path.exists(),
                "workflow_step_results_path": _display_path(workflow_step_results_path, runtime_root, project_root) if workflow_step_results_path else "",
                "runtime_assembly": runtime_assembly,
                "event_stream": event_stream,
                "dispatch_audit": dispatch_audit,
                "invocation": {
                    "source": str(invocation.get("source") or "").strip(),
                    "mode": str(invocation.get("mode") or "").strip(),
                    "fail_on_warnings": bool(invocation.get("fail_on_warnings")),
                    "providers": _clean_text_list(list(invocation.get("providers") or [])),
                    "approvers": _clean_text_list(list(invocation.get("approvers") or [])),
                    "executed_by": str(invocation.get("executed_by") or "").strip(),
                    "note": str(invocation.get("note") or "").strip(),
                },
                "ci_gate": {
                    "status": status,
                    "should_block": bool(ci_gate.get("should_block")),
                    "fail_on_warnings": bool(ci_gate.get("fail_on_warnings")),
                    "blocking_checks": _clean_text_list(list(ci_gate.get("blocking_checks") or [])),
                    "warning_checks": _clean_text_list(list(ci_gate.get("warning_checks") or [])),
                    "evaluated_check_count": max(int(ci_gate.get("evaluated_check_count") or 0), 0),
                },
                "runtime_gates": {
                    "release_live_runner_baseline_status": str(runtime_gates.get("release_live_runner_baseline_status") or "").strip(),
                    "full_live_validation_status": str(runtime_gates.get("full_live_validation_status") or "").strip(),
                    "distribution_bundle_status": str(runtime_gates.get("distribution_bundle_status") or "").strip(),
                    "distribution_signing_handoff_status": str(runtime_gates.get("distribution_signing_handoff_status") or "").strip(),
                    "distribution_publish_handoff_status": str(runtime_gates.get("distribution_publish_handoff_status") or "").strip(),
                    "distribution_publish_receipts_status": str(runtime_gates.get("distribution_publish_receipts_status") or "").strip(),
                    "identity_handoff_status": str(runtime_gates.get("identity_handoff_status") or "").strip(),
                },
                "runtime_lanes": {
                    "full_live_validation": full_live_validation_lanes,
                },
                "workflow_steps": workflow_steps,
                "human_signoffs": {
                    "status": str(human_signoffs.get("status") or "").strip().lower() or "skipped",
                    "required_signoffs": _clean_text_list(list(human_signoffs.get("required_signoffs") or [])),
                    "provided_signoffs": _clean_text_list(list(human_signoffs.get("provided_signoffs") or [])),
                    "missing_signoffs": _clean_text_list(list(human_signoffs.get("missing_signoffs") or [])),
                },
            },
        }

    return {
        "status": "warning",
        "path": "",
        "summary": "release_live_ci_summary.json not found",
        "details": {
            "artifact_dir": "logs/reports/release_live_ci",
            "generated_at": "",
            "target_channel": target_channel,
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
            "invocation": {
                "source": "",
                "mode": "",
                "fail_on_warnings": False,
                "providers": [],
                "approvers": [],
                "executed_by": "",
                "note": "",
            },
            "ci_gate": {
                "status": "warning",
                "should_block": False,
                "fail_on_warnings": False,
                "blocking_checks": [],
                "warning_checks": ["missing_release_live_ci_summary"],
                "evaluated_check_count": 0,
            },
            "runtime_gates": {
                "release_live_runner_baseline_status": "",
                "full_live_validation_status": "",
                "distribution_bundle_status": "",
                "distribution_signing_handoff_status": "",
                "distribution_publish_handoff_status": "",
                "distribution_publish_receipts_status": "",
                "identity_handoff_status": "",
            },
            "runtime_lanes": {
                "full_live_validation": [],
            },
            "workflow_steps": [],
            "human_signoffs": {
                "status": "skipped",
                "required_signoffs": [],
                "provided_signoffs": [],
                "missing_signoffs": [],
            },
        },
    }


def _build_release_live_runner_baseline_report_lines(summary: Dict[str, Any]) -> List[str]:
    details = dict(summary.get("details") or {})
    lines = [
        f"- Status: {summary.get('status') or 'warning'}",
        f"- Report Path: {summary.get('path') or '-'}",
        f"- Summary: {summary.get('summary') or '-'}",
        f"- Target: {details.get('target_channel') or '-'} -> {details.get('target_environment') or '-'}",
        f"- Runner Profile: {details.get('runner_profile_id') or '-'} / path={details.get('runner_profile_path') or '-'}",
        (
            f"- Runner Host: name={details.get('runner_name') or '-'} / "
            f"os={details.get('runner_os') or '-'} / arch={details.get('runner_arch') or '-'} / "
            f"python={details.get('python_version') or '-'}"
        ),
        (
            f"- Workflow Context: github_actions={bool(details.get('github_actions'))} / "
            f"workflow={details.get('github_workflow') or '-'} / "
            f"job={details.get('github_job') or '-'} / "
            f"run_id={details.get('github_run_id') or '-'} / "
            f"attempt={details.get('github_run_attempt') or '-'}"
        ),
        f"- Runner Labels: {', '.join(list(details.get('declared_runner_labels') or [])) or '-'}",
        (
            f"- Checks: {details.get('check_count') or 0} / passed={details.get('passed_check_count') or 0} / "
            f"warning={details.get('warning_check_count') or 0} / blocked={details.get('blocked_check_count') or 0}"
        ),
        (
            f"- Toolchain: powershell={details.get('powershell_executable') or '-'} / "
            f"godot={details.get('godot_executable') or '-'} / "
            f"browser={details.get('browser_executable') or '-'}"
        ),
    ]
    blocking_checks = list(details.get("blocking_checks") or [])
    if blocking_checks:
        lines.append(f"- Blocking Checks: {', '.join(blocking_checks)}")
    warning_checks = list(details.get("warning_checks") or [])
    if warning_checks:
        lines.append(f"- Warning Checks: {', '.join(warning_checks)}")
    if details.get("required_runner_os") or list(details.get("required_runner_arches") or []) or list(details.get("allowed_runner_names") or []):
        lines.append(
            f"- Profile Constraints: os={details.get('required_runner_os') or '-'} / "
            f"arches={','.join(list(details.get('required_runner_arches') or [])) or '-'} / "
            f"labels={','.join(list(details.get('required_runner_labels') or [])) or '-'} / "
            f"runner_names={','.join(list(details.get('allowed_runner_names') or [])) or '-'}"
        )
    checks = list(details.get("checks") or [])
    if checks:
        lines.append(
            "- Check Statuses: " + ", ".join(
                f"{item.get('check_id') or 'check'}={item.get('status') or 'unknown'}"
                for item in checks[:8]
            )
        )
    recommendations = list(details.get("recommendations") or [])
    if recommendations:
        lines.append(f"- Recommendation: {recommendations[0]}")
    return lines


def _build_release_live_ci_summary_report_lines(summary: Dict[str, Any]) -> List[str]:
    details = dict(summary.get("details") or {})
    ci_gate = dict(details.get("ci_gate") or {})
    runtime_gates = dict(details.get("runtime_gates") or {})
    invocation = dict(details.get("invocation") or {})
    runtime_assembly = dict(details.get("runtime_assembly") or {})
    event_stream = dict(details.get("event_stream") or {})
    dispatch_audit = dict(details.get("dispatch_audit") or {})
    human_signoffs = dict(details.get("human_signoffs") or {})
    full_live_validation_lanes = list(details.get("runtime_lanes", {}).get("full_live_validation") or [])
    workflow_steps = [dict(item) for item in list(details.get("workflow_steps") or []) if isinstance(item, dict)]

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
            f"providers={','.join(list(invocation.get('providers') or [])) or '-'} / "
            f"approvers={','.join(list(invocation.get('approvers') or [])) or '-'}"
        ),
    ]
    lines.extend(build_release_runtime_assembly_report_lines(runtime_assembly))
    lines.extend(build_release_live_event_stream_report_lines(event_stream))
    lines.extend(build_release_live_dispatch_audit_report_lines(dispatch_audit))
    lines.extend([
        (
            f"- CI Gate: status={ci_gate.get('status') or '-'} / "
            f"should_block={bool(ci_gate.get('should_block'))} / "
            f"blocking={', '.join(list(ci_gate.get('blocking_checks') or [])) or 'none'} / "
            f"warning={', '.join(list(ci_gate.get('warning_checks') or [])) or 'none'}"
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
            f"provided={', '.join(list(human_signoffs.get('provided_signoffs') or [])) or 'none'} / "
            f"missing={', '.join(list(human_signoffs.get('missing_signoffs') or [])) or 'none'}"
        ),
    ])
    for lane in full_live_validation_lanes[:6]:
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


def _load_full_live_validation_report(
    project_root: Path,
    runtime_root: Path,
    *,
    target_channel: str,
) -> Dict[str, Any]:
    candidates: List[Path] = []
    seen = set()
    for root in (runtime_root, project_root):
        candidate = root / "logs" / "reports" / "full_live_validation.json"
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

        step_statuses: List[Dict[str, Any]] = []
        for item in list(payload.get("steps") or []):
            if not isinstance(item, dict):
                continue
            raw_status = str(item.get("status") or "").strip().lower()
            raw_details = dict(item.get("details") or {})
            lane_id = str(item.get("id") or "").strip() or f"lane_{len(step_statuses) + 1}"
            lane_report_path = _resolve_full_live_validation_lane_report_path(
                raw_path=raw_details.get("report_path") or item.get("report_path"),
                lane_id=lane_id,
                runtime_root=runtime_root,
                project_root=project_root,
            )
            flow_statuses = _extract_full_live_validation_flow_statuses(raw_details)
            step_statuses.append({
                "id": lane_id,
                "label": str(item.get("label") or item.get("id") or "").strip() or f"Lane {len(step_statuses) + 1}",
                "status": raw_status if raw_status in {"passed", "warning", "blocked", "skipped"} else "skipped",
                "summary": str(item.get("summary") or "").strip(),
                "artifact_paths": _clean_text_list([
                    _normalize_path_text(path)
                    for path in list(item.get("artifact_paths") or raw_details.get("artifact_paths") or [])
                ]),
                "report_path": lane_report_path,
                "flow_statuses": flow_statuses,
            })

        blocking_issues = [item for item in list(payload.get("blocking_issues") or []) if isinstance(item, dict)]
        passed_lane_count = sum(1 for item in step_statuses if item["status"] == "passed")
        warning_lane_count = sum(1 for item in step_statuses if item["status"] == "warning")
        blocked_lane_count = sum(1 for item in step_statuses if item["status"] == "blocked")
        status = "blocked" if blocked_lane_count or blocking_issues else ("warning" if warning_lane_count else "passed")
        if not bool(payload.get("ok", status == "passed")) and status == "passed":
            status = "warning"
        release_binding = dict(payload.get("release_binding") or {})
        report_release_build_id = str(release_binding.get("build_id") or "").strip()
        report_release_version = str(release_binding.get("version") or "").strip()
        report_release_channel = str(release_binding.get("channel") or "").strip()
        report_release_binding_status = str(release_binding.get("status") or "").strip().lower()
        if report_release_binding_status not in {"passed", "warning", "blocked", "skipped"}:
            report_release_binding_status = "passed" if (report_release_build_id and report_release_version and report_release_channel) else "warning"
        report_release_manifest_path = _normalize_path_text(release_binding.get("manifest_path"))
        report_release_dir = _normalize_path_text(release_binding.get("release_dir"))
        report_output_path = _normalize_path_text(release_binding.get("output_path"))
        report_release_url = str(release_binding.get("release_url") or "").strip()
        report_versioned_release_url = str(release_binding.get("versioned_release_url") or "").strip()
        lane_artifacts = [
            {
                "lane_id": str(item.get("id") or "").strip(),
                "label": str(item.get("label") or item.get("id") or "").strip(),
                "status": str(item.get("status") or "skipped"),
                "summary": str(item.get("summary") or "").strip(),
                "executed_at": str(payload.get("executed_at") or "").strip(),
                "report_path": str(item.get("report_path") or "").strip(),
                "report_exists": bool(item.get("report_path")),
                "artifact_paths": list(item.get("artifact_paths") or []),
                "build_id": report_release_build_id,
                "version": report_release_version,
                "channel": report_release_channel,
                "release_manifest_path": report_release_manifest_path,
                "release_dir": report_release_dir,
                "output_path": report_output_path,
                "release_url": report_release_url,
                "versioned_release_url": report_versioned_release_url,
                "release_binding_status": report_release_binding_status,
                "release_binding_mismatches": [],
                "flow_statuses": dict(item.get("flow_statuses") or {}),
            }
            for item in step_statuses
        ]

        blocking_issue_codes = _clean_text_list(
            [item.get("code") for item in blocking_issues if isinstance(item, dict)]
        ) or [item["id"] for item in step_statuses if item["status"] == "blocked"]

        return {
            "status": status,
            "path": _display_path(candidate, runtime_root, project_root),
            "summary": (
                f"ok={bool(payload.get('ok'))} / lanes={len(step_statuses)} / "
                f"passed={passed_lane_count} / warning={warning_lane_count} / blocked={blocked_lane_count}"
            ),
            "details": {
                "ok": bool(payload.get("ok")),
                "executed_at": str(payload.get("executed_at") or "").strip(),
                "lane_count": len(step_statuses),
                "passed_lane_count": passed_lane_count,
                "warning_lane_count": warning_lane_count,
                "blocked_lane_count": blocked_lane_count,
                "blocking_issue_count": len(blocking_issues),
                "blocking_issue_codes": blocking_issue_codes,
                "report_release_binding_status": report_release_binding_status,
                "report_release_manifest_source": str(release_binding.get("manifest_source") or "").strip(),
                "report_release_build_id": report_release_build_id,
                "report_release_version": report_release_version,
                "report_release_channel": report_release_channel,
                "report_release_manifest_path": report_release_manifest_path,
                "report_release_dir": report_release_dir,
                "report_output_path": report_output_path,
                "report_release_url": report_release_url,
                "report_versioned_release_url": report_versioned_release_url,
                "lane_artifact_count": len(lane_artifacts),
                "lane_artifacts": lane_artifacts[:8],
                "step_statuses": step_statuses[:8],
            },
        }

    return {
        "status": "blocked" if target_channel == "release" else "warning",
        "path": "",
        "summary": "full_live_validation.json not found",
        "details": {
            "ok": False,
            "executed_at": "",
            "lane_count": 0,
            "passed_lane_count": 0,
            "warning_lane_count": 0,
            "blocked_lane_count": 0,
            "blocking_issue_count": 1,
            "blocking_issue_codes": ["missing_full_live_validation"],
            "report_release_binding_status": "blocked" if target_channel == "release" else "warning",
            "report_release_manifest_source": "",
            "report_release_build_id": "",
            "report_release_version": "",
            "report_release_channel": "",
            "report_release_manifest_path": "",
            "report_release_dir": "",
            "report_output_path": "",
            "report_release_url": "",
            "report_versioned_release_url": "",
            "lane_artifact_count": 0,
            "lane_artifacts": [],
            "step_statuses": [],
        },
    }


def _bind_full_live_validation_to_release(
    summary: Dict[str, Any],
    release_summary: Dict[str, Any],
    *,
    target_channel: str,
    project_root: Path | None = None,
    runtime_root: Path | None = None,
) -> Dict[str, Any]:
    bound = {
        "status": str(summary.get("status") or "warning"),
        "path": str(summary.get("path") or ""),
        "summary": str(summary.get("summary") or ""),
        "details": dict(summary.get("details") or {}),
    }
    details = bound["details"]
    expected_build_id = str(release_summary.get("build_id") or "").strip()
    expected_version = str(release_summary.get("version") or "").strip()
    expected_channel = str(release_summary.get("channel") or "").strip()
    roots = tuple(root for root in (project_root, runtime_root) if root)
    expected_manifest_path = _normalize_binding_path(release_summary.get("release_manifest_path"), *roots)

    report_release_build_id = str(details.get("report_release_build_id") or "").strip()
    report_release_version = str(details.get("report_release_version") or "").strip()
    report_release_channel = str(details.get("report_release_channel") or "").strip()
    report_release_manifest_path = _normalize_binding_path(details.get("report_release_manifest_path"), *roots)
    report_binding_status = str(details.get("report_release_binding_status") or "").strip().lower()
    if report_binding_status not in {"passed", "warning", "blocked", "skipped"}:
        report_binding_status = "passed" if (report_release_build_id and report_release_version and report_release_channel) else "warning"

    mismatch_codes: List[str] = []
    expected_fields_present = any((expected_build_id, expected_version, expected_channel, expected_manifest_path))
    report_fields_present = any((report_release_build_id, report_release_version, report_release_channel, report_release_manifest_path))
    if expected_fields_present and not report_fields_present:
        mismatch_codes.append("missing_release_binding")
    if expected_build_id and report_release_build_id and expected_build_id != report_release_build_id:
        mismatch_codes.append("release_build_id_mismatch")
    if expected_version and report_release_version and expected_version != report_release_version:
        mismatch_codes.append("release_version_mismatch")
    if expected_channel and report_release_channel and expected_channel != report_release_channel:
        mismatch_codes.append("release_channel_mismatch")
    if expected_manifest_path and report_release_manifest_path and expected_manifest_path != report_release_manifest_path:
        mismatch_codes.append("release_manifest_path_mismatch")

    release_binding_status = report_binding_status
    if mismatch_codes:
        release_binding_status = "blocked" if target_channel == "release" else "warning"
    elif not report_fields_present and expected_fields_present:
        release_binding_status = "blocked" if target_channel == "release" else "warning"

    details.update({
        "release_build_id": expected_build_id,
        "release_version": expected_version,
        "release_channel": expected_channel,
        "release_manifest_path": expected_manifest_path,
        "release_binding_status": release_binding_status,
        "release_binding_mismatches": mismatch_codes,
        "report_release_binding_status": report_binding_status,
    })
    lane_artifacts = []
    for item in list(details.get("lane_artifacts") or []):
        if not isinstance(item, dict):
            continue
        lane_artifact = dict(item)
        lane_artifact["release_binding_status"] = release_binding_status
        lane_artifact["release_binding_mismatches"] = mismatch_codes
        lane_artifact["expected_build_id"] = expected_build_id
        lane_artifact["expected_version"] = expected_version
        lane_artifact["expected_channel"] = expected_channel
        lane_artifact["expected_release_manifest_path"] = expected_manifest_path
        lane_artifacts.append(lane_artifact)
    details["lane_artifact_count"] = len(lane_artifacts)
    details["lane_artifacts"] = lane_artifacts
    if release_binding_status:
        bound["status"] = _merge_status(bound["status"], release_binding_status)
        bound["summary"] = (
            f"{bound['summary']} / binding={release_binding_status}"
            if bound["summary"]
            else f"binding={release_binding_status}"
        )
    return bound


def _expected_release_binding_summary(
    release_candidate: Dict[str, Any],
    release_summary: Dict[str, Any],
) -> Dict[str, Any]:
    return {
        "build_id": str(release_summary.get("build_id") or "").strip(),
        "version": str(release_summary.get("version") or "").strip(),
        "channel": str(release_summary.get("channel") or "").strip(),
        "release_manifest_path": str(
            release_candidate.get("release_manifest_path") or release_summary.get("release_manifest_path") or ""
        ).strip(),
    }


def _extract_full_live_validation_artifact(evidence_bundle: Dict[str, Any]) -> Dict[str, Any]:
    for item in list(evidence_bundle.get("artifacts") or []):
        if str(item.get("artifact_id") or "") == "full_live_validation":
            return {
                "status": str(item.get("status") or "warning"),
                "path": str(item.get("path") or ""),
                "summary": str(item.get("summary") or ""),
                "details": dict(item.get("details") or {}),
            }
    return {
        "status": "warning",
        "path": "",
        "summary": "full_live_validation artifact missing",
        "details": {
            "ok": False,
            "executed_at": "",
            "lane_count": 0,
            "passed_lane_count": 0,
            "warning_lane_count": 0,
            "blocked_lane_count": 0,
            "blocking_issue_count": 1,
            "blocking_issue_codes": ["missing_full_live_validation"],
            "report_release_binding_status": "warning",
            "report_release_manifest_source": "",
            "report_release_build_id": "",
            "report_release_version": "",
            "report_release_channel": "",
            "report_release_manifest_path": "",
            "report_release_dir": "",
            "report_output_path": "",
            "report_release_url": "",
            "report_versioned_release_url": "",
            "release_build_id": "",
            "release_version": "",
            "release_channel": "",
            "release_manifest_path": "",
            "release_binding_status": "warning",
            "release_binding_mismatches": ["missing_full_live_validation"],
            "lane_artifact_count": 0,
            "lane_artifacts": [],
            "step_statuses": [],
        },
    }


def _build_full_live_validation_report_lines(summary: Dict[str, Any]) -> List[str]:
    details = dict(summary.get("details") or {})
    lines = [
        f"- Status: {summary.get('status') or 'warning'}",
        f"- Report Path: {summary.get('path') or '-'}",
        f"- Summary: {summary.get('summary') or '-'}",
        f"- ok={bool(details.get('ok'))} / executed_at={details.get('executed_at') or '-'}",
        f"- Lanes: {details.get('lane_count') or 0}",
        f"- Passed/Warning/Blocked: {details.get('passed_lane_count') or 0}/{details.get('warning_lane_count') or 0}/{details.get('blocked_lane_count') or 0}",
        f"- Blocking Issues: {details.get('blocking_issue_count') or 0}",
    ]
    if details.get("release_build_id") or details.get("release_channel"):
        lines.append(
            f"- Expected Release: build={details.get('release_build_id') or '-'} / "
            f"version={details.get('release_version') or '-'} / channel={details.get('release_channel') or '-'}"
        )
    if details.get("report_release_build_id") or details.get("report_release_channel") or details.get("report_release_manifest_path"):
        lines.append(
            f"- Report Binding: build={details.get('report_release_build_id') or '-'} / "
            f"version={details.get('report_release_version') or '-'} / "
            f"channel={details.get('report_release_channel') or '-'} / "
            f"manifest={details.get('report_release_manifest_path') or '-'}"
        )
    if details.get("release_binding_status"):
        lines.append(f"- Binding Status: {details.get('release_binding_status') or 'warning'}")
    issue_codes = list(details.get("blocking_issue_codes") or [])
    if issue_codes:
        lines.append(f"- Blocking Issue Codes: {', '.join(issue_codes)}")
    binding_mismatches = list(details.get("release_binding_mismatches") or [])
    if binding_mismatches:
        lines.append(f"- Binding Mismatches: {', '.join(binding_mismatches)}")
    step_statuses = list(details.get("step_statuses") or [])
    if step_statuses:
        lines.append(
            "- Lane Statuses: " + ", ".join(
                f"{item.get('id') or 'lane'}={item.get('status') or 'unknown'}"
                for item in step_statuses
            )
        )
        for item in step_statuses[:4]:
            artifact_paths = list(item.get("artifact_paths") or [])
            if artifact_paths:
                lines.append(
                    f"- Lane Artifacts ({item.get('id') or 'lane'}): {', '.join(artifact_paths[:4])}"
                )
            flow_statuses = dict(item.get("flow_statuses") or {})
            if flow_statuses:
                lines.append(
                    "- Lane Flows "
                    f"({item.get('id') or 'lane'}): "
                    + ", ".join(f"{key}={value}" for key, value in sorted(flow_statuses.items()))
                )
    lane_artifacts = list(details.get("lane_artifacts") or [])
    if lane_artifacts:
        lines.append(
            "- Lane Reports: " + ", ".join(
                f"{item.get('lane_id') or 'lane'}={item.get('report_path') or '-'}"
                for item in lane_artifacts
            )
        )
        for item in lane_artifacts[:4]:
            lines.append(
                f"- Lane Report ({item.get('lane_id') or 'lane'}): "
                f"path={item.get('report_path') or '-'} / "
                f"lane_status={item.get('status') or 'skipped'} / "
                f"build={item.get('build_id') or '-'} / "
                f"channel={item.get('channel') or '-'} / "
                f"executed_at={item.get('executed_at') or '-'}"
            )
    return lines


def _full_live_validation_lane_artifact_status(lane_artifact: Dict[str, Any]) -> str:
    return "passed" if str(lane_artifact.get("report_path") or "").strip() else "warning"


def _build_full_live_validation_lane_artifact_entries(summary: Dict[str, Any]) -> List[Dict[str, Any]]:
    details = dict(summary.get("details") or {})
    artifacts: List[Dict[str, Any]] = []
    for item in list(details.get("lane_artifacts") or []):
        if not isinstance(item, dict):
            continue
        lane_artifact = dict(item)
        lane_id = str(lane_artifact.get("lane_id") or "").strip() or f"lane_{len(artifacts) + 1}"
        artifacts.append(
            _artifact(
                f"full_live_validation_lane_{_slugify_live_validation_lane_id(lane_id)}",
                f"Live Lane Report: {lane_artifact.get('label') or lane_id}",
                _full_live_validation_lane_artifact_status(lane_artifact),
                str(lane_artifact.get("report_path") or "").strip(),
                (
                    f"lane_status={lane_artifact.get('status') or 'skipped'} / "
                    f"build={lane_artifact.get('build_id') or '-'} / "
                    f"channel={lane_artifact.get('channel') or '-'} / "
                    f"executed_at={lane_artifact.get('executed_at') or '-'}"
                ),
                required=False,
                kind="validation_lane",
                details=lane_artifact,
            )
        )
    return artifacts


def _status_from_contract(payload: Dict[str, Any]) -> str:
    status = str(payload.get("status") or "").strip().lower()
    return status if status in {"passed", "warning", "blocked", "skipped"} else ("blocked" if payload.get("should_block") else "passed")


def _status_from_agent_compat(payload: Dict[str, Any]) -> str:
    status = str(payload.get("status") or "").strip().lower()
    return status if status in {"passed", "warning", "blocked", "skipped"} else ("blocked" if not payload.get("passed", False) else "passed")


def _status_from_scene_ownership(payload: Dict[str, Any]) -> str:
    if int(payload.get("scene_count") or 0) <= 0:
        return "skipped"
    return _status_from_contract(payload)


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
        "details": details or {},
    }


def _artifact(
    artifact_id: str,
    label: str,
    status: str,
    path: str,
    summary: str,
    *,
    required: bool,
    kind: str = "artifact",
    details: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    return {
        "artifact_id": artifact_id,
        "label": label,
        "status": status,
        "path": str(path or "").strip(),
        "summary": str(summary or "").strip(),
        "required": required,
        "kind": kind,
        "details": details or {},
    }


def _check(
    check_id: str,
    label: str,
    status: str,
    message: str,
    *,
    required: bool,
    details: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    return {
        "check_id": check_id,
        "label": label,
        "status": status,
        "required": required,
        "message": message,
        "details": details or {},
    }


def _build_evidence_bundle(
    project_root: Path,
    runtime_root: Path,
    target_channel: str,
    target_environment: str,
    approvers: List[str],
    missing_signoffs: List[str],
    release_candidate: Dict[str, Any],
    build_run_matrix: Dict[str, Any],
    scene_ownership_board: Dict[str, Any],
    release_live_runner_baseline: Dict[str, Any],
    release_live_ci_summary: Dict[str, Any],
    request_auth_posture: Dict[str, Any],
    request_auth_rotation_audit: Dict[str, Any],
    request_auth_identity_audit: Dict[str, Any],
    release_distribution_bundle: Dict[str, Any],
) -> Dict[str, Any]:
    release_summary = dict(release_candidate.get("release_summary") or {})
    qa_evidence = dict(release_summary.get("qa_evidence") or {})
    expected_release_binding = _expected_release_binding_summary(release_candidate, release_summary)
    clean_machine_bootstrap = _load_clean_machine_bootstrap_report(
        project_root,
        runtime_root,
        target_channel=target_channel,
    )
    full_live_validation = _load_full_live_validation_report(
        project_root,
        runtime_root,
        target_channel=target_channel,
    )
    full_live_validation = _bind_full_live_validation_to_release(
        full_live_validation,
        expected_release_binding,
        target_channel=target_channel,
        project_root=project_root,
        runtime_root=runtime_root,
    )
    default_sequence = list(build_run_matrix.get("default_sequence") or [])
    artifacts = [
        _artifact(
            "release_manifest",
            "Release Manifest",
            _release_candidate_item_status(release_candidate, "release_manifest"),
            str(release_candidate.get("release_manifest_path") or ""),
            f"source={release_candidate.get('release_manifest_source') or 'missing'}",
            required=True,
            kind="contract",
        ),
        _artifact(
            "release_notes",
            "Release Notes",
            _release_candidate_item_status(release_candidate, "release_notes"),
            str(release_candidate.get("release_notes_path") or ""),
            f"build_id={release_summary.get('build_id') or '-'}",
            required=True,
            kind="report",
        ),
        _artifact(
            "qa_gate_report",
            "QA Gate Report",
            _release_candidate_item_status(release_candidate, "qa_gate_report"),
            str(release_candidate.get("qa_gate_report_path") or ""),
            f"quality_passed={release_summary.get('quality_gate', {}).get('passed')}",
            required=True,
            kind="report",
        ),
        _artifact(
            "qa_evidence_summary",
            "QA Evidence Summary",
            _normalize_release_qa_status(qa_evidence.get("status"), target_channel=target_channel),
            str(qa_evidence.get("screenshot_path") or ""),
            _build_release_qa_summary(qa_evidence),
            required=True,
            kind="qa",
            details={
                "scene_path": qa_evidence.get("scene_path") or "",
                "assertion_node_count": int(qa_evidence.get("assertion_node_count") or 0),
                "screenshot_diff_ratio": qa_evidence.get("screenshot_diff_ratio"),
                "max_screenshot_diff_ratio": qa_evidence.get("max_screenshot_diff_ratio"),
            },
        ),
        _artifact(
            "clean_machine_bootstrap",
            "Clean Machine Bootstrap Report",
            str(clean_machine_bootstrap.get("status") or "warning"),
            str(clean_machine_bootstrap.get("path") or ""),
            str(clean_machine_bootstrap.get("summary") or ""),
            required=True,
            kind="bootstrap",
            details=dict(clean_machine_bootstrap.get("details") or {}),
        ),
        _artifact(
            "full_live_validation",
            "Full Live Validation Report",
            str(full_live_validation.get("status") or "warning"),
            str(full_live_validation.get("path") or ""),
            str(full_live_validation.get("summary") or ""),
            required=target_channel == "release",
            kind="validation",
            details=dict(full_live_validation.get("details") or {}),
        ),
        *_build_full_live_validation_lane_artifact_entries(full_live_validation),
        _artifact(
            "release_live_runner_baseline",
            "Release Live Runner Baseline",
            _release_live_runner_baseline_gate_status(release_live_runner_baseline, target_channel=target_channel),
            _release_live_runner_baseline_artifact_path(release_live_runner_baseline),
            str(release_live_runner_baseline.get("summary") or ""),
            required=target_channel == "release",
            kind="environment",
            details=dict(release_live_runner_baseline.get("details") or {}),
        ),
        _artifact(
            "release_live_ci_summary",
            "Release Live CI Summary",
            _release_live_ci_summary_gate_status(release_live_ci_summary, target_channel=target_channel),
            _release_live_ci_summary_artifact_path(release_live_ci_summary),
            str(release_live_ci_summary.get("summary") or ""),
            required=target_channel == "release",
            kind="environment",
            details=dict(release_live_ci_summary.get("details") or {}),
        ),
        _artifact(
            "release_request_auth_posture",
            "Release Request Auth Posture",
            _request_auth_posture_gate_status(request_auth_posture, target_channel=target_channel),
            _request_auth_posture_artifact_path(request_auth_posture),
            str(request_auth_posture.get("summary") or ""),
            required=target_channel == "release",
            kind="security",
            details=dict(request_auth_posture),
        ),
        _artifact(
            "release_request_auth_rotation_audit",
            "Release Request Auth Rotation Audit",
            _request_auth_rotation_audit_gate_status(request_auth_rotation_audit, target_channel=target_channel),
            _request_auth_rotation_audit_artifact_path(request_auth_rotation_audit),
            str(request_auth_rotation_audit.get("summary") or ""),
            required=target_channel == "release",
            kind="security",
            details=dict(request_auth_rotation_audit),
        ),
        _artifact(
            "release_request_auth_identity_audit",
            "Release Request Auth Identity Audit",
            _request_auth_identity_audit_gate_status(request_auth_identity_audit, target_channel=target_channel),
            _request_auth_identity_audit_artifact_path(request_auth_identity_audit),
            str(request_auth_identity_audit.get("summary") or ""),
            required=target_channel == "release",
            kind="security",
            details=dict(request_auth_identity_audit),
        ),
        _artifact(
            "release_distribution_bundle",
            "Release Distribution Bundle",
            _release_distribution_bundle_gate_status(release_distribution_bundle, target_channel=target_channel),
            _release_distribution_bundle_artifact_path(release_distribution_bundle),
            str(release_distribution_bundle.get("summary") or ""),
            required=target_channel == "release",
            kind="distribution",
            details=dict(release_distribution_bundle),
        ),
        _artifact(
            "release_distribution_publish_receipts",
            "Release Distribution Publish Receipts",
            _release_distribution_publish_receipts_artifact_status(release_distribution_bundle),
            _release_distribution_publish_receipts_artifact_path(release_distribution_bundle),
            _build_release_distribution_publish_receipts_summary(release_distribution_bundle),
            required=False,
            kind="distribution",
            details=_release_distribution_publish_receipts_artifact_details(release_distribution_bundle),
        ),
        _artifact(
            "build_log",
            "Build Log",
            "passed" if str(release_candidate.get("build_log_path") or "").strip() else "blocked",
            str(release_candidate.get("build_log_path") or ""),
            f"release_dir={release_summary.get('release_dir') or '-'}",
            required=True,
            kind="log",
        ),
        _artifact(
            "release_output",
            "Release Output",
            _release_candidate_item_status(release_candidate, "release_outputs"),
            str(release_summary.get("output_path") or release_summary.get("release_dir") or ""),
            f"release_url={release_summary.get('release_url') or '-'}",
            required=True,
            kind="artifact",
        ),
        _artifact(
            "versioned_release",
            "Versioned Release URL",
            "passed" if str(release_summary.get("versioned_release_url") or "").strip() else "warning",
            str(release_summary.get("versioned_release_url") or ""),
            f"latest={release_summary.get('release_url') or '-'}",
            required=False,
            kind="url",
        ),
        _artifact(
            "rollback_hint",
            "Rollback Hint",
            _release_candidate_item_status(release_candidate, "rollback_ready"),
            "",
            str(release_summary.get("rollback_hint") or "未声明 rollback_hint"),
            required=True,
            kind="rollback",
        ),
        _artifact(
            "signoff_record",
            "Promotion Signoffs",
            "blocked" if missing_signoffs else "passed",
            "",
            f"provided={', '.join(approvers) or 'none'} / missing={', '.join(missing_signoffs) or 'none'}",
            required=True,
            kind="signoff",
        ),
        _artifact(
            "matrix_default_sequence",
            "Matrix Default Sequence",
            "passed" if default_sequence else "blocked",
            "",
            ", ".join(default_sequence) or "none",
            required=True,
            kind="runbook",
        ),
    ]
    if int(scene_ownership_board.get("scene_count") or 0) > 0:
        artifacts.append(
            _artifact(
                "scene_ownership_board",
                "Scene Ownership Board",
                _status_from_scene_ownership(scene_ownership_board),
                str(scene_ownership_board.get("board_path") or ""),
                f"scenes={scene_ownership_board.get('scene_count') or 0} / missing_owner={scene_ownership_board.get('missing_owner_count') or 0}",
                required=False,
                kind="collaboration",
            )
        )

    missing_artifacts = [item["artifact_id"] for item in artifacts if item["status"] == "blocked"]
    warning_artifacts = [item["artifact_id"] for item in artifacts if item["status"] == "warning"]
    return {
        "status": "blocked" if missing_artifacts else ("warning" if warning_artifacts else "passed"),
        "should_block": bool(missing_artifacts),
        "artifact_count": len(artifacts),
        "artifacts": artifacts,
        "missing_artifacts": missing_artifacts,
        "warning_artifacts": warning_artifacts,
        "release_metadata": {
            "build_id": str(release_summary.get("build_id") or ""),
            "version": str(release_summary.get("version") or ""),
            "channel": str(release_summary.get("channel") or ""),
            "generated_at": str(release_summary.get("generated_at") or ""),
            "target_channel": target_channel,
            "target_environment": target_environment,
            "release_url": str(release_summary.get("release_url") or ""),
            "versioned_release_url": str(release_summary.get("versioned_release_url") or ""),
        },
        "notes": [
            f"Target promotion: {target_channel} -> {target_environment}",
            f"Build: {release_summary.get('build_id') or '-'} / Version: {release_summary.get('version') or '-'}",
            f"QA evidence: {_build_release_qa_summary(qa_evidence)}",
            f"Clean machine bootstrap: {clean_machine_bootstrap.get('summary') or 'missing'}",
            f"Full live validation: {full_live_validation.get('summary') or 'missing'}",
            f"Release live runner baseline: {release_live_runner_baseline.get('summary') or 'missing'}",
            f"Release live CI summary: {release_live_ci_summary.get('summary') or 'missing'}",
            f"Release request auth posture: {request_auth_posture.get('summary') or 'missing'}",
            f"Release request auth rotation audit: {request_auth_rotation_audit.get('summary') or 'missing'}",
            f"Release request auth identity audit: {request_auth_identity_audit.get('summary') or 'missing'}",
            f"Release distribution bundle: {release_distribution_bundle.get('summary') or 'missing'}",
            f"Release distribution publish receipts: {_build_release_distribution_publish_receipts_summary(release_distribution_bundle)}",
        ],
    }


def _build_review_bundle(
    project_root: Path,
    runtime_root: Path,
    target_channel: str,
    target_environment: str,
    required_signoffs: List[str],
    approvers: List[str],
    missing_signoffs: List[str],
    release_candidate: Dict[str, Any],
    release_live_runner_baseline: Dict[str, Any],
    release_live_ci_summary: Dict[str, Any],
    request_auth_posture: Dict[str, Any],
    request_auth_rotation_audit: Dict[str, Any],
    request_auth_identity_audit: Dict[str, Any],
    release_distribution_bundle: Dict[str, Any],
) -> Dict[str, Any]:
    release_summary = dict(release_candidate.get("release_summary") or {})
    feature = dict(release_summary.get("feature") or {})
    change_summary = list(release_summary.get("change_summary") or [])
    acceptance_checklist = list(release_summary.get("acceptance_checklist") or [])
    changed_paths = list(release_candidate.get("changed_paths") or [])
    known_issues = list(release_summary.get("known_issues") or release_summary.get("known_risks") or [])
    qa_evidence = dict(release_summary.get("qa_evidence") or {})
    expected_release_binding = _expected_release_binding_summary(release_candidate, release_summary)
    clean_machine_bootstrap = _load_clean_machine_bootstrap_report(
        project_root,
        runtime_root,
        target_channel=target_channel,
    )
    full_live_validation = _load_full_live_validation_report(
        project_root,
        runtime_root,
        target_channel=target_channel,
    )
    full_live_validation = _bind_full_live_validation_to_release(
        full_live_validation,
        expected_release_binding,
        target_channel=target_channel,
        project_root=project_root,
        runtime_root=runtime_root,
    )

    acceptance_ready = sum(1 for item in acceptance_checklist if str(item.get("status") or "").strip().lower() == "ready")
    acceptance_pending = sum(1 for item in acceptance_checklist if str(item.get("status") or "").strip().lower() == "pending")
    acceptance_blocked = sum(1 for item in acceptance_checklist if str(item.get("status") or "").strip().lower() == "blocked")

    artifact_links = [
        _artifact(
            "release_manifest",
            "Release Manifest",
            _release_candidate_item_status(release_candidate, "release_manifest"),
            str(release_candidate.get("release_manifest_path") or ""),
            f"build_id={release_summary.get('build_id') or '-'}",
            required=True,
            kind="contract",
        ),
        _artifact(
            "release_notes",
            "Release Notes",
            _release_candidate_item_status(release_candidate, "release_notes"),
            str(release_candidate.get("release_notes_path") or ""),
            f"version={release_summary.get('version') or '-'}",
            required=True,
            kind="report",
        ),
        _artifact(
            "qa_gate_report",
            "QA Gate Report",
            _release_candidate_item_status(release_candidate, "qa_gate_report"),
            str(release_candidate.get("qa_gate_report_path") or ""),
            f"quality_passed={release_summary.get('quality_gate', {}).get('passed')}",
            required=True,
            kind="report",
        ),
        _artifact(
            "qa_evidence_summary",
            "QA Evidence Summary",
            _normalize_release_qa_status(qa_evidence.get("status"), target_channel=target_channel),
            str(qa_evidence.get("screenshot_path") or ""),
            _build_release_qa_summary(qa_evidence),
            required=True,
            kind="qa",
            details={
                "scene_path": qa_evidence.get("scene_path") or "",
                "assertion_node_count": int(qa_evidence.get("assertion_node_count") or 0),
                "screenshot_diff_ratio": qa_evidence.get("screenshot_diff_ratio"),
                "max_screenshot_diff_ratio": qa_evidence.get("max_screenshot_diff_ratio"),
            },
        ),
        _artifact(
            "clean_machine_bootstrap",
            "Clean Machine Bootstrap Report",
            str(clean_machine_bootstrap.get("status") or "warning"),
            str(clean_machine_bootstrap.get("path") or ""),
            str(clean_machine_bootstrap.get("summary") or ""),
            required=True,
            kind="bootstrap",
            details=dict(clean_machine_bootstrap.get("details") or {}),
        ),
        _artifact(
            "full_live_validation",
            "Full Live Validation Report",
            str(full_live_validation.get("status") or "warning"),
            str(full_live_validation.get("path") or ""),
            str(full_live_validation.get("summary") or ""),
            required=target_channel == "release",
            kind="validation",
            details=dict(full_live_validation.get("details") or {}),
        ),
        *_build_full_live_validation_lane_artifact_entries(full_live_validation),
        _artifact(
            "release_live_runner_baseline",
            "Release Live Runner Baseline",
            _release_live_runner_baseline_gate_status(release_live_runner_baseline, target_channel=target_channel),
            _release_live_runner_baseline_artifact_path(release_live_runner_baseline),
            str(release_live_runner_baseline.get("summary") or ""),
            required=target_channel == "release",
            kind="environment",
            details=dict(release_live_runner_baseline.get("details") or {}),
        ),
        _artifact(
            "release_live_ci_summary",
            "Release Live CI Summary",
            _release_live_ci_summary_gate_status(release_live_ci_summary, target_channel=target_channel),
            _release_live_ci_summary_artifact_path(release_live_ci_summary),
            str(release_live_ci_summary.get("summary") or ""),
            required=target_channel == "release",
            kind="environment",
            details=dict(release_live_ci_summary.get("details") or {}),
        ),
        _artifact(
            "release_request_auth_posture",
            "Release Request Auth Posture",
            _request_auth_posture_gate_status(request_auth_posture, target_channel=target_channel),
            _request_auth_posture_artifact_path(request_auth_posture),
            str(request_auth_posture.get("summary") or ""),
            required=target_channel == "release",
            kind="security",
            details=dict(request_auth_posture),
        ),
        _artifact(
            "release_request_auth_rotation_audit",
            "Release Request Auth Rotation Audit",
            _request_auth_rotation_audit_gate_status(request_auth_rotation_audit, target_channel=target_channel),
            _request_auth_rotation_audit_artifact_path(request_auth_rotation_audit),
            str(request_auth_rotation_audit.get("summary") or ""),
            required=target_channel == "release",
            kind="security",
            details=dict(request_auth_rotation_audit),
        ),
        _artifact(
            "release_request_auth_identity_audit",
            "Release Request Auth Identity Audit",
            _request_auth_identity_audit_gate_status(request_auth_identity_audit, target_channel=target_channel),
            _request_auth_identity_audit_artifact_path(request_auth_identity_audit),
            str(request_auth_identity_audit.get("summary") or ""),
            required=target_channel == "release",
            kind="security",
            details=dict(request_auth_identity_audit),
        ),
        _artifact(
            "release_distribution_bundle",
            "Release Distribution Bundle",
            _release_distribution_bundle_gate_status(release_distribution_bundle, target_channel=target_channel),
            _release_distribution_bundle_artifact_path(release_distribution_bundle),
            str(release_distribution_bundle.get("summary") or ""),
            required=target_channel == "release",
            kind="distribution",
            details=dict(release_distribution_bundle),
        ),
        _artifact(
            "release_distribution_publish_receipts",
            "Release Distribution Publish Receipts",
            _release_distribution_publish_receipts_artifact_status(release_distribution_bundle),
            _release_distribution_publish_receipts_artifact_path(release_distribution_bundle),
            _build_release_distribution_publish_receipts_summary(release_distribution_bundle),
            required=False,
            kind="distribution",
            details=_release_distribution_publish_receipts_artifact_details(release_distribution_bundle),
        ),
        _artifact(
            "build_log",
            "Build Log",
            "passed" if str(release_candidate.get("build_log_path") or "").strip() else "warning",
            str(release_candidate.get("build_log_path") or ""),
            f"release_dir={release_summary.get('release_dir') or '-'}",
            required=False,
            kind="log",
        ),
        _artifact(
            "release_output",
            "Release Output",
            _release_candidate_item_status(release_candidate, "release_outputs"),
            str(release_summary.get("output_path") or release_summary.get("release_dir") or ""),
            f"release_url={release_summary.get('release_url') or '-'}",
            required=True,
            kind="artifact",
        ),
        _artifact(
            "versioned_release_url",
            "Versioned Release URL",
            "passed" if str(release_summary.get("versioned_release_url") or "").strip() else "warning",
            str(release_summary.get("versioned_release_url") or ""),
            f"latest={release_summary.get('release_url') or '-'}",
            required=False,
            kind="url",
        ),
        _artifact(
            "rollback_hint",
            "Rollback Hint",
            _release_candidate_item_status(release_candidate, "rollback_ready"),
            "",
            str(release_summary.get("rollback_hint") or "未声明 rollback_hint"),
            required=True,
            kind="rollback",
        ),
    ]

    blocking_items: List[str] = []
    if not change_summary:
        blocking_items.append("change_summary")
    if not acceptance_checklist or acceptance_blocked:
        blocking_items.append("acceptance_checklist")
    if _normalize_release_qa_status(qa_evidence.get("status"), target_channel=target_channel) == "blocked":
        blocking_items.append("qa_evidence")
    blocking_items.extend(
        item["artifact_id"]
        for item in artifact_links
        if item["required"] and item["status"] == "blocked" and item["artifact_id"] not in blocking_items
    )

    warning_items: List[str] = []
    if acceptance_pending and "acceptance_checklist" not in blocking_items:
        warning_items.append("acceptance_checklist")
    if not changed_paths:
        warning_items.append("changed_paths")
    if missing_signoffs:
        warning_items.append("signoffs")
    if (
        _normalize_release_qa_status(qa_evidence.get("status"), target_channel=target_channel) == "warning"
        and "qa_evidence" not in warning_items
    ):
        warning_items.append("qa_evidence")
    warning_items.extend(
        item["artifact_id"]
        for item in artifact_links
        if item["status"] == "warning" and item["artifact_id"] not in warning_items
    )

    audience_summaries = [
        {
            "audience_id": "engineering",
            "label": "Engineering",
            "summary_lines": [
                f"Feature {feature.get('feature_id') or '-'} by {feature.get('owner') or '-'} / status={feature.get('feature_status') or '-'}",
                f"Structured change summary items: {len(change_summary)}",
                f"Changed paths recorded: {len(changed_paths)}",
                f"Exported files captured: {len(list(release_summary.get('files') or []))}",
            ] + [str(item) for item in change_summary[:3]],
        },
        {
            "audience_id": "qa",
            "label": "QA",
            "summary_lines": [
                f"Acceptance ready={acceptance_ready} pending={acceptance_pending} blocked={acceptance_blocked}",
                f"Quality gate passed={bool(release_summary.get('quality_gate', {}).get('passed'))}",
                f"QA evidence {_build_release_qa_summary(qa_evidence)}",
                f"Clean machine bootstrap {clean_machine_bootstrap.get('summary') or 'missing'}",
                f"Full live validation {full_live_validation.get('summary') or 'missing'}",
                f"Release live runner baseline {release_live_runner_baseline.get('summary') or 'missing'}",
                f"Request auth posture {request_auth_posture.get('summary') or 'missing'}",
                f"Request auth rotation audit {request_auth_rotation_audit.get('summary') or 'missing'}",
                f"Request auth identity audit {request_auth_identity_audit.get('summary') or 'missing'}",
                f"Release distribution bundle {release_distribution_bundle.get('summary') or 'missing'}",
                f"Distribution publish receipts {_build_release_distribution_publish_receipts_summary(release_distribution_bundle)}",
                f"Known issues count={len(known_issues)}",
            ] + [str(item) for item in known_issues[:3]],
        },
        {
            "audience_id": "production",
            "label": "Production",
            "summary_lines": [
                f"Target promotion: {target_channel} -> {target_environment}",
                f"Build {release_summary.get('build_id') or '-'} / version {release_summary.get('version') or '-'} / release channel {release_summary.get('channel') or '-'}",
                f"Signoffs provided={', '.join(approvers) or 'none'} / missing={', '.join(missing_signoffs) or 'none'}",
                f"Clean machine bootstrap: {clean_machine_bootstrap.get('summary') or 'missing'}",
                f"Full live validation: {full_live_validation.get('summary') or 'missing'}",
                f"Release live runner baseline: {release_live_runner_baseline.get('summary') or 'missing'}",
                f"Request auth posture: {request_auth_posture.get('summary') or 'missing'}",
                f"Request auth rotation audit: {request_auth_rotation_audit.get('summary') or 'missing'}",
                f"Request auth identity audit: {request_auth_identity_audit.get('summary') or 'missing'}",
                f"Release distribution bundle: {release_distribution_bundle.get('summary') or 'missing'}",
                f"Distribution publish receipts: {_build_release_distribution_publish_receipts_summary(release_distribution_bundle)}",
                f"Rollback: {release_summary.get('rollback_hint') or '未声明 rollback_hint'}",
            ],
        },
    ]

    recommendations: List[str] = []
    if "change_summary" in blocking_items:
        recommendations.append("补齐结构化 change_summary，避免评审包只剩构建产物没有改动摘要。")
    if "acceptance_checklist" in blocking_items or "acceptance_checklist" in warning_items:
        recommendations.append("补齐 acceptance_checklist 状态和结论，确保 QA/制作能直接复核。")
    if "qa_evidence" in blocking_items or "qa_evidence" in warning_items:
        recommendations.append("补齐断言型 QA 与 visual regression 证据，确保 release_summary 能直接给 RC / promotion 复核。")
    if "clean_machine_bootstrap" in blocking_items or "clean_machine_bootstrap" in warning_items:
        recommendations.append("补跑 clean machine bootstrap，并保留 logs/reports/clean_machine_bootstrap.json 供 promotion evidence / review bundle 复核。")
    if "full_live_validation" in blocking_items or "full_live_validation" in warning_items:
        recommendations.append("补跑 full live validation，并保留 logs/reports/full_live_validation.json 供 promotion evidence / review bundle / execution report 复核。")
    if "release_request_auth_posture" in blocking_items or "release_request_auth_posture" in warning_items:
        recommendations.append("补齐 release_request_auth posture：关闭 local bypass，移除 env fallback，并为当前 action/channel 配置 actor-bound token。")
    if "release_request_auth_rotation_audit" in blocking_items or "release_request_auth_rotation_audit" in warning_items:
        recommendations.append("补齐 release_request_auth rotation audit：同时覆盖 promotion_record / release_execution，并清理 expires_at hygiene 与重复 token_id。")
    if "release_request_auth_identity_audit" in blocking_items or "release_request_auth_identity_audit" in warning_items:
        recommendations.append("补齐 release_request_auth identity audit：确保 scoped issuer、subject actor 绑定和 release session policy 能通过独立审计。")
    if "release_distribution_bundle" in blocking_items or "release_distribution_bundle" in warning_items:
        recommendations.append("先导出 versioned distribution bundle，再发起团队评审；不要让安装/升级/卸载路径只停留在口头说明。")
    if "release_distribution_publish_receipts" in warning_items:
        recommendations.append(
            "外部分发一旦开始，就按 publish target 回写 receipt；不要让 review / execution 只能看到 publish handoff，却看不到哪些目标已经真正完成。"
        )
    if "changed_paths" in warning_items:
        recommendations.append("记录 changed_paths，至少标出本次交付涉及的核心路径。")
    if missing_signoffs:
        recommendations.append(f"当前仍缺少 signoff: {', '.join(missing_signoffs)}。")
    if not recommendations:
        recommendations.append("Review bundle 已具备结构化摘要，可直接进入程序/QA/制作评审。")

    return normalize_release_review_bundle({
        "project_root": str(project_root),
        "runtime_root": str(runtime_root),
        "target_channel": target_channel,
        "target_environment": target_environment,
        "promotion_target_label": f"{target_channel} -> {target_environment}",
        "build_id": str(release_summary.get("build_id") or ""),
        "version": str(release_summary.get("version") or ""),
        "release_channel": str(release_summary.get("channel") or ""),
        "generated_at": str(release_summary.get("generated_at") or ""),
        "release_manifest_path": str(release_candidate.get("release_manifest_path") or ""),
        "feature": feature,
        "change_summary": change_summary,
        "changed_paths": changed_paths,
        "acceptance_checklist": acceptance_checklist,
        "known_issues": known_issues,
        "artifact_links": artifact_links,
        "validation_records": [
            {
                "record_id": "qa_evidence",
                "label": "QA Evidence",
                "status": _normalize_release_qa_status(qa_evidence.get("status"), target_channel=target_channel),
                "source": "release_qa_evidence",
                "validation_method": "qa_gate",
                "path": str(qa_evidence.get("screenshot_path") or ""),
                "summary": _build_release_qa_summary(qa_evidence),
            }
        ],
        "audience_summaries": audience_summaries,
        "required_signoffs": required_signoffs,
        "provided_signoffs": approvers,
        "missing_signoffs": missing_signoffs,
        "blocking_items": blocking_items,
        "warning_items": warning_items,
        "notes": [
            f"Review bundle source build: {release_summary.get('build_id') or '-'}",
            "Review bundle 只汇总结构化评审信息，不执行真实 promotion。",
        ],
        "recommendations": recommendations,
        "contract_versions": {
            "release_candidate_checklist": str(release_candidate.get("schema_version") or ""),
            "release_summary": str(release_summary.get("schema_version") or ""),
            "release_promotion_plan": RELEASE_PROMOTION_PLAN_SCHEMA_VERSION,
        },
    })


def _build_deployment_rehearsal(
    project_root: Path,
    runtime_root: Path,
    target_channel: str,
    target_environment: str,
    approvers: List[str],
    missing_signoffs: List[str],
    release_candidate: Dict[str, Any],
    build_run_matrix: Dict[str, Any],
    scene_ownership_board: Dict[str, Any],
    release_live_runner_baseline: Dict[str, Any],
    release_live_ci_summary: Dict[str, Any],
    request_auth_posture: Dict[str, Any],
    request_auth_rotation_audit: Dict[str, Any],
    request_auth_identity_audit: Dict[str, Any],
    release_distribution_bundle: Dict[str, Any],
) -> Dict[str, Any]:
    release_summary = dict(release_candidate.get("release_summary") or {})
    expected_release_binding = _expected_release_binding_summary(release_candidate, release_summary)
    default_sequence = list(build_run_matrix.get("default_sequence") or [])
    full_live_row = _find_matrix_row(build_run_matrix, "full_live_validation")
    full_live_validation = _load_full_live_validation_report(
        project_root,
        runtime_root,
        target_channel=target_channel,
    )
    full_live_validation = _bind_full_live_validation_to_release(
        full_live_validation,
        expected_release_binding,
        target_channel=target_channel,
        project_root=project_root,
        runtime_root=runtime_root,
    )
    lane_sequence = list(default_sequence)
    if target_channel == "release" and full_live_row and "full_live_validation" not in lane_sequence:
        lane_sequence.append("full_live_validation")
    preflight_checks = [
        _check(
            "release_candidate_gate",
            "Release Candidate Gate",
            _status_from_contract(release_candidate),
            f"blocking_checks={', '.join(list(release_candidate.get('blocking_checks') or [])) or 'none'}",
            required=True,
        ),
        _check(
            "build_run_matrix_gate",
            "Build / Run Matrix",
            _status_from_contract(build_run_matrix),
            f"default_sequence={', '.join(default_sequence) or 'none'}",
            required=True,
        ),
        _check(
            "promotion_target",
            "Promotion Target",
            "passed" if target_channel and target_environment else "blocked",
            f"{target_channel or '-'} -> {target_environment or '-'}",
            required=True,
        ),
        _check(
            "signoff_gate",
            "Promotion Signoffs",
            "blocked" if missing_signoffs else "passed",
            f"provided={', '.join(approvers) or 'none'} / missing={', '.join(missing_signoffs) or 'none'}",
            required=True,
        ),
        _check(
            "deployment_targets",
            "Deployment Targets",
            "passed" if str(release_summary.get("output_path") or release_summary.get("release_dir") or "").strip() else "blocked",
            f"output={release_summary.get('output_path') or release_summary.get('release_dir') or '-'} / release_url={release_summary.get('release_url') or '-'}",
            required=True,
        ),
        _check(
            "full_live_validation_lane",
            "Full Live Validation Lane",
            (
                str(full_live_validation.get("status") or "warning")
                if full_live_row
                else ("blocked" if target_channel == "release" else "skipped")
            ),
            (
                f"{full_live_row.get('label') or 'full_live_validation'}: {full_live_validation.get('summary') or 'missing'}"
                if full_live_row
                else ("full_live_validation lane is required for release promotion" if target_channel == "release" else "Not required for non-release promotion")
            ),
            required=target_channel == "release",
            details={
                "report_path": str(full_live_validation.get("path") or ""),
                "blocking_issue_codes": list(full_live_validation.get("details", {}).get("blocking_issue_codes") or []),
                "release_binding_status": str(full_live_validation.get("details", {}).get("release_binding_status") or ""),
                "release_binding_mismatches": list(full_live_validation.get("details", {}).get("release_binding_mismatches") or []),
                "step_statuses": list(full_live_validation.get("details", {}).get("step_statuses") or []),
            },
        ),
        _check(
            "release_live_runner_baseline_gate",
            "Release Live Runner Baseline",
            _release_live_runner_baseline_gate_status(
                release_live_runner_baseline,
                target_channel=target_channel,
            ),
            str(release_live_runner_baseline.get("summary") or "release live runner baseline not evaluated"),
            required=target_channel == "release",
            details=dict(release_live_runner_baseline),
        ),
        _check(
            "release_live_ci_summary_gate",
            "Release Live CI Summary",
            _release_live_ci_summary_gate_status(
                release_live_ci_summary,
                target_channel=target_channel,
            ),
            str(release_live_ci_summary.get("summary") or "release live ci summary not evaluated"),
            required=target_channel == "release",
            details=dict(release_live_ci_summary),
        ),
        _check(
            "request_auth_posture_gate",
            "Release Request Auth Posture",
            _request_auth_posture_gate_status(request_auth_posture, target_channel=target_channel),
            str(request_auth_posture.get("summary") or "release request auth posture not evaluated"),
            required=target_channel == "release",
            details=dict(request_auth_posture),
        ),
        _check(
            "request_auth_rotation_audit_gate",
            "Release Request Auth Rotation Audit",
            _request_auth_rotation_audit_gate_status(request_auth_rotation_audit, target_channel=target_channel),
            str(request_auth_rotation_audit.get("summary") or "release request auth rotation audit not evaluated"),
            required=target_channel == "release",
            details=dict(request_auth_rotation_audit),
        ),
        _check(
            "request_auth_identity_audit_gate",
            "Release Request Auth Identity Audit",
            _request_auth_identity_audit_gate_status(request_auth_identity_audit, target_channel=target_channel),
            str(request_auth_identity_audit.get("summary") or "release request auth identity audit not evaluated"),
            required=target_channel == "release",
            details=dict(request_auth_identity_audit),
        ),
        _check(
            "release_distribution_bundle_gate",
            "Release Distribution Bundle",
            _release_distribution_bundle_gate_status(release_distribution_bundle, target_channel=target_channel),
            str(release_distribution_bundle.get("summary") or "release distribution bundle not evaluated"),
            required=target_channel == "release",
            details=dict(release_distribution_bundle),
        ),
    ]
    if int(scene_ownership_board.get("scene_count") or 0) > 0:
        preflight_checks.append(
            _check(
                "scene_collaboration",
                "Scene Collaboration",
                _status_from_scene_ownership(scene_ownership_board),
                f"missing_owner={scene_ownership_board.get('missing_owner_count') or 0}",
                required=False,
            )
        )
    blocked_checks = [item["check_id"] for item in preflight_checks if item["status"] == "blocked"]
    warning_checks = [item["check_id"] for item in preflight_checks if item["status"] == "warning"]
    return {
        "status": "blocked" if blocked_checks else ("warning" if warning_checks else "passed"),
        "should_block": bool(blocked_checks),
        "target_channel": target_channel,
        "target_environment": target_environment,
        "lane_sequence": lane_sequence,
        "preflight_checks": preflight_checks,
        "blocking_checks": blocked_checks,
        "warning_checks": warning_checks,
        "verification_targets": {
            "release_url": str(release_summary.get("release_url") or ""),
            "versioned_release_url": str(release_summary.get("versioned_release_url") or ""),
            "output_path": str(release_summary.get("output_path") or ""),
        },
        "verification_steps": [
            f"按顺序执行 lanes: {', '.join(lane_sequence) or 'none'}",
            f"确认 build_id/version/channel: {release_summary.get('build_id') or '-'} / {release_summary.get('version') or '-'} / {release_summary.get('channel') or '-'}",
            f"验证目标入口: {release_summary.get('release_url') or release_summary.get('output_path') or '-'}",
            f"验证 versioned 入口: {release_summary.get('versioned_release_url') or '-'}",
            f"复核 full live validation 证据: {full_live_validation.get('path') or 'missing'}",
            f"复核 runner baseline: {release_live_runner_baseline.get('path') or 'missing'}",
            f"复核 release live ci summary: {_release_live_ci_summary_artifact_path(release_live_ci_summary) or 'missing'}",
            f"复核 request auth posture: {request_auth_posture.get('summary') or 'missing'}",
            f"复核 request auth rotation audit: {request_auth_rotation_audit.get('summary') or 'missing'}",
            f"复核 request auth identity audit: {request_auth_identity_audit.get('summary') or 'missing'}",
            f"复核 distribution bundle: {release_distribution_bundle.get('summary') or 'missing'}",
            f"复核 distribution publish receipts: {_build_release_distribution_publish_receipts_summary(release_distribution_bundle)}",
            "确认 release notes、QA gate、performance/telemetry 摘要都已归档到 evidence bundle",
        ],
        "cutover_steps": [
            f"在 {target_environment} smoke 通过后再切换 promotion alias 或外部入口",
            "记录实际执行时间、执行人和 signoff 来源，不要只留在聊天记录里",
            "切换后立刻复核 Portal、quality gate、telemetry 和 performance 摘要",
        ],
        "notes": [
            f"Target channel={target_channel} environment={target_environment}",
            "Deployment rehearsal 只生成 runbook，不执行真实部署。",
        ],
    }


def _build_rollback_rehearsal(
    target_channel: str,
    target_environment: str,
    release_candidate: Dict[str, Any],
    build_run_matrix: Dict[str, Any],
) -> Dict[str, Any]:
    release_summary = dict(release_candidate.get("release_summary") or {})
    restore_target = str(release_summary.get("versioned_release_url") or release_summary.get("release_dir") or "").strip()
    assets = [
        _artifact(
            "rollback_hint",
            "Rollback Hint",
            _release_candidate_item_status(release_candidate, "rollback_ready"),
            "",
            str(release_summary.get("rollback_hint") or "未声明 rollback_hint"),
            required=True,
            kind="rollback",
        ),
        _artifact(
            "restore_target",
            "Restore Target",
            "passed" if restore_target else "blocked",
            restore_target,
            f"release_url={release_summary.get('release_url') or '-'}",
            required=True,
            kind="artifact",
        ),
        _artifact(
            "release_manifest",
            "Release Manifest",
            _release_candidate_item_status(release_candidate, "release_manifest"),
            str(release_candidate.get("release_manifest_path") or ""),
            f"build_id={release_summary.get('build_id') or '-'}",
            required=True,
            kind="contract",
        ),
        _artifact(
            "release_notes",
            "Release Notes",
            _release_candidate_item_status(release_candidate, "release_notes"),
            str(release_candidate.get("release_notes_path") or ""),
            f"version={release_summary.get('version') or '-'}",
            required=False,
            kind="report",
        ),
        _artifact(
            "build_log",
            "Build Log",
            "passed" if str(release_candidate.get("build_log_path") or "").strip() else "warning",
            str(release_candidate.get("build_log_path") or ""),
            "保留失败构建和恢复构建的 build.log 便于审计",
            required=False,
            kind="log",
        ),
    ]
    verification_checks = [
        _check(
            "rollback_anchor",
            "Rollback Anchor",
            "passed" if str(release_summary.get("rollback_hint") or "").strip() else "blocked",
            str(release_summary.get("rollback_hint") or "未声明 rollback_hint"),
            required=True,
        ),
        _check(
            "restore_target",
            "Restore Target",
            "passed" if restore_target else "blocked",
            restore_target or "缺少 versioned release 或 release_dir",
            required=True,
        ),
        _check(
            "rollback_smoke_lanes",
            "Rollback Smoke Lanes",
            (
                "passed"
                if _find_matrix_row(build_run_matrix, "portal_dom_smoke") and _find_matrix_row(build_run_matrix, "portal_click_smoke")
                else "warning"
            ),
            "Rollback 后至少重跑 portal_dom_smoke 和 portal_click_smoke",
            required=False,
        ),
    ]
    blocked_checks = [item["check_id"] for item in verification_checks if item["status"] == "blocked"]
    warning_checks = [item["check_id"] for item in verification_checks if item["status"] == "warning"]
    return {
        "status": "blocked" if blocked_checks else ("warning" if warning_checks else "passed"),
        "should_block": bool(blocked_checks),
        "target_channel": target_channel,
        "target_environment": target_environment,
        "rollback_hint": str(release_summary.get("rollback_hint") or ""),
        "restore_target": restore_target,
        "assets": assets,
        "asset_count": len(assets),
        "verification_checks": verification_checks,
        "blocking_checks": blocked_checks,
        "warning_checks": warning_checks,
        "rehearsal_steps": [
            f"识别可恢复目标: {restore_target or 'missing'}",
            "在切换前保留当前 release manifest、release notes、build.log 和 QA gate report 快照",
            "按 rollback_hint 恢复 latest alias 或部署入口到上一个稳定版本",
            "回滚后最少重跑 portal_dom_smoke、portal_click_smoke，并复核关键 URL 和版本号",
            "记录 rollback 原因、执行人、时间和恢复后的验证结果",
        ],
        "notes": [
            f"Rollback rehearsal 针对 {target_channel} -> {target_environment} 目标生成。",
            "Rollback rehearsal 只生成操作 runbook，不执行真实回滚。",
        ],
    }


def _build_promotion_steps(
    target_channel: str,
    target_environment: str,
    required_signoffs: List[str],
    missing_signoffs: List[str],
    build_run_matrix: Dict[str, Any],
    release_candidate: Dict[str, Any],
) -> List[str]:
    steps = [
        f"确认 target channel/environment: {target_channel} -> {target_environment}",
        f"按默认顺序执行 matrix lanes: {', '.join(list(build_run_matrix.get('default_sequence') or [])) or 'none'}",
        f"确认 RC checklist 不再新增 blocker: {', '.join(list(release_candidate.get('blocking_checks') or [])) or 'none'}",
    ]
    if missing_signoffs:
        steps.append(f"补齐 signoff: {', '.join(missing_signoffs)}")
    else:
        steps.append(f"记录 signoff: {', '.join(required_signoffs)}")
    steps.append("保留当前 release manifest、release notes 和 rollback hint 作为 promotion evidence。")
    return steps


def _build_recommendations(
    checklist: List[Dict[str, Any]],
    build_run_matrix: Dict[str, Any],
    release_candidate: Dict[str, Any],
    scene_ownership_board: Dict[str, Any],
    evidence_bundle: Dict[str, Any],
    review_bundle: Dict[str, Any],
    deployment_rehearsal: Dict[str, Any],
    rollback_rehearsal: Dict[str, Any],
) -> List[str]:
    recommendations: List[str] = []
    blocked = {item["item_id"] for item in checklist if item["status"] == "blocked"}
    warning = {item["item_id"] for item in checklist if item["status"] == "warning"}
    if "release_live_runner_baseline_gate" in blocked or "release_live_runner_baseline_gate" in warning:
        recommendations.append("先补齐 release live runner baseline，再推进 promotion；不要在未验证 Godot / Chromium / PowerShell / live scripts 的 runner 上直接跑 release gate。")
    if "request_auth_posture_gate" in blocked or "request_auth_posture_gate" in warning:
        recommendations.append("先收紧 release_request_auth posture，再推进 promotion；不要让正式发布仍依赖 local bypass 或 env fallback。")
    if "request_auth_rotation_audit_gate" in blocked or "request_auth_rotation_audit_gate" in warning:
        recommendations.append("先补齐 request_auth rotation audit，再推进 promotion；不要让 promotion_record / release_execution 其中一条仍缺 token 覆盖或 rotation hygiene。")
    if "request_auth_identity_audit_gate" in blocked or "request_auth_identity_audit_gate" in warning:
        recommendations.append("先补齐 request_auth identity audit，再推进 promotion；不要让正式发布仍缺 scoped issuer、subject actor 绑定或 session policy。")
    if "release_distribution_bundle_gate" in blocked or "release_distribution_bundle_gate" in warning:
        recommendations.append("先导出 versioned distribution bundle，再推进 promotion；不要让安装/升级/卸载路径只停留在 release notes 或聊天记录。")
    if "signoff_gate" in blocked:
        recommendations.append("先补齐渠道 signoff，再推进 promotion；不要把签字确认散落在聊天记录里。")
    if "build_run_matrix_gate" in blocked:
        recommendations.append(f"先处理 matrix blocking rows: {', '.join(list(build_run_matrix.get('blocking_rows') or []))}.")
    if "release_candidate_gate" in blocked:
        recommendations.append(f"先清理 RC blockers: {', '.join(list(release_candidate.get('blocking_checks') or [])) or 'release_candidate_gate'}.")
    if "scene_collaboration_gate" in warning or "scene_collaboration_gate" in blocked:
        recommendations.append(
            f"补齐场景 owner/feature_id，当前 missing_owner={scene_ownership_board.get('missing_owner_count') or 0}。"
        )
    if "promotion_evidence_bundle" in blocked:
        recommendations.append(
            f"补齐 promotion evidence 缺失项: {', '.join(list(evidence_bundle.get('missing_artifacts') or [])) or 'promotion_evidence_bundle'}。"
        )
    if "review_bundle" in blocked or "review_bundle" in warning:
        recommendations.append(
            f"补齐 review bundle 结构化缺口: {', '.join(list(review_bundle.get('blocking_items') or review_bundle.get('warning_items') or [])) or 'review_bundle'}。"
        )
    if "deployment_rehearsal" in blocked or "deployment_rehearsal" in warning:
        recommendations.append(
            f"先走完 deployment rehearsal preflight: {', '.join(list(deployment_rehearsal.get('blocking_checks') or deployment_rehearsal.get('warning_checks') or [])) or 'deployment_rehearsal'}。"
        )
    if "rollback_rehearsal" in blocked or "rollback_rehearsal" in warning:
        recommendations.append(
            f"补齐 rollback rehearsal 资产或校验: {', '.join(list(rollback_rehearsal.get('blocking_checks') or rollback_rehearsal.get('warning_checks') or [])) or 'rollback_rehearsal'}。"
        )
    if "channel_alignment" in warning:
        recommendations.append("确认当前 build channel 与 promotion target 是否一致，避免直接把 QA build 当作 release build 晋级。")
    if not recommendations:
        recommendations.append("Promotion plan 已收敛到可执行状态，按默认 matrix 顺序完成 evidence 后即可推进。")
    return recommendations


def _release_candidate_item_status(release_candidate: Dict[str, Any], item_id: str) -> str:
    for item in list(release_candidate.get("checklist") or []):
        if str(item.get("item_id") or "").strip() == item_id:
            return str(item.get("status") or "skipped")
    return "skipped"


def _find_matrix_row(build_run_matrix: Dict[str, Any], row_id: str) -> Dict[str, Any]:
    for item in list(build_run_matrix.get("rows") or []):
        if str(item.get("row_id") or "").strip() == row_id:
            return dict(item)
    return {}


def _release_live_runner_baseline_gate_status(release_live_runner_baseline: Dict[str, Any], *, target_channel: str) -> str:
    normalized = str(release_live_runner_baseline.get("status") or "skipped").strip().lower() or "skipped"
    if target_channel == "release" and normalized != "passed":
        return "blocked"
    return normalized


def _release_live_runner_baseline_artifact_path(release_live_runner_baseline: Dict[str, Any]) -> str:
    if str(release_live_runner_baseline.get("path") or "").strip():
        return str(release_live_runner_baseline.get("path") or "").strip()
    return str(release_live_runner_baseline.get("details", {}).get("report_path") or "").strip()


def _release_live_ci_summary_gate_status(release_live_ci_summary: Dict[str, Any], *, target_channel: str) -> str:
    ci_gate = dict(release_live_ci_summary.get("details", {}).get("ci_gate") or {})
    normalized = str(ci_gate.get("status") or release_live_ci_summary.get("status") or "skipped").strip().lower() or "skipped"
    if bool(ci_gate.get("should_block")):
        return "blocked"
    if target_channel == "release" and not str(release_live_ci_summary.get("path") or "").strip():
        return "blocked"
    if target_channel == "release" and normalized not in {"passed", "skipped"}:
        return "blocked"
    return normalized


def _release_live_ci_summary_artifact_path(release_live_ci_summary: Dict[str, Any]) -> str:
    if str(release_live_ci_summary.get("path") or "").strip():
        return str(release_live_ci_summary.get("path") or "").strip()
    return str(release_live_ci_summary.get("details", {}).get("summary_markdown_path") or "").strip()


def _request_auth_posture_gate_status(request_auth_posture: Dict[str, Any], *, target_channel: str) -> str:
    normalized = str(request_auth_posture.get("status") or "skipped").strip().lower() or "skipped"
    if target_channel == "release" and normalized != "passed":
        return "blocked"
    return normalized


def _request_auth_posture_artifact_path(request_auth_posture: Dict[str, Any]) -> str:
    if bool(request_auth_posture.get("report_exists")) and str(request_auth_posture.get("report_path") or "").strip():
        return str(request_auth_posture.get("report_path") or "").strip()
    return str(
        request_auth_posture.get("manifest_path")
        or request_auth_posture.get("path")
        or ""
    ).strip()


def _request_auth_rotation_audit_gate_status(request_auth_rotation_audit: Dict[str, Any], *, target_channel: str) -> str:
    normalized = str(request_auth_rotation_audit.get("status") or "skipped").strip().lower() or "skipped"
    if target_channel == "release" and normalized != "passed":
        return "blocked"
    return normalized


def _request_auth_rotation_audit_artifact_path(request_auth_rotation_audit: Dict[str, Any]) -> str:
    if bool(request_auth_rotation_audit.get("report_exists")) and str(request_auth_rotation_audit.get("report_path") or "").strip():
        return str(request_auth_rotation_audit.get("report_path") or "").strip()
    return str(request_auth_rotation_audit.get("auth_path") or "").strip()


def _request_auth_identity_audit_gate_status(request_auth_identity_audit: Dict[str, Any], *, target_channel: str) -> str:
    normalized = str(request_auth_identity_audit.get("status") or "skipped").strip().lower() or "skipped"
    if target_channel == "release" and normalized != "passed":
        return "blocked"
    return normalized


def _request_auth_identity_audit_artifact_path(request_auth_identity_audit: Dict[str, Any]) -> str:
    if bool(request_auth_identity_audit.get("report_exists")) and str(request_auth_identity_audit.get("report_path") or "").strip():
        return str(request_auth_identity_audit.get("report_path") or "").strip()
    return str(
        request_auth_identity_audit.get("identity_path")
        or request_auth_identity_audit.get("auth_path")
        or ""
    ).strip()


def _release_distribution_bundle_gate_status(release_distribution_bundle: Dict[str, Any], *, target_channel: str) -> str:
    normalized = str(release_distribution_bundle.get("status") or "skipped").strip().lower() or "skipped"
    if normalized == "blocked":
        return "blocked"
    if target_channel == "release" and normalized != "passed":
        return "blocked"
    return normalized


def _release_distribution_bundle_artifact_path(release_distribution_bundle: Dict[str, Any]) -> str:
    if bool(release_distribution_bundle.get("report_exists")) and str(release_distribution_bundle.get("report_path") or "").strip():
        return str(release_distribution_bundle.get("report_path") or "").strip()
    return str(
        release_distribution_bundle.get("distribution_manifest_path")
        or release_distribution_bundle.get("bundle_dir")
        or ""
    ).strip()


def _release_distribution_publish_receipts_follow_up_required(release_distribution_bundle: Dict[str, Any]) -> bool:
    if list(release_distribution_bundle.get("publish_receipts_failed_targets") or []):
        return True
    if (
        bool(release_distribution_bundle.get("publish_receipts_manifest_exists"))
        and not bool(release_distribution_bundle.get("publish_receipts_manifest_matches_current"))
    ):
        return True
    return (
        int(release_distribution_bundle.get("publish_receipts_recorded_target_count") or 0) > 0
        and bool(list(release_distribution_bundle.get("publish_receipts_missing_targets") or []))
    )


def _release_distribution_publish_receipts_artifact_status(release_distribution_bundle: Dict[str, Any]) -> str:
    normalized = str(release_distribution_bundle.get("publish_receipts_status") or "skipped").strip().lower() or "skipped"
    if normalized == "passed":
        return "passed"
    if _release_distribution_publish_receipts_follow_up_required(release_distribution_bundle):
        return "warning"
    return "skipped"


def _release_distribution_publish_receipts_artifact_path(release_distribution_bundle: Dict[str, Any]) -> str:
    if (
        bool(release_distribution_bundle.get("publish_receipts_manifest_exists"))
        and str(release_distribution_bundle.get("publish_receipts_manifest_path") or "").strip()
    ):
        return str(release_distribution_bundle.get("publish_receipts_manifest_path") or "").strip()
    if bool(release_distribution_bundle.get("publish_receipts_exists")) and str(release_distribution_bundle.get("publish_receipts_dir") or "").strip():
        return str(release_distribution_bundle.get("publish_receipts_dir") or "").strip()
    return str(
        release_distribution_bundle.get("publish_receipts_manifest_path")
        or release_distribution_bundle.get("publish_receipts_dir")
        or ""
    ).strip()


def _build_release_distribution_publish_receipts_summary(release_distribution_bundle: Dict[str, Any]) -> str:
    status = _release_distribution_publish_receipts_artifact_status(release_distribution_bundle)
    summary = str(release_distribution_bundle.get("publish_receipts_summary") or "").strip()
    target_count = int(release_distribution_bundle.get("publish_receipts_target_count") or 0)
    recorded_count = int(release_distribution_bundle.get("publish_receipts_recorded_target_count") or 0)
    completed_targets = list(release_distribution_bundle.get("publish_receipts_completed_targets") or [])
    missing_targets = list(release_distribution_bundle.get("publish_receipts_missing_targets") or [])
    failed_targets = list(release_distribution_bundle.get("publish_receipts_failed_targets") or [])

    if status == "passed":
        return (
            summary
            or f"publish receipts ready / completed={len(completed_targets)}/{target_count}"
        )
    if status == "warning":
        parts = [
            summary or "publish receipts need follow-up",
            f"recorded={recorded_count}/{target_count}",
        ]
        if failed_targets:
            parts.append(f"failed={', '.join(failed_targets)}")
        if missing_targets:
            parts.append(f"missing={', '.join(missing_targets)}")
        return " / ".join(parts)
    return summary or "publish receipts not recorded yet"


def _release_distribution_publish_receipts_artifact_details(
    release_distribution_bundle: Dict[str, Any],
) -> Dict[str, Any]:
    return {
        "publish_receipts_status": str(release_distribution_bundle.get("publish_receipts_status") or "").strip(),
        "publish_receipts_summary": str(release_distribution_bundle.get("publish_receipts_summary") or "").strip(),
        "publish_receipts_dir": str(release_distribution_bundle.get("publish_receipts_dir") or "").strip(),
        "publish_receipts_exists": bool(release_distribution_bundle.get("publish_receipts_exists")),
        "publish_receipts_manifest_path": str(release_distribution_bundle.get("publish_receipts_manifest_path") or "").strip(),
        "publish_receipts_manifest_exists": bool(release_distribution_bundle.get("publish_receipts_manifest_exists")),
        "publish_receipts_manifest_matches_current": bool(release_distribution_bundle.get("publish_receipts_manifest_matches_current")),
        "publish_receipts_target_count": int(release_distribution_bundle.get("publish_receipts_target_count") or 0),
        "publish_receipts_recorded_target_count": int(release_distribution_bundle.get("publish_receipts_recorded_target_count") or 0),
        "publish_receipts_completed_targets": list(release_distribution_bundle.get("publish_receipts_completed_targets") or []),
        "publish_receipts_failed_targets": list(release_distribution_bundle.get("publish_receipts_failed_targets") or []),
        "publish_receipts_missing_targets": list(release_distribution_bundle.get("publish_receipts_missing_targets") or []),
    }

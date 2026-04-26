"""
Production-scale readiness checks.

P5 turns the project standardization work into executable scenario gates for
real project handoff: required file tree, quality dashboard, migrations,
template registry, and governance evidence are evaluated in one payload.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

from agent_system.contracts import (
    PRODUCTION_READINESS_SCHEMA_VERSION,
    PRODUCTION_SCENARIO_SCHEMA_VERSION,
)
from agent_system.migrations import MigrationRunner
from agent_system.tools.governance import build_governance_enforcement
from agent_system.tools.quality_dashboard import build_quality_dashboard
from agent_system.tools.template_registry import GenreTemplateRegistry


_PRODUCTION_SCENARIOS: List[Dict[str, Any]] = [
    {
        "scenario_id": "vertical_slice_2d",
        "label": "Vertical Slice 2D",
        "change_type": "feature",
        "description": "A playable 2D slice with scenes, scripts, data tables, asset manifests, and a performance baseline.",
        "required_evidence": ["contract", "tests", "docs", "quality_dashboard"],
        "required_project_paths": ["project.godot", "scenes", "scripts", "data_tables", "assets/manifests"],
        "required_runtime_paths": ["tests/baselines/performance"],
        "recommended_changed_paths": ["scenes/", "scripts/", "data_tables/", "assets/manifests/", "tests/"],
        "gate_focus": ["layout", "templates", "migrations", "quality_dashboard", "governance"],
    },
    {
        "scenario_id": "content_pipeline",
        "label": "Content Pipeline",
        "change_type": "template",
        "description": "A content production pass covering art intake, data tables, telemetry hooks, screenshots, and template governance.",
        "required_evidence": ["template_manifest", "template_validation", "migration_plan", "tests", "docs"],
        "required_project_paths": ["assets", "assets/manifests", "data_tables", "telemetry"],
        "required_runtime_paths": ["logs/test_artifacts", "tests/baselines/screenshots"],
        "recommended_changed_paths": ["assets/", "assets/manifests/", "data_tables/", "telemetry/", "tests/"],
        "gate_focus": ["asset_intake", "data_tables", "telemetry", "screenshots", "templates"],
    },
    {
        "scenario_id": "release_candidate",
        "label": "Release Candidate",
        "change_type": "release",
        "description": "A release handoff with build metadata, release notes, QA gate report, rollback anchor, and performance budget.",
        "required_evidence": ["feature_approval", "quality_gate", "release_manifest", "rollback", "tests", "docs"],
        "required_project_paths": ["project.godot", "scenes", "scripts"],
        "required_runtime_paths": [
            "api_server/static/dist",
            "api_server/static/dist/release_manifest.json",
            "api_server/static/dist/release_notes.md",
            "api_server/static/dist/qa_gate_report.md",
            "tests/baselines/performance",
        ],
        "recommended_changed_paths": ["api_server/static/dist/", "tests/baselines/performance/", "docs/", "README.md"],
        "gate_focus": ["release_manifest", "qa_gate", "rollback", "performance_budget", "governance"],
    },
]


def list_production_scenarios() -> Dict[str, Any]:
    return {
        "schema_version": PRODUCTION_SCENARIO_SCHEMA_VERSION,
        "default_scenario_id": "vertical_slice_2d",
        "items": [_copy_scenario(item) for item in _PRODUCTION_SCENARIOS],
        "scenario_count": len(_PRODUCTION_SCENARIOS),
    }


def build_production_readiness(
    project_root: str | Path,
    runtime_root: Optional[str | Path] = None,
    *,
    scenario_id: str = "vertical_slice_2d",
    evidence: Optional[Dict[str, Any]] = None,
    changed_paths: Optional[List[str]] = None,
    notes: str = "",
    mode: str = "strict",
    fail_on_warnings: bool = False,
) -> Dict[str, Any]:
    resolved_project_root = Path(project_root).resolve()
    resolved_runtime_root = Path(runtime_root or Path.cwd()).resolve()
    normalized_mode = _normalize_mode(mode)
    requested_scenario_id = str(scenario_id or "").strip() or "vertical_slice_2d"
    scenario = _find_scenario(requested_scenario_id)

    stages: List[Dict[str, Any]] = []
    if scenario is None:
        stages.append(_stage(
            "scenario",
            "Scenario",
            "blocked",
            f"Unknown production scenario: {requested_scenario_id}",
            issues=[{
                "code": "unknown_production_scenario",
                "scenario_id": requested_scenario_id,
                "message": "Requested scenario is not registered in the production scenario catalog",
            }],
            details={"supported_scenarios": [item["scenario_id"] for item in _PRODUCTION_SCENARIOS]},
        ))
    else:
        stages.append(_stage(
            "scenario",
            "Scenario",
            "passed",
            f"{scenario['label']} scenario selected",
            details={"scenario": _copy_scenario(scenario)},
        ))
        stages.append(_check_required_paths(scenario, resolved_project_root, resolved_runtime_root))
        stages.append(_check_templates(resolved_project_root))
        stages.append(_check_quality_dashboard(resolved_project_root, resolved_runtime_root))
        stages.append(_check_migrations(resolved_project_root, resolved_runtime_root))
        stages.append(_check_governance(
            scenario,
            resolved_project_root,
            resolved_runtime_root,
            evidence=evidence,
            changed_paths=changed_paths,
            notes=notes,
        ))

    blocked_stage_names = [stage["name"] for stage in stages if stage["status"] == "blocked"]
    warning_stage_names = [stage["name"] for stage in stages if stage["status"] == "warning"]
    blocking_checks = list(blocked_stage_names)
    if fail_on_warnings:
        blocking_checks.extend(stage for stage in warning_stage_names if stage not in blocking_checks)

    should_block = normalized_mode == "strict" and bool(blocking_checks)
    readiness_status = "blocked" if blocked_stage_names else ("warning" if warning_stage_names else "passed")
    return {
        "schema_version": PRODUCTION_READINESS_SCHEMA_VERSION,
        "contract_versions": {
            "production_scenarios": PRODUCTION_SCENARIO_SCHEMA_VERSION,
            "production_readiness": PRODUCTION_READINESS_SCHEMA_VERSION,
        },
        "project_root": str(resolved_project_root),
        "runtime_root": str(resolved_runtime_root),
        "scenario_id": requested_scenario_id,
        "scenario": _copy_scenario(scenario) if scenario else None,
        "mode": normalized_mode,
        "fail_on_warnings": bool(fail_on_warnings),
        "passed": not should_block,
        "readiness_status": readiness_status,
        "should_block": should_block,
        "exit_code": 1 if should_block else 0,
        "message": _build_message(normalized_mode, should_block, blocking_checks, readiness_status),
        "stage_count": len(stages),
        "blocked_count": len(blocked_stage_names),
        "warning_count": len(warning_stage_names),
        "blocking_checks": blocking_checks,
        "warning_checks": warning_stage_names,
        "stages": stages,
        "recommendations": _build_recommendations(stages, scenario),
    }


def _copy_scenario(scenario: Dict[str, Any]) -> Dict[str, Any]:
    return {
        **scenario,
        "schema_version": PRODUCTION_SCENARIO_SCHEMA_VERSION,
        "required_evidence": list(scenario.get("required_evidence") or []),
        "required_project_paths": list(scenario.get("required_project_paths") or []),
        "required_runtime_paths": list(scenario.get("required_runtime_paths") or []),
        "recommended_changed_paths": list(scenario.get("recommended_changed_paths") or []),
        "gate_focus": list(scenario.get("gate_focus") or []),
    }


def _find_scenario(scenario_id: str) -> Optional[Dict[str, Any]]:
    normalized = str(scenario_id or "").strip()
    for scenario in _PRODUCTION_SCENARIOS:
        if scenario["scenario_id"] == normalized:
            return scenario
    return None


def _normalize_mode(value: str) -> str:
    normalized = str(value or "strict").strip().lower()
    return normalized if normalized in {"strict", "advisory"} else "strict"


def _check_required_paths(scenario: Dict[str, Any], project_root: Path, runtime_root: Path) -> Dict[str, Any]:
    missing: List[Dict[str, Any]] = []
    present: List[Dict[str, str]] = []

    for relative in list(scenario.get("required_project_paths") or []):
        target = (project_root / relative).resolve()
        record = {"scope": "project", "path": relative, "absolute_path": str(target)}
        if target.exists():
            present.append(record)
        else:
            missing.append({
                **record,
                "code": "missing_project_path",
                "message": f"Required project path is missing: {relative}",
            })

    for relative in list(scenario.get("required_runtime_paths") or []):
        target = (runtime_root / relative).resolve()
        record = {"scope": "runtime", "path": relative, "absolute_path": str(target)}
        if target.exists():
            present.append(record)
        else:
            missing.append({
                **record,
                "code": "missing_runtime_path",
                "message": f"Required runtime path is missing: {relative}",
            })

    return _stage(
        "required_paths",
        "Required File Tree",
        "blocked" if missing else "passed",
        f"{len(present)}/{len(present) + len(missing)} required paths present",
        issues=missing,
        details={
            "present_paths": present,
            "missing_paths": missing,
            "required_project_paths": list(scenario.get("required_project_paths") or []),
            "required_runtime_paths": list(scenario.get("required_runtime_paths") or []),
        },
    )


def _check_templates(project_root: Path) -> Dict[str, Any]:
    marketplace = GenreTemplateRegistry(project_path=str(project_root)).build_marketplace_manifest()
    validation = dict(marketplace.get("validation") or {})
    issues = list(validation.get("issues") or [])
    warnings = list(validation.get("warnings") or [])
    project_template_count = len([
        item for item in list(marketplace.get("items") or [])
        if item.get("source_scope") == "project"
    ])
    if not project_template_count:
        warnings.append({
            "code": "no_project_template_override",
            "message": "Project has no local genre template override yet",
        })
    status = "blocked" if issues else ("warning" if warnings else "passed")
    return _stage(
        "templates",
        "Template Registry",
        status,
        f"{marketplace.get('count', 0)} templates registered",
        issues=issues,
        warnings=warnings,
        details={
            "template_count": marketplace.get("count", 0),
            "project_template_count": project_template_count,
            "default_template_id": marketplace.get("default_template_id"),
        },
    )


def _check_quality_dashboard(project_root: Path, runtime_root: Path) -> Dict[str, Any]:
    dashboard = build_quality_dashboard(project_root, runtime_root=runtime_root)
    warnings = [
        {"code": "quality_warning", "section": section["name"], "message": section["summary"]}
        for section in dashboard.get("sections") or []
        if section.get("status") in {"warning", "skipped"}
    ]
    issues = [
        {"code": "quality_blocked", "section": section["name"], "message": section["summary"]}
        for section in dashboard.get("sections") or []
        if section.get("status") == "blocked"
    ]
    status = "blocked" if issues else ("warning" if warnings else "passed")
    return _stage(
        "quality_dashboard",
        "Quality Dashboard",
        status,
        f"{dashboard.get('section_count', 0)} quality sections evaluated",
        issues=issues,
        warnings=warnings,
        details={
            "status": dashboard.get("status"),
            "blocked_count": dashboard.get("blocked_count", 0),
            "warning_count": dashboard.get("warning_count", 0),
            "skipped_count": dashboard.get("skipped_count", 0),
        },
    )


def _check_migrations(project_root: Path, runtime_root: Path) -> Dict[str, Any]:
    migration_status = MigrationRunner(project_root, runtime_root=runtime_root).build_migration_status()
    if migration_status["failed_count"]:
        status = "blocked"
    elif migration_status["pending_count"]:
        status = "warning"
    else:
        status = "passed"
    return _stage(
        "migrations",
        "Migration Compatibility",
        status,
        f"{migration_status['applied_count']}/{migration_status['migration_count']} migrations applied",
        issues=list(migration_status.get("issues") or []),
        warnings=list(migration_status.get("warnings") or []),
        details={key: migration_status[key] for key in ("migration_count", "applied_count", "pending_count", "failed_count")},
    )


def _check_governance(
    scenario: Dict[str, Any],
    project_root: Path,
    runtime_root: Path,
    *,
    evidence: Optional[Dict[str, Any]],
    changed_paths: Optional[List[str]],
    notes: str,
) -> Dict[str, Any]:
    enforcement = build_governance_enforcement(
        project_root,
        runtime_root=runtime_root,
        change_type=str(scenario.get("change_type") or "feature"),
        evidence=dict(evidence or {}),
        changed_paths=list(changed_paths or []),
        notes=notes,
        mode="strict",
        fail_on_warnings=False,
    )
    admission = dict(enforcement.get("admission") or {})
    issues: List[Dict[str, Any]] = []
    warnings: List[Dict[str, Any]] = []
    for check in list(admission.get("checks") or []):
        if check.get("status") == "blocked":
            issues.extend({**item, "check": check.get("name")} for item in list(check.get("issues") or []))
        elif check.get("status") == "warning":
            warnings.extend({**item, "check": check.get("name")} for item in list(check.get("warnings") or []))
    status = "blocked" if admission.get("blocked_checks") else ("warning" if admission.get("warning_checks") else "passed")
    return _stage(
        "governance",
        "Governance Admission",
        status,
        str(enforcement.get("message") or "Governance evaluated"),
        issues=issues,
        warnings=warnings,
        details={
            "change_type": admission.get("change_type"),
            "required_evidence": admission.get("required_evidence", []),
            "provided_evidence": admission.get("provided_evidence", []),
            "missing_evidence": admission.get("missing_evidence", []),
            "blocked_checks": admission.get("blocked_checks", []),
            "warning_checks": admission.get("warning_checks", []),
            "recommended_changed_paths": list(scenario.get("recommended_changed_paths") or []),
        },
    )


def _stage(
    name: str,
    label: str,
    status: str,
    summary: str,
    *,
    issues: Optional[List[Dict[str, Any]]] = None,
    warnings: Optional[List[Dict[str, Any]]] = None,
    details: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    return {
        "schema_version": PRODUCTION_READINESS_SCHEMA_VERSION,
        "name": name,
        "label": label,
        "status": status,
        "passed": status != "blocked",
        "summary": summary,
        "issue_count": len(issues or []),
        "warning_count": len(warnings or []),
        "issues": list(issues or []),
        "warnings": list(warnings or []),
        "details": dict(details or {}),
    }


def _build_message(mode: str, should_block: bool, blocking_checks: List[str], readiness_status: str) -> str:
    if mode == "advisory":
        return f"Production readiness advisory: {readiness_status}"
    if should_block:
        return f"Production readiness blocked: {', '.join(blocking_checks)}"
    return f"Production readiness passed with status: {readiness_status}"


def _build_recommendations(stages: List[Dict[str, Any]], scenario: Optional[Dict[str, Any]]) -> List[str]:
    recommendations: List[str] = []
    for stage in stages:
        if stage["status"] == "passed":
            continue
        if stage["name"] == "required_paths":
            missing_paths = [item["path"] for item in stage.get("details", {}).get("missing_paths", [])]
            if missing_paths:
                recommendations.append(f"Create or migrate required paths: {', '.join(missing_paths[:8])}")
        elif stage["name"] == "governance":
            missing_evidence = stage.get("details", {}).get("missing_evidence") or []
            if missing_evidence:
                recommendations.append(f"Declare missing governance evidence: {', '.join(missing_evidence)}")
            changed_paths = stage.get("details", {}).get("recommended_changed_paths") or []
            if changed_paths:
                recommendations.append(f"Use governed changed paths: {', '.join(changed_paths)}")
        else:
            recommendations.append(f"Review {stage['label']}: {stage['summary']}")
    if scenario:
        recommendations.append(f"Scenario focus: {', '.join(scenario.get('gate_focus') or [])}")
    return recommendations[:8]

"""
Unified project quality dashboard.

This module collects contract health, managed layout health, template status,
skill coverage, telemetry health, performance baseline health, and migration
compatibility into one stable payload for API, Portal, and MCP consumers.
"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List, Optional

from agent_system.contracts import build_contract_catalog
from agent_system.migrations import MigrationRunner
from agent_system.skills.registry import SkillRegistry
from agent_system.tools.performance_analysis import DEFAULT_PERFORMANCE_BASELINE_DIR, GamePerformanceAnalyzer
from agent_system.tools.telemetry_analysis import TelemetryAnalyzer
from agent_system.tools.template_registry import GenreTemplateRegistry
from agent_system.validations import ProjectLayoutValidator


QUALITY_DASHBOARD_SCHEMA_VERSION = "1.0"


def build_quality_dashboard(project_root: str | Path, runtime_root: Optional[str | Path] = None) -> Dict[str, Any]:
    resolved_project_root = Path(project_root).resolve()
    resolved_runtime_root = Path(runtime_root or Path.cwd()).resolve()
    sections = [
        _build_contract_section(),
        _build_layout_section(resolved_project_root, resolved_runtime_root),
        _build_template_section(resolved_project_root),
        _build_skill_coverage_section(),
        _build_telemetry_section(resolved_project_root),
        _build_performance_section(resolved_project_root, resolved_runtime_root),
        _build_migration_section(resolved_project_root, resolved_runtime_root),
    ]
    blocked = [section for section in sections if section["status"] == "blocked"]
    warnings = [section for section in sections if section["status"] == "warning"]
    skipped = [section for section in sections if section["status"] == "skipped"]
    return {
        "schema_version": QUALITY_DASHBOARD_SCHEMA_VERSION,
        "project_root": str(resolved_project_root),
        "runtime_root": str(resolved_runtime_root),
        "passed": not blocked,
        "status": "blocked" if blocked else ("warning" if warnings else "passed"),
        "section_count": len(sections),
        "blocked_count": len(blocked),
        "warning_count": len(warnings),
        "skipped_count": len(skipped),
        "sections": sections,
    }


def _section(
    name: str,
    label: str,
    status: str,
    summary: str,
    *,
    metrics: Optional[Dict[str, Any]] = None,
    issues: Optional[List[Any]] = None,
    warnings: Optional[List[Any]] = None,
    details: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    return {
        "schema_version": QUALITY_DASHBOARD_SCHEMA_VERSION,
        "name": name,
        "label": label,
        "status": status,
        "passed": status not in {"blocked"},
        "summary": summary,
        "metrics": dict(metrics or {}),
        "issue_count": len(issues or []),
        "warning_count": len(warnings or []),
        "issues": list(issues or []),
        "warnings": list(warnings or []),
        "details": dict(details or {}),
    }


def _build_contract_section() -> Dict[str, Any]:
    catalog = build_contract_catalog()
    contracts = list(catalog.get("contracts") or [])
    issues = [
        {"code": "missing_current_version", "contract_name": item.get("contract_name")}
        for item in contracts
        if not item.get("current_version")
    ]
    status = "blocked" if issues else "passed"
    return _section(
        "contracts",
        "Contract Health",
        status,
        f"{len(contracts)} contracts registered",
        metrics={"contract_count": len(contracts), "migration_entrypoint_count": len(catalog.get("migration_entrypoints") or [])},
        issues=issues,
        details={"contracts": contracts},
    )


def _build_layout_section(project_root: Path, runtime_root: Path) -> Dict[str, Any]:
    audit = ProjectLayoutValidator(project_root=project_root, runtime_root=runtime_root).audit_managed_layout()
    status = "passed" if audit["passed"] else "blocked"
    return _section(
        "project_layout",
        "Managed Layout",
        status,
        f"{audit['scanned_file_count']} managed files scanned",
        metrics={
            "scanned_file_count": audit["scanned_file_count"],
            "issue_count": audit["issue_count"],
        },
        issues=list(audit.get("issues") or []),
        details={"audit": audit},
    )


def _build_template_section(project_root: Path) -> Dict[str, Any]:
    marketplace = GenreTemplateRegistry(project_path=str(project_root)).build_marketplace_manifest()
    validation = marketplace.get("validation", {})
    issues = list(validation.get("issues") or [])
    warnings = list(validation.get("warnings") or [])
    project_template_count = len([
        item for item in marketplace.get("items") or []
        if item.get("source_scope") == "project"
    ])
    if issues:
        status = "blocked"
    elif project_template_count == 0:
        status = "warning"
        warnings.append({
            "code": "no_project_template_overrides",
            "message": "Only built-in genre templates are installed for this project",
        })
    else:
        status = "passed"

    return _section(
        "templates",
        "Template Marketplace",
        status,
        f"{marketplace.get('count', 0)} genre templates available",
        metrics={
            "template_count": marketplace.get("count", 0),
            "project_template_count": project_template_count,
            "default_template_id": marketplace.get("default_template_id"),
        },
        issues=issues,
        warnings=warnings,
        details={"marketplace": marketplace},
    )


def _build_skill_coverage_section() -> Dict[str, Any]:
    skills = SkillRegistry.list_skills()
    category_counts = Counter(str(skill.get("category") or "uncategorized") for skill in skills)
    issues = [
        {
            "code": "incomplete_skill_metadata",
            "skill_name": skill.get("name"),
            "message": "Skill metadata must include name, description and category",
        }
        for skill in skills
        if not skill.get("name") or not skill.get("description") or not skill.get("category")
    ]
    status = "blocked" if issues else "passed"
    return _section(
        "skill_coverage",
        "Skill Coverage",
        status,
        f"{len(skills)} registered skills across {len(category_counts)} categories",
        metrics={
            "skill_count": len(skills),
            "category_count": len(category_counts),
            "category_counts": dict(sorted(category_counts.items())),
        },
        issues=issues,
        details={"skills": skills},
    )


def _build_telemetry_section(project_root: Path) -> Dict[str, Any]:
    analyzer = TelemetryAnalyzer(project_root)
    if not analyzer.detect_present_telemetry():
        return _section(
            "telemetry",
            "Telemetry Health",
            "skipped",
            "Telemetry catalog and session logs are not initialized yet",
            metrics={"present": False},
        )

    try:
        summary = analyzer.analyze()
    except Exception as exc:
        return _section(
            "telemetry",
            "Telemetry Health",
            "blocked",
            "Telemetry artifacts could not be parsed",
            issues=[{"code": "telemetry_parse_failed", "message": str(exc)}],
        )

    status = "passed" if summary["passed"] else "blocked"
    crash_dashboard = dict(summary.get("crash_regression_dashboard") or {})
    retention_dashboard = dict(summary.get("retention_funnel_dashboard") or {})
    trend_dashboard = dict(summary.get("retention_funnel_trend_dashboard") or {})
    liveops_dashboard = dict(summary.get("liveops_impact_dashboard") or {})
    return _section(
        "telemetry",
        "Telemetry Health",
        status,
        (
            f"{summary.get('catalog_entry_count', 0)} catalog events / {summary.get('event_count', 0)} session events"
            + (
                f" / builds {crash_dashboard.get('affected_build_count', 0)} / scenes {crash_dashboard.get('affected_scene_count', 0)}"
                if crash_dashboard
                else ""
            )
            + (
                f" / top dropoff {retention_dashboard.get('largest_dropoff_step') or '-'}"
                if retention_dashboard
                else ""
            )
            + (
                f" / trend days {trend_dashboard.get('day_count', 0)}"
                if trend_dashboard
                else ""
            )
        ),
        metrics={
            "catalog_entry_count": summary.get("catalog_entry_count", 0),
            "session_count": summary.get("session_count", 0),
            "event_count": summary.get("event_count", 0),
            "crash_count": summary.get("crash_count", 0),
            "crash_cluster_count": len(summary.get("crash_clusters", [])),
            "affected_build_count": crash_dashboard.get("affected_build_count", 0),
            "affected_scene_count": crash_dashboard.get("affected_scene_count", 0),
            "uncataloged_event_count": summary.get("uncataloged_event_count", 0),
            "pii_violation_count": summary.get("pii_violation_count", 0),
            "privacy_gate_passed": summary.get("privacy_gate_passed", True),
            "retention_user_count": summary.get("retention_user_count", 0),
            "funnel_completion_rate": summary.get("funnel_completion_rate", 0),
            "d1_retention_rate": next((item.get("retention_rate") for item in summary.get("retention_cohorts", []) if item.get("window") == "d1"), 0),
            "d7_retention_rate": next((item.get("retention_rate") for item in summary.get("retention_cohorts", []) if item.get("window") == "d7"), 0),
            "largest_dropoff_step": retention_dashboard.get("largest_dropoff_step", ""),
            "largest_dropoff_rate": retention_dashboard.get("largest_dropoff_rate", 0),
            "lowest_retention_window": retention_dashboard.get("lowest_retention_window", ""),
            "lowest_retention_rate": retention_dashboard.get("lowest_retention_rate", 0),
            "trend_day_count": trend_dashboard.get("day_count", 0),
            "trend_top_build_id": trend_dashboard.get("top_build_id", ""),
            "liveops_running_experiment_count": liveops_dashboard.get("running_experiment_count", 0),
            "liveops_matched_metric_count": liveops_dashboard.get("matched_metric_count", 0),
        },
        issues=list(summary.get("issues") or []),
        warnings=list(summary.get("warnings") or []),
        details={"summary": summary},
    )


def _build_performance_section(project_root: Path, runtime_root: Path) -> Dict[str, Any]:
    baseline_dir = (runtime_root / DEFAULT_PERFORMANCE_BASELINE_DIR).resolve()
    if not baseline_dir.exists():
        return _section(
            "performance",
            "Performance Budgets",
            "skipped",
            "Performance baseline directory is not initialized yet",
            metrics={"baseline_count": 0},
        )

    analyzer = GamePerformanceAnalyzer(project_root, runtime_root=runtime_root)
    summaries: List[Dict[str, Any]] = []
    issues: List[Dict[str, Any]] = []
    warnings: List[Dict[str, Any]] = []

    baseline_files = sorted(path for path in baseline_dir.glob("*.json") if path.is_file())
    for path in baseline_files:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:
            issues.append({"code": "invalid_performance_baseline", "path": str(path), "message": str(exc)})
            continue
        metrics = dict(payload.get("metrics") or {}) if isinstance(payload, dict) else {}
        budgets = dict(payload.get("budgets") or {}) if isinstance(payload, dict) else {}
        if not metrics:
            issues.append({"code": "missing_performance_metrics", "path": str(path), "message": "Baseline has no metrics"})
            continue
        summary = analyzer.analyze(
            scene_path=payload.get("scene_path") if isinstance(payload, dict) else "",
            baseline_path=str(path),
            baseline_metrics=metrics,
            profile_metrics={
                **metrics,
                "frame_breakdown": list(payload.get("frame_breakdown") or []),
                "memory_trend": dict(payload.get("memory_trend") or {}),
            },
            budget_overrides=budgets,
        )
        summaries.append(summary)
        if not summary["passed"]:
            issues.append({
                "code": "performance_budget_failed",
                "path": str(path),
                "message": "; ".join(summary.get("issues") or ["Performance budget failed"]),
            })
        warnings.extend({"code": "performance_warning", "path": str(path), "message": item} for item in summary.get("warnings") or [])

    passed_count = sum(1 for summary in summaries if summary.get("passed"))
    budget_pass_rate = (passed_count / len(summaries)) if summaries else None
    top_frame_stage = next(
        (str(summary.get("metrics", {}).get("top_frame_stage") or "") for summary in summaries if summary.get("metrics", {}).get("top_frame_stage")),
        "",
    )
    max_memory_growth_mb = max(
        (float(summary.get("memory_trend", {}).get("growth_mb") or 0.0) for summary in summaries),
        default=0.0,
    )
    status = "blocked" if issues else ("skipped" if not baseline_files else "passed")
    return _section(
        "performance",
        "Performance Budgets",
        status,
        f"{len(baseline_files)} performance baselines inspected",
        metrics={
            "baseline_count": len(baseline_files),
            "analyzed_count": len(summaries),
            "budget_pass_rate": budget_pass_rate,
            "top_frame_stage": top_frame_stage,
            "max_memory_growth_mb": round(max_memory_growth_mb, 4),
        },
        issues=issues,
        warnings=warnings,
        details={"summaries": summaries},
    )


def _build_migration_section(project_root: Path, runtime_root: Path) -> Dict[str, Any]:
    status_payload = MigrationRunner(project_root, runtime_root=runtime_root).build_migration_status()
    if status_payload["failed_count"]:
        status = "blocked"
    elif status_payload["pending_count"]:
        status = "warning"
    else:
        status = "passed"
    return _section(
        "migrations",
        "Migration Compatibility",
        status,
        f"{status_payload['applied_count']}/{status_payload['migration_count']} migrations applied",
        metrics={
            "migration_count": status_payload["migration_count"],
            "applied_count": status_payload["applied_count"],
            "pending_count": status_payload["pending_count"],
            "failed_count": status_payload["failed_count"],
        },
        issues=list(status_payload.get("issues") or []),
        warnings=list(status_payload.get("warnings") or []),
        details={"migration_status": status_payload},
    )

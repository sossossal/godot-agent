"""
Project governance and change admission checks.

P3 turns the standardization roadmap into a machine-readable admission gate:
every material change must declare evidence such as contracts, tests, docs,
layout strategy, migration plan, quality gate, or security notes.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

from agent_system.contracts import (
    CHANGE_ADMISSION_SCHEMA_VERSION,
    GOVERNANCE_ENFORCEMENT_SCHEMA_VERSION,
    GOVERNANCE_POLICY_SCHEMA_VERSION,
)
from agent_system.migrations import MigrationRunner
from agent_system.tools.quality_dashboard import build_quality_dashboard
from agent_system.validations import ProjectLayoutValidator


_EVIDENCE_CATALOG: Dict[str, str] = {
    "api_contract": "API response/request shape or stable backend contract is updated.",
    "baseline": "A baseline artifact exists or the update strategy is documented.",
    "budget_source": "Budget thresholds and their source are documented.",
    "contract": "Task.context, API payload, artifact metadata, or schema version is explicit.",
    "docs": "README or focused docs describe the changed behavior.",
    "event_catalog": "Telemetry event names, fields, and required properties are registered.",
    "feature_approval": "Release/QA feature status is approved or explicitly handled.",
    "layout": "Managed output paths are validated before writes.",
    "migration_plan": "Compatibility behavior for existing projects is documented or implemented.",
    "preview_or_diff": "Write flows provide preview, validation, or diff before applying changes.",
    "privacy_review": "Telemetry privacy level and sensitive fields are reviewed.",
    "quality_dashboard": "The unified quality dashboard has no blocked sections.",
    "quality_gate": "A release, skill, or module quality gate is attached.",
    "regression_threshold": "Regression thresholds are defined for budgeted metrics.",
    "release_manifest": "Release metadata, manifest, or rollback anchor is generated.",
    "rollback": "Rollback strategy or explicit no-write strategy is documented.",
    "schema": "Data or content schema is defined with required fields and defaults.",
    "security_notes": "Remote access, auth, localhost binding, or gateway constraints are documented.",
    "template_manifest": "Template manifest includes version, directories, data tables, and budgets.",
    "template_validation": "Template manifest is validated by the registry.",
    "tests": "Targeted regression tests cover the change.",
    "tool_schema": "Tool input schema and response shape are stable for MCP/API callers.",
    "ui_wiring": "Portal/UI caller is wired to the backing API rather than local-only state.",
}


_CHANGE_TYPES: Dict[str, Dict[str, Any]] = {
    "feature": {
        "label": "Feature / Module",
        "required_evidence": ["contract", "tests", "docs", "quality_dashboard"],
        "recommended_paths": ["agent_system/", "api_server/", "tests/", "docs/", "README.md"],
    },
    "game_creation": {
        "label": "Zero-to-Playable Game Creation",
        "required_evidence": ["contract", "layout", "schema", "preview_or_diff", "quality_gate", "rollback", "tests", "docs"],
        "recommended_paths": ["project.godot", "scenes/", "scripts/", "data_tables/game_creation/", "docs/"],
    },
    "skill": {
        "label": "Skill",
        "required_evidence": ["contract", "layout", "tests", "docs", "rollback", "quality_gate"],
        "recommended_paths": ["agent_system/skills/", "agent_system/contracts/", "tests/", "docs/", "README.md"],
    },
    "template": {
        "label": "Genre Template",
        "required_evidence": ["template_manifest", "template_validation", "migration_plan", "tests", "docs"],
        "recommended_paths": ["agent_system/templates/genres/", "agent_templates/genres/", "tests/", "docs/", "README.md"],
    },
    "data_table": {
        "label": "Data Table",
        "required_evidence": ["schema", "preview_or_diff", "layout", "migration_plan", "tests", "docs"],
        "recommended_paths": ["data_tables/", "agent_system/skills/resource/", "tests/", "docs/", "README.md"],
    },
    "telemetry": {
        "label": "Telemetry",
        "required_evidence": ["event_catalog", "privacy_review", "schema", "tests", "docs"],
        "recommended_paths": ["telemetry/", "agent_system/tools/telemetry_analysis.py", "tests/", "docs/", "README.md"],
    },
    "performance": {
        "label": "Performance",
        "required_evidence": ["budget_source", "baseline", "regression_threshold", "quality_gate", "tests", "docs"],
        "recommended_paths": ["tests/baselines/performance/", "agent_system/tools/performance_analysis.py", "tests/", "docs/", "README.md"],
    },
    "release": {
        "label": "Release",
        "required_evidence": ["feature_approval", "quality_gate", "release_manifest", "rollback", "tests", "docs"],
        "recommended_paths": ["agent_system/skills/resource/export_skill.py", "api_server/static/dist/", "tests/", "docs/", "README.md"],
    },
    "mcp_bridge": {
        "label": "MCP / IDE Bridge",
        "required_evidence": ["tool_schema", "security_notes", "tests", "docs"],
        "recommended_paths": ["bridge/", "api_server/", "ide_integration/", "tests/", "docs/", "README.md"],
    },
    "portal": {
        "label": "Portal UI",
        "required_evidence": ["api_contract", "ui_wiring", "tests", "docs"],
        "recommended_paths": ["api_server/static/", "api_server/main.py", "tests/", "docs/", "README.md"],
    },
}


_ALLOWED_PATH_PREFIXES = {
    ".codex/skills/",
    ".github/workflows/",
    "addons/godot_agent/",
    "agent_modules/scenes/",
    "agent_modules/scripts/",
    "agent_system/",
    "agent_templates/genres/",
    "api_server/",
    "assets/",
    "bridge/",
    "data_tables/",
    "docs/",
    "godot_plugin/",
    "ide_integration/",
    "logs/reports/",
    "logs/test_artifacts/",
    "logs/visual_feedback/",
    "scenes/",
    "scripts/",
    "telemetry/",
    "tests/",
    "tools/",
}
_ALLOWED_ROOT_FILES = {
    ".gitignore",
    "README.md",
    "config.yaml",
    "project.godot",
    "pytest.ini",
    "requirements.txt",
}


def build_governance_policy() -> Dict[str, Any]:
    return {
        "schema_version": GOVERNANCE_POLICY_SCHEMA_VERSION,
        "default_change_type": "feature",
        "change_types": [
            {
                "change_type": change_type,
                "label": str(config["label"]),
                "required_evidence": list(config["required_evidence"]),
                "recommended_paths": list(config["recommended_paths"]),
            }
            for change_type, config in sorted(_CHANGE_TYPES.items())
        ],
        "evidence_catalog": [
            {"name": name, "description": description}
            for name, description in sorted(_EVIDENCE_CATALOG.items())
        ],
        "path_policy": {
            "allowed_prefixes": sorted(_ALLOWED_PATH_PREFIXES),
            "allowed_root_files": sorted(_ALLOWED_ROOT_FILES),
        },
    }


def build_change_admission(
    project_root: str | Path,
    runtime_root: Optional[str | Path] = None,
    *,
    change_type: str = "feature",
    evidence: Optional[Dict[str, Any]] = None,
    changed_paths: Optional[List[str]] = None,
    notes: str = "",
) -> Dict[str, Any]:
    resolved_project_root = Path(project_root).resolve()
    resolved_runtime_root = Path(runtime_root or Path.cwd()).resolve()
    normalized_type = _normalize_change_type(change_type)
    evidence_map = _normalize_evidence(evidence)
    paths = _normalize_changed_paths(changed_paths)

    checks: List[Dict[str, Any]] = []
    checks.append(_check_change_type(normalized_type))
    checks.append(_check_required_evidence(normalized_type, evidence_map))
    checks.append(_check_changed_paths(resolved_project_root, resolved_runtime_root, paths))
    checks.append(_check_quality_dashboard(resolved_project_root, resolved_runtime_root))
    checks.append(_check_migrations(resolved_project_root, resolved_runtime_root))

    blocked_checks = [check["name"] for check in checks if check["status"] == "blocked"]
    warning_checks = [check["name"] for check in checks if check["status"] == "warning"]
    config = _CHANGE_TYPES.get(normalized_type, _CHANGE_TYPES["feature"])
    missing_evidence = list(checks[1]["details"].get("missing_evidence") or [])
    return {
        "schema_version": CHANGE_ADMISSION_SCHEMA_VERSION,
        "project_root": str(resolved_project_root),
        "runtime_root": str(resolved_runtime_root),
        "change_type": normalized_type,
        "change_label": str(config["label"]),
        "notes": str(notes or "").strip(),
        "passed": not blocked_checks,
        "status": "blocked" if blocked_checks else ("warning" if warning_checks else "passed"),
        "required_evidence": list(config["required_evidence"]),
        "provided_evidence": sorted(name for name, provided in evidence_map.items() if provided),
        "missing_evidence": missing_evidence,
        "changed_paths": paths,
        "checks": checks,
        "blocked_checks": blocked_checks,
        "warning_checks": warning_checks,
        "recommendations": _build_recommendations(normalized_type, missing_evidence, warning_checks, paths),
    }


def build_governance_enforcement(
    project_root: str | Path,
    runtime_root: Optional[str | Path] = None,
    *,
    change_type: str = "feature",
    evidence: Optional[Dict[str, Any]] = None,
    changed_paths: Optional[List[str]] = None,
    notes: str = "",
    mode: str = "strict",
    fail_on_warnings: bool = False,
) -> Dict[str, Any]:
    normalized_mode = _normalize_enforcement_mode(mode)
    admission = build_change_admission(
        project_root,
        runtime_root=runtime_root,
        change_type=change_type,
        evidence=evidence,
        changed_paths=changed_paths,
        notes=notes,
    )
    blocking_checks = list(admission.get("blocked_checks") or [])
    if fail_on_warnings:
        blocking_checks.extend(
            check for check in list(admission.get("warning_checks") or [])
            if check not in blocking_checks
        )

    strict_should_block = bool(blocking_checks)
    should_block = strict_should_block if normalized_mode == "strict" else False
    passed = not should_block
    exit_code = 1 if should_block else 0
    if normalized_mode == "advisory":
        message = (
            "治理准入 advisory 模式: 发现 blockers 但不阻断"
            if strict_should_block
            else "治理准入 advisory 模式: 无阻断项"
        )
    else:
        message = (
            f"治理准入 strict 模式阻断: {', '.join(blocking_checks)}"
            if should_block
            else "治理准入 strict 模式通过"
        )

    return {
        "schema_version": GOVERNANCE_ENFORCEMENT_SCHEMA_VERSION,
        "mode": normalized_mode,
        "fail_on_warnings": bool(fail_on_warnings),
        "passed": passed,
        "should_block": should_block,
        "exit_code": exit_code,
        "message": message,
        "blocking_checks": blocking_checks,
        "admission": admission,
    }


def _normalize_enforcement_mode(value: str) -> str:
    normalized = str(value or "strict").strip().lower()
    return normalized if normalized in {"strict", "advisory"} else "strict"


def _normalize_change_type(value: str) -> str:
    return str(value or "feature").strip().lower() or "feature"


def _normalize_evidence(evidence: Optional[Dict[str, Any]]) -> Dict[str, bool]:
    result: Dict[str, bool] = {}
    for key, value in dict(evidence or {}).items():
        name = str(key or "").strip().lower()
        if not name:
            continue
        if isinstance(value, bool):
            result[name] = value
        elif isinstance(value, (list, tuple, set, dict)):
            result[name] = bool(value)
        else:
            result[name] = bool(str(value or "").strip())
    return result


def _normalize_changed_paths(paths: Optional[List[str]]) -> List[str]:
    normalized: List[str] = []
    seen = set()
    for raw_path in list(paths or []):
        text = str(raw_path or "").strip().replace("\\", "/")
        if not text:
            continue
        while text.startswith("./"):
            text = text[2:]
        text = text.strip("/")
        if text and text not in seen:
            normalized.append(text)
            seen.add(text)
    return normalized


def _check_change_type(change_type: str) -> Dict[str, Any]:
    if change_type in _CHANGE_TYPES:
        return _check("change_type", "passed", f"Change type '{change_type}' is governed", details={"change_type": change_type})
    return _check(
        "change_type",
        "blocked",
        f"Unknown change type: {change_type}",
        issues=[{"code": "unknown_change_type", "message": f"Unknown change type: {change_type}"}],
        details={"supported_change_types": sorted(_CHANGE_TYPES)},
    )


def _check_required_evidence(change_type: str, evidence: Dict[str, bool]) -> Dict[str, Any]:
    config = _CHANGE_TYPES.get(change_type, _CHANGE_TYPES["feature"])
    required = list(config["required_evidence"])
    missing = [item for item in required if not evidence.get(item)]
    if not missing:
        return _check(
            "required_evidence",
            "passed",
            "All required evidence is declared",
            details={"required_evidence": required, "missing_evidence": []},
        )
    return _check(
        "required_evidence",
        "blocked",
        f"Missing required evidence: {', '.join(missing)}",
        issues=[{"code": "missing_evidence", "evidence": item, "message": _EVIDENCE_CATALOG.get(item, item)} for item in missing],
        details={"required_evidence": required, "missing_evidence": missing},
    )


def _check_changed_paths(project_root: Path, runtime_root: Path, changed_paths: List[str]) -> Dict[str, Any]:
    if not changed_paths:
        return _check(
            "changed_paths",
            "warning",
            "No changed paths were declared; path governance could not be fully evaluated",
            warnings=[{"code": "missing_changed_paths", "message": "Provide changed_paths for stronger file tree governance"}],
        )

    issues: List[Dict[str, Any]] = []
    warnings: List[Dict[str, Any]] = []
    layout_validator = ProjectLayoutValidator(project_root=project_root, runtime_root=runtime_root)
    for path_text in changed_paths:
        if _path_escapes(path_text):
            issues.append({"code": "path_escape", "path": path_text, "message": "Changed path may not contain traversal or absolute drive syntax"})
            continue
        if not _is_allowed_path(path_text):
            issues.append({"code": "ungoverned_path", "path": path_text, "message": "Changed path is outside governed source, docs, tests, or managed output roots"})
            continue
        kind = _infer_managed_kind(path_text)
        if kind:
            root = runtime_root if path_text.startswith(("logs/", "api_server/static/dist/", "tests/baselines/")) else project_root
            result = layout_validator.validate_managed_path(root / path_text, kind)
            if not result["passed"]:
                issues.extend({
                    "code": issue["code"],
                    "path": path_text,
                    "message": issue["message"],
                } for issue in result.get("issues") or [])

    status = "blocked" if issues else ("warning" if warnings else "passed")
    return _check(
        "changed_paths",
        status,
        f"{len(changed_paths)} changed paths evaluated",
        issues=issues,
        warnings=warnings,
        details={"changed_path_count": len(changed_paths)},
    )


def _check_quality_dashboard(project_root: Path, runtime_root: Path) -> Dict[str, Any]:
    dashboard = build_quality_dashboard(project_root, runtime_root=runtime_root)
    if dashboard["blocked_count"]:
        return _check(
            "quality_dashboard",
            "blocked",
            "Quality dashboard has blocked sections",
            issues=[{"code": "quality_blocked", "message": section["summary"], "section": section["name"]} for section in dashboard["sections"] if section["status"] == "blocked"],
            details={"status": dashboard["status"], "blocked_count": dashboard["blocked_count"], "warning_count": dashboard["warning_count"]},
        )
    if dashboard["warning_count"]:
        return _check(
            "quality_dashboard",
            "warning",
            "Quality dashboard has warnings but no blockers",
            warnings=[{"code": "quality_warning", "message": section["summary"], "section": section["name"]} for section in dashboard["sections"] if section["status"] == "warning"],
            details={"status": dashboard["status"], "blocked_count": dashboard["blocked_count"], "warning_count": dashboard["warning_count"]},
        )
    return _check(
        "quality_dashboard",
        "passed",
        "Quality dashboard has no blockers",
        details={"status": dashboard["status"], "blocked_count": dashboard["blocked_count"], "warning_count": dashboard["warning_count"]},
    )


def _check_migrations(project_root: Path, runtime_root: Path) -> Dict[str, Any]:
    migration_status = MigrationRunner(project_root, runtime_root=runtime_root).build_migration_status()
    if migration_status["failed_count"]:
        return _check(
            "migrations",
            "blocked",
            "Migration compatibility has failed checks",
            issues=list(migration_status.get("issues") or []),
            details={key: migration_status[key] for key in ("migration_count", "applied_count", "pending_count", "failed_count")},
        )
    if migration_status["pending_count"]:
        return _check(
            "migrations",
            "warning",
            "Migration compatibility has pending setup",
            warnings=list(migration_status.get("warnings") or []),
            details={key: migration_status[key] for key in ("migration_count", "applied_count", "pending_count", "failed_count")},
        )
    return _check(
        "migrations",
        "passed",
        "Migration compatibility is current",
        details={key: migration_status[key] for key in ("migration_count", "applied_count", "pending_count", "failed_count")},
    )


def _build_recommendations(change_type: str, missing_evidence: List[str], warning_checks: List[str], changed_paths: List[str]) -> List[str]:
    recommendations: List[str] = []
    for item in missing_evidence:
        description = _EVIDENCE_CATALOG.get(item, item)
        recommendations.append(f"补齐 evidence `{item}`: {description}")
    if "changed_paths" in warning_checks and not changed_paths:
        recommendations.append("在准入请求中提供 changed_paths，以便检查文件树和受管目录落点。")
    if "migrations" in warning_checks:
        recommendations.append("运行 `/migrations/apply` 或补齐项目模板、数据表、遥测、性能基线目录后再复查。")
    config = _CHANGE_TYPES.get(change_type)
    if config:
        recommendations.append(f"推荐落点: {', '.join(config['recommended_paths'])}")
    return recommendations


def _path_escapes(path_text: str) -> bool:
    parts = [part for part in path_text.replace("\\", "/").split("/") if part]
    return ".." in parts or path_text.startswith("/") or ":" in path_text


def _is_allowed_path(path_text: str) -> bool:
    if path_text in _ALLOWED_ROOT_FILES:
        return True
    normalized = str(path_text or "").strip().replace("\\", "/").strip("/")
    if not normalized:
        return False
    return any(
        normalized == prefix.rstrip("/") or normalized.startswith(prefix)
        for prefix in _ALLOWED_PATH_PREFIXES
    )


def _infer_managed_kind(path_text: str) -> Optional[str]:
    suffix = Path(path_text).suffix.lower()
    name = Path(path_text).name
    if not suffix:
        return None
    if path_text.startswith("data_tables/") and suffix in {".csv", ".tsv", ".json"}:
        return "data_table"
    if path_text.startswith(("scripts/", "agent_modules/scripts/")) and suffix == ".gd":
        return "generated_script"
    if path_text.startswith(("scenes/", "agent_modules/scenes/")) and suffix == ".tscn":
        return "generated_scene"
    if path_text.startswith("assets/manifests/") and suffix == ".json":
        return "asset_manifest"
    if path_text.startswith("assets/"):
        return "art_asset"
    if path_text == "telemetry/event_catalog.json":
        return "telemetry_catalog"
    if path_text.startswith("telemetry/sessions/"):
        return "telemetry_session"
    if path_text.startswith("logs/reports/"):
        return "runtime_report"
    if path_text.startswith(("logs/test_artifacts/", "logs/visual_feedback/")):
        return "runtime_screenshot"
    if path_text.startswith("tests/baselines/"):
        return "baseline_artifact"
    if path_text.startswith("api_server/static/dist/"):
        if name == "release_manifest.json":
            return "release_manifest"
        if name in {"release_notes.md", "qa_gate_report.md", "build.log"}:
            return "release_report"
        return "release_output"
    return None


def _check(
    name: str,
    status: str,
    message: str,
    *,
    issues: Optional[List[Dict[str, Any]]] = None,
    warnings: Optional[List[Dict[str, Any]]] = None,
    details: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    return {
        "name": name,
        "status": status,
        "passed": status != "blocked",
        "message": message,
        "issues": list(issues or []),
        "warnings": list(warnings or []),
        "details": dict(details or {}),
    }

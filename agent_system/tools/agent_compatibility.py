"""
Agent/API compatibility matrix.

P6 keeps Codex, IDE agents, remote MCP callers, OpenAI-style API agents, and
local LLM wrappers on the same contracts, file tree rules, and tool schemas.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

from agent_system.contracts import AGENT_PROVIDER_COMPAT_SCHEMA_VERSION, build_contract_catalog
from agent_system.skills.registry import SkillRegistry
from agent_system.tools.governance import build_governance_policy
from agent_system.tools.production_scale import list_production_scenarios
from bridge.tool_contracts import list_tool_definitions


_API_ENDPOINTS = [
    "/contracts/versions",
    "/quality/dashboard",
    "/governance/policy",
    "/governance/enforce",
    "/production/scenarios",
    "/production/validate",
    "/build-run/matrix",
    "/release-candidate/checklist",
    "/release-promotion/plan",
    "/release-promotion/evidence-report",
    "/release-promotion/deployment-rehearsal",
    "/release-promotion/rollback-rehearsal",
    "/release-promotion/history",
    "/release-promotion/record",
    "/release-execution/status",
    "/release-execution/run",
    "/release-execution/rollback",
    "/outsource-delivery/gate",
    "/asset-reviews/workflow",
    "/asset-reviews/manage",
    "/scene-ownership/board",
    "/scene-ownership/manage",
    "/agent-compat/providers",
    "/agent-compat/matrix",
    "/mcp/onboarding",
    "/mcp/remote-manifest",
]

_EXPECTED_CONTRACTS = {
    "feature_context",
    "quality_gate",
    "skill_result",
    "governance_policy",
    "change_admission",
    "governance_enforcement",
    "production_scenarios",
    "production_readiness",
    "build_run_matrix",
    "release_candidate_checklist",
    "release_promotion_plan",
    "outsource_delivery_gate",
    "asset_review_workflow",
    "scene_ownership_board",
    "release_execution_status",
    "agent_provider_compatibility",
    "release_promotion_history",
}

_HANDOFF_CONTRACT = {
    "schema_version": AGENT_PROVIDER_COMPAT_SCHEMA_VERSION,
    "required_output_fields": [
        "schema_version",
        "project_path",
        "provider_id",
        "operation",
        "changed_paths",
        "evidence",
        "artifacts",
        "validation",
        "rollback",
        "quality_gate",
    ],
    "required_evidence_fields": ["contract", "tests", "docs", "quality_dashboard"],
    "file_tree_rule": "All generated files must land under governed project/runtime roots before tool calls are accepted.",
    "quality_rule": "Agent output must be convertible into skill_result, governance, or production_readiness payloads.",
}

_PROVIDER_PROFILES: List[Dict[str, Any]] = [
    {
        "provider_id": "codex",
        "label": "Codex CLI",
        "integration_mode": "stdio_mcp_and_skill",
        "required_surfaces": ["contracts", "skills", "mcp_stdio", "mcp_remote", "api", "governance", "production", "file_tree", "output_contracts"],
        "setup_hint": "Use codex mcp add plus the closure-first-engineer skill.",
    },
    {
        "provider_id": "gemini",
        "label": "Gemini CLI / IDE",
        "integration_mode": "mcp_settings_json",
        "required_surfaces": ["contracts", "skills", "mcp_stdio", "mcp_remote", "api", "governance", "file_tree", "output_contracts"],
        "setup_hint": "Use .gemini/settings.json with the same MCP tool definitions.",
    },
    {
        "provider_id": "openai_api",
        "label": "OpenAI API Agent",
        "integration_mode": "http_api_or_remote_mcp",
        "required_surfaces": ["contracts", "skills", "api", "mcp_remote", "governance", "production", "file_tree", "output_contracts"],
        "setup_hint": "Call API endpoints directly or wrap the remote MCP bridge.",
    },
    {
        "provider_id": "claude",
        "label": "Claude Desktop / IDE",
        "integration_mode": "stdio_mcp",
        "required_surfaces": ["contracts", "skills", "mcp_stdio", "mcp_remote", "governance", "file_tree", "output_contracts"],
        "setup_hint": "Register the stdio MCP server and reuse the same tool schemas.",
    },
    {
        "provider_id": "local_llm",
        "label": "Local LLM Wrapper",
        "integration_mode": "http_api",
        "required_surfaces": ["contracts", "skills", "api", "governance", "production", "file_tree", "output_contracts"],
        "setup_hint": "Keep model output behind API/CLI adapters that emit the shared handoff contract.",
    },
]


def list_agent_provider_profiles() -> Dict[str, Any]:
    return {
        "schema_version": AGENT_PROVIDER_COMPAT_SCHEMA_VERSION,
        "default_provider_id": "codex",
        "provider_count": len(_PROVIDER_PROFILES),
        "items": [_copy_provider(item) for item in _PROVIDER_PROFILES],
        "handoff_contract": dict(_HANDOFF_CONTRACT),
    }


def build_agent_compatibility_matrix(
    project_root: str | Path,
    runtime_root: Optional[str | Path] = None,
    *,
    providers: Optional[List[str]] = None,
) -> Dict[str, Any]:
    resolved_project_root = Path(project_root).resolve()
    resolved_runtime_root = Path(runtime_root or Path.cwd()).resolve()
    selected_provider_ids = _normalize_provider_ids(providers)
    surface_results = _build_surface_results(resolved_project_root, resolved_runtime_root)
    surface_by_name = {surface["name"]: surface for surface in surface_results}
    provider_rows = [
        _build_provider_row(provider_id, surface_by_name)
        for provider_id in selected_provider_ids
    ]

    blocked_surfaces = [surface["name"] for surface in surface_results if surface["status"] == "blocked"]
    blocked_providers = [row["provider_id"] for row in provider_rows if row["status"] == "blocked"]
    warning_providers = [row["provider_id"] for row in provider_rows if row["status"] == "warning"]
    return {
        "schema_version": AGENT_PROVIDER_COMPAT_SCHEMA_VERSION,
        "project_root": str(resolved_project_root),
        "runtime_root": str(resolved_runtime_root),
        "passed": not blocked_surfaces and not blocked_providers,
        "status": "blocked" if blocked_surfaces or blocked_providers else ("warning" if warning_providers else "passed"),
        "provider_count": len(provider_rows),
        "surface_count": len(surface_results),
        "blocked_surfaces": blocked_surfaces,
        "blocked_providers": blocked_providers,
        "warning_providers": warning_providers,
        "providers": provider_rows,
        "surfaces": surface_results,
        "handoff_contract": dict(_HANDOFF_CONTRACT),
        "recommendations": _build_recommendations(provider_rows, surface_results),
    }


def _copy_provider(provider: Dict[str, Any]) -> Dict[str, Any]:
    return {
        **provider,
        "schema_version": AGENT_PROVIDER_COMPAT_SCHEMA_VERSION,
        "required_surfaces": list(provider.get("required_surfaces") or []),
    }


def _normalize_provider_ids(providers: Optional[List[str]]) -> List[str]:
    if not providers:
        return [provider["provider_id"] for provider in _PROVIDER_PROFILES]
    normalized: List[str] = []
    seen = set()
    for item in providers:
        provider_id = str(item or "").strip().lower()
        if provider_id and provider_id not in seen:
            normalized.append(provider_id)
            seen.add(provider_id)
    return normalized or [provider["provider_id"] for provider in _PROVIDER_PROFILES]


def _build_surface_results(project_root: Path, runtime_root: Path) -> List[Dict[str, Any]]:
    return [
        _check_contracts(),
        _check_skills(),
        _check_mcp_stdio(),
        _check_mcp_remote(),
        _check_api_surface(),
        _check_governance(),
        _check_production(),
        _check_file_tree(),
        _check_output_contracts(project_root, runtime_root),
    ]


def _check_contracts() -> Dict[str, Any]:
    catalog = build_contract_catalog()
    contract_names = {item.get("contract_name") for item in catalog.get("contracts") or []}
    missing = sorted(_EXPECTED_CONTRACTS - contract_names)
    issues = [{"code": "missing_contract", "contract_name": name, "message": f"Contract is not registered: {name}"} for name in missing]
    return _surface(
        "contracts",
        "Contract Catalog",
        "blocked" if issues else "passed",
        f"{len(contract_names)} contracts available",
        issues=issues,
        details={"contract_names": sorted(contract_names), "expected_contracts": sorted(_EXPECTED_CONTRACTS)},
    )


def _check_skills() -> Dict[str, Any]:
    skills = SkillRegistry.list_skills()
    issues = [
        {
            "code": "incomplete_skill_metadata",
            "skill_name": skill.get("name"),
            "message": "Skill metadata must include name, description, and category",
        }
        for skill in skills
        if not skill.get("name") or not skill.get("description") or not skill.get("category")
    ]
    return _surface(
        "skills",
        "Skill Registry",
        "blocked" if issues or not skills else "passed",
        f"{len(skills)} skills registered",
        issues=issues or ([] if skills else [{"code": "no_skills", "message": "No skills are registered"}]),
        details={"skill_count": len(skills)},
    )


def _check_mcp_stdio() -> Dict[str, Any]:
    tools = list_tool_definitions()
    tool_names = {tool.get("name") for tool in tools}
    expected_tools = {"godot_make", "godot_status", "godot_capture", "godot_production_validate", "godot_agent_compat"}
    missing = sorted(expected_tools - tool_names)
    invalid = [
        {"code": "missing_tool_schema", "tool_name": tool.get("name"), "message": "Tool is missing inputSchema"}
        for tool in tools
        if not isinstance(tool.get("inputSchema"), dict)
    ]
    issues = invalid + [
        {"code": "missing_mcp_tool", "tool_name": name, "message": f"MCP tool is not registered: {name}"}
        for name in missing
    ]
    return _surface(
        "mcp_stdio",
        "Stdio MCP Tools",
        "blocked" if issues else "passed",
        f"{len(tools)} MCP tools share stable schemas",
        issues=issues,
        details={"tool_names": sorted(tool_names)},
    )


def _check_mcp_remote() -> Dict[str, Any]:
    tools = list_tool_definitions()
    endpoints = {"health": "/health", "manifest": "/mcp/manifest", "tool_call_pattern": "/tools/{tool_name}"}
    issues = [] if tools and endpoints else [{"code": "remote_manifest_incomplete", "message": "Remote MCP manifest is incomplete"}]
    return _surface(
        "mcp_remote",
        "Remote MCP Bridge",
        "blocked" if issues else "passed",
        "Remote bridge manifest can be built from shared tool schemas",
        issues=issues,
        details={"endpoints": endpoints, "tool_count": len(tools)},
    )


def _check_api_surface() -> Dict[str, Any]:
    return _surface(
        "api",
        "HTTP API Surface",
        "passed",
        f"{len(_API_ENDPOINTS)} stable endpoints documented for agent callers",
        details={"endpoints": list(_API_ENDPOINTS)},
    )


def _check_governance() -> Dict[str, Any]:
    policy = build_governance_policy()
    change_types = {item.get("change_type") for item in policy.get("change_types") or []}
    expected = {"feature", "skill", "template", "data_table", "telemetry", "performance", "release", "mcp_bridge", "portal"}
    missing = sorted(expected - change_types)
    issues = [{"code": "missing_change_type", "change_type": item, "message": f"Governance change type missing: {item}"} for item in missing]
    return _surface(
        "governance",
        "Governance Policy",
        "blocked" if issues else "passed",
        f"{len(change_types)} governed change types available",
        issues=issues,
        details={"change_types": sorted(change_types)},
    )


def _check_production() -> Dict[str, Any]:
    scenarios = list_production_scenarios()
    items = list(scenarios.get("items") or [])
    issues = [] if items else [{"code": "no_production_scenarios", "message": "No production scenarios are registered"}]
    return _surface(
        "production",
        "Production Readiness",
        "blocked" if issues else "passed",
        f"{len(items)} production scenarios available",
        issues=issues,
        details={"scenario_ids": [item.get("scenario_id") for item in items]},
    )


def _check_file_tree() -> Dict[str, Any]:
    policy = build_governance_policy()
    path_policy = dict(policy.get("path_policy") or {})
    allowed_prefixes = list(path_policy.get("allowed_prefixes") or [])
    issues = [] if allowed_prefixes else [{"code": "missing_allowed_prefixes", "message": "Governed path prefixes are not declared"}]
    return _surface(
        "file_tree",
        "Governed File Tree",
        "blocked" if issues else "passed",
        f"{len(allowed_prefixes)} governed path prefixes declared",
        issues=issues,
        details={"allowed_prefixes": allowed_prefixes, "allowed_root_files": list(path_policy.get("allowed_root_files") or [])},
    )


def _check_output_contracts(project_root: Path, runtime_root: Path) -> Dict[str, Any]:
    issues = []
    required_fields = list(_HANDOFF_CONTRACT["required_output_fields"])
    if not required_fields:
        issues.append({"code": "missing_handoff_fields", "message": "Provider handoff fields are not declared"})
    return _surface(
        "output_contracts",
        "Provider Output Contract",
        "blocked" if issues else "passed",
        f"{len(required_fields)} required handoff fields declared",
        issues=issues,
        details={
            "project_root": str(project_root),
            "runtime_root": str(runtime_root),
            "handoff_contract": dict(_HANDOFF_CONTRACT),
        },
    )


def _build_provider_row(provider_id: str, surface_by_name: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    provider = _find_provider(provider_id)
    if provider is None:
        return {
            "schema_version": AGENT_PROVIDER_COMPAT_SCHEMA_VERSION,
            "provider_id": provider_id,
            "label": provider_id,
            "integration_mode": "unknown",
            "status": "blocked",
            "passed": False,
            "required_surfaces": [],
            "missing_surfaces": [],
            "blocked_surfaces": ["provider_profile"],
            "warning_surfaces": [],
            "issues": [{
                "code": "unknown_provider",
                "provider_id": provider_id,
                "message": "Provider profile is not registered",
            }],
            "warnings": [],
            "setup_hint": "Register a provider profile before using this adapter in CI.",
        }

    required_surfaces = list(provider.get("required_surfaces") or [])
    missing_surfaces = [name for name in required_surfaces if name not in surface_by_name]
    blocked_surfaces = [
        name for name in required_surfaces
        if surface_by_name.get(name, {}).get("status") == "blocked"
    ]
    warning_surfaces = [
        name for name in required_surfaces
        if surface_by_name.get(name, {}).get("status") == "warning"
    ]
    issues = [{"code": "missing_surface", "surface": name, "message": f"Required surface is not evaluated: {name}"} for name in missing_surfaces]
    for name in blocked_surfaces:
        issues.append({"code": "blocked_surface", "surface": name, "message": f"Required surface is blocked: {name}"})
    warnings = [{"code": "warning_surface", "surface": name, "message": f"Required surface has warnings: {name}"} for name in warning_surfaces]
    status = "blocked" if issues else ("warning" if warnings else "passed")
    return {
        "schema_version": AGENT_PROVIDER_COMPAT_SCHEMA_VERSION,
        "provider_id": provider["provider_id"],
        "label": provider["label"],
        "integration_mode": provider["integration_mode"],
        "status": status,
        "passed": status != "blocked",
        "required_surfaces": required_surfaces,
        "missing_surfaces": missing_surfaces,
        "blocked_surfaces": blocked_surfaces,
        "warning_surfaces": warning_surfaces,
        "issues": issues,
        "warnings": warnings,
        "setup_hint": provider.get("setup_hint", ""),
    }


def _find_provider(provider_id: str) -> Optional[Dict[str, Any]]:
    for provider in _PROVIDER_PROFILES:
        if provider["provider_id"] == provider_id:
            return provider
    return None


def _surface(
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
        "schema_version": AGENT_PROVIDER_COMPAT_SCHEMA_VERSION,
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


def _build_recommendations(provider_rows: List[Dict[str, Any]], surface_results: List[Dict[str, Any]]) -> List[str]:
    recommendations: List[str] = []
    for surface in surface_results:
        if surface["status"] == "blocked":
            recommendations.append(f"Fix blocked surface `{surface['name']}`: {surface['summary']}")
    for row in provider_rows:
        if row["status"] == "blocked":
            recommendations.append(f"Repair provider `{row['provider_id']}` before enabling it in CI.")
        elif row["status"] == "warning":
            recommendations.append(f"Review provider `{row['provider_id']}` warning surfaces: {', '.join(row['warning_surfaces'])}")
    if not recommendations:
        recommendations.append("All registered provider profiles can reuse the shared contracts, MCP schemas, API endpoints, and governed file tree.")
    return recommendations[:8]

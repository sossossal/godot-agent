from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List


DEFAULT_RELEASE_CAPABILITY_REGISTRY_PATH = "deployment/release_capability_registry.json"
RELEASE_CAPABILITY_REGISTRY_SCHEMA_VERSION = "1.0"
CAPABILITY_SURFACE_TYPES = {"tool", "command", "gateway_method", "hook"}
CAPABILITY_RISK_LEVELS = {"low", "medium", "high", "critical"}
CAPABILITY_SANDBOX_PROFILES = {
    "read_only",
    "workspace_write",
    "local_process",
    "browser_automation",
    "godot_gui",
    "network_bridge",
    "release_write",
}


def default_release_capability_registry_path() -> str:
    return DEFAULT_RELEASE_CAPABILITY_REGISTRY_PATH


def build_release_capability_registry(
    project_root: str | Path,
    *,
    registry_path: str = "",
) -> Dict[str, Any]:
    resolved_project_root = Path(project_root).resolve()
    resolved_registry_path = _resolve_relative_to(
        resolved_project_root,
        registry_path or default_release_capability_registry_path(),
    )
    relative_registry_path = _relative_to_root(resolved_registry_path, resolved_project_root)
    default_payload: Dict[str, Any] = {
        "schema_version": RELEASE_CAPABILITY_REGISTRY_SCHEMA_VERSION,
        "contract_versions": {
            "release_capability_registry": RELEASE_CAPABILITY_REGISTRY_SCHEMA_VERSION,
        },
        "registry_id": "",
        "registry_path": relative_registry_path,
        "registry_exists": resolved_registry_path.exists() and resolved_registry_path.is_file(),
        "valid": False,
        "status": "warning",
        "summary": "release capability registry missing",
        "capability_count": 0,
        "default_enabled_count": 0,
        "optional_heavy_count": 0,
        "actor_scoped_count": 0,
        "request_auth_count": 0,
        "surface_counts": {},
        "risk_counts": {},
        "group_counts": {},
        "capabilities": [],
        "recommendations": [
            f"补齐 {relative_registry_path}，把 release control plane 的 capability surface 显式写进仓库。"
        ],
    }
    if not default_payload["registry_exists"]:
        return default_payload

    try:
        payload = json.loads(resolved_registry_path.read_text(encoding="utf-8"))
    except Exception:
        default_payload["summary"] = "release capability registry is not valid JSON"
        default_payload["recommendations"] = [f"修复 {relative_registry_path} 的 JSON 结构。"]
        return default_payload
    if not isinstance(payload, dict):
        default_payload["summary"] = "release capability registry must be a JSON object"
        default_payload["recommendations"] = [f"修复 {relative_registry_path} 的顶层结构。"]
        return default_payload

    raw_capabilities = payload.get("capabilities")
    if raw_capabilities is not None and not isinstance(raw_capabilities, list):
        default_payload["summary"] = "release capability registry capabilities must be a list"
        default_payload["recommendations"] = [f"修复 {relative_registry_path} 的 capabilities 列表结构。"]
        default_payload["registry_exists"] = True
        return default_payload

    capabilities: List[Dict[str, Any]] = []
    recommendations: List[str] = []
    surface_counts: Dict[str, int] = {}
    risk_counts: Dict[str, int] = {}
    group_counts: Dict[str, int] = {}
    default_enabled_count = 0
    optional_heavy_count = 0
    actor_scoped_count = 0
    request_auth_count = 0

    for index, item in enumerate(list(raw_capabilities or []), start=1):
        capability = _normalize_capability_entry(item, index=index)
        capabilities.append(capability)
        if capability["default_enabled"]:
            default_enabled_count += 1
        if capability["optional_heavy"]:
            optional_heavy_count += 1
        if capability["requires_actor"]:
            actor_scoped_count += 1
        if capability["requires_request_auth"]:
            request_auth_count += 1
        for surface_type in capability["surface_types"]:
            surface_counts[surface_type] = surface_counts.get(surface_type, 0) + 1
        if capability["risk_level"]:
            risk_counts[capability["risk_level"]] = risk_counts.get(capability["risk_level"], 0) + 1
        if capability["group"]:
            group_counts[capability["group"]] = group_counts.get(capability["group"], 0) + 1
        recommendations.extend(capability["recommendations"])

    registry_id = str(payload.get("registry_id") or "release_control_plane_capabilities").strip()
    status = _worst_status([item["status"] for item in capabilities])
    if not capabilities:
        status = "warning"
        recommendations.append("至少登记一条 capability，把 release control plane 的入口和风险面显式化。")

    summary_parts = [
        f"capabilities={len(capabilities)}",
        f"default_enabled={default_enabled_count}",
        f"optional_heavy={optional_heavy_count}",
        f"actor_scoped={actor_scoped_count}",
        f"request_auth={request_auth_count}",
    ]
    if surface_counts:
        summary_parts.append(
            "surfaces="
            + ",".join(f"{key}:{surface_counts[key]}" for key in sorted(surface_counts))
        )
    if risk_counts:
        summary_parts.append(
            "risks=" + ",".join(f"{key}:{risk_counts[key]}" for key in sorted(risk_counts))
        )

    return {
        "schema_version": RELEASE_CAPABILITY_REGISTRY_SCHEMA_VERSION,
        "contract_versions": {
            "release_capability_registry": RELEASE_CAPABILITY_REGISTRY_SCHEMA_VERSION,
        },
        "registry_id": registry_id or "release_control_plane_capabilities",
        "registry_path": relative_registry_path,
        "registry_exists": True,
        "valid": True,
        "status": status,
        "summary": " / ".join(summary_parts),
        "capability_count": len(capabilities),
        "default_enabled_count": default_enabled_count,
        "optional_heavy_count": optional_heavy_count,
        "actor_scoped_count": actor_scoped_count,
        "request_auth_count": request_auth_count,
        "surface_counts": surface_counts,
        "risk_counts": risk_counts,
        "group_counts": group_counts,
        "capabilities": capabilities,
        "recommendations": _dedupe_text_list(recommendations),
    }


def build_release_capability_registry_report(summary: Dict[str, Any] | None) -> str:
    registry = dict(summary or {})
    capabilities = list(registry.get("capabilities") or [])
    lines = [
        "# Release Capability Registry",
        "",
        f"- Status: {registry.get('status') or 'warning'}",
        f"- Registry: {registry.get('registry_path') or '-'}",
        f"- Summary: {registry.get('summary') or '-'}",
        (
            f"- Counts: total={int(registry.get('capability_count') or 0)} / "
            f"default_enabled={int(registry.get('default_enabled_count') or 0)} / "
            f"optional_heavy={int(registry.get('optional_heavy_count') or 0)} / "
            f"actor_scoped={int(registry.get('actor_scoped_count') or 0)} / "
            f"request_auth={int(registry.get('request_auth_count') or 0)}"
        ),
        f"- Surfaces: {_format_count_map(registry.get('surface_counts')) or '-'}",
        f"- Risks: {_format_count_map(registry.get('risk_counts')) or '-'}",
        f"- Groups: {_format_count_map(registry.get('group_counts')) or '-'}",
        "",
        "## Capabilities",
        "",
    ]
    if not capabilities:
        lines.append("- No capabilities registered.")
    for capability in capabilities:
        scope_parts = []
        if capability.get("target_channels"):
            scope_parts.append(f"channels={','.join(capability['target_channels'])}")
        if capability.get("target_environments"):
            scope_parts.append(f"envs={','.join(capability['target_environments'])}")
        lines.extend([
            f"- `{capability.get('capability_id') or 'capability'}` [{capability.get('status') or 'warning'}] {capability.get('label') or '-'}",
            (
                "  "
                f"surface={','.join(capability.get('surface_types') or []) or '-'} / "
                f"risk={capability.get('risk_level') or '-'} / "
                f"actor={'yes' if capability.get('requires_actor') else 'no'} / "
                f"request_auth={'yes' if capability.get('requires_request_auth') else 'no'} / "
                f"sandbox={capability.get('sandbox_profile') or '-'} / "
                f"default_enabled={'yes' if capability.get('default_enabled') else 'no'} / "
                f"optional_heavy={'yes' if capability.get('optional_heavy') else 'no'}"
            ),
            (
                "  "
                f"group={capability.get('group') or '-'} / "
                f"contracts={','.join(capability.get('artifact_contracts') or []) or '-'} / "
                f"entrypoints={','.join(capability.get('entrypoints') or []) or '-'}"
            ),
            (
                "  "
                f"policy_action={capability.get('policy_action') or '-'} / "
                f"policy_decision={capability.get('policy_decision') or '-'} / "
                f"policy_operation={capability.get('policy_operation') or '-'}"
            ),
            f"  scope={'; '.join(scope_parts) if scope_parts else 'all'} / owners={','.join(capability.get('owners') or []) or '-'}",
            f"  summary={capability.get('summary') or '-'}",
        ])
        if capability.get("missing_fields"):
            lines.append(f"  missing={','.join(capability['missing_fields'])}")
    recommendations = list(registry.get("recommendations") or [])
    if recommendations:
        lines.extend(["", "## Recommendations", ""])
        lines.extend(f"- {item}" for item in recommendations)
    return "\n".join(lines).strip() + "\n"


def _normalize_capability_entry(value: Any, *, index: int) -> Dict[str, Any]:
    source = dict(value) if isinstance(value, dict) else {}
    capability_id = str(source.get("capability_id") or source.get("id") or f"capability_{index}").strip() or f"capability_{index}"
    label = str(source.get("label") or source.get("name") or capability_id).strip() or capability_id
    group = str(source.get("group") or "").strip().lower().replace(" ", "_")
    surface_types = _normalize_text_list(source.get("surface_types") or source.get("surfaces"), allowed=CAPABILITY_SURFACE_TYPES)
    risk_level = _normalize_choice(source.get("risk_level"), CAPABILITY_RISK_LEVELS)
    sandbox_profile = _normalize_choice(source.get("sandbox_profile"), CAPABILITY_SANDBOX_PROFILES)
    target_channels = _clean_text_list(source.get("target_channels"))
    target_environments = _clean_text_list(source.get("target_environments"))
    artifact_contracts = _clean_text_list(source.get("artifact_contracts"))
    entrypoints = _clean_text_list(source.get("entrypoints"))
    owners = _clean_text_list(source.get("owners"))
    notes = _clean_text_list(source.get("notes"))
    requires_actor = bool(source.get("requires_actor"))
    requires_request_auth = bool(source.get("requires_request_auth"))
    if "default_enabled" in source:
        default_enabled = bool(source.get("default_enabled"))
    else:
        default_enabled = not bool(source.get("optional_heavy"))
    optional_heavy = bool(source.get("optional_heavy"))

    missing_fields: List[str] = []
    if not surface_types:
        missing_fields.append("surface_types")
    if not risk_level:
        missing_fields.append("risk_level")
    if not sandbox_profile:
        missing_fields.append("sandbox_profile")
    if not artifact_contracts:
        missing_fields.append("artifact_contracts")
    if not entrypoints:
        missing_fields.append("entrypoints")
    if not owners:
        missing_fields.append("owners")
    consumes_live_summary = "release_live_ci_summary" in artifact_contracts
    if consumes_live_summary and "release_artifact_manifest" not in artifact_contracts:
        missing_fields.append("release_artifact_manifest")
    if (
        consumes_live_summary
        and capability_id.endswith("_read")
        and "gateway_method" in surface_types
        and "/release-artifact-manifest" not in entrypoints
    ):
        missing_fields.append("release_artifact_manifest_entrypoint")

    recommendations: List[str] = []
    if "surface_types" in missing_fields:
        recommendations.append(f"为 {capability_id} 声明 tool / command / gateway_method / hook 暴露面。")
    if "risk_level" in missing_fields:
        recommendations.append(f"为 {capability_id} 声明 risk_level，避免高风险能力继续隐式存在。")
    if "sandbox_profile" in missing_fields:
        recommendations.append(f"为 {capability_id} 声明 sandbox_profile，明确运行时边界。")
    if "artifact_contracts" in missing_fields:
        recommendations.append(f"为 {capability_id} 绑定 artifact_contracts，避免 capability 和证据面脱节。")
    if "entrypoints" in missing_fields:
        recommendations.append(f"为 {capability_id} 绑定稳定 entrypoints，避免控制面入口继续散落。")
    if "owners" in missing_fields:
        recommendations.append(f"为 {capability_id} 指定 owners，明确维护责任。")
    if "release_artifact_manifest" in missing_fields:
        recommendations.append(
            f"为 {capability_id} 同步声明 release_artifact_manifest，保持 live CI summary 和 artifact manifest 边界一致。"
        )
    if "release_artifact_manifest_entrypoint" in missing_fields:
        recommendations.append(f"为 {capability_id} 绑定 /release-artifact-manifest 只读入口。")

    return {
        "capability_id": capability_id,
        "label": label,
        "group": group,
        "surface_types": surface_types,
        "risk_level": risk_level,
        "requires_actor": requires_actor,
        "requires_request_auth": requires_request_auth,
        "default_enabled": default_enabled,
        "optional_heavy": optional_heavy,
        "sandbox_profile": sandbox_profile,
        "artifact_contracts": artifact_contracts,
        "entrypoints": entrypoints,
        "policy_action": str(source.get("policy_action") or "").strip().lower(),
        "policy_decision": str(source.get("policy_decision") or "").strip().lower(),
        "policy_operation": str(source.get("policy_operation") or "").strip().lower(),
        "target_channels": target_channels,
        "target_environments": target_environments,
        "owners": owners,
        "notes": notes,
        "status": "passed" if not missing_fields else "warning",
        "missing_fields": missing_fields,
        "summary": (
            f"surface={','.join(surface_types) or '-'} / "
            f"risk={risk_level or '-'} / "
            f"actor={'yes' if requires_actor else 'no'} / "
            f"request_auth={'yes' if requires_request_auth else 'no'} / "
            f"sandbox={sandbox_profile or '-'}"
        ),
        "recommendations": recommendations,
    }


def _clean_text_list(value: Any) -> List[str]:
    if isinstance(value, str):
        raw_items = value.replace("\r", "\n").replace(";", "\n").split("\n")
    elif isinstance(value, (list, tuple, set)):
        raw_items = list(value)
    else:
        return []
    cleaned: List[str] = []
    seen = set()
    for item in raw_items:
        text = str(item).strip()
        if not text or text in seen:
            continue
        cleaned.append(text)
        seen.add(text)
    return cleaned


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


def _normalize_text_list(value: Any, *, allowed: set[str]) -> List[str]:
    normalized: List[str] = []
    for item in _clean_text_list(value):
        lowered = item.strip().lower()
        if lowered in allowed and lowered not in normalized:
            normalized.append(lowered)
    return normalized


def _normalize_choice(value: Any, allowed: set[str]) -> str:
    text = str(value or "").strip().lower()
    return text if text in allowed else ""


def _resolve_relative_to(root: Path, value: str) -> Path:
    candidate = Path(str(value or "").strip() or ".")
    if candidate.is_absolute():
        return candidate.resolve()
    return (root / candidate).resolve()


def _relative_to_root(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return path.resolve().as_posix()


def _worst_status(statuses: List[str]) -> str:
    order = {"blocked": 3, "warning": 2, "passed": 1, "skipped": 0}
    worst = "passed"
    worst_score = order[worst]
    for raw_status in statuses:
        status = str(raw_status or "passed").strip().lower() or "passed"
        score = order.get(status, order["warning"])
        if score > worst_score:
            worst = status if status in order else "warning"
            worst_score = score
    return worst


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

"""
Release access policy helpers.

Provides a local, machine-readable authorization gate for high-risk release
write operations before external auth is fully wired.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from agent_system.validations import ProjectLayoutValidator


DEFAULT_RELEASE_ACCESS_POLICY_PATH = "deployment/release_access_policy.json"
_RELEASE_CHANNELS = {"qa", "staging", "release"}


def authorize_release_operation(
    project_root: str | Path,
    runtime_root: Optional[str | Path] = None,
    *,
    policy_path: str = "",
    actor_id: str = "",
    action: str,
    target_channel: str = "",
    target_environment: str = "",
    decision: str = "",
    operation: str = "",
    required: bool = True,
) -> Dict[str, Any]:
    resolved_project_root = Path(project_root).resolve()
    resolved_runtime_root = Path(runtime_root or Path.cwd()).resolve()
    resolved_policy_path = _resolve_project_path(
        resolved_project_root,
        policy_path or DEFAULT_RELEASE_ACCESS_POLICY_PATH,
    )
    normalized_action = str(action or "").strip().lower()
    normalized_actor_id = str(actor_id or "").strip()
    normalized_target_channel = str(target_channel or "").strip().lower() or "staging"
    normalized_target_environment = str(target_environment or "").strip()
    normalized_decision = str(decision or "").strip().lower()
    normalized_operation = str(operation or "").strip().lower()

    authorization = {
        "status": "blocked" if required else "skipped",
        "required": bool(required),
        "policy_path": _relative_to_root(resolved_policy_path, resolved_project_root),
        "policy_source": "missing",
        "actor_id": normalized_actor_id,
        "actor_roles": [],
        "action": normalized_action,
        "target_channel": normalized_target_channel,
        "target_environment": normalized_target_environment,
        "decision": normalized_decision,
        "operation": normalized_operation,
        "matched_rule_id": "",
        "required_roles": [],
        "reason": "",
    }

    layout_validator = ProjectLayoutValidator(project_root=resolved_project_root, runtime_root=resolved_runtime_root)
    layout_result = layout_validator.validate_managed_path(resolved_policy_path, "release_access_policy_manifest")
    if not layout_result["passed"]:
        authorization["status"] = "blocked" if required else "warning"
        authorization["reason"] = "; ".join(issue["message"] for issue in layout_result["issues"]) or "invalid release access policy path"
        return authorization

    if not resolved_policy_path.exists():
        authorization["status"] = "blocked" if required else "warning"
        authorization["reason"] = "release access policy manifest not found"
        return authorization

    try:
        payload = json.loads(resolved_policy_path.read_text(encoding="utf-8"))
    except Exception as exc:
        authorization["status"] = "blocked" if required else "warning"
        authorization["reason"] = f"release access policy manifest parse failed: {exc}"
        return authorization
    if not isinstance(payload, dict):
        authorization["status"] = "blocked" if required else "warning"
        authorization["reason"] = "release access policy manifest must be a JSON object"
        return authorization

    authorization["policy_source"] = "manifest"
    actors = _normalize_actor_roles(payload.get("actors"))
    rules = _normalize_rules(payload.get("rules"))
    matching_rules = [
        rule for rule in rules
        if _rule_matches(
            rule,
            action=normalized_action,
            target_channel=normalized_target_channel,
            decision=normalized_decision,
            operation=normalized_operation,
        )
    ]

    if normalized_actor_id:
        authorization["actor_roles"] = list(actors.get(normalized_actor_id, []))

    if not matching_rules:
        authorization["status"] = "blocked" if required else "warning"
        authorization["reason"] = "no matching release access policy rule"
        return authorization

    authorization["required_roles"] = _clean_text_list(
        role
        for rule in matching_rules
        for role in list(rule.get("roles") or [])
    )

    if not normalized_actor_id:
        if any(bool(rule.get("allow_without_actor")) for rule in matching_rules):
            matched_rule = next(rule for rule in matching_rules if bool(rule.get("allow_without_actor")))
            authorization["matched_rule_id"] = str(matched_rule.get("rule_id") or "")
            authorization["required_roles"] = _clean_text_list(matched_rule.get("roles"))
            authorization["status"] = "skipped"
            authorization["reason"] = "authorization skipped because actor_id is optional for this action"
            return authorization
        authorization["status"] = "blocked" if required else "warning"
        authorization["reason"] = "executed_by is required by release access policy"
        return authorization

    for rule in matching_rules:
        required_roles = _clean_text_list(rule.get("roles"))
        allowed_actor_ids = _clean_text_list(rule.get("actor_ids"))
        actor_roles = list(authorization.get("actor_roles") or [])
        if normalized_actor_id in allowed_actor_ids or set(actor_roles).intersection(required_roles):
            authorization["status"] = "passed"
            authorization["matched_rule_id"] = str(rule.get("rule_id") or "")
            authorization["required_roles"] = required_roles
            authorization["reason"] = (
                f"actor {normalized_actor_id} authorized for {normalized_action}"
            )
            return authorization

    authorization["status"] = "blocked" if required else "warning"
    if authorization["actor_roles"]:
        authorization["reason"] = (
            f"actor {normalized_actor_id} lacks required roles for {normalized_action}"
        )
    else:
        authorization["reason"] = f"actor {normalized_actor_id} not found in release access policy"
    return authorization


def _normalize_actor_roles(items: Any) -> Dict[str, List[str]]:
    actors: Dict[str, List[str]] = {}
    for raw_item in list(items or []):
        if not isinstance(raw_item, dict):
            continue
        actor_id = str(raw_item.get("actor_id") or "").strip()
        if not actor_id:
            continue
        actors[actor_id] = _clean_text_list(raw_item.get("roles"))
    return actors


def _normalize_rules(items: Any) -> List[Dict[str, Any]]:
    rules: List[Dict[str, Any]] = []
    for index, raw_item in enumerate(list(items or []), start=1):
        if not isinstance(raw_item, dict):
            continue
        action = str(raw_item.get("action") or "").strip().lower()
        if not action:
            continue
        rules.append({
            "rule_id": str(raw_item.get("rule_id") or f"rule_{index}").strip() or f"rule_{index}",
            "action": action,
            "channels": _clean_channels(raw_item.get("channels")),
            "decisions": _clean_text_list(raw_item.get("decisions")),
            "operations": _clean_text_list(raw_item.get("operations")),
            "roles": _clean_text_list(raw_item.get("roles")),
            "actor_ids": _clean_text_list(raw_item.get("actor_ids")),
            "allow_without_actor": bool(raw_item.get("allow_without_actor")),
        })
    return rules


def _rule_matches(
    rule: Dict[str, Any],
    *,
    action: str,
    target_channel: str,
    decision: str,
    operation: str,
) -> bool:
    if str(rule.get("action") or "") != action:
        return False
    channels = list(rule.get("channels") or [])
    if channels and target_channel not in channels:
        return False
    decisions = list(rule.get("decisions") or [])
    if decisions and decision not in decisions:
        return False
    operations = list(rule.get("operations") or [])
    if operations and operation not in operations:
        return False
    return True


def _clean_channels(values: Any) -> List[str]:
    return [
        value for value in _clean_text_list(values)
        if value in _RELEASE_CHANNELS
    ]


def _clean_text_list(values: Any) -> List[str]:
    result: List[str] = []
    for raw in list(values or []):
        value = str(raw or "").strip()
        if value and value not in result:
            result.append(value)
    return result


def _resolve_project_path(project_root: Path, raw_path: str) -> Path:
    relative = str(raw_path or DEFAULT_RELEASE_ACCESS_POLICY_PATH).strip()
    if relative.startswith("res://"):
        relative = relative[6:]
    return (project_root / relative).resolve()


def _relative_to_root(path: Path, project_root: Path) -> str:
    try:
        return path.resolve().relative_to(project_root.resolve()).as_posix()
    except Exception:
        return str(path.resolve())

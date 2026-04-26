from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List


DEFAULT_RELEASE_DISTRIBUTION_DELIVERY_PATH = "deployment/release_distribution_delivery.json"
DEFAULT_RELEASE_IDENTITY_BOUNDARY_PATH = "deployment/release_identity_boundary.json"
_READY_SIGNING_MODES = {"codesigned", "signed_archive", "notarized", "sha256_only"}
_ALLOWED_PROVIDER_MODES = {"project_manifest", "external_gateway", "oidc_federation", "manual_operator"}


def default_release_distribution_delivery_path() -> str:
    return DEFAULT_RELEASE_DISTRIBUTION_DELIVERY_PATH


def default_release_identity_boundary_path() -> str:
    return DEFAULT_RELEASE_IDENTITY_BOUNDARY_PATH


def load_release_distribution_delivery_profile(
    project_root: str | Path,
    *,
    target_channel: str,
    target_environment: str,
    manifest_path: str = "",
) -> Dict[str, Any]:
    resolved_project_root = Path(project_root).resolve()
    resolved_manifest_path = _resolve_project_path(
        resolved_project_root,
        manifest_path or default_release_distribution_delivery_path(),
    )
    payload, manifest_state = _load_profile_manifest(
        resolved_manifest_path,
        resolved_project_root,
        profile_label="release distribution delivery",
    )
    if manifest_state.get("status") == "warning" and not manifest_state.get("valid"):
        return manifest_state

    matched_profile = _match_profile(
        payload.get("profiles"),
        target_channel=target_channel,
        target_environment=target_environment,
    )
    if not matched_profile:
        manifest_state.update({
            "status": "warning",
            "summary": "release distribution delivery profile missing",
            "message": "no matching release distribution delivery profile",
            "recommendations": [
                "在 deployment/release_distribution_delivery.json 中声明与当前 channel/environment 匹配的外部分发 profile。"
            ],
        })
        return manifest_state

    installer_types = _clean_text_list(matched_profile.get("installer_types"))
    primary_installer = str(matched_profile.get("primary_installer") or "").strip()
    signing = _as_dict(matched_profile.get("signing"))
    signing_required = bool(signing.get("required"))
    signing_mode = str(signing.get("mode") or "").strip().lower()
    signing_profile_id = str(signing.get("profile_id") or "").strip()
    publish_targets = [
        _normalize_publish_target(item)
        for item in list(matched_profile.get("publish_targets") or [])
    ]
    publish_targets = [item for item in publish_targets if item]
    first_run_bootstrap = str(matched_profile.get("first_run_bootstrap") or "").strip()
    upgrade_strategy = str(matched_profile.get("upgrade_strategy") or "").strip()
    uninstall_strategy = str(matched_profile.get("uninstall_strategy") or "").strip()

    installer_status = "passed" if primary_installer and installer_types else "warning"
    signing_status = (
        "passed"
        if (not signing_required) or (signing_mode in _READY_SIGNING_MODES and (signing_profile_id or signing_mode == "sha256_only"))
        else "warning"
    )
    publish_status = "passed" if publish_targets else "warning"
    status = _worst_status([installer_status, signing_status, publish_status])
    recommendations: List[str] = []
    if installer_status != "passed":
        recommendations.append("为外部分发 profile 声明 primary_installer 和 installer_types，明确外部交付形态。")
    if signing_status != "passed":
        recommendations.append("补齐 signing.mode / signing.profile_id，把 portable handoff 推进到真实签名安装包。")
    if publish_status != "passed":
        recommendations.append("为外部分发 profile 补齐 publish_targets，明确渠道分发去向。")

    manifest_state.update({
        "valid": True,
        "status": status,
        "summary": (
            f"profile={str(matched_profile.get('profile_id') or 'distribution_delivery').strip()} / "
            f"installer={installer_status} / signing={signing_status} / publish={publish_status}"
        ),
        "message": f"profile={str(matched_profile.get('profile_id') or 'distribution_delivery').strip()}",
        "profile_id": str(matched_profile.get("profile_id") or "distribution_delivery").strip(),
        "primary_installer": primary_installer,
        "installer_types": installer_types,
        "installer_status": installer_status,
        "signing_required": signing_required,
        "signing_mode": signing_mode,
        "signing_profile_id": signing_profile_id,
        "signing_status": signing_status,
        "publish_targets": publish_targets,
        "publish_target_count": len(publish_targets),
        "publish_status": publish_status,
        "first_run_bootstrap": first_run_bootstrap,
        "upgrade_strategy": upgrade_strategy,
        "uninstall_strategy": uninstall_strategy,
        "recommendations": recommendations,
    })
    return manifest_state


def load_release_identity_boundary_profile(
    project_root: str | Path,
    *,
    target_channel: str,
    target_environment: str,
    manifest_path: str = "",
) -> Dict[str, Any]:
    resolved_project_root = Path(project_root).resolve()
    resolved_manifest_path = _resolve_project_path(
        resolved_project_root,
        manifest_path or default_release_identity_boundary_path(),
    )
    payload, manifest_state = _load_profile_manifest(
        resolved_manifest_path,
        resolved_project_root,
        profile_label="release identity boundary",
    )
    if manifest_state.get("status") == "warning" and not manifest_state.get("valid"):
        return manifest_state

    matched_profile = _match_profile(
        payload.get("profiles"),
        target_channel=target_channel,
        target_environment=target_environment,
    )
    if not matched_profile:
        manifest_state.update({
            "status": "warning",
            "summary": "release identity boundary profile missing",
            "message": "no matching release identity boundary profile",
            "recommendations": [
                "在 deployment/release_identity_boundary.json 中声明与当前 channel/environment 匹配的 identity/session profile。"
            ],
        })
        return manifest_state

    provider_mode = str(matched_profile.get("provider_mode") or "").strip().lower()
    provider_id = str(matched_profile.get("provider_id") or "").strip()
    session_policy = _as_dict(matched_profile.get("session_policy"))
    session_required = bool(session_policy.get("required"))
    max_session_age_hours = max(int(session_policy.get("max_session_age_hours") or 0), 0)
    session_backend = str(session_policy.get("backend") or "").strip()
    secret_rotation = _as_dict(matched_profile.get("secret_rotation"))
    secret_rotation_required = bool(secret_rotation.get("required"))
    secret_backend = str(secret_rotation.get("backend") or "").strip()
    rotation_owner = str(secret_rotation.get("owner") or "").strip()
    rotation_window_days = max(int(secret_rotation.get("rotation_window_days") or 0), 0)
    issuer_policy = str(matched_profile.get("issuer_policy") or "").strip()
    external_handoff = _as_dict(matched_profile.get("external_handoff"))
    external_handoff_required = bool(external_handoff.get("required"))
    external_handoff_mode = str(external_handoff.get("mode") or "").strip()
    external_handoff_target_id = str(external_handoff.get("target_id") or "").strip()
    external_handoff_owner = str(external_handoff.get("owner") or "").strip()
    external_handoff_status = (
        "passed"
        if (not external_handoff_required)
        or (external_handoff_mode and external_handoff_target_id and external_handoff_owner)
        else "warning"
    )

    provider_status = "passed" if provider_mode in _ALLOWED_PROVIDER_MODES and (provider_id or provider_mode == "project_manifest") else "warning"
    if str(target_channel or "").strip().lower() == "release":
        session_policy_status = "passed" if session_required and max_session_age_hours > 0 else "warning"
    else:
        session_policy_status = "passed" if (session_required and max_session_age_hours > 0) or session_backend else "warning"
    secret_rotation_status = (
        "passed"
        if ((not secret_rotation_required) and (secret_backend or rotation_owner or rotation_window_days >= 0))
        or (secret_backend and rotation_owner and rotation_window_days > 0)
        else "warning"
    )
    status = _worst_status([provider_status, session_policy_status, secret_rotation_status])
    recommendations: List[str] = []
    if provider_status != "passed":
        recommendations.append("补齐 provider_mode / provider_id，明确 release 使用 project manifest、external gateway 还是 federated OIDC。")
    if session_policy_status != "passed":
        recommendations.append("为 release 身份边界补齐 session_policy.required 和 max_session_age_hours。")
    if secret_rotation_status != "passed":
        recommendations.append("补齐 secret_rotation.backend / owner / rotation_window_days，明确凭据轮换责任边界。")
    if external_handoff_required and external_handoff_status != "passed":
        recommendations.append("补齐 external_handoff.mode / target_id / owner，把对外 identity/session intake 交接边界显式写进仓库。")

    manifest_state.update({
        "valid": True,
        "status": status,
        "summary": (
            f"profile={str(matched_profile.get('profile_id') or 'identity_boundary').strip()} / "
            f"provider={provider_status} / session={session_policy_status} / secret_rotation={secret_rotation_status}"
        ),
        "message": f"profile={str(matched_profile.get('profile_id') or 'identity_boundary').strip()}",
        "profile_id": str(matched_profile.get("profile_id") or "identity_boundary").strip(),
        "provider_mode": provider_mode,
        "provider_id": provider_id,
        "provider_status": provider_status,
        "session_required": session_required,
        "max_session_age_hours": max_session_age_hours,
        "session_backend": session_backend,
        "session_policy_status": session_policy_status,
        "secret_rotation_required": secret_rotation_required,
        "secret_backend": secret_backend,
        "rotation_owner": rotation_owner,
        "rotation_window_days": rotation_window_days,
        "secret_rotation_status": secret_rotation_status,
        "issuer_policy": issuer_policy,
        "external_handoff_required": external_handoff_required,
        "external_handoff_mode": external_handoff_mode,
        "external_handoff_target_id": external_handoff_target_id,
        "external_handoff_owner": external_handoff_owner,
        "external_handoff_status": external_handoff_status,
        "recommendations": recommendations,
    })
    return manifest_state


def _load_profile_manifest(
    manifest_path: Path,
    project_root: Path,
    *,
    profile_label: str,
) -> tuple[Dict[str, Any], Dict[str, Any]]:
    default_state = {
        "path": _relative_to_root(manifest_path, project_root),
        "exists": manifest_path.exists() and manifest_path.is_file(),
        "valid": False,
        "status": "warning",
        "summary": f"{profile_label} manifest missing",
        "message": f"missing {_relative_to_root(manifest_path, project_root)}",
        "profile_id": "",
        "recommendations": [f"补齐 {_relative_to_root(manifest_path, project_root)}，把 {profile_label} 边界显式写进仓库。"],
    }
    if not default_state["exists"]:
        return {}, default_state
    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    except Exception:
        default_state["summary"] = f"{profile_label} manifest is not valid JSON"
        default_state["message"] = default_state["summary"]
        default_state["recommendations"] = [f"修复 {_relative_to_root(manifest_path, project_root)} 的 JSON 结构。"]
        return {}, default_state
    if not isinstance(payload, dict):
        default_state["summary"] = f"{profile_label} manifest must be a JSON object"
        default_state["message"] = default_state["summary"]
        default_state["recommendations"] = [f"修复 {_relative_to_root(manifest_path, project_root)} 的顶层结构。"]
        return {}, default_state
    profiles = payload.get("profiles")
    if not isinstance(profiles, list):
        default_state["summary"] = f"{profile_label} manifest must declare profiles[]"
        default_state["message"] = default_state["summary"]
        default_state["recommendations"] = [f"在 {_relative_to_root(manifest_path, project_root)} 中补 profiles 数组。"]
        return payload, default_state
    default_state["valid"] = True
    default_state["summary"] = f"{profile_label} manifest loaded"
    default_state["message"] = default_state["summary"]
    default_state["recommendations"] = []
    return payload, default_state


def _match_profile(
    profiles: Any,
    *,
    target_channel: str,
    target_environment: str,
) -> Dict[str, Any]:
    normalized_channel = str(target_channel or "").strip().lower()
    normalized_environment = str(target_environment or "").strip().lower()
    for item in list(profiles or []):
        if not isinstance(item, dict):
            continue
        channels = {entry.lower() for entry in _clean_text_list(item.get("target_channels"))}
        environments = {entry.lower() for entry in _clean_text_list(item.get("target_environments"))}
        if channels and normalized_channel not in channels:
            continue
        if environments and normalized_environment not in environments:
            continue
        return dict(item)
    return {}


def _normalize_publish_target(value: Any) -> str:
    if isinstance(value, dict):
        return (
            str(value.get("target_id") or "").strip()
            or str(value.get("channel") or "").strip()
            or str(value.get("kind") or "").strip()
        )
    return str(value or "").strip()


def _resolve_project_path(project_root: Path, raw_path: str) -> Path:
    candidate = Path(str(raw_path or "").strip())
    if not str(candidate):
        return project_root.resolve()
    if candidate.is_absolute():
        return candidate.resolve()
    return (project_root / candidate).resolve()


def _relative_to_root(path: Path, root: Path) -> str:
    try:
        return str(path.resolve().relative_to(root.resolve())).replace("\\", "/")
    except Exception:
        return str(path.resolve()).replace("\\", "/")


def _clean_text_list(value: Any) -> List[str]:
    if isinstance(value, str):
        parts = value.replace(";", ",").replace("\r", ",").replace("\n", ",").split(",")
    elif isinstance(value, (list, tuple, set)):
        parts = list(value)
    else:
        return []

    cleaned: List[str] = []
    seen: set[str] = set()
    for item in parts:
        text = str(item).strip()
        lowered = text.lower()
        if not text or lowered in seen:
            continue
        cleaned.append(text)
        seen.add(lowered)
    return cleaned


def _as_dict(value: Any) -> Dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _worst_status(statuses: List[str]) -> str:
    rank = {"warning": 2, "passed": 1}
    return max(statuses or ["warning"], key=lambda item: rank.get(str(item or "").strip().lower(), 0))

"""
Release request authentication helpers.

Provides a request-level gate for high-risk release write APIs. Supports
legacy env tokens plus a rotation-friendly project manifest with token digests.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from agent_system.validations import ProjectLayoutValidator
from .release_boundary import (
    default_release_identity_boundary_path,
    load_release_identity_boundary_profile,
)


DEFAULT_RELEASE_REQUEST_AUTH_PATH = "deployment/release_request_auth.json"
DEFAULT_RELEASE_IDENTITY_REGISTRY_PATH = "deployment/release_identity_registry.json"
_RELEASE_CHANNELS = {"qa", "staging", "release"}
RELEASE_REQUEST_AUTH_POSTURE_SCHEMA_VERSION = "1.0"
RELEASE_REQUEST_AUTH_ROTATION_AUDIT_SCHEMA_VERSION = "1.0"
RELEASE_REQUEST_AUTH_IDENTITY_AUDIT_SCHEMA_VERSION = "1.0"
RELEASE_REQUEST_AUTH_IDENTITY_HANDOFF_SCHEMA_VERSION = "1.0"
_ROTATION_WARNING_WINDOW_DAYS = 30
_DEFAULT_RELEASE_WRITE_ACTIONS = ["promotion_record", "release_execution"]
_ACTIVE_ISSUER_STATUSES = {"active", "enabled"}
DEFAULT_RELEASE_REQUEST_AUTH_IDENTITY_HANDOFF_ROOT = "logs/reports/release_request_auth_identity_handoff"


def authorize_release_request(
    project_root: str | Path,
    runtime_root: Optional[str | Path] = None,
    *,
    client_host: str = "",
    authorization_header: str = "",
    custom_token_header: str = "",
    actor_id: str = "",
    action: str,
    target_channel: str = "",
    target_environment: str = "",
    auth_path: str = "",
    identity_path: str = "",
) -> Dict[str, Any]:
    resolved_project_root = Path(project_root).resolve()
    resolved_runtime_root = Path(runtime_root or Path.cwd()).resolve()
    resolved_auth_path = _resolve_project_path(
        resolved_project_root,
        auth_path or DEFAULT_RELEASE_REQUEST_AUTH_PATH,
    )
    resolved_identity_path = _resolve_project_path(
        resolved_project_root,
        identity_path or DEFAULT_RELEASE_IDENTITY_REGISTRY_PATH,
    )
    normalized_client_host = str(client_host or "").strip()
    normalized_actor_id = str(actor_id or "").strip()
    normalized_action = str(action or "").strip().lower()
    normalized_target_channel = str(target_channel or "").strip().lower() or "staging"
    normalized_target_environment = str(target_environment or "").strip()
    manifest_exists = resolved_auth_path.exists()
    token_value, scheme, header_name = _extract_token(
        authorization_header=authorization_header,
        custom_token_header=custom_token_header,
    )

    request_auth = {
        "status": "blocked",
        "required": False,
        "auth_path": _relative_to_root(resolved_auth_path, resolved_project_root),
        "client_host": normalized_client_host,
        "actor_id": normalized_actor_id,
        "action": normalized_action,
        "target_channel": normalized_target_channel,
        "target_environment": normalized_target_environment,
        "mode": "local_only",
        "header_name": header_name,
        "scheme": scheme,
        "token_configured": False,
        "token_present": bool(token_value),
        "token_id": "",
        "token_source": "",
        "session_id": "",
        "issued_by": "",
        "issued_at": "",
        "session_tracked": False,
        "identity_path": _relative_to_root(resolved_identity_path, resolved_project_root),
        "identity_registry_exists": False,
        "issuer_registered": False,
        "issuer_status": "",
        "issuer_subject_actor_ids": [],
        "max_session_age_hours": 0,
        "required_actor_ids": [],
        "reason": "",
    }

    layout_validator = ProjectLayoutValidator(project_root=resolved_project_root, runtime_root=resolved_runtime_root)
    layout_result = layout_validator.validate_managed_path(resolved_auth_path, "release_request_auth_manifest")
    if not layout_result["passed"]:
        request_auth["required"] = True
        request_auth["mode"] = "token"
        request_auth["reason"] = (
            "; ".join(issue["message"] for issue in layout_result["issues"])
            or "invalid release request auth path"
        )
        return request_auth

    manifest_payload, manifest_reason = _load_manifest(resolved_auth_path)
    if manifest_reason:
        request_auth["required"] = True
        request_auth["mode"] = "token"
        request_auth["reason"] = manifest_reason
        return request_auth

    manifest_tokens = _normalize_manifest_tokens(manifest_payload.get("tokens"))
    identity_exists = resolved_identity_path.exists()
    request_auth["identity_registry_exists"] = bool(identity_exists)
    identity_issuers: List[Dict[str, Any]] = []
    if identity_exists:
        identity_layout_result = layout_validator.validate_managed_path(
            resolved_identity_path,
            "release_identity_registry_manifest",
        )
        if not identity_layout_result["passed"]:
            request_auth["required"] = True
            request_auth["mode"] = "token"
            request_auth["reason"] = (
                "; ".join(issue["message"] for issue in identity_layout_result["issues"])
                or "invalid release identity registry path"
            )
            return request_auth
        identity_payload, identity_reason = _load_manifest(resolved_identity_path)
        if identity_reason:
            request_auth["required"] = True
            request_auth["mode"] = "token"
            request_auth["reason"] = identity_reason
            return request_auth
        identity_issuers = _normalize_identity_issuers(identity_payload.get("issuers"))
    allow_local_without_token = _resolve_allow_local_without_token(manifest_payload, manifest_tokens)
    env_token = str(os.environ.get("GODOT_AGENT_RELEASE_WRITE_TOKEN") or "").strip()
    token_specs = list(manifest_tokens)
    if env_token:
        token_specs.append({
            "token_id": "env_release_write_token",
            "token_sha256": _hash_token(env_token),
            "token_source": "env",
            "actions": [],
            "channels": [],
            "target_environments": [],
            "actor_ids": [],
            "revoked": False,
            "expires_at": "",
        })

    request_auth["token_configured"] = bool(token_specs)
    request_auth["mode"] = "token" if token_specs else "local_only"
    request_auth["required"] = bool(token_specs)

    if not token_specs:
        if manifest_exists and not allow_local_without_token:
            request_auth["required"] = True
            request_auth["mode"] = "token"
            request_auth["reason"] = "release request auth manifest requires token provisioning"
            return request_auth
        if _is_local_request_host(normalized_client_host):
            request_auth["status"] = "passed"
            request_auth["scheme"] = "local"
            request_auth["reason"] = "trusted local request allowed because no release write token is configured"
            return request_auth
        request_auth["reason"] = "remote release write denied because no release write token is configured"
        return request_auth

    if not token_value:
        if manifest_tokens and allow_local_without_token and _is_local_request_host(normalized_client_host):
            request_auth["status"] = "passed"
            request_auth["required"] = False
            request_auth["mode"] = "local_only"
            request_auth["scheme"] = "local"
            request_auth["reason"] = "trusted local request allowed by release request auth manifest"
            return request_auth
        if manifest_tokens and not any(spec.get("token_sha256") for spec in manifest_tokens):
            request_auth["reason"] = "release request auth manifest requires token provisioning"
            return request_auth
        request_auth["reason"] = "release write token missing or invalid"
        return request_auth

    token_digest = _hash_token(token_value)
    digest_matches = [
        dict(spec)
        for spec in token_specs
        if hmac.compare_digest(str(spec.get("token_sha256") or ""), token_digest)
    ]
    if not digest_matches:
        request_auth["reason"] = "release write token missing or invalid"
        return request_auth

    mismatch_reasons: List[str] = []
    for spec in digest_matches:
        mismatch = _match_token_constraints(
            spec,
            action=normalized_action,
            target_channel=normalized_target_channel,
            target_environment=normalized_target_environment,
            actor_id=normalized_actor_id,
        )
        if mismatch:
            mismatch_reasons.append(mismatch)
            continue
        request_auth["required"] = True
        request_auth["mode"] = "token"
        request_auth["token_id"] = str(spec.get("token_id") or "").strip()
        request_auth["token_source"] = str(spec.get("token_source") or "").strip()
        request_auth["session_id"] = str(spec.get("session_id") or "").strip()
        request_auth["issued_by"] = str(spec.get("issued_by") or "").strip()
        request_auth["issued_at"] = str(spec.get("issued_at") or "").strip()
        request_auth["session_tracked"] = bool(
            request_auth["session_id"]
            and request_auth["issued_by"]
            and _parse_iso_datetime(request_auth["issued_at"]) is not None
        )
        if request_auth["token_source"] == "manifest" and identity_exists:
            issuer_reason, issuer_spec = _match_identity_issuer_for_request(
                identity_issuers,
                issued_by=request_auth["issued_by"],
                target_channel=normalized_target_channel,
                target_environment=normalized_target_environment,
                actor_id=normalized_actor_id,
                session_tracked=bool(request_auth["session_tracked"]),
                issued_at=request_auth["issued_at"],
                token_id=request_auth["token_id"] or str(spec.get("token_id") or "").strip() or "token",
            )
            if issuer_reason:
                mismatch_reasons.append(issuer_reason)
                continue
            request_auth["issuer_registered"] = True
            request_auth["issuer_status"] = str(issuer_spec.get("status") or "").strip()
            request_auth["issuer_subject_actor_ids"] = list(issuer_spec.get("subject_actor_ids") or [])
            request_auth["max_session_age_hours"] = max(int(issuer_spec.get("max_session_age_hours") or 0), 0)
        request_auth["required_actor_ids"] = list(spec.get("actor_ids") or [])
        request_auth["status"] = "passed"
        request_auth["reason"] = (
            f"release write token accepted via {request_auth['token_source'] or 'token'}"
        )
        return request_auth

    request_auth["reason"] = mismatch_reasons[0] if mismatch_reasons else "release write token missing or invalid"
    return request_auth


def build_release_request_auth_posture(
    project_root: str | Path,
    runtime_root: Optional[str | Path] = None,
    *,
    action: str,
    target_channel: str = "",
    target_environment: str = "",
    auth_path: str = "",
    identity_path: str = "",
) -> Dict[str, Any]:
    resolved_project_root = Path(project_root).resolve()
    resolved_runtime_root = Path(runtime_root or Path.cwd()).resolve()
    resolved_auth_path = _resolve_project_path(
        resolved_project_root,
        auth_path or DEFAULT_RELEASE_REQUEST_AUTH_PATH,
    )
    resolved_identity_path = _resolve_project_path(
        resolved_project_root,
        identity_path or DEFAULT_RELEASE_IDENTITY_REGISTRY_PATH,
    )
    normalized_action = str(action or "").strip().lower()
    normalized_target_channel = str(target_channel or "").strip().lower() or "staging"
    normalized_target_environment = str(target_environment or "").strip()
    identity_boundary = load_release_identity_boundary_profile(
        resolved_project_root,
        target_channel=normalized_target_channel,
        target_environment=normalized_target_environment,
    )
    manifest_exists = resolved_auth_path.exists()
    env_token = str(os.environ.get("GODOT_AGENT_RELEASE_WRITE_TOKEN") or "").strip()
    report_relative_path = default_release_request_auth_posture_report_path(
        action=normalized_action,
        target_channel=normalized_target_channel,
    )
    resolved_report_path = _resolve_runtime_path(resolved_runtime_root, report_relative_path)

    posture = {
        "schema_version": RELEASE_REQUEST_AUTH_POSTURE_SCHEMA_VERSION,
        "status": "warning",
        "path": _relative_to_root(resolved_auth_path, resolved_project_root),
        "manifest_path": _relative_to_root(resolved_auth_path, resolved_project_root),
        "report_path": _relative_to_root(resolved_report_path, resolved_runtime_root),
        "report_exists": resolved_report_path.exists(),
        "manifest_exists": bool(manifest_exists),
        "identity_registry_path": _relative_to_root(resolved_identity_path, resolved_project_root),
        "identity_registry_exists": resolved_identity_path.exists(),
        "identity_boundary_path": str(identity_boundary.get("path") or default_release_identity_boundary_path()).strip(),
        "identity_boundary_exists": bool(identity_boundary.get("exists")),
        "identity_boundary_profile_id": str(identity_boundary.get("profile_id") or "").strip(),
        "identity_boundary_status": str(identity_boundary.get("status") or "warning").strip(),
        "identity_boundary_summary": str(identity_boundary.get("summary") or "").strip(),
        "identity_provider_mode": str(identity_boundary.get("provider_mode") or "").strip(),
        "identity_provider_id": str(identity_boundary.get("provider_id") or "").strip(),
        "identity_provider_status": str(identity_boundary.get("provider_status") or "").strip(),
        "identity_session_policy_status": str(identity_boundary.get("session_policy_status") or "").strip(),
        "identity_session_required": bool(identity_boundary.get("session_required")),
        "identity_max_session_age_hours": max(int(identity_boundary.get("max_session_age_hours") or 0), 0),
        "identity_session_backend": str(identity_boundary.get("session_backend") or "").strip(),
        "identity_secret_rotation_status": str(identity_boundary.get("secret_rotation_status") or "").strip(),
        "identity_secret_rotation_required": bool(identity_boundary.get("secret_rotation_required")),
        "identity_secret_backend": str(identity_boundary.get("secret_backend") or "").strip(),
        "identity_rotation_owner": str(identity_boundary.get("rotation_owner") or "").strip(),
        "identity_rotation_window_days": max(int(identity_boundary.get("rotation_window_days") or 0), 0),
        "identity_handoff_required": bool(identity_boundary.get("external_handoff_required")),
        "identity_handoff_mode": str(identity_boundary.get("external_handoff_mode") or "").strip(),
        "identity_handoff_target_id": str(identity_boundary.get("external_handoff_target_id") or "").strip(),
        "identity_handoff_owner": str(identity_boundary.get("external_handoff_owner") or "").strip(),
        "identity_handoff_config_status": str(identity_boundary.get("external_handoff_status") or "skipped").strip(),
        "action": normalized_action,
        "target_channel": normalized_target_channel,
        "target_environment": normalized_target_environment,
        "summary": "",
        "allow_local_without_token": False,
        "env_fallback_configured": bool(env_token),
        "rotation_window_days": _ROTATION_WARNING_WINDOW_DAYS,
        "token_count": 0,
        "active_token_count": 0,
        "matching_token_count": 0,
        "matching_bound_token_count": 0,
        "matching_unbound_token_count": 0,
        "matching_session_token_count": 0,
        "issuer_count": 0,
        "active_issuer_count": 0,
        "matching_registered_issuer_token_count": 0,
        "matching_unknown_issuer_token_count": 0,
        "matching_inactive_issuer_token_count": 0,
        "matching_unscoped_issuer_token_count": 0,
        "matching_subject_out_of_registry_count": 0,
        "matching_stale_session_token_count": 0,
        "revoked_token_count": 0,
        "expired_token_count": 0,
        "invalid_expiry_token_count": 0,
        "invalid_issued_at_token_count": 0,
        "tokens_without_expiry_count": 0,
        "tokens_expiring_soon_count": 0,
        "tokens_without_session_id_count": 0,
        "tokens_without_issued_by_count": 0,
        "tokens_without_issued_at_count": 0,
        "duplicate_token_id_count": 0,
        "matching_token_ids": [],
        "duplicate_token_ids": [],
        "notes": [],
        "recommendations": [],
    }

    layout_validator = ProjectLayoutValidator(project_root=resolved_project_root, runtime_root=resolved_runtime_root)
    layout_result = layout_validator.validate_managed_path(resolved_auth_path, "release_request_auth_manifest")
    if not layout_result["passed"]:
        posture["status"] = "blocked"
        posture["summary"] = (
            "; ".join(issue["message"] for issue in layout_result["issues"])
            or "invalid release request auth path"
        )
        posture["notes"] = [posture["summary"]]
        posture["recommendations"] = ["将 request auth manifest 固定落到 deployment/release_request_auth.json。"]
        return posture

    manifest_payload, manifest_reason = _load_manifest(resolved_auth_path)
    if manifest_reason:
        posture["status"] = "blocked"
        posture["summary"] = manifest_reason
        posture["notes"] = [manifest_reason]
        posture["recommendations"] = ["修复 release_request_auth manifest 的 JSON 格式或字段结构。"]
        return posture

    manifest_tokens = _normalize_manifest_tokens(manifest_payload.get("tokens"))
    identity_issuers: List[Dict[str, Any]] = []
    if resolved_identity_path.exists():
        identity_layout_result = layout_validator.validate_managed_path(
            resolved_identity_path,
            "release_identity_registry_manifest",
        )
        if not identity_layout_result["passed"]:
            posture["status"] = "blocked"
            posture["summary"] = (
                "; ".join(issue["message"] for issue in identity_layout_result["issues"])
                or "invalid release identity registry path"
            )
            posture["notes"] = [posture["summary"]]
            posture["recommendations"] = ["将 release identity registry 固定落到 deployment/release_identity_registry.json。"]
            return posture
        identity_payload, identity_reason = _load_manifest(resolved_identity_path)
        if identity_reason:
            posture["status"] = "blocked"
            posture["summary"] = identity_reason
            posture["notes"] = [identity_reason]
            posture["recommendations"] = ["修复 release_identity_registry manifest 的 JSON 格式或字段结构。"]
            return posture
        identity_issuers = _normalize_identity_issuers(identity_payload.get("issuers"))
    posture["manifest_exists"] = bool(manifest_exists)
    posture["allow_local_without_token"] = bool(
        manifest_payload.get("allow_local_without_token")
    ) if isinstance(manifest_payload, dict) and "allow_local_without_token" in manifest_payload else not bool(manifest_tokens)
    posture["token_count"] = len(manifest_tokens)
    posture["identity_registry_exists"] = resolved_identity_path.exists()
    posture["issuer_count"] = len(identity_issuers)
    posture["active_issuer_count"] = sum(
        1 for issuer in identity_issuers if str(issuer.get("status") or "").strip().lower() in _ACTIVE_ISSUER_STATUSES
    )

    matching_token_ids: List[str] = []
    matching_token_id_counts: Dict[str, int] = {}
    now = datetime.now(timezone.utc)
    rotation_deadline = now + timedelta(days=_ROTATION_WARNING_WINDOW_DAYS)
    for spec in manifest_tokens:
        token_id = str(spec.get("token_id") or "").strip()
        mismatch = _match_token_constraints(
            spec,
            action=normalized_action,
            target_channel=normalized_target_channel,
            target_environment=normalized_target_environment,
            actor_id="",
            ignore_actor=True,
        )
        raw_expires_at = str(spec.get("expires_at") or "").strip()
        expires_at = _parse_iso_datetime(raw_expires_at)
        raw_session_id = str(spec.get("session_id") or "").strip()
        raw_issued_by = str(spec.get("issued_by") or "").strip()
        raw_issued_at = str(spec.get("issued_at") or "").strip()
        issued_at = _parse_iso_datetime(raw_issued_at)
        is_expired = expires_at is not None and expires_at <= now
        is_expiring_soon = expires_at is not None and not is_expired and expires_at <= rotation_deadline
        is_revoked = bool(spec.get("revoked"))
        if is_revoked:
            posture["revoked_token_count"] += 1
        elif is_expired:
            posture["expired_token_count"] += 1
        else:
            posture["active_token_count"] += 1
        if mismatch:
            continue
        if is_revoked or is_expired:
            continue
        posture["matching_token_count"] += 1
        if raw_expires_at and expires_at is None:
            posture["invalid_expiry_token_count"] += 1
        elif not raw_expires_at:
            posture["tokens_without_expiry_count"] += 1
        if list(spec.get("actor_ids") or []):
            posture["matching_bound_token_count"] += 1
        else:
            posture["matching_unbound_token_count"] += 1
        if raw_session_id and raw_issued_by and issued_at is not None:
            posture["matching_session_token_count"] += 1
        else:
            if not raw_session_id:
                posture["tokens_without_session_id_count"] += 1
            if not raw_issued_by:
                posture["tokens_without_issued_by_count"] += 1
            if not raw_issued_at:
                posture["tokens_without_issued_at_count"] += 1
            elif issued_at is None:
                posture["invalid_issued_at_token_count"] += 1
        if is_expiring_soon:
            posture["tokens_expiring_soon_count"] += 1
        issuer_posture = _evaluate_identity_issuer_posture(
            spec,
            identity_issuers=identity_issuers,
            target_channel=normalized_target_channel,
            target_environment=normalized_target_environment,
            issued_at=issued_at,
            session_tracked=bool(raw_session_id and raw_issued_by and issued_at is not None),
            now=now,
        )
        issuer_status = str(issuer_posture.get("status") or "")
        if issuer_status == "registered":
            posture["matching_registered_issuer_token_count"] += 1
        elif issuer_status == "unknown":
            posture["matching_unknown_issuer_token_count"] += 1
        elif issuer_status == "inactive":
            posture["matching_inactive_issuer_token_count"] += 1
        elif issuer_status == "out_of_scope":
            posture["matching_unscoped_issuer_token_count"] += 1
        elif issuer_status == "subject_mismatch":
            posture["matching_subject_out_of_registry_count"] += 1
        elif issuer_status == "stale_session":
            posture["matching_stale_session_token_count"] += 1
        if token_id:
            matching_token_id_counts[token_id] = matching_token_id_counts.get(token_id, 0) + 1
        if token_id and token_id not in matching_token_ids:
            matching_token_ids.append(token_id)

    posture["matching_token_ids"] = matching_token_ids
    duplicate_token_ids = [
        token_id
        for token_id, count in matching_token_id_counts.items()
        if token_id and count > 1
    ]
    posture["duplicate_token_ids"] = duplicate_token_ids
    posture["duplicate_token_id_count"] = len(duplicate_token_ids)

    notes: List[str] = []
    recommendations: List[str] = []
    if posture["matching_token_count"] <= 0:
        if posture["allow_local_without_token"] or posture["env_fallback_configured"]:
            posture["status"] = "warning"
            posture["summary"] = "no matching manifest token; current requests fall back to local bypass or env token"
        else:
            posture["status"] = "blocked"
            posture["summary"] = "no active manifest token matches the current release action/channel"
        recommendations.append(
            "使用 python tools/generate_release_request_token_digest.py 生成新的 token digest 片段，并登记到 deployment/release_request_auth.json。"
        )
    elif posture["matching_unbound_token_count"] > 0:
        posture["status"] = "warning"
        posture["summary"] = "matching tokens exist, but some are not bound to actor_ids"
        recommendations.append("为 matching token 补齐 actor_ids，把请求 token 和 executed_by 绑定到同一主体。")
    elif posture["allow_local_without_token"]:
        posture["status"] = "warning"
        posture["summary"] = "matching tokens exist, but local bypass is still enabled"
        recommendations.append("关闭 allow_local_without_token，避免高风险发布写操作退回 local-only bypass。")
    elif posture["env_fallback_configured"]:
        posture["status"] = "warning"
        posture["summary"] = "matching manifest tokens exist, but env fallback token is still configured"
        recommendations.append("将 GODOT_AGENT_RELEASE_WRITE_TOKEN 退场，仅保留可轮换 manifest token。")
    else:
        posture["status"] = "passed"
        posture["summary"] = "matching manifest tokens are actor-bound and local bypass is disabled"

    if posture["status"] == "passed" and posture["invalid_expiry_token_count"] > 0:
        posture["status"] = "warning"
        posture["summary"] = "matching tokens exist, but some expires_at values are invalid"
        recommendations.append("修复 token 的 expires_at 格式，统一使用 ISO-8601 UTC 时间戳。")
    if posture["status"] == "passed" and posture["tokens_without_expiry_count"] > 0:
        posture["status"] = "warning"
        posture["summary"] = "matching tokens exist, but some do not declare expires_at"
        recommendations.append("为可用 token 补齐 expires_at，避免永久 token 绕过 rotation。")
    if posture["status"] == "passed" and posture["tokens_expiring_soon_count"] > 0:
        posture["status"] = "warning"
        posture["summary"] = (
            f"matching tokens exist, but some expire within {_ROTATION_WARNING_WINDOW_DAYS} days"
        )
        recommendations.append(
            f"轮换即将过期的 token，至少保证当前 action/channel 有一枚超过 {_ROTATION_WARNING_WINDOW_DAYS} 天的可用 token。"
        )
    if posture["status"] == "passed" and posture["duplicate_token_id_count"] > 0:
        posture["status"] = "warning"
        posture["summary"] = "matching tokens exist, but token_id values are duplicated"
        recommendations.append("清理重复 token_id，确保 rotation / 审计能唯一定位每枚 token。")
    if posture["status"] == "passed" and posture["identity_registry_exists"]:
        if posture["matching_unknown_issuer_token_count"] > 0:
            posture["status"] = "warning"
            posture["summary"] = "matching tokens exist, but some issuers are not registered"
            recommendations.append("把 matching token 的 issued_by 补登记到 deployment/release_identity_registry.json。")
        elif posture["matching_inactive_issuer_token_count"] > 0:
            posture["status"] = "warning"
            posture["summary"] = "matching tokens exist, but some issuers are not active"
            recommendations.append("清理或恢复 inactive issuer，避免 manifest token 继续绑定失效身份主体。")
        elif posture["matching_unscoped_issuer_token_count"] > 0:
            posture["status"] = "warning"
            posture["summary"] = "matching tokens exist, but some issuers are not scoped for the current channel/environment"
            recommendations.append("补齐 issuer 的 channels / target_environments，确保身份注册表和 token scope 一致。")
        elif posture["matching_subject_out_of_registry_count"] > 0:
            posture["status"] = "warning"
            posture["summary"] = "matching tokens exist, but some actor bindings are outside issuer registry coverage"
            recommendations.append("把 token actor_ids 和 issuer subject_actor_ids 对齐，避免身份注册表与 token subject 不一致。")
        elif posture["matching_stale_session_token_count"] > 0:
            posture["status"] = "warning"
            posture["summary"] = "matching tokens exist, but some issuer-backed sessions are older than the configured window"
            recommendations.append("轮换过旧 session，并收紧 release identity registry 的 max_session_age_hours。")
    if posture["status"] == "passed" and normalized_target_channel == "release":
        if not posture["identity_registry_exists"]:
            posture["status"] = "warning"
            posture["summary"] = "matching release tokens exist, but no identity registry is configured"
            recommendations.append("为 release 渠道补 deployment/release_identity_registry.json，把 issued_by 绑定到真实身份主体。")
        elif posture["matching_registered_issuer_token_count"] <= 0:
            posture["status"] = "warning"
            posture["summary"] = "matching release tokens exist, but none map to an active registered issuer"
            recommendations.append("先把 release token 的 issued_by 登记到 active issuer，再推进正式发布。")
        elif posture["matching_session_token_count"] <= 0:
            posture["status"] = "warning"
            posture["summary"] = "matching release tokens exist, but none are session-tracked"
            recommendations.append("为 release token 记录 session_id / issued_by / issued_at，避免正式发布仍使用不可追踪凭据。")
        elif (
            posture["tokens_without_session_id_count"] > 0
            or posture["tokens_without_issued_by_count"] > 0
            or posture["tokens_without_issued_at_count"] > 0
            or posture["invalid_issued_at_token_count"] > 0
        ):
            posture["status"] = "warning"
            posture["summary"] = "matching release tokens exist, but some are missing session metadata"
            recommendations.append("补齐 release token 的 session_id / issued_by / issued_at，保证正式发布凭据可审计。")

    if posture["revoked_token_count"] > 0:
        notes.append(f"revoked tokens={posture['revoked_token_count']}")
        recommendations.append("清理已 revoked 的历史 token 记录，避免 manifest 持续膨胀。")
    if posture["expired_token_count"] > 0:
        notes.append(f"expired tokens={posture['expired_token_count']}")
        recommendations.append("移除或轮换已过期 token，避免误以为当前仍有有效 release 凭据。")
    if posture["invalid_expiry_token_count"] > 0:
        notes.append(f"invalid expiry tokens={posture['invalid_expiry_token_count']}")
    if posture["invalid_issued_at_token_count"] > 0:
        notes.append(f"invalid issued_at tokens={posture['invalid_issued_at_token_count']}")
    if posture["tokens_without_expiry_count"] > 0:
        notes.append(f"tokens without expiry={posture['tokens_without_expiry_count']}")
    if posture["tokens_expiring_soon_count"] > 0:
        notes.append(
            f"tokens expiring within {posture['rotation_window_days']}d={posture['tokens_expiring_soon_count']}"
        )
    if posture["tokens_without_session_id_count"] > 0:
        notes.append(f"tokens without session_id={posture['tokens_without_session_id_count']}")
    if posture["tokens_without_issued_by_count"] > 0:
        notes.append(f"tokens without issued_by={posture['tokens_without_issued_by_count']}")
    if posture["tokens_without_issued_at_count"] > 0:
        notes.append(f"tokens without issued_at={posture['tokens_without_issued_at_count']}")
    if not posture["identity_registry_exists"]:
        notes.append("identity registry is not configured")
    if posture["matching_registered_issuer_token_count"] > 0:
        notes.append(f"registered issuers={posture['matching_registered_issuer_token_count']}")
    if posture["matching_unknown_issuer_token_count"] > 0:
        notes.append(f"unknown issuers={posture['matching_unknown_issuer_token_count']}")
    if posture["matching_inactive_issuer_token_count"] > 0:
        notes.append(f"inactive issuers={posture['matching_inactive_issuer_token_count']}")
    if posture["matching_unscoped_issuer_token_count"] > 0:
        notes.append(f"unscoped issuers={posture['matching_unscoped_issuer_token_count']}")
    if posture["matching_subject_out_of_registry_count"] > 0:
        notes.append(f"issuer subject mismatches={posture['matching_subject_out_of_registry_count']}")
    if posture["matching_stale_session_token_count"] > 0:
        notes.append(f"stale issuer-backed sessions={posture['matching_stale_session_token_count']}")
    if posture["duplicate_token_id_count"] > 0:
        notes.append(f"duplicate token_ids={', '.join(posture['duplicate_token_ids'])}")
    if posture["matching_token_ids"]:
        notes.append(f"matching tokens={', '.join(posture['matching_token_ids'])}")
    if posture["env_fallback_configured"]:
        notes.append("env fallback token is configured")
    if posture["allow_local_without_token"]:
        notes.append("local bypass is enabled")
    notes.append(f"identity boundary={posture['identity_boundary_status'] or 'warning'}")
    if posture["identity_boundary_profile_id"]:
        notes.append(f"identity boundary profile={posture['identity_boundary_profile_id']}")
    recommendations.extend(list(identity_boundary.get("recommendations") or []))

    posture["notes"] = _clean_text_list(notes)
    posture["recommendations"] = _clean_text_list(recommendations)
    return posture


def default_release_request_auth_posture_report_path(*, action: str, target_channel: str) -> str:
    normalized_action = _slugify_segment(action, default="release_action")
    normalized_channel = _slugify_segment(target_channel, default="staging")
    return f"logs/reports/release_request_auth_posture_{normalized_action}_{normalized_channel}.json"


def default_release_request_auth_rotation_audit_report_path(*, target_channel: str) -> str:
    normalized_channel = _slugify_segment(target_channel, default="staging")
    return f"logs/reports/release_request_auth_rotation_audit_{normalized_channel}.json"


def default_release_request_auth_identity_audit_report_path(*, target_channel: str) -> str:
    normalized_channel = _slugify_segment(target_channel, default="staging")
    return f"logs/reports/release_request_auth_identity_audit_{normalized_channel}.json"


def default_release_request_auth_identity_handoff_dir(
    *,
    target_channel: str,
    target_environment: str,
) -> str:
    channel_segment = _slugify_segment(target_channel, default="staging")
    environment_segment = _slugify_segment(target_environment, default="environment")
    return f"{DEFAULT_RELEASE_REQUEST_AUTH_IDENTITY_HANDOFF_ROOT}/{channel_segment}/{environment_segment}"


def default_release_request_auth_identity_handoff_manifest_path(
    *,
    target_channel: str,
    target_environment: str,
) -> str:
    return (
        f"{default_release_request_auth_identity_handoff_dir(target_channel=target_channel, target_environment=target_environment)}"
        "/identity_boundary_handoff_manifest.json"
    )


def default_release_request_auth_identity_handoff_instructions_path(
    *,
    target_channel: str,
    target_environment: str,
) -> str:
    return (
        f"{default_release_request_auth_identity_handoff_dir(target_channel=target_channel, target_environment=target_environment)}"
        "/IDENTITY_HANDOFF_INSTRUCTIONS.md"
    )


def build_release_request_auth_rotation_audit(
    project_root: str | Path,
    runtime_root: Optional[str | Path] = None,
    *,
    target_channel: str = "",
    target_environment: str = "",
    actions: Optional[List[str]] = None,
    auth_path: str = "",
) -> Dict[str, Any]:
    resolved_project_root = Path(project_root).resolve()
    resolved_runtime_root = Path(runtime_root or Path.cwd()).resolve()
    normalized_target_channel = str(target_channel or "").strip().lower() or "staging"
    normalized_target_environment = str(target_environment or "").strip() or _default_target_environment(normalized_target_channel)
    normalized_actions = _clean_text_list(actions) or list(_DEFAULT_RELEASE_WRITE_ACTIONS)
    report_relative_path = default_release_request_auth_rotation_audit_report_path(target_channel=normalized_target_channel)
    resolved_auth_path = _resolve_project_path(
        resolved_project_root,
        auth_path or DEFAULT_RELEASE_REQUEST_AUTH_PATH,
    )
    resolved_report_path = _resolve_runtime_path(resolved_runtime_root, report_relative_path)

    coverage = [
        build_release_request_auth_posture(
            resolved_project_root,
            runtime_root=resolved_runtime_root,
            action=action,
            target_channel=normalized_target_channel,
            target_environment=normalized_target_environment,
            auth_path=auth_path,
        )
        for action in normalized_actions
    ]
    blocked_action_count = sum(1 for item in coverage if str(item.get("status") or "") == "blocked")
    warning_action_count = sum(1 for item in coverage if str(item.get("status") or "") == "warning")
    passed_action_count = sum(1 for item in coverage if str(item.get("status") or "") == "passed")
    status = "blocked" if blocked_action_count else ("warning" if warning_action_count else "passed")
    notes = _clean_text_list(
        [
            f"{item.get('action') or 'action'}: {item.get('summary') or item.get('status') or 'unknown'}"
            for item in coverage
        ]
    )
    recommendations = _clean_text_list(
        [
            *(
                ["先补齐 release write actions 的覆盖，再推进远端发布或 CI 接入。"]
                if blocked_action_count > 0
                else []
            ),
            *(
                ["先清理 token rotation hygiene，再把当前 manifest 当成正式发布凭据。"]
                if warning_action_count > 0
                else []
            ),
            *[
                recommendation
                for item in coverage
                for recommendation in list(item.get("recommendations") or [])
            ],
        ]
    )
    summary = (
        f"actions={len(normalized_actions)} / "
        f"passed={passed_action_count} / "
        f"warning={warning_action_count} / "
        f"blocked={blocked_action_count}"
    )

    return {
        "schema_version": RELEASE_REQUEST_AUTH_ROTATION_AUDIT_SCHEMA_VERSION,
        "status": status,
        "summary": summary,
        "auth_path": _relative_to_root(resolved_auth_path, resolved_project_root),
        "manifest_exists": resolved_auth_path.exists(),
        "target_channel": normalized_target_channel,
        "target_environment": normalized_target_environment,
        "actions": normalized_actions,
        "action_count": len(normalized_actions),
        "passed_action_count": passed_action_count,
        "warning_action_count": warning_action_count,
        "blocked_action_count": blocked_action_count,
        "report_path": _relative_to_root(resolved_report_path, resolved_runtime_root),
        "report_exists": resolved_report_path.exists(),
        "coverage": coverage,
        "notes": notes,
        "recommendations": recommendations,
    }


def build_release_request_auth_identity_audit(
    project_root: str | Path,
    runtime_root: Optional[str | Path] = None,
    *,
    target_channel: str = "",
    target_environment: str = "",
    actions: Optional[List[str]] = None,
    auth_path: str = "",
    identity_path: str = "",
) -> Dict[str, Any]:
    resolved_project_root = Path(project_root).resolve()
    resolved_runtime_root = Path(runtime_root or Path.cwd()).resolve()
    normalized_target_channel = str(target_channel or "").strip().lower() or "staging"
    normalized_target_environment = str(target_environment or "").strip() or _default_target_environment(normalized_target_channel)
    normalized_actions = _clean_text_list(actions) or list(_DEFAULT_RELEASE_WRITE_ACTIONS)
    report_relative_path = default_release_request_auth_identity_audit_report_path(target_channel=normalized_target_channel)
    resolved_auth_path = _resolve_project_path(
        resolved_project_root,
        auth_path or DEFAULT_RELEASE_REQUEST_AUTH_PATH,
    )
    resolved_identity_path = _resolve_project_path(
        resolved_project_root,
        identity_path or DEFAULT_RELEASE_IDENTITY_REGISTRY_PATH,
    )
    resolved_report_path = _resolve_runtime_path(resolved_runtime_root, report_relative_path)
    layout_validator = ProjectLayoutValidator(project_root=resolved_project_root, runtime_root=resolved_runtime_root)
    identity_boundary = load_release_identity_boundary_profile(
        resolved_project_root,
        target_channel=normalized_target_channel,
        target_environment=normalized_target_environment,
    )
    handoff_state = _build_release_request_auth_identity_handoff_state(
        resolved_project_root,
        runtime_root=resolved_runtime_root,
        target_channel=normalized_target_channel,
        target_environment=normalized_target_environment,
        actions=normalized_actions,
        identity_boundary=identity_boundary,
    )

    audit = {
        "schema_version": RELEASE_REQUEST_AUTH_IDENTITY_AUDIT_SCHEMA_VERSION,
        "status": "warning",
        "summary": "",
        "auth_path": _relative_to_root(resolved_auth_path, resolved_project_root),
        "manifest_exists": resolved_auth_path.exists(),
        "identity_path": _relative_to_root(resolved_identity_path, resolved_project_root),
        "identity_registry_exists": resolved_identity_path.exists(),
        "target_channel": normalized_target_channel,
        "target_environment": normalized_target_environment,
        "identity_boundary_profile_id": str(identity_boundary.get("profile_id") or "").strip(),
        "identity_boundary_status": str(identity_boundary.get("status") or "warning").strip(),
        "identity_provider_mode": str(identity_boundary.get("provider_mode") or "").strip(),
        "identity_provider_id": str(identity_boundary.get("provider_id") or "").strip(),
        "identity_session_required": bool(identity_boundary.get("session_required")),
        "identity_max_session_age_hours": max(int(identity_boundary.get("max_session_age_hours") or 0), 0),
        "identity_session_backend": str(identity_boundary.get("session_backend") or "").strip(),
        "identity_secret_rotation_required": bool(identity_boundary.get("secret_rotation_required")),
        "identity_secret_backend": str(identity_boundary.get("secret_backend") or "").strip(),
        "identity_rotation_owner": str(identity_boundary.get("rotation_owner") or "").strip(),
        "identity_rotation_window_days": max(int(identity_boundary.get("rotation_window_days") or 0), 0),
        "actions": normalized_actions,
        "action_count": len(normalized_actions),
        "passed_action_count": 0,
        "warning_action_count": 0,
        "blocked_action_count": 0,
        "issuer_count": 0,
        "active_issuer_count": 0,
        "scoped_issuer_count": 0,
        "session_required_issuer_count": 0,
        "session_windowed_issuer_count": 0,
        "unbound_issuer_count": 0,
        "duplicate_issuer_id_count": 0,
        "duplicate_issuer_ids": [],
        "matching_registered_issuer_token_count": 0,
        "matching_unknown_issuer_token_count": 0,
        "matching_inactive_issuer_token_count": 0,
        "matching_unscoped_issuer_token_count": 0,
        "matching_subject_out_of_registry_count": 0,
        "matching_stale_session_token_count": 0,
        "matching_session_token_count": 0,
        "release_issuers_without_session_requirement_count": 0,
        "release_issuers_without_session_window_count": 0,
        "report_path": _relative_to_root(resolved_report_path, resolved_runtime_root),
        "report_exists": resolved_report_path.exists(),
        "coverage": [],
        **handoff_state,
        "notes": [],
        "recommendations": [],
    }

    if resolved_identity_path.exists():
        identity_layout_result = layout_validator.validate_managed_path(
            resolved_identity_path,
            "release_identity_registry_manifest",
        )
        if not identity_layout_result["passed"]:
            message = (
                "; ".join(issue["message"] for issue in identity_layout_result["issues"])
                or "invalid release identity registry path"
            )
            audit["status"] = "blocked"
            audit["summary"] = message
            audit["notes"] = [message]
            audit["recommendations"] = ["将 release identity registry 固定落到 deployment/release_identity_registry.json。"]
            return audit
        identity_payload, identity_reason = _load_manifest(resolved_identity_path)
        if identity_reason:
            audit["status"] = "blocked"
            audit["summary"] = identity_reason
            audit["notes"] = [identity_reason]
            audit["recommendations"] = ["修复 release_identity_registry manifest 的 JSON 格式或字段结构。"]
            return audit
        identity_issuers = _normalize_identity_issuers(identity_payload.get("issuers"))
    else:
        identity_issuers = []

    coverage = [
        build_release_request_auth_posture(
            resolved_project_root,
            runtime_root=resolved_runtime_root,
            action=action,
            target_channel=normalized_target_channel,
            target_environment=normalized_target_environment,
            auth_path=auth_path,
            identity_path=identity_path,
        )
        for action in normalized_actions
    ]
    action_statuses = [
        _build_release_request_auth_identity_action_status(item, target_channel=normalized_target_channel)
        for item in coverage
    ]
    audit["coverage"] = coverage
    audit["issuer_count"] = len(identity_issuers)
    audit["active_issuer_count"] = sum(
        1 for issuer in identity_issuers if str(issuer.get("status") or "").strip().lower() in _ACTIVE_ISSUER_STATUSES
    )

    issuer_id_counts: Dict[str, int] = {}
    scoped_issuers: List[Dict[str, Any]] = []
    for issuer in identity_issuers:
        issuer_id = str(issuer.get("issuer_id") or "").strip()
        if issuer_id:
            issuer_id_counts[issuer_id] = issuer_id_counts.get(issuer_id, 0) + 1
        status = str(issuer.get("status") or "").strip().lower()
        if status not in _ACTIVE_ISSUER_STATUSES:
            continue
        channels = list(issuer.get("channels") or [])
        target_environments = list(issuer.get("target_environments") or [])
        if (channels and normalized_target_channel not in channels) or (
            target_environments and normalized_target_environment not in target_environments
        ):
            continue
        scoped_issuers.append(dict(issuer))

    duplicate_issuer_ids = [
        issuer_id
        for issuer_id, count in issuer_id_counts.items()
        if issuer_id and count > 1
    ]
    audit["duplicate_issuer_ids"] = duplicate_issuer_ids
    audit["duplicate_issuer_id_count"] = len(duplicate_issuer_ids)
    audit["scoped_issuer_count"] = len(scoped_issuers)
    audit["session_required_issuer_count"] = sum(1 for issuer in scoped_issuers if bool(issuer.get("session_required")))
    audit["session_windowed_issuer_count"] = sum(
        1 for issuer in scoped_issuers if max(int(issuer.get("max_session_age_hours") or 0), 0) > 0
    )
    audit["unbound_issuer_count"] = sum(1 for issuer in scoped_issuers if not list(issuer.get("subject_actor_ids") or []))
    if normalized_target_channel == "release":
        audit["release_issuers_without_session_requirement_count"] = sum(
            1 for issuer in scoped_issuers if not bool(issuer.get("session_required"))
        )
        audit["release_issuers_without_session_window_count"] = sum(
            1 for issuer in scoped_issuers if max(int(issuer.get("max_session_age_hours") or 0), 0) <= 0
        )

    registry_warning = bool(
        not audit["identity_registry_exists"]
        or audit["scoped_issuer_count"] <= 0
        or audit["duplicate_issuer_id_count"] > 0
        or audit["unbound_issuer_count"] > 0
        or audit["release_issuers_without_session_requirement_count"] > 0
        or audit["release_issuers_without_session_window_count"] > 0
    )
    if registry_warning:
        action_statuses = [
            "warning" if item == "passed" else item
            for item in action_statuses
        ]
    audit["passed_action_count"] = sum(1 for item in action_statuses if item == "passed")
    audit["warning_action_count"] = sum(1 for item in action_statuses if item == "warning")
    audit["blocked_action_count"] = sum(1 for item in action_statuses if item == "blocked")

    for field in (
        "matching_registered_issuer_token_count",
        "matching_unknown_issuer_token_count",
        "matching_inactive_issuer_token_count",
        "matching_unscoped_issuer_token_count",
        "matching_subject_out_of_registry_count",
        "matching_stale_session_token_count",
        "matching_session_token_count",
    ):
        audit[field] = sum(max(int(item.get(field) or 0), 0) for item in coverage)

    notes = _clean_text_list(
        [
            *[
                f"{item.get('action') or 'action'}={status}"
                for item, status in zip(coverage, action_statuses)
            ],
            *(
                ["identity registry is not configured"]
                if not audit["identity_registry_exists"]
                else []
            ),
            *(
                [f"duplicate issuer_ids={', '.join(audit['duplicate_issuer_ids'])}"]
                if audit["duplicate_issuer_id_count"] > 0
                else []
            ),
            *(
                [f"scoped issuers={audit['scoped_issuer_count']} / active issuers={audit['active_issuer_count']}"]
                if audit["identity_registry_exists"]
                else []
            ),
            *(
                [f"unbound issuers={audit['unbound_issuer_count']}"]
                if audit["unbound_issuer_count"] > 0
                else []
            ),
            *(
                [f"unknown issuer tokens={audit['matching_unknown_issuer_token_count']}"]
                if audit["matching_unknown_issuer_token_count"] > 0
                else []
            ),
            *(
                [f"inactive issuer tokens={audit['matching_inactive_issuer_token_count']}"]
                if audit["matching_inactive_issuer_token_count"] > 0
                else []
            ),
            *(
                [f"out-of-scope issuer tokens={audit['matching_unscoped_issuer_token_count']}"]
                if audit["matching_unscoped_issuer_token_count"] > 0
                else []
            ),
            *(
                [f"issuer subject mismatches={audit['matching_subject_out_of_registry_count']}"]
                if audit["matching_subject_out_of_registry_count"] > 0
                else []
            ),
            *(
                [f"stale issuer-backed sessions={audit['matching_stale_session_token_count']}"]
                if audit["matching_stale_session_token_count"] > 0
                else []
            ),
            *(
                [f"release issuers without session_required={audit['release_issuers_without_session_requirement_count']}"]
                if audit["release_issuers_without_session_requirement_count"] > 0
                else []
            ),
            *(
                [f"release issuers without max_session_age_hours={audit['release_issuers_without_session_window_count']}"]
                if audit["release_issuers_without_session_window_count"] > 0
                else []
            ),
            *(
                [f"identity handoff={audit['identity_handoff_status']}"]
                if str(audit.get("identity_handoff_status") or "").strip()
                else []
            ),
        ]
    )

    recommendations = _clean_text_list(
        [
            *(
                ["先为每条高风险写 action 补齐 matching token，再把 identity registry 当成正式发布身份边界。"]
                if audit["blocked_action_count"] > 0
                else []
            ),
            *(
                ["补齐 issuer registry 覆盖、subject actor 绑定和 session 策略，再把当前 identity registry 当成正式发布证据。"]
                if audit["warning_action_count"] > 0
                else []
            ),
            *(
                ["为 release 渠道补 deployment/release_identity_registry.json，把 issued_by 绑定到真实身份主体。"]
                if not audit["identity_registry_exists"]
                else []
            ),
            *(
                ["至少为当前 channel/environment 维护一枚 active issuer。"]
                if audit["identity_registry_exists"] and audit["scoped_issuer_count"] <= 0
                else []
            ),
            *(
                ["清理重复 issuer_id，确保 issuer registry 能唯一标识每个身份主体。"]
                if audit["duplicate_issuer_id_count"] > 0
                else []
            ),
            *(
                ["为 scoped issuer 补齐 subject_actor_ids，把 issuer 和 executed_by 绑定到同一主体。"]
                if audit["unbound_issuer_count"] > 0
                else []
            ),
            *(
                ["把 matching token 的 issued_by 全部登记到 active issuer，避免 token 漂离 registry。"]
                if audit["matching_unknown_issuer_token_count"] > 0
                else []
            ),
            *(
                ["恢复或轮换 inactive issuer，避免高风险写操作继续绑定失效身份主体。"]
                if audit["matching_inactive_issuer_token_count"] > 0
                else []
            ),
            *(
                ["补齐 issuer 的 channels / target_environments，确保 registry scope 和 token scope 一致。"]
                if audit["matching_unscoped_issuer_token_count"] > 0
                else []
            ),
            *(
                ["把 token actor_ids 和 issuer subject_actor_ids 对齐，避免 issuer subject 漏绑或越权。"]
                if audit["matching_subject_out_of_registry_count"] > 0
                else []
            ),
            *(
                ["轮换过旧 session，并给 scoped issuer 配置可执行的 max_session_age_hours。"]
                if audit["matching_stale_session_token_count"] > 0
                else []
            ),
            *(
                ["为 release scoped issuer 打开 session_required，避免正式发布 issuer 仍允许无 session 凭据。"]
                if audit["release_issuers_without_session_requirement_count"] > 0
                else []
            ),
            *(
                ["为 release scoped issuer 配置正数 max_session_age_hours，避免 session 永久有效。"]
                if audit["release_issuers_without_session_window_count"] > 0
                else []
            ),
            *(
                ["运行 python tools/export_release_request_auth_identity_handoff.py，生成面向外部 identity/session/secret rotation 的 redacted handoff 包。"]
                if audit["identity_handoff_status"] == "warning"
                and bool(audit.get("identity_handoff_required"))
                else []
            ),
        ]
    )

    audit["status"] = (
        "blocked"
        if audit["blocked_action_count"] > 0
        else ("warning" if audit["warning_action_count"] > 0 else "passed")
    )
    audit["summary"] = (
        f"actions={audit['action_count']} / "
        f"passed={audit['passed_action_count']} / "
        f"warning={audit['warning_action_count']} / "
        f"blocked={audit['blocked_action_count']} / "
        f"scoped_issuers={audit['scoped_issuer_count']}"
    )
    audit["notes"] = notes
    audit["recommendations"] = recommendations
    return audit


def export_release_request_auth_posture_report(
    project_root: str | Path,
    runtime_root: Optional[str | Path] = None,
    *,
    action: str,
    target_channel: str = "",
    target_environment: str = "",
    auth_path: str = "",
    output_path: str = "",
) -> Dict[str, Any]:
    resolved_project_root = Path(project_root).resolve()
    resolved_runtime_root = Path(runtime_root or Path.cwd()).resolve()
    posture = build_release_request_auth_posture(
        resolved_project_root,
        runtime_root=resolved_runtime_root,
        action=action,
        target_channel=target_channel,
        target_environment=target_environment,
        auth_path=auth_path,
    )
    resolved_report_path = _resolve_runtime_path(
        resolved_runtime_root,
        output_path or str(posture.get("report_path") or ""),
    )
    report_payload = dict(posture)
    report_payload["generated_at"] = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    report_payload["manifest_path"] = str(posture.get("manifest_path") or posture.get("path") or "")
    report_payload["report_path"] = _relative_to_root(resolved_report_path, resolved_runtime_root)
    report_payload["report_exists"] = True
    _write_json(resolved_report_path, report_payload)
    return report_payload


def export_release_request_auth_identity_audit_report(
    project_root: str | Path,
    runtime_root: Optional[str | Path] = None,
    *,
    target_channel: str = "",
    target_environment: str = "",
    actions: Optional[List[str]] = None,
    auth_path: str = "",
    identity_path: str = "",
    output_path: str = "",
) -> Dict[str, Any]:
    resolved_project_root = Path(project_root).resolve()
    resolved_runtime_root = Path(runtime_root or Path.cwd()).resolve()
    normalized_target_channel = str(target_channel or "").strip().lower() or "staging"
    normalized_target_environment = str(target_environment or "").strip() or _default_target_environment(normalized_target_channel)
    normalized_actions = _clean_text_list(actions) or list(_DEFAULT_RELEASE_WRITE_ACTIONS)
    for action_name in normalized_actions:
        export_release_request_auth_posture_report(
            resolved_project_root,
            runtime_root=resolved_runtime_root,
            action=action_name,
            target_channel=normalized_target_channel,
            target_environment=normalized_target_environment,
            auth_path=auth_path,
        )
    audit = build_release_request_auth_identity_audit(
        resolved_project_root,
        runtime_root=resolved_runtime_root,
        target_channel=normalized_target_channel,
        target_environment=normalized_target_environment,
        actions=normalized_actions,
        auth_path=auth_path,
        identity_path=identity_path,
    )
    resolved_report_path = _resolve_runtime_path(
        resolved_runtime_root,
        output_path or str(audit.get("report_path") or ""),
    )
    report_payload = dict(audit)
    report_payload["generated_at"] = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    report_payload["report_path"] = _relative_to_root(resolved_report_path, resolved_runtime_root)
    report_payload["report_exists"] = True
    _write_json(resolved_report_path, report_payload)
    return report_payload


def export_release_request_auth_identity_handoff(
    project_root: str | Path,
    runtime_root: Optional[str | Path] = None,
    *,
    target_channel: str = "",
    target_environment: str = "",
    actions: Optional[List[str]] = None,
    auth_path: str = "",
    identity_path: str = "",
    release_manifest_path: str = "",
) -> Dict[str, Any]:
    resolved_project_root = Path(project_root).resolve()
    resolved_runtime_root = Path(runtime_root or Path.cwd()).resolve()
    normalized_target_channel = str(target_channel or "").strip().lower() or "staging"
    normalized_target_environment = str(target_environment or "").strip() or _default_target_environment(normalized_target_channel)
    normalized_actions = _clean_text_list(actions) or list(_DEFAULT_RELEASE_WRITE_ACTIONS)

    posture_reports: Dict[str, Dict[str, Any]] = {}
    for action_name in normalized_actions:
        posture_reports[action_name] = export_release_request_auth_posture_report(
            resolved_project_root,
            runtime_root=resolved_runtime_root,
            action=action_name,
            target_channel=normalized_target_channel,
            target_environment=normalized_target_environment,
            auth_path=auth_path,
        )

    rotation_report = export_release_request_auth_rotation_audit_report(
        resolved_project_root,
        runtime_root=resolved_runtime_root,
        target_channel=normalized_target_channel,
        target_environment=normalized_target_environment,
        actions=normalized_actions,
        auth_path=auth_path,
    )
    identity_report = export_release_request_auth_identity_audit_report(
        resolved_project_root,
        runtime_root=resolved_runtime_root,
        target_channel=normalized_target_channel,
        target_environment=normalized_target_environment,
        actions=normalized_actions,
        auth_path=auth_path,
        identity_path=identity_path,
    )

    if not bool(identity_report.get("identity_handoff_required")):
        return identity_report
    if str(identity_report.get("identity_handoff_config_status") or "").strip().lower() != "passed":
        return identity_report

    resolved_handoff_dir = _resolve_runtime_path(
        resolved_runtime_root,
        str(identity_report.get("identity_handoff_dir") or ""),
    )
    if resolved_handoff_dir.exists():
        shutil.rmtree(resolved_handoff_dir, ignore_errors=True)
    resolved_handoff_dir.mkdir(parents=True, exist_ok=True)

    audits_dir = resolved_handoff_dir / "audits"
    deployment_dir = resolved_handoff_dir / "deployment"
    metadata_dir = resolved_handoff_dir / "metadata"
    copied_artifacts: Dict[str, str] = {}

    for action_name, report in posture_reports.items():
        source = _resolve_runtime_path(
            resolved_runtime_root,
            str(report.get("report_path") or ""),
        )
        if not source.exists():
            continue
        destination = audits_dir / source.name
        _copy_file(source, destination)
        copied_artifacts[f"posture_{action_name}"] = _relative_to_root(destination, resolved_handoff_dir)

    for artifact_id, report in (
        ("rotation_audit", rotation_report),
        ("identity_audit", identity_report),
    ):
        source = _resolve_runtime_path(
            resolved_runtime_root,
            str(report.get("report_path") or ""),
        )
        if not source.exists():
            continue
        destination = audits_dir / source.name
        _copy_file(source, destination)
        copied_artifacts[artifact_id] = _relative_to_root(destination, resolved_handoff_dir)

    for source_path, destination_name, artifact_id in (
        (resolved_project_root / default_release_identity_boundary_path(), "release_identity_boundary.json", "identity_boundary_manifest"),
        (_resolve_project_path(resolved_project_root, identity_path or DEFAULT_RELEASE_IDENTITY_REGISTRY_PATH), "release_identity_registry.json", "identity_registry_manifest"),
    ):
        if not source_path.exists():
            continue
        destination = deployment_dir / destination_name
        _copy_file(source_path, destination)
        copied_artifacts[artifact_id] = _relative_to_root(destination, resolved_handoff_dir)

    release_binding: Dict[str, Any] = {}
    if str(release_manifest_path or "").strip():
        resolved_release_manifest_path = _resolve_runtime_path(resolved_runtime_root, release_manifest_path)
        release_manifest_payload, release_manifest_reason = _load_manifest(resolved_release_manifest_path)
        if not release_manifest_reason and release_manifest_payload:
            destination = metadata_dir / "release_manifest.json"
            _write_json(destination, release_manifest_payload)
            copied_artifacts["release_manifest"] = _relative_to_root(destination, resolved_handoff_dir)
            release_binding = {
                "build_id": str(release_manifest_payload.get("build_id") or "").strip(),
                "version": str(release_manifest_payload.get("version") or "").strip(),
                "channel": str(release_manifest_payload.get("channel") or "").strip(),
                "manifest_path": str(release_manifest_path or "").strip(),
            }

    instructions_path = _resolve_runtime_path(
        resolved_runtime_root,
        str(identity_report.get("identity_handoff_instructions_path") or ""),
    )
    _write_text(
        instructions_path,
        "\n".join(
            [
                "# Identity Boundary Handoff",
                "",
                f"- Target: {normalized_target_channel} -> {normalized_target_environment}",
                f"- Provider: {identity_report.get('identity_provider_mode') or '-'} / {identity_report.get('identity_provider_id') or '-'}",
                f"- Session Policy: required={bool(identity_report.get('identity_session_required'))} / max_age_hours={int(identity_report.get('identity_max_session_age_hours') or 0)} / backend={identity_report.get('identity_session_backend') or '-'}",
                f"- Secret Rotation: required={bool(identity_report.get('identity_secret_rotation_required'))} / backend={identity_report.get('identity_secret_backend') or '-'} / owner={identity_report.get('identity_rotation_owner') or '-'} / window_days={int(identity_report.get('identity_rotation_window_days') or 0)}",
                f"- External Handoff: mode={identity_report.get('identity_handoff_mode') or '-'} / target={identity_report.get('identity_handoff_target_id') or '-'} / owner={identity_report.get('identity_handoff_owner') or '-'}",
                "",
                "请使用 audits/ 下的 redacted posture / rotation / identity 审计结果，完成外部 identity provider、session policy 和 secret rotation 接入。",
                "deployment/ 下的 manifest 仅提供边界和 issuer scope，不应把 release_request_auth token manifest 带出仓库。",
            ]
        )
        + "\n",
    )

    manifest_path = _resolve_runtime_path(
        resolved_runtime_root,
        str(identity_report.get("identity_handoff_manifest_path") or ""),
    )
    _write_json(
        manifest_path,
        {
            "schema_version": RELEASE_REQUEST_AUTH_IDENTITY_HANDOFF_SCHEMA_VERSION,
            "generated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
            "target_channel": normalized_target_channel,
            "target_environment": normalized_target_environment,
            "actions": normalized_actions,
            "identity_boundary_profile_id": str(identity_report.get("identity_boundary_profile_id") or "").strip(),
            "provider_mode": str(identity_report.get("identity_provider_mode") or "").strip(),
            "provider_id": str(identity_report.get("identity_provider_id") or "").strip(),
            "session_required": bool(identity_report.get("identity_session_required")),
            "max_session_age_hours": max(int(identity_report.get("identity_max_session_age_hours") or 0), 0),
            "session_backend": str(identity_report.get("identity_session_backend") or "").strip(),
            "secret_rotation_required": bool(identity_report.get("identity_secret_rotation_required")),
            "secret_backend": str(identity_report.get("identity_secret_backend") or "").strip(),
            "rotation_owner": str(identity_report.get("identity_rotation_owner") or "").strip(),
            "rotation_window_days": max(int(identity_report.get("identity_rotation_window_days") or 0), 0),
            "external_handoff_mode": str(identity_report.get("identity_handoff_mode") or "").strip(),
            "external_handoff_target_id": str(identity_report.get("identity_handoff_target_id") or "").strip(),
            "external_handoff_owner": str(identity_report.get("identity_handoff_owner") or "").strip(),
            "artifacts": {
                "instructions_path": _relative_to_root(instructions_path, resolved_handoff_dir),
                **copied_artifacts,
            },
            "release_binding": release_binding,
        },
    )

    return export_release_request_auth_identity_audit_report(
        resolved_project_root,
        runtime_root=resolved_runtime_root,
        target_channel=normalized_target_channel,
        target_environment=normalized_target_environment,
        actions=normalized_actions,
        auth_path=auth_path,
        identity_path=identity_path,
    )


def export_release_request_auth_rotation_audit_report(
    project_root: str | Path,
    runtime_root: Optional[str | Path] = None,
    *,
    target_channel: str = "",
    target_environment: str = "",
    actions: Optional[List[str]] = None,
    auth_path: str = "",
    output_path: str = "",
) -> Dict[str, Any]:
    resolved_project_root = Path(project_root).resolve()
    resolved_runtime_root = Path(runtime_root or Path.cwd()).resolve()
    normalized_target_channel = str(target_channel or "").strip().lower() or "staging"
    normalized_target_environment = str(target_environment or "").strip() or _default_target_environment(normalized_target_channel)
    normalized_actions = _clean_text_list(actions) or list(_DEFAULT_RELEASE_WRITE_ACTIONS)
    for action_name in normalized_actions:
        export_release_request_auth_posture_report(
            resolved_project_root,
            runtime_root=resolved_runtime_root,
            action=action_name,
            target_channel=normalized_target_channel,
            target_environment=normalized_target_environment,
            auth_path=auth_path,
        )
    audit = build_release_request_auth_rotation_audit(
        resolved_project_root,
        runtime_root=resolved_runtime_root,
        target_channel=normalized_target_channel,
        target_environment=normalized_target_environment,
        actions=normalized_actions,
        auth_path=auth_path,
    )
    resolved_report_path = _resolve_runtime_path(
        resolved_runtime_root,
        output_path or str(audit.get("report_path") or ""),
    )
    report_payload = dict(audit)
    report_payload["generated_at"] = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    report_payload["report_path"] = _relative_to_root(resolved_report_path, resolved_runtime_root)
    report_payload["report_exists"] = True
    _write_json(resolved_report_path, report_payload)
    return report_payload


def build_release_request_token_spec(
    *,
    token_id: str,
    token_value: str,
    actions: Optional[List[str]] = None,
    channels: Optional[List[str]] = None,
    target_environments: Optional[List[str]] = None,
    actor_ids: Optional[List[str]] = None,
    expires_at: str = "",
    session_id: str = "",
    issued_by: str = "",
    issued_at: str = "",
) -> Dict[str, Any]:
    normalized_token_id = str(token_id or "").strip()
    normalized_token_value = str(token_value or "").strip()
    if not normalized_token_id:
        raise ValueError("token_id is required")
    if not normalized_token_value:
        raise ValueError("token_value is required")
    return {
        "token_id": normalized_token_id,
        "token_sha256": _hash_token(normalized_token_value),
        "actions": _clean_text_list(actions),
        "channels": _clean_channels(channels),
        "target_environments": _clean_text_list(target_environments),
        "actor_ids": _clean_text_list(actor_ids),
        "expires_at": str(expires_at or "").strip(),
        "session_id": str(session_id or "").strip(),
        "issued_by": str(issued_by or "").strip(),
        "issued_at": str(issued_at or "").strip(),
        "revoked": False,
    }


def build_release_request_auth_posture_report_lines(summary: Dict[str, Any] | None) -> List[str]:
    normalized = dict(summary or {})
    notes = list(normalized.get("notes") or [])
    recommendations = list(normalized.get("recommendations") or [])
    return [
        f"- Status: {normalized.get('status') or 'skipped'}",
        f"- Manifest Path: {normalized.get('manifest_path') or normalized.get('path') or '-'}",
        f"- Report Path: {normalized.get('report_path') or '-'} / exported={bool(normalized.get('report_exists'))}",
        f"- Action: {normalized.get('action') or '-'} / target={normalized.get('target_channel') or '-'} -> {normalized.get('target_environment') or '-'}",
        f"- Summary: {normalized.get('summary') or '-'}",
        f"- Manifest Exists: {bool(normalized.get('manifest_exists'))} / Local Bypass: {bool(normalized.get('allow_local_without_token'))} / Env Fallback: {bool(normalized.get('env_fallback_configured'))}",
        f"- Identity Registry: {normalized.get('identity_registry_path') or '-'} / exists={bool(normalized.get('identity_registry_exists'))} / issuers={normalized.get('issuer_count') or 0} / active={normalized.get('active_issuer_count') or 0}",
        (
            f"- Identity Boundary: profile={normalized.get('identity_boundary_profile_id') or '-'} / "
            f"status={normalized.get('identity_boundary_status') or '-'} / "
            f"handoff_required={bool(normalized.get('identity_handoff_required'))} / "
            f"handoff_config={normalized.get('identity_handoff_config_status') or '-'} / "
            f"handoff_target={normalized.get('identity_handoff_target_id') or '-'}"
        ),
        f"- Tokens: total={normalized.get('token_count') or 0} active={normalized.get('active_token_count') or 0} matching={normalized.get('matching_token_count') or 0} bound={normalized.get('matching_bound_token_count') or 0} unbound={normalized.get('matching_unbound_token_count') or 0} session_tracked={normalized.get('matching_session_token_count') or 0}",
        (
            f"- Rotation Hygiene: window={normalized.get('rotation_window_days') or _ROTATION_WARNING_WINDOW_DAYS}d / "
            f"missing_expiry={normalized.get('tokens_without_expiry_count') or 0} / "
            f"expiring_soon={normalized.get('tokens_expiring_soon_count') or 0} / "
            f"invalid_expiry={normalized.get('invalid_expiry_token_count') or 0} / "
            f"duplicate_ids={normalized.get('duplicate_token_id_count') or 0}"
        ),
        (
            f"- Session Hygiene: missing_session_id={normalized.get('tokens_without_session_id_count') or 0} / "
            f"missing_issued_by={normalized.get('tokens_without_issued_by_count') or 0} / "
            f"missing_issued_at={normalized.get('tokens_without_issued_at_count') or 0} / "
            f"invalid_issued_at={normalized.get('invalid_issued_at_token_count') or 0}"
        ),
        (
            f"- Identity Hygiene: registered={normalized.get('matching_registered_issuer_token_count') or 0} / "
            f"unknown={normalized.get('matching_unknown_issuer_token_count') or 0} / "
            f"inactive={normalized.get('matching_inactive_issuer_token_count') or 0} / "
            f"unscoped={normalized.get('matching_unscoped_issuer_token_count') or 0} / "
            f"subject_mismatch={normalized.get('matching_subject_out_of_registry_count') or 0} / "
            f"stale_session={normalized.get('matching_stale_session_token_count') or 0}"
        ),
        f"- Revoked: {normalized.get('revoked_token_count') or 0} / Expired: {normalized.get('expired_token_count') or 0}",
        f"- Matching Token IDs: {', '.join(list(normalized.get('matching_token_ids') or [])) or 'none'}",
        f"- Duplicate Token IDs: {', '.join(list(normalized.get('duplicate_token_ids') or [])) or 'none'}",
        f"- Notes: {', '.join(notes) or 'none'}",
        f"- Recommendations: {', '.join(recommendations) or 'none'}",
    ]


def build_release_request_auth_rotation_audit_report_lines(summary: Dict[str, Any] | None) -> List[str]:
    normalized = dict(summary or {})
    notes = list(normalized.get("notes") or [])
    recommendations = list(normalized.get("recommendations") or [])
    coverage = [
        f"{item.get('action') or 'action'}={item.get('status') or 'skipped'}"
        for item in list(normalized.get("coverage") or [])
        if isinstance(item, dict)
    ]
    return [
        f"- Status: {normalized.get('status') or 'skipped'}",
        f"- Auth Path: {normalized.get('auth_path') or '-'} / manifest_exists={bool(normalized.get('manifest_exists'))}",
        f"- Report Path: {normalized.get('report_path') or '-'} / exported={bool(normalized.get('report_exists'))}",
        f"- Target: {normalized.get('target_channel') or '-'} -> {normalized.get('target_environment') or '-'}",
        f"- Summary: {normalized.get('summary') or '-'}",
        f"- Actions: {', '.join(list(normalized.get('actions') or [])) or 'none'}",
        (
            f"- Coverage Counts: passed={normalized.get('passed_action_count') or 0} / "
            f"warning={normalized.get('warning_action_count') or 0} / "
            f"blocked={normalized.get('blocked_action_count') or 0}"
        ),
        f"- Coverage Statuses: {', '.join(coverage) or 'none'}",
        f"- Notes: {', '.join(notes) or 'none'}",
        f"- Recommendations: {', '.join(recommendations) or 'none'}",
    ]


def build_release_request_auth_identity_audit_report_lines(summary: Dict[str, Any] | None) -> List[str]:
    normalized = dict(summary or {})
    notes = list(normalized.get("notes") or [])
    recommendations = list(normalized.get("recommendations") or [])
    coverage = [
        f"{item.get('action') or 'action'}={_build_release_request_auth_identity_action_status(item, target_channel=str(normalized.get('target_channel') or '').strip().lower() or 'staging')}"
        for item in list(normalized.get("coverage") or [])
        if isinstance(item, dict)
    ]
    return [
        f"- Status: {normalized.get('status') or 'skipped'}",
        f"- Auth Path: {normalized.get('auth_path') or '-'} / manifest_exists={bool(normalized.get('manifest_exists'))}",
        f"- Identity Path: {normalized.get('identity_path') or '-'} / exists={bool(normalized.get('identity_registry_exists'))}",
        f"- Report Path: {normalized.get('report_path') or '-'} / exported={bool(normalized.get('report_exists'))}",
        f"- Target: {normalized.get('target_channel') or '-'} -> {normalized.get('target_environment') or '-'}",
        f"- Summary: {normalized.get('summary') or '-'}",
        f"- Actions: {', '.join(list(normalized.get('actions') or [])) or 'none'}",
        (
            f"- Coverage Counts: passed={normalized.get('passed_action_count') or 0} / "
            f"warning={normalized.get('warning_action_count') or 0} / "
            f"blocked={normalized.get('blocked_action_count') or 0}"
        ),
        f"- Coverage Statuses: {', '.join(coverage) or 'none'}",
        (
            f"- Issuers: total={normalized.get('issuer_count') or 0} / "
            f"active={normalized.get('active_issuer_count') or 0} / "
            f"scoped={normalized.get('scoped_issuer_count') or 0} / "
            f"session_required={normalized.get('session_required_issuer_count') or 0} / "
            f"session_windowed={normalized.get('session_windowed_issuer_count') or 0} / "
            f"unbound={normalized.get('unbound_issuer_count') or 0} / "
            f"duplicate_ids={normalized.get('duplicate_issuer_id_count') or 0}"
        ),
        (
            f"- Token Mapping: registered={normalized.get('matching_registered_issuer_token_count') or 0} / "
            f"unknown={normalized.get('matching_unknown_issuer_token_count') or 0} / "
            f"inactive={normalized.get('matching_inactive_issuer_token_count') or 0} / "
            f"out_of_scope={normalized.get('matching_unscoped_issuer_token_count') or 0} / "
            f"subject_mismatch={normalized.get('matching_subject_out_of_registry_count') or 0} / "
            f"stale_session={normalized.get('matching_stale_session_token_count') or 0}"
        ),
        (
            f"- Release Session Policy: missing_session_required={normalized.get('release_issuers_without_session_requirement_count') or 0} / "
            f"missing_session_window={normalized.get('release_issuers_without_session_window_count') or 0} / "
            f"tracked_sessions={normalized.get('matching_session_token_count') or 0}"
        ),
        (
            f"- Identity Handoff: status={normalized.get('identity_handoff_status') or '-'} / "
            f"required={bool(normalized.get('identity_handoff_required'))} / "
            f"target={normalized.get('identity_handoff_target_id') or '-'} / "
            f"owner={normalized.get('identity_handoff_owner') or '-'} / "
            f"manifest={normalized.get('identity_handoff_manifest_path') or '-'} / "
            f"exported={bool(normalized.get('identity_handoff_manifest_exists'))}"
        ),
        f"- Duplicate Issuer IDs: {', '.join(list(normalized.get('duplicate_issuer_ids') or [])) or 'none'}",
        f"- Notes: {', '.join(notes) or 'none'}",
        f"- Recommendations: {', '.join(recommendations) or 'none'}",
    ]


def _normalize_manifest_tokens(items: Any) -> List[Dict[str, Any]]:
    tokens: List[Dict[str, Any]] = []
    for index, raw_item in enumerate(list(items or []), start=1):
        if not isinstance(raw_item, dict):
            continue
        token_sha256 = str(raw_item.get("token_sha256") or "").strip().lower()
        if len(token_sha256) != 64 or any(char not in "0123456789abcdef" for char in token_sha256):
            continue
        tokens.append({
            "token_id": str(raw_item.get("token_id") or f"token_{index}").strip() or f"token_{index}",
            "token_sha256": token_sha256,
            "token_source": "manifest",
            "actions": _clean_text_list(raw_item.get("actions")),
            "channels": _clean_channels(raw_item.get("channels")),
            "target_environments": _clean_text_list(raw_item.get("target_environments")),
            "actor_ids": _clean_text_list(raw_item.get("actor_ids")),
            "revoked": bool(raw_item.get("revoked")),
            "expires_at": str(raw_item.get("expires_at") or "").strip(),
            "session_id": str(raw_item.get("session_id") or "").strip(),
            "issued_by": str(raw_item.get("issued_by") or "").strip(),
            "issued_at": str(raw_item.get("issued_at") or "").strip(),
        })
    return tokens


def _normalize_identity_issuers(items: Any) -> List[Dict[str, Any]]:
    issuers: List[Dict[str, Any]] = []
    for index, raw_item in enumerate(list(items or []), start=1):
        if not isinstance(raw_item, dict):
            continue
        issuer_id = str(raw_item.get("issuer_id") or f"issuer_{index}").strip() or f"issuer_{index}"
        status = str(raw_item.get("status") or "active").strip().lower() or "active"
        issuers.append({
            "issuer_id": issuer_id,
            "status": status,
            "channels": _clean_channels(raw_item.get("channels")),
            "target_environments": _clean_text_list(raw_item.get("target_environments")),
            "subject_actor_ids": _clean_text_list(raw_item.get("subject_actor_ids")),
            "session_required": bool(raw_item.get("session_required")),
            "max_session_age_hours": _coerce_nonnegative_int(raw_item.get("max_session_age_hours")),
        })
    return issuers


def _match_identity_issuer_for_request(
    identity_issuers: List[Dict[str, Any]],
    *,
    issued_by: str,
    target_channel: str,
    target_environment: str,
    actor_id: str,
    session_tracked: bool,
    issued_at: str,
    token_id: str,
) -> tuple[str, Dict[str, Any]]:
    normalized_issued_by = str(issued_by or "").strip()
    if not normalized_issued_by:
        return f"release write token {token_id} is missing issued_by for identity registry", {}

    matching_issuers = [
        issuer for issuer in identity_issuers
        if str(issuer.get("issuer_id") or "").strip() == normalized_issued_by
    ]
    if not matching_issuers:
        return f"release write token {token_id} issuer={normalized_issued_by} is not registered", {}

    issued_at_dt = _parse_iso_datetime(issued_at)
    now = datetime.now(timezone.utc)
    mismatch_reasons: List[str] = []
    for issuer in matching_issuers:
        status = str(issuer.get("status") or "").strip().lower()
        if status not in _ACTIVE_ISSUER_STATUSES:
            mismatch_reasons.append(
                f"release write token {token_id} issuer={normalized_issued_by} is not active"
            )
            continue
        channels = list(issuer.get("channels") or [])
        if channels and target_channel not in channels:
            mismatch_reasons.append(
                f"release write token {token_id} issuer={normalized_issued_by} is not allowed for target_channel={target_channel}"
            )
            continue
        target_environments = list(issuer.get("target_environments") or [])
        if target_environments and target_environment not in target_environments:
            mismatch_reasons.append(
                f"release write token {token_id} issuer={normalized_issued_by} is not allowed for target_environment={target_environment or '-'}"
            )
            continue
        subject_actor_ids = list(issuer.get("subject_actor_ids") or [])
        if subject_actor_ids and actor_id not in subject_actor_ids:
            mismatch_reasons.append(
                f"release write token {token_id} issuer={normalized_issued_by} is not allowed for executed_by={actor_id or '-'}"
            )
            continue
        if bool(issuer.get("session_required")):
            if not session_tracked or issued_at_dt is None:
                mismatch_reasons.append(
                    f"release write token {token_id} issuer={normalized_issued_by} requires session-tracked metadata"
                )
                continue
            max_session_age_hours = max(int(issuer.get("max_session_age_hours") or 0), 0)
            if max_session_age_hours > 0 and issued_at_dt < now - timedelta(hours=max_session_age_hours):
                mismatch_reasons.append(
                    f"release write token {token_id} issuer={normalized_issued_by} session is older than {max_session_age_hours}h"
                )
                continue
        return "", issuer
    return mismatch_reasons[0] if mismatch_reasons else f"release write token {token_id} issuer={normalized_issued_by} is not registered", {}


def _evaluate_identity_issuer_posture(
    token_spec: Dict[str, Any],
    *,
    identity_issuers: List[Dict[str, Any]],
    target_channel: str,
    target_environment: str,
    issued_at: Optional[datetime],
    session_tracked: bool,
    now: datetime,
) -> Dict[str, Any]:
    issued_by = str(token_spec.get("issued_by") or "").strip()
    if not identity_issuers:
        return {"status": "missing_registry"}
    if not issued_by:
        return {"status": "unknown"}

    matching_issuers = [
        issuer for issuer in identity_issuers
        if str(issuer.get("issuer_id") or "").strip() == issued_by
    ]
    if not matching_issuers:
        return {"status": "unknown"}

    saw_inactive = False
    saw_out_of_scope = False
    saw_subject_mismatch = False
    saw_stale_session = False
    token_actor_ids = list(token_spec.get("actor_ids") or [])
    for issuer in matching_issuers:
        status = str(issuer.get("status") or "").strip().lower()
        if status not in _ACTIVE_ISSUER_STATUSES:
            saw_inactive = True
            continue
        channels = list(issuer.get("channels") or [])
        target_environments = list(issuer.get("target_environments") or [])
        if (channels and target_channel not in channels) or (
            target_environments and target_environment not in target_environments
        ):
            saw_out_of_scope = True
            continue
        subject_actor_ids = list(issuer.get("subject_actor_ids") or [])
        if token_actor_ids and subject_actor_ids and any(actor_id not in subject_actor_ids for actor_id in token_actor_ids):
            saw_subject_mismatch = True
            continue
        if bool(issuer.get("session_required")):
            max_session_age_hours = max(int(issuer.get("max_session_age_hours") or 0), 0)
            if max_session_age_hours > 0 and issued_at is not None and issued_at < now - timedelta(hours=max_session_age_hours):
                saw_stale_session = True
                continue
            if not session_tracked:
                return {"status": "unknown"}
        return {"status": "registered", "issuer": issuer}
    if saw_subject_mismatch:
        return {"status": "subject_mismatch"}
    if saw_stale_session:
        return {"status": "stale_session"}
    if saw_out_of_scope:
        return {"status": "out_of_scope"}
    if saw_inactive:
        return {"status": "inactive"}
    return {"status": "unknown"}


def _build_release_request_auth_identity_action_status(
    posture: Dict[str, Any],
    *,
    target_channel: str,
) -> str:
    if max(int(posture.get("matching_token_count") or 0), 0) <= 0:
        return "blocked"
    if not bool(posture.get("identity_registry_exists")):
        return "warning"
    if max(int(posture.get("matching_registered_issuer_token_count") or 0), 0) <= 0:
        return "warning"
    if any(
        max(int(posture.get(field) or 0), 0) > 0
        for field in (
            "matching_unknown_issuer_token_count",
            "matching_inactive_issuer_token_count",
            "matching_unscoped_issuer_token_count",
            "matching_subject_out_of_registry_count",
            "matching_stale_session_token_count",
        )
    ):
        return "warning"
    if target_channel == "release" and (
        max(int(posture.get("matching_session_token_count") or 0), 0) <= 0
        or max(int(posture.get("tokens_without_session_id_count") or 0), 0) > 0
        or max(int(posture.get("tokens_without_issued_by_count") or 0), 0) > 0
        or max(int(posture.get("tokens_without_issued_at_count") or 0), 0) > 0
        or max(int(posture.get("invalid_issued_at_token_count") or 0), 0) > 0
    ):
        return "warning"
    return "passed"


def _resolve_allow_local_without_token(payload: Dict[str, Any], token_specs: List[Dict[str, Any]]) -> bool:
    if "allow_local_without_token" in payload:
        return bool(payload.get("allow_local_without_token"))
    return not bool(token_specs)


def _match_token_constraints(
    token_spec: Dict[str, Any],
    *,
    action: str,
    target_channel: str,
    target_environment: str,
    actor_id: str,
    ignore_actor: bool = False,
) -> str:
    token_id = str(token_spec.get("token_id") or "token").strip() or "token"
    if bool(token_spec.get("revoked")):
        return f"release write token {token_id} is revoked"

    expires_at = _parse_iso_datetime(token_spec.get("expires_at"))
    if expires_at is not None and expires_at <= datetime.now(timezone.utc):
        return f"release write token {token_id} is expired"

    actions = list(token_spec.get("actions") or [])
    if actions and action not in actions:
        return f"release write token {token_id} is not allowed for action={action}"

    channels = list(token_spec.get("channels") or [])
    if channels and target_channel not in channels:
        return f"release write token {token_id} is not allowed for target_channel={target_channel}"

    target_environments = list(token_spec.get("target_environments") or [])
    if target_environments and target_environment not in target_environments:
        return f"release write token {token_id} is not allowed for target_environment={target_environment or '-'}"

    actor_ids = list(token_spec.get("actor_ids") or [])
    if not ignore_actor and actor_ids and actor_id not in actor_ids:
        return f"release write token {token_id} is not allowed for executed_by={actor_id or '-'}"

    return ""


def _extract_token(*, authorization_header: str, custom_token_header: str) -> tuple[str, str, str]:
    normalized_authorization = str(authorization_header or "").strip()
    normalized_custom_header = str(custom_token_header or "").strip()
    if normalized_authorization.lower().startswith("bearer "):
        return normalized_authorization[7:].strip(), "bearer", "authorization"
    if normalized_custom_header:
        return normalized_custom_header, "header", "x-godot-agent-release-token"
    return "", "", ""


def _is_local_request_host(host: str) -> bool:
    normalized = str(host or "").strip().lower()
    return (
        not normalized
        or normalized in {"127.0.0.1", "::1", "localhost", "testclient"}
        or normalized.startswith("127.")
        or normalized.startswith("::ffff:127.")
    )


def _hash_token(token_value: str) -> str:
    return hashlib.sha256(str(token_value or "").encode("utf-8")).hexdigest()


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _copy_file(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)


def _load_manifest(auth_path: Path) -> tuple[Dict[str, Any], str]:
    if not auth_path.exists():
        return {}, ""
    try:
        payload = json.loads(auth_path.read_text(encoding="utf-8"))
    except Exception as exc:
        return {}, f"release request auth manifest parse failed: {exc}"
    if not isinstance(payload, dict):
        return {}, "release request auth manifest must be a JSON object"
    return payload, ""


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


def _coerce_nonnegative_int(raw_value: Any) -> int:
    try:
        return max(int(raw_value or 0), 0)
    except (TypeError, ValueError):
        return 0


def _parse_iso_datetime(raw_value: Any) -> Optional[datetime]:
    value = str(raw_value or "").strip()
    if not value:
        return None
    try:
        if value.endswith("Z"):
            value = f"{value[:-1]}+00:00"
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _resolve_project_path(project_root: Path, raw_path: str) -> Path:
    relative = str(raw_path or DEFAULT_RELEASE_REQUEST_AUTH_PATH).strip()
    if relative.startswith("res://"):
        relative = relative[6:]
    return (project_root / relative).resolve()


def _resolve_runtime_path(runtime_root: Path, raw_path: str) -> Path:
    relative = str(raw_path or "").strip()
    if not relative:
        relative = default_release_request_auth_posture_report_path(action="release_action", target_channel="staging")
    candidate = Path(relative)
    if candidate.is_absolute():
        return candidate.resolve()
    return (runtime_root / relative).resolve()


def _default_target_environment(target_channel: str) -> str:
    normalized_target_channel = str(target_channel or "").strip().lower()
    if normalized_target_channel == "release":
        return "production"
    return normalized_target_channel or "staging"


def _build_release_request_auth_identity_handoff_state(
    project_root: Path,
    *,
    runtime_root: Path,
    target_channel: str,
    target_environment: str,
    actions: List[str],
    identity_boundary: Dict[str, Any],
) -> Dict[str, Any]:
    handoff_dir = default_release_request_auth_identity_handoff_dir(
        target_channel=target_channel,
        target_environment=target_environment,
    )
    handoff_manifest_path = default_release_request_auth_identity_handoff_manifest_path(
        target_channel=target_channel,
        target_environment=target_environment,
    )
    handoff_instructions_path = default_release_request_auth_identity_handoff_instructions_path(
        target_channel=target_channel,
        target_environment=target_environment,
    )
    resolved_handoff_dir = _resolve_runtime_path(runtime_root, handoff_dir)
    resolved_handoff_manifest_path = _resolve_runtime_path(runtime_root, handoff_manifest_path)
    resolved_handoff_instructions_path = _resolve_runtime_path(runtime_root, handoff_instructions_path)
    resolved_boundary_manifest_path = resolved_handoff_dir / "deployment" / "release_identity_boundary.json"
    resolved_registry_manifest_path = resolved_handoff_dir / "deployment" / "release_identity_registry.json"
    resolved_rotation_audit_path = resolved_handoff_dir / "audits" / Path(
        default_release_request_auth_rotation_audit_report_path(target_channel=target_channel)
    ).name
    resolved_identity_audit_path = resolved_handoff_dir / "audits" / Path(
        default_release_request_auth_identity_audit_report_path(target_channel=target_channel)
    ).name
    handoff_required = bool(identity_boundary.get("external_handoff_required"))
    handoff_config_status = str(identity_boundary.get("external_handoff_status") or "skipped").strip() or "skipped"
    missing_items: List[str] = []
    if handoff_required:
        if handoff_config_status != "passed":
            missing_items.extend(["handoff_mode", "handoff_target_id", "handoff_owner"])
        if not resolved_handoff_manifest_path.exists():
            missing_items.append("handoff_manifest")
        if not resolved_handoff_instructions_path.exists():
            missing_items.append("handoff_instructions")
        if not resolved_boundary_manifest_path.exists():
            missing_items.append("identity_boundary_manifest")
        if not resolved_registry_manifest_path.exists():
            missing_items.append("identity_registry_manifest")
        if not resolved_rotation_audit_path.exists():
            missing_items.append("rotation_audit")
        if not resolved_identity_audit_path.exists():
            missing_items.append("identity_audit")
        for action_name in actions:
            posture_path = resolved_handoff_dir / "audits" / Path(
                default_release_request_auth_posture_report_path(
                    action=action_name,
                    target_channel=target_channel,
                )
            ).name
            if not posture_path.exists():
                missing_items.append(f"posture_{action_name}")

    if not handoff_required:
        handoff_status = "skipped"
        handoff_summary = "identity boundary handoff not required"
        missing_items = []
    else:
        file_count = sum(1 for path in resolved_handoff_dir.rglob("*") if path.is_file()) if resolved_handoff_dir.exists() else 0
        handoff_status = "passed" if not missing_items else "warning"
        handoff_summary = (
            f"identity boundary handoff ready / files={file_count}"
            if handoff_status == "passed"
            else "identity boundary handoff incomplete"
        )

    return {
        "identity_handoff_required": handoff_required,
        "identity_handoff_mode": str(identity_boundary.get("external_handoff_mode") or "").strip(),
        "identity_handoff_target_id": str(identity_boundary.get("external_handoff_target_id") or "").strip(),
        "identity_handoff_owner": str(identity_boundary.get("external_handoff_owner") or "").strip(),
        "identity_handoff_config_status": handoff_config_status,
        "identity_handoff_dir": _relative_to_root(resolved_handoff_dir, runtime_root),
        "identity_handoff_exists": resolved_handoff_dir.exists() and resolved_handoff_dir.is_dir(),
        "identity_handoff_file_count": sum(1 for path in resolved_handoff_dir.rglob("*") if path.is_file()) if resolved_handoff_dir.exists() else 0,
        "identity_handoff_manifest_path": _relative_to_root(resolved_handoff_manifest_path, runtime_root),
        "identity_handoff_manifest_exists": resolved_handoff_manifest_path.exists(),
        "identity_handoff_instructions_path": _relative_to_root(resolved_handoff_instructions_path, runtime_root),
        "identity_handoff_instructions_exists": resolved_handoff_instructions_path.exists(),
        "identity_handoff_boundary_manifest_path": _relative_to_root(resolved_boundary_manifest_path, runtime_root),
        "identity_handoff_boundary_manifest_exists": resolved_boundary_manifest_path.exists(),
        "identity_handoff_registry_manifest_path": _relative_to_root(resolved_registry_manifest_path, runtime_root),
        "identity_handoff_registry_manifest_exists": resolved_registry_manifest_path.exists(),
        "identity_handoff_status": handoff_status,
        "identity_handoff_summary": handoff_summary,
        "identity_handoff_missing_items": _clean_text_list(missing_items),
    }


def _slugify_segment(value: str, *, default: str) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "_", str(value or "").strip().lower()).strip("_")
    return normalized or default


def _relative_to_root(path: Path, project_root: Path) -> str:
    try:
        return path.resolve().relative_to(project_root.resolve()).as_posix()
    except Exception:
        return str(path.resolve())

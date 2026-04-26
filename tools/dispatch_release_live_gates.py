from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_WORKFLOW = "release-live-gates.yml"
DEFAULT_TOKEN_ENV_NAMES = ("GH_TOKEN", "GITHUB_TOKEN")
RELEASE_LIVE_DISPATCH_PREFLIGHT_SCHEMA_VERSION = "1.0"
RELEASE_LIVE_DISPATCH_RESULT_SCHEMA_VERSION = "1.0"
RELEASE_LIVE_DISPATCH_AUDIT_SCHEMA_VERSION = "1.0"
DEFAULT_RELEASE_LIVE_DISPATCH_AUDIT_PATH = "logs/reports/release_live_ci/release_live_dispatch.json"
DEFAULT_RELEASE_LIVE_DISPATCH_PREFLIGHT_PATH = "logs/reports/release_live_ci/release_live_dispatch_preflight.json"
DEFAULT_RELEASE_LIVE_DISPATCH_PREFLIGHT_MARKDOWN_PATH = "logs/reports/release_live_ci/release_live_dispatch_preflight.md"


def _git_output(project_root: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=project_root,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or result.stdout.strip() or f"git {' '.join(args)} failed")
    return result.stdout.strip()


def infer_repo_from_remote_url(remote_url: str) -> str:
    normalized = str(remote_url or "").strip()
    if normalized.endswith(".git"):
        normalized = normalized[:-4]
    if normalized.startswith("git@github.com:"):
        normalized = normalized.split(":", 1)[1]
    elif normalized.startswith("https://github.com/"):
        normalized = normalized.split("https://github.com/", 1)[1]
    elif normalized.startswith("http://github.com/"):
        normalized = normalized.split("http://github.com/", 1)[1]
    if normalized.count("/") != 1:
        raise ValueError(f"Cannot infer owner/repo from remote URL: {remote_url}")
    owner, repo = normalized.split("/", 1)
    if not owner or not repo:
        raise ValueError(f"Cannot infer owner/repo from remote URL: {remote_url}")
    return f"{owner}/{repo}"


def infer_repo_slug(project_root: Path) -> str:
    return infer_repo_from_remote_url(_git_output(project_root, "remote", "get-url", "origin"))


def infer_ref_name(project_root: Path) -> str:
    ref = _git_output(project_root, "branch", "--show-current")
    return ref or "main"


def _normalize_list_values(value: Any) -> list[str]:
    if isinstance(value, str):
        parts = value.replace("\r", "\n").replace(";", "\n").split("\n")
    elif isinstance(value, (list, tuple, set)):
        parts = list(value)
    else:
        return []
    normalized: list[str] = []
    seen: set[str] = set()
    for item in parts:
        text = str(item or "").strip()
        if not text or text in seen:
            continue
        normalized.append(text)
        seen.add(text)
    return normalized


def _resolve_input_value(args: Any, overrides: dict[str, Any], name: str, default: Any = "") -> Any:
    if name in overrides and overrides[name] is not None:
        return overrides[name]
    if args is None:
        return default
    return getattr(args, name, default)


def _normalize_csv_input(value: Any) -> str:
    if isinstance(value, (list, tuple, set)):
        return ",".join(_normalize_list_values(value))
    return str(value or "").strip()


def _normalize_token_env_names(value: Any) -> list[str]:
    names = _normalize_list_values(value if not isinstance(value, str) else value.replace(",", "\n"))
    return names or list(DEFAULT_TOKEN_ENV_NAMES)


def normalize_runner_labels(raw_value: Any) -> str:
    if isinstance(raw_value, (list, tuple, set)):
        parsed = [str(item).strip() for item in raw_value if str(item).strip()]
        if not parsed:
            raise ValueError("runner_labels must contain at least one label")
        return json.dumps(parsed, ensure_ascii=True)

    raw_text = str(raw_value or "").strip()
    if not raw_text:
        raise ValueError("runner_labels cannot be empty")
    if raw_text.startswith("["):
        parsed = json.loads(raw_text)
        if not isinstance(parsed, list) or not all(str(item).strip() for item in parsed):
            raise ValueError("runner_labels JSON must be a non-empty array of strings")
        return json.dumps([str(item).strip() for item in parsed], ensure_ascii=True)
    labels = [item.strip() for item in raw_text.split(",") if item.strip()]
    if not labels:
        raise ValueError("runner_labels must contain at least one label")
    return json.dumps(labels, ensure_ascii=True)


def build_workflow_dispatch_inputs(args: Any = None, /, **overrides: Any) -> dict[str, str]:
    return {
        "runner_labels": normalize_runner_labels(_resolve_input_value(args, overrides, "runner_labels", '["self-hosted","windows","godot"]')),
        "target_channel": str(_resolve_input_value(args, overrides, "target_channel", "release") or "").strip() or "release",
        "target_environment": str(_resolve_input_value(args, overrides, "target_environment", "production") or "").strip() or "production",
        "release_manifest_path": str(
            _resolve_input_value(args, overrides, "release_manifest_path", "api_server/static/dist/release_manifest.json") or ""
        ).strip() or "api_server/static/dist/release_manifest.json",
        "runner_profile_path": str(
            _resolve_input_value(args, overrides, "runner_profile_path", "deployment/release_live_runner_profile.json") or ""
        ).strip() or "deployment/release_live_runner_profile.json",
        "approvers": _normalize_csv_input(_resolve_input_value(args, overrides, "approvers", "")),
        "providers": _normalize_csv_input(_resolve_input_value(args, overrides, "providers", "codex,openai_api")) or "codex,openai_api",
        "artifact_dir": str(_resolve_input_value(args, overrides, "artifact_dir", "logs/reports/release_live_ci") or "").strip() or "logs/reports/release_live_ci",
        "fail_on_warnings": "true" if bool(_resolve_input_value(args, overrides, "fail_on_warnings", False)) else "false",
    }


def _resolve_token_from_sources(*, direct_token: str = "", token_env_names: Any = DEFAULT_TOKEN_ENV_NAMES) -> tuple[str, str]:
    explicit_token = str(direct_token or "").strip()
    if explicit_token:
        return explicit_token, "explicit"
    for name in _normalize_token_env_names(token_env_names):
        candidate = str(os.environ.get(name) or "").strip()
        if candidate:
            return candidate, name
    raise RuntimeError("No GitHub token found. Set GH_TOKEN or GITHUB_TOKEN, or pass --token.")


def _parse_github_datetime(raw_value: Any) -> datetime | None:
    text = str(raw_value or "").strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None


def _github_api_request(
    *,
    method: str,
    url: str,
    token: str,
    payload: dict[str, Any] | None = None,
    timeout: float = 30.0,
) -> dict[str, Any]:
    request_data = None
    headers = {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {token}",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "godot-agent-release-live-gates-dispatcher",
    }
    if payload is not None:
        request_data = json.dumps(payload, ensure_ascii=True).encode("utf-8")
        headers["Content-Type"] = "application/json; charset=utf-8"
    request = urllib.request.Request(url, method=method.upper(), data=request_data, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = response.read().decode("utf-8", errors="replace").strip()
            return json.loads(body) if body else {}
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"{method.upper()} {url} failed: {exc.code} {detail}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"{method.upper()} {url} failed: {exc}") from exc


def _pick_workflow_run(
    workflow_runs: list[dict[str, Any]],
    *,
    ref_name: str,
    dispatched_after: datetime,
) -> dict[str, Any] | None:
    threshold = dispatched_after - timedelta(seconds=5)
    candidates: list[tuple[datetime, dict[str, Any]]] = []
    for run in workflow_runs:
        if str(run.get("event") or "") != "workflow_dispatch":
            continue
        if ref_name and str(run.get("head_branch") or "") != ref_name:
            continue
        created_at = _parse_github_datetime(run.get("created_at"))
        if created_at is None or created_at < threshold:
            continue
        candidates.append((created_at, run))
    if not candidates:
        return None
    candidates.sort(key=lambda item: item[0], reverse=True)
    return candidates[0][1]


def _workflow_dispatch_url(repo_slug: str, workflow_name: str) -> str:
    owner, repo = repo_slug.split("/", 1)
    encoded_workflow = urllib.parse.quote(workflow_name, safe="")
    return f"https://api.github.com/repos/{owner}/{repo}/actions/workflows/{encoded_workflow}/dispatches"


def _workflow_runs_url(repo_slug: str, workflow_name: str, *, ref_name: str) -> str:
    owner, repo = repo_slug.split("/", 1)
    encoded_workflow = urllib.parse.quote(workflow_name, safe="")
    query = urllib.parse.urlencode({
        "event": "workflow_dispatch",
        "branch": ref_name,
        "per_page": 20,
    })
    return f"https://api.github.com/repos/{owner}/{repo}/actions/workflows/{encoded_workflow}/runs?{query}"


def _resolve_workflow_path(project_root: Path, workflow_name: str) -> Path | None:
    normalized = str(workflow_name or "").strip()
    if not normalized:
        return (project_root / ".github" / "workflows" / DEFAULT_WORKFLOW).resolve()
    if normalized.isdigit():
        return None
    candidate = Path(normalized)
    if candidate.is_absolute():
        return candidate.resolve()
    if "/" in normalized or "\\" in normalized:
        return (project_root / candidate).resolve()
    return (project_root / ".github" / "workflows" / normalized).resolve()


def _read_workflow_dispatch_enabled(workflow_path: Path | None) -> tuple[bool, bool]:
    if workflow_path is None:
        return False, False
    if not workflow_path.exists():
        return False, False
    workflow_text = workflow_path.read_text(encoding="utf-8", errors="replace")
    return True, bool(re.search(r"^\s*workflow_dispatch\s*:", workflow_text, flags=re.MULTILINE))


def _dedupe_list(values: list[str]) -> list[str]:
    normalized: list[str] = []
    seen: set[str] = set()
    for item in values:
        text = str(item or "").strip()
        if not text or text in seen:
            continue
        normalized.append(text)
        seen.add(text)
    return normalized


def _relative_to_root(path: Path, project_root: Path) -> str:
    try:
        return path.resolve().relative_to(project_root.resolve()).as_posix()
    except Exception:
        return str(path.resolve())


def _resolve_dispatch_audit_path(project_root: Path, *, artifact_dir: str = "", audit_path: str = "") -> Path:
    if str(audit_path or "").strip():
        candidate = Path(str(audit_path or "").strip())
        return candidate.resolve() if candidate.is_absolute() else (project_root / candidate).resolve()
    normalized_artifact_dir = str(artifact_dir or "").strip() or "logs/reports/release_live_ci"
    candidate = Path(normalized_artifact_dir) / "release_live_dispatch.json"
    return candidate.resolve() if candidate.is_absolute() else (project_root / candidate).resolve()


def _normalize_dispatch_run(source: Any) -> dict[str, Any]:
    raw = dict(source or {})
    return {
        "id": raw.get("id"),
        "number": raw.get("number"),
        "status": str(raw.get("status") or "").strip(),
        "conclusion": str(raw.get("conclusion") or "").strip(),
        "html_url": str(raw.get("html_url") or "").strip(),
        "created_at": str(raw.get("created_at") or "").strip(),
        "updated_at": str(raw.get("updated_at") or "").strip(),
        "head_branch": str(raw.get("head_branch") or "").strip(),
    }


def _normalize_dispatch_result_payload(source: Any) -> dict[str, Any]:
    raw = dict(source or {})
    inputs = {
        str(key).strip(): str(value).strip()
        for key, value in dict(raw.get("inputs") or {}).items()
        if str(key).strip()
    }
    return {
        "schema_version": str(raw.get("schema_version") or RELEASE_LIVE_DISPATCH_RESULT_SCHEMA_VERSION).strip()
        or RELEASE_LIVE_DISPATCH_RESULT_SCHEMA_VERSION,
        "ok": bool(raw.get("ok")),
        "status": str(raw.get("status") or "").strip(),
        "summary": str(raw.get("summary") or "").strip(),
        "repo": str(raw.get("repo") or "").strip(),
        "workflow": str(raw.get("workflow") or "").strip(),
        "ref": str(raw.get("ref") or "").strip(),
        "dispatched_at": str(raw.get("dispatched_at") or "").strip(),
        "token_source": str(raw.get("token_source") or "").strip(),
        "inputs": inputs,
        "wait": bool(raw.get("wait")),
        "run": _normalize_dispatch_run(raw.get("run")),
        "error": str(raw.get("error") or "").strip(),
        "error_type": str(raw.get("error_type") or "").strip(),
    }


def build_release_live_dispatch_audit(
    project_root: str | Path,
    *,
    artifact_dir: str = "logs/reports/release_live_ci",
    audit_path: str = "",
    preflight: dict[str, Any] | None = None,
    dispatch_result: dict[str, Any] | None = None,
    request_auth: dict[str, Any] | None = None,
    triggered_by: str = "",
    error: str = "",
    error_type: str = "",
    recorded_at: str = "",
) -> dict[str, Any]:
    resolved_project_root = Path(project_root).resolve()
    resolved_audit_path = _resolve_dispatch_audit_path(
        resolved_project_root,
        artifact_dir=artifact_dir,
        audit_path=audit_path,
    )
    normalized_preflight = dict(preflight or {})
    normalized_result = _normalize_dispatch_result_payload(dispatch_result)
    normalized_request_auth = dict(request_auth or {})
    normalized_triggered_by = str(triggered_by or normalized_request_auth.get("actor_id") or "").strip()
    normalized_error = str(error or normalized_result.get("error") or "").strip()
    normalized_error_type = str(error_type or normalized_result.get("error_type") or "").strip()
    preflight_status = str(normalized_preflight.get("status") or "").strip().lower()
    result_status = str(normalized_result.get("status") or "").strip().lower()
    request_auth_status = str(normalized_request_auth.get("status") or "").strip().lower()
    blocking_checks = _dedupe_list([str(item).strip() for item in list(normalized_preflight.get("blocking_checks") or []) if str(item).strip()])
    warning_checks = _dedupe_list([str(item).strip() for item in list(normalized_preflight.get("warning_checks") or []) if str(item).strip()])
    recommendations = _dedupe_list([
        *[str(item).strip() for item in list(normalized_preflight.get("recommendations") or []) if str(item).strip()],
        str(normalized_request_auth.get("reason") or "").strip(),
        normalized_error,
    ])
    if request_auth_status == "blocked":
        blocking_checks = _dedupe_list([*blocking_checks, "request_auth_blocked"])
    elif request_auth_status == "warning":
        warning_checks = _dedupe_list([*warning_checks, "request_auth_warning"])
    if normalized_error and not blocking_checks:
        blocking_checks = ["dispatch_error"]

    status = "passed"
    if request_auth_status == "blocked" or normalized_error or preflight_status == "blocked" or result_status == "blocked":
        status = "blocked"
    elif request_auth_status == "warning" or preflight_status == "warning" or result_status == "warning":
        status = "warning"
    elif not normalized_result.get("summary") and preflight_status:
        status = preflight_status

    run = dict(normalized_result.get("run") or {})
    dispatch_attempted = bool(normalized_result.get("summary") or normalized_result.get("dispatched_at") or run.get("id"))
    dispatch_completed = str(run.get("status") or "").strip().lower() == "completed"
    follow_up_required = bool(blocking_checks) or (
        dispatch_attempted and normalized_result.get("wait") and not dispatch_completed
    )
    summary = (
        normalized_error
        or str(normalized_result.get("summary") or "").strip()
        or str(normalized_preflight.get("summary") or "").strip()
        or "release live dispatch audit captured"
    )
    normalized_recorded_at = str(recorded_at or datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")).strip()
    effective_artifact_dir = str(artifact_dir or "").strip() or "logs/reports/release_live_ci"
    inputs = dict(normalized_result.get("inputs") or normalized_preflight.get("dispatch_inputs") or {})

    return {
        "schema_version": RELEASE_LIVE_DISPATCH_AUDIT_SCHEMA_VERSION,
        "contract_versions": {
            "release_live_dispatch_audit": RELEASE_LIVE_DISPATCH_AUDIT_SCHEMA_VERSION,
            "release_live_dispatch_preflight": str(normalized_preflight.get("schema_version") or ""),
            "release_live_dispatch_result": str(normalized_result.get("schema_version") or RELEASE_LIVE_DISPATCH_RESULT_SCHEMA_VERSION),
        },
        "status": status,
        "summary": summary,
        "path": _relative_to_root(resolved_audit_path, resolved_project_root),
        "artifact_dir": effective_artifact_dir.replace("\\", "/"),
        "project_root": str(resolved_project_root),
        "recorded_at": normalized_recorded_at,
        "triggered_by": normalized_triggered_by,
        "workflow": str(normalized_result.get("workflow") or normalized_preflight.get("workflow") or DEFAULT_WORKFLOW).strip(),
        "repo": str(normalized_result.get("repo") or normalized_preflight.get("repo") or "").strip(),
        "ref": str(normalized_result.get("ref") or normalized_preflight.get("ref") or "").strip(),
        "target_channel": str(inputs.get("target_channel") or "").strip(),
        "target_environment": str(inputs.get("target_environment") or "").strip(),
        "ready": bool(normalized_preflight.get("ready")),
        "ok": bool(normalized_result.get("ok")) and status == "passed",
        "wait": bool(normalized_result.get("wait")),
        "dispatch_attempted": dispatch_attempted,
        "dispatch_completed": dispatch_completed,
        "follow_up_required": follow_up_required,
        "token_source": str(normalized_result.get("token_source") or normalized_preflight.get("token_source") or "").strip(),
        "inputs": inputs,
        "run": run,
        "error": normalized_error,
        "error_type": normalized_error_type,
        "blocking_checks": blocking_checks,
        "warning_checks": warning_checks,
        "recommendations": recommendations,
        "request_auth": normalized_request_auth,
        "preflight": normalized_preflight,
        "dispatch_result": normalized_result,
    }


def write_release_live_dispatch_audit(
    project_root: str | Path,
    *,
    artifact_dir: str = "logs/reports/release_live_ci",
    audit_path: str = "",
    preflight: dict[str, Any] | None = None,
    dispatch_result: dict[str, Any] | None = None,
    request_auth: dict[str, Any] | None = None,
    triggered_by: str = "",
    error: str = "",
    error_type: str = "",
    recorded_at: str = "",
) -> dict[str, Any]:
    resolved_project_root = Path(project_root).resolve()
    payload = build_release_live_dispatch_audit(
        resolved_project_root,
        artifact_dir=artifact_dir,
        audit_path=audit_path,
        preflight=preflight,
        dispatch_result=dispatch_result,
        request_auth=request_auth,
        triggered_by=triggered_by,
        error=error,
        error_type=error_type,
        recorded_at=recorded_at,
    )
    resolved_audit_path = _resolve_dispatch_audit_path(
        resolved_project_root,
        artifact_dir=artifact_dir,
        audit_path=audit_path,
    )
    resolved_audit_path.parent.mkdir(parents=True, exist_ok=True)
    resolved_audit_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return payload


def load_release_live_dispatch_audit(
    project_root: str | Path,
    *,
    artifact_dir: str = "logs/reports/release_live_ci",
    audit_path: str = "",
) -> dict[str, Any]:
    resolved_audit_path = _resolve_dispatch_audit_path(
        Path(project_root).resolve(),
        artifact_dir=artifact_dir,
        audit_path=audit_path,
    )
    if not resolved_audit_path.exists() or not resolved_audit_path.is_file():
        return {}
    try:
        payload = json.loads(resolved_audit_path.read_text(encoding="utf-8-sig"))
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def build_release_live_dispatch_audit_report_lines(audit: dict[str, Any] | None) -> list[str]:
    raw = dict(audit or {})
    run = dict(raw.get("run") or dict(raw.get("dispatch_result") or {}).get("run") or {})
    request_auth = dict(raw.get("request_auth") or {})
    preflight = dict(raw.get("preflight") or {})
    blocking_checks = _normalize_list_values(raw.get("blocking_checks") or preflight.get("blocking_checks"))
    warning_checks = _normalize_list_values(raw.get("warning_checks") or preflight.get("warning_checks"))
    recommendations = _normalize_list_values(raw.get("recommendations") or preflight.get("recommendations"))

    if not any([
        str(raw.get("status") or "").strip(),
        str(raw.get("summary") or "").strip(),
        str(raw.get("path") or "").strip(),
        bool(raw.get("ready")),
        bool(raw.get("dispatch_attempted")),
        bool(raw.get("dispatch_completed")),
        bool(run),
        str(request_auth.get("status") or "").strip(),
    ]):
        return []

    lines = [
        (
            f"- Dispatch Audit: status={str(raw.get('status') or 'skipped').strip() or 'skipped'} / "
            f"ready={bool(raw.get('ready'))} / attempted={bool(raw.get('dispatch_attempted'))} / "
            f"completed={bool(raw.get('dispatch_completed'))} / wait={bool(raw.get('wait'))} / "
            f"follow_up_required={bool(raw.get('follow_up_required'))}"
        ),
        f"- Dispatch Summary: {str(raw.get('summary') or '-').strip() or '-'}",
        (
            f"- Dispatch Path: {str(raw.get('path') or '-').strip() or '-'} / "
            f"recorded_at={str(raw.get('recorded_at') or '-').strip() or '-'} / "
            f"triggered_by={str(raw.get('triggered_by') or request_auth.get('actor_id') or '-').strip() or '-'}"
        ),
        (
            f"- Dispatch Target: workflow={str(raw.get('workflow') or preflight.get('workflow') or '-').strip() or '-'} / "
            f"repo={str(raw.get('repo') or preflight.get('repo') or '-').strip() or '-'} / "
            f"ref={str(raw.get('ref') or preflight.get('ref') or '-').strip() or '-'} / "
            f"channel={str(raw.get('target_channel') or raw.get('inputs', {}).get('target_channel') or '-').strip() or '-'} / "
            f"environment={str(raw.get('target_environment') or raw.get('inputs', {}).get('target_environment') or '-').strip() or '-'}"
        ),
        (
            f"- Dispatch Run: id={run.get('id') or '-'} / "
            f"status={str(run.get('status') or '-').strip() or '-'} / "
            f"conclusion={str(run.get('conclusion') or '-').strip() or '-'} / "
            f"url={str(run.get('html_url') or '-').strip() or '-'}"
        ),
        (
            f"- Dispatch Request Auth: status={str(request_auth.get('status') or '-').strip() or '-'} / "
            f"actor={str(request_auth.get('actor_id') or '-').strip() or '-'} / "
            f"reason={str(request_auth.get('reason') or '-').strip() or '-'}"
        ),
    ]
    if blocking_checks:
        lines.append(f"- Dispatch Blocking Checks: {', '.join(blocking_checks)}")
    if warning_checks:
        lines.append(f"- Dispatch Warning Checks: {', '.join(warning_checks)}")
    if str(raw.get("token_source") or "").strip():
        lines.append(f"- Dispatch Token Source: {str(raw.get('token_source') or '').strip()}")
    if str(raw.get("error") or "").strip():
        lines.append(
            f"- Dispatch Error: {str(raw.get('error_type') or 'runtime').strip() or 'runtime'} / {str(raw.get('error') or '').strip()}"
        )
    if recommendations:
        lines.append(f"- Dispatch Recommendation: {recommendations[0]}")
    return lines


def build_release_live_dispatch_preflight(
    project_root: str | Path,
    *,
    repo: str = "",
    ref: str = "",
    workflow: str = DEFAULT_WORKFLOW,
    runner_labels: Any = '["self-hosted","windows","godot"]',
    target_channel: str = "release",
    target_environment: str = "production",
    release_manifest_path: str = "api_server/static/dist/release_manifest.json",
    runner_profile_path: str = "deployment/release_live_runner_profile.json",
    approvers: Any = "",
    providers: Any = "codex,openai_api",
    artifact_dir: str = "logs/reports/release_live_ci",
    fail_on_warnings: bool = False,
    token_env_names: Any = DEFAULT_TOKEN_ENV_NAMES,
    token: str = "",
) -> dict[str, Any]:
    resolved_project_root = Path(project_root).resolve()
    workflow_name = str(workflow or "").strip() or DEFAULT_WORKFLOW
    normalized_repo = str(repo or "").strip()
    normalized_ref = str(ref or "").strip()
    normalized_token_env_names = _normalize_token_env_names(token_env_names)
    blocking_checks: list[str] = []
    warning_checks: list[str] = []
    recommendations: list[str] = []

    origin_remote_url = ""
    repo_source = "explicit" if normalized_repo else "git_remote"
    if not normalized_repo:
        try:
            origin_remote_url = _git_output(resolved_project_root, "remote", "get-url", "origin")
            normalized_repo = infer_repo_from_remote_url(origin_remote_url)
        except Exception:
            repo_source = "missing"
            blocking_checks.append("github_repo_missing")
            recommendations.append("Provide --repo or configure git origin before dispatching release-live-gates.")
    if not normalized_ref:
        try:
            normalized_ref = infer_ref_name(resolved_project_root)
            ref_source = "git_branch"
        except Exception:
            normalized_ref = "main"
            ref_source = "default"
            warning_checks.append("git_ref_defaulted")
            recommendations.append("Review the target ref before dispatching if this checkout is detached.")
    else:
        ref_source = "explicit"

    token_present = False
    token_source = ""
    try:
        _, token_source = _resolve_token_from_sources(direct_token=token, token_env_names=normalized_token_env_names)
        token_present = True
    except RuntimeError:
        blocking_checks.append("github_token_missing")
        recommendations.append("Set GH_TOKEN or GITHUB_TOKEN before dispatching the real GitHub workflow.")

    try:
        dispatch_inputs = build_workflow_dispatch_inputs(
            runner_labels=runner_labels,
            target_channel=target_channel,
            target_environment=target_environment,
            release_manifest_path=release_manifest_path,
            runner_profile_path=runner_profile_path,
            approvers=approvers,
            providers=providers,
            artifact_dir=artifact_dir,
            fail_on_warnings=fail_on_warnings,
        )
        normalized_runner_labels = list(json.loads(dispatch_inputs["runner_labels"]))
    except Exception as exc:
        dispatch_inputs = {}
        normalized_runner_labels = []
        blocking_checks.append("dispatch_inputs_invalid")
        recommendations.append(str(exc))

    workflow_path = _resolve_workflow_path(resolved_project_root, workflow_name)
    workflow_exists, workflow_dispatch_enabled = _read_workflow_dispatch_enabled(workflow_path)
    if workflow_path is None:
        warning_checks.append("workflow_manifest_unavailable")
        recommendations.append("Use the workflow file name for local preflight validation, not only a numeric workflow id.")
    elif not workflow_exists:
        blocking_checks.append("workflow_file_missing")
        recommendations.append(f"Ensure {workflow_path.relative_to(resolved_project_root).as_posix()} exists in this checkout.")
    elif not workflow_dispatch_enabled:
        blocking_checks.append("workflow_dispatch_missing")
        recommendations.append("Enable workflow_dispatch in the target workflow before attempting remote dispatch.")

    gh_cli_path = shutil.which("gh") or ""
    if not gh_cli_path:
        warning_checks.append("gh_cli_missing")

    ready = not blocking_checks
    status = "blocked" if blocking_checks else ("warning" if warning_checks else "passed")
    summary = (
        f"ready={'yes' if ready else 'no'} / repo={normalized_repo or '-'} / ref={normalized_ref or '-'} / "
        f"token={'yes' if token_present else 'no'} / workflow_dispatch={'yes' if workflow_dispatch_enabled else 'no'}"
    )

    return {
        "schema_version": RELEASE_LIVE_DISPATCH_PREFLIGHT_SCHEMA_VERSION,
        "contract_versions": {
            "release_live_dispatch_preflight": RELEASE_LIVE_DISPATCH_PREFLIGHT_SCHEMA_VERSION,
        },
        "status": status,
        "summary": summary,
        "ready": ready,
        "project_root": str(resolved_project_root),
        "workflow": workflow_name,
        "workflow_path": str(workflow_path) if workflow_path else "",
        "workflow_exists": workflow_exists,
        "workflow_dispatch_enabled": workflow_dispatch_enabled,
        "repo": normalized_repo,
        "repo_source": repo_source,
        "origin_remote_url": origin_remote_url,
        "ref": normalized_ref,
        "ref_source": ref_source,
        "token_env_names": normalized_token_env_names,
        "token_present": token_present,
        "token_source": token_source,
        "gh_cli_installed": bool(gh_cli_path),
        "gh_cli_path": gh_cli_path,
        "runner_labels": normalized_runner_labels,
        "dispatch_inputs": dispatch_inputs,
        "blocking_checks": _dedupe_list(blocking_checks),
        "warning_checks": _dedupe_list(warning_checks),
        "recommendations": _dedupe_list(recommendations),
    }


def build_release_live_dispatch_preflight_report_lines(preflight: dict[str, Any] | None) -> list[str]:
    raw = dict(preflight or {})
    if not raw:
        return []
    lines = [
        "# Release Live Dispatch Preflight",
        "",
        f"- Status: {str(raw.get('status') or 'skipped').strip() or 'skipped'}",
        f"- Ready: {bool(raw.get('ready'))}",
        f"- Summary: {str(raw.get('summary') or '-').strip() or '-'}",
        (
            f"- Target: repo={str(raw.get('repo') or '-').strip() or '-'} / "
            f"ref={str(raw.get('ref') or '-').strip() or '-'} / "
            f"workflow={str(raw.get('workflow') or '-').strip() or '-'}"
        ),
        (
            f"- Workflow: exists={bool(raw.get('workflow_exists'))} / "
            f"dispatch_enabled={bool(raw.get('workflow_dispatch_enabled'))} / "
            f"path={str(raw.get('workflow_path') or '-').strip() or '-'}"
        ),
        (
            f"- Token: present={bool(raw.get('token_present'))} / "
            f"source={str(raw.get('token_source') or '-').strip() or '-'} / "
            f"env_names={', '.join(list(raw.get('token_env_names') or [])) or '-'}"
        ),
        (
            f"- GitHub CLI: installed={bool(raw.get('gh_cli_installed'))} / "
            f"path={str(raw.get('gh_cli_path') or '-').strip() or '-'}"
        ),
        f"- Runner Labels: {', '.join(list(raw.get('runner_labels') or [])) or '-'}",
    ]
    blocking_checks = _normalize_list_values(raw.get("blocking_checks"))
    warning_checks = _normalize_list_values(raw.get("warning_checks"))
    recommendations = _normalize_list_values(raw.get("recommendations"))
    if blocking_checks:
        lines.append(f"- Blocking Checks: {', '.join(blocking_checks)}")
    if warning_checks:
        lines.append(f"- Warning Checks: {', '.join(warning_checks)}")
    dispatch_inputs = dict(raw.get("dispatch_inputs") or {})
    if dispatch_inputs:
        lines.extend(["", "## Dispatch Inputs", ""])
        for key in sorted(dispatch_inputs):
            lines.append(f"- {key}: {dispatch_inputs[key]}")
    if recommendations:
        lines.extend(["", "## Recommendations", ""])
        lines.extend(f"- {item}" for item in recommendations)
    return lines


def build_release_live_dispatch_preflight_report(preflight: dict[str, Any] | None) -> str:
    lines = build_release_live_dispatch_preflight_report_lines(preflight)
    return "\n".join(lines).strip() + ("\n" if lines else "")


def export_release_live_dispatch_preflight(
    project_root: str | Path,
    *,
    repo: str = "",
    ref: str = "",
    workflow: str = DEFAULT_WORKFLOW,
    runner_labels: Any = '["self-hosted","windows","godot"]',
    target_channel: str = "release",
    target_environment: str = "production",
    release_manifest_path: str = "api_server/static/dist/release_manifest.json",
    runner_profile_path: str = "deployment/release_live_runner_profile.json",
    approvers: Any = "",
    providers: Any = "codex,openai_api",
    artifact_dir: str = "logs/reports/release_live_ci",
    fail_on_warnings: bool = False,
    token_env_names: Any = DEFAULT_TOKEN_ENV_NAMES,
    token: str = "",
    report_path: str | Path = DEFAULT_RELEASE_LIVE_DISPATCH_PREFLIGHT_PATH,
    markdown_path: str | Path = DEFAULT_RELEASE_LIVE_DISPATCH_PREFLIGHT_MARKDOWN_PATH,
) -> dict[str, Any]:
    payload = build_release_live_dispatch_preflight(
        project_root,
        repo=repo,
        ref=ref,
        workflow=workflow,
        runner_labels=runner_labels,
        target_channel=target_channel,
        target_environment=target_environment,
        release_manifest_path=release_manifest_path,
        runner_profile_path=runner_profile_path,
        approvers=approvers,
        providers=providers,
        artifact_dir=artifact_dir,
        fail_on_warnings=fail_on_warnings,
        token_env_names=token_env_names,
        token=token,
    )
    resolved_project_root = Path(project_root).resolve()
    json_path = (resolved_project_root / report_path).resolve() if not Path(report_path).is_absolute() else Path(report_path)
    md_path = (resolved_project_root / markdown_path).resolve() if not Path(markdown_path).is_absolute() else Path(markdown_path)
    payload["report_path"] = str(json_path.relative_to(resolved_project_root)).replace("\\", "/") if json_path.is_relative_to(resolved_project_root) else str(json_path)
    payload["report_markdown_path"] = str(md_path.relative_to(resolved_project_root)).replace("\\", "/") if md_path.is_relative_to(resolved_project_root) else str(md_path)
    json_path.parent.mkdir(parents=True, exist_ok=True)
    md_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    md_path.write_text(build_release_live_dispatch_preflight_report(payload), encoding="utf-8")
    return payload


def dispatch_release_live_gates_request(
    project_root: str | Path,
    *,
    repo: str = "",
    ref: str = "",
    workflow: str = DEFAULT_WORKFLOW,
    runner_labels: Any = '["self-hosted","windows","godot"]',
    target_channel: str = "release",
    target_environment: str = "production",
    release_manifest_path: str = "api_server/static/dist/release_manifest.json",
    runner_profile_path: str = "deployment/release_live_runner_profile.json",
    approvers: Any = "",
    providers: Any = "codex,openai_api",
    artifact_dir: str = "logs/reports/release_live_ci",
    fail_on_warnings: bool = False,
    wait: bool = False,
    poll_interval: float = 15.0,
    wait_timeout: float = 7200.0,
    dispatch_timeout: float = 30.0,
    token: str = "",
    token_env_names: Any = DEFAULT_TOKEN_ENV_NAMES,
) -> dict[str, Any]:
    preflight = build_release_live_dispatch_preflight(
        project_root,
        repo=repo,
        ref=ref,
        workflow=workflow,
        runner_labels=runner_labels,
        target_channel=target_channel,
        target_environment=target_environment,
        release_manifest_path=release_manifest_path,
        runner_profile_path=runner_profile_path,
        approvers=approvers,
        providers=providers,
        artifact_dir=artifact_dir,
        fail_on_warnings=fail_on_warnings,
        token_env_names=token_env_names,
        token=token,
    )
    if not preflight["ready"]:
        raise RuntimeError(
            f"release live dispatch preflight blocked: {', '.join(preflight.get('blocking_checks') or ['unknown'])}"
        )

    token_value, token_source = _resolve_token_from_sources(direct_token=token, token_env_names=token_env_names)
    repo_slug = str(preflight.get("repo") or "").strip()
    ref_name = str(preflight.get("ref") or "").strip()
    workflow_name = str(preflight.get("workflow") or DEFAULT_WORKFLOW).strip() or DEFAULT_WORKFLOW
    inputs = dict(preflight.get("dispatch_inputs") or {})
    dispatched_at = datetime.now(timezone.utc)

    _github_api_request(
        method="POST",
        url=_workflow_dispatch_url(repo_slug, workflow_name),
        token=token_value,
        payload={"ref": ref_name, "inputs": inputs},
        timeout=float(dispatch_timeout),
    )

    result: dict[str, Any] = {
        "schema_version": RELEASE_LIVE_DISPATCH_RESULT_SCHEMA_VERSION,
        "contract_versions": {
            "release_live_dispatch_result": RELEASE_LIVE_DISPATCH_RESULT_SCHEMA_VERSION,
            "release_live_dispatch_preflight": str(preflight.get("schema_version") or ""),
        },
        "ok": True,
        "status": "passed",
        "summary": f"workflow_dispatch accepted for {repo_slug}@{ref_name}",
        "repo": repo_slug,
        "workflow": workflow_name,
        "ref": ref_name,
        "dispatched_at": dispatched_at.replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "token_source": token_source,
        "inputs": inputs,
        "wait": bool(wait),
        "run": {},
        "preflight": preflight,
    }

    if not wait:
        return result

    deadline = time.time() + float(wait_timeout)
    polling_interval = max(float(poll_interval), 1.0)
    while time.time() < deadline:
        runs_payload = _github_api_request(
            method="GET",
            url=_workflow_runs_url(repo_slug, workflow_name, ref_name=ref_name),
            token=token_value,
            timeout=30.0,
        )
        workflow_runs = list(runs_payload.get("workflow_runs") or [])
        matched_run = _pick_workflow_run(
            workflow_runs,
            ref_name=ref_name,
            dispatched_after=dispatched_at,
        )
        if matched_run is None:
            time.sleep(polling_interval)
            continue
        result["run"] = {
            "id": matched_run.get("id"),
            "number": matched_run.get("run_number"),
            "status": str(matched_run.get("status") or ""),
            "conclusion": str(matched_run.get("conclusion") or ""),
            "html_url": str(matched_run.get("html_url") or ""),
            "created_at": str(matched_run.get("created_at") or ""),
            "updated_at": str(matched_run.get("updated_at") or ""),
            "head_branch": str(matched_run.get("head_branch") or ""),
        }
        if str(matched_run.get("status") or "") == "completed":
            conclusion = str(matched_run.get("conclusion") or "").strip().lower()
            result["status"] = "passed" if conclusion in {"success", ""} else "blocked"
            result["ok"] = result["status"] == "passed"
            result["summary"] = (
                f"workflow_dispatch completed with {conclusion or 'success'} for "
                f"{repo_slug}@{ref_name}"
            )
            return result
        time.sleep(polling_interval)

    raise RuntimeError(
        f"Timed out waiting for workflow run: repo={repo_slug} workflow={workflow_name} ref={ref_name}"
    )


def dispatch_release_live_gates(args: argparse.Namespace) -> dict[str, Any]:
    return dispatch_release_live_gates_request(
        project_root=args.project_root,
        repo=args.repo,
        ref=args.ref,
        workflow=args.workflow,
        runner_labels=args.runner_labels,
        target_channel=args.target_channel,
        target_environment=args.target_environment,
        release_manifest_path=args.release_manifest_path,
        runner_profile_path=args.runner_profile_path,
        approvers=args.approvers,
        providers=args.providers,
        artifact_dir=args.artifact_dir,
        fail_on_warnings=args.fail_on_warnings,
        wait=args.wait,
        poll_interval=args.poll_interval,
        wait_timeout=args.wait_timeout,
        dispatch_timeout=args.dispatch_timeout,
        token=args.token,
        token_env_names=args.token_env_names,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Dispatch the GitHub release-live-gates workflow and optionally wait for completion.")
    parser.add_argument("--project-root", default=str(REPO_ROOT), help="Local project root used to infer repo/ref from git when omitted.")
    parser.add_argument("--repo", default="", help="GitHub repo in owner/name form. Defaults to origin remote.")
    parser.add_argument("--ref", default="", help="Git ref/branch to dispatch. Defaults to current branch.")
    parser.add_argument("--workflow", default=DEFAULT_WORKFLOW, help="Workflow file name or workflow id to dispatch.")
    parser.add_argument("--runner-labels", default='["self-hosted","windows","godot"]', help="JSON array or comma-separated runner labels.")
    parser.add_argument("--target-channel", default="release", help="Workflow input: target_channel.")
    parser.add_argument("--target-environment", default="production", help="Workflow input: target_environment.")
    parser.add_argument("--release-manifest-path", default="api_server/static/dist/release_manifest.json", help="Workflow input: release_manifest_path.")
    parser.add_argument("--runner-profile-path", default="deployment/release_live_runner_profile.json", help="Workflow input: runner_profile_path.")
    parser.add_argument("--approvers", default="", help="Workflow input: comma-separated approvers.")
    parser.add_argument("--providers", default="codex,openai_api", help="Workflow input: comma-separated providers.")
    parser.add_argument("--artifact-dir", default="logs/reports/release_live_ci", help="Workflow input: artifact_dir.")
    parser.add_argument("--fail-on-warnings", action="store_true", help="Workflow input: fail_on_warnings=true.")
    parser.add_argument("--wait", action="store_true", help="Poll GitHub Actions until the dispatched run completes.")
    parser.add_argument("--poll-interval", type=float, default=15.0, help="Polling interval in seconds when --wait is enabled.")
    parser.add_argument("--wait-timeout", type=float, default=7200.0, help="Maximum seconds to wait for a run when --wait is enabled.")
    parser.add_argument("--dispatch-timeout", type=float, default=30.0, help="HTTP timeout in seconds for the dispatch request.")
    parser.add_argument("--token", default="", help="Explicit GitHub token. Prefer GH_TOKEN/GITHUB_TOKEN instead.")
    parser.add_argument("--preflight-only", action="store_true", help="Only build/export the dispatch preflight snapshot; do not call GitHub.")
    parser.add_argument("--preflight-report-path", default=DEFAULT_RELEASE_LIVE_DISPATCH_PREFLIGHT_PATH, help="JSON path for --preflight-only export.")
    parser.add_argument("--preflight-markdown-path", default=DEFAULT_RELEASE_LIVE_DISPATCH_PREFLIGHT_MARKDOWN_PATH, help="Markdown path for --preflight-only export.")
    parser.add_argument(
        "--token-env-names",
        default=",".join(DEFAULT_TOKEN_ENV_NAMES),
        help="Comma-separated environment variable names to search for a GitHub token.",
    )
    args = parser.parse_args(argv)

    try:
        if args.preflight_only:
            result = export_release_live_dispatch_preflight(
                args.project_root,
                repo=args.repo,
                ref=args.ref,
                workflow=args.workflow,
                runner_labels=args.runner_labels,
                target_channel=args.target_channel,
                target_environment=args.target_environment,
                release_manifest_path=args.release_manifest_path,
                runner_profile_path=args.runner_profile_path,
                approvers=args.approvers,
                providers=args.providers,
                artifact_dir=args.artifact_dir,
                fail_on_warnings=args.fail_on_warnings,
                token=args.token,
                token_env_names=args.token_env_names,
                report_path=args.preflight_report_path,
                markdown_path=args.preflight_markdown_path,
            )
        else:
            result = dispatch_release_live_gates(args)
    except Exception as exc:
        print(
            json.dumps(
                {
                    "ok": False,
                    "error": str(exc),
                    "error_type": type(exc).__name__,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 1

    print(json.dumps(result, ensure_ascii=False, indent=2))
    if args.wait and not bool(result.get("ok")):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

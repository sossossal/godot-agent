from __future__ import annotations

import json
import os
import re
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from .godot_cli import GodotCLI


RELEASE_LIVE_RUNNER_BASELINE_SCHEMA_VERSION = "1.0"
DEFAULT_RELEASE_LIVE_RUNNER_BASELINE_ROOT = "logs/reports"
DEFAULT_RELEASE_LIVE_RUNNER_PROFILE_PATH = "deployment/release_live_runner_profile.json"


def default_release_live_runner_baseline_report_path(*, target_channel: str = "release") -> str:
    normalized_target = str(target_channel or "release").strip().lower() or "release"
    return f"{DEFAULT_RELEASE_LIVE_RUNNER_BASELINE_ROOT}/release_live_runner_baseline_{normalized_target}.json"


def default_release_live_runner_profile_path() -> str:
    return DEFAULT_RELEASE_LIVE_RUNNER_PROFILE_PATH


def build_release_live_runner_baseline(
    project_root: str | Path,
    *,
    runtime_root: str | Path,
    target_channel: str = "release",
    target_environment: str = "",
    release_manifest_path: str = "api_server/static/dist/release_manifest.json",
    report_path: str = "",
    browser_path: str = "",
    config_path: str = "config.yaml",
    runner_profile_path: str = DEFAULT_RELEASE_LIVE_RUNNER_PROFILE_PATH,
    declared_runner_labels: list[str] | str | None = None,
) -> dict[str, Any]:
    resolved_project_root = Path(project_root).resolve()
    resolved_runtime_root = Path(runtime_root).resolve()
    normalized_target_channel = str(target_channel or "release").strip().lower() or "release"
    normalized_target_environment = str(target_environment or "").strip() or (
        "production" if normalized_target_channel == "release" else normalized_target_channel
    )
    relative_report_path = str(
        report_path or default_release_live_runner_baseline_report_path(target_channel=normalized_target_channel)
    ).strip() or default_release_live_runner_baseline_report_path(target_channel=normalized_target_channel)
    resolved_report_path = _resolve_relative_to(resolved_runtime_root, relative_report_path)
    resolved_config_path = _resolve_relative_to(resolved_project_root, config_path)
    resolved_release_manifest_path = _resolve_relative_to(resolved_runtime_root, release_manifest_path)
    resolved_runner_profile_path = _resolve_relative_to(
        resolved_project_root,
        runner_profile_path or default_release_live_runner_profile_path(),
    )

    checks: list[dict[str, Any]] = []
    recommendations: list[str] = []

    is_windows = sys.platform.startswith("win")
    runner_context = _collect_runner_context(is_windows=is_windows)
    runner_context["declared_runner_labels"] = _clean_text_list(declared_runner_labels)
    runner_profile = _load_release_live_runner_profile(
        resolved_runner_profile_path,
        target_channel=normalized_target_channel,
        target_environment=normalized_target_environment,
    )
    expected_runner_os = str(runner_profile.get("required_runner_os") or "").strip()
    actual_runner_os = str(runner_context.get("runner_os") or "").strip()
    actual_runner_arch = _normalize_runner_arch(str(runner_context.get("runner_arch") or ""))
    allowed_runner_names = [str(item).strip() for item in list(runner_profile.get("allowed_runner_names") or []) if str(item).strip()]
    required_runner_arches = [
        _normalize_runner_arch(item)
        for item in list(runner_profile.get("required_runner_arches") or [])
        if _normalize_runner_arch(item)
    ]
    required_runner_labels = _clean_text_list(runner_profile.get("required_runner_labels"))
    declared_runner_labels_set = {item.lower() for item in list(runner_context.get("declared_runner_labels") or [])}
    runner_profile["required_runner_arches"] = required_runner_arches
    runner_profile["allowed_runner_names"] = allowed_runner_names
    runner_profile["required_runner_labels"] = required_runner_labels
    runner_profile["runner_os_matches"] = (
        not expected_runner_os
        or _normalize_runner_os(actual_runner_os) == _normalize_runner_os(expected_runner_os)
    )
    runner_profile["runner_arch_matches"] = (
        not required_runner_arches
        or actual_runner_arch in required_runner_arches
    )
    runner_profile["runner_name_matches"] = (
        not allowed_runner_names
        or str(runner_context.get("runner_name") or "").strip().lower() in {item.lower() for item in allowed_runner_names}
    )
    runner_profile["runner_labels_match"] = (
        not required_runner_labels
        or all(item.lower() in declared_runner_labels_set for item in required_runner_labels)
    )

    checks.append(_build_check(
        "windows_host",
        "Windows Host",
        "passed" if is_windows else "blocked",
        f"runner host={sys.platform}",
        details={"platform": sys.platform, "required_platform": "win32"},
        recommendation="将 release-live-gates workflow 固定到 self-hosted Windows runner 上执行。" if not is_windows else "",
    ))

    python_version = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
    python_ok = sys.version_info.major == 3 and sys.version_info.minor >= 10
    checks.append(_build_check(
        "python_version",
        "Python Version",
        "passed" if python_ok else "blocked",
        f"python={python_version}",
        details={"python_version": python_version, "minimum_version": "3.10"},
        recommendation="切换到 Python 3.10 或更高版本后再执行 release-live-gates。" if not python_ok else "",
    ))
    checks.append(_build_check(
        "runner_profile_manifest",
        "Release Live Runner Profile",
        str(runner_profile.get("status") or "blocked"),
        str(runner_profile.get("message") or "release live runner profile missing"),
        details={
            "path": _relative_to_root(resolved_runner_profile_path, resolved_project_root),
            "exists": bool(runner_profile.get("exists")),
            "valid": bool(runner_profile.get("valid")),
            "profile_id": str(runner_profile.get("profile_id") or ""),
            "target_channel": normalized_target_channel,
            "target_environment": normalized_target_environment,
        },
        recommendation=str(runner_profile.get("recommendation") or ""),
    ))
    checks.append(_build_check(
        "runner_os_match",
        "Runner OS Profile Match",
        _runner_constraint_status(
            expected=bool(runner_profile.get("required_runner_os")),
            matched=bool(runner_profile.get("runner_os_matches", True)),
            target_channel=normalized_target_channel,
        ),
        (
            f"runner_os={runner_context.get('runner_os') or '-'} matches profile"
            if bool(runner_profile.get("runner_os_matches", True))
            else f"runner_os={runner_context.get('runner_os') or '-'} expected={runner_profile.get('required_runner_os') or '-'}"
        ),
        details={
            "runner_os": str(runner_context.get("runner_os") or ""),
            "required_runner_os": str(runner_profile.get("required_runner_os") or ""),
        },
        recommendation=(
            "把 workflow 固定到 profile 声明的 Windows runner 上，或更新 deployment/release_live_runner_profile.json。"
            if not bool(runner_profile.get("runner_os_matches", True)) and bool(runner_profile.get("required_runner_os"))
            else ""
        ),
    ))
    checks.append(_build_check(
        "runner_arch_match",
        "Runner Arch Profile Match",
        _runner_constraint_status(
            expected=bool(runner_profile.get("required_runner_arches")),
            matched=bool(runner_profile.get("runner_arch_matches", True)),
            target_channel=normalized_target_channel,
        ),
        (
            f"runner_arch={runner_context.get('runner_arch') or '-'} matches profile"
            if bool(runner_profile.get("runner_arch_matches", True))
            else (
                f"runner_arch={runner_context.get('runner_arch') or '-'} "
                f"expected={','.join(list(runner_profile.get('required_runner_arches') or [])) or '-'}"
            )
        ),
        details={
            "runner_arch": str(runner_context.get("runner_arch") or ""),
            "required_runner_arches": list(runner_profile.get("required_runner_arches") or []),
        },
        recommendation=(
            "使用 profile 允许的 runner arch，或更新 deployment/release_live_runner_profile.json 中的 required_runner_arches。"
            if not bool(runner_profile.get("runner_arch_matches", True)) and bool(runner_profile.get("required_runner_arches"))
            else ""
        ),
    ))
    checks.append(_build_check(
        "runner_name_match",
        "Runner Name Profile Match",
        _runner_constraint_status(
            expected=bool(runner_profile.get("allowed_runner_names")),
            matched=bool(runner_profile.get("runner_name_matches", True)),
            target_channel=normalized_target_channel,
        ),
        (
            f"runner_name={runner_context.get('runner_name') or '-'} matches profile"
            if bool(runner_profile.get("runner_name_matches", True))
            else (
                f"runner_name={runner_context.get('runner_name') or '-'} "
                f"allowed={','.join(list(runner_profile.get('allowed_runner_names') or [])) or '-'}"
            )
        ),
        details={
            "runner_name": str(runner_context.get("runner_name") or ""),
            "allowed_runner_names": list(runner_profile.get("allowed_runner_names") or []),
        },
        recommendation=(
            "把 allowed_runner_names 固定到真实 self-hosted runner，并确保 workflow 落到该 runner。"
            if not bool(runner_profile.get("runner_name_matches", True)) and bool(runner_profile.get("allowed_runner_names"))
            else ""
        ),
    ))
    checks.append(_build_check(
        "runner_labels_match",
        "Runner Labels Profile Match",
        _runner_constraint_status(
            expected=bool(runner_profile.get("required_runner_labels")),
            matched=bool(runner_profile.get("runner_labels_match", True)),
            target_channel=normalized_target_channel,
        ),
        (
            f"runner_labels={','.join(list(runner_context.get('declared_runner_labels') or [])) or '-'} match profile"
            if bool(runner_profile.get("runner_labels_match", True))
            else (
                f"runner_labels={','.join(list(runner_context.get('declared_runner_labels') or [])) or '-'} "
                f"expected={','.join(list(runner_profile.get('required_runner_labels') or [])) or '-'}"
            )
        ),
        details={
            "declared_runner_labels": list(runner_context.get("declared_runner_labels") or []),
            "required_runner_labels": list(runner_profile.get("required_runner_labels") or []),
        },
        recommendation=(
            "把 workflow_dispatch 的 runner_labels 固定到 profile 允许的 self-hosted 标签集合。"
            if not bool(runner_profile.get("runner_labels_match", True)) and bool(runner_profile.get("required_runner_labels"))
            else ""
        ),
    ))

    powershell_detection = _resolve_powershell_executable()
    powershell_path = str(powershell_detection.get("path") or "").strip()
    checks.append(_build_check(
        "powershell_available",
        "PowerShell",
        "passed" if powershell_path else "blocked",
        (
            f"detected via {powershell_detection.get('source_label')}: {powershell_path}"
            if powershell_path
            else "PowerShell executable not found"
        ),
        details=powershell_detection,
        recommendation="安装 PowerShell 7 或确认 powershell/pwsh 已加入 PATH。" if not powershell_path else "",
    ))

    configured_godot_path = _load_configured_godot_path(resolved_config_path)
    godot_detection = GodotCLI.detect_executable(configured_godot_path)
    godot_path = str(godot_detection.get("path") or "").strip()
    checks.append(_build_check(
        "godot_available",
        "Godot Executable",
        "passed" if godot_path else "blocked",
        (
            f"detected via {godot_detection.get('source_label')}: {godot_path}"
            if godot_path
            else "Godot executable not found"
        ),
        details={
            "path": godot_path,
            "source": str(godot_detection.get("source") or ""),
            "source_label": str(godot_detection.get("source_label") or ""),
            "config_path": str(resolved_config_path),
            "configured_path": str(configured_godot_path or ""),
        },
        recommendation="在 config.yaml 中声明 godot.executable_path，或通过 GODOT/GODOT_EXE/GODOT_PATH 暴露 Godot。" if not godot_path else "",
    ))

    browser_detection = _resolve_chromium_browser(browser_path)
    browser_resolved_path = str(browser_detection.get("path") or "").strip()
    checks.append(_build_check(
        "chromium_browser",
        "Chromium Browser",
        "passed" if browser_resolved_path else "blocked",
        (
            f"detected via {browser_detection.get('source_label')}: {browser_resolved_path}"
            if browser_resolved_path
            else "No Chromium-compatible browser found"
        ),
        details=browser_detection,
        recommendation="安装 Chrome 或 Edge，或在 workflow 中通过 --browser-path 提供可执行文件路径。" if not browser_resolved_path else "",
    ))

    required_paths = {
        "live_validation_script": resolved_project_root / "tools" / "run_full_live_validation.ps1",
        "portal_dom_smoke_script": resolved_project_root / "tools" / "run_portal_browser_smoke.ps1",
        "portal_click_smoke_script": resolved_project_root / "tools" / "run_portal_browser_click_smoke.py",
        "remote_mcp_live_script": resolved_project_root / "tools" / "run_remote_mcp_live_smoke.ps1",
        "live_ci_exporter": resolved_project_root / "tools" / "export_release_live_ci_artifacts.py",
        "release_manifest": resolved_release_manifest_path,
    }
    checks.append(_build_file_check(
        "full_live_validation_script",
        "Full Live Validation Script",
        required_paths["live_validation_script"],
        resolved_project_root,
        recommendation="确认 tools/run_full_live_validation.ps1 已随仓库 checkout 到 runner 上。",
    ))
    browser_scripts_present = required_paths["portal_dom_smoke_script"].exists() and required_paths["portal_click_smoke_script"].exists()
    checks.append(_build_check(
        "portal_browser_smoke_scripts",
        "Portal Browser Smoke Scripts",
        "passed" if browser_scripts_present else "blocked",
        (
            "portal DOM smoke and click smoke scripts are present"
            if browser_scripts_present
            else "Portal browser smoke scripts are missing"
        ),
        details={
            "portal_dom_smoke_script": _relative_to_root(required_paths["portal_dom_smoke_script"], resolved_project_root),
            "portal_dom_smoke_exists": required_paths["portal_dom_smoke_script"].exists(),
            "portal_click_smoke_script": _relative_to_root(required_paths["portal_click_smoke_script"], resolved_project_root),
            "portal_click_smoke_exists": required_paths["portal_click_smoke_script"].exists(),
        },
        recommendation="补齐 tools/run_portal_browser_smoke.ps1 与 tools/run_portal_browser_click_smoke.py。",
    ))
    checks.append(_build_file_check(
        "remote_mcp_live_script",
        "Remote MCP Live Smoke Script",
        required_paths["remote_mcp_live_script"],
        resolved_project_root,
        recommendation="确认 tools/run_remote_mcp_live_smoke.ps1 已进入 release runner 工作区。",
    ))
    checks.append(_build_file_check(
        "live_ci_exporter",
        "Live CI Artifact Exporter",
        required_paths["live_ci_exporter"],
        resolved_project_root,
        recommendation="确认 tools/export_release_live_ci_artifacts.py 已进入 release runner 工作区。",
    ))
    checks.append(_build_file_check(
        "release_manifest_present",
        "Release Manifest",
        required_paths["release_manifest"],
        resolved_runtime_root,
        recommendation="先生成并同步 api_server/static/dist/release_manifest.json，再执行 release-live-gates。",
    ))

    blocking_checks = [str(item.get("check_id") or "") for item in checks if str(item.get("status") or "") == "blocked"]
    warning_checks = [str(item.get("check_id") or "") for item in checks if str(item.get("status") or "") == "warning"]
    for item in checks:
        recommendation = str(item.get("recommendation") or "").strip()
        if recommendation and str(item.get("status") or "") in {"blocked", "warning"}:
            recommendations.append(recommendation)

    passed_check_count = sum(1 for item in checks if str(item.get("status") or "") == "passed")
    warning_check_count = sum(1 for item in checks if str(item.get("status") or "") == "warning")
    blocked_check_count = sum(1 for item in checks if str(item.get("status") or "") == "blocked")
    status = "blocked" if blocked_check_count else ("warning" if warning_check_count else "passed")
    payload = {
        "schema_version": RELEASE_LIVE_RUNNER_BASELINE_SCHEMA_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "status": status,
        "summary": (
            f"checks={len(checks)} / passed={passed_check_count} / "
            f"warning={warning_check_count} / blocked={blocked_check_count}"
        ),
        "project_root": str(resolved_project_root),
        "runtime_root": str(resolved_runtime_root),
        "target_channel": normalized_target_channel,
        "target_environment": normalized_target_environment,
        "report_path": _relative_to_root(resolved_report_path, resolved_runtime_root),
        "release_manifest_path": _relative_to_root(resolved_release_manifest_path, resolved_runtime_root),
        "runner_profile_path": _relative_to_root(resolved_runner_profile_path, resolved_project_root),
        "runner_profile_id": str(runner_profile.get("profile_id") or ""),
        "runner_name": str(runner_context.get("runner_name") or ""),
        "runner_os": str(runner_context.get("runner_os") or ""),
        "runner_arch": str(runner_context.get("runner_arch") or ""),
        "declared_runner_labels": list(runner_context.get("declared_runner_labels") or []),
        "github_actions": bool(runner_context.get("github_actions")),
        "github_workflow": str(runner_context.get("github_workflow") or ""),
        "github_job": str(runner_context.get("github_job") or ""),
        "github_run_id": str(runner_context.get("github_run_id") or ""),
        "github_run_attempt": str(runner_context.get("github_run_attempt") or ""),
        "python_version": python_version,
        "check_count": len(checks),
        "passed_check_count": passed_check_count,
        "warning_check_count": warning_check_count,
        "blocked_check_count": blocked_check_count,
        "blocking_checks": blocking_checks,
        "warning_checks": warning_checks,
        "checks": checks,
        "recommendations": recommendations,
        "detected_tools": {
            "powershell_executable": powershell_path,
            "godot_executable": godot_path,
            "godot_source": str(godot_detection.get("source") or ""),
            "godot_source_label": str(godot_detection.get("source_label") or ""),
            "browser_executable": browser_resolved_path,
            "browser_source": str(browser_detection.get("source") or ""),
            "browser_source_label": str(browser_detection.get("source_label") or ""),
        },
        "required_paths": {
            key: _relative_to_root(path, resolved_runtime_root if key == "release_manifest" else resolved_project_root)
            for key, path in required_paths.items()
        },
        "runner_profile": {
            "path": _relative_to_root(resolved_runner_profile_path, resolved_project_root),
            "exists": bool(runner_profile.get("exists")),
            "valid": bool(runner_profile.get("valid")),
            "profile_id": str(runner_profile.get("profile_id") or ""),
            "required_runner_os": str(runner_profile.get("required_runner_os") or ""),
            "required_runner_arches": list(runner_profile.get("required_runner_arches") or []),
            "required_runner_labels": list(runner_profile.get("required_runner_labels") or []),
            "allowed_runner_names": list(runner_profile.get("allowed_runner_names") or []),
        },
        "runner_context": dict(runner_context),
    }
    resolved_report_path.parent.mkdir(parents=True, exist_ok=True)
    resolved_report_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return payload


def _build_check(
    check_id: str,
    label: str,
    status: str,
    message: str,
    *,
    required: bool = True,
    details: dict[str, Any] | None = None,
    recommendation: str = "",
) -> dict[str, Any]:
    normalized_status = str(status or "blocked").strip().lower()
    if normalized_status not in {"passed", "warning", "blocked", "skipped"}:
        normalized_status = "blocked"
    return {
        "check_id": str(check_id or "").strip(),
        "label": str(label or "").strip(),
        "status": normalized_status,
        "required": bool(required),
        "message": str(message or "").strip(),
        "details": dict(details or {}),
        "recommendation": str(recommendation or "").strip(),
    }


def _build_file_check(
    check_id: str,
    label: str,
    path: Path,
    root: Path,
    *,
    recommendation: str,
) -> dict[str, Any]:
    exists = path.exists() and path.is_file()
    return _build_check(
        check_id,
        label,
        "passed" if exists else "blocked",
        f"path={_relative_to_root(path, root)}" if exists else f"missing {_relative_to_root(path, root)}",
        details={
            "path": _relative_to_root(path, root),
            "exists": exists,
        },
        recommendation="" if exists else recommendation,
    )


def _load_configured_godot_path(config_path: Path) -> str:
    if not config_path.exists():
        return ""
    try:
        source = config_path.read_text(encoding="utf-8")
        payload = yaml.safe_load(source) or {}
    except Exception:
        return _extract_godot_path_from_config_text(source if "source" in locals() else "")
    if not isinstance(payload, dict):
        return ""
    godot = payload.get("godot")
    if not isinstance(godot, dict):
        return ""
    return str(godot.get("executable_path") or "").strip()


def _extract_godot_path_from_config_text(source: str) -> str:
    match = re.search(r"(?m)^\s*executable_path\s*:\s*(.+?)\s*$", source or "")
    if not match:
        return ""
    return match.group(1).strip().strip('"').strip("'")


def _resolve_powershell_executable() -> dict[str, str]:
    for executable_name in ("pwsh", "powershell"):
        resolved = shutil.which(executable_name)
        if resolved:
            return {
                "path": resolved,
                "source": "path",
                "source_label": executable_name,
            }
    return {"path": "", "source": "", "source_label": ""}


def _resolve_chromium_browser(requested_path: str = "") -> dict[str, str]:
    candidates: list[tuple[str, str, str]] = []
    requested = str(requested_path or "").strip()
    if requested:
        candidates.append((requested, "argument", "--browser-path"))
    for env_key in ("BROWSER_PATH", "CHROME_PATH", "EDGE_PATH", "CHROME"):
        env_value = str(os.environ.get(env_key) or "").strip()
        if env_value:
            candidates.append((env_value, "env", env_key))
    for known_path in (
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    ):
        candidates.append((known_path, "well_known_path", known_path))

    for raw_path, source, source_label in candidates:
        resolved = _resolve_executable_candidate(raw_path)
        if resolved:
            return {
                "path": resolved,
                "source": source,
                "source_label": source_label,
            }

    for executable_name in ("chrome", "msedge", "chromium", "chromium-browser"):
        resolved = shutil.which(executable_name)
        if resolved:
            return {
                "path": resolved,
                "source": "path",
                "source_label": executable_name,
            }
    return {"path": "", "source": "", "source_label": ""}


def _resolve_executable_candidate(raw_path: str) -> str:
    candidate = Path(str(raw_path or "").strip().strip('"').strip("'"))
    if not str(candidate):
        return ""
    if candidate.exists() and candidate.is_file():
        return str(candidate.resolve())
    resolved = shutil.which(str(candidate))
    return str(resolved or "")


def _resolve_relative_to(root: Path, raw_path: str) -> Path:
    candidate = Path(str(raw_path or "").strip())
    if not str(candidate):
        return root.resolve()
    if candidate.is_absolute():
        return candidate.resolve()
    return (root / candidate).resolve()


def _collect_runner_context(*, is_windows: bool) -> dict[str, Any]:
    runner_os = str(os.environ.get("RUNNER_OS") or "").strip()
    runner_arch = str(os.environ.get("RUNNER_ARCH") or os.environ.get("PROCESSOR_ARCHITECTURE") or "").strip()
    return {
        "runner_name": str(os.environ.get("RUNNER_NAME") or "").strip(),
        "runner_os": runner_os or ("Windows" if is_windows else sys.platform),
        "runner_arch": _normalize_runner_arch(runner_arch),
        "github_actions": str(os.environ.get("GITHUB_ACTIONS") or "").strip().lower() == "true",
        "github_workflow": str(os.environ.get("GITHUB_WORKFLOW") or "").strip(),
        "github_job": str(os.environ.get("GITHUB_JOB") or "").strip(),
        "github_run_id": str(os.environ.get("GITHUB_RUN_ID") or "").strip(),
        "github_run_attempt": str(os.environ.get("GITHUB_RUN_ATTEMPT") or "").strip(),
    }


def _load_release_live_runner_profile(
    profile_path: Path,
    *,
    target_channel: str,
    target_environment: str,
) -> dict[str, Any]:
    missing_status = "blocked" if str(target_channel or "").strip().lower() == "release" else "warning"
    display_path = _relative_to_root(profile_path, profile_path.parents[1] if len(profile_path.parents) > 1 else profile_path.parent)
    payload: dict[str, Any] = {
        "exists": profile_path.exists() and profile_path.is_file(),
        "valid": False,
        "status": missing_status,
        "message": f"missing {display_path}",
        "recommendation": "补齐 deployment/release_live_runner_profile.json，把 release self-hosted runner 的受管约束沉淀到仓库中。",
        "profile_id": "",
        "required_runner_os": "",
        "required_runner_arches": [],
        "required_runner_labels": [],
        "allowed_runner_names": [],
        "runner_os_matches": True,
        "runner_arch_matches": True,
        "runner_name_matches": True,
        "runner_labels_match": True,
    }
    if not payload["exists"]:
        return payload
    try:
        source = json.loads(profile_path.read_text(encoding="utf-8"))
    except Exception:
        payload["message"] = f"invalid {display_path}"
        payload["recommendation"] = "修复 deployment/release_live_runner_profile.json 的 JSON 结构后再执行 release-live-gates。"
        return payload
    if not isinstance(source, dict):
        payload["message"] = "release live runner profile manifest must be an object"
        payload["recommendation"] = "修复 deployment/release_live_runner_profile.json 的顶层结构后再执行 release-live-gates。"
        return payload
    profiles = [item for item in list(source.get("profiles") or []) if isinstance(item, dict)]
    matched_profile = next(
        (
            item
            for item in profiles
            if _runner_profile_matches(
                item,
                target_channel=target_channel,
                target_environment=target_environment,
            )
        ),
        None,
    )
    payload["valid"] = True
    if not matched_profile:
        payload["message"] = f"no runner profile matched {target_channel} -> {target_environment}"
        payload["recommendation"] = "在 deployment/release_live_runner_profile.json 中补一条匹配当前 channel/environment 的 profile。"
        return payload
    required_runner_os = str(matched_profile.get("required_runner_os") or "").strip()
    required_runner_arches = [
        normalized
        for normalized in (
            _normalize_runner_arch(item)
            for item in list(matched_profile.get("required_runner_arches") or [])
        )
        if normalized
    ]
    allowed_runner_names = [
        str(item).strip()
        for item in list(matched_profile.get("allowed_runner_names") or [])
        if str(item).strip()
    ]
    payload.update(
        {
            "status": "passed",
            "message": f"profile={str(matched_profile.get('profile_id') or 'runner_profile').strip()}",
            "recommendation": "",
            "profile_id": str(matched_profile.get("profile_id") or "runner_profile").strip(),
            "required_runner_os": required_runner_os,
            "required_runner_arches": required_runner_arches,
            "required_runner_labels": _clean_text_list(matched_profile.get("required_runner_labels")),
            "allowed_runner_names": allowed_runner_names,
        }
    )
    return payload


def _runner_profile_matches(
    profile: dict[str, Any],
    *,
    target_channel: str,
    target_environment: str,
) -> bool:
    channels = [str(item).strip().lower() for item in list(profile.get("target_channels") or []) if str(item).strip()]
    environments = [str(item).strip().lower() for item in list(profile.get("target_environments") or []) if str(item).strip()]
    normalized_target_channel = str(target_channel or "").strip().lower()
    normalized_target_environment = str(target_environment or "").strip().lower()
    if channels and normalized_target_channel not in channels and "*" not in channels and "all" not in channels:
        return False
    if environments and normalized_target_environment not in environments and "*" not in environments and "all" not in environments:
        return False
    return True


def _runner_constraint_status(*, expected: bool, matched: bool, target_channel: str) -> str:
    if not expected or matched:
        return "passed"
    return "blocked" if str(target_channel or "").strip().lower() == "release" else "warning"


def _normalize_runner_arch(value: str) -> str:
    normalized = str(value or "").strip().lower()
    if normalized in {"amd64", "x86_64"}:
        return "x64"
    if normalized in {"x64", "arm64", "x86"}:
        return normalized
    return normalized


def _normalize_runner_os(value: str) -> str:
    normalized = str(value or "").strip().lower()
    if normalized in {"win32", "windows"}:
        return "windows"
    return normalized


def _clean_text_list(value: Any) -> list[str]:
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            return []
        try:
            payload = json.loads(stripped)
        except Exception:
            parts = stripped.replace(";", ",").replace("\r", ",").replace("\n", ",").split(",")
        else:
            if isinstance(payload, list):
                parts = payload
            else:
                parts = [stripped]
    elif isinstance(value, (list, tuple, set)):
        parts = list(value)
    else:
        return []

    cleaned: list[str] = []
    seen: set[str] = set()
    for item in parts:
        text = str(item).strip()
        if not text:
            continue
        lowered = text.lower()
        if lowered in seen:
            continue
        cleaned.append(text)
        seen.add(lowered)
    return cleaned


def _relative_to_root(path: Path, root: Path) -> str:
    try:
        return str(path.resolve().relative_to(root.resolve())).replace("\\", "/")
    except Exception:
        return str(path.resolve()).replace("\\", "/")

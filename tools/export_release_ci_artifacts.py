from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from agent_system.tools.release_execution import (  # noqa: E402
    build_release_execution_report,
    run_release_execution,
)
from agent_system.tools.doctor import default_doctor_report_path  # noqa: E402
from agent_system.tools.release_live_runner_baseline import (  # noqa: E402
    default_release_live_runner_profile_path,
)
from agent_system.tools.release_boundary import (  # noqa: E402
    default_release_distribution_delivery_path,
    default_release_identity_boundary_path,
)
from agent_system.tools.release_distribution import (  # noqa: E402
    default_release_distribution_archive_dir,
    default_release_distribution_archive_path,
    default_release_distribution_archive_sha256_path,
    default_release_distribution_bundle_dir,
    default_release_distribution_channel_dir,
    default_release_distribution_channel_latest_path,
    default_release_distribution_channel_releases_path,
    default_release_distribution_channel_report_path,
    default_release_distribution_handoff_dir,
    default_release_distribution_publish_handoff_dir,
    default_release_distribution_publish_receipts_dir,
    default_release_distribution_signing_handoff_dir,
    default_release_distribution_install_smoke_report_path,
    default_release_distribution_report_path,
    export_release_distribution_archive,
    export_release_distribution_bundle,
    export_release_distribution_channel_index,
    export_release_distribution_handoff,
    export_release_distribution_publish_handoff,
    export_release_distribution_signing_handoff,
    export_release_distribution_install_smoke,
    record_release_distribution_publish_receipt,
)
from agent_system.tools.release_promotion import (  # noqa: E402
    build_deployment_rehearsal_report,
    build_release_promotion_evidence_report,
    build_release_promotion_plan,
    build_release_review_bundle_report,
    build_rollback_rehearsal_report,
)
from agent_system.tools.release_promotion_history import (  # noqa: E402
    build_release_promotion_history,
    build_release_promotion_history_report,
    record_release_promotion_event,
)
from agent_system.tools.release_request_auth import (  # noqa: E402
    default_release_request_auth_identity_handoff_dir,
    default_release_request_auth_identity_audit_report_path,
    default_release_request_auth_rotation_audit_report_path,
    default_release_request_auth_posture_report_path,
    export_release_request_auth_identity_handoff,
    export_release_request_auth_identity_audit_report,
    export_release_request_auth_rotation_audit_report,
    export_release_request_auth_posture_report,
)
from agent_system.tools.release_live_event_stream import (  # noqa: E402
    build_release_live_event_stream,
)
from agent_system.tools.release_runtime_assembly import (  # noqa: E402
    build_release_runtime_assembly_snapshot,
)
from agent_system.contracts import normalize_release_artifact_manifest  # noqa: E402


_SYNTHETIC_RELEASE_DIR = Path("api_server/static/dist/web_release_validation_ci")
_CI_TARGET_CHANNEL = "staging"
_CI_TARGET_ENVIRONMENT = "staging"
_CI_SYNTHETIC_BUILD_ID = f"web-{_CI_TARGET_CHANNEL}-ci-001"
_BOOTSTRAP_PREVIEW_TIMEOUT_SECONDS = 30
_CI_APPROVERS = ["qa_lead", "tech_lead", "producer"]
_CANONICAL_FILE_PATHS = [
    Path(default_release_live_runner_profile_path()),
    Path(default_release_distribution_delivery_path()),
    Path(default_release_identity_boundary_path()),
    Path("deployment/release_identity_registry.json"),
    Path("deployment/release_access_policy.json"),
    Path("deployment/release_promotion_history.json"),
    Path("deployment/release_execution_status.json"),
    Path("deployment/release_channels.json"),
    Path("logs/reports/clean_machine_bootstrap.json"),
    Path(default_doctor_report_path()),
    Path("logs/reports/full_live_validation.json"),
    Path(default_release_request_auth_identity_audit_report_path(target_channel=_CI_TARGET_CHANNEL)),
    Path(default_release_request_auth_rotation_audit_report_path(target_channel=_CI_TARGET_CHANNEL)),
    Path(default_release_request_auth_posture_report_path(action="promotion_record", target_channel=_CI_TARGET_CHANNEL)),
    Path(default_release_request_auth_posture_report_path(action="release_execution", target_channel=_CI_TARGET_CHANNEL)),
    Path(default_release_distribution_report_path(target_channel=_CI_TARGET_CHANNEL)),
    Path(default_release_distribution_install_smoke_report_path(target_channel=_CI_TARGET_CHANNEL)),
    Path(default_release_distribution_channel_report_path(target_channel=_CI_TARGET_CHANNEL)),
    Path(default_release_distribution_channel_latest_path(target_channel=_CI_TARGET_CHANNEL)),
    Path(default_release_distribution_channel_releases_path(target_channel=_CI_TARGET_CHANNEL)),
    Path(default_release_distribution_archive_path(target_channel=_CI_TARGET_CHANNEL, build_id=_CI_SYNTHETIC_BUILD_ID)),
    Path(default_release_distribution_archive_sha256_path(target_channel=_CI_TARGET_CHANNEL, build_id=_CI_SYNTHETIC_BUILD_ID)),
    Path("api_server/static/dist/release_manifest.json"),
    Path("api_server/static/dist/release_notes.md"),
    Path("api_server/static/dist/qa_gate_report.md"),
]


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _normalize_flow_statuses(value: Any) -> dict[str, str]:
    if not isinstance(value, dict):
        return {}

    normalized: dict[str, str] = {}
    for raw_key, raw_value in value.items():
        key = str(raw_key).strip()
        if not key or (key != "flow" and not key.endswith("_flow")):
            continue
        status = str(raw_value).strip().lower()
        if status in {"passed", "warning", "blocked", "skipped"}:
            normalized[key] = status
    return normalized


def _build_runtime_lane_summaries(full_live_validation: dict[str, Any]) -> list[dict[str, Any]]:
    details = dict(full_live_validation.get("details") or {})
    raw_items = list(details.get("lane_artifacts") or [])
    if not raw_items:
        raw_items = list(details.get("step_statuses") or [])

    lanes: list[dict[str, Any]] = []
    for index, item in enumerate(raw_items, start=1):
        if not isinstance(item, dict):
            continue
        raw = dict(item)
        lane_id = str(raw.get("lane_id") or raw.get("id") or f"lane_{index}").strip() or f"lane_{index}"
        lanes.append({
            "lane_id": lane_id,
            "label": str(raw.get("label") or raw.get("lane_id") or raw.get("id") or lane_id).strip() or lane_id,
            "status": str(raw.get("status") or "skipped").strip() or "skipped",
            "summary": str(raw.get("summary") or "").strip(),
            "report_path": str(raw.get("report_path") or "").strip(),
            "artifact_paths": [str(path).strip() for path in list(raw.get("artifact_paths") or []) if str(path).strip()],
            "flow_statuses": _normalize_flow_statuses(raw.get("flow_statuses")),
        })
    return lanes


def _build_execution_readiness_summary(execution_status: dict[str, Any]) -> dict[str, Any]:
    latest_execution = dict(execution_status.get("latest_execution") or {})
    actions = [dict(item) for item in list(latest_execution.get("release_delivery_readiness_next_actions") or [])]
    return {
        "status": str(latest_execution.get("release_delivery_readiness_status") or "warning"),
        "summary": str(latest_execution.get("release_delivery_readiness_summary") or ""),
        "next_action_count": int(latest_execution.get("release_delivery_readiness_next_action_count") or len(actions)),
        "next_action_ids": [
            str(item.get("action_id") or "").strip()
            for item in actions
            if str(item.get("action_id") or "").strip()
        ],
        "blocking_checks": [
            str(item).strip()
            for item in list(latest_execution.get("release_delivery_readiness_blocking_checks") or [])
            if str(item).strip()
        ],
        "warning_checks": [
            str(item).strip()
            for item in list(latest_execution.get("release_delivery_readiness_warning_checks") or [])
            if str(item).strip()
        ],
    }


def _default_full_live_validation_lane_report_path(lane_id: str) -> str:
    normalized = "".join(
        char.lower() if char.isalnum() else "_"
        for char in str(lane_id or "").strip()
    ).strip("_")
    while "__" in normalized:
        normalized = normalized.replace("__", "_")
    return f"logs/reports/full_live_validation_lanes/{normalized or 'lane'}.json"


def _write_full_live_validation_lane_report(
    reports_dir: Path,
    *,
    lane_id: str,
    label: str,
    status: str,
    summary: str,
    executed_at: str,
    artifact_paths: list[str],
    release_binding: dict[str, Any],
    flow_statuses: dict[str, str] | None = None,
) -> str:
    report_relative_path = _default_full_live_validation_lane_report_path(lane_id)
    report_path = reports_dir / "full_live_validation_lanes" / Path(report_relative_path).name
    _write_json(
        report_path,
        {
            "schema_version": "1.0",
            "lane_id": lane_id,
            "label": label,
            "status": status,
            "summary": summary,
            "executed_at": executed_at,
            "report_path": report_relative_path,
            "full_report_path": "logs/reports/full_live_validation.json",
            "artifact_paths": artifact_paths,
            "release_binding": release_binding,
            "details": {
                "artifact_paths": artifact_paths,
                "flow_statuses": _normalize_flow_statuses(flow_statuses),
            },
        },
    )
    return report_relative_path


def _write_doctor_self_check_report(
    reports_dir: Path,
    *,
    report_path: str,
) -> dict[str, Any]:
    report_file = reports_dir / Path(report_path).name
    payload = {
        "schema_version": "1.0",
        "generated_at": "2026-04-15T09:10:00Z",
        "ok": True,
        "config_path": "config.yaml",
        "report_path": report_path,
        "check_count": 6,
        "passed_check_count": 6,
        "failed_check_count": 0,
        "action_item_count": 0,
        "blocking_checks": [],
        "summary": "checks=6 / passed=6 / failed=0 / action_items=0",
        "checks": [
            {"id": "python_version", "name": "Python 版本", "passed": True, "status": "passed", "message": "Python 3.12.0", "help": "", "remediation_actions": []},
            {"id": "config_parse", "name": "配置解析", "passed": True, "status": "passed", "message": "config.yaml 格式正确", "help": "", "remediation_actions": []},
            {"id": "godot_install", "name": "Godot 安装", "passed": True, "status": "passed", "message": "已通过 config.yaml 的 godot.executable_path 找到可执行文件: C:/Godot/godot.exe", "help": "", "remediation_actions": []},
            {"id": "plugin_sync", "name": "插件文件", "passed": True, "status": "passed", "message": "运行态插件与分发副本已同步", "help": "", "remediation_actions": []},
            {"id": "runtime_directories", "name": "目录结构", "passed": True, "status": "passed", "message": "核心运行目录完整", "help": "", "remediation_actions": []},
            {"id": "project_layout", "name": "文件树规范", "passed": True, "status": "passed", "message": "受管目录命名与落点通过 (42 files checked)", "help": "", "remediation_actions": []},
        ],
        "action_items": [],
    }
    _write_json(report_file, payload)
    return payload


def _relative_to_repo(path: Path) -> str:
    try:
        return path.resolve().relative_to(REPO_ROOT.resolve()).as_posix()
    except Exception:
        return str(path.resolve())


def _copy_file(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)


def _copy_tree(source: Path, destination: Path) -> None:
    if destination.exists():
        shutil.rmtree(destination, ignore_errors=True)
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(source, destination)


def _capture_managed_state(paths: list[Path], directories: list[Path], backup_root: Path) -> list[dict[str, Any]]:
    snapshots: list[dict[str, Any]] = []
    for target in [*paths, *directories]:
        kind = "dir" if target in directories else "file"
        absolute = target.resolve()
        backup_path = backup_root / _relative_to_repo(absolute)
        exists = absolute.exists()
        if exists:
            if kind == "dir":
                _copy_tree(absolute, backup_path)
            else:
                _copy_file(absolute, backup_path)
        snapshots.append({
            "path": absolute,
            "kind": kind,
            "exists": exists,
            "backup_path": backup_path,
        })
    return snapshots


def _restore_managed_state(snapshots: list[dict[str, Any]]) -> None:
    for item in reversed(snapshots):
        target = Path(item["path"])
        kind = str(item["kind"])
        backup_path = Path(item["backup_path"])
        existed = bool(item["exists"])

        if target.exists():
            if target.is_dir():
                shutil.rmtree(target, ignore_errors=True)
            else:
                target.unlink()

        if existed and backup_path.exists():
            if kind == "dir":
                _copy_tree(backup_path, target)
            else:
                _copy_file(backup_path, target)


def _prepare_release_fixture(*, channel: str) -> dict[str, Any]:
    release_dir = (REPO_ROOT / _SYNTHETIC_RELEASE_DIR).resolve()
    dist_dir = (REPO_ROOT / "api_server" / "static" / "dist").resolve()
    release_dir.mkdir(parents=True, exist_ok=True)
    dist_dir.mkdir(parents=True, exist_ok=True)

    manifest = {
        "schema_version": "1.0",
        "build_id": f"web-{channel}-ci-001",
        "version": f"0.1.0-{channel}+ci1",
        "channel": channel,
        "preset_name": "Web",
        "platform": "web",
        "generated_at": "2026-04-15T09:00:00Z",
        "output_path": "api_server/static/dist/web_release_validation_ci/index.html",
        "release_dir": "api_server/static/dist/web_release_validation_ci",
        "release_url": "/portal/dist/index.html",
        "versioned_release_url": "/portal/dist/web_release_validation_ci/index.html",
        "build_log_path": "api_server/static/dist/web_release_validation_ci/build.log",
        "release_notes_path": "api_server/static/dist/web_release_validation_ci/release_notes.md",
        "release_manifest_path": "api_server/static/dist/web_release_validation_ci/release_manifest.json",
        "feature": {
            "schema_version": "1.0",
            "feature_id": "feature-ci-release",
            "owner": "release_engineer",
            "priority": "high",
            "risk": "medium",
            "feature_status": "approved",
        },
        "change_summary": [
            "ci artifact export fixture",
            "promotion, review, and execution reports exported",
        ],
        "acceptance_checklist": [
            {"label": "smoke", "status": "ready"},
            {"label": "promotion evidence", "status": "ready"},
            {"label": "execution rehearsal", "status": "ready"},
        ],
        "quality_gate": {
            "schema_version": "1.0",
            "passed": True,
            "channel": channel,
            "preset_name": "Web",
            "checks": [
                {"name": "feature_status", "status": "passed", "message": "ok"},
                {"name": "smoke_test", "status": "passed", "message": "ok"},
                {"name": "performance_budget", "status": "passed", "message": "ok"},
                {"name": "fps_budget", "status": "passed", "message": "ok"},
                {"name": "memory_peak_budget", "status": "passed", "message": "ok"},
                {"name": "screenshot_diff", "status": "passed", "message": "ok"},
                {"name": "draw_call_budget", "status": "passed", "message": "ok"},
                {"name": "node_count_budget", "status": "passed", "message": "ok"},
                {"name": "texture_memory_budget", "status": "passed", "message": "ok"},
                {"name": "frame_spike_budget", "status": "passed", "message": "ok"},
                {"name": "draw_call_regression", "status": "passed", "message": "ok"},
                {"name": "telemetry_health", "status": "passed", "message": "ok"},
            ],
            "blocked_checks": [],
            "warning_checks": [],
            "metrics": {
                "scene_load_ms": 280,
                "fps": 60.0,
                "memory_peak_mb": 136.0,
                "draw_call_count": 210,
                "node_count": 180,
                "texture_memory_mb": 96,
                "frame_spike_ms": 12,
            },
        },
        "qa_evidence": {
            "schema_version": "1.0",
            "scene_path": "res://scenes/main_scene.tscn",
            "smoke_status": "passed",
            "smoke_message": "scene ok",
            "assertion_status": "passed",
            "assertion_message": "assertions ok",
            "assertion_node_count": 3,
            "asserted_nodes": ["Player", "HUD", "Portal"],
            "screenshot_status": "passed",
            "screenshot_message": "visual ok",
            "screenshot_path": "logs/test_artifacts/release_validation_ci.png",
            "screenshot_diff_ratio": 0.0112,
            "max_screenshot_diff_ratio": 0.05,
            "metrics": {"scene_load_ms": 280, "fps": 60.0, "memory_peak_mb": 136.0},
        },
        "files": [
            {"path": "index.html", "size": 13, "sha256": "abc"},
            {"path": "release_notes.md", "size": 16, "sha256": "def"},
            {"path": "qa_gate_report.md", "size": 10, "sha256": "ghi"},
        ],
        "rollback_hint": "restore web_release_validation_ci",
    }

    manifest_path = release_dir / "release_manifest.json"
    release_notes_path = release_dir / "release_notes.md"
    qa_gate_report_path = release_dir / "qa_gate_report.md"
    build_log_path = release_dir / "build.log"
    output_path = release_dir / "index.html"

    _write_text(release_notes_path, "# Release Validation Notes\n")
    _write_text(qa_gate_report_path, "# Release Validation QA Gate\n")
    _write_text(build_log_path, "build ok\n")
    _write_text(output_path, "<html></html>\n")
    _write_json(manifest_path, manifest)

    _write_json(dist_dir / "release_manifest.json", manifest)
    _write_text(dist_dir / "release_notes.md", "# Stable Release Validation Notes\n")
    _write_text(dist_dir / "qa_gate_report.md", "# Stable Release Validation QA Gate\n")

    return manifest


def _prepare_runtime_reports(release_manifest: dict[str, Any]) -> None:
    reports_dir = (REPO_ROOT / "logs" / "reports").resolve()
    reports_dir.mkdir(parents=True, exist_ok=True)
    executed_at = "2026-04-15T09:15:00Z"
    doctor_report_relative = default_doctor_report_path()
    doctor_report = _write_doctor_self_check_report(
        reports_dir,
        report_path=doctor_report_relative,
    )
    release_binding = {
        "status": "passed",
        "manifest_source": "stable",
        "manifest_path": "api_server/static/dist/release_manifest.json",
        "build_id": str(release_manifest.get("build_id") or ""),
        "version": str(release_manifest.get("version") or ""),
        "channel": str(release_manifest.get("channel") or ""),
        "generated_at": str(release_manifest.get("generated_at") or ""),
        "release_dir": str(release_manifest.get("release_dir") or ""),
        "output_path": str(release_manifest.get("output_path") or ""),
        "release_url": str(release_manifest.get("release_url") or ""),
        "versioned_release_url": str(release_manifest.get("versioned_release_url") or ""),
    }
    _write_json(
        reports_dir / "clean_machine_bootstrap.json",
        {
            "ok": True,
            "preview": False,
            "doctor_report_path": doctor_report_relative,
            "doctor_report": {
                "path": doctor_report_relative,
                "exists": True,
                "ok": True,
                "summary": str(doctor_report.get("summary") or ""),
                "check_count": int(doctor_report.get("check_count") or 0),
                "passed_check_count": int(doctor_report.get("passed_check_count") or 0),
                "failed_check_count": int(doctor_report.get("failed_check_count") or 0),
                "action_item_count": int(doctor_report.get("action_item_count") or 0),
                "blocking_checks": list(doctor_report.get("blocking_checks") or []),
            },
            "steps": [
                {"id": "create_venv", "status": "passed"},
                {"id": "install_requirements", "status": "passed"},
                {"id": "sync_plugin", "status": "passed"},
                {
                    "id": "doctor",
                    "status": "passed",
                    "report_path": doctor_report_relative,
                    "report_exists": True,
                    "doctor_ok": True,
                    "doctor_action_item_count": int(doctor_report.get("action_item_count") or 0),
                },
            ],
            "blocking_issues": [],
        },
    )
    step_fixtures = [
        {
            "id": "godot_live_sandbox",
            "label": "Godot Live Sandbox",
            "status": "passed",
            "summary": "Godot live sandbox passed",
            "artifact_paths": [
                "logs/live_sandbox_state.json",
                "logs/api_server_8000.out",
            ],
        },
        {
            "id": "portal_dom_smoke",
            "label": "Portal DOM Smoke",
            "status": "passed",
            "summary": "Portal DOM smoke passed",
            "artifact_paths": [
                "logs/test_artifacts/portal_browser_smoke_8012.html",
                "logs/portal_browser_api_8012.out",
            ],
        },
        {
            "id": "portal_click_smoke",
            "label": "Portal Click Smoke",
            "status": "passed",
            "summary": "Portal click smoke passed",
            "artifact_paths": [
                "logs/test_artifacts/portal_click_chrome_8014.out",
                "logs/portal_click_api_8014.out",
            ],
            "flow_statuses": {
                "flow": "passed",
                "release_promotion_history_flow": "passed",
                "release_promotion_history_report_flow": "passed",
            },
        },
        {
            "id": "remote_mcp_live",
            "label": "Remote MCP Live Smoke",
            "status": "passed",
            "summary": "Remote MCP live smoke passed",
            "artifact_paths": [
                "logs/remote_mcp_8766.out",
                "logs/remote_mcp_8766.err",
            ],
        },
    ]
    full_live_steps = []
    for item in step_fixtures:
        report_relative_path = _write_full_live_validation_lane_report(
            reports_dir,
            lane_id=str(item["id"]),
            label=str(item["label"]),
            status=str(item["status"]),
            summary=str(item["summary"]),
            executed_at=executed_at,
            artifact_paths=list(item["artifact_paths"]),
            release_binding=release_binding,
            flow_statuses=dict(item.get("flow_statuses") or {}),
        )
        full_live_steps.append(
            {
                "id": item["id"],
                "label": item["label"],
                "status": item["status"],
                "summary": item["summary"],
                "report_path": report_relative_path,
                "artifact_paths": list(item["artifact_paths"]),
                "details": {
                    "artifact_paths": list(item["artifact_paths"]),
                    "report_path": report_relative_path,
                    "flow_statuses": dict(item.get("flow_statuses") or {}),
                },
            }
        )
    _write_json(
        reports_dir / "full_live_validation.json",
        {
            "schema_version": "1.1",
            "ok": True,
            "executed_at": executed_at,
            "release_binding": release_binding,
            "steps": full_live_steps,
            "blocking_issues": [],
        },
    )
    export_release_request_auth_posture_report(
        REPO_ROOT,
        runtime_root=REPO_ROOT,
        action="promotion_record",
        target_channel=_CI_TARGET_CHANNEL,
        target_environment=_CI_TARGET_ENVIRONMENT,
    )
    export_release_request_auth_posture_report(
        REPO_ROOT,
        runtime_root=REPO_ROOT,
        action="release_execution",
        target_channel=_CI_TARGET_CHANNEL,
        target_environment=_CI_TARGET_ENVIRONMENT,
    )
    export_release_request_auth_rotation_audit_report(
        REPO_ROOT,
        runtime_root=REPO_ROOT,
        target_channel=_CI_TARGET_CHANNEL,
        target_environment=_CI_TARGET_ENVIRONMENT,
    )
    export_release_request_auth_identity_audit_report(
        REPO_ROOT,
        runtime_root=REPO_ROOT,
        target_channel=_CI_TARGET_CHANNEL,
        target_environment=_CI_TARGET_ENVIRONMENT,
    )
    export_release_request_auth_identity_handoff(
        REPO_ROOT,
        runtime_root=REPO_ROOT,
        target_channel=_CI_TARGET_CHANNEL,
        target_environment=_CI_TARGET_ENVIRONMENT,
        release_manifest_path=str(release_manifest.get("release_manifest_path") or ""),
    )
    export_release_distribution_bundle(
        REPO_ROOT,
        runtime_root=REPO_ROOT,
        target_channel=_CI_TARGET_CHANNEL,
        target_environment=_CI_TARGET_ENVIRONMENT,
        release_manifest_path=str(release_manifest.get("release_manifest_path") or ""),
    )
    export_release_distribution_install_smoke(
        REPO_ROOT,
        runtime_root=REPO_ROOT,
        target_channel=_CI_TARGET_CHANNEL,
        target_environment=_CI_TARGET_ENVIRONMENT,
        release_manifest_path=str(release_manifest.get("release_manifest_path") or ""),
    )
    export_release_distribution_archive(
        REPO_ROOT,
        runtime_root=REPO_ROOT,
        target_channel=_CI_TARGET_CHANNEL,
        target_environment=_CI_TARGET_ENVIRONMENT,
        release_manifest_path=str(release_manifest.get("release_manifest_path") or ""),
    )
    export_release_distribution_channel_index(
        REPO_ROOT,
        runtime_root=REPO_ROOT,
        target_channel=_CI_TARGET_CHANNEL,
        target_environment=_CI_TARGET_ENVIRONMENT,
        release_manifest_path=str(release_manifest.get("release_manifest_path") or ""),
    )
    export_release_distribution_handoff(
        REPO_ROOT,
        runtime_root=REPO_ROOT,
        target_channel=_CI_TARGET_CHANNEL,
        target_environment=_CI_TARGET_ENVIRONMENT,
        release_manifest_path=str(release_manifest.get("release_manifest_path") or ""),
    )
    export_release_distribution_signing_handoff(
        REPO_ROOT,
        runtime_root=REPO_ROOT,
        target_channel=_CI_TARGET_CHANNEL,
        target_environment=_CI_TARGET_ENVIRONMENT,
        release_manifest_path=str(release_manifest.get("release_manifest_path") or ""),
    )
    export_release_distribution_publish_handoff(
        REPO_ROOT,
        runtime_root=REPO_ROOT,
        target_channel=_CI_TARGET_CHANNEL,
        target_environment=_CI_TARGET_ENVIRONMENT,
        release_manifest_path=str(release_manifest.get("release_manifest_path") or ""),
    )
    record_release_distribution_publish_receipt(
        REPO_ROOT,
        runtime_root=REPO_ROOT,
        target_channel=_CI_TARGET_CHANNEL,
        target_environment=_CI_TARGET_ENVIRONMENT,
        release_manifest_path=str(release_manifest.get("release_manifest_path") or ""),
        target_id="staging_ci_artifact",
        status="published",
        external_reference="ci-artifact-staging-001",
        artifact_url="artifact://release-validation/staging/web-staging-ci-001",
        operator="release_validation_ci",
        published_at="2026-04-15T09:20:00Z",
        notes=["synthetic staging publish receipt for non-live rehearsal"],
    )


def _prepare_bootstrap_preview_fixture(repo_dir: Path) -> None:
    shutil.rmtree(repo_dir, ignore_errors=True)
    (repo_dir / "tools").mkdir(parents=True, exist_ok=True)
    (repo_dir / "addons" / "godot_agent").mkdir(parents=True, exist_ok=True)
    (repo_dir / "tests").mkdir(parents=True, exist_ok=True)
    (repo_dir / "requirements.txt").write_text("pytest==7.4.4\n", encoding="utf-8")
    (repo_dir / "config.yaml").write_text("godot:\n  executable_path: \"\"\n", encoding="utf-8")
    (repo_dir / "tools" / "sync_plugin.ps1").write_text(
        "[ordered]@{ ok = $true } | ConvertTo-Json -Depth 3\n",
        encoding="utf-8",
    )
    for relative_path in (
        "tests/test_godot_cli.py",
        "tests/test_cli.py",
        "tests/test_agent_compatibility.py",
        "tests/test_api.py",
    ):
        (repo_dir / relative_path).write_text("pass\n", encoding="utf-8")


def _run_bootstrap_preview(repo_dir: Path) -> dict[str, Any]:
    command = [
        "powershell",
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        str(REPO_ROOT / "tools" / "bootstrap_clean_machine.ps1"),
        "-RepoRoot",
        str(repo_dir),
        "-Preview",
        "-IncludeSmoke",
    ]
    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
            timeout=_BOOTSTRAP_PREVIEW_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired as exc:
        return {
            "status": "warning",
            "ok": False,
            "repo_root": str(repo_dir),
            "summary": f"bootstrap preview timed out after {_BOOTSTRAP_PREVIEW_TIMEOUT_SECONDS}s",
            "blocking_checks": [],
            "warning_checks": ["bootstrap_preview_timeout"],
            "stdout_excerpt": str(exc.stdout or "")[-2000:],
            "stderr_excerpt": str(exc.stderr or "")[-2000:],
        }
    if completed.returncode != 0:
        raise RuntimeError(f"bootstrap preview failed:\nSTDOUT:\n{completed.stdout}\nSTDERR:\n{completed.stderr}")
    return json.loads(completed.stdout)


def _snapshot_outputs(output_dir: Path, generated_files: list[Path]) -> None:
    snapshot_files = [
        (
            REPO_ROOT / "logs" / "reports" / "clean_machine_bootstrap.json",
            output_dir / "runtime_reports" / "clean_machine_bootstrap.json",
        ),
        (
            REPO_ROOT / default_doctor_report_path(),
            output_dir / "runtime_reports" / "doctor_self_check.json",
        ),
        (
            REPO_ROOT / "logs" / "reports" / "full_live_validation.json",
            output_dir / "runtime_reports" / "full_live_validation.json",
        ),
        (
            REPO_ROOT / default_release_request_auth_identity_audit_report_path(
                target_channel=_CI_TARGET_CHANNEL,
            ),
            output_dir / "runtime_reports" / "release_request_auth_identity_audit_staging.json",
        ),
        (
            REPO_ROOT / default_release_request_auth_rotation_audit_report_path(
                target_channel=_CI_TARGET_CHANNEL,
            ),
            output_dir / "runtime_reports" / "release_request_auth_rotation_audit_staging.json",
        ),
        (
            REPO_ROOT / default_release_request_auth_posture_report_path(
                action="promotion_record",
                target_channel=_CI_TARGET_CHANNEL,
            ),
            output_dir / "runtime_reports" / "release_request_auth_posture_promotion_record_staging.json",
        ),
        (
            REPO_ROOT / default_release_request_auth_posture_report_path(
                action="release_execution",
                target_channel=_CI_TARGET_CHANNEL,
            ),
            output_dir / "runtime_reports" / "release_request_auth_posture_release_execution_staging.json",
        ),
        (
            REPO_ROOT / default_release_distribution_report_path(
                target_channel=_CI_TARGET_CHANNEL,
            ),
            output_dir / "runtime_reports" / "release_distribution_bundle_staging.json",
        ),
        (
            REPO_ROOT / default_release_distribution_install_smoke_report_path(
                target_channel=_CI_TARGET_CHANNEL,
            ),
            output_dir / "runtime_reports" / "release_distribution_install_smoke_staging.json",
        ),
        (
            REPO_ROOT / default_release_distribution_channel_report_path(
                target_channel=_CI_TARGET_CHANNEL,
            ),
            output_dir / "runtime_reports" / "release_distribution_channel_staging.json",
        ),
        (
            REPO_ROOT / default_release_live_runner_profile_path(),
            output_dir / "deployment" / "release_live_runner_profile.json",
        ),
        (
            REPO_ROOT / default_release_distribution_delivery_path(),
            output_dir / "deployment" / "release_distribution_delivery.json",
        ),
        (
            REPO_ROOT / default_release_identity_boundary_path(),
            output_dir / "deployment" / "release_identity_boundary.json",
        ),
        (
            REPO_ROOT / "deployment" / "release_identity_registry.json",
            output_dir / "deployment" / "release_identity_registry.json",
        ),
        (
            REPO_ROOT / "deployment" / "release_promotion_history.json",
            output_dir / "deployment" / "release_promotion_history.json",
        ),
        (
            REPO_ROOT / "deployment" / "release_execution_status.json",
            output_dir / "deployment" / "release_execution_status.json",
        ),
        (
            REPO_ROOT / "deployment" / "release_channels.json",
            output_dir / "deployment" / "release_channels.json",
        ),
        (
            REPO_ROOT / "deployment" / "release_access_policy.json",
            output_dir / "deployment" / "release_access_policy.json",
        ),
    ]
    for source, destination in snapshot_files:
        if source.exists():
            _copy_file(source, destination)
            generated_files.append(destination)

    full_live_lane_reports_source = (REPO_ROOT / "logs" / "reports" / "full_live_validation_lanes").resolve()
    full_live_lane_reports_destination = output_dir / "runtime_reports" / "full_live_validation_lanes"
    if full_live_lane_reports_source.exists():
        _copy_tree(full_live_lane_reports_source, full_live_lane_reports_destination)
        generated_files.extend(path for path in full_live_lane_reports_destination.rglob("*") if path.is_file())

    release_bundle_source = (REPO_ROOT / _SYNTHETIC_RELEASE_DIR).resolve()
    release_bundle_destination = output_dir / "release_bundle"
    if release_bundle_source.exists():
        _copy_tree(release_bundle_source, release_bundle_destination)
        generated_files.extend(path for path in release_bundle_destination.rglob("*") if path.is_file())

    distribution_bundle_source = (
        REPO_ROOT / default_release_distribution_bundle_dir(
            target_channel=_CI_TARGET_CHANNEL,
            build_id=_CI_SYNTHETIC_BUILD_ID,
        )
    ).resolve()
    distribution_bundle_destination = output_dir / "release_distribution_bundle"
    if distribution_bundle_source.exists():
        _copy_tree(distribution_bundle_source, distribution_bundle_destination)
        generated_files.extend(path for path in distribution_bundle_destination.rglob("*") if path.is_file())

    distribution_archive_source = (
        REPO_ROOT / default_release_distribution_archive_dir(
            target_channel=_CI_TARGET_CHANNEL,
            build_id=_CI_SYNTHETIC_BUILD_ID,
        )
    ).resolve()
    distribution_archive_destination = output_dir / "release_distribution_archive"
    if distribution_archive_source.exists():
        _copy_tree(distribution_archive_source, distribution_archive_destination)
        generated_files.extend(path for path in distribution_archive_destination.rglob("*") if path.is_file())

    distribution_channel_source = (
        REPO_ROOT / default_release_distribution_channel_dir(
            target_channel=_CI_TARGET_CHANNEL,
        )
    ).resolve()
    distribution_channel_destination = output_dir / "release_distribution_channel"
    if distribution_channel_source.exists():
        _copy_tree(distribution_channel_source, distribution_channel_destination)
        generated_files.extend(path for path in distribution_channel_destination.rglob("*") if path.is_file())

    distribution_handoff_source = (
        REPO_ROOT / default_release_distribution_handoff_dir(
            target_channel=_CI_TARGET_CHANNEL,
            build_id=_CI_SYNTHETIC_BUILD_ID,
        )
    ).resolve()
    distribution_handoff_destination = output_dir / "release_distribution_handoff"
    if distribution_handoff_source.exists():
        _copy_tree(distribution_handoff_source, distribution_handoff_destination)
        generated_files.extend(path for path in distribution_handoff_destination.rglob("*") if path.is_file())

    distribution_signing_source = (
        REPO_ROOT / default_release_distribution_signing_handoff_dir(
            target_channel=_CI_TARGET_CHANNEL,
            build_id=_CI_SYNTHETIC_BUILD_ID,
        )
    ).resolve()
    distribution_signing_destination = output_dir / "release_distribution_signing"
    if distribution_signing_source.exists():
        _copy_tree(distribution_signing_source, distribution_signing_destination)
        generated_files.extend(path for path in distribution_signing_destination.rglob("*") if path.is_file())

    distribution_publish_source = (
        REPO_ROOT / default_release_distribution_publish_handoff_dir(
            target_channel=_CI_TARGET_CHANNEL,
            build_id=_CI_SYNTHETIC_BUILD_ID,
        )
    ).resolve()
    distribution_publish_destination = output_dir / "release_distribution_publish"
    if distribution_publish_source.exists():
        _copy_tree(distribution_publish_source, distribution_publish_destination)
        generated_files.extend(path for path in distribution_publish_destination.rglob("*") if path.is_file())

    distribution_publish_receipts_source = (
        REPO_ROOT / default_release_distribution_publish_receipts_dir(
            target_channel=_CI_TARGET_CHANNEL,
            build_id=_CI_SYNTHETIC_BUILD_ID,
        )
    ).resolve()
    distribution_publish_receipts_destination = output_dir / "release_distribution_publish_receipts"
    if distribution_publish_receipts_source.exists():
        _copy_tree(distribution_publish_receipts_source, distribution_publish_receipts_destination)
        generated_files.extend(path for path in distribution_publish_receipts_destination.rglob("*") if path.is_file())

    identity_handoff_source = (
        REPO_ROOT / default_release_request_auth_identity_handoff_dir(
            target_channel=_CI_TARGET_CHANNEL,
            target_environment=_CI_TARGET_ENVIRONMENT,
        )
    ).resolve()
    identity_handoff_destination = output_dir / "release_request_auth_identity_handoff"
    if identity_handoff_source.exists():
        _copy_tree(identity_handoff_source, identity_handoff_destination)
        generated_files.extend(path for path in identity_handoff_destination.rglob("*") if path.is_file())


def export_artifacts(output_dir: Path) -> list[Path]:
    temp_root = REPO_ROOT / "tests" / ".tmp_release_ci_export"
    bootstrap_dir = temp_root / "bootstrap_fixture"
    backup_root = temp_root / "managed_state_backup"
    shutil.rmtree(temp_root, ignore_errors=True)
    temp_root.mkdir(parents=True, exist_ok=True)

    if output_dir.exists():
        if output_dir.is_dir():
            shutil.rmtree(output_dir, ignore_errors=True)
        else:
            output_dir.unlink()
    output_dir.mkdir(parents=True, exist_ok=True)

    _prepare_bootstrap_preview_fixture(bootstrap_dir)
    generated_files: list[Path] = []

    bootstrap_preview = _run_bootstrap_preview(bootstrap_dir)
    bootstrap_preview_path = output_dir / "bootstrap_clean_machine_preview.json"
    _write_json(bootstrap_preview_path, bootstrap_preview)
    generated_files.append(bootstrap_preview_path)

    managed_files = [(REPO_ROOT / relative).resolve() for relative in _CANONICAL_FILE_PATHS]
    managed_directories = [
        (REPO_ROOT / "logs" / "reports" / "full_live_validation_lanes").resolve(),
        (REPO_ROOT / _SYNTHETIC_RELEASE_DIR).resolve(),
        (
            REPO_ROOT / default_release_distribution_bundle_dir(
                target_channel=_CI_TARGET_CHANNEL,
                build_id=_CI_SYNTHETIC_BUILD_ID,
            )
        ).resolve(),
        (
            REPO_ROOT / default_release_distribution_archive_dir(
                target_channel=_CI_TARGET_CHANNEL,
                build_id=_CI_SYNTHETIC_BUILD_ID,
            )
        ).resolve(),
        (
            REPO_ROOT / default_release_distribution_channel_dir(
                target_channel=_CI_TARGET_CHANNEL,
            )
        ).resolve(),
        (
            REPO_ROOT / default_release_distribution_handoff_dir(
                target_channel=_CI_TARGET_CHANNEL,
                build_id=_CI_SYNTHETIC_BUILD_ID,
            )
        ).resolve(),
        (
            REPO_ROOT / default_release_distribution_signing_handoff_dir(
                target_channel=_CI_TARGET_CHANNEL,
                build_id=_CI_SYNTHETIC_BUILD_ID,
            )
        ).resolve(),
        (
            REPO_ROOT / default_release_distribution_publish_handoff_dir(
                target_channel=_CI_TARGET_CHANNEL,
                build_id=_CI_SYNTHETIC_BUILD_ID,
            )
        ).resolve(),
        (
            REPO_ROOT / default_release_distribution_publish_receipts_dir(
                target_channel=_CI_TARGET_CHANNEL,
                build_id=_CI_SYNTHETIC_BUILD_ID,
            )
        ).resolve(),
        (
            REPO_ROOT / default_release_request_auth_identity_handoff_dir(
                target_channel=_CI_TARGET_CHANNEL,
                target_environment=_CI_TARGET_ENVIRONMENT,
            )
        ).resolve(),
    ]
    snapshots = _capture_managed_state(managed_files, managed_directories, backup_root)

    try:
        release_manifest = _prepare_release_fixture(channel=_CI_TARGET_CHANNEL)
        release_manifest_path = str(release_manifest["release_manifest_path"])
        _prepare_runtime_reports(release_manifest)

        promotion_plan = build_release_promotion_plan(
            REPO_ROOT,
            runtime_root=REPO_ROOT,
            target_channel=_CI_TARGET_CHANNEL,
            target_environment=_CI_TARGET_ENVIRONMENT,
            release_manifest_path=release_manifest_path,
            approvers=list(_CI_APPROVERS),
            providers=["codex", "openai_api"],
            mode="advisory",
            fail_on_warnings=False,
        )
        if bool(promotion_plan.get("should_block")):
            raise RuntimeError(
                "release promotion plan is blocked: "
                + ", ".join(list(promotion_plan.get("blocking_checks") or []))
            )

        promotion_plan_path = output_dir / "release_promotion_plan.json"
        _write_json(promotion_plan_path, promotion_plan)
        generated_files.append(promotion_plan_path)

        evidence_report_path = output_dir / "release_promotion_evidence_bundle.md"
        _write_text(evidence_report_path, build_release_promotion_evidence_report(promotion_plan))
        generated_files.append(evidence_report_path)

        review_bundle_report_path = output_dir / "release_review_bundle.md"
        _write_text(review_bundle_report_path, build_release_review_bundle_report(promotion_plan))
        generated_files.append(review_bundle_report_path)

        deployment_report_path = output_dir / "release_promotion_deployment_rehearsal.md"
        _write_text(deployment_report_path, build_deployment_rehearsal_report(promotion_plan))
        generated_files.append(deployment_report_path)

        rollback_report_path = output_dir / "release_promotion_rollback_rehearsal.md"
        _write_text(rollback_report_path, build_rollback_rehearsal_report(promotion_plan))
        generated_files.append(rollback_report_path)

        promotion_record = record_release_promotion_event(
            REPO_ROOT,
            runtime_root=REPO_ROOT,
            target_channel=_CI_TARGET_CHANNEL,
            target_environment=_CI_TARGET_ENVIRONMENT,
            release_manifest_path=release_manifest_path,
            approvers=list(_CI_APPROVERS),
            providers=["codex", "openai_api"],
            mode="advisory",
            decision="approved",
            executed_by="ci_release",
            note="ci export fixture approval",
            signoff_source="github_actions",
        )
        promotion_history = build_release_promotion_history(
            REPO_ROOT,
            runtime_root=REPO_ROOT,
            target_channel=_CI_TARGET_CHANNEL,
            limit=5,
        )
        promotion_history_path = output_dir / "release_promotion_history.json"
        _write_json(
            promotion_history_path,
            {
                "record_result": promotion_record,
                "history": promotion_history,
            },
        )
        generated_files.append(promotion_history_path)

        promotion_history_report_path = output_dir / "release_promotion_history.md"
        _write_text(
            promotion_history_report_path,
            build_release_promotion_history_report(promotion_history),
        )
        generated_files.append(promotion_history_report_path)

        execution_result = run_release_execution(
            REPO_ROOT,
            runtime_root=REPO_ROOT,
            target_channel=_CI_TARGET_CHANNEL,
            target_environment=_CI_TARGET_ENVIRONMENT,
            release_manifest_path=release_manifest_path,
            approvers=list(_CI_APPROVERS),
            providers=["codex", "openai_api"],
            mode="advisory",
            fail_on_warnings=False,
            operation="canary",
            rollout_percentage=20,
            executed_by="ci_release",
            note="ci execution export",
        )
        if bool(dict(execution_result.get("execution") or {}).get("should_block")):
            raise RuntimeError(
                "release execution is blocked: "
                + ", ".join(list(dict(execution_result.get("execution") or {}).get("blocking_checks") or []))
            )

        execution_result_path = output_dir / "release_execution_status.json"
        _write_json(execution_result_path, execution_result)
        generated_files.append(execution_result_path)

        channels_path = output_dir / "release_channel_bindings.json"
        canonical_channels_path = REPO_ROOT / "deployment" / "release_channels.json"
        if canonical_channels_path.exists():
            _write_json(channels_path, json.loads(canonical_channels_path.read_text(encoding="utf-8")))
        else:
            _write_json(channels_path, {"schema_version": "1.0", "channels": []})
        generated_files.append(channels_path)

        execution_report_path = output_dir / "release_execution_report.md"
        _write_text(
            execution_report_path,
            build_release_execution_report(execution_result["execution_status"]),
        )
        generated_files.append(execution_report_path)

        _snapshot_outputs(output_dir, generated_files)

        runtime_lane_summaries = _build_runtime_lane_summaries(
            dict(execution_result.get("execution_status", {}).get("full_live_validation") or {})
        )
        release_summary = dict(
            execution_result.get("execution_status", {})
            .get("release_candidate_checklist", {})
            .get("release_summary")
            or {}
        )
        execution_readiness_summary = _build_execution_readiness_summary(
            dict(execution_result.get("execution_status") or {})
        )
        runtime_assembly = build_release_runtime_assembly_snapshot(
            REPO_ROOT,
            runtime_root=REPO_ROOT,
            route_kind="ci_rehearsal",
            target_channel=_CI_TARGET_CHANNEL,
            target_environment=_CI_TARGET_ENVIRONMENT,
            actor_id="ci_release",
            invocation_source="release_validation_workflow",
            route_id=f"ci_rehearsal:{_CI_TARGET_CHANNEL}:{_CI_TARGET_ENVIRONMENT}",
            session_id=_CI_SYNTHETIC_BUILD_ID,
        )
        event_stream = build_release_live_event_stream(
            generated_at=str(execution_result.get("execution_status", {}).get("latest_execution", {}).get("executed_at") or ""),
            target_channel=_CI_TARGET_CHANNEL,
            target_environment=_CI_TARGET_ENVIRONMENT,
            release_build_id=_CI_SYNTHETIC_BUILD_ID,
            release_version=str(
                execution_result.get("execution_status", {}).get("release_candidate_checklist", {}).get("release_summary", {}).get("version")
                or ""
            ),
            release_channel=_CI_TARGET_CHANNEL,
            invocation={
                "source": "release_validation_workflow",
                "providers": ["codex", "openai_api"],
                "approvers": list(_CI_APPROVERS),
                "mode": "advisory",
                "fail_on_warnings": False,
                "executed_by": "ci_release",
                "note": "release validation workflow synthetic replay",
            },
            runtime_assembly=runtime_assembly,
            ci_gate=dict(execution_result.get("execution_status", {}).get("release_live_ci_summary", {}).get("details", {}).get("ci_gate") or {
                "status": "passed",
                "should_block": False,
                "fail_on_warnings": False,
                "blocking_checks": [],
                "warning_checks": [],
                "evaluated_check_count": 0,
            }),
            runtime_lanes={
                "full_live_validation": runtime_lane_summaries,
            },
            workflow_steps=[
                {
                    "step_id": "release_validation_rehearsal",
                    "label": "Release validation rehearsal",
                    "status": "passed",
                    "outcome": "success",
                    "always_run": False,
                    "message": "",
                }
            ],
            human_signoffs={
                "status": "skipped",
                "required_signoffs": list(_CI_APPROVERS),
                "provided_signoffs": [],
                "missing_signoffs": list(_CI_APPROVERS),
            },
            path="release_live_ci_events.json",
            source="ci_rehearsal_export",
        )
        event_stream_path = output_dir / "release_live_ci_events.json"
        _write_json(event_stream_path, event_stream)
        generated_files.append(event_stream_path)

        artifact_manifest_path = output_dir / "artifact_manifest.json"
        report_files = {
            "bootstrap_preview": "bootstrap_clean_machine_preview.json",
            "promotion_plan": "release_promotion_plan.json",
            "evidence_bundle": "release_promotion_evidence_bundle.md",
            "review_bundle": "release_review_bundle.md",
            "deployment_rehearsal": "release_promotion_deployment_rehearsal.md",
            "rollback_rehearsal": "release_promotion_rollback_rehearsal.md",
            "promotion_history": "release_promotion_history.json",
            "promotion_history_report": "release_promotion_history.md",
            "execution_status": "release_execution_status.json",
            "execution_report": "release_execution_report.md",
            "event_stream": "release_live_ci_events.json",
            "artifact_manifest": "artifact_manifest.json",
        }
        generated_file_paths = [
            str(path.relative_to(output_dir)).replace("\\", "/")
            for path in generated_files
            if path.exists()
        ]
        generated_file_paths.append("artifact_manifest.json")
        _write_json(
            artifact_manifest_path,
            normalize_release_artifact_manifest({
                "project_root": ".",
                "runtime_root": ".",
                "target_channel": _CI_TARGET_CHANNEL,
                "target_environment": _CI_TARGET_ENVIRONMENT,
                "ci_mode": "non_live_staging_rehearsal",
                "synthetic_release_dir": _SYNTHETIC_RELEASE_DIR.as_posix(),
                "release_manifest_path": release_manifest_path,
                "release_build_id": str(release_summary.get("build_id") or _CI_SYNTHETIC_BUILD_ID),
                "release_version": str(release_summary.get("version") or ""),
                "release_channel": str(release_summary.get("channel") or _CI_TARGET_CHANNEL),
                "release_summary": release_summary,
                "runtime_assembly": runtime_assembly,
                "event_stream": event_stream,
                "execution_delivery_readiness": execution_readiness_summary,
                "report_files": report_files,
                "generated_files": generated_file_paths,
                "runtime_lanes": {
                    "full_live_validation": runtime_lane_summaries,
                },
            }),
        )
        generated_files.append(artifact_manifest_path)
        return generated_files
    finally:
        _restore_managed_state(snapshots)
        shutil.rmtree(temp_root, ignore_errors=True)


def main() -> int:
    parser = argparse.ArgumentParser(description="Export non-live release validation artifacts for CI.")
    parser.add_argument(
        "--output-dir",
        default=str(REPO_ROOT / "logs" / "reports" / "release_validation_ci"),
        help="Directory to write generated JSON/Markdown artifacts into.",
    )
    args = parser.parse_args()
    output_dir = Path(args.output_dir).resolve()

    generated_files = export_artifacts(output_dir)
    print(
        json.dumps(
            {
                "ok": True,
                "output_dir": str(output_dir),
                "file_count": len(generated_files),
                "files": [str(path) for path in generated_files],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

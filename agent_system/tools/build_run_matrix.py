"""
Build/run matrix builder.

P15 turns platform delivery targets, production gates, RC checks, and local
verification lanes into one executable matrix contract for Portal, API, and MCP
callers.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from agent_system.contracts import (
    BUILD_RUN_MATRIX_SCHEMA_VERSION,
    PERFORMANCE_SUMMARY_SCHEMA_VERSION,
    normalize_build_run_matrix,
    normalize_platform_delivery_profile,
)
from agent_system.tools.performance_analysis import GamePerformanceAnalyzer
from agent_system.tools.production_scale import build_production_readiness, list_production_scenarios
from agent_system.tools.release_candidate import build_release_candidate_checklist


DEFAULT_PLATFORM_DELIVERY_MANIFEST_PATH = "deployment/platform_delivery.json"

_RUN_LANES: List[Dict[str, Any]] = [
    {
        "lane_id": "non_live_regression",
        "label": "Full Non-live Regression",
        "scenario_ids": ["vertical_slice_2d", "content_pipeline", "release_candidate"],
        "execution_mode": "non_live",
        "command": 'python -m pytest -m "not live" -q',
        "script_path": "",
        "endpoint": "",
        "required": True,
        "default_selected": True,
        "required_paths": ["tests"],
        "notes": ["Shared repo regression lane. Run before browser or live automation."],
    },
    {
        "lane_id": "portal_dom_smoke",
        "label": "Portal DOM Smoke",
        "scenario_ids": ["content_pipeline", "release_candidate"],
        "execution_mode": "browser",
        "command": r"pwsh -File .\tools\run_portal_browser_smoke.ps1",
        "script_path": "tools/run_portal_browser_smoke.ps1",
        "endpoint": "",
        "required": True,
        "default_selected": True,
        "required_paths": ["tools/run_portal_browser_smoke.ps1"],
        "notes": ["Requires Chromium/Edge and PowerShell 7."],
    },
    {
        "lane_id": "portal_click_smoke",
        "label": "Portal Click Smoke",
        "scenario_ids": ["content_pipeline", "release_candidate"],
        "execution_mode": "browser",
        "command": r"python .\tools\run_portal_browser_click_smoke.py",
        "script_path": "tools/run_portal_browser_click_smoke.py",
        "endpoint": "",
        "required": True,
        "default_selected": True,
        "required_paths": ["tools/run_portal_browser_click_smoke.py"],
        "notes": ["Uses Chromium DevTools Protocol and a temp project under tests/."],
    },
    {
        "lane_id": "godot_live_sandbox",
        "label": "Godot Live Sandbox",
        "scenario_ids": ["vertical_slice_2d", "content_pipeline"],
        "execution_mode": "live",
        "command": r".\tools\run_live_sandbox_tests.ps1 -ApiPort 8011",
        "script_path": "tools/run_live_sandbox_tests.ps1",
        "endpoint": "",
        "required": False,
        "default_selected": False,
        "required_paths": ["tools/run_live_sandbox_tests.ps1", "sandbox_project"],
        "notes": ["Requires local Godot editor runtime and the live sandbox project."],
    },
    {
        "lane_id": "remote_mcp_live",
        "label": "Remote MCP Live Smoke",
        "scenario_ids": ["release_candidate"],
        "execution_mode": "remote_mcp",
        "command": r".\tools\run_remote_mcp_live_smoke.ps1",
        "script_path": "tools/run_remote_mcp_live_smoke.ps1",
        "endpoint": "/mcp/remote-manifest",
        "required": False,
        "default_selected": False,
        "required_paths": ["tools/run_remote_mcp_live_smoke.ps1", "bridge/remote_mcp_server.py"],
        "notes": ["Validates HTTP MCP bridge and shared tool schemas."],
    },
    {
        "lane_id": "full_live_validation",
        "label": "Full Live Validation",
        "scenario_ids": ["release_candidate"],
        "execution_mode": "live",
        "command": r".\tools\run_full_live_validation.ps1",
        "script_path": "tools/run_full_live_validation.ps1",
        "endpoint": "",
        "required": False,
        "default_selected": False,
        "required_paths": [
            "tools/run_full_live_validation.ps1",
            "tools/run_live_sandbox_tests.ps1",
            "tools/run_portal_browser_smoke.ps1",
            "tools/run_portal_browser_click_smoke.py",
            "tools/run_remote_mcp_live_smoke.ps1",
        ],
        "notes": ["Runs Godot live, Portal browser smoke, and Remote MCP live smoke in one pass."],
    },
]


def build_build_run_matrix(
    project_root: str | Path,
    runtime_root: Optional[str | Path] = None,
    *,
    manifest_path: str = "",
    scenario_ids: Optional[List[str]] = None,
    mode: str = "strict",
    fail_on_warnings: bool = False,
) -> Dict[str, Any]:
    resolved_project_root = Path(project_root).resolve()
    resolved_runtime_root = Path(runtime_root or Path.cwd()).resolve()
    normalized_mode = _normalize_mode(mode)
    resolved_manifest_path = _resolve_project_path(
        resolved_project_root,
        manifest_path or DEFAULT_PLATFORM_DELIVERY_MANIFEST_PATH,
    )
    selected_scenarios = _select_scenarios(scenario_ids)
    selected_scenario_ids = [item["scenario_id"] for item in selected_scenarios]

    platform_profile = _load_platform_delivery_profile(
        resolved_project_root,
        resolved_manifest_path,
    )
    release_candidate = build_release_candidate_checklist(
        resolved_project_root,
        runtime_root=resolved_runtime_root,
        release_manifest_path="",
        mode=normalized_mode,
        fail_on_warnings=fail_on_warnings,
    )

    rows: List[Dict[str, Any]] = []
    rows.append(_build_platform_baseline_row(platform_profile))
    rows.extend(_build_platform_export_rows(platform_profile))
    rows.extend(_build_production_gate_rows(
        resolved_project_root,
        resolved_runtime_root,
        selected_scenarios,
        mode=normalized_mode,
        fail_on_warnings=fail_on_warnings,
    ))
    if "release_candidate" in selected_scenario_ids:
        rows.append(_build_release_candidate_row(release_candidate))
    rows.append(_build_runtime_performance_sampling_row(
        resolved_project_root,
        resolved_runtime_root,
        selected_scenario_ids,
    ))
    rows.extend(_build_run_lane_rows(resolved_runtime_root, selected_scenario_ids))
    manifest_display = _display_project_path(resolved_project_root, resolved_manifest_path)

    payload = normalize_build_run_matrix({
        "project_root": str(resolved_project_root),
        "runtime_root": str(resolved_runtime_root),
        "manifest_path": manifest_display,
        "platform_delivery_profile": platform_profile,
        "release_candidate_checklist": release_candidate,
        "selected_scenario_ids": selected_scenario_ids,
        "scenarios": selected_scenarios,
        "mode": normalized_mode,
        "fail_on_warnings": fail_on_warnings,
        "rows": rows,
        "default_sequence": [row["row_id"] for row in rows if row.get("default_selected")],
        "notes": _build_notes(
            platform_profile,
            resolved_project_root,
            resolved_manifest_path,
            selected_scenario_ids,
        ),
        "recommendations": _build_recommendations(rows, selected_scenarios),
        "contract_versions": {
            "build_run_matrix": BUILD_RUN_MATRIX_SCHEMA_VERSION,
            "platform_delivery_profile": platform_profile.get("schema_version", ""),
            "production_scenarios": list_production_scenarios().get("schema_version", ""),
            "release_candidate_checklist": release_candidate.get("schema_version", ""),
            "performance_summary": PERFORMANCE_SUMMARY_SCHEMA_VERSION,
        },
    })
    return payload


def _normalize_mode(value: str) -> str:
    normalized = str(value or "strict").strip().lower()
    return normalized if normalized in {"strict", "advisory"} else "strict"


def _resolve_project_path(project_root: Path, raw_path: str) -> Path:
    relative = str(raw_path or DEFAULT_PLATFORM_DELIVERY_MANIFEST_PATH).strip()
    if relative.startswith("res://"):
        relative = relative[6:]
    return (project_root / relative).resolve()


def _load_platform_delivery_profile(project_root: Path, manifest_path: Path) -> Dict[str, Any]:
    payload: Dict[str, Any] = {}
    if manifest_path.exists():
        try:
            payload = json.loads(manifest_path.read_text(encoding="utf-8"))
        except Exception:
            payload = {}
    return normalize_platform_delivery_profile({
        "manifest_path": _display_project_path(project_root, manifest_path),
        "platforms": list(payload.get("platforms") or []),
        "savegame": dict(payload.get("savegame") or {}),
        "services": dict(payload.get("services") or {}),
        "multiplayer": dict(payload.get("multiplayer") or {}),
        "issues": list(payload.get("issues") or []),
        "warnings": list(payload.get("warnings") or []),
        "notes": [f"manifest: {_display_project_path(project_root, manifest_path)}"],
    })


def _select_scenarios(requested_ids: Optional[List[str]]) -> List[Dict[str, Any]]:
    catalog = list_production_scenarios()
    items = list(catalog.get("items") or [])
    if not requested_ids:
        return items
    requested = {str(item or "").strip() for item in requested_ids if str(item or "").strip()}
    return [item for item in items if item.get("scenario_id") in requested] or items


def _build_platform_baseline_row(platform_profile: Dict[str, Any]) -> Dict[str, Any]:
    blocking_reasons: List[str] = []
    warning_reasons: List[str] = []
    if platform_profile.get("platform_count", 0) <= 0:
        blocking_reasons.append("No platform targets declared in deployment/platform_delivery.json")
    if not str(platform_profile.get("savegame", {}).get("schema_id") or "").strip():
        blocking_reasons.append("Savegame schema_id is missing from the platform delivery baseline")
    if not bool(platform_profile.get("service_count", 0)):
        warning_reasons.append("No platform services are enabled in the baseline")

    status = "blocked" if blocking_reasons else ("warning" if warning_reasons else "passed")
    return {
        "row_id": "platform_delivery_baseline",
        "row_type": "gate",
        "label": "Platform Delivery Baseline",
        "status": status,
        "required": True,
        "default_selected": True,
        "platform_id": "",
        "platform_label": "",
        "scenario_ids": ["release_candidate"],
        "execution_mode": "baseline",
        "command": "",
        "endpoint": "/platform-delivery/profile",
        "script_path": "",
        "summary": (
            f"{platform_profile.get('platform_count', 0)} platform target(s), "
            f"savegame schema {platform_profile.get('savegame', {}).get('schema_id') or '-'}"
        ),
        "details": {
            "manifest_path": platform_profile.get("manifest_path"),
            "platform_count": platform_profile.get("platform_count", 0),
            "service_count": platform_profile.get("service_count", 0),
            "savegame_schema_id": platform_profile.get("savegame", {}).get("schema_id") or "",
            "multiplayer_enabled": bool(platform_profile.get("multiplayer", {}).get("enabled")),
        },
        "notes": list(platform_profile.get("notes") or []),
        "blocking_reasons": blocking_reasons,
        "warning_reasons": warning_reasons,
    }


def _build_platform_export_rows(platform_profile: Dict[str, Any]) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for platform in list(platform_profile.get("platforms") or []):
        platform_id = str(platform.get("platform_id") or "").strip() or "unnamed_platform"
        preset_name = str(platform.get("preset_name") or "").strip()
        output_path = str(platform.get("output_path") or "").strip()
        blocking_reasons: List[str] = []
        warning_reasons: List[str] = []
        if not preset_name:
            blocking_reasons.append(f"{platform_id} is missing preset_name")
        if not output_path:
            blocking_reasons.append(f"{platform_id} is missing output_path")
        if not list(platform.get("feature_flags") or []):
            warning_reasons.append(f"{platform_id} does not declare feature_flags")
        status = "blocked" if blocking_reasons else ("warning" if warning_reasons else "passed")
        rows.append({
            "row_id": f"build_{platform_id}",
            "row_type": "build",
            "label": f"Build Export: {platform_id}",
            "status": status,
            "required": True,
            "default_selected": True,
            "platform_id": platform_id,
            "platform_label": preset_name or platform_id,
            "scenario_ids": ["release_candidate"],
            "execution_mode": "build",
            "command": f'godot --headless --path . --export-release "{preset_name}" "{output_path}"' if preset_name and output_path else "",
            "endpoint": "/platform-delivery/profile",
            "script_path": "",
            "summary": output_path or "Missing output_path",
            "details": {
                "preset_name": preset_name,
                "store": platform.get("store") or "",
                "arch": platform.get("arch") or "",
                "output_path": output_path,
                "feature_flags": list(platform.get("feature_flags") or []),
            },
            "notes": [f"store: {platform.get('store') or '-'}", f"arch: {platform.get('arch') or '-'}"],
            "blocking_reasons": blocking_reasons,
            "warning_reasons": warning_reasons,
        })
    return rows


def _build_production_gate_rows(
    project_root: Path,
    runtime_root: Path,
    scenarios: List[Dict[str, Any]],
    *,
    mode: str,
    fail_on_warnings: bool,
) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for scenario in scenarios:
        scenario_id = str(scenario.get("scenario_id") or "").strip() or "vertical_slice_2d"
        readiness = build_production_readiness(
            project_root,
            runtime_root=runtime_root,
            scenario_id=scenario_id,
            evidence={name: True for name in list(scenario.get("required_evidence") or [])},
            changed_paths=list(scenario.get("recommended_changed_paths") or []),
            notes="build_run_matrix",
            mode=mode,
            fail_on_warnings=fail_on_warnings,
        )
        rows.append({
            "row_id": f"production_gate_{scenario_id}",
            "row_type": "gate",
            "label": f"Production Gate: {scenario.get('label') or scenario_id}",
            "status": _map_status(readiness.get("readiness_status")),
            "required": True,
            "default_selected": True,
            "platform_id": "",
            "platform_label": "",
            "scenario_ids": [scenario_id],
            "execution_mode": "gate",
            "command": "",
            "endpoint": "/production/validate",
            "script_path": "",
            "summary": str(readiness.get("message") or ""),
            "details": {
                "exit_code": readiness.get("exit_code"),
                "blocking_checks": list(readiness.get("blocking_checks") or []),
                "warning_checks": list(readiness.get("warning_checks") or []),
                "gate_focus": list(scenario.get("gate_focus") or []),
            },
            "notes": [
                f"required evidence: {', '.join(list(scenario.get('required_evidence') or [])) or '-'}",
            ],
            "blocking_reasons": list(readiness.get("blocking_checks") or []),
            "warning_reasons": list(readiness.get("warning_checks") or []),
        })
    return rows


def _build_release_candidate_row(release_candidate: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "row_id": "release_candidate_checklist",
        "row_type": "gate",
        "label": "Release Candidate Checklist",
        "status": _map_status(release_candidate.get("status")),
        "required": True,
        "default_selected": True,
        "platform_id": "",
        "platform_label": "",
        "scenario_ids": ["release_candidate"],
        "execution_mode": "gate",
        "command": "",
        "endpoint": "/release-candidate/checklist",
        "script_path": "",
        "summary": str(release_candidate.get("release_manifest_source") or "release checklist"),
        "details": {
            "build_id": release_candidate.get("release_summary", {}).get("build_id") or "",
            "channel": release_candidate.get("release_summary", {}).get("channel") or "",
            "blocking_checks": list(release_candidate.get("blocking_checks") or []),
            "warning_checks": list(release_candidate.get("warning_checks") or []),
            "should_block": bool(release_candidate.get("should_block")),
        },
        "notes": list(release_candidate.get("notes") or []),
        "blocking_reasons": list(release_candidate.get("blocking_checks") or []),
        "warning_reasons": list(release_candidate.get("warning_checks") or []),
    }


def _build_runtime_performance_sampling_row(
    project_root: Path,
    runtime_root: Path,
    selected_scenario_ids: List[str],
) -> Dict[str, Any]:
    profile_path = _find_latest_performance_profile(runtime_root)
    blocking_reasons: List[str] = []
    warning_reasons: List[str] = []
    notes: List[str] = [
        "Consumes the latest runtime profile emitted by manage_game_performance or live production flows.",
    ]
    summary_payload: Dict[str, Any] = {}
    details: Dict[str, Any] = {
        "profile_path": _display_runtime_path(runtime_root, profile_path) if profile_path else "",
        "profile_exists": bool(profile_path and profile_path.exists()),
        "performance_schema_version": PERFORMANCE_SUMMARY_SCHEMA_VERSION,
    }

    if profile_path:
        analyzer = GamePerformanceAnalyzer(project_root, runtime_root=runtime_root)
        profile_payload = _load_json(profile_path)
        scene_path = str(profile_payload.get("scene_path") or "").strip()
        snapshot = analyzer.snapshot(
            scene_path=scene_path,
            profile_path=str(profile_path),
            budget_overrides=dict(profile_payload.get("budgets") or {}),
        )
        summary_payload = dict(snapshot.get("summary") or {})
        status = "passed" if summary_payload.get("passed") else "blocked"
        if status == "blocked":
            blocking_reasons.extend(summary_payload.get("issues") or ["Performance profile failed budget checks"])
        warning_reasons.extend(str(item) for item in list(summary_payload.get("warnings") or []))
        details.update({
            "scene_path": scene_path,
            "baseline_path": _display_runtime_path(runtime_root, Path(str(snapshot.get("baseline_path") or ""))) if snapshot.get("baseline_path") else "",
            "baseline_exists": bool(snapshot.get("baseline_exists")),
            "metric_count": len(dict(summary_payload.get("metrics") or {})),
            "check_count": len(list(summary_payload.get("checks") or [])),
            "issue_count": len(list(summary_payload.get("issues") or [])),
            "warning_count": len(list(summary_payload.get("warnings") or [])),
            "top_frame_stage": str(summary_payload.get("metrics", {}).get("top_frame_stage") or ""),
            "memory_trend_status": str(summary_payload.get("memory_trend", {}).get("trend_status") or ""),
            "performance_summary": summary_payload,
        })
        row_summary = (
            f"Runtime profile sampled: {details['metric_count']} metric(s), "
            f"{details['issue_count']} issue(s), {details['warning_count']} warning(s)"
        )
    else:
        status = "warning"
        warning_reasons.append("No runtime performance profile found under logs/test_artifacts")
        row_summary = "Awaiting runtime performance profile in logs/test_artifacts"

    return {
        "row_id": "runtime_performance_sampling",
        "row_type": "run",
        "label": "Runtime Performance Sampling",
        "status": status,
        "required": False,
        "default_selected": True,
        "platform_id": "",
        "platform_label": "",
        "scenario_ids": [
            item for item in ["vertical_slice_2d", "content_pipeline", "release_candidate"]
            if item in selected_scenario_ids
        ],
        "execution_mode": "non_live",
        "command": "python -m agent_system.cli run \"分析性能画像\" -y",
        "endpoint": "/performance/profile",
        "script_path": "",
        "summary": row_summary,
        "details": details,
        "notes": notes,
        "blocking_reasons": blocking_reasons,
        "warning_reasons": warning_reasons,
    }


def _build_run_lane_rows(runtime_root: Path, selected_scenario_ids: List[str]) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for lane in _RUN_LANES:
        lane_scenarios = [item for item in list(lane.get("scenario_ids") or []) if item in selected_scenario_ids]
        if not lane_scenarios:
            continue
        missing_paths = [
            relative for relative in list(lane.get("required_paths") or [])
            if not (runtime_root / relative).exists()
        ]
        blocking_reasons = [f"Missing required path: {relative}" for relative in missing_paths]
        warning_reasons: List[str] = []
        if not blocking_reasons and lane.get("execution_mode") in {"live", "browser", "remote_mcp"}:
            warning_reasons.append("Requires local runtime prerequisites before execution")
        status = "blocked" if blocking_reasons else ("warning" if warning_reasons else "passed")
        rows.append({
            "row_id": str(lane.get("lane_id") or "unnamed_lane"),
            "row_type": "run",
            "label": str(lane.get("label") or lane.get("lane_id") or "Run Lane"),
            "status": status,
            "required": bool(lane.get("required", False)),
            "default_selected": bool(lane.get("default_selected", False)),
            "platform_id": "",
            "platform_label": "",
            "scenario_ids": lane_scenarios,
            "execution_mode": str(lane.get("execution_mode") or "non_live"),
            "command": str(lane.get("command") or ""),
            "endpoint": str(lane.get("endpoint") or ""),
            "script_path": str(lane.get("script_path") or ""),
            "summary": _build_lane_summary(lane_scenarios, missing_paths, warning_reasons),
            "details": {
                "required_paths": list(lane.get("required_paths") or []),
                "missing_paths": missing_paths,
            },
            "notes": list(lane.get("notes") or []),
            "blocking_reasons": blocking_reasons,
            "warning_reasons": warning_reasons,
        })
    return rows


def _find_latest_performance_profile(runtime_root: Path) -> Optional[Path]:
    artifact_dir = runtime_root / "logs" / "test_artifacts"
    if not artifact_dir.exists():
        return None
    candidates = [
        path for path in artifact_dir.glob("performance_profile_*.json")
        if path.is_file()
    ]
    if not candidates:
        return None
    return max(candidates, key=lambda item: item.stat().st_mtime).resolve()


def _load_json(path: Path) -> Dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return dict(payload) if isinstance(payload, dict) else {}


def _display_runtime_path(runtime_root: Path, target_path: Path) -> str:
    try:
        return target_path.resolve().relative_to(runtime_root).as_posix()
    except ValueError:
        return target_path.as_posix()


def _build_lane_summary(
    scenario_ids: List[str],
    missing_paths: List[str],
    warning_reasons: List[str],
) -> str:
    if missing_paths:
        return f"Missing runtime prerequisites: {', '.join(missing_paths)}"
    if warning_reasons:
        return f"Available for {', '.join(scenario_ids)} but depends on local runtime setup"
    return f"Ready for {', '.join(scenario_ids)}"


def _build_notes(
    platform_profile: Dict[str, Any],
    project_root: Path,
    manifest_path: Path,
    selected_scenario_ids: List[str],
) -> List[str]:
    manifest_display = _display_project_path(project_root, manifest_path)
    notes = [
        f"platform manifest: {manifest_display}",
        f"selected scenarios: {', '.join(selected_scenario_ids)}",
    ]
    if platform_profile.get("platform_count", 0) <= 0:
        notes.append("No platform targets are currently declared; export rows will block until deployment/platform_delivery.json is filled.")
    return notes


def _build_recommendations(rows: List[Dict[str, Any]], scenarios: List[Dict[str, Any]]) -> List[str]:
    recommendations: List[str] = []
    blocked_rows = [row for row in rows if row.get("status") == "blocked"]
    warning_rows = [row for row in rows if row.get("status") == "warning"]
    if blocked_rows:
        recommendations.extend(
            f"Fix {row['label']} before release handoff."
            for row in blocked_rows[:4]
        )
    if not blocked_rows:
        recommendations.append("Run default-selected rows first: build targets, production gates, RC checklist, then shared regression lanes.")
    live_rows = [row for row in warning_rows if row.get("execution_mode") in {"live", "browser", "remote_mcp"}]
    if live_rows:
        recommendations.append("Schedule browser/live/remote MCP lanes after the non-live regression has passed.")
    if any((scenario.get("scenario_id") or "") == "release_candidate" for scenario in scenarios):
        recommendations.append("Treat release_candidate rows as the final release checklist, not as a substitute for scenario-specific gates.")
    return recommendations


def _map_status(value: Any) -> str:
    normalized = str(value or "").strip().lower()
    if normalized in {"passed", "warning", "blocked", "skipped"}:
        return normalized
    return "passed"


def _display_project_path(project_root: Path, target_path: Path) -> str:
    try:
        return f"res://{target_path.relative_to(project_root).as_posix()}"
    except ValueError:
        return target_path.as_posix()

"""Zero-to-playable game creation planner and local scaffold writer."""

from __future__ import annotations

import json
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

from agent_system.contracts import (
    normalize_game_creation_profile,
    normalize_game_creation_replay,
    normalize_game_creation_review,
    normalize_game_creation_template_migration,
    normalize_scene_graph_audit,
    normalize_scene_graph_snapshot,
)
from agent_system.tools.godot_cli import GodotCLI
from agent_system.tools.governance import build_governance_enforcement
from agent_system.validations import ProjectLayoutValidator


DEFAULT_GAME_CREATION_MANIFEST_PATH = "data_tables/game_creation/game_creation_profile.json"
DEFAULT_GAME_CREATION_DESIGN_DOC_PATH = "docs/game_creation_design.md"
DEFAULT_GAME_CREATION_INPUT_REPLAY_PATH = "data_tables/game_creation/input_replay.json"
DEFAULT_GAME_CREATION_REPLAY_REPORT_PATH = "data_tables/game_creation/input_replay_run.json"
DEFAULT_GAME_CREATION_TEMPLATE_MIGRATION_PATH = "data_tables/game_creation/template_migration_plan.json"
DEFAULT_SCENE_GRAPH_AUDIT_PATH = "data_tables/game_creation/scene_graph_audit.json"
DEFAULT_GAME_CREATION_REVIEW_PATH = "data_tables/game_creation/game_creation_review.json"
DEFAULT_GAME_CREATION_REVIEW_DOC_PATH = "docs/game_creation_review.md"
DEFAULT_GAME_TEMPLATE_ID = "platformer_2d"
PLATFORMER_FEATURES = [
    "player_movement",
    "jump",
    "coin_collection",
    "enemy_patrol",
    "health",
    "hud",
]
TOPDOWN_ACTION_TEMPLATE_ID = "topdown_action_2d"
TOPDOWN_FEATURES = [
    "topdown_movement",
    "melee_attack",
    "pickup_collection",
    "enemy_chase",
    "health",
    "hud",
]
TOWER_DEFENSE_TEMPLATE_ID = "tower_defense_2d"
TOWER_DEFENSE_FEATURES = [
    "tower_placement",
    "enemy_wave",
    "tower_targeting",
    "base_health",
    "resource_income",
    "hud",
]
ARPG_TEMPLATE_ID = "arpg_2d"
ARPG_FEATURES = [
    "topdown_movement",
    "melee_attack",
    "dodge_roll",
    "quest_relic_collection",
    "enemy_chase",
    "health",
    "hud",
]
ROGUELIKE_TEMPLATE_ID = "roguelike_2d"
ROGUELIKE_FEATURES = [
    "room_navigation",
    "melee_attack",
    "loot_collection",
    "enemy_chase",
    "floor_descent",
    "health",
    "hud",
]
VISUAL_NOVEL_TEMPLATE_ID = "visual_novel_2d"
VISUAL_NOVEL_FEATURES = [
    "dialogue_progression",
    "branching_choices",
    "speaker_portraits",
    "affinity_tracking",
    "scene_state",
    "hud",
]
SURVIVAL_CRAFTING_TEMPLATE_ID = "survival_crafting_2d"
SURVIVAL_CRAFTING_FEATURES = [
    "resource_gathering",
    "crafting",
    "campfire_building",
    "hunger",
    "health",
    "hud",
]
SUPPORTED_TEMPLATES = {
    DEFAULT_GAME_TEMPLATE_ID: {
        "template_id": DEFAULT_GAME_TEMPLATE_ID,
        "label": "2D Platformer Prototype",
        "genre": "platformer_2d",
        "description": "Playable 2D baseline with movement, jump, coins, enemy patrol, health, and HUD.",
    },
    TOPDOWN_ACTION_TEMPLATE_ID: {
        "template_id": TOPDOWN_ACTION_TEMPLATE_ID,
        "label": "Top-down Action Prototype",
        "genre": "topdown_action_2d",
        "description": "Playable top-down baseline with 4-way movement, attack input, pickups, enemy chase, health, and HUD.",
    },
    TOWER_DEFENSE_TEMPLATE_ID: {
        "template_id": TOWER_DEFENSE_TEMPLATE_ID,
        "label": "Tower Defense Prototype",
        "genre": "tower_defense_2d",
        "description": "Playable defense baseline with tower placement input, enemy waves, base health, resource income, and HUD.",
    },
    ARPG_TEMPLATE_ID: {
        "template_id": ARPG_TEMPLATE_ID,
        "label": "Action RPG Prototype",
        "genre": "arpg_2d",
        "description": "Playable action RPG baseline with movement, attack, dodge roll, relic quest pickup, enemy chase, health, and HUD.",
    },
    ROGUELIKE_TEMPLATE_ID: {
        "template_id": ROGUELIKE_TEMPLATE_ID,
        "label": "Roguelike Room Prototype",
        "genre": "roguelike_2d",
        "description": "Playable roguelike baseline with room movement, attack, loot pickup, enemy chase, floor descent, health, and HUD.",
    },
    VISUAL_NOVEL_TEMPLATE_ID: {
        "template_id": VISUAL_NOVEL_TEMPLATE_ID,
        "label": "Visual Novel Prototype",
        "genre": "visual_novel_2d",
        "description": "Playable visual novel baseline with dialogue progression, branching choices, speaker portraits, affinity tracking, scene state, and HUD.",
    },
    SURVIVAL_CRAFTING_TEMPLATE_ID: {
        "template_id": SURVIVAL_CRAFTING_TEMPLATE_ID,
        "label": "Survival Crafting Prototype",
        "genre": "survival_crafting_2d",
        "description": "Playable survival crafting baseline with gathering, crafting, campfire building, hunger, health, and HUD.",
    },
}
TEMPLATE_ALIASES = {
    "arpg": ARPG_TEMPLATE_ID,
    "action_rpg": ARPG_TEMPLATE_ID,
    "action_rpg_2d": ARPG_TEMPLATE_ID,
    "roguelike": ROGUELIKE_TEMPLATE_ID,
    "roguelite": ROGUELIKE_TEMPLATE_ID,
    "dungeon": ROGUELIKE_TEMPLATE_ID,
    "visual_novel": VISUAL_NOVEL_TEMPLATE_ID,
    "visualnovel": VISUAL_NOVEL_TEMPLATE_ID,
    "vn": VISUAL_NOVEL_TEMPLATE_ID,
    "survival": SURVIVAL_CRAFTING_TEMPLATE_ID,
    "survival_crafting": SURVIVAL_CRAFTING_TEMPLATE_ID,
    "crafting": SURVIVAL_CRAFTING_TEMPLATE_ID,
    "topdown_action": TOPDOWN_ACTION_TEMPLATE_ID,
    "topdown": TOPDOWN_ACTION_TEMPLATE_ID,
    "top_down_action": TOPDOWN_ACTION_TEMPLATE_ID,
    "tower_defense": TOWER_DEFENSE_TEMPLATE_ID,
    "towerdefense": TOWER_DEFENSE_TEMPLATE_ID,
    "td": TOWER_DEFENSE_TEMPLATE_ID,
}


def list_game_creation_templates() -> Dict[str, Any]:
    return {
        "default_template_id": DEFAULT_GAME_TEMPLATE_ID,
        "count": len(SUPPORTED_TEMPLATES),
        "items": list(SUPPORTED_TEMPLATES.values()),
    }


def build_game_creation_plan(
    project_root: str | Path,
    *,
    title: str = "Platformer Prototype",
    genre: str = "platformer_2d",
    template_id: str = DEFAULT_GAME_TEMPLATE_ID,
    features: List[str] | None = None,
    target_platforms: List[str] | None = None,
    notes: str = "",
) -> Dict[str, Any]:
    resolved_template = _resolve_template_id(template_id or genre or DEFAULT_GAME_TEMPLATE_ID)
    blocking_checks = _validate_request(title, resolved_template)
    template_spec = _template_spec(resolved_template)
    generated_features = _clean_list(features) or list(template_spec["features"])
    scene_paths = list(template_spec["scene_paths"])
    script_paths = [
        "scripts/main_controller.gd",
        "scripts/player_controller.gd",
        template_spec["pickup_script"],
        template_spec["enemy_script"],
        "scripts/health_system.gd",
        "scripts/hud_controller.gd",
    ]
    data_tables = [
        {"path": "data_tables/game_creation/gameplay.json", "schema": "gameplay_balance"},
        {"path": DEFAULT_GAME_CREATION_INPUT_REPLAY_PATH, "schema": "game_creation_input_replay"},
    ]
    data_paths = [item["path"] for item in data_tables]
    module_plan = _module_plan(resolved_template)
    godot_response_map = _godot_response_map(resolved_template)
    skill_binding_plan = _skill_binding_plan(module_plan)
    block_diagram = _block_diagram(module_plan)
    resolved_genre = str(genre or "").strip().lower()
    if not resolved_genre or (resolved_template != DEFAULT_GAME_TEMPLATE_ID and resolved_genre == "platformer_2d"):
        resolved_genre = str(template_spec["genre"])
    return normalize_game_creation_profile({
        "game_id": _slug(title),
        "title": str(title or "").strip(),
        "genre": resolved_genre,
        "template_id": resolved_template,
        "target_platforms": _clean_list(target_platforms) or ["desktop", "web"],
        "features": generated_features,
        "scene_plan": _scene_plan(scene_paths, template_spec["scene_roles"]),
        "input_map": template_spec["input_map"],
        "asset_plan": template_spec["asset_plan"],
        "module_plan": module_plan,
        "skill_binding_plan": skill_binding_plan,
        "block_diagram": block_diagram,
        "godot_response_map": godot_response_map,
        "data_tables": data_tables,
        "playtest_plan": template_spec["playtest_plan"],
        "input_replay_plan": _input_replay_plan(resolved_template),
        "golden_screenshot_plan": _golden_screenshot_plan(resolved_template),
        "template_migration_plan": _template_migration_policy(resolved_template),
        "export_plan": {"targets": _clean_list(target_platforms) or ["desktop", "web"], "signing_required": False},
        "acceptance_criteria": template_spec["acceptance_criteria"],
        "artifact_paths": [*scene_paths, *script_paths, *data_paths, DEFAULT_GAME_CREATION_MANIFEST_PATH, DEFAULT_GAME_CREATION_DESIGN_DOC_PATH],
        "blocking_checks": blocking_checks,
        "warning_checks": [str(notes).strip()] if str(notes or "").strip() else [],
        "manifest_path": DEFAULT_GAME_CREATION_MANIFEST_PATH,
        "project_root": str(Path(project_root).resolve()),
    })


def apply_game_creation_plan(
    project_root: str | Path,
    *,
    title: str = "Platformer Prototype",
    genre: str = "platformer_2d",
    template_id: str = DEFAULT_GAME_TEMPLATE_ID,
    features: List[str] | None = None,
    target_platforms: List[str] | None = None,
    notes: str = "",
    overwrite: bool = False,
) -> Dict[str, Any]:
    root = Path(project_root).resolve()
    plan = build_game_creation_plan(
        root,
        title=title,
        genre=genre,
        template_id=template_id,
        features=features,
        target_platforms=target_platforms,
        notes=notes,
    )
    if plan["should_block"]:
        return plan

    generated: List[str] = []
    skipped: List[str] = []
    files = _scaffold_files(str(title or "Platformer Prototype").strip(), plan["template_id"])
    files[DEFAULT_GAME_CREATION_DESIGN_DOC_PATH] = _design_doc(plan)
    files[DEFAULT_GAME_CREATION_INPUT_REPLAY_PATH] = json.dumps(_input_replay_artifact(plan), indent=2) + "\n"
    changed_paths = [*files.keys(), DEFAULT_GAME_CREATION_MANIFEST_PATH]
    layout_payload = _validate_game_creation_layout(root, changed_paths)
    if layout_payload["blocking_checks"]:
        return normalize_game_creation_profile({
            **plan,
            "layout_checks": layout_payload["checks"],
            "layout_check_count": layout_payload["check_count"],
            "layout_passed": False,
            "layout_blocking_checks": layout_payload["blocking_checks"],
            "blocking_checks": [*list(plan.get("blocking_checks") or []), *layout_payload["blocking_checks"]],
            "status": "blocked",
            "generated_files": [],
            "skipped_files": [],
            "message": "Game creation scaffold blocked by managed layout validation.",
        })
    governance_payload = _build_game_creation_governance_gate(root, changed_paths)
    if governance_payload["should_block"]:
        governance_blocking_checks = [
            f"governance {item}"
            for item in list(governance_payload.get("blocking_checks") or [])
        ]
        return normalize_game_creation_profile({
            **plan,
            "layout_checks": layout_payload["checks"],
            "layout_check_count": layout_payload["check_count"],
            "layout_passed": True,
            "layout_blocking_checks": [],
            "governance_enforcement": governance_payload,
            "governance_admission": governance_payload.get("admission") or {},
            "governance_passed": False,
            "governance_blocking_checks": governance_blocking_checks,
            "blocking_checks": [*list(plan.get("blocking_checks") or []), *governance_blocking_checks],
            "status": "blocked",
            "generated_files": [],
            "skipped_files": [],
            "message": "Game creation scaffold blocked by governance admission.",
        })
    for relative_path, content in files.items():
        _write_text(root / relative_path, content, relative_path, overwrite, generated, skipped)

    manifest = normalize_game_creation_profile({
        **plan,
        "layout_checks": layout_payload["checks"],
        "layout_check_count": layout_payload["check_count"],
        "layout_passed": True,
        "layout_blocking_checks": [],
        "governance_enforcement": governance_payload,
        "governance_admission": governance_payload.get("admission") or {},
        "governance_passed": bool(governance_payload.get("passed")),
        "governance_blocking_checks": list(governance_payload.get("blocking_checks") or []),
        "generated_files": generated,
        "skipped_files": skipped,
    })
    manifest_path = root / DEFAULT_GAME_CREATION_MANIFEST_PATH
    _write_text(
        manifest_path,
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n",
        DEFAULT_GAME_CREATION_MANIFEST_PATH,
        True,
        generated,
        skipped,
    )
    return normalize_game_creation_profile({**manifest, "generated_files": generated, "skipped_files": skipped})


def build_scene_graph_audit(
    project_root: str | Path,
    *,
    manifest_path: str = DEFAULT_GAME_CREATION_MANIFEST_PATH,
    scene_graph_snapshot: Dict[str, Any] | None = None,
    write_report: bool = False,
    report_path: str = DEFAULT_SCENE_GRAPH_AUDIT_PATH,
) -> Dict[str, Any]:
    root = Path(project_root).resolve()
    manifest_relative = str(manifest_path or DEFAULT_GAME_CREATION_MANIFEST_PATH).strip()
    manifest_file = root / manifest_relative
    if not manifest_file.exists():
        payload = normalize_scene_graph_audit({
            "project_root": str(root),
            "manifest_path": manifest_relative,
            "manifest_exists": False,
            "blocking_checks": [f"missing manifest: {manifest_relative}"],
            "message": "Scene graph audit blocked because game creation manifest is missing.",
            "generated_at": _utc_now(),
        })
        if write_report:
            _write_audit_report(root, report_path, payload)
        return payload

    try:
        plan = normalize_game_creation_profile(json.loads(manifest_file.read_text(encoding="utf-8")))
    except (OSError, json.JSONDecodeError) as exc:
        payload = normalize_scene_graph_audit({
            "project_root": str(root),
            "manifest_path": manifest_relative,
            "manifest_exists": True,
            "blocking_checks": [f"invalid manifest: {exc}"],
            "message": "Scene graph audit blocked because manifest JSON is invalid.",
            "generated_at": _utc_now(),
        })
        if write_report:
            _write_audit_report(root, report_path, payload)
        return payload

    live_snapshot_summary = _live_snapshot_summary(scene_graph_snapshot)
    live_graph = _scene_graph_from_snapshot(scene_graph_snapshot)
    scene_graph = [_parse_scene_file(root, item.get("path") or "") for item in plan.get("scene_plan") or []]
    scene_graph = [item for item in scene_graph if item]
    if live_graph:
        scene_graph = _merge_live_scene_graph(scene_graph, live_graph)
    graph_by_path = {item["scene_path"]: item for item in scene_graph}
    all_scripts = _read_scripts(root, plan.get("artifact_paths") or [])

    module_checks = [
        _audit_module(root, module, graph_by_path, all_scripts)
        for module in list(plan.get("module_plan") or [])
    ]
    response_checks = [
        _audit_response(item, graph_by_path)
        for item in list(plan.get("godot_response_map") or [])
    ]

    missing_scenes = sorted({
        check["scene_path"]
        for check in module_checks
        if check.get("scene_missing") and check.get("scene_path")
    })
    missing_scripts = sorted({
        script
        for check in module_checks
        for script in check.get("missing_scripts", [])
    })
    missing_nodes = sorted({
        node
        for check in module_checks
        for node in check.get("missing_nodes", [])
    })
    missing_signals = sorted({
        signal
        for check in module_checks
        for signal in check.get("missing_signals", [])
    })
    response_warnings = [
        f"response target not found: {item.get('trigger')} -> {item.get('node_path')}"
        for item in response_checks
        if not item.get("node_found")
    ]
    blocking_checks = [
        *(f"missing scene: {path}" for path in missing_scenes),
        *(f"missing script: {path}" for path in missing_scripts),
        *(f"missing node: {item}" for item in missing_nodes),
    ]
    warning_checks = [
        *(f"missing signal wiring: {item}" for item in missing_signals),
        *response_warnings,
    ]

    payload = normalize_scene_graph_audit({
        "project_root": str(root),
        "manifest_path": manifest_relative,
        "manifest_exists": True,
        "generated_at": _utc_now(),
        "scene_graph": scene_graph,
        "scene_count": len(scene_graph),
        "node_count": sum(len(item.get("nodes") or []) for item in scene_graph),
        "live_snapshot_used": bool(live_graph),
        "live_snapshot": live_snapshot_summary,
        "live_snapshot_source": live_snapshot_summary.get("source", ""),
        "live_snapshot_scene_path": live_snapshot_summary.get("scene_path", ""),
        "live_snapshot_node_count": live_snapshot_summary.get("node_count", 0),
        "expected_module_count": len(module_checks),
        "module_checks": module_checks,
        "response_checks": response_checks,
        "missing_scenes": missing_scenes,
        "missing_scripts": missing_scripts,
        "missing_nodes": missing_nodes,
        "missing_signals": missing_signals,
        "blocking_checks": blocking_checks,
        "warning_checks": warning_checks,
        "message": "Scene graph audit completed against game creation manifest.",
    })
    if write_report:
        _write_audit_report(root, report_path, payload)
    return payload


def build_game_creation_review(
    project_root: str | Path,
    *,
    manifest_path: str = DEFAULT_GAME_CREATION_MANIFEST_PATH,
    scene_graph_snapshot: Dict[str, Any] | None = None,
    write_reports: bool = False,
) -> Dict[str, Any]:
    root = Path(project_root).resolve()
    manifest_relative = str(manifest_path or DEFAULT_GAME_CREATION_MANIFEST_PATH).strip()
    manifest_file = root / manifest_relative
    if manifest_file.exists():
        try:
            plan = normalize_game_creation_profile(json.loads(manifest_file.read_text(encoding="utf-8")))
        except (OSError, json.JSONDecodeError):
            plan = normalize_game_creation_profile({"manifest_path": manifest_relative})
    else:
        plan = normalize_game_creation_profile({"manifest_path": manifest_relative})

    audit = build_scene_graph_audit(
        root,
        manifest_path=manifest_relative,
        scene_graph_snapshot=scene_graph_snapshot,
        write_report=write_reports,
    )
    acceptance_checklist = [
        {
            "label": criterion,
            "status": "blocked" if audit.get("should_block") else "warning" if audit.get("warning_checks") else "ready",
            "validation_method": "scene_graph_audit",
            "blockers": list(audit.get("blocking_checks") or []),
        }
        for criterion in list(plan.get("acceptance_criteria") or [])
    ]
    if not acceptance_checklist:
        acceptance_checklist.append({
            "label": "game creation manifest is available",
            "status": "blocked" if not audit.get("manifest_exists") else "ready",
            "validation_method": "manifest_check",
            "blockers": list(audit.get("blocking_checks") or []),
        })

    module_review = [
        {
            "module_id": item.get("module_id") or "",
            "label": item.get("label") or item.get("module_id") or "",
            "role": item.get("role") or "",
            "status": item.get("status") or "warning",
            "skill_names": list(item.get("skill_names") or []),
            "missing_nodes": list(item.get("missing_nodes") or []),
            "missing_scripts": list(item.get("missing_scripts") or []),
            "missing_signals": list(item.get("missing_signals") or []),
        }
        for item in list(audit.get("module_checks") or [])
    ]
    data_table_review = _review_game_creation_data_tables(root, plan)
    blocking_checks = list(audit.get("blocking_checks") or [])
    blocking_checks.extend(
        f"data table blocked: {item.get('path')} - {item.get('message')}"
        for item in data_table_review
        if item.get("status") == "blocked"
    )
    warning_checks = list(audit.get("warning_checks") or [])
    warning_checks.extend(
        f"data table warning: {item.get('path')} - {item.get('message')}"
        for item in data_table_review
        if item.get("status") == "warning"
    )
    payload = normalize_game_creation_review({
        "project_root": str(root),
        "manifest_path": manifest_relative,
        "generated_at": _utc_now(),
        "game_id": plan.get("game_id") or "",
        "title": plan.get("title") or "",
        "template_id": plan.get("template_id") or "",
        "acceptance_checklist": acceptance_checklist,
        "module_review": module_review,
        "data_table_review": data_table_review,
        "audit_summary": {
            "status": audit.get("status"),
            "scene_count": audit.get("scene_count"),
            "node_count": audit.get("node_count"),
            "live_snapshot_used": audit.get("live_snapshot_used"),
            "live_snapshot_source": audit.get("live_snapshot_source"),
            "live_snapshot_scene_path": audit.get("live_snapshot_scene_path"),
            "live_snapshot_node_count": audit.get("live_snapshot_node_count"),
            "missing_scene_count": len(audit.get("missing_scenes") or []),
            "missing_script_count": len(audit.get("missing_scripts") or []),
            "missing_node_count": len(audit.get("missing_nodes") or []),
            "missing_signal_count": len(audit.get("missing_signals") or []),
            "data_table_count": len(data_table_review),
            "passed_data_table_count": sum(1 for item in data_table_review if item.get("status") == "passed"),
        },
        "artifact_paths": [
            *list(plan.get("artifact_paths") or []),
            DEFAULT_SCENE_GRAPH_AUDIT_PATH,
            DEFAULT_GAME_CREATION_REVIEW_PATH,
            DEFAULT_GAME_CREATION_REVIEW_DOC_PATH,
        ],
        "blocking_checks": blocking_checks,
        "warning_checks": warning_checks,
        "message": "Game creation review completed from manifest and scene graph audit.",
    })
    if write_reports:
        _write_review_report(root, payload)
    return payload


def build_game_creation_input_replay(
    project_root: str | Path,
    *,
    manifest_path: str = DEFAULT_GAME_CREATION_MANIFEST_PATH,
    input_replay_path: str = DEFAULT_GAME_CREATION_INPUT_REPLAY_PATH,
    write_report: bool = False,
    write_script: bool = True,
    execute_replay: bool = False,
    promote_baseline: bool = False,
    replay_render_mode: str = "headless",
    godot_cli: Any | None = None,
) -> Dict[str, Any]:
    root = Path(project_root).resolve()
    manifest_relative = str(manifest_path or DEFAULT_GAME_CREATION_MANIFEST_PATH).strip()
    replay_relative = str(input_replay_path or DEFAULT_GAME_CREATION_INPUT_REPLAY_PATH).strip()
    manifest = _read_json_file(root / manifest_relative)
    plan = normalize_game_creation_profile(manifest or {"manifest_path": manifest_relative})
    replay_payload = _read_json_file(root / replay_relative)
    blocking_checks: List[str] = []
    warning_checks: List[str] = []
    if not manifest:
        blocking_checks.append(f"missing manifest: {manifest_relative}")
    if not replay_payload:
        blocking_checks.append(f"missing input replay: {replay_relative}")
        replay_payload = _input_replay_artifact(plan)

    template_id = str(replay_payload.get("template_id") or plan.get("template_id") or DEFAULT_GAME_TEMPLATE_ID)
    scene_path = str(replay_payload.get("scene_path") or "res://scenes/Main.tscn")
    scene_relative = _res_to_relative(scene_path)
    scene_file = root / scene_relative
    if not scene_file.exists():
        blocking_checks.append(f"missing replay scene: {scene_path}")

    steps = list(replay_payload.get("steps") or plan.get("input_replay_plan") or _input_replay_plan(template_id))
    golden_plan = dict(replay_payload.get("golden_screenshot_plan") or plan.get("golden_screenshot_plan") or _golden_screenshot_plan(template_id))
    known_actions = _project_input_actions(root)
    action_checks = _build_replay_action_checks(steps, known_actions)
    blocking_checks.extend(
        f"input action missing: {item.get('input')}"
        for item in action_checks
        if item.get("status") == "blocked"
    )

    scene_graph = _parse_scene_file(root, scene_relative)
    node_names = {str(item.get("name") or "") for item in list(scene_graph.get("nodes") or [])}
    required_nodes = _clean_list(golden_plan.get("required_nodes"))
    node_checks = [
        {
            "node": node,
            "status": "passed" if node in node_names else "blocked",
            "message": "required node exists" if node in node_names else "required node missing from replay scene",
        }
        for node in required_nodes
    ]
    blocking_checks.extend(
        f"required replay node missing: {item.get('node')}"
        for item in node_checks
        if item.get("status") == "blocked"
    )

    runtime_capture_path = _replay_runtime_capture_path(steps, golden_plan)
    script_relative = f"logs/test_artifacts/game_creation/input_replay_{template_id}.gd"
    script_content = _build_input_replay_script(scene_path, steps, required_nodes, runtime_capture_path)
    if write_script and not blocking_checks:
        _write_text(root / script_relative, script_content, script_relative, True, [], [])
    elif write_script and blocking_checks:
        warning_checks.append("replay script not written because blocking checks failed")

    execution_status = "script_generated" if write_script and not blocking_checks else "not_executed"
    execution_message = ""
    execution_error = ""
    stdout = ""
    stderr = ""
    screenshot_exists = False
    screenshot_capture_mode = ""
    render_mode = _normalize_replay_render_mode(replay_render_mode)
    baseline_path = str(golden_plan.get("baseline_path") or "")
    baseline_exists = bool(baseline_path and (root / baseline_path).exists())
    baseline_promoted = False
    baseline_promoted_at = ""
    if execute_replay:
        if not write_script:
            blocking_checks.append("execute_replay requires write_script")
            execution_status = "blocked"
        elif blocking_checks:
            execution_status = "blocked"
        else:
            runner = godot_cli or GodotCLI(project_path=str(root))
            script_abs_path = str((root / script_relative).resolve())
            if render_mode == "viewport":
                run_script = getattr(runner, "run_script", None)
                if callable(run_script):
                    result = run_script(script_abs_path, headless=False)
                else:
                    result = runner.run_headless(script_abs_path)
                    warning_checks.append("runner does not expose run_script; replay fell back to headless execution")
            else:
                result = runner.run_headless(script_abs_path)
            execution_message = str(getattr(result, "message", "") or "")
            execution_error = str(getattr(result, "error", "") or "")
            data = getattr(result, "data", None) or {}
            stdout = str(data.get("stdout") or "")
            stderr = str(data.get("stderr") or "")
            screenshot_capture_mode = _extract_replay_screenshot_capture_mode(stdout)
            if getattr(result, "success", False):
                execution_status = "passed"
            else:
                execution_status = "blocked"
                blocking_checks.append(f"replay execution failed: {execution_error or execution_message or 'unknown error'}")
        if runtime_capture_path:
            screenshot_exists = (root / runtime_capture_path).exists()
            if execution_status == "passed" and not screenshot_exists:
                execution_status = "blocked"
                blocking_checks.append(f"runtime screenshot missing: {runtime_capture_path}")
    elif runtime_capture_path:
        screenshot_exists = (root / runtime_capture_path).exists()

    viewport_baseline = _build_viewport_baseline_status(
        runtime_capture_path=runtime_capture_path,
        screenshot_exists=screenshot_exists,
        screenshot_capture_mode=screenshot_capture_mode,
        executed=bool(execute_replay and execution_status in {"passed", "blocked"}),
    )

    if promote_baseline:
        if not runtime_capture_path or not (root / runtime_capture_path).exists():
            execution_status = "blocked"
            blocking_checks.append(f"cannot promote missing runtime screenshot: {runtime_capture_path or '-'}")
        elif not baseline_path:
            execution_status = "blocked"
            blocking_checks.append("cannot promote baseline without baseline_path")
        else:
            source_path = root / runtime_capture_path
            target_path = root / baseline_path
            target_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source_path, target_path)
            baseline_exists = True
            baseline_promoted = True
            baseline_promoted_at = _utc_now()

    payload = normalize_game_creation_replay({
        "project_root": str(root),
        "manifest_path": manifest_relative,
        "input_replay_path": replay_relative,
        "report_path": DEFAULT_GAME_CREATION_REPLAY_REPORT_PATH,
        "script_path": script_relative if write_script and not blocking_checks else "",
        "generated_at": _utc_now(),
        "template_id": template_id,
        "scene_path": scene_path,
        "runtime_capture_path": runtime_capture_path,
        "baseline_path": baseline_path,
        "baseline_source_path": runtime_capture_path,
        "baseline_exists": baseline_exists,
        "baseline_promoted": baseline_promoted,
        "baseline_promoted_at": baseline_promoted_at,
        "max_diff_ratio": float(golden_plan.get("max_diff_ratio") or 0.0),
        "replay_steps": steps,
        "action_checks": action_checks,
        "node_checks": node_checks,
        "execution_mode": "viewport_script" if render_mode == "viewport" else "headless_script",
        "replay_render_mode": render_mode,
        "execution_status": execution_status,
        "executed": bool(execute_replay and execution_status in {"passed", "blocked"}),
        "execution_message": execution_message,
        "execution_error": execution_error,
        "stdout": stdout,
        "stderr": stderr,
        "screenshot_exists": screenshot_exists,
        "screenshot_capture_mode": screenshot_capture_mode,
        **viewport_baseline,
        "blocking_checks": blocking_checks,
        "warning_checks": warning_checks,
        "message": "Game creation input replay script generated from input_replay.json.",
    })
    if write_report:
        _write_json_report(root, DEFAULT_GAME_CREATION_REPLAY_REPORT_PATH, payload)
    return payload


def build_game_creation_template_migration(
    project_root: str | Path,
    *,
    manifest_path: str = DEFAULT_GAME_CREATION_MANIFEST_PATH,
    from_template_id: str = "",
    to_template_id: str = DEFAULT_GAME_TEMPLATE_ID,
    write_report: bool = False,
    report_path: str = DEFAULT_GAME_CREATION_TEMPLATE_MIGRATION_PATH,
) -> Dict[str, Any]:
    root = Path(project_root).resolve()
    manifest_relative = str(manifest_path or DEFAULT_GAME_CREATION_MANIFEST_PATH).strip()
    report_relative = str(report_path or DEFAULT_GAME_CREATION_TEMPLATE_MIGRATION_PATH).strip()
    manifest = _read_json_file(root / manifest_relative)
    source_template = _resolve_template_id(from_template_id or str((manifest or {}).get("template_id") or ""))
    target_template = _resolve_template_id(to_template_id or DEFAULT_GAME_TEMPLATE_ID)
    blocking_checks: List[str] = []
    warning_checks: List[str] = []
    if not manifest and not from_template_id:
        blocking_checks.append(f"missing manifest: {manifest_relative}")
    if source_template not in SUPPORTED_TEMPLATES:
        blocking_checks.append(f"unsupported from_template_id: {source_template or '-'}")
    if target_template not in SUPPORTED_TEMPLATES:
        blocking_checks.append(f"unsupported to_template_id: {target_template or '-'}")
    if source_template and target_template and source_template == target_template:
        warning_checks.append("source and target templates match; migration is a no-op")

    source_spec = _template_spec(source_template) if source_template in SUPPORTED_TEMPLATES else {}
    target_spec = _template_spec(target_template) if target_template in SUPPORTED_TEMPLATES else {}
    compatibility_checks = _template_migration_compatibility(source_template, target_template, source_spec, target_spec)
    file_operations = _template_migration_file_operations(source_template, target_template, source_spec, target_spec)
    data_migrations = _template_migration_data_migrations(source_template, target_template, source_spec, target_spec)
    validation_plan = [
        {"step_id": "regenerate_plan", "command": f"game-create --template-id {target_template} --json", "expect": "target template plan normalizes"},
        {"step_id": "apply_scaffold", "command": f"game-create --template-id {target_template} --apply --overwrite", "expect": "managed scaffold writes without layout or governance blocking checks"},
        {"step_id": "audit_scene_graph", "command": "game-create --audit --write-report", "expect": "scene graph audit passes after migration"},
        {"step_id": "review_acceptance", "command": "game-create --review --write-report", "expect": "game creation review remains ready for acceptance"},
        {"step_id": "rebuild_replay", "command": "game-create --replay --write-report", "expect": "input replay script and report regenerate for target template"},
    ]
    rollback_plan = [
        {"step_id": "preserve_manifest", "action": "keep previous data_tables/game_creation/game_creation_profile.json before overwrite"},
        {"step_id": "restore_source_template", "action": f"rerun game-create --template-id {source_template or DEFAULT_GAME_TEMPLATE_ID} --apply --overwrite"},
        {"step_id": "restore_data_tables", "action": "restore gameplay.json and input_replay.json from source-template backup if validation blocks"},
    ]
    skill_constraints = [
        {"skill_name": "plan_game_feature", "constraint": "target template features must replace the source feature set explicitly"},
        {"skill_name": "manage_game_data_tables", "constraint": "gameplay.json and input_replay.json schema sections must match the target template"},
        {"skill_name": "audit_project_consistency", "constraint": "layout, governance, scene graph, review, and replay checks must pass before migration is accepted"},
        {"skill_name": "smoke_test_scene", "constraint": "live or headless replay evidence is required before promoting screenshot baselines"},
    ]

    payload = normalize_game_creation_template_migration({
        "project_root": str(root),
        "manifest_path": manifest_relative,
        "manifest_exists": bool(manifest),
        "report_path": report_relative,
        "from_template_id": source_template,
        "to_template_id": target_template,
        "strategy": "plan_only_overwrite_with_backup",
        "compatibility_checks": compatibility_checks,
        "migration_steps": _template_migration_steps(source_template, target_template),
        "file_operations": file_operations,
        "data_migrations": data_migrations,
        "validation_plan": validation_plan,
        "rollback_plan": rollback_plan,
        "skill_constraints": skill_constraints,
        "blocking_checks": blocking_checks,
        "warning_checks": warning_checks,
        "generated_at": _utc_now(),
        "message": "Game creation template migration strategy generated; no project files are changed unless write_report is enabled.",
    })
    if write_report:
        _write_json_report(root, report_relative, payload)
    return payload


def _parse_scene_file(root: Path, scene_path: str) -> Dict[str, Any]:
    relative_path = str(scene_path or "").strip()
    if not relative_path:
        return {}
    path = root / relative_path
    if not path.exists():
        return {
            "scene_path": relative_path,
            "exists": False,
            "root_node": "",
            "nodes": [],
            "node_types": [],
            "script_paths": [],
            "instance_paths": [],
        }
    content = path.read_text(encoding="utf-8")
    resources = _parse_ext_resources(content)
    nodes: List[Dict[str, Any]] = []
    node_matches = list(re.finditer(r'^\[node\s+([^\]]+)\]', content, flags=re.MULTILINE))
    for index, match in enumerate(node_matches):
        attrs = _parse_scene_attrs(match.group(1))
        block_end = node_matches[index + 1].start() if index + 1 < len(node_matches) else len(content)
        block = content[match.end():block_end]
        name = attrs.get("name", "")
        parent = attrs.get("parent", "")
        node_path = _scene_node_path(name, parent)
        script_resource_id = _extract_ext_resource_id(block, "script")
        instance_resource_id = _extract_inline_ext_resource_id(attrs.get("instance", ""))
        nodes.append({
            "name": name,
            "path": node_path,
            "type": attrs.get("type", ""),
            "parent": parent,
            "script_path": resources.get(script_resource_id, {}).get("path", "") if script_resource_id else "",
            "instance_path": resources.get(instance_resource_id, {}).get("path", "") if instance_resource_id else "",
        })
    return {
        "scene_path": relative_path,
        "exists": True,
        "root_node": nodes[0]["name"] if nodes else "",
        "nodes": nodes,
        "node_types": sorted({item["type"] for item in nodes if item.get("type")}),
        "node_names": sorted({item["name"] for item in nodes if item.get("name")}),
        "script_paths": sorted({item["script_path"] for item in nodes if item.get("script_path")}),
        "instance_paths": sorted({item["instance_path"] for item in nodes if item.get("instance_path")}),
    }


def _validate_game_creation_layout(root: Path, relative_paths: Any) -> Dict[str, Any]:
    validator = ProjectLayoutValidator(project_root=root, runtime_root=Path.cwd())
    checks: List[Dict[str, Any]] = []
    blocking_checks: List[str] = []
    for relative_path in sorted(str(path or "").strip() for path in relative_paths):
        kind = _managed_kind_for_game_creation_path(relative_path)
        if not kind:
            continue
        result = validator.validate_managed_path(root / relative_path, kind)
        check = {
            "path": relative_path,
            "kind": kind,
            "status": "passed" if result.get("passed") else "blocked",
            "issues": list(result.get("issues") or []),
        }
        checks.append(check)
        for issue in check["issues"]:
            blocking_checks.append(f"layout {relative_path}: {issue.get('message') or issue.get('code')}")
    return {
        "checks": checks,
        "check_count": len(checks),
        "blocking_checks": blocking_checks,
    }


def _build_game_creation_governance_gate(root: Path, changed_paths: List[str]) -> Dict[str, Any]:
    evidence = {
        "contract": True,
        "layout": True,
        "schema": True,
        "preview_or_diff": True,
        "quality_gate": True,
        "rollback": True,
        "tests": True,
        "docs": True,
    }
    return build_governance_enforcement(
        root,
        runtime_root=Path.cwd(),
        change_type="game_creation",
        evidence=evidence,
        changed_paths=list(changed_paths),
        notes="P19 game-create --apply pre-write governance gate.",
        mode="strict",
        fail_on_warnings=False,
    )


def _managed_kind_for_game_creation_path(relative_path: str) -> str:
    if relative_path.startswith("scripts/") and relative_path.endswith(".gd"):
        return "generated_script"
    if relative_path.startswith("scenes/") and relative_path.endswith(".tscn"):
        return "generated_scene"
    if relative_path.startswith("data_tables/") and Path(relative_path).suffix.lower() in {".csv", ".tsv", ".json"}:
        return "data_table"
    return ""


def _scene_graph_from_snapshot(snapshot: Dict[str, Any] | None) -> Dict[str, Any]:
    if not isinstance(snapshot, dict):
        return {}
    normalized = normalize_scene_graph_snapshot(snapshot)
    scene_path = _res_to_relative(normalized.get("scene_path") or "")
    if not scene_path:
        return {}
    nodes = []
    for item in list(normalized.get("nodes") or []):
        if not isinstance(item, dict):
            continue
        node = dict(item)
        if node.get("script_path"):
            node["script_path"] = _res_to_relative(str(node.get("script_path") or ""))
        if node.get("instance_path"):
            node["instance_path"] = _res_to_relative(str(node.get("instance_path") or ""))
        nodes.append(node)
    return {
        "scene_path": scene_path,
        "exists": True,
        "root_node": normalized.get("root_node") or "",
        "nodes": nodes,
        "node_types": sorted({str(item.get("type") or "") for item in nodes if item.get("type")}),
        "node_names": sorted({str(item.get("name") or "") for item in nodes if item.get("name")}),
        "script_paths": sorted({str(item.get("script_path") or "") for item in nodes if item.get("script_path")}),
        "instance_paths": sorted({str(item.get("instance_path") or "") for item in nodes if item.get("instance_path")}),
        "snapshot_source": normalized.get("source") or "godot_plugin",
        "captured_at": normalized.get("captured_at") or "",
    }


def _live_snapshot_summary(snapshot: Dict[str, Any] | None) -> Dict[str, Any]:
    if not isinstance(snapshot, dict):
        return {}
    normalized = normalize_scene_graph_snapshot(snapshot)
    scene_path = _res_to_relative(normalized.get("scene_path") or "")
    if not scene_path:
        return {}
    return {
        "scene_path": scene_path,
        "root_node": normalized.get("root_node") or "",
        "node_count": int(normalized.get("node_count") or 0),
        "source": normalized.get("source") or "godot_plugin",
        "captured_at": normalized.get("captured_at") or "",
        "node_types": list(normalized.get("node_types") or []),
        "script_paths": list(normalized.get("script_paths") or []),
    }


def _merge_live_scene_graph(scene_graph: List[Dict[str, Any]], live_graph: Dict[str, Any]) -> List[Dict[str, Any]]:
    merged = []
    replaced = False
    live_scene = str(live_graph.get("scene_path") or "")
    for graph in scene_graph:
        if str(graph.get("scene_path") or "") == live_scene:
            merged.append(live_graph)
            replaced = True
        else:
            merged.append(graph)
    if not replaced:
        merged.append(live_graph)
    return merged


def _review_game_creation_data_tables(root: Path, plan: Dict[str, Any]) -> List[Dict[str, Any]]:
    reviews: List[Dict[str, Any]] = []
    for item in list(plan.get("data_tables") or []):
        path = str(item.get("path") or "").strip()
        expected_schema = str(item.get("schema") or "gameplay_balance").strip()
        if not path:
            continue
        table_path = root / path
        if not table_path.exists():
            reviews.append({
                "path": path,
                "schema": expected_schema,
                "status": "blocked",
                "message": "data table is missing",
                "required_sections": [],
            })
            continue
        try:
            payload = json.loads(table_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            reviews.append({
                "path": path,
                "schema": expected_schema,
                "status": "blocked",
                "message": f"invalid JSON: {exc}",
                "required_sections": [],
            })
            continue
        schema = str(payload.get("schema") or "").strip()
        required_sections = _required_data_table_sections(expected_schema, str(plan.get("template_id") or ""))
        missing_sections = [section for section in required_sections if section not in payload]
        status = "blocked" if schema != expected_schema else "warning" if missing_sections else "passed"
        if schema != expected_schema:
            message = f"schema mismatch: expected {expected_schema}, got {schema or 'missing'}"
        elif missing_sections:
            message = "missing sections: " + ", ".join(missing_sections)
        else:
            message = f"{expected_schema} table matches expected schema and sections"
        reviews.append({
            "path": path,
            "schema": expected_schema,
            "actual_schema": schema,
            "status": status,
            "message": message,
            "required_sections": required_sections,
            "missing_sections": missing_sections,
        })
    return reviews


def _required_data_table_sections(schema: str, template_id: str) -> List[str]:
    if schema == "game_creation_input_replay":
        return ["schema", "template_id", "scene_path", "steps", "golden_screenshot_plan"]
    return _required_gameplay_sections(template_id)


def _required_gameplay_sections(template_id: str) -> List[str]:
    if template_id == TOWER_DEFENSE_TEMPLATE_ID:
        return ["schema", "player", "towers", "enemies", "base", "economy", "waves"]
    if template_id == SURVIVAL_CRAFTING_TEMPLATE_ID:
        return ["schema", "player", "resources", "crafting", "survival"]
    if template_id == VISUAL_NOVEL_TEMPLATE_ID:
        return ["schema", "dialogue", "choices", "characters", "progression"]
    if template_id == ROGUELIKE_TEMPLATE_ID:
        return ["schema", "player", "combat", "loot", "enemies", "dungeon"]
    if template_id == ARPG_TEMPLATE_ID:
        return ["schema", "player", "combat", "quest", "enemies", "arena"]
    if template_id == TOPDOWN_ACTION_TEMPLATE_ID:
        return ["schema", "player", "collectibles", "enemies", "arena"]
    return ["schema", "player", "collectibles", "enemies"]


def _parse_ext_resources(content: str) -> Dict[str, Dict[str, str]]:
    resources: Dict[str, Dict[str, str]] = {}
    for match in re.finditer(r'^\[ext_resource\s+([^\]]+)\]', content, flags=re.MULTILINE):
        attrs = _parse_scene_attrs(match.group(1))
        resource_id = attrs.get("id", "")
        if resource_id:
            resources[resource_id] = {
                "type": attrs.get("type", ""),
                "path": _res_to_relative(attrs.get("path", "")),
            }
    return resources


def _parse_scene_attrs(raw: str) -> Dict[str, str]:
    attrs: Dict[str, str] = {}
    for key, value in re.findall(r'(\w+)=(".*?"|[^\s]+)', raw):
        attrs[key] = value[1:-1] if value.startswith('"') and value.endswith('"') else value
    return attrs


def _extract_ext_resource_id(block: str, property_name: str) -> str:
    match = re.search(rf'^\s*{re.escape(property_name)}\s*=\s*ExtResource\("([^"]+)"\)', block, flags=re.MULTILINE)
    return match.group(1) if match else ""


def _extract_inline_ext_resource_id(value: str) -> str:
    match = re.search(r'ExtResource\("([^"]+)"\)', value or "")
    return match.group(1) if match else ""


def _scene_node_path(name: str, parent: str) -> str:
    if not parent or parent == ".":
        return name
    return f"{parent.rstrip('/')}/{name}"


def _res_to_relative(path: str) -> str:
    raw = str(path or "").strip()
    return raw[6:] if raw.startswith("res://") else raw


def _read_scripts(root: Path, artifact_paths: List[str]) -> Dict[str, str]:
    scripts: Dict[str, str] = {}
    for relative_path in artifact_paths:
        script_path = str(relative_path or "").strip()
        if not script_path.endswith(".gd"):
            continue
        path = root / script_path
        if path.exists():
            scripts[script_path] = path.read_text(encoding="utf-8")
    return scripts


def _audit_module(
    root: Path,
    module: Dict[str, Any],
    graph_by_path: Dict[str, Dict[str, Any]],
    scripts: Dict[str, str],
) -> Dict[str, Any]:
    module_id = str(module.get("module_id") or "").strip()
    scene_path = str(module.get("scene_path") or "").strip()
    script_path = str(module.get("script_path") or "").strip()
    graph = graph_by_path.get(scene_path, {})
    expected_nodes = [node for node in list(module.get("godot_nodes") or []) if node != "ProjectSettings"]
    present_node_types = set(graph.get("node_types") or [])
    present_node_names = set(graph.get("node_names") or [])
    missing_nodes = [node for node in expected_nodes if node not in present_node_types and node not in present_node_names]
    if scene_path == "scenes/Main.tscn":
        missing_nodes = _filter_main_instanced_nodes(missing_nodes, graph)
    missing_scripts = []
    if script_path and script_path != "project.godot" and not (root / script_path).exists():
        missing_scripts.append(script_path)
    missing_signals = [
        signal
        for signal in list(module.get("signals") or [])
        if signal != "body_entered" and not _signal_found(signal, scripts)
    ]
    scene_missing = bool(scene_path and scene_path != "project.godot" and not graph.get("exists"))
    status = "blocked" if scene_missing or missing_nodes or missing_scripts else "warning" if missing_signals else "passed"
    return {
        "module_id": module_id,
        "label": str(module.get("label") or module_id),
        "role": str(module.get("role") or ""),
        "scene_path": scene_path,
        "script_path": script_path,
        "scene_missing": scene_missing,
        "missing_nodes": missing_nodes,
        "missing_scripts": missing_scripts,
        "missing_signals": missing_signals,
        "skill_names": [item.get("skill_name") for item in list(module.get("skill_bindings") or []) if item.get("skill_name")],
        "status": status,
    }


def _filter_main_instanced_nodes(missing_nodes: List[str], graph: Dict[str, Any]) -> List[str]:
    instance_paths = set(graph.get("instance_paths") or [])
    filtered = []
    for node_type in missing_nodes:
        if node_type == "CharacterBody2D" and "scenes/Player.tscn" in instance_paths:
            continue
        if node_type == "Area2D" and ({"scenes/Coin.tscn", "scenes/Pickup.tscn", "scenes/Enemy.tscn"} & instance_paths):
            continue
        filtered.append(node_type)
    return filtered


def _signal_found(signal: str, scripts: Dict[str, str]) -> bool:
    declaration = f"signal {signal}"
    connection = f".{signal}.connect"
    return any(declaration in content or connection in content for content in scripts.values())


def _audit_response(item: Dict[str, Any], graph_by_path: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    node_path = str(item.get("node_path") or "").strip()
    node_name = node_path.split("/")[-1]
    node_found = any(
        node.get("path") == node_path or node.get("path") == node_name or node.get("path", "").endswith(f"/{node_name}")
        for graph in graph_by_path.values()
        for node in list(graph.get("nodes") or [])
    )
    return {
        "trigger": str(item.get("trigger") or ""),
        "node_path": node_path,
        "script_path": str(item.get("script_path") or ""),
        "response": str(item.get("response") or ""),
        "node_found": node_found,
        "status": "passed" if node_found else "warning",
    }


def _write_audit_report(root: Path, report_path: str, payload: Dict[str, Any]) -> None:
    path = root / str(report_path or DEFAULT_SCENE_GRAPH_AUDIT_PATH).strip()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _write_review_report(root: Path, payload: Dict[str, Any]) -> None:
    path = root / DEFAULT_GAME_CREATION_REVIEW_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    doc_path = root / DEFAULT_GAME_CREATION_REVIEW_DOC_PATH
    doc_path.parent.mkdir(parents=True, exist_ok=True)
    doc_path.write_text(_review_doc(payload), encoding="utf-8")


def _write_json_report(root: Path, report_path: str, payload: Dict[str, Any]) -> None:
    path = root / report_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _read_json_file(path: Path) -> Dict[str, Any]:
    try:
        if path.exists():
            payload = json.loads(path.read_text(encoding="utf-8"))
            return payload if isinstance(payload, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}
    return {}


def _project_input_actions(root: Path) -> List[str]:
    project_file = root / "project.godot"
    try:
        content = project_file.read_text(encoding="utf-8")
    except OSError:
        return []
    return sorted({
        match.group(1)
        for match in re.finditer(r"^([A-Za-z_]\w*)=\{", content, flags=re.MULTILINE)
    })


def _build_replay_action_checks(steps: List[Dict[str, Any]], known_actions: List[str]) -> List[Dict[str, Any]]:
    known = set(known_actions)
    checks: List[Dict[str, Any]] = []
    for step in steps:
        action = str(step.get("action") or "").strip()
        input_name = str(step.get("input") or "").strip()
        if action not in {"press", "tap"}:
            continue
        checks.append({
            "step_id": str(step.get("step_id") or ""),
            "action": action,
            "input": input_name,
            "status": "passed" if input_name in known else "blocked",
            "message": "input action exists in project.godot" if input_name in known else "input action missing from project.godot",
        })
    return checks


def _replay_runtime_capture_path(steps: List[Dict[str, Any]], golden_plan: Dict[str, Any]) -> str:
    for step in reversed(steps):
        if str(step.get("action") or "").strip() == "capture_screenshot":
            target = str(step.get("target") or "").strip()
            if target:
                return target
    return str(golden_plan.get("runtime_capture_path") or "")


def _build_input_replay_script(
    scene_path: str,
    steps: List[Dict[str, Any]],
    required_nodes: List[str],
    screenshot_path: str,
) -> str:
    lines = [
        "extends SceneTree",
        "",
        "func _initialize():",
        "    var tree := self",
        f"    var packed = load({_gd_quote(scene_path)})",
        "    if packed == null:",
        "        push_error(\"Replay scene could not be loaded\")",
        "        quit(1)",
        "        return",
        "    var instance = packed.instantiate()",
        "    tree.root.add_child(instance)",
        "    await tree.process_frame",
    ]
    for node in required_nodes:
        node_text = str(node or "").strip()
        if not node_text:
            continue
        lines.extend([
            f"    if instance.name != {_gd_quote(node_text)} and instance.get_node_or_null({_gd_quote(node_text)}) == null:",
            f"        push_error({_gd_quote('Required replay node missing: ' + node_text)})",
            "        quit(1)",
            "        return",
        ])
    for step in steps:
        action = str(step.get("action") or "").strip()
        input_name = str(step.get("input") or "").strip()
        duration = max(1, int(step.get("duration_ms") or 100))
        if action == "press" and input_name:
            lines.extend([
                f"    Input.action_press({_gd_quote(input_name)})",
                f"    await tree.create_timer({duration / 1000:.3f}).timeout",
                f"    Input.action_release({_gd_quote(input_name)})",
                "    await tree.process_frame",
            ])
        elif action == "tap" and input_name:
            lines.extend([
                f"    Input.action_press({_gd_quote(input_name)})",
                "    await tree.process_frame",
                f"    Input.action_release({_gd_quote(input_name)})",
                "    await tree.process_frame",
            ])
        elif action == "capture_screenshot":
            target = str(step.get("target") or screenshot_path or "").strip()
            if target:
                lines.extend(_screenshot_gd_lines(target))
    if screenshot_path and not any(str(step.get("action") or "") == "capture_screenshot" for step in steps):
        lines.extend(_screenshot_gd_lines(screenshot_path))
    lines.extend([
        "    quit(0)",
        "",
    ])
    return "\n".join(lines)


def _screenshot_gd_lines(path: str) -> List[str]:
    normalized = str(path or "").replace("\\", "/")
    return [
        f"    var screenshot_path := ProjectSettings.globalize_path({_gd_quote('res://' + normalized.lstrip('/'))})",
        "    DirAccess.make_dir_recursive_absolute(screenshot_path.get_base_dir())",
        "    var replay_image: Image = null",
        "    var capture_mode := \"fallback_headless\"",
        "    if DisplayServer.get_name() != \"headless\":",
        "        var replay_texture: ViewportTexture = instance.get_viewport().get_texture()",
        "        if replay_texture != null:",
        "            replay_image = replay_texture.get_image()",
        "            if replay_image != null and not replay_image.is_empty():",
        "                capture_mode = \"viewport\"",
        "    if replay_image == null or replay_image.is_empty():",
        "        replay_image = Image.create(320, 180, false, Image.FORMAT_RGBA8)",
        "        replay_image.fill(Color(0.08, 0.12, 0.16, 1.0))",
        "        var marker_color := Color(0.25, 0.76, 0.54, 1.0)",
        "        for x in range(24, 296):",
        "            for y in range(24, 156):",
        "                if (int(x / 16) + int(y / 16)) % 2 == 0:",
        "                    replay_image.set_pixel(x, y, marker_color)",
        "    replay_image.save_png(screenshot_path)",
        "    print(\"REPLAY_SCREENSHOT_CAPTURE=\" + capture_mode)",
    ]


def _extract_replay_screenshot_capture_mode(stdout: str) -> str:
    marker = "REPLAY_SCREENSHOT_CAPTURE="
    for line in str(stdout or "").splitlines():
        text = line.strip()
        if text.startswith(marker):
            return text[len(marker):].strip()
    return ""


def _normalize_replay_render_mode(value: str) -> str:
    normalized = str(value or "").strip().lower().replace("-", "_")
    if normalized in {"viewport", "display", "rendered", "windowed"}:
        return "viewport"
    return "headless"


def _build_viewport_baseline_status(
    *,
    runtime_capture_path: str,
    screenshot_exists: bool,
    screenshot_capture_mode: str,
    executed: bool,
) -> Dict[str, Any]:
    if not runtime_capture_path:
        return {
            "viewport_baseline_status": "not_applicable",
            "viewport_baseline_ready": False,
            "viewport_baseline_message": "No runtime screenshot path is planned for this replay.",
        }
    if not executed:
        return {
            "viewport_baseline_status": "not_executed",
            "viewport_baseline_ready": False,
            "viewport_baseline_message": "Replay has not executed yet; viewport baseline readiness is unknown.",
        }
    if not screenshot_exists:
        return {
            "viewport_baseline_status": "blocked",
            "viewport_baseline_ready": False,
            "viewport_baseline_message": "Runtime screenshot was not produced.",
        }
    if screenshot_capture_mode == "viewport":
        return {
            "viewport_baseline_status": "passed",
            "viewport_baseline_ready": True,
            "viewport_baseline_message": "Runtime screenshot was captured from the active viewport.",
        }
    if screenshot_capture_mode == "fallback_headless":
        return {
            "viewport_baseline_status": "warning",
            "viewport_baseline_ready": False,
            "viewport_baseline_message": "Runtime screenshot used the deterministic headless fallback; rerun with a display render backend before treating it as viewport golden evidence.",
        }
    return {
        "viewport_baseline_status": "unknown",
        "viewport_baseline_ready": False,
        "viewport_baseline_message": "Runtime screenshot exists, but the replay did not report its capture mode.",
    }


def _gd_quote(value: str) -> str:
    return json.dumps(str(value or ""))


def _review_doc(payload: Dict[str, Any]) -> str:
    audit_summary = dict(payload.get("audit_summary") or {})
    lines = [
        f"# {payload.get('title') or 'Game Creation'} Acceptance Review",
        "",
        f"- Status: `{payload.get('status') or '-'}`",
        f"- Ready For Acceptance: `{bool(payload.get('ready_for_acceptance'))}`",
        f"- Template: `{payload.get('template_id') or '-'}`",
        f"- Manifest: `{payload.get('manifest_path') or '-'}`",
        f"- Generated At: `{payload.get('generated_at') or '-'}`",
        "",
        "## Audit Summary",
        "",
        f"- Audit Status: `{audit_summary.get('status') or '-'}`",
        f"- Scene Count: `{audit_summary.get('scene_count', 0)}`",
        f"- Node Count: `{audit_summary.get('node_count', 0)}`",
        f"- Live Snapshot: `used={bool(audit_summary.get('live_snapshot_used'))} / source={audit_summary.get('live_snapshot_source') or '-'} / scene={audit_summary.get('live_snapshot_scene_path') or '-'} / nodes={audit_summary.get('live_snapshot_node_count', 0)}`",
        f"- Missing Scenes: `{audit_summary.get('missing_scene_count', 0)}`",
        f"- Missing Scripts: `{audit_summary.get('missing_script_count', 0)}`",
        f"- Missing Nodes: `{audit_summary.get('missing_node_count', 0)}`",
        f"- Missing Signals: `{audit_summary.get('missing_signal_count', 0)}`",
        f"- Data Tables: `{audit_summary.get('passed_data_table_count', 0)}/{audit_summary.get('data_table_count', 0)}`",
        "",
        "## Acceptance Checklist",
        "",
    ]
    for item in list(payload.get("acceptance_checklist") or []):
        blockers = "; ".join(item.get("blockers") or [])
        suffix = f" blockers={blockers}" if blockers else ""
        lines.append(f"- `{item.get('status') or 'pending'}` {item.get('label') or '-'} ({item.get('validation_method') or '-'}){suffix}")
    lines.extend(["", "## Module Review", ""])
    for item in list(payload.get("module_review") or []):
        missing = []
        if item.get("missing_nodes"):
            missing.append("nodes=" + ",".join(item.get("missing_nodes") or []))
        if item.get("missing_scripts"):
            missing.append("scripts=" + ",".join(item.get("missing_scripts") or []))
        if item.get("missing_signals"):
            missing.append("signals=" + ",".join(item.get("missing_signals") or []))
        missing_text = f" missing={' | '.join(missing)}" if missing else ""
        skills = ", ".join(item.get("skill_names") or [])
        lines.append(f"- `{item.get('status') or 'pending'}` {item.get('module_id') or '-'} / role=`{item.get('role') or '-'}` / skills=`{skills or '-'}`{missing_text}")
    lines.extend(["", "## Data Table Review", ""])
    for item in list(payload.get("data_table_review") or []):
        missing = ", ".join(item.get("missing_sections") or [])
        suffix = f" missing={missing}" if missing else ""
        lines.append(f"- `{item.get('status') or 'pending'}` {item.get('path') or '-'} / schema=`{item.get('actual_schema') or item.get('schema') or '-'}` / {item.get('message') or '-'}{suffix}")
    if not payload.get("data_table_review"):
        lines.append("- none")
    lines.extend(["", "## Blocking Checks", ""])
    for item in list(payload.get("blocking_checks") or []):
        lines.append(f"- {item}")
    if not payload.get("blocking_checks"):
        lines.append("- none")
    lines.extend(["", "## Warning Checks", ""])
    for item in list(payload.get("warning_checks") or []):
        lines.append(f"- {item}")
    if not payload.get("warning_checks"):
        lines.append("- none")
    lines.append("")
    return "\n".join(lines)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _validate_request(title: str, template_id: str) -> List[str]:
    issues = []
    if not str(title or "").strip():
        issues.append("title is required")
    if template_id not in SUPPORTED_TEMPLATES:
        issues.append(f"unsupported template_id: {template_id}")
    return issues


def _resolve_template_id(value: str) -> str:
    normalized = str(value or DEFAULT_GAME_TEMPLATE_ID).strip().lower()
    return TEMPLATE_ALIASES.get(normalized, normalized)


def _template_spec(template_id: str) -> Dict[str, Any]:
    if template_id == SURVIVAL_CRAFTING_TEMPLATE_ID:
        return {
            "genre": "survival_crafting_2d",
            "features": SURVIVAL_CRAFTING_FEATURES,
            "scene_paths": ["scenes/Main.tscn", "scenes/Player.tscn", "scenes/Resource.tscn", "scenes/Campfire.tscn"],
            "scene_roles": ["survival_field", "survivor", "resource_node", "crafted_campfire"],
            "pickup_script": "scripts/resource_node.gd",
            "enemy_script": "scripts/campfire_controller.gd",
            "input_map": {
                "move_left": ["A", "Left"],
                "move_right": ["D", "Right"],
                "move_up": ["W", "Up"],
                "move_down": ["S", "Down"],
                "gather": ["J", "Space"],
                "craft": ["K", "E"],
            },
            "asset_plan": [
                {"asset_id": "survivor_placeholder", "type": "shape", "usage": "player_survivor"},
                {"asset_id": "resource_placeholder", "type": "shape", "usage": "wood_resource"},
                {"asset_id": "campfire_placeholder", "type": "shape", "usage": "crafted_station"},
                {"asset_id": "field_bounds_placeholder", "type": "shape", "usage": "survival_field"},
            ],
            "playtest_plan": ["Open res://scenes/Main.tscn", "Move survivor", "Press gather", "Press craft", "Observe campfire and survival HUD"],
            "acceptance_criteria": [
                "Survival field opens without missing resource errors",
                "Survivor can move with configured inputs",
                "Gather input increases wood resources",
                "Craft input builds a campfire when resources are available",
                "Hunger and health values are visible in HUD",
            ],
        }
    if template_id == VISUAL_NOVEL_TEMPLATE_ID:
        return {
            "genre": "visual_novel_2d",
            "features": VISUAL_NOVEL_FEATURES,
            "scene_paths": ["scenes/Main.tscn", "scenes/Player.tscn", "scenes/Choice.tscn", "scenes/Npc.tscn"],
            "scene_roles": ["dialogue_stage", "reader_cursor", "choice_option", "speaker_portrait"],
            "pickup_script": "scripts/choice_option.gd",
            "enemy_script": "scripts/npc_portrait.gd",
            "input_map": {
                "advance_dialogue": ["Space", "Enter"],
                "choice_left": ["A", "Left"],
                "choice_right": ["D", "Right"],
                "select_choice": ["J", "Enter"],
            },
            "asset_plan": [
                {"asset_id": "speaker_placeholder", "type": "shape", "usage": "speaker_portrait"},
                {"asset_id": "choice_placeholder", "type": "shape", "usage": "choice_option"},
                {"asset_id": "dialogue_box_placeholder", "type": "shape", "usage": "dialogue_ui"},
            ],
            "playtest_plan": ["Open res://scenes/Main.tscn", "Advance dialogue", "Move choice focus", "Select a choice", "Observe affinity and scene state update"],
            "acceptance_criteria": [
                "Dialogue stage opens without missing resource errors",
                "Advance input progresses dialogue text",
                "Choice focus moves with configured inputs",
                "Select choice updates affinity and HUD state",
                "Speaker portrait and dialogue HUD are visible",
            ],
        }
    if template_id == ROGUELIKE_TEMPLATE_ID:
        return {
            "genre": "roguelike_2d",
            "features": ROGUELIKE_FEATURES,
            "scene_paths": ["scenes/Main.tscn", "scenes/Player.tscn", "scenes/Pickup.tscn", "scenes/Enemy.tscn"],
            "scene_roles": ["dungeon_room", "hero", "loot", "chasing_enemy"],
            "pickup_script": "scripts/loot_collectible.gd",
            "enemy_script": "scripts/enemy_chaser.gd",
            "input_map": {
                "move_left": ["A", "Left"],
                "move_right": ["D", "Right"],
                "move_up": ["W", "Up"],
                "move_down": ["S", "Down"],
                "attack": ["Space", "J"],
                "descend": ["E", "Enter"],
            },
            "asset_plan": [
                {"asset_id": "hero_placeholder", "type": "shape", "usage": "player_hero"},
                {"asset_id": "loot_placeholder", "type": "shape", "usage": "loot_pickup"},
                {"asset_id": "enemy_placeholder", "type": "shape", "usage": "chasing_enemy"},
                {"asset_id": "stair_placeholder", "type": "shape", "usage": "floor_exit"},
                {"asset_id": "room_bounds_placeholder", "type": "shape", "usage": "dungeon_room"},
            ],
            "playtest_plan": ["Open res://scenes/Main.tscn", "Move hero in four directions", "Press attack", "Collect loot", "Press descend", "Touch enemy and lose health"],
            "acceptance_criteria": [
                "Dungeon room opens without missing resource errors",
                "Hero can move in four directions with configured inputs",
                "Attack input emits combat hook",
                "Loot collection updates HUD loot count",
                "Descend input advances dungeon depth on HUD",
                "Enemy contact damages player health",
            ],
        }
    if template_id == ARPG_TEMPLATE_ID:
        return {
            "genre": "arpg_2d",
            "features": ARPG_FEATURES,
            "scene_paths": ["scenes/Main.tscn", "scenes/Player.tscn", "scenes/Pickup.tscn", "scenes/Enemy.tscn"],
            "scene_roles": ["quest_arena", "hero", "quest_relic", "chasing_enemy"],
            "pickup_script": "scripts/relic_collectible.gd",
            "enemy_script": "scripts/enemy_chaser.gd",
            "input_map": {
                "move_left": ["A", "Left"],
                "move_right": ["D", "Right"],
                "move_up": ["W", "Up"],
                "move_down": ["S", "Down"],
                "attack": ["Space", "J"],
                "dodge": ["Shift", "K"],
            },
            "asset_plan": [
                {"asset_id": "hero_placeholder", "type": "shape", "usage": "player_hero"},
                {"asset_id": "relic_placeholder", "type": "shape", "usage": "quest_objective"},
                {"asset_id": "enemy_placeholder", "type": "shape", "usage": "chasing_enemy"},
                {"asset_id": "arena_bounds_placeholder", "type": "shape", "usage": "level_bounds"},
            ],
            "playtest_plan": ["Open res://scenes/Main.tscn", "Move hero in four directions", "Press attack", "Press dodge", "Collect relic", "Touch enemy and lose health"],
            "acceptance_criteria": [
                "Quest arena opens without missing resource errors",
                "Hero can move in four directions with configured inputs",
                "Attack input emits combat hook",
                "Dodge input briefly increases movement response",
                "Relic collection updates quest progress on HUD",
                "Enemy contact damages player health",
            ],
        }
    if template_id == TOWER_DEFENSE_TEMPLATE_ID:
        return {
            "genre": "tower_defense_2d",
            "features": TOWER_DEFENSE_FEATURES,
            "scene_paths": ["scenes/Main.tscn", "scenes/Player.tscn", "scenes/Tower.tscn", "scenes/Enemy.tscn"],
            "scene_roles": ["defense_map", "placement_cursor", "tower", "wave_enemy"],
            "pickup_script": "scripts/tower_controller.gd",
            "enemy_script": "scripts/enemy_runner.gd",
            "input_map": {
                "move_left": ["A", "Left"],
                "move_right": ["D", "Right"],
                "move_up": ["W", "Up"],
                "move_down": ["S", "Down"],
                "place_tower": ["Space", "J"],
            },
            "asset_plan": [
                {"asset_id": "cursor_placeholder", "type": "shape", "usage": "placement_cursor"},
                {"asset_id": "tower_placeholder", "type": "shape", "usage": "defense_tower"},
                {"asset_id": "enemy_placeholder", "type": "shape", "usage": "wave_enemy"},
                {"asset_id": "base_placeholder", "type": "shape", "usage": "defense_goal"},
            ],
            "playtest_plan": ["Open res://scenes/Main.tscn", "Move placement cursor", "Press place_tower", "Observe tower targeting", "Let enemy reach base and reduce health"],
            "acceptance_criteria": [
                "Main defense map opens without missing resource errors",
                "Placement cursor moves with configured inputs",
                "Place tower input emits a tower placement event",
                "Tower can target the wave enemy",
                "Enemy reaching the base damages base health and updates HUD",
            ],
        }
    if template_id == TOPDOWN_ACTION_TEMPLATE_ID:
        return {
            "genre": "topdown_action_2d",
            "features": TOPDOWN_FEATURES,
            "scene_paths": ["scenes/Main.tscn", "scenes/Player.tscn", "scenes/Pickup.tscn", "scenes/Enemy.tscn"],
            "scene_roles": ["arena", "player", "pickup", "hazard"],
            "pickup_script": "scripts/pickup_collectible.gd",
            "enemy_script": "scripts/enemy_chaser.gd",
            "input_map": {
                "move_left": ["A", "Left"],
                "move_right": ["D", "Right"],
                "move_up": ["W", "Up"],
                "move_down": ["S", "Down"],
                "attack": ["Space", "J"],
            },
            "asset_plan": [
                {"asset_id": "player_placeholder", "type": "shape", "usage": "player"},
                {"asset_id": "pickup_placeholder", "type": "shape", "usage": "collectible"},
                {"asset_id": "enemy_placeholder", "type": "shape", "usage": "hazard"},
                {"asset_id": "arena_bounds_placeholder", "type": "shape", "usage": "level_bounds"},
            ],
            "playtest_plan": ["Open res://scenes/Main.tscn", "Move in four directions", "Press attack", "Collect pickup", "Touch enemy and lose health"],
            "acceptance_criteria": [
                "Main arena opens without missing resource errors",
                "Player can move in four directions with configured inputs",
                "Attack input is handled by player controller",
                "Pickup collection updates HUD score",
                "Enemy contact damages player health",
            ],
        }
    return {
        "genre": "platformer_2d",
        "features": PLATFORMER_FEATURES,
        "scene_paths": ["scenes/Main.tscn", "scenes/Player.tscn", "scenes/Coin.tscn", "scenes/Enemy.tscn"],
        "scene_roles": ["main_level", "player", "collectible", "hazard"],
        "pickup_script": "scripts/coin_collectible.gd",
        "enemy_script": "scripts/enemy_patrol.gd",
        "input_map": {
            "move_left": ["A", "Left"],
            "move_right": ["D", "Right"],
            "jump": ["Space", "W", "Up"],
        },
        "asset_plan": [
            {"asset_id": "player_placeholder", "type": "shape", "usage": "player"},
            {"asset_id": "coin_placeholder", "type": "shape", "usage": "collectible"},
            {"asset_id": "enemy_placeholder", "type": "shape", "usage": "hazard"},
        ],
        "playtest_plan": ["Open res://scenes/Main.tscn", "Move left/right", "Jump", "Collect a coin", "Touch enemy and lose health"],
        "acceptance_criteria": [
            "Main scene opens without missing resource errors",
            "Player can move and jump with configured inputs",
            "Coin collection updates HUD score",
            "Enemy contact damages player health",
        ],
    }


def _module_plan(template_id: str) -> List[Dict[str, Any]]:
    if template_id == SURVIVAL_CRAFTING_TEMPLATE_ID:
        return [
            _module_entry(
                "input_map",
                "Input Map",
                scene_path="project.godot",
                script_path="project.godot",
                role="developer",
                skills=["manage_input_mapping", "plan_game_feature"],
                inputs=["move_left", "move_right", "move_up", "move_down", "gather", "craft"],
                godot_nodes=["ProjectSettings"],
                response="Godot input actions expose movement, gathering, and crafting controls.",
            ),
            _module_entry(
                "survivor_controller",
                "Survivor Movement and Actions",
                scene_path="scenes/Player.tscn",
                script_path="scripts/player_controller.gd",
                role="code_generator",
                depends_on=["input_map"],
                skills=["generate_movement_script", "attach_script_to_node", "configure_physics_collision"],
                inputs=["move_left", "move_right", "move_up", "move_down", "gather", "craft"],
                signals=["gathered", "crafted"],
                godot_nodes=["CharacterBody2D", "CollisionShape2D"],
                response="Survivor moves in the field and emits gathered/crafted actions from input.",
            ),
            _module_entry(
                "resource_node",
                "Resource Node",
                scene_path="scenes/Resource.tscn",
                script_path="scripts/resource_node.gd",
                role="code_generator",
                depends_on=["survivor_controller"],
                skills=["create_godot_scene", "wire_signal_connection", "attach_script_to_node"],
                signals=["harvested"],
                godot_nodes=["Area2D", "CollisionShape2D"],
                response="Resource node emits harvested when gathered, providing wood to inventory.",
            ),
            _module_entry(
                "campfire",
                "Campfire Crafting",
                scene_path="scenes/Campfire.tscn",
                script_path="scripts/campfire_controller.gd",
                role="developer",
                depends_on=["resource_node"],
                skills=["create_godot_scene", "wire_signal_connection", "attach_script_to_node"],
                signals=["built"],
                godot_nodes=["Node2D", "Polygon2D"],
                response="Campfire tracks built state and exposes warmth once crafted.",
            ),
            _module_entry(
                "survival_hud",
                "Survival HUD",
                scene_path="scenes/Main.tscn",
                script_path="scripts/hud_controller.gd",
                role="developer",
                depends_on=["resource_node", "campfire"],
                skills=["auto_layout_ui", "wire_signal_connection", "manage_game_data_tables"],
                signals=["gathered", "crafted", "harvested", "built"],
                godot_nodes=["CanvasLayer", "Label", "Node", "Campfire"],
                response="HUD updates wood, hunger, HP, and campfire status from survival actions.",
            ),
            _module_entry(
                "playtest_gate",
                "Playable Smoke Gate",
                scene_path="scenes/Main.tscn",
                script_path="",
                role="tester",
                depends_on=["survival_hud"],
                skills=["smoke_test_scene", "audit_logic_errors", "audit_project_consistency"],
                godot_nodes=["Main", "Player", "Resource", "Campfire", "HUD"],
                response="Scene smoke pass confirms movement, gathering, crafting, survival HUD, and project resources.",
            ),
        ]
    if template_id == VISUAL_NOVEL_TEMPLATE_ID:
        return [
            _module_entry(
                "input_map",
                "Input Map",
                scene_path="project.godot",
                script_path="project.godot",
                role="developer",
                skills=["manage_input_mapping", "plan_game_feature"],
                inputs=["advance_dialogue", "choice_left", "choice_right", "select_choice"],
                godot_nodes=["ProjectSettings"],
                response="Godot input actions expose dialogue advance and branching choice controls.",
            ),
            _module_entry(
                "reader_controller",
                "Reader Choice Controller",
                scene_path="scenes/Player.tscn",
                script_path="scripts/player_controller.gd",
                role="code_generator",
                depends_on=["input_map"],
                skills=["generate_movement_script", "attach_script_to_node"],
                inputs=["advance_dialogue", "choice_left", "choice_right", "select_choice"],
                signals=["advanced", "choice_changed", "choice_selected"],
                godot_nodes=["Node2D"],
                response="Reader controller emits dialogue and choice signals from configured inputs.",
            ),
            _module_entry(
                "choice_option",
                "Choice Option",
                scene_path="scenes/Choice.tscn",
                script_path="scripts/choice_option.gd",
                role="code_generator",
                depends_on=["reader_controller"],
                skills=["create_godot_scene", "wire_signal_connection", "attach_script_to_node"],
                signals=["selected"],
                godot_nodes=["Area2D", "Label", "CollisionShape2D"],
                response="Choice option stores label text and emits selected when activated.",
            ),
            _module_entry(
                "speaker_portrait",
                "Speaker Portrait",
                scene_path="scenes/Npc.tscn",
                script_path="scripts/npc_portrait.gd",
                role="developer",
                depends_on=["reader_controller"],
                skills=["create_godot_scene", "attach_script_to_node"],
                godot_nodes=["Node2D", "Polygon2D", "Label"],
                response="Speaker portrait exposes speaker name and mood state for the dialogue HUD.",
            ),
            _module_entry(
                "dialogue_hud",
                "Dialogue HUD and Affinity",
                scene_path="scenes/Main.tscn",
                script_path="scripts/hud_controller.gd",
                role="developer",
                depends_on=["choice_option", "speaker_portrait"],
                skills=["auto_layout_ui", "wire_signal_connection", "manage_game_data_tables"],
                signals=["advanced", "choice_changed", "choice_selected"],
                godot_nodes=["CanvasLayer", "Label", "Panel", "Node"],
                response="HUD updates dialogue line, choice focus, affinity, and scene state from reader events.",
            ),
            _module_entry(
                "playtest_gate",
                "Playable Smoke Gate",
                scene_path="scenes/Main.tscn",
                script_path="",
                role="tester",
                depends_on=["dialogue_hud"],
                skills=["smoke_test_scene", "audit_logic_errors", "audit_project_consistency"],
                godot_nodes=["Main", "Player", "Choice", "Npc", "HUD"],
                response="Scene smoke pass confirms dialogue advance, choice focus, selection, affinity HUD, and resources.",
            ),
        ]
    if template_id == ROGUELIKE_TEMPLATE_ID:
        return [
            _module_entry(
                "input_map",
                "Input Map",
                scene_path="project.godot",
                script_path="project.godot",
                role="developer",
                skills=["manage_input_mapping", "plan_game_feature"],
                inputs=["move_left", "move_right", "move_up", "move_down", "attack", "descend"],
                godot_nodes=["ProjectSettings"],
                response="Godot input actions expose room movement, attack, and floor descent controls.",
            ),
            _module_entry(
                "hero_controller",
                "Hero Movement, Attack, and Descend",
                scene_path="scenes/Player.tscn",
                script_path="scripts/player_controller.gd",
                role="code_generator",
                depends_on=["input_map"],
                skills=["generate_movement_script", "attach_script_to_node", "configure_physics_collision"],
                inputs=["move_left", "move_right", "move_up", "move_down", "attack", "descend"],
                signals=["attacked", "descended"],
                godot_nodes=["CharacterBody2D", "AttackArea", "CollisionShape2D"],
                response="Hero moves through the dungeon room, emits attacked on combat input, and emits descended on floor descent input.",
            ),
            _module_entry(
                "loot_loop",
                "Loot Collection",
                scene_path="scenes/Pickup.tscn",
                script_path="scripts/loot_collectible.gd",
                role="code_generator",
                depends_on=["hero_controller"],
                skills=["create_godot_scene", "wire_signal_connection", "attach_script_to_node"],
                signals=["collected"],
                godot_nodes=["Area2D", "CollisionShape2D"],
                response="Loot Area2D emits collected when the Hero enters, then removes itself.",
            ),
            _module_entry(
                "enemy_chase",
                "Enemy Chase and Damage",
                scene_path="scenes/Enemy.tscn",
                script_path="scripts/enemy_chaser.gd",
                role="ai_controller",
                depends_on=["hero_controller"],
                skills=["generate_ai_behavior", "configure_physics_collision", "wire_signal_connection"],
                signals=["body_entered"],
                godot_nodes=["Area2D", "CollisionShape2D"],
                response="Enemy tracks Hero target_path and damages health on body_entered.",
            ),
            _module_entry(
                "dungeon_hud",
                "Dungeon HUD and Health",
                scene_path="scenes/Main.tscn",
                script_path="scripts/hud_controller.gd",
                role="developer",
                depends_on=["loot_loop", "enemy_chase"],
                skills=["auto_layout_ui", "wire_signal_connection", "manage_game_data_tables"],
                signals=["health_changed", "collected", "body_entered", "attacked", "descended"],
                godot_nodes=["CanvasLayer", "Label", "Node", "Stairs"],
                response="HUD updates loot, HP, action feedback, and dungeon depth from room events.",
            ),
            _module_entry(
                "playtest_gate",
                "Playable Smoke Gate",
                scene_path="scenes/Main.tscn",
                script_path="",
                role="tester",
                depends_on=["dungeon_hud"],
                skills=["smoke_test_scene", "audit_logic_errors", "audit_project_consistency"],
                godot_nodes=["Main", "Player", "Pickup", "Enemy", "HUD", "Stairs"],
                response="Scene smoke pass confirms movement, attack, loot collection, enemy damage, descent, HUD, and project resources.",
            ),
        ]
    if template_id == ARPG_TEMPLATE_ID:
        return [
            _module_entry(
                "input_map",
                "Input Map",
                scene_path="project.godot",
                script_path="project.godot",
                role="developer",
                skills=["manage_input_mapping", "plan_game_feature"],
                inputs=["move_left", "move_right", "move_up", "move_down", "attack", "dodge"],
                godot_nodes=["ProjectSettings"],
                response="Godot input actions expose movement, attack, and dodge controls before scripts consume them.",
            ),
            _module_entry(
                "hero_controller",
                "Hero Movement, Attack, and Dodge",
                scene_path="scenes/Player.tscn",
                script_path="scripts/player_controller.gd",
                role="code_generator",
                depends_on=["input_map"],
                skills=["generate_movement_script", "attach_script_to_node", "configure_physics_collision"],
                inputs=["move_left", "move_right", "move_up", "move_down", "attack", "dodge"],
                signals=["attacked", "dodged"],
                godot_nodes=["CharacterBody2D", "AttackArea", "CollisionShape2D"],
                response="Hero moves in four directions, emits attacked on combat input, and emits dodged during dodge rolls.",
            ),
            _module_entry(
                "quest_relic",
                "Quest Relic Collection",
                scene_path="scenes/Pickup.tscn",
                script_path="scripts/relic_collectible.gd",
                role="code_generator",
                depends_on=["hero_controller"],
                skills=["create_godot_scene", "wire_signal_connection", "attach_script_to_node"],
                signals=["collected"],
                godot_nodes=["Area2D", "CollisionShape2D"],
                response="Relic Area2D emits collected when the Hero enters, then removes itself.",
            ),
            _module_entry(
                "enemy_chase",
                "Enemy Chase and Damage",
                scene_path="scenes/Enemy.tscn",
                script_path="scripts/enemy_chaser.gd",
                role="ai_controller",
                depends_on=["hero_controller"],
                skills=["generate_ai_behavior", "configure_physics_collision", "wire_signal_connection"],
                signals=["body_entered"],
                godot_nodes=["Area2D", "CollisionShape2D"],
                response="Enemy tracks Hero target_path and damages health on body_entered.",
            ),
            _module_entry(
                "quest_hud",
                "Quest HUD and Health",
                scene_path="scenes/Main.tscn",
                script_path="scripts/hud_controller.gd",
                role="developer",
                depends_on=["quest_relic", "enemy_chase"],
                skills=["auto_layout_ui", "wire_signal_connection", "manage_game_data_tables"],
                signals=["health_changed", "collected", "body_entered", "attacked", "dodged"],
                godot_nodes=["CanvasLayer", "Label", "Node"],
                response="HUD updates quest progress, HP, and action feedback from combat and relic events.",
            ),
            _module_entry(
                "playtest_gate",
                "Playable Smoke Gate",
                scene_path="scenes/Main.tscn",
                script_path="",
                role="tester",
                depends_on=["quest_hud"],
                skills=["smoke_test_scene", "audit_logic_errors", "audit_project_consistency"],
                godot_nodes=["Main", "Player", "Pickup", "Enemy", "HUD"],
                response="Scene smoke pass confirms movement, attack, dodge, relic collection, enemy damage, HUD, and project resources.",
            ),
        ]
    if template_id == TOWER_DEFENSE_TEMPLATE_ID:
        return [
            _module_entry(
                "input_map",
                "Input Map",
                scene_path="project.godot",
                script_path="project.godot",
                role="developer",
                skills=["manage_input_mapping", "plan_game_feature"],
                inputs=["move_left", "move_right", "move_up", "move_down", "place_tower"],
                godot_nodes=["ProjectSettings"],
                response="Godot input actions expose cursor movement and tower placement controls.",
            ),
            _module_entry(
                "placement_cursor",
                "Placement Cursor",
                scene_path="scenes/Player.tscn",
                script_path="scripts/player_controller.gd",
                role="code_generator",
                depends_on=["input_map"],
                skills=["generate_movement_script", "attach_script_to_node", "configure_physics_collision"],
                inputs=["move_left", "move_right", "move_up", "move_down", "place_tower"],
                signals=["tower_placed"],
                godot_nodes=["CharacterBody2D", "CollisionShape2D"],
                response="Cursor moves on the build grid and emits tower_placed on placement input.",
            ),
            _module_entry(
                "tower_targeting",
                "Tower Targeting",
                scene_path="scenes/Tower.tscn",
                script_path="scripts/tower_controller.gd",
                role="code_generator",
                depends_on=["placement_cursor"],
                skills=["create_godot_scene", "wire_signal_connection", "attach_script_to_node"],
                signals=["fired"],
                godot_nodes=["Area2D", "CollisionShape2D"],
                response="Tower Area2D tracks enemies in range and emits fired when cooldown completes.",
            ),
            _module_entry(
                "enemy_wave",
                "Enemy Wave Runner",
                scene_path="scenes/Enemy.tscn",
                script_path="scripts/enemy_runner.gd",
                role="ai_controller",
                depends_on=["tower_targeting"],
                skills=["generate_ai_behavior", "configure_physics_collision", "wire_signal_connection"],
                signals=["base_reached"],
                godot_nodes=["Area2D", "CollisionShape2D"],
                response="Enemy moves toward the base and emits base_reached when crossing the goal line.",
            ),
            _module_entry(
                "base_hud",
                "Base Health and HUD",
                scene_path="scenes/Main.tscn",
                script_path="scripts/hud_controller.gd",
                role="developer",
                depends_on=["enemy_wave", "placement_cursor"],
                skills=["auto_layout_ui", "wire_signal_connection", "manage_game_data_tables"],
                signals=["health_changed", "base_reached", "tower_placed"],
                godot_nodes=["CanvasLayer", "Label", "Node", "Base"],
                response="HUD updates resources and base HP from placement and enemy reach events.",
            ),
            _module_entry(
                "playtest_gate",
                "Playable Smoke Gate",
                scene_path="scenes/Main.tscn",
                script_path="",
                role="tester",
                depends_on=["base_hud"],
                skills=["smoke_test_scene", "audit_logic_errors", "audit_project_consistency"],
                godot_nodes=["Main", "Player", "Tower", "Enemy", "HUD"],
                response="Scene smoke pass confirms placement input, tower targeting, enemy wave, HUD, and project resources.",
            ),
        ]
    if template_id == TOPDOWN_ACTION_TEMPLATE_ID:
        return [
            _module_entry(
                "input_map",
                "Input Map",
                scene_path="project.godot",
                script_path="project.godot",
                role="developer",
                skills=["manage_input_mapping", "plan_game_feature"],
                inputs=["move_left", "move_right", "move_up", "move_down", "attack"],
                godot_nodes=["ProjectSettings"],
                response="Godot input actions expose movement and attack controls before scripts consume them.",
            ),
            _module_entry(
                "player_controller",
                "Player Movement and Attack",
                scene_path="scenes/Player.tscn",
                script_path="scripts/player_controller.gd",
                role="code_generator",
                depends_on=["input_map"],
                skills=["generate_movement_script", "attach_script_to_node", "configure_physics_collision"],
                inputs=["move_left", "move_right", "move_up", "move_down", "attack"],
                signals=["attacked"],
                godot_nodes=["CharacterBody2D", "AttackArea"],
                response="CharacterBody2D moves in four directions and emits attacked on attack input.",
            ),
            _module_entry(
                "pickup_loop",
                "Pickup Collection",
                scene_path="scenes/Pickup.tscn",
                script_path="scripts/pickup_collectible.gd",
                role="code_generator",
                depends_on=["player_controller"],
                skills=["create_godot_scene", "wire_signal_connection", "attach_script_to_node"],
                signals=["collected"],
                godot_nodes=["Area2D", "CollisionShape2D"],
                response="Area2D emits collected when Player enters, then removes itself.",
            ),
            _module_entry(
                "enemy_chase",
                "Enemy Chase and Damage",
                scene_path="scenes/Enemy.tscn",
                script_path="scripts/enemy_chaser.gd",
                role="ai_controller",
                depends_on=["player_controller"],
                skills=["generate_ai_behavior", "configure_physics_collision", "wire_signal_connection"],
                signals=["body_entered"],
                godot_nodes=["Area2D", "CollisionShape2D"],
                response="Enemy tracks Player target_path and damages health on body_entered.",
            ),
            _module_entry(
                "hud_health",
                "HUD and Health",
                scene_path="scenes/Main.tscn",
                script_path="scripts/hud_controller.gd",
                role="developer",
                depends_on=["pickup_loop", "enemy_chase"],
                skills=["auto_layout_ui", "wire_signal_connection", "manage_game_data_tables"],
                signals=["health_changed", "collected", "body_entered"],
                godot_nodes=["CanvasLayer", "Label", "Node"],
                response="HUD updates score and HP labels when collection or health events fire.",
            ),
            _module_entry(
                "playtest_gate",
                "Playable Smoke Gate",
                scene_path="scenes/Main.tscn",
                script_path="",
                role="tester",
                depends_on=["hud_health"],
                skills=["smoke_test_scene", "audit_logic_errors", "audit_project_consistency"],
                godot_nodes=["Main", "Player", "HUD"],
                response="Scene smoke pass confirms input, collection, enemy damage, HUD, and project resources.",
            ),
        ]
    return [
        _module_entry(
            "input_map",
            "Input Map",
            scene_path="project.godot",
            script_path="project.godot",
            role="developer",
            skills=["manage_input_mapping", "plan_game_feature"],
            inputs=["move_left", "move_right", "jump"],
            godot_nodes=["ProjectSettings"],
            response="Godot input actions expose movement and jump controls before scripts consume them.",
        ),
        _module_entry(
            "player_controller",
            "Player Movement and Jump",
            scene_path="scenes/Player.tscn",
            script_path="scripts/player_controller.gd",
            role="code_generator",
            depends_on=["input_map"],
            skills=["generate_movement_script", "attach_script_to_node", "configure_physics_collision"],
            inputs=["move_left", "move_right", "jump"],
            godot_nodes=["CharacterBody2D", "CollisionShape2D"],
            response="CharacterBody2D applies horizontal velocity, gravity, jump impulse, and move_and_slide.",
        ),
        _module_entry(
            "coin_loop",
            "Coin Collection",
            scene_path="scenes/Coin.tscn",
            script_path="scripts/coin_collectible.gd",
            role="code_generator",
            depends_on=["player_controller"],
            skills=["create_godot_scene", "wire_signal_connection", "attach_script_to_node"],
            signals=["collected"],
            godot_nodes=["Area2D", "CollisionShape2D"],
            response="Area2D emits collected when Player enters, then removes itself.",
        ),
        _module_entry(
            "enemy_patrol",
            "Enemy Patrol and Damage",
            scene_path="scenes/Enemy.tscn",
            script_path="scripts/enemy_patrol.gd",
            role="ai_controller",
            depends_on=["player_controller"],
            skills=["generate_ai_behavior", "configure_physics_collision", "wire_signal_connection"],
            signals=["body_entered"],
            godot_nodes=["Area2D", "CollisionShape2D"],
            response="Enemy patrols between bounds and damages health on body_entered.",
        ),
        _module_entry(
            "hud_health",
            "HUD and Health",
            scene_path="scenes/Main.tscn",
            script_path="scripts/hud_controller.gd",
            role="developer",
            depends_on=["coin_loop", "enemy_patrol"],
            skills=["auto_layout_ui", "wire_signal_connection", "manage_game_data_tables"],
            signals=["health_changed", "collected", "body_entered"],
            godot_nodes=["CanvasLayer", "Label", "Node"],
            response="HUD updates score and HP labels when collection or health events fire.",
        ),
        _module_entry(
            "playtest_gate",
            "Playable Smoke Gate",
            scene_path="scenes/Main.tscn",
            script_path="",
            role="tester",
            depends_on=["hud_health"],
            skills=["smoke_test_scene", "audit_logic_errors", "audit_project_consistency"],
            godot_nodes=["Main", "Player", "HUD"],
            response="Scene smoke pass confirms input, collection, enemy damage, HUD, and project resources.",
        ),
    ]


def _module_entry(
    module_id: str,
    label: str,
    *,
    scene_path: str,
    script_path: str,
    role: str,
    skills: List[str],
    depends_on: List[str] | None = None,
    inputs: List[str] | None = None,
    signals: List[str] | None = None,
    godot_nodes: List[str] | None = None,
    response: str,
) -> Dict[str, Any]:
    return {
        "module_id": module_id,
        "label": label,
        "role": role,
        "scene_path": scene_path,
        "script_path": script_path,
        "depends_on": list(depends_on or []),
        "inputs": list(inputs or []),
        "signals": list(signals or []),
        "godot_nodes": list(godot_nodes or []),
        "skill_bindings": [_skill_binding(module_id, skill_name) for skill_name in skills],
        "constraints": _module_constraints(scene_path, script_path, role),
        "response": response,
    }


def _skill_binding(module_id: str, skill_name: str) -> Dict[str, Any]:
    purpose_by_skill = {
        "plan_game_feature": "define feature contract and acceptance criteria",
        "manage_input_mapping": "create stable Godot InputMap actions",
        "generate_movement_script": "generate movement GDScript that consumes the input contract",
        "attach_script_to_node": "attach generated scripts to the declared scene nodes",
        "configure_physics_collision": "keep physics bodies and collision shapes aligned with gameplay",
        "create_godot_scene": "create a reusable Godot scene with required node hierarchy",
        "wire_signal_connection": "connect Godot signals to the owning controller",
        "generate_ai_behavior": "generate deterministic enemy behavior for the template",
        "auto_layout_ui": "place HUD labels in a readable CanvasLayer layout",
        "manage_game_data_tables": "persist balance values in a structured gameplay table",
        "smoke_test_scene": "validate the playable scene opens and responds",
        "audit_logic_errors": "catch missing signal, node, or script wiring",
        "audit_project_consistency": "check generated resources and manifest consistency",
    }
    return {
        "skill_name": skill_name,
        "module_id": module_id,
        "purpose": purpose_by_skill.get(skill_name, "constrain generated module behavior"),
        "constraints": [
            "must preserve declared scene_path and script_path contract",
            "must report blocking checks instead of silently dropping required Godot nodes",
        ],
    }


def _module_constraints(scene_path: str, script_path: str, role: str) -> List[str]:
    constraints = [
        "scene resources must stay under scenes/ or project.godot",
        "Godot node names referenced by scripts must exist in the generated scene",
        "signals listed by the module must be declared or connected in generated GDScript",
        f"primary execution role is {role}",
    ]
    if script_path and script_path != "project.godot":
        constraints.append("generated scripts must stay under scripts/ unless the module is project.godot")
    if scene_path == "scenes/Main.tscn":
        constraints.append("main-scene modules must wire child modules without duplicating gameplay state")
    return constraints


def _skill_binding_plan(module_plan: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    bindings: List[Dict[str, Any]] = []
    for module in module_plan:
        for binding in list(module.get("skill_bindings") or []):
            bindings.append({
                **binding,
                "role": module.get("role") or "",
                "label": module.get("label") or module.get("module_id") or "",
            })
    return bindings


def _block_diagram(module_plan: List[Dict[str, Any]]) -> str:
    module_ids = {str(module.get("module_id") or "") for module in module_plan}
    labels = {
        str(module.get("module_id") or ""): str(module.get("label") or module.get("module_id") or "")
        for module in module_plan
    }
    lines = ["flowchart LR"]
    for module_id, label in labels.items():
        if module_id:
            lines.append(f"    {_diagram_node(module_id)}[{json.dumps(label)}]")
    for module in module_plan:
        target = str(module.get("module_id") or "")
        if not target:
            continue
        for dependency in list(module.get("depends_on") or []):
            source = str(dependency or "")
            if source in module_ids:
                lines.append(f"    {_diagram_node(source)} --> {_diagram_node(target)}")
    return "\n".join(lines) + "\n"


def _diagram_node(module_id: str) -> str:
    return "".join(ch if ch.isalnum() else "_" for ch in module_id) or "module"


def _godot_response_map(template_id: str) -> List[Dict[str, Any]]:
    if template_id == SURVIVAL_CRAFTING_TEMPLATE_ID:
        return [
            {"trigger": "move input", "node_path": "Main/Player", "script_path": "scripts/player_controller.gd", "response": "update CharacterBody2D velocity and move_and_slide"},
            {"trigger": "gather input", "node_path": "Main/Player", "script_path": "scripts/main_controller.gd", "response": "harvest resource node and increase wood"},
            {"trigger": "craft input", "node_path": "Main/Player", "script_path": "scripts/main_controller.gd", "response": "spend wood and build campfire"},
            {"trigger": "survival tick", "node_path": "Main", "script_path": "scripts/main_controller.gd", "response": "reduce hunger and update HUD"},
        ]
    if template_id == VISUAL_NOVEL_TEMPLATE_ID:
        return [
            {"trigger": "advance_dialogue input", "node_path": "Main/Player", "script_path": "scripts/player_controller.gd", "response": "emit advanced and update dialogue text"},
            {"trigger": "choice_left input", "node_path": "Main/Player", "script_path": "scripts/player_controller.gd", "response": "move choice focus left"},
            {"trigger": "choice_right input", "node_path": "Main/Player", "script_path": "scripts/player_controller.gd", "response": "move choice focus right"},
            {"trigger": "select_choice input", "node_path": "Main/Player", "script_path": "scripts/main_controller.gd", "response": "apply choice affinity and update scene state"},
        ]
    if template_id == ROGUELIKE_TEMPLATE_ID:
        return [
            {"trigger": "move input", "node_path": "Main/Player", "script_path": "scripts/player_controller.gd", "response": "update CharacterBody2D velocity and move_and_slide"},
            {"trigger": "attack input", "node_path": "Main/Player/AttackArea", "script_path": "scripts/player_controller.gd", "response": "emit attacked for combat hooks and HUD feedback"},
            {"trigger": "loot body_entered", "node_path": "Main/Pickup", "script_path": "scripts/loot_collectible.gd", "response": "emit collected and update loot count"},
            {"trigger": "descend input", "node_path": "Main/Player", "script_path": "scripts/player_controller.gd", "response": "emit descended and advance dungeon depth"},
            {"trigger": "enemy body_entered", "node_path": "Main/Enemy", "script_path": "scripts/main_controller.gd", "response": "call Health.damage and update HUD"},
        ]
    if template_id == ARPG_TEMPLATE_ID:
        return [
            {"trigger": "move input", "node_path": "Main/Player", "script_path": "scripts/player_controller.gd", "response": "update CharacterBody2D velocity and move_and_slide"},
            {"trigger": "attack input", "node_path": "Main/Player/AttackArea", "script_path": "scripts/player_controller.gd", "response": "emit attacked for combat hooks and HUD feedback"},
            {"trigger": "dodge input", "node_path": "Main/Player", "script_path": "scripts/player_controller.gd", "response": "emit dodged and briefly increase movement response"},
            {"trigger": "relic body_entered", "node_path": "Main/Pickup", "script_path": "scripts/relic_collectible.gd", "response": "emit collected and update quest progress"},
            {"trigger": "enemy body_entered", "node_path": "Main/Enemy", "script_path": "scripts/main_controller.gd", "response": "call Health.damage and update HUD"},
        ]
    if template_id == TOWER_DEFENSE_TEMPLATE_ID:
        return [
            {"trigger": "move input", "node_path": "Main/Player", "script_path": "scripts/player_controller.gd", "response": "move placement cursor across the build grid"},
            {"trigger": "place_tower input", "node_path": "Main/Player", "script_path": "scripts/player_controller.gd", "response": "emit tower_placed for build economy hooks"},
            {"trigger": "tower cooldown", "node_path": "Main/Tower", "script_path": "scripts/tower_controller.gd", "response": "emit fired when an enemy is in range"},
            {"trigger": "enemy reaches base", "node_path": "Main/Enemy", "script_path": "scripts/main_controller.gd", "response": "damage base health and update HUD"},
        ]
    if template_id == TOPDOWN_ACTION_TEMPLATE_ID:
        return [
            {"trigger": "move input", "node_path": "Main/Player", "script_path": "scripts/player_controller.gd", "response": "update CharacterBody2D velocity and move_and_slide"},
            {"trigger": "attack input", "node_path": "Main/Player/AttackArea", "script_path": "scripts/player_controller.gd", "response": "emit attacked for combat hooks"},
            {"trigger": "pickup body_entered", "node_path": "Main/Pickup", "script_path": "scripts/pickup_collectible.gd", "response": "emit collected and queue_free"},
            {"trigger": "enemy body_entered", "node_path": "Main/Enemy", "script_path": "scripts/main_controller.gd", "response": "call Health.damage and update HUD"},
        ]
    return [
        {"trigger": "move input", "node_path": "Main/Player", "script_path": "scripts/player_controller.gd", "response": "update CharacterBody2D velocity and move_and_slide"},
        {"trigger": "jump input", "node_path": "Main/Player", "script_path": "scripts/player_controller.gd", "response": "apply jump_velocity when on floor"},
        {"trigger": "coin body_entered", "node_path": "Main/Coin", "script_path": "scripts/coin_collectible.gd", "response": "emit collected and queue_free"},
        {"trigger": "enemy body_entered", "node_path": "Main/Enemy", "script_path": "scripts/main_controller.gd", "response": "call Health.damage and update HUD"},
    ]


def _input_replay_plan(template_id: str) -> List[Dict[str, Any]]:
    if template_id == SURVIVAL_CRAFTING_TEMPLATE_ID:
        return [
            {"step_id": "open_main_scene", "action": "open_scene", "target": "res://scenes/Main.tscn", "expect": "Main scene loads"},
            {"step_id": "move_survivor_right", "action": "press", "input": "move_right", "duration_ms": 350, "expect": "Survivor moves right"},
            {"step_id": "gather", "action": "tap", "input": "gather", "expect": "Wood resource increases"},
            {"step_id": "craft", "action": "tap", "input": "craft", "expect": "Campfire built state updates"},
            {"step_id": "capture_golden", "action": "capture_screenshot", "target": "logs/test_artifacts/game_creation/survival_crafting_runtime.png", "expect": "Runtime frame is nonblank"},
        ]
    if template_id == VISUAL_NOVEL_TEMPLATE_ID:
        return [
            {"step_id": "open_main_scene", "action": "open_scene", "target": "res://scenes/Main.tscn", "expect": "Main scene loads"},
            {"step_id": "advance_dialogue", "action": "tap", "input": "advance_dialogue", "expect": "Dialogue line advances"},
            {"step_id": "choice_right", "action": "tap", "input": "choice_right", "expect": "Choice focus moves right"},
            {"step_id": "select_choice", "action": "tap", "input": "select_choice", "expect": "Choice selection updates affinity"},
            {"step_id": "capture_golden", "action": "capture_screenshot", "target": "logs/test_artifacts/game_creation/visual_novel_runtime.png", "expect": "Runtime frame is nonblank"},
        ]
    if template_id == ROGUELIKE_TEMPLATE_ID:
        return [
            {"step_id": "open_main_scene", "action": "open_scene", "target": "res://scenes/Main.tscn", "expect": "Main scene loads"},
            {"step_id": "move_hero_right", "action": "press", "input": "move_right", "duration_ms": 350, "expect": "Hero moves right"},
            {"step_id": "attack", "action": "tap", "input": "attack", "expect": "attacked signal can fire"},
            {"step_id": "descend", "action": "tap", "input": "descend", "expect": "descended signal can fire"},
            {"step_id": "capture_golden", "action": "capture_screenshot", "target": "logs/test_artifacts/game_creation/roguelike_runtime.png", "expect": "Runtime frame is nonblank"},
        ]
    if template_id == ARPG_TEMPLATE_ID:
        return [
            {"step_id": "open_main_scene", "action": "open_scene", "target": "res://scenes/Main.tscn", "expect": "Main scene loads"},
            {"step_id": "move_hero_right", "action": "press", "input": "move_right", "duration_ms": 350, "expect": "Hero moves right"},
            {"step_id": "attack", "action": "tap", "input": "attack", "expect": "attacked signal can fire"},
            {"step_id": "dodge", "action": "tap", "input": "dodge", "expect": "dodged signal can fire"},
            {"step_id": "capture_golden", "action": "capture_screenshot", "target": "logs/test_artifacts/game_creation/arpg_runtime.png", "expect": "Runtime frame is nonblank"},
        ]
    if template_id == TOWER_DEFENSE_TEMPLATE_ID:
        return [
            {"step_id": "open_main_scene", "action": "open_scene", "target": "res://scenes/Main.tscn", "expect": "Main scene loads"},
            {"step_id": "move_cursor_right", "action": "press", "input": "move_right", "duration_ms": 450, "expect": "Placement cursor moves right"},
            {"step_id": "move_cursor_down", "action": "press", "input": "move_down", "duration_ms": 250, "expect": "Placement cursor moves down"},
            {"step_id": "place_tower", "action": "tap", "input": "place_tower", "expect": "tower_placed signal updates resources"},
            {"step_id": "capture_golden", "action": "capture_screenshot", "target": "logs/test_artifacts/game_creation/tower_defense_runtime.png", "expect": "Runtime frame is nonblank"},
        ]
    if template_id == TOPDOWN_ACTION_TEMPLATE_ID:
        return [
            {"step_id": "open_main_scene", "action": "open_scene", "target": "res://scenes/Main.tscn", "expect": "Main scene loads"},
            {"step_id": "move_player_right", "action": "press", "input": "move_right", "duration_ms": 350, "expect": "Player moves right"},
            {"step_id": "attack", "action": "tap", "input": "attack", "expect": "attacked signal can fire"},
            {"step_id": "capture_golden", "action": "capture_screenshot", "target": "logs/test_artifacts/game_creation/topdown_action_runtime.png", "expect": "Runtime frame is nonblank"},
        ]
    return [
        {"step_id": "open_main_scene", "action": "open_scene", "target": "res://scenes/Main.tscn", "expect": "Main scene loads"},
        {"step_id": "move_player_right", "action": "press", "input": "move_right", "duration_ms": 350, "expect": "Player moves right"},
        {"step_id": "jump", "action": "tap", "input": "jump", "expect": "Player jump input is accepted"},
        {"step_id": "capture_golden", "action": "capture_screenshot", "target": "logs/test_artifacts/game_creation/platformer_runtime.png", "expect": "Runtime frame is nonblank"},
    ]


def _golden_screenshot_plan(template_id: str) -> Dict[str, Any]:
    stem_by_template = {
        DEFAULT_GAME_TEMPLATE_ID: "platformer_2d_main",
        TOPDOWN_ACTION_TEMPLATE_ID: "topdown_action_2d_main",
        TOWER_DEFENSE_TEMPLATE_ID: "tower_defense_2d_main",
        ARPG_TEMPLATE_ID: "arpg_2d_main",
        ROGUELIKE_TEMPLATE_ID: "roguelike_2d_main",
        VISUAL_NOVEL_TEMPLATE_ID: "visual_novel_2d_main",
        SURVIVAL_CRAFTING_TEMPLATE_ID: "survival_crafting_2d_main",
    }
    stem = stem_by_template.get(template_id, "game_creation_main")
    return {
        "baseline_path": f"tests/baselines/screenshots/game_creation/{stem}.png",
        "runtime_capture_path": f"logs/test_artifacts/game_creation/{stem}.png",
        "scene_path": "res://scenes/Main.tscn",
        "max_diff_ratio": 0.03,
        "required_nodes": ["Main", "Player", "HUD"],
        "status": "planned",
    }


def _template_migration_policy(template_id: str) -> Dict[str, Any]:
    candidate_targets = [
        item_id for item_id in SUPPORTED_TEMPLATES
        if item_id != template_id
    ]
    return {
        "schema": "game_creation_template_migration_policy",
        "current_template_id": template_id,
        "strategy": "plan_only_overwrite_with_backup",
        "supported_targets": candidate_targets,
        "report_path": DEFAULT_GAME_CREATION_TEMPLATE_MIGRATION_PATH,
        "required_gates": [
            "layout_validation",
            "governance_admission",
            "scene_graph_audit",
            "game_creation_review",
            "input_replay_report",
        ],
        "rollback_required": True,
    }


def _template_migration_steps(source_template: str, target_template: str) -> List[Dict[str, Any]]:
    return [
        {"step_id": "snapshot_source", "action": "backup", "target": DEFAULT_GAME_CREATION_MANIFEST_PATH, "expect": f"source template {source_template or '-'} manifest is preserved"},
        {"step_id": "plan_target", "action": "plan", "target": target_template, "expect": "target template profile, modules, skills, and block diagram are generated"},
        {"step_id": "rewrite_managed_scaffold", "action": "apply", "target": "scenes/, scripts/, data_tables/game_creation/", "expect": "managed scaffold is overwritten only after layout and governance pass"},
        {"step_id": "regenerate_replay", "action": "replay", "target": DEFAULT_GAME_CREATION_INPUT_REPLAY_PATH, "expect": "input replay plan and headless script match target inputs"},
        {"step_id": "acceptance_review", "action": "review", "target": DEFAULT_GAME_CREATION_REVIEW_PATH, "expect": "scene graph audit, data table review, and acceptance criteria pass"},
    ]


def _template_migration_compatibility(
    source_template: str,
    target_template: str,
    source_spec: Dict[str, Any],
    target_spec: Dict[str, Any],
) -> List[Dict[str, Any]]:
    source_inputs = set(_as_key_list(source_spec.get("input_map")))
    target_inputs = set(_as_key_list(target_spec.get("input_map")))
    source_scenes = set(source_spec.get("scene_paths") or [])
    target_scenes = set(target_spec.get("scene_paths") or [])
    return [
        {
            "check_id": "template_ids",
            "status": "passed" if source_template and target_template and source_template != target_template else "warning",
            "message": f"{source_template or '-'} -> {target_template or '-'}",
        },
        {
            "check_id": "input_actions",
            "status": "passed",
            "source_only": sorted(source_inputs - target_inputs),
            "target_only": sorted(target_inputs - source_inputs),
            "shared": sorted(source_inputs & target_inputs),
            "message": "target input map will replace source-only actions during project.godot rewrite",
        },
        {
            "check_id": "scene_paths",
            "status": "passed",
            "source_only": sorted(source_scenes - target_scenes),
            "target_only": sorted(target_scenes - source_scenes),
            "shared": sorted(source_scenes & target_scenes),
            "message": "shared scene paths are overwritten by managed scaffold; source-only files require backup if retained",
        },
        {
            "check_id": "data_tables",
            "status": "passed",
            "message": "gameplay.json and input_replay.json are regenerated for the target template schema",
        },
    ]


def _template_migration_file_operations(
    source_template: str,
    target_template: str,
    source_spec: Dict[str, Any],
    target_spec: Dict[str, Any],
) -> List[Dict[str, Any]]:
    source_files = set(source_spec.get("scene_paths") or [])
    target_files = set(target_spec.get("scene_paths") or [])
    if source_spec:
        source_files.update([
            "scripts/main_controller.gd",
            "scripts/player_controller.gd",
            str(source_spec.get("pickup_script") or ""),
            str(source_spec.get("enemy_script") or ""),
            "scripts/health_system.gd",
            "scripts/hud_controller.gd",
        ])
    if target_spec:
        target_files.update([
            "scripts/main_controller.gd",
            "scripts/player_controller.gd",
            str(target_spec.get("pickup_script") or ""),
            str(target_spec.get("enemy_script") or ""),
            "scripts/health_system.gd",
            "scripts/hud_controller.gd",
        ])
    target_files.update(["project.godot", "data_tables/game_creation/gameplay.json", DEFAULT_GAME_CREATION_INPUT_REPLAY_PATH, DEFAULT_GAME_CREATION_MANIFEST_PATH])
    operations: List[Dict[str, Any]] = []
    for path in sorted(path for path in target_files if path):
        operations.append({
            "path": path,
            "operation": "overwrite" if path in source_files or path in {"project.godot", DEFAULT_GAME_CREATION_MANIFEST_PATH} else "create",
            "reason": f"target template {target_template} managed output",
        })
    for path in sorted(path for path in source_files - target_files if path):
        operations.append({
            "path": path,
            "operation": "backup_or_remove",
            "reason": f"source template {source_template} file is not used by target template {target_template}",
        })
    return operations


def _template_migration_data_migrations(
    source_template: str,
    target_template: str,
    source_spec: Dict[str, Any],
    target_spec: Dict[str, Any],
) -> List[Dict[str, Any]]:
    return [
        {
            "path": "data_tables/game_creation/gameplay.json",
            "operation": "regenerate",
            "from_required_sections": _required_gameplay_sections(source_template) if source_template in SUPPORTED_TEMPLATES else [],
            "to_required_sections": _required_gameplay_sections(target_template) if target_template in SUPPORTED_TEMPLATES else [],
        },
        {
            "path": DEFAULT_GAME_CREATION_INPUT_REPLAY_PATH,
            "operation": "regenerate",
            "from_inputs": _as_key_list(source_spec.get("input_map")),
            "to_inputs": _as_key_list(target_spec.get("input_map")),
        },
    ]


def _as_key_list(value: Any) -> List[str]:
    if isinstance(value, dict):
        return sorted(str(key) for key in value.keys())
    return []


def _input_replay_artifact(plan: Dict[str, Any]) -> Dict[str, Any]:
    template_id = str(plan.get("template_id") or DEFAULT_GAME_TEMPLATE_ID)
    return {
        "schema": "game_creation_input_replay",
        "template_id": template_id,
        "scene_path": "res://scenes/Main.tscn",
        "steps": list(plan.get("input_replay_plan") or _input_replay_plan(template_id)),
        "golden_screenshot_plan": dict(plan.get("golden_screenshot_plan") or _golden_screenshot_plan(template_id)),
    }


def _clean_list(value: Any) -> List[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def _slug(value: str) -> str:
    slug = "".join(ch.lower() if ch.isalnum() else "_" for ch in str(value or "").strip())
    return "_".join(part for part in slug.split("_") if part) or "platformer_prototype"


def _scene_plan(scene_paths: List[str], roles: List[str]) -> List[Dict[str, str]]:
    return [{"path": path, "role": role} for path, role in zip(scene_paths, roles)]


def _write_text(
    path: Path,
    content: str,
    relative_path: str,
    overwrite: bool,
    generated: List[str],
    skipped: List[str],
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and not overwrite:
        skipped.append(relative_path)
        return
    path.write_text(content, encoding="utf-8")
    generated.append(relative_path)


def _scaffold_files(title: str, template_id: str) -> Dict[str, str]:
    if template_id == SURVIVAL_CRAFTING_TEMPLATE_ID:
        return _survival_crafting_scaffold_files(title)
    if template_id == VISUAL_NOVEL_TEMPLATE_ID:
        return _visual_novel_scaffold_files(title)
    if template_id == ROGUELIKE_TEMPLATE_ID:
        return _roguelike_scaffold_files(title)
    if template_id == ARPG_TEMPLATE_ID:
        return _arpg_scaffold_files(title)
    if template_id == TOWER_DEFENSE_TEMPLATE_ID:
        return _tower_defense_scaffold_files(title)
    if template_id == TOPDOWN_ACTION_TEMPLATE_ID:
        return _topdown_scaffold_files(title)
    return {
        "project.godot": _project_file(title, DEFAULT_GAME_TEMPLATE_ID),
        "scenes/Main.tscn": _main_scene(),
        "scenes/Player.tscn": _player_scene(),
        "scenes/Coin.tscn": _script_scene("Coin", "Area2D", "res://scripts/coin_collectible.gd", "coin"),
        "scenes/Enemy.tscn": _script_scene("Enemy", "Area2D", "res://scripts/enemy_patrol.gd", "enemy"),
        "scripts/main_controller.gd": _main_script(),
        "scripts/player_controller.gd": _player_script(),
        "scripts/coin_collectible.gd": _coin_script(),
        "scripts/enemy_patrol.gd": _enemy_script(),
        "scripts/health_system.gd": _health_script(),
        "scripts/hud_controller.gd": _hud_script(),
        "data_tables/game_creation/gameplay.json": json.dumps(_gameplay_table(), indent=2) + "\n",
    }


def _topdown_scaffold_files(title: str) -> Dict[str, str]:
    return {
        "project.godot": _project_file(title, TOPDOWN_ACTION_TEMPLATE_ID),
        "scenes/Main.tscn": _topdown_main_scene(),
        "scenes/Player.tscn": _topdown_player_scene(),
        "scenes/Pickup.tscn": _script_scene("Pickup", "Area2D", "res://scripts/pickup_collectible.gd", "coin"),
        "scenes/Enemy.tscn": _script_scene("Enemy", "Area2D", "res://scripts/enemy_chaser.gd", "enemy"),
        "scripts/main_controller.gd": _topdown_main_script(),
        "scripts/player_controller.gd": _topdown_player_script(),
        "scripts/pickup_collectible.gd": _coin_script(),
        "scripts/enemy_chaser.gd": _topdown_enemy_script(),
        "scripts/health_system.gd": _health_script(),
        "scripts/hud_controller.gd": _hud_script(),
        "data_tables/game_creation/gameplay.json": json.dumps(_topdown_gameplay_table(), indent=2) + "\n",
    }


def _tower_defense_scaffold_files(title: str) -> Dict[str, str]:
    return {
        "project.godot": _project_file(title, TOWER_DEFENSE_TEMPLATE_ID),
        "scenes/Main.tscn": _tower_defense_main_scene(),
        "scenes/Player.tscn": _tower_defense_player_scene(),
        "scenes/Tower.tscn": _script_scene("Tower", "Area2D", "res://scripts/tower_controller.gd", "tower"),
        "scenes/Enemy.tscn": _script_scene("Enemy", "Area2D", "res://scripts/enemy_runner.gd", "enemy"),
        "scripts/main_controller.gd": _tower_defense_main_script(),
        "scripts/player_controller.gd": _tower_defense_player_script(),
        "scripts/tower_controller.gd": _tower_script(),
        "scripts/enemy_runner.gd": _tower_defense_enemy_script(),
        "scripts/health_system.gd": _health_script(),
        "scripts/hud_controller.gd": _tower_defense_hud_script(),
        "data_tables/game_creation/gameplay.json": json.dumps(_tower_defense_gameplay_table(), indent=2) + "\n",
    }


def _arpg_scaffold_files(title: str) -> Dict[str, str]:
    return {
        "project.godot": _project_file(title, ARPG_TEMPLATE_ID),
        "scenes/Main.tscn": _arpg_main_scene(),
        "scenes/Player.tscn": _arpg_player_scene(),
        "scenes/Pickup.tscn": _script_scene("Pickup", "Area2D", "res://scripts/relic_collectible.gd", "coin"),
        "scenes/Enemy.tscn": _script_scene("Enemy", "Area2D", "res://scripts/enemy_chaser.gd", "enemy"),
        "scripts/main_controller.gd": _arpg_main_script(),
        "scripts/player_controller.gd": _arpg_player_script(),
        "scripts/relic_collectible.gd": _relic_script(),
        "scripts/enemy_chaser.gd": _topdown_enemy_script(),
        "scripts/health_system.gd": _health_script(),
        "scripts/hud_controller.gd": _arpg_hud_script(),
        "data_tables/game_creation/gameplay.json": json.dumps(_arpg_gameplay_table(), indent=2) + "\n",
    }


def _roguelike_scaffold_files(title: str) -> Dict[str, str]:
    return {
        "project.godot": _project_file(title, ROGUELIKE_TEMPLATE_ID),
        "scenes/Main.tscn": _roguelike_main_scene(),
        "scenes/Player.tscn": _roguelike_player_scene(),
        "scenes/Pickup.tscn": _script_scene("Pickup", "Area2D", "res://scripts/loot_collectible.gd", "coin"),
        "scenes/Enemy.tscn": _script_scene("Enemy", "Area2D", "res://scripts/enemy_chaser.gd", "enemy"),
        "scripts/main_controller.gd": _roguelike_main_script(),
        "scripts/player_controller.gd": _roguelike_player_script(),
        "scripts/loot_collectible.gd": _loot_script(),
        "scripts/enemy_chaser.gd": _topdown_enemy_script(),
        "scripts/health_system.gd": _health_script(),
        "scripts/hud_controller.gd": _roguelike_hud_script(),
        "data_tables/game_creation/gameplay.json": json.dumps(_roguelike_gameplay_table(), indent=2) + "\n",
    }


def _visual_novel_scaffold_files(title: str) -> Dict[str, str]:
    return {
        "project.godot": _project_file(title, VISUAL_NOVEL_TEMPLATE_ID),
        "scenes/Main.tscn": _visual_novel_main_scene(),
        "scenes/Player.tscn": _visual_novel_player_scene(),
        "scenes/Choice.tscn": _visual_novel_choice_scene(),
        "scenes/Npc.tscn": _visual_novel_npc_scene(),
        "scripts/main_controller.gd": _visual_novel_main_script(),
        "scripts/player_controller.gd": _visual_novel_player_script(),
        "scripts/choice_option.gd": _choice_option_script(),
        "scripts/npc_portrait.gd": _npc_portrait_script(),
        "scripts/health_system.gd": _health_script(),
        "scripts/hud_controller.gd": _visual_novel_hud_script(),
        "data_tables/game_creation/gameplay.json": json.dumps(_visual_novel_gameplay_table(), indent=2) + "\n",
    }


def _survival_crafting_scaffold_files(title: str) -> Dict[str, str]:
    return {
        "project.godot": _project_file(title, SURVIVAL_CRAFTING_TEMPLATE_ID),
        "scenes/Main.tscn": _survival_crafting_main_scene(),
        "scenes/Player.tscn": _survival_crafting_player_scene(),
        "scenes/Resource.tscn": _script_scene("Resource", "Area2D", "res://scripts/resource_node.gd", "coin"),
        "scenes/Campfire.tscn": _survival_crafting_campfire_scene(),
        "scripts/main_controller.gd": _survival_crafting_main_script(),
        "scripts/player_controller.gd": _survival_crafting_player_script(),
        "scripts/resource_node.gd": _resource_node_script(),
        "scripts/campfire_controller.gd": _campfire_script(),
        "scripts/health_system.gd": _health_script(),
        "scripts/hud_controller.gd": _survival_crafting_hud_script(),
        "data_tables/game_creation/gameplay.json": json.dumps(_survival_crafting_gameplay_table(), indent=2) + "\n",
    }


def _project_file(title: str, template_id: str) -> str:
    input_block = """move_left={"deadzone":0.5,"events":[Object(InputEventKey,"physical_keycode":65),Object(InputEventKey,"physical_keycode":4194319)]}
move_right={"deadzone":0.5,"events":[Object(InputEventKey,"physical_keycode":68),Object(InputEventKey,"physical_keycode":4194321)]}
jump={"deadzone":0.5,"events":[Object(InputEventKey,"physical_keycode":32),Object(InputEventKey,"physical_keycode":87),Object(InputEventKey,"physical_keycode":4194320)]}"""
    if template_id == TOPDOWN_ACTION_TEMPLATE_ID:
        input_block = """move_left={"deadzone":0.5,"events":[Object(InputEventKey,"physical_keycode":65),Object(InputEventKey,"physical_keycode":4194319)]}
move_right={"deadzone":0.5,"events":[Object(InputEventKey,"physical_keycode":68),Object(InputEventKey,"physical_keycode":4194321)]}
move_up={"deadzone":0.5,"events":[Object(InputEventKey,"physical_keycode":87),Object(InputEventKey,"physical_keycode":4194320)]}
move_down={"deadzone":0.5,"events":[Object(InputEventKey,"physical_keycode":83),Object(InputEventKey,"physical_keycode":4194322)]}
attack={"deadzone":0.5,"events":[Object(InputEventKey,"physical_keycode":32),Object(InputEventKey,"physical_keycode":74)]}"""
    if template_id == TOWER_DEFENSE_TEMPLATE_ID:
        input_block = """move_left={"deadzone":0.5,"events":[Object(InputEventKey,"physical_keycode":65),Object(InputEventKey,"physical_keycode":4194319)]}
move_right={"deadzone":0.5,"events":[Object(InputEventKey,"physical_keycode":68),Object(InputEventKey,"physical_keycode":4194321)]}
move_up={"deadzone":0.5,"events":[Object(InputEventKey,"physical_keycode":87),Object(InputEventKey,"physical_keycode":4194320)]}
move_down={"deadzone":0.5,"events":[Object(InputEventKey,"physical_keycode":83),Object(InputEventKey,"physical_keycode":4194322)]}
place_tower={"deadzone":0.5,"events":[Object(InputEventKey,"physical_keycode":32),Object(InputEventKey,"physical_keycode":74)]}"""
    if template_id == ARPG_TEMPLATE_ID:
        input_block = """move_left={"deadzone":0.5,"events":[Object(InputEventKey,"physical_keycode":65),Object(InputEventKey,"physical_keycode":4194319)]}
move_right={"deadzone":0.5,"events":[Object(InputEventKey,"physical_keycode":68),Object(InputEventKey,"physical_keycode":4194321)]}
move_up={"deadzone":0.5,"events":[Object(InputEventKey,"physical_keycode":87),Object(InputEventKey,"physical_keycode":4194320)]}
move_down={"deadzone":0.5,"events":[Object(InputEventKey,"physical_keycode":83),Object(InputEventKey,"physical_keycode":4194322)]}
attack={"deadzone":0.5,"events":[Object(InputEventKey,"physical_keycode":32),Object(InputEventKey,"physical_keycode":74)]}
dodge={"deadzone":0.5,"events":[Object(InputEventKey,"physical_keycode":4194325),Object(InputEventKey,"physical_keycode":75)]}"""
    if template_id == ROGUELIKE_TEMPLATE_ID:
        input_block = """move_left={"deadzone":0.5,"events":[Object(InputEventKey,"physical_keycode":65),Object(InputEventKey,"physical_keycode":4194319)]}
move_right={"deadzone":0.5,"events":[Object(InputEventKey,"physical_keycode":68),Object(InputEventKey,"physical_keycode":4194321)]}
move_up={"deadzone":0.5,"events":[Object(InputEventKey,"physical_keycode":87),Object(InputEventKey,"physical_keycode":4194320)]}
move_down={"deadzone":0.5,"events":[Object(InputEventKey,"physical_keycode":83),Object(InputEventKey,"physical_keycode":4194322)]}
attack={"deadzone":0.5,"events":[Object(InputEventKey,"physical_keycode":32),Object(InputEventKey,"physical_keycode":74)]}
descend={"deadzone":0.5,"events":[Object(InputEventKey,"physical_keycode":69),Object(InputEventKey,"physical_keycode":4194309)]}"""
    if template_id == VISUAL_NOVEL_TEMPLATE_ID:
        input_block = """advance_dialogue={"deadzone":0.5,"events":[Object(InputEventKey,"physical_keycode":32),Object(InputEventKey,"physical_keycode":4194309)]}
choice_left={"deadzone":0.5,"events":[Object(InputEventKey,"physical_keycode":65),Object(InputEventKey,"physical_keycode":4194319)]}
choice_right={"deadzone":0.5,"events":[Object(InputEventKey,"physical_keycode":68),Object(InputEventKey,"physical_keycode":4194321)]}
select_choice={"deadzone":0.5,"events":[Object(InputEventKey,"physical_keycode":74),Object(InputEventKey,"physical_keycode":4194309)]}"""
    if template_id == SURVIVAL_CRAFTING_TEMPLATE_ID:
        input_block = """move_left={"deadzone":0.5,"events":[Object(InputEventKey,"physical_keycode":65),Object(InputEventKey,"physical_keycode":4194319)]}
move_right={"deadzone":0.5,"events":[Object(InputEventKey,"physical_keycode":68),Object(InputEventKey,"physical_keycode":4194321)]}
move_up={"deadzone":0.5,"events":[Object(InputEventKey,"physical_keycode":87),Object(InputEventKey,"physical_keycode":4194320)]}
move_down={"deadzone":0.5,"events":[Object(InputEventKey,"physical_keycode":83),Object(InputEventKey,"physical_keycode":4194322)]}
gather={"deadzone":0.5,"events":[Object(InputEventKey,"physical_keycode":74),Object(InputEventKey,"physical_keycode":32)]}
craft={"deadzone":0.5,"events":[Object(InputEventKey,"physical_keycode":75),Object(InputEventKey,"physical_keycode":69)]}"""
    return f"""; Engine configuration file.

config_version=5

[application]
config/name="{title}"
run/main_scene="res://scenes/Main.tscn"

[input]
{input_block}
"""


def _main_scene() -> str:
    return """[gd_scene load_steps=8 format=3]

[ext_resource type="PackedScene" path="res://scenes/Player.tscn" id="1_player"]
[ext_resource type="PackedScene" path="res://scenes/Coin.tscn" id="2_coin"]
[ext_resource type="PackedScene" path="res://scenes/Enemy.tscn" id="3_enemy"]
[ext_resource type="Script" path="res://scripts/main_controller.gd" id="4_main_script"]
[ext_resource type="Script" path="res://scripts/health_system.gd" id="5_health_script"]
[ext_resource type="Script" path="res://scripts/hud_controller.gd" id="6_hud_script"]
[sub_resource type="RectangleShape2D" id="RectangleShape2D_ground"]
size = Vector2(960, 32)

[node name="Main" type="Node2D"]
script = ExtResource("4_main_script")

[node name="Ground" type="StaticBody2D" parent="."]
position = Vector2(480, 384)

[node name="CollisionShape2D" type="CollisionShape2D" parent="Ground"]
shape = SubResource("RectangleShape2D_ground")

[node name="GroundVisual" type="Polygon2D" parent="Ground"]
color = Color(0.25, 0.35, 0.28, 1)
polygon = PackedVector2Array(-480, -16, 480, -16, 480, 16, -480, 16)

[node name="Player" parent="." instance=ExtResource("1_player")]
position = Vector2(96, 336)

[node name="Coin" parent="." instance=ExtResource("2_coin")]
position = Vector2(320, 288)

[node name="Enemy" parent="." instance=ExtResource("3_enemy")]
position = Vector2(512, 336)

[node name="Health" type="Node" parent="."]
script = ExtResource("5_health_script")

[node name="HUD" type="CanvasLayer" parent="."]
script = ExtResource("6_hud_script")

[node name="ScoreLabel" type="Label" parent="HUD"]
offset_left = 16.0
offset_top = 12.0
offset_right = 180.0
offset_bottom = 38.0
text = "Score: 0"

[node name="HealthLabel" type="Label" parent="HUD"]
offset_left = 16.0
offset_top = 40.0
offset_right = 180.0
offset_bottom = 66.0
text = "HP: 3"

[node name="Camera2D" type="Camera2D" parent="."]
position = Vector2(320, 220)
enabled = true
"""


def _topdown_main_scene() -> str:
    return """[gd_scene load_steps=8 format=3]

[ext_resource type="PackedScene" path="res://scenes/Player.tscn" id="1_player"]
[ext_resource type="PackedScene" path="res://scenes/Pickup.tscn" id="2_pickup"]
[ext_resource type="PackedScene" path="res://scenes/Enemy.tscn" id="3_enemy"]
[ext_resource type="Script" path="res://scripts/main_controller.gd" id="4_main_script"]
[ext_resource type="Script" path="res://scripts/health_system.gd" id="5_health_script"]
[ext_resource type="Script" path="res://scripts/hud_controller.gd" id="6_hud_script"]
[sub_resource type="RectangleShape2D" id="RectangleShape2D_bounds"]
size = Vector2(704, 448)

[node name="Main" type="Node2D"]
script = ExtResource("4_main_script")

[node name="ArenaBounds" type="Area2D" parent="."]
position = Vector2(352, 224)

[node name="CollisionShape2D" type="CollisionShape2D" parent="ArenaBounds"]
shape = SubResource("RectangleShape2D_bounds")

[node name="ArenaVisual" type="Polygon2D" parent="ArenaBounds"]
color = Color(0.16, 0.2, 0.18, 1)
polygon = PackedVector2Array(-352, -224, 352, -224, 352, 224, -352, 224)

[node name="Player" parent="." instance=ExtResource("1_player")]
position = Vector2(160, 224)

[node name="Pickup" parent="." instance=ExtResource("2_pickup")]
position = Vector2(360, 180)

[node name="Enemy" parent="." instance=ExtResource("3_enemy")]
position = Vector2(560, 260)

[node name="Health" type="Node" parent="."]
script = ExtResource("5_health_script")

[node name="HUD" type="CanvasLayer" parent="."]
script = ExtResource("6_hud_script")

[node name="ScoreLabel" type="Label" parent="HUD"]
offset_left = 16.0
offset_top = 12.0
offset_right = 180.0
offset_bottom = 38.0
text = "Score: 0"

[node name="HealthLabel" type="Label" parent="HUD"]
offset_left = 16.0
offset_top = 40.0
offset_right = 180.0
offset_bottom = 66.0
text = "HP: 3"

[node name="Camera2D" type="Camera2D" parent="."]
position = Vector2(352, 224)
enabled = true
"""


def _arpg_main_scene() -> str:
    return """[gd_scene load_steps=8 format=3]

[ext_resource type="PackedScene" path="res://scenes/Player.tscn" id="1_player"]
[ext_resource type="PackedScene" path="res://scenes/Pickup.tscn" id="2_pickup"]
[ext_resource type="PackedScene" path="res://scenes/Enemy.tscn" id="3_enemy"]
[ext_resource type="Script" path="res://scripts/main_controller.gd" id="4_main_script"]
[ext_resource type="Script" path="res://scripts/health_system.gd" id="5_health_script"]
[ext_resource type="Script" path="res://scripts/hud_controller.gd" id="6_hud_script"]
[sub_resource type="RectangleShape2D" id="RectangleShape2D_bounds"]
size = Vector2(768, 480)

[node name="Main" type="Node2D"]
script = ExtResource("4_main_script")

[node name="QuestArena" type="Area2D" parent="."]
position = Vector2(384, 240)

[node name="CollisionShape2D" type="CollisionShape2D" parent="QuestArena"]
shape = SubResource("RectangleShape2D_bounds")

[node name="ArenaVisual" type="Polygon2D" parent="QuestArena"]
color = Color(0.14, 0.21, 0.18, 1)
polygon = PackedVector2Array(-384, -240, 384, -240, 384, 240, -384, 240)

[node name="Player" parent="." instance=ExtResource("1_player")]
position = Vector2(160, 240)

[node name="Pickup" parent="." instance=ExtResource("2_pickup")]
position = Vector2(430, 190)

[node name="Enemy" parent="." instance=ExtResource("3_enemy")]
position = Vector2(620, 300)

[node name="Health" type="Node" parent="."]
script = ExtResource("5_health_script")

[node name="HUD" type="CanvasLayer" parent="."]
script = ExtResource("6_hud_script")

[node name="QuestLabel" type="Label" parent="HUD"]
offset_left = 16.0
offset_top = 12.0
offset_right = 260.0
offset_bottom = 38.0
text = "Quest: Find relic"

[node name="HealthLabel" type="Label" parent="HUD"]
offset_left = 16.0
offset_top = 40.0
offset_right = 260.0
offset_bottom = 66.0
text = "HP: 3"

[node name="ActionLabel" type="Label" parent="HUD"]
offset_left = 16.0
offset_top = 68.0
offset_right = 260.0
offset_bottom = 94.0
text = "Action: Ready"

[node name="Camera2D" type="Camera2D" parent="."]
position = Vector2(384, 240)
enabled = true
"""


def _roguelike_main_scene() -> str:
    return """[gd_scene load_steps=9 format=3]

[ext_resource type="PackedScene" path="res://scenes/Player.tscn" id="1_player"]
[ext_resource type="PackedScene" path="res://scenes/Pickup.tscn" id="2_pickup"]
[ext_resource type="PackedScene" path="res://scenes/Enemy.tscn" id="3_enemy"]
[ext_resource type="Script" path="res://scripts/main_controller.gd" id="4_main_script"]
[ext_resource type="Script" path="res://scripts/health_system.gd" id="5_health_script"]
[ext_resource type="Script" path="res://scripts/hud_controller.gd" id="6_hud_script"]
[sub_resource type="RectangleShape2D" id="RectangleShape2D_room"]
size = Vector2(736, 448)
[sub_resource type="RectangleShape2D" id="RectangleShape2D_stairs"]
size = Vector2(38, 38)

[node name="Main" type="Node2D"]
script = ExtResource("4_main_script")

[node name="DungeonRoom" type="Area2D" parent="."]
position = Vector2(384, 240)

[node name="CollisionShape2D" type="CollisionShape2D" parent="DungeonRoom"]
shape = SubResource("RectangleShape2D_room")

[node name="RoomVisual" type="Polygon2D" parent="DungeonRoom"]
color = Color(0.13, 0.16, 0.18, 1)
polygon = PackedVector2Array(-368, -224, 368, -224, 368, 224, -368, 224)

[node name="Stairs" type="Area2D" parent="."]
position = Vector2(650, 150)

[node name="CollisionShape2D" type="CollisionShape2D" parent="Stairs"]
shape = SubResource("RectangleShape2D_stairs")

[node name="StairsVisual" type="Polygon2D" parent="Stairs"]
color = Color(0.42, 0.35, 0.2, 1)
polygon = PackedVector2Array(-19, -19, 19, -19, 19, 19, -19, 19)

[node name="Player" parent="." instance=ExtResource("1_player")]
position = Vector2(150, 250)

[node name="Pickup" parent="." instance=ExtResource("2_pickup")]
position = Vector2(390, 220)

[node name="Enemy" parent="." instance=ExtResource("3_enemy")]
position = Vector2(580, 300)

[node name="Health" type="Node" parent="."]
script = ExtResource("5_health_script")

[node name="HUD" type="CanvasLayer" parent="."]
script = ExtResource("6_hud_script")

[node name="LootLabel" type="Label" parent="HUD"]
offset_left = 16.0
offset_top = 12.0
offset_right = 250.0
offset_bottom = 38.0
text = "Loot: 0"

[node name="DepthLabel" type="Label" parent="HUD"]
offset_left = 16.0
offset_top = 40.0
offset_right = 250.0
offset_bottom = 66.0
text = "Depth: 1"

[node name="HealthLabel" type="Label" parent="HUD"]
offset_left = 16.0
offset_top = 68.0
offset_right = 250.0
offset_bottom = 94.0
text = "HP: 3"

[node name="ActionLabel" type="Label" parent="HUD"]
offset_left = 16.0
offset_top = 96.0
offset_right = 250.0
offset_bottom = 122.0
text = "Action: Ready"

[node name="Camera2D" type="Camera2D" parent="."]
position = Vector2(384, 240)
enabled = true
"""


def _visual_novel_main_scene() -> str:
    return """[gd_scene load_steps=8 format=3]

[ext_resource type="PackedScene" path="res://scenes/Player.tscn" id="1_player"]
[ext_resource type="PackedScene" path="res://scenes/Choice.tscn" id="2_choice"]
[ext_resource type="PackedScene" path="res://scenes/Npc.tscn" id="3_npc"]
[ext_resource type="Script" path="res://scripts/main_controller.gd" id="4_main_script"]
[ext_resource type="Script" path="res://scripts/health_system.gd" id="5_health_script"]
[ext_resource type="Script" path="res://scripts/hud_controller.gd" id="6_hud_script"]
[sub_resource type="RectangleShape2D" id="RectangleShape2D_stage"]
size = Vector2(760, 420)

[node name="Main" type="Node2D"]
script = ExtResource("4_main_script")

[node name="Stage" type="Area2D" parent="."]
position = Vector2(384, 230)

[node name="CollisionShape2D" type="CollisionShape2D" parent="Stage"]
shape = SubResource("RectangleShape2D_stage")

[node name="StageVisual" type="Polygon2D" parent="Stage"]
color = Color(0.16, 0.17, 0.22, 1)
polygon = PackedVector2Array(-380, -210, 380, -210, 380, 210, -380, 210)

[node name="Player" parent="." instance=ExtResource("1_player")]
position = Vector2(60, 60)

[node name="Choice" parent="." instance=ExtResource("2_choice")]
position = Vector2(384, 365)

[node name="Npc" parent="." instance=ExtResource("3_npc")]
position = Vector2(560, 210)

[node name="Health" type="Node" parent="."]
script = ExtResource("5_health_script")

[node name="HUD" type="CanvasLayer" parent="."]
script = ExtResource("6_hud_script")

[node name="Panel" type="Panel" parent="HUD"]
offset_left = 16.0
offset_top = 292.0
offset_right = 744.0
offset_bottom = 450.0

[node name="SpeakerLabel" type="Label" parent="HUD"]
offset_left = 24.0
offset_top = 300.0
offset_right = 280.0
offset_bottom = 326.0
text = "Mira"

[node name="DialogueLabel" type="Label" parent="HUD"]
offset_left = 24.0
offset_top = 328.0
offset_right = 730.0
offset_bottom = 382.0
text = "The old gate is still open."

[node name="ChoiceLabel" type="Label" parent="HUD"]
offset_left = 24.0
offset_top = 386.0
offset_right = 730.0
offset_bottom = 414.0
text = "> Enter  |  Wait"

[node name="AffinityLabel" type="Label" parent="HUD"]
offset_left = 24.0
offset_top = 418.0
offset_right = 260.0
offset_bottom = 444.0
text = "Affinity: 0"

[node name="Camera2D" type="Camera2D" parent="."]
position = Vector2(384, 240)
enabled = true
"""


def _survival_crafting_main_scene() -> str:
    return """[gd_scene load_steps=8 format=3]

[ext_resource type="PackedScene" path="res://scenes/Player.tscn" id="1_player"]
[ext_resource type="PackedScene" path="res://scenes/Resource.tscn" id="2_resource"]
[ext_resource type="PackedScene" path="res://scenes/Campfire.tscn" id="3_campfire"]
[ext_resource type="Script" path="res://scripts/main_controller.gd" id="4_main_script"]
[ext_resource type="Script" path="res://scripts/health_system.gd" id="5_health_script"]
[ext_resource type="Script" path="res://scripts/hud_controller.gd" id="6_hud_script"]
[sub_resource type="RectangleShape2D" id="RectangleShape2D_field"]
size = Vector2(760, 460)

[node name="Main" type="Node2D"]
script = ExtResource("4_main_script")

[node name="Field" type="Area2D" parent="."]
position = Vector2(384, 240)

[node name="CollisionShape2D" type="CollisionShape2D" parent="Field"]
shape = SubResource("RectangleShape2D_field")

[node name="FieldVisual" type="Polygon2D" parent="Field"]
color = Color(0.13, 0.22, 0.16, 1)
polygon = PackedVector2Array(-380, -230, 380, -230, 380, 230, -380, 230)

[node name="Player" parent="." instance=ExtResource("1_player")]
position = Vector2(150, 250)

[node name="Resource" parent="." instance=ExtResource("2_resource")]
position = Vector2(380, 210)

[node name="Campfire" parent="." instance=ExtResource("3_campfire")]
position = Vector2(560, 290)

[node name="Health" type="Node" parent="."]
script = ExtResource("5_health_script")

[node name="HUD" type="CanvasLayer" parent="."]
script = ExtResource("6_hud_script")

[node name="WoodLabel" type="Label" parent="HUD"]
offset_left = 16.0
offset_top = 12.0
offset_right = 240.0
offset_bottom = 38.0
text = "Wood: 0"

[node name="HungerLabel" type="Label" parent="HUD"]
offset_left = 16.0
offset_top = 40.0
offset_right = 240.0
offset_bottom = 66.0
text = "Hunger: 100"

[node name="HealthLabel" type="Label" parent="HUD"]
offset_left = 16.0
offset_top = 68.0
offset_right = 240.0
offset_bottom = 94.0
text = "HP: 3"

[node name="CampfireLabel" type="Label" parent="HUD"]
offset_left = 16.0
offset_top = 96.0
offset_right = 240.0
offset_bottom = 122.0
text = "Campfire: none"

[node name="Camera2D" type="Camera2D" parent="."]
position = Vector2(384, 240)
enabled = true
"""


def _tower_defense_main_scene() -> str:
    return """[gd_scene load_steps=8 format=3]

[ext_resource type="PackedScene" path="res://scenes/Player.tscn" id="1_player"]
[ext_resource type="PackedScene" path="res://scenes/Tower.tscn" id="2_tower"]
[ext_resource type="PackedScene" path="res://scenes/Enemy.tscn" id="3_enemy"]
[ext_resource type="Script" path="res://scripts/main_controller.gd" id="4_main_script"]
[ext_resource type="Script" path="res://scripts/health_system.gd" id="5_health_script"]
[ext_resource type="Script" path="res://scripts/hud_controller.gd" id="6_hud_script"]
[sub_resource type="RectangleShape2D" id="RectangleShape2D_base"]
size = Vector2(48, 160)

[node name="Main" type="Node2D"]
script = ExtResource("4_main_script")

[node name="DefenseLane" type="Polygon2D" parent="."]
color = Color(0.18, 0.24, 0.2, 1)
polygon = PackedVector2Array(40, 220, 700, 220, 700, 300, 40, 300)

[node name="Base" type="Area2D" parent="."]
position = Vector2(704, 260)

[node name="CollisionShape2D" type="CollisionShape2D" parent="Base"]
shape = SubResource("RectangleShape2D_base")

[node name="BaseVisual" type="Polygon2D" parent="Base"]
color = Color(0.25, 0.45, 0.8, 1)
polygon = PackedVector2Array(-24, -80, 24, -80, 24, 80, -24, 80)

[node name="Player" parent="." instance=ExtResource("1_player")]
position = Vector2(180, 160)

[node name="Tower" parent="." instance=ExtResource("2_tower")]
position = Vector2(340, 190)

[node name="Enemy" parent="." instance=ExtResource("3_enemy")]
position = Vector2(80, 260)

[node name="Health" type="Node" parent="."]
script = ExtResource("5_health_script")

[node name="HUD" type="CanvasLayer" parent="."]
script = ExtResource("6_hud_script")

[node name="ScoreLabel" type="Label" parent="HUD"]
offset_left = 16.0
offset_top = 12.0
offset_right = 220.0
offset_bottom = 38.0
text = "Resources: 5"

[node name="HealthLabel" type="Label" parent="HUD"]
offset_left = 16.0
offset_top = 40.0
offset_right = 220.0
offset_bottom = 66.0
text = "Base HP: 3"

[node name="Camera2D" type="Camera2D" parent="."]
position = Vector2(384, 240)
enabled = true
"""


def _player_scene() -> str:
    return """[gd_scene load_steps=3 format=3]

[ext_resource type="Script" path="res://scripts/player_controller.gd" id="1_player_script"]
[sub_resource type="RectangleShape2D" id="RectangleShape2D_player"]
size = Vector2(32, 48)

[node name="Player" type="CharacterBody2D"]
script = ExtResource("1_player_script")

[node name="CollisionShape2D" type="CollisionShape2D" parent="."]
shape = SubResource("RectangleShape2D_player")

[node name="PlayerVisual" type="Polygon2D" parent="."]
color = Color(0.25, 0.55, 0.95, 1)
polygon = PackedVector2Array(-16, -24, 16, -24, 16, 24, -16, 24)
"""


def _topdown_player_scene() -> str:
    return """[gd_scene load_steps=4 format=3]

[ext_resource type="Script" path="res://scripts/player_controller.gd" id="1_player_script"]
[sub_resource type="CircleShape2D" id="CircleShape2D_player"]
radius = 16.0
[sub_resource type="CircleShape2D" id="CircleShape2D_attack"]
radius = 36.0

[node name="Player" type="CharacterBody2D"]
script = ExtResource("1_player_script")

[node name="CollisionShape2D" type="CollisionShape2D" parent="."]
shape = SubResource("CircleShape2D_player")

[node name="AttackArea" type="Area2D" parent="."]

[node name="CollisionShape2D" type="CollisionShape2D" parent="AttackArea"]
shape = SubResource("CircleShape2D_attack")

[node name="PlayerVisual" type="Polygon2D" parent="."]
color = Color(0.25, 0.55, 0.95, 1)
polygon = PackedVector2Array(0, -18, 16, 12, -16, 12)
"""


def _arpg_player_scene() -> str:
    return """[gd_scene load_steps=4 format=3]

[ext_resource type="Script" path="res://scripts/player_controller.gd" id="1_player_script"]
[sub_resource type="CircleShape2D" id="CircleShape2D_player"]
radius = 16.0
[sub_resource type="CircleShape2D" id="CircleShape2D_attack"]
radius = 42.0

[node name="Player" type="CharacterBody2D"]
script = ExtResource("1_player_script")

[node name="CollisionShape2D" type="CollisionShape2D" parent="."]
shape = SubResource("CircleShape2D_player")

[node name="AttackArea" type="Area2D" parent="."]

[node name="CollisionShape2D" type="CollisionShape2D" parent="AttackArea"]
shape = SubResource("CircleShape2D_attack")

[node name="PlayerVisual" type="Polygon2D" parent="."]
color = Color(0.32, 0.58, 0.92, 1)
polygon = PackedVector2Array(0, -20, 18, 10, 0, 20, -18, 10)
"""


def _roguelike_player_scene() -> str:
    return """[gd_scene load_steps=4 format=3]

[ext_resource type="Script" path="res://scripts/player_controller.gd" id="1_player_script"]
[sub_resource type="CircleShape2D" id="CircleShape2D_player"]
radius = 16.0
[sub_resource type="CircleShape2D" id="CircleShape2D_attack"]
radius = 34.0

[node name="Player" type="CharacterBody2D"]
script = ExtResource("1_player_script")

[node name="CollisionShape2D" type="CollisionShape2D" parent="."]
shape = SubResource("CircleShape2D_player")

[node name="AttackArea" type="Area2D" parent="."]

[node name="CollisionShape2D" type="CollisionShape2D" parent="AttackArea"]
shape = SubResource("CircleShape2D_attack")

[node name="PlayerVisual" type="Polygon2D" parent="."]
color = Color(0.42, 0.68, 0.88, 1)
polygon = PackedVector2Array(0, -18, 16, 12, -16, 12)
"""


def _visual_novel_player_scene() -> str:
    return """[gd_scene load_steps=2 format=3]

[ext_resource type="Script" path="res://scripts/player_controller.gd" id="1_player_script"]

[node name="Player" type="Node2D"]
script = ExtResource("1_player_script")
"""


def _survival_crafting_player_scene() -> str:
    return """[gd_scene load_steps=3 format=3]

[ext_resource type="Script" path="res://scripts/player_controller.gd" id="1_player_script"]
[sub_resource type="CircleShape2D" id="CircleShape2D_player"]
radius = 16.0

[node name="Player" type="CharacterBody2D"]
script = ExtResource("1_player_script")

[node name="CollisionShape2D" type="CollisionShape2D" parent="."]
shape = SubResource("CircleShape2D_player")

[node name="PlayerVisual" type="Polygon2D" parent="."]
color = Color(0.32, 0.6, 0.42, 1)
polygon = PackedVector2Array(0, -18, 16, 12, -16, 12)
"""


def _tower_defense_player_scene() -> str:
    return """[gd_scene load_steps=3 format=3]

[ext_resource type="Script" path="res://scripts/player_controller.gd" id="1_player_script"]
[sub_resource type="RectangleShape2D" id="RectangleShape2D_cursor"]
size = Vector2(28, 28)

[node name="Player" type="CharacterBody2D"]
script = ExtResource("1_player_script")

[node name="CollisionShape2D" type="CollisionShape2D" parent="."]
shape = SubResource("RectangleShape2D_cursor")

[node name="CursorVisual" type="Polygon2D" parent="."]
color = Color(0.3, 0.75, 0.95, 0.75)
polygon = PackedVector2Array(-14, -14, 14, -14, 14, 14, -14, 14)
"""


def _script_scene(name: str, node_type: str, script_path: str, visual_kind: str) -> str:
    color_by_kind = {
        "coin": "Color(1, 0.82, 0.18, 1)",
        "tower": "Color(0.3, 0.65, 0.95, 1)",
        "enemy": "Color(0.9, 0.2, 0.2, 1)",
    }
    color = color_by_kind.get(visual_kind, "Color(0.9, 0.2, 0.2, 1)")
    return f"""[gd_scene load_steps=3 format=3]

[ext_resource type="Script" path="{script_path}" id="1_script"]
[sub_resource type="CircleShape2D" id="CircleShape2D_body"]
radius = 12.0

[node name="{name}" type="{node_type}"]
script = ExtResource("1_script")

[node name="CollisionShape2D" type="CollisionShape2D" parent="."]
shape = SubResource("CircleShape2D_body")

[node name="{name}Visual" type="Polygon2D" parent="."]
color = {color}
polygon = PackedVector2Array(0, -14, 12, 0, 0, 14, -12, 0)
"""


def _visual_novel_choice_scene() -> str:
    return """[gd_scene load_steps=3 format=3]

[ext_resource type="Script" path="res://scripts/choice_option.gd" id="1_script"]
[sub_resource type="RectangleShape2D" id="RectangleShape2D_choice"]
size = Vector2(180, 34)

[node name="Choice" type="Area2D"]
script = ExtResource("1_script")

[node name="CollisionShape2D" type="CollisionShape2D" parent="."]
shape = SubResource("RectangleShape2D_choice")

[node name="ChoiceVisual" type="Polygon2D" parent="."]
color = Color(0.24, 0.3, 0.42, 1)
polygon = PackedVector2Array(-90, -17, 90, -17, 90, 17, -90, 17)

[node name="ChoiceLabel" type="Label" parent="."]
offset_left = -76.0
offset_top = -12.0
offset_right = 76.0
offset_bottom = 12.0
text = "Enter"
"""


def _visual_novel_npc_scene() -> str:
    return """[gd_scene load_steps=2 format=3]

[ext_resource type="Script" path="res://scripts/npc_portrait.gd" id="1_script"]

[node name="Npc" type="Node2D"]
script = ExtResource("1_script")

[node name="PortraitVisual" type="Polygon2D" parent="."]
color = Color(0.58, 0.38, 0.72, 1)
polygon = PackedVector2Array(0, -68, 44, -24, 34, 58, -34, 58, -44, -24)

[node name="NameLabel" type="Label" parent="."]
offset_left = -58.0
offset_top = 66.0
offset_right = 58.0
offset_bottom = 92.0
text = "Mira"
"""


def _survival_crafting_campfire_scene() -> str:
    return """[gd_scene load_steps=2 format=3]

[ext_resource type="Script" path="res://scripts/campfire_controller.gd" id="1_script"]

[node name="Campfire" type="Node2D"]
script = ExtResource("1_script")

[node name="CampfireVisual" type="Polygon2D" parent="."]
color = Color(0.65, 0.32, 0.16, 1)
polygon = PackedVector2Array(0, -20, 22, 18, -22, 18)
"""


def _main_script() -> str:
    return """extends Node2D

@onready var hud := $HUD
@onready var health := $Health

func _ready() -> void:
    if has_node("Coin"):
        $Coin.collected.connect(_on_coin_collected)
    if has_node("Enemy"):
        $Enemy.body_entered.connect(_on_enemy_body_entered)
    health.health_changed.connect(_on_health_changed)
    hud.set_health(health.current_health)

func _on_coin_collected() -> void:
    hud.add_score(1)

func _on_enemy_body_entered(body: Node) -> void:
    if body.name == "Player":
        health.damage(1)

func _on_health_changed(current_health: int) -> void:
    hud.set_health(current_health)
"""


def _topdown_main_script() -> str:
    return """extends Node2D

@onready var hud := $HUD
@onready var health := $Health

func _ready() -> void:
    if has_node("Pickup"):
        $Pickup.collected.connect(_on_pickup_collected)
    if has_node("Enemy"):
        $Enemy.body_entered.connect(_on_enemy_body_entered)
        $Enemy.target_path = $Enemy.get_path_to($Player)
    health.health_changed.connect(_on_health_changed)
    hud.set_health(health.current_health)

func _on_pickup_collected() -> void:
    hud.add_score(1)

func _on_enemy_body_entered(body: Node) -> void:
    if body.name == "Player":
        health.damage(1)

func _on_health_changed(current_health: int) -> void:
    hud.set_health(current_health)
"""


def _arpg_main_script() -> str:
    return """extends Node2D

@onready var hud := $HUD
@onready var health := $Health
@onready var player := $Player

var relics_collected := 0

func _ready() -> void:
    if has_node("Pickup"):
        $Pickup.collected.connect(_on_relic_collected)
    if has_node("Enemy"):
        $Enemy.body_entered.connect(_on_enemy_body_entered)
        $Enemy.target_path = $Enemy.get_path_to($Player)
    player.attacked.connect(_on_player_attacked)
    player.dodged.connect(_on_player_dodged)
    health.health_changed.connect(_on_health_changed)
    hud.set_health(health.current_health)
    hud.set_quest(relics_collected)

func _on_relic_collected() -> void:
    relics_collected += 1
    hud.set_quest(relics_collected)

func _on_enemy_body_entered(body: Node) -> void:
    if body.name == "Player":
        health.damage(1)

func _on_player_attacked() -> void:
    hud.set_action("Attack")

func _on_player_dodged() -> void:
    hud.set_action("Dodge")

func _on_health_changed(current_health: int) -> void:
    hud.set_health(current_health)
"""


def _roguelike_main_script() -> str:
    return """extends Node2D

@onready var hud := $HUD
@onready var health := $Health
@onready var player := $Player

var loot_collected := 0
var depth := 1

func _ready() -> void:
    if has_node("Pickup"):
        $Pickup.collected.connect(_on_loot_collected)
    if has_node("Enemy"):
        $Enemy.body_entered.connect(_on_enemy_body_entered)
        $Enemy.target_path = $Enemy.get_path_to($Player)
    player.attacked.connect(_on_player_attacked)
    player.descended.connect(_on_player_descended)
    health.health_changed.connect(_on_health_changed)
    hud.set_loot(loot_collected)
    hud.set_depth(depth)
    hud.set_health(health.current_health)

func _on_loot_collected() -> void:
    loot_collected += 1
    hud.set_loot(loot_collected)

func _on_enemy_body_entered(body: Node) -> void:
    if body.name == "Player":
        health.damage(1)

func _on_player_attacked() -> void:
    hud.set_action("Attack")

func _on_player_descended() -> void:
    depth += 1
    hud.set_depth(depth)
    hud.set_action("Descend")

func _on_health_changed(current_health: int) -> void:
    hud.set_health(current_health)
"""


def _visual_novel_main_script() -> str:
    return """extends Node2D

@onready var hud := $HUD
@onready var player := $Player
@onready var npc := $Npc

var dialogue_index := 0
var choice_focus := 0
var affinity := 0
var lines := [
    "The old gate is still open.",
    "Someone has to decide before sunrise.",
    "Will you enter or wait?"
]
var choices := ["Enter", "Wait"]

func _ready() -> void:
    player.advanced.connect(_on_advanced)
    player.choice_changed.connect(_on_choice_changed)
    player.choice_selected.connect(_on_choice_selected)
    hud.set_speaker(npc.speaker_name)
    hud.set_dialogue(lines[dialogue_index])
    hud.set_choices(choices, choice_focus)
    hud.set_affinity(affinity)

func _on_advanced() -> void:
    dialogue_index = min(dialogue_index + 1, lines.size() - 1)
    hud.set_dialogue(lines[dialogue_index])

func _on_choice_changed(delta: int) -> void:
    choice_focus = wrapi(choice_focus + delta, 0, choices.size())
    hud.set_choices(choices, choice_focus)

func _on_choice_selected(index: int) -> void:
    affinity += 1 if index == 0 else -1
    hud.set_affinity(affinity)
    hud.set_dialogue("Choice: %s" % choices[index])
"""


def _survival_crafting_main_script() -> str:
    return """extends Node2D

@onready var hud := $HUD
@onready var health := $Health
@onready var player := $Player
@onready var resource := $Resource
@onready var campfire := $Campfire

var wood := 0
var hunger := 100

func _ready() -> void:
    player.gathered.connect(_on_player_gathered)
    player.crafted.connect(_on_player_crafted)
    resource.harvested.connect(_on_resource_harvested)
    campfire.built.connect(_on_campfire_built)
    health.health_changed.connect(_on_health_changed)
    hud.set_wood(wood)
    hud.set_hunger(hunger)
    hud.set_health(health.current_health)
    hud.set_campfire(campfire.is_built)

func _process(delta: float) -> void:
    hunger = max(hunger - int(delta * 1.0), 0)
    hud.set_hunger(hunger)

func _on_player_gathered() -> void:
    resource.harvest()

func _on_resource_harvested(amount: int) -> void:
    wood += amount
    hud.set_wood(wood)

func _on_player_crafted() -> void:
    if wood < 2:
        return
    wood -= 2
    hud.set_wood(wood)
    campfire.build()

func _on_campfire_built() -> void:
    hud.set_campfire(campfire.is_built)

func _on_health_changed(current_health: int) -> void:
    hud.set_health(current_health)
"""


def _tower_defense_main_script() -> str:
    return """extends Node2D

@onready var hud := $HUD
@onready var health := $Health
@onready var player := $Player
@onready var tower := $Tower
@onready var enemy := $Enemy

var resources := 5

func _ready() -> void:
    player.tower_placed.connect(_on_tower_placed)
    tower.fired.connect(_on_tower_fired)
    enemy.base_reached.connect(_on_enemy_base_reached)
    health.health_changed.connect(_on_health_changed)
    hud.set_resources(resources)
    hud.set_health(health.current_health)

func _on_tower_placed(_position: Vector2) -> void:
    if resources <= 0:
        return
    resources -= 1
    hud.set_resources(resources)

func _on_tower_fired() -> void:
    enemy.take_damage(1)

func _on_enemy_base_reached() -> void:
    health.damage(1)
    enemy.reset_to_spawn()

func _on_health_changed(current_health: int) -> void:
    hud.set_health(current_health)
"""


def _player_script() -> str:
    return """extends CharacterBody2D

@export var speed := 240.0
@export var jump_velocity := -420.0
@export var gravity := 980.0

func _physics_process(delta: float) -> void:
    var direction := Input.get_axis("move_left", "move_right")
    velocity.x = direction * speed
    if not is_on_floor():
        velocity.y += gravity * delta
    if Input.is_action_just_pressed("jump") and is_on_floor():
        velocity.y = jump_velocity
    move_and_slide()
"""


def _topdown_player_script() -> str:
    return """extends CharacterBody2D

signal attacked

@export var speed := 220.0
var facing := Vector2.RIGHT

func _physics_process(_delta: float) -> void:
    var input_vector := Vector2(
        Input.get_axis("move_left", "move_right"),
        Input.get_axis("move_up", "move_down")
    )
    if input_vector.length() > 0.01:
        facing = input_vector.normalized()
    velocity = input_vector.normalized() * speed
    move_and_slide()
    if Input.is_action_just_pressed("attack"):
        attacked.emit()
"""


def _arpg_player_script() -> str:
    return """extends CharacterBody2D

signal attacked
signal dodged

@export var speed := 210.0
@export var dodge_multiplier := 2.2
@export var dodge_time := 0.18
var _dodge_left := 0.0
var facing := Vector2.RIGHT

func _physics_process(delta: float) -> void:
    var input_vector := Vector2(
        Input.get_axis("move_left", "move_right"),
        Input.get_axis("move_up", "move_down")
    )
    if input_vector.length() > 0.01:
        facing = input_vector.normalized()
    if Input.is_action_just_pressed("dodge"):
        _dodge_left = dodge_time
        dodged.emit()
    var current_speed := speed * (dodge_multiplier if _dodge_left > 0.0 else 1.0)
    velocity = input_vector.normalized() * current_speed
    _dodge_left = max(_dodge_left - delta, 0.0)
    move_and_slide()
    if Input.is_action_just_pressed("attack"):
        attacked.emit()
"""


def _roguelike_player_script() -> str:
    return """extends CharacterBody2D

signal attacked
signal descended

@export var speed := 205.0
var facing := Vector2.RIGHT

func _physics_process(_delta: float) -> void:
    var input_vector := Vector2(
        Input.get_axis("move_left", "move_right"),
        Input.get_axis("move_up", "move_down")
    )
    if input_vector.length() > 0.01:
        facing = input_vector.normalized()
    velocity = input_vector.normalized() * speed
    move_and_slide()
    if Input.is_action_just_pressed("attack"):
        attacked.emit()
    if Input.is_action_just_pressed("descend"):
        descended.emit()
"""


def _visual_novel_player_script() -> str:
    return """extends Node2D

signal advanced
signal choice_changed(delta: int)
signal choice_selected(index: int)

var current_choice := 0

func _process(_delta: float) -> void:
    if Input.is_action_just_pressed("advance_dialogue"):
        advanced.emit()
    if Input.is_action_just_pressed("choice_left"):
        current_choice = max(current_choice - 1, 0)
        choice_changed.emit(-1)
    if Input.is_action_just_pressed("choice_right"):
        current_choice = min(current_choice + 1, 1)
        choice_changed.emit(1)
    if Input.is_action_just_pressed("select_choice"):
        choice_selected.emit(current_choice)
"""


def _survival_crafting_player_script() -> str:
    return """extends CharacterBody2D

signal gathered
signal crafted

@export var speed := 190.0

func _physics_process(_delta: float) -> void:
    var input_vector := Vector2(
        Input.get_axis("move_left", "move_right"),
        Input.get_axis("move_up", "move_down")
    )
    velocity = input_vector.normalized() * speed
    move_and_slide()
    if Input.is_action_just_pressed("gather"):
        gathered.emit()
    if Input.is_action_just_pressed("craft"):
        crafted.emit()
"""


def _tower_defense_player_script() -> str:
    return """extends CharacterBody2D

signal tower_placed(location: Vector2)

@export var speed := 180.0

func _physics_process(_delta: float) -> void:
    var input_vector := Vector2(
        Input.get_axis("move_left", "move_right"),
        Input.get_axis("move_up", "move_down")
    )
    velocity = input_vector.normalized() * speed
    move_and_slide()
    if Input.is_action_just_pressed("place_tower"):
        tower_placed.emit(global_position)
"""


def _coin_script() -> str:
    return """extends Area2D

signal collected

func _ready() -> void:
    body_entered.connect(_on_body_entered)

func _on_body_entered(body: Node) -> void:
    if body.name == "Player":
        collected.emit()
        queue_free()
"""


def _relic_script() -> str:
    return """extends Area2D

signal collected

func _ready() -> void:
    body_entered.connect(_on_body_entered)

func _on_body_entered(body: Node) -> void:
    if body.name == "Player":
        collected.emit()
        queue_free()
"""


def _loot_script() -> str:
    return """extends Area2D

signal collected

func _ready() -> void:
    body_entered.connect(_on_body_entered)

func _on_body_entered(body: Node) -> void:
    if body.name == "Player":
        collected.emit()
        queue_free()
"""


def _choice_option_script() -> str:
    return """extends Area2D

signal selected

@export var choice_text := "Enter"

func activate() -> void:
    selected.emit()
"""


def _npc_portrait_script() -> str:
    return """extends Node2D

@export var speaker_name := "Mira"
@export var mood := "calm"
"""


def _resource_node_script() -> str:
    return """extends Area2D

signal harvested(amount: int)

@export var amount := 1

func harvest() -> void:
    harvested.emit(amount)
"""


def _campfire_script() -> str:
    return """extends Node2D

signal built

var is_built := false

func build() -> void:
    if is_built:
        return
    is_built = true
    built.emit()
"""


def _enemy_script() -> str:
    return """extends Area2D

@export var patrol_distance := 120.0
@export var patrol_speed := 80.0
var _origin_x := 0.0
var _direction := 1.0

func _ready() -> void:
    _origin_x = position.x

func _process(delta: float) -> void:
    position.x += _direction * patrol_speed * delta
    if abs(position.x - _origin_x) >= patrol_distance:
        _direction *= -1.0
"""


def _topdown_enemy_script() -> str:
    return """extends Area2D

@export var chase_speed := 80.0
@export var target_path: NodePath

func _process(delta: float) -> void:
    var target := get_node_or_null(target_path)
    if target == null:
        return
    var direction := (target.global_position - global_position).normalized()
    global_position += direction * chase_speed * delta
"""


def _tower_script() -> str:
    return """extends Area2D

signal fired

@export var cooldown := 1.0
var _cooldown_left := 0.0

func _process(delta: float) -> void:
    _cooldown_left = max(_cooldown_left - delta, 0.0)
    if _cooldown_left > 0.0:
        return
    for body in get_overlapping_areas():
        if body.name == "Enemy":
            _cooldown_left = cooldown
            fired.emit()
            return
"""


def _tower_defense_enemy_script() -> str:
    return """extends Area2D

signal base_reached

@export var move_speed := 60.0
@export var health := 3
@export var base_x := 680.0
var _spawn_position := Vector2.ZERO

func _ready() -> void:
    _spawn_position = global_position

func _process(delta: float) -> void:
    global_position.x += move_speed * delta
    if global_position.x >= base_x:
        base_reached.emit()

func take_damage(amount: int = 1) -> void:
    health -= amount
    if health <= 0:
        reset_to_spawn()

func reset_to_spawn() -> void:
    global_position = _spawn_position
    health = 3
"""


def _health_script() -> str:
    return """extends Node

signal health_changed(current_health: int)

@export var max_health := 3
var current_health := 3

func damage(amount: int = 1) -> void:
    current_health = max(current_health - amount, 0)
    health_changed.emit(current_health)
"""


def _hud_script() -> str:
    return """extends CanvasLayer

@onready var score_label: Label = $ScoreLabel
@onready var health_label: Label = $HealthLabel

var score := 0

func add_score(amount: int = 1) -> void:
    score += amount
    score_label.text = "Score: %d" % score

func set_health(current_health: int) -> void:
    health_label.text = "HP: %d" % current_health
"""


def _tower_defense_hud_script() -> str:
    return """extends CanvasLayer

@onready var score_label: Label = $ScoreLabel
@onready var health_label: Label = $HealthLabel

func set_resources(resources: int) -> void:
    score_label.text = "Resources: %d" % resources

func set_health(current_health: int) -> void:
    health_label.text = "Base HP: %d" % current_health
"""


def _arpg_hud_script() -> str:
    return """extends CanvasLayer

@onready var quest_label: Label = $QuestLabel
@onready var health_label: Label = $HealthLabel
@onready var action_label: Label = $ActionLabel

func set_quest(relics_collected: int) -> void:
    quest_label.text = "Quest: Relics %d/1" % relics_collected

func set_health(current_health: int) -> void:
    health_label.text = "HP: %d" % current_health

func set_action(action_name: String) -> void:
    action_label.text = "Action: %s" % action_name
"""


def _roguelike_hud_script() -> str:
    return """extends CanvasLayer

@onready var loot_label: Label = $LootLabel
@onready var depth_label: Label = $DepthLabel
@onready var health_label: Label = $HealthLabel
@onready var action_label: Label = $ActionLabel

func set_loot(loot_count: int) -> void:
    loot_label.text = "Loot: %d" % loot_count

func set_depth(depth: int) -> void:
    depth_label.text = "Depth: %d" % depth

func set_health(current_health: int) -> void:
    health_label.text = "HP: %d" % current_health

func set_action(action_name: String) -> void:
    action_label.text = "Action: %s" % action_name
"""


def _visual_novel_hud_script() -> str:
    return """extends CanvasLayer

@onready var speaker_label: Label = $SpeakerLabel
@onready var dialogue_label: Label = $DialogueLabel
@onready var choice_label: Label = $ChoiceLabel
@onready var affinity_label: Label = $AffinityLabel

func set_speaker(speaker_name: String) -> void:
    speaker_label.text = speaker_name

func set_dialogue(line: String) -> void:
    dialogue_label.text = line

func set_choices(choices: Array, focus: int) -> void:
    var labels := []
    for index in choices.size():
        var prefix := "> " if index == focus else "  "
        labels.append("%s%s" % [prefix, choices[index]])
    choice_label.text = "  |  ".join(labels)

func set_affinity(affinity: int) -> void:
    affinity_label.text = "Affinity: %d" % affinity
"""


def _survival_crafting_hud_script() -> str:
    return """extends CanvasLayer

@onready var wood_label: Label = $WoodLabel
@onready var hunger_label: Label = $HungerLabel
@onready var health_label: Label = $HealthLabel
@onready var campfire_label: Label = $CampfireLabel

func set_wood(wood: int) -> void:
    wood_label.text = "Wood: %d" % wood

func set_hunger(hunger: int) -> void:
    hunger_label.text = "Hunger: %d" % hunger

func set_health(current_health: int) -> void:
    health_label.text = "HP: %d" % current_health

func set_campfire(is_built: bool) -> void:
    campfire_label.text = "Campfire: %s" % ("built" if is_built else "none")
"""


def _gameplay_table() -> Dict[str, Any]:
    return {
        "schema": "gameplay_balance",
        "player": {"speed": 240, "jump_velocity": -420, "health": 3},
        "collectibles": {"coin_score": 1},
        "enemies": {"patrol_distance": 120, "patrol_speed": 80, "damage": 1},
    }


def _topdown_gameplay_table() -> Dict[str, Any]:
    return {
        "schema": "gameplay_balance",
        "player": {"speed": 220, "health": 3, "attack_radius": 36},
        "collectibles": {"pickup_score": 1},
        "enemies": {"chase_speed": 80, "damage": 1},
        "arena": {"width": 704, "height": 448},
    }


def _tower_defense_gameplay_table() -> Dict[str, Any]:
    return {
        "schema": "gameplay_balance",
        "player": {"cursor_speed": 180},
        "towers": {"cost": 1, "cooldown": 1.0, "damage": 1, "range": 12},
        "enemies": {"move_speed": 60, "health": 3, "damage": 1},
        "base": {"health": 3, "goal_x": 680},
        "economy": {"starting_resources": 5},
        "waves": {"starter_enemy_count": 1, "spawn_interval": 2.0},
    }


def _arpg_gameplay_table() -> Dict[str, Any]:
    return {
        "schema": "gameplay_balance",
        "player": {"speed": 210, "health": 3, "dodge_multiplier": 2.2, "dodge_time": 0.18},
        "combat": {"attack_radius": 42, "damage": 1},
        "quest": {"relic_goal": 1, "relic_score": 1},
        "enemies": {"chase_speed": 80, "damage": 1},
        "arena": {"width": 768, "height": 480},
    }


def _roguelike_gameplay_table() -> Dict[str, Any]:
    return {
        "schema": "gameplay_balance",
        "player": {"speed": 205, "health": 3},
        "combat": {"attack_radius": 34, "damage": 1},
        "loot": {"pickup_value": 1, "starter_pickups": 1},
        "enemies": {"chase_speed": 80, "damage": 1},
        "dungeon": {"starting_depth": 1, "room_width": 736, "room_height": 448},
    }


def _visual_novel_gameplay_table() -> Dict[str, Any]:
    return {
        "schema": "gameplay_balance",
        "dialogue": {"starter_line_count": 3, "auto_advance": False},
        "choices": {"options": ["Enter", "Wait"], "default_focus": 0},
        "characters": {"speaker": "Mira", "mood": "calm"},
        "progression": {"starting_affinity": 0, "enter_affinity_delta": 1, "wait_affinity_delta": -1},
    }


def _survival_crafting_gameplay_table() -> Dict[str, Any]:
    return {
        "schema": "gameplay_balance",
        "player": {"speed": 190, "health": 3},
        "resources": {"wood_per_gather": 1, "starting_wood": 0},
        "crafting": {"campfire_wood_cost": 2},
        "survival": {"starting_hunger": 100, "hunger_tick": 1},
    }


def _design_doc(plan: Dict[str, Any]) -> str:
    template = SUPPORTED_TEMPLATES.get(str(plan.get("template_id") or ""), {})
    lines = [
        f"# {plan.get('title') or 'Game Creation'} Design Plan",
        "",
        f"- Template: `{plan.get('template_id') or '-'}`",
        f"- Template Label: {template.get('label') or '-'}",
        f"- Genre: `{plan.get('genre') or '-'}`",
        f"- Manifest: `{plan.get('manifest_path') or DEFAULT_GAME_CREATION_MANIFEST_PATH}`",
        "",
        "## Block Structure",
        "",
        "```mermaid",
        str(plan.get("block_diagram") or "").strip(),
        "```",
        "",
        "## Modules",
        "",
    ]
    for module in list(plan.get("module_plan") or []):
        lines.extend([
            f"### {module.get('label') or module.get('module_id') or 'Module'}",
            "",
            f"- Module ID: `{module.get('module_id') or '-'}`",
            f"- Role: `{module.get('role') or '-'}`",
            f"- Scene: `{module.get('scene_path') or '-'}`",
            f"- Script: `{module.get('script_path') or '-'}`",
            f"- Depends On: `{', '.join(module.get('depends_on') or []) or '-'}`",
            f"- Godot Nodes: `{', '.join(module.get('godot_nodes') or []) or '-'}`",
            f"- Skills: `{', '.join(item.get('skill_name') or '' for item in module.get('skill_bindings') or []) or '-'}`",
            f"- Constraints: {'; '.join(module.get('constraints') or []) or '-'}",
            f"- Response: {module.get('response') or '-'}",
            "",
        ])
    lines.extend([
        "## Skill Binding Plan",
        "",
    ])
    for item in list(plan.get("skill_binding_plan") or []):
        lines.append(
            f"- `{item.get('module_id') or '-'}` / `{item.get('role') or '-'}` -> `{item.get('skill_name') or '-'}`: {item.get('purpose') or '-'}"
        )
    lines.append("")
    lines.extend([
        "## Godot Response Map",
        "",
    ])
    for item in list(plan.get("godot_response_map") or []):
        lines.append(
            f"- `{item.get('trigger') or '-'}` -> `{item.get('node_path') or '-'}` -> `{item.get('response') or '-'}`"
        )
    lines.append("")
    return "\n".join(lines)

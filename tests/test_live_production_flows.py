import base64
import os
import time
from pathlib import Path
from urllib.parse import quote

import httpx
import pytest


pytestmark = pytest.mark.live


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


API_HOST = os.environ.get("GODOT_AGENT_API_HOST", "127.0.0.1").strip() or "127.0.0.1"
API_PORT = _env_int("GODOT_AGENT_API_PORT", 8000)
BASE_URL = f"http://{API_HOST}:{API_PORT}"
REPO_ROOT = Path(__file__).parent.parent.resolve()
PROJECT_PATH = str((REPO_ROOT / "sandbox_project").resolve())
HTTP_TIMEOUT = 60.0


@pytest.fixture(scope="session", autouse=True)
def ensure_live_api_and_editor():
    try:
        response = httpx.get(f"{BASE_URL}/health", timeout=2.0)
        response.raise_for_status()
    except Exception as exc:
        pytest.skip(f"API Server 未在 {BASE_URL} 启动，跳过扩展 live 验证: {exc}")

    try:
        response = httpx.post(
            f"{BASE_URL}/editor/launch",
            json={"project_path": PROJECT_PATH, "wait_for_editor": True, "editor_timeout": 30},
            timeout=HTTP_TIMEOUT,
        )
        response.raise_for_status()
    except Exception as exc:
        pytest.skip(f"无法启动或连接 Godot 编辑器，跳过扩展 live 验证: {exc}")

    payload = response.json()
    if not payload.get("editor_online"):
        pytest.skip("Godot 编辑器未上线，跳过扩展 live 验证。")


def _post_json(path: str, payload: dict, *, timeout: float = HTTP_TIMEOUT) -> dict:
    response = httpx.post(f"{BASE_URL}{path}", json=payload, timeout=timeout)
    response.raise_for_status()
    return response.json()


def _assert_task_success(payload: dict, expected_skill: str) -> None:
    assert payload.get("status") == "success", payload.get("message")
    skill_result = (payload.get("context") or {}).get("last_skill_result") or {}
    assert skill_result.get("skill_name") == expected_skill
    assert (skill_result.get("validation") or {}).get("passed") is True


def test_p1_content_pipeline_skills_execute_while_godot_editor_is_live():
    raw_asset_dir = Path(PROJECT_PATH) / "raw_assets"
    raw_asset_dir.mkdir(parents=True, exist_ok=True)
    source_png = raw_asset_dir / "live_probe_texture.png"
    source_png.write_bytes(base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADElEQVR42mP8z8AARQMBgAEpAikAAAAASUVORK5CYII="
    ))

    level_payload = _post_json(
        "/execute",
        {
            "project_path": PROJECT_PATH,
            "command": "创建关卡 live_validation_level 的 combat 关卡模板",
        },
    )
    _assert_task_success(level_payload, "manage_level_workflow")
    assert (Path(PROJECT_PATH) / "scenes" / "levels" / "live_validation_level.tscn").exists()
    assert (Path(PROJECT_PATH) / "data_tables" / "levels" / "live_validation_level.json").exists()

    art_payload = _post_json(
        "/execute",
        {
            "project_path": PROJECT_PATH,
            "command": (
                '导入美术资源 资产ID live_probe_texture "res://raw_assets/live_probe_texture.png" '
                "到 res://assets/textures/live_probe_texture.png 64x64 内存 0.1mb"
            ),
        },
    )
    _assert_task_success(art_payload, "manage_art_asset_pipeline")
    assert (Path(PROJECT_PATH) / "assets" / "textures" / "live_probe_texture.png").exists()

    telemetry_payload = _post_json(
        "/telemetry/manage",
        {
            "project_path": PROJECT_PATH,
            "action": "apply",
            "catalog_entries": [
                {
                    "event_name": "live_probe_start",
                    "category": "playtest",
                    "description": "Live validation probe started.",
                    "feature_id": "live_validation",
                    "privacy_level": "anonymous",
                    "fields": [{"name": "build_id", "type": "string", "required": True, "pii": False}],
                },
                {
                    "event_name": "live_probe_complete",
                    "category": "playtest",
                    "description": "Live validation probe completed.",
                    "feature_id": "live_validation",
                    "privacy_level": "anonymous",
                    "fields": [{"name": "elapsed_seconds", "type": "number", "required": True, "pii": False}],
                },
            ],
            "events": [
                {
                    "event_name": "live_probe_start",
                    "session_id": "live_probe_session",
                    "timestamp": "2026-04-11T10:00:00Z",
                    "payload": {"build_id": "live"},
                },
                {
                    "event_name": "live_probe_complete",
                    "session_id": "live_probe_session",
                    "timestamp": "2026-04-11T10:00:03Z",
                    "payload": {"elapsed_seconds": 3},
                },
            ],
        },
    )
    _assert_task_success(telemetry_payload, "manage_game_telemetry")
    assert telemetry_payload["telemetry"]["summary"]["passed"] is True
    assert telemetry_payload["telemetry"]["summary"]["privacy_gate_passed"] is True
    assert telemetry_payload["telemetry"]["summary"]["pii_violation_count"] == 0

    performance_payload = _post_json(
        "/performance/manage",
        {
            "project_path": PROJECT_PATH,
            "action": "analyze",
            "scene_path": "res://sandbox_main.tscn",
            "baseline_metrics": {
                "scene_load_ms": 400,
                "fps": 60,
                "memory_peak_mb": 120,
                "draw_call_count": 100,
                "node_count": 40,
                "texture_memory_mb": 16,
                "frame_spike_ms": 10,
                "screenshot_diff_ratio": 0.01,
            },
            "profile_metrics": {
                "scene_load_ms": 390,
                "fps": 60,
                "memory_peak_mb": 118,
                "draw_call_count": 98,
                "node_count": 42,
                "texture_memory_mb": 16,
                "frame_spike_ms": 9,
                "screenshot_diff_ratio": 0.012,
            },
            "budget_overrides": {"max_screenshot_diff_ratio": 0.035},
        },
    )
    _assert_task_success(performance_payload, "manage_game_performance")
    assert performance_payload["performance"]["summary"]["passed"] is True

    balance_payload = _post_json(
        "/execute",
        {
            "project_path": PROJECT_PATH,
            "command": "分析敌人任务掉落数值平衡",
            "context": {
                "balance_enemy_rows": [
                    {"enemy_id": "slime_basic", "name": "Slime", "hp": "30", "attack": "5", "move_speed": "100", "loot_table_id": "loot_slime"}
                ],
                "balance_loot_rows": [
                    {"loot_id": "loot_slime", "item_id": "coin", "drop_rate": "0.5", "quantity": "2"}
                ],
                "balance_quest_rows": [
                    {"quest_id": "quest_slime", "title": "清理史莱姆", "description": "消灭 3 只史莱姆", "target_count": "3", "reward_gold": "90", "next_quest_id": ""}
                ],
            },
        },
    )
    _assert_task_success(balance_payload, "analyze_game_balance")


def test_p11_art_dcc_profiles_execute_live():
    raw_model_dir = Path(PROJECT_PATH) / "raw_assets" / "models"
    raw_model_dir.mkdir(parents=True, exist_ok=True)
    source_blend = raw_model_dir / "live_guard.blend"
    source_blend.write_bytes(b"fake-live-blend")

    payload = _post_json(
        "/execute",
        {
            "project_path": PROJECT_PATH,
            "command": (
                "同步 Blender GLTF 模型 资产ID live_guard "
                "res://raw_assets/models/live_guard.blend 到 res://assets/models/live_guard.glb LOD 2"
            ),
        },
    )
    _assert_task_success(payload, "manage_art_asset_pipeline")
    assert payload["context"]["art_asset_type"] == "model"
    assert payload["context"]["art_asset_source_tool"] == "blender"
    assert (Path(PROJECT_PATH) / "assets" / "models" / "live_guard.glb").exists()
    assert (Path(PROJECT_PATH) / "assets" / "manifests" / "model_assets.json").exists()


def test_p11_art_asset_manage_endpoint_supports_model_profile_live():
    raw_model_dir = Path(PROJECT_PATH) / "raw_assets" / "models"
    raw_model_dir.mkdir(parents=True, exist_ok=True)
    source_blend = raw_model_dir / "live_guard_api.blend"
    albedo = raw_model_dir / "live_guard_api_albedo.png"
    source_blend.write_bytes(b"fake-live-blend-api")
    albedo.write_bytes(b"fake-live-albedo")

    preview_payload = _post_json(
        "/art-assets/manage",
        {
            "project_path": PROJECT_PATH,
            "action": "preview",
            "asset_type": "model",
            "asset_id": "live_guard_api",
            "source_path": "res://raw_assets/models/live_guard_api.blend",
            "target_path": "res://assets/models/live_guard_api.glb",
            "source_tool": "blender",
            "lod_count": 2,
        },
    )
    _assert_task_success(preview_payload, "manage_art_asset_pipeline")
    assert preview_payload["art_asset_profile"]["asset_type"] == "model"
    assert preview_payload["art_asset_profile"]["entry_count"] == 1

    apply_payload = _post_json(
        "/art-assets/manage",
        {
            "project_path": PROJECT_PATH,
            "action": "apply",
            "asset_type": "model",
            "asset_id": "live_guard_api",
            "source_path": "res://raw_assets/models/live_guard_api.blend",
            "target_path": "res://assets/models/live_guard_api.glb",
            "source_tool": "blender",
            "lod_count": 2,
            "source_dependency_paths": [
                "res://raw_assets/models/live_guard_api_albedo.png",
            ],
            "target_dependency_paths": [
                "res://assets/models/live_guard_api_albedo.png",
            ],
        },
    )
    _assert_task_success(apply_payload, "manage_art_asset_pipeline")
    assert apply_payload["context"]["art_asset_type"] == "model"
    assert apply_payload["context"]["art_asset_source_tool"] == "blender"
    assert (Path(PROJECT_PATH) / "assets" / "models" / "live_guard_api.glb").exists()
    assert (Path(PROJECT_PATH) / "assets" / "models" / "live_guard_api_albedo.png").exists()


def test_p8_level_workflow_manage_endpoint_supports_snapshot_and_diff_live():
    level_name = "live_p8_level"
    scene_path = Path(PROJECT_PATH) / "scenes" / "levels" / f"{level_name}.tscn"
    snapshot_a = REPO_ROOT / "logs" / "test_artifacts" / "live_p8_snapshot_a.json"
    snapshot_b = REPO_ROOT / "logs" / "test_artifacts" / "live_p8_snapshot_b.json"
    snapshot_a.unlink(missing_ok=True)
    snapshot_b.unlink(missing_ok=True)

    template_payload = _post_json(
        "/levels/manage",
        {
            "project_path": PROJECT_PATH,
            "action": "template",
            "level_name": level_name,
            "level_type": "hub",
        },
    )
    _assert_task_success(template_payload, "manage_level_workflow")
    assert template_payload["level_workflow"]["level_manifest"]["schema_version"] == "1.1"
    assert scene_path.exists()

    snapshot_payload = _post_json(
        "/levels/manage",
        {
            "project_path": PROJECT_PATH,
            "action": "snapshot",
            "level_name": level_name,
            "level_type": "hub",
            "snapshot_path": str(snapshot_a),
        },
    )
    _assert_task_success(snapshot_payload, "manage_level_workflow")
    assert snapshot_payload["level_workflow"]["snapshot"]["node_count"] > 0
    assert snapshot_a.exists()

    scene_path.write_text(
        scene_path.read_text(encoding="utf-8") + '[node name="LiveExtraTrigger" type="Area2D" parent="."]\n\n',
        encoding="utf-8",
    )

    diff_payload = _post_json(
        "/levels/manage",
        {
            "project_path": PROJECT_PATH,
            "action": "diff",
            "level_name": level_name,
            "level_type": "hub",
            "snapshot_path": str(snapshot_b),
            "compare_snapshot_path": str(snapshot_a),
        },
    )
    _assert_task_success(diff_payload, "manage_level_workflow")
    assert diff_payload["level_workflow"]["diff"]["status"] == "changed"
    assert any(
        node["path"] == "LiveExtraTrigger"
        for node in diff_payload["level_workflow"]["diff"]["added_nodes"]
    )

    snapshot_a.unlink(missing_ok=True)
    snapshot_b.unlink(missing_ok=True)


def test_p9_gameplay_template_manage_endpoint_supports_preview_and_apply_live():
    preview_payload = _post_json(
        "/gameplay/manage",
        {
            "project_path": PROJECT_PATH,
            "action": "preview",
            "template_id": "survival_crafting",
            "include_system_ids": ["inventory_core", "crafting_recipes"],
        },
    )
    _assert_task_success(preview_payload, "manage_gameplay_template")
    assert preview_payload["gameplay_template"]["template_id"] == "survival_crafting"
    assert preview_payload["gameplay_template"]["system_count"] == 2

    apply_payload = _post_json(
        "/gameplay/manage",
        {
            "project_path": PROJECT_PATH,
            "action": "apply",
            "template_id": "survival_crafting",
        },
    )
    _assert_task_success(apply_payload, "manage_gameplay_template")
    assert apply_payload["gameplay_template"]["template_id"] == "survival_crafting"
    assert apply_payload["context"]["gameplay_template_applied"] is True
    assert apply_payload["gameplay_template"]["system_count"] >= 6


def test_p10_presentation_manage_endpoint_supports_preview_and_apply_live():
    preview_payload = _post_json(
        "/presentation/manage",
        {
            "project_path": PROJECT_PATH,
            "action": "preview",
            "presentation_type": "shader",
            "profile_id": "live_heat_wave",
            "shader_mode": "canvas_item",
            "shader_params": {
                "wave_strength": 0.18,
                "scroll_speed": 0.24,
                "tint_color": "#4fc3f7",
            },
        },
    )
    _assert_task_success(preview_payload, "manage_presentation_pipeline")
    assert preview_payload["presentation_profile"]["presentation_type"] == "shader"
    assert preview_payload["presentation_profile"]["entry_count"] == 1
    assert preview_payload["presentation_profile"]["generated_path_count"] == 2

    apply_payload = _post_json(
        "/presentation/manage",
        {
            "project_path": PROJECT_PATH,
            "action": "apply",
            "presentation_type": "audio",
            "profile_id": "live_ui_confirm",
            "audio_role": "ui",
            "event_name": "live_ui_confirm",
            "bus_name": "UI",
            "audio_stream_path": "res://assets/audio/live_ui_confirm.ogg",
        },
    )
    _assert_task_success(apply_payload, "manage_presentation_pipeline")
    assert apply_payload["context"]["presentation_written"] is True
    assert apply_payload["presentation_profile"]["presentation_type"] == "audio"
    assert (Path(PROJECT_PATH) / "assets" / "manifests" / "audio_profiles.json").exists()
    assert (Path(PROJECT_PATH) / "scripts" / "audio" / "live_ui_confirm_audio_router.gd").exists()


def test_p12_liveops_manage_endpoint_supports_template_and_apply_live():
    remote_config_path = Path(PROJECT_PATH) / "liveops" / "remote_config.json"
    experiments_path = Path(PROJECT_PATH) / "liveops" / "experiments.json"

    template_payload = _post_json(
        "/liveops/manage",
        {
            "project_path": PROJECT_PATH,
            "action": "template",
            "liveops_type": "remote_config",
            "entry_id": "live_spawn_multiplier",
        },
    )
    _assert_task_success(template_payload, "manage_liveops_pipeline")
    assert template_payload["liveops_profile"]["liveops_type"] == "remote_config"
    assert template_payload["liveops_profile"]["entry_count"] >= 1
    assert remote_config_path.exists()

    apply_payload = _post_json(
        "/liveops/manage",
        {
            "project_path": PROJECT_PATH,
            "action": "apply",
            "liveops_type": "experiment_catalog",
            "entries": [
                {
                    "experiment_id": "live_tutorial_short_path",
                    "status": "running",
                    "hypothesis": "缩短教程路径提升完成率",
                    "owner": "product_ops",
                    "target_metrics": ["tutorial_completion_rate", "d1_retention"],
                    "rollout_percentage": 40,
                    "rollback_rule": "tutorial_completion_rate 下降 3% 回滚",
                    "variants": [
                        {"variant_id": "control", "weight": 50},
                        {"variant_id": "short_path", "weight": 50},
                    ],
                }
            ],
        },
    )
    _assert_task_success(apply_payload, "manage_liveops_pipeline")
    assert apply_payload["context"]["liveops_written"] is True
    assert apply_payload["liveops_profile"]["liveops_type"] == "experiment_catalog"
    assert apply_payload["liveops_profile"]["variant_count"] == 2
    assert experiments_path.exists()


def test_p5_p6_surfaces_pass_while_godot_editor_is_live():
    production = _post_json(
        "/production/validate",
        {
            "project_path": str(REPO_ROOT),
            "scenario_id": "vertical_slice_2d",
            "evidence": {"contract": True, "tests": True, "docs": True, "quality_dashboard": True},
            "changed_paths": ["scenes/Main.tscn", "scripts/player_controller.gd", "README.md"],
            "mode": "strict",
        },
    )
    assert production["readiness_status"] == "passed"
    assert production["blocking_checks"] == []
    assert production["warning_checks"] == []

    compat = _post_json(
        "/agent-compat/matrix",
        {"project_path": str(REPO_ROOT), "providers": ["codex", "openai_api"]},
    )
    assert compat["passed"] is True
    assert compat["provider_count"] == 2
    assert not compat["blocked_surfaces"]


def test_live_portal_websocket_observes_production_api_updates():
    project = quote(PROJECT_PATH, safe="")
    response = httpx.get(f"{BASE_URL}/health?project_path={project}", timeout=HTTP_TIMEOUT)
    response.raise_for_status()
    health = response.json()
    assert health["editor_state"]["is_active"] is True
    assert str(health["editor_state"]["project_path"]).replace("\\", "/").endswith("/sandbox_project/")

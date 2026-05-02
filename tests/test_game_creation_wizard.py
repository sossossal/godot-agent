import json
import shutil
import unittest
from pathlib import Path
from unittest.mock import patch

from agent_system.models import ToolResult
from agent_system.tools.game_creation_wizard import (
    DEFAULT_GAME_CREATION_INPUT_REPLAY_PATH,
    DEFAULT_GAME_CREATION_MANIFEST_PATH,
    DEFAULT_GAME_CREATION_REPLAY_REPORT_PATH,
    DEFAULT_GAME_CREATION_TEMPLATE_MIGRATION_PATH,
    DEFAULT_GAME_CREATION_REVIEW_DOC_PATH,
    DEFAULT_GAME_CREATION_REVIEW_PATH,
    DEFAULT_SCENE_GRAPH_AUDIT_PATH,
    apply_game_creation_plan,
    build_game_creation_input_replay,
    build_game_creation_template_migration,
    build_game_creation_review,
    build_game_creation_plan,
    build_scene_graph_audit,
    list_game_creation_templates,
)


project_root = Path(__file__).parent.parent


class ReplayGodotCLI:
    def __init__(self, project_root: Path):
        self.project_root = Path(project_root)
        self.calls = []

    def run_headless(self, script_path, args=None):
        self.calls.append({"script_path": str(script_path), "args": list(args or [])})
        screenshot_path = self.project_root / "logs" / "test_artifacts" / "game_creation" / "tower_defense_runtime.png"
        screenshot_path.parent.mkdir(parents=True, exist_ok=True)
        screenshot_path.write_bytes(b"fake-png")
        return ToolResult(True, "OK", data={"stdout": "REPLAY_SCREENSHOT_CAPTURE=viewport\nreplay ok", "stderr": ""})


class FallbackScreenshotReplayGodotCLI(ReplayGodotCLI):
    def run_headless(self, script_path, args=None):
        self.calls.append({"script_path": str(script_path), "args": list(args or [])})
        screenshot_path = self.project_root / "logs" / "test_artifacts" / "game_creation" / "tower_defense_runtime.png"
        screenshot_path.parent.mkdir(parents=True, exist_ok=True)
        screenshot_path.write_bytes(b"fake-png")
        return ToolResult(True, "OK", data={"stdout": "REPLAY_SCREENSHOT_CAPTURE=fallback_headless", "stderr": ""})


class ViewportReplayGodotCLI(ReplayGodotCLI):
    def run_script(self, script_path, args=None, *, headless=True, timeout=30):
        self.calls.append({
            "script_path": str(script_path),
            "args": list(args or []),
            "headless": headless,
            "timeout": timeout,
        })
        screenshot_path = self.project_root / "logs" / "test_artifacts" / "game_creation" / "tower_defense_runtime.png"
        screenshot_path.parent.mkdir(parents=True, exist_ok=True)
        screenshot_path.write_bytes(b"viewport-png")
        return ToolResult(True, "OK", data={"stdout": "REPLAY_SCREENSHOT_CAPTURE=viewport", "stderr": ""})


class FailingReplayGodotCLI(ReplayGodotCLI):
    def run_headless(self, script_path, args=None):
        self.calls.append({"script_path": str(script_path), "args": list(args or [])})
        return ToolResult(False, "failed", error="boom", data={"stdout": "", "stderr": "boom"})


class GameCreationWizardTestCase(unittest.TestCase):
    def setUp(self):
        self.temp_project = project_root / "tests" / ".tmp_game_creation_wizard"
        shutil.rmtree(self.temp_project, ignore_errors=True)
        self.temp_project.mkdir(parents=True, exist_ok=True)

    def tearDown(self):
        shutil.rmtree(self.temp_project, ignore_errors=True)

    def test_list_templates_exposes_default_platformer(self):
        payload = list_game_creation_templates()

        self.assertEqual(payload["default_template_id"], "platformer_2d")
        self.assertEqual(payload["count"], 7)
        genres = {item["genre"] for item in payload["items"]}
        self.assertIn("platformer_2d", genres)
        self.assertIn("topdown_action_2d", genres)
        self.assertIn("tower_defense_2d", genres)
        self.assertIn("arpg_2d", genres)
        self.assertIn("roguelike_2d", genres)
        self.assertIn("visual_novel_2d", genres)
        self.assertIn("survival_crafting_2d", genres)

    def test_build_plan_returns_normalized_contract_without_writing(self):
        payload = build_game_creation_plan(
            self.temp_project,
            title="Demo Runner",
            features=["jump", "coins"],
            target_platforms=["web"],
        )

        self.assertEqual(payload["schema_version"], "1.0")
        self.assertEqual(payload["game_id"], "demo_runner")
        self.assertEqual(payload["status"], "passed")
        self.assertEqual(payload["target_platforms"], ["web"])
        self.assertEqual(payload["manifest_path"], DEFAULT_GAME_CREATION_MANIFEST_PATH)
        self.assertTrue(payload["module_plan"])
        self.assertIn("flowchart LR", payload["block_diagram"])
        self.assertIn("input_map --> player_controller", payload["block_diagram"])
        self.assertTrue(payload["skill_binding_plan"])
        self.assertIn("generate_movement_script", {item["skill_name"] for item in payload["skill_binding_plan"]})
        self.assertTrue(payload["module_plan"][0]["constraints"])
        self.assertTrue(payload["godot_response_map"])
        self.assertIn("docs/game_creation_design.md", payload["artifact_paths"])
        self.assertIn(DEFAULT_GAME_CREATION_INPUT_REPLAY_PATH, payload["artifact_paths"])
        self.assertTrue(payload["input_replay_plan"])
        self.assertEqual(payload["golden_screenshot_plan"]["status"], "planned")
        self.assertIn("platformer_2d_main.png", payload["golden_screenshot_plan"]["baseline_path"])
        self.assertEqual(payload["template_migration_plan"]["current_template_id"], "platformer_2d")
        self.assertIn("arpg_2d", payload["template_migration_plan"]["supported_targets"])
        self.assertIn("roguelike_2d", payload["template_migration_plan"]["supported_targets"])
        self.assertIn("visual_novel_2d", payload["template_migration_plan"]["supported_targets"])
        self.assertIn("survival_crafting_2d", payload["template_migration_plan"]["supported_targets"])
        self.assertFalse((self.temp_project / "scenes" / "Main.tscn").exists())

    def test_apply_plan_writes_scaffold_and_manifest(self):
        payload = apply_game_creation_plan(
            self.temp_project,
            title="Demo Runner",
            target_platforms=["desktop"],
            overwrite=True,
        )

        manifest_path = self.temp_project / DEFAULT_GAME_CREATION_MANIFEST_PATH
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

        self.assertEqual(payload["status"], "passed")
        self.assertIn("scenes/Main.tscn", payload["generated_files"])
        self.assertIn("scripts/main_controller.gd", payload["generated_files"])
        self.assertTrue(payload["layout_passed"])
        self.assertGreater(payload["layout_check_count"], 0)
        self.assertFalse(payload["layout_blocking_checks"])
        self.assertTrue(payload["governance_passed"])
        self.assertFalse(payload["governance_blocking_checks"])
        self.assertEqual(payload["governance_admission"]["change_type"], "game_creation")
        self.assertIn("contract", payload["governance_admission"]["provided_evidence"])
        self.assertIn("data_tables/game_creation/game_creation_profile.json", {
            item["path"] for item in payload["layout_checks"]
        })
        self.assertTrue((self.temp_project / "project.godot").exists())
        self.assertTrue((self.temp_project / "scripts" / "player_controller.gd").exists())
        self.assertTrue((self.temp_project / "docs" / "game_creation_design.md").exists())
        self.assertTrue((self.temp_project / DEFAULT_GAME_CREATION_INPUT_REPLAY_PATH).exists())
        self.assertEqual(manifest["game_id"], "demo_runner")
        self.assertIn("module_plan", manifest)
        self.assertIn("skill_binding_plan", manifest)
        self.assertIn("input_replay_plan", manifest)
        self.assertIn("golden_screenshot_plan", manifest)
        replay = json.loads((self.temp_project / DEFAULT_GAME_CREATION_INPUT_REPLAY_PATH).read_text(encoding="utf-8"))
        self.assertEqual(replay["schema"], "game_creation_input_replay")
        self.assertTrue(any(item["action"] == "capture_screenshot" for item in replay["steps"]))

    def test_apply_plan_wires_main_scene_gameplay_loop(self):
        apply_game_creation_plan(self.temp_project, title="Demo Runner", overwrite=True)

        main_scene = (self.temp_project / "scenes" / "Main.tscn").read_text(encoding="utf-8")
        main_script = (self.temp_project / "scripts" / "main_controller.gd").read_text(encoding="utf-8")
        hud_script = (self.temp_project / "scripts" / "hud_controller.gd").read_text(encoding="utf-8")
        design_doc = (self.temp_project / "docs" / "game_creation_design.md").read_text(encoding="utf-8")

        self.assertIn('path="res://scripts/main_controller.gd"', main_scene)
        self.assertIn('[node name="Ground" type="StaticBody2D" parent="."]', main_scene)
        self.assertIn('[node name="Camera2D" type="Camera2D" parent="."]', main_scene)
        self.assertIn('[node name="HUD" type="CanvasLayer" parent="."]', main_scene)
        self.assertIn('$Coin.collected.connect(_on_coin_collected)', main_script)
        self.assertIn('$Enemy.body_entered.connect(_on_enemy_body_entered)', main_script)
        self.assertIn('func set_health(current_health: int) -> void:', hud_script)
        self.assertIn("## Block Structure", design_doc)
        self.assertIn("Player Movement and Jump", design_doc)
        self.assertIn("## Skill Binding Plan", design_doc)
        self.assertIn("generate_movement_script", design_doc)

    def test_topdown_plan_returns_template_specific_contract(self):
        payload = build_game_creation_plan(
            self.temp_project,
            title="Arena Trial",
            template_id="topdown_action",
        )

        self.assertEqual(payload["status"], "passed")
        self.assertEqual(payload["template_id"], "topdown_action_2d")
        self.assertIn("melee_attack", payload["features"])
        self.assertIn("move_up", payload["input_map"])
        self.assertIn("attack", payload["input_map"])
        self.assertIn("input_map --> player_controller", payload["block_diagram"])
        self.assertIn("player_controller --> enemy_chase", payload["block_diagram"])
        self.assertIn("generate_ai_behavior", {item["skill_name"] for item in payload["skill_binding_plan"]})
        self.assertTrue(any(item["trigger"] == "attack input" for item in payload["godot_response_map"]))
        self.assertIn("scenes/Pickup.tscn", payload["artifact_paths"])
        self.assertIn("scripts/enemy_chaser.gd", payload["artifact_paths"])

    def test_topdown_apply_wires_arena_and_attack_loop(self):
        payload = apply_game_creation_plan(
            self.temp_project,
            title="Arena Trial",
            template_id="topdown_action_2d",
            overwrite=True,
        )

        main_scene = (self.temp_project / "scenes" / "Main.tscn").read_text(encoding="utf-8")
        project_file = (self.temp_project / "project.godot").read_text(encoding="utf-8")
        player_script = (self.temp_project / "scripts" / "player_controller.gd").read_text(encoding="utf-8")
        enemy_script = (self.temp_project / "scripts" / "enemy_chaser.gd").read_text(encoding="utf-8")
        design_doc = (self.temp_project / "docs" / "game_creation_design.md").read_text(encoding="utf-8")

        self.assertEqual(payload["template_id"], "topdown_action_2d")
        self.assertIn("scenes/Pickup.tscn", payload["generated_files"])
        self.assertIn("scripts/pickup_collectible.gd", payload["generated_files"])
        self.assertIn("scripts/enemy_chaser.gd", payload["generated_files"])
        self.assertIn('[node name="ArenaBounds" type="Area2D" parent="."]', main_scene)
        self.assertIn('path="res://scenes/Pickup.tscn"', main_scene)
        self.assertIn('move_up=', project_file)
        self.assertIn('attack=', project_file)
        self.assertIn('signal attacked', player_script)
        self.assertIn('Input.is_action_just_pressed("attack")', player_script)
        self.assertIn('target_path: NodePath', enemy_script)
        self.assertIn("Top-down", design_doc)
        self.assertIn("attack input", design_doc)

    def test_tower_defense_plan_returns_template_specific_contract(self):
        payload = build_game_creation_plan(
            self.temp_project,
            title="Defense Trial",
            template_id="tower_defense",
        )

        self.assertEqual(payload["status"], "passed")
        self.assertEqual(payload["template_id"], "tower_defense_2d")
        self.assertIn("tower_placement", payload["features"])
        self.assertIn("place_tower", payload["input_map"])
        self.assertIn("input_map --> placement_cursor", payload["block_diagram"])
        self.assertIn("placement_cursor --> tower_targeting", payload["block_diagram"])
        self.assertIn("tower_controller.gd", " ".join(payload["artifact_paths"]))
        self.assertTrue(any(item["trigger"] == "place_tower input" for item in payload["godot_response_map"]))
        self.assertIn("manage_game_data_tables", {item["skill_name"] for item in payload["skill_binding_plan"]})
        self.assertTrue(any(item.get("input") == "place_tower" for item in payload["input_replay_plan"]))
        self.assertIn("tower_defense_2d_main.png", payload["golden_screenshot_plan"]["baseline_path"])

    def test_tower_defense_apply_wires_defense_loop_and_review(self):
        payload = apply_game_creation_plan(
            self.temp_project,
            title="Defense Trial",
            template_id="tower_defense_2d",
            overwrite=True,
        )

        main_scene = (self.temp_project / "scenes" / "Main.tscn").read_text(encoding="utf-8")
        project_file = (self.temp_project / "project.godot").read_text(encoding="utf-8")
        player_script = (self.temp_project / "scripts" / "player_controller.gd").read_text(encoding="utf-8")
        tower_script = (self.temp_project / "scripts" / "tower_controller.gd").read_text(encoding="utf-8")
        enemy_script = (self.temp_project / "scripts" / "enemy_runner.gd").read_text(encoding="utf-8")
        review = build_game_creation_review(self.temp_project, write_reports=True)

        self.assertEqual(payload["template_id"], "tower_defense_2d")
        self.assertTrue(payload["layout_passed"])
        self.assertIn("scenes/Tower.tscn", payload["generated_files"])
        self.assertIn("scripts/tower_controller.gd", payload["generated_files"])
        self.assertIn("scripts/enemy_runner.gd", payload["generated_files"])
        self.assertIn('[node name="Base" type="Area2D" parent="."]', main_scene)
        self.assertIn('path="res://scenes/Tower.tscn"', main_scene)
        self.assertIn('place_tower=', project_file)
        self.assertIn('signal tower_placed', player_script)
        self.assertIn('Input.is_action_just_pressed("place_tower")', player_script)
        self.assertIn('signal fired', tower_script)
        self.assertIn('signal base_reached', enemy_script)
        self.assertEqual(review["status"], "passed")
        self.assertEqual(review["data_table_review"][0]["status"], "passed")
        self.assertEqual(review["data_table_review"][1]["schema"], "game_creation_input_replay")

    def test_template_migration_plan_reads_manifest_and_writes_report(self):
        apply_game_creation_plan(
            self.temp_project,
            title="Demo Runner",
            template_id="platformer_2d",
            overwrite=True,
        )

        payload = build_game_creation_template_migration(
            self.temp_project,
            to_template_id="arpg",
            write_report=True,
        )

        self.assertEqual(payload["schema_version"], "1.0")
        self.assertEqual(payload["status"], "passed")
        self.assertEqual(payload["from_template_id"], "platformer_2d")
        self.assertEqual(payload["to_template_id"], "arpg_2d")
        self.assertTrue(any(item["check_id"] == "input_actions" for item in payload["compatibility_checks"]))
        self.assertTrue(any(item["path"] == "project.godot" and item["operation"] == "overwrite" for item in payload["file_operations"]))
        self.assertTrue(any(item["path"] == "data_tables/game_creation/gameplay.json" for item in payload["data_migrations"]))
        self.assertTrue(any(item["step_id"] == "review_acceptance" for item in payload["validation_plan"]))
        self.assertTrue(any(item["step_id"] == "restore_source_template" for item in payload["rollback_plan"]))
        self.assertTrue((self.temp_project / DEFAULT_GAME_CREATION_TEMPLATE_MIGRATION_PATH).exists())

    def test_template_migration_blocks_missing_manifest_without_source_template(self):
        payload = build_game_creation_template_migration(
            self.temp_project,
            to_template_id="arpg",
        )

        self.assertEqual(payload["status"], "blocked")
        self.assertIn("missing manifest: data_tables/game_creation/game_creation_profile.json", payload["blocking_checks"])

    def test_arpg_plan_returns_template_specific_contract(self):
        payload = build_game_creation_plan(
            self.temp_project,
            title="Relic Trial",
            template_id="arpg",
        )

        self.assertEqual(payload["status"], "passed")
        self.assertEqual(payload["template_id"], "arpg_2d")
        self.assertIn("dodge_roll", payload["features"])
        self.assertIn("attack", payload["input_map"])
        self.assertIn("dodge", payload["input_map"])
        self.assertIn("input_map --> hero_controller", payload["block_diagram"])
        self.assertIn("hero_controller --> quest_relic", payload["block_diagram"])
        self.assertIn("relic_collectible.gd", " ".join(payload["artifact_paths"]))
        self.assertTrue(any(item["trigger"] == "dodge input" for item in payload["godot_response_map"]))
        self.assertTrue(any(item.get("input") == "dodge" for item in payload["input_replay_plan"]))
        self.assertIn("arpg_2d_main.png", payload["golden_screenshot_plan"]["baseline_path"])

    def test_arpg_apply_wires_quest_combat_loop_and_review(self):
        payload = apply_game_creation_plan(
            self.temp_project,
            title="Relic Trial",
            template_id="arpg_2d",
            overwrite=True,
        )

        main_scene = (self.temp_project / "scenes" / "Main.tscn").read_text(encoding="utf-8")
        project_file = (self.temp_project / "project.godot").read_text(encoding="utf-8")
        player_script = (self.temp_project / "scripts" / "player_controller.gd").read_text(encoding="utf-8")
        main_script = (self.temp_project / "scripts" / "main_controller.gd").read_text(encoding="utf-8")
        hud_script = (self.temp_project / "scripts" / "hud_controller.gd").read_text(encoding="utf-8")
        review = build_game_creation_review(self.temp_project, write_reports=True)

        self.assertEqual(payload["template_id"], "arpg_2d")
        self.assertTrue(payload["layout_passed"])
        self.assertIn("scripts/relic_collectible.gd", payload["generated_files"])
        self.assertIn('[node name="QuestArena" type="Area2D" parent="."]', main_scene)
        self.assertIn('path="res://scripts/relic_collectible.gd"', (self.temp_project / "scenes" / "Pickup.tscn").read_text(encoding="utf-8"))
        self.assertIn('attack=', project_file)
        self.assertIn('dodge=', project_file)
        self.assertIn('signal dodged', player_script)
        self.assertIn('Input.is_action_just_pressed("dodge")', player_script)
        self.assertIn('player.dodged.connect(_on_player_dodged)', main_script)
        self.assertIn('func set_quest(relics_collected: int) -> void:', hud_script)
        self.assertEqual(review["status"], "passed")
        self.assertEqual(review["data_table_review"][0]["status"], "passed")

    def test_roguelike_plan_returns_template_specific_contract(self):
        payload = build_game_creation_plan(
            self.temp_project,
            title="Dungeon Trial",
            template_id="roguelike",
        )

        self.assertEqual(payload["status"], "passed")
        self.assertEqual(payload["template_id"], "roguelike_2d")
        self.assertIn("floor_descent", payload["features"])
        self.assertIn("descend", payload["input_map"])
        self.assertIn("input_map --> hero_controller", payload["block_diagram"])
        self.assertIn("hero_controller --> loot_loop", payload["block_diagram"])
        self.assertIn("loot_collectible.gd", " ".join(payload["artifact_paths"]))
        self.assertTrue(any(item["trigger"] == "descend input" for item in payload["godot_response_map"]))
        self.assertTrue(any(item.get("input") == "descend" for item in payload["input_replay_plan"]))
        self.assertIn("roguelike_2d_main.png", payload["golden_screenshot_plan"]["baseline_path"])

    def test_roguelike_apply_wires_dungeon_loop_and_review(self):
        payload = apply_game_creation_plan(
            self.temp_project,
            title="Dungeon Trial",
            template_id="roguelike_2d",
            overwrite=True,
        )

        main_scene = (self.temp_project / "scenes" / "Main.tscn").read_text(encoding="utf-8")
        project_file = (self.temp_project / "project.godot").read_text(encoding="utf-8")
        player_script = (self.temp_project / "scripts" / "player_controller.gd").read_text(encoding="utf-8")
        main_script = (self.temp_project / "scripts" / "main_controller.gd").read_text(encoding="utf-8")
        hud_script = (self.temp_project / "scripts" / "hud_controller.gd").read_text(encoding="utf-8")
        gameplay = json.loads((self.temp_project / "data_tables" / "game_creation" / "gameplay.json").read_text(encoding="utf-8"))
        review = build_game_creation_review(self.temp_project, write_reports=True)

        self.assertEqual(payload["template_id"], "roguelike_2d")
        self.assertTrue(payload["layout_passed"])
        self.assertIn("scripts/loot_collectible.gd", payload["generated_files"])
        self.assertIn('[node name="DungeonRoom" type="Area2D" parent="."]', main_scene)
        self.assertIn('[node name="Stairs" type="Area2D" parent="."]', main_scene)
        self.assertIn('path="res://scripts/loot_collectible.gd"', (self.temp_project / "scenes" / "Pickup.tscn").read_text(encoding="utf-8"))
        self.assertIn('descend=', project_file)
        self.assertIn('signal descended', player_script)
        self.assertIn('Input.is_action_just_pressed("descend")', player_script)
        self.assertIn('player.descended.connect(_on_player_descended)', main_script)
        self.assertIn('func set_depth(depth: int) -> void:', hud_script)
        self.assertIn("dungeon", gameplay)
        self.assertEqual(review["status"], "passed")
        self.assertEqual(review["data_table_review"][0]["status"], "passed")

    def test_visual_novel_plan_returns_template_specific_contract(self):
        payload = build_game_creation_plan(
            self.temp_project,
            title="Story Trial",
            template_id="visual_novel",
        )

        self.assertEqual(payload["status"], "passed")
        self.assertEqual(payload["template_id"], "visual_novel_2d")
        self.assertIn("branching_choices", payload["features"])
        self.assertIn("advance_dialogue", payload["input_map"])
        self.assertIn("select_choice", payload["input_map"])
        self.assertIn("input_map --> reader_controller", payload["block_diagram"])
        self.assertIn("reader_controller --> choice_option", payload["block_diagram"])
        self.assertIn("choice_option.gd", " ".join(payload["artifact_paths"]))
        self.assertTrue(any(item["trigger"] == "select_choice input" for item in payload["godot_response_map"]))
        self.assertTrue(any(item.get("input") == "select_choice" for item in payload["input_replay_plan"]))
        self.assertIn("visual_novel_2d_main.png", payload["golden_screenshot_plan"]["baseline_path"])

    def test_visual_novel_apply_wires_dialogue_loop_and_review(self):
        payload = apply_game_creation_plan(
            self.temp_project,
            title="Story Trial",
            template_id="visual_novel_2d",
            overwrite=True,
        )

        main_scene = (self.temp_project / "scenes" / "Main.tscn").read_text(encoding="utf-8")
        project_file = (self.temp_project / "project.godot").read_text(encoding="utf-8")
        player_script = (self.temp_project / "scripts" / "player_controller.gd").read_text(encoding="utf-8")
        main_script = (self.temp_project / "scripts" / "main_controller.gd").read_text(encoding="utf-8")
        hud_script = (self.temp_project / "scripts" / "hud_controller.gd").read_text(encoding="utf-8")
        gameplay = json.loads((self.temp_project / "data_tables" / "game_creation" / "gameplay.json").read_text(encoding="utf-8"))
        review = build_game_creation_review(self.temp_project, write_reports=True)

        self.assertEqual(payload["template_id"], "visual_novel_2d")
        self.assertTrue(payload["layout_passed"])
        self.assertIn("scenes/Choice.tscn", payload["generated_files"])
        self.assertIn("scripts/choice_option.gd", payload["generated_files"])
        self.assertIn('[node name="Stage" type="Area2D" parent="."]', main_scene)
        self.assertIn('path="res://scenes/Choice.tscn"', main_scene)
        self.assertIn('advance_dialogue=', project_file)
        self.assertIn('select_choice=', project_file)
        self.assertIn('signal choice_selected', player_script)
        self.assertIn('Input.is_action_just_pressed("select_choice")', player_script)
        self.assertIn('player.choice_selected.connect(_on_choice_selected)', main_script)
        self.assertIn('func set_affinity(affinity: int) -> void:', hud_script)
        self.assertIn("dialogue", gameplay)
        self.assertEqual(review["status"], "passed")
        self.assertEqual(review["data_table_review"][0]["status"], "passed")

    def test_survival_crafting_plan_returns_template_specific_contract(self):
        payload = build_game_creation_plan(
            self.temp_project,
            title="Camp Trial",
            template_id="survival_crafting",
        )

        self.assertEqual(payload["status"], "passed")
        self.assertEqual(payload["template_id"], "survival_crafting_2d")
        self.assertIn("resource_gathering", payload["features"])
        self.assertIn("gather", payload["input_map"])
        self.assertIn("craft", payload["input_map"])
        self.assertIn("input_map --> survivor_controller", payload["block_diagram"])
        self.assertIn("resource_node --> campfire", payload["block_diagram"])
        self.assertIn("resource_node.gd", " ".join(payload["artifact_paths"]))
        self.assertTrue(any(item["trigger"] == "craft input" for item in payload["godot_response_map"]))
        self.assertTrue(any(item.get("input") == "craft" for item in payload["input_replay_plan"]))
        self.assertIn("survival_crafting_2d_main.png", payload["golden_screenshot_plan"]["baseline_path"])

    def test_survival_crafting_apply_wires_survival_loop_and_review(self):
        payload = apply_game_creation_plan(
            self.temp_project,
            title="Camp Trial",
            template_id="survival_crafting_2d",
            overwrite=True,
        )

        main_scene = (self.temp_project / "scenes" / "Main.tscn").read_text(encoding="utf-8")
        project_file = (self.temp_project / "project.godot").read_text(encoding="utf-8")
        player_script = (self.temp_project / "scripts" / "player_controller.gd").read_text(encoding="utf-8")
        main_script = (self.temp_project / "scripts" / "main_controller.gd").read_text(encoding="utf-8")
        hud_script = (self.temp_project / "scripts" / "hud_controller.gd").read_text(encoding="utf-8")
        gameplay = json.loads((self.temp_project / "data_tables" / "game_creation" / "gameplay.json").read_text(encoding="utf-8"))
        review = build_game_creation_review(self.temp_project, write_reports=True)

        self.assertEqual(payload["template_id"], "survival_crafting_2d")
        self.assertTrue(payload["layout_passed"])
        self.assertIn("scenes/Resource.tscn", payload["generated_files"])
        self.assertIn("scripts/campfire_controller.gd", payload["generated_files"])
        self.assertIn('[node name="Field" type="Area2D" parent="."]', main_scene)
        self.assertIn('path="res://scenes/Campfire.tscn"', main_scene)
        self.assertIn('gather=', project_file)
        self.assertIn('craft=', project_file)
        self.assertIn('signal gathered', player_script)
        self.assertIn('Input.is_action_just_pressed("craft")', player_script)
        self.assertIn('player.crafted.connect(_on_player_crafted)', main_script)
        self.assertIn('func set_campfire(is_built: bool) -> void:', hud_script)
        self.assertIn("survival", gameplay)
        self.assertEqual(review["status"], "passed")
        self.assertEqual(review["data_table_review"][0]["status"], "passed")

    def test_input_replay_generates_headless_script_and_report(self):
        apply_game_creation_plan(
            self.temp_project,
            title="Defense Trial",
            template_id="tower_defense_2d",
            overwrite=True,
        )

        payload = build_game_creation_input_replay(self.temp_project, write_report=True)

        self.assertEqual(payload["schema_version"], "1.0")
        self.assertEqual(payload["status"], "passed")
        self.assertEqual(payload["template_id"], "tower_defense_2d")
        self.assertEqual(payload["execution_mode"], "headless_script")
        self.assertEqual(payload["execution_status"], "script_generated")
        self.assertTrue(payload["script_path"].endswith("input_replay_tower_defense_2d.gd"))
        self.assertTrue((self.temp_project / payload["script_path"]).exists())
        self.assertTrue((self.temp_project / DEFAULT_GAME_CREATION_REPLAY_REPORT_PATH).exists())
        self.assertTrue(any(item["input"] == "place_tower" and item["status"] == "passed" for item in payload["action_checks"]))
        script = (self.temp_project / payload["script_path"]).read_text(encoding="utf-8")
        self.assertIn('Input.action_press("place_tower")', script)
        self.assertIn("tower_defense_runtime.png", script)
        self.assertIn('DisplayServer.get_name() != "headless"', script)
        self.assertIn('REPLAY_SCREENSHOT_CAPTURE=', script)

    def test_input_replay_can_execute_headless_script_and_capture_screenshot(self):
        apply_game_creation_plan(
            self.temp_project,
            title="Defense Trial",
            template_id="tower_defense_2d",
            overwrite=True,
        )
        fake_cli = ReplayGodotCLI(self.temp_project)

        payload = build_game_creation_input_replay(
            self.temp_project,
            write_report=True,
            execute_replay=True,
            godot_cli=fake_cli,
        )

        self.assertEqual(payload["status"], "passed")
        self.assertTrue(payload["executed"])
        self.assertEqual(payload["execution_status"], "passed")
        self.assertEqual(payload["execution_message"], "OK")
        self.assertTrue(payload["screenshot_exists"])
        self.assertEqual(len(fake_cli.calls), 1)
        self.assertTrue(fake_cli.calls[0]["script_path"].endswith("input_replay_tower_defense_2d.gd"))

    def test_input_replay_can_promote_runtime_screenshot_to_golden_baseline(self):
        apply_game_creation_plan(
            self.temp_project,
            title="Defense Trial",
            template_id="tower_defense_2d",
            overwrite=True,
        )
        fake_cli = ReplayGodotCLI(self.temp_project)

        payload = build_game_creation_input_replay(
            self.temp_project,
            write_report=True,
            execute_replay=True,
            promote_baseline=True,
            godot_cli=fake_cli,
        )

        baseline_path = self.temp_project / payload["baseline_path"]
        self.assertEqual(payload["status"], "passed")
        self.assertTrue(payload["baseline_promoted"])
        self.assertTrue(payload["baseline_exists"])
        self.assertTrue(payload["baseline_promoted_at"])
        self.assertEqual(payload["baseline_source_path"], "logs/test_artifacts/game_creation/tower_defense_runtime.png")
        self.assertEqual(payload["screenshot_capture_mode"], "viewport")
        self.assertEqual(payload["viewport_baseline_status"], "passed")
        self.assertTrue(payload["viewport_baseline_ready"])
        self.assertTrue(baseline_path.exists())
        self.assertEqual(baseline_path.read_bytes(), b"fake-png")

    def test_input_replay_reports_headless_fallback_screenshot_readiness(self):
        apply_game_creation_plan(
            self.temp_project,
            title="Defense Trial",
            template_id="tower_defense_2d",
            overwrite=True,
        )

        payload = build_game_creation_input_replay(
            self.temp_project,
            execute_replay=True,
            godot_cli=FallbackScreenshotReplayGodotCLI(self.temp_project),
        )

        self.assertEqual(payload["status"], "passed")
        self.assertEqual(payload["screenshot_capture_mode"], "fallback_headless")
        self.assertEqual(payload["viewport_baseline_status"], "warning")
        self.assertFalse(payload["viewport_baseline_ready"])
        self.assertIn("headless fallback", payload["viewport_baseline_message"])

    def test_input_replay_can_execute_with_viewport_render_mode(self):
        apply_game_creation_plan(
            self.temp_project,
            title="Defense Trial",
            template_id="tower_defense_2d",
            overwrite=True,
        )
        fake_cli = ViewportReplayGodotCLI(self.temp_project)

        payload = build_game_creation_input_replay(
            self.temp_project,
            execute_replay=True,
            replay_render_mode="viewport",
            godot_cli=fake_cli,
        )

        self.assertEqual(payload["status"], "passed")
        self.assertEqual(payload["execution_mode"], "viewport_script")
        self.assertEqual(payload["replay_render_mode"], "viewport")
        self.assertEqual(payload["screenshot_capture_mode"], "viewport")
        self.assertTrue(payload["viewport_baseline_ready"])
        self.assertFalse(fake_cli.calls[0]["headless"])

    def test_input_replay_blocks_baseline_promotion_without_runtime_screenshot(self):
        apply_game_creation_plan(
            self.temp_project,
            title="Defense Trial",
            template_id="tower_defense_2d",
            overwrite=True,
        )

        payload = build_game_creation_input_replay(
            self.temp_project,
            promote_baseline=True,
        )

        self.assertEqual(payload["status"], "blocked")
        self.assertFalse(payload["baseline_promoted"])
        self.assertIn("cannot promote missing runtime screenshot: logs/test_artifacts/game_creation/tower_defense_runtime.png", payload["blocking_checks"])

    def test_input_replay_blocks_failed_headless_execution(self):
        apply_game_creation_plan(
            self.temp_project,
            title="Defense Trial",
            template_id="tower_defense_2d",
            overwrite=True,
        )

        payload = build_game_creation_input_replay(
            self.temp_project,
            execute_replay=True,
            godot_cli=FailingReplayGodotCLI(self.temp_project),
        )

        self.assertEqual(payload["status"], "blocked")
        self.assertTrue(payload["executed"])
        self.assertEqual(payload["execution_status"], "blocked")
        self.assertIn("replay execution failed: boom", payload["blocking_checks"])

    def test_input_replay_blocks_missing_project_input_action(self):
        apply_game_creation_plan(
            self.temp_project,
            title="Defense Trial",
            template_id="tower_defense_2d",
            overwrite=True,
        )
        project_file = self.temp_project / "project.godot"
        project_file.write_text(project_file.read_text(encoding="utf-8").replace("place_tower=", "missing_place_tower="), encoding="utf-8")

        payload = build_game_creation_input_replay(self.temp_project, write_report=True)

        self.assertEqual(payload["status"], "blocked")
        self.assertTrue(payload["should_block"])
        self.assertIn("input action missing: place_tower", payload["blocking_checks"])
        self.assertFalse((self.temp_project / "logs" / "test_artifacts" / "game_creation" / "input_replay_tower_defense_2d.gd").exists())

    def test_apply_plan_skips_existing_files_without_overwrite(self):
        existing_script = self.temp_project / "scripts" / "player_controller.gd"
        existing_script.parent.mkdir(parents=True, exist_ok=True)
        existing_script.write_text("extends Node\n", encoding="utf-8")

        payload = apply_game_creation_plan(self.temp_project, title="Demo Runner", overwrite=False)

        self.assertIn("scripts/player_controller.gd", payload["skipped_files"])
        self.assertEqual(existing_script.read_text(encoding="utf-8"), "extends Node\n")

    def test_apply_plan_blocks_failed_governance_before_writes(self):
        with patch("agent_system.tools.game_creation_wizard._build_game_creation_governance_gate", return_value={
            "passed": False,
            "should_block": True,
            "blocking_checks": ["required_evidence"],
            "admission": {
                "change_type": "game_creation",
                "missing_evidence": ["tests"],
                "blocked_checks": ["required_evidence"],
            },
        }):
            payload = apply_game_creation_plan(self.temp_project, title="Demo Runner", overwrite=True)

        self.assertEqual(payload["status"], "blocked")
        self.assertTrue(payload["should_block"])
        self.assertTrue(payload["layout_passed"])
        self.assertFalse(payload["governance_passed"])
        self.assertIn("governance required_evidence", payload["governance_blocking_checks"])
        self.assertFalse((self.temp_project / "scenes" / "Main.tscn").exists())
        self.assertFalse((self.temp_project / DEFAULT_GAME_CREATION_MANIFEST_PATH).exists())

    def test_apply_plan_blocks_invalid_managed_layout_path(self):
        with patch("agent_system.tools.game_creation_wizard._scaffold_files", return_value={
            "scripts/bad name.gd": "extends Node\n",
        }):
            payload = apply_game_creation_plan(self.temp_project, title="Demo Runner", overwrite=True)

        self.assertEqual(payload["status"], "blocked")
        self.assertTrue(payload["should_block"])
        self.assertFalse(payload["layout_passed"])
        self.assertGreater(payload["layout_check_count"], 0)
        self.assertIn("layout scripts/bad name.gd", payload["layout_blocking_checks"][0])
        self.assertFalse((self.temp_project / "scripts" / "bad name.gd").exists())

    def test_build_plan_blocks_unknown_template(self):
        payload = build_game_creation_plan(self.temp_project, title="Demo Runner", template_id="unknown")

        self.assertEqual(payload["status"], "blocked")
        self.assertTrue(payload["should_block"])
        self.assertIn("unsupported template_id: unknown", payload["blocking_checks"])

    def test_scene_graph_audit_compares_manifest_to_generated_scenes(self):
        apply_game_creation_plan(self.temp_project, title="Demo Runner", overwrite=True)

        payload = build_scene_graph_audit(self.temp_project, write_report=True)

        self.assertEqual(payload["schema_version"], "1.0")
        self.assertEqual(payload["status"], "passed")
        self.assertTrue(payload["manifest_exists"])
        self.assertGreaterEqual(payload["scene_count"], 4)
        self.assertGreater(payload["node_count"], 0)
        self.assertTrue(any(item["module_id"] == "player_controller" for item in payload["module_checks"]))
        self.assertFalse(payload["missing_scripts"])
        self.assertFalse(payload["missing_nodes"])
        self.assertTrue((self.temp_project / DEFAULT_SCENE_GRAPH_AUDIT_PATH).exists())

    def test_scene_graph_audit_blocks_missing_manifest(self):
        payload = build_scene_graph_audit(self.temp_project)

        self.assertEqual(payload["status"], "blocked")
        self.assertTrue(payload["should_block"])
        self.assertIn("missing manifest", payload["blocking_checks"][0])

    def test_game_creation_review_summarizes_acceptance_and_modules(self):
        apply_game_creation_plan(self.temp_project, title="Demo Runner", overwrite=True)

        payload = build_game_creation_review(self.temp_project, write_reports=True)

        self.assertEqual(payload["schema_version"], "1.0")
        self.assertEqual(payload["status"], "passed")
        self.assertTrue(payload["ready_for_acceptance"])
        self.assertGreater(payload["acceptance_count"], 0)
        self.assertGreater(payload["module_count"], 0)
        self.assertEqual(payload["data_table_count"], 2)
        self.assertEqual(payload["passed_data_table_count"], 2)
        self.assertEqual(payload["acceptance_count"], payload["ready_acceptance_count"])
        self.assertEqual(payload["module_count"], payload["passed_module_count"])
        self.assertTrue((self.temp_project / DEFAULT_SCENE_GRAPH_AUDIT_PATH).exists())
        self.assertTrue((self.temp_project / DEFAULT_GAME_CREATION_REVIEW_PATH).exists())
        review_doc = (self.temp_project / DEFAULT_GAME_CREATION_REVIEW_DOC_PATH).read_text(encoding="utf-8")
        self.assertIn("Acceptance Review", review_doc)
        self.assertIn("## Acceptance Checklist", review_doc)
        self.assertIn("## Module Review", review_doc)
        self.assertIn("## Data Table Review", review_doc)

    def test_game_creation_review_blocks_invalid_gameplay_table(self):
        apply_game_creation_plan(self.temp_project, title="Demo Runner", overwrite=True)
        gameplay_path = self.temp_project / "data_tables" / "game_creation" / "gameplay.json"
        gameplay_path.write_text('{"schema":"wrong"}\n', encoding="utf-8")

        payload = build_game_creation_review(self.temp_project, write_reports=True)

        self.assertEqual(payload["status"], "blocked")
        self.assertTrue(payload["should_block"])
        self.assertEqual(payload["data_table_review"][0]["status"], "blocked")
        self.assertIn("schema mismatch", payload["blocking_checks"][0])

    def test_scene_graph_audit_can_use_live_snapshot_for_current_scene(self):
        apply_game_creation_plan(self.temp_project, title="Demo Runner", overwrite=True)
        snapshot = {
            "scene_path": "res://scenes/Main.tscn",
            "root_node": "Main",
            "nodes": [
                {"name": "Main", "path": "Main", "type": "Node2D", "script_path": "res://scripts/main_controller.gd"},
                {"name": "Player", "path": "Player", "type": "CharacterBody2D", "script_path": "res://scripts/player_controller.gd"},
                {"name": "HUD", "path": "HUD", "type": "CanvasLayer", "script_path": "res://scripts/hud_controller.gd"},
                {"name": "ScoreLabel", "path": "HUD/ScoreLabel", "type": "Label"},
                {"name": "Health", "path": "Health", "type": "Node", "script_path": "res://scripts/health_system.gd"},
            ],
            "source": "godot_plugin",
        }

        payload = build_scene_graph_audit(self.temp_project, scene_graph_snapshot=snapshot)

        live_main = next(item for item in payload["scene_graph"] if item["scene_path"] == "scenes/Main.tscn")
        self.assertTrue(payload["live_snapshot_used"])
        self.assertEqual(payload["live_snapshot_source"], "godot_plugin")
        self.assertEqual(payload["live_snapshot_scene_path"], "scenes/Main.tscn")
        self.assertEqual(payload["live_snapshot_node_count"], 5)
        self.assertEqual(live_main["snapshot_source"], "godot_plugin")
        self.assertTrue(any(item["node_found"] for item in payload["response_checks"]))

    def test_game_creation_review_records_live_snapshot_evidence(self):
        apply_game_creation_plan(self.temp_project, title="Demo Runner", overwrite=True)
        snapshot = {
            "scene_path": "res://scenes/Main.tscn",
            "root_node": "Main",
            "nodes": [
                {"name": "Main", "path": "Main", "type": "Node2D", "script_path": "res://scripts/main_controller.gd"},
                {"name": "Player", "path": "Player", "type": "CharacterBody2D", "script_path": "res://scripts/player_controller.gd"},
                {"name": "HUD", "path": "HUD", "type": "CanvasLayer", "script_path": "res://scripts/hud_controller.gd"},
                {"name": "ScoreLabel", "path": "HUD/ScoreLabel", "type": "Label"},
                {"name": "Health", "path": "Health", "type": "Node", "script_path": "res://scripts/health_system.gd"},
            ],
            "source": "godot_plugin",
        }

        payload = build_game_creation_review(
            self.temp_project,
            scene_graph_snapshot=snapshot,
            write_reports=True,
        )

        self.assertTrue(payload["audit_summary"]["live_snapshot_used"])
        self.assertEqual(payload["audit_summary"]["live_snapshot_source"], "godot_plugin")
        self.assertEqual(payload["audit_summary"]["live_snapshot_scene_path"], "scenes/Main.tscn")
        self.assertEqual(payload["audit_summary"]["live_snapshot_node_count"], 5)
        review_doc = (self.temp_project / DEFAULT_GAME_CREATION_REVIEW_DOC_PATH).read_text(encoding="utf-8")
        self.assertIn("Live Snapshot", review_doc)
        self.assertIn("source=godot_plugin", review_doc)


if __name__ == "__main__":
    unittest.main()

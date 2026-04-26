import shutil
import sys
import unittest
from pathlib import Path


project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from agent_system.tools.index_service import ProjectIndexService


class TestProjectIndexService(unittest.TestCase):
    def test_symbol_level_impact_tracks_class_and_signal_references(self):
        project_dir = project_root / "tests" / ".tmp_symbol_index"
        shutil.rmtree(project_dir, ignore_errors=True)
        try:
            scripts_dir = project_dir / "scripts"
            scenes_dir = project_dir / "scenes"
            scripts_dir.mkdir(parents=True, exist_ok=True)
            scenes_dir.mkdir(parents=True, exist_ok=True)

            (scripts_dir / "player_controller.gd").write_text(
                'extends Node\n'
                'class_name PlayerController\n'
                '\n'
                'signal jumped(height)\n'
                '\n'
                'func move_player() -> void:\n'
                '    pass\n',
                encoding="utf-8"
            )
            (scripts_dir / "spawn_manager.gd").write_text(
                'extends Node\n'
                'var controller: PlayerController = PlayerController.new()\n',
                encoding="utf-8"
            )
            (scenes_dir / "main_scene.tscn").write_text(
                '[gd_scene load_steps=1 format=3 uid="uid://main_scene_uid"]\n'
                '\n'
                '[connection signal="jumped" from="Player" to="HUD" method="_on_player_jumped"]\n',
                encoding="utf-8"
            )

            index_service = ProjectIndexService(str(project_dir))
            index_service.rebuild(force=True)

            class_impact = index_service.get_symbol_impact(
                "PlayerController",
                symbol_type="类",
                defining_path="scripts/player_controller.gd",
            )
            signal_refs = index_service.find_symbol_references(
                "jumped",
                symbol_type="信号",
                defining_path="scripts/player_controller.gd",
            )
        finally:
            shutil.rmtree(project_dir, ignore_errors=True)

        self.assertEqual(class_impact["reference_count"], 2)
        self.assertEqual(class_impact["impacted_files"], ["scripts/spawn_manager.gd"])
        self.assertEqual(signal_refs[0]["path"], "scenes/main_scene.tscn")
        self.assertEqual(signal_refs[0]["context"], "scene_connection_signal")


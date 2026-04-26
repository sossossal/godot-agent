import json
import shutil
import sys
import unittest
from pathlib import Path

from fastapi.testclient import TestClient


project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from agent_system.tools.scene_ownership import build_scene_ownership_board
from api_server.main import app


class SceneOwnershipBoardTestCase(unittest.TestCase):
    def setUp(self):
        self.project_dir = project_root / "tests" / ".tmp_scene_ownership_project"
        self.runtime_dir = project_root / "tests" / ".tmp_scene_ownership_runtime"
        shutil.rmtree(self.project_dir, ignore_errors=True)
        shutil.rmtree(self.runtime_dir, ignore_errors=True)
        self.project_dir.mkdir(parents=True, exist_ok=True)
        self.runtime_dir.mkdir(parents=True, exist_ok=True)
        self._write_scene_tree()

    def tearDown(self):
        shutil.rmtree(self.project_dir, ignore_errors=True)
        shutil.rmtree(self.runtime_dir, ignore_errors=True)

    def _write_scene_tree(self) -> None:
        level_dir = self.project_dir / "scenes" / "levels"
        ui_dir = self.project_dir / "scenes" / "ui"
        module_dir = self.project_dir / "agent_modules" / "scenes"
        level_manifest_dir = self.project_dir / "data_tables" / "levels"
        level_dir.mkdir(parents=True, exist_ok=True)
        ui_dir.mkdir(parents=True, exist_ok=True)
        module_dir.mkdir(parents=True, exist_ok=True)
        level_manifest_dir.mkdir(parents=True, exist_ok=True)
        (level_dir / "forest_gateway.tscn").write_text(
            '[gd_scene format=3]\n\n[node name="ForestGateway" type="Node2D"]\n',
            encoding="utf-8",
        )
        (ui_dir / "hud_root.tscn").write_text(
            '[gd_scene format=3]\n\n[node name="HudRoot" type="CanvasLayer"]\n',
            encoding="utf-8",
        )
        (module_dir / "combat_overlay.tscn").write_text(
            '[gd_scene format=3]\n\n[node name="CombatOverlay" type="Node"]\n',
            encoding="utf-8",
        )
        (level_manifest_dir / "forest_gateway.json").write_text(
            json.dumps({
                "schema_version": "1.1",
                "level_id": "forest_gateway",
                "scene_path": "res://scenes/levels/forest_gateway.tscn",
            }, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def test_board_warns_when_scene_owners_are_missing(self):
        payload = build_scene_ownership_board(
            self.project_dir,
            runtime_root=self.runtime_dir,
        )

        self.assertEqual(payload["schema_version"], "1.0")
        self.assertEqual(payload["status"], "warning")
        self.assertEqual(payload["scene_count"], 3)
        self.assertEqual(payload["missing_owner_count"], 3)
        level_entry = next(item for item in payload["scene_entries"] if item["scene_path"] == "res://scenes/levels/forest_gateway.tscn")
        self.assertTrue(level_entry["source_manifest_exists"])
        self.assertEqual(level_entry["scene_category"], "level")

    def test_filtered_snapshot_does_not_mark_existing_non_selected_entries_as_orphans(self):
        board_path = self.project_dir / "scenes" / "scene_ownership_board.json"
        board_path.parent.mkdir(parents=True, exist_ok=True)
        board_path.write_text(
            json.dumps({
                "schema_version": "1.0",
                "items": [
                    {
                        "scene_path": "res://scenes/levels/forest_gateway.tscn",
                        "scene_name": "forest_gateway",
                        "scene_category": "level",
                        "owner": "level_team",
                        "feature_id": "feature_level_polish",
                        "lock_state": "locked",
                    },
                    {
                        "scene_path": "res://scenes/ui/hud_root.tscn",
                        "scene_name": "hud_root",
                        "scene_category": "ui",
                        "owner": "ui_team",
                        "feature_id": "feature_ui_refresh",
                        "lock_state": "shared",
                    },
                ],
            }, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        payload = build_scene_ownership_board(
            self.project_dir,
            runtime_root=self.runtime_dir,
            scene_paths=["res://scenes/levels/forest_gateway.tscn"],
        )

        self.assertEqual(payload["scene_count"], 1)
        self.assertEqual(payload["orphan_count"], 0)
        self.assertEqual(payload["scene_entries"][0]["owner"], "level_team")

    def test_scene_ownership_api_claim_writes_board(self):
        client = TestClient(app)
        response = client.post(
            "/scene-ownership/manage",
            json={
                "project_path": str(self.project_dir),
                "action": "claim",
                "scene_paths": ["res://scenes/levels/forest_gateway.tscn"],
                "owner": "level_team",
                "feature_id": "feature_level_polish",
                "lock_state": "locked",
                "note": "terrain polish",
            },
        )

        board_path = self.project_dir / "scenes" / "scene_ownership_board.json"
        board_content = board_path.read_text(encoding="utf-8")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["schema_version"], "1.0")
        self.assertEqual(payload["locked_count"], 1)
        self.assertEqual(payload["assigned_count"], 1)
        self.assertEqual(payload["updated_count"], 1)
        self.assertIn('"owner": "level_team"', board_content)
        self.assertIn('"lock_state": "locked"', board_content)

    def test_scene_ownership_api_requires_owner_for_locked_claim(self):
        client = TestClient(app)
        response = client.post(
            "/scene-ownership/manage",
            json={
                "project_path": str(self.project_dir),
                "action": "claim",
                "scene_paths": ["res://scenes/levels/forest_gateway.tscn"],
                "lock_state": "locked",
            },
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("owner is required", response.json()["detail"])


if __name__ == "__main__":
    unittest.main()

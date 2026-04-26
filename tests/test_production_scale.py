import shutil
import sys
import unittest
from pathlib import Path

from fastapi.testclient import TestClient


project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from agent_system.tools.production_scale import build_production_readiness, list_production_scenarios
from api_server.main import app


class ProductionScaleTestCase(unittest.TestCase):
    def setUp(self):
        self.project_dir = project_root / "tests" / ".tmp_production_project"
        self.runtime_dir = project_root / "tests" / ".tmp_production_runtime"
        shutil.rmtree(self.project_dir, ignore_errors=True)
        shutil.rmtree(self.runtime_dir, ignore_errors=True)
        self.project_dir.mkdir(parents=True, exist_ok=True)
        self.runtime_dir.mkdir(parents=True, exist_ok=True)

    def tearDown(self):
        shutil.rmtree(self.project_dir, ignore_errors=True)
        shutil.rmtree(self.runtime_dir, ignore_errors=True)

    def _prepare_vertical_slice_paths(self):
        (self.project_dir / "project.godot").write_text("; test project\n", encoding="utf-8")
        for relative in ["scenes", "scripts", "data_tables", "assets/manifests"]:
            (self.project_dir / relative).mkdir(parents=True, exist_ok=True)
        (self.runtime_dir / "tests" / "baselines" / "performance").mkdir(parents=True, exist_ok=True)

    def test_scenario_catalog_declares_required_paths_and_evidence(self):
        catalog = list_production_scenarios()

        self.assertEqual(catalog["schema_version"], "1.0")
        self.assertEqual(catalog["default_scenario_id"], "vertical_slice_2d")
        scenario_ids = {item["scenario_id"] for item in catalog["items"]}
        self.assertIn("vertical_slice_2d", scenario_ids)
        self.assertIn("release_candidate", scenario_ids)
        vertical_slice = next(item for item in catalog["items"] if item["scenario_id"] == "vertical_slice_2d")
        self.assertIn("data_tables", vertical_slice["required_project_paths"])
        self.assertIn("quality_dashboard", vertical_slice["required_evidence"])

    def test_readiness_blocks_missing_required_paths(self):
        payload = build_production_readiness(
            self.project_dir,
            runtime_root=self.runtime_dir,
            scenario_id="vertical_slice_2d",
            evidence={"contract": True, "tests": True, "docs": True, "quality_dashboard": True},
            changed_paths=["scenes/Main.tscn"],
            mode="strict",
        )

        self.assertEqual(payload["schema_version"], "1.0")
        self.assertFalse(payload["passed"])
        self.assertTrue(payload["should_block"])
        self.assertIn("required_paths", payload["blocking_checks"])
        required_paths = next(stage for stage in payload["stages"] if stage["name"] == "required_paths")
        self.assertGreater(required_paths["issue_count"], 0)

    def test_readiness_passes_strict_when_required_paths_and_evidence_exist(self):
        self._prepare_vertical_slice_paths()

        payload = build_production_readiness(
            self.project_dir,
            runtime_root=self.runtime_dir,
            scenario_id="vertical_slice_2d",
            evidence={"contract": True, "tests": True, "docs": True, "quality_dashboard": True},
            changed_paths=["scenes/Main.tscn", "scripts/player_controller.gd", "README.md"],
            mode="strict",
        )

        self.assertTrue(payload["passed"])
        self.assertFalse(payload["should_block"])
        self.assertEqual(payload["exit_code"], 0)
        self.assertIn(payload["readiness_status"], {"passed", "warning"})
        self.assertNotIn("required_paths", payload["blocking_checks"])

    def test_readiness_accepts_recommended_directory_changed_paths(self):
        self._prepare_vertical_slice_paths()

        payload = build_production_readiness(
            self.project_dir,
            runtime_root=self.runtime_dir,
            scenario_id="vertical_slice_2d",
            evidence={"contract": True, "tests": True, "docs": True, "quality_dashboard": True},
            changed_paths=["scenes/", "scripts/", "data_tables/", "assets/manifests/", "tests/"],
            mode="strict",
        )

        self.assertNotIn("governance", payload["blocking_checks"])
        governance_stage = next(stage for stage in payload["stages"] if stage["name"] == "governance")
        self.assertIn(governance_stage["status"], {"passed", "warning"})
        self.assertNotIn("changed_paths", governance_stage["details"]["blocked_checks"])

    def test_unknown_scenario_blocks(self):
        payload = build_production_readiness(
            self.project_dir,
            runtime_root=self.runtime_dir,
            scenario_id="unknown",
            mode="strict",
        )

        self.assertFalse(payload["passed"])
        self.assertEqual(payload["readiness_status"], "blocked")
        self.assertIn("scenario", payload["blocking_checks"])

    def test_production_api_shape(self):
        client = TestClient(app)
        response = client.post(
            "/production/validate",
            json={
                "project_path": str(self.project_dir),
                "scenario_id": "vertical_slice_2d",
                "evidence": {"contract": True},
                "changed_paths": ["scenes/Main.tscn"],
                "mode": "advisory",
            },
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["schema_version"], "1.0")
        self.assertEqual(payload["project_path"], f"{self.project_dir.resolve().as_posix()}/")
        self.assertEqual(payload["scenario_id"], "vertical_slice_2d")
        self.assertTrue(any(stage["name"] == "required_paths" for stage in payload["stages"]))

    def test_production_scenarios_api_shape(self):
        client = TestClient(app)
        response = client.get("/production/scenarios", params={"project_path": "default"})

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["schema_version"], "1.0")
        self.assertEqual(payload["project_path"], "default")
        self.assertGreaterEqual(payload["scenario_count"], 3)


if __name__ == "__main__":
    unittest.main()

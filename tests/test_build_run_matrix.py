import json
import shutil
import sys
import unittest
from pathlib import Path

from fastapi.testclient import TestClient


project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from agent_system.tools.build_run_matrix import build_build_run_matrix
from api_server.main import app


class BuildRunMatrixTestCase(unittest.TestCase):
    def setUp(self):
        self.project_dir = project_root / "tests" / ".tmp_build_run_matrix_project"
        shutil.rmtree(self.project_dir, ignore_errors=True)
        self.project_dir.mkdir(parents=True, exist_ok=True)

    def tearDown(self):
        shutil.rmtree(self.project_dir, ignore_errors=True)

    def test_repository_sample_builds_matrix_with_build_gate_and_run_rows(self):
        payload = build_build_run_matrix(project_root, runtime_root=project_root)

        self.assertEqual(payload["schema_version"], "1.0")
        self.assertGreaterEqual(payload["row_count"], 8)
        row_ids = {row["row_id"] for row in payload["rows"]}
        self.assertIn("platform_delivery_baseline", row_ids)
        self.assertIn("non_live_regression", row_ids)
        self.assertIn("release_candidate_checklist", row_ids)
        self.assertIn("runtime_performance_sampling", row_ids)
        self.assertIn("build_run_matrix", payload["contract_versions"])
        self.assertIn("performance_summary", payload["contract_versions"])
        self.assertGreaterEqual(payload["platform_count"], 1)

    def test_matrix_blocks_when_platform_delivery_baseline_is_missing(self):
        payload = build_build_run_matrix(
            self.project_dir,
            runtime_root=self.project_dir,
            scenario_ids=["release_candidate"],
        )

        self.assertEqual(payload["status"], "blocked")
        self.assertTrue(payload["should_block"])
        self.assertIn("platform_delivery_baseline", payload["blocking_rows"])

    def test_matrix_includes_runtime_performance_sampling_evidence(self):
        profile_dir = self.project_dir / "logs" / "test_artifacts"
        profile_dir.mkdir(parents=True, exist_ok=True)
        profile_path = profile_dir / "performance_profile_matrix_sample.json"
        profile_path.write_text(
            json.dumps(
                {
                    "schema_version": "1.1",
                    "scene_path": "res://scenes/main_scene.tscn",
                    "metrics": {
                        "fps": 60,
                        "draw_call_count": 120,
                        "node_count": 80,
                        "memory_peak_mb": 128,
                        "frame_breakdown": [
                            {"stage": "render", "ms": 6.5},
                            {"stage": "script", "ms": 3.0},
                        ],
                        "memory_samples_mb": [120, 122, 124],
                    },
                    "budgets": {
                        "min_fps": 55,
                        "max_draw_call_count": 180,
                        "max_node_count": 120,
                        "max_memory_peak_mb": 160,
                    },
                },
                indent=2,
            ),
            encoding="utf-8",
        )

        payload = build_build_run_matrix(
            self.project_dir,
            runtime_root=self.project_dir,
            scenario_ids=["content_pipeline"],
        )

        rows = {row["row_id"]: row for row in payload["rows"]}
        performance_row = rows["runtime_performance_sampling"]
        self.assertEqual(performance_row["status"], "passed")
        self.assertTrue(performance_row["default_selected"])
        self.assertEqual(performance_row["details"]["profile_path"], "logs/test_artifacts/performance_profile_matrix_sample.json")
        self.assertEqual(performance_row["details"]["performance_summary"]["schema_version"], "1.1")
        self.assertEqual(performance_row["details"]["top_frame_stage"], "render")

    def test_build_run_matrix_api_shape(self):
        client = TestClient(app)
        response = client.post(
            "/build-run/matrix",
            json={
                "project_path": "default",
                "scenario_ids": ["release_candidate"],
                "mode": "advisory",
            },
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["schema_version"], "1.0")
        self.assertEqual(payload["project_path"], "default")
        self.assertEqual(payload["mode"], "advisory")
        self.assertIn("release_candidate", payload["selected_scenario_ids"])
        self.assertTrue(any(row["row_id"] == "release_candidate_checklist" for row in payload["rows"]))


if __name__ == "__main__":
    unittest.main()

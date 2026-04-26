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
        self.assertIn("build_run_matrix", payload["contract_versions"])
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

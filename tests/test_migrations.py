import json
import shutil
import sys
import unittest
from pathlib import Path


project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from agent_system.migrations import MigrationRunner


class MigrationRunnerTestCase(unittest.TestCase):
    def setUp(self):
        self.project_dir = project_root / "tests" / ".tmp_migrations_project"
        self.runtime_dir = project_root / "tests" / ".tmp_migrations_runtime"
        shutil.rmtree(self.project_dir, ignore_errors=True)
        shutil.rmtree(self.runtime_dir, ignore_errors=True)
        self.project_dir.mkdir(parents=True, exist_ok=True)
        self.runtime_dir.mkdir(parents=True, exist_ok=True)

    def tearDown(self):
        shutil.rmtree(self.project_dir, ignore_errors=True)
        shutil.rmtree(self.runtime_dir, ignore_errors=True)

    def test_status_reports_pending_setup_without_blocking(self):
        status = MigrationRunner(self.project_dir, runtime_root=self.runtime_dir).build_migration_status()

        self.assertEqual(status["schema_version"], "1.0")
        self.assertTrue(status["passed"])
        self.assertEqual(status["migration_count"], 4)
        self.assertGreaterEqual(status["pending_count"], 1)
        self.assertEqual(status["failed_count"], 0)
        self.assertTrue(any(item["migration_id"] == "template_manifest_1_0" for item in status["migrations"]))

    def test_apply_pending_only_creates_managed_directories(self):
        result = MigrationRunner(self.project_dir, runtime_root=self.runtime_dir).apply_pending()

        self.assertTrue(result["passed"])
        self.assertGreaterEqual(result["created_directory_count"], 3)
        self.assertTrue((self.project_dir / "agent_templates" / "genres").exists())
        self.assertTrue((self.project_dir / "data_tables").exists())
        self.assertTrue((self.project_dir / "telemetry" / "sessions").exists())
        self.assertTrue((self.runtime_dir / "tests" / "baselines" / "performance").exists())

    def test_invalid_project_template_manifest_blocks_migration(self):
        override_dir = self.project_dir / "agent_templates" / "genres"
        override_dir.mkdir(parents=True, exist_ok=True)
        (override_dir / "broken.json").write_text(
            json.dumps({
                "template_id": "broken",
                "display_name": "Broken",
                "game_genre": "Broken",
                "version": "1.0.0",
                "recommended_directories": ["../outside"],
                "starter_data_tables": [],
                "performance_budget": {"min_fps": 60},
            }),
            encoding="utf-8",
        )

        status = MigrationRunner(self.project_dir, runtime_root=self.runtime_dir).build_migration_status()

        self.assertFalse(status["passed"])
        self.assertEqual(status["failed_count"], 1)
        self.assertTrue(any(issue["code"] == "directory_escape" for issue in status["issues"]))


if __name__ == "__main__":
    unittest.main()

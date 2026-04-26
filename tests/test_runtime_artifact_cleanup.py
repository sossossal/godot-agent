import os
import shutil
import subprocess
import sys
import unittest
from pathlib import Path


project_root = Path(__file__).parent.parent
script_path = project_root / "tools" / "clean_runtime_artifacts.ps1"


@unittest.skipUnless(os.name == "nt", "PowerShell cleanup script test requires Windows")
class RuntimeArtifactCleanupScriptTestCase(unittest.TestCase):
    def setUp(self):
        self.repo_dir = project_root / "tests" / ".tmp_runtime_artifact_cleanup"
        shutil.rmtree(self.repo_dir, ignore_errors=True)
        self.repo_dir.mkdir(parents=True, exist_ok=True)
        (self.repo_dir / "logs" / "reports").mkdir(parents=True, exist_ok=True)
        (self.repo_dir / "logs" / "reports" / "report.md").write_text("report\n", encoding="utf-8")
        (self.repo_dir / "tests" / ".tmp_preview").mkdir(parents=True, exist_ok=True)
        (self.repo_dir / "tests" / ".tmp_preview" / "artifact.txt").write_text("temp\n", encoding="utf-8")
        dist_dir = self.repo_dir / "api_server" / "static" / "dist"
        release_dir = dist_dir / "web_20260414"
        release_dir.mkdir(parents=True, exist_ok=True)
        (release_dir / "index.html").write_text("<html></html>\n", encoding="utf-8")
        (dist_dir / "release_manifest.json").write_text("{}", encoding="utf-8")
        (dist_dir / "release_notes.md").write_text("# release\n", encoding="utf-8")
        (dist_dir / "qa_gate_report.md").write_text("# qa\n", encoding="utf-8")
        (dist_dir / "build.log").write_text("build\n", encoding="utf-8")
        (dist_dir / ".gitkeep").write_text("", encoding="utf-8")

    def tearDown(self):
        shutil.rmtree(self.repo_dir, ignore_errors=True)

    def _run_cleanup(self, *extra_args: str) -> subprocess.CompletedProcess[str]:
        completed = subprocess.run(
            [
                "powershell",
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(script_path),
                "-RepoRoot",
                str(self.repo_dir),
                *extra_args,
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        if completed.returncode != 0:
            self.fail(f"cleanup script failed: {completed.stdout}\n{completed.stderr}")
        return completed

    def test_preview_lists_release_output_artifacts_without_touching_gitkeep(self):
        completed = self._run_cleanup("-Preview")

        self.assertIn("api_server\\static\\dist\\web_20260414", completed.stdout)
        self.assertIn("api_server\\static\\dist\\release_manifest.json", completed.stdout)
        self.assertNotIn("api_server\\static\\dist\\.gitkeep", completed.stdout)
        self.assertTrue((self.repo_dir / "api_server" / "static" / "dist" / ".gitkeep").exists())

    def test_cleanup_removes_release_outputs_and_recreates_dist_anchor(self):
        self._run_cleanup()

        dist_dir = self.repo_dir / "api_server" / "static" / "dist"
        self.assertTrue((dist_dir / ".gitkeep").exists())
        self.assertFalse((dist_dir / "web_20260414").exists())
        self.assertFalse((dist_dir / "release_manifest.json").exists())
        self.assertFalse((dist_dir / "release_notes.md").exists())
        self.assertFalse((dist_dir / "qa_gate_report.md").exists())
        self.assertFalse((dist_dir / "build.log").exists())
        self.assertEqual([item.name for item in dist_dir.iterdir()], [".gitkeep"])
        self.assertTrue((self.repo_dir / "logs" / "backups").exists())
        self.assertTrue((self.repo_dir / "logs" / "reports").exists())
        self.assertTrue((self.repo_dir / "logs" / "test_artifacts").exists())
        self.assertFalse((self.repo_dir / "tests" / ".tmp_preview").exists())


if __name__ == "__main__":
    unittest.main()

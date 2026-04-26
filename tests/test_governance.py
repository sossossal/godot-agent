import shutil
import sys
import unittest
from pathlib import Path

from fastapi.testclient import TestClient


project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from agent_system.tools.governance import build_change_admission, build_governance_enforcement, build_governance_policy
from api_server.main import app


class GovernanceTestCase(unittest.TestCase):
    def setUp(self):
        self.project_dir = project_root / "tests" / ".tmp_governance_project"
        self.runtime_dir = project_root / "tests" / ".tmp_governance_runtime"
        shutil.rmtree(self.project_dir, ignore_errors=True)
        shutil.rmtree(self.runtime_dir, ignore_errors=True)
        self.project_dir.mkdir(parents=True, exist_ok=True)
        self.runtime_dir.mkdir(parents=True, exist_ok=True)

    def tearDown(self):
        shutil.rmtree(self.project_dir, ignore_errors=True)
        shutil.rmtree(self.runtime_dir, ignore_errors=True)

    def test_policy_declares_change_types_and_evidence_catalog(self):
        policy = build_governance_policy()

        self.assertEqual(policy["schema_version"], "1.0")
        change_types = {item["change_type"] for item in policy["change_types"]}
        self.assertIn("skill", change_types)
        self.assertIn("mcp_bridge", change_types)
        evidence_names = {item["name"] for item in policy["evidence_catalog"]}
        self.assertIn("tests", evidence_names)
        self.assertIn("security_notes", evidence_names)

    def test_admission_blocks_missing_required_evidence(self):
        admission = build_change_admission(
            self.project_dir,
            runtime_root=self.runtime_dir,
            change_type="skill",
            evidence={"contract": True},
            changed_paths=["agent_system/skills/resource/demo_skill.py"],
        )

        self.assertFalse(admission["passed"])
        self.assertEqual(admission["status"], "blocked")
        self.assertIn("required_evidence", admission["blocked_checks"])
        self.assertIn("tests", admission["missing_evidence"])
        self.assertIn("rollback", admission["missing_evidence"])

    def test_admission_passes_with_required_evidence_and_governed_paths(self):
        admission = build_change_admission(
            self.project_dir,
            runtime_root=self.runtime_dir,
            change_type="mcp_bridge",
            evidence={
                "tool_schema": True,
                "security_notes": True,
                "tests": True,
                "docs": True,
            },
            changed_paths=[
                "bridge/remote_mcp_server.py",
                "tests/test_remote_mcp_bridge.py",
                "README.md",
            ],
        )

        self.assertTrue(admission["passed"])
        self.assertNotIn("required_evidence", admission["blocked_checks"])
        self.assertEqual(admission["missing_evidence"], [])
        self.assertIn(admission["status"], {"passed", "warning"})

    def test_admission_accepts_directory_scoped_changed_paths(self):
        admission = build_change_admission(
            self.project_dir,
            runtime_root=self.runtime_dir,
            change_type="feature",
            evidence={
                "contract": True,
                "tests": True,
                "docs": True,
                "quality_dashboard": True,
            },
            changed_paths=["scenes/", "scripts/", "data_tables/", "assets/manifests/", "tests/"],
        )

        self.assertNotIn("changed_paths", admission["blocked_checks"])
        changed_paths_check = next(check for check in admission["checks"] if check["name"] == "changed_paths")
        self.assertEqual(changed_paths_check["status"], "passed")

    def test_admission_blocks_ungoverned_or_escaping_paths(self):
        admission = build_change_admission(
            self.project_dir,
            runtime_root=self.runtime_dir,
            change_type="feature",
            evidence={
                "contract": True,
                "tests": True,
                "docs": True,
                "quality_dashboard": True,
            },
            changed_paths=["../outside.txt", "random_root_file.txt"],
        )

        self.assertFalse(admission["passed"])
        self.assertIn("changed_paths", admission["blocked_checks"])
        self.assertTrue(any(issue["code"] == "path_escape" for issue in admission["checks"][2]["issues"]))
        self.assertTrue(any(issue["code"] == "ungoverned_path" for issue in admission["checks"][2]["issues"]))

    def test_admission_uses_layout_rules_for_managed_paths(self):
        admission = build_change_admission(
            self.project_dir,
            runtime_root=self.runtime_dir,
            change_type="data_table",
            evidence={
                "schema": True,
                "preview_or_diff": True,
                "layout": True,
                "migration_plan": True,
                "tests": True,
                "docs": True,
            },
            changed_paths=["data_tables/Bad Name.csv"],
        )

        self.assertFalse(admission["passed"])
        self.assertIn("changed_paths", admission["blocked_checks"])
        self.assertTrue(any(issue["code"] == "whitespace_name" for issue in admission["checks"][2]["issues"]))

    def test_strict_enforcement_returns_blocking_exit_code(self):
        enforcement = build_governance_enforcement(
            self.project_dir,
            runtime_root=self.runtime_dir,
            change_type="skill",
            evidence={"contract": True},
            changed_paths=["agent_system/skills/resource/demo_skill.py"],
            mode="strict",
        )

        self.assertEqual(enforcement["schema_version"], "1.0")
        self.assertFalse(enforcement["passed"])
        self.assertTrue(enforcement["should_block"])
        self.assertEqual(enforcement["exit_code"], 1)
        self.assertIn("required_evidence", enforcement["blocking_checks"])

    def test_advisory_enforcement_does_not_block_exit_code(self):
        enforcement = build_governance_enforcement(
            self.project_dir,
            runtime_root=self.runtime_dir,
            change_type="skill",
            evidence={"contract": True},
            changed_paths=["agent_system/skills/resource/demo_skill.py"],
            mode="advisory",
        )

        self.assertTrue(enforcement["passed"])
        self.assertFalse(enforcement["should_block"])
        self.assertEqual(enforcement["exit_code"], 0)
        self.assertIn("required_evidence", enforcement["blocking_checks"])

    def test_strict_enforcement_can_fail_on_warnings(self):
        enforcement = build_governance_enforcement(
            self.project_dir,
            runtime_root=self.runtime_dir,
            change_type="mcp_bridge",
            evidence={
                "tool_schema": True,
                "security_notes": True,
                "tests": True,
                "docs": True,
            },
            changed_paths=["bridge/remote_mcp_server.py"],
            mode="strict",
            fail_on_warnings=True,
        )

        self.assertFalse(enforcement["passed"])
        self.assertEqual(enforcement["exit_code"], 1)
        self.assertIn("quality_dashboard", enforcement["blocking_checks"])

    def test_governance_policy_api_shape(self):
        client = TestClient(app)
        response = client.get("/governance/policy", params={"project_path": "default"})

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["schema_version"], "1.0")
        self.assertTrue(any(item["change_type"] == "template" for item in payload["change_types"]))

    def test_governance_admission_api_blocks_missing_evidence(self):
        client = TestClient(app)
        response = client.post(
            "/governance/admission",
            json={
                "project_path": str(self.project_dir),
                "change_type": "portal",
                "evidence": {"api_contract": True},
                "changed_paths": ["api_server/static/index.html"],
            },
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["schema_version"], "1.0")
        self.assertEqual(payload["project_path"], f"{self.project_dir.resolve().as_posix()}/")
        self.assertFalse(payload["passed"])
        self.assertIn("ui_wiring", payload["missing_evidence"])

    def test_governance_enforce_api_returns_exit_code_contract(self):
        client = TestClient(app)
        response = client.post(
            "/governance/enforce",
            json={
                "project_path": str(self.project_dir),
                "change_type": "portal",
                "evidence": {"api_contract": True},
                "changed_paths": ["api_server/static/index.html"],
                "mode": "strict",
            },
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["schema_version"], "1.0")
        self.assertEqual(payload["project_path"], f"{self.project_dir.resolve().as_posix()}/")
        self.assertTrue(payload["should_block"])
        self.assertEqual(payload["exit_code"], 1)
        self.assertIn("required_evidence", payload["blocking_checks"])


if __name__ == "__main__":
    unittest.main()

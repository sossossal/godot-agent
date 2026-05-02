import json
import shutil
import sys
import unittest
from pathlib import Path

from fastapi.testclient import TestClient


project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from agent_system.tools.asset_review import build_asset_review_workflow
from api_server.main import app


class AssetReviewWorkflowTestCase(unittest.TestCase):
    def setUp(self):
        self.project_dir = project_root / "tests" / ".tmp_asset_review_project"
        self.runtime_dir = project_root / "tests" / ".tmp_asset_review_runtime"
        shutil.rmtree(self.project_dir, ignore_errors=True)
        shutil.rmtree(self.runtime_dir, ignore_errors=True)
        self.project_dir.mkdir(parents=True, exist_ok=True)
        self.runtime_dir.mkdir(parents=True, exist_ok=True)

    def tearDown(self):
        shutil.rmtree(self.project_dir, ignore_errors=True)
        shutil.rmtree(self.runtime_dir, ignore_errors=True)

    def _write_outsource_manifest(self) -> None:
        manifest_dir = self.project_dir / "assets" / "manifests"
        package_dir = self.project_dir / "assets" / "packages" / "outsource"
        manifest_dir.mkdir(parents=True, exist_ok=True)
        package_dir.mkdir(parents=True, exist_ok=True)
        (package_dir / "npc_vendor_delivery.zip").write_bytes(b"managed-zip")
        (manifest_dir / "outsource_assets.json").write_text(
            json.dumps({
                "schema_version": "1.1",
                "asset_type": "outsource",
                "entries": [{
                    "asset_id": "npc_vendor_delivery",
                    "source_path": "res://raw_assets/outsource/npc_vendor_delivery.zip",
                    "target_path": "res://assets/packages/outsource/npc_vendor_delivery.zip",
                    "source_tool": "outsource_delivery",
                    "package_version": "v2026_04",
                    "license_name": "work_for_hire",
                    "source_dependency_paths": ["res://raw_assets/outsource/npc_vendor_terms.pdf"],
                    "target_dependency_paths": ["res://assets/packages/outsource/npc_vendor_terms.pdf"],
                    "tags": ["delivery", "vendor"],
                }],
            }, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def test_workflow_warns_when_assets_are_pending_review(self):
        self._write_outsource_manifest()

        payload = build_asset_review_workflow(
            self.project_dir,
            runtime_root=self.runtime_dir,
            asset_type="outsource",
        )

        self.assertEqual(payload["schema_version"], "1.0")
        self.assertEqual(payload["status"], "warning")
        self.assertEqual(payload["pending_review_count"], 1)
        self.assertEqual(payload["review_entries"][0]["asset_id"], "npc_vendor_delivery")
        self.assertEqual(payload["review_entries"][0]["review_status"], "pending_review")
        self.assertEqual(payload["provenance_issue_count"], 0)
        self.assertEqual(payload["license_coverage_ratio"], 1.0)
        self.assertEqual(payload["provenance_summary"]["source_dependency_count"], 1)
        self.assertEqual(payload["review_entries"][0]["source_dependency_paths"], ["res://raw_assets/outsource/npc_vendor_terms.pdf"])

    def test_workflow_reports_provenance_gaps(self):
        manifest_dir = self.project_dir / "assets" / "manifests"
        manifest_dir.mkdir(parents=True, exist_ok=True)
        (manifest_dir / "outsource_assets.json").write_text(
            json.dumps({
                "schema_version": "1.1",
                "asset_type": "outsource",
                "entries": [{
                    "asset_id": "incomplete_delivery",
                    "target_path": "res://assets/packages/outsource/incomplete_delivery.zip",
                    "tags": ["delivery"],
                }],
            }, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        payload = build_asset_review_workflow(
            self.project_dir,
            runtime_root=self.runtime_dir,
            asset_type="outsource",
        )

        self.assertEqual(payload["status"], "warning")
        self.assertEqual(payload["provenance_issue_count"], 1)
        self.assertEqual(payload["license_coverage_ratio"], 0.0)
        self.assertEqual(payload["provenance_summary"]["missing_license_assets"], ["incomplete_delivery"])
        self.assertIn("asset_provenance", payload["warning_checks"])

    def test_asset_review_api_apply_writes_review_board(self):
        self._write_outsource_manifest()

        client = TestClient(app)
        response = client.post(
            "/asset-reviews/manage",
            json={
                "project_path": str(self.project_dir),
                "action": "apply",
                "asset_type": "outsource",
                "asset_manifest_path": "assets/manifests/outsource_assets.json",
                "review_manifest_path": "assets/manifests/asset_review_board.json",
                "asset_ids": ["npc_vendor_delivery"],
                "reviewer": "art_lead",
                "review_status": "approved",
                "review_note": "ready for merge",
            },
        )

        review_board_path = self.project_dir / "assets" / "manifests" / "asset_review_board.json"
        review_board_exists = review_board_path.exists()
        review_board_content = review_board_path.read_text(encoding="utf-8") if review_board_exists else ""

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["schema_version"], "1.0")
        self.assertEqual(payload["status"], "passed")
        self.assertEqual(payload["approved_count"], 1)
        self.assertEqual(payload["updated_count"], 1)
        self.assertTrue(review_board_exists)
        self.assertIn('"review_status": "approved"', review_board_content)
        self.assertIn('"reviewer": "art_lead"', review_board_content)

    def test_asset_review_api_requires_reviewer_for_approval(self):
        self._write_outsource_manifest()

        client = TestClient(app)
        response = client.post(
            "/asset-reviews/manage",
            json={
                "project_path": str(self.project_dir),
                "action": "apply",
                "asset_type": "outsource",
                "asset_manifest_path": "assets/manifests/outsource_assets.json",
                "review_status": "approved",
            },
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("reviewer is required", response.json()["detail"])


if __name__ == "__main__":
    unittest.main()

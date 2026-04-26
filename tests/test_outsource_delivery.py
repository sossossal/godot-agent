import json
import shutil
import sys
import unittest
from pathlib import Path

from fastapi.testclient import TestClient


project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from agent_system.tools.outsource_delivery import build_outsource_delivery_gate
from api_server.main import app


class OutsourceDeliveryGateTestCase(unittest.TestCase):
    def setUp(self):
        self.project_dir = project_root / "tests" / ".tmp_outsource_delivery_project"
        self.runtime_dir = project_root / "tests" / ".tmp_outsource_delivery_runtime"
        shutil.rmtree(self.project_dir, ignore_errors=True)
        shutil.rmtree(self.runtime_dir, ignore_errors=True)
        self.project_dir.mkdir(parents=True, exist_ok=True)
        self.runtime_dir.mkdir(parents=True, exist_ok=True)

    def tearDown(self):
        shutil.rmtree(self.project_dir, ignore_errors=True)
        shutil.rmtree(self.runtime_dir, ignore_errors=True)

    def _write_valid_delivery(self) -> None:
        manifest_dir = self.project_dir / "assets" / "manifests"
        package_dir = self.project_dir / "assets" / "packages" / "outsource"
        raw_dir = self.project_dir / "raw_assets" / "outsource"
        manifest_dir.mkdir(parents=True, exist_ok=True)
        package_dir.mkdir(parents=True, exist_ok=True)
        raw_dir.mkdir(parents=True, exist_ok=True)

        (raw_dir / "npc_vendor_delivery.zip").write_bytes(b"source-zip")
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
                    "estimated_memory_mb": 64.0,
                    "tags": ["delivery", "vendor"],
                    "notes": "NPC vendor package",
                }],
            }, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def test_gate_blocks_when_manifest_is_missing(self):
        payload = build_outsource_delivery_gate(self.project_dir, runtime_root=self.runtime_dir)

        self.assertEqual(payload["schema_version"], "1.0")
        self.assertEqual(payload["status"], "blocked")
        self.assertTrue(payload["should_block"])
        self.assertIn("manifest_available", payload["blocking_checks"])

    def test_gate_passes_when_manifest_and_package_are_ready(self):
        self._write_valid_delivery()

        payload = build_outsource_delivery_gate(
            self.project_dir,
            runtime_root=self.runtime_dir,
            required_license_names=["work_for_hire"],
        )

        self.assertEqual(payload["status"], "passed")
        self.assertFalse(payload["should_block"])
        self.assertEqual(payload["delivery_count"], 1)
        self.assertEqual(payload["passed_delivery_count"], 1)
        self.assertEqual(payload["manifest_asset_type"], "outsource")
        self.assertEqual(payload["deliveries"][0]["asset_id"], "npc_vendor_delivery")
        self.assertTrue(payload["deliveries"][0]["target_exists"])

    def test_outsource_delivery_gate_api_shape(self):
        self._write_valid_delivery()

        client = TestClient(app)
        response = client.post(
            "/outsource-delivery/gate",
            json={
                "project_path": str(self.project_dir),
                "required_license_names": ["work_for_hire"],
                "mode": "strict",
            },
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["schema_version"], "1.0")
        self.assertEqual(payload["project_path"], f"{self.project_dir.resolve().as_posix()}/")
        self.assertEqual(payload["manifest_path"], "assets/manifests/outsource_assets.json")
        self.assertEqual(payload["package_root"], "assets/packages/outsource")
        self.assertEqual(payload["status"], "passed")


if __name__ == "__main__":
    unittest.main()

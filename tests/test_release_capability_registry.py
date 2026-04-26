import json
import shutil
import sys
import unittest
from pathlib import Path


project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from agent_system.tools.release_capability_registry import (  # noqa: E402
    build_release_capability_registry,
    build_release_capability_registry_report,
)


class ReleaseCapabilityRegistryTestCase(unittest.TestCase):
    def setUp(self):
        self.project_dir = project_root / "tests" / ".tmp_release_capability_registry_project"
        shutil.rmtree(self.project_dir, ignore_errors=True)
        self.project_dir.mkdir(parents=True, exist_ok=True)

    def tearDown(self):
        shutil.rmtree(self.project_dir, ignore_errors=True)

    def test_repo_registry_is_valid(self):
        payload = build_release_capability_registry(project_root)

        self.assertEqual(payload["status"], "passed")
        self.assertTrue(payload["registry_exists"])
        self.assertGreaterEqual(payload["capability_count"], 10)
        self.assertIn("command", payload["surface_counts"])
        self.assertIn("gateway_method", payload["surface_counts"])
        self.assertGreaterEqual(payload["request_auth_count"], 1)
        live_summary = next(
            item for item in payload["capabilities"]
            if item["capability_id"] == "release_live_ci_summary_read"
        )
        self.assertIn("release_artifact_manifest", live_summary["artifact_contracts"])
        self.assertIn("/release-artifact-manifest", live_summary["entrypoints"])
        live_summary_consumers = [
            item for item in payload["capabilities"]
            if "release_live_ci_summary" in item["artifact_contracts"]
        ]
        self.assertGreaterEqual(len(live_summary_consumers), 1)
        for item in live_summary_consumers:
            self.assertIn("release_artifact_manifest", item["artifact_contracts"])
        for item in live_summary_consumers:
            if item["capability_id"].endswith("_read"):
                self.assertIn("/release-artifact-manifest", item["entrypoints"])

    def test_missing_registry_returns_warning(self):
        payload = build_release_capability_registry(
            self.project_dir,
            registry_path="deployment/release_capability_registry.json",
        )

        self.assertEqual(payload["status"], "warning")
        self.assertFalse(payload["registry_exists"])
        self.assertEqual(payload["capability_count"], 0)
        self.assertIn("release capability registry missing", payload["summary"])

    def test_report_contains_capability_details(self):
        manifest_path = self.project_dir / "deployment" / "release_capability_registry.json"
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        manifest_path.write_text(
            json.dumps(
                {
                    "schema_version": "1.0",
                    "registry_id": "test_registry",
                    "capabilities": [
                        {
                            "capability_id": "release_plan_read",
                            "label": "Release Plan Read",
                            "group": "release_control_plane",
                            "surface_types": ["command", "gateway_method"],
                            "risk_level": "medium",
                            "requires_actor": False,
                            "requires_request_auth": False,
                            "default_enabled": True,
                            "optional_heavy": False,
                            "sandbox_profile": "read_only",
                            "artifact_contracts": ["release_promotion_plan"],
                            "entrypoints": ["/release-promotion/plan"],
                            "owners": ["producer"],
                        },
                        {
                            "capability_id": "portal_click_smoke_run",
                            "label": "Portal Click Smoke",
                            "group": "release_runtime",
                            "surface_types": ["tool", "command"],
                            "risk_level": "high",
                            "requires_actor": False,
                            "requires_request_auth": False,
                            "default_enabled": False,
                            "optional_heavy": True,
                            "sandbox_profile": "browser_automation",
                            "artifact_contracts": ["release_live_ci_summary", "release_artifact_manifest"],
                            "entrypoints": [
                                "python tools/run_portal_browser_click_smoke.py",
                                "/release-artifact-manifest",
                            ],
                            "owners": ["qa_lead"],
                        },
                    ],
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

        payload = build_release_capability_registry(self.project_dir)
        report = build_release_capability_registry_report(payload)

        self.assertEqual(payload["status"], "passed")
        self.assertIn("# Release Capability Registry", report)
        self.assertIn("`release_plan_read` [passed]", report)
        self.assertIn("sandbox=browser_automation", report)
        self.assertIn("contracts=release_live_ci_summary,release_artifact_manifest", report)
        self.assertIn("Groups: release_control_plane=1, release_runtime=1", report)

    def test_live_summary_capability_requires_artifact_manifest_contract(self):
        manifest_path = self.project_dir / "deployment" / "release_capability_registry.json"
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        manifest_path.write_text(
            json.dumps(
                {
                    "schema_version": "1.0",
                    "registry_id": "test_registry",
                    "capabilities": [
                        {
                            "capability_id": "release_delivery_readiness_read",
                            "label": "Release Delivery Readiness",
                            "group": "release_governance",
                            "surface_types": ["command", "gateway_method"],
                            "risk_level": "medium",
                            "requires_actor": False,
                            "requires_request_auth": False,
                            "default_enabled": True,
                            "optional_heavy": False,
                            "sandbox_profile": "read_only",
                            "artifact_contracts": ["release_delivery_readiness", "release_live_ci_summary"],
                            "entrypoints": ["/release-delivery-readiness"],
                            "owners": ["ops"],
                        },
                    ],
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

        payload = build_release_capability_registry(self.project_dir)
        capability = payload["capabilities"][0]

        self.assertEqual(payload["status"], "warning")
        self.assertIn("release_artifact_manifest", capability["missing_fields"])
        self.assertIn("release_artifact_manifest_entrypoint", capability["missing_fields"])
        self.assertIn("release_artifact_manifest", payload["recommendations"][0])


if __name__ == "__main__":
    unittest.main()

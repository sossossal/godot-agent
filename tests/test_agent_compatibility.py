import sys
import unittest
from pathlib import Path

from fastapi.testclient import TestClient


project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from agent_system.tools.agent_compatibility import build_agent_compatibility_matrix, list_agent_provider_profiles
from api_server.main import app


class AgentCompatibilityTestCase(unittest.TestCase):
    def test_provider_catalog_declares_supported_agent_profiles(self):
        catalog = list_agent_provider_profiles()

        self.assertEqual(catalog["schema_version"], "1.0")
        provider_ids = {item["provider_id"] for item in catalog["items"]}
        self.assertIn("codex", provider_ids)
        self.assertIn("openai_api", provider_ids)
        self.assertIn("local_llm", provider_ids)
        self.assertIn("schema_version", catalog["handoff_contract"]["required_output_fields"])
        self.assertIn("changed_paths", catalog["handoff_contract"]["required_output_fields"])

    def test_matrix_passes_for_default_registered_providers(self):
        matrix = build_agent_compatibility_matrix(project_root, runtime_root=project_root)

        self.assertEqual(matrix["schema_version"], "1.0")
        self.assertTrue(matrix["passed"])
        self.assertEqual(matrix["status"], "passed")
        self.assertGreaterEqual(matrix["provider_count"], 5)
        surface_names = {surface["name"] for surface in matrix["surfaces"]}
        self.assertIn("contracts", surface_names)
        self.assertIn("mcp_stdio", surface_names)
        self.assertIn("production", surface_names)

    def test_matrix_blocks_unknown_provider_profile(self):
        matrix = build_agent_compatibility_matrix(project_root, runtime_root=project_root, providers=["codex", "unknown"])

        self.assertFalse(matrix["passed"])
        self.assertEqual(matrix["status"], "blocked")
        self.assertIn("unknown", matrix["blocked_providers"])
        unknown = next(provider for provider in matrix["providers"] if provider["provider_id"] == "unknown")
        self.assertTrue(any(issue["code"] == "unknown_provider" for issue in unknown["issues"]))

    def test_agent_provider_api_shape(self):
        client = TestClient(app)
        response = client.get("/agent-compat/providers", params={"project_path": "default"})

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["schema_version"], "1.0")
        self.assertEqual(payload["project_path"], "default")
        self.assertGreaterEqual(payload["provider_count"], 5)

    def test_agent_matrix_api_filters_provider(self):
        client = TestClient(app)
        response = client.post(
            "/agent-compat/matrix",
            json={"project_path": "default", "providers": ["codex"]},
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["schema_version"], "1.0")
        self.assertEqual(payload["project_path"], "default")
        self.assertEqual(payload["provider_count"], 1)
        self.assertEqual(payload["providers"][0]["provider_id"], "codex")
        self.assertTrue(payload["passed"])


if __name__ == "__main__":
    unittest.main()

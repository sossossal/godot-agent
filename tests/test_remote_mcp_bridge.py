import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from fastapi.testclient import TestClient


project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from agent_system.models import Task, TaskStatus
from api_server.main import app as api_app
from bridge import remote_mcp_server


class RemoteMcpBridgeTestCase(unittest.TestCase):
    def test_manifest_reuses_stdio_tool_contracts(self):
        manifest = remote_mcp_server.build_remote_bridge_manifest()

        self.assertEqual(manifest["schema_version"], "1.0")
        tool_names = {tool["name"] for tool in manifest["tools"]}
        self.assertEqual(tool_names, {
            "godot_make",
            "godot_status",
            "godot_capture",
            "godot_production_validate",
            "godot_agent_compat",
            "godot_create_game_plan",
            "godot_apply_game_plan",
            "godot_audit_game_scene_graph",
            "godot_review_game_creation",
            "godot_plan_game_template_migration",
        })

    def test_remote_bridge_manifest_endpoint(self):
        client = TestClient(remote_mcp_server.app)
        response = client.get("/mcp/manifest")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["transport"], "http")
        self.assertEqual(payload["endpoints"]["tool_call_pattern"], "/tools/{tool_name}")

    def test_remote_bridge_calls_godot_make(self):
        task = Task(prompt="demo", status=TaskStatus.SUCCESS)
        task.add_log("SUCCESS: demo done")
        fake_router = SimpleNamespace(execute=lambda prompt, confirm=True: task)

        with patch("bridge.remote_mcp_server.get_router", return_value=fake_router):
            client = TestClient(remote_mcp_server.app)
            response = client.post("/tools/godot_make", json={"arguments": {"prompt": "demo"}})

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertFalse(payload["is_error"])
        self.assertEqual(payload["structured_content"]["status"], "success")
        self.assertEqual(payload["tool_name"], "godot_make")

    def test_api_remote_mcp_manifest_shape(self):
        client = TestClient(api_app)
        response = client.get("/mcp/remote-manifest", params={"project_path": "default"})

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["schema_version"], "1.0")
        self.assertEqual(payload["transport"], "http")
        self.assertTrue(payload["launch_command"].endswith('remote_mcp_server.py"'))
        self.assertTrue(any(tool["name"] == "godot_status" for tool in payload["tools"]))


if __name__ == "__main__":
    unittest.main()

"""
CLI 行为测试
"""

import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

# 添加项目路径
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from agent_system import cli


class TestCLI(unittest.TestCase):
    @patch("agent_system.cli.cmd_chat")
    @patch("agent_system.cli.GodotAgentRouter")
    @patch("agent_system.cli.setup_io")
    def test_chat_command_dispatches(self, _mock_setup_io, mock_router_cls, mock_cmd_chat):
        mock_router = mock_router_cls.return_value

        with patch.object(sys, "argv", ["godot-agent", "chat"]):
            cli.main()

        mock_cmd_chat.assert_called_once()
        args, _kwargs = mock_cmd_chat.call_args
        self.assertEqual(args[1], mock_router)

    @patch("agent_system.cli.cmd_launch")
    @patch("agent_system.cli.GodotAgentRouter")
    @patch("agent_system.cli.setup_io")
    def test_launch_command_dispatches(self, _mock_setup_io, mock_router_cls, mock_cmd_launch):
        mock_router = mock_router_cls.return_value

        with patch.object(sys, "argv", ["godot-agent", "launch"]):
            cli.main()

        mock_cmd_launch.assert_called_once()
        args, _kwargs = mock_cmd_launch.call_args
        self.assertEqual(args[1], mock_router)

    @patch("agent_system.cli.cmd_wait_editor_event")
    @patch("agent_system.cli.GodotAgentRouter")
    @patch("agent_system.cli.setup_io")
    def test_wait_event_command_dispatches_without_router(self, _mock_setup_io, mock_router_cls, mock_cmd_wait_editor_event):
        with patch.object(sys, "argv", ["godot-agent", "wait-event"]):
            cli.main()

        mock_cmd_wait_editor_event.assert_called_once()
        mock_router_cls.assert_not_called()

    @patch("agent_system.cli.cmd_governance", return_value=0)
    @patch("agent_system.cli.GodotAgentRouter")
    @patch("agent_system.cli.setup_io")
    def test_governance_command_dispatches_without_router(self, _mock_setup_io, mock_router_cls, mock_cmd_governance):
        with patch.object(sys, "argv", ["godot-agent", "governance", "--policy"]):
            cli.main()

        mock_cmd_governance.assert_called_once()
        mock_router_cls.assert_not_called()

    @patch("agent_system.cli.cmd_production", return_value=0)
    @patch("agent_system.cli.GodotAgentRouter")
    @patch("agent_system.cli.setup_io")
    def test_production_command_dispatches_without_router(self, _mock_setup_io, mock_router_cls, mock_cmd_production):
        with patch.object(sys, "argv", ["godot-agent", "production", "--scenarios"]):
            cli.main()

        mock_cmd_production.assert_called_once()
        mock_router_cls.assert_not_called()

    @patch("agent_system.cli.cmd_agent_compat", return_value=0)
    @patch("agent_system.cli.GodotAgentRouter")
    @patch("agent_system.cli.setup_io")
    def test_agent_compat_command_dispatches_without_router(self, _mock_setup_io, mock_router_cls, mock_cmd_agent_compat):
        with patch.object(sys, "argv", ["godot-agent", "agent-compat", "--providers"]):
            cli.main()

        mock_cmd_agent_compat.assert_called_once()
        mock_router_cls.assert_not_called()

    def test_cmd_governance_returns_nonzero_for_strict_blockers(self):
        args = SimpleNamespace(
            policy=False,
            project=None,
            project_root=str(project_root / "tests" / ".tmp_cli_governance"),
            change_type="skill",
            evidence=["contract"],
            changed_path=["agent_system/skills/resource/demo_skill.py"],
            notes="",
            mode="strict",
            fail_on_warnings=False,
            json=True,
        )

        code = cli.cmd_governance(args)

        self.assertEqual(code, 1)

    def test_cmd_production_returns_nonzero_for_strict_blockers(self):
        args = SimpleNamespace(
            scenarios=False,
            project=None,
            project_root=str(project_root / "tests" / ".tmp_cli_production"),
            scenario_id="vertical_slice_2d",
            evidence=["contract,tests,docs,quality_dashboard"],
            changed_path=["scenes/Main.tscn"],
            notes="",
            mode="strict",
            fail_on_warnings=False,
            json=True,
        )

        code = cli.cmd_production(args)

        self.assertEqual(code, 1)

    def test_cmd_agent_compat_returns_zero_for_registered_provider(self):
        args = SimpleNamespace(
            providers=False,
            provider=["codex"],
            project=None,
            project_root=str(project_root),
            json=True,
        )

        code = cli.cmd_agent_compat(args)

        self.assertEqual(code, 0)

    @patch("agent_system.cli.SystemDoctor")
    def test_cmd_doctor_uses_default_report_path_and_returns_nonzero_on_failures(self, mock_doctor_cls):
        doctor = mock_doctor_cls.return_value
        doctor.check_all.return_value = False
        args = SimpleNamespace(config="config.yaml", report_path="", json=True)

        code = cli.cmd_doctor(args)

        self.assertEqual(code, 1)
        mock_doctor_cls.assert_called_once_with(config_path="config.yaml")
        doctor.check_all.assert_called_once_with(
            report_path="logs/reports/doctor_self_check.json",
            json_output=True,
        )


if __name__ == "__main__":
    unittest.main()

"""
CLI 行为测试
"""

import sys
import shutil
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

    @patch("agent_system.cli.cmd_game_create", return_value=0)
    @patch("agent_system.cli.GodotAgentRouter")
    @patch("agent_system.cli.setup_io")
    def test_game_create_command_dispatches_without_router(self, _mock_setup_io, mock_router_cls, mock_cmd_game_create):
        with patch.object(sys, "argv", ["godot-agent", "game-create", "--templates"]):
            cli.main()

        mock_cmd_game_create.assert_called_once()
        mock_router_cls.assert_not_called()

    @patch("agent_system.cli.cmd_roadmap", return_value=0)
    @patch("agent_system.cli.GodotAgentRouter")
    @patch("agent_system.cli.setup_io")
    def test_roadmap_command_dispatches_without_router(self, _mock_setup_io, mock_router_cls, mock_cmd_roadmap):
        with patch.object(sys, "argv", ["godot-agent", "roadmap", "--json"]):
            cli.main()

        mock_cmd_roadmap.assert_called_once()
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

    def test_cmd_roadmap_returns_status_counts(self):
        args = SimpleNamespace(
            project=None,
            project_root=str(project_root),
            json=True,
        )

        code = cli.cmd_roadmap(args)

        self.assertEqual(code, 0)

    def test_cmd_game_create_plan_returns_zero_for_default_template(self):
        args = SimpleNamespace(
            templates=False,
            audit=False,
            review=False,
            replay=False,
            apply=False,
            overwrite=False,
            project=None,
            project_root=str(project_root / "tests" / ".tmp_cli_game_create_plan"),
            title="Demo Runner",
            genre="platformer_2d",
            template_id="platformer_2d",
            feature=["jump,coin_collection"],
            target_platform=["web"],
            notes="",
            manifest_path="data_tables/game_creation/game_creation_profile.json",
            write_report=False,
            json=True,
        )

        code = cli.cmd_game_create(args)

        self.assertEqual(code, 0)

    def test_cmd_game_create_apply_writes_scaffold(self):
        temp_project = project_root / "tests" / ".tmp_cli_game_create_apply"
        shutil.rmtree(temp_project, ignore_errors=True)
        try:
            args = SimpleNamespace(
                templates=False,
                audit=False,
                review=False,
                replay=False,
                apply=True,
                overwrite=True,
                project=None,
                project_root=str(temp_project),
                title="Demo Runner",
                genre="platformer_2d",
                template_id="platformer_2d",
                feature=[],
                target_platform=["desktop"],
                notes="",
                manifest_path="data_tables/game_creation/game_creation_profile.json",
                write_report=False,
                json=True,
            )

            code = cli.cmd_game_create(args)
            manifest_exists = (temp_project / "data_tables" / "game_creation" / "game_creation_profile.json").exists()
            main_scene_exists = (temp_project / "scenes" / "Main.tscn").exists()
        finally:
            shutil.rmtree(temp_project, ignore_errors=True)

        self.assertEqual(code, 0)
        self.assertTrue(manifest_exists)
        self.assertTrue(main_scene_exists)

    def test_cmd_game_create_audit_writes_scene_graph_report(self):
        temp_project = project_root / "tests" / ".tmp_cli_game_create_audit"
        shutil.rmtree(temp_project, ignore_errors=True)
        try:
            apply_args = SimpleNamespace(
                templates=False,
                audit=False,
                review=False,
                replay=False,
                apply=True,
                overwrite=True,
                project=None,
                project_root=str(temp_project),
                title="Demo Runner",
                genre="platformer_2d",
                template_id="platformer_2d",
                feature=[],
                target_platform=["desktop"],
                notes="",
                manifest_path="data_tables/game_creation/game_creation_profile.json",
                write_report=False,
                json=True,
            )
            audit_args = SimpleNamespace(
                templates=False,
                audit=True,
                review=False,
                replay=False,
                apply=False,
                overwrite=False,
                project=None,
                project_root=str(temp_project),
                title="Demo Runner",
                genre="platformer_2d",
                template_id="platformer_2d",
                feature=[],
                target_platform=[],
                notes="",
                manifest_path="data_tables/game_creation/game_creation_profile.json",
                write_report=True,
                json=True,
            )

            cli.cmd_game_create(apply_args)
            code = cli.cmd_game_create(audit_args)
            audit_exists = (temp_project / "data_tables" / "game_creation" / "scene_graph_audit.json").exists()
        finally:
            shutil.rmtree(temp_project, ignore_errors=True)

        self.assertEqual(code, 0)
        self.assertTrue(audit_exists)

    def test_cmd_game_create_review_writes_acceptance_report(self):
        temp_project = project_root / "tests" / ".tmp_cli_game_create_review"
        shutil.rmtree(temp_project, ignore_errors=True)
        try:
            apply_args = SimpleNamespace(
                templates=False,
                audit=False,
                review=False,
                replay=False,
                apply=True,
                overwrite=True,
                project=None,
                project_root=str(temp_project),
                title="Demo Runner",
                genre="platformer_2d",
                template_id="platformer_2d",
                feature=[],
                target_platform=["desktop"],
                notes="",
                manifest_path="data_tables/game_creation/game_creation_profile.json",
                write_report=False,
                json=True,
            )
            review_args = SimpleNamespace(
                templates=False,
                audit=False,
                review=True,
                replay=False,
                apply=False,
                overwrite=False,
                project=None,
                project_root=str(temp_project),
                title="Demo Runner",
                genre="platformer_2d",
                template_id="platformer_2d",
                feature=[],
                target_platform=[],
                notes="",
                manifest_path="data_tables/game_creation/game_creation_profile.json",
                write_report=True,
                json=True,
            )

            cli.cmd_game_create(apply_args)
            code = cli.cmd_game_create(review_args)
            review_exists = (temp_project / "data_tables" / "game_creation" / "game_creation_review.json").exists()
            review_doc_exists = (temp_project / "docs" / "game_creation_review.md").exists()
        finally:
            shutil.rmtree(temp_project, ignore_errors=True)

        self.assertEqual(code, 0)
        self.assertTrue(review_exists)
        self.assertTrue(review_doc_exists)

    def test_cmd_game_create_replay_writes_input_replay_report(self):
        temp_project = project_root / "tests" / ".tmp_cli_game_create_replay"
        shutil.rmtree(temp_project, ignore_errors=True)
        try:
            apply_args = SimpleNamespace(
                templates=False,
                audit=False,
                review=False,
                replay=False,
                apply=True,
                overwrite=True,
                project=None,
                project_root=str(temp_project),
                title="Defense Trial",
                genre="tower_defense_2d",
                template_id="tower_defense_2d",
                feature=[],
                target_platform=["desktop"],
                notes="",
                manifest_path="data_tables/game_creation/game_creation_profile.json",
                write_report=False,
                json=True,
            )
            replay_args = SimpleNamespace(
                templates=False,
                audit=False,
                review=False,
                replay=True,
                apply=False,
                overwrite=False,
                project=None,
                project_root=str(temp_project),
                title="Defense Trial",
                genre="tower_defense_2d",
                template_id="tower_defense_2d",
                feature=[],
                target_platform=[],
                notes="",
                manifest_path="data_tables/game_creation/game_creation_profile.json",
                input_replay_path="data_tables/game_creation/input_replay.json",
                no_replay_script=False,
                execute_replay=False,
                promote_baseline=False,
                write_report=True,
                json=True,
            )

            cli.cmd_game_create(apply_args)
            code = cli.cmd_game_create(replay_args)
            replay_report_exists = (temp_project / "data_tables" / "game_creation" / "input_replay_run.json").exists()
            replay_script_exists = (temp_project / "logs" / "test_artifacts" / "game_creation" / "input_replay_tower_defense_2d.gd").exists()
        finally:
            shutil.rmtree(temp_project, ignore_errors=True)

        self.assertEqual(code, 0)
        self.assertTrue(replay_report_exists)
        self.assertTrue(replay_script_exists)

    def test_cmd_game_create_plan_supports_topdown_template_alias(self):
        args = SimpleNamespace(
            templates=False,
            audit=False,
            review=False,
            replay=False,
            apply=False,
            overwrite=False,
            project=None,
            project_root=str(project_root / "tests" / ".tmp_cli_game_create_topdown"),
            title="Arena Trial",
            genre="topdown_action_2d",
            template_id="topdown_action",
            feature=[],
            target_platform=["desktop"],
            notes="",
            manifest_path="data_tables/game_creation/game_creation_profile.json",
            write_report=False,
            json=True,
        )

        code = cli.cmd_game_create(args)

        self.assertEqual(code, 0)

    def test_cmd_game_create_plan_supports_tower_defense_template_alias(self):
        args = SimpleNamespace(
            templates=False,
            audit=False,
            review=False,
            replay=False,
            apply=False,
            overwrite=False,
            project=None,
            project_root=str(project_root / "tests" / ".tmp_cli_game_create_tower_defense"),
            title="Defense Trial",
            genre="tower_defense_2d",
            template_id="tower_defense",
            feature=[],
            target_platform=["desktop"],
            notes="",
            manifest_path="data_tables/game_creation/game_creation_profile.json",
            write_report=False,
            json=True,
        )

        code = cli.cmd_game_create(args)

        self.assertEqual(code, 0)

    def test_cmd_game_create_plan_supports_arpg_template_alias(self):
        args = SimpleNamespace(
            templates=False,
            audit=False,
            review=False,
            replay=False,
            apply=False,
            overwrite=False,
            project=None,
            project_root=str(project_root / "tests" / ".tmp_cli_game_create_arpg"),
            title="Relic Trial",
            genre="arpg_2d",
            template_id="arpg",
            feature=[],
            target_platform=["desktop"],
            notes="",
            manifest_path="data_tables/game_creation/game_creation_profile.json",
            write_report=False,
            json=True,
        )

        code = cli.cmd_game_create(args)

        self.assertEqual(code, 0)

    def test_cmd_game_create_plan_supports_roguelike_template_alias(self):
        args = SimpleNamespace(
            templates=False,
            audit=False,
            review=False,
            replay=False,
            template_migration=False,
            apply=False,
            overwrite=False,
            project=None,
            project_root=str(project_root / "tests" / ".tmp_cli_game_create_roguelike"),
            title="Dungeon Trial",
            genre="roguelike_2d",
            template_id="roguelike",
            feature=[],
            target_platform=["desktop"],
            notes="",
            manifest_path="data_tables/game_creation/game_creation_profile.json",
            write_report=False,
            json=True,
        )

        code = cli.cmd_game_create(args)

        self.assertEqual(code, 0)

    def test_cmd_game_create_plan_supports_visual_novel_template_alias(self):
        args = SimpleNamespace(
            templates=False,
            audit=False,
            review=False,
            replay=False,
            template_migration=False,
            apply=False,
            overwrite=False,
            project=None,
            project_root=str(project_root / "tests" / ".tmp_cli_game_create_visual_novel"),
            title="Story Trial",
            genre="visual_novel_2d",
            template_id="visual_novel",
            feature=[],
            target_platform=["desktop"],
            notes="",
            manifest_path="data_tables/game_creation/game_creation_profile.json",
            write_report=False,
            json=True,
        )

        code = cli.cmd_game_create(args)

        self.assertEqual(code, 0)

    def test_cmd_game_create_plan_supports_survival_crafting_template_alias(self):
        args = SimpleNamespace(
            templates=False,
            audit=False,
            review=False,
            replay=False,
            template_migration=False,
            apply=False,
            overwrite=False,
            project=None,
            project_root=str(project_root / "tests" / ".tmp_cli_game_create_survival"),
            title="Camp Trial",
            genre="survival_crafting_2d",
            template_id="survival_crafting",
            feature=[],
            target_platform=["desktop"],
            notes="",
            manifest_path="data_tables/game_creation/game_creation_profile.json",
            write_report=False,
            json=True,
        )

        code = cli.cmd_game_create(args)

        self.assertEqual(code, 0)

    def test_cmd_game_create_template_migration_writes_report(self):
        temp_project = project_root / "tests" / ".tmp_cli_game_create_template_migration"
        shutil.rmtree(temp_project, ignore_errors=True)
        try:
            apply_args = SimpleNamespace(
                templates=False,
                audit=False,
                review=False,
                replay=False,
                template_migration=False,
                apply=True,
                overwrite=True,
                project=None,
                project_root=str(temp_project),
                title="Demo Runner",
                genre="platformer_2d",
                template_id="platformer_2d",
                feature=[],
                target_platform=["desktop"],
                notes="",
                manifest_path="data_tables/game_creation/game_creation_profile.json",
                input_replay_path="data_tables/game_creation/input_replay.json",
                no_replay_script=False,
                execute_replay=False,
                promote_baseline=False,
                write_report=False,
                json=True,
            )
            migration_args = SimpleNamespace(
                templates=False,
                audit=False,
                review=False,
                replay=False,
                template_migration=True,
                apply=False,
                overwrite=False,
                project=None,
                project_root=str(temp_project),
                title="Demo Runner",
                genre="platformer_2d",
                template_id="platformer_2d",
                to_template_id="arpg",
                from_template_id="",
                migration_report_path="data_tables/game_creation/template_migration_plan.json",
                feature=[],
                target_platform=[],
                notes="",
                manifest_path="data_tables/game_creation/game_creation_profile.json",
                input_replay_path="data_tables/game_creation/input_replay.json",
                no_replay_script=False,
                execute_replay=False,
                promote_baseline=False,
                write_report=True,
                json=True,
            )

            cli.cmd_game_create(apply_args)
            code = cli.cmd_game_create(migration_args)
            report_exists = (
                temp_project / "data_tables" / "game_creation" / "template_migration_plan.json"
            ).exists()
        finally:
            shutil.rmtree(temp_project, ignore_errors=True)

        self.assertEqual(code, 0)
        self.assertTrue(report_exists)

    def test_cmd_game_create_replay_passes_render_mode(self):
        args = SimpleNamespace(
            templates=False,
            audit=False,
            review=False,
            replay=True,
            template_migration=False,
            apply=False,
            overwrite=False,
            project=None,
            project_root=str(project_root / "tests" / ".tmp_cli_game_create_replay_mode"),
            title="Demo Runner",
            genre="platformer_2d",
            template_id="platformer_2d",
            feature=[],
            target_platform=[],
            notes="",
            manifest_path="data_tables/game_creation/game_creation_profile.json",
            input_replay_path="data_tables/game_creation/input_replay.json",
            no_replay_script=False,
            execute_replay=True,
            replay_render_mode="viewport",
            promote_baseline=False,
            write_report=True,
            json=True,
        )

        with patch("agent_system.cli.build_game_creation_input_replay", return_value={"should_block": False}) as replay_mock:
            code = cli.cmd_game_create(args)

        self.assertEqual(code, 0)
        self.assertEqual(replay_mock.call_args.kwargs["replay_render_mode"], "viewport")

    def test_cmd_game_create_returns_nonzero_for_unknown_template(self):
        args = SimpleNamespace(
            templates=False,
            audit=False,
            review=False,
            replay=False,
            apply=False,
            overwrite=False,
            project=None,
            project_root=str(project_root / "tests" / ".tmp_cli_game_create_blocked"),
            title="Demo Runner",
            genre="platformer_2d",
            template_id="unknown",
            feature=[],
            target_platform=[],
            notes="",
            manifest_path="data_tables/game_creation/game_creation_profile.json",
            write_report=False,
            json=True,
        )

        code = cli.cmd_game_create(args)

        self.assertEqual(code, 1)

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

import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from agent_system.models import Task, TaskStatus, ToolResult
from agent_system.skills.resource.balance_analysis_skill import BalanceAnalysisSkill


class MockGodotCLI:
    def __init__(self, executable_path=None, project_path=None):
        self.executable = "godot"
        self.project_path = project_path

    def is_available(self):
        return True

    def run_headless(self, script_path, args=None):
        return ToolResult(True, "OK")

    def run_scene(self, scene_path):
        return ToolResult(True, "OK")

    def execute_editor_script(self, script_content):
        return ToolResult(True, "OK")

    def export_project(self, preset_name, output_path, release=True):
        return ToolResult(True, "OK")

    def get_version(self):
        return "4.2.0"


class BalanceAnalysisTestCase(unittest.TestCase):
    def setUp(self):
        self.project_dir = project_root / "tests" / ".tmp_balance_analysis"
        shutil.rmtree(self.project_dir, ignore_errors=True)
        self.project_dir.mkdir(parents=True, exist_ok=True)
        self.history_file = tempfile.mktemp(suffix=".json")

    def tearDown(self):
        shutil.rmtree(self.project_dir, ignore_errors=True)
        if os.path.exists(self.history_file):
            os.remove(self.history_file)

    def test_balance_analysis_skill_flags_missing_loot_links_and_probability_overflow(self):
        skill = BalanceAnalysisSkill(MockGodotCLI(project_path=str(self.project_dir)))
        task = Task(prompt="分析敌人和掉落数值平衡")
        result = skill.execute(task, {
            "enemy_rows": [
                {"enemy_id": "slime_elite", "name": "Elite Slime", "hp": "18", "attack": "12", "move_speed": "110", "loot_table_id": "loot_missing"},
            ],
            "loot_rows": [
                {"loot_id": "loot_common", "item_id": "coin", "drop_rate": "0.8", "quantity": "2"},
                {"loot_id": "loot_common", "item_id": "gem", "drop_rate": "0.5", "quantity": "1"},
            ],
            "quest_rows": [
                {"quest_id": "quest_intro", "title": "清理史莱姆", "description": "消灭 2 只史莱姆", "target_count": "2", "reward_gold": "60", "next_quest_id": ""},
            ],
        })

        self.assertFalse(result.success)
        self.assertEqual(task.context["balance_analysis"]["schema_version"], "1.0")
        self.assertEqual(task.context["contract_versions"]["balance_analysis"], "1.0")
        self.assertEqual(result.metadata["skill_result"]["skill_name"], "analyze_game_balance")
        self.assertEqual(result.metadata["skill_result"]["validation"]["passed"], False)
        self.assertTrue(any("不存在的掉落表" in issue for issue in task.context["balance_analysis"]["issues"]))
        self.assertTrue(any("总概率超过 1.0" in issue for issue in task.context["balance_analysis"]["issues"]))
        self.assertTrue(any(artifact.type == "report" for artifact in result.artifacts))

    def test_balance_analysis_skill_compares_candidate_against_baseline(self):
        skill = BalanceAnalysisSkill(MockGodotCLI(project_path=str(self.project_dir)))
        task = Task(prompt="比较当前数值与基线")
        result = skill.execute(task, {
            "enemy_rows": [
                {"enemy_id": "slime_basic", "name": "Slime", "hp": "240", "attack": "8", "move_speed": "100", "loot_table_id": "loot_slime"},
            ],
            "loot_rows": [
                {"loot_id": "loot_slime", "item_id": "coin", "drop_rate": "0.5", "quantity": "2"},
            ],
            "quest_rows": [
                {"quest_id": "quest_slime", "title": "清理史莱姆", "description": "消灭 3 只史莱姆", "target_count": "3", "reward_gold": "90", "next_quest_id": ""},
            ],
            "baseline_enemy_rows": [
                {"enemy_id": "slime_basic", "name": "Slime", "hp": "60", "attack": "8", "move_speed": "100", "loot_table_id": "loot_slime"},
            ],
            "baseline_loot_rows": [
                {"loot_id": "loot_slime", "item_id": "coin", "drop_rate": "0.5", "quantity": "2"},
            ],
            "baseline_quest_rows": [
                {"quest_id": "quest_slime", "title": "清理史莱姆", "description": "消灭 3 只史莱姆", "target_count": "3", "reward_gold": "90", "next_quest_id": ""},
            ],
        })

        self.assertFalse(result.success)
        self.assertEqual(task.context["balance_version_compare"]["schema_version"], "1.0")
        self.assertEqual(task.context["contract_versions"]["balance_version_compare"], "1.0")
        self.assertEqual(task.context["balance_version_compare_passed"], False)
        self.assertGreaterEqual(task.context["balance_version_compare"]["changed_metric_count"], 1)
        self.assertIn("avg_enemy_hp", task.context["balance_version_compare"]["metric_deltas"])
        self.assertTrue(any(artifact.name == "balance_version_compare.json" for artifact in result.artifacts))
        self.assertTrue(Path(task.context["balance_version_compare_report_path"]).exists())

    def test_balance_analysis_skill_runs_combat_simulation_gate(self):
        skill = BalanceAnalysisSkill(MockGodotCLI(project_path=str(self.project_dir)))
        task = Task(prompt="仿真敌人战斗节奏")
        result = skill.execute(task, {
            "simulate_combat_balance": True,
            "player_hp": 100,
            "player_attack": 5,
            "player_attacks_per_second": 1,
            "enemy_attacks_per_second": 1,
            "enemy_rows": [
                {"enemy_id": "brute", "name": "Brute", "hp": "200", "attack": "12", "move_speed": "80", "loot_table_id": "loot_brute"},
            ],
            "loot_rows": [
                {"loot_id": "loot_brute", "item_id": "coin", "drop_rate": "0.5", "quantity": "3"},
            ],
            "quest_rows": [
                {"quest_id": "quest_brute", "title": "击败蛮兵", "description": "消灭 1 个蛮兵", "target_count": "1", "reward_gold": "60", "next_quest_id": ""},
            ],
        })

        self.assertFalse(result.success)
        self.assertEqual(task.context["balance_combat_simulation_passed"], False)
        self.assertEqual(task.context["balance_combat_simulation_enemy_count"], 1)
        self.assertTrue(any("预计承伤" in issue for issue in task.context["balance_combat_simulation"]["issues"]))
        self.assertTrue(any(artifact.name == "combat_simulation.json" for artifact in result.artifacts))
        self.assertTrue(Path(task.context["balance_combat_simulation_report_path"]).exists())

    def test_balance_analysis_skill_audits_growth_curve_gate(self):
        skill = BalanceAnalysisSkill(MockGodotCLI(project_path=str(self.project_dir)))
        task = Task(prompt="审计成长曲线")
        result = skill.execute(task, {
            "audit_growth_curve": True,
            "max_enemy_power_slope_ratio": 2.0,
            "enemy_rows": [
                {"enemy_id": "unit_alpha", "level": "1", "hp": "30", "attack": "4", "move_speed": "100", "loot_table_id": "loot_alpha"},
                {"enemy_id": "unit_beta", "level": "2", "hp": "40", "attack": "5", "move_speed": "120", "loot_table_id": "loot_beta"},
                {"enemy_id": "unit_gamma", "level": "3", "hp": "180", "attack": "20", "move_speed": "80", "loot_table_id": "loot_gamma"},
            ],
            "loot_rows": [
                {"loot_id": "loot_alpha", "item_id": "coin", "drop_rate": "0.5", "quantity": "1"},
                {"loot_id": "loot_beta", "item_id": "coin", "drop_rate": "0.5", "quantity": "2"},
                {"loot_id": "loot_gamma", "item_id": "coin", "drop_rate": "0.5", "quantity": "5"},
            ],
            "quest_rows": [
                {"quest_id": "q1", "level": "1", "target_count": "2", "reward_gold": "40"},
                {"quest_id": "q2", "level": "2", "target_count": "2", "reward_gold": "60"},
                {"quest_id": "q3", "level": "3", "target_count": "2", "reward_gold": "80"},
            ],
        })

        self.assertFalse(result.success)
        self.assertEqual(task.context["balance_growth_curve_audit_passed"], False)
        self.assertEqual(task.context["balance_growth_curve_blocked_curve_count"], 1)
        self.assertIn("enemy_power", task.context["balance_growth_curve_audit"]["curves"])
        self.assertTrue(any("斜率跨度" in issue for issue in task.context["balance_growth_curve_audit"]["issues"]))
        self.assertTrue(any(artifact.name == "growth_curve_audit.json" for artifact in result.artifacts))
        self.assertTrue(Path(task.context["balance_growth_curve_audit_report_path"]).exists())

    @patch("agent_system.router.GodotCLI", MockGodotCLI)
    def test_router_routes_balance_prompt_and_records_skill_result(self):
        from agent_system.router import GodotAgentRouter

        router = GodotAgentRouter(godot_project_path=str(self.project_dir), history_file=self.history_file)
        task = router.execute(
            "做一次敌人强度和掉落分析",
            context={
                "balance_enemy_rows": [
                    {"enemy_id": "slime_basic", "name": "Slime", "hp": "30", "attack": "5", "move_speed": "100", "loot_table_id": "loot_slime"},
                ],
                "balance_loot_rows": [
                    {"loot_id": "loot_slime", "item_id": "coin", "drop_rate": "0.5", "quantity": "2"},
                ],
                "balance_quest_rows": [
                    {"quest_id": "quest_slime", "title": "清理史莱姆", "description": "消灭 3 只史莱姆", "target_count": "3", "reward_gold": "90", "next_quest_id": ""},
                ],
            },
            confirm=True,
        )

        self.assertEqual(task.status, TaskStatus.SUCCESS)
        self.assertEqual(task.steps[0].role, "resource_manager")
        self.assertEqual(task.context["last_skill_result"]["skill_name"], "analyze_game_balance")
        self.assertEqual(task.context["last_skill_result"]["validation"]["passed"], True)
        self.assertGreater(task.context["balance_analysis_score"], 0)

    @patch("agent_system.router.GodotCLI", MockGodotCLI)
    def test_router_passes_balance_baseline_rows_to_skill(self):
        from agent_system.router import GodotAgentRouter

        router = GodotAgentRouter(godot_project_path=str(self.project_dir), history_file=self.history_file)
        task = router.execute(
            "做一次敌人强度和基线对比",
            context={
                "balance_enemy_rows": [
                    {"enemy_id": "slime_basic", "name": "Slime", "hp": "240", "attack": "8", "move_speed": "100", "loot_table_id": "loot_slime"},
                ],
                "balance_loot_rows": [
                    {"loot_id": "loot_slime", "item_id": "coin", "drop_rate": "0.5", "quantity": "2"},
                ],
                "balance_quest_rows": [
                    {"quest_id": "quest_slime", "title": "清理史莱姆", "description": "消灭 3 只史莱姆", "target_count": "3", "reward_gold": "90", "next_quest_id": ""},
                ],
                "balance_baseline_enemy_rows": [
                    {"enemy_id": "slime_basic", "name": "Slime", "hp": "60", "attack": "8", "move_speed": "100", "loot_table_id": "loot_slime"},
                ],
                "balance_baseline_loot_rows": [
                    {"loot_id": "loot_slime", "item_id": "coin", "drop_rate": "0.5", "quantity": "2"},
                ],
                "balance_baseline_quest_rows": [
                    {"quest_id": "quest_slime", "title": "清理史莱姆", "description": "消灭 3 只史莱姆", "target_count": "3", "reward_gold": "90", "next_quest_id": ""},
                ],
            },
            confirm=True,
        )

        self.assertEqual(task.status, TaskStatus.FAILED)
        self.assertEqual(task.context["last_skill_result"]["skill_name"], "analyze_game_balance")
        self.assertEqual(task.context["balance_version_compare"]["schema_version"], "1.0")
        self.assertFalse(task.context["balance_version_compare_passed"])

    @patch("agent_system.router.GodotCLI", MockGodotCLI)
    def test_router_passes_combat_simulation_context_to_skill(self):
        from agent_system.router import GodotAgentRouter

        router = GodotAgentRouter(godot_project_path=str(self.project_dir), history_file=self.history_file)
        task = router.execute(
            "做一次敌人战斗仿真和平衡分析",
            context={
                "balance_simulate_combat": True,
                "balance_player_hp": 100,
                "balance_player_attack": 5,
                "balance_enemy_rows": [
                    {"enemy_id": "brute", "name": "Brute", "hp": "200", "attack": "12", "move_speed": "80", "loot_table_id": "loot_brute"},
                ],
                "balance_loot_rows": [
                    {"loot_id": "loot_brute", "item_id": "coin", "drop_rate": "0.5", "quantity": "3"},
                ],
                "balance_quest_rows": [
                    {"quest_id": "quest_brute", "title": "击败蛮兵", "description": "消灭 1 个蛮兵", "target_count": "1", "reward_gold": "60", "next_quest_id": ""},
                ],
            },
            confirm=True,
        )

        self.assertEqual(task.status, TaskStatus.FAILED)
        self.assertEqual(task.context["last_skill_result"]["skill_name"], "analyze_game_balance")
        self.assertEqual(task.context["balance_combat_simulation_passed"], False)
        self.assertIn("combat_simulation_max_damage_taken", task.context["last_skill_result"]["quality_gate"]["metrics"])

    @patch("agent_system.router.GodotCLI", MockGodotCLI)
    def test_router_passes_growth_curve_context_to_skill(self):
        from agent_system.router import GodotAgentRouter

        router = GodotAgentRouter(godot_project_path=str(self.project_dir), history_file=self.history_file)
        task = router.execute(
            "做一次敌人成长曲线和平衡分析",
            context={
                "balance_audit_growth_curve": True,
                "balance_max_enemy_power_slope_ratio": 2.0,
                "balance_enemy_rows": [
                    {"enemy_id": "unit_alpha", "level": "1", "hp": "30", "attack": "4", "move_speed": "100", "loot_table_id": "loot_alpha"},
                    {"enemy_id": "unit_beta", "level": "2", "hp": "40", "attack": "5", "move_speed": "120", "loot_table_id": "loot_beta"},
                    {"enemy_id": "unit_gamma", "level": "3", "hp": "180", "attack": "20", "move_speed": "80", "loot_table_id": "loot_gamma"},
                ],
                "balance_loot_rows": [
                    {"loot_id": "loot_alpha", "item_id": "coin", "drop_rate": "0.5", "quantity": "1"},
                    {"loot_id": "loot_beta", "item_id": "coin", "drop_rate": "0.5", "quantity": "2"},
                    {"loot_id": "loot_gamma", "item_id": "coin", "drop_rate": "0.5", "quantity": "5"},
                ],
                "balance_quest_rows": [
                    {"quest_id": "q1", "level": "1", "target_count": "2", "reward_gold": "40"},
                    {"quest_id": "q2", "level": "2", "target_count": "2", "reward_gold": "60"},
                    {"quest_id": "q3", "level": "3", "target_count": "2", "reward_gold": "80"},
                ],
            },
            confirm=True,
        )

        self.assertEqual(task.status, TaskStatus.FAILED)
        self.assertEqual(task.context["balance_growth_curve_audit_passed"], False)
        self.assertIn("growth_curve_enemy_power_max_slope_ratio", task.context["last_skill_result"]["quality_gate"]["metrics"])


if __name__ == "__main__":
    unittest.main()

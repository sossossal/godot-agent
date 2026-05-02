"""
Balance analysis skill for managed quest / enemy / loot data tables.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from ..base import BaseSkill, SkillMetadata
from ...contracts import BALANCE_ANALYSIS_SCHEMA_VERSION, BALANCE_VERSION_COMPARE_SCHEMA_VERSION
from ...models import Artifact, Task, ToolResult
from ...tools.balance_analysis import (
    GameBalanceAnalyzer,
    build_balance_analysis_report,
    build_balance_version_compare_report,
    build_combat_simulation_report,
    build_growth_curve_report,
    compare_balance_versions,
)
from ...validations import ProjectLayoutValidator


class BalanceAnalysisParams(BaseModel):
    include_tables: List[str] = Field(default_factory=lambda: ["enemy", "quest", "loot"])
    enemy_table_path: Optional[str] = Field(default=None)
    quest_table_path: Optional[str] = Field(default=None)
    loot_table_path: Optional[str] = Field(default=None)
    enemy_rows: List[Dict[str, Any]] = Field(default_factory=list)
    quest_rows: List[Dict[str, Any]] = Field(default_factory=list)
    loot_rows: List[Dict[str, Any]] = Field(default_factory=list)
    compare_with_baseline: bool = Field(default=False)
    baseline_enemy_table_path: Optional[str] = Field(default=None)
    baseline_quest_table_path: Optional[str] = Field(default=None)
    baseline_loot_table_path: Optional[str] = Field(default=None)
    baseline_enemy_rows: List[Dict[str, Any]] = Field(default_factory=list)
    baseline_quest_rows: List[Dict[str, Any]] = Field(default_factory=list)
    baseline_loot_rows: List[Dict[str, Any]] = Field(default_factory=list)
    simulate_combat_balance: bool = Field(default=False)
    player_hp: float = Field(default=100.0)
    player_attack: float = Field(default=10.0)
    player_attacks_per_second: float = Field(default=1.0)
    enemy_attacks_per_second: float = Field(default=1.0)
    min_ttk_seconds: float = Field(default=3.0)
    max_ttk_seconds: float = Field(default=18.0)
    max_damage_taken_ratio: float = Field(default=0.8)
    audit_growth_curve: bool = Field(default=False)
    max_enemy_power_slope_ratio: float = Field(default=3.0)
    max_reward_slope_ratio: float = Field(default=4.0)


class BalanceAnalysisSkill(BaseSkill):
    metadata = SkillMetadata(
        name="analyze_game_balance",
        description="分析敌人、任务和掉落数据表的数值平衡，输出结构化报告与风险摘要",
        category="resource",
        tags=["balance", "enemy", "quest", "loot", "economy"],
    )

    input_model = BalanceAnalysisParams

    def execute(self, task: Task, params: Dict[str, Any]) -> ToolResult:
        p = BalanceAnalysisParams(**params)
        project_root = Path(getattr(self.godot_cli, "project_path", ".") or ".").resolve()
        analyzer = GameBalanceAnalyzer(project_root)
        analysis = analyzer.analyze(
            include_tables=list(p.include_tables or ["enemy", "quest", "loot"]),
            enemy_table_path=p.enemy_table_path,
            quest_table_path=p.quest_table_path,
            loot_table_path=p.loot_table_path,
            enemy_rows=p.enemy_rows,
            quest_rows=p.quest_rows,
            loot_rows=p.loot_rows,
        )
        report_content = build_balance_analysis_report(analysis)

        layout_validator = ProjectLayoutValidator(project_root=project_root, runtime_root=Path.cwd())
        report_path = Path("logs/reports") / f"balance_analysis_{int(time.time())}.md"
        report_layout = layout_validator.validate_managed_path(report_path, "runtime_report")
        if not report_layout["passed"]:
            return self.build_result(
                success=False,
                message="数值平衡报告路径不符合文件树规范",
                params=self.dump_model(p),
                error="; ".join(issue["message"] for issue in report_layout["issues"]),
                validation={"passed": False, "issues": [issue["code"] for issue in report_layout["issues"]]},
            )

        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(report_content, encoding="utf-8")

        analysis_artifact = Artifact(
            name="balance_analysis.json",
            path="internal://balance_analysis.json",
            type="report",
            content=json.dumps(analysis, ensure_ascii=False, indent=2),
            metadata={"schema_version": BALANCE_ANALYSIS_SCHEMA_VERSION},
        )
        report_artifact = Artifact(
            name=report_path.name,
            path=str(report_path),
            type="report",
            content=report_content,
            metadata={"schema_version": BALANCE_ANALYSIS_SCHEMA_VERSION},
        )
        artifacts = [analysis_artifact, report_artifact]
        combat_simulation = None
        combat_report_path = None
        if p.simulate_combat_balance:
            combat_simulation = analyzer.simulate_combat_balance(
                enemy_table_path=p.enemy_table_path,
                enemy_rows=p.enemy_rows,
                player_hp=p.player_hp,
                player_attack=p.player_attack,
                player_attacks_per_second=p.player_attacks_per_second,
                enemy_attacks_per_second=p.enemy_attacks_per_second,
                min_ttk_seconds=p.min_ttk_seconds,
                max_ttk_seconds=p.max_ttk_seconds,
                max_damage_taken_ratio=p.max_damage_taken_ratio,
            )
            combat_report_content = build_combat_simulation_report(combat_simulation)
            combat_report_path = Path("logs/reports") / f"combat_simulation_{int(time.time())}.md"
            combat_report_layout = layout_validator.validate_managed_path(combat_report_path, "runtime_report")
            if not combat_report_layout["passed"]:
                return self.build_result(
                    success=False,
                    message="战斗仿真报告路径不符合文件树规范",
                    params=self.dump_model(p),
                    error="; ".join(issue["message"] for issue in combat_report_layout["issues"]),
                    validation={"passed": False, "issues": [issue["code"] for issue in combat_report_layout["issues"]]},
                )
            combat_report_path.parent.mkdir(parents=True, exist_ok=True)
            combat_report_path.write_text(combat_report_content, encoding="utf-8")
            artifacts.extend([
                Artifact(
                    name="combat_simulation.json",
                    path="internal://combat_simulation.json",
                    type="report",
                    content=json.dumps(combat_simulation, ensure_ascii=False, indent=2),
                    metadata={"schema_version": BALANCE_ANALYSIS_SCHEMA_VERSION},
                ),
                Artifact(
                    name=combat_report_path.name,
                    path=str(combat_report_path),
                    type="report",
                    content=combat_report_content,
                    metadata={"schema_version": BALANCE_ANALYSIS_SCHEMA_VERSION},
                ),
            ])
        growth_curve_audit = None
        growth_curve_report_path = None
        if p.audit_growth_curve:
            growth_curve_audit = analyzer.audit_growth_curve(
                enemy_table_path=p.enemy_table_path,
                quest_table_path=p.quest_table_path,
                enemy_rows=p.enemy_rows,
                quest_rows=p.quest_rows,
                max_enemy_power_slope_ratio=p.max_enemy_power_slope_ratio,
                max_reward_slope_ratio=p.max_reward_slope_ratio,
            )
            growth_curve_report_content = build_growth_curve_report(growth_curve_audit)
            growth_curve_report_path = Path("logs/reports") / f"growth_curve_audit_{int(time.time())}.md"
            growth_curve_report_layout = layout_validator.validate_managed_path(growth_curve_report_path, "runtime_report")
            if not growth_curve_report_layout["passed"]:
                return self.build_result(
                    success=False,
                    message="成长曲线审计报告路径不符合文件树规范",
                    params=self.dump_model(p),
                    error="; ".join(issue["message"] for issue in growth_curve_report_layout["issues"]),
                    validation={"passed": False, "issues": [issue["code"] for issue in growth_curve_report_layout["issues"]]},
                )
            growth_curve_report_path.parent.mkdir(parents=True, exist_ok=True)
            growth_curve_report_path.write_text(growth_curve_report_content, encoding="utf-8")
            artifacts.extend([
                Artifact(
                    name="growth_curve_audit.json",
                    path="internal://growth_curve_audit.json",
                    type="report",
                    content=json.dumps(growth_curve_audit, ensure_ascii=False, indent=2),
                    metadata={"schema_version": BALANCE_ANALYSIS_SCHEMA_VERSION},
                ),
                Artifact(
                    name=growth_curve_report_path.name,
                    path=str(growth_curve_report_path),
                    type="report",
                    content=growth_curve_report_content,
                    metadata={"schema_version": BALANCE_ANALYSIS_SCHEMA_VERSION},
                ),
            ])
        compare = None
        compare_report_path = None
        has_baseline = bool(
            p.compare_with_baseline
            or p.baseline_enemy_rows
            or p.baseline_quest_rows
            or p.baseline_loot_rows
            or p.baseline_enemy_table_path
            or p.baseline_quest_table_path
            or p.baseline_loot_table_path
        )
        if has_baseline:
            baseline_analysis = analyzer.analyze(
                include_tables=list(p.include_tables or ["enemy", "quest", "loot"]),
                enemy_table_path=p.baseline_enemy_table_path,
                quest_table_path=p.baseline_quest_table_path,
                loot_table_path=p.baseline_loot_table_path,
                enemy_rows=p.baseline_enemy_rows,
                quest_rows=p.baseline_quest_rows,
                loot_rows=p.baseline_loot_rows,
            )
            compare = compare_balance_versions(baseline_analysis, analysis)
            compare_report_content = build_balance_version_compare_report(compare)
            compare_report_path = Path("logs/reports") / f"balance_version_compare_{int(time.time())}.md"
            compare_report_layout = layout_validator.validate_managed_path(compare_report_path, "runtime_report")
            if not compare_report_layout["passed"]:
                return self.build_result(
                    success=False,
                    message="数值版本对比报告路径不符合文件树规范",
                    params=self.dump_model(p),
                    error="; ".join(issue["message"] for issue in compare_report_layout["issues"]),
                    validation={"passed": False, "issues": [issue["code"] for issue in compare_report_layout["issues"]]},
                )
            compare_report_path.parent.mkdir(parents=True, exist_ok=True)
            compare_report_path.write_text(compare_report_content, encoding="utf-8")
            artifacts.extend([
                Artifact(
                    name="balance_version_compare.json",
                    path="internal://balance_version_compare.json",
                    type="report",
                    content=json.dumps(compare, ensure_ascii=False, indent=2),
                    metadata={"schema_version": BALANCE_VERSION_COMPARE_SCHEMA_VERSION},
                ),
                Artifact(
                    name=compare_report_path.name,
                    path=str(compare_report_path),
                    type="report",
                    content=compare_report_content,
                    metadata={"schema_version": BALANCE_VERSION_COMPARE_SCHEMA_VERSION},
                ),
            ])

        contract_versions = dict(task.context.get("contract_versions") or {})
        contract_versions["balance_analysis"] = BALANCE_ANALYSIS_SCHEMA_VERSION
        if compare:
            contract_versions["balance_version_compare"] = BALANCE_VERSION_COMPARE_SCHEMA_VERSION
        task.context.update({
            "balance_analysis": analysis,
            "balance_analysis_score": analysis["score"],
            "balance_analysis_passed": analysis["passed"],
            "balance_analysis_issue_count": analysis["issue_count"],
            "balance_analysis_warning_count": analysis["warning_count"],
            "balance_analysis_table_types": list(analysis["table_types"]),
            "balance_analysis_report_path": str(report_path),
            "contract_versions": contract_versions,
        })
        if combat_simulation:
            task.context.update({
                "balance_combat_simulation": combat_simulation,
                "balance_combat_simulation_passed": combat_simulation["passed"],
                "balance_combat_simulation_report_path": str(combat_report_path),
                "balance_combat_simulation_enemy_count": combat_simulation["metrics"].get("combat_simulation_enemy_count", 0),
            })
        if growth_curve_audit:
            task.context.update({
                "balance_growth_curve_audit": growth_curve_audit,
                "balance_growth_curve_audit_passed": growth_curve_audit["passed"],
                "balance_growth_curve_audit_report_path": str(growth_curve_report_path),
                "balance_growth_curve_blocked_curve_count": growth_curve_audit["metrics"].get("growth_curve_blocked_curve_count", 0),
            })
        if compare:
            task.context.update({
                "balance_version_compare": compare,
                "balance_version_compare_passed": compare["passed"],
                "balance_version_compare_score_delta": compare["score_delta"],
                "balance_version_compare_issue_delta": compare["issue_delta"],
                "balance_version_compare_warning_delta": compare["warning_delta"],
                "balance_version_compare_report_path": str(compare_report_path),
            })

        success = (
            analysis["passed"]
            and (combat_simulation is None or combat_simulation["passed"])
            and (growth_curve_audit is None or growth_curve_audit["passed"])
            and (compare is None or compare["passed"])
        )

        message = (
            f"数值平衡分析通过，score={analysis['score']}"
            if success
            else f"数值平衡分析发现 {analysis['issue_count']} 个问题，score={analysis['score']}"
        )
        if compare and not compare["passed"]:
            message = f"数值版本对比未通过，score_delta={compare['score_delta']}，issue_delta={compare['issue_delta']}"
        if combat_simulation and not combat_simulation["passed"]:
            message = f"战斗仿真未通过，blocked={combat_simulation['metrics'].get('combat_simulation_blocked_count', 0)}"
        if growth_curve_audit and not growth_curve_audit["passed"]:
            message = f"成长曲线审计未通过，blocked={growth_curve_audit['metrics'].get('growth_curve_blocked_curve_count', 0)}"

        validation_checks = list(analysis["checks"])
        validation_issues = list(analysis["issues"])
        if combat_simulation:
            validation_checks.extend(combat_simulation["checks"])
            validation_issues.extend(combat_simulation["issues"])
        if growth_curve_audit:
            validation_checks.extend(growth_curve_audit["checks"])
            validation_issues.extend(growth_curve_audit["issues"])
        if compare:
            validation_checks.extend(compare["checks"])
            validation_issues.extend(compare["issues"])

        quality_metrics = dict(analysis["metrics"])
        if combat_simulation:
            quality_metrics.update(combat_simulation["metrics"])
        if growth_curve_audit:
            quality_metrics.update(growth_curve_audit["metrics"])
        if compare:
            quality_metrics["balance_version_score_delta"] = compare["score_delta"]

        return self.build_result(
            success=success,
            message=message,
            params=self.dump_model(p),
            artifacts=artifacts,
            validation={
                "passed": success,
                "issues": validation_issues,
                "checks": validation_checks,
            },
            quality_gate={
                "passed": success,
                "checks": validation_checks,
                "metrics": quality_metrics,
            },
            rollback={"available": False, "strategy": "analysis_only_no_write"},
        )

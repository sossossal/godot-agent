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
from ...contracts import BALANCE_ANALYSIS_SCHEMA_VERSION
from ...models import Artifact, Task, ToolResult
from ...tools.balance_analysis import GameBalanceAnalyzer, build_balance_analysis_report
from ...validations import ProjectLayoutValidator


class BalanceAnalysisParams(BaseModel):
    include_tables: List[str] = Field(default_factory=lambda: ["enemy", "quest", "loot"])
    enemy_table_path: Optional[str] = Field(default=None)
    quest_table_path: Optional[str] = Field(default=None)
    loot_table_path: Optional[str] = Field(default=None)
    enemy_rows: List[Dict[str, Any]] = Field(default_factory=list)
    quest_rows: List[Dict[str, Any]] = Field(default_factory=list)
    loot_rows: List[Dict[str, Any]] = Field(default_factory=list)


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

        contract_versions = dict(task.context.get("contract_versions") or {})
        contract_versions["balance_analysis"] = BALANCE_ANALYSIS_SCHEMA_VERSION
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

        message = (
            f"数值平衡分析通过，score={analysis['score']}"
            if analysis["passed"]
            else f"数值平衡分析发现 {analysis['issue_count']} 个问题，score={analysis['score']}"
        )

        return self.build_result(
            success=analysis["passed"],
            message=message,
            params=self.dump_model(p),
            artifacts=artifacts,
            validation={
                "passed": analysis["passed"],
                "issues": list(analysis["issues"]),
                "checks": list(analysis["checks"]),
            },
            quality_gate={
                "passed": analysis["passed"],
                "checks": list(analysis["checks"]),
                "metrics": dict(analysis["metrics"]),
            },
            rollback={"available": False, "strategy": "analysis_only_no_write"},
        )

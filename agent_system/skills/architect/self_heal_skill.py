"""
自修复技能 (Self-Heal Skill)
职责: 发现蓝图与物理工程的不一致, 并自动生成重做任务以补全工程
"""

from typing import Dict, Any, List
from ..base import BaseSkill, SkillMetadata
from ...models import Task, ToolResult, TaskStep, Artifact


class SelfHealSkill(BaseSkill):
    metadata = SkillMetadata(
        name="self_heal_project",
        description="执行项目自修复。自动检测缺失的文件并根据蓝图元数据重新生成它们。",
        category="architect",
        tags=["architect", "repair", "automation"]
    )

    def execute(self, task: Task, params: Dict[str, Any]) -> ToolResult:
        blueprint = task.context.get("blueprint_manager")
        if not blueprint:
            return self.build_result(
                success=False,
                message="未找到蓝图管理器",
                params=dict(params or {}),
                validation={"passed": False, "issues": ["missing_blueprint_manager"]},
            )
            
        task.add_log("🩺 正在扫描缺失产物并匹配修复方案...")
        repair_plans = blueprint.get_repair_plan()
        
        if not repair_plans:
            return self.build_result(
                success=True,
                message="项目状态完美，无需自修复。",
                params=dict(params or {}),
                validation={
                    "passed": True,
                    "checks": [
                        {"name": "repair_scan_completed", "status": "passed"},
                        {"name": "missing_feature_scan", "status": "passed"},
                    ],
                },
                rollback={"available": False, "strategy": "no_write_required"},
            )
            
        task.add_log(f"发现 {len(repair_plans)} 个待修复项。正在生成恢复序列...")
        
        # 将修复步骤注入到任务上下文 (Router 会在下一步处理)
        new_steps = []
        for i, plan in enumerate(repair_plans):
            step = TaskStep(
                name=f"Repair_{plan['feature_name']}",
                description=f"重新生成功能 '{plan['feature_name']}' 的缺失文件",
                role="auto",
                metadata={
                    "skill_name": plan["skill"],
                    "params": plan["params"]
                }
            )
            new_steps.append(step)
            
        from dataclasses import asdict
        task.context["pending_pattern_steps"] = [asdict(s) for s in new_steps]
        plan_lines = [
            "# Self-Heal Plan",
            "",
            f"- Repair Count: {len(new_steps)}",
            "",
        ]
        for plan in repair_plans:
            plan_lines.append(
                f"- `{plan['feature_name']}` via `{plan['skill']}`"
            )
        
        return self.build_result(
            success=True,
            message=f"已成功生成自修复计划, 包含 {len(new_steps)} 个恢复步骤。",
            params=dict(params or {}),
            artifacts=[
                Artifact(
                    name="SelfHealPlan",
                    path="internal://self_heal_plan.md",
                    type="plan",
                    content="\n".join(plan_lines) + "\n",
                )
            ],
            validation={
                "passed": True,
                "checks": [
                    {"name": "repair_scan_completed", "status": "passed"},
                    {"name": "repair_plan_generated", "status": "passed"},
                ],
            },
            rollback={"available": False, "strategy": "clear_pending_repair_steps"},
            metadata={"pending_repair_step_count": len(new_steps)},
        )

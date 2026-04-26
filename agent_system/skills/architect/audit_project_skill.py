"""
项目状态审计技能 (Audit Project Skill)
职责: 比对物理工程与蓝图, 发现文件缺失、进度差异或规约冲突
"""

from typing import Dict, Any
from ..base import BaseSkill, SkillMetadata
from ...models import Task, ToolResult, Artifact


class AuditProjectSkill(BaseSkill):
    metadata = SkillMetadata(
        name="audit_project_consistency",
        description="执行项目全量审计, 检查物理文件与蓝图设计是否一致",
        category="architect",
        tags=["architect", "audit", "health-check"]
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
            
        task.add_log("🔍 正在扫描工程物理状态并比对蓝图设计...")
        issues = blueprint.validate_project()
        
        if not issues:
            return self.build_result(
                success=True,
                message="项目健康检查通过: 所有蓝图功能在物理工程中均已就绪。",
                params=dict(params or {}),
                validation={
                    "passed": True,
                    "checks": [
                        {"name": "blueprint_consistency_scan", "status": "passed"},
                        {"name": "physical_file_presence", "status": "passed"},
                    ],
                },
                rollback={"available": False, "strategy": "no_write_required"},
            )
        
        # 格式化问题报告
        report = ["检测到以下一致性问题:"]
        for issue in issues:
            report.append(f"- [{issue['severity'].upper()}] 功能 '{issue['feature']}' 缺少文件: {issue['path']}")
            
        report_content = "\n".join(report)
        return self.build_result(
            success=True,
            message=report_content,
            params=dict(params or {}),
            error="inconsistent_state",
            artifacts=[
                Artifact(
                    name="ProjectConsistencyAudit",
                    path="internal://project_consistency_audit.md",
                    type="report",
                    content=report_content,
                )
            ],
            validation={
                "passed": False,
                "checks": [
                    {"name": "blueprint_consistency_scan", "status": "warning"},
                    {"name": "physical_file_presence", "status": "blocked"},
                ],
                "issues": [
                    f"{issue['feature']}::{issue['path']}"
                    for issue in issues
                ],
            },
            rollback={"available": False, "strategy": "no_write_required"},
        )

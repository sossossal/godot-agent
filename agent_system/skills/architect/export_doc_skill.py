"""
蓝图文档导出技能 (Export Blueprint Skill)
职责: 将当前的蓝图状态导出为精美的 Markdown 报告
"""

import os
from typing import Dict, Any, Optional
from pydantic import BaseModel, Field
from ..base import BaseSkill, SkillMetadata
from ...models import Task, ToolResult, Artifact


class ExportDocParams(BaseModel):
    file_name: str = Field(default="PROJECT_BLUEPRINT.md", description="导出的文件名")


class ExportBlueprintSkill(BaseSkill):
    metadata = SkillMetadata(
        name="export_blueprint_doc",
        description="导出项目的全量蓝图文档 (Markdown 格式), 包含功能清单、拓扑结构和架构规约。",
        category="architect",
        tags=["architect", "documentation", "report"]
    )
    input_model = ExportDocParams

    def execute(self, task: Task, params: Dict[str, Any]) -> ToolResult:
        p = ExportDocParams(**params)
        blueprint = task.context.get("blueprint_manager")
        if not blueprint:
            return self.build_result(
                success=False,
                message="未找到蓝图管理器",
                params=self.dump_model(p),
                validation={"passed": False, "issues": ["missing_blueprint_manager"]},
            )
            
        task.add_log("📝 正在根据当前蓝图生成开发报告...")
        report_content = blueprint.generate_markdown_report()
        
        # 确定保存路径
        output_path = os.path.join(self.godot_cli.project_path or ".", p.file_name)
        backup_path = self.backup_existing_file(task, output_path)
        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(report_content)
            
        artifact = Artifact(
            name="Project Blueprint Document",
            path=f"res://{p.file_name}",
            type="report",
            content=report_content
        )
        
        return self.build_result(
            success=True,
            message=f"项目开发文档已导出至: {p.file_name}。您可以随时查看当前工程的完整蓝图状态。",
            params=self.dump_model(p),
            artifacts=[artifact],
            validation={
                "passed": True,
                "checks": [
                    {"name": "blueprint_report_generated", "status": "passed"},
                    {"name": "report_written_to_disk", "status": "passed"},
                ],
            },
            rollback={
                "available": bool(backup_path),
                "strategy": "restore_previous_report_file" if backup_path else "delete_generated_report",
                "backup_paths": [backup_path] if backup_path else [],
            },
        )

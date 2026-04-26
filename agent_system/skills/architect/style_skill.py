"""
UI 样式设定技能 (UI Style Skill)
职责: 在蓝图中定义全局 UI 视觉规范 (颜色、圆角等)
"""

from typing import Dict, Any, Optional
from pydantic import BaseModel, Field
from ..base import BaseSkill, SkillMetadata
from ...models import Task, ToolResult


class StyleParams(BaseModel):
    primary_color: Optional[str] = Field(None, description="主色调 (Hex)")
    corner_radius: Optional[int] = Field(None, description="圆角大小 (像素)")
    font_size: Optional[int] = Field(None, description="基础字体大小")


class SetUIStyleSkill(BaseSkill):
    metadata = SkillMetadata(
        name="set_ui_style",
        description="设定项目的全局 UI 样式规范, 影响后续生成的界面视觉效果。",
        category="architect",
        tags=["architect", "ui", "style"]
    )
    input_model = StyleParams

    def execute(self, task: Task, params: Dict[str, Any]) -> ToolResult:
        p = StyleParams(**params)
        blueprint = task.context.get("blueprint_manager")
        if not blueprint:
            return self.build_result(
                success=False,
                message="未找到蓝图管理器",
                params=self.dump_model(p),
                validation={"passed": False, "issues": ["missing_blueprint_manager"]},
            )
            
        style_updates = {k: v for k, v in self.dump_model(p).items() if v is not None}
        blueprint.update_ui_style(style_updates)
        
        task.add_log(f"🎨 已更新全局 UI 样式: {style_updates}")
        return self.build_result(
            success=True,
            message="全局 UI 样式规范已更新。",
            params=self.dump_model(p),
            validation={
                "passed": True,
                "checks": [
                    {"name": "ui_style_updates_applied", "status": "passed"},
                ],
            },
            rollback={"available": False, "strategy": "blueprint_snapshot_before_changes_recommended"},
            metadata={"style_updates": style_updates},
        )

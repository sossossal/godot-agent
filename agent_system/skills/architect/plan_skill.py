"""
功能规划技能 (Plan Feature Skill)
职责: 在蓝图中添加或更新计划中的功能模块
"""

from typing import Dict, Any, List
from pydantic import BaseModel, Field
from ..base import BaseSkill, SkillMetadata
from ...models import Task, ToolResult
from ...tools.blueprint_manager import Feature


class PlanParams(BaseModel):
    feature_name: str = Field(description="功能名称")
    description: str = Field(description="详细功能描述")
    dependencies: List[str] = Field(default_factory=list, description="依赖的功能名列表")


class PlanFeatureSkill(BaseSkill):
    metadata = SkillMetadata(
        name="plan_game_feature",
        description="规划一个新的游戏功能模块并记入蓝图",
        category="architect",
        tags=["architect", "planning", "roadmap"]
    )
    input_model = PlanParams

    def execute(self, task: Task, params: Dict[str, Any]) -> ToolResult:
        p = PlanParams(**params)
        blueprint = task.context.get("blueprint_manager")
        if not blueprint:
            return self.build_result(
                success=False,
                message="未找到蓝图管理器实例",
                params=self.dump_model(p),
                validation={"passed": False, "issues": ["missing_blueprint_manager"]},
            )
            
        new_feat = Feature(
            name=p.feature_name,
            description=p.description,
            status="planned",
            dependencies=p.dependencies
        )
        
        blueprint.add_feature(new_feat)
        task.add_log(f"📝 架构师已规划新功能: {p.feature_name}")
        return self.build_result(
            success=True,
            message=f"功能 '{p.feature_name}' 已加入开发路线图。",
            params=self.dump_model(p),
            validation={
                "passed": True,
                "checks": [
                    {"name": "feature_added_to_blueprint", "status": "passed"},
                    {"name": "feature_dependencies_recorded", "status": "passed"},
                ],
            },
            rollback={"available": False, "strategy": "blueprint_snapshot_before_changes_recommended"},
            metadata={"feature_name": p.feature_name},
        )

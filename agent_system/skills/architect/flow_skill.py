"""
逻辑流定义技能 (Game Flow Skill)
职责: 在蓝图中定义场景跳转和全局事件触发逻辑, 串联游戏关卡
"""

from typing import Dict, Any, Optional
from pydantic import BaseModel, Field
from ..base import BaseSkill, SkillMetadata
from ...models import Task, ToolResult
from ...tools.blueprint_manager import Feature


class FlowParams(BaseModel):
    from_scene: str = Field(description="来源场景名称或路径")
    trigger: str = Field(description="触发条件, 如 'start_button_pressed', 'player_died'")
    to_scene: str = Field(description="目标场景名称或路径")


class DefineGameFlowSkill(BaseSkill):
    metadata = SkillMetadata(
        name="define_game_flow",
        description="定义游戏场景间的逻辑跳转, 将孤立的场景串联成完整的游戏流",
        category="architect",
        tags=["architect", "flow", "topology"]
    )
    input_model = FlowParams

    def execute(self, task: Task, params: Dict[str, Any]) -> ToolResult:
        p = FlowParams(**params)
        blueprint = task.context.get("blueprint_manager")
        if not blueprint:
            return self.build_result(
                success=False,
                message="未找到蓝图管理器",
                params=self.dump_model(p),
                validation={"passed": False, "issues": ["missing_blueprint_manager"]},
            )
            
        blueprint.add_scene_connection(p.from_scene, p.trigger, p.to_scene)
        
        task.add_log(f"🔗 已建立拓扑连接: {p.from_scene} --[{p.trigger}]--> {p.to_scene}")
        
        # 同时生成一个功能描述，记录到蓝图 Features 中作为“逻辑链”
        logic_feat = Feature(
            name=f"Flow_{p.from_scene}_to_{p.to_scene}",
            description=f"当 {p.from_scene} 触发 {p.trigger} 时跳转到 {p.to_scene}",
            status="planned"
        )
        blueprint.add_feature(logic_feat)
        
        return self.build_result(
            success=True,
            message=f"逻辑流已记录：从 {p.from_scene} 触发 '{p.trigger}' 将进入 {p.to_scene}。",
            params=self.dump_model(p),
            validation={
                "passed": True,
                "checks": [
                    {"name": "scene_connection_recorded", "status": "passed"},
                    {"name": "flow_feature_created", "status": "passed"},
                ],
            },
            rollback={"available": False, "strategy": "blueprint_snapshot_before_changes_recommended"},
        )

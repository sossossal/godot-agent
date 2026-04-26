"""
架构师角色 (Architect Role)
职责: 负责项目顶层设计、功能规划和蓝图维护
"""

from typing import List
from ..models import Task, TaskStatus
from .base import BaseRole
from ..skills.registry import SkillRegistry


class ArchitectRole(BaseRole):
    def get_description(self) -> str:
        return "游戏架构师, 负责项目从 0 到 1 的顶层规划、功能拆解和进度管理。"
    
    def get_capabilities(self) -> List[str]:
        return ["初始化项目蓝图", "规划功能模块", "维护开发路线图", "架构规约制定"]
    
    def execute(self, task: Task) -> Task:
        task.status = TaskStatus.RUNNING
        command = task.prompt
        
        try:
            # 自动选择最合适的架构技能
            if any(k in command for k in ["初始化", "开始制作", "项目设定", "基调"]):
                skill_name = "init_game_blueprint"
            else:
                skill_name = "plan_game_feature"
                
            # 注入蓝图管理器实例到上下文
            # 确保技能可以访问到它 (Router 会处理，这里做兜底)
            if "blueprint_manager" not in task.context:
                from ..tools.blueprint_manager import BlueprintManager
                task.context["blueprint_manager"] = BlueprintManager(self.godot_cli.project_path or ".")

            skill_res = SkillRegistry.get_skill_with_params(
                skill_name, 
                command, 
                self.godot_cli, 
                self.index_service
            )
            
            if skill_res:
                skill, params = skill_res
                # 特殊处理：将蓝图管理器传递给技能执行
                result = skill.execute(task, params)
                self._apply_skill_result_contract(task, result)
                self._merge_result_artifacts(task, result)
                
                if result.success:
                    return self._success_task(task, result.message)
                else:
                    return self._error_task(task, result.message, result.error)
            
            return self._error_task(task, f"架构师技能匹配失败: {skill_name}")
            
        except Exception as e:
            return self._error_task(task, f"架构逻辑异常: {str(e)}", str(e))

"""
项目开发角色 (上下文增强版)
职责: 场景创建、实时节点注入、多级上下文感知
"""

from typing import Dict, List, Any, Optional
from ..models import Task, TaskStatus, Artifact
from .base import BaseRole
from ..skills.registry import SkillRegistry


class DeveloperRole(BaseRole):
    """项目开发角色 (技能化重构版)"""
    
    def get_description(self) -> str:
        return "项目架构师, 支持实时感知编辑器选中节点并进行针对性修改"
    
    def get_capabilities(self) -> List[str]:
        return ["创建场景", "生成关卡模板与审计", "添加节点", "实时感知选中节点", "增量修改"]
    
    def execute(self, task: Task) -> Task:
        """执行开发任务"""
        task.status = TaskStatus.RUNNING
        command = task.prompt
        
        try:
            # 🆕 增强型模块化技能分发逻辑
            if any(keyword in command for keyword in ["输入", "按键", "键位", "映射"]):
                skill_name = "manage_input_mapping"
            elif "关卡" in command:
                skill_name = "manage_level_workflow"
            elif "场景" in command:
                skill_name = "create_godot_scene"
            elif "挂载" in command or "绑定脚本" in command or "设置脚本" in command:
                skill_name = "attach_script_to_node"
            elif "碰撞" in command or "物理" in command:
                skill_name = "configure_physics_collision"
            elif "实例化" in command or "预制件" in command:
                skill_name = "instantiate_scene_prefab"
            elif "UI" in command or "布局" in command or "界面" in command:
                skill_name = "auto_layout_ui"
            elif "粒子" in command or "特效" in command or "VFX" in command:
                skill_name = "inject_vfx_particle"
            elif "3D环境" in command or "搭建3D" in command:
                skill_name = "setup_3d_environment"
            elif "3D几何体" in command or "立方体" in command or "球体" in command:
                skill_name = "inject_3d_primitive"
            elif "节点" in command or "组件" in command:
                skill_name = "inject_godot_node"
            else:
                return self._error_task(task, "未识别的开发指令")

            skill_res = SkillRegistry.get_skill_with_params(
                skill_name, 
                command, 
                self.godot_cli, 
                self.index_service
            )
            
            if skill_res:
                skill, params = skill_res
                result = skill.execute(task, params)
                self._apply_skill_result_contract(task, result)
                self._merge_result_artifacts(task, result)
                
                if result.success:
                    return self._success_task(task, result.message)
                else:
                    return self._error_task(task, result.message, result.error)
            
            return self._error_task(task, f"无法匹配开发技能: {skill_name}")
            
        except Exception as e:
            return self._error_task(task, f"开发任务异常: {str(e)}", str(e))

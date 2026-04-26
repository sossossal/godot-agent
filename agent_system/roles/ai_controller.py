"""
AI 控制角色 (模板驱动版)
职责: 加载 AI 行为模板、生成智能 NPC 逻辑
"""

import os
from typing import Dict, List, Any, Optional
from ..models import Task, TaskStatus, Artifact
from .base import BaseRole
from ..skills.registry import SkillRegistry


from ..tools.template_manager import TemplateManager

class AIControllerRole(BaseRole):
    """AI 控制角色"""
    
    def __init__(self, godot_cli, index_service=None):
        super().__init__(godot_cli)
        self.template_manager = TemplateManager(godot_cli.project_path)

    def get_description(self) -> str:
        return "AI 架构师, 提供专业的巡逻、追击、状态机等行为逻辑模板"
    
    def get_capabilities(self) -> List[str]:
        return ["生成巡逻 AI", "生成追击 AI", "生成状态机基类", "生成警戒逻辑"]
    
    def execute(self, task: Task) -> Task:
        """执行 AI 控制任务 (模板驱动)"""
        task.status = TaskStatus.RUNNING
        command = task.prompt
        
        try:
            template_name = ""
            script_name = "ai_behavior.gd"
            
            if "巡逻" in command:
                template_name = "patrol.gd"
                script_name = "patrol_ai.gd"
            elif "追击" in command:
                template_name = "chase.gd"
                script_name = "chase_ai.gd"
            elif "状态机" in command:
                template_name = "fsm_base.gd"
                script_name = "fsm.gd"
            elif "警戒" in command:
                template_name = "alert.gd"
                script_name = "alert_ai.gd"
            
            if template_name:
                content = self.template_manager.get_template_content("ai", template_name)
                if content:
                    # 确定保存路径
                    rel_dir = "scripts/ai"
                    full_dir = rel_dir
                    if self.godot_cli.project_path:
                        full_dir = os.path.join(self.godot_cli.project_path, rel_dir)
                    
                    os.makedirs(full_dir, exist_ok=True)
                    full_path = os.path.join(full_dir, script_name)
                    
                    with open(full_path, 'w', encoding='utf-8') as f:
                        f.write(content)
                    
                    artifact = Artifact(
                        name=script_name,
                        path=f"res://{rel_dir}/{script_name}",
                        type="script",
                        content=content
                    )
                    task.artifacts.append(artifact)
                    return self._success_task(task, f"AI 行为脚本已基于模板生成: {script_name}")

            skill_res = SkillRegistry.get_skill_with_params(
                "generate_ai_behavior",
                command,
                self.godot_cli,
                self.index_service,
            )
            if skill_res:
                skill, params = skill_res
                result = skill.execute(task, params)
                self._apply_skill_result_contract(task, result)
                self._merge_result_artifacts(task, result)
                if result.success:
                    return self._success_task(task, result.message)
                return self._error_task(task, result.message, result.error)
            
            return self._error_task(task, "未找到匹配的 AI 模板,请尝试 '生成巡逻 AI'")
            
        except Exception as e:
            return self._error_task(task, f"AI 任务异常: {str(e)}", str(e))



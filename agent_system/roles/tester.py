"""
测试角色 (修复版)
职责: 场景冒烟测试、输入模拟自动化
"""

import base64
import os
import re
import tempfile
import time
from pathlib import Path
from typing import Dict, List, Any, Optional
from ..models import Task, TaskStatus, Artifact
from .base import BaseRole
from ..skills.registry import SkillRegistry


class TesterRole(BaseRole):
    """测试角色 (技能化重构版)"""
    
    def get_description(self) -> str:
        return "测试工程师, 擅长执行场景冒烟测试和自动化功能验证"
    
    def get_capabilities(self) -> List[str]:
        return ["运行场景冒烟测试", "模拟玩家输入验证", "端到端自动化测试", "运行期截图产物"]
    
    def execute(self, task: Task) -> Task:
        """执行测试任务"""
        task.status = TaskStatus.RUNNING
        command = task.prompt
        
        try:
            # 🆕 模块化技能调用
            if any(k in command for k in ["逻辑审计", "逻辑检查", "语法检查", "信号审计"]):
                skill_name = "audit_logic_errors"
            elif any(k in command for k in ["调试", "debug", "报错分析"]):
                skill_name = "auto_debug_runtime"
            elif any(k in command for k in ["端到端", "e2e", "模拟", "断言"]):
                skill_name = "e2e_test_scene"
            elif any(k in command for k in ["截图", "快照", "视觉反馈"]):
                skill_name = "quick_capture_scene"
            else:
                skill_name = "smoke_test_scene"
            
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
            
            return self._error_task(task, f"未找到匹配的测试技能: {skill_name}")
            
        except Exception as e:
            return self._error_task(task, f"测试引擎异常: {str(e)}", str(e))

"""
AI 行为建模技能 (AI Behavior Skill)
职责: 自动生成基于状态机的 AI 控制脚本, 实现 NPC 或敌人的复杂逻辑
"""

import os
from typing import Dict, Any, List, Optional
from pydantic import BaseModel, Field
from ..base import BaseSkill, SkillMetadata
from ...models import Task, ToolResult, Artifact


class AIParams(BaseModel):
    target_node_name: str = Field(description="应用 AI 的节点名称, 如 'Enemy' 或 'Guard'")
    states: List[str] = Field(default=["idle", "chase", "attack"], description="AI 包含的状态列表")
    target_script_name: Optional[str] = Field(None, description="生成的脚本文件名")


class AIBehaviorSkill(BaseSkill):
    metadata = SkillMetadata(
        name="generate_ai_behavior",
        description="为节点生成 AI 状态机脚本。支持定义多个状态并自动生成切换框架。",
        category="code",
        tags=["ai", "logic", "npc", "state-machine"]
    )
    input_model = AIParams

    def execute(self, task: Task, params: Dict[str, Any]) -> ToolResult:
        p = AIParams(**params)
        script_name = p.target_script_name or f"{p.target_node_name.lower()}_ai.gd"
        res_path = f"res://scripts/{script_name}"
        layout_check = self.validate_managed_output_path(res_path, "generated_script")
        if not layout_check["passed"]:
            return self.build_result(
                success=False,
                message=f"文件树规范阻断 AI 脚本生成: {res_path}",
                params=self.dump_model(p),
                error="project_layout_validation_failed",
                validation={
                    "passed": False,
                    "checks": [{"name": "project_layout", "status": "blocked"}],
                    "layout_check": layout_check,
                },
            )
        full_path = self.resolve_project_file_path(res_path)
        os.makedirs(os.path.dirname(full_path), exist_ok=True)
        
        task.add_log(f"🧠 正在建模 AI 行为: {p.target_node_name} (状态: {', '.join(p.states)})")
        
        # 1. 生成状态机代码
        code = self._generate_state_machine_code(p)
        
        # 2. 写入文件
        backup_path = self.backup_existing_file(task, full_path)
        with open(full_path, 'w', encoding='utf-8') as f:
            f.write(code)
            
        # 3. 更新蓝图
        blueprint = task.context.get("blueprint_manager")
        if blueprint:
            from ...tools.blueprint_manager import Feature
            blueprint.add_feature(Feature(
                name=f"AI_{p.target_node_name}",
                description=f"AI 状态机控制: {p.target_node_name}",
                files=[f"res://scripts/{script_name}"],
                creation_skill=self.metadata.name,
                creation_params=params
            ))

        artifact = Artifact(name=script_name, path=res_path, type="script", content=code)
        return self.build_result(
            success=True,
            message=f"已为 {p.target_node_name} 生成 AI 状态机脚本: {script_name}。",
            params=self.dump_model(p),
            artifacts=[artifact],
            validation={
                "passed": True,
                "checks": [
                    {"name": "ai_script_render", "status": "passed"},
                    {"name": "project_layout", "status": "passed"},
                    {"name": "ai_script_write", "status": "passed"},
                ],
                "layout_check": layout_check,
            },
            rollback={
                "available": bool(backup_path),
                "strategy": "restore_ai_script_from_backup" if backup_path else "replace_generated_script",
                "backup_paths": [backup_path] if backup_path else [],
            },
            metadata={"state_count": len(p.states)},
        )

    def _generate_state_machine_code(self, p: AIParams) -> str:
        state_enums = ", ".join([s.upper() for s in p.states])
        state_cases = ""
        for s in p.states:
            state_cases += f"""		STATE.{s.upper()}:
			_process_{s}(delta)
"""
        
        func_stubs = ""
        for s in p.states:
            func_stubs += f"""
func _process_{s}(delta):
	# 在此编写 {s} 状态的逻辑
	pass
"""

        return f"""extends CharacterBody2D

enum STATE {{ {state_enums} }}
var current_state = STATE.{p.states[0].upper()}

func _physics_process(delta):
	match current_state:
{state_cases}
	move_and_slide()

func change_state(new_state):
	current_state = new_state
	print("AI State changed to: ", new_state)
{func_stubs}
"""

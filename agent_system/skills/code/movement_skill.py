"""
2D/3D 角色移动生成技能 (Movement Skill - 增强型)
职责: 根据用户需求生成 CharacterBody2D/3D 移动逻辑
"""

import os
import time
import re
from typing import Dict, Any, Optional
from pydantic import BaseModel, Field

from ..base import BaseSkill, SkillMetadata
from ...models import Task, ToolResult, Artifact, Backup


class MovementParams(BaseModel):
    """移动脚本生成参数"""
    speed: float = Field(default=5.0, description="移动速度")
    jump_velocity: float = Field(default=4.5, description="跳跃力度")
    script_name: str = Field(default="player_movement.gd", description="脚本文件名")
    is_3d: bool = Field(default=True, description="是否为 3D 移动")
    use_gravity: bool = Field(default=True, description="是否包含重力")


class GenerateMovementSkill(BaseSkill):
    """生成移动脚本的具体技能"""
    
    metadata = SkillMetadata(
        name="generate_movement_script",
        description="为 Godot 角色生成标准的 2D 或 3D 移动脚本。支持自动感知项目维度。",
        category="code",
        tags=["movement", "scripting", "character", "3d"]
    )
    
    input_model = MovementParams

    def execute(self, task: Task, params: Dict[str, Any]) -> ToolResult:
        p = MovementParams(**params)
        
        # 自动推断 3D (从蓝图或参数)
        blueprint = task.context.get("blueprint_manager")
        if blueprint and blueprint.blueprint.game_genre == "3D":
            p.is_3d = True
            
        if p.is_3d:
            code = self._get_3d_template(p)
        else:
            code = self._get_2d_template(p)
            
        # 🆕 产物路径重定向
        res_path = self.resolve_generated_path(f"res://scripts/{p.script_name}", task)
        
        try:
            full_path, backup_path = self._save_script(task, res_path, code)
            artifact = Artifact(
                name=p.script_name, 
                path=res_path, 
                type="script", 
                content=code
            )
            return self.build_result(
                success=True,
                message=f"已生成 {'3D' if p.is_3d else '2D'} 移动脚本: {res_path}",
                params=self.dump_model(p),
                artifacts=[artifact],
                validation={
                    "passed": True,
                    "checks": [
                        {"name": "template_render", "status": "passed"},
                        {"name": "script_write", "status": "passed"},
                    ],
                },
                rollback={
                    "available": bool(backup_path),
                    "strategy": "restore_previous_script_from_backup" if backup_path else "replace_generated_script",
                    "backup_paths": [backup_path] if backup_path else [],
                },
            )
        except Exception as e:
            return self.build_result(
                success=False,
                message=f"生成脚本失败: {str(e)}",
                params=self.dump_model(p),
                error=str(e),
                validation={"passed": False, "issues": ["script_write_failed"]},
            )

    def _save_script(self, task: Task, res_path: str, code: str) -> tuple[str, Optional[str]]:
        # 将 res:// 转换为物理路径
        rel_path = res_path.replace("res://", "", 1)
        full_path = os.path.join(self.godot_cli.project_path or ".", rel_path)
        os.makedirs(os.path.dirname(full_path), exist_ok=True)
        backup_path: Optional[str] = None
        
        if os.path.exists(full_path):
            backup_path = os.path.join("logs", "backups", f"{os.path.basename(res_path)}.{int(time.time())}.bak")
            os.makedirs(os.path.dirname(backup_path), exist_ok=True)
            import shutil
            shutil.copy2(full_path, backup_path)
            
        with open(full_path, 'w', encoding='utf-8') as f:
            f.write(code)
        return full_path, backup_path

    def _get_2d_template(self, p: MovementParams) -> str:
        return f"""extends CharacterBody2D

const SPEED = {p.speed * 100}
const JUMP_VELOCITY = {-abs(p.jump_velocity * 100)}

var gravity = ProjectSettings.get_setting("physics/2d/default_gravity")

func _physics_process(delta):
	if not is_on_floor():
		velocity.y += gravity * delta
	if Input.is_action_just_pressed("ui_accept") and is_on_floor():
		velocity.y = JUMP_VELOCITY
	var direction = Input.get_axis("ui_left", "ui_right")
	if direction:
		velocity.x = direction * SPEED
	else:
		velocity.x = move_toward(velocity.x, 0, SPEED)
	move_and_slide()
"""

    def _get_3d_template(self, p: MovementParams) -> str:
        return f"""extends CharacterBody3D

const SPEED = {p.speed}
const JUMP_VELOCITY = {p.jump_velocity}

var gravity = ProjectSettings.get_setting("physics/3d/default_gravity")

func _physics_process(delta):
	if not is_on_floor():
		velocity.y -= gravity * delta

	if Input.is_action_just_pressed("ui_accept") and is_on_floor():
		velocity.y = JUMP_VELOCITY

	var input_dir = Input.get_vector("ui_left", "ui_right", "ui_up", "ui_down")
	var direction = (transform.basis * Vector3(input_dir.x, 0, input_dir.y)).normalized()
	if direction:
		velocity.x = direction.x * SPEED
		velocity.z = direction.z * SPEED
	else:
		velocity.x = move_toward(velocity.x, 0, SPEED)
		velocity.z = move_toward(velocity.z, 0, SPEED)

	move_and_slide()
"""

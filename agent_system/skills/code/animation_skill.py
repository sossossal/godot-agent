"""
动画指令技能 (Tween Animation Skill)
职责: 自动在指定脚本中插入 Tween 动画代码, 实现节点的平滑过渡和视觉反馈
"""

import os
from typing import Dict, Any
from pydantic import BaseModel, Field
from ..base import BaseSkill, SkillMetadata
from ...models import Task, ToolResult, Artifact


class AnimationParams(BaseModel):
    target_script: str = Field(description="目标脚本路径, 如 res://scripts/player.gd")
    animation_type: str = Field(description="动画类型: fade_in, scale_up, bounce, rotate_loop")
    duration: float = Field(default=1.0, description="持续时间 (秒)")
    target_node_path: str = Field(default="self", description="要应用动画的子节点路径")


class TweenAnimationSkill(BaseSkill):
    metadata = SkillMetadata(
        name="apply_tween_animation",
        description="为指定节点添加 Tween 动画效果。支持淡入、缩放、弹跳和循环旋转等预设。",
        category="code",
        tags=["animation", "tween", "visual-effect"]
    )
    input_model = AnimationParams

    def execute(self, task: Task, params: Dict[str, Any]) -> ToolResult:
        p = AnimationParams(**params)
        layout_check = self.validate_managed_output_path(p.target_script, "generated_script")
        if not layout_check["passed"]:
            return self.build_result(
                success=False,
                message=f"文件树规范阻断动画脚本写入: {p.target_script}",
                params=self.dump_model(p),
                error="project_layout_validation_failed",
                validation={
                    "passed": False,
                    "checks": [{"name": "project_layout", "status": "blocked"}],
                    "layout_check": layout_check,
                },
            )
        full_path = self.resolve_project_file_path(p.target_script)
        
        if not os.path.exists(full_path):
            return self.build_result(
                success=False,
                message=f"目标脚本不存在: {p.target_script}",
                params=self.dump_model(p),
                validation={"passed": False, "issues": ["missing_target_script"]},
            )
            
        task.add_log(f"🎬 正在为 {p.target_script} 注入动画逻辑: {p.animation_type}")
        
        # 1. 生成对应的 Tween 代码块
        tween_code = self._generate_tween_code(p)
        
        # 2. 读取并注入代码
        with open(full_path, 'r', encoding='utf-8') as f:
            content = f.read()
            
        # 寻找合适的注入点 (优先放在 _ready 或新函数中)
        func_name = f"play_{p.animation_type}"
        if f"func {func_name}" in content:
            return self.build_result(
                success=True,
                message=f"动画函数 {func_name} 已存在, 跳过。",
                params=self.dump_model(p),
                artifacts=[Artifact(name=os.path.basename(full_path), path=p.target_script, type="script", content=content)],
                validation={
                    "passed": True,
                    "checks": [
                        {"name": "target_script_exists", "status": "passed"},
                        {"name": "project_layout", "status": "passed"},
                        {"name": "animation_function_present", "status": "passed"},
                    ],
                    "layout_check": layout_check,
                },
                rollback={"available": False, "strategy": "no_write_required"},
            )
            
        content += f"\n\nfunc {func_name}():\n{tween_code}\n"
        
        # 尝试在 _ready 中自动触发 (如果是单次动画)
        if p.animation_type in ["fade_in", "scale_up"]:
            if "func _ready():" in content:
                content = content.replace("func _ready():", f"func _ready():\n\t{func_name}()")
            else:
                content += f"\nfunc _ready():\n\t{func_name}()\n"

        backup_path = self.backup_existing_file(task, full_path)
        with open(full_path, 'w', encoding='utf-8') as f:
            f.write(content)
            
        artifact = Artifact(name=os.path.basename(full_path), path=p.target_script, type="script", content=content)
        return self.build_result(
            success=True,
            message=f"已成功为 {p.target_script} 添加了 '{p.animation_type}' 动画函数。",
            params=self.dump_model(p),
            artifacts=[artifact],
            validation={
                "passed": True,
                "checks": [
                    {"name": "target_script_exists", "status": "passed"},
                    {"name": "project_layout", "status": "passed"},
                    {"name": "animation_function_inserted", "status": "passed"},
                ],
                "layout_check": layout_check,
            },
            rollback={
                "available": bool(backup_path),
                "strategy": "restore_script_from_backup" if backup_path else "replace_generated_script",
                "backup_paths": [backup_path] if backup_path else [],
            },
        )

    def _generate_tween_code(self, p: AnimationParams) -> str:
        target = f"get_node(\"{p.target_node_path}\")" if p.target_node_path != "self" else "self"
        
        presets = {
            "fade_in": f"""	var tween = create_tween()
	{target}.modulate.a = 0
	tween.tween_property({target}, "modulate:a", 1.0, {p.duration}).set_trans(Tween.TRANS_SINE)""",
            
            "scale_up": f"""	var tween = create_tween()
	{target}.scale = Vector2.ZERO
	tween.tween_property({target}, "scale", Vector2.ONE, {p.duration}).set_trans(Tween.TRANS_ELASTIC).set_ease(Tween.EASE_OUT)""",
            
            "bounce": f"""	var tween = create_tween().set_loops()
	var original_pos = {target}.position
	tween.tween_property({target}, "position:y", original_pos.y - 20, {p.duration/2}).set_trans(Tween.TRANS_SINE)
	tween.tween_property({target}, "position:y", original_pos.y, {p.duration/2}).set_trans(Tween.TRANS_SINE)""",
            
            "rotate_loop": f"""	var tween = create_tween().set_loops()
	tween.tween_property({target}, "rotation", PI * 2, {p.duration}).as_relative()"""
        }
        
        return presets.get(p.animation_type, f"	pass # 暂不支持的动画类型: {p.animation_type}")

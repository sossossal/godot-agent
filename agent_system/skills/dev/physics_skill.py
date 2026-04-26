"""
物理碰撞配置技能 (Physics Configuration Skill - 工业级离线版)
职责: 自动为节点添加物理主体和碰撞形状, 采用 SceneTree 确保 Headless 执行成功
"""

from typing import Dict, Any, Optional
import os
from pydantic import BaseModel, Field
from ..base import BaseSkill, SkillMetadata
from ...models import Task, ToolResult, Artifact


class PhysicsParams(BaseModel):
    target_node_path: str = Field(description="目标节点路径")
    body_type: Optional[str] = Field(None, description="物理类型")
    shape_type: Optional[str] = Field(None, description="形状类型")
    is_3d: bool = Field(default=True, description="是否为 3D 物理")
    target_scene: Optional[str] = Field(None, description="目标场景文件路径")


class PhysicsConfigSkill(BaseSkill):
    metadata = SkillMetadata(
        name="configure_physics_collision",
        description="自动化配置物理碰撞。支持离线 SceneTree 烘焙模式。",
        category="dev",
        tags=["physics", "collision", "body", "3d"]
    )
    input_model = PhysicsParams

    def execute(self, task: Task, params: Dict[str, Any]) -> ToolResult:
        p = PhysicsParams(**params)
        
        blueprint = task.context.get("blueprint_manager")
        if blueprint and blueprint.blueprint.game_genre == "3D":
            p.is_3d = True
            
        target_scene = p.target_scene or task.context.get("scene_path")
        if not target_scene:
            return self.build_result(
                success=False,
                message="未找到目标场景路径。",
                params=self.dump_model(p),
                validation={"passed": False, "issues": ["missing_target_scene"]},
            )
        
        # 统一类名
        suffix = "3D" if p.is_3d else "2D"
        body_class = p.body_type or f"StaticBody{suffix}"
        if not (body_class.endswith("2D") or body_class.endswith("3D")): body_class += suffix
        
        shape_class = p.shape_type or ("SphereShape3D" if "球" in task.prompt else ("BoxShape3D" if p.is_3d else "RectangleShape2D"))
        if not (shape_class.endswith("2D") or shape_class.endswith("3D")): shape_class += suffix
        
        task.add_log(f"🛡️ 正在离线配置物理: {p.target_node_path} ({body_class})")
        
        script = self._generate_baked_script(p, body_class, shape_class, target_scene)
        artifacts = [
            Artifact(
                name=f"physics_{p.target_node_path.replace('/', '_')}.gd",
                path="internal://",
                type="headless_script",
                content=script,
                metadata={"target_scene": target_scene},
            )
        ]
        
        result = self.godot_cli.run_headless_script(script)
        
        if result.success:
            return self.build_result(
                success=True,
                message=f"已成功为 {p.target_node_path} 配置物理主体 {body_class}。",
                params=self.dump_model(p),
                artifacts=artifacts,
                validation={
                    "passed": True,
                    "checks": [
                        {"name": "target_scene_resolved", "status": "passed"},
                        {"name": "headless_physics_bake", "status": "passed"},
                    ],
                },
                rollback={"available": False, "strategy": "restore_scene_from_vcs_or_backup"},
            )
        return self.build_result(
            success=False,
            message="物理烘焙失败",
            params=self.dump_model(p),
            error=result.error,
            artifacts=artifacts,
            validation={"passed": False, "issues": ["physics_bake_failed"]},
            rollback={"available": False, "strategy": "restore_scene_from_vcs_or_backup"},
        )

    def _generate_baked_script(self, p: PhysicsParams, body_class: str, shape_class: str, scene_path: str) -> str:
        return f'''extends SceneTree
func _initialize():
	var scene = load("{scene_path}")
	if not scene is PackedScene:
		push_error("FAILED_TO_LOAD")
		quit(1); return
		
	var root = scene.instantiate()
	var target = root.get_node_or_null(NodePath("{p.target_node_path}"))
	if not target:
		push_error("NODE_NOT_FOUND")
		quit(1); return
	
	# 创建物理主体
	var body = {body_class}.new()
	body.name = target.name + "_Body"
	var parent = target.get_parent()
	var pos = target.position
	
	parent.add_child(body)
	body.owner = root
	body.position = pos
	
	# 移动节点
	target.get_parent().remove_child(target)
	body.add_child(target)
	target.owner = root
	target.position = Vector3.ZERO if "{body_class}".ends_with("3D") else Vector2.ZERO
	
	# 创建碰撞形状
	var col_class = "CollisionShape3D" if "{body_class}".ends_with("3D") else "CollisionShape2D"
	var col = ClassDB.instantiate(col_class)
	col.name = "CollisionShape"
	col.shape = {shape_class}.new()
	body.add_child(col)
	col.owner = root
	
	# 保存场景
	var new_scene = PackedScene.new()
	new_scene.pack(root)
	var res = ResourceSaver.save(new_scene, "{scene_path}")
	if res == OK:
		print("SUCCESS_BAKED")
		quit(0)
	else:
		push_error("SAVE_FAILED")
		quit(1)
'''

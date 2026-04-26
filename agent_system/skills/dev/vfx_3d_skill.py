"""
3D 几何体注入技能 (3D Primitive Skill - 增强型)
职责: 在 3D 场景中添加基础几何体, 支持位置设定和离线注入
"""

from typing import Dict, Any, Optional, List
import os
from pydantic import BaseModel, Field
from ..base import BaseSkill, SkillMetadata
from ...models import Task, ToolResult, Artifact


class Primitive3DParams(BaseModel):
    shape_type: str = Field(description="几何体类型: Box, Sphere, Capsule, Cylinder")
    node_name: Optional[str] = Field(None, description="节点名称")
    size: float = Field(default=1.0, description="几何体缩放/大小")
    position: List[float] = Field(default=[0.0, 0.0, 0.0], description="3D 坐标 [x, y, z]")
    target_scene: Optional[str] = Field(None, description="目标场景文件路径")


class Inject3DPrimitiveSkill(BaseSkill):
    metadata = SkillMetadata(
        name="inject_3d_primitive",
        description="在 3D 场景中添加基础几何体。支持指定坐标位置、网格类型和碰撞生成。",
        category="dev",
        tags=["3d", "primitive", "mesh", "editor_plugin"]
    )
    input_model = Primitive3DParams

    def execute(self, task: Task, params: Dict[str, Any]) -> ToolResult:
        p = Primitive3DParams(**params)
        node_name = p.node_name or f"{p.shape_type}3D"
        target_scene = p.target_scene or task.context.get("scene_path")
        
        editor_state = task.context.get("editor_state", {})
        if editor_state.get("is_active") and not p.target_scene:
            task.add_log(f"🎯 编辑器在线: 正在实时注入 {p.shape_type} 到 {p.position}")
            script = self._generate_editor_script(p, node_name)
            artifact = Artifact(name=f"add_{node_name}.gd", path="internal://", type="editor_script", content=script)
            return self.build_result(
                success=True,
                message="已下发注入指令。",
                params=self.dump_model(p),
                artifacts=[artifact],
                validation={
                    "passed": True,
                    "checks": [
                        {"name": "editor_online", "status": "passed"},
                        {"name": "primitive_editor_script_generated", "status": "passed"},
                    ],
                },
                rollback={"available": False, "strategy": "wait_for_editor_confirmation"},
            )
        
        if not target_scene:
            return self.build_result(
                success=False,
                message="离线模式下必须提供 target_scene 路径",
                params=self.dump_model(p),
                validation={"passed": False, "issues": ["missing_target_scene"]},
            )
            
        task.add_log(f"⚙️ 编辑器离线: 正在向文件 {target_scene} 注入 {p.shape_type} (Pos: {p.position})")
        script = self._generate_headless_script(p, node_name, target_scene)
        result = self.godot_cli.execute_editor_script(script)
        
        if result.success:
            return self.build_result(
                success=True,
                message=f"已将 {p.shape_type} 注入到 {target_scene} 的 {p.position}",
                params=self.dump_model(p),
                artifacts=[
                    Artifact(name=f"add_{node_name}.gd", path="internal://", type="headless_script", content=script),
                    Artifact(name=node_name, path=target_scene, type="scene"),
                ],
                validation={
                    "passed": True,
                    "checks": [
                        {"name": "target_scene_resolved", "status": "passed"},
                        {"name": "primitive_injection_dispatch", "status": "passed"},
                    ],
                },
                rollback={"available": False, "strategy": "restore_scene_from_vcs_or_backup"},
            )
        return self.build_result(
            success=False,
            message="注入失败",
            params=self.dump_model(p),
            error=result.error,
            artifacts=[Artifact(name=f"add_{node_name}.gd", path="internal://", type="headless_script", content=script)],
            validation={"passed": False, "issues": ["primitive_injection_failed"]},
        )

    def _generate_editor_script(self, p: Primitive3DParams, node_name: str) -> str:
        mesh_class = f"{p.shape_type}Mesh"
        return f'''
func _run(plugin: EditorPlugin):
	var root = plugin.get_editor_interface().get_edited_scene_root()
	if not root: return
	var mesh_instance = MeshInstance3D.new()
	mesh_instance.name = "{node_name}"
	mesh_instance.position = Vector3({p.position[0]}, {p.position[1]}, {p.position[2]})
	var mesh = {mesh_class}.new()
	if mesh is BoxMesh: mesh.size = Vector3({p.size}, {p.size}, {p.size})
	mesh_instance.mesh = mesh
	mesh_instance.create_trimesh_collision()
	root.add_child(mesh_instance)
	mesh_instance.owner = root
'''

    def _generate_headless_script(self, p: Primitive3DParams, node_name: str, scene_path: str) -> str:
        mesh_class = f"{p.shape_type}Mesh"
        return f'''@tool
extends EditorScript
func _run():
	var scene = load("{scene_path}")
	if not scene is PackedScene: return
	var root = scene.instantiate()
	var mesh_instance = MeshInstance3D.new()
	mesh_instance.name = "{node_name}"
	mesh_instance.position = Vector3({p.position[0]}, {p.position[1]}, {p.position[2]})
	var mesh = {mesh_class}.new()
	if mesh is BoxMesh: mesh.size = Vector3({p.size}, {p.size}, {p.size})
	mesh_instance.mesh = mesh
	mesh_instance.create_trimesh_collision()
	root.add_child(mesh_instance)
	mesh_instance.owner = root
	var new_scene = PackedScene.new()
	new_scene.pack(root)
	ResourceSaver.save(new_scene, "{scene_path}")
'''

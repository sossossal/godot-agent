"""
脚本挂载技能 (Attach Script Skill)
职责: 将指定的脚本文件挂载到场景中的特定节点上
"""

import os
from typing import Dict, Any, Optional
from pydantic import BaseModel, Field
from ..base import BaseSkill, SkillMetadata
from ...models import Task, ToolResult, Artifact


class AttachParams(BaseModel):
    target_node_path: str = Field(description="目标节点路径")
    script_path: str = Field(description="脚本文件路径, 如 res://scripts/player.gd")
    target_scene: Optional[str] = Field(None, description="场景文件路径 (离线模式必填)")


class AttachScriptSkill(BaseSkill):
    metadata = SkillMetadata(
        name="attach_script_to_node",
        description="将一个 GDScript 脚本挂载到场景中的指定节点上。支持实时和离线模式。",
        category="dev",
        tags=["script", "node", "bind", "editor_plugin"]
    )
    input_model = AttachParams

    def execute(self, task: Task, params: Dict[str, Any]) -> ToolResult:
        p = AttachParams(**params)
        target_scene = p.target_scene or task.context.get("scene_path")
        
        editor_state = task.context.get("editor_state", {})
        if editor_state.get("is_active") and not p.target_scene:
            task.add_log(f"🎯 编辑器在线: 正在实时挂载脚本 {p.script_path}")
            script = self._generate_editor_script(p)
            artifact = Artifact(name="attach_script.gd", path="internal://", type="editor_script", content=script)
            return self.build_result(
                success=True,
                message="已下发脚本挂载指令。",
                params=self.dump_model(p),
                artifacts=[artifact],
                validation={
                    "passed": True,
                    "checks": [
                        {"name": "target_scene_resolution", "status": "passed"},
                        {"name": "editor_dispatch_ready", "status": "passed"},
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
            
        task.add_log(f"⚙️ 编辑器离线: 正在向 {target_scene} 中的 {p.target_node_path} 挂载脚本")
        script = self._generate_headless_script(p, target_scene)
        result = self.godot_cli.execute_editor_script(script)
        
        if result.success:
            return self.build_result(
                success=True,
                message=f"脚本 {p.script_path} 已成功挂载到 {target_scene} 的 {p.target_node_path}",
                params=self.dump_model(p),
                validation={
                    "passed": True,
                    "checks": [
                        {"name": "target_scene_resolution", "status": "passed"},
                        {"name": "headless_attach", "status": "passed"},
                    ],
                },
                rollback={"available": False, "strategy": "restore_scene_from_backup_or_vcs"},
            )
        else:
            return self.build_result(
                success=False,
                message="挂载失败",
                params=self.dump_model(p),
                error=result.error,
                validation={"passed": False, "issues": ["attach_script_failed"]},
            )

    def _generate_editor_script(self, p: AttachParams) -> str:
        return f'''
func _run(plugin: EditorPlugin):
	var root = plugin.get_editor_interface().get_edited_scene_root()
	var target = root.get_node_or_null(NodePath("{p.target_node_path}"))
	if target:
		var script = load("{p.script_path}")
		target.set_script(script)
		print("✅ Attached {p.script_path} to {p.target_node_path}")
'''

    def _generate_headless_script(self, p: AttachParams, scene_path: str) -> str:
        return f'''@tool
extends EditorScript
func _run():
	var scene = load("{scene_path}")
	if not scene is PackedScene: return
	var root = scene.instantiate()
	var target = root.get_node_or_null(NodePath("{p.target_node_path}"))
	if target:
		var script = load("{p.script_path}")
		target.set_script(script)
		var new_scene = PackedScene.new()
		new_scene.pack(root)
		ResourceSaver.save(new_scene, "{scene_path}")
		print("✅ Headless Attached {p.script_path}")
'''

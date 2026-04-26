"""
场景实例管理技能 (Scene Instantiation Skill)
职责: 在当前场景中实例化并添加已有的场景预制件 (.tscn)
"""

from typing import Dict, Any, Optional, List
from pydantic import BaseModel, Field
from ..base import BaseSkill, SkillMetadata
from ...models import Task, ToolResult, Artifact


class InstantiationParams(BaseModel):
    instance_scene_path: str = Field(description="要实例化的场景路径, 如 res://scenes/Player.tscn")
    parent_node_path: Optional[str] = Field(None, description="父节点路径, 默认根节点")
    instance_name: Optional[str] = Field(None, description="实例后的节点名称")
    count: int = Field(default=1, description="生成的数量")


class InstantiateSkill(BaseSkill):
    metadata = SkillMetadata(
        name="instantiate_scene_prefab",
        description="将一个场景文件 (.tscn) 作为实例添加到当前场景树中。支持批量生成和自动重命名。",
        category="dev",
        tags=["scene", "prefab", "instantiation", "editor_plugin"]
    )
    input_model = InstantiationParams

    def execute(self, task: Task, params: Dict[str, Any]) -> ToolResult:
        p = InstantiationParams(**params)
        
        # 1. 检查编辑器状态
        editor_state = task.context.get("editor_state", {})
        if not editor_state.get("is_active"):
            return self.build_result(
                success=False,
                message="编辑器离线, 无法实时执行实例化动作",
                params=self.dump_model(p),
                validation={"passed": False, "issues": ["editor_offline"]},
            )
            
        task.add_log(f"🏗️ 正在实例化场景: {p.instance_scene_path} (数量: {p.count})")
        
        # 2. 生成实例化脚本
        script = self._generate_instantiate_script(p)
        
        artifact = Artifact(
            name=f"instantiate_{p.instance_name or 'prefab'}.gd",
            path="internal://",
            type="editor_script",
            content=script
        )
        
        # 3. 更新蓝图
        blueprint = task.context.get("blueprint_manager")
        if blueprint:
            from ...tools.blueprint_manager import Feature
            blueprint.add_feature(Feature(
                name=f"Instance_{p.instance_name or 'Object'}",
                description=f"在场景中实例化了 {p.count} 个 {p.instance_scene_path}",
                creation_skill=self.metadata.name,
                creation_params=params
            ))

        return self.build_result(
            success=True,
            message=f"已下发实例化指令：将 {p.instance_scene_path} 注入到当前场景。",
            params=self.dump_model(p),
            artifacts=[artifact],
            validation={
                "passed": True,
                "checks": [
                    {"name": "editor_online", "status": "passed"},
                    {"name": "instantiate_script_generated", "status": "passed"},
                ],
            },
            rollback={"available": False, "strategy": "wait_for_editor_confirmation"},
        )

    def _generate_instantiate_script(self, p: InstantiationParams) -> str:
        find_parent = "plugin.get_editor_interface().get_edited_scene_root()"
        if p.parent_node_path:
            find_parent += f'.get_node_or_null(NodePath("{p.parent_node_path}"))'
            
        return f'''
func _run(plugin: EditorPlugin):
	var scene_root = plugin.get_editor_interface().get_edited_scene_root()
	if not scene_root:
		print("❌ Error: No active scene root")
		return
		
	var parent = {find_parent}
	if not parent:
		print("⚠️ Parent path not found, defaulting to root")
		parent = scene_root
		
	var prefab = load("{p.instance_scene_path}")
	if not prefab:
		print("❌ Error: Prefab not found at {p.instance_scene_path}")
		return
		
	for i in range({p.count}):
		var instance = prefab.instantiate()
		if "{p.instance_name or ''}" != "":
			instance.name = "{p.instance_name or ''}" + str(i) if {p.count} > 1 else "{p.instance_name or ''}"
		
		parent.add_child(instance)
		instance.owner = scene_root
		
	print("✅ Success: Instantiated {p.count} items")
'''

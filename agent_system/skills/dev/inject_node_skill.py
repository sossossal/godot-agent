"""
Godot 节点注入技能 (Inject Node Skill)
职责: 在当前编辑器场景树中添加新节点, 感知选中节点并作为父节点
"""

from typing import Dict, Any, Optional
from pydantic import BaseModel, Field
from ..base import BaseSkill, SkillMetadata
from ...models import Task, ToolResult, Artifact


class InjectNodeParams(BaseModel):
    """节点注入参数"""
    node_type: str = Field(default="Node2D", description="节点类型 (如 Sprite2D, Button)")
    node_name: Optional[str] = Field(None, description="节点名称, 为空则使用类型名")
    parent_path: Optional[str] = Field(None, description="父节点路径, 为空则根据上下文自动感知 (选中节点)")


class InjectNodeSkill(BaseSkill):
    """节点注入技能"""
    
    metadata = SkillMetadata(
        name="inject_godot_node",
        description="在当前编辑器场景中动态添加新节点, 支持智能父节点感知",
        category="dev",
        tags=["node", "scene_tree", "editor_plugin"]
    )
    
    input_model = InjectNodeParams

    def execute(self, task: Task, params: Dict[str, Any]) -> ToolResult:
        p = InjectNodeParams(**params)
        node_type = p.node_type
        node_name = p.node_name or node_type
        
        task.add_log(f"🏗️ 准备注入节点: {node_type} (Name: {node_name})")
        
        # 1. 检查编辑器
        editor_state = task.context.get("editor_state", {})
        if not editor_state.get("is_active"):
            return self.build_result(
                success=False,
                message="编辑器离线, 无法进行实时节点注入",
                params=self.dump_model(p),
                validation={"passed": False, "issues": ["editor_offline"]},
            )
            
        # 2. 确定父节点逻辑
        parent_path = p.parent_path
        find_logic = "plugin.get_editor_interface().get_edited_scene_root()"
        
        # 智能感知
        if not parent_path:
            selected_node_paths = editor_state.get("selected_node_paths", [])
            if selected_node_paths:
                parent_path = selected_node_paths[0]
                task.add_log(f"🎯 智能感知: 自动定位到选中父节点 '{parent_path}'")
                
                if parent_path != ".":
                    find_logic = f'plugin.get_editor_interface().get_edited_scene_root().get_node_or_null(NodePath("{parent_path}"))'

        # 3. 生成注入脚本
        script = f'''
func _run(plugin: EditorPlugin):
    var parent = {find_logic}
    if parent:
        var node = {node_type}.new()
        node.name = "{node_name}"
        parent.add_child(node)
        node.owner = plugin.get_editor_interface().get_edited_scene_root()
        print("✅ Success: Added {node_name} under %s" % parent.name)
    else:
        print("❌ Error: Parent node not found")
'''
        artifact = Artifact(name=f"inject_{node_name}.gd", path="internal://", type="editor_script", content=script)
        return self.build_result(
            success=True,
            message=f"已下发节点注入指令: {node_name}",
            params=self.dump_model(p),
            artifacts=[artifact],
            validation={
                "passed": True,
                "checks": [
                    {"name": "editor_online", "status": "passed"},
                    {"name": "editor_script_generated", "status": "passed"},
                ],
            },
            rollback={"available": False, "strategy": "wait_for_editor_confirmation"},
        )

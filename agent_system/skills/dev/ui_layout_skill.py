"""
UI 自动布局技能 (UI Auto-Layout Skill)
职责: 根据结构化描述自动生成复杂的嵌套 UI 节点树 (基于 Control 容器)
"""

from typing import Dict, Any, List, Optional
from pydantic import BaseModel, Field
from ..base import BaseSkill, SkillMetadata
from ...models import Task, ToolResult, Artifact


class UIElement(BaseModel):
    type: str = Field(description="节点类型, 如 VBoxContainer, Button, Label")
    name: str = Field(description="节点名称")
    text: Optional[str] = Field(None, description="文本内容 (针对 Button/Label)")
    children: List['UIElement'] = Field(default_factory=list, description="子节点列表")


class UILayoutParams(BaseModel):
    root_name: str = Field(default="UIRoot", description="根容器名称")
    layout_type: str = Field(default="CenterContainer", description="根容器类型")
    elements: List[UIElement] = Field(default_factory=list, description="UI 元素列表")


class UILayoutSkill(BaseSkill):
    metadata = SkillMetadata(
        name="auto_layout_ui",
        description="自动构建嵌套的 UI 布局。支持容器嵌套、按钮和标签的批量生成与对齐。",
        category="dev",
        tags=["ui", "layout", "control", "editor_plugin"]
    )
    input_model = UILayoutParams

    def execute(self, task: Task, params: Dict[str, Any]) -> ToolResult:
        p = UILayoutParams(**params)
        
        # 1. 检查编辑器状态
        editor_state = task.context.get("editor_state", {})
        if not editor_state.get("is_active"):
            return self.build_result(
                success=False,
                message="编辑器离线, 无法进行实时 UI 布局",
                params=self.dump_model(p),
                validation={"passed": False, "issues": ["editor_offline"]},
            )
            
        # 2. 获取蓝图样式 (🆕 新增)
        blueprint = task.context.get("blueprint_manager")
        styles = blueprint.blueprint.ui_styles if blueprint else {}
        
        task.add_log(f"🎨 正在构建 UI 布局 (样式继承: {styles})")
        
        # 3. 生成递归构建脚本
        script = self._generate_ui_script(p, styles)
        
        artifact = Artifact(
            name=f"ui_layout_{p.root_name}.gd",
            path="internal://",
            type="editor_script",
            content=script
        )
        
        return self.build_result(
            success=True,
            message=f"已生成 UI 布局指令: {p.root_name}。已应用全局视觉规范。",
            params=self.dump_model(p),
            artifacts=[artifact],
            validation={
                "passed": True,
                "checks": [
                    {"name": "editor_online", "status": "passed"},
                    {"name": "ui_layout_script_generated", "status": "passed"},
                ],
            },
            rollback={"available": False, "strategy": "wait_for_editor_confirmation"},
        )

    def _generate_ui_script(self, p: UILayoutParams, styles: Dict[str, Any]) -> str:
        """生成用于在编辑器中递归创建 UI 的脚本"""
        
        primary_color = styles.get("primary_color", "#ffffff")
        radius = styles.get("corner_radius", 4)

        def build_node_code(elem: UIElement, parent_var: str, indent: int) -> str:
            v_name = f"node_{elem.name.replace(' ', '_')}"
            lines = [
                f"{'	' * indent}var {v_name} = {elem.type}.new()",
                f"{'	' * indent}{v_name}.name = \"{elem.name}\"",
            ]
            
            # 应用样式 (针对 Control 节点)
            if elem.type in ["Button", "Panel", "PanelContainer"]:
                lines.append(f"{'	' * indent}{v_name}.add_theme_color_override(\"font_color\", Color(\"{primary_color}\"))")
            
            if elem.text:
                lines.append(f"{'	' * indent}if {v_name}.has_method(\"set_text\"): {v_name}.text = \"{elem.text}\"")
            
            lines.append(f"{'	' * indent}{parent_var}.add_child({v_name})")
            lines.append(f"{'	' * indent}{v_name}.owner = plugin.get_editor_interface().get_edited_scene_root()")
            
            for child in elem.children:
                lines.append(build_node_code(child, v_name, indent))
            
            return "\n".join(lines)

        element_codes = []
        for e in p.elements:
            element_codes.append(build_node_code(e, "root", 1))

        return f"""
func _run(plugin: EditorPlugin):
	var scene_root = plugin.get_editor_interface().get_edited_scene_root()
	if not scene_root:
		print("❌ Error: No active scene root")
		return
		
	var root = {p.layout_type}.new()
	root.name = "{p.root_name}"
	if root is Control:
		root.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
		
	scene_root.add_child(root)
	root.owner = scene_root
	
{chr(10).join(element_codes)}
	print("✅ Success: Built UI layout {p.root_name}")
"""

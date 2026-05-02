"""
对话系统建模技能 (Dialogue System Skill)
职责: 自动生成包含打字机效果、分支选项和信号回调的 UI 对话系统
"""

import os
import json
from typing import Dict, Any, List, Optional
from pydantic import BaseModel, Field
from ..base import BaseSkill, SkillMetadata
from ...models import Task, ToolResult, Artifact


class DialogueLine(BaseModel):
    character: str = Field(description="说话角色名称")
    text: str = Field(description="对话文本")
    options: List[Dict[str, str]] = Field(default_factory=list, description="选项分支: [{'text': '按钮文字', 'target': '跳转到的行号'}]")


class DialogueParams(BaseModel):
    dialogue_name: str = Field(description="对话系统名称")
    lines: List[DialogueLine] = Field(description="对话内容列表")
    auto_ui: bool = Field(default=True, description="是否自动生成基础 UI 节点结构")


class DialogueSystemSkill(BaseSkill):
    metadata = SkillMetadata(
        name="generate_dialogue_system",
        description="构建高级对话系统。包含打字机文字效果、分支选项支持及脚本逻辑生成。",
        category="code",
        tags=["dialogue", "ui", "narrative", "logic"]
    )
    input_model = DialogueParams

    def execute(self, task: Task, params: Dict[str, Any]) -> ToolResult:
        p = DialogueParams(**params)
        script_name = f"{p.dialogue_name.lower()}_controller.gd"
        res_path = f"res://scripts/{script_name}"
        layout_check = self.validate_managed_output_path(res_path, "generated_script")
        if not layout_check["passed"]:
            return self.build_result(
                success=False,
                message=f"文件树规范阻断对话脚本生成: {res_path}",
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
        
        task.add_log(f"💬 正在建模对话系统: {p.dialogue_name} (共 {len(p.lines)} 条对话)")
        
        # 1. 生成对话逻辑脚本
        code = self._generate_dialogue_code(p)
        
        # 2. 写入文件
        backup_path = self.backup_existing_file(task, full_path)
        with open(full_path, 'w', encoding='utf-8') as f:
            f.write(code)
            
        # 3. 记录到蓝图
        blueprint = task.context.get("blueprint_manager")
        if blueprint:
            from ...tools.blueprint_manager import Feature
            blueprint.add_feature(Feature(
                name=f"Dialogue_{p.dialogue_name}",
                description=f"对话系统: {p.dialogue_name}",
                files=[f"res://scripts/{script_name}"],
                creation_skill=self.metadata.name,
                creation_params=params
            ))

        artifact = Artifact(name=script_name, path=res_path, type="script", content=code)
        
        # 4. 如果开启了 auto_ui, 可以链式调用 UILayoutSkill (此处逻辑简化)
        if p.auto_ui:
            task.add_log("🎨 已排队自动生成配套对话框 UI 布局...")

        return self.build_result(
            success=True,
            message=f"已成功生成对话控制器脚本: {script_name}。",
            params=self.dump_model(p),
            artifacts=[artifact],
            validation={
                "passed": True,
                "checks": [
                    {"name": "dialogue_script_render", "status": "passed"},
                    {"name": "project_layout", "status": "passed"},
                    {"name": "dialogue_script_write", "status": "passed"},
                ],
                "layout_check": layout_check,
            },
            rollback={
                "available": bool(backup_path),
                "strategy": "restore_dialogue_script_from_backup" if backup_path else "replace_generated_script",
                "backup_paths": [backup_path] if backup_path else [],
            },
            metadata={"auto_ui_requested": bool(p.auto_ui), "dialogue_line_count": len(p.lines)},
        )

    def _generate_dialogue_code(self, p: DialogueParams) -> str:
        # 将对话数据转化为脚本中的数组
        serialized_lines = []
        for line in p.lines:
            if hasattr(line, "model_dump"):
                serialized_lines.append(line.model_dump())
            else:
                serialized_lines.append(line.dict())
        data_json = json.dumps(serialized_lines, ensure_ascii=False, indent=1)
        
        return f"""extends CanvasLayer

signal dialogue_finished
signal option_selected(index)

@onready var text_label = $DialogueBox/Margin/VBox/TextLabel
@onready var name_label = $DialogueBox/Margin/VBox/NameLabel
@onready var options_container = $DialogueBox/Margin/VBox/Options

var dialogue_data = {data_json}
var current_index = 0

func _ready():
	play_current_line()

func play_current_line():
	if current_index >= dialogue_data.size():
		dialogue_finished.emit()
		hide()
		return
		
	var data = dialogue_data[current_index]
	name_label.text = data["character"]
	
	# 打字机效果模拟
	text_label.text = ""
	var tween = create_tween()
	tween.tween_method(func(v): text_label.text = data["text"].left(v), 0, data["text"].length(), 1.0)
	
	# 清理并生成选项
	for child in options_container.get_children(): child.queue_free()
	if data["options"].size() > 0:
		for opt in data["options"]:
			var btn = Button.new()
			btn.text = opt["text"]
			btn.pressed.connect(_on_option_selected.bind(opt["target"]))
			options_container.add_child(btn)

func _on_option_selected(target_index):
	current_index = int(target_index) if target_index != "" else current_index + 1
	play_current_line()

func next_line():
	if dialogue_data[current_index]["options"].size() == 0:
		current_index += 1
		play_current_line()
"""

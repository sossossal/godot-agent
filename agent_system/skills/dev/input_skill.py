"""
输入映射管理技能 (Input Mapping Skill)
职责: 自动化维护项目的输入映射 (Input Map), 绑定动作与按键
"""

import os
from typing import Dict, Any
from pydantic import BaseModel, Field
from ..base import BaseSkill, SkillMetadata
from ...models import Task, ToolResult, Artifact


class InputParams(BaseModel):
    action_name: str = Field(description="动作名称, 如 'jump', 'move_left'")
    key_code: str = Field(description="绑定的按键名称, 如 'Space', 'W', 'Enter'")
    event_type: str = Field(default="InputEventKey", description="事件类型")


class InputMappingSkill(BaseSkill):
    metadata = SkillMetadata(
        name="manage_input_mapping",
        description="管理项目的输入映射。将动作(Action)与物理按键或鼠标事件进行绑定。",
        category="dev",
        tags=["input", "config", "control"]
    )
    input_model = InputParams

    def execute(self, task: Task, params: Dict[str, Any]) -> ToolResult:
        p = InputParams(**params)
        project_file = os.path.join(self.godot_cli.project_path or ".", "project.godot")
        
        if not os.path.exists(project_file):
            return self.build_result(
                success=False,
                message="未找到 project.godot 文件",
                params=self.dump_model(p),
                validation={"passed": False, "issues": ["missing_project_file"]},
            )
            
        task.add_log(f"🎮 正在配置输入映射: {p.action_name} -> {p.key_code}")
        
        with open(project_file, 'r', encoding='utf-8') as f:
            lines = f.readlines()
        
        input_section_index = -1
        for i, line in enumerate(lines):
            if "[input]" in line:
                input_section_index = i
                break

        action_prefix = f"{p.action_name}="
        action_exists = any(line.startswith(action_prefix) for line in lines)
        backup_path = None

        if not action_exists:
            new_entry = f'{p.action_name}={{"deadzone":0.5,"events":[Object(InputEventKey,"keycode":0,"physical_keycode":{self._get_keycode(p.key_code)})]}}\n'
            if input_section_index != -1:
                lines.insert(input_section_index + 1, new_entry)
            else:
                lines.append("\n[input]\n")
                lines.append(new_entry)

            backup_path = self.backup_existing_file(task, project_file)
            with open(project_file, 'w', encoding='utf-8') as f:
                f.writelines(lines)
        else:
            task.add_log(f"输入动作 '{p.action_name}' 已存在，跳过重复写入。")
            
        blueprint = task.context.get("blueprint_manager")
        if blueprint:
            from ...tools.blueprint_manager import Feature
            blueprint.add_feature(Feature(
                name=f"Input_{p.action_name}",
                description=f"映射动作 {p.action_name} 到按键 {p.key_code}",
                creation_skill=self.metadata.name,
                creation_params=params
            ))

        project_content = "".join(lines)
        return self.build_result(
            success=True,
            message=(
                f"已成功将动作 '{p.action_name}' 绑定到按键 '{p.key_code}'。"
                if not action_exists
                else f"动作 '{p.action_name}' 已存在，保持当前输入映射不变。"
            ),
            params=self.dump_model(p),
            artifacts=[
                Artifact(
                    name="project.godot",
                    path="res://project.godot",
                    type="config",
                    content=project_content,
                )
            ],
            validation={
                "passed": True,
                "checks": [
                    {"name": "project_file_exists", "status": "passed"},
                    {"name": "input_mapping_present", "status": "passed"},
                ],
            },
            rollback={
                "available": bool(backup_path),
                "strategy": "restore_project_settings_from_backup" if backup_path else "no_write_required",
                "backup_paths": [backup_path] if backup_path else [],
            },
        )

    def _get_keycode(self, key_name: str) -> int:
        """映射常用按键名到 Godot KeyCode (部分常用预设)"""
        mapping = {
            "Space": 32, "Enter": 4194309, "Escape": 4194305,
            "W": 87, "A": 65, "S": 83, "D": 68,
            "Up": 4194320, "Down": 4194322, "Left": 4194319, "Right": 4194321
        }
        return mapping.get(key_name, 0)

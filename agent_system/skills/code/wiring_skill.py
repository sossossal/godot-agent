"""
信号自动连接技能 (Signal Wiring Skill)
职责: 自动在指定脚本中插入信号连接代码 (如 SignalBus.signal.connect(callback))
"""

import os
from typing import Dict, Any
from pydantic import BaseModel, Field
from ..base import BaseSkill, SkillMetadata
from ...models import Task, ToolResult, Artifact


class WiringParams(BaseModel):
    target_script: str = Field(description="目标脚本路径, 如 res://scripts/ui.gd")
    signal_bus_name: str = Field(default="SignalBus", description="信号总线单例名称")
    signal_name: str = Field(description="信号名称")
    callback_name: str = Field(description="回调函数名称")


class SignalWiringSkill(BaseSkill):
    metadata = SkillMetadata(
        name="wire_signal_connection",
        description="在脚本中自动插入信号连接逻辑, 实现模块间通信",
        category="code",
        tags=["signals", "logic", "automation"]
    )
    input_model = WiringParams

    def execute(self, task: Task, params: Dict[str, Any]) -> ToolResult:
        p = WiringParams(**params)
        full_path = self.resolve_project_file_path(p.target_script)
        
        if not os.path.exists(full_path):
            return self.build_result(
                success=False,
                message=f"目标脚本不存在: {p.target_script}",
                params=self.dump_model(p),
                validation={"passed": False, "issues": ["missing_target_script"]},
            )
            
        task.add_log(f"🔌 正在为脚本 {p.target_script} 连接信号: {p.signal_name}")
        
        with open(full_path, 'r', encoding='utf-8') as f:
            content = f.read()
            
        # 1. 检查是否已经连接
        connect_line = f"{p.signal_bus_name}.{p.signal_name}.connect({p.callback_name})"
        if connect_line in content:
            return self.build_result(
                success=True,
                message="信号已连接, 无需重复操作。",
                params=self.dump_model(p),
                artifacts=[Artifact(name=os.path.basename(full_path), path=p.target_script, type="script", content=content)],
                validation={
                    "passed": True,
                    "checks": [
                        {"name": "target_script_exists", "status": "passed"},
                        {"name": "signal_connection_present", "status": "passed"},
                    ],
                },
                rollback={"available": False, "strategy": "no_write_required"},
            )
            
        # 2. 插入连接逻辑到 _ready 函数
        if "func _ready()" in content:
            # 在 _ready 下方插入
            content = content.replace("func _ready():", f"func _ready():\n\t{connect_line}")
        else:
            # 创建 _ready 函数
            content += f"\n\nfunc _ready():\n\t{connect_line}\n"
            
        # 3. 确保回调函数存在 (极简处理: 若不存在则创建空函数)
        if f"func {p.callback_name}" not in content:
            content += f"\n\nfunc {p.callback_name}(args = None):\n\tpass # 由 Agent 自动生成的信号回调\n"
            task.add_log(f"📝 已自动补全回调函数占位符: {p.callback_name}")

        backup_path = self.backup_existing_file(task, full_path)
        with open(full_path, 'w', encoding='utf-8') as f:
            f.write(content)
            
        artifact = Artifact(name=os.path.basename(full_path), path=p.target_script, type="script", content=content)
        return self.build_result(
            success=True,
            message=f"已成功将 {p.signal_name} 连接至 {p.target_script} 的 {p.callback_name} 函数。",
            params=self.dump_model(p),
            artifacts=[artifact],
            validation={
                "passed": True,
                "checks": [
                    {"name": "target_script_exists", "status": "passed"},
                    {"name": "signal_connection_inserted", "status": "passed"},
                ],
            },
            rollback={
                "available": bool(backup_path),
                "strategy": "restore_script_from_backup" if backup_path else "replace_generated_script",
                "backup_paths": [backup_path] if backup_path else [],
            },
        )

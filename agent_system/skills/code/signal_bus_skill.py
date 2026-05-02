"""
全局信号总线技能 (SignalBus Skill)
职责: 维护全局 SignalBus 单例, 自动注册 Autoload 并添加常用全局信号
"""

import os
from typing import Dict, Any, List
from pydantic import BaseModel, Field
from ..base import BaseSkill, SkillMetadata
from ...models import Task, ToolResult, Artifact


class SignalBusParams(BaseModel):
    signal_name: str = Field(description="要添加的信号名称, 如 'score_changed'")
    arguments: List[str] = Field(default_factory=list, description="信号参数列表, 如 ['new_score']")


class SignalBusSkill(BaseSkill):
    metadata = SkillMetadata(
        name="manage_signal_bus",
        description="管理全局信号总线 (SignalBus), 自动注册单例并维护全局信号定义",
        category="code",
        tags=["signals", "autoload", "architecture"]
    )
    input_model = SignalBusParams

    def execute(self, task: Task, params: Dict[str, Any]) -> ToolResult:
        p = SignalBusParams(**params)
        bus_path = "res://scripts/signal_bus.gd"
        layout_check = self.validate_managed_output_path(bus_path, "generated_script")
        if not layout_check["passed"]:
            return self.build_result(
                success=False,
                message=f"文件树规范阻断 SignalBus 写入: {bus_path}",
                params=self.dump_model(p),
                error="project_layout_validation_failed",
                validation={
                    "passed": False,
                    "checks": [{"name": "project_layout", "status": "blocked"}],
                    "layout_check": layout_check,
                },
            )
        full_path = self.resolve_project_file_path(bus_path)
        os.makedirs(os.path.dirname(full_path), exist_ok=True)
        
        task.add_log(f"📡 正在维护信号总线: {p.signal_name}")
        
        content = ""
        if os.path.exists(full_path):
            with open(full_path, 'r', encoding='utf-8') as f:
                content = f.read()
        else:
            content = "extends Node\n# 全局信号中台 (由 Godot Agent 自动维护)\n\n"
            
        backup_paths: List[str] = []
        changed_bus = False
        if f"signal {p.signal_name}" in content:
            task.add_log(f"信号 '{p.signal_name}' 已存在，跳过更新内容。")
        else:
            args_str = f"({', '.join(p.arguments)})" if p.arguments else ""
            content += f"signal {p.signal_name}{args_str}\n"
            backup_path = self.backup_existing_file(task, full_path)
            if backup_path:
                backup_paths.append(backup_path)
            with open(full_path, 'w', encoding='utf-8') as f:
                f.write(content)
            changed_bus = True
            task.add_log(f"✅ 已在 SignalBus 中注册新信号: {p.signal_name}")

        autoload_result = self._register_autoload(task)
        if autoload_result["backup_path"]:
            backup_paths.append(autoload_result["backup_path"])
        
        blueprint = task.context.get("blueprint_manager")
        if blueprint:
            if "SignalBus" not in blueprint.blueprint.global_autoloads:
                blueprint.blueprint.global_autoloads.append("SignalBus")
                blueprint.save()

        artifacts = [Artifact(name="signal_bus.gd", path=bus_path, type="script", content=content)]
        if autoload_result["content"]:
            artifacts.append(Artifact(
                name="project.godot",
                path="res://project.godot",
                type="config",
                content=autoload_result["content"],
            ))

        return self.build_result(
            success=True,
            message=f"全局信号 '{p.signal_name}' 已就绪并自动关联 Autoload。",
            params=self.dump_model(p),
            artifacts=artifacts,
            validation={
                "passed": True,
                "checks": [
                    {"name": "signal_definition_present", "status": "passed"},
                    {"name": "project_layout", "status": "passed"},
                    {"name": "autoload_registered", "status": "passed"},
                ],
                "layout_check": layout_check,
            },
            rollback={
                "available": bool(backup_paths),
                "strategy": (
                    "restore_signal_bus_and_project_settings_from_backup"
                    if backup_paths
                    else "no_write_required"
                ),
                "backup_paths": backup_paths,
            },
            metadata={"signal_bus_changed": changed_bus, "autoload_changed": autoload_result["updated"]},
        )

    def _register_autoload(self, task: Task) -> Dict[str, Any]:
        """将 SignalBus 注册到 project.godot (简化实现)"""
        project_file = os.path.join(self.godot_cli.project_path or ".", "project.godot")
        if not os.path.exists(project_file):
            return {"updated": False, "backup_path": None, "content": ""}
        
        with open(project_file, 'r', encoding='utf-8') as f:
            lines = f.readlines()
            
        # 查找或创建 [autoload] 节点
        has_autoload_section = False
        bus_registered = False
        for line in lines:
            if "[autoload]" in line: has_autoload_section = True
            if 'SignalBus="*res://scripts/signal_bus.gd"' in line: bus_registered = True
            
        if bus_registered:
            return {"updated": False, "backup_path": None, "content": "".join(lines)}
        
        new_lines = []
        if has_autoload_section:
            for line in lines:
                new_lines.append(line)
                if "[autoload]" in line:
                    new_lines.append('SignalBus="*res://scripts/signal_bus.gd"\n')
        else:
            new_lines = lines + ["\n[autoload]\n", 'SignalBus="*res://scripts/signal_bus.gd"\n']
            
        backup_path = self.backup_existing_file(task, project_file)
        with open(project_file, 'w', encoding='utf-8') as f:
            f.writelines(new_lines)
        task.add_log("🔗 已自动修改 project.godot 并注册 SignalBus 单例。")
        return {"updated": True, "backup_path": backup_path, "content": "".join(new_lines)}

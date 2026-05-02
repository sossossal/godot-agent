"""
Godot 场景创建技能 (Create Scene Skill)
职责: 初始化 .tscn 场景文件, 支持 Node2D, Node3D 和 UI (Control) 根节点
"""

from typing import Dict, Any, Optional
from pydantic import BaseModel, Field
from ..base import BaseSkill, SkillMetadata
from ...models import Task, ToolResult, Artifact
from ...tools.scene_tools import SceneTools


class CreateSceneParams(BaseModel):
    """场景创建参数"""
    scene_name: str = Field(description="场景名称 (不含后缀)")
    root_type: str = Field(default="Node2D", description="根节点类型: Node2D, Node3D, Control")
    save_path: str = Field(default="res://scenes/", description="保存目录")


class CreateSceneSkill(BaseSkill):
    """场景创建技能"""
    
    metadata = SkillMetadata(
        name="create_godot_scene",
        description="创建一个新的 Godot 场景文件 (.tscn), 支持 2D/3D/UI 根节点",
        category="dev",
        tags=["scene", "create", "initialize"]
    )
    
    input_model = CreateSceneParams

    def execute(self, task: Task, params: Dict[str, Any]) -> ToolResult:
        p = CreateSceneParams(**params)
        scene_name = p.scene_name
        root_type = p.root_type
        
        base_path = f"res://scenes/{scene_name}.tscn"
        full_path = base_path
        layout_check = self.validate_managed_output_path(full_path, "generated_scene")
        if not layout_check["passed"]:
            return self.build_result(
                success=False,
                message=f"文件树规范阻断场景创建: {full_path}",
                params=self.dump_model(p),
                error="project_layout_validation_failed",
                validation={
                    "passed": False,
                    "checks": [{"name": "project_layout", "status": "blocked"}],
                    "layout_check": layout_check,
                },
            )
        task.context["scene_path"] = full_path
        task.context["scene_path_source"] = "developer"
        
        task.add_log(f"🏗️ 准备创建场景: {full_path} (Type: {root_type})")
        
        # 1. 检查编辑器是否在线 (同步执行)
        editor_state = task.context.get("editor_state", {})
        if editor_state.get("is_active"):
            task.add_log("🎯 编辑器在线: 生成实时场景创建脚本")
            script = SceneTools.generate_editor_scene_script(scene_name, root_type)
            # 注意: 这里实时脚本目前由插件决定保存路径, 
            # 插件逻辑也需要适配生成的 root 路径, 此处先标记 Artifact 路径
            artifact = Artifact(
                name=f"create_{scene_name}.gd",
                path="internal://",
                type="editor_script",
                content=script,
                metadata={"scene_path": full_path}
            )
            return self.build_result(
                success=True, 
                message=f"已生成场景创建指令: {scene_name}", 
                params=self.dump_model(p),
                artifacts=[artifact, Artifact(name=f"{scene_name}.tscn", path=full_path, type="scene")],
                validation={
                    "passed": True,
                    "checks": [
                        {"name": "scene_path_resolution", "status": "passed"},
                        {"name": "project_layout", "status": "passed"},
                        {"name": "editor_dispatch_ready", "status": "passed"},
                    ],
                    "layout_check": layout_check,
                },
                rollback={"available": False, "strategy": "wait_for_editor_confirmation"},
            )
            
        # 2. 离线/CLI 模式
        script = SceneTools.generate_headless_scene_script(scene_name, root_type)
        # 注入路径修复逻辑 (针对 headless 脚本)
        script = script.replace(f'res://scenes/{scene_name}.tscn', full_path)
        
        result = self.godot_cli.execute_editor_script(script)
        
        if result.success:
            return self.build_result(
                success=True, 
                message=f"已成功创建场景文件: {full_path}", 
                params=self.dump_model(p),
                artifacts=[Artifact(name=f"{scene_name}.tscn", path=full_path, type="scene")],
                validation={
                    "passed": True,
                    "checks": [
                        {"name": "scene_path_resolution", "status": "passed"},
                        {"name": "project_layout", "status": "passed"},
                        {"name": "headless_scene_create", "status": "passed"},
                    ],
                    "layout_check": layout_check,
                },
                rollback={"available": False, "strategy": "delete_created_scene_or_restore_from_vcs"},
            )
        else:
            return self.build_result(
                success=False,
                message=f"场景创建失败: {result.message}",
                params=self.dump_model(p),
                error=result.error,
                validation={"passed": False, "issues": ["scene_create_failed"]},
            )

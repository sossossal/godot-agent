"""
Godot 场景冒烟测试技能 (Smoke Test Skill)
职责: 启动指定场景并验证其加载成功, 支持编辑器内实时运行或 CLI Headless 运行
"""

import re
from pathlib import Path
from typing import Dict, Any, Optional
from pydantic import BaseModel, Field
from ..base import BaseSkill, SkillMetadata
from ...models import Task, ToolResult, Artifact


class SmokeTestParams(BaseModel):
    """冒烟测试参数"""
    scene_path: Optional[str] = Field(None, description="要测试的场景路径 (如 res://scenes/Main.tscn)")
    use_editor: bool = Field(True, description="是否优先在编辑器中运行")


class SmokeTestSkill(BaseSkill):
    """场景冒烟测试技能"""
    
    metadata = SkillMetadata(
        name="smoke_test_scene",
        description="运行 Godot 场景冒烟测试, 验证场景加载是否正常",
        category="test",
        tags=["test", "smoke", "run"]
    )
    
    input_model = SmokeTestParams

    def execute(self, task: Task, params: Dict[str, Any]) -> ToolResult:
        p = SmokeTestParams(**params)
        scene_path = self._resolve_path(task, p.scene_path)
        
        if not scene_path:
            return self.build_result(
                success=False,
                message="未找到可测试的场景路径, 请明确指定或在编辑器中打开场景",
                params=self.dump_model(p),
                validation={"passed": False, "issues": ["missing_scene_path"]},
            )

        task.context.setdefault("scene_path", scene_path)
        task.context.setdefault(
            "scene_path_source",
            "editor_state" if scene_path == task.context.get("editor_state", {}).get("current_scene") else "prompt",
        )
        task.context.setdefault("test_scene_path", scene_path)
        task.context.setdefault("test_scene_source", "context")
            
        task.add_log(f"🚀 启动场景冒烟测试: {scene_path}")
        
        # 1. 如果要求在编辑器运行且插件在线
        # 这里逻辑简化，实际会发送指令给插件
        
        # 2. 调用 Godot CLI 运行场景
        result = self.godot_cli.run_scene(scene_path)
        
        if result.success:
            return self.build_result(
                success=True,
                message=f"场景冒烟测试通过: {scene_path}",
                params=self.dump_model(p),
                validation={
                    "passed": True,
                    "checks": [
                        {"name": "scene_resolution", "status": "passed"},
                        {"name": "scene_load", "status": "passed"},
                    ],
                },
                rollback={"available": False, "strategy": "test_only_no_write"},
            )
        else:
            return self.build_result(
                success=False,
                message=f"场景加载失败: {result.message}",
                params=self.dump_model(p),
                error=result.error,
                validation={"passed": False, "issues": ["scene_load_failed"]},
            )

    def _resolve_path(self, task: Task, param_path: Optional[str]) -> Optional[str]:
        if param_path: return param_path
        
        # 从上下文推断
        editor_state = task.context.get("editor_state", {})
        current_scene = editor_state.get("current_scene")
        if current_scene and current_scene != "None":
            return current_scene
            
        # 从历史产物推断
        for art in reversed(task.artifacts):
            if art.type == "scene":
                return art.path

        project_path = getattr(self.godot_cli, "project_path", None)
        if project_path:
            project_root = Path(project_path)
            scene_candidates = sorted(project_root.rglob("*.tscn"))
            if scene_candidates:
                first_scene = scene_candidates[0].relative_to(project_root).as_posix()
                return f"res://{first_scene}"
        return None

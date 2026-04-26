"""
快速截图技能 (Quick Capture Skill)
职责: 运行当前或指定场景并立即抓取一张快照, 用于对话反馈
"""

import time
import os
import base64
from pathlib import Path
from typing import Dict, Any, Optional
from pydantic import BaseModel, Field
from ..base import BaseSkill, SkillMetadata
from ...models import Task, ToolResult, Artifact


class CaptureParams(BaseModel):
    scene_path: Optional[str] = Field(None, description="要截图的场景路径")
    delay: float = Field(1.0, description="运行后等待多久再截图 (秒)")


class QuickCaptureSkill(BaseSkill):
    metadata = SkillMetadata(
        name="quick_capture_scene",
        description="启动 Godot 场景并抓取一张实时快照, 用于展示开发进度",
        category="test",
        tags=["feedback", "visual", "screenshot"]
    )
    input_model = CaptureParams

    def execute(self, task: Task, params: Dict[str, Any]) -> ToolResult:
        p = CaptureParams(**params)
        scene_path = p.scene_path or self._resolve_current_scene(task)
        
        if not scene_path:
            return self.build_result(
                success=False,
                message="未找到可截图的场景",
                params=self.dump_model(p),
                validation={"passed": False, "issues": ["missing_scene_path"]},
            )
            
        task.add_log(f"🖼️ 正在生成视觉反馈: {scene_path}...")
        
        # 准备路径
        output_dir = Path("logs/visual_feedback")
        output_dir.mkdir(parents=True, exist_ok=True)
        file_name = f"feedback_{int(time.time())}.png"
        full_path = output_dir / file_name

        editor_state = task.context.get("editor_state", {})
        screenshot_blob = editor_state.get("screenshot") if isinstance(editor_state, dict) else None
        if screenshot_blob:
            snapshot_path = output_dir / f"feedback_{int(time.time())}.jpg"
            try:
                snapshot_path.write_bytes(base64.b64decode(screenshot_blob))
            except Exception as exc:
                task.add_log(f"⚠️ 编辑器实时截图解码失败，改用 headless 截图: {exc}")
            else:
                artifact = Artifact(
                    name="Visual Feedback",
                    path=str(snapshot_path),
                    type="screenshot",
                    metadata={"scene": scene_path, "capture_mode": "editor_state"},
                )
                task.context["quick_capture_mode"] = "editor_state"
                return self.build_result(
                    success=True,
                    message=f"已使用编辑器实时快照生成场景 {scene_path} 的视觉反馈。",
                    params=self.dump_model(p),
                    artifacts=[artifact],
                    validation={
                        "passed": True,
                        "checks": [
                            {"name": "scene_resolution", "status": "passed"},
                            {"name": "editor_snapshot", "status": "passed"},
                            {"name": "screenshot_file_created", "status": "passed"},
                        ],
                    },
                    rollback={"available": False, "strategy": "test_only_no_write"},
                )
        
        # 构建极简截图脚本
        script = f"""extends SceneTree
func _initialize():
	var tree := self
	var packed = load("{scene_path}")
	var instance = packed.instantiate()
	tree.root.add_child(instance)
	await tree.create_timer({p.delay}).timeout
	var img = tree.root.get_viewport().get_texture().get_image()
	img.save_png("{str(full_path).replace('\\\\', '/')}")
	quit(0)
"""
        result = self.godot_cli.run_headless_script(script)
        
        if result.success and full_path.exists():
            artifact = Artifact(
                name="Visual Feedback",
                path=str(full_path),
                type="screenshot",
                metadata={"scene": scene_path}
            )
            return self.build_result(
                success=True,
                message=f"已生成场景 {scene_path} 的视觉反馈快照。",
                params=self.dump_model(p),
                artifacts=[artifact],
                validation={
                    "passed": True,
                    "checks": [
                        {"name": "scene_resolution", "status": "passed"},
                        {"name": "capture_script_dispatch", "status": "passed"},
                        {"name": "screenshot_file_created", "status": "passed"},
                    ],
                },
                rollback={"available": False, "strategy": "test_only_no_write"},
            )
        return self.build_result(
            success=False,
            message="截图失败",
            params=self.dump_model(p),
            error=result.error,
            validation={"passed": False, "issues": ["screenshot_capture_failed"]},
            rollback={"available": False, "strategy": "test_only_no_write"},
        )

    def _resolve_current_scene(self, task: Task) -> Optional[str]:
        # 优先使用上下文中的场景
        scene = task.context.get("scene_path")
        if scene: return scene
        
        # 其次使用最近产出的场景
        for art in reversed(task.artifacts):
            if art.type == "scene": return art.path
        return None

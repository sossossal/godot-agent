"""
Godot 端到端测试技能 (E2E Test Skill)
职责: 模拟玩家输入、执行断言并在运行期截图
"""

import os
import time
import tempfile
import base64
from pathlib import Path
from typing import Dict, List, Any, Optional
from pydantic import BaseModel, Field
from ..base import BaseSkill, SkillMetadata
from ...models import Task, ToolResult, Artifact


class E2EParams(BaseModel):
    """E2E 测试参数"""
    scene_path: Optional[str] = Field(None, description="测试场景路径")
    actions: List[str] = Field(default_factory=list, description="要模拟的动作序列, 如 ['ui_right', 'ui_accept']")
    screenshot: bool = Field(default=False, description="是否在测试结束前截图")
    assert_nodes: List[str] = Field(default_factory=list, description="要断言存在的节点路径")


class E2ETestSkill(BaseSkill):
    """端到端测试技能"""
    
    metadata = SkillMetadata(
        name="e2e_test_scene",
        description="执行端到端自动化测试, 支持输入回放、节点断言和实时截图",
        category="test",
        tags=["e2e", "automated", "screenshot", "assertion"]
    )
    
    input_model = E2EParams

    def execute(self, task: Task, params: Dict[str, Any]) -> ToolResult:
        p = E2EParams(**params)
        scene_path = p.scene_path or self._resolve_scene(task)
        if not scene_path:
            return self.build_result(
                success=False,
                message="缺少测试场景路径",
                params=self.dump_model(p),
                validation={"passed": False, "issues": ["missing_scene_path"]},
            )

        task.context["e2e_scene_path"] = scene_path
        task.context["e2e_playback_action_count"] = len(p.actions)
        task.context["e2e_screenshot_requested"] = p.screenshot
        task.add_log(f"🏗️ 构建 E2E 测试脚本 (Actions: {len(p.actions)}, Screenshot: {p.screenshot})")

        artifacts = []
        screenshot_path = None
        use_editor_snapshot_only = False
        editor_state = task.context.get("editor_state", {})
        if p.screenshot:
            artifact_dir = Path("logs/test_artifacts")
            artifact_dir.mkdir(parents=True, exist_ok=True)
            screenshot_blob = editor_state.get("screenshot") if isinstance(editor_state, dict) else None
            if screenshot_blob:
                screenshot_path = artifact_dir / f"e2e_capture_{int(time.time())}.jpg"
                screenshot_path.write_bytes(base64.b64decode(screenshot_blob))
                task.context["e2e_screenshot_mode"] = "editor_state"
                artifacts.append(
                    Artifact(
                        name=screenshot_path.name,
                        path=str(screenshot_path),
                        type="screenshot",
                    )
                )
                use_editor_snapshot_only = not p.actions and not p.assert_nodes
            else:
                screenshot_path = artifact_dir / f"e2e_capture_{int(time.time())}.png"
                task.context["e2e_screenshot_mode"] = "headless"

        script_content = self._build_script(scene_path, p.actions, p.assert_nodes, screenshot_path)
        artifacts.append(
            Artifact(
                name="e2e_harness.gd",
                path="internal://e2e_harness.gd",
                type="test_script",
                content=script_content,
            )
        )

        if use_editor_snapshot_only:
            task.add_log("🖼️ 已使用编辑器实时截图完成快照验证")
            return self.build_result(
                success=True,
                message=f"E2E 快照验证成功: {scene_path}",
                artifacts=artifacts,
                params=self.dump_model(p),
                validation={
                    "passed": True,
                    "checks": [
                        {"name": "scene_resolution", "status": "passed"},
                        {"name": "editor_snapshot", "status": "passed"},
                    ],
                },
                rollback={"available": False, "strategy": "test_only_no_write"},
            )

        with tempfile.NamedTemporaryFile(mode="w", suffix=".gd", delete=False, encoding="utf-8") as h:
            h.write(script_content)
            temp_script = h.name

        try:
            result = self.godot_cli.run_headless(temp_script, args=["--", scene_path])

            if result.success and p.screenshot and screenshot_path and not any(
                artifact.type == "screenshot" for artifact in artifacts
            ):
                artifacts.append(Artifact(
                    name=screenshot_path.name,
                    path=str(screenshot_path),
                    type="screenshot"
                ))
                task.add_log(f"🖼️ 截图产物已声明: {screenshot_path.name}")

            if result.success:
                return self.build_result(
                    success=True,
                    message=f"E2E 测试成功: {scene_path}",
                    params=self.dump_model(p),
                    artifacts=artifacts,
                    validation={
                        "passed": True,
                        "checks": [
                            {"name": "scene_resolution", "status": "passed"},
                            {"name": "headless_execution", "status": "passed"},
                            {"name": "assert_nodes", "status": "passed" if p.assert_nodes else "skipped"},
                            {"name": "screenshot_capture", "status": "passed" if p.screenshot else "skipped"},
                        ],
                    },
                    rollback={"available": False, "strategy": "test_only_no_write"},
                )
            else:
                return self.build_result(
                    success=False,
                    message=f"E2E 测试失败: {result.message}",
                    params=self.dump_model(p),
                    error=result.error,
                    artifacts=artifacts,
                    validation={"passed": False, "issues": ["headless_execution_failed"]},
                )
        finally:
            if os.path.exists(temp_script): os.unlink(temp_script)

    def _resolve_scene(self, task: Task) -> Optional[str]:
        if task.context.get("e2e_scene_path"):
            return task.context["e2e_scene_path"]
        editor_state = task.context.get("editor_state", {})
        if isinstance(editor_state, dict):
            current_scene = editor_state.get("current_scene")
            if current_scene:
                return current_scene
        return task.context.get("scene_path")

    def _build_script(self, scene_path: str, actions: List[str], nodes: List[str], screenshot_path: Optional[Path]) -> str:
        # 脚本构建逻辑与原 TesterRole 类似, 但更加参数化
        action_lines = []
        for action in actions:
            action_lines.append(f'    Input.action_press("{action}")')
            action_lines.append('    await tree.create_timer(0.4).timeout')
            action_lines.append(f'    Input.action_release("{action}")')
            
        assert_lines = []
        for node in nodes:
            assert_lines.append(f'    if not instance.get_node_or_null("{node}"): quit(1)')
            
        screenshot_code = ""
        if screenshot_path:
            screenshot_code = f'    instance.get_viewport().get_texture().get_image().save_png("{str(screenshot_path).replace("\\\\", "/")}")'
            
        return f"""extends SceneTree
func _initialize():
    var tree := self
    var packed = load("{scene_path}")
    var instance = packed.instantiate()
    tree.root.add_child(instance)
    await tree.process_frame
{"\n".join(action_lines)}
{"\n".join(assert_lines)}
{screenshot_code}
    quit(0)
"""

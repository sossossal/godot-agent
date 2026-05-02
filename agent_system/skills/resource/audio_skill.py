"""
音频资源管理技能 (Audio Management Skill)
职责: 在场景中注入音频播放节点, 配置音频文件并设置播放属性
"""

from typing import Dict, Any, Optional
from pydantic import BaseModel, Field
from ..base import BaseSkill, SkillMetadata
from ...models import Task, ToolResult, Artifact


class AudioParams(BaseModel):
    audio_name: str = Field(description="音频节点名称, 如 'BGM' 或 'JumpSFX'")
    audio_path: str = Field(description="音频文件路径, 如 res://assets/audio/bgm.ogg")
    is_2d: bool = Field(default=False, description="是否使用 AudioStreamPlayer2D")
    autoplay: bool = Field(default=True, description="是否自动播放")
    bus: str = Field(default="Master", description="所属音频总线")


class AudioManagementSkill(BaseSkill):
    metadata = SkillMetadata(
        name="manage_audio_resource",
        description="在当前场景中添加音频播放器。支持设置音频文件、自动播放和 2D/全局音效切换。",
        category="resource",
        tags=["audio", "resource", "sfx", "bgm"]
    )
    input_model = AudioParams

    def execute(self, task: Task, params: Dict[str, Any]) -> ToolResult:
        p = AudioParams(**params)
        
        # 1. 检查编辑器状态
        editor_state = task.context.get("editor_state", {})
        if not editor_state.get("is_active"):
            return self.build_result(
                success=False,
                message="编辑器离线, 无法实时注入音频节点",
                params=self.dump_model(p),
                validation={"passed": False, "issues": ["editor_offline"]},
                rollback={"available": False, "strategy": "no_write_performed"},
            )
            
        task.add_log(f"🔊 正在配置音频资源: {p.audio_name} -> {p.audio_path}")
        
        # 2. 生成注入脚本
        node_type = "AudioStreamPlayer2D" if p.is_2d else "AudioStreamPlayer"
        script = f'''
func _run(plugin: EditorPlugin):
	var scene_root = plugin.get_editor_interface().get_edited_scene_root()
	if not scene_root:
		print("❌ Error: No active scene root")
		return
		
	var player = {node_type}.new()
	player.name = "{p.audio_name}"
	
	# 加载资源
	var stream = load("{p.audio_path}")
	if stream:
		player.stream = stream
	else:
		print("⚠️ Warning: Audio file not found at {p.audio_path}, created node anyway")
		
	player.autoplay = {"true" if p.autoplay else "false"}
	player.bus = "{p.bus}"
	
	scene_root.add_child(player)
	player.owner = scene_root
	print("✅ Success: Added audio player {p.audio_name}")
'''
        artifact = Artifact(
            name=f"add_audio_{p.audio_name}.gd",
            path="internal://",
            type="editor_script",
            content=script
        )
        
        # 3. 更新蓝图功能
        blueprint = task.context.get("blueprint_manager")
        if blueprint:
            from ...tools.blueprint_manager import Feature
            blueprint.add_feature(Feature(
                name=f"Audio_{p.audio_name}",
                description=f"音频节点: {p.audio_name}, 资源: {p.audio_path}",
                creation_skill=self.metadata.name,
                creation_params=params
            ))

        return self.build_result(
            success=True,
            message=f"已在场景中成功添加音频节点 '{p.audio_name}'。",
            params=self.dump_model(p),
            artifacts=[artifact],
            validation={
                "passed": True,
                "checks": [
                    {"name": "editor_online", "status": "passed"},
                    {"name": "audio_editor_script_generated", "status": "passed"},
                ],
            },
            rollback={"available": False, "strategy": "wait_for_editor_confirmation"},
            metadata={"audio_node_type": node_type},
        )

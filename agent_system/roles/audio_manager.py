"""
AudioManagerRole — 音频系统生成角色
"""
from typing import Dict, List, Any
from .base import BaseRole


class AudioManagerRole(BaseRole):
    def get_description(self) -> str:
        return "音频专家，生成 BGM 管理器、音效控制器、音频配置脚本"

    def get_capabilities(self) -> List[str]:
        return ["AudioManager 单例", "BGM 无缝切换", "音效触发器", "音量设置", "3D 空间音效"]

    def execute(self, command: str, context: Dict[str, Any]) -> Dict[str, Any]:
        cmd = command.lower()
        if any(k in cmd for k in ["bgm", "背景音乐", "音乐", "切换"]):
            return self._gen_audio_manager()
        elif any(k in cmd for k in ["音效", "sfx", "3d音效", "空间"]):
            return self._gen_sfx_system()
        else:
            return self._gen_audio_manager()

    def _gen_audio_manager(self) -> Dict[str, Any]:
        code = '''\
# audio_manager.gd — 全局音频管理单例
extends Node

const BGM_BUS = "BGM"
const SFX_BUS = "SFX"

@onready var bgm_player: AudioStreamPlayer = $BGMPlayer
@onready var sfx_player: AudioStreamPlayer = $SFXPlayer

var current_bgm: String = ""
var is_fading: bool = false

func _ready() -> void:
	# 设置音频总线
	AudioServer.set_bus_volume_db(
		AudioServer.get_bus_index(BGM_BUS),
		linear_to_db(0.7)
	)

# ─── BGM ───────────────────────────────────────────────────────────────────

func play_bgm(stream: AudioStream, fade_duration: float = 1.0) -> void:
	"""播放/切换 BGM（带淡入淡出）"""
	if bgm_player.stream == stream:
		return
	if is_fading:
		return
	is_fading = true
	if bgm_player.playing:
		await _fade_out(bgm_player, fade_duration * 0.5)
	bgm_player.stream = stream
	bgm_player.play()
	await _fade_in(bgm_player, fade_duration * 0.5)
	is_fading = false

func stop_bgm(fade_duration: float = 1.0) -> void:
	if bgm_player.playing:
		await _fade_out(bgm_player, fade_duration)
		bgm_player.stop()

func _fade_out(player: AudioStreamPlayer, duration: float) -> void:
	var tween = create_tween()
	tween.tween_property(player, "volume_db", -80.0, duration)
	await tween.finished

func _fade_in(player: AudioStreamPlayer, duration: float) -> void:
	player.volume_db = -80.0
	var tween = create_tween()
	tween.tween_property(player, "volume_db", 0.0, duration)
	await tween.finished

# ─── SFX ───────────────────────────────────────────────────────────────────

func play_sfx(stream: AudioStream, pitch: float = 1.0) -> void:
	"""播放音效（自动创建临时播放节点，支持叠加）"""
	var player = AudioStreamPlayer.new()
	player.stream = stream
	player.bus = SFX_BUS
	player.pitch_scale = pitch + randf_range(-0.05, 0.05)  # 轻微随机音高，防止单调
	add_child(player)
	player.play()
	await player.finished
	player.queue_free()

# ─── 音量设置 ──────────────────────────────────────────────────────────────

func set_bgm_volume(value: float) -> void:
	"""设置 BGM 音量 (0.0 ~ 1.0)"""
	AudioServer.set_bus_volume_db(
		AudioServer.get_bus_index(BGM_BUS), linear_to_db(value)
	)

func set_sfx_volume(value: float) -> void:
	AudioServer.set_bus_volume_db(
		AudioServer.get_bus_index(SFX_BUS), linear_to_db(value)
	)
'''
        return self._success_result("AudioManager 已生成", {
            "script_name": "audio_manager.gd", "code": code,
            "tips": "在项目设置 → Autoload 中添加此脚本，名称 AudioManager；并在音频总线中创建 BGM 和 SFX 两条总线"
        })

    def _gen_sfx_system(self) -> Dict[str, Any]:
        code = '''\
# sfx_emitter_3d.gd — 3D 空间音效发射器（挂载到敌人/物件）
extends AudioStreamPlayer3D

@export var hit_sound: AudioStream
@export var death_sound: AudioStream

func play_hit() -> void:
	stream = hit_sound
	play()

func play_death() -> void:
	stream = death_sound
	play()
'''
        return self._success_result("3D 音效发射器已生成",
            {"script_name": "sfx_emitter_3d.gd", "code": code})

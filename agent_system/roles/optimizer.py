"""
OptimizerRole — 性能分析与优化建议角色
"""
from typing import Dict, List, Any
from .base import BaseRole


class OptimizerRole(BaseRole):
    def get_description(self) -> str:
        return "性能优化专家，生成对象池、LOD 控制、帧率监控、Draw Call 优化脚本"

    def get_capabilities(self) -> List[str]:
        return ["对象池", "帧率监控 HUD", "LOD 细节层次", "批次渲染优化建议", "内存泄漏检测"]

    def execute(self, command: str, context: Dict[str, Any]) -> Dict[str, Any]:
        cmd = command.lower()
        if any(k in cmd for k in ["对象池", "pool", "子弹", "粒子"]):
            return self._gen_object_pool()
        elif any(k in cmd for k in ["帧率", "fps", "监控", "debug"]):
            return self._gen_fps_monitor()
        elif any(k in cmd for k in ["lod", "细节", "距离"]):
            return self._gen_lod_controller()
        else:
            return self._gen_optimization_tips(command)

    def _gen_object_pool(self) -> Dict[str, Any]:
        code = '''\
# object_pool.gd — 通用对象池
extends Node
class_name ObjectPool

@export var prefab: PackedScene
@export var initial_size: int = 20
@export var max_size: int = 100

var _pool: Array[Node] = []
var _active: Array[Node] = []

func _ready() -> void:
	for i in range(initial_size):
		_create_instance()

func _create_instance() -> Node:
	var obj = prefab.instantiate()
	obj.set_meta("pooled", true)
	obj.hide()
	add_child(obj)
	_pool.append(obj)
	return obj

func get_object() -> Node:
	"""从池中获取一个可用对象"""
	var obj: Node
	if _pool.is_empty():
		if _active.size() < max_size:
			obj = _create_instance()
		else:
			# 池满时复用最老的对象
			obj = _active.pop_front()
	else:
		obj = _pool.pop_back()
	_active.append(obj)
	obj.show()
	return obj

func release(obj: Node) -> void:
	"""归还对象到池"""
	if obj in _active:
		_active.erase(obj)
		obj.hide()
		if obj.has_method("reset"):
			obj.reset()
		_pool.append(obj)

func release_all() -> void:
	for obj in _active.duplicate():
		release(obj)
'''
        return self._success_result("对象池已生成", {
            "script_name": "object_pool.gd", "code": code,
            "tips": "为对象脚本添加 reset() 方法以在归还时复位状态"
        })

    def _gen_fps_monitor(self) -> Dict[str, Any]:
        code = '''\
# fps_monitor.gd — FPS 与性能监控面板
extends CanvasLayer

@onready var fps_label: Label = $Panel/FPSLabel
@onready var mem_label: Label = $Panel/MemLabel
@onready var draw_label: Label = $Panel/DrawLabel

var update_interval: float = 0.5
var _timer: float = 0.0

func _process(delta: float) -> void:
	_timer += delta
	if _timer < update_interval:
		return
	_timer = 0.0
	fps_label.text = "FPS: %d" % Engine.get_frames_per_second()
	mem_label.text = "MEM: %.1f MB" % (OS.get_static_memory_used() / 1_048_576.0)
	draw_label.text = "Draw: %d" % RenderingServer.get_rendering_info(
		RenderingServer.RENDERING_INFO_TOTAL_DRAW_CALLS_IN_FRAME
	)

func _input(event: InputEvent) -> void:
	if event.is_action_just_pressed("toggle_debug"):
		visible = !visible
'''
        return self._success_result("FPS 监控面板已生成", {
            "script_name": "fps_monitor.gd", "code": code,
            "tips": "在输入映射中添加 toggle_debug 动作（建议 F3 键）"
        })

    def _gen_lod_controller(self) -> Dict[str, Any]:
        code = '''\
# lod_controller.gd — LOD 细节层次控制器
extends Node3D

@export var lod_distances: Array[float] = [10.0, 30.0, 60.0]
@export var lod_meshes: Array[MeshInstance3D]
@export_node_path var camera_path: NodePath

var _camera: Camera3D

func _ready() -> void:
	_camera = get_node(camera_path) if camera_path else get_viewport().get_camera_3d()

func _process(_delta: float) -> void:
	if not _camera:
		return
	var dist = global_position.distance_to(_camera.global_position)
	_apply_lod(dist)

func _apply_lod(distance: float) -> void:
	var level = lod_distances.size()
	for i in range(lod_distances.size()):
		if distance < lod_distances[i]:
			level = i
			break
	for i in range(lod_meshes.size()):
		if lod_meshes[i]:
			lod_meshes[i].visible = (i == level or (level >= lod_meshes.size() and i == lod_meshes.size() - 1))
'''
        return self._success_result("LOD 控制器已生成",
            {"script_name": "lod_controller.gd", "code": code})

    def _gen_optimization_tips(self, command: str) -> Dict[str, Any]:
        tips = [
            "使用对象池管理高频创建/销毁的对象（子弹、粒子、掉落物）",
            "场景中大量相似物体使用 MultiMeshInstance3D 代替独立 MeshInstance3D",
            "对距离较远的物体启用 LOD（Level of Detail）",
            "音频使用流式播放（AudioStream），避免将大文件完全加载到内存",
            "使用 VisibleOnScreenNotifier2D/3D 对屏幕外节点暂停处理",
            "避免每帧调用 find_node/get_node，改用 @onready 变量缓存",
            "在 _process 中使用时间累加器，降低非关键逻辑的执行频率",
        ]
        return self._success_result("性能优化建议", {
            "tips": tips,
            "scripts": ["object_pool.gd → 输入'生成对象池'", "fps_monitor.gd → 输入'生成帧率监控'"]
        })

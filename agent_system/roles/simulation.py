"""
SimulationRole — 物理仿真角色（来源：AGI-Walker）
"""
from typing import Dict, List, Any
from .base import BaseRole


class SimulationRole(BaseRole):
    def get_description(self) -> str:
        return "物理仿真专家，生成 TCP 通信、PID 控制器、传感器等高级物理脚本（源自 AGI-Walker）"

    def get_capabilities(self) -> List[str]:
        return ["TCP 服务器脚本", "PID 控制器", "视觉传感器", "平衡控制器", "物理参数配置"]

    def execute(self, command: str, context: Dict[str, Any]) -> Dict[str, Any]:
        cmd = command.lower()
        if any(k in cmd for k in ["tcp", "通信", "网络", "服务器"]):
            return self._gen_tcp_server()
        elif any(k in cmd for k in ["pid", "控制器", "平衡"]):
            return self._gen_pid_controller()
        elif any(k in cmd for k in ["传感", "视觉", "sensor"]):
            return self._gen_vision_sensor()
        else:
            return self._gen_tcp_server()

    def _gen_tcp_server(self) -> Dict[str, Any]:
        code = '''\
# tcp_simulation_server.gd — TCP 仿真通信服务器
# 来源: AGI-Walker godot_project
extends Node

const PORT = 9999
const BUFFER_SIZE = 4096

var server: TCPServer
var connection: StreamPeerTCP
var is_connected: bool = false

signal data_received(data: Dictionary)
signal client_connected()
signal client_disconnected()

func _ready() -> void:
	server = TCPServer.new()
	var err = server.listen(PORT)
	if err != OK:
		push_error("TCP 服务器启动失败: " + str(err))
		return
	print("🌐 TCP 仿真服务器已启动，端口: " + str(PORT))

func _process(_delta: float) -> void:
	if server.is_connection_available():
		connection = server.take_connection()
		is_connected = true
		client_connected.emit()
		print("✅ 客户端已连接")
	if is_connected and connection.get_status() == StreamPeerTCP.STATUS_CONNECTED:
		_receive_data()
	elif is_connected:
		is_connected = false
		client_disconnected.emit()

func _receive_data() -> void:
	var available = connection.get_available_bytes()
	if available <= 0:
		return
	var raw = connection.get_utf8_string(available)
	var parsed = JSON.parse_string(raw)
	if parsed is Dictionary:
		data_received.emit(parsed)

func send_data(data: Dictionary) -> void:
	if not is_connected:
		return
	connection.put_utf8_string(JSON.stringify(data) + "\\n")
'''
        return self._success_result("TCP 仿真服务器已生成（AGI-Walker 风格）",
            {"script_name": "tcp_simulation_server.gd", "code": code})

    def _gen_pid_controller(self) -> Dict[str, Any]:
        code = '''\
# pid_controller.gd — PID 控制器（来源: AGI-Walker）
extends RefCounted
class_name PIDController

var kp: float  # 比例增益
var ki: float  # 积分增益
var kd: float  # 微分增益

var _integral: float = 0.0
var _prev_error: float = 0.0
var _integral_limit: float = 100.0

func _init(p: float, i: float, d: float) -> void:
	kp = p; ki = i; kd = d

func update(setpoint: float, measurement: float, delta: float) -> float:
	var error = setpoint - measurement
	_integral = clamp(_integral + error * delta, -_integral_limit, _integral_limit)
	var derivative = (error - _prev_error) / delta if delta > 0 else 0.0
	_prev_error = error
	return kp * error + ki * _integral + kd * derivative

func reset() -> void:
	_integral = 0.0
	_prev_error = 0.0
'''
        return self._success_result("PID 控制器已生成",
            {"script_name": "pid_controller.gd", "code": code,
             "tips": "使用示例：var pid = PIDController.new(1.0, 0.1, 0.05)\n          var output = pid.update(target, current, delta)"})

    def _gen_vision_sensor(self) -> Dict[str, Any]:
        code = '''\
# vision_sensor.gd — 视野传感器（来源: AGI-Walker）
extends Node2D

@export var vision_range: float = 300.0
@export var vision_angle: float = 90.0  # 单侧角度（总视野 = 2x）
@export var target_group: String = "player"

signal target_spotted(target: Node2D)
signal target_lost()

var detected_target: Node2D = null

func _physics_process(_delta: float) -> void:
	var targets = get_tree().get_nodes_in_group(target_group)
	var found: Node2D = null
	for t in targets:
		if _can_see(t):
			found = t
			break
	if found and found != detected_target:
		detected_target = found
		target_spotted.emit(found)
	elif not found and detected_target:
		detected_target = null
		target_lost.emit()

func _can_see(target: Node2D) -> bool:
	var to_target = target.global_position - global_position
	if to_target.length() > vision_range:
		return false
	var angle = rad_to_deg(global_transform.x.angle_to(to_target))
	if abs(angle) > vision_angle:
		return false
	# 射线检测障碍物
	var space = get_world_2d().direct_space_state
	var query = PhysicsRayQueryParameters2D.create(
		global_position, target.global_position, 1, [self]
	)
	var result = space.intersect_ray(query)
	return result.is_empty() or result.collider == target
'''
        return self._success_result("视觉传感器已生成（AGI-Walker 风格）",
            {"script_name": "vision_sensor.gd", "code": code})

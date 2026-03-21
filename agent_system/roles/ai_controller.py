"""
AIControllerRole — AI 行为/状态机/行为树生成角色
"""
from typing import Dict, List, Any
from .base import BaseRole


class AIControllerRole(BaseRole):
    def get_description(self) -> str:
        return "AI 专家，生成敌人状态机、行为树、Boss 多阶段 AI"

    def get_capabilities(self) -> List[str]:
        return ["有限状态机 AI", "行为树节点", "巡逻/追击逻辑", "Boss 多阶段", "视野检测", "路径导航"]

    def execute(self, command: str, context: Dict[str, Any]) -> Dict[str, Any]:
        cmd = command.lower()
        if any(k in cmd for k in ["boss", "多阶段", "精英"]):
            return self._gen_boss_ai()
        elif any(k in cmd for k in ["巡逻", "追击", "patrol", "chase"]):
            return self._gen_patrol_ai()
        else:
            return self._gen_enemy_state_machine()

    def _gen_enemy_state_machine(self) -> Dict[str, Any]:
        code = '''\
# enemy_ai.gd — 敌人有限状态机
extends CharacterBody2D

enum State { IDLE, PATROL, CHASE, ATTACK, HURT, DEAD }

@export var speed: float = 80.0
@export var chase_speed: float = 140.0
@export var attack_range: float = 40.0
@export var detect_range: float = 200.0
@export var patrol_points: Array[Vector2] = []

@onready var detection_area: Area2D = $DetectionArea
@onready var attack_area: Area2D = $AttackArea
@onready var nav_agent: NavigationAgent2D = $NavigationAgent2D
@onready var anim: AnimationPlayer = $AnimationPlayer

var state: State = State.IDLE
var target: Node2D = null
var patrol_index: int = 0
var health: int = 100

func _ready() -> void:
	detection_area.body_entered.connect(_on_player_detected)
	detection_area.body_exited.connect(_on_player_lost)
	attack_area.body_entered.connect(_on_attack_range_entered)

func _physics_process(delta: float) -> void:
	match state:
		State.IDLE:   _state_idle()
		State.PATROL: _state_patrol(delta)
		State.CHASE:  _state_chase(delta)
		State.ATTACK: _state_attack()

func _state_idle() -> void:
	velocity = Vector2.ZERO
	if patrol_points.size() > 0:
		_change_state(State.PATROL)

func _state_patrol(delta: float) -> void:
	if patrol_points.is_empty(): return
	var target_pos = patrol_points[patrol_index]
	nav_agent.target_position = global_position + target_pos
	var dir = nav_agent.get_next_path_position() - global_position
	velocity = dir.normalized() * speed
	move_and_slide()
	if global_position.distance_to(global_position + target_pos) < 10:
		patrol_index = (patrol_index + 1) % patrol_points.size()

func _state_chase(delta: float) -> void:
	if not target: _change_state(State.PATROL); return
	nav_agent.target_position = target.global_position
	var dir = nav_agent.get_next_path_position() - global_position
	velocity = dir.normalized() * chase_speed
	move_and_slide()

func _state_attack() -> void:
	velocity = Vector2.ZERO
	anim.play("attack")

func _change_state(new_state: State) -> void:
	state = new_state

func _on_player_detected(body: Node) -> void:
	if body.is_in_group("player"):
		target = body
		_change_state(State.CHASE)

func _on_player_lost(body: Node) -> void:
	if body == target:
		target = null
		_change_state(State.PATROL)

func _on_attack_range_entered(body: Node) -> void:
	if body.is_in_group("player"):
		_change_state(State.ATTACK)

func take_damage(amount: int) -> void:
	health -= amount
	if health <= 0:
		_change_state(State.DEAD)
		queue_free()
	else:
		_change_state(State.HURT)
		await get_tree().create_timer(0.3).timeout
		_change_state(State.CHASE)
'''
        return self._success_result("敌人 AI 状态机已生成",
            {"script_name": "enemy_ai.gd", "code": code})

    def _gen_boss_ai(self) -> Dict[str, Any]:
        code = '''\
# boss_ai.gd — Boss 多阶段 AI
extends CharacterBody2D

enum Phase { P1, P2, P3 }

@export var max_health: int = 3000
var health: int = max_health
var phase: Phase = Phase.P1

var phase2_threshold: float = 0.6  # 60% 血量进入二阶段
var phase3_threshold: float = 0.3  # 30% 血量进入三阶段

signal phase_changed(new_phase: Phase)

func take_damage(amount: int) -> void:
	health -= amount
	_check_phase()

func _check_phase() -> void:
	var ratio = float(health) / max_health
	var new_phase = Phase.P1
	if ratio <= phase3_threshold:
		new_phase = Phase.P3
	elif ratio <= phase2_threshold:
		new_phase = Phase.P2
	if new_phase != phase:
		phase = new_phase
		phase_changed.emit(phase)
		_on_phase_changed(phase)

func _on_phase_changed(new_phase: Phase) -> void:
	match new_phase:
		Phase.P2:
			print("Boss 进入二阶段！速度提升，新增技能")
		Phase.P3:
			print("Boss 进入最终阶段！狂暴模式")
			# 狂暴效果
			Engine.time_scale = 1.2

func _physics_process(delta: float) -> void:
	match phase:
		Phase.P1: _attack_p1(delta)
		Phase.P2: _attack_p2(delta)
		Phase.P3: _attack_p3(delta)

func _attack_p1(_delta: float) -> void: pass
func _attack_p2(_delta: float) -> void: pass
func _attack_p3(_delta: float) -> void: pass
'''
        return self._success_result("Boss 多阶段 AI 已生成",
            {"script_name": "boss_ai.gd", "code": code})

    def _gen_patrol_ai(self) -> Dict[str, Any]:
        code = '''\
# patrol_enemy.gd — 简单巡逻追击 AI
extends CharacterBody2D

@export var speed: float = 60.0
@export var patrol_distance: float = 150.0
@export var detect_range: float = 180.0

var direction: float = 1.0
var start_position: Vector2
var player: Node2D = null

func _ready() -> void:
	start_position = global_position
	add_to_group("enemy")

func _physics_process(delta: float) -> void:
	player = _find_player()
	if player and global_position.distance_to(player.global_position) < detect_range:
		_chase(delta)
	else:
		_patrol(delta)
	move_and_slide()

func _patrol(delta: float) -> void:
	velocity.x = speed * direction
	if abs(global_position.x - start_position.x) > patrol_distance:
		direction *= -1

func _chase(delta: float) -> void:
	var dir = (player.global_position - global_position).normalized()
	velocity = dir * (speed * 1.8)

func _find_player() -> Node2D:
	return get_tree().get_first_node_in_group("player")
'''
        return self._success_result("巡逻追击 AI 已生成",
            {"script_name": "patrol_enemy.gd", "code": code})

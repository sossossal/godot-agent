"""
ScriptLibrary — GDScript 模板库
存储所有单机游戏常用 GDScript 代码模板，供 CodeGeneratorRole 调用
"""
from typing import Dict


class ScriptLibrary:
    """GDScript 模板集中管理"""

    _templates: Dict[str, str] = {

        # ─── 玩家移动 ──────────────────────────────────────────────────────────
        "player_2d": '''\
# player_controller_2d.gd — 2D 玩家控制器
extends CharacterBody2D

@export var speed: float = 300.0
@export var jump_velocity: float = -600.0
@export var acceleration: float = 2000.0
@export var friction: float = 1500.0

var gravity: float = ProjectSettings.get_setting("physics/2d/default_gravity")
var is_dead: bool = false

func _physics_process(delta: float) -> void:
	if is_dead: return
	# 重力
	if not is_on_floor():
		velocity.y += gravity * delta
	# 跳跃
	if Input.is_action_just_pressed("jump") and is_on_floor():
		velocity.y = jump_velocity
	# 水平移动
	var dir = Input.get_axis("move_left", "move_right")
	if dir:
		velocity.x = move_toward(velocity.x, dir * speed, acceleration * delta)
	else:
		velocity.x = move_toward(velocity.x, 0, friction * delta)
	move_and_slide()
''',

        "player_3d": '''\
# player_controller_3d.gd — 3D 玩家控制器（第三人称）
extends CharacterBody3D

@export var speed: float = 5.0
@export var jump_velocity: float = 5.0
@export var mouse_sensitivity: float = 0.003

@onready var camera_arm: SpringArm3D = $SpringArm3D
@onready var camera: Camera3D = $SpringArm3D/Camera3D

var gravity: float = ProjectSettings.get_setting("physics/3d/default_gravity")

func _ready() -> void:
	Input.set_mouse_mode(Input.MOUSE_MODE_CAPTURED)

func _unhandled_input(event: InputEvent) -> void:
	if event is InputEventMouseMotion:
		rotate_y(-event.relative.x * mouse_sensitivity)
		camera_arm.rotation.x = clamp(
			camera_arm.rotation.x - event.relative.y * mouse_sensitivity,
			-PI/3, PI/3
		)

func _physics_process(delta: float) -> void:
	if not is_on_floor():
		velocity.y -= gravity * delta
	if Input.is_action_just_pressed("jump") and is_on_floor():
		velocity.y = jump_velocity
	var input_dir = Input.get_vector("move_left", "move_right", "move_forward", "move_back")
	var dir = (transform.basis * Vector3(input_dir.x, 0, input_dir.y)).normalized()
	velocity.x = dir.x * speed
	velocity.z = dir.z * speed
	move_and_slide()
''',

        # ─── 血量系统 ──────────────────────────────────────────────────────────
        "health_system": '''\
# health_system.gd
extends Node
class_name HealthSystem

signal health_changed(current: int, maximum: int)
signal died()

@export var max_health: int = 100
var current_health: int

func _ready() -> void:
	current_health = max_health

func take_damage(amount: int) -> void:
	if current_health <= 0: return
	current_health = max(0, current_health - amount)
	health_changed.emit(current_health, max_health)
	if current_health == 0:
		died.emit()

func heal(amount: int) -> void:
	current_health = min(max_health, current_health + amount)
	health_changed.emit(current_health, max_health)

func is_alive() -> bool:
	return current_health > 0

func get_ratio() -> float:
	return float(current_health) / max_health
''',

        # ─── 存档系统 ──────────────────────────────────────────────────────────
        "save_system": '''\
# save_system.gd — 存档/读档系统单例
extends Node

const SAVE_PATH = "user://save_data.cfg"

signal game_saved()
signal game_loaded()

func save_game(data: Dictionary = {}) -> void:
	var config = ConfigFile.new()
	# 从场景树收集存档数据
	var save_nodes = get_tree().get_nodes_in_group("saveable")
	for node in save_nodes:
		if not node.has_method("get_save_data"):
			continue
		var node_data = node.get_save_data()
		for key in node_data:
			config.set_value(node.name, key, node_data[key])
	# 合并外部传入数据
	for section in data:
		for key in data[section]:
			config.set_value(section, key, data[section][key])
	config.save(SAVE_PATH)
	game_saved.emit()
	print("💾 游戏已保存")

func load_game() -> Dictionary:
	var config = ConfigFile.new()
	if config.load(SAVE_PATH) != OK:
		print("⚠️ 未找到存档")
		return {}
	var result = {}
	for section in config.get_sections():
		result[section] = {}
		for key in config.get_section_keys(section):
			result[section][key] = config.get_value(section, key)
	game_loaded.emit()
	return result

func has_save() -> bool:
	return FileAccess.file_exists(SAVE_PATH)

func delete_save() -> void:
	DirAccess.remove_absolute(SAVE_PATH)
''',

        # ─── 状态机 ────────────────────────────────────────────────────────────
        "state_machine": '''\
# state_machine.gd — 通用有限状态机
extends Node
class_name StateMachine

signal state_changed(from: String, to: String)

var current_state: State = null
var states: Dictionary = {}

class State:
	var name: String
	var machine: Node
	func enter() -> void: pass
	func exit()  -> void: pass
	func update(delta: float) -> void: pass
	func physics_update(delta: float) -> void: pass

func _ready() -> void:
	for child in get_children():
		if child is State:
			states[child.name] = child
			child.machine = owner
	if states.size() > 0:
		transition_to(states.keys()[0])

func transition_to(state_name: String) -> void:
	if not state_name in states:
		push_error("状态不存在: " + state_name); return
	var prev = current_state.name if current_state else ""
	if current_state:
		current_state.exit()
	current_state = states[state_name]
	current_state.enter()
	state_changed.emit(prev, state_name)

func _process(delta: float) -> void:
	if current_state: current_state.update(delta)

func _physics_process(delta: float) -> void:
	if current_state: current_state.physics_update(delta)
''',

        # ─── 背包系统 ──────────────────────────────────────────────────────────
        "inventory": '''\
# inventory.gd — 背包系统单例
extends Node

signal item_added(item: Dictionary)
signal item_removed(item: Dictionary)
signal item_changed()

var items: Array[Dictionary] = []
var max_slots: int = 36
var gold: int = 0

func add_item(item: Dictionary, quantity: int = 1) -> bool:
	# 尝试叠加
	if item.get("stackable", false):
		for existing in items:
			if existing["id"] == item["id"]:
				existing["quantity"] = existing.get("quantity", 1) + quantity
				item_changed.emit()
				return true
	if items.size() >= max_slots:
		return false
	var new_item = item.duplicate()
	new_item["quantity"] = quantity
	items.append(new_item)
	item_added.emit(new_item)
	item_changed.emit()
	return true

func remove_item(item_id: String, quantity: int = 1) -> bool:
	for i in range(items.size()):
		if items[i]["id"] == item_id:
			items[i]["quantity"] -= quantity
			if items[i]["quantity"] <= 0:
				var removed = items[i]
				items.remove_at(i)
				item_removed.emit(removed)
			item_changed.emit()
			return true
	return false

func has_item(item_id: String, quantity: int = 1) -> bool:
	for item in items:
		if item["id"] == item_id and item.get("quantity", 1) >= quantity:
			return true
	return false

func get_item(item_id: String) -> Dictionary:
	for item in items:
		if item["id"] == item_id:
			return item
	return {}
''',

        # ─── 战斗系统 ──────────────────────────────────────────────────────────
        "combat_system": '''\
# combat_system.gd — 战斗伤害计算系统
extends Node
class_name CombatSystem

static func calculate_damage(
	base_damage: int,
	attacker_atk: int,
	defender_def: int,
	crit_rate: float = 0.1,
	crit_multiplier: float = 2.0
) -> Dictionary:
	var is_crit = randf() < crit_rate
	var raw = base_damage + attacker_atk - defender_def
	raw = max(raw, 1)  # 最低造成 1 点伤害
	if is_crit:
		raw = int(raw * crit_multiplier)
	return {"damage": raw, "is_crit": is_crit}

static func apply_knockback(target: CharacterBody2D, from: Vector2, force: float) -> void:
	var dir = (target.global_position - from).normalized()
	target.velocity += dir * force
''',

        # ─── 技能/冷却 ─────────────────────────────────────────────────────────
        "skill_system": '''\
# skill_system.gd — 技能冷却管理
extends Node

signal skill_used(skill_id: String)
signal skill_ready(skill_id: String)

# {skill_id: {cooldown: float, remaining: float, cost: int}}
var skills: Dictionary = {}

func register_skill(skill_id: String, cooldown: float, cost: int = 0) -> void:
	skills[skill_id] = {"cooldown": cooldown, "remaining": 0.0, "cost": cost}

func use_skill(skill_id: String) -> bool:
	if not skill_id in skills: return false
	var s = skills[skill_id]
	if s["remaining"] > 0: return false
	s["remaining"] = s["cooldown"]
	skill_used.emit(skill_id)
	return true

func _process(delta: float) -> void:
	for id in skills:
		if skills[id]["remaining"] > 0:
			skills[id]["remaining"] -= delta
			if skills[id]["remaining"] <= 0:
				skills[id]["remaining"] = 0.0
				skill_ready.emit(id)

func get_cooldown_ratio(skill_id: String) -> float:
	if not skill_id in skills: return 0.0
	var s = skills[skill_id]
	return s["remaining"] / s["cooldown"] if s["cooldown"] > 0 else 0.0
''',

        # ─── 全局事件总线 ──────────────────────────────────────────────────────
        "event_bus": '''\
# event_bus.gd — 全局事件总线单例
extends Node

# 单机游戏常用信号
signal player_died()
signal player_respawned()
signal level_completed(level_id: int)
signal game_paused()
signal game_resumed()
signal item_picked_up(item: Dictionary)
signal enemy_defeated(enemy_id: String, position: Vector2)
signal gold_changed(amount: int)
signal xp_gained(amount: int)
signal level_up(new_level: int)
signal checkpoint_reached(checkpoint_id: String)
signal cutscene_started(cutscene_id: String)
signal cutscene_ended()
''',

        # ─── 对象池 ────────────────────────────────────────────────────────────
        "object_pool": '''\
# 请参见 optimizer 角色生成的对象池
# 快速版本（单场景）：
extends Node
class_name SimplePool

@export var prefab: PackedScene
@export var size: int = 20
var _pool: Array[Node] = []

func _ready() -> void:
	for i in size: _grow()

func _grow() -> Node:
	var n = prefab.instantiate()
	n.hide(); add_child(n)
	_pool.append(n); return n

func get_obj() -> Node:
	var n = _pool.pop_back() if _pool else _grow()
	n.show(); return n

func release(n: Node) -> void:
	n.hide(); _pool.append(n)
''',

        # ─── 摄像机抖动 ────────────────────────────────────────────────────────
        "camera_shake": '''\
# camera_shake.gd — 摄像机抖动效果（挂载到 Camera2D）
extends Camera2D

var _shake_intensity: float = 0.0
var _shake_duration: float = 0.0
var _elapsed: float = 0.0

func shake(intensity: float, duration: float) -> void:
	_shake_intensity = intensity
	_shake_duration = duration
	_elapsed = 0.0

func _process(delta: float) -> void:
	if _elapsed < _shake_duration:
		_elapsed += delta
		var t = 1.0 - (_elapsed / _shake_duration)
		offset = Vector2(
			randf_range(-1, 1) * _shake_intensity * t,
			randf_range(-1, 1) * _shake_intensity * t
		)
	else:
		offset = Vector2.ZERO
''',

        # ─── 游戏管理单例 ──────────────────────────────────────────────────────
        "game_manager": '''\
# game_manager.gd — 全局游戏管理单例
extends Node

var current_level: int = 1
var player_data: Dictionary = {
	"name": "Hero",
	"level": 1,
	"xp": 0,
	"xp_to_next": 100,
	"gold": 0,
}

func _ready() -> void:
	print("🎮 GameManager 已初始化")
	# 监听事件总线
	if has_node("/root/EventBus"):
		var eb = get_node("/root/EventBus")
		eb.gold_changed.connect(_on_gold_changed)
		eb.xp_gained.connect(_on_xp_gained)

func _on_gold_changed(amount: int) -> void:
	player_data["gold"] += amount

func _on_xp_gained(amount: int) -> void:
	player_data["xp"] += amount
	while player_data["xp"] >= player_data["xp_to_next"]:
		player_data["xp"] -= player_data["xp_to_next"]
		player_data["level"] += 1
		player_data["xp_to_next"] = int(player_data["xp_to_next"] * 1.3)
		if has_node("/root/EventBus"):
			get_node("/root/EventBus").level_up.emit(player_data["level"])

func pause() -> void:
	get_tree().paused = true
	if has_node("/root/EventBus"):
		get_node("/root/EventBus").game_paused.emit()

func resume() -> void:
	get_tree().paused = false
	if has_node("/root/EventBus"):
		get_node("/root/EventBus").game_resumed.emit()

func restart_level() -> void:
	get_tree().reload_current_scene()

func go_to_scene(path: String) -> void:
	get_tree().change_scene_to_file(path)
''',
    }

    def get(self, key: str) -> str:
        """获取模板代码，找不到时返回空模板"""
        return self._templates.get(key, "extends Node\n\nfunc _ready() -> void:\n\tpass\n")

    def list_templates(self) -> list:
        """列出所有可用模板键名"""
        return list(self._templates.keys())

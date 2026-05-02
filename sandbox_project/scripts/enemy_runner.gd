extends Area2D

signal base_reached

@export var move_speed := 60.0
@export var health := 3
@export var base_x := 680.0
var _spawn_position := Vector2.ZERO

func _ready() -> void:
    _spawn_position = global_position

func _process(delta: float) -> void:
    global_position.x += move_speed * delta
    if global_position.x >= base_x:
        base_reached.emit()

func take_damage(amount: int = 1) -> void:
    health -= amount
    if health <= 0:
        reset_to_spawn()

func reset_to_spawn() -> void:
    global_position = _spawn_position
    health = 3

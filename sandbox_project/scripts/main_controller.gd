extends Node2D

@onready var hud := $HUD
@onready var health := $Health
@onready var player := $Player
@onready var tower := $Tower
@onready var enemy := $Enemy

var resources := 5

func _ready() -> void:
    player.tower_placed.connect(_on_tower_placed)
    tower.fired.connect(_on_tower_fired)
    enemy.base_reached.connect(_on_enemy_base_reached)
    health.health_changed.connect(_on_health_changed)
    hud.set_resources(resources)
    hud.set_health(health.current_health)

func _on_tower_placed(_position: Vector2) -> void:
    if resources <= 0:
        return
    resources -= 1
    hud.set_resources(resources)

func _on_tower_fired() -> void:
    enemy.take_damage(1)

func _on_enemy_base_reached() -> void:
    health.damage(1)
    enemy.reset_to_spawn()

func _on_health_changed(current_health: int) -> void:
    hud.set_health(current_health)

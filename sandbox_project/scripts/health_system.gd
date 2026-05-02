extends Node

signal health_changed(current_health: int)

@export var max_health := 3
var current_health := 3

func damage(amount: int = 1) -> void:
    current_health = max(current_health - amount, 0)
    health_changed.emit(current_health)

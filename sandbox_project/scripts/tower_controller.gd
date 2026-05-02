extends Area2D

signal fired

@export var cooldown := 1.0
var _cooldown_left := 0.0

func _process(delta: float) -> void:
    _cooldown_left = max(_cooldown_left - delta, 0.0)
    if _cooldown_left > 0.0:
        return
    for body in get_overlapping_areas():
        if body.name == "Enemy":
            _cooldown_left = cooldown
            fired.emit()
            return

extends CharacterBody2D

signal tower_placed(location: Vector2)

@export var speed := 180.0

func _physics_process(_delta: float) -> void:
    var input_vector := Vector2(
        Input.get_axis("move_left", "move_right"),
        Input.get_axis("move_up", "move_down")
    )
    velocity = input_vector.normalized() * speed
    move_and_slide()
    if Input.is_action_just_pressed("place_tower"):
        tower_placed.emit(global_position)

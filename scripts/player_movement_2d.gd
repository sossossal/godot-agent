extends CharacterBody2D
func _physics_process(delta):
    var dir = Input.get_axis("ui_left", "ui_right")
    velocity.x = dir * 300
    move_and_slide()

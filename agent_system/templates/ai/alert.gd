extends CharacterBody2D
## AI 警戒行为模板
## 监听目标进入范围并在短时间内保持面向目标

@export var target_node: Node2D
@export var alert_radius: float = 180.0
@export var look_speed: float = 6.0

var is_alerted: bool = false

func _physics_process(delta):
    if not target_node:
        return

    var to_target = target_node.global_position - global_position
    is_alerted = to_target.length() <= alert_radius

    if is_alerted:
        rotation = lerp_angle(rotation, to_target.angle(), delta * look_speed)

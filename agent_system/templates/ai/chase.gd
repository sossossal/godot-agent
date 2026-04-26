extends CharacterBody2D
## AI 追击行为模板
## 自动寻找目标并保持距离追踪

@export var target_node: Node2D
@export var speed: float = 200.0
@export var min_distance: float = 50.0

func _physics_process(delta):
    if not target_node: return
    
    var direction = (target_node.global_position - global_position).normalized()
    var distance = global_position.distance_to(target_node.global_position)
    
    if distance > min_distance:
        velocity = direction * speed
        move_and_slide()
    else:
        velocity = Vector2.ZERO

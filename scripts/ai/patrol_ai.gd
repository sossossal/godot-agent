extends CharacterBody2D
## AI 巡逻行为模板
## 支持多个巡逻点循环移动,并具备到达等待功能

@export var patrol_points: Array[Vector2] = []
@export var speed: float = 100.0
@export var wait_time: float = 1.5

var current_index: int = 0
var is_waiting: bool = false

func _physics_process(delta):
    if is_waiting or patrol_points.is_empty(): return
    
    var target = patrol_points[current_index]
    var direction = (target - global_position).normalized()
    
    if global_position.distance_to(target) < 10.0:
        _arrive_at_point()
    else:
        velocity = direction * speed
        move_and_slide()

func _arrive_at_point():
    is_waiting = true
    current_index = (current_index + 1) % patrol_points.size()
    await get_tree().create_timer(wait_time).timeout
    is_waiting = false

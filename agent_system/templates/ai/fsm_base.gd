extends Node
class_name FiniteStateMachine
## 简单有限状态机基类

@export var initial_state: Node
var current_state: Node

func _ready():
    for child in get_children():
        child.fsm = self
    
    if initial_state:
        change_to(initial_state.name)

func change_to(state_name: String):
    var new_state = get_node(state_name)
    if not new_state: return
    
    if current_state:
        current_state.exit()
    
    current_state = new_state
    current_state.enter()

func _physics_process(delta):
    if current_state:
        current_state.update(delta)

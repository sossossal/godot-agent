extends Control
class_name DialogueSystem

signal dialogue_started
signal line_changed(text: String)
signal dialogue_finished

var lines: Array[String] = []
var current_index: int = -1

func start_dialogue(dialogue_lines: Array[String]) -> void:
    lines = dialogue_lines
    current_index = -1
    visible = true
    dialogue_started.emit()
    next_line()

func next_line() -> void:
    current_index += 1
    if current_index >= lines.size():
        finish_dialogue()
        return

    line_changed.emit(lines[current_index])

func finish_dialogue() -> void:
    visible = false
    dialogue_finished.emit()

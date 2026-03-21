"""
NarrativeRole — 剧情/对话树/任务系统生成角色
"""
from typing import Dict, List, Any
from .base import BaseRole


class NarrativeRole(BaseRole):
    """负责生成剧情、对话树和任务系统"""

    def get_description(self) -> str:
        return "叙事设计专家，生成对话树、任务系统、剧情触发器"

    def get_capabilities(self) -> List[str]:
        return ["对话树 GDScript", "任务/支线系统", "剧情触发器", "JSON 对话数据", "NPC 台词模板"]

    def execute(self, command: str, context: Dict[str, Any]) -> Dict[str, Any]:
        cmd = command.lower()
        if "对话" in cmd or "台词" in cmd:
            return self._gen_dialogue_system()
        elif "任务" in cmd or "支线" in cmd or "主线" in cmd:
            return self._gen_quest_system()
        else:
            return self._gen_story_trigger()

    def _gen_dialogue_system(self) -> Dict[str, Any]:
        code = '''\
# dialogue_system.gd — 对话管理系统
extends Node
class_name DialogueSystem

signal dialogue_started(npc_name: String)
signal dialogue_line_changed(line: DialogueLine)
signal dialogue_ended()
signal choice_made(choice_id: int)

@export var dialogue_data_path: String = "res://data/dialogues/"

var current_dialogue: Dictionary = {}
var current_node_id: String = ""
var is_active: bool = false

class DialogueLine:
	var speaker: String
	var text: String
	var choices: Array[Dictionary]

func start_dialogue(dialogue_id: String, start_node: String = "start") -> void:
	"""启动对话"""
	var path = dialogue_data_path + dialogue_id + ".json"
	var file = FileAccess.open(path, FileAccess.READ)
	if not file:
		push_error("找不到对话文件: " + path)
		return
	current_dialogue = JSON.parse_string(file.get_as_text())
	current_node_id = start_node
	is_active = true
	dialogue_started.emit(current_dialogue.get("npc_name", ""))
	_show_current_node()

func _show_current_node() -> void:
	if not current_node_id in current_dialogue.get("nodes", {}):
		end_dialogue()
		return
	var node = current_dialogue["nodes"][current_node_id]
	var line = DialogueLine.new()
	line.speaker = node.get("speaker", "")
	line.text = node.get("text", "")
	line.choices = node.get("choices", [])
	dialogue_line_changed.emit(line)

func advance(choice_index: int = 0) -> void:
	"""推进对话（选择分支）"""
	var node = current_dialogue["nodes"].get(current_node_id, {})
	var choices = node.get("choices", [])
	if choices.is_empty():
		end_dialogue()
		return
	choice_made.emit(choice_index)
	current_node_id = choices[choice_index].get("next", "")
	_show_current_node()

func end_dialogue() -> void:
	is_active = false
	current_dialogue = {}
	dialogue_ended.emit()
'''
        sample_json = '''{
  "npc_name": "村民老王",
  "nodes": {
    "start": {
      "speaker": "老王",
      "text": "欢迎来到我们的村子，旅行者！",
      "choices": [
        {"text": "你好，请问有什么需要帮忙的？", "next": "quest_offer"},
        {"text": "我只是路过。", "next": "farewell"}
      ]
    },
    "quest_offer": {
      "speaker": "老王",
      "text": "太好了！村子东边的森林里出现了怪物，你能帮我们吗？",
      "choices": [
        {"text": "当然，我去看看。", "next": "quest_accept"},
        {"text": "抱歉，我没时间。", "next": "farewell"}
      ]
    }
  }
}'''
        return self._success_result(
            "对话系统已生成",
            {"script_name": "dialogue_system.gd", "code": code,
             "sample_data": sample_json, "tips": "JSON 文件放到 res://data/dialogues/ 目录"}
        )

    def _gen_quest_system(self) -> Dict[str, Any]:
        code = '''\
# quest_system.gd — 任务管理单例
extends Node

signal quest_started(quest_id: String)
signal quest_updated(quest_id: String, objective_id: String)
signal quest_completed(quest_id: String)

var active_quests: Dictionary = {}   # {quest_id: QuestData}
var completed_quests: Array[String] = []

class QuestData:
	var id: String
	var title: String
	var description: String
	var objectives: Dictionary    # {obj_id: {done:bool, count:int, target:int}}
	var rewards: Dictionary

func start_quest(quest_resource: Dictionary) -> void:
	var qid = quest_resource["id"]
	if qid in active_quests or qid in completed_quests:
		return
	var q = QuestData.new()
	q.id = qid
	q.title = quest_resource["title"]
	q.description = quest_resource["description"]
	q.objectives = {}
	for obj in quest_resource["objectives"]:
		q.objectives[obj["id"]] = {"done": false, "count": 0, "target": obj.get("target", 1)}
	q.rewards = quest_resource.get("rewards", {})
	active_quests[qid] = q
	quest_started.emit(qid)

func update_objective(quest_id: String, objective_id: String, amount: int = 1) -> void:
	if not quest_id in active_quests:
		return
	var obj = active_quests[quest_id].objectives.get(objective_id)
	if not obj or obj["done"]:
		return
	obj["count"] = min(obj["count"] + amount, obj["target"])
	if obj["count"] >= obj["target"]:
		obj["done"] = true
	quest_updated.emit(quest_id, objective_id)
	_check_completion(quest_id)

func _check_completion(quest_id: String) -> void:
	var q = active_quests[quest_id]
	if q.objectives.values().all(func(o): return o["done"]):
		completed_quests.append(quest_id)
		active_quests.erase(quest_id)
		quest_completed.emit(quest_id)
'''
        return self._success_result(
            "任务系统已生成",
            {"script_name": "quest_system.gd", "code": code,
             "tips": "将此脚本添加为 Autoload，名称为 QuestSystem"}
        )

    def _gen_story_trigger(self) -> Dict[str, Any]:
        code = '''\
# story_trigger.gd — 剧情触发器（挂载到 Area2D/3D）
extends Area2D

@export var dialogue_id: String = "intro_scene"
@export var trigger_once: bool = true

var triggered: bool = false

func _ready() -> void:
	body_entered.connect(_on_body_entered)

func _on_body_entered(body: Node) -> void:
	if trigger_once and triggered:
		return
	if body.is_in_group("player"):
		triggered = true
		if has_node("/root/DialogueSystem"):
			get_node("/root/DialogueSystem").start_dialogue(dialogue_id)
'''
        return self._success_result(
            "剧情触发器已生成",
            {"script_name": "story_trigger.gd", "code": code}
        )

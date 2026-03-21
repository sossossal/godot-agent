"""
UIDesignerRole — UI 场景与脚本生成角色
"""
from typing import Dict, List, Any
from .base import BaseRole


class UIDesignerRole(BaseRole):
    """负责生成 UI 场景和对应控制脚本"""

    def get_description(self) -> str:
        return "UI 设计专家，生成 HUD、菜单、背包界面、对话框等游戏 UI"

    def get_capabilities(self) -> List[str]:
        return ["HUD 血条/魔法条", "暂停菜单", "主菜单", "背包界面", "对话框", "技能栏", "小地图"]

    def execute(self, command: str, context: Dict[str, Any]) -> Dict[str, Any]:
        cmd = command.lower()
        if any(k in cmd for k in ["hud", "血条", "头显"]):
            return self._gen_hud()
        elif any(k in cmd for k in ["暂停", "pause"]):
            return self._gen_pause_menu()
        elif any(k in cmd for k in ["背包", "道具栏", "inventory"]):
            return self._gen_inventory_ui()
        elif any(k in cmd for k in ["对话框", "dialogue box", "聊天框"]):
            return self._gen_dialogue_box()
        elif any(k in cmd for k in ["小地图", "minimap"]):
            return self._gen_minimap()
        else:
            return self._gen_hud()

    def _gen_hud(self) -> Dict[str, Any]:
        code = '''\
# hud.gd — HUD 控制器
extends CanvasLayer

@onready var health_bar: ProgressBar = $VBox/HealthBar
@onready var mana_bar: ProgressBar = $VBox/ManaBar
@onready var level_label: Label = $VBox/LevelLabel
@onready var gold_label: Label = $HBox/GoldLabel

func _ready() -> void:
	# 监听玩家信号
	if has_node("/root/Player"):
		var player = get_node("/root/Player")
		if player.has_signal("health_changed"):
			player.health_changed.connect(_on_health_changed)
		if player.has_signal("mana_changed"):
			player.mana_changed.connect(_on_mana_changed)

func _on_health_changed(current: int, maximum: int) -> void:
	health_bar.max_value = maximum
	health_bar.value = current
	# 血量低于 25% 时红色闪烁
	if float(current) / maximum < 0.25:
		health_bar.modulate = Color.RED
	else:
		health_bar.modulate = Color.WHITE

func _on_mana_changed(current: int, maximum: int) -> void:
	mana_bar.max_value = maximum
	mana_bar.value = current

func set_level(level: int) -> void:
	level_label.text = "Lv." + str(level)

func set_gold(amount: int) -> void:
	gold_label.text = "💰 " + str(amount)

func show_damage_number(amount: int, position: Vector2) -> void:
	"""在屏幕位置显示伤害飘字"""
	var label = Label.new()
	label.text = "-" + str(amount)
	label.position = position
	label.modulate = Color.RED
	add_child(label)
	var tween = create_tween()
	tween.tween_property(label, "position:y", position.y - 60, 0.8)
	tween.parallel().tween_property(label, "modulate:a", 0.0, 0.8)
	tween.tween_callback(label.queue_free)
'''
        return self._success_result("HUD 脚本已生成", {
            "script_name": "hud.gd", "code": code,
            "tips": "配合 CanvasLayer > VBoxContainer > (HealthBar + ManaBar) 节点结构使用"
        })

    def _gen_pause_menu(self) -> Dict[str, Any]:
        code = '''\
# pause_menu.gd — 暂停菜单
extends CanvasLayer

func _ready() -> void:
	hide()

func _input(event: InputEvent) -> void:
	if event.is_action_just_pressed("ui_cancel"):
		toggle_pause()

func toggle_pause() -> void:
	get_tree().paused = !get_tree().paused
	visible = get_tree().paused

func _on_resume_pressed() -> void:
	get_tree().paused = false
	hide()

func _on_settings_pressed() -> void:
	pass  # 打开设置界面

func _on_save_pressed() -> void:
	if has_node("/root/SaveSystem"):
		get_node("/root/SaveSystem").save_game()

func _on_quit_pressed() -> void:
	get_tree().paused = false
	get_tree().change_scene_to_file("res://scenes/main_menu.tscn")
'''
        return self._success_result("暂停菜单已生成",
            {"script_name": "pause_menu.gd", "code": code})

    def _gen_inventory_ui(self) -> Dict[str, Any]:
        code = '''\
# inventory_ui.gd — 背包界面
extends Control

const SLOT_SCENE = preload("res://ui/inventory_slot.tscn")
@onready var grid: GridContainer = $Panel/GridContainer
@onready var item_name_label: Label = $Panel/ItemInfo/NameLabel
@onready var item_desc_label: Label = $Panel/ItemInfo/DescLabel

var selected_slot: Control = null

func _ready() -> void:
	hide()
	if has_node("/root/Inventory"):
		get_node("/root/Inventory").item_changed.connect(refresh)

func toggle() -> void:
	visible = !visible
	if visible:
		refresh()

func refresh() -> void:
	# 清空现有格子
	for child in grid.get_children():
		child.queue_free()
	# 重建背包格子
	if not has_node("/root/Inventory"):
		return
	var inventory = get_node("/root/Inventory")
	for item in inventory.items:
		var slot = SLOT_SCENE.instantiate()
		slot.set_item(item)
		slot.slot_clicked.connect(_on_slot_clicked)
		grid.add_child(slot)

func _on_slot_clicked(item: Dictionary) -> void:
	item_name_label.text = item.get("name", "")
	item_desc_label.text = item.get("description", "")
'''
        return self._success_result("背包界面脚本已生成",
            {"script_name": "inventory_ui.gd", "code": code})

    def _gen_dialogue_box(self) -> Dict[str, Any]:
        code = '''\
# dialogue_box.gd — 对话框 UI 控制器
extends CanvasLayer

@onready var panel: Panel = $Panel
@onready var speaker_label: Label = $Panel/SpeakerLabel
@onready var text_label: RichTextLabel = $Panel/TextLabel
@onready var choice_container: VBoxContainer = $Panel/ChoiceContainer
@onready var continue_hint: Label = $Panel/ContinueHint

const CHOICES_BUTTON = preload("res://ui/choice_button.tscn")

var is_animating: bool = false

func _ready() -> void:
	hide()
	if has_node("/root/DialogueSystem"):
		var ds = get_node("/root/DialogueSystem")
		ds.dialogue_started.connect(_on_dialogue_started)
		ds.dialogue_line_changed.connect(_on_line_changed)
		ds.dialogue_ended.connect(_on_dialogue_ended)

func _on_dialogue_started(npc_name: String) -> void:
	show()
	speaker_label.text = npc_name

func _on_line_changed(line) -> void:
	text_label.text = ""
	# 打字机效果
	for c in line.text:
		text_label.text += c
		await get_tree().create_timer(0.03).timeout
	_build_choices(line.choices)

func _build_choices(choices: Array) -> void:
	for child in choice_container.get_children():
		child.queue_free()
	if choices.is_empty():
		continue_hint.show()
		return
	continue_hint.hide()
	for i in range(choices.size()):
		var btn = CHOICES_BUTTON.instantiate()
		btn.text = choices[i].get("text", "")
		btn.pressed.connect(func(): get_node("/root/DialogueSystem").advance(i))
		choice_container.add_child(btn)

func _on_dialogue_ended() -> void:
	hide()

func _input(event: InputEvent) -> void:
	if not visible: return
	if event.is_action_just_pressed("ui_accept") and choice_container.get_child_count() == 0:
		get_node("/root/DialogueSystem").advance()
'''
        return self._success_result("对话框 UI 已生成",
            {"script_name": "dialogue_box.gd", "code": code})

    def _gen_minimap(self) -> Dict[str, Any]:
        code = '''\
# minimap.gd — 小地图控制器
extends Control

@onready var viewport: SubViewport = $SubViewport
@onready var camera: Camera2D = $SubViewport/MinimapCamera
@export var target: NodePath
@export var zoom_level: float = 0.15

func _ready() -> void:
	camera.zoom = Vector2(zoom_level, zoom_level)

func _process(_delta: float) -> void:
	if not target.is_empty() and has_node(target):
		camera.global_position = get_node(target).global_position
'''
        return self._success_result("小地图脚本已生成",
            {"script_name": "minimap.gd", "code": code,
             "tips": "需配合 SubViewport 节点使用，将地图场景复制一份渲染到 SubViewport"})

# agent_panel.gd — Godot 编辑器插件：Agent 侧边栏
# 在 Godot 编辑器内嵌入 Godot Studio Agent 对话面板
@tool
extends EditorPlugin

const PANEL_NAME = "Agent"
var panel: Control

func _enter_tree() -> void:
	panel = _build_panel()
	add_control_to_dock(DOCK_SLOT_RIGHT_UR, panel)
	print("🎮 Godot Studio Agent 插件已加载")

func _exit_tree() -> void:
	if panel:
		remove_control_from_docks(panel)
		panel.queue_free()

func _build_panel() -> Control:
	var vbox = VBoxContainer.new()
	vbox.name = "GodotStudioAgent"

	# 标题
	var title = Label.new()
	title.text = "🎮 Studio Agent"
	title.add_theme_font_size_override("font_size", 14)
	vbox.add_child(title)

	# 输入框
	var input = TextEdit.new()
	input.placeholder_text = "描述你需要什么…"
	input.custom_minimum_size = Vector2(0, 80)
	input.name = "Input"
	vbox.add_child(input)

	# 发送按钮
	var btn = Button.new()
	btn.text = "▶ 发送到 Agent"
	btn.pressed.connect(func(): _send_command(input.text))
	vbox.add_child(btn)

	# API 地址
	var api_label = Label.new()
	api_label.text = "API: http://localhost:8000"
	api_label.modulate = Color(0.6, 0.6, 0.6)
	api_label.add_theme_font_size_override("font_size", 11)
	vbox.add_child(api_label)

	# 结果输出
	var result = RichTextLabel.new()
	result.name = "Result"
	result.bbcode_enabled = true
	result.custom_minimum_size = Vector2(0, 200)
	result.size_flags_vertical = Control.SIZE_EXPAND_FILL
	vbox.add_child(result)

	# 快速按钮组
	var hbox = HBoxContainer.new()
	for label_cmd in [["💻 移动", "生成 2D 玩家移动脚本"], ["💾 存档", "生成存档系统"], ["🤖 AI", "为敌人创建巡逻追击 AI"]]:
		var qbtn = Button.new()
		qbtn.text = label_cmd[0]
		var cmd = label_cmd[1]
		qbtn.pressed.connect(func():
			input.text = cmd
			_send_command(cmd)
		)
		hbox.add_child(qbtn)
	vbox.add_child(hbox)

	return vbox

func _send_command(command: String) -> void:
	if command.strip_edges().is_empty():
		return
	var result_label = panel.find_child("Result")
	if result_label:
		result_label.text = "[color=yellow]⏳ 正在请求 Agent...[/color]"

	var http = HTTPRequest.new()
	panel.add_child(http)
	http.request_completed.connect(func(result, code, headers, body):
		var text = body.get_string_from_utf8()
		var json = JSON.parse_string(text)
		if json and result_label:
			var msg = json.get("message", "")
			var code_data = json.get("data", {}).get("code", "")
			var display = "[color=cyan]%s[/color]" % msg
			if code_data:
				display += "\n[color=green]---  代码已生成  ---[/color]\n" + code_data.substr(0, 300) + ("..." if code_data.length() > 300 else "")
			result_label.text = display
		elif result_label:
			result_label.text = "[color=red]请求失败[/color]"
		http.queue_free()
	)

	var body = JSON.stringify({"command": command})
	http.request(
		"http://localhost:8000/execute",
		["Content-Type: application/json"],
		HTTPClient.METHOD_POST, body
	)

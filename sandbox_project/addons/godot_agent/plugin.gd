@tool
extends EditorPlugin

## Godot Agent 协同插件 (V1.5.0 - 实时事件流版)
## 职责: WebSocket 实时通信、事件驱动状态同步、编辑器命令执行、Dock 协同面板

var ws_url := ""
var socket: WebSocketPeer
var socket_pump_timer: Timer
var reconnect_timer: Timer
var state_sync_timer: Timer

var dock_panel: Control
var status_label: Label
var task_info_label: Label
var log_display: RichTextLabel
var confirm_button: Button
var rollback_button: Button

var last_state_hash := 0
var pending_events: Array[Dictionary] = []
var is_connected := false
var pending_force_sync := false
var current_task_id := ""
var current_step_id := ""
var observed_code_editor: Object = null
var active_editor_operation_audit: Dictionary = {}
var active_editor_operation_schema_version := "1.1"


func _enter_tree():
    set_process(true)
    _configure_server_url()
    socket = WebSocketPeer.new()
    _create_timers()
    dock_panel = _create_dock()
    add_control_to_dock(DOCK_SLOT_RIGHT_BL, dock_panel)
    _connect_editor_signals()
    _refresh_code_editor_binding(true)
    _connect_to_server()
    _queue_state_sync(true)
    print("Godot Agent realtime dock started")


func _configure_server_url():
    var api_host := OS.get_environment("GODOT_AGENT_API_HOST").strip_edges()
    if api_host.is_empty():
        api_host = "127.0.0.1"

    var raw_port := OS.get_environment("GODOT_AGENT_API_PORT").strip_edges()
    var api_port := 8000
    if not raw_port.is_empty() and raw_port.is_valid_int():
        api_port = int(raw_port)

    ws_url = "ws://%s:%d/ws/plugin" % [api_host, api_port]


func _exit_tree():
    set_process(false)
    _disconnect_editor_signals()
    _disconnect_code_editor()
    if dock_panel:
        remove_control_from_docks(dock_panel)
    if socket_pump_timer:
        socket_pump_timer.stop()
    if state_sync_timer:
        state_sync_timer.stop()
    if reconnect_timer:
        reconnect_timer.stop()
    if socket:
        socket.close()


func _process(_delta):
    _refresh_code_editor_binding()
    _pump_socket()


func _pump_socket():
    if socket == null:
        return

    socket.poll()
    var state := socket.get_ready_state()
    if state == WebSocketPeer.STATE_OPEN:
        if not is_connected:
            is_connected = true
            _on_connected()
        while socket.get_available_packet_count() > 0:
            var packet := socket.get_packet()
            _on_data_received(packet.get_string_from_utf8())
    elif state == WebSocketPeer.STATE_CLOSED:
        if is_connected:
            is_connected = false
            _on_disconnected()
        _schedule_reconnect()


func _create_timers():
    socket_pump_timer = Timer.new()
    socket_pump_timer.wait_time = 0.05
    socket_pump_timer.timeout.connect(_pump_socket)
    add_child(socket_pump_timer)
    socket_pump_timer.start()

    reconnect_timer = Timer.new()
    reconnect_timer.one_shot = true
    reconnect_timer.wait_time = 2.0
    reconnect_timer.timeout.connect(_connect_to_server)
    add_child(reconnect_timer)

    state_sync_timer = Timer.new()
    state_sync_timer.one_shot = true
    state_sync_timer.wait_time = 0.05
    state_sync_timer.timeout.connect(_flush_state_sync)
    add_child(state_sync_timer)


func _connect_to_server():
    if socket and socket.get_ready_state() in [WebSocketPeer.STATE_OPEN, WebSocketPeer.STATE_CONNECTING]:
        return
    socket = WebSocketPeer.new()
    var project_path := ProjectSettings.globalize_path("res://")
    var url := ws_url + "?project_path=" + project_path.uri_encode()
    var err := socket.connect_to_url(url)
    if err != OK:
        _set_connection_status(false, "无法连接服务端")
        _schedule_reconnect()


func _schedule_reconnect():
    if reconnect_timer and reconnect_timer.is_stopped():
        reconnect_timer.start()


func _on_connected():
    _set_connection_status(true, "实时连接已建立")
    if reconnect_timer:
        reconnect_timer.stop()
    _queue_state_sync(true)


func _on_disconnected():
    _set_connection_status(false, "连接已断开")


func _set_connection_status(online: bool, text: String):
    if status_label == null:
        return
    status_label.text = ("🟢 " if online else "🔴 ") + text
    status_label.modulate = Color.WHITE if online else Color(1.0, 0.45, 0.45)


func _queue_state_sync(force: bool = false):
    pending_force_sync = pending_force_sync or force
    if state_sync_timer and state_sync_timer.is_stopped():
        state_sync_timer.start()


func _flush_state_sync():
    if not is_connected:
        return
    _send_state(pending_force_sync)
    pending_force_sync = false


func _connect_editor_signals():
    var selection := get_editor_interface().get_selection()
    if selection and not selection.selection_changed.is_connected(_on_selection_changed):
        selection.selection_changed.connect(_on_selection_changed)

    if not scene_changed.is_connected(_on_scene_changed):
        scene_changed.connect(_on_scene_changed)
    if not main_screen_changed.is_connected(_on_main_screen_changed):
        main_screen_changed.connect(_on_main_screen_changed)
    if not resource_saved.is_connected(_on_resource_saved):
        resource_saved.connect(_on_resource_saved)


func _disconnect_editor_signals():
    var selection := get_editor_interface().get_selection()
    if selection and selection.selection_changed.is_connected(_on_selection_changed):
        selection.selection_changed.disconnect(_on_selection_changed)

    if scene_changed.is_connected(_on_scene_changed):
        scene_changed.disconnect(_on_scene_changed)
    if main_screen_changed.is_connected(_on_main_screen_changed):
        main_screen_changed.disconnect(_on_main_screen_changed)
    if resource_saved.is_connected(_on_resource_saved):
        resource_saved.disconnect(_on_resource_saved)


func _refresh_code_editor_binding(force: bool = false):
    var candidate = _get_current_code_editor(get_editor_interface().get_script_editor() if get_editor_interface().has_method("get_script_editor") else null)
    if not force and candidate == observed_code_editor:
        return

    _disconnect_code_editor()
    observed_code_editor = candidate
    if observed_code_editor == null:
        return

    if observed_code_editor.has_signal("caret_changed") and not observed_code_editor.caret_changed.is_connected(_on_code_caret_changed):
        observed_code_editor.caret_changed.connect(_on_code_caret_changed)
    if observed_code_editor.has_signal("text_changed") and not observed_code_editor.text_changed.is_connected(_on_code_text_changed):
        observed_code_editor.text_changed.connect(_on_code_text_changed)
    _queue_state_sync(true)


func _disconnect_code_editor():
    if observed_code_editor == null:
        return
    if observed_code_editor.has_signal("caret_changed") and observed_code_editor.caret_changed.is_connected(_on_code_caret_changed):
        observed_code_editor.caret_changed.disconnect(_on_code_caret_changed)
    if observed_code_editor.has_signal("text_changed") and observed_code_editor.text_changed.is_connected(_on_code_text_changed):
        observed_code_editor.text_changed.disconnect(_on_code_text_changed)
    observed_code_editor = null


func _on_selection_changed():
    _queue_state_sync()


func _on_scene_changed(_root):
    _refresh_code_editor_binding(true)
    _queue_state_sync(true)


func _on_main_screen_changed(_screen_name):
    _refresh_code_editor_binding(true)
    _queue_state_sync(true)


func _on_resource_saved(_resource):
    _queue_state_sync()


func _on_code_caret_changed():
    _queue_state_sync()


func _on_code_text_changed():
    _queue_state_sync()


func _on_data_received(data_str: String):
    var payload = JSON.parse_string(data_str)
    if typeof(payload) != TYPE_DICTIONARY:
        return

    if payload.has("commands"):
        for cmd in payload["commands"]:
            _handle_command(cmd)

    if payload.has("task_update"):
        _update_ui_task_state(payload["task_update"])


func _handle_command(cmd: Dictionary):
    var cmd_id := cmd.get("command_id", "")
    if cmd.get("type") == "execute_script":
        _run_internal_script(cmd.get("script", ""), cmd_id)
        _queue_state_sync(true)
    elif cmd.get("type") == "editor_operation":
        _run_editor_operation(cmd, cmd_id)
        _queue_state_sync(true)
    elif cmd.get("type") == "open_resource":
        _open_resource(
            cmd.get("path", ""),
            int(cmd.get("line", -1)),
            int(cmd.get("column", 0)),
            cmd.get("scene_node_path", ""),
            cmd.get("scene_node_name", ""),
            cmd.get("scene_instance_root_path", ""),
            cmd.get("scene_instance_source", ""),
            cmd.get("script_class_name", ""),
            cmd.get("script_symbol_kind", ""),
            cmd.get("script_symbol_name", ""),
            cmd.get("script_symbol_signature", ""),
            cmd_id
        )
        _queue_state_sync(true)


func _send_state(force: bool = false):
    var state := _build_editor_state(_capture_screenshot())
    var current_hash := hash(JSON.stringify(state))
    if not force and current_hash == last_state_hash and pending_events.is_empty():
        return

    last_state_hash = current_hash
    var payload := {"state": state}
    if not pending_events.is_empty():
        payload["state"]["events"] = pending_events.duplicate(true)
        pending_events.clear()
    socket.send_text(JSON.stringify(payload))


func _capture_screenshot() -> String:
    var interface := get_editor_interface()
    var base_control := interface.get_base_control()
    if base_control == null:
        return ""
    var viewport := base_control.get_viewport()
    if viewport == null:
        return ""
    var image := viewport.get_texture().get_image()
    if image == null:
        return ""
    image.resize(640, 360, Image.INTERPOLATE_LANCZOS)
    var buffer := image.save_jpg_to_buffer()
    return Marshalls.raw_to_base64(buffer)


func _send_plugin_event(event: Dictionary):
    if is_connected and socket and socket.get_ready_state() == WebSocketPeer.STATE_OPEN:
        socket.send_text(JSON.stringify({"event": event}))
    else:
        pending_events.append(event.duplicate(true))


func _run_internal_script(content: String, command_id: String = ""):
    var script := GDScript.new()
    var source_code := content.strip_edges()
    if not source_code.begins_with("@tool"):
        source_code = "@tool\nextends RefCounted\n\n" + source_code
    elif not source_code.contains("\nextends "):
        source_code = source_code.replace("@tool", "@tool\nextends RefCounted")

    script.source_code = source_code
    var reload_result := script.reload()
    if reload_result != OK:
        _send_plugin_event({
            "kind": "execute_script",
            "status": "error",
            "message": "Godot 内部脚本加载失败",
            "error_code": reload_result,
            "command_id": command_id
        })
        return

    var obj := RefCounted.new()
    obj.set_script(script)
    if not obj.has_method("_run"):
        _send_plugin_event({
            "kind": "execute_script",
            "status": "error",
            "message": "Godot 内部脚本缺少 _run 方法",
            "command_id": command_id
        })
        return

    obj.call("_run", self)
    _send_plugin_event({
        "kind": "execute_script",
        "status": "success",
        "message": "Godot 内部脚本执行完成",
        "command_id": command_id
    })


func _run_editor_operation(cmd: Dictionary, command_id: String = ""):
    var operation := str(cmd.get("operation", "")).strip_edges().to_lower()
    var audit = cmd.get("audit", {})
    active_editor_operation_audit = audit.duplicate(true) if typeof(audit) == TYPE_DICTIONARY else {}
    active_editor_operation_schema_version = str(cmd.get("schema_version", "1.1"))
    var interface := get_editor_interface()
    var root := interface.get_edited_scene_root()
    if root == null:
        _send_editor_operation_result(operation, command_id, "error", "当前没有可编辑场景")
        return

    match operation:
        "get_scene_tree":
            _operation_get_scene_tree(root, cmd, command_id)
        "select_node":
            _operation_select_node(root, cmd, command_id)
        "set_node_property":
            _operation_set_node_property(root, cmd, command_id)
        "create_node":
            _operation_create_node(root, cmd, command_id)
        "delete_node":
            _operation_delete_node(root, cmd, command_id)
        "save_scene":
            _operation_save_scene(root, cmd, command_id)
        "save_scene_as":
            _operation_save_scene_as(root, cmd, command_id)
        "reload_scene":
            _operation_reload_scene(root, cmd, command_id)
        "duplicate_node":
            _operation_duplicate_node(root, cmd, command_id)
        "reparent_node":
            _operation_reparent_node(root, cmd, command_id)
        "rename_node":
            _operation_rename_node(root, cmd, command_id)
        "move_node_order":
            _operation_move_node_order(root, cmd, command_id)
        "batch_set_properties":
            _operation_batch_set_properties(root, cmd, command_id)
        "batch_create_nodes":
            _operation_batch_create_nodes(root, cmd, command_id)
        "attach_script":
            _operation_attach_script(root, cmd, command_id)
        "detach_script":
            _operation_detach_script(root, cmd, command_id)
        "instantiate_scene":
            _operation_instantiate_scene(root, cmd, command_id)
        _:
            _send_editor_operation_result(operation, command_id, "error", "不支持的编辑器实时操作: %s" % operation)


func _operation_get_scene_tree(root: Node, cmd: Dictionary, command_id: String):
    var max_depth := clampi(int(cmd.get("max_depth", 4)), 0, 16)
    var max_nodes := clampi(int(cmd.get("max_nodes", 200)), 1, 1000)
    var counter := {"count": 0, "truncated": false}
    var tree := _serialize_scene_node(root, root, 0, max_depth, max_nodes, counter)
    _send_editor_operation_result(
        "get_scene_tree",
        command_id,
        "success",
        "已读取当前场景树",
        {
            "scene_path": root.scene_file_path,
            "root": tree,
            "node_count": counter["count"],
            "truncated": counter["truncated"]
        }
    )


func _operation_select_node(root: Node, cmd: Dictionary, command_id: String):
    var node = _resolve_operation_node(root, str(cmd.get("node_path", "")), str(cmd.get("node_name", "")))
    if node == null:
        _send_editor_operation_result("select_node", command_id, "error", "未找到要选择的节点")
        return

    _select_editor_node(root, node)
    _send_editor_operation_result(
        "select_node",
        command_id,
        "success",
        "已选中节点 %s" % node.name,
        {
            "selected_node_name": node.name,
            "selected_node_path": _get_relative_node_path(root, node),
            "selected_node_type": node.get_class()
        }
    )


func _operation_set_node_property(root: Node, cmd: Dictionary, command_id: String):
    var node = _resolve_operation_node(root, str(cmd.get("node_path", "")), str(cmd.get("node_name", "")))
    var result = _apply_node_property(
        root,
        node,
        str(cmd.get("property_name", "")),
        cmd.get("value"),
        str(cmd.get("value_type", ""))
    )
    if result.get("status") == "success":
        _select_editor_node(root, node)
    _send_editor_operation_result(
        "set_node_property",
        command_id,
        str(result.get("status", "error")),
        str(result.get("message", "设置节点属性失败")),
        result
    )


func _operation_create_node(root: Node, cmd: Dictionary, command_id: String):
    var result = _create_node_from_payload(root, cmd, bool(cmd.get("select_created", true)))
    result.erase("_node")

    _send_editor_operation_result(
        "create_node",
        command_id,
        str(result.get("status", "error")),
        str(result.get("message", "创建节点失败")),
        result
    )


func _operation_delete_node(root: Node, cmd: Dictionary, command_id: String):
    var node = _resolve_operation_node(root, str(cmd.get("node_path", "")), str(cmd.get("node_name", "")))
    if node == null:
        _send_editor_operation_result("delete_node", command_id, "error", "未找到要删除的节点")
        return
    if node == root:
        _send_editor_operation_result("delete_node", command_id, "error", "不能通过实时操作删除当前场景根节点")
        return

    var deleted_path := _get_relative_node_path(root, node)
    var deleted_name := str(node.name)
    var deleted_type := str(node.get_class())
    var selection := get_editor_interface().get_selection()
    if selection:
        selection.clear()
    var parent = node.get_parent()
    if parent:
        parent.remove_child(node)
    node.free()

    _send_editor_operation_result(
        "delete_node",
        command_id,
        "success",
        "已删除节点 %s" % deleted_name,
        {
            "deleted_node_name": deleted_name,
            "deleted_node_path": deleted_path,
            "deleted_node_type": deleted_type
        }
    )


func _operation_save_scene(root: Node, _cmd: Dictionary, command_id: String):
    var scene_path := str(root.scene_file_path)
    if scene_path.is_empty():
        _send_editor_operation_result("save_scene", command_id, "error", "当前场景没有保存路径")
        return

    var result = _save_scene_to_path(root, scene_path)
    _send_editor_operation_result(
        "save_scene",
        command_id,
        result["status"],
        result["message"],
        {"scene_path": scene_path, "saved": result["status"] == "success", "error_code": result.get("error_code")}
    )


func _operation_save_scene_as(root: Node, cmd: Dictionary, command_id: String):
    var scene_path = _normalize_operation_resource_path(str(cmd.get("scene_path", "")))
    if scene_path.is_empty():
        _send_editor_operation_result("save_scene_as", command_id, "error", "scene_path 为空")
        return

    var result = _save_scene_to_path(root, scene_path)
    _send_editor_operation_result(
        "save_scene_as",
        command_id,
        result["status"],
        result["message"],
        {"scene_path": scene_path, "saved": result["status"] == "success", "error_code": result.get("error_code")}
    )


func _operation_reload_scene(root: Node, cmd: Dictionary, command_id: String):
    var scene_path = _normalize_operation_resource_path(str(cmd.get("scene_path", "")))
    if scene_path.is_empty():
        scene_path = str(root.scene_file_path)
    if scene_path.is_empty():
        _send_editor_operation_result("reload_scene", command_id, "error", "没有可重载的场景路径")
        return

    var interface := get_editor_interface()
    if scene_path != str(root.scene_file_path) and interface.has_method("open_scene_from_path"):
        interface.open_scene_from_path(scene_path)
    elif interface.has_method("reload_scene_from_path"):
        interface.call("reload_scene_from_path", scene_path)
    elif interface.has_method("open_scene_from_path"):
        interface.open_scene_from_path(scene_path)
    else:
        _send_editor_operation_result("reload_scene", command_id, "error", "当前 Godot 版本不支持重载场景")
        return

    _send_editor_operation_result(
        "reload_scene",
        command_id,
        "success",
        "已重载场景 %s" % scene_path,
        {"scene_path": scene_path}
    )


func _operation_duplicate_node(root: Node, cmd: Dictionary, command_id: String):
    var node = _resolve_operation_node(root, str(cmd.get("node_path", "")), str(cmd.get("node_name", "")))
    if node == null:
        _send_editor_operation_result("duplicate_node", command_id, "error", "未找到要复制的节点")
        return
    if node == root:
        _send_editor_operation_result("duplicate_node", command_id, "error", "不能复制当前场景根节点")
        return

    var parent = node.get_parent()
    if parent == null:
        _send_editor_operation_result("duplicate_node", command_id, "error", "目标节点没有父节点")
        return

    var duplicated = node.duplicate()
    if duplicated == null or not (duplicated is Node):
        _send_editor_operation_result("duplicate_node", command_id, "error", "节点复制失败")
        return

    var duplicate_node: Node = duplicated
    var requested_name := str(cmd.get("new_name", "")).strip_edges()
    if requested_name.is_empty():
        requested_name = "%s_copy" % node.name
    duplicate_node.name = _make_unique_child_name_for_node(parent, duplicate_node, requested_name)
    parent.add_child(duplicate_node)
    _set_node_owner_recursive(duplicate_node, root)
    _select_editor_node(root, duplicate_node)

    _send_editor_operation_result(
        "duplicate_node",
        command_id,
        "success",
        "已复制节点 %s" % node.name,
        {
            "source_node_path": _get_relative_node_path(root, node),
            "node_name": duplicate_node.name,
            "node_path": _get_relative_node_path(root, duplicate_node),
            "node_type": duplicate_node.get_class(),
            "parent_path": _get_relative_node_path(root, parent)
        }
    )


func _operation_reparent_node(root: Node, cmd: Dictionary, command_id: String):
    var node = _resolve_operation_node(root, str(cmd.get("node_path", "")), str(cmd.get("node_name", "")))
    if node == null:
        _send_editor_operation_result("reparent_node", command_id, "error", "未找到要移动的节点")
        return
    if node == root:
        _send_editor_operation_result("reparent_node", command_id, "error", "不能移动当前场景根节点")
        return

    var target_parent = _resolve_operation_node(root, str(cmd.get("target_parent_path", "")), "")
    if target_parent == null:
        target_parent = _resolve_operation_node(root, str(cmd.get("parent_path", ".")), "")
    if target_parent == null:
        _send_editor_operation_result("reparent_node", command_id, "error", "未找到新的父节点")
        return
    if _is_node_descendant(target_parent, node):
        _send_editor_operation_result("reparent_node", command_id, "error", "不能把节点移动到自身或子节点下")
        return

    var old_parent = node.get_parent()
    var old_path := _get_relative_node_path(root, node)
    var old_parent_path := _get_relative_node_path(root, old_parent)
    var preserve_transform := bool(cmd.get("preserve_global_transform", true))
    var saved_transform = null
    var saved_transform_kind := ""
    if preserve_transform and node is Node2D:
        saved_transform = node.global_transform
        saved_transform_kind = "node2d"
    elif preserve_transform and node is Node3D:
        saved_transform = node.global_transform
        saved_transform_kind = "node3d"

    old_parent.remove_child(node)
    target_parent.add_child(node)
    _set_node_owner_recursive(node, root)
    if saved_transform_kind == "node2d":
        node.global_transform = saved_transform
    elif saved_transform_kind == "node3d":
        node.global_transform = saved_transform
    _select_editor_node(root, node)

    _send_editor_operation_result(
        "reparent_node",
        command_id,
        "success",
        "已移动节点 %s" % node.name,
        {
            "old_node_path": old_path,
            "node_path": _get_relative_node_path(root, node),
            "node_name": node.name,
            "old_parent_path": old_parent_path,
            "parent_path": _get_relative_node_path(root, target_parent),
            "preserve_global_transform": preserve_transform
        }
    )


func _operation_rename_node(root: Node, cmd: Dictionary, command_id: String):
    var node = _resolve_operation_node(root, str(cmd.get("node_path", "")), str(cmd.get("node_name", "")))
    if node == null:
        _send_editor_operation_result("rename_node", command_id, "error", "未找到要重命名的节点")
        return

    var requested_name := str(cmd.get("new_name", "")).strip_edges()
    if requested_name.is_empty():
        _send_editor_operation_result("rename_node", command_id, "error", "new_name 为空")
        return

    var old_name := str(node.name)
    var old_path := _get_relative_node_path(root, node)
    var parent = node.get_parent()
    node.name = _make_unique_child_name_for_node(parent, node, requested_name) if parent else requested_name
    _select_editor_node(root, node)
    _send_editor_operation_result(
        "rename_node",
        command_id,
        "success",
        "已重命名节点 %s -> %s" % [old_name, node.name],
        {
            "old_node_name": old_name,
            "old_node_path": old_path,
            "node_name": node.name,
            "node_path": _get_relative_node_path(root, node)
        }
    )


func _operation_move_node_order(root: Node, cmd: Dictionary, command_id: String):
    var node = _resolve_operation_node(root, str(cmd.get("node_path", "")), str(cmd.get("node_name", "")))
    if node == null:
        _send_editor_operation_result("move_node_order", command_id, "error", "未找到要调整顺序的节点")
        return
    if node == root:
        _send_editor_operation_result("move_node_order", command_id, "error", "不能调整当前场景根节点顺序")
        return
    var parent = node.get_parent()
    if parent == null:
        _send_editor_operation_result("move_node_order", command_id, "error", "目标节点没有父节点")
        return

    var old_index := int(node.get_index())
    var target_index := clampi(int(cmd.get("index", old_index)), 0, max(0, parent.get_child_count() - 1))
    parent.move_child(node, target_index)
    _select_editor_node(root, node)
    _send_editor_operation_result(
        "move_node_order",
        command_id,
        "success",
        "已调整节点顺序 %s: %d -> %d" % [node.name, old_index, target_index],
        {
            "node_name": node.name,
            "node_path": _get_relative_node_path(root, node),
            "old_index": old_index,
            "index": target_index,
            "parent_path": _get_relative_node_path(root, parent)
        }
    )


func _operation_batch_set_properties(root: Node, cmd: Dictionary, command_id: String):
    var items = cmd.get("items", [])
    if typeof(items) != TYPE_ARRAY or items.is_empty():
        _send_editor_operation_result("batch_set_properties", command_id, "error", "items 为空")
        return

    var results: Array[Dictionary] = []
    var success_count := 0
    for index in range(items.size()):
        var item = items[index]
        if typeof(item) != TYPE_DICTIONARY:
            results.append({"index": index, "status": "error", "message": "item 不是对象"})
            continue
        var node = _resolve_operation_node(root, str(item.get("node_path", "")), str(item.get("node_name", "")))
        var result = _apply_node_property(
            root,
            node,
            str(item.get("property_name", "")),
            item.get("value"),
            str(item.get("value_type", ""))
        )
        result["index"] = index
        results.append(result)
        if result.get("status") == "success":
            success_count += 1

    _send_editor_operation_result(
        "batch_set_properties",
        command_id,
        "success" if success_count == results.size() else "error",
        "批量设置属性完成: %d/%d" % [success_count, results.size()],
        {
            "success_count": success_count,
            "failure_count": results.size() - success_count,
            "results": results
        }
    )


func _operation_batch_create_nodes(root: Node, cmd: Dictionary, command_id: String):
    var items = cmd.get("items", [])
    if typeof(items) != TYPE_ARRAY or items.is_empty():
        _send_editor_operation_result("batch_create_nodes", command_id, "error", "items 为空")
        return

    var results: Array[Dictionary] = []
    var success_count := 0
    var last_created: Node = null
    for index in range(items.size()):
        var item = items[index]
        if typeof(item) != TYPE_DICTIONARY:
            results.append({"index": index, "status": "error", "message": "item 不是对象"})
            continue
        var result = _create_node_from_payload(root, item, false)
        result["index"] = index
        results.append(result)
        if result.get("status") == "success":
            success_count += 1
            last_created = result.get("_node")
            result.erase("_node")

    if bool(cmd.get("select_created", true)) and last_created:
        _select_editor_node(root, last_created)

    _send_editor_operation_result(
        "batch_create_nodes",
        command_id,
        "success" if success_count == results.size() else "error",
        "批量创建节点完成: %d/%d" % [success_count, results.size()],
        {
            "success_count": success_count,
            "failure_count": results.size() - success_count,
            "results": results
        }
    )


func _operation_attach_script(root: Node, cmd: Dictionary, command_id: String):
    var node = _resolve_operation_node(root, str(cmd.get("node_path", "")), str(cmd.get("node_name", "")))
    if node == null:
        _send_editor_operation_result("attach_script", command_id, "error", "未找到要挂载脚本的节点")
        return

    var script_path = _normalize_operation_resource_path(str(cmd.get("script_path", "")))
    if script_path.is_empty():
        _send_editor_operation_result("attach_script", command_id, "error", "script_path 为空")
        return
    var script_resource = load(script_path)
    if script_resource == null or not (script_resource is Script):
        _send_editor_operation_result("attach_script", command_id, "error", "无法加载脚本 %s" % script_path)
        return

    node.set_script(script_resource)
    _select_editor_node(root, node)
    _send_editor_operation_result(
        "attach_script",
        command_id,
        "success",
        "已挂载脚本 %s" % script_path,
        {
            "node_name": node.name,
            "node_path": _get_relative_node_path(root, node),
            "script_path": script_path
        }
    )


func _operation_detach_script(root: Node, cmd: Dictionary, command_id: String):
    var node = _resolve_operation_node(root, str(cmd.get("node_path", "")), str(cmd.get("node_name", "")))
    if node == null:
        _send_editor_operation_result("detach_script", command_id, "error", "未找到要卸载脚本的节点")
        return

    var old_script = node.get_script()
    var old_script_path = str(old_script.resource_path) if old_script and old_script is Script else ""
    node.set_script(null)
    _select_editor_node(root, node)
    _send_editor_operation_result(
        "detach_script",
        command_id,
        "success",
        "已卸载节点脚本",
        {
            "node_name": node.name,
            "node_path": _get_relative_node_path(root, node),
            "old_script_path": old_script_path
        }
    )


func _operation_instantiate_scene(root: Node, cmd: Dictionary, command_id: String):
    var parent = _resolve_operation_node(root, str(cmd.get("parent_path", ".")), "")
    if parent == null:
        _send_editor_operation_result("instantiate_scene", command_id, "error", "未找到父节点")
        return

    var scene_path = _normalize_operation_resource_path(str(cmd.get("scene_path", "")))
    if scene_path.is_empty():
        _send_editor_operation_result("instantiate_scene", command_id, "error", "scene_path 为空")
        return
    var packed = load(scene_path)
    if packed == null or not (packed is PackedScene):
        _send_editor_operation_result("instantiate_scene", command_id, "error", "无法加载 PackedScene %s" % scene_path)
        return

    var instance = packed.instantiate()
    if instance == null or not (instance is Node):
        _send_editor_operation_result("instantiate_scene", command_id, "error", "场景实例化失败")
        return

    var scene_node: Node = instance
    var requested_name := str(cmd.get("node_name", "")).strip_edges()
    if not requested_name.is_empty():
        scene_node.name = _make_unique_child_name_for_node(parent, scene_node, requested_name)
    parent.add_child(scene_node)
    _set_node_owner_recursive(scene_node, root)
    if bool(cmd.get("select_created", true)):
        _select_editor_node(root, scene_node)

    _send_editor_operation_result(
        "instantiate_scene",
        command_id,
        "success",
        "已实例化场景 %s" % scene_path,
        {
            "scene_path": scene_path,
            "node_name": scene_node.name,
            "node_path": _get_relative_node_path(root, scene_node),
            "node_type": scene_node.get_class(),
            "parent_path": _get_relative_node_path(root, parent)
        }
    )


func _send_editor_operation_result(
    operation: String,
    command_id: String,
    status: String,
    message: String,
    payload: Dictionary = {}
):
    var event := {
        "kind": "editor_operation",
        "schema_version": active_editor_operation_schema_version,
        "operation": operation,
        "status": status,
        "message": message,
        "command_id": command_id
    }
    if not active_editor_operation_audit.is_empty():
        var event_audit := active_editor_operation_audit.duplicate(true)
        event_audit["completed_at"] = Time.get_datetime_string_from_system(true)
        event["audit"] = event_audit
    for key in payload.keys():
        if payload[key] != null:
            event[key] = payload[key]
    _send_plugin_event(event)


func _save_scene_to_path(root: Node, scene_path: String) -> Dictionary:
    var normalized_path = _normalize_operation_resource_path(scene_path)
    if normalized_path.is_empty():
        return {"status": "error", "message": "场景路径为空", "error_code": ERR_INVALID_PARAMETER}
    if not normalized_path.ends_with(".tscn") and not normalized_path.ends_with(".scn"):
        return {"status": "error", "message": "场景路径必须以 .tscn 或 .scn 结尾", "error_code": ERR_INVALID_PARAMETER}

    var packed := PackedScene.new()
    var pack_result := packed.pack(root)
    if pack_result != OK:
        return {"status": "error", "message": "打包当前场景失败", "error_code": pack_result}

    var save_result := ResourceSaver.save(packed, normalized_path)
    if save_result != OK:
        return {"status": "error", "message": "保存场景失败: %s" % normalized_path, "error_code": save_result}
    return {"status": "success", "message": "已保存场景 %s" % normalized_path}


func _normalize_operation_resource_path(path_value: String) -> String:
    var path := path_value.strip_edges().replace("\\", "/")
    if path.is_empty():
        return ""
    if path.begins_with("res://"):
        return path
    while path.begins_with("/"):
        path = path.substr(1)
    return "res://%s" % path


func _apply_node_property(
    root: Node,
    node,
    property_name: String,
    raw_value,
    value_type: String
) -> Dictionary:
    if node == null:
        return {"status": "error", "message": "未找到要设置属性的节点"}

    var normalized_property := property_name.strip_edges()
    if normalized_property.is_empty():
        return {
            "status": "error",
            "message": "属性名为空",
            "node_path": _get_relative_node_path(root, node) if node is Node else ""
        }
    if not _node_has_property(node, normalized_property):
        return {
            "status": "error",
            "message": "节点 %s 不包含属性 %s" % [node.name, normalized_property],
            "node_name": node.name,
            "node_path": _get_relative_node_path(root, node),
            "property_name": normalized_property
        }

    var normalized_value_type := value_type.strip_edges().to_lower()
    var value = _coerce_editor_operation_value(raw_value, normalized_value_type)
    node.set(normalized_property, value)
    return {
        "status": "success",
        "message": "已设置节点 %s 的属性 %s" % [node.name, normalized_property],
        "node_name": node.name,
        "node_path": _get_relative_node_path(root, node),
        "node_type": node.get_class(),
        "property_name": normalized_property,
        "value_type": normalized_value_type,
        "value": _serialize_operation_value(value)
    }


func _create_node_from_payload(root: Node, payload: Dictionary, select_created: bool = true) -> Dictionary:
    var parent = _resolve_operation_node(root, str(payload.get("parent_path", ".")), "")
    if parent == null:
        return {"status": "error", "message": "未找到父节点", "parent_path": str(payload.get("parent_path", "."))}

    var node_type := str(payload.get("node_type", "Node2D")).strip_edges()
    if node_type.is_empty():
        node_type = "Node"
    if not ClassDB.class_exists(node_type) or not ClassDB.can_instantiate(node_type):
        return {"status": "error", "message": "无法实例化节点类型 %s" % node_type, "node_type": node_type}

    var instance = ClassDB.instantiate(node_type)
    if instance == null or not (instance is Node):
        return {"status": "error", "message": "%s 不是 Node 类型" % node_type, "node_type": node_type}

    var new_node: Node = instance
    var node_name := str(payload.get("node_name", "")).strip_edges()
    if node_name.is_empty():
        node_name = node_type
    new_node.name = _make_unique_child_name_for_node(parent, new_node, node_name)
    parent.add_child(new_node)
    _set_node_owner_recursive(new_node, root)
    if select_created:
        _select_editor_node(root, new_node)
    return {
        "status": "success",
        "message": "已创建节点 %s" % new_node.name,
        "node_name": new_node.name,
        "node_path": _get_relative_node_path(root, new_node),
        "node_type": new_node.get_class(),
        "parent_path": _get_relative_node_path(root, parent),
        "_node": new_node
    }


func _set_node_owner_recursive(node: Node, owner: Node):
    node.owner = owner
    for child in node.get_children():
        if child is Node:
            _set_node_owner_recursive(child, owner)


func _make_unique_child_name_for_node(parent: Node, node: Node, requested_name: String) -> String:
    var base_name := requested_name.strip_edges()
    if base_name.is_empty():
        base_name = node.get_class()
    var candidate := base_name
    var suffix := 2
    while parent:
        var existing = parent.get_node_or_null(NodePath(candidate))
        if existing == null or existing == node:
            break
        candidate = "%s_%d" % [base_name, suffix]
        suffix += 1
    return candidate


func _is_node_descendant(candidate: Node, ancestor: Node) -> bool:
    var current = candidate
    while current:
        if current == ancestor:
            return true
        current = current.get_parent()
    return false


func _serialize_scene_node(
    root: Node,
    node: Node,
    depth: int,
    max_depth: int,
    max_nodes: int,
    counter: Dictionary
) -> Dictionary:
    if int(counter["count"]) >= max_nodes:
        counter["truncated"] = true
        return {}

    counter["count"] = int(counter["count"]) + 1
    var item := {
        "name": node.name,
        "path": _get_relative_node_path(root, node),
        "type": node.get_class(),
        "child_count": node.get_child_count(),
        "children": []
    }

    var node_script = node.get_script()
    if node_script and node_script is Script and not node_script.resource_path.is_empty():
        item["script_path"] = node_script.resource_path

    if depth >= max_depth:
        if node.get_child_count() > 0:
            item["children_truncated"] = true
        return item

    for child in node.get_children():
        if int(counter["count"]) >= max_nodes:
            counter["truncated"] = true
            break
        item["children"].append(_serialize_scene_node(root, child, depth + 1, max_depth, max_nodes, counter))
    return item


func _resolve_operation_node(root: Node, node_path: String, node_name: String):
    if root == null:
        return null

    var trimmed_path := node_path.strip_edges()
    var trimmed_name := node_name.strip_edges()
    if not trimmed_path.is_empty() and trimmed_path != ".":
        var candidate := root.get_node_or_null(NodePath(trimmed_path))
        if candidate:
            return candidate
    elif trimmed_path == ".":
        return root

    if not trimmed_name.is_empty():
        return _find_node_by_name(root, trimmed_name)
    if trimmed_path.is_empty():
        return root
    return null


func _select_editor_node(root: Node, node: Node):
    var interface := get_editor_interface()
    var selection := interface.get_selection()
    if selection:
        selection.clear()
        if selection.has_method("add_node"):
            selection.add_node(node)
    if interface.has_method("inspect_object"):
        interface.inspect_object(node)


func _node_has_property(node: Node, property_name: String) -> bool:
    for property in node.get_property_list():
        if str(property.get("name", "")) == property_name:
            return true
    return false


func _coerce_editor_operation_value(value, value_type: String):
    match value_type:
        "int":
            return int(value)
        "float":
            return float(value)
        "bool":
            if typeof(value) == TYPE_STRING:
                return str(value).strip_edges().to_lower() in ["1", "true", "yes", "on"]
            return bool(value)
        "string":
            return str(value)
        "vector2":
            if typeof(value) == TYPE_DICTIONARY:
                return Vector2(float(value.get("x", 0)), float(value.get("y", 0)))
            if typeof(value) == TYPE_ARRAY and value.size() >= 2:
                return Vector2(float(value[0]), float(value[1]))
        "vector3":
            if typeof(value) == TYPE_DICTIONARY:
                return Vector3(float(value.get("x", 0)), float(value.get("y", 0)), float(value.get("z", 0)))
            if typeof(value) == TYPE_ARRAY and value.size() >= 3:
                return Vector3(float(value[0]), float(value[1]), float(value[2]))
        "color":
            if typeof(value) == TYPE_DICTIONARY:
                return Color(
                    float(value.get("r", 1)),
                    float(value.get("g", 1)),
                    float(value.get("b", 1)),
                    float(value.get("a", 1))
                )
            if typeof(value) == TYPE_ARRAY and value.size() >= 3:
                return Color(
                    float(value[0]),
                    float(value[1]),
                    float(value[2]),
                    float(value[3]) if value.size() > 3 else 1.0
                )
            if typeof(value) == TYPE_STRING:
                return Color.html(str(value))
    return value


func _serialize_operation_value(value):
    match typeof(value):
        TYPE_VECTOR2:
            return {"x": value.x, "y": value.y}
        TYPE_VECTOR3:
            return {"x": value.x, "y": value.y, "z": value.z}
        TYPE_COLOR:
            return {"r": value.r, "g": value.g, "b": value.b, "a": value.a}
    return value


func _open_resource(
    path: String,
    line: int = -1,
    column: int = 0,
    scene_node_path: String = "",
    scene_node_name: String = "",
    scene_instance_root_path: String = "",
    scene_instance_source: String = "",
    script_class_name: String = "",
    script_symbol_kind: String = "",
    script_symbol_name: String = "",
    script_symbol_signature: String = "",
    command_id: String = ""
):
    if path.is_empty():
        _send_plugin_event({
            "kind": "open_resource",
            "status": "error",
            "message": "资源路径为空",
            "command_id": command_id
        })
        return

    var interface := get_editor_interface()
    var payload := {
        "kind": "open_resource",
        "path": path,
        "line": line if line > 0 else null,
        "command_id": command_id
    }

    if interface.has_method("get_file_system_dock"):
        var fs_dock = interface.get_file_system_dock()
        if fs_dock and fs_dock.has_method("navigate_to_path"):
            fs_dock.navigate_to_path(path)

    if path.ends_with(".tscn") and interface.has_method("open_scene_from_path"):
        if interface.has_method("set_main_screen_editor"):
            interface.set_main_screen_editor("2D")
        interface.open_scene_from_path(path)
        payload["mode"] = "scene"
        payload["scene_node_path"] = scene_node_path
        payload["scene_node_name"] = scene_node_name
        payload["scene_instance_root_path"] = scene_instance_root_path
        payload["scene_instance_source"] = scene_instance_source
        if not scene_node_path.is_empty() or not scene_node_name.is_empty():
            _focus_scene_target(
                path,
                scene_node_path,
                scene_node_name,
                scene_instance_root_path,
                scene_instance_source,
                8,
                command_id
            )
        else:
            payload["status"] = "success"
            payload["message"] = "Godot 已打开场景 %s" % path
            _send_plugin_event(payload)
        return

    if path.ends_with(".gd"):
        var script_resource := load(path)
        if script_resource and interface.has_method("edit_script"):
            if interface.has_method("set_main_screen_editor"):
                interface.set_main_screen_editor("Script")
            interface.edit_script(script_resource, line, max(column, 0), true)
            payload["status"] = "success"
            payload["mode"] = "script"
            payload["script_class_name"] = script_class_name
            payload["script_symbol_kind"] = script_symbol_kind
            payload["script_symbol_name"] = script_symbol_name
            payload["script_symbol_signature"] = script_symbol_signature
            payload["message"] = "Godot 已打开脚本 %s%s" % [
                path,
                ":%d" % line if line > 0 else ""
            ]
            var label := _format_script_target_label(script_class_name, script_symbol_kind, script_symbol_signature)
            if not label.is_empty():
                payload["message"] += " (%s)" % label
            _send_plugin_event(payload)
            return

    var resource := load(path)
    if resource and interface.has_method("edit_resource"):
        if interface.has_method("inspect_object"):
            interface.inspect_object(resource)
        interface.edit_resource(resource)
        payload["status"] = "success"
        payload["mode"] = "resource"
        payload["message"] = "Godot 已打开资源 %s" % path
        _send_plugin_event(payload)
        return

    payload["status"] = "error"
    payload["mode"] = "resource"
    payload["message"] = "Godot 无法打开资源 %s" % path
    _send_plugin_event(payload)


func _focus_scene_target(
    scene_path: String,
    scene_node_path: String,
    scene_node_name: String,
    scene_instance_root_path: String,
    scene_instance_source: String,
    retries: int = 8,
    command_id: String = ""
):
    var interface := get_editor_interface()
    var root := interface.get_edited_scene_root()
    if root and root.scene_file_path == scene_path:
        var target: Node = root
        if not scene_node_path.is_empty() and scene_node_path != ".":
            target = root.get_node_or_null(NodePath(scene_node_path))
        elif not scene_node_name.is_empty():
            target = _find_node_by_name(root, scene_node_name)

        if target:
            var selection := interface.get_selection()
            if selection:
                selection.clear()
                if selection.has_method("add_node"):
                    selection.add_node(target)
            if interface.has_method("inspect_object"):
                interface.inspect_object(target)
            _send_plugin_event({
                "kind": "open_resource",
                "status": "success",
                "mode": "scene",
                "path": scene_path,
                "scene_node_path": scene_node_path if not scene_node_path.is_empty() else _get_relative_node_path(root, target),
                "scene_node_name": target.name,
                "scene_instance_root_path": scene_instance_root_path,
                "scene_instance_source": scene_instance_source,
                "command_id": command_id,
                "message": "Godot 已打开场景 %s 并选中节点 %s" % [
                    scene_path,
                    _format_scene_target_label(
                        target.name,
                        scene_node_path if not scene_node_path.is_empty() else _get_relative_node_path(root, target),
                        scene_instance_source
                    )
                ]
            })
            return

    if retries > 0:
        var timer := get_tree().create_timer(0.05)
        timer.timeout.connect(
            Callable(self, "_focus_scene_target").bind(
                scene_path,
                scene_node_path,
                scene_node_name,
                scene_instance_root_path,
                scene_instance_source,
                retries - 1,
                command_id
            ),
            CONNECT_ONE_SHOT
        )
        return

    _send_plugin_event({
        "kind": "open_resource",
        "status": "success",
        "mode": "scene",
        "path": scene_path,
        "scene_node_path": scene_node_path,
        "scene_node_name": scene_node_name,
        "scene_instance_root_path": scene_instance_root_path,
        "scene_instance_source": scene_instance_source,
        "command_id": command_id,
        "message": "Godot 已打开场景 %s，但未能定位节点 %s" % [
            scene_path,
            _format_scene_target_label(scene_node_name, scene_node_path, scene_instance_source)
        ]
    })


func _build_editor_state(screenshot_base64: String) -> Dictionary:
    var interface := get_editor_interface()
    var root := interface.get_edited_scene_root()
    var selection := interface.get_selection()
    var selected_nodes_raw = selection.get_selected_nodes() if selection else []

    var selected_node_names: Array[String] = []
    var selected_node_paths: Array[String] = []
    var selected_node_details: Array[Dictionary] = []
    for node in selected_nodes_raw:
        if node == null:
            continue
        var node_path := _get_relative_node_path(root, node)
        selected_node_names.append(node.name)
        selected_node_paths.append(node_path)
        selected_node_details.append(_build_selected_node_detail(root, node, node_path))

    var state := {
        "is_active": true,
        "current_scene": root.scene_file_path if root else "",
        "edited_scene_root_name": root.name if root else "",
        "selected_nodes": selected_node_names,
        "selected_node_paths": selected_node_paths,
        "selected_node_count": selected_node_paths.size(),
        "selected_node_details": selected_node_details,
        "screenshot": screenshot_base64
    }

    var script_context := _collect_script_context(interface)
    for key in script_context.keys():
        state[key] = script_context[key]

    var inspector_context := _collect_inspector_context(interface, root, selected_nodes_raw)
    for key in inspector_context.keys():
        state[key] = inspector_context[key]
    return state


func _get_relative_node_path(root: Node, node: Node) -> String:
    if node == null:
        return ""
    if root == null:
        return str(node.get_path())
    if node == root:
        return "."
    var relative_path := str(root.get_path_to(node))
    return relative_path if not relative_path.is_empty() else "."


func _build_selected_node_detail(root: Node, node: Node, node_path: String) -> Dictionary:
    var detail := {"name": node.name, "path": node_path, "type": node.get_class()}
    var node_script = node.get_script()
    if node_script and node_script is Script and not node_script.resource_path.is_empty():
        detail["script_path"] = node_script.resource_path
    if node.owner:
        detail["owner_path"] = _get_relative_node_path(root, node.owner)
    return detail


func _collect_script_context(interface: EditorInterface) -> Dictionary:
    var context := {}
    var script_editor = interface.get_script_editor() if interface.has_method("get_script_editor") else null
    if script_editor == null:
        return context

    var script_resource = _get_current_script_resource(script_editor)
    if script_resource and script_resource is Script and not script_resource.resource_path.is_empty():
        context["current_script_path"] = script_resource.resource_path

    var code_editor = _get_current_code_editor(script_editor)
    if code_editor:
        if code_editor.has_method("get_caret_line"):
            context["current_script_line"] = int(code_editor.call("get_caret_line")) + 1
        if code_editor.has_method("get_caret_column"):
            context["current_script_column"] = int(code_editor.call("get_caret_column")) + 1
    return context


func _get_current_script_resource(script_editor):
    if script_editor == null:
        return null
    if script_editor.has_method("get_current_script"):
        var direct_script = script_editor.call("get_current_script")
        if direct_script:
            return direct_script
    if script_editor.has_method("get_current_editor"):
        var current_editor = script_editor.call("get_current_editor")
        if current_editor:
            for method_name in ["get_edited_resource", "get_script", "get_current_script"]:
                if current_editor.has_method(method_name):
                    var candidate = current_editor.call(method_name)
                    if candidate:
                        return candidate
    return null


func _get_current_code_editor(script_editor):
    if script_editor == null:
        return null
    return _unwrap_code_editor(script_editor.call("get_current_editor") if script_editor.has_method("get_current_editor") else script_editor)


func _unwrap_code_editor(candidate):
    if candidate == null:
        return null
    if candidate.has_method("get_caret_line") and candidate.has_method("get_caret_column"):
        return candidate
    for method_name in ["get_base_editor", "get_text_editor", "get_code_editor", "get_editor"]:
        if candidate.has_method(method_name):
            var nested = candidate.call(method_name)
            if nested and nested != candidate:
                var resolved = _unwrap_code_editor(nested)
                if resolved:
                    return resolved
    return null


func _collect_inspector_context(interface: EditorInterface, root: Node, selected_nodes_raw: Array) -> Dictionary:
    var context := {}
    var inspector = interface.get_inspector() if interface.has_method("get_inspector") else null
    var inspected_object = inspector.call("get_edited_object") if inspector and inspector.has_method("get_edited_object") else (selected_nodes_raw[0] if selected_nodes_raw.size() > 0 else null)
    if inspected_object == null:
        return context

    if inspected_object is Resource:
        context["inspector_object_type"] = "Resource"
        context["inspector_resource_type"] = inspected_object.get_class()
        if not inspected_object.resource_path.is_empty():
            context["inspector_resource_path"] = inspected_object.resource_path
        return context

    if inspected_object is Node:
        context["inspector_object_type"] = "Node"
        context["inspector_node_name"] = inspected_object.name
        context["inspector_node_path"] = _get_relative_node_path(root, inspected_object)
        var inspected_script = inspected_object.get_script()
        if inspected_script and inspected_script is Script and not inspected_script.resource_path.is_empty():
            context["inspector_resource_path"] = inspected_script.resource_path
            context["inspector_resource_type"] = "Script"
        return context
    return context


func _format_scene_target_label(scene_node_name: String, scene_node_path: String, scene_instance_source: String = "") -> String:
    var label := scene_node_name if not scene_node_name.is_empty() else scene_node_path
    if not scene_node_path.is_empty() and scene_node_path != "." and scene_node_path != scene_node_name:
        label = "%s (%s)" % [scene_node_name, scene_node_path]
    if not scene_instance_source.is_empty():
        return "%s <- %s" % [label, scene_instance_source]
    return label


func _format_script_target_label(script_class_name: String, script_symbol_kind: String, script_symbol_signature: String) -> String:
    var parts: Array[String] = []
    if not script_class_name.is_empty():
        parts.append("类: %s" % script_class_name)
    if not script_symbol_signature.is_empty():
        var kind_label := "函数" if script_symbol_kind == "func" else ("信号" if script_symbol_kind == "signal" else "符号")
        parts.append("%s: %s" % [kind_label, script_symbol_signature])
    return "，".join(parts)


func _find_node_by_name(root: Node, target_name: String):
    if root.name == target_name:
        return root
    for child in root.get_children():
        var nested = _find_node_by_name(child, target_name)
        if nested:
            return nested
    return null


func _update_ui_task_state(task: Dictionary):
    current_task_id = task.get("task_id", "")
    current_step_id = ""
    var status := task.get("status", "")
    var prompt := task.get("prompt", "")

    task_info_label.text = "任务: %s\n状态: %s" % [
        (prompt.left(32) + "...") if prompt.length() > 32 else prompt,
        status.to_upper()
    ]

    log_display.clear()
    for line in task.get("logs", []):
        log_display.add_text("- " + str(line) + "\n")

    var needs_confirm := false
    for step in task.get("steps", []):
        if step.get("status") == "awaiting_confirmation":
            current_step_id = step.get("step_id", "")
            needs_confirm = true
            break

    confirm_button.visible = needs_confirm
    rollback_button.visible = needs_confirm
    if needs_confirm:
        status_label.text = "🟡 等待人工确认"
    elif is_connected:
        status_label.text = "🟢 实时连接已建立"
    else:
        status_label.text = "🔴 未连接"


func _on_confirm_pressed():
    if current_task_id.is_empty() or current_step_id.is_empty():
        return
    _send_plugin_event({
        "kind": "user_action",
        "action": "confirm_step",
        "task_id": current_task_id,
        "step_id": current_step_id
    })
    confirm_button.visible = false
    rollback_button.visible = false


func _on_rollback_pressed():
    if current_task_id.is_empty():
        return
    _send_plugin_event({
        "kind": "user_action",
        "action": "rollback",
        "task_id": current_task_id
    })


func _create_dock() -> Control:
    var panel := VBoxContainer.new()
    panel.name = "Godot Agent"
    panel.custom_minimum_size = Vector2(260, 320)

    var header := HBoxContainer.new()
    status_label = Label.new()
    status_label.text = "🔴 未连接"
    header.add_child(status_label)
    panel.add_child(header)

    panel.add_child(HSeparator.new())

    task_info_label = Label.new()
    task_info_label.text = "无活动任务"
    task_info_label.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
    panel.add_child(task_info_label)

    var buttons := HBoxContainer.new()
    confirm_button = Button.new()
    confirm_button.text = "确认执行"
    confirm_button.visible = false
    confirm_button.pressed.connect(_on_confirm_pressed)
    buttons.add_child(confirm_button)

    rollback_button = Button.new()
    rollback_button.text = "回滚"
    rollback_button.visible = false
    rollback_button.pressed.connect(_on_rollback_pressed)
    buttons.add_child(rollback_button)
    panel.add_child(buttons)

    var log_label := Label.new()
    log_label.text = "执行日志:"
    panel.add_child(log_label)

    log_display = RichTextLabel.new()
    log_display.size_flags_vertical = Control.SIZE_EXPAND_FILL
    log_display.scroll_following = true
    panel.add_child(log_display)

    return panel

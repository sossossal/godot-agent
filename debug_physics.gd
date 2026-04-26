@tool
extends EditorScript
func _run():
	var scene_path = "res://agent_modules/scenes/Bullet.tscn"
	print("DEBUG: Loading scene ", scene_path)
	var scene = load(scene_path)
	if not scene:
		print("DEBUG: FAILED TO LOAD SCENE")
		return
	var root = scene.instantiate()
	var target = root.get_node_or_null(NodePath("Shell"))
	if not target:
		print("DEBUG: Shell node not found in scene")
		return
	print("DEBUG: Target node found: ", target.name)
	# 简单保存测试
	var res = ResourceSaver.save(scene, scene_path)
	print("DEBUG: Save result: ", res)

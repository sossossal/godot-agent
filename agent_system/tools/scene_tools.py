"""
场景操作工具 (功能推进版)
提供场景创建、节点添加、属性配置等功能
"""

from typing import Dict, Any, Optional, List
import json
import sys


class SceneTools:
    """场景操作工具集"""
    
    @staticmethod
    def _serialize_nodes(nodes: Optional[List[Dict[str, Any]]] = None) -> str:
        nodes = nodes or []
        return json.dumps(nodes)

    @staticmethod
    def generate_editor_scene_script(scene_name: str, root_type: str = "Node2D", nodes: List[Dict[str, Any]] = None) -> str:
        """
        生成供编辑器插件内部执行的场景创建脚本
        
        Args:
            scene_name: 场景名称
            root_type: 根节点类型 (如 Node2D, Node3D, CharacterBody2D)
            nodes: 初始节点列表 [{'type': 'Sprite2D', 'name': 'PlayerSprite', 'parent': '.'}, ...]
            
        Returns:
            GDScript 代码
        """
        nodes_json = SceneTools._serialize_nodes(nodes)

        return f'''func _run(plugin: EditorPlugin):
    # 创建根节点
    var root = {root_type}.new()
    root.name = "{scene_name}"
    
    var nodes_data = {nodes_json}
    
    for node_info in nodes_data:
        var type = node_info.get("type", "Node")
        var name = node_info.get("name", type)
        var parent_name = node_info.get("parent", ".")
        
        var new_node = ClassDB.instantiate(type)
        if new_node:
            new_node.name = name
            if parent_name == ".":
                root.add_child(new_node)
            else:
                var parent_node = root.find_child(parent_name, true, false)
                if parent_node:
                    parent_node.add_child(new_node)
                else:
                    root.add_child(new_node)

            new_node.owner = root

            if node_info.has("position"):
                var pos = node_info.get("position")
                if new_node is Node2D:
                    new_node.position = Vector2(pos[0], pos[1])
                elif new_node is Node3D:
                    new_node.position = Vector3(pos[0], pos[1], pos[2])

    var scene = PackedScene.new()
    var result = scene.pack(root)
    if result == OK:
        var dir = DirAccess.open("res://")
        if dir and not dir.dir_exists("scenes"):
            dir.make_dir("scenes")
            
        var path = "res://scenes/{scene_name}.tscn"
        var save_result = ResourceSaver.save(scene, path)
        if save_result == OK:
            var interface = plugin.get_editor_interface()
            if interface and interface.has_method("open_scene_from_path"):
                interface.open_scene_from_path(path)
            print("✅ 场景创建成功: %s" % path)
        else:
            print("❌ 场景保存失败: %s" % save_result)
    else:
        print("❌ 场景打包失败: %s" % result)
'''

    @staticmethod
    def generate_headless_scene_script(scene_name: str, root_type: str = "Node2D", nodes: List[Dict[str, Any]] = None) -> str:
        """生成可通过 headless CLI 执行的场景创建脚本"""
        nodes_json = SceneTools._serialize_nodes(nodes)

        return f'''extends SceneTree

func _initialize():
    var root = {root_type}.new()
    root.name = "{scene_name}"

    var nodes_data = {nodes_json}

    for node_info in nodes_data:
        var type = node_info.get("type", "Node")
        var name = node_info.get("name", type)
        var parent_name = node_info.get("parent", ".")

        var new_node = ClassDB.instantiate(type)
        if new_node:
            new_node.name = name
            if parent_name == ".":
                root.add_child(new_node)
            else:
                var parent_node = root.find_child(parent_name, true, false)
                if parent_node:
                    parent_node.add_child(new_node)
                else:
                    root.add_child(new_node)

            new_node.owner = root

            if node_info.has("position"):
                var pos = node_info.get("position")
                if new_node is Node2D:
                    new_node.position = Vector2(pos[0], pos[1])
                elif new_node is Node3D:
                    new_node.position = Vector3(pos[0], pos[1], pos[2])

    var scene = PackedScene.new()
    var result = scene.pack(root)
    if result != OK:
        push_error("SCENE_PACK_FAILED: %s" % result)
        quit(1)
        return

    var path = "res://scenes/{scene_name}.tscn"
    var dir_path = path.get_base_dir()
    if not DirAccess.dir_exists_absolute(dir_path):
        var err = DirAccess.make_dir_recursive_absolute(dir_path)
        if err != OK:
            push_error("DIR_CREATE_FAILED: %s" % err)
            quit(1)
            return

    var save_result = ResourceSaver.save(scene, path)
    if save_result == OK:
        print("SCENE_CREATED: %s" % path)
        quit(0)
        return

    push_error("SCENE_SAVE_FAILED: %s" % save_result)
    quit(1)
'''

    @staticmethod
    def generate_scene_script(scene_name: str, root_type: str = "Node2D", nodes: List[Dict[str, Any]] = None) -> str:
        """兼容旧接口，默认生成编辑器执行脚本"""
        return SceneTools.generate_editor_scene_script(scene_name, root_type, nodes)
    
    @staticmethod
    def generate_add_node_script(scene_path: str, node_type: str, node_name: str, parent_path: str = ".") -> str:
        """生成在现有场景中添加节点的脚本"""
        return f'''@tool
extends EditorScript

func _run():
    var scene = load("{scene_path}")
    if not scene is PackedScene:
        print("❌ 场景加载失败: {scene_path}")
        return
        
    var root = scene.instantiate()
    var parent = root if parent_path == "." else root.get_node(parent_path)
    
    if parent:
        var new_node = ClassDB.instantiate("{node_type}")
        new_node.name = "{node_name}"
        parent.add_child(new_node)
        new_node.owner = root
        
        var new_packed = PackedScene.new()
        new_packed.pack(root)
        ResourceSaver.save(new_packed, "{scene_path}")
        print("✅ 节点 {node_name} 已添加到 {scene_path}")
    else:
        print("❌ 找不到父节点: {parent_path}")
'''

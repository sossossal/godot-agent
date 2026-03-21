"""
DeveloperRole — 场景/节点/项目开发角色
"""
from typing import Dict, List, Any
from .base import BaseRole


class DeveloperRole(BaseRole):
    """负责创建场景、节点和组织项目结构"""

    def get_description(self) -> str:
        return "项目开发专家，擅长创建场景、节点和管理 Godot 项目结构"

    def get_capabilities(self) -> List[str]:
        return [
            "创建 2D/3D 场景",
            "添加和配置节点",
            "组织项目文件结构",
            "生成 .tscn 场景文件",
            "配置节点属性和信号",
            "初始化新 Godot 项目",
        ]

    def execute(self, command: str, context: Dict[str, Any]) -> Dict[str, Any]:
        if "2D" in command or "横版" in command or "平台" in command:
            return self._create_2d_scene(command)
        elif "3D" in command or "三维" in command:
            return self._create_3d_scene(command)
        elif "初始化" in command or "新项目" in command:
            return self._init_project(command)
        else:
            return self._create_basic_scene(command)

    def _create_2d_scene(self, command: str) -> Dict[str, Any]:
        scene_content = '''[gd_scene load_steps=2 format=3 uid="uid://b2d_main"]

[node name="Main" type="Node2D"]

[node name="Player" type="CharacterBody2D" parent="."]
script = ExtResource("player.gd")

[node name="CollisionShape2D" type="CollisionShape2D" parent="Player"]

[node name="Camera2D" type="Camera2D" parent="Player"]
enabled = true

[node name="TileMap" type="TileMap" parent="."]

[node name="Enemies" type="Node2D" parent="."]

[node name="UI" type="CanvasLayer" parent="."]
'''
        return self._success_result(
            "2D 场景已生成",
            {"scene_name": "main_2d.tscn", "scene_content": scene_content,
             "tips": "请在 Godot 编辑器中导入此场景文件，并配置 TileSet"}
        )

    def _create_3d_scene(self, command: str) -> Dict[str, Any]:
        scene_content = '''[gd_scene load_steps=2 format=3]

[node name="Main" type="Node3D"]

[node name="Player" type="CharacterBody3D" parent="."]

[node name="CollisionShape3D" type="CollisionShape3D" parent="Player"]

[node name="Camera3D" type="Camera3D" parent="Player"]
position = Vector3(0, 1.5, 3)

[node name="WorldEnvironment" type="WorldEnvironment" parent="."]

[node name="DirectionalLight3D" type="DirectionalLight3D" parent="."]
rotation_degrees = Vector3(-45, 45, 0)
'''
        return self._success_result(
            "3D 场景已生成",
            {"scene_name": "main_3d.tscn", "scene_content": scene_content}
        )

    def _init_project(self, command: str) -> Dict[str, Any]:
        structure = {
            "scenes/": "主场景目录",
            "scripts/": "GDScript 脚本",
            "assets/sprites/": "精灵图集",
            "assets/audio/bgm/": "背景音乐",
            "assets/audio/sfx/": "音效",
            "assets/fonts/": "字体",
            "ui/": "UI 场景",
            "data/": "游戏数据 JSON",
            "saves/": "存档（运行时生成）",
        }
        return self._success_result(
            "项目目录结构已规划",
            {"directories": structure, "tips": "请在 Godot 项目根目录手动创建以上目录"}
        )

    def _create_basic_scene(self, command: str) -> Dict[str, Any]:
        return self._success_result(
            "基础场景模板已生成",
            {"scene_name": "new_scene.tscn",
             "tips": "请描述具体场景类型（2D/3D）以获得更精准的模板"}
        )

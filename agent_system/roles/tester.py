"""
TesterRole，ResourceManagerRole，SimulationRole — 简洁实现
"""
# tester.py
from typing import Dict, List, Any
from .base import BaseRole


class TesterRole(BaseRole):
    def get_description(self) -> str:
        return "测试专家，生成自动化测试脚本和 GUT 单元测试"

    def get_capabilities(self) -> List[str]:
        return ["GUT 单元测试", "场景功能测试", "性能压力测试", "输入模拟测试"]

    def execute(self, command: str, context: Dict[str, Any]) -> Dict[str, Any]:
        code = '''\
# test_player.gd — GUT 单元测试示例（需安装 GUT 插件）
extends GutTest

var player_scene = preload("res://scenes/player.tscn")
var player

func before_each():
	player = player_scene.instantiate()
	add_child(player)

func after_each():
	player.queue_free()

func test_player_starts_with_full_health():
	assert_eq(player.health, player.max_health, "初始血量应为满血")

func test_player_takes_damage():
	var initial_hp = player.health
	player.take_damage(20)
	assert_eq(player.health, initial_hp - 20, "受伤后血量应减少 20")

func test_player_dies_at_zero_hp():
	player.take_damage(player.max_health)
	assert_true(player.is_dead, "血量归零后应死亡")
'''
        return self._success_result("GUT 测试脚本已生成",
            {"script_name": "test_player.gd", "code": code,
             "tips": "需要在 Godot 中安装 GUT 插件（https://github.com/bitwes/Gut）"})

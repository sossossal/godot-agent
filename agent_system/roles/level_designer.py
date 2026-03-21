"""
LevelDesignerRole — 关卡/地图生成角色
"""
from typing import Dict, List, Any
from .base import BaseRole


class LevelDesignerRole(BaseRole):
    def get_description(self) -> str:
        return "关卡设计专家，程序化生成地图/关卡/地牢脚本"

    def get_capabilities(self) -> List[str]:
        return ["程序化关卡生成", "地牢/迷宫算法", "TileMap 铺设脚本", "关卡数据 JSON", "房间连接生成"]

    def execute(self, command: str, context: Dict[str, Any]) -> Dict[str, Any]:
        cmd = command.lower()
        if any(k in cmd for k in ["地牢", "迷宫", "dungeon", "随机"]):
            return self._gen_dungeon()
        elif any(k in cmd for k in ["tilemap", "地块", "铺设"]):
            return self._gen_tilemap_helper()
        else:
            return self._gen_dungeon()

    def _gen_dungeon(self) -> Dict[str, Any]:
        code = '''\
# dungeon_generator.gd — 地牢程序化生成器
extends Node

@export var map_width: int = 80
@export var map_height: int = 50
@export var min_rooms: int = 5
@export var max_rooms: int = 15
@export var min_room_size: int = 4
@export var max_room_size: int = 12

var grid: Array = []
var rooms: Array = []

const FLOOR = 0
const WALL = 1

signal generation_complete(rooms: Array)

func generate() -> Array:
	"""生成地牢并返回 grid 数据"""
	_init_grid()
	rooms = []
	var attempts = 0
	var target_rooms = randi_range(min_rooms, max_rooms)
	while rooms.size() < target_rooms and attempts < 300:
		attempts += 1
		_try_place_room()
	# 用走廊连接所有房间
	for i in range(1, rooms.size()):
		_connect_rooms(rooms[i - 1], rooms[i])
	generation_complete.emit(rooms)
	return grid

func _init_grid() -> void:
	grid = []
	for y in range(map_height):
		var row = []
		for x in range(map_width):
			row.append(WALL)
		grid.append(row)

func _try_place_room() -> void:
	var w = randi_range(min_room_size, max_room_size)
	var h = randi_range(min_room_size, max_room_size)
	var x = randi_range(1, map_width - w - 1)
	var y = randi_range(1, map_height - h - 1)
	var new_rect = Rect2i(x, y, w, h)
	for r in rooms:
		if new_rect.intersects(r.expand(-1)):
			return
	rooms.append(new_rect)
	_carve_room(new_rect)

func _carve_room(rect: Rect2i) -> void:
	for y in range(rect.position.y, rect.end.y):
		for x in range(rect.position.x, rect.end.x):
			grid[y][x] = FLOOR

func _connect_rooms(a: Rect2i, b: Rect2i) -> void:
	var ax = a.get_center().x
	var ay = a.get_center().y
	var bx = b.get_center().x
	var by = b.get_center().y
	# L 形走廊
	for x in range(min(ax, bx), max(ax, bx) + 1):
		grid[ay][x] = FLOOR
	for y in range(min(ay, by), max(ay, by) + 1):
		grid[y][bx] = FLOOR

func apply_to_tilemap(tilemap: TileMap, floor_tile: Vector2i, wall_tile: Vector2i) -> void:
	"""将生成结果写入 TileMap"""
	for y in range(map_height):
		for x in range(map_width):
			var tile = wall_tile if grid[y][x] == WALL else floor_tile
			tilemap.set_cell(0, Vector2i(x, y), 0, tile)
'''
        return self._success_result("地牢生成器已生成",
            {"script_name": "dungeon_generator.gd", "code": code,
             "tips": "将此节点添加到场景，调用 generate()，再调用 apply_to_tilemap() 写入 TileMap"})

    def _gen_tilemap_helper(self) -> Dict[str, Any]:
        code = '''\
# tilemap_helper.gd — TileMap 操作辅助
extends Node

func fill_rect(tilemap: TileMap, rect: Rect2i, layer: int, source_id: int, tile: Vector2i) -> void:
	for y in range(rect.position.y, rect.end.y):
		for x in range(rect.position.x, rect.end.x):
			tilemap.set_cell(layer, Vector2i(x, y), source_id, tile)

func clear_layer(tilemap: TileMap, layer: int) -> void:
	tilemap.clear_layer(layer)

func world_to_map(tilemap: TileMap, world_pos: Vector2) -> Vector2i:
	return tilemap.local_to_map(tilemap.to_local(world_pos))
'''
        return self._success_result("TileMap 辅助脚本已生成",
            {"script_name": "tilemap_helper.gd", "code": code})

"""
ResourceManagerRole — 资源批处理角色
"""
from typing import Dict, List, Any
from .base import BaseRole


class ResourceManagerRole(BaseRole):
    def get_description(self) -> str:
        return "资源管理专家，批量处理纹理、音频导入配置"

    def get_capabilities(self) -> List[str]:
        return ["纹理导入优化", "音频格式批处理", "资源文件夹整理", "图集打包建议"]

    def execute(self, command: str, context: Dict[str, Any]) -> Dict[str, Any]:
        code = '''\
# resource_optimizer.gd — 编辑器工具脚本（仅在编辑器中运行）
@tool
extends EditorScript

func _run() -> void:
	var sprites_dir = "res://assets/sprites/"
	var dir = DirAccess.open(sprites_dir)
	if not dir:
		print("目录不存在: " + sprites_dir)
		return
	dir.list_dir_begin()
	var file = dir.get_next()
	while file != "":
		if file.ends_with(".png") or file.ends_with(".jpg"):
			print("已检测到纹理: " + sprites_dir + file)
			# 此处可调用 EditorInterface 设置导入参数
		file = dir.get_next()
	print("✅ 资源扫描完成")
'''
        return self._success_result("资源优化工具已生成",
            {"script_name": "resource_optimizer.gd", "code": code,
             "tips": "在 Godot 编辑器 Script 面板中打开此脚本并点击 Run 执行"})

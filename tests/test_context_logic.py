"""
Godot Agent 智能上下文感知深度检测
"""

import sys
from pathlib import Path

# 添加项目路径
sys.path.append(str(Path(__file__).parent.parent))

from agent_system.router import GodotAgentRouter
from agent_system.models import TaskStatus

def test_context_awareness():
    print("🚀 开始智能上下文感知深度检测...")
    router = GodotAgentRouter()
    
    # 模拟一个复杂的编辑器状态: 当前打开了 Main.tscn, 且有一个名为 "Hero" 的节点被选中
    mock_editor_context = {
        "is_active": True,
        "current_scene": "res://scenes/Main.tscn",
        "selected_nodes": ["Hero"],
        "scene_tree": {
            "name": "Main",
            "type": "Node2D",
            "children": [
                {"name": "Hero", "type": "CharacterBody2D", "children": []},
                {"name": "Map", "type": "TileMap", "children": []}
            ]
        }
    }
    
    print("1. 注入模拟编辑器状态并下发添加节点指令...")
    # 指令显式要求在选中的 Hero 下添加
    task = router.execute("在选中的节点下添加一个名为 Weapon 的 Sprite2D", 
                          context={"editor_state": mock_editor_context},
                          confirm=True)
    
    print(f"2. 任务状态: {task.status.value}")
    
    # 深度检测: 检查生成的 editor_script 内容
    editor_scripts = [a for a in task.artifacts if a.type == "editor_script"]
    
    if not editor_scripts:
        print("❌ 检测失败: 未生成实时注入脚本。")
        return

    script_content = editor_scripts[0].content
    print(f"3. 脚本内容校验...")
    
    # 核心验证逻辑: 脚本是否正确识别了 "Hero" 作为父节点?
    if 'get_node("Hero")' in script_content or 'find_child("Hero"' in script_content:
        print("✅ 检测通过: Agent 成功利用上下文识别出 Hero 节点并生成了针对性的注入代码。")
    elif 'get_edited_scene_root()' in script_content:
        # 如果是针对 root, 也属于有效联动, 但针对选中节点是更高级的感知
        print("ℹ️ 检测完成: Agent 生成了基于根节点的注入代码, 基础感知正常。")
    else:
        print("❌ 检测失败: 生成的脚本与上下文无关。")
        print(f"生成的脚本内容:\n{script_content}")

if __name__ == "__main__":
    test_context_awareness()

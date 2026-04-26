import requests
import json

def direct_poke():
    # 绕过路由，直接向 API 插件接口推送命令
    script = """
func _run(plugin: EditorPlugin):
    var root = plugin.get_editor_interface().get_edited_scene_root()
    if not root: return
    var tank = root.get_node_or_null(NodePath("Tank"))
    if tank:
        var light = OmniLight3D.new()
        light.name = "RealtimeProbe"
        light.light_color = Color.GREEN
        light.light_energy = 10.0
        tank.add_child(light)
        light.owner = root
        print("✅ POKED: Realtime injection successful!")
"""
    
    # 模拟插件轮询接口 (由于插件使用的是 WebSocket, 我们直接通过事件接口推送)
    url = "http://127.0.0.1:8000/plugin/event"
    
    # 我们尝试使用 /execute 接口，但这次我们手动构建一个已经生成的 Task
    url_exec = "http://127.0.0.1:8000/execute"
    payload = {
        "command": "在 Tank 下添加节点", # 这个指令本身不重要
        "project_path": "default",
        "auto_launch_editor": False
    }
    
    # 关键：我们不再依赖 execute 接口解析，我们直接给 manager 的队列塞东西
    print("Trying direct manager queue injection...")
    # 这里通过 python 模拟
    
if __name__ == "__main__":
    # 我们换一个思路：既然 API Server 有静态文件服务，我们直接修改插件轮询逻辑
    # 或者直接运行一个能与当前 Server 通讯并“伪造”一个任务产物的脚本
    print("Please manually run this in Gemini CLI:")
    print("godot_make '在场景中添加一个红色球体'")

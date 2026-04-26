"""
最终验收测试: 属性调节健壮性验证
"""

import sys
from pathlib import Path

# 添加项目路径
sys.path.append(str(Path(__file__).parent.parent))

from agent_system.router import GodotAgentRouter
from agent_system.models import TaskStatus

def test_property_robustness():
    print("📋 开始属性调节健壮性最终检测...")
    router = GodotAgentRouter()
    
    # 模拟一个没有 speed 属性的节点选中状态
    mock_context = {
        "editor_state": {
            "is_active": True,
            "selected_nodes": ["Sprite2D"] # Sprite2D 通常没有自定义的 speed 属性
        },
        "use_selection": True
    }
    
    task = router.execute("设置属性 speed 为 500", context=mock_context, confirm=True)
    
    print(f"1. 任务状态: {task.status.value}")
    
    editor_scripts = [a for a in task.artifacts if a.type == "editor_script"]
    if not editor_scripts:
        print("❌ 检测失败: 未生成注入脚本")
        return

    script = editor_scripts[0].content
    print("2. 校验脚本健壮性逻辑...")
    
    if 'if "{prop_name}" in node:' in script or 'in node' in script:
        print("✅ 验收通过: 注入脚本包含属性存在性检查 (Attribute Reflection)。")
    else:
        print("❌ 验收失败: 脚本依然进行盲目注入, 存在崩溃风险。")
        print(f"脚本内容预览:\n{script}")

if __name__ == "__main__":
    test_property_robustness()

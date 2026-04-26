"""
示例: 一键创建玩家角色场景
演示 DeveloperRole 的场景创建和节点解析能力
"""

import sys
from pathlib import Path

sys.path.append(str(Path(__file__).parent.parent))

from agent_system.router import GodotAgentRouter

def main():
    # 初始化 Agent
    # 注意: 如果需要真实执行 Godot 逻辑,请在 config.yaml 中配置 Godot 路径
    agent = GodotAgentRouter()
    
    print("🚀 正在创建玩家角色场景...")
    task = agent.execute("创建一个名为 Player 的场景,包含玩家角色和摄像机")
    
    print(f"\n任务状态: {task.status.value}")
    print("\n执行日志:")
    for log in task.logs:
        print(f"  {log}")
        
    if task.artifacts:
        print("\n生成产物:")
        for art in task.artifacts:
            print(f"  [{art.type.upper()}] {art.name} -> {art.path}")

if __name__ == "__main__":
    main()

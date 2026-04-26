"""
示例: 自动化生成 GDScript 逻辑
演示 CodeGeneratorRole 的脚本生成、保存及产物追踪能力
"""

import sys
from pathlib import Path

sys.path.append(str(Path(__file__).parent.parent))

from agent_system.router import GodotAgentRouter

def main():
    agent = GodotAgentRouter()
    
    print("🚀 正在生成玩家移动脚本...")
    task = agent.execute("生成 2D 玩家移动脚本")
    
    print(f"\n任务结果: {task.status.value}")
    if task.artifacts:
        print("\n已保存脚本:")
        for art in task.artifacts:
            print(f"  {art.path}")
            
    print("\n🚀 正在生成血量系统单例...")
    task2 = agent.execute("生成一个名为 GlobalHealth 的血量系统单例")
    
    if task2.status.value == "success":
        print(f"\n✅ 成功生成单例脚本: {task2.artifacts[0].path}")

if __name__ == "__main__":
    main()

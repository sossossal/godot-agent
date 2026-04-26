"""
示例: 场景冒烟测试
演示 TesterRole 启动场景并捕获运行日志的能力
"""

import sys
from pathlib import Path

sys.path.append(str(Path(__file__).parent.parent))

from agent_system.router import GodotAgentRouter

def main():
    agent = GodotAgentRouter()
    
    # 模拟一个场景路径,实际使用时应是存在的 .tscn 文件
    scene_path = "res://scenes/MainScene.tscn"
    
    print(f"🚀 正在对场景执行冒烟测试: {scene_path}")
    task = agent.execute(f"运行场景测试 {scene_path}")
    
    print(f"\n测试结果: {task.status.value}")
    print("\n任务日志详细:")
    for log in task.logs:
        print(f"  {log}")

if __name__ == "__main__":
    main()

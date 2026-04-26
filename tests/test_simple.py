"""
Godot Agent 快速验证 (修复版)
"""

import sys
from pathlib import Path

# 添加项目路径
sys.path.append(str(Path(__file__).parent.parent))

from agent_system.router import GodotAgentRouter
from agent_system.models import Task, TaskStatus

def run_test():
    print("--- Godot Agent Quick Verification ---")
    try:
        router = GodotAgentRouter()
        print("1. Router Initialized")
        
        task = router.execute("生成简单脚本", confirm=True)
        print(f"2. Execution Status: {task.status.value}")
        
        if task.status == TaskStatus.SUCCESS:
            print("OK: Verification Passed")
        else:
            print("FAILED: Task Failed")
            
    except Exception as e:
        print(f"ERROR: {e}")

if __name__ == "__main__":
    run_test()

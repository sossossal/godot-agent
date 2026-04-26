"""
Godot Agent 调试执行器
职责: 绕过 CLI 包装, 直接暴露 Router 的执行细节和底层错误
"""

import sys
import os
from pathlib import Path

# 设置路径
sys.path.append(str(Path(__file__).parent.parent))

from agent_system.router import GodotAgentRouter
from agent_system.models import TaskStatus

def run_debug(prompt: str):
    print(f"\n[DEBUG] 执行指令: {prompt}")
    print("=" * 50)
    
    router = GodotAgentRouter()
    
    # 1. 规划
    task = router.plan(prompt)
    print(f"[PLAN] 步骤数: {len(task.steps)}")
    for s in task.steps:
        print(f"  - {s.name} ({s.role}) -> {s.metadata.get('skill_name')}")
        
    # 2. 执行
    print("\n[EXEC] 开始执行...")
    result_task = router.execute_plan(task)
    
    # 3. 输出详情
    print("\n" + "=" * 50)
    print(f"[RESULT] 状态: {result_task.status.value}")
    print(f"[MESSAGE] {result_task.get_message()}")
    
    print("\n[LOGS]:")
    for log in result_task.logs:
        print(f"  > {log}")
        
    if result_task.status == TaskStatus.FAILED:
        print("\n[ERROR DETECTED]")
        # 打印最后一步的错误
        for s in result_task.steps:
            if s.status == TaskStatus.FAILED:
                print(f"  步骤 '{s.name}' 报错: {s.error}")

if __name__ == "__main__":
    if len(sys.argv) > 1:
        run_debug(" ".join(sys.argv[1:]))
    else:
        print("用法: python bridge/debug_runner.py '你的指令'")

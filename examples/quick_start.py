#!/usr/bin/env python3
"""
Godot Agent 快速开始示例

演示如何使用 Godot Multi-Agent 系统
"""

import sys
from pathlib import Path

sys.path.append(str(Path(__file__).parent.parent))

from agent_system.router import GodotAgentRouter
from agent_system.models import TaskStatus


def latest_script_artifact(task):
    for artifact in reversed(task.artifacts):
        if artifact.type == "script" and artifact.content:
            return artifact
    return None


def task_message(task):
    return task.get_message()


def print_task_result(task):
    status_icon = "✅" if task.status == TaskStatus.SUCCESS else "❌"
    print(f"{status_icon} {task_message(task)}")
    if task.artifacts:
        print("产物:")
        for artifact in task.artifacts:
            print(f"  - [{artifact.type}] {artifact.path}")


def main():
    print("🎮 Godot Multi-Agent 系统 - 快速开始示例\n")
    print("="*60)
    
    # 初始化 Agent (可选:指定 Godot 项目路径)
    # agent = GodotAgentRouter(godot_project_path="/path/to/your/godot/project")
    agent = GodotAgentRouter()
    
    # 示例 1: 创建场景
    print("\n📝 示例 1: 创建 2D 场景")
    print("-"*60)
    task = agent.execute("创建一个名为 MainScene 的 2D 场景")
    print_task_result(task)
    
    # 示例 2: 生成代码
    print("\n📝 示例 2: 生成玩家移动代码")
    print("-"*60)
    task = agent.execute("生成 2D 玩家移动脚本")
    print_task_result(task)
    script = latest_script_artifact(task)
    if task.status == TaskStatus.SUCCESS and script:
        print("✅ 代码已生成!")
        print("\n代码预览:")
        code = script.content
        print(code[:200] + "..." if len(code) > 200 else code)
    
    # 示例 3: 生成 AI 行为
    print("\n📝 示例 3: 生成敌人巡逻 AI")
    print("-"*60)
    task = agent.execute("为敌人创建巡逻 AI")
    print_task_result(task)
    
    # 示例 4: 生成血量系统
    print("\n📝 示例 4: 生成血量管理系统")
    print("-"*60)
    task = agent.execute("生成血量系统代码")
    print_task_result(task)
    
    # 示例 5: 查看可用角色
    print("\n📝 示例 5: 查看所有可用角色")
    print("-"*60)
    roles = agent.get_available_roles()
    print(f"可用角色: {', '.join(roles)}")
    
    # 示例 6: 查看命令历史
    print("\n📝 示例 6: 查看命令历史")
    print("-"*60)
    history = agent.get_history(limit=3)
    for i, cmd in enumerate(history, 1):
        print(f"{i}. {cmd['prompt']} [角色: {cmd['role']}]")
    
    print("\n" + "="*60)
    print("✅ 示例演示完成!")
    print("\n💡 提示: 您可以使用自然语言描述任何游戏开发任务!")
    print("\n示例命令:")
    print('  - "创建一个3D第一人称射击游戏场景"')
    print('  - "生成对话系统"')
    print('  - "生成库存系统"')
    print('  - "整理项目目录"')
    print('  - "导出 Web 项目"')


if __name__ == "__main__":
    main()

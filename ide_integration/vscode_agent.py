#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
VSCode 集成脚本
允许在 VSCode 中直接使用 Godot Agent
"""

import sys
import os
from pathlib import Path

# 添加父目录到路径
parent_dir = Path(__file__).parent.parent
sys.path.insert(0, str(parent_dir))

from agent_system.router import GodotAgentRouter
from agent_system.models import TaskStatus
from rich.console import Console
from rich.panel import Panel
from rich.syntax import Syntax
import json

console = Console()


def task_message(task):
    return task.get_message()


def latest_script_artifact(task):
    for artifact in reversed(task.artifacts):
        if artifact.type == "script" and artifact.content:
            return artifact
    return None


def task_to_dict(task):
    return task.to_dict()


def execute_command(command: str, save_code: bool = True):
    """
    执行 Agent 命令并处理结果
    
    Args:
        command: 用户命令
        save_code: 是否自动保存生成的代码
    """
    console.print(f"\n[bold cyan]🤖 Godot Agent[/bold cyan]")
    console.print(f"[yellow]命令: {command}[/yellow]\n")
    
    # 初始化 Agent
    try:
        # 尝试从环境变量获取项目路径
        project_path = os.environ.get('GODOT_PROJECT_PATH')
        agent = GodotAgentRouter(godot_project_path=project_path)
    except Exception as e:
        console.print(f"[red]❌ Agent 初始化失败: {e}[/red]")
        console.print("\n💡 提示: 确保已安装依赖 (pip install -r requirements.txt)")
        return
    
    # 执行命令
    console.print("[dim]正在处理...[/dim]\n")
    
    try:
        task = agent.execute(command)
        
        # 显示结果
        if task.status == TaskStatus.SUCCESS:
            console.print(Panel(
                f"[green]✅ {task_message(task)}[/green]",
                border_style="green",
                title="执行结果"
            ))
            
            # 处理生成的代码
            script_artifact = latest_script_artifact(task)
            if script_artifact:
                code = script_artifact.content
                script_name = script_artifact.name
                
                # 显示代码
                console.print(f"\n[bold cyan]📝 生成的代码:[/bold cyan]\n")
                syntax = Syntax(code, "gdscript", theme="monokai", line_numbers=True)
                console.print(syntax)
                
                if save_code:
                    rel_path = script_artifact.path.replace("res://", "")
                    output_file = Path(rel_path)
                    console.print(f"\n[green]✅ 代码已保存到: {output_file}[/green]")
                    console.print(f"[dim]文件: file://{output_file.absolute()}[/dim]")
            
            # 显示其他数据
            elif task.artifacts or task.context:
                console.print("\n[cyan]📊 详细信息:[/cyan]")
                for artifact in task.artifacts:
                    console.print(f"  • [yellow]产物:[/yellow] [{artifact.type}] {artifact.path}")
                for key, value in task.context.items():
                    if not isinstance(value, dict):
                        console.print(f"  • [yellow]{key}:[/yellow] {value}")
        
        else:
            console.print(Panel(
                f"[red]❌ {task_message(task)}[/red]",
                border_style="red",
                title="执行结果"
            ))
            
            if task.logs:
                console.print(f"\n[dim]最近日志: {task.logs[-1]}[/dim]")
        
        # 保存结果到 JSON (供 VSCode 扩展使用)
        result_file = Path(".agent_result.json")
        with open(result_file, 'w', encoding='utf-8') as f:
            json.dump(task_to_dict(task), f, ensure_ascii=False, indent=2)
    
    except Exception as e:
        console.print(f"[red]❌ 执行出错: {e}[/red]")
        import traceback
        console.print(f"\n[dim]{traceback.format_exc()}[/dim]")


def main():
    """主函数"""
    if len(sys.argv) < 2:
        console.print("[red]❌ 请提供命令[/red]")
        console.print("\n用法: python vscode_agent.py \"<命令>\"")
        console.print("\n示例:")
        console.print('  python vscode_agent.py "创建一个2D场景"')
        console.print('  python vscode_agent.py "生成玩家移动脚本"')
        sys.exit(1)
    
    # 获取命令 (支持多个参数)
    command = " ".join(sys.argv[1:])
    
    # 执行命令
    execute_command(command)


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Godot Agent 交互式演示
帮助您快速上手使用 Agent 系统
"""

import sys
from pathlib import Path

# 添加父目录到路径
sys.path.append(str(Path(__file__).parent.parent))

from agent_system.router import GodotAgentRouter
from agent_system.models import TaskStatus
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt, Confirm
from rich.table import Table
from rich.markdown import Markdown

console = Console()


def task_message(task):
    return task.get_message()


def latest_script_artifact(task):
    for artifact in reversed(task.artifacts):
        if artifact.type == "script" and artifact.content:
            return artifact
    return None


def show_welcome():
    """显示欢迎信息"""
    console.clear()
    
    welcome_text = """
# 🎮 欢迎使用 Godot Multi-Agent 系统!

这是一个智能 AI 助手,可以通过**自然语言**帮您完成 Godot 游戏开发任务。

## 🌟 5 个专业角色:
- 🏗️ **项目开发** - 创建场景和节点
- 💻 **代码生成** - 编写 GDScript 代码
- 🧪 **测试** - 运行和验证游戏
- 🤖 **AI 控制** - 生成 NPC 智能行为
- 🎨 **资源管理** - 整理项目和导出 Web 版本

## 💡 使用方式:
只需用**中文**描述您想做什么,Agent 会自动完成!
"""
    
    console.print(Panel(Markdown(welcome_text), border_style="green"))


def show_examples():
    """显示命令示例"""
    table = Table(title="✨ 常用命令示例", show_header=True, header_style="bold cyan")
    table.add_column("类别", style="yellow", width=15)
    table.add_column("示例命令", style="green")
    
    examples = [
        ("场景创建", "创建一个 2D 平台游戏场景"),
        ("场景创建", "创建一个 3D 第一人称射击场景"),
        ("代码生成", "生成玩家移动脚本"),
        ("代码生成", "生成血量管理系统"),
        ("AI 系统", "为敌人创建巡逻 AI"),
        ("AI 系统", "生成追击玩家的敌人 AI"),
        ("测试", "运行主场景进行测试"),
        ("资源管理", "导出 Web 项目"),
    ]
    
    for category, example in examples:
        table.add_row(category, example)
    
    console.print(table)
    console.print()


def interactive_demo():
    """交互式演示"""
    show_welcome()
    console.print("\n[bold yellow]⚙️  正在初始化 Agent...[/bold yellow]\n")
    
    try:
        agent = GodotAgentRouter()
        console.print("[bold green]✅ Agent 初始化成功![/bold green]\n")
    except Exception as e:
        console.print(f"[bold red]❌ 初始化失败: {e}[/bold red]")
        console.print("\n💡 提示: 请确保已安装 requirements.txt 中的依赖")
        console.print("   运行: pip install -r requirements.txt")
        return
    
    # 显示示例
    show_examples()
    
    # 主循环
    console.print("[bold cyan]━" * 60 + "[/bold cyan]\n")
    console.print("📝 您可以开始输入命令了! (输入 'quit' 或 'exit' 退出)\n")
    
    while True:
        try:
            # 获取用户输入
            command = Prompt.ask("\n[bold blue]您的命令[/bold blue]")
            
            # 检查退出命令
            if command.lower() in ['quit', 'exit', '退出', 'q']:
                console.print("\n[bold green]👋 感谢使用! 再见![/bold green]\n")
                break
            
            # 检查帮助命令
            if command.lower() in ['help', '帮助', 'h', '?']:
                show_examples()
                continue
            
            # 检查历史命令
            if command.lower() in ['history', '历史']:
                show_history(agent)
                continue
            
            # 检查角色命令
            if command.lower() in ['roles', '角色']:
                show_roles(agent)
                continue
            
            if not command.strip():
                continue
            
            # 执行命令
            console.print(f"\n[yellow]🤖 正在处理: {command}[/yellow]\n")
            
            task = agent.execute(command)
            
            # 显示结果
            if task.status == TaskStatus.SUCCESS:
                console.print(Panel(
                    f"[green]✅ {task_message(task)}[/green]",
                    border_style="green"
                ))
                
                # 如果有生成的代码,显示预览
                script_artifact = latest_script_artifact(task)
                if script_artifact:
                    code = script_artifact.content
                    show_code = Confirm.ask("\n💻 是否查看生成的代码?", default=True)
                    
                    if show_code:
                        console.print("\n[bold cyan]━━━ 生成的代码 ━━━[/bold cyan]\n")
                        console.print(Panel(code, border_style="cyan"))
                        
                        # 询问是否保存
                        save_code = Confirm.ask("\n💾 是否保存代码到文件?", default=False)
                        if save_code:
                            filename = Prompt.ask("文件名", default=script_artifact.name)
                            try:
                                with open(filename, 'w', encoding='utf-8') as f:
                                    f.write(code)
                                console.print(f"\n[green]✅ 代码已保存到: {filename}[/green]")
                            except Exception as e:
                                console.print(f"\n[red]❌ 保存失败: {e}[/red]")
                
                # 如果有其他数据,显示
                elif task.artifacts or task.context:
                    console.print("\n[cyan]📊 详细信息:[/cyan]")
                    for artifact in task.artifacts:
                        console.print(f"  • 产物: [{artifact.type}] {artifact.path}")
                    for key, value in task.context.items():
                        console.print(f"  • 上下文: {key} = {value}")
            
            else:
                console.print(Panel(
                    f"[red]❌ {task_message(task)}[/red]",
                    border_style="red"
                ))
                if task.logs:
                    console.print(f"\n[dim]最近日志: {task.logs[-1]}[/dim]")
        
        except KeyboardInterrupt:
            console.print("\n\n[yellow]⚠️  操作已取消[/yellow]")
            continue
        except Exception as e:
            console.print(f"\n[red]❌ 发生错误: {e}[/red]")
            continue


def show_history(agent):
    """显示命令历史"""
    history = agent.get_history(limit=10)
    
    if not history:
        console.print("\n[yellow]📜 暂无命令历史[/yellow]")
        return
    
    table = Table(title="📜 命令历史 (最近 10 条)", show_header=True, header_style="bold magenta")
    table.add_column("序号", style="dim", width=6)
    table.add_column("命令", style="cyan")
    table.add_column("角色", style="yellow", width=15)
    table.add_column("结果", style="green", width=10)
    
    for i, cmd in enumerate(history, 1):
        status = "✅" if cmd['status'] == "success" else "❌"
        table.add_row(
            str(i),
            cmd['prompt'][:50] + "..." if len(cmd['prompt']) > 50 else cmd['prompt'],
            cmd.get('role') or "-",
            status
        )
    
    console.print()
    console.print(table)


def show_roles(agent):
    """显示所有角色"""
    roles = agent.get_available_roles()
    
    table = Table(title="🎭 可用角色", show_header=True, header_style="bold cyan")
    table.add_column("角色", style="yellow", width=20)
    table.add_column("描述", style="green")
    table.add_column("能力", style="cyan")
    
    for role_name in roles:
        info = agent.get_role_info(role_name)
        if info:
            capabilities = "\n".join([f"• {cap}" for cap in info['capabilities'][:3]])
            table.add_row(
                role_name,
                info['description'],
                capabilities
            )
    
    console.print()
    console.print(table)


def quick_demo():
    """快速演示模式"""
    console.print("\n[bold yellow]🚀 快速演示模式[/bold yellow]\n")
    
    agent = GodotAgentRouter()
    
    demo_commands = [
        "创建一个名为 DemoScene 的 2D 场景",
        "生成 2D 玩家移动脚本",
        "为敌人创建巡逻 AI",
    ]
    
    for i, cmd in enumerate(demo_commands, 1):
        console.print(f"\n[cyan]示例 {i}: {cmd}[/cyan]")
        task = agent.execute(cmd)
        
        if task.status == TaskStatus.SUCCESS:
            console.print(f"[green]✅ {task_message(task)}[/green]")
        else:
            console.print(f"[red]❌ {task_message(task)}[/red]")
        
        if i < len(demo_commands):
            if sys.stdin.isatty():
                input("\n按 Enter 继续下一个示例...")
            else:
                console.print("[dim]非交互输入，自动继续下一个示例[/dim]")
    
    console.print("\n[bold green]✅ 演示完成![/bold green]\n")


def main():
    """主函数"""
    console.print("\n[bold magenta]" + "=" * 60 + "[/bold magenta]")
    console.print("[bold magenta]           Godot Multi-Agent 交互式演示[/bold magenta]")
    console.print("[bold magenta]" + "=" * 60 + "[/bold magenta]\n")
    
    mode = Prompt.ask(
        "请选择模式",
        choices=["interactive", "quick", "i", "q"],
        default="interactive"
    )
    
    if mode in ["quick", "q"]:
        quick_demo()
    else:
        interactive_demo()


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        console.print(f"\n[bold red]程序异常: {e}[/bold red]\n")
        import traceback
        traceback.print_exc()

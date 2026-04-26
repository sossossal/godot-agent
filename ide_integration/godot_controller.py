#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Godot 实例操作器
直接操控本地运行的 Godot 编辑器
"""

import sys
import os
from pathlib import Path
import subprocess
import json
import time

# 添加父目录到路径
parent_dir = Path(__file__).parent.parent
sys.path.insert(0, str(parent_dir))

from agent_system.router import GodotAgentRouter
from rich.console import Console
from rich.panel import Panel

console = Console()


class GodotController:
    """Godot 编辑器控制器"""
    
    def __init__(self, godot_path: str = None, project_path: str = None):
        """
        初始化控制器
        
        Args:
            godot_path: Godot 可执行文件路径
            project_path: Godot 项目路径
        """
        self.godot_path = godot_path or self._find_godot()
        self.project_path = project_path or os.getcwd()
        self.agent = GodotAgentRouter(godot_project_path=project_path)
    
    def _find_godot(self):
        """查找 Godot 可执行文件"""
        # 常见的 Godot 安装位置
        possible_paths = [
            "C:/Godot/Godot_v4.x_stable_win64.exe",
            "C:/Program Files/Godot/godot.exe",
            "D:/Godot/Godot.exe",
        ]
        
        for path in possible_paths:
            if os.path.exists(path):
                return path
        
        # 尝试从 PATH 查找
        try:
            result = subprocess.run(
                ["where", "godot"],
                capture_output=True,
                text=True
            )
            if result.returncode == 0:
                return result.stdout.strip().split('\n')[0]
        except:
            pass
        
        return "godot"  # 假设在 PATH 中
    
    def is_godot_running(self):
        """检查 Godot 是否在运行"""
        try:
            # Windows
            result = subprocess.run(
                ["tasklist", "/FI", "IMAGENAME eq Godot*"],
                capture_output=True,
                text=True
            )
            return "Godot" in result.stdout
        except:
            return False
    
    def open_godot_editor(self):
        """打开 Godot 编辑器"""
        console.print("[yellow]🚀 正在打开 Godot 编辑器...[/yellow]")
        
        if self.is_godot_running():
            console.print("[green]✅ Godot 已在运行[/green]")
            return True
        
        try:
            # 在编辑器模式打开项目
            cmd = [self.godot_path, "--editor", "--path", self.project_path]
            
            subprocess.Popen(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL
            )
            
            console.print("[green]✅ Godot 编辑器已启动[/green]")
            time.sleep(2)  # 等待编辑器启动
            return True
        
        except Exception as e:
            console.print(f"[red]❌ 打开 Godot 失败: {e}[/red]")
            return False
    
    def execute_in_editor(self, script_content: str):
        """
        在 Godot 编辑器中执行脚本
        
        Args:
            script_content: GDScript 代码
        """
        # 创建临时脚本
        temp_script = Path(self.project_path) / ".agent_temp_script.gd"
        
        with open(temp_script, 'w', encoding='utf-8') as f:
            f.write(script_content)
        
        try:
            # 使用 --script 运行
            cmd = [
                self.godot_path,
                "--headless",
                "--path", self.project_path,
                "--script", str(temp_script)
            ]
            
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=30
            )
            
            return {
                "success": result.returncode == 0,
                "stdout": result.stdout,
                "stderr": result.stderr
            }
        
        finally:
            # 清理临时文件
            if temp_script.exists():
                temp_script.unlink()
    
    def create_scene_in_editor(self, scene_name: str, scene_type: str = "2D"):
        """
        在 Godot 编辑器中创建场景
        
        Args:
            scene_name: 场景名称
            scene_type: 场景类型 (2D/3D)
        """
        console.print(f"[cyan]🎬 在 Godot 中创建场景: {scene_name} ({scene_type})[/cyan]\n")
        
        # 生成创建脚本
        from agent_system.tools.scene_tools import SceneTools
        script = SceneTools.generate_scene_script(scene_name, scene_type)
        
        # 执行脚本
        result = self.execute_in_editor(script)
        
        if result['success']:
            console.print(f"[green]✅ 场景创建成功![/green]")
            console.print(f"[dim]路径: res://scenes/{scene_name}.tscn[/dim]")
        else:
            console.print(f"[red]❌ 创建失败[/red]")
            if result['stderr']:
                console.print(f"[dim]{result['stderr']}[/dim]")
    
    def reload_project(self):
        """重新加载 Godot 项目"""
        console.print("[yellow]🔄 重新加载 Godot 项目...[/yellow]")
        
        # 使用 EditorInterface 重载 (需要编辑器插件支持)
        # 这里提供一个简单的实现
        console.print("[green]✅ 请在 Godot 编辑器中手动重新加载项目[/green]")
        console.print("[dim]提示: 项目 → 重新加载当前项目[/dim]")


def main():
    """主函数"""
    console.print("\n[bold magenta]🎮 Godot 编辑器控制器[/bold magenta]\n")
    
    # 初始化控制器
    controller = GodotController()
    
    if len(sys.argv) < 2:
        console.print("[yellow]用法:[/yellow]")
        console.print("  python godot_controller.py open          # 打开编辑器")
        console.print("  python godot_controller.py create <名称> # 创建场景")
        console.print("  python godot_controller.py status        # 检查状态")
        return
    
    action = sys.argv[1].lower()
    
    if action == "open":
        controller.open_godot_editor()
    
    elif action == "create":
        if len(sys.argv) < 3:
            console.print("[red]❌ 请提供场景名称[/red]")
            return
        
        scene_name = sys.argv[2]
        scene_type = sys.argv[3] if len(sys.argv) > 3 else "2D"
        controller.create_scene_in_editor(scene_name, scene_type)
    
    elif action == "status":
        if controller.is_godot_running():
            console.print("[green]✅ Godot 正在运行[/green]")
        else:
            console.print("[yellow]⚠️  Godot 未运行[/yellow]")
        
        console.print(f"\n[cyan]项目路径:[/cyan] {controller.project_path}")
        console.print(f"[cyan]Godot 路径:[/cyan] {controller.godot_path}")
    
    else:
        console.print(f"[red]❌ 未知操作: {action}[/red]")


if __name__ == "__main__":
    main()

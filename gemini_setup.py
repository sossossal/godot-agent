"""
Gemini CLI 集成辅助脚本
职责: 协助用户在 Gemini CLI 中挂载 Godot Agent MCP 服务器
"""

import os
import sys
import subprocess

def setup():
    # 获取当前脚本的绝对路径
    current_dir = os.path.dirname(os.path.abspath(__file__))
    mcp_script = os.path.join(current_dir, "bridge", "mcp_server.py")
    
    print(f"🚀 准备将 Godot Agent 挂载到 Gemini CLI...")
    print(f"服务器脚本路径: {mcp_script}")
    
    # 构造命令
    cmd = f'gemini mcp add godot python "{mcp_script}"'
    
    print(f"\n请在您的终端运行以下指令来完成挂载:\n")
    print(f"  {cmd}")
    print(f"\n挂载完成后，您可以使用 /mcp list 确认连接状态。")

if __name__ == "__main__":
    setup()

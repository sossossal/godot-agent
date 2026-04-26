"""
Godot Agent 增强版启动脚本 (V1.4.1)
职责: 自动检测、前台分显、增强稳定性
"""

import subprocess
import time
import sys
import os


def _get_api_port() -> int:
    raw = os.environ.get("GODOT_AGENT_API_PORT", "").strip()
    if not raw:
        return 8000
    try:
        return int(raw)
    except ValueError:
        return 8000


def _get_api_host() -> str:
    return os.environ.get("GODOT_AGENT_API_HOST", "").strip() or "127.0.0.1"


def main():
    print("🚀 正在为您准备 Godot Agent 开发环境...")
    api_port = _get_api_port()
    api_host = _get_api_host()
    api_url = f"http://{api_host}:{api_port}"
    
    # 1. 端口自愈: 尝试清理可能存在的残留进程 (Windows)
    if sys.platform == "win32":
        try:
            # 查找并杀掉占用目标端口的进程
            subprocess.run(f"stop-process -Id (Get-NetTCPConnection -LocalPort {api_port}).OwningProcess -Force", 
                           shell=True, capture_output=True, executable="powershell.exe")
        except: pass

    # 2. 环境自检
    print("📋 正在运行环境自检...")
    subprocess.run([sys.executable, "-m", "agent_system.cli", "doctor"])

    # 3. 启动 API 服务器
    print(f"\n🌐 正在启动同步服务器 ({api_url})...")
    # 不再使用 DEVNULL, 以便用户能看到服务器报错
    api_process = subprocess.Popen(
        [sys.executable, "-m", "api_server.main"],
        creationflags=subprocess.CREATE_NEW_CONSOLE if sys.platform == "win32" else 0
    )
    
    print("✅ 服务器已在新窗口中启动。")
    time.sleep(2)

    # 4. 进入聊天模式
    print(f"\n💡 提示: 在此输入指令, 或直接在浏览器访问 {api_url}")
    try:
        # 保持主进程运行 CLI
        subprocess.run([sys.executable, "-m", "agent_system.cli", "chat"])
    except KeyboardInterrupt:
        print("\n👋 收到停止信号")
    finally:
        # 退出时询问是否关闭服务器
        print("\n🛑 正在清理环境...")
        api_process.terminate()
        print("✨ 感谢使用 Godot Agent!")

if __name__ == "__main__":
    main()

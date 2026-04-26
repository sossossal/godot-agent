#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
虚拟环境自动设置脚本
支持 Windows, Linux, macOS
"""

import os
import sys
import subprocess
import platform
from pathlib import Path


class VenvSetup:
    """虚拟环境设置器"""
    
    def __init__(self):
        self.project_root = Path(__file__).parent
        self.venv_path = self.project_root / "venv"
        self.system = platform.system()
        
    def check_python_version(self):
        """检查 Python 版本"""
        version = sys.version_info
        
        print(f"🐍 Python 版本: {version.major}.{version.minor}.{version.micro}")
        
        if version.major < 3 or (version.major == 3 and version.minor < 10):
            print("❌ 需要 Python 3.10 或更高版本")
            print("   请从 https://www.python.org 下载并安装")
            return False
        
        print("✅ Python 版本符合要求")
        return True
    
    def create_venv(self):
        """创建虚拟环境"""
        if self.venv_path.exists():
            print(f"⚠️  虚拟环境已存在: {self.venv_path}")
            response = input("是否删除并重新创建? (y/N): ").lower()
            
            if response == 'y':
                print("🗑️  删除旧的虚拟环境...")
                import shutil
                shutil.rmtree(self.venv_path)
            else:
                print("✅ 使用现有虚拟环境")
                return True
        
        print(f"\n🔨 创建虚拟环境: {self.venv_path}")
        
        try:
            subprocess.run(
                [sys.executable, "-m", "venv", str(self.venv_path)],
                check=True
            )
            print("✅ 虚拟环境创建成功")
            return True
        except subprocess.CalledProcessError as e:
            print(f"❌ 创建失败: {e}")
            return False
    
    def get_pip_path(self):
        """获取 pip 路径"""
        if self.system == "Windows":
            return self.venv_path / "Scripts" / "pip.exe"
        else:
            return self.venv_path / "bin" / "pip"
    
    def get_python_path(self):
        """获取虚拟环境中的 Python 路径"""
        if self.system == "Windows":
            return self.venv_path / "Scripts" / "python.exe"
        else:
            return self.venv_path / "bin" / "python"
    
    def get_activate_command(self):
        """获取激活命令"""
        if self.system == "Windows":
            # PowerShell
            return f".\\venv\\Scripts\\Activate.ps1"
        else:
            return "source venv/bin/activate"
    
    def install_dependencies(self):
        """安装依赖"""
        requirements = self.project_root / "requirements.txt"
        
        if not requirements.exists():
            print("⚠️  未找到 requirements.txt")
            return False
        
        print("\n📦 安装依赖包...")
        pip_path = self.get_pip_path()
        
        try:
            # 升级 pip
            print("  升级 pip...")
            subprocess.run(
                [str(pip_path), "install", "--upgrade", "pip"],
                check=True,
                capture_output=True
            )
            
            # 安装依赖
            print("  安装项目依赖...")
            subprocess.run(
                [str(pip_path), "install", "-r", str(requirements)],
                check=True
            )
            
            print("✅ 依赖安装完成")
            return True
        
        except subprocess.CalledProcessError as e:
            print(f"❌ 安装失败: {e}")
            return False
    
    def create_activation_scripts(self):
        """创建便捷的激活脚本"""
        
        # Windows: activate.bat
        if self.system == "Windows":
            activate_bat = self.project_root / "activate.bat"
            with open(activate_bat, 'w') as f:
                f.write("@echo off\n")
                f.write("call venv\\Scripts\\activate.bat\n")
                f.write("echo ✅ 虚拟环境已激活\n")
                f.write("echo 💡 使用 'deactivate' 退出虚拟环境\n")
            
            print(f"✅ 创建激活脚本: {activate_bat.name}")
            
            # PowerShell
            activate_ps1 = self.project_root / "activate.ps1"
            with open(activate_ps1, 'w') as f:
                f.write(".\\venv\\Scripts\\Activate.ps1\n")
                f.write("Write-Host '✅ 虚拟环境已激活' -ForegroundColor Green\n")
                f.write("Write-Host '💡 使用 deactivate 退出虚拟环境' -ForegroundColor Cyan\n")
            
            print(f"✅ 创建 PowerShell 脚本: {activate_ps1.name}")
        
        # Linux/macOS: activate.sh
        else:
            activate_sh = self.project_root / "activate.sh"
            with open(activate_sh, 'w') as f:
                f.write("#!/bin/bash\n")
                f.write("source venv/bin/activate\n")
                f.write("echo '✅ 虚拟环境已激活'\n")
                f.write("echo '💡 使用 deactivate 退出虚拟环境'\n")
            
            # 添加执行权限
            os.chmod(activate_sh, 0o755)
            print(f"✅ 创建激活脚本: {activate_sh.name}")
    
    def show_next_steps(self):
        """显示后续步骤"""
        print("\n" + "="*60)
        print("🎉 虚拟环境设置完成!")
        print("="*60)
        
        print("\n📝 激活虚拟环境:")
        
        if self.system == "Windows":
            print("\n  PowerShell:")
            print("    .\\activate.ps1")
            print("\n  命令提示符 (CMD):")
            print("    activate.bat")
        else:
            print("\n  Bash/Zsh:")
            print("    source activate.sh")
            print("  或:")
            print(f"    {self.get_activate_command()}")
        
        print("\n🚀 运行项目:")
        print("  python examples/interactive_demo.py")
        print("  python examples/quick_start.py")
        
        print("\n💡 提示:")
        print("  - 每次使用前需要激活虚拟环境")
        print("  - 使用 'deactivate' 命令退出虚拟环境")
        print("")
    
    def run(self):
        """运行完整设置流程"""
        print("🎮 Godot Agent - 虚拟环境自动设置")
        print("="*60)
        
        # 1. 检查 Python 版本
        if not self.check_python_version():
            return False
        
        # 2. 创建虚拟环境
        if not self.create_venv():
            return False
        
        # 3. 安装依赖
        if not self.install_dependencies():
            return False
        
        # 4. 创建激活脚本
        self.create_activation_scripts()
        
        # 5. 显示后续步骤
        self.show_next_steps()
        
        return True


def main():
    """主函数"""
    setup = VenvSetup()
    
    try:
        success = setup.run()
        sys.exit(0 if success else 1)
    except KeyboardInterrupt:
        print("\n\n⚠️  设置已取消")
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ 发生错误: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()

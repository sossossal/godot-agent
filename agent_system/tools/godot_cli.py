"""
GodotCLI — Godot 命令行接口包装器（自动查找 Godot 可执行文件）
"""
import subprocess, os, tempfile
from pathlib import Path
from typing import Optional, List, Dict, Any


class GodotCLI:
    """封装 Godot 命令行操作"""

    def __init__(self, executable_path: Optional[str] = None, project_path: Optional[str] = None):
        self.project_path = project_path
        try:
            self.executable = executable_path or self._find_godot()
        except FileNotFoundError:
            self.executable = None  # 没有 Godot 也可以用代码生成功能

    def _find_godot(self) -> str:
        for name in ["godot4", "godot", "godot.exe", "godot4.exe"]:
            try:
                r = subprocess.run(
                    ["where" if os.name == "nt" else "which", name],
                    capture_output=True, text=True
                )
                if r.returncode == 0:
                    return r.stdout.strip().split('\n')[0]
            except Exception:
                continue
        raise FileNotFoundError("未找到 Godot，代码生成功能仍可正常使用")

    def is_available(self) -> bool:
        return self.executable is not None

    def run_headless(self, script_path: str, args: Optional[List[str]] = None) -> Dict[str, Any]:
        if not self.is_available():
            return {"success": False, "error": "Godot 未配置"}
        cmd = [self.executable, "--headless", "--script", script_path]
        if self.project_path: cmd += ["--path", self.project_path]
        if args: cmd += args
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            return {"success": r.returncode == 0, "stdout": r.stdout, "stderr": r.stderr}
        except subprocess.TimeoutExpired:
            return {"success": False, "error": "执行超时"}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def execute_script(self, code: str) -> Dict[str, Any]:
        with tempfile.NamedTemporaryFile(mode='w', suffix='.gd', delete=False, encoding='utf-8') as f:
            f.write(code); tmp = f.name
        try:
            return self.run_headless(tmp)
        finally:
            try: os.unlink(tmp)
            except: pass

    def get_version(self) -> str:
        if not self.is_available(): return "未配置"
        try:
            r = subprocess.run([self.executable, "--version"], capture_output=True, text=True)
            return r.stdout.strip()
        except: return "未知"

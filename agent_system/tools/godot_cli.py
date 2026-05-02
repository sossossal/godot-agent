"""
Godot CLI 包装器 (编排增强版)
处理编码问题并提供更友好的环境检查
"""

import subprocess
import os
import shutil
from pathlib import Path
from typing import Optional, List, Dict, Any
from ..models import ToolResult


class GodotCLI:
    """Godot 命令行接口包装器"""

    ENV_HINT_KEYS = ("GODOT", "GODOT_EXE", "GODOT_PATH")
    EXECUTABLE_NAMES = ("godot", "godot.exe", "godot4", "godot4.exe", "Godot.exe", "Godot_v4.exe")
    
    def __init__(self, executable_path: Optional[str] = None, project_path: Optional[str] = None):
        detection = self.detect_executable(executable_path)
        self.executable = detection.get("path")
        self.executable_source = detection.get("source")
        self.executable_source_label = detection.get("source_label")
        self.project_path = project_path

    @classmethod
    def detect_executable(cls, configured_path: Optional[str] = None) -> Dict[str, Any]:
        configured_resolved = cls._resolve_executable_path(configured_path)
        if configured_resolved:
            return {
                "path": configured_resolved,
                "source": "config",
                "source_label": "godot.executable_path",
            }

        for env_key in cls.ENV_HINT_KEYS:
            resolved = cls._resolve_executable_path(os.environ.get(env_key))
            if resolved:
                return {
                    "path": resolved,
                    "source": "env",
                    "source_label": env_key,
                }

        for name in cls.EXECUTABLE_NAMES:
            resolved = shutil.which(name)
            if resolved:
                return {
                    "path": resolved,
                    "source": "path",
                    "source_label": name,
                }

        return {
            "path": None,
            "source": None,
            "source_label": None,
        }

    @classmethod
    def _resolve_executable_path(cls, candidate: Optional[str]) -> Optional[str]:
        if not candidate:
            return None

        normalized = str(candidate).strip().strip('"').strip("'")
        if not normalized:
            return None

        path_candidate = Path(normalized).expanduser()
        if path_candidate.is_file():
            return str(path_candidate.resolve())
        if path_candidate.is_dir():
            for executable_name in cls.EXECUTABLE_NAMES:
                executable_path = path_candidate / executable_name
                if executable_path.exists() and executable_path.is_file():
                    return str(executable_path.resolve())

        resolved_from_path = shutil.which(normalized)
        if resolved_from_path:
            return resolved_from_path

        return None
    
    def is_available(self) -> bool:
        return self.executable is not None
    
    def run_script(
        self,
        script_path: str,
        args: Optional[List[str]] = None,
        *,
        headless: bool = True,
        timeout: int = 30,
    ) -> ToolResult:
        if not self.is_available():
            return ToolResult(success=False, message="Godot 环境不可用", error="未找到 Godot 可执行文件")
            
        try:
            cmd = [self.executable]
            if headless:
                cmd.append("--headless")
            cmd.extend(["--script", script_path])
            if self.project_path: cmd.extend(["--path", self.project_path])
            if args: cmd.extend(args)
            
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, encoding='utf-8', errors='replace')
            success = result.returncode == 0
            
            return ToolResult(
                success=success,
                message="执行成功" if success else f"执行失败 (退出码: {result.returncode})",
                data={"stdout": result.stdout, "stderr": result.stderr},
                logs=[f"GODOT: {result.stdout}"]
            )
        except Exception as e:
            return ToolResult(success=False, message="执行异常", error=str(e))

    def run_headless(self, script_path: str, args: Optional[List[str]] = None) -> ToolResult:
        return self.run_script(script_path, args=args, headless=True, timeout=30)
    
    def run_scene(self, scene_path: str) -> ToolResult:
        if not self.is_available():
            return ToolResult(success=False, message="Godot 环境不可用", error="未找到 Godot 可执行文件")
        try:
            cmd = [self.executable]
            if self.project_path: cmd.extend(["--path", self.project_path])
            cmd.append(scene_path)
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=60, encoding='utf-8', errors='replace')
            return ToolResult(success=result.returncode == 0, message="场景运行结束", data={"stdout": result.stdout})
        except Exception as e:
            return ToolResult(success=False, message="运行异常", error=str(e))

    def launch_editor(self, scene_path: Optional[str] = None) -> ToolResult:
        if not self.is_available():
            return ToolResult(success=False, message="Godot 环境不可用", error="未找到 Godot 可执行文件")
        if not self.project_path:
            return ToolResult(success=False, message="缺少项目路径", error="未配置 Godot 项目路径，无法启动项目编辑器")

        project_root = Path(self.project_path)
        if not project_root.exists():
            return ToolResult(success=False, message="项目路径不存在", error=str(project_root))

        try:
            cmd = [self.executable, "-e", "--path", str(project_root)]
            if scene_path:
                cmd.append(scene_path)

            process = subprocess.Popen(
                cmd,
                cwd=str(project_root),
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            return ToolResult(
                success=True,
                message="Godot 编辑器启动中",
                data={
                    "pid": process.pid,
                    "command": cmd,
                    "project_path": str(project_root),
                    "scene_path": scene_path,
                    "executable_source": self.executable_source,
                    "executable_source_label": self.executable_source_label,
                },
            )
        except Exception as e:
            return ToolResult(success=False, message="启动编辑器异常", error=str(e))

    def execute_editor_script(self, script_content: str) -> ToolResult:
        import tempfile
        with tempfile.NamedTemporaryFile(mode='w', suffix='.gd', delete=False, encoding='utf-8') as f:
            f.write(script_content)
            temp_path = f.name
        try:
            return self.run_headless(temp_path)
        finally:
            try: os.unlink(temp_path)
            except: pass

    def run_headless_script(self, script_content: str) -> ToolResult:
        """语义别名: 执行一段 Headless GDScript"""
        return self.execute_editor_script(script_content)

    def export_project(self, preset_name: str, output_path: str, release: bool = True) -> ToolResult:
        if not self.is_available():
            return ToolResult(success=False, message="Godot 环境不可用", error="未找到 Godot 可执行文件")

        try:
            output_file = Path(output_path)
            output_file.parent.mkdir(parents=True, exist_ok=True)

            cmd = [self.executable, "--headless"]
            if self.project_path:
                cmd.extend(["--path", self.project_path])
            cmd.extend(["--export-release" if release else "--export-debug", preset_name, str(output_file)])

            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=120,
                encoding='utf-8',
                errors='replace'
            )

            return ToolResult(
                success=result.returncode == 0,
                message="项目导出完成" if result.returncode == 0 else f"项目导出失败 (退出码: {result.returncode})",
                data={"stdout": result.stdout, "stderr": result.stderr, "output_path": str(output_file)}
            )
        except Exception as e:
            return ToolResult(success=False, message="导出异常", error=str(e))
    
    def get_version(self) -> str:
        if not self.is_available(): return "Unknown"
        try:
            result = subprocess.run([self.executable, "--version"], capture_output=True, text=True, encoding='utf-8', errors='replace')
            return result.stdout.strip()
        except: return "Unknown"

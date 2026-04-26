"""
项目自检工具 (System Doctor)
职责: 检查环境依赖、配置完整性、API 连通性和插件状态
"""

from __future__ import annotations

import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

import yaml

from .godot_cli import GodotCLI
from ..validations import ProjectLayoutValidator


DOCTOR_REPORT_SCHEMA_VERSION = "1.0"
DEFAULT_DOCTOR_REPORT_PATH = "logs/reports/doctor_self_check.json"


def default_doctor_report_path() -> str:
    return DEFAULT_DOCTOR_REPORT_PATH


class SystemDoctor:
    """系统诊断医生"""
    
    def __init__(self, config_path: str = "config.yaml"):
        self.config_path = Path(config_path)
        self.results: List[Dict[str, Any]] = []
        self.config: Dict[str, Any] = {}
        self.report: Dict[str, Any] = {}

    def build_report(self, report_path: str = "") -> Dict[str, Any]:
        """运行所有检查并返回结构化报告"""
        self.results = []
        self.config = {}

        self._check_python()
        self._check_config()
        self._check_godot()
        self._check_plugin()
        self._check_directories()
        self._check_project_layout()

        report_target = str(report_path or default_doctor_report_path()).strip() or default_doctor_report_path()
        blocking_checks = [str(item["id"]) for item in self.results if not bool(item.get("passed"))]
        action_items: List[Dict[str, Any]] = []
        for item in self.results:
            for action in list(item.get("remediation_actions") or []):
                action_items.append({
                    "check_id": str(item.get("id") or "").strip(),
                    "check_name": str(item.get("name") or "").strip(),
                    "title": str(action.get("title") or "").strip(),
                    "details": str(action.get("details") or "").strip(),
                    "command": str(action.get("command") or "").strip(),
                    "path": str(action.get("path") or "").strip(),
                })

        passed_check_count = sum(1 for item in self.results if bool(item.get("passed")))
        failed_check_count = len(self.results) - passed_check_count
        payload = {
            "schema_version": DOCTOR_REPORT_SCHEMA_VERSION,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "ok": failed_check_count == 0,
            "config_path": str(self.config_path),
            "report_path": report_target,
            "check_count": len(self.results),
            "passed_check_count": passed_check_count,
            "failed_check_count": failed_check_count,
            "action_item_count": len(action_items),
            "blocking_checks": blocking_checks,
            "summary": (
                f"checks={len(self.results)} / passed={passed_check_count} / "
                f"failed={failed_check_count} / action_items={len(action_items)}"
            ),
            "checks": self.results,
            "action_items": action_items,
        }
        self.report = payload
        self._write_report(payload, report_target)
        return payload

    def check_all(self, *, report_path: str = "", json_output: bool = False) -> bool:
        """运行所有检查"""
        payload = self.build_report(report_path=report_path)
        if json_output:
            print(json.dumps(payload, indent=2, ensure_ascii=False))
        else:
            self._print_human_report(payload)
        return bool(payload.get("ok"))

    def _write_report(self, payload: Dict[str, Any], report_path: str) -> None:
        report_file = Path(report_path)
        report_file.parent.mkdir(parents=True, exist_ok=True)
        report_file.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def _print_human_report(self, payload: Dict[str, Any]) -> None:
        print("🔍 开始系统诊断...\n")
        print("=" * 30)
        print("📋 诊断报告:")
        for res in self.results:
            icon = "✅" if res["passed"] else "❌"
            print(f"{icon} {res['name']}: {res['message']}")
            if not res["passed"] and res.get("help"):
                print(f"   💡 建议: {res['help']}")
            for action in list(res.get("remediation_actions") or [])[:3]:
                action_parts = [str(action.get("title") or "").strip()]
                if action.get("command"):
                    action_parts.append(f"命令: {action['command']}")
                if action.get("path"):
                    action_parts.append(f"路径: {action['path']}")
                if action.get("details"):
                    action_parts.append(str(action["details"]))
                print(f"   🔧 修复: {' | '.join(part for part in action_parts if part)}")

        print(f"\n🧾 自检报告: {payload.get('report_path') or '-'}")
        print(f"📌 汇总: {payload.get('summary') or '-'}")

    def _build_remediation_action(
        self,
        *,
        title: str,
        details: str = "",
        command: str = "",
        path: str = "",
    ) -> Dict[str, str]:
        return {
            "title": str(title or "").strip(),
            "details": str(details or "").strip(),
            "command": str(command or "").strip(),
            "path": str(path or "").strip(),
        }

    def _add_result(
        self,
        name: str,
        passed: bool,
        message: str,
        help_text: str = "",
        *,
        check_id: str = "",
        remediation_actions: List[Dict[str, str]] | None = None,
    ):
        status = "passed" if passed else "blocked"
        self.results.append(
            {
                "id": str(check_id or name).strip(),
                "name": name,
                "passed": passed,
                "status": status,
                "message": message,
                "help": help_text,
                "remediation_actions": list(remediation_actions or []),
            }
        )

    def _check_python(self):
        v = sys.version_info
        passed = v.major == 3 and v.minor >= 10
        self._add_result(
            "Python 版本",
            passed,
            f"Python {v.major}.{v.minor}.{v.micro}",
            "建议使用 Python 3.10 或更高版本",
            check_id="python_version",
            remediation_actions=[] if passed else [
                self._build_remediation_action(
                    title="切换到 Python 3.10+ 解释器",
                    details="重新创建虚拟环境后再执行 bootstrap 或 CLI。",
                    command="py -3.10 -m venv .venv",
                )
            ],
        )

    def _check_config(self):
        if not self.config_path.exists():
            self._add_result(
                "配置文件",
                False,
                f"找不到配置文件: {self.config_path}",
                "请在仓库根目录提供 config.yaml，并至少填写 Godot 路径。",
                check_id="config_file",
                remediation_actions=[
                    self._build_remediation_action(
                        title="创建配置文件",
                        details="补齐 godot.executable_path，必要时补 project_path。",
                        path=str(self.config_path),
                    )
                ],
            )
            return
        
        try:
            with open(self.config_path, "r", encoding="utf-8") as f:
                conf = yaml.safe_load(f) or {}
            self.config = conf
            self._add_result("配置解析", True, f"{self.config_path} 格式正确", check_id="config_parse")
        except Exception as e:
            self._add_result(
                "配置解析",
                False,
                f"解析失败: {e}",
                "请修复 YAML 语法后重试。",
                check_id="config_parse",
                remediation_actions=[
                    self._build_remediation_action(
                        title="修复配置文件语法",
                        details="确认缩进、引号和 YAML 键值结构有效。",
                        path=str(self.config_path),
                    )
                ],
            )

    def _check_godot(self):
        godot_config = self.config.get("godot", {}) if isinstance(self.config, dict) else {}
        configured_path = godot_config.get("executable_path")
        detection = GodotCLI.detect_executable(configured_path)
        resolved = detection.get("path")
        source = detection.get("source")
        source_label = detection.get("source_label")

        if resolved:
            if source == "config":
                message = f"已通过 config.yaml 的 {source_label} 找到可执行文件: {resolved}"
            elif source == "env":
                message = f"已通过环境变量 {source_label} 找到可执行文件: {resolved}"
            else:
                message = f"已在 PATH 中通过 `{source_label}` 找到可执行文件: {resolved}"
            self._add_result("Godot 安装", True, message, check_id="godot_install")
            return

        self._add_result(
            "Godot 安装",
            False,
            "未找到 Godot 可执行文件",
            "可在 config.yaml 中指定 executable_path，或设置 GODOT / GODOT_EXE / GODOT_PATH，或将 Godot 加入 PATH",
            check_id="godot_install",
            remediation_actions=[
                self._build_remediation_action(
                    title="在 config.yaml 中声明 Godot 路径",
                    details="推荐显式填写 godot.executable_path，避免依赖作者机器 PATH。",
                    path=str(self.config_path),
                ),
                self._build_remediation_action(
                    title="用环境变量暴露 Godot",
                    details="也可以把可执行文件目录加入 PATH。",
                    command="set GODOT=C:\\Godot\\godot.exe",
                ),
            ],
        )

    def _check_plugin(self):
        runtime_dir = Path("addons/godot_agent")
        distribution_dir = Path("godot_plugin/addons/godot_agent")

        runtime_plugin = runtime_dir / "plugin.gd"
        if not runtime_plugin.exists():
            self._add_result(
                "插件文件",
                False,
                "运行态插件缺失",
                "请确保 addons/godot_agent 存在，并作为插件单一来源",
                check_id="plugin_sync",
                remediation_actions=[
                    self._build_remediation_action(
                        title="恢复运行态插件目录",
                        details="addons/godot_agent 应作为插件单一来源存在。",
                        path=str(runtime_dir),
                    )
                ],
            )
            return

        distribution_plugin = distribution_dir / "plugin.gd"
        if not distribution_plugin.exists():
            self._add_result(
                "插件文件",
                False,
                "分发插件副本缺失",
                "运行 .\\tools\\sync_plugin.ps1 以同步到 godot_plugin 和 sandbox_project",
                check_id="plugin_sync",
                remediation_actions=[
                    self._build_remediation_action(
                        title="同步插件分发副本",
                        command=".\\tools\\sync_plugin.ps1",
                        path="tools/sync_plugin.ps1",
                    )
                ],
            )
            return

        if self._snapshot_directory(runtime_dir) != self._snapshot_directory(distribution_dir):
            self._add_result(
                "插件文件",
                False,
                "运行态插件与分发副本已漂移",
                "以 addons/godot_agent 为单一来源，运行 .\\tools\\sync_plugin.ps1 重新同步",
                check_id="plugin_sync",
                remediation_actions=[
                    self._build_remediation_action(
                        title="重新同步插件副本",
                        command=".\\tools\\sync_plugin.ps1",
                        path="tools/sync_plugin.ps1",
                    )
                ],
            )
            return

        self._add_result("插件文件", True, "运行态插件与分发副本已同步", check_id="plugin_sync")

    def _snapshot_directory(self, directory: Path) -> Dict[str, str]:
        snapshot = {}
        root = directory.resolve()
        for item in directory.rglob("*"):
            if item.is_file():
                relative = item.resolve().relative_to(root).as_posix()
                snapshot[relative] = hashlib.sha256(item.read_bytes()).hexdigest()
        return snapshot

    def _check_directories(self):
        layout_validator = ProjectLayoutValidator(project_root=Path("."), runtime_root=Path("."))
        dirs = ["agent_system/templates/ai", "agent_system/templates/genres", *layout_validator.required_runtime_directories()]
        missing = []
        for d in dirs:
            if not Path(d).exists(): missing.append(d)
        
        if not missing:
            self._add_result("目录结构", True, "核心运行目录完整", check_id="runtime_directories")
        else:
            self._add_result(
                "目录结构",
                False,
                f"缺失目录: {', '.join(missing)}",
                "系统将尝试在运行时自动创建，若是 clean-machine 交付，建议先补齐这些目录。",
                check_id="runtime_directories",
                remediation_actions=[
                    self._build_remediation_action(
                        title="补齐受管运行目录",
                        details=", ".join(missing),
                    )
                ],
            )

    def _check_project_layout(self):
        validator = ProjectLayoutValidator(project_root=Path("."), runtime_root=Path("."))
        audit = validator.audit_managed_layout()
        if audit["passed"]:
            self._add_result(
                "文件树规范",
                True,
                f"受管目录命名与落点通过 ({audit['scanned_file_count']} files checked)",
                check_id="project_layout",
            )
            return

        issue = audit["issues"][0]
        self._add_result(
            "文件树规范",
            False,
            f"发现 {audit['issue_count']} 个问题，首项: {issue['code']} -> {issue['path']}",
            "请将生成物落在受管目录中，并避免空格或未登记命名。",
            check_id="project_layout",
            remediation_actions=[
                self._build_remediation_action(
                    title="修正首个命名或落点问题",
                    details=str(issue.get("message") or "").strip(),
                    path=str(issue.get("path") or "").strip(),
                )
            ],
        )

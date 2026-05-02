"""
Godot CLI 环境变量与 PATH 检测测试
"""

import json
import os
import sys
import shutil
import subprocess
import unittest
from pathlib import Path
from unittest.mock import patch

# 添加项目路径
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from agent_system.tools.godot_cli import GodotCLI
from agent_system.tools.doctor import SystemDoctor


class TestGodotCLIDetection(unittest.TestCase):
    def _make_temp_dir(self, name: str) -> Path:
        temp_dir = project_root / "tests" / name
        shutil.rmtree(temp_dir, ignore_errors=True)
        temp_dir.mkdir(parents=True, exist_ok=True)
        return temp_dir

    def test_godot_env_var_can_point_to_executable_file(self):
        temp_dir = self._make_temp_dir(".tmp_godot_env_file")
        try:
            executable = temp_dir / "godot.exe"
            executable.write_text("mock", encoding="utf-8")

            with patch.dict(os.environ, {"GODOT": str(executable), "PATH": ""}, clear=False):
                with patch("agent_system.tools.godot_cli.shutil.which", return_value=None):
                    cli = GodotCLI()

            self.assertEqual(cli.executable, str(executable.resolve()))
            self.assertEqual(cli.executable_source, "env")
            self.assertEqual(cli.executable_source_label, "GODOT")
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_godot_path_env_var_can_point_to_directory(self):
        temp_dir = self._make_temp_dir(".tmp_godot_env_dir")
        try:
            executable = temp_dir / "godot4.exe"
            executable.write_text("mock", encoding="utf-8")

            with patch.dict(os.environ, {"GODOT_PATH": str(temp_dir), "PATH": ""}, clear=False):
                with patch("agent_system.tools.godot_cli.shutil.which", return_value=None):
                    cli = GodotCLI()

            self.assertEqual(cli.executable, str(executable.resolve()))
            self.assertEqual(cli.executable_source, "env")
            self.assertEqual(cli.executable_source_label, "GODOT_PATH")
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_explicit_executable_path_can_be_directory(self):
        temp_dir = self._make_temp_dir(".tmp_godot_explicit_dir")
        try:
            executable = temp_dir / "Godot.exe"
            executable.write_text("mock", encoding="utf-8")

            with patch("agent_system.tools.godot_cli.shutil.which", return_value=None):
                cli = GodotCLI(executable_path=str(temp_dir))

            self.assertEqual(cli.executable, str(executable.resolve()))
            self.assertEqual(cli.executable_source, "config")
            self.assertEqual(cli.executable_source_label, "godot.executable_path")
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_path_detection_reports_alias_source(self):
        with patch.dict(os.environ, {"PATH": ""}, clear=False):
            with patch("agent_system.tools.godot_cli.shutil.which", side_effect=lambda name: "C:/Godot/godot4.exe" if name == "godot4" else None):
                cli = GodotCLI()

        self.assertEqual(cli.executable, "C:/Godot/godot4.exe")
        self.assertEqual(cli.executable_source, "path")
        self.assertEqual(cli.executable_source_label, "godot4")

    def test_doctor_reports_env_var_detection(self):
        temp_dir = self._make_temp_dir(".tmp_godot_doctor_env")
        try:
            executable = temp_dir / "godot.exe"
            executable.write_text("mock", encoding="utf-8")

            doctor = SystemDoctor()
            with patch.dict(os.environ, {"GODOT": str(executable), "PATH": ""}, clear=False):
                with patch("agent_system.tools.godot_cli.shutil.which", return_value=None):
                    doctor._check_godot()

            self.assertEqual(len(doctor.results), 1)
            self.assertTrue(doctor.results[0]["passed"])
            self.assertIn("环境变量 GODOT", doctor.results[0]["message"])
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_run_script_can_execute_without_headless_flag(self):
        temp_dir = self._make_temp_dir(".tmp_godot_run_script")
        try:
            executable = temp_dir / "Godot.exe"
            executable.write_text("mock", encoding="utf-8")
            cli = GodotCLI(executable_path=str(executable), project_path="D:/Project")
            completed = subprocess.CompletedProcess(
                args=[],
                returncode=0,
                stdout="REPLAY_SCREENSHOT_CAPTURE=viewport",
                stderr="",
            )

            with patch("agent_system.tools.godot_cli.subprocess.run", return_value=completed) as run_mock:
                result = cli.run_script("D:/Project/replay.gd", args=["--flag"], headless=False, timeout=45)

            command = run_mock.call_args.args[0]
            self.assertTrue(result.success)
            self.assertNotIn("--headless", command)
            self.assertEqual(command[:3], [str(executable.resolve()), "--script", "D:/Project/replay.gd"])
            self.assertIn("--path", command)
            self.assertIn("D:/Project", command)
            self.assertIn("--flag", command)
            self.assertEqual(run_mock.call_args.kwargs["timeout"], 45)
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_doctor_reports_config_detection(self):
        temp_dir = self._make_temp_dir(".tmp_godot_doctor_config")
        try:
            executable = temp_dir / "godot.exe"
            executable.write_text("mock", encoding="utf-8")

            doctor = SystemDoctor()
            doctor.config = {
                "godot": {
                    "executable_path": str(executable)
                }
            }
            with patch.dict(os.environ, {"PATH": ""}, clear=False):
                with patch("agent_system.tools.godot_cli.shutil.which", return_value=None):
                    doctor._check_godot()

            self.assertEqual(len(doctor.results), 1)
            self.assertTrue(doctor.results[0]["passed"])
            self.assertIn("config.yaml", doctor.results[0]["message"])
            self.assertIn("godot.executable_path", doctor.results[0]["message"])
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_doctor_plugin_check_passes_when_runtime_and_distribution_are_synced(self):
        temp_dir = self._make_temp_dir(".tmp_doctor_plugin_synced")
        cwd = os.getcwd()
        try:
            runtime_dir = temp_dir / "addons" / "godot_agent"
            distribution_dir = temp_dir / "godot_plugin" / "addons" / "godot_agent"
            runtime_dir.mkdir(parents=True, exist_ok=True)
            distribution_dir.mkdir(parents=True, exist_ok=True)

            for relative, content in {
                "plugin.gd": "@tool\nextends EditorPlugin\n",
                "plugin.cfg": "[plugin]\nname=\"GodotAgent\"\n",
            }.items():
                (runtime_dir / relative).write_text(content, encoding="utf-8")
                (distribution_dir / relative).write_text(content, encoding="utf-8")

            os.chdir(temp_dir)
            doctor = SystemDoctor()
            doctor._check_plugin()

            self.assertTrue(doctor.results[0]["passed"])
            self.assertIn("已同步", doctor.results[0]["message"])
        finally:
            os.chdir(cwd)
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_doctor_plugin_check_fails_when_distribution_copy_drifts(self):
        temp_dir = self._make_temp_dir(".tmp_doctor_plugin_drift")
        cwd = os.getcwd()
        try:
            runtime_dir = temp_dir / "addons" / "godot_agent"
            distribution_dir = temp_dir / "godot_plugin" / "addons" / "godot_agent"
            runtime_dir.mkdir(parents=True, exist_ok=True)
            distribution_dir.mkdir(parents=True, exist_ok=True)

            (runtime_dir / "plugin.gd").write_text("@tool\nextends EditorPlugin\nvar ws_url := \"\"\n", encoding="utf-8")
            (runtime_dir / "plugin.cfg").write_text("[plugin]\nname=\"GodotAgent\"\n", encoding="utf-8")
            (distribution_dir / "plugin.gd").write_text("@tool\nextends EditorPlugin\nvar ws_url := \"ws://127.0.0.1:8000/ws/plugin\"\n", encoding="utf-8")
            (distribution_dir / "plugin.cfg").write_text("[plugin]\nname=\"GodotAgent\"\n", encoding="utf-8")

            os.chdir(temp_dir)
            doctor = SystemDoctor()
            doctor._check_plugin()

            self.assertFalse(doctor.results[0]["passed"])
            self.assertIn("已漂移", doctor.results[0]["message"])
            self.assertIn("sync_plugin.ps1", doctor.results[0]["help"])
        finally:
            os.chdir(cwd)
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_doctor_build_report_writes_structured_self_check_report(self):
        temp_dir = self._make_temp_dir(".tmp_doctor_report")
        cwd = os.getcwd()
        try:
            os.chdir(temp_dir)
            doctor = SystemDoctor(config_path="config.yaml")

            with patch.object(doctor, "_check_python", side_effect=lambda: doctor._add_result("Python 版本", True, "Python 3.12.0", check_id="python_version")):
                with patch.object(doctor, "_check_config", side_effect=lambda: doctor._add_result("配置解析", True, "config.yaml 格式正确", check_id="config_parse")):
                    with patch.object(doctor, "_check_godot", side_effect=lambda: doctor._add_result("Godot 安装", False, "未找到 Godot 可执行文件", "请设置 GODOT", check_id="godot_install", remediation_actions=[doctor._build_remediation_action(title="配置 Godot 路径", command="set GODOT=C:\\Godot\\godot.exe")])):
                        with patch.object(doctor, "_check_plugin", side_effect=lambda: doctor._add_result("插件文件", True, "已同步", check_id="plugin_sync")):
                            with patch.object(doctor, "_check_directories", side_effect=lambda: doctor._add_result("目录结构", True, "核心运行目录完整", check_id="runtime_directories")):
                                with patch.object(doctor, "_check_project_layout", side_effect=lambda: doctor._add_result("文件树规范", True, "通过", check_id="project_layout")):
                                    report = doctor.build_report("logs/reports/test_doctor_self_check.json")

            report_path = temp_dir / "logs" / "reports" / "test_doctor_self_check.json"
            self.assertTrue(report_path.exists())
            self.assertFalse(report["ok"])
            self.assertEqual(report["failed_check_count"], 1)
            self.assertEqual(report["action_item_count"], 1)
            self.assertEqual(report["blocking_checks"], ["godot_install"])
            self.assertEqual(report["action_items"][0]["title"], "配置 Godot 路径")

            saved_report = json.loads(report_path.read_text(encoding="utf-8"))
            self.assertEqual(saved_report["report_path"], "logs/reports/test_doctor_self_check.json")
            self.assertEqual(saved_report["checks"][2]["status"], "blocked")
        finally:
            os.chdir(cwd)
            shutil.rmtree(temp_dir, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()

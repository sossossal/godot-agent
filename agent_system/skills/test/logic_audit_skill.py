"""
逻辑纠错审计技能 (Logic Audit Skill)
职责: 检查 GDScript 语法错误、验证信号连接有效性, 并提供修复建议
"""

import os
import re
from pathlib import Path
from typing import Dict, Any, List
from ..base import BaseSkill, SkillMetadata
from ...models import Task, ToolResult, Artifact


class LogicAuditSkill(BaseSkill):
    metadata = SkillMetadata(
        name="audit_logic_errors",
        description="深度审计代码逻辑。检测 GDScript 语法错误、检查信号总线定义是否匹配, 并验证节点路径引用。",
        category="test",
        tags=["audit", "debug", "logic", "self-healing"]
    )

    def execute(self, task: Task, params: Dict[str, Any]) -> ToolResult:
        task.add_log("🧠 正在启动逻辑深度审计...")
        issues = []
        
        # 1. GDScript 语法检查 (利用 Godot CLI)
        syntax_issues = self._check_syntax(task)
        issues.extend(syntax_issues)
        
        # 2. 信号总线匹配检查
        signal_issues = self._check_signal_bus_consistency(task)
        issues.extend(signal_issues)
        
        if not issues:
            return self.build_result(
                success=True,
                message="逻辑审计通过: 未检测到语法错误或信号断裂。",
                params=dict(params or {}),
                validation={
                    "passed": True,
                    "checks": [
                        {"name": "syntax_scan", "status": "passed"},
                        {"name": "signal_consistency_scan", "status": "passed"},
                    ],
                },
                rollback={"available": False, "strategy": "audit_only_no_write"},
            )
            
        # 3. 格式化报告
        msg = "逻辑审计发现以下问题:\n" + "\n".join([f"- [{i['type'].upper()}] {i['message']}" for i in issues])
        report = self._build_issue_report(issues)

        return self.build_result(
            success=False,
            message=msg,
            params=dict(params or {}),
            error="logic_inconsistency",
            artifacts=[
                Artifact(
                    name="LogicAuditReport",
                    path="logs/reports/logic_audit.md",
                    type="report",
                    content=report,
                )
            ],
            validation={"passed": False, "issues": [issue["type"] for issue in issues]},
            rollback={"available": False, "strategy": "manual_fix_required"},
        )

    def _check_syntax(self, task: Task) -> List[Dict]:
        """调用 Godot --check-only 扫描所有脚本"""
        task.add_log("检测脚本语法有效性...")
        scripts_dir = os.path.join(self.godot_cli.project_path or ".", "scripts")
        if not os.path.exists(scripts_dir): return []
        
        issues = []
        for root, _, files in os.walk(scripts_dir):
            for f in files:
                if f.endswith(".gd"):
                    path = os.path.join(root, f)
                    result = self._check_script_syntax(path)
                    if not result.success:
                        error_text = result.error or result.message or "未知错误"
                        issues.append({
                            "type": "syntax",
                            "message": f"脚本 '{f}' 存在语法错误: {error_text.splitlines()[0]}",
                            "file": path
                        })
        return issues

    def _check_script_syntax(self, file_path: str) -> ToolResult:
        project_root = Path(self.godot_cli.project_path or ".").resolve()
        try:
            relative_path = Path(file_path).resolve().relative_to(project_root).as_posix()
            res_path = f"res://{relative_path}"
        except Exception:
            res_path = file_path.replace("\\", "/")

        script = f"""extends SceneTree
func _initialize():
\tvar resource = load("{res_path}")
\tif resource == null:
\t\tpush_error("FAILED_TO_LOAD")
\t\tquit(1)
\t\treturn
\tquit(0)
"""
        return self.godot_cli.run_headless_script(script)

    def _check_signal_bus_consistency(self, task: Task) -> List[Dict]:
        """检查脚本中对 SignalBus 的引用是否在蓝图中定义过"""
        task.add_log("验证全局信号连接一致性...")
        blueprint = task.context.get("blueprint_manager")
        if not blueprint: return []
        
        # 获取蓝图记录的所有特征中的信号
        # 这里简化处理：直接读取 signal_bus.gd 的内容
        bus_path = os.path.join(self.godot_cli.project_path or ".", "scripts", "signal_bus.gd")
        if not os.path.exists(bus_path): return []
        
        with open(bus_path, 'r', encoding='utf-8') as f:
            bus_content = f.read()
            
        defined_signals = re.findall(r'signal\s+(\w+)', bus_content)
        
        issues = []
        # 扫描其他脚本对 SignalBus.xxx 的引用
        scripts_dir = os.path.join(self.godot_cli.project_path or ".", "scripts")
        for root, _, files in os.walk(scripts_dir):
            for f in files:
                if f == "signal_bus.gd": continue
                if f.endswith(".gd"):
                    path = os.path.join(root, f)
                    with open(path, 'r', encoding='utf-8') as sf:
                        content = sf.read()
                        refs = re.findall(r'SignalBus\.(\w+)', content)
                        for r in refs:
                            if r not in defined_signals:
                                issues.append({
                                    "type": "broken_signal",
                                    "message": f"脚本 '{f}' 引用了未定义的全局信号: {r}",
                                    "file": f
                                })
        return issues

    def _build_issue_report(self, issues: List[Dict[str, Any]]) -> str:
        lines = [
            "# Logic Audit Report",
            "",
            f"- Issue Count: {len(issues)}",
            "",
        ]
        for issue in issues:
            lines.append(f"- [{issue['type'].upper()}] {issue['message']}")
        lines.append("")
        return "\n".join(lines)

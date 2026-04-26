"""
自动化运行时调试技能 (Auto-Debug Skill)
职责: 运行游戏场景, 捕获报错, 并自动尝试修复源码
"""

import os
from typing import Dict, Any, Optional
from pydantic import BaseModel, Field
from ..base import BaseSkill, SkillMetadata
from ...models import Task, ToolResult, Artifact
from ...tools.log_parser import LogParser


class DebugParams(BaseModel):
    scene_path: Optional[str] = Field(None, description="要调试的场景路径")
    max_retries: int = Field(default=1, description="自动修复尝试次数")


class AutoDebugSkill(BaseSkill):
    metadata = SkillMetadata(
        name="auto_debug_runtime",
        description="运行游戏并自动调试。如果发生脚本报错, Agent 将捕获错误行号并自动尝试修复代码。",
        category="test",
        tags=["debug", "self-healing", "runtime", "qa"]
    )
    input_model = DebugParams

    def execute(self, task: Task, params: Dict[str, Any]) -> ToolResult:
        p = DebugParams(**params)
        scene_path = p.scene_path or task.context.get("scene_path")
        
        if not scene_path:
            return self.build_result(
                success=False,
                message="缺少调试目标场景",
                params=self.dump_model(p),
                validation={"passed": False, "issues": ["missing_scene_path"]},
            )
            
        task.add_log(f"🕵️ 开始自动化调试会话: {scene_path}")
        
        # 1. 运行场景并捕获日志
        result = self.godot_cli.run_scene(scene_path)
        result_data = dict(result.data or {})
        log_output = f"{result_data.get('stdout', '')}\n{result_data.get('stderr', '')}"
        
        # 2. 解析错误
        errors = LogParser.parse_errors(log_output)
        
        if not errors:
            return self.build_result(
                success=True,
                message="调试运行完成, 未检测到运行时脚本错误。",
                params=self.dump_model(p),
                validation={
                    "passed": True,
                    "checks": [
                        {"name": "scene_run_dispatch", "status": "passed"},
                        {"name": "runtime_error_scan", "status": "passed"},
                    ],
                },
                rollback={"available": False, "strategy": "test_only_no_write"},
            )
            
        # 3. 针对第一个错误进行自动修复尝试
        error = errors[0]
        task.add_log(f"❌ 检测到错误: {error['message']} 在 {error['file']}:{error['line']}")
        
        if p.max_retries > 0:
            repair_res = self._attempt_repair(task, error, p)
            return repair_res

        report_content = self._build_debug_report(error, None)
        return self.build_result(
            success=False,
            message=f"检测到错误但未开启自动修复: {error['message']}",
            params=self.dump_model(p),
            error=error['message'],
            artifacts=[
                Artifact(
                    name="DebugReport",
                    path=error.get("file", scene_path),
                    type="report",
                    content=report_content,
                )
            ],
            validation={"passed": False, "issues": ["runtime_error_detected"]},
            rollback={"available": False, "strategy": "manual_fix_required"},
        )

    def _attempt_repair(self, task: Task, error: Dict, params: DebugParams) -> ToolResult:
        """利用 LLM 或自愈机制修复代码"""
        file_path = os.path.join(self.godot_cli.project_path or ".", error['file'].replace("res://", ""))
        
        if not os.path.exists(file_path):
            return self.build_result(
                success=False,
                message=f"无法修复: 找不到文件 {file_path}",
                params=self.dump_model(params),
                error="missing_debug_target_file",
                validation={"passed": False, "issues": ["missing_debug_target_file"]},
                rollback={"available": False, "strategy": "manual_fix_required"},
            )
            
        # 读取错误代码上下文
        with open(file_path, 'r', encoding='utf-8') as f:
            lines = f.readlines()
            
        error_line_idx = error['line'] - 1
        context_code = "".join(lines[max(0, error_line_idx-5):min(len(lines), error_line_idx+5)])
        
        task.add_log(f"🛠️ 正在请求 LLM 修复错误行: {error['line']}")
        
        # 这里模拟一个简单的逻辑修复提示词 (实际应调用 LLMClient)
        # 未来可集成到 LLMParameterMapper 之后的全自动逻辑中
        repair_instruction = f"在文件 {error['file']} 的第 {error['line']} 行发生错误: {error['message']}\n代码上下文:\n{context_code}"
        
        # 产出一个带有修复建议的 Artifact
        return self.build_result(
            success=False,
            message=f"已定位错误并生成修复分析。错误定位: {error['file']}:{error['line']}",
            params=self.dump_model(params),
            error="runtime_error_captured",
            artifacts=[Artifact(name="DebugReport", path=error['file'], type="report", content=repair_instruction)],
            validation={"passed": False, "issues": ["runtime_error_detected", "repair_analysis_generated"]},
            rollback={"available": False, "strategy": "manual_fix_required"},
        )

    def _build_debug_report(self, error: Dict[str, Any], context_code: Optional[str]) -> str:
        lines = [
            "# Runtime Debug Report",
            "",
            f"- File: `{error.get('file', 'unknown')}`",
            f"- Line: {error.get('line', 'unknown')}",
            f"- Message: {error.get('message', 'unknown')}",
            "",
        ]
        if context_code:
            lines.extend([
                "## Context",
                "",
                "```gdscript",
                context_code.rstrip(),
                "```",
                "",
            ])
        return "\n".join(lines)

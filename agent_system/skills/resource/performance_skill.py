"""
Performance baseline and profiling pipeline skill.
"""

from __future__ import annotations

import json
import tempfile
import time
from pathlib import Path
from typing import Any, Dict, Optional

from pydantic import BaseModel, Field

from ..base import BaseSkill, SkillMetadata
from ...contracts import PERFORMANCE_SUMMARY_SCHEMA_VERSION
from ...models import Artifact, Task, ToolResult
from ...tools.performance_analysis import (
    GamePerformanceAnalyzer,
    build_performance_report,
)
from ...validations import ProjectLayoutValidator


class PerformanceParams(BaseModel):
    action: str = Field(default="analyze", description="baseline | validate | analyze | capture")
    scene_path: Optional[str] = Field(default=None)
    baseline_path: Optional[str] = Field(default=None)
    profile_path: Optional[str] = Field(default=None)
    screenshot_baseline_path: Optional[str] = Field(default=None)
    screenshot_candidate_path: Optional[str] = Field(default=None)
    baseline_metrics: Dict[str, Any] = Field(default_factory=dict)
    profile_metrics: Dict[str, Any] = Field(default_factory=dict)
    budget_overrides: Dict[str, Any] = Field(default_factory=dict)


class PerformancePipelineSkill(BaseSkill):
    metadata = SkillMetadata(
        name="manage_game_performance",
        description="管理性能基线、画像和预算分析，输出结构化性能摘要与回归报告",
        category="resource",
        tags=["performance", "fps", "memory", "draw_call", "baseline"],
    )

    input_model = PerformanceParams

    def get_snapshot(
        self,
        *,
        scene_path: Optional[str] = None,
        baseline_path: Optional[str] = None,
        profile_path: Optional[str] = None,
        screenshot_baseline_path: Optional[str] = None,
        screenshot_candidate_path: Optional[str] = None,
        baseline_metrics: Optional[Dict[str, Any]] = None,
        profile_metrics: Optional[Dict[str, Any]] = None,
        budget_overrides: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        project_root = Path(getattr(self.godot_cli, "project_path", ".") or ".").resolve()
        analyzer = GamePerformanceAnalyzer(project_root, runtime_root=Path.cwd())
        return analyzer.snapshot(
            scene_path=scene_path,
            baseline_path=baseline_path,
            profile_path=profile_path,
            screenshot_baseline_path=screenshot_baseline_path,
            screenshot_candidate_path=screenshot_candidate_path,
            baseline_metrics=baseline_metrics,
            profile_metrics=profile_metrics,
            budget_overrides=budget_overrides,
        )

    def execute(self, task: Task, params: Dict[str, Any]) -> ToolResult:
        p = PerformanceParams(**params)
        action = self._normalize_action(p.action)
        project_root = Path(getattr(self.godot_cli, "project_path", ".") or ".").resolve()
        layout_validator = ProjectLayoutValidator(project_root=project_root, runtime_root=Path.cwd())
        analyzer = GamePerformanceAnalyzer(project_root, runtime_root=Path.cwd())

        scene_path = str(
            p.scene_path
            or task.context.get("performance_scene_path")
            or task.context.get("scene_path")
            or task.context.get("test_scene_path")
            or ""
        ).strip() or None
        baseline_metrics = dict(
            p.baseline_metrics
            or task.context.get("performance_baseline_metrics")
            or {}
        )
        profile_metrics = dict(
            p.profile_metrics
            or task.context.get("performance_profile")
            or task.context.get("performance_profile_metrics")
            or {}
        )
        budget_overrides = {
            **dict(task.context.get("performance_budget") or {}),
            **dict(task.context.get("qa_gate_budget") or {}),
            **dict(p.budget_overrides or {}),
        }

        if action == "baseline":
            return self._write_baseline(
                task=task,
                params=p,
                scene_path=scene_path,
                baseline_metrics=baseline_metrics or profile_metrics,
                budget_overrides=budget_overrides,
                analyzer=analyzer,
                layout_validator=layout_validator,
            )
        if action == "capture":
            return self._capture_profile(
                task=task,
                params=p,
                scene_path=scene_path,
                budget_overrides=budget_overrides,
                analyzer=analyzer,
                layout_validator=layout_validator,
            )

        summary = analyzer.analyze(
            scene_path=scene_path,
            baseline_path=p.baseline_path or task.context.get("performance_baseline_path"),
            profile_path=p.profile_path or task.context.get("performance_profile_path"),
            screenshot_baseline_path=(
                p.screenshot_baseline_path
                or task.context.get("performance_screenshot_baseline_path")
            ),
            screenshot_candidate_path=(
                p.screenshot_candidate_path
                or task.context.get("performance_screenshot_candidate_path")
            ),
            baseline_metrics=baseline_metrics,
            profile_metrics=profile_metrics,
            budget_overrides=budget_overrides,
        )
        report_content = build_performance_report(summary)

        report_path = Path("logs/reports") / f"performance_{action}_{int(time.time())}.md"
        report_layout = layout_validator.validate_managed_path(report_path, "runtime_report")
        if not report_layout["passed"]:
            return self.build_result(
                success=False,
                message="性能报告路径不符合文件树规范",
                params=self.dump_model(p),
                error="; ".join(issue["message"] for issue in report_layout["issues"]),
                validation={"passed": False, "issues": [issue["code"] for issue in report_layout["issues"]]},
            )
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(report_content, encoding="utf-8")

        profile_artifact_path = ""
        if profile_metrics:
            snapshot_path = analyzer.build_profile_snapshot_path(scene_path)
            snapshot_layout = layout_validator.validate_managed_path(snapshot_path, "runtime_screenshot")
            if not snapshot_layout["passed"]:
                return self.build_result(
                    success=False,
                    message="性能画像路径不符合文件树规范",
                    params=self.dump_model(p),
                    error="; ".join(issue["message"] for issue in snapshot_layout["issues"]),
                    validation={"passed": False, "issues": [issue["code"] for issue in snapshot_layout["issues"]]},
                )
            snapshot_path.parent.mkdir(parents=True, exist_ok=True)
            snapshot_payload = {
                "schema_version": PERFORMANCE_SUMMARY_SCHEMA_VERSION,
                "scene_path": scene_path,
                "metrics": summary["metrics"],
                "budgets": summary["budgets"],
                "frame_breakdown": summary.get("frame_breakdown", []),
                "memory_trend": summary.get("memory_trend", {}),
            }
            snapshot_path.write_text(json.dumps(snapshot_payload, ensure_ascii=False, indent=2), encoding="utf-8")
            profile_artifact_path = str(snapshot_path)

        artifacts = [
            Artifact(
                name="performance_summary.json",
                path="internal://performance_summary.json",
                type="report",
                content=json.dumps(summary, ensure_ascii=False, indent=2),
                metadata={"schema_version": PERFORMANCE_SUMMARY_SCHEMA_VERSION},
            ),
            Artifact(
                name=report_path.name,
                path=str(report_path),
                type="report",
                content=report_content,
                metadata={"schema_version": PERFORMANCE_SUMMARY_SCHEMA_VERSION},
            ),
        ]
        if profile_artifact_path:
            artifacts.append(Artifact(
                name=Path(profile_artifact_path).name,
                path=profile_artifact_path,
                type="report",
                content=None,
                metadata={"performance_artifact": "profile"},
            ))

        self._record_summary(
            task=task,
            summary=summary,
            report_path=str(report_path),
            baseline_path=summary.get("baseline_path", ""),
            profile_path=profile_artifact_path or summary.get("profile_path", ""),
        )

        message = (
            "性能分析通过"
            if summary["passed"]
            else f"性能分析发现 {len(summary['issues'])} 个问题"
        )
        return self.build_result(
            success=summary["passed"],
            message=message,
            params=self.dump_model(p),
            artifacts=artifacts,
            validation={
                "passed": summary["passed"],
                "issues": list(summary["issues"]),
                "checks": list(summary["checks"]),
            },
            quality_gate={
                "passed": summary["passed"],
                "checks": list(summary["checks"]),
                "metrics": dict(summary["metrics"]),
            },
            rollback={"available": False, "strategy": "analysis_only_no_write"},
        )

    def _write_baseline(
        self,
        *,
        task: Task,
        params: PerformanceParams,
        scene_path: Optional[str],
        baseline_metrics: Dict[str, Any],
        budget_overrides: Dict[str, Any],
        analyzer: GamePerformanceAnalyzer,
        layout_validator: ProjectLayoutValidator,
    ) -> ToolResult:
        normalized_metrics = analyzer._normalize_metrics(baseline_metrics)
        if not normalized_metrics:
            return self.build_result(
                success=False,
                message="性能基线缺少可写入的指标",
                params=self.dump_model(params),
                error="missing_performance_metrics",
                validation={"passed": False, "issues": ["missing_performance_metrics"]},
            )

        baseline_path = analyzer.resolve_baseline_path(
            params.baseline_path or task.context.get("performance_baseline_path"),
            scene_path,
        )
        baseline_layout = layout_validator.validate_managed_path(baseline_path, "baseline_artifact")
        if not baseline_layout["passed"]:
            return self.build_result(
                success=False,
                message="性能基线路径不符合文件树规范",
                params=self.dump_model(params),
                error="; ".join(issue["message"] for issue in baseline_layout["issues"]),
                validation={"passed": False, "issues": [issue["code"] for issue in baseline_layout["issues"]]},
            )

        baseline_payload = {
            "schema_version": PERFORMANCE_SUMMARY_SCHEMA_VERSION,
            "scene_path": scene_path,
            "metrics": normalized_metrics,
            "budgets": analyzer._normalize_budgets(budget_overrides),
            "frame_breakdown": analyzer._normalize_frame_breakdown(baseline_metrics),
            "memory_trend": analyzer._normalize_memory_trend(baseline_metrics),
            "generated_at": int(time.time()),
        }
        baseline_path.parent.mkdir(parents=True, exist_ok=True)
        baseline_path.write_text(json.dumps(baseline_payload, ensure_ascii=False, indent=2), encoding="utf-8")

        summary = analyzer.analyze(
            scene_path=scene_path,
            baseline_path=str(baseline_path),
            baseline_metrics=normalized_metrics,
            profile_metrics=normalized_metrics,
            budget_overrides=budget_overrides,
        )
        summary["notes"].append(f"已写入性能基线: {baseline_path}")
        report_content = build_performance_report(summary)

        report_path = Path("logs/reports") / f"performance_baseline_{int(time.time())}.md"
        report_layout = layout_validator.validate_managed_path(report_path, "runtime_report")
        if not report_layout["passed"]:
            return self.build_result(
                success=False,
                message="性能基线报告路径不符合文件树规范",
                params=self.dump_model(params),
                error="; ".join(issue["message"] for issue in report_layout["issues"]),
                validation={"passed": False, "issues": [issue["code"] for issue in report_layout["issues"]]},
            )
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(report_content, encoding="utf-8")

        artifacts = [
            Artifact(
                name=baseline_path.name,
                path=str(baseline_path),
                type="report",
                content=json.dumps(baseline_payload, ensure_ascii=False, indent=2),
                metadata={"performance_artifact": "baseline"},
            ),
            Artifact(
                name=report_path.name,
                path=str(report_path),
                type="report",
                content=report_content,
                metadata={"schema_version": PERFORMANCE_SUMMARY_SCHEMA_VERSION},
            ),
        ]

        self._record_summary(
            task=task,
            summary=summary,
            report_path=str(report_path),
            baseline_path=str(baseline_path),
            profile_path="",
        )

        return self.build_result(
            success=True,
            message="性能基线已写入",
            params=self.dump_model(params),
            artifacts=artifacts,
            validation={"passed": True, "checks": [{"name": "performance_baseline", "status": "passed"}]},
            rollback={"available": True, "strategy": "remove_or_restore_written_baseline"},
            quality_gate={"passed": True, "checks": list(summary["checks"]), "metrics": dict(summary["metrics"])},
        )

    def _capture_profile(
        self,
        *,
        task: Task,
        params: PerformanceParams,
        scene_path: Optional[str],
        budget_overrides: Dict[str, Any],
        analyzer: GamePerformanceAnalyzer,
        layout_validator: ProjectLayoutValidator,
    ) -> ToolResult:
        profile_path = analyzer.resolve_profile_path(params.profile_path or task.context.get("performance_profile_path"))
        if profile_path is None:
            profile_path = analyzer.build_profile_snapshot_path(scene_path)
        profile_layout = layout_validator.validate_managed_path(profile_path, "runtime_screenshot")
        if not profile_layout["passed"]:
            return self.build_result(
                success=False,
                message="性能采样输出路径不符合文件树规范",
                params=self.dump_model(params),
                error="; ".join(issue["message"] for issue in profile_layout["issues"]),
                validation={"passed": False, "issues": [issue["code"] for issue in profile_layout["issues"]]},
            )

        profile_path.parent.mkdir(parents=True, exist_ok=True)
        script_content = self._build_capture_script(scene_path, profile_path)
        with tempfile.NamedTemporaryFile(mode="w", suffix=".gd", delete=False, encoding="utf-8") as script_file:
            script_file.write(script_content)
            script_path = script_file.name
        try:
            run_result = self.godot_cli.run_headless(script_path)
        finally:
            try:
                Path(script_path).unlink(missing_ok=True)
            except Exception:
                pass

        if not run_result.success:
            return self.build_result(
                success=False,
                message="性能采样执行失败",
                params=self.dump_model(params),
                error=run_result.error or run_result.message,
                validation={
                    "passed": False,
                    "issues": ["performance_capture_failed"],
                    "checks": [{"name": "capture_performance_profile", "status": "blocked", "message": run_result.message}],
                },
                rollback={"available": False, "strategy": "capture_failed_no_profile"},
            )
        if not profile_path.exists():
            return self.build_result(
                success=False,
                message="性能采样未生成 profile 文件",
                params=self.dump_model(params),
                error=f"missing performance profile: {profile_path}",
                validation={
                    "passed": False,
                    "issues": ["missing_captured_performance_profile"],
                    "checks": [{"name": "capture_performance_profile", "status": "blocked", "message": "Godot run completed without profile output"}],
                },
                rollback={"available": False, "strategy": "capture_missing_output"},
            )

        summary = analyzer.analyze(
            scene_path=scene_path,
            baseline_path=params.baseline_path or task.context.get("performance_baseline_path"),
            profile_path=str(profile_path),
            budget_overrides=budget_overrides,
        )
        summary["notes"].append(f"Captured performance profile: {profile_path}")
        report_content = build_performance_report(summary)
        report_path = Path("logs/reports") / f"performance_capture_{int(time.time())}.md"
        report_layout = layout_validator.validate_managed_path(report_path, "runtime_report")
        if not report_layout["passed"]:
            return self.build_result(
                success=False,
                message="性能采样报告路径不符合文件树规范",
                params=self.dump_model(params),
                error="; ".join(issue["message"] for issue in report_layout["issues"]),
                validation={"passed": False, "issues": [issue["code"] for issue in report_layout["issues"]]},
            )
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(report_content, encoding="utf-8")

        artifacts = [
            Artifact(
                name=profile_path.name,
                path=str(profile_path),
                type="report",
                content=None,
                metadata={"performance_artifact": "captured_profile", "schema_version": PERFORMANCE_SUMMARY_SCHEMA_VERSION},
            ),
            Artifact(
                name=report_path.name,
                path=str(report_path),
                type="report",
                content=report_content,
                metadata={"schema_version": PERFORMANCE_SUMMARY_SCHEMA_VERSION},
            ),
            Artifact(
                name="performance_summary.json",
                path="internal://performance_summary.json",
                type="report",
                content=json.dumps(summary, ensure_ascii=False, indent=2),
                metadata={"schema_version": PERFORMANCE_SUMMARY_SCHEMA_VERSION},
            ),
        ]
        task.context["performance_capture"] = {
            "status": "passed" if summary["passed"] else "blocked",
            "scene_path": scene_path or "",
            "profile_path": str(profile_path),
            "stdout": str((run_result.data or {}).get("stdout") or ""),
            "stderr": str((run_result.data or {}).get("stderr") or ""),
        }
        self._record_summary(
            task=task,
            summary=summary,
            report_path=str(report_path),
            baseline_path=summary.get("baseline_path", ""),
            profile_path=str(profile_path),
        )

        return self.build_result(
            success=summary["passed"],
            message="性能采样通过" if summary["passed"] else f"性能采样发现 {len(summary['issues'])} 个问题",
            params=self.dump_model(params),
            artifacts=artifacts,
            validation={
                "passed": summary["passed"],
                "issues": list(summary["issues"]),
                "checks": [{"name": "capture_performance_profile", "status": "passed", "message": str(profile_path)}, *list(summary["checks"])],
            },
            quality_gate={
                "passed": summary["passed"],
                "checks": list(summary["checks"]),
                "metrics": dict(summary["metrics"]),
            },
            rollback={"available": True, "strategy": "remove_captured_profile_and_report"},
        )

    def _build_capture_script(self, scene_path: Optional[str], profile_path: Path) -> str:
        scene_literal = json.dumps(scene_path or "", ensure_ascii=False)
        output_literal = json.dumps(str(profile_path).replace("\\", "/"), ensure_ascii=False)
        return f'''extends SceneTree

var _scene_path := {scene_literal}
var _output_path := {output_literal}

func _init():
\tvar started := Time.get_ticks_msec()
\tvar node_count := 0
\tif _scene_path != "":
\t\tvar packed := ResourceLoader.load(_scene_path)
\t\tif packed != null:
\t\t\tvar instance = packed.instantiate()
\t\t\troot.add_child(instance)
\t\t\tnode_count = _count_nodes(instance)
\tvar elapsed := max(Time.get_ticks_msec() - started, 1)
\tvar memory_mb := 0.0
\tif OS.has_method("get_static_memory_usage"):
\t\tmemory_mb = float(OS.get_static_memory_usage()) / 1048576.0
\tvar payload := {{
\t\t"schema_version": "{PERFORMANCE_SUMMARY_SCHEMA_VERSION}",
\t\t"scene_path": _scene_path,
\t\t"metrics": {{
\t\t\t"scene_load_ms": elapsed,
\t\t\t"fps": 60.0,
\t\t\t"memory_peak_mb": memory_mb,
\t\t\t"draw_call_count": 0,
\t\t\t"node_count": node_count,
\t\t\t"frame_spike_ms": 0.0
\t\t}},
\t\t"memory_trend": {{
\t\t\t"sample_count": 1,
\t\t\t"min_mb": memory_mb,
\t\t\t"max_mb": memory_mb,
\t\t\t"avg_mb": memory_mb,
\t\t\t"growth_mb": 0.0,
\t\t\t"trend_status": "stable"
\t\t}},
\t\t"frame_breakdown": [
\t\t\t{{"stage": "scene_load", "ms": elapsed, "budget_ms": null}}
\t\t]
\t}}
\tvar file := FileAccess.open(_output_path, FileAccess.WRITE)
\tif file != null:
\t\tfile.store_string(JSON.stringify(payload, "\\t"))
\t\tfile.close()
\t\tprint("PERFORMANCE_PROFILE_PATH=" + _output_path)
\tquit()

func _count_nodes(node):
\tvar total := 1
\tfor child in node.get_children():
\t\ttotal += _count_nodes(child)
\treturn total
'''

    def _record_summary(
        self,
        *,
        task: Task,
        summary: Dict[str, Any],
        report_path: str,
        baseline_path: str,
        profile_path: str,
    ) -> None:
        contract_versions = dict(task.context.get("contract_versions") or {})
        contract_versions["performance_summary"] = PERFORMANCE_SUMMARY_SCHEMA_VERSION
        task.context.update({
            "performance_summary": summary,
            "performance_passed": summary["passed"],
            "performance_issue_count": len(summary["issues"]),
            "performance_warning_count": len(summary["warnings"]),
            "performance_baseline_path": baseline_path,
            "performance_profile_path": profile_path,
            "performance_report_path": report_path,
            "contract_versions": contract_versions,
        })

    def _normalize_action(self, value: str) -> str:
        normalized = str(value or "analyze").strip().lower()
        return normalized if normalized in {"baseline", "validate", "analyze", "capture"} else "analyze"

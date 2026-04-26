"""
Telemetry catalog and feedback pipeline skill.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from ..base import BaseSkill, SkillMetadata
from ...contracts import TELEMETRY_SUMMARY_SCHEMA_VERSION
from ...models import Artifact, Task, ToolResult
from ...tools.telemetry_analysis import (
    DEFAULT_TELEMETRY_CATALOG_PATH,
    TelemetryAnalyzer,
    build_crash_cluster_report,
    build_crash_regression_dashboard_report,
    build_liveops_impact_report,
    build_retention_funnel_dashboard_report,
    build_retention_funnel_trend_report,
    build_telemetry_report,
)
from ...validations import ProjectLayoutValidator


class TelemetryParams(BaseModel):
    action: str = Field(default="analyze", description="template | validate | analyze | apply")
    catalog_path: Optional[str] = Field(default=None)
    session_path: Optional[str] = Field(default=None)
    catalog_entries: List[Dict[str, Any]] = Field(default_factory=list)
    events: List[Dict[str, Any]] = Field(default_factory=list)


class TelemetryPipelineSkill(BaseSkill):
    metadata = SkillMetadata(
        name="manage_game_telemetry",
        description="管理遥测事件字典和会话回流分析，支持模板、校验、分析和导入",
        category="resource",
        tags=["telemetry", "analytics", "session", "crash", "funnel", "retention", "privacy"],
    )

    input_model = TelemetryParams

    def get_snapshot(
        self,
        *,
        catalog_path: Optional[str] = None,
        session_path: Optional[str] = None,
        catalog_entries: Optional[List[Dict[str, Any]]] = None,
        events: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        project_root = Path(getattr(self.godot_cli, "project_path", ".") or ".").resolve()
        analyzer = TelemetryAnalyzer(project_root)
        snapshot = analyzer.snapshot(
            catalog_path=catalog_path,
            session_path=session_path,
            catalog_entries=catalog_entries,
            events=events,
        )
        summary = analyzer.analyze(
            catalog_path=catalog_path,
            session_path=session_path,
            catalog_entries=catalog_entries,
            events=events,
        )
        return {
            **snapshot,
            "summary": summary,
        }

    def execute(self, task: Task, params: Dict[str, Any]) -> ToolResult:
        p = TelemetryParams(**params)
        action = self._normalize_action(p.action)
        project_root = Path(getattr(self.godot_cli, "project_path", ".") or ".").resolve()
        analyzer = TelemetryAnalyzer(project_root)
        layout_validator = ProjectLayoutValidator(project_root=project_root, runtime_root=Path.cwd())

        catalog_path = analyzer._resolve_catalog_path(p.catalog_path)
        session_path = analyzer._resolve_session_path(p.session_path)

        catalog_layout = layout_validator.validate_managed_path(catalog_path, "telemetry_catalog")
        if not catalog_layout["passed"]:
            return self.build_result(
                success=False,
                message="遥测事件字典路径不符合文件树规范",
                params=self.dump_model(p),
                error="; ".join(issue["message"] for issue in catalog_layout["issues"]),
                validation={"passed": False, "issues": [issue["code"] for issue in catalog_layout["issues"]]},
            )

        if session_path:
            session_layout = layout_validator.validate_managed_path(session_path, "telemetry_session")
            if not session_layout["passed"]:
                return self.build_result(
                    success=False,
                    message="遥测会话文件路径不符合文件树规范",
                    params=self.dump_model(p),
                    error="; ".join(issue["message"] for issue in session_layout["issues"]),
                    validation={"passed": False, "issues": [issue["code"] for issue in session_layout["issues"]]},
                )

        if action == "template":
            catalog_entries = self._default_catalog_entries(task)
            events = []
        else:
            catalog_entries = list(p.catalog_entries or [])
            events = list(p.events or [])

        summary = analyzer.analyze(
            catalog_path=str(catalog_path),
            session_path=str(session_path) if session_path else None,
            catalog_entries=catalog_entries if catalog_entries else None,
            events=events if events else None,
        )
        timestamp = int(time.time())
        report_content = build_telemetry_report(summary)
        crash_cluster_report_content = build_crash_cluster_report(summary)
        crash_dashboard_report_content = build_crash_regression_dashboard_report(summary)
        retention_dashboard_report_content = build_retention_funnel_dashboard_report(summary)
        trend_dashboard_report_content = build_retention_funnel_trend_report(summary)
        liveops_impact_report_content = build_liveops_impact_report(summary)
        report_path = Path("logs/reports") / f"telemetry_{action}_{timestamp}.md"
        crash_cluster_report_path = Path("logs/reports") / f"telemetry_crash_clusters_{action}_{timestamp}.md"
        crash_dashboard_report_path = Path("logs/reports") / f"telemetry_crash_dashboard_{action}_{timestamp}.md"
        retention_dashboard_report_path = Path("logs/reports") / f"telemetry_retention_dashboard_{action}_{timestamp}.md"
        trend_dashboard_report_path = Path("logs/reports") / f"telemetry_trend_dashboard_{action}_{timestamp}.md"
        liveops_impact_report_path = Path("logs/reports") / f"telemetry_liveops_impact_{action}_{timestamp}.md"
        report_layout = layout_validator.validate_managed_path(report_path, "runtime_report")
        if not report_layout["passed"]:
            return self.build_result(
                success=False,
                message="遥测报告路径不符合文件树规范",
                params=self.dump_model(p),
                error="; ".join(issue["message"] for issue in report_layout["issues"]),
                validation={"passed": False, "issues": [issue["code"] for issue in report_layout["issues"]]},
            )
        crash_cluster_report_layout = layout_validator.validate_managed_path(crash_cluster_report_path, "runtime_report")
        if not crash_cluster_report_layout["passed"]:
            return self.build_result(
                success=False,
                message="Crash cluster 报告路径不符合文件树规范",
                params=self.dump_model(p),
                error="; ".join(issue["message"] for issue in crash_cluster_report_layout["issues"]),
                validation={"passed": False, "issues": [issue["code"] for issue in crash_cluster_report_layout["issues"]]},
            )
        crash_dashboard_report_layout = layout_validator.validate_managed_path(crash_dashboard_report_path, "runtime_report")
        if not crash_dashboard_report_layout["passed"]:
            return self.build_result(
                success=False,
                message="Crash dashboard 报告路径不符合文件树规范",
                params=self.dump_model(p),
                error="; ".join(issue["message"] for issue in crash_dashboard_report_layout["issues"]),
                validation={"passed": False, "issues": [issue["code"] for issue in crash_dashboard_report_layout["issues"]]},
            )
        retention_dashboard_report_layout = layout_validator.validate_managed_path(retention_dashboard_report_path, "runtime_report")
        if not retention_dashboard_report_layout["passed"]:
            return self.build_result(
                success=False,
                message="留存漏斗 dashboard 报告路径不符合文件树规范",
                params=self.dump_model(p),
                error="; ".join(issue["message"] for issue in retention_dashboard_report_layout["issues"]),
                validation={"passed": False, "issues": [issue["code"] for issue in retention_dashboard_report_layout["issues"]]},
            )
        trend_dashboard_report_layout = layout_validator.validate_managed_path(trend_dashboard_report_path, "runtime_report")
        if not trend_dashboard_report_layout["passed"]:
            return self.build_result(
                success=False,
                message="留存趋势 dashboard 报告路径不符合文件树规范",
                params=self.dump_model(p),
                error="; ".join(issue["message"] for issue in trend_dashboard_report_layout["issues"]),
                validation={"passed": False, "issues": [issue["code"] for issue in trend_dashboard_report_layout["issues"]]},
            )
        liveops_impact_report_layout = layout_validator.validate_managed_path(liveops_impact_report_path, "runtime_report")
        if not liveops_impact_report_layout["passed"]:
            return self.build_result(
                success=False,
                message="LiveOps impact 报告路径不符合文件树规范",
                params=self.dump_model(p),
                error="; ".join(issue["message"] for issue in liveops_impact_report_layout["issues"]),
                validation={"passed": False, "issues": [issue["code"] for issue in liveops_impact_report_layout["issues"]]},
            )
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(report_content, encoding="utf-8")
        crash_cluster_report_path.write_text(crash_cluster_report_content, encoding="utf-8")
        crash_dashboard_report_path.write_text(crash_dashboard_report_content, encoding="utf-8")
        retention_dashboard_report_path.write_text(retention_dashboard_report_content, encoding="utf-8")
        trend_dashboard_report_path.write_text(trend_dashboard_report_content, encoding="utf-8")
        liveops_impact_report_path.write_text(liveops_impact_report_content, encoding="utf-8")

        artifacts = [
            Artifact(
                name="telemetry_summary.json",
                path="internal://telemetry_summary.json",
                type="report",
                content=json.dumps(summary, ensure_ascii=False, indent=2),
                metadata={"schema_version": TELEMETRY_SUMMARY_SCHEMA_VERSION},
            ),
            Artifact(
                name=report_path.name,
                path=str(report_path),
                type="report",
                content=report_content,
                metadata={"schema_version": TELEMETRY_SUMMARY_SCHEMA_VERSION},
            ),
            Artifact(
                name=crash_cluster_report_path.name,
                path=str(crash_cluster_report_path),
                type="report",
                content=crash_cluster_report_content,
                metadata={"schema_version": TELEMETRY_SUMMARY_SCHEMA_VERSION, "report_kind": "crash_clusters"},
            ),
            Artifact(
                name=crash_dashboard_report_path.name,
                path=str(crash_dashboard_report_path),
                type="report",
                content=crash_dashboard_report_content,
                metadata={"schema_version": TELEMETRY_SUMMARY_SCHEMA_VERSION, "report_kind": "crash_dashboard"},
            ),
            Artifact(
                name=retention_dashboard_report_path.name,
                path=str(retention_dashboard_report_path),
                type="report",
                content=retention_dashboard_report_content,
                metadata={"schema_version": TELEMETRY_SUMMARY_SCHEMA_VERSION, "report_kind": "retention_funnel_dashboard"},
            ),
            Artifact(
                name=trend_dashboard_report_path.name,
                path=str(trend_dashboard_report_path),
                type="report",
                content=trend_dashboard_report_content,
                metadata={"schema_version": TELEMETRY_SUMMARY_SCHEMA_VERSION, "report_kind": "retention_funnel_trends"},
            ),
            Artifact(
                name=liveops_impact_report_path.name,
                path=str(liveops_impact_report_path),
                type="report",
                content=liveops_impact_report_content,
                metadata={"schema_version": TELEMETRY_SUMMARY_SCHEMA_VERSION, "report_kind": "liveops_impact"},
            ),
        ]

        if action in {"validate", "analyze", "apply"} and not summary["passed"]:
            contract_versions = dict(task.context.get("contract_versions") or {})
            contract_versions["telemetry_summary"] = TELEMETRY_SUMMARY_SCHEMA_VERSION
            task.context.update({
                "telemetry_summary": summary,
                "telemetry_passed": False,
                "telemetry_issue_count": len(summary["issues"]),
                "telemetry_warning_count": len(summary["warnings"]),
                "telemetry_pii_violation_count": summary["pii_violation_count"],
                "telemetry_privacy_gate_passed": summary["privacy_gate_passed"],
                "telemetry_catalog_path": f"res://{catalog_path.relative_to(project_root).as_posix()}",
                "telemetry_session_path": "",
                "contract_versions": contract_versions,
            })
            return self.build_result(
                success=False,
                message=f"遥测分析发现 {len(summary['issues'])} 个问题",
                params=self.dump_model(p),
                artifacts=artifacts,
                validation={
                    "passed": False,
                    "issues": list(summary["issues"]),
                    "checks": list(summary["checks"]),
                },
                quality_gate={
                    "passed": False,
                    "checks": list(summary["checks"]),
                    "metrics": dict(summary["metrics"]),
                },
                rollback={"available": False, "strategy": "analysis_failed_no_write"},
            )

        if action in {"template", "apply"}:
            catalog_to_write = catalog_entries if catalog_entries else summary["catalog_entries"]
            catalog_path.parent.mkdir(parents=True, exist_ok=True)
            self.backup_existing_file(task, str(catalog_path))
            catalog_payload = {"schema_version": TELEMETRY_SUMMARY_SCHEMA_VERSION, "events": catalog_to_write}
            catalog_path.write_text(json.dumps(catalog_payload, ensure_ascii=False, indent=2), encoding="utf-8")
            artifacts.append(Artifact(
                name=catalog_path.name,
                path=f"res://{catalog_path.relative_to(project_root).as_posix()}",
                type="resource",
                content=json.dumps(catalog_payload, ensure_ascii=False, indent=2),
                metadata={"telemetry_artifact": "catalog"},
            ))

        if action == "apply" and events:
            target_session_path = session_path or (project_root / "telemetry" / "sessions" / f"session_{int(time.time())}.jsonl").resolve()
            session_layout = layout_validator.validate_managed_path(target_session_path, "telemetry_session")
            if not session_layout["passed"]:
                return self.build_result(
                    success=False,
                    message="遥测会话文件路径不符合文件树规范",
                    params=self.dump_model(p),
                    error="; ".join(issue["message"] for issue in session_layout["issues"]),
                    validation={"passed": False, "issues": [issue["code"] for issue in session_layout["issues"]]},
                )
            target_session_path.parent.mkdir(parents=True, exist_ok=True)
            self.backup_existing_file(task, str(target_session_path))
            rendered = "\n".join(json.dumps(item, ensure_ascii=False) for item in events) + "\n"
            target_session_path.write_text(rendered, encoding="utf-8")
            artifacts.append(Artifact(
                name=target_session_path.name,
                path=f"res://{target_session_path.relative_to(project_root).as_posix()}",
                type="resource",
                content=rendered if len(rendered) < 20000 else None,
                metadata={"telemetry_artifact": "session"},
            ))
            session_path = target_session_path

        contract_versions = dict(task.context.get("contract_versions") or {})
        contract_versions["telemetry_summary"] = TELEMETRY_SUMMARY_SCHEMA_VERSION
        task.context.update({
            "telemetry_summary": summary,
            "telemetry_passed": summary["passed"],
            "telemetry_issue_count": len(summary["issues"]),
            "telemetry_warning_count": len(summary["warnings"]),
            "telemetry_pii_violation_count": summary["pii_violation_count"],
            "telemetry_privacy_gate_passed": summary["privacy_gate_passed"],
            "telemetry_catalog_path": f"res://{catalog_path.relative_to(project_root).as_posix()}",
            "telemetry_session_path": f"res://{session_path.relative_to(project_root).as_posix()}" if session_path and session_path.exists() else "",
            "contract_versions": contract_versions,
        })

        success = summary["passed"] or action == "template"
        message = (
            "遥测模板已生成"
            if action == "template"
            else f"遥测分析通过，sessions={summary['session_count']} events={summary['event_count']}"
            if summary["passed"]
            else f"遥测分析发现 {len(summary['issues'])} 个问题"
        )

        return self.build_result(
            success=success,
            message=message,
            params=self.dump_model(p),
            artifacts=artifacts,
            validation={
                "passed": summary["passed"] if action != "template" else True,
                "issues": list(summary["issues"]),
                "checks": list(summary["checks"]),
            },
            quality_gate={
                "passed": summary["passed"],
                "checks": list(summary["checks"]),
                "metrics": dict(summary["metrics"]),
            },
            rollback={"available": action in {"template", "apply"}, "strategy": "restore_backups_or_remove_written_telemetry_files" if action in {"template", "apply"} else "analysis_only_no_write"},
        )

    def _normalize_action(self, value: str) -> str:
        normalized = str(value or "analyze").strip().lower()
        return normalized if normalized in {"template", "validate", "analyze", "apply"} else "analyze"

    def _default_catalog_entries(self, task: Task) -> List[Dict[str, Any]]:
        feature_id = str(task.context.get("feature_id") or "").strip()
        return [
            {
                "event_name": "session_start",
                "category": "session",
                "description": "玩家开始新会话",
                "feature_id": feature_id,
                "privacy_level": "anonymous",
                "fields": [
                    {"name": "build_id", "type": "string", "required": True, "pii": False},
                    {"name": "channel", "type": "string", "required": True, "pii": False},
                    {"name": "player_id", "type": "string", "required": False, "pii": False},
                ],
            },
            {
                "event_name": "level_start",
                "category": "gameplay",
                "description": "玩家开始关卡",
                "feature_id": feature_id,
                "privacy_level": "anonymous",
                "fields": [
                    {"name": "level_id", "type": "string", "required": True, "pii": False},
                ],
            },
            {
                "event_name": "level_complete",
                "category": "gameplay",
                "description": "玩家完成关卡",
                "feature_id": feature_id,
                "privacy_level": "anonymous",
                "fields": [
                    {"name": "level_id", "type": "string", "required": True, "pii": False},
                    {"name": "duration_sec", "type": "number", "required": False, "pii": False},
                ],
            },
            {
                "event_name": "session_end",
                "category": "session",
                "description": "玩家结束会话",
                "feature_id": feature_id,
                "privacy_level": "anonymous",
                "fields": [
                    {"name": "player_id", "type": "string", "required": False, "pii": False},
                    {"name": "reason", "type": "string", "required": False, "pii": False},
                ],
            },
            {
                "event_name": "economy_reward_granted",
                "category": "economy",
                "description": "授予任务或掉落奖励",
                "feature_id": feature_id,
                "privacy_level": "internal",
                "fields": [
                    {"name": "source_id", "type": "string", "required": True, "pii": False},
                    {"name": "reward_gold", "type": "number", "required": False, "pii": False},
                ],
            },
            {
                "event_name": "crash",
                "category": "error",
                "description": "客户端崩溃或致命错误",
                "feature_id": feature_id,
                "privacy_level": "restricted",
                "fields": [
                    {"name": "error_code", "type": "string", "required": True, "pii": False},
                    {"name": "crash_type", "type": "string", "required": False, "pii": False},
                    {"name": "scene_path", "type": "string", "required": False, "pii": False},
                ],
            },
        ]

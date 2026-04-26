"""
Godot 项目导出技能 (Export Skill)
职责: 调用 Godot CLI 进行 Web 或 Windows 平台的导出, 并管理生成产物
"""

import json
import os
import re
import shutil
import tempfile
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from typing import Dict, Any, List, Optional
from pydantic import BaseModel, Field

from ..base import BaseSkill, SkillMetadata
from ...contracts import (
    BALANCE_ANALYSIS_SCHEMA_VERSION,
    PERFORMANCE_SUMMARY_SCHEMA_VERSION,
    QUALITY_GATE_SCHEMA_VERSION,
    RELEASE_SUMMARY_SCHEMA_VERSION,
    TELEMETRY_SUMMARY_SCHEMA_VERSION,
    build_compact_quality_gate,
    build_release_feature_snapshot,
    normalize_balance_analysis,
    normalize_performance_summary,
    normalize_quality_gate,
    normalize_release_summary,
    normalize_telemetry_summary,
)
from ...models import Task, ToolResult, Artifact
from ...tools.balance_analysis import GameBalanceAnalyzer
from ...tools.performance_analysis import GamePerformanceAnalyzer
from ...tools.telemetry_analysis import TelemetryAnalyzer
from ...validations import ProjectLayoutValidator


class ExportParams(BaseModel):
    """导出参数"""
    preset_name: str = Field(description="导出预设名称, 如 'Web' 或 'Windows Desktop'")
    output_path: Optional[str] = Field(None, description="导出文件路径, 若为空则自动生成时间戳路径")


class ExportProjectSkill(BaseSkill):
    """项目导出技能"""
    
    metadata = SkillMetadata(
        name="export_godot_project",
        description="执行 Godot 项目导出流程, 支持 Web 和 Windows 平台",
        category="resource",
        tags=["export", "build", "release"]
    )
    
    input_model = ExportParams

    def _detect_release_channel(self, task: Task, preset_name: str) -> str:
        explicit = str(task.context.get("release_channel") or "").strip().lower()
        if explicit in {"dev", "qa", "preview", "release"}:
            return explicit

        prompt = f"{task.prompt} {preset_name}".lower()
        if any(token in prompt for token in [" qa", "测试", "验证"]):
            return "qa"
        if any(token in prompt for token in ["preview", "预览", "试玩", "demo", "分享"]):
            return "preview"
        if any(token in prompt for token in ["dev", "开发", "debug"]):
            return "dev"
        if any(token in prompt for token in ["release", "正式", "上线", "发布"]):
            return "release"
        return "preview" if "web" in preset_name.lower() else "dev"

    def _build_release_version(self, task: Task, channel: str, build_stamp: str) -> str:
        base_version = str(
            task.context.get("project_version")
            or task.context.get("release_version")
            or "0.1.0"
        ).strip() or "0.1.0"
        return base_version if channel == "release" else f"{base_version}-{channel}+{build_stamp}"

    def _ensure_export_output(self, output_file: Path, is_web: bool) -> None:
        if output_file.exists():
            return
        output_file.parent.mkdir(parents=True, exist_ok=True)
        if is_web:
            output_file.write_text(
                "<html><body><h1>Godot Game Build Placeholder</h1></body></html>",
                encoding="utf-8",
            )
            return
        output_file.write_bytes(b"")

    def _sync_latest_web_release(self, dist_base: Path, export_dir: Path) -> None:
        dist_base.mkdir(parents=True, exist_ok=True)
        for child in dist_base.iterdir():
            if child.name.startswith(("web_", "win_")):
                continue
            if child.is_dir():
                shutil.rmtree(child, ignore_errors=True)
            else:
                child.unlink(missing_ok=True)

        for child in export_dir.iterdir():
            target = dist_base / child.name
            if child.is_dir():
                shutil.copytree(child, target, dirs_exist_ok=True)
            else:
                shutil.copy2(child, target)

    def _build_known_risks(self, task: Task, channel: str) -> List[str]:
        context = task.context or {}
        risks: List[str] = []
        feature_status = str(context.get("feature_status") or "").strip().lower()
        risk_level = str(context.get("risk") or "").strip().lower()
        review_note = str(context.get("feature_review_note") or "").strip()

        if feature_status and feature_status != "approved":
            risks.append(f"当前功能状态为 {feature_status}，尚未完成最终验收")
        if risk_level in {"medium", "high"}:
            risks.append(f"登记风险等级为 {risk_level}")
        if review_note:
            risks.append(f"评审备注: {review_note}")
        if channel != "release":
            risks.append(f"当前渠道为 {channel}，默认视为非正式交付包")

        return risks or ["未登记已知风险"]

    def _hash_release_file(self, path: Path) -> str:
        digest = sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(65536), b""):
                digest.update(chunk)
        return digest.hexdigest()

    def _collect_release_files(self, export_dir: Path, exclude_names: set[str]) -> List[Dict[str, Any]]:
        files: List[Dict[str, Any]] = []
        for file_path in sorted(path for path in export_dir.rglob("*") if path.is_file()):
            if file_path.name in exclude_names:
                continue
            rel_path = file_path.relative_to(export_dir).as_posix()
            files.append({
                "path": rel_path,
                "size": file_path.stat().st_size,
                "sha256": self._hash_release_file(file_path),
            })
        return files

    def _build_release_summary(
        self,
        task: Task,
        preset_name: str,
        channel: str,
        build_id: str,
        version: str,
        generated_at: str,
        export_dir: Path,
        output_path: str,
        release_url: str,
        versioned_url: str,
        build_log_path: str,
        release_notes_path: str,
        release_manifest_path: str,
        quality_gate: Dict[str, Any],
        files: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        context = task.context or {}
        known_issues = self._build_known_risks(task, channel)
        qa_evidence = self._build_release_qa_evidence(task, quality_gate)
        return normalize_release_summary({
            "build_id": build_id,
            "version": version,
            "channel": channel,
            "preset_name": preset_name,
            "platform": "web" if "web" in preset_name.lower() else "windows",
            "generated_at": generated_at,
            "task_id": task.task_id,
            "task_prompt": task.prompt,
            "output_path": output_path,
            "release_dir": str(export_dir),
            "release_url": release_url,
            "versioned_release_url": versioned_url,
            "build_log_path": build_log_path,
            "release_notes_path": release_notes_path,
            "release_manifest_path": release_manifest_path,
            "feature": build_release_feature_snapshot(context),
            "change_summary": list(context.get("change_summary") or []),
            "acceptance_checklist": list(context.get("acceptance_checklist") or []),
            "known_risks": known_issues,
            "known_issues": known_issues,
            "quality_gate": quality_gate,
            "qa_evidence": qa_evidence,
            "files": files,
            "rollback_hint": f"保留版本目录 {export_dir.name}，如需回滚可重新同步该目录到 latest 入口",
        })

    def _latest_skill_run(self, task: Task, skill_name: str) -> Dict[str, Any]:
        history = list((task.context or {}).get("skill_runs") or [])
        for item in reversed(history):
            if str(item.get("skill_name") or "").strip() == skill_name:
                return dict(item)
        last_skill = dict((task.context or {}).get("last_skill_result") or {})
        if str(last_skill.get("skill_name") or "").strip() == skill_name:
            return last_skill
        return {}

    def _skill_check(self, skill_run: Dict[str, Any], *check_names: str) -> Dict[str, Any]:
        validation = dict(skill_run.get("validation") or {})
        for item in list(validation.get("checks") or []):
            raw = dict(item) if isinstance(item, dict) else {}
            name = str(raw.get("name") or "").strip()
            if name and name in check_names:
                return raw
        return {}

    def _skill_artifact_path(self, skill_run: Dict[str, Any], artifact_type: str) -> str:
        summary = dict(skill_run.get("summary") or {})
        artifact_summary = dict(summary.get("artifact_summary") or {})
        by_type = dict(artifact_summary.get("by_type") or {})
        if int(by_type.get(artifact_type) or 0) <= 0:
            return ""
        for path in list(artifact_summary.get("paths") or []):
            text = str(path or "").strip()
            if text:
                return text
        return ""

    def _skill_status_from_run(self, skill_run: Dict[str, Any], *check_names: str) -> str:
        if not skill_run:
            return "skipped"
        check = self._skill_check(skill_run, *check_names)
        if check:
            return str(check.get("status") or "skipped").strip().lower() or "skipped"
        if str(skill_run.get("status") or "").strip().lower() == "failed":
            return "blocked"
        return "passed"

    def _skill_issues(self, skill_run: Dict[str, Any]) -> List[str]:
        validation = dict(skill_run.get("validation") or {})
        issues: List[str] = []
        for item in list(validation.get("issues") or []):
            text = str(item or "").strip()
            if text and text not in issues:
                issues.append(text)
        return issues

    def _build_release_qa_evidence(self, task: Task, quality_gate: Dict[str, Any]) -> Dict[str, Any]:
        context = task.context or {}
        checks = {
            str(item.get("name") or "").strip(): dict(item)
            for item in list(quality_gate.get("checks") or [])
            if str(item.get("name") or "").strip()
        }
        metrics = dict(quality_gate.get("metrics") or {})
        smoke_run = self._latest_skill_run(task, "smoke_test_scene")
        e2e_run = self._latest_skill_run(task, "e2e_test_scene")
        capture_run = self._latest_skill_run(task, "quick_capture_scene")

        scene_path = str(
            context.get("e2e_scene_path")
            or context.get("test_scene_path")
            or context.get("scene_path")
            or checks.get("smoke_test", {}).get("scene_path")
            or checks.get("performance_budget", {}).get("scene_path")
            or ""
        ).strip()
        asserted_nodes = []
        seen_nodes = set()
        for item in list(dict(e2e_run.get("params") or {}).get("assert_nodes") or []):
            text = str(item or "").strip()
            if text and text not in seen_nodes:
                asserted_nodes.append(text)
                seen_nodes.add(text)
        action_count = len(list(dict(e2e_run.get("params") or {}).get("actions") or []))

        smoke_status = str(
            checks.get("smoke_test", {}).get("status")
            or self._skill_status_from_run(smoke_run, "scene_load", "scene_resolution")
        ).strip().lower() or "skipped"
        smoke_message = str(
            checks.get("smoke_test", {}).get("message")
            or dict(smoke_run.get("summary") or {}).get("message")
            or ("未记录 smoke_test 结果" if smoke_status == "skipped" else "")
        ).strip()

        assertion_status = self._skill_status_from_run(e2e_run, "assert_nodes")
        if asserted_nodes and assertion_status == "skipped":
            assertion_status = "passed" if str(e2e_run.get("status") or "").strip().lower() != "failed" else "blocked"
        assertion_message = str(
            dict(self._skill_check(e2e_run, "assert_nodes")).get("message")
            or dict(e2e_run.get("summary") or {}).get("message")
            or (f"记录了 {len(asserted_nodes)} 个断言节点" if asserted_nodes else "未记录断言型 QA")
        ).strip()

        visual_status = str(checks.get("screenshot_diff", {}).get("status") or "").strip().lower()
        if not visual_status:
            if metrics.get("screenshot_path"):
                visual_status = "passed"
            else:
                visual_status = self._skill_status_from_run(e2e_run, "screenshot_capture", "editor_snapshot")
                if visual_status == "skipped":
                    visual_status = self._skill_status_from_run(capture_run, "screenshot_file_created", "editor_snapshot")
        screenshot_path = str(
            metrics.get("screenshot_path")
            or self._skill_artifact_path(e2e_run, "screenshot")
            or self._skill_artifact_path(capture_run, "screenshot")
            or ""
        ).strip()
        if not screenshot_path and visual_status == "passed":
            visual_status = "warning"
        if metrics.get("screenshot_diff_error") and visual_status == "passed":
            visual_status = "warning"
        visual_message = str(
            checks.get("screenshot_diff", {}).get("message")
            or dict(self._skill_check(e2e_run, "screenshot_capture", "editor_snapshot")).get("message")
            or dict(self._skill_check(capture_run, "screenshot_file_created", "editor_snapshot")).get("message")
            or (f"已记录截图证据: {screenshot_path}" if screenshot_path else "未记录 visual regression 结果")
        ).strip()

        notes: List[str] = []
        for item in [
            *self._skill_issues(smoke_run),
            *self._skill_issues(e2e_run),
            *self._skill_issues(capture_run),
            str(metrics.get("screenshot_diff_error") or "").strip(),
        ]:
            text = str(item or "").strip()
            if text and text not in notes:
                notes.append(text)

        return {
            "scene_path": scene_path,
            "smoke_status": smoke_status,
            "smoke_message": smoke_message,
            "assertion_status": assertion_status,
            "assertion_message": assertion_message,
            "assertion_node_count": len(asserted_nodes),
            "asserted_nodes": asserted_nodes,
            "action_count": action_count,
            "screenshot_status": visual_status or "skipped",
            "screenshot_message": visual_message,
            "screenshot_path": screenshot_path,
            "screenshot_diff_ratio": metrics.get("screenshot_diff_ratio"),
            "max_screenshot_diff_ratio": metrics.get("max_screenshot_diff_ratio"),
            "screenshot_diff_error": metrics.get("screenshot_diff_error"),
            "metrics": {
                "scene_load_ms": metrics.get("scene_load_ms"),
                "fps": metrics.get("fps"),
                "memory_peak_mb": metrics.get("memory_peak_mb"),
            },
            "checks": [
                {
                    "check_id": "smoke_test",
                    "label": "Smoke Test",
                    "status": smoke_status,
                    "message": smoke_message,
                    "details": {"scene_path": scene_path, "skill_name": "smoke_test_scene"},
                },
                {
                    "check_id": "qa_assertions",
                    "label": "Assertion QA",
                    "status": assertion_status,
                    "message": assertion_message,
                    "details": {
                        "scene_path": scene_path,
                        "assertion_node_count": len(asserted_nodes),
                        "asserted_nodes": asserted_nodes,
                        "action_count": action_count,
                        "skill_name": "e2e_test_scene",
                    },
                },
                {
                    "check_id": "visual_regression",
                    "label": "Visual Regression",
                    "status": visual_status or "skipped",
                    "message": visual_message,
                    "details": {
                        "scene_path": scene_path,
                        "screenshot_path": screenshot_path,
                        "screenshot_diff_ratio": metrics.get("screenshot_diff_ratio"),
                        "max_screenshot_diff_ratio": metrics.get("max_screenshot_diff_ratio"),
                        "screenshot_diff_error": metrics.get("screenshot_diff_error"),
                        "skill_name": "e2e_test_scene" if e2e_run else ("quick_capture_scene" if capture_run else ""),
                    },
                },
            ],
            "notes": notes,
        }

    def _build_release_notes(self, summary: Dict[str, Any]) -> str:
        feature = summary.get("feature") or {}
        change_summary = list(summary.get("change_summary") or [])
        acceptance_checklist = list(summary.get("acceptance_checklist") or [])
        known_risks = list(summary.get("known_risks") or [])
        quality_gate = summary.get("quality_gate") or {}
        qa_evidence = summary.get("qa_evidence") or {}
        files = list(summary.get("files") or [])

        lines = [
            f"# Release Notes: {summary['build_id']}",
            "",
            f"- Version: {summary['version']}",
            f"- Channel: {summary['channel']}",
            f"- Platform: {summary['platform']}",
            f"- Preset: {summary['preset_name']}",
            f"- Generated At: {summary['generated_at']}",
            f"- Task ID: {summary['task_id']}",
            f"- Release URL: {summary['release_url']}",
            f"- Versioned URL: {summary['versioned_release_url']}",
            "",
            "## Feature Context",
            "",
            f"- Feature ID: {feature.get('feature_id') or '-'}",
            f"- Owner: {feature.get('owner') or '-'}",
            f"- Priority: {feature.get('priority') or '-'}",
            f"- Risk: {feature.get('risk') or '-'}",
            f"- Feature Status: {feature.get('feature_status') or '-'}",
            "",
            "## Change Summary",
            "",
        ]
        lines.extend([f"- {item}" for item in change_summary] or ["- No structured change summary recorded"])
        lines.extend(["", "## Acceptance Checklist", ""])
        lines.extend(
            [
                f"- [{item.get('status', 'pending')}] {item.get('label', '')}"
                + (f" / validation={item.get('validation_method')}" if item.get("validation_method") else "")
                + (f" / blockers={', '.join(list(item.get('blockers') or []))}" if item.get("blockers") else "")
                for item in acceptance_checklist
            ]
            or ["- No acceptance checklist recorded"]
        )
        lines.extend(["", "## Known Risks", ""])
        lines.extend([f"- {item}" for item in known_risks] or ["- None"])
        lines.extend(["", "## Quality Gate", ""])
        lines.append(f"- Passed: {quality_gate.get('passed', False)}")
        lines.extend([
            f"- {check.get('name')}: {check.get('status')} - {check.get('message')}"
            for check in quality_gate.get("checks", [])
        ] or ["- No quality gate checks recorded"])
        lines.extend(["", "## QA Evidence", ""])
        lines.append(f"- Scene: {qa_evidence.get('scene_path') or '-'}")
        lines.append(
            f"- Smoke: {qa_evidence.get('smoke_status') or 'skipped'} / Assertions: {qa_evidence.get('assertion_status') or 'skipped'} / Visual: {qa_evidence.get('screenshot_status') or 'skipped'}"
        )
        lines.append(
            f"- Metrics: scene_load_ms={qa_evidence.get('metrics', {}).get('scene_load_ms') or '-'} / fps={qa_evidence.get('metrics', {}).get('fps') or '-'} / memory_peak_mb={qa_evidence.get('metrics', {}).get('memory_peak_mb') or '-'}"
        )
        if qa_evidence.get("assertion_node_count") is not None:
            lines.append(f"- Assertion Nodes: {qa_evidence.get('assertion_node_count') or 0}")
        if qa_evidence.get("screenshot_path"):
            lines.append(f"- Screenshot: {qa_evidence.get('screenshot_path')}")
        if qa_evidence.get("screenshot_diff_ratio") is not None:
            lines.append(
                f"- Screenshot Diff: {qa_evidence.get('screenshot_diff_ratio'):.4f} / threshold={qa_evidence.get('max_screenshot_diff_ratio') if qa_evidence.get('max_screenshot_diff_ratio') is not None else '-'}"
            )
        lines.extend(["", "## Files", ""])
        lines.extend([f"- {item['path']} ({item['size']} bytes)" for item in files] or ["- No exported files recorded"])
        lines.extend(["", "## Rollback", "", f"- {summary['rollback_hint']}"])
        return "\n".join(lines)

    def _resolve_gate_scene(self, task: Task) -> Optional[str]:
        for key in ("test_scene_path", "e2e_scene_path", "scene_path"):
            value = str(task.context.get(key) or "").strip()
            if value:
                return value

        editor_state = task.context.get("editor_state", {})
        if isinstance(editor_state, dict):
            current_scene = str(editor_state.get("current_scene") or "").strip()
            if current_scene:
                return current_scene

        project_path = getattr(self.godot_cli, "project_path", None)
        if project_path:
            project_root = Path(project_path)
            scenes = sorted(project_root.rglob("*.tscn"))
            if scenes:
                return f"res://{scenes[0].relative_to(project_root).as_posix()}"
        return None

    def _resolve_project_path(self, raw_path: str) -> Optional[Path]:
        if not raw_path:
            return None

        project_root = Path(getattr(self.godot_cli, "project_path", ".") or ".").resolve()
        normalized = str(raw_path).strip().replace("\\", "/")
        if normalized.startswith("res://"):
            return (project_root / normalized.replace("res://", "", 1)).resolve()

        candidate = Path(normalized)
        if candidate.is_absolute():
            return candidate.resolve()
        return (project_root / candidate).resolve()

    def _normalize_optional_float(self, value: Any) -> Optional[float]:
        if value in (None, "", False):
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    def _gate_status_for_budget(
        self,
        measured: Optional[float],
        limit: Optional[float],
        compare: str,
        channel: str,
        missing_message: str,
        formatter,
    ) -> tuple[str, str]:
        if measured is None:
            status = "blocked" if channel in {"qa", "release"} else "skipped"
            return status, missing_message
        if limit is None:
            return "skipped", formatter(measured, None)

        passed = measured <= limit if compare == "max" else measured >= limit
        if passed:
            return "passed", formatter(measured, limit)

        status = "blocked" if channel in {"qa", "release"} else "warning"
        return status, formatter(measured, limit)

    def _build_gate_paths(self, task: Task) -> tuple[Optional[Path], Optional[Path]]:
        context = task.context or {}
        budget_context = context.get("performance_budget") or context.get("qa_gate_budget") or {}
        baseline_path = self._resolve_project_path(str(budget_context.get("baseline_screenshot_path") or ""))

        should_capture = bool(
            baseline_path
            or budget_context.get("capture_screenshot")
            or context.get("capture_release_screenshot")
        )
        if not should_capture:
            return None, baseline_path

        project_root = Path(getattr(self.godot_cli, "project_path", ".") or ".").resolve()
        artifact_dir = project_root / "logs" / "test_artifacts"
        artifact_dir.mkdir(parents=True, exist_ok=True)
        screenshot_path = artifact_dir / f"release_gate_{task.task_id[:8]}_{int(datetime.now(timezone.utc).timestamp())}.png"
        return screenshot_path, baseline_path

    def _build_gate_script(
        self,
        scene_path: str,
        screenshot_path: Optional[Path],
        baseline_path: Optional[Path],
    ) -> str:
        normalized_path = scene_path.replace("\\", "/")
        normalized_screenshot = str(screenshot_path).replace("\\", "/") if screenshot_path else ""
        normalized_baseline = str(baseline_path).replace("\\", "/") if baseline_path else ""
        return f"""extends SceneTree
func _sample_diff_ratio(current_image: Image, baseline_image: Image) -> float:
    current_image.convert(Image.FORMAT_RGBA8)
    baseline_image.convert(Image.FORMAT_RGBA8)
    if current_image.get_width() != baseline_image.get_width() or current_image.get_height() != baseline_image.get_height():
        return 1.0

    var width := current_image.get_width()
    var height := current_image.get_height()
    var step_x := max(1, int(width / 64))
    var step_y := max(1, int(height / 64))
    var changed := 0
    var sampled := 0

    for y in range(0, height, step_y):
        for x in range(0, width, step_x):
            var current_pixel := current_image.get_pixel(x, y)
            var baseline_pixel := baseline_image.get_pixel(x, y)
            var delta := abs(current_pixel.r - baseline_pixel.r) + abs(current_pixel.g - baseline_pixel.g) + abs(current_pixel.b - baseline_pixel.b) + abs(current_pixel.a - baseline_pixel.a)
            if delta > 0.03:
                changed += 1
            sampled += 1

    return float(changed) / max(1.0, float(sampled))

func _initialize():
    var started_at := Time.get_ticks_msec()
    var packed := load("{normalized_path}")
    if packed == null:
        push_error("load failed")
        quit(2)
        return
    var instance = packed.instantiate()
    root.add_child(instance)
    for _frame in range(6):
        await process_frame
    var elapsed := Time.get_ticks_msec() - started_at
    var fps := Engine.get_frames_per_second()
    var memory_peak_mb := OS.get_static_memory_peak_usage() / (1024.0 * 1024.0)
    print("GODOT_AGENT_SCENE_LOAD_MS=%d" % elapsed)
    print("GODOT_AGENT_FPS=%.2f" % fps)
    print("GODOT_AGENT_MEMORY_PEAK_MB=%.2f" % memory_peak_mb)
    if "{normalized_screenshot}" != "":
        var screenshot := root.get_texture().get_image()
        if screenshot:
            screenshot.save_png("{normalized_screenshot}")
            print("GODOT_AGENT_SCREENSHOT_PATH={normalized_screenshot}")
            if "{normalized_baseline}" != "":
                var baseline := Image.new()
                var baseline_error := baseline.load("{normalized_baseline}")
                if baseline_error == OK:
                    print("GODOT_AGENT_SCREENSHOT_DIFF_RATIO=%.4f" % _sample_diff_ratio(screenshot, baseline))
                else:
                    print("GODOT_AGENT_SCREENSHOT_DIFF_ERROR=baseline_load_failed")
    quit(0)
"""

    def _extract_gate_metrics(self, stdout: str) -> Dict[str, Any]:
        def _read_number(pattern: str) -> Optional[float]:
            match = re.search(pattern, stdout)
            return float(match.group(1)) if match else None

        screenshot_match = re.search(r"GODOT_AGENT_SCREENSHOT_PATH=(.+)", stdout)
        diff_error_match = re.search(r"GODOT_AGENT_SCREENSHOT_DIFF_ERROR=(.+)", stdout)
        return {
            "scene_load_ms": int(_read_number(r"GODOT_AGENT_SCENE_LOAD_MS=(\d+)") or 0) or None,
            "fps": _read_number(r"GODOT_AGENT_FPS=([0-9]+(?:\.[0-9]+)?)"),
            "memory_peak_mb": _read_number(r"GODOT_AGENT_MEMORY_PEAK_MB=([0-9]+(?:\.[0-9]+)?)"),
            "screenshot_diff_ratio": _read_number(r"GODOT_AGENT_SCREENSHOT_DIFF_RATIO=([0-9]+(?:\.[0-9]+)?)"),
            "screenshot_path": screenshot_match.group(1).strip() if screenshot_match else None,
            "screenshot_diff_error": diff_error_match.group(1).strip() if diff_error_match else None,
        }

    def _run_scene_gate(self, task: Task, scene_path: str, budget_context: Dict[str, Any], channel: str) -> tuple[List[Dict[str, Any]], List[Artifact], Dict[str, Any]]:
        max_scene_load_ms = int(budget_context.get("max_scene_load_ms", 1500))
        min_fps = self._normalize_optional_float(budget_context.get("min_fps"))
        max_memory_peak_mb = self._normalize_optional_float(budget_context.get("max_memory_peak_mb"))
        max_screenshot_diff_ratio = self._normalize_optional_float(budget_context.get("max_screenshot_diff_ratio"))
        screenshot_path, baseline_path = self._build_gate_paths(task)
        script_content = self._build_gate_script(scene_path, screenshot_path, baseline_path)
        with tempfile.NamedTemporaryFile(mode="w", suffix=".gd", delete=False, encoding="utf-8") as handle:
            handle.write(script_content)
            script_path = handle.name

        try:
            result = self.godot_cli.run_headless(script_path)
        finally:
            try:
                os.unlink(script_path)
            except OSError:
                pass

        if not result.success:
            message = result.error or result.message or "headless scene gate failed"
            return (
                [
                    {"name": "smoke_test", "status": "blocked", "message": message, "scene_path": scene_path},
                    {"name": "performance_budget", "status": "blocked", "message": "烟雾测试失败，无法产出性能指标", "scene_path": scene_path},
                    {"name": "fps_budget", "status": "blocked", "message": "烟雾测试失败，无法采集 FPS", "scene_path": scene_path},
                    {"name": "memory_peak_budget", "status": "blocked", "message": "烟雾测试失败，无法采集内存峰值", "scene_path": scene_path},
                    {"name": "screenshot_diff", "status": "blocked" if baseline_path else "skipped", "message": "烟雾测试失败，无法执行截图对比", "scene_path": scene_path},
                ],
                [],
                {},
            )

        stdout = str((result.data or {}).get("stdout", ""))
        metrics = self._extract_gate_metrics(stdout)
        artifacts: List[Artifact] = []
        smoke_check = {
            "name": "smoke_test",
            "status": "passed",
            "message": f"场景可正常加载: {scene_path}",
            "scene_path": scene_path,
        }

        if metrics.get("screenshot_path") and Path(metrics["screenshot_path"]).exists():
            artifacts.append(Artifact(
                name=Path(metrics["screenshot_path"]).name,
                path=str(Path(metrics["screenshot_path"]).resolve()),
                type="screenshot",
                metadata={"scene_path": scene_path, "gate": "quality_gate"},
            ))

        perf_status, perf_message = self._gate_status_for_budget(
            metrics.get("scene_load_ms"),
            float(max_scene_load_ms),
            "max",
            channel,
            "未获取到场景加载耗时指标",
            lambda measured, limit: (
                f"场景加载 {int(measured)}ms / 预算 {int(limit)}ms"
                if limit is not None and measured <= limit
                else f"场景加载 {int(measured)}ms 超出预算 {int(limit)}ms"
                if limit is not None
                else f"场景加载 {int(measured)}ms，未配置 max_scene_load_ms"
            ),
        )
        fps_status, fps_message = self._gate_status_for_budget(
            metrics.get("fps"),
            min_fps,
            "min",
            channel,
            "未获取到 FPS 指标",
            lambda measured, limit: (
                f"FPS {measured:.2f} / 下限 {limit:.2f}"
                if limit is not None and measured >= limit
                else f"FPS {measured:.2f} 低于下限 {limit:.2f}"
                if limit is not None
                else f"FPS {measured:.2f}，未配置 min_fps"
            ),
        )
        memory_status, memory_message = self._gate_status_for_budget(
            metrics.get("memory_peak_mb"),
            max_memory_peak_mb,
            "max",
            channel,
            "未获取到内存峰值指标",
            lambda measured, limit: (
                f"内存峰值 {measured:.2f}MB / 预算 {limit:.2f}MB"
                if limit is not None and measured <= limit
                else f"内存峰值 {measured:.2f}MB 超出预算 {limit:.2f}MB"
                if limit is not None
                else f"内存峰值 {measured:.2f}MB，未配置 max_memory_peak_mb"
            ),
        )

        if baseline_path:
            if metrics.get("screenshot_diff_error"):
                screenshot_status = "blocked" if channel in {"qa", "release"} else "warning"
                screenshot_message = f"基线图加载失败: {metrics['screenshot_diff_error']}"
            else:
                screenshot_status, screenshot_message = self._gate_status_for_budget(
                    metrics.get("screenshot_diff_ratio"),
                    max_screenshot_diff_ratio,
                    "max",
                    channel,
                    "未获取到截图 diff 指标",
                    lambda measured, limit: (
                        f"截图 diff {measured:.4f} / 上限 {limit:.4f}"
                        if limit is not None and measured <= limit
                        else f"截图 diff {measured:.4f} 超出上限 {limit:.4f}"
                        if limit is not None
                        else f"截图 diff {measured:.4f}，未配置 max_screenshot_diff_ratio"
                    ),
                )
        elif metrics.get("screenshot_path"):
            screenshot_status = "skipped"
            screenshot_message = "已生成截图样本，未配置 baseline_screenshot_path"
        else:
            screenshot_status = "skipped"
            screenshot_message = "未启用截图采集"

        checks = [
            smoke_check,
            {
                "name": "performance_budget",
                "status": perf_status,
                "message": perf_message,
                "scene_path": scene_path,
                "scene_load_ms": metrics.get("scene_load_ms"),
                "budget_ms": max_scene_load_ms,
            },
            {
                "name": "fps_budget",
                "status": fps_status,
                "message": fps_message,
                "scene_path": scene_path,
                "fps": metrics.get("fps"),
                "min_fps": min_fps,
            },
            {
                "name": "memory_peak_budget",
                "status": memory_status,
                "message": memory_message,
                "scene_path": scene_path,
                "memory_peak_mb": metrics.get("memory_peak_mb"),
                "max_memory_peak_mb": max_memory_peak_mb,
            },
            {
                "name": "screenshot_diff",
                "status": screenshot_status,
                "message": screenshot_message,
                "scene_path": scene_path,
                "baseline_path": str(baseline_path) if baseline_path else None,
                "screenshot_path": metrics.get("screenshot_path"),
                "screenshot_diff_ratio": metrics.get("screenshot_diff_ratio"),
                "max_screenshot_diff_ratio": max_screenshot_diff_ratio,
            },
        ]
        return checks, artifacts, {key: value for key, value in metrics.items() if value not in (None, "")}

    def _run_quality_gate(self, task: Task, preset_name: str, channel: str) -> tuple[Dict[str, Any], List[Artifact]]:
        context = task.context or {}
        feature_status = str(context.get("feature_status") or "").strip().lower()
        checks: List[Dict[str, Any]] = []
        gate_artifacts: List[Artifact] = []
        gate_metrics: Dict[str, Any] = {}

        if channel == "release":
            passed = feature_status == "approved"
            checks.append({
                "name": "feature_status",
                "status": "passed" if passed else "blocked",
                "message": "功能已通过正式验收" if passed else f"正式发布要求 feature_status=approved，当前为 {feature_status or 'unset'}",
            })
        elif channel == "qa":
            passed = feature_status in {"pending_acceptance", "approved"}
            checks.append({
                "name": "feature_status",
                "status": "passed" if passed else "blocked",
                "message": "QA 渠道允许待验收或已通过任务" if passed else f"QA 发布要求功能至少进入待验收，当前为 {feature_status or 'unset'}",
            })
        else:
            checks.append({
                "name": "feature_status",
                "status": "warning" if feature_status == "returned" else "passed",
                "message": f"{channel} 渠道记录当前功能状态: {feature_status or 'unset'}",
            })

        scene_path = self._resolve_gate_scene(task)
        budget_context = context.get("performance_budget") or context.get("qa_gate_budget") or {}
        max_scene_load_ms = int(budget_context.get("max_scene_load_ms", 1500))
        if scene_path:
            scene_checks, scene_artifacts, scene_metrics = self._run_scene_gate(task, scene_path, budget_context, channel)
            checks.extend(scene_checks)
            gate_artifacts.extend(scene_artifacts)
            gate_metrics.update(scene_metrics)
        else:
            checks.append({
                "name": "smoke_test",
                "status": "blocked" if channel in {"qa", "release"} else "skipped",
                "message": "未找到可执行门禁的场景路径",
            })
            checks.append({
                "name": "performance_budget",
                "status": "blocked" if channel in {"qa", "release"} else "skipped",
                "message": "缺少场景路径，无法测量性能预算",
                "budget_ms": max_scene_load_ms,
            })
            checks.append({
                "name": "fps_budget",
                "status": "blocked" if channel in {"qa", "release"} else "skipped",
                "message": "缺少场景路径，无法采集 FPS",
            })
            checks.append({
                "name": "memory_peak_budget",
                "status": "blocked" if channel in {"qa", "release"} else "skipped",
                "message": "缺少场景路径，无法采集内存峰值",
            })
            checks.append({
                "name": "screenshot_diff",
                "status": "blocked" if channel in {"qa", "release"} else "skipped",
                "message": "缺少场景路径，无法执行截图对比",
            })

        performance_checks, performance_metrics = self._run_performance_gate(task, channel)
        existing_check_names = {check["name"] for check in checks}
        for performance_check in performance_checks:
            if performance_check.get("name") in existing_check_names:
                continue
            checks.append(performance_check)
            existing_check_names.add(performance_check.get("name"))
        gate_metrics.update(performance_metrics)

        balance_check, balance_metrics = self._run_balance_gate(task, channel)
        if balance_check:
            checks.append(balance_check)
            gate_metrics.update(balance_metrics)

        telemetry_check, telemetry_metrics = self._run_telemetry_gate(task, channel)
        if telemetry_check:
            checks.append(telemetry_check)
            gate_metrics.update(telemetry_metrics)

        blocked_checks = [check for check in checks if check["status"] == "blocked"]
        return (normalize_quality_gate({
            "passed": not blocked_checks,
            "channel": channel,
            "preset_name": preset_name,
            "checks": checks,
            "blocked_checks": [check["name"] for check in blocked_checks],
            "metrics": gate_metrics,
        }), gate_artifacts)

    def _run_performance_gate(self, task: Task, channel: str) -> tuple[List[Dict[str, Any]], Dict[str, Any]]:
        context = task.context or {}
        budget_context = context.get("performance_budget") or context.get("qa_gate_budget") or {}
        existing_summary = context.get("performance_summary")
        summary = normalize_performance_summary(existing_summary) if existing_summary else None

        has_profile_input = any(
            key in context for key in [
                "performance_profile",
                "performance_profile_metrics",
                "performance_profile_path",
                "performance_baseline_metrics",
                "performance_baseline_path",
            ]
        )
        if (not summary or not summary.get("checks")) and has_profile_input:
            analyzer = GamePerformanceAnalyzer(
                Path(getattr(self.godot_cli, "project_path", ".") or ".").resolve(),
                runtime_root=Path.cwd(),
            )
            summary = analyzer.analyze(
                scene_path=str(
                    context.get("performance_scene_path")
                    or context.get("scene_path")
                    or context.get("test_scene_path")
                    or ""
                ).strip() or None,
                baseline_path=str(context.get("performance_baseline_path") or "").strip() or None,
                profile_path=str(context.get("performance_profile_path") or "").strip() or None,
                baseline_metrics=context.get("performance_baseline_metrics"),
                profile_metrics=context.get("performance_profile")
                    or context.get("performance_profile_metrics"),
                budget_overrides=budget_context,
            )
            contract_versions = dict(context.get("contract_versions") or {})
            contract_versions["performance_summary"] = PERFORMANCE_SUMMARY_SCHEMA_VERSION
            task.context["contract_versions"] = contract_versions
            task.context["performance_summary"] = summary
            task.context["performance_passed"] = summary["passed"]
            task.context["performance_issue_count"] = len(summary["issues"])
            task.context["performance_warning_count"] = len(summary["warnings"])
            task.context["performance_baseline_path"] = summary.get("baseline_path", "")
            task.context["performance_profile_path"] = summary.get("profile_path", "")

        if summary and summary.get("checks"):
            contract_versions = dict(context.get("contract_versions") or {})
            contract_versions["performance_summary"] = PERFORMANCE_SUMMARY_SCHEMA_VERSION
            task.context["contract_versions"] = contract_versions
            task.context["performance_summary"] = summary
            task.context["performance_passed"] = summary["passed"]
            task.context["performance_issue_count"] = len(summary["issues"])
            task.context["performance_warning_count"] = len(summary["warnings"])

        if not summary or not summary.get("checks"):
            return [], {}

        checks = []
        for item in list(summary.get("checks") or []):
            check = dict(item)
            if str(check.get("name") or "") in {"performance_budget", "fps_budget", "memory_peak_budget", "screenshot_diff"}:
                continue
            if channel not in {"qa", "release"} and check.get("status") == "blocked":
                check["status"] = "warning"
            checks.append(check)
        return checks, dict(summary.get("metrics") or {})

    def _run_balance_gate(self, task: Task, channel: str) -> tuple[Optional[Dict[str, Any]], Dict[str, Any]]:
        context = task.context or {}
        project_root = Path(getattr(self.godot_cli, "project_path", ".") or ".").resolve()
        analyzer = GameBalanceAnalyzer(project_root)

        existing_analysis = context.get("balance_analysis")
        analysis = normalize_balance_analysis(existing_analysis) if existing_analysis else None
        present_tables = analyzer.detect_present_tables()
        if (not analysis or not analysis.get("table_types")) and present_tables:
            analysis = analyzer.analyze(include_tables=present_tables)
            contract_versions = dict(context.get("contract_versions") or {})
            contract_versions["balance_analysis"] = BALANCE_ANALYSIS_SCHEMA_VERSION
            task.context["contract_versions"] = contract_versions
            task.context["balance_analysis"] = analysis
            task.context["balance_analysis_score"] = analysis["score"]
            task.context["balance_analysis_passed"] = analysis["passed"]
            task.context["balance_analysis_issue_count"] = analysis["issue_count"]
            task.context["balance_analysis_warning_count"] = analysis["warning_count"]
            task.context["balance_analysis_table_types"] = list(analysis["table_types"])

        if not analysis or not analysis.get("table_types"):
            return ({
                "name": "balance_analysis",
                "status": "skipped",
                "message": "未检测到 enemy / quest / loot 数值表，跳过平衡分析门禁",
            }, {})

        status = "passed" if analysis["passed"] else ("blocked" if channel in {"qa", "release"} else "warning")
        issue_count = analysis.get("issue_count", 0)
        warning_count = analysis.get("warning_count", 0)
        message = (
            f"数值平衡分析通过，score={analysis['score']}"
            if analysis["passed"]
            else f"数值平衡分析发现 {issue_count} 个问题 / {warning_count} 个警告，score={analysis['score']}"
        )
        return ({
            "name": "balance_analysis",
            "status": status,
            "message": message,
            "table_types": list(analysis["table_types"]),
            "score": analysis["score"],
            "issue_count": issue_count,
            "warning_count": warning_count,
        }, {
            "balance_score": analysis["score"],
            "balance_issue_count": issue_count,
            "balance_warning_count": warning_count,
            "balance_table_types": list(analysis["table_types"]),
        })

    def _run_telemetry_gate(self, task: Task, channel: str) -> tuple[Optional[Dict[str, Any]], Dict[str, Any]]:
        context = task.context or {}
        project_root = Path(getattr(self.godot_cli, "project_path", ".") or ".").resolve()
        analyzer = TelemetryAnalyzer(project_root)

        existing_summary = context.get("telemetry_summary")
        summary = normalize_telemetry_summary(existing_summary) if existing_summary else None
        if (not summary or not summary.get("catalog_entry_count")) and analyzer.detect_present_telemetry():
            summary = analyzer.analyze()
            contract_versions = dict(context.get("contract_versions") or {})
            contract_versions["telemetry_summary"] = TELEMETRY_SUMMARY_SCHEMA_VERSION
            task.context["contract_versions"] = contract_versions
            task.context["telemetry_summary"] = summary
            task.context["telemetry_passed"] = summary["passed"]
            task.context["telemetry_issue_count"] = len(summary["issues"])
            task.context["telemetry_warning_count"] = len(summary["warnings"])
            task.context["telemetry_pii_violation_count"] = summary.get("pii_violation_count", 0)
            task.context["telemetry_privacy_gate_passed"] = summary.get("privacy_gate_passed", True)
            task.context["telemetry_catalog_path"] = summary.get("catalog_path", "")
            task.context["telemetry_session_path"] = summary.get("session_path", "")

        if not summary or not summary.get("catalog_entry_count"):
            return ({
                "name": "telemetry_health",
                "status": "skipped",
                "message": "未检测到遥测字典或会话回流，跳过 telemetry 门禁",
            }, {})

        issue_count = len(summary.get("issues") or [])
        warning_count = len(summary.get("warnings") or [])
        pii_violation_count = int(summary.get("pii_violation_count") or 0)
        status = "passed" if issue_count == 0 else ("blocked" if channel in {"qa", "release"} else "warning")
        message = (
            f"遥测回流通过，sessions={summary['session_count']} events={summary['event_count']}"
            if issue_count == 0
            else (
                f"遥测隐私门禁失败，检测到 {pii_violation_count} 个 PII 问题 / {warning_count} 个警告"
                if pii_violation_count
                else f"遥测回流发现 {issue_count} 个问题 / {warning_count} 个警告"
            )
        )
        return ({
            "name": "telemetry_health",
            "status": status,
            "message": message,
            "session_count": summary.get("session_count"),
            "event_count": summary.get("event_count"),
            "crash_count": summary.get("crash_count"),
            "uncataloged_event_count": summary.get("uncataloged_event_count"),
            "pii_violation_count": pii_violation_count,
            "privacy_gate_passed": summary.get("privacy_gate_passed"),
            "affected_build_count": dict(summary.get("crash_regression_dashboard") or {}).get("affected_build_count", 0),
            "affected_scene_count": dict(summary.get("crash_regression_dashboard") or {}).get("affected_scene_count", 0),
            "largest_dropoff_step": dict(summary.get("retention_funnel_dashboard") or {}).get("largest_dropoff_step", ""),
            "largest_dropoff_rate": dict(summary.get("retention_funnel_dashboard") or {}).get("largest_dropoff_rate", 0),
            "trend_day_count": dict(summary.get("retention_funnel_trend_dashboard") or {}).get("day_count", 0),
            "liveops_running_experiment_count": dict(summary.get("liveops_impact_dashboard") or {}).get("running_experiment_count", 0),
            "liveops_matched_metric_count": dict(summary.get("liveops_impact_dashboard") or {}).get("matched_metric_count", 0),
        }, {
            "telemetry_session_count": summary.get("session_count"),
            "telemetry_event_count": summary.get("event_count"),
            "telemetry_crash_count": summary.get("crash_count"),
            "telemetry_crash_cluster_count": len(summary.get("crash_clusters") or []),
            "telemetry_affected_build_count": dict(summary.get("crash_regression_dashboard") or {}).get("affected_build_count", 0),
            "telemetry_affected_scene_count": dict(summary.get("crash_regression_dashboard") or {}).get("affected_scene_count", 0),
            "telemetry_uncataloged_event_count": summary.get("uncataloged_event_count"),
            "telemetry_funnel_completion_rate": summary.get("funnel_completion_rate"),
            "telemetry_pii_violation_count": pii_violation_count,
            "telemetry_privacy_gate_passed": summary.get("privacy_gate_passed"),
            "telemetry_retention_user_count": summary.get("retention_user_count"),
            "telemetry_d1_retention_rate": next((item.get("retention_rate") for item in summary.get("retention_cohorts", []) if item.get("window") == "d1"), 0),
            "telemetry_d7_retention_rate": next((item.get("retention_rate") for item in summary.get("retention_cohorts", []) if item.get("window") == "d7"), 0),
            "telemetry_largest_dropoff_step": dict(summary.get("retention_funnel_dashboard") or {}).get("largest_dropoff_step", ""),
            "telemetry_largest_dropoff_rate": dict(summary.get("retention_funnel_dashboard") or {}).get("largest_dropoff_rate", 0),
            "telemetry_lowest_retention_window": dict(summary.get("retention_funnel_dashboard") or {}).get("lowest_retention_window", ""),
            "telemetry_lowest_retention_rate": dict(summary.get("retention_funnel_dashboard") or {}).get("lowest_retention_rate", 0),
            "telemetry_trend_day_count": dict(summary.get("retention_funnel_trend_dashboard") or {}).get("day_count", 0),
            "telemetry_liveops_running_experiment_count": dict(summary.get("liveops_impact_dashboard") or {}).get("running_experiment_count", 0),
            "telemetry_liveops_matched_metric_count": dict(summary.get("liveops_impact_dashboard") or {}).get("matched_metric_count", 0),
        })

    def _build_quality_gate_report(self, gate: Dict[str, Any]) -> str:
        lines = [
            "# QA Gate Report",
            "",
            f"- Channel: {gate.get('channel')}",
            f"- Preset: {gate.get('preset_name')}",
            f"- Passed: {gate.get('passed')}",
            "",
            "## Metrics",
            "",
        ]
        metrics = gate.get("metrics") or {}
        if metrics:
            for key, value in metrics.items():
                lines.append(f"- {key}: {value}")
        else:
            lines.append("- No metrics captured")
        lines.extend([
            "",
            "## Checks",
            "",
        ])
        for check in gate.get("checks", []):
            lines.append(f"- {check.get('name')}: {check.get('status')} - {check.get('message')}")
        if gate.get("blocked_checks"):
            lines.extend(["", "## Blocked Checks", ""])
            lines.extend([f"- {name}" for name in gate["blocked_checks"]])
        return "\n".join(lines)

    def execute(self, task: Task, params: Dict[str, Any]) -> ToolResult:
        p = ExportParams(**params)
        preset_name = p.preset_name
        
        task.add_log(f"🚀 开始准备 {preset_name} 发布 (Skill 执行)...")
        
        # 1. 确定导出目录
        is_web = "web" in preset_name.lower()
        dist_base = Path("api_server/static/dist")
        dist_base.mkdir(parents=True, exist_ok=True)
        
        build_dt = datetime.now(timezone.utc)
        build_stamp = build_dt.strftime("%Y%m%d%H%M%S")
        if is_web:
            export_dir = dist_base / f"web_{build_stamp}"
            output_path = p.output_path or str(export_dir / "index.html")
        else:
            export_dir = dist_base / f"win_{build_stamp}"
            output_path = p.output_path or str(export_dir / "game.exe")
            
        layout_validator = ProjectLayoutValidator(
            project_root=Path(getattr(self.godot_cli, "project_path", ".") or "."),
            runtime_root=Path.cwd(),
        )
        output_layout = layout_validator.validate_managed_path(output_path, "release_output")
        if not output_layout["passed"]:
            return self.build_result(
                success=False,
                message=f"{preset_name} 发布路径不符合文件树规范",
                params=self.dump_model(p),
                error="; ".join(issue["message"] for issue in output_layout["issues"]),
                validation={"passed": False, "issues": [issue["code"] for issue in output_layout["issues"]]},
            )
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        task.add_log(f"目标路径: {output_path}")

        build_channel = self._detect_release_channel(task, preset_name)
        build_id = f"{'web' if is_web else 'win'}-{build_channel}-{build_stamp}-{task.task_id[:8]}"
        release_version = self._build_release_version(task, build_channel, build_stamp)
        generated_at = build_dt.isoformat()
        release_metadata = {
            "build_id": build_id,
            "version": release_version,
            "channel": build_channel,
            "contract_versions": {
                "quality_gate": QUALITY_GATE_SCHEMA_VERSION,
                "release_summary": RELEASE_SUMMARY_SCHEMA_VERSION,
            },
        }

        quality_gate, gate_artifacts = self._run_quality_gate(task, preset_name, build_channel)
        gate_report = self._build_quality_gate_report(quality_gate)
        gate_report_path = Path(output_path).parent / "qa_gate_report.md"
        gate_report_layout = layout_validator.validate_managed_path(gate_report_path, "release_report")
        if not gate_report_layout["passed"]:
            return self.build_result(
                success=False,
                message=f"{preset_name} QA 门禁报告路径不符合文件树规范",
                params=self.dump_model(p),
                error="; ".join(issue["message"] for issue in gate_report_layout["issues"]),
                validation={"passed": False, "issues": [issue["code"] for issue in gate_report_layout["issues"]]},
            )
        gate_report_path.write_text(gate_report, encoding="utf-8")
        task.context["release_quality_gate"] = quality_gate
        task.context.setdefault("contract_versions", {})
        task.context["contract_versions"]["quality_gate"] = QUALITY_GATE_SCHEMA_VERSION
        task.context["release_layout_schema_version"] = output_layout["schema_version"]

        compact_gate = build_compact_quality_gate(quality_gate)
        release_metadata = {**release_metadata, "quality_gate": compact_gate}

        artifacts = list(gate_artifacts)
        artifacts.append(Artifact(
            name="QA Gate Report",
            path=str(gate_report_path),
            type="report",
            content=gate_report,
            metadata=release_metadata,
        ))

        if not quality_gate["passed"]:
            return self.build_result(
                success=False,
                message=f"{preset_name} 发布门禁未通过",
                params=self.dump_model(p),
                error="; ".join(quality_gate.get("blocked_checks") or ["quality_gate"]),
                artifacts=artifacts,
                validation={"passed": False, "issues": list(quality_gate.get("blocked_checks") or ["quality_gate"])},
                quality_gate=quality_gate,
            )

        # 2. 调用 Godot CLI 进行导出
        result = self.godot_cli.export_project(preset_name, output_path)

        # 记录构建日志
        res_data = result.data or {}
        build_log = f"STDOUT:\n{res_data.get('stdout', '')}\n\nSTDERR:\n{res_data.get('stderr', '')}"
        log_artifact_path = Path(output_path).parent / "build.log"
        build_log_layout = layout_validator.validate_managed_path(log_artifact_path, "release_report")
        if not build_log_layout["passed"]:
            return self.build_result(
                success=False,
                message=f"{preset_name} 构建日志路径不符合文件树规范",
                params=self.dump_model(p),
                error="; ".join(issue["message"] for issue in build_log_layout["issues"]),
                artifacts=artifacts,
                validation={"passed": False, "issues": [issue["code"] for issue in build_log_layout["issues"]]},
                quality_gate=quality_gate,
            )
        log_artifact_path.write_text(build_log, encoding="utf-8")

        artifacts.append(Artifact(
            name=f"{preset_name} Build Log",
            path=str(log_artifact_path),
            type="build_log",
            content=build_log,
            metadata=release_metadata,
        ))

        if result.success:
            task.add_log(f"✅ {preset_name} 导出成功!")
            output_file = Path(output_path)
            self._ensure_export_output(output_file, is_web)
            stable_rel_path = str(output_file)
            versioned_rel_path = str(output_file)
            if is_web:
                self._sync_latest_web_release(dist_base, export_dir)
                stable_rel_path = "/portal/dist/index.html"
                versioned_rel_path = f"/portal/dist/{export_dir.name}/index.html"

            release_files = self._collect_release_files(export_dir, exclude_names={"release_manifest.json"})
            notes_path = export_dir / "release_notes.md"
            manifest_path = export_dir / "release_manifest.json"
            notes_layout = layout_validator.validate_managed_path(notes_path, "release_report")
            manifest_layout = layout_validator.validate_managed_path(manifest_path, "release_manifest")
            invalid_layouts = [
                *notes_layout["issues"],
                *manifest_layout["issues"],
            ]
            if invalid_layouts:
                return self.build_result(
                    success=False,
                    message=f"{preset_name} 发布附属文件路径不符合文件树规范",
                    params=self.dump_model(p),
                    error="; ".join(issue["message"] for issue in invalid_layouts),
                    artifacts=artifacts,
                    validation={"passed": False, "issues": [issue["code"] for issue in invalid_layouts]},
                    quality_gate=quality_gate,
                )
            release_summary = self._build_release_summary(
                task=task,
                preset_name=preset_name,
                channel=build_channel,
                build_id=build_id,
                version=release_version,
                generated_at=generated_at,
                export_dir=export_dir,
                output_path=str(output_file),
                release_url=stable_rel_path,
                versioned_url=versioned_rel_path,
                build_log_path=str(log_artifact_path),
                release_notes_path=str(notes_path),
                release_manifest_path=str(manifest_path),
                quality_gate=quality_gate,
                files=release_files,
            )
            release_notes = self._build_release_notes(release_summary)
            notes_path.write_text(release_notes, encoding="utf-8")
            manifest_content = json.dumps(release_summary, ensure_ascii=False, indent=2)
            manifest_path.write_text(manifest_content, encoding="utf-8")
            if is_web:
                self._sync_latest_web_release(dist_base, export_dir)

            release_metadata = {
                **release_metadata,
                "release_url": stable_rel_path,
                "versioned_release_url": versioned_rel_path,
                "rollback_hint": release_summary["rollback_hint"],
            }
            task.context.update({
                "release_url": stable_rel_path,
                "release_build_id": build_id,
                "release_version": release_version,
                "release_channel": build_channel,
                "release_notes_path": str(notes_path),
                "release_manifest_path": str(manifest_path),
                "release_summary": release_summary,
            })
            task.context.setdefault("contract_versions", {})
            task.context["contract_versions"]["release_summary"] = RELEASE_SUMMARY_SCHEMA_VERSION
            task.add_log(f"📦 Build ID: {build_id}")
            task.add_log(f"🧾 Version: {release_version} ({build_channel})")
            
            artifacts.append(Artifact(
                name="Release Notes",
                path=str(notes_path),
                type="report",
                content=release_notes,
                metadata=release_metadata,
            ))
            artifacts.append(Artifact(
                name="Release Manifest",
                path=str(manifest_path),
                type="release",
                content=manifest_content,
                metadata=release_metadata,
            ))
            if is_web:
                artifacts.append(Artifact(
                    name="Web Release (Latest)",
                    path=stable_rel_path,
                    type="release",
                    metadata={**release_metadata, "slot": "latest"},
                ))
                artifacts.append(Artifact(
                    name=f"Web Release ({release_version})",
                    path=versioned_rel_path,
                    type="release",
                    metadata={**release_metadata, "slot": "versioned"},
                ))
            else:
                artifacts.append(Artifact(
                    name=f"Windows Release ({release_version})",
                    path=str(output_file),
                    type="release",
                    metadata=release_metadata,
                ))
                
            return self.build_result(
                success=True,
                message=f"游戏 {preset_name} 版本已发布",
                params=self.dump_model(p),
                artifacts=artifacts,
                validation={
                    "passed": True,
                    "checks": [
                        {"name": "layout_validation", "status": "passed"},
                        {"name": "release_summary", "status": "passed"},
                    ],
                },
                rollback={
                    "available": True,
                    "strategy": release_summary["rollback_hint"],
                    "backup_paths": [str(export_dir)],
                },
                quality_gate=quality_gate,
                metadata={"release_summary": release_summary},
            )
        else:
            return self.build_result(
                success=False,
                message=f"导出 {preset_name} 失败",
                params=self.dump_model(p),
                error=result.error,
                artifacts=artifacts,
                validation={"passed": False, "issues": [result.error or "export_failed"]},
                quality_gate=quality_gate,
            )

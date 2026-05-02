"""
Reusable performance profiling and baseline analysis helpers.
"""

from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..contracts import normalize_performance_summary


DEFAULT_PERFORMANCE_BASELINE_DIR = "tests/baselines/performance"
DEFAULT_PERFORMANCE_PROFILE_DIR = "logs/test_artifacts"

_METRIC_ALIASES = {
    "draw_calls": "draw_call_count",
    "draw_call": "draw_call_count",
    "draw_call_budget": "draw_call_count",
    "texture_budget_mb": "texture_memory_mb",
    "texture_mem_mb": "texture_memory_mb",
    "texture_budget": "texture_memory_mb",
    "frame_spike": "frame_spike_ms",
    "memory_mb": "memory_peak_mb",
}

_BUDGET_ALIASES = {
    "draw_call_budget": "max_draw_call_count",
    "draw_calls_budget": "max_draw_call_count",
    "node_budget": "max_node_count",
    "texture_budget_mb": "max_texture_memory_mb",
    "texture_budget": "max_texture_memory_mb",
    "frame_spike_budget": "max_frame_spike_ms",
    "screenshot_diff_budget": "max_screenshot_diff_ratio",
    "screenshot_budget": "max_screenshot_diff_ratio",
    "memory_growth_budget": "max_memory_growth_mb",
    "memory_trend_budget": "max_memory_growth_mb",
}

_EXTRA_BUDGET_KEYS = {
    "max_memory_growth_mb",
    "max_memory_avg_delta_mb",
    "max_memory_peak_delta_mb",
}

_METRIC_SPECS: Dict[str, Dict[str, Any]] = {
    "scene_load_ms": {
        "check_name": "performance_budget",
        "budget_key": "max_scene_load_ms",
        "regression_check": "scene_load_regression",
        "regression_budget_key": "scene_load_regression_ratio",
        "compare": "max",
        "label": "场景加载",
        "unit": "ms",
        "precision": 0,
        "default_regression_ratio": 0.25,
    },
    "fps": {
        "check_name": "fps_budget",
        "budget_key": "min_fps",
        "regression_check": "fps_regression",
        "regression_budget_key": "fps_drop_ratio",
        "compare": "min",
        "label": "FPS",
        "unit": "",
        "precision": 2,
        "default_regression_ratio": 0.10,
    },
    "memory_peak_mb": {
        "check_name": "memory_peak_budget",
        "budget_key": "max_memory_peak_mb",
        "regression_check": "memory_peak_regression",
        "regression_budget_key": "memory_peak_regression_ratio",
        "compare": "max",
        "label": "内存峰值",
        "unit": "MB",
        "precision": 2,
        "default_regression_ratio": 0.20,
    },
    "draw_call_count": {
        "check_name": "draw_call_budget",
        "budget_key": "max_draw_call_count",
        "regression_check": "draw_call_regression",
        "regression_budget_key": "draw_call_regression_ratio",
        "compare": "max",
        "label": "Draw Call",
        "unit": "",
        "precision": 0,
        "default_regression_ratio": 0.20,
    },
    "node_count": {
        "check_name": "node_count_budget",
        "budget_key": "max_node_count",
        "regression_check": "node_count_regression",
        "regression_budget_key": "node_count_regression_ratio",
        "compare": "max",
        "label": "节点数",
        "unit": "",
        "precision": 0,
        "default_regression_ratio": 0.20,
    },
    "texture_memory_mb": {
        "check_name": "texture_memory_budget",
        "budget_key": "max_texture_memory_mb",
        "regression_check": "texture_memory_regression",
        "regression_budget_key": "texture_memory_regression_ratio",
        "compare": "max",
        "label": "纹理内存",
        "unit": "MB",
        "precision": 2,
        "default_regression_ratio": 0.20,
    },
    "frame_spike_ms": {
        "check_name": "frame_spike_budget",
        "budget_key": "max_frame_spike_ms",
        "regression_check": "frame_spike_regression",
        "regression_budget_key": "frame_spike_regression_ratio",
        "compare": "max",
        "label": "帧尖峰",
        "unit": "ms",
        "precision": 2,
        "default_regression_ratio": 0.25,
    },
    "screenshot_diff_ratio": {
        "check_name": "screenshot_diff",
        "budget_key": "max_screenshot_diff_ratio",
        "regression_check": "screenshot_diff_regression",
        "regression_budget_key": "screenshot_diff_regression_ratio",
        "compare": "max",
        "label": "截图 diff",
        "unit": "",
        "precision": 4,
        "default_regression_ratio": 0.30,
    },
}


def _sanitize_stem(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_]+", "_", str(value or "").strip())
    cleaned = re.sub(r"_+", "_", cleaned).strip("_")
    return cleaned or "project_default"


def _to_float(value: Any) -> Optional[float]:
    if value in (None, "", False):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _round_value(value: float, precision: int) -> Any:
    rounded = round(float(value), precision)
    if precision == 0:
        return int(round(rounded))
    return rounded


class GamePerformanceAnalyzer:
    def __init__(self, project_root: str | Path, runtime_root: Optional[str | Path] = None):
        self.project_root = Path(project_root).resolve()
        self.runtime_root = Path(runtime_root or Path.cwd()).resolve()

    def resolve_baseline_path(self, raw_path: Optional[str] = None, scene_path: Optional[str] = None) -> Path:
        if raw_path:
            return self._resolve_any_path(raw_path)
        if not str(scene_path or "").strip():
            return (self.runtime_root / DEFAULT_PERFORMANCE_BASELINE_DIR / "_inline_profile_performance.json").resolve()
        stem = self._scene_stem(scene_path)
        return (self.runtime_root / DEFAULT_PERFORMANCE_BASELINE_DIR / f"{stem}_performance.json").resolve()

    def resolve_profile_path(self, raw_path: Optional[str] = None) -> Optional[Path]:
        if not raw_path:
            return None
        return self._resolve_any_path(raw_path)

    def build_profile_snapshot_path(self, scene_path: Optional[str] = None) -> Path:
        stem = self._scene_stem(scene_path)
        return (
            self.runtime_root
            / DEFAULT_PERFORMANCE_PROFILE_DIR
            / f"performance_profile_{stem}_{int(time.time())}.json"
        ).resolve()

    def _should_load_baseline_payload(
        self,
        *,
        baseline_path: Optional[str] = None,
        scene_path: Optional[str] = None,
        baseline_metrics: Optional[Dict[str, Any]] = None,
    ) -> bool:
        if baseline_metrics:
            return False
        if str(baseline_path or "").strip():
            return True
        if str(scene_path or "").strip():
            return True
        return False

    def snapshot(
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
        resolved_baseline_path = self.resolve_baseline_path(baseline_path, scene_path)
        resolved_profile_path = self.resolve_profile_path(profile_path)

        baseline_payload = (
            self._load_payload(resolved_baseline_path)
            if self._should_load_baseline_payload(
                baseline_path=baseline_path,
                scene_path=scene_path,
                baseline_metrics=baseline_metrics,
            ) and resolved_baseline_path.exists()
            else {}
        )
        profile_payload = self._load_payload(resolved_profile_path) if resolved_profile_path and resolved_profile_path.exists() else {}
        resolved_baseline_metrics = self._normalize_metrics(baseline_metrics or baseline_payload)
        resolved_profile_metrics = self._normalize_metrics(profile_metrics or profile_payload)
        resolved_baseline_memory_trend = self._normalize_memory_trend(baseline_metrics or baseline_payload)
        resolved_frame_breakdown = self._normalize_frame_breakdown(profile_metrics or profile_payload)
        resolved_memory_trend = self._normalize_memory_trend(profile_metrics or profile_payload)
        resolved_budgets = self._normalize_budgets({
            **dict(baseline_payload.get("budgets") or {}),
            **dict(profile_payload.get("budgets") or {}),
            **dict(budget_overrides or {}),
        })

        summary = None
        if resolved_profile_metrics or screenshot_baseline_path or screenshot_candidate_path:
            summary = self.analyze(
                scene_path=scene_path,
                baseline_path=str(resolved_baseline_path),
                profile_path=str(resolved_profile_path) if resolved_profile_path else None,
                screenshot_baseline_path=screenshot_baseline_path,
                screenshot_candidate_path=screenshot_candidate_path,
                baseline_metrics={
                    **resolved_baseline_metrics,
                    "memory_trend": resolved_baseline_memory_trend,
                },
                profile_metrics={
                    **resolved_profile_metrics,
                    "frame_breakdown": resolved_frame_breakdown,
                    "memory_trend": resolved_memory_trend,
                },
                budget_overrides=resolved_budgets,
            )

        return {
            "scene_path": str(scene_path or "").strip(),
            "baseline_path": str(resolved_baseline_path),
            "baseline_exists": resolved_baseline_path.exists(),
            "baseline_metrics": resolved_baseline_metrics,
            "profile_path": str(resolved_profile_path) if resolved_profile_path else "",
            "profile_exists": bool(resolved_profile_path and resolved_profile_path.exists()),
            "profile_metrics": resolved_profile_metrics,
            "budgets": resolved_budgets,
            "summary": summary,
        }

    def analyze(
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
        resolved_baseline_path = self.resolve_baseline_path(baseline_path, scene_path)
        resolved_profile_path = self.resolve_profile_path(profile_path)
        baseline_payload = (
            self._load_payload(resolved_baseline_path)
            if self._should_load_baseline_payload(
                baseline_path=baseline_path,
                scene_path=scene_path,
                baseline_metrics=baseline_metrics,
            ) and resolved_baseline_path.exists()
            else {}
        )
        profile_payload = self._load_payload(resolved_profile_path) if resolved_profile_path and resolved_profile_path.exists() else {}

        resolved_baseline_metrics = self._normalize_metrics(baseline_metrics or baseline_payload)
        resolved_profile_metrics = self._normalize_metrics(profile_metrics or profile_payload)
        baseline_memory_trend = self._normalize_memory_trend(baseline_metrics or baseline_payload)
        frame_breakdown = self._normalize_frame_breakdown(profile_metrics or profile_payload)
        memory_trend = self._normalize_memory_trend(profile_metrics or profile_payload)
        resolved_budgets = self._normalize_budgets({
            **dict(baseline_payload.get("budgets") or {}),
            **dict(profile_payload.get("budgets") or {}),
            **dict(budget_overrides or {}),
        })
        screenshot_compare = self.compare_screenshot_baselines(
            baseline_path=screenshot_baseline_path,
            candidate_path=screenshot_candidate_path,
            max_diff_ratio=resolved_budgets.get("max_screenshot_diff_ratio"),
        ) if screenshot_baseline_path or screenshot_candidate_path else {}
        if screenshot_compare.get("diff_ratio") is not None:
            resolved_profile_metrics["screenshot_diff_ratio"] = float(screenshot_compare["diff_ratio"])
        memory_regression = self.track_memory_regressions(
            baseline_trend=baseline_memory_trend,
            candidate_trend=memory_trend,
            budgets=resolved_budgets,
        )

        checks: List[Dict[str, Any]] = []
        issues: List[str] = []
        warnings: List[str] = []
        notes: List[str] = []

        if not resolved_profile_metrics:
            checks.append({
                "name": "performance_inputs",
                "status": "blocked",
                "message": "未提供性能 profile 指标，无法执行分析",
            })
            issues.append("未提供性能 profile 指标")
            return normalize_performance_summary({
                "passed": False,
                "scene_path": str(scene_path or "").strip(),
                "baseline_path": str(resolved_baseline_path),
                "profile_path": str(resolved_profile_path) if resolved_profile_path else "",
                "issues": issues,
                "warnings": warnings,
                "notes": notes,
                "checks": checks,
                "metrics": {},
                "budgets": resolved_budgets,
                "baselines": [
                    {
                        "scene_path": str(scene_path or "").strip(),
                        "baseline_path": str(resolved_baseline_path),
                        "profile_path": str(resolved_profile_path) if resolved_profile_path else "",
                    }
                ],
            })

        checks.append({
            "name": "performance_inputs",
            "status": "passed",
            "message": (
                "已加载性能 profile 和 baseline"
                if resolved_baseline_metrics
                else "已加载性能 profile，未提供 baseline"
            ),
        })
        if screenshot_compare:
            checks.append({
                "name": "screenshot_baseline_compare",
                "status": screenshot_compare["status"],
                "message": screenshot_compare["message"],
                "baseline_path": screenshot_compare.get("baseline_path", ""),
                "candidate_path": screenshot_compare.get("candidate_path", ""),
                "diff_ratio": screenshot_compare.get("diff_ratio"),
                "max_diff_ratio": screenshot_compare.get("max_diff_ratio"),
            })
            if screenshot_compare["status"] == "blocked":
                issues.append(screenshot_compare["message"])
            elif screenshot_compare["status"] == "warning":
                warnings.append(screenshot_compare["message"])
            else:
                notes.append(screenshot_compare["message"])

        metrics: Dict[str, Any] = dict(resolved_profile_metrics)
        if frame_breakdown:
            top_stage = max(frame_breakdown, key=lambda item: float(item.get("ms") or 0.0))
            metrics["top_frame_stage"] = str(top_stage.get("stage") or "")
            metrics["top_frame_stage_ms"] = round(float(top_stage.get("ms") or 0.0), 4)
            metrics["frame_total_ms"] = round(sum(float(item.get("ms") or 0.0) for item in frame_breakdown), 4)
            checks.append({
                "name": "frame_breakdown_profile",
                "status": "passed",
                "message": f"已采集 frame breakdown，top stage={metrics['top_frame_stage']} {metrics['top_frame_stage_ms']}ms",
            })
        if memory_trend.get("sample_count"):
            metrics["memory_growth_mb"] = round(float(memory_trend.get("growth_mb") or 0.0), 4)
            checks.append({
                "name": "memory_trend_profile",
                "status": "passed",
                "message": f"已采集 memory trend，growth={metrics['memory_growth_mb']}MB",
            })
        if memory_regression:
            checks.append({
                "name": "memory_regression_trend",
                "status": memory_regression["status"],
                "message": memory_regression["message"],
                "growth_delta_mb": memory_regression.get("growth_delta_mb"),
                "peak_delta_mb": memory_regression.get("peak_delta_mb"),
                "avg_delta_mb": memory_regression.get("avg_delta_mb"),
            })
            metrics["memory_growth_delta_mb"] = memory_regression["growth_delta_mb"]
            metrics["memory_peak_delta_mb"] = memory_regression["peak_delta_mb"]
            metrics["memory_avg_delta_mb"] = memory_regression["avg_delta_mb"]
            if memory_regression["status"] == "blocked":
                issues.append(memory_regression["message"])
            elif memory_regression["status"] == "warning":
                warnings.append(memory_regression["message"])
            else:
                notes.append(memory_regression["message"])
        if resolved_baseline_metrics:
            for metric_name, value in resolved_baseline_metrics.items():
                metrics[f"baseline_{metric_name}"] = value
                if metric_name in resolved_profile_metrics:
                    delta = float(resolved_profile_metrics[metric_name]) - float(value)
                    precision = int(_METRIC_SPECS[metric_name]["precision"])
                    metrics[f"{metric_name}_delta"] = _round_value(delta, precision)

        for metric_name, spec in _METRIC_SPECS.items():
            measured = _to_float(resolved_profile_metrics.get(metric_name))
            baseline_value = _to_float(resolved_baseline_metrics.get(metric_name))
            budget_value = _to_float(resolved_budgets.get(spec["budget_key"]))

            if measured is None and budget_value is None and baseline_value is None:
                continue

            budget_check = self._build_budget_check(
                metric_name=metric_name,
                measured=measured,
                budget_value=budget_value,
                spec=spec,
            )
            checks.append(budget_check)
            if budget_check["status"] == "blocked":
                issues.append(budget_check["message"])
            elif budget_check["status"] == "warning":
                warnings.append(budget_check["message"])
            elif budget_check["status"] == "skipped":
                notes.append(budget_check["message"])

            regression_check = self._build_regression_check(
                metric_name=metric_name,
                measured=measured,
                baseline_value=baseline_value,
                spec=spec,
                budgets=resolved_budgets,
            )
            if regression_check:
                checks.append(regression_check)
                if regression_check["status"] == "blocked":
                    issues.append(regression_check["message"])
                elif regression_check["status"] == "warning":
                    warnings.append(regression_check["message"])
                else:
                    notes.append(regression_check["message"])

        notes.append(f"Captured metrics: {', '.join(sorted(resolved_profile_metrics.keys()))}")
        if resolved_baseline_metrics:
            notes.append(f"Baseline metrics: {', '.join(sorted(resolved_baseline_metrics.keys()))}")
        if frame_breakdown:
            notes.append(f"Frame breakdown stages: {', '.join(item['stage'] for item in frame_breakdown)}")
        if memory_trend.get("sample_count"):
            notes.append(f"Memory trend: {memory_trend['trend_status']} growth={memory_trend['growth_mb']}MB")
        if memory_regression:
            notes.append(
                "Memory regression: "
                f"growth_delta={memory_regression['growth_delta_mb']}MB"
                f" / budget={memory_regression['max_growth_delta_mb']}MB"
            )
        if screenshot_compare:
            notes.append(
                "Screenshot compare: "
                f"{screenshot_compare.get('diff_ratio', '-')}"
                f" / budget={screenshot_compare.get('max_diff_ratio', '-')}"
            )

        return normalize_performance_summary({
            "passed": len(issues) == 0,
            "scene_path": str(scene_path or "").strip(),
            "baseline_path": str(resolved_baseline_path),
            "profile_path": str(resolved_profile_path) if resolved_profile_path else "",
            "issues": issues,
            "warnings": warnings,
            "notes": notes,
            "checks": checks,
            "metrics": metrics,
            "budgets": resolved_budgets,
            "frame_breakdown": frame_breakdown,
            "memory_trend": memory_trend,
            "memory_regression": memory_regression,
            "screenshot_compare": screenshot_compare,
            "baselines": [
                {
                    "scene_path": str(scene_path or "").strip(),
                    "baseline_path": str(resolved_baseline_path),
                    "profile_path": str(resolved_profile_path) if resolved_profile_path else "",
                }
            ],
        })

    def compare_screenshot_baselines(
        self,
        *,
        baseline_path: Optional[str],
        candidate_path: Optional[str],
        max_diff_ratio: Any = None,
    ) -> Dict[str, Any]:
        baseline = self._resolve_any_path(baseline_path or "") if baseline_path else None
        candidate = self._resolve_any_path(candidate_path or "") if candidate_path else None
        budget = _to_float(max_diff_ratio)
        if budget is None:
            budget = 0.035

        missing = []
        if baseline is None or not baseline.exists():
            missing.append(f"missing screenshot baseline: {baseline_path or '-'}")
        if candidate is None or not candidate.exists():
            missing.append(f"missing screenshot candidate: {candidate_path or '-'}")
        if missing:
            return {
                "status": "blocked",
                "message": "; ".join(missing),
                "baseline_path": str(baseline or ""),
                "candidate_path": str(candidate or ""),
                "baseline_exists": bool(baseline and baseline.exists()),
                "candidate_exists": bool(candidate and candidate.exists()),
                "diff_ratio": None,
                "max_diff_ratio": round(float(budget), 4),
            }

        baseline_bytes = baseline.read_bytes()
        candidate_bytes = candidate.read_bytes()
        denominator = max(len(baseline_bytes), len(candidate_bytes), 1)
        overlap = min(len(baseline_bytes), len(candidate_bytes))
        mismatch_count = sum(
            1 for index in range(overlap)
            if baseline_bytes[index] != candidate_bytes[index]
        ) + abs(len(baseline_bytes) - len(candidate_bytes))
        diff_ratio = round(mismatch_count / denominator, 4)
        status = "passed" if diff_ratio <= float(budget) else "blocked"
        return {
            "status": status,
            "message": (
                f"截图 diff {diff_ratio} / 预算 {round(float(budget), 4)}"
                if status == "passed"
                else f"截图 diff {diff_ratio} 超出预算 {round(float(budget), 4)}"
            ),
            "baseline_path": str(baseline),
            "candidate_path": str(candidate),
            "baseline_exists": True,
            "candidate_exists": True,
            "baseline_size_bytes": len(baseline_bytes),
            "candidate_size_bytes": len(candidate_bytes),
            "mismatch_count": mismatch_count,
            "diff_ratio": diff_ratio,
            "max_diff_ratio": round(float(budget), 4),
        }

    def track_memory_regressions(
        self,
        *,
        baseline_trend: Dict[str, Any],
        candidate_trend: Dict[str, Any],
        budgets: Dict[str, Any],
    ) -> Dict[str, Any]:
        baseline_count = int(baseline_trend.get("sample_count") or 0)
        candidate_count = int(candidate_trend.get("sample_count") or 0)
        if not baseline_count or not candidate_count:
            return {}

        growth_delta = round(float(candidate_trend.get("growth_mb") or 0.0) - float(baseline_trend.get("growth_mb") or 0.0), 4)
        peak_delta = round(float(candidate_trend.get("max_mb") or 0.0) - float(baseline_trend.get("max_mb") or 0.0), 4)
        avg_delta = round(float(candidate_trend.get("avg_mb") or 0.0) - float(baseline_trend.get("avg_mb") or 0.0), 4)
        max_growth_delta = _to_float(budgets.get("max_memory_growth_mb"))
        if max_growth_delta is None:
            max_growth_delta = 8.0
        max_peak_delta = _to_float(budgets.get("max_memory_peak_delta_mb"))
        if max_peak_delta is None:
            max_peak_delta = max(float(max_growth_delta) * 2.0, 16.0)
        max_avg_delta = _to_float(budgets.get("max_memory_avg_delta_mb"))
        if max_avg_delta is None:
            max_avg_delta = max(float(max_growth_delta), 8.0)

        blocked = (
            growth_delta > float(max_growth_delta)
            or peak_delta > float(max_peak_delta)
            or avg_delta > float(max_avg_delta)
        )
        status = "blocked" if blocked else "passed"
        message = (
            "内存趋势回归 "
            f"growth_delta={growth_delta}MB / budget={round(float(max_growth_delta), 4)}MB, "
            f"peak_delta={peak_delta}MB / budget={round(float(max_peak_delta), 4)}MB, "
            f"avg_delta={avg_delta}MB / budget={round(float(max_avg_delta), 4)}MB"
        )
        return {
            "status": status,
            "message": message,
            "baseline": dict(baseline_trend),
            "candidate": dict(candidate_trend),
            "baseline_sample_count": baseline_count,
            "candidate_sample_count": candidate_count,
            "growth_delta_mb": growth_delta,
            "peak_delta_mb": peak_delta,
            "avg_delta_mb": avg_delta,
            "max_growth_delta_mb": round(float(max_growth_delta), 4),
            "max_peak_delta_mb": round(float(max_peak_delta), 4),
            "max_avg_delta_mb": round(float(max_avg_delta), 4),
        }

    def _build_budget_check(
        self,
        *,
        metric_name: str,
        measured: Optional[float],
        budget_value: Optional[float],
        spec: Dict[str, Any],
    ) -> Dict[str, Any]:
        check_name = str(spec["check_name"])
        label = str(spec["label"])
        budget_key = str(spec["budget_key"])
        if budget_value is None:
            if measured is None:
                return {
                    "name": check_name,
                    "status": "skipped",
                    "message": f"{label} 未采集，且未配置 {budget_key}",
                }
            return {
                "name": check_name,
                "status": "skipped",
                "message": f"{label} {self._format_value(measured, spec)}，未配置 {budget_key}",
            }
        if measured is None:
            return {
                "name": check_name,
                "status": "blocked",
                "message": f"{label} 缺少采样值，无法校验 {budget_key}",
            }

        compare = str(spec["compare"])
        passed = measured <= budget_value if compare == "max" else measured >= budget_value
        if compare == "max":
            message = (
                f"{label} {self._format_value(measured, spec)} / 预算 {self._format_value(budget_value, spec)}"
                if passed
                else f"{label} {self._format_value(measured, spec)} 超出预算 {self._format_value(budget_value, spec)}"
            )
        else:
            message = (
                f"{label} {self._format_value(measured, spec)} / 下限 {self._format_value(budget_value, spec)}"
                if passed
                else f"{label} {self._format_value(measured, spec)} 低于下限 {self._format_value(budget_value, spec)}"
            )
        return {
            "name": check_name,
            "status": "passed" if passed else "blocked",
            "message": message,
            "metric_name": metric_name,
            "measured": _round_value(measured, int(spec["precision"])),
            "budget": _round_value(budget_value, int(spec["precision"])),
        }

    def _build_regression_check(
        self,
        *,
        metric_name: str,
        measured: Optional[float],
        baseline_value: Optional[float],
        spec: Dict[str, Any],
        budgets: Dict[str, Any],
    ) -> Optional[Dict[str, Any]]:
        if measured is None or baseline_value is None:
            return None
        baseline_denominator = max(abs(float(baseline_value)), 1.0)
        compare = str(spec["compare"])
        if compare == "max":
            regression_ratio = (float(measured) - float(baseline_value)) / baseline_denominator
        else:
            regression_ratio = (float(baseline_value) - float(measured)) / baseline_denominator

        allowed_ratio = _to_float(budgets.get(spec["regression_budget_key"]))
        if allowed_ratio is None:
            allowed_ratio = float(spec["default_regression_ratio"])

        status = "passed" if regression_ratio <= allowed_ratio else "blocked"
        direction = "回退" if regression_ratio > 0 else "改善"
        message = (
            f"{spec['label']} 相比基线{direction} {abs(regression_ratio) * 100:.1f}% "
            f"(当前 {self._format_value(measured, spec)} / 基线 {self._format_value(baseline_value, spec)} / 阈值 {allowed_ratio * 100:.1f}%)"
        )
        return {
            "name": str(spec["regression_check"]),
            "status": status,
            "message": message,
            "metric_name": metric_name,
            "baseline": _round_value(baseline_value, int(spec["precision"])),
            "measured": _round_value(measured, int(spec["precision"])),
            "regression_ratio": round(regression_ratio, 4),
            "allowed_ratio": round(allowed_ratio, 4),
        }

    def _normalize_metrics(self, source: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        payload = dict(source or {})
        raw_metrics = dict(payload.get("metrics") or payload)
        result: Dict[str, Any] = {}
        for key, value in raw_metrics.items():
            canonical = _METRIC_ALIASES.get(str(key).strip(), str(key).strip())
            spec = _METRIC_SPECS.get(canonical)
            if spec is None:
                continue
            number = _to_float(value)
            if number is None:
                continue
            result[canonical] = _round_value(number, int(spec["precision"]))
        return result

    def _normalize_frame_breakdown(self, source: Optional[Dict[str, Any]]) -> List[Dict[str, Any]]:
        payload = dict(source or {})
        raw_metrics = {**payload, **dict(payload.get("metrics") or {})}
        raw_breakdown = raw_metrics.get("frame_breakdown")
        rows: List[Dict[str, Any]] = []
        if isinstance(raw_breakdown, list):
            for item in raw_breakdown:
                if not isinstance(item, dict):
                    continue
                stage = str(item.get("stage") or "").strip()
                ms = _to_float(item.get("ms"))
                budget_ms = _to_float(item.get("budget_ms"))
                if not stage or ms is None:
                    continue
                rows.append({
                    "stage": stage,
                    "ms": round(ms, 4),
                    "budget_ms": round(budget_ms, 4) if budget_ms is not None else None,
                })
            return rows

        alias_map = {
            "cpu_ms": "cpu",
            "render_ms": "render",
            "script_ms": "script",
            "physics_ms": "physics",
            "gpu_ms": "gpu",
        }
        for key, stage in alias_map.items():
            ms = _to_float(raw_metrics.get(key))
            if ms is None:
                continue
            rows.append({"stage": stage, "ms": round(ms, 4), "budget_ms": None})
        return rows

    def _normalize_memory_trend(self, source: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        payload = dict(source or {})
        raw_metrics = {**payload, **dict(payload.get("metrics") or {})}
        raw_trend = raw_metrics.get("memory_trend")
        if isinstance(raw_trend, dict):
            return {
                "sample_count": int(raw_trend.get("sample_count") or 0),
                "min_mb": round(float(raw_trend.get("min_mb") or 0.0), 4),
                "max_mb": round(float(raw_trend.get("max_mb") or 0.0), 4),
                "avg_mb": round(float(raw_trend.get("avg_mb") or 0.0), 4),
                "growth_mb": round(float(raw_trend.get("growth_mb") or 0.0), 4),
                "trend_status": str(raw_trend.get("trend_status") or "").strip() or "stable",
            }
        raw_samples = raw_metrics.get("memory_samples_mb") or raw_metrics.get("memory_timeline_mb") or raw_metrics.get("memory_series_mb")
        if not isinstance(raw_samples, list):
            return {
                "sample_count": 0,
                "min_mb": 0.0,
                "max_mb": 0.0,
                "avg_mb": 0.0,
                "growth_mb": 0.0,
                "trend_status": "stable",
            }
        samples = [float(item) for item in raw_samples if _to_float(item) is not None]
        if not samples:
            return {
                "sample_count": 0,
                "min_mb": 0.0,
                "max_mb": 0.0,
                "avg_mb": 0.0,
                "growth_mb": 0.0,
                "trend_status": "stable",
            }
        growth = float(samples[-1]) - float(samples[0])
        if growth > 8:
            trend_status = "growing"
        elif growth < -8:
            trend_status = "declining"
        else:
            trend_status = "stable"
        return {
            "sample_count": len(samples),
            "min_mb": round(min(samples), 4),
            "max_mb": round(max(samples), 4),
            "avg_mb": round(sum(samples) / len(samples), 4),
            "growth_mb": round(growth, 4),
            "trend_status": trend_status,
        }

    def _normalize_budgets(self, source: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        payload = dict(source or {})
        result: Dict[str, Any] = {}
        known_keys = {spec["budget_key"] for spec in _METRIC_SPECS.values()} | set(_EXTRA_BUDGET_KEYS)
        regression_keys = {spec["regression_budget_key"] for spec in _METRIC_SPECS.values()}
        for key, value in payload.items():
            canonical = _BUDGET_ALIASES.get(str(key).strip(), str(key).strip())
            if canonical not in known_keys and canonical not in regression_keys:
                continue
            number = _to_float(value)
            if number is None:
                continue
            result[canonical] = round(number, 4)
        return result

    def _load_payload(self, path: Path) -> Dict[str, Any]:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return {}
        return dict(payload) if isinstance(payload, dict) else {}

    def _resolve_any_path(self, raw_path: str) -> Path:
        normalized = str(raw_path or "").replace("\\", "/").strip()
        if normalized.startswith("res://"):
            return (self.project_root / normalized.replace("res://", "", 1)).resolve()
        candidate = Path(normalized)
        if candidate.is_absolute():
            return candidate.resolve()
        return (self.runtime_root / candidate).resolve()

    def _scene_stem(self, scene_path: Optional[str]) -> str:
        normalized = str(scene_path or "").strip()
        if normalized.startswith("res://"):
            normalized = normalized.replace("res://", "", 1)
        stem = Path(normalized).stem if normalized else "project_default"
        return _sanitize_stem(stem)

    def _format_value(self, value: float, spec: Dict[str, Any]) -> str:
        rounded = _round_value(value, int(spec["precision"]))
        unit = str(spec["unit"])
        return f"{rounded}{unit}"


def build_performance_report(summary: Dict[str, Any]) -> str:
    normalized = normalize_performance_summary(summary)
    lines = [
        "# Performance Analysis Report",
        "",
        f"- Passed: {normalized['passed']}",
        f"- Scene Path: {normalized['scene_path'] or '-'}",
        f"- Baseline Path: {normalized['baseline_path'] or '-'}",
        f"- Profile Path: {normalized['profile_path'] or '-'}",
        "",
        "## Notes",
        "",
    ]
    lines.extend([f"- {item}" for item in normalized["notes"]] or ["- none"])
    lines.extend(["", "## Checks", ""])
    lines.extend([f"- {item['name']}: {item['status']} - {item['message']}" for item in normalized["checks"]] or ["- none"])
    lines.extend(["", "## Issues", ""])
    lines.extend([f"- {item}" for item in normalized["issues"]] or ["- none"])
    lines.extend(["", "## Warnings", ""])
    lines.extend([f"- {item}" for item in normalized["warnings"]] or ["- none"])
    lines.extend(["", "## Metrics", ""])
    for key in sorted(normalized["metrics"]):
        lines.append(f"- {key}: {normalized['metrics'][key]}")
    if not normalized["metrics"]:
        lines.append("- none")
    lines.extend(["", "## Budgets", ""])
    for key in sorted(normalized["budgets"]):
        lines.append(f"- {key}: {normalized['budgets'][key]}")
    if not normalized["budgets"]:
        lines.append("- none")
    lines.extend(["", "## Frame Breakdown", ""])
    lines.extend([
        f"- {item['stage']}: {item['ms']}ms / budget={item['budget_ms'] if item['budget_ms'] is not None else '-'}"
        for item in normalized.get("frame_breakdown", [])
    ] or ["- none"])
    memory_trend = dict(normalized.get("memory_trend") or {})
    lines.extend(["", "## Memory Trend", ""])
    lines.extend([
        f"- sample_count: {memory_trend.get('sample_count', 0)}",
        f"- min_mb: {memory_trend.get('min_mb', 0)}",
        f"- max_mb: {memory_trend.get('max_mb', 0)}",
        f"- avg_mb: {memory_trend.get('avg_mb', 0)}",
        f"- growth_mb: {memory_trend.get('growth_mb', 0)}",
        f"- trend_status: {memory_trend.get('trend_status') or '-'}",
    ])
    memory_regression = dict(normalized.get("memory_regression") or {})
    lines.extend(["", "## Memory Regression", ""])
    if memory_regression:
        lines.extend([
            f"- status: {memory_regression.get('status') or '-'}",
            f"- growth_delta_mb: {memory_regression.get('growth_delta_mb') if memory_regression.get('growth_delta_mb') is not None else '-'}",
            f"- max_growth_delta_mb: {memory_regression.get('max_growth_delta_mb') if memory_regression.get('max_growth_delta_mb') is not None else '-'}",
            f"- peak_delta_mb: {memory_regression.get('peak_delta_mb') if memory_regression.get('peak_delta_mb') is not None else '-'}",
            f"- avg_delta_mb: {memory_regression.get('avg_delta_mb') if memory_regression.get('avg_delta_mb') is not None else '-'}",
        ])
    else:
        lines.append("- none")
    screenshot_compare = dict(normalized.get("screenshot_compare") or {})
    lines.extend(["", "## Screenshot Compare", ""])
    if screenshot_compare:
        lines.extend([
            f"- status: {screenshot_compare.get('status') or '-'}",
            f"- diff_ratio: {screenshot_compare.get('diff_ratio') if screenshot_compare.get('diff_ratio') is not None else '-'}",
            f"- max_diff_ratio: {screenshot_compare.get('max_diff_ratio') if screenshot_compare.get('max_diff_ratio') is not None else '-'}",
            f"- baseline_path: {screenshot_compare.get('baseline_path') or '-'}",
            f"- candidate_path: {screenshot_compare.get('candidate_path') or '-'}",
        ])
    else:
        lines.append("- none")
    lines.append("")
    return "\n".join(lines)

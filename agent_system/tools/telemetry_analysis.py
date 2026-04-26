"""
Reusable telemetry catalog and session analysis helpers.
"""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from ..contracts import normalize_telemetry_summary


DEFAULT_TELEMETRY_CATALOG_PATH = "telemetry/event_catalog.json"
DEFAULT_TELEMETRY_SESSIONS_DIR = "telemetry/sessions"
TELEMETRY_ALLOWED_CATEGORIES = {"session", "gameplay", "economy", "combat", "ui", "error", "system"}
FORBIDDEN_PII_KEYS = {"email", "phone", "address", "full_name", "password", "token"}
ACTOR_ID_KEYS = ("player_id", "user_id", "account_id", "anonymous_id")
CRASH_TYPE_KEYS = ("crash_type", "error_type", "exception_type", "error_code")
CRASH_SIGNATURE_KEYS = ("stack_hash", "stack_signature", "crash_signature", "error_code", "crash_type")
RETENTION_WINDOWS = (1, 3, 7)
DEFAULT_FUNNEL_SEQUENCE = ("session_start", "level_start", "level_complete", "session_end")


def _read_json_file(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _read_jsonl_file(path: Path) -> List[Dict[str, Any]]:
    events: List[Dict[str, Any]] = []
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        payload = json.loads(line)
        if isinstance(payload, dict):
            events.append(dict(payload))
    return events


def _clean_event_name(value: Any) -> str:
    return str(value or "").strip().lower()


class TelemetryAnalyzer:
    def __init__(self, project_root: str | Path):
        self.project_root = Path(project_root).resolve()

    def snapshot(
        self,
        *,
        catalog_path: Optional[str] = None,
        session_path: Optional[str] = None,
        catalog_entries: Optional[List[Dict[str, Any]]] = None,
        events: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        resolved_catalog_path = self._resolve_catalog_path(catalog_path)
        resolved_session_path = self._resolve_session_path(session_path)
        resolved_catalog_entries = self._load_catalog_entries(resolved_catalog_path, catalog_entries)
        resolved_events = self._load_events(resolved_session_path, events)
        session_summaries = self._summarize_sessions(resolved_events)
        return {
            "catalog_path": str(resolved_catalog_path),
            "catalog_exists": resolved_catalog_path.exists(),
            "catalog_entries": resolved_catalog_entries,
            "catalog_entry_count": len(resolved_catalog_entries),
            "session_path": str(resolved_session_path) if resolved_session_path else "",
            "session_exists": bool(resolved_session_path and resolved_session_path.exists()),
            "sessions": session_summaries,
            "session_count": len(session_summaries),
            "event_count": len(resolved_events),
        }

    def analyze(
        self,
        *,
        catalog_path: Optional[str] = None,
        session_path: Optional[str] = None,
        catalog_entries: Optional[List[Dict[str, Any]]] = None,
        events: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        resolved_catalog_path = self._resolve_catalog_path(catalog_path)
        resolved_session_path = self._resolve_session_path(session_path)
        catalog = self._load_catalog_entries(resolved_catalog_path, catalog_entries)
        events_list = self._load_events(resolved_session_path, events)

        issues: List[str] = []
        warnings: List[str] = []
        notes: List[str] = []
        checks: List[Dict[str, Any]] = []
        metrics: Dict[str, Any] = {}

        catalog_issues, catalog_warnings, catalog_map, catalog_metrics = self._validate_catalog(catalog)
        issues.extend(catalog_issues)
        warnings.extend(catalog_warnings)
        metrics.update(catalog_metrics)
        checks.append({
            "name": "telemetry_catalog",
            "status": "passed" if not catalog_issues and catalog else ("warning" if catalog and not catalog_issues else "blocked"),
            "message": "遥测事件字典已加载并通过基础校验" if catalog and not catalog_issues else ("遥测事件字典存在问题" if catalog else "未提供遥测事件字典"),
        })

        event_issues, event_warnings, event_metrics, session_summaries, completion_rate = self._validate_events(events_list, catalog_map)
        issues.extend(event_issues)
        warnings.extend(event_warnings)
        metrics.update(event_metrics)
        metrics["pii_violation_count"] = int(catalog_metrics.get("pii_violation_count") or 0) + int(event_metrics.get("pii_violation_count") or 0)
        metrics["privacy_gate_passed"] = metrics["pii_violation_count"] == 0
        metrics["funnel_completion_rate"] = completion_rate

        if events_list:
            checks.append({
                "name": "telemetry_sessions",
                "status": "passed" if not event_issues else "blocked",
                "message": f"已分析 {len(session_summaries)} 个 session / {len(events_list)} 条事件",
            })
        else:
            checks.append({
                "name": "telemetry_sessions",
                "status": "skipped",
                "message": "未提供会话事件，跳过回流分析",
            })

        retention_user_count = int(metrics.get("retention_user_count") or 0)
        pii_violation_count = int(metrics.get("pii_violation_count") or 0)
        crash_taxonomy = list(metrics.get("crash_taxonomy") or [])
        crash_clusters = list(metrics.get("crash_clusters") or [])
        crash_regression_dashboard = dict(metrics.get("crash_regression_dashboard") or {})
        retention_cohorts = list(metrics.get("retention_cohorts") or [])
        retention_funnel_dashboard = dict(metrics.get("retention_funnel_dashboard") or {})
        retention_funnel_trend_dashboard = dict(metrics.get("retention_funnel_trend_dashboard") or {})
        liveops_impact_dashboard = dict(metrics.get("liveops_impact_dashboard") or {})
        privacy_gate_passed = bool(metrics.get("privacy_gate_passed", True))
        retention_summary = ", ".join(
            f"{item.get('window', '').upper()}={item.get('retention_rate', 0)}"
            for item in retention_cohorts
        )
        checks.append({
            "name": "telemetry_funnel",
            "status": "passed" if session_summaries else "skipped",
            "message": (
                f"关键漏斗完成率 {completion_rate}"
                if session_summaries
                else "未提供会话事件，跳过漏斗分析"
            ),
        })
        checks.append({
            "name": "telemetry_retention",
            "status": "passed" if retention_user_count else "skipped",
            "message": (
                f"留存样本用户 {retention_user_count}，窗口 {retention_summary or 'none'}"
                if retention_user_count
                else "未检测到 player_id/user_id/account_id/anonymous_id，跳过留存分析"
            ),
        })
        checks.append({
            "name": "telemetry_privacy",
            "status": "passed" if privacy_gate_passed else "blocked",
            "message": (
                "未检测到未授权敏感字段或 PII 配置错误"
                if privacy_gate_passed
                else f"检测到 {pii_violation_count} 个 PII/隐私门禁问题"
            ),
        })
        checks.append({
            "name": "telemetry_crash_taxonomy",
            "status": "warning" if crash_taxonomy else ("skipped" if not events_list else "passed"),
            "message": (
                f"已归类 {len(crash_taxonomy)} 类 crash/fatal_error"
                if crash_taxonomy
                else ("未提供会话事件，跳过 crash taxonomy" if not events_list else "未检测到 crash/fatal_error")
            ),
        })
        checks.append({
            "name": "telemetry_crash_clusters",
            "status": "warning" if crash_clusters else ("skipped" if not events_list else "passed"),
            "message": (
                f"已聚类 {len(crash_clusters)} 个 crash cluster"
                if crash_clusters
                else ("未提供会话事件，跳过 crash cluster" if not events_list else "未检测到 crash/fatal_error")
            ),
        })

        notes.append(f"Catalog entries: {len(catalog)}")
        notes.append(f"Session count: {len(session_summaries)}")
        notes.append(f"Event count: {len(events_list)}")
        if metrics.get("top_events"):
            notes.append(f"Top events: {', '.join(metrics['top_events'])}")
        if retention_summary:
            notes.append(f"Retention: {retention_summary}")
        if retention_funnel_dashboard.get("largest_dropoff_step"):
            notes.append(
                f"Funnel largest dropoff: {retention_funnel_dashboard.get('largest_dropoff_step')} x{retention_funnel_dashboard.get('largest_dropoff_count', 0)}"
            )
        if retention_funnel_trend_dashboard.get("highest_crash_day"):
            notes.append(f"Trend highest crash day: {retention_funnel_trend_dashboard.get('highest_crash_day')}")
        notes.append(f"Privacy gate passed: {privacy_gate_passed}")
        if crash_clusters:
            notes.append(f"Crash clusters: {', '.join(item.get('cluster_id') or 'unknown' for item in crash_clusters[:3])}")
        if crash_regression_dashboard.get("top_cluster_id"):
            notes.append(
                f"Crash dashboard top cluster: {crash_regression_dashboard.get('top_cluster_id')} x{crash_regression_dashboard.get('top_cluster_count', 0)}"
            )
        if liveops_impact_dashboard.get("running_experiment_count"):
            notes.append(
                f"LiveOps running experiments: {liveops_impact_dashboard.get('running_experiment_count')} / matched metrics {liveops_impact_dashboard.get('matched_metric_count', 0)}"
            )

        return normalize_telemetry_summary({
            "passed": not issues,
            "catalog_path": str(resolved_catalog_path),
            "session_path": str(resolved_session_path) if resolved_session_path else "",
            "catalog_entry_count": len(catalog),
            "session_count": len(session_summaries),
            "event_count": len(events_list),
            "crash_count": int(metrics.get("crash_count") or 0),
            "uncataloged_event_count": int(metrics.get("uncataloged_event_count") or 0),
            "pii_violation_count": pii_violation_count,
            "privacy_gate_passed": privacy_gate_passed,
            "retention_user_count": retention_user_count,
            "funnel_completion_rate": completion_rate,
            "issues": issues,
            "warnings": warnings,
            "notes": notes,
            "catalog_entries": catalog,
            "sessions": session_summaries,
            "checks": checks,
            "retention_cohorts": retention_cohorts,
            "funnel_breakdown": list(metrics.get("funnel_breakdown") or []),
            "crash_taxonomy": crash_taxonomy,
            "crash_clusters": crash_clusters,
            "crash_regression_dashboard": crash_regression_dashboard,
            "retention_funnel_dashboard": retention_funnel_dashboard,
            "retention_funnel_trend_dashboard": retention_funnel_trend_dashboard,
            "liveops_impact_dashboard": liveops_impact_dashboard,
            "metrics": metrics,
        })

    def detect_present_telemetry(self) -> bool:
        catalog_path = self._resolve_catalog_path(None)
        sessions_dir = self._resolve_sessions_dir()
        return catalog_path.exists() or any(path.is_file() for path in sessions_dir.glob("*.json*"))

    def _resolve_catalog_path(self, raw_path: Optional[str]) -> Path:
        if raw_path:
            normalized = str(raw_path).replace("\\", "/").strip()
            if normalized.startswith("res://"):
                return (self.project_root / normalized.replace("res://", "", 1)).resolve()
            return (self.project_root / normalized).resolve()
        return (self.project_root / DEFAULT_TELEMETRY_CATALOG_PATH).resolve()

    def _resolve_sessions_dir(self) -> Path:
        return (self.project_root / DEFAULT_TELEMETRY_SESSIONS_DIR).resolve()

    def _resolve_session_path(self, raw_path: Optional[str]) -> Optional[Path]:
        if raw_path:
            normalized = str(raw_path).replace("\\", "/").strip()
            if normalized.startswith("res://"):
                return (self.project_root / normalized.replace("res://", "", 1)).resolve()
            return (self.project_root / normalized).resolve()
        return None

    def _load_catalog_entries(self, catalog_path: Path, inline_catalog: Optional[List[Dict[str, Any]]]) -> List[Dict[str, Any]]:
        if inline_catalog:
            return [dict(item) for item in inline_catalog if isinstance(item, dict)]
        if not catalog_path.exists():
            return []
        payload = _read_json_file(catalog_path)
        if isinstance(payload, dict):
            payload = payload.get("events") or payload.get("items") or []
        return [dict(item) for item in payload if isinstance(item, dict)]

    def _load_events(self, session_path: Optional[Path], inline_events: Optional[List[Dict[str, Any]]]) -> List[Dict[str, Any]]:
        if inline_events:
            return [dict(item) for item in inline_events if isinstance(item, dict)]
        if session_path:
            if not session_path.exists():
                return []
            if session_path.suffix.lower() == ".jsonl":
                return _read_jsonl_file(session_path)
            payload = _read_json_file(session_path)
            if isinstance(payload, dict):
                payload = payload.get("events") or payload.get("items") or []
            return [dict(item) for item in payload if isinstance(item, dict)]

        sessions_dir = self._resolve_sessions_dir()
        if not sessions_dir.exists():
            return []
        events: List[Dict[str, Any]] = []
        for path in sorted(candidate for candidate in sessions_dir.glob("*.json*") if candidate.is_file()):
            if path.suffix.lower() == ".jsonl":
                events.extend(_read_jsonl_file(path))
            else:
                payload = _read_json_file(path)
                if isinstance(payload, dict):
                    payload = payload.get("events") or payload.get("items") or []
                events.extend([dict(item) for item in payload if isinstance(item, dict)])
        return events

    def _validate_catalog(
        self,
        catalog_entries: List[Dict[str, Any]],
    ) -> tuple[List[str], List[str], Dict[str, Dict[str, Any]], Dict[str, Any]]:
        issues: List[str] = []
        warnings: List[str] = []
        catalog_map: Dict[str, Dict[str, Any]] = {}
        pii_issue_count = 0

        if not catalog_entries:
            issues.append("未提供遥测事件字典")
            return issues, warnings, catalog_map, {"pii_violation_count": 0, "catalog_pii_issue_count": 0}

        for item in catalog_entries:
            event_name = _clean_event_name(item.get("event_name"))
            category = str(item.get("category") or "").strip().lower()
            privacy_level = str(item.get("privacy_level") or "").strip().lower()
            fields = list(item.get("fields") or [])

            if not event_name:
                issues.append("遥测事件字典存在空 event_name")
                continue
            if event_name in catalog_map:
                issues.append(f"遥测事件重复定义: {event_name}")
            if category and category not in TELEMETRY_ALLOWED_CATEGORIES:
                warnings.append(f"事件 {event_name} 使用了未注册分类 {category}")
            if privacy_level and privacy_level not in {"anonymous", "internal", "restricted"}:
                issues.append(f"事件 {event_name} 使用了非法 privacy_level={privacy_level}")

            seen_fields = set()
            normalized_fields: List[Dict[str, Any]] = []
            for field in fields:
                raw = dict(field or {})
                field_name = str(raw.get("name") or "").strip()
                if not field_name:
                    issues.append(f"事件 {event_name} 存在空字段名")
                    continue
                if field_name in seen_fields:
                    issues.append(f"事件 {event_name} 字段重复: {field_name}")
                seen_fields.add(field_name)
                normalized_fields.append({
                    "name": field_name,
                    "type": str(raw.get("type") or "string").strip() or "string",
                    "required": bool(raw.get("required")),
                    "pii": bool(raw.get("pii")),
                })

            pii_fields = [field["name"] for field in normalized_fields if field.get("pii")]
            normalized_privacy_level = privacy_level or "anonymous"
            if pii_fields and normalized_privacy_level != "restricted":
                pii_issue_count += len(pii_fields)
                issues.append(
                    f"事件 {event_name} 标记了 PII 字段 {', '.join(pii_fields)}，但 privacy_level 不是 restricted"
                )

            catalog_map[event_name] = {
                **dict(item),
                "event_name": event_name,
                "category": category or "gameplay",
                "privacy_level": normalized_privacy_level,
                "fields": normalized_fields,
            }
        return issues, warnings, catalog_map, {
            "pii_violation_count": pii_issue_count,
            "catalog_pii_issue_count": pii_issue_count,
        }

    def _validate_events(
        self,
        events: List[Dict[str, Any]],
        catalog_map: Dict[str, Dict[str, Any]],
    ) -> tuple[List[str], List[str], Dict[str, Any], List[Dict[str, Any]], float]:
        issues: List[str] = []
        warnings: List[str] = []
        event_counter: Counter[str] = Counter()
        uncataloged_count = 0
        crash_count = 0
        session_events: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
        crash_counter: Counter[str] = Counter()
        crash_sessions: Dict[str, set[str]] = defaultdict(set)
        crash_cluster_events: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
        actor_days: Dict[str, set[Any]] = defaultdict(set)
        pii_violation_count = 0

        for item in events:
            event_name = _clean_event_name(item.get("event_name"))
            session_id = str(item.get("session_id") or "").strip()
            timestamp = str(item.get("timestamp") or "").strip()
            payload = dict(item.get("payload") or {}) if isinstance(item.get("payload"), dict) else {}

            if not event_name:
                issues.append("遥测事件缺少 event_name")
                continue
            if not session_id:
                issues.append(f"事件 {event_name} 缺少 session_id")
            if not timestamp:
                issues.append(f"事件 {event_name} 缺少 timestamp")

            event_counter[event_name] += 1
            if session_id:
                session_events[session_id].append(item)

            actor_id = self._extract_actor_id(item)
            event_day = self._parse_event_day(timestamp)
            if actor_id and event_day:
                actor_days[actor_id].add(event_day)

            crash_type = self._classify_crash(item)
            if crash_type:
                crash_count += 1
                crash_counter[crash_type] += 1
                if session_id:
                    crash_sessions[crash_type].add(session_id)
                crash_cluster_key = self._build_crash_cluster_key(item, crash_type)
                crash_cluster_events[crash_cluster_key].append(item)

            catalog_entry = catalog_map.get(event_name)
            if not catalog_entry:
                uncataloged_count += 1
                issues.append(f"未登记的遥测事件: {event_name}")
                continue

            required_fields = {field["name"] for field in catalog_entry["fields"] if field.get("required")}
            missing_fields = sorted(name for name in required_fields if name not in payload)
            if missing_fields:
                issues.append(f"事件 {event_name} 缺少必填字段: {', '.join(missing_fields)}")

            declared_pii_fields = {field["name"] for field in catalog_entry["fields"] if field.get("pii")}
            forbidden_keys = sorted(name for name in payload if name in FORBIDDEN_PII_KEYS)
            unauthorized_keys = [
                name
                for name in forbidden_keys
                if catalog_entry.get("privacy_level") != "restricted" or name not in declared_pii_fields
            ]
            if unauthorized_keys:
                pii_violation_count += len(unauthorized_keys)
                issues.append(f"事件 {event_name} 包含未授权敏感字段: {', '.join(unauthorized_keys)}")

        session_summaries = self._summarize_sessions(events)
        funnel_breakdown, completion_rate = self._build_funnel_breakdown(session_events)
        retention_cohorts, retention_user_count = self._build_retention_cohorts(actor_days)
        crash_taxonomy = self._build_crash_taxonomy(crash_counter, crash_sessions)
        crash_clusters = self._build_crash_clusters(crash_cluster_events)
        crash_regression_dashboard = self._build_crash_regression_dashboard(crash_cluster_events)
        retention_funnel_dashboard = self._build_retention_funnel_dashboard(
            retention_cohorts,
            funnel_breakdown,
            completion_rate,
        )
        retention_funnel_trend_dashboard = self._build_retention_funnel_trend_dashboard(
            session_events=session_events,
            session_summaries=session_summaries,
            actor_days=actor_days,
            crash_cluster_events=crash_cluster_events,
        )
        liveops_impact_dashboard = self._build_liveops_impact_dashboard(
            retention_cohorts=retention_cohorts,
            completion_rate=completion_rate,
            crash_count=crash_count,
            trend_dashboard=retention_funnel_trend_dashboard,
        )
        if crash_count:
            warnings.append(f"回流事件中检测到 {crash_count} 次 crash/fatal_error")

        metrics: Dict[str, Any] = {
            "uncataloged_event_count": uncataloged_count,
            "crash_count": crash_count,
            "pii_violation_count": pii_violation_count,
            "privacy_gate_passed": pii_violation_count == 0,
            "top_events": [f"{name}:{count}" for name, count in event_counter.most_common(5)],
            "session_count": len(session_summaries),
            "event_count": len(events),
            "retention_user_count": retention_user_count,
            "retention_cohorts": retention_cohorts,
            "funnel_breakdown": funnel_breakdown,
            "crash_taxonomy": crash_taxonomy,
            "crash_clusters": crash_clusters,
            "crash_cluster_count": len(crash_clusters),
            "crash_regression_dashboard": crash_regression_dashboard,
            "retention_funnel_dashboard": retention_funnel_dashboard,
            "retention_funnel_trend_dashboard": retention_funnel_trend_dashboard,
            "liveops_impact_dashboard": liveops_impact_dashboard,
        }
        for cohort in retention_cohorts:
            metrics[f"{cohort['window']}_retention_rate"] = cohort["retention_rate"]
        return issues, warnings, metrics, session_summaries, completion_rate

    def _summarize_sessions(self, events: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        grouped: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
        for item in events:
            session_id = str(item.get("session_id") or "").strip()
            if session_id:
                grouped[session_id].append(item)

        summaries: List[Dict[str, Any]] = []
        for session_id in sorted(grouped):
            rows = grouped[session_id]
            timestamps = sorted(str(row.get("timestamp") or "").strip() for row in rows if str(row.get("timestamp") or "").strip())
            build_ids = [str(row.get("build_id") or row.get("payload", {}).get("build_id") or "").strip() for row in rows]
            channels = [str(row.get("channel") or row.get("payload", {}).get("channel") or "").strip() for row in rows]
            summaries.append({
                "session_id": session_id,
                "event_count": len(rows),
                "first_event_at": timestamps[0] if timestamps else "",
                "last_event_at": timestamps[-1] if timestamps else "",
                "build_id": next((value for value in build_ids if value), ""),
                "channel": next((value for value in channels if value), ""),
            })
        return summaries

    def _extract_actor_id(self, event: Dict[str, Any]) -> str:
        payload = dict(event.get("payload") or {}) if isinstance(event.get("payload"), dict) else {}
        for key in ACTOR_ID_KEYS:
            value = event.get(key)
            if value not in (None, ""):
                return str(value).strip()
            payload_value = payload.get(key)
            if payload_value not in (None, ""):
                return str(payload_value).strip()
        return ""

    def _parse_event_day(self, timestamp: str) -> Optional[Any]:
        normalized = str(timestamp or "").strip()
        if not normalized:
            return None
        if normalized.endswith("Z"):
            normalized = normalized[:-1] + "+00:00"
        try:
            return datetime.fromisoformat(normalized).date()
        except ValueError:
            try:
                return datetime.fromisoformat(normalized.split(".", 1)[0]).date()
            except ValueError:
                return None

    def _classify_crash(self, event: Dict[str, Any]) -> str:
        event_name = _clean_event_name(event.get("event_name"))
        if event_name not in {"crash", "fatal_error"}:
            return ""
        payload = dict(event.get("payload") or {}) if isinstance(event.get("payload"), dict) else {}
        for key in CRASH_TYPE_KEYS:
            value = payload.get(key)
            if value not in (None, ""):
                return str(value).strip().lower()
        return event_name

    def _build_crash_cluster_key(self, event: Dict[str, Any], crash_type: str) -> str:
        payload = dict(event.get("payload") or {}) if isinstance(event.get("payload"), dict) else {}
        for key in CRASH_SIGNATURE_KEYS:
            value = payload.get(key)
            if value not in (None, ""):
                return str(value).strip().lower()
        return crash_type or "unknown"

    def _build_funnel_breakdown(
        self,
        session_events: Dict[str, List[Dict[str, Any]]],
    ) -> tuple[List[Dict[str, Any]], float]:
        if not session_events:
            return [], 0.0

        total_sessions = float(len(session_events))
        breakdown: List[Dict[str, Any]] = []
        completed = 0
        for step_index, event_name in enumerate(DEFAULT_FUNNEL_SEQUENCE, start=1):
            session_count = sum(
                1
                for rows in session_events.values()
                if event_name in {_clean_event_name(item.get("event_name")) for item in rows}
            )
            breakdown.append({
                "step_index": step_index,
                "step": event_name,
                "event_name": event_name,
                "session_count": session_count,
                "conversion_rate": round(session_count / total_sessions, 4),
            })
        for rows in session_events.values():
            names = {_clean_event_name(item.get("event_name")) for item in rows}
            if all(name in names for name in DEFAULT_FUNNEL_SEQUENCE):
                completed += 1
        return breakdown, round(completed / total_sessions, 4)

    def _build_retention_cohorts(self, actor_days: Dict[str, set[Any]]) -> tuple[List[Dict[str, Any]], int]:
        if not actor_days:
            return [], 0

        max_day = max(max(days) for days in actor_days.values() if days)
        cohorts: List[Dict[str, Any]] = []
        for day_offset in RETENTION_WINDOWS:
            eligible_users = 0
            retained_users = 0
            for days in actor_days.values():
                if not days:
                    continue
                first_day = min(days)
                if (max_day - first_day).days < day_offset:
                    continue
                eligible_users += 1
                if first_day + timedelta(days=day_offset) in days:
                    retained_users += 1
            cohorts.append({
                "window": f"d{day_offset}",
                "day_offset": day_offset,
                "eligible_users": eligible_users,
                "retained_users": retained_users,
                "retention_rate": round(retained_users / float(eligible_users), 4) if eligible_users else 0.0,
            })
        return cohorts, len(actor_days)

    def _build_crash_taxonomy(
        self,
        crash_counter: Counter[str],
        crash_sessions: Dict[str, set[str]],
    ) -> List[Dict[str, Any]]:
        return [
            {
                "crash_type": crash_type,
                "count": count,
                "session_count": len(crash_sessions.get(crash_type) or set()),
            }
            for crash_type, count in crash_counter.most_common()
        ]

    def _build_crash_clusters(self, crash_cluster_events: Dict[str, List[Dict[str, Any]]]) -> List[Dict[str, Any]]:
        clusters: List[Dict[str, Any]] = []
        for cluster_key, events in crash_cluster_events.items():
            if not events:
                continue
            sample_event = events[0]
            payload = dict(sample_event.get("payload") or {}) if isinstance(sample_event.get("payload"), dict) else {}
            timestamps = sorted(
                str(item.get("timestamp") or "").strip()
                for item in events
                if str(item.get("timestamp") or "").strip()
            )
            session_ids = sorted(
                {
                    str(item.get("session_id") or "").strip()
                    for item in events
                    if str(item.get("session_id") or "").strip()
                }
            )
            builds = sorted(
                {
                    str(item.get("build_id") or item.get("payload", {}).get("build_id") or "").strip()
                    for item in events
                    if str(item.get("build_id") or item.get("payload", {}).get("build_id") or "").strip()
                }
            )
            clusters.append({
                "cluster_id": cluster_key.replace(" ", "_"),
                "signature": cluster_key,
                "crash_type": self._classify_crash(sample_event) or "unknown",
                "error_code": str(payload.get("error_code") or "").strip(),
                "stack_hash": str(payload.get("stack_hash") or payload.get("stack_signature") or "").strip(),
                "count": len(events),
                "session_count": len(session_ids),
                "latest_seen_at": timestamps[-1] if timestamps else "",
                "sample_session_id": session_ids[0] if session_ids else "",
                "sample_scene_path": str(payload.get("scene_path") or "").strip(),
                "builds": builds,
            })
        return sorted(
            clusters,
            key=lambda item: (-int(item.get("count") or 0), str(item.get("latest_seen_at") or "")),
        )

    def _build_crash_regression_dashboard(self, crash_cluster_events: Dict[str, List[Dict[str, Any]]]) -> Dict[str, Any]:
        build_rows: Dict[str, Dict[str, Any]] = {}
        scene_rows: Dict[str, Dict[str, Any]] = {}
        top_cluster_id = ""
        top_cluster_count = 0

        for cluster_key, events in crash_cluster_events.items():
            if not events:
                continue
            cluster_id = cluster_key.replace(" ", "_")
            cluster_count = len(events)
            if cluster_count > top_cluster_count:
                top_cluster_id = cluster_id
                top_cluster_count = cluster_count

            for item in events:
                payload = dict(item.get("payload") or {}) if isinstance(item.get("payload"), dict) else {}
                build_id = str(item.get("build_id") or payload.get("build_id") or "").strip() or "unknown_build"
                scene_path = str(payload.get("scene_path") or "").strip() or "unknown_scene"
                timestamp = str(item.get("timestamp") or "").strip()

                build_bucket = build_rows.setdefault(build_id, {
                    "build_id": build_id,
                    "crash_count": 0,
                    "cluster_ids": set(),
                    "latest_seen_at": "",
                    "cluster_counter": Counter(),
                })
                build_bucket["crash_count"] += 1
                build_bucket["cluster_ids"].add(cluster_id)
                build_bucket["cluster_counter"][cluster_id] += 1
                if timestamp and timestamp > str(build_bucket["latest_seen_at"] or ""):
                    build_bucket["latest_seen_at"] = timestamp

                scene_bucket = scene_rows.setdefault(scene_path, {
                    "scene_path": scene_path,
                    "crash_count": 0,
                    "cluster_ids": set(),
                    "build_ids": set(),
                    "latest_seen_at": "",
                    "cluster_counter": Counter(),
                })
                scene_bucket["crash_count"] += 1
                scene_bucket["cluster_ids"].add(cluster_id)
                scene_bucket["build_ids"].add(build_id)
                scene_bucket["cluster_counter"][cluster_id] += 1
                if timestamp and timestamp > str(scene_bucket["latest_seen_at"] or ""):
                    scene_bucket["latest_seen_at"] = timestamp

        build_regressions = [
            {
                "build_id": row["build_id"],
                "crash_count": row["crash_count"],
                "cluster_count": len(row["cluster_ids"]),
                "latest_seen_at": row["latest_seen_at"],
                "top_cluster_id": row["cluster_counter"].most_common(1)[0][0] if row["cluster_counter"] else "",
            }
            for row in build_rows.values()
        ]
        build_regressions.sort(key=lambda item: (-int(item["crash_count"]), str(item["latest_seen_at"])))

        scene_regressions = [
            {
                "scene_path": row["scene_path"],
                "crash_count": row["crash_count"],
                "cluster_count": len(row["cluster_ids"]),
                "affected_build_count": len(row["build_ids"]),
                "latest_seen_at": row["latest_seen_at"],
                "top_cluster_id": row["cluster_counter"].most_common(1)[0][0] if row["cluster_counter"] else "",
            }
            for row in scene_rows.values()
        ]
        scene_regressions.sort(key=lambda item: (-int(item["crash_count"]), str(item["latest_seen_at"])))

        recommendations: List[str] = []
        if top_cluster_id:
            recommendations.append(f"优先处理 Top Cluster `{top_cluster_id}`，当前命中 {top_cluster_count} 次。")
        if build_regressions:
            recommendations.append(f"优先检查 build `{build_regressions[0]['build_id']}`，它当前 crash 数最高。")
        if scene_regressions and scene_regressions[0]["scene_path"] != "unknown_scene":
            recommendations.append(f"优先复测 scene `{scene_regressions[0]['scene_path']}`，它当前是最高风险场景。")

        return {
            "affected_build_count": len(build_regressions),
            "affected_scene_count": len(scene_regressions),
            "top_cluster_id": top_cluster_id,
            "top_cluster_count": top_cluster_count,
            "build_regressions": build_regressions,
            "scene_regressions": scene_regressions,
            "recommendations": recommendations,
        }

    def _build_retention_funnel_dashboard(
        self,
        retention_cohorts: List[Dict[str, Any]],
        funnel_breakdown: List[Dict[str, Any]],
        completion_rate: float,
    ) -> Dict[str, Any]:
        retention_windows = [
            {
                "window": str(item.get("window") or "").strip().lower(),
                "day_offset": int(item.get("day_offset") or 0),
                "eligible_users": int(item.get("eligible_users") or 0),
                "retained_users": int(item.get("retained_users") or 0),
                "retention_rate": round(float(item.get("retention_rate") or 0.0), 4),
            }
            for item in retention_cohorts
        ]

        funnel_dropoffs: List[Dict[str, Any]] = []
        previous_step = ""
        previous_event_name = ""
        previous_session_count = 0
        for item in funnel_breakdown:
            session_count = int(item.get("session_count") or 0)
            if previous_session_count == 0:
                dropoff_count = 0
                dropoff_rate = 0.0
            else:
                dropoff_count = max(previous_session_count - session_count, 0)
                dropoff_rate = round(dropoff_count / float(previous_session_count), 4) if previous_session_count else 0.0
            funnel_dropoffs.append({
                "step_index": int(item.get("step_index") or 0),
                "step": str(item.get("step") or item.get("event_name") or "").strip(),
                "event_name": str(item.get("event_name") or item.get("step") or "").strip(),
                "previous_step": previous_step,
                "previous_event_name": previous_event_name,
                "previous_session_count": previous_session_count,
                "session_count": session_count,
                "dropoff_count": dropoff_count,
                "dropoff_rate": dropoff_rate,
            })
            previous_step = str(item.get("step") or item.get("event_name") or "").strip()
            previous_event_name = str(item.get("event_name") or item.get("step") or "").strip()
            previous_session_count = session_count

        lowest_retention_window = ""
        lowest_retention_rate = 0.0
        eligible_windows = [item for item in retention_windows if int(item.get("eligible_users") or 0) > 0]
        if eligible_windows:
            lowest_retention = min(
                eligible_windows,
                key=lambda item: (float(item.get("retention_rate") or 0.0), int(item.get("day_offset") or 0)),
            )
            lowest_retention_window = str(lowest_retention.get("window") or "").strip().lower()
            lowest_retention_rate = round(float(lowest_retention.get("retention_rate") or 0.0), 4)

        largest_dropoff_step = ""
        largest_dropoff_count = 0
        largest_dropoff_rate = 0.0
        actionable_dropoffs = [item for item in funnel_dropoffs if int(item.get("step_index") or 0) > 1]
        if actionable_dropoffs:
            largest_dropoff = max(
                actionable_dropoffs,
                key=lambda item: (int(item.get("dropoff_count") or 0), float(item.get("dropoff_rate") or 0.0)),
            )
            largest_dropoff_step = str(largest_dropoff.get("event_name") or largest_dropoff.get("step") or "").strip()
            largest_dropoff_count = int(largest_dropoff.get("dropoff_count") or 0)
            largest_dropoff_rate = round(float(largest_dropoff.get("dropoff_rate") or 0.0), 4)

        recommendations: List[str] = []
        if lowest_retention_window:
            recommendations.append(
                f"优先补样 `{lowest_retention_window}` 留存窗口，当前留存率 {lowest_retention_rate}。"
            )
        if largest_dropoff_step:
            previous_name = next(
                (
                    item.get("previous_event_name") or item.get("previous_step") or ""
                    for item in funnel_dropoffs
                    if str(item.get("event_name") or item.get("step") or "").strip() == largest_dropoff_step
                ),
                "",
            )
            if previous_name:
                recommendations.append(
                    f"优先检查 `{previous_name}` -> `{largest_dropoff_step}` 漏斗转化，当前流失 {largest_dropoff_count} ({largest_dropoff_rate})。"
                )
            else:
                recommendations.append(
                    f"优先检查 `{largest_dropoff_step}` 步骤，当前流失 {largest_dropoff_count} ({largest_dropoff_rate})。"
                )
        if completion_rate < 1.0:
            recommendations.append(f"当前关键漏斗完成率 {round(float(completion_rate or 0.0), 4)}，建议补齐完成链路事件。")

        return {
            "completion_rate": round(float(completion_rate or 0.0), 4),
            "lowest_retention_window": lowest_retention_window,
            "lowest_retention_rate": lowest_retention_rate,
            "largest_dropoff_step": largest_dropoff_step,
            "largest_dropoff_count": largest_dropoff_count,
            "largest_dropoff_rate": largest_dropoff_rate,
            "retention_windows": retention_windows,
            "funnel_dropoffs": funnel_dropoffs,
            "recommendations": recommendations,
        }

    def _build_retention_funnel_trend_dashboard(
        self,
        *,
        session_events: Dict[str, List[Dict[str, Any]]],
        session_summaries: List[Dict[str, Any]],
        actor_days: Dict[str, set[Any]],
        crash_cluster_events: Dict[str, List[Dict[str, Any]]],
    ) -> Dict[str, Any]:
        session_lookup = {str(item.get("session_id") or "").strip(): item for item in session_summaries}
        actor_first_days = {
            actor_id: min(days)
            for actor_id, days in actor_days.items()
            if days
        }
        day_rows: Dict[str, Dict[str, Any]] = {}
        build_rows: Dict[str, Dict[str, Any]] = {}
        channel_rows: Dict[str, Dict[str, Any]] = {}

        for session_id, rows in session_events.items():
            summary = session_lookup.get(session_id, {})
            timestamps = [
                str(item.get("timestamp") or "").strip()
                for item in rows
                if str(item.get("timestamp") or "").strip()
            ]
            session_day_value = self._parse_event_day(min(timestamps) if timestamps else "")
            session_day = session_day_value.isoformat() if session_day_value else "unknown_day"
            build_id = str(summary.get("build_id") or "").strip() or "unknown_build"
            channel = str(summary.get("channel") or "").strip() or "unknown"
            event_names = {_clean_event_name(item.get("event_name")) for item in rows}
            completed = all(name in event_names for name in DEFAULT_FUNNEL_SEQUENCE)
            crash_hits = sum(1 for item in rows if self._classify_crash(item))
            actor_ids = {
                self._extract_actor_id(item)
                for item in rows
                if self._extract_actor_id(item)
            }

            day_bucket = day_rows.setdefault(session_day, {
                "date": session_day,
                "session_count": 0,
                "event_count": 0,
                "active_users": set(),
                "completed_session_count": 0,
                "crash_count": 0,
            })
            day_bucket["session_count"] += 1
            day_bucket["event_count"] += len(rows)
            day_bucket["active_users"].update(actor_ids)
            day_bucket["completed_session_count"] += 1 if completed else 0
            day_bucket["crash_count"] += crash_hits

            build_bucket = build_rows.setdefault(build_id, {
                "build_id": build_id,
                "session_count": 0,
                "event_count": 0,
                "completed_session_count": 0,
                "crash_count": 0,
            })
            build_bucket["session_count"] += 1
            build_bucket["event_count"] += len(rows)
            build_bucket["completed_session_count"] += 1 if completed else 0
            build_bucket["crash_count"] += crash_hits

            channel_bucket = channel_rows.setdefault(channel, {
                "channel": channel,
                "session_count": 0,
                "event_count": 0,
                "completed_session_count": 0,
                "crash_count": 0,
            })
            channel_bucket["session_count"] += 1
            channel_bucket["event_count"] += len(rows)
            channel_bucket["completed_session_count"] += 1 if completed else 0
            channel_bucket["crash_count"] += crash_hits

        normalized_day_rows: List[Dict[str, Any]] = []
        for date in sorted(day_rows):
            row = day_rows[date]
            active_users = sorted(user_id for user_id in row["active_users"] if user_id)
            new_user_count = sum(
                1 for user_id in active_users
                if actor_first_days.get(user_id) and actor_first_days[user_id].isoformat() == date
            )
            active_user_count = len(active_users)
            normalized_day_rows.append({
                "date": date,
                "session_count": row["session_count"],
                "event_count": row["event_count"],
                "active_user_count": active_user_count,
                "new_user_count": new_user_count,
                "returning_user_count": max(active_user_count - new_user_count, 0),
                "completed_session_count": row["completed_session_count"],
                "completion_rate": round(row["completed_session_count"] / float(row["session_count"]), 4) if row["session_count"] else 0.0,
                "crash_count": row["crash_count"],
            })

        normalized_build_rows = sorted([
            {
                "build_id": row["build_id"],
                "session_count": row["session_count"],
                "event_count": row["event_count"],
                "completion_rate": round(row["completed_session_count"] / float(row["session_count"]), 4) if row["session_count"] else 0.0,
                "crash_count": row["crash_count"],
            }
            for row in build_rows.values()
        ], key=lambda item: (-int(item["session_count"]), str(item["build_id"])))

        normalized_channel_rows = sorted([
            {
                "channel": row["channel"],
                "session_count": row["session_count"],
                "event_count": row["event_count"],
                "completion_rate": round(row["completed_session_count"] / float(row["session_count"]), 4) if row["session_count"] else 0.0,
                "crash_count": row["crash_count"],
            }
            for row in channel_rows.values()
        ], key=lambda item: (-int(item["session_count"]), str(item["channel"])))

        highest_crash_day = ""
        if normalized_day_rows:
            highest_crash_day = max(
                normalized_day_rows,
                key=lambda item: (int(item.get("crash_count") or 0), int(item.get("session_count") or 0)),
            ).get("date", "")

        top_build_id = normalized_build_rows[0]["build_id"] if normalized_build_rows else ""
        top_channel = normalized_channel_rows[0]["channel"] if normalized_channel_rows else ""
        recommendations: List[str] = []
        if highest_crash_day and any(int(item.get("crash_count") or 0) > 0 for item in normalized_day_rows):
            recommendations.append(f"优先复盘 {highest_crash_day} 的回流样本，该日 crash 命中最高。")
        if normalized_build_rows:
            weakest_build = min(normalized_build_rows, key=lambda item: (float(item.get("completion_rate") or 0.0), int(item.get("session_count") or 0)))
            recommendations.append(
                f"优先检查 build `{weakest_build['build_id']}`，当前 completion_rate={weakest_build['completion_rate']}。"
            )
        if normalized_channel_rows:
            weakest_channel = min(normalized_channel_rows, key=lambda item: (float(item.get("completion_rate") or 0.0), int(item.get("session_count") or 0)))
            recommendations.append(
                f"优先检查 channel `{weakest_channel['channel']}`，当前 completion_rate={weakest_channel['completion_rate']}。"
            )

        return {
            "day_count": len(normalized_day_rows),
            "top_build_id": top_build_id,
            "top_channel": top_channel,
            "highest_crash_day": highest_crash_day,
            "day_rows": normalized_day_rows,
            "build_rows": normalized_build_rows,
            "channel_rows": normalized_channel_rows,
            "recommendations": recommendations,
        }

    def _build_liveops_impact_dashboard(
        self,
        *,
        retention_cohorts: List[Dict[str, Any]],
        completion_rate: float,
        crash_count: int,
        trend_dashboard: Dict[str, Any],
    ) -> Dict[str, Any]:
        liveops_root = self.project_root / "liveops"
        remote_config_entries = self._load_liveops_items(liveops_root / "remote_config.json")
        experiment_entries = self._load_liveops_items(liveops_root / "experiments.json")

        available_metrics = [
            "funnel_completion_rate",
            *(f"{item.get('window')}_retention_rate" for item in retention_cohorts if item.get("window")),
        ]
        if crash_count:
            available_metrics.append("crash_count")
        available_metrics = [item for item in available_metrics if item]

        active_remote_configs = [
            entry for entry in remote_config_entries
            if bool(entry.get("enabled"))
        ]
        running_experiments = [
            entry for entry in experiment_entries
            if str(entry.get("status") or "").strip().lower() == "running"
        ]

        tracked_metrics: List[str] = []
        metric_matches: List[Dict[str, str]] = []
        for entry in running_experiments:
            for metric_name in list(entry.get("target_metrics") or []):
                normalized_metric = str(metric_name or "").strip()
                if not normalized_metric:
                    continue
                tracked_metrics.append(normalized_metric)
                matched_metric = self._match_liveops_metric(normalized_metric, available_metrics)
                if matched_metric:
                    metric_matches.append({
                        "target_metric": normalized_metric,
                        "matched_metric": matched_metric,
                        "source": "telemetry_summary",
                    })

        unmatched_target_metrics = sorted({
            metric for metric in tracked_metrics
            if metric not in {item["target_metric"] for item in metric_matches}
        })

        active_entries = []
        for entry in active_remote_configs:
            active_entries.append({
                "entry_type": "remote_config",
                "entry_id": str(entry.get("config_key") or "").strip() or "unnamed",
                "owner": str(entry.get("owner") or "").strip(),
                "status": "enabled" if bool(entry.get("enabled")) else "disabled",
                "rollout_percentage": float(entry.get("rollout_percentage") or 100.0),
                "matched_metrics": [],
                "target_metrics": [],
            })
        for entry in running_experiments:
            target_metrics = [str(item or "").strip() for item in list(entry.get("target_metrics") or []) if str(item or "").strip()]
            matched_metrics = [
                item["matched_metric"]
                for item in metric_matches
                if item["target_metric"] in target_metrics
            ]
            active_entries.append({
                "entry_type": "experiment_catalog",
                "entry_id": str(entry.get("experiment_id") or "").strip() or "unnamed",
                "owner": str(entry.get("owner") or "").strip(),
                "status": str(entry.get("status") or "").strip(),
                "rollout_percentage": float(entry.get("rollout_percentage") or 0.0),
                "matched_metrics": matched_metrics,
                "target_metrics": target_metrics,
            })

        recommendations: List[str] = []
        if unmatched_target_metrics:
            recommendations.append(f"补齐 LiveOps target_metrics 的遥测映射: {', '.join(unmatched_target_metrics)}")
        if float(completion_rate or 0.0) < 1.0 and running_experiments:
            recommendations.append("存在运行中的实验且关键漏斗未满转，建议按实验维度补样回流并拆分渠道。")
        if trend_dashboard.get("top_build_id"):
            recommendations.append(f"优先对 build `{trend_dashboard.get('top_build_id')}` 复核当前 LiveOps 影响。")

        return {
            "active_remote_config_count": len(active_remote_configs),
            "running_experiment_count": len(running_experiments),
            "tracked_metric_count": len(sorted(set(tracked_metrics))),
            "matched_metric_count": len(metric_matches),
            "available_metric_count": len(available_metrics),
            "tracked_metrics": sorted(set(tracked_metrics)),
            "available_metrics": sorted(set(available_metrics)),
            "unmatched_target_metrics": unmatched_target_metrics,
            "metric_matches": metric_matches,
            "active_entries": active_entries,
            "recommendations": recommendations,
        }

    def _load_liveops_items(self, path: Path) -> List[Dict[str, Any]]:
        payload = self._load_json_file(path)
        if not payload:
            return []
        items = payload.get("items") if isinstance(payload, dict) else []
        return [dict(item) for item in items if isinstance(item, dict)]

    def _load_json_file(self, path: Path) -> Dict[str, Any]:
        try:
            return dict(_read_json_file(path))
        except Exception:
            return {}

    def _match_liveops_metric(self, target_metric: str, available_metrics: List[str]) -> str:
        normalized = str(target_metric or "").strip().lower()
        exact_match = next((item for item in available_metrics if item == normalized), "")
        if exact_match:
            return exact_match
        if normalized in {"tutorial_completion_rate", "level_completion_rate"}:
            return "funnel_completion_rate" if "funnel_completion_rate" in available_metrics else ""
        if normalized.endswith("_retention"):
            candidate = normalized.replace("_retention", "_retention_rate")
            if candidate in available_metrics:
                return candidate
        if "retention" in normalized:
            return next((item for item in available_metrics if item.endswith("_retention_rate")), "")
        if "crash" in normalized:
            return "crash_count" if "crash_count" in available_metrics else ""
        if "completion" in normalized:
            return "funnel_completion_rate" if "funnel_completion_rate" in available_metrics else ""
        return ""


def build_telemetry_report(summary: Dict[str, Any]) -> str:
    normalized = normalize_telemetry_summary(summary)
    lines = [
        "# Telemetry Report",
        "",
        f"- Passed: {normalized['passed']}",
        f"- Catalog Entries: {normalized['catalog_entry_count']}",
        f"- Sessions: {normalized['session_count']}",
        f"- Events: {normalized['event_count']}",
        f"- Crash Count: {normalized['crash_count']}",
        f"- Uncataloged Events: {normalized['uncataloged_event_count']}",
        f"- PII Violations: {normalized['pii_violation_count']}",
        f"- Privacy Gate Passed: {normalized['privacy_gate_passed']}",
        f"- Retention Users: {normalized['retention_user_count']}",
        f"- Funnel Completion Rate: {normalized['funnel_completion_rate']}",
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
    lines.extend(["", "## Retention Cohorts", ""])
    lines.extend([
        f"- {item['window']}: eligible={item['eligible_users']} retained={item['retained_users']} rate={item['retention_rate']}"
        for item in normalized["retention_cohorts"]
    ] or ["- none"])
    lines.extend(["", "## Funnel Breakdown", ""])
    lines.extend([
        f"- step {item['step_index']} {item['event_name']}: sessions={item['session_count']} rate={item['conversion_rate']}"
        for item in normalized["funnel_breakdown"]
    ] or ["- none"])
    retention_dashboard = dict(normalized.get("retention_funnel_dashboard") or {})
    lines.extend(["", "## Retention Funnel Dashboard", ""])
    lines.extend([
        f"- completion_rate: {retention_dashboard.get('completion_rate', 0)}",
        f"- lowest_retention_window: {retention_dashboard.get('lowest_retention_window') or '-'}",
        f"- lowest_retention_rate: {retention_dashboard.get('lowest_retention_rate', 0)}",
        f"- largest_dropoff_step: {retention_dashboard.get('largest_dropoff_step') or '-'}",
        f"- largest_dropoff_count: {retention_dashboard.get('largest_dropoff_count', 0)}",
        f"- largest_dropoff_rate: {retention_dashboard.get('largest_dropoff_rate', 0)}",
    ])
    trend_dashboard = dict(normalized.get("retention_funnel_trend_dashboard") or {})
    lines.extend(["", "## Retention Funnel Trends", ""])
    lines.extend([
        f"- day_count: {trend_dashboard.get('day_count', 0)}",
        f"- top_build_id: {trend_dashboard.get('top_build_id') or '-'}",
        f"- top_channel: {trend_dashboard.get('top_channel') or '-'}",
        f"- highest_crash_day: {trend_dashboard.get('highest_crash_day') or '-'}",
    ])
    lines.extend(["", "## Crash Taxonomy", ""])
    lines.extend([
        f"- {item['crash_type']}: count={item['count']} sessions={item['session_count']}"
        for item in normalized["crash_taxonomy"]
    ] or ["- none"])
    lines.extend(["", "## Crash Clusters", ""])
    lines.extend([
        f"- {item['cluster_id']}: type={item['crash_type']} count={item['count']} latest={item['latest_seen_at']} sample_session={item['sample_session_id']} builds={','.join(item['builds']) or '-'}"
        for item in normalized["crash_clusters"]
    ] or ["- none"])
    liveops_dashboard = dict(normalized.get("liveops_impact_dashboard") or {})
    lines.extend(["", "## LiveOps Impact", ""])
    lines.extend([
        f"- active_remote_config_count: {liveops_dashboard.get('active_remote_config_count', 0)}",
        f"- running_experiment_count: {liveops_dashboard.get('running_experiment_count', 0)}",
        f"- tracked_metric_count: {liveops_dashboard.get('tracked_metric_count', 0)}",
        f"- matched_metric_count: {liveops_dashboard.get('matched_metric_count', 0)}",
        f"- unmatched_target_metrics: {', '.join(liveops_dashboard.get('unmatched_target_metrics') or []) or 'none'}",
    ])
    lines.extend(["", "## Metrics", ""])
    for key in sorted(normalized["metrics"]):
        lines.append(f"- {key}: {normalized['metrics'][key]}")
    if not normalized["metrics"]:
        lines.append("- none")
    lines.append("")
    return "\n".join(lines)


def build_crash_cluster_report(summary: Dict[str, Any]) -> str:
    normalized = normalize_telemetry_summary(summary)
    clusters = list(normalized["crash_clusters"])
    lines = [
        "# Crash Cluster Report",
        "",
        f"- Passed: {normalized['passed']}",
        f"- Crash Count: {normalized['crash_count']}",
        f"- Crash Cluster Count: {len(clusters)}",
        f"- Session Count: {normalized['session_count']}",
        f"- Event Count: {normalized['event_count']}",
        "",
        "## Summary",
        "",
    ]
    if clusters:
        top_cluster = clusters[0]
        lines.extend([
            f"- Top Cluster: {top_cluster['cluster_id']}",
            f"- Top Signature: {top_cluster['signature']}",
            f"- Top Count: {top_cluster['count']}",
            f"- Latest Seen: {top_cluster['latest_seen_at'] or '-'}",
        ])
    else:
        lines.append("- No crash clusters detected")

    lines.extend(["", "## Clusters", ""])
    if not clusters:
        lines.append("- none")
    else:
        for item in clusters:
            lines.extend([
                f"### {item['cluster_id']}",
                f"- Signature: {item['signature']}",
                f"- Crash Type: {item['crash_type']}",
                f"- Error Code: {item['error_code'] or '-'}",
                f"- Stack Hash: {item['stack_hash'] or '-'}",
                f"- Count: {item['count']}",
                f"- Session Count: {item['session_count']}",
                f"- Latest Seen: {item['latest_seen_at'] or '-'}",
                f"- Sample Session: {item['sample_session_id'] or '-'}",
                f"- Sample Scene: {item['sample_scene_path'] or '-'}",
                f"- Builds: {', '.join(item['builds']) if item['builds'] else '-'}",
                "",
            ])
    lines.extend(["## Recommendations", ""])
    if clusters:
        lines.extend([
            "- 优先按 Top Cluster 追溯对应 build 和 scene_path。",
            "- 若同一 cluster 跨多个 build 出现，先检查共享 runtime/script 变更。",
            "- 若 cluster 只出现在单 build，优先回看该 build 的最近资源或脚本改动。",
        ])
    else:
        lines.append("- 当前没有 crash cluster，可继续观察后续样本。")
    lines.append("")
    return "\n".join(lines)


def build_crash_regression_dashboard_report(summary: Dict[str, Any]) -> str:
    normalized = normalize_telemetry_summary(summary)
    dashboard = dict(normalized.get("crash_regression_dashboard") or {})
    build_regressions = list(dashboard.get("build_regressions") or [])
    scene_regressions = list(dashboard.get("scene_regressions") or [])
    recommendations = list(dashboard.get("recommendations") or [])

    lines = [
        "# Crash Regression Dashboard",
        "",
        f"- Affected Builds: {dashboard.get('affected_build_count', 0)}",
        f"- Affected Scenes: {dashboard.get('affected_scene_count', 0)}",
        f"- Top Cluster: {dashboard.get('top_cluster_id') or '-'}",
        f"- Top Cluster Count: {dashboard.get('top_cluster_count', 0)}",
        "",
        "## Build Regressions",
        "",
    ]
    lines.extend([
        f"- {item['build_id']}: crashes={item['crash_count']} clusters={item['cluster_count']} latest={item['latest_seen_at'] or '-'} top_cluster={item['top_cluster_id'] or '-'}"
        for item in build_regressions
    ] or ["- none"])
    lines.extend(["", "## Scene Regressions", ""])
    lines.extend([
        f"- {item['scene_path']}: crashes={item['crash_count']} clusters={item['cluster_count']} builds={item['affected_build_count']} latest={item['latest_seen_at'] or '-'} top_cluster={item['top_cluster_id'] or '-'}"
        for item in scene_regressions
    ] or ["- none"])
    lines.extend(["", "## Recommendations", ""])
    lines.extend([f"- {item}" for item in recommendations] or ["- none"])
    lines.append("")
    return "\n".join(lines)


def build_retention_funnel_dashboard_report(summary: Dict[str, Any]) -> str:
    normalized = normalize_telemetry_summary(summary)
    dashboard = dict(normalized.get("retention_funnel_dashboard") or {})
    retention_windows = list(dashboard.get("retention_windows") or [])
    funnel_dropoffs = list(dashboard.get("funnel_dropoffs") or [])
    recommendations = list(dashboard.get("recommendations") or [])

    lines = [
        "# Retention Funnel Dashboard",
        "",
        f"- Completion Rate: {dashboard.get('completion_rate', 0)}",
        f"- Lowest Retention Window: {dashboard.get('lowest_retention_window') or '-'}",
        f"- Lowest Retention Rate: {dashboard.get('lowest_retention_rate', 0)}",
        f"- Largest Dropoff Step: {dashboard.get('largest_dropoff_step') or '-'}",
        f"- Largest Dropoff Count: {dashboard.get('largest_dropoff_count', 0)}",
        f"- Largest Dropoff Rate: {dashboard.get('largest_dropoff_rate', 0)}",
        "",
        "## Retention Windows",
        "",
    ]
    lines.extend([
        f"- {item['window']}: eligible={item['eligible_users']} retained={item['retained_users']} rate={item['retention_rate']}"
        for item in retention_windows
    ] or ["- none"])
    lines.extend(["", "## Funnel Dropoffs", ""])
    lines.extend([
        f"- step {item['step_index']} {item['event_name']}: prev={item['previous_session_count']} current={item['session_count']} dropoff={item['dropoff_count']} rate={item['dropoff_rate']}"
        for item in funnel_dropoffs
    ] or ["- none"])
    lines.extend(["", "## Recommendations", ""])
    lines.extend([f"- {item}" for item in recommendations] or ["- none"])
    lines.append("")
    return "\n".join(lines)


def build_retention_funnel_trend_report(summary: Dict[str, Any]) -> str:
    normalized = normalize_telemetry_summary(summary)
    dashboard = dict(normalized.get("retention_funnel_trend_dashboard") or {})
    day_rows = list(dashboard.get("day_rows") or [])
    build_rows = list(dashboard.get("build_rows") or [])
    channel_rows = list(dashboard.get("channel_rows") or [])
    recommendations = list(dashboard.get("recommendations") or [])

    lines = [
        "# Retention Funnel Trend Dashboard",
        "",
        f"- Day Count: {dashboard.get('day_count', 0)}",
        f"- Top Build: {dashboard.get('top_build_id') or '-'}",
        f"- Top Channel: {dashboard.get('top_channel') or '-'}",
        f"- Highest Crash Day: {dashboard.get('highest_crash_day') or '-'}",
        "",
        "## Daily Trends",
        "",
    ]
    lines.extend([
        f"- {item['date']}: sessions={item['session_count']} events={item['event_count']} active_users={item['active_user_count']} new_users={item['new_user_count']} completion={item['completion_rate']} crashes={item['crash_count']}"
        for item in day_rows
    ] or ["- none"])
    lines.extend(["", "## Build Trends", ""])
    lines.extend([
        f"- {item['build_id']}: sessions={item['session_count']} events={item['event_count']} completion={item['completion_rate']} crashes={item['crash_count']}"
        for item in build_rows
    ] or ["- none"])
    lines.extend(["", "## Channel Trends", ""])
    lines.extend([
        f"- {item['channel']}: sessions={item['session_count']} events={item['event_count']} completion={item['completion_rate']} crashes={item['crash_count']}"
        for item in channel_rows
    ] or ["- none"])
    lines.extend(["", "## Recommendations", ""])
    lines.extend([f"- {item}" for item in recommendations] or ["- none"])
    lines.append("")
    return "\n".join(lines)


def build_liveops_impact_report(summary: Dict[str, Any]) -> str:
    normalized = normalize_telemetry_summary(summary)
    dashboard = dict(normalized.get("liveops_impact_dashboard") or {})
    metric_matches = list(dashboard.get("metric_matches") or [])
    active_entries = list(dashboard.get("active_entries") or [])
    recommendations = list(dashboard.get("recommendations") or [])

    lines = [
        "# LiveOps Impact Dashboard",
        "",
        f"- Active Remote Configs: {dashboard.get('active_remote_config_count', 0)}",
        f"- Running Experiments: {dashboard.get('running_experiment_count', 0)}",
        f"- Tracked Metric Count: {dashboard.get('tracked_metric_count', 0)}",
        f"- Matched Metric Count: {dashboard.get('matched_metric_count', 0)}",
        f"- Available Metric Count: {dashboard.get('available_metric_count', 0)}",
        "",
        "## Metric Matches",
        "",
    ]
    lines.extend([
        f"- {item['target_metric']} -> {item['matched_metric']} ({item['source'] or '-'})"
        for item in metric_matches
    ] or ["- none"])
    lines.extend(["", "## Active Entries", ""])
    lines.extend([
        f"- {item['entry_type']} {item['entry_id']}: status={item['status'] or '-'} rollout={item['rollout_percentage']} target_metrics={','.join(item['target_metrics']) or '-'} matched_metrics={','.join(item['matched_metrics']) or '-'}"
        for item in active_entries
    ] or ["- none"])
    lines.extend(["", "## Recommendations", ""])
    lines.extend([f"- {item}" for item in recommendations] or ["- none"])
    lines.append("")
    return "\n".join(lines)

"""
Reusable balance analysis helpers for managed game data tables.
"""

from __future__ import annotations

import csv
import json
from collections import defaultdict
from io import StringIO
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from ..contracts import normalize_balance_analysis


BALANCE_DEFAULT_TABLE_PATHS: Dict[str, str] = {
    "enemy": "data_tables/enemies.csv",
    "quest": "data_tables/quests.csv",
    "loot": "data_tables/loot_tables.csv",
}


def _parse_rows(content: str, path_hint: str) -> List[Dict[str, Any]]:
    text = str(content or "").strip()
    if not text:
        return []
    if text.startswith("{") or text.startswith("["):
        payload = json.loads(text)
        if isinstance(payload, dict):
            payload = payload.get("rows") or payload.get("items") or []
        return [dict(item) for item in payload if isinstance(item, dict)]

    suffix = Path(path_hint).suffix.lower()
    delimiter = "\t" if suffix == ".tsv" else ","
    reader = csv.DictReader(StringIO(text), delimiter=delimiter)
    return [dict(row) for row in reader]


def _to_float(value: Any) -> Optional[float]:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _safe_avg(values: Iterable[float]) -> Optional[float]:
    items = [float(value) for value in values]
    if not items:
        return None
    return sum(items) / float(len(items))


class GameBalanceAnalyzer:
    def __init__(self, project_root: str | Path):
        self.project_root = Path(project_root).resolve()

    def analyze(
        self,
        *,
        include_tables: Optional[List[str]] = None,
        enemy_table_path: Optional[str] = None,
        quest_table_path: Optional[str] = None,
        loot_table_path: Optional[str] = None,
        enemy_rows: Optional[List[Dict[str, Any]]] = None,
        quest_rows: Optional[List[Dict[str, Any]]] = None,
        loot_rows: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        table_types = [
            item for item in (include_tables or ["enemy", "quest", "loot"])
            if item in BALANCE_DEFAULT_TABLE_PATHS
        ]

        snapshots = {
            "enemy": self._load_table("enemy", enemy_table_path, enemy_rows),
            "quest": self._load_table("quest", quest_table_path, quest_rows),
            "loot": self._load_table("loot", loot_table_path, loot_rows),
        }

        requested_snapshots = {name: snapshots[name] for name in table_types}
        checks: List[Dict[str, Any]] = []
        issues: List[str] = []
        warnings: List[str] = []
        metrics: Dict[str, Any] = {}
        summary: List[str] = []
        loaded_table_types = [name for name, snapshot in requested_snapshots.items() if snapshot["rows"]]

        if not loaded_table_types:
            return normalize_balance_analysis({
                "passed": False,
                "score": 0,
                "table_types": table_types,
                "issues": ["未找到可分析的 enemy / quest / loot 数据表"],
                "checks": [
                    {
                        "name": "balance_inputs",
                        "status": "blocked",
                        "message": "未检测到可用的数值表，无法执行平衡分析",
                    }
                ],
                "metrics": {},
                "summary": ["缺少可分析的数据表输入"],
            })

        for name in table_types:
            snapshot = requested_snapshots[name]
            if snapshot["rows"]:
                checks.append({
                    "name": f"{name}_table_loaded",
                    "status": "passed",
                    "message": f"已加载 {len(snapshot['rows'])} 行，来源 {snapshot['path']}",
                })
            else:
                checks.append({
                    "name": f"{name}_table_loaded",
                    "status": "skipped",
                    "message": f"未找到 {name} 表，跳过该维度分析",
                })

        enemy_rows_loaded = requested_snapshots.get("enemy", {}).get("rows", [])
        quest_rows_loaded = requested_snapshots.get("quest", {}).get("rows", [])
        loot_rows_loaded = requested_snapshots.get("loot", {}).get("rows", [])

        if enemy_rows_loaded:
            self._analyze_enemy_table(enemy_rows_loaded, checks, issues, warnings, metrics, summary)
        if quest_rows_loaded:
            self._analyze_quest_table(quest_rows_loaded, checks, issues, warnings, metrics, summary)
        if loot_rows_loaded:
            self._analyze_loot_table(loot_rows_loaded, checks, issues, warnings, metrics, summary)
        if enemy_rows_loaded and loot_rows_loaded:
            self._analyze_enemy_loot_links(enemy_rows_loaded, loot_rows_loaded, checks, issues, warnings, metrics, summary)

        score = max(0.0, 100.0 - (15.0 * len(issues)) - (5.0 * len(warnings)))
        if not summary:
            summary.append("已加载数据表，但未生成额外分析摘要")

        return normalize_balance_analysis({
            "passed": len(issues) == 0,
            "score": score,
            "issue_count": len(issues),
            "warning_count": len(warnings),
            "table_types": loaded_table_types,
            "issues": issues,
            "warnings": warnings,
            "checks": checks,
            "metrics": metrics,
            "summary": summary,
        })

    def detect_present_tables(self) -> List[str]:
        present: List[str] = []
        for name, relative in BALANCE_DEFAULT_TABLE_PATHS.items():
            if (self.project_root / relative).exists():
                present.append(name)
        return present

    def _load_table(
        self,
        table_type: str,
        raw_path: Optional[str],
        rows: Optional[List[Dict[str, Any]]],
    ) -> Dict[str, Any]:
        if rows:
            return {
                "path": f"inline:{table_type}",
                "rows": [dict(item) for item in rows],
            }

        target = self._resolve_table_path(table_type, raw_path)
        if not target.exists():
            return {"path": str(target), "rows": []}
        return {
            "path": str(target),
            "rows": _parse_rows(target.read_text(encoding="utf-8"), str(target)),
        }

    def _resolve_table_path(self, table_type: str, raw_path: Optional[str]) -> Path:
        if raw_path:
            normalized = str(raw_path).replace("\\", "/").strip()
            if normalized.startswith("res://"):
                return (self.project_root / normalized.replace("res://", "", 1)).resolve()
            return (self.project_root / normalized).resolve()
        return (self.project_root / BALANCE_DEFAULT_TABLE_PATHS[table_type]).resolve()

    def _analyze_enemy_table(
        self,
        rows: List[Dict[str, Any]],
        checks: List[Dict[str, Any]],
        issues: List[str],
        warnings: List[str],
        metrics: Dict[str, Any],
        summary: List[str],
    ) -> None:
        hp_values = [value for value in (_to_float(row.get("hp")) for row in rows) if value is not None]
        attack_values = [value for value in (_to_float(row.get("attack")) for row in rows) if value is not None]
        speed_values = [value for value in (_to_float(row.get("move_speed")) for row in rows) if value is not None]

        avg_hp = _safe_avg(hp_values)
        avg_attack = _safe_avg(attack_values)
        avg_speed = _safe_avg(speed_values)
        metrics.update({
            "enemy_count": len(rows),
            "avg_enemy_hp": round(avg_hp, 2) if avg_hp is not None else None,
            "avg_enemy_attack": round(avg_attack, 2) if avg_attack is not None else None,
            "avg_enemy_speed": round(avg_speed, 2) if avg_speed is not None else None,
        })
        summary.append(
            f"Enemy 平均值: hp {metrics['avg_enemy_hp'] or '-'} / attack {metrics['avg_enemy_attack'] or '-'} / speed {metrics['avg_enemy_speed'] or '-'}"
        )

        if hp_values and attack_values:
            hp_attack_ratio = _safe_avg([hp / max(attack, 1.0) for hp, attack in zip(hp_values, attack_values)])
            metrics["enemy_hp_attack_ratio"] = round(hp_attack_ratio or 0.0, 2)
            if hp_attack_ratio is not None and hp_attack_ratio < 2.0:
                issues.append("敌人平均 hp/attack 比例过低，战斗时长可能失衡")
            elif hp_attack_ratio is not None and hp_attack_ratio > 24.0:
                warnings.append("敌人平均 hp/attack 比例偏高，击杀节奏可能拖沓")

        if hp_values and min(hp_values) > 0 and max(hp_values) / min(hp_values) > 12.0:
            warnings.append("敌人 hp 梯度跨度过大，难度曲线可能过陡")
        if attack_values and min(attack_values) >= 0 and max(attack_values) / max(min(attack_values), 1.0) > 10.0:
            warnings.append("敌人 attack 梯度跨度过大，伤害曲线需要复核")

        enemy_issues_before = len(issues) + len(warnings)
        checks.append({
            "name": "combat_stat_spread",
            "status": "passed" if enemy_issues_before == len(issues) + len(warnings) else "warning",
            "message": "已分析敌人基础战斗数值",
        })
        if issues and any("敌人" in item or "战斗" in item for item in issues):
            checks[-1]["status"] = "blocked"
        elif warnings and any("敌人" in item or "战斗" in item for item in warnings):
            checks[-1]["status"] = "warning"

    def _analyze_quest_table(
        self,
        rows: List[Dict[str, Any]],
        checks: List[Dict[str, Any]],
        issues: List[str],
        warnings: List[str],
        metrics: Dict[str, Any],
        summary: List[str],
    ) -> None:
        target_counts = [value for value in (_to_float(row.get("target_count")) for row in rows) if value is not None and value > 0]
        reward_values = [value for value in (_to_float(row.get("reward_gold")) for row in rows) if value is not None and value >= 0]
        reward_per_target: List[float] = []
        for row in rows:
            target = _to_float(row.get("target_count"))
            reward = _to_float(row.get("reward_gold"))
            if target and reward is not None and target > 0:
                reward_per_target.append(reward / target)

        metrics.update({
            "quest_count": len(rows),
            "avg_quest_target_count": round(_safe_avg(target_counts) or 0.0, 2) if target_counts else None,
            "avg_quest_reward_gold": round(_safe_avg(reward_values) or 0.0, 2) if reward_values else None,
            "avg_reward_per_target": round(_safe_avg(reward_per_target) or 0.0, 2) if reward_per_target else None,
        })
        summary.append(
            f"Quest 平均值: target {metrics['avg_quest_target_count'] or '-'} / reward {metrics['avg_quest_reward_gold'] or '-'} / reward_per_target {metrics['avg_reward_per_target'] or '-'}"
        )

        if reward_per_target:
            nonzero = [value for value in reward_per_target if value > 0]
            if nonzero:
                spread_ratio = max(nonzero) / max(min(nonzero), 1.0)
                metrics["quest_reward_spread_ratio"] = round(spread_ratio, 2)
                if spread_ratio > 8.0:
                    warnings.append("任务 reward_per_target 跨度较大，奖励曲线可能不平滑")
                if spread_ratio > 14.0:
                    issues.append("任务 reward_per_target 跨度过大，奖励设计需要重新分段")
            elif len(rows) > 0:
                warnings.append("任务奖励全部为 0，缺少有效经济激励")

        checks.append({
            "name": "quest_reward_scaling",
            "status": "passed",
            "message": "已分析任务目标和奖励关系",
        })
        if issues and any("任务" in item or "奖励" in item for item in issues):
            checks[-1]["status"] = "blocked"
        elif warnings and any("任务" in item or "奖励" in item for item in warnings):
            checks[-1]["status"] = "warning"

    def _analyze_loot_table(
        self,
        rows: List[Dict[str, Any]],
        checks: List[Dict[str, Any]],
        issues: List[str],
        warnings: List[str],
        metrics: Dict[str, Any],
        summary: List[str],
    ) -> None:
        grouped_rates: Dict[str, float] = defaultdict(float)
        expected_quantities: Dict[str, float] = defaultdict(float)

        for row in rows:
            loot_id = str(row.get("loot_id") or "").strip()
            drop_rate = _to_float(row.get("drop_rate")) or 0.0
            quantity = _to_float(row.get("quantity")) or 0.0
            if not loot_id:
                continue
            grouped_rates[loot_id] += drop_rate
            expected_quantities[loot_id] += drop_rate * quantity

        metrics["loot_table_count"] = len(grouped_rates)
        if grouped_rates:
            metrics["avg_loot_total_drop_rate"] = round(_safe_avg(grouped_rates.values()) or 0.0, 2)
            metrics["avg_loot_expected_quantity"] = round(_safe_avg(expected_quantities.values()) or 0.0, 2)
            summary.append(
                f"Loot 平均值: total_drop_rate {metrics['avg_loot_total_drop_rate']} / expected_quantity {metrics['avg_loot_expected_quantity']}"
            )

        overloaded = [loot_id for loot_id, total in grouped_rates.items() if total > 1.05]
        underfilled = [loot_id for loot_id, total in grouped_rates.items() if total < 0.25]
        if overloaded:
            issues.append(f"掉落表总概率超过 1.0: {', '.join(overloaded[:5])}")
        if underfilled:
            warnings.append(f"掉落表总概率偏低: {', '.join(underfilled[:5])}")

        checks.append({
            "name": "loot_probability_budget",
            "status": "passed",
            "message": "已分析掉落概率和期望产出",
        })
        if overloaded:
            checks[-1]["status"] = "blocked"
        elif underfilled:
            checks[-1]["status"] = "warning"

    def _analyze_enemy_loot_links(
        self,
        enemy_rows: List[Dict[str, Any]],
        loot_rows: List[Dict[str, Any]],
        checks: List[Dict[str, Any]],
        issues: List[str],
        warnings: List[str],
        metrics: Dict[str, Any],
        summary: List[str],
    ) -> None:
        existing_loot_ids = {
            str(row.get("loot_id") or "").strip()
            for row in loot_rows
            if str(row.get("loot_id") or "").strip()
        }
        referenced_loot_ids = {
            str(row.get("loot_table_id") or "").strip()
            for row in enemy_rows
            if str(row.get("loot_table_id") or "").strip()
        }
        missing = sorted(loot_id for loot_id in referenced_loot_ids if loot_id not in existing_loot_ids)
        coverage = 1.0 if not referenced_loot_ids else ((len(referenced_loot_ids) - len(missing)) / float(len(referenced_loot_ids)))
        metrics["enemy_loot_link_coverage"] = round(coverage, 2)
        summary.append(f"Enemy-Loot 链接覆盖率: {metrics['enemy_loot_link_coverage']}")

        if missing:
            issues.append(f"敌人引用了不存在的掉落表: {', '.join(missing[:5])}")
        elif not referenced_loot_ids:
            warnings.append("敌人表未配置 loot_table_id，掉落链路尚未闭环")

        checks.append({
            "name": "enemy_loot_links",
            "status": "passed" if not missing and referenced_loot_ids else ("warning" if not missing else "blocked"),
            "message": "已检查敌人与掉落表的引用关系" if referenced_loot_ids else "敌人表未配置掉落引用",
        })


def build_balance_analysis_report(analysis: Dict[str, Any]) -> str:
    normalized = normalize_balance_analysis(analysis)
    lines = [
        "# Balance Analysis Report",
        "",
        f"- Passed: {normalized['passed']}",
        f"- Score: {normalized['score']}",
        f"- Table Types: {', '.join(normalized['table_types']) or '-'}",
        f"- Issues: {normalized['issue_count']}",
        f"- Warnings: {normalized['warning_count']}",
        "",
        "## Summary",
        "",
    ]
    lines.extend([f"- {item}" for item in normalized["summary"]] or ["- No summary"])
    lines.extend(["", "## Checks", ""])
    lines.extend([f"- {item['name']}: {item['status']} - {item['message']}" for item in normalized["checks"]] or ["- No checks"])
    lines.extend(["", "## Issues", ""])
    lines.extend([f"- {item}" for item in normalized["issues"]] or ["- none"])
    lines.extend(["", "## Warnings", ""])
    lines.extend([f"- {item}" for item in normalized["warnings"]] or ["- none"])
    lines.extend(["", "## Metrics", ""])
    for key in sorted(normalized["metrics"]):
        lines.append(f"- {key}: {normalized['metrics'][key]}")
    if not normalized["metrics"]:
        lines.append("- none")
    lines.append("")
    return "\n".join(lines)

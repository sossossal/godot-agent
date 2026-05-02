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

from ..contracts import normalize_balance_analysis, normalize_balance_version_compare


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

    def simulate_combat_balance(
        self,
        *,
        enemy_table_path: Optional[str] = None,
        enemy_rows: Optional[List[Dict[str, Any]]] = None,
        player_hp: float = 100.0,
        player_attack: float = 10.0,
        player_attacks_per_second: float = 1.0,
        enemy_attacks_per_second: float = 1.0,
        min_ttk_seconds: float = 3.0,
        max_ttk_seconds: float = 18.0,
        max_damage_taken_ratio: float = 0.8,
    ) -> Dict[str, Any]:
        snapshot = self._load_table("enemy", enemy_table_path, enemy_rows)
        rows = snapshot["rows"]
        issues: List[str] = []
        warnings: List[str] = []
        checks: List[Dict[str, Any]] = []
        simulations: List[Dict[str, Any]] = []

        player_hp = max(float(player_hp or 0.0), 1.0)
        player_dps = max(float(player_attack or 0.0) * max(float(player_attacks_per_second or 0.0), 0.01), 0.01)
        enemy_aps = max(float(enemy_attacks_per_second or 0.0), 0.0)
        max_damage_taken = player_hp * max(float(max_damage_taken_ratio or 0.0), 0.0)

        if not rows:
            return {
                "passed": False,
                "source_path": snapshot["path"],
                "issues": ["未找到可用于战斗仿真的 enemy 数据"],
                "warnings": [],
                "checks": [{
                    "name": "combat_simulation_inputs",
                    "status": "blocked",
                    "message": "缺少 enemy rows，无法执行战斗仿真",
                }],
                "metrics": {},
                "simulations": [],
                "summary": ["战斗仿真缺少输入"],
            }

        for index, row in enumerate(rows):
            enemy_id = str(row.get("enemy_id") or row.get("id") or row.get("name") or f"enemy_{index + 1}").strip()
            hp = max(_to_float(row.get("hp")) or 0.0, 0.0)
            attack = max(_to_float(row.get("attack")) or 0.0, 0.0)
            ttk = hp / player_dps if hp > 0 else 0.0
            damage_taken = attack * enemy_aps * ttk
            survival_margin = player_hp - damage_taken
            status = "passed"
            if hp <= 0:
                status = "blocked"
                issues.append(f"{enemy_id} 缺少有效 hp，无法仿真击杀时长")
            elif ttk < min_ttk_seconds:
                status = "warning"
                warnings.append(f"{enemy_id} TTK={round(ttk, 2)}s 低于下限 {min_ttk_seconds}s")
            elif ttk > max_ttk_seconds:
                status = "warning"
                warnings.append(f"{enemy_id} TTK={round(ttk, 2)}s 高于上限 {max_ttk_seconds}s")
            if damage_taken > max_damage_taken:
                status = "blocked"
                issues.append(f"{enemy_id} 预计承伤 {round(damage_taken, 2)} 超过预算 {round(max_damage_taken, 2)}")
            elif survival_margin < player_hp * 0.35 and status == "passed":
                status = "warning"
                warnings.append(f"{enemy_id} 存活边际偏低: {round(survival_margin, 2)}")

            simulations.append({
                "enemy_id": enemy_id,
                "hp": round(hp, 2),
                "attack": round(attack, 2),
                "ttk_seconds": round(ttk, 2),
                "damage_taken": round(damage_taken, 2),
                "survival_margin": round(survival_margin, 2),
                "status": status,
            })

        ttk_values = [item["ttk_seconds"] for item in simulations]
        damage_values = [item["damage_taken"] for item in simulations]
        blocked_count = sum(1 for item in simulations if item["status"] == "blocked")
        warning_count = sum(1 for item in simulations if item["status"] == "warning")
        metrics = {
            "combat_simulation_enemy_count": len(simulations),
            "combat_simulation_avg_ttk_seconds": round(_safe_avg(ttk_values) or 0.0, 2),
            "combat_simulation_max_ttk_seconds": round(max(ttk_values), 2) if ttk_values else 0.0,
            "combat_simulation_avg_damage_taken": round(_safe_avg(damage_values) or 0.0, 2),
            "combat_simulation_max_damage_taken": round(max(damage_values), 2) if damage_values else 0.0,
            "combat_simulation_blocked_count": blocked_count,
            "combat_simulation_warning_count": warning_count,
        }
        checks.append({
            "name": "combat_ttk_budget",
            "status": "warning" if warning_count else "passed",
            "message": f"avg_ttk={metrics['combat_simulation_avg_ttk_seconds']}s max_ttk={metrics['combat_simulation_max_ttk_seconds']}s",
        })
        checks.append({
            "name": "combat_survival_budget",
            "status": "blocked" if blocked_count else "passed",
            "message": f"avg_damage={metrics['combat_simulation_avg_damage_taken']} max_damage={metrics['combat_simulation_max_damage_taken']}",
        })
        return {
            "passed": blocked_count == 0,
            "source_path": snapshot["path"],
            "issues": issues,
            "warnings": warnings,
            "checks": checks,
            "metrics": metrics,
            "simulations": simulations,
            "summary": [
                f"战斗仿真覆盖 {len(simulations)} 个敌人",
                f"平均 TTK {metrics['combat_simulation_avg_ttk_seconds']}s，最大承伤 {metrics['combat_simulation_max_damage_taken']}",
            ],
        }

    def audit_growth_curve(
        self,
        *,
        enemy_table_path: Optional[str] = None,
        quest_table_path: Optional[str] = None,
        enemy_rows: Optional[List[Dict[str, Any]]] = None,
        quest_rows: Optional[List[Dict[str, Any]]] = None,
        max_enemy_power_slope_ratio: float = 3.0,
        max_reward_slope_ratio: float = 4.0,
    ) -> Dict[str, Any]:
        enemy_snapshot = self._load_table("enemy", enemy_table_path, enemy_rows)
        quest_snapshot = self._load_table("quest", quest_table_path, quest_rows)
        issues: List[str] = []
        warnings: List[str] = []
        checks: List[Dict[str, Any]] = []
        curves: Dict[str, Any] = {}

        enemy_points = self._build_enemy_growth_points(enemy_snapshot["rows"])
        quest_points = self._build_quest_growth_points(quest_snapshot["rows"])
        if not enemy_points and not quest_points:
            return {
                "passed": False,
                "source_paths": {"enemy": enemy_snapshot["path"], "quest": quest_snapshot["path"]},
                "issues": ["未找到带 level/min_level/unlock_level 的 enemy 或 quest 数据，无法审计成长曲线"],
                "warnings": [],
                "checks": [{
                    "name": "growth_curve_inputs",
                    "status": "blocked",
                    "message": "缺少可排序的成长曲线点",
                }],
                "metrics": {},
                "curves": {},
                "summary": ["成长曲线审计缺少输入"],
            }

        if enemy_points:
            enemy_curve = self._audit_curve_points(
                points=enemy_points,
                value_key="power",
                ratio_limit=max_enemy_power_slope_ratio,
                label="enemy_power",
            )
            curves["enemy_power"] = enemy_curve
            warnings.extend(enemy_curve["warnings"])
            issues.extend(enemy_curve["issues"])
            checks.append({
                "name": "enemy_power_growth_curve",
                "status": "blocked" if enemy_curve["issues"] else ("warning" if enemy_curve["warnings"] else "passed"),
                "message": f"points={len(enemy_points)} max_slope_ratio={enemy_curve['metrics']['max_slope_ratio']}",
            })

        if quest_points:
            reward_curve = self._audit_curve_points(
                points=quest_points,
                value_key="reward_per_target",
                ratio_limit=max_reward_slope_ratio,
                label="quest_reward",
            )
            curves["quest_reward"] = reward_curve
            warnings.extend(reward_curve["warnings"])
            issues.extend(reward_curve["issues"])
            checks.append({
                "name": "quest_reward_growth_curve",
                "status": "blocked" if reward_curve["issues"] else ("warning" if reward_curve["warnings"] else "passed"),
                "message": f"points={len(quest_points)} max_slope_ratio={reward_curve['metrics']['max_slope_ratio']}",
            })

        metrics: Dict[str, Any] = {
            "growth_curve_enemy_point_count": len(enemy_points),
            "growth_curve_quest_point_count": len(quest_points),
            "growth_curve_blocked_curve_count": sum(1 for item in curves.values() if item["issues"]),
            "growth_curve_warning_curve_count": sum(1 for item in curves.values() if item["warnings"]),
        }
        for curve_name, curve in curves.items():
            for key, value in curve["metrics"].items():
                metrics[f"growth_curve_{curve_name}_{key}"] = value

        return {
            "passed": not issues,
            "source_paths": {"enemy": enemy_snapshot["path"], "quest": quest_snapshot["path"]},
            "issues": issues,
            "warnings": warnings,
            "checks": checks,
            "metrics": metrics,
            "curves": curves,
            "summary": [
                f"成长曲线审计覆盖 enemy={len(enemy_points)} / quest={len(quest_points)} 个点",
                f"阻断曲线 {metrics['growth_curve_blocked_curve_count']} 条，警告曲线 {metrics['growth_curve_warning_curve_count']} 条",
            ],
        }

    def _extract_level(self, row: Dict[str, Any]) -> Optional[float]:
        for key in ("level", "min_level", "unlock_level", "tier", "stage"):
            value = _to_float(row.get(key))
            if value is not None:
                return value
        return None

    def _build_enemy_growth_points(self, rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        points: List[Dict[str, Any]] = []
        for index, row in enumerate(rows):
            level = self._extract_level(row)
            hp = _to_float(row.get("hp"))
            attack = _to_float(row.get("attack"))
            if level is None or hp is None or attack is None:
                continue
            enemy_id = str(row.get("enemy_id") or row.get("id") or row.get("name") or f"enemy_{index + 1}").strip()
            points.append({
                "id": enemy_id,
                "level": float(level),
                "power": round(float(hp) + (float(attack) * 8.0), 4),
                "hp": round(float(hp), 4),
                "attack": round(float(attack), 4),
            })
        return sorted(points, key=lambda item: (item["level"], item["id"]))

    def _build_quest_growth_points(self, rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        points: List[Dict[str, Any]] = []
        for index, row in enumerate(rows):
            level = self._extract_level(row)
            reward = _to_float(row.get("reward_gold"))
            target = _to_float(row.get("target_count")) or 1.0
            if level is None or reward is None:
                continue
            quest_id = str(row.get("quest_id") or row.get("id") or row.get("title") or f"quest_{index + 1}").strip()
            points.append({
                "id": quest_id,
                "level": float(level),
                "reward_per_target": round(float(reward) / max(float(target), 1.0), 4),
                "reward_gold": round(float(reward), 4),
                "target_count": round(float(target), 4),
            })
        return sorted(points, key=lambda item: (item["level"], item["id"]))

    def _audit_curve_points(
        self,
        *,
        points: List[Dict[str, Any]],
        value_key: str,
        ratio_limit: float,
        label: str,
    ) -> Dict[str, Any]:
        issues: List[str] = []
        warnings: List[str] = []
        slopes: List[Dict[str, Any]] = []
        previous = None
        for point in points:
            if previous is None:
                previous = point
                continue
            level_delta = max(float(point["level"]) - float(previous["level"]), 0.0001)
            value_delta = float(point[value_key]) - float(previous[value_key])
            slope = value_delta / level_delta
            status = "passed"
            if value_delta < 0:
                status = "warning"
                warnings.append(f"{label} 在 level {previous['level']}->{point['level']} 出现回落")
            slopes.append({
                "from_id": previous["id"],
                "to_id": point["id"],
                "from_level": previous["level"],
                "to_level": point["level"],
                "delta": round(value_delta, 4),
                "slope": round(slope, 4),
                "status": status,
            })
            previous = point

        positive_slopes = [item["slope"] for item in slopes if item["slope"] > 0]
        max_slope = max(positive_slopes) if positive_slopes else 0.0
        min_slope = min(positive_slopes) if positive_slopes else 0.0
        slope_ratio = (max_slope / max(min_slope, 0.0001)) if positive_slopes else 0.0
        if len(points) < 3:
            warnings.append(f"{label} 成长点少于 3 个，曲线可信度有限")
        if slope_ratio > ratio_limit:
            issues.append(f"{label} 斜率跨度 {round(slope_ratio, 2)} 超过阈值 {ratio_limit}")
            for item in slopes:
                if item["slope"] == max_slope:
                    item["status"] = "blocked"
        elif slope_ratio > max(ratio_limit * 0.65, 1.0):
            warnings.append(f"{label} 斜率跨度偏高: {round(slope_ratio, 2)}")
            for item in slopes:
                if item["slope"] == max_slope and item["status"] == "passed":
                    item["status"] = "warning"

        return {
            "points": points,
            "slopes": slopes,
            "issues": issues,
            "warnings": warnings,
            "metrics": {
                "point_count": len(points),
                "slope_count": len(slopes),
                "max_slope": round(max_slope, 4),
                "min_positive_slope": round(min_slope, 4),
                "max_slope_ratio": round(slope_ratio, 4),
            },
        }

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


def _numeric_metric(value: Any) -> Optional[float]:
    if isinstance(value, bool):
        return None
    return _to_float(value)


def compare_balance_versions(
    baseline: Dict[str, Any],
    candidate: Dict[str, Any],
    *,
    max_score_drop: float = 10.0,
    warning_metric_delta_percent: float = 50.0,
    blocked_metric_delta_percent: float = 100.0,
) -> Dict[str, Any]:
    baseline_analysis = normalize_balance_analysis(baseline)
    candidate_analysis = normalize_balance_analysis(candidate)
    issues: List[str] = []
    warnings: List[str] = []
    checks: List[Dict[str, Any]] = []
    metric_deltas: Dict[str, Dict[str, Any]] = {}

    score_delta = candidate_analysis["score"] - baseline_analysis["score"]
    issue_delta = candidate_analysis["issue_count"] - baseline_analysis["issue_count"]
    warning_delta = candidate_analysis["warning_count"] - baseline_analysis["warning_count"]

    if score_delta < -abs(max_score_drop):
        issues.append(f"候选版本平衡评分下降 {abs(round(score_delta, 2))}，超过允许阈值 {max_score_drop}")
    checks.append({
        "name": "score_regression",
        "status": "blocked" if score_delta < -abs(max_score_drop) else "passed",
        "message": f"baseline={baseline_analysis['score']} candidate={candidate_analysis['score']} delta={round(score_delta, 2)}",
    })

    if issue_delta > 0:
        issues.append(f"候选版本新增 {issue_delta} 个平衡问题")
    checks.append({
        "name": "issue_regression",
        "status": "blocked" if issue_delta > 0 else "passed",
        "message": f"baseline={baseline_analysis['issue_count']} candidate={candidate_analysis['issue_count']}",
    })

    if warning_delta > 0:
        warnings.append(f"候选版本新增 {warning_delta} 个平衡警告")
    checks.append({
        "name": "warning_regression",
        "status": "warning" if warning_delta > 0 else "passed",
        "message": f"baseline={baseline_analysis['warning_count']} candidate={candidate_analysis['warning_count']}",
    })

    metric_issue_count = 0
    metric_warning_count = 0
    all_metric_keys = sorted(set(baseline_analysis["metrics"]) | set(candidate_analysis["metrics"]))
    for key in all_metric_keys:
        baseline_value = baseline_analysis["metrics"].get(key)
        candidate_value = candidate_analysis["metrics"].get(key)
        baseline_number = _numeric_metric(baseline_value)
        candidate_number = _numeric_metric(candidate_value)
        if baseline_number is None or candidate_number is None:
            if baseline_value != candidate_value:
                metric_deltas[key] = {
                    "baseline": baseline_value,
                    "candidate": candidate_value,
                    "delta": None,
                    "delta_percent": None,
                    "status": "warning",
                }
                metric_warning_count += 1
            continue

        delta = candidate_number - baseline_number
        if abs(delta) < 0.0001:
            continue
        denominator = abs(baseline_number) if abs(baseline_number) > 0.0001 else 1.0
        delta_percent = (delta / denominator) * 100.0
        abs_percent = abs(delta_percent)
        status = "passed"
        if abs_percent >= blocked_metric_delta_percent:
            status = "blocked"
            metric_issue_count += 1
        elif abs_percent >= warning_metric_delta_percent:
            status = "warning"
            metric_warning_count += 1

        metric_deltas[key] = {
            "baseline": baseline_value,
            "candidate": candidate_value,
            "delta": round(delta, 4),
            "delta_percent": round(delta_percent, 4),
            "status": status,
        }

    if metric_issue_count:
        issues.append(f"候选版本有 {metric_issue_count} 个关键数值指标漂移超过 {blocked_metric_delta_percent}%")
    if metric_warning_count:
        warnings.append(f"候选版本有 {metric_warning_count} 个数值指标漂移超过 {warning_metric_delta_percent}%")
    checks.append({
        "name": "metric_drift",
        "status": "blocked" if metric_issue_count else ("warning" if metric_warning_count else "passed"),
        "message": f"changed_metrics={len(metric_deltas)} blocked={metric_issue_count} warning={metric_warning_count}",
    })

    table_types = sorted(set(baseline_analysis["table_types"]) | set(candidate_analysis["table_types"]))
    summary = [
        f"评分变化: {baseline_analysis['score']} -> {candidate_analysis['score']} (delta {round(score_delta, 2)})",
        f"问题变化: {baseline_analysis['issue_count']} -> {candidate_analysis['issue_count']} (delta {issue_delta})",
        f"警告变化: {baseline_analysis['warning_count']} -> {candidate_analysis['warning_count']} (delta {warning_delta})",
        f"变化指标数: {len(metric_deltas)}",
    ]
    return normalize_balance_version_compare({
        "passed": not issues,
        "baseline_score": baseline_analysis["score"],
        "candidate_score": candidate_analysis["score"],
        "score_delta": score_delta,
        "baseline_issue_count": baseline_analysis["issue_count"],
        "candidate_issue_count": candidate_analysis["issue_count"],
        "issue_delta": issue_delta,
        "baseline_warning_count": baseline_analysis["warning_count"],
        "candidate_warning_count": candidate_analysis["warning_count"],
        "warning_delta": warning_delta,
        "table_types": table_types,
        "changed_metric_count": len(metric_deltas),
        "metric_deltas": metric_deltas,
        "checks": checks,
        "issues": issues,
        "warnings": warnings,
        "summary": summary,
    })


def build_balance_version_compare_report(compare: Dict[str, Any]) -> str:
    normalized = normalize_balance_version_compare(compare)
    lines = [
        "# Balance Version Compare Report",
        "",
        f"- Passed: {normalized['passed']}",
        f"- Score Delta: {normalized['score_delta']}",
        f"- Issue Delta: {normalized['issue_delta']}",
        f"- Warning Delta: {normalized['warning_delta']}",
        f"- Changed Metrics: {normalized['changed_metric_count']}",
        f"- Table Types: {', '.join(normalized['table_types']) or '-'}",
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
    lines.extend(["", "## Metric Deltas", ""])
    for key in sorted(normalized["metric_deltas"]):
        delta = normalized["metric_deltas"][key]
        lines.append(
            f"- {key}: {delta['baseline']} -> {delta['candidate']} "
            f"(delta {delta['delta']}, {delta['delta_percent']}%, {delta['status']})"
        )
    if not normalized["metric_deltas"]:
        lines.append("- none")
    lines.append("")
    return "\n".join(lines)


def build_combat_simulation_report(simulation: Dict[str, Any]) -> str:
    lines = [
        "# Combat Simulation Report",
        "",
        f"- Passed: {bool(simulation.get('passed'))}",
        f"- Source: {simulation.get('source_path') or '-'}",
        "",
        "## Summary",
        "",
    ]
    lines.extend([f"- {item}" for item in simulation.get("summary") or []] or ["- No summary"])
    lines.extend(["", "## Checks", ""])
    lines.extend([
        f"- {item.get('name')}: {item.get('status')} - {item.get('message')}"
        for item in simulation.get("checks") or []
    ] or ["- No checks"])
    lines.extend(["", "## Issues", ""])
    lines.extend([f"- {item}" for item in simulation.get("issues") or []] or ["- none"])
    lines.extend(["", "## Warnings", ""])
    lines.extend([f"- {item}" for item in simulation.get("warnings") or []] or ["- none"])
    lines.extend(["", "## Metrics", ""])
    for key in sorted(dict(simulation.get("metrics") or {})):
        lines.append(f"- {key}: {simulation['metrics'][key]}")
    if not simulation.get("metrics"):
        lines.append("- none")
    lines.extend(["", "## Enemy Samples", ""])
    for item in simulation.get("simulations") or []:
        lines.append(
            f"- {item.get('enemy_id')}: ttk={item.get('ttk_seconds')}s "
            f"damage={item.get('damage_taken')} margin={item.get('survival_margin')} status={item.get('status')}"
        )
    if not simulation.get("simulations"):
        lines.append("- none")
    lines.append("")
    return "\n".join(lines)


def build_growth_curve_report(audit: Dict[str, Any]) -> str:
    lines = [
        "# Growth Curve Audit Report",
        "",
        f"- Passed: {bool(audit.get('passed'))}",
        f"- Enemy Source: {dict(audit.get('source_paths') or {}).get('enemy') or '-'}",
        f"- Quest Source: {dict(audit.get('source_paths') or {}).get('quest') or '-'}",
        "",
        "## Summary",
        "",
    ]
    lines.extend([f"- {item}" for item in audit.get("summary") or []] or ["- No summary"])
    lines.extend(["", "## Checks", ""])
    lines.extend([
        f"- {item.get('name')}: {item.get('status')} - {item.get('message')}"
        for item in audit.get("checks") or []
    ] or ["- No checks"])
    lines.extend(["", "## Issues", ""])
    lines.extend([f"- {item}" for item in audit.get("issues") or []] or ["- none"])
    lines.extend(["", "## Warnings", ""])
    lines.extend([f"- {item}" for item in audit.get("warnings") or []] or ["- none"])
    lines.extend(["", "## Metrics", ""])
    for key in sorted(dict(audit.get("metrics") or {})):
        lines.append(f"- {key}: {audit['metrics'][key]}")
    if not audit.get("metrics"):
        lines.append("- none")
    for curve_name, curve in dict(audit.get("curves") or {}).items():
        lines.extend(["", f"## {curve_name}", "", "### Points", ""])
        for point in curve.get("points") or []:
            value_pairs = ", ".join(f"{key}={value}" for key, value in point.items() if key not in {"id"})
            lines.append(f"- {point.get('id')}: {value_pairs}")
        if not curve.get("points"):
            lines.append("- none")
        lines.extend(["", "### Slopes", ""])
        for slope in curve.get("slopes") or []:
            lines.append(
                f"- {slope.get('from_id')} -> {slope.get('to_id')}: "
                f"delta={slope.get('delta')} slope={slope.get('slope')} status={slope.get('status')}"
            )
        if not curve.get("slopes"):
            lines.append("- none")
    lines.append("")
    return "\n".join(lines)

"""
LiveOps pipeline skill.
"""

from __future__ import annotations

import difflib
import json
import re
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from pydantic import BaseModel, Field

from ..base import BaseSkill, SkillMetadata
from ...contracts import LIVEOPS_PROFILE_SCHEMA_VERSION, normalize_liveops_profile
from ...models import Artifact, Task, ToolResult
from ...validations import ProjectLayoutValidator


LIVEOPS_TYPE_LABELS: Dict[str, str] = {
    "remote_config": "Remote Config",
    "experiment_catalog": "Experiment Catalog",
}

LIVEOPS_SCHEMAS: Dict[str, Dict[str, Any]] = {
    "remote_config": {
        "manifest_path": "liveops/remote_config.json",
        "sample_entries": [{
            "config_key": "combat_spawn_multiplier",
            "value_type": "float",
            "default_value": 1.1,
            "owner": "design_ops",
            "enabled": True,
            "requires_restart": False,
            "environments": ["qa", "live"],
            "rollout_strategy": "percentage",
            "rollout_percentage": 25,
            "audience_segments": ["new_players"],
            "tags": ["balance", "combat"],
            "acceptance_checks": ["owner_declared", "rollout_strategy_defined", "rollback_plan_recorded"],
            "notes": "用于灰度提高首个 combat 场景刷怪系数",
        }],
    },
    "experiment_catalog": {
        "manifest_path": "liveops/experiments.json",
        "sample_entries": [{
            "experiment_id": "tutorial_short_path",
            "status": "running",
            "hypothesis": "缩短前 3 个引导步骤可以提升 tutorial 完成率和 D1 留存",
            "owner": "product_ops",
            "audience_segments": ["new_players"],
            "target_metrics": ["tutorial_completion_rate", "d1_retention"],
            "rollout_percentage": 50,
            "rollback_rule": "tutorial_completion_rate 下降超过 3% 立即回滚",
            "variants": [
                {"variant_id": "control", "weight": 50, "config_overrides": {}},
                {"variant_id": "short_path", "weight": 50, "config_overrides": {"tutorial_step_count": 3}},
            ],
            "acceptance_checks": ["variants_weight_sum_100", "metrics_declared", "rollback_rule_defined"],
            "notes": "针对首日新用户的引导流程实验",
        }],
    },
}

_LIVEOPS_TYPE_VALUES = set(LIVEOPS_SCHEMAS.keys())
_LIVEOPS_VALUE_TYPES = {"bool", "int", "float", "string", "json"}
_LIVEOPS_ENVIRONMENTS = {"dev", "qa", "live"}
_LIVEOPS_ROLLOUT_STRATEGIES = {"global", "percentage", "segment", "whitelist"}
_LIVEOPS_EXPERIMENT_STATUSES = {"draft", "running", "paused", "completed", "archived"}
_SNAKE_CASE_RE = re.compile(r"^[a-z0-9_]+$")


class LiveOpsParams(BaseModel):
    action: str = Field(default="preview", description="template | validate | preview | apply")
    liveops_type: str = Field(default="remote_config", description="remote_config | experiment_catalog")
    manifest_path: Optional[str] = Field(default=None, description="manifest 路径")
    entry_id: Optional[str] = Field(default=None, description="config_key 或 experiment_id")
    owner: Optional[str] = Field(default=None, description="owner")
    value_type: Optional[str] = Field(default=None, description="bool | int | float | string | json")
    default_value: Any = Field(default=None, description="Remote Config 默认值")
    enabled: bool = Field(default=True, description="Remote Config 是否启用")
    requires_restart: bool = Field(default=False, description="Remote Config 是否要求重启")
    environments: List[str] = Field(default_factory=list, description="环境")
    rollout_strategy: Optional[str] = Field(default=None, description="global | percentage | segment | whitelist")
    rollout_percentage: Optional[float] = Field(default=None, description="灰度百分比")
    audience_segments: List[str] = Field(default_factory=list, description="受众分群")
    tags: List[str] = Field(default_factory=list, description="标签")
    hypothesis: str = Field(default="", description="实验假设")
    status: Optional[str] = Field(default=None, description="draft | running | paused | completed | archived")
    target_metrics: List[str] = Field(default_factory=list, description="目标指标")
    variants: List[Dict[str, Any]] = Field(default_factory=list, description="实验 variants")
    rollback_rule: str = Field(default="", description="回滚规则")
    acceptance_checks: List[str] = Field(default_factory=list, description="验收项")
    notes: str = Field(default="", description="备注")
    entries: List[Dict[str, Any]] = Field(default_factory=list, description="结构化 entries")


class LiveOpsPipelineSkill(BaseSkill):
    metadata = SkillMetadata(
        name="manage_liveops_pipeline",
        description="管理 remote config 与 experiment catalog，支持 template、validate、preview、apply",
        category="resource",
        tags=["liveops", "remote_config", "experiment", "ab_test", "ops"],
    )

    input_model = LiveOpsParams

    def get_snapshot(
        self,
        *,
        liveops_type: str,
        manifest_path: Optional[str] = None,
    ) -> Dict[str, Any]:
        normalized_type = self._normalize_type(liveops_type)
        project_root = Path(getattr(self.godot_cli, "project_path", ".") or ".").resolve()
        resolved_manifest = self._resolve_manifest_path(project_root, normalized_type, manifest_path)
        entries = self._load_existing_manifest(resolved_manifest)
        counts = self._build_counts(normalized_type, entries)
        return normalize_liveops_profile({
            "liveops_type": normalized_type,
            "manifest_path": f"res://{resolved_manifest.relative_to(project_root).as_posix()}",
            "entry_count": len(entries),
            "active_entry_count": counts["active_entry_count"],
            "rollout_count": counts["rollout_count"],
            "variant_count": counts["variant_count"],
            "target_metric_count": counts["target_metric_count"],
            "entries": entries,
            "issues": [],
            "warnings": [],
            "notes": [],
        })

    def execute(self, task: Task, params: Dict[str, Any]) -> ToolResult:
        p = LiveOpsParams(**params)
        action = self._normalize_action(p.action)
        liveops_type = self._normalize_type(p.liveops_type)
        project_root = Path(getattr(self.godot_cli, "project_path", ".") or ".").resolve()
        layout_validator = ProjectLayoutValidator(project_root=project_root, runtime_root=Path.cwd())
        manifest_path = self._resolve_manifest_path(project_root, liveops_type, p.manifest_path)

        manifest_layout = layout_validator.validate_managed_path(manifest_path, "liveops_manifest")
        if not manifest_layout["passed"]:
            return self.build_result(
                success=False,
                message=f"{LIVEOPS_TYPE_LABELS[liveops_type]} manifest 路径不符合文件树规范",
                params=self.dump_model(p),
                error="; ".join(issue["message"] for issue in manifest_layout["issues"]),
                validation={"passed": False, "issues": [issue["code"] for issue in manifest_layout["issues"]]},
            )

        current_manifest = self._load_existing_manifest(manifest_path)
        raw_entries = self._resolve_entries(p, liveops_type, action)
        if not raw_entries and action in {"validate", "preview", "apply"}:
            raw_entries = [dict(entry) for entry in current_manifest]

        normalized_entries, issues, warnings = self._normalize_entries(
            entries=raw_entries,
            liveops_type=liveops_type,
        )
        merged_entries = self._merge_entries(current_manifest, normalized_entries, liveops_type)
        snapshot_entries = merged_entries if action in {"template", "preview", "apply"} else normalized_entries
        counts = self._build_counts(liveops_type, snapshot_entries)

        snapshot = normalize_liveops_profile({
            "liveops_type": liveops_type,
            "manifest_path": f"res://{manifest_path.relative_to(project_root).as_posix()}",
            "entry_count": len(snapshot_entries),
            "active_entry_count": counts["active_entry_count"],
            "rollout_count": counts["rollout_count"],
            "variant_count": counts["variant_count"],
            "target_metric_count": counts["target_metric_count"],
            "entries": snapshot_entries,
            "issues": issues,
            "warnings": warnings,
            "notes": [f"manifest: res://{manifest_path.relative_to(project_root).as_posix()}"],
        })

        manifest_content = json.dumps({
            "schema_version": LIVEOPS_PROFILE_SCHEMA_VERSION,
            "liveops_type": liveops_type,
            "items": merged_entries,
        }, ensure_ascii=False, indent=2)
        current_content = manifest_path.read_text(encoding="utf-8") if manifest_path.exists() else ""
        diff_text = self._build_diff(current_content, manifest_content, manifest_path)

        report_path = Path("logs/reports") / f"liveops_{liveops_type}_{action}_{int(time.time())}.md"
        report_layout = layout_validator.validate_managed_path(report_path, "runtime_report")
        if not report_layout["passed"]:
            return self.build_result(
                success=False,
                message=f"{LIVEOPS_TYPE_LABELS[liveops_type]} 报告路径不符合文件树规范",
                params=self.dump_model(p),
                error="; ".join(issue["message"] for issue in report_layout["issues"]),
                validation={"passed": False, "issues": [issue["code"] for issue in report_layout["issues"]]},
            )

        report_content = self._build_report(
            liveops_type=liveops_type,
            action=action,
            manifest_path=manifest_path,
            snapshot=snapshot,
            issues=issues,
            warnings=warnings,
            diff_text=diff_text,
        )
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(report_content, encoding="utf-8")

        task.context.setdefault("contract_versions", {})["liveops_profile"] = LIVEOPS_PROFILE_SCHEMA_VERSION
        task.context.update({
            "liveops_type": liveops_type,
            "liveops_action": action,
            "liveops_manifest_path": f"res://{manifest_path.relative_to(project_root).as_posix()}",
            "liveops_entry_count": snapshot["entry_count"],
            "liveops_active_entry_count": snapshot["active_entry_count"],
            "liveops_rollout_count": snapshot["rollout_count"],
            "liveops_variant_count": snapshot["variant_count"],
            "liveops_target_metric_count": snapshot["target_metric_count"],
            "liveops_profile": snapshot,
        })

        artifacts = [
            Artifact(
                name=manifest_path.name,
                path=str(manifest_path),
                type="resource",
                content=manifest_content if len(manifest_content) < 40000 else None,
                metadata={"liveops_type": liveops_type, "action": action, "manifest": True},
            ),
            Artifact(
                name=report_path.name,
                path=str(report_path),
                type="report",
                content=report_content,
                metadata={"liveops_type": liveops_type, "action": action},
            ),
        ]

        if issues and action in {"validate", "preview", "apply"}:
            return self.build_result(
                success=False,
                message=f"{LIVEOPS_TYPE_LABELS[liveops_type]} 校验失败",
                params=self.dump_model(p),
                error="; ".join(issues),
                artifacts=artifacts,
                data={"liveops_profile": snapshot},
                validation={
                    "passed": False,
                    "issues": issues,
                    "checks": [{"name": "liveops_profile_validation", "status": "failed"}],
                },
                rollback={"available": False, "strategy": "validation_failed_no_write"},
            )

        if action == "validate":
            return self.build_result(
                success=True,
                message=f"{LIVEOPS_TYPE_LABELS[liveops_type]} 校验通过",
                params=self.dump_model(p),
                artifacts=artifacts,
                data={"liveops_profile": snapshot},
                validation={
                    "passed": True,
                    "checks": [{"name": "liveops_profile_validation", "status": "passed"}],
                },
                rollback={"available": False, "strategy": "validate_only"},
            )

        if action == "preview":
            return self.build_result(
                success=True,
                message=f"{LIVEOPS_TYPE_LABELS[liveops_type]} 预览完成",
                params=self.dump_model(p),
                artifacts=artifacts,
                data={"liveops_profile": snapshot},
                validation={
                    "passed": True,
                    "checks": [
                        {"name": "liveops_profile_validation", "status": "passed"},
                        {"name": "liveops_diff_built", "status": "passed"},
                    ],
                },
                rollback={"available": False, "strategy": "preview_only"},
            )

        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        manifest_backup = self.backup_existing_file(task, str(manifest_path))
        manifest_path.write_text(manifest_content, encoding="utf-8")
        task.context["liveops_written"] = True

        rollback_paths = [backup.backup_path for backup in task.backups]
        if manifest_backup and manifest_backup not in rollback_paths:
            rollback_paths.append(manifest_backup)
        return self.build_result(
            success=True,
            message=(
                f"{LIVEOPS_TYPE_LABELS[liveops_type]} 模板已生成"
                if action == "template"
                else f"{LIVEOPS_TYPE_LABELS[liveops_type]} 已写入"
            ),
            params=self.dump_model(p),
            artifacts=artifacts,
            data={"liveops_profile": snapshot},
            validation={
                "passed": True,
                "checks": [
                    {"name": "liveops_profile_validation", "status": "passed"},
                    {"name": "liveops_manifest_written", "status": "passed"},
                ],
            },
            rollback={
                "available": True,
                "strategy": "restore_liveops_manifest_backup",
                "backup_paths": rollback_paths,
            },
            metadata={"manifest_path": str(manifest_path)},
        )

    def _normalize_action(self, value: str) -> str:
        normalized = str(value or "preview").strip().lower()
        return normalized if normalized in {"template", "validate", "preview", "apply"} else "preview"

    def _normalize_type(self, value: str) -> str:
        normalized = str(value or "remote_config").strip().lower()
        return normalized if normalized in _LIVEOPS_TYPE_VALUES else "remote_config"

    def _resolve_manifest_path(self, project_root: Path, liveops_type: str, raw_path: Optional[str]) -> Path:
        relative = str(raw_path or LIVEOPS_SCHEMAS[liveops_type]["manifest_path"]).strip()
        if relative.startswith("res://"):
            relative = relative.replace("res://", "", 1)
        return (project_root / relative).resolve()

    def _resolve_entries(self, params: LiveOpsParams, liveops_type: str, action: str) -> List[Dict[str, Any]]:
        if params.entries:
            return [dict(entry) for entry in params.entries]

        if action == "template":
            entries = [dict(entry) for entry in LIVEOPS_SCHEMAS[liveops_type]["sample_entries"]]
            if params.entry_id:
                entries[0][self._entry_key_name(liveops_type)] = self._snake_case(params.entry_id)
            return entries

        single_entry = {
            "owner": params.owner,
            "notes": params.notes,
            "acceptance_checks": list(params.acceptance_checks or []),
        }
        if liveops_type == "remote_config":
            single_entry.update({
                "config_key": params.entry_id,
                "value_type": params.value_type,
                "default_value": params.default_value,
                "enabled": params.enabled,
                "requires_restart": params.requires_restart,
                "environments": list(params.environments or []),
                "rollout_strategy": params.rollout_strategy,
                "rollout_percentage": params.rollout_percentage,
                "audience_segments": list(params.audience_segments or []),
                "tags": list(params.tags or []),
            })
        else:
            single_entry.update({
                "experiment_id": params.entry_id,
                "status": params.status,
                "hypothesis": params.hypothesis,
                "audience_segments": list(params.audience_segments or []),
                "target_metrics": list(params.target_metrics or []),
                "rollout_percentage": params.rollout_percentage,
                "rollback_rule": params.rollback_rule,
                "variants": [dict(item) for item in params.variants],
            })
        if any(value not in (None, "", [], {}) for value in single_entry.values()):
            return [single_entry]
        return []

    def _load_existing_manifest(self, manifest_path: Path) -> List[Dict[str, Any]]:
        if not manifest_path.exists():
            return []
        try:
            payload = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return []
        if isinstance(payload, dict):
            payload = payload.get("items") or payload.get("entries") or []
        if not isinstance(payload, list):
            return []
        return [dict(entry) for entry in payload if isinstance(entry, dict)]

    def _merge_entries(self, current_entries: List[Dict[str, Any]], new_entries: List[Dict[str, Any]], liveops_type: str) -> List[Dict[str, Any]]:
        key_name = self._entry_key_name(liveops_type)
        merged: Dict[str, Dict[str, Any]] = {}
        ordered_keys: List[str] = []
        for entry in current_entries:
            key = str(entry.get(key_name) or "").strip()
            if not key:
                continue
            merged[key] = dict(entry)
            ordered_keys.append(key)
        for entry in new_entries:
            key = str(entry.get(key_name) or "").strip()
            if not key:
                continue
            if key not in merged:
                ordered_keys.append(key)
            merged[key] = dict(entry)
        return [merged[key] for key in ordered_keys if key in merged]

    def _normalize_entries(
        self,
        *,
        entries: List[Dict[str, Any]],
        liveops_type: str,
    ) -> Tuple[List[Dict[str, Any]], List[str], List[str]]:
        if not entries:
            return [], [f"{LIVEOPS_TYPE_LABELS[liveops_type]} 条目不能为空"], []

        normalized_entries: List[Dict[str, Any]] = []
        issues: List[str] = []
        warnings: List[str] = []
        seen_ids = set()
        key_name = self._entry_key_name(liveops_type)

        for index, raw_entry in enumerate(entries, start=1):
            if liveops_type == "remote_config":
                entry, entry_issues, entry_warnings = self._normalize_remote_config_entry(raw_entry)
            else:
                entry, entry_issues, entry_warnings = self._normalize_experiment_entry(raw_entry)

            entry_id = str(entry.get(key_name) or "").strip()
            if not entry_id:
                entry_issues.append(f"第 {index} 条 {key_name} 不能为空")
            elif entry_id in seen_ids:
                entry_issues.append(f"{key_name} 重复: {entry_id}")
            seen_ids.add(entry_id)

            normalized_entries.append(entry)
            issues.extend(entry_issues)
            warnings.extend(entry_warnings)
        return normalized_entries, issues, warnings

    def _normalize_remote_config_entry(self, raw_entry: Dict[str, Any]) -> Tuple[Dict[str, Any], List[str], List[str]]:
        issues: List[str] = []
        warnings: List[str] = []
        config_key = self._snake_case(raw_entry.get("config_key") or raw_entry.get("entry_id") or "")
        value_type = self._normalize_value_type(raw_entry.get("value_type"), raw_entry.get("default_value"))
        default_value = raw_entry.get("default_value")
        environments = self._normalize_text_list(raw_entry.get("environments")) or ["dev", "qa", "live"]
        rollout_strategy = self._normalize_rollout_strategy(raw_entry.get("rollout_strategy"))
        rollout_percentage = self._normalize_percentage(raw_entry.get("rollout_percentage"), 100.0 if rollout_strategy == "global" else 0.0)
        audience_segments = self._normalize_text_list(raw_entry.get("audience_segments"))
        tags = self._normalize_text_list(raw_entry.get("tags"))
        acceptance_checks = self._normalize_text_list(raw_entry.get("acceptance_checks"))

        if not config_key:
            issues.append("Remote Config 条目缺少 config_key")
        elif not _SNAKE_CASE_RE.match(config_key):
            issues.append(f"Remote Config config_key 必须使用 snake_case: {config_key}")
        if any(item not in _LIVEOPS_ENVIRONMENTS for item in environments):
            issues.append(f"Remote Config {config_key or 'unnamed'} 使用了非法 environments")
        if rollout_strategy == "percentage" and rollout_percentage <= 0:
            issues.append(f"Remote Config {config_key or 'unnamed'} 的 percentage rollout 必须大于 0")
        if rollout_strategy in {"segment", "whitelist"} and not audience_segments:
            issues.append(f"Remote Config {config_key or 'unnamed'} 的 {rollout_strategy} rollout 需要 audience_segments")
        if not self._value_matches_type(default_value, value_type):
            issues.append(f"Remote Config {config_key or 'unnamed'} 的 default_value 与 value_type={value_type} 不匹配")
        if not str(raw_entry.get("owner") or "").strip():
            warnings.append(f"Remote Config {config_key or 'unnamed'} 缺少 owner")

        entry = {
            "liveops_type": "remote_config",
            "config_key": config_key,
            "value_type": value_type,
            "default_value": default_value,
            "owner": str(raw_entry.get("owner") or "").strip(),
            "enabled": bool(raw_entry.get("enabled", True)),
            "requires_restart": bool(raw_entry.get("requires_restart")),
            "environments": environments,
            "rollout_strategy": rollout_strategy,
            "rollout_percentage": rollout_percentage,
            "audience_segments": audience_segments,
            "tags": tags,
            "acceptance_checks": acceptance_checks,
            "notes": str(raw_entry.get("notes") or "").strip(),
        }
        return entry, issues, warnings

    def _normalize_experiment_entry(self, raw_entry: Dict[str, Any]) -> Tuple[Dict[str, Any], List[str], List[str]]:
        issues: List[str] = []
        warnings: List[str] = []
        experiment_id = self._snake_case(raw_entry.get("experiment_id") or raw_entry.get("entry_id") or "")
        status = self._normalize_experiment_status(raw_entry.get("status"))
        hypothesis = str(raw_entry.get("hypothesis") or "").strip()
        target_metrics = self._normalize_text_list(raw_entry.get("target_metrics"))
        audience_segments = self._normalize_text_list(raw_entry.get("audience_segments"))
        acceptance_checks = self._normalize_text_list(raw_entry.get("acceptance_checks"))
        rollout_percentage = self._normalize_percentage(raw_entry.get("rollout_percentage"), 0.0)
        rollback_rule = str(raw_entry.get("rollback_rule") or "").strip()

        variants: List[Dict[str, Any]] = []
        seen_variant_ids = set()
        total_weight = 0.0
        for index, raw_variant in enumerate(list(raw_entry.get("variants") or []), start=1):
            variant_payload = dict(raw_variant or {})
            variant_id = self._snake_case(variant_payload.get("variant_id") or f"variant_{index}")
            weight = round(float(variant_payload.get("weight") or 0.0), 2)
            total_weight += weight
            if variant_id in seen_variant_ids:
                issues.append(f"Experiment {experiment_id or 'unnamed'} 的 variant_id 重复: {variant_id}")
            seen_variant_ids.add(variant_id)
            if weight <= 0:
                issues.append(f"Experiment {experiment_id or 'unnamed'} 的 variant {variant_id} weight 必须大于 0")
            variants.append({
                "variant_id": variant_id,
                "weight": weight,
                "config_overrides": dict(variant_payload.get("config_overrides") or {}),
            })

        if not experiment_id:
            issues.append("Experiment 条目缺少 experiment_id")
        elif not _SNAKE_CASE_RE.match(experiment_id):
            issues.append(f"Experiment experiment_id 必须使用 snake_case: {experiment_id}")
        if not hypothesis:
            issues.append(f"Experiment {experiment_id or 'unnamed'} 缺少 hypothesis")
        if not target_metrics:
            issues.append(f"Experiment {experiment_id or 'unnamed'} 缺少 target_metrics")
        if len(variants) < 2:
            issues.append(f"Experiment {experiment_id or 'unnamed'} 至少需要 2 个 variants")
        if variants and abs(total_weight - 100.0) > 0.01:
            issues.append(f"Experiment {experiment_id or 'unnamed'} 的 variants weight 总和必须为 100")
        if status == "running" and rollout_percentage <= 0:
            issues.append(f"Experiment {experiment_id or 'unnamed'} 运行中时 rollout_percentage 必须大于 0")
        if status == "running" and not rollback_rule:
            issues.append(f"Experiment {experiment_id or 'unnamed'} 运行中时必须提供 rollback_rule")
        if not str(raw_entry.get("owner") or "").strip():
            warnings.append(f"Experiment {experiment_id or 'unnamed'} 缺少 owner")

        entry = {
            "liveops_type": "experiment_catalog",
            "experiment_id": experiment_id,
            "status": status,
            "hypothesis": hypothesis,
            "owner": str(raw_entry.get("owner") or "").strip(),
            "audience_segments": audience_segments,
            "target_metrics": target_metrics,
            "rollout_percentage": rollout_percentage,
            "rollback_rule": rollback_rule,
            "variants": variants,
            "acceptance_checks": acceptance_checks,
            "notes": str(raw_entry.get("notes") or "").strip(),
        }
        return entry, issues, warnings

    def _build_counts(self, liveops_type: str, entries: List[Dict[str, Any]]) -> Dict[str, int]:
        active_entry_count = 0
        rollout_count = 0
        variant_count = 0
        target_metric_count = 0
        for entry in entries:
            if liveops_type == "remote_config":
                if bool(entry.get("enabled")):
                    active_entry_count += 1
                rollout_strategy = str(entry.get("rollout_strategy") or "").strip().lower()
                rollout_percentage = float(entry.get("rollout_percentage") or 0.0)
                if rollout_strategy in {"percentage", "segment", "whitelist"} or (0.0 < rollout_percentage < 100.0):
                    rollout_count += 1
            else:
                if str(entry.get("status") or "").strip().lower() == "running":
                    active_entry_count += 1
                if float(entry.get("rollout_percentage") or 0.0) > 0.0:
                    rollout_count += 1
                variant_count += len(list(entry.get("variants") or []))
                target_metric_count += len(self._normalize_text_list(entry.get("target_metrics")))
        return {
            "active_entry_count": active_entry_count,
            "rollout_count": rollout_count,
            "variant_count": variant_count,
            "target_metric_count": target_metric_count,
        }

    def _build_diff(self, before_text: str, after_text: str, manifest_path: Path) -> str:
        return "\n".join(difflib.unified_diff(
            before_text.splitlines(),
            after_text.splitlines(),
            fromfile=str(manifest_path) + ".before",
            tofile=str(manifest_path),
            lineterm="",
        ))

    def _build_report(
        self,
        *,
        liveops_type: str,
        action: str,
        manifest_path: Path,
        snapshot: Dict[str, Any],
        issues: List[str],
        warnings: List[str],
        diff_text: str,
    ) -> str:
        project_root = Path(getattr(self.godot_cli, "project_path", ".") or ".").resolve()
        lines = [
            f"# {LIVEOPS_TYPE_LABELS[liveops_type]} Report",
            "",
            f"- Action: {action}",
            f"- Manifest: res://{manifest_path.relative_to(project_root).as_posix()}",
            f"- Entry Count: {snapshot['entry_count']}",
            f"- Active Entry Count: {snapshot['active_entry_count']}",
            f"- Rollout Count: {snapshot['rollout_count']}",
            f"- Variant Count: {snapshot['variant_count']}",
            f"- Target Metric Count: {snapshot['target_metric_count']}",
            "",
            "## Issues",
        ]
        lines.extend([f"- {issue}" for issue in issues] or ["- Validation passed"])
        lines.extend(["", "## Warnings"])
        lines.extend([f"- {warning}" for warning in warnings] or ["- None"])
        lines.extend(["", "## Entries"])
        for entry in snapshot.get("entries") or []:
            lines.append(f"- {entry.get(self._entry_key_name(liveops_type)) or 'unnamed'}")
        lines.extend(["", "## Diff", "```diff", diff_text or "# no diff", "```"])
        return "\n".join(lines) + "\n"

    def _entry_key_name(self, liveops_type: str) -> str:
        return "config_key" if liveops_type == "remote_config" else "experiment_id"

    def _snake_case(self, value: Any) -> str:
        text = str(value or "").strip().lower()
        text = re.sub(r"[^a-z0-9]+", "_", text)
        return re.sub(r"_+", "_", text).strip("_")

    def _normalize_text_list(self, value: Any) -> List[str]:
        if isinstance(value, str):
            parts = re.split(r"[,;\n]", value)
        elif isinstance(value, (list, tuple, set)):
            parts = list(value)
        else:
            return []
        items: List[str] = []
        seen = set()
        for item in parts:
            text = str(item or "").strip()
            if not text or text in seen:
                continue
            items.append(text)
            seen.add(text)
        return items

    def _normalize_rollout_strategy(self, value: Any) -> str:
        normalized = str(value or "global").strip().lower()
        return normalized if normalized in _LIVEOPS_ROLLOUT_STRATEGIES else "global"

    def _normalize_experiment_status(self, value: Any) -> str:
        normalized = str(value or "draft").strip().lower()
        return normalized if normalized in _LIVEOPS_EXPERIMENT_STATUSES else "draft"

    def _normalize_value_type(self, value: Any, default_value: Any) -> str:
        normalized = str(value or "").strip().lower()
        if normalized in _LIVEOPS_VALUE_TYPES:
            return normalized
        if isinstance(default_value, bool):
            return "bool"
        if isinstance(default_value, int) and not isinstance(default_value, bool):
            return "int"
        if isinstance(default_value, float):
            return "float"
        if isinstance(default_value, str):
            return "string"
        if isinstance(default_value, (dict, list)):
            return "json"
        return "string"

    def _normalize_percentage(self, value: Any, default: float) -> float:
        try:
            numeric = float(value if value is not None else default)
        except (TypeError, ValueError):
            numeric = default
        return round(max(0.0, min(100.0, numeric)), 2)

    def _value_matches_type(self, value: Any, value_type: str) -> bool:
        if value_type == "bool":
            return isinstance(value, bool)
        if value_type == "int":
            return isinstance(value, int) and not isinstance(value, bool)
        if value_type == "float":
            return isinstance(value, (int, float)) and not isinstance(value, bool)
        if value_type == "string":
            return isinstance(value, str)
        if value_type == "json":
            return isinstance(value, (dict, list))
        return True

"""
游戏数据表管线技能 (Data Table Pipeline Skill)
职责: 提供模板生成、schema 校验、diff 预览和落盘导入
"""

import csv
import difflib
import json
import time
from io import StringIO
from pathlib import Path
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from ..base import BaseSkill, SkillMetadata
from ...validations import ProjectLayoutValidator
from ...models import Artifact, Task, ToolResult


TABLE_TYPE_LABELS: Dict[str, str] = {
    "dialogue": "对白表",
    "quest": "任务表",
    "enemy": "敌人表",
    "loot": "掉落表",
    "localization": "本地化表",
}


TABLE_SCHEMAS: Dict[str, Dict[str, Any]] = {
    "dialogue": {
        "default_path": "data_tables/dialogue.csv",
        "key": "dialogue_id",
        "columns": [
            {"name": "dialogue_id", "required": True, "unique": True},
            {"name": "speaker", "required": True},
            {"name": "text", "required": True},
            {"name": "emotion", "default": "neutral"},
            {"name": "next_id", "default": ""},
        ],
        "sample_rows": [
            {"dialogue_id": "dlg_intro_001", "speaker": "Guide", "text": "欢迎来到测试场景。", "emotion": "smile", "next_id": "dlg_intro_002"},
            {"dialogue_id": "dlg_intro_002", "speaker": "Player", "text": "开始吧。", "emotion": "neutral", "next_id": ""},
        ],
    },
    "quest": {
        "default_path": "data_tables/quests.csv",
        "key": "quest_id",
        "columns": [
            {"name": "quest_id", "required": True, "unique": True},
            {"name": "title", "required": True},
            {"name": "description", "required": True},
            {"name": "target_count", "required": True, "numeric": True, "min": 1},
            {"name": "reward_gold", "default": "0", "numeric": True, "min": 0},
            {"name": "next_quest_id", "default": ""},
        ],
        "sample_rows": [
            {"quest_id": "quest_intro", "title": "收集金币", "description": "收集 5 枚金币", "target_count": "5", "reward_gold": "100", "next_quest_id": ""},
        ],
    },
    "enemy": {
        "default_path": "data_tables/enemies.csv",
        "key": "enemy_id",
        "columns": [
            {"name": "enemy_id", "required": True, "unique": True},
            {"name": "name", "required": True},
            {"name": "hp", "required": True, "numeric": True, "min": 1},
            {"name": "attack", "required": True, "numeric": True, "min": 0},
            {"name": "move_speed", "default": "120", "numeric": True, "min": 0},
            {"name": "loot_table_id", "default": ""},
        ],
        "sample_rows": [
            {"enemy_id": "slime_basic", "name": "Slime", "hp": "25", "attack": "5", "move_speed": "110", "loot_table_id": "loot_slime"},
        ],
    },
    "loot": {
        "default_path": "data_tables/loot_tables.csv",
        "key": "loot_id",
        "columns": [
            {"name": "loot_id", "required": True, "unique": True},
            {"name": "item_id", "required": True},
            {"name": "drop_rate", "required": True, "numeric": True, "min": 0, "max": 1},
            {"name": "quantity", "default": "1", "numeric": True, "min": 1},
        ],
        "sample_rows": [
            {"loot_id": "loot_slime", "item_id": "coin", "drop_rate": "0.5", "quantity": "2"},
        ],
    },
    "localization": {
        "default_path": "data_tables/localization.csv",
        "key": "key",
        "columns": [
            {"name": "key", "required": True, "unique": True},
            {"name": "zh_CN", "required": True},
            {"name": "en_US", "required": True},
            {"name": "notes", "default": ""},
        ],
        "sample_rows": [
            {"key": "ui.start", "zh_CN": "开始游戏", "en_US": "Start Game", "notes": "主菜单按钮"},
        ],
    },
}


class DataTableParams(BaseModel):
    action: str = Field(default="validate", description="template | validate | preview | apply")
    table_type: str = Field(default="dialogue", description="dialogue | quest | enemy | loot | localization")
    table_path: Optional[str] = Field(default=None, description="目标数据表路径")
    content: Optional[str] = Field(default=None, description="原始 CSV/TSV/JSON 文本")
    rows: List[Dict[str, Any]] = Field(default_factory=list, description="结构化行数据")


class DataTablePipelineSkill(BaseSkill):
    metadata = SkillMetadata(
        name="manage_game_data_tables",
        description="管理游戏数据表，支持模板生成、schema 校验、diff 预览和导入落盘",
        category="resource",
        tags=["data", "table", "csv", "json", "schema"],
    )

    input_model = DataTableParams

    def get_schema(self, table_type: str) -> Dict[str, Any]:
        normalized_type = self._normalize_table_type(table_type)
        return TABLE_SCHEMAS[normalized_type]

    def get_table_snapshot(
        self,
        table_type: str,
        table_path: Optional[str] = None,
        rows: Optional[List[Dict[str, Any]]] = None,
        content: Optional[str] = None,
    ) -> Dict[str, Any]:
        normalized_type = self._normalize_table_type(table_type)
        schema = TABLE_SCHEMAS[normalized_type]
        project_root = Path(getattr(self.godot_cli, "project_path", ".") or ".").resolve()
        resolved_path = self._resolve_table_path(project_root, normalized_type, table_path)
        exists = resolved_path.exists()
        if rows:
            resolved_rows = [dict(row) for row in rows]
            normalized_rows, issues = self._validate_rows(schema, resolved_rows)
            resolved_content = self._render_rows(normalized_rows, resolved_path.suffix or ".csv", schema)
        else:
            resolved_content = content if content is not None else (
                resolved_path.read_text(encoding="utf-8") if exists else ""
            )
            resolved_rows = self._parse_rows(resolved_content, str(resolved_path)) if str(resolved_content).strip() else []
            normalized_rows = []
            issues = []
            if resolved_rows:
                normalized_rows, issues = self._validate_rows(schema, resolved_rows)

        return {
            "table_type": normalized_type,
            "table_label": TABLE_TYPE_LABELS.get(normalized_type, normalized_type),
            "table_path": str(resolved_path),
            "default_path": str((project_root / schema["default_path"]).resolve()),
            "exists": exists,
            "schema": schema,
            "rows": normalized_rows,
            "content": resolved_content,
            "columns": [column["name"] for column in schema["columns"]],
            "row_count": len(normalized_rows),
            "issue_count": len(issues),
            "issues": issues,
            "sample_rows": list(schema.get("sample_rows") or []),
        }

    def execute(self, task: Task, params: Dict[str, Any]) -> ToolResult:
        p = DataTableParams(**params)
        table_type = self._normalize_table_type(p.table_type)
        action = self._normalize_action(p.action)
        schema = TABLE_SCHEMAS[table_type]
        project_root = Path(getattr(self.godot_cli, "project_path", ".") or ".").resolve()
        table_path = self._resolve_table_path(project_root, table_type, p.table_path)
        current_content = table_path.read_text(encoding="utf-8") if table_path.exists() else ""
        layout_validator = ProjectLayoutValidator(project_root=project_root, runtime_root=Path.cwd())

        table_layout = layout_validator.validate_managed_path(table_path, "data_table")
        if not table_layout["passed"]:
            return self.build_result(
                success=False,
                message=f"{table_type} 数据表路径不符合文件树规范",
                params=self.dump_model(p),
                error="; ".join(issue["message"] for issue in table_layout["issues"]),
                validation={"passed": False, "issues": [issue["code"] for issue in table_layout["issues"]]},
            )

        rows = self._resolve_rows(p, schema, current_content)
        normalized_rows, issues = self._validate_rows(schema, rows)
        rendered = self._render_rows(normalized_rows, table_path.suffix or ".csv", schema)
        diff_text = self._build_diff(current_content, rendered, table_path)
        report_content = self._build_report(table_type, action, table_path, schema, normalized_rows, issues, diff_text)
        report_path = Path("logs/reports") / f"data_table_{table_type}_{action}_{int(time.time())}.md"
        report_layout = layout_validator.validate_managed_path(report_path, "runtime_report")
        if not report_layout["passed"]:
            return self.build_result(
                success=False,
                message=f"{table_type} 数据表报告路径不符合文件树规范",
                params=self.dump_model(p),
                error="; ".join(issue["message"] for issue in report_layout["issues"]),
                validation={"passed": False, "issues": [issue["code"] for issue in report_layout["issues"]]},
            )
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(report_content, encoding="utf-8")

        schema_artifact = Artifact(
            name=f"{table_type}_schema.json",
            path=f"internal://{table_type}_schema.json",
            type="report",
            content=json.dumps(schema, ensure_ascii=False, indent=2),
            metadata={"table_type": table_type, "action": action},
        )
        report_artifact = Artifact(
            name=report_path.name,
            path=str(report_path),
            type="report",
            content=report_content,
            metadata={"table_type": table_type, "action": action},
        )
        artifacts = [schema_artifact, report_artifact]

        task.context.update({
            "data_table_type": table_type,
            "data_table_action": action,
            "data_table_path": str(table_path),
            "data_table_row_count": len(normalized_rows),
            "data_table_issue_count": len(issues),
            "data_table_columns": [column["name"] for column in schema["columns"]],
            "data_table_layout_schema_version": table_layout["schema_version"],
        })

        if action in {"template", "apply"} and issues:
            return self.build_result(
                success=False,
                message=f"{table_type} 数据表校验失败",
                params=self.dump_model(p),
                error="; ".join(issues),
                artifacts=artifacts,
                validation={"passed": False, "issues": issues},
            )

        if action == "validate":
            if issues:
                return self.build_result(
                    success=False,
                    message=f"{table_type} 数据表校验失败",
                    params=self.dump_model(p),
                    error="; ".join(issues),
                    artifacts=artifacts,
                    validation={"passed": False, "issues": issues},
                )
            return self.build_result(
                success=True,
                message=f"{table_type} 数据表校验通过",
                params=self.dump_model(p),
                artifacts=artifacts,
                validation={"passed": True, "checks": [{"name": "schema_validation", "status": "passed"}]},
                rollback={"available": False, "strategy": "no_write_validate_only"},
            )

        if action == "preview":
            message = f"{table_type} 数据表预览完成"
            if issues:
                message += f"，发现 {len(issues)} 个问题"
                return self.build_result(
                    success=False,
                    message=message,
                    params=self.dump_model(p),
                    error="; ".join(issues),
                    artifacts=artifacts,
                    validation={"passed": False, "issues": issues},
                )
            return self.build_result(
                success=True,
                message=message,
                params=self.dump_model(p),
                artifacts=artifacts,
                validation={"passed": True, "checks": [{"name": "preview_ready", "status": "passed"}]},
                rollback={"available": False, "strategy": "preview_only"},
            )

        table_path.parent.mkdir(parents=True, exist_ok=True)
        table_path.write_text(rendered, encoding="utf-8")
        table_artifact = Artifact(
            name=table_path.name,
            path=str(table_path),
            type="resource",
            content=rendered if len(rendered) < 20000 else None,
            metadata={"table_type": table_type, "action": action},
        )
        artifacts.append(table_artifact)
        task.context["data_table_written"] = True
        if action == "template":
            return self.build_result(
                success=True,
                message=f"{table_type} 数据表模板已创建",
                params=self.dump_model(p),
                artifacts=artifacts,
                validation={"passed": True, "checks": [{"name": "schema_validation", "status": "passed"}]},
                rollback={"available": True, "strategy": "delete_or_restore_table_file", "backup_paths": [str(table_path)]},
            )
        return self.build_result(
            success=True,
            message=f"{table_type} 数据表已导入",
            params=self.dump_model(p),
            artifacts=artifacts,
            validation={"passed": True, "checks": [{"name": "schema_validation", "status": "passed"}]},
            rollback={"available": True, "strategy": "overwrite_table_file", "backup_paths": [str(table_path)]},
        )

    def _normalize_table_type(self, value: str) -> str:
        normalized = str(value or "dialogue").strip().lower()
        return normalized if normalized in TABLE_SCHEMAS else "dialogue"

    def _normalize_action(self, value: str) -> str:
        normalized = str(value or "validate").strip().lower()
        return normalized if normalized in {"template", "validate", "preview", "apply"} else "validate"

    def _resolve_table_path(self, project_root: Path, table_type: str, raw_path: Optional[str]) -> Path:
        if raw_path:
            path_text = str(raw_path).strip()
            if path_text.startswith("res://"):
                return (project_root / path_text.replace("res://", "", 1)).resolve()
            return (project_root / path_text).resolve()
        return (project_root / TABLE_SCHEMAS[table_type]["default_path"]).resolve()

    def _resolve_rows(self, params: DataTableParams, schema: Dict[str, Any], current_content: str) -> List[Dict[str, Any]]:
        if params.rows:
            return params.rows
        if params.content:
            return self._parse_rows(params.content, params.table_path)
        if self._normalize_action(params.action) == "template":
            return list(schema.get("sample_rows") or [])
        if current_content:
            return self._parse_rows(current_content, params.table_path or schema["default_path"])
        return []

    def _parse_rows(self, content: str, path_hint: Optional[str]) -> List[Dict[str, Any]]:
        text = str(content or "").strip()
        if not text:
            return []
        if text.startswith("{") or text.startswith("["):
            payload = json.loads(text)
            if isinstance(payload, dict):
                payload = payload.get("rows") or payload.get("items") or []
            return [dict(item) for item in payload if isinstance(item, dict)]

        suffix = Path(path_hint or "table.csv").suffix.lower()
        delimiter = "\t" if suffix == ".tsv" else ","
        reader = csv.DictReader(StringIO(text), delimiter=delimiter)
        return [dict(row) for row in reader]

    def _validate_rows(self, schema: Dict[str, Any], rows: List[Dict[str, Any]]) -> tuple[List[Dict[str, str]], List[str]]:
        issues: List[str] = []
        key_name = schema["key"]
        seen_keys = set()
        normalized_rows: List[Dict[str, str]] = []

        for row_index, raw_row in enumerate(rows, start=2):
            normalized_row: Dict[str, str] = {}
            for column in schema["columns"]:
                name = column["name"]
                value = raw_row.get(name, column.get("default", ""))
                value_text = str(value if value is not None else "").strip()
                normalized_row[name] = value_text
                if column.get("required") and not value_text:
                    issues.append(f"第 {row_index} 行字段 {name} 不能为空")
                if value_text and column.get("numeric"):
                    try:
                        numeric_value = float(value_text)
                    except ValueError:
                        issues.append(f"第 {row_index} 行字段 {name} 必须是数字")
                    else:
                        if "min" in column and numeric_value < column["min"]:
                            issues.append(f"第 {row_index} 行字段 {name} 不能小于 {column['min']}")
                        if "max" in column and numeric_value > column["max"]:
                            issues.append(f"第 {row_index} 行字段 {name} 不能大于 {column['max']}")

            key_value = normalized_row.get(key_name, "")
            if key_value:
                if key_value in seen_keys:
                    issues.append(f"主键 {key_name}={key_value} 重复")
                seen_keys.add(key_value)
            normalized_rows.append(normalized_row)

        if not normalized_rows:
            issues.append("数据表不能为空")
        return normalized_rows, issues

    def _render_rows(self, rows: List[Dict[str, str]], suffix: str, schema: Dict[str, Any]) -> str:
        fieldnames = [column["name"] for column in schema["columns"]]
        if suffix.lower() == ".json":
            return json.dumps(rows, ensure_ascii=False, indent=2)

        delimiter = "\t" if suffix.lower() == ".tsv" else ","
        buffer = StringIO()
        writer = csv.DictWriter(buffer, fieldnames=fieldnames, delimiter=delimiter, lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow({name: row.get(name, "") for name in fieldnames})
        return buffer.getvalue()

    def _build_diff(self, before: str, after: str, table_path: Path) -> str:
        before_lines = before.splitlines()
        after_lines = after.splitlines()
        diff = difflib.unified_diff(
            before_lines,
            after_lines,
            fromfile=f"a/{table_path.name}",
            tofile=f"b/{table_path.name}",
            lineterm="",
        )
        return "\n".join(diff)

    def _build_report(
        self,
        table_type: str,
        action: str,
        table_path: Path,
        schema: Dict[str, Any],
        rows: List[Dict[str, str]],
        issues: List[str],
        diff_text: str,
    ) -> str:
        lines = [
            f"# Data Table Report: {table_type}",
            "",
            f"- Action: {action}",
            f"- Path: {table_path}",
            f"- Row Count: {len(rows)}",
            f"- Columns: {', '.join(column['name'] for column in schema['columns'])}",
            f"- Issue Count: {len(issues)}",
            "",
            "## Validation",
            "",
        ]
        lines.extend([f"- {issue}" for issue in issues] or ["- Validation passed"])
        lines.extend(["", "## Preview Rows", ""])
        lines.extend([
            f"- {schema['key']}: {row.get(schema['key'], '')}"
            for row in rows[:10]
        ] or ["- No rows"])
        lines.extend(["", "## Diff", "", "```diff", diff_text or "(no diff)", "```"])
        return "\n".join(lines)

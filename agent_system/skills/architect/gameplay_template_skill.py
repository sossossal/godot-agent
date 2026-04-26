"""
Gameplay template management skill.

Responsibilities:
- preview starter gameplay system packs by genre template
- apply starter gameplay system packs into blueprint context
- emit structured reports for Portal, MCP, and future provider integrations
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from ..base import BaseSkill, SkillMetadata
from ...models import Artifact, Task, ToolResult
from ...tools.blueprint_manager import BlueprintManager
from ...tools.template_registry import GenreTemplateRegistry
from ...validations import ProjectLayoutValidator


class GameplayTemplateParams(BaseModel):
    action: str = Field(default="preview", description="preview | apply")
    template_id: Optional[str] = Field(default=None, description="模板 ID, 如 platformer")
    game_genre: Optional[str] = Field(default=None, description="游戏类型名称")
    include_system_ids: List[str] = Field(default_factory=list, description="仅输出指定 system_id")
    notes: str = Field(default="", description="附加备注")


class GameplayTemplateSkill(BaseSkill):
    metadata = SkillMetadata(
        name="manage_gameplay_template",
        description="按游戏类型输出并应用 starter gameplay systems 模板。",
        category="architect",
        tags=["architect", "gameplay", "template", "feature-pack"],
    )

    input_model = GameplayTemplateParams

    def execute(self, task: Task, params: Dict[str, Any]) -> ToolResult:
        p = GameplayTemplateParams(**params)
        action = self._normalize_action(p.action)
        project_root = Path(getattr(self.godot_cli, "project_path", ".") or ".").resolve()
        layout_validator = ProjectLayoutValidator(project_root=project_root, runtime_root=Path.cwd())
        registry = GenreTemplateRegistry(project_path=str(project_root))

        template_query = (
            p.template_id
            or p.game_genre
            or (task.context.get("project_template") or {}).get("template_id")
            or task.context.get("gameplay_template_id")
        )
        snapshot = registry.build_gameplay_template_snapshot(template_query, include_system_ids=p.include_system_ids or None)
        if not snapshot:
            return self.build_result(
                success=False,
                message="未找到匹配的玩法模板",
                params=self.dump_model(p),
                error=f"template not found: {template_query or 'default'}",
                validation={"passed": False, "issues": ["missing_gameplay_template"]},
            )

        report_path = Path("logs/reports") / f"gameplay_template_{snapshot['template_id']}_{action}_{int(time.time())}.md"
        report_layout = layout_validator.validate_managed_path(report_path, "runtime_report")
        if not report_layout["passed"]:
            return self.build_result(
                success=False,
                message="玩法模板报告路径不符合文件树规范",
                params=self.dump_model(p),
                error="; ".join(issue["message"] for issue in report_layout["issues"]),
                validation={"passed": False, "issues": [issue["code"] for issue in report_layout["issues"]]},
            )

        report_content = self._build_report(snapshot, action=action, notes=p.notes)
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(report_content, encoding="utf-8")

        json_content = json.dumps(snapshot, ensure_ascii=False, indent=2)
        artifacts = [
            Artifact(
                name=f"{snapshot['template_id']}_gameplay_template.json",
                path=f"internal://gameplay_template/{snapshot['template_id']}.json",
                type="gameplay_template",
                content=json_content,
                metadata={"template_id": snapshot["template_id"], "action": action},
            ),
            Artifact(
                name=report_path.name,
                path=str(report_path),
                type="report",
                content=report_content,
                metadata={"template_id": snapshot["template_id"], "action": action},
            ),
        ]

        task.context["gameplay_template_id"] = snapshot["template_id"]
        task.context["starter_gameplay_systems"] = list(snapshot.get("starter_gameplay_systems") or [])
        task.context["gameplay_system_count"] = snapshot["system_count"]
        task.context["gameplay_acceptance_checks"] = list(snapshot.get("acceptance_checks") or [])

        if action == "preview":
            return self.build_result(
                success=True,
                message=f"玩法模板 {snapshot['template_id']} 预览完成",
                params=self.dump_model(p),
                data={"gameplay_template": snapshot},
                artifacts=artifacts,
                validation={
                    "passed": True,
                    "checks": [
                        {"name": "gameplay_template_resolved", "status": "passed"},
                        {"name": "gameplay_template_report_generated", "status": "passed"},
                    ],
                },
                rollback={"available": False, "strategy": "preview_only"},
            )

        blueprint = task.context.get("blueprint_manager")
        if not blueprint:
            blueprint = BlueprintManager(str(project_root))
            task.context["blueprint_manager"] = blueprint
        resolved_template = registry.resolve_genre_template(snapshot["template_id"])
        if resolved_template:
            template_snapshot = registry.build_template_snapshot(resolved_template)
            if not dict(getattr(blueprint.blueprint, "project_template", {}) or {}):
                blueprint.blueprint.project_template = template_snapshot
                blueprint.blueprint.game_genre = template_snapshot["game_genre"]
            if not task.context.get("project_template"):
                task.context["project_template"] = template_snapshot

        seeded_features = blueprint.upsert_gameplay_systems(
            snapshot["template_id"],
            list(snapshot.get("starter_gameplay_systems") or []),
            creation_skill=self.metadata.name,
            creation_params=self.dump_model(p),
        )

        if task.context.get("project_template"):
            task.context["project_template"] = {
                **dict(task.context.get("project_template") or {}),
                "starter_gameplay_systems": list(snapshot.get("starter_gameplay_systems") or []),
            }
        task.context["gameplay_template_applied"] = True
        task.context["gameplay_seeded_features"] = seeded_features

        return self.build_result(
            success=True,
            message=f"玩法模板 {snapshot['template_id']} 已应用到蓝图",
            params=self.dump_model(p),
            data={
                "gameplay_template": snapshot,
                "seeded_feature_names": seeded_features,
            },
            artifacts=artifacts,
            validation={
                "passed": True,
                "checks": [
                    {"name": "gameplay_template_resolved", "status": "passed"},
                    {"name": "gameplay_template_applied", "status": "passed"},
                    {"name": "starter_features_seeded", "status": "passed"},
                ],
            },
            rollback={"available": False, "strategy": "blueprint_snapshot_before_apply_recommended"},
        )

    def _normalize_action(self, action: str) -> str:
        normalized = str(action or "preview").strip().lower()
        if normalized not in {"preview", "apply"}:
            return "preview"
        return normalized

    def _build_report(self, snapshot: Dict[str, Any], *, action: str, notes: str) -> str:
        lines = [
            f"# Gameplay Template {action.title()}",
            "",
            f"- Template ID: `{snapshot['template_id']}`",
            f"- Display Name: `{snapshot['display_name']}`",
            f"- Game Genre: `{snapshot['game_genre']}`",
            f"- System Count: `{snapshot['system_count']}`",
            f"- Acceptance Check Count: `{snapshot['acceptance_check_count']}`",
            "",
            "## Starter Systems",
        ]
        for system in list(snapshot.get("starter_gameplay_systems") or []):
            lines.extend([
                f"### {system['display_name']} (`{system['system_id']}`)",
                f"- Category: `{system['category']}`",
                f"- Summary: {system['summary']}",
                f"- Recommended Skills: {', '.join(system.get('recommended_skills') or ['-'])}",
                f"- Suggested Data Tables: {', '.join(system.get('suggested_data_tables') or ['-'])}",
                f"- Acceptance Checks: {', '.join(system.get('acceptance_checks') or ['-'])}",
                f"- Dependencies: {', '.join(system.get('dependencies') or ['-'])}",
                "",
            ])

        lines.extend([
            "## Starter Data Tables",
            *[f"- `{item}`" for item in list(snapshot.get("starter_data_tables") or [])],
            "",
            "## Recommended Directories",
            *[f"- `{item}`" for item in list(snapshot.get("recommended_directories") or [])],
        ])
        if notes.strip():
            lines.extend(["", "## Notes", notes.strip()])
        lines.append("")
        return "\n".join(lines)

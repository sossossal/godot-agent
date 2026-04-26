"""
项目初始化技能 (Initialize Project Skill)
职责: 为新项目设定游戏类型、编码风格和初步架构蓝图
"""

from pathlib import Path
from typing import Dict, Any, Optional
from pydantic import BaseModel, Field
from ..base import BaseSkill, SkillMetadata
from ...models import Task, ToolResult
from ...tools.template_registry import GenreTemplateRegistry


class InitParams(BaseModel):
    game_genre: str = Field(description="游戏类型, 如 Platformer, RPG, Shooter")
    template_id: Optional[str] = Field(default=None, description="可选模板 ID, 如 platformer, arpg")
    naming_style: str = Field(default="snake_case", description="命名规范")
    use_signal_bus: bool = Field(default=True, description="是否使用信号总线模式")


class InitializeProjectSkill(BaseSkill):
    metadata = SkillMetadata(
        name="init_game_blueprint",
        description="初始化游戏蓝图, 设定项目类型和全局架构规约",
        category="architect",
        tags=["architect", "init", "setup"]
    )
    input_model = InitParams

    def execute(self, task: Task, params: Dict[str, Any]) -> ToolResult:
        p = InitParams(**params)
        
        # 获取蓝图管理器 (通过路由传递或从 task context 寻找)
        # 这里假设技能可以通过实例访问 blueprint_manager
        # (后续需确保 Router 注入此实例)
        blueprint = task.context.get("blueprint_manager")
        if not blueprint:
            return self.build_result(
                success=False,
                message="未找到蓝图管理器实例",
                params=self.dump_model(p),
                validation={"passed": False, "issues": ["missing_blueprint_manager"]},
            )

        project_root = Path(getattr(self.godot_cli, "project_path", ".") or ".").resolve()
        registry = GenreTemplateRegistry(project_path=str(project_root))
        template = registry.resolve_genre_template(p.template_id or p.game_genre)

        if template:
            blueprint.blueprint.game_genre = template["game_genre"]
            blueprint.blueprint.project_template = registry.build_template_snapshot(template)
            blueprint.blueprint.gameplay_template_id = template["template_id"]
            blueprint.blueprint.starter_gameplay_systems = list(template.get("starter_gameplay_systems") or [])
            blueprint.blueprint.ui_styles.update(template.get("default_ui_style") or {})
            blueprint.blueprint.coding_style["naming_convention"] = p.naming_style or template["coding_style"]["naming_convention"]
            blueprint.blueprint.coding_style["signal_pattern"] = "SignalBus" if p.use_signal_bus else "Direct"
            created_directories = registry.ensure_project_directories(template, project_root)
            seeded_gameplay_features = blueprint.upsert_gameplay_systems(
                template["template_id"],
                list(template.get("starter_gameplay_systems") or []),
                creation_skill=self.metadata.name,
                creation_params=self.dump_model(p),
            )
            task.context["project_template"] = blueprint.blueprint.project_template
            task.context["project_template_directories"] = created_directories
            task.context["performance_budget"] = {
                **dict(template.get("performance_budget") or {}),
                **dict(task.context.get("performance_budget") or {}),
            }
            task.context["starter_data_tables"] = list(template.get("starter_data_tables") or [])
            task.context["starter_gameplay_systems"] = list(template.get("starter_gameplay_systems") or [])
            task.context["gameplay_template_id"] = template["template_id"]
            task.context["gameplay_seeded_features"] = seeded_gameplay_features
            template_message = f"{template['display_name']} ({template['template_id']})"
        else:
            blueprint.blueprint.game_genre = p.game_genre
            blueprint.blueprint.project_template = {
                "schema_version": "1.0",
                "template_id": "custom",
                "display_name": str(p.game_genre),
                "game_genre": str(p.game_genre),
                "version": "custom",
                "description": "Custom project template",
                "tags": [],
                "starter_data_tables": [],
                "starter_gameplay_systems": [],
                "recommended_directories": [],
                "performance_budget": {},
            }
            blueprint.blueprint.gameplay_template_id = ""
            blueprint.blueprint.starter_gameplay_systems = []
            blueprint.blueprint.coding_style["naming_convention"] = p.naming_style
            blueprint.blueprint.coding_style["signal_pattern"] = "SignalBus" if p.use_signal_bus else "Direct"
            task.context["project_template"] = blueprint.blueprint.project_template
            task.context["project_template_directories"] = []
            task.context["starter_gameplay_systems"] = []
            task.context["gameplay_template_id"] = ""
            task.context["gameplay_seeded_features"] = []
            template_message = f"custom ({p.game_genre})"

        blueprint.save()

        task.add_log(f"🏗️ 架构师已设定项目基调: {template_message} ({p.naming_style})")
        return self.build_result(
            success=True,
            message=f"项目已初始化为 {template_message} 类型。",
            params=self.dump_model(p),
            validation={
                "passed": True,
                "checks": [
                    {"name": "template_resolved", "status": "passed" if template else "warning"},
                    {"name": "project_template_persisted", "status": "passed"},
                    {"name": "starter_gameplay_systems_seeded", "status": "passed" if template else "skipped"},
                ],
            },
            rollback={"available": False, "strategy": "snapshot_before_init_recommended"},
            metadata={
                "project_template": task.context.get("project_template"),
                "gameplay_template_id": task.context.get("gameplay_template_id"),
                "gameplay_system_count": len(task.context.get("starter_gameplay_systems") or []),
            },
        )

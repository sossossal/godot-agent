"""
Level workflow skill.

Responsibilities:
- scaffold managed level scene + manifest templates
- preview level template diffs without writing
- audit level manifests and scene marker coverage
"""

from __future__ import annotations

import difflib
import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from ..base import BaseSkill, SkillMetadata
from ...models import Artifact, Task, ToolResult
from ...validations import ProjectLayoutValidator


LEVEL_WORKFLOW_SCHEMA_VERSION = "1.1"

LEVEL_TYPE_DEFAULTS: Dict[str, Dict[str, Any]] = {
    "combat": {
        "checkpoints": [{"id": "checkpoint_a", "node_path": "CheckpointA", "position": [480, 0]}],
        "interaction_points": [{"id": "level_exit", "node_path": "LevelExit", "kind": "exit", "position": [960, 0]}],
        "navigation_zones": [{"id": "main_route", "node_path": "NavigationZoneMain", "kind": "walkable"}],
        "tile_layers": [{"id": "ground", "node_path": "TileLayerGround", "kind": "ground", "cell_size": [32, 32], "grid_size": [32, 10]}],
        "navigation_agents": [{"id": "enemy_agent", "node_path": "EnemyNavigationAgent", "kind": "enemy"}],
        "trigger_zones": [{"id": "exit_trigger", "node_path": "TriggerLevelExit", "kind": "exit", "position": [960, 0], "size": [96, 96]}],
        "level_bounds": {"min": [-64, -128], "max": [1088, 384]},
        "collision_layers": [{"name": "world", "layer": 1}, {"name": "player", "layer": 2}, {"name": "enemy", "layer": 3}],
    },
    "puzzle": {
        "checkpoints": [{"id": "checkpoint_a", "node_path": "CheckpointA", "position": [320, 0]}],
        "interaction_points": [
            {"id": "puzzle_console", "node_path": "PuzzleConsole", "kind": "switch", "position": [640, 0]},
            {"id": "level_exit", "node_path": "LevelExit", "kind": "exit", "position": [960, 0]},
        ],
        "navigation_zones": [{"id": "main_route", "node_path": "NavigationZoneMain", "kind": "walkable"}],
        "tile_layers": [{"id": "puzzle_floor", "node_path": "TileLayerPuzzleFloor", "kind": "floor", "cell_size": [32, 32], "grid_size": [30, 10]}],
        "navigation_agents": [{"id": "puzzle_actor_agent", "node_path": "PuzzleActorNavigationAgent", "kind": "puzzle_actor"}],
        "trigger_zones": [{"id": "puzzle_trigger", "node_path": "TriggerPuzzleConsole", "kind": "switch", "position": [640, 0], "size": [96, 96]}],
        "level_bounds": {"min": [-64, -128], "max": [1088, 384]},
        "collision_layers": [{"name": "world", "layer": 1}, {"name": "player", "layer": 2}, {"name": "interactive", "layer": 4}],
    },
    "hub": {
        "checkpoints": [{"id": "checkpoint_a", "node_path": "CheckpointA", "position": [160, 0]}],
        "interaction_points": [
            {"id": "vendor", "node_path": "VendorPoint", "kind": "npc", "position": [480, 0]},
            {"id": "level_exit", "node_path": "LevelExit", "kind": "gate", "position": [960, 0]},
        ],
        "navigation_zones": [
            {"id": "town_square", "node_path": "NavigationZoneTownSquare", "kind": "hub"},
            {"id": "level_route", "node_path": "NavigationZoneMain", "kind": "walkable"},
        ],
        "tile_layers": [{"id": "hub_ground", "node_path": "TileLayerHubGround", "kind": "ground", "cell_size": [32, 32], "grid_size": [40, 14]}],
        "navigation_agents": [{"id": "npc_agent", "node_path": "NpcNavigationAgent", "kind": "npc"}],
        "trigger_zones": [{"id": "gate_trigger", "node_path": "TriggerLevelGate", "kind": "gate", "position": [960, 0], "size": [128, 96]}],
        "level_bounds": {"min": [-128, -160], "max": [1216, 512]},
        "collision_layers": [{"name": "world", "layer": 1}, {"name": "player", "layer": 2}, {"name": "npc", "layer": 5}],
    },
    "boss": {
        "checkpoints": [{"id": "checkpoint_gate", "node_path": "CheckpointGate", "position": [256, 0]}],
        "interaction_points": [
            {"id": "boss_intro", "node_path": "BossIntroTrigger", "kind": "trigger", "position": [640, 0]},
            {"id": "level_exit", "node_path": "LevelExit", "kind": "exit", "position": [1280, 0]},
        ],
        "navigation_zones": [{"id": "arena_nav", "node_path": "NavigationZoneArena", "kind": "arena"}],
        "tile_layers": [{"id": "arena_floor", "node_path": "TileLayerArenaFloor", "kind": "arena", "cell_size": [32, 32], "grid_size": [44, 16]}],
        "navigation_agents": [{"id": "boss_agent", "node_path": "BossNavigationAgent", "kind": "boss"}],
        "trigger_zones": [{"id": "boss_intro_trigger", "node_path": "BossIntroTrigger", "kind": "trigger", "position": [640, 0], "size": [160, 128]}],
        "level_bounds": {"min": [-128, -192], "max": [1408, 576]},
        "collision_layers": [{"name": "world", "layer": 1}, {"name": "player", "layer": 2}, {"name": "boss", "layer": 6}],
    },
}


class LevelWorkflowParams(BaseModel):
    action: str = Field(default="template", description="template | preview | audit | snapshot | diff")
    level_name: str = Field(default="level_01", description="关卡 ID, 推荐 snake_case")
    level_type: str = Field(default="combat", description="combat | puzzle | hub | boss")
    root_type: str = Field(default="Node2D", description="Node2D | Node3D")
    scene_path: Optional[str] = Field(default=None, description="关卡场景路径")
    manifest_path: Optional[str] = Field(default=None, description="关卡 manifest 路径")
    snapshot_path: Optional[str] = Field(default=None, description="关卡快照输出路径")
    compare_snapshot_path: Optional[str] = Field(default=None, description="用于 diff 的历史快照路径")
    template_id: Optional[str] = Field(default=None, description="关联的项目模板 ID")
    spawn_points: List[Dict[str, Any]] = Field(default_factory=list, description="出生点")
    interaction_points: List[Dict[str, Any]] = Field(default_factory=list, description="交互点")
    checkpoints: List[Dict[str, Any]] = Field(default_factory=list, description="检查点")
    navigation_zones: List[Dict[str, Any]] = Field(default_factory=list, description="导航区域")
    navigation_agents: List[Dict[str, Any]] = Field(default_factory=list, description="导航代理")
    tile_layers: List[Dict[str, Any]] = Field(default_factory=list, description="TileMap / GridMap 层")
    trigger_zones: List[Dict[str, Any]] = Field(default_factory=list, description="Area/Trigger 区域")
    collision_layers: List[Dict[str, Any]] = Field(default_factory=list, description="碰撞层约束")
    critical_path: List[str] = Field(default_factory=list, description="关键路径节点 ID")
    level_bounds: Dict[str, Any] = Field(default_factory=dict, description="关卡边界")
    notes: str = Field(default="", description="关卡备注")


class LevelWorkflowSkill(BaseSkill):
    metadata = SkillMetadata(
        name="manage_level_workflow",
        description="管理关卡模板与审计流程，生成受管关卡场景、schema 和验收报告",
        category="dev",
        tags=["level", "scene", "template", "audit", "workflow"],
    )

    input_model = LevelWorkflowParams

    def execute(self, task: Task, params: Dict[str, Any]) -> ToolResult:
        p = LevelWorkflowParams(**params)
        action = self._normalize_action(p.action)
        level_name = self._slugify(p.level_name or "level_01")
        level_type = self._normalize_level_type(p.level_type)
        root_type = "Node3D" if str(p.root_type).strip().lower() == "node3d" else "Node2D"
        project_root = Path(getattr(self.godot_cli, "project_path", ".") or ".").resolve()
        layout_validator = ProjectLayoutValidator(project_root=project_root, runtime_root=Path.cwd())

        scene_res_path = self._resolve_scene_res_path(level_name, p.scene_path)
        scene_full_path = self._resolve_project_path(project_root, scene_res_path)
        manifest_full_path = self._resolve_manifest_path(project_root, level_name, p.manifest_path)
        manifest_res_path = self._to_res_path(project_root, manifest_full_path)
        template_id = self._resolve_template_id(task, p.template_id)

        scene_layout = layout_validator.validate_managed_path(scene_full_path, "generated_scene")
        if not scene_layout["passed"]:
            return self.build_result(
                success=False,
                message="关卡场景路径不符合文件树规范",
                params=self.dump_model(p),
                error="; ".join(issue["message"] for issue in scene_layout["issues"]),
                validation={"passed": False, "issues": [issue["code"] for issue in scene_layout["issues"]]},
            )

        manifest_layout = layout_validator.validate_managed_path(manifest_full_path, "data_table")
        if not manifest_layout["passed"]:
            return self.build_result(
                success=False,
                message="关卡 manifest 路径不符合文件树规范",
                params=self.dump_model(p),
                error="; ".join(issue["message"] for issue in manifest_layout["issues"]),
                validation={"passed": False, "issues": [issue["code"] for issue in manifest_layout["issues"]]},
            )

        level_manifest = self._build_level_manifest(
            level_name=level_name,
            level_type=level_type,
            root_type=root_type,
            scene_path=scene_res_path,
            template_id=template_id,
            params=p,
        )
        scene_content = self._build_scene_content(level_manifest)
        manifest_content = json.dumps(level_manifest, ensure_ascii=False, indent=2)

        report_path = Path("logs/reports") / f"level_workflow_{level_name}_{action}_{int(time.time())}.md"
        report_layout = layout_validator.validate_managed_path(report_path, "runtime_report")
        if not report_layout["passed"]:
            return self.build_result(
                success=False,
                message="关卡报告路径不符合文件树规范",
                params=self.dump_model(p),
                error="; ".join(issue["message"] for issue in report_layout["issues"]),
                validation={"passed": False, "issues": [issue["code"] for issue in report_layout["issues"]]},
            )

        if action == "audit":
            audit_payload = self._audit_level(scene_full_path, manifest_full_path, level_manifest)
            report_content = self._build_audit_report(level_name, audit_payload, scene_res_path, manifest_res_path)
            report_path.parent.mkdir(parents=True, exist_ok=True)
            report_path.write_text(report_content, encoding="utf-8")

            artifacts = [
                Artifact(
                    name=report_path.name,
                    path=str(report_path),
                    type="report",
                    content=report_content,
                    metadata={"level_name": level_name, "action": action},
                )
            ]
            if manifest_full_path.exists():
                artifacts.append(Artifact(
                    name=manifest_full_path.name,
                    path=manifest_res_path,
                    type="data_table",
                    content=manifest_full_path.read_text(encoding="utf-8"),
                    metadata={"level_name": level_name, "level_type": level_type},
                ))

            task.context.update({
                "scene_path": scene_res_path,
                "scene_path_source": "level_workflow",
                "level_name": level_name,
                "level_type": level_type,
                "level_issue_count": len(audit_payload["issues"]),
                "level_scene_path": scene_res_path,
                "level_manifest_path": manifest_res_path,
                "level_schema_version": LEVEL_WORKFLOW_SCHEMA_VERSION,
            })

            if audit_payload["issues"]:
                return self.build_result(
                    success=False,
                    message=f"关卡 {level_name} 审计失败",
                    params=self.dump_model(p),
                    data={
                        "level_name": level_name,
                        "scene_path": scene_res_path,
                        "manifest_path": manifest_res_path,
                        "audit": audit_payload,
                    },
                    error="; ".join(audit_payload["issues"]),
                    artifacts=artifacts,
                    validation={
                        "passed": False,
                        "issues": audit_payload["issues"],
                        "checks": audit_payload["checks"],
                    },
                )

            return self.build_result(
                success=True,
                message=f"关卡 {level_name} 审计通过",
                params=self.dump_model(p),
                data={
                    "level_name": level_name,
                    "scene_path": scene_res_path,
                    "manifest_path": manifest_res_path,
                    "audit": audit_payload,
                },
                artifacts=artifacts,
                validation={
                    "passed": True,
                    "checks": audit_payload["checks"],
                },
                rollback={"available": False, "strategy": "audit_only"},
            )

        if action in {"snapshot", "diff"}:
            snapshot_full_path = self._resolve_snapshot_path(project_root, level_name, p.snapshot_path)
            snapshot_layout = layout_validator.validate_managed_path(snapshot_full_path, "runtime_screenshot")
            if not snapshot_layout["passed"]:
                return self.build_result(
                    success=False,
                    message="关卡快照路径不符合文件树规范",
                    params=self.dump_model(p),
                    error="; ".join(issue["message"] for issue in snapshot_layout["issues"]),
                    validation={"passed": False, "issues": [issue["code"] for issue in snapshot_layout["issues"]]},
                )

            snapshot_payload = self._build_level_snapshot(
                level_name=level_name,
                scene_res_path=scene_res_path,
                manifest_res_path=manifest_res_path,
                scene_full_path=scene_full_path,
                manifest_full_path=manifest_full_path,
                fallback_manifest=level_manifest,
            )
            snapshot_content = json.dumps(snapshot_payload, ensure_ascii=False, indent=2)
            snapshot_full_path.parent.mkdir(parents=True, exist_ok=True)
            snapshot_full_path.write_text(snapshot_content, encoding="utf-8")

            artifacts = [
                Artifact(
                    name=snapshot_full_path.name,
                    path=str(snapshot_full_path),
                    type="level_snapshot",
                    content=snapshot_content,
                    metadata={"level_name": level_name, "action": action, "schema_version": LEVEL_WORKFLOW_SCHEMA_VERSION},
                )
            ]
            task.context.update({
                "scene_path": scene_res_path,
                "scene_path_source": "level_workflow",
                "level_name": level_name,
                "level_type": level_type,
                "level_scene_path": scene_res_path,
                "level_manifest_path": manifest_res_path,
                "level_snapshot_path": str(snapshot_full_path),
                "level_schema_version": LEVEL_WORKFLOW_SCHEMA_VERSION,
                "level_template_id": template_id,
            })

            if action == "snapshot":
                report_content = self._build_snapshot_report(snapshot_payload)
                report_path.parent.mkdir(parents=True, exist_ok=True)
                report_path.write_text(report_content, encoding="utf-8")
                artifacts.append(Artifact(
                    name=report_path.name,
                    path=str(report_path),
                    type="report",
                    content=report_content,
                    metadata={"level_name": level_name, "action": action},
                ))
                return self.build_result(
                    success=True,
                    message=f"关卡 {level_name} 快照已生成",
                    params=self.dump_model(p),
                    data={"snapshot": snapshot_payload},
                    artifacts=artifacts,
                    validation={"passed": True, "checks": [{"name": "level_snapshot_generated", "status": "passed"}]},
                    rollback={"available": False, "strategy": "snapshot_only"},
                )

            compare_snapshot_path = self._resolve_runtime_or_project_path(project_root, p.compare_snapshot_path)
            if compare_snapshot_path is None or not compare_snapshot_path.exists():
                return self.build_result(
                    success=False,
                    message=f"关卡 {level_name} diff 失败",
                    params=self.dump_model(p),
                    error="缺少 compare_snapshot_path 或快照不存在",
                    artifacts=artifacts,
                    validation={"passed": False, "issues": ["missing_compare_snapshot"]},
                )

            previous_snapshot = json.loads(compare_snapshot_path.read_text(encoding="utf-8"))
            diff_payload = self._build_snapshot_diff(previous_snapshot, snapshot_payload)
            report_content = self._build_snapshot_diff_report(level_name, diff_payload, compare_snapshot_path, snapshot_full_path)
            report_path.parent.mkdir(parents=True, exist_ok=True)
            report_path.write_text(report_content, encoding="utf-8")
            artifacts.append(Artifact(
                name=report_path.name,
                path=str(report_path),
                type="report",
                content=report_content,
                metadata={"level_name": level_name, "action": action},
            ))
            task.context["level_diff_status"] = diff_payload["status"]
            task.context["level_diff_added_nodes"] = len(diff_payload["added_nodes"])
            task.context["level_diff_removed_nodes"] = len(diff_payload["removed_nodes"])
            return self.build_result(
                success=True,
                message=f"关卡 {level_name} 快照 diff 已生成",
                params=self.dump_model(p),
                data={"snapshot": snapshot_payload, "diff": diff_payload},
                artifacts=artifacts,
                validation={
                    "passed": True,
                    "checks": [{"name": "level_snapshot_diff_generated", "status": "passed"}],
                },
                rollback={"available": False, "strategy": "diff_only"},
            )

        current_scene = scene_full_path.read_text(encoding="utf-8") if scene_full_path.exists() else ""
        current_manifest = manifest_full_path.read_text(encoding="utf-8") if manifest_full_path.exists() else ""
        diff_text = self._build_diff_bundle(
            scene_res_path=scene_res_path,
            manifest_res_path=manifest_res_path,
            current_scene=current_scene,
            next_scene=scene_content,
            current_manifest=current_manifest,
            next_manifest=manifest_content,
        )
        report_content = self._build_template_report(
            level_manifest=level_manifest,
            action=action,
            diff_text=diff_text,
            scene_res_path=scene_res_path,
            manifest_res_path=manifest_res_path,
        )
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(report_content, encoding="utf-8")

        artifacts = [
            Artifact(
                name=Path(scene_res_path).name,
                path=scene_res_path,
                type="scene",
                content=scene_content,
                metadata={"level_name": level_name, "level_type": level_type, "template_id": template_id},
            ),
            Artifact(
                name=manifest_full_path.name,
                path=manifest_res_path,
                type="data_table",
                content=manifest_content,
                metadata={"level_name": level_name, "level_type": level_type, "template_id": template_id},
            ),
            Artifact(
                name=report_path.name,
                path=str(report_path),
                type="report",
                content=report_content,
                metadata={"level_name": level_name, "action": action},
            ),
        ]

        task.context.update({
            "scene_path": scene_res_path,
            "scene_path_source": "level_workflow",
            "level_name": level_name,
            "level_type": level_type,
            "level_scene_path": scene_res_path,
            "level_manifest_path": manifest_res_path,
            "level_schema_version": LEVEL_WORKFLOW_SCHEMA_VERSION,
            "level_template_id": template_id,
        })

        if action == "preview":
            return self.build_result(
                success=True,
                message=f"关卡 {level_name} 模板预览完成",
                params=self.dump_model(p),
                data={
                    "level_name": level_name,
                    "scene_path": scene_res_path,
                    "manifest_path": manifest_res_path,
                    "level_manifest": level_manifest,
                    "diff": diff_text,
                },
                artifacts=artifacts,
                validation={
                    "passed": True,
                    "checks": [
                        {"name": "scene_template_generated", "status": "passed"},
                        {"name": "manifest_template_generated", "status": "passed"},
                    ],
                },
                rollback={"available": False, "strategy": "preview_only"},
            )

        scene_full_path.parent.mkdir(parents=True, exist_ok=True)
        manifest_full_path.parent.mkdir(parents=True, exist_ok=True)
        scene_backup = self.backup_existing_file(task, str(scene_full_path))
        manifest_backup = self.backup_existing_file(task, str(manifest_full_path))
        scene_full_path.write_text(scene_content, encoding="utf-8")
        manifest_full_path.write_text(manifest_content, encoding="utf-8")

        rollback_paths = [backup.backup_path for backup in task.backups]
        return self.build_result(
            success=True,
            message=f"已生成关卡模板 {level_name}",
            params=self.dump_model(p),
            data={
                "level_name": level_name,
                "scene_path": scene_res_path,
                "manifest_path": manifest_res_path,
                "level_manifest": level_manifest,
                "diff": diff_text,
            },
            artifacts=artifacts,
            validation={
                "passed": True,
                "checks": [
                    {"name": "scene_template_generated", "status": "passed"},
                    {"name": "manifest_template_generated", "status": "passed"},
                    {"name": "level_acceptance_checks_seeded", "status": "passed"},
                ],
            },
            rollback={
                "available": True,
                "strategy": "restore_backups_or_remove_generated_level",
                "paths": [path for path in [scene_backup, manifest_backup] if path] or [scene_res_path, manifest_res_path],
            },
            quality_gate={
                "passed": True,
                "checks": [{"name": "level_template_baseline_ready", "status": "passed"}],
            },
        )

    def _normalize_action(self, action: str) -> str:
        normalized = str(action or "template").strip().lower()
        if normalized not in {"template", "preview", "audit", "snapshot", "diff"}:
            return "template"
        return normalized

    def _normalize_level_type(self, level_type: str) -> str:
        normalized = str(level_type or "combat").strip().lower()
        if normalized not in LEVEL_TYPE_DEFAULTS:
            return "combat"
        return normalized

    def _slugify(self, value: str) -> str:
        lowered = re.sub(r"[^A-Za-z0-9_]+", "_", str(value or "").strip()).strip("_").lower()
        return lowered or "level_01"

    def _resolve_template_id(self, task: Task, template_id: Optional[str]) -> str:
        if template_id:
            return str(template_id).strip().lower()
        blueprint_manager = task.context.get("blueprint_manager")
        project_template = getattr(getattr(blueprint_manager, "blueprint", None), "project_template", {}) or {}
        return str(project_template.get("template_id") or "default").strip().lower()

    def _resolve_scene_res_path(self, level_name: str, scene_path: Optional[str]) -> str:
        raw = str(scene_path or "").strip().replace("\\", "/")
        if raw.startswith("res://"):
            return raw
        if raw:
            return f"res://{raw.lstrip('/')}"
        return f"res://scenes/levels/{level_name}.tscn"

    def _resolve_project_path(self, project_root: Path, res_path: str) -> Path:
        relative = str(res_path).replace("res://", "", 1).lstrip("/")
        return (project_root / relative).resolve()

    def _resolve_manifest_path(self, project_root: Path, level_name: str, manifest_path: Optional[str]) -> Path:
        raw = str(manifest_path or "").strip().replace("\\", "/")
        if raw.startswith("res://"):
            raw = raw.replace("res://", "", 1)
        if not raw:
            raw = f"data_tables/levels/{level_name}.json"
        return (project_root / raw.lstrip("/")).resolve()

    def _resolve_snapshot_path(self, project_root: Path, level_name: str, snapshot_path: Optional[str]) -> Path:
        raw = str(snapshot_path or "").strip().replace("\\", "/")
        if raw.startswith("res://"):
            raw = raw.replace("res://", "", 1)
            return (project_root / raw.lstrip("/")).resolve()
        if raw:
            return Path(raw).resolve() if Path(raw).is_absolute() else (Path.cwd() / raw.lstrip("/")).resolve()
        return (Path.cwd() / "logs" / "test_artifacts" / f"level_snapshot_{level_name}.json").resolve()

    def _resolve_runtime_or_project_path(self, project_root: Path, raw_path: Optional[str]) -> Optional[Path]:
        raw = str(raw_path or "").strip().replace("\\", "/")
        if not raw:
            return None
        if raw.startswith("res://"):
            return (project_root / raw.replace("res://", "", 1).lstrip("/")).resolve()
        path = Path(raw)
        return path.resolve() if path.is_absolute() else (Path.cwd() / raw.lstrip("/")).resolve()

    def _to_res_path(self, project_root: Path, full_path: Path) -> str:
        try:
            relative = full_path.resolve().relative_to(project_root.resolve())
            return f"res://{relative.as_posix()}"
        except ValueError:
            return str(full_path)

    def _build_level_manifest(
        self,
        *,
        level_name: str,
        level_type: str,
        root_type: str,
        scene_path: str,
        template_id: str,
        params: LevelWorkflowParams,
    ) -> Dict[str, Any]:
        defaults = LEVEL_TYPE_DEFAULTS[level_type]
        spawn_points = self._normalize_points(
            params.spawn_points or [{"id": "player_spawn", "node_path": "PlayerSpawn", "kind": "spawn", "position": [0, 0]}],
            default_kind="spawn",
        )
        interaction_points = self._normalize_points(params.interaction_points or defaults["interaction_points"], default_kind="interaction")
        checkpoints = self._normalize_points(params.checkpoints or defaults["checkpoints"], default_kind="checkpoint")
        navigation_zones = self._normalize_points(params.navigation_zones or defaults["navigation_zones"], default_kind="navigation")
        navigation_agents = self._normalize_navigation_agents(params.navigation_agents or defaults["navigation_agents"], root_type=root_type)
        tile_layers = self._normalize_tile_layers(params.tile_layers or defaults["tile_layers"], root_type=root_type)
        trigger_zones = self._normalize_trigger_zones(params.trigger_zones or defaults["trigger_zones"], root_type=root_type)
        collision_layers = self._normalize_collision_layers(params.collision_layers or defaults["collision_layers"])
        level_bounds = self._normalize_level_bounds(params.level_bounds or defaults["level_bounds"], root_type=root_type)
        critical_path = [self._slugify(item) for item in (params.critical_path or []) if str(item).strip()]
        if not critical_path:
            critical_path = [spawn_points[0]["id"], interaction_points[-1]["id"]]

        return {
            "schema_version": LEVEL_WORKFLOW_SCHEMA_VERSION,
            "level_id": level_name,
            "level_type": level_type,
            "template_id": template_id,
            "root_type": root_type,
            "scene_path": scene_path,
            "spawn_points": spawn_points,
            "interaction_points": interaction_points,
            "checkpoints": checkpoints,
            "navigation_zones": navigation_zones,
            "navigation_agents": navigation_agents,
            "tile_layers": tile_layers,
            "trigger_zones": trigger_zones,
            "collision_layers": collision_layers,
            "level_bounds": level_bounds,
            "critical_path": critical_path,
            "acceptance_checks": [
                "player_spawn_present",
                "level_exit_present",
                "navigation_zones_defined",
                "navigation_agents_defined",
                "tile_layers_defined",
                "trigger_zones_defined",
                "collision_layers_defined",
                "level_bounds_defined",
                "critical_path_seeded",
                "level_snapshot_ready",
            ],
            "notes": params.notes or "",
        }

    def _normalize_points(self, entries: List[Dict[str, Any]], *, default_kind: str) -> List[Dict[str, Any]]:
        normalized: List[Dict[str, Any]] = []
        for index, raw in enumerate(entries or []):
            item = dict(raw or {})
            point_id = self._slugify(item.get("id") or f"{default_kind}_{index + 1}")
            node_path = str(item.get("node_path") or self._node_name_from_id(point_id)).strip() or self._node_name_from_id(point_id)
            kind = str(item.get("kind") or default_kind).strip().lower() or default_kind
            position = item.get("position")
            normalized.append({
                "id": point_id,
                "node_path": node_path,
                "kind": kind,
                "position": position if isinstance(position, list) else None,
            })
        return normalized

    def _normalize_collision_layers(self, layers: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        normalized: List[Dict[str, Any]] = []
        for index, raw in enumerate(layers or []):
            item = dict(raw or {})
            normalized.append({
                "name": self._slugify(item.get("name") or f"layer_{index + 1}"),
                "layer": int(item.get("layer") or index + 1),
            })
        return normalized

    def _normalize_tile_layers(self, layers: List[Dict[str, Any]], *, root_type: str) -> List[Dict[str, Any]]:
        normalized: List[Dict[str, Any]] = []
        for index, raw in enumerate(layers or []):
            item = dict(raw or {})
            layer_id = self._slugify(item.get("id") or f"tile_layer_{index + 1}")
            node_path = str(item.get("node_path") or self._node_name_from_id(layer_id)).strip() or self._node_name_from_id(layer_id)
            cell_size = self._normalize_vector(item.get("cell_size"), root_type=root_type, dimensions=2)
            grid_size = self._normalize_vector(item.get("grid_size"), root_type=root_type, dimensions=2)
            normalized.append({
                "id": layer_id,
                "node_path": node_path,
                "kind": str(item.get("kind") or "ground").strip().lower() or "ground",
                "tileset_path": str(item.get("tileset_path") or "").strip(),
                "cell_size": cell_size,
                "grid_size": grid_size,
            })
        return normalized

    def _normalize_navigation_agents(self, agents: List[Dict[str, Any]], *, root_type: str) -> List[Dict[str, Any]]:
        normalized: List[Dict[str, Any]] = []
        for index, raw in enumerate(agents or []):
            item = dict(raw or {})
            agent_id = self._slugify(item.get("id") or f"nav_agent_{index + 1}")
            normalized.append({
                "id": agent_id,
                "node_path": str(item.get("node_path") or self._node_name_from_id(agent_id)).strip() or self._node_name_from_id(agent_id),
                "kind": str(item.get("kind") or "navigation").strip().lower() or "navigation",
                "position": self._normalize_vector(item.get("position"), root_type=root_type, dimensions=3 if root_type == "Node3D" else 2),
                "radius": float(item.get("radius") or 24.0),
            })
        return normalized

    def _normalize_trigger_zones(self, zones: List[Dict[str, Any]], *, root_type: str) -> List[Dict[str, Any]]:
        normalized: List[Dict[str, Any]] = []
        for index, raw in enumerate(zones or []):
            item = dict(raw or {})
            zone_id = self._slugify(item.get("id") or f"trigger_zone_{index + 1}")
            normalized.append({
                "id": zone_id,
                "node_path": str(item.get("node_path") or self._node_name_from_id(zone_id)).strip() or self._node_name_from_id(zone_id),
                "kind": str(item.get("kind") or "trigger").strip().lower() or "trigger",
                "position": self._normalize_vector(item.get("position"), root_type=root_type, dimensions=3 if root_type == "Node3D" else 2),
                "size": self._normalize_vector(item.get("size"), root_type=root_type, dimensions=3 if root_type == "Node3D" else 2),
            })
        return normalized

    def _normalize_level_bounds(self, bounds: Dict[str, Any], *, root_type: str) -> Dict[str, Any]:
        raw = dict(bounds or {})
        dimensions = 3 if root_type == "Node3D" else 2
        return {
            "min": self._normalize_vector(raw.get("min"), root_type=root_type, dimensions=dimensions, default=[0.0] * dimensions),
            "max": self._normalize_vector(raw.get("max"), root_type=root_type, dimensions=dimensions, default=[1024.0, 512.0, 256.0][:dimensions]),
        }

    def _normalize_vector(
        self,
        value: Any,
        *,
        root_type: str,
        dimensions: int,
        default: Optional[List[float]] = None,
    ) -> List[float]:
        fallback = list(default or ([0.0] * dimensions))
        if isinstance(value, list):
            source = value
        elif isinstance(value, dict):
            source = [value.get(key) for key in ("x", "y", "z")[:dimensions]]
        else:
            return fallback
        normalized: List[float] = []
        for index in range(dimensions):
            try:
                normalized.append(float(source[index]))
            except Exception:
                normalized.append(float(fallback[index]))
        return normalized

    def _node_name_from_id(self, value: str) -> str:
        parts = [chunk for chunk in str(value).strip().split("_") if chunk]
        return "".join(part.capitalize() for part in parts) or "Marker"

    def _build_scene_content(self, manifest: Dict[str, Any]) -> str:
        root_type = manifest.get("root_type") or "Node2D"
        marker_type = "Marker3D" if root_type == "Node3D" else "Marker2D"
        nav_region_type = "NavigationRegion3D" if root_type == "Node3D" else "NavigationRegion2D"
        nav_agent_type = "NavigationAgent3D" if root_type == "Node3D" else "NavigationAgent2D"
        trigger_type = "Area3D" if root_type == "Node3D" else "Area2D"
        trigger_shape_type = "CollisionShape3D" if root_type == "Node3D" else "CollisionShape2D"
        tile_layer_type = "GridMap" if root_type == "Node3D" else "TileMap"
        lines = [
            '[gd_scene format=3]',
            "",
            f'[node name="{self._node_name_from_id(str(manifest["level_id"]))}" type="{root_type}"]',
            "",
        ]
        for point in manifest.get("spawn_points", []):
            lines.extend(self._build_point_node(point, marker_type, root_type))
        for point in manifest.get("interaction_points", []):
            lines.extend(self._build_point_node(point, marker_type, root_type))
        for point in manifest.get("checkpoints", []):
            lines.extend(self._build_point_node(point, marker_type, root_type))
        for zone in manifest.get("navigation_zones", []):
            lines.extend(self._build_navigation_zone_node(zone, nav_region_type, root_type))
        for agent in manifest.get("navigation_agents", []):
            lines.extend(self._build_navigation_agent_node(agent, nav_agent_type, root_type))
        for tile_layer in manifest.get("tile_layers", []):
            lines.extend(self._build_tile_layer_node(tile_layer, tile_layer_type, root_type))
        for trigger_zone in manifest.get("trigger_zones", []):
            lines.extend(self._build_trigger_zone_node(trigger_zone, trigger_type, trigger_shape_type, root_type))
        for layer in manifest.get("collision_layers", []):
            lines.extend([
                f'[node name="CollisionProfile{self._node_name_from_id(str(layer["name"]))}" type="Node" parent="."]',
                "",
            ])
        lines.extend(self._build_level_bounds_node(manifest.get("level_bounds") or {}, root_type))
        return "\n".join(lines).rstrip() + "\n"

    def _build_point_node(self, point: Dict[str, Any], marker_type: str, root_type: str) -> List[str]:
        node_name = str(point.get("node_path") or self._node_name_from_id(point.get("id") or "marker")).split("/")[-1]
        lines = [f'[node name="{node_name}" type="{marker_type}" parent="."]']
        position = point.get("position")
        if isinstance(position, list) and position:
            if root_type == "Node3D":
                coords = [float(position[i]) if i < len(position) else 0.0 for i in range(3)]
                lines.append(f"position = Vector3({coords[0]}, {coords[1]}, {coords[2]})")
            else:
                coords = [float(position[i]) if i < len(position) else 0.0 for i in range(2)]
                lines.append(f"position = Vector2({coords[0]}, {coords[1]})")
        lines.append("")
        return lines

    def _build_navigation_zone_node(self, zone: Dict[str, Any], nav_region_type: str, root_type: str) -> List[str]:
        node_name = str(zone.get("node_path") or self._node_name_from_id(zone.get("id") or "navigation_zone")).split("/")[-1]
        lines = [f'[node name="{node_name}" type="{nav_region_type}" parent="."]']
        position = zone.get("position")
        if isinstance(position, list) and position:
            if root_type == "Node3D":
                coords = [float(position[i]) if i < len(position) else 0.0 for i in range(3)]
                lines.append(f"position = Vector3({coords[0]}, {coords[1]}, {coords[2]})")
            else:
                coords = [float(position[i]) if i < len(position) else 0.0 for i in range(2)]
                lines.append(f"position = Vector2({coords[0]}, {coords[1]})")
        lines.append("")
        return lines

    def _build_navigation_agent_node(self, agent: Dict[str, Any], nav_agent_type: str, root_type: str) -> List[str]:
        node_name = str(agent.get("node_path") or self._node_name_from_id(agent.get("id") or "navigation_agent")).split("/")[-1]
        lines = [f'[node name="{node_name}" type="{nav_agent_type}" parent="."]']
        position = agent.get("position")
        if isinstance(position, list) and position:
            if root_type == "Node3D":
                coords = [float(position[i]) if i < len(position) else 0.0 for i in range(3)]
                lines.append(f"position = Vector3({coords[0]}, {coords[1]}, {coords[2]})")
            else:
                coords = [float(position[i]) if i < len(position) else 0.0 for i in range(2)]
                lines.append(f"position = Vector2({coords[0]}, {coords[1]})")
        lines.append("")
        return lines

    def _build_tile_layer_node(self, tile_layer: Dict[str, Any], tile_layer_type: str, root_type: str) -> List[str]:
        node_name = str(tile_layer.get("node_path") or self._node_name_from_id(tile_layer.get("id") or "tile_layer")).split("/")[-1]
        lines = [f'[node name="{node_name}" type="{tile_layer_type}" parent="."]']
        lines.append("")
        return lines

    def _build_trigger_zone_node(self, zone: Dict[str, Any], trigger_type: str, trigger_shape_type: str, root_type: str) -> List[str]:
        node_name = str(zone.get("node_path") or self._node_name_from_id(zone.get("id") or "trigger_zone")).split("/")[-1]
        lines = [f'[node name="{node_name}" type="{trigger_type}" parent="."]']
        position = zone.get("position")
        if isinstance(position, list) and position:
            if root_type == "Node3D":
                coords = [float(position[i]) if i < len(position) else 0.0 for i in range(3)]
                lines.append(f"position = Vector3({coords[0]}, {coords[1]}, {coords[2]})")
            else:
                coords = [float(position[i]) if i < len(position) else 0.0 for i in range(2)]
                lines.append(f"position = Vector2({coords[0]}, {coords[1]})")
        lines.append("")
        lines.append(f'[node name="CollisionShape" type="{trigger_shape_type}" parent="{node_name}"]')
        lines.append("")
        return lines

    def _build_level_bounds_node(self, bounds: Dict[str, Any], root_type: str) -> List[str]:
        lines = ['[node name="LevelBounds" type="Node" parent="."]']
        mins = bounds.get("min") or []
        maxs = bounds.get("max") or []
        if root_type == "Node3D":
            min_values = [float(mins[i]) if i < len(mins) else 0.0 for i in range(3)]
            max_values = [float(maxs[i]) if i < len(maxs) else 0.0 for i in range(3)]
            lines.append('[node name="BoundsMin" type="Marker3D" parent="LevelBounds"]')
            lines.append(f"position = Vector3({min_values[0]}, {min_values[1]}, {min_values[2]})")
            lines.append("")
            lines.append('[node name="BoundsMax" type="Marker3D" parent="LevelBounds"]')
            lines.append(f"position = Vector3({max_values[0]}, {max_values[1]}, {max_values[2]})")
        else:
            min_values = [float(mins[i]) if i < len(mins) else 0.0 for i in range(2)]
            max_values = [float(maxs[i]) if i < len(maxs) else 0.0 for i in range(2)]
            lines.append('[node name="BoundsMin" type="Marker2D" parent="LevelBounds"]')
            lines.append(f"position = Vector2({min_values[0]}, {min_values[1]})")
            lines.append("")
            lines.append('[node name="BoundsMax" type="Marker2D" parent="LevelBounds"]')
            lines.append(f"position = Vector2({max_values[0]}, {max_values[1]})")
        lines.append("")
        return lines

    def _build_level_snapshot(
        self,
        *,
        level_name: str,
        scene_res_path: str,
        manifest_res_path: str,
        scene_full_path: Path,
        manifest_full_path: Path,
        fallback_manifest: Dict[str, Any],
    ) -> Dict[str, Any]:
        manifest_exists = manifest_full_path.exists()
        scene_exists = scene_full_path.exists()

        manifest_payload = fallback_manifest
        manifest_parse_error = ""
        if manifest_exists:
            try:
                manifest_payload = json.loads(manifest_full_path.read_text(encoding="utf-8"))
            except Exception as exc:
                manifest_parse_error = str(exc)

        scene_text = scene_full_path.read_text(encoding="utf-8") if scene_exists else ""
        scene_nodes = self._extract_scene_nodes(scene_text)
        node_type_counts: Dict[str, int] = {}
        for node in scene_nodes:
            node_type = str(node.get("type") or "").strip() or "Node"
            node_type_counts[node_type] = node_type_counts.get(node_type, 0) + 1

        manifest_summary = {
            "spawn_point_count": len(manifest_payload.get("spawn_points") or []),
            "interaction_point_count": len(manifest_payload.get("interaction_points") or []),
            "checkpoint_count": len(manifest_payload.get("checkpoints") or []),
            "navigation_zone_count": len(manifest_payload.get("navigation_zones") or []),
            "navigation_agent_count": len(manifest_payload.get("navigation_agents") or []),
            "tile_layer_count": len(manifest_payload.get("tile_layers") or []),
            "trigger_zone_count": len(manifest_payload.get("trigger_zones") or []),
            "collision_layer_count": len(manifest_payload.get("collision_layers") or []),
            "critical_path_count": len(manifest_payload.get("critical_path") or []),
        }

        return {
            "schema_version": LEVEL_WORKFLOW_SCHEMA_VERSION,
            "snapshot_type": "level_workflow_snapshot",
            "captured_at": datetime.now(timezone.utc).isoformat(),
            "level_id": level_name,
            "level_type": str(manifest_payload.get("level_type") or fallback_manifest.get("level_type") or "combat"),
            "template_id": str(manifest_payload.get("template_id") or fallback_manifest.get("template_id") or "default"),
            "root_type": str(manifest_payload.get("root_type") or fallback_manifest.get("root_type") or "Node2D"),
            "scene_path": scene_res_path,
            "manifest_path": manifest_res_path,
            "scene_exists": scene_exists,
            "manifest_exists": manifest_exists,
            "manifest_parse_error": manifest_parse_error,
            "node_count": len(scene_nodes),
            "scene_nodes": scene_nodes,
            "scene_node_type_counts": node_type_counts,
            "manifest_summary": manifest_summary,
            "acceptance_checks": list(manifest_payload.get("acceptance_checks") or []),
            "critical_path": list(manifest_payload.get("critical_path") or []),
            "level_bounds": dict(manifest_payload.get("level_bounds") or {}),
        }

    def _extract_scene_nodes(self, scene_text: str) -> List[Dict[str, Any]]:
        node_pattern = re.compile(r'^\[node name="([^"]+)" type="([^"]+)"(?: parent="([^"]+)")?\]$')
        nodes: List[Dict[str, Any]] = []
        for line in scene_text.splitlines():
            match = node_pattern.match(line.strip())
            if not match:
                continue
            node_name, node_type, parent_path = match.groups()
            normalized_parent = parent_path or ""
            if not normalized_parent:
                node_path = "."
            elif normalized_parent == ".":
                node_path = node_name
            else:
                node_path = f"{normalized_parent}/{node_name}"
            nodes.append({
                "name": node_name,
                "type": node_type,
                "parent_path": normalized_parent or ".",
                "path": node_path,
            })
        return nodes

    def _build_snapshot_report(self, snapshot_payload: Dict[str, Any]) -> str:
        lines = [
            "# Level Workflow Snapshot",
            "",
            f"- Level ID: `{snapshot_payload['level_id']}`",
            f"- Level Type: `{snapshot_payload['level_type']}`",
            f"- Scene Path: `{snapshot_payload['scene_path']}`",
            f"- Manifest Path: `{snapshot_payload['manifest_path']}`",
            f"- Captured At: `{snapshot_payload['captured_at']}`",
            f"- Scene Exists: `{snapshot_payload['scene_exists']}`",
            f"- Manifest Exists: `{snapshot_payload['manifest_exists']}`",
            f"- Node Count: `{snapshot_payload['node_count']}`",
            "",
            "## Manifest Summary",
        ]
        for key, value in snapshot_payload.get("manifest_summary", {}).items():
            lines.append(f"- `{key}`: {value}")
        lines.extend(["", "## Scene Node Types"])
        node_type_counts = dict(snapshot_payload.get("scene_node_type_counts") or {})
        if node_type_counts:
            for node_type, count in sorted(node_type_counts.items()):
                lines.append(f"- `{node_type}`: {count}")
        else:
            lines.append("- none")
        lines.extend(["", "## Sample Nodes"])
        scene_nodes = list(snapshot_payload.get("scene_nodes") or [])
        if scene_nodes:
            for node in scene_nodes[:10]:
                lines.append(f"- `{node['path']}` ({node['type']})")
        else:
            lines.append("- none")
        lines.append("")
        return "\n".join(lines)

    def _build_snapshot_diff(self, previous_snapshot: Dict[str, Any], current_snapshot: Dict[str, Any]) -> Dict[str, Any]:
        previous_nodes = {
            str(node.get("path") or node.get("name") or "."): dict(node)
            for node in list(previous_snapshot.get("scene_nodes") or [])
        }
        current_nodes = {
            str(node.get("path") or node.get("name") or "."): dict(node)
            for node in list(current_snapshot.get("scene_nodes") or [])
        }

        previous_paths = set(previous_nodes)
        current_paths = set(current_nodes)
        added_nodes = [current_nodes[path] for path in sorted(current_paths - previous_paths)]
        removed_nodes = [previous_nodes[path] for path in sorted(previous_paths - current_paths)]
        changed_nodes: List[Dict[str, Any]] = []
        for path in sorted(previous_paths & current_paths):
            before_node = previous_nodes[path]
            after_node = current_nodes[path]
            changes: List[str] = []
            if before_node.get("type") != after_node.get("type"):
                changes.append("type")
            if before_node.get("parent_path") != after_node.get("parent_path"):
                changes.append("parent_path")
            if changes:
                changed_nodes.append({
                    "path": path,
                    "before": before_node,
                    "after": after_node,
                    "changes": changes,
                })

        previous_summary = dict(previous_snapshot.get("manifest_summary") or {})
        current_summary = dict(current_snapshot.get("manifest_summary") or {})
        metric_changes: List[Dict[str, Any]] = []
        for metric in sorted(set(previous_summary) | set(current_summary)):
            before_value = int(previous_summary.get(metric) or 0)
            after_value = int(current_summary.get(metric) or 0)
            if before_value != after_value:
                metric_changes.append({
                    "metric": metric,
                    "before": before_value,
                    "after": after_value,
                    "delta": after_value - before_value,
                })

        has_changes = bool(added_nodes or removed_nodes or changed_nodes or metric_changes)
        return {
            "schema_version": LEVEL_WORKFLOW_SCHEMA_VERSION,
            "status": "changed" if has_changes else "no_changes",
            "added_nodes": added_nodes,
            "removed_nodes": removed_nodes,
            "changed_nodes": changed_nodes,
            "metric_changes": metric_changes,
        }

    def _build_snapshot_diff_report(
        self,
        level_name: str,
        diff_payload: Dict[str, Any],
        compare_snapshot_path: Path,
        snapshot_full_path: Path,
    ) -> str:
        lines = [
            "# Level Workflow Snapshot Diff",
            "",
            f"- Level ID: `{level_name}`",
            f"- Compare Snapshot: `{compare_snapshot_path}`",
            f"- Current Snapshot: `{snapshot_full_path}`",
            f"- Status: `{diff_payload['status']}`",
            f"- Added Nodes: `{len(diff_payload['added_nodes'])}`",
            f"- Removed Nodes: `{len(diff_payload['removed_nodes'])}`",
            f"- Changed Nodes: `{len(diff_payload['changed_nodes'])}`",
            f"- Metric Changes: `{len(diff_payload['metric_changes'])}`",
            "",
            "## Node Changes",
        ]
        if diff_payload["added_nodes"]:
            for node in diff_payload["added_nodes"]:
                lines.append(f"- added `{node['path']}` ({node['type']})")
        if diff_payload["removed_nodes"]:
            for node in diff_payload["removed_nodes"]:
                lines.append(f"- removed `{node['path']}` ({node['type']})")
        if diff_payload["changed_nodes"]:
            for item in diff_payload["changed_nodes"]:
                lines.append(f"- changed `{item['path']}`: {', '.join(item['changes'])}")
        if not diff_payload["added_nodes"] and not diff_payload["removed_nodes"] and not diff_payload["changed_nodes"]:
            lines.append("- none")
        lines.extend(["", "## Manifest Metric Changes"])
        if diff_payload["metric_changes"]:
            for item in diff_payload["metric_changes"]:
                lines.append(f"- `{item['metric']}`: {item['before']} -> {item['after']} (delta {item['delta']})")
        else:
            lines.append("- none")
        lines.append("")
        return "\n".join(lines)

    def _audit_level(self, scene_full_path: Path, manifest_full_path: Path, fallback_manifest: Dict[str, Any]) -> Dict[str, Any]:
        issues: List[str] = []
        checks: List[Dict[str, str]] = []

        manifest_payload = fallback_manifest
        if manifest_full_path.exists():
            try:
                manifest_payload = json.loads(manifest_full_path.read_text(encoding="utf-8"))
                checks.append({"name": "level_manifest_exists", "status": "passed"})
            except Exception:
                issues.append("关卡 manifest 无法解析")
                checks.append({"name": "level_manifest_exists", "status": "failed"})
        else:
            issues.append("缺少关卡 manifest")
            checks.append({"name": "level_manifest_exists", "status": "failed"})

        scene_text = ""
        if scene_full_path.exists():
            scene_text = scene_full_path.read_text(encoding="utf-8")
            checks.append({"name": "level_scene_exists", "status": "passed"})
        else:
            issues.append("缺少关卡场景文件")
            checks.append({"name": "level_scene_exists", "status": "failed"})

        spawn_points = list(manifest_payload.get("spawn_points") or [])
        interaction_points = list(manifest_payload.get("interaction_points") or [])
        checkpoints = list(manifest_payload.get("checkpoints") or [])
        navigation_zones = list(manifest_payload.get("navigation_zones") or [])
        navigation_agents = list(manifest_payload.get("navigation_agents") or [])
        tile_layers = list(manifest_payload.get("tile_layers") or [])
        trigger_zones = list(manifest_payload.get("trigger_zones") or [])
        collision_layers = list(manifest_payload.get("collision_layers") or [])
        critical_path = list(manifest_payload.get("critical_path") or [])
        level_bounds = dict(manifest_payload.get("level_bounds") or {})

        if spawn_points:
            checks.append({"name": "player_spawn_present", "status": "passed"})
        else:
            issues.append("关卡缺少玩家出生点")
            checks.append({"name": "player_spawn_present", "status": "failed"})

        if any(str(item.get("kind")).lower() in {"exit", "gate"} for item in interaction_points):
            checks.append({"name": "level_exit_present", "status": "passed"})
        else:
            issues.append("关卡缺少出口交互点")
            checks.append({"name": "level_exit_present", "status": "failed"})

        if navigation_zones:
            checks.append({"name": "navigation_zones_defined", "status": "passed"})
        else:
            issues.append("关卡缺少导航区域定义")
            checks.append({"name": "navigation_zones_defined", "status": "failed"})

        if navigation_agents:
            checks.append({"name": "navigation_agents_defined", "status": "passed"})
        else:
            issues.append("关卡缺少导航代理定义")
            checks.append({"name": "navigation_agents_defined", "status": "failed"})

        if tile_layers:
            checks.append({"name": "tile_layers_defined", "status": "passed"})
        else:
            issues.append("关卡缺少 TileMap/GridMap 层定义")
            checks.append({"name": "tile_layers_defined", "status": "failed"})

        if trigger_zones:
            checks.append({"name": "trigger_zones_defined", "status": "passed"})
        else:
            issues.append("关卡缺少 Trigger/Area 定义")
            checks.append({"name": "trigger_zones_defined", "status": "failed"})

        if collision_layers:
            checks.append({"name": "collision_layers_defined", "status": "passed"})
        else:
            issues.append("关卡缺少碰撞层约束")
            checks.append({"name": "collision_layers_defined", "status": "failed"})

        if level_bounds.get("min") and level_bounds.get("max"):
            checks.append({"name": "level_bounds_defined", "status": "passed"})
        else:
            issues.append("关卡缺少边界定义")
            checks.append({"name": "level_bounds_defined", "status": "failed"})

        if len(critical_path) >= 2:
            checks.append({"name": "critical_path_seeded", "status": "passed"})
        else:
            issues.append("关卡关键路径未初始化")
            checks.append({"name": "critical_path_seeded", "status": "failed"})

        if scene_full_path.exists() and manifest_full_path.exists():
            checks.append({"name": "level_snapshot_ready", "status": "passed"})
        else:
            issues.append("关卡快照前置条件不完整")
            checks.append({"name": "level_snapshot_ready", "status": "failed"})

        node_names = set(re.findall(r'\[node name="([^"]+)"', scene_text))
        if scene_text:
            for point in (
                spawn_points
                + interaction_points
                + checkpoints
                + navigation_zones
                + navigation_agents
                + tile_layers
                + trigger_zones
            ):
                expected = str(point.get("node_path") or "").split("/")[-1]
                if expected and expected not in node_names:
                    issues.append(f"场景缺少关卡标记节点: {expected}")
            for trigger_zone in trigger_zones:
                expected = str(trigger_zone.get("node_path") or "").split("/")[-1]
                if expected and "CollisionShape" not in node_names:
                    issues.append(f"场景缺少 Trigger 碰撞节点: {expected}/CollisionShape")
            for layer in collision_layers:
                expected = f"CollisionProfile{self._node_name_from_id(str(layer.get('name') or 'layer'))}"
                if expected not in node_names:
                    issues.append(f"场景缺少碰撞配置节点: {expected}")
            for bounds_node in ("LevelBounds", "BoundsMin", "BoundsMax"):
                if bounds_node not in node_names:
                    issues.append(f"场景缺少边界节点: {bounds_node}")

        return {"issues": issues, "checks": checks}

    def _build_diff_bundle(
        self,
        *,
        scene_res_path: str,
        manifest_res_path: str,
        current_scene: str,
        next_scene: str,
        current_manifest: str,
        next_manifest: str,
    ) -> str:
        chunks: List[str] = []
        chunks.append(f"## Scene Diff: {scene_res_path}")
        chunks.append(self._build_diff(current_scene, next_scene, scene_res_path))
        chunks.append("")
        chunks.append(f"## Manifest Diff: {manifest_res_path}")
        chunks.append(self._build_diff(current_manifest, next_manifest, manifest_res_path))
        return "\n".join(chunks).strip()

    def _build_diff(self, before: str, after: str, label: str) -> str:
        before_lines = before.splitlines()
        after_lines = after.splitlines()
        diff = list(difflib.unified_diff(before_lines, after_lines, fromfile=f"{label}:before", tofile=f"{label}:after", lineterm=""))
        return "\n".join(diff) if diff else "(no changes)"

    def _build_template_report(
        self,
        *,
        level_manifest: Dict[str, Any],
        action: str,
        diff_text: str,
        scene_res_path: str,
        manifest_res_path: str,
    ) -> str:
        return "\n".join([
            f"# Level Workflow {action.title()}",
            "",
            f"- Level ID: `{level_manifest['level_id']}`",
            f"- Level Type: `{level_manifest['level_type']}`",
            f"- Template ID: `{level_manifest['template_id']}`",
            f"- Scene Path: `{scene_res_path}`",
            f"- Manifest Path: `{manifest_res_path}`",
            f"- Spawn Points: `{len(level_manifest['spawn_points'])}`",
            f"- Interaction Points: `{len(level_manifest['interaction_points'])}`",
            f"- Navigation Zones: `{len(level_manifest['navigation_zones'])}`",
            f"- Navigation Agents: `{len(level_manifest['navigation_agents'])}`",
            f"- Tile Layers: `{len(level_manifest['tile_layers'])}`",
            f"- Trigger Zones: `{len(level_manifest['trigger_zones'])}`",
            f"- Collision Layers: `{len(level_manifest['collision_layers'])}`",
            f"- Level Bounds Ready: `{bool(level_manifest.get('level_bounds'))}`",
            "",
            "## Acceptance Checks",
            *[f"- `{item}`" for item in level_manifest.get("acceptance_checks", [])],
            "",
            "## Diff",
            "",
            diff_text,
            "",
        ]).strip() + "\n"

    def _build_audit_report(
        self,
        level_name: str,
        audit_payload: Dict[str, Any],
        scene_res_path: str,
        manifest_res_path: str,
    ) -> str:
        lines = [
            "# Level Workflow Audit",
            "",
            f"- Level ID: `{level_name}`",
            f"- Scene Path: `{scene_res_path}`",
            f"- Manifest Path: `{manifest_res_path}`",
            "",
            "## Checks",
        ]
        for check in audit_payload["checks"]:
            lines.append(f"- `{check['name']}`: {check['status']}")
        lines.extend(["", "## Issues"])
        if audit_payload["issues"]:
            lines.extend([f"- {issue}" for issue in audit_payload["issues"]])
        else:
            lines.append("- none")
        lines.append("")
        return "\n".join(lines)

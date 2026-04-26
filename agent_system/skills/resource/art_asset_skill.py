"""
Art asset intake pipeline skill.

Responsibilities:
- scaffold asset manifests by asset type
- validate asset metadata, naming, target directory, and budgets
- preview copy/manifest changes before applying
- apply managed asset copies plus manifest updates
"""

from __future__ import annotations

import difflib
import json
import shutil
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from ..base import BaseSkill, SkillMetadata
from ...models import Artifact, Task, ToolResult
from ...validations import ProjectLayoutValidator


ART_ASSET_MANIFEST_SCHEMA_VERSION = "1.1"

ART_ASSET_TYPE_LABELS: Dict[str, str] = {
    "texture": "贴图资源",
    "ui": "UI 资源",
    "spritesheet": "精灵表资源",
    "material": "材质资源",
    "vfx": "特效资源",
    "model": "GLTF 模型资源",
    "aseprite": "Aseprite 精灵表",
    "spine": "Spine 骨骼资源",
    "substance": "Substance 材质集",
    "outsource": "外包交付包",
}


ART_ASSET_SCHEMAS: Dict[str, Dict[str, Any]] = {
    "texture": {
        "default_directory": "assets/textures",
        "manifest_path": "assets/manifests/texture_assets.json",
        "allowed_extensions": [".png", ".jpg", ".jpeg", ".webp"],
        "requires_dimensions": True,
        "max_dimension": 2048,
        "max_memory_mb": 8.0,
        "sample_entries": [
            {
                "asset_id": "hero_diffuse",
                "source_path": "res://raw_assets/hero_diffuse.png",
                "target_path": "res://assets/textures/hero_diffuse.png",
                "width": 1024,
                "height": 1024,
                "tags": ["character", "diffuse"],
                "notes": "主角漫反射贴图",
            }
        ],
    },
    "ui": {
        "default_directory": "assets/ui",
        "manifest_path": "assets/manifests/ui_assets.json",
        "allowed_extensions": [".png", ".jpg", ".jpeg", ".webp"],
        "requires_dimensions": True,
        "max_dimension": 1024,
        "max_memory_mb": 4.0,
        "sample_entries": [
            {
                "asset_id": "main_menu_logo",
                "source_path": "res://raw_assets/main_menu_logo.png",
                "target_path": "res://assets/ui/main_menu_logo.png",
                "width": 512,
                "height": 256,
                "tags": ["ui", "logo"],
                "notes": "主菜单标题图",
            }
        ],
    },
    "spritesheet": {
        "default_directory": "assets/textures/spritesheets",
        "manifest_path": "assets/manifests/spritesheet_assets.json",
        "allowed_extensions": [".png", ".webp"],
        "requires_dimensions": True,
        "requires_frame_size": True,
        "max_dimension": 4096,
        "max_memory_mb": 16.0,
        "sample_entries": [
            {
                "asset_id": "slime_walk_sheet",
                "source_path": "res://raw_assets/slime_walk_sheet.png",
                "target_path": "res://assets/textures/spritesheets/slime_walk_sheet.png",
                "width": 1024,
                "height": 256,
                "frame_width": 128,
                "frame_height": 128,
                "tags": ["enemy", "animation"],
                "notes": "史莱姆移动帧图",
            }
        ],
    },
    "material": {
        "default_directory": "assets/materials",
        "manifest_path": "assets/manifests/material_assets.json",
        "allowed_extensions": [".tres", ".res"],
        "requires_dimensions": False,
        "max_memory_mb": 2.0,
        "sample_entries": [
            {
                "asset_id": "water_surface_material",
                "source_path": "res://raw_assets/water_surface_material.tres",
                "target_path": "res://assets/materials/water_surface_material.tres",
                "estimated_memory_mb": 1.5,
                "tags": ["environment", "material"],
                "notes": "水面材质实例",
            }
        ],
    },
    "vfx": {
        "default_directory": "assets/vfx",
        "manifest_path": "assets/manifests/vfx_assets.json",
        "allowed_extensions": [".png", ".webp", ".tres", ".tscn"],
        "requires_dimensions": False,
        "max_dimension": 2048,
        "max_memory_mb": 8.0,
        "sample_entries": [
            {
                "asset_id": "slash_hit_fx",
                "source_path": "res://raw_assets/slash_hit_fx.tscn",
                "target_path": "res://assets/vfx/slash_hit_fx.tscn",
                "estimated_memory_mb": 2.0,
                "tags": ["combat", "hit"],
                "notes": "斩击命中特效",
            }
        ],
    },
    "model": {
        "default_directory": "assets/models",
        "manifest_path": "assets/manifests/model_assets.json",
        "allowed_extensions": [".glb", ".gltf"],
        "allowed_source_extensions": [".blend", ".glb", ".gltf"],
        "default_target_extension": ".glb",
        "default_source_tool": "blender",
        "requires_dimensions": False,
        "max_memory_mb": 48.0,
        "sample_entries": [
            {
                "asset_id": "hero_knight_model",
                "source_path": "res://raw_assets/models/hero_knight.blend",
                "target_path": "res://assets/models/hero_knight.glb",
                "source_tool": "blender",
                "lod_count": 3,
                "source_dependency_paths": [
                    "res://raw_assets/models/hero_knight_albedo.png",
                    "res://raw_assets/models/hero_knight_normal.png",
                ],
                "target_dependency_paths": [
                    "res://assets/models/hero_knight_albedo.png",
                    "res://assets/models/hero_knight_normal.png",
                ],
                "estimated_memory_mb": 18.0,
                "tags": ["character", "3d", "rigged"],
                "notes": "Blender 导出的主角 GLTF 模型",
            }
        ],
    },
    "aseprite": {
        "default_directory": "assets/textures/spritesheets",
        "manifest_path": "assets/manifests/aseprite_assets.json",
        "allowed_extensions": [".png", ".webp"],
        "allowed_source_extensions": [".ase", ".aseprite", ".png", ".webp"],
        "default_target_extension": ".png",
        "default_source_tool": "aseprite",
        "requires_dimensions": True,
        "requires_frame_size": True,
        "max_dimension": 4096,
        "max_memory_mb": 24.0,
        "sample_entries": [
            {
                "asset_id": "slime_walk_aseprite",
                "source_path": "res://raw_assets/aseprite/slime_walk.aseprite",
                "target_path": "res://assets/textures/spritesheets/slime_walk_aseprite.png",
                "source_tool": "aseprite",
                "width": 1024,
                "height": 256,
                "frame_width": 128,
                "frame_height": 128,
                "source_dependency_paths": ["res://raw_assets/aseprite/slime_walk.json"],
                "target_dependency_paths": ["res://assets/textures/spritesheets/slime_walk_aseprite.json"],
                "estimated_memory_mb": 1.0,
                "tags": ["enemy", "2d", "animation"],
                "notes": "Aseprite 导出的史莱姆帧图与 atlas",
            }
        ],
    },
    "spine": {
        "default_directory": "assets/characters/spine",
        "manifest_path": "assets/manifests/spine_assets.json",
        "allowed_extensions": [".json"],
        "allowed_source_extensions": [".json"],
        "default_target_extension": ".json",
        "default_source_tool": "spine",
        "requires_dimensions": False,
        "max_memory_mb": 16.0,
        "sample_entries": [
            {
                "asset_id": "hero_spine_rig",
                "source_path": "res://raw_assets/spine/hero_spine.json",
                "target_path": "res://assets/characters/spine/hero_spine_rig.json",
                "source_tool": "spine",
                "source_dependency_paths": [
                    "res://raw_assets/spine/hero_spine.atlas",
                    "res://raw_assets/spine/hero_spine.png",
                ],
                "target_dependency_paths": [
                    "res://assets/characters/spine/hero_spine_rig.atlas",
                    "res://assets/characters/spine/hero_spine_rig.png",
                ],
                "estimated_memory_mb": 6.0,
                "tags": ["character", "2d", "skeleton"],
                "notes": "Spine 导出的角色骨骼包",
            }
        ],
    },
    "substance": {
        "default_directory": "assets/materials/substance",
        "manifest_path": "assets/manifests/substance_assets.json",
        "allowed_extensions": [".tres"],
        "allowed_source_extensions": [".sbsar", ".tres"],
        "default_target_extension": ".tres",
        "default_source_tool": "substance",
        "requires_dimensions": False,
        "max_memory_mb": 32.0,
        "sample_entries": [
            {
                "asset_id": "crate_pbr_surface",
                "source_path": "res://raw_assets/substance/crate_pbr.sbsar",
                "target_path": "res://assets/materials/substance/crate_pbr_surface.tres",
                "source_tool": "substance",
                "texture_set": "crate_surface",
                "source_dependency_paths": [
                    "res://raw_assets/substance/crate_pbr_albedo.png",
                    "res://raw_assets/substance/crate_pbr_normal.png",
                    "res://raw_assets/substance/crate_pbr_orm.png",
                ],
                "target_dependency_paths": [
                    "res://assets/materials/substance/crate_pbr_surface_albedo.png",
                    "res://assets/materials/substance/crate_pbr_surface_normal.png",
                    "res://assets/materials/substance/crate_pbr_surface_orm.png",
                ],
                "estimated_memory_mb": 12.0,
                "tags": ["environment", "pbr"],
                "notes": "Substance 输出的 PBR 材质集",
            }
        ],
    },
    "outsource": {
        "default_directory": "assets/packages/outsource",
        "manifest_path": "assets/manifests/outsource_assets.json",
        "allowed_extensions": [".zip"],
        "allowed_source_extensions": [".zip"],
        "default_target_extension": ".zip",
        "default_source_tool": "outsource_delivery",
        "requires_dimensions": False,
        "max_memory_mb": 512.0,
        "sample_entries": [
            {
                "asset_id": "npc_vendor_delivery",
                "source_path": "res://raw_assets/outsource/npc_vendor_delivery.zip",
                "target_path": "res://assets/packages/outsource/npc_vendor_delivery.zip",
                "source_tool": "outsource_delivery",
                "package_version": "v2026_04",
                "license_name": "work_for_hire",
                "estimated_memory_mb": 84.0,
                "tags": ["delivery", "vendor", "character"],
                "notes": "外包交付包，包含源文件、导出文件和授权说明",
            }
        ],
    },
}


class ArtAssetParams(BaseModel):
    action: str = Field(default="validate", description="template | validate | preview | apply")
    asset_type: str = Field(default="texture", description="texture | ui | spritesheet | material | vfx | model | aseprite | spine | substance | outsource")
    asset_id: Optional[str] = Field(default=None, description="资产 ID，要求 snake_case")
    source_path: Optional[str] = Field(default=None, description="原始资产路径")
    target_path: Optional[str] = Field(default=None, description="目标资产路径")
    manifest_path: Optional[str] = Field(default=None, description="资产 manifest 路径")
    source_tool: Optional[str] = Field(default=None, description="来源工具，如 blender / aseprite / spine / substance / outsource_delivery")
    width: Optional[int] = Field(default=None, description="宽度")
    height: Optional[int] = Field(default=None, description="高度")
    frame_width: Optional[int] = Field(default=None, description="精灵表单帧宽度")
    frame_height: Optional[int] = Field(default=None, description="精灵表单帧高度")
    lod_count: Optional[int] = Field(default=None, description="LOD 数量")
    texture_set: Optional[str] = Field(default=None, description="纹理集标识")
    package_version: Optional[str] = Field(default=None, description="外包交付包版本")
    license_name: Optional[str] = Field(default=None, description="授权或许可标识")
    source_dependency_paths: List[str] = Field(default_factory=list, description="源侧依赖文件，如 atlas / textures / maps")
    target_dependency_paths: List[str] = Field(default_factory=list, description="目标侧依赖文件")
    estimated_memory_mb: Optional[float] = Field(default=None, description="预估内存占用 MB")
    tags: List[str] = Field(default_factory=list, description="标签")
    notes: str = Field(default="", description="备注")
    entries: List[Dict[str, Any]] = Field(default_factory=list, description="结构化资产条目")


class ArtAssetPipelineSkill(BaseSkill):
    metadata = SkillMetadata(
        name="manage_art_asset_pipeline",
        description="管理美术资产导入链路，支持模板、校验、预览和落盘",
        category="resource",
        tags=["art", "asset", "pipeline", "texture", "ui", "vfx"],
    )

    input_model = ArtAssetParams

    def get_snapshot(
        self,
        *,
        asset_type: str,
        manifest_path: Optional[str] = None,
        asset_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        normalized_type = self._normalize_asset_type(asset_type)
        schema = ART_ASSET_SCHEMAS[normalized_type]
        project_root = Path(getattr(self.godot_cli, "project_path", ".") or ".").resolve()
        resolved_manifest = self._resolve_manifest_path(project_root, normalized_type, manifest_path)
        entries = self._load_existing_manifest(resolved_manifest)
        if asset_id:
            wanted = self._snake_case(asset_id)
            entries = [entry for entry in entries if str(entry.get("asset_id") or "") == wanted]
        return self._build_snapshot(
            asset_type=normalized_type,
            schema=schema,
            manifest_path=resolved_manifest,
            entries=entries,
        )

    def execute(self, task: Task, params: Dict[str, Any]) -> ToolResult:
        p = ArtAssetParams(**params)
        action = self._normalize_action(p.action)
        asset_type = self._normalize_asset_type(p.asset_type)
        schema = ART_ASSET_SCHEMAS[asset_type]
        project_root = Path(getattr(self.godot_cli, "project_path", ".") or ".").resolve()
        layout_validator = ProjectLayoutValidator(project_root=project_root, runtime_root=Path.cwd())
        manifest_path = self._resolve_manifest_path(project_root, asset_type, p.manifest_path)

        manifest_layout = layout_validator.validate_managed_path(manifest_path, "asset_manifest")
        if not manifest_layout["passed"]:
            return self.build_result(
                success=False,
                message=f"{ART_ASSET_TYPE_LABELS[asset_type]} manifest 路径不符合文件树规范",
                params=self.dump_model(p),
                error="; ".join(issue["message"] for issue in manifest_layout["issues"]),
                validation={"passed": False, "issues": [issue["code"] for issue in manifest_layout["issues"]]},
            )

        entries = self._resolve_entries(p, schema, project_root)
        normalized_entries, issues, copy_plan = self._normalize_and_validate_entries(
            entries=entries,
            asset_type=asset_type,
            schema=schema,
            project_root=project_root,
            layout_validator=layout_validator,
            check_source_exists=action != "template",
        )

        current_manifest = self._load_existing_manifest(manifest_path)
        merged_manifest = self._build_manifest(asset_type, schema, current_manifest, normalized_entries)
        manifest_content = json.dumps(merged_manifest, ensure_ascii=False, indent=2)
        current_content = manifest_path.read_text(encoding="utf-8") if manifest_path.exists() else ""
        diff_text = self._build_diff(current_content, manifest_content, manifest_path)

        report_path = Path("logs/reports") / f"art_asset_{asset_type}_{action}_{int(time.time())}.md"
        report_layout = layout_validator.validate_managed_path(report_path, "runtime_report")
        if not report_layout["passed"]:
            return self.build_result(
                success=False,
                message=f"{ART_ASSET_TYPE_LABELS[asset_type]} 报告路径不符合文件树规范",
                params=self.dump_model(p),
                error="; ".join(issue["message"] for issue in report_layout["issues"]),
                validation={"passed": False, "issues": [issue["code"] for issue in report_layout["issues"]]},
            )

        report_content = self._build_report(
            asset_type=asset_type,
            action=action,
            manifest_path=manifest_path,
            schema=schema,
            entries=normalized_entries,
            issues=issues,
            copy_plan=copy_plan,
            diff_text=diff_text,
        )
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(report_content, encoding="utf-8")

        snapshot = self._build_snapshot(
            asset_type=asset_type,
            schema=schema,
            manifest_path=manifest_path,
            entries=normalized_entries,
        )

        manifest_artifact = Artifact(
            name=manifest_path.name,
            path=str(manifest_path),
            type="resource",
            content=manifest_content if len(manifest_content) < 30000 else None,
            metadata={"asset_type": asset_type, "action": action, "manifest": True},
        )
        report_artifact = Artifact(
            name=report_path.name,
            path=str(report_path),
            type="report",
            content=report_content,
            metadata={"asset_type": asset_type, "action": action},
        )
        artifacts = [manifest_artifact, report_artifact]

        task.context.update({
            "art_asset_type": asset_type,
            "art_asset_action": action,
            "art_asset_id": normalized_entries[0].get("asset_id") if normalized_entries else "",
            "art_asset_source_path": normalized_entries[0].get("source_path") if normalized_entries else "",
            "art_asset_target_path": normalized_entries[0].get("target_path") if normalized_entries else "",
            "art_asset_source_tool": normalized_entries[0].get("source_tool") if normalized_entries else "",
            "art_asset_width": normalized_entries[0].get("width") if normalized_entries else None,
            "art_asset_height": normalized_entries[0].get("height") if normalized_entries else None,
            "art_asset_frame_width": normalized_entries[0].get("frame_width") if normalized_entries else None,
            "art_asset_frame_height": normalized_entries[0].get("frame_height") if normalized_entries else None,
            "art_asset_lod_count": normalized_entries[0].get("lod_count") if normalized_entries else None,
            "art_asset_texture_set": normalized_entries[0].get("texture_set") if normalized_entries else "",
            "art_asset_package_version": normalized_entries[0].get("package_version") if normalized_entries else "",
            "art_asset_license_name": normalized_entries[0].get("license_name") if normalized_entries else "",
            "art_asset_source_dependency_paths": list(params.get("source_dependency_paths") or []),
            "art_asset_target_dependency_paths": list(params.get("target_dependency_paths") or []),
            "art_asset_estimated_memory_mb": normalized_entries[0].get("estimated_memory_mb") if normalized_entries else None,
            "art_asset_tags": list(normalized_entries[0].get("tags") or []) if normalized_entries else [],
            "art_asset_notes": normalized_entries[0].get("notes") if normalized_entries else "",
            "art_asset_manifest_path": str(manifest_path),
            "art_asset_entry_count": len(normalized_entries),
            "art_asset_issue_count": len(issues),
            "art_asset_copy_count": len(copy_plan),
            "art_asset_layout_schema_version": manifest_layout["schema_version"],
            "art_asset_manifest_schema_version": ART_ASSET_MANIFEST_SCHEMA_VERSION,
            "art_asset_profile": snapshot,
        })

        if issues and action in {"validate", "preview", "apply"}:
            return self.build_result(
                success=False,
                message=f"{ART_ASSET_TYPE_LABELS[asset_type]} 校验失败",
                params=self.dump_model(p),
                error="; ".join(issues),
                artifacts=artifacts,
                data={"art_asset_profile": snapshot},
                validation={
                    "passed": False,
                    "issues": issues,
                    "checks": [
                        {"name": "asset_manifest_validation", "status": "failed"},
                    ],
                },
            )

        if action == "validate":
            return self.build_result(
                success=True,
                message=f"{ART_ASSET_TYPE_LABELS[asset_type]} 校验通过",
                params=self.dump_model(p),
                artifacts=artifacts,
                data={"art_asset_profile": snapshot},
                validation={
                    "passed": True,
                    "checks": [
                        {"name": "asset_manifest_validation", "status": "passed"},
                    ],
                },
                rollback={"available": False, "strategy": "validate_only"},
            )

        if action == "preview":
            return self.build_result(
                success=True,
                message=f"{ART_ASSET_TYPE_LABELS[asset_type]} 预览完成",
                params=self.dump_model(p),
                artifacts=artifacts,
                data={"art_asset_profile": snapshot},
                validation={
                    "passed": True,
                    "checks": [
                        {"name": "asset_manifest_validation", "status": "passed"},
                        {"name": "copy_plan_generated", "status": "passed"},
                    ],
                },
                rollback={"available": False, "strategy": "preview_only"},
            )

        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        manifest_backup = self.backup_existing_file(task, str(manifest_path))
        manifest_path.write_text(manifest_content, encoding="utf-8")

        copied_targets: List[str] = []
        if action == "apply":
            for item in copy_plan:
                source_path = Path(item["source_path"])
                target_path = Path(item["target_path"])
                target_path.parent.mkdir(parents=True, exist_ok=True)
                self.backup_existing_file(task, str(target_path))
                if source_path.resolve() != target_path.resolve():
                    shutil.copy2(source_path, target_path)
                copied_targets.append(str(target_path))
                artifacts.append(Artifact(
                    name=target_path.name,
                    path=str(target_path),
                    type="resource",
                    content=None,
                    metadata={"asset_type": asset_type, "action": action, "asset_id": item["asset_id"]},
                ))
            task.context["art_asset_copied"] = bool(copied_targets)

        rollback_paths = [backup.backup_path for backup in task.backups]
        if manifest_backup and manifest_backup not in rollback_paths:
            rollback_paths.append(manifest_backup)
        return self.build_result(
            success=True,
            message=(
                f"{ART_ASSET_TYPE_LABELS[asset_type]} 模板已生成"
                if action == "template"
                else f"{ART_ASSET_TYPE_LABELS[asset_type]} 已导入并登记"
            ),
            params=self.dump_model(p),
            artifacts=artifacts,
            data={"art_asset_profile": snapshot},
            validation={
                "passed": True,
                "checks": [
                    {"name": "asset_manifest_validation", "status": "passed"},
                    {"name": "asset_manifest_written", "status": "passed"},
                    {"name": "asset_copy_execution", "status": "passed" if action == "apply" else "skipped"},
                ],
            },
            rollback={
                "available": True,
                "strategy": "restore_art_asset_targets_and_manifest",
                "backup_paths": rollback_paths,
            },
            metadata={
                "manifest_path": str(manifest_path),
                "copied_target_count": len(copied_targets),
            },
        )

    def _normalize_action(self, value: str) -> str:
        normalized = str(value or "validate").strip().lower()
        return normalized if normalized in {"template", "validate", "preview", "apply"} else "validate"

    def _normalize_asset_type(self, value: str) -> str:
        normalized = str(value or "texture").strip().lower()
        return normalized if normalized in ART_ASSET_SCHEMAS else "texture"

    def _resolve_manifest_path(self, project_root: Path, asset_type: str, raw_path: Optional[str]) -> Path:
        relative = str(raw_path or ART_ASSET_SCHEMAS[asset_type]["manifest_path"]).strip()
        if relative.startswith("res://"):
            relative = relative.replace("res://", "", 1)
        return (project_root / relative).resolve()

    def _resolve_entries(self, params: ArtAssetParams, schema: Dict[str, Any], project_root: Path) -> List[Dict[str, Any]]:
        if params.entries:
            return [dict(entry) for entry in params.entries]

        if self._normalize_action(params.action) == "template":
            return [dict(entry) for entry in schema.get("sample_entries") or []]

        if not params.source_path and not params.target_path:
            return []

        return [{
            "asset_id": params.asset_id,
            "source_path": params.source_path,
            "target_path": params.target_path,
            "source_tool": params.source_tool,
            "width": params.width,
            "height": params.height,
            "frame_width": params.frame_width,
            "frame_height": params.frame_height,
            "lod_count": params.lod_count,
            "texture_set": params.texture_set,
            "package_version": params.package_version,
            "license_name": params.license_name,
            "source_dependency_paths": list(params.source_dependency_paths or []),
            "target_dependency_paths": list(params.target_dependency_paths or []),
            "estimated_memory_mb": params.estimated_memory_mb,
            "tags": list(params.tags or []),
            "notes": params.notes,
        }]

    def _normalize_and_validate_entries(
        self,
        *,
        entries: List[Dict[str, Any]],
        asset_type: str,
        schema: Dict[str, Any],
        project_root: Path,
        layout_validator: ProjectLayoutValidator,
        check_source_exists: bool,
    ) -> tuple[List[Dict[str, Any]], List[str], List[Dict[str, str]]]:
        issues: List[str] = []
        normalized_entries: List[Dict[str, Any]] = []
        copy_plan: List[Dict[str, str]] = []
        seen_ids = set()

        if not entries:
            return [], ["资产条目不能为空"], []

        for index, raw_entry in enumerate(entries, start=1):
            source_path = self._resolve_input_path(project_root, raw_entry.get("source_path"))
            asset_id = self._snake_case(raw_entry.get("asset_id") or (source_path.stem if source_path else ""))
            target_path = self._resolve_target_path(
                project_root=project_root,
                schema=schema,
                asset_id=asset_id,
                source_path=source_path,
                raw_target=raw_entry.get("target_path"),
            )
            target_res_path = self._to_res_path(project_root, target_path)
            source_display = self._to_display_path(project_root, source_path) if source_path else ""
            width = self._normalize_int(raw_entry.get("width"))
            height = self._normalize_int(raw_entry.get("height"))
            frame_width = self._normalize_int(raw_entry.get("frame_width"))
            frame_height = self._normalize_int(raw_entry.get("frame_height"))
            lod_count = self._normalize_int(raw_entry.get("lod_count"))
            estimated_memory_mb = self._normalize_float(raw_entry.get("estimated_memory_mb"))
            source_tool = str(raw_entry.get("source_tool") or "").strip().lower()
            texture_set = str(raw_entry.get("texture_set") or "").strip()
            package_version = str(raw_entry.get("package_version") or "").strip()
            license_name = str(raw_entry.get("license_name") or "").strip()
            source_dependency_values = self._normalize_path_list(raw_entry.get("source_dependency_paths"))
            target_dependency_values = self._normalize_path_list(raw_entry.get("target_dependency_paths"))
            if estimated_memory_mb is None and width and height:
                estimated_memory_mb = round((width * height * 4) / (1024 * 1024), 2)

            tags = self._clean_tags(raw_entry.get("tags"))
            notes = str(raw_entry.get("notes") or "").strip()

            if not asset_id:
                issues.append(f"第 {index} 条资产缺少 asset_id")
            elif asset_id in seen_ids:
                issues.append(f"asset_id 重复: {asset_id}")
            seen_ids.add(asset_id)

            if source_path is None and check_source_exists:
                issues.append(f"{asset_id or f'entry_{index}'} 缺少 source_path")
            elif source_path is not None and check_source_exists and not source_path.exists():
                issues.append(f"{asset_id or f'entry_{index}'} source_path 不存在: {source_display}")
            allowed_source_extensions = set(schema.get("allowed_source_extensions") or [])
            if source_path is not None and allowed_source_extensions and source_path.suffix.lower() not in allowed_source_extensions:
                issues.append(
                    f"{asset_id or f'entry_{index}'} source_path 扩展名 {source_path.suffix.lower()} 不在允许列表 {', '.join(sorted(allowed_source_extensions))}"
                )

            layout_result = layout_validator.validate_managed_path(target_path, "art_asset")
            if not layout_result["passed"]:
                for issue in layout_result["issues"]:
                    issues.append(f"{asset_id or f'entry_{index}'} target_path 非法: {issue['message']}")

            expected_prefix = f"{schema['default_directory'].rstrip('/')}/"
            if not target_res_path.startswith(f"res://{expected_prefix}"):
                issues.append(f"{asset_id or f'entry_{index}'} 目标目录必须位于 res://{schema['default_directory']}/")

            if target_path.suffix.lower() not in set(schema["allowed_extensions"]):
                issues.append(f"{asset_id or f'entry_{index}'} 扩展名 {target_path.suffix.lower()} 不在允许列表 {', '.join(schema['allowed_extensions'])}")

            if schema.get("requires_dimensions"):
                if not width or not height:
                    issues.append(f"{asset_id or f'entry_{index}'} 需要提供 width / height")
                if width is not None and width <= 0:
                    issues.append(f"{asset_id or f'entry_{index}'} width 必须大于 0")
                if height is not None and height <= 0:
                    issues.append(f"{asset_id or f'entry_{index}'} height 必须大于 0")
            max_dimension = schema.get("max_dimension")
            if max_dimension and width and width > max_dimension:
                issues.append(f"{asset_id or f'entry_{index}'} width 超出预算上限 {max_dimension}")
            if max_dimension and height and height > max_dimension:
                issues.append(f"{asset_id or f'entry_{index}'} height 超出预算上限 {max_dimension}")

            if estimated_memory_mb is not None and estimated_memory_mb > float(schema.get("max_memory_mb", 0)):
                issues.append(
                    f"{asset_id or f'entry_{index}'} estimated_memory_mb={estimated_memory_mb:.2f} 超出预算 {float(schema['max_memory_mb']):.2f}"
                )

            if schema.get("requires_frame_size"):
                if not frame_width or not frame_height:
                    issues.append(f"{asset_id or f'entry_{index}'} 需要提供 frame_width / frame_height")
                elif width and height:
                    if width % frame_width != 0 or height % frame_height != 0:
                        issues.append(f"{asset_id or f'entry_{index}'} 精灵表尺寸无法被 frame_width / frame_height 整除")

            dependency_pairs = self._build_dependency_pairs(
                asset_id=asset_id or f"entry_{index}",
                project_root=project_root,
                source_dependency_values=source_dependency_values,
                target_dependency_values=target_dependency_values,
                target_path=target_path,
                layout_validator=layout_validator,
                issues=issues,
                check_source_exists=check_source_exists,
            )

            profile_source_tool = source_tool or str(schema.get("default_source_tool") or "").strip().lower()
            self._validate_profile_rules(
                asset_type=asset_type,
                asset_id=asset_id or f"entry_{index}",
                source_tool=profile_source_tool,
                source_path=source_path,
                target_path=target_path,
                width=width,
                height=height,
                frame_width=frame_width,
                frame_height=frame_height,
                lod_count=lod_count,
                texture_set=texture_set,
                package_version=package_version,
                license_name=license_name,
                dependency_pairs=dependency_pairs,
                issues=issues,
            )

            normalized_entry = {
                "asset_id": asset_id,
                "source_path": source_display,
                "target_path": target_res_path,
                "source_tool": profile_source_tool,
                "width": width,
                "height": height,
                "frame_width": frame_width,
                "frame_height": frame_height,
                "lod_count": lod_count,
                "texture_set": texture_set,
                "package_version": package_version,
                "license_name": license_name,
                "dependency_targets": [item["target_res_path"] for item in dependency_pairs],
                "estimated_memory_mb": estimated_memory_mb,
                "tags": tags,
                "notes": notes,
            }
            normalized_entries.append(normalized_entry)

            if source_path is not None and check_source_exists and source_path.exists():
                copy_plan.append({
                    "asset_id": asset_id,
                    "source_path": str(source_path),
                    "target_path": str(target_path),
                    "target_res_path": target_res_path,
                })
            for item in dependency_pairs:
                if item["copy_ready"]:
                    copy_plan.append({
                        "asset_id": asset_id,
                        "source_path": item["source_path"],
                        "target_path": item["target_path"],
                        "target_res_path": item["target_res_path"],
                    })

        return normalized_entries, issues, copy_plan

    def _build_dependency_pairs(
        self,
        *,
        asset_id: str,
        project_root: Path,
        source_dependency_values: List[str],
        target_dependency_values: List[str],
        target_path: Path,
        layout_validator: ProjectLayoutValidator,
        issues: List[str],
        check_source_exists: bool,
    ) -> List[Dict[str, Any]]:
        if target_dependency_values and len(target_dependency_values) != len(source_dependency_values):
            issues.append(f"{asset_id} source_dependency_paths 与 target_dependency_paths 数量不一致")

        dependency_pairs: List[Dict[str, Any]] = []
        for index, raw_source in enumerate(source_dependency_values):
            source_path = self._resolve_input_path(project_root, raw_source)
            if target_dependency_values and index < len(target_dependency_values):
                target_candidate = self._resolve_input_path(project_root, target_dependency_values[index])
            elif source_path is not None:
                target_candidate = (target_path.parent / source_path.name).resolve()
            else:
                target_candidate = None

            if source_path is None:
                issues.append(f"{asset_id} 第 {index + 1} 个 source_dependency_path 非法")
                continue
            if target_candidate is None:
                issues.append(f"{asset_id} 第 {index + 1} 个 target_dependency_path 非法")
                continue
            if check_source_exists and not source_path.exists():
                issues.append(f"{asset_id} dependency source 不存在: {self._to_display_path(project_root, source_path)}")

            layout_result = layout_validator.validate_managed_path(target_candidate, "art_asset")
            if not layout_result["passed"]:
                for issue in layout_result["issues"]:
                    issues.append(f"{asset_id} dependency target 非法: {issue['message']}")

            dependency_pairs.append({
                "source_path": str(source_path),
                "target_path": str(target_candidate),
                "target_res_path": self._to_res_path(project_root, target_candidate),
                "source_suffix": source_path.suffix.lower(),
                "target_suffix": target_candidate.suffix.lower(),
                "copy_ready": (not check_source_exists) or source_path.exists(),
            })
        return dependency_pairs

    def _validate_profile_rules(
        self,
        *,
        asset_type: str,
        asset_id: str,
        source_tool: str,
        source_path: Optional[Path],
        target_path: Path,
        width: Optional[int],
        height: Optional[int],
        frame_width: Optional[int],
        frame_height: Optional[int],
        lod_count: Optional[int],
        texture_set: str,
        package_version: str,
        license_name: str,
        dependency_pairs: List[Dict[str, Any]],
        issues: List[str],
    ) -> None:
        dependency_target_suffixes = {item["target_suffix"] for item in dependency_pairs}
        dependency_target_names = {Path(item["target_path"]).stem.lower() for item in dependency_pairs}

        if asset_type == "model":
            if source_tool and source_tool not in {"blender", "gltf"}:
                issues.append(f"{asset_id} model profile 仅支持 blender / gltf 作为 source_tool")
            if lod_count is not None and lod_count < 1:
                issues.append(f"{asset_id} lod_count 必须大于等于 1")
            if source_path is not None and source_path.suffix.lower() == ".blend" and target_path.suffix.lower() not in {".glb", ".gltf"}:
                issues.append(f"{asset_id} Blender 源文件必须导出到 .glb 或 .gltf")
            return

        if asset_type == "aseprite":
            if source_tool and source_tool != "aseprite":
                issues.append(f"{asset_id} aseprite profile 的 source_tool 必须是 aseprite")
            if not width or not height or not frame_width or not frame_height:
                issues.append(f"{asset_id} aseprite profile 需要完整的 width / height / frame_width / frame_height")
            if ".json" not in dependency_target_suffixes:
                issues.append(f"{asset_id} aseprite profile 需要 atlas/json sidecar")
            return

        if asset_type == "spine":
            if source_tool and source_tool != "spine":
                issues.append(f"{asset_id} spine profile 的 source_tool 必须是 spine")
            if ".atlas" not in dependency_target_suffixes:
                issues.append(f"{asset_id} spine profile 缺少 .atlas 依赖")
            if not dependency_target_suffixes.intersection({".png", ".webp"}):
                issues.append(f"{asset_id} spine profile 缺少骨骼贴图依赖")
            return

        if asset_type == "substance":
            if source_tool and source_tool != "substance":
                issues.append(f"{asset_id} substance profile 的 source_tool 必须是 substance")
            if not texture_set:
                issues.append(f"{asset_id} substance profile 需要 texture_set")
            required_map_tokens = ("albedo", "normal", "orm")
            for token in required_map_tokens:
                if not any(token in name for name in dependency_target_names):
                    issues.append(f"{asset_id} substance profile 缺少 {token} 贴图")
            return

        if asset_type == "outsource":
            if source_tool and source_tool not in {"outsource", "outsource_delivery"}:
                issues.append(f"{asset_id} outsource profile 的 source_tool 必须是 outsource 或 outsource_delivery")
            if not package_version:
                issues.append(f"{asset_id} outsource profile 需要 package_version")
            if not license_name:
                issues.append(f"{asset_id} outsource profile 需要 license_name")
            return

    def _resolve_target_path(
        self,
        *,
        project_root: Path,
        schema: Dict[str, Any],
        asset_id: str,
        source_path: Optional[Path],
        raw_target: Any,
    ) -> Path:
        if raw_target:
            return self._resolve_input_path(project_root, raw_target) or (project_root / schema["default_directory"] / f"{asset_id}.bin")

        suffix = str(schema.get("default_target_extension") or "").strip().lower()
        if not suffix:
            suffix = source_path.suffix.lower() if source_path else ".png"
        return (project_root / schema["default_directory"] / f"{asset_id}{suffix}").resolve()

    def _resolve_input_path(self, project_root: Path, raw_value: Any) -> Optional[Path]:
        value = str(raw_value or "").strip()
        if not value:
            return None
        if value.startswith("res://"):
            return (project_root / value.replace("res://", "", 1)).resolve()
        candidate = Path(value)
        if candidate.is_absolute():
            return candidate.resolve()
        return (project_root / candidate).resolve()

    def _load_existing_manifest(self, manifest_path: Path) -> List[Dict[str, Any]]:
        if not manifest_path.exists():
            return []
        try:
            payload = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return []
        if isinstance(payload, dict):
            payload = payload.get("entries") or []
        return [dict(item) for item in payload if isinstance(item, dict)]

    def _build_manifest(
        self,
        asset_type: str,
        schema: Dict[str, Any],
        existing_entries: List[Dict[str, Any]],
        new_entries: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        merged = {str(entry.get("asset_id") or ""): dict(entry) for entry in existing_entries if entry.get("asset_id")}
        for entry in new_entries:
            merged[entry["asset_id"]] = dict(entry)
        return {
            "schema_version": ART_ASSET_MANIFEST_SCHEMA_VERSION,
            "asset_type": asset_type,
            "asset_label": ART_ASSET_TYPE_LABELS[asset_type],
            "default_directory": schema["default_directory"],
            "allowed_extensions": list(schema["allowed_extensions"]),
            "budget": {
                "max_dimension": schema.get("max_dimension"),
                "max_memory_mb": schema.get("max_memory_mb"),
            },
            "entries": [merged[key] for key in sorted(merged.keys()) if key],
        }

    def _build_snapshot(
        self,
        *,
        asset_type: str,
        schema: Dict[str, Any],
        manifest_path: Path,
        entries: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        copied_targets: List[str] = []
        for entry in entries:
            for candidate in [entry.get("target_path"), *(entry.get("dependency_targets") or [])]:
                text = str(candidate or "").strip()
                if text and text not in copied_targets:
                    copied_targets.append(text)
        return {
            "schema_version": ART_ASSET_MANIFEST_SCHEMA_VERSION,
            "asset_type": asset_type,
            "asset_label": ART_ASSET_TYPE_LABELS[asset_type],
            "default_directory": schema["default_directory"],
            "manifest_path": f"res://{manifest_path.relative_to(Path(getattr(self.godot_cli, 'project_path', '.') or '.').resolve()).as_posix()}",
            "entry_count": len(entries),
            "copied_target_count": len(copied_targets),
            "copied_targets": copied_targets,
            "entries": entries,
        }

    def _build_diff(self, before: str, after: str, manifest_path: Path) -> str:
        diff = difflib.unified_diff(
            before.splitlines(),
            after.splitlines(),
            fromfile=f"a/{manifest_path.name}",
            tofile=f"b/{manifest_path.name}",
            lineterm="",
        )
        return "\n".join(diff)

    def _build_report(
        self,
        *,
        asset_type: str,
        action: str,
        manifest_path: Path,
        schema: Dict[str, Any],
        entries: List[Dict[str, Any]],
        issues: List[str],
        copy_plan: List[Dict[str, str]],
        diff_text: str,
    ) -> str:
        lines = [
            f"# Art Asset Pipeline Report: {asset_type}",
            "",
            f"- Action: {action}",
            f"- Manifest: {manifest_path}",
            f"- Entry Count: {len(entries)}",
            f"- Issue Count: {len(issues)}",
            f"- Default Directory: {schema['default_directory']}",
            f"- Allowed Extensions: {', '.join(schema['allowed_extensions'])}",
            f"- Max Dimension: {schema.get('max_dimension', '-')}",
            f"- Max Memory MB: {schema.get('max_memory_mb', '-')}",
            "",
            "## Validation",
            "",
        ]
        lines.extend([f"- {issue}" for issue in issues] or ["- Validation passed"])
        lines.extend(["", "## Entries", ""])
        for entry in entries:
            lines.append(
                f"- {entry['asset_id']}: {entry['target_path']}"
                f" | {entry.get('width') or '-'}x{entry.get('height') or '-'}"
                f" | mem={entry.get('estimated_memory_mb') if entry.get('estimated_memory_mb') is not None else '-'}"
            )
            if entry.get("source_tool"):
                lines.append(f"  source_tool={entry['source_tool']}")
            if entry.get("lod_count") is not None:
                lines.append(f"  lod_count={entry['lod_count']}")
            if entry.get("texture_set"):
                lines.append(f"  texture_set={entry['texture_set']}")
            if entry.get("package_version"):
                lines.append(f"  package_version={entry['package_version']}")
            if entry.get("license_name"):
                lines.append(f"  license_name={entry['license_name']}")
            if entry.get("dependency_targets"):
                lines.append(f"  dependency_targets={', '.join(entry['dependency_targets'])}")
        if not entries:
            lines.append("- No entries")
        lines.extend(["", "## Copy Plan", ""])
        lines.extend([
            f"- {item['source_path']} -> {item['target_res_path']}"
            for item in copy_plan
        ] or ["- No file copies scheduled"])
        lines.extend(["", "## Manifest Diff", "", "```diff", diff_text or "(no diff)", "```"])
        return "\n".join(lines)

    def _snake_case(self, value: str) -> str:
        text = str(value or "").strip()
        text = text.replace("\\", "/").split("/")[-1]
        stem = Path(text).stem if text else ""
        stem = stem.replace("-", "_").replace(" ", "_")
        normalized = []
        for index, char in enumerate(stem):
            if char.isupper() and index > 0 and normalized[-1] != "_":
                normalized.append("_")
            normalized.append(char.lower() if char.isalnum() else "_")
        return "".join(normalized).strip("_") or "art_asset"

    def _normalize_int(self, value: Any) -> Optional[int]:
        if value in (None, ""):
            return None
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    def _normalize_float(self, value: Any) -> Optional[float]:
        if value in (None, ""):
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    def _clean_tags(self, value: Any) -> List[str]:
        if isinstance(value, str):
            items = [value]
        elif isinstance(value, (list, tuple, set)):
            items = list(value)
        else:
            return []
        seen = set()
        cleaned = []
        for item in items:
            text = str(item or "").strip()
            if not text or text in seen:
                continue
            seen.add(text)
            cleaned.append(text)
        return cleaned

    def _normalize_path_list(self, value: Any) -> List[str]:
        if isinstance(value, str):
            items = [segment.strip() for segment in value.replace("\r", "\n").split("\n")]
        elif isinstance(value, (list, tuple, set)):
            items = [str(item or "").strip() for item in value]
        else:
            return []
        cleaned: List[str] = []
        seen = set()
        for item in items:
            if not item or item in seen:
                continue
            seen.add(item)
            cleaned.append(item)
        return cleaned

    def _to_res_path(self, project_root: Path, path: Path) -> str:
        try:
            return f"res://{path.resolve().relative_to(project_root).as_posix()}"
        except ValueError:
            return str(path.resolve())

    def _to_display_path(self, project_root: Path, path: Path) -> str:
        try:
            return f"res://{path.resolve().relative_to(project_root).as_posix()}"
        except ValueError:
            return str(path.resolve())

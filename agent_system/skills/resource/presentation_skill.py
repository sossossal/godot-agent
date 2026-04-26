"""
Presentation pipeline skill.
"""

from __future__ import annotations

import difflib
import json
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from pydantic import BaseModel, Field

from ..base import BaseSkill, SkillMetadata
from ...contracts import PRESENTATION_PROFILE_SCHEMA_VERSION, normalize_presentation_profile
from ...models import Artifact, Task, ToolResult
from ...tools.blueprint_manager import Feature
from ...validations import ProjectLayoutValidator


PRESENTATION_TYPE_LABELS: Dict[str, str] = {
    "animation": "动画表现",
    "vfx": "VFX 表现",
    "shader": "Shader 表现",
    "audio": "音频表现",
}

PRESENTATION_SCHEMAS: Dict[str, Dict[str, Any]] = {
    "animation": {
        "manifest_path": "assets/manifests/animation_profiles.json",
        "sample_entries": [
            {
                "profile_id": "hero_locomotion",
                "animation_mode": "animation_tree",
                "target_node_path": "CharacterRoot",
                "target_script_path": "res://scripts/presentation/hero_locomotion_animation_controller.gd",
                "animation_clips": ["idle", "run", "jump", "fall"],
                "state_machine_states": ["idle", "run", "jump", "fall"],
                "acceptance_checks": [
                    "animation_player_bootstraps",
                    "animation_tree_state_machine_ready",
                    "locomotion_clips_declared",
                ],
                "notes": "角色移动与跳跃状态机骨架",
            }
        ],
    },
    "vfx": {
        "manifest_path": "assets/manifests/vfx_profiles.json",
        "sample_entries": [
            {
                "profile_id": "slash_hit_fx",
                "particle_mode": "gpu_particles_2d",
                "amount": 24,
                "lifetime_seconds": 0.6,
                "one_shot": True,
                "color_hex": "#ffb347",
                "target_scene_path": "res://assets/vfx/slash_hit_fx.tscn",
                "target_material_path": "res://assets/vfx/slash_hit_fx_process_material.tres",
                "acceptance_checks": [
                    "vfx_scene_generated",
                    "particle_material_generated",
                    "one_shot_profile_ready",
                ],
                "notes": "命中特效粒子模板",
            }
        ],
    },
    "shader": {
        "manifest_path": "assets/manifests/shader_profiles.json",
        "sample_entries": [
            {
                "profile_id": "water_surface",
                "shader_mode": "canvas_item",
                "target_shader_path": "res://assets/shaders/water_surface.gdshader",
                "target_material_path": "res://assets/materials/water_surface_material.tres",
                "shader_params": {
                    "wave_strength": 0.15,
                    "scroll_speed": 0.4,
                    "tint_color": "#5bc0ff",
                },
                "acceptance_checks": [
                    "shader_file_generated",
                    "shader_material_generated",
                    "shader_params_declared",
                ],
                "notes": "水面滚动与着色参数模板",
            }
        ],
    },
    "audio": {
        "manifest_path": "assets/manifests/audio_profiles.json",
        "sample_entries": [
            {
                "profile_id": "ui_click",
                "audio_role": "ui",
                "event_name": "ui_click",
                "bus_name": "UI",
                "audio_stream_path": "res://assets/audio/ui_click.ogg",
                "target_script_path": "res://scripts/audio/ui_click_audio_router.gd",
                "autoplay": False,
                "acceptance_checks": [
                    "audio_event_declared",
                    "bus_mapping_declared",
                    "router_script_generated",
                ],
                "notes": "UI 点击事件与总线路由模板",
            }
        ],
    },
}

_PRESENTATION_TYPE_VALUES = set(PRESENTATION_SCHEMAS.keys())
_ANIMATION_MODES = {"animation_player", "animation_tree", "tween_state"}
_PARTICLE_MODES = {"gpu_particles_2d", "gpu_particles_3d", "cpu_particles_2d", "cpu_particles_3d"}
_SHADER_MODES = {"canvas_item", "spatial", "particles"}
_AUDIO_ROLES = {"bgm", "sfx", "ui", "ambience"}


class PresentationParams(BaseModel):
    action: str = Field(default="validate", description="template | validate | preview | apply")
    presentation_type: str = Field(default="animation", description="animation | vfx | shader | audio")
    profile_id: Optional[str] = Field(default=None, description="profile 标识，要求 snake_case")
    manifest_path: Optional[str] = Field(default=None, description="manifest 路径")
    target_script_path: Optional[str] = Field(default=None, description="生成脚本路径")
    target_scene_path: Optional[str] = Field(default=None, description="生成场景路径")
    target_shader_path: Optional[str] = Field(default=None, description="生成 shader 路径")
    target_material_path: Optional[str] = Field(default=None, description="生成 material 路径")
    target_node_path: str = Field(default="", description="目标节点路径")
    animation_mode: Optional[str] = Field(default=None, description="animation_player | animation_tree | tween_state")
    animation_clips: List[str] = Field(default_factory=list, description="动画片段列表")
    state_machine_states: List[str] = Field(default_factory=list, description="状态机状态列表")
    particle_mode: Optional[str] = Field(default=None, description="gpu_particles_2d | gpu_particles_3d | cpu_particles_2d | cpu_particles_3d")
    amount: Optional[int] = Field(default=None, description="粒子数量")
    lifetime_seconds: Optional[float] = Field(default=None, description="粒子生命周期")
    one_shot: bool = Field(default=False, description="是否单次播放")
    texture_path: Optional[str] = Field(default=None, description="粒子或 shader 贴图路径")
    color_hex: str = Field(default="#ffffff", description="主色，#RRGGBB")
    shader_mode: Optional[str] = Field(default=None, description="canvas_item | spatial | particles")
    shader_params: Dict[str, Any] = Field(default_factory=dict, description="shader 参数")
    audio_role: Optional[str] = Field(default=None, description="bgm | sfx | ui | ambience")
    event_name: Optional[str] = Field(default=None, description="音频事件名")
    bus_name: Optional[str] = Field(default=None, description="音频总线名")
    audio_stream_path: Optional[str] = Field(default=None, description="音频流路径")
    autoplay: bool = Field(default=False, description="是否自动播放")
    acceptance_checks: List[str] = Field(default_factory=list, description="验收项")
    notes: str = Field(default="", description="备注")
    entries: List[Dict[str, Any]] = Field(default_factory=list, description="结构化 profile 条目")


class PresentationPipelineSkill(BaseSkill):
    metadata = SkillMetadata(
        name="manage_presentation_pipeline",
        description="管理动画/VFX/shader/audio 表现层模板，支持 template、validate、preview、apply",
        category="resource",
        tags=["presentation", "animation", "vfx", "shader", "audio"],
    )

    input_model = PresentationParams

    def get_snapshot(
        self,
        *,
        presentation_type: str,
        manifest_path: Optional[str] = None,
        profile_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        normalized_type = self._normalize_type(presentation_type)
        project_root = Path(getattr(self.godot_cli, "project_path", ".") or ".").resolve()
        resolved_manifest = self._resolve_manifest_path(project_root, normalized_type, manifest_path)
        entries = self._load_existing_manifest(resolved_manifest)
        if profile_id:
            wanted = self._snake_case(profile_id)
            entries = [entry for entry in entries if str(entry.get("profile_id") or "") == wanted]
        generated_paths: List[str] = []
        for entry in entries:
            for item in list(entry.get("generation_targets") or []):
                text = str(item or "").strip()
                if text and text not in generated_paths:
                    generated_paths.append(text)
        return normalize_presentation_profile({
            "presentation_type": normalized_type,
            "manifest_path": f"res://{resolved_manifest.relative_to(project_root).as_posix()}",
            "entry_count": len(entries),
            "generated_path_count": len(generated_paths),
            "generated_paths": generated_paths,
            "entries": entries,
        })

    def execute(self, task: Task, params: Dict[str, Any]) -> ToolResult:
        p = PresentationParams(**params)
        action = self._normalize_action(p.action)
        presentation_type = self._normalize_type(p.presentation_type)
        project_root = Path(getattr(self.godot_cli, "project_path", ".") or ".").resolve()
        layout_validator = ProjectLayoutValidator(project_root=project_root, runtime_root=Path.cwd())
        manifest_path = self._resolve_manifest_path(project_root, presentation_type, p.manifest_path)

        manifest_layout = layout_validator.validate_managed_path(manifest_path, "asset_manifest")
        if not manifest_layout["passed"]:
            return self.build_result(
                success=False,
                message=f"{PRESENTATION_TYPE_LABELS[presentation_type]} manifest 路径不符合文件树规范",
                params=self.dump_model(p),
                error="; ".join(issue["message"] for issue in manifest_layout["issues"]),
                validation={"passed": False, "issues": [issue["code"] for issue in manifest_layout["issues"]]},
            )

        raw_entries = self._resolve_entries(p, presentation_type, action)
        normalized_entries, issues, generation_plan = self._normalize_entries(
            entries=raw_entries,
            presentation_type=presentation_type,
            project_root=project_root,
            layout_validator=layout_validator,
        )
        current_manifest = self._load_existing_manifest(manifest_path)
        merged_manifest = self._build_manifest(presentation_type, current_manifest, normalized_entries)
        manifest_content = json.dumps(merged_manifest, ensure_ascii=False, indent=2)
        current_content = manifest_path.read_text(encoding="utf-8") if manifest_path.exists() else ""
        diff_text = self._build_diff(current_content, manifest_content, manifest_path)

        report_path = Path("logs/reports") / f"presentation_{presentation_type}_{action}_{int(time.time())}.md"
        report_layout = layout_validator.validate_managed_path(report_path, "runtime_report")
        if not report_layout["passed"]:
            return self.build_result(
                success=False,
                message=f"{PRESENTATION_TYPE_LABELS[presentation_type]} 报告路径不符合文件树规范",
                params=self.dump_model(p),
                error="; ".join(issue["message"] for issue in report_layout["issues"]),
                validation={"passed": False, "issues": [issue["code"] for issue in report_layout["issues"]]},
            )

        report_content = self._build_report(
            presentation_type=presentation_type,
            action=action,
            manifest_path=manifest_path,
            entries=normalized_entries,
            issues=issues,
            generation_plan=generation_plan,
            diff_text=diff_text,
        )
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(report_content, encoding="utf-8")

        snapshot = normalize_presentation_profile({
            "presentation_type": presentation_type,
            "manifest_path": f"res://{manifest_path.relative_to(project_root).as_posix()}",
            "entry_count": len(normalized_entries),
            "generated_path_count": len(generation_plan),
            "generated_paths": [item["res_path"] for item in generation_plan],
            "entries": normalized_entries,
        })
        task.context.setdefault("contract_versions", {})["presentation_profile"] = PRESENTATION_PROFILE_SCHEMA_VERSION
        task.context.update({
            "presentation_type": presentation_type,
            "presentation_action": action,
            "presentation_manifest_path": f"res://{manifest_path.relative_to(project_root).as_posix()}",
            "presentation_entry_count": len(normalized_entries),
            "presentation_issue_count": len(issues),
            "presentation_generated_path_count": len(generation_plan),
            "presentation_generated_paths": [item["res_path"] for item in generation_plan],
            "presentation_profile": snapshot,
        })

        artifacts = [
            Artifact(
                name=manifest_path.name,
                path=str(manifest_path),
                type="resource",
                content=manifest_content if len(manifest_content) < 40000 else None,
                metadata={"presentation_type": presentation_type, "action": action, "manifest": True},
            ),
            Artifact(
                name=report_path.name,
                path=str(report_path),
                type="report",
                content=report_content,
                metadata={"presentation_type": presentation_type, "action": action},
            ),
        ]
        artifacts.extend(self._build_preview_artifacts(generation_plan))

        if issues and action in {"validate", "preview", "apply"}:
            return self.build_result(
                success=False,
                message=f"{PRESENTATION_TYPE_LABELS[presentation_type]} 校验失败",
                params=self.dump_model(p),
                error="; ".join(issues),
                artifacts=artifacts,
                data={"presentation_profile": snapshot},
                validation={
                    "passed": False,
                    "issues": issues,
                    "checks": [{"name": "presentation_profile_validation", "status": "failed"}],
                },
            )

        if action == "validate":
            return self.build_result(
                success=True,
                message=f"{PRESENTATION_TYPE_LABELS[presentation_type]} 校验通过",
                params=self.dump_model(p),
                artifacts=artifacts,
                data={"presentation_profile": snapshot},
                validation={
                    "passed": True,
                    "checks": [{"name": "presentation_profile_validation", "status": "passed"}],
                },
                rollback={"available": False, "strategy": "validate_only"},
            )

        if action == "preview":
            return self.build_result(
                success=True,
                message=f"{PRESENTATION_TYPE_LABELS[presentation_type]} 预览完成",
                params=self.dump_model(p),
                artifacts=artifacts,
                data={"presentation_profile": snapshot},
                validation={
                    "passed": True,
                    "checks": [
                        {"name": "presentation_profile_validation", "status": "passed"},
                        {"name": "generation_plan_built", "status": "passed"},
                    ],
                },
                rollback={"available": False, "strategy": "preview_only"},
            )

        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        manifest_backup = self.backup_existing_file(task, str(manifest_path))
        manifest_path.write_text(manifest_content, encoding="utf-8")
        written_paths: List[str] = []
        for item in generation_plan:
            target_path = Path(item["path"])
            target_path.parent.mkdir(parents=True, exist_ok=True)
            self.backup_existing_file(task, str(target_path))
            target_path.write_text(item["content"], encoding="utf-8")
            written_paths.append(item["res_path"])
            artifacts.append(Artifact(
                name=target_path.name,
                path=item["res_path"],
                type=item["artifact_type"],
                content=item["content"] if len(item["content"]) < 30000 else None,
                metadata={"presentation_type": presentation_type, "action": action, "profile_id": item["profile_id"]},
            ))

        task.context["presentation_written"] = True
        task.context["presentation_generated_paths"] = written_paths
        blueprint = task.context.get("blueprint_manager")
        if blueprint:
            for entry in normalized_entries:
                blueprint.add_feature(Feature(
                    name=f"presentation_{entry['profile_id']}",
                    description=f"{PRESENTATION_TYPE_LABELS[presentation_type]} profile: {entry['profile_id']}",
                    status="planned",
                    files=list(entry.get("generation_targets") or []),
                    creation_skill=self.metadata.name,
                    creation_params={**self.dump_model(p), "profile_id": entry["profile_id"]},
                ))

        rollback_paths = [backup.backup_path for backup in task.backups]
        if manifest_backup and manifest_backup not in rollback_paths:
            rollback_paths.append(manifest_backup)
        return self.build_result(
            success=True,
            message=f"{PRESENTATION_TYPE_LABELS[presentation_type]} 已生成并登记",
            params=self.dump_model(p),
            artifacts=artifacts,
            data={"presentation_profile": snapshot},
            validation={
                "passed": True,
                "checks": [
                    {"name": "presentation_profile_validation", "status": "passed"},
                    {"name": "presentation_manifest_written", "status": "passed"},
                    {"name": "presentation_scaffolds_written", "status": "passed"},
                ],
            },
            rollback={
                "available": True,
                "strategy": "restore_presentation_manifest_and_generated_files",
                "backup_paths": rollback_paths,
            },
            metadata={"written_path_count": len(written_paths)},
        )

    def _normalize_action(self, value: str) -> str:
        normalized = str(value or "validate").strip().lower()
        return normalized if normalized in {"template", "validate", "preview", "apply"} else "validate"

    def _normalize_type(self, value: str) -> str:
        normalized = str(value or "animation").strip().lower()
        return normalized if normalized in _PRESENTATION_TYPE_VALUES else "animation"

    def _resolve_manifest_path(self, project_root: Path, presentation_type: str, raw_path: Optional[str]) -> Path:
        relative = str(raw_path or PRESENTATION_SCHEMAS[presentation_type]["manifest_path"]).strip()
        if relative.startswith("res://"):
            relative = relative.replace("res://", "", 1)
        return (project_root / relative).resolve()

    def _resolve_entries(self, params: PresentationParams, presentation_type: str, action: str) -> List[Dict[str, Any]]:
        if params.entries:
            return [dict(entry) for entry in params.entries]
        if action == "template":
            return [dict(entry) for entry in PRESENTATION_SCHEMAS[presentation_type]["sample_entries"]]
        return [{
            "profile_id": params.profile_id,
            "target_script_path": params.target_script_path,
            "target_scene_path": params.target_scene_path,
            "target_shader_path": params.target_shader_path,
            "target_material_path": params.target_material_path,
            "target_node_path": params.target_node_path,
            "animation_mode": params.animation_mode,
            "animation_clips": list(params.animation_clips or []),
            "state_machine_states": list(params.state_machine_states or []),
            "particle_mode": params.particle_mode,
            "amount": params.amount,
            "lifetime_seconds": params.lifetime_seconds,
            "one_shot": params.one_shot,
            "texture_path": params.texture_path,
            "color_hex": params.color_hex,
            "shader_mode": params.shader_mode,
            "shader_params": dict(params.shader_params or {}),
            "audio_role": params.audio_role,
            "event_name": params.event_name,
            "bus_name": params.bus_name,
            "audio_stream_path": params.audio_stream_path,
            "autoplay": params.autoplay,
            "acceptance_checks": list(params.acceptance_checks or []),
            "notes": params.notes,
        }]

    def _normalize_entries(
        self,
        *,
        entries: List[Dict[str, Any]],
        presentation_type: str,
        project_root: Path,
        layout_validator: ProjectLayoutValidator,
    ) -> Tuple[List[Dict[str, Any]], List[str], List[Dict[str, Any]]]:
        if not entries:
            return [], ["表现层 profile 条目不能为空"], []

        normalized_entries: List[Dict[str, Any]] = []
        issues: List[str] = []
        generation_plan: List[Dict[str, Any]] = []
        seen_ids = set()
        for index, raw_entry in enumerate(entries, start=1):
            if presentation_type == "animation":
                entry, entry_issues, files = self._normalize_animation_entry(raw_entry, project_root, layout_validator)
            elif presentation_type == "vfx":
                entry, entry_issues, files = self._normalize_vfx_entry(raw_entry, project_root, layout_validator)
            elif presentation_type == "shader":
                entry, entry_issues, files = self._normalize_shader_entry(raw_entry, project_root, layout_validator)
            else:
                entry, entry_issues, files = self._normalize_audio_entry(raw_entry, project_root, layout_validator)

            profile_id = entry.get("profile_id", "")
            if not profile_id:
                entry_issues.append(f"第 {index} 条 profile 缺少 profile_id")
            elif profile_id in seen_ids:
                entry_issues.append(f"profile_id 重复: {profile_id}")
            seen_ids.add(profile_id)

            normalized_entries.append(entry)
            generation_plan.extend(files)
            issues.extend(entry_issues)
        return normalized_entries, issues, generation_plan

    def _normalize_animation_entry(
        self,
        raw_entry: Dict[str, Any],
        project_root: Path,
        layout_validator: ProjectLayoutValidator,
    ) -> Tuple[Dict[str, Any], List[str], List[Dict[str, Any]]]:
        issues: List[str] = []
        profile_id = self._snake_case(raw_entry.get("profile_id") or "animation_profile")
        animation_mode = self._normalize_choice(raw_entry.get("animation_mode"), _ANIMATION_MODES, "animation_player")
        target_node_path = str(raw_entry.get("target_node_path") or "AnimatedNode").strip() or "AnimatedNode"
        script_path = self._resolve_output_path(
            project_root,
            raw_entry.get("target_script_path"),
            f"scripts/presentation/{profile_id}_animation_controller.gd",
        )
        clips = self._clean_text_list(raw_entry.get("animation_clips")) or ["idle", "run"]
        states = self._clean_text_list(raw_entry.get("state_machine_states")) or (clips if animation_mode != "animation_player" else [])
        acceptance_checks = self._clean_text_list(raw_entry.get("acceptance_checks")) or [
            "animation_controller_generated",
            "presentation_node_binding_declared",
        ]
        notes = str(raw_entry.get("notes") or "").strip()

        self._validate_path(script_path, "generated_script", layout_validator, issues, profile_id)
        if animation_mode != "animation_player" and not states:
            issues.append(f"{profile_id} 需要至少一个 state_machine_state")

        res_path = self._to_res_path(project_root, script_path)
        entry = {
            "profile_id": profile_id,
            "presentation_type": "animation",
            "animation_mode": animation_mode,
            "target_node_path": target_node_path,
            "target_script_path": res_path,
            "animation_clips": clips,
            "state_machine_states": states,
            "acceptance_checks": acceptance_checks,
            "notes": notes,
            "generation_targets": [res_path],
        }
        return entry, issues, [{
            "profile_id": profile_id,
            "path": str(script_path),
            "res_path": res_path,
            "artifact_type": "script",
            "content": self._render_animation_script(entry),
        }]

    def _normalize_vfx_entry(
        self,
        raw_entry: Dict[str, Any],
        project_root: Path,
        layout_validator: ProjectLayoutValidator,
    ) -> Tuple[Dict[str, Any], List[str], List[Dict[str, Any]]]:
        issues: List[str] = []
        profile_id = self._snake_case(raw_entry.get("profile_id") or "vfx_profile")
        particle_mode = self._normalize_choice(raw_entry.get("particle_mode"), _PARTICLE_MODES, "gpu_particles_2d")
        amount = self._normalize_int(raw_entry.get("amount"), 24)
        lifetime_seconds = self._normalize_float(raw_entry.get("lifetime_seconds"), 0.6)
        one_shot = bool(raw_entry.get("one_shot", True))
        color_hex = self._normalize_color(raw_entry.get("color_hex") or "#ffffff", issues, profile_id)
        scene_path = self._resolve_output_path(project_root, raw_entry.get("target_scene_path"), f"assets/vfx/{profile_id}.tscn")
        material_path = self._resolve_output_path(project_root, raw_entry.get("target_material_path"), f"assets/vfx/{profile_id}_process_material.tres")
        texture_path = self._normalize_res_path(raw_entry.get("texture_path"))
        acceptance_checks = self._clean_text_list(raw_entry.get("acceptance_checks")) or [
            "vfx_scene_generated",
            "particle_material_generated",
        ]
        notes = str(raw_entry.get("notes") or "").strip()

        self._validate_path(scene_path, "art_asset", layout_validator, issues, profile_id)
        self._validate_path(material_path, "art_asset", layout_validator, issues, profile_id)
        if amount <= 0:
            issues.append(f"{profile_id} amount 必须大于 0")
        if lifetime_seconds <= 0:
            issues.append(f"{profile_id} lifetime_seconds 必须大于 0")

        scene_res = self._to_res_path(project_root, scene_path)
        material_res = self._to_res_path(project_root, material_path)
        entry = {
            "profile_id": profile_id,
            "presentation_type": "vfx",
            "particle_mode": particle_mode,
            "amount": amount,
            "lifetime_seconds": lifetime_seconds,
            "one_shot": one_shot,
            "color_hex": color_hex,
            "texture_path": texture_path,
            "target_scene_path": scene_res,
            "target_material_path": material_res,
            "acceptance_checks": acceptance_checks,
            "notes": notes,
            "generation_targets": [scene_res, material_res],
        }
        return entry, issues, [
            {
                "profile_id": profile_id,
                "path": str(material_path),
                "res_path": material_res,
                "artifact_type": "resource",
                "content": self._render_vfx_material(entry),
            },
            {
                "profile_id": profile_id,
                "path": str(scene_path),
                "res_path": scene_res,
                "artifact_type": "scene",
                "content": self._render_vfx_scene(entry),
            },
        ]

    def _normalize_shader_entry(
        self,
        raw_entry: Dict[str, Any],
        project_root: Path,
        layout_validator: ProjectLayoutValidator,
    ) -> Tuple[Dict[str, Any], List[str], List[Dict[str, Any]]]:
        issues: List[str] = []
        profile_id = self._snake_case(raw_entry.get("profile_id") or "shader_profile")
        shader_mode = self._normalize_choice(raw_entry.get("shader_mode"), _SHADER_MODES, "canvas_item")
        shader_path = self._resolve_output_path(project_root, raw_entry.get("target_shader_path"), f"assets/shaders/{profile_id}.gdshader")
        material_path = self._resolve_output_path(project_root, raw_entry.get("target_material_path"), f"assets/materials/{profile_id}_material.tres")
        shader_params = dict(raw_entry.get("shader_params") or {})
        if not shader_params:
            shader_params = {"strength": 0.15, "tint_color": "#ffffff"}
        acceptance_checks = self._clean_text_list(raw_entry.get("acceptance_checks")) or [
            "shader_file_generated",
            "shader_material_generated",
        ]
        notes = str(raw_entry.get("notes") or "").strip()

        self._validate_path(shader_path, "art_asset", layout_validator, issues, profile_id)
        self._validate_path(material_path, "art_asset", layout_validator, issues, profile_id)

        shader_res = self._to_res_path(project_root, shader_path)
        material_res = self._to_res_path(project_root, material_path)
        entry = {
            "profile_id": profile_id,
            "presentation_type": "shader",
            "shader_mode": shader_mode,
            "shader_params": shader_params,
            "target_shader_path": shader_res,
            "target_material_path": material_res,
            "acceptance_checks": acceptance_checks,
            "notes": notes,
            "generation_targets": [shader_res, material_res],
        }
        return entry, issues, [
            {
                "profile_id": profile_id,
                "path": str(shader_path),
                "res_path": shader_res,
                "artifact_type": "resource",
                "content": self._render_shader_code(entry),
            },
            {
                "profile_id": profile_id,
                "path": str(material_path),
                "res_path": material_res,
                "artifact_type": "resource",
                "content": self._render_shader_material(entry),
            },
        ]

    def _normalize_audio_entry(
        self,
        raw_entry: Dict[str, Any],
        project_root: Path,
        layout_validator: ProjectLayoutValidator,
    ) -> Tuple[Dict[str, Any], List[str], List[Dict[str, Any]]]:
        issues: List[str] = []
        profile_id = self._snake_case(raw_entry.get("profile_id") or raw_entry.get("event_name") or "audio_profile")
        audio_role = self._normalize_choice(raw_entry.get("audio_role"), _AUDIO_ROLES, "sfx")
        event_name = self._snake_case(raw_entry.get("event_name") or profile_id)
        bus_name = str(raw_entry.get("bus_name") or "Master").strip() or "Master"
        stream_path = self._normalize_res_path(raw_entry.get("audio_stream_path"))
        autoplay = bool(raw_entry.get("autoplay", False))
        script_path = self._resolve_output_path(project_root, raw_entry.get("target_script_path"), f"scripts/audio/{profile_id}_audio_router.gd")
        acceptance_checks = self._clean_text_list(raw_entry.get("acceptance_checks")) or [
            "audio_event_declared",
            "bus_mapping_declared",
            "router_script_generated",
        ]
        notes = str(raw_entry.get("notes") or "").strip()

        self._validate_path(script_path, "generated_script", layout_validator, issues, profile_id)
        if not event_name:
            issues.append(f"{profile_id} 缺少 event_name")

        script_res = self._to_res_path(project_root, script_path)
        entry = {
            "profile_id": profile_id,
            "presentation_type": "audio",
            "audio_role": audio_role,
            "event_name": event_name,
            "bus_name": bus_name,
            "audio_stream_path": stream_path,
            "autoplay": autoplay,
            "acceptance_checks": acceptance_checks,
            "notes": notes,
            "target_script_path": script_res,
            "generation_targets": [script_res],
        }
        return entry, issues, [{
            "profile_id": profile_id,
            "path": str(script_path),
            "res_path": script_res,
            "artifact_type": "script",
            "content": self._render_audio_script(entry),
        }]

    def _validate_path(
        self,
        path: Path,
        kind: str,
        layout_validator: ProjectLayoutValidator,
        issues: List[str],
        profile_id: str,
    ) -> None:
        result = layout_validator.validate_managed_path(path, kind)
        if not result["passed"]:
            for issue in result["issues"]:
                issues.append(f"{profile_id} 路径非法: {issue['message']}")

    def _build_manifest(
        self,
        presentation_type: str,
        existing_entries: List[Dict[str, Any]],
        new_entries: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        merged = {str(entry.get("profile_id") or ""): dict(entry) for entry in existing_entries if entry.get("profile_id")}
        for entry in new_entries:
            merged[entry["profile_id"]] = dict(entry)
        generated_paths: List[str] = []
        for entry in merged.values():
            for item in list(entry.get("generation_targets") or []):
                text = str(item or "").strip()
                if text and text not in generated_paths:
                    generated_paths.append(text)
        return {
            "schema_version": PRESENTATION_PROFILE_SCHEMA_VERSION,
            "presentation_type": presentation_type,
            "presentation_label": PRESENTATION_TYPE_LABELS[presentation_type],
            "generated_path_count": len(generated_paths),
            "generated_paths": generated_paths,
            "entries": [merged[key] for key in sorted(merged.keys()) if key],
        }

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

    def _build_diff(self, before: str, after: str, manifest_path: Path) -> str:
        diff = difflib.unified_diff(
            before.splitlines(),
            after.splitlines(),
            fromfile=f"a/{manifest_path.name}",
            tofile=f"b/{manifest_path.name}",
            lineterm="",
        )
        return "\n".join(diff)

    def _build_preview_artifacts(self, generation_plan: List[Dict[str, Any]]) -> List[Artifact]:
        artifacts: List[Artifact] = []
        for item in generation_plan:
            artifacts.append(Artifact(
                name=Path(item["path"]).name,
                path=item["res_path"],
                type=item["artifact_type"],
                content=item["content"] if len(item["content"]) < 20000 else None,
                metadata={"preview_only": True, "profile_id": item["profile_id"]},
            ))
        return artifacts

    def _build_report(
        self,
        *,
        presentation_type: str,
        action: str,
        manifest_path: Path,
        entries: List[Dict[str, Any]],
        issues: List[str],
        generation_plan: List[Dict[str, Any]],
        diff_text: str,
    ) -> str:
        lines = [
            f"# Presentation Pipeline Report: {presentation_type}",
            "",
            f"- Action: {action}",
            f"- Manifest: {manifest_path}",
            f"- Entry Count: {len(entries)}",
            f"- Issue Count: {len(issues)}",
            f"- Generated File Count: {len(generation_plan)}",
            "",
            "## Validation",
            "",
        ]
        lines.extend([f"- {issue}" for issue in issues] or ["- Validation passed"])
        lines.extend(["", "## Entries", ""])
        for entry in entries:
            summary_bits = [f"profile_id={entry['profile_id']}", f"type={entry['presentation_type']}"]
            if entry.get("animation_mode"):
                summary_bits.append(f"mode={entry['animation_mode']}")
            if entry.get("particle_mode"):
                summary_bits.append(f"particles={entry['particle_mode']}")
            if entry.get("shader_mode"):
                summary_bits.append(f"shader={entry['shader_mode']}")
            if entry.get("event_name"):
                summary_bits.append(f"event={entry['event_name']}")
            lines.append(f"- {' | '.join(summary_bits)}")
        if not entries:
            lines.append("- No entries")
        lines.extend(["", "## Generated Targets", ""])
        lines.extend([f"- {item['res_path']}" for item in generation_plan] or ["- No generated files"])
        lines.extend(["", "## Manifest Diff", "", "```diff", diff_text or "(no diff)", "```"])
        return "\n".join(lines)

    def _render_animation_script(self, entry: Dict[str, Any]) -> str:
        profile_id = entry["profile_id"]
        target_node_path = entry["target_node_path"]
        clips = entry["animation_clips"]
        states = entry["state_machine_states"]
        clip_constants = "\n".join(f'const CLIP_{clip.upper()} := "{clip}"' for clip in clips)
        state_enum = "\n".join(f"\t{state.upper()}," for state in states) or "\tDEFAULT,"
        ready_binding = (
            f'@onready var animated_target: Node = get_node_or_null("{target_node_path}")\n'
            '@onready var animation_player: AnimationPlayer = _ensure_animation_player()\n'
        )
        if entry["animation_mode"] == "animation_tree":
            ready_binding += '@onready var animation_tree: AnimationTree = _ensure_animation_tree(animation_player)\n'
        state_matches = "".join(
            f'\t\t"{state}":\n\t\t\tplay_clip(CLIP_{(state if state in clips else clips[0]).upper()})\n'
            for state in states
        )
        return (
            "extends Node\n\n"
            f"class_name {self._pascal_case(profile_id)}AnimationController\n\n"
            f"# Auto-generated by manage_presentation_pipeline for `{profile_id}`.\n"
            f"# Declared clips: {', '.join(clips)}\n\n"
            f"{clip_constants}\n\n"
            "enum State {\n"
            f"{state_enum}\n"
            "}\n\n"
            f"{ready_binding}\n"
            "var current_state: State = State.values()[0]\n\n"
            "func _ready() -> void:\n"
            "\tif animation_player == null:\n"
            '\t\tpush_warning("AnimationPlayer was not found or created.")\n'
            "\treturn\n\n"
            "func play_clip(clip_name: StringName) -> void:\n"
            "\tif animation_player == null:\n"
            "\t\treturn\n"
            '\tif not animation_player.has_animation(String(clip_name)):\n'
            '\t\tpush_warning("Missing animation clip: %s" % clip_name)\n'
            "\t\treturn\n"
            "\tanimation_player.play(String(clip_name))\n\n"
            "func transition_to(state_name: String) -> void:\n"
            "\tmatch state_name.to_lower():\n"
            f"{state_matches}"
            '\t\t_:\n\t\t\tpush_warning("Unknown presentation state: %s" % state_name)\n\n'
            "func _ensure_animation_player() -> AnimationPlayer:\n"
            "\tif animated_target == null:\n"
            "\t\treturn null\n"
            "\tvar existing := animated_target.get_node_or_null(\"AnimationPlayer\")\n"
            "\tif existing is AnimationPlayer:\n"
            "\t\treturn existing\n"
            "\tvar created := AnimationPlayer.new()\n"
            '\tcreated.name = "AnimationPlayer"\n'
            "\tanimated_target.add_child(created)\n"
            "\treturn created\n\n"
            "func _ensure_animation_tree(player: AnimationPlayer) -> AnimationTree:\n"
            "\tif animated_target == null:\n"
            "\t\treturn null\n"
            "\tvar existing := animated_target.get_node_or_null(\"AnimationTree\")\n"
            "\tif existing is AnimationTree:\n"
            "\t\texisting.anim_player = player.get_path()\n"
            "\t\treturn existing\n"
            "\tvar created := AnimationTree.new()\n"
            '\tcreated.name = "AnimationTree"\n'
            "\tcreated.anim_player = player.get_path()\n"
            "\tanimated_target.add_child(created)\n"
            "\treturn created\n"
        )

    def _render_vfx_material(self, entry: Dict[str, Any]) -> str:
        r, g, b = self._hex_to_rgb(entry["color_hex"])
        gravity = "Vector3(0, 98, 0)" if "2d" in entry["particle_mode"] else "Vector3(0, -4, 0)"
        return (
            "[gd_resource type=\"ParticleProcessMaterial\" format=3]\n\n"
            "[resource]\n"
            "emission_shape = 0\n"
            f"gravity = {gravity}\n"
            "initial_velocity_min = 24.0\n"
            "initial_velocity_max = 64.0\n"
            f"color = Color({r}, {g}, {b}, 1)\n"
        )

    def _render_vfx_scene(self, entry: Dict[str, Any]) -> str:
        is_3d = "3d" in entry["particle_mode"]
        node_type = {
            "gpu_particles_2d": "GPUParticles2D",
            "gpu_particles_3d": "GPUParticles3D",
            "cpu_particles_2d": "CPUParticles2D",
            "cpu_particles_3d": "CPUParticles3D",
        }[entry["particle_mode"]]
        root_type = "Node3D" if is_3d else "Node2D"
        return (
            "[gd_scene load_steps=2 format=3]\n\n"
            f"[ext_resource type=\"ParticleProcessMaterial\" path=\"{entry['target_material_path']}\" id=\"1\"]\n\n"
            f"[node name=\"{entry['profile_id']}\" type=\"{root_type}\"]\n"
            f"[node name=\"Particles\" type=\"{node_type}\" parent=\".\"]\n"
            f"amount = {int(entry['amount'])}\n"
            f"lifetime = {float(entry['lifetime_seconds'])}\n"
            f"one_shot = {str(bool(entry['one_shot'])).lower()}\n"
            "process_material = ExtResource(\"1\")\n"
        )

    def _render_shader_code(self, entry: Dict[str, Any]) -> str:
        params = dict(entry["shader_params"])
        uniform_lines: List[str] = []
        body_lines: List[str] = []
        for key, value in params.items():
            name = self._snake_case(key)
            uniform_lines.append(self._render_shader_uniform(name, value))
            if name.endswith("color"):
                body_lines.append(self._render_shader_color_line(entry["shader_mode"], name))
            elif isinstance(value, (int, float)):
                body_lines.append(self._render_shader_strength_line(entry["shader_mode"], name))
        if not body_lines:
            body_lines.append(self._render_shader_strength_line(entry["shader_mode"], "strength"))

        header = {"canvas_item": "shader_type canvas_item;", "spatial": "shader_type spatial;", "particles": "shader_type particles;"}[entry["shader_mode"]]
        body_name = "fragment" if entry["shader_mode"] in {"canvas_item", "spatial"} else "process"
        return (
            f"{header}\n\n"
            + "\n".join(uniform_lines)
            + f"\n\nvoid {body_name}() {{\n"
            + "\n".join(f"\t{line}" for line in body_lines)
            + "\n}\n"
        )

    def _render_shader_material(self, entry: Dict[str, Any]) -> str:
        lines = [
            "[gd_resource type=\"ShaderMaterial\" load_steps=2 format=3]",
            "",
            f"[ext_resource type=\"Shader\" path=\"{entry['target_shader_path']}\" id=\"1\"]",
            "",
            "[resource]",
            "shader = ExtResource(\"1\")",
        ]
        for key, value in dict(entry["shader_params"]).items():
            lines.append(f"shader_parameter/{self._snake_case(key)} = {self._render_material_param(value)}")
        return "\n".join(lines) + "\n"

    def _render_audio_script(self, entry: Dict[str, Any]) -> str:
        profile_id = entry["profile_id"]
        preloaded = (
            f'@export var default_stream: AudioStream = preload("{entry["audio_stream_path"]}")\n'
            if entry.get("audio_stream_path")
            else "@export var default_stream: AudioStream\n"
        )
        node_type = "AudioStreamPlayer" if entry["audio_role"] in {"bgm", "ui", "sfx"} else "AudioStreamPlayer2D"
        return (
            "extends Node\n\n"
            f"class_name {self._pascal_case(profile_id)}AudioRouter\n\n"
            f"# Auto-generated by manage_presentation_pipeline for `{profile_id}`.\n"
            f"{preloaded}"
            f'const EVENT_TO_BUS := {{"{entry["event_name"]}": "{entry["bus_name"]}"}}\n\n'
            "func play_event(event_name: String, parent: Node = self) -> Node:\n"
            "\tif not EVENT_TO_BUS.has(event_name):\n"
            '\t\tpush_warning("Unknown audio event: %s" % event_name)\n'
            "\t\treturn null\n"
            f"\tvar player := {node_type}.new()\n"
            "\tplayer.bus = EVENT_TO_BUS[event_name]\n"
            f"\tplayer.autoplay = {str(bool(entry['autoplay'])).lower()}\n"
            "\tplayer.stream = default_stream\n"
            "\tparent.add_child(player)\n"
            '\tplayer.name = "%s_player" % event_name\n'
            "\tif default_stream != null and not player.autoplay:\n"
            "\t\tplayer.play()\n"
            "\treturn player\n"
        )

    def _render_shader_uniform(self, name: str, value: Any) -> str:
        if isinstance(value, bool):
            return f"uniform bool {name} = {'true' if value else 'false'};"
        if isinstance(value, int):
            return f"uniform float {name} = {float(value):.3f};"
        if isinstance(value, float):
            return f"uniform float {name} = {value:.3f};"
        if isinstance(value, str) and value.startswith("#") and len(value) == 7:
            r, g, b = self._hex_to_rgb(value)
            return f"uniform vec4 {name} = vec4({r}, {g}, {b}, 1.0);"
        return f"uniform float {name} = 0.0;"

    def _render_shader_color_line(self, shader_mode: str, name: str) -> str:
        if shader_mode == "canvas_item":
            return f"COLOR.rgb *= {name}.rgb;"
        if shader_mode == "spatial":
            return f"ALBEDO *= {name}.rgb;"
        return f"COLOR = {name};"

    def _render_shader_strength_line(self, shader_mode: str, name: str) -> str:
        if shader_mode == "canvas_item":
            return f"UV.x += {name};"
        if shader_mode == "spatial":
            return f"ROUGHNESS = clamp({name}, 0.0, 1.0);"
        return f"VELOCITY += vec3({name});"

    def _render_material_param(self, value: Any) -> str:
        if isinstance(value, bool):
            return "true" if value else "false"
        if isinstance(value, int):
            return str(value)
        if isinstance(value, float):
            return f"{value:.3f}"
        if isinstance(value, str) and value.startswith("#") and len(value) == 7:
            r, g, b = self._hex_to_rgb(value)
            return f"Color({r}, {g}, {b}, 1)"
        return "0.0"

    def _resolve_output_path(self, project_root: Path, raw_path: Any, default_relative: str) -> Path:
        value = str(raw_path or "").strip()
        if not value:
            return (project_root / default_relative).resolve()
        if value.startswith("res://"):
            value = value.replace("res://", "", 1)
        return (project_root / value).resolve()

    def _snake_case(self, value: Any) -> str:
        text = str(value or "").strip()
        text = text.replace("\\", "/").split("/")[-1]
        stem = Path(text).stem if text else ""
        if not stem:
            return ""
        stem = stem.replace("-", "_").replace(" ", "_")
        cleaned: List[str] = []
        for index, char in enumerate(stem):
            if char.isupper() and index > 0 and cleaned[-1] != "_":
                cleaned.append("_")
            cleaned.append(char.lower() if char.isalnum() else "_")
        return "".join(cleaned).strip("_")

    def _pascal_case(self, value: str) -> str:
        parts = [part for part in self._snake_case(value).split("_") if part]
        return "".join(part.capitalize() for part in parts) or "Presentation"

    def _clean_text_list(self, value: Any) -> List[str]:
        if isinstance(value, str):
            items = value.replace("\r", "\n").replace(",", "\n").split("\n")
        elif isinstance(value, (list, tuple, set)):
            items = list(value)
        else:
            return []
        cleaned: List[str] = []
        seen = set()
        for item in items:
            text = str(item or "").strip()
            if not text or text in seen:
                continue
            cleaned.append(text)
            seen.add(text)
        return cleaned

    def _normalize_choice(self, value: Any, allowed: set[str], default: str) -> str:
        text = str(value or "").strip().lower()
        return text if text in allowed else default

    def _normalize_int(self, value: Any, default: int) -> int:
        try:
            return int(value)
        except (TypeError, ValueError):
            return default

    def _normalize_float(self, value: Any, default: float) -> float:
        try:
            return float(value)
        except (TypeError, ValueError):
            return default

    def _normalize_color(self, value: Any, issues: List[str], profile_id: str) -> str:
        text = str(value or "").strip()
        if len(text) == 7 and text.startswith("#"):
            return text.lower()
        issues.append(f"{profile_id} color_hex 必须使用 #RRGGBB")
        return "#ffffff"

    def _normalize_res_path(self, value: Any) -> str:
        text = str(value or "").strip()
        if not text:
            return ""
        if text.startswith("res://"):
            return text
        return f"res://{text.replace(chr(92), '/')}"

    def _to_res_path(self, project_root: Path, target_path: Path) -> str:
        try:
            return f"res://{target_path.resolve().relative_to(project_root).as_posix()}"
        except ValueError:
            return str(target_path.resolve())

    def _hex_to_rgb(self, value: str) -> Tuple[str, str, str]:
        clean = value.lstrip("#")
        return (
            f"{int(clean[0:2], 16) / 255:.3f}",
            f"{int(clean[2:4], 16) / 255:.3f}",
            f"{int(clean[4:6], 16) / 255:.3f}",
        )

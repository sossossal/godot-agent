"""
资源管理角色 (发布增强版)
职责: 命名审计、目录整理、自动化 Web 发布
"""

from collections import deque
import os
import re
import shutil
import time
from pathlib import Path
from typing import Dict, List, Any, Optional
from ..models import Task, TaskStatus, Artifact, Backup
from .base import BaseRole
from ..tools.struct_editor import GodotStructEditor
from ..skills.registry import SkillRegistry


class ResourceManagerRole(BaseRole):
    """资源管理角色"""
    
    def __init__(self, godot_cli, index_service: Any = None):
        super().__init__(godot_cli, index_service)
        self.struct_editor = GodotStructEditor()

    def get_description(self) -> str:
        return "资产管理员, 负责目录整理、资源命名审计和 Web 发布"
    
    def get_capabilities(self) -> List[str]:
        return [
            "整理项目",
            "文件命名审计",
            "美术资产模板管理",
            "美术资产 intake 校验",
            "美术资产变更预览",
            "美术资产导入落盘",
            "表现层模板管理",
            "动画/VFX/shader/audio profile 校验",
            "表现层 scaffold 生成",
            "数据表模板管理",
            "数据表 Schema 校验",
            "数据表变更预览",
            "数据表导入落盘",
            "数值平衡分析",
            "性能基线管理",
            "性能画像分析",
            "性能预算回归检查",
            "遥测事件字典模板",
            "遥测会话回流分析",
            "遥测事件导入",
            "资源审计修复预览",
            "资源审计一键修复",
            "场景头部审计",
            "场景节点命名审计",
            "场景引用审计",
            "资源头部审计",
            "资源引用审计",
            "二进制资源降级识别",
            "资源引用环审计",
            "导入资源审计",
            "导入配置一致性审计",
            "导入产物关系审计",
            "导出 Web 项目"
        ]
    
    def execute(self, task: Task) -> Task:
        """执行任务"""
        task.status = TaskStatus.RUNNING
        command = task.prompt
        
        try:
            if any(k in command.lower() for k in [
                "animation tree", "animationtree", "animation player", "animationplayer",
                "shader", "shadermaterial", "audio bus", "audio event", "particle profile", "presentation"
            ]) or any(k in command for k in [
                "表现层模板", "动画树", "状态动画", "着色器", "音频总线", "音频事件", "粒子模板", "粒子配置"
            ]):
                skill_bundle = SkillRegistry.get_skill_with_params("manage_presentation_pipeline", command, self.godot_cli, self.index_service)
                if skill_bundle:
                    skill, params = skill_bundle
                    context_overrides = {
                        "action": task.context.get("presentation_action"),
                        "presentation_type": task.context.get("presentation_type"),
                        "profile_id": task.context.get("presentation_profile_id"),
                        "manifest_path": task.context.get("presentation_manifest_path"),
                        "target_script_path": task.context.get("presentation_target_script_path"),
                        "target_scene_path": task.context.get("presentation_target_scene_path"),
                        "target_shader_path": task.context.get("presentation_target_shader_path"),
                        "target_material_path": task.context.get("presentation_target_material_path"),
                        "target_node_path": task.context.get("presentation_target_node_path"),
                        "animation_mode": task.context.get("presentation_animation_mode"),
                        "animation_clips": task.context.get("presentation_animation_clips"),
                        "state_machine_states": task.context.get("presentation_state_machine_states"),
                        "particle_mode": task.context.get("presentation_particle_mode"),
                        "amount": task.context.get("presentation_amount"),
                        "lifetime_seconds": task.context.get("presentation_lifetime_seconds"),
                        "one_shot": task.context.get("presentation_one_shot"),
                        "texture_path": task.context.get("presentation_texture_path"),
                        "color_hex": task.context.get("presentation_color_hex"),
                        "shader_mode": task.context.get("presentation_shader_mode"),
                        "shader_params": task.context.get("presentation_shader_params"),
                        "audio_role": task.context.get("presentation_audio_role"),
                        "event_name": task.context.get("presentation_event_name"),
                        "bus_name": task.context.get("presentation_bus_name"),
                        "audio_stream_path": task.context.get("presentation_audio_stream_path"),
                        "autoplay": task.context.get("presentation_autoplay"),
                        "acceptance_checks": task.context.get("presentation_acceptance_checks"),
                        "notes": task.context.get("presentation_notes"),
                        "entries": task.context.get("presentation_entries"),
                    }
                    params.update({key: value for key, value in context_overrides.items() if value not in (None, "", [])})
                    result = skill.execute(task, params)
                    self._apply_skill_result_contract(task, result)
                    self._merge_result_artifacts(task, result)
                    if result.success:
                        return self._success_task(task, result.message)
                    return self._error_task(task, result.message, result.error)

            if any(k in command.lower() for k in [
                "texture", "spritesheet", "material", "vfx", "icon", "blender", "gltf", "glb", "aseprite", "spine", "substance", "outsource", "vendor package"
            ]) or any(k in command for k in [
                "美术资源", "贴图", "纹理", "UI 图标", "界面资源", "精灵表", "材质资源", "特效资源", "粒子资源", "Blender 模型", "GLTF 模型", "Aseprite", "骨骼资源", "Substance", "外包交付包"
            ]):
                skill_bundle = SkillRegistry.get_skill_with_params("manage_art_asset_pipeline", command, self.godot_cli, self.index_service)
                if skill_bundle:
                    skill, params = skill_bundle
                    context_overrides = {
                        "action": task.context.get("art_asset_action"),
                        "asset_type": task.context.get("art_asset_type"),
                        "asset_id": task.context.get("art_asset_id"),
                        "source_path": task.context.get("art_asset_source_path"),
                        "target_path": task.context.get("art_asset_target_path"),
                        "manifest_path": task.context.get("art_asset_manifest_path"),
                        "source_tool": task.context.get("art_asset_source_tool"),
                        "width": task.context.get("art_asset_width"),
                        "height": task.context.get("art_asset_height"),
                        "frame_width": task.context.get("art_asset_frame_width"),
                        "frame_height": task.context.get("art_asset_frame_height"),
                        "lod_count": task.context.get("art_asset_lod_count"),
                        "texture_set": task.context.get("art_asset_texture_set"),
                        "package_version": task.context.get("art_asset_package_version"),
                        "license_name": task.context.get("art_asset_license_name"),
                        "source_dependency_paths": task.context.get("art_asset_source_dependency_paths"),
                        "target_dependency_paths": task.context.get("art_asset_target_dependency_paths"),
                        "estimated_memory_mb": task.context.get("art_asset_estimated_memory_mb"),
                        "tags": task.context.get("art_asset_tags"),
                        "notes": task.context.get("art_asset_notes"),
                        "entries": task.context.get("art_asset_entries"),
                    }
                    params.update({key: value for key, value in context_overrides.items() if value not in (None, "", [])})
                    result = skill.execute(task, params)
                    self._apply_skill_result_contract(task, result)
                    self._merge_result_artifacts(task, result)
                    if result.success:
                        return self._success_task(task, result.message)
                    return self._error_task(task, result.message, result.error)

            if any(k in command.lower() for k in [
                "performance", "fps", "draw call", "draw_call", "node count", "frame spike", "texture budget"
            ]) or any(k in command for k in [
                "性能", "性能基线", "性能画像", "帧率", "内存峰值", "draw call", "节点数", "卡顿峰值", "纹理预算"
            ]):
                skill_bundle = SkillRegistry.get_skill_with_params("manage_game_performance", command, self.godot_cli, self.index_service)
                if skill_bundle:
                    skill, params = skill_bundle
                    context_overrides = {
                        "action": task.context.get("performance_action"),
                        "scene_path": task.context.get("performance_scene_path") or task.context.get("scene_path"),
                        "baseline_path": task.context.get("performance_baseline_path"),
                        "profile_path": task.context.get("performance_profile_path"),
                        "screenshot_baseline_path": task.context.get("performance_screenshot_baseline_path"),
                        "screenshot_candidate_path": task.context.get("performance_screenshot_candidate_path"),
                        "baseline_metrics": task.context.get("performance_baseline_metrics"),
                        "profile_metrics": task.context.get("performance_profile")
                            or task.context.get("performance_profile_metrics"),
                        "budget_overrides": task.context.get("performance_budget")
                            or task.context.get("qa_gate_budget"),
                    }
                    params.update({key: value for key, value in context_overrides.items() if value not in (None, "", [])})
                    result = skill.execute(task, params)
                    self._apply_skill_result_contract(task, result)
                    self._merge_result_artifacts(task, result)
                    if result.success:
                        return self._success_task(task, result.message)
                    return self._error_task(task, result.message, result.error)

            if any(k in command.lower() for k in [
                "telemetry", "analytics", "session", "crash", "funnel", "retention", "privacy", "pii"
            ]) or any(k in command for k in [
                "遥测", "埋点", "事件字典", "会话回流", "崩溃回流", "漏斗分析", "留存分析", "隐私门禁"
            ]):
                skill_bundle = SkillRegistry.get_skill_with_params("manage_game_telemetry", command, self.godot_cli, self.index_service)
                if skill_bundle:
                    skill, params = skill_bundle
                    context_overrides = {
                        "action": task.context.get("telemetry_action"),
                        "catalog_path": task.context.get("telemetry_catalog_path"),
                        "session_path": task.context.get("telemetry_session_path"),
                        "catalog_entries": task.context.get("telemetry_catalog_entries"),
                        "events": task.context.get("telemetry_events"),
                    }
                    params.update({key: value for key, value in context_overrides.items() if value not in (None, "", [])})
                    result = skill.execute(task, params)
                    self._apply_skill_result_contract(task, result)
                    self._merge_result_artifacts(task, result)
                    if result.success:
                        return self._success_task(task, result.message)
                    return self._error_task(task, result.message, result.error)

            if any(k in command.lower() for k in [
                "remote config", "experiment", "ab test", "a/b test", "liveops"
            ]) or any(k in command for k in [
                "运营配置", "灰度实验", "实验目录", "远程配置"
            ]):
                skill_bundle = SkillRegistry.get_skill_with_params("manage_liveops_pipeline", command, self.godot_cli, self.index_service)
                if skill_bundle:
                    skill, params = skill_bundle
                    context_overrides = {
                        "action": task.context.get("liveops_action"),
                        "liveops_type": task.context.get("liveops_type"),
                        "manifest_path": task.context.get("liveops_manifest_path"),
                        "entries": task.context.get("liveops_entries"),
                    }
                    params.update({key: value for key, value in context_overrides.items() if value not in (None, "", [])})
                    result = skill.execute(task, params)
                    self._apply_skill_result_contract(task, result)
                    self._merge_result_artifacts(task, result)
                    if result.success:
                        return self._success_task(task, result.message)
                    return self._error_task(task, result.message, result.error)

            if any(k in command.lower() for k in [
                "platform delivery", "savegame schema", "multiplayer profile", "platform profile"
            ]) or any(k in command for k in [
                "平台交付", "平台发布", "存档", "存档 schema", "多人模式", "联机配置"
            ]):
                skill_bundle = SkillRegistry.get_skill_with_params("manage_platform_delivery", command, self.godot_cli, self.index_service)
                if skill_bundle:
                    skill, params = skill_bundle
                    context_overrides = {
                        "action": task.context.get("platform_delivery_action"),
                        "manifest_path": task.context.get("platform_delivery_manifest_path"),
                        "platforms": task.context.get("platform_delivery_platforms"),
                        "savegame": task.context.get("platform_delivery_savegame"),
                        "services": task.context.get("platform_delivery_services"),
                        "multiplayer": task.context.get("platform_delivery_multiplayer"),
                    }
                    params.update({key: value for key, value in context_overrides.items() if value not in (None, "", [])})
                    result = skill.execute(task, params)
                    self._apply_skill_result_contract(task, result)
                    self._merge_result_artifacts(task, result)
                    if result.success:
                        return self._success_task(task, result.message)
                    return self._error_task(task, result.message, result.error)

            if any(k in command.lower() for k in [
                "balance", "enemy", "loot", "quest", "economy"
            ]) or any(k in command for k in [
                "数值平衡", "平衡分析", "敌人强度", "掉落分析", "奖励分析", "经济分析"
            ]):
                skill_bundle = SkillRegistry.get_skill_with_params("analyze_game_balance", command, self.godot_cli, self.index_service)
                if skill_bundle:
                    skill, params = skill_bundle
                    context_overrides = {
                        "include_tables": task.context.get("balance_include_tables"),
                        "enemy_table_path": task.context.get("balance_enemy_table_path"),
                        "quest_table_path": task.context.get("balance_quest_table_path"),
                        "loot_table_path": task.context.get("balance_loot_table_path"),
                        "enemy_rows": task.context.get("balance_enemy_rows"),
                        "quest_rows": task.context.get("balance_quest_rows"),
                        "loot_rows": task.context.get("balance_loot_rows"),
                        "compare_with_baseline": task.context.get("balance_compare_with_baseline"),
                        "baseline_enemy_table_path": task.context.get("balance_baseline_enemy_table_path"),
                        "baseline_quest_table_path": task.context.get("balance_baseline_quest_table_path"),
                        "baseline_loot_table_path": task.context.get("balance_baseline_loot_table_path"),
                        "baseline_enemy_rows": task.context.get("balance_baseline_enemy_rows"),
                        "baseline_quest_rows": task.context.get("balance_baseline_quest_rows"),
                        "baseline_loot_rows": task.context.get("balance_baseline_loot_rows"),
                        "simulate_combat_balance": task.context.get("balance_simulate_combat"),
                        "player_hp": task.context.get("balance_player_hp"),
                        "player_attack": task.context.get("balance_player_attack"),
                        "player_attacks_per_second": task.context.get("balance_player_attacks_per_second"),
                        "enemy_attacks_per_second": task.context.get("balance_enemy_attacks_per_second"),
                        "min_ttk_seconds": task.context.get("balance_min_ttk_seconds"),
                        "max_ttk_seconds": task.context.get("balance_max_ttk_seconds"),
                        "max_damage_taken_ratio": task.context.get("balance_max_damage_taken_ratio"),
                        "audit_growth_curve": task.context.get("balance_audit_growth_curve"),
                        "max_enemy_power_slope_ratio": task.context.get("balance_max_enemy_power_slope_ratio"),
                        "max_reward_slope_ratio": task.context.get("balance_max_reward_slope_ratio"),
                    }
                    params.update({key: value for key, value in context_overrides.items() if value not in (None, "", [])})
                    result = skill.execute(task, params)
                    self._apply_skill_result_contract(task, result)
                    self._merge_result_artifacts(task, result)
                    if result.success:
                        return self._success_task(task, result.message)
                    return self._error_task(task, result.message, result.error)

            if any(k in command for k in ["数据表", "任务表", "对白表", "对话表", "掉落表", "本地化表", "CSV", "TSV", "JSON"]):
                skill_bundle = SkillRegistry.get_skill_with_params("manage_game_data_tables", command, self.godot_cli, self.index_service)
                if skill_bundle:
                    skill, params = skill_bundle
                    context_overrides = {
                        "action": task.context.get("data_table_action"),
                        "table_type": task.context.get("data_table_type"),
                        "table_path": task.context.get("data_table_path"),
                        "content": task.context.get("data_table_content"),
                        "rows": task.context.get("data_table_rows"),
                    }
                    params.update({key: value for key, value in context_overrides.items() if value not in (None, "", [])})
                    result = skill.execute(task, params)
                    self._apply_skill_result_contract(task, result)
                    self._merge_result_artifacts(task, result)
                    if result.success:
                        return self._success_task(task, result.message)
                    return self._error_task(task, result.message, result.error)

            # 1. 🆕 模块化技能调用: 发布/导出
            if any(k in command for k in ["发布", "导出", "分享"]):
                skill = SkillRegistry.get_skill("export_godot_project", self.godot_cli, self.index_service)
                if skill:
                    preset = "Windows Desktop" if "windows" in command.lower() or "win" in command.lower() else "Web"
                    result = skill.execute(task, {"preset_name": preset})
                    self._apply_skill_result_contract(task, result)
                    self._merge_result_artifacts(task, result)
                    
                    if result.success:
                        return self._success_task(task, result.message)
                    else:
                        return self._error_task(task, result.message, result.error)
            
            # 原有的其余逻辑 (审计、修复等逐步迁移)
            if "修复" in command and ("审计" in command or "资源" in command or "命名" in command):
                if "预览" in command or "dry-run" in command.lower():
                    return self._preview_audit_fixes(task)
                return self._apply_audit_fixes(task)
            elif "整理" in command or "初始化" in command:
                return self._organize_project(task)
            elif "检查" in command or "审计" in command:
                return self._audit_naming(task)
            else:
                return self._error_task(task, "未识别的资源指令")
        except Exception as e:
            return self._error_task(task, f"操作异常: {str(e)}", str(e))

    def _export_project(self, task: Task, preset_name: str) -> Task:
        """执行项目导出流程"""
        task.add_log(f"🚀 开始准备 {preset_name} 发布...")
        
        # 1. 确定导出目录
        is_web = "web" in preset_name.lower()
        dist_base = Path("api_server/static/dist")
        dist_base.mkdir(parents=True, exist_ok=True)
        
        timestamp = int(time.time())
        if is_web:
            export_dir = dist_base / f"web_{timestamp}"
            output_path = export_dir / "index.html"
        else:
            export_dir = dist_base / f"win_{timestamp}"
            output_path = export_dir / "game.exe"
            
        export_dir.mkdir(parents=True, exist_ok=True)
        task.add_log(f"目标目录: {export_dir}")
        
        # 2. 调用 Godot CLI 进行导出
        result = self.godot_cli.export_project(preset_name, str(output_path))
        
        # 记录构建日志 (增加对 result.data 为 None 的兼容)
        res_data = result.data or {}
        build_log = f"STDOUT:\n{res_data.get('stdout', '')}\n\nSTDERR:\n{res_data.get('stderr', '')}"
        log_artifact_path = export_dir / "build.log"
        log_artifact_path.write_text(build_log, encoding="utf-8")
        
        task.artifacts.append(Artifact(
            name=f"{preset_name} Build Log",
            path=str(log_artifact_path),
            type="build_log",
            content=build_log
        ))

        if result.success:
            task.add_log(f"✅ {preset_name} 导出成功!")
            
            # 如果是 Web 导出，提供稳定预览链接以兼容测试和前端
            if is_web:
                stable_rel_path = "/portal/dist/index.html"
                # 同时保留版本化记录作为历史
                versioned_rel_path = f"/portal/dist/web_{timestamp}/index.html"
                
                task.artifacts.append(Artifact(
                    name="Web Release (Latest)",
                    path=stable_rel_path,
                    type="release"
                ))
                task.artifacts.append(Artifact(
                    name=f"Web Release (v{timestamp})",
                    path=versioned_rel_path,
                    type="release"
                ))
                task.context["release_url"] = stable_rel_path
            else:
                task.artifacts.append(Artifact(
                    name="Windows Binary",
                    path=str(output_path),
                    type="release"
                ))
                
            return self._success_task(task, f"游戏 {preset_name} 版本已发布")
        else:
            # 导出失败处理
            task.add_log(f"❌ {preset_name} 导出失败: {result.error or '请检查构建日志'}")
            return self._error_task(task, f"导出 {preset_name} 失败", result.error)


    def _organize_project(self, task: Task) -> Task:
        base_path = self.godot_cli.project_path or "."
        for d in [
            "scenes",
            "scripts",
            "assets",
            "assets/audio",
            "assets/textures",
            "assets/textures/spritesheets",
            "assets/ui",
            "assets/models",
            "assets/characters/spine",
            "assets/materials",
            "assets/materials/substance",
            "assets/vfx",
            "assets/packages/outsource",
            "assets/manifests",
            "assets/shaders",
            "telemetry",
            "telemetry/sessions",
            "liveops",
            "scripts/presentation",
            "scripts/audio",
            "tests/baselines/performance",
            "logs/reports",
            "logs/test_artifacts",
        ]:
            os.makedirs(os.path.join(base_path, d), exist_ok=True)
        return self._success_task(task, "目录已整理")

    def _audit_naming(self, task: Task) -> Task:
        project_root = Path(self.godot_cli.project_path or ".").resolve()
        if not project_root.exists():
            return self._error_task(task, f"项目路径不存在: {project_root}")

        snapshot = self._collect_audit_snapshot(project_root)
        report_content = self._build_audit_report(
            project_root,
            snapshot["roots"],
            snapshot["checked"],
            snapshot["issues"]
        )
        report_dir = Path("logs") / "reports"
        report_dir.mkdir(parents=True, exist_ok=True)
        report_path = report_dir / f"resource_audit_{int(time.time())}.md"
        report_path.write_text(report_content, encoding="utf-8")

        task.artifacts.append(Artifact(
            name=report_path.name,
            path=str(report_path),
            type="report",
            content=report_content
        ))
        self._apply_audit_snapshot_to_task(task, snapshot, report_path=str(report_path))
        report_artifact = task.artifacts[-1]
        validation = {
            "passed": len(snapshot["issues"]) == 0,
            "issues": [issue.get("type", "audit_issue") for issue in snapshot["issues"]],
            "checks": [
                {"name": "resource_scan_completed", "status": "passed"},
                {
                    "name": "resource_issue_evaluation",
                    "status": "passed" if len(snapshot["issues"]) == 0 else "failed",
                },
            ],
        }
        self._record_synthetic_skill_result(
            task,
            skill_name="audit_godot_resources",
            skill_category="resource",
            success=True,
            message=(
                f"审计完成，发现 {len(snapshot['issues'])} 个问题"
                f"（{snapshot['severity_counts']['error']} error / {snapshot['severity_counts']['warning']} warning / {snapshot['severity_counts']['info']} info）"
                if snapshot["issues"]
                else "审计完成，未发现问题"
            ),
            params={"mode": "audit"},
            artifacts=[report_artifact],
            validation=validation,
            rollback={"available": False, "strategy": "audit_only_no_write"},
        )

        if snapshot["issues"]:
            return self._success_task(
                task,
                f"审计完成，发现 {len(snapshot['issues'])} 个问题"
                f"（{snapshot['severity_counts']['error']} error / {snapshot['severity_counts']['warning']} warning / {snapshot['severity_counts']['info']} info）"
            )
        return self._success_task(task, "审计完成，未发现问题")

    def _preview_audit_fixes(self, task: Task) -> Task:
        project_root = Path(self.godot_cli.project_path or ".").resolve()
        if not project_root.exists():
            return self._error_task(task, f"项目路径不存在: {project_root}")

        snapshot = self._collect_audit_snapshot(project_root)
        plan = self._build_audit_fix_plan(project_root, snapshot)
        report_content = self._build_fix_report(project_root, snapshot, plan, mode="preview")
        report_path = self._write_fix_report("resource_fix_preview", report_content)

        task.artifacts.append(Artifact(
            name=report_path.name,
            path=str(report_path),
            type="fix_report",
            content=report_content
        ))
        self._apply_audit_snapshot_to_task(task, snapshot)
        self._apply_fix_plan_to_task(task, plan, mode="preview", report_path=str(report_path))
        report_artifact = task.artifacts[-1]
        self._record_synthetic_skill_result(
            task,
            skill_name="preview_resource_audit_fixes",
            skill_category="resource",
            success=True,
            message=(
                f"修复预览完成，计划应用 {plan['change_count']} 处低风险修复，另有 {len(plan['skipped_issues'])} 个问题需人工处理"
                if plan["change_count"] > 0
                else f"修复预览完成，无可自动修复问题；仍有 {len(snapshot['issues'])} 个问题需要人工处理"
            ),
            params={"mode": "preview"},
            artifacts=[report_artifact],
            validation={
                "passed": len(snapshot["issues"]) == 0,
                "issues": [issue.get("type", "audit_issue") for issue in snapshot["issues"]],
                "checks": [
                    {"name": "preview_plan_generated", "status": "passed"},
                    {
                        "name": "preview_remaining_issues",
                        "status": "passed" if len(snapshot["issues"]) == 0 else "failed",
                    },
                ],
            },
            rollback={"available": False, "strategy": "preview_only_no_write"},
        )

        if plan["change_count"] == 0:
            return self._success_task(task, f"修复预览完成，无可自动修复问题；仍有 {len(snapshot['issues'])} 个问题需要人工处理")
        return self._success_task(
            task,
            f"修复预览完成，计划应用 {plan['change_count']} 处低风险修复，另有 {len(plan['skipped_issues'])} 个问题需人工处理"
        )

    def _apply_audit_fixes(self, task: Task) -> Task:
        project_root = Path(self.godot_cli.project_path or ".").resolve()
        if not project_root.exists():
            return self._error_task(task, f"项目路径不存在: {project_root}")

        before_snapshot = self._collect_audit_snapshot(project_root)
        plan = self._build_audit_fix_plan(project_root, before_snapshot)
        if plan["change_count"] == 0:
            report_content = self._build_fix_report(project_root, before_snapshot, plan, mode="apply")
            report_path = self._write_fix_report("resource_fix_apply", report_content)
            task.artifacts.append(Artifact(
                name=report_path.name,
                path=str(report_path),
                type="fix_report",
                content=report_content
            ))
            self._apply_audit_snapshot_to_task(task, before_snapshot)
            self._apply_fix_plan_to_task(task, plan, mode="apply", report_path=str(report_path))
            report_artifact = task.artifacts[-1]
            self._record_synthetic_skill_result(
                task,
                skill_name="apply_resource_audit_fixes",
                skill_category="resource",
                success=True,
                message="自动修复完成，无可应用的低风险修复",
                params={"mode": "apply"},
                artifacts=[report_artifact],
                validation={
                    "passed": len(before_snapshot["issues"]) == 0,
                    "issues": [issue.get("type", "audit_issue") for issue in before_snapshot["issues"]],
                    "checks": [
                        {"name": "fix_plan_built", "status": "passed"},
                        {"name": "apply_changes", "status": "passed"},
                    ],
                },
                rollback={"available": False, "strategy": "no_changes_applied"},
            )
            return self._success_task(task, "自动修复完成，无可应用的低风险修复")

        try:
            execution = self._execute_audit_fix_plan(task, project_root, plan)
        except Exception as exc:
            return self._error_task(task, f"自动修复失败: {exc}", str(exc))

        after_snapshot = self._collect_audit_snapshot(project_root)
        report_content = self._build_fix_report(
            project_root,
            before_snapshot,
            plan,
            mode="apply",
            execution=execution,
            after_snapshot=after_snapshot
        )
        report_path = self._write_fix_report("resource_fix_apply", report_content)
        task.artifacts.append(Artifact(
            name=report_path.name,
            path=str(report_path),
            type="fix_report",
            content=report_content
        ))
        self._apply_audit_snapshot_to_task(task, after_snapshot)
        self._apply_fix_plan_to_task(task, plan, mode="apply", report_path=str(report_path), execution=execution)
        report_artifact = task.artifacts[-1]
        self._record_synthetic_skill_result(
            task,
            skill_name="apply_resource_audit_fixes",
            skill_category="resource",
            success=True,
            message=f"自动修复完成，已应用 {execution['applied_change_count']} 处变更；剩余 {len(after_snapshot['issues'])} 个问题",
            params={"mode": "apply"},
            artifacts=[report_artifact],
            validation={
                "passed": len(after_snapshot["issues"]) == 0,
                "issues": [issue.get("type", "audit_issue") for issue in after_snapshot["issues"]],
                "checks": [
                    {"name": "fix_plan_built", "status": "passed"},
                    {"name": "apply_changes", "status": "passed"},
                    {
                        "name": "remaining_issues_evaluation",
                        "status": "passed" if len(after_snapshot["issues"]) == 0 else "failed",
                    },
                ],
            },
            rollback={
                "available": bool(task.backups),
                "strategy": "restore_files_from_backup" if task.backups else "manual_restore_required",
                "backup_paths": [backup.backup_path for backup in task.backups],
            },
        )

        return self._success_task(
            task,
            f"自动修复完成，已应用 {execution['applied_change_count']} 处变更；剩余 {len(after_snapshot['issues'])} 个问题"
        )

    def _collect_audit_snapshot(self, project_root: Path) -> Dict[str, Any]:
        roots = self._collect_scan_roots(project_root)
        text_resource_uid_by_path, text_resource_paths_by_uid = self._collect_text_resource_uid_index(project_root)

        filesystem_issues, filesystem_checked = self._scan_filesystem_names(project_root, roots)
        scene_node_issues, scene_node_checked = self._scan_scene_nodes(project_root)
        scene_header_issues, scene_header_checked = self._scan_scene_headers(project_root, text_resource_paths_by_uid)
        scene_reference_issues, scene_reference_checked = self._scan_scene_references(project_root, text_resource_uid_by_path)
        resource_header_issues, resource_header_checked = self._scan_resource_headers(project_root, text_resource_paths_by_uid)
        resource_reference_issues, resource_reference_checked = self._scan_resource_references(project_root, text_resource_uid_by_path)
        binary_resource_issues, binary_resource_checked = self._scan_binary_resources(project_root)
        resource_cycle_issues, resource_cycle_checked = self._scan_text_resource_cycles(project_root)
        import_resource_issues, import_resource_checked = self._scan_import_resources(project_root)

        issues = self._annotate_issue_severity(
            filesystem_issues
            + scene_header_issues
            + scene_node_issues
            + scene_reference_issues
            + resource_header_issues
            + resource_reference_issues
            + binary_resource_issues
            + resource_cycle_issues
            + import_resource_issues
        )
        severity_counts = self._count_issue_severity(issues)

        snapshot = {
            "roots": roots,
            "checked": (
                filesystem_checked
                + scene_node_checked
                + scene_header_checked
                + scene_reference_checked
                + resource_header_checked
                + resource_reference_checked
                + binary_resource_checked
                + resource_cycle_checked
                + import_resource_checked
            ),
            "issues": issues,
            "severity_counts": severity_counts,
            "filesystem_issues": [issue for issue in issues if issue.get("category") == "filesystem"],
            "scene_node_issues": [issue for issue in issues if issue.get("category") == "scene_nodes"],
            "scene_header_issues": [issue for issue in issues if issue.get("category") == "scene_headers"],
            "scene_reference_issues": [issue for issue in issues if issue.get("category") == "scene_references"],
            "resource_header_issues": [issue for issue in issues if issue.get("category") == "resource_headers"],
            "resource_reference_issues": [issue for issue in issues if issue.get("category") == "resource_references"],
            "binary_resource_issues": [issue for issue in issues if issue.get("category") == "binary_resources"],
            "resource_cycle_issues": [issue for issue in issues if issue.get("category") == "resource_cycles"],
            "import_resource_issues": [issue for issue in issues if issue.get("category") == "import_resources"],
            "import_config_issues": [issue for issue in issues if issue.get("category") == "import_config"],
            "import_artifact_issues": [issue for issue in issues if issue.get("category") == "import_artifacts"]
        }
        return snapshot

    def _collect_scan_roots(self, project_root: Path) -> List[Path]:
        roots = []
        for name in ("assets", "scenes", "scripts", "addons"):
            candidate = project_root / name
            if candidate.exists():
                roots.append(candidate)
        if not roots:
            roots.append(project_root)
        return roots

    def _apply_audit_snapshot_to_task(self, task: Task, snapshot: Dict[str, Any], report_path: Optional[str] = None) -> None:
        task.context.update({
            "audit_issue_count": len(snapshot["issues"]),
            "audit_file_issue_count": len(snapshot["filesystem_issues"]),
            "audit_scene_issue_count": (
                len(snapshot["scene_node_issues"])
                + len(snapshot["scene_header_issues"])
                + len(snapshot["scene_reference_issues"])
            ),
            "audit_scene_node_issue_count": len(snapshot["scene_node_issues"]),
            "audit_scene_header_issue_count": len(snapshot["scene_header_issues"]),
            "audit_scene_reference_issue_count": len(snapshot["scene_reference_issues"]),
            "audit_resource_issue_count": (
                len(snapshot["resource_header_issues"])
                + len(snapshot["resource_reference_issues"])
                + len(snapshot["binary_resource_issues"])
                + len(snapshot["resource_cycle_issues"])
            ),
            "audit_resource_header_issue_count": len(snapshot["resource_header_issues"]),
            "audit_resource_reference_issue_count": len(snapshot["resource_reference_issues"]),
            "audit_binary_resource_issue_count": len(snapshot["binary_resource_issues"]),
            "audit_cycle_issue_count": len(snapshot["resource_cycle_issues"]),
            "audit_import_issue_count": (
                len(snapshot["import_resource_issues"])
                + len(snapshot["import_config_issues"])
                + len(snapshot["import_artifact_issues"])
            ),
            "audit_import_config_issue_count": len(snapshot["import_config_issues"]),
            "audit_import_artifact_issue_count": len(snapshot["import_artifact_issues"]),
            "audit_error_count": snapshot["severity_counts"]["error"],
            "audit_warning_count": snapshot["severity_counts"]["warning"],
            "audit_info_count": snapshot["severity_counts"]["info"],
            "audit_highest_severity": self._get_highest_severity(snapshot["issues"]) if snapshot["issues"] else "info"
        })
        if report_path:
            task.context["audit_report_path"] = report_path

    def _build_audit_fix_plan(self, project_root: Path, snapshot: Dict[str, Any]) -> Dict[str, Any]:
        issue_lookup = {
            self._issue_key(issue): issue
            for issue in snapshot["issues"]
        }
        handled_issue_keys = set()
        skipped_issues = []
        renames = []
        rename_map: Dict[str, str] = {}
        source_updates: Dict[str, str] = {}
        planned_targets = set()

        for issue in snapshot["filesystem_issues"]:
            if issue.get("type") != "file":
                continue

            source_rel = Path(issue["path"]).as_posix()
            source_path = project_root / source_rel
            if not source_path.exists() or not source_path.is_file():
                continue

            target_rel = (Path(source_rel).parent / issue["suggested"]).as_posix()
            if not self._can_plan_rename(project_root, source_rel, target_rel, rename_map, planned_targets):
                continue

            renames.append({
                "kind": "file",
                "source": source_rel,
                "target": target_rel,
                "reason": f"{issue['type']} -> {issue['suggested']}"
            })
            rename_map[source_rel] = target_rel
            planned_targets.add(target_rel)
            handled_issue_keys.add(self._issue_key(issue))

            source_import_rel = f"{source_rel}.import"
            source_import_path = project_root / source_import_rel
            if source_import_path.exists():
                target_import_rel = f"{target_rel}.import"
                if self._can_plan_rename(project_root, source_import_rel, target_import_rel, rename_map, planned_targets):
                    renames.append({
                        "kind": "import_file",
                        "source": source_import_rel,
                        "target": target_import_rel,
                        "reason": "sync import sidecar with renamed source file"
                    })
                    rename_map[source_import_rel] = target_import_rel
                    planned_targets.add(target_import_rel)

                    import_file_issue = issue_lookup.get(("import_resources", source_import_rel, "import_file"))
                    if import_file_issue:
                        handled_issue_keys.add(self._issue_key(import_file_issue))

                source_updates[target_import_rel] = target_rel
                import_source_issue = issue_lookup.get(("import_resources", f"{source_import_rel}::source_file", "import_source"))
                if import_source_issue:
                    handled_issue_keys.add(self._issue_key(import_source_issue))
                mismatch_issue = issue_lookup.get(("import_config", f"{source_import_rel}::source_file", "source_file_mismatch"))
                if mismatch_issue:
                    handled_issue_keys.add(self._issue_key(mismatch_issue))

                cache_plan = self._build_import_cache_renames(
                    project_root,
                    source_import_rel,
                    rename_map.get(source_import_rel, source_import_rel),
                    Path(source_rel).name,
                    Path(target_rel).name,
                    rename_map,
                    planned_targets
                )
                renames.extend(cache_plan)

        for issue in snapshot["import_resource_issues"]:
            if issue.get("type") != "import_file":
                continue
            if self._issue_key(issue) in handled_issue_keys:
                continue

            source_rel = Path(issue["path"]).as_posix()
            source_path = project_root / source_rel
            if not source_path.exists() or not source_path.is_file():
                continue

            target_rel = (Path(source_rel).parent / f"{issue['suggested']}.import").as_posix()
            logical_target_rel = target_rel[:-7]
            if not (
                (project_root / logical_target_rel).exists()
                or logical_target_rel in rename_map.values()
            ):
                skipped_issues.append(self._skip_issue(issue, "matching source asset does not exist"))
                continue

            if not self._can_plan_rename(project_root, source_rel, target_rel, rename_map, planned_targets):
                skipped_issues.append(self._skip_issue(issue, "target import file already exists"))
                continue

            renames.append({
                "kind": "import_file",
                "source": source_rel,
                "target": target_rel,
                "reason": f"import_file -> {issue['suggested']}.import"
            })
            rename_map[source_rel] = target_rel
            planned_targets.add(target_rel)
            handled_issue_keys.add(self._issue_key(issue))
            source_updates[target_rel] = logical_target_rel

        for issue in snapshot["import_config_issues"]:
            if issue.get("type") != "source_file_mismatch":
                continue

            source_rel = Path(issue["path"].split("::", 1)[0]).as_posix()
            target_rel = rename_map.get(source_rel, source_rel)
            expected_source_rel = target_rel[:-7]
            expected_source_path = project_root / expected_source_rel
            if not expected_source_path.exists() and expected_source_rel not in rename_map.values():
                skipped_issues.append(self._skip_issue(issue, "expected logical source file does not exist"))
                continue

            source_updates[target_rel] = expected_source_rel
            handled_issue_keys.add(self._issue_key(issue))

        for issue in snapshot["import_resource_issues"]:
            if issue.get("type") != "import_source":
                continue
            source_rel = Path(issue["path"].split("::", 1)[0]).as_posix()
            source_file_rel = rename_map.get(source_rel[:-7], source_rel[:-7])
            target_import_rel = rename_map.get(source_rel, source_rel)
            if source_file_rel != source_rel[:-7] or target_import_rel in source_updates:
                handled_issue_keys.add(self._issue_key(issue))

        for issue in snapshot["scene_node_issues"]:
            path_parts = issue["path"].split("::", 1)
            if len(path_parts) != 2:
                continue
            scene_rel = path_parts[0]
            old_name = path_parts[1]
            new_name = issue["suggested"]

            renames.append({
                "kind": "scene_node",
                "source": scene_rel, # 这里 source 指向场景文件
                "target": new_name,
                "old_name": old_name,
                "reason": f"node {old_name} -> {new_name}"
            })
            handled_issue_keys.add(self._issue_key(issue))

        for issue in snapshot["issues"]:
            if self._issue_key(issue) in handled_issue_keys:
                continue
            if issue.get("category") == "binary_resources":
                skipped_issues.append(self._skip_issue(issue, "informational only"))
                continue
            if issue.get("type") == "directory":
                skipped_issues.append(self._skip_issue(issue, "rename requires complex path refactor"))
                continue
            skipped_issues.append(self._skip_issue(issue, "requires manual review"))

        reference_renames = {
            rename["source"]: rename["target"]
            for rename in renames
            if rename["kind"] in {"file", "import_cache"}
        }

        content_update_targets = self._collect_fix_content_targets(project_root, reference_renames, source_updates, rename_map)
        return {
            "renames": renames,
            "reference_renames": reference_renames,
            "source_updates": source_updates,
            "content_update_targets": content_update_targets,
            "skipped_issues": skipped_issues,
            "change_count": len(renames) + len(content_update_targets)
        }

    def _collect_fix_content_targets(
        self,
        project_root: Path,
        reference_renames: Dict[str, str],
        source_updates: Dict[str, str],
        rename_map: Dict[str, str]
    ) -> List[Dict[str, str]]:
        targets = {}
        replacement_pairs = [
            (f"res://{source}", f"res://{target}")
            for source, target in reference_renames.items()
        ]

        for file_path in self._iter_text_reference_files(project_root):
            relative_path = file_path.relative_to(project_root).as_posix()
            display_path = rename_map.get(relative_path, relative_path)
            try:
                content = file_path.read_text(encoding="utf-8")
            except Exception:
                continue

            changes = []
            for old_value, new_value in replacement_pairs:
                if old_value in content:
                    changes.append(f"{old_value} -> {new_value}")

            if relative_path in source_updates or display_path in source_updates:
                expected_source = source_updates.get(display_path, source_updates.get(relative_path))
                if expected_source:
                    changes.append(f'source_file -> res://{expected_source}')

            if changes:
                targets[display_path] = {
                    "path": display_path,
                    "detail": "; ".join(sorted(set(changes)))
                }

        for relative_path, expected_source in source_updates.items():
            targets.setdefault(relative_path, {
                "path": relative_path,
                "detail": f'source_file -> res://{expected_source}'
            })

        return sorted(targets.values(), key=lambda item: item["path"])

    def _build_import_cache_renames(
        self,
        project_root: Path,
        source_import_rel: str,
        target_import_rel: str,
        old_logical_name: str,
        new_logical_name: str,
        rename_map: Dict[str, str],
        planned_targets: set[str]
    ) -> List[Dict[str, str]]:
        renames = []
        import_file_path = project_root / source_import_rel
        try:
            content = import_file_path.read_text(encoding="utf-8")
        except Exception:
            return renames

        dest_pattern = re.compile(r'^dest_files=(.+)$', re.MULTILINE)
        for dest_match in dest_pattern.finditer(content):
            for dest_path in self._parse_string_list(dest_match.group(1)):
                normalized = self._normalize_res_path(dest_path)
                if normalized is None:
                    continue
                source_cache_rel = normalized.as_posix()
                source_cache_name = Path(source_cache_rel).name
                if not source_cache_name.startswith(old_logical_name):
                    continue

                target_cache_name = f"{new_logical_name}{source_cache_name[len(old_logical_name):]}"
                target_cache_rel = (Path(source_cache_rel).parent / target_cache_name).as_posix()
                if not self._can_plan_rename(project_root, source_cache_rel, target_cache_rel, rename_map, planned_targets):
                    continue

                renames.append({
                    "kind": "import_cache",
                    "source": source_cache_rel,
                    "target": target_cache_rel,
                    "reason": f"sync imported cache with {target_import_rel}"
                })
                rename_map[source_cache_rel] = target_cache_rel
                planned_targets.add(target_cache_rel)

        return renames

    def _execute_audit_fix_plan(self, task: Task, project_root: Path, plan: Dict[str, Any]) -> Dict[str, Any]:
        import difflib
        backed_up = set()
        applied_renames = []
        modified_files = []
        diffs = []

        # 1. 执行物理重命名 (文件、导入、缓存)
        rename_order = {"file": 0, "import_file": 1, "import_cache": 2}
        for rename in sorted(plan["renames"], key=lambda item: (rename_order.get(item["kind"], 9), -len(item["source"]))):
            if rename["kind"] == "scene_node":
                continue # 节点重命名在第 2 步处理

            source_path = project_root / rename["source"]
            target_path = project_root / rename["target"]
            if not source_path.exists():
                continue

            self._backup_file(task, project_root, source_path, backed_up)
            self._rename_path(source_path, target_path)
            
            task.artifacts.append(Artifact(
                name=target_path.name,
                path=f"res://{rename['target']}",
                type="rename_target",
                metadata={"original_source": rename["source"]}
            ))
            applied_renames.append(rename)

        # 2. 执行结构化内容更新 (节点重命名 + 引用更新)
        ref_replacements = {f"res://{s}": f"res://{t}" for s, t in plan["reference_renames"].items()}
        node_renames_by_scene = {}
        for rename in plan["renames"]:
            if rename["kind"] == "scene_node":
                node_renames_by_scene.setdefault(rename["source"], []).append(rename)

        for file_path in self._iter_text_reference_files(project_root):
            relative_path = file_path.relative_to(project_root).as_posix()
            original_content = self._read_text_file(file_path)
            if original_content is None:
                continue

            working_content = original_content
            self.struct_editor.load(working_content)
            structured_changed = False
             
            if relative_path in node_renames_by_scene:
                for nr in node_renames_by_scene[relative_path]:
                    if self.struct_editor.rename_node(nr["old_name"], nr["target"]) > 0:
                        structured_changed = True
                        applied_renames.append(nr)

            for old_res, new_res in ref_replacements.items():
                if self.struct_editor.update_ext_resource_path(old_res, new_res) > 0:
                    structured_changed = True

            if structured_changed:
                working_content = self.struct_editor.serialize()

            text_changed = False
            for old_res, new_res in ref_replacements.items():
                if old_res in working_content:
                    working_content = working_content.replace(old_res, new_res)
                    text_changed = True

            expected_source = plan["source_updates"].get(relative_path)
            if expected_source:
                updated_source_content, replacements = re.subn(
                    r'(source_file=")[^"]+(")',
                    rf'\1res://{expected_source}\2',
                    working_content
                )
                if replacements > 0:
                    working_content = updated_source_content
                    text_changed = True

            if structured_changed or text_changed:
                updated_content = working_content

                # 🧠 Stage 4: 记录差异
                file_diff = list(difflib.unified_diff(
                    original_content.splitlines(),
                    updated_content.splitlines(),
                    fromfile=f"a/{relative_path}",
                    tofile=f"b/{relative_path}",
                    lineterm=""
                ))
                if file_diff:
                    diffs.append("\n".join(file_diff))

                self._backup_file(task, project_root, file_path, backed_up)
                file_path.write_text(updated_content, encoding="utf-8")
                modified_files.append(relative_path)

        # 如果产生了大范围改动，在日志中提醒
        if len(modified_files) > 1:
            task.add_log(f"📝 结构化修改了 {len(modified_files)} 个文件，已生成差异报告。")
            if diffs:
                diff_content = "\n\n".join(diffs)
                task.artifacts.append(Artifact(
                    name="Refactor Diff",
                    path="internal://diff.patch",
                    type="log",
                    content=diff_content
                ))

        return {
            "applied_renames": applied_renames,
            "modified_files": sorted(set(modified_files)),
            "applied_change_count": len(applied_renames) + len(set(modified_files))
        }

    def _apply_node_rename_to_content(self, content: str, old_name: str, new_name: str) -> str:
        """结构化重命名 (降级适配器)"""
        self.struct_editor.load(content)
        if self.struct_editor.rename_node(old_name, new_name) > 0:
            return self.struct_editor.serialize()
        return content


    def _backup_file(self, task: Task, project_root: Path, file_path: Path, backed_up: set[str]) -> None:
        resolved = str(file_path.resolve())
        if resolved in backed_up or not file_path.exists() or not file_path.is_file():
            return

        relative_name = file_path.relative_to(project_root).as_posix().replace("/", "__")
        backup_dir = Path("logs") / "backups"
        backup_dir.mkdir(parents=True, exist_ok=True)
        backup_path = backup_dir / f"{relative_name}.{int(time.time() * 1000)}.bak"
        shutil.copy2(file_path, backup_path)
        task.backups.append(Backup(original_path=str(file_path), backup_path=str(backup_path)))
        backed_up.add(resolved)

    def _rename_path(self, source_path: Path, target_path: Path) -> None:
        target_path.parent.mkdir(parents=True, exist_ok=True)
        if source_path.resolve() == target_path.resolve():
            return

        if str(source_path).lower() == str(target_path).lower():
            temp_path = source_path.with_name(f"{source_path.name}.codex_tmp_{int(time.time() * 1000)}")
            shutil.move(str(source_path), str(temp_path))
            shutil.move(str(temp_path), str(target_path))
            return

        shutil.move(str(source_path), str(target_path))

    def _can_plan_rename(
        self,
        project_root: Path,
        source_rel: str,
        target_rel: str,
        rename_map: Dict[str, str],
        planned_targets: set[str]
    ) -> bool:
        if source_rel == target_rel or source_rel in rename_map:
            return False
        if target_rel in planned_targets:
            return False

        target_path = project_root / target_rel
        source_path = project_root / source_rel
        if target_path.exists() and str(target_path).lower() != str(source_path).lower():
            return False
        return True

    def _iter_text_reference_files(self, project_root: Path):
        yielded = set()
        project_file = project_root / "project.godot"
        if project_file.exists():
            yielded.add(project_file.resolve())
            yield project_file

        for pattern in ("*.tscn", "*.tres", "*.res", "*.gd", "*.import"):
            for file_path in project_root.rglob(pattern):
                if self._should_skip(file_path):
                    continue
                resolved = file_path.resolve()
                if resolved in yielded:
                    continue
                yielded.add(resolved)
                yield file_path

    def _read_text_file(self, file_path: Path) -> Optional[str]:
        try:
            return file_path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            return None
        except Exception:
            return None

    def _issue_key(self, issue: Dict[str, str]) -> tuple[str, str, str]:
        return issue.get("category", ""), issue.get("path", ""), issue.get("type", "")

    def _skip_issue(self, issue: Dict[str, str], reason: str) -> Dict[str, str]:
        return {
            "path": issue.get("path", ""),
            "type": issue.get("type", ""),
            "severity": issue.get("severity", "warning"),
            "reason": reason
        }

    def _apply_fix_plan_to_task(
        self,
        task: Task,
        plan: Dict[str, Any],
        mode: str,
        report_path: str,
        execution: Optional[Dict[str, Any]] = None
    ) -> None:
        task.context.update({
            "audit_fix_mode": mode,
            "audit_fix_report_path": report_path,
            "audit_fix_rename_count": len(plan["renames"]),
            "audit_fix_content_update_count": len(plan["content_update_targets"]),
            "audit_fix_skip_count": len(plan["skipped_issues"]),
            "audit_fix_change_count": plan["change_count"],
            "audit_fixable_issue_count": len(plan["renames"]) + len(plan["source_updates"])
        })
        if execution:
            task.context["audit_fix_applied_count"] = execution["applied_change_count"]

    def _write_fix_report(self, prefix: str, report_content: str) -> Path:
        report_dir = Path("logs") / "reports"
        report_dir.mkdir(parents=True, exist_ok=True)
        report_path = report_dir / f"{prefix}_{int(time.time())}.md"
        report_path.write_text(report_content, encoding="utf-8")
        return report_path

    def _build_fix_report(
        self,
        project_root: Path,
        snapshot: Dict[str, Any],
        plan: Dict[str, Any],
        mode: str,
        execution: Optional[Dict[str, Any]] = None,
        after_snapshot: Optional[Dict[str, Any]] = None
    ) -> str:
        lines = [
            f"# Resource Auto-Fix {'Preview' if mode == 'preview' else 'Execution'}",
            "",
            f"- Project Root: `{project_root}`",
            f"- Issues Before: {len(snapshot['issues'])}",
            f"- Planned Renames: {len(plan['renames'])}",
            f"- Planned Content Updates: {len(plan['content_update_targets'])}",
            f"- Manual Review Needed: {len(plan['skipped_issues'])}",
        ]

        if execution:
            lines.append(f"- Applied Changes: {execution['applied_change_count']}")
        if after_snapshot:
            lines.append(f"- Issues After: {len(after_snapshot['issues'])}")
        lines.append("")

        if plan["renames"]:
            lines.extend(["## Planned Renames", ""])
            for rename in plan["renames"]:
                lines.append(f"- `{rename['source']}` -> `{rename['target']}` ({rename['kind']})")
            lines.append("")

        if plan["content_update_targets"]:
            lines.extend(["## Planned Content Updates", ""])
            for target in plan["content_update_targets"]:
                lines.append(f"- `{target['path']}` - {target['detail']}")
            lines.append("")

        if execution and execution.get("modified_files"):
            lines.extend(["## Modified Files", ""])
            for relative_path in execution["modified_files"]:
                lines.append(f"- `{relative_path}`")
            lines.append("")

        if plan["skipped_issues"]:
            lines.extend(["## Manual Review", ""])
            for skipped in plan["skipped_issues"]:
                lines.append(
                    f"- [{skipped['severity'].upper()}] `{skipped['path']}` ({skipped['type']}) - {skipped['reason']}"
                )
            lines.append("")

        if not plan["renames"] and not plan["content_update_targets"]:
            lines.append("No low-risk auto-fixes were planned.")

        return "\n".join(lines) + "\n"

    def _scan_filesystem_names(self, project_root: Path, roots: List[Path]) -> tuple[list[Dict[str, str]], int]:
        issues = []
        checked = 0

        for root in roots:
            for item in root.rglob("*"):
                if self._should_skip(item) or item.suffix == ".import":
                    continue

                checked += 1
                target_name = item.stem if item.is_file() else item.name
                if self._is_snake_case(target_name):
                    continue

                suggested = self._to_snake_case(target_name)
                if item.is_file() and item.suffix:
                    suggested = f"{suggested}{item.suffix.lower()}"

                issues.append({
                    "category": "filesystem",
                    "path": str(item.relative_to(project_root)),
                    "type": "file" if item.is_file() else "directory",
                    "suggested": suggested
                })

        return issues, checked

    def _scan_scene_nodes(self, project_root: Path) -> tuple[list[Dict[str, str]], int]:
        issues = []
        checked = 0
        node_pattern = re.compile(r'^\[node\s+name="([^"]+)"')

        for scene_file in project_root.rglob("*.tscn"):
            if self._should_skip(scene_file):
                continue

            try:
                content = scene_file.read_text(encoding="utf-8")
            except Exception:
                continue

            for line in content.splitlines():
                match = node_pattern.match(line.strip())
                if not match:
                    continue

                checked += 1
                node_name = match.group(1)
                if self._is_snake_case(node_name):
                    continue

                issues.append({
                    "category": "scene_nodes",
                    "path": f"{scene_file.relative_to(project_root)}::{node_name}",
                    "type": "scene_node",
                    "suggested": self._to_snake_case(node_name)
                })

        return issues, checked

    def _collect_text_resource_uid_index(self, project_root: Path) -> tuple[Dict[str, str], Dict[str, List[str]]]:
        resource_uid_by_path: Dict[str, str] = {}
        resource_paths_by_uid: Dict[str, List[str]] = {}

        for pattern in ("*.tscn", "*.tres", "*.res"):
            for resource_file in project_root.rglob(pattern):
                if self._should_skip(resource_file):
                    continue

                try:
                    lines = resource_file.read_text(encoding="utf-8").splitlines()
                except Exception:
                    continue

                header_line = next((line.strip() for line in lines if line.strip()), "")
                if not (
                    header_line.startswith("[gd_scene") or
                    header_line.startswith("[gd_resource")
                ):
                    continue

                uid = self._parse_section_attributes(header_line).get("uid", "")
                if not uid:
                    continue

                relative_path = resource_file.relative_to(project_root).as_posix()
                resource_uid_by_path[relative_path] = uid
                resource_paths_by_uid.setdefault(uid, []).append(relative_path)

        return resource_uid_by_path, resource_paths_by_uid

    def _scan_scene_headers(self, project_root: Path, text_resource_paths_by_uid: Dict[str, List[str]]) -> tuple[list[Dict[str, str]], int]:
        issues = []
        checked = 0
        scene_paths_with_uid: List[tuple[str, str]] = []

        for scene_file in project_root.rglob("*.tscn"):
            if self._should_skip(scene_file):
                continue

            try:
                lines = scene_file.read_text(encoding="utf-8").splitlines()
            except Exception:
                continue

            header_line = next((line.strip() for line in lines if line.strip()), "")
            checked += 1
            if not header_line.startswith("[gd_scene"):
                issues.append({
                    "category": "scene_headers",
                    "path": str(scene_file.relative_to(project_root)),
                    "type": "invalid_scene_header",
                    "detail": "missing [gd_scene ...] header"
                })
                continue

            attrs = self._parse_section_attributes(header_line)
            format_value = attrs.get("format", "")
            load_steps = attrs.get("load_steps", "")
            uid = attrs.get("uid", "")
            declared_resources = sum(
                1 for line in lines
                if line.strip().startswith("[ext_resource") or line.strip().startswith("[sub_resource")
            )

            checked += 1
            if not format_value or not format_value.isdigit():
                issues.append({
                    "category": "scene_headers",
                    "path": f"{scene_file.relative_to(project_root)}::format",
                    "type": "invalid_scene_format",
                    "detail": "missing or invalid scene format"
                })

            checked += 1
            if not uid:
                issues.append({
                    "category": "scene_headers",
                    "path": f"{scene_file.relative_to(project_root)}::uid",
                    "type": "missing_scene_uid",
                    "detail": "missing scene uid"
                })
            elif not uid.startswith("uid://"):
                issues.append({
                    "category": "scene_headers",
                    "path": f"{scene_file.relative_to(project_root)}::uid",
                    "type": "invalid_scene_uid",
                    "detail": "scene uid should start with uid://"
                })
            else:
                scene_paths_with_uid.append((scene_file.relative_to(project_root).as_posix(), uid))

            checked += 1
            if not load_steps:
                issues.append({
                    "category": "scene_headers",
                    "path": f"{scene_file.relative_to(project_root)}::load_steps",
                    "type": "missing_load_steps",
                    "detail": "missing load_steps"
                })
            elif not load_steps.isdigit() or int(load_steps) <= 0:
                issues.append({
                    "category": "scene_headers",
                    "path": f"{scene_file.relative_to(project_root)}::load_steps",
                    "type": "invalid_load_steps",
                    "detail": "load_steps should be a positive integer"
                })
            else:
                checked += 1
                minimum_steps = declared_resources + 1 if declared_resources else 1
                if int(load_steps) < minimum_steps:
                    issues.append({
                        "category": "scene_headers",
                        "path": f"{scene_file.relative_to(project_root)}::load_steps",
                        "type": "load_steps_too_small",
                        "detail": f"expected at least {minimum_steps}"
                    })

        for relative_path, uid in scene_paths_with_uid:
            duplicates = text_resource_paths_by_uid.get(uid, [])
            checked += 1
            if len(duplicates) > 1:
                sibling_paths = ", ".join(f"`{path}`" for path in duplicates if path != relative_path)
                issues.append({
                    "category": "scene_headers",
                    "path": f"{relative_path}::uid",
                    "type": "duplicate_scene_uid",
                    "detail": f"shared with {sibling_paths}" if sibling_paths else "duplicate scene uid"
                })

        return issues, checked

    def _scan_scene_references(self, project_root: Path, text_resource_uid_by_path: Dict[str, str]) -> tuple[list[Dict[str, str]], int]:
        return self._scan_text_resource_references(
            project_root,
            ("*.tscn",),
            "scene_references",
            text_resource_uid_by_path
        )

    def _scan_resource_references(self, project_root: Path, text_resource_uid_by_path: Dict[str, str]) -> tuple[list[Dict[str, str]], int]:
        return self._scan_text_resource_references(
            project_root,
            ("*.tres", "*.res"),
            "resource_references",
            text_resource_uid_by_path
        )

    def _scan_text_resource_references(
        self,
        project_root: Path,
        patterns: tuple[str, ...],
        category: str,
        text_resource_uid_by_path: Dict[str, str]
    ) -> tuple[list[Dict[str, str]], int]:
        issues = []
        checked = 0
        ext_resource_pattern = re.compile(r'^\[ext_resource\b')
        sub_resource_pattern = re.compile(r'^\[sub_resource\b')
        ext_ref_pattern = re.compile(r'ExtResource\("([^"]+)"\)')
        sub_ref_pattern = re.compile(r'SubResource\("([^"]+)"\)')

        for pattern in patterns:
            for resource_file in project_root.rglob(pattern):
                if self._should_skip(resource_file):
                    continue

                try:
                    lines = resource_file.read_text(encoding="utf-8").splitlines()
                except Exception:
                    continue

                declared_ext_ids: set[str] = set()
                declared_sub_ids: set[str] = set()
                ext_paths_by_value: Dict[str, str] = {}
                relative_path = resource_file.relative_to(project_root)

                for line_number, raw_line in enumerate(lines, start=1):
                    line = raw_line.strip()
                    if ext_resource_pattern.match(line):
                        checked += 1
                        attrs = self._parse_section_attributes(line)
                        ext_id = attrs.get("id", "")
                        ext_type = attrs.get("type", "")
                        ext_path = attrs.get("path", "")
                        ext_uid = attrs.get("uid", "")

                        if not ext_id:
                            issues.append({
                                "category": category,
                                "path": f"{relative_path}:line{line_number}",
                                "type": "ext_resource_missing_id",
                                "detail": "missing ext_resource id"
                            })
                        elif ext_id in declared_ext_ids:
                            issues.append({
                                "category": category,
                                "path": f"{relative_path}::ext_resource[{ext_id}]",
                                "type": "duplicate_ext_resource_id",
                                "detail": "duplicate ext_resource id"
                            })
                        else:
                            declared_ext_ids.add(ext_id)

                        checked += 1
                        if not ext_type:
                            issues.append({
                                "category": category,
                                "path": f"{relative_path}::ext_resource[{ext_id or '?'}]",
                                "type": "ext_resource_missing_type",
                                "detail": "missing ext_resource type"
                            })

                        checked += 1
                        if not ext_path:
                            issues.append({
                                "category": category,
                                "path": f"{relative_path}::ext_resource[{ext_id or '?'}]",
                                "type": "ext_resource_missing_path",
                                "detail": "missing ext_resource path"
                            })
                        else:
                            normalized_path = self._normalize_res_path(ext_path)
                            if normalized_path is None:
                                issues.append({
                                    "category": category,
                                    "path": f"{relative_path}::ext_resource[{ext_id or '?'}]",
                                    "type": "ext_resource_invalid_path",
                                    "detail": "ext_resource path should start with res://"
                                })
                            else:
                                normalized_path_str = normalized_path.as_posix()

                                checked += 1
                                if normalized_path_str in ext_paths_by_value:
                                    issues.append({
                                        "category": category,
                                        "path": f"{relative_path}::ext_resource[{ext_id or '?'}]",
                                        "type": "duplicate_ext_resource_path",
                                        "detail": f"duplicate path with id `{ext_paths_by_value[normalized_path_str]}`"
                                    })
                                else:
                                    ext_paths_by_value[normalized_path_str] = ext_id or f"line{line_number}"

                                checked += 1
                                if not (project_root / normalized_path).exists():
                                    issues.append({
                                        "category": category,
                                        "path": f"{relative_path}::ext_resource[{ext_id or '?'}]",
                                        "type": "ext_resource_missing_target",
                                        "detail": f"missing target `{normalized_path_str}`"
                                    })

                                if ext_uid:
                                    checked += 1
                                    if not ext_uid.startswith("uid://"):
                                        issues.append({
                                            "category": category,
                                            "path": f"{relative_path}::ext_resource[{ext_id or '?'}]",
                                            "type": "invalid_ext_resource_uid",
                                            "detail": "ext_resource uid should start with uid://"
                                        })
                                    elif normalized_path.suffix.lower() in {".tscn", ".tres", ".res"}:
                                        checked += 1
                                        target_uid = text_resource_uid_by_path.get(normalized_path_str)
                                        if target_uid and target_uid != ext_uid:
                                            issues.append({
                                                "category": category,
                                                "path": f"{relative_path}::ext_resource[{ext_id or '?'}]",
                                                "type": "ext_resource_uid_mismatch",
                                                "detail": f"expected `{target_uid}`"
                                            })
                                        elif not target_uid and (project_root / normalized_path).exists():
                                            issues.append({
                                                "category": category,
                                                "path": f"{relative_path}::ext_resource[{ext_id or '?'}]",
                                                "type": "ext_resource_uid_unresolved",
                                                "detail": "target resource does not expose a valid uid"
                                            })

                    elif sub_resource_pattern.match(line):
                        checked += 1
                        attrs = self._parse_section_attributes(line)
                        sub_id = attrs.get("id", "")
                        sub_type = attrs.get("type", "")

                        if not sub_id:
                            issues.append({
                                "category": category,
                                "path": f"{relative_path}:line{line_number}",
                                "type": "sub_resource_missing_id",
                                "detail": "missing sub_resource id"
                            })
                        elif sub_id in declared_sub_ids:
                            issues.append({
                                "category": category,
                                "path": f"{relative_path}::sub_resource[{sub_id}]",
                                "type": "duplicate_sub_resource_id",
                                "detail": "duplicate sub_resource id"
                            })
                        else:
                            declared_sub_ids.add(sub_id)

                        checked += 1
                        if not sub_type:
                            issues.append({
                                "category": category,
                                "path": f"{relative_path}::sub_resource[{sub_id or '?'}]",
                                "type": "sub_resource_missing_type",
                                "detail": "missing sub_resource type"
                            })

                for line_number, raw_line in enumerate(lines, start=1):
                    for match in ext_ref_pattern.finditer(raw_line):
                        checked += 1
                        ext_id = match.group(1)
                        if ext_id not in declared_ext_ids:
                            issues.append({
                                "category": category,
                                "path": f"{relative_path}:line{line_number}",
                                "type": "unknown_ext_resource_reference",
                                "detail": f'ExtResource("{ext_id}") is not declared'
                            })

                    for match in sub_ref_pattern.finditer(raw_line):
                        checked += 1
                        sub_id = match.group(1)
                        if sub_id not in declared_sub_ids:
                            issues.append({
                                "category": category,
                                "path": f"{relative_path}:line{line_number}",
                                "type": "unknown_sub_resource_reference",
                                "detail": f'SubResource("{sub_id}") is not declared'
                            })

        return issues, checked

    def _scan_resource_headers(self, project_root: Path, text_resource_paths_by_uid: Dict[str, List[str]]) -> tuple[list[Dict[str, str]], int]:
        issues = []
        checked = 0
        resource_paths_with_uid: List[tuple[str, str]] = []

        for pattern in ("*.tres", "*.res"):
            for resource_file in project_root.rglob(pattern):
                if self._should_skip(resource_file):
                    continue

                try:
                    lines = resource_file.read_text(encoding="utf-8").splitlines()
                except Exception:
                    continue

                header_line = next((line.strip() for line in lines if line.strip()), "")
                checked += 1
                if not header_line.startswith("[gd_resource"):
                    issues.append({
                        "category": "resource_headers",
                        "path": str(resource_file.relative_to(project_root)),
                        "type": "invalid_resource_header",
                        "detail": "missing [gd_resource ...] header"
                    })
                    continue

                attrs = self._parse_section_attributes(header_line)
                resource_type = attrs.get("type", "")
                format_value = attrs.get("format", "")
                uid = attrs.get("uid", "")
                load_steps = attrs.get("load_steps", "")
                declared_resources = sum(
                    1 for line in lines
                    if line.strip().startswith("[ext_resource") or line.strip().startswith("[sub_resource")
                )

                checked += 1
                if not resource_type:
                    issues.append({
                        "category": "resource_headers",
                        "path": f"{resource_file.relative_to(project_root)}::type",
                        "type": "missing_resource_type",
                        "detail": "missing resource type"
                    })

                checked += 1
                if not format_value or not format_value.isdigit():
                    issues.append({
                        "category": "resource_headers",
                        "path": f"{resource_file.relative_to(project_root)}::format",
                        "type": "invalid_resource_format",
                        "detail": "missing or invalid resource format"
                    })

                checked += 1
                if not uid:
                    issues.append({
                        "category": "resource_headers",
                        "path": f"{resource_file.relative_to(project_root)}::uid",
                        "type": "missing_resource_uid",
                        "detail": "missing resource uid"
                    })
                elif not uid.startswith("uid://"):
                    issues.append({
                        "category": "resource_headers",
                        "path": f"{resource_file.relative_to(project_root)}::uid",
                        "type": "invalid_resource_uid",
                        "detail": "resource uid should start with uid://"
                    })
                else:
                    resource_paths_with_uid.append((resource_file.relative_to(project_root).as_posix(), uid))

                if load_steps:
                    checked += 1
                    if not load_steps.isdigit() or int(load_steps) <= 0:
                        issues.append({
                            "category": "resource_headers",
                            "path": f"{resource_file.relative_to(project_root)}::load_steps",
                            "type": "invalid_resource_load_steps",
                            "detail": "load_steps should be a positive integer"
                        })
                    else:
                        checked += 1
                        minimum_steps = declared_resources + 1 if declared_resources else 1
                        if int(load_steps) < minimum_steps:
                            issues.append({
                                "category": "resource_headers",
                                "path": f"{resource_file.relative_to(project_root)}::load_steps",
                                "type": "resource_load_steps_too_small",
                                "detail": f"expected at least {minimum_steps}"
                            })

        for relative_path, uid in resource_paths_with_uid:
            duplicates = text_resource_paths_by_uid.get(uid, [])
            checked += 1
            if len(duplicates) > 1:
                sibling_paths = ", ".join(f"`{path}`" for path in duplicates if path != relative_path)
                issues.append({
                    "category": "resource_headers",
                    "path": f"{relative_path}::uid",
                    "type": "duplicate_resource_uid",
                    "detail": f"shared with {sibling_paths}" if sibling_paths else "duplicate resource uid"
                })

        return issues, checked

    def _scan_binary_resources(self, project_root: Path) -> tuple[list[Dict[str, str]], int]:
        issues = []
        checked = 0

        for resource_file in project_root.rglob("*.res"):
            if self._should_skip(resource_file):
                continue

            checked += 1
            try:
                raw = resource_file.read_bytes()
            except Exception:
                continue

            if not raw:
                continue

            binary_signature = raw.startswith((b"RSRC", b"RSCC")) or b"\x00" in raw[:256]
            if binary_signature:
                issues.append({
                    "category": "binary_resources",
                    "path": str(resource_file.relative_to(project_root)),
                    "type": "binary_resource_skipped",
                    "detail": "binary .res detected; deep text audit skipped"
                })
                continue

            try:
                raw.decode("utf-8")
            except UnicodeDecodeError:
                issues.append({
                    "category": "binary_resources",
                    "path": str(resource_file.relative_to(project_root)),
                    "type": "unreadable_resource_skipped",
                    "detail": "resource file is not valid UTF-8; deep text audit skipped"
                })

        return issues, checked

    def _scan_text_resource_cycles(self, project_root: Path) -> tuple[list[Dict[str, str]], int]:
        issues = []
        checked = 0
        graph, edge_locations = self._build_text_resource_dependency_graph(project_root)
        checked += sum(len(targets) for targets in graph.values())

        index = 0
        stack: List[str] = []
        indices: Dict[str, int] = {}
        lowlinks: Dict[str, int] = {}
        on_stack: set[str] = set()
        strongly_connected_components: List[List[str]] = []

        def strongconnect(node: str) -> None:
            nonlocal index
            indices[node] = index
            lowlinks[node] = index
            index += 1
            stack.append(node)
            on_stack.add(node)

            for neighbor in graph.get(node, set()):
                if neighbor not in indices:
                    strongconnect(neighbor)
                    lowlinks[node] = min(lowlinks[node], lowlinks[neighbor])
                elif neighbor in on_stack:
                    lowlinks[node] = min(lowlinks[node], indices[neighbor])

            if lowlinks[node] == indices[node]:
                component: List[str] = []
                while stack:
                    current = stack.pop()
                    on_stack.remove(current)
                    component.append(current)
                    if current == node:
                        break
                strongly_connected_components.append(component)

        for node in graph:
            if node not in indices:
                strongconnect(node)

        for component in strongly_connected_components:
            if len(component) == 1:
                node = component[0]
                if node not in graph.get(node, set()):
                    continue
                checked += 1
                cycle_nodes = [node, node]
                issues.append({
                    "category": "resource_cycles",
                    "path": " -> ".join(cycle_nodes),
                    "type": "reference_cycle",
                    "detail": "shortest closed path with 1 edge",
                    "suggested": self._build_cycle_break_suggestion(cycle_nodes, edge_locations)
                })
                continue

            cycle_nodes = self._find_shortest_cycle_path(component, graph)
            if not cycle_nodes:
                continue

            checked += len(cycle_nodes) - 1
            cycle_path = " -> ".join(cycle_nodes)
            issues.append({
                "category": "resource_cycles",
                "path": cycle_path,
                "type": "reference_cycle",
                "detail": f"shortest closed path with {len(cycle_nodes) - 1} edges",
                "suggested": self._build_cycle_break_suggestion(cycle_nodes, edge_locations)
            })

        return issues, checked

    def _build_text_resource_dependency_graph(self, project_root: Path) -> tuple[Dict[str, set[str]], Dict[tuple[str, str], List[int]]]:
        graph: Dict[str, set[str]] = {}
        edge_locations: Dict[tuple[str, str], List[int]] = {}
        ext_resource_pattern = re.compile(r'^\[ext_resource\b')

        for pattern in ("*.tscn", "*.tres", "*.res"):
            for resource_file in project_root.rglob(pattern):
                if self._should_skip(resource_file):
                    continue

                try:
                    lines = resource_file.read_text(encoding="utf-8").splitlines()
                except Exception:
                    continue

                relative_path = resource_file.relative_to(project_root).as_posix()
                graph.setdefault(relative_path, set())

                for line_number, raw_line in enumerate(lines, start=1):
                    line = raw_line.strip()
                    if not ext_resource_pattern.match(line):
                        continue

                    attrs = self._parse_section_attributes(line)
                    ext_path = attrs.get("path", "")
                    normalized_path = self._normalize_res_path(ext_path)
                    if normalized_path is None:
                        continue

                    normalized_path_str = normalized_path.as_posix()
                    if normalized_path.suffix.lower() not in {".tscn", ".tres", ".res"}:
                        continue
                    if self._should_skip(project_root / normalized_path):
                        continue
                    if not (project_root / normalized_path).exists():
                        continue

                    graph[relative_path].add(normalized_path_str)
                    graph.setdefault(normalized_path_str, set())
                    edge_locations.setdefault((relative_path, normalized_path_str), []).append(line_number)

        return graph, edge_locations

    def _find_shortest_cycle_path(self, component: List[str], graph: Dict[str, set[str]]) -> Optional[List[str]]:
        allowed_nodes = set(component)
        best_cycle: Optional[List[str]] = None

        for start in sorted(allowed_nodes):
            for neighbor in sorted(graph.get(start, set()) & allowed_nodes):
                if neighbor == start:
                    candidate = [start, start]
                else:
                    path_back = self._find_shortest_path(neighbor, start, graph, allowed_nodes)
                    if not path_back:
                        continue
                    candidate = [start] + path_back

                if candidate[0] != candidate[-1]:
                    continue

                if best_cycle is None:
                    best_cycle = candidate
                    continue

                if len(candidate) < len(best_cycle):
                    best_cycle = candidate
                    continue

                if len(candidate) == len(best_cycle) and " -> ".join(candidate) < " -> ".join(best_cycle):
                    best_cycle = candidate

        return best_cycle

    def _find_shortest_path(
        self,
        start: str,
        goal: str,
        graph: Dict[str, set[str]],
        allowed_nodes: set[str]
    ) -> Optional[List[str]]:
        if start == goal:
            return [start]

        queue = deque([(start, [start])])
        visited = {start}

        while queue:
            node, path = queue.popleft()
            for neighbor in sorted(graph.get(node, set()) & allowed_nodes):
                if neighbor == goal:
                    return path + [neighbor]
                if neighbor in visited:
                    continue
                visited.add(neighbor)
                queue.append((neighbor, path + [neighbor]))

        return None

    def _build_cycle_break_suggestion(
        self,
        cycle_nodes: List[str],
        edge_locations: Dict[tuple[str, str], List[int]]
    ) -> str:
        if len(cycle_nodes) < 2:
            return "inspect the resource cycle"
        source = cycle_nodes[0]
        target = cycle_nodes[1]
        locations = edge_locations.get((source, target), [])
        if locations:
            location_text = ", ".join(f"{source}:{line_number}" for line_number in sorted(locations))
            return f"remove or redirect ext_resource at {location_text} pointing to {target}"
        return f"remove or redirect ext_resource {source} -> {target}"

    def _scan_import_resources(self, project_root: Path) -> tuple[list[Dict[str, str]], int]:
        issues = []
        checked = 0
        dest_pattern = re.compile(r'^dest_files=(.+)$', re.MULTILINE)
        importer_pattern = re.compile(r'^importer="([^"]+)"$', re.MULTILINE)
        type_pattern = re.compile(r'^type="([^"]+)"$', re.MULTILINE)
        source_pattern = re.compile(r'source_file="([^"]+)"')

        for import_file in project_root.rglob("*.import"):
            if self._should_skip(import_file):
                continue

            logical_name = import_file.name[:-7]
            checked += 1
            if not self._is_snake_case(Path(logical_name).stem):
                suggested = self._to_snake_case(Path(logical_name).stem)
                if Path(logical_name).suffix:
                    suggested = f"{suggested}{Path(logical_name).suffix.lower()}"
                issues.append({
                    "category": "import_resources",
                    "path": str(import_file.relative_to(project_root)),
                    "type": "import_file",
                    "suggested": suggested
                })

            try:
                content = import_file.read_text(encoding="utf-8")
            except Exception:
                continue

            logical_relative_path = str(import_file.relative_to(project_root)).replace("\\", "/")[:-7]

            checked += 1
            if not importer_pattern.search(content):
                issues.append({
                    "category": "import_config",
                    "path": f"{import_file.relative_to(project_root)}::importer",
                    "type": "missing_importer",
                    "detail": "missing importer field"
                })

            checked += 1
            if not type_pattern.search(content):
                issues.append({
                    "category": "import_config",
                    "path": f"{import_file.relative_to(project_root)}::type",
                    "type": "missing_type",
                    "detail": "missing type field"
                })

            dest_matches = list(dest_pattern.finditer(content))
            checked += 1
            if not dest_matches:
                issues.append({
                    "category": "import_artifacts",
                    "path": f"{import_file.relative_to(project_root)}::dest_files",
                    "type": "missing_dest_files",
                    "detail": "missing dest_files field"
                })

            for dest_match in dest_matches:
                dest_paths = self._parse_string_list(dest_match.group(1))
                checked += 1
                if not dest_paths:
                    issues.append({
                        "category": "import_artifacts",
                        "path": f"{import_file.relative_to(project_root)}::dest_files",
                        "type": "empty_dest_files",
                        "detail": "dest_files does not contain any target paths"
                    })
                    continue

                for dest_path in dest_paths:
                    checked += 1
                    normalized_dest_path = self._normalize_res_path(dest_path)
                    if normalized_dest_path is None:
                        issues.append({
                            "category": "import_artifacts",
                            "path": f"{import_file.relative_to(project_root)}::dest_files",
                            "type": "invalid_dest_path",
                            "detail": "dest_files entries should start with res://"
                        })
                        continue

                    normalized_dest_path_str = normalized_dest_path.as_posix()

                    checked += 1
                    if not normalized_dest_path_str.startswith(".godot/imported/"):
                        issues.append({
                            "category": "import_artifacts",
                            "path": f"{import_file.relative_to(project_root)}::dest_files",
                            "type": "dest_file_outside_import_cache",
                            "detail": f"unexpected target `{normalized_dest_path_str}`"
                        })

                    checked += 1
                    if not (project_root / normalized_dest_path).exists():
                        issues.append({
                            "category": "import_artifacts",
                            "path": f"{import_file.relative_to(project_root)}::dest_files",
                            "type": "missing_dest_target",
                            "detail": f"missing target `{normalized_dest_path_str}`"
                        })

            source_matches = list(source_pattern.finditer(content))
            checked += 1
            if not source_matches:
                issues.append({
                    "category": "import_config",
                    "path": f"{import_file.relative_to(project_root)}::source_file",
                    "type": "missing_source_file",
                    "detail": "missing source_file field"
                })

            for source_match in source_pattern.finditer(content):
                checked += 1
                source_path = source_match.group(1)
                normalized_source_path = self._normalize_res_path(source_path)
                if normalized_source_path is None:
                    issues.append({
                        "category": "import_config",
                        "path": f"{import_file.relative_to(project_root)}::source_file",
                        "type": "invalid_source_path",
                        "detail": "source_file should start with res://"
                    })
                    continue

                normalized_source_path_str = normalized_source_path.as_posix()

                checked += 1
                if normalized_source_path_str != logical_relative_path:
                    issues.append({
                        "category": "import_config",
                        "path": f"{import_file.relative_to(project_root)}::source_file",
                        "type": "source_file_mismatch",
                        "detail": f"expected `{logical_relative_path}`",
                        "suggested": logical_relative_path
                    })

                checked += 1
                if not (project_root / normalized_source_path).exists():
                    issues.append({
                        "category": "import_config",
                        "path": f"{import_file.relative_to(project_root)}::source_file",
                        "type": "missing_source_target",
                        "detail": f"missing target `{normalized_source_path_str}`"
                    })

                source_name = normalized_source_path.name
                source_stem = Path(source_name).stem
                if self._is_snake_case(source_stem):
                    continue

                suggested = self._to_snake_case(source_stem)
                if Path(source_name).suffix:
                    suggested = f"{suggested}{Path(source_name).suffix.lower()}"

                issues.append({
                    "category": "import_resources",
                    "path": f"{import_file.relative_to(project_root)}::source_file",
                    "type": "import_source",
                    "suggested": suggested
                })

        return issues, checked

    def _parse_section_attributes(self, line: str) -> Dict[str, str]:
        attrs = {}
        for match in re.finditer(r'(\w+)=("([^"]*)"|([^\s\]]+))', line):
            key = match.group(1)
            value = match.group(3) if match.group(3) is not None else match.group(4)
            attrs[key] = value
        return attrs

    def _parse_string_list(self, value: str) -> List[str]:
        return re.findall(r'"([^"]+)"', value)

    def _normalize_res_path(self, value: str) -> Optional[Path]:
        if not value.startswith("res://"):
            return None
        relative = value.replace("res://", "", 1).strip()
        if not relative:
            return None
        return Path(relative)

    def _should_skip(self, path: Path) -> bool:
        hidden_markers = {"__pycache__", ".git", ".import", ".godot"}
        if path.name.startswith(".") and path.name not in {".gdignore"}:
            return True
        return any(part in hidden_markers for part in path.parts)

    def _is_snake_case(self, value: str) -> bool:
        return bool(re.fullmatch(r"[a-z0-9_]+", value))

    def _to_snake_case(self, value: str) -> str:
        normalized = re.sub(r"[\s\-]+", "_", value)
        normalized = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", normalized)
        normalized = re.sub(r"[^a-zA-Z0-9_]", "_", normalized)
        normalized = re.sub(r"_+", "_", normalized).strip("_")
        return normalized.lower() or "unnamed"

    def _annotate_issue_severity(self, issues: List[Dict[str, str]]) -> List[Dict[str, str]]:
        annotated_issues = []
        for issue in issues:
            annotated_issue = dict(issue)
            annotated_issue["severity"] = self._classify_issue_severity(annotated_issue)
            annotated_issues.append(annotated_issue)
        return annotated_issues

    def _classify_issue_severity(self, issue: Dict[str, str]) -> str:
        issue_type = issue.get("type", "")
        category = issue.get("category", "")

        info_types = {
            "binary_resource_skipped",
            "unreadable_resource_skipped"
        }
        warning_types = {
            "file",
            "directory",
            "scene_node",
            "import_file",
            "import_source",
            "duplicate_ext_resource_path",
            "load_steps_too_small",
            "resource_load_steps_too_small",
            "dest_file_outside_import_cache"
        }

        if issue_type in info_types or category == "binary_resources":
            return "info"
        if issue_type in warning_types:
            return "warning"
        return "error"

    def _count_issue_severity(self, issues: List[Dict[str, str]]) -> Dict[str, int]:
        counts = {"error": 0, "warning": 0, "info": 0}
        for issue in issues:
            counts[issue.get("severity", "warning")] = counts.get(issue.get("severity", "warning"), 0) + 1
        return counts

    def _get_highest_severity(self, issues: List[Dict[str, str]]) -> str:
        severity_order = {"error": 3, "warning": 2, "info": 1}
        highest = "info"
        highest_score = 0
        for issue in issues:
            severity = issue.get("severity", "warning")
            score = severity_order.get(severity, 0)
            if score > highest_score:
                highest = severity
                highest_score = score
        return highest

    def _build_audit_report(self, project_root: Path, roots: List[Path], checked: int, issues: List[Dict[str, str]]) -> str:
        categories = {
            "filesystem": "Filesystem Issues",
            "scene_headers": "Scene Header Issues",
            "scene_nodes": "Scene Node Issues",
            "scene_references": "Scene Reference Issues",
            "resource_headers": "Resource Header Issues",
            "resource_references": "Resource Reference Issues",
            "binary_resources": "Binary Resource Issues",
            "resource_cycles": "Resource Cycle Issues",
            "import_resources": "Import Resource Issues",
            "import_config": "Import Config Issues",
            "import_artifacts": "Import Artifact Issues"
        }
        severity_counts = self._count_issue_severity(issues)
        severity_order = {"error": 0, "warning": 1, "info": 2}

        lines = [
            "# Resource Audit",
            "",
            f"- Project Root: `{project_root}`",
            f"- Scan Roots: {', '.join(f'`{root.relative_to(project_root) if root != project_root else '.'}`' for root in roots)}",
            f"- Checked Items: {checked}",
            f"- Issues Found: {len(issues)}",
            f"- Errors: {severity_counts['error']}",
            f"- Warnings: {severity_counts['warning']}",
            f"- Infos: {severity_counts['info']}",
            ""
        ]

        if not issues:
            lines.append("No audit issues detected.")
            return "\n".join(lines) + "\n"

        for category_key, title in categories.items():
            category_issues = [issue for issue in issues if issue.get("category") == category_key]
            if not category_issues:
                continue
            category_issues = sorted(
                category_issues,
                key=lambda issue: (
                    severity_order.get(issue.get("severity", "warning"), 1),
                    issue.get("path", ""),
                    issue.get("type", "")
                )
            )

            lines.extend([
                f"## {title}",
                ""
            ])
            for issue in category_issues:
                severity_label = issue.get("severity", "warning").upper()
                detail = issue.get("detail")
                suggested = issue.get("suggested")
                if detail and suggested:
                    lines.append(f"- [{severity_label}] `{issue['path']}` ({issue['type']}) - {detail} -> `{suggested}`")
                elif detail:
                    lines.append(f"- [{severity_label}] `{issue['path']}` ({issue['type']}) - {detail}")
                elif suggested:
                    lines.append(f"- [{severity_label}] `{issue['path']}` ({issue['type']}) -> `{suggested}`")
                else:
                    lines.append(f"- [{severity_label}] `{issue['path']}` ({issue['type']})")
            lines.append("")

        return "\n".join(lines) + "\n"

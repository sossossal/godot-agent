"""
Godot 项目蓝图管理器 (Project Blueprint Manager)
职责: 维护项目的全局状态、设计规约、功能列表、拓扑结构、快照及 UI 样式规范
"""

import json
import os
import time
import shutil
from typing import Dict, List, Any, Optional
from pydantic import BaseModel, Field


class Feature(BaseModel):
    """已实现的功能单元 (增强版: 包含生存元数据)"""
    name: str
    description: str
    status: str = "completed"
    dependencies: List[str] = []
    files: List[str] = []
    creation_skill: Optional[str] = None
    creation_params: Dict[str, Any] = {}
    created_at: float = Field(default_factory=time.time)


class ProjectBlueprint(BaseModel):
    """项目完整蓝图"""
    project_name: str = "New Game"
    game_genre: str = "General"
    project_template: Dict[str, Any] = {}
    gameplay_template_id: str = ""
    starter_gameplay_systems: List[Dict[str, Any]] = []
    coding_style: Dict[str, str] = {
        "naming_convention": "snake_case",
        "class_name_required": "true",
        "signal_pattern": "SignalBus"
    }
    ui_styles: Dict[str, Any] = {
        "primary_color": "#ffffff",
        "corner_radius": 4
    }
    features: Dict[str, Feature] = {}
    applied_patterns: List[Dict[str, Any]] = []
    scene_topology: List[Dict[str, Any]] = []
    global_autoloads: List[str] = []
    last_updated: float = Field(default_factory=time.time)


class BlueprintManager:
    """蓝图持久化、约束与自修复引擎"""
    
    def __init__(self, project_path: str):
        self.project_path = project_path
        self.base_dir = os.path.join(project_path, ".godot_agent")
        self.blueprint_path = os.path.join(self.base_dir, "blueprint.json")
        self.snapshot_dir = os.path.join(self.base_dir, "snapshots")
        os.makedirs(self.snapshot_dir, exist_ok=True)
        self.blueprint = self._load_blueprint()

    def _load_blueprint(self) -> ProjectBlueprint:
        if os.path.exists(self.blueprint_path):
            try:
                with open(self.blueprint_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    return ProjectBlueprint(**data)
            except: pass
        return ProjectBlueprint()

    def save(self):
        """持久化蓝图 (兼容 Pydantic V2)"""
        self.blueprint.last_updated = time.time()
        # 使用 model_dump_json 并通过 json.loads/dumps 处理 ensure_ascii
        json_str = self.blueprint.model_dump_json(indent=2)
        with open(self.blueprint_path, 'w', encoding='utf-8') as f:
            f.write(json_str)

    def create_snapshot(self, label: str) -> str:
        """创建当前蓝图的快照"""
        timestamp = int(time.time())
        snapshot_name = f"snapshot_{label}_{timestamp}.json"
        path = os.path.join(self.snapshot_dir, snapshot_name)
        with open(path, 'w', encoding='utf-8') as f:
            f.write(self.blueprint.model_dump_json(indent=2))
        return snapshot_name

    def list_snapshots(self) -> List[str]:
        if not os.path.exists(self.snapshot_dir): return []
        return sorted(os.listdir(self.snapshot_dir), reverse=True)

    def restore_snapshot(self, snapshot_name: str) -> bool:
        path = os.path.join(self.snapshot_dir, snapshot_name)
        if not os.path.exists(path): return False
        try:
            with open(path, 'r', encoding='utf-8') as f:
                data = json.load(f)
                self.blueprint = ProjectBlueprint(**data)
                self.save()
                return True
        except: return False

    def add_feature(self, feature: Feature):
        self.blueprint.features[feature.name] = feature
        self.save()

    def upsert_gameplay_systems(
        self,
        template_id: str,
        systems: List[Dict[str, Any]],
        *,
        creation_skill: str,
        creation_params: Dict[str, Any],
    ) -> List[str]:
        normalized_systems: List[Dict[str, Any]] = []
        seeded_features: List[str] = []

        for raw_system in systems or []:
            system = dict(raw_system or {})
            system_id = str(system.get("system_id") or "").strip()
            if not system_id:
                continue
            feature_name = str(system.get("starter_feature_name") or system_id).strip() or system_id
            dependencies = [
                str(item).strip()
                for item in list(system.get("dependencies") or [])
                if str(item).strip()
            ]
            normalized_systems.append(system)

            if feature_name not in self.blueprint.features:
                self.blueprint.features[feature_name] = Feature(
                    name=feature_name,
                    description=str(system.get("summary") or system.get("display_name") or feature_name),
                    status="planned",
                    dependencies=dependencies,
                    files=[],
                    creation_skill=creation_skill,
                    creation_params={**dict(creation_params or {}), "system_id": system_id},
                )
                seeded_features.append(feature_name)
            else:
                existing = self.blueprint.features[feature_name]
                existing.dependencies = dependencies or list(existing.dependencies or [])
                if not existing.description:
                    existing.description = str(system.get("summary") or system.get("display_name") or feature_name)

        self.blueprint.gameplay_template_id = str(template_id or "").strip()
        self.blueprint.starter_gameplay_systems = normalized_systems
        self.save()
        return seeded_features

    def get_repair_plan(self) -> List[Dict[str, Any]]:
        """查找缺失文件并生成修复步骤"""
        missing_features = []
        for name, feat in self.blueprint.features.items():
            if not feat.creation_skill: continue
            for file_path in feat.files:
                if file_path.startswith("res://"):
                    rel_path = file_path.replace("res://", "", 1)
                    full_path = os.path.join(self.project_path, rel_path)
                    if not os.path.exists(full_path):
                        missing_features.append({
                            "skill": feat.creation_skill,
                            "params": feat.creation_params,
                            "feature_name": name
                        })
                        break
        return missing_features

    def update_ui_style(self, styles: Dict[str, Any]):
        self.blueprint.ui_styles.update(styles)
        self.save()

    def generate_markdown_report(self) -> str:
        b = self.blueprint
        lines = [f"# 项目开发报告: {b.project_name}", f"**导出时间**: {time.strftime('%Y-%m-%d %H:%M:%S')}", f"**游戏类型**: {b.game_genre}", "\n## 1. 架构规约"]
        if b.project_template:
            lines.append(f"- **模板**: {b.project_template.get('display_name', '-') } ({b.project_template.get('template_id', '-')})")
        if b.gameplay_template_id:
            lines.append(f"- **玩法模板**: {b.gameplay_template_id} ({len(b.starter_gameplay_systems)} systems)")
        lines.append(f"- **命名规范**: {b.coding_style.get('naming_convention')}")
        lines.append(f"- **UI 风格**: {b.ui_styles}")
        lines.append("\n## 2. 功能清单")
        for name, feat in b.features.items():
            lines.append(f"### {name}\n- {feat.description}")
        return "\n".join(lines)

    def add_scene_connection(self, from_scene: str, trigger: str, to_scene: str):
        self.blueprint.scene_topology.append({"from": from_scene, "trigger": trigger, "to": to_scene})
        self.save()

    def mark_pattern_applied(self, info: Dict[str, Any]):
        self.blueprint.applied_patterns.append(info)
        self.save()

    def validate_project(self) -> List[Dict[str, Any]]:
        issues: List[Dict[str, Any]] = []
        for name, feat in self.blueprint.features.items():
            for file_path in feat.files:
                if not isinstance(file_path, str) or not file_path.startswith("res://"):
                    continue
                rel_path = file_path.replace("res://", "", 1)
                full_path = os.path.join(self.project_path, rel_path)
                if not os.path.exists(full_path):
                    issues.append({
                        "severity": "error",
                        "feature": name,
                        "path": file_path,
                        "message": "declared feature file is missing",
                    })
        return issues

    def get_context_summary(self) -> str:
        b = self.blueprint
        summary = [f"### 项目蓝图 (Project Blueprint)", f"- 游戏类型: {b.game_genre}"]
        if b.project_template:
            summary.append(f"- 项目模板: {b.project_template.get('display_name', '-') } ({b.project_template.get('template_id', '-')})")
        if b.gameplay_template_id:
            summary.append(f"- 玩法模板: {b.gameplay_template_id} ({len(b.starter_gameplay_systems)} systems)")
        summary.extend([f"- 编码规约: {b.coding_style}", f"- 已实现功能: {list(b.features.keys())}"])
        return "\n".join(summary)

    def check_conflict(self, proposed_action: str) -> Optional[str]:
        for name in self.blueprint.features:
            if name.lower() in proposed_action.lower() and ("创建" in proposed_action or "新建" in proposed_action):
                return f"警告: 功能 '{name}' 已存在。"
        return None

"""
代码生成角色 (编排版 - 带备份)
负责生成 GDScript 代码并在修改前进行备份
"""

import re
import os
import shutil
import time
from pathlib import Path
from typing import Dict, List, Any, Optional
from ..models import Task, TaskStatus, Artifact, Backup
from .base import BaseRole
from ..tools.gdscript_ast import GDScriptRefactorEngine
from ..skills.registry import SkillRegistry


class CodeGeneratorRole(BaseRole):
    """代码生成角色"""

    def __init__(self, godot_cli, index_service=None):
        super().__init__(godot_cli, index_service=index_service)
        self.refactor_engine = GDScriptRefactorEngine()
    
    def get_description(self) -> str:
        return "代码生成专家,擅长生成玩家控制、收集、库存、对话和战斗等常用脚本"
    
    def get_capabilities(self) -> List[str]:
        return ["生成并保存脚本", "自动备份旧文件", "生成玩法模板", "生成 UI/系统脚本", "安全重命名类/函数/信号"]
    
    def execute(self, task: Task) -> Task:
        """执行代码生成或属性修改任务"""
        task.status = TaskStatus.RUNNING
        command = task.prompt
        
        # 🧠 语义中台补强
        keywords = re.findall(r'[A-Z][a-z]+|[a-z]+', command)
        useful_keywords = [k for k in keywords if len(k) > 3]
        self._enrich_context_from_index(task, useful_keywords)
        
        try:
            # 1. 检查是否为安全重构指令
            if "重命名" in command or "改名" in command or "重构" in command:
                return self._handle_safe_refactor(task)

            # 2. 检查是否为属性修改指令
            if "设置" in command and "属性" in command:
                return self._handle_property_update(task)

            if any(k in command for k in ["SignalBus", "信号总线", "全局信号", "注册信号"]):
                skill_res = SkillRegistry.get_skill_with_params(
                    "manage_signal_bus",
                    command,
                    self.godot_cli,
                    self.index_service,
                )
                if skill_res:
                    skill, params = skill_res
                    result = skill.execute(task, params)
                    self._apply_skill_result_contract(task, result)
                    self._merge_result_artifacts(task, result)
                    if result.success:
                        return self._success_task(task, result.message)
                    return self._error_task(task, result.message, result.error)

            if "信号" in command and any(k in command for k in ["连接", "connect", "回调"]):
                skill_res = SkillRegistry.get_skill_with_params(
                    "wire_signal_connection",
                    command,
                    self.godot_cli,
                    self.index_service,
                )
                if skill_res:
                    skill, params = skill_res
                    result = skill.execute(task, params)
                    self._apply_skill_result_contract(task, result)
                    self._merge_result_artifacts(task, result)
                    if result.success:
                        return self._success_task(task, result.message)
                    return self._error_task(task, result.message, result.error)

            if any(k in command for k in ["动画", "淡入", "缩放", "弹跳", "旋转", "Tween", "tween"]):
                skill_res = SkillRegistry.get_skill_with_params(
                    "apply_tween_animation",
                    command,
                    self.godot_cli,
                    self.index_service,
                )
                if skill_res:
                    skill, params = skill_res
                    if not params.get("target_script") and task.context.get("target_script_path"):
                        params["target_script"] = task.context["target_script_path"]
                    result = skill.execute(task, params)
                    self._apply_skill_result_contract(task, result)
                    self._merge_result_artifacts(task, result)
                    if result.success:
                        return self._success_task(task, result.message)
                    return self._error_task(task, result.message, result.error)

            if "对话" in command:
                skill_res = SkillRegistry.get_skill_with_params(
                    "generate_dialogue_system",
                    command,
                    self.godot_cli,
                    self.index_service,
                )
                if skill_res:
                    skill, params = skill_res
                    result = skill.execute(task, params)
                    self._apply_skill_result_contract(task, result)
                    self._merge_result_artifacts(task, result)
                    if result.success:
                        return self._success_task(task, result.message)
                    return self._error_task(task, result.message, result.error)

            # 3. 🆕 模块化技能调用: 2D 移动
            if any(k in command for k in ["移动", "运动", "控制"]):
                skill = SkillRegistry.get_skill("generate_movement_script", self.godot_cli, self.index_service)
                if skill:
                    # 从命令中提取参数 (这里未来可以由 Router/LLM 直接传入 params)
                    params = {
                        "is_top_down": "俯视" in command or "top-down" in command.lower(),
                        "script_name": "player_movement.gd"
                    }
                    if "速度" in command:
                        try:
                            s = re.search(r'速度\s*(\d+)', command)
                            if s: params["speed"] = float(s.group(1))
                        except: pass
                    
                    result = skill.execute(task, params)
                    self._apply_skill_result_contract(task, result)
                    self._merge_result_artifacts(task, result)
                    if result.success:
                        return self._success_task(task, result.message)
                    else:
                        return self._error_task(task, result.message, result.error)
            elif "金币" in command or "收集" in command:
                result_data = self._generate_coin_collectible(command)
            elif "库存" in command:
                result_data = self._generate_inventory_system(command)
            elif "对话" in command:
                result_data = self._generate_dialogue_system(command)
            elif "攻击" in command:
                result_data = self._generate_attack_system(command)
            elif "预加载" in command:
                result_data = self._generate_preload_registry(command)
            elif "血量" in command or "生命值" in command or "HP" in command.upper():
                result_data = self._generate_health_system(command)
            elif "单例" in command or "autoload" in command.lower():
                result_data = self._generate_singleton(command)
            else:
                result_data = self._generate_generic_script(command)
            
            if result_data:
                # ... (保持原有的文件保存和产物创建逻辑)
                code = result_data.get("code", "")
                name = result_data.get("script_name", "script.gd")
                
                rel_dir = "scripts"
                full_dir = rel_dir
                if self.godot_cli.project_path:
                    full_dir = os.path.join(self.godot_cli.project_path, rel_dir)
                
                os.makedirs(full_dir, exist_ok=True)
                full_path = os.path.join(full_dir, name)
                
                if os.path.exists(full_path):
                    backup_name = f"{name}.{int(time.time())}.bak"
                    backup_dir = os.path.join("logs", "backups")
                    os.makedirs(backup_dir, exist_ok=True)
                    backup_path = os.path.join(backup_dir, backup_name)
                    shutil.copy2(full_path, backup_path)
                    task.backups.append(Backup(original_path=full_path, backup_path=backup_path))
                
                with open(full_path, 'w', encoding='utf-8') as f:
                    f.write(code)
                
                artifact = Artifact(name=name, path=f"res://{rel_dir}/{name}", type="script", content=code)
                if not any(a.path == artifact.path for a in task.artifacts):
                    task.artifacts.append(artifact)
                return self._success_task(task, f"代码生成成功: {name}")
            
            return self._error_task(task, "未能生成有效代码")
                
        except Exception as e:
            return self._error_task(task, f"逻辑处理异常: {str(e)}", str(e))

    def _handle_safe_refactor(self, task: Task) -> Task:
        refactor = self._parse_refactor_command(task)
        if not refactor:
            return self._error_task(task, "无法解析重构指令，示例：重命名类 PlayerController 为 HeroController")

        project_root = Path(self.godot_cli.project_path or ".").resolve()
        if not project_root.exists():
            return self._error_task(task, f"项目路径不存在: {project_root}")

        target_script_rel = None
        if refactor.get("target_script_path"):
            target_script_rel = refactor["target_script_path"].replace("res://", "").replace("\\", "/")
        impact_before = self._get_symbol_impact_snapshot(
            refactor["symbol_type"],
            refactor["old_name"],
            target_script_rel,
        )

        backed_up = set()
        modified_files = []
        refactor_hits: Dict[str, List[Dict[str, Any]]] = {}
        for file_path in self._iter_refactor_files(project_root):
            try:
                original = file_path.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                continue
            except Exception:
                continue

            updated, hits = self._apply_refactor_to_content(
                file_path,
                original,
                refactor["symbol_type"],
                refactor["old_name"],
                refactor["new_name"],
            )
            if updated == original:
                continue

            self._backup_existing_file(task, file_path, backed_up)
            file_path.write_text(updated, encoding="utf-8")
            relative_path = file_path.relative_to(project_root).as_posix()
            modified_files.append(relative_path)
            if hits:
                refactor_hits[relative_path] = hits

        if not modified_files:
            return self._error_task(
                task,
                f"未找到可更新的 {refactor['symbol_type']} `{refactor['old_name']}` 引用"
            )

        if self.index_service:
            self.index_service.rebuild(force=True)
        impact_after = self._get_symbol_impact_snapshot(
            refactor["symbol_type"],
            refactor["new_name"],
            target_script_rel,
        )

        report_content = self._build_refactor_report(refactor, modified_files, refactor_hits, impact_before, impact_after)
        report_dir = Path("logs") / "reports"
        report_dir.mkdir(parents=True, exist_ok=True)
        report_path = report_dir / f"safe_refactor_{int(time.time())}.md"
        report_path.write_text(report_content, encoding="utf-8")
        task.artifacts.append(Artifact(
            name=report_path.name,
            path=str(report_path),
            type="refactor_report",
            content=report_content
        ))
        task.context.update({
            "refactor_symbol_type": refactor["symbol_type"],
            "refactor_old_name": refactor["old_name"],
            "refactor_new_name": refactor["new_name"],
            "refactor_file_count": len(modified_files),
            "refactor_report_path": str(report_path),
            "refactor_reference_count_before": impact_before.get("reference_count", 0),
            "refactor_reference_count_after": impact_after.get("reference_count", 0),
            "refactor_impacted_files_before": impact_before.get("impacted_files", []),
            "refactor_impacted_files_after": impact_after.get("impacted_files", []),
        })
        if refactor.get("target_script_path"):
            task.context["refactor_target_script_path"] = refactor["target_script_path"]
        return self._success_task(
            task,
            f"安全重构完成: {refactor['symbol_type']} {refactor['old_name']} -> {refactor['new_name']}"
        )

    def _parse_refactor_command(self, task: Task) -> Optional[Dict[str, str]]:
        command = task.prompt
        patterns = [
            re.compile(r'(?:重命名|改名|重构)\s*(类|函数|方法|信号)\s*([A-Za-z_][A-Za-z0-9_]*)\s*(?:为|成|->|到)\s*([A-Za-z_][A-Za-z0-9_]*)'),
            re.compile(r'把\s*(类|函数|方法|信号)\s*([A-Za-z_][A-Za-z0-9_]*)\s*(?:重命名|改名)\s*(?:为|成)?\s*([A-Za-z_][A-Za-z0-9_]*)'),
            re.compile(r'(?:重命名|改名|重构)\s*当前(类|函数|方法|信号)\s*(?:为|成|->|到)\s*([A-Za-z_][A-Za-z0-9_]*)'),
            re.compile(r'把\s*当前(类|函数|方法|信号)\s*(?:重命名|改名)\s*(?:为|成)?\s*([A-Za-z_][A-Za-z0-9_]*)'),
        ]
        for pattern in patterns:
            match = pattern.search(command)
            if not match:
                continue
            symbol_type = match.group(1)
            if symbol_type == "方法":
                symbol_type = "函数"
            if pattern.groups == 3:
                return {
                    "symbol_type": symbol_type,
                    "old_name": match.group(2),
                    "new_name": match.group(3),
                    "target_script_path": task.context.get("target_script_path")
                }

            current_symbol = self._resolve_current_refactor_symbol(task, symbol_type)
            if not current_symbol:
                return None
            return {
                "symbol_type": symbol_type,
                "old_name": current_symbol,
                "new_name": match.group(2),
                "target_script_path": task.context.get("target_script_path")
            }
        return None

    def _resolve_current_refactor_symbol(self, task: Task, symbol_type: str) -> Optional[str]:
        if symbol_type == "类":
            return task.context.get("current_script_class_name")

        symbol_kind = task.context.get("current_script_symbol_kind")
        symbol_name = task.context.get("current_script_symbol_name")
        kind_map = {
            "函数": "func",
            "信号": "signal",
        }
        if symbol_kind == kind_map.get(symbol_type):
            return symbol_name
        return None

    def _iter_refactor_files(self, project_root: Path):
        yielded = set()
        project_file = project_root / "project.godot"
        if project_file.exists():
            yielded.add(project_file.resolve())
            yield project_file

        for pattern in ("*.gd", "*.tscn", "*.tres", "*.res"):
            for file_path in project_root.rglob(pattern):
                if any(part in {"__pycache__", ".git", ".godot"} for part in file_path.parts):
                    continue
                resolved = file_path.resolve()
                if resolved in yielded:
                    continue
                yielded.add(resolved)
                yield file_path

    def _apply_refactor_to_content(
        self,
        file_path: Path,
        content: str,
        symbol_type: str,
        old_name: str,
        new_name: str,
    ) -> tuple[str, List[Dict[str, Any]]]:
        if file_path.suffix.lower() == ".gd":
            updated, hits = self.refactor_engine.rename_symbol(content, symbol_type, old_name, new_name)
            return updated, hits

        escaped_old = re.escape(old_name)
        updated = content

        if symbol_type == "类":
            updated = re.sub(
                rf'(^\s*class_name\s+){escaped_old}(\s*$)',
                rf'\1{new_name}\2',
                updated,
                flags=re.MULTILINE
            )
            updated = re.sub(rf'\b{escaped_old}\b', new_name, updated)
            return updated, ([{"line": 0, "context": "text_fallback"}] if updated != content else [])

        if symbol_type == "函数":
            replacements = [
                (rf'(^\s*func\s+){escaped_old}(\s*\()', rf'\1{new_name}\2'),
                (rf'(\.){escaped_old}(\s*\()', rf'\1{new_name}\2'),
                (rf'(?<!func\s)\b{escaped_old}(\s*\()', rf'{new_name}\1'),
                (rf'((?:call|call_deferred|rpc|rpc_id|has_method)\(\s*["\']){escaped_old}(["\'])', rf'\1{new_name}\2'),
                (rf'(Callable\([^,\n]+,\s*["\']){escaped_old}(["\'])', rf'\1{new_name}\2'),
            ]
            for pattern, replacement in replacements:
                updated = re.sub(pattern, replacement, updated, flags=re.MULTILINE)
            return updated, ([{"line": 0, "context": "text_fallback"}] if updated != content else [])

        if symbol_type == "信号":
            replacements = [
                (rf'(^\s*signal\s+){escaped_old}(\s*(?:\(|$))', rf'\1{new_name}\2'),
                (rf'\b{escaped_old}(\s*\.(?:connect|disconnect|emit)\b)', rf'{new_name}\1'),
                (rf'((?:emit_signal|connect|disconnect|is_connected)\(\s*["\']){escaped_old}(["\'])', rf'\1{new_name}\2'),
            ]
            for pattern, replacement in replacements:
                updated = re.sub(pattern, replacement, updated, flags=re.MULTILINE)
            return updated, ([{"line": 0, "context": "text_fallback"}] if updated != content else [])

        return updated, []

    def _backup_existing_file(self, task: Task, file_path: Path, backed_up: set[str]) -> None:
        resolved = str(file_path.resolve())
        if resolved in backed_up:
            return

        backup_dir = Path("logs") / "backups"
        backup_dir.mkdir(parents=True, exist_ok=True)
        backup_name = f"{file_path.name}.{int(time.time() * 1000)}.bak"
        backup_path = backup_dir / backup_name
        shutil.copy2(file_path, backup_path)
        task.backups.append(Backup(original_path=str(file_path), backup_path=str(backup_path)))
        backed_up.add(resolved)

    def _build_refactor_report(
        self,
        refactor: Dict[str, str],
        modified_files: List[str],
        refactor_hits: Dict[str, List[Dict[str, Any]]],
        impact_before: Dict[str, Any],
        impact_after: Dict[str, Any],
    ) -> str:
        lines = [
            "# Safe Refactor",
            "",
            f"- Symbol Type: `{refactor['symbol_type']}`",
            f"- Rename: `{refactor['old_name']}` -> `{refactor['new_name']}`",
            f"- Files Updated: {len(modified_files)}",
            f"- References Before: {impact_before.get('reference_count', 0)}",
            f"- References After: {impact_after.get('reference_count', 0)}",
            "",
            "## Modified Files",
            ""
        ]
        for relative_path in modified_files:
            lines.append(f"- `{relative_path}`")
            for hit in refactor_hits.get(relative_path, [])[:8]:
                line_no = hit.get("line")
                context = hit.get("context", "change")
                if line_no:
                    lines.append(f"  - line {line_no}: `{context}`")
                else:
                    lines.append(f"  - `{context}`")
        if impact_before.get("references"):
            lines.extend([
                "",
                "## Impact Before",
                "",
            ])
            for ref in impact_before["references"][:12]:
                lines.append(
                    f"- `{ref['path']}`:{ref.get('line', 0)} `{ref.get('context', 'ref')}`"
                )
        if impact_after.get("references"):
            lines.extend([
                "",
                "## Impact After",
                "",
            ])
            for ref in impact_after["references"][:12]:
                lines.append(
                    f"- `{ref['path']}`:{ref.get('line', 0)} `{ref.get('context', 'ref')}`"
                )
        lines.append("")
        return "\n".join(lines)

    def _get_symbol_impact_snapshot(
        self,
        symbol_type: str,
        symbol_name: str,
        target_script_rel: Optional[str],
    ) -> Dict[str, Any]:
        if not self.index_service:
            return {"reference_count": 0, "impacted_files": [], "references": []}
        return self.index_service.get_symbol_impact(
            symbol_name,
            symbol_type=symbol_type,
            defining_path=target_script_rel,
        )

    def _handle_property_update(self, task: Task) -> Task:
        """处理属性实时更新 (增加健壮性校验)"""
        command = task.prompt
        match = re.search(r'设置.*?属性\s*(\w+)\s*为\s*(-?[\d\.]+)', command)
        if not match: return self._error_task(task, "无法解析指令")
            
        prop_name = match.group(1)
        prop_value = match.group(2)
        
        script = f'''
func _run(plugin: EditorPlugin):
    var selection = plugin.get_editor_interface().get_selection().get_selected_nodes()
    if selection.size() == 0:
        print("⚠️ 未选中节点, 尝试操作场景根节点")
        var root = plugin.get_editor_interface().get_edited_scene_root()
        if root: selection = [root]
    
    for node in selection:
        if "{prop_name}" in node:
            node.set("{prop_name}", {prop_value})
            print("✅ 成功更新 %s: %s = %s" % [node.name, "{prop_name}", "{prop_value}"])
        else:
            # 智能尝试: 检查是否在子节点或关联脚本中
            print("ℹ️ 节点 %s 不直接支持 %s, 正在跳过" % [node.name, "{prop_name}"])
'''
        task.artifacts.append(Artifact(name="prop_update.gd", path="internal://", type="editor_script", content=script))
        return self._success_task(task, f"属性指令已下发")

    def _generate_movement_script(self, command: str) -> Dict[str, Any]:
        is_3d = "3D" in command or "三维" in command
        code = self._get_3d_movement_template() if is_3d else self._get_2d_movement_template()
        name = "player_movement_3d.gd" if is_3d else "player_movement_2d.gd"
        return {"script_name": name, "code": code, "language": "gdscript"}
    
    def _generate_health_system(self, command: str) -> Dict[str, Any]:
        code = 'extends Node\nclass_name HealthSystem\nvar hp = 100\n'
        return {"script_name": "health_system.gd", "code": code, "language": "gdscript"}

    def _generate_coin_collectible(self, command: str) -> Dict[str, Any]:
        code = """extends Area2D
class_name CoinCollectible

@export var value: int = 1

func _ready():
    body_entered.connect(_on_body_entered)

func _on_body_entered(body):
    if body.has_method("add_coins"):
        body.add_coins(value)
    elif "coins" in body:
        body.coins += value

    queue_free()
"""
        return {"script_name": "coin_collectible.gd", "code": code, "language": "gdscript"}

    def _generate_inventory_system(self, command: str) -> Dict[str, Any]:
        code = """extends Node
class_name InventorySystem

signal item_added(item_id: String, amount: int)
signal item_removed(item_id: String, amount: int)

var items: Dictionary = {}

func add_item(item_id: String, amount: int = 1) -> void:
    items[item_id] = items.get(item_id, 0) + amount
    item_added.emit(item_id, amount)

func remove_item(item_id: String, amount: int = 1) -> bool:
    if not has_item(item_id, amount):
        return false

    items[item_id] -= amount
    if items[item_id] <= 0:
        items.erase(item_id)

    item_removed.emit(item_id, amount)
    return true

func has_item(item_id: String, amount: int = 1) -> bool:
    return items.get(item_id, 0) >= amount
"""
        return {"script_name": "inventory_system.gd", "code": code, "language": "gdscript"}

    def _generate_dialogue_system(self, command: str) -> Dict[str, Any]:
        code = """extends Control
class_name DialogueSystem

signal dialogue_started
signal line_changed(text: String)
signal dialogue_finished

var lines: Array[String] = []
var current_index: int = -1

func start_dialogue(dialogue_lines: Array[String]) -> void:
    lines = dialogue_lines
    current_index = -1
    visible = true
    dialogue_started.emit()
    next_line()

func next_line() -> void:
    current_index += 1
    if current_index >= lines.size():
        finish_dialogue()
        return

    line_changed.emit(lines[current_index])

func finish_dialogue() -> void:
    visible = false
    dialogue_finished.emit()
"""
        return {"script_name": "dialogue_system.gd", "code": code, "language": "gdscript"}

    def _generate_attack_system(self, command: str) -> Dict[str, Any]:
        code = """extends Node
class_name AttackSystem

signal attack_triggered(damage: int)

@export var damage: int = 10
@export var attack_cooldown: float = 0.4

var _cooldown_left: float = 0.0

func _process(delta: float) -> void:
    if _cooldown_left > 0.0:
        _cooldown_left = max(0.0, _cooldown_left - delta)

func can_attack() -> bool:
    return _cooldown_left <= 0.0

func try_attack() -> bool:
    if not can_attack():
        return false

    _cooldown_left = attack_cooldown
    attack_triggered.emit(damage)
    return true
"""
        return {"script_name": "attack_system.gd", "code": code, "language": "gdscript"}

    def _generate_preload_registry(self, command: str) -> Dict[str, Any]:
        code = """extends Node
class_name PreloadRegistry

const PLAYER_SCENE := preload("res://scenes/Player.tscn")
const ENEMY_SCENE := preload("res://scenes/Enemy.tscn")
const UI_THEME := preload("res://assets/ui/default_theme.tres")
"""
        return {"script_name": "preload_registry.gd", "code": code, "language": "gdscript"}
    
    def _generate_singleton(self, command: str) -> Dict[str, Any]:
        return {"script_name": "game_manager.gd", "code": "extends Node\n", "language": "gdscript"}
    
    def _generate_generic_script(self, command: str) -> Dict[str, Any]:
        return {"script_name": "new_script.gd", "code": "extends Node\n", "language": "gdscript"}
    
    def _get_2d_movement_template(self) -> str:
        return 'extends CharacterBody2D\nfunc _physics_process(delta):\n    var dir = Input.get_axis("ui_left", "ui_right")\n    velocity.x = dir * 300\n    move_and_slide()\n'
        
    def _get_3d_movement_template(self) -> str:
        return 'extends CharacterBody3D\nfunc _physics_process(delta):\n    velocity.y -= 9.8 * delta\n    move_and_slide()\n'

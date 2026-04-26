"""
Godot Multi-Agent System - 中央路由器 (V1.7.5 - 调试透传版)
职责: 任务全生命周期管理、深度蓝图约束、多技能链式编排
注意: 临时移除了执行期的异常捕获, 以便 debug_runner 捕获原始堆栈
"""

import json
import time
import yaml
import shutil
import os
import re
import sys
from typing import Dict, List, Optional, Any
from pathlib import Path

from .models import Task, TaskStatus, TaskStep, RoleMatch, Artifact, Backup, ToolResult
from .contracts import record_skill_result_on_task
from .tools.diagnosis_service import DiagnosisService, DiagnosisResult
from .roles.developer import DeveloperRole
from .roles.code_generator import CodeGeneratorRole
from .roles.tester import TesterRole
from .roles.ai_controller import AIControllerRole
from .roles.resource_manager import ResourceManagerRole
from .roles.architect import ArchitectRole
from .tools.godot_cli import GodotCLI
from .tools.index_service import ProjectIndexService
from .skills.registry import SkillRegistry
from .tools.blueprint_manager import BlueprintManager, Feature
from .tools.llm_client import LLMClient


class GodotAgentRouter:
    """Godot Agent 中央路由器"""

    SCRIPT_CLASS_RE = re.compile(r'^\s*class_name\s+([A-Za-z_]\w*)')
    SCRIPT_SIGNAL_RE = re.compile(r'^\s*signal\s+([A-Za-z_]\w*)(?:\(([^)]*)\))?')
    SCRIPT_FUNC_RE = re.compile(r'^\s*(?:static\s+)?func\s+([A-Za-z_]\w*)\s*\(([^)]*)\)\s*(?:->\s*([^:]+))?:?')

    STEP_DESCRIPTIONS = {
        "architect": "规划顶层架构",
        "developer": "构建场景节点",
        "code_generator": "处理逻辑或属性",
        "ai_controller": "生成 AI 行为逻辑",
        "tester": "运行测试或验证",
        "resource_manager": "整理项目或执行发布"
    }
    
    SKILL_ROLE_MAP = {
        "architect": "architect",
        "code": "code_generator",
        "dev": "developer",
        "test": "tester",
        "resource": "resource_manager",
        "ai": "ai_controller"
    }

    def __init__(self, config_path: str = "config.yaml", godot_project_path: Optional[str] = None, history_file: Optional[str] = None):
        self.config_path = Path(config_path)
        if not self.config_path.exists():
            alternate_path = Path(__file__).parent.parent / config_path
            if alternate_path.exists():
                self.config_path = alternate_path

        self.runtime_root = self.config_path.parent.resolve()
        self.config = self._load_config(str(self.config_path))

        configured_project_path = self.config.get("godot", {}).get("project_path")
        self.project_path = self._resolve_project_path(godot_project_path or configured_project_path)
        
        self.generated_root = self.config.get("runtime", {}).get("generated_root", "agent_modules")
        
        if not self.project_path:
            sandbox_project = self.runtime_root / "sandbox_project"
            if sandbox_project.exists():
                self.project_path = str(sandbox_project.resolve())

        self.godot_cli = GodotCLI(
            executable_path=self.config.get("godot", {}).get("executable_path"),
            project_path=self.project_path
        )

        self.index_service = self._create_index_service(self.project_path)
        self.blueprint_manager = BlueprintManager(self.project_path or ".")
        self.diagnosis_service = DiagnosisService(self.index_service)

        llm_config = self.config.get("llm", {})
        if llm_config.get("enabled"):
            llm_client = LLMClient(api_key=llm_config.get("api_key"), base_url=llm_config.get("base_url", "https://api.openai.com/v1"))
            SkillRegistry.set_llm_client(llm_client)

        if self.index_service is not None:
            try:
                self.index_service.rebuild(force=True)
            except Exception as exc:
                sys.stderr.write(f"⚠️ 项目索引初始化失败: {exc}\n")

        self.roles = {
            "developer": DeveloperRole(self.godot_cli, self.index_service),
            "code_generator": CodeGeneratorRole(self.godot_cli, self.index_service),
            "tester": TesterRole(self.godot_cli, self.index_service),
            "ai_controller": AIControllerRole(self.godot_cli, self.index_service),
            "resource_manager": ResourceManagerRole(self.godot_cli, self.index_service)
        }

        configured_history_path = history_file or self.config.get("runtime", {}).get("history_path", "logs/task_history.json")
        self.history_file = self._resolve_runtime_path(configured_history_path)
        self.history_file.parent.mkdir(parents=True, exist_ok=True)
        self.backup_dir = (self.history_file.parent / "backups").resolve()
        self.backup_dir.mkdir(parents=True, exist_ok=True)

        self.tasks: Dict[str, Task] = {}
        self._load_history()

    def _resolve_project_path(self, project_path: Optional[str]) -> Optional[str]:
        if not project_path: return None
        candidate = Path(project_path).expanduser()
        if not candidate.is_absolute():
            candidate = (self.runtime_root / candidate).resolve()
        else:
            candidate = candidate.resolve()
        return str(candidate)

    def _resolve_runtime_path(self, path_value: str) -> Path:
        candidate = Path(path_value).expanduser()
        if not candidate.is_absolute():
            candidate = (self.runtime_root / candidate).resolve()
        else:
            candidate = candidate.resolve()
        return candidate

    def _create_index_service(self, project_path: Optional[str]):
        if not project_path: return None
        project_root = Path(project_path)
        if not project_root.exists(): return None
        return ProjectIndexService(str(project_root))

    def _load_config(self, config_path: str) -> Dict:
        try:
            with open(config_path, 'r', encoding='utf-8') as f:
                return yaml.safe_load(f)
        except Exception as e:
            sys.stderr.write(f"⚠️ 加载配置失败: {e}\n")
            return self._get_default_config()

    def _get_default_config(self) -> Dict:
        return {"roles": {"architect": {"enabled": True}, "developer": {"enabled": True}, "code_generator": {"enabled": True}, "tester": {"enabled": True}, "ai_controller": {"enabled": True}, "resource_manager": {"enabled": True}}}

    def _load_history(self):
        if not self.history_file.exists(): return
        try:
            with open(self.history_file, 'r', encoding='utf-8') as f:
                for line in f:
                    if not line.strip(): continue
                    try:
                        d = json.loads(line)
                        task = Task(
                            prompt=d.get('prompt', ''),
                            task_id=d.get('task_id', ''),
                            role=d.get('role'),
                            status=TaskStatus(d.get('status', 'pending')),
                            created_at=d.get('created_at', time.time()),
                            logs=d.get('logs', []),
                            context=d.get('context', {})
                        )
                        for a in d.get('artifacts', []):
                            task.artifacts.append(Artifact(**a))
                        for s in d.get('steps', []):
                            task.steps.append(TaskStep(
                                name=s['name'], 
                                description=s['description'], 
                                role=s['role'],
                                status=TaskStatus(s['status']),
                                metadata=s.get('metadata', {})
                            ))
                        self.tasks[task.task_id] = task
                    except: pass
        except: pass

    def plan(self, prompt: str, context: Optional[Dict] = None) -> Task:
        task = Task(prompt=prompt, context=context or {}, status=TaskStatus.PLANNING)
        task.context["generated_root"] = self.generated_root
        self._apply_editor_context_hints(task)
        
        conflict_msg = self.blueprint_manager.check_conflict(prompt)
        if conflict_msg: task.add_log(f"⚠️ 冲突: {conflict_msg}")
        task.context["blueprint_context"] = self.blueprint_manager.get_context_summary()
        task.context["blueprint_manager"] = self.blueprint_manager

        skill_matches = self._match_skills(prompt)
        if skill_matches:
            for skill_meta in skill_matches:
                task.steps.append(TaskStep(
                    name=skill_meta["name"],
                    description=skill_meta["description"],
                    role=self.SKILL_ROLE_MAP.get(skill_meta["category"], "code_generator"),
                    metadata={"skill_name": skill_meta["name"]}
                ))
            task.status = TaskStatus.AWAITING_CONFIRMATION
            task.role = task.steps[0].role
            return task

        for role_name in self._match_step_roles(prompt):
            task.steps.append(self._create_step_for_role(role_name))
            
        if not task.steps:
            task.status = TaskStatus.FAILED
            task.add_log("错误: 无法规划任务")
        else:
            task.status = TaskStatus.AWAITING_CONFIRMATION
            task.role = task.steps[0].role
        return task

    def _match_skills(self, prompt: str) -> List[Dict[str, Any]]:
        all_skills = {s["name"]: s for s in SkillRegistry.list_skills()}
        matches = []
        intent_map = [
            (("开始制作", "项目基调"), "init_game_blueprint"),
            (("规划功能", "新增需求"), "plan_game_feature"),
            (("玩法模板", "核心系统", "玩法骨架", "gameplay 模板", "starter systems"), "manage_gameplay_template"),
            (("表现层模板", "动画树", "animation tree", "shader 模板", "音频总线", "音频事件", "particle profile"), "manage_presentation_pipeline"),
            (("remote config", "experiment catalog", "ab test", "A/B test", "liveops", "运营配置", "灰度实验"), "manage_liveops_pipeline"),
            (("平台交付", "平台发布", "存档 schema", "savegame schema", "multiplayer profile", "platform delivery"), "manage_platform_delivery"),
            (("检查进度", "状态检查"), "audit_project_consistency"),
            (("游戏流程", "逻辑流", "场景跳转"), "define_game_flow"),
            (("UI 风格", "界面风格", "样式规范"), "set_ui_style"),
            (("关卡模板", "关卡审计", "出生点", "交互点", "检查点", "导航区"), "manage_level_workflow"),
            (("美术资源", "贴图资源", "UI 图标", "精灵表", "材质资源", "特效资源", "Blender 模型", "GLTF 模型", "Aseprite", "Spine", "Substance", "外包交付包"), "manage_art_asset_pipeline"),
            (("测试流程", "验证蓝图"), "run_scenario_chain_test"),
            (("逻辑审计", "逻辑检查", "语法检查", "信号审计"), "audit_logic_errors"),
            (("保存快照", "恢复架构"), "manage_blueprint_snapshots"),
            (("导出报告", "生成文档"), "export_blueprint_doc"),
            (("应用模式", "设计模式"), "apply_design_pattern"),
            (("自修复", "自愈"), "self_heal_project"),
        ]
        found_names = set()
        for keywords, skill_name in intent_map:
            if skill_name in found_names:
                continue
            if any(keyword in prompt for keyword in keywords):
                skill_meta = all_skills.get(skill_name)
                if skill_meta:
                    matches.append(skill_meta)
                    found_names.add(skill_name)
        return matches

    def execute_plan(self, task: Task) -> Task:
        if task.status not in {TaskStatus.AWAITING_CONFIRMATION, TaskStatus.RUNNING, TaskStatus.PLANNING}:
            return task
        task.status = TaskStatus.RUNNING

        step_index = 0
        while step_index < len(task.steps):
            step = task.steps[step_index]
            if step.status in {TaskStatus.SUCCESS, TaskStatus.CANCELLED}:
                step_index += 1
                continue
            if step.status == TaskStatus.WAITING_ACK:
                task.status = TaskStatus.WAITING_ACK
                self._save_task(task)
                return task
            if step.status == TaskStatus.PENDING and step.requires_confirmation:
                step.status = TaskStatus.AWAITING_CONFIRMATION
                task.status = TaskStatus.AWAITING_CONFIRMATION
                self._save_task(task)
                return task

            step.status = TaskStatus.RUNNING
            step.start_time = time.time()
            task.add_log(f"开始步骤: {step.name}")

            artifact_count = len(task.artifacts)
            original_prompt = task.prompt
            task.prompt = step.metadata.get("prompt_override", original_prompt)

            try:
                skill_name = step.metadata.get("skill_name")
                if skill_name:
                    params = step.metadata.get("params")
                    skill = None
                    if params is None:
                        skill_res = SkillRegistry.get_skill_with_params(skill_name, task.prompt, self.godot_cli, self.index_service)
                        if skill_res:
                            skill, params = skill_res
                    else:
                        skill = SkillRegistry.get_skill(skill_name, self.godot_cli, self.index_service)

                    if not skill or params is None:
                        step.status = TaskStatus.FAILED
                        step.error = f"无法匹配技能: {skill_name}"
                        task.status = TaskStatus.FAILED
                        break

                    result = skill.execute(task, params)
                    task.artifacts.extend(result.artifacts)
                    record_skill_result_on_task(task, dict(result.metadata or {}).get("skill_result"))
                    step.metadata["skill_result"] = dict(result.metadata or {}).get("skill_result")
                    step.end_time = time.time()

                    if result.success:
                        if self._contains_editor_script(task.artifacts[artifact_count:]):
                            step.status = TaskStatus.WAITING_ACK
                            task.status = TaskStatus.WAITING_ACK
                            self._save_task(task)
                            return task

                        step.status = TaskStatus.SUCCESS
                        self._sync_blueprint_feature(skill_name, params, result)
                        self._inject_pending_skill_steps(task, step_index)
                        step_index += 1
                        continue

                    step.status = TaskStatus.FAILED
                    step.error = result.error or result.message
                    task.status = TaskStatus.FAILED
                    if self._schedule_auto_fix(task, step, step_index):
                        step.status = TaskStatus.PENDING
                        step.error = None
                        step.start_time = 0.0
                        step.end_time = 0.0
                        task.status = TaskStatus.RUNNING
                        continue
                    break

                role = self.roles.get(step.role)
                if not role:
                    step.status = TaskStatus.FAILED
                    step.error = f"未找到角色: {step.role}"
                    task.status = TaskStatus.FAILED
                    break

                task = role.execute(task)
                step.end_time = time.time()
                new_artifacts = task.artifacts[artifact_count:]

                if task.status == TaskStatus.WAITING_ACK or self._contains_editor_script(new_artifacts):
                    step.status = TaskStatus.WAITING_ACK
                    task.status = TaskStatus.WAITING_ACK
                    self._save_task(task)
                    return task

                if task.status == TaskStatus.SUCCESS:
                    step.status = TaskStatus.SUCCESS
                    step_index += 1
                    continue

                step.status = TaskStatus.FAILED
                step.error = task.get_message()
                if self._schedule_auto_fix(task, step, step_index):
                    step.status = TaskStatus.PENDING
                    step.error = None
                    step.start_time = 0.0
                    step.end_time = 0.0
                    task.status = TaskStatus.RUNNING
                    continue
                break
            finally:
                task.prompt = original_prompt

        if task.steps and all(s.status == TaskStatus.SUCCESS for s in task.steps):
            task.status = TaskStatus.SUCCESS
        elif task.status == TaskStatus.RUNNING and any(s.status == TaskStatus.FAILED for s in task.steps):
            task.status = TaskStatus.FAILED
        self._save_task(task)
        return task

    def _contains_editor_script(self, artifacts: List[Artifact]) -> bool:
        return any(artifact.type == "editor_script" for artifact in artifacts)

    def _sync_blueprint_feature(self, skill_name: str, params: Dict[str, Any], result: ToolResult) -> None:
        tracked_skills = {
            "create_godot_scene",
            "generate_movement_script",
            "init_game_blueprint",
            "plan_game_feature",
            "auto_layout_ui",
            "inject_godot_node",
            "instantiate_scene_prefab",
            "manage_input_mapping",
            "manage_signal_bus",
            "wire_signal_connection",
            "manage_level_workflow",
            "apply_tween_animation",
            "generate_dialogue_system",
            "manage_audio_resource",
            "generate_ai_behavior",
            "inject_vfx_particle",
            "setup_3d_environment",
            "configure_physics_collision",
            "inject_3d_primitive",
            "quick_capture_scene",
        }
        if skill_name not in tracked_skills:
            return

        feature_name = (
            params.get("scene_name")
            or params.get("script_name")
            or params.get("feature_name")
            or params.get("level_name")
            or params.get("dialogue_name")
            or params.get("action_name")
            or params.get("signal_name")
            or params.get("callback_name")
            or params.get("audio_name")
            or params.get("target_node_name")
            or params.get("node_name")
            or skill_name
        )
        self.blueprint_manager.add_feature(Feature(
            name=feature_name,
            description=f"由技能 {skill_name} 产出",
            files=[artifact.path for artifact in result.artifacts if artifact.type in {"scene", "script"}],
            creation_skill=skill_name,
            creation_params=params,
        ))

    def _inject_pending_skill_steps(self, task: Task, step_index: int) -> None:
        if "pending_pattern_steps" not in task.context:
            return
        pending = task.context.pop("pending_pattern_steps")
        for offset, step_dict in enumerate(pending, start=1):
            task.steps.insert(step_index + offset, TaskStep(**step_dict))

    def _schedule_auto_fix(self, task: Task, step: TaskStep, step_index: int) -> bool:
        if step.role != "code_generator" or step.metadata.get("auto_fix_retry"):
            return False
        if "resource_manager" not in self.roles:
            return False

        recent_error = task.get_message()
        if "No export template found" not in recent_error and not any(
            "No export template found" in log for log in task.logs[-5:]
        ):
            return False

        step.metadata["auto_fix_retry"] = True
        task.steps.insert(step_index, TaskStep(
            name="AutoFix-resource_manager",
            description="审计并初始化导出环境",
            role="resource_manager",
            metadata={"prompt_override": "审计并初始化导出环境", "auto_fix": True},
        ))
        return True

    def _save_task(self, task: Task):
        self.tasks[task.task_id] = task
        try:
            with open(self.history_file, 'a', encoding='utf-8') as f:
                f.write(json.dumps(task.to_dict(), ensure_ascii=False) + "\n")
        except: pass

    def rollback(self, task: Task):
        task.status = TaskStatus.ROLLED_BACK
        task.add_log("执行回滚...")

    def get_available_roles(self) -> List[str]:
        return list(self.roles.keys())

    def get_history(self, limit: int = 10) -> List[Dict[str, Any]]:
        tasks = sorted(self.tasks.values(), key=lambda x: x.created_at, reverse=True)
        return [t.to_dict() for t in tasks[:limit]]

    def get_task(self, task_id: str) -> Optional[Task]:
        return self.tasks.get(task_id)

    def execute(self, prompt: str, context: Optional[Dict] = None, confirm: bool = True) -> Task:
        task = self.plan(prompt, context)
        return self.execute_plan(task) if confirm and task.status != TaskStatus.FAILED else task

    def _match_step_roles(self, prompt: str) -> List[str]:
        matched: List[str] = []
        is_resource = (
            any(keyword in prompt for keyword in ["导出", "发布", "分享"])
            or (any(keyword in prompt for keyword in ["资源", "命名"]) and any(keyword in prompt for keyword in ["审计", "检查", "修复", "预览"]))
            or any(keyword in prompt for keyword in ["数据表", "任务表", "对白表", "对话表", "掉落表", "本地化表", "CSV", "TSV", "JSON"])
            or any(keyword in prompt for keyword in ["数值平衡", "平衡分析", "敌人强度", "掉落分析", "奖励分析", "经济分析"])
            or any(keyword in prompt for keyword in ["性能", "性能基线", "性能画像", "帧率", "内存峰值", "draw call", "节点数", "卡顿峰值", "纹理预算"])
            or any(keyword in prompt for keyword in ["遥测", "埋点", "事件字典", "会话回流", "崩溃回流", "漏斗分析", "留存分析", "隐私门禁", "PII"])
            or any(keyword in prompt for keyword in ["运营配置", "remote config", "experiment", "A/B test", "ab test", "灰度实验", "liveops"])
            or (
                any(keyword in prompt.lower() for keyword in ["texture", "spritesheet", "material", "vfx", "gltf", "blender", "aseprite", "spine", "substance", "outsource", "vendor package", "telemetry", "analytics", "session", "crash", "funnel", "performance", "fps", "draw call", "draw_call", "node count", "frame spike", "texture budget", "shader", "audio bus", "audio event", "animation tree", "animationplayer", "presentation", "remote config", "experiment catalog", "liveops", "ab test"])
                or any(keyword in prompt for keyword in ["美术资源", "贴图", "纹理", "UI 图标", "界面资源", "精灵表", "材质资源", "特效资源", "粒子资源"])
            )
            or "整理项目" in prompt
            or "初始化导出环境" in prompt
        )
        is_test = any(keyword in prompt for keyword in ["测试", "验证", "调试", "截图", "端到端", "冒烟"]) or "运行场景" in prompt
        is_ai = "AI" in prompt or any(keyword in prompt for keyword in ["巡逻", "追击", "警戒"])
        is_code = (
            any(keyword in prompt for keyword in [
                "代码", "脚本", "逻辑", "信号", "函数", "类", "重命名", "改名", "重构",
                "库存", "对话", "攻击", "血量", "生命值", "单例", "autoload", "预加载",
                "移动", "控制", "金币", "收集"
            ])
            or "生成代码" in prompt
        )
        is_developer = (
            (
                "关卡" in prompt
                or
                ("场景" in prompt and any(keyword in prompt for keyword in ["创建", "新建"]))
                or "节点" in prompt
                or any(keyword in prompt for keyword in [
                    "实例化", "碰撞", "物理", "UI", "界面", "布局", "特效",
                    "VFX", "3D环境", "立方体", "球体", "方块", "挂载",
                    "输入", "按键", "键位", "映射"
                ])
            )
            and not is_resource
        )

        if is_resource:
            matched.append("resource_manager")
        if is_developer:
            matched.append("developer")
        if is_ai:
            matched.append("ai_controller")
        elif is_code:
            matched.append("code_generator")
        if is_test:
            matched.append("tester")
        if not matched:
            matched.append("code_generator")
        return matched

    def _create_step_for_role(self, role_name: str) -> TaskStep:
        return TaskStep(name=role_name.capitalize(), description=self.STEP_DESCRIPTIONS.get(role_name, "执行指令"), role=role_name)

    def _apply_editor_context_hints(self, task: Task) -> None:
        editor_state = task.context.get("editor_state")
        if not isinstance(editor_state, dict):
            return

        current_scene = editor_state.get("current_scene")
        if current_scene and not task.context.get("scene_path") and (
            "当前场景" in task.prompt or any(keyword in task.prompt for keyword in ["测试", "验证", "运行", "截图"])
        ):
            task.context["scene_path"] = current_scene
            task.context["scene_path_source"] = "editor_state"

        current_script_path = editor_state.get("current_script_path")
        if current_script_path and not task.context.get("target_script_path"):
            task.context["target_script_path"] = current_script_path

        if not current_script_path:
            return

        script_file = self._resolve_project_file(current_script_path)
        if not script_file or not script_file.exists():
            return

        try:
            lines = script_file.read_text(encoding="utf-8").splitlines()
        except Exception:
            return

        for line in lines:
            match = self.SCRIPT_CLASS_RE.match(line)
            if match:
                task.context["current_script_class_name"] = match.group(1)
                break

        line_number = int(editor_state.get("current_script_line") or 0)
        symbol = self._find_script_symbol(lines, line_number)
        if not symbol:
            return

        task.context["current_script_symbol_kind"] = symbol["kind"]
        task.context["current_script_symbol_name"] = symbol["name"]
        if symbol["kind"] == "class":
            task.context["current_script_class_name"] = symbol["name"]

    def _resolve_project_file(self, path_value: str) -> Optional[Path]:
        candidate = Path(path_value)
        if candidate.is_absolute():
            return candidate
        if path_value.startswith("res://"):
            relative_path = path_value.replace("res://", "", 1)
            project_root = Path(self.project_path or self.runtime_root)
            return project_root / relative_path
        return Path(self.project_path or self.runtime_root) / path_value

    def _find_script_symbol(self, lines: List[str], line_number: int) -> Optional[Dict[str, str]]:
        if not lines:
            return None

        cursor = min(max(line_number, 1), len(lines)) if line_number else len(lines)
        fallback_class = None

        for index, line in enumerate(lines, start=1):
            class_match = self.SCRIPT_CLASS_RE.match(line)
            if class_match:
                fallback_class = {"kind": "class", "name": class_match.group(1)}
            if index > cursor:
                break

        for index in range(cursor, 0, -1):
            line = lines[index - 1]
            func_match = self.SCRIPT_FUNC_RE.match(line)
            if func_match:
                return {"kind": "func", "name": func_match.group(1)}
            signal_match = self.SCRIPT_SIGNAL_RE.match(line)
            if signal_match:
                return {"kind": "signal", "name": signal_match.group(1)}
            class_match = self.SCRIPT_CLASS_RE.match(line)
            if class_match:
                return {"kind": "class", "name": class_match.group(1)}

        return fallback_class

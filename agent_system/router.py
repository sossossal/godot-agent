"""
增强型中央路由器
支持关键词路由 + LLM 语义路由（可选）+ 插件化角色扩展
"""

import re
import importlib
import pkgutil
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field
from pathlib import Path
import yaml

from .roles.base import BaseRole
from .roles.developer import DeveloperRole
from .roles.code_generator import CodeGeneratorRole
from .roles.tester import TesterRole
from .roles.ai_controller import AIControllerRole
from .roles.resource_manager import ResourceManagerRole
from .roles.simulation import SimulationRole
from .roles.narrative import NarrativeRole
from .roles.ui_designer import UIDesignerRole
from .roles.audio_manager import AudioManagerRole
from .roles.level_designer import LevelDesignerRole
from .roles.optimizer import OptimizerRole
from .tools.godot_cli import GodotCLI


# ─── 关键词词典（未来可按需扩展） ───────────────────────────────────────────
DEFAULT_KEYWORDS: Dict[str, List[str]] = {
    "developer":        ["创建", "添加", "场景", "节点", "项目", "新建", "初始化"],
    "code_generator":   ["生成", "代码", "脚本", "写", "实现", "存档", "状态机", "单例", "血量", "移动", "物品", "背包", "战斗", "冷却"],
    "tester":           ["测试", "验证", "检查", "断言", "运行", "QA"],
    "ai_controller":    ["AI", "智能", "行为", "巡逻", "追击", "BOSS", "状态机", "NPC行为", "导航"],
    "resource_manager": ["资源", "优化", "导入", "纹理", "压缩", "整理"],
    "simulation":       ["仿真", "物理", "TCP", "通信", "传感", "PID", "平衡", "机器人"],
    "narrative":        ["剧情", "对话", "任务", "故事", "NPC", "支线", "主线", "台词", "对白", "对话树"],
    "ui_designer":      ["UI", "界面", "血条", "HUD", "菜单", "暂停", "背包界面", "技能栏", "小地图", "控件"],
    "audio_manager":    ["音频", "音效", "BGM", "音乐", "声音", "背景音"],
    "level_designer":   ["关卡", "地图", "房间", "地块", "TileMap", "地牢", "迷宫", "关卡生成", "程序化"],
    "optimizer":        ["优化", "卡顿", "帧率", "性能", "内存", "对象池", "LOD", "Draw Call"],
}


@dataclass
class RoleMatch:
    """角色路由匹配结果"""
    role_name: str
    confidence: float
    matched_keywords: List[str] = field(default_factory=list)


class GodotStudioRouter:
    """
    Godot Studio Agent 中央路由器

    特性：
    - 关键词路由（始终可用）
    - LLM 语义路由（可选，配置 llm.enabled=true）
    - 插件化角色注册（运行时动态添加角色）
    - 命令历史 + 上下文传递
    - 未来可插拔的中间件管道
    """

    def __init__(
        self,
        config_path: str = "config.yaml",
        godot_project_path: Optional[str] = None,
    ):
        self.config = self._load_config(config_path)
        self.godot_cli = GodotCLI(
            executable_path=self.config.get("godot", {}).get("executable_path"),
            project_path=godot_project_path or self.config.get("godot", {}).get("project_path"),
        )
        self._roles: Dict[str, BaseRole] = {}
        self._init_builtin_roles()

        # 命令历史（带完整上下文，方便日后回溯分析）
        self.history: List[Dict[str, Any]] = []
        # 会话上下文（跨命令共享状态）
        self.session_context: Dict[str, Any] = {}

        print("🎮 Godot Studio Agent 已就绪，共", len(self._roles), "个角色")

    # ─── 初始化 ─────────────────────────────────────────────────────────────

    def _load_config(self, path: str) -> Dict:
        try:
            with open(path, "r", encoding="utf-8") as f:
                return yaml.safe_load(f) or {}
        except FileNotFoundError:
            return {}

    def _init_builtin_roles(self):
        """初始化所有内置角色"""
        builtin = {
            "developer":        DeveloperRole,
            "code_generator":   CodeGeneratorRole,
            "tester":           TesterRole,
            "ai_controller":    AIControllerRole,
            "resource_manager": ResourceManagerRole,
            "simulation":       SimulationRole,
            "narrative":        NarrativeRole,
            "ui_designer":      UIDesignerRole,
            "audio_manager":    AudioManagerRole,
            "level_designer":   LevelDesignerRole,
            "optimizer":        OptimizerRole,
        }
        for name, cls in builtin.items():
            self._roles[name] = cls(self.godot_cli)

    # ─── 插件化角色扩展 ──────────────────────────────────────────────────────

    def register_role(self, name: str, role: BaseRole, keywords: List[str] = None) -> None:
        """
        动态注册自定义角色（支持运行时热插拔）

        Args:
            name: 角色名称（唯一键）
            role: 角色实例（继承 BaseRole）
            keywords: 触发该角色的关键词列表
        """
        self._roles[name] = role
        if keywords:
            DEFAULT_KEYWORDS[name] = keywords
        print(f"🔌 已注册自定义角色: {name}")

    def unregister_role(self, name: str) -> bool:
        """注销角色"""
        if name in self._roles:
            del self._roles[name]
            DEFAULT_KEYWORDS.pop(name, None)
            return True
        return False

    # ─── 路由逻辑 ────────────────────────────────────────────────────────────

    def _keyword_route(self, prompt: str) -> List[RoleMatch]:
        """关键词路由（必备，始终可用）"""
        matches = []
        for role_name, keywords in DEFAULT_KEYWORDS.items():
            if role_name not in self._roles:
                continue
            matched = [kw for kw in keywords if kw.lower() in prompt.lower()]
            if matched:
                confidence = len(matched) / len(keywords)
                matches.append(RoleMatch(role_name, min(confidence + 0.05, 1.0), matched))
        matches.sort(key=lambda x: x.confidence, reverse=True)
        return matches

    def _llm_route(self, prompt: str) -> Optional[str]:
        """
        LLM 语义路由（可选，需在 config.yaml 配置 llm.enabled=true）
        当关键词路由置信度不足 0.3 时自动触发。
        未来可对接 OpenAI / Gemini / 本地 Ollama。
        """
        llm_cfg = self.config.get("llm", {})
        if not llm_cfg.get("enabled", False):
            return None
        # TODO: 接入 LLM 语义分类（角色枚举作为 few-shot 示例）
        return None

    def _analyze_prompt(self, prompt: str) -> List[RoleMatch]:
        """综合路由分析"""
        matches = self._keyword_route(prompt)

        # 若关键词置信度不足，尝试 LLM 路由
        if not matches or matches[0].confidence < 0.3:
            llm_role = self._llm_route(prompt)
            if llm_role and llm_role in self._roles:
                matches.insert(0, RoleMatch(llm_role, 0.85, ["[LLM语义]"]))

        return matches

    # ─── 执行接口 ────────────────────────────────────────────────────────────

    def execute(self, prompt: str, context: Optional[Dict] = None) -> Dict[str, Any]:
        """
        执行用户命令

        Args:
            prompt: 自然语言命令
            context: 可选的上下文（会与 session_context 合并）

        Returns:
            执行结果字典
        """
        print(f"\n🤖 命令: {prompt}")

        # 合并上下文
        merged_ctx = {**self.session_context, **(context or {})}

        matches = self._analyze_prompt(prompt)
        if not matches:
            result = {
                "success": False,
                "message": "❌ 无法识别命令意图，请换种描述方式",
                "prompt": prompt,
                "available_roles": list(self._roles.keys()),
            }
            self._record(prompt, "unknown", 0.0, result)
            return result

        best = matches[0]
        role = self._roles[best.role_name]
        print(f"📋 路由 → {best.role_name}（置信度 {best.confidence:.2f}，关键词: {best.matched_keywords}）")

        try:
            result = role.execute(prompt, merged_ctx)
            # 将角色元信息写入结果
            result["_meta"] = {
                "role": best.role_name,
                "confidence": best.confidence,
                "matched_keywords": best.matched_keywords,
                "all_matches": [{"role": m.role_name, "conf": m.confidence} for m in matches],
            }
        except Exception as e:
            result = {
                "success": False,
                "message": f"❌ 执行失败: {e}",
                "error": str(e),
                "role": best.role_name,
            }

        self._record(prompt, best.role_name, best.confidence, result)
        return result

    def execute_pipeline(self, commands: List[str]) -> List[Dict[str, Any]]:
        """
        执行命令流水线（多步骤顺序执行，结果自动传递为上下文）

        Args:
            commands: 命令列表

        Returns:
            每步结果列表
        """
        results = []
        for cmd in commands:
            result = self.execute(cmd)
            results.append(result)
            # 把上一步的数据写入会话上下文，供下一步使用
            if result.get("success") and result.get("data"):
                self.session_context.update(result["data"])
        return results

    # ─── 辅助方法 ────────────────────────────────────────────────────────────

    def _record(self, prompt, role, confidence, result):
        self.history.append({
            "prompt": prompt,
            "role": role,
            "confidence": confidence,
            "success": result.get("success", False),
            "message": result.get("message", ""),
        })

    def get_history(self, limit: int = 20) -> List[Dict]:
        return self.history[-limit:]

    def get_roles_info(self) -> List[Dict]:
        return [
            {
                "name": name,
                "description": role.get_description(),
                "capabilities": role.get_capabilities(),
            }
            for name, role in self._roles.items()
        ]

    def clear_session(self):
        """清空会话上下文（开始新项目时使用）"""
        self.session_context = {}
        self.history = []

"""
CodeGeneratorRole — GDScript/C# 代码生成角色
集成单机游戏全套系统模板
"""
from typing import Dict, List, Any
from .base import BaseRole
from ..tools.script_library import ScriptLibrary


class CodeGeneratorRole(BaseRole):
    """负责生成 GDScript 和 C# 代码"""

    def __init__(self, godot_cli=None):
        super().__init__(godot_cli)
        self.lib = ScriptLibrary()

    def get_description(self) -> str:
        return "代码生成专家，支持存档、状态机、战斗、背包等单机游戏全套系统"

    def get_capabilities(self) -> List[str]:
        return [
            "玩家移动脚本（2D/3D）",
            "血量/伤害系统",
            "存档/读档系统",
            "有限状态机",
            "背包/道具系统",
            "战斗/伤害计算",
            "技能/冷却系统",
            "全局事件总线",
            "对象池",
            "摄像机抖动",
            "单例/Autoload",
        ]

    def execute(self, command: str, context: Dict[str, Any]) -> Dict[str, Any]:
        cmd = command.lower()
        if any(k in cmd for k in ["移动", "运动", "controller"]):
            is_3d = "3d" in cmd or "三维" in cmd
            return self._gen("3D 玩家移动脚本" if is_3d else "2D 玩家移动脚本",
                             self.lib.get("player_3d") if is_3d else self.lib.get("player_2d"),
                             "player_controller.gd")

        elif any(k in cmd for k in ["血量", "生命", "hp", "伤害", "健康"]):
            return self._gen("血量系统", self.lib.get("health_system"), "health_system.gd")

        elif any(k in cmd for k in ["存档", "读档", "保存", "save", "load"]):
            return self._gen("存档系统", self.lib.get("save_system"), "save_system.gd")

        elif any(k in cmd for k in ["状态机", "fsm", "state machine"]):
            return self._gen("有限状态机", self.lib.get("state_machine"), "state_machine.gd")

        elif any(k in cmd for k in ["背包", "道具", "物品", "inventory", "item"]):
            return self._gen("背包系统", self.lib.get("inventory"), "inventory.gd")

        elif any(k in cmd for k in ["战斗", "攻击", "combat", "hit"]):
            return self._gen("战斗系统", self.lib.get("combat_system"), "combat_system.gd")

        elif any(k in cmd for k in ["技能", "冷却", "skill", "cooldown"]):
            return self._gen("技能冷却系统", self.lib.get("skill_system"), "skill_system.gd")

        elif any(k in cmd for k in ["事件", "信号", "eventbus", "bus"]):
            return self._gen("全局事件总线", self.lib.get("event_bus"), "event_bus.gd")

        elif any(k in cmd for k in ["对象池", "pool", "pooling"]):
            return self._gen("对象池", self.lib.get("object_pool"), "object_pool.gd")

        elif any(k in cmd for k in ["摄像机抖动", "camera shake", "震屏"]):
            return self._gen("摄像机抖动", self.lib.get("camera_shake"), "camera_shake.gd")

        elif any(k in cmd for k in ["单例", "autoload", "全局管理"]):
            return self._gen("游戏管理单例", self.lib.get("game_manager"), "game_manager.gd")

        else:
            return self._gen(
                "通用脚本模板",
                'extends Node\n\nfunc _ready() -> void:\n\tpass\n\nfunc _process(delta: float) -> void:\n\tpass\n',
                "new_script.gd"
            )

    def _gen(self, name: str, code: str, filename: str) -> Dict[str, Any]:
        print(f"💻 生成: {filename}")
        return self._success_result(
            f"{name} 已生成 → {filename}",
            {"script_name": filename, "code": code, "language": "gdscript"}
        )

"""
BaseRole — 所有 Agent 角色的抽象基类
"""
from abc import ABC, abstractmethod
from typing import Dict, List, Any, Optional


class BaseRole(ABC):
    """所有专业角色的基类"""

    def __init__(self, godot_cli=None):
        self.godot_cli = godot_cli

    @abstractmethod
    def get_description(self) -> str:
        """返回角色描述"""
        pass

    @abstractmethod
    def get_capabilities(self) -> List[str]:
        """返回角色能力列表"""
        pass

    @abstractmethod
    def execute(self, command: str, context: Dict[str, Any]) -> Dict[str, Any]:
        """执行命令"""
        pass

    # ─── 公共结果构造 ───────────────────────────────────────────────────────

    def _success_result(self, message: str, data: Optional[Dict] = None) -> Dict:
        return {
            "success": True,
            "message": f"✅ {message}",
            "role": self.__class__.__name__,
            "data": data or {},
        }

    def _error_result(self, message: str, error: str = "") -> Dict:
        return {
            "success": False,
            "message": f"❌ {message}",
            "role": self.__class__.__name__,
            "error": error,
        }

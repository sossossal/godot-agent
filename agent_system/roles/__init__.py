"""角色包初始化"""

from .base import BaseRole
from .developer import DeveloperRole
from .code_generator import CodeGeneratorRole
from .tester import TesterRole
from .ai_controller import AIControllerRole
from .resource_manager import ResourceManagerRole

__all__ = [
    "BaseRole",
    "DeveloperRole",
    "CodeGeneratorRole",
    "TesterRole",
    "AIControllerRole",
    "ResourceManagerRole"
]

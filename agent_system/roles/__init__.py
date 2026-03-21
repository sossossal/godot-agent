"""
所有 Agent 角色模块
"""
from .developer import DeveloperRole
from .code_generator import CodeGeneratorRole
from .tester import TesterRole
from .ai_controller import AIControllerRole
from .resource_manager import ResourceManagerRole
from .simulation import SimulationRole
from .narrative import NarrativeRole
from .ui_designer import UIDesignerRole
from .audio_manager import AudioManagerRole
from .level_designer import LevelDesignerRole
from .optimizer import OptimizerRole

__all__ = [
    "DeveloperRole", "CodeGeneratorRole", "TesterRole",
    "AIControllerRole", "ResourceManagerRole", "SimulationRole",
    "NarrativeRole", "UIDesignerRole", "AudioManagerRole",
    "LevelDesignerRole", "OptimizerRole"
]

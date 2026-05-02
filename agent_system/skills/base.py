"""
Godot Agent 技能系统基类 (模块化重构版)
职责: 定义原子化能力接口, 支持 Pydantic 参数验证和语义描述
"""

import os
import shutil
import time
from pathlib import Path
from abc import ABC, abstractmethod
from typing import Dict, List, Any, Optional, Type
from pydantic import BaseModel, Field
from ..contracts import build_skill_result_envelope
from ..models import Task, ToolResult, Artifact, Backup
from ..validations import ProjectLayoutValidator


class SkillMetadata(BaseModel):
    """技能元数据, 供 LLM 理解和检索"""
    name: str
    description: str
    category: str  # 'code', 'resource', 'test', 'ai', 'dev'
    tags: List[str] = []
    author: str = "Godot Agent Core"
    version: str = "1.0.0"


class BaseSkill(ABC):
    """技能基类"""
    
    # 静态元数据 (子类重写)
    metadata: SkillMetadata
    
    # 输入参数模型 (可选, 默认为空)
    input_model: Optional[Type[BaseModel]] = None
    
    def __init__(self, godot_cli: Any = None, index_service: Any = None):
        self.godot_cli = godot_cli
        self.index_service = index_service

    def resolve_generated_path(self, relative_res_path: str, task: Task) -> str:
        """
        将 res://scripts/abc.gd 转换为 res://agent_modules/scripts/abc.gd
        基于 Router.generated_root 配置进行隔离
        """
        # 从 task 上下文或路由配置中获取隔离根目录
        generated_root = task.context.get("generated_root", "agent_modules")
        
        if not relative_res_path.startswith("res://"):
            return relative_res_path
            
        path_part = relative_res_path.replace("res://", "", 1)
        return f"res://{generated_root}/{path_part}"

    @abstractmethod
    def execute(self, task: Task, params: Dict[str, Any]) -> ToolResult:
        """
        执行技能逻辑
        :param task: 当前任务对象 (用于记录日志和产物)
        :param params: 经过校验的输入参数
        :return: ToolResult
        """
        pass

    def validate_params(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """验证并清洗输入参数"""
        if self.input_model:
            model_instance = self.input_model(**params)
            return self.dump_model(model_instance)
        return params

    def dump_model(self, model_instance: BaseModel) -> Dict[str, Any]:
        if hasattr(model_instance, "model_dump"):
            return model_instance.model_dump()
        return model_instance.dict()

    def resolve_project_file_path(self, res_path: str) -> str:
        if res_path.startswith("res://"):
            relative_path = res_path.replace("res://", "", 1)
            return os.path.join(self.godot_cli.project_path or ".", relative_path)
        return os.path.join(self.godot_cli.project_path or ".", res_path)

    def validate_managed_output_path(self, res_path: str, kind: str) -> Dict[str, Any]:
        project_root = Path(getattr(self.godot_cli, "project_path", None) or ".").resolve()
        full_path = Path(self.resolve_project_file_path(res_path)).resolve()
        return ProjectLayoutValidator(
            project_root=project_root,
            runtime_root=Path.cwd().resolve(),
        ).validate_managed_path(full_path, kind)

    def backup_existing_file(self, task: Task, full_path: str) -> Optional[str]:
        if not full_path or not os.path.exists(full_path):
            return None

        backup_dir = os.path.join("logs", "backups")
        os.makedirs(backup_dir, exist_ok=True)
        backup_name = f"{os.path.basename(full_path)}.{int(time.time() * 1000)}.bak"
        backup_path = os.path.join(backup_dir, backup_name)
        shutil.copy2(full_path, backup_path)
        task.backups.append(Backup(original_path=full_path, backup_path=backup_path))
        return backup_path

    def build_result(
        self,
        *,
        success: bool,
        message: str,
        params: Optional[Dict[str, Any]] = None,
        data: Any = None,
        error: Optional[str] = None,
        artifacts: Optional[List[Artifact]] = None,
        logs: Optional[List[str]] = None,
        validation: Optional[Dict[str, Any]] = None,
        rollback: Optional[Dict[str, Any]] = None,
        quality_gate: Optional[Dict[str, Any]] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> ToolResult:
        artifact_list = list(artifacts or [])
        for artifact in artifact_list:
            artifact.metadata = {
                **dict(artifact.metadata or {}),
                "skill_name": self.metadata.name,
                "skill_category": self.metadata.category,
                "skill_version": self.metadata.version,
            }

        envelope = build_skill_result_envelope(
            skill_name=self.metadata.name,
            skill_category=self.metadata.category,
            skill_version=self.metadata.version,
            success=success,
            message=message,
            params=dict(params or {}),
            artifacts=artifact_list,
            validation=validation,
            rollback=rollback,
            quality_gate=quality_gate,
        )
        result_metadata = dict(metadata or {})
        result_metadata["skill_result"] = envelope
        return ToolResult(
            success=success,
            message=message,
            data=data,
            error=error,
            artifacts=artifact_list,
            logs=list(logs or []),
            metadata=result_metadata,
        )

    def get_tool_definition(self) -> Dict[str, Any]:
        """生成符合 OpenAI Tool Calling 规范的定义"""
        definition = {
            "type": "function",
            "function": {
                "name": self.metadata.name,
                "description": self.metadata.description,
                "parameters": {
                    "type": "object",
                    "properties": {},
                    "required": []
                }
            }
        }
        
        if self.input_model:
            schema = self.input_model.schema()
            definition["function"]["parameters"]["properties"] = schema.get("properties", {})
            definition["function"]["parameters"]["required"] = schema.get("required", [])
            
        return definition

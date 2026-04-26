"""
角色基类
所有专业角色都继承自此基类
"""

from abc import ABC, abstractmethod
from typing import Dict, List, Any, Optional
from ..contracts import build_skill_result_envelope, record_skill_result_on_task
from ..tools.godot_cli import GodotCLI
from ..models import Task, TaskStatus, Artifact, ToolResult


class BaseRole(ABC):
    """角色基类"""
    
    def __init__(self, godot_cli: GodotCLI, index_service: Any = None):
        """
        初始化角色
        
        Args:
            godot_cli: Godot CLI 实例
            index_service: 项目索引服务 (语义中台)
        """
        self.godot_cli = godot_cli
        self.index_service = index_service
    
    def _enrich_context_from_index(self, task: Task, keywords: List[str]):
        """根据关键字从索引中自动提取相关类、信号和方法到上下文中"""
        if not self.index_service:
            return
            
        related_info = []
        for kw in keywords:
            # 搜索匹配的类名
            for cls_name, info in self.index_service.classes.items():
                if kw.lower() in cls_name.lower():
                    related_info.append(f"类 {cls_name} (基类: {info.get('base') or 'None'})")
                    if info.get('signals'):
                        related_info.append(f"  - 信号: {', '.join(info['signals'])}")
                    if info.get('methods'):
                        methods = [m['name'] for m in info['methods'][:5]]
                        related_info.append(f"  - 方法: {', '.join(methods)}...")
        
        if related_info:
            task.add_log(f"🧠 语义中台发现相关参考: {', '.join(keywords)}")
            task.context.setdefault("index_hints", []).extend(related_info)
    
    @abstractmethod
    def get_description(self) -> str:
        """获取角色描述"""
        pass
    
    @abstractmethod
    def get_capabilities(self) -> List[str]:
        """获取角色能力列表"""
        pass
    
    @abstractmethod
    def execute(self, task: Task) -> Task:
        """
        执行命令
        
        Args:
            task: 统一任务模型
            
        Returns:
            执行后的 Task 对象
        """
        pass
    
    def _success_task(self, task: Task, message: str, data: Any = None) -> Task:
        """完成任务并标记成功"""
        task.status = TaskStatus.SUCCESS
        task.add_log(f"SUCCESS: {message}")
        if data:
            task.context.update(data)
        return task
    
    def _error_task(self, task: Task, message: str, error: Optional[str] = None) -> Task:
        """完成任务并标记失败"""
        task.status = TaskStatus.FAILED
        task.add_log(f"ERROR: {message}")
        if error:
            task.add_log(f"DETAIL: {error}")
        return task

    def _apply_skill_result_contract(self, task: Task, result: ToolResult) -> None:
        record_skill_result_on_task(task, dict(result.metadata or {}).get("skill_result"))

    def _merge_result_artifacts(self, task: Task, result: ToolResult) -> None:
        for artifact in result.artifacts:
            if any(
                existing.name == artifact.name
                and existing.path == artifact.path
                and existing.type == artifact.type
                for existing in task.artifacts
            ):
                continue
            task.artifacts.append(artifact)

    def _record_synthetic_skill_result(
        self,
        task: Task,
        *,
        skill_name: str,
        skill_category: str,
        success: bool,
        message: str,
        params: Optional[Dict[str, Any]] = None,
        artifacts: Optional[List[Artifact]] = None,
        validation: Optional[Dict[str, Any]] = None,
        rollback: Optional[Dict[str, Any]] = None,
        quality_gate: Optional[Dict[str, Any]] = None,
        skill_version: str = "1.0.0",
    ) -> None:
        artifact_list = list(artifacts or [])
        for artifact in artifact_list:
            artifact.metadata = {
                **dict(artifact.metadata or {}),
                "skill_name": skill_name,
                "skill_category": skill_category,
                "skill_version": skill_version,
            }

        record_skill_result_on_task(
            task,
            build_skill_result_envelope(
                skill_name=skill_name,
                skill_category=skill_category,
                skill_version=skill_version,
                success=success,
                message=message,
                params=dict(params or {}),
                artifacts=artifact_list,
                validation=validation,
                rollback=rollback,
                quality_gate=quality_gate,
            ),
        )

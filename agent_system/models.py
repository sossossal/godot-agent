"""
Godot Agent 系统模型定义 (编排版)
提供支持多步骤规划、预览和回滚的数据结构
"""

from dataclasses import dataclass, field, asdict
from typing import Dict, List, Optional, Any
import uuid
import time
from enum import Enum
from pathlib import Path

from .contracts import build_task_feature_context


class TaskStatus(Enum):
    PENDING = "pending"
    PLANNING = "planning"
    AWAITING_CONFIRMATION = "awaiting_confirmation"
    RUNNING = "running"
    BLOCKED = "blocked"             # 被依赖阻塞
    WAITING_ACK = "waiting_ack"     # 等待外部（如编辑器）回执
    SUCCESS = "success"
    FAILED = "failed"
    ROLLING_BACK = "rolling_back"
    ROLLED_BACK = "rolled_back"
    CANCELLED = "cancelled"


@dataclass
class Artifact:
    """任务产生的产物"""
    name: str
    path: str
    type: str  # 'script', 'scene', 'resource', 'log'
    content: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class Backup:
    """文件备份信息"""
    original_path: str
    backup_path: str
    timestamp: float = field(default_factory=time.time)


@dataclass
class TaskStep:
    """任务执行的具体步骤"""
    name: str
    description: str
    role: str
    step_id: str = field(default_factory=lambda: str(uuid.uuid4())) # 步骤级 trace ID
    status: TaskStatus = TaskStatus.PENDING
    result: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    start_time: float = 0.0
    end_time: float = 0.0
    depends_on: List[str] = field(default_factory=list) # 依赖的步骤名
    requires_confirmation: bool = False # 是否需要人工确认后执行
    metadata: Dict[str, Any] = field(default_factory=dict)



@dataclass
class Task:
    """编排任务模型"""
    prompt: str
    task_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    context: Dict[str, Any] = field(default_factory=dict)
    role: Optional[str] = None # 记录主角色
    status: TaskStatus = TaskStatus.PENDING
    steps: List[TaskStep] = field(default_factory=list)
    artifacts: List[Artifact] = field(default_factory=list)
    backups: List[Backup] = field(default_factory=list)
    logs: List[str] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    
    def add_log(self, message: str):
        timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
        self.logs.append(f"[{timestamp}] {message}")
        self.updated_at = time.time()

    def get_message(self) -> str:
        """返回适合展示给用户的任务摘要消息"""
        if not self.logs:
            return self.status.value

        detail = None
        for entry in reversed(self.logs):
            message = entry.split("] ", 1)[-1]

            if message.startswith("DETAIL: "):
                if detail is None:
                    detail = message[len("DETAIL: "):]
                continue

            if message.startswith("ERROR: "):
                base = message[len("ERROR: "):]
                return f"{base}: {detail}" if detail else base

            if message.startswith("SUCCESS: "):
                return message[len("SUCCESS: "):]

        for entry in reversed(self.logs):
            message = entry.split("] ", 1)[-1]
            if message not in {"启动回滚机制..."}:
                return message

        return self.status.value

    @property
    def message(self) -> str:
        return self.get_message()

    def to_dict(self) -> Dict[str, Any]:
        """统一任务序列化结构，供 CLI / API / IDE 复用"""
        _apply_feature_tracking(self)
        data = _json_safe(asdict(self))
        data["status"] = self.status.value
        data["message"] = self.message

        for step in data["steps"]:
            step_status = step.get("status")
            if hasattr(step_status, "value"):
                step["status"] = step_status.value

        return data


@dataclass
class ToolResult:
    """统一工具返回协议"""
    success: bool
    message: str
    data: Optional[Any] = None
    error: Optional[str] = None
    artifacts: List[Artifact] = field(default_factory=list)
    logs: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class RoleMatch:
    """角色匹配结果"""
    role_name: str
    confidence: float
    matched_keywords: List[str]


def _json_safe(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Path):
        return str(value)
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(item) for item in value]
    if hasattr(value, "model_dump"):
        return _json_safe(value.model_dump())
    return str(value)


def _apply_feature_tracking(task: Task) -> None:
    task.context = build_task_feature_context(
        prompt=task.prompt,
        task_id=task.task_id,
        task_status=task.status,
        context=task.context,
        steps=task.steps,
        artifacts=task.artifacts,
        message=task.message,
    )

"""
蓝图快照技能 (Snapshot Skill)
职责: 管理项目蓝图的版本快照, 支持保存、列出和回滚架构状态
"""

from typing import Dict, Any, List, Optional
from pydantic import BaseModel, Field
from ..base import BaseSkill, SkillMetadata
from ...models import Task, ToolResult, Artifact


class SnapshotParams(BaseModel):
    action: str = Field(description="动作: save, list, restore")
    label: str = Field(default="manual", description="快照标签 (用于保存)")
    snapshot_id: Optional[str] = Field(None, description="要恢复的快照 ID (用于恢复)")


class BlueprintSnapshotSkill(BaseSkill):
    metadata = SkillMetadata(
        name="manage_blueprint_snapshots",
        description="管理项目蓝图的快照。可以保存当前架构状态、查看快照列表或回滚到之前的快照。",
        category="architect",
        tags=["architect", "version-control", "snapshot"]
    )
    input_model = SnapshotParams

    def execute(self, task: Task, params: Dict[str, Any]) -> ToolResult:
        p = SnapshotParams(**params)
        blueprint = task.context.get("blueprint_manager")
        if not blueprint:
            return self.build_result(
                success=False,
                message="未找到蓝图管理器",
                params=self.dump_model(p),
                validation={"passed": False, "issues": ["missing_blueprint_manager"]},
            )
            
        if p.action == "save":
            name = blueprint.create_snapshot(p.label)
            return self.build_result(
                success=True,
                message=f"已保存蓝图快照: {name}",
                params=self.dump_model(p),
                artifacts=[
                    Artifact(
                        name="BlueprintSnapshot",
                        path=f"internal://blueprint_snapshot/{name}",
                        type="snapshot",
                        content=name,
                    )
                ],
                validation={
                    "passed": True,
                    "checks": [{"name": "snapshot_saved", "status": "passed"}],
                },
                rollback={"available": False, "strategy": "restore_snapshot"},
            )
            
        elif p.action == "list":
            snapshots = blueprint.list_snapshots()
            if not snapshots:
                return self.build_result(
                    success=True,
                    message="当前没有任何蓝图快照。",
                    params=self.dump_model(p),
                    validation={
                        "passed": True,
                        "checks": [{"name": "snapshot_inventory_scanned", "status": "passed"}],
                    },
                    rollback={"available": False, "strategy": "no_write_required"},
                )
            msg = "可用蓝图快照:\n" + "\n".join([f"- {s}" for s in snapshots])
            return self.build_result(
                success=True,
                message=msg,
                params=self.dump_model(p),
                artifacts=[
                    Artifact(
                        name="BlueprintSnapshotList",
                        path="internal://blueprint_snapshot/list.md",
                        type="report",
                        content=msg,
                    )
                ],
                validation={
                    "passed": True,
                    "checks": [{"name": "snapshot_inventory_scanned", "status": "passed"}],
                },
                rollback={"available": False, "strategy": "no_write_required"},
                metadata={"snapshot_count": len(snapshots)},
            )
            
        elif p.action == "restore":
            if not p.snapshot_id:
                return self.build_result(
                    success=False,
                    message="恢复快照需要提供具体的 snapshot_id",
                    params=self.dump_model(p),
                    validation={"passed": False, "issues": ["missing_snapshot_id"]},
                )
            restore_backup = blueprint.create_snapshot("pre_restore")
            success = blueprint.restore_snapshot(p.snapshot_id)
            if success:
                return self.build_result(
                    success=True,
                    message=f"已成功回滚架构到快照: {p.snapshot_id}",
                    params=self.dump_model(p),
                    artifacts=[
                        Artifact(
                            name="RestoredBlueprintSnapshot",
                            path=f"internal://blueprint_snapshot/{p.snapshot_id}",
                            type="snapshot",
                            content=p.snapshot_id,
                        )
                    ],
                    validation={
                        "passed": True,
                        "checks": [{"name": "snapshot_restored", "status": "passed"}],
                    },
                    rollback={
                        "available": True,
                        "strategy": "restore_snapshot",
                        "backup_paths": [f"internal://blueprint_snapshot/{restore_backup}"],
                    },
                )
            else:
                return self.build_result(
                    success=False,
                    message=f"快照恢复失败, 请检查 ID 是否正确: {p.snapshot_id}",
                    params=self.dump_model(p),
                    validation={"passed": False, "issues": ["snapshot_restore_failed"]},
                    rollback={
                        "available": True,
                        "strategy": "restore_snapshot",
                        "backup_paths": [f"internal://blueprint_snapshot/{restore_backup}"],
                    },
                )
                
        return self.build_result(
            success=False,
            message=f"未知的快照动作: {p.action}",
            params=self.dump_model(p),
            validation={"passed": False, "issues": ["unsupported_snapshot_action"]},
        )

"""
设计模式应用技能 (Apply Pattern Skill)
职责: 根据预设模板生成多个 Skill 任务序列, 实现复杂功能原型
"""

import json
import os
import time
from typing import Dict, Any, Optional
from pydantic import BaseModel, Field
from ..base import BaseSkill, SkillMetadata
from ...models import Task, ToolResult, TaskStep, Artifact


class PatternParams(BaseModel):
    pattern_name: str = Field(description="设计模式名称")
    overrides: Dict[str, Any] = Field(default_factory=dict, description="要覆盖的参数, 如 {'speed': 500}")


class ApplyPatternSkill(BaseSkill):
    metadata = SkillMetadata(
        name="apply_design_pattern",
        description="应用一个预设的 Godot 设计模式模板, 支持参数覆盖 (如速度、名称等)",
        category="architect",
        tags=["architect", "pattern", "automation"]
    )
    input_model = PatternParams

    def execute(self, task: Task, params: Dict[str, Any]) -> ToolResult:
        p = PatternParams(**params)
        pattern = self._load_pattern(p.pattern_name)
        
        if not pattern:
            return self.build_result(
                success=False,
                message=f"未找到设计模式: {p.pattern_name}",
                params=self.dump_model(p),
                validation={"passed": False, "issues": ["pattern_not_found"]},
            )
            
        task.add_log(f"🎨 正在应用设计模式: {p.pattern_name} (覆盖参数: {p.overrides})")
        
        # 合并参数逻辑
        new_steps = []
        for i, step_def in enumerate(pattern["steps"]):
            # 基础参数来自模板
            merged_params = step_def["params"].copy()
            # 寻找是否有匹配的 override (简单合并)
            for key, val in p.overrides.items():
                if key in merged_params:
                    merged_params[key] = val
            
            step = TaskStep(
                name=f"{p.pattern_name}_{i}",
                description=f"应用模板步骤: {step_def['skill']}",
                role="auto",
                metadata={
                    "skill_name": step_def["skill"],
                    "params": merged_params
                }
            )
            new_steps.append(step)
            
        from dataclasses import asdict
        task.context["pending_pattern_steps"] = [asdict(s) for s in new_steps]
        
        # 记录到蓝图的准备数据
        task.context["applied_pattern_info"] = {
            "name": p.pattern_name,
            "overrides": p.overrides,
            "timestamp": time.time()
        }
        blueprint = task.context.get("blueprint_manager")
        if blueprint:
            blueprint.mark_pattern_applied(task.context["applied_pattern_info"])
        
        plan_lines = [
            "# Pattern Execution Plan",
            "",
            f"- Pattern: {p.pattern_name}",
            f"- Step Count: {len(new_steps)}",
            "",
        ]
        for step in new_steps:
            plan_lines.append(
                f"- `{step.metadata['skill_name']}` with params `{json.dumps(step.metadata['params'], ensure_ascii=False)}`"
            )
        
        return self.build_result(
            success=True,
            message=f"已成功加载模式 '{p.pattern_name}' (已应用 {len(p.overrides)} 项自定义参数)。",
            params=self.dump_model(p),
            artifacts=[
                Artifact(
                    name="PatternExecutionPlan",
                    path="internal://pattern_execution_plan.md",
                    type="plan",
                    content="\n".join(plan_lines) + "\n",
                )
            ],
            validation={
                "passed": True,
                "checks": [
                    {"name": "pattern_loaded", "status": "passed"},
                    {"name": "pattern_steps_generated", "status": "passed"},
                ],
            },
            rollback={"available": False, "strategy": "clear_pending_pattern_steps"},
            metadata={"generated_step_count": len(new_steps)},
        )

    def _load_pattern(self, name: str) -> Optional[Dict]:
        path = os.path.join(os.path.dirname(__file__), "..", "..", "templates", "patterns.json")
        if not os.path.exists(path): return None
        try:
            with open(path, 'r', encoding='utf-8') as f:
                data = json.load(f)
                for p in data.get("patterns", []):
                    if p["name"].lower() == name.lower():
                        return p
        except: pass
        return None

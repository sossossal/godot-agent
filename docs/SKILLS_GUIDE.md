# Godot Agent 技能开发指南 (V1.4.0)

本系统已全面转向 **原子化技能 (Skills)** 驱动架构。`Role` 现在仅作为技能的逻辑容器，核心执行逻辑由 `BaseSkill` 子类承载。

## 1. 核心架构

- **BaseSkill**: 技能基类，定义元数据、输入参数模型 (Pydantic) 和执行逻辑。
- **SkillRegistry**: 技能注册表，负责技能的自动发现、实例化及参数映射。
- **ParameterMapper**: 智能参数映射器，支持 **Regex 规则匹配** 和 **LLM 语义提取** (Tool Calling)。

## 2. 如何创建一个新技能

### 第一步：定义参数模型
使用 Pydantic 定义技能所需的输入参数。

```python
from pydantic import BaseModel, Field

class MySkillParams(BaseModel):
    target_name: str = Field(description="目标名称")
    intensity: float = Field(default=1.0, description="强度系数")
```

### 第二步：编写技能逻辑
继承 `BaseSkill` 并实现 `execute` 方法。

```python
from ..base import BaseSkill, SkillMetadata

class MyCustomSkill(BaseSkill):
    metadata = SkillMetadata(
        name="my_custom_action",
        description="执行自定义 Godot 动作",
        category="dev",
        tags=["custom"]
    )
    input_model = MySkillParams

    def execute(self, task: Task, params: Dict[str, Any]) -> ToolResult:
        p = MySkillParams(**params)
        # 执行逻辑...
        return ToolResult(success=True, message=f"已处理 {p.target_name}")
```

### 第三步：注册技能
在 `agent_system/skills/__init__.py` 中添加注册语句。

```python
SkillRegistry.register(MyCustomSkill)
```

## 3. 智能参数映射机制

系统会自动尝试将用户的自然语言映射到技能参数：
1. **语义提取**：如果配置了 `llm.api_key`，系统会利用 LLM 的 Tool Calling 能力，将 Prompt 精准转化为参数 JSON。
2. **规则匹配**：如果 LLM 离线，系统会根据 `ParameterMapper` 中定义的正则表达式进行启发式提取。

## 4. 链式调用 (Skill Chaining)

用户的一个指令可以触发多个技能。例如：
> "创建一个名为 Battle 的场景并添加一个 Sprite2D 节点"

系统会识别出：
1. `create_godot_scene` (params: scene_name="Battle")
2. `inject_godot_node` (params: node_type="Sprite2D")

并自动按顺序编排执行。

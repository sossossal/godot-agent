# 在 IDE 中使用 Godot Agent

## 支持范围

当前仓库提供两类 IDE 入口:

- `ide_integration/vscode_agent.py`: 在终端里执行 Agent 命令并展示任务结果
- `ide_integration/godot_controller.py`: 打开或控制本地 Godot 编辑器

## VSCode 快速开始

### 1. 复制任务模板

把 `ide_integration/vscode_templates/tasks.json` 复制到你的 Godot 项目 `.vscode/` 目录。

### 2. 配置 Godot

```yaml
godot:
  executable_path: "C:/Godot/Godot_v4.x_stable_win64.exe"
  project_path: "D:/MyGodotProject"
```

如果你的 IDE 运行环境已经设置了 `GODOT` / `GODOT_EXE` / `GODOT_PATH`，或者 Godot 已加入 `PATH`，也可以把 `executable_path` 留空。

### 3. 直接从终端运行

```bash
python ide_integration/vscode_agent.py "生成 2D 玩家移动脚本"
python ide_integration/vscode_agent.py "为敌人创建巡逻 AI"
python ide_integration/vscode_agent.py "导出 Web 项目"
```

## `vscode_agent.py` 的当前行为

- 调用 `GodotAgentRouter.execute()`
- 按 `Task.status` 判断成功或失败
- 从 `Task.artifacts` 中提取最新脚本并做代码高亮展示
- 将序列化后的任务保存到 `.agent_result.json`

生成脚本时，实际文件已经由 Agent 保存到 `scripts/` 或 `scripts/ai/`，脚本会直接展示该路径。

## Godot 编辑器控制

```bash
python ide_integration/godot_controller.py status
python ide_integration/godot_controller.py open
python ide_integration/godot_controller.py create MainScene 2D
```

## 在 Python 中集成

如果你想在自己的工具里嵌入 Agent，按当前 `Task` API 写：

```python
from agent_system.router import GodotAgentRouter
from agent_system.models import TaskStatus

agent = GodotAgentRouter()
task = agent.execute("生成玩家移动脚本")

if task.status == TaskStatus.SUCCESS:
    script = next((a for a in task.artifacts if a.type == "script"), None)
    if script:
        print(script.path)
        print(script.content)
else:
    print(task.logs[-1] if task.logs else task.status.value)
```

## 常见问题

### 1. VSCode 任务无法运行

检查:

- `.vscode/tasks.json` 是否已复制
- 当前终端是否位于 `godot-agent` 根目录
- Python 依赖是否已安装

### 2. Godot 编辑器无法打开

先确认 `config.yaml` 中的 `executable_path` 正确。

### 3. 找不到生成脚本

代码类任务默认保存到:

- `scripts/`
- `scripts/ai/`

### 4. 场景任务失败

场景创建和测试依赖 Godot 引擎。没有 Godot 环境时，这类任务会失败并回滚。

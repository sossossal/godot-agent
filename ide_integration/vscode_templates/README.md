# VSCode 配置模板

把这个目录里的模板复制到 Godot 项目的 `.vscode/` 目录。

## 使用方式

### 1. 通过 VSCode 任务

打开命令面板:

```text
Ctrl+Shift+P -> Run Task
```

然后选择对应任务。

### 2. 通过集成终端

```bash
python ide_integration/vscode_agent.py "生成 2D 玩家移动脚本"
python ide_integration/godot_controller.py open
python ide_integration/godot_controller.py create MainScene 2D
```

## 当前行为

- `vscode_agent.py` 调用 Agent 并展示 `Task` 结果
- 最新任务会保存到 `.agent_result.json`
- 脚本类任务会从 `Task.artifacts` 中读取路径和代码内容
- 代码文件本身由 Agent 保存到 `scripts/` 或 `scripts/ai/`

## 环境变量

可选地在 VSCode 中设置:

```json
{
  "terminal.integrated.env.windows": {
    "GODOT_PROJECT_PATH": "D:/MyGame"
  }
}
```

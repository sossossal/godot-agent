# 快速开始指南

## 5 分钟上手

### 1. 安装依赖

```bash
pip install -r requirements.txt
```

### 2. 配置 Godot 路径

编辑 `config.yaml`:

```yaml
godot:
  executable_path: "C:/Godot/godot.exe"  # Windows
  # executable_path: "/usr/bin/godot"    # Linux
  # executable_path: "/Applications/Godot.app/Contents/MacOS/Godot"  # macOS
```

如果你已经把 Godot 放进环境变量，也可以把 `executable_path` 留空。支持这几种方式：

```bash
set GODOT=C:\Godot\Godot_v4.4-stable_win64.exe
```

- `GODOT` / `GODOT_EXE` / `GODOT_PATH`
- 或把 Godot 所在目录加入系统 `PATH`

`python -m agent_system.cli doctor` 现在会明确告诉你当前是通过 `config`、环境变量还是 `PATH` 命中的。

### 3. 先做环境自检

```bash
python -m agent_system.cli doctor
```

### 4. 规划或执行任务

```bash
# 只看计划
python -m agent_system.cli plan "创建一个玩家场景并生成移动脚本"

# Portal 中生成可编辑计划
# 先点击“规划”，编辑右侧步骤后再执行

# 直接执行
python -m agent_system.cli run "生成 2D 玩家移动脚本" -y
python -m agent_system.cli run "预览修复项目资源命名" -y
python -m agent_system.cli run "重命名类 PlayerController 为 HeroController" -y

# 交互式聊天
python -m agent_system.cli chat
```

## Python 用法

`agent.execute()` 现在返回 `Task` 对象，不再是旧版 `dict` 结果。

```python
from agent_system.router import GodotAgentRouter
from agent_system.models import TaskStatus

agent = GodotAgentRouter()
task = agent.execute("生成 2D 玩家移动脚本")

print(task.status.value)
print(task.message)

script = next((a for a in task.artifacts if a.type == "script"), None)
if task.status == TaskStatus.SUCCESS and script:
    print(script.path)
    print(script.content)
```

## HTTP API

启动服务:

```bash
python api_server/main.py
```

如需改到非默认端口，例如当前机器上更稳的 `8011`:

```bash
set GODOT_AGENT_API_HOST=127.0.0.1
set GODOT_AGENT_API_PORT=8011
python api_server/main.py
```

调用接口:

```bash
curl -X POST "http://127.0.0.1:8011/execute" \
  -H "Content-Type: application/json" \
  -d "{\"command\": \"生成玩家移动脚本\"}"
```

如果未设置环境变量，接口地址默认还是 `http://127.0.0.1:8000`。

Windows PowerShell 下，如果你想直接进入 live sandbox 联调状态：

```powershell
.\tools\run_live_sandbox_tests.ps1 -ApiPort 8011
```

如果需要逐步查看 API 或编辑器日志，再改用 `start_live_sandbox.ps1` 和 `stop_live_sandbox.ps1` 分步执行。

返回值是任务结构，重点字段是:

- `status`: 任务状态
- `message`: 用户可直接展示的摘要
- `steps`: 规划出的步骤
- `logs`: 执行日志
- `artifacts`: 生成的脚本、场景或内部脚本
- `context`: 额外上下文，例如 `release_url`

额外的计划接口:

- `POST /plan`: 返回可编辑的 `Task` 计划
- `POST /execute-plan`: 执行前端或外部系统修改过的步骤列表

## 常用命令

```text
创建一个名为 MainScene 的 2D 场景
生成 2D 玩家移动脚本
生成金币收集逻辑
生成库存系统
生成对话系统
为敌人创建巡逻 AI
生成警戒 AI
审计项目资源命名
预览修复项目资源命名
修复项目资源命名
重命名类 PlayerController 为 HeroController
重命名函数 move_player 为 move_character
重命名信号 jumped 为 landed
设置属性 speed 为 500
导出 Web 项目
运行场景测试
端到端测试 res://scenes/main_scene.tscn 并向右跳跃后截图
测试当前场景
重命名当前函数为 move_character
python -m agent_system.cli launch
```

资源审计命令 `审计项目资源命名` 会生成一份 Markdown 报告，当前覆盖:

- 文件和目录命名
- `.tscn` 头部字段，例如 `uid`、`load_steps`
- 重复场景 `uid`
- `.tres` / `.res` 头部字段，例如 `type`、`format`、`uid`
- 跨场景和跨资源文件的重复 `uid`
- `.tscn` 场景节点命名
- `.tscn` 中 `ext_resource` / `sub_resource` 声明与引用一致性
- `.tscn` 中 `ext_resource uid` 与目标场景 `uid` 的交叉核对
- `.tscn` 中 `ext_resource uid` 与目标 `.tres` / `.res` 的交叉核对
- `.tscn` 中重复的 `ext_resource path`
- `.tres` / `.res` 中 `ext_resource` / `sub_resource` 声明与引用一致性
- `.tres` / `.res` 中 `ext_resource uid` 与目标资源 `uid` 的交叉核对
- `.tres` / `.res` 中重复的 `ext_resource path`
- `.tscn` / `.tres` / `.res` 之间的引用环，报告会给出最短闭环路径和精确到 `文件:行号` 的断环建议
- 二进制 `.res` 的降级识别和跳过深度解析提示
- `.import` 文件及其 `source_file` 引用命名
- `.import` 中 `importer` / `type` / `source_file` 关键字段一致性
- `.import` 中 `dest_files` 与 `.godot/imported` 产物关系

报告会额外输出 `Errors / Warnings / Infos` 摘要，每条问题也会带 `[ERROR]`、`[WARNING]` 或 `[INFO]` 标签。通过 Portal 审计面板还可以直接查看源码片段，源码预览头部会显示脚本或场景上下文，并提供可点击 badge 重新精确打开，同时也能把问题条目发送到 Godot 编辑器中打开；`.gd` 会附带最近的 `class_name / func / signal` 上下文，`.tscn` 会按定位行尽量选中对应节点，并在同名节点场景下优先显示完整节点路径；如果命中实例化分支，还会显示实例源场景；`.import` 会优先跳到源资源，项目状态区会显示最近一次编辑器回执。

Portal 现在还带一个“产物中心”，会读取最近任务历史里的脚本、报告、场景、截图和发布产物，支持按类型筛选、内联预览、直接打开文件，以及把 `res://` 产物再次发送到 Godot 编辑器中打开。

Portal 还带一个“计划编辑器”，支持先规划、再改角色/顺序/步骤描述、最后执行编辑后的计划。

自动修复相关命令:

- `预览修复项目资源命名`
- `修复项目资源命名`

当前自动修复只覆盖低风险项，例如文件重命名、`.import` 同步、`source_file` 修正和 `res://` 文本引用更新；目录、节点、UID、引用环等仍需要人工处理。

安全重构命令:

- `重命名类 PlayerController 为 HeroController`
- `重命名函数 move_player 为 move_character`
- `重命名信号 jumped 为 landed`

端到端测试命令:

- `端到端测试 res://scenes/main_scene.tscn`
- `端到端测试 res://scenes/main_scene.tscn 并向右跳跃后截图`

## 能力边界

- 场景创建、场景测试、Web 导出依赖 Godot 引擎。
- 实时节点注入和属性修改依赖 Godot 编辑器插件联动。
- 无 Godot 环境时，相关任务可能失败并触发回滚。

## 进一步阅读

- `README.md`: 系统总览
- `docs/使用指南.md`: 更完整的使用说明
- `docs/IDE集成指南.md`: VSCode 与 Godot 集成
- `docs/TESTING_GUIDE.md`: 测试与回归验证
- `docs/制作路线图.md`: 从制作人视角整理的功能优先级

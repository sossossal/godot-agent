# Godot 多角色 Agent 系统 (V1.3.5)

一个基于 `Task` 编排、角色分工和 Godot 编辑器联动的游戏开发助手。

## 核心架构

- `Router`: 负责自然语言任务规划、多步执行、历史记录和失败回滚
- `Roles`: 按职责拆分为开发、代码、测试、AI、资源管理五类角色
- `CLI`: 提供 `doctor / plan / run / chat / launch / roles / history`
- `API Server + Plugin`: 在 Godot 编辑器在线时同步状态、截图和编辑器脚本注入

## Godot 查找顺序

系统会按这个顺序寻找 Godot 可执行文件：

1. `config.yaml` 里的 `godot.executable_path`
2. 环境变量 `GODOT` / `GODOT_EXE` / `GODOT_PATH`
3. 系统 `PATH` 中的 `godot` / `godot4`

其中环境变量既可以直接写可执行文件路径，也可以写 Godot 所在目录。`doctor`、`launch` 和 Portal 状态区现在都会明确显示当前命中来源；Portal 里还可以展开查看并复制完整可执行文件路径。
`python -m agent_system.cli doctor` 现在还会默认写出 `logs/reports/doctor_self_check.json`；如果有阻断项会返回非零退出码，并把明确修复动作写进结构化 `action_items`。

## 当前结果模型

系统的统一返回对象是 `Task`，无论来自 Python、CLI 还是 HTTP API，核心信息都围绕这些字段：

- `status`: 任务状态
- `message`: 适合直接展示给用户的摘要
- `steps`: 规划出的步骤
- `logs`: 执行日志
- `artifacts`: 生成物，例如脚本、场景、内部编辑器脚本
- `context`: 附加上下文，例如 `release_url`

## 能力边界

| 功能类型 | 功能名称 | 离线模式 | CLI 模式 | 联动模式 | 依赖说明 |
| :--- | :--- | :---: | :---: | :---: | :--- |
| 规划 | 任务拆解与编排 | ✅ | ✅ | ✅ | 仅逻辑运算 |
| 代码 | 生成 GDScript | ✅ | ✅ | ✅ | 仅文本生成 |
| 代码 | 安全重构类/函数/信号 | ✅ | ✅ | ✅ | 文本级重命名并自动备份 |
| 代码 | 自动备份与回滚 | ✅ | ✅ | ✅ | 文件系统操作 |
| 场景 | 创建 `.tscn` 场景 | ❌ | ✅ | ✅ | 需要 Godot 引擎 |
| 场景 | 实时注入节点 | ❌ | ❌ | ✅ | 需要 Godot 编辑器插件 |
| 测试 | 场景冒烟测试 | ❌ | ✅ | ✅ | 需要 Godot 引擎 |
| 测试 | 端到端冒烟脚本 / 输入回放 / 截图 | ❌ | ✅ | ✅ | 需要 Godot 引擎，截图为最佳努力 |
| AI | 加载行为模板 | ✅ | ✅ | ✅ | 模板库驱动 |
| 资源 | 资源命名审计与低风险自动修复 | ✅ | ✅ | ✅ | 文件系统、`.tscn` / `.tres` / `.res` 头部、引用、UID、引用环、`.import` 资源/配置/产物扫描 |
| 发布 | 导出 Web 项目 | ❌ | ✅ | ✅ | 需要 Godot 导出能力 |

说明：

- 场景创建、场景测试、Web 导出依赖 Godot 可执行文件。
- 如果你已经把 Godot 加入 `PATH`，或者设置了 `GODOT` / `GODOT_EXE` / `GODOT_PATH`，可以不再填写绝对 `executable_path`。
- 实时节点注入和属性修改依赖编辑器插件联动。
- 没有 Godot 环境时，相关任务可能失败并触发回滚。

## CLI 快速上手

```bash
# 1. 环境自检
python -m agent_system.cli doctor
python -m agent_system.cli doctor --json

# 2. 只看计划
python -m agent_system.cli plan "创建一个玩家场景并生成移动脚本"
python -m agent_system.cli plan "预览修复项目资源命名"
python -m agent_system.cli plan "重命名类 PlayerController 为 HeroController"
python -m agent_system.cli plan "端到端测试 res://scenes/main_scene.tscn 并向右跳跃后截图"

# 3. 直接执行
python -m agent_system.cli run "生成 2D 玩家移动脚本" -y

# 4. 交互式模式
python -m agent_system.cli chat

# 5. 查看历史与角色
python -m agent_system.cli history --limit 5
python -m agent_system.cli roles

# 6. P4 治理准入门禁
python -m agent_system.cli governance --change-type skill --evidence contract,layout,tests,docs,rollback,quality_gate --changed-path agent_system/skills/resource/demo_skill.py

# 7. P19 从零创建可玩原型
python -m agent_system.cli game-create --title "Demo Runner" --target-platform desktop,web --json
python -m agent_system.cli game-create --apply --overwrite --title "Demo Runner"
python -m agent_system.cli game-create --template-id topdown_action_2d --title "Arena Trial" --json
python -m agent_system.cli game-create --template-id arpg_2d --title "Relic Trial" --json
python -m agent_system.cli game-create --audit --write-report --json
python -m agent_system.cli game-create --review --write-report --json
python -m agent_system.cli roadmap --json

# 8. 分片执行非 live 回归，避免 release/P19 慢用例拖垮单条 pytest
.\tools\run_non_live_validation_shards.ps1 -PythonCommand D:\actions-tools\Python312\python.exe -Preview
.\tools\run_non_live_validation_shards.ps1 -PythonCommand D:\actions-tools\Python312\python.exe -Profile quick
.\tools\run_non_live_validation_shards.ps1 -PythonCommand D:\actions-tools\Python312\python.exe -Profile release -ContinueOnFailure
.\tools\run_non_live_validation_shards.ps1 -PythonCommand D:\actions-tools\Python312\python.exe -Profile release -SlowShardSeconds 120 -FailOnSlowShards -ContinueOnFailure
.\tools\run_non_live_validation_shards.ps1 -PythonCommand D:\actions-tools\Python312\python.exe -Profile customer -SlowShardSeconds 60
.\tools\run_non_live_validation_shards.ps1 -PythonCommand D:\actions-tools\Python312\python.exe -Shard api,p19_cli_contracts
.\tools\run_non_live_validation_shards.ps1 -PythonCommand D:\actions-tools\Python312\python.exe -ContinueOnFailure

# 8.1 本地 release-live gate 预检，不执行 live 步骤也能提前发现环境缺口
.\tools\run_release_live_gates_locally.ps1 -PythonCommand D:\actions-tools\Python312\python.exe -Preflight

# 8.2 PR / merge / release / customer gate 总控入口
.\tools\run_pr_release_gate.ps1 -Stage release -Mode preflight -PythonCommand D:\actions-tools\Python312\python.exe
.\tools\run_pr_release_gate.ps1 -Stage release -Mode preflight -PrepareReleaseFixture -RestorePreparedFixture -PythonCommand D:\actions-tools\Python312\python.exe
.\tools\run_pr_release_gate.ps1 -Stage pr -PythonCommand D:\actions-tools\Python312\python.exe
.\tools\run_pr_release_gate.ps1 -Stage release -PythonCommand D:\actions-tools\Python312\python.exe -ContinueOnFailure
.\tools\run_pr_release_gate.ps1 -Stage release -PythonCommand D:\actions-tools\Python312\python.exe -FailOnSlowShards -ContinueOnFailure

# 8.3 GitHub Actions 已接入 pr-release-gate：PR 默认跑轻量 preflight，push 默认跑 merge/preflight
# merge/release/customer 的 preflight 会自动准备轻量 release fixture；只有 full gate 会安装完整 requirements.txt

# 8.4 客户试用证据包：汇总 doctor、customer gate、readiness、命令清单和复跑脚本
.\tools\export_customer_trial_bundle.ps1 -PythonCommand D:\actions-tools\Python312\python.exe -GateMode preflight -ContinueOnFailure
.\tools\export_customer_trial_bundle.ps1 -PythonCommand D:\actions-tools\Python312\python.exe -GateMode preflight -SyncPluginBeforeDoctor -PrepareReleaseFixture -RestorePreparedFixture -ContinueOnFailure

# 9. 启动 Godot 编辑器
python -m agent_system.cli launch
python -m agent_system.cli launch --scene res://scenes/Main.tscn
```

如果你要把当前仓库作为 clean machine 首次安装入口，优先使用：

```powershell
.\tools\bootstrap_clean_machine.ps1 -Preview
.\tools\bootstrap_clean_machine.ps1
```

默认会创建 `.venv`、安装 `requirements.txt`、同步插件副本并执行 `doctor`；其中 `doctor` 会先落盘 `logs/reports/doctor_self_check.json`，bootstrap 再把该报告路径和修复动作摘要写进 `logs/reports/clean_machine_bootstrap.json`。如需把 targeted non-live smoke 一起纳入首次验收，可追加 `-IncludeSmoke`。这份 bootstrap 报告现在也会被 `Release Promotion Evidence / Review Bundle` 直接复用。支持边界和分发说明见 `docs/支持矩阵与分发说明.md`。

如果目标是让试用客户独立完成安装、任务执行和验收，先发 `docs/客户操作手册.md`。如果目标是验证真实客户是否愿意付费，再按 `docs/真实场景变现测试指南.md` 执行。变现测试指南把测试拆成独立开发者原型、小团队交付切片、API/MCP 集成三类场景，并给出执行命令、验收证据、访谈问题和定价实验。项目完成状态、LIVE 证据和分片回归入口见 `docs/项目完成验收报告.md`。

## Python 用法

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

注：

- `Task` 同时提供 `message` 属性和 `get_message()` 方法。
- HTTP API 会额外直接返回 `message` 字段。
- `审计项目资源命名` 会同时检查文件/目录命名、`.tscn` 的 `uid/load_steps`、`.tres/.res` 的 `type/format/uid`、跨场景和跨资源文件的重复 `uid`、场景节点命名，以及 `.tscn/.tres/.res` 中 `ext_resource/sub_resource` 的声明、引用、UID 交叉核对、重复 `ext_resource path` 和引用环；资源环会给出最短闭环路径，以及精确到 `文件:行号` 的断环建议。对二进制 `.res` 会降级标记为“已识别但跳过深度解析”。另外还会检查 `.import` 的 `importer/type/source_file/dest_files` 一致性，并在 `context` 中返回 `error / warning / info` 分级统计。
- `预览修复项目资源命名` 会生成低风险自动修复预览报告；当前自动修复范围包括文件重命名、`.import` sidecar 同步、`source_file` 修正、`res://` 文本引用更新，以及可安全推断的 `.godot/imported` 产物重命名。目录、节点、UID、引用环等高风险问题仍保留为人工处理项。
- `重命名类 / 函数 / 信号 ...` 会走代码角色的安全重构入口，自动备份并更新 `.gd/.tscn/.tres/.res/project.godot` 中的常见文本引用。
- 如果编辑器在线，`Router` 还会把当前场景、当前脚本和 Inspector 资源转成执行提示。例如没有显式 `res://` 路径时，`测试当前场景` 会自动落到当前打开的场景；`重命名当前函数为 move_character` 会根据当前脚本光标位置推断函数名并走安全重构。
- API Server 现在支持 `POST /editor/launch` 主动拉起 Godot 编辑器；`/execute`、`/execute-plan` 和 `/editor/open-resource` 也支持 `auto_launch_editor=true`，在编辑器离线时自动启动并等待插件上线后再继续执行编辑动作。
- Godot 实时桥接现在额外提供 `POST /editor/operation` 类型化操作入口，支持 `get_scene_tree / select_node / create_node / set_node_property / delete_node / save_scene / save_scene_as / reload_scene / duplicate_node / reparent_node / rename_node / move_node_order / batch_set_properties / batch_create_nodes / attach_script / detach_script / instantiate_scene`。每次操作都会返回带 `audit.rollback_anchor` 的结构化 `editor_event`，让 Agent 或 Portal 在编辑器内直接读场景树、调整节点结构、批量改属性、挂脚本、实例化场景并保存重载，不再必须拼接临时 GDScript。
- 历史接口现在额外支持 `POST /history/{task_id}/feature-review`，可把功能状态更新为 `approved / returned / pending_review / pending_acceptance`，并把评审意见写回任务历史。
- 功能验收上下文已升级到 `feature_context 1.5`：`Task.context`、历史记录、发布摘要和 Review Bundle 会统一保留 `dependency / eta / validation_method / blockers / artifact_links / external_links`，评审历史会记录 `reviewer / review_round / required_followups`，并用 `feature_lifecycle_events` 记录 retry / rollback 等流程事件；`returned` 评审现在还会把 `required_followups` 反向生成带 `review_followup` metadata 的待执行步骤，Portal 的计划评审区也可直接编辑协作字段、查看关联产物和功能时间线。
- `POST /history/{task_id}/feature-review` 现在也会写入 feature timeline；退回状态会把评审意见或显式 blockers 带入 `feature_context.blockers`，Review Bundle 会把 `returned` 和 feature blockers 转成阻断项。
- Review Bundle Markdown 现在会展开 `Feature Timeline`、`Signoff Records`、`Review Follow-up Actions`、`Validation Records`、`Risk Summary` 与 `External Review Links`，并通过 `release_review_bundle 1.5` 自动把 `changed_paths` 分类成 code / scenes / resources / docs / other，从 required/provided/missing signoffs 生成逐角色审批记录，从 blocking/warning/signoff/validation/risk 缺口生成带 `owner_hint / dependency / eta / validation_method / blockers` 的复审行动，从 acceptance checklist、QA evidence 和 artifact links 生成验证记录，从 feature risk、known issues、feature blockers、blocking/warning items 生成风险摘要，直接列出 feature blockers、review/retry/rollback 事件、评审人/轮次/followups、审批状态、改动范围、验证依据、风险面和 PR/CI/截图等外部依据，减少审阅时反查历史 JSON。
- `GET /history` 现在支持 `limit / offset / feature_status / feature_id / owner` 查询参数，服务端会先过滤再分页，方便 Portal 直接按功能条目或责任人拉取历史任务，并继续翻看更早的记录。
- `Task.context`、功能评审历史、`release_summary` 和 `release_quality_gate` 现在开始走统一契约层，结构里会附带稳定的 `contract_versions` 或 `schema_version`，方便后续 Portal、CLI、MCP 和导出产物复用同一套字段。
- API 现在额外提供 `GET /contracts/versions`，可返回当前 `feature_context / quality_gate / release_summary / release_candidate_checklist / build_run_matrix / scene_ownership_board / release_promotion_plan / skill_result / balance_analysis / balance_version_compare / telemetry_summary / performance_summary / presentation_profile / liveops_profile / game_creation_profile / scene_graph_audit / game_creation_review / game_creation_replay / game_creation_template_migration / scene_graph_snapshot / platform_delivery_profile / outsource_delivery_gate / asset_review_workflow / governance_* / production_* / agent_provider_compatibility` 的版本目录和 normalize/migration entrypoint，方便 Portal 或外部集成在接 schema 前先拿一份稳定合同清单。
- 受管文件树现在开始走统一命名与落点规则：`data_tables/`、`scripts/`、`scenes/`、`logs/`、`api_server/static/dist/` 等目录会由布局校验器约束；`doctor` 也会检查受管目录里的命名和落点是否漂移，数据表导入和发布导出在路径不符合规范时会直接失败。
- 项目初始化现在开始走模板注册中心：内建 `platformer / topdown_action / arpg / roguelike / tower_defense / visual_novel / survival_crafting` 模板，`init_game_blueprint` 会把模板快照写入蓝图、自动建立推荐目录骨架，并通过 `GET /genre-templates` 对外暴露统一模板清单。
- 主项目现在已有项目级模板覆盖样本：`agent_templates/genres/platformer_production.json`，用于验证 production 场景下的模板来源、推荐目录、数据表、性能预算和截图 diff 预算。
- 模板注册中心现在额外提供 marketplace manifest：`GET /genre-templates/marketplace` 会返回模板来源、安装状态、校验问题和默认模板，方便后续做模板市场、项目覆盖模板和版本迁移。
- P2 迁移兼容层已落地为 `agent_system/migrations/`，`GET /migrations/status` 会检查模板 manifest、数据表 schema、遥测目录和性能基线目录，`POST /migrations/apply` 只创建缺失的受管目录，不会自动重写用户数据。
- API 现在额外提供 `GET /quality/dashboard`，统一汇总 contract health、managed layout、template marketplace、skill coverage、telemetry health、performance budget pass rate 和 migration compatibility，供 Portal、CLI、MCP 或外部 CI 复用。
- P3 治理准入层已落地为 `agent_system/tools/governance.py`：`GET /governance/policy` 返回变更类型、必需 evidence 和路径策略，`POST /governance/admission` 会按变更类型检查 evidence、changed paths、质量面板和迁移状态。
- P4 治理执行层现在会把准入结果变成可用于 CI 的门禁结果：`POST /governance/enforce` 和 `python -m agent_system.cli governance` 都会输出 `passed / should_block / exit_code / blocking_checks`，支持 `strict / advisory` 模式和 `fail_on_warnings`。
- P5 生产规模验证已落地为 `agent_system/tools/production_scale.py`：`GET /production/scenarios` 暴露 `vertical_slice_2d / content_pipeline / release_candidate` 场景目录，`POST /production/validate` 和 `python -m agent_system.cli production` 会统一检查 required paths、template registry、quality dashboard、migrations 和 governance evidence。
- P15 首个交付切片已落地为 `agent_system/tools/release_candidate.py`：`GET /release-candidate/checklist` 和 `POST /release-candidate/checklist` 会把 `release_manifest / release_notes / qa_gate_report / quality_gate / performance_gate / telemetry_gate / rollback / production_gate` 压成统一 `release_candidate_checklist` contract，并根据 `strict|advisory` 与 `fail_on_warnings` 给出 `should_block`。
- P6 多 Agent/API 兼容矩阵已落地为 `agent_system/tools/agent_compatibility.py`：`GET /agent-compat/providers` 返回 Codex、Gemini、OpenAI API、Claude、local LLM 的 profile，`/agent-compat/matrix` 会检查 contracts、skills、stdio/remote MCP、API surface、governance、production readiness、file tree 和输出 handoff contract。
- 主链 skill 现在开始走统一结果基线：会把 `schema_version / validation / rollback / quality_gate / artifact metadata` 收敛到同一份 skill result envelope，并写入 `Task.context.last_skill_result` 与 `skill_runs`；当前已先接到项目初始化、数据表管线、发布链路，以及 `generate_movement_script / create_godot_scene / attach_script_to_node / smoke_test_scene / e2e_test_scene / manage_input_mapping / inject_godot_node / auto_layout_ui / configure_physics_collision / manage_signal_bus / wire_signal_connection / instantiate_scene_prefab / setup_3d_environment / inject_3d_primitive / inject_vfx_particle / apply_tween_animation / generate_dialogue_system / generate_ai_behavior / quick_capture_scene / run_scenario_chain_test / auto_debug_runtime / audit_logic_errors / audit_godot_resources / preview_resource_audit_fixes / apply_resource_audit_fixes / self_heal_project`。
- 剩余 architect 主链也已经收进同一 contract：`plan_game_feature / define_game_flow / set_ui_style / export_blueprint_doc / audit_project_consistency / apply_design_pattern / manage_blueprint_snapshots` 现在同样会写入 `last_skill_result / skill_runs`，并带上统一的 `validation / rollback / artifact summary`。
- 发布链路现在会为每次导出生成 `build_id / version / channel / release_summary`，并额外产出 `release_notes.md` 与 `release_manifest.json`；Web 导出会同步 latest 入口到 `/portal/dist/index.html`，同时保留版本化目录作为回滚锚点。
- 资源管理角色现在支持 `数据表模板 / Schema 校验 / diff 预览 / 导入落盘`。当前内建表类型包括 `dialogue / quest / enemy / loot / localization`，默认输出到项目根目录下的 `data_tables/`；Portal 里也新增了独立数据表编辑器，可直接读取、套模板、编辑行、预览 diff 和保存。
- 资源管理角色现在还支持 `数值平衡分析`：`analyze_game_balance` 会对 `enemy / quest / loot` 三类表做交叉检查，输出 `balance_analysis` 结构化摘要、风险分级和 Markdown 报告，并把 `score / issue_count / warning_count / table_types` 写回 `Task.context`。当任务上下文传入 `balance_baseline_*` 行或表路径时，它还会生成 `balance_version_compare` contract/report，对比 baseline 与 candidate 的 score、issue、warning 和 metric drift；传入 `balance_simulate_combat=true` 时，还会执行可复现战斗仿真，输出 TTK、承伤、存活边际、`combat_simulation.json` 和 Markdown 报告；传入 `balance_audit_growth_curve=true` 时，会审计 enemy power 与 quest reward 的成长点、斜率和异常段，输出 `growth_curve_audit.json` 与 Markdown 报告。仿真和曲线指标都会并入 `last_skill_result.quality_gate`。
- 资源管理角色现在还支持 `遥测回流`：`manage_game_telemetry` 提供 `template / validate / analyze / apply` 四段式链路，会维护 `telemetry/event_catalog.json` 和 `telemetry/sessions/*.jsonl`，并输出 `telemetry_summary 1.4`，其中已包含 `retention_cohorts / funnel_breakdown / retention_funnel_dashboard / retention_funnel_trend_dashboard / liveops_impact_dashboard / crash_taxonomy / crash_clusters / crash_regression_dashboard / pii_violation_count / privacy_gate_passed`。API 额外提供 `GET /telemetry/crash-clusters`、`GET /telemetry/crash-dashboard`、`GET /telemetry/retention-dashboard`、`GET /telemetry/trends` 和 `GET /liveops/impact-dashboard`；Portal 的 `遥测回流` 与 `运营配置 / LiveOps` 面板现在可直接导出留存漏斗、趋势和 LiveOps 影响报告。
- 资源管理角色现在还支持 `性能基线与画像分析`：`manage_game_performance` 提供 `capture / baseline / validate / analyze` 链路，会用 Godot headless 采集 profile，把性能基线写入 `tests/baselines/performance/`，把 profile 快照写入 `logs/test_artifacts/`，并输出 `performance_summary 1.1`、预算校验、基线回归、`frame_breakdown / memory_trend` 和 Markdown 报告。它还支持 `screenshot_baseline_path / screenshot_candidate_path` 截图基线比对，计算 `screenshot_diff_ratio` 并复用 `max_screenshot_diff_ratio` 预算；也支持 baseline/candidate `memory_trend` 回归对比，输出 `memory_regression`、growth/peak/avg delta，并复用 `max_memory_growth_mb` 等预算。API 额外提供 `GET /performance/dashboard`；Portal 的 `性能分析` 面板可直接编辑 `baseline_metrics / profile_metrics / budget_overrides` JSON，执行基线写入、校验、分析和画像导出。`Build / Run Matrix` 也会读取最新 `performance_profile_*.json` 生成 `runtime_performance_sampling` 默认 lane，把运行时采样状态纳入发布前矩阵。
- 资源管理角色现在还支持 `LiveOps 运营配置`：`manage_liveops_pipeline` 提供 `template / validate / preview / apply` 四段式链路，当前先覆盖 `remote_config / experiment_catalog` 两类 manifest，统一写入 `liveops/remote_config.json` 与 `liveops/experiments.json`，并输出 `liveops_profile`、active entry 数、rollout 数、variant 数和 target metric 数。Portal 现在也新增了 `运营配置 / LiveOps` 面板，可直接切换类型、加载模板、编辑 `entries` JSON、模板落盘、校验、预览和应用。
- 资源管理角色现在还支持 `平台交付 / Savegame baseline`：`manage_platform_delivery` 提供 `template / validate / preview / apply` 四段式链路，统一维护 `deployment/platform_delivery.json`，覆盖导出平台条目、savegame schema、服务开关和多人模式配置，并通过 `GET /platform-delivery/profile` 与 `POST /platform-delivery/manage` 暴露给 Portal、CLI、MCP 和外部 Agent。Portal 现在也新增了 `平台交付 / Savegame` 面板，可直接加载模板、校验、预览并应用 baseline。
- 主项目现在附带可回归样本：`telemetry/event_catalog.json`、`telemetry/sessions/vertical_slice_sample.jsonl` 和 `tests/baselines/performance/vertical_slice_sample_performance.json`，其中 telemetry 样本覆盖 5 个 session、`D1 / D3 / D7 retention`、funnel breakdown、`native` crash taxonomy、`stack_native_sigsegv_player_controller` crash cluster 和隐私字段约束，性能样本覆盖 `scene_load_ms / fps / memory_peak_mb / draw_call_count / node_count / texture_memory_mb / frame_spike_ms / screenshot_diff_ratio`。
- 资源管理角色现在还支持 `美术资产 intake`：`manage_art_asset_pipeline` 提供 `template / validate / preview / apply` 四段式链路，当前已覆盖 `texture / ui / spritesheet / material / vfx / model / aseprite / spine / substance / outsource` 十类 schema，会约束目标目录、文件名、扩展名、尺寸/帧图规则、sidecar 依赖、LOD、texture set、交付版本与授权字段，并将 manifest 统一写入 `assets/manifests/`；spritesheet/aseprite profile 还会生成 `atlas_plan`，包含 frame grid、atlas path、frame count 和预算状态；material/substance profile 会生成 `material_link_audit`，识别 albedo/normal/orm 等贴图通道、缺失项和链接数量。前端、CLI、MCP 与外部 Agent 现在可通过 `GET /art-assets/profiles` 和 `POST /art-assets/manage` 直接读取和执行同一份 intake contract。Portal 也新增了独立 `美术资产 Intake` 面板，可直接读取 profile、加载模板、模板落盘、校验、预览并导入受管资产。
- P15 第二个交付切片已落地为 `agent_system/tools/outsource_delivery.py`：`GET /outsource-delivery/gate` 和 `POST /outsource-delivery/gate` 会复用 `assets/manifests/outsource_assets.json` 与 `assets/packages/outsource/`，统一检查 manifest contract、package_root、关键 metadata、license scope、target package 可用性、source traceability 和预算偏差，并输出 `outsource_delivery_gate` contract。Portal 现在也新增了 `外包交付 Gate` 面板，可直接填写 manifest/package root/license 白名单并执行 Gate。
- P15 第三个交付切片已落地为 `agent_system/tools/asset_review.py`：`GET /asset-reviews/workflow` 和 `POST /asset-reviews/manage` 会复用 art intake manifest 和 `assets/manifests/asset_review_board.json`，统一维护 `pending_review / approved / returned` 状态、reviewer、review_note 和 review board 一致性，并输出 `asset_review_workflow` contract。该 workflow 现在还会生成 `provenance_summary`，统计 source/target/source_tool/license/dependency 覆盖率和缺口资产，用于追踪资源来源与授权完整性。Portal 现在也新增了 `资产评审` 面板，可按资产类型读取评审状态、批量通过/退回或重置待评审。
- P15 第四个交付切片已落地为 `agent_system/tools/build_run_matrix.py`：`GET /build-run/matrix` 和 `POST /build-run/matrix` 会把 `deployment/platform_delivery.json`、P5 `production_scenarios`、`release_candidate_checklist`、运行时性能采样和本地 `non-live / browser / live / remote MCP` 验收 lane 收敛到同一份 `build_run_matrix` contract，统一返回 `rows / blocking_rows / warning_rows / default_sequence / should_block`。Portal 现在也新增了 `Build / Run Matrix` 面板，可直接查看 build target、production gate、RC checklist、`runtime_performance_sampling` 和推荐执行顺序。
- P15 第五个交付切片已落地为 `agent_system/tools/scene_ownership.py`：`GET /scene-ownership/board` 和 `POST /scene-ownership/manage` 会扫描 `scenes/**/*.tscn` 与 `agent_modules/scenes/**/*.tscn`，把 `owner / feature_id / lock_state / source_manifest_path / orphan_count` 收敛到统一 `scene_ownership_board` contract，并把持久化 board 固定写到 `scenes/scene_ownership_board.json`。Portal 现在也新增了 `场景归属 / 锁定` 面板，可直接认领锁定、设为共享或释放场景，避免多人协作时靠聊天记录约定场景归属。
- 发布控制面现在还额外沉淀了一份显式 `Release Capability Registry`：`deployment/release_capability_registry.json` 会把当前 release control plane 的主要能力按 `tool / command / gateway_method / hook`、`risk_level`、`sandbox_profile`、`artifact_contracts` 和 `owners` 分类，后端通过 `GET /release-capability-registry` 与 `GET /release-capability-registry/report` 暴露同一份 contract，Portal 也新增了 `Release Capability Registry` 面板，可直接查看当前哪些能力默认开启、哪些属于 optional heavy runtime、哪些要求 actor/request_auth；凡是声明消费 `release_live_ci_summary` 的能力都会同时声明 `release_artifact_manifest`，只读 gateway 面还会列出 `/release-artifact-manifest` 入口，registry 工具和 contract normalizer 都会把漏配项降为 warning，避免发布链路里“入口存在但边界隐式”的问题。
- 在 `Release Capability Registry` 之外，发布控制面现在还补了一层只读 `Release Capability Policy` snapshot：`GET /release-capability-policy` 与 `GET /release-capability-policy/report` 会在同一份 capability taxonomy 之上，再按 `route_kind / actor_id / target_channel / target_environment` 计算本次调用是 `passed / warning / blocked / skipped`，并把 `authorization`、`request_auth_posture`、route profile、artifact contracts、entrypoints 和 denial reasons 一起暴露出来；registry capability 本身的 warning/blocked 也会继续传递成 policy warning/blocked，避免漏配 artifact boundary 的能力被误判为可调用。Portal 也新增了 `Release Capability Policy` 面板，因此“能力存在”和“这次允不允许调用”现在已经显式拆开，而不必继续靠 release gate 报告反推控制面策略。
- 发布控制面现在还新增了聚合 `Release Delivery Readiness`：`GET /release-delivery-readiness` 与 `GET /release-delivery-readiness/report` 会把“外部 identity/session/secret rotation 边界”“真实 self-hosted Windows runner 上的 `.github/workflows/release-live-gates.yml` 证据”“外部分发 installer/signing/publish/receipt 链”三条剩余主线收成同一份可交付级 closeout snapshot。Portal 也新增了同名面板，可直接看到三类 component、阻断项和带 `owner_hint / dependency / eta / validation_method / blockers` 的 next actions，而不必继续分别翻 `request_auth_identity_audit`、`release_live_ci_summary` 和 `release_distribution_bundle`。
- `Release Delivery Readiness` 的 distribution closeout 现在会把外部分发拆成可分派的 `distribution_signing_handoff / distribution_publish_handoff / distribution_publish_receipts` 子行动；缺失或失败的 publish target receipt 会进入 action blockers，Markdown 报告、Portal next actions、Release Promotion evidence/review/deployment 报告、Release Execution status/report 和 Portal Execution 面板都能直接看到签名、发布和回执分别卡在哪。
- 第三阶段第一刀也已落地为 `agent_system/tools/release_runtime_assembly.py`：`release_live_ci_summary` 现在会额外收一份结构化 `runtime_assembly`，把 `route_kind / route_id / session_id / invocation_source / actor_id / enabled_capabilities / warning_capabilities / denied_capabilities / sandbox_profile / artifact_contracts / entrypoints / identity_boundary / runner_profile` 压成同一份快照；这份对象会继续进入 `release_promotion_plan`、`release_execution_status`、`release_promotion_history`、GitHub step summary Markdown 与 Portal `Release Live CI` 面板，后两者会直接显示 capability contract/entrypoint 摘要，因此 registry/policy 发现的 artifact boundary warning 会一路保留到 runtime assembly 证据面，contract normalizer 也会从 capability 列表派生 warning/blocked 汇总，复盘 fixed runner 或 portal/local replay 差异时，不必再同时翻 capability policy、identity boundary 和 runner baseline 三份报告。
- P16 已完整落地为 `agent_system/tools/release_promotion.py`：`GET /release-promotion/plan` 和 `POST /release-promotion/plan` 会把 `release_candidate_checklist / build_run_matrix / agent_provider_compatibility / scene_ownership_board / signoff_gate / evidence_bundle / review_bundle / deployment_rehearsal / rollback_rehearsal` 收敛到统一 `release_promotion_plan` contract，面向 `qa / staging / release` 目标输出 `promotion_steps / missing_signoffs / selected_scenario_ids / selected_provider_ids / should_block`。同时还新增 `GET /release-promotion/review-bundle`、`GET /release-promotion/evidence-report`、`GET /release-promotion/deployment-rehearsal` 和 `GET /release-promotion/rollback-rehearsal` 四个导出端点，Portal 的 `Release Promotion` 面板现在可直接导出 Review Bundle、Evidence Bundle、Deployment Rehearsal 和 Rollback Rehearsal 报告到源码预览区。
- 发布链路现在额外沉淀 `release_qa_evidence`：`release_summary` 会统一记录 smoke、断言型 QA、screenshot diff、截图路径和关键指标，`Release Candidate / Promotion Evidence / Review Bundle` 都会直接复用这份结构化 QA 证据。
- `clean_machine_bootstrap.json` 现在也会进入 `Release Promotion Evidence / Review Bundle`；`release` 目标缺失这份安装验证报告时会直接阻断 promotion evidence。
- `full_live_validation.json` 现在也会进入 `Release Promotion Evidence / Review Bundle / Release Execution Report`；`release` 目标缺失这份 live 验证报告时会直接阻断 promotion evidence 与 deployment rehearsal。
- `logs/reports/release_live_ci/release_live_ci_summary.json` 现在也会进入 `Release Promotion plan / Evidence / Review Bundle / Deployment Rehearsal / Release Execution Report`；`release` 目标下如果这份 live CI 摘要缺失，promotion checklist、evidence artifact 和 deployment preflight 会直接把它当成 blocker，而 `human_signoffs` 仍保持和自动化 `ci_gate` 分开记录。
- `release_live_ci_summary` 里的 `workflow_steps` 现在也会继续进入 `Release Promotion` / `Release Execution` 的结构化 payload 和 Markdown 报告，不再只停在 live CI artifact 自身；Portal 的 `Release Live CI` 面板也会直接显示这些 step 级诊断，方便从 UI 看出 fixed runner 是卡在 baseline、distribution 还是 full live validation。
- `release_live_ci_summary` 现在还会附带结构化 `event_stream`，把 `run_started / step_finished / lane_reported / gate_evaluated / run_finished` 固化到 `release_live_ci_events.json`；这份时间线会继续进入 `Release Promotion / Release Execution / Release Promotion History` 报告、Portal `Release Live CI` 面板和 `GET /release-live-ci/events`，让 fixed runner 排障不再只有最终 gate 结论，也能直接看到最新事件序列。
- P19 初版游戏创建向导已落地为 `agent_system/tools/game_creation_wizard.py`：`GET /game-creation/templates`、`POST /game-creation/plan`、`POST /game-creation/apply`、`POST /game-creation/audit-scene-graph` 与 `POST /game-creation/review` 会把从零创建 `platformer_2d / topdown_action_2d / tower_defense_2d / arpg_2d / roguelike_2d / visual_novel_2d / survival_crafting_2d` 可玩原型收成 `game_creation_profile` contract，把生成后的 `.tscn/.gd` 或 Godot 插件实时 `scene_graph_snapshot` 对照审计收成 `scene_graph_audit` contract，再把验收清单、模块状态、数据表检查和审计摘要收成 `game_creation_review` contract；计划 contract 包含 `module_plan / skill_binding_plan / block_diagram / godot_response_map`，块状结构图会从模块依赖生成，并把 `generate_movement_script / create_godot_scene / wire_signal_connection / smoke_test_scene` 等项目 Skills 绑定到各模块的职责与约束上，同时写出 `docs/game_creation_design.md`。`tower_defense_2d` 会生成 Placement Cursor、Tower、Enemy wave、Base health、resources HUD 与 `place_tower` 输入；`arpg_2d` 会生成 Hero、Quest Relic、Enemy chase、Quest/Action HUD、`attack` 和 `dodge` 输入；`roguelike_2d` 会生成 DungeonRoom、Stairs、Loot pickup、Enemy chase、Depth/Loot/Action HUD、`attack` 和 `descend` 输入；`visual_novel_2d` 会生成 Stage、Reader controller、Choice、Npc portrait、Dialogue/Affinity HUD、`advance_dialogue` 和 `select_choice` 输入；`survival_crafting_2d` 会生成 Field、Resource、Campfire、Survivor、Wood/Hunger/Health HUD、`gather` 和 `craft` 输入。`game-create --apply` 写入前会对 `scripts/ / scenes/ / data_tables/` 受管输出执行 `ProjectLayoutValidator`，并把 `layout_checks / layout_passed / layout_blocking_checks` 写入 `game_creation_profile`，非法路径会在落盘前阻断；随后还会执行 `game_creation` 治理准入强校验，要求 `contract / layout / schema / preview_or_diff / quality_gate / rollback / tests / docs` evidence，并把 `governance_enforcement / governance_admission / governance_passed / governance_blocking_checks` 写入 manifest。Portal 已新增“游戏创建向导”面板、“审计场景树”和“生成验收摘要”按钮，Godot 插件会在 editor state 中回传完整节点树，API 也提供 `POST/GET /plugin/scene-snapshot`；`scene_graph_audit` 和 `game_creation_review.audit_summary` 现在会显式记录 `live_snapshot_used / live_snapshot_source / live_snapshot_scene_path / live_snapshot_node_count`，用于区分静态文件审计和真实编辑器监控证据。CLI 已新增 `python -m agent_system.cli game-create --audit --write-report` 与 `--review --write-report`，stdio/remote MCP 也新增 `godot_create_game_plan`、`godot_apply_game_plan`、`godot_audit_game_scene_graph` 与 `godot_review_game_creation`，可先生成结构化计划，再选择写入脚手架，并输出 `scene_graph_audit.json`、`game_creation_review.json` 和 `docs/game_creation_review.md` 作为监控和人工验收报告；`tests/test_live_sandbox.py::test_8_p19_scene_graph_snapshot_reaches_health_monitor` 会在真实 Godot editor live sandbox 中验证场景树快照进入 `/health` 监控面；`tests/test_live_sandbox.py::test_9_p19_runtime_playability_smoke_generated_tower_defense` 会生成 `tower_defense_2d`、打开主场景、等待 live snapshot、触发当前场景截图运行检查，并用 live snapshot 生成验收 review；`tests/test_live_sandbox.py::test_10_p19_execute_replay_generates_runtime_screenshot` 会调用 `/game-creation/replay` 的 `execute_replay=true / promote_baseline=true` 固定 lane，验证 headless replay 实际执行、报告、runtime screenshot 产物和 baseline promotion。
- P19 计划 contract 现在还会生成 `input_replay_plan` 与 `golden_screenshot_plan`，`game-create --apply` 会额外写出 `data_tables/game_creation/input_replay.json`。Review 会把 `gameplay_balance` 和 `game_creation_input_replay` 两类数据表分别校验，确保每个模板都留下可回放输入步骤、截图捕获目标、baseline 路径、允许 diff 阈值和必要节点约束。
- P19 现在新增 `game_creation_replay` contract、`POST /game-creation/replay` 和 `python -m agent_system.cli game-create --replay --write-report`：它会读取 `input_replay.json`，校验 `project.godot` 输入动作、Main 场景和 golden screenshot 必需节点，并生成 `logs/test_artifacts/game_creation/input_replay_<template>.gd` headless 回放脚本与 `data_tables/game_creation/input_replay_run.json` 报告；传入 `execute_replay=true` 或 CLI `--execute-replay` 时，会调用 Godot headless 实际执行脚本，并记录 stdout/stderr、执行错误和截图产物是否生成；传入 `promote_baseline=true` 或 CLI `--promote-baseline` 时，会把 runtime screenshot 显式登记到 `tests/baselines/screenshots/game_creation/` 下，并在报告里记录 baseline source/path/promoted_at。
- `game_creation_replay` 的截图脚本现在优先捕获 viewport；在无显示的 Godot headless runner 中若 `ViewportTexture` 为空，会生成确定性的 `fallback_headless` PNG 证据并在 stdout 写入 `REPLAY_SCREENSHOT_CAPTURE=fallback_headless`。报告会把该 marker 标准化为 `screenshot_capture_mode`，并输出 `replay_render_mode / viewport_baseline_status / viewport_baseline_ready / viewport_baseline_message`，让 Agent 能区分 headless 证据和真正可作为 golden screenshot 的 viewport 证据。CLI 可用 `game-create --replay --execute-replay --replay-render-mode viewport --promote-baseline --write-report` 显式请求非 headless `--script` 运行，API 可在 `/game-creation/replay` 请求体传 `replay_render_mode=viewport`。2026-05-01 已用 Godot 4.5.1 + Vulkan 对 `sandbox_project` 执行 viewport replay，stdout 返回 `REPLAY_SCREENSHOT_CAPTURE=viewport`，并将 `tower_defense_runtime.png` 推广到 `tower_defense_2d_main.png`。
- P0 layout policy 继续向 legacy skill 收口：`generate_movement_script`、`generate_ai_behavior`、`generate_dialogue_system`、`wire_signal_connection`、`apply_tween_animation`、`manage_signal_bus` 现在都会在写入或修改 `.gd` 前调用 `ProjectLayoutValidator`，阻断空格、路径逃逸、错误目录或非 `.gd` 的受管脚本输出；`skill_result.validation` 会保留 `layout_check` 证据，方便 Portal/API/任务历史直接解释为什么没有写入文件。
- 编辑器操作类 legacy skill 也已继续接入 layout policy：`manage_input_mapping` 会校验 `project.godot` 根配置，`attach_script_to_node` 会校验待挂载脚本和离线目标场景，`create_godot_scene` 与 `setup_3d_environment` 会在派发 Godot editor/headless 脚本前校验目标 `.tscn` 路径；非法场景名、脚本路径或项目配置路径会在真正写入/派发前阻断。
- 边缘编辑器链路也已接入同一策略：`instantiate_scene_prefab` 会校验被实例化的 `.tscn` 预制件路径，`configure_physics_collision` 会在 headless 物理烘焙前校验目标场景路径，避免 editor/headless 脚本对非受管场景执行结构性修改。
- `ProjectLayoutValidator` 现在会为非法受管路径返回 `repair_preview`：包含 `suggested_relative_path / suggested_path / issue_codes / changes / apply_mode=preview_only`，用于提示建议落点，例如把 `scripts/Bad Name.txt` 建议为 `scripts/bad_name.gd`，但不会自动移动或写入任何文件。
- Skill 统一基线继续收口：skill 层现在不再直接裸返回 `ToolResult`，统一通过 `BaseSkill.build_result()` 生成 `skill_result` envelope；`manage_audio_resource` 和独立 `audit_godot_resources` 旧入口也已补齐 `schema_version / validation / rollback / artifact metadata`，其中资源审计报告写入前会走 runtime report layout 校验。
- P19 现在新增 `game_creation_template_migration` contract、`POST /game-creation/template-migration`、CLI `game-create --template-migration --to-template-id arpg` 和 MCP `godot_plan_game_template_migration`：它会从 manifest 读取源模板，生成目标模板兼容检查、受管文件 overwrite/create/backup_or_remove 操作、`gameplay.json` 与 `input_replay.json` 数据迁移策略、验证计划和 rollback 计划；该入口默认只规划并可写出 `data_tables/game_creation/template_migration_plan.json`，不会直接改写 Godot 项目文件。
- `tools/run_full_live_validation.ps1` 的 `godot_live_sandbox` lane 现在会把 P19 execute-replay 子链作为结构化证据写入 lane report：`flow_statuses.p19_execute_replay_flow`、`expected_live_tests`、`p19_replay_evidence`，以及 `sandbox_project/data_tables/game_creation/input_replay_run.json`、replay 脚本和 runtime screenshot artifact 路径都会进入 `logs/reports/full_live_validation_lanes/godot_live_sandbox.json`。
- 路线图剩余任务现在也有机器可读状态：`GET /roadmap/status` 与 `python -m agent_system.cli roadmap --json` 会输出 `roadmap_status` contract，包含 done/partial/pending 计数、remaining items 和下一步建议，避免每次靠人工盘点。
- 非 live 回归现在提供分片脚本 `tools/run_non_live_validation_shards.ps1`，把 API、P19/CLI/contracts、资源质量、telemetry/template、agent/MCP、release foundation、release live CI、release execution 和 release promotion 等慢测试族拆成独立 shard，并写出 `logs/reports/non_live_validation_shards.json` 与 Markdown 摘要。建议显式传 `-PythonCommand`，避免 Windows PATH 命中不兼容 Python。
- `release` 目标渠道现在会强制启用 `strict + fail_on_warnings`；不再接受 advisory 放行，缺失 `acceptance_checklist`、断言型 QA 或 visual regression 证据都会直接阻断 RC / promotion / execution。
- P17 已落地为 `agent_system/tools/release_promotion_history.py`：`GET /release-promotion/history` 和 `POST /release-promotion/record` 会把实际晋级结论、执行人、signoff 来源、目标渠道、版本信息和完整 `plan_snapshot` 持久化到 `deployment/release_promotion_history.json`，并支持按 `decision / target_channel / executed_by` 过滤与分页。现在 history record 还会直接回写 `distribution_status`、`distribution_publish_receipts_*`、`release_delivery_readiness_*`、`release_live_ci_*` 摘要以及 Review Bundle 生成的 `review_followup_actions`，这样 promotion ledger 不再只知道“批了没有”，也能直接说明这次晋级对应的交付 readiness next actions、外部分发回执是否已经完整回流、fixed runner 的 live CI 卡在哪一个 workflow step、还有哪些复审行动未收口；同时也支持按 `live_ci_status / delivery_readiness_status / readiness_action / dispatch_status / dispatch_follow_up / dispatch_run_status / dispatch_run_conclusion / failed_workflow_step` 聚焦具体失败面。`GET /release-promotion/history-report` 还会把同一份 ledger 导出为 Markdown，方便 Portal/API/CI 直接查看 latest promotion、Delivery Readiness Next Actions、distribution 状态、publish receipt follow-up、Review Follow-up Actions 和 live CI workflow step 诊断。Portal 的 `Release Promotion` 面板现在也会直接显示并筛选 promotion history、delivery readiness、distribution/publish receipt 摘要、review follow-up 摘要，以及 latest/live CI failed workflow steps 与 workflow step result 路径，并支持把 `history-report` 直接导出到源码预览区，避免渠道晋级只留在聊天记录或临时导出里。
- `release-promotion/history` 和 `release-promotion/history-report` 现在还支持 `live_ci_status` 过滤；Portal 的 `Release Promotion` history 区也加了对应下拉，便于直接筛出 `warning / blocked` 的 fixed-runner 记录，而不必人工扫描整段 ledger。
- 同一条 history 链现在也支持 `failed_workflow_step` 过滤；可以直接按 `run_full_live_validation` 这类 step id 筛出卡在某一步的 fixed-runner promotion 记录，而不必先导出全量 ledger 再手动 grep。
- 发布链现在还额外落了三层高风险写保护：`deployment/release_access_policy.json` 会把 release actor 与 role 绑定到 `promotion_record / release_execution` 规则上；`deployment/release_request_auth.json` 则支持按 `token_id / token_sha256 / action / channel / target_environment / actor_ids / expires_at / session_id / issued_by / issued_at` 管理可轮换的请求级 token；`deployment/release_identity_registry.json` 会把 `issued_by` 绑定到真实 issuer、允许的 `subject_actor_ids`、渠道/环境范围，以及可选的 `session_required / max_session_age_hours`。`POST /release-promotion/record`、`POST /release-execution/run` 和 `POST /release-execution/rollback` 会先做请求级 `request_auth` 校验，再把 `executed_by` 对照 policy 做 fail-closed 授权，并把结构化 `request_auth(status / mode / scheme / token_source / token_id / session_id / issued_by / issued_at / issuer_registered)` 与 `authorization(status / actor_roles / matched_rule_id / reason)` 一起写进 promotion history / execution ledger。`Release Promotion / Execution` 现在还会额外给出 `request_auth_posture`、`request_auth_rotation_audit` 与 `request_auth_identity_audit`；前者直接暴露当前 action/channel 下的 token 覆盖、actor 绑定、本地 bypass、`expires_at` hygiene、session 跟踪状态、identity registry 覆盖和重复 `token_id` 状态，第二层汇总同一渠道下 `promotion_record + release_execution` 的覆盖与 rotation 缺口，第三层则独立审计 scoped issuer、subject actor 绑定、重复 issuer_id、stale session 和 `release` 渠道的 session policy。`release` 目标下如果这三层姿态里任一不是 `passed`，promotion checklist、evidence bundle、review bundle 和 deployment rehearsal 会直接阻断。
- 当前仓库里的 `deployment/release_request_auth.json` 已额外补了一条 `staging` actor-bound digest，用来覆盖 `promotion_record + release_execution` 的 local replay/request-auth 审计；因此 `staging/staging` local replay 下的 `request_auth_posture / request_auth_rotation_audit / request_auth_identity_audit` 现在都会收敛到 `passed`，不再依赖 `allow_local_without_token` 本机豁免。
- P18 已完整落地为 `agent_system/tools/release_execution.py`：`GET /release-execution/status`、`GET /release-execution/report`、`POST /release-execution/run` 和 `POST /release-execution/rollback` 会把 `dry_run / canary / full_rollout / rollback` 收敛到统一 `release_execution_status 1.1` contract，并把 execution ledger 与 channel binding 固定写入 `deployment/release_execution_status.json` 和 `deployment/release_channels.json`。`clean_machine_bootstrap.json`、`full_live_validation.json`、`logs/reports/release_live_ci/release_live_ci_summary.json` 与当次 `release_delivery_readiness_*` 摘要现在也会直接进入 execution 状态摘要与导出报告，后者会把 `ci_gate / runtime_gates / runtime_lanes.full_live_validation / human_signoffs` 直接收成结构化字段，并从 latest `plan_snapshot.review_bundle.review_followup_actions` 继承复审行动，在 `Review Follow-up Actions` 段落里继续展示 owner、依赖、ETA、验证方法和 blockers。Portal 的 `Release Execution` 面板可直接执行 rehearsal、canary、full rollout 和 rollback，并查看当前 active channel URL、versioned URL、rollback 锚点、bootstrap/live validation 摘要、当次 Delivery Readiness actions、Review Follow-up Actions 与最近执行记录。
- 开发链路新增了 `关卡工作流`：`manage_level_workflow` 现已提供 `template / preview / audit / snapshot / diff` 五段式关卡模板与审计流程，会统一生成 `scenes/levels/` 下的关卡场景、`data_tables/levels/` 下的关卡 schema，并围绕 `出生点 / 交互点 / 检查点 / 导航区 / 导航代理 / TileMap / Trigger / 关卡边界 / 碰撞层 / 关键路径` 输出验收报告与快照 diff；前端与 MCP 可通过 `POST /levels/manage` 直接调用。
- 架构链路新增了 `玩法模板工作流`：`manage_gameplay_template` 现已提供 `preview / apply` 两段式玩法模板入口，围绕 `platformer / topdown_action / arpg / roguelike / tower_defense / visual_novel / survival_crafting` 输出 `starter_gameplay_systems`、依赖关系、验收项和推荐 skill，并可直接把核心系统骨架写入蓝图与功能列表；前端、CLI、MCP 与外部 Agent 可通过 `GET /gameplay/templates` 和 `POST /gameplay/manage` 复用同一份 contract。
- 资源链路新增了 `表现层工作流`：`manage_presentation_pipeline` 现已提供 `template / validate / preview / apply` 四段式入口，覆盖 `animation / vfx / shader / audio` 四类 profile，统一生成 `assets/manifests/*_profiles.json`、`assets/shaders/`、`assets/materials/`、`assets/vfx/`、`scripts/presentation/` 与 `scripts/audio/` 下的受管产物，并通过 `GET /presentation/profiles` 与 `POST /presentation/manage` 暴露同一份 contract 给 Portal、CLI、MCP 和外部 Agent。Portal 现在也新增了独立 `表现层 Pipeline` 面板，可直接读取 profile、加载模板、模板落盘、校验、预览并应用 presentation scaffold。
- `端到端测试 ...` 会走测试角色的 headless 冒烟脚本，支持按自然语言触发简单输入回放，并可选输出截图产物声明。
- Portal 现在额外提供“产物中心”，会从最近任务历史里汇总脚本、报告、场景、截图、发布产物，支持按类型筛选、内联预览、再次打开文件，以及把 `res://` 产物一键发送到 Godot 编辑器中打开；对应后端接口为 `/artifacts` 和 `/artifact-file`。
- Portal 的发布结果现在会直接展示 `version / channel / build_id`，`release` 类型产物卡片也会附带版本、回滚提示和质量门禁指标摘要，便于 QA 和制作快速确认当前包的身份。
- 发布前现在会自动执行 QA / 性能门禁：按渠道校验 `feature_status`，并在可解析场景时执行 headless smoke、`scene_load_ms`、`fps`、`memory_peak_mb` 以及可选的截图 diff 门禁；如果任务上下文里已经存在 `performance_summary`，发布门禁还会继续纳入 `draw_call_count / node_count / texture_memory_mb / frame_spike_ms` 和基线回归检查。结果会写入 `QA Gate Report` 和 `release_summary.quality_gate`。
- 当项目存在 `enemy / quest / loot` 表时，发布门禁现在还会附带 `balance_analysis` 检查；`QA / release` 渠道下如果发现敌人与掉落引用断链、掉落总概率溢出或明显奖励曲线异常，会直接阻止继续导出。
- 当项目存在 `telemetry/event_catalog.json` 或 `telemetry/sessions/*.jsonl` 时，发布门禁现在还会附带 `telemetry_health` 检查；`QA / release` 渠道下如果发现未登记事件、缺少必填字段或未授权敏感字段，也会直接阻止继续导出。
- API 现在额外提供 `GET /performance`、`GET /performance/profile` 和 `POST /performance/manage`，可让 Portal、CLI 或外部工具直接读写性能基线、profile 摘要和预算分析结果。
- Portal 现在还提供“计划编辑器”：输入指令后可以先调用 `/plan` 生成步骤，再在前端修改步骤名、说明、角色和顺序，补充 `feature_id / owner / priority / risk / 验收标准`，最后通过 `/execute-plan` 执行编辑后的计划；执行编辑计划时会保留每个 step 的 `status / metadata / requires_confirmation`，因此 returned review 自动生成的 `review_followup` 步骤可以带着来源继续执行，而已成功步骤不会被迫丢掉状态。计划评审区现在还提供“执行复审待办”，会在本次提交中跳过非 review-followup 步骤，只执行仍未完成的复审步骤；复审步骤全部成功后，API 会清空已完成的 `required_followups`，移除对应 blockers，并把功能状态推回 `pending_acceptance` 等待二次验收。执行完成后还可以直接标记“已通过 / 已退回”并留下评审意见。侧边栏“任务历史”支持按 `待验收 / 已通过 / 已退回` 筛选，并可继续按 `Feature ID / Owner` 缩小范围；历史任务也可以直接重新载入编辑器、重试或触发回滚，载入后会保留复审 step metadata，当前页待验收任务还可以通过 `/history/feature-review-batch` 批量二次验收通过或退回。批量接口支持 `source_feature_status / feature_id / owner / limit / offset / dry_run`，Portal 会先 dry-run 预览并确认数量，再写入统一的 review history / lifecycle 记录。
- Portal 检视器现在新增 `Skill Result` 面板，会直接展示最近一次 `last_skill_result`、近几次 `skill_runs`、validation/rollback 状态以及当前任务挂载的 `contract_versions`；它也会同步读取 `/contracts/versions` 的目录，方便在前端核对“任务实际写入的版本”和“系统当前支持的版本”。
- Portal 检视器现在新增 `质量面板`，会直接读取 `/quality/dashboard` 并显示 contracts、目录、模板、skills、遥测、性能和 migrations 的 pass / warning / blocked 状态。
- Portal 检视器现在新增 `治理准入`，可选择 `feature / skill / template / data_table / telemetry / performance / release / mcp_bridge / portal` 变更类型，填写 evidence 和 changed paths 后调用 `/governance/admission` 生成 blockers、warnings 和推荐落点。
- Portal 检视器现在新增 `生产验证`，可选择 P5 场景并调用 `/production/validate`，把真实项目交付前需要的目录、迁移、质量、模板和治理证据压成一个 strict/advisory 结果。
- Portal 检视器现在新增 `Release Candidate` 面板，可直接读取 `/release-candidate/checklist`，集中查看当前包的 build metadata、QA gate、performance/telemetry 状态、acceptance checklist、known issues、rollback 提示和 production gate，并给出 RC 推荐动作。
- `Release Candidate` 面板现在还会单独展示 `Assertion QA` 与 `Visual Regression` 摘要卡；`Release Promotion / Release Execution` 选择 `release` 目标时，前端也会自动把模式收紧到 `strict + fail_on_warnings`，避免 UI 侧误配。
- Portal 检视器现在新增 `Agent 兼容性`，可调用 `/agent-compat/matrix` 检查不同 AI/API 接入是否都复用同一套 MCP tool schema、API endpoint、skill result、治理与文件树约束。
- Portal 侧边栏现在新增 `MCP / IDE` 接入面板，可直接复制 `codex mcp add` 命令、`config.toml` 片段、Gemini `settings.json` 配置、Remote MCP Bridge 启动命令，以及 IDE 终端命令；同时可从前端直接把 `closure-first-engineer` skill 同步到本机全局 Codex 目录。
- `bridge/remote_mcp_server.py` 提供 HTTP 形态的 MCP-style bridge，复用 stdio MCP 的 `godot_make / godot_status / godot_capture / godot_production_validate / godot_agent_compat / godot_create_game_plan / godot_apply_game_plan / godot_audit_game_scene_graph / godot_review_game_creation` 工具 schema；`GET /mcp/remote-manifest` 会返回本机部署命令、manifest URL、tool call pattern 和安全提示。
- Portal 顶部现在提供“启动 Godot”按钮和“自动拉起”开关。启用后，发送指令、执行计划或在 Godot 中打开资源时，如果编辑器离线，会先请求服务端拉起编辑器并等待插件上线。
- 编辑器状态同步现在不只包含当前场景和选中节点名，还会同步选中节点完整路径、选中节点详情、当前脚本路径与光标行列、Inspector 当前资源或节点；服务端会进一步补全当前脚本的 `class_name / func / signal` 上下文，并通过 `/health` 的 `editor_state` 返回给 Portal。`developer` 角色在实时注入节点时会优先使用完整节点路径，`tester` 会在缺省场景路径时优先接管当前打开场景，`code_generator` 则可以利用当前脚本上下文解析“重命名当前函数/类/信号”。
- Portal 前端现在会直接展示审计分级摘要，并支持按 `error / warning / info` 过滤查看问题。
- Portal 审计面板支持直接打开 Markdown 报告、按问题条目查看对应源码片段，并把条目一键发送到 Godot 编辑器中打开；源码预览头部会直接显示脚本的 `class_name / func / signal` 上下文，或场景节点路径/实例源信息，并以可点击 badge 的形式再次触发精确打开。脚本会尽量定位到行号，`.tscn` 会按定位行尽量选中对应节点并在同名节点场景下优先显示完整节点路径，跨实例场景时还会带实例根路径和实例源场景，`.import` 会优先跳到源资源，场景和资源其余情况走最佳努力打开。Portal 也会显示最近一次编辑器执行回执，区分“请求已发送”和“Godot 端已执行”。

## HTTP API

启动服务：

```bash
python api_server/main.py
```

默认监听 `0.0.0.0:8000`。如果需要统一修改插件、live 测试和启动脚本使用的地址，可先设置：

```bash
set GODOT_AGENT_API_HOST=127.0.0.1
set GODOT_AGENT_API_PORT=8011
python api_server/main.py
```

执行任务：

```bash
curl -X POST "http://127.0.0.1:8011/execute" \
  -H "Content-Type: application/json" \
  -d "{\"command\": \"生成玩家移动脚本\"}"
```

如果没有设置环境变量，请把端口换回默认的 `8000`。

PowerShell 下的 live 沙箱联调可以直接用：

```powershell
.\tools\run_live_sandbox_tests.ps1 -ApiPort 8011
```

如果你想分步排查启动或编辑器回执，也可以继续手动执行 `start_live_sandbox.ps1` / `pytest` / `stop_live_sandbox.ps1`。

如果你要一次跑完 Godot live、Portal browser 和 Remote MCP live 验证，可直接用：

```powershell
.\tools\run_full_live_validation.ps1
```

这条命令会把汇总结果写到 `logs/reports/full_live_validation.json`，供 `Release Promotion Evidence / Review Bundle / Release Execution Report` 直接复用。`portal_click_smoke` 这类 lane 现在还会把 `release_promotion_history_report_flow` 等子 flow 状态一起固化进 lane report / normalized contract，避免 Portal 人工审计链只停留在浏览器脚本返回值里。
报告现在会额外携带 `release_binding(build_id / version / channel / manifest_path / release_url)` 与 lane 级 `artifact_paths`；`release_promotion / release_execution` 会把这份 binding 和当前 release manifest / execution ledger 做比对，`release` 目标发现不一致时会直接阻断。

如果你要把 release 写接口暴露给远端 Portal、脚本或 CI，现在有两种方式：

1. 简单 fallback：设置单一环境变量 token

```powershell
$env:GODOT_AGENT_RELEASE_WRITE_TOKEN = "replace-with-long-random-token"
```

2. 可轮换 manifest：在 `deployment/release_request_auth.json` 中维护 token 摘要

```json
{
  "schema_version": "1.0",
  "allow_local_without_token": false,
  "tokens": [
    {
      "token_id": "staging_release_manager",
      "token_sha256": "<sha256 hex>",
      "actions": ["release_execution"],
      "channels": ["staging"],
      "target_environments": ["staging"],
      "actor_ids": ["release_manager"],
      "session_id": "staging-session-001",
      "issued_by": "ops_a",
      "issued_at": "2026-04-15T00:00:00Z"
    }
  ]
}
```

如果你要把 `issued_by` 继续收紧成受管身份主体，再补一份 `deployment/release_identity_registry.json`：

```json
{
  "schema_version": "1.0",
  "issuers": [
    {
      "issuer_id": "ops_a",
      "status": "active",
      "channels": ["qa", "staging", "release"],
      "target_environments": ["qa", "staging", "production"],
      "subject_actor_ids": ["producer_a", "release_manager", "ops_a"],
      "session_required": true,
      "max_session_age_hours": 0
    }
  ]
}
```

两种方式都接受同一个请求头：

```powershell
Authorization: Bearer <token>
```

也可以用 `X-Godot-Agent-Release-Token: <token>`。如果既没有 env token，也没有 manifest token，服务端只允许本机请求调用这些高风险写接口，远端请求会直接拒绝。manifest 里如果配置了 `actor_ids`，请求 token 还必须和 `executed_by` 对齐；如果项目里存在 `deployment/release_identity_registry.json`，manifest token 的 `issued_by` 还必须映射到 active issuer，且 subject actor、channel/environment scope、可选 session age window 都要通过。`release` 渠道现在还会额外检查 matching token 是否带 `session_id / issued_by / issued_at`，并优先要求它们能映射到 registry 里的 issuer，避免正式发布仍使用不可追踪或不可归属的凭据。

如果你想先生成 digest 片段再手工登记到 manifest，可直接用：

```powershell
python .\tools\generate_release_request_token_digest.py `
  --token-id staging_release_manager `
  --token-value "replace-with-long-random-token" `
  --action release_execution `
  --channel staging `
  --target-environment staging `
  --actor-id release_manager `
  --expires-at 2099-01-01T00:00:00Z `
  --session-id staging-session-001 `
  --issued-by ops_a `
  --issued-at 2026-04-15T00:00:00Z
```

这条命令只输出 `token_sha256` 片段，不会把明文 token 写入仓库。`Release Promotion Evidence / Review Bundle / Release Execution Report` 现在也会带上 `Release Request Auth Posture` 段落，用来复核当前渠道是否仍依赖 local bypass、env fallback、未绑定 actor 的 token，或者在 `release` 渠道下仍缺 `session_id / issued_by / issued_at`、identity registry 映射或 session freshness 约束；`release` 目标如果这层姿态不是 `passed`，会直接卡住 promotion / rehearsal。

如果你想把这层安全姿态单独导出成 redacted 运行时证据，也可以直接用：

```powershell
python .\tools\export_release_request_auth_posture.py `
  --project-root . `
  --runtime-root . `
  --action promotion_record `
  --channel release `
  --target-environment production
```

这条命令会生成 `logs/reports/release_request_auth_posture_<action>_<channel>.json`，只保留 posture 摘要、token 计数、binding 状态、`expires_at` hygiene、identity registry 覆盖和建议，不会把 `token_sha256` 或明文 token 带进 runtime report。

如果你想一次看完整个渠道下 `promotion_record + release_execution` 的 rotation 覆盖，也可以直接导出聚合审计：

```powershell
python .\tools\export_release_request_auth_rotation_audit.py `
  --project-root . `
  --runtime-root . `
  --channel release `
  --target-environment production
```

这条命令会生成 `logs/reports/release_request_auth_rotation_audit_<channel>.json`，把两个高风险写 action 的覆盖状态、缺口和 rotation 建议汇总到同一份 redacted 报告里。

如果你还想把 issuer registry 的覆盖单独导成 release 证据，也可以直接导出 identity audit：

```powershell
python .\tools\export_release_request_auth_identity_audit.py `
  --project-root . `
  --runtime-root . `
  --channel release `
  --target-environment production
```

这条命令会生成 `logs/reports/release_request_auth_identity_audit_<channel>.json`，单独汇总当前渠道下的 scoped issuer、subject actor 绑定、重复 `issuer_id`、stale session，以及 `release` 渠道是否已经为 issuer 打开 `session_required + max_session_age_hours`。

如果你要在本地生成与 `.github/workflows/release-validation.yml` 对齐的 non-live 发布证据包，可直接用：

```powershell
python .\tools\export_release_ci_artifacts.py --output-dir .\logs\reports\release_validation_ci
```

这条命令会基于当前真实仓库生成 `staging` 渠道的 promotion / execution rehearsal artifacts，并把 `runtime_reports / deployment manifests / synthetic release bundle` 一起复制到 `logs/reports/release_validation_ci/`。脚本会临时接管 `deployment/*.json` 与 `logs/reports/*.json`，结束后自动恢复本地原始状态。
导出的 `runtime_reports/full_live_validation.json` 也会包含和 synthetic release bundle 对齐的 `release_binding` 与 lane `artifact_paths`，方便在 CI 中直接复核 promotion / execution 的绑定逻辑；`deployment/release_access_policy.json` 与 `deployment/release_identity_registry.json` 也会一起打包，保证 CI artifact 里能看到这次 release 写操作依赖的授权策略和 issuer registry。现在还会额外导出 redacted `runtime_reports/release_request_auth_posture_*.json`、`runtime_reports/release_request_auth_rotation_audit_*.json`、`runtime_reports/release_request_auth_identity_audit_*.json`、`runtime_reports/release_distribution_bundle_staging.json`、`runtime_reports/release_distribution_install_smoke_staging.json` 与 `runtime_reports/release_distribution_channel_staging.json`，并把 `release_distribution_bundle/`、`release_distribution_archive/` 和 `release_distribution_channel/` 一起复制到 artifact 目录；`artifact_manifest.json` 现在也会作为 `release_artifact_manifest 1.0` contract 暴露 `release_build_id / release_version / release_channel / release_summary`、`runtime_lanes.full_live_validation` 与 `execution_delivery_readiness(status / next_action_ids / checks)`，把 synthetic `portal_click_smoke` 的 `release_promotion_history_report_flow` 之类子 flow、release identity 元数据和当次 execution readiness 摘要一起沉进 non-live rehearsal 摘要；manifest 里的 `runtime_assembly` 也走同一个 canonical normalizer，会保留并派生 capability warning/blocked 汇总；`GET /release-artifact-manifest` 会按 artifact dir 读取并归一化同一份 manifest，Portal 的 `Release Live CI` 面板和 `GET /release-live-ci/summary-report` Markdown 也会同步显示 Artifact Manifest 摘要，供 Portal/API/CI 直接消费。`deployment/release_request_auth.json` 默认不会进入 CI artifact bundle，因为它可能包含可轮换 token 的摘要配置。

如果你已经在当前机器上跑完真实 `browser / live / release distribution` 验证，还想生成和 `.github/workflows/release-live-gates.yml` 对齐的 release 级 artifact bundle，可直接用：

```powershell
python .\tools\export_release_live_runner_baseline.py `
  --project-root . `
  --runtime-root . `
  --channel release `
  --target-environment production `
  --release-manifest-path api_server/static/dist/release_manifest.json `
  --fail-on-blockers

python .\tools\export_release_live_ci_artifacts.py `
  --project-root . `
  --runtime-root . `
  --channel release `
  --target-environment production `
  --release-manifest-path api_server/static/dist/release_manifest.json `
  --providers codex,openai_api `
  --fail-on-warnings `
  --fail-on-blockers
```

第一条命令会先生成 `logs/reports/release_live_runner_baseline_release.json`，明确检查 self-hosted Windows runner 是否已经具备 `PowerShell / Godot / Chromium / live scripts / release manifest` 这些真实 release gate 依赖。baseline 现在还会读取 `deployment/release_live_runner_profile.json`，把受管 `runner_profile_id / runner_name / runner_os / runner_arch / runner_labels / workflow run context` 一起写进报告，避免 release gate 只知道“工具存在”，却不知道“是不是那台被批准的 runner”。第二条命令会基于当前真实 runtime 生成 `release_promotion_plan / evidence bundle / review bundle / deployment rehearsal / rollback rehearsal / release_execution_report`，并把 `runtime_reports/full_live_validation*.json`、`runtime_reports/release_live_runner_baseline_*.json`、request auth 三层审计、`release_request_auth_identity_handoff/`、distribution bundle/install smoke/archive/channel index、当前 runtime 已存在的 `release_distribution_signing/`、`release_distribution_publish/`、`release_distribution_publish_receipts/`、`deployment/*.json` 和 versioned release 一起复制到 `logs/reports/release_live_ci/`。`release_live_runner_baseline` 现在不只是 workflow 前置检查，也会作为结构化证据进入 promotion/evidence/review/deployment/execution contract；`release` 目标下如果这份 report 缺失或不是 `passed`，主发布链会直接阻断。它现在会同时写出 `release_live_ci_summary.json` 和面向 GitHub Actions 的 `release_live_ci_summary.md`；workflow 会把后者直接追加进 `GITHUB_STEP_SUMMARY`，把自动化 CI gate、runner baseline 和人工 signoff 分开呈现，避免首轮 self-hosted runner 调试还得先下载 JSON 才能看结论。`release_live_ci_summary` 现在还会额外暴露 `runtime_lanes.full_live_validation`，把 `portal_click_smoke` 的 `release_promotion_history_report_flow` 之类子 flow 直接写进 step summary；同时 workflow 前序 step outcome 也会作为 `workflow_steps` 一并收进 summary，因此即使 baseline / distribution / full live validation 先失败，GitHub step summary 仍能直接指出卡在哪一步。默认只因真实 `runner/browser/live/distribution/request_auth` 门禁失败而阻断，不会把“还没签字”混进自动化 gate。`deployment/release_distribution_delivery.json` 与 `deployment/release_identity_boundary.json` 现在也是受管 release manifest：前者声明外部分发的 installer/signing/publish 形态，后者声明 identity/session/secret rotation 边界；live CI summary 会把它们的 `status/profile_id`、`publish_handoff`、`publish_receipts` 和 `identity_handoff` target 一并暴露出来。

如果你要先在固定 Windows runner 上本地重放一次 `.github/workflows/release-live-gates.yml`，而不是直接进 GitHub Actions，可直接用：

```powershell
.\tools\run_release_live_gates_locally.ps1 `
  -ProjectRoot . `
  -RuntimeRoot . `
  -ArtifactDir logs/reports/release_live_ci_local `
  -RunnerLabels '["self-hosted","windows","godot"]' `
  -FailOnWarnings
```

这个脚本会按 workflow 顺序执行 `runner baseline -> distribution handoff -> distribution signing handoff -> distribution publish handoff -> request-auth identity handoff -> run_full_live_validation.ps1 -> live CI artifact export`，并额外写出 `release_live_ci_step_summary.md`。如果显式传了 `-BrowserPath`，它现在会继续透传到 `run_full_live_validation.ps1` 的 DOM / click browser lanes；click lane 也会用更接近 fixed runner 的脚本预算，避免真实 Portal click-through 因默认 30 分钟窗口过窄而在本地 replay 里被过早截断。`release_live_ci_summary.json` 现在会附带 `invocation.source`，可区分 `local_replay` 与真实 `github_workflow`，方便比较“本地重放通过”与“Actions 实跑失败”的差异；脚本自身返回的 JSON 结果也会附上 `summary_excerpt.runtime_assembly`、`summary_excerpt.event_stream` 与 `summary_excerpt.runtime_lanes`，让本地 replay 调用方可以直接拿到当前 route/runner/identity 装配快照、最新 step/lane/gate 事件，以及 `portal_click_smoke` 的 `release_promotion_history_report_flow` 这类 lane 子 flow 诊断。现在即使 replay 在 baseline / distribution / live validation 某一步先失败，也会继续尝试导出 `release_live_ci_summary.json/.md`，并把 pre-export `workflow_steps` 诊断一起写进 summary，避免 fixed runner 首轮排障时只看到 step 失败而没有统一 gate 结论。

`2026-04-22` 已在一台固定 Windows self-hosted 机器上完成一轮真实 `staging` local replay：`run_full_live_validation.ps1` 的 `godot_live_sandbox / portal_dom_smoke / portal_click_smoke / remote_mcp_live` 四条 lane 全部 `passed`，`run_release_live_gates_locally.ps1` 顶层结果为 `ok=true`。当前自动化 gate 剩余的是 `full_live_validation_lane` 绑定摘要 warning 和人工 signoff warning，不再是 browser/live lane 失败。

如果你已经恢复了 GitHub 认证，还想从仓库内直接触发真正的 `.github/workflows/release-live-gates.yml`，可直接用：

```powershell
$env:GH_TOKEN = "<github-token>"
python .\tools\dispatch_release_live_gates.py `
  --target-channel staging `
  --target-environment staging `
  --release-manifest-path api_server/static/dist/web_release_validation_ci/release_manifest.json `
  --runner-labels '["self-hosted","windows","godot"]' `
  --wait
```

这个 helper 会优先从 `origin` 推断 `owner/repo`，从当前分支推断 `ref`，然后调用 GitHub REST `workflow_dispatch` 触发 `release-live-gates.yml`；如果加了 `--wait`，它还会轮询对应 workflow run，直到拿到 `status / conclusion / html_url`。默认会从 `GH_TOKEN` 或 `GITHUB_TOKEN` 读取认证；如果这两个环境变量都不存在，会 fail-fast 返回明确错误，而不是把 GitHub 侧缺口伪装成 workflow 本身失败。

如果只想导出 dispatch 解锁清单、不触发远端 workflow，可加 `--preflight-only`；它会写出 `logs/reports/release_live_ci/release_live_dispatch_preflight.json` 和 `.md`，用于离线审计 `repo/ref/workflow_dispatch/token/runner_labels` 当前是否就绪。

同一条链现在也已经接进 Portal / API 控制面：`GET /release-live-ci/dispatch-preflight` 会返回结构化 `release_live_dispatch_preflight`，把 `repo/ref/workflow/workflow_dispatch/token/runner_labels` 的 readiness 收成统一快照；Portal `Release Live CI` 面板会直接显示这份 preflight。真正触发 workflow 时，Portal 和 API 都走 `POST /release-live-ci/dispatch`，并复用同一个 helper 与 `request_auth` 边界；现在每次 dispatch 尝试还会把 `preflight + request_auth + run outcome` 一起固化到 `logs/reports/release_live_ci/release_live_dispatch.json`，可通过 `GET /release-live-ci/dispatch-audit` 和 Portal `Release Live CI` 面板直接复查，不必只依赖瞬时 API 响应。最新的 `release_live_ci_summary`、`Release Promotion` 和 `Release Execution` 报告现在也会直接展开这份 `dispatch_audit`，所以真实 GitHub workflow 还没产出完整 summary 时，控制面仍然能说明到底卡在 preflight、request_auth，还是 GitHub run 本身。
这份 `dispatch_audit` 现在也会作为持久字段写进 `release_promotion_history` 的每条 record，而不只是作为“当前最新快照”存在。这样即使 `logs/reports/release_live_ci/release_live_dispatch.json` 后续被清理，history report、Portal `Release Promotion` 列表和 recent records 仍然能回放当次晋级对应的 dispatch 状态、run 结论和 follow-up 标记。

如果你想把当前 release 目录导出成可交付给 QA / 发布执行侧的 versioned distribution bundle，可直接用：

```powershell
python .\tools\export_release_distribution_bundle.py `
  --project-root . `
  --runtime-root . `
  --channel staging `
  --target-environment staging
```

这条命令会在 `logs/reports/release_distribution/<channel>/<build_id>/` 下生成 `distribution_manifest.json`、`install_release_bundle.ps1`、`upgrade_release_bundle.ps1`、`uninstall_release_bundle.ps1`、`support_matrix.md`、`release_manifest.json`、`release_notes.md`、`qa_gate_report.md`、`installed_release.example.json` 和 `release_payload/`，并把汇总状态写到 `logs/reports/release_distribution_bundle_<channel>.json`。`release_distribution_bundle` 现在还会把 `deployment/release_distribution_delivery.json` 中匹配当前 channel/environment 的外部分发 profile 一起收成 `delivery_*` 字段，明确当前 bundle 距离“真实安装器 / 签名 / 渠道分发”还差哪一层。`Release Promotion / Review Bundle / Deployment Rehearsal / Release Execution Report` 现在都会直接消费这份 bundle 状态；`release` 目标下如果 distribution bundle 不是 `passed`，会直接阻断。

如果你还想把生成出来的 install / upgrade / uninstall 脚本真正跑一遍，补上安装链 smoke 证据，可直接用：

```powershell
python .\tools\export_release_distribution_install_smoke.py `
  --project-root . `
  --runtime-root . `
 --channel staging `
  --target-environment staging
```

这条命令会先确保 bundle 已导出，再在 `logs/reports/release_distribution_smoke/<channel>/<build_id>/` 下执行一次临时 `install -> upgrade -> uninstall`，并把结果写到 `logs/reports/release_distribution_install_smoke_<channel>.json`。`release_distribution_bundle` 现在也会直接读取这份 smoke 报告；`release` 目标下如果只导出了 bundle、但没跑过 install smoke，bundle 状态仍然会保持 `warning` 并继续阻断。
现在这份 smoke 报告还会把 `state_path / build_id / version / previous_build_id / backup_dir / removed_build_id / removed_version` 一起写回 `release_distribution_bundle_<channel>.json`，让 promotion / execution / CI artifact 可以直接看到真实安装、升级和卸载链路是否完整闭环。

如果你还要把这份已验证 bundle 收成可交付 zip 包和校验文件，可直接用：

```powershell
python .\tools\export_release_distribution_archive.py `
  --project-root . `
  --runtime-root . `
 --channel staging `
  --target-environment staging
```

这条命令会先确保 bundle 和 install smoke 都已经就绪，再把 `logs/reports/release_distribution/<channel>/<build_id>/` 打成 `logs/reports/release_distribution_packages/<channel>/<build_id>/release_distribution_bundle.zip`，同时生成 `release_distribution_bundle.sha256`。`release_distribution_bundle_<channel>.json` 也会在 archive 导出后同步刷新；`release` 目标下如果 archive 缺失，bundle 状态仍然不会变成 `passed`。

如果你还要把这份 archive 继续收成渠道分发索引，可直接用：

```powershell
python .\tools\export_release_distribution_channel_index.py `
  --project-root . `
  --runtime-root . `
  --channel staging `
  --target-environment staging
```

这条命令会生成 `logs/reports/release_distribution_channels/<channel>/latest.json`、`releases.json` 和 `logs/reports/release_distribution_channel_<channel>.json`。`release_distribution_bundle_<channel>.json` 会同步刷新 channel index 状态；`release` 目标下如果 latest / releases 索引缺失或没有指向当前 archive，bundle 仍然不会变成 `passed`。

如果你还要把这份 verified archive + channel latest/releases 索引再收成一个可直接 handoff 给 QA / 发布执行侧的安装包目录，可直接用：

```powershell
python .\tools\export_release_distribution_handoff.py `
  --project-root . `
  --runtime-root . `
  --channel staging `
  --target-environment staging
```

这条命令会生成 `logs/reports/release_distribution_handoff/<channel>/<build_id>/`，里面包含 `distribution_handoff_manifest.json`、`install_release_handoff.ps1`、`upgrade_release_handoff.ps1`、`uninstall_release_handoff.ps1`、`packages/release_distribution_bundle.zip(.sha256)`、`channel/latest.json`、`channel/releases.json`，以及顶层 `release_manifest / release_notes / qa_gate_report / support_matrix` 副本。wrapper 脚本会临时解压 archive 并调用 bundle 内的 install/upgrade/uninstall 逻辑，所以消费侧不必再解析原仓库里的 `logs/reports/...` 相对路径。`release_distribution_bundle_<channel>.json` 现在也会同步暴露 `handoff_status / handoff_dir / handoff_manifest_path`。

如果你还要把 verified archive 再推进成可交给外部签名环节消费的 signing intake 包，可直接用：

```powershell
python .\tools\export_release_distribution_signing_handoff.py `
  --project-root . `
  --runtime-root . `
  --channel release `
  --target-environment production
```

这条命令会生成 `logs/reports/release_distribution_signing/<channel>/<build_id>/`，里面包含 `distribution_signing_manifest.json`、`SIGNING_INSTRUCTIONS.md`、`unsigned/release_distribution_bundle.zip(.sha256)` 和 `metadata/` 下的 release manifest / notes / QA gate / support matrix / channel index 副本。它不会执行真实外部签名，但会把 verified archive 与签名 profile 约束收成稳定 handoff，`release_distribution_bundle_<channel>.json` 也会同步暴露 `signing_handoff_*` 字段。

如果你还要把 verified archive、channel index 和 publish target 继续收成一个可交给外部分发/渠道发布侧消费的 intake 包，可直接用：

```powershell
python .\tools\export_release_distribution_publish_handoff.py `
  --project-root . `
  --runtime-root . `
  --channel release `
  --target-environment production
```

这条命令会生成 `logs/reports/release_distribution_publish/<channel>/<build_id>/`，里面包含 `distribution_publish_manifest.json`、`PUBLISH_INSTRUCTIONS.md`、`payload/release_distribution_bundle.zip(.sha256)`、`metadata/` 下的 release manifest / notes / QA gate / support matrix / channel index 副本，以及 `inputs/` 下的 portable/signing handoff manifest 副本和 `targets/publish_targets.json`。它不会执行真实外部发布，但会把“当前 verified archive 应该往哪些 publish target 推进、签名链路如何衔接”收成稳定 intake，`release_distribution_bundle_<channel>.json` 也会同步暴露 `publish_handoff_*` 字段。

如果外部分发/渠道发布已经完成，你还可以把 publish 回执重新收回仓库：

```powershell
python .\tools\record_release_distribution_publish_receipt.py `
  --project-root . `
  --runtime-root . `
  --channel release `
  --target-environment production `
  --target-id github_release_manual `
  --status published `
  --external-reference gh-release-001 `
  --artifact-url https://example.invalid/releases/web-release-001.zip `
  --operator ops_release
```

这条命令会在 `logs/reports/release_distribution_publish_receipts/<channel>/<build_id>/` 下写入 `publish_receipts_manifest.json` 和 `receipts/<target_id>.json`，把外部分发回执重新绑定到当前 `build_id / version / channel`。`release_distribution_bundle_<channel>.json` 也会同步暴露 `publish_receipts_*` 字段，方便 CI artifact、promotion evidence / review bundle、execution report 或后续人工复核看到哪些 publish target 已经真正完成。

如果你要把当前渠道的 redacted request-auth / issuer registry / identity boundary 再收成一个可交给外部 identity/session/secret rotation 环节消费的 intake 包：

```powershell
python .\tools\export_release_request_auth_identity_handoff.py `
  --project-root . `
  --runtime-root . `
  --channel release `
  --target-environment production `
  --release-manifest-path api_server/static/dist/release_manifest.json
```

这条命令会生成 `logs/reports/release_request_auth_identity_handoff/<channel>/<environment>/`，里面包含 `identity_boundary_handoff_manifest.json`、`IDENTITY_HANDOFF_INSTRUCTIONS.md`、`audits/` 下的 redacted posture / rotation / identity 审计，以及 `deployment/` 下的 `release_identity_boundary.json` 与 `release_identity_registry.json` 副本。它不会把 `deployment/release_request_auth.json` 带出仓库，但会把“当前 release 身份边界应该如何外部化”收成稳定 handoff，`request_auth_identity_audit` 也会同步暴露 `identity_handoff_*` 字段。

Portal browser smoke 可以直接用：

```powershell
.\tools\run_portal_browser_smoke.ps1
python .\tools\run_portal_browser_click_smoke.py
```

第一条会启动本地 API、用无头 Chrome/Edge 加载 `/portal/index.html`，并检查 `质量面板 / 治理准入 / 生产验证 / Release Candidate / Build / Run Matrix / Agent 兼容性 / Release Promotion / Release Execution / MCP / IDE / 美术资产 Intake / 外包交付 Gate / 资产评审 / 场景归属 / 锁定 / 表现层 Pipeline / 运营配置 / LiveOps / 遥测回流 / 性能分析 / 平台交付 / Savegame` 等关键 Portal 标记。第二条会通过 Chrome DevTools Protocol 真实触发治理准入、生产验证、RC checklist、Build / Run Matrix、Agent 兼容性、Release Promotion 及其 Evidence/Deployment/Rollback 导出、History 记录和 `History Report` 导出、Release Execution 的 `dry_run -> canary -> full_rollout -> rollback`、LiveOps 应用、遥测留存/趋势导出、性能画像导出、美术 intake、外包交付 Gate、资产评审、场景认领锁定、表现层应用和平台交付模板应用。点击式 smoke 现在会先给它的临时项目注入最小 `deployment/release_*` 基线，这样 release promotion / execution 写口会在隔离 temp project 内通过当前 release policy，而不会错误回落到仓库根或因缺少 manifests 直接 `400`。

P2 的部署向质量检查可以直接跑：

```powershell
.\tools\run_p2_quality_checks.ps1
```

默认会先跑 P2 targeted non-live，再跑 `python -m pytest -m "not live" -q`。如果本机 Godot live 环境已准备好，可追加 `-IncludeLive`。

P3 的治理准入检查可以直接跑：

```powershell
.\tools\run_p3_governance_checks.ps1
```

默认会先跑治理/API targeted non-live，再跑全量非 live；如果需要追加真实 Godot 联动，同样使用 `-IncludeLive`。

P4 的可执行准入门禁可以直接跑：

```powershell
.\tools\run_p4_enforcement_checks.ps1
```

如果只想在 CI 或本地脚本中检查单次变更，可调用：

```powershell
.\tools\enforce_governance.ps1 -ChangeType skill -Evidence contract,layout,tests,docs,rollback,quality_gate -ChangedPath agent_system/skills/resource/demo_skill.py -Mode strict
```

P5 的生产规模验证可以直接跑：

```powershell
.\tools\run_p5_production_checks.ps1
```

默认只跑 non-live；如果本机已准备好 Godot、Chromium 和 Remote MCP 自动化，可追加 `-IncludeLive -IncludeBrowser -IncludeRemoteMcp` 把 live sandbox、Portal browser smoke 和 Remote MCP smoke 一起纳入本地验收。

如果只想检查单个生产场景，可调用：

```powershell
.\tools\validate_production_readiness.ps1 -ScenarioId vertical_slice_2d -Evidence contract,tests,docs,quality_dashboard -ChangedPath scenes/Main.tscn,scripts/player_controller.gd,README.md -Mode strict
```

P6 的多 Agent/API 兼容矩阵可以直接跑：

```powershell
.\tools\run_p6_agent_compat_checks.ps1
```

也可以直接查看特定 provider：

```powershell
python -m agent_system.cli agent-compat --provider codex,openai_api --json
```

典型响应字段：

```json
{
  "status": "success",
  "message": "代码生成成功: player_movement_2d.gd",
  "steps": [],
  "logs": [],
  "artifacts": [],
  "context": {}
}
```

## Godot 插件安装

1. 如需刷新分发副本，先运行 `.\tools\sync_plugin.ps1`。
2. 将 `godot_plugin/addons/godot_agent` 复制到目标 Godot 项目。
3. 在 `项目设置 -> 插件` 中启用插件。
4. 启动 `api_server`，保持编辑器与服务端联动。

仓库内的插件目录策略：

- `addons/godot_agent/` 是唯一源码，当前仓库和自动化验证都基于它
- `godot_plugin/addons/godot_agent/` 是对外分发副本
- `sandbox_project/addons/godot_agent/` 是 live sandbox 测试副本
- 当你修改插件后，运行 `.\tools\sync_plugin.ps1` 将源码同步到分发和测试副本
- `整理项目` 现在也会顺带创建 `assets/textures/`、`assets/textures/spritesheets/`、`assets/ui/`、`assets/materials/`、`assets/vfx/` 和 `assets/manifests/`，方便把美术产物按受管目录落位

## 项目目录结构分析

按 2026-04-08 对仓库的实际扫描结果，这个项目可以拆成下面几层：

| 目录 | 作用 | 观察结果 |
| :--- | :--- | :--- |
| `agent_system/` | 核心编排层，包含 `router`、角色、技能、工具、模板 | 132 个文件，是主要业务实现区域 |
| `api_server/` | FastAPI 服务、Portal 静态页、编辑器会话与事件中转 | 16 个文件，负责 HTTP / WebSocket / 编辑器桥接 |
| `addons/godot_agent/` | 插件唯一源码，同时也是当前仓库的运行态插件 | 已在 `project.godot` 中启用，并作为同步源 |
| `godot_plugin/` | 便于分发到其他 Godot 项目的插件副本 | 通过 `tools/sync_plugin.ps1` 从 `addons/` 同步 |
| `bridge/` | 调试桥接脚本、MCP 服务、实时联调脚本 | 偏工具链和联调用途 |
| `ide_integration/` | VS Code 控制器与模板 | 用于 IDE 联动而非核心运行时 |
| `agent_modules/` | 生成物/示例模块目录 | 当前 `project.godot` 的主场景指向这里的 `scenes/Main3D.tscn` |
| `scenes/`、`scripts/` | 示例场景与 GDScript 资产 | 既是样例，也被部分测试用作模板源 |
| `tests/` | 单元、集成、API、真实联动测试 | 共收集 79 个测试 |
| `docs/`、`examples/` | 文档与演示脚本 | 面向使用者，不直接参与主运行链路 |
| `.godot/`、`logs/` | Godot 缓存、任务历史、测试产物、报告 | 运行期产物较多，不应当视为核心源码 |

补充观察：

- `config.yaml` 目前将 `godot.project_path` 指向 `.`，说明默认就是把当前仓库当成 Godot 工程根目录。
- `project.godot` 当前启用了 `res://addons/godot_agent/plugin.cfg`，并把主场景设置为 `res://agent_modules/scenes/Main3D.tscn`。
- 插件源码现统一维护在 `addons/godot_agent/`；`godot_plugin/` 和 `sandbox_project/` 应通过 `tools/sync_plugin.ps1` 保持同步。
- `logs/` 目录产物很多，说明这个仓库既存源码，也存运行历史与测试副产物。
- `.gitignore` 现已默认忽略 `logs/`、`.godot/`、`tests/.tmp*`、`pytest-cache-files-*` 以及 `api_server/static/dist/` 下的生成发布产物；如需预览清理范围，可运行 `.\tools\clean_runtime_artifacts.ps1 -Preview`。
- `.\tools\clean_runtime_artifacts.ps1` 现在会输出清理汇总，并一并清空 `api_server/static/dist/` 下历史 `web_*` 版本目录与 stable `release_manifest / release_notes / qa_gate_report / build.log`；脚本会保留 `api_server/static/dist/.gitkeep` 作为受管目录锚点。如果遇到 ACL 拒绝访问的历史残留，还会直接打印一段管理员 PowerShell 修复命令，方便在提权窗口里继续收尾。
- 如需对 ACL 拒绝访问的历史残留单独收尾，可在管理员 PowerShell 中运行 `.\tools\fix_acl_artifacts.ps1`；先看目标范围可用 `.\tools\fix_acl_artifacts.ps1 -Preview`。该脚本默认只匹配需要 ACL 接管的托管运行产物，不会把正常可访问目录一起带上。

## 2026-04-08 深度测试结果

本轮实际执行过的检查包括：

```bash
python -m pytest --collect-only
python -m pytest
python -m agent_system.cli doctor
python -m agent_system.cli roles
python -m agent_system.cli history --limit 5
python -m agent_system.cli plan "创建一个玩家场景并生成移动脚本"
python -m agent_system.cli plan "验证玩家跳跃功能"
python -m agent_system.cli plan "为NPC添加对话系统"
python -m agent_system.cli plan "预览修复项目资源命名"
python -m agent_system.cli plan "端到端测试 res://scenes/main_scene.tscn 并向右跳跃后截图"
python -m uvicorn api_server.main:app --host 127.0.0.1 --port 8011
```

测试结论：

- `pytest` 共收集 86 项测试。
- 在标准 live 启动流程下已验证 `86` 项全部通过。
- `tests/test_live_sandbox.py` 现已通过 `tools/run_live_sandbox_tests.ps1 -ApiPort 8011` 的标准链路稳定执行，不再依赖手工预启动环境。
- `python -m agent_system.cli doctor` 通过，能识别本机 `PATH` 中的 Godot，可执行文件命中为 `D:\迅雷下载\Godot\godot.EXE`。
- 真实 HTTP 服务在端口 `8011` 上验证通过，`/health`、`/plan`、`/execute`、Portal WebSocket 和编辑器联动事件都能返回有效结果。
- API 端口现在支持通过 `GODOT_AGENT_API_PORT` 统一配置，插件和 live 测试会跟随同一配置。

稳定通过的测试区域：

- 路由器核心行为：`tests/test_agent.py`
- API 层：`tests/test_api.py`
- CLI 分发：`tests/test_cli.py`
- Godot 可执行文件探测：`tests/test_godot_cli.py`
- 索引服务：`tests/test_index_service.py`
- 基础集成链路：`tests/test_integration.py`
- 两个独立脚本式验证：`tests/test_context_logic.py`、`tests/test_final_acceptance.py`

已完成自动验收的真实联动区域：

- 真实联动沙箱：`tests/test_live_sandbox.py`
- 覆盖资源打开、节点注入、场景创建、E2E 截图、Portal WebSocket 实时事件
- 非 live CI 已扩成两层：先跑稳定子集，再跑 `python -m pytest -m "not live" -q` 的全量非 live 回归；对应工作流为 `.github/workflows/non-live-tests.yml`
- 现在还新增了 `.github/workflows/release-validation.yml`：会跑 `clean_machine / governance / production / release_request_auth / release_distribution / release promotion / release execution / contracts` 的 targeted non-live 回归，并导出 `logs/reports/release_validation_ci/` 下的 `staging` 渠道 rehearsal artifacts；artifact 中现在还会带 `release_distribution_bundle/`、`release_distribution_archive/`、`release_distribution_channel/`、`release_distribution_handoff/`、`release_distribution_signing/`、`release_distribution_publish/`、`release_distribution_publish_receipts/`、`release_request_auth_identity_handoff/`、`release_promotion_history.json` 和 `release_promotion_history.md`，再加上 `runtime_reports/release_distribution_bundle_staging.json`、`runtime_reports/release_distribution_install_smoke_staging.json` 和 `runtime_reports/release_distribution_channel_staging.json`。它沉淀的是非 live 发布证据，不替代真实 `release` 的 browser/live/full-live gate。
- `.github/workflows/release-live-gates.yml` 现在提供了真实 `release` 级 CI 入口：先生成 `release_live_runner_baseline_<channel>.json`，并按 `deployment/release_live_runner_profile.json` 校验 self-hosted Windows runner 的 `runner identity / runner labels / runner os / runner arch / Godot / Chromium / PowerShell / live scripts / release manifest` 基线，再生成 verified `release_distribution_handoff`、`release_distribution_signing`、`release_distribution_publish` 与 `release_request_auth_identity_handoff`，跑 `run_full_live_validation.ps1`，最后导出 `logs/reports/release_live_ci/` 下的 release artifact bundle，并用 `release_live_ci_summary.json` 的自动化 gate 决定是否失败。`Export live release CI artifacts` 现在会以 `always()` 运行，并把前序 step outcome 收成 `release_live_ci_workflow_steps.json` 与 summary 里的 `workflow_steps`，这样即使真实 runner 首轮卡在 baseline / distribution / live validation 中途，GitHub step summary 也仍能给出明确的失败步骤和最终 gate 结论。这个 workflow 预期跑在带 Godot、Chromium 和浏览器自动化依赖的自托管 Windows runner 上。

## 2026-04-10 P2 验证结果

- P2 targeted non-live：`21 passed`
- API 回归：`47 passed`
- 全量非 live：`183 passed, 5 deselected`
- `.\tools\run_p2_quality_checks.ps1` 已验证可用；默认跳过 live，可用 `-IncludeLive` 追加 Godot live sandbox 检查。

## 2026-04-11 P3 验证结果

- P3 governance targeted non-live：`61 passed`
- 全量非 live：`190 passed, 5 deselected`
- `.\tools\run_p3_governance_checks.ps1` 已验证可用；默认跳过 live，可用 `-IncludeLive` 追加 Godot live sandbox 检查。

## 2026-04-11 P4 验证结果

- P4 governance enforcement targeted non-live：`63 passed`
- 全量非 live：`196 passed, 5 deselected`
- `.\tools\run_p4_enforcement_checks.ps1` 已验证可用；advisory smoke 返回 `exit_code=0`，默认跳过 live，可用 `-IncludeLive` 追加 Godot live sandbox 检查。

## 2026-04-11 P5 验证结果

- P5 production readiness targeted non-live：`77 passed`
- 全量非 live：`218 passed, 8 deselected`
- `.\tools\run_p5_production_checks.ps1` 已验证可用；主项目 `vertical_slice_2d` strict smoke 返回 `exit_code=0`，当前 readiness 为 `passed`，`blocking_checks` 和 `warning_checks` 均为空。
- 项目级模板覆盖、遥测样本和性能基线样本已填充，并由 `tests/test_production_samples.py` 纳入非 live CI。

## 2026-04-11 P6 验证结果

- P6 agent compatibility targeted non-live：`72 passed`
- 全量非 live：`218 passed, 8 deselected`
- `.\tools\run_p6_agent_compat_checks.ps1` 已验证可用；`codex / openai_api` provider smoke 返回 `status=passed`，contracts、skills、stdio/remote MCP、API、governance、production 和 file tree surface 均通过，MCP tool schema 当前为 9 个。

## 2026-04-12 Live / Browser / MCP 自动化结果

- 完整 live 验证入口：`.\tools\run_full_live_validation.ps1` 已实际运行通过。
- Live Godot sandbox + production flows：`9 passed`，覆盖资源打开、节点注入、场景创建、E2E 截图、Portal WebSocket、美术导入、关卡模板、遥测回流、性能分析、数值平衡、P5 production validate 和 P6 agent compatibility。
- Portal browser DOM smoke：`ok=true`，无头 Chrome 加载 `http://127.0.0.1:8012/portal/index.html`，`scenario_count=3`，`provider_count=5`。
- Portal browser click smoke：`ok=true`，真实触发治理准入、生产验证、Agent 兼容性和数据表预览，结果均为 passed / exit 0。
- Remote MCP live smoke：`ok=true`，HTTP bridge 工具数已扩展到 `9`，`godot_production_validate` 与 `godot_agent_compat` 均返回 passed。

## 2026-04-25 Staging 发布闭环结果

- 全量非 live：`486 passed, 16 deselected`。
- 完整 live validation：`4/4 lanes passed`，其中 Godot live sandbox + production flows 为 `16 passed`，Portal DOM、Portal click 和 Remote MCP live 均为 passed。
- `release_live_ci_local` staging artifact 已重新导出：`ci_gate_status=passed`、`human_signoff_status=passed`、`full_live_validation_status=passed`、`distribution_bundle=passed`、`request_auth=passed`，并生成 `artifact_manifest.json`、`release_live_ci_summary.md`、`release_delivery_readiness_staging.json/.md` 与 `release_live_dispatch_preflight.json/.md`；summary 的 `report_files` 和 manifest 的 `generated_files` 均可直接发现这些 readiness/preflight 报告。
- Staging delivery readiness 已收敛为 `identity=passed / workflow=blocked / distribution=passed`；`staging_internal_windows` 使用 `sha256_only` 且 `delivery_signing_required=false`，因此 `signing_handoff=skipped` 不再被当作 incomplete；readiness recommendations 也只剩 workflow unblock 入口和 GitHub token/workflow 说明。
- P5 `release_candidate` strict readiness 在完整 evidence 下通过；P6 `codex / openai_api` compatibility smoke 通过。
- 真正 `release -> production` 仍需外部收口：identity/session/secret rotation、固定 self-hosted Windows runner 上的真实 release-live-gates、外部分发签名/发布/receipt 回写。

## 当前实现与文档的偏差

这轮测试后，代码与文档的主要差异已经收敛，当前更准确的结论是：

- Router 已恢复对测试、资源审计/修复、安全重构、场景创建、节点注入、AI 模板和上下文提示的核心行为。
- `WAITING_ACK`、历史持久化、当前脚本符号推断、E2E 场景参数提取等关键链路已经通过自动化测试。
- 当前主要剩余风险已从“核心功能是否可用”收缩到“运行产物治理、CI 扩面、发布说明完善”等工程化问题。

## 相关文档

- `docs/QUICKSTART.md`
- `docs/使用指南.md`
- `docs/IDE集成指南.md`
- `docs/TESTING_GUIDE.md`
- `docs/完成度补齐清单.md`
- `docs/制作路线图.md`
- `docs/成品发布计划.md`
- `docs/支持矩阵与分发说明.md`
- `docs/游戏开发标准化增强路线图.md`

## Codex Skill

仓库内现在附带了一个面向后续开发任务的 Codex skill 包：`.codex/skills/closure-first-engineer/`。

- 适用场景：多层联动功能、重构、发布链路、数据表管线、Portal/API 同步改动
- 目标：减少“功能先通，后面再补测试/文档/分页/发布元数据”的返工
- 安装预览：`.\tools\install_codex_skill.ps1 -Preview`
- 安装到本机 Codex：`.\tools\install_codex_skill.ps1`

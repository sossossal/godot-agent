# 测试指南

## 运行测试

```bash
pytest -q
```

如果你想逐个文件运行:

```bash
python -m pytest tests/test_agent.py -q
python -m pytest tests/test_integration.py -q
python -m pytest tests/test_cli.py -q
```

如果你想在本地跑与 GitHub Actions 对齐的全量非 live 回归:

```bash
python -m pytest -m "not live" -q
```

如果你要生成与 `.github/workflows/release-validation.yml` 对齐的 non-live 发布证据包:

```powershell
python .\tools\export_release_ci_artifacts.py --output-dir .\logs\reports\release_validation_ci
```

这条命令会基于当前仓库生成 `staging` 渠道的 promotion / execution rehearsal artifact bundle，并额外导出 `runtime_reports / deployment manifests / synthetic release bundle` 快照。它不会替代真实 `release` 渠道的 live/browser/full-live 验收，只负责让 GitHub Actions 稳定沉淀 non-live 证据和 lane 级归档形态。
导出的 `runtime_reports/full_live_validation.json` 会带上 `release_binding`、lane `artifact_paths` 和 lane report 路径；同时还会复制 `runtime_reports/full_live_validation_lanes/*.json`，让每条 `godot_live_sandbox / portal_dom_smoke / portal_click_smoke / remote_mcp_live` lane 都拥有独立 `build_id / version / channel / executed_at / report_path` 级别的证据快照。`artifact_manifest.json` 现在也会作为 `release_artifact_manifest 1.0` contract 额外暴露 `release_build_id / release_version / release_channel / release_summary`、`runtime_lanes.full_live_validation` 与 `execution_delivery_readiness(status / next_action_ids / checks)`，把 synthetic `portal_click_smoke` 的 `release_promotion_history_report_flow` 之类子 flow、release identity 元数据和当次 execution readiness 摘要一起沉进 non-live rehearsal 摘要；manifest 里的 `runtime_assembly` 也走同一个 canonical normalizer，会保留并派生 capability warning/blocked 汇总；同一份 manifest 也可通过 `GET /release-artifact-manifest?artifact_dir=...` 读取归一化 contract，并会在 Portal `Release Live CI` 面板和 `GET /release-live-ci/summary-report` Markdown 中随 summary 一起显示。`deployment/release_access_policy.json` 与 `deployment/release_identity_registry.json` 也会一起进入导出目录，供 CI 复核 release 写操作的本地授权策略和 issuer registry；同时还会生成 redacted `runtime_reports/release_request_auth_posture_*.json`、`runtime_reports/release_request_auth_rotation_audit_*.json`、`runtime_reports/release_request_auth_identity_audit_*.json`、`runtime_reports/release_distribution_bundle_staging.json`、`runtime_reports/release_distribution_install_smoke_staging.json` 和 `runtime_reports/release_distribution_channel_staging.json`，并复制 `release_distribution_bundle/`、`release_distribution_archive/`、`release_distribution_channel/`、`release_distribution_handoff/`、`release_distribution_signing/`、`release_distribution_publish/`、`release_distribution_publish_receipts/`、`release_request_auth_identity_handoff/`、`release_promotion_history.json` 和 `release_promotion_history.md`，把 request auth 审计、identity handoff、bundle 导出、安装链 smoke、可交付 archive、渠道索引、portable handoff 包、外部签名 intake、外部分发 intake、publish receipt 回流和 promotion ledger 审计一起沉淀成独立 runtime evidence。
`bootstrap_clean_machine_preview.json` 由同一个导出流程生成，但 preview 子进程带固定超时；如果 PowerShell preview 卡住，导出会写入 `status=warning` 和 `bootstrap_preview_timeout`，避免 non-live artifact export 在 CI 中无限挂起。

如果你已经在当前机器上完成真实 `release` 渠道的 distribution + browser/live 验证，并且要导出与 `.github/workflows/release-live-gates.yml` 对齐的 artifact bundle:

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

第一条命令会先生成 `logs/reports/release_live_runner_baseline_<channel>.json`，把 self-hosted Windows runner 的 `PowerShell / Godot / Chromium / live scripts / release manifest` 基线收成独立 runtime report。baseline 现在还会读取 `deployment/release_live_runner_profile.json`，把受管 `runner_profile_id / runner_name / runner_os / runner_arch / runner_labels / workflow run context` 一起写进报告；如果 `release` 目标下 profile 缺失、target 不匹配，或者 runner 身份不符合 profile 约束，也会直接失败关闭。workflow dispatch 传入的 `runner_labels` 现在也会参与 baseline 校验，避免 release gate 跑在错误的 self-hosted 标签集上。第二条命令会直接复用当前仓库里的真实 `full_live_validation`、runner baseline、request auth 审计、distribution bundle/install smoke/archive/channel index/handoff，以及当前 runtime 已存在的 signing handoff、publish handoff、publish receipts、identity handoff、promotion history 和 versioned release，额外生成 `release_promotion_plan.json`、`release_promotion_evidence_bundle.md`、`release_review_bundle.md`、`release_promotion_deployment_rehearsal.md`、`release_promotion_rollback_rehearsal.md`、`release_promotion_history.json`、`release_promotion_history.md`、`release_execution_report.md`、`release_live_ci_summary.json` 与 `release_live_ci_summary.md`。`release_live_runner_baseline` 现在会直接进入 promotion/evidence/review/deployment/execution contract；`release` 目标下如果 report 缺失或状态不是 `passed`，不会只在 workflow summary 里报警，而是会作为主发布链 blocker 体现出来。导出的 artifact bundle 会继续快照 `release_distribution_handoff/`、当前 runtime 已导出的 `release_distribution_signing/`、`release_distribution_publish/`、`release_distribution_publish_receipts/`、`release_request_auth_identity_handoff/`、`runtime_reports/release_live_runner_baseline_*.json`、`deployment/release_live_runner_profile.json`、`deployment/release_distribution_delivery.json` 与 `deployment/release_identity_boundary.json`，让 release 级 CI 能直接把 portable handoff 包、外部签名 intake、外部分发 intake、publish receipt 回流、identity/session intake、promotion ledger 审计、runner 基线、外部分发边界、身份边界和 live/runtime 证据一起归档。其中 `release_live_ci_summary.json` 会把“自动化 CI gate 是否应阻断”和“人工 signoff 是否仍待补齐”拆开记录，并额外暴露 `runtime_lanes.full_live_validation`，把 `portal_click_smoke` 的 `release_promotion_history_report_flow` 之类子 flow 直接带进摘要；`artifact_manifest.json` 也会同步暴露 `execution_delivery_readiness`，供外部 CI 消费 readiness status、next action IDs 和 checks；现在还会把 workflow 前序 step outcome 收成 `workflow_steps`，所以即使某个 live/browser step 先失败，也仍能从 summary 看出失败发生在哪一步。`-BrowserPath` 现在会继续透传到 `run_full_live_validation.ps1` 的 DOM / click lanes；click lane 也会使用更贴近 fixed runner 的脚本预算，减少本地 replay 因默认 30 分钟窗口过窄而把真实 click-through 提前截断的误报。`release_live_ci_summary.md` 则会被 `.github/workflows/release-live-gates.yml` 直接追加进 `GITHUB_STEP_SUMMARY`，方便在 GitHub UI 里直接看 gate 诊断而不是先下载 JSON。

如果你要先在同一台 Windows self-hosted runner 上本地重放一次 workflow，而不是直接触发 GitHub Actions：

```powershell
.\tools\run_release_live_gates_locally.ps1 `
  -ProjectRoot . `
  -RuntimeRoot . `
  -ArtifactDir logs/reports/release_live_ci_local `
  -RunnerLabels '["self-hosted","windows","godot"]' `
  -PrepareReleaseFixture `
  -FailOnWarnings
```

这个 replay 脚本会按 workflow 顺序执行 fixture 准备、runner baseline、distribution handoff、distribution signing handoff、distribution publish handoff、request-auth identity handoff、full live validation 和 live CI artifact export，并额外写出 `release_live_ci_step_summary.md`。`-PrepareReleaseFixture` 会先生成和真实 GitHub workflow 对齐的 full release fixture；`release_live_ci_summary.json` 现在会记录 `invocation.source=local_replay`；真实 GitHub workflow 则会记录 `invocation.source=github_workflow`，方便对比“本地重放通过”与“Actions 实跑失败”的差异。脚本自己的 JSON 返回值也会附带 `summary_excerpt.runtime_assembly` 与 `summary_excerpt.runtime_lanes`，本地调用方不必再手动打开 summary 文件就能同时读到 route/runner/identity 装配快照和 `portal_click_smoke` 的 lane / sub-flow 诊断。现在即使 replay 在 baseline / distribution / live validation 某一步先失败，脚本也会继续尝试导出 `release_live_ci_summary.json/.md`，并把 pre-export `workflow_steps` 诊断带进 summary，方便直接看哪一步 failed / skipped。

`2026-04-22` 已在固定 Windows self-hosted 机器上实测通过一轮 `staging` local replay：`run_full_live_validation.ps1` 的四条 live lane 全部 `passed`，`run_release_live_gates_locally.ps1` 顶层结果为 `ok=true`。当前自动化 gate 还保留 `full_live_validation_lane` 绑定摘要 warning 与人工 signoff warning，但不再存在 browser/live lane 级失败。

如果你要直接从本地仓库触发真实 GitHub Actions workflow，而不是手工去 GitHub UI 点 `workflow_dispatch`：

```powershell
$env:GH_TOKEN = "<github-token>"
python .\tools\dispatch_release_live_gates.py `
  --target-channel staging `
  --target-environment staging `
  --release-manifest-path api_server/static/dist/web_release_validation_ci/release_manifest.json `
  --runner-labels '["self-hosted","windows","godot"]' `
  --wait
```

这个 helper 会优先从 `origin` 推断 `owner/repo`，从当前分支推断 `ref`，然后调用 GitHub REST `workflow_dispatch` 触发 `release-live-gates.yml`；如果加了 `--wait`，它会继续轮询 workflow run，直到拿到 `status / conclusion / html_url`。默认认证来源是 `GH_TOKEN` / `GITHUB_TOKEN`；如果缺失，会直接 fail-fast 提示 GitHub 认证未就绪，而不是把问题混淆到 release workflow 本身。

如果只需要离线确认 dispatch 还差什么，不触发 GitHub workflow，可加 `--preflight-only`。这会写出 `logs/reports/release_live_ci/release_live_dispatch_preflight.json` 和 `.md`；live CI artifact export 会把它们复制为 `release_live_dispatch_preflight.json/.md`，并登记到 `release_live_ci_summary.json.report_files` 与 `artifact_manifest.json.generated_files`。

如果你想先在控制面里确认“现在到底能不能 dispatch”，而不是直接跑 CLI，`GET /release-live-ci/dispatch-preflight` 和 Portal `Release Live CI` 面板现在都会返回同一份 `release_live_dispatch_preflight`。这份快照会显式暴露 `workflow_exists / workflow_dispatch_enabled / repo / ref / token_present / token_source / runner_labels / blocking_checks / warning_checks`；真正触发 workflow 时，Portal 也会走 `POST /release-live-ci/dispatch`，并沿用 release write 的 `request_auth` 校验，而不是绕过现有高风险写边界。无论 dispatch 成功、被 `request_auth` 拦下，还是 GitHub run 本身失败，当前尝试都会被固化到 `logs/reports/release_live_ci/release_live_dispatch.json`，可通过 `GET /release-live-ci/dispatch-audit` 和 Portal 里的 `Workflow Dispatch Audit` 直接回看。现在 `GET /release-live-ci/summary-report`、`Release Promotion` 和 `Release Execution` 报告也会把这份 dispatch audit 一起展开，所以真实 workflow 首轮失败时不需要先翻孤立 JSON 才能定位失败层级。

如果你想把“离可交付级还差什么”压成一份聚合视图，而不是分别看 identity / workflow / distribution 三条链：

```powershell
curl "http://127.0.0.1:8000/release-delivery-readiness?project_path=default&target_channel=release&target_environment=production"
python .\tools\export_release_delivery_readiness.py `
  --project-root . `
  --runtime-root . `
  --channel release `
  --target-environment production `
  --fail-on-blockers
```

对应的 `GET /release-delivery-readiness` 与 `GET /release-delivery-readiness/report` 会把 `release_request_auth_identity_audit`、`release_live_dispatch_preflight + dispatch_audit + release_live_ci_summary + runner baseline`、`release_distribution_bundle` 收成统一 `release_delivery_readiness` contract，并给出带 `owner_hint / dependency / eta / validation_method / blockers` 的 `next_actions`。Portal 的 `Release Delivery Readiness` 面板也会直接消费同一份结果，适合在 closeout 阶段快速回答“现在能不能交付，还差哪一步”。
如果不想启动 API，`tools/export_release_delivery_readiness.py` 会把同一份快照落到 `logs/reports/release_delivery_readiness_<channel>.json` 和 `.md`，可作为 release/production closeout 附件；`--fail-on-blockers` 可让 CI 在仍有外部阻断时返回非零。`tools/export_release_live_ci_artifacts.py` 也会在 artifact 目录生成 `release_delivery_readiness_<channel>.json/.md`，并把 readiness、dispatch preflight 和 release live fixture 证据登记到 `release_live_ci_summary.json.report_files`、`artifact_manifest.json.report_files` 与 `artifact_manifest.json.generated_files`，方便 CI artifact 页面或离线审计直接定位。Readiness 报告会保留 passed action 的状态，但 `Recommendations` 只收未通过 action 和未通过组件的处理入口，避免 closeout 时重复执行已经收口的 identity/distribution 链。
其中 distribution closeout 会额外拆出 `distribution_signing_handoff / distribution_publish_handoff / distribution_publish_receipts` 子行动；缺失或失败的 publish target receipt 会进入 action blockers，并继续出现在 Release Promotion evidence/review/deployment 报告、Release Execution status/report 和 Portal Execution 面板的 readiness 段落里。若当前 delivery profile 的 `delivery_signing_required=false`，例如 staging 的 `sha256_only` 分发，`signing_handoff=skipped` 会被视为正确的非必需状态，不会生成 signing incomplete warning 或 next action。对应回归在 `tests/test_release_delivery_readiness.py`、`tests/test_release_promotion.py::ReleasePromotionPlanTestCase::test_release_promotion_report_builders_include_new_sections`、`tests/test_release_execution.py::ReleaseExecutionTestCase::test_release_execution_status_exposes_clean_machine_bootstrap_summary` 和 `tests/test_api.py::TestAPI::test_portal_index_exposes_release_execution_panel` 中覆盖。
同时，promotion ledger 现在也会持久化 `release_live_dispatch_*` 字段，所以 `GET /release-promotion/history`、`GET /release-promotion/history-report` 和 Portal `Release Promotion` 列表在 dispatch audit 文件缺失后仍能回放当次晋级对应的 dispatch 状态与 run 结论。

功能验收上下文现在使用 `feature_context 1.5`。`/plan`、`/execute-plan` 和 `POST /history/{task_id}/feature-review` 会保留 `dependency / eta / validation_method / blockers / artifact_links / external_links`，评审历史会记录 `reviewer / review_round / required_followups`；当评审状态为 `returned` 时，`required_followups` 会反向生成带 `review_followup` metadata 的待执行步骤。`POST /history/{task_id}/retry` 和 `/rollback` 会追加 `feature_lifecycle_events`，这些字段会继续进入 release summary 与 review bundle。

`/execute-plan` 的 editable step payload 也会保留 `status / requires_confirmation / metadata`。这保证从 returned review 生成的 follow-up step 在 Portal 里再次执行时不会丢失 `review_followup` 来源字段，也避免已成功步骤在重放计划时被无条件重置成 pending。

Portal 计划评审区的“执行复审待办”会复用同一 `/execute-plan` contract：本次提交中非 `review_followup` 步骤会标记为 `cancelled` 以跳过，仍未完成的 follow-up step 保持可执行。对应静态回归在 `tests/test_api.py::TestAPI::test_portal_index_exposes_release_promotion_panel` 中覆盖。

当所有 `review_followup` step 执行成功后，`/execute-plan` 会追加 `review_followups_completed` timeline event，清空已完成的 `required_followups`，移除同名 blockers，并把 `feature_status` 推回 `pending_acceptance`。对应 API 回归在 `tests/test_api.py::TestAPI::test_execute_plan_accepts_edited_steps` 中覆盖。

历史面板当前页的待验收任务可以通过 `/history/feature-review-batch` 批量二次验收通过或退回；批量请求支持 `source_feature_status / feature_id / owner / limit / offset / dry_run`，Portal 会先 dry-run 预览并确认数量。后端仍复用单任务 feature-review contract，逐个写入 `feature_review_history`、`feature_lifecycle_events` 与 blockers/followups 状态。对应 API 回归在 `tests/test_api.py::TestAPI::test_feature_review_batch_updates_pending_acceptance_tasks`、`tests/test_api.py::TestAPI::test_feature_review_batch_can_preview_filtered_tasks` 和 `tests/test_api.py::TestAPI::test_feature_review_batch_rejects_invalid_source_status` 中覆盖，Portal 静态入口在 `tests/test_api.py::TestAPI::test_portal_index_exposes_release_promotion_panel` 中覆盖。

其中 `feature-review` 也会写入 `review_*` 时间线事件；`returned` 会把评审意见或显式 blockers 转成 feature blockers，并在 Review Bundle 中形成阻断项。
Review Bundle Markdown 会额外展开 `Feature Timeline`、`Signoff Records`、`Review Follow-up Actions`、`Validation Records`、`Risk Summary` 与 `External Review Links`，并通过 `release_review_bundle 1.5` 自动把 `changed_paths` 分类成 code / scenes / resources / docs / other，从 required/provided/missing signoffs 生成逐角色审批记录，从 blocking/warning/signoff/validation/risk 缺口生成带 `owner_hint / dependency / eta / validation_method / blockers` 的复审行动，同时从 acceptance checklist、QA evidence 和 artifact links 生成验证记录，从 feature risk、known issues、feature blockers、blocking/warning items 生成风险摘要，直接列出 feature blockers、lifecycle events、review history、评审人/轮次/followups、审批状态、复审行动、改动范围、验证依据、风险面和 PR/CI/截图等外部依据。

如果你要单独导出当前 release manifest 对应的 versioned distribution bundle:

```powershell
python .\tools\export_release_distribution_bundle.py `
  --project-root . `
  --runtime-root . `
  --channel staging `
  --target-environment staging
```

这条命令会在 `logs/reports/release_distribution/<channel>/<build_id>/` 下生成 `distribution_manifest.json`、`install_release_bundle.ps1`、`upgrade_release_bundle.ps1`、`uninstall_release_bundle.ps1`、`support_matrix.md`、`release_manifest.json`、`release_notes.md`、`qa_gate_report.md`、`installed_release.example.json` 和 `release_payload/`，并把状态摘要写到 `logs/reports/release_distribution_bundle_<channel>.json`。`release_distribution_bundle` 现在还会吸收 `deployment/release_distribution_delivery.json` 中匹配当前 channel/environment 的 profile，把 installer/signing/publish 边界收成 `delivery_*` 字段。`release` 目标如果没有这份 distribution bundle，promotion / rehearsal / execution 报告会直接降级并阻断。

如果你还要验证这份 bundle 的安装链脚本确实能跑通:

```powershell
python .\tools\export_release_distribution_install_smoke.py `
  --project-root . `
  --runtime-root . `
 --channel staging `
  --target-environment staging
```

这条命令会在 `logs/reports/release_distribution_smoke/<channel>/<build_id>/` 下执行一次临时 `install -> upgrade -> uninstall`，并把汇总结果写到 `logs/reports/release_distribution_install_smoke_<channel>.json`。`release_distribution_bundle` contract 现在会直接读取这份 smoke 报告；`release` 目标如果没通过 install smoke，bundle 状态会继续停在 `warning`。
现在安装链 smoke 还会把 `state_path / installed_build_id / installed_version / previous_build_id / backup_dir / removed_build_id / removed_version` 一起回写到 `release_distribution_bundle_<channel>.json`，方便在 promotion / execution / CI artifact 中直接判断升级备份和卸载清理是否真实发生。

如果你还要补齐对外交付物 zip 和 checksum:

```powershell
python .\tools\export_release_distribution_archive.py `
  --project-root . `
  --runtime-root . `
 --channel staging `
  --target-environment staging
```

这条命令会在 `logs/reports/release_distribution_packages/<channel>/<build_id>/` 下生成 `release_distribution_bundle.zip` 与 `release_distribution_bundle.sha256`。导出完成后，`release_distribution_bundle_<channel>.json` 会刷新为最新 archive 状态；`release` 目标如果 archive 缺失，bundle 仍不会进入 `passed`。

如果你还要补齐渠道 latest / releases 索引:

```powershell
python .\tools\export_release_distribution_channel_index.py `
  --project-root . `
  --runtime-root . `
  --channel staging `
  --target-environment staging
```

这条命令会在 `logs/reports/release_distribution_channels/<channel>/` 下生成 `latest.json` 与 `releases.json`，并把汇总结果写到 `logs/reports/release_distribution_channel_<channel>.json`。`release_distribution_bundle_<channel>.json` 会同步刷新 channel index 状态；`release` 目标如果渠道 latest / releases 索引没有指向当前 archive，bundle 仍不会进入 `passed`。

如果你还要把这份 verified archive + 渠道索引收成一个可直接交给 QA / 发布执行侧的 handoff 安装包目录:

```powershell
python .\tools\export_release_distribution_handoff.py `
  --project-root . `
  --runtime-root . `
  --channel staging `
  --target-environment staging
```

这条命令会生成 `logs/reports/release_distribution_handoff/<channel>/<build_id>/`，包含 `distribution_handoff_manifest.json`、`install_release_handoff.ps1`、`upgrade_release_handoff.ps1`、`uninstall_release_handoff.ps1`、`packages/release_distribution_bundle.zip(.sha256)`、`channel/latest.json`、`channel/releases.json`，以及顶层 `release_manifest / release_notes / qa_gate_report / support_matrix` 副本。wrapper 脚本会临时解压 archive 并继续调用 bundle 内的 install/upgrade/uninstall 逻辑，所以消费侧不必保留原仓库里的 `logs/reports/...` 布局。`release_distribution_bundle_<channel>.json` 也会同步暴露 `handoff_status / handoff_dir / handoff_manifest_path`，供 promotion / execution / CI artifact 直接判断 handoff 包是否已收齐。

如果你要继续把 verified archive 收成可交给外部签名环节消费的 signing intake 包：

```powershell
python .\tools\export_release_distribution_signing_handoff.py `
  --project-root . `
  --runtime-root . `
  --channel release `
  --target-environment production
```

这条命令会生成 `logs/reports/release_distribution_signing/<channel>/<build_id>/`，包含 `distribution_signing_manifest.json`、`SIGNING_INSTRUCTIONS.md`、`unsigned/release_distribution_bundle.zip(.sha256)`，以及 `metadata/` 下的 release manifest / notes / QA gate / support matrix / channel index 副本。它不会执行真实外部签名，但会把当前 verified archive、signing profile 和 publish target 约束收成稳定 handoff；`release_distribution_bundle_<channel>.json` 也会同步暴露 `signing_handoff_status / signing_handoff_dir / signing_handoff_manifest_path`。

```powershell
python .\tools\export_release_distribution_publish_handoff.py `
  --project-root . `
  --runtime-root . `
  --channel release `
  --target-environment production
```

这条命令会生成 `logs/reports/release_distribution_publish/<channel>/<build_id>/`，包含 `distribution_publish_manifest.json`、`PUBLISH_INSTRUCTIONS.md`、`payload/release_distribution_bundle.zip(.sha256)`、`metadata/` 下的 release manifest / notes / QA gate / support matrix / channel index 副本，以及 `inputs/` 下的 portable/signing handoff manifest 副本和 `targets/publish_targets.json`。它不会执行真实外部发布，但会把“当前 verified archive 应该往哪些 publish target 推进、签名链路如何接入”收成稳定 intake；`release_distribution_bundle_<channel>.json` 也会同步暴露 `publish_handoff_status / publish_handoff_dir / publish_handoff_manifest_path`。

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

这条命令会在 `logs/reports/release_distribution_publish_receipts/<channel>/<build_id>/` 下生成 `publish_receipts_manifest.json` 和 `receipts/<target_id>.json`，把外部分发回执重新绑定到当前 `build_id / version / channel`。`release_distribution_bundle_<channel>.json` 也会同步暴露 `publish_receipts_status / publish_receipts_dir / publish_receipts_manifest_path / publish_receipts_missing_targets`。

如果你还要把当前渠道的 request-auth / issuer registry / identity boundary 审计收成一个 redacted identity intake 包:

```powershell
python .\tools\export_release_request_auth_identity_handoff.py `
  --project-root . `
  --runtime-root . `
  --channel release `
  --target-environment production `
  --release-manifest-path api_server/static/dist/release_manifest.json
```

这条命令会生成 `logs/reports/release_request_auth_identity_handoff/<channel>/<environment>/`，包含 `identity_boundary_handoff_manifest.json`、`IDENTITY_HANDOFF_INSTRUCTIONS.md`、`audits/` 下的 redacted posture / rotation / identity 审计，以及 `deployment/` 下的 `release_identity_boundary.json` / `release_identity_registry.json` 副本。它不会把 `deployment/release_request_auth.json` 带进 handoff，但会把“当前 release 身份边界如何外部化”收成稳定 intake；`request_auth_identity_audit` 现在也会同步暴露 `identity_handoff_status / identity_handoff_dir / identity_handoff_manifest_path`。

Windows PowerShell 下，如果你要执行完整的 live sandbox 联调回归，直接使用:

```powershell
.\tools\run_live_sandbox_tests.ps1 -ApiPort 8011
```

这条命令会自动完成 `start_live_sandbox.ps1`、`tests/test_live_sandbox.py` 和 `stop_live_sandbox.ps1`。

如果你要一次跑完当前全部真实自动化验证，使用:

```powershell
.\tools\run_full_live_validation.ps1
```

这条命令会依次执行 Godot live sandbox、扩展 production flow live、Portal DOM smoke、Portal 点击式 browser smoke 和 Remote MCP live smoke。
执行结束后还会把汇总结果写到 `logs/reports/full_live_validation.json`，并为每条 lane 额外写出 `logs/reports/full_live_validation_lanes/<lane>.json`，供 `Release Promotion Evidence / Review Bundle / Release Execution Report` 和 CI rehearsal artifact bundle 复用。像 `portal_click_smoke` 这样的 lane 还会把 `release_promotion_history_report_flow` 等子 flow 状态一起固化进 lane report / normalized contract。
总报告会固定输出 `release_binding(build_id / version / channel / manifest_path)`、lane 级 `artifact_paths` 和 lane report 路径；每条 lane report 会固定输出 `build_id / version / channel / executed_at / report_path`，promotion / execution 会对照当前 release manifest 或 execution ledger 检查是否一致。

如果你要验证 Portal 真实浏览器加载路径，使用:

```powershell
.\tools\run_portal_browser_smoke.ps1
python .\tools\run_portal_browser_click_smoke.py
```

第一条会启动本地 API，并用无头 Chrome/Edge 检查 Portal DOM 中的 `质量面板 / 治理准入 / 生产验证 / Release Candidate / Build / Run Matrix / Agent 兼容性 / Release Promotion / Release Execution / MCP / IDE / 美术资产 Intake / 外包交付 Gate / 资产评审 / 场景归属 / 锁定 / 表现层 Pipeline / 运营配置 / LiveOps / 遥测回流 / 性能分析 / 平台交付 / Savegame` 标记。第二条会通过 Chrome DevTools Protocol 真实点击治理、生产验证、Release Candidate、Build / Run Matrix、Agent 兼容性、Release Promotion 及其 Evidence/Deployment/Rollback 导出、History 记录和 `History Report` 导出、Release Execution 的 `dry_run / canary / full_rollout / rollback`、LiveOps、遥测导出、性能画像导出、美术 intake、外包交付 Gate、资产评审、场景归属、表现层和平台交付链路。点击式 smoke 会先在它的临时项目下写入最小 `deployment/release_*` 基线，让 release promotion / execution 写接口在隔离项目里按当前 staging policy 通过，而不是因为 temp project 缺少 manifests 直接失败。

## 当前测试覆盖重点

- 路由器初始化与历史恢复
- 多步骤规划与执行
- 上下文感知节点注入
- 属性更新脚本生成
- CLI `chat` 分发
- 资源导出路由
- 资源审计自动修复预览与应用
- 类 / 函数 / 信号安全重构
- 端到端冒烟脚本生成
- API 计划编辑链路

## Mock 策略

大部分测试使用 `MockGodotCLI`，避免真实依赖 Godot 可执行文件。

这意味着:

- 逻辑回归很快
- 规划与任务编排可以稳定测试
- 真实引擎链路仍需手工验证
- 端到端测试命令当前主要验证“脚本生成与调用链路”，不代表截图或输入回放已在真实引擎中逐帧验收

## 编写新测试

当前 `execute()` 返回 `Task`，断言应该围绕 `status`、`steps`、`artifacts` 和 `logs`：

```python
import unittest
from agent_system.router import GodotAgentRouter
from agent_system.models import TaskStatus


class TestMyFeature(unittest.TestCase):
    def setUp(self):
        self.agent = GodotAgentRouter()

    def test_generate_script(self):
        task = self.agent.execute("生成 2D 玩家移动脚本", confirm=True)
        self.assertEqual(task.status, TaskStatus.SUCCESS)
        self.assertTrue(any(a.type == "script" for a in task.artifacts))
```

## 手工回归建议

每次改完核心逻辑，至少跑这几条:

```bash
python -m agent_system.cli plan "导出 Web 项目"
python -m agent_system.cli run "导出 Web 项目" -y
python -m agent_system.cli plan "验证玩家跳跃功能"
python -m agent_system.cli plan "预览修复项目资源命名"
python -m agent_system.cli plan "重命名类 PlayerController 为 HeroController"
python -m agent_system.cli plan "端到端测试 res://scenes/main_scene.tscn 并向右跳跃后截图"
python -m agent_system.cli chat
```

说明:

- `导出 Web 项目` 应该规划到 `resource_manager`
- `验证玩家跳跃功能` 应该规划到 `tester`
- `预览修复项目资源命名` 应该规划到 `resource_manager`
- `重命名类 PlayerController 为 HeroController` 应该规划到 `code_generator`
- `端到端测试 ...` 应该规划到 `tester`
- `chat` 应该真正进入交互模式

API 侧还应覆盖:

- `POST /plan` 能返回 `awaiting_confirmation` 的可编辑任务
- `POST /execute-plan` 能接受修改后的步骤顺序和角色
- `POST /editor/operation` 能排队类型化编辑器操作，并在 live Godot 中跑通创建、选择、属性设置、场景树读取、删除、保存、重载、复制、重挂、重命名、排序、批量操作、脚本挂载和场景实例化
- `POST /levels/manage` 能统一执行 `template / preview / audit / snapshot / diff` 关卡工作流，并返回 `level_workflow` 结构化数据
- `GET /gameplay/templates` 能返回玩法模板快照，`POST /gameplay/manage` 能统一执行 `preview / apply` 并把 starter gameplay systems 写回蓝图
- `GET /presentation/profiles` 能返回 animation / vfx / shader / audio 表现层 profile 快照，`POST /presentation/manage` 能统一执行 `template / validate / preview / apply` 并产出受管 manifest 与 scaffold
- `GET /portal/index.html` 现在会包含 `表现层 Pipeline` 面板和 `presentation-*` 控件，Portal browser smoke / click smoke 也会覆盖该面板
- `GET /liveops/profiles` 能返回 `remote_config / experiment_catalog` LiveOps profile 快照，`POST /liveops/manage` 能统一执行 `template / validate / preview / apply` 并产出 `liveops/remote_config.json` 与 `liveops/experiments.json`
- `GET /portal/index.html` 现在会包含 `运营配置 / LiveOps` 面板和 `liveops-*` 控件，Portal browser smoke / click smoke 也会覆盖该面板
- `GET /portal/index.html` 现在还会包含 `遥测回流` 与 `性能分析` 面板，以及 `telemetry-*` / `performance-*` 控件；其中 telemetry 面板会展示 `Privacy Gate / Retention / Funnel Breakdown / Retention / Funnel Dashboard / Crash Taxonomy / Crash Clusters / Crash Regression`，并提供 `导出留存漏斗报告` 与 `导出 Crash 报告` 按钮；Portal browser smoke / click smoke 会覆盖这两条面板链路
- `GET /telemetry/trends` 能直接返回当前 telemetry snapshot 的 retention/funnel 趋势 dashboard 和 Markdown 摘要
- `GET /liveops/impact-dashboard` 能直接返回当前 telemetry 与 LiveOps manifest 关联后的 impact dashboard 和 Markdown 摘要
- `GET /telemetry/crash-clusters` 能直接返回当前 telemetry snapshot 的 crash cluster 列表和 Markdown 排障摘要
- `GET /telemetry/crash-dashboard` 能直接返回当前 telemetry snapshot 的 build/scene crash regression dashboard 和 Markdown 摘要
- `GET /telemetry/retention-dashboard` 能直接返回当前 telemetry snapshot 的 retention/funnel dashboard 和 Markdown 摘要
- `GET /performance/dashboard` 能直接返回当前性能画像的 `frame_breakdown / memory_trend` 和 Markdown 摘要
- `GET /platform-delivery/profile` 能返回平台交付 baseline 快照，`POST /platform-delivery/manage` 能统一执行 `template / validate / preview / apply`
- `GET /portal/index.html` 现在会包含 `平台交付 / Savegame` 面板和 `platform-delivery-*` 控件，Portal browser smoke / click smoke 也会覆盖该面板
- `GET /release-candidate/checklist` 与 `POST /release-candidate/checklist` 能返回统一 `release_candidate_checklist` contract，收敛 release manifest、QA gate、performance/telemetry gate、rollback 和 production gate；`GET /portal/index.html` 现在也会包含 `Release Candidate` 面板与 `release-candidate-*` 控件
- `GET /art-assets/profiles` 能返回 art intake profile 快照，`POST /art-assets/manage` 能统一执行 `template / validate / preview / apply`
- `manage_art_asset_pipeline` 现在已覆盖 `model / aseprite / spine / substance / outsource` DCC/交付 profile，并会校验 sidecar 依赖、LOD、texture set、版本和授权字段
- `GET /portal/index.html` 现在会包含 `美术资产 Intake` 面板和 `art-asset-*` 控件，Portal browser smoke / click smoke 也会一并覆盖该面板
- `GET /outsource-delivery/gate` 与 `POST /outsource-delivery/gate` 能返回统一 `outsource_delivery_gate` contract，收敛 manifest、package_root、metadata、license scope、target package、traceability 和预算检查；`GET /portal/index.html` 现在也会包含 `外包交付 Gate` 面板与 `outsource-gate-*` 控件
- `GET /asset-reviews/workflow` 与 `POST /asset-reviews/manage` 能返回统一 `asset_review_workflow` contract，并把 review board manifest、per-asset `pending_review / approved / returned`、reviewer、review_note 和一致性检查收敛到同一份结构；`GET /portal/index.html` 现在也会包含 `资产评审` 面板与 `asset-review-*` 控件
- `GET /build-run/matrix` 与 `POST /build-run/matrix` 能返回统一 `build_run_matrix` contract，把平台交付 target、production gate、RC checklist 和 `non-live / browser / live / remote MCP` 验收 lane 收敛到同一份 matrix；`GET /portal/index.html` 现在也会包含 `Build / Run Matrix` 面板与 `build-run-matrix-*` 控件
- `GET /scene-ownership/board` 与 `POST /scene-ownership/manage` 能返回统一 `scene_ownership_board` contract，把 `owner / feature_id / lock_state / source_manifest_path / orphan_count` 收敛到同一份场景协作 board；`GET /portal/index.html` 现在也会包含 `场景归属 / 锁定` 面板与 `scene-ownership-*` 控件
- `GET /release-promotion/plan` 与 `POST /release-promotion/plan` 能返回统一 `release_promotion_plan` contract，把 `release_candidate_checklist / build_run_matrix / agent_provider_compatibility / scene_ownership_board / signoff_gate / evidence_bundle / deployment_rehearsal / rollback_rehearsal` 收敛到同一份晋级决策；`GET /release-promotion/evidence-report`、`GET /release-promotion/deployment-rehearsal`、`GET /release-promotion/rollback-rehearsal` 与 `GET /release-promotion/history-report` 会返回可直接导出的 Markdown 报告；`GET /release-promotion/history` 与 `POST /release-promotion/record` 会把实际晋级结论、执行人和 `plan_snapshot` 持久化到 `deployment/release_promotion_history.json`；`GET /portal/index.html` 现在也会包含 `Release Promotion` 面板、`release-promotion-*` 控件，以及直接导出 `History Report` 的入口
- `release_promotion_plan` 现在还会直接消费 `logs/reports/release_live_ci/release_live_ci_summary.json`，把 `ci_gate / runtime_gates / runtime_lanes.full_live_validation / human_signoffs` 带进 `plan / evidence / review bundle / deployment rehearsal`；`release` 目标下如果这份 summary 缺失，`release_live_ci_summary_gate` 会直接进入 checklist、evidence artifact 和 deployment preflight blocker
- `release_live_ci_summary` 里的 `workflow_steps` 现在也会继续进入 `release_promotion_plan` / `release_execution_status` 的结构化 contract 与 Markdown 报告；Portal 的 `Release Live CI` 面板同样会直接显示这些 step 级诊断，不必再手动打开 summary JSON 才能看出失败发生在哪一步
- `release_live_ci_summary` 现在还会额外暴露 `event_stream`，把 `run_started / step_finished / lane_reported / gate_evaluated / run_finished` 收成 `release_live_ci_events.json`；`GET /release-live-ci/events`、Portal 的 `Release Live CI` 面板，以及 promotion/execution/history 报告都会继续消费这条时间线，便于直接定位 fixed runner 的最新失败事件
- `release_runtime_assembly_snapshot` 现在也会继续进入这条链：`tests/test_release_runtime_assembly.py` 直接验证 helper 会把 `route_kind / route_id / session_id / invocation_source / actor_id / enabled_capabilities / denied_capabilities / identity_boundary / runner_profile` 汇成统一快照，而 `tests/test_release_live_event_stream.py`、`tests/test_release_live_ci_artifacts.py`、`tests/test_release_ci_artifacts.py`、`tests/test_release_promotion.py`、`tests/test_release_execution.py` 与 `tests/test_api.py` 会继续验证这份快照和 `event_stream` 已经进入 `release_live_ci_summary`、artifact manifest、promotion/execution/history report 和 Portal `Release Live CI` 面板
- `release_promotion_history` 现在也会把 `release_delivery_readiness_status / release_delivery_readiness_next_actions`、`release_live_ci_status / release_live_ci_workflow_step_results_path / release_live_ci_workflow_steps / release_live_ci_failed_workflow_steps` 和 Review Bundle 的 `review_followup_actions` 从 `plan_snapshot` 提升为 ledger 顶层字段；因此 `GET /release-promotion/history-report` 和 Portal 的 history export 不必再反查 plan snapshot，就能直接看出 latest promotion 的 delivery readiness next actions、live CI 是 passed、warning 还是 blocked、fixed runner 失败卡在哪一个 workflow step，以及还有哪些复审行动未收口。history API/Portal 现在还支持额外按 `delivery_readiness_status / readiness_action / dispatch_status / dispatch_follow_up / dispatch_run_status / dispatch_run_conclusion` 过滤，所以可以直接筛出 readiness 处于 `warning / blocked`、卡在 `distribution_publish_receipts` 等具体 action、GitHub workflow dispatch 本身处于 `warning / blocked`、仍待 follow-up、run 仍处于 `queued / in_progress / completed`，或进一步聚焦最终 run 结论是 `success / failure` 的那一批晋级记录，而不必人工逐条翻最近 history
- Portal 的 `Release Promotion` history 面板现在也会直接把 `release_delivery_readiness_status / readiness_actions` 和 `release_live_ci_status / failed_steps / workflow_step_results_path` 渲染出来，并提供 readiness status/action 过滤；如果 latest promotion 的 delivery readiness、fixed runner baseline、distribution 或 full live validation 卡住，不必先导出 `history-report` 才能在 UI 中看到
- `GET /release-promotion/history` 与 `GET /release-promotion/history-report` 现在支持 `live_ci_status` 过滤；Portal 的 `Release Promotion` history 下拉会把这个查询参数直接带到 API，用来快速筛出 `warning / blocked` 的 live CI promotion 记录
- 同一组 history 接口现在也支持 `failed_workflow_step` 过滤；Portal 的 history 输入框会把它直接带到 API，用来快速聚焦 `run_full_live_validation` 这类具体失败 step 的 promotion 记录
- `deployment/release_access_policy.json` 现在会作为本地 release 写操作授权清单，绑定 `actor_id -> roles -> promotion_record / release_execution` 规则；`deployment/release_request_auth.json` 可按 `token_id / token_sha256 / actions / channels / target_environments / actor_ids / expires_at / session_id / issued_by / issued_at` 管理可轮换 token；`deployment/release_identity_registry.json` 则把 `issued_by` 继续绑定到 active issuer、允许的 `subject_actor_ids`、渠道/环境范围，以及可选的 `session_required / max_session_age_hours`。`POST /release-promotion/record`、`POST /release-execution/run` 与 `POST /release-execution/rollback` 会接受 `Authorization: Bearer <token>` / `X-Godot-Agent-Release-Token` 请求认证，未通过请求认证、issuer registry 或 actor 授权的写操作都会返回 `400`
- `tools/export_release_ci_artifacts.py` 会继续导出 `deployment/release_access_policy.json` 与 `deployment/release_identity_registry.json`，但不会复制 `deployment/release_request_auth.json`，因为后者可能包含可轮换 token 的摘要配置；替代地，CI artifact 里现在会带 redacted `runtime_reports/release_request_auth_posture_*.json`、`runtime_reports/release_request_auth_rotation_audit_*.json`、`runtime_reports/release_request_auth_identity_audit_*.json`，以及额外的 `release_distribution_publish/`、`release_distribution_publish_receipts/` 和 `release_request_auth_identity_handoff/`
- `python tools/generate_release_request_token_digest.py --token-id ... --token-value ... --expires-at ... --session-id ... --issued-by ... --issued-at ...` 可以本地生成 `release_request_auth.json` 的 digest 片段；`python tools/export_release_request_auth_posture.py --action ... --channel ...` 可以把当前 posture 单独导出为 redacted runtime report，`python tools/export_release_request_auth_rotation_audit.py --channel ...` 可以把当前渠道下 `promotion_record + release_execution` 的覆盖和 rotation 缺口汇总成聚合审计，`python tools/export_release_request_auth_identity_audit.py --channel ...` 则会把 scoped issuer、subject actor 绑定、重复 `issuer_id`、stale session 与 `release` 渠道 session policy 汇总成独立审计。`Release Promotion` / `Release Execution` 的 payload 和 Markdown 报告现在也会额外包含 `request_auth_posture`、`request_auth_rotation_audit` 与 `request_auth_identity_audit`；前者汇总当前 action/channel 下的 token 覆盖、local bypass、env fallback、actor 绑定、`expires_at` hygiene、session 跟踪状态、identity registry 覆盖与 session freshness 状态，第二层汇总同一渠道下两个高风险写 action 的覆盖计数、缺口和 rotation 建议，第三层单独审计 issuer registry 本身的 scope / subject / session policy。`release` 目标下如果这三层任一不是 `passed`，对应的 `request_auth_posture_gate / request_auth_rotation_audit_gate / request_auth_identity_audit_gate` 都会直接卡住 promotion checklist、evidence bundle、review bundle 和 deployment rehearsal
- `GET /release-execution/status`、`POST /release-execution/run` 与 `POST /release-execution/rollback` 能返回统一 `release_execution_status` contract，并把 execution ledger 与 active channel binding 分别持久化到 `deployment/release_execution_status.json` 与 `deployment/release_channels.json`；最新 execution 会额外包含结构化 `authorization` 结果。`clean_machine_bootstrap`、`full_live_validation`、`release_live_ci_summary` 和当次 `release_delivery_readiness_*` 摘要现在都会一起进入 execution status/report，其中 `release_live_ci_summary` 会把 `ci_gate / runtime_gates / runtime_lanes.full_live_validation / human_signoffs` 直接暴露出来；latest `plan_snapshot.review_bundle.review_followup_actions` 也会进入 execution status/report，报告和 Portal `Release Execution` 面板中的 `Review Follow-up Actions` 会继续保留 owner、依赖、ETA、验证方法和 blockers，execution ledger 列表也会直接显示当次 delivery readiness status/action 摘要；`GET /portal/index.html` 现在也会包含 `Release Execution` 面板与 `release-execution-*` 控件
- `python -m pytest tests/test_level_workflow.py -q` 能覆盖 P8 关卡模板、审计、snapshot/diff 和 prompt 路由
- `python -m pytest tests/test_gameplay_template_skill.py -q` 能覆盖 P9 玩法模板 skill、蓝图落地和 prompt 路由
- `python -m pytest tests/test_art_pipeline.py -q` 能覆盖 P11 扩展后的 art intake、Blender/GLTF sidecar 复制、外包交付校验和 prompt 路由
- `python -m pytest tests/test_api.py -k "art_asset or art_assets" -q` 能覆盖 P11 art intake API 快照、preview/apply 和失败返回
- `python -m pytest tests/test_presentation_pipeline_skill.py -q` 能覆盖 P10 表现层 skill、蓝图落地和 prompt 路由
- `python -m pytest tests/test_liveops_pipeline_skill.py -q` 能覆盖 P12 LiveOps skill、manifest 落地和 prompt 路由
- `python -m pytest tests/test_telemetry_pipeline.py -q` 能覆盖 P12 遥测留存窗口、漏斗拆解、crash taxonomy、crash cluster、crash regression dashboard 和隐私门禁
- `python -m pytest tests/test_production_samples.py -q` 能覆盖仓库内置 telemetry/performance 样本是否仍然产出 `D1 / D3 / D7 retention`、crash taxonomy 和 richer budget 指标
- `python -m pytest tests/test_api.py -k "gameplay_template or gameplay_templates" -q` 能覆盖 P9 API 入口、模板快照和失败返回
- `python -m pytest tests/test_api.py -k "presentation" -q` 能覆盖 P10 API 入口、profile 快照和失败返回
- `python -m pytest tests/test_api.py -k "liveops" -q` 能覆盖 P12 API 入口、profile 快照、preview/apply 和失败返回
- `python -m pytest tests/test_api.py -k "telemetry" -q` 能覆盖 P12 遥测 API 快照、retention/privacy summary 和失败返回
- `python -m pytest tests/test_api.py -k "level_workflow or manage_level_workflow" -q` 能覆盖 P8 API 入口、快照 diff 和审计失败返回
- `.\tools\run_live_sandbox_tests.ps1 -PytestArgs @('tests/test_live_production_flows.py::test_p8_level_workflow_manage_endpoint_supports_snapshot_and_diff_live','-v','-s')` 能单独验证 P8 `/levels/manage` live 闭环
- `.\tools\run_live_sandbox_tests.ps1 -PytestArgs @('tests/test_live_production_flows.py::test_p9_gameplay_template_manage_endpoint_supports_preview_and_apply_live','-v','-s')` 能单独验证 P9 `/gameplay/manage` live 闭环
- `.\tools\run_live_sandbox_tests.ps1 -PytestArgs @('tests/test_live_production_flows.py::test_p10_presentation_manage_endpoint_supports_preview_and_apply_live','-v','-s')` 能单独验证 P10 `/presentation/manage` live 闭环
- `.\tools\run_live_sandbox_tests.ps1 -PytestArgs @('tests/test_live_production_flows.py::test_p11_art_dcc_profiles_execute_live','-v','-s')` 能单独验证 P11 Blender/GLTF intake live 闭环
- `.\tools\run_live_sandbox_tests.ps1 -PytestArgs @('tests/test_live_production_flows.py::test_p11_art_asset_manage_endpoint_supports_model_profile_live','-v','-s')` 能单独验证 P11 `/art-assets/manage` live 闭环
- `.\tools\run_live_sandbox_tests.ps1 -ApiPort 8011` 能跑通 live sandbox 七项真实联动测试
- `.\tools\run_live_sandbox_tests.ps1 -PytestArgs @('tests/test_live_sandbox.py::test_6_typed_editor_operations','-v','-s')` 能单独验证 Godot 引擎内实时操作链路
- `.\tools\run_live_sandbox_tests.ps1 -PytestArgs @('tests/test_live_sandbox.py::test_7_p7_editor_operations','-v','-s')` 能单独验证 P7 编辑器操作扩展链路
- `.\tools\run_live_sandbox_tests.ps1 -PytestArgs @('tests/test_live_sandbox.py','tests/test_live_production_flows.py','-v','-s')` 能跑通 Godot live + P1/P5/P6/P7 扩展 live 测试；P8/P9/P10/P11 已补充独立 API/live 用例
- `.\tools\run_portal_browser_smoke.ps1` 能跑通 Portal browser smoke
- `python .\tools\run_portal_browser_click_smoke.py` 能跑通 Portal 点击式 browser smoke
- `.\tools\run_remote_mcp_live_smoke.ps1` 能跑通 Remote MCP live smoke
- `.\tools\run_remote_mcp_live_smoke.ps1` 现在会给 `godot_production_validate / godot_agent_compat` 预留 120 秒 HTTP 预算，并在失败时明确输出 `step=<...>`，避免真实仓库上的 production validate 因默认 30 秒超时而把 Remote MCP live lane 误判成脚本失败
- `python -m pytest -m "not live" -q` 能覆盖当前全部非 live 自动化测试

## 注意

- 没有 Godot 环境时，场景创建和真实场景测试可能失败，这是环境限制，不一定是逻辑缺陷。
- 对这类能力，优先验证规划结果、脚本生成结果和失败路径是否符合预期。

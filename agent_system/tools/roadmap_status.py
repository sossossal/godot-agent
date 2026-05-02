"""Machine-readable status ledger for the standardization roadmap."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

from agent_system.contracts import normalize_roadmap_status


DEFAULT_ROADMAP_DOC_PATH = "docs/游戏开发标准化增强路线图.md"


ROADMAP_ITEMS: List[Dict[str, Any]] = [
    {
        "item_id": "p0_contracts",
        "phase": "P0",
        "title": "统一契约层",
        "status": "done",
        "summary": "核心合同目录、版本清单和 normalize_on_read 已覆盖主链路。",
        "evidence": ["agent_system/contracts", "GET /contracts/versions"],
    },
    {
        "item_id": "p0_layout_rules",
        "phase": "P0",
        "title": "文件树与命名规范引擎",
        "status": "done",
        "summary": "项目布局校验已存在，P19 game-create、data table/export、movement/AI/dialogue 脚本生成入口、wiring/animation/signal bus 修改型 code skill，以及 input/attach/create_scene/setup_3d/instantiate/physics 编辑器操作链路已在写入或派发前接入受管输出校验；非法路径会返回 preview-only 自动修复建议落点。",
        "remaining_work": [],
        "next_action": "",
        "evidence": ["agent_system/validations/project_layout.py", "agent_system/tools/game_creation_wizard.py", "doctor"],
    },
    {
        "item_id": "p0_template_registry",
        "phase": "P0",
        "title": "模板注册中心",
        "status": "done",
        "summary": "genre template registry 已可用，P19 已覆盖 platformer/topdown/tower_defense/arpg/roguelike/visual_novel/survival_crafting 七个 zero-to-playable 模板，写入前会通过 game_creation 治理准入，模板迁移策略也已可生成；viewport baseline 剩余工作已归入回放资产/P19 验证。",
        "remaining_work": [],
        "next_action": "",
        "evidence": ["agent_system/tools/template_registry.py", "agent_system/tools/game_creation_wizard.py"],
    },
    {
        "item_id": "p0_skill_baseline",
        "phase": "P0",
        "title": "Skill 统一基线",
        "status": "done",
        "summary": "主链 skill result envelope 已落地，legacy skill 已清除裸 ToolResult 返回，audio/resource audit 等旧入口也统一输出 schema/validation/rollback 与 artifact metadata。",
        "remaining_work": [],
        "next_action": "",
        "evidence": ["agent_system/contracts/skill_results.py", "governance/admission"],
    },
    {
        "item_id": "p0_budget_replay",
        "phase": "P0",
        "title": "预算系统与回放资产",
        "status": "done",
        "summary": "性能 baseline、live/browser smoke、P19 runtime playability smoke，以及 P19 输入回放/golden screenshot 计划资产、headless replay 脚本生成器、Godot headless/viewport 执行、baseline promote 流程、live sandbox 固定 lane、full live validation lane evidence、viewport baseline readiness 监控字段和首批 tower_defense viewport golden screenshot baseline promotion 已存在。",
        "remaining_work": [],
        "next_action": "",
        "evidence": ["tests/baselines/performance", "tools/run_full_live_validation.ps1"],
    },
    {
        "item_id": "p1_art_pipeline",
        "phase": "P1/P11/P15",
        "title": "美术内容生产链路",
        "status": "done",
        "summary": "DCC profile、外包 Gate、资产评审、provenance/license 覆盖率报告、spritesheet/aseprite 图集计划和材质资源链接审计已落地。",
        "remaining_work": [],
        "next_action": "",
        "evidence": ["agent_system/skills/resource/art_asset_skill.py", "agent_system/tools/outsource_delivery.py", "agent_system/tools/asset_review.py"],
    },
    {
        "item_id": "p1_level_workflow",
        "phase": "P1/P8",
        "title": "关卡编辑器级工作流",
        "status": "done",
        "summary": "关卡 template/preview/audit/snapshot/diff 和 live 验证已落地。",
        "evidence": ["agent_system/skills/dev/level_workflow_skill.py", "POST /levels/manage"],
    },
    {
        "item_id": "p1_balance",
        "phase": "P1",
        "title": "数值平衡分析",
        "status": "done",
        "summary": "基础敌人/任务/掉落分析、baseline-vs-candidate 版本对比、可复现战斗仿真和成长曲线审计已可用。",
        "remaining_work": [],
        "next_action": "",
        "evidence": ["agent_system/tools/balance_analysis.py", "balance_version_compare", "combat_simulation", "growth_curve_audit"],
    },
    {
        "item_id": "p1_telemetry",
        "phase": "P1/P12",
        "title": "运营数据与遥测回流",
        "status": "done",
        "summary": "telemetry_summary、retention、crash dashboard、LiveOps impact 已落地。",
        "evidence": ["agent_system/tools/telemetry_analysis.py", "GET /telemetry/trends", "GET /liveops/impact-dashboard"],
    },
    {
        "item_id": "p1_performance",
        "phase": "P1/P14",
        "title": "重型性能画像体系",
        "status": "done",
        "summary": "frame_breakdown/memory_trend、runtime 性能采样 Build / Run Matrix lane、截图 baseline diff 比对、内存趋势回归报告和 Godot headless capture_performance_profile 已落地。",
        "remaining_work": [],
        "next_action": "",
        "evidence": ["agent_system/tools/performance_analysis.py", "GET /performance/dashboard", "GET /build-run/matrix"],
    },
    {
        "item_id": "p2_migrations",
        "phase": "P2",
        "title": "迁移与兼容层",
        "status": "done",
        "summary": "MigrationRunner、status/apply API 和模板 marketplace 状态已落地。",
        "evidence": ["agent_system/migrations", "GET /migrations/status"],
    },
    {
        "item_id": "p2_quality_dashboard",
        "phase": "P2",
        "title": "统一质量面板",
        "status": "done",
        "summary": "质量面板聚合 contract/layout/template/skill/telemetry/performance/migrations。",
        "evidence": ["agent_system/tools/quality_dashboard.py", "GET /quality/dashboard"],
    },
    {
        "item_id": "p2_remote_mcp",
        "phase": "P2/P6",
        "title": "远程 MCP 与部署接入",
        "status": "done",
        "summary": "HTTP bridge、remote manifest 和 remote MCP smoke 已落地。",
        "evidence": ["bridge/remote_mcp_server.py", "GET /mcp/remote-manifest"],
    },
    {"item_id": "p3_governance", "phase": "P3", "title": "项目治理与变更准入", "status": "done", "summary": "governance policy/admission 与 Portal 面板已落地。", "evidence": ["GET /governance/policy", "POST /governance/admission"]},
    {"item_id": "p4_enforcement", "phase": "P4", "title": "自动化准入执行与 CI 门禁", "status": "done", "summary": "governance enforcement、CLI 和 PowerShell wrapper 已落地。", "evidence": ["POST /governance/enforce", "tools/enforce_governance.ps1"]},
    {"item_id": "p5_production", "phase": "P5", "title": "生产规模验证与真实项目交付", "status": "done", "summary": "production readiness、Portal、CLI、live production flow 已落地。", "evidence": ["POST /production/validate", "tests/test_live_production_flows.py"]},
    {"item_id": "p6_agent_compat", "phase": "P6", "title": "多 Agent/API 兼容矩阵", "status": "done", "summary": "provider compatibility matrix、stdio/remote MCP schema 和 Portal 面板已落地。", "evidence": ["GET /agent-compat/matrix"]},
    {"item_id": "p7_editor_ops", "phase": "P7", "title": "Godot 引擎内实时操作扩展", "status": "done", "summary": "editor_operation 1.1、保存/重载/批量/实例化/live 测试已落地。", "evidence": ["POST /editor/operation", "tests/test_live_sandbox.py::test_7_p7_editor_operations"]},
    {"item_id": "p9_gameplay_templates", "phase": "P9", "title": "按游戏类型补 Gameplay 系统模板", "status": "done", "summary": "starter gameplay systems、模板快照和 API/CLI 路由已落地。", "evidence": ["agent_system/tools/template_registry.py"]},
    {"item_id": "p10_presentation", "phase": "P10", "title": "动画、VFX、Shader、Audio 专项链路", "status": "done", "summary": "presentation pipeline template/validate/preview/apply 已落地。", "evidence": ["agent_system/skills/resource/presentation_skill.py"]},
    {"item_id": "p13_platform_delivery", "phase": "P13", "title": "平台交付 / Savegame 基线", "status": "done", "summary": "platform delivery profile、API、Portal 和样本已落地。", "evidence": ["POST /platform-delivery/manage"]},
    {"item_id": "p15_release_candidate", "phase": "P15", "title": "Release Candidate Checklist", "status": "done", "summary": "RC checklist builder、API、Portal 和浏览器 smoke 已落地。", "evidence": ["GET /release-candidate/checklist"]},
    {"item_id": "p15_outsource_delivery", "phase": "P15", "title": "Outsource Delivery Gate", "status": "done", "summary": "外包交付 gate、Portal、API 和回归已落地。", "evidence": ["GET /outsource-delivery/gate"]},
    {"item_id": "p15_asset_review", "phase": "P15", "title": "Asset Review Workflow", "status": "done", "summary": "资产评审 board、批量决策和 Portal 面板已落地。", "evidence": ["GET /asset-reviews/workflow"]},
    {"item_id": "p15_build_run_matrix", "phase": "P15", "title": "Build / Run Matrix", "status": "done", "summary": "build target、production gate、RC、runtime performance sampling 和 live lanes 已统一成 matrix。", "evidence": ["GET /build-run/matrix"]},
    {"item_id": "p15_scene_ownership", "phase": "P15", "title": "Scene Ownership / Lock Hints", "status": "done", "summary": "场景 ownership board、锁定状态和 Portal 面板已落地。", "evidence": ["GET /scene-ownership/board"]},
    {"item_id": "p16_promotion_plan", "phase": "P16", "title": "Release Promotion Plan", "status": "done", "summary": "晋级计划、证据、部署/回滚 rehearsal 已落地。", "evidence": ["GET /release-promotion/plan"]},
    {"item_id": "p17_promotion_history", "phase": "P17", "title": "Release Promotion History", "status": "done", "summary": "渠道晋级 ledger、筛选、报告和 Portal record 已落地。", "evidence": ["GET /release-promotion/history"]},
    {"item_id": "p18_release_execution", "phase": "P18", "title": "Release Execution / Rollout Control", "status": "done", "summary": "dry_run/canary/full_rollout/rollback execution ledger 已落地。", "evidence": ["GET /release-execution/status"]},
    {
        "item_id": "p19_game_creation",
        "phase": "P19",
        "title": "Zero-to-Playable Game Creation Wizard",
        "status": "done",
        "summary": "计划、脚手架、审计、review、Portal、MCP、live snapshot 监控、tower_defense/arpg/roguelike/visual_novel/survival_crafting 模板扩展、模板迁移策略、runtime playability smoke、输入回放/golden screenshot 计划资产、headless/viewport replay 脚本执行、baseline promote 流程、首批 tower_defense viewport golden baseline、viewport baseline readiness 监控字段、live sandbox execute-replay lane、full live validation lane evidence 和写入前治理强校验已落地。",
        "remaining_work": [],
        "next_action": "",
        "evidence": [
            "agent_system/tools/game_creation_wizard.py",
            "tests/test_live_sandbox.py::test_8_p19_scene_graph_snapshot_reaches_health_monitor",
            "tests/test_live_sandbox.py::test_9_p19_runtime_playability_smoke_generated_tower_defense",
            "tests/test_live_sandbox.py::test_10_p19_execute_replay_generates_runtime_screenshot",
        ],
    },
]


def build_roadmap_status(project_root: str | Path | None = None) -> Dict[str, Any]:
    root = Path(project_root or ".").resolve()
    doc_path = root / DEFAULT_ROADMAP_DOC_PATH
    items = [dict(item) for item in ROADMAP_ITEMS]
    partial_items = [item for item in items if item.get("status") == "partial"]
    pending_items = [item for item in items if item.get("status") == "pending"]
    next_actions = [
        item.get("next_action", "")
        for item in [*partial_items, *pending_items]
        if item.get("next_action")
    ][:5]
    return normalize_roadmap_status({
        "source_doc": DEFAULT_ROADMAP_DOC_PATH,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "items": items,
        "next_recommended_actions": next_actions,
        "message": (
            f"Roadmap status built from {DEFAULT_ROADMAP_DOC_PATH}; "
            f"source_exists={doc_path.exists()}"
        ),
    })

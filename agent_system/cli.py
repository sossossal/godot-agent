"""
Godot Agent 正式化命令行入口 (V1.3.5)
支持多级子命令、环境自检、任务编排和历史查询
"""

import sys
import argparse
import json
from pathlib import Path
from urllib import request as urllib_request
from urllib import error as urllib_error

from . import configure_utf8_stdio
from .router import GodotAgentRouter
from .models import TaskStatus
from .tools.doctor import SystemDoctor, default_doctor_report_path
from .tools.agent_compatibility import build_agent_compatibility_matrix, list_agent_provider_profiles
from .tools.game_creation_wizard import (
    apply_game_creation_plan,
    build_game_creation_input_replay,
    build_game_creation_template_migration,
    build_game_creation_review,
    build_game_creation_plan,
    build_scene_graph_audit,
    list_game_creation_templates,
)
from .tools.governance import build_governance_enforcement, build_governance_policy
from .tools.production_scale import build_production_readiness, list_production_scenarios
from .tools.roadmap_status import build_roadmap_status


def setup_io():
    """解决 Windows 编码问题"""
    configure_utf8_stdio()


def cmd_run(args, router: GodotAgentRouter):
    """运行指令"""
    print(f"🔍 正在规划任务: {args.prompt}...")
    task = router.plan(args.prompt)
    
    if task.status == TaskStatus.FAILED:
        print(f"❌ 规划失败: {task.logs[-1]}")
        return

    # 如果需要确认
    if not args.yes:
        print(f"\n--- 任务计划预览 ---")
        for i, step in enumerate(task.steps, 1):
            print(f"  {i}. [{step.role}] {step.name}: {step.description}")
        
        confirm = input("\n是否执行? (y/n): ").lower()
        if confirm != 'y':
            print("任务取消")
            return

    # 执行
    task = router.execute_plan(task)
    
    if task.status == TaskStatus.SUCCESS:
        print(f"\n✅ 任务执行成功!")
    elif task.status == TaskStatus.ROLLED_BACK:
        print(f"\n⚠️ 任务失败且已回滚: {task.get_message()}")
    else:
        print(f"\n❌ 任务执行失败: {task.get_message()}")

    if task.artifacts:
        print("\n--- 产物 ---")
        for art in task.artifacts:
            print(f"  {art.path}")


def cmd_doctor(args):
    """自检环境"""
    doctor = SystemDoctor(config_path=args.config)
    passed = doctor.check_all(
        report_path=args.report_path or default_doctor_report_path(),
        json_output=args.json,
    )
    return 0 if passed else 1


def cmd_roles(args, router: GodotAgentRouter):
    """列出可用角色"""
    roles = router.get_available_roles()
    print(f"当前启用的角色 ({len(roles)}):")
    for r_name in roles:
        info = router.roles.get(r_name)
        print(f"\n🔹 {r_name.upper()}")
        print(f"   描述: {info.get_description()}")
        print(f"   能力: {', '.join(info.get_capabilities())}")


def cmd_history(args, router: GodotAgentRouter):
    """显示历史记录"""
    history = router.get_history(limit=args.limit)
    print(f"最近 {len(history)} 条任务记录:")
    for h in history:
        print(f"[{h['status']}] {h['task_id'][:8]}... | {h['prompt']}")


def cmd_chat(args, router: GodotAgentRouter):
    """交互式聊天模式"""
    print("💬 进入 Godot Agent 聊天模式 (输入 'exit' 退出, 'clear' 清空上下文)")
    context = {}
    
    while True:
        try:
            prompt = input("\n👤 > ").strip()
            if not prompt: continue
            if prompt.lower() in ['exit', 'quit', '退出']: break
            if prompt.lower() == 'clear':
                context = {}
                print("✨ 上下文已清空")
                continue
                
            task = router.execute(prompt, context=context, confirm=True)
            
            if task.status == TaskStatus.SUCCESS:
                print(f"✅ 执行成功: {task.get_message()}")
                # 累积上下文, 使得后续指令能感知前面的产物
                context.update(task.context)
            elif task.status == TaskStatus.ROLLED_BACK:
                print(f"⚠️ 失败并已回滚: {task.get_message()}")
            else:
                print(f"❌ 失败: {task.get_message()}")
                
        except KeyboardInterrupt:
            break
    print("\n👋 已退出聊天模式")


def cmd_launch(args, router: GodotAgentRouter):
    """启动 Godot 编辑器"""
    result = router.godot_cli.launch_editor(scene_path=args.scene)
    if result.success:
        pid = (result.data or {}).get("pid")
        source = (result.data or {}).get("executable_source")
        source_label = (result.data or {}).get("executable_source_label")
        suffix = f" (PID: {pid})" if pid else ""
        source_text = ""
        if source == "config":
            source_text = f" | 来源: config `{source_label}`"
        elif source == "env":
            source_text = f" | 来源: 环境变量 `{source_label}`"
        elif source == "path":
            source_text = f" | 来源: PATH `{source_label}`"
        print(f"✅ {result.message}{suffix}{source_text}")
        return
    print(f"❌ 启动失败: {result.error or result.message}")


def cmd_wait_editor_event(args):
    """等待 API Server 返回最新编辑器回执"""
    payload = {
        "project_path": args.project or "default",
        "timeout": args.timeout,
    }
    if args.after_id is not None:
        payload["after_event_id"] = args.after_id
    if args.kind:
        payload["kind"] = args.kind

    api_url = args.api_url.rstrip("/")
    req = urllib_request.Request(
        f"{api_url}/editor/wait-event",
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        with urllib_request.urlopen(req, timeout=max(args.timeout + 2, 3)) as resp:
            result = json.loads(resp.read().decode("utf-8"))
    except urllib_error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        print(f"❌ 等待编辑器回执失败: {detail or exc.reason}")
        return
    except Exception as exc:
        print(f"❌ 请求 API Server 失败: {exc}")
        return

    event = result.get("event") or {}
    print(json.dumps(event, indent=2, ensure_ascii=False))


def _parse_csv_values(values):
    items = []
    for value in values or []:
        for part in str(value or "").replace(";", ",").split(","):
            text = part.strip()
            if text:
                items.append(text)
    return items


def cmd_governance(args):
    """执行 P4 治理准入门禁"""
    if args.policy:
        payload = build_governance_policy()
        print(json.dumps(payload, indent=2, ensure_ascii=False))
        return 0

    evidence = {name: True for name in _parse_csv_values(args.evidence)}
    changed_paths = _parse_csv_values(args.changed_path)
    project_root = Path(args.project_root or args.project or ".").resolve()
    payload = build_governance_enforcement(
        project_root,
        runtime_root=Path(".").resolve(),
        change_type=args.change_type,
        evidence=evidence,
        changed_paths=changed_paths,
        notes=args.notes or "",
        mode=args.mode,
        fail_on_warnings=args.fail_on_warnings,
    )

    if args.json:
        print(json.dumps(payload, indent=2, ensure_ascii=False))
    else:
        admission = payload["admission"]
        print(f"治理准入: {payload['message']}")
        print(f"变更类型: {admission['change_type']} | 状态: {admission['status']} | exit_code: {payload['exit_code']}")
        if admission.get("missing_evidence"):
            print(f"缺失 evidence: {', '.join(admission['missing_evidence'])}")
        if payload.get("blocking_checks"):
            print(f"阻断检查: {', '.join(payload['blocking_checks'])}")
        for recommendation in admission.get("recommendations", [])[:5]:
            print(f"- {recommendation}")

    return int(payload["exit_code"])


def cmd_production(args):
    """执行 P5 生产规模验证"""
    if args.scenarios:
        payload = list_production_scenarios()
        print(json.dumps(payload, indent=2, ensure_ascii=False))
        return 0

    evidence = {name: True for name in _parse_csv_values(args.evidence)}
    changed_paths = _parse_csv_values(args.changed_path)
    project_root = Path(args.project_root or args.project or ".").resolve()
    payload = build_production_readiness(
        project_root,
        runtime_root=Path(".").resolve(),
        scenario_id=args.scenario_id,
        evidence=evidence,
        changed_paths=changed_paths,
        notes=args.notes or "",
        mode=args.mode,
        fail_on_warnings=args.fail_on_warnings,
    )

    if args.json:
        print(json.dumps(payload, indent=2, ensure_ascii=False))
    else:
        print(f"生产验证: {payload['message']}")
        print(f"场景: {payload['scenario_id']} | 状态: {payload['readiness_status']} | exit_code: {payload['exit_code']}")
        if payload.get("blocking_checks"):
            print(f"阻断检查: {', '.join(payload['blocking_checks'])}")
        for recommendation in payload.get("recommendations", [])[:5]:
            print(f"- {recommendation}")

    return int(payload["exit_code"])


def cmd_agent_compat(args):
    """执行 P6 Agent/API 兼容性矩阵"""
    if args.providers:
        payload = list_agent_provider_profiles()
        print(json.dumps(payload, indent=2, ensure_ascii=False))
        return 0

    provider_ids = _parse_csv_values(args.provider)
    project_root = Path(args.project_root or args.project or ".").resolve()
    payload = build_agent_compatibility_matrix(
        project_root,
        runtime_root=Path(".").resolve(),
        providers=provider_ids or None,
    )

    if args.json:
        print(json.dumps(payload, indent=2, ensure_ascii=False))
    else:
        print(f"Agent 兼容性: {payload['status']} | providers: {payload['provider_count']} | surfaces: {payload['surface_count']}")
        if payload.get("blocked_providers"):
            print(f"阻断 provider: {', '.join(payload['blocked_providers'])}")
        if payload.get("blocked_surfaces"):
            print(f"阻断 surface: {', '.join(payload['blocked_surfaces'])}")
        for recommendation in payload.get("recommendations", [])[:5]:
            print(f"- {recommendation}")

    return 0 if payload.get("passed") else 1


def cmd_roadmap(args):
    """输出路线图状态盘点。"""
    project_root = Path(args.project_root or args.project or ".").resolve()
    payload = build_roadmap_status(project_root)
    if args.json:
        print(json.dumps(payload, indent=2, ensure_ascii=False))
    else:
        print(
            "路线图状态: "
            f"{payload['done_count']}/{payload['total_count']} done | "
            f"partial={payload['partial_count']} | pending={payload['pending_count']} | "
            f"remaining={payload['remaining_count']}"
        )
        for item in payload.get("remaining_items", [])[:10]:
            print(f"- [{item['status']}] {item['item_id']}: {item['title']} -> {item.get('next_action') or item.get('summary')}")
    return 0


def cmd_game_create(args):
    """执行 P19 游戏创建向导"""
    if args.templates:
        payload = list_game_creation_templates()
        print(json.dumps(payload, indent=2, ensure_ascii=False))
        return 0

    project_root = Path(args.project_root or args.project or ".").resolve()
    if args.audit:
        payload = build_scene_graph_audit(
            project_root,
            manifest_path=args.manifest_path,
            write_report=args.write_report,
        )
        print(json.dumps(payload, indent=2, ensure_ascii=False))
        return 1 if payload.get("should_block") else 0
    if args.review:
        payload = build_game_creation_review(
            project_root,
            manifest_path=args.manifest_path,
            write_reports=args.write_report,
        )
        print(json.dumps(payload, indent=2, ensure_ascii=False))
        return 1 if payload.get("should_block") else 0
    if args.replay:
        payload = build_game_creation_input_replay(
            project_root,
            manifest_path=args.manifest_path,
            input_replay_path=args.input_replay_path,
            write_report=args.write_report,
            write_script=not args.no_replay_script,
            execute_replay=args.execute_replay,
            promote_baseline=args.promote_baseline,
            replay_render_mode=getattr(args, "replay_render_mode", "headless"),
        )
        print(json.dumps(payload, indent=2, ensure_ascii=False))
        return 1 if payload.get("should_block") else 0
    if getattr(args, "template_migration", False):
        payload = build_game_creation_template_migration(
            project_root,
            manifest_path=args.manifest_path,
            from_template_id=getattr(args, "from_template_id", ""),
            to_template_id=getattr(args, "to_template_id", "") or args.template_id,
            write_report=args.write_report,
            report_path=getattr(args, "migration_report_path", "data_tables/game_creation/template_migration_plan.json"),
        )
        print(json.dumps(payload, indent=2, ensure_ascii=False))
        return 1 if payload.get("should_block") else 0

    features = _parse_csv_values(args.feature)
    target_platforms = _parse_csv_values(args.target_platform)
    common_args = {
        "title": args.title,
        "genre": args.genre,
        "template_id": args.template_id,
        "features": features or None,
        "target_platforms": target_platforms or None,
        "notes": args.notes or "",
    }
    if args.apply:
        payload = apply_game_creation_plan(project_root, overwrite=args.overwrite, **common_args)
    else:
        payload = build_game_creation_plan(project_root, **common_args)

    if args.json:
        print(json.dumps(payload, indent=2, ensure_ascii=False))
    else:
        mode = "写入" if args.apply else "计划"
        print(f"游戏创建{mode}: {payload['status']} | title: {payload['title']} | template: {payload['template_id']}")
        print(f"manifest: {payload.get('manifest_path') or '-'}")
        if payload.get("blocking_checks"):
            print(f"阻断检查: {', '.join(payload['blocking_checks'])}")
        if payload.get("warning_checks"):
            print(f"警告: {', '.join(payload['warning_checks'])}")
        if args.apply:
            print(f"生成文件: {len(payload.get('generated_files') or [])} | 跳过文件: {len(payload.get('skipped_files') or [])}")
        else:
            for path in (payload.get("artifact_paths") or [])[:10]:
                print(f"- {path}")

    return 1 if payload.get("should_block") else 0


def main():
    setup_io()
    parser = argparse.ArgumentParser(description="Godot 多角色 Agent 系统")
    parser.add_argument("-c", "--config", default="config.yaml", help="配置文件路径")
    parser.add_argument("-p", "--project", help="Godot 项目路径")
    
    subparsers = parser.add_subparsers(dest="command", help="子命令")

    # run 命令
    run_parser = subparsers.add_parser("run", help="执行自然语言指令")
    run_parser.add_argument("prompt", help="自然语言指令内容")
    run_parser.add_argument("-y", "--yes", action="store_true", help="跳过确认直接执行")

    # chat 命令
    subparsers.add_parser("chat", help="进入交互式聊天模式")

    # plan 命令
    plan_parser = subparsers.add_parser("plan", help="仅规划任务不执行")
    plan_parser.add_argument("prompt", help="自然语言指令内容")

    # doctor 命令
    doctor_parser = subparsers.add_parser("doctor", help="诊断系统环境和依赖")
    doctor_parser.add_argument("--json", action="store_true", help="输出完整 JSON 结果")
    doctor_parser.add_argument(
        "--report-path",
        default="",
        help=f"自检报告输出路径，默认写入 {default_doctor_report_path()}",
    )

    # roles 命令
    subparsers.add_parser("roles", help="列出所有可用角色和能力")

    # history 命令
    hist_parser = subparsers.add_parser("history", help="查询历史任务记录")
    hist_parser.add_argument("-l", "--limit", type=int, default=10, help="显示条数")

    # launch 命令
    launch_parser = subparsers.add_parser("launch", help="启动 Godot 编辑器")
    launch_parser.add_argument("--scene", help="启动后尝试打开的场景路径，例如 res://scenes/Main.tscn")

    wait_event_parser = subparsers.add_parser("wait-event", help="通过 API Server 等待最新编辑器回执")
    wait_event_parser.add_argument("--kind", choices=["execute_script", "open_resource"], help="只等待特定类型的回执")
    wait_event_parser.add_argument("--after-id", type=int, help="只接收 event_id 大于该值的新回执")
    wait_event_parser.add_argument("--timeout", type=int, default=10, help="等待秒数")
    wait_event_parser.add_argument("--api-url", default="http://127.0.0.1:8000", help="API Server 地址")

    governance_parser = subparsers.add_parser("governance", help="执行 P4 治理准入检查")
    governance_parser.add_argument("--policy", action="store_true", help="只输出治理策略，不执行准入")
    governance_parser.add_argument("--change-type", default="feature", help="变更类型，例如 feature / skill / template / mcp_bridge")
    governance_parser.add_argument("--evidence", action="append", default=[], help="逗号分隔 evidence，例如 contract,tests,docs")
    governance_parser.add_argument("--changed-path", action="append", default=[], help="逗号分隔 changed paths，可重复传入")
    governance_parser.add_argument("--notes", default="", help="准入说明")
    governance_parser.add_argument("--mode", choices=["strict", "advisory"], default="strict", help="strict 会按阻断项返回非零退出码")
    governance_parser.add_argument("--fail-on-warnings", action="store_true", help="strict 模式下 warning 也视为阻断")
    governance_parser.add_argument("--project-root", help="用于治理检查的项目根目录；默认使用 --project 或当前目录")
    governance_parser.add_argument("--json", action="store_true", help="输出完整 JSON 结果")

    production_parser = subparsers.add_parser("production", help="执行 P5 生产规模验证")
    production_parser.add_argument("--scenarios", action="store_true", help="只输出生产验证场景目录")
    production_parser.add_argument("--scenario-id", default="vertical_slice_2d", help="生产验证场景，例如 vertical_slice_2d / content_pipeline / release_candidate")
    production_parser.add_argument("--evidence", action="append", default=[], help="逗号分隔 evidence，例如 contract,tests,docs,quality_dashboard")
    production_parser.add_argument("--changed-path", action="append", default=[], help="逗号分隔 changed paths，可重复传入")
    production_parser.add_argument("--notes", default="", help="验证说明")
    production_parser.add_argument("--mode", choices=["strict", "advisory"], default="strict", help="strict 会按阻断项返回非零退出码")
    production_parser.add_argument("--fail-on-warnings", action="store_true", help="strict 模式下 warning 也视为阻断")
    production_parser.add_argument("--project-root", help="用于生产验证的项目根目录；默认使用 --project 或当前目录")
    production_parser.add_argument("--json", action="store_true", help="输出完整 JSON 结果")

    compat_parser = subparsers.add_parser("agent-compat", help="执行 P6 Agent/API 兼容矩阵")
    compat_parser.add_argument("--providers", action="store_true", help="只输出 provider profile 目录")
    compat_parser.add_argument("--provider", action="append", default=[], help="逗号分隔 provider，例如 codex,openai_api")
    compat_parser.add_argument("--project-root", help="用于兼容检查的项目根目录；默认使用 --project 或当前目录")
    compat_parser.add_argument("--json", action="store_true", help="输出完整 JSON 结果")

    roadmap_parser = subparsers.add_parser("roadmap", help="输出路线图完成状态")
    roadmap_parser.add_argument("--project-root", help="用于读取路线图文档的项目根目录；默认使用 --project 或当前目录")
    roadmap_parser.add_argument("--json", action="store_true", help="输出完整 JSON 结果")

    game_create_parser = subparsers.add_parser("game-create", help="执行 P19 游戏创建向导")
    game_create_parser.add_argument("--templates", action="store_true", help="只输出可用游戏创建模板")
    game_create_parser.add_argument("--apply", action="store_true", help="按计划写入 Godot 项目脚手架；默认只预览计划")
    game_create_parser.add_argument("--overwrite", action="store_true", help="写入时覆盖已有脚手架文件")
    game_create_parser.add_argument("--title", default="Platformer Prototype", help="游戏标题")
    game_create_parser.add_argument("--genre", default="platformer_2d", help="游戏类型")
    game_create_parser.add_argument("--template-id", default="platformer_2d", help="模板 ID")
    game_create_parser.add_argument("--feature", action="append", default=[], help="逗号分隔功能，例如 player_movement,jump,coin_collection")
    game_create_parser.add_argument("--target-platform", action="append", default=[], help="逗号分隔目标平台，例如 desktop,web")
    game_create_parser.add_argument("--notes", default="", help="计划备注")
    game_create_parser.add_argument("--audit", action="store_true", help="审计 game_creation_profile 对应的场景树、节点、脚本与信号")
    game_create_parser.add_argument("--review", action="store_true", help="生成 game_creation_review 验收摘要，汇总场景审计、模块状态和验收清单")
    game_create_parser.add_argument("--replay", action="store_true", help="根据 input_replay.json 生成可执行回放脚本和 replay 报告")
    game_create_parser.add_argument("--template-migration", action="store_true", help="规划 P19 模板迁移策略，不直接改写项目文件")
    game_create_parser.add_argument("--from-template-id", default="", help="模板迁移源模板；为空时从 manifest 读取")
    game_create_parser.add_argument("--to-template-id", default="", help="模板迁移目标模板；为空时使用 --template-id")
    game_create_parser.add_argument("--migration-report-path", default="data_tables/game_creation/template_migration_plan.json", help="模板迁移策略报告路径")
    game_create_parser.add_argument("--manifest-path", default="data_tables/game_creation/game_creation_profile.json", help="审计使用的 game_creation_profile manifest")
    game_create_parser.add_argument("--input-replay-path", default="data_tables/game_creation/input_replay.json", help="输入回放计划路径")
    game_create_parser.add_argument("--no-replay-script", action="store_true", help="只校验 input_replay.json，不写入 headless replay 脚本")
    game_create_parser.add_argument("--execute-replay", action="store_true", help="生成 replay 脚本后调用 Godot headless 实际执行")
    game_create_parser.add_argument("--replay-render-mode", choices=["headless", "viewport"], default="headless", help="执行 replay 时使用 headless 或可渲染 viewport runner")
    game_create_parser.add_argument("--promote-baseline", action="store_true", help="将 replay runtime screenshot 登记为 golden screenshot baseline")
    game_create_parser.add_argument("--write-report", action="store_true", help="审计或评审时写入 data_tables/game_creation/*.json 报告")
    game_create_parser.add_argument("--project-root", help="用于写入脚手架的项目根目录；默认使用 --project 或当前目录")
    game_create_parser.add_argument("--json", action="store_true", help="输出完整 JSON 结果")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return

    # 初始化路由器 (针对非 doctor 命令)
    router = None
    if args.command not in {"doctor", "wait-event", "governance", "production", "agent-compat", "roadmap", "game-create"}:
        try:
            router = GodotAgentRouter(config_path=args.config, godot_project_path=args.project)
        except Exception as e:
            print(f"❌ 初始化失败: {e}")
            return

    # 路由子命令
    if args.command == "run":
        cmd_run(args, router)
    elif args.command == "doctor":
        code = cmd_doctor(args)
        if code:
            raise SystemExit(code)
    elif args.command == "chat":
        cmd_chat(args, router)
    elif args.command == "roles":
        cmd_roles(args, router)
    elif args.command == "history":
        cmd_history(args, router)
    elif args.command == "launch":
        cmd_launch(args, router)
    elif args.command == "wait-event":
        cmd_wait_editor_event(args)
    elif args.command == "governance":
        code = cmd_governance(args)
        if code:
            raise SystemExit(code)
    elif args.command == "production":
        code = cmd_production(args)
        if code:
            raise SystemExit(code)
    elif args.command == "agent-compat":
        code = cmd_agent_compat(args)
        if code:
            raise SystemExit(code)
    elif args.command == "roadmap":
        code = cmd_roadmap(args)
        if code:
            raise SystemExit(code)
    elif args.command == "game-create":
        code = cmd_game_create(args)
        if code:
            raise SystemExit(code)
    elif args.command == "plan":
        task = router.plan(args.prompt)
        print(json.dumps([{"step": s.name, "role": s.role, "desc": s.description} for s in task.steps], indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()

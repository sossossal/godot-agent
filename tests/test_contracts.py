import unittest

from agent_system.contracts import (
    BALANCE_ANALYSIS_SCHEMA_VERSION,
    FEATURE_CONTEXT_SCHEMA_VERSION,
    LIVEOPS_PROFILE_SCHEMA_VERSION,
    ASSET_REVIEW_WORKFLOW_SCHEMA_VERSION,
    OUTSOURCE_DELIVERY_GATE_SCHEMA_VERSION,
    PERFORMANCE_SUMMARY_SCHEMA_VERSION,
    PLATFORM_DELIVERY_PROFILE_SCHEMA_VERSION,
    QUALITY_GATE_SCHEMA_VERSION,
    RELEASE_QA_EVIDENCE_SCHEMA_VERSION,
    RELEASE_CANDIDATE_CHECKLIST_SCHEMA_VERSION,
    RELEASE_CAPABILITY_REGISTRY_SCHEMA_VERSION,
    RELEASE_CAPABILITY_POLICY_SCHEMA_VERSION,
    RELEASE_RUNTIME_ASSEMBLY_SCHEMA_VERSION,
    RELEASE_DELIVERY_READINESS_SCHEMA_VERSION,
    RELEASE_LIVE_EVENT_STREAM_SCHEMA_VERSION,
    RELEASE_LIVE_DISPATCH_PREFLIGHT_SCHEMA_VERSION,
    RELEASE_LIVE_DISPATCH_AUDIT_SCHEMA_VERSION,
    RELEASE_ARTIFACT_MANIFEST_SCHEMA_VERSION,
    RELEASE_EXECUTION_STATUS_SCHEMA_VERSION,
    RELEASE_PROMOTION_HISTORY_SCHEMA_VERSION,
    RELEASE_PROMOTION_PLAN_SCHEMA_VERSION,
    RELEASE_REVIEW_BUNDLE_SCHEMA_VERSION,
    RELEASE_SUMMARY_SCHEMA_VERSION,
    SCENE_OWNERSHIP_BOARD_SCHEMA_VERSION,
    TELEMETRY_SUMMARY_SCHEMA_VERSION,
    normalize_balance_analysis,
    normalize_liveops_profile,
    normalize_asset_review_workflow,
    normalize_build_run_matrix,
    normalize_release_capability_registry,
    normalize_release_capability_policy,
    normalize_release_runtime_assembly_snapshot,
    normalize_release_delivery_readiness,
    normalize_release_live_event_stream,
    normalize_release_live_dispatch_preflight,
    normalize_release_live_dispatch_audit,
    normalize_release_artifact_manifest,
    normalize_outsource_delivery_gate,
    normalize_performance_summary,
    normalize_platform_delivery_profile,
    normalize_release_qa_evidence,
    normalize_release_candidate_checklist,
    normalize_release_execution_status,
    normalize_release_promotion_history,
    normalize_release_promotion_plan,
    normalize_release_review_bundle,
    normalize_release_summary,
    normalize_scene_ownership_board,
    normalize_telemetry_summary,
)
from agent_system.models import Artifact, Task, TaskStatus, TaskStep


class ContractsTestCase(unittest.TestCase):
    def test_task_to_dict_normalizes_feature_context_and_review_history(self):
        task = Task(
            prompt="创建一个玩家控制功能",
            status=TaskStatus.SUCCESS,
            context={
                "priority": "urgent",
                "risk": "severe",
                "dependency": "art_pack",
                "eta": "2026-05-01",
                "validation_method": "portal smoke",
                "blockers": ["missing screenshot"],
                "feature_review_note": "需要补图",
                "feature_review_history": [
                    {"feature_status": "done", "review_note": "旧记录", "reviewer": "qa", "round": "r1", "followups": ["补截图"]},
                ],
                "feature_lifecycle_events": [
                    {"event_type": "retry", "summary": "旧重试"},
                ],
                "external_links": [
                    {"label": "PR 12", "url": "https://example.test/pr/12", "type": "pull_request", "status": "passed"},
                ],
            },
        )
        task.steps = [
            TaskStep(name="Logic", description="生成控制逻辑", role="code_generator", status=TaskStatus.SUCCESS),
        ]
        task.artifacts = [
            Artifact(name="player.gd", path="res://scripts/player.gd", type="script"),
        ]

        payload = task.to_dict()
        context = payload["context"]

        self.assertEqual(context["priority"], "medium")
        self.assertEqual(context["risk"], "medium")
        self.assertEqual(context["dependency"], "art_pack")
        self.assertEqual(context["eta"], "2026-05-01")
        self.assertEqual(context["validation_method"], "portal smoke")
        self.assertEqual(context["blockers"], ["missing screenshot"])
        self.assertEqual(context["feature_status"], "pending_acceptance")
        self.assertEqual(context["contract_versions"]["feature_context"], FEATURE_CONTEXT_SCHEMA_VERSION)
        self.assertEqual(context["feature_review_history"][-1]["feature_status"], "pending_review")
        self.assertEqual(context["feature_review_history"][-1]["reviewer"], "qa")
        self.assertEqual(context["feature_review_history"][-1]["review_round"], "r1")
        self.assertEqual(context["feature_review_history"][-1]["required_followups"], ["补截图"])
        self.assertEqual(context["feature_lifecycle_events"][-1]["event_type"], "retry")
        self.assertEqual(context["external_links"][0]["link_id"], "external_link_1")
        self.assertEqual(context["external_links"][0]["type"], "pull_request")
        self.assertEqual(context["acceptance_checklist"][0]["status"], "ready")
        self.assertEqual(context["acceptance_checklist"][0]["validation_method"], "portal smoke")
        self.assertEqual(context["acceptance_checklist"][0]["blockers"], ["missing screenshot"])
        self.assertEqual(context["artifact_links"][0]["artifact_id"], "player.gd")
        self.assertEqual(context["artifact_links"][0]["path"], "res://scripts/player.gd")
        self.assertEqual(context["artifact_links"][0]["kind"], "script")
        self.assertTrue(any("新增产物: script x1" in line for line in context["change_summary"]))

    def test_release_summary_normalizes_nested_contracts(self):
        summary = normalize_release_summary({
            "build_id": "web-preview-1",
            "version": "0.1.0-preview+1",
            "channel": "preview",
            "feature": {
                "feature_id": "feature-001",
                "priority": "urgent",
                "risk": "severe",
                "dependency": "qa",
                "eta": "2026-05-03",
                "validation_method": "release smoke",
                "blockers": ["qa pending"],
                "reviewer": "producer",
                "review_round": "final",
                "required_followups": ["确认最终截图"],
                "artifact_links": [{"artifact_id": "release_manifest", "path": "api_server/static/dist/release_manifest.json", "kind": "manifest", "status": "passed"}],
                "feature_review_history": [{"feature_status": "returned", "review_note": "补截图", "reviewer": "lead", "review_round": "r2", "required_followups": ["复审截图"]}],
                "feature_lifecycle_events": [{"event_type": "retry", "summary": "补测后重跑"}],
                "external_links": [{"label": "CI run", "href": "https://example.test/ci/1", "kind": "ci", "status": "ok"}],
                "feature_status": "done",
            },
            "quality_gate": {
                "passed": True,
                "checks": [
                    {"name": "smoke_test", "status": "ok", "message": "done"},
                ],
                "metrics": {"scene_load_ms": 320},
            },
            "acceptance_checklist": [{"label": "冒烟通过", "status": "ready", "validation_method": "release smoke", "blockers": ["qa pending"]}],
            "known_risks": [],
            "files": [{"path": "index.html", "size": 12, "sha256": "abc"}],
        })

        self.assertEqual(summary["schema_version"], RELEASE_SUMMARY_SCHEMA_VERSION)
        self.assertEqual(summary["feature"]["schema_version"], FEATURE_CONTEXT_SCHEMA_VERSION)
        self.assertEqual(summary["feature"]["priority"], "medium")
        self.assertEqual(summary["feature"]["risk"], "medium")
        self.assertEqual(summary["feature"]["dependency"], "qa")
        self.assertEqual(summary["feature"]["eta"], "2026-05-03")
        self.assertEqual(summary["feature"]["validation_method"], "release smoke")
        self.assertEqual(summary["feature"]["blockers"], ["qa pending"])
        self.assertEqual(summary["feature"]["reviewer"], "producer")
        self.assertEqual(summary["feature"]["review_round"], "final")
        self.assertEqual(summary["feature"]["required_followups"], ["确认最终截图"])
        self.assertEqual(summary["feature"]["artifact_links"][0]["artifact_id"], "release_manifest")
        self.assertEqual(summary["feature"]["feature_review_history"][0]["review_note"], "补截图")
        self.assertEqual(summary["feature"]["feature_review_history"][0]["reviewer"], "lead")
        self.assertEqual(summary["feature"]["feature_review_history"][0]["required_followups"], ["复审截图"])
        self.assertEqual(summary["feature"]["feature_lifecycle_events"][0]["event_type"], "retry")
        self.assertEqual(summary["feature"]["external_links"][0]["status"], "skipped")
        self.assertEqual(summary["feature"]["external_links"][0]["url"], "https://example.test/ci/1")
        self.assertEqual(summary["feature"]["feature_status"], "pending_review")
        self.assertEqual(summary["quality_gate"]["schema_version"], QUALITY_GATE_SCHEMA_VERSION)
        self.assertEqual(summary["quality_gate"]["checks"][0]["status"], "skipped")
        self.assertEqual(summary["qa_evidence"]["schema_version"], RELEASE_QA_EVIDENCE_SCHEMA_VERSION)
        self.assertEqual(summary["qa_evidence"]["smoke_status"], "skipped")
        self.assertEqual(summary["known_risks"], ["未登记已知风险"])
        self.assertEqual(summary["known_issues"], ["未登记已知风险"])
        self.assertEqual(summary["acceptance_checklist"][0]["validation_method"], "release smoke")
        self.assertEqual(summary["acceptance_checklist"][0]["blockers"], ["qa pending"])

    def test_release_qa_evidence_normalizes_gate_metrics_and_assertions(self):
        evidence = normalize_release_qa_evidence(
            {
                "assertion_status": "passed",
                "asserted_nodes": ["Player", "HUD"],
                "screenshot_status": "warning",
                "screenshot_path": "logs/test_artifacts/release_gate.png",
                "screenshot_diff_ratio": 0.0849,
                "max_screenshot_diff_ratio": 0.05,
            },
            {
                "passed": True,
                "checks": [
                    {"name": "smoke_test", "status": "passed", "message": "scene ok", "scene_path": "res://scenes/demo.tscn"},
                ],
                "metrics": {"scene_load_ms": 320, "fps": 58.4, "memory_peak_mb": 144.2},
            },
        )

        self.assertEqual(evidence["schema_version"], RELEASE_QA_EVIDENCE_SCHEMA_VERSION)
        self.assertEqual(evidence["status"], "warning")
        self.assertEqual(evidence["smoke_status"], "passed")
        self.assertEqual(evidence["assertion_node_count"], 2)
        self.assertEqual(evidence["checks"][1]["check_id"], "qa_assertions")
        self.assertEqual(evidence["metrics"]["scene_load_ms"], 320)
        self.assertEqual(evidence["warning_checks"], ["visual_regression"])

    def test_balance_analysis_normalizes_statuses_and_counts(self):
        analysis = normalize_balance_analysis({
            "passed": True,
            "score": "88.6",
            "table_types": ["Enemy", "loot", "unknown"],
            "issues": ["问题 A"],
            "warnings": ["警告 A"],
            "checks": [
                {"name": "combat_stat_spread", "status": "ok", "message": "done"},
            ],
            "metrics": {"avg_enemy_hp": 32},
        })

        self.assertEqual(analysis["schema_version"], BALANCE_ANALYSIS_SCHEMA_VERSION)
        self.assertEqual(analysis["score"], 88.6)
        self.assertEqual(analysis["table_types"], ["enemy", "loot"])
        self.assertEqual(analysis["issue_count"], 1)
        self.assertEqual(analysis["warning_count"], 1)
        self.assertEqual(analysis["checks"][0]["status"], "skipped")

    def test_telemetry_summary_normalizes_catalog_and_counts(self):
        summary = normalize_telemetry_summary({
            "passed": True,
            "catalog_entries": [
                {
                    "event_name": "session_start",
                    "category": "session",
                    "privacy_level": "invalid",
                    "fields": [{"name": "build_id", "type": "", "required": True, "pii": False}],
                }
            ],
            "sessions": [{"session_id": "s1", "event_count": "2"}],
            "event_count": "2",
            "pii_violation_count": "1",
            "privacy_gate_passed": False,
            "retention_user_count": "3",
            "retention_cohorts": [{"window": "D1", "day_offset": "1", "eligible_users": "2", "retained_users": "1", "retention_rate": "0.5"}],
            "funnel_breakdown": [{"step_index": "1", "event_name": "session_start", "session_count": "2", "conversion_rate": "1"}],
            "crash_taxonomy": [{"crash_type": "", "count": "1", "session_count": "1"}],
            "crash_clusters": [{"cluster_id": "", "signature": "", "crash_type": "native", "count": "1", "session_count": "1", "builds": ["qa", "qa"]}],
            "crash_regression_dashboard": {
                "affected_build_count": "2",
                "affected_scene_count": "1",
                "top_cluster_id": "native_cluster",
                "top_cluster_count": "3",
                "build_regressions": [{"build_id": "", "crash_count": "2", "cluster_count": "1", "latest_seen_at": "2026-04-10T10:00:00Z"}],
                "scene_regressions": [{"scene_path": "", "crash_count": "2", "cluster_count": "1", "affected_build_count": "2"}],
                "recommendations": ["check build"],
            },
            "retention_funnel_dashboard": {
                "completion_rate": "0.5",
                "lowest_retention_window": "D7",
                "lowest_retention_rate": "0.25",
                "largest_dropoff_step": "level_complete",
                "largest_dropoff_count": "1",
                "largest_dropoff_rate": "0.5",
                "retention_windows": [{"window": "D7", "day_offset": "7", "eligible_users": "4", "retained_users": "1", "retention_rate": "0.25"}],
                "funnel_dropoffs": [{"step_index": "2", "event_name": "level_complete", "previous_event_name": "level_start", "previous_session_count": "2", "session_count": "1", "dropoff_count": "1", "dropoff_rate": "0.5"}],
                "recommendations": ["check funnel"],
            },
            "retention_funnel_trend_dashboard": {
                "day_count": "2",
                "top_build_id": "web-preview-1",
                "top_channel": "qa",
                "highest_crash_day": "2026-04-10",
                "day_rows": [{"date": "2026-04-10", "session_count": "2", "event_count": "6", "active_user_count": "1", "new_user_count": "1", "returning_user_count": "0", "completed_session_count": "1", "completion_rate": "0.5", "crash_count": "1"}],
                "build_rows": [{"build_id": "", "session_count": "2", "event_count": "6", "completion_rate": "0.5", "crash_count": "1"}],
                "channel_rows": [{"channel": "", "session_count": "2", "event_count": "6", "completion_rate": "0.5", "crash_count": "1"}],
                "recommendations": ["check trend"],
            },
            "liveops_impact_dashboard": {
                "active_remote_config_count": "1",
                "running_experiment_count": "1",
                "tracked_metric_count": "2",
                "matched_metric_count": "1",
                "available_metric_count": "3",
                "tracked_metrics": ["d1_retention", "tutorial_completion_rate"],
                "available_metrics": ["d1_retention_rate", "funnel_completion_rate"],
                "unmatched_target_metrics": ["tutorial_completion_rate"],
                "metric_matches": [{"target_metric": "d1_retention", "matched_metric": "d1_retention_rate", "source": "telemetry_summary"}],
                "active_entries": [{"entry_type": "experiment_catalog", "entry_id": "tutorial_branch_test", "owner": "product_ops", "status": "running", "rollout_percentage": "50", "matched_metrics": ["d1_retention_rate"], "target_metrics": ["d1_retention"]}],
                "recommendations": ["add mapping"],
            },
            "checks": [{"name": "telemetry_catalog", "status": "ok", "message": "done"}],
        })

        self.assertEqual(summary["schema_version"], TELEMETRY_SUMMARY_SCHEMA_VERSION)
        self.assertEqual(summary["catalog_entry_count"], 1)
        self.assertEqual(summary["session_count"], 1)
        self.assertEqual(summary["event_count"], 2)
        self.assertEqual(summary["pii_violation_count"], 1)
        self.assertFalse(summary["privacy_gate_passed"])
        self.assertEqual(summary["retention_user_count"], 3)
        self.assertEqual(summary["retention_cohorts"][0]["window"], "d1")
        self.assertEqual(summary["funnel_breakdown"][0]["step"], "session_start")
        self.assertEqual(summary["crash_taxonomy"][0]["crash_type"], "unknown")
        self.assertEqual(summary["crash_clusters"][0]["cluster_id"], "unknown_cluster")
        self.assertEqual(summary["crash_clusters"][0]["builds"], ["qa"])
        self.assertEqual(summary["crash_regression_dashboard"]["affected_build_count"], 2)
        self.assertEqual(summary["crash_regression_dashboard"]["build_regressions"][0]["build_id"], "unknown_build")
        self.assertEqual(summary["crash_regression_dashboard"]["scene_regressions"][0]["scene_path"], "unknown_scene")
        self.assertEqual(summary["retention_funnel_dashboard"]["lowest_retention_window"], "d7")
        self.assertEqual(summary["retention_funnel_dashboard"]["largest_dropoff_step"], "level_complete")
        self.assertEqual(summary["retention_funnel_dashboard"]["funnel_dropoffs"][0]["previous_event_name"], "level_start")
        self.assertEqual(summary["retention_funnel_trend_dashboard"]["day_rows"][0]["date"], "2026-04-10")
        self.assertEqual(summary["retention_funnel_trend_dashboard"]["build_rows"][0]["build_id"], "unknown_build")
        self.assertEqual(summary["liveops_impact_dashboard"]["matched_metric_count"], 1)
        self.assertEqual(summary["liveops_impact_dashboard"]["active_entries"][0]["entry_id"], "tutorial_branch_test")
        self.assertEqual(summary["catalog_entries"][0]["privacy_level"], "anonymous")
        self.assertEqual(summary["checks"][0]["status"], "skipped")

    def test_performance_summary_normalizes_metrics_and_checks(self):
        summary = normalize_performance_summary({
            "passed": True,
            "scene_path": "res://scenes/main_scene.tscn",
            "baseline_path": "tests/baselines/performance/main_scene.json",
            "profile_path": "logs/test_artifacts/performance_profile_main_scene.json",
            "issues": ["draw call 超标"],
            "checks": [
                {"name": "draw_call_budget", "status": "ok", "message": "done"},
            ],
            "metrics": {"draw_call_count": 320},
            "budgets": {"max_draw_call_count": 300},
            "frame_breakdown": [{"stage": "cpu", "ms": "5.5", "budget_ms": "8.0"}],
            "memory_trend": {"sample_count": "4", "min_mb": "100", "max_mb": "140", "avg_mb": "120", "growth_mb": "40", "trend_status": "growing"},
        })

        self.assertEqual(summary["schema_version"], PERFORMANCE_SUMMARY_SCHEMA_VERSION)
        self.assertEqual(summary["metrics"]["draw_call_count"], 320)
        self.assertEqual(summary["budgets"]["max_draw_call_count"], 300)
        self.assertEqual(summary["checks"][0]["status"], "skipped")
        self.assertEqual(summary["frame_breakdown"][0]["stage"], "cpu")
        self.assertEqual(summary["memory_trend"]["growth_mb"], 40.0)
        self.assertEqual(summary["issues"], ["draw call 超标"])

    def test_liveops_profile_normalizes_entries_and_counts(self):
        profile = normalize_liveops_profile({
            "liveops_type": "experiment_catalog",
            "entry_count": "1",
            "active_entry_count": "1",
            "rollout_count": "1",
            "variant_count": "2",
            "target_metric_count": "2",
            "issues": ["missing owner"],
            "entries": [{
                "experiment_id": "tutorial_short_path",
                "status": "RUNNING",
                "hypothesis": "shorter tutorial improves completion",
                "target_metrics": ["tutorial_completion_rate", "d1_retention"],
                "variants": [
                    {"variant_id": "control", "weight": "50"},
                    {"variant_id": "short_path", "weight": "50"},
                ],
            }],
        })

        self.assertEqual(profile["schema_version"], LIVEOPS_PROFILE_SCHEMA_VERSION)
        self.assertEqual(profile["liveops_type"], "experiment_catalog")
        self.assertEqual(profile["entry_count"], 1)
        self.assertEqual(profile["variant_count"], 2)
        self.assertEqual(profile["entries"][0]["status"], "running")
        self.assertEqual(profile["entries"][0]["variants"][0]["weight"], 50.0)
        self.assertEqual(profile["issues"], ["missing owner"])

    def test_platform_delivery_profile_normalizes_counts_and_defaults(self):
        profile = normalize_platform_delivery_profile({
            "manifest_path": "res://deployment/platform_delivery.json",
            "platforms": [{
                "platform_id": "web",
                "store": "web",
                "preset_name": "Web",
                "output_path": "builds/web/index.html",
                "feature_flags": ["analytics"],
            }],
            "savegame": {
                "schema_id": "profile_save",
                "version": "1.0.0",
                "save_mode": "cloud_optional",
                "slot_count": "3",
                "fields": [{"name": "player_level", "type": "int", "required": True, "default": 1}],
            },
            "services": {"cloud_save": True},
            "multiplayer": {"enabled": True, "mode": "coop", "transport": "enet", "max_players": "4"},
        })

        self.assertEqual(profile["schema_version"], PLATFORM_DELIVERY_PROFILE_SCHEMA_VERSION)
        self.assertEqual(profile["platform_count"], 1)
        self.assertEqual(profile["service_count"], 2)
        self.assertEqual(profile["savegame"]["slot_count"], 3)
        self.assertEqual(profile["multiplayer"]["transport"], "enet")

    def test_outsource_delivery_gate_normalizes_deliveries_and_status(self):
        gate = normalize_outsource_delivery_gate({
            "project_root": "D:/repo",
            "runtime_root": "D:/repo",
            "mode": "advisory",
            "fail_on_warnings": True,
            "required_license_names": ["work_for_hire", "work_for_hire"],
            "checklist": [
                {"item_id": "manifest_available", "label": "Manifest", "status": "passed", "required": True, "message": "ok"},
                {"item_id": "package_budget", "label": "Budget", "status": "warning", "required": False, "message": "missing estimate"},
            ],
            "deliveries": [{
                "asset_id": "",
                "status": "warning",
                "package_version": "v2026_04",
                "license_name": "work_for_hire",
                "source_tool": "outsource_delivery",
                "target_exists": True,
                "target_size_mb": "12.5",
                "estimated_memory_mb": "10",
                "issues": [],
                "warnings": ["estimated_memory_mb_missing", "estimated_memory_mb_missing"],
                "tags": ["vendor", "vendor"],
            }],
        })

        self.assertEqual(gate["schema_version"], OUTSOURCE_DELIVERY_GATE_SCHEMA_VERSION)
        self.assertEqual(gate["status"], "warning")
        self.assertFalse(gate["should_block"])
        self.assertEqual(gate["required_license_names"], ["work_for_hire"])
        self.assertEqual(gate["deliveries"][0]["asset_id"], "unnamed_delivery")
        self.assertEqual(gate["deliveries"][0]["target_size_mb"], 12.5)
        self.assertEqual(gate["deliveries"][0]["estimated_memory_mb"], 10.0)
        self.assertEqual(gate["deliveries"][0]["warnings"], ["estimated_memory_mb_missing"])
        self.assertEqual(gate["warning_checks"], ["package_budget"])

    def test_asset_review_workflow_normalizes_entries_and_counts(self):
        workflow = normalize_asset_review_workflow({
            "project_root": "D:/repo",
            "runtime_root": "D:/repo",
            "asset_type": "outsource",
            "checklist": [
                {"item_id": "source_manifest_available", "label": "Manifest", "status": "passed", "required": True, "message": "ok"},
                {"item_id": "pending_review", "label": "Pending", "status": "warning", "required": False, "message": "1 pending"},
            ],
            "review_entries": [{
                "asset_type": "outsource",
                "asset_id": "",
                "status": "warning",
                "review_status": "unknown",
                "source_manifest_path": "assets/manifests/outsource_assets.json",
                "target_path": "res://assets/packages/outsource/npc_vendor_delivery.zip",
                "reviewer": "",
                "review_note": "needs polish",
                "reviewed_at": "",
                "tags": ["vendor", "vendor"],
                "warnings": ["missing_reviewer", "missing_reviewer"],
            }],
        })

        self.assertEqual(workflow["schema_version"], ASSET_REVIEW_WORKFLOW_SCHEMA_VERSION)
        self.assertEqual(workflow["status"], "warning")
        self.assertEqual(workflow["review_entries"][0]["asset_id"], "unnamed_asset")
        self.assertEqual(workflow["review_entries"][0]["review_status"], "pending_review")
        self.assertEqual(workflow["review_entries"][0]["tags"], ["vendor"])
        self.assertEqual(workflow["pending_review_count"], 1)
        self.assertEqual(workflow["warning_checks"], ["pending_review"])

    def test_build_run_matrix_normalizes_rows_and_nested_contracts(self):
        matrix = normalize_build_run_matrix({
            "project_root": "D:/repo",
            "runtime_root": "D:/repo",
            "mode": "strict",
            "platform_delivery_profile": {
                "manifest_path": "res://deployment/platform_delivery.json",
                "platforms": [{
                    "platform_id": "web",
                    "preset_name": "Web",
                    "output_path": "builds/web/index.html",
                }],
                "savegame": {
                    "schema_id": "profile_save",
                    "version": "1.0.0",
                    "save_mode": "cloud_optional",
                    "slot_count": 3,
                    "fields": [{"name": "player_level", "type": "int", "required": True, "default": 1}],
                },
            },
            "release_candidate_checklist": {
                "release_summary": {"build_id": "web-qa-001", "channel": "qa"},
                "quality_gate": {"passed": True, "checks": [{"name": "smoke_test", "status": "passed"}]},
            },
            "scenarios": [{
                "scenario_id": "release_candidate",
                "label": "Release Candidate",
                "required_evidence": ["feature_approval", "quality_gate"],
            }],
            "rows": [
                {
                    "row_id": "build_web",
                    "row_type": "build",
                    "label": "Build Export: web",
                    "status": "passed",
                    "required": True,
                    "default_selected": True,
                    "platform_id": "web",
                    "scenario_ids": ["release_candidate", "release_candidate"],
                    "execution_mode": "build",
                    "command": "godot --headless --export-release",
                },
                {
                    "row_id": "godot_live_sandbox",
                    "row_type": "run",
                    "label": "Godot Live Sandbox",
                    "status": "warning",
                    "required": False,
                    "warning_reasons": ["needs runtime", "needs runtime"],
                },
            ],
        })

        self.assertEqual(matrix["schema_version"], "1.0")
        self.assertEqual(matrix["row_count"], 2)
        self.assertEqual(matrix["build_count"], 1)
        self.assertEqual(matrix["run_count"], 1)
        self.assertEqual(matrix["warning_rows"], ["godot_live_sandbox"])
        self.assertEqual(matrix["platform_delivery_profile"]["platform_count"], 1)
        self.assertEqual(matrix["release_candidate_checklist"]["release_summary"]["schema_version"], RELEASE_SUMMARY_SCHEMA_VERSION)
        self.assertEqual(matrix["rows"][0]["scenario_ids"], ["release_candidate"])
        self.assertEqual(matrix["rows"][1]["warning_reasons"], ["needs runtime"])

    def test_scene_ownership_board_normalizes_entries_and_counts(self):
        board = normalize_scene_ownership_board({
            "project_root": "D:/repo",
            "runtime_root": "D:/repo",
            "mode": "advisory",
            "fail_on_warnings": True,
            "checklist": [
                {"item_id": "board_path", "label": "Board", "status": "passed", "required": True, "message": "ok"},
                {"item_id": "owner_coverage", "label": "Owner Coverage", "status": "warning", "required": False, "message": "1 missing"},
            ],
            "scene_entries": [
                {
                    "scene_path": "",
                    "scene_name": "",
                    "scene_category": "level",
                    "status": "warning",
                    "owner": "",
                    "feature_id": "",
                    "lock_state": "locked",
                    "source_manifest_path": "data_tables/levels/forest_gateway.json",
                    "source_manifest_exists": True,
                    "note": "needs owner",
                },
                {
                    "scene_path": "res://scenes/ui/hud_root.tscn",
                    "scene_name": "hud_root",
                    "scene_category": "ui",
                    "status": "passed",
                    "owner": "ui_team",
                    "feature_id": "feature_ui_refresh",
                    "lock_state": "shared",
                },
            ],
        })

        self.assertEqual(board["schema_version"], SCENE_OWNERSHIP_BOARD_SCHEMA_VERSION)
        self.assertEqual(board["status"], "warning")
        self.assertFalse(board["should_block"])
        self.assertEqual(board["scene_entries"][0]["scene_path"], "res://scenes/unnamed_scene.tscn")
        self.assertEqual(board["scene_entries"][0]["lock_state"], "locked")
        self.assertEqual(board["locked_count"], 1)
        self.assertEqual(board["shared_count"], 1)
        self.assertEqual(board["missing_owner_count"], 1)
        self.assertEqual(board["warning_checks"], ["owner_coverage"])

    def test_release_delivery_readiness_normalizes_components_and_next_actions(self):
        readiness = normalize_release_delivery_readiness({
            "target_channel": "release",
            "target_environment": "production",
            "status": "warning",
            "summary": "identity=passed / workflow=warning / distribution=warning / next_actions=3",
            "components": [
                {
                    "component_id": "identity_boundary",
                    "label": "External Identity Boundary",
                    "status": "passed",
                    "required": True,
                    "summary": "identity ready",
                    "paths": {"report_path": "logs/reports/release_request_auth_identity_audit_release.json"},
                },
                {
                    "component_id": "workflow_release",
                    "label": "Self-Hosted Workflow Release",
                    "status": "warning",
                    "required": True,
                    "summary": "dispatch pending",
                    "warning_checks": ["github_workflow_not_observed"],
                    "details": {"dispatch_run_status": "queued"},
                },
                {
                    "component_id": "distribution_delivery",
                    "label": "External Distribution Delivery",
                    "status": "warning",
                    "required": True,
                    "summary": "publish handoff pending",
                    "warning_checks": ["distribution_publish_handoff_incomplete"],
                },
            ],
            "next_actions": [
                {
                    "action_id": "self_hosted_release_workflow",
                    "label": "Run real release workflow",
                    "status": "warning",
                    "owner_hint": "release_engineering",
                    "dependency": "github_actions_self_hosted_windows_runner",
                    "eta": "before_release_gate",
                    "validation_method": "release_live_dispatch_audit_and_release_live_ci_summary",
                    "blockers": ["github_workflow_not_observed"],
                    "entrypoint": "python .\\tools\\dispatch_release_live_gates.py --wait",
                }
            ],
        })

        self.assertEqual(readiness["schema_version"], RELEASE_DELIVERY_READINESS_SCHEMA_VERSION)
        self.assertEqual(readiness["component_count"], 3)
        self.assertEqual(readiness["warning_count"], 2)
        self.assertEqual(readiness["identity_boundary"]["status"], "passed")
        self.assertEqual(readiness["workflow_release"]["warning_checks"], ["github_workflow_not_observed"])
        self.assertEqual(readiness["next_actions"][0]["action_id"], "self_hosted_release_workflow")
        self.assertEqual(readiness["next_actions"][0]["dependency"], "github_actions_self_hosted_windows_runner")
        self.assertEqual(readiness["next_actions"][0]["eta"], "before_release_gate")
        self.assertEqual(readiness["next_actions"][0]["validation_method"], "release_live_dispatch_audit_and_release_live_ci_summary")
        self.assertEqual(readiness["next_actions"][0]["blockers"], ["github_workflow_not_observed"])

    def test_release_promotion_plan_normalizes_nested_contracts_and_signoffs(self):
        plan = normalize_release_promotion_plan({
            "project_root": "D:/repo",
            "runtime_root": "D:/repo",
            "target_channel": "staging",
            "target_environment": "staging",
            "required_signoffs": ["qa_lead", "tech_lead", "producer"],
            "provided_signoffs": ["qa_lead", "tech_lead"],
            "checklist": [
                {"item_id": "release_candidate_gate", "label": "RC", "status": "passed", "required": True, "message": "ok"},
                {"item_id": "signoff_gate", "label": "Signoffs", "status": "blocked", "required": True, "message": "missing producer"},
            ],
            "release_candidate_checklist": {
                "release_summary": {"build_id": "web-qa-001", "channel": "qa"},
                "quality_gate": {"passed": True, "checks": [{"name": "smoke_test", "status": "passed"}]},
            },
            "build_run_matrix": {
                "rows": [{"row_id": "non_live_regression", "row_type": "run", "status": "passed", "required": True}],
            },
            "scene_ownership_board": {
                "scene_entries": [{"scene_path": "res://scenes/levels/forest_gateway.tscn", "owner": "level_team", "feature_id": "feature_level_polish", "lock_state": "locked"}],
            },
            "agent_compatibility_summary": {
                "status": "passed",
                "passed": True,
                "provider_count": 2,
                "surface_count": 9,
            },
            "release_live_runner_baseline": {
                "status": "passed",
                "path": "logs/reports/release_live_runner_baseline_staging.json",
                "summary": "checks=10 / passed=10 / warning=0 / blocked=0",
                "details": {
                    "target_channel": "staging",
                    "target_environment": "staging",
                    "report_path": "logs/reports/release_live_runner_baseline_staging.json",
                    "runner_profile_path": "deployment/release_live_runner_profile.json",
                    "runner_profile_id": "release_windows_runner",
                    "runner_name": "godot-release-01",
                    "runner_os": "Windows",
                    "runner_arch": "x64",
                    "declared_runner_labels": ["self-hosted", "windows", "godot"],
                    "github_actions": True,
                    "github_workflow": "release-live-gates",
                    "github_job": "live-release-gates",
                    "github_run_id": "1234567890",
                    "github_run_attempt": "1",
                    "python_version": "3.12.10",
                    "required_runner_os": "Windows",
                    "required_runner_arches": ["x64"],
                    "required_runner_labels": ["self-hosted", "windows", "godot"],
                    "allowed_runner_names": ["godot-release-01"],
                    "check_count": 10,
                    "passed_check_count": 10,
                    "warning_check_count": 0,
                    "blocked_check_count": 0,
                    "blocking_checks": [],
                    "warning_checks": [],
                    "checks": [
                        {
                            "check_id": "chromium_browser",
                            "label": "Chromium Browser",
                            "status": "passed",
                            "required": True,
                            "message": "detected via chrome",
                        }
                    ],
                    "recommendations": [],
                    "powershell_executable": "powershell",
                    "godot_executable": "C:/Godot/godot.exe",
                    "browser_executable": "C:/Program Files/Google/Chrome/Application/chrome.exe",
                },
            },
            "release_live_ci_summary": {
                "status": "passed",
                "path": "logs/reports/release_live_ci/release_live_ci_summary.json",
                "summary": "ci_gate=passed / lanes=1 / signoffs=passed",
                "details": {
                    "artifact_dir": "logs/reports/release_live_ci",
                    "generated_at": "2026-04-18T10:00:00Z",
                    "target_channel": "staging",
                    "target_environment": "staging",
                    "release_build_id": "web-qa-001",
                    "release_version": "0.1.0-qa+1",
                    "release_channel": "staging",
                    "release_manifest_path": "api_server/static/dist/release_manifest.json",
                    "summary_markdown_path": "logs/reports/release_live_ci/release_live_ci_summary.md",
                    "summary_markdown_exists": True,
                    "workflow_step_results_path": "logs/reports/release_live_ci/release_live_ci_workflow_steps.json",
                    "dispatch_audit": {
                        "status": "warning",
                        "summary": "workflow_dispatch accepted for sossossal/cim-comm-soc@main",
                        "path": "logs/reports/release_live_ci/release_live_dispatch.json",
                        "recorded_at": "2026-04-18T10:10:00Z",
                        "triggered_by": "release_manager",
                        "workflow": "release-live-gates.yml",
                        "repo": "sossossal/cim-comm-soc",
                        "ref": "main",
                        "target_channel": "staging",
                        "target_environment": "staging",
                        "ready": True,
                        "dispatch_attempted": True,
                        "dispatch_completed": True,
                        "wait": True,
                        "follow_up_required": False,
                        "token_source": "GH_TOKEN",
                        "run": {
                            "id": 9001,
                            "status": "completed",
                            "conclusion": "success",
                            "html_url": "https://github.com/sossossal/cim-comm-soc/actions/runs/9001",
                        },
                        "request_auth": {
                            "status": "passed",
                            "actor_id": "release_manager",
                            "reason": "accepted",
                        },
                    },
                    "event_stream": {
                        "status": "passed",
                        "path": "release_live_ci_events.json",
                        "summary": "events=4 / blocked=0 / warning=0 / latest=run_finished",
                        "route_kind": "local_replay",
                        "route_id": "local_replay:staging:staging",
                        "invocation_source": "local_replay",
                        "event_count": 4,
                        "blocked_event_count": 0,
                        "warning_event_count": 0,
                        "latest_event_type": "run_finished",
                        "latest_event_status": "passed",
                        "events": [
                            {
                                "event_id": "run_started_1",
                                "event_type": "run_started",
                                "scope": "run",
                                "order": 1,
                                "status": "passed",
                                "occurred_at": "2026-04-18T10:00:00Z",
                                "summary": "route=local_replay",
                            }
                        ],
                    },
                    "runtime_assembly": {
                        "schema_version": "1.0",
                        "status": "warning",
                        "summary": "route=local_replay / actor=- / allowed=3 / warning=0 / blocked=1 / identity=passed",
                        "route_kind": "local_replay",
                        "route_id": "local_replay:staging:staging",
                        "session_id": "web-qa-001",
                        "invocation_source": "local_replay",
                        "target_channel": "staging",
                        "target_environment": "staging",
                        "allowed_count": 3,
                        "warning_count": 0,
                        "denied_count": 1,
                        "enabled_sandbox_profiles": ["read_only", "browser_automation"],
                        "denied_sandbox_profiles": ["release_write"],
                        "auth_profile": {
                            "actor_present": False,
                            "requires_actor_count": 2,
                            "request_auth_required_count": 1,
                            "request_auth_warning_capability_ids": ["release_execution_rollout_write"],
                        },
                        "identity_boundary": {
                            "status": "passed",
                            "profile_id": "staging_identity_boundary",
                            "provider_mode": "project_manifest",
                        },
                        "runner_profile": {
                            "status": "passed",
                            "profile_id": "release_windows_runner",
                            "runner_name": "godot-release-01",
                        },
                    },
                    "invocation": {
                        "source": "local_replay",
                        "mode": "advisory",
                        "fail_on_warnings": False,
                        "providers": ["codex"],
                        "approvers": ["qa_lead", "tech_lead", "producer"],
                    },
                    "ci_gate": {
                        "status": "passed",
                        "should_block": False,
                        "fail_on_warnings": False,
                        "blocking_checks": [],
                        "warning_checks": [],
                        "evaluated_check_count": 3,
                    },
                    "runtime_gates": {
                        "release_live_runner_baseline_status": "passed",
                        "full_live_validation_status": "passed",
                        "distribution_bundle_status": "warning",
                        "distribution_signing_handoff_status": "skipped",
                        "distribution_publish_handoff_status": "skipped",
                        "distribution_publish_receipts_status": "skipped",
                        "identity_handoff_status": "passed",
                    },
                    "runtime_lanes": {
                        "full_live_validation": [
                            {
                                "lane_id": "portal_click_smoke",
                                "label": "Portal Click Smoke",
                                "status": "passed",
                                "summary": "click ok",
                                "report_path": "logs/reports/full_live_validation_lanes/portal_click_smoke.json",
                                "artifact_paths": ["logs/test_artifacts/portal_click_chrome_8014.out"],
                                "flow_statuses": {
                                    "release_promotion_history_report_flow": "passed",
                                },
                            }
                        ]
                    },
                    "workflow_steps": [
                        {
                            "step_id": "export_runner_baseline",
                            "label": "Export release-live runner baseline",
                            "status": "passed",
                            "outcome": "success",
                            "always_run": False,
                            "message": "",
                        },
                        {
                            "step_id": "run_full_live_validation",
                            "label": "Run full live validation",
                            "status": "warning",
                            "outcome": "failure",
                            "always_run": False,
                            "message": "portal click smoke failed",
                        },
                    ],
                    "human_signoffs": {
                        "status": "passed",
                        "required_signoffs": ["qa_lead", "tech_lead", "producer"],
                        "provided_signoffs": ["qa_lead", "tech_lead", "producer"],
                        "missing_signoffs": [],
                    },
                },
            },
            "request_auth_posture": {
                "schema_version": "1.0",
                "status": "passed",
                "path": "deployment/release_request_auth.json",
                "manifest_path": "deployment/release_request_auth.json",
                "report_path": "logs/reports/release_request_auth_posture_promotion_record_staging.json",
                "report_exists": True,
                "manifest_exists": True,
                "identity_registry_path": "deployment/release_identity_registry.json",
                "identity_registry_exists": True,
                "identity_boundary_path": "deployment/release_identity_boundary.json",
                "identity_boundary_exists": True,
                "identity_boundary_profile_id": "staging_identity_boundary",
                "identity_boundary_status": "passed",
                "identity_boundary_summary": "profile=staging_identity_boundary / provider=passed / session=passed / secret_rotation=passed",
                "identity_provider_mode": "project_manifest",
                "identity_provider_id": "release_request_auth_manifest",
                "identity_provider_status": "passed",
                "identity_session_policy_status": "passed",
                "identity_session_required": True,
                "identity_max_session_age_hours": 48,
                "identity_session_backend": "identity_registry",
                "identity_secret_rotation_status": "passed",
                "identity_secret_rotation_required": True,
                "identity_secret_backend": "deployment_manifest",
                "identity_rotation_owner": "ops_release",
                "identity_rotation_window_days": 30,
                "action": "promotion_record",
                "target_channel": "staging",
                "target_environment": "staging",
                "summary": "matching manifest tokens are actor-bound and local bypass is disabled",
                "allow_local_without_token": False,
                "env_fallback_configured": False,
                "rotation_window_days": 30,
                "token_count": 1,
                "active_token_count": 1,
                "matching_token_count": 1,
                "matching_bound_token_count": 1,
                "matching_unbound_token_count": 0,
                "matching_session_token_count": 0,
                "issuer_count": 1,
                "active_issuer_count": 1,
                "matching_registered_issuer_token_count": 1,
                "matching_unknown_issuer_token_count": 0,
                "matching_inactive_issuer_token_count": 0,
                "matching_unscoped_issuer_token_count": 0,
                "matching_subject_out_of_registry_count": 0,
                "matching_stale_session_token_count": 0,
                "revoked_token_count": 0,
                "expired_token_count": 0,
                "invalid_expiry_token_count": 0,
                "invalid_issued_at_token_count": 0,
                "tokens_without_expiry_count": 0,
                "tokens_expiring_soon_count": 0,
                "tokens_without_session_id_count": 0,
                "tokens_without_issued_by_count": 0,
                "tokens_without_issued_at_count": 0,
                "duplicate_token_id_count": 0,
                "matching_token_ids": ["staging_producer"],
                "duplicate_token_ids": [],
                "notes": ["matching tokens=staging_producer"],
                "recommendations": [],
            },
            "request_auth_rotation_audit": {
                "schema_version": "1.0",
                "status": "warning",
                "summary": "actions=2 / passed=1 / warning=1 / blocked=0",
                "auth_path": "deployment/release_request_auth.json",
                "manifest_exists": True,
                "target_channel": "staging",
                "target_environment": "staging",
                "actions": ["promotion_record", "release_execution"],
                "action_count": 2,
                "passed_action_count": 1,
                "warning_action_count": 1,
                "blocked_action_count": 0,
                "report_path": "logs/reports/release_request_auth_rotation_audit_staging.json",
                "report_exists": True,
                "coverage": [
                    {
                        "schema_version": "1.0",
                        "status": "passed",
                        "path": "deployment/release_request_auth.json",
                        "manifest_path": "deployment/release_request_auth.json",
                        "report_path": "logs/reports/release_request_auth_posture_promotion_record_staging.json",
                        "report_exists": True,
                        "manifest_exists": True,
                        "identity_registry_path": "deployment/release_identity_registry.json",
                        "identity_registry_exists": True,
                        "action": "promotion_record",
                        "target_channel": "staging",
                        "target_environment": "staging",
                        "summary": "matching manifest tokens are actor-bound and local bypass is disabled",
                        "allow_local_without_token": False,
                        "env_fallback_configured": False,
                        "rotation_window_days": 30,
                        "token_count": 1,
                        "active_token_count": 1,
                        "matching_token_count": 1,
                        "matching_bound_token_count": 1,
                        "matching_unbound_token_count": 0,
                        "matching_session_token_count": 0,
                        "issuer_count": 1,
                        "active_issuer_count": 1,
                        "matching_registered_issuer_token_count": 1,
                        "matching_unknown_issuer_token_count": 0,
                        "matching_inactive_issuer_token_count": 0,
                        "matching_unscoped_issuer_token_count": 0,
                        "matching_subject_out_of_registry_count": 0,
                        "matching_stale_session_token_count": 0,
                        "revoked_token_count": 0,
                        "expired_token_count": 0,
                        "invalid_expiry_token_count": 0,
                        "invalid_issued_at_token_count": 0,
                        "tokens_without_expiry_count": 0,
                        "tokens_expiring_soon_count": 0,
                        "tokens_without_session_id_count": 0,
                        "tokens_without_issued_by_count": 0,
                        "tokens_without_issued_at_count": 0,
                        "duplicate_token_id_count": 0,
                        "matching_token_ids": ["staging_producer"],
                        "duplicate_token_ids": [],
                        "notes": ["matching tokens=staging_producer"],
                        "recommendations": [],
                    }
                ],
                "notes": ["promotion_record: matching manifest tokens are actor-bound and local bypass is disabled"],
                "recommendations": ["先清理 token rotation hygiene，再把当前 manifest 当成正式发布凭据。"],
            },
            "request_auth_identity_audit": {
                "schema_version": "1.0",
                "status": "warning",
                "summary": "actions=2 / passed=0 / warning=2 / blocked=0 / scoped_issuers=1",
                "auth_path": "deployment/release_request_auth.json",
                "manifest_exists": True,
                "identity_path": "deployment/release_identity_registry.json",
                "identity_registry_exists": True,
                "target_channel": "staging",
                "target_environment": "staging",
                "actions": ["promotion_record", "release_execution"],
                "action_count": 2,
                "passed_action_count": 0,
                "warning_action_count": 2,
                "blocked_action_count": 0,
                "issuer_count": 1,
                "active_issuer_count": 1,
                "scoped_issuer_count": 1,
                "session_required_issuer_count": 1,
                "session_windowed_issuer_count": 0,
                "unbound_issuer_count": 0,
                "duplicate_issuer_id_count": 0,
                "duplicate_issuer_ids": [],
                "matching_registered_issuer_token_count": 1,
                "matching_unknown_issuer_token_count": 0,
                "matching_inactive_issuer_token_count": 0,
                "matching_unscoped_issuer_token_count": 0,
                "matching_subject_out_of_registry_count": 0,
                "matching_stale_session_token_count": 0,
                "matching_session_token_count": 0,
                "release_issuers_without_session_requirement_count": 0,
                "release_issuers_without_session_window_count": 0,
                "report_path": "logs/reports/release_request_auth_identity_audit_staging.json",
                "report_exists": True,
                "coverage": [
                    {
                        "schema_version": "1.0",
                        "status": "passed",
                        "path": "deployment/release_request_auth.json",
                        "manifest_path": "deployment/release_request_auth.json",
                        "report_path": "logs/reports/release_request_auth_posture_promotion_record_staging.json",
                        "report_exists": True,
                        "manifest_exists": True,
                        "identity_registry_path": "deployment/release_identity_registry.json",
                        "identity_registry_exists": True,
                        "action": "promotion_record",
                        "target_channel": "staging",
                        "target_environment": "staging",
                        "summary": "matching manifest tokens are actor-bound and local bypass is disabled",
                        "allow_local_without_token": False,
                        "env_fallback_configured": False,
                        "rotation_window_days": 30,
                        "token_count": 1,
                        "active_token_count": 1,
                        "matching_token_count": 1,
                        "matching_bound_token_count": 1,
                        "matching_unbound_token_count": 0,
                        "matching_session_token_count": 0,
                        "issuer_count": 1,
                        "active_issuer_count": 1,
                        "matching_registered_issuer_token_count": 1,
                        "matching_unknown_issuer_token_count": 0,
                        "matching_inactive_issuer_token_count": 0,
                        "matching_unscoped_issuer_token_count": 0,
                        "matching_subject_out_of_registry_count": 0,
                        "matching_stale_session_token_count": 0,
                        "revoked_token_count": 0,
                        "expired_token_count": 0,
                        "invalid_expiry_token_count": 0,
                        "invalid_issued_at_token_count": 0,
                        "tokens_without_expiry_count": 0,
                        "tokens_expiring_soon_count": 0,
                        "tokens_without_session_id_count": 0,
                        "tokens_without_issued_by_count": 0,
                        "tokens_without_issued_at_count": 0,
                        "duplicate_token_id_count": 0,
                        "matching_token_ids": ["staging_producer"],
                        "duplicate_token_ids": [],
                        "notes": ["matching tokens=staging_producer"],
                        "recommendations": [],
                    }
                ],
                "notes": ["promotion_record=warning"],
                "recommendations": ["补齐 issuer registry 覆盖、subject actor 绑定和 session 策略，再把当前 identity registry 当成正式发布证据。"],
            },
            "release_distribution_bundle": {
                "schema_version": "1.0",
                "status": "warning",
                "summary": "source=ready / bundle=missing / payload_files=0 / bundle_files=0",
                "target_channel": "staging",
                "target_environment": "staging",
                "build_id": "web-qa-001",
                "version": "0.1.0-qa+1",
                "release_channel": "qa",
                "release_manifest_path": "api_server/static/dist/release_manifest.json",
                "release_manifest_source": "stable",
                "release_notes_path": "api_server/static/dist/web_001/release_notes.md",
                "qa_gate_report_path": "api_server/static/dist/web_001/qa_gate_report.md",
                "build_log_path": "api_server/static/dist/web_001/build.log",
                "release_dir": "api_server/static/dist/web_001",
                "output_path": "api_server/static/dist/web_001/index.html",
                "release_url": "/portal/dist/index.html",
                "versioned_release_url": "/portal/dist/web_001/index.html",
                "bundle_root": "logs/reports/release_distribution",
                "bundle_dir": "logs/reports/release_distribution/staging/web-qa-001",
                "bundle_exists": False,
                "bundle_file_count": 0,
                "payload_dir": "logs/reports/release_distribution/staging/web-qa-001/release_payload",
                "payload_exists": False,
                "payload_file_count": 0,
                "distribution_manifest_path": "logs/reports/release_distribution/staging/web-qa-001/distribution_manifest.json",
                "distribution_manifest_exists": False,
                "install_script_path": "logs/reports/release_distribution/staging/web-qa-001/install_release_bundle.ps1",
                "install_script_exists": False,
                "upgrade_script_path": "logs/reports/release_distribution/staging/web-qa-001/upgrade_release_bundle.ps1",
                "upgrade_script_exists": False,
                "uninstall_script_path": "logs/reports/release_distribution/staging/web-qa-001/uninstall_release_bundle.ps1",
                "uninstall_script_exists": False,
                "support_matrix_source_path": "docs/支持矩阵与分发说明.md",
                "support_matrix_path": "logs/reports/release_distribution/staging/web-qa-001/support_matrix.md",
                "support_matrix_exists": False,
                "bootstrap_script_source_path": "tools/bootstrap_clean_machine.ps1",
                "bundle_manifest_copy_path": "logs/reports/release_distribution/staging/web-qa-001/release_manifest.json",
                "bundle_manifest_copy_exists": False,
                "bundle_release_notes_path": "logs/reports/release_distribution/staging/web-qa-001/release_notes.md",
                "bundle_release_notes_exists": False,
                "bundle_qa_gate_report_path": "logs/reports/release_distribution/staging/web-qa-001/qa_gate_report.md",
                "bundle_qa_gate_report_exists": False,
                "state_manifest_path": "logs/reports/release_distribution/staging/web-qa-001/installed_release.example.json",
                "state_manifest_exists": False,
                "report_path": "logs/reports/release_distribution_bundle_staging.json",
                "report_exists": True,
                "install_smoke_report_path": "logs/reports/release_distribution_install_smoke_staging.json",
                "install_smoke_report_exists": False,
                "install_smoke_status": "warning",
                "install_smoke_summary": "distribution install smoke report missing",
                "install_smoke_target_root": "",
                "install_smoke_state_path": "",
                "install_smoke_backup_count": 0,
                "install_smoke_marker_preserved": False,
                "install_smoke_current_exists": False,
                "install_smoke_state_written": False,
                "install_smoke_state_removed": False,
                "install_smoke_installed_build_id": "",
                "install_smoke_installed_version": "",
                "install_smoke_previous_build_id": "",
                "install_smoke_backup_dir": "",
                "install_smoke_removed_build_id": "",
                "install_smoke_removed_version": "",
                "archive_dir": "logs/reports/release_distribution_packages/staging/web-qa-001",
                "archive_exists": False,
                "archive_path": "logs/reports/release_distribution_packages/staging/web-qa-001/release_distribution_bundle.zip",
                "archive_file_exists": False,
                "archive_sha256_path": "logs/reports/release_distribution_packages/staging/web-qa-001/release_distribution_bundle.sha256",
                "archive_sha256_exists": False,
                "archive_size_bytes": 0,
                "archive_status": "skipped",
                "archive_summary": "distribution archive not ready",
                "channel_index_dir": "logs/reports/release_distribution_channels/staging",
                "channel_index_exists": False,
                "channel_index_report_path": "logs/reports/release_distribution_channel_staging.json",
                "channel_index_report_exists": False,
                "channel_index_latest_path": "logs/reports/release_distribution_channels/staging/latest.json",
                "channel_index_latest_exists": False,
                "channel_index_releases_path": "logs/reports/release_distribution_channels/staging/releases.json",
                "channel_index_releases_exists": False,
                "channel_index_release_count": 0,
                "channel_index_latest_build_id": "",
                "channel_index_latest_matches_current": False,
                "channel_index_status": "skipped",
                "channel_index_summary": "distribution channel index not ready",
                "handoff_dir": "logs/reports/release_distribution_handoff/staging/web-qa-001",
                "handoff_exists": False,
                "handoff_file_count": 0,
                "handoff_manifest_path": "logs/reports/release_distribution_handoff/staging/web-qa-001/distribution_handoff_manifest.json",
                "handoff_manifest_exists": False,
                "handoff_install_script_path": "logs/reports/release_distribution_handoff/staging/web-qa-001/install_release_handoff.ps1",
                "handoff_install_script_exists": False,
                "handoff_upgrade_script_path": "logs/reports/release_distribution_handoff/staging/web-qa-001/upgrade_release_handoff.ps1",
                "handoff_upgrade_script_exists": False,
                "handoff_uninstall_script_path": "logs/reports/release_distribution_handoff/staging/web-qa-001/uninstall_release_handoff.ps1",
                "handoff_uninstall_script_exists": False,
                "handoff_archive_path": "logs/reports/release_distribution_handoff/staging/web-qa-001/packages/release_distribution_bundle.zip",
                "handoff_archive_exists": False,
                "handoff_archive_sha256_path": "logs/reports/release_distribution_handoff/staging/web-qa-001/packages/release_distribution_bundle.sha256",
                "handoff_archive_sha256_exists": False,
                "handoff_channel_latest_path": "logs/reports/release_distribution_handoff/staging/web-qa-001/channel/latest.json",
                "handoff_channel_latest_exists": False,
                "handoff_channel_releases_path": "logs/reports/release_distribution_handoff/staging/web-qa-001/channel/releases.json",
                "handoff_channel_releases_exists": False,
                "handoff_status": "skipped",
                "handoff_summary": "distribution handoff not ready",
                "signing_handoff_dir": "logs/reports/release_distribution_signing/staging/web-qa-001",
                "signing_handoff_exists": False,
                "signing_handoff_file_count": 0,
                "signing_handoff_manifest_path": "logs/reports/release_distribution_signing/staging/web-qa-001/distribution_signing_manifest.json",
                "signing_handoff_manifest_exists": False,
                "signing_handoff_instructions_path": "logs/reports/release_distribution_signing/staging/web-qa-001/SIGNING_INSTRUCTIONS.md",
                "signing_handoff_instructions_exists": False,
                "signing_handoff_unsigned_archive_path": "logs/reports/release_distribution_signing/staging/web-qa-001/unsigned/release_distribution_bundle.zip",
                "signing_handoff_unsigned_archive_exists": False,
                "signing_handoff_unsigned_archive_sha256_path": "logs/reports/release_distribution_signing/staging/web-qa-001/unsigned/release_distribution_bundle.sha256",
                "signing_handoff_unsigned_archive_sha256_exists": False,
                "signing_handoff_status": "skipped",
                "signing_handoff_summary": "external signing handoff not required",
                "source_missing_items": [],
                "bundle_missing_items": ["distribution_manifest", "install_script", "release_payload"],
                "handoff_missing_items": ["handoff_manifest", "handoff_install_script", "handoff_archive"],
                "signing_handoff_missing_items": [],
                "delivery_manifest_path": "deployment/release_distribution_delivery.json",
                "delivery_manifest_exists": True,
                "delivery_profile_id": "staging_internal_windows",
                "delivery_status": "passed",
                "delivery_summary": "profile=staging_internal_windows / installer=passed / signing=passed / publish=passed",
                "delivery_primary_installer": "portable_handoff",
                "delivery_installer_types": ["portable_handoff", "archive_zip"],
                "delivery_installer_status": "passed",
                "delivery_signing_required": False,
                "delivery_signing_mode": "sha256_only",
                "delivery_signing_profile_id": "",
                "delivery_signing_status": "passed",
                "delivery_publish_targets": ["staging_ci_artifact"],
                "delivery_publish_target_count": 1,
                "delivery_publish_status": "passed",
                "delivery_first_run_bootstrap": "doctor_self_check",
                "delivery_upgrade_strategy": "in_place_backup",
                "delivery_uninstall_strategy": "scripted_cleanup",
                "exported_files": [],
                "notes": ["bundle_dir=logs/reports/release_distribution/staging/web-qa-001"],
                "recommendations": ["run export_release_distribution_bundle"],
            },
            "evidence_bundle": {
                "artifacts": [
                    {"artifact_id": "release_manifest", "status": "passed", "required": True, "path": "api_server/static/dist/release_manifest.json"},
                    {"artifact_id": "signoff_record", "status": "blocked", "required": True, "summary": "missing producer"},
                ],
            },
            "deployment_rehearsal": {
                "preflight_checks": [
                    {"check_id": "promotion_target", "status": "passed", "required": True, "message": "staging -> staging"},
                ],
                "lane_sequence": ["non_live_regression", "portal_dom_smoke"],
            },
            "review_bundle": {
                "build_id": "web-qa-001",
                "release_channel": "qa",
                "feature": {"feature_id": "feature_level_polish", "feature_status": "pending_acceptance"},
                "change_summary": ["collect signoff"],
                "changed_paths": ["README.md"],
                "acceptance_checklist": [{"label": "smoke", "status": "pending"}],
                "known_issues": ["need final QA signoff"],
                "artifact_links": [
                    {"artifact_id": "release_manifest", "status": "passed", "required": True, "path": "api_server/static/dist/release_manifest.json"},
                ],
                "audience_summaries": [{"audience_id": "qa", "label": "QA", "summary_lines": ["smoke pending"]}],
                "required_signoffs": ["qa_lead", "tech_lead", "producer"],
                "provided_signoffs": ["qa_lead", "tech_lead"],
            },
            "rollback_rehearsal": {
                "rollback_hint": "restore previous build",
                "restore_target": "/portal/dist/web_001/index.html",
                "assets": [
                    {"artifact_id": "restore_target", "status": "passed", "required": True, "path": "/portal/dist/web_001/index.html"},
                ],
                "verification_checks": [
                    {"check_id": "rollback_anchor", "status": "passed", "required": True, "message": "restore previous build"},
                ],
            },
            "promotion_steps": ["run matrix", "collect signoffs"],
        })

        self.assertEqual(plan["schema_version"], RELEASE_PROMOTION_PLAN_SCHEMA_VERSION)
        self.assertEqual(plan["status"], "blocked")
        self.assertTrue(plan["should_block"])
        self.assertEqual(plan["missing_signoffs"], ["producer"])
        self.assertEqual(plan["release_candidate_checklist"]["release_summary"]["schema_version"], RELEASE_SUMMARY_SCHEMA_VERSION)
        self.assertEqual(plan["build_run_matrix"]["row_count"], 1)
        self.assertEqual(plan["evidence_bundle"]["artifact_count"], 2)
        self.assertEqual(plan["evidence_bundle"]["missing_artifacts"], ["signoff_record"])
        self.assertEqual(plan["review_bundle"]["schema_version"], RELEASE_REVIEW_BUNDLE_SCHEMA_VERSION)
        self.assertEqual(plan["review_bundle"]["status"], "warning")
        self.assertEqual(plan["review_bundle"]["acceptance_pending_count"], 1)
        self.assertEqual(plan["request_auth_posture"]["status"], "passed")
        self.assertTrue(plan["request_auth_posture"]["report_exists"])
        self.assertEqual(plan["request_auth_posture"]["rotation_window_days"], 30)
        self.assertEqual(plan["request_auth_posture"]["matching_token_ids"], ["staging_producer"])
        self.assertEqual(plan["request_auth_posture"]["tokens_without_expiry_count"], 0)
        self.assertEqual(plan["request_auth_posture"]["matching_session_token_count"], 0)
        self.assertTrue(plan["request_auth_posture"]["identity_registry_exists"])
        self.assertEqual(plan["request_auth_posture"]["matching_registered_issuer_token_count"], 1)
        self.assertEqual(plan["request_auth_posture"]["tokens_without_session_id_count"], 0)
        self.assertEqual(plan["request_auth_posture"]["identity_boundary_path"], "deployment/release_identity_boundary.json")
        self.assertTrue(plan["request_auth_posture"]["identity_boundary_exists"])
        self.assertEqual(plan["request_auth_posture"]["identity_boundary_profile_id"], "staging_identity_boundary")
        self.assertEqual(plan["request_auth_posture"]["identity_boundary_status"], "passed")
        self.assertEqual(plan["request_auth_posture"]["identity_provider_mode"], "project_manifest")
        self.assertEqual(plan["request_auth_posture"]["identity_session_policy_status"], "passed")
        self.assertEqual(plan["request_auth_posture"]["identity_secret_rotation_status"], "passed")
        self.assertEqual(plan["release_live_runner_baseline"]["status"], "passed")
        self.assertEqual(plan["release_live_runner_baseline"]["path"], "logs/reports/release_live_runner_baseline_staging.json")
        self.assertEqual(plan["release_live_runner_baseline"]["details"]["check_count"], 10)
        self.assertEqual(plan["release_live_runner_baseline"]["details"]["checks"][0]["check_id"], "chromium_browser")
        self.assertEqual(plan["release_live_runner_baseline"]["details"]["runner_profile_id"], "release_windows_runner")
        self.assertEqual(plan["release_live_runner_baseline"]["details"]["runner_name"], "godot-release-01")
        self.assertEqual(plan["release_live_runner_baseline"]["details"]["declared_runner_labels"], ["self-hosted", "windows", "godot"])
        self.assertEqual(plan["release_live_ci_summary"]["status"], "passed")
        self.assertEqual(plan["release_live_ci_summary"]["path"], "logs/reports/release_live_ci/release_live_ci_summary.json")
        self.assertEqual(plan["release_live_ci_summary"]["details"]["summary_markdown_path"], "logs/reports/release_live_ci/release_live_ci_summary.md")
        self.assertTrue(plan["release_live_ci_summary"]["details"]["summary_markdown_exists"])
        self.assertEqual(plan["release_live_ci_summary"]["details"]["workflow_step_results_path"], "logs/reports/release_live_ci/release_live_ci_workflow_steps.json")
        self.assertEqual(plan["release_live_ci_summary"]["details"]["dispatch_audit"]["status"], "warning")
        self.assertEqual(plan["release_live_ci_summary"]["details"]["dispatch_audit"]["path"], "logs/reports/release_live_ci/release_live_dispatch.json")
        self.assertEqual(plan["runtime_assembly_snapshot"]["route_kind"], "local_replay")
        self.assertEqual(plan["runtime_assembly_snapshot"]["runner_profile"]["profile_id"], "release_windows_runner")
        self.assertEqual(plan["release_live_ci_summary"]["details"]["ci_gate"]["evaluated_check_count"], 3)
        self.assertEqual(plan["release_live_ci_summary"]["details"]["runtime_gates"]["distribution_bundle_status"], "warning")
        self.assertEqual(
            plan["release_live_ci_summary"]["details"]["runtime_assembly"]["identity_boundary"]["profile_id"],
            "staging_identity_boundary",
        )
        self.assertEqual(
            plan["release_live_ci_summary"]["details"]["runtime_lanes"]["full_live_validation"][0]["flow_statuses"]["release_promotion_history_report_flow"],
            "passed",
        )
        self.assertEqual(plan["release_live_ci_summary"]["details"]["workflow_steps"][0]["step_id"], "export_runner_baseline")
        self.assertEqual(plan["release_live_ci_summary"]["details"]["workflow_steps"][1]["status"], "warning")
        self.assertEqual(plan["release_live_ci_summary"]["details"]["workflow_steps"][1]["message"], "portal click smoke failed")
        self.assertEqual(plan["release_live_ci_summary"]["details"]["event_stream"]["path"], "release_live_ci_events.json")
        self.assertEqual(plan["release_live_ci_summary"]["details"]["event_stream"]["latest_event_type"], "run_finished")
        self.assertEqual(plan["release_live_ci_summary"]["details"]["event_stream"]["events"][0]["event_type"], "run_started")
        self.assertEqual(plan["request_auth_rotation_audit"]["status"], "warning")
        self.assertTrue(plan["request_auth_rotation_audit"]["report_exists"])
        self.assertEqual(plan["request_auth_rotation_audit"]["warning_action_count"], 1)
        self.assertEqual(plan["request_auth_rotation_audit"]["actions"], ["promotion_record", "release_execution"])
        self.assertEqual(plan["request_auth_rotation_audit"]["coverage"][0]["action"], "promotion_record")
        self.assertEqual(plan["request_auth_identity_audit"]["status"], "warning")
        self.assertTrue(plan["request_auth_identity_audit"]["report_exists"])
        self.assertEqual(plan["request_auth_identity_audit"]["scoped_issuer_count"], 1)
        self.assertEqual(plan["request_auth_identity_audit"]["warning_action_count"], 2)
        self.assertEqual(plan["request_auth_identity_audit"]["coverage"][0]["action"], "promotion_record")
        self.assertEqual(plan["release_distribution_bundle"]["status"], "warning")
        self.assertTrue(plan["release_distribution_bundle"]["report_exists"])
        self.assertEqual(plan["release_distribution_bundle"]["bundle_dir"], "logs/reports/release_distribution/staging/web-qa-001")
        self.assertEqual(plan["release_distribution_bundle"]["bundle_missing_items"], ["distribution_manifest", "install_script", "release_payload"])
        self.assertEqual(plan["release_distribution_bundle"]["install_smoke_status"], "warning")
        self.assertFalse(plan["release_distribution_bundle"]["install_smoke_report_exists"])
        self.assertEqual(plan["release_distribution_bundle"]["install_smoke_state_path"], "")
        self.assertEqual(plan["release_distribution_bundle"]["install_smoke_installed_build_id"], "")
        self.assertEqual(plan["release_distribution_bundle"]["install_smoke_previous_build_id"], "")
        self.assertEqual(plan["release_distribution_bundle"]["archive_status"], "skipped")
        self.assertFalse(plan["release_distribution_bundle"]["archive_file_exists"])
        self.assertEqual(plan["release_distribution_bundle"]["channel_index_status"], "skipped")
        self.assertFalse(plan["release_distribution_bundle"]["channel_index_latest_exists"])
        self.assertEqual(plan["release_distribution_bundle"]["handoff_status"], "skipped")
        self.assertFalse(plan["release_distribution_bundle"]["handoff_manifest_exists"])
        self.assertEqual(plan["release_distribution_bundle"]["signing_handoff_status"], "skipped")
        self.assertFalse(plan["release_distribution_bundle"]["signing_handoff_manifest_exists"])
        self.assertEqual(plan["release_distribution_bundle"]["publish_handoff_status"], "skipped")
        self.assertFalse(plan["release_distribution_bundle"]["publish_handoff_manifest_exists"])
        self.assertEqual(plan["release_distribution_bundle"]["publish_receipts_status"], "skipped")
        self.assertFalse(plan["release_distribution_bundle"]["publish_receipts_manifest_exists"])
        self.assertEqual(plan["release_distribution_bundle"]["delivery_manifest_path"], "deployment/release_distribution_delivery.json")
        self.assertTrue(plan["release_distribution_bundle"]["delivery_manifest_exists"])
        self.assertEqual(plan["release_distribution_bundle"]["delivery_profile_id"], "staging_internal_windows")
        self.assertEqual(plan["release_distribution_bundle"]["delivery_status"], "passed")
        self.assertEqual(plan["release_distribution_bundle"]["delivery_primary_installer"], "portable_handoff")
        self.assertEqual(plan["release_distribution_bundle"]["delivery_signing_status"], "passed")
        self.assertEqual(plan["release_distribution_bundle"]["delivery_publish_targets"], ["staging_ci_artifact"])
        self.assertEqual(plan["deployment_rehearsal"]["lane_sequence"], ["non_live_regression", "portal_dom_smoke"])
        self.assertEqual(plan["rollback_rehearsal"]["restore_target"], "/portal/dist/web_001/index.html")
        self.assertEqual(plan["scene_ownership_board"]["scene_count"], 1)

    def test_release_review_bundle_normalizes_audiences_and_acceptance(self):
        bundle = normalize_release_review_bundle({
            "project_root": "D:/repo",
            "runtime_root": "D:/repo",
            "target_channel": "release",
            "target_environment": "production",
            "build_id": "web-release-001",
            "version": "1.0.0",
            "release_channel": "release",
            "feature": {"feature_id": "feature-001", "feature_status": "approved"},
            "change_summary": ["ship release"],
            "changed_paths": [
                "README.md",
                "README.md",
                "scenes/levels/forest_gateway.tscn",
                "assets/ui/hud.png",
                "scripts/player.gd",
            ],
            "acceptance_checklist": [
                {"label": "smoke", "status": "ready"},
                {"label": "telemetry", "status": "pending"},
            ],
            "known_issues": ["known issue"],
            "artifact_links": [
                {"artifact_id": "release_manifest", "status": "passed", "required": True, "path": "api_server/static/dist/release_manifest.json"},
                {"artifact_id": "build_log", "status": "warning", "required": False, "path": "api_server/static/dist/build.log"},
            ],
            "validation_records": [
                {"record_id": "qa_evidence", "label": "QA Evidence", "status": "passed", "source": "release_qa_evidence", "summary": "qa passed"},
            ],
            "audience_summaries": [{"audience_id": "qa", "label": "QA", "summary_lines": ["telemetry pending"]}],
            "required_signoffs": ["qa_lead"],
            "provided_signoffs": [],
        })

        self.assertEqual(bundle["schema_version"], RELEASE_REVIEW_BUNDLE_SCHEMA_VERSION)
        self.assertEqual(bundle["status"], "warning")
        self.assertEqual(bundle["change_scope_count"], 4)
        self.assertEqual(bundle["change_scope_summary"]["scene_paths"], ["scenes/levels/forest_gateway.tscn"])
        self.assertEqual(bundle["change_scope_summary"]["resource_paths"], ["assets/ui/hud.png"])
        self.assertEqual(bundle["change_scope_summary"]["code_paths"], ["scripts/player.gd"])
        self.assertEqual(bundle["change_scope_summary"]["docs_paths"], ["README.md"])
        self.assertEqual(bundle["validation_record_count"], 5)
        self.assertEqual(bundle["validation_records"][0]["record_id"], "qa_evidence")
        self.assertIn("acceptance_1", [item["record_id"] for item in bundle["validation_records"]])
        self.assertIn("artifact_release_manifest", [item["record_id"] for item in bundle["validation_records"]])
        self.assertEqual(bundle["risk_summary"]["known_issue_count"], 1)
        self.assertEqual(bundle["risk_summary"]["warning_count"], 3)
        self.assertEqual(bundle["risk_summary"]["warning_items"], ["acceptance_checklist", "signoffs", "build_log"])
        self.assertEqual(bundle["signoff_record_count"], 1)
        self.assertEqual(bundle["signoff_records"][0]["actor"], "qa_lead")
        self.assertEqual(bundle["signoff_records"][0]["status"], "missing")
        self.assertTrue(bundle["signoff_records"][0]["required"])
        self.assertIn("signoffs", [item["action_id"] for item in bundle["review_followup_actions"]])
        self.assertIn("validation_artifact_build_log", [item["action_id"] for item in bundle["review_followup_actions"]])
        self.assertEqual(bundle["acceptance_ready_count"], 1)
        self.assertEqual(bundle["acceptance_pending_count"], 1)
        self.assertEqual(bundle["audience_count"], 1)
        self.assertEqual(bundle["warning_items"], ["acceptance_checklist", "signoffs", "build_log"])

    def test_release_review_bundle_blocks_returned_feature_status(self):
        bundle = normalize_release_review_bundle({
            "feature": {
                "feature_id": "feature-001",
                "feature_status": "returned",
                "blockers": ["缺验收截图"],
            },
            "change_summary": ["implemented feature"],
            "changed_paths": ["scripts/player.gd"],
            "acceptance_checklist": [{"label": "smoke", "status": "ready"}],
        })

        self.assertEqual(bundle["status"], "blocked")
        self.assertTrue(bundle["should_block"])
        self.assertIn("feature_status", bundle["blocking_items"])
        self.assertIn("feature_blockers", bundle["blocking_items"])
        self.assertEqual(bundle["risk_summary"]["feature_blocker_count"], 1)
        self.assertTrue(bundle["risk_summary"]["should_block"])
        self.assertIn("feature_blockers", [item["action_id"] for item in bundle["review_followup_actions"]])

    def test_release_promotion_history_normalizes_records_and_filters(self):
        history = normalize_release_promotion_history({
            "project_root": "D:/repo",
            "runtime_root": "D:/repo",
            "history_path": "deployment/release_promotion_history.json",
            "history_exists": True,
            "decision_filter": "approved",
            "target_channel_filter": "staging",
            "executor_filter": "producer_a",
            "live_ci_status_filter": "warning",
            "dispatch_status_filter": "warning",
            "dispatch_follow_up_filter": "clear",
            "dispatch_run_status_filter": "completed",
            "dispatch_run_conclusion_filter": "success",
            "failed_workflow_step_filter": "run_full_live_validation",
            "delivery_readiness_status_filter": "warning",
            "readiness_action_filter": "distribution_publish_receipts",
            "offset": 0,
            "limit": 5,
            "items": [{
                "record_id": "promotion_001",
                "recorded_at": "2026-04-14T10:00:00Z",
                "decision": "approved",
                "target_channel": "staging",
                "target_environment": "staging",
                "promotion_target_label": "staging -> staging",
                "executed_by": "producer_a",
                "note": "ready",
                "signoff_source": "portal_manual",
                "authorization": {
                    "status": "passed",
                    "required": True,
                    "policy_path": "deployment/release_access_policy.json",
                    "policy_source": "manifest",
                    "actor_id": "producer_a",
                    "actor_roles": ["producer"],
                    "action": "promotion_record",
                    "target_channel": "staging",
                    "decision": "approved",
                    "matched_rule_id": "promotion_non_blocking_qa_staging",
                    "required_roles": ["producer", "ops"],
                    "reason": "actor producer_a authorized for promotion_record",
                },
                "request_auth": {
                    "status": "passed",
                    "required": False,
                    "auth_path": "deployment/release_request_auth.json",
                    "mode": "local_only",
                    "client_host": "127.0.0.1",
                    "actor_id": "producer_a",
                    "action": "promotion_record",
                    "target_channel": "staging",
                    "target_environment": "staging",
                    "header_name": "",
                    "scheme": "local",
                    "token_configured": False,
                    "token_present": False,
                    "token_id": "",
                    "token_source": "",
                    "session_id": "",
                    "issued_by": "",
                    "issued_at": "",
                    "session_tracked": False,
                    "identity_path": "deployment/release_identity_registry.json",
                    "identity_registry_exists": True,
                    "issuer_registered": False,
                    "issuer_status": "",
                    "issuer_subject_actor_ids": [],
                    "max_session_age_hours": 0,
                    "required_actor_ids": [],
                    "reason": "trusted local request allowed because no release write token is configured",
                },
                "plan_status": "warning",
                "distribution_status": "passed",
                "distribution_summary": "distribution bundle ready",
                "distribution_publish_receipts_status": "warning",
                "distribution_publish_receipts_summary": "publish receipts pending / completed=1 / required=2",
                "distribution_publish_receipts_manifest_path": "logs/reports/release_distribution_publish_receipts/staging/web-qa-001/publish_receipts_manifest.json",
                "distribution_publish_receipts_target_count": 2,
                "distribution_publish_receipts_completed_targets": ["qa_handoff"],
                "distribution_publish_receipts_missing_targets": ["github_release_manual"],
                "distribution_publish_receipts_follow_up_required": True,
                "release_delivery_readiness": {
                    "status": "warning",
                    "summary": "delivery readiness needs external receipts",
                    "blocking_checks": ["missing_receipt:github_release_manual"],
                    "next_actions": [
                        {
                            "action_id": "distribution_publish_receipts",
                            "status": "warning",
                            "owner_hint": "release_ops",
                            "dependency": "external publish receipt",
                            "eta": "before production promotion",
                            "validation_method": "record_release_distribution_publish_receipt",
                            "blockers": ["missing_receipt:github_release_manual"],
                        }
                    ],
                },
                "release_live_ci_status": "warning",
                "release_live_ci_path": "logs/reports/release_live_ci/release_live_ci_summary.json",
                "release_live_ci_summary": "local replay warning / portal click smoke failed",
                "release_live_ci_summary_markdown_path": "logs/reports/release_live_ci/release_live_ci_summary.md",
                "release_live_dispatch_audit": {
                    "status": "warning",
                    "summary": "workflow_dispatch accepted for sossossal/cim-comm-soc@main",
                    "path": "logs/reports/release_live_ci/release_live_dispatch.json",
                    "recorded_at": "2026-04-18T10:10:00Z",
                    "triggered_by": "release_manager",
                    "workflow": "release-live-gates.yml",
                    "repo": "sossossal/cim-comm-soc",
                    "ref": "main",
                    "target_channel": "staging",
                    "target_environment": "staging",
                    "ready": True,
                    "dispatch_attempted": True,
                    "dispatch_completed": True,
                    "wait": True,
                    "run": {
                        "id": 9001,
                        "status": "completed",
                        "conclusion": "success",
                        "html_url": "https://github.com/sossossal/cim-comm-soc/actions/runs/9001",
                    },
                    "request_auth": {
                        "status": "passed",
                        "actor_id": "release_manager",
                        "reason": "accepted",
                    },
                },
                "release_live_ci_event_stream": {
                    "status": "warning",
                    "path": "release_live_ci_events.json",
                    "summary": "events=5 / blocked=1 / warning=1 / latest=run_finished",
                    "route_kind": "local_replay",
                    "route_id": "local_replay:staging:staging",
                    "invocation_source": "local_replay",
                    "event_count": 5,
                    "blocked_event_count": 1,
                    "warning_event_count": 1,
                    "latest_event_type": "run_finished",
                    "latest_event_status": "warning",
                    "events": [
                        {
                            "event_id": "run_started_1",
                            "event_type": "run_started",
                            "scope": "run",
                            "order": 1,
                            "status": "passed",
                            "occurred_at": "2026-04-18T10:00:00Z",
                            "summary": "route=local_replay",
                        }
                    ],
                },
                "release_live_ci_event_stream_path": "release_live_ci_events.json",
                "release_live_ci_event_stream_status": "warning",
                "release_live_ci_event_count": 5,
                "release_live_ci_latest_event_type": "run_finished",
                "release_live_ci_latest_event_status": "warning",
                "release_live_ci_workflow_step_results_path": "logs/reports/release_live_ci/release_live_ci_workflow_steps.json",
                "release_live_ci_workflow_steps": [
                    {
                        "step_id": "export_runner_baseline",
                        "label": "Export runner baseline",
                        "status": "passed",
                        "outcome": "success",
                        "always_run": False,
                        "message": "",
                    },
                    {
                        "step_id": "run_full_live_validation",
                        "label": "Run full live validation",
                        "status": "warning",
                        "outcome": "failure",
                        "always_run": False,
                        "message": "portal click smoke failed",
                    },
                ],
                "release_live_ci_failed_workflow_steps": ["run_full_live_validation"],
                "release_live_ci_follow_up_required": True,
                "missing_signoffs": ["producer", "producer"],
                "plan_snapshot": {
                    "target_channel": "staging",
                    "target_environment": "staging",
                    "provided_signoffs": ["qa_lead", "tech_lead"],
                    "required_signoffs": ["qa_lead", "tech_lead", "producer"],
                    "checklist": [{"item_id": "signoff_gate", "status": "blocked", "required": True, "message": "missing producer"}],
                    "review_bundle": {
                        "feature": {"feature_id": "feature-001", "feature_status": "approved", "blockers": ["qa follow-up"]},
                        "change_summary": ["ship staging"],
                        "changed_paths": ["README.md"],
                        "acceptance_checklist": [{"label": "smoke", "status": "ready"}],
                        "required_signoffs": ["producer"],
                        "provided_signoffs": [],
                    },
                    "release_candidate_checklist": {
                        "release_summary": {"build_id": "web-qa-001", "version": "0.1.0", "channel": "qa"},
                        "quality_gate": {"passed": True, "checks": [{"name": "smoke_test", "status": "passed"}]},
                    },
                },
            }],
            "matched_count": 1,
            "total_count": 1,
            "visible_count": 1,
        })

        self.assertEqual(history["schema_version"], RELEASE_PROMOTION_HISTORY_SCHEMA_VERSION)
        self.assertEqual(history["decision_filter"], "approved")
        self.assertEqual(history["target_channel_filter"], "staging")
        self.assertEqual(history["executor_filter"], "producer_a")
        self.assertEqual(history["live_ci_status_filter"], "warning")
        self.assertEqual(history["dispatch_status_filter"], "warning")
        self.assertEqual(history["dispatch_follow_up_filter"], "clear")
        self.assertEqual(history["dispatch_run_status_filter"], "completed")
        self.assertEqual(history["dispatch_run_conclusion_filter"], "success")
        self.assertEqual(history["failed_workflow_step_filter"], "run_full_live_validation")
        self.assertEqual(history["delivery_readiness_status_filter"], "warning")
        self.assertEqual(history["readiness_action_filter"], "distribution_publish_receipts")
        self.assertEqual(history["decision_counts"]["approved"], 1)
        self.assertEqual(history["latest_record"]["record_id"], "promotion_001")
        self.assertEqual(history["latest_record"]["missing_signoffs"], ["producer"])
        self.assertIn("feature_blockers", [item["action_id"] for item in history["latest_record"]["review_followup_actions"]])
        self.assertIn("signoffs", [item["action_id"] for item in history["latest_record"]["review_followup_actions"]])
        self.assertIn("signoff_producer", [item["action_id"] for item in history["latest_record"]["review_followup_actions"]])
        self.assertEqual(history["latest_record"]["review_followup_action_count"], 3)
        self.assertEqual(history["latest_record"]["authorization"]["status"], "passed")
        self.assertEqual(history["latest_record"]["request_auth"]["auth_path"], "deployment/release_request_auth.json")
        self.assertEqual(history["latest_record"]["request_auth"]["mode"], "local_only")
        self.assertEqual(history["latest_record"]["request_auth"]["identity_path"], "deployment/release_identity_registry.json")
        self.assertEqual(history["latest_record"]["distribution_status"], "passed")
        self.assertEqual(history["latest_record"]["distribution_publish_receipts_status"], "warning")
        self.assertEqual(history["latest_record"]["distribution_publish_receipts_completed_targets"], ["qa_handoff"])
        self.assertEqual(history["latest_record"]["distribution_publish_receipts_missing_targets"], ["github_release_manual"])
        self.assertTrue(history["latest_record"]["distribution_publish_receipts_follow_up_required"])
        self.assertEqual(history["latest_record"]["release_delivery_readiness_status"], "warning")
        self.assertEqual(history["latest_record"]["release_delivery_readiness_summary"], "delivery readiness needs external receipts")
        self.assertEqual(history["latest_record"]["release_delivery_readiness_next_action_count"], 1)
        self.assertEqual(
            history["latest_record"]["release_delivery_readiness_next_actions"][0]["action_id"],
            "distribution_publish_receipts",
        )
        self.assertEqual(
            history["latest_record"]["release_delivery_readiness_blocking_checks"],
            ["missing_receipt:github_release_manual"],
        )
        self.assertEqual(history["latest_record"]["release_live_ci_status"], "warning")
        self.assertEqual(history["latest_record"]["release_live_ci_path"], "logs/reports/release_live_ci/release_live_ci_summary.json")
        self.assertEqual(history["latest_record"]["release_live_ci_summary"], "local replay warning / portal click smoke failed")
        self.assertEqual(history["latest_record"]["release_live_dispatch_status"], "warning")
        self.assertEqual(history["latest_record"]["release_live_dispatch_path"], "logs/reports/release_live_ci/release_live_dispatch.json")
        self.assertEqual(history["latest_record"]["release_live_dispatch_run_status"], "completed")
        self.assertEqual(history["latest_record"]["release_live_ci_event_stream"]["path"], "release_live_ci_events.json")
        self.assertEqual(history["latest_record"]["release_live_ci_event_stream_status"], "warning")
        self.assertEqual(history["latest_record"]["release_live_ci_event_count"], 5)
        self.assertEqual(history["latest_record"]["release_live_ci_latest_event_type"], "run_finished")
        self.assertEqual(
            history["latest_record"]["release_live_ci_workflow_step_results_path"],
            "logs/reports/release_live_ci/release_live_ci_workflow_steps.json",
        )
        self.assertEqual(
            history["latest_record"]["release_live_ci_workflow_steps"][1]["step_id"],
            "run_full_live_validation",
        )
        self.assertEqual(history["latest_record"]["release_live_ci_failed_workflow_steps"], ["run_full_live_validation"])
        self.assertTrue(history["latest_record"]["release_live_ci_follow_up_required"])
        self.assertEqual(history["items"][0]["plan_snapshot"]["schema_version"], RELEASE_PROMOTION_PLAN_SCHEMA_VERSION)
        self.assertEqual(history["items"][0]["plan_snapshot"]["missing_signoffs"], ["producer"])
        self.assertEqual(history["items"][0]["release_build_id"], "web-qa-001")

    def test_release_execution_status_normalizes_executions_and_channels(self):
        status = normalize_release_execution_status({
            "project_root": "D:/repo",
            "runtime_root": "D:/repo",
            "status_path": "deployment/release_execution_status.json",
            "channels_path": "deployment/release_channels.json",
            "history_path": "deployment/release_promotion_history.json",
            "operation_filter": "canary",
            "target_channel_filter": "staging",
            "executor_filter": "release_manager",
            "items": [{
                "execution_id": "exec_001",
                "recorded_at": "2026-04-14T10:00:00Z",
                "operation": "canary",
                "target_channel": "staging",
                "target_environment": "staging",
                "promotion_target_label": "staging -> staging",
                "execution_status": "warning",
                "should_block": False,
                "executed_by": "release_manager",
                "note": "canary",
                "rollout_stage": "canary",
                "rollout_percentage": "15",
                "channel_binding_changed": True,
                "authorization": {
                    "status": "passed",
                    "required": True,
                    "policy_path": "deployment/release_access_policy.json",
                    "policy_source": "manifest",
                    "actor_id": "release_manager",
                    "actor_roles": ["release_manager"],
                    "action": "release_execution",
                    "target_channel": "staging",
                    "operation": "canary",
                    "matched_rule_id": "execution_rollout_qa_staging",
                    "required_roles": ["producer", "ops", "release_manager"],
                    "reason": "actor release_manager authorized for release_execution",
                },
                "request_auth": {
                    "status": "passed",
                    "required": True,
                    "auth_path": "deployment/release_request_auth.json",
                    "mode": "token",
                    "client_host": "10.0.0.8",
                    "actor_id": "release_manager",
                    "action": "release_execution",
                    "target_channel": "staging",
                    "target_environment": "staging",
                    "header_name": "authorization",
                    "scheme": "bearer",
                    "token_configured": True,
                    "token_present": True,
                    "token_id": "staging_release_manager",
                    "token_source": "manifest",
                    "session_id": "staging-session-001",
                    "issued_by": "ops_a",
                    "issued_at": "2026-04-15T00:00:00Z",
                    "session_tracked": True,
                    "identity_path": "deployment/release_identity_registry.json",
                    "identity_registry_exists": True,
                    "issuer_registered": True,
                    "issuer_status": "active",
                    "issuer_subject_actor_ids": ["producer_a", "release_manager", "ops_a"],
                    "max_session_age_hours": 0,
                    "required_actor_ids": ["release_manager"],
                    "reason": "release write token accepted",
                },
                "release_manifest_path": "api_server/static/dist/release_manifest.json",
                "release_build_id": "web-staging-001",
                "release_version": "0.1.0-staging+1",
                "release_channel": "staging",
                "public_url": "/portal/dist/web_20260413/index.html",
                "versioned_release_url": "/portal/dist/web_20260413/index.html",
                "rollback_url": "/portal/dist/index.html",
                "promotion_record_id": "promotion_001",
                "promotion_decision": "approved",
                "checklist": [{"item_id": "rollout_target", "status": "passed", "required": True, "message": "ok"}],
                "plan_snapshot": {
                    "target_channel": "staging",
                    "target_environment": "staging",
                    "required_signoffs": ["qa_lead", "tech_lead", "producer"],
                    "provided_signoffs": ["qa_lead", "tech_lead", "producer"],
                    "checklist": [{"item_id": "release_candidate_gate", "status": "passed", "required": True, "message": "ok"}],
                    "release_candidate_checklist": {
                        "release_summary": {"build_id": "web-staging-001", "version": "0.1.0-staging+1", "channel": "staging"},
                        "quality_gate": {"passed": True, "checks": [{"name": "smoke_test", "status": "passed"}]},
                    },
                    "review_bundle": {
                        "feature": {
                            "feature_id": "feature-001",
                            "feature_status": "approved",
                            "blockers": ["qa follow-up"],
                        },
                        "change_summary": ["ship canary"],
                        "changed_paths": ["README.md"],
                        "acceptance_checklist": [{"label": "smoke", "status": "ready"}],
                        "required_signoffs": ["qa_lead"],
                        "provided_signoffs": [],
                    },
                    "release_delivery_readiness": {
                        "status": "warning",
                        "summary": "execution readiness needs receipts",
                        "blocking_checks": ["missing_receipt:github_release_manual"],
                        "next_actions": [
                            {
                                "action_id": "distribution_publish_receipts",
                                "status": "warning",
                                "owner_hint": "release_ops",
                                "dependency": "external publish receipt",
                                "validation_method": "record_release_distribution_publish_receipt",
                                "blockers": ["missing_receipt:github_release_manual"],
                            }
                        ],
                    },
                },
            }],
            "channel_entries": [{
                "channel_id": "staging",
                "target_environment": "staging",
                "binding_status": "warning",
                "rollout_stage": "canary",
                "rollout_percentage": "15",
                "active_release_manifest_path": "api_server/static/dist/release_manifest.json",
                "active_build_id": "web-staging-001",
                "active_version": "0.1.0-staging+1",
                "active_release_channel": "staging",
                "active_public_url": "/portal/dist/web_20260413/index.html",
                "rollback_public_url": "/portal/dist/index.html",
                "executed_by": "release_manager",
            }],
            "execution_count": 1,
            "matched_execution_count": 1,
            "visible_execution_count": 1,
            "channel_count": 1,
            "active_channel_count": 1,
            "clean_machine_bootstrap": {
                "status": "passed",
                "path": "logs/reports/clean_machine_bootstrap.json",
                "summary": "ok=True / preview=False / steps=4 / blocking_issues=0",
                "details": {
                    "ok": True,
                    "preview": False,
                    "step_count": 4,
                    "blocking_issue_count": 0,
                    "blocking_issue_codes": [],
                    "doctor_report_path": "logs/reports/doctor_self_check.json",
                    "doctor_report_exists": True,
                    "doctor_ok": True,
                    "doctor_summary": "checks=6 / passed=6 / failed=0 / action_items=0",
                    "doctor_check_count": 6,
                    "doctor_failed_check_count": 0,
                    "doctor_action_item_count": 0,
                    "doctor_blocking_checks": [],
                    "step_statuses": [
                        {"id": "create_venv", "status": "passed"},
                        {"id": "doctor", "status": "passed"},
                    ],
                },
            },
            "release_live_runner_baseline": {
                "status": "passed",
                "path": "logs/reports/release_live_runner_baseline_staging.json",
                "summary": "checks=10 / passed=10 / warning=0 / blocked=0",
                "details": {
                    "target_channel": "staging",
                    "target_environment": "staging",
                    "report_path": "logs/reports/release_live_runner_baseline_staging.json",
                    "runner_profile_path": "deployment/release_live_runner_profile.json",
                    "runner_profile_id": "release_windows_runner",
                    "runner_name": "godot-release-01",
                    "runner_os": "Windows",
                    "runner_arch": "x64",
                    "declared_runner_labels": ["self-hosted", "windows", "godot"],
                    "github_actions": True,
                    "github_workflow": "release-live-gates",
                    "github_job": "live-release-gates",
                    "github_run_id": "1234567890",
                    "github_run_attempt": "1",
                    "python_version": "3.12.10",
                    "required_runner_os": "Windows",
                    "required_runner_arches": ["x64"],
                    "required_runner_labels": ["self-hosted", "windows", "godot"],
                    "allowed_runner_names": ["godot-release-01"],
                    "check_count": 10,
                    "passed_check_count": 10,
                    "warning_check_count": 0,
                    "blocked_check_count": 0,
                    "blocking_checks": [],
                    "warning_checks": [],
                    "checks": [
                        {
                            "check_id": "chromium_browser",
                            "label": "Chromium Browser",
                            "status": "passed",
                            "required": True,
                            "message": "detected via chrome",
                        }
                    ],
                    "recommendations": [],
                    "powershell_executable": "powershell",
                    "godot_executable": "C:/Godot/godot.exe",
                    "browser_executable": "C:/Program Files/Google/Chrome/Application/chrome.exe",
                },
            },
            "full_live_validation": {
                "status": "passed",
                "path": "logs/reports/full_live_validation.json",
                "summary": "ok=True / lanes=4 / passed=4 / warning=0 / blocked=0 / binding=passed",
                "details": {
                    "ok": True,
                    "executed_at": "2026-04-14T11:00:00Z",
                    "lane_count": 4,
                    "passed_lane_count": 4,
                    "warning_lane_count": 0,
                    "blocked_lane_count": 0,
                    "blocking_issue_count": 0,
                    "blocking_issue_codes": [],
                    "report_release_binding_status": "passed",
                    "report_release_manifest_source": "stable",
                    "report_release_build_id": "web-staging-001",
                    "report_release_version": "0.1.0-staging+1",
                    "report_release_channel": "staging",
                    "report_release_manifest_path": "api_server/static/dist/release_manifest.json",
                    "report_release_dir": "api_server/static/dist/web_20260413",
                    "report_output_path": "api_server/static/dist/web_20260413/index.html",
                    "report_release_url": "/portal/dist/index.html",
                    "report_versioned_release_url": "/portal/dist/web_20260413/index.html",
                    "release_build_id": "web-staging-001",
                    "release_version": "0.1.0-staging+1",
                    "release_channel": "staging",
                    "release_manifest_path": "api_server/static/dist/release_manifest.json",
                    "release_binding_status": "passed",
                    "release_binding_mismatches": [],
                    "step_statuses": [
                        {
                            "id": "godot_live_sandbox",
                            "label": "Godot Live Sandbox",
                            "status": "passed",
                            "summary": "sandbox ok",
                            "artifact_paths": ["logs/live_sandbox_state.json", "logs/api_server_8000.out"],
                            "report_path": "logs/reports/full_live_validation_lanes/godot_live_sandbox.json",
                        },
                        {
                            "id": "portal_dom_smoke",
                            "label": "Portal DOM Smoke",
                            "status": "passed",
                            "summary": "dom ok",
                            "artifact_paths": ["logs/test_artifacts/portal_browser_smoke_8012.html"],
                            "report_path": "logs/reports/full_live_validation_lanes/portal_dom_smoke.json",
                        },
                        {
                            "id": "portal_click_smoke",
                            "label": "Portal Click Smoke",
                            "status": "passed",
                            "summary": "click ok",
                            "artifact_paths": ["logs/test_artifacts/portal_click_chrome_8014.out"],
                            "report_path": "logs/reports/full_live_validation_lanes/portal_click_smoke.json",
                            "flow_statuses": {
                                "flow": "passed",
                                "release_promotion_history_flow": "passed",
                                "release_promotion_history_report_flow": "passed",
                            },
                        },
                    ],
                    "lane_artifact_count": 3,
                    "lane_artifacts": [
                        {
                            "lane_id": "godot_live_sandbox",
                            "label": "Godot Live Sandbox",
                            "status": "passed",
                            "summary": "sandbox ok",
                            "executed_at": "2026-04-14T11:00:00Z",
                            "report_path": "logs/reports/full_live_validation_lanes/godot_live_sandbox.json",
                            "artifact_paths": ["logs/live_sandbox_state.json", "logs/api_server_8000.out"],
                            "build_id": "web-staging-001",
                            "version": "0.1.0-staging+1",
                            "channel": "staging",
                            "release_manifest_path": "api_server/static/dist/release_manifest.json",
                            "release_url": "/portal/dist/index.html",
                            "versioned_release_url": "/portal/dist/web_20260413/index.html",
                            "release_binding_status": "passed",
                            "release_binding_mismatches": [],
                        },
                        {
                            "lane_id": "portal_dom_smoke",
                            "label": "Portal DOM Smoke",
                            "status": "passed",
                            "summary": "dom ok",
                            "executed_at": "2026-04-14T11:00:00Z",
                            "report_path": "logs/reports/full_live_validation_lanes/portal_dom_smoke.json",
                            "artifact_paths": ["logs/test_artifacts/portal_browser_smoke_8012.html"],
                            "build_id": "web-staging-001",
                            "version": "0.1.0-staging+1",
                            "channel": "staging",
                            "release_manifest_path": "api_server/static/dist/release_manifest.json",
                            "release_url": "/portal/dist/index.html",
                            "versioned_release_url": "/portal/dist/web_20260413/index.html",
                            "release_binding_status": "passed",
                            "release_binding_mismatches": [],
                        },
                        {
                            "lane_id": "portal_click_smoke",
                            "label": "Portal Click Smoke",
                            "status": "passed",
                            "summary": "click ok",
                            "executed_at": "2026-04-14T11:00:00Z",
                            "report_path": "logs/reports/full_live_validation_lanes/portal_click_smoke.json",
                            "artifact_paths": ["logs/test_artifacts/portal_click_chrome_8014.out"],
                            "build_id": "web-staging-001",
                            "version": "0.1.0-staging+1",
                            "channel": "staging",
                            "release_manifest_path": "api_server/static/dist/release_manifest.json",
                            "release_url": "/portal/dist/index.html",
                            "versioned_release_url": "/portal/dist/web_20260413/index.html",
                            "release_binding_status": "passed",
                            "release_binding_mismatches": [],
                            "flow_statuses": {
                                "flow": "passed",
                                "release_promotion_history_flow": "passed",
                                "release_promotion_history_report_flow": "passed",
                            },
                        },
                    ],
                },
            },
            "release_live_runner_baseline": {
                "status": "passed",
                "path": "logs/reports/release_live_runner_baseline_staging.json",
                "summary": "checks=10 / passed=10 / warning=0 / blocked=0",
                "details": {
                    "target_channel": "staging",
                    "target_environment": "staging",
                    "report_path": "logs/reports/release_live_runner_baseline_staging.json",
                    "runner_profile_path": "deployment/release_live_runner_profile.json",
                    "runner_profile_id": "release_windows_runner",
                    "runner_name": "godot-release-01",
                    "runner_os": "Windows",
                    "runner_arch": "x64",
                    "declared_runner_labels": ["self-hosted", "windows", "godot"],
                    "github_actions": True,
                    "github_workflow": "release-live-gates",
                    "github_job": "live-release-gates",
                    "github_run_id": "1234567890",
                    "github_run_attempt": "1",
                    "python_version": "3.12.10",
                    "required_runner_os": "Windows",
                    "required_runner_arches": ["x64"],
                    "required_runner_labels": ["self-hosted", "windows", "godot"],
                    "allowed_runner_names": ["godot-release-01"],
                    "check_count": 10,
                    "passed_check_count": 10,
                    "warning_check_count": 0,
                    "blocked_check_count": 0,
                    "blocking_checks": [],
                    "warning_checks": [],
                    "checks": [
                        {
                            "check_id": "chromium_browser",
                            "label": "Chromium Browser",
                            "status": "passed",
                            "required": True,
                            "message": "detected via chrome",
                        }
                    ],
                    "recommendations": [],
                    "powershell_executable": "powershell",
                    "godot_executable": "C:/Godot/godot.exe",
                    "browser_executable": "C:/Program Files/Google/Chrome/Application/chrome.exe",
                },
            },
            "request_auth_posture": {
                "schema_version": "1.0",
                "status": "passed",
                "path": "deployment/release_request_auth.json",
                "manifest_path": "deployment/release_request_auth.json",
                "report_path": "logs/reports/release_request_auth_posture_release_execution_staging.json",
                "report_exists": True,
                "manifest_exists": True,
                "identity_registry_path": "deployment/release_identity_registry.json",
                "identity_registry_exists": True,
                "identity_boundary_path": "deployment/release_identity_boundary.json",
                "identity_boundary_exists": True,
                "identity_boundary_profile_id": "staging_identity_boundary",
                "identity_boundary_status": "passed",
                "identity_boundary_summary": "profile=staging_identity_boundary / provider=passed / session=passed / secret_rotation=passed",
                "identity_provider_mode": "project_manifest",
                "identity_provider_id": "release_request_auth_manifest",
                "identity_provider_status": "passed",
                "identity_session_policy_status": "passed",
                "identity_session_required": True,
                "identity_max_session_age_hours": 48,
                "identity_session_backend": "identity_registry",
                "identity_secret_rotation_status": "passed",
                "identity_secret_rotation_required": True,
                "identity_secret_backend": "deployment_manifest",
                "identity_rotation_owner": "ops_release",
                "identity_rotation_window_days": 30,
                "action": "release_execution",
                "target_channel": "staging",
                "target_environment": "staging",
                "summary": "matching manifest tokens are actor-bound and local bypass is disabled",
                "allow_local_without_token": False,
                "env_fallback_configured": False,
                "rotation_window_days": 30,
                "token_count": 1,
                "active_token_count": 1,
                "matching_token_count": 1,
                "matching_bound_token_count": 1,
                "matching_unbound_token_count": 0,
                "matching_session_token_count": 1,
                "issuer_count": 1,
                "active_issuer_count": 1,
                "matching_registered_issuer_token_count": 1,
                "matching_unknown_issuer_token_count": 0,
                "matching_inactive_issuer_token_count": 0,
                "matching_unscoped_issuer_token_count": 0,
                "matching_subject_out_of_registry_count": 0,
                "matching_stale_session_token_count": 0,
                "revoked_token_count": 0,
                "expired_token_count": 0,
                "invalid_expiry_token_count": 0,
                "invalid_issued_at_token_count": 0,
                "tokens_without_expiry_count": 0,
                "tokens_expiring_soon_count": 0,
                "tokens_without_session_id_count": 0,
                "tokens_without_issued_by_count": 0,
                "tokens_without_issued_at_count": 0,
                "duplicate_token_id_count": 0,
                "matching_token_ids": ["staging_release_manager"],
                "duplicate_token_ids": [],
                "notes": ["matching tokens=staging_release_manager"],
                "recommendations": [],
            },
            "request_auth_rotation_audit": {
                "schema_version": "1.0",
                "status": "passed",
                "summary": "actions=2 / passed=2 / warning=0 / blocked=0",
                "auth_path": "deployment/release_request_auth.json",
                "manifest_exists": True,
                "target_channel": "staging",
                "target_environment": "staging",
                "actions": ["promotion_record", "release_execution"],
                "action_count": 2,
                "passed_action_count": 2,
                "warning_action_count": 0,
                "blocked_action_count": 0,
                "report_path": "logs/reports/release_request_auth_rotation_audit_staging.json",
                "report_exists": True,
                "coverage": [
                    {
                        "schema_version": "1.0",
                        "status": "passed",
                        "path": "deployment/release_request_auth.json",
                        "manifest_path": "deployment/release_request_auth.json",
                        "report_path": "logs/reports/release_request_auth_posture_release_execution_staging.json",
                        "report_exists": True,
                        "manifest_exists": True,
                        "identity_registry_path": "deployment/release_identity_registry.json",
                        "identity_registry_exists": True,
                        "action": "release_execution",
                        "target_channel": "staging",
                        "target_environment": "staging",
                        "summary": "matching manifest tokens are actor-bound and local bypass is disabled",
                        "allow_local_without_token": False,
                        "env_fallback_configured": False,
                        "rotation_window_days": 30,
                        "token_count": 1,
                        "active_token_count": 1,
                        "matching_token_count": 1,
                        "matching_bound_token_count": 1,
                        "matching_unbound_token_count": 0,
                        "matching_session_token_count": 1,
                        "issuer_count": 1,
                        "active_issuer_count": 1,
                        "matching_registered_issuer_token_count": 1,
                        "matching_unknown_issuer_token_count": 0,
                        "matching_inactive_issuer_token_count": 0,
                        "matching_unscoped_issuer_token_count": 0,
                        "matching_subject_out_of_registry_count": 0,
                        "matching_stale_session_token_count": 0,
                        "revoked_token_count": 0,
                        "expired_token_count": 0,
                        "invalid_expiry_token_count": 0,
                        "invalid_issued_at_token_count": 0,
                        "tokens_without_expiry_count": 0,
                        "tokens_expiring_soon_count": 0,
                        "tokens_without_session_id_count": 0,
                        "tokens_without_issued_by_count": 0,
                        "tokens_without_issued_at_count": 0,
                        "duplicate_token_id_count": 0,
                        "matching_token_ids": ["staging_release_manager"],
                        "duplicate_token_ids": [],
                        "notes": ["matching tokens=staging_release_manager"],
                        "recommendations": [],
                    }
                ],
                "notes": ["release_execution: matching manifest tokens are actor-bound and local bypass is disabled"],
                "recommendations": [],
            },
            "request_auth_identity_audit": {
                "schema_version": "1.0",
                "status": "passed",
                "summary": "actions=2 / passed=2 / warning=0 / blocked=0 / scoped_issuers=1",
                "auth_path": "deployment/release_request_auth.json",
                "manifest_exists": True,
                "identity_path": "deployment/release_identity_registry.json",
                "identity_registry_exists": True,
                "target_channel": "staging",
                "target_environment": "staging",
                "actions": ["promotion_record", "release_execution"],
                "action_count": 2,
                "passed_action_count": 2,
                "warning_action_count": 0,
                "blocked_action_count": 0,
                "issuer_count": 1,
                "active_issuer_count": 1,
                "scoped_issuer_count": 1,
                "session_required_issuer_count": 1,
                "session_windowed_issuer_count": 0,
                "unbound_issuer_count": 0,
                "duplicate_issuer_id_count": 0,
                "duplicate_issuer_ids": [],
                "matching_registered_issuer_token_count": 2,
                "matching_unknown_issuer_token_count": 0,
                "matching_inactive_issuer_token_count": 0,
                "matching_unscoped_issuer_token_count": 0,
                "matching_subject_out_of_registry_count": 0,
                "matching_stale_session_token_count": 0,
                "matching_session_token_count": 2,
                "release_issuers_without_session_requirement_count": 0,
                "release_issuers_without_session_window_count": 0,
                "report_path": "logs/reports/release_request_auth_identity_audit_staging.json",
                "report_exists": True,
                "coverage": [
                    {
                        "schema_version": "1.0",
                        "status": "passed",
                        "path": "deployment/release_request_auth.json",
                        "manifest_path": "deployment/release_request_auth.json",
                        "report_path": "logs/reports/release_request_auth_posture_release_execution_staging.json",
                        "report_exists": True,
                        "manifest_exists": True,
                        "identity_registry_path": "deployment/release_identity_registry.json",
                        "identity_registry_exists": True,
                        "action": "release_execution",
                        "target_channel": "staging",
                        "target_environment": "staging",
                        "summary": "matching manifest tokens are actor-bound and local bypass is disabled",
                        "allow_local_without_token": False,
                        "env_fallback_configured": False,
                        "rotation_window_days": 30,
                        "token_count": 1,
                        "active_token_count": 1,
                        "matching_token_count": 1,
                        "matching_bound_token_count": 1,
                        "matching_unbound_token_count": 0,
                        "matching_session_token_count": 1,
                        "issuer_count": 1,
                        "active_issuer_count": 1,
                        "matching_registered_issuer_token_count": 1,
                        "matching_unknown_issuer_token_count": 0,
                        "matching_inactive_issuer_token_count": 0,
                        "matching_unscoped_issuer_token_count": 0,
                        "matching_subject_out_of_registry_count": 0,
                        "matching_stale_session_token_count": 0,
                        "revoked_token_count": 0,
                        "expired_token_count": 0,
                        "invalid_expiry_token_count": 0,
                        "invalid_issued_at_token_count": 0,
                        "tokens_without_expiry_count": 0,
                        "tokens_expiring_soon_count": 0,
                        "tokens_without_session_id_count": 0,
                        "tokens_without_issued_by_count": 0,
                        "tokens_without_issued_at_count": 0,
                        "duplicate_token_id_count": 0,
                        "matching_token_ids": ["staging_release_manager"],
                        "duplicate_token_ids": [],
                        "notes": ["matching tokens=staging_release_manager"],
                        "recommendations": [],
                    }
                ],
                "notes": ["release_execution=passed"],
                "recommendations": [],
            },
            "release_distribution_bundle": {
                "schema_version": "1.0",
                "status": "passed",
                "summary": "source=ready / bundle=ready / payload_files=4 / bundle_files=9",
                "target_channel": "staging",
                "target_environment": "staging",
                "build_id": "web-staging-001",
                "version": "0.1.0-staging+1",
                "release_channel": "staging",
                "release_manifest_path": "api_server/static/dist/release_manifest.json",
                "release_manifest_source": "stable",
                "release_notes_path": "api_server/static/dist/web_20260413/release_notes.md",
                "qa_gate_report_path": "api_server/static/dist/web_20260413/qa_gate_report.md",
                "build_log_path": "api_server/static/dist/web_20260413/build.log",
                "release_dir": "api_server/static/dist/web_20260413",
                "output_path": "api_server/static/dist/web_20260413/index.html",
                "release_url": "/portal/dist/index.html",
                "versioned_release_url": "/portal/dist/web_20260413/index.html",
                "bundle_root": "logs/reports/release_distribution",
                "bundle_dir": "logs/reports/release_distribution/staging/web-staging-001",
                "bundle_exists": True,
                "bundle_file_count": 9,
                "payload_dir": "logs/reports/release_distribution/staging/web-staging-001/release_payload",
                "payload_exists": True,
                "payload_file_count": 4,
                "distribution_manifest_path": "logs/reports/release_distribution/staging/web-staging-001/distribution_manifest.json",
                "distribution_manifest_exists": True,
                "install_script_path": "logs/reports/release_distribution/staging/web-staging-001/install_release_bundle.ps1",
                "install_script_exists": True,
                "upgrade_script_path": "logs/reports/release_distribution/staging/web-staging-001/upgrade_release_bundle.ps1",
                "upgrade_script_exists": True,
                "uninstall_script_path": "logs/reports/release_distribution/staging/web-staging-001/uninstall_release_bundle.ps1",
                "uninstall_script_exists": True,
                "support_matrix_source_path": "docs/支持矩阵与分发说明.md",
                "support_matrix_path": "logs/reports/release_distribution/staging/web-staging-001/support_matrix.md",
                "support_matrix_exists": True,
                "bootstrap_script_source_path": "tools/bootstrap_clean_machine.ps1",
                "bundle_manifest_copy_path": "logs/reports/release_distribution/staging/web-staging-001/release_manifest.json",
                "bundle_manifest_copy_exists": True,
                "bundle_release_notes_path": "logs/reports/release_distribution/staging/web-staging-001/release_notes.md",
                "bundle_release_notes_exists": True,
                "bundle_qa_gate_report_path": "logs/reports/release_distribution/staging/web-staging-001/qa_gate_report.md",
                "bundle_qa_gate_report_exists": True,
                "state_manifest_path": "logs/reports/release_distribution/staging/web-staging-001/installed_release.example.json",
                "state_manifest_exists": True,
                "report_path": "logs/reports/release_distribution_bundle_staging.json",
                "report_exists": True,
                "install_smoke_report_path": "logs/reports/release_distribution_install_smoke_staging.json",
                "install_smoke_report_exists": True,
                "install_smoke_status": "passed",
                "install_smoke_summary": "steps=3 / passed=3 / failed=0 / backups=1",
                "install_smoke_target_root": "logs/reports/release_distribution_smoke/staging/web-staging-001/installed_release",
                "install_smoke_state_path": "logs/reports/release_distribution_smoke/staging/web-staging-001/installed_release/.release_bundle/installed_release.json",
                "install_smoke_backup_count": 1,
                "install_smoke_marker_preserved": True,
                "install_smoke_current_exists": False,
                "install_smoke_state_written": False,
                "install_smoke_state_removed": True,
                "install_smoke_installed_build_id": "web-staging-001",
                "install_smoke_installed_version": "0.1.0-staging+1",
                "install_smoke_previous_build_id": "web-staging-001",
                "install_smoke_backup_dir": "logs/reports/release_distribution_smoke/staging/web-staging-001/installed_release/backups/web-staging-001_20260416T101500Z",
                "install_smoke_removed_build_id": "web-staging-001",
                "install_smoke_removed_version": "0.1.0-staging+1",
                "archive_dir": "logs/reports/release_distribution_packages/staging/web-staging-001",
                "archive_exists": True,
                "archive_path": "logs/reports/release_distribution_packages/staging/web-staging-001/release_distribution_bundle.zip",
                "archive_file_exists": True,
                "archive_sha256_path": "logs/reports/release_distribution_packages/staging/web-staging-001/release_distribution_bundle.sha256",
                "archive_sha256_exists": True,
                "archive_size_bytes": 2048,
                "archive_status": "passed",
                "archive_summary": "archive ready / size=2048 bytes / sha256=yes",
                "channel_index_dir": "logs/reports/release_distribution_channels/staging",
                "channel_index_exists": True,
                "channel_index_report_path": "logs/reports/release_distribution_channel_staging.json",
                "channel_index_report_exists": True,
                "channel_index_latest_path": "logs/reports/release_distribution_channels/staging/latest.json",
                "channel_index_latest_exists": True,
                "channel_index_releases_path": "logs/reports/release_distribution_channels/staging/releases.json",
                "channel_index_releases_exists": True,
                "channel_index_release_count": 1,
                "channel_index_latest_build_id": "web-staging-001",
                "channel_index_latest_matches_current": True,
                "channel_index_status": "passed",
                "channel_index_summary": "channel index ready / releases=1 / latest=web-staging-001",
                "handoff_dir": "logs/reports/release_distribution_handoff/staging/web-staging-001",
                "handoff_exists": True,
                "handoff_file_count": 8,
                "handoff_manifest_path": "logs/reports/release_distribution_handoff/staging/web-staging-001/distribution_handoff_manifest.json",
                "handoff_manifest_exists": True,
                "handoff_install_script_path": "logs/reports/release_distribution_handoff/staging/web-staging-001/install_release_handoff.ps1",
                "handoff_install_script_exists": True,
                "handoff_upgrade_script_path": "logs/reports/release_distribution_handoff/staging/web-staging-001/upgrade_release_handoff.ps1",
                "handoff_upgrade_script_exists": True,
                "handoff_uninstall_script_path": "logs/reports/release_distribution_handoff/staging/web-staging-001/uninstall_release_handoff.ps1",
                "handoff_uninstall_script_exists": True,
                "handoff_archive_path": "logs/reports/release_distribution_handoff/staging/web-staging-001/packages/release_distribution_bundle.zip",
                "handoff_archive_exists": True,
                "handoff_archive_sha256_path": "logs/reports/release_distribution_handoff/staging/web-staging-001/packages/release_distribution_bundle.sha256",
                "handoff_archive_sha256_exists": True,
                "handoff_channel_latest_path": "logs/reports/release_distribution_handoff/staging/web-staging-001/channel/latest.json",
                "handoff_channel_latest_exists": True,
                "handoff_channel_releases_path": "logs/reports/release_distribution_handoff/staging/web-staging-001/channel/releases.json",
                "handoff_channel_releases_exists": True,
                "handoff_status": "passed",
                "handoff_summary": "distribution handoff ready / files=8",
                "signing_handoff_dir": "logs/reports/release_distribution_signing/staging/web-staging-001",
                "signing_handoff_exists": False,
                "signing_handoff_file_count": 0,
                "signing_handoff_manifest_path": "logs/reports/release_distribution_signing/staging/web-staging-001/distribution_signing_manifest.json",
                "signing_handoff_manifest_exists": False,
                "signing_handoff_instructions_path": "logs/reports/release_distribution_signing/staging/web-staging-001/SIGNING_INSTRUCTIONS.md",
                "signing_handoff_instructions_exists": False,
                "signing_handoff_unsigned_archive_path": "logs/reports/release_distribution_signing/staging/web-staging-001/unsigned/release_distribution_bundle.zip",
                "signing_handoff_unsigned_archive_exists": False,
                "signing_handoff_unsigned_archive_sha256_path": "logs/reports/release_distribution_signing/staging/web-staging-001/unsigned/release_distribution_bundle.sha256",
                "signing_handoff_unsigned_archive_sha256_exists": False,
                "signing_handoff_status": "skipped",
                "signing_handoff_summary": "external signing handoff not required",
                "source_missing_items": [],
                "bundle_missing_items": [],
                "handoff_missing_items": [],
                "signing_handoff_missing_items": [],
                "delivery_manifest_path": "deployment/release_distribution_delivery.json",
                "delivery_manifest_exists": True,
                "delivery_profile_id": "staging_internal_windows",
                "delivery_status": "passed",
                "delivery_summary": "profile=staging_internal_windows / installer=passed / signing=passed / publish=passed",
                "delivery_primary_installer": "portable_handoff",
                "delivery_installer_types": ["portable_handoff", "archive_zip"],
                "delivery_installer_status": "passed",
                "delivery_signing_required": False,
                "delivery_signing_mode": "sha256_only",
                "delivery_signing_profile_id": "",
                "delivery_signing_status": "passed",
                "delivery_publish_targets": ["staging_ci_artifact"],
                "delivery_publish_target_count": 1,
                "delivery_publish_status": "passed",
                "delivery_first_run_bootstrap": "doctor_self_check",
                "delivery_upgrade_strategy": "in_place_backup",
                "delivery_uninstall_strategy": "scripted_cleanup",
                "exported_files": [
                    "logs/reports/release_distribution/staging/web-staging-001/distribution_manifest.json",
                    "logs/reports/release_distribution/staging/web-staging-001/install_release_bundle.ps1",
                ],
                "notes": ["bundle_dir=logs/reports/release_distribution/staging/web-staging-001"],
                "recommendations": [],
            },
        })

        self.assertEqual(status["schema_version"], RELEASE_EXECUTION_STATUS_SCHEMA_VERSION)
        self.assertEqual(status["operation_filter"], "canary")
        self.assertEqual(status["target_channel_filter"], "staging")
        self.assertEqual(status["executor_filter"], "release_manager")
        self.assertEqual(status["latest_execution"]["execution_id"], "exec_001")
        self.assertEqual(status["latest_execution"]["rollout_percentage"], 15)
        self.assertEqual(status["latest_execution"]["plan_snapshot"]["schema_version"], RELEASE_PROMOTION_PLAN_SCHEMA_VERSION)
        review_followup_action_ids = [item["action_id"] for item in status["review_followup_actions"]]
        self.assertIn("feature_blockers", review_followup_action_ids)
        self.assertIn("signoffs", review_followup_action_ids)
        self.assertIn("signoff_qa_lead", review_followup_action_ids)
        self.assertEqual(status["review_followup_action_count"], 3)
        self.assertEqual(status["latest_execution"]["authorization"]["status"], "passed")
        self.assertEqual(status["latest_execution"]["request_auth"]["scheme"], "bearer")
        self.assertEqual(status["latest_execution"]["request_auth"]["token_source"], "manifest")
        self.assertEqual(status["latest_execution"]["request_auth"]["session_id"], "staging-session-001")
        self.assertEqual(status["latest_execution"]["request_auth"]["issued_by"], "ops_a")
        self.assertTrue(status["latest_execution"]["request_auth"]["session_tracked"])
        self.assertTrue(status["latest_execution"]["request_auth"]["issuer_registered"])
        self.assertEqual(status["latest_execution"]["request_auth"]["issuer_status"], "active")
        self.assertEqual(status["latest_execution"]["request_auth"]["required_actor_ids"], ["release_manager"])
        self.assertEqual(status["latest_execution"]["release_delivery_readiness_status"], "warning")
        self.assertEqual(status["latest_execution"]["release_delivery_readiness_summary"], "execution readiness needs receipts")
        self.assertEqual(status["latest_execution"]["release_delivery_readiness_next_action_count"], 1)
        self.assertEqual(
            status["latest_execution"]["release_delivery_readiness_next_actions"][0]["action_id"],
            "distribution_publish_receipts",
        )
        self.assertEqual(
            status["latest_execution"]["release_delivery_readiness_blocking_checks"],
            ["missing_receipt:github_release_manual"],
        )
        self.assertEqual(status["channel_entries"][0]["channel_id"], "staging")
        self.assertEqual(status["channel_entries"][0]["rollout_stage"], "canary")
        self.assertEqual(status["operation_counts"]["canary"], 1)
        self.assertEqual(status["clean_machine_bootstrap"]["status"], "passed")
        self.assertEqual(status["clean_machine_bootstrap"]["details"]["step_count"], 4)
        self.assertEqual(status["clean_machine_bootstrap"]["details"]["step_statuses"][0]["id"], "create_venv")
        self.assertTrue(status["clean_machine_bootstrap"]["details"]["doctor_report_exists"])
        self.assertEqual(status["clean_machine_bootstrap"]["details"]["doctor_report_path"], "logs/reports/doctor_self_check.json")
        self.assertEqual(status["clean_machine_bootstrap"]["details"]["doctor_check_count"], 6)
        self.assertEqual(status["release_live_runner_baseline"]["status"], "passed")
        self.assertEqual(status["release_live_runner_baseline"]["path"], "logs/reports/release_live_runner_baseline_staging.json")
        self.assertEqual(status["release_live_runner_baseline"]["details"]["check_count"], 10)
        self.assertEqual(status["release_live_runner_baseline"]["details"]["checks"][0]["check_id"], "chromium_browser")
        self.assertEqual(status["release_live_runner_baseline"]["details"]["runner_profile_id"], "release_windows_runner")
        self.assertEqual(status["release_live_runner_baseline"]["details"]["runner_name"], "godot-release-01")
        self.assertEqual(status["release_live_runner_baseline"]["details"]["declared_runner_labels"], ["self-hosted", "windows", "godot"])
        self.assertEqual(status["full_live_validation"]["status"], "passed")
        self.assertEqual(status["request_auth_posture"]["status"], "passed")
        self.assertTrue(status["request_auth_posture"]["report_exists"])
        self.assertEqual(status["request_auth_posture"]["rotation_window_days"], 30)
        self.assertEqual(status["request_auth_posture"]["matching_token_ids"], ["staging_release_manager"])
        self.assertEqual(status["request_auth_posture"]["tokens_expiring_soon_count"], 0)
        self.assertEqual(status["request_auth_posture"]["matching_session_token_count"], 1)
        self.assertEqual(status["request_auth_posture"]["matching_registered_issuer_token_count"], 1)
        self.assertEqual(status["request_auth_posture"]["identity_boundary_path"], "deployment/release_identity_boundary.json")
        self.assertTrue(status["request_auth_posture"]["identity_boundary_exists"])
        self.assertEqual(status["request_auth_posture"]["identity_boundary_profile_id"], "staging_identity_boundary")
        self.assertEqual(status["request_auth_posture"]["identity_boundary_status"], "passed")
        self.assertEqual(status["request_auth_posture"]["identity_provider_mode"], "project_manifest")
        self.assertEqual(status["request_auth_posture"]["identity_session_policy_status"], "passed")
        self.assertEqual(status["request_auth_posture"]["identity_secret_rotation_status"], "passed")
        self.assertEqual(status["request_auth_rotation_audit"]["status"], "passed")
        self.assertTrue(status["request_auth_rotation_audit"]["report_exists"])
        self.assertEqual(status["request_auth_rotation_audit"]["passed_action_count"], 2)
        self.assertEqual(status["request_auth_rotation_audit"]["actions"], ["promotion_record", "release_execution"])
        self.assertEqual(status["request_auth_rotation_audit"]["coverage"][0]["action"], "release_execution")
        self.assertEqual(status["request_auth_identity_audit"]["status"], "passed")
        self.assertTrue(status["request_auth_identity_audit"]["report_exists"])
        self.assertEqual(status["request_auth_identity_audit"]["passed_action_count"], 2)
        self.assertEqual(status["request_auth_identity_audit"]["scoped_issuer_count"], 1)
        self.assertEqual(status["request_auth_identity_audit"]["coverage"][0]["action"], "release_execution")
        self.assertEqual(status["release_distribution_bundle"]["status"], "passed")
        self.assertTrue(status["release_distribution_bundle"]["bundle_exists"])
        self.assertEqual(status["release_distribution_bundle"]["payload_file_count"], 4)
        self.assertEqual(status["release_distribution_bundle"]["distribution_manifest_path"], "logs/reports/release_distribution/staging/web-staging-001/distribution_manifest.json")
        self.assertEqual(status["release_distribution_bundle"]["install_smoke_status"], "passed")
        self.assertTrue(status["release_distribution_bundle"]["install_smoke_report_exists"])
        self.assertEqual(
            status["release_distribution_bundle"]["install_smoke_state_path"],
            "logs/reports/release_distribution_smoke/staging/web-staging-001/installed_release/.release_bundle/installed_release.json",
        )
        self.assertEqual(status["release_distribution_bundle"]["install_smoke_backup_count"], 1)
        self.assertEqual(status["release_distribution_bundle"]["install_smoke_installed_build_id"], "web-staging-001")
        self.assertEqual(status["release_distribution_bundle"]["install_smoke_installed_version"], "0.1.0-staging+1")
        self.assertEqual(status["release_distribution_bundle"]["install_smoke_previous_build_id"], "web-staging-001")
        self.assertEqual(
            status["release_distribution_bundle"]["install_smoke_backup_dir"],
            "logs/reports/release_distribution_smoke/staging/web-staging-001/installed_release/backups/web-staging-001_20260416T101500Z",
        )
        self.assertEqual(status["release_distribution_bundle"]["install_smoke_removed_build_id"], "web-staging-001")
        self.assertEqual(status["release_distribution_bundle"]["install_smoke_removed_version"], "0.1.0-staging+1")
        self.assertEqual(status["release_distribution_bundle"]["archive_status"], "passed")
        self.assertTrue(status["release_distribution_bundle"]["archive_file_exists"])
        self.assertTrue(status["release_distribution_bundle"]["archive_sha256_exists"])
        self.assertEqual(status["release_distribution_bundle"]["channel_index_status"], "passed")
        self.assertTrue(status["release_distribution_bundle"]["channel_index_report_exists"])
        self.assertTrue(status["release_distribution_bundle"]["channel_index_latest_matches_current"])
        self.assertEqual(status["release_distribution_bundle"]["handoff_status"], "passed")
        self.assertTrue(status["release_distribution_bundle"]["handoff_manifest_exists"])
        self.assertTrue(status["release_distribution_bundle"]["handoff_install_script_exists"])
        self.assertEqual(status["release_distribution_bundle"]["handoff_file_count"], 8)
        self.assertEqual(status["release_distribution_bundle"]["signing_handoff_status"], "skipped")
        self.assertFalse(status["release_distribution_bundle"]["signing_handoff_manifest_exists"])
        self.assertEqual(status["release_distribution_bundle"]["publish_handoff_status"], "skipped")
        self.assertFalse(status["release_distribution_bundle"]["publish_handoff_manifest_exists"])
        self.assertEqual(status["release_distribution_bundle"]["publish_receipts_status"], "skipped")
        self.assertFalse(status["release_distribution_bundle"]["publish_receipts_manifest_exists"])
        self.assertEqual(status["release_distribution_bundle"]["delivery_manifest_path"], "deployment/release_distribution_delivery.json")
        self.assertTrue(status["release_distribution_bundle"]["delivery_manifest_exists"])
        self.assertEqual(status["release_distribution_bundle"]["delivery_profile_id"], "staging_internal_windows")
        self.assertEqual(status["release_distribution_bundle"]["delivery_status"], "passed")
        self.assertEqual(status["release_distribution_bundle"]["delivery_primary_installer"], "portable_handoff")
        self.assertEqual(status["release_distribution_bundle"]["delivery_signing_status"], "passed")
        self.assertEqual(status["release_distribution_bundle"]["delivery_publish_targets"], ["staging_ci_artifact"])
        self.assertEqual(status["full_live_validation"]["details"]["lane_count"], 4)
        self.assertEqual(status["full_live_validation"]["details"]["report_release_build_id"], "web-staging-001")
        self.assertEqual(status["full_live_validation"]["details"]["release_binding_status"], "passed")
        self.assertEqual(status["full_live_validation"]["details"]["step_statuses"][0]["id"], "godot_live_sandbox")
        self.assertEqual(
            status["full_live_validation"]["details"]["step_statuses"][0]["report_path"],
            "logs/reports/full_live_validation_lanes/godot_live_sandbox.json",
        )
        self.assertEqual(
            status["full_live_validation"]["details"]["step_statuses"][0]["artifact_paths"][0],
            "logs/live_sandbox_state.json",
        )
        self.assertEqual(status["full_live_validation"]["details"]["lane_artifact_count"], 3)
        self.assertEqual(
            status["full_live_validation"]["details"]["lane_artifacts"][0]["lane_id"],
            "godot_live_sandbox",
        )
        self.assertTrue(status["full_live_validation"]["details"]["lane_artifacts"][0]["report_exists"])
        self.assertEqual(
            status["full_live_validation"]["details"]["lane_artifacts"][0]["report_path"],
            "logs/reports/full_live_validation_lanes/godot_live_sandbox.json",
        )
        self.assertEqual(
            status["full_live_validation"]["details"]["step_statuses"][2]["flow_statuses"]["release_promotion_history_report_flow"],
            "passed",
        )
        self.assertEqual(
            status["full_live_validation"]["details"]["lane_artifacts"][2]["flow_statuses"]["release_promotion_history_flow"],
            "passed",
        )

    def test_release_candidate_checklist_normalizes_nested_contracts(self):
        checklist = normalize_release_candidate_checklist({
            "project_root": "D:/repo",
            "runtime_root": "D:/repo",
            "mode": "advisory",
            "fail_on_warnings": True,
            "release_manifest_source": "versioned_fallback",
            "checklist": [
                {"item_id": "quality_gate", "label": "Quality Gate", "status": "passed", "required": True, "message": "ok"},
                {"item_id": "channel_ready", "label": "Channel", "status": "warning", "required": False, "message": "qa only"},
            ],
            "release_summary": {
                "build_id": "web-qa-001",
                "version": "0.1.0",
                "channel": "qa",
                "quality_gate": {"passed": True, "checks": [{"name": "smoke_test", "status": "ok", "message": "done"}]},
            },
            "production_readiness": {"schema_version": "1.0", "readiness_status": "warning"},
        })

        self.assertEqual(checklist["schema_version"], RELEASE_CANDIDATE_CHECKLIST_SCHEMA_VERSION)
        self.assertEqual(checklist["status"], "warning")
        self.assertFalse(checklist["should_block"])
        self.assertEqual(checklist["warning_checks"], ["channel_ready"])
        self.assertEqual(checklist["quality_gate"]["schema_version"], QUALITY_GATE_SCHEMA_VERSION)
        self.assertEqual(checklist["release_summary"]["schema_version"], RELEASE_SUMMARY_SCHEMA_VERSION)
        self.assertEqual(checklist["contract_versions"]["production_readiness"], "1.0")

    def test_release_execution_status_normalizes_release_live_ci_summary(self):
        status = normalize_release_execution_status({
            "target_channel_filter": "release",
            "release_live_ci_summary": {
                "status": "passed",
                "path": "logs/reports/release_live_ci/release_live_ci_summary.json",
                "summary": "ci_gate=passed / lanes=1 / signoffs=passed",
                "details": {
                    "artifact_dir": "logs/reports/release_live_ci",
                    "generated_at": "2026-04-18T10:00:00Z",
                    "target_channel": "release",
                    "target_environment": "production",
                    "release_build_id": "web-release-001",
                    "release_version": "1.0.0",
                    "release_channel": "release",
                    "release_manifest_path": "api_server/static/dist/release_manifest.json",
                    "summary_markdown_path": "logs/reports/release_live_ci/release_live_ci_summary.md",
                    "summary_markdown_exists": True,
                    "workflow_step_results_path": "logs/reports/release_live_ci/release_live_ci_workflow_steps.json",
                    "dispatch_audit": {
                        "status": "warning",
                        "summary": "workflow_dispatch accepted for sossossal/cim-comm-soc@main",
                        "path": "logs/reports/release_live_ci/release_live_dispatch.json",
                        "recorded_at": "2026-04-18T10:10:00Z",
                        "triggered_by": "release_manager",
                        "workflow": "release-live-gates.yml",
                        "repo": "sossossal/cim-comm-soc",
                        "ref": "main",
                        "target_channel": "release",
                        "target_environment": "production",
                        "ready": True,
                        "dispatch_attempted": True,
                        "dispatch_completed": True,
                        "wait": True,
                        "follow_up_required": False,
                        "token_source": "GH_TOKEN",
                        "run": {
                            "id": 9001,
                            "status": "completed",
                            "conclusion": "success",
                            "html_url": "https://github.com/sossossal/cim-comm-soc/actions/runs/9001",
                        },
                        "request_auth": {
                            "status": "passed",
                            "actor_id": "release_manager",
                            "reason": "accepted",
                        },
                    },
                    "event_stream": {
                        "status": "warning",
                        "path": "release_live_ci_events.json",
                        "summary": "events=5 / blocked=1 / warning=1 / latest=run_finished",
                        "route_kind": "github_workflow",
                        "route_id": "github_workflow:release:production",
                        "invocation_source": "github_workflow",
                        "event_count": 5,
                        "blocked_event_count": 1,
                        "warning_event_count": 1,
                        "latest_event_type": "run_finished",
                        "latest_event_status": "warning",
                        "events": [
                            {
                                "event_id": "run_started_1",
                                "event_type": "run_started",
                                "scope": "run",
                                "order": 1,
                                "status": "passed",
                                "occurred_at": "2026-04-18T10:00:00Z",
                                "summary": "route=github_workflow",
                            }
                        ],
                    },
                    "invocation": {
                        "source": "github_workflow",
                        "mode": "strict",
                        "fail_on_warnings": True,
                        "providers": ["codex"],
                        "approvers": ["qa_lead", "tech_lead", "producer", "ops"],
                    },
                    "ci_gate": {
                        "status": "passed",
                        "should_block": False,
                        "fail_on_warnings": True,
                        "blocking_checks": [],
                        "warning_checks": [],
                        "evaluated_check_count": 4,
                    },
                    "runtime_gates": {
                        "release_live_runner_baseline_status": "passed",
                        "full_live_validation_status": "passed",
                        "distribution_bundle_status": "passed",
                        "distribution_signing_handoff_status": "passed",
                        "distribution_publish_handoff_status": "warning",
                        "distribution_publish_receipts_status": "warning",
                        "identity_handoff_status": "passed",
                    },
                    "runtime_lanes": {
                        "full_live_validation": [
                            {
                                "lane_id": "portal_click_smoke",
                                "label": "Portal Click Smoke",
                                "status": "passed",
                                "summary": "click ok",
                                "report_path": "logs/reports/full_live_validation_lanes/portal_click_smoke.json",
                                "artifact_paths": ["logs/test_artifacts/portal_click_chrome_8014.out"],
                                "flow_statuses": {
                                    "release_promotion_history_report_flow": "passed",
                                },
                            }
                        ]
                    },
                    "workflow_steps": [
                        {
                            "step_id": "export_runner_baseline",
                            "label": "Export release-live runner baseline",
                            "status": "passed",
                            "outcome": "success",
                            "always_run": False,
                            "message": "",
                        },
                        {
                            "step_id": "run_full_live_validation",
                            "label": "Run full live validation",
                            "status": "blocked",
                            "outcome": "failure",
                            "always_run": False,
                            "message": "live validation failed",
                        },
                    ],
                    "human_signoffs": {
                        "status": "passed",
                        "required_signoffs": ["qa_lead", "tech_lead", "producer", "ops"],
                        "provided_signoffs": ["qa_lead", "tech_lead", "producer", "ops"],
                        "missing_signoffs": [],
                    },
                },
            },
        })

        self.assertEqual(status["release_live_ci_summary"]["status"], "passed")
        self.assertEqual(status["release_live_ci_summary"]["path"], "logs/reports/release_live_ci/release_live_ci_summary.json")
        self.assertEqual(status["release_live_ci_summary"]["details"]["summary_markdown_path"], "logs/reports/release_live_ci/release_live_ci_summary.md")
        self.assertTrue(status["release_live_ci_summary"]["details"]["summary_markdown_exists"])
        self.assertEqual(status["release_live_ci_summary"]["details"]["workflow_step_results_path"], "logs/reports/release_live_ci/release_live_ci_workflow_steps.json")
        self.assertEqual(status["release_live_ci_summary"]["details"]["dispatch_audit"]["status"], "warning")
        self.assertEqual(status["release_live_ci_summary"]["details"]["dispatch_audit"]["path"], "logs/reports/release_live_ci/release_live_dispatch.json")
        self.assertEqual(status["release_live_ci_summary"]["details"]["invocation"]["source"], "github_workflow")
        self.assertEqual(status["release_live_ci_summary"]["details"]["ci_gate"]["evaluated_check_count"], 4)
        self.assertEqual(status["release_live_ci_summary"]["details"]["runtime_gates"]["distribution_publish_receipts_status"], "warning")
        self.assertEqual(
            status["release_live_ci_summary"]["details"]["runtime_lanes"]["full_live_validation"][0]["flow_statuses"]["release_promotion_history_report_flow"],
            "passed",
        )
        self.assertEqual(status["release_live_ci_summary"]["details"]["workflow_steps"][0]["step_id"], "export_runner_baseline")
        self.assertEqual(status["release_live_ci_summary"]["details"]["workflow_steps"][1]["status"], "blocked")
        self.assertEqual(status["release_live_ci_summary"]["details"]["workflow_steps"][1]["message"], "live validation failed")
        self.assertEqual(status["release_live_ci_summary"]["details"]["event_stream"]["path"], "release_live_ci_events.json")
        self.assertEqual(status["release_live_ci_summary"]["details"]["event_stream"]["latest_event_type"], "run_finished")
        self.assertEqual(status["release_live_ci_summary"]["details"]["event_stream"]["events"][0]["event_type"], "run_started")

    def test_release_live_event_stream_normalizes_summary(self):
        payload = normalize_release_live_event_stream({
            "status": "warning",
            "path": "release_live_ci_events.json",
            "source": "live_ci_export",
            "generated_at": "2026-04-21T10:00:00Z",
            "route_kind": "github_workflow",
            "route_id": "github_workflow:release:production",
            "invocation_source": "github_workflow",
            "release_build_id": "web-release-001",
            "release_version": "1.0.0",
            "release_channel": "release",
            "target_channel": "release",
            "target_environment": "production",
            "event_count": 2,
            "blocked_event_count": 1,
            "warning_event_count": 0,
            "latest_event_type": "run_finished",
            "latest_event_status": "warning",
            "events": [
                {
                    "event_id": "run_started_1",
                    "event_type": "run_started",
                    "scope": "run",
                    "order": 1,
                    "status": "passed",
                    "occurred_at": "2026-04-21T10:00:00Z",
                    "summary": "route=github_workflow",
                },
                {
                    "event_id": "run_finished_2",
                    "event_type": "run_finished",
                    "scope": "run",
                    "order": 2,
                    "status": "warning",
                    "occurred_at": "2026-04-21T10:05:00Z",
                    "summary": "automation=passed / signoffs=warning",
                },
            ],
        })

        self.assertEqual(payload["schema_version"], RELEASE_LIVE_EVENT_STREAM_SCHEMA_VERSION)
        self.assertEqual(payload["contract_versions"]["release_live_event_stream"], RELEASE_LIVE_EVENT_STREAM_SCHEMA_VERSION)
        self.assertEqual(payload["route_kind"], "github_workflow")
        self.assertEqual(payload["event_count"], 2)
        self.assertEqual(payload["latest_event_type"], "run_finished")
        self.assertEqual(payload["events"][1]["status"], "warning")

    def test_release_live_dispatch_preflight_normalizes_summary(self):
        payload = normalize_release_live_dispatch_preflight({
            "status": "warning",
            "ready": True,
            "summary": "ready=yes / repo=sossossal/cim-comm-soc / ref=main / token=yes / workflow_dispatch=yes",
            "workflow": "release-live-gates.yml",
            "workflow_path": ".github/workflows/release-live-gates.yml",
            "workflow_exists": True,
            "workflow_dispatch_enabled": True,
            "repo": "sossossal/cim-comm-soc",
            "repo_source": "git_remote",
            "origin_remote_url": "https://github.com/sossossal/cim-comm-soc.git",
            "ref": "main",
            "ref_source": "git_branch",
            "token_env_names": ["GH_TOKEN", "GITHUB_TOKEN"],
            "token_present": True,
            "token_source": "GH_TOKEN",
            "gh_cli_installed": False,
            "gh_cli_path": "",
            "runner_labels": ["self-hosted", "windows", "godot"],
            "dispatch_inputs": {
                "runner_labels": '["self-hosted", "windows", "godot"]',
                "target_channel": "staging",
                "target_environment": "staging",
                "release_manifest_path": "api_server/static/dist/web_release_validation_ci/release_manifest.json",
                "runner_profile_path": "deployment/release_live_runner_profile.json",
                "approvers": "qa_lead,tech_lead",
                "providers": "codex,openai_api",
                "artifact_dir": "logs/reports/release_live_ci",
                "fail_on_warnings": "false",
            },
            "blocking_checks": [],
            "warning_checks": ["gh_cli_missing"],
            "recommendations": ["Install gh if you also want CLI parity with the Portal dispatch surface."],
        })

        self.assertEqual(payload["schema_version"], RELEASE_LIVE_DISPATCH_PREFLIGHT_SCHEMA_VERSION)
        self.assertEqual(payload["contract_versions"]["release_live_dispatch_preflight"], RELEASE_LIVE_DISPATCH_PREFLIGHT_SCHEMA_VERSION)
        self.assertEqual(payload["repo"], "sossossal/cim-comm-soc")
        self.assertEqual(payload["ref"], "main")
        self.assertTrue(payload["ready"])
        self.assertEqual(payload["dispatch_inputs"]["target_channel"], "staging")
        self.assertEqual(payload["warning_checks"], ["gh_cli_missing"])

    def test_release_live_dispatch_audit_normalizes_nested_preflight_result_and_request_auth(self):
        payload = normalize_release_live_dispatch_audit({
            "status": "blocked",
            "summary": "release write request authentication failed: token required",
            "path": "logs/reports/release_live_ci/release_live_dispatch.json",
            "artifact_dir": "logs/reports/release_live_ci",
            "recorded_at": "2026-04-23T10:00:00Z",
            "triggered_by": "release_manager",
            "workflow": "release-live-gates.yml",
            "repo": "sossossal/cim-comm-soc",
            "ref": "main",
            "ready": True,
            "dispatch_attempted": False,
            "dispatch_completed": False,
            "follow_up_required": True,
            "blocking_checks": ["request_auth_blocked"],
            "warning_checks": ["gh_cli_missing"],
            "request_auth": {
                "status": "blocked",
                "actor_id": "release_manager",
                "reason": "token required",
                "token_id": "token-001",
            },
            "preflight": {
                "schema_version": "1.0",
                "status": "warning",
                "ready": True,
                "workflow": "release-live-gates.yml",
                "repo": "sossossal/cim-comm-soc",
                "ref": "main",
                "dispatch_inputs": {
                    "target_channel": "staging",
                    "target_environment": "staging",
                    "artifact_dir": "logs/reports/release_live_ci",
                },
                "warning_checks": ["gh_cli_missing"],
            },
            "dispatch_result": {
                "schema_version": "1.0",
                "ok": False,
                "status": "skipped",
                "summary": "",
                "wait": True,
                "run": {},
            },
        })

        self.assertEqual(payload["schema_version"], RELEASE_LIVE_DISPATCH_AUDIT_SCHEMA_VERSION)
        self.assertEqual(payload["status"], "blocked")
        self.assertEqual(payload["preflight"]["repo"], "sossossal/cim-comm-soc")
        self.assertEqual(payload["inputs"]["target_channel"], "staging")
        self.assertEqual(payload["request_auth"]["actor_id"], "release_manager")
        self.assertIn("request_auth_blocked", payload["blocking_checks"])
        self.assertEqual(payload["contract_versions"]["release_live_dispatch_audit"], RELEASE_LIVE_DISPATCH_AUDIT_SCHEMA_VERSION)

    def test_release_artifact_manifest_normalizes_execution_readiness_and_lanes(self):
        payload = normalize_release_artifact_manifest({
            "project_root": ".",
            "runtime_root": ".",
            "target_channel": "staging",
            "target_environment": "staging",
            "ci_mode": "non_live_staging_rehearsal",
            "release_build_id": "web-staging-001",
            "release_version": "0.1.0-staging+1",
            "release_channel": "staging",
            "release_summary": {
                "build_id": "web-staging-001",
                "version": "0.1.0-staging+1",
                "channel": "staging",
                "release_manifest_path": "api_server/static/dist/release_manifest.json",
            },
            "generated_files": ["release_execution_status.json", "", "release_execution_status.json"],
            "runtime_assembly": {
                "route_kind": "ci_rehearsal",
                "actor_id": "ci_release",
                "target_channel": "staging",
                "capabilities": [
                    {
                        "capability_id": "release_delivery_readiness_read",
                        "policy_status": "warning",
                        "sandbox_profile": "read_only",
                        "surface_types": ["command", "gateway_method"],
                        "artifact_contracts": ["release_delivery_readiness", "release_live_ci_summary"],
                        "entrypoints": ["/release-delivery-readiness"],
                        "warning_reasons": ["capability_registry_warning"],
                    }
                ],
            },
            "event_stream": {
                "status": "passed",
                "route_kind": "ci_rehearsal",
                "path": "release_live_ci_events.json",
            },
            "execution_delivery_readiness": {
                "status": "warning",
                "summary": "delivery needs external handoff",
                "next_action_ids": ["distribution_signing_handoff", "distribution_signing_handoff"],
                "blocking_checks": ["missing signing receipt"],
            },
            "release_delivery_readiness": {
                "status": "blocked",
                "summary": "identity=blocked / workflow=warning / distribution=passed",
                "next_actions": [
                    {"action_id": "external_identity_boundary", "status": "blocked"},
                ],
                "blocking_checks": ["identity_boundary_blocked"],
            },
            "runtime_lanes": {
                "full_live_validation": [
                    {
                        "lane_id": "portal_click_smoke",
                        "status": "passed",
                        "artifact_paths": ["runtime_reports/full_live_validation_lanes/portal_click_smoke.json"],
                        "flow_statuses": {"release_promotion_history_report_flow": "passed", "ignored": "passed"},
                    }
                ],
            },
        })

        self.assertEqual(payload["schema_version"], RELEASE_ARTIFACT_MANIFEST_SCHEMA_VERSION)
        self.assertEqual(
            payload["contract_versions"]["release_artifact_manifest"],
            RELEASE_ARTIFACT_MANIFEST_SCHEMA_VERSION,
        )
        self.assertEqual(payload["mode"], "non_live_staging_rehearsal")
        self.assertEqual(payload["release_build_id"], "web-staging-001")
        self.assertEqual(payload["release_version"], "0.1.0-staging+1")
        self.assertEqual(payload["release_channel"], "staging")
        self.assertEqual(payload["release_summary"]["schema_version"], RELEASE_SUMMARY_SCHEMA_VERSION)
        self.assertEqual(payload["runtime_assembly"]["route_kind"], "ci_rehearsal")
        self.assertEqual(payload["runtime_assembly"]["warning_count"], 1)
        self.assertEqual(
            payload["runtime_assembly"]["warning_capability_ids"],
            ["release_delivery_readiness_read"],
        )
        self.assertEqual(payload["runtime_assembly"]["warning_sandbox_profiles"], ["read_only"])
        self.assertEqual(payload["event_stream"]["path"], "release_live_ci_events.json")
        self.assertEqual(payload["release_delivery_readiness"]["status"], "blocked")
        self.assertEqual(len(payload["release_delivery_readiness"]["next_actions"]), 1)
        self.assertEqual(
            payload["release_delivery_readiness"]["blocking_checks"],
            ["identity_boundary_blocked"],
        )
        self.assertEqual(payload["execution_delivery_readiness"]["status"], "warning")
        self.assertEqual(payload["execution_delivery_readiness"]["next_action_count"], 1)
        self.assertEqual(
            payload["execution_delivery_readiness"]["next_action_ids"],
            ["distribution_signing_handoff"],
        )
        self.assertEqual(payload["runtime_lanes"]["full_live_validation"][0]["lane_id"], "portal_click_smoke")
        self.assertEqual(
            payload["runtime_lanes"]["full_live_validation"][0]["flow_statuses"],
            {"release_promotion_history_report_flow": "passed"},
        )
        self.assertEqual(payload["generated_files"], ["release_execution_status.json"])

    def test_release_capability_registry_normalizes_capabilities(self):
        registry = normalize_release_capability_registry({
            "registry_id": "release_control_plane_capabilities",
            "registry_path": "deployment/release_capability_registry.json",
            "registry_exists": True,
            "valid": True,
            "capabilities": [
                {
                    "capability_id": "release_execution_mutation_write",
                    "label": "Release Execution Mutation",
                    "group": "release_control_plane",
                    "surface_types": ["command", "gateway_method", "unknown"],
                    "risk_level": "critical",
                    "requires_actor": True,
                    "requires_request_auth": True,
                    "default_enabled": True,
                    "optional_heavy": False,
                    "sandbox_profile": "release_write",
                    "artifact_contracts": ["release_execution_status", "release_promotion_history"],
                    "entrypoints": ["/release-execution/run", "/release-execution/run"],
                    "owners": ["ops", "ops", "release_manager"],
                    "status": "passed",
                }
            ],
        })

        self.assertEqual(registry["schema_version"], RELEASE_CAPABILITY_REGISTRY_SCHEMA_VERSION)
        self.assertEqual(registry["status"], "passed")
        self.assertEqual(registry["registry_path"], "deployment/release_capability_registry.json")
        self.assertEqual(registry["capability_count"], 1)
        self.assertEqual(registry["surface_counts"]["command"], 1)
        self.assertEqual(registry["surface_counts"]["gateway_method"], 1)
        self.assertEqual(registry["risk_counts"]["critical"], 1)
        self.assertEqual(registry["capabilities"][0]["surface_types"], ["command", "gateway_method"])
        self.assertEqual(registry["capabilities"][0]["owners"], ["ops", "release_manager"])
        self.assertEqual(
            registry["contract_versions"]["release_capability_registry"],
            RELEASE_CAPABILITY_REGISTRY_SCHEMA_VERSION,
        )

    def test_release_capability_registry_warns_when_live_summary_manifest_boundary_is_missing(self):
        registry = normalize_release_capability_registry({
            "registry_exists": True,
            "valid": True,
            "capabilities": [
                {
                    "capability_id": "release_delivery_readiness_read",
                    "label": "Release Delivery Readiness",
                    "group": "release_governance",
                    "surface_types": ["command", "gateway_method"],
                    "risk_level": "medium",
                    "sandbox_profile": "read_only",
                    "artifact_contracts": ["release_delivery_readiness", "release_live_ci_summary"],
                    "entrypoints": ["/release-delivery-readiness"],
                    "owners": ["ops"],
                    "status": "passed",
                }
            ],
        })

        capability = registry["capabilities"][0]
        self.assertEqual(registry["status"], "warning")
        self.assertEqual(capability["status"], "warning")
        self.assertIn("release_artifact_manifest", capability["missing_fields"])
        self.assertIn("release_artifact_manifest_entrypoint", capability["missing_fields"])
        self.assertIn("release_artifact_manifest", capability["recommendations"][0])

    def test_release_capability_policy_normalizes_snapshot(self):
        policy = normalize_release_capability_policy({
            "status": "warning",
            "summary": "route=portal / allowed=1 / warning=1 / blocked=1",
            "route_kind": "portal",
            "target_channel": "staging",
            "target_environment": "staging",
            "actor_id": "release_manager",
            "registry_status": "passed",
            "registry_path": "deployment/release_capability_registry.json",
            "registry_id": "release_control_plane_capabilities",
            "route_profile": {
                "allow_workspace_write": True,
                "allow_release_write": True,
                "allow_local_process": False,
                "allow_optional_heavy": False,
                "allow_browser_automation": False,
                "allow_godot_gui": False,
                "allow_network_bridge": False,
            },
            "capabilities": [
                {
                    "capability_id": "release_execution_rollout_write",
                    "label": "Release Execution Rollout",
                    "group": "release_control_plane",
                    "surface_types": ["command", "gateway_method"],
                    "risk_level": "critical",
                    "sandbox_profile": "release_write",
                    "artifact_contracts": ["release_execution_status"],
                    "entrypoints": ["/release-execution/run"],
                    "policy_action": "release_execution",
                    "policy_operation": "canary",
                    "owners": ["release_manager"],
                    "policy_status": "passed",
                    "applicable": True,
                    "invocation_allowed": True,
                    "authorization_status": "passed",
                    "request_auth_posture_status": "passed",
                },
                {
                    "capability_id": "portal_browser_click_smoke_run",
                    "label": "Portal Click Smoke",
                    "group": "release_runtime",
                    "surface_types": ["tool", "command"],
                    "risk_level": "medium",
                    "sandbox_profile": "browser_automation",
                    "artifact_contracts": ["release_live_ci_summary", "release_artifact_manifest"],
                    "entrypoints": [
                        "python tools/run_portal_browser_click_smoke.py",
                        "/release-artifact-manifest",
                    ],
                    "owners": ["qa_lead"],
                    "policy_status": "blocked",
                    "applicable": True,
                    "invocation_allowed": False,
                    "denial_reasons": ["browser_automation_disabled"],
                },
            ],
        })

        self.assertEqual(policy["schema_version"], RELEASE_CAPABILITY_POLICY_SCHEMA_VERSION)
        self.assertEqual(policy["route_kind"], "portal")
        self.assertEqual(policy["allowed_count"], 1)
        self.assertEqual(policy["denied_count"], 1)
        self.assertTrue(policy["route_profile"]["allow_release_write"])
        self.assertEqual(policy["capabilities"][0]["policy_operation"], "canary")
        self.assertEqual(policy["capabilities"][1]["denial_reasons"], ["browser_automation_disabled"])
        self.assertIn("release_artifact_manifest", policy["capabilities"][1]["artifact_contracts"])
        self.assertIn("/release-artifact-manifest", policy["capabilities"][1]["entrypoints"])
        self.assertEqual(
            policy["contract_versions"]["release_capability_policy"],
            RELEASE_CAPABILITY_POLICY_SCHEMA_VERSION,
        )

    def test_release_runtime_assembly_snapshot_normalizes_summary(self):
        snapshot = normalize_release_runtime_assembly_snapshot({
            "status": "warning",
            "summary": "route=github_workflow / actor=release_manager / allowed=2 / warning=0 / blocked=1 / identity=passed",
            "route_kind": "github_workflow",
            "route_id": "github_workflow:release:production",
            "session_id": "web-release-001",
            "invocation_source": "github_workflow",
            "actor_id": "release_manager",
            "target_channel": "release",
            "target_environment": "production",
            "registry_path": "deployment/release_capability_registry.json",
            "registry_status": "passed",
            "policy_status": "blocked",
            "allowed_count": 2,
            "warning_count": 0,
            "denied_count": 1,
            "enabled_sandbox_profiles": ["read_only", "browser_automation"],
            "denied_sandbox_profiles": ["release_write"],
            "auth_profile": {
                "actor_present": True,
                "requires_actor_count": 2,
                "request_auth_required_count": 2,
                "authorization_blocked_capability_ids": ["release_execution_rollback_write"],
            },
            "identity_boundary": {
                "status": "passed",
                "profile_id": "release_identity_boundary",
                "provider_mode": "project_manifest",
                "session_required": True,
            },
            "runner_profile": {
                "status": "passed",
                "profile_id": "release_windows_runner",
                "runner_name": "godot-release-01",
                "runner_labels": ["self-hosted", "windows", "godot"],
            },
            "capabilities": [
                {
                    "capability_id": "portal_browser_click_smoke_run",
                    "label": "Portal Click Smoke",
                    "policy_status": "passed",
                    "sandbox_profile": "browser_automation",
                    "surface_types": ["tool", "command"],
                    "artifact_contracts": ["release_live_ci_summary", "release_artifact_manifest"],
                    "entrypoints": ["python tools/run_portal_browser_click_smoke.py"],
                }
            ],
        })

        self.assertEqual(snapshot["schema_version"], RELEASE_RUNTIME_ASSEMBLY_SCHEMA_VERSION)
        self.assertEqual(snapshot["route_kind"], "github_workflow")
        self.assertEqual(snapshot["auth_profile"]["request_auth_required_count"], 2)
        self.assertEqual(snapshot["identity_boundary"]["profile_id"], "release_identity_boundary")
        self.assertEqual(snapshot["runner_profile"]["runner_labels"], ["self-hosted", "windows", "godot"])
        self.assertEqual(snapshot["capabilities"][0]["sandbox_profile"], "browser_automation")
        self.assertIn("release_artifact_manifest", snapshot["capabilities"][0]["artifact_contracts"])
        self.assertEqual(
            snapshot["capabilities"][0]["entrypoints"],
            ["python tools/run_portal_browser_click_smoke.py"],
        )
        self.assertEqual(
            snapshot["contract_versions"]["release_runtime_assembly_snapshot"],
            RELEASE_RUNTIME_ASSEMBLY_SCHEMA_VERSION,
        )

    def test_release_runtime_assembly_snapshot_derives_warning_summary_from_capabilities(self):
        snapshot = normalize_release_runtime_assembly_snapshot({
            "status": "warning",
            "route_kind": "portal",
            "capabilities": [
                {
                    "capability_id": "release_delivery_readiness_read",
                    "policy_status": "warning",
                    "sandbox_profile": "read_only",
                    "surface_types": ["command", "gateway_method"],
                    "artifact_contracts": ["release_delivery_readiness", "release_live_ci_summary"],
                    "entrypoints": ["/release-delivery-readiness"],
                    "warning_reasons": ["capability_registry_warning"],
                },
                {
                    "capability_id": "release_execution_rollout_write",
                    "policy_status": "blocked",
                    "sandbox_profile": "release_write",
                    "surface_types": ["command", "gateway_method"],
                    "artifact_contracts": ["release_execution_status"],
                    "entrypoints": ["/release-execution/run"],
                    "denial_reasons": ["release_write_disabled"],
                },
            ],
        })

        self.assertEqual(snapshot["warning_count"], 1)
        self.assertEqual(snapshot["denied_count"], 1)
        self.assertEqual(snapshot["warning_capability_ids"], ["release_delivery_readiness_read"])
        self.assertEqual(snapshot["denied_capability_ids"], ["release_execution_rollout_write"])
        self.assertEqual(snapshot["warning_sandbox_profiles"], ["read_only"])
        self.assertEqual(snapshot["denied_sandbox_profiles"], ["release_write"])
        self.assertEqual(snapshot["denied_surface_types"], ["command", "gateway_method"])
        self.assertIn("capability_registry_warning", snapshot["capabilities"][0]["warning_reasons"])


if __name__ == "__main__":
    unittest.main()

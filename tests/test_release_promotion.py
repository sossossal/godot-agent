import hashlib
import json
import os
import shutil
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient


project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from agent_system.tools.release_promotion import (
    build_deployment_rehearsal_report,
    build_release_promotion_evidence_report,
    build_release_promotion_plan,
    build_release_review_bundle,
    build_release_review_bundle_report,
    build_rollback_rehearsal_report,
)
from agent_system.tools.release_distribution import (
    export_release_distribution_archive,
    export_release_distribution_bundle,
    export_release_distribution_channel_index,
    export_release_distribution_install_smoke,
    export_release_distribution_publish_handoff,
    record_release_distribution_publish_receipt,
)
from agent_system.tools.release_live_runner_baseline import (
    default_release_live_runner_baseline_report_path,
)
from agent_system.tools.release_request_auth import (
    export_release_request_auth_identity_audit_report,
    export_release_request_auth_posture_report,
    export_release_request_auth_rotation_audit_report,
)
from agent_system.tools.release_promotion_history import (
    build_release_promotion_history_report,
    build_release_promotion_history,
    record_release_promotion_event,
)
from tools.dispatch_release_live_gates import write_release_live_dispatch_audit
from api_server.main import app


class ReleasePromotionPlanTestCase(unittest.TestCase):
    def setUp(self):
        self.project_dir = project_root / "tests" / ".tmp_release_promotion_project"
        self.runtime_dir = project_root / "tests" / ".tmp_release_promotion_runtime"
        shutil.rmtree(self.project_dir, ignore_errors=True)
        shutil.rmtree(self.runtime_dir, ignore_errors=True)
        self.project_dir.mkdir(parents=True, exist_ok=True)
        self.runtime_dir.mkdir(parents=True, exist_ok=True)

    def tearDown(self):
        shutil.rmtree(self.project_dir, ignore_errors=True)
        shutil.rmtree(self.runtime_dir, ignore_errors=True)

    def _write_access_policy(self) -> None:
        policy = {
            "schema_version": "1.0",
            "actors": [
                {"actor_id": "producer_a", "roles": ["producer"]},
                {"actor_id": "ops_a", "roles": ["ops"]},
                {"actor_id": "release_manager", "roles": ["release_manager"]},
                {"actor_id": "portal_smoke", "roles": ["qa_lead"]},
            ],
            "rules": [
                {
                    "rule_id": "promotion_planned_any",
                    "action": "promotion_record",
                    "decisions": ["planned"],
                    "channels": ["qa", "staging", "release"],
                    "roles": ["producer", "ops", "release_manager"],
                    "allow_without_actor": True,
                },
                {
                    "rule_id": "promotion_non_blocking_qa_staging",
                    "action": "promotion_record",
                    "decisions": ["approved", "promoted"],
                    "channels": ["qa", "staging"],
                    "roles": ["producer", "ops", "release_manager"],
                },
                {
                    "rule_id": "promotion_non_blocking_release",
                    "action": "promotion_record",
                    "decisions": ["approved", "promoted"],
                    "channels": ["release"],
                    "roles": ["ops", "release_manager"],
                },
                {
                    "rule_id": "promotion_blocking_any",
                    "action": "promotion_record",
                    "decisions": ["blocked", "rolled_back", "aborted"],
                    "channels": ["qa", "staging", "release"],
                    "roles": ["producer", "ops", "release_manager"],
                },
            ],
        }
        policy_path = self.project_dir / "deployment" / "release_access_policy.json"
        policy_path.parent.mkdir(parents=True, exist_ok=True)
        policy_path.write_text(json.dumps(policy, ensure_ascii=False, indent=2), encoding="utf-8")

    def _write_request_auth_manifest(
        self,
        token_value: str = "manifest-release-secret",
        *,
        token_id: str = "release_promotion_manager",
        actor_ids: list[str] | None = None,
        action: str = "promotion_record",
        actions: list[str] | None = None,
        target_channel: str = "release",
        target_environment: str = "production",
        allow_local_without_token: bool = False,
        expires_at: str = "2099-01-01T00:00:00Z",
        session_id: str = "release-session-001",
        issued_by: str = "ops_a",
        issued_at: str = "2026-04-15T00:00:00Z",
    ) -> None:
        token_digest = hashlib.sha256(token_value.encode("utf-8")).hexdigest()
        manifest = {
            "schema_version": "1.0",
            "allow_local_without_token": allow_local_without_token,
            "tokens": [
                {
                    "token_id": token_id,
                    "token_sha256": token_digest,
                    "actions": actions or [action],
                    "channels": [target_channel],
                    "target_environments": [target_environment],
                    "actor_ids": actor_ids or ["release_manager"],
                    "expires_at": expires_at,
                    "session_id": session_id,
                    "issued_by": issued_by,
                    "issued_at": issued_at,
                }
            ],
        }
        manifest_path = self.project_dir / "deployment" / "release_request_auth.json"
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    def _fresh_issued_at(self, *, hours_ago: int = 1) -> str:
        return (
            datetime.now(timezone.utc) - timedelta(hours=hours_ago)
        ).replace(microsecond=0).isoformat().replace("+00:00", "Z")

    def _write_identity_registry(
        self,
        *,
        max_session_age_hours: int = 0,
        issuer_id: str = "ops_a",
        subject_actor_ids: list[str] | None = None,
    ) -> None:
        registry_path = self.project_dir / "deployment" / "release_identity_registry.json"
        registry_path.parent.mkdir(parents=True, exist_ok=True)
        registry_path.write_text(
            json.dumps(
                {
                    "schema_version": "1.0",
                    "issuers": [
                        {
                            "issuer_id": issuer_id,
                            "status": "active",
                            "channels": ["qa", "staging", "release"],
                            "target_environments": ["qa", "staging", "production"],
                            "subject_actor_ids": subject_actor_ids or ["producer_a", "release_manager", "ops_a"],
                            "session_required": True,
                            "max_session_age_hours": max_session_age_hours,
                        }
                    ],
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

    def _write_delivery_manifest(self, *, channel: str, environment: str) -> None:
        delivery_path = self.project_dir / "deployment" / "release_distribution_delivery.json"
        delivery_path.parent.mkdir(parents=True, exist_ok=True)
        delivery_path.write_text(
            json.dumps(
                {
                    "schema_version": "1.0",
                    "profiles": [
                        {
                            "profile_id": f"{channel}_delivery",
                            "target_channels": [channel],
                            "target_environments": [environment],
                            "primary_installer": "portable_handoff",
                            "installer_types": ["portable_handoff", "archive_zip"],
                            "signing": {
                                "required": channel == "release",
                                "mode": "manual_pending" if channel == "release" else "sha256_only",
                                "profile_id": "windows_release_codesign" if channel == "release" else "",
                            },
                            "publish_targets": [{"target_id": f"{channel}_artifact", "kind": "ci_artifact"}],
                            "first_run_bootstrap": "doctor_self_check",
                            "upgrade_strategy": "in_place_backup",
                            "uninstall_strategy": "scripted_cleanup",
                        }
                    ],
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

    def _prepare_runtime(self, *, channel: str = "staging") -> None:
        (self.project_dir / "project.godot").write_text("; test project\n", encoding="utf-8")
        (self.project_dir / "README.md").write_text("# temp project\n", encoding="utf-8")
        (self.project_dir / "docs").mkdir(parents=True, exist_ok=True)
        (self.project_dir / "tools").mkdir(parents=True, exist_ok=True)
        (self.project_dir / "tests").mkdir(parents=True, exist_ok=True)
        (self.project_dir / "scenes" / "levels").mkdir(parents=True, exist_ok=True)
        (self.project_dir / "scripts").mkdir(parents=True, exist_ok=True)
        (self.project_dir / "docs" / "支持矩阵与分发说明.md").write_text(
            "# Support Matrix\n\n- release promotion fixture\n",
            encoding="utf-8",
        )
        (self.project_dir / "tools" / "bootstrap_clean_machine.ps1").write_text(
            "Write-Output 'bootstrap fixture'\n",
            encoding="utf-8",
        )
        (self.project_dir / "scenes" / "levels" / "forest_gateway.tscn").write_text(
            '[gd_scene format=3]\n\n[node name="ForestGateway" type="Node2D"]\n',
            encoding="utf-8",
        )
        self._write_access_policy()
        self._write_identity_registry()

        dist_dir = self.runtime_dir / "api_server" / "static" / "dist"
        dist_dir.mkdir(parents=True, exist_ok=True)
        release_dir = dist_dir / "web_20260413"
        release_dir.mkdir(parents=True, exist_ok=True)
        (release_dir / "qa_gate_report.md").write_text("# QA Gate\n", encoding="utf-8")
        (release_dir / "release_notes.md").write_text("# Release Notes\n", encoding="utf-8")
        (release_dir / "build.log").write_text("build ok\n", encoding="utf-8")
        (release_dir / "index.html").write_text("<html></html>", encoding="utf-8")

        manifest = {
            "schema_version": "1.0",
            "build_id": f"web-{channel}-001",
            "version": f"0.1.0-{channel}+1",
            "channel": channel,
            "preset_name": "Web",
            "platform": "web",
            "generated_at": "2026-04-13T10:00:00Z",
            "output_path": "api_server/static/dist/web_20260413/index.html",
            "release_dir": "api_server/static/dist/web_20260413",
            "release_url": "/portal/dist/index.html",
            "versioned_release_url": "/portal/dist/web_20260413/index.html",
            "build_log_path": "api_server/static/dist/web_20260413/build.log",
            "release_notes_path": "api_server/static/dist/web_20260413/release_notes.md",
            "release_manifest_path": "api_server/static/dist/web_20260413/release_manifest.json",
            "feature": {
                "schema_version": "1.0",
                "feature_id": "feature-001",
                "owner": "producer",
                "priority": "high",
                "risk": "medium",
                "blockers": ["qa screenshot pending"],
                "feature_review_history": [{"feature_status": "returned", "review_note": "needs screenshot", "reviewer": "qa_lead", "review_round": "r2", "required_followups": ["attach final screenshot"]}],
                "feature_lifecycle_events": [{"event_type": "review_returned", "summary": "needs screenshot"}],
                "external_links": [{"label": "Review PR", "url": "https://example.test/pr/42", "type": "pull_request", "status": "passed"}],
                "feature_status": "approved",
            },
            "change_summary": ["prepare promotion"],
            "acceptance_checklist": [{"label": "smoke", "status": "ready"}],
            "quality_gate": {
                "schema_version": "1.0",
                "passed": True,
                "channel": channel,
                "preset_name": "Web",
                "checks": [
                    {"name": "feature_status", "status": "passed", "message": "ok"},
                    {"name": "smoke_test", "status": "passed", "message": "ok"},
                ],
                "blocked_checks": [],
                "warning_checks": [],
            },
            "qa_evidence": {
                "scene_path": "res://scenes/levels/forest_gateway.tscn",
                "smoke_status": "passed",
                "assertion_status": "passed",
                "assertion_node_count": 2,
                "asserted_nodes": ["Player", "HUD"],
                "screenshot_status": "passed",
                "screenshot_path": "logs/test_artifacts/release_gate.png",
                "screenshot_diff_ratio": 0.0142,
                "max_screenshot_diff_ratio": 0.05,
                "metrics": {"scene_load_ms": 280, "fps": 59.5, "memory_peak_mb": 132.0},
            },
            "files": [{"path": "index.html", "size": 13, "sha256": "abc"}],
            "rollback_hint": "restore web_20260413",
        }
        manifest_text = json.dumps(manifest, ensure_ascii=False, indent=2)
        (release_dir / "release_manifest.json").write_text(manifest_text, encoding="utf-8")
        (dist_dir / "release_manifest.json").write_text(manifest_text, encoding="utf-8")
        (dist_dir / "release_notes.md").write_text("# Stable Release Notes\n", encoding="utf-8")
        (dist_dir / "qa_gate_report.md").write_text("# Stable QA Gate\n", encoding="utf-8")
        reports_dir = self.runtime_dir / "logs" / "reports"
        reports_dir.mkdir(parents=True, exist_ok=True)
        (reports_dir / "doctor_self_check.json").write_text(
            json.dumps(
                {
                    "schema_version": "1.0",
                    "generated_at": "2026-04-13T10:45:00Z",
                    "ok": True,
                    "config_path": "config.yaml",
                    "report_path": "logs/reports/doctor_self_check.json",
                    "check_count": 6,
                    "passed_check_count": 6,
                    "failed_check_count": 0,
                    "action_item_count": 0,
                    "blocking_checks": [],
                    "summary": "checks=6 / passed=6 / failed=0 / action_items=0",
                    "checks": [],
                    "action_items": [],
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        (reports_dir / "clean_machine_bootstrap.json").write_text(
            json.dumps(
                {
                    "ok": True,
                    "preview": False,
                    "doctor_report_path": "logs/reports/doctor_self_check.json",
                    "doctor_report": {
                        "path": "logs/reports/doctor_self_check.json",
                        "exists": True,
                        "ok": True,
                        "summary": "checks=6 / passed=6 / failed=0 / action_items=0",
                        "check_count": 6,
                        "passed_check_count": 6,
                        "failed_check_count": 0,
                        "action_item_count": 0,
                        "blocking_checks": [],
                    },
                    "steps": [
                        {"id": "install_requirements", "status": "passed"},
                        {"id": "sync_plugin", "status": "passed"},
                        {
                            "id": "doctor",
                            "status": "passed",
                            "report_path": "logs/reports/doctor_self_check.json",
                            "report_exists": True,
                            "doctor_ok": True,
                            "doctor_action_item_count": 0,
                        },
                    ],
                    "blocking_issues": [],
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        (reports_dir / "release_live_runner_baseline_release.json").write_text(
            json.dumps(
                {
                    "schema_version": "1.0",
                    "generated_at": "2026-04-13T10:50:00Z",
                    "status": "passed",
                    "summary": "checks=10 / passed=10 / warning=0 / blocked=0",
                    "report_path": default_release_live_runner_baseline_report_path(target_channel="release"),
                    "target_channel": "release",
                    "target_environment": "production",
                    "check_count": 10,
                    "passed_check_count": 10,
                    "warning_check_count": 0,
                    "blocked_check_count": 0,
                    "blocking_checks": [],
                    "warning_checks": [],
                    "checks": [],
                    "recommendations": [],
                    "detected_tools": {
                        "powershell_executable": "powershell",
                        "godot_executable": "C:/Godot/godot.exe",
                        "browser_executable": "C:/Program Files/Google/Chrome/Application/chrome.exe",
                    },
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        executed_at = "2026-04-13T11:00:00Z"
        release_binding = {
            "status": "passed",
            "manifest_source": "stable",
            "manifest_path": "api_server/static/dist/release_manifest.json",
            "build_id": manifest["build_id"],
            "version": manifest["version"],
            "channel": manifest["channel"],
            "generated_at": manifest["generated_at"],
            "release_dir": manifest["release_dir"],
            "output_path": manifest["output_path"],
            "release_url": manifest["release_url"],
            "versioned_release_url": manifest["versioned_release_url"],
        }
        lane_reports_dir = reports_dir / "full_live_validation_lanes"
        lane_reports_dir.mkdir(parents=True, exist_ok=True)
        live_validation_steps = []
        for lane in [
            {
                "id": "godot_live_sandbox",
                "label": "Godot Live Sandbox",
                "status": "passed",
                "summary": "sandbox ok",
                "artifact_paths": [
                    "logs/live_sandbox_state.json",
                    "logs/api_server_8000.out",
                ],
            },
            {
                "id": "portal_dom_smoke",
                "label": "Portal DOM Smoke",
                "status": "passed",
                "summary": "dom ok",
                "artifact_paths": [
                    "logs/test_artifacts/portal_browser_smoke_8012.html",
                    "logs/portal_browser_api_8012.out",
                ],
            },
            {
                "id": "portal_click_smoke",
                "label": "Portal Click Smoke",
                "status": "passed",
                "summary": "click ok",
                "artifact_paths": [
                    "logs/test_artifacts/portal_click_chrome_8014.out",
                    "logs/portal_click_api_8014.out",
                ],
                "flow_statuses": {
                    "flow": "passed",
                    "release_promotion_history_flow": "passed",
                    "release_promotion_history_report_flow": "passed",
                },
            },
            {
                "id": "remote_mcp_live",
                "label": "Remote MCP Live Smoke",
                "status": "passed",
                "summary": "remote ok",
                "artifact_paths": [
                    "logs/remote_mcp_8766.out",
                    "logs/remote_mcp_8766.err",
                ],
            },
        ]:
            lane_report_relative_path = f"logs/reports/full_live_validation_lanes/{lane['id']}.json"
            (lane_reports_dir / f"{lane['id']}.json").write_text(
                json.dumps(
                    {
                        "schema_version": "1.0",
                        "lane_id": lane["id"],
                        "label": lane["label"],
                        "status": lane["status"],
                        "summary": lane["summary"],
                        "executed_at": executed_at,
                        "report_path": lane_report_relative_path,
                        "full_report_path": "logs/reports/full_live_validation.json",
                        "artifact_paths": list(lane["artifact_paths"]),
                        "release_binding": release_binding,
                        "details": {
                            "flow_statuses": dict(lane.get("flow_statuses") or {}),
                        },
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )
            live_validation_steps.append(
                {
                    "id": lane["id"],
                    "label": lane["label"],
                    "status": lane["status"],
                    "summary": lane["summary"],
                    "report_path": lane_report_relative_path,
                    "artifact_paths": list(lane["artifact_paths"]),
                    "details": {
                        "artifact_paths": list(lane["artifact_paths"]),
                        "report_path": lane_report_relative_path,
                        "flow_statuses": dict(lane.get("flow_statuses") or {}),
                    },
                }
            )
        (reports_dir / "full_live_validation.json").write_text(
            json.dumps(
                {
                    "schema_version": "1.1",
                    "ok": True,
                    "executed_at": executed_at,
                    "release_binding": release_binding,
                    "steps": live_validation_steps,
                    "blocking_issues": [],
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        release_live_ci_dir = reports_dir / "release_live_ci"
        release_live_ci_dir.mkdir(parents=True, exist_ok=True)
        required_signoffs = ["qa_lead", "tech_lead", "producer", "ops"] if channel == "release" else ["qa_lead", "tech_lead", "producer"]
        release_live_ci_summary = {
            "schema_version": "1.0",
            "generated_at": executed_at,
            "target_channel": channel,
            "target_environment": "production" if channel == "release" else channel,
            "release_manifest_path": "api_server/static/dist/release_manifest.json",
            "release_build_id": manifest["build_id"],
            "release_version": manifest["version"],
            "release_channel": manifest["channel"],
            "invocation": {
                "source": "local_replay",
                "providers": ["codex"],
                "approvers": required_signoffs,
                "mode": "strict" if channel == "release" else "advisory",
                "fail_on_warnings": channel == "release",
            },
            "runtime_assembly": {
                "schema_version": "1.0",
                "status": "warning",
                "summary": (
                    "route=local_replay / actor=- / allowed=3 / warning=0 / "
                    f"blocked=1 / identity=passed / runner_profile=release_windows_runner"
                ),
                "route_kind": "local_replay",
                "route_id": f"local_replay:{channel}:{'production' if channel == 'release' else channel}",
                "session_id": manifest["build_id"],
                "invocation_source": "local_replay",
                "actor_id": "",
                "target_channel": channel,
                "target_environment": "production" if channel == "release" else channel,
                "capability_count": 4,
                "allowed_count": 3,
                "warning_count": 0,
                "denied_count": 1,
                "skipped_count": 0,
                "registry_path": "deployment/release_capability_registry.json",
                "registry_status": "passed",
                "route_profile": {
                    "interactive": True,
                    "live_runtime": True,
                    "requires_runner_profile": False,
                    "write_operations_enabled": False,
                },
                "auth_profile": {
                    "actor_present": False,
                    "requires_actor_count": 1,
                    "request_auth_required_count": 1,
                    "authorization_blocked_capability_ids": ["release_execution_rollout_write"],
                    "request_auth_warning_capability_ids": ["release_execution_rollout_write"],
                },
                "identity_boundary": {
                    "status": "passed",
                    "profile_id": "release_identity_boundary" if channel == "release" else "staging_identity_boundary",
                    "provider_mode": "project_manifest",
                    "session_required": channel == "release",
                    "external_handoff_target_id": "release_identity_intake" if channel == "release" else "",
                },
                "runner_profile": {
                    "status": "passed",
                    "profile_id": "release_windows_runner",
                    "runner_name": "godot-release-01",
                    "runner_os": "Windows",
                    "runner_arch": "x64",
                    "runner_labels": ["self-hosted", "windows", "godot"],
                },
                "enabled_surface_types": ["tool", "command"],
                "denied_surface_types": ["gateway_method"],
                "enabled_sandbox_profiles": ["browser_automation"],
                "denied_sandbox_profiles": ["release_write"],
                "capabilities": [
                    {
                        "capability_id": "release_execution_rollout_write",
                        "policy_status": "blocked",
                        "sandbox_profile": "release_write",
                        "surface_types": ["command", "gateway_method"],
                        "artifact_contracts": ["release_execution_status"],
                        "entrypoints": ["/release-execution/run"],
                        "denial_reasons": ["release_write_disabled"],
                    },
                    {
                        "capability_id": "release_live_ci_summary_read",
                        "policy_status": "passed",
                        "sandbox_profile": "read_only",
                        "surface_types": ["command", "gateway_method"],
                        "artifact_contracts": ["release_live_ci_summary", "release_artifact_manifest"],
                        "entrypoints": ["/release-live-ci/summary", "/release-artifact-manifest"],
                        "denial_reasons": [],
                    }
                ],
            },
            "event_stream": {
                "schema_version": "1.0",
                "status": "passed",
                "summary": "events=5 / blocked=0 / warning=0 / latest=run_finished",
                "path": "release_live_ci_events.json",
                "source": "local_replay",
                "generated_at": executed_at,
                "route_kind": "local_replay",
                "route_id": f"local_replay:{channel}:{'production' if channel == 'release' else channel}",
                "invocation_source": "local_replay",
                "release_build_id": manifest["build_id"],
                "release_version": manifest["version"],
                "release_channel": manifest["channel"],
                "target_channel": channel,
                "target_environment": "production" if channel == "release" else channel,
                "event_count": 5,
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
                        "occurred_at": executed_at,
                        "step_id": "",
                        "lane_id": "",
                        "summary": "route=local_replay / invocation=local_replay / build=web-qa-001",
                        "message": "",
                        "details": {},
                    },
                    {
                        "event_id": "step_finished_2",
                        "event_type": "step_finished",
                        "scope": "workflow_step",
                        "order": 2,
                        "status": "passed",
                        "occurred_at": executed_at,
                        "step_id": "run_full_live_validation",
                        "lane_id": "",
                        "summary": "run_full_live_validation [passed]",
                        "message": "",
                        "details": {},
                    },
                    {
                        "event_id": "lane_reported_3",
                        "event_type": "lane_reported",
                        "scope": "runtime_lane",
                        "order": 3,
                        "status": "passed",
                        "occurred_at": executed_at,
                        "step_id": "",
                        "lane_id": "portal_click_smoke",
                        "summary": "portal_click_smoke [passed]",
                        "message": "",
                        "details": {
                            "flow_statuses": {
                                "release_promotion_history_report_flow": "passed",
                            },
                        },
                    },
                    {
                        "event_id": "gate_evaluated_4",
                        "event_type": "gate_evaluated",
                        "scope": "automation_gate",
                        "order": 4,
                        "status": "passed",
                        "occurred_at": executed_at,
                        "step_id": "",
                        "lane_id": "",
                        "summary": "ci_gate=passed / blocking=none / warning=none",
                        "message": "",
                        "details": {},
                    },
                    {
                        "event_id": "run_finished_5",
                        "event_type": "run_finished",
                        "scope": "run",
                        "order": 5,
                        "status": "passed",
                        "occurred_at": executed_at,
                        "step_id": "",
                        "lane_id": "",
                        "summary": "automation=passed / signoffs=passed",
                        "message": "",
                        "details": {},
                    },
                ],
            },
            "ci_gate": {
                "status": "passed",
                "should_block": False,
                "fail_on_warnings": channel == "release",
                "blocking_checks": [],
                "warning_checks": [],
                "evaluated_check_count": 3,
                "evaluated_checks": [],
            },
            "runtime_gates": {
                "release_live_runner_baseline_status": "passed",
                "full_live_validation_status": "passed",
                "distribution_bundle_status": "passed",
                "distribution_signing_handoff_status": "skipped",
                "distribution_publish_handoff_status": "skipped",
                "distribution_publish_receipts_status": "skipped",
                "identity_handoff_status": "passed",
            },
            "runtime_lanes": {
                "full_live_validation": [
                    {
                        "lane_id": str(item["id"]),
                        "label": str(item["label"]),
                        "status": str(item["status"]),
                        "summary": str(item["summary"]),
                        "report_path": str(item["report_path"]),
                        "artifact_paths": list(item["artifact_paths"]),
                        "flow_statuses": dict(item["details"].get("flow_statuses") or {}),
                    }
                    for item in live_validation_steps
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
                    "status": "passed",
                    "outcome": "success",
                    "always_run": False,
                    "message": "",
                },
            ],
            "human_signoffs": {
                "status": "passed",
                "required_signoffs": required_signoffs,
                "provided_signoffs": required_signoffs,
                "missing_signoffs": [],
            },
            "report_files": {
                "summary_markdown": "release_live_ci_summary.md",
                "workflow_step_results": "release_live_ci_workflow_steps.json",
            },
        }
        (release_live_ci_dir / "release_live_ci_summary.json").write_text(
            json.dumps(release_live_ci_summary, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        (release_live_ci_dir / "release_live_ci_summary.md").write_text(
            "# Release Live CI Summary\n\n- portal_click_smoke [passed]\n- release_promotion_history_report_flow=passed\n",
            encoding="utf-8",
        )
        write_release_live_dispatch_audit(
            self.runtime_dir,
            artifact_dir="logs/reports/release_live_ci",
            preflight={
                "schema_version": "1.0",
                "status": "passed",
                "ready": True,
                "workflow": "release-live-gates.yml",
                "repo": "sossossal/cim-comm-soc",
                "ref": "main",
                "dispatch_inputs": {
                    "target_channel": channel,
                    "target_environment": "production" if channel == "release" else channel,
                },
            },
            dispatch_result={
                "schema_version": "1.0",
                "ok": True,
                "status": "warning",
                "summary": "workflow_dispatch accepted for sossossal/cim-comm-soc@main",
                "repo": "sossossal/cim-comm-soc",
                "workflow": "release-live-gates.yml",
                "ref": "main",
                "wait": True,
                "token_source": "GH_TOKEN",
                "run": {
                    "id": 9001,
                    "number": 42,
                    "status": "completed",
                    "conclusion": "success",
                    "html_url": "https://github.com/sossossal/cim-comm-soc/actions/runs/9001",
                },
            },
            request_auth={
                "status": "passed",
                "actor_id": "release_manager",
                "token_id": "token-001",
                "reason": "accepted",
            },
            triggered_by="release_manager",
        )
        project_reports_dir = self.project_dir / "logs" / "reports"
        shutil.rmtree(project_reports_dir, ignore_errors=True)
        shutil.copytree(reports_dir, project_reports_dir)
        write_release_live_dispatch_audit(
            self.project_dir,
            artifact_dir="logs/reports/release_live_ci",
            preflight={
                "schema_version": "1.0",
                "status": "passed",
                "ready": True,
                "workflow": "release-live-gates.yml",
                "repo": "sossossal/cim-comm-soc",
                "ref": "main",
                "dispatch_inputs": {
                    "target_channel": channel,
                    "target_environment": "production" if channel == "release" else channel,
                },
            },
            dispatch_result={
                "schema_version": "1.0",
                "ok": True,
                "status": "warning",
                "summary": "workflow_dispatch accepted for sossossal/cim-comm-soc@main",
                "repo": "sossossal/cim-comm-soc",
                "workflow": "release-live-gates.yml",
                "ref": "main",
                "wait": True,
                "token_source": "GH_TOKEN",
                "run": {
                    "id": 9001,
                    "number": 42,
                    "status": "completed",
                    "conclusion": "success",
                    "html_url": "https://github.com/sossossal/cim-comm-soc/actions/runs/9001",
                },
            },
            request_auth={
                "status": "passed",
                "actor_id": "release_manager",
                "token_id": "token-001",
                "reason": "accepted",
            },
            triggered_by="release_manager",
        )

    def test_repository_sample_builds_release_promotion_plan(self):
        payload = build_release_promotion_plan(
            project_root,
            runtime_root=project_root,
            target_channel="staging",
            approvers=["qa_lead", "tech_lead", "producer"],
            providers=["codex", "openai_api"],
        )

        self.assertEqual(payload["schema_version"], "1.1")
        self.assertIn(payload["status"], {"passed", "warning", "blocked"})
        self.assertEqual(payload["target_channel"], "staging")
        self.assertIn("release_promotion_plan", payload["contract_versions"])
        self.assertGreaterEqual(payload["item_count"], 5)
        self.assertIn(payload["request_auth_posture"]["status"], {"warning", "passed", "blocked"})
        self.assertIn(payload["request_auth_rotation_audit"]["status"], {"warning", "passed", "blocked"})
        self.assertIn("evidence_bundle", payload)
        self.assertIn("review_bundle", payload)
        self.assertIn("deployment_rehearsal", payload)
        self.assertIn("rollback_rehearsal", payload)

    def test_release_promotion_blocks_when_signoffs_are_missing(self):
        self._prepare_runtime(channel="staging")

        payload = build_release_promotion_plan(
            self.project_dir,
            runtime_root=self.runtime_dir,
            target_channel="release",
            approvers=["qa_lead", "tech_lead"],
            providers=["codex"],
        )

        self.assertEqual(payload["status"], "blocked")
        self.assertTrue(payload["should_block"])
        self.assertIn("signoff_gate", payload["blocking_checks"])
        self.assertIn("producer", payload["missing_signoffs"])
        self.assertIn("ops", payload["missing_signoffs"])
        self.assertIn("signoff_record", payload["evidence_bundle"]["missing_artifacts"])

    def test_release_promotion_api_shape(self):
        self._prepare_runtime(channel="staging")

        client = TestClient(app)
        response = client.post(
            "/release-promotion/plan",
            json={
                "project_path": str(self.project_dir),
                "target_channel": "staging",
                "target_environment": "staging",
                "approvers": ["qa_lead", "tech_lead", "producer"],
                "providers": ["codex"],
                "mode": "advisory",
            },
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["schema_version"], "1.1")
        self.assertEqual(payload["project_path"], f"{self.project_dir.resolve().as_posix()}/")
        self.assertEqual(payload["target_channel"], "staging")
        self.assertEqual(payload["mode"], "advisory")
        self.assertEqual(payload["agent_compatibility_summary"]["provider_count"], 1)
        self.assertIn(payload["release_live_ci_summary"]["status"], {"warning", "passed", "blocked"})
        self.assertEqual(payload["runtime_assembly_snapshot"]["route_kind"], "local_replay")
        self.assertEqual(
            payload["runtime_assembly_snapshot"]["runner_profile"]["profile_id"],
            "release_windows_runner",
        )
        live_summary_capability = next(
            item for item in payload["runtime_assembly_snapshot"]["capabilities"]
            if item["capability_id"] == "release_live_ci_summary_read"
        )
        self.assertIn("release_artifact_manifest", live_summary_capability["artifact_contracts"])
        self.assertIn("/release-artifact-manifest", live_summary_capability["entrypoints"])
        self.assertEqual(
            payload["release_live_ci_summary"]["details"]["workflow_steps"][0]["step_id"],
            "export_runner_baseline",
        )
        self.assertEqual(
            payload["release_live_ci_summary"]["details"]["runtime_assembly"]["identity_boundary"]["profile_id"],
            "staging_identity_boundary",
        )
        live_summary_detail_capability = next(
            item for item in payload["release_live_ci_summary"]["details"]["runtime_assembly"]["capabilities"]
            if item["capability_id"] == "release_live_ci_summary_read"
        )
        self.assertIn("release_artifact_manifest", live_summary_detail_capability["artifact_contracts"])
        self.assertEqual(
            payload["release_live_ci_summary"]["details"]["event_stream"]["path"],
            "release_live_ci_events.json",
        )
        self.assertEqual(
            payload["release_live_ci_summary"]["details"]["event_stream"]["latest_event_type"],
            "run_finished",
        )
        self.assertEqual(
            payload["release_live_ci_summary"]["details"]["dispatch_audit"]["path"],
            "logs/reports/release_live_ci/release_live_dispatch.json",
        )
        self.assertIn(payload["request_auth_posture"]["status"], {"warning", "passed", "blocked"})
        self.assertIn(payload["release_delivery_readiness"]["status"], {"warning", "passed", "blocked"})
        self.assertEqual(payload["release_delivery_readiness"]["component_count"], 3)
        self.assertIn("release_candidate_gate", [item["item_id"] for item in payload["checklist"]])
        self.assertIn("evidence_bundle", payload)
        self.assertIn("review_bundle", payload)
        self.assertIn("deployment_rehearsal", payload)
        self.assertIn("rollback_rehearsal", payload)

    def test_release_promotion_report_builders_include_new_sections(self):
        self._prepare_runtime(channel="staging")

        payload = build_release_promotion_plan(
            self.project_dir,
            runtime_root=self.runtime_dir,
            target_channel="staging",
            approvers=["qa_lead", "tech_lead", "producer"],
            providers=["codex"],
            mode="advisory",
        )

        evidence_report = build_release_promotion_evidence_report(payload)
        review_bundle_report = build_release_review_bundle_report(payload)
        deployment_report = build_deployment_rehearsal_report(payload)
        rollback_report = build_rollback_rehearsal_report(payload)

        self.assertIn("# Release Promotion Evidence Bundle", evidence_report)
        self.assertIn("## Artifacts", evidence_report)
        self.assertIn("## QA Evidence", evidence_report)
        self.assertIn("## Clean Machine Bootstrap", evidence_report)
        self.assertIn("## Full Live Validation", evidence_report)
        self.assertIn("## Release Live CI Summary", evidence_report)
        self.assertIn("## Release Live Runner Baseline", evidence_report)
        self.assertIn("## Release Request Auth Posture", evidence_report)
        self.assertIn("## Release Request Auth Rotation Audit", evidence_report)
        self.assertIn("## Release Distribution Bundle", evidence_report)
        self.assertIn("## Release Delivery Readiness", evidence_report)
        self.assertIn("Next Actions:", evidence_report)
        self.assertIn("signing=skipped", evidence_report)
        self.assertIn("distribution_publish_handoff", evidence_report)
        self.assertIn("distribution_publish_receipts", evidence_report)
        self.assertIn("Doctor Report: path=logs/reports/doctor_self_check.json", evidence_report)
        self.assertIn("Binding Status: passed", evidence_report)
        self.assertIn("Lane Report (portal_click_smoke):", evidence_report)
        self.assertIn("release_promotion_history_report_flow=passed", evidence_report)
        self.assertIn("CI Gate: status=passed / should_block=False", evidence_report)
        self.assertIn("Dispatch Audit: status=warning / ready=True / attempted=True / completed=True", evidence_report)
        self.assertIn("Dispatch Summary: workflow_dispatch accepted for sossossal/cim-comm-soc@main", evidence_report)
        self.assertIn("Route: local_replay / route_id=local_replay:staging:staging", evidence_report)
        self.assertIn("Runner Profile: status=passed / profile=release_windows_runner", evidence_report)
        self.assertIn("Identity Boundary: status=passed / profile=staging_identity_boundary", evidence_report)
        self.assertIn("Workflow Step Results: logs/reports/release_live_ci/release_live_ci_workflow_steps.json", evidence_report)
        self.assertIn("Path: release_live_ci_events.json / source=local_replay", evidence_report)
        self.assertIn("lane_reported [passed] / scope=runtime_lane / step=- / lane=portal_click_smoke", evidence_report)
        self.assertIn("Workflow Step (run_full_live_validation): status=passed / outcome=success", evidence_report)
        self.assertIn("# Release Review Bundle", review_bundle_report)
        self.assertIn("## Signoff Records", review_bundle_report)
        self.assertIn("qa_lead: status=approved required=True source=provided_signoffs", review_bundle_report)
        self.assertIn("## Review Follow-up Actions", review_bundle_report)
        self.assertIn("feature_blockers: status=blocked owner=feature_owner", review_bundle_report)
        self.assertIn("Summary: files=", review_bundle_report)
        self.assertIn("Docs: README.md", review_bundle_report)
        self.assertIn("## Validation Records", review_bundle_report)
        self.assertIn("qa_evidence: status=passed source=release_qa_evidence method=qa_gate", review_bundle_report)
        self.assertIn("artifact_release_manifest: status=passed source=artifact_links method=contract", review_bundle_report)
        self.assertIn("## Feature Timeline", review_bundle_report)
        self.assertIn("Blocker: qa screenshot pending", review_bundle_report)
        self.assertIn("Event `review_returned`: needs screenshot", review_bundle_report)
        self.assertIn("Review `returned`: needs screenshot [reviewer=qa_lead / round=r2] / followups=attach final screenshot", review_bundle_report)
        self.assertIn("## External Review Links", review_bundle_report)
        self.assertIn("Review PR: type=pull_request status=passed url=https://example.test/pr/42", review_bundle_report)
        self.assertIn("## Risk Summary", review_bundle_report)
        self.assertIn("Feature Blockers: qa screenshot pending", review_bundle_report)
        self.assertIn("Known Issues: 未登记已知风险", review_bundle_report)
        self.assertIn("## Acceptance Checklist", review_bundle_report)
        self.assertIn("## QA Evidence", review_bundle_report)
        self.assertIn("## Clean Machine Bootstrap", review_bundle_report)
        self.assertIn("## Full Live Validation", review_bundle_report)
        self.assertIn("## Release Live CI Summary", review_bundle_report)
        self.assertIn("## Release Live Runner Baseline", review_bundle_report)
        self.assertIn("## Release Request Auth Posture", review_bundle_report)
        self.assertIn("## Release Request Auth Rotation Audit", review_bundle_report)
        self.assertIn("## Release Distribution Bundle", review_bundle_report)
        self.assertIn("## Release Delivery Readiness", review_bundle_report)
        self.assertIn("signing=skipped", review_bundle_report)
        self.assertIn("distribution_publish_receipts", review_bundle_report)
        self.assertIn("Doctor Report: path=logs/reports/doctor_self_check.json", review_bundle_report)
        self.assertIn("Binding Status: passed", review_bundle_report)
        self.assertIn("Lane Report (portal_click_smoke):", review_bundle_report)
        self.assertIn("release_promotion_history_report_flow=passed", review_bundle_report)
        self.assertIn("Route: local_replay / route_id=local_replay:staging:staging", review_bundle_report)
        self.assertIn("Workflow Step (run_full_live_validation): status=passed / outcome=success", review_bundle_report)
        self.assertIn("# Release Promotion Deployment Rehearsal", deployment_report)
        self.assertIn("## Lane Sequence", deployment_report)
        self.assertIn("## Release Live CI Summary", deployment_report)
        self.assertIn("## Release Live Runner Baseline", deployment_report)
        self.assertIn("## Release Request Auth Posture", deployment_report)
        self.assertIn("## Release Request Auth Rotation Audit", deployment_report)
        self.assertIn("## Release Distribution Bundle", deployment_report)
        self.assertIn("## Release Delivery Readiness", deployment_report)
        self.assertIn("distribution_publish_handoff", deployment_report)
        self.assertIn("Route: local_replay / route_id=local_replay:staging:staging", deployment_report)
        self.assertIn("Workflow Step (run_full_live_validation): status=passed / outcome=success", deployment_report)
        self.assertIn("# Release Promotion Rollback Rehearsal", rollback_report)
        self.assertIn("## Rehearsal Steps", rollback_report)

    def test_release_target_forces_strict_mode_and_fail_on_warnings(self):
        self._prepare_runtime(channel="staging")

        payload = build_release_promotion_plan(
            self.project_dir,
            runtime_root=self.runtime_dir,
            target_channel="release",
            approvers=["qa_lead", "tech_lead", "producer", "ops"],
            providers=["codex"],
            mode="advisory",
            fail_on_warnings=False,
        )

        self.assertEqual(payload["mode"], "strict")
        self.assertTrue(payload["fail_on_warnings"])
        self.assertIn("qa_evidence_summary", [item["artifact_id"] for item in payload["evidence_bundle"]["artifacts"]])
        self.assertIn("clean_machine_bootstrap", [item["artifact_id"] for item in payload["evidence_bundle"]["artifacts"]])
        self.assertIn("full_live_validation", [item["artifact_id"] for item in payload["evidence_bundle"]["artifacts"]])
        self.assertIn("release_live_runner_baseline", [item["artifact_id"] for item in payload["evidence_bundle"]["artifacts"]])
        self.assertIn("release_live_ci_summary", [item["artifact_id"] for item in payload["evidence_bundle"]["artifacts"]])
        lane_artifact = next(
            item
            for item in payload["evidence_bundle"]["artifacts"]
            if item["artifact_id"] == "full_live_validation_lane_portal_click_smoke"
        )
        self.assertEqual(lane_artifact["status"], "passed")
        self.assertEqual(lane_artifact["path"], "logs/reports/full_live_validation_lanes/portal_click_smoke.json")
        self.assertEqual(lane_artifact["details"]["status"], "passed")
        self.assertEqual(
            lane_artifact["details"]["flow_statuses"]["release_promotion_history_report_flow"],
            "passed",
        )
        runner_baseline_check = next(
            item
            for item in payload["deployment_rehearsal"]["preflight_checks"]
            if item["check_id"] == "release_live_runner_baseline_gate"
        )
        release_live_ci_check = next(
            item
            for item in payload["deployment_rehearsal"]["preflight_checks"]
            if item["check_id"] == "release_live_ci_summary_gate"
        )
        self.assertEqual(runner_baseline_check["status"], "passed")
        self.assertEqual(release_live_ci_check["status"], "passed")

    def test_release_target_blocks_when_request_auth_posture_is_not_hardened(self):
        self._prepare_runtime(channel="release")

        payload = build_release_promotion_plan(
            self.project_dir,
            runtime_root=self.runtime_dir,
            target_channel="release",
            approvers=["qa_lead", "tech_lead", "producer", "ops"],
            providers=["codex"],
            mode="advisory",
            fail_on_warnings=False,
        )

        request_auth_artifact = next(
            item
            for item in payload["evidence_bundle"]["artifacts"]
            if item["artifact_id"] == "release_request_auth_posture"
        )
        request_auth_check = next(
            item
            for item in payload["deployment_rehearsal"]["preflight_checks"]
            if item["check_id"] == "request_auth_posture_gate"
        )
        rotation_audit_artifact = next(
            item
            for item in payload["evidence_bundle"]["artifacts"]
            if item["artifact_id"] == "release_request_auth_rotation_audit"
        )
        rotation_audit_check = next(
            item
            for item in payload["deployment_rehearsal"]["preflight_checks"]
            if item["check_id"] == "request_auth_rotation_audit_gate"
        )
        identity_audit_artifact = next(
            item
            for item in payload["evidence_bundle"]["artifacts"]
            if item["artifact_id"] == "release_request_auth_identity_audit"
        )
        identity_audit_check = next(
            item
            for item in payload["deployment_rehearsal"]["preflight_checks"]
            if item["check_id"] == "request_auth_identity_audit_gate"
        )

        self.assertEqual(payload["request_auth_posture"]["status"], "warning")
        self.assertEqual(payload["request_auth_rotation_audit"]["status"], "warning")
        self.assertEqual(payload["request_auth_identity_audit"]["status"], "blocked")
        self.assertEqual(payload["status"], "blocked")
        self.assertIn("request_auth_posture_gate", payload["blocking_checks"])
        self.assertIn("request_auth_rotation_audit_gate", payload["blocking_checks"])
        self.assertIn("request_auth_identity_audit_gate", payload["blocking_checks"])
        self.assertEqual(request_auth_artifact["status"], "blocked")
        self.assertEqual(rotation_audit_artifact["status"], "blocked")
        self.assertEqual(identity_audit_artifact["status"], "blocked")
        self.assertIn("release_request_auth_posture", payload["evidence_bundle"]["missing_artifacts"])
        self.assertIn("release_request_auth_rotation_audit", payload["evidence_bundle"]["missing_artifacts"])
        self.assertIn("release_request_auth_identity_audit", payload["evidence_bundle"]["missing_artifacts"])
        self.assertIn("release_request_auth_posture", payload["review_bundle"]["blocking_items"])
        self.assertIn("release_request_auth_rotation_audit", payload["review_bundle"]["blocking_items"])
        self.assertIn("release_request_auth_identity_audit", payload["review_bundle"]["blocking_items"])
        self.assertEqual(request_auth_check["status"], "blocked")
        self.assertEqual(rotation_audit_check["status"], "blocked")
        self.assertEqual(identity_audit_check["status"], "blocked")
        self.assertIn("request_auth_posture_gate", payload["deployment_rehearsal"]["blocking_checks"])
        self.assertIn("request_auth_rotation_audit_gate", payload["deployment_rehearsal"]["blocking_checks"])
        self.assertIn("request_auth_identity_audit_gate", payload["deployment_rehearsal"]["blocking_checks"])

    def test_release_target_blocks_when_distribution_bundle_is_missing(self):
        self._prepare_runtime(channel="release")
        self._write_identity_registry(max_session_age_hours=72)
        self._write_request_auth_manifest(
            actions=["promotion_record", "release_execution"],
            issued_at=self._fresh_issued_at(),
        )

        payload = build_release_promotion_plan(
            self.project_dir,
            runtime_root=self.runtime_dir,
            target_channel="release",
            approvers=["qa_lead", "tech_lead", "producer", "ops"],
            providers=["codex"],
            mode="advisory",
            fail_on_warnings=False,
        )

        distribution_artifact = next(
            item
            for item in payload["evidence_bundle"]["artifacts"]
            if item["artifact_id"] == "release_distribution_bundle"
        )
        distribution_check = next(
            item
            for item in payload["deployment_rehearsal"]["preflight_checks"]
            if item["check_id"] == "release_distribution_bundle_gate"
        )

        self.assertEqual(payload["request_auth_posture"]["status"], "passed")
        self.assertEqual(payload["request_auth_rotation_audit"]["status"], "passed")
        self.assertEqual(payload["request_auth_identity_audit"]["status"], "passed")
        self.assertEqual(payload["release_distribution_bundle"]["status"], "warning")
        self.assertEqual(payload["status"], "blocked")
        self.assertIn("release_distribution_bundle_gate", payload["blocking_checks"])
        self.assertEqual(distribution_artifact["status"], "blocked")
        self.assertIn("release_distribution_bundle", payload["evidence_bundle"]["missing_artifacts"])
        self.assertIn("release_distribution_bundle", payload["review_bundle"]["blocking_items"])
        self.assertEqual(distribution_check["status"], "blocked")
        self.assertIn("release_distribution_bundle_gate", payload["deployment_rehearsal"]["blocking_checks"])

    def test_release_target_blocks_when_distribution_install_smoke_is_missing(self):
        self._prepare_runtime(channel="release")
        self._write_identity_registry(max_session_age_hours=72)
        self._write_request_auth_manifest(
            actions=["promotion_record", "release_execution"],
            issued_at=self._fresh_issued_at(),
        )
        export_release_distribution_bundle(
            self.project_dir,
            runtime_root=self.runtime_dir,
            target_channel="release",
            target_environment="production",
            release_manifest_path="api_server/static/dist/release_manifest.json",
        )

        payload = build_release_promotion_plan(
            self.project_dir,
            runtime_root=self.runtime_dir,
            target_channel="release",
            approvers=["qa_lead", "tech_lead", "producer", "ops"],
            providers=["codex"],
            mode="advisory",
            fail_on_warnings=False,
        )

        self.assertEqual(payload["request_auth_posture"]["status"], "passed")
        self.assertEqual(payload["request_auth_rotation_audit"]["status"], "passed")
        self.assertEqual(payload["request_auth_identity_audit"]["status"], "passed")
        self.assertEqual(payload["release_distribution_bundle"]["status"], "warning")
        self.assertEqual(payload["release_distribution_bundle"]["install_smoke_status"], "warning")
        self.assertEqual(payload["status"], "blocked")
        self.assertIn("release_distribution_bundle_gate", payload["blocking_checks"])

    def test_release_target_blocks_when_distribution_archive_is_missing(self):
        self._prepare_runtime(channel="release")
        self._write_identity_registry(max_session_age_hours=72)
        self._write_request_auth_manifest(
            actions=["promotion_record", "release_execution"],
            issued_at=self._fresh_issued_at(),
        )
        export_release_distribution_bundle(
            self.project_dir,
            runtime_root=self.runtime_dir,
            target_channel="release",
            target_environment="production",
            release_manifest_path="api_server/static/dist/release_manifest.json",
        )
        export_release_distribution_install_smoke(
            self.project_dir,
            runtime_root=self.runtime_dir,
            target_channel="release",
            target_environment="production",
            release_manifest_path="api_server/static/dist/release_manifest.json",
        )

        payload = build_release_promotion_plan(
            self.project_dir,
            runtime_root=self.runtime_dir,
            target_channel="release",
            approvers=["qa_lead", "tech_lead", "producer", "ops"],
            providers=["codex"],
            mode="advisory",
            fail_on_warnings=False,
        )

        self.assertEqual(payload["release_distribution_bundle"]["status"], "warning")
        self.assertEqual(payload["release_distribution_bundle"]["archive_status"], "warning")
        self.assertEqual(payload["release_distribution_bundle"]["install_smoke_status"], "passed")
        self.assertEqual(payload["status"], "blocked")
        self.assertIn("release_distribution_bundle_gate", payload["blocking_checks"])

    def test_release_target_blocks_when_distribution_channel_index_is_missing(self):
        self._prepare_runtime(channel="release")
        self._write_identity_registry(max_session_age_hours=72)
        self._write_request_auth_manifest(
            actions=["promotion_record", "release_execution"],
            issued_at=self._fresh_issued_at(),
        )
        export_release_distribution_bundle(
            self.project_dir,
            runtime_root=self.runtime_dir,
            target_channel="release",
            target_environment="production",
            release_manifest_path="api_server/static/dist/release_manifest.json",
        )
        export_release_distribution_install_smoke(
            self.project_dir,
            runtime_root=self.runtime_dir,
            target_channel="release",
            target_environment="production",
            release_manifest_path="api_server/static/dist/release_manifest.json",
        )
        export_release_distribution_archive(
            self.project_dir,
            runtime_root=self.runtime_dir,
            target_channel="release",
            target_environment="production",
            release_manifest_path="api_server/static/dist/release_manifest.json",
        )

        payload = build_release_promotion_plan(
            self.project_dir,
            runtime_root=self.runtime_dir,
            target_channel="release",
            approvers=["qa_lead", "tech_lead", "producer", "ops"],
            providers=["codex"],
            mode="advisory",
            fail_on_warnings=False,
        )

        self.assertEqual(payload["release_distribution_bundle"]["status"], "warning")
        self.assertEqual(payload["release_distribution_bundle"]["install_smoke_status"], "passed")
        self.assertEqual(payload["release_distribution_bundle"]["archive_status"], "passed")
        self.assertEqual(payload["release_distribution_bundle"]["channel_index_status"], "warning")
        self.assertEqual(payload["status"], "blocked")
        self.assertIn("release_distribution_bundle_gate", payload["blocking_checks"])

    def test_release_target_accepts_hardened_request_auth_posture(self):
        self._prepare_runtime(channel="release")
        self._write_identity_registry(max_session_age_hours=72)
        self._write_request_auth_manifest(
            actions=["promotion_record", "release_execution"],
            issued_at=self._fresh_issued_at(),
        )
        export_release_distribution_bundle(
            self.project_dir,
            runtime_root=self.runtime_dir,
            target_channel="release",
            target_environment="production",
            release_manifest_path="api_server/static/dist/release_manifest.json",
        )
        export_release_distribution_install_smoke(
            self.project_dir,
            runtime_root=self.runtime_dir,
            target_channel="release",
            target_environment="production",
            release_manifest_path="api_server/static/dist/release_manifest.json",
        )
        export_release_distribution_archive(
            self.project_dir,
            runtime_root=self.runtime_dir,
            target_channel="release",
            target_environment="production",
            release_manifest_path="api_server/static/dist/release_manifest.json",
        )
        export_release_distribution_channel_index(
            self.project_dir,
            runtime_root=self.runtime_dir,
            target_channel="release",
            target_environment="production",
            release_manifest_path="api_server/static/dist/release_manifest.json",
        )

        payload = build_release_promotion_plan(
            self.project_dir,
            runtime_root=self.runtime_dir,
            target_channel="release",
            approvers=["qa_lead", "tech_lead", "producer", "ops"],
            providers=["codex"],
            mode="advisory",
            fail_on_warnings=False,
        )

        request_auth_artifact = next(
            item
            for item in payload["evidence_bundle"]["artifacts"]
            if item["artifact_id"] == "release_request_auth_posture"
        )
        request_auth_check = next(
            item
            for item in payload["checklist"]
            if item["item_id"] == "request_auth_posture_gate"
        )
        rotation_audit_artifact = next(
            item
            for item in payload["evidence_bundle"]["artifacts"]
            if item["artifact_id"] == "release_request_auth_rotation_audit"
        )
        rotation_audit_check = next(
            item
            for item in payload["checklist"]
            if item["item_id"] == "request_auth_rotation_audit_gate"
        )
        identity_audit_artifact = next(
            item
            for item in payload["evidence_bundle"]["artifacts"]
            if item["artifact_id"] == "release_request_auth_identity_audit"
        )
        identity_audit_check = next(
            item
            for item in payload["checklist"]
            if item["item_id"] == "request_auth_identity_audit_gate"
        )
        distribution_artifact = next(
            item
            for item in payload["evidence_bundle"]["artifacts"]
            if item["artifact_id"] == "release_distribution_bundle"
        )
        publish_receipts_artifact = next(
            item
            for item in payload["evidence_bundle"]["artifacts"]
            if item["artifact_id"] == "release_distribution_publish_receipts"
        )
        distribution_check = next(
            item
            for item in payload["checklist"]
            if item["item_id"] == "release_distribution_bundle_gate"
        )

        self.assertEqual(payload["request_auth_posture"]["status"], "passed")
        self.assertEqual(payload["request_auth_rotation_audit"]["status"], "passed")
        self.assertEqual(payload["request_auth_identity_audit"]["status"], "passed")
        self.assertEqual(payload["release_distribution_bundle"]["status"], "passed")
        self.assertEqual(request_auth_check["status"], "passed")
        self.assertEqual(rotation_audit_check["status"], "passed")
        self.assertEqual(identity_audit_check["status"], "passed")
        self.assertEqual(distribution_check["status"], "passed")
        self.assertEqual(request_auth_artifact["status"], "passed")
        self.assertEqual(rotation_audit_artifact["status"], "passed")
        self.assertEqual(identity_audit_artifact["status"], "passed")
        self.assertEqual(distribution_artifact["status"], "passed")
        self.assertEqual(publish_receipts_artifact["status"], "skipped")
        self.assertNotIn("request_auth_posture_gate", payload["blocking_checks"])
        self.assertNotIn("request_auth_rotation_audit_gate", payload["blocking_checks"])
        self.assertNotIn("request_auth_identity_audit_gate", payload["blocking_checks"])
        self.assertNotIn("release_distribution_bundle_gate", payload["blocking_checks"])
        self.assertNotIn("release_request_auth_posture", payload["evidence_bundle"]["missing_artifacts"])
        self.assertNotIn("release_request_auth_rotation_audit", payload["evidence_bundle"]["missing_artifacts"])
        self.assertNotIn("release_request_auth_identity_audit", payload["evidence_bundle"]["missing_artifacts"])
        self.assertNotIn("release_distribution_bundle", payload["evidence_bundle"]["missing_artifacts"])
        self.assertNotIn("release_request_auth_posture", payload["review_bundle"]["blocking_items"])
        self.assertNotIn("release_request_auth_rotation_audit", payload["review_bundle"]["blocking_items"])
        self.assertNotIn("release_request_auth_identity_audit", payload["review_bundle"]["blocking_items"])
        self.assertNotIn("release_distribution_bundle", payload["review_bundle"]["blocking_items"])
        self.assertNotIn("release_distribution_publish_receipts", payload["review_bundle"]["warning_items"])
        self.assertNotIn("request_auth_posture_gate", payload["deployment_rehearsal"]["blocking_checks"])
        self.assertNotIn("request_auth_rotation_audit_gate", payload["deployment_rehearsal"]["blocking_checks"])
        self.assertNotIn("request_auth_identity_audit_gate", payload["deployment_rehearsal"]["blocking_checks"])
        self.assertNotIn("release_distribution_bundle_gate", payload["deployment_rehearsal"]["blocking_checks"])

    def test_release_promotion_threads_distribution_publish_receipts_into_evidence_and_review(self):
        self._prepare_runtime(channel="release")
        self._write_identity_registry(max_session_age_hours=72)
        self._write_delivery_manifest(channel="release", environment="production")
        self._write_request_auth_manifest(
            actions=["promotion_record", "release_execution"],
            issued_at=self._fresh_issued_at(),
        )
        export_release_distribution_bundle(
            self.project_dir,
            runtime_root=self.runtime_dir,
            target_channel="release",
            target_environment="production",
            release_manifest_path="api_server/static/dist/release_manifest.json",
        )
        export_release_distribution_install_smoke(
            self.project_dir,
            runtime_root=self.runtime_dir,
            target_channel="release",
            target_environment="production",
            release_manifest_path="api_server/static/dist/release_manifest.json",
        )
        export_release_distribution_archive(
            self.project_dir,
            runtime_root=self.runtime_dir,
            target_channel="release",
            target_environment="production",
            release_manifest_path="api_server/static/dist/release_manifest.json",
        )
        export_release_distribution_channel_index(
            self.project_dir,
            runtime_root=self.runtime_dir,
            target_channel="release",
            target_environment="production",
            release_manifest_path="api_server/static/dist/release_manifest.json",
        )
        publish_handoff = export_release_distribution_publish_handoff(
            self.project_dir,
            runtime_root=self.runtime_dir,
            target_channel="release",
            target_environment="production",
            release_manifest_path="api_server/static/dist/release_manifest.json",
        )
        record_release_distribution_publish_receipt(
            self.project_dir,
            runtime_root=self.runtime_dir,
            target_channel="release",
            target_environment="production",
            release_manifest_path="api_server/static/dist/release_manifest.json",
            target_id=str(publish_handoff["delivery_publish_targets"][0]),
            status="published",
            external_reference="github-release-2026-04-18",
            artifact_url="https://example.invalid/releases/web-release-001.zip",
            operator="ops_a",
            published_at="2026-04-18T09:30:00Z",
            notes=["release publish receipt fixture"],
        )

        payload = build_release_promotion_plan(
            self.project_dir,
            runtime_root=self.runtime_dir,
            target_channel="release",
            approvers=["qa_lead", "tech_lead", "producer", "ops"],
            providers=["codex"],
            mode="advisory",
            fail_on_warnings=False,
        )
        evidence_report = build_release_promotion_evidence_report(payload)
        review_bundle_report = build_release_review_bundle_report(payload)

        evidence_artifact = next(
            item
            for item in payload["evidence_bundle"]["artifacts"]
            if item["artifact_id"] == "release_distribution_publish_receipts"
        )
        review_artifact = next(
            item
            for item in payload["review_bundle"]["artifact_links"]
            if item["artifact_id"] == "release_distribution_publish_receipts"
        )

        self.assertEqual(payload["release_distribution_bundle"]["publish_receipts_status"], "passed")
        self.assertEqual(evidence_artifact["status"], "passed")
        self.assertEqual(review_artifact["status"], "passed")
        self.assertEqual(
            evidence_artifact["path"],
            "logs/reports/release_distribution_publish_receipts/release/web-release-001/publish_receipts_manifest.json",
        )
        self.assertEqual(
            review_artifact["details"]["publish_receipts_completed_targets"],
            [str(payload["release_distribution_bundle"]["delivery_publish_targets"][0])],
        )
        self.assertNotIn("release_distribution_publish_receipts", payload["evidence_bundle"]["warning_artifacts"])
        self.assertNotIn("release_distribution_publish_receipts", payload["review_bundle"]["warning_items"])
        self.assertIn("release_distribution_publish_receipts: status=passed", evidence_report)
        self.assertIn("release_distribution_publish_receipts: status=passed", review_bundle_report)
        self.assertIn("复核 distribution publish receipts: publish receipts ready", build_deployment_rehearsal_report(payload))

    def test_release_promotion_prefers_redacted_request_auth_report_when_exported(self):
        self._prepare_runtime(channel="release")
        self._write_request_auth_manifest(
            actions=["promotion_record", "release_execution"],
            issued_at=self._fresh_issued_at(),
        )
        export_release_request_auth_posture_report(
            self.project_dir,
            runtime_root=self.runtime_dir,
            action="promotion_record",
            target_channel="release",
            target_environment="production",
        )
        export_release_request_auth_rotation_audit_report(
            self.project_dir,
            runtime_root=self.runtime_dir,
            target_channel="release",
            target_environment="production",
        )
        export_release_request_auth_identity_audit_report(
            self.project_dir,
            runtime_root=self.runtime_dir,
            target_channel="release",
            target_environment="production",
        )
        export_release_distribution_bundle(
            self.project_dir,
            runtime_root=self.runtime_dir,
            target_channel="release",
            target_environment="production",
            release_manifest_path="api_server/static/dist/release_manifest.json",
        )
        export_release_distribution_install_smoke(
            self.project_dir,
            runtime_root=self.runtime_dir,
            target_channel="release",
            target_environment="production",
            release_manifest_path="api_server/static/dist/release_manifest.json",
        )
        export_release_distribution_archive(
            self.project_dir,
            runtime_root=self.runtime_dir,
            target_channel="release",
            target_environment="production",
            release_manifest_path="api_server/static/dist/release_manifest.json",
        )
        export_release_distribution_channel_index(
            self.project_dir,
            runtime_root=self.runtime_dir,
            target_channel="release",
            target_environment="production",
            release_manifest_path="api_server/static/dist/release_manifest.json",
        )

        payload = build_release_promotion_plan(
            self.project_dir,
            runtime_root=self.runtime_dir,
            target_channel="release",
            approvers=["qa_lead", "tech_lead", "producer", "ops"],
            providers=["codex"],
            mode="advisory",
            fail_on_warnings=False,
        )

        request_auth_artifact = next(
            item
            for item in payload["evidence_bundle"]["artifacts"]
            if item["artifact_id"] == "release_request_auth_posture"
        )
        rotation_audit_artifact = next(
            item
            for item in payload["evidence_bundle"]["artifacts"]
            if item["artifact_id"] == "release_request_auth_rotation_audit"
        )
        identity_audit_artifact = next(
            item
            for item in payload["evidence_bundle"]["artifacts"]
            if item["artifact_id"] == "release_request_auth_identity_audit"
        )
        distribution_artifact = next(
            item
            for item in payload["evidence_bundle"]["artifacts"]
            if item["artifact_id"] == "release_distribution_bundle"
        )

        self.assertEqual(
            request_auth_artifact["path"],
            "logs/reports/release_request_auth_posture_promotion_record_release.json",
        )
        self.assertTrue(request_auth_artifact["details"]["report_exists"])
        self.assertEqual(
            request_auth_artifact["details"]["report_path"],
            "logs/reports/release_request_auth_posture_promotion_record_release.json",
        )
        self.assertEqual(
            request_auth_artifact["details"]["manifest_path"],
            "deployment/release_request_auth.json",
        )
        self.assertEqual(
            rotation_audit_artifact["path"],
            "logs/reports/release_request_auth_rotation_audit_release.json",
        )
        self.assertTrue(rotation_audit_artifact["details"]["report_exists"])
        self.assertEqual(
            rotation_audit_artifact["details"]["report_path"],
            "logs/reports/release_request_auth_rotation_audit_release.json",
        )
        self.assertEqual(
            identity_audit_artifact["path"],
            "logs/reports/release_request_auth_identity_audit_release.json",
        )
        self.assertTrue(identity_audit_artifact["details"]["report_exists"])
        self.assertEqual(
            identity_audit_artifact["details"]["report_path"],
            "logs/reports/release_request_auth_identity_audit_release.json",
        )
        self.assertEqual(
            distribution_artifact["path"],
            "logs/reports/release_distribution_bundle_release.json",
        )
        self.assertTrue(distribution_artifact["details"]["report_exists"])
        self.assertEqual(
            distribution_artifact["details"]["report_path"],
            "logs/reports/release_distribution_bundle_release.json",
        )

    def test_release_target_blocks_when_clean_machine_bootstrap_report_is_missing(self):
        self._prepare_runtime(channel="release")
        (self.runtime_dir / "logs" / "reports" / "clean_machine_bootstrap.json").unlink()
        (self.project_dir / "logs" / "reports" / "clean_machine_bootstrap.json").unlink()

        payload = build_release_promotion_plan(
            self.project_dir,
            runtime_root=self.runtime_dir,
            target_channel="release",
            approvers=["qa_lead", "tech_lead", "producer", "ops"],
            providers=["codex"],
            mode="advisory",
            fail_on_warnings=False,
        )

        self.assertEqual(payload["evidence_bundle"]["status"], "blocked")
        self.assertIn("clean_machine_bootstrap", payload["evidence_bundle"]["missing_artifacts"])
        self.assertIn("clean_machine_bootstrap", payload["review_bundle"]["blocking_items"])

    def test_release_target_blocks_when_runner_baseline_report_is_missing(self):
        self._prepare_runtime(channel="release")
        (self.runtime_dir / "logs" / "reports" / "release_live_runner_baseline_release.json").unlink()
        (self.project_dir / "logs" / "reports" / "release_live_runner_baseline_release.json").unlink()
        self._write_identity_registry(max_session_age_hours=72)
        self._write_request_auth_manifest(
            actions=["promotion_record", "release_execution"],
            issued_at=self._fresh_issued_at(),
        )
        export_release_distribution_bundle(
            self.project_dir,
            runtime_root=self.runtime_dir,
            target_channel="release",
            target_environment="production",
            release_manifest_path="api_server/static/dist/release_manifest.json",
        )
        export_release_distribution_install_smoke(
            self.project_dir,
            runtime_root=self.runtime_dir,
            target_channel="release",
            target_environment="production",
            release_manifest_path="api_server/static/dist/release_manifest.json",
        )
        export_release_distribution_archive(
            self.project_dir,
            runtime_root=self.runtime_dir,
            target_channel="release",
            target_environment="production",
            release_manifest_path="api_server/static/dist/release_manifest.json",
        )
        export_release_distribution_channel_index(
            self.project_dir,
            runtime_root=self.runtime_dir,
            target_channel="release",
            target_environment="production",
            release_manifest_path="api_server/static/dist/release_manifest.json",
        )

        payload = build_release_promotion_plan(
            self.project_dir,
            runtime_root=self.runtime_dir,
            target_channel="release",
            approvers=["qa_lead", "tech_lead", "producer", "ops"],
            providers=["codex"],
            mode="advisory",
            fail_on_warnings=False,
        )

        self.assertEqual(payload["status"], "blocked")
        self.assertEqual(payload["release_live_runner_baseline"]["status"], "blocked")
        self.assertIn("release_live_runner_baseline_gate", payload["blocking_checks"])
        self.assertIn("release_live_runner_baseline", payload["evidence_bundle"]["missing_artifacts"])
        self.assertIn("release_live_runner_baseline", payload["review_bundle"]["blocking_items"])
        self.assertIn("release_live_runner_baseline_gate", payload["deployment_rehearsal"]["blocking_checks"])

    def test_release_target_blocks_when_release_live_ci_summary_is_missing(self):
        self._prepare_runtime(channel="release")
        (self.runtime_dir / "logs" / "reports" / "release_live_ci" / "release_live_ci_summary.json").unlink()
        (self.runtime_dir / "logs" / "reports" / "release_live_ci" / "release_live_ci_summary.md").unlink()
        (self.project_dir / "logs" / "reports" / "release_live_ci" / "release_live_ci_summary.json").unlink()
        (self.project_dir / "logs" / "reports" / "release_live_ci" / "release_live_ci_summary.md").unlink()

        payload = build_release_promotion_plan(
            self.project_dir,
            runtime_root=self.runtime_dir,
            target_channel="release",
            approvers=["qa_lead", "tech_lead", "producer", "ops"],
            providers=["codex"],
            mode="advisory",
            fail_on_warnings=False,
        )

        release_live_ci_artifact = next(
            item for item in payload["evidence_bundle"]["artifacts"] if item["artifact_id"] == "release_live_ci_summary"
        )
        release_live_ci_check = next(
            item for item in payload["deployment_rehearsal"]["preflight_checks"] if item["check_id"] == "release_live_ci_summary_gate"
        )
        self.assertEqual(payload["release_live_ci_summary"]["status"], "warning")
        self.assertEqual(release_live_ci_artifact["status"], "blocked")
        self.assertIn("release_live_ci_summary_gate", payload["blocking_checks"])
        self.assertIn("release_live_ci_summary", payload["evidence_bundle"]["missing_artifacts"])
        self.assertIn("release_live_ci_summary", payload["review_bundle"]["blocking_items"])
        self.assertEqual(release_live_ci_check["status"], "blocked")
        self.assertIn("release_live_ci_summary_gate", payload["deployment_rehearsal"]["blocking_checks"])

    def test_release_target_blocks_when_full_live_validation_report_is_missing(self):
        self._prepare_runtime(channel="release")
        (self.runtime_dir / "logs" / "reports" / "full_live_validation.json").unlink()
        (self.project_dir / "logs" / "reports" / "full_live_validation.json").unlink()

        payload = build_release_promotion_plan(
            self.project_dir,
            runtime_root=self.runtime_dir,
            target_channel="release",
            approvers=["qa_lead", "tech_lead", "producer", "ops"],
            providers=["codex"],
            mode="advisory",
            fail_on_warnings=False,
        )

        self.assertEqual(payload["evidence_bundle"]["status"], "blocked")
        self.assertIn("full_live_validation", payload["evidence_bundle"]["missing_artifacts"])
        self.assertIn("full_live_validation", payload["review_bundle"]["blocking_items"])
        self.assertIn("full_live_validation_lane", payload["deployment_rehearsal"]["blocking_checks"])

    def test_release_target_blocks_when_full_live_validation_binding_mismatches_release_bundle(self):
        self._prepare_runtime(channel="release")
        report_path = self.runtime_dir / "logs" / "reports" / "full_live_validation.json"
        report_payload = json.loads(report_path.read_text(encoding="utf-8"))
        report_payload["release_binding"]["build_id"] = "web-release-999"
        report_payload["release_binding"]["channel"] = "staging"
        report_path.write_text(json.dumps(report_payload, ensure_ascii=False, indent=2), encoding="utf-8")

        payload = build_release_promotion_plan(
            self.project_dir,
            runtime_root=self.runtime_dir,
            target_channel="release",
            approvers=["qa_lead", "tech_lead", "producer", "ops"],
            providers=["codex"],
            mode="advisory",
            fail_on_warnings=False,
        )

        full_live_artifact = next(
            item for item in payload["evidence_bundle"]["artifacts"] if item["artifact_id"] == "full_live_validation"
        )
        self.assertEqual(payload["evidence_bundle"]["status"], "blocked")
        self.assertEqual(full_live_artifact["status"], "blocked")
        self.assertEqual(full_live_artifact["details"]["release_binding_status"], "blocked")
        self.assertIn("release_build_id_mismatch", full_live_artifact["details"]["release_binding_mismatches"])
        self.assertIn("release_channel_mismatch", full_live_artifact["details"]["release_binding_mismatches"])
        self.assertIn("full_live_validation", payload["review_bundle"]["blocking_items"])
        self.assertIn("full_live_validation_lane", payload["deployment_rehearsal"]["blocking_checks"])

    def test_build_release_review_bundle_rebuilds_request_auth_artifact_when_bundle_missing(self):
        self._prepare_runtime(channel="staging")

        payload = build_release_promotion_plan(
            self.project_dir,
            runtime_root=self.runtime_dir,
            target_channel="staging",
            approvers=["qa_lead", "tech_lead", "producer"],
            providers=["codex"],
            mode="advisory",
        )
        payload["review_bundle"] = {}

        rebuilt_bundle = build_release_review_bundle(payload)
        request_auth_artifact = next(
            item
            for item in rebuilt_bundle["artifact_links"]
            if item["artifact_id"] == "release_request_auth_posture"
        )
        rotation_audit_artifact = next(
            item
            for item in rebuilt_bundle["artifact_links"]
            if item["artifact_id"] == "release_request_auth_rotation_audit"
        )
        identity_audit_artifact = next(
            item
            for item in rebuilt_bundle["artifact_links"]
            if item["artifact_id"] == "release_request_auth_identity_audit"
        )
        distribution_artifact = next(
            item
            for item in rebuilt_bundle["artifact_links"]
            if item["artifact_id"] == "release_distribution_bundle"
        )

        self.assertEqual(request_auth_artifact["status"], "warning")
        self.assertEqual(request_auth_artifact["artifact_id"], "release_request_auth_posture")
        self.assertEqual(rotation_audit_artifact["status"], "warning")
        self.assertEqual(rotation_audit_artifact["artifact_id"], "release_request_auth_rotation_audit")
        self.assertEqual(identity_audit_artifact["status"], "blocked")
        self.assertEqual(identity_audit_artifact["artifact_id"], "release_request_auth_identity_audit")
        self.assertEqual(distribution_artifact["status"], "warning")
        self.assertEqual(distribution_artifact["artifact_id"], "release_distribution_bundle")

    def test_release_promotion_export_endpoints_return_reports(self):
        self._prepare_runtime(channel="staging")

        client = TestClient(app)
        evidence_response = client.get(
            "/release-promotion/evidence-report",
            params={
                "project_path": str(self.project_dir),
                "target_channel": "staging",
                "target_environment": "staging",
                "approvers": "qa_lead,tech_lead,producer",
                "providers": "codex",
                "mode": "advisory",
            },
        )
        deployment_response = client.get(
            "/release-promotion/deployment-rehearsal",
            params={
                "project_path": str(self.project_dir),
                "target_channel": "staging",
                "target_environment": "staging",
                "approvers": "qa_lead,tech_lead,producer",
                "providers": "codex",
                "mode": "advisory",
            },
        )
        review_bundle_response = client.get(
            "/release-promotion/review-bundle",
            params={
                "project_path": str(self.project_dir),
                "target_channel": "staging",
                "target_environment": "staging",
                "approvers": "qa_lead,tech_lead,producer",
                "providers": "codex",
                "mode": "advisory",
            },
        )
        rollback_response = client.get(
            "/release-promotion/rollback-rehearsal",
            params={
                "project_path": str(self.project_dir),
                "target_channel": "staging",
                "target_environment": "staging",
                "approvers": "qa_lead,tech_lead,producer",
                "providers": "codex",
                "mode": "advisory",
            },
        )

        self.assertEqual(evidence_response.status_code, 200)
        self.assertEqual(deployment_response.status_code, 200)
        self.assertEqual(review_bundle_response.status_code, 200)
        self.assertEqual(rollback_response.status_code, 200)
        self.assertEqual(evidence_response.json()["report_name"], "release_promotion_evidence_bundle.md")
        self.assertIn("# Release Promotion Evidence Bundle", evidence_response.json()["report_content"])
        self.assertEqual(deployment_response.json()["report_name"], "release_promotion_deployment_rehearsal.md")
        self.assertIn("# Release Promotion Deployment Rehearsal", deployment_response.json()["report_content"])
        self.assertEqual(review_bundle_response.json()["report_name"], "release_review_bundle.md")
        self.assertIn("# Release Review Bundle", review_bundle_response.json()["report_content"])
        self.assertEqual(rollback_response.json()["report_name"], "release_promotion_rollback_rehearsal.md")
        self.assertIn("# Release Promotion Rollback Rehearsal", rollback_response.json()["report_content"])

    def test_record_release_promotion_event_persists_history_manifest(self):
        self._prepare_runtime(channel="staging")

        payload = record_release_promotion_event(
            self.project_dir,
            runtime_root=self.runtime_dir,
            target_channel="staging",
            target_environment="staging",
            release_manifest_path="api_server/static/dist/release_manifest.json",
            approvers=["qa_lead", "tech_lead", "producer"],
            providers=["codex"],
            mode="advisory",
            decision="approved",
            executed_by="producer_a",
            note="ready for staging rollout",
            signoff_source="portal_manual",
        )

        history_path = self.project_dir / "deployment" / "release_promotion_history.json"
        self.assertTrue(history_path.exists())
        self.assertEqual(payload["record"]["decision"], "approved")
        self.assertEqual(payload["record"]["executed_by"], "producer_a")
        self.assertEqual(payload["record"]["authorization"]["status"], "passed")
        self.assertEqual(payload["history"]["visible_count"], 1)
        self.assertEqual(payload["history"]["latest_record"]["release_build_id"], "web-staging-001")
        self.assertEqual(payload["history"]["latest_record"]["plan_snapshot"]["schema_version"], "1.1")
        self.assertEqual(payload["history"]["latest_record"]["release_live_ci_status"], "passed")
        self.assertEqual(payload["history"]["latest_record"]["release_live_dispatch_status"], "warning")
        self.assertEqual(
            payload["history"]["latest_record"]["release_live_dispatch_summary"],
            "workflow_dispatch accepted for sossossal/cim-comm-soc@main",
        )
        self.assertEqual(
            payload["history"]["latest_record"]["release_live_dispatch_path"],
            "logs/reports/release_live_ci/release_live_dispatch.json",
        )
        self.assertEqual(payload["history"]["latest_record"]["release_live_ci_event_stream_status"], "passed")
        self.assertEqual(payload["history"]["latest_record"]["release_live_ci_event_count"], 5)
        self.assertEqual(
            payload["history"]["latest_record"]["release_live_ci_workflow_step_results_path"],
            "logs/reports/release_live_ci/release_live_ci_workflow_steps.json",
        )
        self.assertEqual(
            payload["history"]["latest_record"]["release_live_ci_workflow_steps"][0]["step_id"],
            "export_runner_baseline",
        )
        self.assertEqual(payload["history"]["latest_record"]["release_live_ci_failed_workflow_steps"], [])
        self.assertFalse(payload["history"]["latest_record"]["release_live_ci_follow_up_required"])
        self.assertEqual(
            payload["history"]["latest_record"]["release_live_ci_runtime_assembly"]["route_kind"],
            "local_replay",
        )
        self.assertEqual(
            payload["history"]["latest_record"]["release_live_ci_runtime_assembly"]["runner_profile"]["profile_id"],
            "release_windows_runner",
        )
        latest_live_summary_capability = next(
            item for item in payload["history"]["latest_record"]["release_live_ci_runtime_assembly"]["capabilities"]
            if item["capability_id"] == "release_live_ci_summary_read"
        )
        self.assertIn("release_artifact_manifest", latest_live_summary_capability["artifact_contracts"])
        self.assertIn("/release-artifact-manifest", latest_live_summary_capability["entrypoints"])
        self.assertEqual(
            payload["history"]["latest_record"]["release_live_ci_event_stream"]["latest_event_type"],
            "run_finished",
        )

    def test_record_release_promotion_event_persists_distribution_publish_receipts_summary(self):
        self._prepare_runtime(channel="staging")
        self._write_delivery_manifest(channel="staging", environment="staging")
        export_release_distribution_bundle(
            self.project_dir,
            runtime_root=self.runtime_dir,
            target_channel="staging",
            target_environment="staging",
            release_manifest_path="api_server/static/dist/release_manifest.json",
        )
        export_release_distribution_install_smoke(
            self.project_dir,
            runtime_root=self.runtime_dir,
            target_channel="staging",
            target_environment="staging",
            release_manifest_path="api_server/static/dist/release_manifest.json",
        )
        export_release_distribution_archive(
            self.project_dir,
            runtime_root=self.runtime_dir,
            target_channel="staging",
            target_environment="staging",
            release_manifest_path="api_server/static/dist/release_manifest.json",
        )
        export_release_distribution_channel_index(
            self.project_dir,
            runtime_root=self.runtime_dir,
            target_channel="staging",
            target_environment="staging",
            release_manifest_path="api_server/static/dist/release_manifest.json",
        )
        publish_handoff = export_release_distribution_publish_handoff(
            self.project_dir,
            runtime_root=self.runtime_dir,
            target_channel="staging",
            target_environment="staging",
            release_manifest_path="api_server/static/dist/release_manifest.json",
        )
        record_release_distribution_publish_receipt(
            self.project_dir,
            runtime_root=self.runtime_dir,
            target_channel="staging",
            target_environment="staging",
            release_manifest_path="api_server/static/dist/release_manifest.json",
            target_id=str(publish_handoff["delivery_publish_targets"][0]),
            status="published",
            external_reference="staging-artifact-2026-04-18",
            artifact_url="artifact://release-validation/staging/web-staging-001",
            operator="producer_a",
            published_at="2026-04-18T11:00:00Z",
            notes=["staging publish receipt persisted to history"],
        )

        payload = record_release_promotion_event(
            self.project_dir,
            runtime_root=self.runtime_dir,
            target_channel="staging",
            target_environment="staging",
            release_manifest_path="api_server/static/dist/release_manifest.json",
            approvers=["qa_lead", "tech_lead", "producer"],
            providers=["codex"],
            mode="advisory",
            decision="approved",
            executed_by="producer_a",
            note="ready for staging rollout after publish receipt",
            signoff_source="portal_manual",
        )

        latest_record = payload["history"]["latest_record"]
        self.assertEqual(latest_record["distribution_status"], "passed")
        self.assertEqual(latest_record["distribution_publish_receipts_status"], "passed")
        self.assertEqual(
            latest_record["distribution_publish_receipts_manifest_path"],
            "logs/reports/release_distribution_publish_receipts/staging/web-staging-001/publish_receipts_manifest.json",
        )
        self.assertEqual(latest_record["distribution_publish_receipts_target_count"], 1)
        self.assertEqual(latest_record["distribution_publish_receipts_completed_targets"], ["staging_artifact"])
        self.assertEqual(latest_record["distribution_publish_receipts_missing_targets"], [])
        self.assertFalse(latest_record["distribution_publish_receipts_follow_up_required"])
        self.assertIn(latest_record["release_delivery_readiness_status"], {"passed", "warning", "blocked"})
        self.assertEqual(
            latest_record["release_delivery_readiness_next_action_count"],
            len(latest_record["release_delivery_readiness_next_actions"]),
        )
        self.assertNotIn(
            "distribution_signing_handoff",
            [item["action_id"] for item in latest_record["release_delivery_readiness_next_actions"]],
        )
        self.assertEqual(latest_record["release_live_ci_status"], "passed")
        self.assertEqual(latest_record["release_live_dispatch_status"], "warning")
        self.assertEqual(latest_record["release_live_dispatch_run_status"], "completed")
        self.assertEqual(latest_record["release_live_dispatch_run_conclusion"], "success")
        self.assertEqual(latest_record["release_live_ci_summary"], "ci_gate=passed / lanes=4 / signoffs=passed")
        self.assertEqual(latest_record["release_live_ci_event_stream_status"], "passed")
        self.assertEqual(
            latest_record["release_live_ci_summary_markdown_path"],
            "logs/reports/release_live_ci/release_live_ci_summary.md",
        )
        self.assertEqual(
            latest_record["release_live_ci_workflow_steps"][1]["step_id"],
            "run_full_live_validation",
        )
        self.assertEqual(latest_record["release_live_ci_failed_workflow_steps"], [])
        self.assertFalse(latest_record["release_live_ci_follow_up_required"])
        self.assertEqual(latest_record["release_live_ci_runtime_assembly"]["route_kind"], "local_replay")
        latest_live_summary_capability = next(
            item for item in latest_record["release_live_ci_runtime_assembly"]["capabilities"]
            if item["capability_id"] == "release_live_ci_summary_read"
        )
        self.assertIn("release_artifact_manifest", latest_live_summary_capability["artifact_contracts"])
        self.assertEqual(latest_record["release_live_ci_latest_event_type"], "run_finished")

    def test_release_promotion_history_supports_filters_and_pagination(self):
        self._prepare_runtime(channel="staging")

        record_release_promotion_event(
            self.project_dir,
            runtime_root=self.runtime_dir,
            target_channel="staging",
            target_environment="staging",
            release_manifest_path="api_server/static/dist/release_manifest.json",
            approvers=["qa_lead", "tech_lead", "producer"],
            providers=["codex"],
            mode="advisory",
            decision="approved",
            executed_by="producer_a",
            note="approve staging",
            signoff_source="portal_manual",
        )
        release_live_ci_summary_path = self.runtime_dir / "logs" / "reports" / "release_live_ci" / "release_live_ci_summary.json"
        project_release_live_ci_summary_path = self.project_dir / "logs" / "reports" / "release_live_ci" / "release_live_ci_summary.json"
        for summary_path in [release_live_ci_summary_path, project_release_live_ci_summary_path]:
            summary_payload = json.loads(summary_path.read_text(encoding="utf-8"))
            summary_payload["status"] = "warning"
            summary_payload["summary"] = "ci_gate=warning / lanes=4 / signoffs=passed"
            summary_payload["ci_gate"]["status"] = "warning"
            summary_payload["workflow_steps"][1]["status"] = "warning"
            summary_payload["workflow_steps"][1]["outcome"] = "failure"
            summary_payload["workflow_steps"][1]["message"] = "portal click smoke failed"
            summary_path.write_text(json.dumps(summary_payload, ensure_ascii=False, indent=2), encoding="utf-8")
        record_release_promotion_event(
            self.project_dir,
            runtime_root=self.runtime_dir,
            target_channel="release",
            target_environment="production",
            release_manifest_path="api_server/static/dist/release_manifest.json",
            approvers=["qa_lead", "tech_lead", "producer", "ops"],
            providers=["codex"],
            mode="advisory",
            decision="blocked",
            executed_by="ops_a",
            note="hold release",
            signoff_source="ops_review",
        )

        payload = build_release_promotion_history(
            self.project_dir,
            runtime_root=self.runtime_dir,
            decision="blocked",
            target_channel="release",
            executed_by="ops_a",
            live_ci_status="warning",
            dispatch_status="warning",
            dispatch_follow_up="clear",
            dispatch_run_status="completed",
            dispatch_run_conclusion="success",
            failed_workflow_step="run_full_live_validation",
            offset=0,
            limit=1,
        )

        self.assertEqual(payload["matched_count"], 1)
        self.assertEqual(payload["visible_count"], 1)
        self.assertEqual(payload["live_ci_status_filter"], "warning")
        self.assertEqual(payload["dispatch_status_filter"], "warning")
        self.assertEqual(payload["dispatch_follow_up_filter"], "clear")
        self.assertEqual(payload["dispatch_run_status_filter"], "completed")
        self.assertEqual(payload["dispatch_run_conclusion_filter"], "success")
        self.assertEqual(payload["failed_workflow_step_filter"], "run_full_live_validation")
        self.assertEqual(payload["decision_counts"]["blocked"], 1)
        self.assertEqual(payload["latest_record"]["decision"], "blocked")
        self.assertEqual(payload["latest_record"]["executed_by"], "ops_a")
        self.assertEqual(payload["latest_record"]["release_live_ci_status"], "warning")
        self.assertEqual(payload["latest_record"]["release_live_dispatch_status"], "warning")
        self.assertEqual(payload["latest_record"]["release_live_ci_event_stream_status"], "passed")
        self.assertEqual(payload["latest_record"]["release_live_ci_failed_workflow_steps"], ["run_full_live_validation"])
        self.assertEqual(payload["items"][0]["target_channel"], "release")
        self.assertIsNone(payload["next_offset"])

    def test_release_promotion_history_report_includes_distribution_publish_receipts(self):
        self._prepare_runtime(channel="staging")
        self._write_delivery_manifest(channel="staging", environment="staging")
        export_release_distribution_bundle(
            self.project_dir,
            runtime_root=self.runtime_dir,
            target_channel="staging",
            target_environment="staging",
            release_manifest_path="api_server/static/dist/release_manifest.json",
        )
        export_release_distribution_install_smoke(
            self.project_dir,
            runtime_root=self.runtime_dir,
            target_channel="staging",
            target_environment="staging",
            release_manifest_path="api_server/static/dist/release_manifest.json",
        )
        export_release_distribution_archive(
            self.project_dir,
            runtime_root=self.runtime_dir,
            target_channel="staging",
            target_environment="staging",
            release_manifest_path="api_server/static/dist/release_manifest.json",
        )
        export_release_distribution_channel_index(
            self.project_dir,
            runtime_root=self.runtime_dir,
            target_channel="staging",
            target_environment="staging",
            release_manifest_path="api_server/static/dist/release_manifest.json",
        )
        publish_handoff = export_release_distribution_publish_handoff(
            self.project_dir,
            runtime_root=self.runtime_dir,
            target_channel="staging",
            target_environment="staging",
            release_manifest_path="api_server/static/dist/release_manifest.json",
        )
        record_release_distribution_publish_receipt(
            self.project_dir,
            runtime_root=self.runtime_dir,
            target_channel="staging",
            target_environment="staging",
            release_manifest_path="api_server/static/dist/release_manifest.json",
            target_id=str(publish_handoff["delivery_publish_targets"][0]),
            status="published",
            external_reference="staging-artifact-2026-04-18",
            artifact_url="artifact://release-validation/staging/web-staging-001",
            operator="producer_a",
            published_at="2026-04-18T11:10:00Z",
            notes=["history report fixture"],
        )
        record_release_promotion_event(
            self.project_dir,
            runtime_root=self.runtime_dir,
            target_channel="staging",
            target_environment="staging",
            release_manifest_path="api_server/static/dist/release_manifest.json",
            approvers=["qa_lead", "tech_lead", "producer"],
            providers=["codex"],
            mode="advisory",
            decision="approved",
            executed_by="producer_a",
            note="history report ready",
            signoff_source="portal_manual",
        )
        write_release_live_dispatch_audit(
            self.project_dir,
            artifact_dir="logs/reports/release_live_ci",
            preflight={
                "schema_version": "1.0",
                "status": "passed",
                "ready": True,
                "workflow": "release-live-gates.yml",
                "repo": "sossossal/cim-comm-soc",
                "ref": "main",
                "dispatch_inputs": {
                    "target_channel": "staging",
                    "target_environment": "staging",
                    "artifact_dir": "logs/reports/release_live_ci",
                },
            },
            dispatch_result={
                "schema_version": "1.0",
                "ok": True,
                "status": "warning",
                "summary": "workflow_dispatch accepted for sossossal/cim-comm-soc@main",
                "repo": "sossossal/cim-comm-soc",
                "workflow": "release-live-gates.yml",
                "ref": "main",
                "wait": True,
                "token_source": "GH_TOKEN",
                "run": {
                    "id": 9001,
                    "number": 42,
                    "status": "completed",
                    "conclusion": "success",
                    "html_url": "https://github.com/sossossal/cim-comm-soc/actions/runs/9001",
                },
            },
            request_auth={
                "status": "passed",
                "actor_id": "release_manager",
                "token_id": "token-001",
                "reason": "accepted",
            },
            triggered_by="release_manager",
        )

        history = build_release_promotion_history(
            self.project_dir,
            runtime_root=self.runtime_dir,
            decision="approved",
            target_channel="staging",
            executed_by="producer_a",
        )
        report = build_release_promotion_history_report(history)

        self.assertIn("# Release Promotion History", report)
        self.assertIn("## Latest Record", report)
        self.assertIn("## Distribution", report)
        self.assertIn("Release Delivery Readiness:", report)
        self.assertIn("## Delivery Readiness Next Actions", report)
        self.assertNotIn("distribution_signing_handoff", report)
        self.assertIn("Distribution Publish Receipts: passed / completed=1/1 / missing=none / failed=none", report)
        self.assertIn("Publish Receipt Follow-up Required: False", report)
        self.assertIn("## Latest Live CI", report)
        self.assertIn("Release Live CI: passed / summary=ci_gate=passed / lanes=4 / signoffs=passed", report)
        self.assertIn("## Live CI Runtime Assembly", report)
        self.assertIn("## Live CI Event Stream", report)
        self.assertIn("Path: release_live_ci_events.json / source=local_replay", report)
        self.assertIn("Route: local_replay / route_id=local_replay:staging:staging", report)
        self.assertIn("Workflow Step Results: logs/reports/release_live_ci/release_live_ci_workflow_steps.json", report)
        self.assertIn("Live CI Failed Workflow Steps: none", report)
        self.assertIn("lane_reported [passed] / scope=runtime_lane / step=- / lane=portal_click_smoke", report)
        self.assertIn("Workflow Step (run_full_live_validation): status=passed / outcome=success", report)
        self.assertIn("## Latest Dispatch Audit", report)
        self.assertIn("workflow_dispatch accepted for sossossal/cim-comm-soc@main", report)
        self.assertIn("Audit Path: logs/reports/release_live_ci/release_live_dispatch.json", report)
        self.assertIn("Release Live Dispatch: warning / summary=workflow_dispatch accepted for sossossal/cim-comm-soc@main", report)
        self.assertIn("## Recent Records", report)
        self.assertIn("delivery_readiness=", report)
        self.assertIn("readiness_actions=", report)

    def test_release_promotion_history_report_uses_persisted_dispatch_audit_when_audit_file_is_missing(self):
        self._prepare_runtime(channel="staging")
        record_release_promotion_event(
            self.project_dir,
            runtime_root=self.runtime_dir,
            target_channel="staging",
            target_environment="staging",
            release_manifest_path="api_server/static/dist/release_manifest.json",
            approvers=["qa_lead", "tech_lead", "producer"],
            providers=["codex"],
            mode="advisory",
            decision="approved",
            executed_by="producer_a",
            note="persist dispatch audit",
            signoff_source="portal_manual",
        )
        for root in [self.runtime_dir, self.project_dir]:
            audit_path = root / "logs" / "reports" / "release_live_ci" / "release_live_dispatch.json"
            if audit_path.exists():
                audit_path.unlink()

        history = build_release_promotion_history(
            self.project_dir,
            runtime_root=self.runtime_dir,
            decision="approved",
            target_channel="staging",
            executed_by="producer_a",
        )
        report = build_release_promotion_history_report(history)

        self.assertEqual(history["latest_dispatch_audit"]["path"], "logs/reports/release_live_ci/release_live_dispatch.json")
        self.assertEqual(history["latest_dispatch_audit"]["status"], "warning")
        self.assertIn("## Latest Dispatch Audit", report)
        self.assertIn("workflow_dispatch accepted for sossossal/cim-comm-soc@main", report)

    def test_release_promotion_history_report_surfaces_review_followup_actions(self):
        history = build_release_promotion_history_report({
            "items": [{
                "record_id": "promotion_followup_001",
                "decision": "blocked",
                "target_channel": "staging",
                "target_environment": "staging",
                "plan_snapshot": {
                    "target_channel": "staging",
                    "target_environment": "staging",
                    "review_bundle": {
                        "feature": {
                            "feature_id": "feature-001",
                            "feature_status": "returned",
                            "blockers": ["attach final screenshot"],
                        },
                        "change_summary": ["prepare staging review"],
                        "changed_paths": ["README.md"],
                        "acceptance_checklist": [{"label": "smoke", "status": "ready"}],
                    },
                },
            }]
        })

        self.assertIn("## Review Follow-up Actions", history)
        self.assertIn("feature_status: status=blocked", history)
        self.assertIn("feature_blockers: status=blocked", history)

    def test_record_release_promotion_rejects_approved_when_plan_is_blocked(self):
        self._prepare_runtime(channel="staging")

        with self.assertRaisesRegex(ValueError, "cannot record approved/promoted"):
            record_release_promotion_event(
                self.project_dir,
                runtime_root=self.runtime_dir,
                target_channel="release",
                target_environment="production",
                release_manifest_path="api_server/static/dist/release_manifest.json",
                approvers=["qa_lead", "tech_lead"],
                providers=["codex"],
                mode="strict",
                decision="approved",
                executed_by="producer_a",
                note="should fail",
                signoff_source="portal_manual",
            )

    def test_record_release_promotion_rejects_unauthorized_actor(self):
        self._prepare_runtime(channel="staging")

        with self.assertRaisesRegex(ValueError, "release promotion authorization failed"):
            record_release_promotion_event(
                self.project_dir,
                runtime_root=self.runtime_dir,
                target_channel="staging",
                target_environment="staging",
                release_manifest_path="api_server/static/dist/release_manifest.json",
                approvers=["qa_lead", "tech_lead", "producer"],
                providers=["codex"],
                mode="advisory",
                decision="approved",
                executed_by="intruder",
                note="unauthorized record",
                signoff_source="portal_manual",
            )

    def test_release_promotion_history_api_shape(self):
        self._prepare_runtime(channel="staging")

        client = TestClient(app)
        record_response = client.post(
            "/release-promotion/record",
            json={
                "project_path": str(self.project_dir),
                "target_channel": "staging",
                "target_environment": "staging",
                "release_manifest_path": "api_server/static/dist/release_manifest.json",
                "approvers": ["qa_lead", "tech_lead", "producer"],
                "providers": ["codex"],
                "mode": "advisory",
                "decision": "approved",
                "executed_by": "producer_a",
                "note": "api record",
                "signoff_source": "portal_manual",
            },
        )
        self.assertEqual(record_response.status_code, 200)
        record_payload = record_response.json()
        readiness_status = record_payload["record"]["release_delivery_readiness_status"]
        readiness_action = record_payload["record"]["release_delivery_readiness_next_actions"][0]["action_id"]
        history_response = client.get(
            "/release-promotion/history",
            params={
                "project_path": str(self.project_dir),
                "decision": "approved",
                "target_channel": "staging",
                "executed_by": "producer_a",
                "live_ci_status": "passed",
                "delivery_readiness_status": readiness_status,
                "readiness_action": readiness_action,
                "dispatch_status": "warning",
                "dispatch_follow_up": "clear",
                "dispatch_run_status": "completed",
                "dispatch_run_conclusion": "success",
                "limit": 5,
            },
        )

        self.assertEqual(record_payload["record"]["decision"], "approved")
        self.assertEqual(record_payload["history"]["latest_record"]["executed_by"], "producer_a")
        self.assertEqual(record_payload["record"]["authorization"]["status"], "passed")
        self.assertEqual(record_payload["record"]["request_auth"]["status"], "passed")
        self.assertEqual(record_payload["record"]["request_auth"]["mode"], "local_only")
        self.assertEqual(record_payload["record"]["request_auth"]["scheme"], "local")
        self.assertEqual(record_payload["project_path"], f"{self.project_dir.resolve().as_posix()}/")

        self.assertEqual(history_response.status_code, 200)
        history_payload = history_response.json()
        self.assertEqual(history_payload["schema_version"], "1.0")
        self.assertEqual(history_payload["matched_count"], 1)
        self.assertEqual(history_payload["live_ci_status_filter"], "passed")
        self.assertEqual(history_payload["delivery_readiness_status_filter"], readiness_status)
        self.assertEqual(history_payload["readiness_action_filter"], readiness_action)
        self.assertEqual(history_payload["dispatch_status_filter"], "warning")
        self.assertEqual(history_payload["dispatch_follow_up_filter"], "clear")
        self.assertEqual(history_payload["dispatch_run_status_filter"], "completed")
        self.assertEqual(history_payload["dispatch_run_conclusion_filter"], "success")
        self.assertEqual(history_payload["items"][0]["decision"], "approved")
        self.assertEqual(history_payload["items"][0]["plan_snapshot"]["schema_version"], "1.1")
        self.assertEqual(history_payload["items"][0]["authorization"]["status"], "passed")
        self.assertEqual(history_payload["items"][0]["request_auth"]["status"], "passed")
        self.assertEqual(history_payload["items"][0]["release_live_ci_status"], "passed")
        self.assertEqual(history_payload["items"][0]["release_delivery_readiness_status"], readiness_status)
        self.assertEqual(
            history_payload["items"][0]["release_delivery_readiness_next_actions"][0]["action_id"],
            readiness_action,
        )
        self.assertEqual(history_payload["items"][0]["release_live_dispatch_status"], "warning")
        self.assertEqual(
            history_payload["items"][0]["release_live_ci_workflow_steps"][0]["step_id"],
            "export_runner_baseline",
        )
        self.assertEqual(history_payload["items"][0]["release_live_ci_failed_workflow_steps"], [])

    def test_release_promotion_history_api_supports_failed_workflow_step_filter(self):
        self._prepare_runtime(channel="staging")
        release_live_ci_summary_path = self.runtime_dir / "logs" / "reports" / "release_live_ci" / "release_live_ci_summary.json"
        project_release_live_ci_summary_path = self.project_dir / "logs" / "reports" / "release_live_ci" / "release_live_ci_summary.json"
        for summary_path in [release_live_ci_summary_path, project_release_live_ci_summary_path]:
            summary_payload = json.loads(summary_path.read_text(encoding="utf-8"))
            summary_payload["status"] = "warning"
            summary_payload["summary"] = "ci_gate=warning / lanes=4 / signoffs=passed"
            summary_payload["ci_gate"]["status"] = "warning"
            summary_payload["workflow_steps"][1]["status"] = "warning"
            summary_payload["workflow_steps"][1]["outcome"] = "failure"
            summary_payload["workflow_steps"][1]["message"] = "portal click smoke failed"
            summary_path.write_text(json.dumps(summary_payload, ensure_ascii=False, indent=2), encoding="utf-8")

        record_release_promotion_event(
            self.project_dir,
            runtime_root=self.runtime_dir,
            target_channel="release",
            target_environment="production",
            release_manifest_path="api_server/static/dist/release_manifest.json",
            approvers=["qa_lead", "tech_lead", "producer", "ops"],
            providers=["codex"],
            mode="advisory",
            decision="blocked",
            executed_by="ops_a",
            note="api failed workflow step filter",
            signoff_source="ops_review",
        )

        client = TestClient(app)
        response = client.get(
            "/release-promotion/history",
            params={
                "project_path": str(self.project_dir),
                "decision": "blocked",
                "target_channel": "release",
                "executed_by": "ops_a",
                "live_ci_status": "warning",
                "dispatch_status": "warning",
                "dispatch_follow_up": "clear",
                "dispatch_run_status": "completed",
                "dispatch_run_conclusion": "success",
                "failed_workflow_step": "run_full_live_validation",
                "limit": 5,
            },
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["matched_count"], 1)
        self.assertEqual(payload["live_ci_status_filter"], "warning")
        self.assertEqual(payload["dispatch_status_filter"], "warning")
        self.assertEqual(payload["dispatch_follow_up_filter"], "clear")
        self.assertEqual(payload["dispatch_run_status_filter"], "completed")
        self.assertEqual(payload["dispatch_run_conclusion_filter"], "success")
        self.assertEqual(payload["failed_workflow_step_filter"], "run_full_live_validation")
        self.assertEqual(payload["items"][0]["release_live_ci_failed_workflow_steps"], ["run_full_live_validation"])

    def test_release_promotion_history_report_endpoint_returns_markdown(self):
        self._prepare_runtime(channel="staging")
        client = TestClient(app)
        client.post(
            "/release-promotion/record",
            json={
                "project_path": str(self.project_dir),
                "target_channel": "staging",
                "target_environment": "staging",
                "release_manifest_path": "api_server/static/dist/release_manifest.json",
                "approvers": ["qa_lead", "tech_lead", "producer"],
                "providers": ["codex"],
                "mode": "advisory",
                "decision": "approved",
                "executed_by": "producer_a",
                "note": "api history report",
                "signoff_source": "portal_manual",
            },
        )

        response = client.get(
            "/release-promotion/history-report",
            params={
                "project_path": str(self.project_dir),
                "decision": "approved",
                "target_channel": "staging",
                "executed_by": "producer_a",
                "live_ci_status": "passed",
                "dispatch_status": "warning",
                "dispatch_follow_up": "clear",
                "dispatch_run_status": "completed",
                "dispatch_run_conclusion": "success",
                "failed_workflow_step": "",
            },
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["report_name"], "release_promotion_history.md")
        self.assertIn("# Release Promotion History", payload["report_content"])
        self.assertIn("live_ci_status=passed", payload["report_content"])
        self.assertIn("dispatch_status=warning", payload["report_content"])
        self.assertIn("dispatch_follow_up=clear", payload["report_content"])
        self.assertIn("dispatch_run_status=completed", payload["report_content"])
        self.assertIn("dispatch_run_conclusion=success", payload["report_content"])
        self.assertIn("## Latest Record", payload["report_content"])
        self.assertIn("## Distribution", payload["report_content"])
        self.assertIn("## Latest Live CI", payload["report_content"])
        self.assertIn("## Live CI Runtime Assembly", payload["report_content"])
        self.assertIn("Route: local_replay / route_id=local_replay:staging:staging", payload["report_content"])
        self.assertIn("Release Live CI: passed / summary=ci_gate=passed / lanes=4 / signoffs=passed", payload["report_content"])
        self.assertEqual(payload["history"]["items"][0]["release_live_ci_status"], "passed")
        self.assertEqual(payload["history"]["items"][0]["decision"], "approved")

    def test_release_promotion_history_api_rejects_unauthorized_actor(self):
        self._prepare_runtime(channel="staging")

        client = TestClient(app)
        response = client.post(
            "/release-promotion/record",
            json={
                "project_path": str(self.project_dir),
                "target_channel": "staging",
                "target_environment": "staging",
                "release_manifest_path": "api_server/static/dist/release_manifest.json",
                "approvers": ["qa_lead", "tech_lead", "producer"],
                "providers": ["codex"],
                "mode": "advisory",
                "decision": "approved",
                "executed_by": "intruder",
                "note": "api auth fail",
                "signoff_source": "portal_manual",
            },
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("release promotion authorization failed", response.json()["detail"])

    def test_release_promotion_history_api_requires_release_write_token_when_configured(self):
        self._prepare_runtime(channel="staging")

        client = TestClient(app)
        payload = {
            "project_path": str(self.project_dir),
            "target_channel": "staging",
            "target_environment": "staging",
            "release_manifest_path": "api_server/static/dist/release_manifest.json",
            "approvers": ["qa_lead", "tech_lead", "producer"],
            "providers": ["codex"],
            "mode": "advisory",
            "decision": "approved",
            "executed_by": "producer_a",
            "note": "api token gate",
            "signoff_source": "portal_manual",
        }

        with patch.dict(os.environ, {"GODOT_AGENT_RELEASE_WRITE_TOKEN": "release-secret"}, clear=False):
            blocked_response = client.post("/release-promotion/record", json=payload)
            allowed_response = client.post(
                "/release-promotion/record",
                json=payload,
                headers={"Authorization": "Bearer release-secret"},
            )

        self.assertEqual(blocked_response.status_code, 400)
        self.assertIn("release write request authentication failed", blocked_response.json()["detail"])

        self.assertEqual(allowed_response.status_code, 200)
        allowed_payload = allowed_response.json()
        self.assertEqual(allowed_payload["record"]["request_auth"]["status"], "passed")
        self.assertEqual(allowed_payload["record"]["request_auth"]["mode"], "token")
        self.assertEqual(allowed_payload["record"]["request_auth"]["scheme"], "bearer")
        self.assertEqual(allowed_payload["record"]["request_auth"]["header_name"], "authorization")
        self.assertTrue(allowed_payload["record"]["request_auth"]["token_configured"])
        self.assertTrue(allowed_payload["record"]["request_auth"]["token_present"])
        self.assertFalse(allowed_payload["record"]["request_auth"]["session_tracked"])


if __name__ == "__main__":
    unittest.main()

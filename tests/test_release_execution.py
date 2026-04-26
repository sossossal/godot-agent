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

from agent_system.tools.release_execution import (
    build_release_execution_report,
    build_release_execution_status,
    rollback_release_execution,
    run_release_execution,
)
from agent_system.tools.release_distribution import (
    export_release_distribution_archive,
    export_release_distribution_bundle,
    export_release_distribution_install_smoke,
    export_release_distribution_publish_handoff,
    record_release_distribution_publish_receipt,
)
from agent_system.tools.release_live_runner_baseline import default_release_live_runner_baseline_report_path
from agent_system.tools.release_promotion_history import record_release_promotion_event
from agent_system.contracts import RELEASE_EXECUTION_STATUS_SCHEMA_VERSION
from api_server.main import app
from tools.dispatch_release_live_gates import write_release_live_dispatch_audit


class ReleaseExecutionTestCase(unittest.TestCase):
    def setUp(self):
        self.project_dir = project_root / "tests" / ".tmp_release_execution_project"
        self.runtime_dir = project_root / "tests" / ".tmp_release_execution_runtime"
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
            ],
            "rules": [
                {
                    "rule_id": "execution_dry_run_any",
                    "action": "release_execution",
                    "operations": ["dry_run"],
                    "channels": ["qa", "staging", "release"],
                    "roles": ["producer", "ops", "release_manager"],
                    "allow_without_actor": True,
                },
                {
                    "rule_id": "execution_rollout_qa_staging",
                    "action": "release_execution",
                    "operations": ["canary", "full_rollout"],
                    "channels": ["qa", "staging"],
                    "roles": ["producer", "ops", "release_manager"],
                },
                {
                    "rule_id": "execution_rollout_release",
                    "action": "release_execution",
                    "operations": ["canary", "full_rollout"],
                    "channels": ["release"],
                    "roles": ["ops", "release_manager"],
                },
                {
                    "rule_id": "execution_rollback_any",
                    "action": "release_execution",
                    "operations": ["rollback"],
                    "channels": ["qa", "staging", "release"],
                    "roles": ["ops", "release_manager"],
                },
                {
                    "rule_id": "promotion_non_blocking_qa_staging",
                    "action": "promotion_record",
                    "decisions": ["approved", "promoted"],
                    "channels": ["qa", "staging"],
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
        token_id: str = "staging_release_manager",
        actor_ids: list[str] | None = None,
        action: str = "release_execution",
        actions: list[str] | None = None,
        target_channel: str = "staging",
        target_environment: str = "staging",
        allow_local_without_token: bool = False,
        expires_at: str = "2099-01-01T00:00:00Z",
        session_id: str = "staging-session-001",
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
        reports_dir = self.runtime_dir / "logs" / "reports"
        reports_dir.mkdir(parents=True, exist_ok=True)
        (self.project_dir / "docs" / "支持矩阵与分发说明.md").write_text(
            "# Support Matrix\n\n- release execution fixture\n",
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
                "feature_status": "approved",
            },
            "change_summary": ["prepare execution"],
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
                "screenshot_diff_ratio": 0.0125,
                "max_screenshot_diff_ratio": 0.05,
                "metrics": {"scene_load_ms": 300, "fps": 60.0, "memory_peak_mb": 140.0},
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
        doctor_report_payload = {
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
        }
        (reports_dir / "doctor_self_check.json").write_text(
            json.dumps(doctor_report_payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        bootstrap_payload = json.dumps({
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
                {"id": "create_venv", "status": "passed"},
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
        }, ensure_ascii=False, indent=2)
        (reports_dir / "clean_machine_bootstrap.json").write_text(bootstrap_payload, encoding="utf-8-sig")
        project_reports_dir = self.project_dir / "logs" / "reports"
        project_reports_dir.mkdir(parents=True, exist_ok=True)
        (project_reports_dir / "doctor_self_check.json").write_text(
            json.dumps(doctor_report_payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        (project_reports_dir / "clean_machine_bootstrap.json").write_text(bootstrap_payload, encoding="utf-8")
        runner_baseline_payload = json.dumps({
            "schema_version": "1.0",
            "generated_at": "2026-04-13T10:50:00Z",
            "status": "passed",
            "summary": "checks=10 / passed=10 / warning=0 / blocked=0",
            "report_path": default_release_live_runner_baseline_report_path(target_channel=channel),
            "target_channel": channel,
            "target_environment": "production" if channel == "release" else channel,
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
        }, ensure_ascii=False, indent=2)
        (reports_dir / f"release_live_runner_baseline_{channel}.json").write_text(
            runner_baseline_payload,
            encoding="utf-8",
        )
        (project_reports_dir / f"release_live_runner_baseline_{channel}.json").write_text(
            runner_baseline_payload,
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
        live_validation_payload = json.dumps({
            "schema_version": "1.1",
            "ok": True,
            "executed_at": executed_at,
            "release_binding": release_binding,
            "steps": live_validation_steps,
            "blocking_issues": [],
        }, ensure_ascii=False, indent=2)
        (reports_dir / "full_live_validation.json").write_text(live_validation_payload, encoding="utf-8")
        (project_reports_dir / "full_live_validation.json").write_text(live_validation_payload, encoding="utf-8")
        release_live_ci_dir = reports_dir / "release_live_ci"
        release_live_ci_dir.mkdir(parents=True, exist_ok=True)
        project_release_live_ci_dir = project_reports_dir / "release_live_ci"
        project_release_live_ci_dir.mkdir(parents=True, exist_ok=True)
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
        release_live_ci_summary_text = json.dumps(release_live_ci_summary, ensure_ascii=False, indent=2)
        release_live_ci_markdown = (
            "# Release Live CI Summary\n\n"
            "- portal_click_smoke [passed]\n"
            "- release_promotion_history_report_flow=passed\n"
        )
        (release_live_ci_dir / "release_live_ci_summary.json").write_text(release_live_ci_summary_text, encoding="utf-8")
        (release_live_ci_dir / "release_live_ci_summary.md").write_text(release_live_ci_markdown, encoding="utf-8")
        (project_release_live_ci_dir / "release_live_ci_summary.json").write_text(release_live_ci_summary_text, encoding="utf-8")
        (project_release_live_ci_dir / "release_live_ci_summary.md").write_text(release_live_ci_markdown, encoding="utf-8")
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

    def _record_approved_promotion(self) -> None:
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
            note="ready for rollout",
            signoff_source="portal_manual",
        )

    def test_release_execution_dry_run_persists_status_without_channel_binding(self):
        self._prepare_runtime(channel="staging")

        payload = run_release_execution(
            self.project_dir,
            runtime_root=self.runtime_dir,
            target_channel="staging",
            target_environment="staging",
            release_manifest_path="api_server/static/dist/release_manifest.json",
            approvers=["qa_lead", "tech_lead", "producer"],
            providers=["codex"],
            mode="advisory",
            operation="dry_run",
            note="rehearsal only",
        )

        self.assertEqual(payload["execution_status"]["schema_version"], RELEASE_EXECUTION_STATUS_SCHEMA_VERSION)
        self.assertEqual(payload["execution"]["operation"], "dry_run")
        self.assertFalse(payload["execution"]["channel_binding_changed"])
        self.assertEqual(payload["execution"]["rollout_percentage"], 0)
        self.assertEqual(payload["execution_status"]["channel_count"], 0)
        self.assertEqual(payload["execution"]["authorization"]["status"], "skipped")

    def test_release_execution_forces_strict_mode_for_release_target(self):
        self._prepare_runtime(channel="staging")

        payload = run_release_execution(
            self.project_dir,
            runtime_root=self.runtime_dir,
            target_channel="release",
            target_environment="production",
            release_manifest_path="api_server/static/dist/release_manifest.json",
            approvers=["qa_lead", "tech_lead", "producer", "ops"],
            providers=["codex"],
            mode="advisory",
            fail_on_warnings=False,
            operation="dry_run",
        )

        self.assertEqual(payload["plan"]["mode"], "strict")
        self.assertTrue(payload["plan"]["fail_on_warnings"])

    def test_release_execution_release_target_blocks_when_request_auth_posture_is_not_hardened(self):
        self._prepare_runtime(channel="release")

        payload = run_release_execution(
            self.project_dir,
            runtime_root=self.runtime_dir,
            target_channel="release",
            target_environment="production",
            release_manifest_path="api_server/static/dist/release_manifest.json",
            approvers=["qa_lead", "tech_lead", "producer", "ops"],
            providers=["codex"],
            mode="advisory",
            fail_on_warnings=False,
            operation="dry_run",
        )

        self.assertEqual(payload["plan"]["request_auth_posture"]["status"], "warning")
        self.assertEqual(payload["plan"]["request_auth_rotation_audit"]["status"], "warning")
        self.assertEqual(payload["plan"]["request_auth_identity_audit"]["status"], "blocked")
        self.assertIn("request_auth_posture_gate", payload["plan"]["blocking_checks"])
        self.assertIn("request_auth_rotation_audit_gate", payload["plan"]["blocking_checks"])
        self.assertIn("request_auth_identity_audit_gate", payload["plan"]["blocking_checks"])
        self.assertEqual(payload["execution"]["execution_status"], "blocked")
        self.assertIn("promotion_plan_ready", payload["execution"]["blocking_checks"])

    def test_release_execution_release_target_blocks_when_distribution_bundle_is_missing(self):
        self._prepare_runtime(channel="release")
        self._write_identity_registry(max_session_age_hours=72)
        self._write_request_auth_manifest(
            actions=["promotion_record", "release_execution"],
            target_channel="release",
            target_environment="production",
            issued_at=self._fresh_issued_at(),
        )

        payload = run_release_execution(
            self.project_dir,
            runtime_root=self.runtime_dir,
            target_channel="release",
            target_environment="production",
            release_manifest_path="api_server/static/dist/release_manifest.json",
            approvers=["qa_lead", "tech_lead", "producer", "ops"],
            providers=["codex"],
            mode="advisory",
            fail_on_warnings=False,
            operation="dry_run",
        )

        self.assertEqual(payload["plan"]["request_auth_posture"]["status"], "passed")
        self.assertEqual(payload["plan"]["request_auth_rotation_audit"]["status"], "passed")
        self.assertEqual(payload["plan"]["request_auth_identity_audit"]["status"], "passed")
        self.assertEqual(payload["plan"]["release_distribution_bundle"]["status"], "warning")
        self.assertIn("release_distribution_bundle_gate", payload["plan"]["blocking_checks"])
        self.assertEqual(payload["execution"]["execution_status"], "blocked")
        self.assertIn("promotion_plan_ready", payload["execution"]["blocking_checks"])

    def test_release_execution_release_target_blocks_when_distribution_install_smoke_is_missing(self):
        self._prepare_runtime(channel="release")
        self._write_identity_registry(max_session_age_hours=72)
        self._write_request_auth_manifest(
            actions=["promotion_record", "release_execution"],
            target_channel="release",
            target_environment="production",
            issued_at=self._fresh_issued_at(),
        )
        export_release_distribution_bundle(
            self.project_dir,
            runtime_root=self.runtime_dir,
            target_channel="release",
            target_environment="production",
            release_manifest_path="api_server/static/dist/release_manifest.json",
        )

        payload = run_release_execution(
            self.project_dir,
            runtime_root=self.runtime_dir,
            target_channel="release",
            target_environment="production",
            release_manifest_path="api_server/static/dist/release_manifest.json",
            approvers=["qa_lead", "tech_lead", "producer", "ops"],
            providers=["codex"],
            mode="advisory",
            fail_on_warnings=False,
            operation="dry_run",
        )

        self.assertEqual(payload["plan"]["release_distribution_bundle"]["status"], "warning")
        self.assertEqual(payload["plan"]["release_distribution_bundle"]["install_smoke_status"], "warning")
        self.assertIn("release_distribution_bundle_gate", payload["plan"]["blocking_checks"])
        self.assertEqual(payload["execution"]["execution_status"], "blocked")
        self.assertIn("promotion_plan_ready", payload["execution"]["blocking_checks"])

    def test_release_execution_release_target_blocks_when_distribution_archive_is_missing(self):
        self._prepare_runtime(channel="release")
        self._write_identity_registry(max_session_age_hours=72)
        self._write_request_auth_manifest(
            actions=["promotion_record", "release_execution"],
            target_channel="release",
            target_environment="production",
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

        payload = run_release_execution(
            self.project_dir,
            runtime_root=self.runtime_dir,
            target_channel="release",
            target_environment="production",
            release_manifest_path="api_server/static/dist/release_manifest.json",
            approvers=["qa_lead", "tech_lead", "producer", "ops"],
            providers=["codex"],
            mode="advisory",
            fail_on_warnings=False,
            operation="dry_run",
        )

        self.assertEqual(payload["plan"]["release_distribution_bundle"]["status"], "warning")
        self.assertEqual(payload["plan"]["release_distribution_bundle"]["install_smoke_status"], "passed")
        self.assertEqual(payload["plan"]["release_distribution_bundle"]["archive_status"], "warning")
        self.assertIn("release_distribution_bundle_gate", payload["plan"]["blocking_checks"])
        self.assertEqual(payload["execution"]["execution_status"], "blocked")
        self.assertIn("promotion_plan_ready", payload["execution"]["blocking_checks"])

    def test_release_execution_release_target_blocks_when_distribution_channel_index_is_missing(self):
        self._prepare_runtime(channel="release")
        self._write_identity_registry(max_session_age_hours=72)
        self._write_request_auth_manifest(
            actions=["promotion_record", "release_execution"],
            target_channel="release",
            target_environment="production",
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

        payload = run_release_execution(
            self.project_dir,
            runtime_root=self.runtime_dir,
            target_channel="release",
            target_environment="production",
            release_manifest_path="api_server/static/dist/release_manifest.json",
            approvers=["qa_lead", "tech_lead", "producer", "ops"],
            providers=["codex"],
            mode="advisory",
            fail_on_warnings=False,
            operation="dry_run",
        )

        self.assertEqual(payload["plan"]["release_distribution_bundle"]["status"], "warning")
        self.assertEqual(payload["plan"]["release_distribution_bundle"]["install_smoke_status"], "passed")
        self.assertEqual(payload["plan"]["release_distribution_bundle"]["archive_status"], "passed")
        self.assertEqual(payload["plan"]["release_distribution_bundle"]["channel_index_status"], "warning")
        self.assertIn("release_distribution_bundle_gate", payload["plan"]["blocking_checks"])
        self.assertEqual(payload["execution"]["execution_status"], "blocked")
        self.assertIn("promotion_plan_ready", payload["execution"]["blocking_checks"])

    def test_release_execution_status_exposes_clean_machine_bootstrap_summary(self):
        self._prepare_runtime(channel="staging")

        payload = build_release_execution_status(
            self.project_dir,
            runtime_root=self.runtime_dir,
            target_channel="staging",
        )
        report = build_release_execution_report(payload)

        self.assertEqual(payload["clean_machine_bootstrap"]["status"], "passed")
        self.assertEqual(payload["clean_machine_bootstrap"]["details"]["step_count"], 4)
        self.assertEqual(payload["clean_machine_bootstrap"]["details"]["blocking_issue_count"], 0)
        self.assertTrue(payload["clean_machine_bootstrap"]["details"]["doctor_report_exists"])
        self.assertEqual(payload["clean_machine_bootstrap"]["details"]["doctor_report_path"], "logs/reports/doctor_self_check.json")
        self.assertEqual(payload["clean_machine_bootstrap"]["details"]["doctor_check_count"], 6)
        self.assertEqual(payload["release_live_runner_baseline"]["status"], "passed")
        self.assertEqual(payload["release_live_runner_baseline"]["details"]["check_count"], 10)
        self.assertEqual(payload["release_live_runner_baseline"]["details"]["checks"][0]["check_id"], "chromium_browser")
        self.assertEqual(payload["full_live_validation"]["status"], "passed")
        self.assertIn(payload["request_auth_posture"]["status"], {"warning", "passed", "blocked"})
        self.assertIn(payload["request_auth_rotation_audit"]["status"], {"warning", "passed", "blocked"})
        self.assertIn(payload["request_auth_identity_audit"]["status"], {"warning", "passed", "blocked"})
        self.assertIn(payload["release_distribution_bundle"]["status"], {"warning", "passed", "blocked"})
        self.assertIn(payload["release_delivery_readiness"]["status"], {"warning", "passed", "blocked"})
        self.assertEqual(payload["release_delivery_readiness"]["component_count"], 3)
        self.assertEqual(payload["full_live_validation"]["details"]["lane_count"], 4)
        self.assertEqual(payload["full_live_validation"]["details"]["report_release_build_id"], "web-staging-001")
        self.assertEqual(payload["full_live_validation"]["details"]["release_binding_status"], "passed")
        self.assertEqual(
            payload["full_live_validation"]["details"]["step_statuses"][0]["artifact_paths"][0],
            "logs/live_sandbox_state.json",
        )
        self.assertEqual(
            payload["full_live_validation"]["details"]["step_statuses"][0]["report_path"],
            "logs/reports/full_live_validation_lanes/godot_live_sandbox.json",
        )
        self.assertEqual(payload["full_live_validation"]["details"]["lane_artifact_count"], 4)
        self.assertEqual(
            payload["full_live_validation"]["details"]["lane_artifacts"][2]["lane_id"],
            "portal_click_smoke",
        )
        self.assertEqual(
            payload["full_live_validation"]["details"]["lane_artifacts"][2]["report_path"],
            "logs/reports/full_live_validation_lanes/portal_click_smoke.json",
        )
        self.assertEqual(
            payload["full_live_validation"]["details"]["lane_artifacts"][2]["flow_statuses"]["release_promotion_history_report_flow"],
            "passed",
        )
        self.assertEqual(payload["release_live_ci_summary"]["status"], "passed")
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
            payload["release_live_ci_summary"]["details"]["summary_markdown_path"],
            "logs/reports/release_live_ci/release_live_ci_summary.md",
        )
        self.assertTrue(payload["release_live_ci_summary"]["details"]["summary_markdown_exists"])
        self.assertEqual(
            payload["release_live_ci_summary"]["details"]["workflow_step_results_path"],
            "logs/reports/release_live_ci/release_live_ci_workflow_steps.json",
        )
        self.assertEqual(
            payload["release_live_ci_summary"]["details"]["runtime_lanes"]["full_live_validation"][2]["flow_statuses"]["release_promotion_history_report_flow"],
            "passed",
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
            payload["release_live_ci_summary"]["details"]["workflow_steps"][0]["step_id"],
            "export_runner_baseline",
        )
        self.assertEqual(
            payload["release_live_ci_summary"]["details"]["workflow_steps"][1]["status"],
            "passed",
        )
        self.assertEqual(
            payload["release_live_ci_summary"]["details"]["dispatch_audit"]["path"],
            "logs/reports/release_live_ci/release_live_dispatch.json",
        )
        self.assertIn("## Clean Machine Bootstrap", report)
        self.assertIn("## Release Live Runner Baseline", report)
        self.assertIn("## Full Live Validation", report)
        self.assertIn("## Release Live CI Summary", report)
        self.assertIn("Report Binding:", report)
        self.assertIn("Binding Status: passed", report)
        self.assertIn("create_venv=passed", report)
        self.assertIn("Doctor Report: path=logs/reports/doctor_self_check.json", report)
        self.assertIn("CI Gate: status=passed / should_block=False", report)
        self.assertIn("Route: local_replay / route_id=local_replay:staging:staging", report)
        self.assertIn("Runner Profile: status=passed / profile=release_windows_runner", report)
        self.assertIn("Identity Boundary: status=passed / profile=staging_identity_boundary", report)
        self.assertIn("Path: release_live_ci_events.json / source=local_replay", report)
        self.assertIn("Dispatch Audit: status=warning / ready=True / attempted=True / completed=True", report)
        self.assertIn("Dispatch Summary: workflow_dispatch accepted for sossossal/cim-comm-soc@main", report)
        self.assertIn("lane_reported [passed] / scope=runtime_lane / step=- / lane=portal_click_smoke", report)
        self.assertIn("Summary Markdown: logs/reports/release_live_ci/release_live_ci_summary.md (exists=yes)", report)
        self.assertIn("Workflow Step Results: logs/reports/release_live_ci/release_live_ci_workflow_steps.json", report)
        self.assertIn("Lane (portal_click_smoke): status=passed", report)
        self.assertIn("Workflow Step (run_full_live_validation): status=passed / outcome=success", report)
        self.assertIn("## Release Request Auth Identity Audit", report)
        self.assertIn("## Release Distribution Bundle", report)
        self.assertIn("## Release Delivery Readiness", report)
        self.assertIn("Latest Execution Delivery Readiness:", report)
        self.assertIn("## Latest Execution Delivery Readiness Actions", report)
        self.assertIn("Next Actions:", report)
        self.assertIn("signing=skipped", report)
        self.assertIn("distribution_publish_handoff", report)
        self.assertIn("distribution_publish_receipts", report)
        self.assertIn("Distribution Publish Receipts: skipped", report)
        self.assertIn("Lane Report (portal_click_smoke):", report)
        self.assertIn("release_promotion_history_report_flow=passed", report)

    def test_release_execution_report_surfaces_review_followup_actions(self):
        report = build_release_execution_report({
            "items": [{
                "execution_id": "exec_followup",
                "operation": "dry_run",
                "target_channel": "staging",
                "target_environment": "staging",
                "execution_status": "warning",
                "plan_snapshot": {
                    "target_channel": "staging",
                    "target_environment": "staging",
                    "review_bundle": {
                        "feature": {
                            "feature_id": "feature-001",
                            "feature_status": "approved",
                            "blockers": ["attach final screenshot"],
                        },
                        "change_summary": ["prepare review"],
                        "changed_paths": ["README.md"],
                        "acceptance_checklist": [{"label": "smoke", "status": "ready"}],
                        "required_signoffs": ["qa_lead"],
                        "provided_signoffs": [],
                    },
                },
            }]
        })

        self.assertIn("## Review Follow-up Actions", report)
        self.assertIn("feature_blockers: status=blocked owner=feature_owner", report)
        self.assertIn("signoffs: status=warning owner=producer", report)

    def test_release_execution_report_surfaces_distribution_publish_receipts_after_publish_receipt(self):
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
            artifact_url="artifact://staging/web-staging-001",
            operator="release_manager",
            published_at="2026-04-18T10:10:00Z",
            notes=["staging publish receipt fixture"],
        )

        payload = build_release_execution_status(
            self.project_dir,
            runtime_root=self.runtime_dir,
            target_channel="staging",
        )
        report = build_release_execution_report(payload)

        self.assertEqual(payload["release_distribution_bundle"]["publish_receipts_status"], "passed")
        self.assertEqual(
            payload["release_distribution_bundle"]["publish_receipts_completed_targets"],
            [str(payload["release_distribution_bundle"]["delivery_publish_targets"][0])],
        )
        self.assertIn("Distribution Publish Receipts: passed / completed=1/1 / missing=none", report)
        self.assertNotIn("distribution publish receipts:", " ".join(payload["notes"]).lower())

    def test_release_execution_status_warns_when_full_live_validation_binding_mismatches_release_bundle(self):
        self._prepare_runtime(channel="staging")
        report_path = self.runtime_dir / "logs" / "reports" / "full_live_validation.json"
        report_payload = json.loads(report_path.read_text(encoding="utf-8"))
        report_payload["release_binding"]["manifest_path"] = "api_server/static/dist/web_other/release_manifest.json"
        report_path.write_text(json.dumps(report_payload, ensure_ascii=False, indent=2), encoding="utf-8")

        payload = build_release_execution_status(
            self.project_dir,
            runtime_root=self.runtime_dir,
            target_channel="staging",
        )

        self.assertEqual(payload["full_live_validation"]["status"], "warning")
        self.assertEqual(payload["full_live_validation"]["details"]["release_binding_status"], "warning")
        self.assertIn(
            "release_manifest_path_mismatch",
            payload["full_live_validation"]["details"]["release_binding_mismatches"],
        )

    def test_release_execution_status_accepts_absolute_full_live_validation_manifest_path(self):
        self._prepare_runtime(channel="staging")
        report_path = self.runtime_dir / "logs" / "reports" / "full_live_validation.json"
        report_payload = json.loads(report_path.read_text(encoding="utf-8"))
        report_payload["release_binding"]["manifest_path"] = str(
            self.runtime_dir / "api_server" / "static" / "dist" / "release_manifest.json"
        )
        report_path.write_text(json.dumps(report_payload, ensure_ascii=False, indent=2), encoding="utf-8")

        payload = build_release_execution_status(
            self.project_dir,
            runtime_root=self.runtime_dir,
            target_channel="staging",
        )

        self.assertEqual(payload["full_live_validation"]["details"]["release_binding_status"], "passed")
        self.assertEqual(payload["full_live_validation"]["details"]["release_binding_mismatches"], [])

    def test_release_execution_status_blocks_release_target_when_runner_baseline_report_is_missing(self):
        self._prepare_runtime(channel="release")
        (self.runtime_dir / "logs" / "reports" / "release_live_runner_baseline_release.json").unlink()
        (self.project_dir / "logs" / "reports" / "release_live_runner_baseline_release.json").unlink()

        payload = build_release_execution_status(
            self.project_dir,
            runtime_root=self.runtime_dir,
            target_channel="release",
        )
        report = build_release_execution_report(payload)

        self.assertEqual(payload["release_live_runner_baseline"]["status"], "blocked")
        self.assertEqual(payload["release_live_runner_baseline"]["details"]["blocked_check_count"], 1)
        self.assertIn("release live runner baseline", " ".join(payload["notes"]).lower())
        self.assertIn("## Release Live Runner Baseline", report)
        self.assertIn("Status: blocked", report)

    def test_canary_and_full_rollout_persist_channel_binding_after_approved_promotion(self):
        self._prepare_runtime(channel="staging")
        self._record_approved_promotion()

        canary_payload = run_release_execution(
            self.project_dir,
            runtime_root=self.runtime_dir,
            target_channel="staging",
            target_environment="staging",
            release_manifest_path="api_server/static/dist/release_manifest.json",
            approvers=["qa_lead", "tech_lead", "producer"],
            providers=["codex"],
            mode="advisory",
            operation="canary",
            rollout_percentage=15,
            executed_by="release_manager",
            note="canary stage",
        )
        full_payload = run_release_execution(
            self.project_dir,
            runtime_root=self.runtime_dir,
            target_channel="staging",
            target_environment="staging",
            release_manifest_path="api_server/static/dist/release_manifest.json",
            approvers=["qa_lead", "tech_lead", "producer"],
            providers=["codex"],
            mode="advisory",
            operation="full_rollout",
            executed_by="release_manager",
            note="full rollout",
        )

        self.assertEqual(canary_payload["execution"]["operation"], "canary")
        self.assertTrue(canary_payload["execution"]["channel_binding_changed"])
        self.assertEqual(canary_payload["execution"]["authorization"]["status"], "passed")
        self.assertEqual(canary_payload["channel_entry"]["rollout_stage"], "canary")
        self.assertEqual(canary_payload["channel_entry"]["rollout_percentage"], 15)
        self.assertEqual(canary_payload["channel_entry"]["active_public_url"], "/portal/dist/web_20260413/index.html")

        self.assertEqual(full_payload["execution"]["operation"], "full_rollout")
        self.assertEqual(full_payload["channel_entry"]["rollout_stage"], "full_rollout")
        self.assertEqual(full_payload["channel_entry"]["rollout_percentage"], 100)
        self.assertEqual(full_payload["channel_entry"]["active_public_url"], "/portal/dist/index.html")
        self.assertTrue((self.project_dir / "deployment" / "release_execution_status.json").exists())
        self.assertTrue((self.project_dir / "deployment" / "release_channels.json").exists())

    def test_rollback_marks_channel_as_rolled_back(self):
        self._prepare_runtime(channel="staging")
        self._record_approved_promotion()
        run_release_execution(
            self.project_dir,
            runtime_root=self.runtime_dir,
            target_channel="staging",
            target_environment="staging",
            release_manifest_path="api_server/static/dist/release_manifest.json",
            approvers=["qa_lead", "tech_lead", "producer"],
            providers=["codex"],
            mode="advisory",
            operation="full_rollout",
            executed_by="release_manager",
            note="full rollout",
        )

        payload = rollback_release_execution(
            self.project_dir,
            runtime_root=self.runtime_dir,
            target_channel="staging",
            target_environment="staging",
            release_manifest_path="api_server/static/dist/release_manifest.json",
            approvers=["qa_lead", "tech_lead", "producer"],
            providers=["codex"],
            mode="advisory",
            executed_by="ops_a",
            note="rollback to immutable version",
        )

        self.assertEqual(payload["execution"]["operation"], "rollback")
        self.assertEqual(payload["execution"]["rollout_stage"], "rolled_back")
        self.assertEqual(payload["execution"]["authorization"]["status"], "passed")
        self.assertEqual(payload["channel_entry"]["rollout_stage"], "rolled_back")
        self.assertEqual(payload["channel_entry"]["active_public_url"], "/portal/dist/web_20260413/index.html")

    def test_release_execution_rejects_unauthorized_canary_actor(self):
        self._prepare_runtime(channel="staging")
        self._record_approved_promotion()

        with self.assertRaisesRegex(ValueError, "release execution authorization failed"):
            run_release_execution(
                self.project_dir,
                runtime_root=self.runtime_dir,
                target_channel="staging",
                target_environment="staging",
                release_manifest_path="api_server/static/dist/release_manifest.json",
                approvers=["qa_lead", "tech_lead", "producer"],
                providers=["codex"],
                mode="advisory",
                operation="canary",
                rollout_percentage=15,
                executed_by="intruder",
                note="unauthorized canary",
            )

    def test_full_rollout_blocks_without_approved_promotion_history(self):
        self._prepare_runtime(channel="staging")

        payload = run_release_execution(
            self.project_dir,
            runtime_root=self.runtime_dir,
            target_channel="staging",
            target_environment="staging",
            release_manifest_path="api_server/static/dist/release_manifest.json",
            approvers=["qa_lead", "tech_lead", "producer"],
            providers=["codex"],
            mode="strict",
            operation="full_rollout",
            executed_by="release_manager",
            note="should block",
        )

        self.assertEqual(payload["execution"]["execution_status"], "blocked")
        self.assertTrue(payload["execution"]["should_block"])
        self.assertIn("promotion_history_ready", payload["execution"]["blocking_checks"])
        self.assertEqual(payload["execution_status"]["channel_count"], 0)

    def test_release_execution_api_shape(self):
        self._prepare_runtime(channel="staging")
        self._record_approved_promotion()

        client = TestClient(app)
        run_response = client.post(
            "/release-execution/run",
            json={
                "project_path": str(self.project_dir),
                "target_channel": "staging",
                "target_environment": "staging",
                "release_manifest_path": "api_server/static/dist/release_manifest.json",
                "approvers": ["qa_lead", "tech_lead", "producer"],
                "providers": ["codex"],
                "mode": "advisory",
                "operation": "canary",
                "rollout_percentage": 20,
                "executed_by": "release_manager",
            },
        )
        status_response = client.get(
            "/release-execution/status",
            params={
                "project_path": str(self.project_dir),
                "target_channel": "staging",
                "operation": "canary",
                "executed_by": "release_manager",
            },
        )
        report_response = client.get(
            "/release-execution/report",
            params={
                "project_path": str(self.project_dir),
                "target_channel": "staging",
                "operation": "canary",
                "executed_by": "release_manager",
            },
        )

        self.assertEqual(run_response.status_code, 200)
        run_payload = run_response.json()
        self.assertEqual(run_payload["execution"]["operation"], "canary")
        self.assertEqual(run_payload["execution"]["request_auth"]["status"], "passed")
        self.assertEqual(run_payload["execution"]["request_auth"]["mode"], "local_only")
        self.assertEqual(run_payload["execution"]["request_auth"]["scheme"], "local")
        self.assertIn(run_payload["execution"]["release_delivery_readiness_status"], {"warning", "passed", "blocked"})
        self.assertEqual(
            run_payload["execution"]["release_delivery_readiness_next_action_count"],
            len(run_payload["execution"]["release_delivery_readiness_next_actions"]),
        )
        self.assertNotIn(
            "distribution_signing_handoff",
            [item["action_id"] for item in run_payload["execution"]["release_delivery_readiness_next_actions"]],
        )
        self.assertEqual(run_payload["project_path"], f"{self.project_dir.resolve().as_posix()}/")

        self.assertEqual(status_response.status_code, 200)
        status_payload = status_response.json()
        self.assertEqual(status_payload["schema_version"], RELEASE_EXECUTION_STATUS_SCHEMA_VERSION)
        self.assertEqual(status_payload["matched_execution_count"], 1)
        self.assertEqual(status_payload["latest_execution"]["executed_by"], "release_manager")
        self.assertEqual(status_payload["clean_machine_bootstrap"]["status"], "passed")
        self.assertIn(status_payload["release_live_runner_baseline"]["status"], {"passed", "warning", "blocked"})
        self.assertIn(status_payload["full_live_validation"]["status"], {"passed", "warning"})
        self.assertIn(status_payload["full_live_validation"]["details"]["release_binding_status"], {"passed", "warning"})
        self.assertIn(status_payload["request_auth_posture"]["status"], {"warning", "passed", "blocked"})
        self.assertIn(status_payload["request_auth_rotation_audit"]["status"], {"warning", "passed", "blocked"})
        self.assertIn(status_payload["request_auth_identity_audit"]["status"], {"warning", "passed", "blocked"})
        self.assertIn(status_payload["release_distribution_bundle"]["status"], {"warning", "passed", "blocked"})
        self.assertEqual(status_payload["latest_execution"]["authorization"]["status"], "passed")
        self.assertEqual(status_payload["latest_execution"]["request_auth"]["status"], "passed")
        self.assertEqual(
            status_payload["latest_execution"]["release_delivery_readiness_status"],
            run_payload["execution"]["release_delivery_readiness_status"],
        )

        self.assertEqual(report_response.status_code, 200)
        report_payload = report_response.json()
        self.assertEqual(report_payload["report_name"], "release_execution_report.md")
        self.assertIn("## Clean Machine Bootstrap", report_payload["report_content"])
        self.assertIn("## Release Live Runner Baseline", report_payload["report_content"])
        self.assertIn("## Full Live Validation", report_payload["report_content"])
        self.assertIn("## Release Request Auth Posture", report_payload["report_content"])
        self.assertIn("## Release Request Auth Rotation Audit", report_payload["report_content"])
        self.assertIn("## Release Request Auth Identity Audit", report_payload["report_content"])
        self.assertIn("## Release Distribution Bundle", report_payload["report_content"])
        self.assertIn("Latest Execution Delivery Readiness:", report_payload["report_content"])
        self.assertIn("## Latest Execution Delivery Readiness Actions", report_payload["report_content"])
        self.assertIn("delivery_readiness=", report_payload["report_content"])
        self.assertIn("readiness_actions=", report_payload["report_content"])
        self.assertIn("Report Binding:", report_payload["report_content"])
        self.assertIn("Request Auth:", report_payload["report_content"])
        self.assertIn("Authorization:", report_payload["report_content"])
        self.assertEqual(report_payload["execution_status"]["clean_machine_bootstrap"]["status"], "passed")
        self.assertIn(report_payload["execution_status"]["release_live_runner_baseline"]["status"], {"passed", "warning", "blocked"})
        self.assertIn(report_payload["execution_status"]["full_live_validation"]["status"], {"passed", "warning"})
        self.assertEqual(
            report_payload["execution_status"]["full_live_validation"]["details"]["lane_artifacts"][2]["report_path"],
            "logs/reports/full_live_validation_lanes/portal_click_smoke.json",
        )

    def test_release_execution_api_rejects_unauthorized_actor(self):
        self._prepare_runtime(channel="staging")
        self._record_approved_promotion()

        client = TestClient(app)
        response = client.post(
            "/release-execution/run",
            json={
                "project_path": str(self.project_dir),
                "target_channel": "staging",
                "target_environment": "staging",
                "release_manifest_path": "api_server/static/dist/release_manifest.json",
                "approvers": ["qa_lead", "tech_lead", "producer"],
                "providers": ["codex"],
                "mode": "advisory",
                "operation": "canary",
                "rollout_percentage": 20,
                "executed_by": "intruder",
            },
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("release execution authorization failed", response.json()["detail"])

    def test_release_execution_api_requires_release_write_token_when_configured(self):
        self._prepare_runtime(channel="staging")
        self._record_approved_promotion()

        client = TestClient(app)
        payload = {
            "project_path": str(self.project_dir),
            "target_channel": "staging",
            "target_environment": "staging",
            "release_manifest_path": "api_server/static/dist/release_manifest.json",
            "approvers": ["qa_lead", "tech_lead", "producer"],
            "providers": ["codex"],
            "mode": "advisory",
            "operation": "canary",
            "rollout_percentage": 20,
            "executed_by": "release_manager",
        }

        with patch.dict(os.environ, {"GODOT_AGENT_RELEASE_WRITE_TOKEN": "release-secret"}, clear=False):
            blocked_response = client.post("/release-execution/run", json=payload)
            allowed_response = client.post(
                "/release-execution/run",
                json=payload,
                headers={"Authorization": "Bearer release-secret"},
            )

        self.assertEqual(blocked_response.status_code, 400)
        self.assertIn("release write request authentication failed", blocked_response.json()["detail"])

        self.assertEqual(allowed_response.status_code, 200)
        allowed_payload = allowed_response.json()
        self.assertEqual(allowed_payload["execution"]["request_auth"]["status"], "passed")
        self.assertEqual(allowed_payload["execution"]["request_auth"]["mode"], "token")
        self.assertEqual(allowed_payload["execution"]["request_auth"]["scheme"], "bearer")
        self.assertEqual(allowed_payload["execution"]["request_auth"]["header_name"], "authorization")
        self.assertTrue(allowed_payload["execution"]["request_auth"]["token_configured"])
        self.assertTrue(allowed_payload["execution"]["request_auth"]["token_present"])
        self.assertFalse(allowed_payload["execution"]["request_auth"]["session_tracked"])

    def test_release_execution_api_accepts_rotated_manifest_token_and_binds_actor(self):
        self._prepare_runtime(channel="staging")
        self._record_approved_promotion()
        self._write_request_auth_manifest()

        client = TestClient(app)
        base_payload = {
            "project_path": str(self.project_dir),
            "target_channel": "staging",
            "target_environment": "staging",
            "release_manifest_path": "api_server/static/dist/release_manifest.json",
            "approvers": ["qa_lead", "tech_lead", "producer"],
            "providers": ["codex"],
            "mode": "advisory",
            "operation": "canary",
            "rollout_percentage": 20,
            "executed_by": "release_manager",
        }

        blocked_response = client.post("/release-execution/run", json=base_payload)
        actor_mismatch_response = client.post(
            "/release-execution/run",
            json={**base_payload, "executed_by": "producer_a"},
            headers={"Authorization": "Bearer manifest-release-secret"},
        )
        allowed_response = client.post(
            "/release-execution/run",
            json=base_payload,
            headers={"Authorization": "Bearer manifest-release-secret"},
        )

        self.assertEqual(blocked_response.status_code, 400)
        self.assertIn("release write request authentication failed", blocked_response.json()["detail"])

        self.assertEqual(actor_mismatch_response.status_code, 400)
        self.assertIn("not allowed for executed_by=producer_a", actor_mismatch_response.json()["detail"])

        self.assertEqual(allowed_response.status_code, 200)
        allowed_payload = allowed_response.json()
        self.assertEqual(allowed_payload["execution"]["request_auth"]["status"], "passed")
        self.assertEqual(allowed_payload["execution"]["request_auth"]["mode"], "token")
        self.assertEqual(allowed_payload["execution"]["request_auth"]["token_source"], "manifest")
        self.assertEqual(allowed_payload["execution"]["request_auth"]["token_id"], "staging_release_manager")
        self.assertEqual(allowed_payload["execution"]["request_auth"]["session_id"], "staging-session-001")
        self.assertEqual(allowed_payload["execution"]["request_auth"]["issued_by"], "ops_a")
        self.assertEqual(allowed_payload["execution"]["request_auth"]["issued_at"], "2026-04-15T00:00:00Z")
        self.assertTrue(allowed_payload["execution"]["request_auth"]["session_tracked"])
        self.assertTrue(allowed_payload["execution"]["request_auth"]["issuer_registered"])
        self.assertEqual(allowed_payload["execution"]["request_auth"]["issuer_status"], "active")
        self.assertEqual(
            allowed_payload["execution"]["request_auth"]["issuer_subject_actor_ids"],
            ["producer_a", "release_manager", "ops_a"],
        )
        self.assertEqual(allowed_payload["execution"]["request_auth"]["required_actor_ids"], ["release_manager"])

    def test_release_execution_api_rejects_manifest_token_when_identity_registry_session_is_stale(self):
        self._prepare_runtime(channel="release")
        self._record_approved_promotion()
        self._write_identity_registry(max_session_age_hours=1)
        self._write_request_auth_manifest(
            target_channel="release",
            target_environment="production",
            session_id="release-session-001",
            issued_at="2020-01-01T00:00:00Z",
        )

        client = TestClient(app)
        response = client.post(
            "/release-execution/run",
            json={
                "project_path": str(self.project_dir),
                "target_channel": "release",
                "target_environment": "production",
                "release_manifest_path": "api_server/static/dist/release_manifest.json",
                "approvers": ["qa_lead", "tech_lead", "producer", "ops"],
                "providers": ["codex"],
                "mode": "advisory",
                "operation": "dry_run",
                "executed_by": "release_manager",
            },
            headers={"Authorization": "Bearer manifest-release-secret"},
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("older than 1h", response.json()["detail"])


if __name__ == "__main__":
    unittest.main()

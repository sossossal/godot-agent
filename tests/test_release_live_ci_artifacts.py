import hashlib
import json
import subprocess
import shutil
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path


project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from agent_system.tools.release_distribution import (
    export_release_distribution_handoff,
    export_release_distribution_publish_handoff,
    export_release_distribution_signing_handoff,
    record_release_distribution_publish_receipt,
)
from agent_system.tools.release_live_runner_baseline import default_release_live_runner_baseline_report_path
from agent_system.tools.release_request_auth import export_release_request_auth_identity_handoff
from tools.dispatch_release_live_gates import write_release_live_dispatch_audit
from tools.export_release_live_ci_artifacts import export_live_ci_artifacts, main

local_replay_script_path = project_root / "tools" / "run_release_live_gates_locally.ps1"


class ReleaseLiveCiArtifactsTestCase(unittest.TestCase):
    def setUp(self):
        self.project_dir = project_root / "tests" / ".tmp_release_live_ci_project"
        self.runtime_dir = project_root / "tests" / ".tmp_release_live_ci_runtime"
        self.output_dir = project_root / "tests" / ".tmp_release_live_ci_output"
        shutil.rmtree(self.project_dir, ignore_errors=True)
        shutil.rmtree(self.runtime_dir, ignore_errors=True)
        shutil.rmtree(self.output_dir, ignore_errors=True)
        self.project_dir.mkdir(parents=True, exist_ok=True)
        self.runtime_dir.mkdir(parents=True, exist_ok=True)

    def tearDown(self):
        shutil.rmtree(self.project_dir, ignore_errors=True)
        shutil.rmtree(self.runtime_dir, ignore_errors=True)
        shutil.rmtree(self.output_dir, ignore_errors=True)

    def _write_access_policy(self) -> None:
        policy = {
            "schema_version": "1.0",
            "actors": [
                {"actor_id": "ops_a", "roles": ["ops"]},
                {"actor_id": "release_manager", "roles": ["release_manager"]},
            ],
            "rules": [
                {
                    "rule_id": "execution_dry_run_any",
                    "action": "release_execution",
                    "operations": ["dry_run"],
                    "channels": ["qa", "staging", "release"],
                    "roles": ["ops", "release_manager"],
                    "allow_without_actor": True,
                },
                {
                    "rule_id": "promotion_planned_any",
                    "action": "promotion_record",
                    "decisions": ["planned"],
                    "channels": ["qa", "staging", "release"],
                    "roles": ["ops", "release_manager"],
                    "allow_without_actor": True,
                },
            ],
        }
        policy_path = self.project_dir / "deployment" / "release_access_policy.json"
        policy_path.parent.mkdir(parents=True, exist_ok=True)
        policy_path.write_text(json.dumps(policy, ensure_ascii=False, indent=2), encoding="utf-8")

    def _write_request_auth_manifest(self) -> None:
        token_digest = hashlib.sha256(b"release-live-ci-secret").hexdigest()
        manifest = {
            "schema_version": "1.0",
            "allow_local_without_token": False,
            "tokens": [
                {
                    "token_id": "release_ci_gate",
                    "token_sha256": token_digest,
                    "actions": ["promotion_record", "release_execution"],
                    "channels": ["release"],
                    "target_environments": ["production"],
                    "actor_ids": ["ops_a", "release_manager"],
                    "expires_at": "2099-01-01T00:00:00Z",
                    "session_id": "release-session-001",
                    "issued_by": "ops_a",
                    "issued_at": (
                        datetime.now(timezone.utc) - timedelta(hours=1)
                    ).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
                }
            ],
        }
        manifest_path = self.project_dir / "deployment" / "release_request_auth.json"
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    def _write_identity_registry(self) -> None:
        registry_path = self.project_dir / "deployment" / "release_identity_registry.json"
        registry_path.parent.mkdir(parents=True, exist_ok=True)
        registry_path.write_text(
            json.dumps(
                {
                    "schema_version": "1.0",
                    "issuers": [
                        {
                            "issuer_id": "ops_a",
                            "status": "active",
                            "channels": ["release"],
                            "target_environments": ["production"],
                            "subject_actor_ids": ["ops_a", "release_manager"],
                            "session_required": True,
                            "max_session_age_hours": 48,
                        }
                    ],
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

    def _write_runner_profile(self) -> None:
        profile_path = self.project_dir / "deployment" / "release_live_runner_profile.json"
        profile_path.parent.mkdir(parents=True, exist_ok=True)
        profile_path.write_text(
            json.dumps(
                {
                    "schema_version": "1.0",
                    "profiles": [
                        {
                            "profile_id": "release_windows_runner",
                            "target_channels": ["release"],
                            "target_environments": ["production"],
                            "required_runner_os": "Windows",
                            "required_runner_arches": ["x64"],
                            "required_runner_labels": ["self-hosted", "windows", "godot"],
                            "allowed_runner_names": [],
                        }
                    ],
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

    def _write_distribution_delivery_manifest(self) -> None:
        manifest_path = self.project_dir / "deployment" / "release_distribution_delivery.json"
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        manifest_path.write_text(
            json.dumps(
                {
                    "schema_version": "1.0",
                    "profiles": [
                        {
                            "profile_id": "release_external_windows",
                            "target_channels": ["release"],
                            "target_environments": ["production"],
                            "primary_installer": "portable_handoff",
                            "installer_types": ["portable_handoff", "archive_zip"],
                            "signing": {
                                "required": True,
                                "mode": "manual_pending",
                                "profile_id": "windows_release_codesign",
                            },
                            "publish_targets": [
                                {"target_id": "qa_handoff", "kind": "filesystem"},
                                {"target_id": "github_release_manual", "kind": "manual_release_channel"},
                            ],
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

    def _write_identity_boundary_manifest(self) -> None:
        manifest_path = self.project_dir / "deployment" / "release_identity_boundary.json"
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        manifest_path.write_text(
            json.dumps(
                {
                    "schema_version": "1.0",
                    "profiles": [
                        {
                            "profile_id": "release_identity_boundary",
                            "target_channels": ["release"],
                            "target_environments": ["production"],
                            "provider_mode": "project_manifest",
                            "provider_id": "release_request_auth_manifest",
                            "session_policy": {
                                "required": True,
                                "max_session_age_hours": 24,
                                "backend": "identity_registry",
                            },
                            "secret_rotation": {
                                "required": True,
                                "backend": "deployment_manifest",
                                "owner": "ops_release",
                                "rotation_window_days": 30,
                            },
                            "issuer_policy": "identity_registry_scoped",
                            "external_handoff": {
                                "required": True,
                                "mode": "manual_operator",
                                "target_id": "release_identity_intake",
                                "owner": "ops_release",
                            },
                        }
                    ],
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

    def _write_capability_registry(self) -> None:
        registry_path = self.project_dir / "deployment" / "release_capability_registry.json"
        registry_path.parent.mkdir(parents=True, exist_ok=True)
        registry_path.write_text(
            json.dumps(
                {
                    "schema_version": "1.0",
                    "registry_id": "release_control_plane_capabilities",
                    "capabilities": [
                        {
                            "capability_id": "release_live_ci_summary_read",
                            "label": "Release Live CI Summary",
                            "group": "release_runtime",
                            "surface_types": ["command", "gateway_method"],
                            "risk_level": "medium",
                            "requires_actor": False,
                            "requires_request_auth": False,
                            "default_enabled": True,
                            "optional_heavy": False,
                            "sandbox_profile": "read_only",
                            "artifact_contracts": ["release_live_ci_summary", "release_artifact_manifest"],
                            "entrypoints": [
                                "/release-live-ci/summary",
                                "/release-live-ci/summary-report",
                                "/release-artifact-manifest",
                            ],
                            "owners": ["qa_lead", "ops"],
                        },
                    ],
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

    def _prepare_runtime(self) -> None:
        (self.project_dir / "project.godot").write_text("; test project\n", encoding="utf-8")
        (self.project_dir / "README.md").write_text("# temp project\n", encoding="utf-8")
        (self.project_dir / "docs").mkdir(parents=True, exist_ok=True)
        (self.project_dir / "tools").mkdir(parents=True, exist_ok=True)
        (self.project_dir / "tests").mkdir(parents=True, exist_ok=True)
        (self.project_dir / "scenes" / "levels").mkdir(parents=True, exist_ok=True)
        (self.project_dir / "scripts").mkdir(parents=True, exist_ok=True)
        (self.project_dir / "docs" / "支持矩阵与分发说明.md").write_text(
            "# Support Matrix\n\n- release live ci fixture\n",
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
        self._write_request_auth_manifest()
        self._write_identity_registry()
        self._write_runner_profile()
        self._write_distribution_delivery_manifest()
        self._write_identity_boundary_manifest()
        self._write_capability_registry()

        dist_dir = self.runtime_dir / "api_server" / "static" / "dist"
        dist_dir.mkdir(parents=True, exist_ok=True)
        release_dir = dist_dir / "web_20260417"
        release_dir.mkdir(parents=True, exist_ok=True)
        (release_dir / "qa_gate_report.md").write_text("# QA Gate\n", encoding="utf-8")
        (release_dir / "release_notes.md").write_text("# Release Notes\n", encoding="utf-8")
        (release_dir / "build.log").write_text("build ok\n", encoding="utf-8")
        (release_dir / "index.html").write_text("<html></html>\n", encoding="utf-8")

        manifest = {
            "schema_version": "1.0",
            "build_id": "web-release-001",
            "version": "0.1.0-release+1",
            "channel": "release",
            "preset_name": "Web",
            "platform": "web",
            "generated_at": "2026-04-17T10:00:00Z",
            "output_path": "api_server/static/dist/web_20260417/index.html",
            "release_dir": "api_server/static/dist/web_20260417",
            "release_url": "/portal/dist/index.html",
            "versioned_release_url": "/portal/dist/web_20260417/index.html",
            "build_log_path": "api_server/static/dist/web_20260417/build.log",
            "release_notes_path": "api_server/static/dist/web_20260417/release_notes.md",
            "release_manifest_path": "api_server/static/dist/web_20260417/release_manifest.json",
            "feature": {
                "schema_version": "1.0",
                "feature_id": "feature-release-live-ci",
                "owner": "ops",
                "priority": "high",
                "risk": "medium",
                "feature_status": "approved",
            },
            "change_summary": ["prepare live ci release evidence"],
            "acceptance_checklist": [{"label": "smoke", "status": "ready"}],
            "quality_gate": {
                "schema_version": "1.0",
                "passed": True,
                "channel": "release",
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
                "screenshot_diff_ratio": 0.01,
                "max_screenshot_diff_ratio": 0.05,
                "metrics": {"scene_load_ms": 275, "fps": 60.0, "memory_peak_mb": 128.0},
            },
            "files": [{"path": "index.html", "size": 13, "sha256": "abc"}],
            "rollback_hint": "restore web_20260417",
        }
        manifest_text = json.dumps(manifest, ensure_ascii=False, indent=2)
        (release_dir / "release_manifest.json").write_text(manifest_text, encoding="utf-8")
        (dist_dir / "release_manifest.json").write_text(manifest_text, encoding="utf-8")

        reports_dir = self.runtime_dir / "logs" / "reports"
        project_reports_dir = self.project_dir / "logs" / "reports"
        reports_dir.mkdir(parents=True, exist_ok=True)
        project_reports_dir.mkdir(parents=True, exist_ok=True)

        doctor_report_payload = {
            "schema_version": "1.0",
            "generated_at": "2026-04-17T10:45:00Z",
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
        bootstrap_payload = {
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
        }
        for reports_root in (reports_dir, project_reports_dir):
            (reports_root / "doctor_self_check.json").write_text(
                json.dumps(doctor_report_payload, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            (reports_root / "clean_machine_bootstrap.json").write_text(
                json.dumps(bootstrap_payload, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            (reports_root / "release_live_runner_baseline_release.json").write_text(
                json.dumps(
                    {
                        "schema_version": "1.0",
                        "generated_at": "2026-04-17T10:55:00Z",
                        "status": "passed",
                        "summary": "checks=10 / passed=10 / warning=0 / blocked=0",
                        "report_path": default_release_live_runner_baseline_report_path(target_channel="release"),
                        "target_channel": "release",
                        "target_environment": "production",
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
                        "allowed_runner_names": [],
                        "check_count": 10,
                        "passed_check_count": 10,
                        "warning_check_count": 0,
                        "blocked_check_count": 0,
                        "blocking_checks": [],
                        "warning_checks": [],
                        "checks": [],
                        "recommendations": [],
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )

        executed_at = "2026-04-17T11:00:00Z"
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
        for reports_root in (reports_dir, project_reports_dir):
            lane_reports_dir = reports_root / "full_live_validation_lanes"
            lane_reports_dir.mkdir(parents=True, exist_ok=True)
            live_validation_steps = []
            for lane in [
                {
                    "id": "godot_live_sandbox",
                    "label": "Godot Live Sandbox",
                    "status": "passed",
                    "summary": "sandbox ok",
                    "artifact_paths": ["logs/live_sandbox_state.json", "logs/api_server_8000.out"],
                },
                {
                    "id": "portal_dom_smoke",
                    "label": "Portal DOM Smoke",
                    "status": "passed",
                    "summary": "dom ok",
                    "artifact_paths": ["logs/test_artifacts/portal_browser_smoke_8012.html"],
                },
                {
                    "id": "portal_click_smoke",
                    "label": "Portal Click Smoke",
                    "status": "passed",
                    "summary": "click ok",
                    "artifact_paths": ["logs/test_artifacts/portal_click_chrome_8014.out"],
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
                    "artifact_paths": ["logs/remote_mcp_8766.out"],
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
            (reports_root / "full_live_validation.json").write_text(
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

    def _prepare_local_replay_files(self) -> Path:
        fake_godot = self.project_dir / "fake_godot.exe"
        fake_browser = self.project_dir / "fake_chrome.exe"
        fake_godot.write_text("godot\n", encoding="utf-8")
        fake_browser.write_text("chrome\n", encoding="utf-8")
        (self.project_dir / "config.yaml").write_text(
            f"godot:\n  executable_path: \"{fake_godot.as_posix()}\"\n",
            encoding="utf-8",
        )
        for relative_path, content in (
            ("tools/export_release_live_ci_artifacts.py", "# fixture\n"),
            ("tools/run_portal_browser_smoke.ps1", "Write-Output 'portal dom fixture'\n"),
            ("tools/run_portal_browser_click_smoke.py", "print('portal click fixture')\n"),
            ("tools/run_remote_mcp_live_smoke.ps1", "Write-Output 'remote mcp fixture'\n"),
        ):
            path = self.project_dir / relative_path
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")

        (self.project_dir / "tools" / "run_full_live_validation.ps1").write_text(
            """param(
    [string]$ReleaseManifestPath = "api_server/static/dist/release_manifest.json"
)

$ErrorActionPreference = "Stop"
$runtimeRoot = $env:RELEASE_LIVE_GATES_RUNTIME_ROOT
$projectRoot = $env:RELEASE_LIVE_GATES_PROJECT_ROOT
if ([string]::IsNullOrWhiteSpace($runtimeRoot)) {
    throw "RELEASE_LIVE_GATES_RUNTIME_ROOT not set"
}
if ([string]::IsNullOrWhiteSpace($projectRoot)) {
    throw "RELEASE_LIVE_GATES_PROJECT_ROOT not set"
}

$manifestPath = Join-Path $runtimeRoot $ReleaseManifestPath
$manifest = Get-Content $manifestPath -Raw | ConvertFrom-Json
$executedAt = "2026-04-17T11:30:00Z"
$releaseBinding = [ordered]@{
    status = "passed"
    manifest_source = "stable"
    manifest_path = $ReleaseManifestPath
    build_id = [string]$manifest.build_id
    version = [string]$manifest.version
    channel = [string]$manifest.channel
    generated_at = [string]$manifest.generated_at
    release_dir = [string]$manifest.release_dir
    output_path = [string]$manifest.output_path
    release_url = [string]$manifest.release_url
    versioned_release_url = [string]$manifest.versioned_release_url
}

$lanes = @(
    [ordered]@{
        id = "godot_live_sandbox"
        label = "Godot Live Sandbox"
        status = "passed"
        summary = "sandbox ok"
        artifact_paths = @("logs/live_sandbox_state.json", "logs/api_server_8000.out")
    },
    [ordered]@{
        id = "portal_dom_smoke"
        label = "Portal DOM Smoke"
        status = "passed"
        summary = "dom ok"
        artifact_paths = @("logs/test_artifacts/portal_browser_smoke_8012.html")
    },
    [ordered]@{
        id = "portal_click_smoke"
        label = "Portal Click Smoke"
        status = "passed"
        summary = "click ok"
        artifact_paths = @("logs/test_artifacts/portal_click_chrome_8014.out")
        flow_statuses = [ordered]@{
            flow = "passed"
            release_promotion_history_flow = "passed"
            release_promotion_history_report_flow = "passed"
        }
    },
    [ordered]@{
        id = "remote_mcp_live"
        label = "Remote MCP Live Smoke"
        status = "passed"
        summary = "remote ok"
        artifact_paths = @("logs/remote_mcp_8766.out")
    }
)

foreach ($root in @($runtimeRoot, $projectRoot)) {
    $reportsDir = Join-Path $root "logs\\reports"
    $laneDir = Join-Path $reportsDir "full_live_validation_lanes"
    New-Item -ItemType Directory -Force -Path $reportsDir | Out-Null
    New-Item -ItemType Directory -Force -Path $laneDir | Out-Null
    $steps = @()
    foreach ($lane in $lanes) {
        $relativeLanePath = "logs/reports/full_live_validation_lanes/$($lane.id).json"
        $lanePayload = [ordered]@{
            schema_version = "1.0"
            lane_id = $lane.id
            label = $lane.label
            status = $lane.status
            summary = $lane.summary
            executed_at = $executedAt
            report_path = $relativeLanePath
            full_report_path = "logs/reports/full_live_validation.json"
            artifact_paths = @($lane.artifact_paths)
            release_binding = $releaseBinding
            details = [ordered]@{
                flow_statuses = $lane.flow_statuses
            }
        }
        $lanePayload | ConvertTo-Json -Depth 8 | Set-Content -Path (Join-Path $laneDir ($lane.id + ".json")) -Encoding utf8
        $steps += [ordered]@{
            id = $lane.id
            label = $lane.label
            status = $lane.status
            summary = $lane.summary
            report_path = $relativeLanePath
            artifact_paths = @($lane.artifact_paths)
            details = [ordered]@{
                artifact_paths = @($lane.artifact_paths)
                report_path = $relativeLanePath
                flow_statuses = $lane.flow_statuses
            }
        }
    }
    [ordered]@{
        schema_version = "1.1"
        ok = $true
        executed_at = $executedAt
        release_binding = $releaseBinding
        steps = $steps
        blocking_issues = @()
    } | ConvertTo-Json -Depth 8 | Set-Content -Path (Join-Path $reportsDir "full_live_validation.json") -Encoding utf8
}
""",
            encoding="utf-8",
        )
        return fake_browser

    def _run_local_replay(self, *extra_args: str) -> dict:
        completed = subprocess.run(
            [
                "powershell",
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(local_replay_script_path),
                "-ProjectRoot",
                str(self.project_dir),
                "-RuntimeRoot",
                str(self.runtime_dir),
                "-PythonCommand",
                sys.executable,
                *extra_args,
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
        if completed.returncode != 0:
            self.fail(f"local replay script failed: {completed.stdout}\n{completed.stderr}")
        return json.loads(completed.stdout)

    def _write_dispatch_audit(self, *, channel: str, environment: str) -> None:
        preflight = {
            "schema_version": "1.0",
            "status": "passed",
            "ready": True,
            "workflow": "release-live-gates.yml",
            "repo": "sossossal/cim-comm-soc",
            "ref": "main",
            "dispatch_inputs": {
                "target_channel": channel,
                "target_environment": environment,
            },
        }
        write_release_live_dispatch_audit(
            self.project_dir,
            artifact_dir="logs/reports/release_live_ci",
            preflight=preflight,
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
        preflight_dir = self.runtime_dir / "logs" / "reports" / "release_live_ci"
        preflight_dir.mkdir(parents=True, exist_ok=True)
        (preflight_dir / "release_live_dispatch_preflight.json").write_text(
            json.dumps(preflight, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        (preflight_dir / "release_live_dispatch_preflight.md").write_text(
            "# Release Live Dispatch Preflight\n\n- Status: passed\n",
            encoding="utf-8",
        )

    @unittest.skipUnless(sys.platform.startswith("win"), "requires PowerShell")
    def test_export_live_ci_artifacts_separates_automation_gate_from_manual_signoffs(self):
        self._prepare_runtime()
        self._write_dispatch_audit(channel="release", environment="production")
        export_release_distribution_handoff(
            self.project_dir,
            runtime_root=self.runtime_dir,
            target_channel="release",
            target_environment="production",
            release_manifest_path="api_server/static/dist/release_manifest.json",
        )
        export_release_distribution_signing_handoff(
            self.project_dir,
            runtime_root=self.runtime_dir,
            target_channel="release",
            target_environment="production",
            release_manifest_path="api_server/static/dist/release_manifest.json",
        )
        export_release_distribution_publish_handoff(
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
            target_id="qa_handoff",
            status="published",
            external_reference="qa-handoff-001",
            operator="ops_release",
            artifact_url="file:///qa_handoff/web-release-001.zip",
        )
        record_release_distribution_publish_receipt(
            self.project_dir,
            runtime_root=self.runtime_dir,
            target_channel="release",
            target_environment="production",
            release_manifest_path="api_server/static/dist/release_manifest.json",
            target_id="github_release_manual",
            status="published",
            external_reference="gh-release-001",
            operator="ops_release",
            artifact_url="https://example.invalid/github_release_manual/web-release-001.zip",
        )
        export_release_request_auth_identity_handoff(
            self.project_dir,
            runtime_root=self.runtime_dir,
            target_channel="release",
            target_environment="production",
            release_manifest_path="api_server/static/dist/release_manifest.json",
        )
        workflow_step_results_path = self.runtime_dir / "logs" / "reports" / "release_live_ci_workflow_steps.json"
        workflow_step_results_path.parent.mkdir(parents=True, exist_ok=True)
        workflow_step_results_path.write_text(
            json.dumps(
                [
                    {
                        "step_id": "export_runner_baseline",
                        "label": "Export release-live runner baseline",
                        "outcome": "success",
                        "always_run": False,
                    },
                    {
                        "step_id": "run_full_live_validation",
                        "label": "Run full live validation",
                        "outcome": "success",
                        "always_run": False,
                    },
                ],
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        fixture_dir = self.runtime_dir / "logs" / "reports"
        fixture_dir.mkdir(parents=True, exist_ok=True)
        (fixture_dir / "release_live_fixture.json").write_text(
            json.dumps({"schema_version": "1.0", "fixture_scope": "full"}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        (fixture_dir / "release_live_fixture.md").write_text("# Release Live Fixture\n", encoding="utf-8")

        result = export_live_ci_artifacts(
            self.output_dir,
            project_root=self.project_dir,
            runtime_root=self.runtime_dir,
            target_channel="release",
            target_environment="production",
            release_manifest_path="api_server/static/dist/release_manifest.json",
            approvers=[],
            providers=["codex"],
            fail_on_warnings=True,
            workflow_step_results_path=workflow_step_results_path,
        )

        summary = result["summary"]
        self.assertEqual(summary["ci_gate"]["status"], "passed")
        self.assertFalse(summary["ci_gate"]["should_block"])
        self.assertEqual(summary["human_signoffs"]["status"], "warning")
        self.assertEqual(summary["human_signoffs"]["missing_signoffs"], ["qa_lead", "tech_lead", "producer", "ops"])
        self.assertEqual(summary["promotion"]["status"], "blocked")
        self.assertTrue(summary["promotion"]["should_block"])
        self.assertTrue(summary["execution"]["should_block"])
        self.assertEqual(summary["invocation"]["source"], "cli")
        self.assertEqual(summary["invocation"]["providers"], ["codex"])
        self.assertEqual(summary["runtime_assembly"]["route_kind"], "local_replay")
        self.assertEqual(summary["runtime_assembly"]["invocation_source"], "cli")
        self.assertEqual(summary["runtime_assembly"]["route_id"], "local_replay:release:production")
        self.assertEqual(summary["runtime_assembly"]["session_id"], "web-release-001")
        self.assertEqual(summary["runtime_assembly"]["runner_profile"]["profile_id"], "release_windows_runner")
        self.assertEqual(
            summary["runtime_assembly"]["identity_boundary"]["profile_id"],
            "release_identity_boundary",
        )
        self.assertEqual(summary["runtime_gates"]["release_live_runner_baseline_status"], "passed")
        self.assertEqual(summary["runtime_gates"]["release_live_runner_profile_id"], "release_windows_runner")
        self.assertEqual(summary["runtime_gates"]["release_live_runner_name"], "godot-release-01")
        self.assertEqual(summary["runtime_gates"]["release_live_runner_labels"], ["self-hosted", "windows", "godot"])
        self.assertEqual(summary["runtime_gates"]["distribution_delivery_status"], "warning")
        self.assertEqual(summary["runtime_gates"]["distribution_delivery_profile_id"], "release_external_windows")
        self.assertEqual(summary["runtime_gates"]["distribution_signing_handoff_status"], "passed")
        self.assertEqual(summary["runtime_gates"]["distribution_publish_handoff_status"], "passed")
        self.assertEqual(summary["runtime_gates"]["distribution_publish_receipts_status"], "passed")
        self.assertEqual(summary["runtime_gates"]["identity_boundary_status"], "passed")
        self.assertEqual(summary["runtime_gates"]["identity_boundary_profile_id"], "release_identity_boundary")
        self.assertEqual(summary["runtime_gates"]["identity_handoff_status"], "passed")
        self.assertEqual(summary["runtime_gates"]["identity_handoff_target_id"], "release_identity_intake")
        self.assertTrue((self.output_dir / "runtime_reports" / "full_live_validation.json").exists())
        self.assertTrue((self.output_dir / "runtime_reports" / "release_live_runner_baseline_release.json").exists())
        self.assertTrue((self.output_dir / "deployment" / "release_live_runner_profile.json").exists())
        self.assertTrue((self.output_dir / "deployment" / "release_distribution_delivery.json").exists())
        self.assertTrue((self.output_dir / "deployment" / "release_identity_boundary.json").exists())
        self.assertTrue((self.output_dir / "release_live_ci_summary.md").exists())
        self.assertTrue((self.output_dir / "release_live_dispatch.json").exists())
        self.assertTrue((self.output_dir / "release_live_ci_events.json").exists())
        self.assertTrue((self.output_dir / "release_promotion_history.md").exists())
        self.assertTrue((self.output_dir / "runtime_reports" / "release_distribution_bundle_release.json").exists())
        self.assertTrue((self.output_dir / "release_distribution_archive" / "release_distribution_bundle.zip").exists())
        self.assertTrue((self.output_dir / "release_distribution_channel" / "latest.json").exists())
        self.assertTrue((self.output_dir / "release_distribution_handoff" / "install_release_handoff.ps1").exists())
        self.assertTrue((self.output_dir / "release_distribution_signing" / "distribution_signing_manifest.json").exists())
        self.assertTrue((self.output_dir / "release_distribution_publish" / "distribution_publish_manifest.json").exists())
        self.assertTrue((self.output_dir / "release_distribution_publish_receipts" / "publish_receipts_manifest.json").exists())
        self.assertTrue((self.output_dir / "release_request_auth_identity_handoff" / "identity_boundary_handoff_manifest.json").exists())
        exported_summary = json.loads((self.output_dir / "release_live_ci_summary.json").read_text(encoding="utf-8"))
        artifact_manifest = json.loads((self.output_dir / "artifact_manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(artifact_manifest["schema_version"], "1.0")
        self.assertEqual(artifact_manifest["contract_versions"]["release_artifact_manifest"], "1.0")
        self.assertEqual(exported_summary["ci_gate"]["evaluated_check_count"], 8)
        self.assertEqual(exported_summary["release_build_id"], "web-release-001")
        self.assertEqual(artifact_manifest["release_build_id"], "web-release-001")
        self.assertEqual(artifact_manifest["release_version"], exported_summary["release_version"])
        self.assertEqual(artifact_manifest["release_channel"], "release")
        self.assertEqual(artifact_manifest["release_summary"]["build_id"], "web-release-001")
        self.assertEqual(exported_summary["report_files"]["summary_markdown"], "release_live_ci_summary.md")
        self.assertEqual(exported_summary["report_files"]["promotion_history_report"], "release_promotion_history.md")
        self.assertEqual(exported_summary["report_files"]["workflow_step_results"], "release_live_ci_workflow_steps.json")
        self.assertEqual(exported_summary["report_files"]["release_live_fixture"], "release_live_fixture.json")
        self.assertEqual(exported_summary["report_files"]["release_live_fixture_report"], "release_live_fixture.md")
        self.assertEqual(exported_summary["report_files"]["event_stream"], "release_live_ci_events.json")
        self.assertEqual(exported_summary["report_files"]["dispatch_preflight"], "release_live_dispatch_preflight.json")
        self.assertEqual(exported_summary["report_files"]["dispatch_preflight_report"], "release_live_dispatch_preflight.md")
        self.assertEqual(exported_summary["report_files"]["release_delivery_readiness"], "release_delivery_readiness_release.json")
        self.assertEqual(exported_summary["report_files"]["release_delivery_readiness_report"], "release_delivery_readiness_release.md")
        self.assertEqual(exported_summary["runtime_assembly"]["route_kind"], "local_replay")
        self.assertEqual(exported_summary["runtime_assembly"]["invocation_source"], "cli")
        self.assertEqual(exported_summary["event_stream"]["path"], "release_live_ci_events.json")
        self.assertEqual(exported_summary["event_stream"]["latest_event_type"], "run_finished")
        self.assertIn(exported_summary["release_delivery_readiness"]["status"], {"passed", "warning", "blocked"})
        self.assertIn(artifact_manifest["release_delivery_readiness"]["status"], {"passed", "warning", "blocked"})
        self.assertIn("release_delivery_readiness_release.json", artifact_manifest["generated_files"])
        self.assertIn("release_delivery_readiness_release.md", artifact_manifest["generated_files"])
        self.assertIn("release_live_fixture.json", artifact_manifest["generated_files"])
        self.assertIn("release_live_fixture.md", artifact_manifest["generated_files"])
        self.assertIn(artifact_manifest["execution_delivery_readiness"]["status"], {"passed", "warning", "blocked"})
        self.assertIn(
            "external_distribution_delivery",
            artifact_manifest["execution_delivery_readiness"]["next_action_ids"],
        )
        self.assertEqual(
            artifact_manifest["execution_delivery_readiness"]["next_action_count"],
            len(artifact_manifest["execution_delivery_readiness"]["next_action_ids"]),
        )
        self.assertEqual(exported_summary["dispatch_audit"]["path"], "release_live_dispatch.json")
        self.assertTrue((self.output_dir / "release_live_dispatch_preflight.json").exists())
        self.assertTrue((self.output_dir / "release_live_dispatch_preflight.md").exists())
        self.assertTrue(any(
            item.get("lane_id") == "portal_click_smoke"
            for item in exported_summary["event_stream"]["events"]
        ))
        self.assertEqual(exported_summary["workflow_steps"][0]["step_id"], "export_runner_baseline")
        self.assertEqual(exported_summary["workflow_steps"][0]["status"], "passed")
        self.assertEqual(exported_summary["workflow_steps"][1]["step_id"], "run_full_live_validation")
        self.assertEqual(exported_summary["workflow_steps"][1]["status"], "passed")
        self.assertEqual(
            exported_summary["runtime_lanes"]["full_live_validation"][2]["flow_statuses"]["release_promotion_history_report_flow"],
            "passed",
        )
        self.assertTrue((self.output_dir / "release_live_ci_workflow_steps.json").exists())
        markdown_summary = (self.output_dir / "release_live_ci_summary.md").read_text(encoding="utf-8")
        self.assertIn("# Release Live CI Summary", markdown_summary)
        self.assertIn("## Invocation", markdown_summary)
        self.assertIn("## Runtime Assembly", markdown_summary)
        self.assertIn("## Event Stream", markdown_summary)
        self.assertIn("## Workflow Dispatch Audit", markdown_summary)
        self.assertIn("## Artifact Manifest", markdown_summary)
        self.assertIn("## Live Validation Lanes", markdown_summary)
        self.assertIn("## Workflow Steps", markdown_summary)
        self.assertIn("Source: cli / mode=strict / fail_on_warnings=True", markdown_summary)
        self.assertIn("Route: local_replay / route_id=local_replay:release:production", markdown_summary)
        self.assertIn("Identity Boundary: status=passed / profile=release_identity_boundary", markdown_summary)
        self.assertIn("Runner Profile: status=passed / profile=release_windows_runner", markdown_summary)
        self.assertIn("contracts=release_live_ci_summary, release_artifact_manifest", markdown_summary)
        self.assertIn("entrypoints=/release-live-ci/summary, /release-live-ci/summary-report, /release-artifact-manifest", markdown_summary)
        self.assertIn("signing_handoff=passed", markdown_summary)
        self.assertIn("publish_handoff=passed", markdown_summary)
        self.assertIn("publish_receipts=passed", markdown_summary)
        self.assertIn("delivery=warning (profile=release_external_windows)", markdown_summary)
        self.assertIn("identity_boundary=passed (profile=release_identity_boundary)", markdown_summary)
        self.assertIn("identity_handoff=passed (target=release_identity_intake)", markdown_summary)
        self.assertIn("CI Gate: status=passed / should_block=False / fail_on_warnings=True", markdown_summary)
        self.assertIn("Path: release_live_ci_events.json / source=live_ci_export", markdown_summary)
        self.assertIn("Dispatch Audit: status=warning / ready=True / attempted=True / completed=True", markdown_summary)
        self.assertIn("Dispatch Summary: workflow_dispatch accepted for sossossal/cim-comm-soc@main", markdown_summary)
        self.assertIn("Contract: 1.0 / build=web-release-001", markdown_summary)
        self.assertIn("full_live_validation_lanes=4", markdown_summary)
        self.assertIn("Execution Delivery Readiness: status=", markdown_summary)
        self.assertIn("ids=external_identity_boundary, self_hosted_release_workflow, external_distribution_delivery", markdown_summary)
        self.assertIn("lane_reported [passed] / scope=runtime_lane / step=- / lane=portal_click_smoke", markdown_summary)
        self.assertIn("labels=self-hosted, windows, godot", markdown_summary)
        self.assertIn("Missing: qa_lead, tech_lead, producer, ops", markdown_summary)
        self.assertIn("portal_click_smoke [passed]", markdown_summary)
        self.assertIn("run_full_live_validation [passed]", markdown_summary)
        self.assertIn("release_promotion_history_report_flow=passed", markdown_summary)
        self.assertIn("# Release Promotion History", (self.output_dir / "release_promotion_history.md").read_text(encoding="utf-8"))

    @unittest.skipUnless(sys.platform.startswith("win"), "requires PowerShell")
    def test_main_returns_nonzero_when_automation_gate_blocks(self):
        self._prepare_runtime()
        export_release_distribution_handoff(
            self.project_dir,
            runtime_root=self.runtime_dir,
            target_channel="release",
            target_environment="production",
            release_manifest_path="api_server/static/dist/release_manifest.json",
        )
        (self.runtime_dir / "logs" / "reports" / "full_live_validation.json").unlink()
        (self.project_dir / "logs" / "reports" / "full_live_validation.json").unlink()
        shutil.rmtree(self.runtime_dir / "logs" / "reports" / "full_live_validation_lanes", ignore_errors=True)
        shutil.rmtree(self.project_dir / "logs" / "reports" / "full_live_validation_lanes", ignore_errors=True)

        exit_code = main(
            [
                "--project-root",
                str(self.project_dir),
                "--runtime-root",
                str(self.runtime_dir),
                "--output-dir",
                str(self.output_dir),
                "--channel",
                "release",
                "--target-environment",
                "production",
                "--release-manifest-path",
                "api_server/static/dist/release_manifest.json",
                "--providers",
                "codex",
                "--fail-on-warnings",
                "--fail-on-blockers",
            ]
        )

        self.assertEqual(exit_code, 1)
        summary = json.loads((self.output_dir / "release_live_ci_summary.json").read_text(encoding="utf-8"))
        self.assertTrue(summary["ci_gate"]["should_block"])
        self.assertIn("full_live_validation_lane", summary["ci_gate"]["blocking_checks"])

    @unittest.skipUnless(sys.platform.startswith("win"), "requires PowerShell")
    def test_export_live_ci_artifacts_blocks_when_runner_baseline_report_is_missing(self):
        self._prepare_runtime()
        export_release_distribution_handoff(
            self.project_dir,
            runtime_root=self.runtime_dir,
            target_channel="release",
            target_environment="production",
            release_manifest_path="api_server/static/dist/release_manifest.json",
        )
        (self.runtime_dir / "logs" / "reports" / "release_live_runner_baseline_release.json").unlink()
        (self.project_dir / "logs" / "reports" / "release_live_runner_baseline_release.json").unlink()

        result = export_live_ci_artifacts(
            self.output_dir,
            project_root=self.project_dir,
            runtime_root=self.runtime_dir,
            target_channel="release",
            target_environment="production",
            release_manifest_path="api_server/static/dist/release_manifest.json",
            approvers=[],
            providers=["codex"],
            fail_on_warnings=True,
        )

        summary = result["summary"]
        self.assertTrue(summary["ci_gate"]["should_block"])
        self.assertIn("release_live_runner_baseline_gate", summary["ci_gate"]["blocking_checks"])
        self.assertEqual(summary["runtime_gates"]["release_live_runner_baseline_status"], "")

    @unittest.skipUnless(sys.platform.startswith("win"), "requires PowerShell")
    def test_run_release_live_gates_locally_preview_lists_workflow_aligned_steps(self):
        self._prepare_runtime()
        fake_browser = self._prepare_local_replay_files()

        payload = self._run_local_replay(
            "-ArtifactDir",
            str(self.output_dir),
            "-BrowserPath",
            str(fake_browser),
            "-Preview",
        )

        self.assertTrue(payload["ok"])
        self.assertTrue(payload["preview"])
        self.assertFalse(payload["preflight"])
        self.assertIn(payload["preflight_status"], {"passed", "warning"})
        self.assertEqual(payload["preflight_checks"]["blocking_checks"], [])
        self.assertNotIn("release_manifest", payload["preflight_checks"]["blocking_checks"])
        self.assertEqual(payload["invocation_source"], "local_replay")
        self.assertEqual(
            [step["id"] for step in payload["steps"]],
            [
                "export_runner_baseline",
                "build_distribution_handoff",
                "build_distribution_signing_handoff",
                "build_distribution_publish_handoff",
                "build_request_auth_identity_handoff",
                "run_full_live_validation",
                "export_live_ci_artifacts",
            ],
        )
        self.assertTrue(payload["step_summary_path"].endswith("release_live_ci_step_summary.md"))

    @unittest.skipUnless(sys.platform.startswith("win"), "requires PowerShell")
    def test_run_release_live_gates_locally_preflight_blocks_missing_manifest(self):
        self._prepare_runtime()
        fake_browser = self._prepare_local_replay_files()
        (self.runtime_dir / "api_server" / "static" / "dist" / "release_manifest.json").unlink()

        completed = subprocess.run(
            [
                "powershell",
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(local_replay_script_path),
                "-ProjectRoot",
                str(self.project_dir),
                "-RuntimeRoot",
                str(self.runtime_dir),
                "-PythonCommand",
                sys.executable,
                "-ArtifactDir",
                str(self.output_dir),
                "-BrowserPath",
                str(fake_browser),
                "-Preflight",
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )

        self.assertEqual(completed.returncode, 1)
        payload = json.loads(completed.stdout)
        self.assertFalse(payload["ok"])
        self.assertTrue(payload["preflight"])
        self.assertEqual(payload["preflight_status"], "blocked")
        self.assertIn("release_manifest", payload["preflight_checks"]["blocking_checks"])
        manifest_check = next(
            item for item in payload["preflight_checks"]["checks"] if item["id"] == "release_manifest"
        )
        self.assertIn("-ReleaseManifestPath", manifest_check["remediation"])
        self.assertTrue(Path(payload["preflight_report_path"]).exists())
        self.assertTrue(Path(payload["preflight_markdown_path"]).exists())

    @unittest.skipUnless(sys.platform.startswith("win"), "requires PowerShell")
    def test_run_release_live_gates_locally_executes_release_replay_and_writes_step_summary(self):
        self._prepare_runtime()
        fake_browser = self._prepare_local_replay_files()

        payload = self._run_local_replay(
            "-ArtifactDir",
            str(self.output_dir),
            "-BrowserPath",
            str(fake_browser),
            "-Providers",
            "codex",
            "-FailOnWarnings",
        )

        self.assertTrue(payload["ok"])
        self.assertFalse(payload["preview"])
        self.assertEqual(payload["invocation_source"], "local_replay")
        self.assertTrue(Path(payload["summary_path"]).exists())
        self.assertTrue(Path(payload["summary_markdown_path"]).exists())
        self.assertTrue(Path(payload["step_summary_path"]).exists())
        self.assertTrue(Path(payload["workflow_step_results_path"]).exists())
        summary = json.loads(Path(payload["summary_path"]).read_text(encoding="utf-8"))
        self.assertEqual(summary["ci_gate"]["status"], "passed")
        self.assertFalse(summary["ci_gate"]["should_block"])
        self.assertEqual(summary["human_signoffs"]["status"], "warning")
        self.assertEqual(summary["invocation"]["source"], "local_replay")
        self.assertEqual(summary["invocation"]["providers"], ["codex"])
        self.assertEqual(summary["runtime_assembly"]["route_kind"], "local_replay")
        self.assertEqual(summary["runtime_assembly"]["invocation_source"], "local_replay")
        self.assertEqual(summary["runtime_assembly"]["route_id"], "local_replay:release:production")
        self.assertEqual(summary["runtime_assembly"]["session_id"], "web-release-001")
        self.assertEqual(summary["workflow_steps"][0]["step_id"], "export_runner_baseline")
        self.assertEqual(summary["workflow_steps"][-1]["step_id"], "run_full_live_validation")
        self.assertEqual(summary["workflow_steps"][-1]["status"], "passed")
        self.assertEqual(summary["event_stream"]["latest_event_type"], "run_finished")
        self.assertEqual(summary["runtime_gates"]["release_live_runner_baseline_status"], "passed")
        self.assertEqual(summary["runtime_gates"]["full_live_validation_status"], "passed")
        self.assertEqual(summary["runtime_gates"]["distribution_signing_handoff_status"], "passed")
        self.assertEqual(summary["runtime_gates"]["distribution_publish_handoff_status"], "passed")
        self.assertEqual(summary["runtime_gates"]["distribution_publish_receipts_status"], "warning")
        self.assertEqual(summary["runtime_gates"]["identity_handoff_status"], "passed")
        self.assertEqual(
            payload["summary_excerpt"]["runtime_lanes"]["full_live_validation"][2]["flow_statuses"]["release_promotion_history_report_flow"],
            "passed",
        )
        self.assertEqual(payload["summary_excerpt"]["runtime_assembly"]["route_kind"], "local_replay")
        self.assertEqual(payload["summary_excerpt"]["runtime_assembly"]["invocation_source"], "local_replay")
        self.assertEqual(payload["summary_excerpt"]["event_stream"]["latest_event_type"], "run_finished")
        self.assertEqual(payload["summary_excerpt"]["workflow_steps"][-1]["step_id"], "run_full_live_validation")
        self.assertEqual(payload["summary_excerpt"]["workflow_steps"][-1]["status"], "passed")
        step_summary = Path(payload["step_summary_path"]).read_text(encoding="utf-8")
        self.assertIn("# Release Live CI Summary", step_summary)
        self.assertIn("Source: local_replay / mode=strict / fail_on_warnings=True", step_summary)
        self.assertIn("## Runtime Assembly", step_summary)
        self.assertIn("Route: local_replay / route_id=local_replay:release:production", step_summary)
        self.assertIn("contracts=release_live_ci_summary, release_artifact_manifest", step_summary)
        self.assertIn("entrypoints=/release-live-ci/summary, /release-live-ci/summary-report, /release-artifact-manifest", step_summary)
        self.assertIn("## Workflow Steps", step_summary)
        self.assertIn("release_promotion_history_report_flow=passed", step_summary)

    @unittest.skipUnless(sys.platform.startswith("win"), "requires PowerShell")
    def test_run_release_live_gates_locally_still_exports_summary_after_preexport_failure(self):
        self._prepare_runtime()
        fake_browser = self._prepare_local_replay_files()
        (self.runtime_dir / "logs" / "reports" / "full_live_validation.json").unlink()
        (self.project_dir / "logs" / "reports" / "full_live_validation.json").unlink()
        shutil.rmtree(self.runtime_dir / "logs" / "reports" / "full_live_validation_lanes", ignore_errors=True)
        shutil.rmtree(self.project_dir / "logs" / "reports" / "full_live_validation_lanes", ignore_errors=True)
        (self.project_dir / "tools" / "run_full_live_validation.ps1").write_text(
            "Write-Error 'live validation fixture failure'`nexit 1`n",
            encoding="utf-8",
        )

        completed = subprocess.run(
            [
                "powershell",
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(local_replay_script_path),
                "-ProjectRoot",
                str(self.project_dir),
                "-RuntimeRoot",
                str(self.runtime_dir),
                "-PythonCommand",
                sys.executable,
                "-ArtifactDir",
                str(self.output_dir),
                "-BrowserPath",
                str(fake_browser),
                "-Providers",
                "codex",
                "-FailOnWarnings",
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )

        self.assertEqual(completed.returncode, 1)
        payload = json.loads(completed.stdout)
        self.assertFalse(payload["ok"])
        self.assertIn("run_full_live_validation", payload["failed_step_ids"])
        self.assertTrue(Path(payload["summary_path"]).exists())
        self.assertTrue(Path(payload["summary_markdown_path"]).exists())
        self.assertTrue(Path(payload["workflow_step_results_path"]).exists())
        summary = json.loads(Path(payload["summary_path"]).read_text(encoding="utf-8"))
        self.assertTrue(summary["ci_gate"]["should_block"])
        self.assertIn("full_live_validation_lane", summary["ci_gate"]["blocking_checks"])
        self.assertEqual(summary["runtime_assembly"]["route_kind"], "local_replay")
        self.assertEqual(summary["runtime_assembly"]["invocation_source"], "local_replay")
        self.assertEqual(summary["event_stream"]["latest_event_type"], "run_finished")
        self.assertEqual(summary["workflow_steps"][-1]["step_id"], "run_full_live_validation")
        self.assertEqual(summary["workflow_steps"][-1]["status"], "blocked")
        self.assertEqual(summary["workflow_steps"][-1]["outcome"], "failure")
        self.assertEqual(payload["summary_excerpt"]["workflow_steps"][-1]["status"], "blocked")
        self.assertEqual(payload["step_results"][-1]["step_id"], "export_live_ci_artifacts")
        self.assertEqual(payload["step_results"][-1]["status"], "blocked")
        step_summary = Path(payload["step_summary_path"]).read_text(encoding="utf-8")
        self.assertIn("## Runtime Assembly", step_summary)
        self.assertIn("## Workflow Steps", step_summary)
        self.assertIn("run_full_live_validation [blocked]", step_summary)


if __name__ == "__main__":
    unittest.main()

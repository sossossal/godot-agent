from __future__ import annotations

import os
import shutil
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from tools.dispatch_release_live_gates import (
    _pick_workflow_run,
    build_release_live_dispatch_audit,
    build_release_live_dispatch_audit_report_lines,
    build_release_live_dispatch_preflight,
    build_release_live_dispatch_preflight_report,
    build_workflow_dispatch_inputs,
    dispatch_release_live_gates_request,
    export_release_live_dispatch_preflight,
    infer_repo_from_remote_url,
    load_release_live_dispatch_audit,
    write_release_live_dispatch_audit,
)


class _Args:
    runner_labels = '["self-hosted","windows","godot"]'
    target_channel = "staging"
    target_environment = "staging"
    release_manifest_path = "api_server/static/dist/web_release_validation_ci/release_manifest.json"
    runner_profile_path = "deployment/release_live_runner_profile.json"
    approvers = "qa_lead,tech_lead"
    providers = "codex,openai_api"
    artifact_dir = "logs/reports/release_live_ci"
    fail_on_warnings = True


def test_infer_repo_from_remote_url_supports_https_and_ssh() -> None:
    assert infer_repo_from_remote_url("https://github.com/sossossal/cim-comm-soc.git") == "sossossal/cim-comm-soc"
    assert infer_repo_from_remote_url("git@github.com:sossossal/cim-comm-soc.git") == "sossossal/cim-comm-soc"


def test_build_workflow_dispatch_inputs_normalizes_labels_and_bool() -> None:
    inputs = build_workflow_dispatch_inputs(_Args())

    assert inputs["runner_labels"] == '["self-hosted", "windows", "godot"]'
    assert inputs["target_channel"] == "staging"
    assert inputs["target_environment"] == "staging"
    assert inputs["fail_on_warnings"] == "true"
    assert inputs["providers"] == "codex,openai_api"


def test_pick_workflow_run_prefers_recent_matching_dispatch() -> None:
    dispatched_after = datetime(2026, 4, 22, 18, 0, tzinfo=timezone.utc)
    matched = _pick_workflow_run(
        [
            {
                "id": 101,
                "event": "push",
                "head_branch": "main",
                "created_at": "2026-04-22T18:00:10Z",
            },
            {
                "id": 102,
                "event": "workflow_dispatch",
                "head_branch": "feature-branch",
                "created_at": "2026-04-22T18:00:20Z",
            },
            {
                "id": 103,
                "event": "workflow_dispatch",
                "head_branch": "main",
                "created_at": "2026-04-22T18:00:30Z",
            },
            {
                "id": 104,
                "event": "workflow_dispatch",
                "head_branch": "main",
                "created_at": "2026-04-22T18:01:00Z",
            },
        ],
        ref_name="main",
        dispatched_after=dispatched_after,
    )

    assert matched is not None
    assert matched["id"] == 104


def test_build_release_live_dispatch_preflight_reports_ready_when_workflow_and_token_exist() -> None:
    temp_project = Path(__file__).resolve().parent / ".tmp_dispatch_preflight"
    shutil.rmtree(temp_project, ignore_errors=True)
    try:
        workflow_path = temp_project / ".github" / "workflows" / "release-live-gates.yml"
        workflow_path.parent.mkdir(parents=True, exist_ok=True)
        workflow_path.write_text("on:\n  workflow_dispatch:\n", encoding="utf-8")

        with patch.dict(os.environ, {"GH_TOKEN": "secret-token"}, clear=False):
            payload = build_release_live_dispatch_preflight(
                temp_project,
                repo="sossossal/cim-comm-soc",
                ref="main",
                target_channel="staging",
                target_environment="staging",
            )

        assert payload["ready"] is True
        assert payload["workflow_exists"] is True
        assert payload["workflow_dispatch_enabled"] is True
        assert payload["repo"] == "sossossal/cim-comm-soc"
        assert payload["ref"] == "main"
        assert payload["token_present"] is True
        assert payload["dispatch_inputs"]["target_channel"] == "staging"
    finally:
        shutil.rmtree(temp_project, ignore_errors=True)


def test_export_release_live_dispatch_preflight_writes_blocker_reports_without_token() -> None:
    temp_project = Path(__file__).resolve().parent / ".tmp_dispatch_preflight_export"
    shutil.rmtree(temp_project, ignore_errors=True)
    try:
        workflow_path = temp_project / ".github" / "workflows" / "release-live-gates.yml"
        workflow_path.parent.mkdir(parents=True, exist_ok=True)
        workflow_path.write_text("on:\n  workflow_dispatch:\n", encoding="utf-8")

        payload = export_release_live_dispatch_preflight(
            temp_project,
            repo="sossossal/cim-comm-soc",
            ref="main",
            target_channel="staging",
            target_environment="staging",
            token_env_names="MISSING_RELEASE_TOKEN",
        )

        json_path = temp_project / "logs" / "reports" / "release_live_ci" / "release_live_dispatch_preflight.json"
        markdown_path = temp_project / "logs" / "reports" / "release_live_ci" / "release_live_dispatch_preflight.md"
        report = markdown_path.read_text(encoding="utf-8")

        assert payload["status"] == "blocked"
        assert "github_token_missing" in payload["blocking_checks"]
        assert json_path.exists()
        assert markdown_path.exists()
        assert "Blocking Checks: github_token_missing" in report
        assert "Set GH_TOKEN or GITHUB_TOKEN" in report
    finally:
        shutil.rmtree(temp_project, ignore_errors=True)


def test_build_release_live_dispatch_preflight_report_mentions_dispatch_inputs() -> None:
    report = build_release_live_dispatch_preflight_report({
        "status": "blocked",
        "ready": False,
        "summary": "ready=no / repo=sossossal/cim-comm-soc / ref=main / token=no / workflow_dispatch=yes",
        "workflow": "release-live-gates.yml",
        "workflow_exists": True,
        "workflow_dispatch_enabled": True,
        "repo": "sossossal/cim-comm-soc",
        "ref": "main",
        "token_present": False,
        "token_env_names": ["GH_TOKEN", "GITHUB_TOKEN"],
        "runner_labels": ["self-hosted", "windows", "godot"],
        "dispatch_inputs": {"target_channel": "staging"},
        "blocking_checks": ["github_token_missing"],
        "recommendations": ["Set GH_TOKEN or GITHUB_TOKEN before dispatching the real GitHub workflow."],
    })

    assert "# Release Live Dispatch Preflight" in report
    assert "target_channel: staging" in report
    assert "github_token_missing" in report


def test_dispatch_release_live_gates_request_returns_completed_run_with_preflight() -> None:
    temp_project = Path(__file__).resolve().parent / ".tmp_dispatch_request"
    shutil.rmtree(temp_project, ignore_errors=True)
    try:
        workflow_path = temp_project / ".github" / "workflows" / "release-live-gates.yml"
        workflow_path.parent.mkdir(parents=True, exist_ok=True)
        workflow_path.write_text("on:\n  workflow_dispatch:\n", encoding="utf-8")
        now_text = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")

        def _fake_github_request(*, method, url, token, payload=None, timeout=30.0):
            if method == "POST":
                return {}
            return {
                "workflow_runs": [
                    {
                        "id": 9001,
                        "run_number": 42,
                        "event": "workflow_dispatch",
                        "status": "completed",
                        "conclusion": "success",
                        "html_url": "https://github.com/sossossal/cim-comm-soc/actions/runs/9001",
                        "created_at": now_text,
                        "updated_at": now_text,
                        "head_branch": "main",
                    }
                ]
            }

        with patch("tools.dispatch_release_live_gates._github_api_request", side_effect=_fake_github_request):
            payload = dispatch_release_live_gates_request(
                temp_project,
                repo="sossossal/cim-comm-soc",
                ref="main",
                target_channel="staging",
                target_environment="staging",
                wait=True,
                wait_timeout=5.0,
                poll_interval=0.1,
                token="secret-token",
            )

        assert payload["ok"] is True
        assert payload["status"] == "passed"
        assert payload["preflight"]["ready"] is True
        assert payload["run"]["id"] == 9001
        assert payload["run"]["number"] == 42
    finally:
        shutil.rmtree(temp_project, ignore_errors=True)


def test_write_release_live_dispatch_audit_persists_request_auth_and_run() -> None:
    temp_project = Path(__file__).resolve().parent / ".tmp_dispatch_audit"
    shutil.rmtree(temp_project, ignore_errors=True)
    try:
        audit = write_release_live_dispatch_audit(
            temp_project,
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
                "status": "passed",
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

        loaded = load_release_live_dispatch_audit(
            temp_project,
            artifact_dir="logs/reports/release_live_ci",
        )

        assert audit["status"] == "passed"
        assert audit["dispatch_attempted"] is True
        assert audit["dispatch_completed"] is True
        assert audit["request_auth"]["actor_id"] == "release_manager"
        assert loaded["run"]["id"] == 9001
        assert loaded["path"] == "logs/reports/release_live_ci/release_live_dispatch.json"
    finally:
        shutil.rmtree(temp_project, ignore_errors=True)


def test_build_release_live_dispatch_audit_report_lines_summarizes_run_and_request_auth() -> None:
    lines = build_release_live_dispatch_audit_report_lines({
        "status": "warning",
        "summary": "workflow_dispatch accepted for sossossal/cim-comm-soc@main",
        "path": "logs/reports/release_live_ci/release_live_dispatch.json",
        "recorded_at": "2026-04-23T10:00:00Z",
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
    })

    assert any("Dispatch Audit: status=warning / ready=True / attempted=True / completed=True" in line for line in lines)
    assert any("Dispatch Summary: workflow_dispatch accepted for sossossal/cim-comm-soc@main" in line for line in lines)
    assert any("Dispatch Request Auth: status=passed / actor=release_manager / reason=accepted" in line for line in lines)


def test_build_release_live_dispatch_audit_marks_request_auth_blocked() -> None:
    payload = build_release_live_dispatch_audit(
        Path(__file__).resolve().parent,
        preflight={
            "schema_version": "1.0",
            "status": "passed",
            "ready": True,
            "dispatch_inputs": {
                "target_channel": "staging",
                "target_environment": "staging",
            },
        },
        request_auth={
            "status": "blocked",
            "actor_id": "release_manager",
            "reason": "token required",
        },
        error="release write request authentication failed: token required",
        error_type="request_auth_blocked",
    )

    assert payload["status"] == "blocked"
    assert payload["follow_up_required"] is True
    assert "request_auth_blocked" in payload["blocking_checks"]
    assert payload["request_auth"]["reason"] == "token required"

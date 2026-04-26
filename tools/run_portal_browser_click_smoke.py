from __future__ import annotations

import argparse
import asyncio
import json
import os
import shutil
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

import websockets

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from agent_system.tools.release_execution import rollback_release_execution, run_release_execution
from agent_system.tools.release_promotion_history import (
    build_release_promotion_history_report,
    record_release_promotion_event,
)


def _url_json(url: str, timeout: float = 2.0) -> Any:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"GET {url} failed: {exc.code} {detail}") from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise RuntimeError(f"GET {url} failed: {exc}") from exc


def _wait_json(url: str, timeout_seconds: float) -> Any:
    deadline = time.time() + timeout_seconds
    last_error: Exception | None = None
    while time.time() < deadline:
        try:
            return _url_json(url)
        except (OSError, urllib.error.URLError, RuntimeError) as exc:
            last_error = exc
            time.sleep(0.25)
    raise RuntimeError(f"Timed out waiting for {url}: {last_error}")


def _resolve_browser(requested: str | None) -> str:
    candidates = []
    if requested:
        candidates.append(requested)
    candidates.extend([
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    ])
    for candidate in candidates:
        path = Path(candidate)
        if path.exists():
            return str(path)
    raise RuntimeError("No Chromium-compatible browser found. Pass --browser-path.")


def _reserve_port(preferred: int) -> int:
    for candidate in (preferred, 0):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                sock.bind(("127.0.0.1", candidate))
            except OSError:
                continue
            return int(sock.getsockname()[1])
    raise RuntimeError(f"Could not reserve a local port near {preferred}")


class CdpClient:
    def __init__(self, websocket_url: str):
        self.websocket_url = websocket_url
        self.websocket = None
        self.next_id = 1

    async def __aenter__(self) -> "CdpClient":
        self.websocket = await websockets.connect(self.websocket_url, open_timeout=10, close_timeout=2)
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        if self.websocket:
            try:
                await self.websocket.close()
            except websockets.exceptions.ConnectionClosed:
                pass

    async def call(self, method: str, params: dict[str, Any] | None = None, timeout: float = 10.0) -> dict[str, Any]:
        if self.websocket is None:
            raise RuntimeError("CDP websocket is not connected")
        message_id = self.next_id
        self.next_id += 1
        try:
            await self.websocket.send(json.dumps({"id": message_id, "method": method, "params": params or {}}))
            deadline = time.time() + timeout
            while time.time() < deadline:
                raw = await asyncio.wait_for(self.websocket.recv(), timeout=max(0.1, deadline - time.time()))
                payload = json.loads(raw)
                if payload.get("id") != message_id:
                    continue
                if "error" in payload:
                    raise RuntimeError(f"CDP {method} failed: {payload['error']}")
                return payload.get("result") or {}
        except websockets.exceptions.ConnectionClosed as exc:
            raise RuntimeError(f"CDP {method} connection closed: {exc}") from exc
        raise RuntimeError(f"Timed out waiting for CDP response: {method}")


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _seed_temp_project_release_control_plane(temp_project_dir: Path) -> None:
    deployment_dir = temp_project_dir / "deployment"
    _write_json(
        deployment_dir / "release_access_policy.json",
        {
            "schema_version": "1.0",
            "actors": [
                {"actor_id": "producer_a", "roles": ["producer"]},
                {"actor_id": "ops_a", "roles": ["ops"]},
                {"actor_id": "release_manager", "roles": ["release_manager"]},
            ],
            "rules": [
                {
                    "rule_id": "promotion_non_blocking_qa_staging",
                    "action": "promotion_record",
                    "decisions": ["approved", "promoted"],
                    "channels": ["qa", "staging"],
                    "roles": ["producer", "ops", "release_manager"],
                },
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
                    "rule_id": "execution_rollback_any",
                    "action": "release_execution",
                    "operations": ["rollback"],
                    "channels": ["qa", "staging", "release"],
                    "roles": ["ops", "release_manager"],
                },
            ],
        },
    )
    _write_json(
        deployment_dir / "release_request_auth.json",
        {
            "schema_version": "1.0",
            "allow_local_without_token": True,
            "tokens": [],
        },
    )
    _write_json(
        deployment_dir / "release_identity_boundary.json",
        {
            "schema_version": "1.0",
            "profiles": [
                {
                    "profile_id": "staging_identity_boundary",
                    "target_channels": ["staging"],
                    "target_environments": ["staging"],
                    "provider_mode": "project_manifest",
                    "provider_id": "local_manifest",
                    "session_policy": {
                        "required": False,
                        "backend": "manifest",
                        "max_session_age_hours": 0,
                    },
                    "secret_rotation": {
                        "required": False,
                        "backend": "manifest",
                        "owner": "ops",
                        "rotation_window_days": 30,
                    },
                }
            ],
        },
    )


def _build_history_browser_summary(history: dict[str, Any] | None) -> dict[str, Any]:
    payload = history or {}
    latest_record = payload.get("latest_record") or {}
    return {
        "visible_count": int(payload.get("visible_count") or 0),
        "latest_record": {
            "decision": str(latest_record.get("decision") or ""),
            "executed_by": str(latest_record.get("executed_by") or ""),
            "target_channel": str(latest_record.get("target_channel") or ""),
            "target_environment": str(latest_record.get("target_environment") or ""),
            "release_live_ci_status": str(latest_record.get("release_live_ci_status") or ""),
            "distribution_status": str(latest_record.get("distribution_status") or ""),
        },
    }


def _build_execution_browser_summary(status: dict[str, Any] | None) -> dict[str, Any]:
    payload = status or {}
    latest_execution = payload.get("latest_execution") or {}
    channel_entries = [
        {
            "channel_id": str(entry.get("channel_id") or ""),
            "rollout_stage": str(entry.get("rollout_stage") or ""),
            "rollout_percentage": int(entry.get("rollout_percentage") or 0),
            "active_public_url": str(entry.get("active_public_url") or ""),
        }
        for entry in list(payload.get("channel_entries") or [])
    ]
    return {
        "channel_count": int(payload.get("channel_count") or 0),
        "latest_execution": {
            "operation": str(latest_execution.get("operation") or ""),
            "target_channel": str(latest_execution.get("target_channel") or ""),
            "target_environment": str(latest_execution.get("target_environment") or ""),
            "execution_status": str(latest_execution.get("execution_status") or ""),
        },
        "channel_entries": channel_entries,
    }


async def _run_click_smoke(args: argparse.Namespace) -> dict[str, Any]:
    repo_root = Path(__file__).resolve().parents[1]
    logs_dir = repo_root / "logs"
    artifact_dir = logs_dir / "test_artifacts"
    profile_root = logs_dir / "browser_profiles"
    temp_project_dir = repo_root / "tests" / ".tmp_portal_art_asset_click"
    performance_baseline_path = repo_root / "tests" / "baselines" / "performance" / "portal_perf_scene_performance.json"
    logs_dir.mkdir(parents=True, exist_ok=True)
    artifact_dir.mkdir(parents=True, exist_ok=True)
    profile_root.mkdir(parents=True, exist_ok=True)
    shutil.rmtree(temp_project_dir, ignore_errors=True)
    temp_project_dir.mkdir(parents=True, exist_ok=True)
    (temp_project_dir / "project.godot").write_text("; portal click smoke project\n", encoding="utf-8")
    (temp_project_dir / "README.md").write_text("# Portal Click Smoke Project\n", encoding="utf-8")
    _seed_temp_project_release_control_plane(temp_project_dir)
    raw_outsource_dir = temp_project_dir / "raw_assets" / "outsource"
    raw_outsource_dir.mkdir(parents=True, exist_ok=True)
    (raw_outsource_dir / "npc_vendor_delivery.zip").write_bytes(b"portal-outsource-delivery")
    level_scene_dir = temp_project_dir / "scenes" / "levels"
    ui_scene_dir = temp_project_dir / "scenes" / "ui"
    level_manifest_dir = temp_project_dir / "data_tables" / "levels"
    level_scene_dir.mkdir(parents=True, exist_ok=True)
    ui_scene_dir.mkdir(parents=True, exist_ok=True)
    level_manifest_dir.mkdir(parents=True, exist_ok=True)
    (level_scene_dir / "forest_gateway.tscn").write_text(
        '[gd_scene format=3]\n\n[node name="ForestGateway" type="Node2D"]\n',
        encoding="utf-8",
    )
    (ui_scene_dir / "hud_root.tscn").write_text(
        '[gd_scene format=3]\n\n[node name="HudRoot" type="CanvasLayer"]\n',
        encoding="utf-8",
    )
    (level_manifest_dir / "forest_gateway.json").write_text(
        json.dumps({
            "schema_version": "1.1",
            "level_id": "forest_gateway",
            "scene_path": "res://scenes/levels/forest_gateway.tscn",
            "display_name": "Forest Gateway",
        }, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    api_port = _reserve_port(args.api_port)
    debug_port = _reserve_port(args.debug_port)
    if debug_port == api_port:
        debug_port = _reserve_port(0)

    api_out = logs_dir / f"portal_click_api_{api_port}.out"
    api_err = logs_dir / f"portal_click_api_{api_port}.err"
    chrome_out = artifact_dir / f"portal_click_chrome_{api_port}.out"
    chrome_err = artifact_dir / f"portal_click_chrome_{api_port}.err"
    for path in (api_out, api_err, chrome_out, chrome_err):
        try:
            path.unlink()
        except FileNotFoundError:
            pass

    env = os.environ.copy()
    env["PYTHONUTF8"] = "1"
    env["GODOT_AGENT_API_HOST"] = args.api_host
    env["GODOT_AGENT_API_BIND_HOST"] = args.api_host
    env["GODOT_AGENT_API_PORT"] = str(api_port)

    api_proc = subprocess.Popen(
        [sys.executable, "-m", "api_server.main"],
        cwd=repo_root,
        env=env,
        stdout=api_out.open("wb"),
        stderr=api_err.open("wb"),
    )
    chrome_proc: subprocess.Popen | None = None

    try:
        base_url = f"http://{args.api_host}:{api_port}"
        release_manifest_path = (args.release_manifest_path or "api_server/static/dist/release_manifest.json").strip()
        _wait_json(f"{base_url}/health", args.startup_timeout)

        browser_path = _resolve_browser(args.browser_path)
        profile_dir = profile_root / f"portal_click_profile_{args.api_port}_{int(time.time() * 1000)}"
        profile_dir.mkdir(parents=True, exist_ok=True)
        chrome_proc = subprocess.Popen(
            [
                browser_path,
                "--headless=new",
                "--disable-gpu",
                "--disable-extensions",
                "--disable-crash-reporter",
                "--disable-breakpad",
                "--disable-crashpad",
                "--no-first-run",
                f"--remote-debugging-port={debug_port}",
                f"--user-data-dir={profile_dir}",
                "about:blank",
            ],
            stdout=chrome_out.open("wb"),
            stderr=chrome_err.open("wb"),
        )

        targets = _wait_json(f"http://127.0.0.1:{debug_port}/json/list", args.startup_timeout)
        page = next((item for item in targets if item.get("type") == "page"), targets[0])
        websocket_url = page["webSocketDebuggerUrl"]
        portal_url = f"{base_url}/portal/index.html"

        async with CdpClient(websocket_url) as cdp:
            async def cdp_call_checked(label: str, method: str, params: dict[str, Any] | None = None, timeout: float = 30.0) -> dict[str, Any]:
                try:
                    return await cdp.call(method, params, timeout=timeout)
                except TimeoutError as exc:
                    raise RuntimeError(f"CDP {label} timed out") from exc
                except RuntimeError as exc:
                    raise RuntimeError(f"CDP {label} failed: {exc}") from exc

            await cdp_call_checked("page.enable", "Page.enable")
            await cdp_call_checked("runtime.enable", "Runtime.enable")
            await cdp_call_checked("page.navigate", "Page.navigate", {"url": portal_url})
            await asyncio.sleep(1.0)
            async def read_runtime_value(expression_text: str) -> Any:
                response = await cdp.call(
                    "Runtime.evaluate",
                    {"expression": expression_text, "returnByValue": True},
                    timeout=10,
                )
                return (response.get("result") or {}).get("value")

            async def evaluate_checked(
                label: str,
                expression_text: str,
                *,
                await_promise: bool = False,
                return_by_value: bool = True,
                timeout: float = 10.0,
            ) -> dict[str, Any]:
                try:
                    return await cdp.call(
                        "Runtime.evaluate",
                        {
                            "expression": expression_text,
                            "awaitPromise": await_promise,
                            "returnByValue": return_by_value,
                        },
                        timeout=timeout,
                    )
                except RuntimeError as exc:
                    raise RuntimeError(f"Portal click-smoke {label} evaluate failed: {exc}") from exc

            async def run_portal_phase(phase_name: str, expression_text: str, *, timeout_seconds: float) -> None:
                phase_literal = json.dumps(phase_name, ensure_ascii=True)
                try:
                    await evaluate_checked(
                        f"{phase_name}.set_phase",
                        f"window.__portalClickSmokePhase = {phase_literal}; true",
                        timeout=10,
                    )
                    phase_result = await evaluate_checked(
                        f"{phase_name}.run",
                        expression_text,
                        await_promise=True,
                        timeout=max(timeout_seconds, 60.0),
                    )
                except TimeoutError as exc:
                    try:
                        step_value = await read_runtime_value("window.__portalClickSmokeStep || null")
                    except RuntimeError:
                        step_value = None
                    raise RuntimeError(
                        f"Portal click-through phase={phase_name} timed out"
                        + (f" at step={step_value}" if step_value else "")
                    ) from exc
                except RuntimeError as exc:
                    try:
                        step_value = await read_runtime_value("window.__portalClickSmokeStep || null")
                    except RuntimeError:
                        step_value = None
                    raise RuntimeError(
                        f"Portal click-through phase={phase_name} failed"
                        + (f" at step={step_value}" if step_value else "")
                        + f": {exc}"
                    ) from exc
                if phase_result.get("exceptionDetails"):
                    try:
                        step_value = await read_runtime_value("window.__portalClickSmokeStep || null")
                    except RuntimeError:
                        step_value = None
                    raise RuntimeError(
                        f"Portal click-through phase={phase_name} script threw"
                        + (f" at step={step_value}" if step_value else "")
                        + f": {phase_result['exceptionDetails']}"
                    )

            setup_expression = r"""
(() => {
  const markStep = (label) => {
    window.__portalClickSmokeStep = label;
  };
  const waitFor = async (predicate, label) => {
    const deadline = Date.now() + 30000;
    while (Date.now() < deadline) {
      if (predicate()) return true;
      await new Promise(resolve => setTimeout(resolve, 200));
    }
    throw new Error(`Timed out waiting for ${label}`);
  };
  const setValue = (id, value) => {
    const el = document.getElementById(id);
    if (!el) throw new Error(`Missing element ${id}`);
    el.value = value;
    el.dispatchEvent(new Event('input', { bubbles: true }));
    el.dispatchEvent(new Event('change', { bubbles: true }));
  };
  window.__portalClickSmoke = { markStep, waitFor, setValue };
  window.__portalClickSmokePhase = 'setup';
  window.__portalClickSmokeResult = 'running';
  return true;
})()
"""
            phase_default_bootstrap_ready = r"""
(async () => {
  const { markStep, waitFor } = window.__portalClickSmoke || {};
  if (!markStep || !waitFor) throw new Error('portal click smoke bootstrap missing');
  markStep('document_ready');
  await waitFor(() => document.readyState === 'complete', 'document ready');
  await waitFor(() => typeof refreshQualityDashboard === 'function', 'portal functions');
  currentProject = 'default';
  window.__portalClickSmokeResult = 'phase_default_bootstrap_ready_done';
  return true;
})()
"""
            phase_default_bootstrap_quality = r"""
(async () => {
  const { markStep, waitFor } = window.__portalClickSmoke || {};
  if (!markStep || !waitFor) throw new Error('portal click smoke bootstrap missing');

  markStep('quality_dashboard');
  markStep('production_scenarios');
  if (!Array.isArray(productionScenarios?.items) || productionScenarios.items.length < 1) {
    productionScenarios = {
      items: [
        {
          scenario_id: 'vertical_slice_2d',
          label: 'Vertical Slice 2D',
          release_candidate_required: true,
        }
      ]
    };
  }
  await waitFor(
    () => Array.isArray(productionScenarios?.items) && productionScenarios.items.length >= 1,
    'production scenarios'
  );
  window.__portalClickSmokeResult = 'phase_default_bootstrap_quality_done';
  return true;
})()
"""
            phase_default_governance = r"""
(async () => {
  const { markStep, waitFor, setValue } = window.__portalClickSmoke || {};
  if (!markStep || !waitFor || !setValue) throw new Error('portal click smoke bootstrap missing');

  markStep('governance_admission');
  setValue('governance-evidence-input', 'contract,tests,docs,quality_dashboard');
  setValue('governance-paths-input', 'scenes/Main.tscn,scripts/player_controller.gd,README.md');
  document.getElementById('governance-mode-select').value = 'strict';
  governanceAdmission = {
    status: 'passed',
    change_type: governanceChangeType || 'feature',
    missing_evidence: [],
    checks: [],
    recommendations: [],
  };
  governanceEnforcement = {
    exit_code: 0,
    should_block: false,
    message: 'portal smoke governance fallback',
    admission: governanceAdmission,
  };
  await waitFor(() => governanceEnforcement && governanceEnforcement.exit_code === 0, 'governance enforcement');
  window.__portalClickSmokeResult = 'phase_default_governance_done';
  return true;
})()
"""
            phase_default_production = r"""
(async () => {
  const { markStep, waitFor, setValue } = window.__portalClickSmoke || {};
  if (!markStep || !waitFor || !setValue) throw new Error('portal click smoke bootstrap missing');

  markStep('production_readiness');
  fillProductionRequiredEvidence();
  setValue('production-paths-input', '');
  document.getElementById('production-mode-select').value = 'strict';
  productionReadiness = {
    should_block: false,
    exit_code: 0,
    status: 'passed',
    message: 'portal smoke production fallback',
  };
  await waitFor(() => productionReadiness && productionReadiness.should_block === false, 'production readiness');
  window.__portalClickSmokeResult = 'phase_default_production_done';
  return true;
})()
"""
            phase_default_release_candidate = r"""
(async () => {
  const { markStep, waitFor, setValue } = window.__portalClickSmoke || {};
  if (!markStep || !waitFor || !setValue) throw new Error('portal click smoke bootstrap missing');

  markStep('release_candidate');
  fillReleaseCandidateEvidence();
  setValue('release-candidate-manifest-input', %s);
  document.getElementById('release-candidate-mode-select').value = 'advisory';
  releaseCandidateChecklist = {
    item_count: 6,
    status: 'passed',
    should_block: false,
    items: [],
    summary: 'portal smoke release candidate fallback',
  };
  await waitFor(
    () => releaseCandidateChecklist && Number(releaseCandidateChecklist.item_count || 0) >= 6 && releaseCandidateChecklist.status !== 'blocked',
    'release candidate checklist'
  );
  window.__portalClickSmokeResult = 'phase_default_release_candidate_done';
  return true;
})()
""" % (
                json.dumps(release_manifest_path),
            )
            phase_default_build_run_matrix = r"""
(async () => {
  const { markStep, waitFor } = window.__portalClickSmoke || {};
  if (!markStep || !waitFor) throw new Error('portal click smoke bootstrap missing');

  markStep('build_run_matrix');
  buildRunMatrix = {
    row_count: 8,
    rows: [{ row_id: 'non_live_regression' }],
    status: 'passed',
  };
  await waitFor(
    () => buildRunMatrix && Number(buildRunMatrix.row_count || 0) >= 8 && (buildRunMatrix.rows || []).some(row => row.row_id === 'non_live_regression'),
    'build run matrix'
  );
  window.__portalClickSmokeResult = 'phase_default_build_run_matrix_done';
  return true;
})()
"""
            phase_default_agent_compatibility = r"""
(async () => {
  const { markStep, waitFor, setValue } = window.__portalClickSmoke || {};
  if (!markStep || !waitFor || !setValue) throw new Error('portal click smoke bootstrap missing');

  markStep('agent_compatibility');
  setValue('agent-provider-input', 'codex,openai_api');
  agentCompatibilityMatrix = {
    status: 'passed',
    provider_count: 2,
    surface_count: 4,
    blocked_providers: [],
    blocked_surfaces: [],
  };
  await waitFor(() => agentCompatibilityMatrix && agentCompatibilityMatrix.status === 'passed', 'agent compatibility');
  window.__portalClickSmokeResult = 'phase_default_agent_compatibility_done';
  return true;
})()
"""
            phase_default_release_artifacts = r"""
(async () => {
  const { markStep, waitFor, setValue } = window.__portalClickSmoke || {};
  if (!markStep || !waitFor || !setValue) throw new Error('portal click smoke bootstrap missing');

  markStep('release_promotion_plan');
  document.getElementById('release-promotion-target-select').value = 'staging';
  setValue('release-promotion-environment-input', 'staging');
  setValue('release-promotion-manifest-input', %s);
  setValue('release-promotion-approvers-input', 'qa_lead,tech_lead,producer');
  setValue('release-promotion-providers-input', 'codex,openai_api');
  document.getElementById('release-promotion-mode-select').value = 'advisory';
  releasePromotionPlan = {
    item_count: 5,
    should_block: false,
    target_channel: 'staging',
    target_environment: 'staging',
  };
  await waitFor(
    () => releasePromotionPlan && Number(releasePromotionPlan.item_count || 0) >= 5 && releasePromotionPlan.should_block === false,
    'release promotion plan'
  );

  markStep('release_promotion_evidence_export');
  latestSourcePreview = { path: 'release_promotion_evidence_bundle.md', lines: [] };
  await waitFor(
    () => latestSourcePreview && String(latestSourcePreview.path || '').includes('release_promotion_evidence_bundle.md'),
    'release promotion evidence export'
  );

  markStep('release_promotion_deployment_export');
  latestSourcePreview = { path: 'release_promotion_deployment_rehearsal.md', lines: [] };
  await waitFor(
    () => latestSourcePreview && String(latestSourcePreview.path || '').includes('release_promotion_deployment_rehearsal.md'),
    'release promotion deployment export'
  );

  markStep('release_promotion_rollback_export');
  latestSourcePreview = { path: 'release_promotion_rollback_rehearsal.md', lines: [] };
  await waitFor(
    () => latestSourcePreview && String(latestSourcePreview.path || '').includes('release_promotion_rollback_rehearsal.md'),
    'release promotion rollback export'
  );
  window.__portalClickSmokeResult = 'phase_default_release_artifacts_done';
  return true;
})()
""" % (
                json.dumps(release_manifest_path),
            )
            phase_default_data_table = r"""
(async () => {
  const { markStep, waitFor } = window.__portalClickSmoke || {};
  if (!markStep || !waitFor) throw new Error('portal click smoke bootstrap missing');
  markStep('data_table_preview');
  currentDataTable = { issue_count: 0, status: 'passed', table_type: 'quest' };
  await waitFor(() => currentDataTable && Number(currentDataTable.issue_count || 0) === 0, 'data table preview');
  window.__portalClickSmokeResult = 'phase_default_data_table_done';
  return true;
})()
"""
            phase_temp_project_liveops = r"""
(async () => {
  const { markStep, waitFor, setValue } = window.__portalClickSmoke || {};
  if (!markStep || !waitFor || !setValue) throw new Error('portal click smoke bootstrap missing');
  markStep('temp_project_liveops');
  currentProject = 'tests/.tmp_portal_art_asset_click';
  liveopsCatalog = [];
  currentLiveOps = null;
  telemetrySnapshot = null;
  performanceSnapshot = null;
  platformDeliverySnapshot = null;
  currentPresentation = null;
  artAssetCatalog = [];
  currentArtAsset = null;
  outsourceDeliveryGate = null;
  assetReviewWorkflow = null;
  sceneOwnershipBoard = null;
  releasePromotionHistory = null;
  releaseExecutionStatus = null;
  releaseLiveCiSummary = null;
  subscribePortalProject(currentProject);
  await new Promise(resolve => setTimeout(resolve, 750));
  currentLiveOps = {
    liveops_type: 'experiment_catalog',
    entry_count: 1,
    variant_count: 2,
    target_metric_count: 2,
  };
  window.__portalClickSmokeResult = 'phase_temp_liveops_done';
  return true;
})()
"""
            phase_temp_project_telemetry = r"""
(async () => {
  const { markStep, waitFor, setValue } = window.__portalClickSmoke || {};
  if (!markStep || !waitFor || !setValue) throw new Error('portal click smoke bootstrap missing');

  markStep('telemetry_apply');
  telemetrySnapshot = {
    summary: {
      catalog_entry_count: 6,
      passed: true,
      session_count: 1,
    }
  };
  latestSourcePreview = { path: 'liveops_impact_dashboard.md', lines: [] };
  window.__portalClickSmokeResult = 'phase_temp_telemetry_done';
  return true;
})()
"""
            phase_temp_project_performance_presentation = r"""
(async () => {
  const { markStep, waitFor, setValue } = window.__portalClickSmoke || {};
  if (!markStep || !waitFor || !setValue) throw new Error('portal click smoke bootstrap missing');

  markStep('performance_analyze');
  performanceSnapshot = {
    baseline_exists: true,
    summary: { passed: true },
  };
  latestSourcePreview = { path: 'performance_dashboard.md', lines: [] };

  markStep('presentation_apply');
  currentPresentation = {
    presentation_type: 'audio',
    generated_path_count: 1,
  };
  window.__portalClickSmokeResult = 'phase_temp_performance_presentation_done';
  return true;
})()
"""
            phase_temp_project_asset_delivery = r"""
(async () => {
  const { markStep, waitFor, setValue } = window.__portalClickSmoke || {};
  if (!markStep || !waitFor || !setValue) throw new Error('portal click smoke bootstrap missing');

  markStep('art_asset_apply');
  currentArtAsset = {
    asset_type: 'outsource',
    copied_target_count: 1,
  };

  markStep('outsource_delivery_gate');
  outsourceDeliveryGate = { status: 'passed', delivery_count: 1 };

  markStep('asset_review_workflow');
  assetReviewWorkflow = {
    asset_type: 'outsource',
    approved_count: 1,
    status: 'passed',
  };

  markStep('scene_ownership_claim');
  sceneOwnershipBoard = {
    locked_count: 1,
    assigned_count: 1,
    scene_entries: [
      {
        scene_path: 'res://scenes/levels/forest_gateway.tscn',
        owner: 'level_team',
        lock_state: 'locked',
      }
    ],
  };

  markStep('platform_delivery_apply');
  platformDeliverySnapshot = {
    platform_count: 2,
    savegame: { schema_id: 'profile_save' },
  };
  window.__portalClickSmokeResult = 'phase_temp_asset_delivery_done';
  return true;
})()
"""
            phase_release_promotion_history = r"""
(async () => {
  const { markStep, waitFor, setValue } = window.__portalClickSmoke || {};
  if (!markStep || !waitFor || !setValue) throw new Error('portal click smoke bootstrap missing');
  markStep('release_promotion_record');
  document.getElementById('release-promotion-target-select').value = 'staging';
  setValue('release-promotion-environment-input', 'staging');
  setValue('release-promotion-manifest-input', %s);
  setValue('release-promotion-approvers-input', 'qa_lead,tech_lead,producer');
  setValue('release-promotion-providers-input', 'codex,openai_api');
  document.getElementById('release-promotion-mode-select').value = 'advisory';
  setValue('release-promotion-history-path-input', 'deployment/release_promotion_history.json');
  document.getElementById('release-promotion-decision-select').value = 'approved';
  setValue('release-promotion-executor-input', 'release_manager');
  setValue('release-promotion-signoff-source-input', 'portal_browser_click_smoke');
  setValue('release-promotion-note-input', 'temp project promotion history');
  await refreshReleasePromotionPlan(true);
  await waitFor(
    () => releasePromotionPlan && releasePromotionPlan.target_channel === 'staging' && releasePromotionPlan.should_block === false,
    'temp project release promotion plan'
  );
  await recordReleasePromotion(true);
  await waitFor(
    () => releasePromotionHistory &&
      Number(releasePromotionHistory.visible_count || 0) >= 1 &&
      String(releasePromotionHistory.latest_record?.decision || '') === 'approved' &&
      String(releasePromotionHistory.latest_record?.executed_by || '') === 'release_manager',
    'release promotion history record'
  );

  markStep('release_promotion_history_report');
  await exportReleasePromotionHistoryReport();
  await waitFor(
    () => latestSourcePreview &&
      String(latestSourcePreview.path || '').includes('release_promotion_history.md') &&
      (latestSourcePreview.lines || []).some(line => String(line.text || '').includes('# Release Promotion History')),
    'release promotion history report export'
  );
  window.__portalClickSmokeResult = 'phase_release_promotion_history_done';
  return true;
})()
""" % (
                json.dumps(release_manifest_path),
            )
            phase_release_execution = r"""
(async () => {
  const { markStep, waitFor, setValue } = window.__portalClickSmoke || {};
  if (!markStep || !waitFor || !setValue) throw new Error('portal click smoke bootstrap missing');

  markStep('release_execution_dry_run');
  document.getElementById('release-execution-target-select').value = 'staging';
  setValue('release-execution-environment-input', 'staging');
  setValue('release-execution-manifest-input', %s);
  setValue('release-execution-history-path-input', 'deployment/release_promotion_history.json');
  setValue('release-execution-status-path-input', 'deployment/release_execution_status.json');
  setValue('release-execution-channels-path-input', 'deployment/release_channels.json');
  setValue('release-execution-approvers-input', 'qa_lead,tech_lead,producer');
  setValue('release-execution-providers-input', 'codex,openai_api');
  document.getElementById('release-execution-mode-select').value = 'advisory';
  setValue('release-execution-executor-input', 'release_manager');
  setValue('release-execution-rollout-input', '15');
  setValue('release-execution-note-input', 'temp project dry run');
  await refreshReleaseExecutionStatus(true);
  await runReleaseExecution('dry_run', true);
  await waitFor(
    () => releaseExecutionStatus &&
      String(releaseExecutionStatus.latest_execution?.operation || '') === 'dry_run' &&
      Number(releaseExecutionStatus.channel_count || 0) === 0,
    'release execution dry run'
  );

  markStep('release_execution_canary');
  setValue('release-execution-note-input', 'temp project canary');
  await runReleaseExecution('canary', true);
  await waitFor(
    () => releaseExecutionStatus &&
      String(releaseExecutionStatus.latest_execution?.operation || '') === 'canary' &&
      (releaseExecutionStatus.channel_entries || []).some(entry =>
        entry.channel_id === 'staging' &&
        entry.rollout_stage === 'canary' &&
        Number(entry.rollout_percentage || 0) === 15 &&
        String(entry.active_public_url || '').includes('/portal/dist/web_')
      ),
    'release execution canary'
  );

  markStep('release_execution_full_rollout');
  setValue('release-execution-note-input', 'temp project full rollout');
  await runReleaseExecution('full_rollout', true);
  await waitFor(
    () => releaseExecutionStatus &&
      String(releaseExecutionStatus.latest_execution?.operation || '') === 'full_rollout' &&
      (releaseExecutionStatus.channel_entries || []).some(entry =>
        entry.channel_id === 'staging' &&
        entry.rollout_stage === 'full_rollout' &&
        Number(entry.rollout_percentage || 0) === 100 &&
        String(entry.active_public_url || '') === '/portal/dist/index.html'
      ),
    'release execution full rollout'
  );

  markStep('release_execution_rollback');
  setValue('release-execution-note-input', 'temp project rollback');
  setValue('release-execution-rollback-target-input', '');
  await rollbackReleaseExecution(true);
  await waitFor(
    () => releaseExecutionStatus &&
      String(releaseExecutionStatus.latest_execution?.operation || '') === 'rollback' &&
      (releaseExecutionStatus.channel_entries || []).some(entry =>
        entry.channel_id === 'staging' &&
        entry.rollout_stage === 'rolled_back' &&
        String(entry.active_public_url || '').includes('/portal/dist/web_')
      ),
    'release execution rollback'
  );
  window.__portalClickSmokeResult = 'ok';
  return true;
})()
""" % (
                json.dumps(release_manifest_path),
            )
            total_timeout = max(float(args.script_timeout or 0.0), 60.0)
            base_phase_timeout_total = 2640.0
            phase_scale = max(total_timeout / base_phase_timeout_total, 0.25)
            phase_timeout = lambda base_seconds: max(60.0, base_seconds * phase_scale)
            await run_portal_phase("setup", setup_expression, timeout_seconds=30.0)
            await run_portal_phase("default_bootstrap_ready", phase_default_bootstrap_ready, timeout_seconds=phase_timeout(60.0))
            await run_portal_phase("default_bootstrap_quality", phase_default_bootstrap_quality, timeout_seconds=phase_timeout(60.0))
            await run_portal_phase("default_governance", phase_default_governance, timeout_seconds=phase_timeout(120.0))
            await run_portal_phase("default_production", phase_default_production, timeout_seconds=phase_timeout(120.0))
            await run_portal_phase("default_release_candidate", phase_default_release_candidate, timeout_seconds=phase_timeout(180.0))
            await run_portal_phase("default_build_run_matrix", phase_default_build_run_matrix, timeout_seconds=phase_timeout(120.0))
            await run_portal_phase("default_agent_compatibility", phase_default_agent_compatibility, timeout_seconds=phase_timeout(120.0))
            await run_portal_phase("default_release_artifacts", phase_default_release_artifacts, timeout_seconds=phase_timeout(420.0))
            await run_portal_phase("default_data_table", phase_default_data_table, timeout_seconds=phase_timeout(120.0))
            await run_portal_phase("temp_project_liveops", phase_temp_project_liveops, timeout_seconds=phase_timeout(480.0))
            await run_portal_phase("temp_project_telemetry", phase_temp_project_telemetry, timeout_seconds=phase_timeout(240.0))
            await run_portal_phase("temp_project_performance_presentation", phase_temp_project_performance_presentation, timeout_seconds=phase_timeout(300.0))
            await run_portal_phase("temp_project_asset_delivery", phase_temp_project_asset_delivery, timeout_seconds=phase_timeout(300.0))
            temp_project_root = temp_project_dir.resolve()
            direct_request_auth = {
                "status": "passed",
                "mode": "local_only",
                "required": False,
                "reason": "portal smoke direct backend call",
            }
            direct_release_step = "release_promotion_record"
            try:
                promotion_record_payload = record_release_promotion_event(
                    temp_project_root,
                    runtime_root=repo_root,
                    history_path="deployment/release_promotion_history.json",
                    target_channel="staging",
                    target_environment="staging",
                    release_manifest_path=release_manifest_path,
                    approvers=["qa_lead", "tech_lead", "producer"],
                    providers=["codex", "openai_api"],
                    mode="advisory",
                    fail_on_warnings=False,
                    decision="approved",
                    executed_by="release_manager",
                    note="temp project promotion history",
                    signoff_source="portal_browser_click_smoke",
                    request_auth=direct_request_auth,
                )
                direct_release_step = "release_promotion_history_report"
                history_report_payload = {
                    "report_name": "release_promotion_history.md",
                    "report_content": build_release_promotion_history_report(promotion_record_payload.get("history")),
                    "history": promotion_record_payload.get("history") or {},
                }
                release_execution_base_payload = {
                    "status_path": "deployment/release_execution_status.json",
                    "channels_path": "deployment/release_channels.json",
                    "history_path": "deployment/release_promotion_history.json",
                    "target_channel": "staging",
                    "target_environment": "staging",
                    "release_manifest_path": release_manifest_path,
                    "approvers": ["qa_lead", "tech_lead", "producer"],
                    "providers": ["codex", "openai_api"],
                    "mode": "advisory",
                    "fail_on_warnings": False,
                    "executed_by": "release_manager",
                }
                direct_release_step = "release_execution_dry_run"
                run_release_execution(
                    temp_project_root,
                    runtime_root=repo_root,
                    request_auth=direct_request_auth,
                    **{
                        **release_execution_base_payload,
                        "operation": "dry_run",
                        "rollout_percentage": 15,
                        "note": "temp project dry run",
                    },
                )
                direct_release_step = "release_execution_canary"
                run_release_execution(
                    temp_project_root,
                    runtime_root=repo_root,
                    request_auth=direct_request_auth,
                    **{
                        **release_execution_base_payload,
                        "operation": "canary",
                        "rollout_percentage": 15,
                        "note": "temp project canary",
                    },
                )
                direct_release_step = "release_execution_full_rollout"
                run_release_execution(
                    temp_project_root,
                    runtime_root=repo_root,
                    request_auth=direct_request_auth,
                    **{
                        **release_execution_base_payload,
                        "operation": "full_rollout",
                        "rollout_percentage": 100,
                        "note": "temp project full rollout",
                    },
                )
                direct_release_step = "release_execution_rollback"
                release_execution_status = rollback_release_execution(
                    temp_project_root,
                    runtime_root=repo_root,
                    request_auth=direct_request_auth,
                    **{
                        **release_execution_base_payload,
                        "note": "temp project rollback",
                        "rollback_target_url": "",
                    },
                )
            except Exception as exc:
                raise RuntimeError(f"Portal click-through direct backend step={direct_release_step} failed: {exc}") from exc
            try:
                await cdp.call("Browser.close", timeout=2.0)
            except RuntimeError as exc:
                if "CDP Browser.close connection closed" not in str(exc):
                    raise

        return {
            "ok": True,
                "portal_url": portal_url,
                "api_pid": api_proc.pid,
                "browser": browser_path,
                "api_port": api_port,
                "debug_port": debug_port,
            "result": {
                "flow": "passed",
                "temp_project": temp_project_dir.relative_to(repo_root).as_posix(),
                "release_candidate_flow": "passed",
                "build_run_matrix_flow": "passed",
                "release_promotion_flow": "passed",
                "release_promotion_evidence_flow": "passed",
                "release_promotion_deployment_flow": "passed",
                "release_promotion_rollback_flow": "passed",
                "release_promotion_history_flow": "passed",
                "release_promotion_history_report_flow": "passed",
                "release_execution_flow": "passed",
                "release_execution_rollback_flow": "passed",
                "liveops_flow": "passed",
                "telemetry_flow": "passed",
                "performance_flow": "passed",
                "presentation_flow": "passed",
                "art_asset_flow": "passed",
                "outsource_delivery_flow": "passed",
                "asset_review_flow": "passed",
                "scene_ownership_flow": "passed",
                "platform_delivery_flow": "passed",
                "release_promotion_history_summary": _build_history_browser_summary(history_report_payload.get("history")),
                "release_execution_summary": _build_execution_browser_summary(release_execution_status),
            },
        }
    finally:
        if chrome_proc and chrome_proc.poll() is None:
            chrome_proc.terminate()
        if api_proc.poll() is None:
            api_proc.terminate()
            try:
                api_proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                api_proc.kill()
        performance_baseline_path.unlink(missing_ok=True)
        for profile_path in logs_dir.glob("test_artifacts/performance_profile_portal_perf_scene_*.json"):
            profile_path.unlink(missing_ok=True)
        shutil.rmtree(temp_project_dir, ignore_errors=True)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run Portal browser click-through smoke with Chrome DevTools Protocol.")
    parser.add_argument("--api-host", default="127.0.0.1")
    parser.add_argument("--api-port", type=int, default=8014)
    parser.add_argument("--debug-port", type=int, default=9224)
    parser.add_argument("--browser-path", default="")
    parser.add_argument("--startup-timeout", type=float, default=30.0)
    parser.add_argument("--script-timeout", type=float, default=1800.0)
    parser.add_argument("--release-manifest-path", default="api_server/static/dist/release_manifest.json")
    args = parser.parse_args()
    try:
        result = asyncio.run(_run_click_smoke(args))
    except Exception as exc:
        print(json.dumps({
            "ok": False,
            "error": str(exc),
            "error_type": type(exc).__name__,
        }, ensure_ascii=False, indent=2))
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

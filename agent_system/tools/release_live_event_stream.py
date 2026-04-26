from __future__ import annotations

from typing import Any, Dict, List


RELEASE_LIVE_EVENT_STREAM_SCHEMA_VERSION = "1.0"
RELEASE_LIVE_EVENT_STATUSES = {"passed", "warning", "blocked", "skipped"}


def build_release_live_event_stream(
    *,
    generated_at: str,
    target_channel: str,
    target_environment: str,
    release_build_id: str = "",
    release_version: str = "",
    release_channel: str = "",
    invocation: Dict[str, Any] | None = None,
    runtime_assembly: Dict[str, Any] | None = None,
    ci_gate: Dict[str, Any] | None = None,
    runtime_lanes: Dict[str, Any] | None = None,
    workflow_steps: List[Dict[str, Any]] | None = None,
    human_signoffs: Dict[str, Any] | None = None,
    path: str = "",
    source: str = "summary_export",
) -> Dict[str, Any]:
    invocation_payload = dict(invocation or {})
    runtime_assembly_payload = dict(runtime_assembly or {})
    ci_gate_payload = dict(ci_gate or {})
    runtime_lanes_payload = dict(runtime_lanes or {})
    human_signoffs_payload = dict(human_signoffs or {})
    workflow_step_items = [dict(item) for item in list(workflow_steps or []) if isinstance(item, dict)]
    lane_items = [
        dict(item)
        for item in list(runtime_lanes_payload.get("full_live_validation") or [])
        if isinstance(item, dict)
    ]

    route_kind = str(runtime_assembly_payload.get("route_kind") or "").strip()
    route_id = str(runtime_assembly_payload.get("route_id") or "").strip()
    invocation_source = str(
        invocation_payload.get("source")
        or runtime_assembly_payload.get("invocation_source")
        or source
        or ""
    ).strip()
    ci_gate_status = _normalize_status(ci_gate_payload.get("status"), "warning")
    signoff_status = _normalize_status(human_signoffs_payload.get("status"), "skipped")
    final_status = "blocked" if bool(ci_gate_payload.get("should_block")) else _worst_status([ci_gate_status, signoff_status])

    events: List[Dict[str, Any]] = []

    def add_event(
        event_type: str,
        *,
        status: str,
        scope: str,
        summary: str,
        message: str = "",
        step_id: str = "",
        lane_id: str = "",
        details: Dict[str, Any] | None = None,
    ) -> None:
        events.append({
            "event_id": f"{event_type}_{len(events) + 1}",
            "event_type": str(event_type or "").strip(),
            "scope": str(scope or "").strip(),
            "order": len(events) + 1,
            "status": _normalize_status(status, "passed"),
            "occurred_at": str(generated_at or "").strip(),
            "step_id": str(step_id or "").strip(),
            "lane_id": str(lane_id or "").strip(),
            "summary": str(summary or "").strip(),
            "message": str(message or "").strip(),
            "details": dict(details or {}),
        })

    add_event(
        "run_started",
        status="passed",
        scope="run",
        summary=(
            f"route={route_kind or '-'} / invocation={invocation_source or '-'} / "
            f"build={release_build_id or '-'}"
        ),
        details={
            "route_id": route_id,
            "mode": str(invocation_payload.get("mode") or "").strip(),
            "providers": _clean_text_list(invocation_payload.get("providers")),
            "approvers": _clean_text_list(invocation_payload.get("approvers")),
        },
    )

    for item in workflow_step_items:
        step_id = str(item.get("step_id") or "").strip()
        add_event(
            "step_finished",
            status=_normalize_status(item.get("status"), "skipped"),
            scope="workflow_step",
            summary=f"{step_id or '-'} [{_normalize_status(item.get('status'), 'skipped')}]",
            message=str(item.get("message") or "").strip(),
            step_id=step_id,
            details={
                "label": str(item.get("label") or step_id or "").strip(),
                "outcome": str(item.get("outcome") or "").strip(),
                "always_run": bool(item.get("always_run")),
            },
        )

    for item in lane_items:
        lane_id = str(item.get("lane_id") or "").strip()
        add_event(
            "lane_reported",
            status=_normalize_status(item.get("status"), "skipped"),
            scope="runtime_lane",
            summary=f"{lane_id or '-'} [{_normalize_status(item.get('status'), 'skipped')}]",
            lane_id=lane_id,
            details={
                "label": str(item.get("label") or lane_id or "").strip(),
                "report_path": str(item.get("report_path") or "").strip(),
                "flow_statuses": dict(item.get("flow_statuses") or {}),
            },
        )

    add_event(
        "gate_evaluated",
        status=ci_gate_status,
        scope="automation_gate",
        summary=(
            f"ci_gate={ci_gate_status} / "
            f"blocking={','.join(_clean_text_list(ci_gate_payload.get('blocking_checks'))) or 'none'} / "
            f"warning={','.join(_clean_text_list(ci_gate_payload.get('warning_checks'))) or 'none'}"
        ),
        details={
            "should_block": bool(ci_gate_payload.get("should_block")),
            "fail_on_warnings": bool(ci_gate_payload.get("fail_on_warnings")),
            "evaluated_check_count": max(int(ci_gate_payload.get("evaluated_check_count") or 0), 0),
        },
    )

    add_event(
        "run_finished",
        status=final_status,
        scope="run",
        summary=f"automation={ci_gate_status} / signoffs={signoff_status}",
        details={
            "missing_signoffs": _clean_text_list(human_signoffs_payload.get("missing_signoffs")),
            "required_signoffs": _clean_text_list(human_signoffs_payload.get("required_signoffs")),
            "provided_signoffs": _clean_text_list(human_signoffs_payload.get("provided_signoffs")),
        },
    )

    blocked_event_count = sum(1 for item in events if item["status"] == "blocked")
    warning_event_count = sum(1 for item in events if item["status"] == "warning")
    latest_event = events[-1] if events else {}

    return {
        "schema_version": RELEASE_LIVE_EVENT_STREAM_SCHEMA_VERSION,
        "contract_versions": {
            "release_live_event_stream": RELEASE_LIVE_EVENT_STREAM_SCHEMA_VERSION,
        },
        "status": final_status,
        "summary": (
            f"events={len(events)} / blocked={blocked_event_count} / "
            f"warning={warning_event_count} / latest={str(latest_event.get('event_type') or '-').strip() or '-'}"
        ),
        "path": str(path or "").strip(),
        "source": str(source or "").strip(),
        "generated_at": str(generated_at or "").strip(),
        "target_channel": str(target_channel or "").strip(),
        "target_environment": str(target_environment or "").strip(),
        "release_build_id": str(release_build_id or "").strip(),
        "release_version": str(release_version or "").strip(),
        "release_channel": str(release_channel or "").strip(),
        "route_kind": route_kind,
        "route_id": route_id,
        "invocation_source": invocation_source,
        "event_count": len(events),
        "blocked_event_count": blocked_event_count,
        "warning_event_count": warning_event_count,
        "latest_event_type": str(latest_event.get("event_type") or "").strip(),
        "latest_event_status": str(latest_event.get("status") or "").strip(),
        "events": events,
    }


def build_release_live_event_stream_report_lines(
    summary: Dict[str, Any] | None,
    *,
    limit: int = 8,
) -> List[str]:
    normalized = dict(summary or {})
    lines = [
        f"- Status: {normalized.get('status') or 'warning'}",
        f"- Summary: {normalized.get('summary') or '-'}",
        (
            f"- Path: {normalized.get('path') or '-'} / "
            f"source={normalized.get('source') or '-'} / "
            f"generated_at={normalized.get('generated_at') or '-'}"
        ),
        (
            f"- Route: {normalized.get('route_kind') or '-'} / "
            f"route_id={normalized.get('route_id') or '-'} / "
            f"invocation={normalized.get('invocation_source') or '-'}"
        ),
        (
            f"- Build: {normalized.get('release_build_id') or '-'} / "
            f"version={normalized.get('release_version') or '-'} / "
            f"channel={normalized.get('release_channel') or '-'} / "
            f"target={normalized.get('target_channel') or '-'}->{normalized.get('target_environment') or '-'}"
        ),
        (
            f"- Counts: total={int(normalized.get('event_count') or 0)} / "
            f"blocked={int(normalized.get('blocked_event_count') or 0)} / "
            f"warning={int(normalized.get('warning_event_count') or 0)} / "
            f"latest={normalized.get('latest_event_type') or '-'} [{normalized.get('latest_event_status') or '-'}]"
        ),
    ]
    for item in [dict(event) for event in list(normalized.get("events") or [])[: max(int(limit or 0), 0)] if isinstance(event, dict)]:
        lines.append(
            f"- Event ({int(item.get('order') or 0)}): "
            f"{item.get('event_type') or '-'} "
            f"[{item.get('status') or '-'}] / "
            f"scope={item.get('scope') or '-'} / "
            f"step={item.get('step_id') or '-'} / "
            f"lane={item.get('lane_id') or '-'} / "
            f"summary={item.get('summary') or '-'}"
        )
    return lines


def _normalize_status(value: Any, default: str) -> str:
    normalized = str(value or "").strip().lower()
    return normalized if normalized in RELEASE_LIVE_EVENT_STATUSES else default


def _clean_text_list(values: Any) -> List[str]:
    result: List[str] = []
    for raw in list(values or []):
        value = str(raw or "").strip()
        if value and value not in result:
            result.append(value)
    return result


def _worst_status(values: List[Any]) -> str:
    priorities = {"blocked": 3, "warning": 2, "passed": 1, "skipped": 0}
    worst = "skipped"
    for raw in values:
        value = _normalize_status(raw, "skipped")
        if priorities[value] > priorities[worst]:
            worst = value
    return worst

"""
Release distribution bundle builder/exporter.

This closes the packaging gap between a versioned release directory and a
repeatable handoff bundle by generating:
- a machine-readable distribution manifest
- versioned install / upgrade / uninstall scripts
- copied release notes / QA gate / support matrix evidence
"""

from __future__ import annotations

import json
import hashlib
import re
import shutil
import subprocess
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from agent_system.contracts import normalize_release_distribution_bundle
from agent_system.tools.release_candidate import (
    DEFAULT_RELEASE_MANIFEST_PATH,
    _load_release_summary,
)
from agent_system.tools.release_boundary import (
    default_release_distribution_delivery_path,
    load_release_distribution_delivery_profile,
)


RELEASE_DISTRIBUTION_BUNDLE_SCHEMA_VERSION = "1.0"
DEFAULT_RELEASE_DISTRIBUTION_ROOT = "logs/reports/release_distribution"
DEFAULT_RELEASE_DISTRIBUTION_REPORT_TEMPLATE = "logs/reports/release_distribution_bundle_{target_channel}.json"
DEFAULT_RELEASE_DISTRIBUTION_INSTALL_SMOKE_ROOT = "logs/reports/release_distribution_smoke"
DEFAULT_RELEASE_DISTRIBUTION_INSTALL_SMOKE_REPORT_TEMPLATE = (
    "logs/reports/release_distribution_install_smoke_{target_channel}.json"
)
DEFAULT_RELEASE_DISTRIBUTION_PACKAGE_ROOT = "logs/reports/release_distribution_packages"
DEFAULT_RELEASE_DISTRIBUTION_CHANNEL_ROOT = "logs/reports/release_distribution_channels"
DEFAULT_RELEASE_DISTRIBUTION_HANDOFF_ROOT = "logs/reports/release_distribution_handoff"
DEFAULT_RELEASE_DISTRIBUTION_SIGNING_ROOT = "logs/reports/release_distribution_signing"
DEFAULT_RELEASE_DISTRIBUTION_PUBLISH_ROOT = "logs/reports/release_distribution_publish"
DEFAULT_RELEASE_DISTRIBUTION_PUBLISH_RECEIPTS_ROOT = "logs/reports/release_distribution_publish_receipts"
DEFAULT_RELEASE_DISTRIBUTION_CHANNEL_REPORT_TEMPLATE = "logs/reports/release_distribution_channel_{target_channel}.json"
_SAFE_SEGMENT_RE = re.compile(r"[^A-Za-z0-9._-]+")


def _relative_to_root(path: Optional[Path], runtime_root: Path) -> str:
    if path is None:
        return ""
    candidate = Path(path)
    if not candidate.is_absolute():
        candidate = runtime_root / candidate
    try:
        return candidate.absolute().relative_to(runtime_root.absolute()).as_posix()
    except Exception:
        return str(candidate.absolute())


def default_release_distribution_report_path(*, target_channel: str = "staging") -> str:
    normalized_target = str(target_channel or "staging").strip().lower() or "staging"
    return DEFAULT_RELEASE_DISTRIBUTION_REPORT_TEMPLATE.format(target_channel=normalized_target)


def default_release_distribution_install_smoke_report_path(*, target_channel: str = "staging") -> str:
    normalized_target = str(target_channel or "staging").strip().lower() or "staging"
    return DEFAULT_RELEASE_DISTRIBUTION_INSTALL_SMOKE_REPORT_TEMPLATE.format(target_channel=normalized_target)


def default_release_distribution_bundle_dir(*, target_channel: str = "staging", build_id: str = "") -> str:
    normalized_target = str(target_channel or "staging").strip().lower() or "staging"
    normalized_build = _safe_segment(build_id or f"{normalized_target}-bundle")
    return f"{DEFAULT_RELEASE_DISTRIBUTION_ROOT}/{normalized_target}/{normalized_build}"


def default_release_distribution_install_smoke_dir(*, target_channel: str = "staging", build_id: str = "") -> str:
    normalized_target = str(target_channel or "staging").strip().lower() or "staging"
    normalized_build = _safe_segment(build_id or f"{normalized_target}-bundle")
    return f"{DEFAULT_RELEASE_DISTRIBUTION_INSTALL_SMOKE_ROOT}/{normalized_target}/{normalized_build}"


def default_release_distribution_archive_dir(*, target_channel: str = "staging", build_id: str = "") -> str:
    normalized_target = str(target_channel or "staging").strip().lower() or "staging"
    normalized_build = _safe_segment(build_id or f"{normalized_target}-bundle")
    return f"{DEFAULT_RELEASE_DISTRIBUTION_PACKAGE_ROOT}/{normalized_target}/{normalized_build}"


def default_release_distribution_archive_path(*, target_channel: str = "staging", build_id: str = "") -> str:
    archive_dir = default_release_distribution_archive_dir(
        target_channel=target_channel,
        build_id=build_id,
    )
    return f"{archive_dir}/release_distribution_bundle.zip"


def default_release_distribution_archive_sha256_path(*, target_channel: str = "staging", build_id: str = "") -> str:
    archive_dir = default_release_distribution_archive_dir(
        target_channel=target_channel,
        build_id=build_id,
    )
    return f"{archive_dir}/release_distribution_bundle.sha256"


def default_release_distribution_handoff_dir(*, target_channel: str = "staging", build_id: str = "") -> str:
    normalized_target = str(target_channel or "staging").strip().lower() or "staging"
    normalized_build = _safe_segment(build_id or f"{normalized_target}-bundle")
    return f"{DEFAULT_RELEASE_DISTRIBUTION_HANDOFF_ROOT}/{normalized_target}/{normalized_build}"


def default_release_distribution_signing_handoff_dir(*, target_channel: str = "staging", build_id: str = "") -> str:
    normalized_target = str(target_channel or "staging").strip().lower() or "staging"
    normalized_build = _safe_segment(build_id or f"{normalized_target}-bundle")
    return f"{DEFAULT_RELEASE_DISTRIBUTION_SIGNING_ROOT}/{normalized_target}/{normalized_build}"


def default_release_distribution_publish_handoff_dir(*, target_channel: str = "staging", build_id: str = "") -> str:
    normalized_target = str(target_channel or "staging").strip().lower() or "staging"
    normalized_build = _safe_segment(build_id or f"{normalized_target}-bundle")
    return f"{DEFAULT_RELEASE_DISTRIBUTION_PUBLISH_ROOT}/{normalized_target}/{normalized_build}"


def default_release_distribution_publish_receipts_dir(*, target_channel: str = "staging", build_id: str = "") -> str:
    normalized_target = str(target_channel or "staging").strip().lower() or "staging"
    normalized_build = _safe_segment(build_id or f"{normalized_target}-bundle")
    return f"{DEFAULT_RELEASE_DISTRIBUTION_PUBLISH_RECEIPTS_ROOT}/{normalized_target}/{normalized_build}"


def default_release_distribution_channel_report_path(*, target_channel: str = "staging") -> str:
    normalized_target = str(target_channel or "staging").strip().lower() or "staging"
    return DEFAULT_RELEASE_DISTRIBUTION_CHANNEL_REPORT_TEMPLATE.format(target_channel=normalized_target)


def default_release_distribution_channel_dir(*, target_channel: str = "staging") -> str:
    normalized_target = str(target_channel or "staging").strip().lower() or "staging"
    return f"{DEFAULT_RELEASE_DISTRIBUTION_CHANNEL_ROOT}/{normalized_target}"


def default_release_distribution_channel_latest_path(*, target_channel: str = "staging") -> str:
    channel_dir = default_release_distribution_channel_dir(target_channel=target_channel)
    return f"{channel_dir}/latest.json"


def default_release_distribution_channel_releases_path(*, target_channel: str = "staging") -> str:
    channel_dir = default_release_distribution_channel_dir(target_channel=target_channel)
    return f"{channel_dir}/releases.json"


def build_release_distribution_bundle(
    project_root: str | Path,
    runtime_root: Optional[str | Path] = None,
    *,
    target_channel: str = "",
    target_environment: str = "",
    release_manifest_path: str = "",
    report_path: str = "",
) -> Dict[str, Any]:
    resolved_project_root = Path(project_root).resolve()
    resolved_runtime_root = Path(runtime_root or Path.cwd()).resolve()
    normalized_target_channel = str(target_channel or "staging").strip().lower() or "staging"
    normalized_target_environment = str(target_environment or "").strip() or (
        "production" if normalized_target_channel == "release" else normalized_target_channel
    )
    manifest_state = _load_release_summary(
        resolved_runtime_root,
        release_manifest_path or DEFAULT_RELEASE_MANIFEST_PATH,
    )
    release_summary = dict(manifest_state.get("release_summary") or {})
    build_id = str(release_summary.get("build_id") or "").strip()
    version = str(release_summary.get("version") or "").strip()
    release_channel = str(release_summary.get("channel") or "").strip().lower()
    bundle_dir_relative = default_release_distribution_bundle_dir(
        target_channel=normalized_target_channel,
        build_id=build_id or f"{release_channel or normalized_target_channel}-{version or 'bundle'}",
    )
    bundle_dir = (resolved_runtime_root / bundle_dir_relative).resolve()
    report_relative = str(report_path or default_release_distribution_report_path(target_channel=normalized_target_channel)).strip()
    report_file = (resolved_runtime_root / report_relative).resolve()
    install_smoke_report_relative = default_release_distribution_install_smoke_report_path(
        target_channel=normalized_target_channel,
    )
    install_smoke_report_file = (resolved_runtime_root / install_smoke_report_relative).resolve()
    install_smoke_report = _read_json(install_smoke_report_file)
    channel_index_report_relative = default_release_distribution_channel_report_path(
        target_channel=normalized_target_channel,
    )
    channel_index_dir_relative = default_release_distribution_channel_dir(
        target_channel=normalized_target_channel,
    )
    channel_index_latest_relative = default_release_distribution_channel_latest_path(
        target_channel=normalized_target_channel,
    )
    channel_index_releases_relative = default_release_distribution_channel_releases_path(
        target_channel=normalized_target_channel,
    )
    channel_index_report_file = (resolved_runtime_root / channel_index_report_relative).resolve()
    channel_index_dir = (resolved_runtime_root / channel_index_dir_relative).resolve()
    channel_index_latest_path = (resolved_runtime_root / channel_index_latest_relative).resolve()
    channel_index_releases_path = (resolved_runtime_root / channel_index_releases_relative).resolve()
    channel_index_latest = _read_json(channel_index_latest_path)
    channel_index_releases = _read_json(channel_index_releases_path)
    release_dir_path = manifest_state.get("release_dir_path")
    delivery_profile = load_release_distribution_delivery_profile(
        resolved_project_root,
        target_channel=normalized_target_channel,
        target_environment=normalized_target_environment,
    )

    distribution_manifest_relative = f"{bundle_dir_relative}/distribution_manifest.json"
    install_script_relative = f"{bundle_dir_relative}/install_release_bundle.ps1"
    upgrade_script_relative = f"{bundle_dir_relative}/upgrade_release_bundle.ps1"
    uninstall_script_relative = f"{bundle_dir_relative}/uninstall_release_bundle.ps1"
    support_matrix_relative = f"{bundle_dir_relative}/support_matrix.md"
    bundle_manifest_copy_relative = f"{bundle_dir_relative}/release_manifest.json"
    bundle_release_notes_relative = f"{bundle_dir_relative}/release_notes.md"
    bundle_qa_gate_relative = f"{bundle_dir_relative}/qa_gate_report.md"
    payload_dir_relative = f"{bundle_dir_relative}/release_payload"
    state_manifest_relative = f"{bundle_dir_relative}/installed_release.example.json"
    archive_dir_relative = default_release_distribution_archive_dir(
        target_channel=normalized_target_channel,
        build_id=build_id or f"{release_channel or normalized_target_channel}-{version or 'bundle'}",
    )
    archive_path_relative = default_release_distribution_archive_path(
        target_channel=normalized_target_channel,
        build_id=build_id or f"{release_channel or normalized_target_channel}-{version or 'bundle'}",
    )
    archive_sha256_path_relative = default_release_distribution_archive_sha256_path(
        target_channel=normalized_target_channel,
        build_id=build_id or f"{release_channel or normalized_target_channel}-{version or 'bundle'}",
    )
    handoff_dir_relative = default_release_distribution_handoff_dir(
        target_channel=normalized_target_channel,
        build_id=build_id or f"{release_channel or normalized_target_channel}-{version or 'bundle'}",
    )
    handoff_manifest_relative = f"{handoff_dir_relative}/distribution_handoff_manifest.json"
    handoff_install_script_relative = f"{handoff_dir_relative}/install_release_handoff.ps1"
    handoff_upgrade_script_relative = f"{handoff_dir_relative}/upgrade_release_handoff.ps1"
    handoff_uninstall_script_relative = f"{handoff_dir_relative}/uninstall_release_handoff.ps1"
    handoff_archive_relative = f"{handoff_dir_relative}/packages/release_distribution_bundle.zip"
    handoff_archive_sha256_relative = f"{handoff_dir_relative}/packages/release_distribution_bundle.sha256"
    handoff_channel_latest_relative = f"{handoff_dir_relative}/channel/latest.json"
    handoff_channel_releases_relative = f"{handoff_dir_relative}/channel/releases.json"
    signing_handoff_dir_relative = default_release_distribution_signing_handoff_dir(
        target_channel=normalized_target_channel,
        build_id=build_id or f"{release_channel or normalized_target_channel}-{version or 'bundle'}",
    )
    signing_handoff_manifest_relative = f"{signing_handoff_dir_relative}/distribution_signing_manifest.json"
    signing_handoff_instructions_relative = f"{signing_handoff_dir_relative}/SIGNING_INSTRUCTIONS.md"
    signing_handoff_unsigned_archive_relative = f"{signing_handoff_dir_relative}/unsigned/release_distribution_bundle.zip"
    signing_handoff_unsigned_archive_sha256_relative = (
        f"{signing_handoff_dir_relative}/unsigned/release_distribution_bundle.sha256"
    )
    publish_handoff_dir_relative = default_release_distribution_publish_handoff_dir(
        target_channel=normalized_target_channel,
        build_id=build_id or f"{release_channel or normalized_target_channel}-{version or 'bundle'}",
    )
    publish_handoff_manifest_relative = f"{publish_handoff_dir_relative}/distribution_publish_manifest.json"
    publish_handoff_instructions_relative = f"{publish_handoff_dir_relative}/PUBLISH_INSTRUCTIONS.md"
    publish_handoff_archive_relative = f"{publish_handoff_dir_relative}/payload/release_distribution_bundle.zip"
    publish_handoff_archive_sha256_relative = f"{publish_handoff_dir_relative}/payload/release_distribution_bundle.sha256"
    publish_handoff_channel_latest_relative = f"{publish_handoff_dir_relative}/metadata/channel_latest.json"
    publish_handoff_channel_releases_relative = f"{publish_handoff_dir_relative}/metadata/channel_releases.json"
    publish_receipts_dir_relative = default_release_distribution_publish_receipts_dir(
        target_channel=normalized_target_channel,
        build_id=build_id or f"{release_channel or normalized_target_channel}-{version or 'bundle'}",
    )
    publish_receipts_manifest_relative = f"{publish_receipts_dir_relative}/publish_receipts_manifest.json"

    distribution_manifest_path = (resolved_runtime_root / distribution_manifest_relative).resolve()
    install_script_path = (resolved_runtime_root / install_script_relative).resolve()
    upgrade_script_path = (resolved_runtime_root / upgrade_script_relative).resolve()
    uninstall_script_path = (resolved_runtime_root / uninstall_script_relative).resolve()
    support_matrix_path = (resolved_runtime_root / support_matrix_relative).resolve()
    bundle_manifest_copy_path = (resolved_runtime_root / bundle_manifest_copy_relative).resolve()
    bundle_release_notes_path = (resolved_runtime_root / bundle_release_notes_relative).resolve()
    bundle_qa_gate_path = (resolved_runtime_root / bundle_qa_gate_relative).resolve()
    payload_dir = (resolved_runtime_root / payload_dir_relative).resolve()
    state_manifest_path = (resolved_runtime_root / state_manifest_relative).resolve()
    archive_dir = (resolved_runtime_root / archive_dir_relative).resolve()
    archive_path = (resolved_runtime_root / archive_path_relative).resolve()
    archive_sha256_path = (resolved_runtime_root / archive_sha256_path_relative).resolve()
    handoff_dir = (resolved_runtime_root / handoff_dir_relative).resolve()
    handoff_manifest_path = (resolved_runtime_root / handoff_manifest_relative).resolve()
    handoff_install_script_path = (resolved_runtime_root / handoff_install_script_relative).resolve()
    handoff_upgrade_script_path = (resolved_runtime_root / handoff_upgrade_script_relative).resolve()
    handoff_uninstall_script_path = (resolved_runtime_root / handoff_uninstall_script_relative).resolve()
    handoff_archive_path = (resolved_runtime_root / handoff_archive_relative).resolve()
    handoff_archive_sha256_path = (resolved_runtime_root / handoff_archive_sha256_relative).resolve()
    handoff_channel_latest_path = (resolved_runtime_root / handoff_channel_latest_relative).resolve()
    handoff_channel_releases_path = (resolved_runtime_root / handoff_channel_releases_relative).resolve()
    signing_handoff_dir = (resolved_runtime_root / signing_handoff_dir_relative).resolve()
    signing_handoff_manifest_path = (resolved_runtime_root / signing_handoff_manifest_relative).resolve()
    signing_handoff_instructions_path = (resolved_runtime_root / signing_handoff_instructions_relative).resolve()
    signing_handoff_unsigned_archive_path = (resolved_runtime_root / signing_handoff_unsigned_archive_relative).resolve()
    signing_handoff_unsigned_archive_sha256_path = (
        resolved_runtime_root / signing_handoff_unsigned_archive_sha256_relative
    ).resolve()
    publish_handoff_dir = (resolved_runtime_root / publish_handoff_dir_relative).resolve()
    publish_handoff_manifest_path = (resolved_runtime_root / publish_handoff_manifest_relative).resolve()
    publish_handoff_instructions_path = (resolved_runtime_root / publish_handoff_instructions_relative).resolve()
    publish_handoff_archive_path = (resolved_runtime_root / publish_handoff_archive_relative).resolve()
    publish_handoff_archive_sha256_path = (resolved_runtime_root / publish_handoff_archive_sha256_relative).resolve()
    publish_handoff_channel_latest_path = (resolved_runtime_root / publish_handoff_channel_latest_relative).resolve()
    publish_handoff_channel_releases_path = (resolved_runtime_root / publish_handoff_channel_releases_relative).resolve()
    publish_receipts_dir = (resolved_runtime_root / publish_receipts_dir_relative).resolve()
    publish_receipts_manifest_path = (resolved_runtime_root / publish_receipts_manifest_relative).resolve()

    source_support_matrix = (resolved_project_root / "docs" / "支持矩阵与分发说明.md").resolve()
    source_bootstrap_script = (resolved_project_root / "tools" / "bootstrap_clean_machine.ps1").resolve()

    payload_file_count = _count_files(payload_dir)
    bundle_file_count = _count_files(bundle_dir)
    handoff_file_count = _count_files(handoff_dir)
    signing_handoff_file_count = _count_files(signing_handoff_dir)
    publish_handoff_file_count = _count_files(publish_handoff_dir)
    publish_receipts_file_count = _count_files(publish_receipts_dir)
    exported_files = _relative_list(
        (path for path in bundle_dir.rglob("*") if path.is_file()),
        root=resolved_runtime_root,
    )

    source_missing_items: List[str] = []
    if not bool(manifest_state.get("manifest_exists")):
        source_missing_items.append("release_manifest")
    if not build_id or not version or not release_channel:
        source_missing_items.append("build_metadata")
    if not bool(release_dir_path and Path(release_dir_path).exists()):
        source_missing_items.append("release_dir")
    if not bool(manifest_state.get("release_notes_exists")):
        source_missing_items.append("release_notes")
    if not bool(manifest_state.get("qa_gate_report_exists")):
        source_missing_items.append("qa_gate_report")
    if not source_support_matrix.exists():
        source_missing_items.append("support_matrix")
    if not source_bootstrap_script.exists():
        source_missing_items.append("bootstrap_script")

    bundle_missing_items: List[str] = []
    if not distribution_manifest_path.exists():
        bundle_missing_items.append("distribution_manifest")
    if not install_script_path.exists():
        bundle_missing_items.append("install_script")
    if not upgrade_script_path.exists():
        bundle_missing_items.append("upgrade_script")
    if not uninstall_script_path.exists():
        bundle_missing_items.append("uninstall_script")
    if not support_matrix_path.exists():
        bundle_missing_items.append("support_matrix_copy")
    if not bundle_manifest_copy_path.exists():
        bundle_missing_items.append("release_manifest_copy")
    if not bundle_release_notes_path.exists():
        bundle_missing_items.append("release_notes_copy")
    if not bundle_qa_gate_path.exists():
        bundle_missing_items.append("qa_gate_report_copy")
    if payload_file_count <= 0:
        bundle_missing_items.append("release_payload")
    if not state_manifest_path.exists():
        bundle_missing_items.append("installed_state_example")

    if source_missing_items or bundle_missing_items:
        install_smoke_status = "skipped"
        install_smoke_summary = "distribution bundle not ready for install smoke"
    elif install_smoke_report:
        smoke_build_id = str(install_smoke_report.get("build_id") or "").strip()
        smoke_bundle_dir = str(install_smoke_report.get("bundle_dir") or "").strip()
        if smoke_build_id != build_id or (smoke_bundle_dir and smoke_bundle_dir != bundle_dir_relative):
            install_smoke_status = "warning"
            install_smoke_summary = "distribution install smoke report does not match current bundle"
        else:
            install_smoke_status = str(install_smoke_report.get("status") or "warning").strip().lower() or "warning"
            install_smoke_summary = (
                str(install_smoke_report.get("summary") or "").strip() or "distribution install smoke completed"
            )
    else:
        install_smoke_status = "warning"
        install_smoke_summary = "distribution install smoke report missing"

    install_smoke_install_result = _as_dict(install_smoke_report.get("install_result"))
    install_smoke_upgrade_result = _as_dict(install_smoke_report.get("upgrade_result"))
    install_smoke_uninstall_result = _as_dict(install_smoke_report.get("uninstall_result"))

    if source_missing_items or bundle_missing_items or install_smoke_status != "passed":
        archive_status = "skipped"
        archive_summary = "distribution archive not ready"
    elif archive_path.exists() and archive_sha256_path.exists():
        archive_status = "passed"
        archive_summary = (
            f"archive ready / size={archive_path.stat().st_size} bytes / sha256={'yes' if archive_sha256_path.exists() else 'no'}"
        )
    else:
        archive_status = "warning"
        archive_summary = "distribution archive missing"

    channel_index_items = [
        dict(item)
        for item in list(channel_index_releases.get("items") or [])
        if isinstance(item, dict)
    ]
    channel_index_latest_build_id = str(channel_index_latest.get("build_id") or "").strip()
    channel_index_latest_matches_current = (
        channel_index_latest_build_id == build_id
        and str(channel_index_latest.get("bundle_dir") or "").strip() == bundle_dir_relative
        and str(channel_index_latest.get("archive_path") or "").strip() == archive_path_relative
    )
    channel_index_has_current_release = any(
        str(item.get("build_id") or "").strip() == build_id
        and str(item.get("archive_path") or "").strip() == archive_path_relative
        for item in channel_index_items
    )
    if source_missing_items or bundle_missing_items or install_smoke_status != "passed" or archive_status != "passed":
        channel_index_status = "skipped"
        channel_index_summary = "distribution channel index not ready"
    elif (
        not channel_index_report_file.exists()
        or not channel_index_latest_path.exists()
        or not channel_index_releases_path.exists()
    ):
        channel_index_status = "warning"
        channel_index_summary = "distribution channel index missing"
    elif not channel_index_latest_matches_current or not channel_index_has_current_release:
        channel_index_status = "warning"
        channel_index_summary = "distribution channel index does not match current bundle"
    else:
        channel_index_status = "passed"
        channel_index_summary = (
            f"channel index ready / releases={len(channel_index_items)} / latest={channel_index_latest_build_id or '-'}"
        )

    handoff_missing_items: List[str] = []
    if not handoff_manifest_path.exists():
        handoff_missing_items.append("handoff_manifest")
    if not handoff_install_script_path.exists():
        handoff_missing_items.append("handoff_install_script")
    if not handoff_upgrade_script_path.exists():
        handoff_missing_items.append("handoff_upgrade_script")
    if not handoff_uninstall_script_path.exists():
        handoff_missing_items.append("handoff_uninstall_script")
    if not handoff_archive_path.exists():
        handoff_missing_items.append("handoff_archive")
    if not handoff_archive_sha256_path.exists():
        handoff_missing_items.append("handoff_archive_sha256")
    if not handoff_channel_latest_path.exists():
        handoff_missing_items.append("handoff_channel_latest")
    if not handoff_channel_releases_path.exists():
        handoff_missing_items.append("handoff_channel_releases")
    if (
        source_missing_items
        or bundle_missing_items
        or install_smoke_status != "passed"
        or archive_status != "passed"
        or channel_index_status != "passed"
    ):
        handoff_status = "skipped"
        handoff_summary = "distribution handoff not ready"
    elif handoff_missing_items:
        handoff_status = "warning"
        handoff_summary = "distribution handoff package missing"
    else:
        handoff_status = "passed"
        handoff_summary = f"distribution handoff ready / files={handoff_file_count}"

    signing_handoff_missing_items: List[str] = []
    if not signing_handoff_manifest_path.exists():
        signing_handoff_missing_items.append("signing_handoff_manifest")
    if not signing_handoff_instructions_path.exists():
        signing_handoff_missing_items.append("signing_handoff_instructions")
    if not signing_handoff_unsigned_archive_path.exists():
        signing_handoff_missing_items.append("signing_unsigned_archive")
    if not signing_handoff_unsigned_archive_sha256_path.exists():
        signing_handoff_missing_items.append("signing_unsigned_archive_sha256")

    delivery_signing_required = bool(delivery_profile.get("signing_required"))
    delivery_signing_mode = str(delivery_profile.get("signing_mode") or "").strip().lower()
    if (
        source_missing_items
        or bundle_missing_items
        or install_smoke_status != "passed"
        or archive_status != "passed"
    ):
        signing_handoff_status = "skipped"
        signing_handoff_summary = "distribution signing handoff not ready"
    elif not delivery_signing_required or delivery_signing_mode in {"sha256_only", "codesigned", "signed_archive", "notarized"}:
        signing_handoff_status = "skipped"
        signing_handoff_summary = "external signing handoff not required"
    elif signing_handoff_missing_items:
        signing_handoff_status = "warning"
        signing_handoff_summary = "distribution signing handoff missing"
    else:
        signing_handoff_status = "passed"
        signing_handoff_summary = f"distribution signing handoff ready / files={signing_handoff_file_count}"
    if signing_handoff_status != "warning":
        signing_handoff_missing_items = []

    publish_handoff_missing_items: List[str] = []
    if not publish_handoff_manifest_path.exists():
        publish_handoff_missing_items.append("publish_handoff_manifest")
    if not publish_handoff_instructions_path.exists():
        publish_handoff_missing_items.append("publish_handoff_instructions")
    if not publish_handoff_archive_path.exists():
        publish_handoff_missing_items.append("publish_archive")
    if not publish_handoff_archive_sha256_path.exists():
        publish_handoff_missing_items.append("publish_archive_sha256")
    if not publish_handoff_channel_latest_path.exists():
        publish_handoff_missing_items.append("publish_channel_latest")
    if not publish_handoff_channel_releases_path.exists():
        publish_handoff_missing_items.append("publish_channel_releases")

    delivery_publish_targets = list(delivery_profile.get("publish_targets") or [])
    if (
        source_missing_items
        or bundle_missing_items
        or install_smoke_status != "passed"
        or archive_status != "passed"
        or channel_index_status != "passed"
    ):
        publish_handoff_status = "skipped"
        publish_handoff_summary = "distribution publish handoff not ready"
    elif not delivery_publish_targets:
        publish_handoff_status = "skipped"
        publish_handoff_summary = "external publish handoff not required"
    elif publish_handoff_missing_items:
        publish_handoff_status = "warning"
        publish_handoff_summary = "distribution publish handoff missing"
    else:
        publish_handoff_status = "passed"
        publish_handoff_summary = f"distribution publish handoff ready / files={publish_handoff_file_count}"
    if publish_handoff_status != "warning":
        publish_handoff_missing_items = []

    publish_receipts_manifest = _read_json(publish_receipts_manifest_path)
    publish_receipts_entries = [
        dict(item)
        for item in list(publish_receipts_manifest.get("receipts") or [])
        if isinstance(item, dict)
    ]
    publish_receipts_recorded_targets: List[str] = []
    publish_receipts_completed_targets: List[str] = []
    publish_receipts_failed_targets: List[str] = []
    publish_receipts_manifest_matches_current = (
        not publish_receipts_manifest
        or (
            str(publish_receipts_manifest.get("build_id") or "").strip() == build_id
            and str(publish_receipts_manifest.get("version") or "").strip() == version
            and str(publish_receipts_manifest.get("target_channel") or "").strip() == normalized_target_channel
            and str(publish_receipts_manifest.get("target_environment") or "").strip() == normalized_target_environment
        )
    )
    for entry in publish_receipts_entries:
        target_id = str(entry.get("target_id") or "").strip()
        if not target_id:
            continue
        publish_receipts_recorded_targets.append(target_id)
        receipt_path_text = str(entry.get("receipt_path") or "").strip()
        receipt_status = str(entry.get("status") or "").strip().lower()
        receipt_exists = False
        if receipt_path_text:
            receipt_file = (publish_receipts_dir / receipt_path_text).resolve()
            receipt_exists = receipt_file.exists() and receipt_file.is_file()
        if receipt_exists and receipt_status in {"published", "verified"}:
            publish_receipts_completed_targets.append(target_id)
        elif receipt_status in {"failed", "error"}:
            publish_receipts_failed_targets.append(target_id)
    publish_receipts_recorded_targets = _clean_text_list(publish_receipts_recorded_targets)
    publish_receipts_completed_targets = _clean_text_list(publish_receipts_completed_targets)
    publish_receipts_failed_targets = _clean_text_list(publish_receipts_failed_targets)
    publish_receipts_missing_targets = [
        item for item in delivery_publish_targets if item not in publish_receipts_completed_targets
    ]
    if not delivery_publish_targets:
        publish_receipts_status = "skipped"
        publish_receipts_summary = "publish receipts not required"
    elif publish_handoff_status != "passed":
        publish_receipts_status = "skipped"
        publish_receipts_summary = "publish receipts not ready"
    elif not publish_receipts_manifest_path.exists():
        publish_receipts_status = "warning"
        publish_receipts_summary = "publish receipts manifest missing"
    elif not publish_receipts_manifest_matches_current:
        publish_receipts_status = "warning"
        publish_receipts_summary = "publish receipts manifest does not match current release"
    elif publish_receipts_failed_targets:
        publish_receipts_status = "warning"
        publish_receipts_summary = f"publish receipts recorded failures / targets={len(publish_receipts_failed_targets)}"
    elif publish_receipts_missing_targets:
        publish_receipts_status = "warning"
        publish_receipts_summary = f"publish receipts pending / completed={len(publish_receipts_completed_targets)} / required={len(delivery_publish_targets)}"
    else:
        publish_receipts_status = "passed"
        publish_receipts_summary = f"publish receipts ready / targets={len(publish_receipts_completed_targets)}"

    notes = [
        f"manifest_source={manifest_state.get('manifest_source') or 'missing'}",
        f"build={build_id or '-'} / version={version or '-'} / channel={release_channel or '-'}",
        f"bundle_dir={bundle_dir_relative}",
        f"payload_files={payload_file_count} / bundle_files={bundle_file_count}",
        f"install_smoke={install_smoke_status}",
        f"archive={archive_status}",
        f"channel_index={channel_index_status}",
        f"handoff={handoff_status}",
        f"signing_handoff={signing_handoff_status}",
        f"publish_handoff={publish_handoff_status}",
        f"publish_receipts={publish_receipts_status}",
        f"external_delivery={delivery_profile.get('status') or 'warning'}",
    ]
    if delivery_profile.get("profile_id"):
        notes.append(f"delivery_profile={delivery_profile.get('profile_id')}")
    if delivery_profile.get("primary_installer"):
        notes.append(f"delivery_installer={delivery_profile.get('primary_installer')}")
    if delivery_profile.get("signing_mode"):
        notes.append(f"delivery_signing_mode={delivery_profile.get('signing_mode')}")
    recommendations: List[str] = []
    if source_missing_items:
        recommendations.append(
            "先补齐 release manifest、versioned release 目录、QA gate 和支持矩阵，再导出 distribution bundle。"
        )
    if bundle_missing_items:
        recommendations.append(
            "运行 `python tools/export_release_distribution_bundle.py --project-root . --runtime-root . --channel "
            f"{normalized_target_channel}` 生成版本化 distribution bundle。"
        )
    if not source_missing_items and not bundle_missing_items and install_smoke_status != "passed":
        recommendations.append(
            "运行 `python tools/export_release_distribution_install_smoke.py --project-root . --runtime-root . --channel "
            f"{normalized_target_channel}` 验证 install / upgrade / uninstall 脚本。"
        )
    if not source_missing_items and not bundle_missing_items and install_smoke_status == "passed":
        recommendations.append("当前 distribution bundle 已齐备，可把 versioned 目录交给 QA / 发布执行侧复用。")
    if not source_missing_items and not bundle_missing_items and install_smoke_status == "passed" and archive_status != "passed":
        recommendations.append(
            "运行 `python tools/export_release_distribution_archive.py --project-root . --runtime-root . --channel "
            f"{normalized_target_channel}` 生成可交付 zip 包和 sha256 校验文件。"
        )
    if (
        not source_missing_items
        and not bundle_missing_items
        and install_smoke_status == "passed"
        and archive_status == "passed"
        and channel_index_status != "passed"
    ):
        recommendations.append(
            "运行 `python tools/export_release_distribution_channel_index.py --project-root . --runtime-root . --channel "
            f"{normalized_target_channel}` 生成渠道 latest / releases 索引。"
        )
    if (
        not source_missing_items
        and not bundle_missing_items
        and install_smoke_status == "passed"
        and archive_status == "passed"
        and channel_index_status == "passed"
        and handoff_status != "passed"
    ):
        recommendations.append(
            "运行 `python tools/export_release_distribution_handoff.py --project-root . --runtime-root . --channel "
            f"{normalized_target_channel}` 生成可直接交给 QA / 发布执行侧的 handoff 安装包目录。"
        )
    if (
        not source_missing_items
        and not bundle_missing_items
        and install_smoke_status == "passed"
        and archive_status == "passed"
        and delivery_signing_required
        and delivery_signing_mode not in {"sha256_only", "codesigned", "signed_archive", "notarized"}
        and signing_handoff_status != "passed"
    ):
        recommendations.append(
            "运行 `python tools/export_release_distribution_signing_handoff.py --project-root . --runtime-root . --channel "
            f"{normalized_target_channel}` 生成可交给外部签名环节消费的 signing intake 包。"
        )
    if (
        not source_missing_items
        and not bundle_missing_items
        and install_smoke_status == "passed"
        and archive_status == "passed"
        and channel_index_status == "passed"
        and delivery_publish_targets
        and publish_handoff_status != "passed"
    ):
        recommendations.append(
            "运行 `python tools/export_release_distribution_publish_handoff.py --project-root . --runtime-root . --channel "
            f"{normalized_target_channel}` 生成可交给外部分发/渠道发布侧消费的 publish intake 包。"
        )
    if (
        not source_missing_items
        and not bundle_missing_items
        and publish_handoff_status == "passed"
        and delivery_publish_targets
        and publish_receipts_status != "passed"
    ):
        recommendations.append(
            "运行 `python tools/record_release_distribution_publish_receipt.py --project-root . --runtime-root . --channel "
            f"{normalized_target_channel} --target-id <publish_target>` 记录外部分发回执。"
        )
    recommendations.extend(list(delivery_profile.get("recommendations") or []))

    archive_required = normalized_target_channel == "release"
    channel_index_required = normalized_target_channel == "release"
    status = "blocked" if source_missing_items else (
        "warning"
        if (
            bundle_missing_items
            or install_smoke_status != "passed"
            or (archive_required and archive_status != "passed")
            or (channel_index_required and channel_index_status != "passed")
        )
        else "passed"
    )
    summary = (
        f"source={'missing' if source_missing_items else 'ready'} / "
        f"bundle={'missing' if bundle_missing_items else 'ready'} / "
        f"install_smoke={install_smoke_status} / archive={archive_status} / channel_index={channel_index_status} / "
        f"payload_files={payload_file_count} / bundle_files={bundle_file_count}"
    )
    return normalize_release_distribution_bundle({
        "schema_version": RELEASE_DISTRIBUTION_BUNDLE_SCHEMA_VERSION,
        "status": status,
        "summary": summary,
        "target_channel": normalized_target_channel,
        "target_environment": normalized_target_environment,
        "build_id": build_id,
        "version": version,
        "release_channel": release_channel,
        "release_manifest_path": str(manifest_state.get("manifest_path") or ""),
        "release_manifest_source": str(manifest_state.get("manifest_source") or ""),
        "release_notes_path": str(manifest_state.get("release_notes_path") or ""),
        "qa_gate_report_path": str(manifest_state.get("qa_gate_report_path") or ""),
        "build_log_path": str(manifest_state.get("build_log_path") or ""),
        "release_dir": _relative_to_root(release_dir_path, resolved_runtime_root) if release_dir_path else "",
        "output_path": str(release_summary.get("output_path") or "").replace("\\", "/"),
        "release_url": str(release_summary.get("release_url") or ""),
        "versioned_release_url": str(release_summary.get("versioned_release_url") or ""),
        "bundle_root": DEFAULT_RELEASE_DISTRIBUTION_ROOT,
        "bundle_dir": bundle_dir_relative,
        "bundle_exists": bundle_dir.exists(),
        "bundle_file_count": bundle_file_count,
        "payload_dir": payload_dir_relative,
        "payload_exists": payload_dir.exists(),
        "payload_file_count": payload_file_count,
        "distribution_manifest_path": distribution_manifest_relative,
        "distribution_manifest_exists": distribution_manifest_path.exists(),
        "install_script_path": install_script_relative,
        "install_script_exists": install_script_path.exists(),
        "upgrade_script_path": upgrade_script_relative,
        "upgrade_script_exists": upgrade_script_path.exists(),
        "uninstall_script_path": uninstall_script_relative,
        "uninstall_script_exists": uninstall_script_path.exists(),
        "support_matrix_source_path": _relative_to_root(source_support_matrix, resolved_project_root),
        "support_matrix_path": support_matrix_relative,
        "support_matrix_exists": support_matrix_path.exists(),
        "bootstrap_script_source_path": _relative_to_root(source_bootstrap_script, resolved_project_root),
        "bundle_manifest_copy_path": bundle_manifest_copy_relative,
        "bundle_manifest_copy_exists": bundle_manifest_copy_path.exists(),
        "bundle_release_notes_path": bundle_release_notes_relative,
        "bundle_release_notes_exists": bundle_release_notes_path.exists(),
        "bundle_qa_gate_report_path": bundle_qa_gate_relative,
        "bundle_qa_gate_report_exists": bundle_qa_gate_path.exists(),
        "state_manifest_path": state_manifest_relative,
        "state_manifest_exists": state_manifest_path.exists(),
        "report_path": report_relative,
        "report_exists": report_file.exists(),
        "install_smoke_report_path": install_smoke_report_relative,
        "install_smoke_report_exists": install_smoke_report_file.exists(),
        "install_smoke_status": install_smoke_status,
        "install_smoke_summary": install_smoke_summary,
        "install_smoke_target_root": str(install_smoke_report.get("target_root") or "").strip(),
        "install_smoke_state_path": str(install_smoke_report.get("state_path") or "").strip(),
        "install_smoke_backup_count": int(install_smoke_report.get("backup_count") or 0),
        "install_smoke_marker_preserved": bool(install_smoke_report.get("marker_preserved_in_backup")),
        "install_smoke_current_exists": bool(install_smoke_report.get("current_dir_exists")),
        "install_smoke_state_written": bool(install_smoke_report.get("state_manifest_exists")),
        "install_smoke_state_removed": bool(install_smoke_report.get("state_manifest_removed")),
        "install_smoke_installed_build_id": str(
            install_smoke_install_result.get("build_id") or install_smoke_report.get("build_id") or ""
        ).strip(),
        "install_smoke_installed_version": str(install_smoke_install_result.get("version") or "").strip(),
        "install_smoke_previous_build_id": str(install_smoke_upgrade_result.get("previous_build_id") or "").strip(),
        "install_smoke_backup_dir": str(install_smoke_upgrade_result.get("backup_dir") or "").strip(),
        "install_smoke_removed_build_id": str(install_smoke_uninstall_result.get("removed_build_id") or "").strip(),
        "install_smoke_removed_version": str(install_smoke_uninstall_result.get("removed_version") or "").strip(),
        "archive_dir": archive_dir_relative,
        "archive_exists": archive_dir.exists(),
        "archive_path": archive_path_relative,
        "archive_file_exists": archive_path.exists(),
        "archive_sha256_path": archive_sha256_path_relative,
        "archive_sha256_exists": archive_sha256_path.exists(),
        "archive_size_bytes": int(archive_path.stat().st_size) if archive_path.exists() else 0,
        "archive_status": archive_status,
        "archive_summary": archive_summary,
        "channel_index_dir": channel_index_dir_relative,
        "channel_index_exists": channel_index_dir.exists(),
        "channel_index_report_path": channel_index_report_relative,
        "channel_index_report_exists": channel_index_report_file.exists(),
        "channel_index_latest_path": channel_index_latest_relative,
        "channel_index_latest_exists": channel_index_latest_path.exists(),
        "channel_index_releases_path": channel_index_releases_relative,
        "channel_index_releases_exists": channel_index_releases_path.exists(),
        "channel_index_release_count": len(channel_index_items),
        "channel_index_latest_build_id": channel_index_latest_build_id,
        "channel_index_latest_matches_current": channel_index_latest_matches_current,
        "channel_index_status": channel_index_status,
        "channel_index_summary": channel_index_summary,
        "handoff_dir": handoff_dir_relative,
        "handoff_exists": handoff_dir.exists(),
        "handoff_file_count": handoff_file_count,
        "handoff_manifest_path": handoff_manifest_relative,
        "handoff_manifest_exists": handoff_manifest_path.exists(),
        "handoff_install_script_path": handoff_install_script_relative,
        "handoff_install_script_exists": handoff_install_script_path.exists(),
        "handoff_upgrade_script_path": handoff_upgrade_script_relative,
        "handoff_upgrade_script_exists": handoff_upgrade_script_path.exists(),
        "handoff_uninstall_script_path": handoff_uninstall_script_relative,
        "handoff_uninstall_script_exists": handoff_uninstall_script_path.exists(),
        "handoff_archive_path": handoff_archive_relative,
        "handoff_archive_exists": handoff_archive_path.exists(),
        "handoff_archive_sha256_path": handoff_archive_sha256_relative,
        "handoff_archive_sha256_exists": handoff_archive_sha256_path.exists(),
        "handoff_channel_latest_path": handoff_channel_latest_relative,
        "handoff_channel_latest_exists": handoff_channel_latest_path.exists(),
        "handoff_channel_releases_path": handoff_channel_releases_relative,
        "handoff_channel_releases_exists": handoff_channel_releases_path.exists(),
        "handoff_status": handoff_status,
        "handoff_summary": handoff_summary,
        "signing_handoff_dir": signing_handoff_dir_relative,
        "signing_handoff_exists": signing_handoff_dir.exists(),
        "signing_handoff_file_count": signing_handoff_file_count,
        "signing_handoff_manifest_path": signing_handoff_manifest_relative,
        "signing_handoff_manifest_exists": signing_handoff_manifest_path.exists(),
        "signing_handoff_instructions_path": signing_handoff_instructions_relative,
        "signing_handoff_instructions_exists": signing_handoff_instructions_path.exists(),
        "signing_handoff_unsigned_archive_path": signing_handoff_unsigned_archive_relative,
        "signing_handoff_unsigned_archive_exists": signing_handoff_unsigned_archive_path.exists(),
        "signing_handoff_unsigned_archive_sha256_path": signing_handoff_unsigned_archive_sha256_relative,
        "signing_handoff_unsigned_archive_sha256_exists": signing_handoff_unsigned_archive_sha256_path.exists(),
        "signing_handoff_status": signing_handoff_status,
        "signing_handoff_summary": signing_handoff_summary,
        "publish_handoff_dir": publish_handoff_dir_relative,
        "publish_handoff_exists": publish_handoff_dir.exists(),
        "publish_handoff_file_count": publish_handoff_file_count,
        "publish_handoff_manifest_path": publish_handoff_manifest_relative,
        "publish_handoff_manifest_exists": publish_handoff_manifest_path.exists(),
        "publish_handoff_instructions_path": publish_handoff_instructions_relative,
        "publish_handoff_instructions_exists": publish_handoff_instructions_path.exists(),
        "publish_handoff_archive_path": publish_handoff_archive_relative,
        "publish_handoff_archive_exists": publish_handoff_archive_path.exists(),
        "publish_handoff_archive_sha256_path": publish_handoff_archive_sha256_relative,
        "publish_handoff_archive_sha256_exists": publish_handoff_archive_sha256_path.exists(),
        "publish_handoff_channel_latest_path": publish_handoff_channel_latest_relative,
        "publish_handoff_channel_latest_exists": publish_handoff_channel_latest_path.exists(),
        "publish_handoff_channel_releases_path": publish_handoff_channel_releases_relative,
        "publish_handoff_channel_releases_exists": publish_handoff_channel_releases_path.exists(),
        "publish_handoff_status": publish_handoff_status,
        "publish_handoff_summary": publish_handoff_summary,
        "publish_receipts_dir": publish_receipts_dir_relative,
        "publish_receipts_exists": publish_receipts_dir.exists(),
        "publish_receipts_file_count": publish_receipts_file_count,
        "publish_receipts_manifest_path": publish_receipts_manifest_relative,
        "publish_receipts_manifest_exists": publish_receipts_manifest_path.exists(),
        "publish_receipts_target_count": len(delivery_publish_targets),
        "publish_receipts_recorded_target_count": len(publish_receipts_recorded_targets),
        "publish_receipts_completed_targets": publish_receipts_completed_targets,
        "publish_receipts_failed_targets": publish_receipts_failed_targets,
        "publish_receipts_missing_targets": publish_receipts_missing_targets,
        "publish_receipts_manifest_matches_current": publish_receipts_manifest_matches_current,
        "publish_receipts_status": publish_receipts_status,
        "publish_receipts_summary": publish_receipts_summary,
        "delivery_manifest_path": str(delivery_profile.get("path") or default_release_distribution_delivery_path()).strip(),
        "delivery_manifest_exists": bool(delivery_profile.get("exists")),
        "delivery_profile_id": str(delivery_profile.get("profile_id") or "").strip(),
        "delivery_status": str(delivery_profile.get("status") or "warning").strip(),
        "delivery_summary": str(delivery_profile.get("summary") or "").strip(),
        "delivery_primary_installer": str(delivery_profile.get("primary_installer") or "").strip(),
        "delivery_installer_types": list(delivery_profile.get("installer_types") or []),
        "delivery_installer_status": str(delivery_profile.get("installer_status") or "").strip(),
        "delivery_signing_required": bool(delivery_profile.get("signing_required")),
        "delivery_signing_mode": str(delivery_profile.get("signing_mode") or "").strip(),
        "delivery_signing_profile_id": str(delivery_profile.get("signing_profile_id") or "").strip(),
        "delivery_signing_status": str(delivery_profile.get("signing_status") or "").strip(),
        "delivery_publish_targets": list(delivery_profile.get("publish_targets") or []),
        "delivery_publish_target_count": int(delivery_profile.get("publish_target_count") or 0),
        "delivery_publish_status": str(delivery_profile.get("publish_status") or "").strip(),
        "delivery_first_run_bootstrap": str(delivery_profile.get("first_run_bootstrap") or "").strip(),
        "delivery_upgrade_strategy": str(delivery_profile.get("upgrade_strategy") or "").strip(),
        "delivery_uninstall_strategy": str(delivery_profile.get("uninstall_strategy") or "").strip(),
        "source_missing_items": source_missing_items,
        "bundle_missing_items": bundle_missing_items,
        "handoff_missing_items": handoff_missing_items,
        "signing_handoff_missing_items": signing_handoff_missing_items,
        "publish_handoff_missing_items": publish_handoff_missing_items,
        "exported_files": exported_files,
        "notes": notes,
        "recommendations": recommendations,
    })


def _persist_distribution_bundle_summary(
    project_root: Path,
    runtime_root: Path,
    *,
    target_channel: str,
    target_environment: str,
    release_manifest_path: str,
    report_path: str,
) -> Dict[str, Any]:
    summary = build_release_distribution_bundle(
        project_root,
        runtime_root=runtime_root,
        target_channel=target_channel,
        target_environment=target_environment,
        release_manifest_path=release_manifest_path,
        report_path=report_path,
    )
    report_file = (runtime_root / str(summary.get("report_path") or "")).resolve()
    _write_json(report_file, summary)
    final = build_release_distribution_bundle(
        project_root,
        runtime_root=runtime_root,
        target_channel=target_channel,
        target_environment=target_environment,
        release_manifest_path=release_manifest_path,
        report_path=report_path,
    )
    _write_json(report_file, final)
    return final


def export_release_distribution_bundle(
    project_root: str | Path,
    runtime_root: Optional[str | Path] = None,
    *,
    target_channel: str = "",
    target_environment: str = "",
    release_manifest_path: str = "",
    report_path: str = "",
) -> Dict[str, Any]:
    resolved_project_root = Path(project_root).resolve()
    resolved_runtime_root = Path(runtime_root or Path.cwd()).resolve()
    summary = build_release_distribution_bundle(
        resolved_project_root,
        runtime_root=resolved_runtime_root,
        target_channel=target_channel,
        target_environment=target_environment,
        release_manifest_path=release_manifest_path,
        report_path=report_path,
    )
    report_file = (resolved_runtime_root / str(summary.get("report_path") or "")).resolve()
    if list(summary.get("source_missing_items") or []):
        _write_json(report_file, summary)
        return _persist_distribution_bundle_summary(
            resolved_project_root,
            runtime_root=resolved_runtime_root,
            target_channel=target_channel,
            target_environment=target_environment,
            release_manifest_path=release_manifest_path,
            report_path=report_path,
        )

    manifest_state = _load_release_summary(
        resolved_runtime_root,
        release_manifest_path or DEFAULT_RELEASE_MANIFEST_PATH,
    )
    release_summary = dict(manifest_state.get("release_summary") or {})
    release_dir_path = Path(manifest_state.get("release_dir_path")).resolve()
    bundle_dir = (resolved_runtime_root / str(summary.get("bundle_dir") or "")).resolve()
    payload_dir = (resolved_runtime_root / str(summary.get("payload_dir") or "")).resolve()
    bundle_dir.mkdir(parents=True, exist_ok=True)

    if payload_dir.exists():
        shutil.rmtree(payload_dir, ignore_errors=True)
    shutil.copytree(release_dir_path, payload_dir)

    _copy_file(
        (resolved_runtime_root / str(manifest_state.get("manifest_path") or "")).resolve(),
        (resolved_runtime_root / str(summary.get("bundle_manifest_copy_path") or "")).resolve(),
    )
    _copy_file(
        (resolved_runtime_root / str(manifest_state.get("release_notes_path") or "")).resolve(),
        (resolved_runtime_root / str(summary.get("bundle_release_notes_path") or "")).resolve(),
    )
    _copy_file(
        (resolved_runtime_root / str(manifest_state.get("qa_gate_report_path") or "")).resolve(),
        (resolved_runtime_root / str(summary.get("bundle_qa_gate_report_path") or "")).resolve(),
    )
    _copy_file(
        (resolved_project_root / "docs" / "支持矩阵与分发说明.md").resolve(),
        (resolved_runtime_root / str(summary.get("support_matrix_path") or "")).resolve(),
    )

    distribution_manifest = {
        "schema_version": RELEASE_DISTRIBUTION_BUNDLE_SCHEMA_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "build_id": str(release_summary.get("build_id") or ""),
        "version": str(release_summary.get("version") or ""),
        "channel": str(release_summary.get("channel") or ""),
        "target_channel": str(summary.get("target_channel") or ""),
        "target_environment": str(summary.get("target_environment") or ""),
        "release_url": str(release_summary.get("release_url") or ""),
        "versioned_release_url": str(release_summary.get("versioned_release_url") or ""),
        "payload_path": "release_payload",
        "release_manifest_path": "release_manifest.json",
        "release_notes_path": "release_notes.md",
        "qa_gate_report_path": "qa_gate_report.md",
        "support_matrix_path": "support_matrix.md",
        "install_script_path": "install_release_bundle.ps1",
        "upgrade_script_path": "upgrade_release_bundle.ps1",
        "uninstall_script_path": "uninstall_release_bundle.ps1",
        "state_manifest_path": "installed_release.example.json",
        "payload_file_count": _count_files(payload_dir),
    }
    _write_json((resolved_runtime_root / str(summary.get("distribution_manifest_path") or "")).resolve(), distribution_manifest)
    _write_text((resolved_runtime_root / str(summary.get("install_script_path") or "")).resolve(), _build_install_script())
    _write_text((resolved_runtime_root / str(summary.get("upgrade_script_path") or "")).resolve(), _build_upgrade_script())
    _write_text((resolved_runtime_root / str(summary.get("uninstall_script_path") or "")).resolve(), _build_uninstall_script())
    _write_json(
        (resolved_runtime_root / str(summary.get("state_manifest_path") or "")).resolve(),
        {
            "schema_version": "1.0",
            "note": "Example install state written by install_release_bundle.ps1 / upgrade_release_bundle.ps1.",
            "last_operation": "install",
            "build_id": str(release_summary.get("build_id") or ""),
            "version": str(release_summary.get("version") or ""),
            "channel": str(release_summary.get("channel") or ""),
            "installed_at": "",
            "install_dir": "",
            "current_dir": "",
            "source_bundle": "",
            "bundle_manifest_path": "",
            "release_url": str(release_summary.get("release_url") or ""),
            "versioned_release_url": str(release_summary.get("versioned_release_url") or ""),
            "previous_build_id": "",
            "previous_version": "",
            "previous_channel": "",
            "previous_source_bundle": "",
            "backup_dir": "",
        },
    )

    refreshed = build_release_distribution_bundle(
        resolved_project_root,
        runtime_root=resolved_runtime_root,
        target_channel=target_channel,
        target_environment=target_environment,
        release_manifest_path=release_manifest_path,
        report_path=report_path,
    )
    _write_json(report_file, refreshed)
    final = build_release_distribution_bundle(
        resolved_project_root,
        runtime_root=resolved_runtime_root,
        target_channel=target_channel,
        target_environment=target_environment,
        release_manifest_path=release_manifest_path,
        report_path=report_path,
    )
    _write_json(report_file, final)
    return final


def export_release_distribution_install_smoke(
    project_root: str | Path,
    runtime_root: Optional[str | Path] = None,
    *,
    target_channel: str = "",
    target_environment: str = "",
    release_manifest_path: str = "",
    report_path: str = "",
) -> Dict[str, Any]:
    resolved_project_root = Path(project_root).resolve()
    resolved_runtime_root = Path(runtime_root or Path.cwd()).resolve()
    normalized_target_channel = str(target_channel or "staging").strip().lower() or "staging"
    normalized_target_environment = str(target_environment or "").strip() or (
        "production" if normalized_target_channel == "release" else normalized_target_channel
    )
    bundle_summary = export_release_distribution_bundle(
        resolved_project_root,
        runtime_root=resolved_runtime_root,
        target_channel=normalized_target_channel,
        target_environment=normalized_target_environment,
        release_manifest_path=release_manifest_path,
        report_path=report_path,
    )
    smoke_report_relative = default_release_distribution_install_smoke_report_path(
        target_channel=normalized_target_channel,
    )
    smoke_report_file = (resolved_runtime_root / smoke_report_relative).resolve()
    smoke_root_relative = default_release_distribution_install_smoke_dir(
        target_channel=normalized_target_channel,
        build_id=str(bundle_summary.get("build_id") or ""),
    )
    smoke_root = (resolved_runtime_root / smoke_root_relative).resolve()
    target_root = (smoke_root / "installed_release").resolve()
    install_dir = target_root / str(bundle_summary.get("build_id") or "")
    current_dir = target_root / "current"
    backup_root = target_root / "backups"
    state_path = target_root / ".release_bundle" / "installed_release.json"
    install_script_path = (resolved_runtime_root / str(bundle_summary.get("install_script_path") or "")).resolve()
    upgrade_script_path = (resolved_runtime_root / str(bundle_summary.get("upgrade_script_path") or "")).resolve()
    uninstall_script_path = (resolved_runtime_root / str(bundle_summary.get("uninstall_script_path") or "")).resolve()

    step_statuses: List[Dict[str, str]] = []
    notes: List[str] = []
    recommendations: List[str] = []

    def _append_step(step: str, status: str, message: str) -> None:
        step_statuses.append({
            "step": step,
            "status": status,
            "message": message,
        })

    if list(bundle_summary.get("source_missing_items") or []):
        report = {
            "schema_version": "1.0",
            "status": "blocked",
            "summary": "distribution bundle source prerequisites missing",
            "target_channel": normalized_target_channel,
            "target_environment": normalized_target_environment,
            "build_id": str(bundle_summary.get("build_id") or ""),
            "version": str(bundle_summary.get("version") or ""),
            "release_channel": str(bundle_summary.get("release_channel") or ""),
            "bundle_dir": str(bundle_summary.get("bundle_dir") or ""),
            "target_root": _relative_to_root(target_root, resolved_runtime_root),
            "backup_count": 0,
            "marker_preserved_in_backup": False,
            "install_dir_exists": False,
            "current_dir_exists": False,
            "state_manifest_exists": False,
            "state_manifest_removed": False,
            "step_statuses": [{"step": "bundle_ready", "status": "blocked", "message": "source prerequisites missing"}],
            "notes": notes,
            "recommendations": [
                "先补齐 release manifest、QA gate、支持矩阵和 versioned release 目录，再执行 distribution install smoke。"
            ],
        }
        _write_json(smoke_report_file, report)
        _persist_distribution_bundle_summary(
            resolved_project_root,
            runtime_root=resolved_runtime_root,
            target_channel=normalized_target_channel,
            target_environment=normalized_target_environment,
            release_manifest_path=release_manifest_path,
            report_path=report_path,
        )
        return report

    if list(bundle_summary.get("bundle_missing_items") or []):
        report = {
            "schema_version": "1.0",
            "status": "blocked",
            "summary": "distribution bundle export incomplete",
            "target_channel": normalized_target_channel,
            "target_environment": normalized_target_environment,
            "build_id": str(bundle_summary.get("build_id") or ""),
            "version": str(bundle_summary.get("version") or ""),
            "release_channel": str(bundle_summary.get("release_channel") or ""),
            "bundle_dir": str(bundle_summary.get("bundle_dir") or ""),
            "target_root": _relative_to_root(target_root, resolved_runtime_root),
            "backup_count": 0,
            "marker_preserved_in_backup": False,
            "install_dir_exists": False,
            "current_dir_exists": False,
            "state_manifest_exists": False,
            "state_manifest_removed": False,
            "step_statuses": [{"step": "bundle_ready", "status": "blocked", "message": "bundle export incomplete"}],
            "notes": notes,
            "recommendations": [
                "先执行 export_release_distribution_bundle，确认 distribution_manifest、脚本和 release_payload 都已导出。"
            ],
        }
        _write_json(smoke_report_file, report)
        _persist_distribution_bundle_summary(
            resolved_project_root,
            runtime_root=resolved_runtime_root,
            target_channel=normalized_target_channel,
            target_environment=normalized_target_environment,
            release_manifest_path=release_manifest_path,
            report_path=report_path,
        )
        return report

    powershell_executable = shutil.which("pwsh") or shutil.which("powershell")
    if not powershell_executable:
        report = {
            "schema_version": "1.0",
            "status": "warning",
            "summary": "PowerShell executable not available; install smoke skipped",
            "target_channel": normalized_target_channel,
            "target_environment": normalized_target_environment,
            "build_id": str(bundle_summary.get("build_id") or ""),
            "version": str(bundle_summary.get("version") or ""),
            "release_channel": str(bundle_summary.get("release_channel") or ""),
            "bundle_dir": str(bundle_summary.get("bundle_dir") or ""),
            "target_root": _relative_to_root(target_root, resolved_runtime_root),
            "backup_count": 0,
            "marker_preserved_in_backup": False,
            "install_dir_exists": False,
            "current_dir_exists": False,
            "state_manifest_exists": False,
            "state_manifest_removed": False,
            "step_statuses": [{"step": "resolve_powershell", "status": "warning", "message": "PowerShell executable not found"}],
            "notes": notes,
            "recommendations": [
                "在 Windows 主路径或带 PowerShell 的环境中重新执行 distribution install smoke。"
            ],
        }
        _write_json(smoke_report_file, report)
        _persist_distribution_bundle_summary(
            resolved_project_root,
            runtime_root=resolved_runtime_root,
            target_channel=normalized_target_channel,
            target_environment=normalized_target_environment,
            release_manifest_path=release_manifest_path,
            report_path=report_path,
        )
        return report

    shutil.rmtree(smoke_root, ignore_errors=True)
    smoke_root.mkdir(parents=True, exist_ok=True)
    marker_name = "__upgrade_marker.txt"
    marker_message = "upgrade-marker"

    install_run = _run_powershell_script(
        powershell_executable,
        install_script_path,
        ["-TargetRoot", str(target_root)],
    )
    install_result = _parse_result_payload(install_run)
    install_ok = (
        install_run["returncode"] == 0
        and install_dir.exists()
        and (install_dir / "index.html").exists()
        and current_dir.exists()
        and (current_dir / "index.html").exists()
        and state_path.exists()
        and str(install_result.get("build_id") or bundle_summary.get("build_id") or "").strip() == str(bundle_summary.get("build_id") or "").strip()
    )
    _append_step(
        "install",
        "passed" if install_ok else "blocked",
        "installed release payload into target root" if install_ok else _run_failure_message(install_run, "install failed"),
    )

    marker_preserved = False
    backup_count = 0
    upgrade_run: Dict[str, Any] = {"returncode": -1, "stdout": "", "stderr": ""}
    uninstall_run: Dict[str, Any] = {"returncode": -1, "stdout": "", "stderr": ""}
    upgrade_result: Dict[str, Any] = {}
    uninstall_result: Dict[str, Any] = {}
    if install_ok:
        (current_dir / marker_name).write_text(marker_message, encoding="utf-8")
        upgrade_run = _run_powershell_script(
            powershell_executable,
            upgrade_script_path,
            ["-TargetRoot", str(target_root)],
        )
        upgrade_result = _parse_result_payload(upgrade_run)
        backup_dirs = sorted(path for path in backup_root.iterdir() if path.is_dir()) if backup_root.exists() else []
        backup_count = len(backup_dirs)
        marker_preserved = any((path / marker_name).exists() for path in backup_dirs)
        upgrade_ok = (
            upgrade_run["returncode"] == 0
            and backup_count > 0
            and marker_preserved
            and current_dir.exists()
            and (current_dir / "index.html").exists()
            and state_path.exists()
            and str(upgrade_result.get("backup_dir") or "").strip()
            and str(upgrade_result.get("previous_build_id") or "").strip() == str(bundle_summary.get("build_id") or "").strip()
        )
        _append_step(
            "upgrade",
            "passed" if upgrade_ok else "blocked",
            "upgrade created backup and refreshed current release"
            if upgrade_ok
            else _run_failure_message(upgrade_run, "upgrade failed"),
        )
        if upgrade_ok:
            uninstall_run = _run_powershell_script(
                powershell_executable,
                uninstall_script_path,
                ["-TargetRoot", str(target_root)],
            )
            uninstall_result = _parse_result_payload(uninstall_run)
            uninstall_ok = (
                uninstall_run["returncode"] == 0
                and not install_dir.exists()
                and not current_dir.exists()
                and not state_path.exists()
                and str(uninstall_result.get("removed_build_id") or "").strip() == str(bundle_summary.get("build_id") or "").strip()
            )
            _append_step(
                "uninstall",
                "passed" if uninstall_ok else "blocked",
                "uninstall removed installed release, current mirror and state file"
                if uninstall_ok
                else _run_failure_message(uninstall_run, "uninstall failed"),
            )

    failed_steps = [item for item in step_statuses if str(item.get("status") or "") != "passed"]
    status = "passed" if not failed_steps else "blocked"
    summary = (
        f"steps={len(step_statuses)} / passed={len(step_statuses) - len(failed_steps)} / "
        f"failed={len(failed_steps)} / backups={backup_count}"
    )
    if status != "passed":
        recommendations.append(
            "先修复 install / upgrade / uninstall 脚本的复制、备份或清理行为，再把 distribution bundle 当成正式发布物。"
        )

    report = {
        "schema_version": "1.0",
        "status": status,
        "summary": summary,
        "target_channel": normalized_target_channel,
        "target_environment": normalized_target_environment,
        "build_id": str(bundle_summary.get("build_id") or ""),
        "version": str(bundle_summary.get("version") or ""),
        "release_channel": str(bundle_summary.get("release_channel") or ""),
        "bundle_dir": str(bundle_summary.get("bundle_dir") or ""),
        "bundle_report_path": str(bundle_summary.get("report_path") or ""),
        "target_root": _relative_to_root(target_root, resolved_runtime_root),
        "bundle_root": _relative_to_root((resolved_runtime_root / str(bundle_summary.get("bundle_dir") or "")).resolve(), resolved_runtime_root),
        "state_path": _relative_to_root(state_path, resolved_runtime_root),
        "backup_root": _relative_to_root(backup_root, resolved_runtime_root),
        "install_dir": _relative_to_root(install_dir, resolved_runtime_root),
        "current_dir": _relative_to_root(current_dir, resolved_runtime_root),
        "install_dir_exists": install_dir.exists(),
        "current_dir_exists": current_dir.exists(),
        "state_manifest_exists": state_path.exists(),
        "state_manifest_removed": not state_path.exists(),
        "backup_count": backup_count,
        "marker_preserved_in_backup": marker_preserved,
        "install_return_code": int(install_run["returncode"]),
        "upgrade_return_code": int(upgrade_run["returncode"]),
        "uninstall_return_code": int(uninstall_run["returncode"]),
        "install_result": install_result,
        "upgrade_result": upgrade_result,
        "uninstall_result": uninstall_result,
        "step_statuses": step_statuses,
        "notes": notes,
        "recommendations": recommendations,
    }
    _write_json(smoke_report_file, report)
    _persist_distribution_bundle_summary(
        resolved_project_root,
        runtime_root=resolved_runtime_root,
        target_channel=normalized_target_channel,
        target_environment=normalized_target_environment,
        release_manifest_path=release_manifest_path,
        report_path=report_path,
    )
    return report


def export_release_distribution_archive(
    project_root: str | Path,
    runtime_root: Optional[str | Path] = None,
    *,
    target_channel: str = "",
    target_environment: str = "",
    release_manifest_path: str = "",
    report_path: str = "",
) -> Dict[str, Any]:
    resolved_project_root = Path(project_root).resolve()
    resolved_runtime_root = Path(runtime_root or Path.cwd()).resolve()
    normalized_target_channel = str(target_channel or "staging").strip().lower() or "staging"
    normalized_target_environment = str(target_environment or "").strip() or (
        "production" if normalized_target_channel == "release" else normalized_target_channel
    )
    export_release_distribution_install_smoke(
        resolved_project_root,
        runtime_root=resolved_runtime_root,
        target_channel=normalized_target_channel,
        target_environment=normalized_target_environment,
        release_manifest_path=release_manifest_path,
        report_path=report_path,
    )
    bundle_summary = build_release_distribution_bundle(
        resolved_project_root,
        runtime_root=resolved_runtime_root,
        target_channel=normalized_target_channel,
        target_environment=normalized_target_environment,
        release_manifest_path=release_manifest_path,
        report_path=report_path,
    )
    if list(bundle_summary.get("source_missing_items") or []) or list(bundle_summary.get("bundle_missing_items") or []):
        return _persist_distribution_bundle_summary(
            resolved_project_root,
            runtime_root=resolved_runtime_root,
            target_channel=normalized_target_channel,
            target_environment=normalized_target_environment,
            release_manifest_path=release_manifest_path,
            report_path=report_path,
        )
    if str(bundle_summary.get("install_smoke_status") or "").strip().lower() != "passed":
        return _persist_distribution_bundle_summary(
            resolved_project_root,
            runtime_root=resolved_runtime_root,
            target_channel=normalized_target_channel,
            target_environment=normalized_target_environment,
            release_manifest_path=release_manifest_path,
            report_path=report_path,
        )

    bundle_dir = (resolved_runtime_root / str(bundle_summary.get("bundle_dir") or "")).resolve()
    archive_path = (resolved_runtime_root / str(bundle_summary.get("archive_path") or "")).resolve()
    archive_sha256_path = (resolved_runtime_root / str(bundle_summary.get("archive_sha256_path") or "")).resolve()
    archive_path.parent.mkdir(parents=True, exist_ok=True)
    if archive_path.exists():
        archive_path.unlink()
    if archive_sha256_path.exists():
        archive_sha256_path.unlink()

    with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_DEFLATED) as archive_file:
        for file_path in sorted(path for path in bundle_dir.rglob("*") if path.is_file()):
            arcname = Path(str(bundle_summary.get("build_id") or "bundle")) / file_path.relative_to(bundle_dir)
            archive_file.write(file_path, arcname=arcname.as_posix())

    digest = hashlib.sha256(archive_path.read_bytes()).hexdigest()
    _write_text(archive_sha256_path, f"{digest}  {archive_path.name}\n")
    return _persist_distribution_bundle_summary(
        resolved_project_root,
        runtime_root=resolved_runtime_root,
        target_channel=normalized_target_channel,
        target_environment=normalized_target_environment,
        release_manifest_path=release_manifest_path,
        report_path=report_path,
    )


def export_release_distribution_channel_index(
    project_root: str | Path,
    runtime_root: Optional[str | Path] = None,
    *,
    target_channel: str = "",
    target_environment: str = "",
    release_manifest_path: str = "",
    report_path: str = "",
) -> Dict[str, Any]:
    resolved_project_root = Path(project_root).resolve()
    resolved_runtime_root = Path(runtime_root or Path.cwd()).resolve()
    normalized_target_channel = str(target_channel or "staging").strip().lower() or "staging"
    normalized_target_environment = str(target_environment or "").strip() or (
        "production" if normalized_target_channel == "release" else normalized_target_channel
    )
    export_release_distribution_archive(
        resolved_project_root,
        runtime_root=resolved_runtime_root,
        target_channel=normalized_target_channel,
        target_environment=normalized_target_environment,
        release_manifest_path=release_manifest_path,
        report_path=report_path,
    )
    bundle_summary = build_release_distribution_bundle(
        resolved_project_root,
        runtime_root=resolved_runtime_root,
        target_channel=normalized_target_channel,
        target_environment=normalized_target_environment,
        release_manifest_path=release_manifest_path,
        report_path=report_path,
    )
    if list(bundle_summary.get("source_missing_items") or []) or list(bundle_summary.get("bundle_missing_items") or []):
        return _persist_distribution_bundle_summary(
            resolved_project_root,
            runtime_root=resolved_runtime_root,
            target_channel=normalized_target_channel,
            target_environment=normalized_target_environment,
            release_manifest_path=release_manifest_path,
            report_path=report_path,
        )
    if str(bundle_summary.get("install_smoke_status") or "").strip().lower() != "passed":
        return _persist_distribution_bundle_summary(
            resolved_project_root,
            runtime_root=resolved_runtime_root,
            target_channel=normalized_target_channel,
            target_environment=normalized_target_environment,
            release_manifest_path=release_manifest_path,
            report_path=report_path,
        )
    if str(bundle_summary.get("archive_status") or "").strip().lower() != "passed":
        return _persist_distribution_bundle_summary(
            resolved_project_root,
            runtime_root=resolved_runtime_root,
            target_channel=normalized_target_channel,
            target_environment=normalized_target_environment,
            release_manifest_path=release_manifest_path,
            report_path=report_path,
        )

    published_at = datetime.now(timezone.utc).isoformat()
    channel_report_relative = default_release_distribution_channel_report_path(
        target_channel=normalized_target_channel,
    )
    channel_dir_relative = default_release_distribution_channel_dir(
        target_channel=normalized_target_channel,
    )
    channel_latest_relative = default_release_distribution_channel_latest_path(
        target_channel=normalized_target_channel,
    )
    channel_releases_relative = default_release_distribution_channel_releases_path(
        target_channel=normalized_target_channel,
    )
    channel_report_file = (resolved_runtime_root / channel_report_relative).resolve()
    channel_latest_file = (resolved_runtime_root / channel_latest_relative).resolve()
    channel_releases_file = (resolved_runtime_root / channel_releases_relative).resolve()
    existing_items = [
        dict(item)
        for item in list(_read_json(channel_releases_file).get("items") or [])
        if isinstance(item, dict)
    ]
    build_id = str(bundle_summary.get("build_id") or "").strip()
    version = str(bundle_summary.get("version") or "").strip()
    release_channel = str(bundle_summary.get("release_channel") or "").strip()
    entry = {
        "schema_version": "1.0",
        "build_id": build_id,
        "version": version,
        "release_channel": release_channel,
        "target_channel": normalized_target_channel,
        "target_environment": normalized_target_environment,
        "published_at": published_at,
        "bundle_dir": str(bundle_summary.get("bundle_dir") or ""),
        "report_path": str(bundle_summary.get("report_path") or ""),
        "distribution_manifest_path": str(bundle_summary.get("distribution_manifest_path") or ""),
        "release_manifest_path": str(bundle_summary.get("release_manifest_path") or ""),
        "release_notes_path": str(bundle_summary.get("release_notes_path") or ""),
        "qa_gate_report_path": str(bundle_summary.get("qa_gate_report_path") or ""),
        "release_url": str(bundle_summary.get("release_url") or ""),
        "versioned_release_url": str(bundle_summary.get("versioned_release_url") or ""),
        "archive_path": str(bundle_summary.get("archive_path") or ""),
        "archive_sha256_path": str(bundle_summary.get("archive_sha256_path") or ""),
        "archive_size_bytes": int(bundle_summary.get("archive_size_bytes") or 0),
        "install_smoke_report_path": str(bundle_summary.get("install_smoke_report_path") or ""),
        "status": "passed",
    }
    merged_items = [
        item
        for item in existing_items
        if str(item.get("build_id") or "").strip() != build_id
    ]
    merged_items.append(entry)
    merged_items.sort(
        key=lambda item: (
            str(item.get("published_at") or ""),
            str(item.get("build_id") or ""),
        ),
        reverse=True,
    )
    latest_payload = dict(entry)
    latest_payload.update({
        "latest": True,
        "release_count": len(merged_items),
        "channel_dir": channel_dir_relative,
        "releases_path": channel_releases_relative,
    })
    releases_payload = {
        "schema_version": "1.0",
        "status": "passed",
        "summary": f"channel releases indexed / count={len(merged_items)} / latest={build_id or '-'}",
        "target_channel": normalized_target_channel,
        "target_environment": normalized_target_environment,
        "channel_dir": channel_dir_relative,
        "latest_path": channel_latest_relative,
        "latest_build_id": build_id,
        "latest_version": version,
        "release_count": len(merged_items),
        "generated_at": published_at,
        "items": merged_items,
    }
    report_payload = {
        "schema_version": "1.0",
        "status": "passed",
        "summary": f"distribution channel index ready / releases={len(merged_items)} / latest={build_id or '-'}",
        "target_channel": normalized_target_channel,
        "target_environment": normalized_target_environment,
        "build_id": build_id,
        "version": version,
        "release_channel": release_channel,
        "channel_dir": channel_dir_relative,
        "latest_path": channel_latest_relative,
        "latest_exists": True,
        "releases_path": channel_releases_relative,
        "releases_exists": True,
        "latest_build_id": build_id,
        "latest_matches_current": True,
        "release_count": len(merged_items),
        "archive_path": str(bundle_summary.get("archive_path") or ""),
        "archive_sha256_path": str(bundle_summary.get("archive_sha256_path") or ""),
        "bundle_dir": str(bundle_summary.get("bundle_dir") or ""),
        "notes": [
            f"latest={build_id or '-'}",
            f"channel_dir={channel_dir_relative}",
        ],
        "recommendations": [],
    }
    _write_json(channel_latest_file, latest_payload)
    _write_json(channel_releases_file, releases_payload)
    _write_json(channel_report_file, report_payload)
    return _persist_distribution_bundle_summary(
        resolved_project_root,
        runtime_root=resolved_runtime_root,
        target_channel=normalized_target_channel,
        target_environment=normalized_target_environment,
        release_manifest_path=release_manifest_path,
        report_path=report_path,
    )


def export_release_distribution_handoff(
    project_root: str | Path,
    runtime_root: Optional[str | Path] = None,
    *,
    target_channel: str = "",
    target_environment: str = "",
    release_manifest_path: str = "",
    report_path: str = "",
) -> Dict[str, Any]:
    resolved_project_root = Path(project_root).resolve()
    resolved_runtime_root = Path(runtime_root or Path.cwd()).resolve()
    normalized_target_channel = str(target_channel or "staging").strip().lower() or "staging"
    normalized_target_environment = str(target_environment or "").strip() or (
        "production" if normalized_target_channel == "release" else normalized_target_channel
    )
    export_release_distribution_channel_index(
        resolved_project_root,
        runtime_root=resolved_runtime_root,
        target_channel=normalized_target_channel,
        target_environment=normalized_target_environment,
        release_manifest_path=release_manifest_path,
        report_path=report_path,
    )
    bundle_summary = build_release_distribution_bundle(
        resolved_project_root,
        runtime_root=resolved_runtime_root,
        target_channel=normalized_target_channel,
        target_environment=normalized_target_environment,
        release_manifest_path=release_manifest_path,
        report_path=report_path,
    )
    if list(bundle_summary.get("source_missing_items") or []) or list(bundle_summary.get("bundle_missing_items") or []):
        return _persist_distribution_bundle_summary(
            resolved_project_root,
            runtime_root=resolved_runtime_root,
            target_channel=normalized_target_channel,
            target_environment=normalized_target_environment,
            release_manifest_path=release_manifest_path,
            report_path=report_path,
        )
    if str(bundle_summary.get("install_smoke_status") or "").strip().lower() != "passed":
        return _persist_distribution_bundle_summary(
            resolved_project_root,
            runtime_root=resolved_runtime_root,
            target_channel=normalized_target_channel,
            target_environment=normalized_target_environment,
            release_manifest_path=release_manifest_path,
            report_path=report_path,
        )
    if str(bundle_summary.get("archive_status") or "").strip().lower() != "passed":
        return _persist_distribution_bundle_summary(
            resolved_project_root,
            runtime_root=resolved_runtime_root,
            target_channel=normalized_target_channel,
            target_environment=normalized_target_environment,
            release_manifest_path=release_manifest_path,
            report_path=report_path,
        )
    if str(bundle_summary.get("channel_index_status") or "").strip().lower() != "passed":
        return _persist_distribution_bundle_summary(
            resolved_project_root,
            runtime_root=resolved_runtime_root,
            target_channel=normalized_target_channel,
            target_environment=normalized_target_environment,
            release_manifest_path=release_manifest_path,
            report_path=report_path,
        )

    handoff_dir = (resolved_runtime_root / str(bundle_summary.get("handoff_dir") or "")).resolve()
    if handoff_dir.exists():
        shutil.rmtree(handoff_dir, ignore_errors=True)
    handoff_dir.mkdir(parents=True, exist_ok=True)

    archive_source = (resolved_runtime_root / str(bundle_summary.get("archive_path") or "")).resolve()
    archive_sha256_source = (resolved_runtime_root / str(bundle_summary.get("archive_sha256_path") or "")).resolve()
    latest_source = (resolved_runtime_root / str(bundle_summary.get("channel_index_latest_path") or "")).resolve()
    releases_source = (resolved_runtime_root / str(bundle_summary.get("channel_index_releases_path") or "")).resolve()
    manifest_source = (resolved_runtime_root / str(bundle_summary.get("bundle_manifest_copy_path") or "")).resolve()
    notes_source = (resolved_runtime_root / str(bundle_summary.get("bundle_release_notes_path") or "")).resolve()
    qa_gate_source = (resolved_runtime_root / str(bundle_summary.get("bundle_qa_gate_report_path") or "")).resolve()
    support_matrix_source = (resolved_runtime_root / str(bundle_summary.get("support_matrix_path") or "")).resolve()

    archive_destination = (resolved_runtime_root / str(bundle_summary.get("handoff_archive_path") or "")).resolve()
    archive_sha256_destination = (resolved_runtime_root / str(bundle_summary.get("handoff_archive_sha256_path") or "")).resolve()
    latest_destination = (resolved_runtime_root / str(bundle_summary.get("handoff_channel_latest_path") or "")).resolve()
    releases_destination = (resolved_runtime_root / str(bundle_summary.get("handoff_channel_releases_path") or "")).resolve()
    manifest_destination = (handoff_dir / "release_manifest.json").resolve()
    notes_destination = (handoff_dir / "release_notes.md").resolve()
    qa_gate_destination = (handoff_dir / "qa_gate_report.md").resolve()
    support_matrix_destination = (handoff_dir / "support_matrix.md").resolve()
    handoff_manifest_destination = (resolved_runtime_root / str(bundle_summary.get("handoff_manifest_path") or "")).resolve()
    handoff_install_destination = (resolved_runtime_root / str(bundle_summary.get("handoff_install_script_path") or "")).resolve()
    handoff_upgrade_destination = (resolved_runtime_root / str(bundle_summary.get("handoff_upgrade_script_path") or "")).resolve()
    handoff_uninstall_destination = (resolved_runtime_root / str(bundle_summary.get("handoff_uninstall_script_path") or "")).resolve()

    _copy_file(archive_source, archive_destination)
    _copy_file(archive_sha256_source, archive_sha256_destination)
    _copy_file(latest_source, latest_destination)
    _copy_file(releases_source, releases_destination)
    _copy_file(manifest_source, manifest_destination)
    _copy_file(notes_source, notes_destination)
    _copy_file(qa_gate_source, qa_gate_destination)
    _copy_file(support_matrix_source, support_matrix_destination)

    handoff_manifest = {
        "schema_version": "1.0",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "build_id": str(bundle_summary.get("build_id") or ""),
        "version": str(bundle_summary.get("version") or ""),
        "release_channel": str(bundle_summary.get("release_channel") or ""),
        "target_channel": normalized_target_channel,
        "target_environment": normalized_target_environment,
        "package_archive_path": "packages/release_distribution_bundle.zip",
        "package_archive_sha256_path": "packages/release_distribution_bundle.sha256",
        "channel_latest_path": "channel/latest.json",
        "channel_releases_path": "channel/releases.json",
        "release_manifest_path": "release_manifest.json",
        "release_notes_path": "release_notes.md",
        "qa_gate_report_path": "qa_gate_report.md",
        "support_matrix_path": "support_matrix.md",
        "bundle_install_script_path": "install_release_bundle.ps1",
        "bundle_upgrade_script_path": "upgrade_release_bundle.ps1",
        "bundle_uninstall_script_path": "uninstall_release_bundle.ps1",
        "install_script_path": "install_release_handoff.ps1",
        "upgrade_script_path": "upgrade_release_handoff.ps1",
        "uninstall_script_path": "uninstall_release_handoff.ps1",
        "release_url": str(bundle_summary.get("release_url") or ""),
        "versioned_release_url": str(bundle_summary.get("versioned_release_url") or ""),
        "archive_source_path": str(bundle_summary.get("archive_path") or ""),
        "channel_latest_source_path": str(bundle_summary.get("channel_index_latest_path") or ""),
        "channel_releases_source_path": str(bundle_summary.get("channel_index_releases_path") or ""),
        "target_root_example": ".\\installed_release",
        "notes": [
            "Handoff package bundles the verified archive, channel latest/releases index, release notes, QA gate, and wrapper scripts.",
            "Consumers can install or upgrade from this directory without resolving the original repo-relative package paths.",
        ],
    }
    _write_json(handoff_manifest_destination, handoff_manifest)
    _write_text(handoff_install_destination, _build_handoff_install_script())
    _write_text(handoff_upgrade_destination, _build_handoff_upgrade_script())
    _write_text(handoff_uninstall_destination, _build_handoff_uninstall_script())

    return _persist_distribution_bundle_summary(
        resolved_project_root,
        runtime_root=resolved_runtime_root,
        target_channel=normalized_target_channel,
        target_environment=normalized_target_environment,
        release_manifest_path=release_manifest_path,
        report_path=report_path,
    )


def export_release_distribution_signing_handoff(
    project_root: str | Path,
    runtime_root: Optional[str | Path] = None,
    *,
    target_channel: str = "",
    target_environment: str = "",
    release_manifest_path: str = "",
    report_path: str = "",
) -> Dict[str, Any]:
    resolved_project_root = Path(project_root).resolve()
    resolved_runtime_root = Path(runtime_root or Path.cwd()).resolve()
    normalized_target_channel = str(target_channel or "staging").strip().lower() or "staging"
    normalized_target_environment = str(target_environment or "").strip() or (
        "production" if normalized_target_channel == "release" else normalized_target_channel
    )
    export_release_distribution_channel_index(
        resolved_project_root,
        runtime_root=resolved_runtime_root,
        target_channel=normalized_target_channel,
        target_environment=normalized_target_environment,
        release_manifest_path=release_manifest_path,
        report_path=report_path,
    )
    bundle_summary = build_release_distribution_bundle(
        resolved_project_root,
        runtime_root=resolved_runtime_root,
        target_channel=normalized_target_channel,
        target_environment=normalized_target_environment,
        release_manifest_path=release_manifest_path,
        report_path=report_path,
    )

    if list(bundle_summary.get("source_missing_items") or []) or list(bundle_summary.get("bundle_missing_items") or []):
        return _persist_distribution_bundle_summary(
            resolved_project_root,
            runtime_root=resolved_runtime_root,
            target_channel=normalized_target_channel,
            target_environment=normalized_target_environment,
            release_manifest_path=release_manifest_path,
            report_path=report_path,
        )
    if str(bundle_summary.get("install_smoke_status") or "").strip().lower() != "passed":
        return _persist_distribution_bundle_summary(
            resolved_project_root,
            runtime_root=resolved_runtime_root,
            target_channel=normalized_target_channel,
            target_environment=normalized_target_environment,
            release_manifest_path=release_manifest_path,
            report_path=report_path,
        )
    if str(bundle_summary.get("archive_status") or "").strip().lower() != "passed":
        return _persist_distribution_bundle_summary(
            resolved_project_root,
            runtime_root=resolved_runtime_root,
            target_channel=normalized_target_channel,
            target_environment=normalized_target_environment,
            release_manifest_path=release_manifest_path,
            report_path=report_path,
        )
    if not bool(bundle_summary.get("delivery_signing_required")):
        return _persist_distribution_bundle_summary(
            resolved_project_root,
            runtime_root=resolved_runtime_root,
            target_channel=normalized_target_channel,
            target_environment=normalized_target_environment,
            release_manifest_path=release_manifest_path,
            report_path=report_path,
        )
    if str(bundle_summary.get("delivery_signing_mode") or "").strip().lower() in {"sha256_only", "codesigned", "signed_archive", "notarized"}:
        return _persist_distribution_bundle_summary(
            resolved_project_root,
            runtime_root=resolved_runtime_root,
            target_channel=normalized_target_channel,
            target_environment=normalized_target_environment,
            release_manifest_path=release_manifest_path,
            report_path=report_path,
        )

    signing_handoff_dir = (resolved_runtime_root / str(bundle_summary.get("signing_handoff_dir") or "")).resolve()
    if signing_handoff_dir.exists():
        shutil.rmtree(signing_handoff_dir, ignore_errors=True)
    signing_handoff_dir.mkdir(parents=True, exist_ok=True)

    archive_source = (resolved_runtime_root / str(bundle_summary.get("archive_path") or "")).resolve()
    archive_sha256_source = (resolved_runtime_root / str(bundle_summary.get("archive_sha256_path") or "")).resolve()
    latest_source = (resolved_runtime_root / str(bundle_summary.get("channel_index_latest_path") or "")).resolve()
    releases_source = (resolved_runtime_root / str(bundle_summary.get("channel_index_releases_path") or "")).resolve()
    manifest_source = (resolved_runtime_root / str(bundle_summary.get("bundle_manifest_copy_path") or "")).resolve()
    notes_source = (resolved_runtime_root / str(bundle_summary.get("bundle_release_notes_path") or "")).resolve()
    qa_gate_source = (resolved_runtime_root / str(bundle_summary.get("bundle_qa_gate_report_path") or "")).resolve()
    support_matrix_source = (resolved_runtime_root / str(bundle_summary.get("support_matrix_path") or "")).resolve()
    handoff_manifest_source = (resolved_runtime_root / str(bundle_summary.get("handoff_manifest_path") or "")).resolve()

    archive_destination = (resolved_runtime_root / str(bundle_summary.get("signing_handoff_unsigned_archive_path") or "")).resolve()
    archive_sha256_destination = (
        resolved_runtime_root / str(bundle_summary.get("signing_handoff_unsigned_archive_sha256_path") or "")
    ).resolve()
    manifest_destination = (signing_handoff_dir / "metadata" / "release_manifest.json").resolve()
    notes_destination = (signing_handoff_dir / "metadata" / "release_notes.md").resolve()
    qa_gate_destination = (signing_handoff_dir / "metadata" / "qa_gate_report.md").resolve()
    support_matrix_destination = (signing_handoff_dir / "metadata" / "support_matrix.md").resolve()
    latest_destination = (signing_handoff_dir / "metadata" / "channel_latest.json").resolve()
    releases_destination = (signing_handoff_dir / "metadata" / "channel_releases.json").resolve()
    handoff_manifest_destination = (signing_handoff_dir / "metadata" / "distribution_handoff_manifest.json").resolve()
    signing_manifest_destination = (resolved_runtime_root / str(bundle_summary.get("signing_handoff_manifest_path") or "")).resolve()
    instructions_destination = (resolved_runtime_root / str(bundle_summary.get("signing_handoff_instructions_path") or "")).resolve()

    _copy_file(archive_source, archive_destination)
    _copy_file(archive_sha256_source, archive_sha256_destination)
    _copy_file(manifest_source, manifest_destination)
    _copy_file(notes_source, notes_destination)
    _copy_file(qa_gate_source, qa_gate_destination)
    _copy_file(support_matrix_source, support_matrix_destination)
    _copy_file(latest_source, latest_destination)
    _copy_file(releases_source, releases_destination)
    if handoff_manifest_source.exists():
        _copy_file(handoff_manifest_source, handoff_manifest_destination)

    signing_manifest = {
        "schema_version": "1.0",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "build_id": str(bundle_summary.get("build_id") or ""),
        "version": str(bundle_summary.get("version") or ""),
        "release_channel": str(bundle_summary.get("release_channel") or ""),
        "target_channel": normalized_target_channel,
        "target_environment": normalized_target_environment,
        "delivery_profile_id": str(bundle_summary.get("delivery_profile_id") or ""),
        "primary_installer": str(bundle_summary.get("delivery_primary_installer") or ""),
        "installer_types": list(bundle_summary.get("delivery_installer_types") or []),
        "signing_mode": str(bundle_summary.get("delivery_signing_mode") or ""),
        "signing_profile_id": str(bundle_summary.get("delivery_signing_profile_id") or ""),
        "publish_targets": list(bundle_summary.get("delivery_publish_targets") or []),
        "unsigned_archive_path": "unsigned/release_distribution_bundle.zip",
        "unsigned_archive_sha256_path": "unsigned/release_distribution_bundle.sha256",
        "metadata_dir": "metadata",
        "release_manifest_path": "metadata/release_manifest.json",
        "release_notes_path": "metadata/release_notes.md",
        "qa_gate_report_path": "metadata/qa_gate_report.md",
        "support_matrix_path": "metadata/support_matrix.md",
        "channel_latest_path": "metadata/channel_latest.json",
        "channel_releases_path": "metadata/channel_releases.json",
        "distribution_handoff_manifest_path": (
            "metadata/distribution_handoff_manifest.json" if handoff_manifest_source.exists() else ""
        ),
        "notes": [
            "Signing handoff bundles the verified unsigned archive plus metadata needed by an external signing/release operator.",
            "The external signer should preserve archive bytes or emit a separately traceable signed artifact linked back to this manifest.",
        ],
    }
    _write_json(signing_manifest_destination, signing_manifest)
    _write_text(
        instructions_destination,
        _build_signing_handoff_instructions(
            delivery_profile_id=str(bundle_summary.get("delivery_profile_id") or ""),
            signing_profile_id=str(bundle_summary.get("delivery_signing_profile_id") or ""),
            signing_mode=str(bundle_summary.get("delivery_signing_mode") or ""),
            publish_targets=list(bundle_summary.get("delivery_publish_targets") or []),
        ),
    )

    return _persist_distribution_bundle_summary(
        resolved_project_root,
        runtime_root=resolved_runtime_root,
        target_channel=normalized_target_channel,
        target_environment=normalized_target_environment,
        release_manifest_path=release_manifest_path,
        report_path=report_path,
    )


def export_release_distribution_publish_handoff(
    project_root: str | Path,
    runtime_root: Optional[str | Path] = None,
    *,
    target_channel: str = "",
    target_environment: str = "",
    release_manifest_path: str = "",
    report_path: str = "",
) -> Dict[str, Any]:
    resolved_project_root = Path(project_root).resolve()
    resolved_runtime_root = Path(runtime_root or Path.cwd()).resolve()
    normalized_target_channel = str(target_channel or "staging").strip().lower() or "staging"
    normalized_target_environment = str(target_environment or "").strip() or (
        "production" if normalized_target_channel == "release" else normalized_target_channel
    )
    export_release_distribution_handoff(
        resolved_project_root,
        runtime_root=resolved_runtime_root,
        target_channel=normalized_target_channel,
        target_environment=normalized_target_environment,
        release_manifest_path=release_manifest_path,
        report_path=report_path,
    )
    export_release_distribution_signing_handoff(
        resolved_project_root,
        runtime_root=resolved_runtime_root,
        target_channel=normalized_target_channel,
        target_environment=normalized_target_environment,
        release_manifest_path=release_manifest_path,
        report_path=report_path,
    )
    bundle_summary = build_release_distribution_bundle(
        resolved_project_root,
        runtime_root=resolved_runtime_root,
        target_channel=normalized_target_channel,
        target_environment=normalized_target_environment,
        release_manifest_path=release_manifest_path,
        report_path=report_path,
    )
    if list(bundle_summary.get("source_missing_items") or []) or list(bundle_summary.get("bundle_missing_items") or []):
        return _persist_distribution_bundle_summary(
            resolved_project_root,
            runtime_root=resolved_runtime_root,
            target_channel=normalized_target_channel,
            target_environment=normalized_target_environment,
            release_manifest_path=release_manifest_path,
            report_path=report_path,
        )
    if str(bundle_summary.get("install_smoke_status") or "").strip().lower() != "passed":
        return _persist_distribution_bundle_summary(
            resolved_project_root,
            runtime_root=resolved_runtime_root,
            target_channel=normalized_target_channel,
            target_environment=normalized_target_environment,
            release_manifest_path=release_manifest_path,
            report_path=report_path,
        )
    if str(bundle_summary.get("archive_status") or "").strip().lower() != "passed":
        return _persist_distribution_bundle_summary(
            resolved_project_root,
            runtime_root=resolved_runtime_root,
            target_channel=normalized_target_channel,
            target_environment=normalized_target_environment,
            release_manifest_path=release_manifest_path,
            report_path=report_path,
        )
    if str(bundle_summary.get("channel_index_status") or "").strip().lower() != "passed":
        return _persist_distribution_bundle_summary(
            resolved_project_root,
            runtime_root=resolved_runtime_root,
            target_channel=normalized_target_channel,
            target_environment=normalized_target_environment,
            release_manifest_path=release_manifest_path,
            report_path=report_path,
        )
    publish_targets = list(bundle_summary.get("delivery_publish_targets") or [])
    if not publish_targets:
        return _persist_distribution_bundle_summary(
            resolved_project_root,
            runtime_root=resolved_runtime_root,
            target_channel=normalized_target_channel,
            target_environment=normalized_target_environment,
            release_manifest_path=release_manifest_path,
            report_path=report_path,
        )

    publish_handoff_dir = (resolved_runtime_root / str(bundle_summary.get("publish_handoff_dir") or "")).resolve()
    if publish_handoff_dir.exists():
        shutil.rmtree(publish_handoff_dir, ignore_errors=True)
    publish_handoff_dir.mkdir(parents=True, exist_ok=True)

    archive_source = (resolved_runtime_root / str(bundle_summary.get("archive_path") or "")).resolve()
    archive_sha256_source = (resolved_runtime_root / str(bundle_summary.get("archive_sha256_path") or "")).resolve()
    latest_source = (resolved_runtime_root / str(bundle_summary.get("channel_index_latest_path") or "")).resolve()
    releases_source = (resolved_runtime_root / str(bundle_summary.get("channel_index_releases_path") or "")).resolve()
    manifest_source = (resolved_runtime_root / str(bundle_summary.get("bundle_manifest_copy_path") or "")).resolve()
    notes_source = (resolved_runtime_root / str(bundle_summary.get("bundle_release_notes_path") or "")).resolve()
    qa_gate_source = (resolved_runtime_root / str(bundle_summary.get("bundle_qa_gate_report_path") or "")).resolve()
    support_matrix_source = (resolved_runtime_root / str(bundle_summary.get("support_matrix_path") or "")).resolve()
    handoff_manifest_source = (resolved_runtime_root / str(bundle_summary.get("handoff_manifest_path") or "")).resolve()
    signing_manifest_source = (resolved_runtime_root / str(bundle_summary.get("signing_handoff_manifest_path") or "")).resolve()
    signing_instructions_source = (resolved_runtime_root / str(bundle_summary.get("signing_handoff_instructions_path") or "")).resolve()
    delivery_manifest_source = (resolved_project_root / default_release_distribution_delivery_path()).resolve()

    archive_destination = (resolved_runtime_root / str(bundle_summary.get("publish_handoff_archive_path") or "")).resolve()
    archive_sha256_destination = (
        resolved_runtime_root / str(bundle_summary.get("publish_handoff_archive_sha256_path") or "")
    ).resolve()
    latest_destination = (resolved_runtime_root / str(bundle_summary.get("publish_handoff_channel_latest_path") or "")).resolve()
    releases_destination = (resolved_runtime_root / str(bundle_summary.get("publish_handoff_channel_releases_path") or "")).resolve()
    manifest_destination = (publish_handoff_dir / "metadata" / "release_manifest.json").resolve()
    notes_destination = (publish_handoff_dir / "metadata" / "release_notes.md").resolve()
    qa_gate_destination = (publish_handoff_dir / "metadata" / "qa_gate_report.md").resolve()
    support_matrix_destination = (publish_handoff_dir / "metadata" / "support_matrix.md").resolve()
    target_payload_destination = (publish_handoff_dir / "targets" / "publish_targets.json").resolve()
    handoff_manifest_destination = (publish_handoff_dir / "inputs" / "distribution_handoff_manifest.json").resolve()
    signing_manifest_destination = (publish_handoff_dir / "inputs" / "distribution_signing_manifest.json").resolve()
    signing_instructions_destination = (publish_handoff_dir / "inputs" / "SIGNING_INSTRUCTIONS.md").resolve()
    delivery_manifest_destination = (publish_handoff_dir / "deployment" / "release_distribution_delivery.json").resolve()
    publish_manifest_destination = (resolved_runtime_root / str(bundle_summary.get("publish_handoff_manifest_path") or "")).resolve()
    instructions_destination = (
        resolved_runtime_root / str(bundle_summary.get("publish_handoff_instructions_path") or "")
    ).resolve()

    _copy_file(archive_source, archive_destination)
    _copy_file(archive_sha256_source, archive_sha256_destination)
    _copy_file(latest_source, latest_destination)
    _copy_file(releases_source, releases_destination)
    _copy_file(manifest_source, manifest_destination)
    _copy_file(notes_source, notes_destination)
    _copy_file(qa_gate_source, qa_gate_destination)
    _copy_file(support_matrix_source, support_matrix_destination)
    _write_json(
        target_payload_destination,
        {
            "schema_version": "1.0",
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "delivery_profile_id": str(bundle_summary.get("delivery_profile_id") or ""),
            "publish_targets": [
                {
                    "target_id": str(target_id or ""),
                    "sequence": index + 1,
                }
                for index, target_id in enumerate(publish_targets)
                if str(target_id or "").strip()
            ],
        },
    )
    if handoff_manifest_source.exists():
        _copy_file(handoff_manifest_source, handoff_manifest_destination)
    if signing_manifest_source.exists():
        _copy_file(signing_manifest_source, signing_manifest_destination)
    if signing_instructions_source.exists():
        _copy_file(signing_instructions_source, signing_instructions_destination)
    if delivery_manifest_source.exists():
        _copy_file(delivery_manifest_source, delivery_manifest_destination)

    publish_manifest = {
        "schema_version": "1.0",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "build_id": str(bundle_summary.get("build_id") or ""),
        "version": str(bundle_summary.get("version") or ""),
        "release_channel": str(bundle_summary.get("release_channel") or ""),
        "target_channel": normalized_target_channel,
        "target_environment": normalized_target_environment,
        "delivery_profile_id": str(bundle_summary.get("delivery_profile_id") or ""),
        "primary_installer": str(bundle_summary.get("delivery_primary_installer") or ""),
        "publish_targets": publish_targets,
        "signing_required": bool(bundle_summary.get("delivery_signing_required")),
        "signing_mode": str(bundle_summary.get("delivery_signing_mode") or ""),
        "signing_profile_id": str(bundle_summary.get("delivery_signing_profile_id") or ""),
        "archive_path": "payload/release_distribution_bundle.zip",
        "archive_sha256_path": "payload/release_distribution_bundle.sha256",
        "metadata_dir": "metadata",
        "channel_latest_path": "metadata/channel_latest.json",
        "channel_releases_path": "metadata/channel_releases.json",
        "release_manifest_path": "metadata/release_manifest.json",
        "release_notes_path": "metadata/release_notes.md",
        "qa_gate_report_path": "metadata/qa_gate_report.md",
        "support_matrix_path": "metadata/support_matrix.md",
        "publish_targets_path": "targets/publish_targets.json",
        "distribution_handoff_manifest_path": (
            "inputs/distribution_handoff_manifest.json" if handoff_manifest_source.exists() else ""
        ),
        "distribution_signing_manifest_path": (
            "inputs/distribution_signing_manifest.json" if signing_manifest_source.exists() else ""
        ),
        "distribution_signing_instructions_path": (
            "inputs/SIGNING_INSTRUCTIONS.md" if signing_instructions_source.exists() else ""
        ),
        "delivery_manifest_path": (
            "deployment/release_distribution_delivery.json" if delivery_manifest_source.exists() else ""
        ),
        "release_url": str(bundle_summary.get("release_url") or ""),
        "versioned_release_url": str(bundle_summary.get("versioned_release_url") or ""),
        "notes": [
            "Publish handoff bundles the verified archive, metadata, and publish target list needed by external distribution operators.",
            "If signing is required, pair this package with the signed artifact lineage emitted from distribution_signing_manifest.json before publishing.",
        ],
    }
    _write_json(publish_manifest_destination, publish_manifest)
    _write_text(
        instructions_destination,
        _build_publish_handoff_instructions(
            delivery_profile_id=str(bundle_summary.get("delivery_profile_id") or ""),
            signing_profile_id=str(bundle_summary.get("delivery_signing_profile_id") or ""),
            signing_mode=str(bundle_summary.get("delivery_signing_mode") or ""),
            publish_targets=publish_targets,
        ),
    )

    return _persist_distribution_bundle_summary(
        resolved_project_root,
        runtime_root=resolved_runtime_root,
        target_channel=normalized_target_channel,
        target_environment=normalized_target_environment,
        release_manifest_path=release_manifest_path,
        report_path=report_path,
    )


def record_release_distribution_publish_receipt(
    project_root: str | Path,
    runtime_root: Optional[str | Path] = None,
    *,
    target_channel: str = "",
    target_environment: str = "",
    release_manifest_path: str = "",
    report_path: str = "",
    target_id: str = "",
    status: str = "published",
    external_reference: str = "",
    artifact_url: str = "",
    operator: str = "",
    published_at: str = "",
    notes: Optional[List[str]] = None,
) -> Dict[str, Any]:
    resolved_project_root = Path(project_root).resolve()
    resolved_runtime_root = Path(runtime_root or Path.cwd()).resolve()
    normalized_target_channel = str(target_channel or "staging").strip().lower() or "staging"
    normalized_target_environment = str(target_environment or "").strip() or (
        "production" if normalized_target_channel == "release" else normalized_target_channel
    )
    normalized_target_id = _safe_segment(target_id or "")
    if not normalized_target_id:
        raise ValueError("target_id is required")
    bundle_summary = build_release_distribution_bundle(
        resolved_project_root,
        runtime_root=resolved_runtime_root,
        target_channel=normalized_target_channel,
        target_environment=normalized_target_environment,
        release_manifest_path=release_manifest_path,
        report_path=report_path,
    )
    if str(bundle_summary.get("publish_handoff_status") or "").strip().lower() != "passed":
        export_release_distribution_publish_handoff(
            resolved_project_root,
            runtime_root=resolved_runtime_root,
            target_channel=normalized_target_channel,
            target_environment=normalized_target_environment,
            release_manifest_path=release_manifest_path,
            report_path=report_path,
        )
        bundle_summary = build_release_distribution_bundle(
            resolved_project_root,
            runtime_root=resolved_runtime_root,
            target_channel=normalized_target_channel,
            target_environment=normalized_target_environment,
            release_manifest_path=release_manifest_path,
            report_path=report_path,
        )
    allowed_targets = _clean_text_list(bundle_summary.get("delivery_publish_targets"))
    if normalized_target_id not in allowed_targets:
        raise ValueError(
            f"target_id '{normalized_target_id}' is not declared in delivery_publish_targets: {', '.join(allowed_targets) or '-'}"
        )

    publish_receipts_dir = (resolved_runtime_root / str(bundle_summary.get("publish_receipts_dir") or "")).resolve()
    publish_receipts_dir.mkdir(parents=True, exist_ok=True)
    receipts_dir = (publish_receipts_dir / "receipts").resolve()
    receipts_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = (resolved_runtime_root / str(bundle_summary.get("publish_receipts_manifest_path") or "")).resolve()
    manifest_payload = _read_json(manifest_path)
    manifest_receipts = [
        dict(item)
        for item in list(manifest_payload.get("receipts") or [])
        if isinstance(item, dict)
    ]
    normalized_status = str(status or "published").strip().lower() or "published"
    normalized_notes = _clean_text_list(notes or [])
    normalized_published_at = str(published_at or "").strip() or datetime.now(timezone.utc).isoformat()
    receipt_relative_path = f"receipts/{normalized_target_id}.json"
    receipt_path = (publish_receipts_dir / receipt_relative_path).resolve()
    receipt_payload = {
        "schema_version": "1.0",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "build_id": str(bundle_summary.get("build_id") or ""),
        "version": str(bundle_summary.get("version") or ""),
        "release_channel": str(bundle_summary.get("release_channel") or ""),
        "target_channel": normalized_target_channel,
        "target_environment": normalized_target_environment,
        "delivery_profile_id": str(bundle_summary.get("delivery_profile_id") or ""),
        "target_id": normalized_target_id,
        "status": normalized_status,
        "published_at": normalized_published_at,
        "external_reference": str(external_reference or "").strip(),
        "artifact_url": str(artifact_url or "").strip(),
        "operator": str(operator or "").strip(),
        "notes": normalized_notes,
    }
    _write_json(receipt_path, receipt_payload)

    updated_receipts: List[Dict[str, Any]] = []
    replaced = False
    for entry in manifest_receipts:
        if str(entry.get("target_id") or "").strip() != normalized_target_id:
            updated_receipts.append(entry)
            continue
        updated_receipts.append({
            "target_id": normalized_target_id,
            "status": normalized_status,
            "published_at": normalized_published_at,
            "external_reference": str(external_reference or "").strip(),
            "artifact_url": str(artifact_url or "").strip(),
            "operator": str(operator or "").strip(),
            "receipt_path": receipt_relative_path,
            "notes": normalized_notes,
        })
        replaced = True
    if not replaced:
        updated_receipts.append({
            "target_id": normalized_target_id,
            "status": normalized_status,
            "published_at": normalized_published_at,
            "external_reference": str(external_reference or "").strip(),
            "artifact_url": str(artifact_url or "").strip(),
            "operator": str(operator or "").strip(),
            "receipt_path": receipt_relative_path,
            "notes": normalized_notes,
        })
    updated_receipts.sort(key=lambda item: str(item.get("target_id") or ""))
    _write_json(
        manifest_path,
        {
            "schema_version": "1.0",
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "build_id": str(bundle_summary.get("build_id") or ""),
            "version": str(bundle_summary.get("version") or ""),
            "release_channel": str(bundle_summary.get("release_channel") or ""),
            "target_channel": normalized_target_channel,
            "target_environment": normalized_target_environment,
            "delivery_profile_id": str(bundle_summary.get("delivery_profile_id") or ""),
            "publish_targets": allowed_targets,
            "receipt_count": len(updated_receipts),
            "receipts": updated_receipts,
        },
    )
    return _persist_distribution_bundle_summary(
        resolved_project_root,
        runtime_root=resolved_runtime_root,
        target_channel=normalized_target_channel,
        target_environment=normalized_target_environment,
        release_manifest_path=release_manifest_path,
        report_path=report_path,
    )


def build_release_distribution_bundle_report_lines(summary: Dict[str, Any] | None) -> List[str]:
    normalized = normalize_release_distribution_bundle(summary)
    lines = [
        f"- Status: {normalized.get('status') or 'skipped'}",
        f"- Summary: {normalized.get('summary') or '-'}",
        f"- Build: {normalized.get('build_id') or '-'} / version={normalized.get('version') or '-'} / channel={normalized.get('release_channel') or '-'}",
        f"- Bundle: {normalized.get('bundle_dir') or '-'} / exported={'yes' if normalized.get('bundle_exists') else 'no'} / files={normalized.get('bundle_file_count') or 0}",
        f"- Payload: {normalized.get('payload_dir') or '-'} / exported={'yes' if normalized.get('payload_exists') else 'no'} / files={normalized.get('payload_file_count') or 0}",
        f"- Scripts: install={normalized.get('install_script_path') or '-'} / upgrade={normalized.get('upgrade_script_path') or '-'} / uninstall={normalized.get('uninstall_script_path') or '-'}",
        f"- Distribution Manifest: {normalized.get('distribution_manifest_path') or '-'} / exported={'yes' if normalized.get('distribution_manifest_exists') else 'no'}",
        f"- Install Smoke: {normalized.get('install_smoke_status') or 'skipped'} / summary={normalized.get('install_smoke_summary') or '-'} / report={normalized.get('install_smoke_report_path') or '-'} / exported={'yes' if normalized.get('install_smoke_report_exists') else 'no'}",
        f"- Install Lifecycle: state={normalized.get('install_smoke_state_path') or '-'} / installed={normalized.get('install_smoke_installed_build_id') or '-'}:{normalized.get('install_smoke_installed_version') or '-'} / previous={normalized.get('install_smoke_previous_build_id') or '-'} / backup={normalized.get('install_smoke_backup_dir') or '-'} / removed={normalized.get('install_smoke_removed_build_id') or '-'}:{normalized.get('install_smoke_removed_version') or '-'}",
        f"- Archive: {normalized.get('archive_status') or 'skipped'} / summary={normalized.get('archive_summary') or '-'} / path={normalized.get('archive_path') or '-'} / exported={'yes' if normalized.get('archive_file_exists') else 'no'} / sha256={'yes' if normalized.get('archive_sha256_exists') else 'no'}",
        f"- Channel Index: {normalized.get('channel_index_status') or 'skipped'} / summary={normalized.get('channel_index_summary') or '-'} / latest={normalized.get('channel_index_latest_path') or '-'} / exported={'yes' if normalized.get('channel_index_latest_exists') else 'no'} / releases={normalized.get('channel_index_release_count') or 0}",
        f"- Handoff: {normalized.get('handoff_status') or 'skipped'} / summary={normalized.get('handoff_summary') or '-'} / dir={normalized.get('handoff_dir') or '-'} / exported={'yes' if normalized.get('handoff_exists') else 'no'} / files={normalized.get('handoff_file_count') or 0}",
        f"- Signing Handoff: {normalized.get('signing_handoff_status') or 'skipped'} / summary={normalized.get('signing_handoff_summary') or '-'} / dir={normalized.get('signing_handoff_dir') or '-'} / exported={'yes' if normalized.get('signing_handoff_exists') else 'no'} / files={normalized.get('signing_handoff_file_count') or 0}",
        f"- Publish Handoff: {normalized.get('publish_handoff_status') or 'skipped'} / summary={normalized.get('publish_handoff_summary') or '-'} / dir={normalized.get('publish_handoff_dir') or '-'} / exported={'yes' if normalized.get('publish_handoff_exists') else 'no'} / files={normalized.get('publish_handoff_file_count') or 0}",
        f"- Publish Receipts: {normalized.get('publish_receipts_status') or 'skipped'} / summary={normalized.get('publish_receipts_summary') or '-'} / dir={normalized.get('publish_receipts_dir') or '-'} / exported={'yes' if normalized.get('publish_receipts_exists') else 'no'} / completed={len(list(normalized.get('publish_receipts_completed_targets') or []))}/{normalized.get('publish_receipts_target_count') or 0}",
        f"- Support Matrix: {normalized.get('support_matrix_path') or '-'} / copied={'yes' if normalized.get('support_matrix_exists') else 'no'}",
        f"- Source Release Dir: {normalized.get('release_dir') or '-'} / output={normalized.get('output_path') or '-'}",
        f"- Report Path: {normalized.get('report_path') or '-'} / exported={'yes' if normalized.get('report_exists') else 'no'}",
    ]
    source_missing = list(normalized.get("source_missing_items") or [])
    bundle_missing = list(normalized.get("bundle_missing_items") or [])
    if source_missing:
        lines.append(f"- Source Missing: {', '.join(source_missing)}")
    if bundle_missing:
        lines.append(f"- Bundle Missing: {', '.join(bundle_missing)}")
    handoff_missing = list(normalized.get("handoff_missing_items") or [])
    if handoff_missing:
        lines.append(f"- Handoff Missing: {', '.join(handoff_missing)}")
    signing_handoff_missing = list(normalized.get("signing_handoff_missing_items") or [])
    if signing_handoff_missing:
        lines.append(f"- Signing Handoff Missing: {', '.join(signing_handoff_missing)}")
    publish_handoff_missing = list(normalized.get("publish_handoff_missing_items") or [])
    if publish_handoff_missing:
        lines.append(f"- Publish Handoff Missing: {', '.join(publish_handoff_missing)}")
    publish_receipts_missing = list(normalized.get("publish_receipts_missing_targets") or [])
    if publish_receipts_missing:
        lines.append(f"- Publish Receipt Targets Missing: {', '.join(publish_receipts_missing)}")
    exported_files = list(normalized.get("exported_files") or [])
    if exported_files:
        lines.append(f"- Exported Files: {', '.join(exported_files[:8])}")
    return lines


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _read_json(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return dict(json.loads(path.read_text(encoding="utf-8")) or {})
    except Exception:
        return {}


def _write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _copy_file(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)


def _count_files(path: Path) -> int:
    if not path.exists():
        return 0
    return sum(1 for item in path.rglob("*") if item.is_file())


def _relative_list(paths: Any, *, root: Optional[Path] = None) -> List[str]:
    values: List[str] = []
    for path in list(paths):
        if not isinstance(path, Path):
            continue
        if root is not None:
            values.append(_relative_to_root(path, root))
        else:
            values.append(path.as_posix())
    return sorted(values)


def _as_dict(value: Any) -> Dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _clean_text_list(value: Any) -> List[str]:
    if isinstance(value, str):
        parts = value.replace(";", ",").replace("\r", ",").replace("\n", ",").split(",")
    elif isinstance(value, (list, tuple, set)):
        parts = list(value)
    else:
        return []

    cleaned: List[str] = []
    seen: set[str] = set()
    for item in parts:
        text = str(item).strip()
        lowered = text.lower()
        if not text or lowered in seen:
            continue
        cleaned.append(text)
        seen.add(lowered)
    return cleaned


def _safe_segment(value: str) -> str:
    text = _SAFE_SEGMENT_RE.sub("_", str(value or "").strip())
    text = text.strip("._-")
    return text or "bundle"


def _build_install_script() -> str:
    return """[CmdletBinding()]
param(
    [string]$TargetRoot = ".\\installed_release",
    [switch]$MirrorCurrent = $true
)

$ErrorActionPreference = "Stop"
$BundleRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$ManifestPath = Join-Path $BundleRoot "distribution_manifest.json"
if (-not (Test-Path -LiteralPath $ManifestPath)) {
    throw "distribution_manifest.json not found: $ManifestPath"
}

$Manifest = Get-Content -LiteralPath $ManifestPath -Raw | ConvertFrom-Json
$PayloadRoot = Join-Path $BundleRoot $Manifest.payload_path
if (-not (Test-Path -LiteralPath $PayloadRoot)) {
    throw "release payload not found: $PayloadRoot"
}

$TargetRootPath = [System.IO.Path]::GetFullPath($TargetRoot)
$InstallDir = Join-Path $TargetRootPath $Manifest.build_id
$CurrentDir = Join-Path $TargetRootPath "current"
$MetaDir = Join-Path $TargetRootPath ".release_bundle"
$StatePath = Join-Path $MetaDir "installed_release.json"
$PreviousState = $null
if (Test-Path -LiteralPath $StatePath) {
    try {
        $PreviousState = Get-Content -LiteralPath $StatePath -Raw | ConvertFrom-Json
    } catch {
        $PreviousState = $null
    }
}

if (Test-Path -LiteralPath $InstallDir) {
    Remove-Item -LiteralPath $InstallDir -Recurse -Force
}
New-Item -ItemType Directory -Force -Path $InstallDir | Out-Null
New-Item -ItemType Directory -Force -Path $MetaDir | Out-Null
Copy-Item -Path (Join-Path $PayloadRoot "*") -Destination $InstallDir -Recurse -Force

if ($MirrorCurrent) {
    if (Test-Path -LiteralPath $CurrentDir) {
        Remove-Item -LiteralPath $CurrentDir -Recurse -Force
    }
    New-Item -ItemType Directory -Force -Path $CurrentDir | Out-Null
    Copy-Item -Path (Join-Path $InstallDir "*") -Destination $CurrentDir -Recurse -Force
}

$State = [ordered]@{
    schema_version = "1.0"
    last_operation = "install"
    build_id = $Manifest.build_id
    version = $Manifest.version
    channel = $Manifest.channel
    installed_at = [DateTime]::UtcNow.ToString("o")
    install_dir = $InstallDir
    current_dir = $(if ($MirrorCurrent) { $CurrentDir } else { "" })
    source_bundle = $BundleRoot
    bundle_manifest_path = $ManifestPath
    release_url = $Manifest.release_url
    versioned_release_url = $Manifest.versioned_release_url
    previous_build_id = $(if ($PreviousState) { [string]$PreviousState.build_id } else { "" })
    previous_version = $(if ($PreviousState) { [string]$PreviousState.version } else { "" })
    previous_channel = $(if ($PreviousState) { [string]$PreviousState.channel } else { "" })
    previous_source_bundle = $(if ($PreviousState) { [string]$PreviousState.source_bundle } else { "" })
    backup_dir = ""
    state_path = $StatePath
    mirror_current = [bool]$MirrorCurrent
}
$State | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $StatePath -Encoding UTF8
$State | ConvertTo-Json -Depth 5
"""


def _build_upgrade_script() -> str:
    return """[CmdletBinding()]
param(
    [string]$TargetRoot = ".\\installed_release",
    [switch]$MirrorCurrent = $true
)

$ErrorActionPreference = "Stop"
$BundleRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$ManifestPath = Join-Path $BundleRoot "distribution_manifest.json"
if (-not (Test-Path -LiteralPath $ManifestPath)) {
    throw "distribution_manifest.json not found: $ManifestPath"
}

$Manifest = Get-Content -LiteralPath $ManifestPath -Raw | ConvertFrom-Json
$PayloadRoot = Join-Path $BundleRoot $Manifest.payload_path
if (-not (Test-Path -LiteralPath $PayloadRoot)) {
    throw "release payload not found: $PayloadRoot"
}

$TargetRootPath = [System.IO.Path]::GetFullPath($TargetRoot)
$InstallDir = Join-Path $TargetRootPath $Manifest.build_id
$CurrentDir = Join-Path $TargetRootPath "current"
$BackupRoot = Join-Path $TargetRootPath "backups"
$MetaDir = Join-Path $TargetRootPath ".release_bundle"
$StatePath = Join-Path $MetaDir "installed_release.json"
$PreviousState = $null
if (Test-Path -LiteralPath $StatePath) {
    try {
        $PreviousState = Get-Content -LiteralPath $StatePath -Raw | ConvertFrom-Json
    } catch {
        $PreviousState = $null
    }
}
$BackupDir = ""

if (Test-Path -LiteralPath $CurrentDir) {
    New-Item -ItemType Directory -Force -Path $BackupRoot | Out-Null
    $BackupDir = Join-Path $BackupRoot ("{0}-{1}" -f (Get-Date -Format "yyyyMMddHHmmss"), $Manifest.build_id)
    New-Item -ItemType Directory -Force -Path $BackupDir | Out-Null
    Copy-Item -Path (Join-Path $CurrentDir "*") -Destination $BackupDir -Recurse -Force
}

if (Test-Path -LiteralPath $InstallDir) {
    Remove-Item -LiteralPath $InstallDir -Recurse -Force
}
New-Item -ItemType Directory -Force -Path $InstallDir | Out-Null
New-Item -ItemType Directory -Force -Path $MetaDir | Out-Null
Copy-Item -Path (Join-Path $PayloadRoot "*") -Destination $InstallDir -Recurse -Force

if ($MirrorCurrent) {
    if (Test-Path -LiteralPath $CurrentDir) {
        Remove-Item -LiteralPath $CurrentDir -Recurse -Force
    }
    New-Item -ItemType Directory -Force -Path $CurrentDir | Out-Null
    Copy-Item -Path (Join-Path $InstallDir "*") -Destination $CurrentDir -Recurse -Force
}

$State = [ordered]@{
    schema_version = "1.0"
    last_operation = "upgrade"
    build_id = $Manifest.build_id
    version = $Manifest.version
    channel = $Manifest.channel
    installed_at = [DateTime]::UtcNow.ToString("o")
    install_dir = $InstallDir
    current_dir = $(if ($MirrorCurrent) { $CurrentDir } else { "" })
    source_bundle = $BundleRoot
    bundle_manifest_path = $ManifestPath
    release_url = $Manifest.release_url
    versioned_release_url = $Manifest.versioned_release_url
    previous_build_id = $(if ($PreviousState) { [string]$PreviousState.build_id } else { "" })
    previous_version = $(if ($PreviousState) { [string]$PreviousState.version } else { "" })
    previous_channel = $(if ($PreviousState) { [string]$PreviousState.channel } else { "" })
    previous_source_bundle = $(if ($PreviousState) { [string]$PreviousState.source_bundle } else { "" })
    backup_dir = $BackupDir
    state_path = $StatePath
    mirror_current = [bool]$MirrorCurrent
}
$State | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $StatePath -Encoding UTF8
$State | ConvertTo-Json -Depth 5
"""


def _build_uninstall_script() -> str:
    return """[CmdletBinding()]
param(
    [string]$TargetRoot = ".\\installed_release",
    [string]$BuildId = "",
    [switch]$RemoveCurrent = $true
)

$ErrorActionPreference = "Stop"
$BundleRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$ManifestPath = Join-Path $BundleRoot "distribution_manifest.json"
if (-not (Test-Path -LiteralPath $ManifestPath)) {
    throw "distribution_manifest.json not found: $ManifestPath"
}

$Manifest = Get-Content -LiteralPath $ManifestPath -Raw | ConvertFrom-Json
$TargetRootPath = [System.IO.Path]::GetFullPath($TargetRoot)
$SelectedBuildId = $(if ([string]::IsNullOrWhiteSpace($BuildId)) { $Manifest.build_id } else { $BuildId })
$InstallDir = Join-Path $TargetRootPath $SelectedBuildId
$CurrentDir = Join-Path $TargetRootPath "current"
$MetaDir = Join-Path $TargetRootPath ".release_bundle"
$StatePath = Join-Path $MetaDir "installed_release.json"
$PreviousState = $null
if (Test-Path -LiteralPath $StatePath) {
    try {
        $PreviousState = Get-Content -LiteralPath $StatePath -Raw | ConvertFrom-Json
    } catch {
        $PreviousState = $null
    }
}

if (Test-Path -LiteralPath $InstallDir) {
    Remove-Item -LiteralPath $InstallDir -Recurse -Force
}

if ($RemoveCurrent -and (Test-Path -LiteralPath $CurrentDir)) {
    Remove-Item -LiteralPath $CurrentDir -Recurse -Force
}

if (Test-Path -LiteralPath $StatePath) {
    $State = Get-Content -LiteralPath $StatePath -Raw | ConvertFrom-Json
    if ($State.build_id -eq $SelectedBuildId) {
        Remove-Item -LiteralPath $StatePath -Force
    }
}

if ((Test-Path -LiteralPath $MetaDir) -and -not (Get-ChildItem -LiteralPath $MetaDir -Force | Select-Object -First 1)) {
    Remove-Item -LiteralPath $MetaDir -Force
}

[ordered]@{
    removed_build_id = $SelectedBuildId
    removed_version = $(if ($PreviousState -and [string]$PreviousState.build_id -eq $SelectedBuildId) { [string]$PreviousState.version } else { "" })
    removed_channel = $(if ($PreviousState -and [string]$PreviousState.build_id -eq $SelectedBuildId) { [string]$PreviousState.channel } else { "" })
    removed_source_bundle = $(if ($PreviousState -and [string]$PreviousState.build_id -eq $SelectedBuildId) { [string]$PreviousState.source_bundle } else { "" })
    install_removed = [bool](-not (Test-Path -LiteralPath $InstallDir))
    current_removed = [bool]$RemoveCurrent
    target_root = $TargetRootPath
    state_path = $StatePath
    state_removed = [bool](-not (Test-Path -LiteralPath $StatePath))
} | ConvertTo-Json -Depth 5
"""


def _build_handoff_install_script() -> str:
    return _build_handoff_wrapper_script(
        operation="install",
        bundle_script_property="bundle_install_script_path",
        extra_param_block='    [switch]$MirrorCurrent = $true,\n',
        bundle_argument_block='-TargetRoot $TargetRoot -MirrorCurrent:$MirrorCurrent',
        success_summary="handoff install completed",
    )


def _build_handoff_upgrade_script() -> str:
    return _build_handoff_wrapper_script(
        operation="upgrade",
        bundle_script_property="bundle_upgrade_script_path",
        extra_param_block='    [switch]$MirrorCurrent = $true,\n',
        bundle_argument_block='-TargetRoot $TargetRoot -MirrorCurrent:$MirrorCurrent',
        success_summary="handoff upgrade completed",
    )


def _build_handoff_uninstall_script() -> str:
    return _build_handoff_wrapper_script(
        operation="uninstall",
        bundle_script_property="bundle_uninstall_script_path",
        extra_param_block='    [string]$BuildId = "",\n    [switch]$RemoveCurrent = $true,\n',
        bundle_argument_block='-TargetRoot $TargetRoot -BuildId $BuildId -RemoveCurrent:$RemoveCurrent',
        success_summary="handoff uninstall completed",
    )


def _build_signing_handoff_instructions(
    *,
    delivery_profile_id: str,
    signing_profile_id: str,
    signing_mode: str,
    publish_targets: List[str],
) -> str:
    publish_target_text = ", ".join(str(item).strip() for item in publish_targets if str(item).strip()) or "-"
    return (
        "# Distribution Signing Handoff\n\n"
        f"- Delivery Profile: {delivery_profile_id or '-'}\n"
        f"- Signing Profile: {signing_profile_id or '-'}\n"
        f"- Signing Mode: {signing_mode or '-'}\n"
        f"- Publish Targets: {publish_target_text}\n\n"
        "Expected operator flow:\n"
        "1. Verify `unsigned/release_distribution_bundle.zip` against `unsigned/release_distribution_bundle.sha256`.\n"
        "2. Apply the external signing / notarization process referenced by the signing profile.\n"
        "3. Preserve a traceable mapping from the signed artifact back to `distribution_signing_manifest.json`.\n"
        "4. Return the signed artifact and signing evidence to the release operator for final channel publication.\n"
    )


def _build_publish_handoff_instructions(
    *,
    delivery_profile_id: str,
    signing_profile_id: str,
    signing_mode: str,
    publish_targets: List[str],
) -> str:
    publish_target_text = ", ".join(str(item).strip() for item in publish_targets if str(item).strip()) or "-"
    return (
        "# Distribution Publish Handoff Instructions\n\n"
        f"- Delivery Profile: {delivery_profile_id or '-'}\n"
        f"- Publish Targets: {publish_target_text}\n"
        f"- Signing Mode: {signing_mode or '-'}\n"
        f"- Signing Profile: {signing_profile_id or '-'}\n\n"
        "1. Review `distribution_publish_manifest.json` and confirm `build_id / version / channel` match the intended release lane.\n"
        "2. If signing is still pending, wait for the signed artifact lineage tied to `distribution_signing_manifest.json` before publishing externally.\n"
        "3. Promote the verified archive to each publish target listed in `targets/publish_targets.json` and retain an external publish receipt per target.\n"
        "4. Keep the copied `channel_latest.json` / `channel_releases.json` and release notes aligned with the external channel entry.\n"
    )


def _build_handoff_wrapper_script(
    *,
    operation: str,
    bundle_script_property: str,
    extra_param_block: str,
    bundle_argument_block: str,
    success_summary: str,
) -> str:
    return f"""[CmdletBinding()]
param(
    [string]$TargetRoot = ".\\installed_release",
{extra_param_block}    [string]$TempRoot = "",
    [switch]$KeepExpandedBundle
)

$ErrorActionPreference = "Stop"

function Resolve-UnderRoot {{
    param(
        [string]$BasePath,
        [string]$RelativePath
    )

    if ([string]::IsNullOrWhiteSpace($RelativePath)) {{
        return [System.IO.Path]::GetFullPath($BasePath)
    }}
    if ([System.IO.Path]::IsPathRooted($RelativePath)) {{
        return [System.IO.Path]::GetFullPath($RelativePath)
    }}
    return [System.IO.Path]::GetFullPath((Join-Path $BasePath $RelativePath))
}}

$HandoffRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$ManifestPath = Join-Path $HandoffRoot "distribution_handoff_manifest.json"
if (-not (Test-Path -LiteralPath $ManifestPath)) {{
    throw "distribution_handoff_manifest.json not found: $ManifestPath"
}}

$Manifest = Get-Content -LiteralPath $ManifestPath -Raw | ConvertFrom-Json
$ArchivePath = Resolve-UnderRoot -BasePath $HandoffRoot -RelativePath ([string]$Manifest.package_archive_path)
if (-not (Test-Path -LiteralPath $ArchivePath)) {{
    throw "handoff archive not found: $ArchivePath"
}}

$TargetRootPath = [System.IO.Path]::GetFullPath($TargetRoot)
if ([string]::IsNullOrWhiteSpace($TempRoot)) {{
    $TempRoot = Join-Path $HandoffRoot ".handoff_tmp"
}}
$TempRootPath = [System.IO.Path]::GetFullPath($TempRoot)
New-Item -ItemType Directory -Force -Path $TempRootPath | Out-Null
$ExtractRoot = Join-Path $TempRootPath ("{operation}_{0}_{1}" -f [string]$Manifest.build_id, [Guid]::NewGuid().ToString("N"))
New-Item -ItemType Directory -Force -Path $ExtractRoot | Out-Null

Expand-Archive -LiteralPath $ArchivePath -DestinationPath $ExtractRoot -Force
$BundleRootEntry = Get-ChildItem -LiteralPath $ExtractRoot -Directory | Select-Object -First 1
if ($null -eq $BundleRootEntry) {{
    throw "expanded bundle root not found: $ExtractRoot"
}}
$BundleRoot = $BundleRootEntry.FullName
$BundleScriptPath = Resolve-UnderRoot -BasePath $BundleRoot -RelativePath ([string]$Manifest.{bundle_script_property})
if (-not (Test-Path -LiteralPath $BundleScriptPath)) {{
    throw "bundle script not found: $BundleScriptPath"
}}

$ExitCode = 0
$InnerOutput = @()
try {{
    $InnerOutput = @(& $BundleScriptPath {bundle_argument_block} 2>&1)
}} catch {{
    $ExitCode = 1
    $InnerOutput = @($_.Exception.Message)
}}

$InnerOutputText = ($InnerOutput | ForEach-Object {{ $_.ToString() }}) -join [Environment]::NewLine
$InnerResult = $null
if (-not [string]::IsNullOrWhiteSpace($InnerOutputText)) {{
    try {{
        $InnerResult = $InnerOutputText | ConvertFrom-Json
    }} catch {{
        $InnerResult = $null
    }}
}}

if (-not $KeepExpandedBundle -and (Test-Path -LiteralPath $ExtractRoot)) {{
    Remove-Item -LiteralPath $ExtractRoot -Recurse -Force
}}

[ordered]@{{
    schema_version = "1.0"
    operation = "{operation}"
    status = $(if ($ExitCode -eq 0) {{ "passed" }} else {{ "blocked" }})
    summary = $(if ($ExitCode -eq 0) {{ "{success_summary}" }} else {{ "handoff {operation} failed" }})
    build_id = [string]$Manifest.build_id
    version = [string]$Manifest.version
    release_channel = [string]$Manifest.release_channel
    target_channel = [string]$Manifest.target_channel
    target_environment = [string]$Manifest.target_environment
    handoff_root = $HandoffRoot
    manifest_path = $ManifestPath
    archive_path = $ArchivePath
    extracted_bundle_path = $BundleRoot
    bundle_script_path = $BundleScriptPath
    target_root = $TargetRootPath
    kept_expanded_bundle = [bool]$KeepExpandedBundle
    inner_result = $InnerResult
    inner_output = $InnerOutputText
}} | ConvertTo-Json -Depth 10

if ($ExitCode -ne 0) {{
    exit $ExitCode
}}
"""


_POWERSHELL_SCRIPT_TIMEOUT_SECONDS = 30


def _run_powershell_script(executable: str, script_path: Path, arguments: List[str]) -> Dict[str, Any]:
    command = [
        executable,
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        str(script_path),
        *list(arguments),
    ]
    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
            timeout=_POWERSHELL_SCRIPT_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired as exc:
        return {
            "returncode": 124,
            "stdout": str(exc.stdout or ""),
            "stderr": f"PowerShell script timed out after {_POWERSHELL_SCRIPT_TIMEOUT_SECONDS}s",
        }
    return {
        "returncode": int(completed.returncode),
        "stdout": str(completed.stdout or ""),
        "stderr": str(completed.stderr or ""),
    }


def _run_failure_message(result: Dict[str, Any], fallback: str) -> str:
    stdout = str(result.get("stdout") or "").strip()
    stderr = str(result.get("stderr") or "").strip()
    detail = stderr or stdout
    return f"{fallback}: {detail}" if detail else fallback


def _parse_result_payload(result: Dict[str, Any]) -> Dict[str, Any]:
    stdout = str(result.get("stdout") or "").strip()
    if not stdout:
        return {}
    try:
        return dict(json.loads(stdout) or {})
    except Exception:
        return {}

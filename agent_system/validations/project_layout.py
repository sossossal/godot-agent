"""
Project layout and naming validation for managed outputs.

This validator intentionally scopes itself to managed directories so that
existing repo content such as localized docs is not treated as invalid.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple


PROJECT_LAYOUT_SCHEMA_VERSION = "1.0"

_SAFE_NAME_RE = re.compile(r"^[A-Za-z0-9._-]+$")
_SNAKE_CASE_RE = re.compile(r"^[a-z0-9_]+$")
_SCENE_STEM_RE = re.compile(r"^[A-Za-z0-9_]+$")

_PROJECT_SCAN_ROOTS = [
    "data_tables",
    "scripts",
    "scenes",
    "assets/manifests",
    "assets/textures",
    "assets/ui",
    "assets/models",
    "assets/characters/spine",
    "assets/materials",
    "assets/materials/substance",
    "assets/vfx",
    "assets/packages/outsource",
    "assets/shaders",
    "assets/audio",
    "telemetry",
    "liveops",
    "deployment",
    "agent_modules/scripts",
    "agent_modules/scenes",
]

_RUNTIME_SCAN_ROOTS = [
    "logs/reports",
    "logs/test_artifacts",
    "logs/visual_feedback",
    "api_server/static/dist",
    "tests/baselines/screenshots",
    "tests/baselines/performance",
    "tests/baselines/telemetry",
]


@dataclass
class LayoutIssue:
    code: str
    message: str
    path: str
    kind: str
    scope: str

    def to_dict(self) -> Dict[str, str]:
        return {
            "code": self.code,
            "message": self.message,
            "path": self.path,
            "kind": self.kind,
            "scope": self.scope,
        }


class ProjectLayoutValidator:
    def __init__(self, project_root: Optional[str | Path] = None, runtime_root: Optional[str | Path] = None):
        self.project_root = Path(project_root or ".").absolute()
        self.runtime_root = Path(runtime_root or Path.cwd()).absolute()

    def validate_managed_path(self, path: str | Path, kind: str) -> Dict[str, Any]:
        target = Path(path).absolute()
        scope, relative = self._resolve_scope_for_kind(target, kind)
        issues: List[LayoutIssue] = []

        if scope is None or relative is None:
            issues.append(self._issue(
                "outside_scope",
                "Path is outside the managed project/runtime roots",
                target,
                kind,
                scope or "unknown",
            ))
            return self._build_result(target, kind, scope or "unknown", issues)

        issues.extend(self._validate_generic_name_rules(relative, target, kind, scope))
        issues.extend(self._validate_kind_rules(relative, target, kind, scope))
        return self._build_result(target, kind, scope, issues)

    def audit_managed_layout(self) -> Dict[str, Any]:
        issues: List[LayoutIssue] = []
        scanned_files = 0

        for root in self._iter_scan_roots():
            if not root.exists():
                continue
            for file_path in root.rglob("*"):
                if not file_path.is_file():
                    continue
                kind = self._infer_kind(file_path)
                if not kind:
                    continue
                scanned_files += 1
                result = self.validate_managed_path(file_path, kind)
                issues.extend(LayoutIssue(**item) for item in result["issues"])

        return {
            "schema_version": PROJECT_LAYOUT_SCHEMA_VERSION,
            "passed": not issues,
            "scanned_file_count": scanned_files,
            "issue_count": len(issues),
            "issues": [issue.to_dict() for issue in issues],
        }

    def required_runtime_directories(self) -> List[str]:
        return [
            "logs",
            "logs/backups",
            "logs/reports",
            "logs/test_artifacts",
            "api_server/static/dist",
        ]

    def _build_result(self, target: Path, kind: str, scope: str, issues: List[LayoutIssue]) -> Dict[str, Any]:
        return {
            "schema_version": PROJECT_LAYOUT_SCHEMA_VERSION,
            "passed": not issues,
            "path": str(target),
            "kind": kind,
            "scope": scope,
            "issues": [issue.to_dict() for issue in issues],
        }

    def _relative_to_root(self, target: Path, root: Path) -> Optional[Path]:
        try:
            return target.relative_to(root)
        except ValueError:
            return None

    def _resolve_scope(self, target: Path) -> Tuple[Optional[str], Optional[Path]]:
        project_relative = self._relative_to_root(target, self.project_root)
        if project_relative is not None:
            return "project", project_relative
        runtime_relative = self._relative_to_root(target, self.runtime_root)
        if runtime_relative is not None:
            return "runtime", runtime_relative
        return None, None

    def _resolve_scope_for_kind(self, target: Path, kind: str) -> Tuple[Optional[str], Optional[Path]]:
        if kind in {"data_table", "generated_script", "generated_scene", "art_asset", "asset_manifest", "telemetry_catalog", "telemetry_session", "liveops_manifest", "platform_delivery_manifest", "scene_ownership_manifest", "release_access_policy_manifest", "release_request_auth_manifest", "release_identity_registry_manifest", "release_capability_registry_manifest", "release_promotion_history_manifest", "release_execution_status_manifest", "release_channel_manifest"}:
            priorities = (("project", self.project_root), ("runtime", self.runtime_root))
        else:
            priorities = (("runtime", self.runtime_root), ("project", self.project_root))

        for scope_name, root in priorities:
            relative = self._relative_to_root(target, root)
            if relative is not None:
                return scope_name, relative
        return None, None

    def _iter_scan_roots(self) -> Iterable[Path]:
        seen: set[Path] = set()
        for relative in _PROJECT_SCAN_ROOTS:
            root = (self.project_root / relative).absolute()
            if root not in seen:
                seen.add(root)
                yield root
        for relative in _RUNTIME_SCAN_ROOTS:
            root = (self.runtime_root / relative).absolute()
            if root not in seen:
                seen.add(root)
                yield root

    def _infer_kind(self, file_path: Path) -> Optional[str]:
        target = file_path.absolute()
        name = file_path.name.lower()
        suffix = file_path.suffix.lower()

        project_relative = self._relative_to_root(target, self.project_root)
        if project_relative is not None:
            project_normalized = project_relative.as_posix()
            if project_normalized.startswith("data_tables/") and suffix in {".csv", ".tsv", ".json"}:
                return "data_table"
            if project_normalized.startswith("assets/manifests/") and suffix == ".json":
                return "asset_manifest"
            if project_normalized == "telemetry/event_catalog.json":
                return "telemetry_catalog"
            if project_normalized.startswith("telemetry/sessions/") and suffix in {".json", ".jsonl"}:
                return "telemetry_session"
            if project_normalized in {"liveops/remote_config.json", "liveops/experiments.json"}:
                return "liveops_manifest"
            if project_normalized == "deployment/platform_delivery.json":
                return "platform_delivery_manifest"
            if project_normalized == "deployment/release_access_policy.json":
                return "release_access_policy_manifest"
            if project_normalized == "deployment/release_request_auth.json":
                return "release_request_auth_manifest"
            if project_normalized == "deployment/release_identity_registry.json":
                return "release_identity_registry_manifest"
            if project_normalized == "deployment/release_capability_registry.json":
                return "release_capability_registry_manifest"
            if project_normalized == "deployment/release_promotion_history.json":
                return "release_promotion_history_manifest"
            if project_normalized == "deployment/release_execution_status.json":
                return "release_execution_status_manifest"
            if project_normalized == "deployment/release_channels.json":
                return "release_channel_manifest"
            if project_normalized == "scenes/scene_ownership_board.json":
                return "scene_ownership_manifest"
            if project_normalized.startswith(("scripts/", "agent_modules/scripts/")) and suffix == ".gd":
                return "generated_script"
            if project_normalized.startswith(("scenes/", "agent_modules/scenes/")) and suffix == ".tscn":
                return "generated_scene"

        runtime_relative = self._relative_to_root(target, self.runtime_root)
        if runtime_relative is None:
            return None
        normalized = runtime_relative.as_posix()
        if normalized.startswith("logs/reports/") and suffix in {".md", ".json", ".txt"}:
            return "runtime_report"
        if normalized.startswith(("logs/test_artifacts/", "logs/visual_feedback/")) and suffix in {".png", ".jpg", ".jpeg", ".json", ".txt"}:
            return "runtime_screenshot"
        if normalized.startswith("api_server/static/dist/"):
            if name == "release_manifest.json":
                return "release_manifest"
            if name in {"release_notes.md", "qa_gate_report.md", "build.log"}:
                return "release_report"
            if suffix in {".html", ".exe"}:
                return "release_output"
        if normalized.startswith("tests/baselines/"):
            return "baseline_artifact"
        return None

    def _validate_generic_name_rules(self, relative: Path, target: Path, kind: str, scope: str) -> List[LayoutIssue]:
        issues: List[LayoutIssue] = []
        for part in relative.parts:
            if not part:
                continue
            if part in {".", ".."}:
                issues.append(self._issue(
                    "relative_escape",
                    "Managed paths may not contain relative traversal segments",
                    target,
                    kind,
                    scope,
                ))
            if " " in part:
                issues.append(self._issue(
                    "whitespace_name",
                    "Managed path segments may not contain spaces",
                    target,
                    kind,
                    scope,
                ))
            if not _SAFE_NAME_RE.match(part):
                issues.append(self._issue(
                    "unsafe_name",
                    "Managed path segments must use ASCII letters, digits, dot, underscore or dash",
                    target,
                    kind,
                    scope,
                ))
        return issues

    def _validate_kind_rules(self, relative: Path, target: Path, kind: str, scope: str) -> List[LayoutIssue]:
        normalized = relative.as_posix()
        suffix = target.suffix.lower()
        stem = target.stem
        issues: List[LayoutIssue] = []

        def require(condition: bool, code: str, message: str):
            if not condition:
                issues.append(self._issue(code, message, target, kind, scope))

        if kind == "data_table":
            require(scope == "project", "wrong_scope", "Data tables must live under the project root")
            require(normalized.startswith("data_tables/"), "wrong_directory", "Data tables must live under data_tables/")
            require(suffix in {".csv", ".tsv", ".json"}, "wrong_extension", "Data tables must use .csv, .tsv or .json")
            require(bool(_SNAKE_CASE_RE.match(stem)), "wrong_name", "Data table file names must use snake_case")
            return issues

        if kind == "generated_script":
            require(scope == "project", "wrong_scope", "Generated scripts must live under the project root")
            require(normalized.startswith(("scripts/", "agent_modules/scripts/")), "wrong_directory", "Generated scripts must live under scripts/ or agent_modules/scripts/")
            require(suffix == ".gd", "wrong_extension", "Generated scripts must use .gd")
            require(bool(_SNAKE_CASE_RE.match(stem)), "wrong_name", "Generated script file names must use snake_case")
            return issues

        if kind == "generated_scene":
            require(scope == "project", "wrong_scope", "Generated scenes must live under the project root")
            require(normalized.startswith(("scenes/", "agent_modules/scenes/")), "wrong_directory", "Generated scenes must live under scenes/ or agent_modules/scenes/")
            require(suffix == ".tscn", "wrong_extension", "Generated scenes must use .tscn")
            require(bool(_SCENE_STEM_RE.match(stem)), "wrong_name", "Scene file names must use letters, digits or underscore")
            return issues

        if kind == "art_asset":
            require(scope == "project", "wrong_scope", "Art assets must live under the project root")
            require(normalized.startswith("assets/"), "wrong_directory", "Art assets must live under assets/")
            require(
                suffix in {".png", ".jpg", ".jpeg", ".webp", ".tres", ".res", ".tscn", ".ogg", ".wav", ".mp3", ".flac", ".import", ".gdshader", ".glb", ".gltf", ".json", ".atlas", ".zip"},
                "wrong_extension",
                "Art assets must use an approved resource extension",
            )
            require(bool(_SNAKE_CASE_RE.match(stem)), "wrong_name", "Art asset file names must use snake_case")
            return issues

        if kind == "asset_manifest":
            require(scope == "project", "wrong_scope", "Asset manifests must live under the project root")
            require(normalized.startswith("assets/manifests/"), "wrong_directory", "Asset manifests must live under assets/manifests/")
            require(suffix == ".json", "wrong_extension", "Asset manifests must use .json")
            require(bool(_SNAKE_CASE_RE.match(stem)), "wrong_name", "Asset manifest file names must use snake_case")
            return issues

        if kind == "telemetry_catalog":
            require(scope == "project", "wrong_scope", "Telemetry catalog must live under the project root")
            require(normalized == "telemetry/event_catalog.json", "wrong_directory", "Telemetry catalog must be telemetry/event_catalog.json")
            require(target.name == "event_catalog.json", "wrong_name", "Telemetry catalog file name must be event_catalog.json")
            return issues

        if kind == "telemetry_session":
            require(scope == "project", "wrong_scope", "Telemetry session logs must live under the project root")
            require(normalized.startswith("telemetry/sessions/"), "wrong_directory", "Telemetry sessions must live under telemetry/sessions/")
            require(suffix in {".json", ".jsonl"}, "wrong_extension", "Telemetry sessions must use .json or .jsonl")
            require(bool(_SNAKE_CASE_RE.match(stem)), "wrong_name", "Telemetry session file names must use snake_case")
            return issues

        if kind == "liveops_manifest":
            require(scope == "project", "wrong_scope", "LiveOps manifests must live under the project root")
            require(normalized in {"liveops/remote_config.json", "liveops/experiments.json"}, "wrong_directory", "LiveOps manifests must be liveops/remote_config.json or liveops/experiments.json")
            require(suffix == ".json", "wrong_extension", "LiveOps manifests must use .json")
            require(target.name in {"remote_config.json", "experiments.json"}, "wrong_name", "LiveOps manifest names must be remote_config.json or experiments.json")
            return issues

        if kind == "platform_delivery_manifest":
            require(scope == "project", "wrong_scope", "Platform delivery manifest must live under the project root")
            require(normalized == "deployment/platform_delivery.json", "wrong_directory", "Platform delivery manifest must be deployment/platform_delivery.json")
            require(suffix == ".json", "wrong_extension", "Platform delivery manifest must use .json")
            require(target.name == "platform_delivery.json", "wrong_name", "Platform delivery manifest name must be platform_delivery.json")
            return issues

        if kind == "release_access_policy_manifest":
            require(scope == "project", "wrong_scope", "Release access policy must live under the project root")
            require(normalized == "deployment/release_access_policy.json", "wrong_directory", "Release access policy must be deployment/release_access_policy.json")
            require(suffix == ".json", "wrong_extension", "Release access policy must use .json")
            require(target.name == "release_access_policy.json", "wrong_name", "Release access policy name must be release_access_policy.json")
            return issues

        if kind == "release_request_auth_manifest":
            require(scope == "project", "wrong_scope", "Release request auth manifest must live under the project root")
            require(normalized == "deployment/release_request_auth.json", "wrong_directory", "Release request auth manifest must be deployment/release_request_auth.json")
            require(suffix == ".json", "wrong_extension", "Release request auth manifest must use .json")
            require(target.name == "release_request_auth.json", "wrong_name", "Release request auth manifest name must be release_request_auth.json")
            return issues

        if kind == "release_identity_registry_manifest":
            require(scope == "project", "wrong_scope", "Release identity registry must live under the project root")
            require(normalized == "deployment/release_identity_registry.json", "wrong_directory", "Release identity registry must be deployment/release_identity_registry.json")
            require(suffix == ".json", "wrong_extension", "Release identity registry must use .json")
            require(target.name == "release_identity_registry.json", "wrong_name", "Release identity registry name must be release_identity_registry.json")
            return issues

        if kind == "release_capability_registry_manifest":
            require(scope == "project", "wrong_scope", "Release capability registry must live under the project root")
            require(normalized == "deployment/release_capability_registry.json", "wrong_directory", "Release capability registry must be deployment/release_capability_registry.json")
            require(suffix == ".json", "wrong_extension", "Release capability registry must use .json")
            require(target.name == "release_capability_registry.json", "wrong_name", "Release capability registry name must be release_capability_registry.json")
            return issues

        if kind == "scene_ownership_manifest":
            require(scope == "project", "wrong_scope", "Scene ownership board must live under the project root")
            require(normalized == "scenes/scene_ownership_board.json", "wrong_directory", "Scene ownership board must be scenes/scene_ownership_board.json")
            require(suffix == ".json", "wrong_extension", "Scene ownership board must use .json")
            require(target.name == "scene_ownership_board.json", "wrong_name", "Scene ownership board name must be scene_ownership_board.json")
            return issues

        if kind == "release_promotion_history_manifest":
            require(scope == "project", "wrong_scope", "Release promotion history must live under the project root")
            require(normalized == "deployment/release_promotion_history.json", "wrong_directory", "Release promotion history must be deployment/release_promotion_history.json")
            require(suffix == ".json", "wrong_extension", "Release promotion history must use .json")
            require(target.name == "release_promotion_history.json", "wrong_name", "Release promotion history name must be release_promotion_history.json")
            return issues

        if kind == "release_execution_status_manifest":
            require(scope == "project", "wrong_scope", "Release execution status must live under the project root")
            require(normalized == "deployment/release_execution_status.json", "wrong_directory", "Release execution status must be deployment/release_execution_status.json")
            require(suffix == ".json", "wrong_extension", "Release execution status must use .json")
            require(target.name == "release_execution_status.json", "wrong_name", "Release execution status name must be release_execution_status.json")
            return issues

        if kind == "release_channel_manifest":
            require(scope == "project", "wrong_scope", "Release channel manifest must live under the project root")
            require(normalized == "deployment/release_channels.json", "wrong_directory", "Release channel manifest must be deployment/release_channels.json")
            require(suffix == ".json", "wrong_extension", "Release channel manifest must use .json")
            require(target.name == "release_channels.json", "wrong_name", "Release channel manifest name must be release_channels.json")
            return issues

        if kind == "runtime_report":
            require(scope == "runtime", "wrong_scope", "Runtime reports must live under the runtime root")
            require(normalized.startswith("logs/reports/"), "wrong_directory", "Runtime reports must live under logs/reports/")
            require(suffix in {".md", ".json", ".txt"}, "wrong_extension", "Runtime reports must use .md, .json or .txt")
            return issues

        if kind == "runtime_screenshot":
            require(scope == "runtime", "wrong_scope", "Runtime screenshots must live under the runtime root")
            require(
                normalized.startswith(("logs/test_artifacts/", "logs/visual_feedback/")),
                "wrong_directory",
                "Runtime screenshots must live under logs/test_artifacts/ or logs/visual_feedback/",
            )
            require(suffix in {".png", ".jpg", ".jpeg", ".json", ".txt"}, "wrong_extension", "Runtime screenshot artifacts must use approved image/text extensions")
            return issues

        if kind == "release_output":
            require(scope == "runtime", "wrong_scope", "Release outputs must live under the runtime root")
            require(normalized.startswith("api_server/static/dist/"), "wrong_directory", "Release outputs must live under api_server/static/dist/")
            require(suffix in {".html", ".exe"}, "wrong_extension", "Release outputs must use .html or .exe")
            return issues

        if kind == "release_report":
            require(scope == "runtime", "wrong_scope", "Release reports must live under the runtime root")
            require(normalized.startswith("api_server/static/dist/"), "wrong_directory", "Release reports must live under api_server/static/dist/")
            require(target.name in {"release_notes.md", "qa_gate_report.md", "build.log"}, "wrong_name", "Release report names must use the standard file names")
            return issues

        if kind == "release_manifest":
            require(scope == "runtime", "wrong_scope", "Release manifests must live under the runtime root")
            require(normalized.startswith("api_server/static/dist/"), "wrong_directory", "Release manifests must live under api_server/static/dist/")
            require(target.name == "release_manifest.json", "wrong_name", "Release manifest name must be release_manifest.json")
            return issues

        if kind == "baseline_artifact":
            require(scope == "runtime", "wrong_scope", "Baselines must live under the runtime root")
            require(normalized.startswith("tests/baselines/"), "wrong_directory", "Baselines must live under tests/baselines/")
            return issues

        return issues

    def _issue(self, code: str, message: str, target: Path, kind: str, scope: str) -> LayoutIssue:
        return LayoutIssue(
            code=code,
            message=message,
            path=str(target),
            kind=kind,
            scope=scope,
        )

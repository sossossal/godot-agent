"""
Genre template registry.

This registry turns hard-coded genre assumptions into structured manifests
that can be shared across router, CLI, Portal, and future AI providers.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional


TEMPLATE_REGISTRY_SCHEMA_VERSION = "1.0"
TEMPLATE_MARKETPLACE_SCHEMA_VERSION = "1.0"
GAMEPLAY_TEMPLATE_SCHEMA_VERSION = "1.0"
DEFAULT_GENRE_TEMPLATE_ID = "platformer"
_REQUIRED_TEMPLATE_FIELDS = {
    "template_id",
    "display_name",
    "game_genre",
    "version",
    "recommended_directories",
    "starter_data_tables",
    "starter_gameplay_systems",
    "performance_budget",
}
_REQUIRED_PERFORMANCE_BUDGETS = {
    "max_scene_load_ms",
    "min_fps",
    "max_memory_peak_mb",
}
_REQUIRED_GAMEPLAY_SYSTEM_FIELDS = {
    "system_id",
    "display_name",
    "category",
    "summary",
    "recommended_skills",
    "acceptance_checks",
}


class GenreTemplateRegistry:
    def __init__(self, project_path: Optional[str] = None):
        self.project_path = Path(project_path).resolve() if project_path else None
        self.builtin_dir = (Path(__file__).parent.parent / "templates" / "genres").resolve()

    def list_genre_templates(self) -> List[Dict[str, Any]]:
        templates = self._load_templates()
        return [templates[key] for key in sorted(templates)]

    def build_marketplace_manifest(self) -> Dict[str, Any]:
        items: List[Dict[str, Any]] = []
        registry_issues: List[Dict[str, Any]] = []
        registry_warnings: List[Dict[str, Any]] = []

        for file_path in self._iter_manifest_paths():
            raw, read_error = self._read_manifest_with_error(file_path)
            if read_error:
                issue = {
                    "template_id": file_path.stem,
                    "path": str(file_path),
                    "code": "invalid_json",
                    "message": read_error,
                }
                registry_issues.append(issue)
                items.append({
                    "schema_version": TEMPLATE_MARKETPLACE_SCHEMA_VERSION,
                    "template_id": file_path.stem,
                    "display_name": file_path.stem,
                    "version": "",
                    "source_scope": self._source_scope(file_path),
                    "source_path": str(file_path),
                    "install_state": "invalid",
                    "validation": {
                        "passed": False,
                        "issues": [issue],
                        "warnings": [],
                        "issue_count": 1,
                        "warning_count": 0,
                    },
                })
                continue

            validation = self.validate_template_manifest(raw or {}, file_path)
            normalized = self._normalize_manifest(raw or {}, file_path)
            marketplace_item = {
                **self.build_template_snapshot(normalized),
                "schema_version": TEMPLATE_MARKETPLACE_SCHEMA_VERSION,
                "source_scope": normalized["source_scope"],
                "source_path": normalized["source_path"],
                "install_state": "installed",
                "validation": validation,
            }
            items.append(marketplace_item)
            registry_issues.extend(validation["issues"])
            registry_warnings.extend(validation["warnings"])

        return {
            "schema_version": TEMPLATE_MARKETPLACE_SCHEMA_VERSION,
            "registry_schema_version": TEMPLATE_REGISTRY_SCHEMA_VERSION,
            "default_template_id": DEFAULT_GENRE_TEMPLATE_ID,
            "count": len(items),
            "items": sorted(items, key=lambda item: str(item.get("template_id") or "")),
            "validation": {
                "passed": not registry_issues,
                "issue_count": len(registry_issues),
                "warning_count": len(registry_warnings),
                "issues": registry_issues,
                "warnings": registry_warnings,
            },
        }

    def validate_template_manifest(self, raw: Dict[str, Any], file_path: Optional[Path] = None) -> Dict[str, Any]:
        path_text = str(file_path) if file_path else ""
        template_id = str(raw.get("template_id") or (file_path.stem if file_path else "")).strip().lower()
        issues: List[Dict[str, Any]] = []
        warnings: List[Dict[str, Any]] = []

        missing = sorted(field for field in _REQUIRED_TEMPLATE_FIELDS if field not in raw)
        for field in missing:
            issues.append({
                "template_id": template_id,
                "path": path_text,
                "code": "missing_required_field",
                "message": f"Template manifest is missing required field: {field}",
            })

        if template_id and not template_id.replace("_", "").replace("-", "").isalnum():
            issues.append({
                "template_id": template_id,
                "path": path_text,
                "code": "invalid_template_id",
                "message": "template_id must use letters, numbers, dash or underscore",
            })

        directories = raw.get("recommended_directories")
        if not isinstance(directories, list) or not directories:
            issues.append({
                "template_id": template_id,
                "path": path_text,
                "code": "missing_recommended_directories",
                "message": "recommended_directories must be a non-empty list",
            })
        else:
            for directory in directories:
                normalized = str(directory or "").strip().replace("\\", "/")
                parts = [part for part in normalized.split("/") if part]
                if not normalized:
                    issues.append({
                        "template_id": template_id,
                        "path": path_text,
                        "code": "empty_directory",
                        "message": "recommended_directories contains an empty entry",
                    })
                if normalized.startswith("/") or ":" in normalized:
                    issues.append({
                        "template_id": template_id,
                        "path": path_text,
                        "code": "absolute_directory",
                        "message": f"Template directory must be project-relative: {normalized}",
                    })
                if ".." in parts:
                    issues.append({
                        "template_id": template_id,
                        "path": path_text,
                        "code": "directory_escape",
                        "message": f"Template directory may not escape the project root: {normalized}",
                    })

        starter_tables = raw.get("starter_data_tables")
        if not isinstance(starter_tables, list):
            issues.append({
                "template_id": template_id,
                "path": path_text,
                "code": "invalid_starter_data_tables",
                "message": "starter_data_tables must be a list",
            })

        gameplay_systems = raw.get("starter_gameplay_systems")
        if not isinstance(gameplay_systems, list) or not gameplay_systems:
            issues.append({
                "template_id": template_id,
                "path": path_text,
                "code": "invalid_starter_gameplay_systems",
                "message": "starter_gameplay_systems must be a non-empty list",
            })
        else:
            for index, raw_system in enumerate(gameplay_systems):
                if not isinstance(raw_system, dict):
                    issues.append({
                        "template_id": template_id,
                        "path": path_text,
                        "code": "invalid_gameplay_system_entry",
                        "message": f"starter_gameplay_systems[{index}] must be an object",
                    })
                    continue

                system_id = str(raw_system.get("system_id") or "").strip().lower()
                missing_fields = sorted(field for field in _REQUIRED_GAMEPLAY_SYSTEM_FIELDS if field not in raw_system)
                for field in missing_fields:
                    issues.append({
                        "template_id": template_id,
                        "path": path_text,
                        "code": "missing_gameplay_system_field",
                        "message": f"starter_gameplay_systems[{index}] is missing field: {field}",
                    })

                if system_id and not system_id.replace("_", "").replace("-", "").isalnum():
                    issues.append({
                        "template_id": template_id,
                        "path": path_text,
                        "code": "invalid_gameplay_system_id",
                        "message": f"starter_gameplay_systems[{index}].system_id must use letters, numbers, dash or underscore",
                    })

                recommended_skills = raw_system.get("recommended_skills")
                if not isinstance(recommended_skills, list) or not recommended_skills:
                    issues.append({
                        "template_id": template_id,
                        "path": path_text,
                        "code": "invalid_recommended_skills",
                        "message": f"starter_gameplay_systems[{index}].recommended_skills must be a non-empty list",
                    })

                acceptance_checks = raw_system.get("acceptance_checks")
                if not isinstance(acceptance_checks, list) or not acceptance_checks:
                    warnings.append({
                        "template_id": template_id,
                        "path": path_text,
                        "code": "missing_gameplay_acceptance_checks",
                        "message": f"starter_gameplay_systems[{index}] should define acceptance_checks",
                    })

        budgets = raw.get("performance_budget")
        if not isinstance(budgets, dict) or not budgets:
            issues.append({
                "template_id": template_id,
                "path": path_text,
                "code": "missing_performance_budget",
                "message": "performance_budget must be a non-empty object",
            })
        else:
            for key in sorted(_REQUIRED_PERFORMANCE_BUDGETS - set(budgets)):
                warnings.append({
                    "template_id": template_id,
                    "path": path_text,
                    "code": "missing_budget_hint",
                    "message": f"performance_budget should include {key}",
                })

        return {
            "passed": not issues,
            "issues": issues,
            "warnings": warnings,
            "issue_count": len(issues),
            "warning_count": len(warnings),
        }

    def resolve_genre_template(self, query: Optional[str]) -> Optional[Dict[str, Any]]:
        normalized_query = str(query or "").strip().lower()
        templates = self._load_templates()
        if not normalized_query:
            return templates.get(DEFAULT_GENRE_TEMPLATE_ID)

        if normalized_query in templates:
            return templates[normalized_query]

        for template in templates.values():
            aliases = [str(alias).strip().lower() for alias in template.get("aliases", [])]
            if normalized_query == str(template.get("game_genre") or "").strip().lower():
                return template
            if normalized_query in aliases:
                return template
        return None

    def build_template_snapshot(self, template: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "schema_version": TEMPLATE_REGISTRY_SCHEMA_VERSION,
            "template_id": template["template_id"],
            "display_name": template["display_name"],
            "game_genre": template["game_genre"],
            "version": template["version"],
            "description": template["description"],
            "tags": list(template.get("tags") or []),
            "starter_data_tables": list(template.get("starter_data_tables") or []),
            "starter_gameplay_systems": list(template.get("starter_gameplay_systems") or []),
            "recommended_directories": list(template.get("recommended_directories") or []),
            "performance_budget": dict(template.get("performance_budget") or {}),
            "source_scope": str(template.get("source_scope") or ""),
            "source_path": str(template.get("source_path") or ""),
        }

    def build_gameplay_template_snapshot(
        self,
        query: Optional[str],
        include_system_ids: Optional[List[str]] = None,
    ) -> Optional[Dict[str, Any]]:
        template = self.resolve_genre_template(query)
        if not template:
            return None

        include_filter = {
            str(item).strip().lower()
            for item in list(include_system_ids or [])
            if str(item).strip()
        }
        systems: List[Dict[str, Any]] = []
        for raw_system in list(template.get("starter_gameplay_systems") or []):
            system = dict(raw_system or {})
            system_id = str(system.get("system_id") or "").strip().lower()
            if include_filter and system_id not in include_filter:
                continue
            systems.append(system)

        acceptance_checks: List[str] = []
        for system in systems:
            for check in list(system.get("acceptance_checks") or []):
                normalized = str(check).strip()
                if normalized and normalized not in acceptance_checks:
                    acceptance_checks.append(normalized)

        return {
            "schema_version": GAMEPLAY_TEMPLATE_SCHEMA_VERSION,
            "template_id": template["template_id"],
            "display_name": template["display_name"],
            "game_genre": template["game_genre"],
            "description": template["description"],
            "starter_gameplay_systems": systems,
            "system_count": len(systems),
            "acceptance_checks": acceptance_checks,
            "acceptance_check_count": len(acceptance_checks),
            "starter_data_tables": list(template.get("starter_data_tables") or []),
            "recommended_directories": list(template.get("recommended_directories") or []),
            "performance_budget": dict(template.get("performance_budget") or {}),
        }

    def ensure_project_directories(self, template: Dict[str, Any], project_root: str | Path) -> List[str]:
        root = Path(project_root).resolve()
        created: List[str] = []
        for relative in list(template.get("recommended_directories") or []):
            target = (root / str(relative)).resolve()
            target.mkdir(parents=True, exist_ok=True)
            created.append(target.relative_to(root).as_posix())
        return created

    def _load_templates(self) -> Dict[str, Dict[str, Any]]:
        templates: Dict[str, Dict[str, Any]] = {}
        for file_path in self._iter_manifest_paths():
            raw = self._read_manifest(file_path)
            if not raw:
                continue
            normalized = self._normalize_manifest(raw, file_path)
            templates[normalized["template_id"]] = normalized
        return templates

    def _iter_manifest_paths(self) -> List[Path]:
        paths: List[Path] = []
        if self.builtin_dir.exists():
            paths.extend(sorted(path for path in self.builtin_dir.glob("*.json") if path.is_file()))

        if self.project_path:
            override_dir = (self.project_path / "agent_templates" / "genres").resolve()
            if override_dir.exists():
                for path in sorted(candidate for candidate in override_dir.glob("*.json") if candidate.is_file()):
                    paths.append(path)
        return paths

    def _read_manifest(self, file_path: Path) -> Optional[Dict[str, Any]]:
        raw, _ = self._read_manifest_with_error(file_path)
        return raw

    def _read_manifest_with_error(self, file_path: Path) -> tuple[Optional[Dict[str, Any]], str]:
        try:
            payload = json.loads(file_path.read_text(encoding="utf-8"))
        except Exception as exc:
            return None, str(exc)
        if not isinstance(payload, dict):
            return None, "Template manifest root must be a JSON object"
        return payload, ""

    def _source_scope(self, file_path: Path) -> str:
        if self.project_path:
            override_dir = (self.project_path / "agent_templates" / "genres").resolve()
            try:
                file_path.resolve().relative_to(override_dir)
                return "project"
            except ValueError:
                pass
        return "builtin"

    def _normalize_manifest(self, raw: Dict[str, Any], file_path: Path) -> Dict[str, Any]:
        template_id = str(raw.get("template_id") or file_path.stem).strip().lower()
        display_name = str(raw.get("display_name") or template_id).strip() or template_id
        game_genre = str(raw.get("game_genre") or display_name).strip() or display_name

        coding_style = dict(raw.get("coding_style") or {})
        performance_budget = dict(raw.get("performance_budget") or {})
        default_ui_style = dict(raw.get("default_ui_style") or {})
        starter_gameplay_systems: List[Dict[str, Any]] = []
        for raw_system in list(raw.get("starter_gameplay_systems") or []):
            if not isinstance(raw_system, dict):
                continue
            system_id = str(raw_system.get("system_id") or "").strip().lower().replace(" ", "_")
            if not system_id:
                continue
            starter_gameplay_systems.append({
                "system_id": system_id,
                "display_name": str(raw_system.get("display_name") or system_id).strip() or system_id,
                "category": str(raw_system.get("category") or "gameplay").strip().lower() or "gameplay",
                "summary": str(raw_system.get("summary") or "").strip(),
                "recommended_skills": [
                    str(item).strip()
                    for item in list(raw_system.get("recommended_skills") or [])
                    if str(item).strip()
                ],
                "suggested_data_tables": [
                    str(item).strip().lower()
                    for item in list(raw_system.get("suggested_data_tables") or [])
                    if str(item).strip()
                ],
                "acceptance_checks": [
                    str(item).strip()
                    for item in list(raw_system.get("acceptance_checks") or [])
                    if str(item).strip()
                ],
                "starter_feature_name": str(raw_system.get("starter_feature_name") or system_id).strip() or system_id,
                "dependencies": [
                    str(item).strip()
                    for item in list(raw_system.get("dependencies") or [])
                    if str(item).strip()
                ],
            })

        return {
            "schema_version": TEMPLATE_REGISTRY_SCHEMA_VERSION,
            "template_id": template_id,
            "display_name": display_name,
            "game_genre": game_genre,
            "version": str(raw.get("version") or "1.0.0").strip() or "1.0.0",
            "description": str(raw.get("description") or "").strip(),
            "aliases": [str(alias).strip() for alias in list(raw.get("aliases") or []) if str(alias).strip()],
            "tags": [str(tag).strip() for tag in list(raw.get("tags") or []) if str(tag).strip()],
            "coding_style": {
                "naming_convention": str(coding_style.get("naming_convention") or "snake_case").strip() or "snake_case",
                "signal_pattern": str(coding_style.get("signal_pattern") or "SignalBus").strip() or "SignalBus",
            },
            "default_ui_style": default_ui_style,
            "recommended_directories": [
                str(item).strip().replace("\\", "/")
                for item in list(raw.get("recommended_directories") or [])
                if str(item).strip()
            ],
            "starter_data_tables": [
                str(item).strip().lower()
                for item in list(raw.get("starter_data_tables") or [])
                if str(item).strip()
            ],
            "starter_gameplay_systems": starter_gameplay_systems,
            "performance_budget": performance_budget,
            "source_scope": self._source_scope(file_path),
            "source_path": str(file_path),
            "validation": self.validate_template_manifest(raw, file_path),
        }

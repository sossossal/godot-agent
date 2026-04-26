"""
Project migration and compatibility status.

The runner is intentionally conservative: it validates existing contract
artifacts and only creates missing directories when apply_pending() is called.
It does not rewrite user data tables, telemetry catalogs, or baselines.
"""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from agent_system.skills.resource.data_table_skill import TABLE_SCHEMAS
from agent_system.tools.performance_analysis import DEFAULT_PERFORMANCE_BASELINE_DIR
from agent_system.tools.telemetry_analysis import DEFAULT_TELEMETRY_CATALOG_PATH, DEFAULT_TELEMETRY_SESSIONS_DIR
from agent_system.tools.template_registry import GenreTemplateRegistry


MIGRATION_REGISTRY_SCHEMA_VERSION = "1.0"


class MigrationRunner:
    def __init__(self, project_root: str | Path, runtime_root: Optional[str | Path] = None):
        self.project_root = Path(project_root).resolve()
        self.runtime_root = Path(runtime_root or Path.cwd()).resolve()

    def build_migration_status(self) -> Dict[str, Any]:
        migrations = [
            self._check_template_manifest_migration(),
            self._check_runtime_performance_baseline_migration(),
            self._check_telemetry_catalog_migration(),
            self._check_data_table_schema_migration(),
        ]
        failed = [item for item in migrations if item["status"] == "failed"]
        pending = [item for item in migrations if item["status"] == "pending"]
        applied = [item for item in migrations if item["status"] == "applied"]
        warnings = [
            warning
            for item in migrations
            for warning in list(item.get("warnings") or [])
        ]
        issues = [
            issue
            for item in migrations
            for issue in list(item.get("issues") or [])
        ]
        return {
            "schema_version": MIGRATION_REGISTRY_SCHEMA_VERSION,
            "project_root": str(self.project_root),
            "runtime_root": str(self.runtime_root),
            "passed": not failed,
            "migration_count": len(migrations),
            "applied_count": len(applied),
            "pending_count": len(pending),
            "failed_count": len(failed),
            "warning_count": len(warnings),
            "issue_count": len(issues),
            "migrations": migrations,
            "issues": issues,
            "warnings": warnings,
        }

    def apply_pending(self) -> Dict[str, Any]:
        before = self.build_migration_status()
        created_directories: List[str] = []
        skipped: List[str] = []

        for migration in before["migrations"]:
            if migration["status"] != "pending":
                continue
            for raw_path in migration.get("create_directories") or []:
                target = Path(raw_path).resolve()
                target.mkdir(parents=True, exist_ok=True)
                created_directories.append(str(target))
            if not migration.get("create_directories"):
                skipped.append(migration["migration_id"])

        after = self.build_migration_status()
        return {
            "schema_version": MIGRATION_REGISTRY_SCHEMA_VERSION,
            "project_root": str(self.project_root),
            "runtime_root": str(self.runtime_root),
            "created_directories": created_directories,
            "created_directory_count": len(created_directories),
            "skipped_migrations": skipped,
            "before": before,
            "after": after,
            "passed": after["passed"],
        }

    def _check_template_manifest_migration(self) -> Dict[str, Any]:
        registry = GenreTemplateRegistry(project_path=str(self.project_root))
        marketplace = registry.build_marketplace_manifest()
        issues = list(marketplace.get("validation", {}).get("issues") or [])
        warnings = list(marketplace.get("validation", {}).get("warnings") or [])
        override_dir = (self.project_root / "agent_templates" / "genres").resolve()
        create_directories: List[str] = []
        status = "applied"
        if issues:
            status = "failed"
        elif not override_dir.exists():
            status = "pending"
            create_directories.append(str(override_dir))
            warnings.append({
                "code": "project_template_override_dir_missing",
                "path": str(override_dir),
                "message": "Project template override directory has not been initialized",
            })

        return self._migration(
            migration_id="template_manifest_1_0",
            description="Validate built-in and project genre template manifests",
            status=status,
            issues=issues,
            warnings=warnings,
            affected_paths=[item.get("source_path", "") for item in marketplace.get("items") or []],
            create_directories=create_directories,
            details={
                "template_count": marketplace.get("count", 0),
                "default_template_id": marketplace.get("default_template_id"),
            },
        )

    def _check_runtime_performance_baseline_migration(self) -> Dict[str, Any]:
        baseline_dir = (self.runtime_root / DEFAULT_PERFORMANCE_BASELINE_DIR).resolve()
        issues: List[Dict[str, Any]] = []
        warnings: List[Dict[str, Any]] = []
        affected_paths: List[str] = []
        create_directories: List[str] = []

        if not baseline_dir.exists():
            return self._migration(
                migration_id="runtime_performance_baselines_1_0",
                description="Ensure performance baseline directory and JSON baseline shape",
                status="pending",
                warnings=[{
                    "code": "performance_baseline_dir_missing",
                    "path": str(baseline_dir),
                    "message": "Performance baseline directory has not been initialized",
                }],
                affected_paths=[str(baseline_dir)],
                create_directories=[str(baseline_dir)],
                details={"baseline_count": 0},
            )

        for path in sorted(candidate for candidate in baseline_dir.glob("*.json") if candidate.is_file()):
            affected_paths.append(str(path))
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except Exception as exc:
                issues.append(self._issue("invalid_performance_baseline_json", path, str(exc)))
                continue
            if not isinstance(payload, dict):
                issues.append(self._issue("invalid_performance_baseline_shape", path, "Baseline root must be an object"))
                continue
            if not isinstance(payload.get("metrics"), dict) or not payload.get("metrics"):
                issues.append(self._issue("missing_performance_metrics", path, "Baseline must contain a non-empty metrics object"))
            if str(payload.get("schema_version") or "").strip() != "1.0":
                warnings.append(self._issue("performance_schema_version_missing", path, "Baseline should declare schema_version=1.0"))

        return self._migration(
            migration_id="runtime_performance_baselines_1_0",
            description="Ensure performance baseline directory and JSON baseline shape",
            status="failed" if issues else "applied",
            issues=issues,
            warnings=warnings,
            affected_paths=affected_paths or [str(baseline_dir)],
            create_directories=create_directories,
            details={"baseline_count": len(affected_paths)},
        )

    def _check_telemetry_catalog_migration(self) -> Dict[str, Any]:
        catalog_path = (self.project_root / DEFAULT_TELEMETRY_CATALOG_PATH).resolve()
        sessions_dir = (self.project_root / DEFAULT_TELEMETRY_SESSIONS_DIR).resolve()
        issues: List[Dict[str, Any]] = []
        warnings: List[Dict[str, Any]] = []
        affected_paths: List[str] = []
        create_directories: List[str] = []

        if not catalog_path.exists() and not sessions_dir.exists():
            create_directories.extend([str(catalog_path.parent), str(sessions_dir)])
            return self._migration(
                migration_id="telemetry_catalog_1_0",
                description="Validate telemetry catalog and prepare managed session directory",
                status="pending",
                warnings=[{
                    "code": "telemetry_dirs_missing",
                    "path": str(self.project_root / "telemetry"),
                    "message": "Telemetry directories have not been initialized",
                }],
                affected_paths=[str(catalog_path), str(sessions_dir)],
                create_directories=create_directories,
                details={"catalog_exists": False, "session_file_count": 0},
            )

        if catalog_path.exists():
            affected_paths.append(str(catalog_path))
            try:
                payload = json.loads(catalog_path.read_text(encoding="utf-8"))
            except Exception as exc:
                issues.append(self._issue("invalid_telemetry_catalog_json", catalog_path, str(exc)))
            else:
                entries = payload.get("events") if isinstance(payload, dict) else payload
                if not isinstance(entries, list):
                    issues.append(self._issue("invalid_telemetry_catalog_shape", catalog_path, "Catalog must be a list or an object with events[]"))

        session_files = []
        if sessions_dir.exists():
            session_files = sorted(path for path in sessions_dir.glob("*.json*") if path.is_file())
            for path in session_files:
                affected_paths.append(str(path))
                try:
                    if path.suffix.lower() == ".jsonl":
                        for index, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
                            if line.strip():
                                json.loads(line)
                    else:
                        json.loads(path.read_text(encoding="utf-8"))
                except Exception as exc:
                    issues.append(self._issue("invalid_telemetry_session_json", path, f"{exc}"))

        return self._migration(
            migration_id="telemetry_catalog_1_0",
            description="Validate telemetry catalog and prepare managed session directory",
            status="failed" if issues else "applied",
            issues=issues,
            warnings=warnings,
            affected_paths=affected_paths or [str(catalog_path), str(sessions_dir)],
            create_directories=create_directories,
            details={
                "catalog_exists": catalog_path.exists(),
                "session_file_count": len(session_files),
            },
        )

    def _check_data_table_schema_migration(self) -> Dict[str, Any]:
        data_table_dir = (self.project_root / "data_tables").resolve()
        issues: List[Dict[str, Any]] = []
        warnings: List[Dict[str, Any]] = []
        affected_paths: List[str] = []

        if not data_table_dir.exists():
            return self._migration(
                migration_id="data_table_schema_1_0",
                description="Validate managed data table files against built-in schemas",
                status="pending",
                warnings=[{
                    "code": "data_table_dir_missing",
                    "path": str(data_table_dir),
                    "message": "Managed data table directory has not been initialized",
                }],
                affected_paths=[str(data_table_dir)],
                create_directories=[str(data_table_dir)],
                details={"table_count": 0},
            )

        for table_type, schema in TABLE_SCHEMAS.items():
            path = (self.project_root / str(schema["default_path"])).resolve()
            if not path.exists():
                continue
            affected_paths.append(str(path))
            issues.extend(self._validate_table_file(table_type, schema, path))

        if not affected_paths:
            warnings.append({
                "code": "no_managed_data_tables",
                "path": str(data_table_dir),
                "message": "data_tables/ exists but no built-in schema table files are present yet",
            })

        return self._migration(
            migration_id="data_table_schema_1_0",
            description="Validate managed data table files against built-in schemas",
            status="failed" if issues else "applied",
            issues=issues,
            warnings=warnings,
            affected_paths=affected_paths or [str(data_table_dir)],
            details={"table_count": len(affected_paths)},
        )

    def _validate_table_file(self, table_type: str, schema: Dict[str, Any], path: Path) -> List[Dict[str, Any]]:
        issues: List[Dict[str, Any]] = []
        try:
            if path.suffix.lower() == ".json":
                payload = json.loads(path.read_text(encoding="utf-8"))
                rows = payload.get("rows") if isinstance(payload, dict) else payload
                if not isinstance(rows, list):
                    return [self._issue("invalid_data_table_json_shape", path, f"{table_type} JSON table must be a list or contain rows[]")]
                headers = set(rows[0].keys()) if rows and isinstance(rows[0], dict) else set()
            else:
                with path.open("r", encoding="utf-8", newline="") as handle:
                    sample = handle.read(2048)
                    handle.seek(0)
                    dialect = csv.Sniffer().sniff(sample) if sample.strip() else csv.excel
                    reader = csv.DictReader(handle, dialect=dialect)
                    headers = set(reader.fieldnames or [])
        except Exception as exc:
            return [self._issue("invalid_data_table_file", path, str(exc))]

        required_columns = {column["name"] for column in schema.get("columns", []) if column.get("required")}
        missing_columns = sorted(required_columns - headers)
        for column in missing_columns:
            issues.append(self._issue("missing_required_data_table_column", path, f"{table_type} table is missing required column: {column}"))
        return issues

    def _migration(
        self,
        *,
        migration_id: str,
        description: str,
        status: str,
        issues: Optional[List[Dict[str, Any]]] = None,
        warnings: Optional[List[Dict[str, Any]]] = None,
        affected_paths: Optional[List[str]] = None,
        create_directories: Optional[List[str]] = None,
        details: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        return {
            "schema_version": MIGRATION_REGISTRY_SCHEMA_VERSION,
            "migration_id": migration_id,
            "target_version": "1.0",
            "description": description,
            "status": status,
            "applied": status == "applied",
            "can_apply": bool(create_directories) and status == "pending",
            "issues": list(issues or []),
            "warnings": list(warnings or []),
            "affected_paths": [path for path in list(affected_paths or []) if path],
            "create_directories": list(create_directories or []),
            "details": dict(details or {}),
        }

    def _issue(self, code: str, path: Path, message: str) -> Dict[str, Any]:
        return {
            "code": code,
            "path": str(path),
            "message": message,
        }

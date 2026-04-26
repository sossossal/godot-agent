"""Migration and compatibility helpers for Godot Agent project contracts."""

from .runner import MIGRATION_REGISTRY_SCHEMA_VERSION, MigrationRunner

__all__ = [
    "MIGRATION_REGISTRY_SCHEMA_VERSION",
    "MigrationRunner",
]

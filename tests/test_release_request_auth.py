import hashlib
import json
import shutil
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path


project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from agent_system.tools.release_request_auth import (
    authorize_release_request,
    export_release_request_auth_identity_handoff,
    build_release_request_auth_identity_audit,
    build_release_request_auth_rotation_audit,
    build_release_request_auth_posture,
    build_release_request_token_spec,
    export_release_request_auth_identity_audit_report,
    export_release_request_auth_rotation_audit_report,
    export_release_request_auth_posture_report,
)


class ReleaseRequestAuthTestCase(unittest.TestCase):
    def setUp(self):
        self.project_dir = project_root / "tests" / ".tmp_release_request_auth_project"
        self.runtime_dir = project_root / "tests" / ".tmp_release_request_auth_runtime"
        shutil.rmtree(self.project_dir, ignore_errors=True)
        shutil.rmtree(self.runtime_dir, ignore_errors=True)
        (self.project_dir / "deployment").mkdir(parents=True, exist_ok=True)
        self.runtime_dir.mkdir(parents=True, exist_ok=True)

    def tearDown(self):
        shutil.rmtree(self.project_dir, ignore_errors=True)
        shutil.rmtree(self.runtime_dir, ignore_errors=True)

    def _write_identity_registry(
        self,
        *,
        issuer_id: str = "ops_a",
        subject_actor_ids: list[str] | None = None,
        channels: list[str] | None = None,
        target_environments: list[str] | None = None,
        status: str = "active",
        session_required: bool = True,
        max_session_age_hours: int = 0,
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
                            "status": status,
                            "channels": channels or ["staging", "release"],
                            "target_environments": target_environments or ["staging", "production"],
                            "subject_actor_ids": subject_actor_ids or ["release_manager", "producer_a"],
                            "session_required": session_required,
                            "max_session_age_hours": max_session_age_hours,
                        }
                    ],
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

    def _write_identity_boundary_manifest(
        self,
        *,
        channel: str,
        environment: str,
        provider_mode: str = "project_manifest",
        provider_id: str = "release_request_auth_manifest",
        session_required: bool = True,
        max_session_age_hours: int = 24,
        secret_backend: str = "deployment_manifest",
        handoff_required: bool = False,
        handoff_mode: str = "manual_operator",
        handoff_target_id: str = "identity_ops_intake",
        handoff_owner: str = "ops_release",
    ) -> None:
        (self.project_dir / "deployment" / "release_identity_boundary.json").write_text(
            json.dumps(
                {
                    "schema_version": "1.0",
                    "profiles": [
                        {
                            "profile_id": f"{channel}_identity",
                            "target_channels": [channel],
                            "target_environments": [environment],
                            "provider_mode": provider_mode,
                            "provider_id": provider_id,
                            "session_policy": {
                                "required": session_required,
                                "max_session_age_hours": max_session_age_hours,
                                "backend": "identity_registry",
                            },
                            "secret_rotation": {
                                "required": True,
                                "backend": secret_backend,
                                "owner": "ops_release",
                                "rotation_window_days": 30,
                            },
                            "issuer_policy": "identity_registry_scoped",
                            "external_handoff": {
                                "required": handoff_required,
                                "mode": handoff_mode,
                                "target_id": handoff_target_id,
                                "owner": handoff_owner,
                            },
                        }
                    ],
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

    def test_build_release_request_token_spec_hashes_plaintext_token(self):
        spec = build_release_request_token_spec(
            token_id="staging_release_manager",
            token_value="manifest-release-secret",
            actions=["release_execution"],
            channels=["staging"],
            target_environments=["staging"],
            actor_ids=["release_manager"],
            expires_at="2026-05-01T00:00:00Z",
            session_id="session-staging-001",
            issued_by="ops_a",
            issued_at="2026-04-15T00:00:00Z",
        )

        self.assertEqual(spec["token_id"], "staging_release_manager")
        self.assertEqual(
            spec["token_sha256"],
            hashlib.sha256("manifest-release-secret".encode("utf-8")).hexdigest(),
        )
        self.assertEqual(spec["actions"], ["release_execution"])
        self.assertEqual(spec["channels"], ["staging"])
        self.assertEqual(spec["actor_ids"], ["release_manager"])
        self.assertEqual(spec["session_id"], "session-staging-001")
        self.assertEqual(spec["issued_by"], "ops_a")
        self.assertEqual(spec["issued_at"], "2026-04-15T00:00:00Z")
        self.assertFalse(spec["revoked"])

    def test_release_request_auth_posture_warns_when_only_local_bypass_is_available(self):
        manifest_path = self.project_dir / "deployment" / "release_request_auth.json"
        manifest_path.write_text(
            json.dumps(
                {
                    "schema_version": "1.0",
                    "allow_local_without_token": True,
                    "tokens": [],
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

        posture = build_release_request_auth_posture(
            self.project_dir,
            runtime_root=self.runtime_dir,
            action="release_execution",
            target_channel="staging",
            target_environment="staging",
        )

        self.assertEqual(posture["status"], "warning")
        self.assertTrue(posture["allow_local_without_token"])
        self.assertEqual(posture["matching_token_count"], 0)
        self.assertIn("local bypass", posture["summary"])

    def test_release_request_auth_posture_passes_with_actor_bound_manifest_token(self):
        spec = build_release_request_token_spec(
            token_id="staging_release_manager",
            token_value="manifest-release-secret",
            actions=["release_execution"],
            channels=["staging"],
            target_environments=["staging"],
            actor_ids=["release_manager"],
            expires_at="2099-01-01T00:00:00Z",
        )
        manifest_path = self.project_dir / "deployment" / "release_request_auth.json"
        manifest_path.write_text(
            json.dumps(
                {
                    "schema_version": "1.0",
                    "allow_local_without_token": False,
                    "tokens": [spec],
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

        posture = build_release_request_auth_posture(
            self.project_dir,
            runtime_root=self.runtime_dir,
            action="release_execution",
            target_channel="staging",
            target_environment="staging",
        )

        self.assertEqual(posture["status"], "passed")
        self.assertEqual(posture["matching_token_count"], 1)
        self.assertEqual(posture["matching_bound_token_count"], 1)
        self.assertEqual(posture["matching_unbound_token_count"], 0)
        self.assertEqual(posture["matching_token_ids"], ["staging_release_manager"])
        self.assertEqual(posture["tokens_without_expiry_count"], 0)
        self.assertEqual(posture["tokens_expiring_soon_count"], 0)
        self.assertEqual(posture["duplicate_token_id_count"], 0)
        self.assertEqual(posture["matching_session_token_count"], 0)

    def test_release_request_auth_posture_warns_for_release_token_missing_session_metadata(self):
        self._write_identity_registry()
        self._write_identity_boundary_manifest(channel="release", environment="production")
        spec = build_release_request_token_spec(
            token_id="release_manager",
            token_value="manifest-release-secret",
            actions=["promotion_record"],
            channels=["release"],
            target_environments=["production"],
            actor_ids=["release_manager"],
            expires_at="2099-01-01T00:00:00Z",
        )
        manifest_path = self.project_dir / "deployment" / "release_request_auth.json"
        manifest_path.write_text(
            json.dumps(
                {
                    "schema_version": "1.0",
                    "allow_local_without_token": False,
                    "tokens": [spec],
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

        posture = build_release_request_auth_posture(
            self.project_dir,
            runtime_root=self.runtime_dir,
            action="promotion_record",
            target_channel="release",
            target_environment="production",
        )

        self.assertEqual(posture["status"], "warning")
        self.assertEqual(posture["matching_token_count"], 1)
        self.assertEqual(posture["matching_session_token_count"], 0)
        self.assertEqual(posture["tokens_without_session_id_count"], 1)
        self.assertEqual(posture["tokens_without_issued_by_count"], 1)
        self.assertEqual(posture["tokens_without_issued_at_count"], 1)
        self.assertTrue(
            "session" in posture["summary"] or "issuer" in posture["summary"]
        )

    def test_release_request_auth_posture_warns_for_release_when_identity_registry_is_missing(self):
        self._write_identity_boundary_manifest(channel="release", environment="production")
        spec = build_release_request_token_spec(
            token_id="release_manager",
            token_value="manifest-release-secret",
            actions=["promotion_record"],
            channels=["release"],
            target_environments=["production"],
            actor_ids=["release_manager"],
            expires_at="2099-01-01T00:00:00Z",
            session_id="release-session-001",
            issued_by="ops_a",
            issued_at="2026-04-15T00:00:00Z",
        )
        manifest_path = self.project_dir / "deployment" / "release_request_auth.json"
        manifest_path.write_text(
            json.dumps(
                {
                    "schema_version": "1.0",
                    "allow_local_without_token": False,
                    "tokens": [spec],
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

        posture = build_release_request_auth_posture(
            self.project_dir,
            runtime_root=self.runtime_dir,
            action="promotion_record",
            target_channel="release",
            target_environment="production",
        )

        self.assertEqual(posture["status"], "warning")
        self.assertFalse(posture["identity_registry_exists"])
        self.assertIn("identity registry", posture["summary"])

    def test_release_request_auth_posture_warns_when_identity_registry_session_is_stale(self):
        self._write_identity_registry(max_session_age_hours=1)
        self._write_identity_boundary_manifest(channel="release", environment="production", max_session_age_hours=1)
        spec = build_release_request_token_spec(
            token_id="release_manager",
            token_value="manifest-release-secret",
            actions=["promotion_record"],
            channels=["release"],
            target_environments=["production"],
            actor_ids=["release_manager"],
            expires_at="2099-01-01T00:00:00Z",
            session_id="release-session-001",
            issued_by="ops_a",
            issued_at="2020-01-01T00:00:00Z",
        )
        manifest_path = self.project_dir / "deployment" / "release_request_auth.json"
        manifest_path.write_text(
            json.dumps(
                {
                    "schema_version": "1.0",
                    "allow_local_without_token": False,
                    "tokens": [spec],
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

        posture = build_release_request_auth_posture(
            self.project_dir,
            runtime_root=self.runtime_dir,
            action="promotion_record",
            target_channel="release",
            target_environment="production",
        )

        self.assertEqual(posture["status"], "warning")
        self.assertTrue(posture["identity_registry_exists"])
        self.assertEqual(posture["matching_registered_issuer_token_count"], 0)
        self.assertEqual(posture["matching_stale_session_token_count"], 1)
        self.assertIn("older than the configured window", posture["summary"])

    def test_release_request_auth_posture_surfaces_identity_boundary_manifest(self):
        self._write_identity_registry()
        self._write_identity_boundary_manifest(channel="release", environment="production")
        spec = build_release_request_token_spec(
            token_id="release_manager",
            token_value="manifest-release-secret",
            actions=["promotion_record"],
            channels=["release"],
            target_environments=["production"],
            actor_ids=["release_manager"],
            expires_at="2099-01-01T00:00:00Z",
            session_id="release-session-001",
            issued_by="ops_a",
            issued_at="2026-04-15T00:00:00Z",
        )
        manifest_path = self.project_dir / "deployment" / "release_request_auth.json"
        manifest_path.write_text(
            json.dumps(
                {
                    "schema_version": "1.0",
                    "allow_local_without_token": False,
                    "tokens": [spec],
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

        posture = build_release_request_auth_posture(
            self.project_dir,
            runtime_root=self.runtime_dir,
            action="promotion_record",
            target_channel="release",
            target_environment="production",
        )

        self.assertEqual(posture["identity_boundary_profile_id"], "release_identity")
        self.assertEqual(posture["identity_boundary_status"], "passed")
        self.assertEqual(posture["identity_provider_mode"], "project_manifest")
        self.assertEqual(posture["identity_session_policy_status"], "passed")
        self.assertEqual(posture["identity_secret_rotation_status"], "passed")

    def test_release_request_auth_posture_warns_when_matching_token_has_no_expiry(self):
        spec = build_release_request_token_spec(
            token_id="staging_release_manager",
            token_value="manifest-release-secret",
            actions=["release_execution"],
            channels=["staging"],
            target_environments=["staging"],
            actor_ids=["release_manager"],
        )
        manifest_path = self.project_dir / "deployment" / "release_request_auth.json"
        manifest_path.write_text(
            json.dumps(
                {
                    "schema_version": "1.0",
                    "allow_local_without_token": False,
                    "tokens": [spec],
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

        posture = build_release_request_auth_posture(
            self.project_dir,
            runtime_root=self.runtime_dir,
            action="release_execution",
            target_channel="staging",
            target_environment="staging",
        )

        self.assertEqual(posture["status"], "warning")
        self.assertEqual(posture["matching_token_count"], 1)
        self.assertEqual(posture["tokens_without_expiry_count"], 1)
        self.assertIn("do not declare expires_at", posture["summary"])

    def test_release_request_auth_posture_warns_when_matching_token_expires_soon_or_token_ids_duplicate(self):
        near_expiry = (
            datetime.now(timezone.utc) + timedelta(days=5)
        ).replace(microsecond=0).isoformat().replace("+00:00", "Z")
        near_expiry_spec = build_release_request_token_spec(
            token_id="staging_release_manager",
            token_value="manifest-release-secret",
            actions=["release_execution"],
            channels=["staging"],
            target_environments=["staging"],
            actor_ids=["release_manager"],
            expires_at=near_expiry,
        )
        duplicate_id_spec = build_release_request_token_spec(
            token_id="staging_release_manager",
            token_value="manifest-release-secret-2",
            actions=["release_execution"],
            channels=["staging"],
            target_environments=["staging"],
            actor_ids=["release_manager"],
            expires_at="2099-01-01T00:00:00Z",
        )
        manifest_path = self.project_dir / "deployment" / "release_request_auth.json"
        manifest_path.write_text(
            json.dumps(
                {
                    "schema_version": "1.0",
                    "allow_local_without_token": False,
                    "tokens": [near_expiry_spec, duplicate_id_spec],
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

        posture = build_release_request_auth_posture(
            self.project_dir,
            runtime_root=self.runtime_dir,
            action="release_execution",
            target_channel="staging",
            target_environment="staging",
        )

        self.assertEqual(posture["status"], "warning")
        self.assertEqual(posture["matching_token_count"], 2)
        self.assertEqual(posture["tokens_expiring_soon_count"], 1)
        self.assertEqual(posture["duplicate_token_id_count"], 1)
        self.assertEqual(posture["duplicate_token_ids"], ["staging_release_manager"])
        self.assertTrue(any("expir" in note for note in posture["notes"]))

    def test_export_release_request_auth_posture_report_writes_redacted_runtime_report(self):
        self._write_identity_registry()
        spec = build_release_request_token_spec(
            token_id="staging_release_manager",
            token_value="manifest-release-secret",
            actions=["release_execution"],
            channels=["staging"],
            target_environments=["staging"],
            actor_ids=["release_manager"],
            expires_at="2099-01-01T00:00:00Z",
            session_id="session-staging-001",
            issued_by="ops_a",
            issued_at="2026-04-15T00:00:00Z",
        )
        manifest_path = self.project_dir / "deployment" / "release_request_auth.json"
        manifest_path.write_text(
            json.dumps(
                {
                    "schema_version": "1.0",
                    "allow_local_without_token": False,
                    "tokens": [spec],
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

        payload = export_release_request_auth_posture_report(
            self.project_dir,
            runtime_root=self.runtime_dir,
            action="release_execution",
            target_channel="staging",
            target_environment="staging",
        )

        report_path = self.runtime_dir / "logs" / "reports" / "release_request_auth_posture_release_execution_staging.json"
        self.assertTrue(report_path.exists())
        self.assertTrue(payload["report_exists"])
        self.assertEqual(payload["manifest_path"], "deployment/release_request_auth.json")
        self.assertEqual(payload["report_path"], "logs/reports/release_request_auth_posture_release_execution_staging.json")
        report_text = report_path.read_text(encoding="utf-8")
        self.assertIn("\"status\": \"passed\"", report_text)
        self.assertNotIn("manifest-release-secret", report_text)
        self.assertNotIn("token_sha256", report_text)

    def test_authorize_release_request_blocks_manifest_token_when_identity_registry_session_is_stale(self):
        self._write_identity_registry(max_session_age_hours=1)
        spec = build_release_request_token_spec(
            token_id="release_manager",
            token_value="manifest-release-secret",
            actions=["release_execution"],
            channels=["release"],
            target_environments=["production"],
            actor_ids=["release_manager"],
            expires_at="2099-01-01T00:00:00Z",
            session_id="release-session-001",
            issued_by="ops_a",
            issued_at="2020-01-01T00:00:00Z",
        )
        manifest_path = self.project_dir / "deployment" / "release_request_auth.json"
        manifest_path.write_text(
            json.dumps(
                {
                    "schema_version": "1.0",
                    "allow_local_without_token": False,
                    "tokens": [spec],
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

        payload = authorize_release_request(
            self.project_dir,
            runtime_root=self.runtime_dir,
            client_host="10.0.0.8",
            authorization_header="Bearer manifest-release-secret",
            actor_id="release_manager",
            action="release_execution",
            target_channel="release",
            target_environment="production",
        )

        self.assertEqual(payload["status"], "blocked")
        self.assertIn("older than 1h", payload["reason"])

    def test_release_request_auth_rotation_audit_blocks_when_write_actions_are_not_fully_covered(self):
        execution_spec = build_release_request_token_spec(
            token_id="staging_release_manager",
            token_value="manifest-release-secret",
            actions=["release_execution"],
            channels=["staging"],
            target_environments=["staging"],
            actor_ids=["release_manager"],
            expires_at="2099-01-01T00:00:00Z",
        )
        manifest_path = self.project_dir / "deployment" / "release_request_auth.json"
        manifest_path.write_text(
            json.dumps(
                {
                    "schema_version": "1.0",
                    "allow_local_without_token": False,
                    "tokens": [execution_spec],
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

        audit = build_release_request_auth_rotation_audit(
            self.project_dir,
            runtime_root=self.runtime_dir,
            target_channel="staging",
            target_environment="staging",
        )

        self.assertEqual(audit["status"], "blocked")
        self.assertEqual(audit["action_count"], 2)
        self.assertEqual(audit["blocked_action_count"], 1)
        self.assertEqual(audit["passed_action_count"], 1)
        self.assertEqual(audit["coverage"][0]["action"], "promotion_record")
        self.assertEqual(audit["coverage"][0]["status"], "blocked")
        self.assertEqual(audit["coverage"][1]["action"], "release_execution")
        self.assertEqual(audit["coverage"][1]["status"], "passed")

    def test_release_request_auth_identity_audit_warns_when_release_issuer_has_no_session_window(self):
        self._write_identity_registry(max_session_age_hours=0)
        promotion_spec = build_release_request_token_spec(
            token_id="release_promotion_manager",
            token_value="manifest-promotion-secret",
            actions=["promotion_record"],
            channels=["release"],
            target_environments=["production"],
            actor_ids=["release_manager"],
            expires_at="2099-01-01T00:00:00Z",
            session_id="session-promotion-001",
            issued_by="ops_a",
            issued_at="2026-04-15T00:00:00Z",
        )
        execution_spec = build_release_request_token_spec(
            token_id="release_execution_manager",
            token_value="manifest-release-secret",
            actions=["release_execution"],
            channels=["release"],
            target_environments=["production"],
            actor_ids=["release_manager"],
            expires_at="2099-01-01T00:00:00Z",
            session_id="session-execution-001",
            issued_by="ops_a",
            issued_at="2026-04-15T00:00:00Z",
        )
        manifest_path = self.project_dir / "deployment" / "release_request_auth.json"
        manifest_path.write_text(
            json.dumps(
                {
                    "schema_version": "1.0",
                    "allow_local_without_token": False,
                    "tokens": [promotion_spec, execution_spec],
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

        audit = build_release_request_auth_identity_audit(
            self.project_dir,
            runtime_root=self.runtime_dir,
            target_channel="release",
            target_environment="production",
        )

        self.assertEqual(audit["status"], "warning")
        self.assertEqual(audit["action_count"], 2)
        self.assertEqual(audit["passed_action_count"], 0)
        self.assertEqual(audit["warning_action_count"], 2)
        self.assertEqual(audit["scoped_issuer_count"], 1)
        self.assertEqual(audit["release_issuers_without_session_window_count"], 1)
        self.assertEqual(audit["matching_registered_issuer_token_count"], 2)
        self.assertIn("warning=2", audit["summary"])

    def test_export_release_request_auth_rotation_audit_report_writes_redacted_summary(self):
        self._write_identity_registry()
        promotion_spec = build_release_request_token_spec(
            token_id="staging_promotion_manager",
            token_value="manifest-promotion-secret",
            actions=["promotion_record"],
            channels=["staging"],
            target_environments=["staging"],
            actor_ids=["release_manager"],
            expires_at="2099-01-01T00:00:00Z",
            session_id="session-promotion-001",
            issued_by="ops_a",
            issued_at="2026-04-15T00:00:00Z",
        )
        execution_spec = build_release_request_token_spec(
            token_id="staging_release_manager",
            token_value="manifest-release-secret",
            actions=["release_execution"],
            channels=["staging"],
            target_environments=["staging"],
            actor_ids=["release_manager"],
            expires_at="2099-01-01T00:00:00Z",
            session_id="session-execution-001",
            issued_by="ops_a",
            issued_at="2026-04-15T00:00:00Z",
        )
        manifest_path = self.project_dir / "deployment" / "release_request_auth.json"
        manifest_path.write_text(
            json.dumps(
                {
                    "schema_version": "1.0",
                    "allow_local_without_token": False,
                    "tokens": [promotion_spec, execution_spec],
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

        payload = export_release_request_auth_rotation_audit_report(
            self.project_dir,
            runtime_root=self.runtime_dir,
            target_channel="staging",
            target_environment="staging",
        )

        report_path = self.runtime_dir / "logs" / "reports" / "release_request_auth_rotation_audit_staging.json"
        self.assertTrue(report_path.exists())
        self.assertTrue(payload["report_exists"])
        self.assertEqual(payload["status"], "passed")
        self.assertEqual(payload["report_path"], "logs/reports/release_request_auth_rotation_audit_staging.json")
        self.assertEqual(payload["passed_action_count"], 2)
        report_text = report_path.read_text(encoding="utf-8")
        self.assertIn("\"status\": \"passed\"", report_text)
        self.assertNotIn("manifest-promotion-secret", report_text)
        self.assertNotIn("token_sha256", report_text)

    def test_export_release_request_auth_identity_audit_report_writes_redacted_summary(self):
        self._write_identity_registry()
        promotion_spec = build_release_request_token_spec(
            token_id="staging_promotion_manager",
            token_value="manifest-promotion-secret",
            actions=["promotion_record"],
            channels=["staging"],
            target_environments=["staging"],
            actor_ids=["release_manager"],
            expires_at="2099-01-01T00:00:00Z",
            session_id="session-promotion-001",
            issued_by="ops_a",
            issued_at="2026-04-15T00:00:00Z",
        )
        execution_spec = build_release_request_token_spec(
            token_id="staging_release_manager",
            token_value="manifest-release-secret",
            actions=["release_execution"],
            channels=["staging"],
            target_environments=["staging"],
            actor_ids=["release_manager"],
            expires_at="2099-01-01T00:00:00Z",
            session_id="session-execution-001",
            issued_by="ops_a",
            issued_at="2026-04-15T00:00:00Z",
        )
        manifest_path = self.project_dir / "deployment" / "release_request_auth.json"
        manifest_path.write_text(
            json.dumps(
                {
                    "schema_version": "1.0",
                    "allow_local_without_token": False,
                    "tokens": [promotion_spec, execution_spec],
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

        payload = export_release_request_auth_identity_audit_report(
            self.project_dir,
            runtime_root=self.runtime_dir,
            target_channel="staging",
            target_environment="staging",
        )

        report_path = self.runtime_dir / "logs" / "reports" / "release_request_auth_identity_audit_staging.json"
        self.assertTrue(report_path.exists())
        self.assertTrue(payload["report_exists"])
        self.assertEqual(payload["status"], "passed")
        self.assertEqual(payload["report_path"], "logs/reports/release_request_auth_identity_audit_staging.json")
        self.assertEqual(payload["passed_action_count"], 2)
        self.assertEqual(payload["scoped_issuer_count"], 1)
        report_text = report_path.read_text(encoding="utf-8")
        self.assertIn("\"status\": \"passed\"", report_text)
        self.assertNotIn("manifest-promotion-secret", report_text)
        self.assertNotIn("token_sha256", report_text)

    def test_export_release_request_auth_identity_handoff_writes_redacted_package(self):
        self._write_identity_registry()
        self._write_identity_boundary_manifest(
            channel="release",
            environment="production",
            handoff_required=True,
            handoff_target_id="release_identity_intake",
        )
        promotion_spec = build_release_request_token_spec(
            token_id="release_promotion_manager",
            token_value="manifest-promotion-secret",
            actions=["promotion_record"],
            channels=["release"],
            target_environments=["production"],
            actor_ids=["release_manager"],
            expires_at="2099-01-01T00:00:00Z",
            session_id="session-promotion-001",
            issued_by="ops_a",
            issued_at="2026-04-15T00:00:00Z",
        )
        execution_spec = build_release_request_token_spec(
            token_id="release_execution_manager",
            token_value="manifest-release-secret",
            actions=["release_execution"],
            channels=["release"],
            target_environments=["production"],
            actor_ids=["release_manager"],
            expires_at="2099-01-01T00:00:00Z",
            session_id="session-execution-001",
            issued_by="ops_a",
            issued_at="2026-04-15T00:00:00Z",
        )
        manifest_path = self.project_dir / "deployment" / "release_request_auth.json"
        manifest_path.write_text(
            json.dumps(
                {
                    "schema_version": "1.0",
                    "allow_local_without_token": False,
                    "tokens": [promotion_spec, execution_spec],
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        release_manifest_path = self.runtime_dir / "api_server" / "static" / "dist" / "release_manifest.json"
        release_manifest_path.parent.mkdir(parents=True, exist_ok=True)
        release_manifest_path.write_text(
            json.dumps(
                {
                    "schema_version": "1.0",
                    "build_id": "web-release-001",
                    "version": "0.1.0-release+1",
                    "channel": "release",
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

        payload = export_release_request_auth_identity_handoff(
            self.project_dir,
            runtime_root=self.runtime_dir,
            target_channel="release",
            target_environment="production",
            release_manifest_path="api_server/static/dist/release_manifest.json",
        )

        handoff_dir = self.runtime_dir / payload["identity_handoff_dir"]
        handoff_manifest_path = self.runtime_dir / payload["identity_handoff_manifest_path"]
        instructions_path = self.runtime_dir / payload["identity_handoff_instructions_path"]
        self.assertEqual(payload["identity_handoff_status"], "passed")
        self.assertTrue(payload["identity_handoff_manifest_exists"])
        self.assertTrue(payload["identity_handoff_instructions_exists"])
        self.assertTrue(payload["identity_handoff_boundary_manifest_exists"])
        self.assertTrue(payload["identity_handoff_registry_manifest_exists"])
        self.assertGreater(payload["identity_handoff_file_count"], 0)
        self.assertTrue(handoff_dir.exists())
        self.assertTrue(handoff_manifest_path.exists())
        self.assertTrue(instructions_path.exists())
        self.assertTrue((handoff_dir / "audits" / "release_request_auth_posture_promotion_record_release.json").exists())
        self.assertTrue((handoff_dir / "audits" / "release_request_auth_posture_release_execution_release.json").exists())
        handoff_manifest = json.loads(handoff_manifest_path.read_text(encoding="utf-8"))
        self.assertEqual(handoff_manifest["identity_boundary_profile_id"], "release_identity")
        self.assertEqual(handoff_manifest["external_handoff_target_id"], "release_identity_intake")
        self.assertEqual(handoff_manifest["release_binding"]["build_id"], "web-release-001")
        instructions_text = instructions_path.read_text(encoding="utf-8")
        self.assertIn("Identity Boundary Handoff", instructions_text)
        self.assertIn("release_identity_intake", instructions_text)


if __name__ == "__main__":
    unittest.main()

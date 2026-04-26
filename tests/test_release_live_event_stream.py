import sys
import unittest
from pathlib import Path


project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from agent_system.tools.release_live_event_stream import (
    build_release_live_event_stream,
    build_release_live_event_stream_report_lines,
)


class ReleaseLiveEventStreamTestCase(unittest.TestCase):
    def test_build_release_live_event_stream_emits_expected_timeline(self):
        payload = build_release_live_event_stream(
            generated_at="2026-04-21T10:00:00Z",
            target_channel="release",
            target_environment="production",
            release_build_id="web-release-001",
            release_version="1.0.0",
            release_channel="release",
            invocation={
                "source": "github_workflow",
                "mode": "strict",
                "providers": ["codex"],
                "approvers": ["qa_lead", "tech_lead"],
            },
            runtime_assembly={
                "route_kind": "github_workflow",
                "route_id": "github_workflow:release:production",
                "invocation_source": "github_workflow",
            },
            ci_gate={
                "status": "blocked",
                "should_block": True,
                "blocking_checks": ["full_live_validation_lane"],
                "warning_checks": [],
                "evaluated_check_count": 4,
            },
            runtime_lanes={
                "full_live_validation": [
                    {
                        "lane_id": "portal_click_smoke",
                        "label": "Portal Click Smoke",
                        "status": "blocked",
                        "summary": "portal click failed",
                        "report_path": "logs/reports/full_live_validation_lanes/portal_click_smoke.json",
                        "flow_statuses": {
                            "release_promotion_history_report_flow": "blocked",
                        },
                    }
                ]
            },
            workflow_steps=[
                {
                    "step_id": "run_full_live_validation",
                    "label": "Run full live validation",
                    "status": "blocked",
                    "outcome": "failure",
                    "always_run": False,
                    "message": "portal click failed",
                }
            ],
            human_signoffs={
                "status": "warning",
                "required_signoffs": ["qa_lead", "tech_lead"],
                "provided_signoffs": ["qa_lead"],
                "missing_signoffs": ["tech_lead"],
            },
            path="release_live_ci_events.json",
            source="live_ci_export",
        )

        self.assertEqual(payload["schema_version"], "1.0")
        self.assertEqual(payload["path"], "release_live_ci_events.json")
        self.assertEqual(payload["status"], "blocked")
        self.assertEqual(payload["route_kind"], "github_workflow")
        self.assertEqual(payload["event_count"], 5)
        self.assertEqual(payload["blocked_event_count"], 4)
        self.assertEqual(payload["warning_event_count"], 0)
        self.assertEqual(payload["latest_event_type"], "run_finished")
        self.assertEqual(payload["latest_event_status"], "blocked")
        self.assertEqual(payload["events"][1]["event_type"], "step_finished")
        self.assertEqual(payload["events"][2]["lane_id"], "portal_click_smoke")

    def test_build_release_live_event_stream_report_lines_summarizes_latest_events(self):
        lines = build_release_live_event_stream_report_lines({
            "status": "warning",
            "summary": "events=3 / blocked=0 / warning=1 / latest=run_finished",
            "path": "release_live_ci_events.json",
            "source": "live_ci_export",
            "generated_at": "2026-04-21T10:00:00Z",
            "route_kind": "local_replay",
            "route_id": "local_replay:staging:staging",
            "invocation_source": "local_replay",
            "release_build_id": "web-staging-001",
            "release_version": "0.1.0-staging+1",
            "release_channel": "staging",
            "target_channel": "staging",
            "target_environment": "staging",
            "event_count": 3,
            "blocked_event_count": 0,
            "warning_event_count": 1,
            "latest_event_type": "run_finished",
            "latest_event_status": "warning",
            "events": [
                {
                    "order": 1,
                    "event_type": "run_started",
                    "status": "passed",
                    "scope": "run",
                    "step_id": "",
                    "lane_id": "",
                    "summary": "route=local_replay",
                },
                {
                    "order": 2,
                    "event_type": "step_finished",
                    "status": "warning",
                    "scope": "workflow_step",
                    "step_id": "run_full_live_validation",
                    "lane_id": "",
                    "summary": "run_full_live_validation [warning]",
                },
            ],
        })

        report_text = "\n".join(lines)
        self.assertIn("Path: release_live_ci_events.json / source=live_ci_export", report_text)
        self.assertIn("Route: local_replay / route_id=local_replay:staging:staging", report_text)
        self.assertIn("latest=run_finished [warning]", report_text)
        self.assertIn("Event (2): step_finished [warning] / scope=workflow_step / step=run_full_live_validation", report_text)


if __name__ == "__main__":
    unittest.main()

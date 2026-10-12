#!/usr/bin/env python3
"""Unit tests for render_assets.py: pure render helpers."""

import sys
import traceback
from pathlib import Path

SKILLS_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SKILLS_DIR / "scripts"))

from render_assets import (  # noqa: E402
    AFE_SUPPORTED_REGIONS,
    KNOWN_ISSUE_GUARDRAILS,
    render_coverage,
    render_known_issues,
    render_lifecycle,
    render_monitoring_searches,
    render_readiness,
    render_source_type,
    render_usage_handoff,
    render_ui_handoff,
)


def _ns(tenant="example-prod", tier="unknown"):
    class A:
        pass
    a = A()
    a.tenant_name = tenant
    a.stack_url = "https://example-prod.scs.splunk.com"
    a.subscription_tier = tier
    return a


def test_render_source_type_contains_name_and_sample_paths():
    out = render_source_type("aws:cloudtrail")
    assert '"name": "aws:cloudtrail"' in out
    assert "samples/aws:cloudtrail.raw" in out
    assert "samples/aws:cloudtrail.csv" in out


def test_render_source_type_sanitizes_unsafe_chars():
    out = render_source_type("My Weird Source!")
    assert "samples/My_Weird_Source_.raw" in out


def test_render_lifecycle_apply_runbook():
    out = render_lifecycle("apply")
    assert "Ingest Processor Apply Runbook" in out
    assert "Preview" in out


def test_render_lifecycle_rollback_runbook():
    out = render_lifecycle("rollback")
    assert "Ingest Processor Rollback Runbook" in out
    assert "known good" in out


def test_render_known_issues_lists_all_guardrails():
    out = render_known_issues()
    for item in KNOWN_ISSUE_GUARDRAILS:
        assert item["code"] in out
        assert item["message"] in out


def test_render_known_issues_lists_afe_regions():
    out = render_known_issues()
    for region in AFE_SUPPORTED_REGIONS:
        assert region in out


def test_render_coverage_json_has_all_features():
    import json
    rows = json.loads(render_coverage())
    assert isinstance(rows, list)
    assert len(rows) > 0
    statuses = {row["coverage_status"] for row in rows}
    assert statuses <= {"rendered", "ui_handoff", "delegated_handoff", "refused_handoff", "lint"}


def test_render_readiness_no_findings():
    out = render_readiness(_ns(), [])
    assert "No blocking findings" in out


def test_render_readiness_with_findings_lists_them():
    findings = [{"severity": "error", "code": "IP-FOO", "message": "boom"}]
    out = render_readiness(_ns(), findings)
    assert "ERROR IP-FOO" in out
    assert "boom" in out


def test_render_ui_handoff_lists_sources_destinations_pipelines():
    out = render_ui_handoff(
        ["aws:cloudtrail"],
        [{"name": "splunk_indexer", "type": "splunk_cloud"}],
        [{"name": "redact_auth", "destination": "splunk_indexer"}],
    )
    assert "aws:cloudtrail" in out
    assert "splunk_indexer" in out
    assert "redact_auth" in out


def test_render_monitoring_searches_includes_sourcetype_and_index_clauses():
    out = render_monitoring_searches(
        ["aws:cloudtrail", "json_app"],
        [{"name": "d1", "index": "main"}, {"name": "d2"}],
    )
    assert 'sourcetype="aws:cloudtrail"' in out
    assert 'sourcetype="json_app"' in out
    assert "index=main" in out
    assert "mstats" in out


def test_render_usage_handoff_mentions_dlq_and_branch():
    out = render_usage_handoff()
    assert "DLQ" in out
    assert "branch" in out


def main() -> int:
    tests = [
        ("render_source_type_contains_name_and_sample_paths", test_render_source_type_contains_name_and_sample_paths),
        ("render_source_type_sanitizes_unsafe_chars", test_render_source_type_sanitizes_unsafe_chars),
        ("render_lifecycle_apply_runbook", test_render_lifecycle_apply_runbook),
        ("render_lifecycle_rollback_runbook", test_render_lifecycle_rollback_runbook),
        ("render_known_issues_lists_all_guardrails", test_render_known_issues_lists_all_guardrails),
        ("render_known_issues_lists_afe_regions", test_render_known_issues_lists_afe_regions),
        ("render_coverage_json_has_all_features", test_render_coverage_json_has_all_features),
        ("render_readiness_no_findings", test_render_readiness_no_findings),
        ("render_readiness_with_findings_lists_them", test_render_readiness_with_findings_lists_them),
        ("render_ui_handoff_lists_sources_destinations_pipelines", test_render_ui_handoff_lists_sources_destinations_pipelines),
        ("render_monitoring_searches_includes_sourcetype_and_index_clauses", test_render_monitoring_searches_includes_sourcetype_and_index_clauses),
        ("render_usage_handoff_mentions_dlq_and_branch", test_render_usage_handoff_mentions_dlq_and_branch),
    ]

    failures = 0
    for name, fn in tests:
        try:
            fn()
            print(f"PASS  {name}")
        except Exception:
            failures += 1
            print(f"FAIL  {name}")
            traceback.print_exc()

    print(f"\n{len(tests) - failures}/{len(tests)} tests passed")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
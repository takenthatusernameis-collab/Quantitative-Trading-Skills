#!/usr/bin/env python3
"""Unit tests for spl2_pipeline_kit.py: parsing, linting, and lint reporting.

Run with: python3 skills/splunk-spl2-pipeline-kit/tests/test_kit_lint.py
No third-party test framework is required; uses only the standard library.
"""

import sys
import tempfile
import traceback
from pathlib import Path

SKILLS_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SKILLS_DIR / "scripts"))

from spl2_pipeline_kit import (  # noqa: E402
    BASE_COMMANDS,
    INGEST_ONLY_COMMANDS,
    LintFinding,
    PROFILE_COMMANDS,
    command_names,
    import_names,
    lint_file,
    lint_text,
    status_from_reports,
    strip_comments,
)


VALID_IP = """$pipeline = | from $source
              | where sourcetype != "noisy:type"
              | into $destination;
"""


def _has_code(findings, code):
    """True if any finding (LintFinding or dict) carries the given code."""
    for finding in findings:
        value = finding.code if hasattr(finding, "code") else finding.get("code")
        if value == code:
            return True
    return False


def test_strip_comments_removes_inline_comments():
    out = strip_comments("// header\n$src // trailing\nplain")
    assert "header" not in out
    assert "//" not in out
    assert "$src " in out


def test_command_names_extracts_piped_commands():
    assert command_names(VALID_IP) == ["from", "where", "into"]


def test_command_names_ignores_commented_pipes():
    text = "// | table\n$pipeline = | from $source | into $destination;"
    names = command_names(text)
    assert "table" not in names
    assert names == ["from", "into"]


def test_import_names_parses_import_block():
    text = "import logs_to_metrics from /splunk.ingest.commands;\n$pipeline = | from $source | into $dst;"
    assert import_names(text) == {"logs_to_metrics"}


def test_import_names_empty_without_import():
    assert import_names(VALID_IP) == set()


def test_base_commands_contain_core_catalog():
    for name in ("from", "into", "where", "branch", "eval", "stats", "rex", "thru"):
        assert name in BASE_COMMANDS


def test_ingest_only_disjoint_from_edge_profile():
    assert INGEST_ONLY_COMMANDS.isdisjoint(BASE_COMMANDS)
    edge = PROFILE_COMMANDS["edgeProcessor"]
    assert INGEST_ONLY_COMMANDS.isdisjoint(edge)


def test_lint_finding_as_dict():
    finding = LintFinding("error", "SPL2-X", "boom")
    assert finding.as_dict() == {
        "severity": "error",
        "code": "SPL2-X",
        "message": "boom",
    }


def test_lint_text_valid_pipeline_has_no_findings():
    assert lint_text(VALID_IP, "ingestProcessor") == []


def test_lint_text_missing_pipeline_var():
    findings = lint_text("| from $source | into $destination;", "ingestProcessor")
    assert _has_code(findings, "SPL2-MISSING-PIPELINE")


def test_lint_text_missing_source():
    findings = lint_text("$pipeline = | where x | into $destination;", "ingestProcessor")
    assert _has_code(findings, "SPL2-MISSING-SOURCE")


def test_lint_text_missing_destination():
    findings = lint_text("$pipeline = | from $source;", "ingestProcessor")
    assert _has_code(findings, "SPL2-MISSING-DESTINATION")


def test_lint_text_ingest_only_incompatible_for_edge():
    text = "$pipeline = | from $source | decrypt x AS y WITH k | into $destination;"
    findings = lint_text(text, "edgeProcessor")
    assert _has_code(findings, "SPL2-PROFILE-INCOMPATIBLE")


def test_lint_text_logs_to_metrics_requires_import():
    text = '$pipeline = | from $source | logs_to_metrics metric_name="x" | into $destination;'
    findings = lint_text(text, "ingestProcessor")
    assert _has_code(findings, "SPL2-METRICS-IMPORT")


def test_lint_text_imported_command_skips_unknown_warning():
    text = (
        "import mything from /custom.flows;\n"
        "$pipeline = | from $source | mything | into $destination;"
    )
    findings = lint_text(text, "ingestProcessor")
    assert not _has_code(findings, "SPL2-UNKNOWN-COMMAND")


def test_lint_text_unknown_command_is_warning_when_not_strict():
    text = "$pipeline = | from $source | bogus_cmd | into $destination;"
    findings = lint_text(text, "ingestProcessor", strict=False)
    unknown = [f for f in findings if f.code == "SPL2-UNKNOWN-COMMAND"]
    assert unknown
    assert all(f.severity == "warning" for f in unknown)


def test_lint_text_unknown_command_is_error_when_strict():
    text = "$pipeline = | from $source | bogus_cmd | into $destination;"
    findings = lint_text(text, "ingestProcessor", strict=True)
    unknown = [f for f in findings if f.code == "SPL2-UNKNOWN-COMMAND"]
    assert unknown
    assert unknown[0].severity == "error"


def test_lint_text_stats_avg_is_error():
    text = '$pipeline = | from $source | stats avg(bytes) by sourcetype | into $destination;'
    findings = lint_text(text, "ingestProcessor")
    assert _has_code(findings, "SPL2-STATS-AVG")


def test_lint_text_stats_unknown_function_is_warning():
    text = "$pipeline = | from $source | stats bogus(bytes) | into $destination;"
    findings = lint_text(text, "ingestProcessor")
    assert _has_code(findings, "SPL2-STATS-FUNCTION")


def test_lint_text_stats_builtin_functions_are_clean():
    text = "$pipeline = | from $source | stats count() as c, sum(bytes) as s by sourcetype | into $destination;"
    findings = lint_text(text, "ingestProcessor")
    assert not _has_code(findings, "SPL2-STATS-FUNCTION")
    assert not _has_code(findings, "SPL2-STATS-AVG")


def test_lint_text_object_to_array_is_deprecated():
    text = "$pipeline = | from $source | eval x = object_to_array(y) | into $destination;"
    findings = lint_text(text, "ingestProcessor")
    assert _has_code(findings, "SPL2-DEPRECATED-FUNCTION")


def test_lint_text_pcre2_named_capture_warning():
    text = '$pipeline = | from $source | rex field=_raw "(?<user>[^ ]+)" | into $destination;'
    findings = lint_text(text, "ingestProcessor")
    assert _has_code(findings, "SPL2-PCRE2-NAMED-CAPTURE")


def test_lint_text_pcre2_sp_named_capture_is_clean():
    text = '$pipeline = | from $source | rex field=_raw "(?P<user>[^ ]+)" | into $destination;'
    findings = lint_text(text, "ingestProcessor")
    assert not _has_code(findings, "SPL2-PCRE2-NAMED-CAPTURE")


def test_lint_text_pcre2_backreference_warning():
    text = '$pipeline = | from $source | rex field=_raw "([a-z]+)\\1" | into $destination;'
    findings = lint_text(text, "ingestProcessor")
    assert _has_code(findings, "SPL2-PCRE2-BACKREFERENCE")


def test_lint_text_index_predicate_warning():
    text = "$pipeline = | from $source | where index=main | into $destination;"
    findings = lint_text(text, "ingestProcessor")
    assert _has_code(findings, "SPL2-SPL1-INDEX-PREDICATE")


def test_lint_text_spl1_command_warning():
    text = "$pipeline = | from $source | table x | into $destination;"
    findings = lint_text(text, "ingestProcessor")
    assert _has_code(findings, "SPL2-SPL1-COMMAND")


def test_lint_file_valid_returns_pass():
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "ok.spl2"
        path.write_text(VALID_IP, encoding="utf-8")
        report = lint_file(path, "ingestProcessor")
    assert report["status"] == "PASS"
    assert report["findings"] == []
    assert report["profile"] == "ingestProcessor"
    assert report["commands"] == ["from", "where", "into"]
    assert report["imports"] == []


def test_lint_file_invalid_returns_fail():
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "bad.spl2"
        path.write_text("| from $source | into $destination;", encoding="utf-8")
        report = lint_file(path, "ingestProcessor")
    assert report["status"] == "FAIL"
    assert _has_code(report["findings"], "SPL2-MISSING-PIPELINE")


def test_status_from_reports():
    assert status_from_reports([]) == "PASS"
    assert status_from_reports([{"status": "PASS"}]) == "PASS"
    assert status_from_reports([{"status": "PASS_WITH_WARNINGS"}]) == "PASS_WITH_WARNINGS"
    assert status_from_reports([{"status": "PASS"}, {"status": "FAIL"}]) == "FAIL"
    assert status_from_reports([{"status": "FAIL"}, {"status": "PASS_WITH_WARNINGS"}]) == "FAIL"


def main() -> int:
    tests = [
        ("strip_comments_removes_inline_comments", test_strip_comments_removes_inline_comments),
        ("command_names_extracts_piped_commands", test_command_names_extracts_piped_commands),
        ("command_names_ignores_commented_pipes", test_command_names_ignores_commented_pipes),
        ("import_names_parses_import_block", test_import_names_parses_import_block),
        ("import_names_empty_without_import", test_import_names_empty_without_import),
        ("base_commands_contain_core_catalog", test_base_commands_contain_core_catalog),
        ("ingest_only_disjoint_from_edge_profile", test_ingest_only_disjoint_from_edge_profile),
        ("lint_finding_as_dict", test_lint_finding_as_dict),
        ("lint_text_valid_pipeline_has_no_findings", test_lint_text_valid_pipeline_has_no_findings),
        ("lint_text_missing_pipeline_var", test_lint_text_missing_pipeline_var),
        ("lint_text_missing_source", test_lint_text_missing_source),
        ("lint_text_missing_destination", test_lint_text_missing_destination),
        ("lint_text_ingest_only_incompatible_for_edge", test_lint_text_ingest_only_incompatible_for_edge),
        ("lint_text_logs_to_metrics_requires_import", test_lint_text_logs_to_metrics_requires_import),
        ("lint_text_imported_command_skips_unknown_warning", test_lint_text_imported_command_skips_unknown_warning),
        ("lint_text_unknown_command_is_warning_when_not_strict", test_lint_text_unknown_command_is_warning_when_not_strict),
        ("lint_text_unknown_command_is_error_when_strict", test_lint_text_unknown_command_is_error_when_strict),
        ("lint_text_stats_avg_is_error", test_lint_text_stats_avg_is_error),
        ("lint_text_stats_unknown_function_is_warning", test_lint_text_stats_unknown_function_is_warning),
        ("lint_text_stats_builtin_functions_are_clean", test_lint_text_stats_builtin_functions_are_clean),
        ("lint_text_object_to_array_is_deprecated", test_lint_text_object_to_array_is_deprecated),
        ("lint_text_pcre2_named_capture_warning", test_lint_text_pcre2_named_capture_warning),
        ("lint_text_pcre2_sp_named_capture_is_clean", test_lint_text_pcre2_sp_named_capture_is_clean),
        ("lint_text_pcre2_backreference_warning", test_lint_text_pcre2_backreference_warning),
        ("lint_text_index_predicate_warning", test_lint_text_index_predicate_warning),
        ("lint_text_spl1_command_warning", test_lint_text_spl1_command_warning),
        ("lint_file_valid_returns_pass", test_lint_file_valid_returns_pass),
        ("lint_file_invalid_returns_fail", test_lint_file_invalid_returns_fail),
        ("status_from_reports", test_status_from_reports),
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

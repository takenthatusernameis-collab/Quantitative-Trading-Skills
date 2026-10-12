#!/usr/bin/env python3
"""Unit tests for validate_twb.py (TWB breakage-only XML validator)."""

import logging
import sys
import tempfile
import traceback
from pathlib import Path

SKILLS_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SKILLS_DIR / "scripts"))

from validate_twb import (
    CheckResult,
    TwbValidator,
    ValidationReport,
    main as validator_main,
    print_report,
)


# ── Fixtures ─────────────────────────────────────────────────────────

# Minimal workbook that passes all eight checks: one top-level
# datasource, one worksheet with a view/datasource reference, a
# datasource-dependencies block declaring one column and one
# column-instance, a shelf reference to that instance, and a
# matching worksheet-class window.
VALID_WORKBOOK = """<?xml version='1.0' encoding='utf-8'?>
<workbook>
  <datasources>
    <datasource name="sales" />
  </datasources>
  <worksheets>
    <worksheet name="SalesSheet">
      <view>
        <datasources>
          <datasource name="sales" />
        </datasources>
      </view>
      <datasource-dependencies datasource="sales">
        <column name="[profit]" />
        <column-instance column="[profit]" name="[sum:profit:qk]" />
      </datasource-dependencies>
      <table>
        <rows>[sales].[sum:profit:qk]</rows>
        <cols />
      </table>
    </worksheet>
  </worksheets>
  <windows>
    <window name="SalesSheet" class="worksheet" />
  </windows>
</workbook>
"""

CHECK_NAMES = [
    "Well-formed XML",
    "Datasource existence",
    "Column reference integrity",
    "Shelf reference integrity",
    "CDATA for field references",
    "Dashboard datasource declarations",
    "Filter/slices consistency",
    "Worksheet-window name match",
]


# ── Helpers ──────────────────────────────────────────────────────────

def _write_temp(content, suffix=".twb"):
    f = tempfile.NamedTemporaryFile(
        mode="w", suffix=suffix, delete=False, encoding="utf-8"
    )
    f.write(content)
    f.close()
    return f.name


def _validate(content, suffix=".twb"):
    path = _write_temp(content, suffix)
    try:
        return TwbValidator(path).validate()
    finally:
        Path(path).unlink()


def _mutate(content, old, new):
    assert old in content, f"mutation anchor not found: {old!r}"
    return content.replace(old, new, 1)


def _find_result(report, name):
    for result in report.results:
        if result.name == name:
            return result
    raise AssertionError(f"check {name!r} not present in report")


class _CaptureHandler(logging.Handler):
    def __init__(self):
        super().__init__()
        self.messages = []

    def emit(self, record):
        self.messages.append(record.getMessage())


def _capture_report_output(report, verbose=False):
    handler = _CaptureHandler()
    logger = logging.getLogger("validate_twb")
    logger.addHandler(handler)
    try:
        print_report(report, verbose=verbose)
    finally:
        logger.removeHandler(handler)
    return "\n".join(handler.messages)


# ── Data classes ─────────────────────────────────────────────────────

def test_check_result_default_details_is_empty_list():
    result = CheckResult(name="x", passed=True)
    assert result.details == []


def test_validation_report_passed_when_all_pass():
    report = ValidationReport(file_path="a.twb", results=[
        CheckResult(name="a", passed=True),
        CheckResult(name="b", passed=True),
    ])
    assert report.passed is True


def test_validation_report_failed_when_any_fails():
    report = ValidationReport(file_path="a.twb", results=[
        CheckResult(name="a", passed=True),
        CheckResult(name="b", passed=False, details=["boom"]),
    ])
    assert report.passed is False


def test_validation_report_passed_when_empty():
    report = ValidationReport(file_path="a.twb", results=[])
    assert report.passed is True


def test_validation_report_counts():
    report = ValidationReport(file_path="a.twb", results=[
        CheckResult(name="a", passed=True),
        CheckResult(name="b", passed=True),
        CheckResult(name="c", passed=True),
        CheckResult(name="d", passed=False),
        CheckResult(name="e", passed=False),
    ])
    assert report.passed_count == 3
    assert report.failed_count == 2


# ── Built-in field helpers ───────────────────────────────────────────

def test_is_builtin_field_known_fields():
    for ref in (
        "[Number of Records]",
        "[Measure Names]",
        "[Measure Values]",
        "[:Measure Names]",
        "[:Measure Values]",
    ):
        assert TwbValidator._is_builtin_field(ref), ref


def test_is_builtin_field_regular_fields():
    assert TwbValidator._is_builtin_field("[profit]") is False
    assert TwbValidator._is_builtin_field("profit") is False


def test_is_builtin_field_name_generated_and_measures():
    assert TwbValidator._is_builtin_field_name("City (generated)") is True
    assert TwbValidator._is_builtin_field_name("Measure Names") is True
    assert TwbValidator._is_builtin_field_name("Measure Values") is True


def test_is_builtin_field_name_regular_fields():
    assert TwbValidator._is_builtin_field_name("sum:profit:qk") is False


# ── Init and well-formed XML ─────────────────────────────────────────

def test_init_defaults():
    validator = TwbValidator("a.twb")
    assert validator.file_path == "a.twb"
    assert validator.raw_content == ""
    assert validator.tree is None
    assert validator.root is None
    assert validator.report.file_path == "a.twb"


def test_well_formed_xml_ok():
    report = _validate(VALID_WORKBOOK)
    result = _find_result(report, "Well-formed XML")
    assert result.passed is True
    assert result.details == []
    assert report.file_path  # path recorded


def test_well_formed_xml_malformed():
    report = _validate("<workbook><worksheet></workbook>")
    result = _find_result(report, "Well-formed XML")
    assert result.passed is False
    assert len(result.details) == 1
    assert "XML parse error" in result.details[0]


def test_well_formed_xml_missing_file():
    validator = TwbValidator("/nonexistent/path/does-not-exist.twb")
    report = validator.validate()
    result = _find_result(report, "Well-formed XML")
    assert result.passed is False
    assert len(result.details) == 1
    assert "File read error" in result.details[0]


# ── validate() orchestration ───────────────────────────────────────────

def test_validate_runs_all_eight_checks_in_order():
    report = _validate(VALID_WORKBOOK)
    assert [r.name for r in report.results] == CHECK_NAMES
    assert report.passed is True
    assert report.passed_count == 8
    assert report.failed_count == 0


def test_validate_early_return_on_malformed_xml():
    report = _validate("<workbook><broken></workbook>")
    assert len(report.results) == 1
    assert report.results[0].name == "Well-formed XML"
    assert report.passed is False


def test_validate_bare_workbook_passes():
    report = _validate("<workbook></workbook>")
    assert report.passed is True
    assert len(report.results) == 8


# ── Check 2: Datasource existence ────────────────────────────────────

def test_datasource_existence_ok():
    report = _validate(VALID_WORKBOOK)
    assert _find_result(report, "Datasource existence").passed is True


def test_datasource_existence_missing_reference():
    content = _mutate(
        VALID_WORKBOOK,
        "        <datasources>\n"
        "          <datasource name=\"sales\" />\n"
        "        </datasources>",
        "        <datasources>\n"
        "          <datasource name=\"ghost\" />\n"
        "        </datasources>",
    )
    report = _validate(content)
    result = _find_result(report, "Datasource existence")
    assert result.passed is False
    assert len(result.details) == 1
    assert "SalesSheet" in result.details[0]
    assert "ghost" in result.details[0]


def test_datasource_existence_no_worksheets():
    content = _mutate(
        VALID_WORKBOOK,
        "  <worksheets>\n"
        "    <worksheet name=\"SalesSheet\">\n"
        "      <view>\n"
        "        <datasources>\n"
        "          <datasource name=\"sales\" />\n"
        "        </datasources>\n"
        "      </view>\n"
        "      <datasource-dependencies datasource=\"sales\">\n"
        "        <column name=\"[profit]\" />\n"
        "        <column-instance column=\"[profit]\" name=\"[sum:profit:qk]\" />\n"
        "      </datasource-dependencies>\n"
        "      <table>\n"
        "        <rows>[sales].[sum:profit:qk]</rows>\n"
        "        <cols />\n"
        "      </table>\n"
        "    </worksheet>\n"
        "  </worksheets>",
        "  <worksheets />",
    )
    report = _validate(content)
    assert _find_result(report, "Datasource existence").passed is True


# ── Check 3: Column reference integrity ──────────────────────────────

def test_column_reference_integrity_ok():
    report = _validate(VALID_WORKBOOK)
    assert _find_result(report, "Column reference integrity").passed is True


def test_column_reference_integrity_undeclared_column():
    content = _mutate(
        VALID_WORKBOOK,
        "        <column-instance column=\"[profit]\" name=\"[sum:profit:qk]\" />",
        "        <column-instance column=\"[profit]\" name=\"[sum:profit:qk]\" />\n"
        "        <column-instance column=\"[revenue]\" name=\"[sum:revenue:qk]\" />",
    )
    report = _validate(content)
    result = _find_result(report, "Column reference integrity")
    assert result.passed is False
    assert len(result.details) == 1
    assert "[revenue]" in result.details[0]
    assert "[sum:revenue:qk]" in result.details[0]


def test_column_reference_integrity_builtin_field_skipped():
    content = _mutate(
        VALID_WORKBOOK,
        "        <column-instance column=\"[profit]\" name=\"[sum:profit:qk]\" />",
        "        <column-instance column=\"[profit]\" name=\"[sum:profit:qk]\" />\n"
        "        <column-instance column=\"[Number of Records]\" name=\"[Number of Records]\" />",
    )
    report = _validate(content)
    assert _find_result(report, "Column reference integrity").passed is True


def test_column_reference_integrity_datasource_declared_column():
    # A column declared in a <datasource> (rather than locally in the
    # datasource-dependencies block) also resolves. Note: ds_columns is
    # keyed by datasource name and later same-named datasources overwrite
    # earlier ones, so the declaration must be in the view's datasource
    # (the last same-named one in document order) to be visible here.
    content = _mutate(
        VALID_WORKBOOK,
        "        <datasources>\n"
        "          <datasource name=\"sales\" />\n"
        "        </datasources>",
        "        <datasources>\n"
        "          <datasource name=\"sales\">\n"
        "            <column name=\"[region]\" />\n"
        "          </datasource>\n"
        "        </datasources>",
    )
    content = _mutate(
        content,
        "        <column-instance column=\"[profit]\" name=\"[sum:profit:qk]\" />",
        "        <column-instance column=\"[profit]\" name=\"[sum:profit:qk]\" />\n"
        "        <column-instance column=\"[region]\" name=\"[sum:region:qk]\" />",
    )
    report = _validate(content)
    assert _find_result(report, "Column reference integrity").passed is True


# ── Check 4: Shelf reference integrity ───────────────────────────────

def test_shelf_reference_integrity_ok():
    report = _validate(VALID_WORKBOOK)
    assert _find_result(report, "Shelf reference integrity").passed is True


def test_shelf_reference_integrity_undeclared_instance():
    content = _mutate(
        VALID_WORKBOOK,
        "<rows>[sales].[sum:profit:qk]</rows>",
        "<rows>[sales].[sum:revenue:qk]</rows>",
    )
    report = _validate(content)
    result = _find_result(report, "Shelf reference integrity")
    assert result.passed is False
    assert len(result.details) == 1
    assert "sum:revenue:qk" in result.details[0]
    assert "<rows>" in result.details[0]


def test_shelf_reference_integrity_empty_shelf_valid():
    content = _mutate(
        VALID_WORKBOOK,
        "<rows>[sales].[sum:profit:qk]</rows>",
        "<rows />",
    )
    report = _validate(content)
    assert _find_result(report, "Shelf reference integrity").passed is True


def test_shelf_reference_integrity_measure_names_skipped():
    content = _mutate(
        VALID_WORKBOOK,
        "<rows>[sales].[sum:profit:qk]</rows>",
        "<rows>[sales].[sum:profit:qk] [sales].[Measure Names]</rows>",
    )
    report = _validate(content)
    assert _find_result(report, "Shelf reference integrity").passed is True


def test_shelf_reference_integrity_unbracketed_instance_name():
    content = _mutate(
        VALID_WORKBOOK,
        "        <column-instance column=\"[profit]\" name=\"[sum:profit:qk]\" />",
        "        <column-instance column=\"[profit]\" name=\"sum:profit:qk\" />",
    )
    report = _validate(content)
    assert _find_result(report, "Shelf reference integrity").passed is True


# ── Check 5: CDATA for field references ──────────────────────────────

def test_cdata_entity_encoded_reference_fails():
    content = _mutate(
        VALID_WORKBOOK,
        "      <table>",
        "      <formatted-text>\n"
        "        <run>&lt;[sales].[profit]&gt;</run>\n"
        "      </formatted-text>\n"
        "      <table>",
    )
    report = _validate(content)
    result = _find_result(report, "CDATA for field references")
    assert result.passed is False
    assert len(result.details) == 1
    assert "Line" in result.details[0]
    assert "entity-encoded" in result.details[0]


def test_cdata_cdata_wrapped_reference_passes():
    content = _mutate(
        VALID_WORKBOOK,
        "      <table>",
        "      <formatted-text>\n"
        "        <run><![CDATA[<[sales].[profit]>]]></run>\n"
        "      </formatted-text>\n"
        "      <table>",
    )
    report = _validate(content)
    assert _find_result(report, "CDATA for field references").passed is True


def test_cdata_plain_text_run_passes():
    content = _mutate(
        VALID_WORKBOOK,
        "      <table>",
        "      <formatted-text>\n"
        "        <run>Total sales</run>\n"
        "      </formatted-text>\n"
        "      <table>",
    )
    report = _validate(content)
    assert _find_result(report, "CDATA for field references").passed is True


# ── Check 6: Dashboard datasource declarations ───────────────────────

def test_dashboard_filter_zone_without_datasources_fails():
    content = _mutate(
        VALID_WORKBOOK,
        "  <windows>",
        "  <dashboards>\n"
        "    <dashboard name=\"Overview\">\n"
        "      <zone type=\"filter\" x=\"0\" y=\"0\" w=\"120\" h=\"80\" />\n"
        "    </dashboard>\n"
        "  </dashboards>\n"
        "  <windows>",
    )
    report = _validate(content)
    result = _find_result(report, "Dashboard datasource declarations")
    assert result.passed is False
    assert len(result.details) == 1
    assert "Overview" in result.details[0]
    assert "datasources" in result.details[0]


def test_dashboard_filter_zone_with_datasources_passes():
    content = _mutate(
        VALID_WORKBOOK,
        "  <windows>",
        "  <dashboards>\n"
        "    <dashboard name=\"Overview\">\n"
        "      <datasources>\n"
        "        <datasource name=\"sales\" />\n"
        "      </datasources>\n"
        "      <zone type=\"filter\" x=\"0\" y=\"0\" w=\"120\" h=\"80\" />\n"
        "    </dashboard>\n"
        "  </dashboards>\n"
        "  <windows>",
    )
    report = _validate(content)
    assert _find_result(report, "Dashboard datasource declarations").passed is True


def test_dashboard_filter_zone_mode_trigger_fails():
    content = _mutate(
        VALID_WORKBOOK,
        "  <windows>",
        "  <dashboards>\n"
        "    <dashboard name=\"Overview\">\n"
        "      <zone mode=\"slider\" x=\"0\" y=\"0\" w=\"120\" h=\"80\" />\n"
        "    </dashboard>\n"
        "  </dashboards>\n"
        "  <windows>",
    )
    report = _validate(content)
    assert _find_result(report, "Dashboard datasource declarations").passed is False


def test_dashboard_no_filter_zones_passes():
    content = _mutate(
        VALID_WORKBOOK,
        "  <windows>",
        "  <dashboards>\n"
        "    <dashboard name=\"Overview\">\n"
        "      <zone type=\"text\" x=\"0\" y=\"0\" w=\"120\" h=\"80\" />\n"
        "    </dashboard>\n"
        "  </dashboards>\n"
        "  <windows>",
    )
    report = _validate(content)
    assert _find_result(report, "Dashboard datasource declarations").passed is True


# ── Check 7: Filter/slices consistency ───────────────────────────────

def test_filter_slices_consistent_passes():
    content = _mutate(
        VALID_WORKBOOK,
        "        <datasources>\n"
        "          <datasource name=\"sales\" />\n"
        "        </datasources>\n"
        "      </view>",
        "        <datasources>\n"
        "          <datasource name=\"sales\" />\n"
        "        </datasources>\n"
        "        <filter column=\"region\" />\n"
        "        <slices>\n"
        "          <column>region</column>\n"
        "        </slices>\n"
        "      </view>",
    )
    report = _validate(content)
    assert _find_result(report, "Filter/slices consistency").passed is True


def test_filter_without_slices_entry_fails():
    content = _mutate(
        VALID_WORKBOOK,
        "        <datasources>\n"
        "          <datasource name=\"sales\" />\n"
        "        </datasources>\n"
        "      </view>",
        "        <datasources>\n"
        "          <datasource name=\"sales\" />\n"
        "        </datasources>\n"
        "        <filter column=\"region\" />\n"
        "      </view>",
    )
    report = _validate(content)
    result = _find_result(report, "Filter/slices consistency")
    assert result.passed is False
    assert len(result.details) == 1
    assert "region" in result.details[0]
    assert "slices" in result.details[0]


def test_no_filters_passes():
    report = _validate(VALID_WORKBOOK)
    assert _find_result(report, "Filter/slices consistency").passed is True


# ── Check 8: Worksheet-window name match ─────────────────────────────

def test_worksheet_window_match_ok():
    report = _validate(VALID_WORKBOOK)
    assert _find_result(report, "Worksheet-window name match").passed is True


def test_worksheet_without_window_fails():
    content = _mutate(
        VALID_WORKBOOK,
        "  <windows>\n"
        "    <window name=\"SalesSheet\" class=\"worksheet\" />\n"
        "  </windows>",
        "  <windows />",
    )
    report = _validate(content)
    result = _find_result(report, "Worksheet-window name match")
    assert result.passed is False
    assert len(result.details) == 1
    assert "SalesSheet" in result.details[0]


def test_window_without_worksheet_fails():
    content = _mutate(
        VALID_WORKBOOK,
        "<window name=\"SalesSheet\" class=\"worksheet\" />",
        "<window name=\"OtherSheet\" class=\"worksheet\" />",
    )
    report = _validate(content)
    result = _find_result(report, "Worksheet-window name match")
    assert result.passed is False
    assert len(result.details) == 2


def test_non_worksheet_window_ignored():
    content = _mutate(
        VALID_WORKBOOK,
        "<window name=\"SalesSheet\" class=\"worksheet\" />",
        "<window name=\"SalesSheet\" class=\"worksheet\" />\n"
        "    <window name=\"Dash1\" class=\"dashboard\" />",
    )
    report = _validate(content)
    assert _find_result(report, "Worksheet-window name match").passed is True


# ── print_report ───────────────────────────────────────────────────

def test_print_report_renders_passing_report():
    report = _validate(VALID_WORKBOOK)
    output = _capture_report_output(report)
    assert "TWB Validation Report" in output
    assert "[+] Well-formed XML: PASS" in output
    assert "Result: 8/8 checks passed, 0 failed" in output
    assert "Status: ALL CHECKS PASSED" in output


def test_print_report_renders_failure_details():
    report = _validate("<workbook><broken></workbook>")
    output = _capture_report_output(report)
    assert "[X] Well-formed XML: FAIL" in output
    assert "XML parse error" in output
    assert "Result: 0/1 checks passed, 1 failed" in output
    assert "Status: VALIDATION FAILED" in output


def test_print_report_verbose_runs():
    report = _validate(VALID_WORKBOOK)
    output = _capture_report_output(report, verbose=True)
    assert "Result: 8/8 checks passed, 0 failed" in output


# ── main() CLI ─────────────────────────────────────────────────────

def _run_main_with_argv(argvs):
    old_argv = sys.argv[:]
    try:
        sys.argv = argvs
        try:
            validator_main()
            return 0
        except SystemExit as e:
            return e.code
    finally:
        sys.argv = old_argv


def test_main_valid_file_exits_zero():
    path = _write_temp(VALID_WORKBOOK)
    try:
        assert _run_main_with_argv(["validate_twb.py", path]) == 0
    finally:
        Path(path).unlink()


def test_main_structurally_invalid_exits_one():
    content = _mutate(
        VALID_WORKBOOK,
        "  <windows>\n"
        "    <window name=\"SalesSheet\" class=\"worksheet\" />\n"
        "  </windows>",
        "  <windows />",
    )
    path = _write_temp(content)
    try:
        assert _run_main_with_argv(["validate_twb.py", path]) == 1
    finally:
        Path(path).unlink()


def test_main_malformed_xml_exits_one():
    path = _write_temp("<workbook><broken></workbook>")
    try:
        assert _run_main_with_argv(["validate_twb.py", path]) == 1
    finally:
        Path(path).unlink()


def test_main_missing_file_exits_two():
    assert _run_main_with_argv(["validate_twb.py", "/nonexistent/x.twb"]) == 2


def test_main_non_twb_extension_still_validates():
    path = _write_temp(VALID_WORKBOOK, suffix=".xml")
    try:
        assert _run_main_with_argv(["validate_twb.py", path]) == 0
    finally:
        Path(path).unlink()


def test_main_verbose_flag_runs():
    path = _write_temp(VALID_WORKBOOK)
    try:
        assert _run_main_with_argv(["validate_twb.py", path, "--verbose"]) == 0
    finally:
        Path(path).unlink()


# ── Runner ─────────────────────────────────────────────────────────

def main() -> int:
    tests = [
        ("check_result_default_details_is_empty_list", test_check_result_default_details_is_empty_list),
        ("validation_report_passed_when_all_pass", test_validation_report_passed_when_all_pass),
        ("validation_report_failed_when_any_fails", test_validation_report_failed_when_any_fails),
        ("validation_report_passed_when_empty", test_validation_report_passed_when_empty),
        ("validation_report_counts", test_validation_report_counts),
        ("is_builtin_field_known_fields", test_is_builtin_field_known_fields),
        ("is_builtin_field_regular_fields", test_is_builtin_field_regular_fields),
        ("is_builtin_field_name_generated_and_measures", test_is_builtin_field_name_generated_and_measures),
        ("is_builtin_field_name_regular_fields", test_is_builtin_field_name_regular_fields),
        ("init_defaults", test_init_defaults),
        ("well_formed_xml_ok", test_well_formed_xml_ok),
        ("well_formed_xml_malformed", test_well_formed_xml_malformed),
        ("well_formed_xml_missing_file", test_well_formed_xml_missing_file),
        ("validate_runs_all_eight_checks_in_order", test_validate_runs_all_eight_checks_in_order),
        ("validate_early_return_on_malformed_xml", test_validate_early_return_on_malformed_xml),
        ("validate_bare_workbook_passes", test_validate_bare_workbook_passes),
        ("datasource_existence_ok", test_datasource_existence_ok),
        ("datasource_existence_missing_reference", test_datasource_existence_missing_reference),
        ("datasource_existence_no_worksheets", test_datasource_existence_no_worksheets),
        ("column_reference_integrity_ok", test_column_reference_integrity_ok),
        ("column_reference_integrity_undeclared_column", test_column_reference_integrity_undeclared_column),
        ("column_reference_integrity_builtin_field_skipped", test_column_reference_integrity_builtin_field_skipped),
        ("column_reference_integrity_datasource_declared_column", test_column_reference_integrity_datasource_declared_column),
        ("shelf_reference_integrity_ok", test_shelf_reference_integrity_ok),
        ("shelf_reference_integrity_undeclared_instance", test_shelf_reference_integrity_undeclared_instance),
        ("shelf_reference_integrity_empty_shelf_valid", test_shelf_reference_integrity_empty_shelf_valid),
        ("shelf_reference_integrity_measure_names_skipped", test_shelf_reference_integrity_measure_names_skipped),
        ("shelf_reference_integrity_unbracketed_instance_name", test_shelf_reference_integrity_unbracketed_instance_name),
        ("cdata_entity_encoded_reference_fails", test_cdata_entity_encoded_reference_fails),
        ("cdata_cdata_wrapped_reference_passes", test_cdata_cdata_wrapped_reference_passes),
        ("cdata_plain_text_run_passes", test_cdata_plain_text_run_passes),
        ("dashboard_filter_zone_without_datasources_fails", test_dashboard_filter_zone_without_datasources_fails),
        ("dashboard_filter_zone_with_datasources_passes", test_dashboard_filter_zone_with_datasources_passes),
        ("dashboard_filter_zone_mode_trigger_fails", test_dashboard_filter_zone_mode_trigger_fails),
        ("dashboard_no_filter_zones_passes", test_dashboard_no_filter_zones_passes),
        ("filter_slices_consistent_passes", test_filter_slices_consistent_passes),
        ("filter_without_slices_entry_fails", test_filter_without_slices_entry_fails),
        ("no_filters_passes", test_no_filters_passes),
        ("worksheet_window_match_ok", test_worksheet_window_match_ok),
        ("worksheet_without_window_fails", test_worksheet_without_window_fails),
        ("window_without_worksheet_fails", test_window_without_worksheet_fails),
        ("non_worksheet_window_ignored", test_non_worksheet_window_ignored),
        ("print_report_renders_passing_report", test_print_report_renders_passing_report),
        ("print_report_renders_failure_details", test_print_report_renders_failure_details),
        ("print_report_verbose_runs", test_print_report_verbose_runs),
        ("main_valid_file_exits_zero", test_main_valid_file_exits_zero),
        ("main_structurally_invalid_exits_one", test_main_structurally_invalid_exits_one),
        ("main_malformed_xml_exits_one", test_main_malformed_xml_exits_one),
        ("main_missing_file_exits_two", test_main_missing_file_exits_two),
        ("main_non_twb_extension_still_validates", test_main_non_twb_extension_still_validates),
        ("main_verbose_flag_runs", test_main_verbose_flag_runs),
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

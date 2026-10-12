#!/usr/bin/env python3
"""Unit tests for data_quality_validator.py (data quality validation)."""

import contextlib
import io
import json
import logging
import statistics
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

SKILLS_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SKILLS_DIR / "scripts"))

import data_quality_validator as DQV  # noqa: E402
from data_quality_validator import main as dqv_main  # noqa: E402  (alias to avoid shadowing)


# ── Helpers ──────────────────────────────────────────────────────────


class _ListHandler(logging.Handler):
    """Logging handler that collects records for assertions."""

    def __init__(self):
        super().__init__()
        self.records = []

    def emit(self, record):
        self.records.append(record)


def _make_csv(tmpdir: Path, name: str, header: str, rows: list) -> Path:
    """Write a small CSV file and return its path."""
    path = tmpdir / name
    lines = [header] + [",".join(str(c) for c in row) for row in rows]
    path.write_text("\n".join(lines) + "\n")
    return path


def _make_json(tmpdir: Path, name: str, obj) -> Path:
    """Write a JSON file and return its path."""
    path = tmpdir / name
    path.write_text(json.dumps(obj))
    return path


def _run_main(argv: list):
    """Run the script's main() with a patched argv; return ("exit", code) or ("ok", None)."""
    old = sys.argv
    sys.argv = argv
    try:
        try:
            dqv_main()
        except SystemExit as e:
            return ("exit", e.code)
        return ("ok", None)
    finally:
        sys.argv = old


def _numeric_column_profile(**overrides):
    """Build a ColumnProfile for a clean integer column, with optional overrides."""
    base = dict(
        name="n",
        data_type="integer",
        total_count=10,
        null_count=0,
        null_percentage=0.0,
        unique_count=10,
        unique_percentage=100.0,
        min_value=1.0,
        max_value=10.0,
    )
    base.update(overrides)
    return DQV.ColumnProfile(**base)


# Shared collaborators (the custom runner instantiates test classes
# without invoking pytest-style setup_method, so fixtures are singletons)
_SCHEMA_VALIDATOR = DQV.SchemaValidator()
_ANOMALY_DETECTOR = DQV.AnomalyDetector()
_DATA_PROFILER = DQV.DataProfiler()
_GE_GENERATOR = DQV.GreatExpectationsGenerator()
_SCORE_CALCULATOR = DQV.QualityScoreCalculator()
_CONTRACT_VALIDATOR = DQV.DataContractValidator()
_REPORT_GENERATOR = DQV.ReportGenerator()


# ── Dataclasses ──────────────────────────────────────────────────────


class TestDataclasses:
    def test_column_schema_defaults(self):
        col = DQV.ColumnSchema(name="a", data_type="string")
        assert col.nullable is True
        assert col.unique is False
        assert col.min_value is None
        assert col.max_value is None
        assert col.min_length is None
        assert col.max_length is None
        assert col.pattern is None
        assert col.allowed_values is None
        assert col.description == ""

    def test_data_schema_defaults(self):
        schema = DQV.DataSchema(name="t", version="1.0", columns=[])
        assert schema.primary_key is None
        assert schema.row_count_min is None
        assert schema.row_count_max is None

    def test_validation_result_defaults(self):
        r = DQV.ValidationResult("check", "col", True, "expected", "actual")
        assert r.severity == "error"
        assert r.message == ""
        assert r.failed_rows == []

    def test_column_profile_defaults(self):
        p = DQV.ColumnProfile(
            name="a", data_type="string", total_count=1,
            null_count=0, null_percentage=0.0,
            unique_count=1, unique_percentage=100.0,
        )
        assert p.min_value is None
        assert p.max_value is None
        assert p.mean is None
        assert p.median is None
        assert p.std_dev is None
        assert p.percentile_25 is None
        assert p.percentile_75 is None
        assert p.min_length is None
        assert p.max_length is None
        assert p.avg_length is None
        assert p.detected_pattern is None
        assert p.top_values == []

    def test_quality_score_construction(self):
        score = DQV.QualityScore(
            completeness=90.0, uniqueness=100.0, validity=80.0,
            consistency=70.0, accuracy=60.0, overall=75.0,
        )
        assert score.overall == 75.0
        assert score.completeness == 90.0

    def test_asdict_serialization_round_trip(self):
        col = DQV.ColumnSchema(
            name="a", data_type="integer", nullable=False, unique=True,
            min_value=0, max_value=10, min_length=1, max_length=5,
            pattern=r"^\d+$", allowed_values=["x"], description="col a",
        )
        d = DQV.asdict(col)
        assert d["name"] == "a"
        assert d["data_type"] == "integer"
        assert d["nullable"] is False
        assert d["unique"] is True
        assert d["min_value"] == 0
        assert d["allowed_values"] == ["x"]
        # JSON round trip preserves the fields
        assert json.loads(json.dumps(d)) == d


# ── TypeDetector ─────────────────────────────────────────────────────


class TestTypeDetector:
    def test_empty_values_detect_string(self):
        assert DQV.TypeDetector.detect_type([]) == "string"

    def test_all_blank_values_detect_string(self):
        assert DQV.TypeDetector.detect_type(["", "  ", ""]) == "string"

    def test_detects_email(self):
        assert DQV.TypeDetector.detect_type(["a@b.com"] * 10) == "email"

    def test_detects_uuid(self):
        values = ["12345678-1234-1234-1234-123456789abc"] * 10
        assert DQV.TypeDetector.detect_type(values) == "uuid"

    def test_detects_phone(self):
        assert DQV.TypeDetector.detect_type(["+1 555 123 4567"] * 10) == "phone"

    def test_detects_url(self):
        assert DQV.TypeDetector.detect_type(["https://example.com/x"] * 10) == "url"

    def test_detects_ipv4(self):
        assert DQV.TypeDetector.detect_type(["192.168.1.1"] * 10) == "ipv4"

    def test_detects_datetime_iso(self):
        assert DQV.TypeDetector.detect_type(["2024-01-15T10:30:00"] * 10) == "datetime_iso"

    def test_iso_date_matches_phone_pattern_first(self):
        # PATTERNS is a dict and 'phone' precedes 'date_iso'; a bare
        # ISO date (digits and dashes, 10+ chars) satisfies the phone
        # pattern, so detect_type reports "phone". This documents the
        # actual pattern-precedence behavior.
        assert DQV.TypeDetector.detect_type(["2024-01-15"] * 10) == "phone"

    def test_credit_card_matches_phone_pattern_first(self):
        # Same precedence quirk: the 19-char card number matches 'phone'.
        assert DQV.TypeDetector.detect_type(["4111-1111-1111-1111"] * 10) == "phone"

    def test_detects_integer(self):
        assert DQV.TypeDetector.detect_type([str(i) for i in range(1, 11)]) == "integer"

    def test_detects_float(self):
        assert DQV.TypeDetector.detect_type([f"{i}.5" for i in range(1, 11)]) == "float"

    def test_mixed_int_and_float_detects_float(self):
        assert DQV.TypeDetector.detect_type(["1", "2.5"] * 5) == "float"

    def test_detects_boolean(self):
        assert DQV.TypeDetector.detect_type(["true", "false"] * 5) == "boolean"

    def test_detects_string(self):
        assert DQV.TypeDetector.detect_type(["apple", "banana"] * 5) == "string"

    def test_detect_pattern_returns_none_for_empty(self):
        assert DQV.TypeDetector.detect_pattern([]) is None

    def test_detect_pattern_requires_ten_values(self):
        assert DQV.TypeDetector.detect_pattern(["a@b.com"] * 5) is None

    def test_detect_pattern_finds_email(self):
        assert DQV.TypeDetector.detect_pattern(["a@b.com"] * 10) == "email"

    def test_detect_pattern_returns_none_below_threshold(self):
        # 5 of 10 match, below the 0.8 ratio
        assert DQV.TypeDetector.detect_pattern(["a@b.com"] * 5 + ["x"] * 5) is None


# ── SchemaValidator: type checks ───────────────────────────────────


class TestSchemaValidatorType:

    def test_integer_valid(self):
        assert _SCHEMA_VALIDATOR._validate_type(["1", "2", 3], "integer") == []

    def test_integer_invalid(self):
        assert _SCHEMA_VALIDATOR._validate_type(["1", "x"], "integer") == [1]

    def test_float_valid(self):
        assert _SCHEMA_VALIDATOR._validate_type(["1.5", 2.5], "float") == []

    def test_float_invalid(self):
        assert _SCHEMA_VALIDATOR._validate_type(["1.5", "x"], "float") == [1]

    def test_boolean_valid(self):
        values = ["true", "false", "yes", "no", "1", "0"]
        assert _SCHEMA_VALIDATOR._validate_type(values, "boolean") == []

    def test_boolean_invalid(self):
        assert _SCHEMA_VALIDATOR._validate_type(["true", "maybe"], "boolean") == [1]

    def test_email_valid(self):
        assert _SCHEMA_VALIDATOR._validate_type(["a@b.com"], "email") == []

    def test_email_invalid(self):
        assert _SCHEMA_VALIDATOR._validate_type(["a@b.com", "bad"], "email") == [1]

    def test_uuid_valid(self):
        uuid = "12345678-1234-1234-1234-123456789abc"
        assert _SCHEMA_VALIDATOR._validate_type([uuid], "uuid") == []

    def test_uuid_invalid(self):
        uuid = "12345678-1234-1234-1234-123456789abc"
        assert _SCHEMA_VALIDATOR._validate_type([uuid, "bad"], "uuid") == [1]

    def test_date_valid(self):
        assert _SCHEMA_VALIDATOR._validate_type(["2024-01-15"], "date") == []

    def test_date_invalid(self):
        assert _SCHEMA_VALIDATOR._validate_type(["2024-01-15", "bad"], "date") == [1]

    def test_datetime_valid(self):
        assert _SCHEMA_VALIDATOR._validate_type(["2024-01-15T10:30:00"], "datetime") == []

    def test_datetime_invalid(self):
        assert _SCHEMA_VALIDATOR._validate_type(["2024-01-15T10:30:00", "bad"], "datetime") == [1]

    def test_string_accepts_anything(self):
        assert _SCHEMA_VALIDATOR._validate_type(["anything", "123", ""], "string") == []


# ── SchemaValidator: validate() ────────────────────────────────────


class TestSchemaValidator:

    def test_empty_dataset_fails(self):
        schema = DQV.DataSchema(name="t", version="1.0", columns=[])
        results = _SCHEMA_VALIDATOR.validate([], schema)
        assert len(results) == 1
        assert results[0].check_name == "data_not_empty"
        assert results[0].passed is False
        assert results[0].severity == "error"

    def test_valid_data_passes(self):
        schema = DQV.DataSchema(
            name="t", version="1.0",
            columns=[DQV.ColumnSchema(name="id", data_type="integer",
                                      nullable=False, unique=True)],
        )
        data = [{"id": i} for i in range(1, 6)]
        assert _SCHEMA_VALIDATOR.validate(data, schema) == []

    def test_not_null_check(self):
        schema = DQV.DataSchema(
            name="t", version="1.0",
            columns=[DQV.ColumnSchema(name="id", data_type="integer", nullable=False)],
        )
        data = [{"id": 1}, {"id": None}, {"id": ""}]
        results = _SCHEMA_VALIDATOR.validate(data, schema)
        assert len(results) == 1
        assert results[0].check_name == "not_null"
        assert results[0].failed_rows == [1, 2]
        assert "2 nulls" in results[0].actual

    def test_unique_check(self):
        schema = DQV.DataSchema(
            name="t", version="1.0",
            columns=[DQV.ColumnSchema(name="id", data_type="integer", unique=True)],
        )
        results = _SCHEMA_VALIDATOR.validate([{"id": 1}, {"id": 1}], schema)
        assert len(results) == 1
        assert results[0].check_name == "unique"
        assert "1 duplicates" in results[0].actual

    def test_range_check(self):
        schema = DQV.DataSchema(
            name="t", version="1.0",
            columns=[DQV.ColumnSchema(name="n", data_type="integer",
                                      min_value=0, max_value=10)],
        )
        data = [{"n": -1}, {"n": 5}, {"n": 11}]
        results = _SCHEMA_VALIDATOR.validate(data, schema)
        assert len(results) == 1
        assert results[0].check_name == "value_range"
        assert results[0].failed_rows == [0, 2]

    def test_length_check(self):
        schema = DQV.DataSchema(
            name="t", version="1.0",
            columns=[DQV.ColumnSchema(name="s", data_type="string",
                                      min_length=2, max_length=4)],
        )
        data = [{"s": "a"}, {"s": "ab"}, {"s": "abcde"}]
        results = _SCHEMA_VALIDATOR.validate(data, schema)
        assert len(results) == 1
        assert results[0].check_name == "string_length"
        assert results[0].failed_rows == [0, 2]
        assert results[0].severity == "warning"

    def test_pattern_check(self):
        schema = DQV.DataSchema(
            name="t", version="1.0",
            columns=[DQV.ColumnSchema(name="s", data_type="string", pattern=r"^\d+$")],
        )
        results = _SCHEMA_VALIDATOR.validate([{"s": "123"}, {"s": "abc"}], schema)
        assert len(results) == 1
        assert results[0].check_name == "pattern_match"
        assert results[0].failed_rows == [1]

    def test_allowed_values_check(self):
        schema = DQV.DataSchema(
            name="t", version="1.0",
            columns=[DQV.ColumnSchema(name="s", data_type="string",
                                      allowed_values=["a", "b"])],
        )
        results = _SCHEMA_VALIDATOR.validate([{"s": "a"}, {"s": "c"}], schema)
        assert len(results) == 1
        assert results[0].check_name == "allowed_values"
        assert results[0].failed_rows == [1]

    def test_primary_key_check(self):
        schema = DQV.DataSchema(
            name="t", version="1.0",
            columns=[DQV.ColumnSchema(name="a", data_type="integer")],
            primary_key=["a"],
        )
        results = _SCHEMA_VALIDATOR.validate([{"a": 1}, {"a": 1}], schema)
        assert len(results) == 1
        assert results[0].check_name == "primary_key_unique"
        assert "1 duplicate keys" in results[0].actual

    def test_row_count_min_check(self):
        schema = DQV.DataSchema(name="t", version="1.0", columns=[], row_count_min=10)
        results = _SCHEMA_VALIDATOR.validate([{"a": 1}], schema)
        assert len(results) == 1
        assert results[0].check_name == "row_count_min"
        assert results[0].severity == "error"

    def test_row_count_max_check(self):
        schema = DQV.DataSchema(name="t", version="1.0", columns=[], row_count_max=2)
        results = _SCHEMA_VALIDATOR.validate([{"a": i} for i in range(5)], schema)
        assert len(results) == 1
        assert results[0].check_name == "row_count_max"
        assert results[0].severity == "warning"

    def test_missing_column_check(self):
        schema = DQV.DataSchema(
            name="t", version="1.0",
            columns=[DQV.ColumnSchema(name="x", data_type="integer")],
        )
        results = _SCHEMA_VALIDATOR.validate([{"a": 1}], schema)
        assert len(results) == 1
        assert results[0].check_name == "column_exists"
        assert results[0].column == "x"


# ── SchemaValidator: helper methods ────────────────────────────────


class TestSchemaValidatorHelpers:

    def test_validate_range_returns_out_of_range_indices(self):
        col = DQV.ColumnSchema(name="n", data_type="integer", min_value=0, max_value=10)
        assert _SCHEMA_VALIDATOR._validate_range([-5, 5, 15], col) == [0, 2]

    def test_validate_range_skips_non_numeric(self):
        col = DQV.ColumnSchema(name="n", data_type="integer", min_value=0)
        assert _SCHEMA_VALIDATOR._validate_range(["abc"], col) == []

    def test_validate_length_returns_invalid_indices(self):
        col = DQV.ColumnSchema(name="s", data_type="string", min_length=2, max_length=4)
        assert _SCHEMA_VALIDATOR._validate_length(["a", "ab", "abcde"], col) == [0, 2]

    def test_validate_pattern_returns_non_matching_indices(self):
        assert _SCHEMA_VALIDATOR._validate_pattern(["123", "abc"], r"^\d+$") == [1]

    def test_validate_primary_key_no_duplicates(self):
        assert _SCHEMA_VALIDATOR._validate_primary_key([{"a": 1}, {"a": 2}], ["a"]) == []

    def test_validate_primary_key_composite(self):
        data = [{"a": 1, "b": 1}, {"a": 1, "b": 1}, {"a": 1, "b": 2}]
        results = _SCHEMA_VALIDATOR._validate_primary_key(data, ["a", "b"])
        assert len(results) == 1
        assert results[0].column == "a,b"


# ── AnomalyDetector ────────────────────────────────────────────────


class TestAnomalyDetector:

    def test_empty_data_returns_no_results(self):
        assert _ANOMALY_DETECTOR.validate([]) == []

    def test_clean_data_returns_no_results(self):
        data = [{"v": i} for i in range(1, 21)]
        assert _ANOMALY_DETECTOR.validate(data) == []

    def test_z_score_outlier_detected(self):
        data = [{"v": 1} for _ in range(19)] + [{"v": 1000}]
        results = _ANOMALY_DETECTOR.validate(data)
        z_results = [r for r in results if r.check_name == "z_score_outlier"]
        assert len(z_results) == 1
        assert z_results[0].column == "v"
        assert z_results[0].passed is False
        assert z_results[0].severity == "warning"
        assert z_results[0].failed_rows == [19]

    def test_iqr_outlier_detected(self):
        data = [{"v": 1} for _ in range(19)] + [{"v": 1000}]
        results = _ANOMALY_DETECTOR.validate(data)
        iqr_results = [r for r in results if r.check_name == "iqr_outlier"]
        assert len(iqr_results) == 1
        assert iqr_results[0].column == "v"
        assert iqr_results[0].passed is False
        assert iqr_results[0].severity == "warning"
        assert iqr_results[0].failed_rows == [19]

    def test_non_numeric_column_skipped(self):
        data = [{"s": f"value{i}"} for i in range(20)]
        assert _ANOMALY_DETECTOR.validate(data) == []

    def test_fewer_than_ten_values_skipped(self):
        data = [{"v": i} for i in range(5)]
        assert _ANOMALY_DETECTOR.validate(data) == []

    def test_custom_thresholds(self):
        detector = DQV.AnomalyDetector(z_threshold=1.0)
        data = [{"v": i} for i in range(1, 21)]
        results = detector.validate(data)
        # With a low z-threshold of 1.0, the extremes of 1..20 are flagged
        assert any(r.check_name == "z_score_outlier" for r in results)


# ── DataProfiler ───────────────────────────────────────────────────


class TestDataProfiler:

    def test_empty_profile(self):
        profile = _DATA_PROFILER.profile([], name="empty")
        assert profile.name == "empty"
        assert profile.row_count == 0
        assert profile.column_count == 0
        assert profile.columns == []
        assert profile.duplicate_rows == 0
        assert profile.memory_size_bytes == 0
        assert profile.profile_timestamp

    def test_profile_counts(self):
        data = [{"a": 1, "b": "x"}, {"a": 2, "b": "y"}]
        profile = _DATA_PROFILER.profile(data, name="testds")
        assert profile.row_count == 2
        assert profile.column_count == 2
        assert [c.name for c in profile.columns] == ["a", "b"]

    def test_duplicate_rows_counted(self):
        data = [{"a": 1}, {"a": 1}, {"a": 2}]
        profile = _DATA_PROFILER.profile(data, name="dup")
        assert profile.duplicate_rows == 1

    def test_memory_size_positive(self):
        profile = _DATA_PROFILER.profile([{"a": 1}], name="m")
        assert profile.memory_size_bytes > 0

    def test_numeric_column_stats(self):
        data = [{"n": i} for i in range(1, 11)]
        p = _DATA_PROFILER._profile_column(data, "n")
        assert p.data_type == "integer"
        assert p.min_value == 1.0
        assert p.max_value == 10.0
        assert p.mean == 5.5
        assert p.median == 5.5
        assert abs(p.std_dev - statistics.stdev([float(i) for i in range(1, 11)])) < 1e-9
        assert p.percentile_25 == 3.0
        assert p.percentile_75 == 8.0
        assert p.unique_count == 10
        assert p.unique_percentage == 100.0

    def test_string_column_stats(self):
        data = [{"s": v} for v in ("apple", "banana", "cherry")]
        p = _DATA_PROFILER._profile_column(data, "s")
        assert p.data_type == "string"
        assert p.min_length == 5
        assert p.max_length == 6
        assert abs(p.avg_length - 17 / 3) < 1e-9

    def test_null_counts(self):
        data = [{"a": i} for i in range(1, 9)] + [{"a": None}, {"a": ""}]
        p = _DATA_PROFILER._profile_column(data, "a")
        assert p.total_count == 10
        assert p.null_count == 2
        assert p.null_percentage == 20.0
        assert p.unique_count == 8
        assert p.unique_percentage == 100.0

    def test_top_values(self):
        data = [{"s": "b"}, {"s": "a"}, {"s": "b"}, {"s": "c"}, {"s": "b"}]
        p = _DATA_PROFILER._profile_column(data, "s")
        assert p.top_values[0] == ("b", 3)
        assert ("a", 1) in p.top_values
        assert ("c", 1) in p.top_values

    def test_detected_pattern(self):
        data = [{"e": f"user{i}@example.com"} for i in range(10)]
        p = _DATA_PROFILER._profile_column(data, "e")
        assert p.data_type == "email"
        assert p.detected_pattern == "email"


# ── GreatExpectationsGenerator ───────────────────────────────────


class TestGreatExpectationsGenerator:

    def _profile(self, columns, row_count=10, name="testds"):
        return DQV.DataProfile(
            name=name, row_count=row_count, column_count=len(columns),
            columns=columns, duplicate_rows=0, memory_size_bytes=0,
            profile_timestamp="2024-01-01T00:00:00",
        )

    def test_suite_structure(self):
        profile = self._profile([_numeric_column_profile()])
        suite = _GE_GENERATOR.generate_suite(profile)
        assert suite["expectation_suite_name"] == "testds_suite"
        assert suite["meta"]["generator"] == "data_quality_validator"
        assert suite["meta"]["source_profile"] == "testds"
        assert "generated_at" in suite["meta"]

    def test_table_expectations(self):
        profile = self._profile([_numeric_column_profile()], row_count=10)
        suite = _GE_GENERATOR.generate_suite(profile)
        types = [e["expectation_type"] for e in suite["expectations"]]
        assert "expect_table_row_count_to_be_between" in types
        assert "expect_table_column_count_to_equal" in types
        row_expect = next(
            e for e in suite["expectations"]
            if e["expectation_type"] == "expect_table_row_count_to_be_between"
        )
        assert row_expect["kwargs"]["min_value"] == 5
        assert row_expect["kwargs"]["max_value"] == 20
        col_expect = next(
            e for e in suite["expectations"]
            if e["expectation_type"] == "expect_table_column_count_to_equal"
        )
        assert col_expect["kwargs"]["value"] == 1

    def test_integer_column_expectations(self):
        expectations = _GE_GENERATOR._generate_column_expectations(
            _numeric_column_profile()
        )
        types = [e["expectation_type"] for e in expectations]
        assert types == [
            "expect_column_to_exist",
            "expect_column_values_to_not_be_null",
            "expect_column_values_to_be_unique",
            "expect_column_values_to_be_in_type_list",
            "expect_column_values_to_be_between",
        ]
        between = expectations[-1]
        assert between["kwargs"]["min_value"] == 1.0
        assert between["kwargs"]["max_value"] == 10.0

    def test_email_column_expectations(self):
        col = _numeric_column_profile(name="e", data_type="email")
        types = [e["expectation_type"]
                 for e in _GE_GENERATOR._generate_column_expectations(col)]
        assert "expect_column_values_to_match_regex" in types

    def test_date_column_expectations(self):
        col = _numeric_column_profile(name="d", data_type="date_iso")
        types = [e["expectation_type"]
                 for e in _GE_GENERATOR._generate_column_expectations(col)]
        assert "expect_column_values_to_match_strftime_format" in types

    def test_string_length_expectations(self):
        col = _numeric_column_profile(
            name="s", data_type="string", min_length=2, max_length=5,
        )
        expectations = _GE_GENERATOR._generate_column_expectations(col)
        lengths = next(
            e for e in expectations
            if e["expectation_type"] == "expect_column_value_lengths_to_be_between"
        )
        assert lengths["kwargs"]["min_value"] == 2
        assert lengths["kwargs"]["max_value"] == 10  # max_length * 2

    def test_categorical_column_expectations(self):
        col = _numeric_column_profile(
            name="status", data_type="string",
            total_count=100, unique_count=3, unique_percentage=3.0,
            top_values=[("ok", 95), ("fail", 4), ("warn", 1)],
        )
        expectations = _GE_GENERATOR._generate_column_expectations(col)
        in_set = next(
            e for e in expectations
            if e["expectation_type"] == "expect_column_values_to_be_in_set"
        )
        # "warn" count (1) is not > total_count * 0.01 (1.0), so excluded
        assert in_set["kwargs"]["value_set"] == ["ok", "fail"]
        assert in_set["kwargs"]["mostly"] == 0.95

    def test_mid_null_percentage_includes_mostly(self):
        col = _numeric_column_profile(
            name="s", data_type="string",
            null_count=20, null_percentage=20.0,
            unique_count=80, unique_percentage=80.0,
        )
        expectations = _GE_GENERATOR._generate_column_expectations(col)
        not_null = next(
            e for e in expectations
            if e["expectation_type"] == "expect_column_values_to_not_be_null"
        )
        assert abs(not_null["kwargs"]["mostly"] - 0.7) < 1e-9


# ── QualityScoreCalculator ───────────────────────────────────────


class TestQualityScoreCalculator:

    def test_quality_score_math(self):
        columns = [
            DQV.ColumnProfile(
                name="a", data_type="email", total_count=10,
                null_count=2, null_percentage=20.0,
                unique_count=10, unique_percentage=100.0,
                detected_pattern="email",
            ),
            DQV.ColumnProfile(
                name="b", data_type="string", total_count=10,
                null_count=0, null_percentage=0.0,
                unique_count=5, unique_percentage=50.0,
            ),
        ]
        profile = DQV.DataProfile(
            name="t", row_count=10, column_count=2, columns=columns,
            duplicate_rows=0, memory_size_bytes=0,
            profile_timestamp="2024-01-01T00:00:00",
        )
        results = [
            DQV.ValidationResult("c1", "a", True, "x", "y"),
            DQV.ValidationResult("c2", "a", False, "x", "y", severity="error"),
            DQV.ValidationResult("c3", "a", False, "x", "y", severity="warning"),
        ]
        score = _SCORE_CALCULATOR.calculate(profile, results)
        assert score.completeness == 90.0
        assert score.uniqueness == 100.0
        assert score.validity == 33.33
        assert score.consistency == 66.67
        assert score.accuracy == 75.0
        assert abs(score.overall - 68.33) < 0.01

    def test_empty_profile_score(self):
        profile = DQV.DataProfile(
            name="e", row_count=0, column_count=0, columns=[],
            duplicate_rows=0, memory_size_bytes=0,
            profile_timestamp="2024-01-01T00:00:00",
        )
        score = _SCORE_CALCULATOR.calculate(profile, [])
        assert score.completeness == 0
        assert score.uniqueness == 100
        assert score.validity == 100
        assert score.consistency == 100
        assert score.accuracy == 50
        assert score.overall == 70.0

    def test_all_passing_results(self):
        columns = [
            DQV.ColumnProfile(
                name="a", data_type="string", total_count=10,
                null_count=0, null_percentage=0.0,
                unique_count=10, unique_percentage=100.0,
            ),
        ]
        profile = DQV.DataProfile(
            name="t", row_count=10, column_count=1, columns=columns,
            duplicate_rows=0, memory_size_bytes=0,
            profile_timestamp="2024-01-01T00:00:00",
        )
        results = [DQV.ValidationResult("c1", "a", True, "x", "y")]
        score = _SCORE_CALCULATOR.calculate(profile, results)
        assert score.validity == 100.0
        assert score.consistency == 100.0
        assert score.accuracy == 50.0  # no detected patterns


# ── DataContractValidator ────────────────────────────────────────


class TestDataContractValidator:

    def test_types_compatible_numeric_group(self):
        assert _CONTRACT_VALIDATOR._types_compatible("integer", "int") is True
        assert _CONTRACT_VALIDATOR._types_compatible("integer", "float") is True
        assert _CONTRACT_VALIDATOR._types_compatible("float", "decimal") is True

    def test_types_compatible_string_boolean_date_groups(self):
        assert _CONTRACT_VALIDATOR._types_compatible("string", "varchar") is True
        assert _CONTRACT_VALIDATOR._types_compatible("boolean", "bool") is True
        assert _CONTRACT_VALIDATOR._types_compatible("date_iso", "date") is True
        assert _CONTRACT_VALIDATOR._types_compatible("datetime_iso", "timestamp") is True

    def test_types_compatible_exact_match(self):
        assert _CONTRACT_VALIDATOR._types_compatible("email", "email") is True
        assert _CONTRACT_VALIDATOR._types_compatible("uuid", "uuid") is True

    def test_types_compatible_incompatible(self):
        assert _CONTRACT_VALIDATOR._types_compatible("integer", "string") is False
        assert _CONTRACT_VALIDATOR._types_compatible("email", "string") is False

    def test_validate_contract_pass(self):
        contract = {
            "schema": {"columns": [
                {"name": "id", "type": "integer", "nullable": False},
                {"name": "email", "type": "email"},
            ]},
            "sla": {"min_rows": 1, "max_rows": 100},
        }
        data = [{"id": str(i), "email": f"u{i}@example.com"} for i in range(1, 6)]
        assert _CONTRACT_VALIDATOR.validate_contract(data, contract) == []

    def test_validate_contract_type_mismatch(self):
        contract = {"schema": {"columns": [{"name": "id", "type": "integer"}]}}
        results = _CONTRACT_VALIDATOR.validate_contract([{"id": "abc"}], contract)
        assert len(results) == 1
        assert results[0].check_name == "contract_data_type"
        assert results[0].expected == "integer"
        assert results[0].actual == "string"

    def test_validate_contract_missing_column(self):
        contract = {"schema": {"columns": [{"name": "id"}, {"name": "email"}]}}
        results = _CONTRACT_VALIDATOR.validate_contract([{"id": "10"}], contract)
        assert any(r.check_name == "contract_column_exists" and r.column == "email"
                   for r in results)

    def test_validate_contract_not_nullable(self):
        contract = {"schema": {"columns": [{"name": "id", "type": "integer",
                                          "nullable": False}]}}
        results = _CONTRACT_VALIDATOR.validate_contract([{"id": None}], contract)
        assert len(results) == 1
        assert results[0].check_name == "contract_not_null"
        assert "1 nulls" in results[0].actual

    def test_validate_contract_min_rows(self):
        contract = {"sla": {"min_rows": 5}}
        results = _CONTRACT_VALIDATOR.validate_contract([{"a": 1}, {"a": 2}], contract)
        assert len(results) == 1
        assert results[0].check_name == "contract_min_rows"
        assert results[0].severity == "error"
        assert results[0].expected == ">= 5 rows"

    def test_validate_contract_max_rows(self):
        contract = {"sla": {"max_rows": 1}}
        results = _CONTRACT_VALIDATOR.validate_contract([{"a": 1}, {"a": 2}], contract)
        assert len(results) == 1
        assert results[0].check_name == "contract_max_rows"
        assert results[0].severity == "warning"

    def test_parse_simple_yaml_scalars(self):
        content = 'name: my_contract\nversion: 2\nenabled: true\ndisabled: false\nthreshold: 42\nratio: "quoted string"\n'
        parsed = _CONTRACT_VALIDATOR._parse_simple_yaml(content)
        assert parsed == {
            "name": "my_contract",
            "version": 2,
            "enabled": True,
            "disabled": False,
            "threshold": 42,
            "ratio": "quoted string",
        }

    def test_parse_simple_yaml_inline_list(self):
        parsed = _CONTRACT_VALIDATOR._parse_simple_yaml("tags: [a, b, c]\n")
        assert parsed == {"tags": ["a", "b", "c"]}

    def test_parse_simple_yaml_nested_sections(self):
        content = "sla:\n  min_rows: 5\n  max_rows: 100\n"
        assert _CONTRACT_VALIDATOR._parse_simple_yaml(content) == {
            "sla": {"min_rows": 5, "max_rows": 100}
        }

    def test_parse_simple_yaml_list_items(self):
        content = "owners:\n  - alice\n  - bob\n"
        assert _CONTRACT_VALIDATOR._parse_simple_yaml(content) == {
            "owners": ["alice", "bob"]
        }

    def test_parse_simple_yaml_skips_comments_and_blanks(self):
        content = "# a comment\n\nname: x\n   \n# another\n"
        assert _CONTRACT_VALIDATOR._parse_simple_yaml(content) == {"name": "x"}

    def test_load_contract_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmpdir = Path(tmp)
            contract = {"sla": {"min_rows": 5}}
            path = _make_json(tmpdir, "contract.json", contract)
            assert _CONTRACT_VALIDATOR.load_contract(str(path)) == contract

    def test_load_contract_yaml(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmpdir = Path(tmp)
            path = tmpdir / "contract.yaml"
            path.write_text("sla:\n  min_rows: 5\n  max_rows: 100\n")
            assert _CONTRACT_VALIDATOR.load_contract(str(path)) == {
                "sla": {"min_rows": 5, "max_rows": 100}
            }


# ── ReportGenerator ────────────────────────────────────────────────


class TestReportGenerator:

    def _fixtures(self):
        profile = DQV.DataProfile(
            name="testds", row_count=2, column_count=1,
            columns=[
                DQV.ColumnProfile(
                    name="a", data_type="integer", total_count=2,
                    null_count=0, null_percentage=0.0,
                    unique_count=2, unique_percentage=100.0,
                    min_value=1.0, max_value=2.0, mean=1.5, median=1.5,
                ),
            ],
            duplicate_rows=0, memory_size_bytes=100,
            profile_timestamp="2024-01-01T00:00:00",
        )
        results = [
            DQV.ValidationResult("c1", "a", True, "x", "y"),
            DQV.ValidationResult("c2", "a", False, "x", "y",
                                 severity="error", message="boom"),
        ]
        score = DQV.QualityScore(
            completeness=100.0, uniqueness=100.0, validity=50.0,
            consistency=50.0, accuracy=50.0, overall=70.0,
        )
        return profile, results, score

    def test_text_report_sections(self):
        profile, results, score = self._fixtures()
        text = _REPORT_GENERATOR.generate_text_report(profile, results, score)
        assert "DATA QUALITY VALIDATION REPORT" in text
        assert "testds" in text
        assert "QUALITY SCORES" in text
        assert "VALIDATION SUMMARY" in text
        assert "FAILED CHECKS" in text
        assert "COLUMN PROFILES" in text
        assert "boom" in text

    def test_json_report_structure(self):
        profile, results, score = self._fixtures()
        report = _REPORT_GENERATOR.generate_json_report(profile, results, score)
        assert report["report_type"] == "data_quality_validation"
        assert report["dataset"]["name"] == "testds"
        assert report["dataset"]["row_count"] == 2
        assert report["dataset"]["column_count"] == 1
        assert report["dataset"]["duplicate_rows"] == 0
        assert report["dataset"]["memory_bytes"] == 100
        assert report["quality_score"] == DQV.asdict(score)
        assert report["validation_summary"] == {
            "total_checks": 2, "passed": 1, "failed": 1, "errors": 1, "warnings": 0,
        }
        assert report["validation_results"][0]["check"] == "c1"
        assert report["validation_results"][0]["passed"] is True
        assert report["column_profiles"][0]["name"] == "a"


# ── DataLoader ─────────────────────────────────────────────────────


class TestDataLoader:
    def test_load_csv(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = _make_csv(Path(tmp), "d.csv", "id,name", [(1, "alice"), (2, "bob")])
            assert DQV.DataLoader.load(str(path)) == [
                {"id": "1", "name": "alice"},
                {"id": "2", "name": "bob"},
            ]

    def test_load_json_list(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = _make_json(Path(tmp), "d.json", [{"id": 1}, {"id": 2}])
            assert DQV.DataLoader.load(str(path)) == [{"id": 1}, {"id": 2}]

    def test_load_json_object_with_data_key(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = _make_json(Path(tmp), "d.json", {"data": [{"id": 1}], "other": 5})
            assert DQV.DataLoader.load(str(path)) == [{"id": 1}]

    def test_load_json_object_without_data_key(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = _make_json(Path(tmp), "d.json", {"foo": 1})
            assert DQV.DataLoader.load(str(path)) == [{"foo": 1}]

    def test_load_json_scalar_raises(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = _make_json(Path(tmp), "d.json", "just a string")
            try:
                DQV.DataLoader.load(str(path))
            except ValueError as e:
                assert "JSON must contain array or object" in str(e)
            else:
                raise AssertionError("expected ValueError")

    def test_load_jsonl(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "d.jsonl"
            path.write_text('{"id": 1}\n{"id": 2}\n\n')
            assert DQV.DataLoader.load(str(path)) == [{"id": 1}, {"id": 2}]

    def test_load_missing_file_raises(self):
        try:
            DQV.DataLoader.load("/nonexistent/path/data.csv")
        except FileNotFoundError as e:
            assert "File not found" in str(e)
        else:
            raise AssertionError("expected FileNotFoundError")

    def test_load_unsupported_format_raises(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "d.txt"
            path.write_text("data")
            try:
                DQV.DataLoader.load(str(path))
            except ValueError as e:
                assert "Unsupported file format" in str(e)
            else:
                raise AssertionError("expected ValueError")


# ── SchemaLoader ───────────────────────────────────────────────────


class TestSchemaLoader:
    def test_load_full_schema(self):
        with tempfile.TemporaryDirectory() as tmp:
            schema_dict = {
                "name": "orders", "version": "2.0",
                "columns": [{
                    "name": "id", "type": "integer", "nullable": False,
                    "unique": True, "min_value": 0, "max_value": 100,
                    "pattern": r"^\d+$", "allowed_values": ["a"],
                    "description": "the id",
                }],
                "primary_key": ["id"], "row_count_min": 1, "row_count_max": 10,
            }
            path = _make_json(Path(tmp), "s.json", schema_dict)
            schema = DQV.SchemaLoader.load(str(path))
            assert schema.name == "orders"
            assert schema.version == "2.0"
            assert schema.primary_key == ["id"]
            assert schema.row_count_min == 1
            assert schema.row_count_max == 10
            col = schema.columns[0]
            assert col.name == "id"
            assert col.data_type == "integer"
            assert col.nullable is False
            assert col.unique is True
            assert col.min_value == 0
            assert col.max_value == 100
            assert col.pattern == r"^\d+$"
            assert col.allowed_values == ["a"]
            assert col.description == "the id"

    def test_load_schema_defaults(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = _make_json(Path(tmp), "s.json", {"columns": [{"name": "x"}]})
            schema = DQV.SchemaLoader.load(str(path))
            assert schema.name == "unknown"
            assert schema.version == "1.0"
            assert schema.columns[0].data_type == "string"
            assert schema.columns[0].nullable is True
            assert schema.columns[0].unique is False
            assert schema.primary_key is None


# ── CLI ────────────────────────────────────────────────────────────


class TestCli:
    def test_main_is_importable(self):
        assert callable(dqv_main)

    def test_no_command_exits_1(self):
        status, code = _run_main(["data_quality_validator.py"])
        assert status == "exit"
        assert code == 1

    def test_unknown_command_exits_2(self):
        status, code = _run_main(["data_quality_validator.py", "nope"])
        assert status == "exit"
        assert code == 2

    def test_validate_missing_input_arg_exits_2(self):
        status, code = _run_main(["data_quality_validator.py", "validate"])
        assert status == "exit"
        assert code == 2

    def test_contract_missing_contract_flag_exits_2(self):
        status, code = _run_main(["data_quality_validator.py", "contract", "x.csv"])
        assert status == "exit"
        assert code == 2

    def test_validate_missing_file_exits_1(self):
        status, code = _run_main(
            ["data_quality_validator.py", "validate", "/nonexistent/x.csv"]
        )
        assert status == "exit"
        assert code == 1

    def test_validate_valid_csv_succeeds(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = _make_csv(Path(tmp), "d.csv", "id", [(1,), (2,), (3,)])
            status, code = _run_main(["data_quality_validator.py", "validate", str(path)])
            assert status == "ok"
            assert code is None

    def test_validate_with_failing_schema_exits_1(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmpdir = Path(tmp)
            csv_path = _make_csv(tmpdir, "d.csv", "id", [("abc",), ("def",)])
            schema_path = _make_json(tmpdir, "s.json", {
                "name": "t", "version": "1.0",
                "columns": [{"name": "id", "type": "integer", "nullable": False}],
            })
            status, code = _run_main(
                ["data_quality_validator.py", "validate", str(csv_path),
                 "--schema", str(schema_path)]
            )
            assert status == "exit"
            assert code == 1

    def test_validate_detect_anomalies_flag_accepted(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmpdir = Path(tmp)
            rows = [(1,)] * 19 + [(1000,)]
            csv_path = _make_csv(tmpdir, "d.csv", "v", rows)
            status, code = _run_main(
                ["data_quality_validator.py", "validate", str(csv_path),
                 "--detect-anomalies"]
            )
            # anomalies are warnings, not errors, so validation still succeeds
            assert status == "ok"
            assert code is None

    def test_cmd_profile_prints_text(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = _make_csv(Path(tmp), "d.csv", "id", [(1,), (2,), (3,)])
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                DQV.cmd_profile(SimpleNamespace(
                    input=str(path), output=None, json=False))
            out = buf.getvalue()
            assert "Dataset: d" in out
            assert "Rows: 3" in out

    def test_cmd_profile_json_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = _make_csv(Path(tmp), "d.csv", "id", [(1,), (2,)])
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                DQV.cmd_profile(SimpleNamespace(
                    input=str(path), output=None, json=True))
            profile = json.loads(buf.getvalue())
            assert profile["name"] == "d"
            assert profile["row_count"] == 2
            assert profile["column_count"] == 1

    def test_cmd_generate_suite_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = _make_csv(Path(tmp), "d.csv", "id", [(1,), (2,)])
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                DQV.cmd_generate_suite(SimpleNamespace(input=str(path), output=None))
            suite = json.loads(buf.getvalue())
            assert suite["expectation_suite_name"] == "d_suite"
            assert "expectations" in suite

    def test_cmd_schema_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = _make_csv(Path(tmp), "d.csv", "id", [(1,), (2,), (3,)])
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                DQV.cmd_schema(SimpleNamespace(input=str(path), output=None))
            schema = json.loads(buf.getvalue())
            assert schema["name"] == "d"
            assert schema["columns"][0]["name"] == "id"
            assert schema["columns"][0]["type"] == "integer"

    def test_cmd_contract_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmpdir = Path(tmp)
            csv_path = _make_csv(tmpdir, "d.csv", "id", [(1,), (2,), (3,)])
            contract_path = _make_json(tmpdir, "c.json", {
                "schema": {"columns": [{"name": "id", "type": "integer"}]},
            })
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                DQV.cmd_contract(SimpleNamespace(
                    input=str(csv_path), contract=str(contract_path),
                    output=None, json=False))
            assert "DATA QUALITY VALIDATION REPORT" in buf.getvalue()

    def test_cmd_profile_logs_loading_message(self):
        handler = _ListHandler()
        logger = DQV.logger
        old_propagate = logger.propagate
        logger.addHandler(handler)
        logger.propagate = False
        try:
            with tempfile.TemporaryDirectory() as tmp:
                path = _make_csv(Path(tmp), "d.csv", "id", [(1,)])
                with contextlib.redirect_stdout(io.StringIO()):
                    DQV.cmd_profile(SimpleNamespace(
                        input=str(path), output=None, json=False))
            messages = [r.getMessage() for r in handler.records]
            assert any("Loading data from" in m for m in messages)
        finally:
            logger.removeHandler(handler)
            logger.propagate = old_propagate


# ── Test runner ────────────────────────────────────────────────────


def main() -> int:
    classes = [
        TestDataclasses,
        TestTypeDetector,
        TestSchemaValidatorType,
        TestSchemaValidator,
        TestSchemaValidatorHelpers,
        TestAnomalyDetector,
        TestDataProfiler,
        TestGreatExpectationsGenerator,
        TestQualityScoreCalculator,
        TestDataContractValidator,
        TestReportGenerator,
        TestDataLoader,
        TestSchemaLoader,
        TestCli,
    ]
    total = 0
    passed = 0
    failures = []
    for cls in classes:
        for name in sorted(dir(cls)):
            if not name.startswith("test_"):
                continue
            total += 1
            try:
                getattr(cls(), name)()
                passed += 1
            except Exception as e:  # noqa: BLE001
                failures.append(f"{cls.__name__}.{name}: {e!r}")
    print(f"{passed}/{total} tests passed")
    for f in failures:
        print("FAIL", f)
    return 0 if not failures else 1


if __name__ == "__main__":
    import sys as _sys

    _sys.exit(main())

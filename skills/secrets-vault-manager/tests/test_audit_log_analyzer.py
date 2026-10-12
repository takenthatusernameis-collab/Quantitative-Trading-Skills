#!/usr/bin/env python3
"""Unit tests for audit_log_analyzer.py."""

import json
import sys
import tempfile
import traceback
from pathlib import Path

SKILLS_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SKILLS_DIR / "scripts"))

from audit_log_analyzer import (
    load_logs,
    extract_fields,
    analyze,
    print_human,
    SAMPLE_ENTRIES,
)


def test_load_logs_empty():
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        f.write("")
        fname = f.name
    try:
        entries = load_logs(fname)
        assert entries == []
    finally:
        Path(fname).unlink()


def test_load_logs_json_array():
    data = [{"timestamp": "2026-01-01T00:00:00Z", "msg": "test"}]
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        json.dump(data, f)
        fname = f.name
    try:
        entries = load_logs(fname)
        assert entries == data
    finally:
        Path(fname).unlink()


def test_load_logs_json_lines():
    lines = [
        '{"timestamp": "2026-01-01T00:00:00Z", "msg": "first"}\n',
        '{"timestamp": "2026-01-01T00:00:01Z", "msg": "second"}\n',
    ]
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        f.writelines(lines)
        fname = f.name
    try:
        entries = load_logs(fname)
        assert len(entries) == 2
        assert entries[0]["msg"] == "first"
        assert entries[1]["msg"] == "second"
    finally:
        Path(fname).unlink()


def test_load_logs_with_malformed_line():
    lines = [
        '{"timestamp": "2026-01-01T00:00:00Z", "msg": "good"}\n',
        'bad json line\n',
        '{"timestamp": "2026-01-01T00:00:01Z", "msg": "good2"}\n',
    ]
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        f.writelines(lines)
        fname = f.name
    try:
        entries = load_logs(fname)
        # Should skip the malformed line
        assert len(entries) == 2
        assert entries[0]["msg"] == "good"
        assert entries[1]["msg"] == "good2"
    finally:
        Path(fname).unlink()


def test_extract_fields_basic():
    entry = {
        "timestamp": "2026-03-20T14:32:00Z",
        "type": "request",
        "auth": {"accessor": "token-abc123", "entity_id": "eid-001", "display_name": "approle-payment-svc"},
        "request": {"path": "secret/data/production/payment/api-keys", "operation": "read"},
        "response": {"status_code": 200},
        "remote_address": "10.0.1.15",
    }
    fields = extract_fields(entry)
    assert fields["timestamp"] is not None
    assert fields["hour"] == 14
    assert fields["identity"] == "approle-payment-svc"
    assert fields["path"] == "secret/data/production/payment/api-keys"
    assert fields["operation"] == "read"
    assert fields["status_code"] == 200
    assert fields["remote_address"] == "10.0.1.15"
    assert fields["entry_type"] == "request"


def test_extract_fields_missing():
    entry = {}
    fields = extract_fields(entry)
    assert fields["timestamp"] is None
    assert fields["hour"] is None
    assert fields["identity"] == "unknown"
    assert fields["path"] == "unknown"
    assert fields["operation"] == "unknown"
    assert fields["status_code"] is None
    assert fields["remote_address"] == "unknown"
    assert fields["entry_type"] == "unknown"


def test_extract_fields_alternative_keys():
    # Test with alternative key names
    entry = {
        "time": "2026-03-20T14:32:00Z",
        "auth": {"display_name": "test-user"},
        "path": "secret/test",
        "operation": "list",
        "status_code": 404,
        "source_address": "1.2.3.4",
        "type": "response",
    }
    fields = extract_fields(entry)
    assert fields["timestamp"] is not None
    assert fields["hour"] == 14
    assert fields["identity"] == "test-user"
    assert fields["path"] == "secret/test"
    assert fields["operation"] == "list"
    assert fields["status_code"] == 404
    assert fields["remote_address"] == "1.2.3.4"
    assert fields["entry_type"] == "response"


def test_analyze_with_sample_entries():
    result = analyze(SAMPLE_ENTRIES, threshold=2)
    # Check that we got a result with expected keys
    assert "summary" in result
    assert "anomalies" in result
    assert "top_accessed_paths" in result
    assert "hourly_distribution" in result
    # The sample entries should produce some anomalies
    assert result["summary"]["anomalies_found"] > 0


def test_analyze_threshold():
    # With high threshold, should detect fewer anomalies
    result_high = analyze(SAMPLE_ENTRIES, threshold=10)
    result_low = analyze(SAMPLE_ENTRIES, threshold=1)
    assert result_low["summary"]["anomalies_found"] >= result_high["summary"]["anomalies_found"]


def test_print_human_runs():
    # Just ensure it doesn't crash; we can't easily test stdout without capturing
    result = analyze(SAMPLE_ENTRIES, threshold=2)
    try:
        print_human(result, threshold=2)
    except Exception as e:
        print(f"print_human raised: {e}")
        raise


def test_main_with_sample():
    # We'll test the main function by importing it and calling with sys.argv manipulation
    from audit_log_analyzer import main
    # Backup sys.argv
    old_argv = sys.argv[:]
    try:
        sys.argv = ["audit_log_analyzer.py", "--sample"]
        # We expect main to run without error (exit code 0) or return normally
        try:
            main()
        except SystemExit as e:
            # If it exits, the code should be 0
            assert e.code == 0, f"Expected exit code 0, got {e.code}"
        # If it returns normally, that's also fine.
    finally:
        sys.argv = old_argv


def main() -> int:
    tests = [
        ("load_logs_empty", test_load_logs_empty),
        ("load_logs_json_array", test_load_logs_json_array),
        ("load_logs_json_lines", test_load_logs_json_lines),
        ("load_logs_with_malformed_line", test_load_logs_with_malformed_line),
        ("extract_fields_basic", test_extract_fields_basic),
        ("extract_fields_missing", test_extract_fields_missing),
        ("extract_fields_alternative_keys", test_extract_fields_alternative_keys),
        ("analyze_with_sample_entries", test_analyze_with_sample_entries),
        ("analyze_threshold", test_analyze_threshold),
        ("print_human_runs", test_print_human_runs),
        ("main_with_sample", test_main_with_sample),
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
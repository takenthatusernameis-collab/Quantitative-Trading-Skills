#!/usr/bin/env python3
"""
Unit tests for security/audit_logger.py: structured JSON audit logging with rotation.

Run with: python3 skills/cortex-code/tests/test_audit_logger.py
No third-party test framework is required; uses only the standard library.
"""

import json
import os
import sys
import tempfile
import traceback
from pathlib import Path

SKILLS_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SKILLS_DIR / "security"))

from audit_logger import AuditLogger  # noqa: E402


def test_log_execution_returns_audit_id():
    """log_execution must return a UUID string."""
    with tempfile.TemporaryDirectory() as tmp:
        al = AuditLogger(Path(tmp) / "audit.log")
        audit_id = al.log_execution(
            event_type="test",
            user="user",
            routing={},
            execution={},
            result={},
        )
        assert isinstance(audit_id, str)
        assert len(audit_id) > 0


def test_log_writes_json_line():
    """Each log_execution call must append a single JSON line."""
    with tempfile.TemporaryDirectory() as tmp:
        log_path = Path(tmp) / "audit.log"
        al = AuditLogger(log_path)
        al.log_execution("test", "user", {}, {}, {})
        with open(log_path, "r") as f:
            lines = [l for l in f if l.strip()]
        assert len(lines) == 1
        entry = json.loads(lines[0])
        assert entry["event_type"] == "test"
        assert entry["user"] == "user"
        assert "entry_hash" in entry
        assert "prev_hash" in entry


def test_entry_hash_chaining():
    """Each entry's prev_hash must match the previous entry's entry_hash."""
    with tempfile.TemporaryDirectory() as tmp:
        log_path = Path(tmp) / "audit.log"
        al = AuditLogger(log_path)
        al.log_execution("e1", "u", {}, {}, {})
        al.log_execution("e2", "u", {}, {}, {})
        with open(log_path, "r") as f:
            entries = [json.loads(l) for l in f if l.strip()]
        assert len(entries) == 2
        assert entries[1]["prev_hash"] == entries[0]["entry_hash"]
        assert entries[1]["entry_hash"] != entries[0]["entry_hash"]


def test_parse_size_kb():
    """_parse_size must correctly parse KB suffixes."""
    with tempfile.TemporaryDirectory() as tmp:
        al = AuditLogger(Path(tmp) / "audit.log")
        assert al._parse_size("10KB") == 10 * 1024
        assert al._parse_size("1MB") == 1024 * 1024
        assert al._parse_size("2GB") == 2 * 1024 * 1024 * 1024


def test_parse_size_default():
    """_parse_size must fall back to 10MB for unparseable values."""
    with tempfile.TemporaryDirectory() as tmp:
        al = AuditLogger(Path(tmp) / "audit.log")
        assert al._parse_size("garbage") == 10 * 1024 * 1024
        assert al._parse_size("123") == 123


def test_rotation_when_size_exceeded():
    """When the log exceeds rotation_size, the file must be renamed."""
    with tempfile.TemporaryDirectory() as tmp:
        log_path = Path(tmp) / "audit.log"
        # Small rotation threshold for testing
        al = AuditLogger(log_path, rotation_size="1B")
        al.log_execution("e1", "u", {}, {}, {})
        al.log_execution("e2", "u", {}, {}, {})
        # After rotation, the original path should be a new file
        assert log_path.exists()
        # At least one rotated file should exist
        rotated = list(Path(tmp).glob("audit.*.log"))
        assert len(rotated) >= 1


def test_log_file_created_with_restrictive_permissions():
    """The audit log file must be created with 0600 permissions."""
    with tempfile.TemporaryDirectory() as tmp:
        log_path = Path(tmp) / "audit.log"
        AuditLogger(log_path)
        mode = log_path.stat().st_mode & 0o777
        assert mode == 0o600, f"expected 0600, got {oct(mode)}"


def test_multiple_log_entries():
    """Multiple log_execution calls must produce multiple lines."""
    with tempfile.TemporaryDirectory() as tmp:
        log_path = Path(tmp) / "audit.log"
        al = AuditLogger(log_path)
        for i in range(5):
            al.log_execution(f"e{i}", "u", {}, {}, {})
        with open(log_path, "r") as f:
            lines = [l for l in f if l.strip()]
        assert len(lines) == 5


def test_log_entry_contains_required_fields():
    """Every entry must contain timestamp, version, audit_id, event_type, user."""
    with tempfile.TemporaryDirectory() as tmp:
        log_path = Path(tmp) / "audit.log"
        al = AuditLogger(log_path)
        al.log_execution("test", "alice", {"k": "v"}, {"x": 1}, {"ok": True})
        with open(log_path, "r") as f:
            entry = json.loads(f.readline())
        for field in ("timestamp", "version", "audit_id", "event_type", "user",
                       "routing", "execution", "result"):
            assert field in entry, f"missing field: {field}"
        assert entry["event_type"] == "test"
        assert entry["user"] == "alice"


def main() -> int:
    tests = [
        ("log_execution_returns_audit_id", test_log_execution_returns_audit_id),
        ("log_writes_json_line", test_log_writes_json_line),
        ("entry_hash_chaining", test_entry_hash_chaining),
        ("parse_size_kb", test_parse_size_kb),
        ("parse_size_default", test_parse_size_default),
        ("rotation_when_size_exceeded", test_rotation_when_size_exceeded),
        ("log_file_created_with_restrictive_permissions", test_log_file_created_with_restrictive_permissions),
        ("multiple_log_entries", test_multiple_log_entries),
        ("log_entry_contains_required_fields", test_log_entry_contains_required_fields),
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
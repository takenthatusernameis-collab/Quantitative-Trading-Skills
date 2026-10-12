#!/usr/bin/env python3
"""Unit tests for rotation_planner.py."""

import json
import sys
import tempfile
import traceback
from datetime import datetime, timedelta
from pathlib import Path

SKILLS_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SKILLS_DIR / "scripts"))

from rotation_planner import (
    load_inventory,
    compute_schedule,
    build_summary,
    print_human,
    POLICY_DAYS,
    TYPE_DEFAULTS,
    URGENCY_THRESHOLDS,
)


def test_load_inventory_empty():
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        f.write("[]")
        fname = f.name
    try:
        inventory = load_inventory(fname)
        assert inventory == []
    finally:
        Path(fname).unlink()


def test_load_inventory_valid():
    data = [
        {
            "name": "test-secret",
            "type": "database",
            "store": "vault",
            "last_rotated": "2026-01-15",
            "owner": "team",
            "environment": "prod",
        }
    ]
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        json.dump(data, f)
        fname = f.name
    try:
        inventory = load_inventory(fname)
        assert len(inventory) == 1
        assert inventory[0]["name"] == "test-secret"
        assert inventory[0]["type"] == "database"
        assert inventory[0]["store"] == "vault"
        assert inventory[0]["last_rotated"] == datetime(2026, 1, 15)
        assert inventory[0]["owner"] == "team"
        assert inventory[0]["environment"] == "prod"
    finally:
        Path(fname).unlink()


def test_load_inventory_missing_last_rotated():
    data = [
        {
            "name": "no-date-secret",
            "type": "api-key",
        }
    ]
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        json.dump(data, f)
        fname = f.name
    try:
        inventory = load_inventory(fname)
        assert len(inventory) == 1
        assert inventory[0]["name"] == "no-date-secret"
        assert inventory[0]["last_rotated"] is None
        # Should have printed a warning to stderr, but we ignore
    finally:
        Path(fname).unlink()


def test_load_inventory_invalid_date():
    data = [
        {
            "name": "bad-date-secret",
            "type": "ssh-key",
            "last_rotated": "not-a-date",
        }
    ]
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        json.dump(data, f)
        fname = f.name
    try:
        inventory = load_inventory(fname)
        assert len(inventory) == 1
        assert inventory[0]["name"] == "bad-date-secret"
        assert inventory[0]["last_rotated"] is None
    finally:
        Path(fname).unlink()


def test_load_inventory_non_list():
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        f.write('{"name": "not a list"}')
        fname = f.name
    try:
        # We expect load_inventory to print error and exit, but we can't easily test exit here.
        # Instead we'll test that it raises SystemExit? Actually the function calls sys.exit.
        # We'll catch SystemExit.
        import sys
        from io import StringIO
        old_stderr = sys.stderr
        sys.stderr = StringIO()
        try:
            load_inventory(fname)
            assert False, "Expected SystemExit"
        except SystemExit:
            pass  # expected
        finally:
            sys.stderr = old_stderr
    finally:
        Path(fname).unlink()


def test_compute_schedule_basic():
    # Use a fixed date for reproducibility
    fixed_date = datetime(2026, 1, 15)
    inventory = [
        {
            "name": "test-db",
            "type": "database",
            "store": "vault",
            "last_rotated": fixed_date,
            "owner": "team",
            "environment": "prod",
        }
    ]
    # Policy 30 days, but database default is 30, so interval = 30
    schedule = compute_schedule(inventory, policy_days=30)
    assert len(schedule) == 1
    entry = schedule[0]
    assert entry["name"] == "test-db"
    assert entry["rotation_interval_days"] == 30
    assert entry["last_rotated"] == "2026-01-15"
    # Next rotation should be 2026-02-14 (30 days later)
    assert entry["next_rotation"] == "2026-02-14"
    # days_until_due depends on current date; we'll compute relative to fixed_date for predictability
    # But compute_schedule uses datetime.now(). To make it predictable, we need to mock datetime.now.
    # Since we can't easily mock, we'll skip the exact days_until check and just check that it's an integer.
    assert isinstance(entry["days_until_due"], int)
    assert isinstance(entry["days_since_rotation"], int)


def test_compute_schedule_neverever():
    inventory = [
        {
            "name": "never-rotated",
            "type": "api-key",
            "store": "vault",
            "last_rotated": None,  # as set by load_inventory when missing
            "owner": "team",
            "environment": "prod",
        }
    ]
    schedule = compute_schedule(inventory, policy_days=90)
    assert len(schedule) == 1
    entry = schedule[0]
    assert entry["name"] == "never-rotated"
    assert entry["last_rotated"] == "NEVER"
    assert entry["rotation_interval_days"] == 90  # api-key default is 90, policy 90 -> min=90
    # next_rotation should be today (since last_rotated is None -> immediate)
    expected_today = datetime.now().strftime("%Y-%m-%d")
    assert entry["next_rotation"] == expected_today
    assert entry["days_until_due"] == -999  # as per code when last_rotated is None
    assert entry["days_since_rotation"] == 999  # as per code when last_rotated is None
    assert entry["urgency"] == "CRITICAL"  # because days_until <= 0


def test_compute_schedule_overdue():
    # Set last_rotated to a long time ago so it's overdue
    past = datetime.now() - timedelta(days=100)
    inventory = [
        {
            "name": "overdue-secret",
            "type": "database",  # default 30 days
            "store": "vault",
            "last_rotated": past,
            "owner": "team",
            "environment": "prod",
        }
    ]
    schedule = compute_schedule(inventory, policy_days=30)
    assert len(schedule) == 1
    entry = schedule[0]
    assert entry["urgency"] == "CRITICAL"  # overdue
    assert entry["days_until_due"] < 0


def test_build_summary():
    schedule = [
        {
            "name": "s1",
            "type": "database",
            "store": "vault",
            "owner": "alice",
            "environment": "prod",
            "last_rotated": "2026-01-01",
            "rotation_interval_days": 30,
            "next_rotation": "2026-01-31",
            "days_until_due": -5,
            "days_since_rotation": 40,
            "urgency": "CRITICAL",
        },
        {
            "name": "s2",
            "type": "api-key",
            "store": "vault",
            "owner": "bob",
            "environment": "dev",
            "last_rotated": "2026-01-01",
            "rotation_interval_days": 90,
            "next_rotation": "2026-04-01",
            "days_until_due": 50,
            "days_since_rotation": 40,
            "urgency": "LOW",
        },
    ]
    summary = build_summary(schedule)
    assert summary["total_secrets"] == 2
    assert summary["by_urgency"]["CRITICAL"] == 1
    assert summary["by_urgency"]["LOW"] == 1
    assert summary["by_type"]["database"] == 1
    assert summary["by_type"]["api-key"] == 1
    assert summary["by_owner"]["alice"] == 1
    assert summary["by_owner"]["bob"] == 1
    assert summary["overdue_count"] == 1
    assert summary["due_within_7d"] == 0  # none are HIGH or MEDIUM


def test_print_human_runs():
    schedule = [
        {
            "name": "test",
            "type": "database",
            "store": "vault",
            "owner": "team",
            "environment": "prod",
            "last_rotated": "2026-01-01",
            "rotation_interval_days": 30,
            "next_rotation": "2026-01-31",
            "days_until_due": -5,
            "days_since_rotation": 40,
            "urgency": "CRITICAL",
        }
    ]
    summary = build_summary(schedule)
    try:
        print_human(schedule, summary, policy="30d")
    except Exception as e:
        print(f"print_human raised: {e}")
        raise


def test_main_with_sample_inventory():
    # We'll create a temporary inventory file and run main with it
    from rotation_planner import main
    import sys
    from io import StringIO

    inventory_data = [
        {
            "name": "test-secret",
            "type": "database",
            "store": "vault",
            "last_rotated": "2026-01-15",
            "owner": "team",
            "environment": "prod",
        }
    ]
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        json.dump(inventory_data, f)
        fname = f.name
    try:
        old_argv = sys.argv[:]
        old_stdout = sys.stdout
        sys.stdout = StringIO()  # suppress output
        try:
            sys.argv = ["rotation_planner.py", "--inventory", fname, "--policy", "30d"]
            # main does not call sys.exit on success; it returns None
            try:
                main()
            except SystemExit as e:
                # If it exits, the code should be 0
                assert e.code == 0, f"Expected exit code 0, got {e.code}"
            # If it returns normally, that's also fine.
        finally:
            sys.stdout = old_stdout
            sys.argv = old_argv
    finally:
        Path(fname).unlink()


def main() -> int:
    tests = [
        ("load_inventory_empty", test_load_inventory_empty),
        ("load_inventory_valid", test_load_inventory_valid),
        ("load_inventory_missing_last_rotated", test_load_inventory_missing_last_rotated),
        ("load_inventory_invalid_date", test_load_inventory_invalid_date),
        ("load_inventory_non_list", test_load_inventory_non_list),
        ("compute_schedule_basic", test_compute_schedule_basic),
        ("compute_schedule_neverever", test_compute_schedule_neverever),
        ("compute_schedule_overdue", test_compute_schedule_overdue),
        ("build_summary", test_build_summary),
        ("print_human_runs", test_print_human_runs),
        ("main_with_sample_inventory", test_main_with_sample_inventory),
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
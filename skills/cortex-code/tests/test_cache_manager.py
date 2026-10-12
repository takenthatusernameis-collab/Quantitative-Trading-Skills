#!/usr/bin/env python3
"""
Unit tests for security/cache_manager.py: secure cache with integrity validation.

Run with: python3 skills/cortex-code/tests/test_cache_manager.py
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

from cache_manager import CacheManager  # noqa: E402


def test_write_and_read_roundtrip():
    """Writing then reading must return the original data."""
    with tempfile.TemporaryDirectory() as tmp:
        cm = CacheManager(Path(tmp))
        cm.write("mykey", {"a": 1, "b": [1, 2, 3]}, ttl=3600)
        assert cm.read("mykey") == {"a": 1, "b": [1, 2, 3]}


def test_read_missing_key_returns_none():
    """Reading a nonexistent key must return None."""
    with tempfile.TemporaryDirectory() as tmp:
        cm = CacheManager(Path(tmp))
        assert cm.read("does-not-exist") is None


def test_invalid_key_rejected():
    """Keys with path traversal or special characters must be rejected."""
    with tempfile.TemporaryDirectory() as tmp:
        cm = CacheManager(Path(tmp))
        for bad_key in ["../escape", "with space", "slash/in/key", "dot..dot"]:
            try:
                cm.write(bad_key, {})
                assert False, f"Expected ValueError for key: {bad_key}"
            except ValueError:
                pass  # expected


def test_empty_key_rejected():
    """An empty cache key must be rejected."""
    with tempfile.TemporaryDirectory() as tmp:
        cm = CacheManager(Path(tmp))
        try:
            cm.write("", {})
            assert False, "Expected ValueError for empty key"
        except ValueError:
            pass


def test_expired_entry_returns_none():
    """An entry with a TTL of 0 (already expired) must return None on read."""
    with tempfile.TemporaryDirectory() as tmp:
        cm = CacheManager(Path(tmp))
        cm.write("expiring", {"v": 1}, ttl=0)
        # Give a tiny moment for time.time() to advance if needed
        import time
        time.sleep(0.01)
        assert cm.read("expiring") is None


def test_tampered_data_returns_none():
    """If the cached JSON is modified, read must return None and delete the file."""
    with tempfile.TemporaryDirectory() as tmp:
        cm = CacheManager(Path(tmp))
        cm.write("tamper", {"v": 1}, ttl=3600)
        cache_file = Path(tmp) / "tamper.json"
        assert cache_file.exists()
        with open(cache_file, "r") as f:
            entry = json.load(f)
        entry["data"] = {"v": 2}  # tamper
        with open(cache_file, "w") as f:
            json.dump(entry, f)
        assert cm.read("tamper") is None
        assert not cache_file.exists(), "tampered file should be deleted"


def test_clear_single_key():
    """clear(key) must remove only that key."""
    with tempfile.TemporaryDirectory() as tmp:
        cm = CacheManager(Path(tmp))
        cm.write("keep", {"v": 1}, ttl=3600)
        cm.write("drop", {"v": 2}, ttl=3600)
        cm.clear("drop")
        assert cm.read("keep") == {"v": 1}
        assert cm.read("drop") is None


def test_clear_all_keys():
    """clear() with no argument must remove all cache files."""
    with tempfile.TemporaryDirectory() as tmp:
        cm = CacheManager(Path(tmp))
        cm.write("a", {"v": 1}, ttl=3600)
        cm.write("b", {"v": 2}, ttl=3600)
        cm.clear()
        assert cm.read("a") is None
        assert cm.read("b") is None


def test_file_permissions_are_restrictive():
    """Cached files must be created with 0600 permissions."""
    with tempfile.TemporaryDirectory() as tmp:
        cm = CacheManager(Path(tmp))
        cm.write("perm", {"v": 1}, ttl=3600)
        cache_file = Path(tmp) / "perm.json"
        mode = cache_file.stat().st_mode & 0o777
        assert mode == 0o600, f"expected 0600, got {oct(mode)}"


def test_write_overwrites_existing_key():
    """Writing the same key twice must overwrite the previous entry."""
    with tempfile.TemporaryDirectory() as tmp:
        cm = CacheManager(Path(tmp))
        cm.write("k", {"v": 1}, ttl=3600)
        cm.write("k", {"v": 2}, ttl=3600)
        assert cm.read("k") == {"v": 2}


def main() -> int:
    tests = [
        ("write_and_read_roundtrip", test_write_and_read_roundtrip),
        ("read_missing_key_returns_none", test_read_missing_key_returns_none),
        ("invalid_key_rejected", test_invalid_key_rejected),
        ("empty_key_rejected", test_empty_key_rejected),
        ("expired_entry_returns_none", test_expired_entry_returns_none),
        ("tampered_data_returns_none", test_tampered_data_returns_none),
        ("clear_single_key", test_clear_single_key),
        ("clear_all_keys", test_clear_all_keys),
        ("file_permissions_are_restrictive", test_file_permissions_are_restrictive),
        ("write_overwrites_existing_key", test_write_overwrites_existing_key),
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
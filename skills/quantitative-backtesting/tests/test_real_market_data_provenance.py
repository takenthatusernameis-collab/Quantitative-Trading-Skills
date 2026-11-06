#!/usr/bin/env python3
"""
Regression guard for the provenance of the committed real-market OHLCV fixtures
(skills/quantitative-backtesting/assets/example_data/real_market_data/).

These fixtures back the real-market falsification tests, so their identity is
methodologically load-bearing: if a fixture is silently swapped or regenerated,
the real-market verdicts change without anyone noticing. This test pins each
fixture to the committed PROVENANCE.json manifest (schema, date range, row
count, sha256) and re-asserts the documented byte-identity relationships.

No claim is made about any market or about strategy performance; the test only
guards that the fixtures on disk match their recorded provenance.

Run with: python3 skills/quantitative-backtesting/tests/test_real_market_data_provenance.py
Requires only the standard library, numpy and pandas.
"""

import hashlib
import json
import sys
import traceback
from pathlib import Path

import pandas as pd

SKILLS_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SKILLS_DIR / "scripts"))

from data_loader import load_data  # noqa: E402

FIXTURES_DIR = SKILLS_DIR / "assets" / "example_data" / "real_market_data"
PROVENANCE_PATH = FIXTURES_DIR / "PROVENANCE.json"
CANONICAL_COLUMNS = ["open", "high", "low", "close", "volume"]


def _load_provenance():
    with open(PROVENANCE_PATH, "r", encoding="utf-8") as fh:
        return json.load(fh)


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _bytes(path: Path) -> bytes:
    with open(path, "rb") as fh:
        return fh.read()


def test_provenance_manifest_exists_and_is_valid_json():
    """The committed manifest must exist and parse as JSON."""
    assert PROVENANCE_PATH.exists(), f"provenance manifest missing: {PROVENANCE_PATH}"
    prov = _load_provenance()
    assert isinstance(prov, dict)
    assert "fixtures" in prov and isinstance(prov["fixtures"], dict)
    assert "all_fixtures" in prov


def test_manifest_honest_source_note_not_fabricated():
    """The manifest must not assert an unverified upstream source/fetch date.

    The exact source URL and fetch date are intentionally left unasserted so no
    provenance is fabricated; the note must be present to make that choice
    explicit rather than silent.
    """
    prov = _load_provenance()
    note = prov.get("all_fixtures", {}).get("raw_source_note", "")
    assert "not independently re-verified" in note, "manifest must state source is not re-verified"
    assert "do not fabricate" in note.lower() or "not asserted" in note.lower(), (
        "manifest must explicitly decline to assert unverified source/fetch date"
    )


def _each_fixture_case():
    prov = _load_provenance()
    allf = prov["all_fixtures"]
    for name, meta in prov["fixtures"].items():
        yield name, meta, allf


def test_each_fixture_matches_manifest():
    """Every committed fixture must match its manifest entry: schema, index,
    date range, row count and sha256."""
    prov = _load_provenance()
    allf = prov["all_fixtures"]
    for name, meta, _allf in _each_fixture_case():
        path = FIXTURES_DIR / name
        assert path.exists(), f"fixture missing: {path}"
        df = load_data(str(path))
        # Schema: canonical OHLCV columns only.
        assert list(df.columns) == CANONICAL_COLUMNS, (
            f"{name} schema mismatch: {list(df.columns)}"
        )
        # Index: tz-naive DatetimeIndex, sorted ascending.
        assert isinstance(df.index, pd.DatetimeIndex), f"{name} index not DatetimeIndex"
        assert df.index.tz is None, f"{name} index is timezone-aware"
        assert df.index.is_monotonic_increasing, f"{name} index not sorted ascending"
        # Date range pinned to manifest.
        assert str(df.index.min().date()) == allf["start_date"], (
            f"{name} start date mismatch: {df.index.min().date()} != {allf['start_date']}"
        )
        assert str(df.index.max().date()) == allf["end_date"], (
            f"{name} end date mismatch: {df.index.max().date()} != {allf['end_date']}"
        )
        # Row count pinned to manifest.
        assert len(df) == allf["rows"], (
            f"{name} row count mismatch: {len(df)} != {allf['rows']}"
        )
        # sha256 pinned to manifest (catches silent regeneration/swap).
        assert _sha256(path) == meta["sha256"], (
            f"{name} sha256 mismatch: {_sha256(path)} != {meta['sha256']}"
        )


def test_documented_byte_identity_holds():
    """The manifest's documented byte-identity relationships must hold on disk."""
    prov = _load_provenance()
    rel = prov.get("byte_identity", {})
    assert rel.get("AAPL.csv == sample_ohlcv.csv") is True
    assert _bytes(FIXTURES_DIR / "AAPL.csv") == _bytes(FIXTURES_DIR / "sample_ohlcv.csv"), (
        "AAPL.csv and sample_ohlcv.csv must remain byte-identical"
    )
    assert rel.get("MSFT.csv == sample_benchmark.csv == AAPL.csv.bak") is True
    assert _bytes(FIXTURES_DIR / "MSFT.csv") == _bytes(FIXTURES_DIR / "sample_benchmark.csv"), (
        "MSFT.csv and sample_benchmark.csv must remain byte-identical"
    )


# ---------------------------------------------------------------------------
# Standalone runner (mirrors repo convention: TEST_REGISTRY + main()).
# ---------------------------------------------------------------------------

TEST_REGISTRY = [
    ("test_provenance_manifest_exists_and_is_valid_json", test_provenance_manifest_exists_and_is_valid_json),
    ("test_manifest_honest_source_note_not_fabricated", test_manifest_honest_source_note_not_fabricated),
    ("test_each_fixture_matches_manifest", test_each_fixture_matches_manifest),
    ("test_documented_byte_identity_holds", test_documented_byte_identity_holds),
]


def main() -> int:
    failures = 0
    for name, fn in TEST_REGISTRY:
        try:
            fn()
            print(f"PASS  {name}")
        except Exception:
            failures += 1
            print(f"FAIL  {name}")
            traceback.print_exc()
    print(f"\n{len(TEST_REGISTRY) - failures}/{len(TEST_REGISTRY)} tests passed")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""Methodology audit: the multi-symbol CSV load path must not deliver a
structural temporal violation to the point-in-time gate.

This is the end-to-end positive control for the invariant the gate-level test
`test_multi_symbol_pit_strict_abort_structural_violation_real_panel.py` relies
on. That test injects an unsorted DatetimeIndex into a *post-load* panel dict
and confirms the PIT enforcement gate aborts in strict mode. It cannot, however,
construct such a violation through the normal multi-symbol CSV load path, because
`load_data` sorts the index and `load_multi_symbol` drops symbols whose
per-symbol frame fails `validate_data`. This test records that invariant on the
committed AAPL/MSFT fixtures so that a future change that quietly removes the
sort or the data-quality drop is caught: the loader must normalize ordering and
must drop an invalid-duplicate symbol rather than passing a broken frame to the
downstream PIT gate.

Verified empirically (not asserted by hand):
  * an intentionally shuffled multi-symbol CSV loads to a monotonically
    increasing index (load_data sorts);
  * a multi-symbol CSV with a duplicate timestamp in one symbol's rows drops
    that symbol and warns, instead of returning a frame with duplicate dates.

Complements:
  - test_multi_symbol_pit_survivorship_real_panel.py (clean real panel, strict
    PIT passes end-to-end through the CLI).
  - test_multi_symbol_pit_strict_abort_structural_violation_real_panel.py (the
    gate-level strict-abort control on a post-load structural violation).

Offline, committed fixtures only. Audit of the load path, not a profitability
claim.
"""
import sys
import warnings
from pathlib import Path

import pandas as pd

SKILLS_DIR = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = SKILLS_DIR / "scripts"
REAL_DATA = SKILLS_DIR / "assets" / "example_data" / "real_market_data"
SYMBOLS = ["AAPL", "MSFT"]

sys.path.insert(0, str(SCRIPTS_DIR))

from data_loader import load_data, load_multi_symbol  # noqa: E402


def _shuffled_panel(path: Path) -> Path:
    """Multi-symbol CSV with every symbol's rows shuffled (unsorted CSV)."""
    frames = []
    for sym in SYMBOLS:
        df = pd.read_csv(REAL_DATA / f"{sym}.csv").head(200)
        df["symbol"] = sym
        df = df.sample(frac=1, random_state=0).reset_index(drop=True)
        frames.append(df)
    panel = pd.concat(frames, ignore_index=True)
    out = path / "shuffled_panel.csv"
    panel.to_csv(out, index=False)
    return out


def _duplicate_timestamp_panel(path: Path) -> Path:
    """Multi-symbol CSV where MSFT has a duplicated first row (duplicate dates)."""
    frames = []
    for sym in SYMBOLS:
        df = pd.read_csv(REAL_DATA / f"{sym}.csv").head(200)
        df["symbol"] = sym
        if sym == "MSFT":
            dup = df.iloc[[0]].copy()
            df = pd.concat([df, dup], ignore_index=True)
        frames.append(df)
    panel = pd.concat(frames, ignore_index=True)
    out = path / "dup_timestamp_panel.csv"
    panel.to_csv(out, index=False)
    return out


def test_loader_sorts_unsorted_multi_symbol_csv():
    """load_data must normalize a shuffled multi-symbol CSV to a monotonically
    increasing index so no structural ordering violation reaches the PIT gate."""
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        panel = _shuffled_panel(tmp)
        assert not panel.read_text().count("\n") == 0  # fixture is non-empty

        loaded = load_data(panel)
        assert isinstance(loaded.index, pd.DatetimeIndex)
        assert loaded.index.is_monotonic_increasing, (
            "load_data must sort the index; an unsorted CSV must not reach the "
            "PIT gate with a non-monotonic index"
        )
        assert len(loaded) == 200 * len(SYMBOLS)


def test_loader_drops_symbol_with_duplicate_timestamps():
    """load_multi_symbol must drop a symbol whose per-symbol frame has
    duplicate timestamps (a structural violation validate_data flags) and warn,
    rather than returning a broken frame to the PIT gate."""
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        panel = _duplicate_timestamp_panel(tmp)

        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            result, dropped = load_multi_symbol(panel, return_dropped=True)

        assert "AAPL" in result, f"AAPL should load cleanly, got {list(result.keys())}"
        assert "MSFT" not in result, (
            "MSFT has duplicate timestamps and must be dropped by load_multi_symbol"
        )
        assert "MSFT" in dropped, f"dropped list should name MSFT, got {dropped}"
        assert not result["AAPL"].index.duplicated().any(), (
            "AAPL frame must have no duplicate dates after load"
        )
        messages = " ".join(str(w.message) for w in caught).lower()
        assert "dropped" in messages, (
            f"load_multi_symbol must warn when dropping invalid symbols: {messages!r}"
        )


if __name__ == "__main__":
    test_loader_sorts_unsorted_multi_symbol_csv()
    print("PASS  test_loader_sorts_unsorted_multi_symbol_csv")
    test_loader_drops_symbol_with_duplicate_timestamps()
    print("PASS  test_loader_drops_symbol_with_duplicate_timestamps")
    print("OK")
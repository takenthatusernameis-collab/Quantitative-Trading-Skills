#!/usr/bin/env python3
"""Positive control: strict point-in-time enforcement must abort on a
structural (temporal ordering) violation in a multi-symbol/panel run.

Complements:
- test_multi_symbol_pit_survivorship_real_panel.py (strict PIT passes on a
  complete, aligned real panel — negative control).
- test_point_in_time_strict_abort_on_violation.py (strict abort on a
  look-ahead/signal-correlation violation, single-asset framing).

The multi-symbol PIT path in run_backtest validates each symbol frame for
structural violations (temporal ordering, duplicate timestamps). This test
derives a panel from committed AAPL/MSFT real fixtures and injects an
unsorted DatetimeIndex into one symbol frame (a structural violation that
validate_point_in_time deterministically flags). It asserts:
  1. run_backtest._validate_point_in_time detects the violation on the panel
     (passed=False, monotonic-ordering violation reported).
  2. run_backtest._handle_point_in_time_results(strict=True) signals abort,
     while warn-only does not abort — the same gate the CLI uses
     (--point-in-time-strict).

Note on loader behavior: load_data sorts indices and validate_data drops
symbols with duplicate timestamps, so injecting these structural violations
through the normal multi-symbol CSV load path is defeated by those
pre-processing/data-quality steps. This test exercises the PIT enforcement
gate on a real-data-derived panel (post-load representation) to verify the
control aborts when a structural violation is present — a control that does
not abort on a detected violation provides false assurance.

Offline, committed fixtures only. Audit of the PIT control, not a
profitability claim.
"""
import sys
from pathlib import Path

import pandas as pd

SKILLS_DIR = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = SKILLS_DIR / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

from run_backtest import _handle_point_in_time_results, _validate_point_in_time  # noqa: E402

REAL_DATA = SKILLS_DIR / "assets" / "example_data" / "real_market_data"


def _load_real_indexed(symbol: str, n: int = 400) -> pd.DataFrame:
    df = pd.read_csv(REAL_DATA / f"{symbol}.csv").head(n)
    df["Date"] = pd.to_datetime(df["Date"] if "Date" in df.columns else df["date"])
    df = df.set_index("Date").sort_index()
    # normalize column names to what the stack expects
    df.columns = [c.lower() for c in df.columns]
    return df[["open", "high", "low", "close", "volume"]]


def _unsorted_panel():
    """Panel dict (multi-symbol, post-load form) with MSFT index unsorted."""
    aapl = _load_real_indexed("AAPL")
    msft = _load_real_indexed("MSFT")
    # Inject structural violation: swap two index entries to break monotonicity.
    idx = list(msft.index)
    idx[10], idx[11] = idx[11], idx[10]
    msft_bad = msft.copy()
    msft_bad.index = pd.DatetimeIndex(idx)
    return {"AAPL": aapl, "MSFT": msft_bad}


def test_multi_symbol_pit_detects_structural_ordering_violation():
    """Panel PIT validation must flag an unsorted DatetimeIndex in one symbol
    frame (structural/ordering violation) rather than passing silently."""
    panel = _unsorted_panel()
    pit = _validate_point_in_time(panel, signals=None)
    assert pit["passed"] is False, (
        f"unsorted panel index was not detected as a PIT violation: {pit}"
    )
    assert pit["violations"], f"expected violations, got {pit}"
    combined = " ".join(pit["violations"]).lower()
    assert "monotonic" in combined or "order" in combined or "increasing" in combined, (
        f"violation text did not indicate ordering/monotonicity: {pit['violations']}"
    )


def test_multi_symbol_pit_strict_aborts_on_structural_violation():
    """Strict mode must abort on the detected structural violation; warn-only
    must not abort — the same CLI gate used for --multi-symbol runs."""
    panel = _unsorted_panel()
    pit = _validate_point_in_time(panel, signals=None)
    assert pit["passed"] is False  # precondition

    # Warn-only: detected but not aborting.
    assert _handle_point_in_time_results(pit, strict=False) is False
    # Strict: must signal abort.
    assert _handle_point_in_time_results(pit, strict=True) is True


def test_multi_symbol_pit_clean_panel_not_aborted():
    """Negative control on the same gate: a clean, sorted real panel must not
    trigger strict abort."""
    panel = {"AAPL": _load_real_indexed("AAPL"), "MSFT": _load_real_indexed("MSFT")}
    pit = _validate_point_in_time(panel, signals=None)
    assert pit["passed"] is True, f"clean real panel flagged: {pit}"
    assert _handle_point_in_time_results(pit, strict=True) is False


if __name__ == "__main__":
    test_multi_symbol_pit_detects_structural_ordering_violation()
    print("PASS  test_multi_symbol_pit_detects_structural_ordering_violation")
    test_multi_symbol_pit_strict_aborts_on_structural_violation()
    print("PASS  test_multi_symbol_pit_strict_aborts_on_structural_violation")
    test_multi_symbol_pit_clean_panel_not_aborted()
    print("PASS  test_multi_symbol_pit_clean_panel_not_aborted")
    print("OK")

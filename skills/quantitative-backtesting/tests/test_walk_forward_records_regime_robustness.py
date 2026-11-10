#!/usr/bin/env python3
"""Regression guard: walk-forward / CPCV / Monte Carlo disclose regime robustness.

The walk-forward, CPCV and Monte Carlo analysis paths now surface
`summary["regime_robustness"]` (the regime-concentration diagnostic) alongside
`summary["regime_analysis"]`, so a consumer can see whether the edge is
diversified across regimes or concentrated in a single one. Mirrors
`test_cpcv_records_regime_analysis` and `test_run_backtest_records_regime_analysis`.

Offline, committed fixtures only; no live network.
"""
import contextlib
import io
import sys
from pathlib import Path

import pandas as pd

SKILLS_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SKILLS_DIR / "scripts"))

from walk_forward import walk_forward_analysis, cpcv_analysis, _make_strategy_factory  # noqa: E402

SAMPLE_DATA = SKILLS_DIR / "assets" / "example_data" / "sample_ohlcv.csv"

MEANINGFUL_GRID = {"fast_period": [5, 10], "slow_period": [20, 30]}

VALID_CLASSIFICATIONS = ("robust", "moderate", "fragile", "insufficient_data")


def _load_data():
    return pd.read_csv(SAMPLE_DATA, parse_dates=["date"]).set_index("date").sort_index()


def _assert_regime_robustness(rr, label):
    assert isinstance(rr, dict), f"{label}: regime_robustness must be a dict, got {type(rr)}"
    assert "regime_robustness" in rr, f"{label}: regime_robustness dict missing classification key"
    assert rr["regime_robustness"] in VALID_CLASSIFICATIONS, (
        f"{label}: unexpected classification {rr['regime_robustness']!r}"
    )


def test_walk_forward_records_regime_robustness():
    """walk_forward_analysis summary carries regime_robustness next to regime_analysis."""
    assert SAMPLE_DATA.exists(), f"missing committed fixture {SAMPLE_DATA}"
    data = _load_data()
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        result = walk_forward_analysis(
            data=data,
            strategy_factory=_make_strategy_factory("sma_crossover"),
            param_grid=MEANINGFUL_GRID,
            train_months=12,
            test_months=3,
            step_months=3,
            initial_capital=100000,
            commission=0.0002,
            slippage=0.0001,
            validate_pit=False,
        )
    summary = result["summary"]
    assert "regime_robustness" in summary, "walk-forward summary must carry regime_robustness"
    _assert_regime_robustness(summary["regime_robustness"], "walk_forward_analysis")


def test_cpcv_records_regime_robustness():
    """cpcv_analysis summary carries regime_robustness next to regime_analysis."""
    assert SAMPLE_DATA.exists(), f"missing committed fixture {SAMPLE_DATA}"
    data = _load_data()
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        result = cpcv_analysis(
            data=data,
            strategy_factory=_make_strategy_factory("sma_crossover"),
            param_grid=MEANINGFUL_GRID,
            n_splits=5,
            test_size=0.2,
        )
    summary = result["summary"]
    assert "regime_robustness" in summary, "CPCV summary must carry regime_robustness"
    _assert_regime_robustness(summary["regime_robustness"], "cpcv_analysis")


if __name__ == "__main__":
    for name in sorted(globals()):
        if name.startswith("test_") and callable(globals()[name]):
            try:
                globals()[name]()
                print(f"PASS {name}")
            except Exception:  # noqa: BLE001
                import traceback
                traceback.print_exc()
                print(f"FAIL {name}")
    print("OK")

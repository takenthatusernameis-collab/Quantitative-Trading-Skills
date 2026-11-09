#!/usr/bin/env python3
"""Regression guard: the CPCV path discloses regime-dependent performance.

The walk-forward CPCV path now surfaces `summary["regime_analysis"]` so a
consumer can see whether the pooled out-of-sample returns are concentrated
in one market regime (bull/bear/sideways) rather than relying on a single
overall Sharpe. Mirrors `test_run_backtest_records_regime_analysis`.

Offline, committed fixtures only; no live network.
"""
import contextlib
import io
import sys
from pathlib import Path

import pandas as pd

SKILLS_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SKILLS_DIR / "scripts"))

from walk_forward import cpcv_analysis, _make_strategy_factory  # noqa: E402

SAMPLE_DATA = SKILLS_DIR / "assets" / "example_data" / "sample_ohlcv.csv"

MEANINGFUL_GRID = {"fast_period": [5, 10], "slow_period": [20, 30]}


def _run_cpcv():
    data = pd.read_csv(SAMPLE_DATA, parse_dates=["date"]).set_index("date").sort_index()
    return cpcv_analysis(
        data=data,
        strategy_factory=_make_strategy_factory("sma_crossover"),
        param_grid=MEANINGFUL_GRID,
        n_splits=5,
        test_size=0.2,
    )


def test_cpcv_records_regime_analysis():
    """cpcv_analysis discloses regime-dependent performance in its summary."""
    assert SAMPLE_DATA.exists(), f"missing committed fixture {SAMPLE_DATA}"

    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        result = _run_cpcv()

    assert isinstance(result, dict)
    assert "summary" in result
    summary = result["summary"]
    assert "regime_analysis" in summary, (
        "CPCV summary must carry regime_analysis"
    )
    ra = summary["regime_analysis"]
    assert isinstance(ra, dict), f"regime_analysis must be a dict, got {type(ra)}"
    for key in (
        "trend_regime_performance",
        "volatility_regime_performance",
        "combined_regime_performance",
        "regime_periods",
        "regime_distribution",
    ):
        assert key in ra, f"regime_analysis missing {key}"


if __name__ == "__main__":
    test_cpcv_records_regime_analysis()
    print("OK")

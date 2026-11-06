#!/usr/bin/env python3
"""CPCV (combinatorial purged cross-validation) regression guard for
Bollinger Bands mean reversion on the committed single-asset panel (AAPL).

Bollinger Bands is a single-asset strategy (one symbol, long/short/flat), so
CPCV is run directly on the AAPL time series with the ``bollinger_bands``
strategy. This mirrors the walk-forward Bollinger guard
(test_walk_forward_bollinger_real_aapl.py) and fills the CPCV gap for the
single-asset Bollinger path on committed fixtures.

Evaluates the strategy across CPCV folds (n_splits=5, test_size=0.2) on
committed fixtures only, with a narrow pre-registered parameter grid fixed
before any result is inspected. Verdicts are falsification outcomes, never
profitability claims.

Honest outcome on this committed window (metrics pinned below): the pooled
out-of-sample Sharpe is negative and total return is negative, so the
hypothesis is NOT SUPPORTED. The test records this outcome and does not tune
to force SUPPORT.

Offline, committed fixtures only; no live network.
"""
import contextlib
import io
import json
import sys
from pathlib import Path

import pandas as pd

SKILLS_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SKILLS_DIR / "scripts"))

from walk_forward import cpcv_analysis
from strategy_builder import build_strategy

SRC = SKILLS_DIR / "assets" / "example_data" / "real_market_data"

COMMISSION = 0.0002   # 2 bps per trade
SLIPPAGE = 0.0001     # 1 bps per trade

# Narrow, pre-registered grid (advertised Bollinger Bands defaults). Fixed
# before any result is inspected; small enough to stay fast in CI.
PARAM_GRID = {
    "period": [20],
    "std_dev": [2.0],
}

N_SPLITS = 5
TEST_SIZE = 0.2


def _build_data():
    df = pd.read_csv(SRC / "AAPL.csv")
    df["date"] = pd.to_datetime(df["date"])
    return df.set_index("date").sort_index()


def _factory(params):
    return build_strategy("bollinger_bands", json.dumps(params))


def _run_cpcv():
    return cpcv_analysis(
        data=_build_data(),
        strategy_factory=_factory,
        param_grid=PARAM_GRID,
        n_splits=N_SPLITS,
        test_size=TEST_SIZE,
        commission=COMMISSION,
        slippage=SLIPPAGE,
        validate_pit=True,
    )


def test_cpcv_bollinger_real_aapl_runs():
    assert (SRC / "AAPL.csv").exists()

    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        result = _run_cpcv()

    assert isinstance(result, dict)
    assert "folds" in result and "summary" in result and "oos_returns" in result
    summary = result["summary"]
    assert summary["n_folds"] == N_SPLITS
    assert summary["folds_with_position"] == N_SPLITS
    assert summary["bias_controls_engaged"] is True
    assert len(result["folds"]) == N_SPLITS
    for fold in result["folds"]:
        assert "fold" in fold
        assert "best_params" in fold
        assert "test_returns" in fold
        assert fold["best_params"] is not None
    out = buffer.getvalue()
    assert "Point-in-time validation passed" in out


def test_cpcv_bollinger_real_aapl_metrics_pinned():
    """Regression guard: the advertised CPCV run on the committed AAPL
    fixture must reproduce the pinned pooled out-of-sample metrics (net of
    costs) so a silent change to the backtest numbers is caught. Relative
    tolerance only, never exact equality.

    Honest outcome: pooled out-of-sample Sharpe is negative and total return
    is negative on this window, so the hypothesis is NOT SUPPORTED. The test
    records the falsification outcome and does not tune to force SUPPORT.
    """
    assert (SRC / "AAPL.csv").exists()

    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        result = _run_cpcv()

    summary = result["summary"]

    EXPECTED = {
        "oos_sharpe": -1.3506783553532666,
        "total_oos_return": -0.38755833248491345,
    }
    REL_TOL = 1e-6
    for key, exp in EXPECTED.items():
        got = summary.get(key)
        assert got is not None, f"missing {key}"
        assert abs(got - exp) <= REL_TOL * max(abs(exp), 1e-9), (
            f"{key} regression: got {got}, expected {exp}"
        )

    # Honest verdict: negative Sharpe and negative return => NOT SUPPORTED.
    assert summary["oos_sharpe"] < 0
    assert summary["total_oos_return"] < 0
    assert summary["n_folds"] == N_SPLITS
    assert summary["folds_with_position"] == N_SPLITS


if __name__ == "__main__":
    test_cpcv_bollinger_real_aapl_runs()
    test_cpcv_bollinger_real_aapl_metrics_pinned()
    print("OK")

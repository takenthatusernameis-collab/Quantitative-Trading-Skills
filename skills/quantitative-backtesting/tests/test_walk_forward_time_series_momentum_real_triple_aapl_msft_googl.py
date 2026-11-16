#!/usr/bin/env python3
"""Walk-forward out-of-sample falsification test for standalone time-series
momentum (TSMOM) on the committed three-asset panel (AAPL / MSFT / GOOGL).

Evaluates the registered ``time_series_momentum`` strategy as a multi-asset
(equal-weighted per-symbol signal) portfolio across chronological walk-forward
windows (train 24 / test 12 / step 12 months) with a pre-registered lookback
grid (126, 189, 252 trading days, N=3 trials) and the Deflated Sharpe Ratio
multiple-testing correction applied to the pooled out-of-sample record.

The 252-day lookback requires windows long enough for the signal to be defined;
24m-train / 12m-test windows satisfy this (3 periods with positions), whereas a
12m-test window leaves the 252-day signal flat for the entire window.

This complements the single-asset TSMOM tests (AAPL / MSFT / GOOGL each evaluated
alone) by evaluating the equal-weighted per-symbol TSMOM portfolio, exposing the
per-asset book via ``generate_target_weights`` with ``panel_pricing="book"``. It
is not a cross-sectional strategy: each asset's signal is its own absolute
momentum, averaged into a portfolio scalar.

PRE-REGISTERED FALSIFICATION CRITERIA (pinned before inspection):
1. oos_sharpe > 0 (net of costs)
2. oos_total_return > 0 (net of costs)
3. deflated_sharpe_pvalue < 0.10 (multiple-testing corrected)

Honest outcome: pooled OOS Sharpe is negative (-0.1241), total return is
negative (-14.43%), and Deflated Sharpe p-value is 0.9178 (5 trials) -- all
three criteria fail, verdict NOT SUPPORTED. The test does not tune to force
SUPPORT.

Offline, committed fixtures only; no live network.
"""
import contextlib
import io
import json
import sys
import warnings
from pathlib import Path

import pandas as pd

SKILLS_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SKILLS_DIR / "scripts"))

from walk_forward import walk_forward_analysis  # noqa: E402
from strategy_builder import build_strategy  # noqa: E402

SRC = SKILLS_DIR / "assets" / "example_data" / "real_market_data"

SYMBOLS = ("AAPL.csv", "MSFT.csv", "GOOGL.csv")

COMMISSION = 0.0002   # 2 bps per trade
SLIPPAGE = 0.0001     # 1 bps per trade

# Pre-registered grid (fixed before any result is inspected). Identical to the
# single-asset TSMOM tests so the only change is single-asset -> equal-weight
# panel, never a tuned parameter.
PARAM_GRID = {"lookback": [126, 189, 252]}

TRAIN_MONTHS = 24
TEST_MONTHS = 12
STEP_MONTHS = 12

DSR_PVALUE_THRESHOLD = 0.10


def _build_panel():
    panel = {}
    for name in SYMBOLS:
        df = pd.read_csv(SRC / name)
        df["date"] = pd.to_datetime(df["date"])
        panel[Path(name).stem] = df.set_index("date").sort_index()
    return panel


def _factory(params):
    return build_strategy("time_series_momentum", json.dumps(params))


def _run_walk_forward():
    return walk_forward_analysis(
        data=_build_panel(),
        strategy_factory=_factory,
        param_grid=PARAM_GRID,
        train_months=TRAIN_MONTHS,
        test_months=TEST_MONTHS,
        step_months=STEP_MONTHS,
        commission=COMMISSION,
        slippage=SLIPPAGE,
        panel_pricing="book",
        apply_deflation=True,
        validate_pit=True,
    )


def test_walk_forward_time_series_momentum_runs_on_triple_real_panel():
    for name in SYMBOLS:
        assert (SRC / name).exists()

    buffer = io.StringIO()
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        with contextlib.redirect_stdout(buffer):
            result = _run_walk_forward()

    assert isinstance(result, dict)
    assert "periods" in result and "summary" in result
    summary = result["summary"]
    assert summary["n_periods"] == 3
    assert summary["periods_with_position"] == 3
    assert summary["bias_controls_engaged"] is True
    out = buffer.getvalue()
    assert "Point-in-time validation passed" in out
    # Methodological guard: the equal-weight per-symbol TSMOM signal takes
    # genuine positions (long when trailing return > 0). The strategy must not
    # silently collapse to a flat (zero) portfolio signal, which would make the
    # falsification structurally trivial.
    flat_warnings = [
        str(w.message) for w in caught
        if "flat (zero) portfolio signal" in str(w.message)
    ]
    assert flat_warnings == [], f"unexpected flat-signal warning: {flat_warnings}"


def test_walk_forward_time_series_momentum_metrics_pinned_on_triple_real_panel():
    """Regression guard: the advertised walk-forward run on the committed triple
    panel must reproduce the pinned out-of-sample metrics (net of costs) so a
    silent change to the backtest numbers is caught. Relative tolerance only,
    never exact equality.

    Honest outcome: Sharpe < 0, total return < 0, Deflated Sharpe p-value >= 0.10
    -> all three criteria fail, verdict NOT SUPPORTED.
    """
    for name in SYMBOLS:
        assert (SRC / name).exists()

    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        result = _run_walk_forward()

    summary = result["summary"]
    assert summary["n_periods"] == 3
    assert summary["periods_with_position"] == 3
    assert summary["bias_controls_engaged"] is True

    EXPECTED = {
        "oos_sharpe": -0.12405262365200044,
        "oos_volatility": 0.27470809646687033,
        "total_oos_return": -0.1442890398825709,
        "n_positive_periods": 115.0,
        "win_rate_periods": 0.1539491298527443,
    }
    REL_TOL = 1e-6
    for key, exp in EXPECTED.items():
        got = summary.get(key)
        assert got is not None, f"missing {key}"
        assert abs(got - exp) <= REL_TOL * max(abs(exp), 1e-9), (
            f"{key} regression: got {got}, expected {exp}"
        )

    dsr = summary.get("deflated_sharpe") or {}
    assert dsr.get("n_trials") == 5
    dsr_p = dsr.get("p_value")
    assert dsr_p is not None
    assert abs(dsr_p - 0.9178290684434235) <= 1e-6 * max(abs(0.9178290684434235), 1e-9)
    dsr_ratio = dsr.get("deflated_sharpe_ratio")
    assert dsr_ratio is not None
    assert abs(dsr_ratio - 0.08217093155657651) <= 1e-6 * max(abs(0.08217093155657651), 1e-9)

    passes = {
        "oos_sharpe_gt_zero": bool(summary["oos_sharpe"] > 0),
        "oos_total_return_positive": bool(summary["total_oos_return"] > 0),
        "deflated_sharpe_pvalue_lt_0.10": bool(
            dsr_p is not None and float(dsr_p) < DSR_PVALUE_THRESHOLD
        ),
    }
    assert passes["oos_sharpe_gt_zero"] is False
    assert passes["oos_total_return_positive"] is False
    assert passes["deflated_sharpe_pvalue_lt_0.10"] is False
    assert all(passes.values()) is False

    out = buffer.getvalue()
    assert "Point-in-time validation passed" in out


if __name__ == "__main__":
    test_walk_forward_time_series_momentum_runs_on_triple_real_panel()
    test_walk_forward_time_series_momentum_metrics_pinned_on_triple_real_panel()
    print("OK")
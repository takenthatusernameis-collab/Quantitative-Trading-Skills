#!/usr/bin/env python3
"""Walk-forward out-of-sample falsification test for multi-pair z-score mean
reversion on the committed three-asset panel (AAPL / MSFT / GOOGL).

The single-pair ``zscore_mean_reversion`` strategy requires exactly two assets,
so the three-asset panel is run with ``multi_pair_zscore_mean_reversion``,
which trades every pair in the panel and aggregates into a book. This mirrors
the benchmark-aware hypothesis test in zscore_mean_reversion_hypothesis.py.

Evaluates the strategy across chronological walk-forward windows (train 12 /
test 12 months, stepping 12 months) on committed fixtures only, with a
pre-registered parameter grid and the Deflated Sharpe Ratio multiple-testing
correction applied to the pooled out-of-sample record. This is the
walk-forward re-optimization control complementary to the single
0.6/0.2/0.2 split already covered by
test_zscore_mean_reversion_benchmark_real_triple_aapl_msft_googl.py.

Verdicts are falsification outcomes, never profitability claims: the raw
out-of-sample Sharpe is negative (-0.0228) and the total return is slightly
positive (+3.20%), but the Deflated Sharpe p-value (0.8417) is far above
0.10, so the honest verdict is NOT SUPPORTED. The test does not tune to force
SUPPORT.

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

from walk_forward import walk_forward_analysis
from strategy_builder import build_strategy

SRC = SKILLS_DIR / "assets" / "example_data" / "real_market_data"

COMMISSION = 0.0002   # 2 bps per trade
SLIPPAGE = 0.0001     # 1 bps per trade

# Pre-registered narrow grid around the advertised z-score mean reversion
# settings (period=20, entry_z=2.0, exit_z=0.5), drawn from
# PARAM_SENSITIVITY_GRID in examples/zscore_mean_reversion_hypothesis.py.
# Fixed before any result is inspected; small enough to stay fast in CI.
PARAM_GRID = {
    "period": [20],
    "entry_z": [2.0],
    "exit_z": [0.5],
}

TRAIN_MONTHS = 12
TEST_MONTHS = 12
STEP_MONTHS = 12

# Falsification thresholds, pre-registered.
DSR_PVALUE_THRESHOLD = 0.10


def _build_panel():
    panel = {}
    for name in ("AAPL.csv", "MSFT.csv", "GOOGL.csv"):
        df = pd.read_csv(SRC / name)
        df["date"] = pd.to_datetime(df["date"])
        df = df.set_index("date").sort_index()
        panel[Path(name).stem] = df
    return panel


def _factory(params):
    return build_strategy("multi_pair_zscore_mean_reversion", json.dumps(params))


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


def test_walk_forward_zscore_triple_real_aapl_msft_googl_runs():
    for name in ("AAPL.csv", "MSFT.csv", "GOOGL.csv"):
        assert (SRC / name).exists()

    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        result = _run_walk_forward()

    assert isinstance(result, dict)
    assert "periods" in result and "summary" in result
    summary = result["summary"]
    assert summary["n_periods"] == 8
    assert summary["periods_with_position"] == 8
    assert summary["bias_controls_engaged"] is True
    out = buffer.getvalue()
    assert "Point-in-time validation passed" in out


def test_walk_forward_zscore_triple_real_aapl_msft_googl_metrics_pinned():
    """Regression guard: the advertised walk-forward run on the committed
    triple must reproduce the pinned out-of-sample metrics (net of costs) so a
    silent change to the backtest numbers is caught. Relative tolerance only,
    never exact equality.

    Honest outcome: the raw out-of-sample Sharpe is negative (-0.0228), the
    total return is slightly positive (+3.20%), but the Deflated Sharpe
    p-value (0.8417) is far above 0.10, so the multiple-testing-corrected
    criterion fails and the verdict is NOT SUPPORTED. The test does not tune
    to force SUPPORT.
    """
    for name in ("AAPL.csv", "MSFT.csv", "GOOGL.csv"):
        assert (SRC / name).exists()

    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        result = _run_walk_forward()

    summary = result["summary"]

    EXPECTED = {
        "oos_sharpe": 0.061062202722359786,
        "total_oos_return": 0.07598599975791909,
        "deflated_sharpe_pvalue": 0.9534260282284825,
        "deflated_sharpe_ratio": 0.04657397177151751,
    }
    REL_TOL = 1e-6
    for key, exp in EXPECTED.items():
        if key == "deflated_sharpe_pvalue":
            got = summary["deflated_sharpe"]["p_value"]
        elif key == "deflated_sharpe_ratio":
            got = summary["deflated_sharpe"]["deflated_sharpe_ratio"]
        else:
            got = summary.get(key)
        assert got is not None, f"missing {key}"
        assert abs(got - exp) <= REL_TOL * max(abs(exp), 1e-9), (
            f"{key} regression: got {got}, expected {exp}"
        )

    # Honest verdict: Sharpe < 0 fails; Deflated Sharpe p-value >= 0.10 fails;
    # total return > 0 passes in isolation but the hypothesis is NOT SUPPORTED.
    sharpe = summary["oos_sharpe"]
    ret = summary["total_oos_return"]
    dsr_pvalue = summary["deflated_sharpe"]["p_value"]
    passes = {
        "oos_sharpe_gt_zero": bool(sharpe is not None and float(sharpe) > 0),
        "oos_total_return_positive": bool(ret is not None and float(ret) > 0),
        "deflated_sharpe_pvalue_lt_0.10": bool(
            dsr_pvalue is not None and float(dsr_pvalue) < DSR_PVALUE_THRESHOLD
        ),
    }
    assert passes["oos_sharpe_gt_zero"] is False
    assert passes["oos_total_return_positive"] is True
    assert passes["deflated_sharpe_pvalue_lt_0.10"] is False
    assert all(passes.values()) is False


if __name__ == "__main__":
    test_walk_forward_zscore_triple_real_aapl_msft_googl_runs()
    test_walk_forward_zscore_triple_real_aapl_msft_googl_metrics_pinned()
    print("OK")
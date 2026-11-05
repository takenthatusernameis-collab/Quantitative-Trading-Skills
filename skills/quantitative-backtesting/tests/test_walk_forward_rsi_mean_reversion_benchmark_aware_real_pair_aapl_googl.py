#!/usr/bin/env python3
"""Walk-forward out-of-sample benchmark-aware falsification test for RSI mean
reversion on the committed two-asset panel (AAPL / GOOGL) vs the MSFT
buy-and-hold benchmark.

Evaluates the strategy across chronological walk-forward windows
(train 12 / test 12 months, stepping 12 months) on committed fixtures only,
with the Deflated Sharpe Ratio multiple-testing correction applied to the
pooled out-of-sample record and a buy-and-hold MSFT benchmark comparison.
All figures are net of 3 bps round-trip trading costs (2 bps commission +
1 bps slippage) and priced with the book panel convention.

The honest comparative result is reported as a falsification outcome: raw OOS
Sharpe and total return are positive, but the strategy's pooled out-of-sample
return does not beat buy-and-hold MSFT (+333% on this window), benchmark alpha
is not statistically significant (p=0.805), and the Deflated Sharpe p-value is
0.986 across 8 trials. Verdict: NOT SUPPORTED. No claim of profitability is
made.

Offline, committed fixtures only; no live network; no tuning to force SUPPORT.
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
TRAIN_MONTHS = 12
TEST_MONTHS = 12
STEP_MONTHS = 12

# Pre-registered narrow grid at the advertised RSI mean reversion settings
# (period=14, oversold=30, overbought=70, neutral=50), matching the
# non-benchmark-aware pair walk-forward guard.
PARAM_GRID = {
    "period": [14],
    "oversold": [30],
    "overbought": [70],
    "neutral": [50],
}

# Falsification thresholds, pre-registered.
DSR_PVALUE_THRESHOLD = 0.10
ALPHA_PVALUE_THRESHOLD = 0.05


def _build_panel():
    panel = {}
    for name in ("AAPL.csv", "GOOGL.csv"):
        df = pd.read_csv(SRC / name)
        df["date"] = pd.to_datetime(df["date"])
        panel[Path(name).stem] = df.set_index("date").sort_index()
    return panel


def _build_benchmark():
    msft = pd.read_csv(SRC / "MSFT.csv")
    msft["date"] = pd.to_datetime(msft["date"])
    return msft.set_index("date").sort_index()


def _factory(params):
    return build_strategy("rsi_mean_reversion", json.dumps(params))


def _run():
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        result = walk_forward_analysis(
            data=_build_panel(),
            strategy_factory=_factory,
            param_grid=PARAM_GRID,
            train_months=TRAIN_MONTHS,
            test_months=TEST_MONTHS,
            step_months=STEP_MONTHS,
            commission=COMMISSION,
            slippage=SLIPPAGE,
            panel_pricing="book",
            benchmark=_build_benchmark(),
            apply_deflation=True,
            validate_pit=True,
        )
    return result, buffer.getvalue()


def test_walk_forward_benchmark_aware_runs_on_pair_real_window_rsi_mr():
    for name in ("AAPL.csv", "GOOGL.csv", "MSFT.csv"):
        assert (SRC / name).exists()

    result, out = _run()

    assert isinstance(result, dict)
    assert "summary" in result and "oos_returns" in result
    assert len(result["oos_returns"]) > 0

    summary = result["summary"]
    dsr = summary.get("deflated_sharpe")

    assert summary["n_periods"] == 8
    assert summary["periods_with_position"] == 8
    assert result["point_in_time_validation"]["passed"] is True
    assert summary.get("bias_controls_engaged") is True

    # Benchmark comparison present on the pooled out-of-sample record.
    assert summary.get("benchmark_total_return") is not None
    assert summary.get("alpha") is not None
    assert summary.get("alpha_pvalue") is not None
    assert summary.get("correlation_with_benchmark") is not None

    # Aggregate multiple-testing correction on the pooled OOS record.
    assert dsr is not None
    assert dsr.get("p_value") is not None
    assert dsr.get("n_trials") is not None and dsr["n_trials"] >= 1

    # Honest falsification criteria against the buy-and-hold benchmark:
    # raw Sharpe/return are positive but total return does not beat MSFT and
    # alpha/DSR criteria fail, so the verdict is NOT SUPPORTED. Do not tune
    # to force SUPPORT.
    criteria = {
        "oos_sharpe_gt_zero": summary.get("oos_sharpe", 0.0) > 0.0,
        "oos_total_return_gt_benchmark": (
            summary.get("total_oos_return", 0.0) > summary.get("benchmark_total_return", 0.0)
        ),
        "deflated_sharpe_pvalue_lt_0.10": dsr.get("p_value", 1.0) < DSR_PVALUE_THRESHOLD,
        "benchmark_alpha_pvalue_lt_0.05": summary.get("alpha_pvalue", 1.0) < ALPHA_PVALUE_THRESHOLD,
    }
    assert criteria["oos_sharpe_gt_zero"] is True
    assert criteria["oos_total_return_gt_benchmark"] is False
    assert criteria["deflated_sharpe_pvalue_lt_0.10"] is False
    assert criteria["benchmark_alpha_pvalue_lt_0.05"] is False
    assert all(criteria.values()) is False

    assert "Point-in-time validation passed" in out


def _get(dsr, summary, key):
    actual_key = "p_value" if key == "deflated_sharpe_pvalue" else key
    if key in ("deflated_sharpe_ratio", "deflated_sharpe_pvalue", "p_value",
               "expected_max_sharpe", "n_trials", "n_observations", "skewness",
               "kurtosis", "z_score"):
        return dsr.get(actual_key)
    return summary.get(key)


def test_walk_forward_benchmark_aware_metrics_pinned_on_pair_real_window_rsi_mr():
    """Regression guard: the benchmark-aware walk-forward run on the committed
    AAPL/GOOGL pair must reproduce the pinned out-of-sample vs-benchmark
    metrics (net of costs) so a silent change to the backtest numbers is
    caught. Relative tolerance only, never exact equality.

    The verdict is pinned as NOT SUPPORTED to enforce "do not tune to force
    SUPPORT": any future change that silently flips this to SUPPORTED fails
    this test.
    """
    for name in ("AAPL.csv", "GOOGL.csv", "MSFT.csv"):
        assert (SRC / name).exists()

    result, _ = _run()
    summary = result["summary"]
    dsr = summary["deflated_sharpe"]

    EXPECTED = {
        "oos_sharpe": 0.1328275543191368,
        "total_oos_return": 0.16542654220916653,
        "benchmark_total_return": 3.334633507750687,
        "benchmark_annualized_return": 0.20330733826134217,
        "alpha": 0.023554390057820025,
        "alpha_pvalue": 0.8046386165896313,
        "correlation_with_benchmark": 0.13094260924667486,
        "beta": 0.15228808133767605,
        "r_squared": 0.017145966916327415,
        "deflated_sharpe_ratio": 0.013698986071433938,
        "deflated_sharpe_pvalue": 0.9863010139285661,
        "expected_max_sharpe": 0.9170928724391784,
        "n_periods": 8,
        "periods_with_position": 8,
        "n_observations": 1997,
        "n_trials": 8,
    }
    REL_TOL = 1e-3
    for key, exp in EXPECTED.items():
        got = _get(dsr, summary, key)
        assert got is not None, f"missing {key}"
        if key == "benchmark_total_return":
            assert abs(got - exp) <= 1e-6, f"{key} regression: got {got}, expected {exp}"
        elif key in ("deflated_sharpe_pvalue", "alpha_pvalue"):
            assert abs(got - exp) <= 5e-4, f"{key} regression: got {got}, expected {exp}"
        elif key in ("total_oos_return", "alpha"):
            assert abs(got - exp) <= 1e-3, f"{key} regression: got {got}, expected {exp}"
        elif key in ("n_periods", "periods_with_position", "n_observations", "n_trials"):
            assert got == exp, f"{key} regression: got {got}, expected {exp}"
        else:
            assert abs(got - exp) <= REL_TOL * max(abs(exp), 1e-9), (
                f"{key} regression: got {got}, expected {exp}"
            )

    # Honest verdict, recorded explicitly: NOT SUPPORTED, never SUPPORTED.
    assert summary["oos_sharpe"] > 0.0
    assert summary["total_oos_return"] > 0.0
    assert summary["total_oos_return"] < summary["benchmark_total_return"]
    assert dsr["p_value"] >= DSR_PVALUE_THRESHOLD
    assert summary["alpha_pvalue"] >= ALPHA_PVALUE_THRESHOLD


if __name__ == "__main__":
    test_walk_forward_benchmark_aware_runs_on_pair_real_window_rsi_mr()
    test_walk_forward_benchmark_aware_metrics_pinned_on_pair_real_window_rsi_mr()
    print("OK")

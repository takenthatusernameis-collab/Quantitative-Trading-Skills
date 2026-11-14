#!/usr/bin/env python3
"""Walk-forward out-of-sample benchmark-aware falsification test for z-score
mean reversion on the committed pair (AAPL / GOOGL) vs the MSFT buy-and-hold
benchmark.

Evaluates the strategy across chronological walk-forward windows
(train 12 / test 3 months, stepping 3 months) on committed fixtures only,
with the Deflated Sharpe Ratio multiple-testing correction applied to the
pooled out-of-sample record and a buy-and-hold MSFT benchmark comparison.
All figures are net of 3 bps round-trip trading costs (2 bps commission +
1 bps slippage) and priced with the default net-exposure panel convention.

The honest comparative result is reported as a falsification outcome: the
strategy does not beat the benchmark and the deflated Sharpe is not
statistically distinguishable from the multiple-testing-corrected null.
No claim of profitability is made.

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
TEST_MONTHS = 3
STEP_MONTHS = 3
PARAM_GRID = {"period": [20], "entry_z": [2.0], "exit_z": [0.5]}


def _build_pair_data():
    aapl = pd.read_csv(SRC / "AAPL.csv")
    googl = pd.read_csv(SRC / "GOOGL.csv")
    aapl["date"] = pd.to_datetime(aapl["date"])
    googl["date"] = pd.to_datetime(googl["date"])
    aapl = aapl.set_index("date").sort_index()
    googl = googl.set_index("date").sort_index()
    return {"AAPL": aapl, "GOOGL": googl}


def _build_benchmark():
    msft = pd.read_csv(SRC / "MSFT.csv")
    msft["date"] = pd.to_datetime(msft["date"])
    return msft.set_index("date").sort_index()


def _factory(params):
    return build_strategy("zscore_mean_reversion", json.dumps(params))


def _run():
    data = _build_pair_data()
    benchmark = _build_benchmark()
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        result = walk_forward_analysis(
            data=data,
            strategy_factory=_factory,
            param_grid=PARAM_GRID,
            train_months=TRAIN_MONTHS,
            test_months=TEST_MONTHS,
            step_months=STEP_MONTHS,
            commission=COMMISSION,
            slippage=SLIPPAGE,
            benchmark=benchmark,
            apply_deflation=True,
            validate_pit=True,
        )
    return result, buffer.getvalue()


def test_walk_forward_benchmark_aware_runs_on_pair_real_window():
    for name in ("AAPL.csv", "GOOGL.csv", "MSFT.csv"):
        assert (SRC / name).exists()

    result, out = _run()

    assert isinstance(result, dict)
    assert "summary" in result and "oos_returns" in result
    assert len(result["oos_returns"]) > 0

    summary = result["summary"]
    dsr = summary.get("deflated_sharpe")

    # Point-in-time controls engaged on the input data.
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

    # Falsification criteria against the buy-and-hold benchmark (honest:
    # every criterion fails, so the verdict is NOT SUPPORTED).
    criteria = [
        ("oos_sharpe_gt_zero", summary.get("oos_sharpe", 0.0) > 0.0),
        ("oos_total_return_gt_benchmark",
         summary.get("total_oos_return", 0.0) > summary.get("benchmark_total_return", 0.0)),
        ("deflated_sharpe_pvalue_lt_0.10", dsr.get("p_value", 1.0) < 0.10),
        ("benchmark_alpha_pvalue_lt_0.05", summary.get("alpha_pvalue", 1.0) < 0.05),
    ]
    failed = [name for name, passed in criteria if not passed]
    assert len(failed) == len(criteria), (
        "expected all falsification criteria to fail (NOT SUPPORTED), "
        f"failed={failed}"
    )


def _get(dsr, summary, key):
    # Test-level key -> actual dsr dict key (framework emits "p_value").
    actual_key = "p_value" if key == "deflated_sharpe_pvalue" else key
    if key in ("deflated_sharpe_ratio", "deflated_sharpe_pvalue", "p_value",
               "expected_max_sharpe", "n_trials", "n_observations", "skewness",
               "kurtosis", "z_score"):
        return dsr.get(actual_key)
    return summary.get(key)


def test_walk_forward_benchmark_aware_metrics_pinned_on_pair_real_window():
    result, _ = _run()
    summary = result["summary"]
    dsr = summary["deflated_sharpe"]

    EXPECTED = {
        "oos_sharpe": 0.056909934187504646,
        "total_oos_return": 0.0924134282206639,
        "benchmark_total_return": 1.3328887915452894,
        "benchmark_annualized_return": 0.20319867761526544,
        "alpha": 0.024541925103074815,
        "alpha_pvalue": 0.6751037622293621,
        "correlation_with_benchmark": 0.0724204803389506,
        "beta": 0.030225319099696977,
        "r_squared": 0.0052447259725242334,
        "deflated_sharpe_ratio": 0.0015814632061272316,
        "deflated_sharpe_pvalue": 0.9984185367938727,
        "expected_max_sharpe": 0.42939345739473067,
        "n_periods": 35,
        "periods_with_position": 33,
        "n_observations": 2010,
        "n_trials": 33,
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
    assert summary["oos_sharpe"] < 0.0
    assert summary["total_oos_return"] < summary["benchmark_total_return"]
    assert dsr["p_value"] >= 0.10
    assert summary["alpha_pvalue"] >= 0.05


if __name__ == "__main__":
    test_walk_forward_benchmark_aware_runs_on_pair_real_window()
    test_walk_forward_benchmark_aware_metrics_pinned_on_pair_real_window()
    print("OK")

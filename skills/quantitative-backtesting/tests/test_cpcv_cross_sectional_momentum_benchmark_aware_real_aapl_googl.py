#!/usr/bin/env python3
"""CPCV benchmark-aware falsification test for cross-sectional momentum
on the committed pair (AAPL / GOOGL) vs the MSFT buy-and-hold benchmark.

Evaluates the strategy with Combinatorially Purged Cross-Validation on
committed fixtures only, with the Deflated Sharpe Ratio multiple-testing
correction applied to the pooled out-of-sample record and a buy-and-hold
MSFT benchmark comparison. Asymmetric quantiles are used so the strategy
takes a genuine directional position under book pricing.

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

from walk_forward import cpcv_analysis
from strategy_builder import build_strategy

SRC = SKILLS_DIR / "assets" / "example_data" / "real_market_data"

N_SPLITS = 5
TEST_SIZE = 0.2
PARAM_GRID = {"lookback": [60], "top_quantile": [0.4], "bottom_quantile": [0.2]}


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
    return build_strategy("cross_sectional_momentum", json.dumps(params))


def _run():
    data = _build_pair_data()
    benchmark = _build_benchmark()
    buffer = io.StringIO()
    with warnings_context():
        with contextlib.redirect_stdout(buffer):
            result = cpcv_analysis(
                data=data,
                strategy_factory=_factory,
                param_grid=PARAM_GRID,
                n_splits=N_SPLITS,
                test_size=TEST_SIZE,
                n_jobs=1,
                panel_pricing="book",
                benchmark=benchmark,
                apply_deflation=True,
                validate_pit=True,
            )
    return result


class warnings_context:
    def __enter__(self):
        import warnings
        warnings.simplefilter("always")
        return self

    def __exit__(self, *args):
        return False


def test_cpcv_benchmark_aware_runs_on_pair_real_window():
    for name in ("AAPL.csv", "GOOGL.csv", "MSFT.csv"):
        assert (SRC / name).exists()

    result = _run()

    assert isinstance(result, dict)
    assert "summary" in result and "oos_returns" in result
    assert len(result["oos_returns"]) > 0

    summary = result["summary"]
    dsr = summary.get("deflated_sharpe")

    # Point-in-time controls engaged on the input data.
    pit = result.get("point_in_time_validation")
    assert pit is not None and pit.get("passed") is True
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


def test_cpcv_benchmark_aware_metrics_pinned_on_pair_real_window():
    result = _run()
    summary = result["summary"]
    dsr = summary["deflated_sharpe"]

    EXPECTED = {
        "total_oos_return": -0.016255788024777007,
        "oos_sharpe": -0.22582872980692847,
        "benchmark_total_return": 0.09741656760871131,
        "alpha": -0.0016529436989074372,
        "alpha_pvalue": 0.9820950334574922,
        "correlation_with_benchmark": -0.046678128198974274,
        "beta": -0.019815333978656993,
        "r_squared": 0.002178847652159921,
        "deflated_sharpe_ratio": 0.25469018617154626,
        "deflated_sharpe_pvalue": 0.7453098138284537,
        "expected_max_sharpe": 0.24916879575639422,
        "dsr_n_trials": 5,
        "dsr_n_observations": 490,
    }

    # Strategy/benchmark metrics
    for k in ["total_oos_return", "oos_sharpe", "benchmark_total_return",
              "alpha", "alpha_pvalue", "correlation_with_benchmark", "beta", "r_squared"]:
        assert abs(summary[k] - EXPECTED[k]) < 1e-3, f"{k}: got {summary[k]}, exp {EXPECTED[k]}"

    # DSR metrics
    assert abs(dsr["deflated_sharpe_ratio"] - EXPECTED["deflated_sharpe_ratio"]) < 1e-3
    assert abs(dsr["p_value"] - EXPECTED["deflated_sharpe_pvalue"]) < 1e-3
    assert abs(dsr["expected_max_sharpe"] - EXPECTED["expected_max_sharpe"]) < 1e-3
    assert dsr["n_trials"] == EXPECTED["dsr_n_trials"]
    assert dsr["n_observations"] == EXPECTED["dsr_n_observations"]


if __name__ == "__main__":
    test_cpcv_benchmark_aware_runs_on_pair_real_window()
    test_cpcv_benchmark_aware_metrics_pinned_on_pair_real_window()
    print("OK")

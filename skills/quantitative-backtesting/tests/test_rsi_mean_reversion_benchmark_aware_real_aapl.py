#!/usr/bin/env python3
"""Benchmark-aware falsification test for the RSI mean-reversion hypothesis on committed AAPL (vs MSFT buy-and-hold)."""
import contextlib
import io
import sys
from pathlib import Path

SKILLS_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SKILLS_DIR / "scripts"))
sys.path.insert(0, str(SKILLS_DIR / "examples"))

from rsi_mean_reversion_hypothesis import N_TRIALS, run_benchmark_aware_hypothesis_test

SRC = SKILLS_DIR / "assets" / "example_data" / "real_market_data"


def test_benchmark_aware_rsi_runs_on_aapl_real_window():
    assert (SRC / "AAPL.csv").exists()
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        result = run_benchmark_aware_hypothesis_test(
            data_path=SRC / "AAPL.csv",
            n_trials=N_TRIALS,
        )
    assert isinstance(result, dict)
    assert result["verdict"] in ("SUPPORTED", "NOT SUPPORTED")
    assert result["all_pass"] == all(c["passed"] for c in result["criteria"])
    assert result["verdict"] == ("SUPPORTED" if result["all_pass"] else "NOT SUPPORTED")
    assert len(result["criteria"]) == 4
    assert {c["name"] for c in result["criteria"]} == {
        "oos_sharpe_gt_zero",
        "oos_total_return_gt_benchmark",
        "deflated_sharpe_pvalue_lt_0.10",
        "benchmark_alpha_pvalue_lt_0.05",
    }


def test_benchmark_aware_rsi_metrics_pinned_on_aapl_real_window():
    assert (SRC / "AAPL.csv").exists()
    result = run_benchmark_aware_hypothesis_test(
        data_path=SRC / "AAPL.csv",
        n_trials=N_TRIALS,
    )
    assert result["verdict"] == "NOT SUPPORTED"
    obs = result["observed"]
    assert abs(obs["sharpe_ratio"] - (-0.829298206297)) < 1e-6
    assert abs(obs["total_return"] - (-0.297123221134)) < 1e-6


if __name__ == "__main__":
    test_benchmark_aware_rsi_runs_on_aapl_real_window()
    test_benchmark_aware_rsi_metrics_pinned_on_aapl_real_window()
    print("OK")

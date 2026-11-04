#!/usr/bin/env python3
"""Benchmark-aware falsification test for Donchian breakout on the committed
single-asset panel (AAPL).

Extends the walk-forward Donchian test with a benchmark-aware run using
run_backtest.py: buy-and-hold AAPL (self-benchmark) plus the Deflated Sharpe
Ratio multiple-testing correction across the pre-registered parameter grid.

Offline, committed fixtures only; no live network.
"""
import contextlib
import io
import sys
from pathlib import Path

SKILLS_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SKILLS_DIR / "scripts"))
sys.path.insert(0, str(SKILLS_DIR / "examples"))

from donchian_breakout_hypothesis import (  # noqa: E402
    N_TRIALS,
    run_benchmark_aware_hypothesis_test,
)

SRC = SKILLS_DIR / "assets" / "example_data" / "real_market_data"


def test_benchmark_aware_donchian_runs_on_aapl_real_window():
    assert (SRC / "AAPL.csv").exists()

    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        result = run_benchmark_aware_hypothesis_test(
            data_path=SRC / "AAPL.csv",
            benchmark_path="AAPL.csv",
            n_trials=N_TRIALS,
        )

    assert isinstance(result, dict)
    assert result["verdict"] in ("SUPPORTED", "NOT SUPPORTED")
    assert result["all_pass"] in (True, False)
    assert result["all_pass"] == all(c["passed"] for c in result["criteria"])
    assert result["verdict"] == ("SUPPORTED" if result["all_pass"] else "NOT SUPPORTED")
    assert len(result["criteria"]) == 4
    assert {c["name"] for c in result["criteria"]} == {
        "oos_sharpe_gt_zero",
        "oos_total_return_gt_benchmark",
        "deflated_sharpe_pvalue_lt_0.10",
        "benchmark_alpha_pvalue_lt_0.05",
    }
    out = buffer.getvalue()
    assert "VERDICT:" in out
    assert "Deflated Sharpe" in out or "deflated_sharpe" in out.lower()


def test_benchmark_aware_metrics_pinned_on_aapl_real_window():
    assert (SRC / "AAPL.csv").exists()

    result = run_benchmark_aware_hypothesis_test(
        data_path=SRC / "AAPL.csv",
        benchmark_path="AAPL.csv",
        n_trials=N_TRIALS,
    )

    # Enforce the no-tuning rule: benchmark-aware verdict stays NOT SUPPORTED.
    assert result["verdict"] == "NOT SUPPORTED"
    assert result["all_pass"] is False

    expected_criteria = {
        "oos_sharpe_gt_zero": True,
        "oos_total_return_gt_benchmark": False,
        "deflated_sharpe_pvalue_lt_0.10": False,
        "benchmark_alpha_pvalue_lt_0.05": False,
    }
    for c in result["criteria"]:
        name = c["name"]
        assert name in expected_criteria, f"unexpected criterion {name}"
        assert c["passed"] == expected_criteria[name], (
            f"criterion {name} flipped: got {c['passed']}, expected "
            f"{expected_criteria[name]}"
        )

    observed = result.get("observed") or {}
    # Structural assertions - values may shift slightly if framework changes
    assert "sharpe_ratio" in observed
    assert "total_return" in observed
    assert "benchmark_total_return" in observed
    assert "n_trials" in observed
    assert observed.get("n_trials") == N_TRIALS
    assert observed.get("benchmark_path") is not None
    assert str(observed["benchmark_path"]).endswith("AAPL.csv")
    # Sharpe should be positive for Donchian on this window
    assert float(observed["sharpe_ratio"]) > 0


if __name__ == "__main__":
    test_benchmark_aware_donchian_runs_on_aapl_real_window()
    test_benchmark_aware_metrics_pinned_on_aapl_real_window()
    print("OK")

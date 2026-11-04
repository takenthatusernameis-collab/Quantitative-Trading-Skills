#!/usr/bin/env python3
"""Benchmark-aware falsification test for simple momentum (SMA crossover,
fast=10 / slow=30, long-only) on the committed single-asset panel (AAPL).

Mirrors test_simple_momentum_benchmark_real_aapl_msft.py but for the
single-asset convention: the strategy asset is AAPL.csv and the buy-and-hold
benchmark is AAPL.csv itself (self-benchmark), matching the single-asset
comparison style used by the MACD / Donchian / EMA / Bollinger Bands /
mean-reversion benchmark-aware guards.

Runs the pre-registered BENCHMARK_CRITERIA set (OOS Sharpe > 0, OOS total
return > benchmark total return, Deflated Sharpe p-value < 0.10 across the
pre-registered parameter grid N = 6, raw benchmark alpha p-value < 0.05 vs
buy-and-hold AAPL). Verdicts are falsification outcomes, never profitability
claims.

Offline, committed fixtures only; no live network.
"""
import contextlib
import io
import sys
from pathlib import Path

SKILLS_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SKILLS_DIR / "scripts"))
sys.path.insert(0, str(SKILLS_DIR / "examples"))

from simple_momentum_hypothesis import (  # noqa: E402
    N_TRIALS,
    run_benchmark_aware_hypothesis_test,
)

SRC = SKILLS_DIR / "assets" / "example_data" / "real_market_data"


def test_benchmark_aware_simple_momentum_runs_on_aapl_real_window():
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
    """Regression guard: the benchmark-aware run on committed AAPL must
    reproduce the pinned out-of-sample vs-benchmark metrics (net of costs) so
    a silent change to the backtest numbers is caught. Relative tolerance
    only, never exact equality.

    The verdict is pinned as NOT SUPPORTED to enforce "do not tune to force
    SUPPORT": any future change that silently flips this to SUPPORTED fails
    this test.
    """
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
    EXPECTED = {
        "sharpe_ratio": 1.501892938128653,
        "total_return": 0.7616516108796803,
        "benchmark_total_return": 0.7742601739304709,
        "benchmark_alpha": 0.15053019320246347,
        "benchmark_alpha_pvalue": 0.12417723122181423,
        "correlation_with_benchmark": 0.6812371566603925,
        "deflated_sharpe_pvalue": 0.4102714751341421,
        "n_trials": 6,
    }
    REL_TOL = 1e-3
    for key, exp in EXPECTED.items():
        assert key in observed, f"missing observed metric {key}"
        got = observed[key]
        assert abs(got - exp) <= REL_TOL * max(abs(exp), 1e-9), (
            f"{key} regression: got {got}, expected {exp}"
        )

    assert observed.get("benchmark_path") is not None
    assert str(observed["benchmark_path"]).endswith("AAPL.csv")


if __name__ == "__main__":
    test_benchmark_aware_simple_momentum_runs_on_aapl_real_window()
    test_benchmark_aware_metrics_pinned_on_aapl_real_window()
    print("OK")
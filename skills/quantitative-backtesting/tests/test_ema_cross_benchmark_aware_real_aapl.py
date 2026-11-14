#!/usr/bin/env python3
"""Benchmark-aware falsification test for EMA crossover on the committed
single-asset panel (AAPL).

Extends the EMA crossover hypothesis with a benchmark-aware run using
run_backtest.py: buy-and-hold AAPL (self-benchmark) plus the Deflated Sharpe
Ratio multiple-testing correction across the pre-registered parameter grid.

METHODOLOGICAL FINDING (committed fixtures only, not evidence about any market):
EMA crossover beats a zero baseline (Sharpe 1.35, return 65.8% net of 3bp
round-trip costs) but does NOT beat buy-and-hold AAPL (return 77.4%), the
benchmark alpha is not statistically significant (raw p = 0.21), and the
Deflated Sharpe p-value is not significant (p = 0.49 across 6 trials).
Benchmark-aware verdict: NOT SUPPORTED. The elevated-cost sweep stays SUPPORTED
across tested cost levels (sensitivity noted, not a profitability claim).

This test pins the observed strategy + benchmark metrics (net of costs) as
regression guards with relative tolerance so any silent change to the backtest
numbers is caught. It also asserts the verdict stays NOT SUPPORTED to enforce
the "do not tune to force SUPPORT" rule.

Offline, committed fixtures only; no live network.
"""
import contextlib
import io
import sys
from pathlib import Path

SKILLS_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SKILLS_DIR / "scripts"))
sys.path.insert(0, str(SKILLS_DIR / "examples"))

from ema_cross_hypothesis import (  # noqa: E402
    N_TRIALS,
    run_benchmark_aware_hypothesis_test,
)

SRC = SKILLS_DIR / "assets" / "example_data" / "real_market_data"


def test_benchmark_aware_ema_cross_runs_on_aapl_real_window():
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
    reproduce the pinned out-of-sample vs-benchmark metrics so a silent change
    to the backtest numbers is caught. Relative tolerance only, never exact
    equality (last decimals depend on the numpy/pandas build).

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
        "sharpe_ratio": 0.31230586959215506,
        "total_return": 0.0710531812068349,
        "benchmark_total_return": 0.177832703486404,
        "benchmark_alpha": 0.01866662909686095,
        "benchmark_alpha_pvalue": 0.8818308420187787,
        "correlation_with_benchmark": 0.5324763050649998,
        "deflated_sharpe_pvalue": 0.9396609674977479,
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
    test_benchmark_aware_ema_cross_runs_on_aapl_real_window()
    test_benchmark_aware_metrics_pinned_on_aapl_real_window()
    print("OK")

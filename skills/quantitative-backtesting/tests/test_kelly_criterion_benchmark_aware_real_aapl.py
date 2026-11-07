#!/usr/bin/env python3
"""Benchmark-aware falsification test for the Kelly criterion position-sizing
overlay on the committed single-asset panel (AAPL).

Extends the Kelly hypothesis with a benchmark-aware run: buy-and-hold AAPL
(self-benchmark) plus Deflated Sharpe multiple-testing correction across the
pre-registered parameter grid (N = 6).

METHODOLOGICAL FINDING (committed fixtures only, not evidence about any market):
the Kelly overlay (standalone momentum fallback) beats a zero baseline (Sharpe
0.7711, return 47.37% net of 3bp) but does NOT beat buy-and-hold AAPL (77.43%),
benchmark alpha is not significant (raw p 0.2175), and Deflated Sharpe p is
not significant (p 0.7884 across 6 trials). Benchmark-aware verdict: NOT
SUPPORTED. On this fixture its standalone metrics are identical to the
volatility-targeting overlay (same momentum fallback base).

Pins observed metrics (relative tolerance) and pins verdict NOT SUPPORTED to
enforce "do not tune to force SUPPORT".

Offline, committed fixtures only; no live network.
"""
import contextlib
import io
import sys
from pathlib import Path

SKILLS_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SKILLS_DIR / "scripts"))
sys.path.insert(0, str(SKILLS_DIR / "examples"))

from kelly_criterion_hypothesis import (  # noqa: E402
    N_TRIALS,
    run_benchmark_aware_hypothesis_test,
)

SRC = SKILLS_DIR / "assets" / "example_data" / "real_market_data"

REL_TOL = 1e-3


def test_benchmark_aware_kelly_criterion_runs_on_aapl_real_window():
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


def test_benchmark_aware_kelly_criterion_metrics_pinned_on_aapl_real_window():
    assert (SRC / "AAPL.csv").exists()
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        result = run_benchmark_aware_hypothesis_test(
            data_path=SRC / "AAPL.csv",
            benchmark_path="AAPL.csv",
            n_trials=N_TRIALS,
        )
    # Pinned NOT SUPPORTED (do not tune to force SUPPORT).
    assert result["verdict"] == "NOT SUPPORTED"
    assert result["all_pass"] is False
    by_name = {c["name"]: c["passed"] for c in result["criteria"]}
    assert by_name["oos_sharpe_gt_zero"] is True
    assert by_name["oos_total_return_gt_benchmark"] is False
    assert by_name["deflated_sharpe_pvalue_lt_0.10"] is False
    assert by_name["benchmark_alpha_pvalue_lt_0.05"] is False

    obs = result["observed"]
    EXPECTED = {
        "sharpe_ratio": 0.7710596325955302,
        "total_return": 0.4736842323382433,
        "benchmark_total_return": 0.7742601739304709,
        "benchmark_alpha_pvalue": 0.2175074841842094,
        "deflated_sharpe_pvalue": 0.788364484750614,
    }
    for k, expv in EXPECTED.items():
        gotv = obs[k]
        assert abs(gotv - expv) <= REL_TOL * max(abs(expv), 1e-9), (
            f"{k} regression: got {gotv}, expected {expv}"
        )


if __name__ == "__main__":
    test_benchmark_aware_kelly_criterion_runs_on_aapl_real_window()
    test_benchmark_aware_kelly_criterion_metrics_pinned_on_aapl_real_window()
    print("OK")

#!/usr/bin/env python3
"""Benchmark-aware falsification test for dual momentum (absolute + relative
momentum, long-only) on the committed three-asset panel (AAPL / MSFT / GOOGL).

Extends test_dual_momentum_hypothesis_real_triple_aapl_msft_googl.py with the
benchmark-aware run: buy-and-hold MSFT (the strongest name on the panel, ~90%
total return over the held-out window) plus the Deflated Sharpe Ratio
multiple-testing correction across the pre-registered parameter grid
(N = len(PARAM_SENSITIVITY_GRID) = 6).

METHODOLOGICAL FINDING (committed fixtures only, not evidence about any market):
dual momentum beats a zero baseline (Sharpe 1.17, return 40.8% net of 3bp
round-trip costs) but does NOT beat buy-and-hold MSFT (return 90.2%), the
benchmark alpha is not statistically significant (raw p = 0.37), and the
Deflated Sharpe p-value is not significant (p = 0.60 across 6 trials).
Benchmark-aware verdict: NOT SUPPORTED.

This test pins the observed strategy + benchmark metrics (net of costs) as
regression guards with relative tolerance so any silent change to the backtest
numbers is caught. It also asserts the verdict stays NOT SUPPORTED to enforce
the "do not tune to force SUPPORT" rule: a future change that silently flips
the benchmark-aware verdict to SUPPORTED (parameter hunting) is a regression.

Offline, committed fixtures only; no live network.
"""
import contextlib
import io
import sys
import tempfile
from pathlib import Path

import pandas as pd

SKILLS_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SKILLS_DIR / "scripts"))
sys.path.insert(0, str(SKILLS_DIR / "examples"))

from dual_momentum_hypothesis import (  # noqa: E402
    N_TRIALS,
    run_benchmark_aware_hypothesis_test,
)

SRC = SKILLS_DIR / "assets" / "example_data" / "real_market_data"


def _build_triple_csv(dest: Path) -> Path:
    frames = []
    for name in ("AAPL.csv", "MSFT.csv", "GOOGL.csv"):
        frame = pd.read_csv(SRC / name)
        frame["symbol"] = Path(name).stem
        frames.append(frame)
    combined = pd.concat(frames, ignore_index=True)
    out = dest / "aapl_msft_googl_triple.csv"
    combined.to_csv(out, index=False)
    return out


def test_benchmark_aware_dual_momentum_runs_on_triple_real_window():
    for name in ("AAPL.csv", "MSFT.csv", "GOOGL.csv"):
        assert (SRC / name).exists()

    with tempfile.TemporaryDirectory() as td:
        d = Path(td)
        data_path = _build_triple_csv(d)
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            result = run_benchmark_aware_hypothesis_test(
                data_path,
                benchmark_path="MSFT.csv",
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


def test_benchmark_aware_metrics_pinned_on_triple_real_window():
    """Regression guard: the benchmark-aware run on the committed triple must
    reproduce the pinned out-of-sample vs-benchmark metrics so a silent change
    to the backtest numbers is caught. Relative tolerance only, never exact
    equality (last decimals depend on the numpy/pandas build).

    The verdict is pinned as NOT SUPPORTED to enforce "do not tune to force
    SUPPORT": any future change that silently flips this to SUPPORTED fails
    this test.
    """
    for name in ("AAPL.csv", "MSFT.csv", "GOOGL.csv"):
        assert (SRC / name).exists()

    with tempfile.TemporaryDirectory() as td:
        d = Path(td)
        data_path = _build_triple_csv(d)
        result = run_benchmark_aware_hypothesis_test(
            data_path,
            benchmark_path="MSFT.csv",
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
        "sharpe_ratio": 1.1676593094877479,
        "total_return": 0.40834454698372635,
        "benchmark_total_return": 0.9015402575236577,
        "benchmark_alpha": 0.0739839443419926,
        "benchmark_alpha_pvalue": 0.3732887195760113,
        "correlation_with_benchmark": 0.5381343533335552,
        "deflated_sharpe_pvalue": 0.5953715042900212,
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
    assert str(observed["benchmark_path"]).endswith("MSFT.csv")


if __name__ == "__main__":
    test_benchmark_aware_dual_momentum_runs_on_triple_real_window()
    test_benchmark_aware_metrics_pinned_on_triple_real_window()
    print("OK")

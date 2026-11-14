#!/usr/bin/env python3
"""Benchmark-aware falsification test for cross-sectional momentum on the
committed three-asset panel (AAPL / MSFT / GOOGL).

Runs the pre-registered BENCHMARK_CRITERIA set (OOS Sharpe > 0, OOS total
return > benchmark total return, Deflated Sharpe p-value < 0.10 across the
pre-registered parameter grid, and raw benchmark alpha p-value < 0.05 vs the
committed MSFT buy-and-hold benchmark) on the same triple where the baseline
two-criterion test was already run. Verdicts are falsification outcomes,
never profitability claims.

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

from cross_sectional_momentum_hypothesis import (  # noqa: E402
    BENCHMARK_CRITERIA,
    BENCHMARK_FILE,
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


def test_benchmark_aware_hypothesis_runs_on_triple_real_window_cross_sectional_momentum():
    for name in ("AAPL.csv", "MSFT.csv", "GOOGL.csv"):
        assert (SRC / name).exists()

    with tempfile.TemporaryDirectory() as td:
        d = Path(td)
        data_path = _build_triple_csv(d)
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            result = run_benchmark_aware_hypothesis_test(data_path)

    assert isinstance(result, dict)
    assert result["verdict"] in ("SUPPORTED", "NOT SUPPORTED")
    assert result["all_pass"] in (True, False)
    assert result["all_pass"] == all(c["passed"] for c in result["criteria"])
    assert result["verdict"] == ("SUPPORTED" if result["all_pass"] else "NOT SUPPORTED")
    assert len(result["criteria"]) == 4
    assert {c["name"] for c in result["criteria"]} == {
        name for name, _, _ in BENCHMARK_CRITERIA
    }
    out = buffer.getvalue()
    assert "Chronological: True, Disjoint: True" in out
    assert "Point-in-time validation: True" in out
    assert "VERDICT:" in out
    assert "BENCHMARK" in out.upper() or "Benchmark" in out


def test_benchmark_metrics_pinned_on_triple_real_window_cross_sectional_momentum():
    """Regression guard: the benchmark-aware advertised run on the committed
    triple must reproduce the pinned strategy + benchmark metrics (net of
    costs) so a silent change to the backtest numbers is caught. Relative
    tolerance only, never exact equality. The verdict is NOT SUPPORTED:
    cross-sectional momentum loses money on the held-out split
    (total return -2.06%, Sharpe -0.39) and fares far worse than buy-and-hold
    MSFT (+90.2%), with benchmark alpha p-value 0.9366 > 0.05 and Deflated
    Sharpe p-value 0.9924 > 0.10. This is the honest pre-registered outcome;
    the test does not tune to force SUPPORT.
    """
    for name in ("AAPL.csv", "MSFT.csv", "GOOGL.csv"):
        assert (SRC / name).exists()

    with tempfile.TemporaryDirectory() as td:
        d = Path(td)
        data_path = _build_triple_csv(d)
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            result = run_benchmark_aware_hypothesis_test(data_path)

    observed = result.get("observed") or {}
    assert observed.get("benchmark_path") is not None
    assert Path(observed["benchmark_path"]).name == BENCHMARK_FILE
    assert observed.get("n_trials") == N_TRIALS

    EXPECTED = {
        "sharpe_ratio": -0.06086675336851859,
        "total_return": 0.010254526660692376,
        "benchmark_total_return": 0.1711375869976839,
        "benchmark_alpha": 0.021113008107025825,
        "benchmark_alpha_pvalue": 0.8212721599582535,
        "correlation_with_benchmark": -0.10683874181522092,
        "deflated_sharpe_pvalue": 0.9748216227579503,
    }
    REL_TOL = 1e-6
    for key, exp in EXPECTED.items():
        got = observed.get(key)
        assert got is not None, f"missing {key}"
        assert abs(got - exp) <= REL_TOL * max(abs(exp), 1e-9), (
            f"{key} regression: got {got}, expected {exp}"
        )

    # Honest verdict: none of the benchmark-aware criteria pass.
    assert result["verdict"] == "NOT SUPPORTED"
    assert result["all_pass"] is False
    failed = [c["name"] for c in result["criteria"] if not c["passed"]]
    assert "oos_sharpe_gt_zero" in failed
    assert "oos_total_return_gt_benchmark" in failed
    assert "deflated_sharpe_pvalue_lt_0.10" in failed
    assert "benchmark_alpha_pvalue_lt_0.05" in failed


if __name__ == "__main__":
    test_benchmark_aware_hypothesis_runs_on_triple_real_window_cross_sectional_momentum()
    test_benchmark_metrics_pinned_on_triple_real_window_cross_sectional_momentum()
    print("OK")

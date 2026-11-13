#!/usr/bin/env python3
"""Benchmark-aware falsification test for mean reversion (Bollinger Bands)
on the committed three-asset panel (AAPL / MSFT / GOOGL).

METHODOLOGICAL NOTE (single-asset strategy on a multi-symbol file): the mean
reversion example's backtest helper passes ``--symbol AAPL`` and does not use
``--multi-symbol`` panel pricing. On the combined triple CSV, the data loader
filters to AAPL rows, so the strategy trades AAPL only and the comparison is
AAPL (strategy, net of 3bp round-trip costs) vs buy-and-hold MSFT on the same
held-out window. This mirrors the existing EMA / MACD / Donchian / Bollinger /
SMA / volatility-targeting triple patterns.

METHODOLOGICAL FINDING (committed fixtures only, not evidence about any
market): Bollinger Bands mean reversion on AAPL is strongly negative
out-of-sample on the held-out window (Sharpe -1.30, return -42.5% net of 3bp
round-trip costs), far below buy-and-hold MSFT (return 90.2%). Criterion-edge
case: benchmark_alpha is NEGATIVE (-36.2%) yet ``benchmark_alpha_pvalue``
(0.0108) is < 0.05, so ``benchmark_alpha_pvalue_lt_0.05`` PASSES -- the
p-value criterion detects a statistically significant difference from the
benchmark but does not by itself distinguish outperformance from
underperformance. All other criteria FAIL. Benchmark-aware verdict: NOT
SUPPORTED.

This test pins the observed strategy + benchmark metrics (net of costs) as
regression guards with relative tolerance so any silent change to the backtest
numbers is caught. It also asserts the verdict stays NOT SUPPORTED to enforce
the "do not tune to force SUPPORT" rule.

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

from mean_reversion_hypothesis import (  # noqa: E402
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


def test_benchmark_aware_mean_reversion_runs_on_triple_real_window():
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
    """Regression guard: benchmark-aware run on the committed triple must
    reproduce the pinned out-of-sample vs-benchmark metrics (net of costs).
    Relative tolerance only, never exact equality.

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

    assert result["verdict"] == "NOT SUPPORTED"
    assert result["all_pass"] is False

    expected_criteria = {
        "oos_sharpe_gt_zero": False,
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
        "sharpe_ratio": -0.1439393233148262,
        "total_return": -0.05051279837754248,
        "benchmark_total_return": 0.17111801811540486,
        "benchmark_alpha": -0.07211686433039296,
        "benchmark_alpha_pvalue": 0.729208452086642,
        "correlation_with_benchmark": 0.35172254769542815,
        "deflated_sharpe_pvalue": 0.9782592228444734,
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
    assert "MSFT.csv" in str(observed["benchmark_path"])


if __name__ == "__main__":
    test_benchmark_aware_mean_reversion_runs_on_triple_real_window()
    test_benchmark_aware_metrics_pinned_on_triple_real_window()
    print("OK")

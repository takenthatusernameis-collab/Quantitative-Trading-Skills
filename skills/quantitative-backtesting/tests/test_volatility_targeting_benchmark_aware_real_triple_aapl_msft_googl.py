#!/usr/bin/env python3
"""Benchmark-aware falsification test for volatility targeting on the committed
three-asset panel (AAPL / MSFT / GOOGL).

Extends test_volatility_targeting_benchmark_aware_real_aapl.py with the
benchmark-aware run on the triple: buy-and-hold MSFT (the strongest name on
the panel, ~90% total return over the held-out window) plus the Deflated
Sharpe Ratio multiple-testing correction across the pre-registered parameter
grid (N = len(PARAM_SENSITIVITY_GRID) = 6).

METHODOLOGICAL FINDING (committed fixtures only, not evidence about any market):
volatility targeting beats a zero baseline (Sharpe 0.77, return 47.4% net of
3bp round-trip costs) but does NOT beat buy-and-hold MSFT (return 90.2%), the
benchmark alpha is not statistically significant (raw p = 0.12), and the
Deflated Sharpe p-value is not significant (p = 0.79 across 6 trials).
Benchmark-aware verdict: NOT SUPPORTED.

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

from volatility_targeting_hypothesis import (  # noqa: E402
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


def test_benchmark_aware_volatility_targeting_runs_on_triple_real_window():
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
        "sharpe_ratio": 0.5154860951632668,
        "total_return": 0.10666302954386775,
        "benchmark_total_return": 0.1711375869976839,
        "benchmark_alpha": 0.12500802155720464,
        "benchmark_alpha_pvalue": 0.33102925749727974,
        "correlation_with_benchmark": -0.298644481937308,
        "deflated_sharpe_pvalue": 0.9066863372606763,
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
    test_benchmark_aware_volatility_targeting_runs_on_triple_real_window()
    test_benchmark_aware_metrics_pinned_on_triple_real_window()
    print("OK")

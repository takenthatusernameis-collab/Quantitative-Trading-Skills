#!/usr/bin/env python3
"""Benchmark-aware falsification test for z-score mean reversion on the
committed two-asset pair (AAPL / GOOGL), benchmarked against MSFT buy-and-hold.
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

from zscore_mean_reversion_hypothesis import (  # noqa: E402
    BENCHMARK_CRITERIA,
    BENCHMARK_FILE,
    N_TRIALS,
    run_hypothesis_test,
)

SRC = SKILLS_DIR / "assets" / "example_data" / "real_market_data"


def _build_pair_csv(dest: Path) -> Path:
    frames = []
    for name in ("AAPL.csv", "GOOGL.csv"):
        frame = pd.read_csv(SRC / name)
        frame["symbol"] = Path(name).stem
        frames.append(frame)
    combined = pd.concat(frames, ignore_index=True)
    out = dest / "aapl_googl_pair.csv"
    combined.to_csv(out, index=False)
    return out


def test_benchmark_aware_hypothesis_runs_on_pair_real_window_zscore_mean_reversion():
    for name in ("AAPL.csv", "GOOGL.csv", "MSFT.csv"):
        assert (SRC / name).exists()

    with tempfile.TemporaryDirectory() as td:
        d = Path(td)
        data_path = _build_pair_csv(d)
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            result = run_hypothesis_test(
                data_path,
                "aapl_googl pair z-score mean reversion benchmark-aware real window",
                strategy="zscore_mean_reversion",
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
        name for name, _, _ in BENCHMARK_CRITERIA
    }
    out = buffer.getvalue()
    assert "Chronological: True, Disjoint: True" in out
    assert "Point-in-time validation: True" in out
    assert "VERDICT:" in out
    assert "BENCHMARK" in out.upper() or "Benchmark" in out


def test_benchmark_metrics_pinned_on_pair_real_window_zscore_mean_reversion():
    for name in ("AAPL.csv", "GOOGL.csv", "MSFT.csv"):
        assert (SRC / name).exists()

    with tempfile.TemporaryDirectory() as td:
        d = Path(td)
        data_path = _build_pair_csv(d)
        result = run_hypothesis_test(
            data_path,
            "aapl_googl pair z-score mean reversion benchmark-aware real window",
            strategy="zscore_mean_reversion",
            benchmark_path="MSFT.csv",
            n_trials=N_TRIALS,
        )

    observed = result.get("observed") or {}
    assert observed.get("benchmark_path") is not None
    assert Path(observed["benchmark_path"]).name == BENCHMARK_FILE
    assert observed.get("n_trials") == N_TRIALS

    EXPECTED = {
        "sharpe_ratio": -0.4256114742108271,
        "total_return": -0.030959664968179257,
        "benchmark_total_return": 0.9015402575236577,
        "benchmark_alpha": -0.02244377413425092,
        "benchmark_alpha_pvalue": 0.6817989101480841,
        "correlation_with_benchmark": 0.08641782414147907,
        "deflated_sharpe_pvalue": 0.9936363103320118,
    }
    REL_TOL = 1e-6
    for key, exp in EXPECTED.items():
        got = observed.get(key)
        assert got is not None, f"missing {key}"
        assert abs(got - exp) <= REL_TOL * max(abs(exp), 1e-9), (
            f"{key} regression: got {got}, expected {exp}"
        )

    assert result["verdict"] == "NOT SUPPORTED"
    assert result["all_pass"] is False
    failed = [c["name"] for c in result["criteria"] if not c["passed"]]
    assert "oos_total_return_gt_benchmark" in failed
    assert "deflated_sharpe_pvalue_lt_0.10" in failed
    assert "benchmark_alpha_pvalue_lt_0.05" in failed


if __name__ == "__main__":
    test_benchmark_aware_hypothesis_runs_on_pair_real_window_zscore_mean_reversion()
    test_benchmark_metrics_pinned_on_pair_real_window_zscore_mean_reversion()
    print("OK")
#!/usr/bin/env python3
"""
Regression tests for a falsifiable RSI mean-reversion hypothesis using run_backtest.py.
"""

import contextlib
import io
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np

SKILLS_DIR = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = SKILLS_DIR / "scripts"
EXAMPLES_DIR = SKILLS_DIR / "examples"
ASSETS_DIR = SKILLS_DIR / "assets" / "example_data"


def test_rsi_mean_reversion_hypothesis_example_exists():
    example_path = EXAMPLES_DIR / "rsi_mean_reversion_hypothesis.py"
    assert example_path.exists(), f"Missing {example_path}"
    content = example_path.read_text()
    assert "FALSIFICATION" in content
    assert "train" in content.lower() and "test" in content.lower()


def test_run_backtest_rsi_produces_results():
    data_path = ASSETS_DIR / "sample_ohlcv.csv"
    bench_path = ASSETS_DIR / "sample_benchmark.csv"
    with tempfile.TemporaryDirectory() as tmpdir:
        cmd = [
            sys.executable,
            str(SCRIPTS_DIR / "run_backtest.py"),
            "--data", str(data_path),
            "--strategy", "rsi_mean_reversion",
            "--symbol", "SPY",
            "--params", '{"period": 14, "oversold": 30, "overbought": 70, "neutral": 50}',
            "--commission", "0.0002",
            "--slippage", "0.0001",
            "--train-frac", "0.6",
            "--val-frac", "0.2",
            "--test-frac", "0.2",
            "--run-split", "test",
            "--benchmark", str(bench_path),
            "--validate-point-in-time",
            "--output", str(Path(tmpdir) / "test_metrics.json"),
        ]
        result = subprocess.run(cmd, cwd=str(SCRIPTS_DIR), capture_output=True, text=True)
        assert result.returncode == 0, f"Failed: {result.stderr}\n{result.stdout}"


def test_hypothesis_example_runs_successfully():
    example_path = EXAMPLES_DIR / "rsi_mean_reversion_hypothesis.py"
    cmd = [sys.executable, str(example_path)]
    result = subprocess.run(cmd, cwd=str(SKILLS_DIR.parent.parent), capture_output=True, text=True)
    assert result.returncode == 0, f"Failed: {result.stderr}\n{result.stdout}"
    assert "VERDICT" in result.stdout
    assert "SUPPORTED" in result.stdout or "NOT SUPPORTED" in result.stdout


def test_rsi_cost_sensitivity_sweep():
    """The cost-sensitivity sweep runs across all ascending cost levels and
    the honest directional claim holds: higher per-trade costs never improve
    net out-of-sample Sharpe or total return.

    This pins a core methodological control: sensitivity to transaction costs
    must be measured and reported, not merely stated. The sweep is a
    sensitivity analysis on the shipped sample, not evidence about any market;
    the claim is purely directional."""
    sys.path.insert(0, str(EXAMPLES_DIR))
    from rsi_mean_reversion_hypothesis import (  # noqa: E402
        COMMISSION,
        COST_SWEEP_LEVELS,
        run_cost_sweep,
    )
    data_path = ASSETS_DIR / "sample_ohlcv.csv"
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        rows = run_cost_sweep(data_path)

    assert len(rows) == len(COST_SWEEP_LEVELS), (
        f"expected {len(COST_SWEEP_LEVELS)} cost levels, got {len(rows)}"
    )
    assert [r["commission_bps"] for r in rows] == [
        c * 10_000 for c, _ in COST_SWEEP_LEVELS
    ], "cost sweep levels are not recorded in ascending order"
    assert rows[0]["commission_bps"] == 0.0 and rows[0]["slippage_bps"] == 0.0, (
        "first cost sweep level must be frictionless"
    )

    series = {
        "sharpe_ratio": "Sharpe ratio",
        "total_return": "total return",
    }
    for key, label in series.items():
        values = [r[key] for r in rows]
        assert all(v is not None and np.isfinite(v) for v in values), (
            f"{label} is missing or non-finite at one or more cost levels: {values}"
        )
        for prev, curr in zip(values, values[1:]):
            assert curr <= prev + 1e-12, (
                f"{label} does not degrade monotonically with cost: "
                f"{prev} -> {curr}"
            )

    # The advertised cost level is the middle rung of the five levels.
    advertised = next(
        r for r in rows if r["commission_bps"] == COMMISSION * 10_000
    )
    assert advertised is rows[2], (
        "the advertised cost level is not the middle rung of the sweep"
    )


if __name__ == "__main__":
    test_rsi_mean_reversion_hypothesis_example_exists()
    test_run_backtest_rsi_produces_results()
    test_hypothesis_example_runs_successfully()
    test_rsi_cost_sensitivity_sweep()
    print("All tests passed")

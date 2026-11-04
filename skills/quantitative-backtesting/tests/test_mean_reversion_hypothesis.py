#!/usr/bin/env python3
"""
Regression tests for a falsifiable mean-reversion hypothesis using run_backtest.py.
"""

import contextlib
import io
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

SKILLS_DIR = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = SKILLS_DIR / "scripts"
EXAMPLES_DIR = SKILLS_DIR / "examples"
ASSETS_DIR = SKILLS_DIR / "assets" / "example_data"
REAL_MARKET_DIR = ASSETS_DIR / "real_market_data"

sys.path.insert(0, str(EXAMPLES_DIR))

import numpy as np  # noqa: E402
from mean_reversion_hypothesis import (  # noqa: E402
    COMMISSION,
    SLIPPAGE,
    ELEVATED_COST_SWEEP_LEVELS,
    run_elevated_cost_sweep,
    run_hypothesis_test,
    run_benchmark_aware_hypothesis_test,
)


def test_mean_reversion_hypothesis_example_exists():
    example_path = EXAMPLES_DIR / "mean_reversion_hypothesis.py"
    assert example_path.exists(), f"Missing {example_path}"
    content = example_path.read_text()
    assert "FALSIFICATION" in content
    assert "train" in content.lower() and "test" in content.lower()


def test_run_backtest_bollinger_produces_results():
    data_path = ASSETS_DIR / "sample_ohlcv.csv"
    bench_path = ASSETS_DIR / "sample_benchmark.csv"
    with tempfile.TemporaryDirectory() as tmpdir:
        cmd = [
            sys.executable,
            str(SCRIPTS_DIR / "run_backtest.py"),
            "--data", str(data_path),
            "--strategy", "bollinger_bands",
            "--symbol", "SPY",
            "--params", '{"period": 20, "std_dev": 2.0}',
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
    example_path = EXAMPLES_DIR / "mean_reversion_hypothesis.py"
    cmd = [sys.executable, str(example_path)]
    result = subprocess.run(cmd, cwd=str(SKILLS_DIR.parent.parent), capture_output=True, text=True)
    assert result.returncode == 0, f"Failed: {result.stderr}\n{result.stdout}"
    assert "VERDICT" in result.stdout
    assert "SUPPORTED" in result.stdout or "NOT SUPPORTED" in result.stdout


def test_mean_reversion_cost_sensitivity_sweep():
    data_path = ASSETS_DIR / "sample_ohlcv.csv"
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        rows = run_elevated_cost_sweep(data_path)

    assert len(rows) == len(ELEVATED_COST_SWEEP_LEVELS)
    assert [r["commission_bps"] for r in rows] == [c * 10_000 for c, _ in ELEVATED_COST_SWEEP_LEVELS]
    assert rows[0]["commission_bps"] == COMMISSION * 10_000 and rows[0]["slippage_bps"] == SLIPPAGE * 10_000
    for r in rows:
        assert r["verdict"] in ("SUPPORTED", "NOT SUPPORTED")
        assert isinstance(r["criteria"], list)
        assert r["all_pass"] == all(c["passed"] for c in r["criteria"])
    for key in ("sharpe_ratio", "total_return"):
        values = [r[key] for r in rows]
        assert all(v is not None and np.isfinite(v) for v in values)
        for prev, curr in zip(values, values[1:]):
            assert curr <= prev + 1e-12


def test_hypothesis_reports_its_bias_controls_on_real_market_data():
    assert (REAL_MARKET_DIR / "MSFT.csv").exists(), "MSFT fixture missing"
    assert (REAL_MARKET_DIR / "GOOGL.csv").exists(), "GOOGL fixture missing"

    with tempfile.TemporaryDirectory() as td:
        d = Path(td)
        shutil.copyfile(REAL_MARKET_DIR / "MSFT.csv", d / "sample_ohlcv.csv")
        shutil.copyfile(REAL_MARKET_DIR / "GOOGL.csv", d / "sample_benchmark.csv")
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            run_hypothesis_test(d / "sample_ohlcv.csv", "test")
        out = buffer.getvalue()

    assert "Split sizes (train/val/test):" in out
    assert "Chronological: True, Disjoint: True" in out
    assert "Point-in-time validation: True" in out


def test_hypothesis_runs_on_msft_googl_real_window():
    assert (REAL_MARKET_DIR / "MSFT.csv").exists(), "MSFT fixture missing"
    assert (REAL_MARKET_DIR / "GOOGL.csv").exists(), "GOOGL fixture missing"

    with tempfile.TemporaryDirectory() as td:
        d = Path(td)
        shutil.copyfile(REAL_MARKET_DIR / "MSFT.csv", d / "sample_ohlcv.csv")
        shutil.copyfile(REAL_MARKET_DIR / "GOOGL.csv", d / "sample_benchmark.csv")
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            result = run_hypothesis_test(d / "sample_ohlcv.csv", "test")
        out = buffer.getvalue()

    assert isinstance(result, dict)
    assert result["verdict"] in ("SUPPORTED", "NOT SUPPORTED")
    assert result["all_pass"] in (True, False)
    assert result["all_pass"] == all(c["passed"] for c in result["criteria"])
    assert result["verdict"] == ("SUPPORTED" if result["all_pass"] else "NOT SUPPORTED")
    assert len(result["criteria"]) == 4
    assert set([c["name"] for c in result["criteria"]]) == {
        "oos_sharpe_gt_zero",
        "oos_total_return_gt_benchmark",
        "deflated_sharpe_pvalue_lt_0.10",
        "benchmark_alpha_pvalue_lt_0.05",
    }
    assert "VERDICT:" in out
    assert "Chronological: True, Disjoint: True" in out
    assert "Point-in-time validation: True" in out


if __name__ == "__main__":
    test_mean_reversion_hypothesis_example_exists()
    test_run_backtest_bollinger_produces_results()
    test_hypothesis_example_runs_successfully()
    test_mean_reversion_cost_sensitivity_sweep()
    test_hypothesis_reports_its_bias_controls_on_real_market_data()
    test_hypothesis_runs_on_msft_googl_real_window()
    print("All tests passed")

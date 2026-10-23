#!/usr/bin/env python3
"""
Regression tests for a falsifiable RSI mean-reversion hypothesis using run_backtest.py.
"""

import subprocess
import sys
import tempfile
from pathlib import Path

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


if __name__ == "__main__":
    test_rsi_mean_reversion_hypothesis_example_exists()
    test_run_backtest_rsi_produces_results()
    test_hypothesis_example_runs_successfully()
    print("All tests passed")

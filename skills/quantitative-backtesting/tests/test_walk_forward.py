#!/usr/bin/env python3
"""
Unit tests for walk_forward.py: parameter_optimization and walk_forward_analysis.

Run with: python3 skills/quantitative-backtesting/tests/test_walk_forward.py
No third-party test framework is required; uses only the standard library.
"""

import json
import os
import sys
import tempfile
import traceback
from pathlib import Path
from io import StringIO
from contextlib import redirect_stdout, redirect_stderr

import numpy as np
import pandas as pd

SKILLS_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SKILLS_DIR / "scripts"))

from walk_forward import (  # noqa: E402
    overfitting_check,
    parameter_optimization,
    signals_active,
    walk_forward_analysis,
    cpcv_analysis,
    monte_carlo_simulation,
    deflated_sharpe_ratio,
    run_walk_forward,
    run_cpcv,
    run_parameter_optimization,
    run_monte_carlo,
    run_out_of_sample_validation,
    out_of_sample_validation,
    _make_strategy_factory,
    _parse_param_grid,
    _annualization_factor,
    _calculate_strategy_returns,
    _split_train_val_test,
    _verify_split_separation,
    main as walk_forward_main,
)
from strategy_builder import build_strategy  # noqa: E402
from data_loader import load_data  # noqa: E402


def _make_ohlcv_data(periods: int = 300, seed: int = 42) -> pd.DataFrame:
    """Create OHLCV data for testing."""
    rng = np.random.default_rng(seed)
    dates = pd.date_range("2020-01-01", periods=periods, freq="B")
    # Create trending data with some noise
    trend = np.linspace(0, 0.5, periods)  # 50% total trend over periods
    noise = rng.normal(0, 0.01, periods)
    returns = trend / periods + noise  # Small daily returns plus trend
    prices = 100 * np.exp(np.cumsum(returns))

    return pd.DataFrame({
        "open": prices * rng.uniform(0.995, 1.005, periods),
        "high": prices * rng.uniform(1.005, 1.02, periods),
        "low": prices * rng.uniform(0.98, 0.995, periods),
        "close": prices,
        "volume": rng.integers(1_000_000, 10_000_000, periods),
    }, index=dates)


def _make_benchmark_data(periods: int = 300, seed: int = 99) -> pd.DataFrame:
    """Create benchmark OHLCV data for testing."""
    rng = np.random.default_rng(seed)
    dates = pd.date_range("2020-01-01", periods=periods, freq="B")
    # Create benchmark with different trend
    trend = np.linspace(0, 0.3, periods)  # 30% total trend
    noise = rng.normal(0, 0.008, periods)
    returns = trend / periods + noise
    prices = 100 * np.exp(np.cumsum(returns))

    return pd.DataFrame({
        "open": prices * rng.uniform(0.995, 1.005, periods),
        "high": prices * rng.uniform(1.005, 1.02, periods),
        "low": prices * rng.uniform(0.98, 0.995, periods),
        "close": prices,
        "volume": rng.integers(1_000_000, 10_000_000, periods),
    }, index=dates)


def _write_ohlcv_csv(path: str, periods: int = 300, seed: int = 42) -> None:
    """Write OHLCV data to CSV for CLI testing."""
    data = _make_ohlcv_data(periods, seed)
    data.reset_index().rename(columns={"index": "date"}).to_csv(path, index=False)


def _write_benchmark_csv(path: str, periods: int = 300, seed: int = 99) -> None:
    """Write benchmark OHLCV data to CSV for CLI testing."""
    data = _make_benchmark_data(periods, seed)
    data.reset_index().rename(columns={"index": "date"}).to_csv(path, index=False)


def test_out_of_sample_validation_benchmark_cost_is_periodic():
    """Test that out_of_sample_validation correctly handles benchmark_cost_is_periodic flag."""
    # Create test data with sufficient periods for walk-forward windows
    data = _make_ohlcv_data(periods=300, seed=42)
    benchmark = _make_benchmark_data(periods=300, seed=99)

    # Use a simple built-in strategy
    strategy_type = "sma_crossover"
    # Parameter grid - small grid for testing
    param_grid = {
        "fast_period": [3, 5],
        "slow_period": [8, 10]
    }

    # Run out_of_sample_validation with benchmark_cost_is_periodic=False
    results_false = out_of_sample_validation(
        data=data,
        strategy_factory=lambda params: build_strategy(strategy_type, json.dumps(params)),
        param_grid=param_grid,
        train_frac=0.6,
        val_frac=0.2,
        test_frac=0.2,
        validation_method="walk_forward",
        walk_forward_train_months=6,
        walk_forward_test_months=2,
        walk_forward_step_months=2,
        initial_capital=100000,
        commission=0.0002,
        slippage=0.0001,
        benchmark=benchmark,
        total_return_benchmark=False,
        benchmark_commission=0.001,
        benchmark_slippage=0.001,
        benchmark_expense_ratio=0.0,
        benchmark_cost_is_periodic=False,  # Round-trip costs
    )

    # Run out_of_sample_validation with benchmark_cost_is_periodic=True
    results_true = out_of_sample_validation(
        data=data,
        strategy_factory=lambda params: build_strategy(strategy_type, json.dumps(params)),
        param_grid=param_grid,
        train_frac=0.6,
        val_frac=0.2,
        test_frac=0.2,
        validation_method="walk_forward",
        walk_forward_train_months=6,
        walk_forward_test_months=2,
        walk_forward_step_months=2,
        initial_capital=100000,
        commission=0.0002,
        slippage=0.0001,
        benchmark=benchmark,
        total_return_benchmark=False,
        benchmark_commission=0.001,
        benchmark_slippage=0.001,
        benchmark_expense_ratio=0.0,
        benchmark_cost_is_periodic=True,  # Periodic costs
    )

    # Verify that both runs succeeded
    assert results_false is not None, "results_false should not be None"
    assert results_true is not None, "results_true should not be None"
    assert "test_performance" in results_false, "'test_performance' should be in results_false"
    assert "test_performance" in results_true, "'test_performance' should be in results_true"

    # Extract benchmark stats from test performance
    bench_false = results_false["test_performance"]
    bench_true = results_true["test_performance"]

    # Both should have benchmark metrics since we provided a benchmark
    assert "benchmark_total_return" in bench_false, f"'benchmark_total_return' should be in bench_false. Keys: {list(bench_false.keys())}"
    assert "benchmark_total_return" in bench_true, f"'benchmark_total_return' should be in bench_true. Keys: {list(bench_true.keys())}"
    assert "benchmark_cost_is_periodic" in bench_false, f"'benchmark_cost_is_periodic' should be in bench_false. Keys: {list(bench_false.keys())}"
    assert "benchmark_cost_is_periodic" in bench_true, f"'benchmark_cost_is_periodic' should be in bench_true. Keys: {list(bench_true.keys())}"

    # Verify the flag is correctly recorded
    assert bench_false["benchmark_cost_is_periodic"] is False, f"Expected False, got {bench_false['benchmark_cost_is_periodic']}"
    assert bench_true["benchmark_cost_is_periodic"] is True, f"Expected True, got {bench_true['benchmark_cost_is_periodic']}"

    # The key test is that the flag is correctly propagated and recorded
    # We can also verify that the benchmark returns are different (though this depends on the data)
    bench_return_false = bench_false["benchmark_total_return"]
    bench_return_true = bench_true["benchmark_total_return"]

    # Log the values for informational purposes
    print(f"Benchmark return (round-trip): {bench_return_false:.6f}")
    print(f"Benchmark return (periodic): {bench_return_true:.6f}")

    # Also verify that the flag appears in the summary
    assert "summary" in results_false, "'summary' should be in results_false"
    assert "summary" in results_true, "'summary' should be in results_true"
    # The summary should contain the benchmark info from test_performance
    # since out_of_sample_validation updates summary with test_benchmark for single benchmark
    summary_false = results_false["summary"]
    summary_true = results_true["summary"]

    # Check that the flag is in the summary (it should be there from the test phase)
    # Note: For single benchmark, out_of_sample_validation does: summary.update(test_benchmark)
    # So the benchmark_cost_is_periodic should be in the summary
    assert "benchmark_cost_is_periodic" in summary_false, f"'benchmark_cost_is_periodic' should be in summary_false. Keys: {list(summary_false.keys())}"
    assert "benchmark_cost_is_periodic" in summary_true, f"'benchmark_cost_is_periodic' should be in summary_true. Keys: {list(summary_true.keys())}"

    assert summary_false["benchmark_cost_is_periodic"] is False, f"Expected False in summary, got {summary_false['benchmark_cost_is_periodic']}"
    assert summary_true["benchmark_cost_is_periodic"] is True, f"Expected True in summary, got {summary_true['benchmark_cost_is_periodic']}"


def test_out_of_sample_validation_benchmark_cost_is_periodic_cpcv():
    """Test that out_of_sample_validation with CPCV correctly handles benchmark_cost_is_periodic flag."""
    data = _make_ohlcv_data(periods=500, seed=42)
    benchmark = _make_benchmark_data(periods=500, seed=99)
    strategy_type = "sma_crossover"
    param_grid = {"fast_period": [3, 5, 7], "slow_period": [10, 12, 15]}

    results_false = out_of_sample_validation(
        data=data,
        strategy_factory=lambda params: build_strategy(strategy_type, json.dumps(params)),
        param_grid=param_grid,
        train_frac=0.6, val_frac=0.2, test_frac=0.2,
        validation_method="cpcv",
        cpcv_n_splits=5,
        cpcv_test_size=0.2,
        initial_capital=100000,
        commission=0.0002,
        slippage=0.0001,
        benchmark=benchmark,
        total_return_benchmark=False,
        benchmark_commission=0.001,
        benchmark_slippage=0.001,
        benchmark_expense_ratio=0.0,
        benchmark_cost_is_periodic=False,
    )

    results_true = out_of_sample_validation(
        data=data,
        strategy_factory=lambda params: build_strategy(strategy_type, json.dumps(params)),
        param_grid=param_grid,
        train_frac=0.6, val_frac=0.2, test_frac=0.2,
        validation_method="cpcv",
        cpcv_n_splits=5,
        cpcv_test_size=0.2,
        initial_capital=100000,
        commission=0.0002,
        slippage=0.0001,
        benchmark=benchmark,
        total_return_benchmark=False,
        benchmark_commission=0.001,
        benchmark_slippage=0.001,
        benchmark_expense_ratio=0.0,
        benchmark_cost_is_periodic=True,
    )

    assert results_false is not None
    assert results_true is not None
    assert "test_performance" in results_false
    assert "test_performance" in results_true
    bench_false = results_false["test_performance"]
    bench_true = results_true["test_performance"]
    assert bench_false is not None
    assert bench_true is not None
    assert "benchmark_total_return" in bench_false
    assert "benchmark_cost_is_periodic" in bench_false
    assert bench_false["benchmark_cost_is_periodic"] is False
    assert bench_true["benchmark_cost_is_periodic"] is True
    assert "summary" in results_false
    summary_false = results_false["summary"]
    summary_true = results_true["summary"]
    assert "benchmark_cost_is_periodic" in summary_false
    assert summary_true["benchmark_cost_is_periodic"] is True


def test_cli_out_of_sample_benchmark_cost_is_periodic():
    """CLI end-to-end test for out-of-sample with --benchmark-cost-is-periodic flag.

    Verifies that the flag is correctly parsed and propagated through the
    out-of-sample validation pipeline, and that the benchmark_cost_is_periodic
    field is recorded in the output summary.
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        csv_path = os.path.join(tmpdir, "data.csv")
        bench_path = os.path.join(tmpdir, "benchmark.csv")
        _write_ohlcv_csv(csv_path, periods=500)
        _write_benchmark_csv(bench_path, periods=500)
        out_dir = os.path.join(tmpdir, "out")
        argv = [
            "walk_forward", "out-of-sample",
            "--data", csv_path,
            "--benchmark", bench_path,
            "--strategy", "sma_crossover",
            "--param-grid", '{"fast_period": [3, 5], "slow_period": [8, 10]}',
            "--output", out_dir,
            "--benchmark-commission", "0.001",
            "--benchmark-slippage", "0.001",
            "--benchmark-cost-is-periodic",
            "--wf-train-months", "6",
            "--wf-test-months", "2",
            "--wf-step-months", "2",
        ]
        with patch.object(sys, "argv", argv), \
                redirect_stdout(StringIO()), redirect_stderr(StringIO()):
            rc = walk_forward_main()

        assert rc == 0, "CLI with --benchmark-cost-is-periodic should exit 0"

        # Check that the summary JSON contains the benchmark_cost_is_periodic flag
        summary_path = os.path.join(out_dir, "out_of_sample_summary.json")
        assert os.path.exists(summary_path), "out_of_sample_summary.json not written"
        with open(summary_path) as f:
            summary = json.load(f)

        # The flag should be in the test_benchmark section
        assert "test_benchmark" in summary, "test_benchmark missing from summary"
        if isinstance(summary["test_benchmark"], list):
            # Multiple benchmarks case (not expected here)
            pass
        else:
            assert "benchmark_cost_is_periodic" in summary["test_benchmark"], \
                f"benchmark_cost_is_periodic missing from test_benchmark. Keys: {list(summary['test_benchmark'].keys())}"
            assert summary["test_benchmark"]["benchmark_cost_is_periodic"] is True, \
                f"Expected benchmark_cost_is_periodic=True, got {summary['test_benchmark']['benchmark_cost_is_periodic']}"

        # Also verify it's in the config
        assert "config" in summary, "config missing from summary"
        assert "benchmark_cost_is_periodic" in summary["config"], \
            f"benchmark_cost_is_periodic missing from config. Keys: {list(summary['config'].keys())}"
        assert summary["config"]["benchmark_cost_is_periodic"] is True, \
            f"Expected benchmark_cost_is_periodic=True in config, got {summary['config']['benchmark_cost_is_periodic']}"


def test_cli_out_of_sample_benchmark_cost_is_periodic_false():
    """CLI end-to-end test for out-of-sample without --benchmark-cost-is-periodic flag (default False).

    Verifies that when the flag is not provided, it defaults to False and is
    correctly recorded in the output summary.
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        csv_path = os.path.join(tmpdir, "data.csv")
        bench_path = os.path.join(tmpdir, "benchmark.csv")
        _write_ohlcv_csv(csv_path, periods=500)
        _write_benchmark_csv(bench_path, periods=500)
        out_dir = os.path.join(tmpdir, "out")
        argv = [
            "walk_forward", "out-of-sample",
            "--data", csv_path,
            "--benchmark", bench_path,
            "--strategy", "sma_crossover",
            "--param-grid", '{"fast_period": [3, 5], "slow_period": [8, 10]}',
            "--output", out_dir,
            "--benchmark-commission", "0.001",
            "--benchmark-slippage", "0.001",
            # Note: --benchmark-cost-is-periodic NOT provided (should default to False)
            "--wf-train-months", "6",
            "--wf-test-months", "2",
            "--wf-step-months", "2",
        ]
        with patch.object(sys, "argv", argv), \
                redirect_stdout(StringIO()), redirect_stderr(StringIO()):
            rc = walk_forward_main()

        assert rc == 0, "CLI without --benchmark-cost-is-periodic should exit 0"

        # Check that the summary JSON contains the benchmark_cost_is_periodic flag as False
        summary_path = os.path.join(out_dir, "out_of_sample_summary.json")
        assert os.path.exists(summary_path), "out_of_sample_summary.json not written"
        with open(summary_path) as f:
            summary = json.load(f)

        # The flag should be in the test_benchmark section
        assert "test_benchmark" in summary, "test_benchmark missing from summary"
        if isinstance(summary["test_benchmark"], list):
            pass
        else:
            assert "benchmark_cost_is_periodic" in summary["test_benchmark"], \
                f"benchmark_cost_is_periodic missing from test_benchmark. Keys: {list(summary['test_benchmark'].keys())}"
            assert summary["test_benchmark"]["benchmark_cost_is_periodic"] is False, \
                f"Expected benchmark_cost_is_periodic=False, got {summary['test_benchmark']['benchmark_cost_is_periodic']}"

        # Also verify it's in the config as False
        assert "config" in summary, "config missing from summary"
        assert "benchmark_cost_is_periodic" in summary["config"], \
            f"benchmark_cost_is_periodic missing from config. Keys: {list(summary['config'].keys())}"
        assert summary["config"]["benchmark_cost_is_periodic"] is False, \
            f"Expected benchmark_cost_is_periodic=False in config, got {summary['config']['benchmark_cost_is_periodic']}"


def test_cli_out_of_sample_benchmark_cost_is_periodic_cpcv():
    """CLI end-to-end test for out-of-sample with CPCV validation and --benchmark-cost-is-periodic flag.

    Verifies that the flag works correctly when using CPCV as the validation method.
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        csv_path = os.path.join(tmpdir, "data.csv")
        bench_path = os.path.join(tmpdir, "benchmark.csv")
        _write_ohlcv_csv(csv_path, periods=800)
        _write_benchmark_csv(bench_path, periods=800)
        out_dir = os.path.join(tmpdir, "out")
        argv = [
            "walk_forward", "out-of-sample",
            "--data", csv_path,
            "--benchmark", bench_path,
            "--strategy", "sma_crossover",
            "--param-grid", '{"fast_period": [3, 5, 7], "slow_period": [10, 12, 15]}',
            "--output", out_dir,
            "--benchmark-commission", "0.001",
            "--benchmark-slippage", "0.001",
            "--benchmark-cost-is-periodic",
            "--validation-method", "cpcv",
            "--cpcv-n-splits", "5",
            "--cpcv-test-size", "0.2",
        ]
        with patch.object(sys, "argv", argv), \
                redirect_stdout(StringIO()), redirect_stderr(StringIO()):
            rc = walk_forward_main()

        assert rc == 0, "CLI with CPCV and --benchmark-cost-is-periodic should exit 0"

        # Check that the summary JSON contains the benchmark_cost_is_periodic flag
        summary_path = os.path.join(out_dir, "out_of_sample_summary.json")
        assert os.path.exists(summary_path), "out_of_sample_summary.json not written"
        with open(summary_path) as f:
            summary = json.load(f)

        assert "test_benchmark" in summary, "test_benchmark missing from summary"
        if isinstance(summary["test_benchmark"], list):
            pass
        else:
            assert "benchmark_cost_is_periodic" in summary["test_benchmark"], \
                f"benchmark_cost_is_periodic missing from test_benchmark. Keys: {list(summary['test_benchmark'].keys())}"
            assert summary["test_benchmark"]["benchmark_cost_is_periodic"] is True, \
                f"Expected benchmark_cost_is_periodic=True, got {summary['test_benchmark']['benchmark_cost_is_periodic']}"

        # Also verify it's in the config
        assert "config" in summary, "config missing from summary"
        assert "benchmark_cost_is_periodic" in summary["config"], \
            f"benchmark_cost_is_periodic missing from config. Keys: {list(summary['config'].keys())}"
        assert summary["config"]["benchmark_cost_is_periodic"] is True, \
            f"Expected benchmark_cost_is_periodic=True in config, got {summary['config']['benchmark_cost_is_periodic']}"


# Need to import patch for mocking
from unittest.mock import patch


def main() -> int:
    tests = [
        ("test_out_of_sample_validation_benchmark_cost_is_periodic", test_out_of_sample_validation_benchmark_cost_is_periodic),
        ("test_out_of_sample_validation_benchmark_cost_is_periodic_cpcv", test_out_of_sample_validation_benchmark_cost_is_periodic_cpcv),
        ("test_cli_out_of_sample_benchmark_cost_is_periodic", test_cli_out_of_sample_benchmark_cost_is_periodic),
        ("test_cli_out_of_sample_benchmark_cost_is_periodic_false", test_cli_out_of_sample_benchmark_cost_is_periodic_false),
        ("test_cli_out_of_sample_benchmark_cost_is_periodic_cpcv", test_cli_out_of_sample_benchmark_cost_is_periodic_cpcv),
    ]

    failures = 0
    for name, fn in tests:
        try:
            fn()
            print(f"PASS  {name}")
        except Exception as e:
            failures += 1
            print(f"FAIL  {name}: {e}")
            traceback.print_exc()

    print(f"\n{len(tests) - failures}/{len(tests)} tests passed")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
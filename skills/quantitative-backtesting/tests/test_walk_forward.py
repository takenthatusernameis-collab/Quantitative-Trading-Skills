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
    _benchmark_stats_with_splits,
    _add_benchmark_to_summary,
    _benchmark_list_alpha_correction,
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


def _make_benchmark_data_with_splits(periods: int = 50, split_at: int = 20, seed: int = 88) -> pd.DataFrame:
    """Create benchmark OHLCV data with a stock-split column for testing.

    The close prices are generated at the POST-SPLIT price level on and after
    the split date.  Pre-split dates carry the pre-split (higher) price level.
    The ``splits`` column records the split ratio (2.0 for a 2-for-1 split).
    """
    rng = np.random.default_rng(seed)
    dates = pd.date_range("2020-01-01", periods=periods, freq="B")
    trend = np.linspace(0, 0.3, periods)
    noise = rng.normal(0, 0.008, periods)
    daily_returns = trend / periods + noise
    prices = 100 * np.exp(np.cumsum(daily_returns))

    splits = np.ones(periods)
    splits[split_at] = 2.0

    # Post-split prices are halved to simulate a 2-for-1 split
    close = prices.copy()
    close[split_at:] = close[split_at:] / 2.0

    return pd.DataFrame({
        "open": close * rng.uniform(0.995, 1.005, periods),
        "high": close * rng.uniform(1.005, 1.02, periods),
        "low": close * rng.uniform(0.98, 0.995, periods),
        "close": close,
        "volume": rng.integers(1_000_000, 10_000_000, periods),
        "splits": splits,
    }, index=dates)


def test_benchmark_stats_with_splits_runs_without_error():
    """_benchmark_stats_with_splits must be defined and callable with splits data."""
    dates = pd.date_range("2020-01-01", periods=50, freq="B")
    rng = np.random.default_rng(42)
    strategy_returns = pd.Series(rng.normal(0.001, 0.02, 50), index=dates)

    benchmark_data = _make_benchmark_data_with_splits(periods=50, split_at=20)
    benchmark_returns = benchmark_data["close"].pct_change()
    _, aligned_bench = strategy_returns.align(benchmark_returns, join="inner")
    aligned_bench = aligned_bench.dropna()

    stats = _benchmark_stats_with_splits(
        strategy_returns, aligned_bench, 252,
        total_return_benchmark=False,
        benchmark_commission=0.001,
        benchmark_slippage=0.001,
        benchmark_expense_ratio=0.0,
        benchmark_cost_is_periodic=True,
        benchmark_data=benchmark_data,
    )
    assert "benchmark_total_return" in stats, f"Expected benchmark_total_return in stats. Keys: {list(stats.keys())}"
    assert stats["benchmark_cost_is_periodic"] is True
    assert "alpha" in stats
    assert "beta" in stats
    assert "correlation_with_benchmark" in stats


def test_benchmark_stats_with_splits_uses_adjusted_returns():
    """_benchmark_stats_with_splits should adjust prices for splits, producing
    different returns than the raw (unadjusted) close-to-close returns."""
    dates = pd.date_range("2020-01-01", periods=50, freq="B")
    rng = np.random.default_rng(42)
    strategy_returns = pd.Series(rng.normal(0.001, 0.02, 50), index=dates)

    benchmark_data = _make_benchmark_data_with_splits(periods=50, split_at=20)
    raw_returns = benchmark_data["close"].pct_change()
    _, aligned_raw = strategy_returns.align(raw_returns, join="inner")
    aligned_raw = aligned_raw.dropna()

    from data_loader import adjust_for_splits
    adjusted = adjust_for_splits(benchmark_data)
    adjusted_returns = adjusted["close"].pct_change()
    _, aligned_adj = strategy_returns.align(adjusted_returns, join="inner")
    aligned_adj = aligned_adj.dropna()

    # The adjusted returns should differ from raw returns (adjustment happened)
    assert not aligned_raw.equals(aligned_adj), (
        "Split-adjusted returns should differ from raw returns"
    )

    # Both should produce stats without error
    stats_raw = _benchmark_stats_with_splits(
        strategy_returns, aligned_raw, 252,
        benchmark_data=benchmark_data,
    )
    stats_adj = _benchmark_stats_with_splits(
        strategy_returns, aligned_adj, 252,
        benchmark_data=benchmark_data,
    )
    assert "benchmark_total_return" in stats_raw
    assert "benchmark_total_return" in stats_adj


def test_add_benchmark_to_summary_splits_path():
    """_add_benchmark_to_summary should route to splits-aware path without NameError."""
    dates = pd.date_range("2020-01-01", periods=50, freq="B")
    rng = np.random.default_rng(42)
    strategy_returns = pd.Series(rng.normal(0.001, 0.02, 50), index=dates)

    benchmark_data = _make_benchmark_data_with_splits(periods=50, split_at=20)
    benchmark_returns = benchmark_data["close"].pct_change()
    _, aligned_bench = strategy_returns.align(benchmark_returns, join="inner")
    aligned_bench = aligned_bench.dropna()

    summary = {}
    summary = _add_benchmark_to_summary(
        summary, strategy_returns, aligned_bench,
        commission=0.001, slippage=0.001,
        benchmark_expense_ratio=0.0,
        total_return_benchmark=False,
        benchmark_cost_is_periodic=True,
        benchmark_data=benchmark_data,
    )
    assert "benchmark_total_return" in summary, f"Keys: {list(summary.keys())}"
    assert summary["benchmark_cost_is_periodic"] is True


def test_out_of_sample_validation_with_splits():
    """out_of_sample_validation should handle benchmark data with splits + periodic costs."""
    data = _make_ohlcv_data(periods=300, seed=42)
    benchmark = _make_benchmark_data_with_splits(periods=300, split_at=100)

    strategy_type = "sma_crossover"
    param_grid = {"fast_period": [3, 5], "slow_period": [8, 10]}

    results = out_of_sample_validation(
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
        benchmark_cost_is_periodic=True,
    )

    assert results is not None
    assert "test_benchmark" in results
    assert "summary" in results
    test_bench = results["test_benchmark"]
    if isinstance(test_bench, dict):
        assert test_bench.get("benchmark_cost_is_periodic") is True


def test_calculate_metrics_deflated_alpha_with_benchmark_list():
    """calculate_metrics with benchmark_list produces deflated_alpha via walk_forward.deflated_alpha_ratio.

    This integration test verifies the deflated alpha path through calculate_metrics
    when multiple benchmarks are provided via benchmark_list. The test generates
    correlated return series, passes them to calculate_metrics, and asserts the
    deflated_alpha dict has all expected fields with sensible values.
    """
    from performance import calculate_metrics

    # Generate correlated returns for strategy and multiple benchmarks
    np.random.seed(42)
    periods = 252
    dates = pd.date_range("2020-01-01", periods=periods, freq="B")

    # Strategy returns with some skill
    strategy_rets = pd.Series(
        np.random.normal(0.0008, 0.015, periods),
        index=dates
    )

    # Benchmark 1: correlated with strategy
    bench1 = strategy_rets * 0.6 + pd.Series(np.random.normal(0.0003, 0.01, periods), index=dates)
    bench1 = bench1.iloc[: len(strategy_rets)]

    # Benchmark 2: different correlation structure
    bench2 = strategy_rets * 0.4 + pd.Series(np.random.normal(0.0005, 0.012, periods), index=dates)
    bench2 = bench2.iloc[: len(strategy_rets)]

    metrics = calculate_metrics({
        "returns": strategy_rets,
        "benchmark_list": [bench1, bench2],
        "config": {
            "total_return_benchmark": False,
            "benchmark_commission": 0.0,
            "benchmark_slippage": 0.0,
            "benchmark_expense_ratio": 0.0,
        },
    })

    # Verify deflated_alpha is present with all expected fields
    assert "deflated_alpha" in metrics, f"deflated_alpha missing from metrics. Keys: {list(metrics.keys())}"
    da = metrics["deflated_alpha"]

    required_keys = (
        "deflated_alpha_ratio", "p_value", "alpha", "expected_max_alpha",
        "n_benchmarks", "n_observations", "skewness", "kurtosis", "z_score"
    )
    for key in required_keys:
        assert key in da, f"missing key {key} in deflated_alpha"

    # Verify values are sensible
    assert da["n_benchmarks"] == 2, f"Expected n_benchmarks=2, got {da['n_benchmarks']}"
    assert 0.0 <= da["deflated_alpha_ratio"] <= 1.0, f"DAR out of range: {da['deflated_alpha_ratio']}"
    assert 0.0 <= da["p_value"] <= 1.0, f"p-value out of range: {da['p_value']}"
    assert np.isfinite(da["skewness"]), f"skewness not finite: {da['skewness']}"
    assert np.isfinite(da["kurtosis"]), f"kurtosis not finite: {da['kurtosis']}"
    assert np.isfinite(da["alpha"]), f"alpha not finite: {da['alpha']}"
    assert da["n_observations"] == periods, f"Expected n_observations={periods}, got {da['n_observations']}"

    # Verify individual benchmark metrics are also present
    assert "benchmark_0_benchmark_total_return" in metrics
    assert "benchmark_1_benchmark_total_return" in metrics
    assert "benchmark_0_alpha" in metrics
    assert "benchmark_1_alpha" in metrics


def test_cli_cpcv_benchmark_cost_is_periodic():
    """CLI end-to-end test for CPCV subcommand with --benchmark-cost-is-periodic flag.

    Verifies that the flag is correctly parsed and propagated through the
    CPCV pipeline, and that the benchmark_cost_is_periodic field is recorded
    in the output summary.
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        csv_path = os.path.join(tmpdir, "data.csv")
        bench_path = os.path.join(tmpdir, "benchmark.csv")
        _write_ohlcv_csv(csv_path, periods=800)
        _write_benchmark_csv(bench_path, periods=800)
        out_dir = os.path.join(tmpdir, "out")
        argv = [
            "walk_forward", "cpcv",
            "--data", csv_path,
            "--benchmark", bench_path,
            "--strategy", "sma_crossover",
            "--param-grid", '{"fast_period": [3, 5, 7], "slow_period": [10, 12, 15]}',
            "--output", out_dir,
            "--benchmark-commission", "0.001",
            "--benchmark-slippage", "0.001",
            "--benchmark-cost-is-periodic",
            "--n-splits", "5",
            "--test-size", "0.2",
        ]
        with patch.object(sys, "argv", argv), \
                redirect_stdout(StringIO()), redirect_stderr(StringIO()):
            rc = walk_forward_main()

        assert rc == 0, "CLI cpcv with --benchmark-cost-is-periodic should exit 0"

        # Check that the summary JSON contains the benchmark_cost_is_periodic flag
        summary_path = os.path.join(out_dir, "cpcv_summary.json")
        assert os.path.exists(summary_path), "cpcv_summary.json not written"
        with open(summary_path) as f:
            summary = json.load(f)

        # The flag should be in the summary (added by _add_benchmark_to_summary)
        assert "summary" in summary, "summary missing from cpcv_summary.json"
        cpcv_summary = summary["summary"]
        assert "benchmark_cost_is_periodic" in cpcv_summary, \
            f"benchmark_cost_is_periodic missing from summary. Keys: {list(cpcv_summary.keys())}"
        assert cpcv_summary["benchmark_cost_is_periodic"] is True, \
            f"Expected benchmark_cost_is_periodic=True, got {cpcv_summary['benchmark_cost_is_periodic']}"

        # Also verify it's in the config
        assert "config" in summary, "config missing from summary"
        assert "benchmark_cost_is_periodic" in summary["config"], \
            f"benchmark_cost_is_periodic missing from config. Keys: {list(summary['config'].keys())}"
        assert summary["config"]["benchmark_cost_is_periodic"] is True, \
            f"Expected benchmark_cost_is_periodic=True in config, got {summary['config']['benchmark_cost_is_periodic']}"


# Need to import patch for mocking
from unittest.mock import patch


def test_benchmark_list_alpha_correction_deflated_alpha():
    """_benchmark_list_alpha_correction applies the Deflated Alpha Ratio across
    >= 2 benchmarks and returns per-benchmark stats plus an aggregate dict.

    This is the shared correction used by the CPCV and walk-forward pipelines,
    so it is worth covering directly (fast, deterministic, no strategy needed).
    """
    periods = 252
    dates = pd.date_range("2020-01-01", periods=periods, freq="B")
    bench1 = _make_benchmark_data(periods=periods, seed=99)
    bench2 = _make_benchmark_data(periods=periods, seed=7)
    strategy_returns = pd.Series(
        np.random.default_rng(123).normal(0.0005, 0.012, periods), index=dates
    )

    result = _benchmark_list_alpha_correction(
        strategy_returns, [bench1, bench2],
        benchmark_commission=0.001, benchmark_slippage=0.001,
        benchmark_cost_is_periodic=True,
    )
    assert result["n_benchmarks"] == 2
    assert isinstance(result["per_benchmark"], list)
    assert len(result["per_benchmark"]) == 2
    for stats in result["per_benchmark"]:
        assert stats is not None, "Expected non-None benchmark stats"
        assert "alpha" in stats, "Expected 'alpha' in per-benchmark stats"
        assert "deflated_alpha" in stats, "Per-benchmark deflated_alpha not surfaced"
        assert "alpha_pvalue_original" in stats, "Expected corrected p-value metadata"

    assert result["deflated_alpha"] is not None, "Expected aggregate deflated_alpha dict"
    da = result["deflated_alpha"]
    for key in ("deflated_alpha_ratio", "p_value", "alpha", "expected_max_alpha",
                "n_benchmarks", "n_observations", "skewness", "kurtosis", "z_score"):
        assert key in da, f"missing key {key} in deflated_alpha"
    assert da["n_benchmarks"] == 2, f"Expected n_benchmarks=2, got {da['n_benchmarks']}"
    assert 0.0 <= da["deflated_alpha_ratio"] <= 1.0, f"DAR out of range: {da['deflated_alpha_ratio']}"
    assert 0.0 <= da["p_value"] <= 1.0, f"p-value out of range: {da['p_value']}"

    # Single benchmark -> no cross-benchmark deflation is applied.
    result_single = _benchmark_list_alpha_correction(strategy_returns, [bench1])
    assert result_single["n_benchmarks"] == 1
    assert result_single["deflated_alpha"] is None, "Single benchmark must not get a deflated_alpha"


def test_cpcv_analysis_multiple_benchmarks_deflated_alpha():
    """cpcv_analysis with multiple benchmarks surfaces Deflated Alpha at the
    fold level and in the aggregate summary, and leaves single-benchmark
    behaviour unchanged (backward compatibility).
    """
    data = _make_ohlcv_data(periods=500, seed=42)
    bench1 = _make_benchmark_data(periods=500, seed=99)
    bench2 = _make_benchmark_data(periods=500, seed=7)
    factory = lambda params: build_strategy("sma_crossover", json.dumps(params))
    param_grid = {"fast_period": [3, 5, 7], "slow_period": [10, 12, 15]}

    results = cpcv_analysis(
        data=data,
        strategy_factory=factory,
        param_grid=param_grid,
        n_splits=5,
        test_size=0.2,
        initial_capital=100000,
        commission=0.0002,
        slippage=0.0001,
        benchmark=[bench1, bench2],
        benchmark_commission=0.001,
        benchmark_slippage=0.001,
        benchmark_cost_is_periodic=True,
    )

    summary = results["summary"]
    # Aggregate deflated alpha must be surfaced for multiple benchmarks.
    assert "deflated_alpha" in summary, (
        f"deflated_alpha missing from CPCV summary. Keys: {sorted(summary.keys())}"
    )
    da = summary["deflated_alpha"]
    for key in ("deflated_alpha_ratio", "p_value", "alpha", "expected_max_alpha",
                "n_benchmarks", "n_observations", "skewness", "kurtosis", "z_score"):
        assert key in da, f"missing key {key} in deflated_alpha"
    assert da["n_benchmarks"] == 2, f"Expected n_benchmarks=2, got {da['n_benchmarks']}"
    assert 0.0 <= da["deflated_alpha_ratio"] <= 1.0
    assert 0.0 <= da["p_value"] <= 1.0

    # One benchmark metrics dict per benchmark at the aggregate level.
    assert isinstance(summary.get("benchmark_metrics"), list), "benchmark_metrics should be a list"
    assert len(summary["benchmark_metrics"]) == 2
    assert "deflated_alpha" in summary["benchmark_metrics"][0]

    # Per-fold deflated alpha present on folds that produced OOS returns.
    folds = results["folds"]
    folds_with_da = [fold for fold in folds if fold.get("deflated_alpha") is not None]
    assert folds_with_da, "Expected at least one CPCV fold to carry a deflated_alpha"
    for fold in folds_with_da:
        stats = fold.get("benchmark_stats")
        assert isinstance(stats, list) and len(stats) == 2, "Expected per-fold list of 2 benchmark stats"
        assert "deflated_alpha" in stats[0], "Expected per-fold benchmark stats to carry deflated_alpha"

    # Backward-compat: single benchmark (DataFrame) must NOT produce an
    # aggregate deflated_alpha dict, but must still surface raw alpha.
    results_single = cpcv_analysis(
        data=data, strategy_factory=factory, param_grid=param_grid,
        n_splits=5, test_size=0.2, benchmark=bench1,
        benchmark_commission=0.001, benchmark_slippage=0.001,
        benchmark_cost_is_periodic=True,
    )
    assert "deflated_alpha" not in results_single["summary"], "Single benchmark should not get aggregate deflated_alpha"
    assert "alpha" in results_single["summary"], "Single benchmark should still get alpha (backward compat)"


def test_walk_forward_analysis_multiple_benchmarks_deflated_alpha():
    """walk_forward_analysis with multiple benchmarks surfaces Deflated Alpha at
    the per-period level and in the aggregate summary.
    """
    data = _make_ohlcv_data(periods=500, seed=42)
    bench1 = _make_benchmark_data(periods=500, seed=99)
    bench2 = _make_benchmark_data(periods=500, seed=7)
    factory = lambda params: build_strategy("sma_crossover", json.dumps(params))
    param_grid = {"fast_period": [3, 5, 7], "slow_period": [10, 12, 15]}

    results = walk_forward_analysis(
        data=data,
        strategy_factory=factory,
        param_grid=param_grid,
        train_months=12,
        test_months=3,
        step_months=2,
        initial_capital=100000,
        commission=0.0002,
        slippage=0.0001,
        benchmark=[bench1, bench2],
        benchmark_commission=0.001,
        benchmark_slippage=0.001,
        benchmark_cost_is_periodic=True,
    )

    summary = results["summary"]
    assert "deflated_alpha" in summary, (
        f"deflated_alpha missing from walk-forward summary. Keys: {sorted(summary.keys())}"
    )
    da = summary["deflated_alpha"]
    assert da["n_benchmarks"] == 2
    assert 0.0 <= da["deflated_alpha_ratio"] <= 1.0
    assert 0.0 <= da["p_value"] <= 1.0

    assert isinstance(summary.get("benchmark_metrics"), list)
    assert len(summary["benchmark_metrics"]) == 2

    # Per-period deflated alpha on periods that produced OOS returns.
    periods = results["periods"]
    periods_with_da = [p for p in periods if p.get("deflated_alpha") is not None]
    assert periods_with_da, "Expected at least one walk-forward period to carry a deflated_alpha"
    for p in periods_with_da:
        stats = p.get("benchmark_stats")
        assert isinstance(stats, list) and len(stats) == 2
        assert "deflated_alpha" in stats[0]


def test_cli_cpcv_multiple_benchmarks():
    """CLI cpcv subcommand accepts multiple --benchmark files, does not crash
    in the post-call benchmark block, and writes a cpcv_summary.json whose
    summary contains a cross-benchmark deflated_alpha correction plus
    per-benchmark metrics.
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        csv_path = os.path.join(tmpdir, "data.csv")
        bench1_path = os.path.join(tmpdir, "bench1.csv")
        bench2_path = os.path.join(tmpdir, "bench2.csv")
        _write_ohlcv_csv(csv_path, periods=800)
        _write_benchmark_csv(bench1_path, periods=800, seed=99)
        _write_benchmark_csv(bench2_path, periods=800, seed=7)
        out_dir = os.path.join(tmpdir, "out")
        argv = [
            "walk_forward", "cpcv",
            "--data", csv_path,
            "--benchmark", bench1_path, bench2_path,
            "--strategy", "sma_crossover",
            "--param-grid", '{"fast_period": [3, 5, 7], "slow_period": [10, 12, 15]}',
            "--output", out_dir,
            "--benchmark-commission", "0.001",
            "--benchmark-slippage", "0.001",
            "--benchmark-cost-is-periodic",
            "--n-splits", "5",
            "--test-size", "0.2",
        ]
        with patch.object(sys, "argv", argv), \
                redirect_stdout(StringIO()), redirect_stderr(StringIO()):
            rc = walk_forward_main()

        assert rc == 0, f"CLI cpcv with multiple benchmarks should exit 0, got {rc}"
        summary_path = os.path.join(out_dir, "cpcv_summary.json")
        assert os.path.exists(summary_path), "cpcv_summary.json not written"
        with open(summary_path) as f:
            payload = json.load(f)

        assert "summary" in payload, "summary missing from cpcv_summary.json"
        summary = payload["summary"]
        assert "deflated_alpha" in summary, (
            f"deflated_alpha missing from CLI cpcv summary. Keys: {sorted(summary.keys())}"
        )
        da = summary["deflated_alpha"]
        assert da["n_benchmarks"] == 2
        assert 0.0 <= da["deflated_alpha_ratio"] <= 1.0
        assert isinstance(summary.get("benchmark_metrics"), list)
        assert len(summary["benchmark_metrics"]) == 2


# Need to import patch for mocking
from unittest.mock import patch



def main() -> int:
    tests = [
        ("test_out_of_sample_validation_benchmark_cost_is_periodic", test_out_of_sample_validation_benchmark_cost_is_periodic),
        ("test_out_of_sample_validation_benchmark_cost_is_periodic_cpcv", test_out_of_sample_validation_benchmark_cost_is_periodic_cpcv),
        ("test_cli_out_of_sample_benchmark_cost_is_periodic", test_cli_out_of_sample_benchmark_cost_is_periodic),
        ("test_cli_out_of_sample_benchmark_cost_is_periodic_false", test_cli_out_of_sample_benchmark_cost_is_periodic_false),
        ("test_cli_out_of_sample_benchmark_cost_is_periodic_cpcv", test_cli_out_of_sample_benchmark_cost_is_periodic_cpcv),
        ("test_benchmark_stats_with_splits_runs_without_error", test_benchmark_stats_with_splits_runs_without_error),
        ("test_benchmark_stats_with_splits_uses_adjusted_returns", test_benchmark_stats_with_splits_uses_adjusted_returns),
        ("test_add_benchmark_to_summary_splits_path", test_add_benchmark_to_summary_splits_path),
        ("test_out_of_sample_validation_with_splits", test_out_of_sample_validation_with_splits),
        ("test_calculate_metrics_deflated_alpha_with_benchmark_list", test_calculate_metrics_deflated_alpha_with_benchmark_list),
        ("test_cli_cpcv_benchmark_cost_is_periodic", test_cli_cpcv_benchmark_cost_is_periodic),
        ("test_benchmark_list_alpha_correction_deflated_alpha", test_benchmark_list_alpha_correction_deflated_alpha),
        ("test_cpcv_analysis_multiple_benchmarks_deflated_alpha", test_cpcv_analysis_multiple_benchmarks_deflated_alpha),
        ("test_walk_forward_analysis_multiple_benchmarks_deflated_alpha", test_walk_forward_analysis_multiple_benchmarks_deflated_alpha),
        ("test_cli_cpcv_multiple_benchmarks", test_cli_cpcv_multiple_benchmarks),
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
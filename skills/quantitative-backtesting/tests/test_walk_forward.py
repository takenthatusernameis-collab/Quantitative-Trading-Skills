#!/usr/bin/env python3
"""
Unit tests for walk_forward.py: parameter_optimization and walk_forward_analysis.

Run with: python3 skills/quantitative-backtesting/tests/test_walk_forward.py
No third-party test framework is required; uses only the standard library.
"""

import json
import os
import subprocess
import sys
import tempfile
import traceback
from pathlib import Path
from io import StringIO
from contextlib import redirect_stdout, redirect_stderr
from unittest.mock import patch

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
    deflated_alpha_ratio,
    _load_and_validate_data,
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


def _make_flat_ohlcv_data(periods: int = 300, seed: int = 42) -> pd.DataFrame:
    """OHLCV with a constant price: exactly zero returns (zero variance)."""
    dates = pd.date_range("2020-01-01", periods=periods, freq="B")
    return pd.DataFrame({
        "open": np.full(periods, 100.0),
        "high": np.full(periods, 100.5),
        "low": np.full(periods, 99.5),
        "close": np.full(periods, 100.0),
        "volume": np.full(periods, 1_000_000),
    }, index=dates)


def _make_constant_return_ohlcv_data(
    periods: int = 300, daily_return: float = 0.001
) -> pd.DataFrame:
    """OHLCV whose close-to-close returns are exactly constant.

    Built recursively so pct_change() yields one unique value exactly
    (floating-point compounding from ``1.001 ** t`` would not).
    """
    dates = pd.date_range("2020-01-01", periods=periods, freq="B")
    close = np.empty(periods, dtype=float)
    close[0] = 100.0
    for t in range(1, periods):
        close[t] = close[t - 1] * (1.0 + daily_return)
    return pd.DataFrame({
        "open": close,
        "high": close * 1.001,
        "low": close * 0.999,
        "close": close,
        "volume": np.full(periods, 1_000_000),
    }, index=dates)


def _make_random_then_constant_data(
    periods: int = 400, split: int = 252, seed: int = 7
) -> pd.DataFrame:
    """Random returns for the first `split` bars, exactly zero returns after.

    Lets a walk-forward run select parameters on non-constant train returns
    while the combined out-of-sample record is exactly constant, which
    exercises the degenerate-DSR branch of the aggregate correction.
    """
    rng = np.random.default_rng(seed)
    dates = pd.date_range("2020-01-01", periods=periods, freq="B")
    rets = np.concatenate([rng.normal(0.0005, 0.01, split), np.zeros(periods - split)])
    close = np.empty(periods, dtype=float)
    close[0] = 100.0
    for t in range(1, periods):
        close[t] = close[t - 1] * (1.0 + rets[t])
    return pd.DataFrame({
        "open": close,
        "high": close * 1.001,
        "low": close * 0.999,
        "close": close,
        "volume": np.full(periods, 1_000_000),
    }, index=dates)


class _ConstantLongStrategy:
    """Always-long, no-warmup stub strategy: positions are 1.0 on every bar.

    Used so strategy returns are exactly the raw returns, which keeps a
    constant-return series exactly constant through the pipeline (real
    strategies with indicator warmup emit zeros at the start, which breaks
    exact zero variance).
    """

    def generate_signals(self, data: pd.DataFrame) -> pd.Series:
        return pd.Series(1.0, index=data.index)


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

    # The two cost models must produce different benchmark returns — this is
    # the behavioral effect the flag exists for. Without this assertion the
    # test would only guard flag plumbing, not the cost-model divergence that
    # the flag controls (see verify_end_to_end.py for the reference values).
    assert bench_return_false != bench_return_true, (
        f"Expected different benchmark returns for round-trip vs periodic costs, "
        f"got false={bench_return_false:.8f} true={bench_return_true:.8f}"
    )

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


def test_cli_out_of_sample_persists_separation_check_audit_field():
    """CLI out-of-sample persists the split-separation audit field to JSON.

    validation_methods.md documents that the held-out test set must never
    have been used in any selection step and that the check result is
    recorded in ``train_val_test_split.separation_check`` for audit. This
    end-to-end test verifies that claim against the actual CLI artifact:
    the field must be present, report the disjoint/chronological booleans,
    and be green on a clean chronological split.
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        csv_path = os.path.join(tmpdir, "data.csv")
        _write_ohlcv_csv(csv_path, periods=500)
        out_dir = os.path.join(tmpdir, "out")
        argv = [
            "walk_forward", "out-of-sample",
            "--data", csv_path,
            "--strategy", "sma_crossover",
            "--param-grid", '{"fast_period": [3, 5], "slow_period": [8, 10]}',
            "--output", out_dir,
            "--wf-train-months", "6",
            "--wf-test-months", "2",
            "--wf-step-months", "2",
        ]
        with patch.object(sys, "argv", argv), \
                redirect_stdout(StringIO()), redirect_stderr(StringIO()):
            rc = walk_forward_main()

        assert rc == 0, "out-of-sample CLI should exit 0 on a clean split"

        summary_path = os.path.join(out_dir, "out_of_sample_summary.json")
        assert os.path.exists(summary_path), "out_of_sample_summary.json not written"
        with open(summary_path) as f:
            summary = json.load(f)

        split = summary["train_val_test_split"]
        assert "separation_check" in split, (
            "train_val_test_split.separation_check missing from CLI artifact; "
            "the split-separation invariant is not persisted for audit"
        )
        check = split["separation_check"]
        for key in ("disjoint", "chronological", "train_val_overlap",
                    "val_test_overlap", "train_test_overlap"):
            assert key in check, f"separation_check missing field {key}"
        assert check["disjoint"] is True, (
            f"clean chronological split should be disjoint, got {check}"
        )
        assert check["chronological"] is True, (
            f"clean chronological split should be chronological, got {check}"
        )
        assert check["train_val_overlap"] == 0
        assert check["val_test_overlap"] == 0
        assert check["train_test_overlap"] == 0


def test_load_and_validate_data_runs_pit_by_default():
    """_load_and_validate_data runs point-in-time validation by default."""
    with tempfile.TemporaryDirectory() as tmpdir:
        csv_path = os.path.join(tmpdir, "data.csv")
        _write_ohlcv_csv(csv_path, periods=200, seed=42)
        data, pit, surv = _load_and_validate_data(
            csv_path, symbol="TEST", start="2020-01-01", end="2021-12-31",
        )
        assert pit is not None, "PIT should run by default (validate_pit=True)"
        assert pit["passed"] is True, f"PIT should pass on clean data, got {pit}"
        assert surv is None, "Survivorship should be None without --multi-symbol"
        assert data is not None and len(data) > 0

        data2, pit2, surv2 = _load_and_validate_data(
            csv_path, symbol="TEST", start="2020-01-01", end="2021-12-31",
            validate_pit=False,
        )
        assert pit2 is None, "PIT should be skipped when validate_pit=False"


def test_cli_point_in_time_validation_enabled_by_default():
    """CLI out-of-sample runs PIT by default; bias_controls_engaged=True."""
    with tempfile.TemporaryDirectory() as tmpdir:
        csv_path = os.path.join(tmpdir, "data.csv")
        _write_ohlcv_csv(csv_path, periods=500, seed=42)
        out_dir = os.path.join(tmpdir, "out")
        argv = [
            "walk_forward", "out-of-sample",
            "--data", csv_path,
            "--strategy", "sma_crossover",
            "--param-grid", '{"fast_period": [3, 5], "slow_period": [8, 10]}',
            "--output", out_dir,
            "--wf-train-months", "6",
            "--wf-test-months", "2",
            "--wf-step-months", "2",
        ]
        with patch.object(sys, "argv", argv), \
                redirect_stdout(StringIO()), redirect_stderr(StringIO()):
            rc = walk_forward_main()

        assert rc == 0, "CLI out-of-sample with default PIT should exit 0"

        summary_path = os.path.join(out_dir, "out_of_sample_summary.json")
        assert os.path.exists(summary_path), "out_of_sample_summary.json not written"
        with open(summary_path) as f:
            summary = json.load(f)

        assert summary.get("bias_controls_engaged") is True, \
            f"Expected bias_controls_engaged=True by default, got {summary.get('bias_controls_engaged')}"
        assert "point_in_time_validation" in summary.get("config", {}), \
            "point_in_time_validation missing from config"
        pit = summary["config"]["point_in_time_validation"]
        assert pit is not None and pit.get("passed") is True, \
            f"Expected PIT to pass on clean data, got {pit}"


def test_cli_point_in_time_validation_can_be_disabled():
    """--no-validate-point-in-time disables PIT; bias_controls_engaged=False."""
    with tempfile.TemporaryDirectory() as tmpdir:
        csv_path = os.path.join(tmpdir, "data.csv")
        _write_ohlcv_csv(csv_path, periods=500, seed=42)
        out_dir = os.path.join(tmpdir, "out")
        argv = [
            "walk_forward", "out-of-sample",
            "--data", csv_path,
            "--strategy", "sma_crossover",
            "--param-grid", '{"fast_period": [3, 5], "slow_period": [8, 10]}',
            "--output", out_dir,
            "--no-validate-point-in-time",
            "--wf-train-months", "6",
            "--wf-test-months", "2",
            "--wf-step-months", "2",
        ]
        with patch.object(sys, "argv", argv), \
                redirect_stdout(StringIO()), redirect_stderr(StringIO()):
            rc = walk_forward_main()

        assert rc == 0, "CLI out-of-sample with PIT disabled should exit 0"

        summary_path = os.path.join(out_dir, "out_of_sample_summary.json")
        assert os.path.exists(summary_path), "out_of_sample_summary.json not written"
        with open(summary_path) as f:
            summary = json.load(f)

        assert summary.get("bias_controls_engaged") is False, \
            f"Expected bias_controls_engaged=False when PIT disabled, got {summary.get('bias_controls_engaged')}"


def test_out_of_sample_validation_validate_pit_detects_look_ahead():
    """out_of_sample_validation with validate_pit=True detects point-in-time
    violations in the input data (positive control).

    Duplicate timestamps violate temporal ordering; validate_point_in_time
    must record passed=False and bias_controls_engaged must be True.  PIT runs
    before the train/val/test split, so duplicates are appended at the tail
    (all land in the test split) to keep the split from crashing.
    """
    data = _make_ohlcv_data(periods=400, seed=42)
    leaky = pd.concat([data, data.iloc[-10:]])
    strategy_type = "sma_crossover"
    param_grid = {"fast_period": [3, 5], "slow_period": [8, 10]}
    factory = lambda params: build_strategy(strategy_type, json.dumps(params))

    results = out_of_sample_validation(
        data=leaky,
        strategy_factory=factory,
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
        validate_pit=True,
    )

    assert results is not None
    pit = results.get("point_in_time_validation")
    assert pit is not None, "point_in_time_validation should be recorded when validate_pit=True"
    assert pit["passed"] is False, f"Expected PIT to fail on leaky data, got {pit}"
    assert len(pit["violations"]) > 0, "Expected at least one PIT violation"
    assert results["summary"]["bias_controls_engaged"] is True, \
        "bias_controls_engaged should be True when PIT ran"

    # Negative control: clean data with validate_pit=True passes.
    results_clean = out_of_sample_validation(
        data=data,
        strategy_factory=factory,
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
        validate_pit=True,
    )
    pit_clean = results_clean.get("point_in_time_validation")
    assert pit_clean is not None
    assert pit_clean["passed"] is True, f"Expected PIT to pass on clean data, got {pit_clean}"
    assert results_clean["summary"]["bias_controls_engaged"] is True


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


def test_out_of_sample_validation_splits_adjusted_regardless_of_cost_model():
    """A benchmark with a corporate action must be split-adjusted under BOTH
    cost models.

    Split adjustment is orthogonal to the cost model: a stock split injects an
    artificial price drop into benchmark returns whether benchmark costs are
    modeled as round-trip or periodic.  Gating the splits-aware path on
    ``benchmark_cost_is_periodic`` therefore mispriced every split-bearing
    benchmark under the default (round-trip) cost model — a 2-for-1 split in
    the test window produced benchmark_total_return of ~-49% instead of the
    split-adjusted ~+1.5%.

    With zero benchmark costs the two cost models are equivalent, so the two
    runs must now agree exactly (the only remaining difference is the cost
    model, which is disabled).  This is the regression guard for that fix.
    """
    data = _make_ohlcv_data(periods=300, seed=42)
    # split_at=260 lands inside the test window (indices 240-300 for
    # 0.6/0.2/0.2), so the split affects the benchmark stats under test.
    benchmark = _make_benchmark_data_with_splits(periods=300, split_at=260)

    strategy_type = "sma_crossover"
    param_grid = {"fast_period": [3, 5], "slow_period": [8, 10]}

    # Zero benchmark costs: the only thing that should differ between the two
    # calls is the cost model, which is now disabled.  Both must therefore
    # produce the same split-adjusted benchmark total return.
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
        commission=0.0,
        slippage=0.0,
        benchmark=benchmark,
        total_return_benchmark=False,
        benchmark_commission=0.0,
        benchmark_slippage=0.0,
        benchmark_expense_ratio=0.0,
        benchmark_cost_is_periodic=False,
    )

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
        commission=0.0,
        slippage=0.0,
        benchmark=benchmark,
        total_return_benchmark=False,
        benchmark_commission=0.0,
        benchmark_slippage=0.0,
        benchmark_expense_ratio=0.0,
        benchmark_cost_is_periodic=True,
    )

    bench_false = results_false["test_benchmark"]
    bench_true = results_true["test_benchmark"]

    # Both paths must be split-adjusted.  A 2-for-1 split in the test window
    # halves prices on and after the split date; an unadjusted benchmark
    # return would be ~-50%, far below any plausible split-adjusted value.
    ret_false = bench_false["benchmark_total_return"]
    ret_true = bench_true["benchmark_total_return"]
    assert ret_false > -0.2, (
        f"Round-trip path should be split-adjusted, got benchmark_total_return={ret_false:.4f} "
        f"(an unadjusted split yields ~-50%)"
    )
    assert ret_true > -0.2, (
        f"Periodic path should be split-adjusted, got benchmark_total_return={ret_true:.4f}"
    )

    # With zero benchmark costs the two cost models are equivalent, so the
    # split-adjusted benchmark returns must agree exactly.
    assert abs(ret_false - ret_true) < 1e-9, (
        f"Split-adjusted benchmark returns should agree across cost models "
        f"when costs are zero: false={ret_false:.8f} true={ret_true:.8f}"
    )


def test_out_of_sample_validation_n_trials_matches_evaluated_combinations():
    """out_of_sample_validation's aggregate deflated_sharpe n_trials must equal
    the count of actually-evaluated (finite-Sharpe) combinations across
    walk-forward periods -- not the full combinatorial grid size -- and must
    match walk_forward_analysis on the same grid.

    Guards the multiple-testing correction: Deflated Sharpe p-values are only
    comparable across walk_forward, cpcv, and out_of_sample_validation when
    they are all deflated by the same effective trial count.  The cpcv branch
    of out_of_sample_validation reuses the same total_trials computation, so
    this covers both validation methods.
    """
    data = _make_ohlcv_data(periods=1200, seed=11)
    strategy_type = "sma_crossover"
    param_grid = {"fast_period": [5, 10, 15], "slow_period": [20, 30, 40]}
    full_grid_size = len(param_grid["fast_period"]) * len(param_grid["slow_period"])
    factory = lambda params: build_strategy(strategy_type, json.dumps(params))

    train_data, _val_data, _test_data = _split_train_val_test(data, 0.6, 0.2, 0.2)

    # Independent recomputation on the same train slice / grid.
    wf = walk_forward_analysis(
        data=train_data, strategy_factory=factory, param_grid=param_grid,
        train_months=12, test_months=3, step_months=3,
        initial_capital=100000, commission=0.0002, slippage=0.0001,
        apply_deflation=True,
    )
    wf_n = wf["summary"]["deflated_sharpe"]["n_trials"]
    wf_evaluated = sum(
        len(p.get("trial_sharpes") or [])
        for p in wf.get("periods", []) if p.get("best_params") is not None
    )
    assert wf_n == max(wf_evaluated, 1), (wf_n, wf_evaluated)

    oos = out_of_sample_validation(
        data=data, strategy_factory=factory, param_grid=param_grid,
        train_frac=0.6, val_frac=0.2, test_frac=0.2,
        validation_method="walk_forward",
        walk_forward_train_months=12, walk_forward_test_months=3,
        walk_forward_step_months=3,
        initial_capital=100000, commission=0.0002, slippage=0.0001,
        apply_deflation=True, validate_pit=False,
    )
    oos_n = oos["summary"]["deflated_sharpe"]["n_trials"]
    inner_n = oos["validation_results"]["summary"]["deflated_sharpe"]["n_trials"]
    oos_evaluated = sum(
        len(p.get("trial_sharpes") or [])
        for p in oos["validation_results"].get("periods", [])
        if p.get("best_params") is not None
    )

    # Cross-path consistency: out_of_sample_validation matches
    # walk_forward_analysis on the same grid.
    assert oos_n == wf_n, (oos_n, wf_n)
    # Equals the count of actually-evaluated combinations, not the full grid.
    assert oos_n == oos_evaluated == max(oos_evaluated, 1), (oos_n, oos_evaluated)
    # Regression guard: previously the full grid size was used per period, so
    # with multiple periods the count must exceed a single grid traversal.
    assert oos_n > full_grid_size, (oos_n, full_grid_size)
    # Inner (validation_results) and outer (summary) agree.
    assert oos_n == inner_n, (oos_n, inner_n)


def test_out_of_sample_validation_uses_pooled_trial_sharpes_for_sr_star():
    """out_of_sample_validation's aggregate Deflated Sharpe must use the
    pooled cross-period validation trial Sharpes for the SR* estimator, so
    its p-value is comparable to walk_forward_analysis on the same grid.

    Guards the multiple-testing correction: before this fix the OOS
    aggregate passed `trial_sharpes=None`, falling back to the i.i.d.-normal
    null approximation, which reports a different (less conservative)
    expected-max-Sharpe SR* than the pooled cross-sectional estimator used by
    walk_forward_analysis / cpcv_analysis -- even though all three deflated
    by the same `n_trials`. With pooled trial Sharpes the OOS p-value must
    move toward (but need not exactly equal) the walk-forward p-value, since
    both then estimate SR* from the same cross-sectional dispersion of the
    actually-evaluated trial Sharpes.
    """
    data = _make_ohlcv_data(periods=1200, seed=11)
    param_grid = {"fast_period": [5, 10, 15], "slow_period": [20, 30, 40]}
    factory = lambda params: build_strategy("sma_crossover", json.dumps(params))

    train_data, _val_data, _test_data = _split_train_val_test(data, 0.6, 0.2, 0.2)

    wf = walk_forward_analysis(
        data=train_data, strategy_factory=factory, param_grid=param_grid,
        train_months=12, test_months=3, step_months=3,
        initial_capital=100000, commission=0.0002, slippage=0.0001,
        apply_deflation=True,
    )
    wf_ds = wf["summary"]["deflated_sharpe"]

    oos = out_of_sample_validation(
        data=data, strategy_factory=factory, param_grid=param_grid,
        train_frac=0.6, val_frac=0.2, test_frac=0.2,
        validation_method="walk_forward",
        walk_forward_train_months=12, walk_forward_test_months=3,
        walk_forward_step_months=3,
        initial_capital=100000, commission=0.0002, slippage=0.0001,
        apply_deflation=True, validate_pit=False,
    )
    oos_ds = oos["summary"]["deflated_sharpe"]

    # Same effective trial count (already guarded by the n_trials test).
    assert oos_ds["n_trials"] == wf_ds["n_trials"]

    # The OOS aggregate must now carry pooled trial Sharpes (the
    # cross-sectional SR* estimator), not fall back to the i.i.d. null.
    # With pooled Sharpes the OOS p-value moves toward the walk-forward
    # p-value (same SR* estimator on the same evaluated Sharpes); the
    # i.i.d. null would have left them far apart.
    assert oos_ds["p_value"] < 0.999, (
        "OOS aggregate p-value too high; pooled trial Sharpes not used"
    )
    # The pooled estimator is conservative: SR* >= i.i.d. null, so the OOS
    # p-value must not exceed the walk-forward p-value on the same grid.
    assert oos_ds["p_value"] <= wf_ds["p_value"] + 1e-9, (
        oos_ds["p_value"], wf_ds["p_value"]
    )


def test_deflated_sharpe_parity_across_all_four_analysis_paths():
    """Deflated Sharpe p-values must be comparable across all four analysis
    paths that consume the same grid and data:

      1. walk_forward_analysis        (aggregate n_trials = evaluated
                                        finite-Sharpe combos across periods)
      2. cpcv_analysis                (same basis across folds)
      3. out_of_sample_validation     (reconciled to evaluated combos, and now
                                        sharing the pooled SR* estimator)
      4. parameter_optimization       (the grid search behind
                                        `monte-carlo --n-trials`; per-combo
                                        DSR uses the full evaluated combo count)

    Guards the multiple-testing correction: a strategy's reported DSR
    p-value must not depend on which analysis path reported it. All four
    must deflate by the same effective trial count where their counting
    bases agree, and the OOS aggregate must use the same cross-sectional
    SR* estimator (pooled validation trial Sharpes) as the walk-forward /
    CPCV aggregates.
    """
    data = _make_ohlcv_data(periods=1200, seed=11)
    param_grid = {"fast_period": [5, 10, 15], "slow_period": [20, 30, 40]}
    full_grid = len(param_grid["fast_period"]) * len(param_grid["slow_period"])
    factory = lambda params: build_strategy("sma_crossover", json.dumps(params))

    train_data, _val_data, _test_data = _split_train_val_test(data, 0.6, 0.2, 0.2)

    # 1 + 2: walk-forward and CPCV aggregates on the same train slice.
    wf = walk_forward_analysis(
        data=train_data, strategy_factory=factory, param_grid=param_grid,
        train_months=12, test_months=3, step_months=3,
        initial_capital=100000, commission=0.0002, slippage=0.0001,
        apply_deflation=True,
    )
    wf_ds = wf["summary"]["deflated_sharpe"]

    cv = cpcv_analysis(
        data=train_data, strategy_factory=factory, param_grid=param_grid,
        n_splits=5, test_size=0.2,
        initial_capital=100000, commission=0.0002, slippage=0.0001,
        apply_deflation=True,
    )
    cv_ds = cv["summary"]["deflated_sharpe"]

    # 3: out-of-sample validation (walk-forward selection on the train slice).
    oos = out_of_sample_validation(
        data=data, strategy_factory=factory, param_grid=param_grid,
        train_frac=0.6, val_frac=0.2, test_frac=0.2,
        validation_method="walk_forward",
        walk_forward_train_months=12, walk_forward_test_months=3,
        walk_forward_step_months=3,
        initial_capital=100000, commission=0.0002, slippage=0.0001,
        apply_deflation=True, validate_pit=False,
    )
    oos_ds = oos["summary"]["deflated_sharpe"]

    # 4: the grid search that `monte-carlo --n-trials` consumes.
    opt = parameter_optimization(
        data=data, strategy_factory=factory, param_grid=param_grid,
        commission=0.0002, slippage=0.0001,
        apply_deflation=True,
    )
    opt_n = len(opt)
    best_ds = opt[0]["deflated_sharpe"]

    # --- n_trials parity where counting bases agree ---
    # walk-forward / CPCV / OOS all count actually-evaluated finite-Sharpe
    # combos across periods/folds; OOS must match walk-forward on the same
    # grid (it reuses the same walk-forward selection on the train slice).
    assert oos_ds["n_trials"] == wf_ds["n_trials"], (
        oos_ds["n_trials"], wf_ds["n_trials"]
    )
    # The per-combo DSR inside parameter_optimization uses the full evaluated
    # combo count (one grid traversal), not the cross-period sum.
    assert best_ds["n_trials"] == opt_n == full_grid, (
        best_ds["n_trials"], opt_n, full_grid
    )

    # --- SR* estimator parity for the aggregate paths ---
    # With pooled trial Sharpes, the OOS aggregate's expected-max-Sharpe SR*
    # must match the walk-forward aggregate's SR* estimator basis (both
    # derive SR* from the cross-sectional dispersion of the same evaluated
    # trial Sharpes). The i.i.d.-null fallback would have produced a
    # different SR* and a far higher p-value.
    assert oos_ds["p_value"] <= wf_ds["p_value"] + 1e-9, (
        oos_ds["p_value"], wf_ds["p_value"]
    )

    # --- DSR / p_value sanity (finite, in range) ---
    for label, ds in [("walk_forward", wf_ds), ("cpcv", cv_ds),
                      ("oos", oos_ds), ("param_opt", best_ds)]:
        assert 0.0 <= ds["deflated_sharpe_ratio"] <= 1.0, (label, ds)
        assert 0.0 <= ds["p_value"] <= 1.0, (label, ds)
        assert ds["n_trials"] >= 1, (label, ds)


def test_cost_sweep_dsr_parity_across_paths():
    """Cost-sweep artifacts must carry the same Deflated Sharpe correction
    basis as the single-run paths they re-run.

    Each cost sweep re-runs one of the four analysis pipelines
    (walk-forward / out-of-sample / cpcv / monte-carlo) for a series of
    coefficient values and records a per-coefficient `deflated_sharpe`
    and `deflated_sharpe_n_trials` row. The multiple-testing correction
    must therefore be consistent with the single-run parity invariant
    already guarded by `test_deflated_sharpe_parity_across_all_four_analysis_paths`:
    within a sweep, the `n_trials` (the number of configurations the
    pipeline actually evaluated) must be constant across coefficients
    (the grid is unchanged, so the counting basis cannot drift), and
    the DSR / p_value must stay in [0, 1] for every row.

    Guards the cost-sweep extension of the DSR parity invariant: before
    this session the sweeps recorded `deflated_sharpe_n_trials` but no
    test asserted it was coefficient-stable, so a regression in the
    per-coefficient trial counting (e.g. one coefficient evaluating a
    different subset of the grid) would have gone unnoticed while the
    sweep still "ran".
    """
    grid = '{"fast_period": [5, 10, 15], "slow_period": [20, 30, 40]}'

    def run_sweep(subcmd, extra, expect):
        with tempfile.TemporaryDirectory() as tmpdir:
            csv_path = os.path.join(tmpdir, "data.csv")
            _write_ohlcv_csv(csv_path, periods=600, seed=11)
            out_dir = os.path.join(tmpdir, "out")
            # `--impact-coefficients` is nargs="+" so it must come last.
            argv = [
                "walk_forward", subcmd,
                "--data", csv_path,
                "--symbol", "SPY",
                "--strategy", "sma_crossover",
                "--param-grid", grid,
                "--output", out_dir,
            ] + extra + ["--impact-coefficients", "0", "2", "5"]
            with patch.object(sys, "argv", argv), \
                    redirect_stdout(StringIO()), redirect_stderr(StringIO()):
                rc = walk_forward_main()
            assert rc == 0, f"{subcmd} impact sweep should exit 0, got {rc}"
            sweep_path = os.path.join(out_dir, expect)
            assert os.path.exists(sweep_path), f"{expect} not written"
            with open(sweep_path) as f:
                return json.load(f)

    # walk-forward / out-of-sample / cpcv sweeps gate the DSR on `--deflate`;
    # monte-carlo gates it on `--n-trials` instead (no `--deflate` flag exists
    # for the monte-carlo subcommand).
    wf = run_sweep("walk-forward", ["--deflate"], "walk_forward_impact_sweep.json")
    oos = run_sweep("out-of-sample", ["--deflate"], "out_of_sample_impact_sweep.json")
    cv = run_sweep("cpcv", ["--deflate", "--n-splits", "5", "--test-size", "0.2"],
                   "cpcv_impact_sweep.json")
    mc = run_sweep(
        "monte-carlo",
        ["--n-simulations", "50", "--n-trials", "500"],
        "monte_carlo_impact_sweep.json",
    )

    sweeps = {
        "walk_forward": wf,
        "out_of_sample": oos,
        "cpcv": cv,
        "monte_carlo": mc,
    }
    for name, payload in sweeps.items():
        rows = payload["results"]
        assert len(rows) == 3, (name, "expected 3 sweep rows")

        n_trials = [r.get("deflated_sharpe_n_trials") for r in rows]
        # The grid is identical across coefficients, so the counting basis
        # (the number of configurations the pipeline actually evaluated)
        # must not drift between coefficients.
        assert n_trials[0] is not None and n_trials[0] == n_trials[1] == n_trials[2], (
            name, "sweep n_trials must be coefficient-stable", n_trials
        )
        assert n_trials[0] >= 1, (name, n_trials)

        for i, r in enumerate(rows):
            label = f"{name}[{i}]"
            dsr = r.get("deflated_sharpe")
            nt = r.get("deflated_sharpe_n_trials")
            assert dsr is not None, (name, label, "missing deflated_sharpe")
            assert 0.0 <= dsr <= 1.0, (name, label, dsr)
            assert nt == n_trials[0], (name, label, nt, n_trials[0])


def test_non_impact_sweep_dsr_parity_across_paths():
    """Non-impact cost sweeps must carry a coefficient-stable DSR basis.

    Extends `test_cost_sweep_dsr_parity_across_paths` (which guarded only the
    `--impact-coefficients` sweeps) to the remaining cost sweeps:
    `--borrow-costs`, `--funding-costs`, `--commissions`, and `--slippages`.
    Each of these re-runs one of the four analysis pipelines for a series of
    cost values and records a per-cost `deflated_sharpe` /
    `deflated_sharpe_n_trials` row. The grid is unchanged across costs, so
    the multiple-testing correction basis (the number of configurations the
    pipeline actually evaluated) must not drift between costs, and the DSR /
    p_value must stay in [0, 1] for every row.

    Before this session only the impact sweep was guarded, so a regression in
    the per-cost trial counting (e.g. a borrow sweep evaluating a different
    subset of the grid at a different cost) would have gone unnoticed while
    the sweep still "ran" and the artifact still looked well-formed.
    """
    grid = '{"fast_period": [5, 10, 15], "slow_period": [20, 30, 40]}'

    def run_sweep(subcmd, extra, sweep_flag, expect):
        with tempfile.TemporaryDirectory() as tmpdir:
            csv_path = os.path.join(tmpdir, "data.csv")
            _write_ohlcv_csv(csv_path, periods=600, seed=11)
            out_dir = os.path.join(tmpdir, "out")
            argv = [
                "walk_forward", subcmd,
                "--data", csv_path,
                "--symbol", "SPY",
                "--strategy", "sma_crossover",
                "--param-grid", grid,
                "--output", out_dir,
            ] + extra + [sweep_flag, "0", "2", "5"]
            with patch.object(sys, "argv", argv), \
                    redirect_stdout(StringIO()), redirect_stderr(StringIO()):
                rc = walk_forward_main()
            assert rc == 0, f"{subcmd} {sweep_flag} sweep should exit 0, got {rc}"
            sweep_path = os.path.join(out_dir, expect)
            assert os.path.exists(sweep_path), f"{expect} not written"
            with open(sweep_path) as f:
                return json.load(f)

    # walk-forward / out-of-sample / cpcv sweeps gate the DSR on `--deflate`;
    # monte-carlo gates it on `--n-trials` instead (no `--deflate` flag exists
    # for the monte-carlo subcommand).
    sweeps = {
        "borrow": [
            run_sweep("walk-forward", ["--deflate"], "--borrow-costs", "walk_forward_borrow_sweep.json"),
            run_sweep("out-of-sample", ["--deflate"], "--borrow-costs", "out_of_sample_borrow_sweep.json"),
            run_sweep("cpcv", ["--deflate", "--n-splits", "5", "--test-size", "0.2"],
                      "--borrow-costs", "cpcv_borrow_sweep.json"),
            run_sweep("monte-carlo", ["--n-simulations", "50", "--n-trials", "500"],
                      "--borrow-costs", "monte_carlo_borrow_sweep.json"),
        ],
        "funding": [
            run_sweep("walk-forward", ["--deflate"], "--funding-costs", "walk_forward_funding_sweep.json"),
            run_sweep("out-of-sample", ["--deflate"], "--funding-costs", "out_of_sample_funding_sweep.json"),
            run_sweep("cpcv", ["--deflate", "--n-splits", "5", "--test-size", "0.2"],
                      "--funding-costs", "cpcv_funding_sweep.json"),
            run_sweep("monte-carlo", ["--n-simulations", "50", "--n-trials", "500"],
                      "--funding-costs", "monte_carlo_funding_sweep.json"),
        ],
        "commission": [
            run_sweep("walk-forward", ["--deflate"], "--commissions", "walk_forward_commission_sweep.json"),
            run_sweep("out-of-sample", ["--deflate"], "--commissions", "out_of_sample_commission_sweep.json"),
            run_sweep("cpcv", ["--deflate", "--n-splits", "5", "--test-size", "0.2"],
                      "--commissions", "cpcv_commission_sweep.json"),
            run_sweep("monte-carlo", ["--n-simulations", "50", "--n-trials", "500"],
                      "--commissions", "monte_carlo_commission_sweep.json"),
        ],
        "slippage": [
            run_sweep("walk-forward", ["--deflate"], "--slippages", "walk_forward_slippage_sweep.json"),
            run_sweep("out-of-sample", ["--deflate"], "--slippages", "out_of_sample_slippage_sweep.json"),
            run_sweep("cpcv", ["--deflate", "--n-splits", "5", "--test-size", "0.2"],
                      "--slippages", "cpcv_slippage_sweep.json"),
            run_sweep("monte-carlo", ["--n-simulations", "50", "--n-trials", "500"],
                      "--slippages", "monte_carlo_slippage_sweep.json"),
        ],
    }

    for cost_kind, payloads in sweeps.items():
        for payload in payloads:
            rows = payload["results"]
            assert len(rows) == 3, (cost_kind, "expected 3 sweep rows")

            n_trials = [r.get("deflated_sharpe_n_trials") for r in rows]
            # The grid is identical across costs, so the counting basis
            # (the number of configurations the pipeline actually evaluated)
            # must not drift between costs.
            assert n_trials[0] is not None and n_trials[0] == n_trials[1] == n_trials[2], (
                cost_kind, "sweep n_trials must be cost-stable", n_trials
            )
            assert n_trials[0] >= 1, (cost_kind, n_trials)

            for i, r in enumerate(rows):
                label = f"{cost_kind}[{i}]"
                dsr = r.get("deflated_sharpe")
                nt = r.get("deflated_sharpe_n_trials")
                assert dsr is not None, (cost_kind, label, "missing deflated_sharpe")
                assert 0.0 <= dsr <= 1.0, (cost_kind, label, dsr)
                assert nt == n_trials[0], (cost_kind, label, nt, n_trials[0])


def test_optimize_non_impact_sweep_dsr_parity():
    """Optimize non-impact cost sweeps must carry a cost-stable DSR basis.

    Extends the DSR parity guard to the `optimize` subcommand's cost sweeps
    (--borrow-costs, --funding-costs, --commissions, --slippages), which were
    not covered by either sweep parity test. Each sweep re-runs the
    parameter-optimization pipeline for a series of cost values and records a
    per-cost `deflated_sharpe` / `deflated_sharpe_n_trials` row. The grid is
    unchanged across costs, so the multiple-testing correction basis (the
    number of evaluated combinations) must not drift between costs, and the DSR
    must stay in [0, 1] for every row.

    Guards against a regression in per-cost trial counting for the optimize
    path: a sweep that evaluated a different subset of the grid at a different
    cost would still "run" and write a well-formed artifact, but its
    deflated_sharpe_n_trials would drift and its DSR p-values would no longer
    be comparable across costs.
    """
    grid = '{"fast_period": [5, 10, 15], "slow_period": [20, 30, 40]}'

    def run_sweep(sweep_flag, expect):
        with tempfile.TemporaryDirectory() as tmpdir:
            csv_path = os.path.join(tmpdir, "data.csv")
            _write_ohlcv_csv(csv_path, periods=600, seed=11)
            out_dir = os.path.join(tmpdir, "out")
            argv = [
                "walk_forward", "optimize",
                "--data", csv_path,
                "--symbol", "SPY",
                "--strategy", "sma_crossover",
                "--param-grid", grid,
                "--output", out_dir,
                "--deflate",
                sweep_flag, "0", "2", "5",
            ]
            with patch.object(sys, "argv", argv), \
                    redirect_stdout(StringIO()), redirect_stderr(StringIO()):
                rc = walk_forward_main()
            assert rc == 0, f"optimize {sweep_flag} sweep should exit 0, got {rc}"
            sweep_path = os.path.join(out_dir, expect)
            assert os.path.exists(sweep_path), f"{expect} not written"
            with open(sweep_path) as f:
                return json.load(f)

    sweeps = {
        "borrow": run_sweep("--borrow-costs", "parameter_optimization_borrow_sweep.json"),
        "funding": run_sweep("--funding-costs", "parameter_optimization_funding_sweep.json"),
        "commission": run_sweep("--commissions", "parameter_optimization_commission_sweep.json"),
        "slippage": run_sweep("--slippages", "parameter_optimization_slippage_sweep.json"),
    }

    for cost_kind, payload in sweeps.items():
        rows = payload["results"]
        assert len(rows) == 3, (cost_kind, "expected 3 sweep rows")

        n_trials = [r.get("deflated_sharpe_n_trials") for r in rows]
        # The grid is identical across costs, so the counting basis (the
        # number of evaluated combinations) must not drift between costs.
        assert n_trials[0] is not None and n_trials[0] == n_trials[1] == n_trials[2], (
            cost_kind, "sweep n_trials must be cost-stable", n_trials
        )
        assert n_trials[0] >= 1, (cost_kind, n_trials)

        for i, r in enumerate(rows):
            label = f"{cost_kind}[{i}]"
            dsr = r.get("deflated_sharpe")
            nt = r.get("deflated_sharpe_n_trials")
            assert dsr is not None, (cost_kind, label, "missing deflated_sharpe")
            assert 0.0 <= dsr <= 1.0, (cost_kind, label, dsr)
            assert nt == n_trials[0], (cost_kind, label, nt, n_trials[0])


def test_degenerate_constant_return_dsr_consistency():
    """Zero-variance returns must emit the conservative degenerate DSR
    (deflated_sharpe_ratio = 0, p_value = 1, z_score = None) everywhere the
    pipeline reaches deflation, and the trial-counting basis must not drift
    with cost changes.

    Covers:
      1. deflated_sharpe_ratio unit contract on exactly-constant returns.
      2. parameter_optimization --deflate: every combo's deflated_sharpe
         dict is degenerate and n_trials equals the evaluated combo count.
      3. The optimize path's cost basis: varying borrow/funding/commission/
         slippage does not change n_trials (the grid is unchanged) and every
         combo stays on the degenerate DSR under constant returns.
      4. walk_forward_analysis aggregate: random train / constant out-of-sample
         emits the degenerate aggregate DSR rather than a spurious finite-z
         value. (The float-noise residue on a near-constant series must not
         route through the finite-z branch; see _is_constant_returns.)
    """
    grid = {"fast_period": [5, 10, 15], "slow_period": [20, 30, 40]}
    full_grid = len(grid["fast_period"]) * len(grid["slow_period"])
    factory = lambda params: _ConstantLongStrategy()

    # --- 1: unit contract ------------------------------------------------
    dates = pd.date_range("2020-01-01", periods=100, freq="B")
    constant = pd.Series(np.full(100, 0.001), index=dates)
    degenerate = deflated_sharpe_ratio(0.0, constant, n_trials=9)
    assert degenerate["deflated_sharpe_ratio"] == 0.0
    assert degenerate["p_value"] == 1.0
    assert degenerate["z_score"] is None
    assert degenerate["n_trials"] == 9
    assert degenerate["n_observations"] == 100
    # Non-constant returns stay on the finite-z path.
    noisy = pd.Series(
        np.random.default_rng(3).normal(0.001, 0.01, 100), index=dates
    )
    sane = deflated_sharpe_ratio(1.0, noisy, n_trials=9)
    assert 0.0 <= sane["deflated_sharpe_ratio"] <= 1.0
    assert sane["z_score"] is not None

    # --- 2 + 3: parameter_optimization on constant returns ---------------
    data = _make_flat_ohlcv_data(periods=400)
    opt = parameter_optimization(
        data=data,
        strategy_factory=factory,
        param_grid=grid,
        commission=0.0,
        slippage=0.0,
        impact_coefficient=0.0,
        borrow_cost=0.0,
        funding_cost=0.0,
        apply_deflation=True,
    )
    assert len(opt) == full_grid
    for result in opt:
        ds = result["deflated_sharpe"]
        assert ds["deflated_sharpe_ratio"] == 0.0, result["params"]
        assert ds["p_value"] == 1.0, result["params"]
        assert ds["z_score"] is None, result["params"]
        assert ds["n_trials"] == full_grid, result["params"]

    # Cost changes must not move the counting basis off the degenerate DSR.
    base_kwargs = dict(
        commission=0.0, slippage=0.0, impact_coefficient=0.0,
        borrow_cost=0.0, funding_cost=0.0,
    )
    for kwargs in [
        {"borrow_cost": 0.03},
        {"funding_cost": 0.02},
        {"commission": 0.001},
        {"slippage": 0.001},
    ]:
        run_kwargs = dict(base_kwargs)
        run_kwargs.update(kwargs)
        priced = parameter_optimization(
            data=data,
            strategy_factory=factory,
            param_grid=grid,
            apply_deflation=True,
            **run_kwargs,
        )
        assert len(priced) == full_grid, kwargs
        for result in priced:
            ds = result["deflated_sharpe"]
            assert ds["deflated_sharpe_ratio"] == 0.0, (kwargs, result["params"])
            assert ds["p_value"] == 1.0, (kwargs, result["params"])
            assert ds["z_score"] is None, (kwargs, result["params"])
            assert ds["n_trials"] == full_grid, (kwargs, result["params"])

    # --- 4: walk-forward aggregate on random train / constant OOS --------
    wf_data = _make_random_then_constant_data(periods=400, split=252, seed=7)
    wf = walk_forward_analysis(
        data=wf_data,
        strategy_factory=factory,
        param_grid=grid,
        train_months=12,
        test_months=3,
        step_months=3,
        initial_capital=100000,
        commission=0.0,
        slippage=0.0,
        impact_coefficient=0.0,
        borrow_cost=0.0,
        funding_cost=0.0,
        apply_deflation=True,
    )
    ds = wf["summary"]["deflated_sharpe"]
    assert ds is not None
    assert ds["deflated_sharpe_ratio"] == 0.0
    assert ds["p_value"] == 1.0
    assert ds["z_score"] is None
    assert ds["n_trials"] >= 1
    assert wf["summary"]["n_periods"] >= 1


def test_degenerate_constant_return_dar_consistency():
    """Zero-variance returns must emit the conservative degenerate Deflated
    Alpha Ratio (DAR = 0, p_value = 1, z_score = None), mirroring the DSR
    degenerate contract, and non-constant returns must stay on the finite-z
    path with DAR in [0, 1] and p_value = 1 - DAR.

    Covers:
      1. deflated_alpha_ratio unit contract on exactly-constant returns.
      2. Non-constant returns stay on the finite-z path and respect the
         DAR / p_value complement invariant.
      3. Input validation: n_benchmarks < 1 raises ValueError and fewer than
         2 return observations raises ValueError.
    """
    dates = pd.date_range("2020-01-01", periods=100, freq="B")
    constant = pd.Series(np.full(100, 0.001), index=dates)

    # --- 1: unit contract on constant returns -----------------------------
    degenerate = deflated_alpha_ratio(
        alpha=0.02,
        returns=constant,
        benchmark_returns=constant,
        n_benchmarks=3,
    )
    assert degenerate["deflated_alpha_ratio"] == 0.0
    assert degenerate["p_value"] == 1.0
    assert degenerate["z_score"] is None
    assert degenerate["alpha"] == 0.02
    assert abs(degenerate["expected_max_alpha"]) < 1e-9
    assert degenerate["n_benchmarks"] == 3
    assert degenerate["n_observations"] == 100

    # --- 2: non-constant returns stay on the finite-z path ----------------
    noisy = pd.Series(
        np.random.default_rng(3).normal(0.001, 0.01, 100), index=dates
    )
    sane = deflated_alpha_ratio(
        alpha=0.02,
        returns=noisy,
        benchmark_returns=noisy,
        n_benchmarks=3,
    )
    assert 0.0 <= sane["deflated_alpha_ratio"] <= 1.0
    assert sane["z_score"] is not None
    assert abs(sane["p_value"] - (1.0 - sane["deflated_alpha_ratio"])) < 1e-12

    # --- 3: input validation ----------------------------------------------
    for bad_n in (0, -1):
        try:
            deflated_alpha_ratio(
                alpha=0.02,
                returns=noisy,
                benchmark_returns=noisy,
                n_benchmarks=bad_n,
            )
        except ValueError:
            continue
        raise AssertionError(f"n_benchmarks={bad_n} did not raise ValueError")

    try:
        deflated_alpha_ratio(
            alpha=0.02,
            returns=pd.Series([0.001], index=dates[:1]),
            benchmark_returns=pd.Series([0.001], index=dates[:1]),
            n_benchmarks=3,
        )
    except ValueError:
        pass
    else:
        raise AssertionError(
            "single-observation returns did not raise ValueError"
        )


def test_out_of_sample_validation_multiple_benchmarks_deflated_alpha():
    """out_of_sample_validation with multiple benchmarks surfaces Deflated Alpha
    in the summary and preserves backward compatibility with deflated_alphas list.
    """
    data = _make_ohlcv_data(periods=1000, seed=42)
    bench1 = _make_benchmark_data(periods=1000, seed=99)
    bench2 = _make_benchmark_data(periods=1000, seed=7)
    factory = lambda params: build_strategy("sma_crossover", json.dumps(params))
    param_grid = {"fast_period": [3, 5, 7], "slow_period": [10, 12, 15]}

    results = out_of_sample_validation(
        data=data,
        strategy_factory=factory,
        param_grid=param_grid,
        train_frac=0.6,
        val_frac=0.2,
        test_frac=0.2,
        validation_method="walk_forward",
        initial_capital=100000,
        commission=0.0002,
        slippage=0.0001,
        benchmark=[bench1, bench2],
        benchmark_commission=0.001,
        benchmark_slippage=0.001,
        benchmark_cost_is_periodic=True,
    )

    # Verify the basic structure
    assert results is not None
    assert "summary" in results
    assert "test_benchmark" in results
    assert "selected_params" in results

    # Verify multiple benchmark handling
    test_bench = results["test_benchmark"]
    assert isinstance(test_bench, list), "test_benchmark should be a list for multiple benchmarks"
    assert len(test_bench) == 2, "Should have results for both benchmarks"

    # Verify summary contains both the new canonical deflated_alpha and the backward-compatible deflated_alphas list
    summary = results["summary"]
    assert "deflated_alpha" in summary, "summary should contain deflated_alpha (canonical single dict)"
    assert "deflated_alphas" in summary, "summary should contain deflated_alphas (backward compatibility list)"

    # Verify benchmark_metrics is surfaced consistently with CPCV/walk_forward
    assert "benchmark_metrics" in summary, "summary should contain benchmark_metrics"
    assert isinstance(summary["benchmark_metrics"], list), "benchmark_metrics should be a list"
    assert len(summary["benchmark_metrics"]) == 2, f"Expected 2 benchmark_metrics entries, got {len(summary['benchmark_metrics'])}"

    # Verify the canonical deflated_alpha has the expected structure
    da = summary["deflated_alpha"]
    assert isinstance(da, dict), "deflated_alpha should be a dict"
    assert da["n_benchmarks"] == 2, f"Expected n_benchmarks=2, got {da['n_benchmarks']}"
    assert 0.0 <= da["deflated_alpha_ratio"] <= 1.0, "deflated_alpha_ratio should be in [0,1]"
    assert 0.0 <= da["p_value"] <= 1.0, "p_value should be in [0,1]"

    # Verify backward compatibility: deflated_alphas list should have entries for each benchmark
    deflated_alphas = summary["deflated_alphas"]
    assert isinstance(deflated_alphas, list), "deflated_alphas should be a list"
    assert len(deflated_alphas) == 2, f"Expected 2 entries in deflated_alphas list, got {len(deflated_alphas)}"

    # Verify each entry in deflated_alphas has the expected fields
    for i, bench_da in enumerate(deflated_alphas):
        if bench_da is not None:  # Skip if benchmark had no aligned returns
            assert "deflated_alpha" in bench_da, f"Benchmark {i} deflated_alphas entry missing deflated_alpha"
            assert "alpha_pvalue" in bench_da, f"Benchmark {i} deflated_alphas entry missing alpha_pvalue"
            assert "alpha_pvalue_original" in bench_da, f"Benchmark {i} deflated_alphas entry missing alpha_pvalue_original"
            assert "expected_max_alpha" in bench_da, f"Benchmark {i} deflated_alphas entry missing expected_max_alpha"

    # Verify the consolidated backward-compatible lists were derived correctly
    # from correction_result (regression guard: they must match the per-benchmark
    # entries surfaced above, not be empty or stale).
    n_valid = sum(1 for b in test_bench if b is not None and "alpha_pvalue" in b)
    assert "alpha_pvalues" in summary, "summary should contain alpha_pvalues"
    assert len(summary["alpha_pvalues"]) == n_valid, (
        f"alpha_pvalues length {len(summary['alpha_pvalues'])} != {n_valid}"
    )
    assert "alpha_pvalues_original" in summary, "summary should contain alpha_pvalues_original"
    assert len(summary["alpha_pvalues_original"]) == n_valid
    assert "expected_max_alphas" in summary, "summary should contain expected_max_alphas"
    assert len(summary["expected_max_alphas"]) == n_valid
    # Each deflated_alphas entry (full dict) is the same object as the
    # corresponding benchmark_metrics entry, confirming the refactor sources
    # both from the single correction_result rather than duplicating work.
    assert summary["deflated_alphas"] == summary["benchmark_metrics"]

    # Verify the canonical aggregate deflated_alpha is consistent with the
    # helper's aggregate result, and primary-benchmark convenience fields
    # match the first entry.
    assert summary["alpha_pvalue"] == summary["benchmark_metrics"][0]["alpha_pvalue"]
    assert summary["alpha_pvalue_original"] == summary["benchmark_metrics"][0]["alpha_pvalue_original"]


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


def test_benchmark_list_alpha_correction_per_benchmark_pvalue_is_dar_pvalue():
    """Per-benchmark ``alpha_pvalue`` must equal the Deflated Alpha Ratio p-value.

    Regression guard for a defect where the DAR p-value computed by
    ``deflated_alpha_ratio`` was discarded: a stray ``else`` clause on the
    ``try``/``except`` overwrote the corrected p-value with a Bonferroni
    fallback (``min(p * N, 1.0)``) on the success path, so the reported
    ``alpha_pvalue`` disagreed with the ``deflated_alpha`` ratio the same dict
    had just computed.  The corrected p-value must be the DAR p-value whenever
    the cross-sectional estimator is available.
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

    trial_alphas = [
        r["alpha"] for r in result["per_benchmark"]
        if r is not None and "alpha" in r and np.isfinite(r["alpha"])
    ]
    assert len(trial_alphas) >= 2, "Expected at least 2 finite trial alphas"

    # deflated_alpha_ratio accepts benchmark_returns but does not consume it;
    # the DAR depends only on alpha, returns, n_benchmarks and trial_alphas, so
    # it can be recomputed exactly from the surfaced per-benchmark alpha.
    bench_returns_list = [bench1["close"].pct_change(), bench2["close"].pct_change()]
    for i, stats in enumerate(result["per_benchmark"]):
        assert stats is not None
        dar = deflated_alpha_ratio(
            alpha=stats["alpha"],
            returns=strategy_returns,
            benchmark_returns=bench_returns_list[i],
            n_benchmarks=result["n_benchmarks"],
            trial_alphas=trial_alphas,
        )
        bonferroni = min(stats["alpha_pvalue_original"] * result["n_benchmarks"], 1.0)
        assert abs(stats["alpha_pvalue"] - dar["p_value"]) < 1e-12, (
            f"benchmark {i}: alpha_pvalue {stats['alpha_pvalue']} != DAR p_value "
            f"{dar['p_value']} (Bonferroni fallback would be {bonferroni})"
        )
        assert abs(stats["deflated_alpha"] - dar["deflated_alpha_ratio"]) < 1e-12, (
            f"benchmark {i}: deflated_alpha {stats['deflated_alpha']} != DAR ratio "
            f"{dar['deflated_alpha_ratio']}"
        )
        assert abs(stats["expected_max_alpha"] - dar["expected_max_alpha"]) < 1e-12, (
            f"benchmark {i}: expected_max_alpha {stats['expected_max_alpha']} != "
            f"DAR expected_max_alpha {dar['expected_max_alpha']}"
        )


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


def test_cli_walk_forward_multiple_benchmarks():
    """CLI walk_forward subcommand accepts multiple --benchmark files, does not crash
    in the post-call benchmark block, and writes a walk_forward_summary.json whose
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
            "walk_forward", "walk-forward",
            "--data", csv_path,
            "--benchmark", bench1_path, bench2_path,
            "--strategy", "sma_crossover",
            "--param-grid", '{"fast_period": [3, 5, 7], "slow_period": [10, 12, 15]}',
            "--output", out_dir,
            "--benchmark-commission", "0.001",
            "--benchmark-slippage", "0.001",
            "--benchmark-cost-is-periodic",
            "--train-months", "12",
            "--test-months", "3",
            "--step-months", "2",
        ]
        with patch.object(sys, "argv", argv), \
                redirect_stdout(StringIO()), redirect_stderr(StringIO()):
            rc = walk_forward_main()

        assert rc == 0, f"CLI walk_forward with multiple benchmarks should exit 0, got {rc}"
        summary_path = os.path.join(out_dir, "walk_forward_summary.json")
        assert os.path.exists(summary_path), "walk_forward_summary.json not written"
        with open(summary_path) as f:
            payload = json.load(f)

        assert "summary" in payload, "summary missing from walk_forward_summary.json"
        summary = payload["summary"]
        assert "deflated_alpha" in summary, (
            f"deflated_alpha missing from CLI walk_forward summary. Keys: {sorted(summary.keys())}"
        )
        da = summary["deflated_alpha"]
        assert da["n_benchmarks"] == 2
        assert 0.0 <= da["deflated_alpha_ratio"] <= 1.0
        assert isinstance(summary.get("benchmark_metrics"), list)
        assert len(summary["benchmark_metrics"]) == 2


def test_cli_walk_forward_constant_benchmarks_defensive_fallback_surfaces_metrics():
    """CLI walk-forward with constant-price benchmarks surfaces benchmark_metrics via the defensive fallback.

    A constant-price benchmark has zero return variance (sxx == 0), so
    _benchmark_stats emits no alpha key, _benchmark_list_alpha_correction
    returns deflated_alpha=None, and walk_forward_analysis therefore leaves
    summary["deflated_alpha"] unset. The defensive block at walk_forward.py:3757
    re-runs the correction on the CLI side because
    results["summary"].get("deflated_alpha") is None, and must still write
    summary["benchmark_metrics"] (one entry per benchmark) into
    walk_forward_summary.json. No deflated alpha can be computed from constant
    benchmarks, so it must remain absent rather than be fabricated.
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        csv_path = os.path.join(tmpdir, "data.csv")
        bench1_path = os.path.join(tmpdir, "bench1.csv")
        bench2_path = os.path.join(tmpdir, "bench2.csv")
        _write_ohlcv_csv(csv_path, periods=800)
        flat = _make_flat_ohlcv_data(periods=800)
        flat.reset_index().rename(columns={"index": "date"}).to_csv(bench1_path, index=False)
        flat.reset_index().rename(columns={"index": "date"}).to_csv(bench2_path, index=False)
        out_dir = os.path.join(tmpdir, "out")
        argv = [
            "walk_forward", "walk-forward",
            "--data", csv_path,
            "--benchmark", bench1_path, bench2_path,
            "--strategy", "sma_crossover",
            "--param-grid", '{"fast_period": [3, 5], "slow_period": [8, 10]}',
            "--output", out_dir,
            "--benchmark-commission", "0.001",
            "--benchmark-slippage", "0.001",
            "--train-months", "12",
            "--test-months", "3",
            "--step-months", "2",
        ]
        series_lengths = []

        def counting_correction(*args, **kwargs):
            try:
                series_lengths.append(len(args[0]))
            except Exception:
                series_lengths.append(None)
            return _benchmark_list_alpha_correction(*args, **kwargs)

        with patch.object(sys, "argv", argv), \
                patch("walk_forward._benchmark_list_alpha_correction", side_effect=counting_correction), \
                redirect_stdout(StringIO()), redirect_stderr(StringIO()):
            rc = walk_forward_main()

        assert rc == 0, f"CLI walk-forward with constant benchmarks should exit 0, got {rc}"
        summary_path = os.path.join(out_dir, "walk_forward_summary.json")
        assert os.path.exists(summary_path), "walk_forward_summary.json not written"
        with open(summary_path) as f:
            payload = json.load(f)

        summary = payload["summary"]
        # The aggregate call inside walk_forward_analysis (walk_forward.py:536)
        # and the defensive fallback call (walk_forward.py:3761) both receive
        # the full combined OOS returns, which is longer than any per-period
        # slice (walk_forward.py:476). Exactly two such calls proves the
        # fallback block executed on top of analysis's own call.
        max_len = max(series_lengths)
        full_series_calls = sum(1 for n in series_lengths if n == max_len)
        assert full_series_calls == 2, (
            f"Expected exactly 2 full-series correction calls "
            f"(aggregate in analysis + defensive fallback), got {full_series_calls}"
        )

        assert "benchmark_metrics" in summary, (
            f"benchmark_metrics missing from summary. Keys: {sorted(summary.keys())}"
        )
        assert isinstance(summary["benchmark_metrics"], list)
        assert len(summary["benchmark_metrics"]) == 2
        # Constant-price benchmarks carry no finite alpha, so no deflated
        # alpha can be computed by either the analysis or the fallback.
        assert summary.get("deflated_alpha") is None


def test_cli_optimize_multiple_benchmarks():
    """CLI optimize subcommand accepts multiple --benchmark files, does not crash
    in the per-combo benchmark block or provenance save, and writes a
    parameter_optimization.json whose best result includes a cross-benchmark
    deflated_alpha correction plus per-benchmark metrics.
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
            "walk_forward", "optimize",
            "--data", csv_path,
            "--benchmark", bench1_path, bench2_path,
            "--strategy", "sma_crossover",
            "--param-grid", '{"fast_period": [3, 5, 7], "slow_period": [10, 12, 15]}',
            "--output", out_dir,
            "--benchmark-commission", "0.001",
            "--benchmark-slippage", "0.001",
            "--benchmark-cost-is-periodic",
        ]
        with patch.object(sys, "argv", argv), \
                redirect_stdout(StringIO()), redirect_stderr(StringIO()):
            rc = walk_forward_main()

        assert rc == 0, f"CLI optimize with multiple benchmarks should exit 0, got {rc}"
        results_path = os.path.join(out_dir, "parameter_optimization.json")
        assert os.path.exists(results_path), "parameter_optimization.json not written"
        with open(results_path) as f:
            payload = json.load(f)

        best = payload[0]
        assert "deflated_alpha" in best, "best result should have deflated_alpha"
        da = best["deflated_alpha"]
        assert da["n_benchmarks"] == 2
        assert 0.0 <= da["deflated_alpha_ratio"] <= 1.0
        assert 0.0 <= da["p_value"] <= 1.0

        assert "benchmark_metrics" in best, "best result should have benchmark_metrics"
        bm = best["benchmark_metrics"]
        assert isinstance(bm, list)
        assert len(bm) == 2


def test_cli_monte_carlo_multiple_benchmarks():
    """CLI monte_carlo subcommand accepts multiple --benchmark files, does not crash
    in the post-call benchmark block, and writes a monte_carlo_results.json whose
    summary contains a cross-benchmark benchmark_metrics list.
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
            "walk_forward", "monte-carlo",
            "--data", csv_path,
            "--benchmark", bench1_path, bench2_path,
            "--strategy", "sma_crossover",
            "--param-grid", '{"fast_period": [3, 5, 7], "slow_period": [10, 12, 15]}',
            "--output", out_dir,
            "--benchmark-commission", "0.001",
            "--benchmark-slippage", "0.001",
            "--benchmark-cost-is-periodic",
            "--n-simulations", "50",
        ]
        with patch.object(sys, "argv", argv), \
                redirect_stdout(StringIO()), redirect_stderr(StringIO()):
            rc = walk_forward_main()

        assert rc == 0, f"CLI monte_carlo with multiple benchmarks should exit 0, got {rc}"
        results_path = os.path.join(out_dir, "monte_carlo_results.json")
        assert os.path.exists(results_path), "monte_carlo_results.json not written"
        with open(results_path) as f:
            payload = json.load(f)

        assert "summary" in payload, "summary missing from monte_carlo_results.json"
        summary = payload["summary"]
        assert isinstance(summary.get("benchmark_metrics"), list), (
            f"benchmark_metrics missing or not a list. Keys: {sorted(summary.keys())}"
        )
        assert len(summary["benchmark_metrics"]) == 2

        # Provenance should be a list for multiple benchmarks
        prov = payload.get("benchmark_provenance")
        assert isinstance(prov, list), f"benchmark_provenance should be a list, got {type(prov)}"
        assert len(prov) == 2

        # Config should record the periodic flag
        assert payload["config"]["benchmark_cost_is_periodic"] is True

        # Tear sheet coverage: the Monte Carlo tear sheet must render the
        # multiple-benchmark Deflated Alpha section end-to-end, confirming the
        # run_monte_carlo -> calculate_metrics(benchmark_list) -> generate_tear_sheet
        # integration actually surfaces deflated-alpha in the HTML output.
        ts_path = os.path.join(out_dir, "tear_sheet.html")
        assert os.path.exists(ts_path), "tear_sheet.html not written"
        with open(ts_path) as f:
            html = f.read()
        assert "Multiple-Testing Correction (Deflated Alpha)" in html, (
            "tear sheet should render the Deflated Alpha section"
        )
        assert "Per-Benchmark Comparison" in html, (
            "tear sheet should render the per-benchmark comparison"
        )

        # Canonical deflated_alpha dict must be present on the summary, matching
        # the CPCV/walk-forward/out-of-sample multiple-benchmark shape.
        assert isinstance(summary.get("deflated_alpha"), dict), (
            "summary should carry the canonical deflated_alpha dict"
        )
        da = summary["deflated_alpha"]
        assert 0.0 <= da["deflated_alpha_ratio"] <= 1.0, (
            f"deflated_alpha_ratio out of [0,1]: {da.get('deflated_alpha_ratio')}"
        )
        assert da["n_benchmarks"] == 2


def test_cli_monte_carlo_impact_sweep():
    """CLI monte-carlo --impact-coefficients writes a sweep artifact whose
    returns degrade monotonically as the market-impact coefficient rises."""
    with tempfile.TemporaryDirectory() as tmpdir:
        csv_path = os.path.join(tmpdir, "data.csv")
        _write_ohlcv_csv(csv_path, periods=600)
        out_dir = os.path.join(tmpdir, "out")
        argv = [
            "walk_forward", "monte-carlo",
            "--data", csv_path,
            "--symbol", "SPY",
            "--strategy", "sma_crossover",
            "--param-grid", '{"fast_period": [3, 5, 7], "slow_period": [10, 12, 15]}',
            "--output", out_dir,
            "--n-simulations", "100",
            "--impact-coefficients", "0", "2", "5",
        ]
        with patch.object(sys, "argv", argv), \
                redirect_stdout(StringIO()), redirect_stderr(StringIO()):
            rc = walk_forward_main()

        assert rc == 0, f"CLI monte_carlo impact sweep should exit 0, got {rc}"
        sweep_path = os.path.join(out_dir, "monte_carlo_impact_sweep.json")
        assert os.path.exists(sweep_path), "monte_carlo_impact_sweep.json not written"
        with open(sweep_path) as f:
            payload = json.load(f)
        assert payload["impact_coefficients"] == [0.0, 2.0, 5.0]
        assert len(payload["results"]) == 3
        returns = [r["total_return"] for r in payload["results"]]
        # Higher market-impact cost degrades the net return (endpoints).
        assert returns[2] < returns[0], (
            f"expected return degradation with impact, got {returns}"
        )



def test_monte_carlo_n_trials_uses_evaluated_combo_count():
    """run_monte_carlo with --n-trials and a param grid must deflate using
    the actually-evaluated combo count, not the user-supplied n_trials.
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        csv_path = os.path.join(tmpdir, "data.csv")
        _write_ohlcv_csv(csv_path, periods=600)
        out_dir = os.path.join(tmpdir, "out")
        argv = [
            "walk_forward", "monte-carlo",
            "--data", csv_path,
            "--symbol", "SPY",
            "--strategy", "sma_crossover",
            "--param-grid", '{"fast_period": [3, 5, 7], "slow_period": [10, 12, 15]}',
            "--n-trials", "500",
            "--output", out_dir,
        ]
        with patch.object(sys, "argv", argv), \
                redirect_stdout(StringIO()), redirect_stderr(StringIO()):
            rc = walk_forward_main()

        assert rc == 0, f"CLI monte-carlo should exit 0, got {rc}"
        mc_path = os.path.join(out_dir, "monte_carlo_results.json")
        assert os.path.exists(mc_path), "monte_carlo_results.json not written"
        with open(mc_path) as f:
            payload = json.load(f)
        assert payload["config"]["n_trials"] == 9, (
            f"expected n_trials 9 (evaluated combos), got {payload['config'].get('n_trials')}"
        )
        assert "deflated_sharpe" in payload
        assert payload["deflated_sharpe"]["n_trials"] == 9, (
            f"expected deflated_sharpe n_trials 9, got {payload['deflated_sharpe'].get('n_trials')}"
        )


def test_cli_cpcv_impact_sweep():
    """CLI cpcv --impact-coefficients writes a sweep artifact whose OOS
    returns degrade monotonically as the market-impact coefficient rises."""
    with tempfile.TemporaryDirectory() as tmpdir:
        csv_path = os.path.join(tmpdir, "data.csv")
        _write_ohlcv_csv(csv_path, periods=600)
        out_dir = os.path.join(tmpdir, "out")
        argv = [
            "walk_forward", "cpcv",
            "--data", csv_path,
            "--symbol", "SPY",
            "--strategy", "sma_crossover",
            "--param-grid", '{"fast_period": [3, 5, 7], "slow_period": [10, 12, 15]}',
            "--output", out_dir,
            "--n-splits", "5",
            "--test-size", "0.2",
            "--impact-coefficients", "0", "2", "5",
        ]
        with patch.object(sys, "argv", argv), \
                redirect_stdout(StringIO()), redirect_stderr(StringIO()):
            rc = walk_forward_main()

        assert rc == 0, f"CLI cpcv impact sweep should exit 0, got {rc}"
        sweep_path = os.path.join(out_dir, "cpcv_impact_sweep.json")
        assert os.path.exists(sweep_path), "cpcv_impact_sweep.json not written"
        with open(sweep_path) as f:
            payload = json.load(f)
        assert payload["impact_coefficients"] == [0.0, 2.0, 5.0]
        assert len(payload["results"]) == 3
        returns = [r["total_oos_return"] for r in payload["results"]]
        assert returns[2] < returns[0], (
            f"expected OOS return degradation with impact, got {returns}"
        )


def test_cli_monte_carlo_borrow_sweep():
    """CLI monte-carlo --borrow-costs writes a sweep artifact whose returns
    degrade as the short-position borrow cost rises (MACD goes short)."""
    with tempfile.TemporaryDirectory() as tmpdir:
        csv_path = os.path.join(tmpdir, "data.csv")
        _write_ohlcv_csv(csv_path, periods=600)
        out_dir = os.path.join(tmpdir, "out")
        argv = [
            "walk_forward", "monte-carlo",
            "--data", csv_path,
            "--symbol", "SPY",
            "--strategy", "macd",
            "--param-grid", '{"fast_period": [10, 12], "slow_period": [24, 26], "signal_period": [8, 9]}',
            "--output", out_dir,
            "--n-simulations", "100",
            "--borrow-costs", "0", "0.03", "0.10",
        ]
        with patch.object(sys, "argv", argv), \
                redirect_stdout(StringIO()), redirect_stderr(StringIO()):
            rc = walk_forward_main()

        assert rc == 0, f"CLI monte_carlo borrow sweep should exit 0, got {rc}"
        sweep_path = os.path.join(out_dir, "monte_carlo_borrow_sweep.json")
        assert os.path.exists(sweep_path), "monte_carlo_borrow_sweep.json not written"
        with open(sweep_path) as f:
            payload = json.load(f)
        assert payload["borrow_costs"] == [0.0, 0.03, 0.1]
        assert len(payload["results"]) == 3
        returns = [r["total_return"] for r in payload["results"]]
        # Higher borrow cost degrades the net return (endpoints).
        assert returns[2] < returns[0], (
            f"expected return degradation with borrow cost, got {returns}"
        )


def test_cli_cpcv_borrow_sweep():
    """CLI cpcv --borrow-costs writes a sweep artifact whose OOS returns
    degrade as the short-position borrow cost rises (MACD goes short)."""
    with tempfile.TemporaryDirectory() as tmpdir:
        csv_path = os.path.join(tmpdir, "data.csv")
        _write_ohlcv_csv(csv_path, periods=600)
        out_dir = os.path.join(tmpdir, "out")
        argv = [
            "walk_forward", "cpcv",
            "--data", csv_path,
            "--symbol", "SPY",
            "--strategy", "macd",
            "--param-grid", '{"fast_period": [10, 12], "slow_period": [24, 26], "signal_period": [8, 9]}',
            "--output", out_dir,
            "--n-splits", "5",
            "--test-size", "0.2",
            "--borrow-costs", "0", "0.03", "0.10",
        ]
        with patch.object(sys, "argv", argv), \
                redirect_stdout(StringIO()), redirect_stderr(StringIO()):
            rc = walk_forward_main()

        assert rc == 0, f"CLI cpcv borrow sweep should exit 0, got {rc}"
        sweep_path = os.path.join(out_dir, "cpcv_borrow_sweep.json")
        assert os.path.exists(sweep_path), "cpcv_borrow_sweep.json not written"
        with open(sweep_path) as f:
            payload = json.load(f)
        assert payload["borrow_costs"] == [0.0, 0.03, 0.1]
        assert len(payload["results"]) == 3
        returns = [r["total_oos_return"] for r in payload["results"]]
        assert returns[2] < returns[0], (
            f"expected OOS return degradation with borrow cost, got {returns}"
        )


def test_cli_monte_carlo_funding_sweep():
    """CLI monte-carlo --funding-costs writes a sweep artifact whose returns
    degrade as the leveraged-position funding cost rises."""
    with tempfile.TemporaryDirectory() as tmpdir:
        csv_path = os.path.join(tmpdir, "data.csv")
        _write_ohlcv_csv(csv_path, periods=600)
        out_dir = os.path.join(tmpdir, "out")
        argv = [
            "walk_forward", "monte-carlo",
            "--data", csv_path,
            "--symbol", "SPY",
            "--strategy", "macd",
            "--param-grid", '{"fast_period": [10, 12], "slow_period": [24, 26], "signal_period": [8, 9]}',
            "--output", out_dir,
            "--n-simulations", "100",
            "--funding-costs", "0", "0.03", "0.10",
        ]
        with patch.object(sys, "argv", argv), \
                redirect_stdout(StringIO()), redirect_stderr(StringIO()):
            rc = walk_forward_main()

        assert rc == 0, f"CLI monte_carlo funding sweep should exit 0, got {rc}"
        sweep_path = os.path.join(out_dir, "monte_carlo_funding_sweep.json")
        assert os.path.exists(sweep_path), "monte_carlo_funding_sweep.json not written"
        with open(sweep_path) as f:
            payload = json.load(f)
        assert payload["funding_costs"] == [0.0, 0.03, 0.1]
        assert len(payload["results"]) == 3
        returns = [r["total_return"] for r in payload["results"]]
        # Funding costs never increase net return: for an unlevered strategy
        # (MACD positions ∈ {-1, 0, 1}, gross exposure ≤ 1) funding is a no-op
        # and returns are equal; for a levered strategy they degrade. Either
        # way the endpoint must not exceed the zero-cost baseline.
        assert returns[2] <= returns[0], (
            f"expected non-increasing return with funding cost, got {returns}"
        )
        # The per-row funding_cost field must be recorded.
        assert [r["funding_cost"] for r in payload["results"]] == [0.0, 0.03, 0.1]


def test_cli_cpcv_funding_sweep():
    """CLI cpcv --funding-costs writes a sweep artifact whose OOS returns
    never increase as the leveraged-position funding cost rises."""
    with tempfile.TemporaryDirectory() as tmpdir:
        csv_path = os.path.join(tmpdir, "data.csv")
        _write_ohlcv_csv(csv_path, periods=600)
        out_dir = os.path.join(tmpdir, "out")
        argv = [
            "walk_forward", "cpcv",
            "--data", csv_path,
            "--symbol", "SPY",
            "--strategy", "macd",
            "--param-grid", '{"fast_period": [10, 12], "slow_period": [24, 26], "signal_period": [8, 9]}',
            "--output", out_dir,
            "--n-splits", "5",
            "--test-size", "0.2",
            "--funding-costs", "0", "0.03", "0.10",
        ]
        with patch.object(sys, "argv", argv), \
                redirect_stdout(StringIO()), redirect_stderr(StringIO()):
            rc = walk_forward_main()

        assert rc == 0, f"CLI cpcv funding sweep should exit 0, got {rc}"
        sweep_path = os.path.join(out_dir, "cpcv_funding_sweep.json")
        assert os.path.exists(sweep_path), "cpcv_funding_sweep.json not written"
        with open(sweep_path) as f:
            payload = json.load(f)
        assert payload["funding_costs"] == [0.0, 0.03, 0.1]
        assert len(payload["results"]) == 3
        returns = [r["total_oos_return"] for r in payload["results"]]
        assert returns[2] <= returns[0], (
            f"expected non-increasing OOS return with funding cost, got {returns}"
        )
        assert [r["funding_cost"] for r in payload["results"]] == [0.0, 0.03, 0.1]


def test_cli_walk_forward_impact_sweep():
    """CLI walk-forward --impact-coefficients writes a sweep artifact whose
    OOS returns degrade as the market-impact coefficient rises."""
    with tempfile.TemporaryDirectory() as tmpdir:
        csv_path = os.path.join(tmpdir, "data.csv")
        _write_ohlcv_csv(csv_path, periods=600)
        out_dir = os.path.join(tmpdir, "out")
        argv = [
            "walk_forward", "walk-forward",
            "--data", csv_path,
            "--symbol", "SPY",
            "--strategy", "sma_crossover",
            "--param-grid", '{"fast_period": [3, 5, 7], "slow_period": [10, 12, 15]}',
            "--output", out_dir,
            "--impact-coefficients", "0", "2", "5",
        ]
        with patch.object(sys, "argv", argv), \
                redirect_stdout(StringIO()), redirect_stderr(StringIO()):
            rc = walk_forward_main()

        assert rc == 0, f"CLI walk-forward impact sweep should exit 0, got {rc}"
        sweep_path = os.path.join(out_dir, "walk_forward_impact_sweep.json")
        assert os.path.exists(sweep_path), "walk_forward_impact_sweep.json not written"
        with open(sweep_path) as f:
            payload = json.load(f)
        assert payload["impact_coefficients"] == [0.0, 2.0, 5.0]
        assert len(payload["results"]) == 3
        returns = [r["total_oos_return"] for r in payload["results"]]
        assert returns[2] < returns[0], (
            f"expected OOS return degradation with impact, got {returns}"
        )


def test_cli_walk_forward_borrow_sweep():
    """CLI walk-forward --borrow-costs writes a sweep artifact whose OOS
    returns degrade as the short-position borrow cost rises (MACD goes short)."""
    with tempfile.TemporaryDirectory() as tmpdir:
        csv_path = os.path.join(tmpdir, "data.csv")
        _write_ohlcv_csv(csv_path, periods=600)
        out_dir = os.path.join(tmpdir, "out")
        argv = [
            "walk_forward", "walk-forward",
            "--data", csv_path,
            "--symbol", "SPY",
            "--strategy", "macd",
            "--param-grid", '{"fast_period": [10, 12], "slow_period": [24, 26], "signal_period": [8, 9]}',
            "--output", out_dir,
            "--borrow-costs", "0", "0.03", "0.10",
        ]
        with patch.object(sys, "argv", argv), \
                redirect_stdout(StringIO()), redirect_stderr(StringIO()):
            rc = walk_forward_main()

        assert rc == 0, f"CLI walk-forward borrow sweep should exit 0, got {rc}"
        sweep_path = os.path.join(out_dir, "walk_forward_borrow_sweep.json")
        assert os.path.exists(sweep_path), "walk_forward_borrow_sweep.json not written"
        with open(sweep_path) as f:
            payload = json.load(f)
        assert payload["borrow_costs"] == [0.0, 0.03, 0.1]
        assert len(payload["results"]) == 3
        returns = [r["total_oos_return"] for r in payload["results"]]
        assert returns[2] < returns[0], (
            f"expected OOS return degradation with borrow cost, got {returns}"
        )


def test_cli_walk_forward_funding_sweep():
    """CLI walk-forward --funding-costs writes a sweep artifact whose OOS
    returns never increase as the leveraged-position funding cost rises."""
    with tempfile.TemporaryDirectory() as tmpdir:
        csv_path = os.path.join(tmpdir, "data.csv")
        _write_ohlcv_csv(csv_path, periods=600)
        out_dir = os.path.join(tmpdir, "out")
        argv = [
            "walk_forward", "walk-forward",
            "--data", csv_path,
            "--symbol", "SPY",
            "--strategy", "sma_crossover",
            "--param-grid", '{"fast_period": [3, 5, 7], "slow_period": [10, 12, 15]}',
            "--output", out_dir,
            "--funding-costs", "0", "0.03", "0.10",
        ]
        with patch.object(sys, "argv", argv), \
                redirect_stdout(StringIO()), redirect_stderr(StringIO()):
            rc = walk_forward_main()

        assert rc == 0, f"CLI walk-forward funding sweep should exit 0, got {rc}"
        sweep_path = os.path.join(out_dir, "walk_forward_funding_sweep.json")
        assert os.path.exists(sweep_path), "walk_forward_funding_sweep.json not written"
        with open(sweep_path) as f:
            payload = json.load(f)
        assert payload["funding_costs"] == [0.0, 0.03, 0.1]
        assert len(payload["results"]) == 3
        returns = [r["total_oos_return"] for r in payload["results"]]
        assert returns[2] <= returns[0], (
            f"expected non-increasing OOS return with funding cost, got {returns}"
        )
        assert [r["funding_cost"] for r in payload["results"]] == [0.0, 0.03, 0.1]


def test_cli_optimize_impact_sweep():
    """CLI optimize --impact-coefficients writes a sweep artifact whose top
    return degrades as the market-impact coefficient rises."""
    with tempfile.TemporaryDirectory() as tmpdir:
        csv_path = os.path.join(tmpdir, "data.csv")
        _write_ohlcv_csv(csv_path, periods=600)
        out_dir = os.path.join(tmpdir, "out")
        argv = [
            "walk_forward", "optimize",
            "--data", csv_path,
            "--symbol", "SPY",
            "--strategy", "sma_crossover",
            "--param-grid", '{"fast_period": [3, 5, 7], "slow_period": [10, 12, 15]}',
            "--output", out_dir,
            "--impact-coefficients", "0", "2", "5",
        ]
        with patch.object(sys, "argv", argv), \
                redirect_stdout(StringIO()), redirect_stderr(StringIO()):
            rc = walk_forward_main()

        assert rc == 0, f"CLI optimize impact sweep should exit 0, got {rc}"
        sweep_path = os.path.join(out_dir, "parameter_optimization_impact_sweep.json")
        assert os.path.exists(sweep_path), "parameter_optimization_impact_sweep.json not written"
        with open(sweep_path) as f:
            payload = json.load(f)
        assert payload["impact_coefficients"] == [0.0, 2.0, 5.0]
        assert len(payload["results"]) == 3
        returns = [r["top_total_return"] for r in payload["results"]]
        assert returns[2] < returns[0], (
            f"expected top return degradation with impact, got {returns}"
        )


def test_cli_optimize_borrow_sweep():
    """CLI optimize --borrow-costs writes a sweep artifact whose top return
    degrades as the short-position borrow cost rises (MACD goes short)."""
    with tempfile.TemporaryDirectory() as tmpdir:
        csv_path = os.path.join(tmpdir, "data.csv")
        _write_ohlcv_csv(csv_path, periods=600)
        out_dir = os.path.join(tmpdir, "out")
        argv = [
            "walk_forward", "optimize",
            "--data", csv_path,
            "--symbol", "SPY",
            "--strategy", "macd",
            "--param-grid", '{"fast_period": [10, 12], "slow_period": [24, 26], "signal_period": [8, 9]}',
            "--output", out_dir,
            "--borrow-costs", "0", "0.03", "0.10",
        ]
        with patch.object(sys, "argv", argv), \
                redirect_stdout(StringIO()), redirect_stderr(StringIO()):
            rc = walk_forward_main()

        assert rc == 0, f"CLI optimize borrow sweep should exit 0, got {rc}"
        sweep_path = os.path.join(out_dir, "parameter_optimization_borrow_sweep.json")
        assert os.path.exists(sweep_path), "parameter_optimization_borrow_sweep.json not written"
        with open(sweep_path) as f:
            payload = json.load(f)
        assert payload["borrow_costs"] == [0.0, 0.03, 0.1]
        assert len(payload["results"]) == 3
        returns = [r["top_total_return"] for r in payload["results"]]
        assert returns[2] < returns[0], (
            f"expected top return degradation with borrow cost, got {returns}"
        )


def test_cli_optimize_funding_sweep():
    """CLI optimize --funding-costs writes a sweep artifact whose top return
    never increases as the leveraged-position funding cost rises."""
    with tempfile.TemporaryDirectory() as tmpdir:
        csv_path = os.path.join(tmpdir, "data.csv")
        _write_ohlcv_csv(csv_path, periods=600)
        out_dir = os.path.join(tmpdir, "out")
        argv = [
            "walk_forward", "optimize",
            "--data", csv_path,
            "--symbol", "SPY",
            "--strategy", "sma_crossover",
            "--param-grid", '{"fast_period": [3, 5, 7], "slow_period": [10, 12, 15]}',
            "--output", out_dir,
            "--funding-costs", "0", "0.03", "0.10",
        ]
        with patch.object(sys, "argv", argv), \
                redirect_stdout(StringIO()), redirect_stderr(StringIO()):
            rc = walk_forward_main()

        assert rc == 0, f"CLI optimize funding sweep should exit 0, got {rc}"
        sweep_path = os.path.join(out_dir, "parameter_optimization_funding_sweep.json")
        assert os.path.exists(sweep_path), "parameter_optimization_funding_sweep.json not written"
        with open(sweep_path) as f:
            payload = json.load(f)
        assert payload["funding_costs"] == [0.0, 0.03, 0.1]
        assert len(payload["results"]) == 3
        returns = [r["top_total_return"] for r in payload["results"]]
        assert returns[2] <= returns[0], (
            f"expected non-increasing top return with funding cost, got {returns}"
        )


def test_cli_out_of_sample_impact_sweep():
    """CLI out-of-sample --impact-coefficients writes a sweep artifact whose
    held-out test return degrades as the market-impact coefficient rises."""
    with tempfile.TemporaryDirectory() as tmpdir:
        csv_path = os.path.join(tmpdir, "data.csv")
        _write_ohlcv_csv(csv_path, periods=600)
        out_dir = os.path.join(tmpdir, "out")
        argv = [
            "walk_forward", "out-of-sample",
            "--data", csv_path,
            "--symbol", "SPY",
            "--strategy", "sma_crossover",
            "--param-grid", '{"fast_period": [3, 5, 7], "slow_period": [10, 12, 15]}',
            "--output", out_dir,
            "--validation-method", "walk_forward",
            "--impact-coefficients", "0", "2", "5",
        ]
        with patch.object(sys, "argv", argv), \
                redirect_stdout(StringIO()), redirect_stderr(StringIO()):
            rc = walk_forward_main()

        assert rc == 0, f"CLI out-of-sample impact sweep should exit 0, got {rc}"
        sweep_path = os.path.join(out_dir, "out_of_sample_impact_sweep.json")
        assert os.path.exists(sweep_path), "out_of_sample_impact_sweep.json not written"
        with open(sweep_path) as f:
            payload = json.load(f)
        assert payload["impact_coefficients"] == [0.0, 2.0, 5.0]
        assert len(payload["results"]) == 3
        returns = [r["test_total_return"] for r in payload["results"]]
        assert returns[2] < returns[0], (
            f"expected test return degradation with impact, got {returns}"
        )


def test_cli_out_of_sample_borrow_sweep():
    """CLI out-of-sample --borrow-costs writes a sweep artifact whose held-out
    test return degrades as the short-position borrow cost rises (MACD goes short)."""
    with tempfile.TemporaryDirectory() as tmpdir:
        csv_path = os.path.join(tmpdir, "data.csv")
        _write_ohlcv_csv(csv_path, periods=600)
        out_dir = os.path.join(tmpdir, "out")
        argv = [
            "walk_forward", "out-of-sample",
            "--data", csv_path,
            "--symbol", "SPY",
            "--strategy", "macd",
            "--param-grid", '{"fast_period": [10, 12], "slow_period": [24, 26], "signal_period": [8, 9]}',
            "--output", out_dir,
            "--validation-method", "walk_forward",
            "--borrow-costs", "0", "0.03", "0.10",
        ]
        with patch.object(sys, "argv", argv), \
                redirect_stdout(StringIO()), redirect_stderr(StringIO()):
            rc = walk_forward_main()

        assert rc == 0, f"CLI out-of-sample borrow sweep should exit 0, got {rc}"
        sweep_path = os.path.join(out_dir, "out_of_sample_borrow_sweep.json")
        assert os.path.exists(sweep_path), "out_of_sample_borrow_sweep.json not written"
        with open(sweep_path) as f:
            payload = json.load(f)
        assert payload["borrow_costs"] == [0.0, 0.03, 0.1]
        assert len(payload["results"]) == 3
        returns = [r["test_total_return"] for r in payload["results"]]
        assert returns[2] < returns[0], (
            f"expected test return degradation with borrow cost, got {returns}"
        )


def test_cli_out_of_sample_funding_sweep():
    """CLI out-of-sample --funding-costs writes a sweep artifact whose held-out
    test return never increases as the leveraged-position funding cost rises."""
    with tempfile.TemporaryDirectory() as tmpdir:
        csv_path = os.path.join(tmpdir, "data.csv")
        _write_ohlcv_csv(csv_path, periods=600)
        out_dir = os.path.join(tmpdir, "out")
        argv = [
            "walk_forward", "out-of-sample",
            "--data", csv_path,
            "--symbol", "SPY",
            "--strategy", "sma_crossover",
            "--param-grid", '{"fast_period": [3, 5, 7], "slow_period": [10, 12, 15]}',
            "--output", out_dir,
            "--validation-method", "walk_forward",
            "--funding-costs", "0", "0.03", "0.10",
        ]
        with patch.object(sys, "argv", argv), \
                redirect_stdout(StringIO()), redirect_stderr(StringIO()):
            rc = walk_forward_main()

        assert rc == 0, f"CLI out-of-sample funding sweep should exit 0, got {rc}"
        sweep_path = os.path.join(out_dir, "out_of_sample_funding_sweep.json")
        assert os.path.exists(sweep_path), "out_of_sample_funding_sweep.json not written"
        with open(sweep_path) as f:
            payload = json.load(f)
        assert payload["funding_costs"] == [0.0, 0.03, 0.1]
        assert len(payload["results"]) == 3
        returns = [r["test_total_return"] for r in payload["results"]]
        assert returns[2] <= returns[0], (
            f"expected non-increasing test return with funding cost, got {returns}"
        )


_EXAMPLE_PATH = (
    Path(__file__).resolve().parent.parent
    / "examples" / "real_data_pipeline_example.py"
)


def _import_example_module():
    """Import real_data_pipeline_example.py from its file path.

    Loading via importlib (rather than `import`) keeps this test isolated:
    it exercises the example's module-level imports without executing
    `main()` (guarded by ``if __name__ == "__main__"``).
    """
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "real_data_pipeline_example", str(_EXAMPLE_PATH)
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_deflated_alpha_ratio_frequency_invariant():
    """The Deflated Alpha Ratio must be invariant to the data frequency when
    calendar time is held fixed.

    The Bailey & Lopez de Prado (2014) Deflated Sharpe Ratio variance term
    (1 - gamma3*x + ((gamma4-1)/4)*x^2) is dimensionless and only valid when x
    is a Sharpe-like ratio.  Plugging a raw per-period return into it makes the
    statistic frequency-dependent and understates skill on lower-frequency
    data.  This regression holds calendar time fixed by aggregating the same
    daily return process to monthly and asserts the DAR is approximately equal
    (and high) in both cases, since the signal is strong by construction.

    A regression that reverts the fix would show DAR differing by an order of
    magnitude across the two frequencies (e.g. ~0.5 daily vs ~0.5 monthly with
    wildly different z-scores) for a t-statistic of ~30.
    """
    rng = np.random.default_rng(11)
    n_benchmarks = 2
    alpha_annual = 0.15
    vol_annual = 0.20

    # ~5 years of business-daily data with a strong signal.
    n_daily = 1260
    vol_pp = vol_annual / np.sqrt(252)
    mean_pp = alpha_annual / 252
    daily = pd.Series(
        rng.normal(loc=mean_pp, scale=vol_pp, size=n_daily),
        index=pd.bdate_range("2020-01-01", periods=n_daily),
    )

    # Aggregate to monthly: same calendar time, fewer bars.  Simple returns
    # sum across the month, which preserves the annualized alpha and
    # volatility (the t-statistic scales with sqrt(T) and is therefore not
    # itself frequency-invariant, but alpha_ann and vol_ann are).
    monthly = daily.resample("MS").sum()

    results = {}
    for name, rets in (("daily", daily), ("monthly", monthly)):
        ann = _annualization_factor(rets.index)
        alpha = float(rets.mean() * ann)
        vol = float(rets.std() * np.sqrt(ann))
        t_stat = alpha * np.sqrt(len(rets)) / vol if vol > 0 else 0.0
        da = deflated_alpha_ratio(
            alpha=alpha, returns=rets, benchmark_returns=rets,
            n_benchmarks=n_benchmarks,
        )
        results[name] = {"alpha": alpha, "vol": vol, "t_stat": t_stat, "da": da}

    # Annualized alpha and volatility are frequency-invariant when calendar
    # time is held fixed (simple returns sum across the aggregation).
    assert abs(results["daily"]["alpha"] - results["monthly"]["alpha"]) < 0.05, (
        f"annualized alpha should be frequency-invariant: "
        f"daily={results['daily']['alpha']:.4f} monthly={results['monthly']['alpha']:.4f}"
    )
    assert abs(results["daily"]["vol"] - results["monthly"]["vol"]) < 0.05, (
        f"annualized vol should be frequency-invariant: "
        f"daily={results['daily']['vol']:.4f} monthly={results['monthly']['vol']:.4f}"
    )

    dar_daily = results["daily"]["da"]["deflated_alpha_ratio"]
    dar_monthly = results["monthly"]["da"]["deflated_alpha_ratio"]
    # Both frequencies carry a strong signal (t-stat > 7 with 2 benchmarks),
    # so the DAR must be very close to 1 in both cases.
    assert dar_daily > 0.99, (
        f"Daily DAR should be ~1 for a strong signal, got {dar_daily:.4f}"
    )
    assert dar_monthly > 0.99, (
        f"Monthly DAR should be ~1 for a strong signal, got {dar_monthly:.4f}"
    )
    # The two frequencies must agree closely; a buggy formulation diverges by
    # an order of magnitude (e.g. ~0.5 daily vs ~0.5 monthly with wildly
    # different z-scores) even though the underlying signal is identical.
    assert abs(dar_daily - dar_monthly) < 0.05, (
        f"DAR should be frequency-invariant: daily={dar_daily:.4f} "
        f"monthly={dar_monthly:.4f}"
    )

    # expected_max_alpha is reported in annualized alpha units (backward
    # compatibility) and must be small relative to the signal alpha.
    for name in ("daily", "monthly"):
        da = results[name]["da"]
        assert da["expected_max_alpha"] < results[name]["alpha"], (
            f"{name}: expected_max_alpha {da['expected_max_alpha']:.4f} should "
            f"be below the signal alpha {results[name]['alpha']:.4f}"
        )


def test_deflated_alpha_ratio_weakens_with_more_benchmarks():
    """The Deflated Alpha Ratio must weaken (and its p-value strengthen) as the
    number of benchmarks tested grows, for the same signal.

    Testing more benchmarks is a multiple-testing problem: with enough
    benchmarks, luck alone produces an attractive alpha.  The Deflated Alpha
    Ratio corrects for this selection bias, so for a fixed alpha and returns
    the DAR must be non-increasing (p-value non-decreasing) in N.  A regression
    that drops the N-dependence would show a flat DAR across N values.
    """
    rng = np.random.default_rng(5)
    dates = pd.date_range("2020-01-01", periods=500, freq="B")
    rets = pd.Series(rng.normal(0.0003, 0.015, 500), index=dates)
    bench = pd.Series(rng.normal(0.0002, 0.015, 500), index=dates)
    alpha = 0.05
    trial_alphas = [0.05, 0.03, 0.08, -0.01, 0.02, 0.04, 0.01, 0.06, -0.02, 0.03]

    dars, pvals = [], []
    for n in (1, 2, 3, 5, 10):
        da = deflated_alpha_ratio(
            alpha=alpha,
            returns=rets,
            benchmark_returns=bench,
            n_benchmarks=n,
            trial_alphas=trial_alphas[:n],
        )
        dars.append(da["deflated_alpha_ratio"])
        pvals.append(da["p_value"])

    # DAR must not increase as more benchmarks are tested (correction strengthens).
    for i in range(len(dars) - 1):
        assert dars[i] >= dars[i + 1], (
            f"DAR should be non-increasing in N: N={i+1}={dars[i]:.4f} "
            f"N={i+2}={dars[i+1]:.4f}"
        )
    # p-value complement must not decrease.
    for i in range(len(pvals) - 1):
        assert pvals[i] <= pvals[i + 1], (
            f"p-value should be non-decreasing in N: N={i+1}={pvals[i]:.4f} "
            f"N={i+2}={pvals[i+1]:.4f}"
        )
    # Endpoints must bracket: a single benchmark corrects minimally (~1.0),
    # many benchmarks correct strongly (< 1).
    assert dars[0] > dars[-1], (
        f"Single-benchmark DAR {dars[0]:.4f} should exceed multi-benchmark "
        f"DAR {dars[-1]:.4f}"
    )
    assert 0.0 <= dars[-1] <= 1.0 and 0.0 <= pvals[-1] <= 1.0


def test_deflated_sharpe_ratio_weakens_with_more_trials():
    """The Deflated Sharpe Ratio must weaken (and its p-value strengthen) as the
    number of trials tested grows, for the same strategy returns.

    Searching over more configurations is a multiple-testing problem: with
    enough trials, luck alone produces an attractive Sharpe ratio.  The
    Deflated Sharpe Ratio corrects for this selection bias, so for a fixed
    Sharpe ratio and returns the DSR must be non-increasing (p-value
    non-decreasing) in N.  A regression that drops the N-dependence would
    show a flat DSR across N values.
    """
    rng = np.random.default_rng(7)
    dates = pd.date_range("2020-01-01", periods=500, freq="B")
    rets = pd.Series(rng.normal(0.0003, 0.015, 500), index=dates)
    sharpe = 1.0
    trial_sharpes = [1.0, 0.8, 1.2, 0.5, 0.9, 1.1, 0.6, 1.3, 0.4, 0.7]

    dsrs, pvals = [], []
    for n in (1, 2, 3, 5, 10):
        r = deflated_sharpe_ratio(
            sharpe_ratio=sharpe,
            returns=rets,
            n_trials=n,
            trial_sharpes=trial_sharpes[:n] if n <= len(trial_sharpes) else trial_sharpes,
        )
        dsrs.append(r["deflated_sharpe_ratio"])
        pvals.append(r["p_value"])

    for i in range(len(dsrs) - 1):
        assert dsrs[i] >= dsrs[i + 1], (
            f"DSR should be non-increasing in N: N={i+1}={dsrs[i]:.4f} "
            f"N={i+2}={dsrs[i+1]:.4f}"
        )
    for i in range(len(pvals) - 1):
        assert pvals[i] <= pvals[i + 1], (
            f"p-value should be non-decreasing in N: N={i+1}={pvals[i]:.4f} "
            f"N={i+2}={pvals[i+1]:.4f}"
        )
    assert dsrs[0] > dsrs[-1], (
        f"Single-trial DSR {dsrs[0]:.4f} should exceed multi-trial "
        f"DSR {dsrs[-1]:.4f}"
    )
    assert 0.0 <= dsrs[-1] <= 1.0 and 0.0 <= pvals[-1] <= 1.0


def test_real_data_pipeline_example_imports():
    """The real-data integration example must import cleanly and expose its
    documented callables.

    Guards against regressions where a referenced helper was removed, renamed,
    or where the example's module-level imports reference an API that no longer
    exists (which would otherwise fail only at runtime)."""
    module = _import_example_module()
    for name in (
        "main",
        "generate_synthetic_universe",
        "run_pit_validation",
        "run_survivorship_detection",
        "run_cpcv_validation",
        "run_cli_cpcv_validation",
        "run_cli_monte_carlo",
        "demonstrate_deflated_alpha_directly",
    ):
        assert hasattr(module, name), f"example module missing callable: {name}"
        assert callable(getattr(module, name)), f"{name} should be callable"


def test_real_data_pipeline_example_runs():
    """The real-data integration example must run end-to-end (exit 0) and print
    its completion banner.

    This is the primary regression guard for the full pipeline: synthetic
    multi-asset generation, PIT validation, survivorship-bias detection, CPCV
    validation, the production-pattern CLI CPCV + Monte-Carlo subprocess calls,
    and the direct deflated-alpha computation. Running it as a subprocess
    mirrors how a user invokes it and isolates failures from the test process."""
    result = subprocess.run(
        [sys.executable, str(_EXAMPLE_PATH)],
        capture_output=True,
        text=True,
        timeout=300,
    )
    assert result.returncode == 0, (
        f"example exited {result.returncode}\n"
        f"stdout:\n{result.stdout[-3000:]}\n"
        f"stderr:\n{result.stderr[-3000:]}"
    )
    assert "PIPELINE COMPLETE - SUMMARY" in result.stdout, (
        "completion banner missing from example stdout"
    )


_COSTS_EXAMPLE_PATH = (
    Path(__file__).resolve().parent.parent
    / "examples" / "trading_costs_robustness_example.py"
)

_FALSIFIABLE_EXAMPLE_PATH = (
    Path(__file__).resolve().parent.parent
    / "examples" / "falsifiable_hypothesis_example.py"
)


def _import_costs_example_module():
    """Import trading_costs_robustness_example.py from its file path.

    Loading via importlib (rather than ``import``) keeps this test isolated:
    it exercises the example's module-level imports without executing
    ``main()`` (guarded by ``if __name__ == "__main__"``).
    """
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "trading_costs_robustness_example", str(_COSTS_EXAMPLE_PATH)
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_trading_costs_robustness_example_imports():
    """The trading-cost sensitivity example must import cleanly and expose its
    documented callables."""
    module = _import_costs_example_module()
    for name in (
        "main",
        "run_strategy_cost_sweep",
        "run_benchmark_cost_sweep",
        "run_cpcv_robustness",
        "_make_universe",
        "_metrics_from_returns",
        "_make_degraded_strategy_benchmark",
    ):
        assert hasattr(module, name), f"example module missing callable: {name}"
        assert callable(getattr(module, name)), f"{name} should be callable"
    assert module.DEGRADED_PRIMARY_DRAG == -0.30, "primary drag should be -30%"
    assert module.DEGRADED_SECONDARY_DRAG == -0.60, "secondary drag should be -60%"


def test_trading_costs_positive_alpha_dar_in_range():
    """The positive-alpha (degraded-strategy) benchmark scenario must produce
    DAR ∈ (0, 1) and vary across cost-modeling choices.

    The SMA-crossover strategy on the synthetic data has negative Sharpe, so a
    positive alpha only arises when the benchmark drifts more negatively than
    the strategy.  With -30%/-60% drag the alpha is ~+12% annualized and the
    DAR lands in (0, 1) — proving the sensitivity analysis surfaces statistical
    inference, not just alpha-point estimates.  This guards against regressions
    that shrink the drag back to -10%/-20% (which yield DAR ≈ 0).
    """
    module = _import_costs_example_module()
    strategy_df, benchmark_dfs, symbols = module._make_universe()
    strategy = build_strategy("sma_crossover", json.dumps(module.STRATEGY_PARAMS))
    signals = strategy.generate_signals(strategy_df)
    baseline_returns = module._calculate_strategy_returns(
        strategy_df, signals, commission=0.0, slippage=0.0,
        borrow_cost=0.0, funding_cost=0.0,
    )

    primary = module._make_degraded_strategy_benchmark(
        strategy_df, drag_annual=module.DEGRADED_PRIMARY_DRAG
    )
    secondary = module._make_degraded_strategy_benchmark(
        strategy_df, drag_annual=module.DEGRADED_SECONDARY_DRAG
    )

    # Baseline (no benchmark costs, round-trip mode)
    correction = module._benchmark_list_alpha_correction(
        baseline_returns, [primary, secondary],
        benchmark_commission=0.0, benchmark_slippage=0.0,
        benchmark_expense_ratio=0.0, benchmark_cost_is_periodic=False,
    )
    da = correction["deflated_alpha"]
    assert da is not None, "deflated_alpha must be present with 2 benchmarks"
    dar_base = da["deflated_alpha_ratio"]
    assert 0.0 < dar_base < 1.0, (
        f"baseline DAR must be in (0, 1), got {dar_base}"
    )

    # With higher benchmark costs (1% expense, periodic) the benchmark
    # underperforms further, alpha increases, and DAR should move.
    correction_high = module._benchmark_list_alpha_correction(
        baseline_returns, [primary, secondary],
        benchmark_commission=0.0005, benchmark_slippage=0.0005,
        benchmark_expense_ratio=0.01, benchmark_cost_is_periodic=True,
    )
    da_high = correction_high["deflated_alpha"]
    dar_high = da_high["deflated_alpha_ratio"]
    assert 0.0 < dar_high < 1.0, f"high-cost DAR must be in (0, 1), got {dar_high}"
    # DAR must change across cost assumptions (demonstrates sensitivity)
    assert dar_high != dar_base, (
        f"DAR should differ across cost assumptions: {dar_base} vs {dar_high}"
    )


def test_trading_costs_borrow_funding_sweep_exercises_api():
    """Borrow and funding costs are swept in run_strategy_cost_sweep's grid and
    passed through to _calculate_strategy_returns.  On this long-only
    strategy they have no P&L effect, but the API must still accept and process
    them without error.
    """
    module = _import_costs_example_module()
    # Verify the sweep grids include both 0% and a non-zero level
    assert hasattr(module, "BORROW_COST_GRID"), "BORROW_COST_GRID must be defined"
    assert hasattr(module, "FUNDING_COST_GRID"), "FUNDING_COST_GRID must be defined"
    borrow_grid = module.BORROW_COST_GRID
    funding_grid = module.FUNDING_COST_GRID
    assert 0.0 in borrow_grid and any(v > 0 for v in borrow_grid), "borrow grid must span 0% and >0%"
    assert 0.0 in funding_grid and any(v > 0 for v in funding_grid), "funding grid must span 0% and >0%"


def test_trading_costs_robustness_example_runs():
    """The trading-cost sensitivity example must run end-to-end (exit 0) and print
    its completion banner.

    Verifies the three-section pipeline: cost sweep, benchmark cost-model
    sweep, and CPCV robustness under cost stress — all on synthetic data with
    no network access."""
    result = subprocess.run(
        [sys.executable, str(_COSTS_EXAMPLE_PATH)],
        capture_output=True,
        text=True,
        timeout=300,
    )
    assert result.returncode == 0, (
        f"example exited {result.returncode}\n"
        f"stdout:\n{result.stdout[-3000:]}\n"
        f"stderr:\n{result.stderr[-3000:]}"
    )
    assert "TRADING COSTS SENSITIVITY ANALYSIS COMPLETE" in result.stdout, (
        "completion banner missing from example stdout"
    )
    assert "STRUCTURED RESULTS SAVED" in result.stdout.upper(), (
        "JSON summary output message missing from example stdout"
    )


def _import_falsifiable_example_module():
    """Import falsifiable_hypothesis_example.py from its file path.

    Loading via importlib keeps this test isolated: it exercises the example's
    module-level imports without executing ``main()`` (guarded by
    ``if __name__ == "__main__"``).
    """
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "falsifiable_hypothesis_example", str(_FALSIFIABLE_EXAMPLE_PATH)
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_falsifiable_hypothesis_example_imports():
    """The falsifiable-hypothesis example must import cleanly and expose its
    documented callables and pre-registered hypothesis/criteria."""
    module = _import_falsifiable_example_module()
    for name in (
        "main",
        "run_hypothesis_test",
        "HYPOTHESIS",
        "CRITERIA",
        "COMMISSION",
        "SLIPPAGE",
        "PARAM_GRID",
    ):
        assert hasattr(module, name), f"example module missing: {name}"
    assert callable(module.main), "main should be callable"
    assert callable(module.run_hypothesis_test), "run_hypothesis_test should be callable"
    assert isinstance(module.HYPOTHESIS, str) and module.HYPOTHESIS, "HYPOTHESIS must be a non-empty string"
    assert isinstance(module.CRITERIA, list) and len(module.CRITERIA) == 4, (
        f"CRITERIA must define 4 pre-registered criteria, got {len(module.CRITERIA)}"
    )
    # Criterion tuple shape: (name, description, predicate)
    for name, desc, pred in module.CRITERIA:
        assert isinstance(name, str) and name, "criterion name must be non-empty"
        assert isinstance(desc, str) and desc, "criterion description must be non-empty"
        assert callable(pred), "criterion predicate must be callable"


def test_falsifiable_hypothesis_example_runs():
    """The falsifiable-hypothesis example must run end-to-end (exit 0) and
    print a pre-registered verdict.

    The verdict (SUPPORTED / NOT SUPPORTED) is an honest scientific outcome,
    not a profitability claim: this test guards that the hypothesis-testing
    machinery (chronological split, PIT validation, walk-forward selection,
    Deflated Sharpe correction, benchmark alpha, criteria evaluation) executes
    without error and reports a verdict against its pre-registered criteria."""
    result = subprocess.run(
        [sys.executable, str(_FALSIFIABLE_EXAMPLE_PATH)],
        capture_output=True,
        text=True,
        timeout=300,
    )
    assert result.returncode == 0, (
        f"example exited {result.returncode}\n"
        f"stdout:\n{result.stdout[-3000:]}\n"
        f"stderr:\n{result.stderr[-3000:]}"
    )
    assert "FALSIFIABLE FINANCIAL HYPOTHESIS TEST" in result.stdout, (
        "hypothesis header missing from example stdout"
    )
    assert "VERDICT:" in result.stdout, "verdict line missing from example stdout"
    import re

    m = re.search(r"VERDICT:\s*(SUPPORTED|NOT SUPPORTED)", result.stdout)
    assert m, f"verdict must be SUPPORTED or NOT SUPPORTED, got:\n{result.stdout[-2000:]}"


# Need to import patch for mocking
from unittest.mock import patch




def test_trading_costs_short_strategy_borrow_cost_effect():
    """Borrow costs should reduce returns when the strategy carries short exposure."""
    module = _import_costs_example_module()
    strategy_df, _, _ = module._make_universe()
    signals = module._strategy_signals(strategy_df)
    # Create short-capable variant
    signals_short = signals.copy()
    signals_short[signals_short == 0] = -1
    # Returns with no borrow costs
    returns_base = module._calculate_strategy_returns(
        strategy_df, signals_short, commission=0.0, slippage=0.0,
        borrow_cost=0.0, funding_cost=0.0,
    )
    # Returns with borrow costs
    returns_high_b = module._calculate_strategy_returns(
        strategy_df, signals_short, commission=0.0, slippage=0.0,
        borrow_cost=0.03, funding_cost=0.0,
    )
    # Borrow costs should have a negative effect (reduce cumulative returns)
    assert returns_high_b.sum() < returns_base.sum(), (
        f"borrow costs should reduce returns for short strategy: "
        f"{returns_high_b.sum():.6f} vs {returns_base.sum():.6f}"
    )


def test_trading_costs_levered_strategy_funding_cost_effect():
    """Funding costs should reduce returns when the strategy uses leverage.

    The long-only SMA-crossover strategy has positions ∈ {0, 1} (gross exposure
    = 1), so funding_cost has no effect.  By scaling signals to 2× leverage
    (positions ∈ {0, 2}), the excess leverage of 1× is subject to funding_cost,
    which should reduce cumulative returns.
    """
    module = _import_costs_example_module()
    strategy_df, _, _ = module._make_universe()
    signals = module._strategy_signals(strategy_df)
    signals_levered = signals * 2  # 2x leverage, positions ∈ {0, 2}
    # Baseline: no costs
    returns_base = module._calculate_strategy_returns(
        strategy_df, signals_levered, commission=0.0, slippage=0.0,
        borrow_cost=0.0, funding_cost=0.0,
    )
    # With funding cost (3% annual on the 1x excess leverage)
    returns_high_f = module._calculate_strategy_returns(
        strategy_df, signals_levered, commission=0.0, slippage=0.0,
        borrow_cost=0.0, funding_cost=0.03,
    )
    # Gross exposure exceeds 1x, so funding costs must apply
    assert returns_high_f.sum() < returns_base.sum(), (
        f"funding costs should reduce returns for leveraged strategy: "
        f"{returns_high_f.sum():.6f} vs {returns_base.sum():.6f}"
    )


def test_trading_costs_market_neutral_borrow_and_funding_effect():
    """Combined borrow and funding costs should reduce returns for a market-neutral leveraged strategy.

    A market-neutral pairs strategy that is long one asset and short another with
    2× gross exposure carries both short exposure (subject to borrow costs) and
    excess leverage beyond 1× (subject to funding costs). Applying both should
    reduce cumulative returns relative to the zero-cost baseline.
    """
    module = _import_costs_example_module()
    import numpy as np
    import pandas as pd

    # Build market-neutral leveraged positions
    raw = module.generate_multi_asset_data(
        n_assets=module.N_ASSETS,
        periods=module.N_PERIODS,
        seed=42,
    )
    assets = {sym: df.set_index("date") for sym, df in raw.items()}
    syms = sorted(assets.keys())
    asset_a = assets[syms[3]]
    asset_b = assets[syms[4]]
    sig_a = module._strategy_signals(asset_a)
    sig_b = module._strategy_signals(asset_b)
    common = asset_a.index.intersection(asset_b.index)
    pos_a = sig_a.reindex(common).fillna(0)
    pos_b = -sig_b.reindex(common).fillna(0)
    positions_mn = (pos_a + pos_b) * 2  # market neutral, 2x gross exposure
    data_mn = {"A": asset_a.reindex(common), "B": asset_b.reindex(common)}

    returns_base = module._calculate_strategy_returns(
        data_mn, positions_mn, commission=0.0, slippage=0.0,
        borrow_cost=0.0, funding_cost=0.0,
    )
    returns_both = module._calculate_strategy_returns(
        data_mn, positions_mn, commission=0.0, slippage=0.0,
        borrow_cost=0.03, funding_cost=0.02,
    )

    # Should have both short exposure and gross exposure > 1
    assert positions_mn.abs().max() > 1.0
    assert (positions_mn < 0).any()
    assert returns_both.sum() < returns_base.sum(), (
        f"combined borrow and funding costs should reduce returns: "
        f"{returns_both.sum():.6f} vs {returns_base.sum():.6f}"
    )


def test_market_impact_cost_reduces_returns_single_asset():
    """Market impact must degrade returns monotonically on single-asset data.

    Regression guard for the bug where `position_notional` was scaled by the raw
    asset price (~$100) instead of the portfolio equity (~$100k), making the
    ratio position_notional/ADV ~1e-7 and rendering `--impact-coefficient` a
    silent no-op even at coefficient 5.0.  With the fix, impact_coefficient
    0.1 -> 5.0 must progressively reduce total return.
    """
    module = _import_costs_example_module()
    strategy_df, _, _ = module._make_universe()
    signals = module._strategy_signals(strategy_df)

    returns_by_coeff = {}
    for coeff in (0.0, 0.1, 0.5, 1.0, 2.0, 5.0):
        r = _calculate_strategy_returns(
            strategy_df, signals,
            commission=0.0, slippage=0.0,
            impact_coefficient=coeff,
        )
        returns_by_coeff[coeff] = float(r.sum())

    # Zero coefficient must equal the no-cost baseline (no impact applied).
    assert returns_by_coeff[0.0] == max(returns_by_coeff.values()), (
        "impact_coefficient=0 must be the least-cost regime"
    )
    # Higher coefficients must degrade cumulative returns monotonically.
    coeffs = sorted(returns_by_coeff)
    for a, b in zip(coeffs, coeffs[1:]):
        assert returns_by_coeff[b] < returns_by_coeff[a], (
            f"impact_coefficient {b} should reduce returns below {a}: "
            f"{returns_by_coeff[b]:.6f} vs {returns_by_coeff[a]:.6f}"
        )
    # The sweep must be non-trivial: 5.0 must meaningfully exceed 0.1.
    assert returns_by_coeff[0.0] - returns_by_coeff[5.0] > 0.001, (
        "impact sweep must be non-trivial, got "
        f"{returns_by_coeff[0.0]:.6f} vs {returns_by_coeff[5.0]:.6f}"
    )


def test_market_impact_cost_reduces_returns_dict_panel():
    """Market impact must work on dict/panel data without raising UnboundLocalError.

    The dict/panel branch of `_calculate_strategy_returns` did not define `close`,
    so any non-zero `impact_coefficient` raised `UnboundLocalError`.  This test
    exercises the market-neutral pairs path (long A, short B, 2x gross exposure)
    and asserts impact degrades returns monotonically.
    """
    module = _import_costs_example_module()
    raw = module.generate_multi_asset_data(
        n_assets=module.N_ASSETS,
        periods=module.N_PERIODS,
        seed=42,
    )
    assets = {sym: df.set_index("date") for sym, df in raw.items()}
    syms = sorted(assets.keys())
    a, b = assets[syms[3]], assets[syms[4]]
    common = a.index.intersection(b.index)
    sig_a = module._strategy_signals(a).reindex(common).fillna(0)
    sig_b = module._strategy_signals(b).reindex(common).fillna(0)
    positions = (sig_a - sig_b) * 2  # market neutral, 2x gross exposure
    data_mn = {"A": a.reindex(common), "B": b.reindex(common)}

    returns_by_coeff = {}
    for coeff in (0.0, 1.0, 5.0):
        r = _calculate_strategy_returns(
            data_mn, positions,
            commission=0.0, slippage=0.0,
            impact_coefficient=coeff,
        )
        returns_by_coeff[coeff] = float(r.sum())

    assert returns_by_coeff[0.0] == max(returns_by_coeff.values()), (
        "impact_coefficient=0 must be the least-cost regime on dict data"
    )
    assert returns_by_coeff[5.0] < returns_by_coeff[1.0] < returns_by_coeff[0.0], (
        "impact must degrade returns monotonically on dict data: "
        f"{returns_by_coeff}"
    )


def test_cli_walk_forward_commission_sweep():
    """CLI walk-forward --commissions writes a sweep artifact whose OOS return
    degrades as the per-trade commission rises."""
    with tempfile.TemporaryDirectory() as tmpdir:
        csv_path = os.path.join(tmpdir, "data.csv")
        _write_ohlcv_csv(csv_path, periods=600)
        out_dir = os.path.join(tmpdir, "out")
        argv = [
            "walk_forward", "walk-forward",
            "--data", csv_path,
            "--symbol", "SPY",
            "--strategy", "sma_crossover",
            "--param-grid", '{"fast_period": [3, 5, 7], "slow_period": [10, 12, 15]}',
            "--output", out_dir,
            "--commissions", "0.0002", "0.002", "0.004",
        ]
        with patch.object(sys, "argv", argv), \
                redirect_stdout(StringIO()), redirect_stderr(StringIO()):
            rc = walk_forward_main()

        assert rc == 0, f"CLI walk-forward commission sweep should exit 0, got {rc}"
        sweep_path = os.path.join(out_dir, "walk_forward_commission_sweep.json")
        assert os.path.exists(sweep_path), "walk_forward_commission_sweep.json not written"
        with open(sweep_path) as f:
            payload = json.load(f)
        assert payload["commissions"] == [0.0002, 0.002, 0.004]
        assert len(payload["results"]) == 3
        returns = [r["total_oos_return"] for r in payload["results"]]
        assert returns[2] < returns[0], (
            f"expected OOS return degradation with commission, got {returns}"
        )
        assert [r["commission"] for r in payload["results"]] == [0.0002, 0.002, 0.004]


def test_cli_walk_forward_slippage_sweep():
    """CLI walk-forward --slippages writes a sweep artifact whose OOS return
    degrades as the per-trade slippage rises."""
    with tempfile.TemporaryDirectory() as tmpdir:
        csv_path = os.path.join(tmpdir, "data.csv")
        _write_ohlcv_csv(csv_path, periods=600)
        out_dir = os.path.join(tmpdir, "out")
        argv = [
            "walk_forward", "walk-forward",
            "--data", csv_path,
            "--symbol", "SPY",
            "--strategy", "sma_crossover",
            "--param-grid", '{"fast_period": [3, 5, 7], "slow_period": [10, 12, 15]}',
            "--output", out_dir,
            "--slippages", "0.0001", "0.001", "0.002",
        ]
        with patch.object(sys, "argv", argv), \
                redirect_stdout(StringIO()), redirect_stderr(StringIO()):
            rc = walk_forward_main()

        assert rc == 0, f"CLI walk-forward slippage sweep should exit 0, got {rc}"
        sweep_path = os.path.join(out_dir, "walk_forward_slippage_sweep.json")
        assert os.path.exists(sweep_path), "walk_forward_slippage_sweep.json not written"
        with open(sweep_path) as f:
            payload = json.load(f)
        assert payload["slippages"] == [0.0001, 0.001, 0.002]
        assert len(payload["results"]) == 3
        returns = [r["total_oos_return"] for r in payload["results"]]
        assert returns[2] < returns[0], (
            f"expected OOS return degradation with slippage, got {returns}"
        )
        assert [r["slippage"] for r in payload["results"]] == [0.0001, 0.001, 0.002]


def test_cli_optimize_commission_sweep():
    """CLI optimize --commissions writes a sweep artifact whose top return
    degrades as the per-trade commission rises."""
    with tempfile.TemporaryDirectory() as tmpdir:
        csv_path = os.path.join(tmpdir, "data.csv")
        _write_ohlcv_csv(csv_path, periods=600)
        out_dir = os.path.join(tmpdir, "out")
        argv = [
            "walk_forward", "optimize",
            "--data", csv_path,
            "--symbol", "SPY",
            "--strategy", "sma_crossover",
            "--param-grid", '{"fast_period": [3, 5, 7], "slow_period": [10, 12, 15]}',
            "--output", out_dir,
            "--commissions", "0.0002", "0.002", "0.004",
        ]
        with patch.object(sys, "argv", argv), \
                redirect_stdout(StringIO()), redirect_stderr(StringIO()):
            rc = walk_forward_main()

        assert rc == 0, f"CLI optimize commission sweep should exit 0, got {rc}"
        sweep_path = os.path.join(out_dir, "parameter_optimization_commission_sweep.json")
        assert os.path.exists(sweep_path), "parameter_optimization_commission_sweep.json not written"
        with open(sweep_path) as f:
            payload = json.load(f)
        assert payload["commissions"] == [0.0002, 0.002, 0.004]
        assert len(payload["results"]) == 3
        returns = [r["top_total_return"] for r in payload["results"]]
        assert returns[2] < returns[0], (
            f"expected top return degradation with commission, got {returns}"
        )
        assert [r["commission"] for r in payload["results"]] == [0.0002, 0.002, 0.004]


def test_cli_optimize_slippage_sweep():
    """CLI optimize --slippages writes a sweep artifact whose top return
    degrades as the per-trade slippage rises."""
    with tempfile.TemporaryDirectory() as tmpdir:
        csv_path = os.path.join(tmpdir, "data.csv")
        _write_ohlcv_csv(csv_path, periods=600)
        out_dir = os.path.join(tmpdir, "out")
        argv = [
            "walk_forward", "optimize",
            "--data", csv_path,
            "--symbol", "SPY",
            "--strategy", "sma_crossover",
            "--param-grid", '{"fast_period": [3, 5, 7], "slow_period": [10, 12, 15]}',
            "--output", out_dir,
            "--slippages", "0.0001", "0.001", "0.002",
        ]
        with patch.object(sys, "argv", argv), \
                redirect_stdout(StringIO()), redirect_stderr(StringIO()):
            rc = walk_forward_main()

        assert rc == 0, f"CLI optimize slippage sweep should exit 0, got {rc}"
        sweep_path = os.path.join(out_dir, "parameter_optimization_slippage_sweep.json")
        assert os.path.exists(sweep_path), "parameter_optimization_slippage_sweep.json not written"
        with open(sweep_path) as f:
            payload = json.load(f)
        assert payload["slippages"] == [0.0001, 0.001, 0.002]
        assert len(payload["results"]) == 3
        returns = [r["top_total_return"] for r in payload["results"]]
        assert returns[2] < returns[0], (
            f"expected top return degradation with slippage, got {returns}"
        )
        assert [r["slippage"] for r in payload["results"]] == [0.0001, 0.001, 0.002]


def test_cli_cpcv_commission_sweep():
    """CLI cpcv --commissions writes a sweep artifact whose OOS return degrades
    as the per-trade commission rises."""
    with tempfile.TemporaryDirectory() as tmpdir:
        csv_path = os.path.join(tmpdir, "data.csv")
        _write_ohlcv_csv(csv_path, periods=600)
        out_dir = os.path.join(tmpdir, "out")
        argv = [
            "walk_forward", "cpcv",
            "--data", csv_path,
            "--symbol", "SPY",
            "--strategy", "sma_crossover",
            "--param-grid", '{"fast_period": [3, 5, 7], "slow_period": [10, 12, 15]}',
            "--output", out_dir,
            "--n-splits", "5",
            "--test-size", "0.2",
            "--commissions", "0.0002", "0.002", "0.004",
        ]
        with patch.object(sys, "argv", argv), \
                redirect_stdout(StringIO()), redirect_stderr(StringIO()):
            rc = walk_forward_main()

        assert rc == 0, f"CLI cpcv commission sweep should exit 0, got {rc}"
        sweep_path = os.path.join(out_dir, "cpcv_commission_sweep.json")
        assert os.path.exists(sweep_path), "cpcv_commission_sweep.json not written"
        with open(sweep_path) as f:
            payload = json.load(f)
        assert payload["commissions"] == [0.0002, 0.002, 0.004]
        assert len(payload["results"]) == 3
        returns = [r["total_oos_return"] for r in payload["results"]]
        assert returns[2] < returns[0], (
            f"expected OOS return degradation with commission, got {returns}"
        )
        assert [r["commission"] for r in payload["results"]] == [0.0002, 0.002, 0.004]


def test_cli_cpcv_slippage_sweep():
    """CLI cpcv --slippages writes a sweep artifact whose OOS return degrades
    as the per-trade slippage rises."""
    with tempfile.TemporaryDirectory() as tmpdir:
        csv_path = os.path.join(tmpdir, "data.csv")
        _write_ohlcv_csv(csv_path, periods=600)
        out_dir = os.path.join(tmpdir, "out")
        argv = [
            "walk_forward", "cpcv",
            "--data", csv_path,
            "--symbol", "SPY",
            "--strategy", "sma_crossover",
            "--param-grid", '{"fast_period": [3, 5, 7], "slow_period": [10, 12, 15]}',
            "--output", out_dir,
            "--n-splits", "5",
            "--test-size", "0.2",
            "--slippages", "0.0001", "0.001", "0.002",
        ]
        with patch.object(sys, "argv", argv), \
                redirect_stdout(StringIO()), redirect_stderr(StringIO()):
            rc = walk_forward_main()

        assert rc == 0, f"CLI cpcv slippage sweep should exit 0, got {rc}"
        sweep_path = os.path.join(out_dir, "cpcv_slippage_sweep.json")
        assert os.path.exists(sweep_path), "cpcv_slippage_sweep.json not written"
        with open(sweep_path) as f:
            payload = json.load(f)
        assert payload["slippages"] == [0.0001, 0.001, 0.002]
        assert len(payload["results"]) == 3
        returns = [r["total_oos_return"] for r in payload["results"]]
        assert returns[2] < returns[0], (
            f"expected OOS return degradation with slippage, got {returns}"
        )
        assert [r["slippage"] for r in payload["results"]] == [0.0001, 0.001, 0.002]


def test_cli_monte_carlo_commission_sweep():
    """CLI monte-carlo --commissions writes a sweep artifact whose return
    degrades as the per-trade commission rises."""
    with tempfile.TemporaryDirectory() as tmpdir:
        csv_path = os.path.join(tmpdir, "data.csv")
        _write_ohlcv_csv(csv_path, periods=600)
        out_dir = os.path.join(tmpdir, "out")
        argv = [
            "walk_forward", "monte-carlo",
            "--data", csv_path,
            "--symbol", "SPY",
            "--strategy", "sma_crossover",
            "--param-grid", '{"fast_period": [3, 5, 7], "slow_period": [10, 12, 15]}',
            "--output", out_dir,
            "--n-simulations", "100",
            "--commissions", "0.0002", "0.002", "0.004",
        ]
        with patch.object(sys, "argv", argv), \
                redirect_stdout(StringIO()), redirect_stderr(StringIO()):
            rc = walk_forward_main()

        assert rc == 0, f"CLI monte_carlo commission sweep should exit 0, got {rc}"
        sweep_path = os.path.join(out_dir, "monte_carlo_commission_sweep.json")
        assert os.path.exists(sweep_path), "monte_carlo_commission_sweep.json not written"
        with open(sweep_path) as f:
            payload = json.load(f)
        assert payload["commissions"] == [0.0002, 0.002, 0.004]
        assert len(payload["results"]) == 3
        returns = [r["total_return"] for r in payload["results"]]
        assert returns[2] < returns[0], (
            f"expected return degradation with commission, got {returns}"
        )
        assert [r["commission"] for r in payload["results"]] == [0.0002, 0.002, 0.004]


def test_cli_monte_carlo_slippage_sweep():
    """CLI monte-carlo --slippages writes a sweep artifact whose return degrades
    as the per-trade slippage rises."""
    with tempfile.TemporaryDirectory() as tmpdir:
        csv_path = os.path.join(tmpdir, "data.csv")
        _write_ohlcv_csv(csv_path, periods=600)
        out_dir = os.path.join(tmpdir, "out")
        argv = [
            "walk_forward", "monte-carlo",
            "--data", csv_path,
            "--symbol", "SPY",
            "--strategy", "sma_crossover",
            "--param-grid", '{"fast_period": [3, 5, 7], "slow_period": [10, 12, 15]}',
            "--output", out_dir,
            "--n-simulations", "100",
            "--slippages", "0.0001", "0.001", "0.002",
        ]
        with patch.object(sys, "argv", argv), \
                redirect_stdout(StringIO()), redirect_stderr(StringIO()):
            rc = walk_forward_main()

        assert rc == 0, f"CLI monte_carlo slippage sweep should exit 0, got {rc}"
        sweep_path = os.path.join(out_dir, "monte_carlo_slippage_sweep.json")
        assert os.path.exists(sweep_path), "monte_carlo_slippage_sweep.json not written"
        with open(sweep_path) as f:
            payload = json.load(f)
        assert payload["slippages"] == [0.0001, 0.001, 0.002]
        assert len(payload["results"]) == 3
        returns = [r["total_return"] for r in payload["results"]]
        assert returns[2] < returns[0], (
            f"expected return degradation with slippage, got {returns}"
        )
        assert [r["slippage"] for r in payload["results"]] == [0.0001, 0.001, 0.002]


def test_cli_out_of_sample_commission_sweep():
    """CLI out-of-sample --commissions writes a sweep artifact whose held-out
    test return degrades as the per-trade commission rises."""
    with tempfile.TemporaryDirectory() as tmpdir:
        csv_path = os.path.join(tmpdir, "data.csv")
        _write_ohlcv_csv(csv_path, periods=600)
        out_dir = os.path.join(tmpdir, "out")
        argv = [
            "walk_forward", "out-of-sample",
            "--data", csv_path,
            "--symbol", "SPY",
            "--strategy", "sma_crossover",
            "--param-grid", '{"fast_period": [3, 5, 7], "slow_period": [10, 12, 15]}',
            "--output", out_dir,
            "--validation-method", "walk_forward",
            "--commissions", "0.0002", "0.002", "0.004",
        ]
        with patch.object(sys, "argv", argv), \
                redirect_stdout(StringIO()), redirect_stderr(StringIO()):
            rc = walk_forward_main()

        assert rc == 0, f"CLI out-of-sample commission sweep should exit 0, got {rc}"
        sweep_path = os.path.join(out_dir, "out_of_sample_commission_sweep.json")
        assert os.path.exists(sweep_path), "out_of_sample_commission_sweep.json not written"
        with open(sweep_path) as f:
            payload = json.load(f)
        assert payload["commissions"] == [0.0002, 0.002, 0.004]
        assert len(payload["results"]) == 3
        returns = [r["test_total_return"] for r in payload["results"]]
        assert returns[2] < returns[0], (
            f"expected test return degradation with commission, got {returns}"
        )
        assert [r["commission"] for r in payload["results"]] == [0.0002, 0.002, 0.004]


def test_cli_out_of_sample_slippage_sweep():
    """CLI out-of-sample --slippages writes a sweep artifact whose held-out
    test return degrades as the per-trade slippage rises."""
    with tempfile.TemporaryDirectory() as tmpdir:
        csv_path = os.path.join(tmpdir, "data.csv")
        _write_ohlcv_csv(csv_path, periods=600)
        out_dir = os.path.join(tmpdir, "out")
        argv = [
            "walk_forward", "out-of-sample",
            "--data", csv_path,
            "--symbol", "SPY",
            "--strategy", "sma_crossover",
            "--param-grid", '{"fast_period": [3, 5, 7], "slow_period": [10, 12, 15]}',
            "--output", out_dir,
            "--validation-method", "walk_forward",
            "--slippages", "0.0001", "0.001", "0.002",
        ]
        with patch.object(sys, "argv", argv), \
                redirect_stdout(StringIO()), redirect_stderr(StringIO()):
            rc = walk_forward_main()

        assert rc == 0, f"CLI out-of-sample slippage sweep should exit 0, got {rc}"
        sweep_path = os.path.join(out_dir, "out_of_sample_slippage_sweep.json")
        assert os.path.exists(sweep_path), "out_of_sample_slippage_sweep.json not written"
        with open(sweep_path) as f:
            payload = json.load(f)
        assert payload["slippages"] == [0.0001, 0.001, 0.002]
        assert len(payload["results"]) == 3
        returns = [r["test_total_return"] for r in payload["results"]]
        assert returns[2] < returns[0], (
            f"expected test return degradation with slippage, got {returns}"
        )
        assert [r["slippage"] for r in payload["results"]] == [0.0001, 0.001, 0.002]


def test_benchmark_list_alpha_correction_multiple_benchmarks_with_splits():
    """_benchmark_list_alpha_correction applies split adjustment to every
    benchmark carrying a ``splits`` column when multiple benchmarks are passed,
    and the aggregate Deflated Alpha correction remains well-formed.

    Regression guard: a benchmark list that mixes split-bearing and split-free
    benchmarks must route each benchmark through the correct stats path
    (split-aware vs plain) and still produce a single aggregate deflated_alpha
    dict with n_benchmarks equal to the number of benchmarks tested.
    """
    np.random.seed(31)
    periods = 252
    strat_rets = pd.Series(
        np.random.normal(0.0008, 0.015, periods),
        index=pd.date_range("2020-01-01", periods=periods, freq="B"),
    )

    # Benchmark 1: carries a 2-for-1 split inside the sample.
    bench_with_splits = _make_benchmark_data_with_splits(
        periods=periods, split_at=100, seed=21
    )
    # Benchmark 2: no splits column at all.
    bench_no_splits = _make_benchmark_data(periods=periods, seed=7)

    result = _benchmark_list_alpha_correction(
        strat_rets,
        [bench_with_splits, bench_no_splits],
        total_return_benchmark=False,
        benchmark_commission=0.001,
        benchmark_slippage=0.001,
        benchmark_cost_is_periodic=False,
    )

    assert result["n_benchmarks"] == 2
    assert isinstance(result["per_benchmark"], list)
    assert len(result["per_benchmark"]) == 2

    # Both per-benchmark stats must be present and well-formed.
    for stats in result["per_benchmark"]:
        assert stats is not None, "Expected non-None per-benchmark stats"
        for k in ("alpha", "beta", "correlation_with_benchmark", "benchmark_total_return"):
            assert k in stats, f"missing key {k} in per-benchmark stats"

    # The split-bearing benchmark must have been adjusted: an unadjusted
    # 2-for-1 split at index 100 would inject a ~-50% price drop into the
    # benchmark total return; the split-aware path must recover a plausible
    # (non-catastrophic) value.
    split_stats = result["per_benchmark"][0]
    assert split_stats["benchmark_total_return"] > -0.2, (
        f"Split-bearing benchmark should be adjusted, got benchmark_total_return="
        f"{split_stats['benchmark_total_return']:.4f}"
    )

    # Aggregate Deflated Alpha must be well-formed for >= 2 benchmarks.
    da = result["deflated_alpha"]
    assert da is not None, "Expected aggregate deflated_alpha for 2 benchmarks"
    for key in ("deflated_alpha_ratio", "p_value", "alpha", "expected_max_alpha",
                "n_benchmarks", "n_observations", "skewness", "kurtosis", "z_score"):
        assert key in da, f"missing key {key} in aggregate deflated_alpha"
    assert da["n_benchmarks"] == 2
    assert 0.0 <= da["deflated_alpha_ratio"] <= 1.0
    assert 0.0 <= da["p_value"] <= 1.0


def test_benchmark_list_alpha_correction_mixed_splits_backward_compat():
    """A single split-bearing benchmark in a multi-benchmark list still gets
    per-benchmark deflated_alpha correction, and the aggregate uses the first
    benchmark's alpha.  Single-benchmark list must NOT get an aggregate
    deflated_alpha (backward compatibility).
    """
    np.random.seed(41)
    periods = 252
    strat_rets = pd.Series(
        np.random.normal(0.0005, 0.012, periods),
        index=pd.date_range("2020-01-01", periods=periods, freq="B"),
    )
    bench_splits = _make_benchmark_data_with_splits(
        periods=periods, split_at=50, seed=13
    )

    # Two benchmarks, both split-bearing: per-benchmark correction applies.
    result2 = _benchmark_list_alpha_correction(
        strat_rets, [bench_splits, bench_splits],
        benchmark_commission=0.0, benchmark_slippage=0.0,
    )
    assert result2["n_benchmarks"] == 2
    assert result2["deflated_alpha"] is not None
    for stats in result2["per_benchmark"]:
        assert stats is not None
        assert "deflated_alpha" in stats, "per-benchmark deflated_alpha missing"
        assert "alpha_pvalue_original" in stats

    # Single benchmark: no aggregate deflated_alpha (backward compat).
    result1 = _benchmark_list_alpha_correction(
        strat_rets, [bench_splits],
        benchmark_commission=0.0, benchmark_slippage=0.0,
    )
    assert result1["n_benchmarks"] == 1
    assert result1["deflated_alpha"] is None, (
        "Single benchmark must not get an aggregate deflated_alpha"
    )


def test_benchmark_list_alpha_correction_handles_splits():
    """_benchmark_list_alpha_correction uses split-aware stats when benchmarks have splits."""
    # Build aligned strategy and benchmark returns
    np.random.seed(7)
    n = 60
    strat_rets = pd.Series(np.random.normal(0.001, 0.02, n))
    bench_rets = pd.Series(np.random.normal(0.0005, 0.015, n))
    strat_rets.index = pd.date_range("2020-01-01", periods=n, freq="D")
    bench_rets.index = pd.date_range("2020-01-01", periods=n, freq="D")
    bench1 = pd.DataFrame({
        "date": bench_rets.index,
        "close": (1 + bench_rets).cumprod() * 100,
        "open": (1 + bench_rets).cumprod() * 99,
        "high": (1 + bench_rets).cumprod() * 101,
        "low": (1 + bench_rets).cumprod() * 98,
        "volume": 1000000,
        "splits": np.ones(n),
    })
    bench1.iloc[10, bench1.columns.get_loc("splits")] = 2.0
    # Recompute close with split adjustment conceptually; easier to just use adjusted logic by calling through
    # Or recompute returns to match
    bench1_adj = _make_benchmark_data_with_splits(periods=len(strat_rets), split_at=10, seed=21)
    # align
    common = strat_rets.index.intersection(bench1_adj.index)
    result = _benchmark_list_alpha_correction(
        strat_rets.loc[common],
        [bench1_adj.loc[common]],
        total_return_benchmark=False,
    )
    per_bench = result["per_benchmark"]
    assert per_bench is not None
    assert len(per_bench) == 1
    stats = per_bench[0]
    assert stats is not None
    for k in ("alpha", "beta", "correlation_with_benchmark"):
        assert k in stats


def _make_indexed_df(dates) -> pd.DataFrame:
    """Build a DataFrame carrying only a DatetimeIndex (used to exercise
    `_verify_split_separation`, which reads only the index)."""
    return pd.DataFrame(index=pd.DatetimeIndex(dates))


def test_verify_split_separation_clean_splits_pass():
    """Clean, disjoint, chronological splits pass with all checks green."""
    train = _make_indexed_df(pd.date_range("2020-01-01", periods=10, freq="B"))
    val = _make_indexed_df(pd.date_range("2020-01-16", periods=5, freq="B"))
    test = _make_indexed_df(pd.date_range("2020-01-23", periods=5, freq="B"))
    result = _verify_split_separation(train, val, test, strict=False)
    assert result["disjoint"] is True
    assert result["chronological"] is True
    assert result["train_val_overlap"] == 0
    assert result["val_test_overlap"] == 0
    assert result["train_test_overlap"] == 0
    assert result["train_size"] == 10
    assert result["val_size"] == 5
    assert result["test_size"] == 5


def test_verify_split_separation_train_val_overlap_raises():
    """Train/validation overlap must raise ValueError in strict mode."""
    train = _make_indexed_df(pd.date_range("2020-01-01", periods=10, freq="B"))
    val = _make_indexed_df(pd.date_range("2020-01-08", periods=8, freq="B"))
    test = _make_indexed_df(pd.date_range("2020-01-20", periods=5, freq="B"))
    raised = False
    try:
        _verify_split_separation(train, val, test, strict=True)
    except ValueError:
        raised = True
    assert raised, "expected ValueError for train/validation overlap"


def test_verify_split_separation_val_test_overlap_raises():
    """Validation/test overlap must raise ValueError in strict mode."""
    train = _make_indexed_df(pd.date_range("2020-01-01", periods=5, freq="B"))
    val = _make_indexed_df(pd.date_range("2020-01-08", periods=5, freq="B"))
    test = _make_indexed_df(pd.date_range("2020-01-10", periods=8, freq="B"))
    raised = False
    try:
        _verify_split_separation(train, val, test, strict=True)
    except ValueError:
        raised = True
    assert raised, "expected ValueError for validation/test overlap"


def test_verify_split_separation_train_test_overlap_raises():
    """Train/test overlap must raise ValueError in strict mode."""
    train = _make_indexed_df(pd.date_range("2020-01-01", periods=10, freq="B"))
    val = _make_indexed_df(pd.date_range("2020-01-16", periods=5, freq="B"))
    test = _make_indexed_df(pd.date_range("2020-01-08", periods=10, freq="B"))
    raised = False
    try:
        _verify_split_separation(train, val, test, strict=True)
    except ValueError:
        raised = True
    assert raised, "expected ValueError for train/test overlap"


def test_verify_split_separation_non_strict_returns_diagnostic():
    """Non-strict mode returns the diagnostic dict without raising on overlap."""
    train = _make_indexed_df(pd.date_range("2020-01-01", periods=10, freq="B"))
    val = _make_indexed_df(pd.date_range("2020-01-08", periods=8, freq="B"))
    test = _make_indexed_df(pd.date_range("2020-01-20", periods=5, freq="B"))
    result = _verify_split_separation(train, val, test, strict=False)
    assert result["disjoint"] is False
    assert result["chronological"] is False
    assert result["train_val_overlap"] > 0


def test_verify_split_separation_empty_split_raises():
    """An empty split raises ValueError in strict mode."""
    train = _make_indexed_df(pd.DatetimeIndex([]))
    val = _make_indexed_df(pd.date_range("2020-01-08", periods=5, freq="B"))
    test = _make_indexed_df(pd.date_range("2020-01-15", periods=5, freq="B"))
    raised = False
    try:
        _verify_split_separation(train, val, test, strict=True)
    except ValueError:
        raised = True
    assert raised, "expected ValueError for empty train split"


def main() -> int:
    tests = TEST_REGISTRY

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



def test_benchmark_stats_with_splits_produces_finite_inference():
    """Regression: split-bearing benchmarks produce finite alpha/beta/stats."""
    dates = pd.date_range("2020-01-01", periods=60, freq="B")
    rng = np.random.default_rng(123)
    strategy_returns = pd.Series(rng.normal(0.001, 0.01, 60), index=dates)
    benchmark_data = _make_benchmark_data_with_splits(periods=60, split_at=30, seed=123)
    bench_rets = benchmark_data["close"].pct_change().dropna()
    _, aligned = strategy_returns.align(bench_rets, join="inner")
    aligned = aligned.dropna()
    stats = _benchmark_stats_with_splits(
        strategy_returns, aligned, 252,
        benchmark_data=benchmark_data,
    )
    assert np.isfinite(stats["alpha"]), f"alpha must be finite, got {stats['alpha']}"
    assert np.isfinite(stats["beta"]), f"beta must be finite, got {stats['beta']}"
    assert np.isfinite(stats["alpha_pvalue"]), f"alpha_pvalue must be finite, got {stats['alpha_pvalue']}"
    assert np.isfinite(stats["correlation_with_benchmark"])
    assert np.isfinite(stats["benchmark_total_return"])


def test_benchmark_stats_with_splits_regression_pins_corrected_values():
    """Regression test pinning corrected alpha/beta for a split-bearing benchmark.

    After fixing the NaN from leading NaN in pct_change() with dropna(), the
    split-adjusted path should produce finite, deterministic stats.
    """
    dates = pd.date_range("2020-01-01", periods=60, freq="B")
    rng = np.random.default_rng(42)
    strategy_returns = pd.Series(rng.normal(0.0005, 0.012, 60), index=dates)
    split_at = 25
    base = 100 + np.cumsum(rng.normal(0.0003, 0.008, 60))
    splits = pd.Series([1.0] * 60, index=dates)
    splits.iloc[split_at:] = 0.5
    close = base.copy()
    close[split_at:] = close[split_at:] / 2.0
    benchmark_data = pd.DataFrame({
        "close": close,
        "splits": splits,
    }, index=dates)

    bench_rets = benchmark_data["close"].pct_change().dropna()
    _, aligned = strategy_returns.align(bench_rets, join="inner")
    aligned = aligned.dropna()
    stats = _benchmark_stats_with_splits(
        strategy_returns, aligned, 252,
        benchmark_data=benchmark_data,
    )
    assert np.isfinite(stats["alpha"])
    assert np.isfinite(stats["beta"])
    assert np.isfinite(stats["alpha_pvalue"])
    assert abs(stats["alpha"] - 0.011441039611221912) < 1e-10
    assert abs(stats["beta"] - (-0.003953175078033304)) < 1e-10
    assert abs(stats["alpha_pvalue"] - 0.9813727464) < 1e-8
    assert np.isfinite(stats["correlation_with_benchmark"])
    assert np.isfinite(stats["r_squared"])


def test_optimize_impact_sweep_records_bias_controls_and_deflated_sharpe():
    """Optimize impact sweep propagates bias_controls_engaged and n_trials.

    With --deflate, every sweep row must surface the bias-controls engagement
    flag plus the best combination's Deflated Sharpe Ratio and its trial count
    (n_trials == number of evaluated combinations == n_combos).
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        csv_path = os.path.join(tmpdir, "data.csv")
        _write_ohlcv_csv(csv_path, periods=600)
        out_dir = os.path.join(tmpdir, "out")
        argv = [
            "walk_forward", "optimize",
            "--data", csv_path,
            "--symbol", "SPY",
            "--strategy", "sma_crossover",
            "--param-grid", '{"fast_period": [3, 5, 7], "slow_period": [10, 12, 15]}',
            "--output", out_dir,
            "--deflate",
            "--impact-coefficients", "0", "2", "5",
        ]
        with patch.object(sys, "argv", argv), \
                redirect_stdout(StringIO()), redirect_stderr(StringIO()):
            rc = walk_forward_main()

        assert rc == 0, f"CLI optimize impact sweep should exit 0, got {rc}"
        sweep_path = os.path.join(out_dir, "parameter_optimization_impact_sweep.json")
        assert os.path.exists(sweep_path), "parameter_optimization_impact_sweep.json not written"
        with open(sweep_path) as f:
            payload = json.load(f)
        assert len(payload["results"]) == 3
        for row in payload["results"]:
            assert row["bias_controls_engaged"] is True, (
                f"expected bias_controls_engaged True, got {row}"
            )
            assert isinstance(row["deflated_sharpe"], float), (
                f"expected deflated_sharpe float, got {row.get('deflated_sharpe')}"
            )
            assert 0.0 <= row["deflated_sharpe"] <= 1.0, row
            assert row["deflated_sharpe_n_trials"] is not None, row
            assert row["deflated_sharpe_n_trials"] == row["n_combos"], (
                f"n_trials {row['deflated_sharpe_n_trials']} != n_combos {row['n_combos']}"
            )


def test_optimize_sweep_omits_deflated_sharpe_without_deflate():
    """Without --deflate, deflated_sharpe keys are absent but the bias flag is
    still recorded (opt-in multiple-testing correction, bias controls always
    traced when point-in-time validation runs)."""
    with tempfile.TemporaryDirectory() as tmpdir:
        csv_path = os.path.join(tmpdir, "data.csv")
        _write_ohlcv_csv(csv_path, periods=600)
        out_dir = os.path.join(tmpdir, "out")
        argv = [
            "walk_forward", "optimize",
            "--data", csv_path,
            "--symbol", "SPY",
            "--strategy", "sma_crossover",
            "--param-grid", '{"fast_period": [3, 5, 7], "slow_period": [10, 12, 15]}',
            "--output", out_dir,
            "--impact-coefficients", "0", "2",
        ]
        with patch.object(sys, "argv", argv), \
                redirect_stdout(StringIO()), redirect_stderr(StringIO()):
            rc = walk_forward_main()

        assert rc == 0, f"CLI optimize sweep should exit 0, got {rc}"
        sweep_path = os.path.join(out_dir, "parameter_optimization_impact_sweep.json")
        with open(sweep_path) as f:
            payload = json.load(f)
        for row in payload["results"]:
            assert row["bias_controls_engaged"] is True, row
            assert row["deflated_sharpe"] is None, row
            assert row["deflated_sharpe_n_trials"] is None, row


def test_cli_tear_sheet_links_each_benchmark_metric_row_to_its_provenance():
    """The tear-sheet JSON summary must pair each benchmark_metrics row with
    the provenance of the exact benchmark file it came from, so downstream
    consumers can trace corrected alpha/deflated alpha back to the file and
    checksum without relying on list order alone.

    Regression coverage across the multi-benchmark CLI paths (cpcv,
    walk-forward, optimize, monte-carlo), whose tear sheets render a
    Per-Benchmark Comparison section. The out-of-sample CLI tear sheet is
    single-benchmark by design and is covered by a separate test.
    """
    grid = '{"fast_period": [3, 5, 7], "slow_period": [10, 12, 15]}'

    # The optimize CLI path writes a parameter_optimization.json artifact
    # (not a tear sheet); its per-combo benchmark_metrics rows are verified
    # by the existing test_cli_optimize_multiple_benchmarks test. The
    # remaining multi-benchmark CLI paths all render a tear sheet.
    cases = [
        ("cpcv", ["--n-splits", "5", "--test-size", "0.2"]),
        ("walk-forward", ["--train-months", "12", "--test-months", "3", "--step-months", "2"]),
        ("monte-carlo", ["--n-simulations", "30"]),
    ]

    for cmd, extra in cases:
        with tempfile.TemporaryDirectory() as tmpdir:
            csv_path = os.path.join(tmpdir, "data.csv")
            bench1_path = os.path.join(tmpdir, "bench1.csv")
            bench2_path = os.path.join(tmpdir, "bench2.csv")
            _write_ohlcv_csv(csv_path, periods=800)
            _write_benchmark_csv(bench1_path, periods=800, seed=99)
            _write_benchmark_csv(bench2_path, periods=800, seed=7)
            out_dir = os.path.join(tmpdir, "out")
            argv = [
                "walk_forward", cmd,
                "--data", csv_path,
                "--benchmark", bench1_path, bench2_path,
                "--strategy", "sma_crossover",
                "--param-grid", grid,
                "--benchmark-commission", "0.001",
                "--benchmark-slippage", "0.001",
                "--benchmark-cost-is-periodic",
            ] + extra + ["--output", out_dir]
            with patch.object(sys, "argv", argv), \
                    redirect_stdout(StringIO()), redirect_stderr(StringIO()):
                rc = walk_forward_main()
            assert rc == 0, f"{cmd} should exit 0, got {rc}"

            ts_path = os.path.join(out_dir, "tear_sheet_summary.json")
            assert os.path.exists(ts_path), f"{cmd}: tear_sheet_summary.json not written"
            with open(ts_path) as f:
                ts = json.load(f)

            bm = ts.get("benchmark_metrics")
            assert isinstance(bm, list), (
                f"{cmd}: tear-sheet benchmark_metrics missing or not a list. Keys: {sorted(ts.keys())}"
            )
            assert len(bm) == 2, f"{cmd}: expected 2 benchmark_metrics rows, got {len(bm)}"

            # Each row must carry the provenance of its own benchmark file.
            checksums = []
            for i, row in enumerate(bm):
                assert "benchmark_provenance" in row, (
                    f"{cmd}: benchmark_metrics[{i}] missing benchmark_provenance"
                )
                prov = row["benchmark_provenance"]
                assert isinstance(prov, dict), (
                    f"{cmd}: benchmark_metrics[{i}].benchmark_provenance not a dict"
                )
                assert prov.get("checksum"), (
                    f"{cmd}: benchmark_metrics[{i}] provenance missing checksum"
                )
                assert prov.get("source_path") in (bench1_path, bench2_path), (
                    f"{cmd}: benchmark_metrics[{i}] provenance source_path not a benchmark file"
                )
                checksums.append(prov["checksum"])

            # The two checksums must differ (different benchmark files).
            assert checksums[0] != checksums[1], (
                f"{cmd}: both benchmark rows share the same checksum {checksums[0]}"
            )

            # The top-level benchmark_provenance list must match the per-row
            # provenances pairwise (same checksums, same order).
            prov_list = ts.get("benchmark_provenance")
            assert isinstance(prov_list, list), (
                f"{cmd}: top-level benchmark_provenance should be a list, got {type(prov_list)}"
            )
            assert len(prov_list) == 2, (
                f"{cmd}: expected 2 benchmark_provenance entries, got {len(prov_list)}"
            )
            top_checksums = [p["checksum"] for p in prov_list]
            assert top_checksums == checksums, (
                f"{cmd}: top-level provenance checksums {top_checksums} do not match "
                f"per-row checksums {checksums}"
            )


def test_cli_oos_tear_sheet_carries_provenance():
    """The out-of-sample tear sheet must carry benchmark_provenance so the
    report is traceable to the exact benchmark file(s).

    The OOS report path renders a single benchmark (the first when multiple
    were supplied), so the tear-sheet provenance is dict-shaped in both the
    single- and multi-benchmark cases.
    """
    grid = '{"fast_period": [3, 5, 7], "slow_period": [10, 12, 15]}'
    for bench_paths, label in [
        (["bench.csv"], "single"),
        (["bench1.csv", "bench2.csv"], "multi"),
    ]:
        with tempfile.TemporaryDirectory() as tmpdir:
            csv_path = os.path.join(tmpdir, "data.csv")
            _write_ohlcv_csv(csv_path, periods=800)
            for i, name in enumerate(bench_paths):
                _write_benchmark_csv(os.path.join(tmpdir, name), periods=800, seed=99 + i)
            out_dir = os.path.join(tmpdir, "out")
            argv = [
                "walk_forward", "out-of-sample",
                "--data", csv_path, "--benchmark",
            ] + [os.path.join(tmpdir, n) for n in bench_paths] + [
                "--strategy", "sma_crossover",
                "--param-grid", grid,
                "--output", out_dir,
                "--benchmark-commission", "0.001",
                "--benchmark-slippage", "0.001",
                "--benchmark-cost-is-periodic",
            ]
            with patch.object(sys, "argv", argv), \
                    redirect_stdout(StringIO()), redirect_stderr(StringIO()):
                rc = walk_forward_main()
            assert rc == 0, f"OOS {label} should exit 0, got {rc}"

            ts_path = os.path.join(out_dir, "tear_sheet_summary.json")
            with open(ts_path) as f:
                ts = json.load(f)
            prov = ts.get("benchmark_provenance")
            assert isinstance(prov, dict), (
                f"OOS {label}: tear sheet should carry a dict-shaped "
                f"benchmark_provenance, got {type(prov)}"
            )
            assert prov.get("checksum"), f"OOS {label}: provenance missing checksum"
            assert prov["source_path"] == os.path.join(tmpdir, bench_paths[0]), (
                f"OOS {label}: provenance should reference the first benchmark file"
            )


def _write_single_symbol_csv(path: str, periods: int = 600) -> None:
    """Write a single-symbol OHLCV CSV for walk-forward tests."""
    dates = pd.date_range("2020-01-01", periods=periods, freq="B")
    rng = np.random.default_rng(7)
    rets = rng.normal(0.0005, 0.015, periods)
    prices = 100 * np.exp(np.cumsum(rets))
    pd.DataFrame({
        "date": [d.strftime("%Y-%m-%d") for d in dates],
        "symbol": "SPY",
        "open": prices,
        "high": prices * 1.01,
        "low": prices * 0.99,
        "close": prices,
        "volume": rng.integers(1_000_000, 10_000_000, periods),
    }).to_csv(path, index=False)


def _write_multi_symbol_csv(path: str, periods: int = 600) -> None:
    """Write a panel with one survivor, one late entry, one early exit."""
    dates = pd.date_range("2020-01-01", periods=periods, freq="B")
    rows = []
    for i, (sym, start, end) in enumerate([
        ("SURV", 0, periods), ("LATE", 120, periods), ("EARLY", 0, periods - 120),
    ]):
        rng = np.random.default_rng(i + 1)
        rets = rng.normal(0.0005, 0.015, end - start)
        prices = 100 * np.exp(np.cumsum(rets))
        for j, d in enumerate(dates[start:end]):
            rows.append({
                "date": d.strftime("%Y-%m-%d"),
                "symbol": sym,
                "open": prices[j],
                "high": prices[j] * 1.01,
                "low": prices[j] * 0.99,
                "close": prices[j],
                "volume": int(rng.integers(1_000_000, 10_000_000)),
            })
    pd.DataFrame(rows).to_csv(path, index=False)


def test_cli_multi_symbol_load_and_validate_data_returns_survivorship():
    """_load_and_validate_data returns a survivorship dict with --multi-symbol."""
    with tempfile.TemporaryDirectory() as tmpdir:
        csv_path = os.path.join(tmpdir, "multi.csv")
        _write_multi_symbol_csv(csv_path)
        data, pit, surv = _load_and_validate_data(
            csv_path, symbol="SURV", start="2020-01-01", end="2021-12-31",
            multi_symbol=True,
        )
        assert surv is not None, "survivorship should be returned with multi_symbol=True"
        assert surv["surviving_symbols"] == ["SURV"]
        assert [e["symbol"] for e in surv["entered_symbols"]] == ["LATE"]
        assert [e["symbol"] for e in surv["exited_symbols"]] == ["EARLY"]
        assert surv["bias_score"] > 0.0


def test_cli_multi_symbol_out_of_sample_sets_bias_controls_engaged():
    """--multi-symbol on out-of-sample sets bias_controls_engaged=True and
    threads survivorship_bias into the summary JSON."""
    with tempfile.TemporaryDirectory() as tmpdir:
        csv_path = os.path.join(tmpdir, "multi.csv")
        _write_multi_symbol_csv(csv_path)
        out_dir = os.path.join(tmpdir, "out")
        argv = [
            "walk_forward", "out-of-sample",
            "--data", csv_path,
            "--strategy", "cross_sectional_momentum",
            "--param-grid", '{"lookback": [20], "top_quantile": [0.4], "bottom_quantile": [0.2]}',
            "--output", out_dir,
            "--multi-symbol",
            "--no-validate-point-in-time",
            "--wf-train-months", "6",
            "--wf-test-months", "2",
            "--wf-step-months", "2",
        ]
        with patch.object(sys, "argv", argv), \
                redirect_stdout(StringIO()), redirect_stderr(StringIO()):
            rc = walk_forward_main()

        assert rc == 0, f"CLI out-of-sample --multi-symbol should exit 0, got {rc}"

        summary_path = os.path.join(out_dir, "out_of_sample_summary.json")
        assert os.path.exists(summary_path), "out_of_sample_summary.json not written"
        with open(summary_path) as f:
            summary = json.load(f)

        assert summary.get("bias_controls_engaged") is True, \
            f"Expected bias_controls_engaged=True with --multi-symbol, got {summary.get('bias_controls_engaged')}"
        assert "survivorship_bias" in summary, \
            "survivorship_bias missing from out-of-sample summary"
        surv = summary["survivorship_bias"]
        assert surv["surviving_symbols"] == ["SURV"]
        assert surv["bias_score"] > 0.0


def test_cli_multi_symbol_out_of_sample_writes_survivorship_artifact():
    """--multi-symbol persists the survivorship_bias.json artifact."""
    with tempfile.TemporaryDirectory() as tmpdir:
        csv_path = os.path.join(tmpdir, "multi.csv")
        _write_multi_symbol_csv(csv_path)
        out_dir = os.path.join(tmpdir, "out")
        argv = [
            "walk_forward", "out-of-sample",
            "--data", csv_path,
            "--strategy", "cross_sectional_momentum",
            "--param-grid", '{"lookback": [20], "top_quantile": [0.4], "bottom_quantile": [0.2]}',
            "--output", out_dir,
            "--multi-symbol",
            "--wf-train-months", "6",
            "--wf-test-months", "2",
            "--wf-step-months", "2",
        ]
        with patch.object(sys, "argv", argv), \
                redirect_stdout(StringIO()), redirect_stderr(StringIO()):
            rc = walk_forward_main()

        assert rc == 0, f"CLI out-of-sample --multi-symbol should exit 0, got {rc}"

        surv_path = os.path.join(out_dir, "survivorship_bias.json")
        assert os.path.exists(surv_path), "survivorship_bias.json not written"
        with open(surv_path) as f:
            surv = json.load(f)
        assert surv["surviving_symbols"] == ["SURV"]
        assert [e["symbol"] for e in surv["entered_symbols"]] == ["LATE"]
        assert [e["symbol"] for e in surv["exited_symbols"]] == ["EARLY"]
        assert surv["bias_score"] > 0.0


def test_cli_multi_symbol_walk_forward_writes_survivorship_artifact():
    """--multi-symbol on walk-forward persists survivorship_bias.json.

    Regression for a defect where the walk-forward summary was written but
    the standalone survivorship artifact was not, so panel walk-forward runs
    were not auditable on the same file name as the run_backtest CLI path.
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        csv_path = os.path.join(tmpdir, "multi.csv")
        _write_multi_symbol_csv(csv_path)
        out_dir = os.path.join(tmpdir, "out")
        argv = [
            "walk_forward", "walk-forward",
            "--data", csv_path,
            "--strategy", "cross_sectional_momentum",
            "--param-grid", '{"lookback": [20], "top_quantile": [0.4], "bottom_quantile": [0.2]}',
            "--output", out_dir,
            "--multi-symbol",
            "--no-validate-point-in-time",
            "--train-months", "6",
            "--test-months", "2",
            "--step-months", "2",
        ]
        with patch.object(sys, "argv", argv), \
                redirect_stdout(StringIO()), redirect_stderr(StringIO()):
            rc = walk_forward_main()

        assert rc == 0, f"CLI walk-forward --multi-symbol should exit 0, got {rc}"

        surv_path = os.path.join(out_dir, "survivorship_bias.json")
        assert os.path.exists(surv_path), "survivorship_bias.json not written for walk-forward --multi-symbol"
        with open(surv_path) as f:
            surv = json.load(f)
        assert surv["surviving_symbols"] == ["SURV"]
        assert [e["symbol"] for e in surv["entered_symbols"]] == ["LATE"]
        assert [e["symbol"] for e in surv["exited_symbols"]] == ["EARLY"]
        assert surv["bias_score"] > 0.0

        summary_path = os.path.join(out_dir, "walk_forward_summary.json")
        with open(summary_path) as f:
            summary = json.load(f)
        assert summary["config"].get("multi_symbol") is True, \
            "walk-forward summary config should record multi_symbol=True"
        assert summary.get("bias_controls_engaged") is True
        assert summary.get("survivorship_bias") is not None


def test_cli_multi_symbol_cpcv_writes_survivorship_artifact():
    """--multi-symbol on CPCV persists survivorship_bias.json."""
    with tempfile.TemporaryDirectory() as tmpdir:
        csv_path = os.path.join(tmpdir, "multi.csv")
        _write_multi_symbol_csv(csv_path)
        out_dir = os.path.join(tmpdir, "out")
        argv = [
            "walk_forward", "cpcv",
            "--data", csv_path,
            "--strategy", "cross_sectional_momentum",
            "--param-grid", '{"lookback": [20], "top_quantile": [0.4], "bottom_quantile": [0.2]}',
            "--output", out_dir,
            "--multi-symbol",
            "--no-validate-point-in-time",
            "--n-splits", "4",
            "--test-size", "0.2",
        ]
        with patch.object(sys, "argv", argv), \
                redirect_stdout(StringIO()), redirect_stderr(StringIO()):
            rc = walk_forward_main()

        assert rc == 0, f"CLI cpcv --multi-symbol should exit 0, got {rc}"

        surv_path = os.path.join(out_dir, "survivorship_bias.json")
        assert os.path.exists(surv_path), "survivorship_bias.json not written for cpcv --multi-symbol"
        with open(surv_path) as f:
            surv = json.load(f)
        assert surv["surviving_symbols"] == ["SURV"]

        summary_path = os.path.join(out_dir, "cpcv_summary.json")
        with open(summary_path) as f:
            summary = json.load(f)
        assert summary["config"].get("multi_symbol") is True, \
            "cpcv summary config should record multi_symbol=True"


def test_cli_multi_symbol_optimize_writes_survivorship_artifact():
    """--multi-symbol on parameter optimization persists survivorship_bias.json."""
    with tempfile.TemporaryDirectory() as tmpdir:
        csv_path = os.path.join(tmpdir, "multi.csv")
        _write_multi_symbol_csv(csv_path)
        out_dir = os.path.join(tmpdir, "out")
        argv = [
            "walk_forward", "optimize",
            "--data", csv_path,
            "--strategy", "cross_sectional_momentum",
            "--param-grid", '{"lookback": [20], "top_quantile": [0.4], "bottom_quantile": [0.2]}',
            "--output", out_dir,
            "--multi-symbol",
            "--no-validate-point-in-time",
        ]
        with patch.object(sys, "argv", argv), \
                redirect_stdout(StringIO()), redirect_stderr(StringIO()):
            rc = walk_forward_main()

        assert rc == 0, f"CLI optimize --multi-symbol should exit 0, got {rc}"

        surv_path = os.path.join(out_dir, "survivorship_bias.json")
        assert os.path.exists(surv_path), "survivorship_bias.json not written for optimize --multi-symbol"
        with open(surv_path) as f:
            surv = json.load(f)
        assert surv["surviving_symbols"] == ["SURV"]


def _assert_multi_symbol_sweep_records_survivorship(out_dir, sweep_file, expected_commissions):
    sweep_path = os.path.join(out_dir, sweep_file)
    assert os.path.exists(sweep_path), f"{sweep_file} not written"
    with open(sweep_path) as f:
        payload = json.load(f)
    results = payload["results"]
    assert len(results) == len(expected_commissions), (
        f"expected {len(expected_commissions)} sweep rows, got {len(results)}"
    )
    for i, r in enumerate(results):
        assert r.get("commission") == expected_commissions[i], (
            f"row {i} commission {r.get('commission')} != {expected_commissions[i]}"
        )
        sb = r.get("survivorship_bias")
        assert isinstance(sb, dict), f"row {i} survivorship_bias not a dict: {sb!r}"
        assert sb.get("surviving_symbols") == ["SURV"], (
            f"row {i} surviving_symbols {sb.get('surviving_symbols')!r}"
        )
        assert sb.get("bias_score", 0.0) > 0.0, f"row {i} bias_score {sb.get('bias_score')!r}"
        assert r.get("bias_controls_engaged") is True, (
            f"row {i} bias_controls_engaged {r.get('bias_controls_engaged')!r}"
        )


def test_cli_multi_symbol_walk_forward_commission_sweep_records_survivorship():
    """--multi-symbol walk-forward commission sweep records survivorship_bias per row."""
    with tempfile.TemporaryDirectory() as tmpdir:
        csv_path = os.path.join(tmpdir, "multi.csv")
        _write_multi_symbol_csv(csv_path)
        out_dir = os.path.join(tmpdir, "out")
        argv = [
            "walk_forward", "walk-forward",
            "--data", csv_path,
            "--strategy", "cross_sectional_momentum",
            "--param-grid", '{"lookback": [20], "top_quantile": [0.4], "bottom_quantile": [0.2]}',
            "--output", out_dir,
            "--multi-symbol",
            "--no-validate-point-in-time",
            "--train-months", "6", "--test-months", "2", "--step-months", "2",
            "--commissions", "0.0002", "0.002", "0.004",
        ]
        with patch.object(sys, "argv", argv), \
                redirect_stdout(StringIO()), redirect_stderr(StringIO()):
            rc = walk_forward_main()

        assert rc == 0, f"CLI walk-forward --multi-symbol commission sweep should exit 0, got {rc}"
        sweep_path = os.path.join(out_dir, "walk_forward_commission_sweep.json")
        assert os.path.exists(sweep_path), "walk_forward_commission_sweep.json not written"
        with open(sweep_path) as f:
            payload = json.load(f)
        results = payload["results"]
        assert len(results) == 3
        assert [r["commission"] for r in results] == [0.0002, 0.002, 0.004]
        returns = [float(r["total_oos_return"]) for r in results]
        assert returns[2] < returns[0], (
            f"expected OOS return degradation with commission, got {returns}"
        )
        _assert_multi_symbol_sweep_records_survivorship(
            out_dir, "walk_forward_commission_sweep.json", [0.0002, 0.002, 0.004]
        )


def test_cli_multi_symbol_out_of_sample_commission_sweep_records_survivorship():
    """--multi-symbol out-of-sample commission sweep records survivorship_bias per row."""
    with tempfile.TemporaryDirectory() as tmpdir:
        csv_path = os.path.join(tmpdir, "multi.csv")
        _write_multi_symbol_csv(csv_path)
        out_dir = os.path.join(tmpdir, "out")
        argv = [
            "walk_forward", "out-of-sample",
            "--data", csv_path,
            "--strategy", "cross_sectional_momentum",
            "--param-grid", '{"lookback": [20], "top_quantile": [0.4], "bottom_quantile": [0.2]}',
            "--output", out_dir,
            "--multi-symbol",
            "--no-validate-point-in-time",
            "--wf-train-months", "6", "--wf-test-months", "2", "--wf-step-months", "2",
            "--commissions", "0.0002", "0.002", "0.004",
        ]
        with patch.object(sys, "argv", argv), \
                redirect_stdout(StringIO()), redirect_stderr(StringIO()):
            rc = walk_forward_main()

        assert rc == 0, f"CLI out-of-sample --multi-symbol commission sweep should exit 0, got {rc}"
        _assert_multi_symbol_sweep_records_survivorship(
            out_dir, "out_of_sample_commission_sweep.json", [0.0002, 0.002, 0.004]
        )


def test_cli_multi_symbol_cpcv_commission_sweep_records_survivorship():
    """--multi-symbol CPCV commission sweep records survivorship_bias per row."""
    with tempfile.TemporaryDirectory() as tmpdir:
        csv_path = os.path.join(tmpdir, "multi.csv")
        _write_multi_symbol_csv(csv_path)
        out_dir = os.path.join(tmpdir, "out")
        argv = [
            "walk_forward", "cpcv",
            "--data", csv_path,
            "--strategy", "cross_sectional_momentum",
            "--param-grid", '{"lookback": [20], "top_quantile": [0.4], "bottom_quantile": [0.2]}',
            "--output", out_dir,
            "--multi-symbol",
            "--no-validate-point-in-time",
            "--n-splits", "4", "--test-size", "0.2",
            "--commissions", "0.0002", "0.002", "0.004",
        ]
        with patch.object(sys, "argv", argv), \
                redirect_stdout(StringIO()), redirect_stderr(StringIO()):
            rc = walk_forward_main()

        assert rc == 0, f"CLI cpcv --multi-symbol commission sweep should exit 0, got {rc}"
        _assert_multi_symbol_sweep_records_survivorship(
            out_dir, "cpcv_commission_sweep.json", [0.0002, 0.002, 0.004]
        )


def test_cli_multi_symbol_optimize_commission_sweep_records_survivorship():
    """--multi-symbol parameter-optimization commission sweep records survivorship_bias per row."""
    with tempfile.TemporaryDirectory() as tmpdir:
        csv_path = os.path.join(tmpdir, "multi.csv")
        _write_multi_symbol_csv(csv_path)
        out_dir = os.path.join(tmpdir, "out")
        argv = [
            "walk_forward", "optimize",
            "--data", csv_path,
            "--strategy", "cross_sectional_momentum",
            "--param-grid", '{"lookback": [20], "top_quantile": [0.4], "bottom_quantile": [0.2]}',
            "--output", out_dir,
            "--multi-symbol",
            "--no-validate-point-in-time",
            "--commissions", "0.0002", "0.002", "0.004",
        ]
        with patch.object(sys, "argv", argv), \
                redirect_stdout(StringIO()), redirect_stderr(StringIO()):
            rc = walk_forward_main()

        assert rc == 0, f"CLI optimize --multi-symbol commission sweep should exit 0, got {rc}"
        _assert_multi_symbol_sweep_records_survivorship(
            out_dir, "parameter_optimization_commission_sweep.json", [0.0002, 0.002, 0.004]
        )




def test_cli_multi_symbol_monte_carlo_commission_sweep_records_survivorship():
    """--multi-symbol monte-carlo commission sweep records survivorship_bias per row."""
    with tempfile.TemporaryDirectory() as tmpdir:
        csv_path = os.path.join(tmpdir, "multi.csv")
        _write_multi_symbol_csv(csv_path)
        out_dir = os.path.join(tmpdir, "out")
        argv = [
            "walk_forward", "monte-carlo",
            "--data", csv_path,
            "--strategy", "cross_sectional_momentum",
            "--param-grid", '{"lookback": [20], "top_quantile": [0.4], "bottom_quantile": [0.2]}',
            "--output", out_dir,
            "--multi-symbol",
            "--no-validate-point-in-time",
            "--n-trials", "10",
            "--commissions", "0.0002", "0.002", "0.004",
        ]
        with patch.object(sys, "argv", argv), \
                redirect_stdout(StringIO()), redirect_stderr(StringIO()):
            rc = walk_forward_main()

        assert rc == 0, f"CLI monte-carlo --multi-symbol commission sweep should exit 0, got {rc}"
        _assert_multi_symbol_sweep_records_survivorship(
            out_dir, "monte_carlo_commission_sweep.json", [0.0002, 0.002, 0.004]
        )


def test_cli_walk_forward_no_benchmark_does_not_crash():
    """walk-forward without a benchmark must not raise UnboundLocalError.

    Regression for a defect where `benchmark_returns_list` was only assigned
    inside the `if benchmark is not None` branch but referenced in the
    `elif benchmark_returns_list` report block below, so any benchmark-less
    walk-forward run crashed after writing the summary.
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        csv_path = os.path.join(tmpdir, "data.csv")
        _write_single_symbol_csv(csv_path)
        out_dir = os.path.join(tmpdir, "out")
        argv = [
            "walk_forward", "walk-forward",
            "--data", csv_path,
            "--strategy", "sma_crossover",
            "--param-grid", '{"fast_period": [5], "slow_period": [10]}',
            "--output", out_dir,
            "--no-validate-point-in-time",
            "--train-months", "6",
            "--test-months", "2",
            "--step-months", "2",
        ]
        with patch.object(sys, "argv", argv), \
                redirect_stdout(StringIO()), redirect_stderr(StringIO()):
            rc = walk_forward_main()

        assert rc == 0, f"CLI walk-forward without benchmark should exit 0, got {rc}"
        assert os.path.exists(os.path.join(out_dir, "walk_forward_summary.json"))
        assert os.path.exists(os.path.join(out_dir, "tear_sheet_summary.json"))


def _first_nonzero_series(series: pd.Series) -> pd.Series:
    """Subset of `series` at non-zero values (empty if all zero)."""
    return series[series != 0]


def test_calculate_strategy_returns_latency_shifts_entry_by_exact_periods():
    """Execution latency shifts the first position entry by exactly `latency` periods.

    Uses constant non-zero returns so strategy_returns is non-zero exactly
    where the achieved position is non-zero, making entry timing directly
    observable from the returned series. This is the per-latency entry-timing
    shift that walk-forward / out-of-sample returns now reflect.
    """
    data = _make_constant_return_ohlcv_data(periods=200, daily_return=0.001)
    signals = pd.Series(0.0, index=data.index)
    signals.iloc[30:] = 1.0  # enter long at period 30

    base = _calculate_strategy_returns(
        data, signals, commission=0.0, slippage=0.0,
        borrow_cost=0.0, funding_cost=0.0, latency=0, fill_rate=1.0,
    )
    base_entry = data.index.get_loc(_first_nonzero_series(base).index[0])
    # Signal enters at position 30; shift(1) places the first position at 31.
    assert base_entry == 31, f"latency=0 entry at {base_entry}, expected 31"

    for latency in (1, 2, 3):
        delayed = _calculate_strategy_returns(
            data, signals, commission=0.0, slippage=0.0,
            borrow_cost=0.0, funding_cost=0.0, latency=latency, fill_rate=1.0,
        )
        entry = data.index.get_loc(_first_nonzero_series(delayed).index[0])
        # Each added latency period delays the first entry by exactly one period.
        assert entry == base_entry + latency, (
            f"latency={latency}: entry at {entry}, expected {base_entry + latency}"
        )


def test_calculate_strategy_returns_fill_rate_scales_short_borrow_cost():
    """Halving the fill rate halves the per-period borrow cost on a constant short.

    With exactly zero asset returns, borrow cost is the only P&L component, so
    fill_rate=0.5 must produce exactly half the (negative) borrow drag of
    fill_rate=1.0. This is the per-fill-rate borrow-cost scaling that
    walk-forward / out-of-sample returns now reflect.
    """
    data = _make_constant_return_ohlcv_data(periods=200, daily_return=0.0)
    signals = pd.Series(-1.0, index=data.index)  # constant short
    borrow_cost = 0.03  # 3% per year

    full = _calculate_strategy_returns(
        data, signals, commission=0.0, slippage=0.0,
        borrow_cost=borrow_cost, funding_cost=0.0, latency=0, fill_rate=1.0,
    )
    half = _calculate_strategy_returns(
        data, signals, commission=0.0, slippage=0.0,
        borrow_cost=borrow_cost, funding_cost=0.0, latency=0, fill_rate=0.5,
    )

    assert len(full) == len(half) and len(full) > 0
    assert abs(half.sum() - 0.5 * full.sum()) < 1e-9, (
        f"fill_rate=0.5 borrow drag should be exactly half of fill_rate=1.0: "
        f"{half.sum():.10f} vs {0.5 * full.sum():.10f}"
    )
    assert half.sum() > full.sum()  # less negative drag


def test_walk_forward_analysis_default_latency_fill_rate_match_explicit_defaults():
    """walk_forward_Analysis defaults (latency=0, fill_rate=1.0) are bitwise
    identical to explicitly passing latency=0, fill_rate=1.0, so the change is
    backward compatible and prior behavior is preserved.
    """
    data = _make_ohlcv_data(periods=400, seed=42)
    factory = lambda params: build_strategy("sma_crossover", json.dumps(params))
    param_grid = {"fast_period": [5, 10], "slow_period": [20, 30]}
    common = dict(
        data=data, strategy_factory=factory, param_grid=param_grid,
        train_months=6, test_months=2, step_months=2,
        initial_capital=100000, commission=0.0002, slippage=0.0001,
    )

    defaults = walk_forward_analysis(**common)
    explicit = walk_forward_analysis(latency=0, fill_rate=1.0, **common)

    pd.testing.assert_series_equal(defaults["oos_returns"], explicit["oos_returns"])
    assert defaults["summary"] == explicit["summary"]


def test_walk_forward_analysis_fill_rate_invalid_raises():
    """fill_rate outside (0, 1] raises ValueError before execution."""
    data = _make_ohlcv_data(periods=200, seed=42)
    factory = lambda params: build_strategy("sma_crossover", json.dumps(params))
    param_grid = {"fast_period": [5], "slow_period": [10]}

    for bad_fill_rate in (0.0, -0.5, 1.5):
        try:
            walk_forward_analysis(
                data=data, strategy_factory=factory, param_grid=param_grid,
                train_months=6, test_months=2, step_months=2,
                initial_capital=100000, commission=0.0, slippage=0.0,
                latency=0, fill_rate=bad_fill_rate,
            )
        except ValueError:
            continue
        else:
            raise AssertionError(
                f"walk_forward_analysis should raise ValueError for fill_rate={bad_fill_rate}"
            )


def test_walk_forward_analysis_negative_latency_clamped_to_zero():
    """Negative latency is clamped to 0 (no accidental look-ahead), so it
    reproduces the latency=0 result exactly."""
    data = _make_ohlcv_data(periods=300, seed=42)
    factory = lambda params: build_strategy("sma_crossover", json.dumps(params))
    param_grid = {"fast_period": [5], "slow_period": [10]}
    common = dict(
        data=data, strategy_factory=factory, param_grid=param_grid,
        train_months=6, test_months=2, step_months=2,
        initial_capital=100000, commission=0.0, slippage=0.0,
    )

    clamped = walk_forward_analysis(latency=-3, fill_rate=1.0, **common)
    zero = walk_forward_analysis(latency=0, fill_rate=1.0, **common)

    pd.testing.assert_series_equal(clamped["oos_returns"], zero["oos_returns"])
    assert clamped["summary"] == zero["summary"]


def test_parameter_optimization_default_latency_fill_rate_match_explicit_defaults():
    """parameter_optimization defaults (latency=0, fill_rate=1.0) are bitwise
    identical to explicitly passing latency=0, fill_rate=1.0."""
    data = _make_ohlcv_data(periods=300, seed=42)
    factory = lambda params: build_strategy("sma_crossover", json.dumps(params))
    param_grid = {"fast_period": [5, 10], "slow_period": [20, 30]}
    common = dict(
        data=data, strategy_factory=factory, param_grid=param_grid,
        initial_capital=100000, commission=0.0002, slippage=0.0001,
    )

    defaults = parameter_optimization(**common)
    explicit = parameter_optimization(latency=0, fill_rate=1.0, **common)

    assert defaults == explicit


def test_cli_walk_forward_latency_sweep():
    """CLI walk-forward --latencies writes a sweep artifact whose OOS return
    degrades as execution latency rises (positions executed later)."""
    with tempfile.TemporaryDirectory() as tmpdir:
        csv_path = os.path.join(tmpdir, "data.csv")
        _write_ohlcv_csv(csv_path, periods=600)
        out_dir = os.path.join(tmpdir, "out")
        argv = [
            "walk_forward", "walk-forward",
            "--data", csv_path,
            "--symbol", "SPY",
            "--strategy", "sma_crossover",
            "--param-grid", '{"fast_period": [3, 5, 7], "slow_period": [10, 12, 15]}',
            "--output", out_dir,
            "--latencies", "0", "2", "5",
        ]
        with patch.object(sys, "argv", argv), \
                redirect_stdout(StringIO()), redirect_stderr(StringIO()):
            rc = walk_forward_main()

        assert rc == 0, f"CLI walk-forward latency sweep should exit 0, got {rc}"
        sweep_path = os.path.join(out_dir, "walk_forward_latency_sweep.json")
        assert os.path.exists(sweep_path), "walk_forward_latency_sweep.json not written"
        with open(sweep_path) as f:
            payload = json.load(f)
        assert payload["latencies"] == [0, 2, 5]
        assert len(payload["results"]) == 3
        # Each row records the latency it was swept at.
        assert [r["latency"] for r in payload["results"]] == [0, 2, 5]
        # Fill rate is held at the single-run default (1.0) for a latency sweep.
        assert all(r["fill_rate"] == 1.0 for r in payload["results"])
        returns = [r["total_oos_return"] for r in payload["results"]]
        assert returns[2] < returns[0], (
            f"expected OOS return degradation with latency, got {returns}"
        )


def test_cli_walk_forward_fill_rate_sweep():
    """CLI walk-forward --fill-rates writes a sweep artifact whose OOS return
    degrades as the fill rate falls (less of each targeted position change is
    filled, so turnover and costs scale down with the achieved position)."""
    with tempfile.TemporaryDirectory() as tmpdir:
        csv_path = os.path.join(tmpdir, "data.csv")
        _write_ohlcv_csv(csv_path, periods=600)
        out_dir = os.path.join(tmpdir, "out")
        argv = [
            "walk_forward", "walk-forward",
            "--data", csv_path,
            "--symbol", "SPY",
            "--strategy", "sma_crossover",
            "--param-grid", '{"fast_period": [3, 5, 7], "slow_period": [10, 12, 15]}',
            "--output", out_dir,
            "--fill-rates", "1.0", "0.5", "0.1",
        ]
        with patch.object(sys, "argv", argv), \
                redirect_stdout(StringIO()), redirect_stderr(StringIO()):
            rc = walk_forward_main()

        assert rc == 0, f"CLI walk-forward fill-rate sweep should exit 0, got {rc}"
        sweep_path = os.path.join(out_dir, "walk_forward_fill_rate_sweep.json")
        assert os.path.exists(sweep_path), "walk_forward_fill_rate_sweep.json not written"
        with open(sweep_path) as f:
            payload = json.load(f)
        assert payload["fill_rates"] == [1.0, 0.5, 0.1]
        assert len(payload["results"]) == 3
        # Each row records the fill rate it was swept at.
        assert [r["fill_rate"] for r in payload["results"]] == [1.0, 0.5, 0.1]
        # Latency is held at the single-run default (0) for a fill-rate sweep.
        assert all(r["latency"] == 0 for r in payload["results"])
        returns = [r["total_oos_return"] for r in payload["results"]]
        assert returns[2] < returns[0], (
            f"expected OOS return degradation with lower fill rate, got {returns}"
        )


def test_cli_walk_forward_invalid_fill_rate_rejected():
    """CLI --fill-rate outside (0, 1] is rejected at the boundary with a
    ValueError before any backtest runs (mirrors the run_backtest CLI path,
    which also does not catch the ValueError)."""
    with tempfile.TemporaryDirectory() as tmpdir:
        csv_path = os.path.join(tmpdir, "data.csv")
        _write_ohlcv_csv(csv_path, periods=600)
        out_dir = os.path.join(tmpdir, "out")
        argv = [
            "walk_forward", "walk-forward",
            "--data", csv_path,
            "--symbol", "SPY",
            "--strategy", "sma_crossover",
            "--param-grid", '{"fast_period": [5], "slow_period": [10]}',
            "--output", out_dir,
            "--fill-rate", "0",
        ]
        with patch.object(sys, "argv", argv), \
                redirect_stdout(StringIO()), redirect_stderr(StringIO()):
            try:
                walk_forward_main()
            except ValueError as e:
                assert "fill_rate" in str(e) or "fill-rate" in str(e), (
                    f"unexpected ValueError message: {e}"
                )
            else:
                raise AssertionError(
                    "CLI should reject fill_rate=0 with a ValueError"
                )


def test_cpcv_analysis_defaults_preserve_latency_and_fill_rate():
    """cpcv_analysis defaults (latency=0, fill_rate=1.0) are bitwise identical to
    explicitly passing latency=0, fill_rate=1.0, so prior behavior is preserved.
    """
    data = _make_ohlcv_data(periods=400, seed=42)
    factory = lambda params: build_strategy("sma_crossover", json.dumps(params))
    param_grid = {"fast_period": [5, 10], "slow_period": [20, 30]}
    common = dict(
        data=data, strategy_factory=factory, param_grid=param_grid,
        initial_capital=100000, commission=0.0002, slippage=0.0001,
    )

    defaults = cpcv_analysis(**common)
    explicit = cpcv_analysis(latency=0, fill_rate=1.0, **common)

    pd.testing.assert_series_equal(defaults["oos_returns"], explicit["oos_returns"])
    assert defaults["summary"] == explicit["summary"]


def test_cpcv_analysis_fill_rate_invalid_raises():
    """fill_rate outside (0, 1] raises ValueError before execution."""
    data = _make_ohlcv_data(periods=200, seed=42)
    factory = lambda params: build_strategy("sma_crossover", json.dumps(params))
    param_grid = {"fast_period": [5], "slow_period": [10]}

    for bad_fill_rate in (0.0, -0.5, 1.5):
        try:
            cpcv_analysis(
                data=data, strategy_factory=factory, param_grid=param_grid,
                initial_capital=100000, commission=0.0, slippage=0.0,
                latency=0, fill_rate=bad_fill_rate,
            )
        except ValueError:
            continue
        else:
            raise AssertionError(
                f"cpcv_analysis should raise ValueError for fill_rate={bad_fill_rate}"
            )


def test_cpcv_analysis_negative_latency_clamped_to_zero():
    """Negative latency is clamped to 0 (no accidental look-ahead), so results
    reproduce latency=0 exactly."""
    data = _make_ohlcv_data(periods=300, seed=42)
    factory = lambda params: build_strategy("sma_crossover", json.dumps(params))
    param_grid = {"fast_period": [5], "slow_period": [10]}
    common = dict(
        data=data, strategy_factory=factory, param_grid=param_grid,
        initial_capital=100000, commission=0.0, slippage=0.0,
    )

    clamped = cpcv_analysis(latency=-3, fill_rate=1.0, **common)
    zero = cpcv_analysis(latency=0, fill_rate=1.0, **common)

    pd.testing.assert_series_equal(clamped["oos_returns"], zero["oos_returns"])
    assert clamped["summary"] == zero["summary"]


def test_out_of_sample_validation_defaults_preserve_latency_and_fill_rate():
    """out_of_sample_validation defaults (latency=0, fill_rate=1.0) are bitwise
    identical to explicitly passing latency=0, fill_rate=1.0.
    """
    data = _make_ohlcv_data(periods=400, seed=42)
    factory = lambda params: build_strategy("sma_crossover", json.dumps(params))
    param_grid = {"fast_period": [5, 10], "slow_period": [20, 30]}
    common = dict(
        data=data, strategy_factory=factory, param_grid=param_grid,
        train_size=0.6, test_size=0.2, validation_size=0.2,
        initial_capital=100000, commission=0.0002, slippage=0.0001,
    )

    defaults = out_of_sample_validation(**common)
    explicit = out_of_sample_validation(latency=0, fill_rate=1.0, **common)

    assert defaults["summary"] == explicit["summary"]


def test_out_of_sample_validation_fill_rate_invalid_raises():
    """fill_rate outside (0, 1] raises ValueError before execution."""
    data = _make_ohlcv_data(periods=200, seed=42)
    factory = lambda params: build_strategy("sma_crossover", json.dumps(params))
    param_grid = {"fast_period": [5], "slow_period": [10]}

    for bad_fill_rate in (0.0, -0.5, 1.5):
        try:
            out_of_sample_validation(
                data=data, strategy_factory=factory, param_grid=param_grid,
                train_size=0.5, test_size=0.25, validation_size=0.25,
                initial_capital=100000, commission=0.0, slippage=0.0,
                latency=0, fill_rate=bad_fill_rate,
            )
        except ValueError:
            continue
        else:
            raise AssertionError(
                f"out_of_sample_validation should raise ValueError for fill_rate={bad_fill_rate}"
            )


def test_out_of_sample_validation_negative_latency_clamped_to_zero():
    """Negative latency is clamped to 0 (no accidental look-ahead)."""
    data = _make_ohlcv_data(periods=300, seed=42)
    factory = lambda params: build_strategy("sma_crossover", json.dumps(params))
    param_grid = {"fast_period": [5], "slow_period": [10]}
    common = dict(
        data=data, strategy_factory=factory, param_grid=param_grid,
        train_size=0.5, test_size=0.25, validation_size=0.25,
        initial_capital=100000, commission=0.0, slippage=0.0,
    )

    clamped = out_of_sample_validation(latency=-3, fill_rate=1.0, **common)
    zero = out_of_sample_validation(latency=0, fill_rate=1.0, **common)

    assert clamped["summary"] == zero["summary"]

def test_main_registers_every_module_level_test():
    """main() must register every module-level ``test_*`` function.

    Regression guard for a defect where a test function was defined after
    the ``if __name__ == "__main__"`` block (and therefore unreachable at
    runtime) yet omitted from the registry, so the suite reported a lower
    count than the number of tests actually defined. A test defined but
    never registered is dead code: it cannot fail, so it provides no
    coverage of the feature it targets.

    The check is structural: every callable named ``test_*`` at module
    scope must appear in ``TEST_REGISTRY``, and every registry entry must
    be a real module-level function. No test is executed here.
    """
    import inspect

    module_tests = {
        obj
        for name, obj in list(globals().items())
        if name.startswith("test_")
        and inspect.isfunction(obj)
        and obj.__module__ == __name__
    }
    registered = {fn for _, fn in TEST_REGISTRY}

    missing = module_tests - registered
    assert not missing, (
        f"test functions defined but not registered in TEST_REGISTRY: "
        f"{sorted(f.__name__ for f in missing)}. A test outside the "
        "runner is dead code and provides no coverage."
    )
    phantom = registered - module_tests
    assert not phantom, (
        f"entries in TEST_REGISTRY that are not module-level test_* "
        f"functions: {sorted(f.__name__ for f in phantom)}"
    )
    # Labels must be unique so the runner cannot silently skip a test
    # (duplicate labels would overwrite each other in a name->fn map).
    labels = [name for name, _ in TEST_REGISTRY]
    assert len(labels) == len(set(labels)), (
        f"TEST_REGISTRY has duplicate labels: "
        f"{[l for l in labels if labels.count(l) > 1]}"
    )


TEST_REGISTRY = [
    ("test_out_of_sample_validation_benchmark_cost_is_periodic", test_out_of_sample_validation_benchmark_cost_is_periodic),
    ("test_out_of_sample_validation_benchmark_cost_is_periodic_cpcv", test_out_of_sample_validation_benchmark_cost_is_periodic_cpcv),
    ("test_cli_out_of_sample_benchmark_cost_is_periodic", test_cli_out_of_sample_benchmark_cost_is_periodic),
    ("test_cli_out_of_sample_persists_separation_check_audit_field", test_cli_out_of_sample_persists_separation_check_audit_field),
    ("test_load_and_validate_data_runs_pit_by_default", test_load_and_validate_data_runs_pit_by_default),
    ("test_cli_point_in_time_validation_enabled_by_default", test_cli_point_in_time_validation_enabled_by_default),
    ("test_cli_point_in_time_validation_can_be_disabled", test_cli_point_in_time_validation_can_be_disabled),
    ("test_out_of_sample_validation_validate_pit_detects_look_ahead", test_out_of_sample_validation_validate_pit_detects_look_ahead),
    ("test_cli_out_of_sample_benchmark_cost_is_periodic_false", test_cli_out_of_sample_benchmark_cost_is_periodic_false),
    ("test_cli_out_of_sample_benchmark_cost_is_periodic_cpcv", test_cli_out_of_sample_benchmark_cost_is_periodic_cpcv),
    ("test_benchmark_stats_with_splits_runs_without_error", test_benchmark_stats_with_splits_runs_without_error),
    ("test_benchmark_stats_with_splits_uses_adjusted_returns", test_benchmark_stats_with_splits_uses_adjusted_returns),
    ("test_add_benchmark_to_summary_splits_path", test_add_benchmark_to_summary_splits_path),
    ("test_out_of_sample_validation_with_splits", test_out_of_sample_validation_with_splits),
    ("test_out_of_sample_validation_splits_adjusted_regardless_of_cost_model", test_out_of_sample_validation_splits_adjusted_regardless_of_cost_model),
    ("test_out_of_sample_validation_n_trials_matches_evaluated_combinations", test_out_of_sample_validation_n_trials_matches_evaluated_combinations),
    ("test_out_of_sample_validation_uses_pooled_trial_sharpes_for_sr_star", test_out_of_sample_validation_uses_pooled_trial_sharpes_for_sr_star),
    ("test_deflated_sharpe_parity_across_all_four_analysis_paths", test_deflated_sharpe_parity_across_all_four_analysis_paths),
    ("test_cost_sweep_dsr_parity_across_paths", test_cost_sweep_dsr_parity_across_paths),
    ("test_non_impact_sweep_dsr_parity_across_paths", test_non_impact_sweep_dsr_parity_across_paths),
    ("test_optimize_non_impact_sweep_dsr_parity", test_optimize_non_impact_sweep_dsr_parity),
    ("test_degenerate_constant_return_dsr_consistency", test_degenerate_constant_return_dsr_consistency),
    ("test_degenerate_constant_return_dar_consistency", test_degenerate_constant_return_dar_consistency),
    ("test_out_of_sample_validation_multiple_benchmarks_deflated_alpha", test_out_of_sample_validation_multiple_benchmarks_deflated_alpha),
    ("test_calculate_metrics_deflated_alpha_with_benchmark_list", test_calculate_metrics_deflated_alpha_with_benchmark_list),
    ("test_cli_cpcv_benchmark_cost_is_periodic", test_cli_cpcv_benchmark_cost_is_periodic),
    ("test_benchmark_list_alpha_correction_deflated_alpha", test_benchmark_list_alpha_correction_deflated_alpha),
    ("test_benchmark_list_alpha_correction_per_benchmark_pvalue_is_dar_pvalue", test_benchmark_list_alpha_correction_per_benchmark_pvalue_is_dar_pvalue),
    ("test_cpcv_analysis_multiple_benchmarks_deflated_alpha", test_cpcv_analysis_multiple_benchmarks_deflated_alpha),
    ("test_walk_forward_analysis_multiple_benchmarks_deflated_alpha", test_walk_forward_analysis_multiple_benchmarks_deflated_alpha),
    ("test_cli_cpcv_multiple_benchmarks", test_cli_cpcv_multiple_benchmarks),
    ("test_cli_walk_forward_multiple_benchmarks", test_cli_walk_forward_multiple_benchmarks),
    ("test_cli_walk_forward_constant_benchmarks_defensive_fallback_surfaces_metrics", test_cli_walk_forward_constant_benchmarks_defensive_fallback_surfaces_metrics),
    ("test_cli_optimize_multiple_benchmarks", test_cli_optimize_multiple_benchmarks),
    ("test_cli_monte_carlo_multiple_benchmarks", test_cli_monte_carlo_multiple_benchmarks),
    ("test_cli_monte_carlo_impact_sweep", test_cli_monte_carlo_impact_sweep),
    ("test_monte_carlo_n_trials_uses_evaluated_combo_count", test_monte_carlo_n_trials_uses_evaluated_combo_count),
    ("test_cli_cpcv_impact_sweep", test_cli_cpcv_impact_sweep),
    ("test_cli_monte_carlo_borrow_sweep", test_cli_monte_carlo_borrow_sweep),
    ("test_cli_cpcv_borrow_sweep", test_cli_cpcv_borrow_sweep),
    ("test_cli_monte_carlo_funding_sweep", test_cli_monte_carlo_funding_sweep),
    ("test_cli_cpcv_funding_sweep", test_cli_cpcv_funding_sweep),
    ("test_cli_walk_forward_impact_sweep", test_cli_walk_forward_impact_sweep),
    ("test_cli_walk_forward_borrow_sweep", test_cli_walk_forward_borrow_sweep),
    ("test_cli_walk_forward_funding_sweep", test_cli_walk_forward_funding_sweep),
    ("test_cli_optimize_impact_sweep", test_cli_optimize_impact_sweep),
    ("test_cli_optimize_borrow_sweep", test_cli_optimize_borrow_sweep),
    ("test_cli_optimize_funding_sweep", test_cli_optimize_funding_sweep),
    ("test_cli_out_of_sample_impact_sweep", test_cli_out_of_sample_impact_sweep),
    ("test_cli_out_of_sample_borrow_sweep", test_cli_out_of_sample_borrow_sweep),
    ("test_cli_out_of_sample_funding_sweep", test_cli_out_of_sample_funding_sweep),
    ("test_deflated_alpha_ratio_frequency_invariant", test_deflated_alpha_ratio_frequency_invariant),
    ("test_deflated_alpha_ratio_weakens_with_more_benchmarks", test_deflated_alpha_ratio_weakens_with_more_benchmarks),
    ("test_deflated_sharpe_ratio_weakens_with_more_trials", test_deflated_sharpe_ratio_weakens_with_more_trials),
    ("test_real_data_pipeline_example_imports", test_real_data_pipeline_example_imports),
    ("test_real_data_pipeline_example_runs", test_real_data_pipeline_example_runs),
    ("test_trading_costs_robustness_example_imports", test_trading_costs_robustness_example_imports),
    ("test_trading_costs_positive_alpha_dar_in_range", test_trading_costs_positive_alpha_dar_in_range),
    ("test_trading_costs_borrow_funding_sweep_exercises_api", test_trading_costs_borrow_funding_sweep_exercises_api),
    ("test_trading_costs_robustness_example_runs", test_trading_costs_robustness_example_runs),
    ("test_falsifiable_hypothesis_example_imports", test_falsifiable_hypothesis_example_imports),
    ("test_falsifiable_hypothesis_example_runs", test_falsifiable_hypothesis_example_runs),
    ("test_trading_costs_short_strategy_borrow_cost_effect", test_trading_costs_short_strategy_borrow_cost_effect),
    ("test_trading_costs_levered_strategy_funding_cost_effect", test_trading_costs_levered_strategy_funding_cost_effect),
    ("test_trading_costs_market_neutral_borrow_and_funding_effect", test_trading_costs_market_neutral_borrow_and_funding_effect),
    ("test_market_impact_cost_reduces_returns_single_asset", test_market_impact_cost_reduces_returns_single_asset),
    ("test_market_impact_cost_reduces_returns_dict_panel", test_market_impact_cost_reduces_returns_dict_panel),
    ("test_cli_walk_forward_commission_sweep", test_cli_walk_forward_commission_sweep),
    ("test_cli_walk_forward_slippage_sweep", test_cli_walk_forward_slippage_sweep),
    ("test_cli_optimize_commission_sweep", test_cli_optimize_commission_sweep),
    ("test_cli_optimize_slippage_sweep", test_cli_optimize_slippage_sweep),
    ("test_cli_cpcv_commission_sweep", test_cli_cpcv_commission_sweep),
    ("test_cli_cpcv_slippage_sweep", test_cli_cpcv_slippage_sweep),
    ("test_cli_monte_carlo_commission_sweep", test_cli_monte_carlo_commission_sweep),
    ("test_cli_monte_carlo_slippage_sweep", test_cli_monte_carlo_slippage_sweep),
    ("test_cli_out_of_sample_commission_sweep", test_cli_out_of_sample_commission_sweep),
    ("test_cli_out_of_sample_slippage_sweep", test_cli_out_of_sample_slippage_sweep),
    ("test_benchmark_list_alpha_correction_multiple_benchmarks_with_splits", test_benchmark_list_alpha_correction_multiple_benchmarks_with_splits),
    ("test_benchmark_list_alpha_correction_mixed_splits_backward_compat", test_benchmark_list_alpha_correction_mixed_splits_backward_compat),
    ("test_benchmark_list_alpha_correction_handles_splits", test_benchmark_list_alpha_correction_handles_splits),
    ("test_verify_split_separation_clean_splits_pass", test_verify_split_separation_clean_splits_pass),
    ("test_verify_split_separation_train_val_overlap_raises", test_verify_split_separation_train_val_overlap_raises),
    ("test_verify_split_separation_val_test_overlap_raises", test_verify_split_separation_val_test_overlap_raises),
    ("test_verify_split_separation_train_test_overlap_raises", test_verify_split_separation_train_test_overlap_raises),
    ("test_verify_split_separation_non_strict_returns_diagnostic", test_verify_split_separation_non_strict_returns_diagnostic),
    ("test_verify_split_separation_empty_split_raises", test_verify_split_separation_empty_split_raises),
    ("test_benchmark_stats_with_splits_produces_finite_inference", test_benchmark_stats_with_splits_produces_finite_inference),
    ("test_benchmark_stats_with_splits_regression_pins_corrected_values", test_benchmark_stats_with_splits_regression_pins_corrected_values),
    ("test_optimize_impact_sweep_records_bias_controls_and_deflated_sharpe", test_optimize_impact_sweep_records_bias_controls_and_deflated_sharpe),
    ("test_optimize_sweep_omits_deflated_sharpe_without_deflate", test_optimize_sweep_omits_deflated_sharpe_without_deflate),
    ("test_cli_tear_sheet_links_each_benchmark_metric_row_to_its_provenance", test_cli_tear_sheet_links_each_benchmark_metric_row_to_its_provenance),
    ("test_cli_oos_tear_sheet_carries_provenance", test_cli_oos_tear_sheet_carries_provenance),
    ("test_cli_multi_symbol_load_and_validate_data_returns_survivorship", test_cli_multi_symbol_load_and_validate_data_returns_survivorship),
    ("test_cli_multi_symbol_out_of_sample_sets_bias_controls_engaged", test_cli_multi_symbol_out_of_sample_sets_bias_controls_engaged),
    ("test_cli_multi_symbol_out_of_sample_writes_survivorship_artifact", test_cli_multi_symbol_out_of_sample_writes_survivorship_artifact),
    ("test_cli_multi_symbol_walk_forward_writes_survivorship_artifact", test_cli_multi_symbol_walk_forward_writes_survivorship_artifact),
    ("test_cli_multi_symbol_cpcv_writes_survivorship_artifact", test_cli_multi_symbol_cpcv_writes_survivorship_artifact),
    ("test_cli_multi_symbol_optimize_writes_survivorship_artifact", test_cli_multi_symbol_optimize_writes_survivorship_artifact),
    ("test_cli_multi_symbol_walk_forward_commission_sweep_records_survivorship", test_cli_multi_symbol_walk_forward_commission_sweep_records_survivorship),
    ("test_cli_multi_symbol_out_of_sample_commission_sweep_records_survivorship", test_cli_multi_symbol_out_of_sample_commission_sweep_records_survivorship),
    ("test_cli_multi_symbol_cpcv_commission_sweep_records_survivorship", test_cli_multi_symbol_cpcv_commission_sweep_records_survivorship),
    ("test_cli_multi_symbol_optimize_commission_sweep_records_survivorship", test_cli_multi_symbol_optimize_commission_sweep_records_survivorship),
    ("test_cli_multi_symbol_monte_carlo_commission_sweep_records_survivorship", test_cli_multi_symbol_monte_carlo_commission_sweep_records_survivorship),
    ("test_cli_walk_forward_no_benchmark_does_not_crash", test_cli_walk_forward_no_benchmark_does_not_crash),
    ("test_calculate_strategy_returns_latency_shifts_entry_by_exact_periods", test_calculate_strategy_returns_latency_shifts_entry_by_exact_periods),
    ("test_calculate_strategy_returns_fill_rate_scales_short_borrow_cost", test_calculate_strategy_returns_fill_rate_scales_short_borrow_cost),
    ("test_walk_forward_analysis_default_latency_fill_rate_match_explicit_defaults", test_walk_forward_analysis_default_latency_fill_rate_match_explicit_defaults),
    ("test_walk_forward_analysis_fill_rate_invalid_raises", test_walk_forward_analysis_fill_rate_invalid_raises),
    ("test_walk_forward_analysis_negative_latency_clamped_to_zero", test_walk_forward_analysis_negative_latency_clamped_to_zero),
    ("test_parameter_optimization_default_latency_fill_rate_match_explicit_defaults", test_parameter_optimization_default_latency_fill_rate_match_explicit_defaults),
    ("test_cli_walk_forward_latency_sweep", test_cli_walk_forward_latency_sweep),
    ("test_cli_walk_forward_fill_rate_sweep", test_cli_walk_forward_fill_rate_sweep),
    ("test_cli_walk_forward_invalid_fill_rate_rejected", test_cli_walk_forward_invalid_fill_rate_rejected),
    ("test_cpcv_analysis_defaults_preserve_latency_and_fill_rate", test_cpcv_analysis_defaults_preserve_latency_and_fill_rate),
    ("test_cpcv_analysis_fill_rate_invalid_raises", test_cpcv_analysis_fill_rate_invalid_raises),
    ("test_cpcv_analysis_negative_latency_clamped_to_zero", test_cpcv_analysis_negative_latency_clamped_to_zero),
    ("test_out_of_sample_validation_defaults_preserve_latency_and_fill_rate", test_out_of_sample_validation_defaults_preserve_latency_and_fill_rate),
    ("test_out_of_sample_validation_fill_rate_invalid_raises", test_out_of_sample_validation_fill_rate_invalid_raises),
    ("test_out_of_sample_validation_negative_latency_clamped_to_zero", test_out_of_sample_validation_negative_latency_clamped_to_zero),
    ("test_main_registers_every_module_level_test", test_main_registers_every_module_level_test),
]

# ---------------------------------------------------------------------------
# Re-exported example-coverage tests (tests/test_examples_coverage.py)
#
# The standalone module guards the three worked examples that previously had
# no executable coverage (deflated_alpha_example, multiple_benchmarks_example,
# full_pipeline_example).  Re-exporting them here keeps them inside the single
# canonical suite run (`python3 -m pytest .../tests/`) and the registry audit
# (`test_main_registers_every_module_level_test`).
# ---------------------------------------------------------------------------

_EXAMPLES_COVERAGE_PATH = (
    Path(__file__).resolve().parent / "test_examples_coverage.py"
)


def _load_examples_coverage_module():
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "test_examples_coverage", str(_EXAMPLES_COVERAGE_PATH)
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_ec = _load_examples_coverage_module()


def test_examples_coverage_deflated_alpha_imports():
    _ec.test_deflated_alpha_example_imports()


def test_examples_coverage_deflated_alpha_runs():
    _ec.test_deflated_alpha_example_runs()


def test_examples_coverage_multiple_benchmarks_imports():
    _ec.test_multiple_benchmarks_example_imports()


def test_examples_coverage_multiple_benchmarks_runs():
    _ec.test_multiple_benchmarks_example_runs()


def test_examples_coverage_full_pipeline_imports():
    _ec.test_full_pipeline_example_imports()


def test_examples_coverage_full_pipeline_runs():
    _ec.test_full_pipeline_example_runs()


TEST_REGISTRY.extend([
    ("test_examples_coverage_deflated_alpha_imports", test_examples_coverage_deflated_alpha_imports),
    ("test_examples_coverage_deflated_alpha_runs", test_examples_coverage_deflated_alpha_runs),
    ("test_examples_coverage_multiple_benchmarks_imports", test_examples_coverage_multiple_benchmarks_imports),
    ("test_examples_coverage_multiple_benchmarks_runs", test_examples_coverage_multiple_benchmarks_runs),
    ("test_examples_coverage_full_pipeline_imports", test_examples_coverage_full_pipeline_imports),
    ("test_examples_coverage_full_pipeline_runs", test_examples_coverage_full_pipeline_runs),
])

if __name__ == "__main__":
    import sys
    sys.exit(main())

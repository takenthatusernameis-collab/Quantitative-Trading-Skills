#!/usr/bin/env python3
"""
Debug script to test walk_forward_analysis directly
"""

import json
import os
import sys
import tempfile
import traceback
from pathlib import Path

import numpy as np
import pandas as pd

SKILLS_DIR = Path(__file__).resolve().parent / "skills" / "quantitative-backtesting"
sys.path.insert(0, str(SKILLS_DIR / "scripts"))

from walk_forward import (  # noqa: E402
    walk_forward_analysis,
    _make_strategy_factory,
    _calculate_strategy_returns,
)
from strategy_builder import build_strategy  # noqa: E402
from data_loader import load_data  # noqa: E402


def _make_ohlcv_data(periods: int = 100, seed: int = 42) -> pd.DataFrame:
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


def _make_benchmark_data(periods: int = 100, seed: int = 99) -> pd.DataFrame:
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


def debug_walk_forward():
    """Debug walk_forward_analysis directly."""
    # Create test data
    data = _make_ohlcv_data(periods=300, seed=42)
    benchmark = _make_benchmark_data(periods=300, seed=99)

    print(f"Data shape: {data.shape}")
    print(f"Benchmark shape: {benchmark.shape}")

    # Use a simple built-in strategy
    strategy_type = "sma_crossover"
    params = '{"fast_period": 5, "slow_period": 10}'  # Simple params that should work

    # Parameter grid - small grid for testing
    param_grid = {
        "fast_period": [3, 5],
        "slow_period": [8, 10]
    }

    print(f"Param grid: {param_grid}")

    # Test the strategy factory directly
    strategy_factory = _make_strategy_factory(strategy_type)
    print(f"Strategy factory: {strategy_factory}")

    # Test with specific params
    strategy = strategy_factory(json.loads(params))
    print(f"Strategy: {strategy}")

    # Generate signals
    signals = strategy.generate_signals(data)
    print(f"Signals head: {signals.head()}")
    print(f"Signals unique values: {signals.unique()}")
    print(f"Signals active: {(signals.notna() & (signals != 0)).any()}")

    # Calculate returns
    returns = _calculate_strategy_returns(
        data, signals, 0.0002, 0.0001, 0.0, 20, 0.0, 0.0
    )
    print(f"Returns head: {returns.head()}")
    print(f"Returns length: {len(returns)}")
    print(f"Returns std: {returns.std()}")

    # Now test walk_forward_analysis
    print("\n=== Testing walk_forward_analysis ===")
    try:
        result = walk_forward_analysis(
            data=data,
            strategy_factory=strategy_factory,
            param_grid=param_grid,
            train_months=6,
            test_months=2,
            step_months=2,
            initial_capital=100000,
            commission=0.0002,
            slippage=0.0001,
            impact_coefficient=0.0,
            adv_window=20,
            borrow_cost=0.0,
            funding_cost=0.0,
            apply_deflation=False,
            benchmark=benchmark,
            total_return_benchmark=False,
            benchmark_commission=0.001,
            benchmark_slippage=0.001,
            benchmark_expense_ratio=0.0,
            benchmark_cost_is_periodic=False,
        )

        print(f"Walk forward result keys: {result.keys() if result else 'None'}")
        if result:
            print(f"Periods: {len(result.get('periods', []))}")
            print(f"Best params per period: {result.get('best_params_per_period')}")
            print(f"OOS returns length: {len(result.get('oos_returns', []))}")
            print(f"Summary: {result.get('summary')}")
    except Exception as e:
        print(f"Error in walk_forward_analysis: {e}")
        traceback.print_exc()


if __name__ == "__main__":
    debug_walk_forward()
#!/usr/bin/env python3
"""
Debug script to test strategy signals directly
"""

import json
import os
import sys
import tempfile
import traceback
from pathlib import Path

# Add the scripts directory to the path
SKILLS_DIR = Path(__file__).resolve().parent / "skills" / "quantitative-backtesting"
sys.path.insert(0, str(SKILLS_DIR / "scripts"))

import numpy as np
import pandas as pd

from strategy_builder import build_strategy  # noqa: E402
from walk_forward import _calculate_strategy_returns, signals_active


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


def debug_strategy():
    """Debug strategy signals directly."""
    # Create test data
    data = _make_ohlcv_data(periods=100, seed=42)

    print(f"Data shape: {data.shape}")
    print(f"Data head:\n{data.head()}")
    print(f"Data tail:\n{data.tail()}")

    # Use a simple built-in strategy
    strategy_type = "sma_crossover"
    params = '{"fast_period": 5, "slow_period": 10}'  # Simple params that should work

    print(f"\n=== Testing strategy: {strategy_type} with params {params} ===")

    # Build strategy
    strategy = build_strategy(strategy_type, params)
    print(f"Strategy: {strategy}")

    # Generate signals
    signals = strategy.generate_signals(data)
    print(f"Signals head:\n{signals.head()}")
    print(f"Signals tail:\n{signals.tail()}")
    print(f"Signals unique values: {signals.unique()}")
    print(f"Signals is_active: {signals_active(signals)}")

    # Calculate returns
    returns = _calculate_strategy_returns(
        data, signals, 0.0002, 0.0001, 0.0, 20, 0.0, 0.0
    )
    print(f"\nReturns head:\n{returns.head()}")
    print(f"Returns tail:\n{returns.tail()}")
    print(f"Returns length: {len(returns)}")
    print(f"Returns std: {returns.std()}")
    print(f"Returns mean: {returns.mean()}")

    # Try different parameters
    print(f"\n=== Testing different parameters ===")
    test_params = [
        '{"fast_period": 3, "slow_period": 5}',
        '{"fast_period": 2, "slow_period": 3}',
        '{"fast_period": 10, "slow_period": 20}',
    ]

    for param_str in test_params:
        print(f"\nTesting {strategy_type} with params {param_str}")
        try:
            strategy = build_strategy(strategy_type, param_str)
            signals = strategy.generate_signals(data)
            active = signals_active(signals)
            print(f"  Signals active: {active}")
            if active:
                returns = _calculate_strategy_returns(
                    data, signals, 0.0002, 0.0001, 0.0, 20, 0.0, 0.0
                )
                print(f"  Returns length: {len(returns)}, std: {returns.std()}")
        except Exception as e:
            print(f"  Error: {e}")


if __name__ == "__main__":
    debug_strategy()
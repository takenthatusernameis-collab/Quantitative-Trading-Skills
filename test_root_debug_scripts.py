#!/usr/bin/env python3
"""
Regression guard for root debug scripts.
"""

from __future__ import annotations

import json
import sys
import traceback
from pathlib import Path

import numpy as np
import pandas as pd


REPO_ROOT = Path(__file__).resolve().parent
SKILLS_DIR = REPO_ROOT / "skills" / "quantitative-backtesting"
SCRIPTS_DIR = SKILLS_DIR / "scripts"


def _make_ohlcv_data(periods: int = 200, seed: int = 123) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    dates = pd.date_range("2020-01-01", periods=periods, freq="B")
    trend = np.linspace(0, 0.25, periods)
    noise = rng.normal(0, 0.01, periods)
    returns = trend / periods + noise
    prices = 100 * np.exp(np.cumsum(returns))
    return pd.DataFrame(
        {
            "open": prices * rng.uniform(0.995, 1.005, periods),
            "high": prices * rng.uniform(1.005, 1.015, periods),
            "low": prices * rng.uniform(0.985, 0.995, periods),
            "close": prices,
            "volume": rng.integers(1_000_000, 5_000_000, periods),
        },
        index=dates,
    )


def _make_benchmark_data(periods: int = 200, seed: int = 456) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    dates = pd.date_range("2020-01-01", periods=periods, freq="B")
    trend = np.linspace(0, 0.15, periods)
    noise = rng.normal(0, 0.008, periods)
    returns = trend / periods + noise
    prices = 100 * np.exp(np.cumsum(returns))
    return pd.DataFrame(
        {
            "open": prices * rng.uniform(0.995, 1.005, periods),
            "high": prices * rng.uniform(1.005, 1.015, periods),
            "low": prices * rng.uniform(0.985, 0.995, periods),
            "close": prices,
            "volume": rng.integers(1_000_000, 5_000_000, periods),
        },
        index=dates,
    )


def test_debug_strategy_imports_and_runs():
    sys.path.insert(0, str(SCRIPTS_DIR))
    try:
        import debug_strategy  # type: ignore
        from strategy_builder import build_strategy
        from walk_forward import _calculate_strategy_returns

        data = _make_ohlcv_data(periods=80, seed=7)
        strategy = build_strategy("sma_crossover", json.dumps({"fast_period": 5, "slow_period": 10}))
        signals = strategy.generate_signals(data)
        assert signals is not None
        returns = _calculate_strategy_returns(
            data, signals, 0.0002, 0.0001, 0.0, 20, 0.0, 0.0
        )
        assert returns is not None
        assert len(returns) > 0
    finally:
        if str(SCRIPTS_DIR) in sys.path:
            sys.path.remove(str(SCRIPTS_DIR))


def test_debug_walk_forward_imports_and_runs():
    sys.path.insert(0, str(SCRIPTS_DIR))
    try:
        import debug_walk_forward  # type: ignore

        data = _make_ohlcv_data(periods=160, seed=11)
        benchmark = _make_benchmark_data(periods=160, seed=22)
        strategy_factory = debug_walk_forward._make_strategy_factory("sma_crossover")
        param_grid = {"fast_period": [3, 5], "slow_period": [8, 10]}
        result = debug_walk_forward.walk_forward_analysis(
            data=data,
            strategy_factory=strategy_factory,
            param_grid=param_grid,
            train_months=3,
            test_months=1,
            step_months=1,
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
        assert result is not None
        assert "oos_returns" in result or "periods" in result
    finally:
        if str(SCRIPTS_DIR) in sys.path:
            sys.path.remove(str(SCRIPTS_DIR))


TEST_REGISTRY = [
    ("test_debug_strategy_imports_and_runs", test_debug_strategy_imports_and_runs),
    ("test_debug_walk_forward_imports_and_runs", test_debug_walk_forward_imports_and_runs),
]


def main() -> int:
    failures = 0
    for name, fn in TEST_REGISTRY:
        try:
            fn()
            print(f"PASS  {name}")
        except Exception:
            failures += 1
            print(f"FAIL  {name}")
            traceback.print_exc()
    print(f"\n{len(TEST_REGISTRY) - failures}/{len(TEST_REGISTRY)} tests passed")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())

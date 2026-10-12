#!/usr/bin/env python3
"""
Unit tests for strategy_builder.py: the strategy factory and registry.

Run with: python3 skills/quantitative-backtesting/tests/test_strategy_builder.py
No third-party test framework is required; uses only the standard library.
"""

import sys
import traceback
from pathlib import Path

import numpy as np
import pandas as pd

SKILLS_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SKILLS_DIR / "scripts"))

from strategy_builder import (  # noqa: E402
    STRATEGY_REGISTRY,
    build_strategy,
    get_strategy_defaults,
    list_strategies,
)


def _make_data(periods: int = 300, seed: int = 42) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    dates = pd.date_range("2020-01-01", periods=periods, freq="B")
    rets = rng.normal(0.0005, 0.015, periods)
    prices = 100 * np.exp(np.cumsum(rets))
    return pd.DataFrame(
        {
            "open": prices * rng.uniform(0.995, 1.005, periods),
            "high": prices * rng.uniform(1.005, 1.02, periods),
            "low": prices * rng.uniform(0.98, 0.995, periods),
            "close": prices,
            "volume": rng.integers(1_000_000, 10_000_000, periods),
        },
        index=dates,
    )


def test_build_strategy_unknown_type_raises():
    """Unknown strategy types must raise a descriptive ValueError."""
    try:
        build_strategy("does_not_exist")
        assert False, "Expected ValueError for unknown strategy"
    except ValueError as e:
        assert "Unknown strategy" in str(e), f"unexpected message: {e}"


def test_build_strategy_parses_params():
    """params_json is parsed into the strategy parameters."""
    strategy = build_strategy("sma_crossover", '{"fast_period": 7, "slow_period": 21}')
    assert strategy.name == "sma_crossover"
    assert strategy.parameters == {"fast_period": 7, "slow_period": 21}

    bare = build_strategy("sma_crossover")
    assert bare.parameters == {}


def test_registry_listing_and_defaults_agree():
    """list_strategies covers the registry; defaults exist for each entry."""
    assert set(list_strategies()) == set(STRATEGY_REGISTRY)
    for name in STRATEGY_REGISTRY:
        assert get_strategy_defaults(name), f"missing defaults: {name}"
    assert get_strategy_defaults("does_not_exist") == {}


def test_all_registered_strategies_generate_valid_signals():
    """Every registered strategy emits signals in {-1, 0, 1} on the data index."""
    data = _make_data()
    for name in STRATEGY_REGISTRY:
        strategy = build_strategy(name)
        signals = strategy.generate_signals(data)
        assert signals.index.equals(data.index), f"{name}: index mismatch"
        assert set(signals.unique()).issubset({-1, 0, 1}), (
            f"{name}: invalid signal values {signals.unique()}"
        )


def test_sma_crossover_signals_are_binary_with_crossovers():
    """SMA crossover signals are 0/1 and cross over within the window."""
    data = _make_data()
    strategy = build_strategy("sma_crossover", '{"fast_period": 10, "slow_period": 30}')
    signals = strategy.generate_signals(data)

    assert set(signals.unique()).issubset({0, 1})
    # fast < slow over a long window must produce at least one crossover
    assert (signals.diff() != 0).sum() > 0


def main() -> int:
    tests = [
        ("build_strategy_unknown_type_raises", test_build_strategy_unknown_type_raises),
        ("build_strategy_parses_params", test_build_strategy_parses_params),
        ("registry_listing_and_defaults_agree", test_registry_listing_and_defaults_agree),
        ("all_registered_strategies_generate_valid_signals", test_all_registered_strategies_generate_valid_signals),
        ("sma_crossover_signals_are_binary_with_crossovers", test_sma_crossover_signals_are_binary_with_crossovers),
    ]

    failures = 0
    for name, fn in tests:
        try:
            fn()
            print(f"PASS  {name}")
        except Exception:
            failures += 1
            print(f"FAIL  {name}")
            traceback.print_exc()

    print(f"\n{len(tests) - failures}/{len(tests)} tests passed")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())

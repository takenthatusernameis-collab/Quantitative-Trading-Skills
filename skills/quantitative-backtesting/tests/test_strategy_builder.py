import json
import sys
import traceback
from typing import Dict

import pandas as pd

# StrategyBuilder uses relative imports when run as module
try:
    from ..scripts.strategy_builder import (
        build_strategy,
        get_strategy_defaults,

        list_strategies,
    )
except ImportError:  # fallback for direct execution
    sys.path.insert(0, "..")
    from scripts.strategy_builder import (
        build_strategy,
        get_strategy_defaults,

        list_strategies,
    )


def _make_data(n=200):
    dates = pd.date_range("2019-01-01", periods=n, freq="D")
    prices = pd.Series([100 + i * 0.01 + (i % 10) * 0.05 for i in range(n)])
    df = pd.DataFrame(
        {
            "open": prices,
            "high": prices + 0.5,
            "low": prices - 0.5,
            "close": prices,
            "volume": [1000000] * n,
        },
        index=dates,
    )
    return df


def test_build_strategy_unknown_type_raises():
    try:
        build_strategy("nonexistent", "{}")
        assert False, "Expected ValueError"
    except ValueError:
        pass


def test_build_strategy_parses_params():
    s = build_strategy("sma_crossover", '{"fast_period": 5, "slow_period": 15}')
    assert s.parameters["fast_period"] == 5
    assert s.parameters["slow_period"] == 15


def test_registry_listing_and_defaults_agree():
    strategies = list_strategies()
    assert "sma_crossover" in strategies
    assert "donchian_breakout" in strategies
    assert "cross_sectional_momentum" in strategies
    assert "rsi_mean_reversion" in strategies

    for name in strategies:
        params = get_strategy_defaults(name)
        assert isinstance(params, dict)
        s = build_strategy(name, json.dumps(params))
        assert s.name == name


def test_all_registered_strategies_generate_valid_signals():
    data = _make_data()
    for name in list_strategies():
        params = get_strategy_defaults(name)
        s = build_strategy(name, json.dumps(params))
        signals = s.generate_signals(data)
        # Signals must be in {0,1} and same index/length as data
        assert set(signals.unique()).issubset({0, 1, pd.NA if signals.isna().any() else 0})
        assert len(signals) == len(data)
        assert signals.index.equals(data.index)


def test_sma_crossover_signals_are_binary_with_crossovers():
    data = _make_data()
    strategy = build_strategy("sma_crossover", '{"fast_period": 10, "slow_period": 30}')
    signals = strategy.generate_signals(data)

    assert set(signals.unique()).issubset({0, 1})
    # fast < slow over a long window must produce at least one crossover
    assert (signals.diff() != 0).sum() > 0


def test_donchian_breakout_uses_prior_period_high():
    """Donchian channel breakout uses prior N-period high (shifted)."""
    dates = pd.date_range("2020-01-01", periods=6, freq="D")
    data = pd.DataFrame(
        {
            "open": [100] * 6,
            "high": [100, 101, 102, 103, 104, 105],
            "low": [99] * 6,
            "close": [100] * 6,
            "volume": [1000000] * 6,
        },
        index=dates,
    )
    strat = build_strategy("donchian_breakout", '{"period": 5}')
    signals = strat.generate_signals(data)
    assert signals.iloc[0] == 0
    assert signals.iloc[-1] == 1
    assert signals.iloc[4] == 0  # channel not fully formed before shift gives defined value


def main() -> int:
    tests = [
        ("build_strategy_unknown_type_raises", test_build_strategy_unknown_type_raises),
        ("build_strategy_parses_params", test_build_strategy_parses_params),
        ("registry_listing_and_defaults_agree", test_registry_listing_and_defaults_agree),
        ("all_registered_strategies_generate_valid_signals", test_all_registered_strategies_generate_valid_signals),
        ("sma_crossover_signals_are_binary_with_crossovers", test_sma_crossover_signals_are_binary_with_crossovers),
        ("donchian_breakout_uses_prior_period_high", test_donchian_breakout_uses_prior_period_high),
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

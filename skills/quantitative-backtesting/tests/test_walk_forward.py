#!/usr/bin/env python3
"""
Unit tests for walk_forward.py: parameter_optimization and walk_forward_analysis.

Run with: python3 skills/quantitative-backtesting/tests/test_walk_forward.py
No third-party test framework is required; uses only the standard library.
"""

import sys
import traceback
from pathlib import Path

import numpy as np
import pandas as pd

SKILLS_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SKILLS_DIR / "scripts"))

from walk_forward import (  # noqa: E402
    overfitting_check,
    parameter_optimization,
    walk_forward_analysis,
)
from strategy_builder import build_strategy  # noqa: E402


def _make_data(periods: int = 756, seed: int = 42) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    dates = pd.date_range("2018-01-01", periods=periods, freq="B")
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


def _factory(strategy_type: str, params: dict):
    import json

    return build_strategy(strategy_type, json.dumps(params))


def test_parameter_optimization_skips_flat_combos():
    """Combos that take no position (lookback >= window) must be skipped."""
    data = _make_data()
    results = parameter_optimization(
        data=data,
        strategy_factory=lambda p: _factory("sma_crossover", p),
        param_grid={"fast_period": [10, 20, 50], "slow_period": [50, 100, 200]},
    )

    assert len(results) > 0, "expected at least one valid combo"
    for r in results:
        assert r["total_return"] != 0.0 or r["sharpe_ratio"] != 0.0, (
            f"flat combo leaked through: {r['params']}"
        )
    # fast == slow is flat and must be absent
    flat_params = {"fast_period": 50, "slow_period": 50}
    assert flat_params not in [r["params"] for r in results], (
        "flat combo (fast==slow) was not skipped"
    )


def test_walk_forward_skips_flat_combos_in_test_window():
    """A slow_period longer than the test window must not be selected."""
    data = _make_data()
    results = walk_forward_analysis(
        data=data,
        strategy_factory=lambda p: _factory("sma_crossover", p),
        param_grid={"fast_period": [10, 20, 50], "slow_period": [50, 100, 200]},
        train_months=12,
        test_months=3,
        step_months=3,
    )

    assert results["summary"]["n_periods"] > 0, "expected walk-forward periods"
    for period in results["periods"]:
        params = period.get("best_params")
        if params is None:
            continue
        assert params.get("slow_period", 0) < 64, (
            f"selected slow_period {params['slow_period']} exceeds test window"
        )


def test_overfitting_check_handles_empty_oos():
    """overfitting_check must not crash on empty out-of-sample returns."""
    data = _make_data()
    wf = walk_forward_analysis(
        data=data,
        strategy_factory=lambda p: _factory("sma_crossover", p),
        param_grid={"fast_period": [10, 20, 50], "slow_period": [50, 100, 200]},
    )
    diagnostics = overfitting_check(wf)
    assert "overfitting_risk" in diagnostics
    assert diagnostics["overfitting_risk"] in {"low", "medium", "high"}


def main() -> int:
    tests = [
        ("parameter_optimization_skips_flat_combos", test_parameter_optimization_skips_flat_combos),
        ("walk_forward_skips_flat_combos_in_test_window", test_walk_forward_skips_flat_combos_in_test_window),
        ("overfitting_check_handles_empty_oos", test_overfitting_check_handles_empty_oos),
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
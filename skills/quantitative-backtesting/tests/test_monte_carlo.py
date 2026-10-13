#!/usr/bin/env python3
"""
Unit tests for the standalone monte_carlo.py module.

Run with: python3 skills/quantitative-backtesting/tests/test_monte_carlo.py
No third-party test framework is required; uses only the standard library.

These tests exercise the new standalone module directly
(`from monte_carlo import monte_carlo_simulation`) rather than the
walk_forward re-export, so they guard the extraction itself. The
walk_forward re-export is covered by test_walk_forward.py, which still
passes unchanged.
"""

import sys
import traceback
from pathlib import Path

import numpy as np
import pandas as pd

SKILLS_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SKILLS_DIR / "scripts"))

from monte_carlo import monte_carlo_simulation  # noqa: E402


def _make_returns(periods: int = 252, seed: int = 42) -> pd.Series:
    rng = np.random.default_rng(seed)
    dates = pd.date_range("2020-01-01", periods=periods, freq="B")
    return pd.Series(rng.normal(0.0005, 0.015, periods), index=dates)


def test_standalone_module_structure():
    """monte_carlo_simulation is importable from the standalone module."""
    assert callable(monte_carlo_simulation)


def test_standalone_basic_structure():
    """monte_carlo_simulation runs and returns expected structure."""
    returns = _make_returns()
    mc = monte_carlo_simulation(
        base_returns=returns,
        n_simulations=50,
        confidence_levels=[0.90, 0.95],
    )

    assert "simulated_equity_curves" in mc
    assert "metric_distributions" in mc
    assert "confidence_intervals" in mc
    assert "probability_of_ruin" in mc
    assert "summary" in mc
    assert mc["n_simulations"] == 50
    assert mc["base_observations"] == len(returns)
    assert len(mc["simulated_equity_curves"]) == 50

    expected_metrics = [
        "total_return", "annualized_return", "annualized_volatility",
        "sharpe_ratio", "sortino_ratio", "max_drawdown", "calmar_ratio",
    ]
    for metric in expected_metrics:
        assert metric in mc["metric_distributions"], f"missing metric: {metric}"
        assert metric in mc["confidence_intervals"], f"missing CI for: {metric}"
        assert metric in mc["summary"], f"missing summary for: {metric}"
        for level in [0.90, 0.95]:
            assert level in mc["confidence_intervals"][metric]
            lower, upper = mc["confidence_intervals"][metric][level]
            assert lower <= upper, f"CI bounds inverted for {metric}"


def test_standalone_block_bootstrap():
    """monte_carlo_simulation works with block_size parameter."""
    returns = _make_returns()
    mc = monte_carlo_simulation(
        base_returns=returns,
        n_simulations=50,
        block_size=10,
    )

    assert mc["n_simulations"] == 50
    assert len(mc["simulated_equity_curves"]) == 50
    for metric in mc["metric_distributions"]:
        vals = mc["metric_distributions"][metric]
        assert len(vals) == 50
        assert not np.any(np.isnan(vals))


def test_standalone_probability_of_ruin():
    """Probability of ruin is between 0 and 1."""
    returns = _make_returns()
    mc = monte_carlo_simulation(base_returns=returns, n_simulations=200)
    prob_ruin = mc["probability_of_ruin"]
    assert 0.0 <= prob_ruin <= 1.0
    assert mc["ruin_threshold"] == 0.5


def test_standalone_short_series_raises():
    """Monte Carlo should raise ValueError for too few observations."""
    returns = pd.Series([0.01], index=pd.date_range("2020-01-01", periods=1, freq="B"))
    try:
        monte_carlo_simulation(base_returns=returns, n_simulations=10)
        assert False, "Expected ValueError for < 2 observations"
    except ValueError as e:
        assert "at least 2 return observations" in str(e)


def test_standalone_matches_walk_forward_re_export():
    """The standalone function and the walk_forward re-export are identical."""
    from walk_forward import monte_carlo_simulation as wf_mc  # noqa: E402

    assert monte_carlo_simulation is wf_mc, (
        "walk_forward.monte_carlo_simulation must be the same object as "
        "monte_carlo.monte_carlo_simulation (re-export, not a copy)"
    )


def test_standalone_reproducible_structure():
    """The standalone module is reproducible in shape across runs.

    Monte Carlo uses the global RNG (no seed argument), so the exact
    values differ between runs; what is invariant is the output
    structure and the fact that every metric distribution has the
    requested number of simulations.
    """
    returns = _make_returns(periods=252, seed=7)
    mc1 = monte_carlo_simulation(base_returns=returns, n_simulations=20)
    mc2 = monte_carlo_simulation(base_returns=returns, n_simulations=20)

    assert set(mc1["metric_distributions"].keys()) == set(mc2["metric_distributions"].keys())
    for metric in mc1["metric_distributions"]:
        assert len(mc1["metric_distributions"][metric]) == 20
        assert len(mc2["metric_distributions"][metric]) == 20
        assert not np.any(np.isnan(mc1["metric_distributions"][metric]))
        assert not np.any(np.isnan(mc2["metric_distributions"][metric]))


def main() -> int:
    tests = [
        ("standalone_module_structure", test_standalone_module_structure),
        ("standalone_basic_structure", test_standalone_basic_structure),
        ("standalone_block_bootstrap", test_standalone_block_bootstrap),
        ("standalone_probability_of_ruin", test_standalone_probability_of_ruin),
        ("standalone_short_series_raises", test_standalone_short_series_raises),
        ("standalone_matches_walk_forward_re_export", test_standalone_matches_walk_forward_re_export),
        ("standalone_reproducible_structure", test_standalone_reproducible_structure),
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
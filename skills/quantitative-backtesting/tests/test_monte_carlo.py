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

from monte_carlo import monte_carlo_simulation, estimate_optimal_block_size, _annualization_factor  # noqa: E402


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


def test_estimate_optimal_block_size_basic():
    """estimate_optimal_block_size returns a valid block size."""
    returns = _make_returns(periods=252)
    b = estimate_optimal_block_size(returns)
    assert isinstance(b, int)
    assert 2 <= b <= len(returns) // 2


def test_estimate_optimal_block_size_ar1_vs_politis_white():
    """AR(1) and Politis-White methods produce different (but valid) results."""
    returns = _make_returns(periods=500)
    b_ar1 = estimate_optimal_block_size(returns, method="simple_ar1")
    b_pw = estimate_optimal_block_size(returns, method="politis_white_2004")
    assert isinstance(b_ar1, int)
    assert isinstance(b_pw, int)
    assert 2 <= b_ar1 <= len(returns) // 2
    assert 2 <= b_pw <= len(returns) // 2


def test_estimate_optimal_block_size_short_series():
    """Short series returns minimum block size."""
    returns = _make_returns(periods=5)
    b = estimate_optimal_block_size(returns)
    assert b == 2


def test_estimate_optimal_block_size_zero_variance():
    """Constant returns (zero variance) returns minimum block size."""
    returns = pd.Series([0.0] * 100, index=pd.date_range("2020-01-01", periods=100, freq="B"))
    b = estimate_optimal_block_size(returns)
    assert b == 2


def test_monte_carlo_auto_block_size():
    """monte_carlo_simulation with block_size='auto' estimates and uses optimal block size."""
    returns = _make_returns(periods=252)
    mc = monte_carlo_simulation(
        base_returns=returns,
        n_simulations=50,
        block_size="auto",
    )
    assert "block_size_used" in mc
    assert mc["block_size_used"] is not None
    assert isinstance(mc["block_size_used"], int)
    assert mc["block_size_used"] >= 2
    assert mc["n_simulations"] == 50


def test_monte_carlo_auto_block_size_reproducible():
    """Auto block size is deterministic for same input (uses same algorithm)."""
    returns = _make_returns(periods=252, seed=42)
    mc1 = monte_carlo_simulation(base_returns=returns, n_simulations=20, block_size="auto")
    mc2 = monte_carlo_simulation(base_returns=returns, n_simulations=20, block_size="auto")
    assert mc1["block_size_used"] == mc2["block_size_used"]


def test_monte_carlo_block_size_none_vs_auto_different():
    """i.i.d. bootstrap (None) and auto block bootstrap produce different distributions."""
    returns = _make_returns(periods=500)
    mc_iid = monte_carlo_simulation(base_returns=returns, n_simulations=200, block_size=None)
    mc_auto = monte_carlo_simulation(base_returns=returns, n_simulations=200, block_size="auto")

    # They should both run successfully
    assert mc_iid["n_simulations"] == 200
    assert mc_auto["n_simulations"] == 200
    assert mc_iid["block_size_used"] is None
    assert mc_auto["block_size_used"] is not None

    # The Sharpe ratio distributions should differ (block bootstrap preserves autocorrelation)
    sharpe_iid = np.array(mc_iid["metric_distributions"]["sharpe_ratio"])
    sharpe_auto = np.array(mc_auto["metric_distributions"]["sharpe_ratio"])
    # At minimum, they should not be identical arrays
    assert not np.allclose(sharpe_iid, sharpe_auto)


def test_standalone_no_nan_on_bust_paths():
    """Monte Carlo must not emit NaN on paths that bust (growth <= 0).

    A simulated equity curve whose cumulative product drops to zero or
    below has a non-positive growth factor; ``growth ** (ann_factor / n_obs)``
    is NaN (or complex) in that case. The simulation must still emit a finite
    annualized return (NaN) rather than polluting the whole distribution, and
    the summary mean must equal the plain numpy mean of the distribution
    (no silent NaN-skipping that would hide the count of bust paths).
    """
    rng = np.random.default_rng(11)
    dates = pd.date_range("2020-01-01", periods=252, freq="B")
    # Strong negative drift: most simulated paths bust (cumulative equity
    # drops below zero), which is exactly the regime the NaN guard targets.
    returns = pd.Series(rng.normal(-0.015, 0.015, 252), index=dates)

    # Pass an explicit seed: monte_carlo_simulation falls back to the global
    # numpy RNG when seed is None, so without a seed the draws depend on
    # whatever earlier tests in the suite left in the global RNG state and
    # the bust-path count is not reproducible across runs.
    mc = monte_carlo_simulation(base_returns=returns, n_simulations=500, seed=11)
    arr = mc["metric_distributions"]["annualized_return"]
    total = mc["metric_distributions"]["total_return"]

    assert not np.any(np.isnan(arr)), (
        f"annualized_return contained NaN on bust paths: "
        f"{int(np.isnan(arr).sum())}/{len(arr)}"
    )
    assert not np.any(np.isinf(arr)), (
        f"annualized_return contained inf on bust paths: "
        f"{int(np.isinf(arr).sum())}/{len(arr)}"
    )
    # Bust paths are real: at least some simulated total returns must be
    # strongly negative (the regime the guard exists for).
    assert (total < -0.5).any(), (
        "expected at least one simulated path to bust (total_return < -0.5) "
        "with this drift; the test does not exercise the guard otherwise"
    )
    # Summary mean must reconcile with the distribution (no NaN-skipping).
    assert mc["summary"]["annualized_return"]["mean"] == float(np.mean(arr)), (
        "summary annualized_return mean must equal np.mean of the distribution"
    )
    assert mc["summary"]["annualized_return"]["std"] == float(np.std(arr)), (
        "summary annualized_return std must equal np.std of the distribution"
    )


def test_standalone_no_nan_on_extreme_single_move():
    """A single return below -1 must not produce NaN annualized returns.

    Resampling can place an extreme negative move (e.g. -1.5) into a path,
    making the cumulative equity negative. The annualized return must stay
    finite across all simulations.
    """
    rng = np.random.default_rng(21)
    dates = pd.date_range("2020-01-01", periods=252, freq="B")
    base = pd.Series(rng.normal(0.001, 0.02, 252), index=dates)
    base.iloc[50] = -1.5  # extreme single-period move

    mc = monte_carlo_simulation(base_returns=base, n_simulations=500)
    arr = mc["metric_distributions"]["annualized_return"]
    assert not np.any(np.isnan(arr)), (
        f"annualized_return contained NaN with a sub -1 base return: "
        f"{int(np.isnan(arr).sum())}/{len(arr)}"
    )


def test_annualization_factor_known_frequencies():
    """_annualization_factor maps known frequencies and defaults to 252.

    Regression guard for the pandas 3.x fix: the standalone monte_carlo
    module previously used uppercase freq_map keys and first-char
    matching, so hourly ("h") and minutely ("min") defaulted to 252
    instead of 1638 and 98280, and "min" collided with month ("M"/"ME").
    """
    cases = {
        "B": 252,
        "D": 365,
        "W": 52,
        "ME": 12,
        "MS": 12,
        "QE-DEC": 4,
        "h": int(252 * 6.5),       # hourly: 252 trading days * 6.5 hours
        "min": int(252 * 6.5 * 60),  # minutely: 252 * 6.5 hours * 60 minutes
    }
    for freq, expected in cases.items():
        idx = pd.date_range("2020-01-01", periods=10, freq=freq)
        assert _annualization_factor(idx) == expected, (
            f"{freq}: expected {expected}, got {_annualization_factor(idx)}"
        )


def test_annualization_factor_minute_does_not_collide_with_month():
    """Minute ("min") and month ("ME"/"MS") must not collide under pandas 3.x.

    "min", "ME", and "MS" all start with "m" in lowercase, so first-char
    matching would map minute to 12 (month). The full-base-alias match
    keeps them distinct: minute -> 98280, month -> 12.
    """
    minute_idx = pd.date_range("2020-01-01", periods=10, freq="min")
    month_start_idx = pd.date_range("2020-01-01", periods=10, freq="MS")
    month_end_idx = pd.date_range("2020-01-01", periods=10, freq="ME")
    assert _annualization_factor(minute_idx) == int(252 * 6.5 * 60)
    assert _annualization_factor(month_start_idx) == 12
    assert _annualization_factor(month_end_idx) == 12
    assert _annualization_factor(minute_idx) != _annualization_factor(month_start_idx)
    assert _annualization_factor(minute_idx) != _annualization_factor(month_end_idx)


def test_annualization_factor_non_datetime_index():
    """Non-DatetimeIndex defaults to 252 trading days."""
    assert _annualization_factor(pd.Index(range(10))) == 252


def test_main_registers_every_module_level_test():
    """main() must register every module-level ``test_*`` function.

    Regression guard for a defect where a test function was defined but
    omitted from the runner's registry, so the suite reported a lower
    count than the number of tests actually defined. A test defined but
    never registered is dead code: it cannot fail, so it provides no
    coverage of the feature it targets. This is a structural check: no
    test is executed here.

    In this file the guard specifically protects the Monte Carlo bust-path
    invariant: simulated paths where equity is wiped out (growth <= 0)
    must not emit NaN in ``annualized_return``, or the whole distribution,
    summary mean/std, and confidence intervals collapse to NaN. Those tests
    must remain registered.
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


def main() -> int:
    tests = TEST_REGISTRY
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


TEST_REGISTRY = [
    ("standalone_module_structure", test_standalone_module_structure),
    ("standalone_basic_structure", test_standalone_basic_structure),
    ("standalone_block_bootstrap", test_standalone_block_bootstrap),
    ("standalone_probability_of_ruin", test_standalone_probability_of_ruin),
    ("standalone_short_series_raises", test_standalone_short_series_raises),
    ("standalone_matches_walk_forward_re_export", test_standalone_matches_walk_forward_re_export),
    ("standalone_reproducible_structure", test_standalone_reproducible_structure),
    ("estimate_optimal_block_size_basic", test_estimate_optimal_block_size_basic),
    ("estimate_optimal_block_size_ar1_vs_politis_white", test_estimate_optimal_block_size_ar1_vs_politis_white),
    ("estimate_optimal_block_size_short_series", test_estimate_optimal_block_size_short_series),
    ("estimate_optimal_block_size_zero_variance", test_estimate_optimal_block_size_zero_variance),
    ("monte_carlo_auto_block_size", test_monte_carlo_auto_block_size),
    ("monte_carlo_auto_block_size_reproducible", test_monte_carlo_auto_block_size_reproducible),
    ("monte_carlo_block_size_none_vs_auto_different", test_monte_carlo_block_size_none_vs_auto_different),
    ("test_standalone_no_nan_on_bust_paths", test_standalone_no_nan_on_bust_paths),
    ("test_standalone_no_nan_on_extreme_single_move", test_standalone_no_nan_on_extreme_single_move),
    ("annualization_factor_known_frequencies", test_annualization_factor_known_frequencies),
    ("annualization_factor_minute_does_not_collide_with_month", test_annualization_factor_minute_does_not_collide_with_month),
    ("annualization_factor_non_datetime_index", test_annualization_factor_non_datetime_index),
    ("test_main_registers_every_module_level_test", test_main_registers_every_module_level_test),
]

if __name__ == "__main__":
    sys.exit(main())
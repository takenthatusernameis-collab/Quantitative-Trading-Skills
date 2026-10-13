#!/usr/bin/env python3
"""
Unit tests for walk_forward.py: parameter_optimization and walk_forward_analysis.

Run with: python3 skills/quantitative-backtesting/tests/test_walk_forward.py
No third-party test framework is required; uses only the standard library.
"""

import json
import sys
import tempfile
import traceback
from pathlib import Path

import numpy as np
import pandas as pd

SKILLS_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SKILLS_DIR / "scripts"))

from walk_forward import (  # noqa: E402
    overfitting_check,
    parameter_optimization,
    signals_active,
    walk_forward_analysis,
    monte_carlo_simulation,
    run_walk_forward,
    run_parameter_optimization,
    run_monte_carlo,
    _make_strategy_factory,
    _parse_param_grid,
)
from strategy_builder import build_strategy  # noqa: E402
from data_loader import load_data  # noqa: E402


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



def _make_multiasset_multiindex(n=500, n_assets=4, seed=42):
    """Create MultiIndex panel data for multi-asset testing."""
    dates = pd.date_range("2020-01-01", periods=n, freq="B")
    symbols = [f"ASSET_{i}" for i in range(n_assets)]
    cols = pd.MultiIndex.from_product([["open", "high", "low", "close", "volume"], symbols])
    df = pd.DataFrame(0, index=dates, columns=cols)
    rng = np.random.default_rng(seed)
    for i, sym in enumerate(symbols):
        drift = 0.0005 * (i + 1)
        rets = rng.normal(drift, 0.01, n)
        prices = 100 * np.exp(np.cumsum(rets))
        df[("open", sym)] = prices * rng.uniform(0.995, 1.005, n)
        df[("high", sym)] = prices * rng.uniform(1.005, 1.02, n)
        df[("low", sym)] = prices * rng.uniform(0.98, 0.995, n)
        df[("close", sym)] = prices
        df[("volume", sym)] = rng.integers(1_000_000, 10_000_000, n)
    return df


def _make_multiasset_dict(n=500, n_assets=4, seed=42):
    """Create dict of DataFrames for multi-asset testing."""
    dates = pd.date_range("2020-01-01", periods=n, freq="B")
    symbols = [f"ASSET_{i}" for i in range(n_assets)]
    data_dict = {}
    rng = np.random.default_rng(seed)
    for i, sym in enumerate(symbols):
        drift = 0.0005 * (i + 1)
        rets = rng.normal(drift, 0.01, n)
        prices = 100 * np.exp(np.cumsum(rets))
        data_dict[sym] = pd.DataFrame({
            "open": prices * rng.uniform(0.995, 1.005, n),
            "high": prices * rng.uniform(1.005, 1.02, n),
            "low": prices * rng.uniform(0.98, 0.995, n),
            "close": prices,
            "volume": rng.integers(1_000_000, 10_000_000, n),
        }, index=dates)
    return data_dict
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


def test_signals_active_detects_flat_and_active_series():
    """signals_active returns False for all-zero signals, True otherwise."""
    dates = pd.date_range("2020-01-01", periods=5, freq="B")
    flat = pd.Series(0, index=dates, dtype=int)
    assert signals_active(flat) is False

    active = pd.Series([0, 0, 1, 1, 0], index=dates)
    assert signals_active(active) is True

    empty = pd.Series(dtype=int)
    assert signals_active(empty) is False


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


def test_monte_carlo_simulation_basic():
    """monte_carlo_simulation runs and returns expected structure."""
    data = _make_data(periods=252)
    returns = data["close"].pct_change().dropna()

    mc = monte_carlo_simulation(
        base_returns=returns,
        n_simulations=100,
        confidence_levels=[0.90, 0.95],
    )

    assert "simulated_equity_curves" in mc
    assert "metric_distributions" in mc
    assert "confidence_intervals" in mc
    assert "probability_of_ruin" in mc
    assert "summary" in mc
    assert mc["n_simulations"] == 100
    assert mc["base_observations"] == len(returns)
    assert len(mc["simulated_equity_curves"]) == 100

    # Check all expected metrics are present
    expected_metrics = [
        "total_return", "annualized_return", "annualized_volatility",
        "sharpe_ratio", "sortino_ratio", "max_drawdown", "calmar_ratio"
    ]
    for metric in expected_metrics:
        assert metric in mc["metric_distributions"], f"missing metric: {metric}"
        assert metric in mc["confidence_intervals"], f"missing CI for: {metric}"
        assert metric in mc["summary"], f"missing summary for: {metric}"
        # Check CI structure
        for level in [0.90, 0.95]:
            assert level in mc["confidence_intervals"][metric]
            lower, upper = mc["confidence_intervals"][metric][level]
            assert lower <= upper, f"CI bounds inverted for {metric}"


def test_monte_carlo_simulation_block_bootstrap():
    """monte_carlo_simulation works with block_size parameter."""
    data = _make_data(periods=252)
    returns = data["close"].pct_change().dropna()

    mc = monte_carlo_simulation(
        base_returns=returns,
        n_simulations=50,
        block_size=10,
    )

    assert mc["n_simulations"] == 50
    assert len(mc["simulated_equity_curves"]) == 50
    # Block bootstrap should still produce valid metrics
    for metric in mc["metric_distributions"]:
        vals = mc["metric_distributions"][metric]
        assert len(vals) == 50
        assert not np.any(np.isnan(vals))


def test_monte_carlo_block_bootstrap_preserves_autocorrelation():
    """Stationary block bootstrap should preserve autocorrelation better than i.i.d."""
    # Create AR(1) process with known autocorrelation phi = 0.5
    rng = np.random.default_rng(42)
    n = 1000
    phi = 0.5
    dates = pd.date_range("2020-01-01", periods=n, freq="B")
    innovations = rng.normal(0, 0.01, n)
    ar1_returns = np.zeros(n)
    ar1_returns[0] = innovations[0]
    for i in range(1, n):
        ar1_returns[i] = phi * ar1_returns[i-1] + innovations[i]

    returns = pd.Series(ar1_returns, index=dates)

    # Base autocorrelation at lag 1
    base_acf1 = returns.autocorr(lag=1)
    assert base_acf1 > 0.3, "Base series should have positive autocorrelation"

    # i.i.d. bootstrap (block_size=None)
    mc_iid = monte_carlo_simulation(
        base_returns=returns,
        n_simulations=200,
        block_size=None,
    )

    # Stationary block bootstrap with block_size=20
    mc_block = monte_carlo_simulation(
        base_returns=returns,
        n_simulations=200,
        block_size=20,
    )

    # Compute average lag-1 autocorrelation across simulations
    iid_acf1s = []
    block_acf1s = []

    for eq_curve in mc_iid["simulated_equity_curves"]:
        sim_returns = eq_curve.pct_change().dropna()
        if len(sim_returns) > 10:
            iid_acf1s.append(sim_returns.autocorr(lag=1))

    for eq_curve in mc_block["simulated_equity_curves"]:
        sim_returns = eq_curve.pct_change().dropna()
        if len(sim_returns) > 10:
            block_acf1s.append(sim_returns.autocorr(lag=1))

    avg_iid_acf1 = np.mean(iid_acf1s) if iid_acf1s else 0
    avg_block_acf1 = np.mean(block_acf1s) if block_acf1s else 0

    # i.i.d. bootstrap should destroy autocorrelation (close to 0)
    # Block bootstrap should preserve some autocorrelation (closer to base)
    assert abs(avg_iid_acf1) < 0.15, f"i.i.d. bootstrap autocorrelation should be near 0, got {avg_iid_acf1}"
    assert abs(avg_block_acf1 - base_acf1) < abs(avg_iid_acf1 - base_acf1), (
        f"Block bootstrap ({avg_block_acf1:.3f}) should preserve autocorrelation "
        f"better than i.i.d. ({avg_iid_acf1:.3f}) vs base ({base_acf1:.3f})"
    )


def test_monte_carlo_simulation_probability_of_ruin():
    """Probability of ruin is between 0 and 1."""
    data = _make_data(periods=252)
    returns = data["close"].pct_change().dropna()

    mc = monte_carlo_simulation(
        base_returns=returns,
        n_simulations=200,
    )

    prob_ruin = mc["probability_of_ruin"]
    assert 0.0 <= prob_ruin <= 1.0
    assert mc["ruin_threshold"] == 0.5


def test_monte_carlo_simulation_handles_short_series():
    """Monte Carlo should raise ValueError for too few observations."""
    returns = pd.Series([0.01], index=pd.date_range("2020-01-01", periods=1, freq="B"))

    try:
        monte_carlo_simulation(base_returns=returns, n_simulations=10)
        assert False, "Expected ValueError for < 2 observations"
    except ValueError as e:
        assert "at least 2 return observations" in str(e)


def _make_test_data_file(periods: int = 504, seed: int = 42) -> str:
    """Create a temporary CSV file with test data."""
    rng = np.random.default_rng(seed)
    dates = pd.date_range("2018-01-01", periods=periods, freq="B")
    rets = rng.normal(0.0005, 0.015, periods)
    prices = 100 * np.exp(np.cumsum(rets))
    df = pd.DataFrame({
        "date": dates,
        "open": prices * rng.uniform(0.995, 1.005, periods),
        "high": prices * rng.uniform(1.005, 1.02, periods),
        "low": prices * rng.uniform(0.98, 0.995, periods),
        "close": prices,
        "volume": rng.integers(1_000_000, 10_000_000, periods),
    })
    tmp = tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False)
    df.to_csv(tmp.name, index=False)
    return tmp.name


class _CLIArgs:
    """Mock CLI arguments namespace."""
    def __init__(self, **kwargs):
        for k, v in kwargs.items():
            setattr(self, k, v)


def test_run_walk_forward_cli():
    """Test walk-forward CLI function runs and produces output."""
    data_file = _make_test_data_file()
    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            args = _CLIArgs(
                data=data_file,
                strategy="sma_crossover",
                symbol="SPY",
                start=None,
                end=None,
                commission=0.0002,
                slippage=0.0001,
                output=tmpdir,
                param_grid='{"fast_period": [10, 20], "slow_period": [30, 50]}',
                train_months=6,
                test_months=2,
                step_months=2,
                initial_capital=100000,
            )
            result = run_walk_forward(args)
            assert result == 0

            # Check output files exist
            summary_path = Path(tmpdir) / "walk_forward_summary.json"
            assert summary_path.exists(), "Summary JSON not created"

            with open(summary_path) as f:
                summary = json.load(f)
            assert "summary" in summary
            assert "diagnostics" in summary
            assert "best_params_per_period" in summary
            assert summary["summary"]["n_periods"] > 0
    finally:
        Path(data_file).unlink()


def test_run_parameter_optimization_cli():
    """Test parameter optimization CLI function runs and produces output."""
    data_file = _make_test_data_file()
    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            args = _CLIArgs(
                data=data_file,
                strategy="sma_crossover",
                symbol="SPY",
                start=None,
                end=None,
                commission=0.0002,
                slippage=0.0001,
                output=tmpdir,
                param_grid='{"fast_period": [10, 20], "slow_period": [30, 50]}',
                top_n=5,
            )
            result = run_parameter_optimization(args)
            assert result == 0

            # Check output files exist
            results_path = Path(tmpdir) / "parameter_optimization.json"
            assert results_path.exists(), "Results JSON not created"

            with open(results_path) as f:
                results = json.load(f)
            assert len(results) > 0
            assert "sharpe_ratio" in results[0]
            assert "params" in results[0]
    finally:
        Path(data_file).unlink()


def test_run_monte_carlo_cli():
    """Test Monte Carlo CLI function runs and produces output."""
    data_file = _make_test_data_file()
    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            args = _CLIArgs(
                data=data_file,
                strategy="sma_crossover",
                symbol="SPY",
                start=None,
                end=None,
                commission=0.0002,
                slippage=0.0001,
                output=tmpdir,
                param_grid='{"fast_period": [10, 20], "slow_period": [30, 50]}',
                n_simulations=50,
                confidence_levels=[0.90, 0.95],
                block_size=None,
                initial_capital=100000,
            )
            result = run_monte_carlo(args)
            assert result == 0

            # Check output files exist
            mc_path = Path(tmpdir) / "monte_carlo_results.json"
            assert mc_path.exists(), "Monte Carlo results JSON not created"

            with open(mc_path) as f:
                mc = json.load(f)
            assert "metric_distributions" in mc
            assert "confidence_intervals" in mc
            assert "probability_of_ruin" in mc
            assert "summary" in mc
            assert mc["n_simulations"] == 50
    finally:
        Path(data_file).unlink()


def test_parse_param_grid():
    """Test parameter grid parsing from JSON string."""
    # Simple grid
    grid = _parse_param_grid('{"fast_period": [10, 20], "slow_period": 50}')
    assert grid == {"fast_period": [10, 20], "slow_period": [50]}

    # Single values become lists
    grid = _parse_param_grid('{"period": 20}')
    assert grid == {"period": [20]}

    # Invalid JSON raises error
    try:
        _parse_param_grid("not valid json")
        assert False, "Expected ValueError for invalid JSON"
    except ValueError as e:
        assert "Invalid JSON" in str(e)


def main() -> int:
    tests = [
        ("parameter_optimization_skips_flat_combos", test_parameter_optimization_skips_flat_combos),
        ("walk_forward_skips_flat_combos_in_test_window", test_walk_forward_skips_flat_combos_in_test_window),
        ("overfitting_check_handles_empty_oos", test_overfitting_check_handles_empty_oos),
        ("signals_active_detects_flat_and_active_series", test_signals_active_detects_flat_and_active_series),
        ("monte_carlo_simulation_basic", test_monte_carlo_simulation_basic),
        ("monte_carlo_simulation_block_bootstrap", test_monte_carlo_simulation_block_bootstrap),
        ("monte_carlo_block_bootstrap_preserves_autocorrelation", test_monte_carlo_block_bootstrap_preserves_autocorrelation),
        ("monte_carlo_simulation_probability_of_ruin", test_monte_carlo_simulation_probability_of_ruin),
        ("monte_carlo_simulation_handles_short_series", test_monte_carlo_simulation_handles_short_series),
        ("run_walk_forward_cli", test_run_walk_forward_cli),
        ("run_parameter_optimization_cli", test_run_parameter_optimization_cli),
        ("run_monte_carlo_cli", test_run_monte_carlo_cli),
        ("parse_param_grid", test_parse_param_grid),
        ("walk_forward_multi_asset_cross_sectional_momentum", test_walk_forward_multi_asset_cross_sectional_momentum),
        ("walk_forward_multi_asset_dual_momentum", test_walk_forward_multi_asset_dual_momentum),
        ("monte_carlo_multi_asset_integration", test_monte_carlo_multi_asset_integration),
        ("walk_forward_multi_asset_dict_cross_sectional_momentum", test_walk_forward_multi_asset_dict_cross_sectional_momentum),
        ("walk_forward_multi_asset_dict_dual_momentum", test_walk_forward_multi_asset_dict_dual_momentum),
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


def test_walk_forward_multi_asset_cross_sectional_momentum():
    """Walk-forward analysis works with multi-asset panel data (MultiIndex)."""
    data = _make_multiasset_multiindex(n=600, n_assets=5, seed=123)
    results = walk_forward_analysis(
        data=data,
        strategy_factory=lambda p: _factory("cross_sectional_momentum", p),
        param_grid={
            "lookback": [20, 40],
            "top_quantile": [0.3, 0.4],
            "bottom_quantile": [0.2, 0.1],
        },
        train_months=12,
        test_months=3,
        step_months=3,
    )
    assert results["summary"]["n_periods"] > 0
    assert len(results["oos_returns"]) > 0
    assert results["summary"]["total_oos_return"] is not None


def test_walk_forward_multi_asset_dual_momentum():
    """Walk-forward analysis works with multi-asset panel data for dual momentum."""
    data = _make_multiasset_multiindex(n=800, n_assets=5, seed=456)
    results = walk_forward_analysis(
        data=data,
        strategy_factory=lambda p: _factory("dual_momentum", p),
        param_grid={
            "lookback": [60, 90],
            "top_quantile": [0.3, 0.4],
            "risk_free_rate": [0.0],
        },
        train_months=12,
        test_months=6,
        step_months=6,
    )
    assert results["summary"]["n_periods"] > 0
    assert len(results["oos_returns"]) > 0

def test_monte_carlo_multi_asset_integration():
    """Monte Carlo simulation works with multi-asset strategy returns."""
    data = _make_multiasset_multiindex(n=500, n_assets=5, seed=789)
    strategy = build_strategy("cross_sectional_momentum",
                               json.dumps({"lookback": 20, "top_quantile": 0.4, "bottom_quantile": 0.2}))
    signals = strategy.generate_signals(data)
    from scripts.walk_forward import _calculate_strategy_returns
    returns = _calculate_strategy_returns(data, signals, commission=0.0002, slippage=0.0001)
    mc_results = monte_carlo_simulation(
        base_returns=returns,
        n_simulations=50,
        confidence_levels=[0.95],
        block_size=10,
    )
    assert "metric_distributions" in mc_results
    assert "confidence_intervals" in mc_results
    assert mc_results["n_simulations"] == 50


def test_walk_forward_multi_asset_dict_cross_sectional_momentum():
    """Walk-forward analysis works with dict panel data.

    Regression coverage: dict input previously crashed because
    walk-forward windows were sliced with data.index (absent on
    dicts); dict data is now normalized to a MultiIndex panel.
    """
    data = _make_multiasset_dict(n=600, n_assets=5, seed=123)
    results = walk_forward_analysis(
        data=data,
        strategy_factory=lambda p: _factory("cross_sectional_momentum", p),
        param_grid={
            "lookback": [20, 40],
            "top_quantile": [0.3, 0.4],
            "bottom_quantile": [0.2, 0.1],
        },
        train_months=12,
        test_months=3,
        step_months=3,
    )
    assert results["summary"]["n_periods"] > 0
    assert len(results["oos_returns"]) > 0
    assert results["summary"]["total_oos_return"] is not None


def test_walk_forward_multi_asset_dict_dual_momentum():
    """Walk-forward analysis works with dict panel data for dual momentum."""
    data = _make_multiasset_dict(n=800, n_assets=5, seed=456)
    results = walk_forward_analysis(
        data=data,
        strategy_factory=lambda p: _factory("dual_momentum", p),
        param_grid={
            "lookback": [60, 90],
            "top_quantile": [0.3, 0.4],
            "risk_free_rate": [0.0],
        },
        train_months=12,
        test_months=6,
        step_months=6,
    )
    assert results["summary"]["n_periods"] > 0
    assert len(results["oos_returns"]) > 0


if __name__ == "__main__":
    sys.exit(main())

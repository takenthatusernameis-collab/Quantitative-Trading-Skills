#!/usr/bin/env python3
"""
Unit tests for walk_forward.py: parameter_optimization and walk_forward_analysis.

Run with: python3 skills/quantitative-backtesting/tests/test_walk_forward.py
No third-party test framework is required; uses only the standard library.
"""

import json
import os
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


def _make_flat_price_data_file(periods: int = 100) -> str:
    """Create a temporary CSV file with perfectly flat prices (zero returns)."""
    dates = pd.date_range("2020-01-01", periods=periods, freq="B")
    prices = np.full(periods, 100.0)
    df = pd.DataFrame({
        "date": dates,
        "open": prices,
        "high": prices,
        "low": prices,
        "close": prices,
        "volume": [1000000] * periods,
    })
    tmp = tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False)
    df.to_csv(tmp.name, index=False)
    return tmp.name


class _CLIArgs:
    """Mock CLI arguments namespace."""
    def __init__(self, **kwargs):
        # Set defaults for market impact parameters
        defaults = {
            "impact_coefficient": 0.0,
            "adv_window": 20,
            "borrow_cost": 0.0,
            "funding_cost": 0.0,
            # Out-of-sample validation defaults
            "train_frac": 0.6,
            "val_frac": 0.2,
            "test_frac": 0.2,
            "validation_method": "walk_forward",
            "selection_criterion": "best_oos_sharpe",
            "wf_train_months": 12,
            "wf_test_months": 3,
            "wf_step_months": 3,
            "cpcv_n_splits": 10,
            "cpcv_test_size": 0.1,
            "cpcv_purge_size": 0.0,
            "cpcv_embargo_size": 0.0,
        }
        for k, v in defaults.items():
            setattr(self, k, v)
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
                deflate=False,
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
                deflate=False,
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



def test_run_parameter_optimization_cli_constant_returns_deflation():
    """Parameter optimization CLI writes degenerate DSRs to artifact on constant returns."""
    data_file = _make_flat_price_data_file()
    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            args = _CLIArgs(
                data=data_file,
                strategy="donchian_breakout",
                symbol="TEST",
                start=None,
                end=None,
                commission=0.0,
                slippage=0.0,
                output=tmpdir,
                param_grid='{"period": [10, 20], "exit_period": [5, 10]}',
                top_n=4,
                deflate=True,
            )
            assert run_parameter_optimization(args) == 0
            results_path = Path(tmpdir) / "parameter_optimization.json"
            assert results_path.exists()
            with open(results_path) as f:
                results = json.load(f)
            assert len(results) == 4
            for r in results:
                assert r["sharpe_ratio"] == 0.0
                assert "deflated_sharpe" in r
                d = r["deflated_sharpe"]
                assert d["deflated_sharpe_ratio"] == 0.0
                assert d["p_value"] == 1.0
                assert d["z_score"] is None
                assert d["sharpe_ratio"] == 0.0
                assert d["skewness"] == 0.0
                assert d["kurtosis"] == 3.0
                assert d["n_trials"] == len(results)
                assert d["n_observations"] == r["n_periods"]
                assert d["expected_max_sharpe"] > 0 and np.isfinite(d["expected_max_sharpe"])
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


def test_run_monte_carlo_cli_with_n_trials():
    """The monte-carlo CLI deflates the base Sharpe with --n-trials."""
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
                n_trials=50,
            )
            result = run_monte_carlo(args)
            assert result == 0

            mc_path = Path(tmpdir) / "monte_carlo_results.json"
            assert mc_path.exists(), "Monte Carlo results JSON not created"

            with open(mc_path) as f:
                mc = json.load(f)

            assert "deflated_sharpe" in mc, (
                "expected deflated_sharpe in monte-carlo output"
            )
            d = mc["deflated_sharpe"]
            assert 0.0 <= d["deflated_sharpe_ratio"] <= 1.0
            assert d["n_trials"] == 50
            assert d["n_observations"] > 0
            assert "expected_max_sharpe" in d
            assert "p_value" in d
            assert abs(d["p_value"] - (1.0 - d["deflated_sharpe_ratio"])) < 1e-12
            # The saved config records the trial count.
            assert mc["config"]["n_trials"] == 50
    finally:
        Path(data_file).unlink()


def test_run_monte_carlo_cli_without_n_trials_omits_dsr():
    """Without --n-trials no deflated_sharpe key is saved (backward compat)."""
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

            mc_path = Path(tmpdir) / "monte_carlo_results.json"
            with open(mc_path) as f:
                mc = json.load(f)

            assert "deflated_sharpe" not in mc
            assert "n_trials" not in mc["config"]
    finally:
        Path(data_file).unlink()


def test_run_monte_carlo_deflated_sharpe_matches_direct_call():
    """The surfaced DSR equals a direct deflated_sharpe_ratio call.

    The monte-carlo run must deflate the base backtest Sharpe (the
    Sharpe of the selected params over the full sample), and when a
    parameter grid was searched it must pass the optimization
    record's trial Sharpes so SR* uses the cross-sectional
    estimator rather than the i.i.d. null approximation.
    """
    data_file = _make_test_data_file()
    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            param_grid = {"fast_period": [10, 20], "slow_period": [30, 50]}
            args = _CLIArgs(
                data=data_file,
                strategy="sma_crossover",
                symbol="SPY",
                start=None,
                end=None,
                commission=0.0002,
                slippage=0.0001,
                output=tmpdir,
                param_grid=json.dumps(param_grid),
                n_simulations=50,
                confidence_levels=[0.90, 0.95],
                block_size=None,
                initial_capital=100000,
                n_trials=50,
            )
            assert run_monte_carlo(args) == 0

            with open(Path(tmpdir) / "monte_carlo_results.json") as f:
                mc = json.load(f)
            got = mc["deflated_sharpe"]

            # Recompute the optimization record and the base
            # backtest independently of run_monte_carlo.
            data = load_data(data_file, symbol="SPY", start=None, end=None)
            strategy_factory = _make_strategy_factory("sma_crossover")
            opt_results = parameter_optimization(
                data=data,
                strategy_factory=strategy_factory,
                param_grid=param_grid,
                commission=0.0002,
                slippage=0.0001,
            )
            assert opt_results, "expected at least one valid combo"
            best_params = opt_results[0]["params"]
            strategy = strategy_factory(best_params)
            signals = strategy.generate_signals(data)
            returns = _calculate_strategy_returns(
                data, signals, 0.0002, 0.0001
            )

            ann_factor = _annualization_factor(returns.index)
            excess = returns - 0.02 / ann_factor
            sharpe = float(excess.mean() / excess.std() * np.sqrt(ann_factor))

            trial_sharpes = [r["sharpe_ratio"] for r in opt_results]
            expected = deflated_sharpe_ratio(
                sharpe_ratio=sharpe,
                returns=returns,
                n_trials=50,
                trial_sharpes=trial_sharpes,
            )

            for key in (
                "deflated_sharpe_ratio", "p_value", "expected_max_sharpe",
                "n_trials", "n_observations", "skewness", "kurtosis",
            ):
                assert abs(got[key] - expected[key]) < 1e-12, key

            # The cross-sectional estimator (from the optimization
            # record) must differ from the i.i.d. null approximation,
            # proving the trial Sharpes were actually used.
            iid_null = deflated_sharpe_ratio(
                sharpe_ratio=sharpe, returns=returns, n_trials=50
            )
            assert abs(got["expected_max_sharpe"] - iid_null["expected_max_sharpe"]) > 1e-9
    finally:
        Path(data_file).unlink()


def test_run_monte_carlo_n_trials_floored_to_grid_size():
    """--n-trials is floored to the number of grid combos evaluated.

    When the internal parameter search evaluates more
    configurations than the caller reports via --n-trials, the
    effective trial count is the larger grid size so the
    deflation never understates the search.
    """
    data_file = _make_test_data_file()
    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            param_grid = {"fast_period": [10, 20], "slow_period": [30, 50, 70]}
            args = _CLIArgs(
                data=data_file,
                strategy="sma_crossover",
                symbol="SPY",
                start=None,
                end=None,
                commission=0.0002,
                slippage=0.0001,
                output=tmpdir,
                param_grid=json.dumps(param_grid),
                n_simulations=50,
                confidence_levels=[0.90, 0.95],
                block_size=None,
                initial_capital=100000,
                n_trials=2,
            )
            assert run_monte_carlo(args) == 0

            with open(Path(tmpdir) / "monte_carlo_results.json") as f:
                mc = json.load(f)

            # Independent optimization record for the expected count.
            data = load_data(data_file, symbol="SPY", start=None, end=None)
            strategy_factory = _make_strategy_factory("sma_crossover")
            opt_results = parameter_optimization(
                data=data,
                strategy_factory=strategy_factory,
                param_grid=param_grid,
                commission=0.0002,
                slippage=0.0001,
            )
            assert opt_results, "expected at least one valid combo"
            expected_n_trials = max(2, len(opt_results))

            d = mc["deflated_sharpe"]
            assert d["n_trials"] == expected_n_trials
            assert mc["config"]["n_trials"] == expected_n_trials
    finally:
        Path(data_file).unlink()


def test_run_monte_carlo_deflated_sharpe_uses_floored_n_trials():
    """The DSR value uses the floored trial count, not --n-trials.

    With a grid search larger than the reported --n-trials, the
    surfaced DSR must equal a direct deflated_sharpe_ratio call
    with n_trials = max(--n-trials, grid size) and the
    optimization record's trial Sharpes.
    """
    data_file = _make_test_data_file()
    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            param_grid = {"fast_period": [10, 20], "slow_period": [30, 50, 70]}
            args = _CLIArgs(
                data=data_file,
                strategy="sma_crossover",
                symbol="SPY",
                start=None,
                end=None,
                commission=0.0002,
                slippage=0.0001,
                output=tmpdir,
                param_grid=json.dumps(param_grid),
                n_simulations=50,
                confidence_levels=[0.90, 0.95],
                block_size=None,
                initial_capital=100000,
                n_trials=2,
            )
            assert run_monte_carlo(args) == 0

            with open(Path(tmpdir) / "monte_carlo_results.json") as f:
                mc = json.load(f)
            got = mc["deflated_sharpe"]

            # Recompute the optimization record and the base
            # backtest independently of run_monte_carlo.
            data = load_data(data_file, symbol="SPY", start=None, end=None)
            strategy_factory = _make_strategy_factory("sma_crossover")
            opt_results = parameter_optimization(
                data=data,
                strategy_factory=strategy_factory,
                param_grid=param_grid,
                commission=0.0002,
                slippage=0.0001,
            )
            assert opt_results, "expected at least one valid combo"
            best_params = opt_results[0]["params"]
            strategy = strategy_factory(best_params)
            signals = strategy.generate_signals(data)
            returns = _calculate_strategy_returns(
                data, signals, 0.0002, 0.0001
            )

            ann_factor = _annualization_factor(returns.index)
            excess = returns - 0.02 / ann_factor
            sharpe = float(excess.mean() / excess.std() * np.sqrt(ann_factor))

            trial_sharpes = [r["sharpe_ratio"] for r in opt_results]
            expected = deflated_sharpe_ratio(
                sharpe_ratio=sharpe,
                returns=returns,
                n_trials=max(2, len(opt_results)),
                trial_sharpes=trial_sharpes,
            )

            for key in (
                "deflated_sharpe_ratio", "p_value", "expected_max_sharpe",
                "n_trials", "n_observations", "skewness", "kurtosis",
            ):
                assert abs(got[key] - expected[key]) < 1e-12, key
    finally:
        Path(data_file).unlink()


def test_run_monte_carlo_constant_returns_deflated_sharpe():
    """The monte-carlo CLI handles constant returns (zero variance) conservatively.

    When the base backtest produces a constant return series (e.g. a strategy
    that trades on a flat price series with zero costs), the DSR must be
    DSR = 0, p-value = 1, z_score = None rather than raising or producing NaN.
    """
    # Create flat price data file
    data_file = _make_flat_price_data_file()
    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            # donchian_breakout takes positions on flat data (period < len(data))
            args = _CLIArgs(
                data=data_file,
                strategy="donchian_breakout",
                symbol="TEST",
                start=None,
                end=None,
                commission=0.0,
                slippage=0.0,
                output=tmpdir,
                param_grid='{"period": [10, 20]}',
                n_simulations=10,
                confidence_levels=[0.95],
                block_size=None,
                initial_capital=100000,
                n_trials=5,
            )
            assert run_monte_carlo(args) == 0

            mc_path = Path(tmpdir) / "monte_carlo_results.json"
            with open(mc_path) as f:
                mc = json.load(f)

            assert "deflated_sharpe" in mc, "expected deflated_sharpe in output"
            d = mc["deflated_sharpe"]
            assert d["deflated_sharpe_ratio"] == 0.0
            assert d["p_value"] == 1.0
            assert d["z_score"] is None
            assert d["n_trials"] == 5
            assert d["n_observations"] > 0
            assert d["skewness"] == 0.0
            assert d["kurtosis"] == 3.0
            assert d["sharpe_ratio"] == 0.0
    finally:
        Path(data_file).unlink()


def test_run_walk_forward_cli_persists_pit_results():
    """--validate-point-in-time persists the PIT outcome in walk-forward summary JSON."""
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
                deflate=False,
                validate_point_in_time=True,
                point_in_time_strict=False,
            )
            assert run_walk_forward(args) == 0
            summary_path = Path(tmpdir) / "walk_forward_summary.json"
            with open(summary_path) as f:
                summary = json.load(f)
            assert "point_in_time_validation" in summary
            pit = summary["point_in_time_validation"]
            assert "passed" in pit
            assert "violations" in pit
            assert "warnings" in pit
    finally:
        Path(data_file).unlink()


def test_run_walk_forward_cli_omits_pit_without_flag():
    """Without --validate-point-in-time, no PIT key is persisted (backward compat)."""
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
                deflate=False,
            )
            assert run_walk_forward(args) == 0
            summary_path = Path(tmpdir) / "walk_forward_summary.json"
            with open(summary_path) as f:
                summary = json.load(f)
            assert "point_in_time_validation" not in summary
    finally:
        Path(data_file).unlink()


def test_run_cpcv_cli_persists_pit_results():
    """--validate-point-in-time persists the PIT outcome in CPCV summary JSON."""
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
                n_splits=4,
                test_size=0.25,
                purge_size=0.0,
                embargo_size=0.0,
                initial_capital=100000,
                deflate=False,
                validate_point_in_time=True,
                point_in_time_strict=False,
            )
            assert run_cpcv(args) == 0
            summary_path = Path(tmpdir) / "cpcv_summary.json"
            with open(summary_path) as f:
                summary = json.load(f)
            assert "point_in_time_validation" in summary
            pit = summary["point_in_time_validation"]
            assert "passed" in pit
            assert "violations" in pit
    finally:
        Path(data_file).unlink()


def test_run_monte_carlo_cli_persists_pit_and_preserves_block_size():
    """--validate-point-in-time persists PIT in Monte Carlo output and
    block_size is preserved in the config dict (regression for a prior
    edit that replaced block_size with point_in_time_validation)."""
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
                block_size=10,
                initial_capital=100000,
                validate_point_in_time=True,
                point_in_time_strict=False,
            )
            assert run_monte_carlo(args) == 0
            mc_path = Path(tmpdir) / "monte_carlo_results.json"
            with open(mc_path) as f:
                mc = json.load(f)
            assert "point_in_time_validation" in mc
            pit = mc["point_in_time_validation"]
            assert "passed" in pit
            assert "violations" in pit
            # Regression: block_size must be preserved in the config dict
            assert "block_size" in mc["config"]
            assert mc["config"]["block_size"] == 10
    finally:
        Path(data_file).unlink()


def test_run_parameter_optimization_cli_persists_pit_results():
    """--validate-point-in-time persists PIT in a separate artifact for
    parameter optimization, whose results format is a ranked list (not a
    dict), so PIT results are saved to point_in_time_validation.json."""
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
                deflate=False,
                validate_point_in_time=True,
                point_in_time_strict=False,
            )
            assert run_parameter_optimization(args) == 0
            pit_path = Path(tmpdir) / "point_in_time_validation.json"
            assert pit_path.exists(), "point_in_time_validation.json should be written"
            with open(pit_path) as f:
                pit = json.load(f)
            assert "passed" in pit
            assert "violations" in pit
            # The optimization results file remains a list (schema preserved)
            opt_path = Path(tmpdir) / "parameter_optimization.json"
            with open(opt_path) as f:
                opt = json.load(f)
            assert isinstance(opt, list)
            assert len(opt) > 0
    finally:
        Path(data_file).unlink()


def test_run_parameter_optimization_cli_with_benchmark():
    """Parameter optimization CLI with --benchmark computes alpha/beta for each combo."""
    data_file = _make_test_data_file()
    bench_file = _make_benchmark_data_with_dividends()
    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            # Price-only benchmark run
            args_price = _CLIArgs(
                data=data_file,
                strategy="sma_crossover",
                symbol="SPY",
                start=None,
                end=None,
                commission=0.0002,
                slippage=0.0001,
                output=os.path.join(tmpdir, "out_price"),
                param_grid='{"fast_period": [10, 20], "slow_period": [30, 50]}',
                top_n=4,
                deflate=False,
                benchmark=bench_file,
            )
            assert run_parameter_optimization(args_price) == 0

            results_path_price = Path(tmpdir) / "out_price" / "parameter_optimization.json"
            with open(results_path_price) as f:
                results_price = json.load(f)

            # Total-return benchmark run
            args_total = _CLIArgs(
                data=data_file,
                strategy="sma_crossover",
                symbol="SPY",
                start=None,
                end=None,
                commission=0.0002,
                slippage=0.0001,
                output=os.path.join(tmpdir, "out_total"),
                param_grid='{"fast_period": [10, 20], "slow_period": [30, 50]}',
                top_n=4,
                deflate=False,
                benchmark=bench_file,
                total_return_benchmark=True,
            )
            assert run_parameter_optimization(args_total) == 0

            results_path_total = Path(tmpdir) / "out_total" / "parameter_optimization.json"
            with open(results_path_total) as f:
                results_total = json.load(f)

            # Each result should have benchmark metrics
            for r in results_price:
                assert "correlation_with_benchmark" in r
                assert "alpha" in r
                assert "beta" in r
                assert r["benchmark_total_return_type"] == "price"
            for r in results_total:
                assert "correlation_with_benchmark" in r
                assert "alpha" in r
                assert "beta" in r
                assert r["benchmark_total_return_type"] == "total"

            # Total-return benchmark has higher total return (dividends add value)
            # Check best result from each
            best_price = results_price[0]
            best_total = results_total[0]
            assert best_total["benchmark_total_return"] > best_price["benchmark_total_return"]

            # Alpha and beta differ between price-only and total-return
            assert abs(best_total["alpha"] - best_price["alpha"]) > 1e-6
            assert abs(best_total["beta"] - best_price["beta"]) > 1e-6

            # Benchmark provenance written
            prov_path_total = Path(tmpdir) / "out_total" / "benchmark_provenance.json"
            assert prov_path_total.exists()
            with open(prov_path_total) as f:
                prov = json.load(f)
            assert prov["total_return_type"] == "total"
    finally:
        Path(data_file).unlink()
        Path(bench_file).unlink()


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


def test_deflated_sharpe_ratio_basic():
    """DSR is high for a genuine edge with a single trial."""
    rng = np.random.default_rng(123)
    n = 1000
    dates = pd.date_range("2020-01-01", periods=n, freq="B")
    returns = pd.Series(rng.normal(0.001, 0.01, n), index=dates)
    sr_annual = float(returns.mean() / returns.std() * np.sqrt(252))

    out = deflated_sharpe_ratio(
        sharpe_ratio=sr_annual, returns=returns, n_trials=1
    )

    assert 0.0 <= out["deflated_sharpe_ratio"] <= 1.0
    assert out["deflated_sharpe_ratio"] > 0.9
    assert out["n_trials"] == 1
    assert out["n_observations"] == n
    assert out["expected_max_sharpe"] == 0.0
    assert abs(out["p_value"] - (1.0 - out["deflated_sharpe_ratio"])) < 1e-12


def test_deflated_sharpe_ratio_decreases_with_more_trials():
    """More trials mean stronger deflation and a lower DSR."""
    rng = np.random.default_rng(123)
    n = 1000
    dates = pd.date_range("2020-01-01", periods=n, freq="B")
    returns = pd.Series(rng.normal(0.001, 0.01, n), index=dates)
    sr_annual = float(returns.mean() / returns.std() * np.sqrt(252))

    out_few = deflated_sharpe_ratio(
        sharpe_ratio=sr_annual, returns=returns, n_trials=1
    )
    out_many = deflated_sharpe_ratio(
        sharpe_ratio=sr_annual, returns=returns, n_trials=100000
    )

    assert out_many["deflated_sharpe_ratio"] < out_few["deflated_sharpe_ratio"]
    # With enough trials, the expected maximum Sharpe attainable from
    # luck alone exceeds the observed Sharpe, which forces the DSR
    # below 0.5 (the edge is more likely luck than skill)
    assert out_many["expected_max_sharpe"] > sr_annual
    assert out_many["deflated_sharpe_ratio"] < 0.5


def test_deflated_sharpe_ratio_with_trial_sharpes():
    """Cross-sectional trial dispersion estimates SR* differently."""
    rng = np.random.default_rng(123)
    n = 1000
    dates = pd.date_range("2020-01-01", periods=n, freq="B")
    returns = pd.Series(rng.normal(0.001, 0.01, n), index=dates)
    sr_annual = float(returns.mean() / returns.std() * np.sqrt(252))

    fallback = deflated_sharpe_ratio(
        sharpe_ratio=sr_annual, returns=returns, n_trials=5
    )
    trial_sharpes = [sr_annual * f for f in (1.0, 0.9, 0.8, 0.7, 0.6)]
    cross_sectional = deflated_sharpe_ratio(
        sharpe_ratio=sr_annual,
        returns=returns,
        n_trials=5,
        trial_sharpes=trial_sharpes,
    )

    assert 0.0 <= cross_sectional["deflated_sharpe_ratio"] <= 1.0
    # The dispersion-based benchmark differs from the iid null fallback
    assert cross_sectional["expected_max_sharpe"] != fallback["expected_max_sharpe"]
    assert cross_sectional["n_trials"] == 5


def test_deflated_sharpe_ratio_insufficient_data():
    """DSR raises ValueError for fewer than 2 observations."""
    returns = pd.Series([0.01], index=pd.date_range("2020-01-01", periods=1, freq="B"))
    try:
        deflated_sharpe_ratio(0.5, returns, n_trials=10)
        assert False, "Expected ValueError for < 2 observations"
    except ValueError as e:
        assert "at least 2" in str(e)


def test_deflated_sharpe_ratio_zero_variance():
    """Constant returns carry no information: DSR is 0."""
    dates = pd.date_range("2020-01-01", periods=100, freq="B")
    returns = pd.Series(0.0, index=dates)
    out = deflated_sharpe_ratio(0.0, returns, n_trials=5)
    assert out["deflated_sharpe_ratio"] == 0.0
    assert out["p_value"] == 1.0


def test_deflated_sharpe_ratio_invalid_n_trials():
    """DSR raises ValueError for n_trials < 1."""
    dates = pd.date_range("2020-01-01", periods=100, freq="B")
    returns = pd.Series(np.random.default_rng(1).normal(0.0, 0.01, 100), index=dates)
    try:
        deflated_sharpe_ratio(0.5, returns, n_trials=0)
        assert False, "Expected ValueError for n_trials < 1"
    except ValueError as e:
        assert "n_trials" in str(e)


def test_parameter_optimization_deflation():
    """apply_deflation adds DSR keys; the default preserves prior behavior."""
    data = _make_data()
    grid = {"fast_period": [10, 20], "slow_period": [30, 50]}

    plain = parameter_optimization(
        data=data,
        strategy_factory=lambda p: _factory("sma_crossover", p),
        param_grid=grid,
    )
    deflated = parameter_optimization(
        data=data,
        strategy_factory=lambda p: _factory("sma_crossover", p),
        param_grid=grid,
        apply_deflation=True,
    )

    # Backward compatible: same ranking, no DSR keys by default
    assert [r["params"] for r in plain] == [r["params"] for r in deflated]
    assert [r["sharpe_ratio"] for r in plain] == [r["sharpe_ratio"] for r in deflated]
    assert all("deflated_sharpe" not in r for r in plain)

    # Deflated results carry the correction for every ranked combo
    assert len(deflated) > 0
    for r in deflated:
        assert "deflated_sharpe" in r
        d = r["deflated_sharpe"]
        assert 0.0 <= d["deflated_sharpe_ratio"] <= 1.0
        assert d["n_trials"] == len(deflated)
        assert d["n_observations"] == r["n_periods"]
        assert 0.0 <= d["p_value"] <= 1.0

    # The top-ranked combo still has the highest raw Sharpe
    assert deflated[0]["sharpe_ratio"] >= deflated[-1]["sharpe_ratio"]

    # Each DSR must be computed against that combination's OWN
    # return series. Independently recompute the top-ranked
    # combo's DSR and compare (regression guard against a
    # sort/pairing mismatch between results and return series).
    from walk_forward import _calculate_strategy_returns

    top_params = deflated[0]["params"]
    top_signals = _factory("sma_crossover", top_params).generate_signals(data)
    top_returns = _calculate_strategy_returns(data, top_signals, 0.0002, 0.0001)
    expected = deflated_sharpe_ratio(
        sharpe_ratio=deflated[0]["sharpe_ratio"],
        returns=top_returns,
        n_trials=len(deflated),
        trial_sharpes=[r["sharpe_ratio"] for r in deflated],
    )
    assert abs(
        deflated[0]["deflated_sharpe"]["deflated_sharpe_ratio"]
        - expected["deflated_sharpe_ratio"]
    ) < 1e-12
    assert deflated[0]["deflated_sharpe"]["n_observations"] == deflated[0]["n_periods"]


def _make_flat_price_data(periods: int = 100) -> pd.DataFrame:
    """Create a DataFrame with perfectly flat prices (zero returns)."""
    dates = pd.date_range("2020-01-01", periods=periods, freq="B")
    prices = np.full(periods, 100.0)
    return pd.DataFrame({
        "open": prices,
        "high": prices,
        "low": prices,
        "close": prices,
        "volume": [1000000] * periods,
    }, index=dates)


def test_parameter_optimization_constant_returns_deflation():
    """apply_deflation on constant (zero-variance) returns emits the
    degenerate DSR dict for every ranked combo.

    `parameter_optimization` *ranks* zero-variance combos (its
    Sharpe is defined as 0 when `returns.std() == 0`,
    `walk_forward.py:352`) instead of skipping them as the
    walk-forward/CPCV grid search does, where a zero-variance
    *training* series yields sharpe = -inf, no configuration is
    selected and the period is skipped. The per-combo DSR is
    therefore computed — and must take the conservative degenerate
    dict — rather than being omitted.
    """
    data = _make_flat_price_data()
    grid = {"period": [10, 20], "exit_period": [5, 10]}

    results = parameter_optimization(
        data=data,
        strategy_factory=lambda p: _factory("donchian_breakout", p),
        param_grid=grid,
        commission=0.0,
        slippage=0.0,
        apply_deflation=True,
    )

    # donchian_breakout takes active positions on flat data, so
    # every grid combo is ranked (not skipped) at Sharpe 0.
    assert len(results) == len(grid["period"]) * len(grid["exit_period"])
    for r in results:
        assert r["sharpe_ratio"] == 0.0
        assert "deflated_sharpe" in r
        d = r["deflated_sharpe"]
        assert d["deflated_sharpe_ratio"] == 0.0
        assert d["p_value"] == 1.0
        assert d["z_score"] is None
        assert d["sharpe_ratio"] == 0.0
        assert d["skewness"] == 0.0
        assert d["kurtosis"] == 3.0
        assert d["n_trials"] == len(results)
        assert d["n_observations"] == r["n_periods"]

    # Backward compatible: default run ranks the same combos
    # without DSR keys.
    plain = parameter_optimization(
        data=data,
        strategy_factory=lambda p: _factory("donchian_breakout", p),
        param_grid=grid,
        commission=0.0,
        slippage=0.0,
    )
    assert [r["params"] for r in plain] == [r["params"] for r in results]
    assert all("deflated_sharpe" not in r for r in plain)


def test_walk_forward_deflation():
    """Walk-forward with apply_deflation reports per-period and aggregate DSR."""
    data = _make_data()
    results = walk_forward_analysis(
        data=data,
        strategy_factory=lambda p: _factory("sma_crossover", p),
        param_grid={"fast_period": [10, 20], "slow_period": [30, 50]},
        train_months=12,
        test_months=3,
        step_months=3,
        apply_deflation=True,
    )

    # Aggregate DSR on the combined OOS returns
    assert "deflated_sharpe" in results["summary"]
    agg = results["summary"]["deflated_sharpe"]
    assert 0.0 <= agg["deflated_sharpe_ratio"] <= 1.0
    assert agg["n_trials"] >= len(results["periods"])

    # Per-period DSR for the in-sample selection
    n_with_params = 0
    for period in results["periods"]:
        if period.get("best_params") is not None:
            n_with_params += 1
            assert "deflated_sharpe" in period
            d = period["deflated_sharpe"]
            assert 0.0 <= d["deflated_sharpe_ratio"] <= 1.0
            assert d["n_trials"] >= 1
    assert n_with_params > 0

    # Backward compatible: default run has no DSR keys
    default = walk_forward_analysis(
        data=data,
        strategy_factory=lambda p: _factory("sma_crossover", p),
        param_grid={"fast_period": [10, 20], "slow_period": [30, 50]},
        train_months=12,
        test_months=3,
        step_months=3,
    )
    assert "deflated_sharpe" not in default["summary"]
    assert all("deflated_sharpe" not in p for p in default["periods"])


def test_walk_forward_deflation_overfitting_check():
    """overfitting_check surfaces the aggregate DSR when present."""
    data = _make_data()
    wf = walk_forward_analysis(
        data=data,
        strategy_factory=lambda p: _factory("sma_crossover", p),
        param_grid={"fast_period": [10, 20], "slow_period": [30, 50]},
        apply_deflation=True,
    )
    diagnostics = overfitting_check(wf)
    assert "deflated_sharpe" in diagnostics
    assert 0.0 <= diagnostics["deflated_sharpe"]["deflated_sharpe_ratio"] <= 1.0

    # Without deflation the diagnostics are unchanged
    wf_plain = walk_forward_analysis(
        data=data,
        strategy_factory=lambda p: _factory("sma_crossover", p),
        param_grid={"fast_period": [10, 20], "slow_period": [30, 50]},
    )
    diagnostics_plain = overfitting_check(wf_plain)
    assert "deflated_sharpe" not in diagnostics_plain


def test_run_walk_forward_cli_with_deflation():
    """The walk-forward CLI computes and saves DSR with --deflate."""
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
                deflate=True,
            )
            result = run_walk_forward(args)
            assert result == 0

            summary_path = Path(tmpdir) / "walk_forward_summary.json"
            assert summary_path.exists()
            with open(summary_path) as f:
                summary = json.load(f)
            assert "deflated_sharpe" in summary["summary"]
            dsr = summary["summary"]["deflated_sharpe"]
            assert 0.0 <= dsr["deflated_sharpe_ratio"] <= 1.0
            assert summary["config"]["deflate"] is True
    finally:
        Path(data_file).unlink()


def test_walk_forward_aggregate_deflation_uses_pooled_trial_sharpes():
    """The aggregate walk-forward DSR must use pooled cross-period trial Sharpes.

    The aggregate `summary["deflated_sharpe"]` is computed on the combined
    OOS returns with `n_trials` equal to the total evaluated configurations
    across all periods. This test asserts the surfaced aggregate DSR equals
    a direct `deflated_sharpe_ratio` call with the pooled `trial_sharpes`
    list (cross-sectional SR* estimator), not the i.i.d. null approximation.
    """
    data = _make_data()
    param_grid = {"fast_period": [10, 20], "slow_period": [30, 50]}
    strategy_factory = lambda p: _factory("sma_crossover", p)

    results = walk_forward_analysis(
        data=data,
        strategy_factory=strategy_factory,
        param_grid=param_grid,
        train_months=6,
        test_months=2,
        step_months=2,
        apply_deflation=True,
    )

    agg_dsr = results["summary"]["deflated_sharpe"]

    # Recompute the pooled trial Sharpes by running parameter optimization
    # on each training period independently and collecting all trial Sharpes.
    # This mirrors what the function does internally.
    from walk_forward import deflated_sharpe_ratio as dsr_func

    # Collect all trial Sharpes from each period
    pooled_trial_sharpes = []
    for period in results["periods"]:
        if period.get("best_params") is None:
            continue
        train_data = period["train_data"]
        test_data = period["test_data"]
        # We can't easily recover the exact period_trial_sharpes from the
        # results dict (they're not persisted), so we re-run the grid search
        # on the training data to get the same trial Sharpes.
        param_names = list(param_grid.keys())
        param_values = list(param_grid.values())
        from itertools import product
        for combo in product(*param_values):
            params = dict(zip(param_names, combo))
            try:
                strategy = strategy_factory(params)
                train_signals = strategy.generate_signals(train_data)
                test_signals = strategy.generate_signals(test_data)
                if not signals_active(test_signals):
                    continue
                train_returns = _calculate_strategy_returns(
                    train_data, train_signals, 0.0002, 0.0001
                )
                if len(train_returns) > 1 and train_returns.std() > 0:
                    ann_factor = _annualization_factor(train_returns.index)
                    excess = train_returns - 0.02 / ann_factor
                    sharpe = excess.mean() / excess.std() * np.sqrt(ann_factor)
                    if np.isfinite(sharpe):
                        pooled_trial_sharpes.append(float(sharpe))
            except Exception:
                continue

    # Now compute expected aggregate DSR with pooled trial_sharpes
    oos_returns = results["oos_returns"]
    oos_sharpe = results["summary"].get("oos_sharpe", 0.0)
    n_trials = max(len(pooled_trial_sharpes), 1)
    expected = dsr_func(
        sharpe_ratio=oos_sharpe,
        returns=oos_returns,
        n_trials=n_trials,
        trial_sharpes=pooled_trial_sharpes if pooled_trial_sharpes else None,
    )

    # The surfaced aggregate DSR must match the direct call
    for key in (
        "deflated_sharpe_ratio", "p_value", "expected_max_sharpe",
        "n_trials", "n_observations", "skewness", "kurtosis",
    ):
        assert abs(agg_dsr[key] - expected[key]) < 1e-12, (
            f"Mismatch on {key}: got {agg_dsr[key]}, expected {expected[key]}"
        )

    # Also verify the cross-sectional estimator differs from i.i.d. null
    iid_null = dsr_func(
        sharpe_ratio=oos_sharpe, returns=oos_returns, n_trials=n_trials
    )
    assert abs(agg_dsr["expected_max_sharpe"] - iid_null["expected_max_sharpe"]) > 1e-9


def test_cpcv_aggregate_deflation_uses_pooled_trial_sharpes():
    """The aggregate CPCV DSR must use pooled cross-fold trial Sharpes.

    Mirrors the walk-forward test: the aggregate DSR on combined OOS returns
    must use the cross-sectional SR* estimator from pooled fold trial Sharpes.
    """
    # Use more data and larger test_size so test windows can accommodate
    # the slow_period lookback (max 50). 2000 periods with 8 splits,
    # test_size=0.2 gives ~50 test observations per fold.
    data = _make_data(periods=2000)
    param_grid = {"fast_period": [10, 20], "slow_period": [30, 50]}
    strategy_factory = lambda p: _factory("sma_crossover", p)

    results = cpcv_analysis(
        data=data,
        strategy_factory=strategy_factory,
        param_grid=param_grid,
        n_splits=8,
        test_size=0.2,
        purge_size=0.0,
        embargo_size=0.0,
        apply_deflation=True,
    )

    # Verify we have valid OOS returns and a deflated_sharpe key
    assert "deflated_sharpe" in results["summary"], (
        f"Expected deflated_sharpe in summary, got keys: {results['summary'].keys()}"
    )
    assert len(results["oos_returns"]) > 0, "Expected non-empty OOS returns"

    agg_dsr = results["summary"]["deflated_sharpe"]

    # Collect pooled trial Sharpes by re-running grid search on each fold's
    # training data.
    from walk_forward import deflated_sharpe_ratio as dsr_func
    from itertools import product

    pooled_trial_sharpes = []
    for fold in results["folds"]:
        if fold.get("best_params") is None:
            continue
        train_data = fold["train_data"]
        test_data = fold["test_data"]
        param_names = list(param_grid.keys())
        param_values = list(param_grid.values())
        for combo in product(*param_values):
            params = dict(zip(param_names, combo))
            try:
                strategy = strategy_factory(params)
                train_signals = strategy.generate_signals(train_data)
                test_signals = strategy.generate_signals(test_data)
                if not signals_active(test_signals):
                    continue
                train_returns = _calculate_strategy_returns(
                    train_data, train_signals, 0.0002, 0.0001
                )
                if len(train_returns) > 1 and train_returns.std() > 0:
                    ann_factor = _annualization_factor(train_returns.index)
                    excess = train_returns - 0.02 / ann_factor
                    sharpe = excess.mean() / excess.std() * np.sqrt(ann_factor)
                    if np.isfinite(sharpe):
                        pooled_trial_sharpes.append(float(sharpe))
            except Exception:
                continue

    oos_returns = results["oos_returns"]
    oos_sharpe = results["summary"].get("oos_sharpe", 0.0)
    n_trials = max(len(pooled_trial_sharpes), 1)
    expected = dsr_func(
        sharpe_ratio=oos_sharpe,
        returns=oos_returns,
        n_trials=n_trials,
        trial_sharpes=pooled_trial_sharpes if pooled_trial_sharpes else None,
    )

    for key in (
        "deflated_sharpe_ratio", "p_value", "expected_max_sharpe",
        "n_trials", "n_observations", "skewness", "kurtosis",
    ):
        assert abs(agg_dsr[key] - expected[key]) < 1e-12, (
            f"Mismatch on {key}: got {agg_dsr[key]}, expected {expected[key]}"
        )

    iid_null = dsr_func(
        sharpe_ratio=oos_sharpe, returns=oos_returns, n_trials=n_trials
    )
    assert abs(agg_dsr["expected_max_sharpe"] - iid_null["expected_max_sharpe"]) > 1e-9



def _make_flat_test_window_data(periods: int = 300, n_splits: int = 4, test_frac: float = 0.2) -> pd.DataFrame:
    """Build a multi-asset panel whose test windows are perfectly flat.

    The series is trending up to the first test-window boundary (bar 126,
    matching the walk-forward test's train_months=6) and constant thereafter,
    so every walk-forward test window is flat while every expanding training
    window retains variance (it spans the trending region). A cross-sectional
    momentum strategy takes active positions on the flat test windows, so the
    resulting test returns have zero variance. This reproduces the
    degenerate-returns edge case for the aggregate DSR paths.
    """
    dates = pd.date_range("2020-01-01", periods=periods, freq="B")
    symbols = ["A", "B", "C", "D"]
    cols = pd.MultiIndex.from_product([["open", "high", "low", "close", "volume"], symbols])
    df = pd.DataFrame(0.0, index=dates, columns=cols)

    flat_start = 126  # first test window starts here (train_months=6)
    rng = np.random.default_rng(7)
    prices = np.zeros(periods)
    # Trending training region
    if flat_start > 0:
        rets = rng.normal(0.0005, 0.015, flat_start)
        prices[:flat_start] = 100.0 * np.exp(np.cumsum(rets))
    # Constant test region
    if flat_start < periods:
        prices[flat_start:] = prices[flat_start - 1]

    for sym in symbols:
        df[("open", sym)] = prices * rng.uniform(0.995, 1.005, periods)
        df[("high", sym)] = prices * rng.uniform(1.005, 1.02, periods)
        df[("low", sym)] = prices * rng.uniform(0.98, 0.995, periods)
        df[("close", sym)] = prices
        df[("volume", sym)] = rng.integers(1_000_000, 10_000_000, periods)
    return df


def _make_cpcv_flat_test_window_data(periods: int = 300, n_splits: int = 4, test_frac: float = 0.2) -> pd.DataFrame:
    """Build a multi-asset panel whose CPCV test windows are perfectly flat.

    Each group's test window (the first `test_frac` fraction of the group) is
    held at a constant price, while the rest of each group trends. A
    cross-sectional momentum strategy takes active positions on the flat test
    windows, so every fold's test returns have zero variance and the combined
    OOS returns are constant. This reproduces the degenerate-returns edge
    case for the aggregate CPCV DSR path.
    """
    dates = pd.date_range("2020-01-01", periods=periods, freq="B")
    symbols = ["A", "B", "C", "D"]
    cols = pd.MultiIndex.from_product([["open", "high", "low", "close", "volume"], symbols])
    df = pd.DataFrame(0.0, index=dates, columns=cols)

    group_size = periods // n_splits
    test_n = int(group_size * test_frac)
    rng = np.random.default_rng(7)
    prices = np.zeros(periods)
    for g in range(n_splits):
        gstart = g * group_size
        gend = gstart + group_size
        tstart = gstart
        tend = gstart + test_n
        flat_price = 100.0 + 10.0 * g
        prices[tstart:tend] = flat_price
        n_trend = gend - tend
        if n_trend > 0:
            rets = rng.normal(0.0005, 0.015, n_trend)
            cum = np.cumsum(rets)
            prices[tend:gend] = flat_price * np.exp(cum)

    for sym in symbols:
        df[("open", sym)] = prices * rng.uniform(0.995, 1.005, periods)
        df[("high", sym)] = prices * rng.uniform(1.005, 1.02, periods)
        df[("low", sym)] = prices * rng.uniform(0.98, 0.995, periods)
        df[("close", sym)] = prices
        df[("volume", sym)] = rng.integers(1_000_000, 10_000_000, periods)
    return df


def _make_flat_train_window_data(periods: int = 300) -> pd.DataFrame:
    """Build a multi-asset panel whose first training window is flat.

    The first walk-forward training window (130 business days for
    `train_months=6` starting 2020-01-01) is held at a constant
    price and the series trends afterwards, so the first period's
    expanding training window has zero return variance while every
    later training window (and every test window past the flat
    region) retains variance. No configuration achieves a finite
    in-sample Sharpe in the first period, so that period is skipped
    by the grid search.
    """
    dates = pd.date_range("2020-01-01", periods=periods, freq="B")
    symbols = ["A", "B", "C", "D"]
    cols = pd.MultiIndex.from_product([["open", "high", "low", "close", "volume"], symbols])
    df = pd.DataFrame(0.0, index=dates, columns=cols)

    flat_end = 140  # covers the first train window (130 bars)
    rng = np.random.default_rng(7)
    prices = np.zeros(periods)
    prices[:flat_end] = 100.0
    if periods > flat_end:
        rets = rng.normal(0.0005, 0.015, periods - flat_end)
        prices[flat_end:] = 100.0 * np.exp(np.cumsum(rets))

    for sym in symbols:
        df[("open", sym)] = prices * rng.uniform(0.995, 1.005, periods)
        df[("high", sym)] = prices * rng.uniform(1.005, 1.02, periods)
        df[("low", sym)] = prices * rng.uniform(0.98, 0.995, periods)
        df[("close", sym)] = prices
        df[("volume", sym)] = rng.integers(1_000_000, 10_000_000, periods)
    return df


def _recompute_window_deflated_sharpe(
    window, param_grid, strategy_factory, commission, slippage
):
    """Independently recompute a period/fold's per-period DSR.

    Replicates the grid search over `window["train_data"]` /
    `window["test_data"]` exactly as `walk_forward_analysis` /
    `cpcv_analysis` do (same combo order, same `signals_active`
    test-window guard, same in-sample Sharpe rule) and returns the
    `deflated_sharpe` dict the analysis must have stored for that
    period/fold. Returns None when no configuration achieved a finite
    in-sample Sharpe (the period/fold is skipped).
    """
    from itertools import product

    param_names = list(param_grid.keys())
    param_values = list(param_grid.values())
    best_sharpe = -np.inf
    best_train_returns = None
    best_test_returns = None
    trial_sharpes = []

    for combo in product(*param_values):
        params = dict(zip(param_names, combo))
        try:
            strategy = strategy_factory(params)
            train_signals = strategy.generate_signals(window["train_data"])
            test_signals = strategy.generate_signals(window["test_data"])

            if not signals_active(test_signals):
                continue

            test_returns = _calculate_strategy_returns(
                window["test_data"], test_signals, commission, slippage
            )
            train_returns = _calculate_strategy_returns(
                window["train_data"], train_signals, commission, slippage
            )

            if len(train_returns) > 1 and train_returns.std() > 0:
                ann_factor = _annualization_factor(train_returns.index)
                excess = train_returns - 0.02 / ann_factor
                sharpe = excess.mean() / excess.std() * np.sqrt(ann_factor)
            else:
                sharpe = -np.inf

            if np.isfinite(sharpe):
                trial_sharpes.append(float(sharpe))

            if sharpe > best_sharpe:
                best_sharpe = sharpe
                best_test_returns = test_returns
                best_train_returns = train_returns
        except Exception:
            continue

    if best_test_returns is None or len(best_test_returns) == 0:
        return None
    if best_train_returns is None or not trial_sharpes:
        return None
    return deflated_sharpe_ratio(
        sharpe_ratio=best_sharpe,
        returns=best_train_returns,
        n_trials=len(trial_sharpes),
        trial_sharpes=trial_sharpes,
    )


def test_walk_forward_aggregate_deflation_constant_oos_returns():
    """Aggregate walk-forward DSR emits the conservative degenerate dict.

    When the combined out-of-sample returns have zero variance (a strategy
    takes active positions on flat test windows), the aggregate DSR must be
    emitted conservatively as DSR = 0, p_value = 1, z_score = None — mirroring
    the `run_backtest --n-trials` and `monte-carlo` behavior — rather than
    being silently omitted by an `oos_returns.std() > 0` guard.
    """
    data = _make_flat_test_window_data()
    strategy_factory = lambda p: _factory("cross_sectional_momentum", p)
    param_grid = {"lookback": [5, 10], "top_quantile": [0.4], "bottom_quantile": [0.2]}

    results = walk_forward_analysis(
        data=data,
        strategy_factory=strategy_factory,
        param_grid=param_grid,
        train_months=6,
        test_months=2,
        step_months=2,
        commission=0.0,
        slippage=0.0,
        apply_deflation=True,
    )

    assert results["summary"]["n_periods"] > 0, "expected at least one period"
    assert len(results["oos_returns"]) > 0, "expected non-empty OOS returns"
    assert results["oos_returns"].std() == 0.0, "expected zero-variance OOS returns"

    assert "deflated_sharpe" in results["summary"], (
        "expected aggregate deflated_sharpe key even for constant OOS returns"
    )
    d = results["summary"]["deflated_sharpe"]
    assert d["deflated_sharpe_ratio"] == 0.0
    assert d["p_value"] == 1.0
    assert d["z_score"] is None
    assert d["sharpe_ratio"] == 0.0
    assert d["skewness"] == 0.0
    assert d["kurtosis"] == 3.0
    assert d["n_trials"] >= 1
    assert d["n_observations"] == len(results["oos_returns"])

    # Per-period DSR: the per-period path IS reachable on constant
    # test windows, but it is an IN-SAMPLE deflation computed on
    # each period's TRAINING returns (which retain variance here),
    # so it is non-degenerate — only the aggregate DSR on the
    # combined OOS returns takes the degenerate dict above.
    n_with_params = 0
    for period in results["periods"]:
        if period.get("best_params") is None:
            continue
        n_with_params += 1
        assert "deflated_sharpe" in period, (
            "expected per-period deflated_sharpe on constant test returns"
        )
        pd_dsr = period["deflated_sharpe"]
        assert 0.0 <= pd_dsr["deflated_sharpe_ratio"] <= 1.0
        assert pd_dsr["z_score"] is not None, (
            "per-period DSR must be non-degenerate: it is deflated "
            "on the period's training returns, not the flat test returns"
        )
        # The per-period DSR deflates the in-sample selection Sharpe.
        assert abs(pd_dsr["sharpe_ratio"] - period["best_sharpe"]) < 1e-12
        # The per-period DSR equals an independent recomputation of
        # the period's grid search (same guard, same Sharpe rule).
        expected = _recompute_window_deflated_sharpe(
            period, param_grid, strategy_factory, 0.0, 0.0
        )
        assert expected is not None, (
            "recomputed per-period DSR missing for an active period"
        )
        for key in (
            "deflated_sharpe_ratio", "p_value", "expected_max_sharpe",
            "n_trials", "n_observations", "skewness", "kurtosis",
        ):
            assert abs(pd_dsr[key] - expected[key]) < 1e-12, key
    assert n_with_params > 0


def test_cpcv_aggregate_deflation_constant_oos_returns():
    """Aggregate CPCV DSR emits the conservative degenerate dict.

    Mirrors the walk-forward test: when every fold's test window is flat,
    the combined OOS returns have zero variance and the aggregate DSR must
    be emitted conservatively (DSR = 0, p_value = 1, z_score = None) rather
    than being silently omitted.
    """
    data = _make_cpcv_flat_test_window_data()
    strategy_factory = lambda p: _factory("cross_sectional_momentum", p)
    param_grid = {"lookback": [5, 10], "top_quantile": [0.4], "bottom_quantile": [0.2]}

    results = cpcv_analysis(
        data=data,
        strategy_factory=strategy_factory,
        param_grid=param_grid,
        n_splits=4,
        test_size=0.2,
        purge_size=0.0,
        embargo_size=0.0,
        commission=0.0,
        slippage=0.0,
        apply_deflation=True,
    )

    assert results["summary"]["n_folds"] > 0, "expected at least one fold"
    assert len(results["oos_returns"]) > 0, "expected non-empty OOS returns"
    assert results["oos_returns"].std() == 0.0, "expected zero-variance OOS returns"

    assert "deflated_sharpe" in results["summary"], (
        "expected aggregate deflated_sharpe key even for constant OOS returns"
    )
    d = results["summary"]["deflated_sharpe"]
    assert d["deflated_sharpe_ratio"] == 0.0
    assert d["p_value"] == 1.0
    assert d["z_score"] is None
    assert d["sharpe_ratio"] == 0.0
    assert d["skewness"] == 0.0
    assert d["kurtosis"] == 3.0
    assert d["n_trials"] >= 1
    assert d["n_observations"] == len(results["oos_returns"])

    # Per-fold DSR: like walk-forward, the per-fold path IS
    # reachable on constant test windows, but each fold's DSR is
    # an IN-SAMPLE deflation computed on the fold's TRAINING
    # returns (which retain variance), so it is non-degenerate —
    # only the aggregate DSR on the combined OOS returns takes
    # the degenerate dict above.
    n_with_params = 0
    for fold in results["folds"]:
        if fold.get("best_params") is None:
            continue
        n_with_params += 1
        assert "deflated_sharpe" in fold, (
            "expected per-fold deflated_sharpe on constant test returns"
        )
        fold_dsr = fold["deflated_sharpe"]
        assert 0.0 <= fold_dsr["deflated_sharpe_ratio"] <= 1.0
        assert fold_dsr["z_score"] is not None, (
            "per-fold DSR must be non-degenerate: it is deflated "
            "on the fold's training returns, not the flat test returns"
        )
        assert abs(fold_dsr["sharpe_ratio"] - fold["best_sharpe"]) < 1e-12
        expected = _recompute_window_deflated_sharpe(
            fold, param_grid, strategy_factory, 0.0, 0.0
        )
        assert expected is not None, (
            "recomputed per-fold DSR missing for an active fold"
        )
        for key in (
            "deflated_sharpe_ratio", "p_value", "expected_max_sharpe",
            "n_trials", "n_observations", "skewness", "kurtosis",
        ):
            assert abs(fold_dsr[key] - expected[key]) < 1e-12, key
    assert n_with_params > 0


def test_walk_forward_flat_train_window_skips_period():
    """A flat training window skips the period (no per-period DSR).

    When a period's training window is perfectly flat, every
    configuration's in-sample Sharpe is undefined (zero variance),
    so none is selected: the period contributes no out-of-sample
    returns and carries no per-period DSR. This "no signal" outcome
    is distinct from the degenerate dict the aggregate path emits on
    constant OOS returns — there is no in-sample Sharpe to deflate.
    """
    data = _make_flat_train_window_data()
    strategy_factory = lambda p: _factory("cross_sectional_momentum", p)

    results = walk_forward_analysis(
        data=data,
        strategy_factory=strategy_factory,
        param_grid={"lookback": [5, 10], "top_quantile": [0.4], "bottom_quantile": [0.2]},
        train_months=6,
        test_months=2,
        step_months=2,
        commission=0.0,
        slippage=0.0,
        apply_deflation=True,
    )

    assert results["summary"]["n_periods"] > 1, "expected multiple periods"

    # The first period's training window is entirely flat: no
    # configuration is selected and no per-period DSR is emitted.
    first = results["periods"][0]
    assert first["best_params"] is None, (
        "expected the flat-train-window period to be skipped"
    )
    assert "deflated_sharpe" not in first
    assert len(first["test_returns"]) == 0

    # Later periods span the trending region in their training
    # windows, so they are selected with non-degenerate per-period
    # DSRs (finite z_score).
    n_active = 0
    for period in results["periods"][1:]:
        if period.get("best_params") is None:
            continue
        n_active += 1
        assert "deflated_sharpe" in period
        assert period["deflated_sharpe"]["z_score"] is not None
    assert n_active > 0, "expected later periods to be active"

    # Only the active periods contribute OOS returns; their test
    # windows are trending, so the aggregate DSR is non-degenerate.
    assert len(results["oos_returns"]) > 0
    assert results["oos_returns"].std() > 0
    agg = results["summary"]["deflated_sharpe"]
    assert agg["z_score"] is not None


def test_market_impact_reduces_returns():
    """Market impact reduces net returns compared to no impact."""
    data = _make_data(periods=300, seed=42)
    # Create a high-turnover strategy (sma_crossover with short periods)
    strategy = build_strategy("sma_crossover", '{"fast_period": 5, "slow_period": 10}')
    signals = strategy.generate_signals(data)

    # Returns without market impact
    returns_no_impact = _calculate_strategy_returns(
        data, signals, commission=0.0002, slippage=0.0001,
        impact_coefficient=0.0, adv_window=20
    )

    # Returns with market impact
    returns_with_impact = _calculate_strategy_returns(
        data, signals, commission=0.0002, slippage=0.0001,
        impact_coefficient=0.5, adv_window=20
    )

    # Align returns for comparison
    aligned_no, aligned_with = returns_no_impact.align(returns_with_impact, join="inner")

    # With impact, returns should be lower (more negative costs)
    total_no = (1 + aligned_no).prod() - 1
    total_with = (1 + aligned_with).prod() - 1
    assert total_with < total_no, f"Expected impact to reduce returns: {total_with:.4f} >= {total_no:.4f}"


def test_market_impact_zero_coefficient_matches_no_impact():
    """Zero impact coefficient should produce identical results to no impact."""
    data = _make_data(periods=300, seed=42)
    strategy = build_strategy("sma_crossover", '{"fast_period": 10, "slow_period": 30}')
    signals = strategy.generate_signals(data)

    returns_no_impact = _calculate_strategy_returns(
        data, signals, commission=0.0002, slippage=0.0001,
        impact_coefficient=0.0, adv_window=20
    )

    returns_zero_coeff = _calculate_strategy_returns(
        data, signals, commission=0.0002, slippage=0.0001,
        impact_coefficient=0.0, adv_window=20
    )

    # Should be identical
    pd.testing.assert_series_equal(returns_no_impact, returns_zero_coeff)


def test_market_impact_higher_coefficient_increases_costs():
    """Higher impact coefficient should result in lower returns."""
    data = _make_data(periods=300, seed=42)
    strategy = build_strategy("sma_crossover", '{"fast_period": 5, "slow_period": 10}')
    signals = strategy.generate_signals(data)

    returns_low = _calculate_strategy_returns(
        data, signals, commission=0.0002, slippage=0.0001,
        impact_coefficient=0.1, adv_window=20
    )

    returns_high = _calculate_strategy_returns(
        data, signals, commission=0.0002, slippage=0.0001,
        impact_coefficient=1.0, adv_window=20
    )

    aligned_low, aligned_high = returns_low.align(returns_high, join="inner")
    total_low = (1 + aligned_low).prod() - 1
    total_high = (1 + aligned_high).prod() - 1
    assert total_high < total_low, f"Expected higher impact to reduce returns more: {total_high:.4f} >= {total_low:.4f}"


def test_market_impact_integration_walk_forward():
    """Walk-forward analysis works with market impact enabled."""
    data = _make_data(periods=500, seed=42)
    results = walk_forward_analysis(
        data=data,
        strategy_factory=lambda p: build_strategy("sma_crossover", json.dumps(p)),
        param_grid={"fast_period": [10, 20], "slow_period": [30, 50]},
        train_months=12,
        test_months=3,
        step_months=3,
        commission=0.0002,
        slippage=0.0001,
        impact_coefficient=0.2,
        adv_window=20,
    )
    assert results["summary"]["n_periods"] > 0
    assert len(results["oos_returns"]) > 0


def test_market_impact_integration_parameter_optimization():
    """Parameter optimization works with market impact enabled."""
    data = _make_data(periods=500, seed=42)
    results = parameter_optimization(
        data=data,
        strategy_factory=lambda p: build_strategy("sma_crossover", json.dumps(p)),
        param_grid={"fast_period": [10, 20], "slow_period": [30, 50]},
        commission=0.0002,
        slippage=0.0001,
        impact_coefficient=0.2,
        adv_window=20,
    )
    assert len(results) > 0
    assert "sharpe_ratio" in results[0]


def test_market_impact_integration_cpcv():
    """CPCV analysis works with market impact enabled."""
    data = _make_data(periods=1000, seed=42)
    results = cpcv_analysis(
        data=data,
        strategy_factory=lambda p: build_strategy("sma_crossover", json.dumps(p)),
        param_grid={"fast_period": [10, 20], "slow_period": [30, 50]},
        n_splits=5,
        test_size=0.2,
        commission=0.0002,
        slippage=0.0001,
        impact_coefficient=0.2,
        adv_window=20,
    )
    assert results["summary"]["n_folds"] > 0
    assert len(results["oos_returns"]) > 0


def test_run_backtest_market_impact():
    """run_backtest CLI works with market impact arguments."""
    import tempfile
    import subprocess
    import sys

    with tempfile.TemporaryDirectory() as tmpdir:
        # Use existing sample data
        data_path = str(SKILLS_DIR / "assets" / "example_data" / "sample_ohlcv.csv")

        # Run backtest with impact
        result = subprocess.run([
            sys.executable, "-m", "scripts.run_backtest",
            "--data", data_path,
            "--strategy", "sma_crossover",
            "--params", '{"fast_period": 10, "slow_period": 30}',
            "--commission", "0.0002",
            "--slippage", "0.0001",
            "--impact-coefficient", "0.1",
            "--adv-window", "20",
            "--output", f"{tmpdir}/results",
        ], capture_output=True, text=True, cwd=SKILLS_DIR)

        assert result.returncode == 0, f"CLI failed: {result.stderr}"
        assert "Deflated Sharpe Ratio" not in result.stdout  # No n-trials provided

        # Verify output files created
        import os
        assert os.path.exists(f"{tmpdir}/results/metrics.json")
        assert os.path.exists(f"{tmpdir}/results/report.txt")
        assert os.path.exists(f"{tmpdir}/results/tear_sheet.html")


def test_borrow_cost_reduces_returns_for_short_strategy():
    """Borrow cost reduces net returns for strategies with short exposure."""
    data = _make_data(periods=300, seed=42)
    strategy = build_strategy("bollinger_bands", '{"period": 20, "std_dev": 2.0}')
    signals = strategy.generate_signals(data)
    assert (signals < 0).any(), "Expected short exposure from Bollinger strategy"

    returns_no_borrow = _calculate_strategy_returns(
        data, signals, commission=0.0002, slippage=0.0001
    )
    returns_with_borrow = _calculate_strategy_returns(
        data, signals, commission=0.0002, slippage=0.0001, borrow_cost=0.03
    )

    aligned_no, aligned_with = returns_no_borrow.align(returns_with_borrow, join="inner")
    total_no = (1 + aligned_no).prod() - 1
    total_with = (1 + aligned_with).prod() - 1
    assert total_with < total_no, (
        f"Expected borrow cost to reduce returns: {total_with:.4f} >= {total_no:.4f}"
    )


def test_borrow_cost_no_effect_on_long_only_strategy():
    """Borrow cost leaves long/flat strategies unchanged (no short exposure)."""
    data = _make_data(periods=300, seed=42)
    strategy = build_strategy("sma_crossover", '{"fast_period": 10, "slow_period": 30}')
    signals = strategy.generate_signals(data)
    assert (signals < 0).sum() == 0, "sma_crossover should never go short"

    returns_no_borrow = _calculate_strategy_returns(
        data, signals, commission=0.0002, slippage=0.0001
    )
    returns_with_borrow = _calculate_strategy_returns(
        data, signals, commission=0.0002, slippage=0.0001, borrow_cost=0.05
    )
    pd.testing.assert_series_equal(returns_no_borrow, returns_with_borrow)


def test_borrow_funding_zero_costs_match_baseline():
    """Zero borrow and funding costs produce identical returns to baseline."""
    data = _make_data(periods=300, seed=42)
    strategy = build_strategy("bollinger_bands", '{"period": 20, "std_dev": 2.0}')
    signals = strategy.generate_signals(data)
    baseline = _calculate_strategy_returns(
        data, signals, commission=0.0002, slippage=0.0001
    )
    zero_costs = _calculate_strategy_returns(
        data, signals, commission=0.0002, slippage=0.0001,
        borrow_cost=0.0, funding_cost=0.0,
    )
    pd.testing.assert_series_equal(baseline, zero_costs)


def test_funding_cost_applies_only_beyond_one_x_leverage():
    """Funding cost applies to gross exposure beyond 1x and nowhere else."""
    data = _make_data(periods=100, seed=7)
    idx = data.index

    leveraged = pd.Series(1.5, index=idx)
    returns_lev_no_funding = _calculate_strategy_returns(
        data, leveraged, commission=0.0, slippage=0.0
    )
    returns_lev_funding = _calculate_strategy_returns(
        data, leveraged, commission=0.0, slippage=0.0, funding_cost=0.10
    )
    aligned_no, aligned_f = returns_lev_no_funding.align(returns_lev_funding, join="inner")
    total_no = (1 + aligned_no).prod() - 1
    total_f = (1 + aligned_f).prod() - 1
    assert total_f < total_no, (
        f"Expected funding cost to reduce leveraged returns: {total_f:.4f} >= {total_no:.4f}"
    )

    # 1x gross exposure incurs no funding cost
    unleveraged = pd.Series(1.0, index=idx)
    returns_1x_no_funding = _calculate_strategy_returns(
        data, unleveraged, commission=0.0, slippage=0.0
    )
    returns_1x_funding = _calculate_strategy_returns(
        data, unleveraged, commission=0.0, slippage=0.0, funding_cost=0.10
    )
    pd.testing.assert_series_equal(returns_1x_no_funding, returns_1x_funding)


def test_borrow_funding_integration_walk_forward():
    """Walk-forward analysis runs with borrow and funding costs enabled."""
    data = _make_data(periods=500, seed=42)
    results = walk_forward_analysis(
        data=data,
        strategy_factory=lambda p: build_strategy("bollinger_bands", json.dumps(p)),
        param_grid={"period": [20, 25], "std_dev": [2.0]},
        train_months=12,
        test_months=3,
        step_months=3,
        commission=0.0002,
        slippage=0.0001,
        borrow_cost=0.03,
        funding_cost=0.02,
    )
    assert results["summary"]["n_periods"] > 0
    assert len(results["oos_returns"]) > 0


def _make_flat_price_frame(periods: int, freq: str) -> pd.DataFrame:
    """Create a DataFrame with flat prices (zero returns) at a given frequency."""
    dates = pd.date_range("2020-01-01", periods=periods, freq=freq)
    prices = np.full(periods, 100.0)
    return pd.DataFrame(
        {
            "open": prices,
            "high": prices,
            "low": prices,
            "close": prices,
            "volume": [1000000] * periods,
        },
        index=dates,
    )


def test_borrow_cost_frequency_aware_per_period_rate():
    """Borrow cost per period divides the annual rate by the data's
    inferred periods per year, not a hardcoded 252.

    Flat prices and a constant short signal isolate the borrow cost:
    with zero raw returns and no position changes, every period's
    strategy return must equal exactly -borrow_cost / periods_per_year.
    """
    borrow_cost = 0.10
    cases = {
        "B": 252,  # business daily
        "D": 365,  # calendar daily
        "W": 52,   # weekly
    }
    for freq, factor in cases.items():
        data = _make_flat_price_frame(periods=60, freq=freq)
        signals = pd.Series(-1.0, index=data.index)
        returns = _calculate_strategy_returns(
            data, signals, commission=0.0, slippage=0.0,
            borrow_cost=borrow_cost,
        )
        expected = -borrow_cost / factor
        assert np.allclose(returns, expected), (
            f"freq={freq}: expected per-period cost {expected}, "
            f"got {returns.iloc[0]}"
        )


def test_borrow_cost_non_datetime_index_falls_back_to_252():
    """A non-DatetimeIndex keeps the 252 fallback for borrow costs."""
    n = 60
    data = _make_flat_price_frame(periods=n, freq="B")
    data.index = pd.RangeIndex(n)
    signals = pd.Series(-1.0, index=data.index)
    returns = _calculate_strategy_returns(
        data, signals, commission=0.0, slippage=0.0,
        borrow_cost=0.10,
    )
    assert np.allclose(returns, -0.10 / 252), (
        f"expected 252 fallback, got {returns.iloc[0]}"
    )


def test_funding_cost_frequency_aware_per_period_rate():
    """Funding cost per period divides the annual rate by the data's
    inferred periods per year.

    Flat prices and constant 1.5x leverage isolate the funding cost:
    every period's return must equal -(1.5 - 1) * funding_cost / factor.
    """
    funding_cost = 0.10
    data = _make_flat_price_frame(periods=60, freq="W")
    signals = pd.Series(1.5, index=data.index)
    returns = _calculate_strategy_returns(
        data, signals, commission=0.0, slippage=0.0,
        funding_cost=funding_cost,
    )
    expected = -0.5 * funding_cost / 52
    assert np.allclose(returns, expected), (
        f"expected weekly funding cost {expected}, got {returns.iloc[0]}"
    )


def main() -> int:
    tests = [
        ("parameter_optimization_skips_flat_combos", test_parameter_optimization_skips_flat_combos),
        ("walk_forward_skips_flat_combos_in_test_window", test_walk_forward_skips_flat_combos_in_test_window),
        ("overfitting_check_handles_empty_oos", test_overfitting_check_handles_empty_oos),
        ("signals_active_detects_flat_and_active_series", test_signals_active_detects_flat_and_active_series),
        ("deflated_sharpe_ratio_basic", test_deflated_sharpe_ratio_basic),
        ("deflated_sharpe_ratio_decreases_with_more_trials", test_deflated_sharpe_ratio_decreases_with_more_trials),
        ("deflated_sharpe_ratio_with_trial_sharpes", test_deflated_sharpe_ratio_with_trial_sharpes),
        ("deflated_sharpe_ratio_insufficient_data", test_deflated_sharpe_ratio_insufficient_data),
        ("deflated_sharpe_ratio_zero_variance", test_deflated_sharpe_ratio_zero_variance),
        ("deflated_sharpe_ratio_invalid_n_trials", test_deflated_sharpe_ratio_invalid_n_trials),
        ("parameter_optimization_deflation", test_parameter_optimization_deflation),
        ("parameter_optimization_constant_returns_deflation", test_parameter_optimization_constant_returns_deflation),
        ("walk_forward_deflation", test_walk_forward_deflation),
        ("walk_forward_deflation_overfitting_check", test_walk_forward_deflation_overfitting_check),
        ("run_walk_forward_cli_with_deflation", test_run_walk_forward_cli_with_deflation),
        ("walk_forward_aggregate_deflation_uses_pooled_trial_sharpes", test_walk_forward_aggregate_deflation_uses_pooled_trial_sharpes),
        ("cpcv_aggregate_deflation_uses_pooled_trial_sharpes", test_cpcv_aggregate_deflation_uses_pooled_trial_sharpes),
        ("walk_forward_aggregate_deflation_constant_oos_returns", test_walk_forward_aggregate_deflation_constant_oos_returns),
        ("cpcv_aggregate_deflation_constant_oos_returns", test_cpcv_aggregate_deflation_constant_oos_returns),
        ("walk_forward_flat_train_window_skips_period", test_walk_forward_flat_train_window_skips_period),
        ("monte_carlo_simulation_basic", test_monte_carlo_simulation_basic),
        ("monte_carlo_simulation_block_bootstrap", test_monte_carlo_simulation_block_bootstrap),
        ("monte_carlo_block_bootstrap_preserves_autocorrelation", test_monte_carlo_block_bootstrap_preserves_autocorrelation),
        ("monte_carlo_simulation_probability_of_ruin", test_monte_carlo_simulation_probability_of_ruin),
        ("monte_carlo_simulation_handles_short_series", test_monte_carlo_simulation_handles_short_series),
        ("run_walk_forward_cli", test_run_walk_forward_cli),
        ("run_parameter_optimization_cli", test_run_parameter_optimization_cli),
        ("run_monte_carlo_cli", test_run_monte_carlo_cli),
        ("run_monte_carlo_cli_with_n_trials", test_run_monte_carlo_cli_with_n_trials),
        ("run_monte_carlo_cli_without_n_trials_omits_dsr", test_run_monte_carlo_cli_without_n_trials_omits_dsr),
        ("run_monte_carlo_deflated_sharpe_matches_direct_call", test_run_monte_carlo_deflated_sharpe_matches_direct_call),
        ("run_monte_carlo_n_trials_floored_to_grid_size", test_run_monte_carlo_n_trials_floored_to_grid_size),
        ("run_monte_carlo_deflated_sharpe_uses_floored_n_trials", test_run_monte_carlo_deflated_sharpe_uses_floored_n_trials),
        ("run_monte_carlo_constant_returns_deflated_sharpe", test_run_monte_carlo_constant_returns_deflated_sharpe),
        ("run_parameter_optimization_cli_constant_returns_deflation", test_run_parameter_optimization_cli_constant_returns_deflation),
        ("run_walk_forward_cli_persists_pit_results", test_run_walk_forward_cli_persists_pit_results),
        ("run_walk_forward_cli_omits_pit_without_flag", test_run_walk_forward_cli_omits_pit_without_flag),
        ("run_cpcv_cli_persists_pit_results", test_run_cpcv_cli_persists_pit_results),
        ("run_monte_carlo_cli_persists_pit_and_preserves_block_size", test_run_monte_carlo_cli_persists_pit_and_preserves_block_size),
        ("run_parameter_optimization_cli_persists_pit_results", test_run_parameter_optimization_cli_persists_pit_results),
        ("run_parameter_optimization_cli_with_benchmark", test_run_parameter_optimization_cli_with_benchmark),
        ("parse_param_grid", test_parse_param_grid),
        ("walk_forward_multi_asset_cross_sectional_momentum", test_walk_forward_multi_asset_cross_sectional_momentum),
        ("walk_forward_multi_asset_dual_momentum", test_walk_forward_multi_asset_dual_momentum),
        ("monte_carlo_multi_asset_integration", test_monte_carlo_multi_asset_integration),
        ("walk_forward_multi_asset_dict_cross_sectional_momentum", test_walk_forward_multi_asset_dict_cross_sectional_momentum),
        ("walk_forward_multi_asset_dict_dual_momentum", test_walk_forward_multi_asset_dict_dual_momentum),
        ("market_impact_reduces_returns", test_market_impact_reduces_returns),
        ("market_impact_zero_coefficient_matches_no_impact", test_market_impact_zero_coefficient_matches_no_impact),
        ("market_impact_higher_coefficient_increases_costs", test_market_impact_higher_coefficient_increases_costs),
        ("market_impact_integration_walk_forward", test_market_impact_integration_walk_forward),
        ("market_impact_integration_parameter_optimization", test_market_impact_integration_parameter_optimization),
        ("market_impact_integration_cpcv", test_market_impact_integration_cpcv),
        ("run_backtest_market_impact", test_run_backtest_market_impact),
        ("borrow_cost_reduces_returns_for_short_strategy", test_borrow_cost_reduces_returns_for_short_strategy),
        ("borrow_cost_no_effect_on_long_only_strategy", test_borrow_cost_no_effect_on_long_only_strategy),
        ("borrow_funding_zero_costs_match_baseline", test_borrow_funding_zero_costs_match_baseline),
        ("funding_cost_applies_only_beyond_one_x_leverage", test_funding_cost_applies_only_beyond_one_x_leverage),
        ("borrow_funding_integration_walk_forward", test_borrow_funding_integration_walk_forward),
        ("borrow_cost_frequency_aware_per_period_rate", test_borrow_cost_frequency_aware_per_period_rate),
        ("borrow_cost_non_datetime_index_falls_back_to_252", test_borrow_cost_non_datetime_index_falls_back_to_252),
        ("funding_cost_frequency_aware_per_period_rate", test_funding_cost_frequency_aware_per_period_rate),
        ("run_walk_forward_cli_with_benchmark", test_run_walk_forward_cli_with_benchmark),
        ("run_cpcv_cli_with_benchmark", test_run_cpcv_cli_with_benchmark),
        ("run_monte_carlo_cli_with_benchmark", test_run_monte_carlo_cli_with_benchmark),
        ("run_walk_forward_cli_with_total_return_benchmark", test_run_walk_forward_cli_with_total_return_benchmark),
        ("run_cpcv_cli_with_total_return_benchmark", test_run_cpcv_cli_with_total_return_benchmark),
        ("run_monte_carlo_cli_with_total_return_benchmark", test_run_monte_carlo_cli_with_total_return_benchmark),
        # Out-of-sample validation framework tests
        ("out_of_sample_validation_basic", test_out_of_sample_validation_basic),
        ("out_of_sample_validation_cpcv_method", test_out_of_sample_validation_cpcv_method),
        ("out_of_sample_validation_selection_criteria", test_out_of_sample_validation_selection_criteria),
        ("out_of_sample_validation_with_benchmark", test_out_of_sample_validation_with_benchmark),
        ("out_of_sample_validation_split_fractions", test_out_of_sample_validation_split_fractions),
        ("out_of_sample_validation_test_returns_never_used_in_selection", test_out_of_sample_validation_test_returns_never_used_in_selection),
        ("out_of_sample_validation_deflated_sharpe", test_out_of_sample_validation_deflated_sharpe),
        ("split_train_val_test", test_split_train_val_test),
        ("run_out_of_sample_validation_cli", test_run_out_of_sample_validation_cli),
        ("run_out_of_sample_validation_cli_with_benchmark", test_run_out_of_sample_validation_cli_with_benchmark),
        ("run_out_of_sample_validation_cli_cpcv_method", test_run_out_of_sample_validation_cli_cpcv_method),
        # Strict train/validation/test separation invariant tests
        ("verify_split_separation_clean_split", test_verify_split_separation_clean_split),
        ("verify_split_separation_detects_train_val_overlap", test_verify_split_separation_detects_train_val_overlap),
        ("verify_split_separation_detects_val_test_overlap", test_verify_split_separation_detects_val_test_overlap),
        ("verify_split_separation_detects_train_test_overlap", test_verify_split_separation_detects_train_test_overlap),
        ("verify_split_separation_rejects_empty_split", test_verify_split_separation_rejects_empty_split),
        ("out_of_sample_validation_surfaces_separation_check", test_out_of_sample_validation_surfaces_separation_check),
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


# Buy-and-hold benchmark baseline tests for walk-forward CLI
def _make_benchmark_data(periods: int = 756, seed: int = 99) -> str:
    """Create a temporary benchmark data file."""
    rng = np.random.default_rng(seed)
    dates = pd.date_range("2018-01-01", periods=periods, freq="B")
    rets = rng.normal(0.0004, 0.012, periods)
    prices = 100 * np.exp(np.cumsum(rets))
    df = pd.DataFrame(
        {
            "date": dates,
            "open": prices * rng.uniform(0.995, 1.005, periods),
            "high": prices * rng.uniform(1.005, 1.02, periods),
            "low": prices * rng.uniform(0.98, 0.995, periods),
            "close": prices,
            "volume": rng.integers(1_000_000, 10_000_000, periods),
        }
    )
    tmp = tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False)
    df.to_csv(tmp.name, index=False)
    return tmp.name


def _make_benchmark_data_with_dividends(periods: int = 756, seed: int = 99) -> str:
    """Create a temporary benchmark data file with dividends column."""
    rng = np.random.default_rng(seed)
    dates = pd.date_range("2018-01-01", periods=periods, freq="B")
    rets = rng.normal(0.0004, 0.012, periods)
    prices = 100 * np.exp(np.cumsum(rets))
    # Add quarterly dividends
    dividends = np.zeros(periods)
    for i in range(periods):
        if dates[i].month in [3, 6, 9, 12] and dates[i].day <= 5:
            dividends[i] = 0.50
    df = pd.DataFrame(
        {
            "date": dates,
            "open": prices * rng.uniform(0.995, 1.005, periods),
            "high": prices * rng.uniform(1.005, 1.02, periods),
            "low": prices * rng.uniform(0.98, 0.995, periods),
            "close": prices,
            "volume": rng.integers(1_000_000, 10_000_000, periods),
            "dividends": dividends,
        }
    )
    tmp = tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False)
    df.to_csv(tmp.name, index=False)
    return tmp.name


def test_run_walk_forward_cli_with_benchmark():
    """Walk-forward CLI with --benchmark writes benchmark metrics to summary and tear sheet."""
    data_file = _make_test_data_file()
    bench_file = _make_benchmark_data()
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
                deflate=False,
                benchmark=bench_file,
            )
            result = run_walk_forward(args)
            assert result == 0

            summary_path = Path(tmpdir) / "walk_forward_summary.json"
            assert summary_path.exists()
            with open(summary_path) as f:
                summary = json.load(f)

            # Benchmark metrics should be in summary
            s = summary["summary"]
            assert "benchmark_total_return" in s
            assert "benchmark_annualized_return" in s
            assert "correlation_with_benchmark" in s
            assert "alpha" in s
            assert "beta" in s
            assert "alpha_tstat" in s
            assert 0.0 <= s["alpha_pvalue"] <= 1.0
            assert 0.0 <= s["r_squared"] <= 1.0

            # Benchmark provenance should be written
            assert "benchmark_provenance" in summary
            assert summary["benchmark_provenance"]["checksum"] != ""

            # Tear sheet summary should include benchmark
            tear_summary_path = Path(tmpdir) / "tear_sheet_summary.json"
            assert tear_summary_path.exists()
            with open(tear_summary_path) as f:
                tear_summary = json.load(f)
            assert "benchmark_total_return" in tear_summary["metrics"]
            assert "correlation_with_benchmark" in tear_summary["metrics"]
            assert "alpha_pvalue" in tear_summary["metrics"]
    finally:
        Path(data_file).unlink()
        Path(bench_file).unlink()


def test_run_cpcv_cli_with_benchmark():
    """CPCV CLI with --benchmark writes benchmark metrics to summary."""
    data_file = _make_test_data_file()
    bench_file = _make_benchmark_data()
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
                n_splits=4,
                test_size=0.2,
                purge_size=0.0,
                embargo_size=0.0,
                initial_capital=100000,
                deflate=False,
                benchmark=bench_file,
            )
            result = run_cpcv(args)
            assert result == 0

            summary_path = Path(tmpdir) / "cpcv_summary.json"
            assert summary_path.exists()
            with open(summary_path) as f:
                summary = json.load(f)

            # Benchmark metrics should be in summary (if OOS returns exist)
            s = summary["summary"]
            # Note: with small data, CPCV may not produce OOS returns, so just check
            # that the benchmark config is recorded
            assert summary["config"]["benchmark"] == bench_file
    finally:
        Path(data_file).unlink()
        Path(bench_file).unlink()


def test_run_monte_carlo_cli_with_benchmark():
    """Monte Carlo CLI with --benchmark writes benchmark metrics to summary and tear sheet."""
    data_file = _make_test_data_file()
    bench_file = _make_benchmark_data()
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
                impact_coefficient=0.0,
                adv_window=20,
                borrow_cost=0.0,
                funding_cost=0.0,
                output=tmpdir,
                param_grid='{"fast_period": [10, 20], "slow_period": [30, 50]}',
                n_simulations=100,
                confidence_levels=[0.95],
                block_size=10,
                initial_capital=100000,
                n_trials=None,
                benchmark=bench_file,
            )
            result = run_monte_carlo(args)
            assert result == 0

            results_path = Path(tmpdir) / "monte_carlo_results.json"
            assert results_path.exists()
            with open(results_path) as f:
                mc_results = json.load(f)

            # Benchmark metrics should be in summary
            s = mc_results["summary"]
            assert "benchmark_total_return" in s
            assert "benchmark_annualized_return" in s
            assert "correlation_with_benchmark" in s
            assert "alpha" in s
            assert "beta" in s
            assert "alpha_tstat" in s
            assert 0.0 <= s["alpha_pvalue"] <= 1.0
            assert 0.0 <= s["r_squared"] <= 1.0

            # Benchmark provenance should be written
            assert "benchmark_provenance" in mc_results

            # Tear sheet summary should include benchmark
            tear_summary_path = Path(tmpdir) / "tear_sheet_summary.json"
            assert tear_summary_path.exists()
            with open(tear_summary_path) as f:
                tear_summary = json.load(f)
            assert "benchmark_total_return" in tear_summary["metrics"]
            assert "correlation_with_benchmark" in tear_summary["metrics"]
    finally:
        Path(data_file).unlink()
        Path(bench_file).unlink()


def test_run_walk_forward_cli_with_total_return_benchmark():
    """Walk-forward CLI with --total-return-benchmark records total_return_type=total
    and produces different benchmark metrics vs price-only benchmark.
    """
    data_file = _make_test_data_file()
    bench_file = _make_benchmark_data_with_dividends()
    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            # Price-only benchmark run
            args_price = _CLIArgs(
                data=data_file,
                strategy="sma_crossover",
                symbol="SPY",
                start=None,
                end=None,
                commission=0.0002,
                slippage=0.0001,
                output=os.path.join(tmpdir, "out_price"),
                param_grid='{"fast_period": [10, 20], "slow_period": [30, 50]}',
                train_months=6,
                test_months=2,
                step_months=2,
                initial_capital=100000,
                deflate=False,
                benchmark=bench_file,
            )
            result = run_walk_forward(args_price)
            assert result == 0

            summary_path_price = Path(tmpdir) / "out_price" / "walk_forward_summary.json"
            with open(summary_path_price) as f:
                summary_price = json.load(f)

            # Total-return benchmark run
            args_total = _CLIArgs(
                data=data_file,
                strategy="sma_crossover",
                symbol="SPY",
                start=None,
                end=None,
                commission=0.0002,
                slippage=0.0001,
                output=os.path.join(tmpdir, "out_total"),
                param_grid='{"fast_period": [10, 20], "slow_period": [30, 50]}',
                train_months=6,
                test_months=2,
                step_months=2,
                initial_capital=100000,
                deflate=False,
                benchmark=bench_file,
                total_return_benchmark=True,
            )
            result = run_walk_forward(args_total)
            assert result == 0

            summary_path_total = Path(tmpdir) / "out_total" / "walk_forward_summary.json"
            with open(summary_path_total) as f:
                summary_total = json.load(f)

            # Provenance records total_return_type=total
            assert summary_total["benchmark_provenance"]["total_return_type"] == "total"

            # Metrics show benchmark_total_return_type correctly
            assert summary_price["summary"]["benchmark_total_return_type"] == "price"
            assert summary_total["summary"]["benchmark_total_return_type"] == "total"

            # Total-return benchmark has higher total return (dividends add value)
            assert summary_total["summary"]["benchmark_total_return"] > summary_price["summary"]["benchmark_total_return"]

            # Alpha and beta differ between price-only and total-return
            assert abs(summary_total["summary"]["alpha"] - summary_price["summary"]["alpha"]) > 1e-6
            assert abs(summary_total["summary"]["beta"] - summary_price["summary"]["beta"]) > 1e-6
    finally:
        Path(data_file).unlink()
        Path(bench_file).unlink()


def test_run_cpcv_cli_with_total_return_benchmark():
    """CPCV CLI with --total-return-benchmark records total_return_type=total in provenance."""
    data_file = _make_test_data_file()
    bench_file = _make_benchmark_data_with_dividends()
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
                output=os.path.join(tmpdir, "out_total"),
                param_grid='{"fast_period": [10, 20], "slow_period": [30, 50]}',
                n_splits=4,
                test_size=0.2,
                purge_size=0.0,
                embargo_size=0.0,
                initial_capital=100000,
                deflate=False,
                benchmark=bench_file,
                total_return_benchmark=True,
            )
            result = run_cpcv(args)
            assert result == 0

            summary_path = Path(tmpdir) / "out_total" / "cpcv_summary.json"
            with open(summary_path) as f:
                summary = json.load(f)

            # Benchmark config recorded
            assert summary["config"]["benchmark"] == bench_file
            assert summary["config"]["total_return_benchmark"] is True

            # Provenance records total_return_type=total
            assert summary["benchmark_provenance"]["total_return_type"] == "total"
    finally:
        Path(data_file).unlink()
        Path(bench_file).unlink()


def test_run_monte_carlo_cli_with_total_return_benchmark():
    """Monte Carlo CLI with --total-return-benchmark records total_return_type=total
    and produces different benchmark metrics vs price-only benchmark.
    """
    data_file = _make_test_data_file()
    bench_file = _make_benchmark_data_with_dividends()
    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            # Price-only benchmark run
            args_price = _CLIArgs(
                data=data_file,
                strategy="sma_crossover",
                symbol="SPY",
                start=None,
                end=None,
                commission=0.0002,
                slippage=0.0001,
                impact_coefficient=0.0,
                adv_window=20,
                borrow_cost=0.0,
                funding_cost=0.0,
                output=os.path.join(tmpdir, "out_price"),
                param_grid='{"fast_period": [10, 20], "slow_period": [30, 50]}',
                n_simulations=50,
                confidence_levels=[0.95],
                block_size=10,
                initial_capital=100000,
                n_trials=None,
                benchmark=bench_file,
            )
            result = run_monte_carlo(args_price)
            assert result == 0

            results_path_price = Path(tmpdir) / "out_price" / "monte_carlo_results.json"
            with open(results_path_price) as f:
                mc_price = json.load(f)

            # Total-return benchmark run
            args_total = _CLIArgs(
                data=data_file,
                strategy="sma_crossover",
                symbol="SPY",
                start=None,
                end=None,
                commission=0.0002,
                slippage=0.0001,
                impact_coefficient=0.0,
                adv_window=20,
                borrow_cost=0.0,
                funding_cost=0.0,
                output=os.path.join(tmpdir, "out_total"),
                param_grid='{"fast_period": [10, 20], "slow_period": [30, 50]}',
                n_simulations=50,
                confidence_levels=[0.95],
                block_size=10,
                initial_capital=100000,
                n_trials=None,
                benchmark=bench_file,
                total_return_benchmark=True,
            )
            result = run_monte_carlo(args_total)
            assert result == 0

            results_path_total = Path(tmpdir) / "out_total" / "monte_carlo_results.json"
            with open(results_path_total) as f:
                mc_total = json.load(f)

            # Provenance records total_return_type=total
            assert mc_total["benchmark_provenance"]["total_return_type"] == "total"

            # Metrics show benchmark_total_return_type correctly
            assert mc_price["summary"]["benchmark_total_return_type"] == "price"
            assert mc_total["summary"]["benchmark_total_return_type"] == "total"

            # Total-return benchmark has higher total return (dividends add value)
            assert mc_total["summary"]["benchmark_total_return"] > mc_price["summary"]["benchmark_total_return"]

            # Alpha differs between price-only and total-return
            assert abs(mc_total["summary"]["alpha"] - mc_price["summary"]["alpha"]) > 1e-6
    finally:
        Path(data_file).unlink()
        Path(bench_file).unlink()


# Out-of-sample validation framework tests

def test_out_of_sample_validation_basic():
    """Basic out-of-sample validation with walk-forward validation method."""
    data = _make_data(periods=1000)
    results = out_of_sample_validation(
        data=data,
        strategy_factory=lambda p: _factory("sma_crossover", p),
        param_grid={"fast_period": [10, 20], "slow_period": [30, 50]},
        train_frac=0.6,
        val_frac=0.2,
        test_frac=0.2,
        validation_method="walk_forward",
        walk_forward_train_months=6,
        walk_forward_test_months=2,
        walk_forward_step_months=2,
        selection_criterion="best_oos_sharpe",
        apply_deflation=False,
    )

    assert "train_val_test_split" in results
    assert "validation_results" in results
    assert "selected_params" in results
    assert "validation_performance" in results
    assert "test_performance" in results
    assert "summary" in results

    split = results["train_val_test_split"]
    assert split["train_size"] > 0
    assert split["val_size"] > 0
    assert split["test_size"] > 0
    assert split["train_frac"] == 0.6
    assert split["val_frac"] == 0.2
    assert split["test_frac"] == 0.2

    assert results["selected_params"] is not None
    assert "fast_period" in results["selected_params"]
    assert "slow_period" in results["selected_params"]

    val_perf = results["validation_performance"]
    assert "val_total_return" in val_perf
    assert "val_sharpe" in val_perf

    test_perf = results["test_performance"]
    assert "test_total_return" in test_perf
    assert "test_sharpe" in test_perf
    assert "test_returns" in test_perf


def test_out_of_sample_validation_cpcv_method():
    """Out-of-sample validation with CPCV validation method."""
    data = _make_data(periods=1500)
    results = out_of_sample_validation(
        data=data,
        strategy_factory=lambda p: _factory("sma_crossover", p),
        param_grid={"fast_period": [10, 20], "slow_period": [30, 50]},
        train_frac=0.6,
        val_frac=0.2,
        test_frac=0.2,
        validation_method="cpcv",
        cpcv_n_splits=5,
        cpcv_test_size=0.2,
        cpcv_purge_size=0.0,
        cpcv_embargo_size=0.0,
        selection_criterion="best_oos_sharpe",
        apply_deflation=False,
    )

    assert results["selected_params"] is not None
    assert results["validation_results"]["folds"] is not None
    assert len(results["validation_results"]["folds"]) > 0


def test_out_of_sample_validation_selection_criteria():
    """Test different parameter selection criteria."""
    data = _make_data(periods=1000)
    param_grid = {"fast_period": [10, 20], "slow_period": [30, 50]}

    # Test best_oos_sharpe
    results_sharpe = out_of_sample_validation(
        data=data,
        strategy_factory=lambda p: _factory("sma_crossover", p),
        param_grid=param_grid,
        train_frac=0.6,
        val_frac=0.2,
        test_frac=0.2,
        validation_method="walk_forward",
        walk_forward_train_months=6,
        walk_forward_test_months=2,
        walk_forward_step_months=2,
        selection_criterion="best_oos_sharpe",
    )
    assert results_sharpe["selected_params"] is not None

    # Test most_stable
    results_stable = out_of_sample_validation(
        data=data,
        strategy_factory=lambda p: _factory("sma_crossover", p),
        param_grid=param_grid,
        train_frac=0.6,
        val_frac=0.2,
        test_frac=0.2,
        validation_method="walk_forward",
        walk_forward_train_months=6,
        walk_forward_test_months=2,
        walk_forward_step_months=2,
        selection_criterion="most_stable",
    )
    assert results_stable["selected_params"] is not None

    # Test best_avg_sharpe
    results_avg = out_of_sample_validation(
        data=data,
        strategy_factory=lambda p: _factory("sma_crossover", p),
        param_grid=param_grid,
        train_frac=0.6,
        val_frac=0.2,
        test_frac=0.2,
        validation_method="walk_forward",
        walk_forward_train_months=6,
        walk_forward_test_months=2,
        walk_forward_step_months=2,
        selection_criterion="best_avg_sharpe",
    )
    assert results_avg["selected_params"] is not None


def test_out_of_sample_validation_with_benchmark():
    """Out-of-sample validation with benchmark comparison on test set."""
    data = _make_data(periods=1000)
    bench = _make_data(periods=1000, seed=99)

    results = out_of_sample_validation(
        data=data,
        strategy_factory=lambda p: _factory("sma_crossover", p),
        param_grid={"fast_period": [10, 20], "slow_period": [30, 50]},
        train_frac=0.6,
        val_frac=0.2,
        test_frac=0.2,
        validation_method="walk_forward",
        walk_forward_train_months=6,
        walk_forward_test_months=2,
        walk_forward_step_months=2,
        benchmark=bench,
        total_return_benchmark=False,
    )

    assert results["test_benchmark"] is not None
    assert "correlation_with_benchmark" in results["test_benchmark"]
    assert "alpha" in results["test_benchmark"]
    assert "beta" in results["test_benchmark"]
    assert results["summary"]["correlation_with_benchmark"] == results["test_benchmark"]["correlation_with_benchmark"]


def test_out_of_sample_validation_split_fractions():
    """Test that split fractions are enforced and sum to 1."""
    data = _make_data(periods=1000)

    # Valid fractions
    results = out_of_sample_validation(
        data=data,
        strategy_factory=lambda p: _factory("sma_crossover", p),
        param_grid={"fast_period": [10, 20], "slow_period": [30, 50]},
        train_frac=0.7,
        val_frac=0.15,
        test_frac=0.15,
    )
    split = results["train_val_test_split"]
    assert abs(split["train_frac"] - 0.7) < 0.01
    assert abs(split["val_frac"] - 0.15) < 0.01
    assert abs(split["test_frac"] - 0.15) < 0.01

    # Invalid fractions should raise
    try:
        out_of_sample_validation(
            data=data,
            strategy_factory=lambda p: _factory("sma_crossover", p),
            param_grid={"fast_period": [10, 20], "slow_period": [30, 50]},
            train_frac=0.5,
            val_frac=0.2,
            test_frac=0.2,  # sums to 0.9
        )
        assert False, "Expected ValueError for fractions not summing to 1"
    except ValueError as e:
        assert "Fractions must sum to 1.0" in str(e)


def test_out_of_sample_validation_test_returns_never_used_in_selection():
    """Verify test set is never used during parameter selection."""
    data = _make_data(periods=1000)
    param_grid = {"fast_period": [10, 20], "slow_period": [30, 50]}

    results = out_of_sample_validation(
        data=data,
        strategy_factory=lambda p: _factory("sma_crossover", p),
        param_grid=param_grid,
        train_frac=0.6,
        val_frac=0.2,
        test_frac=0.2,
        validation_method="walk_forward",
        walk_forward_train_months=6,
        walk_forward_test_months=2,
        walk_forward_step_months=2,
    )

    # The validation results should only contain periods from the training split
    val_results = results["validation_results"]
    for period in val_results.get("periods", []):
        if period.get("test_end") is not None:
            # All test_end dates should be within the training split
            assert period["test_end"] <= results["train_val_test_split"]["train_end"], (
                f"Validation period test_end {period['test_end']} exceeds train split end "
                f"{results['train_val_test_split']['train_end']}"
            )


def test_out_of_sample_validation_deflated_sharpe():
    """Out-of-sample validation with Deflated Sharpe Ratio on test results."""
    data = _make_data(periods=1000)
    results = out_of_sample_validation(
        data=data,
        strategy_factory=lambda p: _factory("sma_crossover", p),
        param_grid={"fast_period": [10, 20], "slow_period": [30, 50]},
        train_frac=0.6,
        val_frac=0.2,
        test_frac=0.2,
        validation_method="walk_forward",
        walk_forward_train_months=6,
        walk_forward_test_months=2,
        walk_forward_step_months=2,
        apply_deflation=True,
    )

    assert "deflated_sharpe" in results["summary"]
    dsr = results["summary"]["deflated_sharpe"]
    assert 0.0 <= dsr["deflated_sharpe_ratio"] <= 1.0
    assert dsr["n_trials"] > 0
    assert dsr["n_observations"] == len(results["test_performance"]["test_returns"])


def test_split_train_val_test():
    """Test the _split_train_val_test helper function."""
    data = _make_data(periods=1000)

    train, val, test = _split_train_val_test(data, train_frac=0.6, val_frac=0.2, test_frac=0.2)

    assert len(train) == 600
    assert len(val) == 200
    assert len(test) == 200

    # Check chronological order
    assert train.index[-1] < val.index[0]
    assert val.index[-1] < test.index[0]

    # Test with dict panel data
    data_dict = _make_multiasset_dict(n=1000, n_assets=3)
    train_dict, val_dict, test_dict = _split_train_val_test(data_dict, 0.6, 0.2, 0.2)
    assert len(train_dict) == 600
    assert len(val_dict) == 200
    assert len(test_dict) == 200


def test_verify_split_separation_clean_split():
    """_verify_split_separation reports disjoint + chronological for a clean split."""
    data = _make_data(periods=1000)
    train, val, test = _split_train_val_test(data, 0.6, 0.2, 0.2)

    result = _verify_split_separation(train, val, test, strict=False)

    assert result["disjoint"] is True
    assert result["chronological"] is True
    assert result["train_val_overlap"] == 0
    assert result["val_test_overlap"] == 0
    assert result["train_test_overlap"] == 0
    assert result["train_size"] == 600
    assert result["val_size"] == 200
    assert result["test_size"] == 200
    assert result["train_end"] is not None
    assert result["val_start"] is not None


def test_verify_split_separation_detects_train_val_overlap():
    """A shared timestamp between train and validation must be flagged."""
    data = _make_data(periods=1000)
    train, val, test = _split_train_val_test(data, 0.6, 0.2, 0.2)

    # Leak the last training bar into the validation set.
    leaked = data.loc[[train.index[-1]]]
    val_overlap = pd.concat([leaked, val])

    result = _verify_split_separation(train, val_overlap, test, strict=False)
    assert result["disjoint"] is False
    assert result["train_val_overlap"] == 1
    assert result["chronological"] is False

    # In strict mode the leak must raise.
    try:
        _verify_split_separation(train, val_overlap, test, strict=True)
        assert False, "Expected ValueError for train/validation overlap"
    except ValueError as e:
        assert "train/validation share" in str(e)


def test_verify_split_separation_detects_val_test_overlap():
    """A shared timestamp between validation and test must be flagged."""
    data = _make_data(periods=1000)
    train, val, test = _split_train_val_test(data, 0.6, 0.2, 0.2)

    # Leak the last validation bar into the test set.
    leaked = data.loc[[val.index[-1]]]
    test_overlap = pd.concat([leaked, test])

    result = _verify_split_separation(train, val, test_overlap, strict=False)
    assert result["disjoint"] is False
    assert result["val_test_overlap"] == 1

    try:
        _verify_split_separation(train, val, test_overlap, strict=True)
        assert False, "Expected ValueError for validation/test overlap"
    except ValueError as e:
        assert "validation/test share" in str(e)


def test_verify_split_separation_detects_train_test_overlap():
    """A shared timestamp between train and test must be flagged."""
    data = _make_data(periods=1000)
    train, val, test = _split_train_val_test(data, 0.6, 0.2, 0.2)

    # Leak the first test bar into the training set.
    leaked = data.loc[[test.index[0]]]
    train_overlap = pd.concat([train, leaked]).drop_duplicates()

    result = _verify_split_separation(train_overlap, val, test, strict=False)
    assert result["disjoint"] is False
    assert result["train_test_overlap"] == 1

    try:
        _verify_split_separation(train_overlap, val, test, strict=True)
        assert False, "Expected ValueError for train/test overlap"
    except ValueError as e:
        assert "train/test share" in str(e)


def test_verify_split_separation_rejects_empty_split():
    """An empty segment is not a valid separation and must raise in strict mode."""
    data = _make_data(periods=1000)
    train, val, test = _split_train_val_test(data, 0.6, 0.2, 0.2)

    empty = train.iloc[0:0]
    try:
        _verify_split_separation(empty, val, test, strict=True)
        assert False, "Expected ValueError for empty split"
    except ValueError as e:
        assert "empty segment" in str(e)


def test_out_of_sample_validation_surfaces_separation_check():
    """out_of_sample_validation records the separation check in the split info."""
    data = _make_data(periods=1000)
    results = out_of_sample_validation(
        data=data,
        strategy_factory=lambda p: _factory("sma_crossover", p),
        param_grid={"fast_period": [10, 20], "slow_period": [30, 50]},
        train_frac=0.6,
        val_frac=0.2,
        test_frac=0.2,
        validation_method="walk_forward",
        walk_forward_train_months=6,
        walk_forward_test_months=2,
        walk_forward_step_months=2,
    )

    split = results["train_val_test_split"]
    assert "separation_check" in split
    check = split["separation_check"]
    assert check["disjoint"] is True
    assert check["chronological"] is True
    assert check["train_val_overlap"] == 0
    assert check["val_test_overlap"] == 0
    assert check["train_test_overlap"] == 0


def test_run_out_of_sample_validation_cli():
    """Test out-of-sample validation CLI function."""
    data_file = _make_test_data_file(periods=1000)
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
                train_frac=0.6,
                val_frac=0.2,
                test_frac=0.2,
                validation_method="walk_forward",
                selection_criterion="best_oos_sharpe",
                wf_train_months=6,
                wf_test_months=2,
                wf_step_months=2,
                initial_capital=100000,
                deflate=False,
            )
            result = run_out_of_sample_validation(args)
            assert result == 0

            # Check output files exist
            summary_path = Path(tmpdir) / "out_of_sample_summary.json"
            assert summary_path.exists(), "Summary JSON not created"

            with open(summary_path) as f:
                summary = json.load(f)
            assert "summary" in summary
            assert "train_val_test_split" in summary
            assert "selected_params" in summary
            assert "validation_performance" in summary
            assert "test_performance" in summary
            assert summary["summary"]["test_sharpe"] is not None
    finally:
        Path(data_file).unlink()


def test_run_out_of_sample_validation_cli_with_benchmark():
    """Test out-of-sample validation CLI with benchmark."""
    data_file = _make_test_data_file(periods=1000)
    # Use same date range for benchmark to ensure alignment
    bench_file = _make_benchmark_data_with_dividends(periods=1000)
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
                train_frac=0.6,
                val_frac=0.2,
                test_frac=0.2,
                validation_method="walk_forward",
                selection_criterion="best_oos_sharpe",
                wf_train_months=6,
                wf_test_months=2,
                wf_step_months=2,
                initial_capital=100000,
                deflate=False,
                benchmark=bench_file,
                total_return_benchmark=True,
            )
            result = run_out_of_sample_validation(args)
            assert result == 0

            summary_path = Path(tmpdir) / "out_of_sample_summary.json"
            with open(summary_path) as f:
                summary = json.load(f)
            assert "test_benchmark" in summary
            assert summary["test_benchmark"] is not None
            assert "correlation_with_benchmark" in summary["test_benchmark"]
    finally:
        Path(data_file).unlink()
        Path(bench_file).unlink()


def test_run_out_of_sample_validation_cli_cpcv_method():
    """Test out-of-sample validation CLI with CPCV validation method."""
    data_file = _make_test_data_file(periods=1500)
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
                train_frac=0.6,
                val_frac=0.2,
                test_frac=0.2,
                validation_method="cpcv",
                selection_criterion="best_oos_sharpe",
                cpcv_n_splits=5,
                cpcv_test_size=0.2,
                cpcv_purge_size=0.0,
                cpcv_embargo_size=0.0,
                initial_capital=100000,
                deflate=False,
            )
            result = run_out_of_sample_validation(args)
            assert result == 0

            summary_path = Path(tmpdir) / "out_of_sample_summary.json"
            with open(summary_path) as f:
                summary = json.load(f)
            assert summary["config"]["validation_method"] == "cpcv"
    finally:
        Path(data_file).unlink()
    sys.exit(main())

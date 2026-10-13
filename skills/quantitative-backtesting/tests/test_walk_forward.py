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
    deflated_sharpe_ratio,
    run_walk_forward,
    run_parameter_optimization,
    run_monte_carlo,
    _make_strategy_factory,
    _parse_param_grid,
    _annualization_factor,
    _calculate_strategy_returns,
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
        ("walk_forward_deflation", test_walk_forward_deflation),
        ("walk_forward_deflation_overfitting_check", test_walk_forward_deflation_overfitting_check),
        ("run_walk_forward_cli_with_deflation", test_run_walk_forward_cli_with_deflation),
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

#!/usr/bin/env python3
"""
Unit tests for generate_adversarial_scenarios.py: adversarial scenario generation.

Run with: python3 skills/quantitative-backtesting/tests/test_generate_adversarial_scenarios.py
Uses only the standard library.
"""

import sys
import tempfile
import traceback
from pathlib import Path

import numpy as np
import pandas as pd

SKILLS_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SKILLS_DIR / "scripts"))

from generate_adversarial_scenarios import (
    ScenarioConfig,
    generate_regime_shift,
    generate_correlation_breakdown,
    generate_fat_tail_crash,
    generate_liquidity_crisis,
    generate_trend_persistence,
    generate_structural_break,
    generate_volatility_clustering,
    generate_multi_asset_volatility_clustering,
)


def _validate_ohlcv(df: pd.DataFrame, expected_len: int):
    """Validate OHLCV DataFrame structure and relationships."""
    assert len(df) == expected_len, f"Expected {expected_len} rows, got {len(df)}"
    assert list(df.columns) == ["date", "open", "high", "low", "close", "volume"], \
        f"Columns mismatch: {list(df.columns)}"
    assert (df["high"] >= df["low"]).all(), "High < Low violation"
    assert (df["high"] >= df["close"]).all(), "High < Close violation"
    assert (df["high"] >= df["open"]).all(), "High < Open violation"
    assert (df["low"] <= df["close"]).all(), "Low > Close violation"
    assert (df["low"] <= df["open"]).all(), "Low > Open violation"
    assert (df["close"] > 0).all(), "Non-positive close"
    assert (df["volume"] > 0).all(), "Non-positive volume"
    assert isinstance(df.index, pd.RangeIndex), "Index should be RangeIndex"


def _validate_multi_asset(data: Dict[str, pd.DataFrame], n_assets: int, expected_len: int):
    """Validate multi-asset dict of OHLCV DataFrames."""
    assert len(data) == n_assets, f"Expected {n_assets} assets, got {len(data)}"
    for symbol, df in data.items():
        _validate_ohlcv(df, expected_len)
        assert symbol.startswith("ASSET_"), f"Unexpected symbol format: {symbol}"
    # Check all have same dates
    dates = [df["date"].iloc[0] for df in data.values()]
    assert len(set(dates)) == 1, "Assets have different start dates"


def test_regime_shift_basic():
    """Regime shift generates valid OHLCV with correct length."""
    config = ScenarioConfig(periods=500, seed=42)
    df = generate_regime_shift(config, bull_months=12, bear_months=12)
    _validate_ohlcv(df, 500)


def test_regime_shift_deterministic():
    """Same seed produces identical output."""
    config = ScenarioConfig(periods=300, seed=123)
    df1 = generate_regime_shift(config)
    df2 = generate_regime_shift(config)
    pd.testing.assert_frame_equal(df1, df2)


def test_regime_shift_has_transition():
    """Transition period should have elevated volatility."""
    config = ScenarioConfig(periods=1000, seed=42)
    bull_months = 12
    bear_months = 12
    transition_months = 3
    bull_vol = 0.01
    bear_vol = 0.01
    transition_vol_multiplier = 3.0
    df = generate_regime_shift(config, bull_months=bull_months, bear_months=bear_months,
                               transition_months=transition_months,
                               transition_vol_multiplier=transition_vol_multiplier,
                               bull_vol=bull_vol, bear_vol=bear_vol)
    returns = df["close"].pct_change().dropna()
    # Use actual regime boundaries: bull=252, transition=63, bear=rest
    bull_days = bull_months * 21
    transition_days = transition_months * 21
    bull_vol_est = returns[:bull_days].std()
    trans_vol_est = returns[bull_days:bull_days+transition_days].std()
    bear_vol_est = returns[bull_days+transition_days:bull_days+transition_days+252].std()
    # Transition vol should be higher than both bull and bear
    assert trans_vol_est > bull_vol_est * 1.5, f"Transition vol {trans_vol_est:.4f} not elevated vs bull {bull_vol_est:.4f}"
    assert trans_vol_est > bear_vol_est * 1.5, f"Transition vol {trans_vol_est:.4f} not elevated vs bear {bear_vol_est:.4f}"


def test_correlation_breakdown_basic():
    """Generates valid multi-asset data with correct structure."""
    config = ScenarioConfig(periods=400, seed=42)
    data = generate_correlation_breakdown(config, n_assets=4, break_point=0.6)
    _validate_multi_asset(data, 4, 400)


def test_correlation_breakdown_deterministic():
    """Same seed produces identical output."""
    config = ScenarioConfig(periods=300, seed=123)
    data1 = generate_correlation_breakdown(config, n_assets=3)
    data2 = generate_correlation_breakdown(config, n_assets=3)
    for k in data1:
        pd.testing.assert_frame_equal(data1[k], data2[k])


def test_correlation_breakdown_correlation_changes():
    """Pre-break correlation should differ from post-break."""
    config = ScenarioConfig(periods=500, seed=42)
    data = generate_correlation_breakdown(config, n_assets=5, break_point=0.6,
                                          pre_break_corr=0.7, post_break_corr=0.0)
    # Compute correlation matrices for pre and post
    returns_dict = {}
    for symbol, df in data.items():
        returns_dict[symbol] = df["close"].pct_change().dropna()
    returns_df = pd.DataFrame(returns_dict)
    n = len(returns_df)
    break_idx = int(n * 0.6)
    pre_corr = returns_df.iloc[:break_idx].corr().values
    post_corr = returns_df.iloc[break_idx:].corr().values
    # Off-diagonal correlations should be higher pre-break
    pre_offdiag = pre_corr[np.triu_indices_from(pre_corr, k=1)]
    post_offdiag = post_corr[np.triu_indices_from(post_corr, k=1)]
    assert pre_offdiag.mean() > post_offdiag.mean() * 2, \
        f"Pre-break corr {pre_offdiag.mean():.3f} not higher than post {post_offdiag.mean():.3f}"


def test_fat_tail_crash_basic():
    """Generates valid OHLCV with correct length."""
    config = ScenarioConfig(periods=500, seed=42)
    df = generate_fat_tail_crash(config, crash_probability=0.01)
    _validate_ohlcv(df, 500)


def test_fat_tail_crash_deterministic():
    """Same seed produces identical output."""
    config = ScenarioConfig(periods=300, seed=123)
    df1 = generate_fat_tail_crash(config)
    df2 = generate_fat_tail_crash(config)
    pd.testing.assert_frame_equal(df1, df2)


def test_fat_tail_crash_has_extreme_returns():
    """Should produce returns with excess kurtosis (fat tails)."""
    config = ScenarioConfig(periods=2000, seed=42)
    df = generate_fat_tail_crash(config, crash_probability=0.005, crash_mean=-0.1, crash_vol=0.05)
    returns = df["close"].pct_change().dropna()
    kurtosis = returns.kurtosis()  # Excess kurtosis
    skew = returns.skew()
    # Should have positive excess kurtosis and negative skew
    assert kurtosis > 3.0, f"Expected excess kurtosis > 3, got {kurtosis:.2f}"
    assert skew < -0.5, f"Expected negative skew, got {skew:.2f}"


def test_fat_tail_crash_no_crashes_when_prob_zero():
    """Zero crash probability should produce normal-ish returns."""
    config = ScenarioConfig(periods=500, seed=42)
    df = generate_fat_tail_crash(config, crash_probability=0.0)
    returns = df["close"].pct_change().dropna()
    kurtosis = returns.kurtosis()
    # Without crashes, kurtosis should be near 0 (normal)
    assert abs(kurtosis) < 1.0, f"Expected near-normal kurtosis, got {kurtosis:.2f}"


def test_liquidity_crisis_basic():
    """Generates valid OHLCV with volume decay during crisis."""
    config = ScenarioConfig(periods=500, seed=42)
    df = generate_liquidity_crisis(config, crisis_start=0.5, crisis_duration_months=3)
    _validate_ohlcv(df, 500)


def test_liquidity_crisis_volume_decays():
    """Volume should decay exponentially during crisis."""
    config = ScenarioConfig(periods=500, seed=42)
    df = generate_liquidity_crisis(config, crisis_start=0.4, crisis_duration_months=6,
                                   volume_decay=0.95)
    crisis_start_idx = int(500 * 0.4)
    crisis_volumes = df["volume"].iloc[crisis_start_idx:crisis_start_idx+60]
    # Volume should generally decay (not strictly monotonic due to noise, but trend down)
    assert crisis_volumes.iloc[-1] < crisis_volumes.iloc[0] * 0.8, \
        f"Volume did not decay sufficiently: {crisis_volumes.iloc[0]} -> {crisis_volumes.iloc[-1]}"


def test_liquidity_crisis_elevated_vol():
    """Returns volatility should be elevated during crisis."""
    config = ScenarioConfig(periods=500, seed=42)
    df = generate_liquidity_crisis(config, crisis_start=0.4, crisis_duration_months=3,
                                   impact_vol_multiplier=3.0)
    returns = df["close"].pct_change().dropna()
    crisis_start_idx = int(500 * 0.4)
    crisis_end_idx = crisis_start_idx + 63
    normal_vol = returns[:crisis_start_idx].std()
    crisis_vol = returns[crisis_start_idx:crisis_end_idx].std()
    assert crisis_vol > normal_vol * 2.0, \
        f"Crisis vol {crisis_vol:.4f} not elevated vs normal {normal_vol:.4f}"


def test_trend_persistence_basic():
    """Generates valid OHLCV with correct length."""
    config = ScenarioConfig(periods=500, seed=42)
    df = generate_trend_persistence(config)
    _validate_ohlcv(df, 500)


def test_trend_persistence_deterministic():
    """Same seed produces identical output."""
    config = ScenarioConfig(periods=300, seed=123)
    df1 = generate_trend_persistence(config)
    df2 = generate_trend_persistence(config)
    pd.testing.assert_frame_equal(df1, df2)


def test_trend_persistence_has_low_vol_trend():
    """Trend region should have lower volatility than noise region."""
    config = ScenarioConfig(periods=1000, seed=42)
    df = generate_trend_persistence(config, trend_months=24, trend_fraction=0.5,
                                    trend_drift=0.001, trend_vol=0.005,
                                    noise_drift=0.0, noise_vol=0.02)
    returns = df["close"].pct_change().dropna()
    n = len(returns)
    # Find the trend region by looking for low-vol window
    window = 60
    min_vol = float('inf')
    min_idx = 0
    for i in range(n - window):
        vol = returns[i:i+window].std()
        if vol < min_vol:
            min_vol = vol
            min_idx = i
    trend_vol = returns[min_idx:min_idx+window].std()
    overall_vol = returns.std()
    assert trend_vol < overall_vol * 0.5, \
        f"Trend vol {trend_vol:.4f} not sufficiently lower than overall {overall_vol:.4f}"


def test_structural_break_basic():
    """Generates valid OHLCV with correct length."""
    config = ScenarioConfig(periods=500, seed=42)
    df = generate_structural_break(config, break_point=0.5)
    _validate_ohlcv(df, 500)


def test_structural_break_deterministic():
    """Same seed produces identical output."""
    config = ScenarioConfig(periods=300, seed=123)
    df1 = generate_structural_break(config)
    df2 = generate_structural_break(config)
    pd.testing.assert_frame_equal(df1, df2)


def test_structural_break_parameters_change():
    """Pre and post break should have different drift/vol."""
    config = ScenarioConfig(periods=10000, seed=42)
    df = generate_structural_break(config, break_point=0.5,
                                   pre_break_drift=0.001, pre_break_vol=0.01,
                                   post_break_drift=-0.001, post_break_vol=0.03)
    returns = df["close"].pct_change().dropna()
    n = len(returns)
    break_idx = n // 2
    pre_drift = returns[:break_idx].mean()
    post_drift = returns[break_idx:].mean()
    pre_vol = returns[:break_idx].std()
    post_vol = returns[break_idx:].std()
    assert abs(pre_drift - 0.001) < 0.0003, f"Pre-drift {pre_drift:.5f} not near 0.001"
    assert abs(post_drift - (-0.001)) < 0.0006, f"Post-drift {post_drift:.5f} not near -0.001"
    assert post_vol > pre_vol * 2.0, f"Post-vol {post_vol:.4f} not higher than pre {pre_vol:.4f}"


def test_volatility_clustering_basic():
    """Generates valid OHLCV with correct length."""
    config = ScenarioConfig(periods=500, seed=42)
    df = generate_volatility_clustering(config)
    _validate_ohlcv(df, 500)


def test_volatility_clustering_deterministic():
    """Same seed produces identical output."""
    config = ScenarioConfig(periods=300, seed=123)
    df1 = generate_volatility_clustering(config)
    df2 = generate_volatility_clustering(config)
    pd.testing.assert_frame_equal(df1, df2)


def test_volatility_clustering_has_regimes():
    """Should produce periods of high and low volatility."""
    config = ScenarioConfig(periods=2000, seed=42)
    df = generate_volatility_clustering(config, base_vol=0.005, cluster_vol=0.03,
                                        cluster_probability=0.01, cluster_persistence=0.97)
    returns = df["close"].pct_change().dropna()
    # Rolling vol should show clustering
    rolling_vol = returns.rolling(50).std()
    # Should have both low and high vol periods
    assert rolling_vol.min() < 0.01, f"Min rolling vol {rolling_vol.min():.4f} not low enough"
    assert rolling_vol.max() > 0.02, f"Max rolling vol {rolling_vol.max():.4f} not high enough"


def test_volatility_clustering_fat_tails():
    """Vol clustering should produce excess kurtosis in unconditional distribution."""
    config = ScenarioConfig(periods=5000, seed=42)
    df = generate_volatility_clustering(config, base_vol=0.005, cluster_vol=0.03,
                                        cluster_probability=0.02, cluster_persistence=0.95)
    returns = df["close"].pct_change().dropna()
    kurtosis = returns.kurtosis()
    assert kurtosis > 1.0, f"Expected excess kurtosis from vol clustering, got {kurtosis:.2f}"


def test_multi_asset_vol_clustering_basic():
    """Generates valid multi-asset data."""
    config = ScenarioConfig(periods=400, seed=42)
    data = generate_multi_asset_volatility_clustering(config, n_assets=4, sync_clusters=True)
    _validate_multi_asset(data, 4, 400)


def test_multi_asset_vol_clustering_sync():
    """Synced clusters: all assets should enter high-vol together."""
    config = ScenarioConfig(periods=2000, seed=42)
    data = generate_multi_asset_volatility_clustering(config, n_assets=3, sync_clusters=True,
                                                      base_vol=0.005, cluster_vol=0.04,
                                                      cluster_probability=0.03, cluster_persistence=0.97)
    returns_dict = {s: df["close"].pct_change().dropna() for s, df in data.items()}
    # Check rolling vol correlation across assets
    rolling_vols = {s: r.rolling(50).std() for s, r in returns_dict.items()}
    # Correlation of rolling vols should be high
    vol_df = pd.DataFrame(rolling_vols).dropna()
    corr_matrix = vol_df.corr()
    offdiag = corr_matrix.values[np.triu_indices_from(corr_matrix.values, k=1)]
    assert offdiag.mean() > 0.5, f"Synced cluster vol correlation {offdiag.mean():.3f} too low"


def test_multi_asset_vol_clustering_async():
    """Async clusters: assets should have independent vol regimes."""
    config = ScenarioConfig(periods=2000, seed=42)
    data = generate_multi_asset_volatility_clustering(config, n_assets=3, sync_clusters=False,
                                                      base_vol=0.005, cluster_vol=0.03,
                                                      cluster_probability=0.02, cluster_persistence=0.95)
    returns_dict = {s: df["close"].pct_change().dropna() for s, df in data.items()}
    rolling_vols = {s: r.rolling(50).std() for s, r in returns_dict.items()}
    vol_df = pd.DataFrame(rolling_vols).dropna()
    corr_matrix = vol_df.corr()
    offdiag = corr_matrix.values[np.triu_indices_from(corr_matrix.values, k=1)]
    assert offdiag.mean() < 0.5, f"Async cluster vol correlation {offdiag.mean():.3f} too high"


def test_main_registers_every_module_level_test():
    """main() must register every module-level ``test_*`` function."""
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
        f"{sorted(f.__name__ for f in missing)}"
    )
    phantom = registered - module_tests
    assert not phantom, (
        f"entries in TEST_REGISTRY that are not module-level test_* "
        f"functions: {sorted(f.__name__ for f in phantom)}"
    )
    labels = [name for name, _ in TEST_REGISTRY]
    assert len(labels) == len(set(labels)), (
        f"TEST_REGISTRY has duplicate labels: "
        f"{[l for l in labels if labels.count(l) > 1]}"
    )


TEST_REGISTRY = [
    ("regime_shift_basic", test_regime_shift_basic),
    ("regime_shift_deterministic", test_regime_shift_deterministic),
    ("regime_shift_has_transition", test_regime_shift_has_transition),
    ("correlation_breakdown_basic", test_correlation_breakdown_basic),
    ("correlation_breakdown_deterministic", test_correlation_breakdown_deterministic),
    ("correlation_breakdown_correlation_changes", test_correlation_breakdown_correlation_changes),
    ("fat_tail_crash_basic", test_fat_tail_crash_basic),
    ("fat_tail_crash_deterministic", test_fat_tail_crash_deterministic),
    ("fat_tail_crash_has_extreme_returns", test_fat_tail_crash_has_extreme_returns),
    ("fat_tail_crash_no_crashes_when_prob_zero", test_fat_tail_crash_no_crashes_when_prob_zero),
    ("liquidity_crisis_basic", test_liquidity_crisis_basic),
    ("liquidity_crisis_volume_decays", test_liquidity_crisis_volume_decays),
    ("liquidity_crisis_elevated_vol", test_liquidity_crisis_elevated_vol),
    ("trend_persistence_basic", test_trend_persistence_basic),
    ("trend_persistence_deterministic", test_trend_persistence_deterministic),
    ("trend_persistence_has_low_vol_trend", test_trend_persistence_has_low_vol_trend),
    ("structural_break_basic", test_structural_break_basic),
    ("structural_break_deterministic", test_structural_break_deterministic),
    ("structural_break_parameters_change", test_structural_break_parameters_change),
    ("volatility_clustering_basic", test_volatility_clustering_basic),
    ("volatility_clustering_deterministic", test_volatility_clustering_deterministic),
    ("volatility_clustering_has_regimes", test_volatility_clustering_has_regimes),
    ("volatility_clustering_fat_tails", test_volatility_clustering_fat_tails),
    ("multi_asset_vol_clustering_basic", test_multi_asset_vol_clustering_basic),
    ("multi_asset_vol_clustering_sync", test_multi_asset_vol_clustering_sync),
    ("multi_asset_vol_clustering_async", test_multi_asset_vol_clustering_async),
    ("test_main_registers_every_module_level_test", test_main_registers_every_module_level_test),
]


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


if __name__ == "__main__":
    sys.exit(main())
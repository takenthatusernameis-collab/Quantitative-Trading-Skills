#!/usr/bin/env python3
"""
Adversarial Regime Simulation Framework.

Generates synthetic market scenarios with known adverse properties for
stress-testing quantitative strategies. Each scenario is produced by a
documented, deterministic formula so the adverse property is guaranteed
by construction (not merely observed in historical data).

Scenarios:
1. regime_shift: Bull-to-bear transition with volatility spike
2. correlation_breakdown: Multi-asset correlation spike (diversification failure)
3. fat_tail_crash: Sudden large negative returns with excess kurtosis
6. liquidity_crisis: Volume dry-up with impact cost amplification
7. trend_persistence: Mean reversion breakdown (trends persist excessively)
8. structural_break: Fundamental parameter change mid-sample

All generators are seed-deterministic and return OHLCV DataFrames or
dicts of DataFrames suitable for the backtesting pipeline.
"""

import numpy as np
import pandas as pd
from pathlib import Path
from typing import Dict, List, Optional, Union, Literal
from dataclasses import dataclass, field


# Scenario parameter defaults (documented in one place for reproducibility)
DEFAULT_PERIODS = 1000
DEFAULT_START = "2015-01-01"
DEFAULT_INITIAL_PRICE = 100.0
DEFAULT_SEED = 42


@dataclass
class ScenarioConfig:
    """Configuration for adversarial scenario generation."""
    periods: int = DEFAULT_PERIODS
    start_date: str = DEFAULT_START
    initial_price: float = DEFAULT_INITIAL_PRICE
    seed: int = DEFAULT_SEED


def _ohlcv_from_close(
    close: np.ndarray,
    dates: pd.DatetimeIndex,
    volume_seed: int,
    initial_price: float,
    volume_range: tuple = (1_000_000, 10_000_000),
    ohlc_noise: float = 0.01,
) -> pd.DataFrame:
    """Build OHLCV DataFrame from close prices ensuring OHLC relationships."""
    open_ = np.concatenate([[float(initial_price)], close[:-1]])
    rng_micro = np.random.default_rng(volume_seed + 1)
    high = np.maximum(open_, close) * rng_micro.uniform(1.001, 1.001 + ohlc_noise, len(close))
    low = np.minimum(open_, close) * rng_micro.uniform(1.0 - ohlc_noise, 0.999, len(close))
    volume = rng_micro.integers(volume_range[0], volume_range[1], len(close))
    return pd.DataFrame({
        "date": dates,
        "open": open_,
        "high": high,
        "low": low,
        "close": close,
        "volume": volume,
    })


def generate_regime_shift(
    config: Optional[ScenarioConfig] = None,
    bull_months: int = 18,
    bear_months: int = 18,
    bull_drift: float = 0.0008,
    bear_drift: float = -0.0005,
    bull_vol: float = 0.01,
    bear_vol: float = 0.025,
    transition_months: int = 3,
    transition_vol_multiplier: float = 3.0,
) -> pd.DataFrame:
    """
    Generate a bull-to-bear regime shift with volatility spike at transition.

    The transition period has elevated volatility (transition_vol_multiplier x)
    simulating the uncertainty and violent moves during regime changes.

    Args:
        config: ScenarioConfig with periods, start_date, initial_price, seed
        bull_months: Duration of bull market in months (~21 trading days/month)
        bear_months: Duration of bear market in months
        bull_drift: Daily drift during bull (annualized ~20% at 0.0008)
        bear_drift: Daily drift during bear (annualized ~-12% at -0.0005)
        bull_vol: Daily volatility during bull
        bear_vol: Daily volatility during bear
        transition_months: Months of elevated volatility at transition
        transition_vol_multiplier: Volatility multiplier during transition

    Returns:
        DataFrame with OHLCV columns
    """
    if config is None:
        config = ScenarioConfig()

    rng = np.random.default_rng(config.seed)
    dates = pd.date_range(config.start_date, periods=config.periods, freq="B")

    # Convert months to trading days
    bull_days = bull_months * 21
    bear_days = bear_months * 21
    transition_days = transition_months * 21

    # Build piecewise drift and volatility
    n = config.periods
    drifts = np.zeros(n)
    vols = np.zeros(n)

    # Bull regime
    bull_end = min(bull_days, n)
    drifts[:bull_end] = bull_drift
    vols[:bull_end] = bull_vol

    # Transition regime (elevated vol)
    trans_start = bull_end
    trans_end = min(bull_end + transition_days, n)
    if trans_start < n:
        # Linear drift transition from bull to bear
        if trans_end > trans_start:
            alpha = np.linspace(0, 1, trans_end - trans_start)
            drifts[trans_start:trans_end] = bull_drift * (1 - alpha) + bear_drift * alpha
            vols[trans_start:trans_end] = bull_vol * transition_vol_multiplier

    # Bear regime
    if trans_end < n:
        drifts[trans_end:] = bear_drift
        vols[trans_end:] = bear_vol

    # Generate returns
    returns = np.zeros(n)
    for i in range(n):
        returns[i] = rng.normal(drifts[i], vols[i])

    prices = config.initial_price * np.exp(np.cumsum(returns))
    return _ohlcv_from_close(prices, dates, config.seed, config.initial_price)


def generate_correlation_breakdown(
    config: Optional[ScenarioConfig] = None,
    n_assets: int = 5,
    pre_break_corr: float = 0.7,
    post_break_corr: float = 0.0,
    break_point: float = 0.7,  # Fraction of sample
    pre_break_months: int = 12,
    post_break_months: int = 12,
    asset_vols: Optional[List[float]] = None,
    market_drift: float = 0.0003,
    market_vol: float = 0.012,
) -> Dict[str, pd.DataFrame]:
    """
    Generate multi-asset data with a correlation breakdown.

    Pre-break: Assets share a common market factor (correlated).
    Post-break: Common factor vanishes; assets become independent (diversification fails).

    This is the "correlation goes to 1 in a crisis" scenario but in reverse:
    assets that were diversifying suddenly move together, or conversely,
    a previously stable correlation structure breaks down.

    Args:
        config: ScenarioConfig
        n_assets: Number of assets
        pre_break_corr: Correlation level before break (via shared factor beta)
        post_break_corr: Correlation level after break (0 = independent)
        break_point: Fraction of sample at which break occurs
        pre_break_months: Months of pre-break data
        post_break_months: Months of post-break data
        asset_vols: List of idiosyncratic vols per asset (random if None)
        market_drift: Market factor daily drift
        market_vol: Market factor daily vol

    Returns:
        Dict mapping symbol -> OHLCV DataFrame
    """
    if config is None:
        config = ScenarioConfig()

    rng = np.random.default_rng(config.seed)
    dates = pd.date_range(config.start_date, periods=config.periods, freq="B")
    n = config.periods
    break_idx = int(n * break_point)

    if asset_vols is None:
        asset_vols = rng.uniform(0.008, 0.025, n_assets).tolist()
    betas_pre = rng.uniform(0.7, 1.3, n_assets)

    # Market factor (common to all assets pre-break)
    market_returns = rng.normal(market_drift, market_vol, n)

    data_dict = {}
    for i in range(n_assets):
        idio_rng = np.random.default_rng(config.seed + 1000 + i)
        idio_returns = idio_rng.normal(0.0, asset_vols[i], n)

        # Pre-break: beta * market + idio
        # Post-break: 0 * market + idio (market factor vanishes)
        asset_returns = np.zeros(n)
        asset_returns[:break_idx] = betas_pre[i] * market_returns[:break_idx] + idio_returns[:break_idx]
        asset_returns[break_idx:] = post_break_corr * market_returns[break_idx:] + idio_returns[break_idx:]

        # Add small positive drift
        asset_returns += 0.0002

        prices = config.initial_price * np.exp(np.cumsum(asset_returns))
        data_dict[f"ASSET_{i}"] = _ohlcv_from_close(
            prices, dates, config.seed + i, config.initial_price
        )

    return data_dict


def generate_fat_tail_crash(
    config: Optional[ScenarioConfig] = None,
    normal_drift: float = 0.0005,
    normal_vol: float = 0.015,
    crash_probability: float = 0.002,  # ~1 crash per 500 days
    crash_mean: float = -0.15,  # -15% mean crash return
    crash_vol: float = 0.05,    # High uncertainty during crash
    recovery_days: int = 20,    # Days of elevated vol after crash
    recovery_vol_multiplier: float = 2.0,
) -> pd.DataFrame:
    """
    Generate returns with fat-tailed crash events (jump-diffusion).

    Normal periods follow Gaussian diffusion. With crash_probability per day,
    a crash event occurs: a large negative jump drawn from a separate
    distribution, followed by recovery_days of elevated volatility.

    This produces excess kurtosis and negative skew characteristic of
    equity market crashes, which standard Gaussian models underestimate.

    Args:
        config: ScenarioConfig
        normal_drift: Daily drift in normal regime
        normal_vol: Daily vol in normal regime
        crash_probability: Per-day probability of crash event
        crash_mean: Mean crash return (negative)
        crash_vol: Volatility of crash return
        recovery_days: Days of elevated vol after crash
        recovery_vol_multiplier: Vol multiplier during recovery

    Returns:
        DataFrame with OHLCV columns
    """
    if config is None:
        config = ScenarioConfig()

    rng = np.random.default_rng(config.seed)
    dates = pd.date_range(config.start_date, periods=config.periods, freq="B")
    n = config.periods

    returns = np.zeros(n)
    in_recovery = 0

    for i in range(n):
        if in_recovery > 0:
            # Recovery period: elevated vol, zero drift
            returns[i] = rng.normal(0.0, normal_vol * recovery_vol_multiplier)
            in_recovery -= 1
        elif rng.random() < crash_probability:
            # Crash event
            returns[i] = rng.normal(crash_mean, crash_vol)
            in_recovery = recovery_days
        else:
            # Normal diffusion
            returns[i] = rng.normal(normal_drift, normal_vol)

    prices = config.initial_price * np.exp(np.cumsum(returns))
    return _ohlcv_from_close(prices, dates, config.seed, config.initial_price)


def generate_liquidity_crisis(
    config: Optional[ScenarioConfig] = None,
    normal_vol: float = 0.015,
    normal_volume: int = 5_000_000,
    crisis_start: float = 0.6,  # Fraction of sample
    crisis_duration_months: int = 6,
    volume_decay: float = 0.95,  # Daily volume multiplier during crisis
    impact_vol_multiplier: float = 5.0,  # Vol amplification from impact
) -> pd.DataFrame:
    """
    Generate a liquidity crisis: volume dries up, effective volatility spikes.

    Models the feedback loop where falling volume -> higher impact costs ->
    forced liquidation -> more volume pressure -> higher vol.

    The output DataFrame has a 'volume' column that decays exponentially
    during the crisis, and returns whose volatility is amplified to
    simulate the impact cost feedback (the backtester can use the volume
    column for ADV-based impact modeling).

    Args:
        config: ScenarioConfig
        normal_vol: Base daily volatility
        normal_volume: Average daily volume pre-crisis
        crisis_start: Fraction of sample where crisis begins
        crisis_duration_months: Crisis duration in months
        volume_decay: Daily volume decay factor (0.95 = 5% daily decline)
        impact_vol_multiplier: Return vol multiplier during crisis

    Returns:
        DataFrame with OHLCV columns (volume reflects crisis)
    """
    if config is None:
        config = ScenarioConfig()

    rng = np.random.default_rng(config.seed)
    dates = pd.date_range(config.start_date, periods=config.periods, freq="B")
    n = config.periods
    crisis_start_idx = int(n * crisis_start)
    crisis_days = crisis_duration_months * 21
    crisis_end_idx = min(crisis_start_idx + crisis_days, n)

    returns = np.zeros(n)
    volumes = np.full(n, normal_volume, dtype=float)

    for i in range(n):
        if crisis_start_idx <= i < crisis_end_idx:
            # Crisis period: decaying volume, amplified vol
            days_into_crisis = i - crisis_start_idx
            volumes[i] = normal_volume * (volume_decay ** days_into_crisis)
            returns[i] = rng.normal(0.0, normal_vol * impact_vol_multiplier)
        else:
            volumes[i] = normal_volume * rng.uniform(0.8, 1.2)
            returns[i] = rng.normal(0.0003, normal_vol)

    prices = config.initial_price * np.exp(np.cumsum(returns))

    # Build OHLCV with the pre-computed volumes
    open_ = np.concatenate([[float(config.initial_price)], prices[:-1]])
    rng_micro = np.random.default_rng(config.seed + 1)
    high = np.maximum(open_, prices) * rng_micro.uniform(1.001, 1.01, n)
    low = np.minimum(open_, prices) * rng_micro.uniform(0.99, 0.999, n)

    return pd.DataFrame({
        "date": dates,
        "open": open_,
        "high": high,
        "low": low,
        "close": prices,
        "volume": volumes.astype(int),
    })


def generate_trend_persistence(
    config: Optional[ScenarioConfig] = None,
    trend_months: int = 24,
    trend_drift: float = 0.001,   # Strong persistent trend
    trend_vol: float = 0.008,     # Low vol (smooth trend)
    noise_drift: float = 0.0001,
    noise_vol: float = 0.015,
    trend_fraction: float = 0.7,  # Fraction of sample in trend
) -> pd.DataFrame:
    """
    Generate a market where trends persist far longer than mean-reversion
    strategies expect (breakdown of mean reversion).

    A prolonged smooth trend with low volatility will cause mean-reversion
    strategies (Bollinger Bands, RSI, Z-Score) to repeatedly enter counter-trend
    positions and get stopped out, while trend-following strategies profit.

    Args:
        config: ScenarioConfig
        trend_months: Duration of persistent trend in months
        trend_drift: Daily drift during trend
        trend_vol: Daily vol during trend (low = smooth trend)
        noise_drift: Drift outside trend
        noise_vol: Vol outside trend
        trend_fraction: Fraction of sample occupied by trend

    Returns:
        DataFrame with OHLCV columns
    """
    if config is None:
        config = ScenarioConfig()

    rng = np.random.default_rng(config.seed)
    dates = pd.date_range(config.start_date, periods=config.periods, freq="B")
    n = config.periods
    trend_days = int(n * trend_fraction)
    trend_start = rng.integers(0, max(1, n - trend_days))

    returns = np.zeros(n)
    for i in range(n):
        if trend_start <= i < trend_start + trend_days:
            returns[i] = rng.normal(trend_drift, trend_vol)
        else:
            returns[i] = rng.normal(noise_drift, noise_vol)

    prices = config.initial_price * np.exp(np.cumsum(returns))
    return _ohlcv_from_close(prices, dates, config.seed, config.initial_price)


def generate_structural_break(
    config: Optional[ScenarioConfig] = None,
    pre_break_drift: float = 0.0005,
    pre_break_vol: float = 0.015,
    post_break_drift: float = -0.0003,
    post_break_vol: float = 0.025,
    break_point: float = 0.5,
) -> pd.DataFrame:
    """
    Generate a structural break: fundamental change in return distribution.

    The drift and volatility parameters change abruptly at break_point.
    This tests whether validation methods (walk-forward, CPCV) can detect
    and adapt to regime changes, or whether they overfit to the pre-break
    regime and fail post-break.

    Args:
        config: ScenarioConfig
        pre_break_drift: Daily drift before break
        pre_break_vol: Daily vol before break
        post_break_drift: Daily drift after break
        post_break_vol: Daily vol after break
        break_point: Fraction of sample at which break occurs

    Returns:
        DataFrame with OHLCV columns
    """
    if config is None:
        config = ScenarioConfig()

    rng = np.random.default_rng(config.seed)
    dates = pd.date_range(config.start_date, periods=config.periods, freq="B")
    n = config.periods
    break_idx = int(n * break_point)

    returns = np.zeros(n)
    returns[:break_idx] = rng.normal(pre_break_drift, pre_break_vol, break_idx)
    returns[break_idx:] = rng.normal(post_break_drift, post_break_vol, n - break_idx)

    prices = config.initial_price * np.exp(np.cumsum(returns))
    return _ohlcv_from_close(prices, dates, config.seed, config.initial_price)


def generate_volatility_clustering(
    config: Optional[ScenarioConfig] = None,
    base_vol: float = 0.01,
    cluster_vol: float = 0.03,
    cluster_probability: float = 0.02,  # Per-day prob of entering cluster
    cluster_persistence: float = 0.95,  # Prob of staying in cluster
    drift: float = 0.0003,
) -> pd.DataFrame:
    """
    Generate volatility clustering (GARCH-like behavior without GARCH).

    Volatility switches between a low regime and a high regime with
    persistence. This creates volatility clustering and fat tails in
    the unconditional distribution, testing whether strategies properly
    size positions for changing volatility.

    Args:
        config: ScenarioConfig
        base_vol: Low volatility regime
        cluster_vol: High volatility regime
        cluster_probability: Prob of entering high-vol regime per day
        cluster_persistence: Prob of staying in high-vol regime
        drift: Daily drift (constant)

    Returns:
        DataFrame with OHLCV columns
    """
    if config is None:
        config = ScenarioConfig()

    rng = np.random.default_rng(config.seed)
    dates = pd.date_range(config.start_date, periods=config.periods, freq="B")
    n = config.periods

    returns = np.zeros(n)
    in_cluster = False

    for i in range(n):
        if in_cluster:
            vol = cluster_vol
            if rng.random() > cluster_persistence:
                in_cluster = False
        else:
            vol = base_vol
            if rng.random() < cluster_probability:
                in_cluster = True
        returns[i] = rng.normal(drift, vol)

    prices = config.initial_price * np.exp(np.cumsum(returns))
    return _ohlcv_from_close(prices, dates, config.seed, config.initial_price)


def generate_multi_asset_volatility_clustering(
    config: Optional[ScenarioConfig] = None,
    n_assets: int = 5,
    base_vol: float = 0.01,
    cluster_vol: float = 0.03,
    cluster_probability: float = 0.02,
    cluster_persistence: float = 0.95,
    market_drift: float = 0.0003,
    market_vol: float = 0.012,
    sync_clusters: bool = True,  # Whether all assets enter cluster together
) -> Dict[str, pd.DataFrame]:
    """
    Multi-asset version of volatility clustering.

    If sync_clusters=True, all assets share the same volatility regime
    (systematic vol clustering). If False, each asset has independent
    clustering (idiosyncratic vol events).

    Args:
        config: ScenarioConfig
        n_assets: Number of assets
        base_vol: Low vol regime
        cluster_vol: High vol regime
        cluster_probability: Prob of entering cluster
        cluster_persistence: Prob of staying in cluster
        market_drift: Market factor drift
        market_vol: Market factor vol
        sync_clusters: Whether clusters are synchronized across assets

    Returns:
        Dict mapping symbol -> OHLCV DataFrame
    """
    if config is None:
        config = ScenarioConfig()

    rng = np.random.default_rng(config.seed)
    dates = pd.date_range(config.start_date, periods=config.periods, freq="B")
    n = config.periods

    # Market factor
    market_returns = rng.normal(market_drift, market_vol, n)

    # Vol regime (shared or independent) - asset_in_cluster[a][t] = bool
    asset_in_cluster = [[False]*n for _ in range(n_assets)]
    if sync_clusters:
        in_cluster = False
        for t in range(n):
            if in_cluster:
                if rng.random() > cluster_persistence:
                    in_cluster = False
            else:
                if rng.random() < cluster_probability:
                    in_cluster = True
            for a in range(n_assets):
                asset_in_cluster[a][t] = in_cluster
    else:
        for a in range(n_assets):
            in_cluster = False
            for t in range(n):
                if in_cluster:
                    if rng.random() > cluster_persistence:
                        in_cluster = False
                else:
                    if rng.random() < cluster_probability:
                        in_cluster = True
                asset_in_cluster[a][t] = in_cluster

    data_dict = {}
    for i in range(n_assets):
        idio_rng = np.random.default_rng(config.seed + 1000 + i)
        beta = rng.uniform(0.7, 1.3)

        returns = np.zeros(n)
        for t in range(n):
            vol = cluster_vol if asset_in_cluster[i][t] else base_vol
            idio_return = idio_rng.normal(0.0, vol)
            returns[t] = beta * market_returns[t] + idio_return

        returns += 0.0002  # Small drift
        prices = config.initial_price * np.exp(np.cumsum(returns))
        data_dict[f"ASSET_{i}"] = _ohlcv_from_close(
            prices, dates, config.seed + i, config.initial_price
        )

    return data_dict


def describe_scenario(scenario_name: str, **params) -> Dict:
    """Return a description of the scenario construction for documentation."""
    return {
        "scenario": scenario_name,
        "purpose": f"Adversarial stress test: {scenario_name}",
        "parameters": params,
    }


# CLI entry point
def main():
    import argparse
    import json

    parser = argparse.ArgumentParser(
        description="Generate adversarial scenario fixtures for stress testing"
    )
    parser.add_argument("--scenario", required=True, choices=[
        "regime_shift", "correlation_breakdown", "fat_tail_crash",
        "liquidity_crisis", "trend_persistence", "structural_break",
        "volatility_clustering", "multi_asset_volatility_clustering"
    ])
    parser.add_argument("--out", required=True, help="Output directory")
    parser.add_argument("--periods", type=int, default=DEFAULT_PERIODS)
    parser.add_argument("--start", default=DEFAULT_START)
    parser.add_argument("--price", type=float, default=DEFAULT_INITIAL_PRICE)
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)

    # Scenario-specific args (subset for CLI)
    parser.add_argument("--bull-months", type=int, default=18)
    parser.add_argument("--bear-months", type=int, default=18)
    parser.add_argument("--n-assets", type=int, default=5)
    parser.add_argument("--crash-prob", type=float, default=0.002)
    parser.add_argument("--crisis-start", type=float, default=0.6)
    parser.add_argument("--crisis-months", type=int, default=6)
    parser.add_argument("--break-point", type=float, default=0.5)

    args = parser.parse_args()

    config = ScenarioConfig(
        periods=args.periods,
        start_date=args.start,
        initial_price=args.price,
        seed=args.seed,
    )

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    if args.scenario == "regime_shift":
        df = generate_regime_shift(config, bull_months=args.bull_months, bear_months=args.bear_months)
        path = out_dir / "regime_shift_ohlcv.csv"
        df.to_csv(path, index=False)
        print(f"Generated: {path}")

    elif args.scenario == "correlation_breakdown":
        data = generate_correlation_breakdown(config, n_assets=args.n_assets, break_point=args.break_point)
        # Write multi-symbol CSV
        rows = []
        for symbol, df in data.items():
            df = df.copy()
            df["symbol"] = symbol
            rows.append(df)
        panel = pd.concat(rows, ignore_index=True).sort_values(["date", "symbol"])
        path = out_dir / "correlation_breakdown_ohlcv.csv"
        panel.to_csv(path, index=False)
        print(f"Generated: {path}")

    elif args.scenario == "fat_tail_crash":
        df = generate_fat_tail_crash(config, crash_probability=args.crash_prob)
        path = out_dir / "fat_tail_crash_ohlcv.csv"
        df.to_csv(path, index=False)
        print(f"Generated: {path}")

    elif args.scenario == "liquidity_crisis":
        df = generate_liquidity_crisis(config, crisis_start=args.crisis_start, crisis_duration_months=args.crisis_months)
        path = out_dir / "liquidity_crisis_ohlcv.csv"
        df.to_csv(path, index=False)
        print(f"Generated: {path}")

    elif args.scenario == "trend_persistence":
        df = generate_trend_persistence(config)
        path = out_dir / "trend_persistence_ohlcv.csv"
        df.to_csv(path, index=False)
        print(f"Generated: {path}")

    elif args.scenario == "structural_break":
        df = generate_structural_break(config, break_point=args.break_point)
        path = out_dir / "structural_break_ohlcv.csv"
        df.to_csv(path, index=False)
        print(f"Generated: {path}")

    elif args.scenario == "volatility_clustering":
        df = generate_volatility_clustering(config)
        path = out_dir / "volatility_clustering_ohlcv.csv"
        df.to_csv(path, index=False)
        print(f"Generated: {path}")

    elif args.scenario == "multi_asset_volatility_clustering":
        data = generate_multi_asset_volatility_clustering(config, n_assets=args.n_assets)
        rows = []
        for symbol, df in data.items():
            df = df.copy()
            df["symbol"] = symbol
            rows.append(df)
        panel = pd.concat(rows, ignore_index=True).sort_values(["date", "symbol"])
        path = out_dir / "multi_asset_vol_clustering_ohlcv.csv"
        panel.to_csv(path, index=False)
        print(f"Generated: {path}")


if __name__ == "__main__":
    main()
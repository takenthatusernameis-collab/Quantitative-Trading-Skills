#!/usr/bin/env python3
"""Generate sample OHLCV datasets for testing the backtesting skill."""
import numpy as np
import pandas as pd
from pathlib import Path


def generate_single_asset_data(periods: int = 504, seed: int = 42) -> pd.DataFrame:
    """Generate OHLCV data for a single asset."""
    rng = np.random.default_rng(seed)
    dates = pd.date_range("2018-01-01", periods=periods, freq="B")
    returns = rng.normal(0.0005, 0.015, len(dates))
    prices = 100 * np.exp(np.cumsum(returns))

    return pd.DataFrame({
        "date": dates,
        "open": prices * rng.uniform(0.995, 1.005, len(dates)),
        "high": prices * rng.uniform(1.005, 1.02, len(dates)),
        "low": prices * rng.uniform(0.98, 0.995, len(dates)),
        "close": prices,
        "volume": rng.integers(1_000_000, 10_000_000, len(dates)),
    })


def generate_multi_asset_data(n_assets: int = 5, periods: int = 504, seed: int = 42) -> dict:
    """
    Generate a synthetic multi-asset universe with correlated returns.

    Each asset has a unique return profile with controlled correlation
    to a common market factor, simulating realistic cross-sectional structure.

    Returns:
        dict mapping symbol names (ASSET_0, ASSET_1, ...) to DataFrames
    """
    rng = np.random.default_rng(seed)
    dates = pd.date_range("2018-01-01", periods=periods, freq="B")

    # Common market factor (systematic risk)
    market_returns = rng.normal(0.0003, 0.012, periods)

    # Asset-specific factor loadings (betas) and idiosyncratic vol
    betas = rng.uniform(0.7, 1.3, n_assets)
    idio_vols = rng.uniform(0.008, 0.025, n_assets)
    idio_seeds = rng.integers(0, 2**31, n_assets)

    data_dict = {}
    for i in range(n_assets):
        # Idiosyncratic returns
        idio_rng = np.random.default_rng(idio_seeds[i])
        idio_returns = idio_rng.normal(0.0, idio_vols[i], periods)

        # Total returns = beta * market + idiosyncratic
        asset_returns = betas[i] * market_returns + idio_returns

        # Add small positive drift
        asset_returns += 0.0002

        prices = 100 * np.exp(np.cumsum(asset_returns))

        df = pd.DataFrame({
            "date": dates,
            "open": prices * rng.uniform(0.995, 1.005, periods),
            "high": prices * rng.uniform(1.005, 1.02, periods),
            "low": prices * rng.uniform(0.98, 0.995, periods),
            "close": prices,
            "volume": rng.integers(500_000, 20_000_000, periods),
        })

        data_dict[f"ASSET_{i}"] = df

    return data_dict


if __name__ == "__main__":
    # Backward compatibility: generate the original single asset file
    df = generate_single_asset_data()
    out = Path(__file__).parent.parent / "assets" / "example_data" / "sample_ohlcv.csv"
    df.to_csv(out, index=False)
    print(f"Wrote {out} ({len(df)} rows)")
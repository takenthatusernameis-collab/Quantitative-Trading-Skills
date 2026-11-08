#!/usr/bin/env python3
"""
Market Regime Detection Module.

Provides methods to identify market regimes (bull/bear/sideways, high/low volatility)
and compute regime-dependent performance metrics for strategy evaluation.
"""

from typing import Dict, List, Optional, Tuple, Literal
from dataclasses import dataclass
from enum import Enum

import pandas as pd
import numpy as np


class TrendRegime(Enum):
    """Market trend regime classification."""
    BULL = "bull"
    BEAR = "bear"
    SIDEWAYS = "sideways"
    UNKNOWN = "unknown"


class VolatilityRegime(Enum):
    """Market volatility regime classification."""
    HIGH = "high"
    LOW = "low"
    UNKNOWN = "unknown"


@dataclass
class RegimeConfig:
    """Configuration for regime detection."""
    # Trend regime parameters
    trend_ma_short: int = 50
    trend_ma_long: int = 200
    trend_threshold: float = 0.02  # 2% threshold for trend classification

    # Volatility regime parameters
    vol_window: int = 63  # ~3 months
    vol_quantile_high: float = 0.75
    vol_quantile_low: float = 0.25

    # Combined regime parameters
    min_regime_length: int = 21  # Minimum bars for a regime to be valid


@dataclass
class RegimePeriod:
    """A contiguous period of a specific regime."""
    regime: str
    start_date: pd.Timestamp
    end_date: pd.Timestamp
    length: int
    metrics: Dict[str, float]


def detect_trend_regime(
    close: pd.Series,
    ma_short: int = 50,
    ma_long: int = 200,
    threshold: float = 0.02,
) -> pd.Series:
    """
    Detect trend regime (bull/bear/sideways) using moving average crossover.

    Args:
        close: Close price series
        ma_short: Short moving average window
        ma_long: Long moving average window
        threshold: Minimum separation between MAs to classify as bull/bear

    Returns:
        Series with regime labels: 'bull', 'bear', 'sideways', 'unknown'
    """
    if len(close) < ma_long:
        return pd.Series(TrendRegime.UNKNOWN.value, index=close.index)

    sma_short = close.rolling(ma_short).mean()
    sma_long = close.rolling(ma_long).mean()

    # Relative difference between MAs
    ma_diff = (sma_short - sma_long) / sma_long

    regimes = pd.Series(TrendRegime.UNKNOWN.value, index=close.index)
    regimes[ma_diff > threshold] = TrendRegime.BULL.value
    regimes[ma_diff < -threshold] = TrendRegime.BEAR.value
    regimes[(ma_diff >= -threshold) & (ma_diff <= threshold)] = TrendRegime.SIDEWAYS.value

    # Forward fill to handle initial NaN period
    regimes = regimes.replace(TrendRegime.UNKNOWN.value, np.nan).ffill().fillna(TrendRegime.UNKNOWN.value)

    return regimes


def detect_volatility_regime(
    close: pd.Series,
    window: int = 63,
    quantile_high: float = 0.75,
    quantile_low: float = 0.25,
) -> pd.Series:
    """
    Detect volatility regime (high/low) using rolling realized volatility.

    Args:
        close: Close price series
        window: Rolling window for volatility calculation
        quantile_high: Upper quantile threshold for high volatility
        quantile_low: Lower quantile threshold for low volatility

    Returns:
        Series with regime labels: 'high', 'low', 'unknown'
    """
    if len(close) < window + 1:
        return pd.Series(VolatilityRegime.UNKNOWN.value, index=close.index)

    returns = close.pct_change()
    rolling_vol = returns.rolling(window).std() * np.sqrt(252)  # Annualized

    # Compute thresholds from the full series (expanding)
    vol_high_threshold = rolling_vol.expanding().quantile(quantile_high)
    vol_low_threshold = rolling_vol.expanding().quantile(quantile_low)

    regimes = pd.Series(VolatilityRegime.UNKNOWN.value, index=close.index)
    regimes[rolling_vol > vol_high_threshold] = VolatilityRegime.HIGH.value
    regimes[rolling_vol < vol_low_threshold] = VolatilityRegime.LOW.value
    regimes[
        (rolling_vol >= vol_low_threshold) & (rolling_vol <= vol_high_threshold)
    ] = VolatilityRegime.UNKNOWN.value  # Medium vol = unknown for binary classification

    # Forward fill to handle initial NaN period
    regimes = regimes.replace(VolatilityRegime.UNKNOWN.value, np.nan).ffill().fillna(VolatilityRegime.UNKNOWN.value)

    return regimes


def detect_combined_regime(
    close: pd.Series,
    config: Optional[RegimeConfig] = None,
) -> pd.Series:
    """
    Detect combined trend + volatility regime.

    Returns labels like: 'bull_high_vol', 'bull_low_vol', 'bear_high_vol',
    'bear_low_vol', 'sideways_high_vol', 'sideways_low_vol', 'unknown'
    """
    if config is None:
        config = RegimeConfig()

    trend = detect_trend_regime(
        close, config.trend_ma_short, config.trend_ma_long, config.trend_threshold
    )
    vol = detect_volatility_regime(
        close, config.vol_window, config.vol_quantile_high, config.vol_quantile_low
    )

    combined = pd.Series("unknown", index=close.index)

    # Only assign combined regime when both trend and vol are known
    mask_known = (trend != TrendRegime.UNKNOWN.value) & (vol != VolatilityRegime.UNKNOWN.value)
    combined[mask_known] = trend[mask_known] + "_" + vol[mask_known]

    # Forward fill unknown periods
    combined = combined.replace("unknown", np.nan).ffill().fillna("unknown")

    return combined


def identify_regime_periods(regimes: pd.Series) -> List[RegimePeriod]:
    """
    Identify contiguous regime periods from a regime series.

    Args:
        regimes: Series with regime labels

    Returns:
        List of RegimePeriod objects
    """
    periods = []
    current_regime = None
    start_idx = None

    for i, (date, regime) in enumerate(regimes.items()):
        if regime != current_regime:
            if current_regime is not None and start_idx is not None:
                end_date = regimes.index[i - 1]
                periods.append(RegimePeriod(
                    regime=current_regime,
                    start_date=regimes.index[start_idx],
                    end_date=end_date,
                    length=i - start_idx,
                    metrics={}
                ))
            current_regime = regime
            start_idx = i

    # Handle last period
    if current_regime is not None and start_idx is not None:
        periods.append(RegimePeriod(
            regime=current_regime,
            start_date=regimes.index[start_idx],
            end_date=regimes.index[-1],
            length=len(regimes) - start_idx,
            metrics={}
        ))

    return periods


def compute_regime_performance(
    returns: pd.Series,
    regimes: pd.Series,
    min_period_length: int = 21,
) -> Dict[str, Dict[str, float]]:
    """
    Compute performance metrics per regime.

    Args:
        returns: Strategy returns series
        regimes: Regime labels series (aligned with returns)
        min_period_length: Minimum observations for a regime to be reported

    Returns:
        Dict mapping regime -> metrics dict
    """
    # Align series
    aligned = pd.DataFrame({"returns": returns, "regime": regimes}).dropna()

    if len(aligned) == 0:
        return {}

    results = {}

    for regime in aligned["regime"].unique():
        if regime == "unknown":
            continue

        regime_returns = aligned.loc[aligned["regime"] == regime, "returns"]

        if len(regime_returns) < min_period_length:
            continue

        # Basic metrics
        total_return = (1 + regime_returns).prod() - 1
        ann_return = (1 + total_return) ** (252 / len(regime_returns)) - 1
        ann_vol = regime_returns.std() * np.sqrt(252)
        sharpe = ann_return / ann_vol if ann_vol > 0 else 0.0

        # Drawdown
        equity = (1 + regime_returns).cumprod()
        running_max = equity.expanding().max()
        drawdown = (equity - running_max) / running_max
        max_drawdown = drawdown.min()

        # Win rate
        win_rate = (regime_returns > 0).mean()

        # Skewness / Kurtosis
        skew = regime_returns.skew()
        kurt = regime_returns.kurtosis()

        results[regime] = {
            "n_observations": len(regime_returns),
            "total_return": float(total_return),
            "annualized_return": float(ann_return),
            "annualized_volatility": float(ann_vol),
            "sharpe_ratio": float(sharpe),
            "max_drawdown": float(max_drawdown),
            "win_rate": float(win_rate),
            "skewness": float(skew),
            "kurtosis": float(kurt),
        }

    return results


def regime_performance_summary(
    returns: pd.Series,
    close: pd.Series,
    config: Optional[RegimeConfig] = None,
) -> Dict:
    """
    Generate a complete regime-dependent performance summary.

    Args:
        returns: Strategy returns series
        close: Market close price series (for regime detection)
        config: Regime detection configuration

    Returns:
        Dict with regime detection results and per-regime performance
    """
    if config is None:
        config = RegimeConfig()

    # Detect regimes on market data
    trend_regimes = detect_trend_regime(
        close, config.trend_ma_short, config.trend_ma_long, config.trend_threshold
    )
    vol_regimes = detect_volatility_regime(
        close, config.vol_window, config.vol_quantile_high, config.vol_quantile_low
    )
    combined_regimes = detect_combined_regime(close, config)

    # Align all series
    df = pd.DataFrame({
        "returns": returns,
        "trend_regime": trend_regimes,
        "vol_regime": vol_regimes,
        "combined_regime": combined_regimes,
    }).dropna()

    if len(df) == 0:
        return {
            "trend_regime_performance": {},
            "volatility_regime_performance": {},
            "combined_regime_performance": {},
            "regime_periods": [],
        }

    trend_perf = compute_regime_performance(
        df["returns"], df["trend_regime"], config.min_regime_length
    )
    vol_perf = compute_regime_performance(
        df["returns"], df["vol_regime"], config.min_regime_length
    )
    combined_perf = compute_regime_performance(
        df["returns"], df["combined_regime"], config.min_regime_length
    )

    # Identify regime periods for combined regime
    regime_periods = identify_regime_periods(df["combined_regime"])

    # Add performance metrics to periods
    for period in regime_periods:
        if period.regime in combined_perf:
            period.metrics = combined_perf[period.regime]

    return {
        "config": {
            "trend_ma_short": config.trend_ma_short,
            "trend_ma_long": config.trend_ma_long,
            "trend_threshold": config.trend_threshold,
            "vol_window": config.vol_window,
            "vol_quantile_high": config.vol_quantile_high,
            "vol_quantile_low": config.vol_quantile_low,
            "min_regime_length": config.min_regime_length,
        },
        "trend_regime_performance": trend_perf,
        "volatility_regime_performance": vol_perf,
        "combined_regime_performance": combined_perf,
        "regime_periods": [
            {
                "regime": p.regime,
                "start_date": p.start_date.isoformat() if isinstance(p.start_date, pd.Timestamp) else str(p.start_date),
                "end_date": p.end_date.isoformat() if isinstance(p.end_date, pd.Timestamp) else str(p.end_date),
                "length": p.length,
                "metrics": p.metrics,
            }
            for p in regime_periods
        ],
        "regime_distribution": df["combined_regime"].value_counts().to_dict(),
    }


def add_regime_analysis_to_results(
    results: Dict,
    data: pd.DataFrame | Dict[str, pd.DataFrame],
    returns_key: str = "returns",
    close_key: str = "close",
    config: Optional[RegimeConfig] = None,
) -> Dict:
    """
    Add regime-dependent performance analysis to backtest results.

    Args:
        results: Backtest results dictionary
        data: Market data (DataFrame or dict of DataFrames for panels)
        returns_key: Key in results for strategy returns
        close_key: Column name for close prices in data
        config: Regime detection configuration

    Returns:
        Updated results dict with regime_analysis key
    """
    # Extract returns
    if returns_key not in results:
        return results

    returns = results[returns_key]
    if not isinstance(returns, pd.Series):
        try:
            returns = pd.Series(returns)
        except Exception:
            return results

    # Extract close prices
    if isinstance(data, dict):
        # Panel data - use first asset's close
        first_asset = next(iter(data.values()))
        if isinstance(first_asset, pd.DataFrame) and close_key in first_asset.columns:
            close = first_asset[close_key]
        else:
            return results
    elif isinstance(data, pd.DataFrame):
        if close_key in data.columns:
            close = data[close_key]
        else:
            return results
    else:
        return results

    # Align returns and close
    common_index = returns.index.intersection(close.index)
    if len(common_index) == 0:
        return results

    returns_aligned = returns.loc[common_index]
    close_aligned = close.loc[common_index]

    # Compute regime analysis
    regime_analysis = regime_performance_summary(returns_aligned, close_aligned, config)

    results["regime_analysis"] = regime_analysis
    return results


if __name__ == "__main__":
    # Demo
    import tempfile

    dates = pd.date_range("2020-01-01", periods=500, freq="B")
    np.random.seed(42)

    # Generate synthetic market with regime changes
    # Bull market: higher drift, lower vol
    # Bear market: negative drift, higher vol
    # Sideways: near-zero drift, medium vol
    regime_lengths = [100, 150, 100, 150]
    returns_list = []
    for i, length in enumerate(regime_lengths):
        if i % 3 == 0:  # Bull
            mu, sigma = 0.001, 0.01
        elif i % 3 == 1:  # Bear
            mu, sigma = -0.0005, 0.02
        else:  # Sideways
            mu, sigma = 0.0001, 0.015
        returns_list.append(np.random.normal(mu, sigma, length))

    market_returns = np.concatenate(returns_list)
    market_prices = 100 * np.exp(np.cumsum(market_returns))

    market_data = pd.DataFrame({
        "close": market_prices,
    }, index=dates[:len(market_prices)])

    # Strategy returns (some alpha in bull, negative in bear)
    strategy_returns = market_returns * 0.5 + np.random.normal(0.0002, 0.005, len(market_returns))
    strategy_returns = pd.Series(strategy_returns, index=market_data.index)

    print("Testing regime detection...")
    config = RegimeConfig(trend_ma_short=20, trend_ma_long=60, trend_threshold=0.01)

    summary = regime_performance_summary(strategy_returns, market_data["close"], config)

    print("\nTrend Regime Performance:")
    for regime, metrics in summary["trend_regime_performance"].items():
        print(f"  {regime}: Sharpe={metrics['sharpe_ratio']:.3f}, Return={metrics['annualized_return']:.2%}, n={metrics['n_observations']}")

    print("\nVolatility Regime Performance:")
    for regime, metrics in summary["volatility_regime_performance"].items():
        print(f"  {regime}: Sharpe={metrics['sharpe_ratio']:.3f}, Return={metrics['annualized_return']:.2%}, n={metrics['n_observations']}")

    print("\nCombined Regime Performance:")
    for regime, metrics in summary["combined_regime_performance"].items():
        print(f"  {regime}: Sharpe={metrics['sharpe_ratio']:.3f}, Return={metrics['annualized_return']:.2%}, n={metrics['n_observations']}")

    print("\nRegime Periods:")
    for period in summary["regime_periods"]:
        print(f"  {period['regime']}: {period['start_date']} to {period['end_date']} ({period['length']} bars)")

    print("\nRegime Distribution:")
    for regime, count in summary["regime_distribution"].items():
        print(f"  {regime}: {count} bars")

    print("\nTest passed!")
#!/usr/bin/env python3
"""
Factory for creating common strategy templates.

Provides pre-built strategy patterns for trend following, mean reversion,
momentum, and other common quantitative trading approaches.
"""

import json
from typing import Dict, Any, Optional, Callable
from dataclasses import dataclass, field
from abc import ABC, abstractmethod
import pandas as pd
import numpy as np


@dataclass
class StrategyConfig:
    """Configuration for a trading strategy."""
    name: str
    parameters: Dict[str, Any] = field(default_factory=dict)
    description: str = ""


class StrategyBase(ABC):
    """Base class for all strategies."""

    def __init__(self, config: StrategyConfig):
        self.config = config
        self.name = config.name
        self.parameters = config.parameters

    @abstractmethod
    def generate_signals(self, data: pd.DataFrame) -> pd.Series:
        """Generate trading signals from market data.

        Returns:
            Series with values: 1 (long), 0 (flat), -1 (short)
        """
        pass

    def get_position_sizing(self, data: pd.DataFrame, signals: pd.Series) -> pd.Series:
        """Default position sizing: full position when signal != 0."""
        return signals.abs()


class SMACrossoverStrategy(StrategyBase):
    """Simple Moving Average Crossover Strategy.

    Long when fast SMA > slow SMA, flat/short otherwise.
    """

    def generate_signals(self, data: pd.DataFrame) -> pd.Series:
        fast_period = self.parameters.get("fast_period", 20)
        slow_period = self.parameters.get("slow_period", 50)

        fast_sma = data["close"].rolling(fast_period).mean()
        slow_sma = data["close"].rolling(slow_period).mean()

        signals = pd.Series(0, index=data.index)
        signals[fast_sma > slow_sma] = 1
        signals[fast_sma <= slow_sma] = 0  # or -1 for long/short

        return signals


class EMACrossoverStrategy(StrategyBase):
    """Exponential Moving Average Crossover Strategy."""

    def generate_signals(self, data: pd.DataFrame) -> pd.Series:
        fast_period = self.parameters.get("fast_period", 12)
        slow_period = self.parameters.get("slow_period", 26)

        fast_ema = data["close"].ewm(span=fast_period, adjust=False).mean()
        slow_ema = data["close"].ewm(span=slow_period, adjust=False).mean()

        signals = pd.Series(0, index=data.index)
        signals[fast_ema > slow_ema] = 1
        signals[fast_ema <= slow_ema] = 0

        return signals


class BollingerBandsMeanReversion(StrategyBase):
    """Bollinger Bands Mean Reversion Strategy.

    Long when price touches lower band, exit at middle band.
    Short when price touches upper band, exit at middle band.
    """

    def generate_signals(self, data: pd.DataFrame) -> pd.Series:
        period = self.parameters.get("period", 20)
        std_dev = self.parameters.get("std_dev", 2.0)

        middle = data["close"].rolling(period).mean()
        std = data["close"].rolling(period).std()
        upper = middle + std_dev * std
        lower = middle - std_dev * std

        signals = pd.Series(0, index=data.index)
        position = 0

        for i in range(len(data)):
            close = data["close"].iloc[i]
            up = upper.iloc[i]
            low = lower.iloc[i]
            mid = middle.iloc[i]

            if position == 0:
                if close <= low:
                    position = 1
                elif close >= up:
                    position = -1
            elif position == 1 and close >= mid:
                position = 0
            elif position == -1 and close <= mid:
                position = 0

            signals.iloc[i] = position

        return signals


class RSIMeanReversion(StrategyBase):
    """RSI Mean Reversion Strategy.

    Long when RSI < oversold, exit when RSI > neutral.
    Short when RSI > overbought, exit when RSI < neutral.
    """

    def generate_signals(self, data: pd.DataFrame) -> pd.Series:
        period = self.parameters.get("period", 14)
        oversold = self.parameters.get("oversold", 30)
        overbought = self.parameters.get("overbought", 70)
        neutral = self.parameters.get("neutral", 50)

        delta = data["close"].diff()
        gain = delta.where(delta > 0, 0).rolling(period).mean()
        loss = -delta.where(delta < 0, 0).rolling(period).mean()
        rs = gain / loss
        rsi = 100 - (100 / (1 + rs))

        signals = pd.Series(0, index=data.index)
        position = 0

        for i in range(len(data)):
            rsi_val = rsi.iloc[i]

            if position == 0:
                if rsi_val <= oversold:
                    position = 1
                elif rsi_val >= overbought:
                    position = -1
            elif position == 1 and rsi_val >= neutral:
                position = 0
            elif position == -1 and rsi_val <= neutral:
                position = 0

            signals.iloc[i] = position

        return signals


class DonchianChannelBreakout(StrategyBase):
    """Donchian Channel Breakout (Trend Following).

    Long when price breaks above N-period high.
    Short when price breaks below N-period low.
    Exit at opposite channel or trailing stop.
    """

    def generate_signals(self, data: pd.DataFrame) -> pd.Series:
        period = self.parameters.get("period", 20)
        exit_period = self.parameters.get("exit_period", 10)

        upper = data["high"].rolling(period).max()
        lower = data["low"].rolling(period).min()
        exit_upper = data["high"].rolling(exit_period).max()
        exit_lower = data["low"].rolling(exit_period).min()

        signals = pd.Series(0, index=data.index)
        position = 0

        for i in range(len(data)):
            high = data["high"].iloc[i]
            low = data["low"].iloc[i]
            up = upper.iloc[i]
            low_ch = lower.iloc[i]
            exit_up = exit_upper.iloc[i]
            exit_low = exit_lower.iloc[i]

            if position == 0:
                if high >= up:
                    position = 1
                elif low <= low_ch:
                    position = -1
            elif position == 1 and low <= exit_low:
                position = 0
            elif position == -1 and high >= exit_up:
                position = 0

            signals.iloc[i] = position

        return signals


class CrossSectionalMomentum(StrategyBase):
    """Cross-Sectional Momentum Strategy.

    Ranks assets by past return, goes long top quantile, short bottom quantile.
    Requires multi-asset data (handled at portfolio level).
    """

    def generate_signals(self, data: pd.DataFrame) -> pd.Series:
        # This is a placeholder - actual implementation requires panel data
        lookback = self.parameters.get("lookback", 252)
        top_quantile = self.parameters.get("top_quantile", 0.2)
        bottom_quantile = self.parameters.get("bottom_quantile", 0.2)

        # For single asset, just return momentum signal
        returns = data["close"].pct_change(lookback)
        signals = pd.Series(0, index=data.index)
        signals[returns > 0] = 1
        signals[returns < 0] = -1

        return signals


class DualMomentumStrategy(StrategyBase):
    """Dual Momentum (Gary Antonacci).

    Combines absolute momentum (asset vs cash) and relative momentum (asset vs assets).
    """

    def generate_signals(self, data: pd.DataFrame) -> pd.Series:
        lookback = self.parameters.get("lookback", 12 * 21)  # ~12 months

        # Absolute momentum: asset return > 0?
        asset_return = data["close"].pct_change(lookback)

        # For single asset, simplified version
        signals = pd.Series(0, index=data.index)
        signals[asset_return > 0] = 1
        signals[asset_return <= 0] = 0  # Cash

        return signals


class MeanReversionZScore(StrategyBase):
    """Z-Score Mean Reversion (Pairs Trading style).

    Uses rolling z-score of price (or spread) for entry/exit.
    """

    def generate_signals(self, data: pd.DataFrame) -> pd.Series:
        period = self.parameters.get("period", 20)
        entry_z = self.parameters.get("entry_z", 2.0)
        exit_z = self.parameters.get("exit_z", 0.5)

        # Use close price z-score (for single asset, typically use spread)
        rolling_mean = data["close"].rolling(period).mean()
        rolling_std = data["close"].rolling(period).std()
        zscore = (data["close"] - rolling_mean) / rolling_std

        signals = pd.Series(0, index=data.index)
        position = 0

        for i in range(len(data)):
            z = zscore.iloc[i]

            if position == 0:
                if z <= -entry_z:
                    position = 1
                elif z >= entry_z:
                    position = -1
            elif position == 1 and z >= -exit_z:
                position = 0
            elif position == -1 and z <= exit_z:
                position = 0

            signals.iloc[i] = position

        return signals


class VolatilityTargeting(StrategyBase):
    """Volatility Targeting Position Sizing.

    Adjusts position size to target a specific portfolio volatility.
    This is a position sizing overlay, not a signal generator.
    """

    def __init__(self, config: StrategyConfig, base_strategy: StrategyBase):
        super().__init__(config)
        self.base_strategy = base_strategy
        self.target_vol = self.parameters.get("target_vol", 0.15)  # 15% annual
        self.lookback = self.parameters.get("lookback", 63)  # ~3 months

    def generate_signals(self, data: pd.DataFrame) -> pd.Series:
        base_signals = self.base_strategy.generate_signals(data)

        # Calculate realized volatility
        returns = data["close"].pct_change()
        realized_vol = returns.rolling(self.lookback).std() * np.sqrt(252)

        # Position multiplier to target volatility
        vol_multiplier = self.target_vol / realized_vol
        vol_multiplier = vol_multiplier.clip(0, 2)  # Cap at 2x leverage

        # Apply to base signals
        sized_signals = base_signals * vol_multiplier

        return sized_signals


# Strategy registry
STRATEGY_REGISTRY = {
    "sma_crossover": SMACrossoverStrategy,
    "ema_crossover": EMACrossoverStrategy,
    "bollinger_bands": BollingerBandsMeanReversion,
    "rsi_mean_reversion": RSIMeanReversion,
    "donchian_breakout": DonchianChannelBreakout,
    "cross_sectional_momentum": CrossSectionalMomentum,
    "dual_momentum": DualMomentumStrategy,
    "zscore_mean_reversion": MeanReversionZScore,
}


def build_strategy(strategy_type: str, params_json: Optional[str] = None) -> StrategyBase:
    """Build a strategy instance from type and parameters.

    Args:
        strategy_type: Strategy identifier from registry
        params_json: JSON string of parameters

    Returns:
        Configured strategy instance
    """
    if strategy_type not in STRATEGY_REGISTRY:
        available = ", ".join(STRATEGY_REGISTRY.keys())
        raise ValueError(f"Unknown strategy: {strategy_type}. Available: {available}")

    params = {}
    if params_json:
        params = json.loads(params_json)

    config = StrategyConfig(
        name=strategy_type,
        parameters=params,
        description=f"{strategy_type} strategy"
    )

    strategy_class = STRATEGY_REGISTRY[strategy_type]
    return strategy_class(config)


def list_strategies() -> Dict[str, str]:
    """List available strategies with descriptions."""
    return {
        "sma_crossover": "Simple Moving Average Crossover (Trend Following)",
        "ema_crossover": "Exponential Moving Average Crossover (Trend Following)",
        "bollinger_bands": "Bollinger Bands Mean Reversion",
        "rsi_mean_reversion": "RSI Mean Reversion",
        "donchian_breakout": "Donchian Channel Breakout (Trend Following)",
        "cross_sectional_momentum": "Cross-Sectional Momentum (Multi-Asset)",
        "dual_momentum": "Dual Momentum (Absolute + Relative)",
        "zscore_mean_reversion": "Z-Score Mean Reversion (Pairs Style)",
    }


def get_strategy_defaults(strategy_type: str) -> Dict[str, Any]:
    """Get default parameters for a strategy."""
    defaults = {
        "sma_crossover": {"fast_period": 20, "slow_period": 50},
        "ema_crossover": {"fast_period": 12, "slow_period": 26},
        "bollinger_bands": {"period": 20, "std_dev": 2.0},
        "rsi_mean_reversion": {"period": 14, "oversold": 30, "overbought": 70, "neutral": 50},
        "donchian_breakout": {"period": 20, "exit_period": 10},
        "cross_sectional_momentum": {"lookback": 252, "top_quantile": 0.2, "bottom_quantile": 0.2},
        "dual_momentum": {"lookback": 252},
        "zscore_mean_reversion": {"period": 20, "entry_z": 2.0, "exit_z": 0.5},
    }
    return defaults.get(strategy_type, {})


if __name__ == "__main__":
    # Demo
    import tempfile

    dates = pd.date_range("2020-01-01", periods=200, freq="B")
    np.random.seed(42)
    returns = np.random.normal(0.0005, 0.015, 200)
    prices = 100 * np.exp(np.cumsum(returns))

    df = pd.DataFrame({
        "open": prices * np.random.uniform(0.995, 1.005, 200),
        "high": prices * np.random.uniform(1.005, 1.02, 200),
        "low": prices * np.random.uniform(0.98, 0.995, 200),
        "close": prices,
        "volume": np.random.randint(1000000, 10000000, 200)
    }, index=dates)

    print("Available strategies:")
    for k, v in list_strategies().items():
        print(f"  {k}: {v}")

    print("\nTesting SMA Crossover:")
    strategy = build_strategy("sma_crossover", '{"fast_period": 10, "slow_period": 30}')
    signals = strategy.generate_signals(df)
    print(f"Signal changes: {(signals.diff() != 0).sum()}")
    print(f"Long periods: {(signals == 1).sum()}")
    print(f"Flat periods: {(signals == 0).sum()}")
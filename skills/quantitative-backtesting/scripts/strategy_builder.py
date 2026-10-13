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

        # Compute prior N-period channel; shift by 1 to exclude current bar
        upper = data["high"].rolling(period).max().shift(1)
        lower = data["low"].rolling(period).min().shift(1)
        exit_upper = data["high"].rolling(exit_period).max().shift(1)
        exit_lower = data["low"].rolling(exit_period).min().shift(1)

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

    Ranks assets by past return each period; goes long top quantile,
    short bottom quantile. Supports both multi-asset panel data and
    single-asset fallback.

    Multi-asset data formats:
    - DataFrame with MultiIndex columns: (field, symbol) e.g. ('close', 'AAPL')
    - Dict mapping symbol -> DataFrame with OHLCV columns

    Single-asset DataFrame (backward compatible): uses rolling quantile
    thresholds on historical returns as a momentum filter.
    """

    def generate_signals(self, data: pd.DataFrame | dict) -> pd.Series:
        lookback = self.parameters.get("lookback", 252)
        top_quantile = self.parameters.get("top_quantile", 0.2)
        bottom_quantile = self.parameters.get("bottom_quantile", 0.2)

        # Detect multi-asset panel data
        if isinstance(data, dict):
            self._validate_quantiles(top_quantile, bottom_quantile)
            return self._generate_multi_asset_signals_dict(data, lookback, top_quantile, bottom_quantile)
        elif isinstance(data.columns, pd.MultiIndex):
            self._validate_quantiles(top_quantile, bottom_quantile)
            return self._generate_multi_asset_signals_multiindex(data, lookback, top_quantile, bottom_quantile)
        else:
            # Single-asset fallback (backward compatible)
            import warnings
            warnings.warn(
                "CrossSectionalMomentum used with single-asset data; "
                "falling back to rolling quantile momentum filter. "
                "For true cross-sectional momentum, provide panel data "
                "(MultiIndex columns or dict of DataFrames).",
                UserWarning,
                stacklevel=2,
            )
            return self._generate_single_asset_signals(data, lookback, top_quantile, bottom_quantile)

    def _validate_quantiles(self, top_quantile: float, bottom_quantile: float) -> None:
        """Warn about quantile choices that make the portfolio signal flat or ill-defined.

        The portfolio signal is the net exposure (n_long - n_short) / n_assets.
        Two parameter choices make that signal uninformative:

        - ``top_quantile == bottom_quantile``: the long and short books are the
          same size every period, so the net signal is exactly 0 (flat) by
          construction and the strategy never takes a position. This is the
          case for the default parameters (0.2 / 0.2).
        - ``top_quantile + bottom_quantile > 1.0``: the top and bottom
          selections overlap, so at least one asset is simultaneously long and
          short.

        These warnings apply to the multi-asset panel paths only; the
        single-asset fallback uses the quantiles as rolling-threshold
        boundaries, where symmetric values are valid.
        """
        import warnings

        if top_quantile == bottom_quantile:
            warnings.warn(
                "CrossSectionalMomentum: top_quantile == bottom_quantile "
                f"({top_quantile}). With the net-exposure convention "
                "((n_long - n_short) / n_assets), symmetric quantiles produce a "
                "flat (zero) portfolio signal by construction, so the strategy "
                "never takes a position. Use asymmetric quantiles (e.g. "
                "top_quantile=0.4, bottom_quantile=0.2) to take a directional "
                "net position, or model the long and short books separately.",
                UserWarning,
                stacklevel=3,
            )

        if top_quantile + bottom_quantile > 1.0:
            warnings.warn(
                "CrossSectionalMomentum: top_quantile + bottom_quantile > 1.0 "
                f"({top_quantile} + {bottom_quantile} = "
                f"{top_quantile + bottom_quantile}). The top and bottom "
                "selections overlap, so at least one asset is simultaneously "
                "long and short. Reduce the quantiles so that "
                "top_quantile + bottom_quantile <= 1.0.",
                UserWarning,
                stacklevel=3,
            )

    def _generate_multi_asset_signals_dict(
        self,
        data_dict: dict,
        lookback: int,
        top_quantile: float,
        bottom_quantile: float,
    ) -> pd.Series:
        """Generate signals from dict of symbol -> DataFrame."""
        if not data_dict:
            return pd.Series(dtype=float)

        # Align all symbols to common date index
        common_index = None
        for df in data_dict.values():
            if common_index is None:
                common_index = df.index
            else:
                common_index = common_index.intersection(df.index)

        if common_index is None or len(common_index) == 0:
            return pd.Series(dtype=float)

        common_index = common_index.sort_values()

        # Compute lookback returns for each symbol
        returns_dict = {}
        for symbol, df in data_dict.items():
            df_aligned = df.reindex(common_index)
            close = df_aligned["close"]
            returns_dict[symbol] = close.pct_change(lookback)

        returns_df = pd.DataFrame(returns_dict, index=common_index)

        # Rank cross-sectionally each period
        signals = pd.Series(0.0, index=common_index, dtype=float)

        for date in common_index[lookback:]:
            row = returns_df.loc[date].dropna()
            if len(row) == 0:
                continue

            n_assets = len(row)
            n_long = max(1, int(np.ceil(n_assets * top_quantile)))
            n_short = max(1, int(np.ceil(n_assets * bottom_quantile)))

            # Rank: highest returns = long, lowest returns = short
            ranked = row.rank(ascending=False, method="first")
            long_symbols = ranked[ranked <= n_long].index
            short_symbols = ranked[ranked > n_assets - n_short].index

            # For the portfolio-level signal, we return the net position
            # (number of longs - number of shorts) / n_assets
            # This gives a single scalar signal per period for the portfolio
            signals.loc[date] = (len(long_symbols) - len(short_symbols)) / n_assets

        return signals

    def _generate_multi_asset_signals_multiindex(
        self,
        data: pd.DataFrame,
        lookback: int,
        top_quantile: float,
        bottom_quantile: float,
    ) -> pd.Series:
        """Generate signals from DataFrame with MultiIndex columns (field, symbol)."""
        # Expect columns like ('close', 'AAPL'), ('close', 'MSFT'), etc.
        if "close" not in data.columns.get_level_values(0):
            raise ValueError("MultiIndex data must have 'close' as first level column")

        close_data = data["close"]  # DataFrame with symbols as columns
        returns_df = close_data.pct_change(lookback)

        signals = pd.Series(0.0, index=data.index, dtype=float)

        for date in data.index[lookback:]:
            row = returns_df.loc[date].dropna()
            if len(row) == 0:
                continue

            n_assets = len(row)
            n_long = max(1, int(np.ceil(n_assets * top_quantile)))
            n_short = max(1, int(np.ceil(n_assets * bottom_quantile)))

            ranked = row.rank(ascending=False, method="first")
            long_symbols = ranked[ranked <= n_long].index
            short_symbols = ranked[ranked > n_assets - n_short].index

            signals.loc[date] = (len(long_symbols) - len(short_symbols)) / n_assets

        return signals

    def _generate_single_asset_signals(
        self,
        data: pd.DataFrame,
        lookback: int,
        top_quantile: float,
        bottom_quantile: float,
    ) -> pd.Series:
        """Backward-compatible single-asset momentum filter using rolling quantiles."""
        returns = data["close"].pct_change(lookback)
        signals = pd.Series(0, index=data.index)

        rolling_window = min(lookback * 2, len(returns)) if len(returns) > lookback else lookback
        upper = returns.rolling(rolling_window).quantile(1 - top_quantile)
        lower = returns.rolling(rolling_window).quantile(bottom_quantile)

        signals[(returns > upper) & upper.notna()] = 1
        signals[(returns < lower) & lower.notna()] = -1

        return signals


class DualMomentumStrategy(StrategyBase):
    """Dual Momentum (Gary Antonacci).

    Combines absolute momentum (asset vs cash) and relative momentum (asset vs assets).

    Multi-asset data formats:
    - DataFrame with MultiIndex columns: (field, symbol) e.g. ('close', 'AAPL')
    - Dict mapping symbol -> DataFrame with OHLCV columns

    Single-asset DataFrame (backward compatible): uses absolute momentum only
    (asset return vs risk-free rate) with a warning.

    For multi-asset panel data:
    1. Compute lookback returns for each asset
    2. Absolute momentum filter: keep assets with return > risk_free_rate
    3. Relative momentum: rank remaining assets by return, select top quantile
    4. Portfolio signal: equal-weight selected assets (long-only), signal = n_selected / n_assets
    """

    def generate_signals(self, data: pd.DataFrame | dict) -> pd.Series:
        lookback = self.parameters.get("lookback", 12 * 21)  # ~12 months
        top_quantile = self.parameters.get("top_quantile", 0.2)
        risk_free_rate = self.parameters.get("risk_free_rate", 0.0)  # Annualized

        # Convert annualized risk-free rate to period rate
        rf_period = (1 + risk_free_rate) ** (lookback / 252) - 1

        # Detect multi-asset panel data
        if isinstance(data, dict):
            return self._generate_multi_asset_signals_dict(data, lookback, top_quantile, rf_period)
        elif isinstance(data.columns, pd.MultiIndex):
            return self._generate_multi_asset_signals_multiindex(data, lookback, top_quantile, rf_period)
        else:
            # Single-asset fallback (backward compatible)
            import warnings
            warnings.warn(
                "DualMomentumStrategy used with single-asset data; "
                "falling back to absolute momentum only (asset vs cash). "
                "For true dual momentum with relative momentum, provide panel data "
                "(MultiIndex columns or dict of DataFrames).",
                UserWarning,
                stacklevel=2,
            )
            return self._generate_single_asset_signals(data, lookback, rf_period)

    def _generate_multi_asset_signals_dict(
        self,
        data_dict: dict,
        lookback: int,
        top_quantile: float,
        rf_period: float,
    ) -> pd.Series:
        """Generate signals from dict of symbol -> DataFrame."""
        if not data_dict:
            return pd.Series(dtype=float)

        # Align all symbols to common date index
        common_index = None
        for df in data_dict.values():
            if common_index is None:
                common_index = df.index
            else:
                common_index = common_index.intersection(df.index)

        if common_index is None or len(common_index) == 0:
            return pd.Series(dtype=float)

        common_index = common_index.sort_values()

        # Compute lookback returns for each symbol
        returns_dict = {}
        for symbol, df in data_dict.items():
            df_aligned = df.reindex(common_index)
            close = df_aligned["close"]
            returns_dict[symbol] = close.pct_change(lookback)

        returns_df = pd.DataFrame(returns_dict, index=common_index)

        # Dual momentum logic per period
        signals = pd.Series(0.0, index=common_index, dtype=float)

        for date in common_index[lookback:]:
            row = returns_df.loc[date].dropna()
            if len(row) == 0:
                continue

            n_assets = len(row)

            # Absolute momentum: filter assets with return > risk-free rate
            abs_momentum = row[row > rf_period]

            if len(abs_momentum) == 0:
                # No assets with positive absolute momentum -> cash (signal = 0)
                signals.loc[date] = 0.0
                continue

            # Relative momentum: rank assets with positive absolute momentum
            ranked = abs_momentum.rank(ascending=False, method="first")

            # Select top quantile
            n_select = max(1, int(np.ceil(len(abs_momentum) * top_quantile)))
            selected_symbols = ranked[ranked <= n_select].index

            # Portfolio signal: fraction of capital allocated (long-only)
            # Equal weight among selected assets
            signals.loc[date] = len(selected_symbols) / n_assets

        return signals

    def _generate_multi_asset_signals_multiindex(
        self,
        data: pd.DataFrame,
        lookback: int,
        top_quantile: float,
        rf_period: float,
    ) -> pd.Series:
        """Generate signals from DataFrame with MultiIndex columns (field, symbol)."""
        # Expect columns like ('close', 'AAPL'), ('close', 'MSFT'), etc.
        if "close" not in data.columns.get_level_values(0):
            raise ValueError("MultiIndex data must have 'close' as first level column")

        close_data = data["close"]  # DataFrame with symbols as columns
        returns_df = close_data.pct_change(lookback)

        signals = pd.Series(0.0, index=data.index, dtype=float)

        for date in data.index[lookback:]:
            row = returns_df.loc[date].dropna()
            if len(row) == 0:
                continue

            n_assets = len(row)

            # Absolute momentum: filter assets with return > risk-free rate
            abs_momentum = row[row > rf_period]

            if len(abs_momentum) == 0:
                signals.loc[date] = 0.0
                continue

            # Relative momentum: rank assets with positive absolute momentum
            ranked = abs_momentum.rank(ascending=False, method="first")

            # Select top quantile
            n_select = max(1, int(np.ceil(len(abs_momentum) * top_quantile)))
            selected_symbols = ranked[ranked <= n_select].index

            # Portfolio signal: fraction of capital allocated (long-only)
            signals.loc[date] = len(selected_symbols) / n_assets

        return signals

    def _generate_single_asset_signals(
        self,
        data: pd.DataFrame,
        lookback: int,
        rf_period: float,
    ) -> pd.Series:
        """Backward-compatible single-asset absolute momentum only."""
        returns = data["close"].pct_change(lookback)
        signals = pd.Series(0, index=data.index)
        signals[returns > rf_period] = 1
        signals[returns <= rf_period] = 0  # Cash

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
        "cross_sectional_momentum": "Cross-Sectional Momentum (Multi-Asset Panel Data)",
        "dual_momentum": "Dual Momentum (Absolute + Relative, Multi-Asset Panel Data)",
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
        "dual_momentum": {"lookback": 252, "top_quantile": 0.2, "risk_free_rate": 0.0},
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
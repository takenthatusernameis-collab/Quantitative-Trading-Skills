# Strategy Templates

This document describes the pre-built strategy patterns available through
`scripts/strategy_builder.py` and how to customize them.

## Overview

All strategies inherit from `StrategyBase` and implement
`generate_signals(data) -> pd.Series`. The returned series contains integer
values: `1` for long, `0` for flat, `-1` for short.

## Trend Following

### SMA Crossover (`sma_crossover`)

- **Signal**: Long when fast SMA > slow SMA, flat otherwise.
- **Parameters**: `fast_period` (default 20), `slow_period` (default 50).
- **Use case**: Classic trend-following on liquid ETFs or futures.

```python
from scripts.strategy_builder import build_strategy
strategy = build_strategy("sma_crossover", '{"fast_period": 10, "slow_period": 30}')
```

### EMA Crossover (`ema_crossover`)

- **Signal**: Long when fast EMA > slow EMA, flat otherwise.
- **Parameters**: `fast_period` (default 12), `slow_period` (default 26).
- **Use case**: Faster response than SMA; good for volatile markets.

### Donchian Channel Breakout (`donchian_breakout`)

- **Signal**: Long when price breaks above the N-period high; short when it
  breaks below the N-period low. Exit on opposite channel touch.
- **Parameters**: `period` (default 20), `exit_period` (default 10).
- **Use case**: Classic trend-following (original Turtle system).

## Mean Reversion

### Bollinger Bands (`bollinger_bands`)

- **Signal**: Long when close touches the lower band, short when it touches
  the upper band. Exit at the middle band.
- **Parameters**: `period` (default 20), `std_dev` (default 2.0).
- **Use case**: Range-bound markets; equities and FX.

### RSI Mean Reversion (`rsi_mean_reversion`)

- **Signal**: Long when RSI drops below oversold, short when it exceeds
  overbought. Exit at the neutral line.
- **Parameters**: `period` (default 14), `oversold` (default 30),
  `overbought` (default 70), `neutral` (default 50).
- **Use case**: Short-term mean reversion on indices.

### Z-Score Mean Reversion (`zscore_mean_reversion`)

- **Signal**: Long when z-score <= -entry_z, short when z-score >= entry_z.
  Exit when z-score crosses back toward zero.
- **Parameters**: `period` (default 20), `entry_z` (default 2.0),
  `exit_z` (default 0.5).
- **Use case**: Pairs trading and statistical arbitrage overlays.

## Momentum

### Cross-Sectional Momentum (`cross_sectional_momentum`)

- **Signal**: Ranks assets by past return; long top quantile, short bottom
  quantile. For single-asset use, acts as a simple momentum filter.
- **Parameters**: `lookback` (default 252), `top_quantile` (default 0.2),
  `bottom_quantile` (default 0.2).
- **Use case**: Multi-asset portfolios; requires panel data at the portfolio
  layer.

### Dual Momentum (`dual_momentum`)

- **Signal**: Long when absolute momentum (asset return) is positive, flat
  (cash) otherwise. Combines absolute and relative momentum in the full
  implementation.
- **Parameters**: `lookback` (default 252 = 12 months of trading days).
- **Use case**: Asset allocation; Gary Antonacci's dual momentum strategy.

## Position Sizing Overlays

### Volatility Targeting

`VolatilityTargeting` wraps a base strategy and scales positions so that the
annualized realized volatility matches `target_vol` (default 15%). The
multiplier is capped at 2x to avoid excessive leverage.

- **Parameters**: `target_vol` (default 0.15), `lookback` (default 63).

## Strategy Registry

All registered strategies are listed in `STRATEGY_REGISTRY`. To add a new
strategy, subclass `StrategyBase`, implement `generate_signals`, and register
the class in the dictionary.

## Defaults

`get_strategy_defaults(strategy_type)` returns the default parameter set for
each registered strategy.
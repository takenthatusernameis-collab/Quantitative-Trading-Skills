# Transaction Cost Models

This document describes how transaction costs are modeled in the backtesting
framework and how to configure them.

## Cost Components

Every trade incurs three types of cost, applied per unit of position change:

| Component   | Symbol | Default  | Description                                    |
| ----------- | ------ | -------- | ---------------------------------------------- |
| Commission  | `c`    | 2 bps    | Fixed fee per unit of traded notional          |
| Slippage    | `s`    | 1 bps    | Execution price deviation from expected        |
| Market Impact | `m` | 0 bps    | Price movement caused by the trade itself     |

## Implementation

In `scripts/walk_forward.py`, costs are applied as a fraction of notional on
each position change:

```python
position_changes = positions.diff().abs()
costs = position_changes * (commission + slippage)
strategy_returns = positions * raw_returns - costs
```

The cost is subtracted from the period return, so it reduces net performance.

## Configuration

Costs are passed as decimal fractions (not bps) to the backtest entry points:

| CLI Flag       | Type   | Default  | Notes                          |
| -------------- | ------ | -------- | ------------------------------ |
| `--commission` | float  | `0.0002` | 2 bps = 0.0002                 |
| `--slippage`   | float  | `0.0001` | 1 bps = 0.0001                 |

In the walk-forward module, `commission` and `slippage` are keyword arguments
to `walk_forward_analysis` and `parameter_optimization`.

## Choosing Cost Levels

| Asset Class    | Commission (bps) | Slippage (bps) | Notes                                   |
| -------------- | ---------------- | -------------- | --------------------------------------- |
| US Equities    | 1                | 1              | Typical for liquid ETFs and large caps  |
| Futures        | 2-5              | 1-2            | Depends on contract liquidity           |
| Crypto         | 5-20             | 5-50           | Highly variable; model spreads explicitly |
| FX Spot        | 1                | 1              | Often embedded in quoted spreads        |

## Market Impact

Market impact is not modeled by default. For large positions or illiquid
instruments, extend the cost model with:

```python
impact = position_size / average_daily_volume * impact_coefficient
total_cost = commission + slippage + impact
```

This can be added to `_calculate_strategy_returns` as an additional term.

## Effect on Performance

Transaction costs have a disproportionate effect on high-turnover strategies.
Always validate that net returns (after costs) are positive before deploying
capital.
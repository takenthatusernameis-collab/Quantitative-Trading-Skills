# Transaction Cost Models

This document describes how transaction costs are modeled in the backtesting
framework and how to configure them.

## Cost Components

Every trade incurs three types of cost, applied per unit of position change:

| Component       | Symbol | Default  | Description                                          |
| --------------- | ------ | -------- | ---------------------------------------------------- |
| Commission      | `c`    | 2 bps    | Fixed fee per unit of traded notional                |
| Slippage        | `s`    | 1 bps    | Execution price deviation from expected              |
| Market Impact   | `m`    | 0 bps    | Price movement caused by the trade itself           |
| Borrow Cost     | `b`    | 0 bps    | Annual cost to borrow shares for short positions    |
| Funding Cost    | `f`    | 0 bps    | Annual cost to fund leveraged positions beyond 1x   |

## Implementation

In `scripts/walk_forward.py` and `scripts/run_backtest.py`, costs are applied as a fraction of notional on
each position change:

```python
position_changes = positions.diff().abs()
costs = position_changes * (commission + slippage)

# Market impact model (optional)
if impact_coefficient > 0:
    adv_shares = volume.rolling(window=adv_window, min_periods=1).mean()
    adv_notional = adv_shares * close
    position_notional = position_changes * close
    market_impact = (position_notional / adv_notional) * impact_coefficient
    costs = costs + market_impact.fillna(0)

# Borrow cost for short positions (optional)
if borrow_cost > 0:
    daily_borrow_rate = borrow_cost / 252
    short_positions = positions.clip(upper=0).abs()
    borrow_costs = short_positions * daily_borrow_rate
    costs = costs + borrow_costs

# Funding cost for leveraged positions (optional)
if funding_cost > 0:
    daily_funding_rate = funding_cost / 252
    gross_exposure = positions.abs()
    leverage_excess = (gross_exposure - 1).clip(lower=0)
    funding_costs = leverage_excess * daily_funding_rate
    costs = costs + funding_costs

strategy_returns = positions * raw_returns - costs
```

The cost is subtracted from the period return, so it reduces net performance.

### Market Impact Model

Market impact models the price movement caused by the trade itself. The model
implemented is a simple linear impact model:

```
market_impact = (position_notional / ADV) * impact_coefficient
```

Where:
- `position_notional` = `|position_change| * close_price` (notional value traded)
- `ADV` = Average Daily Volume in notional = `rolling_mean(volume, adv_window) * close_price`
- `impact_coefficient` = linear impact coefficient (typically 0.1-1.0)
- `adv_window` = rolling window for ADV calculation (default 20 days)

This model assumes:
1. Impact is linear in participation rate (position size / ADV)
2. The coefficient captures the price elasticity of the order book
3. Volume is averaged over `adv_window` periods to smooth noise

For more sophisticated models, consider:
- Square-root impact: `impact = coefficient * sqrt(position_notional / ADV)`
- Permanent vs. temporary impact decomposition
- Order book depth-based models
- Time-varying impact coefficients by regime

### Borrow Cost Model

Borrow cost models the fee paid to borrow shares for short selling. It is applied
daily on the absolute value of short positions:

```
daily_borrow_rate = annual_borrow_cost / 252
borrow_cost_daily = |short_position| * daily_borrow_rate
```

Where:
- `annual_borrow_cost` = annual borrow rate as a decimal (e.g., 0.03 = 3% per year)
- `short_position` = negative position values (short exposure)
- 252 = trading days per year (standard annualization)

This model assumes:
1. Borrow cost is proportional to short exposure
2. The rate is constant (in practice, borrow rates vary by security and over time)
3. Cost is incurred daily while the short position is held

Typical borrow costs:
- **General collateral (easy-to-borrow)**: 0.1% - 0.5% per year
- **Hard-to-borrow**: 1% - 20%+ per year
- **Special situations**: Can exceed 50% per year

### Funding Cost Model

Funding cost models the cost of financing leveraged positions. It is applied daily
on the amount of gross exposure exceeding 100% of equity (i.e., leverage > 1x):

```
daily_funding_rate = annual_funding_cost / 252
leverage_excess = max(|position| - 1, 0)
funding_cost_daily = leverage_excess * daily_funding_rate
```

Where:
- `annual_funding_cost` = annual funding rate as a decimal (e.g., 0.02 = 2% per year)
- `position` = current position size (1.0 = fully invested long, -1.0 = fully short)
- Leverage excess only applies when gross exposure > 1

This model assumes:
1. Funding cost is proportional to leverage used beyond 1x
2. The rate represents the cost of margin borrowing or financing
3. Long and short positions both contribute to gross leverage

Typical funding costs:
- **Prime brokerage margin rates**: Fed Funds + 0.5% to 2.5%
- **Retail margin rates**: 5% - 10%+ per year
- **Futures implied financing**: Embedded in basis; typically near risk-free rate

## Configuration

Costs are passed as decimal fractions (not bps) to the backtest entry points:

| CLI Flag            | Type   | Default  | Notes                                              |
| ------------------- | ------ | -------- | -------------------------------------------------- |
| `--commission`      | float  | `0.0002` | 2 bps = 0.0002                                     |
| `--slippage`        | float  | `0.0001` | 1 bps = 0.0001                                     |
| `--impact-coefficient` | float | `0.0`  | Linear impact coefficient (0 to disable)           |
| `--adv-window`      | int    | `20`     | Rolling window for ADV calculation                 |
| `--borrow-cost`     | float  | `0.0`    | Annual borrow rate for shorts (e.g., 0.03 = 3%)   |
| `--funding-cost`    | float  | `0.0`    | Annual funding rate for leverage (e.g., 0.02 = 2%) |

In the walk-forward module, `commission`, `slippage`, `impact_coefficient`,
`adv_window`, `borrow_cost`, and `funding_cost` are keyword arguments to
`walk_forward_analysis`, `parameter_optimization`, and `cpcv_analysis`.

## Choosing Cost Levels

| Asset Class    | Commission (bps) | Slippage (bps) | Impact Coeff. | Borrow Cost (annual) | Funding Cost (annual) | Notes                                   |
| -------------- | ---------------- | -------------- | ------------- | -------------------- | --------------------- | --------------------------------------- |
| US Equities    | 1                | 1              | 0.1-0.5       | 0.1%-0.5% (GC)       | 1%-3% (margin)        | GC = general collateral; HTB = hard-to-borrow |
|                |                  |                |               | 1%-20%+ (HTB)        |                       |                                         |
| Futures        | 2-5              | 1-2            | 0.2-1.0       | N/A (no borrow)      | ~Risk-free            | Implied financing in basis              |
| Crypto         | 5-20             | 5-50           | 0.5-2.0       | 5%-50%+              | 5%-20%                | Highly variable; model spreads explicitly |
| FX Spot        | 1                | 1              | 0.1-0.3       | N/A                  | ~Risk-free            | Often embedded in quoted spreads        |

## Effect on Performance

Transaction costs have a disproportionate effect on high-turnover strategies.
Always validate that net returns (after costs) are positive before deploying
capital.

Market impact particularly penalizes:
- Large position sizes relative to ADV
- High-turnover strategies
- Illiquid instruments (low ADV)

Borrow costs particularly penalize:
- Strategies with persistent short exposure
- Short-biased strategies
- Hard-to-borrow securities (high borrow rates)

Funding costs particularly penalize:
- Leveraged strategies (gross exposure > 1x)
- Market-neutral strategies with matched long/short books
- High-turnover strategies that briefly exceed 1x leverage

When market impact, borrow costs, and funding costs are enabled, the effective
cost structure creates natural capacity constraints that should be considered
in strategy design and position sizing.
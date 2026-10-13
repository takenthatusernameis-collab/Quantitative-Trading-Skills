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

 ## Configuration

 Costs are passed as decimal fractions (not bps) to the backtest entry points:

 | CLI Flag           | Type   | Default  | Notes                                  |
 | ------------------ | ------ | -------- | -------------------------------------- |
 | `--commission`     | float  | `0.0002` | 2 bps = 0.0002                         |
 | `--slippage`       | float  | `0.0001` | 1 bps = 0.0001                         |
 | `--impact-coefficient` | float | `0.0`  | Linear impact coefficient (0 to disable) |
 | `--adv-window`     | int    | `20`     | Rolling window for ADV calculation     |

 In the walk-forward module, `commission`, `slippage`, `impact_coefficient`,
 and `adv_window` are keyword arguments to `walk_forward_analysis`,
 `parameter_optimization`, and `cpcv_analysis`.

 ## Choosing Cost Levels

 | Asset Class    | Commission (bps) | Slippage (bps) | Impact Coefficient | Notes                                   |
 | -------------- | ---------------- | -------------- | ------------------ | --------------------------------------- |
 | US Equities    | 1                | 1              | 0.1-0.5            | Typical for liquid ETFs and large caps  |
 | Futures        | 2-5              | 1-2            | 0.2-1.0            | Depends on contract liquidity           |
 | Crypto         | 5-20             | 5-50           | 0.5-2.0            | Highly variable; model spreads explicitly |
 | FX Spot        | 1                | 1              | 0.1-0.3            | Often embedded in quoted spreads        |

 ## Effect on Performance

 Transaction costs have a disproportionate effect on high-turnover strategies.
 Always validate that net returns (after costs) are positive before deploying
 capital.

 Market impact particularly penalizes:
 - Large position sizes relative to ADV
 - High-turnover strategies
 - Illiquid instruments (low ADV)

 When market impact is enabled, the effective cost per trade increases with
 position size, creating a natural capacity constraint that should be considered
 in strategy design and position sizing.
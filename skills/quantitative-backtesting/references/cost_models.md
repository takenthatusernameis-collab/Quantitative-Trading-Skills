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

# Borrow and funding costs are annualized rates applied per
# period. The per-period rate divides by the periods per year
# inferred from the data's index (see _annualization_factor),
# so the model is data-frequency aware: business-daily data
# uses 252, calendar-daily 365, weekly 52, monthly 12. When
# the frequency cannot be inferred (or the index is not a
# DatetimeIndex), it falls back to 252.
periods_per_year = _annualization_factor(returns.index)

# Borrow cost for short positions (optional)
if borrow_cost > 0:
    period_borrow_rate = borrow_cost / periods_per_year
    short_positions = positions.clip(upper=0).abs()
    borrow_costs = short_positions * period_borrow_rate
    costs = costs + borrow_costs

# Funding cost for leveraged positions (optional)
if funding_cost > 0:
    period_funding_rate = funding_cost / periods_per_year
    gross_exposure = positions.abs()
    leverage_excess = (gross_exposure - 1).clip(lower=0)
    funding_costs = leverage_excess * period_funding_rate
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

#### Multi-asset panels

For a panel (MultiIndex columns or a dict of per-asset frames) the portfolio is
an **equal-weighted basket**, which is the same convention the panel *return*
model uses (`raw_returns = mean_i(per-asset return)`, i.e. the portfolio's
gross exposure is spread equally over the `n` assets). A position change of
`|d|` therefore trades `|d| * equity / n` in each asset, and each asset's
impact is measured against **its own** ADV:

```
per_asset_notional = |position_change| * equity / n_assets
impact_i           = (per_asset_notional_i / ADV_notional_i) * impact_coefficient
market_impact      = mean_i(impact_i)          # equal-weighted portfolio cost
```

This is the same weighting the panel return model uses, so the impact cost and
the portfolio return are on one consistent footing, and the dict and MultiIndex
panel formats produce identical results.

**Regression history.** The previous implementation divided the *whole*
portfolio notional by a per-asset ADV frame. That turned the cost series into
a DataFrame, produced an **empty** return series for MultiIndex panels, and
silently dropped every parameter configuration in the grid search — a panel
run with market impact enabled reported "no signal" (0 of N folds selected,
empty out-of-sample returns) instead of modelling impact. It was also
inconsistent with the dict-panel path, which charged the total portfolio
notional against a single-asset proxy ADV (overstating the cost by roughly
`n_assets`). Both are covered by regression tests
(`test_calculate_strategy_returns_panel_with_impact_is_not_empty`,
`..._panel_impact_degrades_returns_monotonically`,
`..._dict_and_multiindex_panels_match_with_impact`).

`run_backtest.py` had its own variant of the same defect: it charged the
whole portfolio notional against an aggregated pseudo-asset ADV (mean close x
mean volume across the panel), overstating the impact of a panel by roughly
`n_assets`. It now uses the same per-asset model
(`test_run_backtest_panel_impact_splits_notional_across_assets`).

**Known limitation.** The panel strategy API exposes a *net* exposure
(`(n_long - n_short) / n_assets`), not the per-asset weights of the book, so
the impact cost is computed on an equal-weight book that the actual long/short
composition does not match. A strategy whose gross exposure exceeds
`|net exposure|` therefore has a modelled impact cost that is, if anything,
too low. Treat panel capacity and impact numbers as order-of-magnitude
estimates and verify them against a portfolio with explicit per-asset weights
before sizing capital.

The trade ledger of `run_backtest.py` has the same limitation: for a panel it
prices entries and exits on the **mean price** of the constituents, because
the panel strategy API does not expose per-asset entries. The ledger's
per-trade P&L is therefore an approximation and does not reconcile exactly
with the panel equity curve (which is marked on the equal-weighted basket).

### Cross-path parity

`run_backtest.py` (single backtest) and `walk_forward.py` (walk-forward, CPCV
and out-of-sample validation) now price a panel with **one** convention. The
shared definitions live in `scripts/utils.py`:

| Model | Shared function | Convention |
| --- | --- | --- |
| Market returns | `build_market_model` | panel return = mean of the per-asset returns (`close.pct_change().mean(axis=1)`) |
| Market impact | `market_impact_cost` | per-asset notional `|d| * equity / n_assets` against each asset's own ADV; portfolio cost = equal-weighted mean |
| Capacity | `estimate_capacity` | equal-weighted basket; the least liquid constituent binds the portfolio capacity |

The mean-of-returns convention is used instead of the return of the mean price
series (`close.mean(axis=1).pct_change()`) because the latter prices a
price-weighted basket whose weights drift with the constituents' relative
moves — a rebalancing rule the position model does not represent — while the
former is the equal-weighted basket the impact and capacity models assume.

Consequence: for the same panel, strategy and cost assumptions, the two paths
produce **identical return values on every bar where both are defined**
(`test_run_backtest_panel_matches_walk_forward_return_calculator`,
`test_run_backtest_dict_panel_matches_walk_forward_return_calculator`).

**One remaining difference: the position warmup.** It is a *position*
convention, not a market-model convention, and it applies to single assets
too:

- `run_backtest.py` fills the undefined first position with `0`, so the
  position is opened on the first executable bar and the **entry cost is
  charged** there.
- `walk_forward.py` propagates the undefined position as `NaN`, so the first
  bar of the window is **dropped** from the evaluation (and the entry cost is
  never charged).

`run_backtest.py` therefore reports exactly one extra leading bar (the
initial-entry bar). This was left unchanged on purpose: changing it would
alter the single-asset path and every published walk-forward / CPCV /
out-of-sample number.

### Borrow Cost Model

Borrow cost models the fee paid to borrow shares for short selling. It is
applied each period on the absolute value of short positions, with the
annual rate converted to a per-period rate using the data's inferred
frequency:

```
periods_per_year = _annualization_factor(index)   # 252 business-daily, 365 daily, 52 weekly, 12 monthly
period_borrow_rate = annual_borrow_cost / periods_per_year
borrow_cost_per_period = |short_position| * period_borrow_rate
```

Where:
- `annual_borrow_cost` = annual borrow rate as a decimal (e.g., 0.03 = 3% per year)
- `short_position` = negative position values (short exposure)
- `periods_per_year` = inferred from the data's DatetimeIndex (252 fallback)

This model assumes:
1. Borrow cost is proportional to short exposure
2. The rate is constant (in practice, borrow rates vary by security and over time)
3. Cost is incurred each period while the short position is held

Because the per-period rate scales with the data frequency, the same annual
borrow rate produces the same annualized cost regardless of whether the
backtest runs on daily, weekly, or monthly bars. Using a fixed 252 divisor
on lower-frequency data would understate the cost per period (e.g., a weekly
bar would accrue only 1/252 of a year's borrow cost instead of 1/52).

Typical borrow costs:
- **General collateral (easy-to-borrow)**: 0.1% - 0.5% per year
- **Hard-to-borrow**: 1% - 20%+ per year
- **Special situations**: Can exceed 50% per year

### Funding Cost Model

Funding cost models the cost of financing leveraged positions. It is applied
each period on the amount of gross exposure exceeding 100% of equity
(i.e., leverage > 1x), with the annual rate converted to a per-period rate
using the data's inferred frequency:

```
periods_per_year = _annualization_factor(index)
period_funding_rate = annual_funding_cost / periods_per_year
leverage_excess = max(|position| - 1, 0)
funding_cost_per_period = leverage_excess * period_funding_rate
```

Where:
- `annual_funding_cost` = annual funding rate as a decimal (e.g., 0.02 = 2% per year)
- `position` = current position size (1.0 = fully invested long, -1.0 = fully short)
- Leverage excess only applies when gross exposure > 1
- `periods_per_year` = inferred from the data's DatetimeIndex (252 fallback)

This model assumes:
1. Funding cost is proportional to leverage used beyond 1x
2. The rate represents the cost of margin borrowing or financing
3. Long and short positions both contribute to gross leverage
4. The rate is constant per period (in practice, financing rates vary over time)

As with borrow costs, frequency awareness keeps the annualized cost
consistent across data frequencies.

Typical funding costs:
- **Prime brokerage margin rates**: Fed Funds + 0.5% to 2.5%
- **Retail margin rates**: 5% - 10%+ per year
- **Futures implied financing**: Embedded in basis; typically near risk-free rate

### Fill Rate Model

The fill rate models partial execution: only a fraction of each targeted
position change is filled, so the achieved position is `fill_rate` times the
targeted position. Because position changes are scaled, all transaction
costs scale with the filled notional:

```
fill_rate = 0.5  # only 50% of each order is filled
positions = signals.shift(1 + latency).fillna(0) * fill_rate
position_changes = positions.diff().abs()
costs = position_changes * (commission + slippage)
# market impact, borrow cost, and funding cost all scale through `positions`
```

Since the achieved position is scaled, market exposure (position returns)
scales by the same factor: partial fills reduce both expected returns and
trading costs. The default fill rate is 1.0 (full fill), which is backward
compatible with all existing cost models.

Constraints:
- `fill_rate` must be in (0, 1]; values outside this range are rejected.
- `fill_rate = 1.0` reproduces the unmodified execution model exactly.

## Strategy Capacity Estimation

When market impact is enabled, each analysis path (`walk_forward_analysis`,
`cpcv_analysis`, `out_of_sample_validation`) also reports a **strategy
capacity** estimate in its `summary["capacity"]` key. The estimate is
computed by `estimate_capacity` in `walk_forward.py` by inverting the
linear impact model:

```
impact = (notional / ADV_notional) * impact_coefficient
=> capacity_notional = max_impact * ADV_notional / impact_coefficient
```

`max_impact` defaults to 0.0005 (5 bps of notional traded per round trip).
The capacity is the maximum notional a full-rebalance strategy can hold
without exceeding that impact threshold. It is `None` when impact is
disabled (`impact_coefficient <= 0`) or when ADV cannot be computed
(missing `close`/`volume`, empty data, or non-positive ADV), so the key is
backward compatible: consumers may omit it when absent.

### Capacity per regime (fold / period / window)

The aggregate `summary["capacity"]` is computed on the whole sample, so it
hides capacity decay inside the sample. Every analysis path therefore also
reports the capacity of each regime it evaluates:

| Path                     | Key                                                        |
| ------------------------ | ---------------------------------------------------------- |
| `walk_forward_analysis`  | `periods[i]["capacity"]` (each out-of-sample test window)  |
| `cpcv_analysis`          | `folds[i]["capacity"]` (each fold's test window)           |
| `out_of_sample_validation` | `validation_performance["capacity"]` (validation window) and `test_performance["capacity"]` (held-out test window) |

The out-of-sample summary also exposes them as `summary["validation_capacity"]`
and `summary["test_capacity"]`. The CLI artifacts persist them as
`capacity_per_period` (walk-forward) and `capacity_per_fold` (CPCV), and the
tear sheet renders a "Capacity (Notional)" column in the per-period and
per-fold tables. Capacity is `None` (never a stale or zero value) when impact
is disabled or ADV is not estimable, so a regime with no estimate is
distinguishable from a regime with a small one.

Note the estimator uses the **latest** ADV in each window, so a per-regime
value is a point-in-time liquidity reading, not a trend; a capacity
*degradation trend* across regimes is not yet derived.

### Multi-asset panels

For a panel (MultiIndex columns) the basket is treated as equal-weighted: each
of the `n_assets` constituents carries `1 / n_assets` of the portfolio
notional, so the *least liquid* constituent sets the portfolio capacity:

```
capacity = n_assets * max_impact * min_i(ADV_notional_i) / impact_coefficient
```

This is the binding constraint — a basket can only grow until its least
liquid member exceeds the impact threshold. The returned dict reports the
binding member's `price` / `adv_shares` / `adv_notional`, plus `n_assets` and
`binding_asset` so the driver of the estimate is auditable. For a single
asset, `n_assets` is 1 and the formula reduces to the single-asset case.

### Reporting

The tear sheet renders the aggregate capacity as a "Strategy Capacity
(Notional)" row in the Walk-Forward / CPCV analysis tables and surfaces it in
`tear_sheet_summary.json` under the corresponding analysis summary.

The single-backtest path (`run_backtest.py`) reports the same estimate as
`results["capacity"]` (mirrored into `metrics["capacity"]`), so capacity is
part of every reported backtest result, not just multi-period validation.
Volume is optional on this path: when the data has no `volume` column (or
ADV is otherwise not estimable), `capacity` is `None` and the run proceeds
without raising. For a panel the estimate uses the same equal-weighted basket
rule as the walk-forward paths (the least liquid constituent binds), so the
two CLIs report the same capacity for the same panel
(`test_run_backtest_panel_capacity_binds_on_least_liquid_constituent`).

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
| `--fill-rate`       | float  | `1.0`    | Fraction of each position change filled (0 < r <= 1) |
| `--fill-rates`      | list   | None     | List of fill rates to sweep (overrides --fill-rate) |

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

## Benchmark Expense Ratio

In addition to transaction costs, the benchmark (buy-and-hold) can be modeled with an annual expense ratio, simulating the cost of holding a benchmark ETF or index fund.

The expense ratio is deducted each period from the benchmark's return, reducing the net benchmark return.

Configuration is done via the `--benchmark-expense-ratio` flag (as decimal, e.g., 0.005 for 0.5%).

## Benchmark Split Adjustment

Split adjustment for benchmark returns is **orthogonal to transaction cost
models**. When benchmark data contains a `splits` column, split adjustment is
applied to the benchmark series in all benchmark-comparison paths
(single-benchmark, summary aggregation, and multiple-benchmark alpha
correction), regardless of whether `benchmark_cost_is_periodic` is `True` or
`False`.

The `benchmark_cost_is_periodic` flag only controls the timing of benchmark
transaction costs (once per round-trip vs. charged each period). It does not
gate split adjustment, which is applied when corporate actions are present to
avoid injecting artificial price drops into benchmark returns.

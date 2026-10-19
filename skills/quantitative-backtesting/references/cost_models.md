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
before sizing capital. The **panel book diagnostic** below measures exactly
this gap (gross book vs net exposure, book turnover vs charged turnover), so
the size of the approximation is now visible instead of implied.

The trade ledger of `run_backtest.py` has the same limitation: for a panel it
prices entries and exits on the **mean price** of the constituents, because
the panel strategy API does not expose per-asset entries. The ledger's
per-trade P&L is therefore an approximation and does not reconcile exactly
with the panel equity curve (which is marked on the equal-weighted basket).

### Panel book diagnostic (measurement only)

The panel path prices a portfolio as **net exposure x mean asset return**:
one scalar per period (`positions[t] * mean_i(r_i[t])`). A strategy that
holds an explicit long/short book cannot be represented by that scalar, so
the engine now *measures* the gap instead of hiding it. The measurement is
read-only: no return, cost, impact or capacity number changes.

A strategy can describe its book with the optional accessor
`StrategyBase.generate_target_weights(data)`:

- returns a `DataFrame` of portfolio weights (rows = dates, columns =
  symbols) whose net exposure matches the scalar signal of
  `generate_signals`, or
- returns `None` (the default) when the strategy does not model a book.
  Single-asset runs and every strategy that does not implement the accessor
  are therefore unchanged.

`CrossSectionalMomentum` implements it with `+1 / n_assets` per long name
and `-1 / n_assets` per short name, so the book's net exposure is exactly
the scalar signal `(n_long - n_short) / n_assets` and the gross book is
`(n_long + n_short) / n_assets`. `DualMomentumStrategy` implements it with
`1 / n_selected` per selected name (a fully invested long-only book).

`utils.compute_book_diagnostic` then reports, per window:

| Key | Meaning |
| --- | --- |
| `gross_book` | mean `sum_i abs(w_i)` per period: the exposure the strategy actually carries |
| `net_exposure` | mean `sum_i w_i`: the book's net exposure |
| `framework_net_exposure` | mean net exposure the engine priced (the scalar signal) |
| `gross_turnover` | mean `sum_i abs(dw_i)`: the turnover the book really has |
| `framework_turnover` | mean `abs(d net exposure)`: the turnover the net-exposure cost model charges |
| `charged_turnover` | the turnover the cost model actually charged: the gross turnover under the `book` cost basis, the net exposure's under `net-exposure` |
| `cost_basis` | the basis the costs were charged on (`"book"` or `"net-exposure"`) |
| `n_periods_with_book` | periods in which the book is not flat |
| `return_gap_bps` | mean per-period gap between the engine's pre-cost return and the book return `sum_i w_i r_i` |
| `return_gap_total` | cumulative gap (engine pre-cost total minus book total) |
| `book_total_return` | cumulative return of the book |
| `framework_total_return` | cumulative return the engine priced, before costs |
| `framework_total_return_after_costs` | cumulative return the engine reported |

The diagnostic also carries the **market-impact participation measurement**
(`impact_*` keys): the impact the run charged next to the impact the names
that traded would have paid, and the difference between them. See "Market-impact
participation (measurement only)" below.

The diagnostic is surfaced by `run_backtest.py` (`results["book_diagnostic"]`,
`metrics["book_diagnostic"]`), by the walk-forward, CPCV and out-of-sample
paths (`summary["book_diagnostic"]`, plus the per-period / per-fold and
per-split records), in the CLI stdout, in the summary JSON artifacts and in
the tear sheet ("Panel Book Diagnostic"). It is `None` for single-asset runs
and for strategies that do not expose a book.

**What the diagnostic shows.** The gap is not hypothetical. With symmetric
quantiles the cross-sectional momentum signal is flat by construction, so
the engine reports "no position" while the strategy holds a market-neutral
book: `gross_book > 0`, `net_exposure == 0` and `framework_turnover == 0`
(a full book rotation charged no impact at all). With asymmetric quantiles
the net exposure is priced correctly, but the *dispersion* the long/short
composition earns is discarded, and the book still rotates several times
more than the turnover the model charges.

**Known limitation (unchanged by the diagnostic).** Under the default
`net-exposure` convention the engine still prices the panel with the scalar
net exposure, and the impact/capacity models still assume an equal-weight
book. The diagnostic measures the size of that approximation; it does not
correct it. Use `--panel-pricing book` to price *and cost* the book itself
(see "Panel pricing modes" below); the diagnostic is reported under both modes
(in `book` mode it shows how much the net-exposure convention would have
missed).

### Panel pricing modes (`--panel-pricing`)

The diagnostic above measures a gap that the engine used to hide. The engine
can now *price* the book instead, behind an explicit opt-in switch:

| Mode | Portfolio return per period | Default |
| --- | --- | --- |
| `net-exposure` | `net_exposure[t] x mean_i(r_i[t])` (the scalar signal) | **yes** |
| `book` | `sum_i w_i[t] r_i[t]` -- the true per-asset book return | no |

```
run_backtest.py --data panel.csv --multi-symbol --panel-pricing book ...
walk_forward.py cpcv --data panel.csv --multi-symbol --panel-pricing book ...
```

The mode is available on `run_backtest.py` and on every `walk_forward.py`
sub-command (`walk-forward`, `optimize`, `cpcv`, `out-of-sample`). The
default is `net-exposure`, so **every number published before this change is
unchanged**; the `net-exposure` mode is bit-identical to the previous code
(verified key by key against `HEAD` on a 5-asset panel across the walk-forward,
CPCV, out-of-sample and single-backtest paths).

**What changes in `book` mode.**

1. *The portfolio return is the book's.* The return series is
   `sum_i w_i r_i` of the held book (the target weights lagged by `1 +
   latency` periods and scaled by the fill rate), not the scalar net exposure
   times the basket return. The two modes therefore differ by exactly the
   `return_gap` the diagnostic measures (with zero costs; see below).
2. *The "does this strategy take a position?" test becomes book-aware.* A
   market-neutral book has a flat net exposure but a positive **gross**
   exposure, so it *is* a position. Under `net-exposure` the symmetric-quantile
   cross-sectional momentum is rejected ("never takes a position") and the
   walk-forward / CPCV grid search skips every parameter combination. Under
   `book` the same strategy is backtested and its parameters are selected.
3. *The costs are charged on the book.* See "The book cost basis" below: the
   transaction, borrow, funding and impact costs of a book are charged on the
   book itself, not on the scalar net exposure.
4. *The trade ledger is built from the book.* One round trip per asset and
   direction, priced at that asset's own close, so the trade-level statistics
   (win rate, profit factor, expectancy) exist for a market-neutral book.
5. *The reported mode is recorded.* `results["panel_pricing"]` (and
   `results["config"]["panel_pricing"]` / `["panel_pricing_effective"]`),
   `summary["panel_pricing"]` on the walk-forward / CPCV / out-of-sample
   paths, the CLI stdout, the summary JSON artifacts and the tear sheet
   ("Panel Pricing") all carry the convention that produced the number. A
   panel return is not interpretable without it: the sign of the gap between
   the two conventions is not even stable across windows.

#### The book cost basis

Under `net-exposure` the engine can only see one scalar per period, so every
cost is charged on it:

| Cost | `net-exposure` basis | `book` basis |
| --- | --- | --- |
| commission + slippage | `abs(d net exposure)` | gross turnover `sum_i abs(dw_i)` |
| borrow | `abs(min(net exposure, 0))` | short legs `sum_i max(-w_i, 0)` |
| funding | `max(abs(net exposure) - 1, 0)` | `max(sum_i abs(w_i) - 1, 0)` (gross exposure) |
| market impact | `abs(d net exposure) x equity / n_assets` per asset | `abs(dw_i) x equity` per asset |
| trade ledger | the scalar position series, priced on the panel's mean close | the book, priced at each asset's own close |

Every term is charged on the **book** in `book` mode, and the fill rate is
inside the held book, so every term scales with the fill rate exactly like the
net-exposure model.

The impact model is the same linear, per-asset model
(`impact_i = traded_notional_i / ADV_notional_i x impact_coefficient`, with
`ADV_notional_i = rolling_mean(volume_i) x close_i`), applied to the notional
each asset actually trades (`abs(dw_i) x equity`) against **that asset's own
ADV**. The portfolio cost stays the equal-weighted mean of the per-asset
impacts, the same panel convention the net-exposure path uses, so the two
modes stay on the same scale.

**Why this matters.** A book rotates much more than its net exposure does
(measured on a 5-asset panel: gross turnover 0.163 against a charged turnover
of 0.0002, i.e. a ~900x under-charge), and a market-neutral book has a zero
net exposure, so under the net-exposure basis its rotation was charged
**nothing at all**, it paid **no borrow cost** and its funding cost was
computed on the net exposure rather than the gross book. `book` mode results
were therefore an **upper bound** on what a fully costed book would earn.
They are now costed, and they are materially lower: on a 900-bar 5-asset
market-neutral cross-sectional book the total return moves from **+16.3%**
(uncosted book) to **-15.7%** (costed book) -- a 32 percentage-point
difference, of which ~30 points are the transaction, borrow and impact costs
the book actually pays. A book-mode number must therefore be read as a
*costed* number, and a net-exposure number as a *net-exposure-convention*
number; the two are not comparable without the mode.

#### Residual approximations in `book` mode

The book cost basis is not a complete cost model. What is left:

- **Impact is the mean over the whole panel.** A period in which only `k` of
  `n` names trade is charged the mean over `n` names, so the drag is diluted
  relative to the participation actually consumed. The convention is kept
  identical to the net-exposure path (where every constituent always trades
  `1 / n` of the notional) so the two modes stay comparable; a *sum* over the
  traded names would be the conservative alternative. **The size of this
  approximation is now measured** -- see "Market-impact participation
  (measurement only)" below, which reports the impact the traded names would
  have paid next to the impact the run charged, and the decision the
  measurement supports.
- **The trade ledger does not reconcile with the equity curve.** The `pnl`
  field of a book trade is in price units scaled by the average weight, and
  the `return` field is that P&L divided by the entry price (the leg's
  contribution to the portfolio return). The ledger ignores compounding and
  transaction costs, and it approximates a leg whose weight changed during the
  trade by its average weight.
- **The impact model is linear in the participation rate** and does not model
  a temporary permanent price impact, an overnight gap risk, or a market
  that moves against the trade. It is a sizing guard, not a fill model.

The *capacity* is no longer one of the residuals: in `book` mode the engine
reports the book-based capacity next to the basket-based one (see
"Two capacity estimates" below).

**Fallbacks.** A strategy that exposes no book (no
`generate_target_weights`, or a single-asset run) cannot be priced as a
book: the run falls back to the `net-exposure` convention and records
`panel_pricing_effective = "net-exposure"`, so the fallback is visible in the
artifacts rather than silent.

### Market-impact participation (measurement only)

The panel impact model charges the **equal-weighted mean over all `n` panel
names** of the per-asset impacts. A name that did not trade has an impact of
zero, so a period in which only `k` of `n` names trade is charged `1 / n` of
the participation its traded names consumed. That approximation used to be
flagged in prose only; it is now *measured* and reported next to the impact
the run charged, under both pricing modes.

`utils.impact_participation_dilution` computes three aggregations of the
same per-asset impact model (`impact_i = |dw_i| * equity / ADV_i *
impact_coefficient`):

| Aggregation | Definition | What it answers |
| --- | --- | --- |
| `panel` | the equal-weighted mean over all `n` names (the convention the engine charges in `book` mode) | what the model charges |
| `traded_only` | the equal-weighted mean over the `k` names that actually traded | what the participation the traded names consumed was worth |
| `notional_weighted` | `sum_i rate_i * notional_i / equity`: the impact *rate* of each name applied to the notional traded in that name | what the trades cost in dollars (the dollar-consistent aggregation of a linear impact model) |

Two exact identities make the measurement auditable (both asserted by the
test suite):

- `panel == (k / n) * traded_only` -- the dilution factor is exactly the
  fraction of names that traded;
- `notional_weighted == f * traded_only` when the traded names trade equal
  notionals, where `f` is the traded notional as a fraction of the equity.
  In general it is `f` times the *notional-weighted* mean rate.

The diagnostic reports the scalars (all `None` when impact is disabled):

| Key | Meaning |
| --- | --- |
| `impact_charged_bps` | the impact the run charged, per period, in bps (the panel mean in `book` mode, the net-exposure model in `net-exposure` mode) |
| `impact_traded_only_bps` | the impact the names that traded would have paid, per period, in bps |
| `impact_notional_weighted_bps` | the dollar-consistent aggregation, per period, in bps |
| `impact_dilution_bps` | `charged - traded_only`: the understatement the run carries (negative = the model charges less) |
| `impact_panel_dilution_bps` | the panel-convention dilution on the book's own trades (`panel - traded_only`); equal to `impact_dilution_bps` in `book` mode |
| `impact_gross_book_return_bps` | the mean per-period gross (pre-cost) book return, in bps: the denominator of the ratio below |
| `impact_dilution_fraction_of_gross_return` | `impact_dilution_bps / impact_gross_book_return_bps` (`None` when the book did not earn a positive gross return, where the ratio would be a sign-flipping artifact) |
| `impact_participation_ratio` | the mean fraction of the panel's names that traded per period (over the periods in which the book traded) |

They are surfaced in the panel book diagnostic (`results["book_diagnostic"]`,
`period["book_diagnostic"]`, `fold["book_diagnostic"]`,
`summary["book_diagnostic"]`, the out-of-sample per-split keys), in the CLI
stdout of both entry points, and in the tear sheet ("Panel Book Diagnostic").
The summary aggregates the per-window values with the period weighting, and
recomputes the ratio from the aggregated bps values.

**What the measurement shows.** On the reference panel used throughout this
document (900 bars, 5 assets, 2 bps commission, 1 bps slippage, 3 % borrow,
impact coefficient 0.5, $100k of equity), in `book` mode with the
market-neutral cross-sectional book and in `net-exposure` mode with the
asymmetric quantiles the default path requires (0.4 / 0.2):

| Reading | `book` mode | `net-exposure` mode |
| --- | --- | --- |
| charged by the model | 0.058 bps/period | 0.00007 bps/period |
| traded names would have paid | 0.131 bps/period | 0.152 bps/period |
| understatement (dilution) | -0.073 bps/period | -0.152 bps/period |
| notional-weighted (dollar) cost | 0.058 bps/period | 0.073 bps/period |
| names trading per period | 2.21 of 5 (ratio 0.44) | 2.29 of 5 (ratio 0.46) |
| gross book return | -1.03 bps/period | +1.56 bps/period |

Three things follow from it.

1. **The dilution is exactly `n / k`.** The model charges 44 % of the
   participation the traded names consumed -- the `k / n` factor, and nothing
   else.
2. **But the *cost* of those trades is not understated.** The book trades
   only `f = 44 %` of its equity in the `k` names it touches (it enters or
   exits one name at `1 / n` of the equity at a time), so the
   dollar-consistent cost `f * traded_only` is 0.058 bps/period -- the same
   number the panel convention charges. For this family of books the panel
   convention is *not* an approximation of the dollar cost: the `k / n`
   dilution and the "only a fraction of the equity was traded" factor cancel
   exactly.
3. **The conservative alternative would overcharge.** Charging the mean over
   the traded names instead would cost 0.131 bps/period instead of
   0.058 -- 2.26x the dollar-consistent cost, i.e. about 0.66 percentage
   points of the reported book-mode return (-15.68 % -> about -16.2 % on
   the reference panel). It is a *rate* comparison, not a cost comparison.

**Decision: the traded-only mean does *not* become the default.** It is the
conservative reading of the *participation rate*, but it is not a cost: it
implicitly charges the whole equity in every name the book touched. The
dimensionally consistent aggregation of a linear impact model is the
notional-weighted one, and that is a separate, number-changing change (it
would move every published impact number). Until that change is made
deliberately, the engine keeps charging the panel mean and *reports* the
measurement, so the size of the convention is visible in every artifact.

**Where the convention does bite.** The cancellation in (2) is a property of
a book that trades `1 / n` of the equity in each name it touches. A book
that *concentrates* -- the whole notional moving in and out of one name --
trades `f ~ 1` of the equity in `k = 1` name, so the panel convention
undercharges it by a factor of `n` while the notional-weighted aggregation
stays correct. A book that trades a fraction of the equity in *many* names
(`f` close to 1, `k` close to `n`) is charged approximately right by either
convention. The measurement distinguishes the three cases, so a reader always
knows which one they are in.

**Caveat.** The `impact_coefficient` is interpreted here as a price
concession rate (the cost is the rate applied to the traded notional), which
is the reading the "price elasticity of the order book" description of the
model implies. If instead it is meant as a portfolio-level cost rate per unit
of participation, the panel convention is the intended one and the
notional-weighted reading does not apply.

### Cross-path parity

`run_backtest.py` (single backtest) and `walk_forward.py` (walk-forward, CPCV
and out-of-sample validation) now price a panel with **one** convention. The
shared definitions live in `scripts/utils.py`:

| Model | Shared function | Convention |
| --- | --- | --- |
| Market returns | `build_market_model` | panel return = mean of the per-asset returns (`close.pct_change().mean(axis=1)`) |
| Market impact (net exposure) | `market_impact_cost` | per-asset notional `|d| * equity / n_assets` against each asset's own ADV; portfolio cost = equal-weighted mean |
| Market impact (book) | `book_market_impact_cost` | per-asset notional `|dw_i| * equity` against each asset's own ADV; portfolio cost = equal-weighted mean |
| Book cost basis | `book_cost_components` | gross turnover `sum_i |dw_i|`, short legs `sum_i max(-w_i, 0)`, gross exposure `sum_i |w_i|` |
| Book trade ledger | `book_trade_ledger` | one round trip per asset and direction, priced at the asset's own close |
| Capacity (basket) | `estimate_capacity` | equal-weighted basket; the least liquid constituent binds the portfolio capacity |
| Capacity (book) | `book_capacity_estimate` | the strategy's own trade sizes: `min_i ( max_impact * ADV_i / (abs(dw_i) * impact_coefficient) )` |

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

### Capacity trend (liquidity degradation inside a window)

The estimator above uses the **latest** ADV in each window, so a per-regime
value is a point-in-time liquidity reading: a drying-up regime *inside* the
window is invisible to it. The `capacity_trend` key therefore reports the
**distribution** of the per-period capacity readings across the whole window:

| Key                        | Meaning                                                       |
| -------------------------- | ------------------------------------------------------------- |
| `n_periods`                | number of periods with a valid capacity reading              |
| `min_capacity`             | worst (lowest) capacity reading inside the window             |
| `median_capacity`          | typical capacity reading inside the window                    |
| `max_capacity`             | best capacity reading inside the window                       |
| `last_capacity`            | the point-in-time reading (equals `estimated_capacity`)       |
| `min_to_median_ratio`      | worst / typical: a mid-window liquidity squeeze (<= 1)        |
| `last_to_median_ratio`     | end-of-window / typical: below 1 means liquidity dried up towards the end of the window |

Both ratios are relative to the median, so they are comparable across windows
with very different absolute capacity levels. `last_capacity` is by
construction the same number as the point-in-time `estimated_capacity`, so the
trend never contradicts the existing estimate.

The trend is surfaced next to the point-in-time capacity everywhere:

| Path                       | Point-in-time                          | Trend                                                   |
| -------------------------- | -------------------------------------- | ------------------------------------------------------- |
| `walk_forward_analysis`    | `periods[i]["capacity"]`               | `periods[i]["capacity_trend"]`                          |
| `cpcv_analysis`            | `folds[i]["capacity"]`                 | `folds[i]["capacity_trend"]`                            |
| `out_of_sample_validation` | `validation_performance["capacity"]`, `test_performance["capacity"]` | `validation_performance["capacity_trend"]`, `test_performance["capacity_trend"]` |
| `run_backtest`             | `results["capacity"]`                  | `results["capacity_trend"]`                             |

The summaries also carry the full-sample trend (`summary["capacity_trend"]`)
and, for the walk-forward / CPCV paths, `summary["oos_min_capacity"]`: the
**worst** capacity seen in any out-of-sample window, i.e. the liquidity level
that actually bound the strategy in the regimes it was traded in. The
out-of-sample summary additionally exposes `summary["validation_capacity_trend"]`
and `summary["test_capacity_trend"]`. The CLI artifacts persist the per-fold /
per-period trends in `capacity_per_fold` / `capacity_per_period`, and the tear
sheet renders a "Strategy Capacity Min (Notional)" summary row plus a
"Capacity Min (Notional)" column in the per-period and per-fold tables (cells
render `N/A` when the trend is absent).

The trend is `None` — never a zero or stale value — when impact is disabled
or ADV is not estimable, exactly like `estimated_capacity`.

**Caveat.** The per-period series uses the same rolling-`adv_window` ADV as the
point-in-time estimate, so the first `adv_window - 1` periods of a window are
based on a partial rolling history (noisier, not systematically biased). The
trend therefore describes the window's liquidity *distribution*; it is not a
liquidity forecast.

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

### Two capacity estimates

The basket rule above assumes a *particular* book: an equal-weight basket
that rebalances `1 / n_assets` per constituent. A strategy that exposes its
own book trades a different amount in every constituent, so the basket rule
is an approximation for it. In `book` mode the engine therefore reports **two**
capacity numbers, computed by `book_capacity_estimate` in `scripts/utils.py`:

| Number | Rule | Meaning |
| --- | --- | --- |
| basket-based (`capacity`) | `n_assets * max_impact * min_i(ADV_i) / impact_coefficient` | the notional an equal-weight basket that rebalances `1 / n` per constituent can carry |
| book-based (`capacity_book`) | `min_i ( max_impact * ADV_i / (abs(dw_i) * impact_coefficient) )` | the equity level at which **the strategy's own** next rebalance reaches the impact threshold |

The book-based number is the direct inversion of the impact model the book
mode actually charges: the impact of asset `i` at equity `E` is
`abs(dw_i) * E * impact_coefficient / ADV_i`, so the equity at which that
trade hits the threshold is `max_impact * ADV_i / (abs(dw_i) *
impact_coefficient)`, and the capacity of the book is the level at which
*every* traded constituent stays inside the threshold.

Properties (asserted by the test suite):

- The two rules **agree exactly** for a book that trades `1 / n_assets` per
  constituent every period: the basket rule is that special case.
- A book that trades **more** per period supports **less** capital: a book
  that rotates the whole notional through one name supports `n_assets` times
  less than the basket rule reports.
- A book that trades **less** per period (a cross-sectional book that only
  rotates when its constituent set changes) supports **more** capital than
  the basket rule reports. The basket number is therefore a *conservative*
  reading of a book that trades often and an *optimistic* one for a book that
  trades rarely.
- The reported number is the **point-in-time** reading: the capacity of the
  most recent bar on which the book actually traded (bars on which the book
  did not trade impose no constraint, so they are skipped). The
  `capacity_book_trend` key reports the distribution of the per-period
  readings, exactly like `capacity_trend` does for the basket number.
- It is `None` when impact is disabled, when the panel carries no volume, or
  when the book never traded in the window.

Where the numbers are reported:

| Path | Book-based capacity | Its distribution |
| --- | --- | --- |
| `run_backtest` | `results["capacity_book"]` | `results["capacity_book_trend"]` |
| `walk_forward_analysis` | `summary["capacity_book"]` | `summary["capacity_book_trend"]` |
| `walk_forward_analysis` (per window) | `periods[i]["capacity_book"]` | `periods[i]["capacity_book_trend"]` |
| `cpcv_analysis` | `summary["capacity_book"]` | `summary["capacity_book_trend"]` |
| `cpcv_analysis` (per fold) | `folds[i]["capacity_book"]` | `folds[i]["capacity_book_trend"]` |
| `out_of_sample_validation` | `summary["capacity_book"]` (test window), `validation_performance["capacity_book"]` | the matching `capacity_book_trend` keys |

The walk-forward and CPCV summaries also carry `oos_min_capacity_book`: the
**worst** book-based capacity seen in any out-of-sample window, i.e. the
liquidity level that actually bound the strategy's own trade sizes. The
per-window series are merged chronologically (each window's series is
computed inside its own window, so no artificial trade is created at a window
boundary) before the summary trend is computed.

The book-based capacity is reported in the **`book` pricing mode only**. In
the `net-exposure` mode the keys are `None`, so the default path keeps a
single (basket-based) capacity number and the default artifacts are
unchanged.

### Reporting

The tear sheet renders the aggregate capacity as a "Strategy Capacity
(Notional)" row in the Walk-Forward / CPCV analysis tables and surfaces it in
`tear_sheet_summary.json` under the corresponding analysis summary. In `book`
mode it also renders "Strategy Capacity (Notional, book-based)" and the
matching "Capacity Min" rows, and the per-window / per-fold tables gain a
"Capacity Book (Notional)" column.

The single-backtest path (`run_backtest.py`) reports the same estimate as
`results["capacity"]` (mirrored into `metrics["capacity"]`) and the same trend
as `results["capacity_trend"]` (mirrored into `metrics["capacity_trend"]`), so
capacity is part of every reported backtest result, not just multi-period
validation. Volume is optional on this path: when the data has no `volume`
column (or ADV is otherwise not estimable), `capacity` and `capacity_trend`
are `None` and the run proceeds without raising. For a panel the estimate uses
the same equal-weighted basket rule as the walk-forward paths (the least
liquid constituent binds), so the two CLIs report the same capacity for the
same panel
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
| `--panel-pricing`   | choice | `net-exposure` | How a panel is priced **and costed**: `net-exposure` (scalar net exposure x mean asset return, costs charged on the net exposure) or `book` (true per-asset book return `sum_i w_i r_i`, costs charged on the book: gross turnover, short legs, gross exposure, per-asset impact). See "Panel pricing modes". |

In the walk-forward module, `commission`, `slippage`, `impact_coefficient`,
`adv_window`, `borrow_cost`, and `funding_cost` are keyword arguments to
`walk_forward_analysis`, `parameter_optimization`, and `cpcv_analysis`.
`panel_pricing` is a keyword argument to the same functions (and to
`out_of_sample_validation`).

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

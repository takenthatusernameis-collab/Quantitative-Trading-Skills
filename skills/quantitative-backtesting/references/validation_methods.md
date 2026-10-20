# Validation Methods

This document describes the validation methodologies provided by
`scripts/walk_forward.py` for assessing strategy robustness.

## Walk-Forward Analysis

`walk_forward_analysis` splits the data into rolling training and testing
windows:

- **Training window**: Used to select optimal parameters via grid search.
- **Testing window**: Used to evaluate the selected parameters out-of-sample.

### Parameters

| Parameter       | Default | Description                                       |
| --------------- | ------- | ------------------------------------------------- |
| `train_months`  | 12      | Length of the training window in months           |
| `test_months`   | 3       | Length of the testing window in months            |
| `step_months`   | 3       | How far the window advances between iterations    |

### Algorithm

1. Start with `train_end = start_date + train_months`.
2. Define `test_start = train_end`, `test_end = test_start + test_months`.
3. For each parameter combination in `param_grid`, compute the Sharpe ratio
   on the training set.
4. Select the parameters with the highest training Sharpe.
5. Apply those parameters to the test window and record out-of-sample
   returns.
6. Advance `train_end` and `test_start` by `step_months` and repeat.

### Output

The result dictionary contains:

- `periods`: Per-period details including train/test boundaries, selected
  parameters, and test returns.
- `best_params_per_period`: List of optimal parameters for each period.
- `oos_returns`: Concatenated out-of-sample returns across all periods.
- `summary`: Aggregate metrics (total return, Sharpe, volatility, win rate).
  - `total_oos_return`: Compound OOS return across periods. `None` when no
    period produced a position (distinct from `0.0`, which means positions
    were taken but compounded to zero).
  - `periods_with_position`: Number of periods that produced an out-of-sample
    return (at least one parameter set took a position in that period).
  - `no_selection_diagnosis`: Why no period could select a parameter, when
    that happened (`{cause, message, details}`). Absent when at least one
    period selected a parameter. See "When No Parameter Can Be Selected".
  - `capacity` / `capacity_trend`: Market-impact capacity for the whole
    sample and the distribution of the per-period capacity readings inside
    it. `capacity` is a point-in-time reading (the last bar's ADV);
    `capacity_trend` carries `min_capacity` / `median_capacity` /
    `max_capacity` and the degradation ratios, so a liquidity squeeze inside
    the sample stays visible. `None` when impact is disabled or ADV is not
    estimable.
  - `oos_min_capacity`: The worst capacity seen in any out-of-sample period
    (the liquidity level that actually bound the strategy in the regimes it
    was traded in). `None` when no period produced a capacity trend.
  - `capacity_book` / `capacity_book_trend`: The capacity implied by the
    strategy's own trade sizes (the equity level at which one of its
    rebalances reaches the impact threshold) and the distribution of the
    per-period readings, reported in the `book` pricing mode next to the
    basket-based numbers above; `None` in the `net-exposure` mode. Each
    period also carries its own `period["capacity_book"]`.
  - `oos_min_capacity_book`: The worst book-based capacity seen in any
    out-of-sample period. `None` when no period produced a book capacity.
  - `book_diagnostic`: The panel book diagnostic aggregated over the
    out-of-sample periods: the per-asset book the strategy actually held
    (gross book, book net exposure vs the priced net exposure, book turnover
    vs the turnover the cost model charges) and the return gap between the
    engine's net-exposure pricing and the book P&L. Measurement only -- no
    return, cost, impact or capacity number changes. `None` for a single
    asset or a strategy that does not expose a book. Each period also carries
    its own `period["book_diagnostic"]`. See `cost_models.md`, "Panel book
    diagnostic (measurement only)".
  - The `impact_*` keys of the same diagnostic: the market-impact
    participation measurement (the impact the run charged, the impact the
    names that traded would have paid, the difference between them, the
    dollar-consistent notional-weighted cost and the participation ratio).
    All `None` when impact is disabled. See `cost_models.md`, "Market-impact
    participation (measurement only)".
  - `panel_pricing`: The pricing convention that produced the reported
    out-of-sample P&L: `"net-exposure"` (the default) or `"book"`. A panel
    return is not interpretable without it. In `book` mode the *costs* are
    charged on the book too (gross turnover, short legs, gross exposure,
    per-asset market impact), so the out-of-sample record is a costed book
    record. See `cost_models.md`, "Panel pricing modes (`--panel-pricing`)".

## Parameter Optimization

`parameter_optimization` performs a simpler grid search over the full dataset
using `n_splits`-style evaluation. Results are sorted by Sharpe ratio
(descending) and include total return and period count.

### Flat parameter sets

Both `walk_forward_analysis` and `parameter_optimization` skip parameter
combinations that take no position. The shared check is the module-level
`signals_active` helper:

- In `walk_forward_analysis`, a combo is skipped when
  `signals_active(test_signals)` is `False` in the test window (e.g.
  `slow_period=200` on a ~64-day window leaves every rolling indicator NaN,
  so the strategy stays flat). Without this guard the grid search would
  silently select such a combo as "optimal" and report a flat (zero)
  out-of-sample return for every period.
- In `parameter_optimization`, a combo is skipped when
  `signals_active(signals)` is `False` across the full dataset (e.g.
  `fast_period == slow_period`, which produces a flat signal everywhere).

Skipped combos are excluded from the returned results; they are never ranked.

Under the `book` panel pricing mode the check is **book-aware**
(`_window_takes_position`): a market-neutral book has a flat net exposure but
a positive gross exposure, so it *is* a position and the combo is not skipped.
A strategy that exposes no book falls back to the scalar `signals_active`
test. See `cost_models.md`, "Panel pricing modes (`--panel-pricing`)".

The same guard is applied by the `run_backtest` CLI entry point
(`scripts/run_backtest.py`), which raises `ValueError` when a strategy
never takes a position instead of producing a meaningless zero-return
backtest with a degenerate Sharpe ratio. Under the `book` mode the guard
asks the book (gross exposure) instead of the scalar signal.

## Deflated Sharpe Ratio (Multiple-Testing Correction)

Grid searches over parameter combinations are a multiple-testing
problem: with enough configurations, luck alone produces an
attractive in-sample Sharpe ratio. `deflated_sharpe_ratio`
implements the Deflated Sharpe Ratio (DSR, Bailey & Lopez de
Prado, 2014) to correct a reported Sharpe for selection bias and
for the non-normality of returns.

### Formula

All Sharpe quantities are in per-period (non-annualized) units:

```
DSR = Phi( (SR_hat - SR*) * sqrt(T - 1)
           / sqrt(1 - gamma3 * SR_hat + ((gamma4 - 1) / 4) * SR_hat^2) )
```

- `SR_hat`: estimated per-period Sharpe of the strategy
- `T`: number of return observations
- `gamma3`, `gamma4`: return skewness and kurtosis (kurtosis is
  the raw fourth moment, not excess kurtosis)
- `Phi`: standard normal CDF
- `SR*`: expected maximum Sharpe ratio under the null of no skill

`SR*` is estimated from the cross-sectional dispersion of the trial
Sharpe ratios when those are available (`SR* = std(SR_trials) *
sqrt(2 * ln(N))`), and otherwise from the i.i.d.-normal null
approximation (`SR* = sqrt(2 * ln(N) / T)`). Both estimators are
conservative: they slightly overstate the Sharpe attainable from
luck, so the correction errs against claiming skill.

### Interpretation

- The DSR is the probability that the strategy's true Sharpe ratio
  exceeds the best Sharpe expected from luck alone across `N`
  trials. It is reported together with `p_value = 1 - DSR`.
- DSR close to 1: the edge is unlikely to be selection bias.
- DSR below roughly 0.95 (p-value above roughly 0.05): the result
  is consistent with luck given the size of the search.
- The DSR corrects the reported Sharpe for the number of trials;
  it does not validate the out-of-sample economics of a strategy,
  and it is not evidence of profitability on its own.

### DSR Parity Invariant (Cross-Path Consistency)

The Deflated Sharpe Ratio is computed by four analysis paths that consume the
same grid and data — `walk_forward_analysis`, `cpcv_analysis`,
`out_of_sample_validation`, and `parameter_optimization` (the grid search
behind `monte-carlo --n-trials`). The **parity invariant** is that a strategy's
reported DSR p-value must not depend on which analysis path reported it.

**Counting basis** (the `n_trials` that drives the correction):

- `walk_forward_analysis` and `cpcv_analysis` (aggregate): `n_trials` is the
  number of **actually-evaluated, finite-Sharpe** configurations summed across
  all periods/folds — the cross-period sum, not the raw grid size. Combos
  filtered out by `signals_active` (flat strategies) are never counted.
- `out_of_sample_validation`: reconciled to the same evaluated-combo count as
  walk-forward on the same grid (it reuses the walk-forward selection on the
  train slice), and it now shares the pooled SR* estimator.
- `parameter_optimization` (per-combo DSR): uses the **full evaluated combo
  count** from a single grid traversal — not the cross-period sum. This is
  the basis `monte-carlo --n-trials` deflates the base backtest Sharpe by
  (effective count = `max(--n-trials, evaluated combos)`).

**SR* estimator parity for the aggregate paths.** When pooled trial Sharpes
are available, the OOS aggregate's expected-max-Sharpe `SR*` must match the
walk-forward / CPCV aggregate's `SR*` basis: all three derive `SR*` from the
cross-sectional dispersion of the same evaluated trial Sharpes
(`SR* = std(SR_trials) * sqrt(2 * ln(N))`). The i.i.d.-null fallback
(`SR* = sqrt(2 * ln(N) / T)`) would produce a different `SR*` and a far higher
p-value, so the pooled estimator is the recommended one for any aggregate DSR.

**Degenerate parity.** On exactly-constant (zero-variance) returns, every
path that reaches deflation emits the conservative degenerate dict
(`DSR = 0`, `p_value = 1`, `z_score = None`) with `n_trials` preserved —
including under cost sweeps, where varying borrow / funding / commission /
slippage must not move the counting basis off the degenerate DSR (the grid is
unchanged, so the multiple-testing counting basis cannot drift).

This invariant is an executable guard, not a documentation note: it is
asserted by `test_deflated_sharpe_parity_across_all_four_analysis_paths`,
`test_cost_sweep_dsr_parity_across_paths`,
`test_non_impact_sweep_dsr_parity_across_paths`, and
`test_degenerate_constant_return_dsr_consistency` in
`tests/test_walk_forward.py`. A regression that made one path deflate by a
different trial count or a different SR* estimator fails those tests even
while the artifact still looks well-formed.

### Usage

`parameter_optimization`, `walk_forward_analysis` and `cpcv_analysis`
accept `apply_deflation=True`:

- `parameter_optimization` adds a `deflated_sharpe` dict to every
  result row, computed with `n_trials` equal to the number of ranked
  configurations and `SR*` estimated from the cross-sectional
  dispersion of all trial Sharpes.
- `walk_forward_analysis` and `cpcv_analysis` add a per-period
  (per-fold) `deflated_sharpe` dict deflating that period's
  in-sample selection Sharpe by the configurations compared in that
  period, plus an aggregate `summary["deflated_sharpe"]` on the
  combined out-of-sample returns with `n_trials` equal to the total
  number of configurations evaluated across all periods/folds. The
  aggregate uses the pooled cross-period (cross-fold) trial Sharpes
  for the cross-sectional `SR*` estimator (the recommended estimator);
  the between-period variation inflates `SR*`, which is conservative.
  The i.i.d. null approximation is used only when no trial Sharpes
  are available.
- `overfitting_check` surfaces the aggregate DSR in its diagnostics
  when the walk-forward run computed one.
- The main backtest entry point `run_backtest.py` also reports the
  DSR when the number of development trials behind the backtest is
  supplied (`--n-trials`). `run_backtest` records `n_trials` in the
  results config and `calculate_metrics` deflates the final backtest
  Sharpe by it, adding a `deflated_sharpe` dict to the metrics (with
  `SR*` from the i.i.d. null approximation, since the individual trial
  Sharpes are not available to a single backtest). The report and tear
  sheet surface the dict; without `--n-trials` no `deflated_sharpe`
  key is emitted, so the output is backward compatible.
- The `monte-carlo` subcommand of `scripts/walk_forward.py` reports
  the DSR for the base backtest Sharpe when the number of development
  trials is supplied (`--n-trials`). The base backtest results are
  passed through `calculate_metrics` (mirroring `run_backtest`), so
  the deflation logic is shared. When a parameter grid was searched,
  the optimization runs internally and its ranked trial Sharpes are
  recorded in the config, so `SR*` uses the cross-sectional
  dispersion estimator (the recommended estimator) instead of the
  i.i.d. null approximation. The effective trial count is
  `max(--n-trials, number of grid combinations evaluated)`, so the
  internal search is never understated while additional development
  trials beyond the grid can still be reported. The DSR is printed
  and written to `monte_carlo_results.json` as a top-level
  `deflated_sharpe` key (with the effective `n_trials` recorded in
  the config); without `--n-trials` no key is emitted, so the output
  is backward compatible.

Example:

```python
results = parameter_optimization(
    data=data,
    strategy_factory=strategy_factory,
    param_grid={"fast_period": [10, 20], "slow_period": [30, 50]},
    apply_deflation=True,
)
top = results[0]
print(top["sharpe_ratio"], top["deflated_sharpe"]["deflated_sharpe_ratio"])
```

### CLI

Pass `--deflate` to the `walk-forward`, `optimize` and `cpcv`
subcommands of `scripts/walk_forward.py`. The flag is recorded in
the saved summary JSON under `config.deflate` and the DSR is printed
alongside the OOS Sharpe.

```bash
python3 scripts/walk_forward.py optimize \
    --data data.csv \
    --strategy sma_crossover \
    --param-grid '{"fast_period": [10, 20], "slow_period": [30, 50]}' \
    --deflate
```

For a single backtest, pass `--n-trials` to `scripts/run_backtest.py`
with the number of parameter configurations considered during
development. The final backtest Sharpe is deflated by that many
trials and the DSR is printed, written to `metrics.json`, and
rendered in `report.txt` and `tear_sheet.html`.

```bash
python3 scripts/run_backtest.py \
    --data data.csv \
    --strategy sma_crossover \
    --params '{"fast_period": 10, "slow_period": 30}' \
    --n-trials 50
```

### Degenerate and edge cases

A strategy that takes active positions on a perfectly flat test window
(e.g. a cross-sectional momentum strategy ranking assets whose prices are
identical) produces out-of-sample returns with **zero variance**. This is a
degenerate case, not a reason to skip the multiple-testing correction.

`deflated_sharpe_ratio` handles it explicitly: when `returns.std() == 0` it
sets `z = -inf`, yielding the conservative dict

```python
{
    "deflated_sharpe_ratio": 0.0,
    "p_value": 1.0,
    "sharpe_ratio": 0.0,
    "expected_max_sharpe": <expected max under the null>,
    "z_score": None,
    "n_trials": ...,
    "n_observations": ...,
    "skewness": 0.0,
    "kurtosis": 3.0,
}
```

This is emitted consistently by every entry point that accepts an
`n_trials` / `apply_deflation` argument:

- `run_backtest --n-trials N`
- `monte-carlo --n-trials N`
- `walk_forward_analysis(apply_deflation=True)` (aggregate DSR)
- `cpcv_analysis(apply_deflation=True)` (aggregate DSR)
- `parameter_optimization(apply_deflation=True)` (per-combo DSR;
  see the ranking distinction below)

A previous guard (`oos_returns.std() > 0`) on the walk-forward and CPCV
aggregate paths silently **omitted** the `deflated_sharpe` key on constant
OOS returns, which was inconsistent with `run_backtest` and `monte-carlo`
and would have made downstream consumers (tear sheets, reports, CI checks
for the key) behave differently for degenerate data. The guard is now
`len(oos_returns) > 1` only; the degenerate dict is always emitted when
deflation is requested and there are at least two observations.

When no configuration takes an active position in any test window (all
combinations are filtered out by `signals_active`), the OOS return series is
empty. In that case no Sharpe or DSR can be computed and the key is omitted
from the summary — this is a genuine "no signal" outcome, not a degenerate
one, and is distinct from the zero-variance case above.

### Per-period and per-fold DSR on degenerate windows

The per-period (walk-forward) and per-fold (CPCV) DSRs are
**in-sample** deflations: each is computed on the period's
*training* returns — the in-sample Sharpe of the configuration
the grid search selected for that period — not on the test-window
returns. Two consequences:

- Constant *test* windows (a strategy that takes active positions
  on a flat test window) leave the per-period DSR **non-degenerate**:
  the training returns retain variance, so the per-period DSR carries
  a finite `z_score` rather than the degenerate dict above. Only the
  *aggregate* DSR on the combined OOS returns takes the degenerate
  dict.
- A flat *training* window leaves every configuration's in-sample
  Sharpe undefined (zero variance), so no configuration is selected:
  the period is skipped entirely (`best_params` is `None`, no
  `deflated_sharpe` key, no out-of-sample contribution). This is a
  genuine "no signal" outcome, distinct from the degenerate dict —
  there is no in-sample Sharpe to deflate.

`parameter_optimization(apply_deflation=True)` deflates each
*ranked* combination's own return series, and its Sharpe rule
defines the per-combo Sharpe as 0 when `returns.std() == 0`
(`walk_forward.py:352`). A zero-variance combo is therefore
**ranked** (at Sharpe 0) rather than skipped: every ranked combo
carries the degenerate dict above (`z_score = None`, DSR = 0,
p-value = 1) because its return series has zero variance. This is
distinct from the walk-forward/CPCV grid search, where a
zero-variance *training* series yields sharpe = -inf, so no
configuration is selected and the period is skipped — and from the
aggregate DSR, which emits a single degenerate dict on the combined
OOS returns.

The `monte-carlo` subcommand accepts the same `--n-trials` flag. It
first runs the parameter optimization implied by `--param-grid` to
select the base parameters, then deflates the base backtest Sharpe
before running the simulations. The effective trial count is
`max(--n-trials, number of grid combinations evaluated)`: the
internal search is always fully accounted for, and `--n-trials` can
still report additional development trials beyond the grid. The
optimization record's trial Sharpes are used for `SR*`. The DSR is
printed and saved to `monte_carlo_results.json`.

```bash
python3 scripts/walk_forward.py monte-carlo \
    --data data.csv \
    --strategy sma_crossover \
    --param-grid '{"fast_period": [10, 20], "slow_period": [30, 50]}' \
    --n-simulations 2000 \
    --n-trials 50
```

## Out-of-Sample Validation Framework

`out_of_sample_validation` implements a three-phase validation framework
that prevents data leakage between parameter selection and final
evaluation:

1. **TRAIN**: Walk-forward analysis or CPCV on the training portion to
   select optimal parameters.
2. **VALIDATE**: Evaluate the selected parameters on the validation
   portion (confirmation).
3. **TEST**: Final evaluation on the held-out test set, which has never
   been used in any optimization or selection step.

### The Walk-Forward Window Inside the Training Split

The validation phase of `out_of_sample_validation` runs **inside** the
training split, so the walk-forward window has to fit the training split: a
single period needs `train_months + test_months` of calendar span before it
can exist at all.

When the requested window does not fit, the validation phase produces
**zero** periods, no parameter can be selected, and the run aborts with
"No valid parameters selected from validation phase" — a message that hides
the real cause. The default window (12 + 3 months) does not fit the
one-year training split the CLI carves out of the shipped
`assets/example_data/sample_ohlcv.csv`, which is exactly how that path
failed.

The window is therefore resolved against the training split before the
validation phase runs (`_resolve_walk_forward_window`):

- a requested window that fits is used **unchanged** — the runs that already
  worked keep their methodology and their numbers;
- a requested window that does not fit is shortened **on the training side
  only**, to the largest value that still yields at least one period. The
  out-of-sample test window of the validation phase (`test_months`) and the
  validation / test splits of the out-of-sample framework are never touched,
  so the out-of-sample guarantee is unaffected;
- a training split too short for *any* window is reported, not guessed.

The resolution is a methodology choice, so it is never implicit: it is
printed by the CLI ("Walk-forward window adapted to the training split"),
and recorded in the result artifact under `summary["walk_forward_window"]`:

| Key | Meaning |
| --- | ------- |
| `requested` | The window the caller asked for |
| `effective` | The window the validation phase actually ran with |
| `adapted` | Whether the training window had to be shortened |
| `train_span_months` | Calendar span of the training split |
| `requested_periods` / `effective_periods` | Periods each window yields |
| `reason` | Why the window was adapted (or why it could not be) |

### When No Parameter Can Be Selected

"No valid parameters selected from validation phase" is a symptom, not a
diagnosis. The two usual causes need completely different remedies, so the
cause is reported explicitly (`summary["no_selection_diagnosis"]`, with a
`cause`, a human-readable `message` and a structured `details` dict):

| `cause` | Meaning | Remedy |
| ------- | ------- | ------ |
| `no_validation_windows` | The validation phase produced no out-of-sample window at all (the walk-forward window does not fit the training split) | Give the training split more history, or shorten `--wf-train-months` / `--wf-test-months` |
| `no_position_in_validation_window` | Windows were built, but every grid combination stayed flat over them (the indicator warm-up is longer than the window) | Shorten the indicator lookbacks in the grid, lengthen the test window, or raise the test-size fraction / lower the number of splits |

**Every path that can end up selecting nothing now reports it**, with the
same vocabulary and the same artifact key, so one reader handles all of them:

| Path | Recorded in | Notes |
| ---- | ----------- | ----- |
| `out-of-sample` | `summary["no_selection_diagnosis"]` (the failure summary) | The validation phase runs inside the training split |
| `cpcv` (standalone) | `summary["no_selection_diagnosis"]` | The whole sample is the data the selection ran on |
| `walk-forward` (standalone) | `summary["no_selection_diagnosis"]` | The whole sample is the data the selection ran on |

The diagnosis is recorded **only** when no period / fold selected a parameter
at all; a run that selected something carries no diagnosis. It is a
measurement: it changes no return, cost, impact, capacity or selection
number.

The CLI prints the diagnosis next to the fold / period count
(`No parameter could be selected: <message>`), so the console and the
artifact carry the same string.

#### When Only Some Windows Select a Parameter

"2 of 5 folds selected" is not a finding on its own. It is compatible with
"the other three folds were too short to trade" (a design problem) and with
"the strategy never triggers on 60% of the sample" (a finding about the
strategy), and the two call for completely different remedies. A run in
which **some** windows selected a parameter and others did not therefore
records its own diagnosis, under a separate key
(`summary["partial_selection_diagnosis"]`, the same
`{cause, message, details}` shape), and the categorical overfitting-risk
verdict keeps its value but gains an `overfitting_risk_reason` that states
how many windows it rests on.

The all-flat case is unchanged: it keeps using `summary["no_selection_diagnosis"]`,
and the partial key is only present when the run is in the partial state.

| Path | Recorded in | Notes |
| ---- | ----------- | ----- |
| `out-of-sample` | `summary["partial_selection_diagnosis"]` | The validation phase runs inside the training split, so the selected parameter was chosen from the windows that could select one |
| `cpcv` (standalone) | `summary["partial_selection_diagnosis"]` | The whole sample is the data the selection ran on |
| `walk-forward` (standalone) | `summary["partial_selection_diagnosis"]` | The whole sample is the data the selection ran on |

##### The cause is measured in the search, not inferred

A window that selected nothing looks the same from the outside whether the
strategy never traded in it or whether the training split made the ranking
impossible, and the two need opposite remedies. The grid search therefore
records a tally of what happened to every combination
(`selection_outcomes` on the period / fold record) and the diagnosis reports
the cause that tally attributes to each window:

| `cause` | Meaning | Remedy |
| ------- | ------- | ------ |
| `no_position_in_validation_window` | No combination took a position in the window, so the search had nothing to rank | Shorten the indicator lookbacks, lengthen the test window, or raise the test-size fraction / lower the number of splits — but only if the window is the short one (see below) |
| `no_estimable_training_sharpe` | Every combination took a position, but the training split produced a constant return series, so the in-sample Sharpe the selection ranks on is undefined | Give the training split more history (`--train-months` / `--n-splits`), or use a strategy that does not stay flat over it |
| `all_combinations_failed` | Every combination raised an error while it was evaluated | Check the values in the parameter grid |

`no_position_in_validation_window` is the vocabulary the "no parameter
could be selected" diagnosis already used. The other two are the causes
that diagnosis could not tell apart, because an empty result looks the
same for all three: a window in which nothing traded, a window whose
training split cannot be ranked, and a grid whose combinations all fail.

##### The per-window breakdown

`details["flat_windows"]` carries one record per flat window:

| Key | Meaning |
| --- | ------- |
| `window` / `fold` | The index of the flat fold / period |
| `cause` | The cause the search's tally attributes to the window |
| `reason` | `window_too_short`, `signal_never_triggered`, `training_sharpe_not_estimable` or `all_combinations_failed` |
| `bars` / `train_bars` | The length of the out-of-sample window and of its training split |
| `test_returns_bars` / `test_sharpe` | The empty out-of-sample record of the window (0 bars, no Sharpe) |
| `max_position_bars` | The most bars any combination could have held a position for in the window (0 when the strategy never traded in it) |
| `test_start` / `test_end` | The window's calendar boundaries |
| `outcome_tally` | How many combinations ended in each outcome |
| `text` | The one-line statement the CLI prints for this window |

`details["traded_windows"]` carries the same evidence for the windows the
verdict rests on, so the two can be read together.

##### "Too short" and "never triggered" are separated by a measurement

For a flat window whose cause is `no_position_in_validation_window`, the
diagnosis compares the window's length with the shortest window in which
the strategy did trade:

- the flat window is **shorter** than every traded window → the window
  length cannot be ruled out as the cause (`reason: window_too_short`);
- the flat window is **at least as long** as the shortest traded window →
  the length does not by itself explain the failure: the signal never
  triggered on it (`reason: signal_never_triggered`).

The comparison is a statement about the windows, not a claim about the
  strategy's warm-up, and it is bounded by what the run measured: the
  diagnosis also reports how many bars the strategy actually held a position
  in the windows that did trade
  (`details["min_traded_position_bars"]`), because a verdict measured on
  windows in which the strategy held a position for a single bar is a
  different statement from one measured on windows it traded throughout.

  #### How much evidence the verdict rests on

  "The strategy held a position for a single bar" is the sharper form of the
  same question, and it is not visible in any number the artifact already
  reports. The aggregate out-of-sample Sharpe and the parameter stability
  ratio are computed over the *returns* of the windows that selected a
  parameter, so they say nothing about how much of those windows the
  strategy actually traded in: a "low" overfitting-risk rating earned on two
  windows that each held a position for one bar out of twenty reads as a
  finding about the strategy when it is mostly a finding about the windows.

  When a run is in the partial state it records `summary[
  "thin_evidence_warning"]` -- a measurement, so it changes no number -- with
  a per-window breakdown of the windows the verdict rests on in which the
  strategy held a position for at most 20% of the **executable** bars. The
  fraction is of executable bars, not raw window bars, so it is stable across
  the two warmup conventions: the walk-forward path drops two leading bars
  from every window before the strategy can act on them, so a 20-bar window
  has 18 executable bars and a position held for one bar is 1/18 of them.

  | Key | Meaning |
  | --- | ------- |
  | `message` | The one-line statement the CLI prints |
  | `details.n_windows_with_selected_params` | How many windows the verdict rests on |
  | `details.n_thin_windows` | How many of those were thin |
  | `details.warmup_bars` | The warmup bars subtracted from each window |
  | `details.threshold` | The fraction at or below which a window is thin (0.2) |
  | `details.thin_windows` | One record per thin window |

  Each thin-window record carries the window's index, its length, its
  executable length, the bars it held a position, the fraction of executable
  bars that represents, the out-of-sample Sharpe of the selected combo in it,
  and the window's calendar boundaries -- the same evidence the
  `traded_windows` breakdown already carries, plus the fraction.

  A run in which every window the verdict rests on traded in at least that
  fraction of its executable bars carries no warning, and a run in which
  nothing was selected at all carries none either (that is the
  `no_selection_diagnosis`, which already says why). The CLI prints the
  warning next to the verdict, and the artifact carries the same message.

  #### The remedy names the flags the path actually accepts

The same setting is spelled differently on the different subcommands, so the
remedy names the flags of the path that produced the failure:

| Path | Flags in the remedy |
| ---- | ------------------- |
| `cpcv` (standalone) | `--test-size`, `--n-splits` |
| `walk-forward` (standalone) | `--train-months`, `--test-months`, `--step-months` |
| `out-of-sample` (CPCV) | `--cpcv-test-size`, `--cpcv-n-splits` |
| `out-of-sample` (walk-forward) | `--wf-train-months`, `--wf-test-months`, `--wf-step-months` |

#### The CPCV test window is a fraction of each group

`--test-size` is the fraction of **each group** that becomes the test set, so
the effective out-of-sample fraction is

```
effective_oos_fraction = test_size / n_splits
```

not the fraction the flag name suggests. At the default `--test-size 0.1
--n-splits 10` the effective out-of-sample fraction is **1%**: on the shipped
`assets/example_data/sample_ohlcv.csv` (504 bars) every fold's test window
holds **5 bars**, which is shorter than the indicator warm-up, so no
combination can take a position and no parameter can be selected. The
diagnosis states the effective fraction and the window length, so this is
never left to be guessed.

### The Overfitting-Risk Verdict When Nothing Could Be Selected

The risk classification is derived from the *parameter stability*, which
exists only when a parameter was selected in at least one period / fold. When
nothing could be selected there is no stability to classify, so the verdict
is **not applicable**, not "low" and not "high":

- CPCV: `summary["overfitting_risk"]` is `null` and
  `summary["overfitting_risk_reason"]` says why;
- walk-forward: `diagnostics["overfitting_risk"]` is `null` and
  `diagnostics["overfitting_risk_reason"]` says why;
- the CLI prints `Overfitting Risk: unknown` plus the reason, and the
  sensitivity-sweep tables print `unknown` in the risk column.

Before this change the two paths disagreed on the same state -- CPCV
reported `high` and walk-forward reported `low` for a run in which no
parameter could be selected -- which is a category error: a categorical
verdict on a run that could not trade reads as a finding about the strategy
when it is a fact about the window.

### Inert Parameter Grids

A grid key whose values all produce the **same** signals (and the same book)
on the data the path prices is inert: the "search" over it cannot change any
result, yet the artifact would still report it as a selected parameter. This
is a behavioural check, not a name check: it catches the common trap of a
grid over a parameter the strategy does not read (e.g. `lookback` for
`sma_crossover`, which reads `fast_period` and `slow_period`), and it does
not flag a parameter that is merely unused on one particular sample.

**Every analysis path detects it.** The measurement lives in
`_inert_param_grid_keys` and is reported by `_inert_grid_report`, which
returns the inert keys, the parameter names the strategy actually reads
(read from the strategy's own source, so the hint cannot drift away from the
implementation) and a human-readable message. The analysis functions only
*measure* — they never print and never change a return, cost, impact,
capacity or selection number — so the CLI decides where the warning appears
and the artifact and the console always say the same thing.

| Path | Recorded in | Scope of the measurement |
| ---- | ----------- | ------------------------ |
| `walk_forward_analysis` (`walk-forward`) | `summary["inert_grid_params"]`, `summary["inert_grid_message"]` | the full sample the path prices |
| `cpcv_analysis` (`cpcv`) | `summary["inert_grid_params"]`, `summary["inert_grid_message"]` | the full sample the path prices |
| `parameter_optimization` (`optimize`) | `parameter_optimization_inert_grid.json` (next to the ranked list) | the full sample the path prices |
| `out_of_sample_validation` (`out-of-sample`) | `summary["inert_grid_params"]`, `summary["inert_grid_message"]` | the training split, which is where the selection happens |

The ranking artifact of the optimization path is a plain ranked list, so the
finding is written next to it as a separate record
(`parameter_optimization_inert_grid.json`: the inert keys, the message, the
parameter names the strategy reads, the grid, the strategy and the number of
ranked combinations). The cost-sweep artifacts carry the same information in
their rows (`inert_grid_params`).

**A warning, not an error.** An entirely inert grid does not abort the run:
the same grid may be non-inert on other data (a parameter can change the
behaviour only in a particular regime), and the measurement is a screen over
the data the path prices. Consistency across the four paths matters more
than strictness, and the out-of-sample path has always warned rather than
failed.

The measurement is a **screen over the data the path prices**, not a proof
about the strategy. What it compares is exhaustive over the combinations: a
key is reported as inert only when its values produce the same behaviour in
**every** combination of the other grid keys' values. Varying one key while
holding the others at their first value is not enough: a key whose effect
appears only in *combination* with a non-first value of another key (a
parameter the strategy reads only inside a branch, say) would be accused of
being inert while it is live, and a false accusation is worse than no
accusation because it teaches the reader to ignore the warning. The check
therefore compares each key across every combination of the other keys'
values, and a key that changes the behaviour in *one* of them is never
reported. Read the strategy's parameter names before trusting a selection:
the parameter names the strategy reads are reported next to the warning
(`strategy_parameters`), and they are read from the strategy's own source, so
they cannot drift away from the implementation.

**The bound.** The exhaustive comparison costs `len(values) x
product(len(other values))` behavioural fingerprints per key, which is
unbounded in the size of the grid, so at most
`_INERT_GRID_MAX_COMBINATIONS` (16) combinations of the other values are
evaluated per key. A grid that fits in the bound is checked exhaustively; a
grid that does not falls back to the first combination (the other keys held
at their first value) **and the finding says so** — the message reports that
the check was bounded and may have missed an interaction between
parameters. The bound can only weaken an *inert* verdict: a key that shows
a behavioural difference is live whatever the bound, because one difference
is proof of liveness, so a bounded check never accuses a live key.

### Strict Train/Validation/Test Separation

The framework depends on the held-out test set having **never** been
used in any parameter selection or confirmation step. That guarantee is
enforced as an executable invariant rather than a documentation note:

- `_split_train_val_test` calls `_verify_split_separation` on the three
  splits before returning. The check asserts that the train, validation
  and test index sets are pairwise disjoint and chronologically ordered
  (`train_end < val_start` and `val_end < test_start`). Any overlap or
  ordering violation raises `ValueError`.
- The check result is recorded in the returned
  `train_val_test_split` dictionary under the `separation_check` key,
  exposing `disjoint`, `chronological`, the three pairwise overlap
  counts, and the split sizes for audit.
- `_verify_split_separation` is also a standalone helper
  (`walk_forward._verify_split_separation`) with a `strict` flag: in
  non-strict mode it returns the diagnostic dict without raising, so the
  invariant can be reused and tested independently of the full pipeline.

This catches the class of defect where an inclusive boundary (e.g. an
`<=` slice or an overlapping rolling window) silently leaks future
information into the training or validation phase. A leak there would
produce an in-sample-optimistic result that is indistinguishable from a
genuine out-of-sample one, so the check is a correctness guard, not a
cosmetic one.

### Per-Period / Per-Fold `test_sharpe` (Out-of-Sample Test Sharpe)

Every walk-forward period and CPCV fold whose grid search selected a combo now
carries a `test_sharpe` key: the **annualized out-of-sample Sharpe of the
selected combo on that period/fold's test window** (net of the same cost model
used in the grid search; risk-free 2% annual; `None` when the test window is
too short or degenerate). This is distinct from `best_sharpe`, which is the
**in-sample training Sharpe** the grid search ranked by.

`_select_parameters` uses `test_sharpe` for the `best_oos_sharpe` and
`best_avg_sharpe` criteria, and the OOS summary exposes
`selected_params_avg_test_sharpe` (mean OOS test Sharpe of the selected combo
across the periods/folds that chose it). Selection on `best_sharpe` would pick
the combo that overfit its training window — the selection bias this framework
exists to avoid — so `best_sharpe` is deliberately not used for selection.

### Selection Criteria (`--selection-criterion`)

`out_of_sample_validation` selects the final parameters from the validation
phase via `--selection-criterion`, one of `best_oos_sharpe` (default),
`most_stable`, or `best_avg_sharpe`. The choice matters because it determines
what the selection is optimizing:

- **`most_stable`** selects on **in-sample** behavior: the combo the grid
  search most often selected across periods/folds. This is a property of the
  optimizer, not of the test data, so it is the only criterion that legitimately
  reads in-sample information.
- **`best_oos_sharpe`** selects the period/fold with the best **out-of-sample**
  test Sharpe.
- **`best_avg_sharpe`** selects the combo with the best **average out-of-sample**
  test Sharpe across the periods/folds where it was chosen.

`best_oos_sharpe` and `best_avg_sharpe` read each period/fold's
**`test_sharpe`** key (the OOS test Sharpe of the combo selected in that
period/fold), **never `best_sharpe`**, which is the **in-sample training
Sharpe** the grid search ranked by. Selecting on `best_sharpe` would pick the
combo that overfit its training window — the exact selection bias the
out-of-sample framework exists to avoid. Each walk-forward period and CPCV
fold now carries `test_sharpe` (`None` on degenerate/empty test windows), and
the OOS summary carries `selected_params_avg_test_sharpe` (mean OOS test Sharpe
of the selected combo across the periods/folds that chose it).

## Overfitting Detection

`overfitting_check` analyzes walk-forward results to flag overfitting risk:

### Parameter Stability

For each parameter, compute:

```
stability_ratio = 1 - unique_values / total_periods
```

A high stability ratio (close to 1.0) means the same parameter value is
selected across most periods, suggesting robustness. A low ratio indicates
the optimizer is chasing noise.

### Risk Classification

| Average Stability | Risk Level |
| ----------------- | ---------- |
| >= 0.5            | low        |
| 0.3 to 0.5        | medium     |
| < 0.3             | high       |

When no period selected a parameter at all there is no stability to
classify: the verdict is `null` ("not applicable") with an
`overfitting_risk_reason`, not a categorical level. See "When No Parameter
Can Be Selected".

### Out-of-Sample Metrics

The diagnostics also include OOS Sharpe, total return, and volatility
computed on the concatenated out-of-sample returns.

## Monte Carlo Simulation

`monte_carlo_simulation` performs bootstrap resampling on strategy returns to
generate synthetic equity curves and compute the distribution of performance
metrics. This helps assess the statistical significance and robustness of
backtest results.

The function lives in the standalone `scripts/monte_carlo.py` module and is
re-exported from `scripts/walk_forward.py` for backward compatibility, so it
can be imported either way:

```python
from monte_carlo import monte_carlo_simulation
# or
from walk_forward import monte_carlo_simulation
```

### Parameters

| Parameter            | Default  | Description                                              |
| -------------------- | -------- | -------------------------------------------------------- |
| `base_returns`       | (required) | Series of strategy returns from a backtest              |
| `n_simulations`      | 2000     | Number of Monte Carlo paths to generate                  |
| `confidence_levels`  | [0.90, 0.95, 0.99] | Confidence levels for percentile bands           |
| `block_size`         | None     | Block size for stationary block bootstrap (preserves autocorrelation). None = simple i.i.d. resampling. |

### Algorithm

1. Take the base strategy returns from a backtest.
2. For each simulation, resample the returns with replacement (optionally using block bootstrap).
3. Construct a synthetic equity curve from the resampled returns.
4. Compute performance metrics (total return, Sharpe, max drawdown, etc.) for each path.
5. Aggregate the metric distributions and compute confidence intervals.

### Output

The result dictionary contains:

- `simulated_equity_curves`: List of equity curve Series for each simulation
- `metric_distributions`: Dict mapping metric name to array of simulated values
- `confidence_intervals`: Dict of metric -> {confidence_level: (lower, upper)}
- `probability_of_ruin`: Fraction of simulations where equity falls below 50% of initial capital
- `summary`: Mean, std, median, min, max for each metric
- `n_simulations`: Number of simulations run
- `base_observations`: Number of observations in base returns

### Usage Example

```python
# After running a backtest
from monte_carlo import monte_carlo_simulation

mc_results = monte_carlo_simulation(
    base_returns=backtest_returns,
    n_simulations=2000,
    confidence_levels=[0.90, 0.95, 0.99],
    block_size=5,  # Optional: preserve autocorrelation
)

# Check probability of ruin
print(f"Probability of 50% drawdown: {mc_results['probability_of_ruin']:.2%}")

# Check Sharpe ratio confidence interval
sharpe_ci = mc_results['confidence_intervals']['sharpe_ratio'][0.95]
print(f"95% CI for Sharpe: [{sharpe_ci[0]:.2f}, {sharpe_ci[1]:.2f}]")
```

### Interpretation

- **Narrow confidence intervals** indicate stable, robust performance.
- **Wide intervals** suggest the strategy's performance is highly sensitive to the specific sequence of returns.
- **Probability of ruin** quantifies tail risk: the chance of a catastrophic drawdown under resampled conditions.
- If the observed Sharpe ratio falls outside the 95% confidence interval of the Monte Carlo distribution, the result may be statistically unusual (either positively or negatively).

### Multiple-Testing Correction (CLI)

The `monte_carlo_simulation` function itself knows nothing about
how the base backtest was produced. The `monte-carlo` CLI
subcommand does: it selects the base parameters via the
`--param-grid` optimization, so the base Sharpe carries the
selection bias of that search. Pass `--n-trials` with the
number of development trials to deflate the base backtest
Sharpe; the DSR is printed, saved as a top-level
`deflated_sharpe` key in `monte_carlo_results.json`, and
computed with `SR*` from the cross-sectional dispersion of the
optimization record's trial Sharpes (or the i.i.d. null
approximation when no grid was searched). The effective trial
count is `max(--n-trials, number of grid combinations
evaluated)`, so the internal search is never understated.
Without `--n-trials` no `deflated_sharpe` key is emitted.

## Combinatorially Purged Cross-Validation (CPCV)

`cpcv_analysis` implements Combinatorially Purged Cross-Validation (CPCV) as
described in Lopez de Prado's *Advances in Financial Machine Learning*. CPCV
addresses look-ahead bias and multiple-testing issues by:

1. Splitting data into `n_splits` sequential groups
2. For each fold, using `n_splits-1` groups for training, 1 group for testing
3. Purging (removing) observations around the test set from training to prevent
   look-ahead bias (e.g., due to overlapping rolling windows)
4. Adding an embargo period after the test set to prevent contamination

### Parameters

| Parameter       | Default | Description                                       |
| --------------- | ------- | ------------------------------------------------- |
| `n_splits`      | 10      | Number of sequential groups to split data into    |
| `test_size`     | 0.1     | Fraction of each group to use as test set         |
| `purge_size`    | 0.0     | Fraction of observations to purge from training   |
| `embargo_size`  | 0.0     | Fraction of observations to embargo after test    |

### Algorithm

1. Split the data into `n_splits` sequential groups of equal size.
2. For each group `i` (0 to `n_splits-1`):
   a. Define test set as first `test_size` fraction of group `i`.
   b. Define training set as all other groups, with:
      - **Purge**: Remove `purge_size` observations before test set from
        preceding groups' training data.
      - **Embargo**: Remove `embargo_size` observations after test set from
        following groups' training data.
   c. Grid search over `param_grid` on training set, select best params by Sharpe.
   d. Evaluate best params on test set, record out-of-sample returns.
3. Aggregate results across all folds.

### Output

The result dictionary contains:

- `folds`: Per-fold details including train/test boundaries, selected
  parameters, and test returns.
- `best_params_per_fold`: List of optimal parameters for each fold.
- `oos_returns`: Concatenated out-of-sample returns across all folds.
- `summary`: Aggregate metrics (total return, Sharpe, volatility, win rate,
  parameter stability, overfitting risk).
  - `total_oos_return`: Compound OOS return across folds. `None` when no fold
    produced a position (distinct from `0.0`, which means positions were taken
    but compounded to zero).
  - `folds_with_position`: Number of folds that produced an out-of-sample
    return (at least one parameter set took a position in that fold).
  - `no_selection_diagnosis`: Why no fold could select a parameter, when
    that happened (`{cause, message, details}`). Absent when at least one
    fold selected a parameter. See "When No Parameter Can Be Selected".
  - `capacity` / `capacity_trend`: Market-impact capacity for the whole
    sample and the distribution of the per-period capacity readings inside
    it. `capacity` is a point-in-time reading (the last bar's ADV);
    `capacity_trend` carries `min_capacity` / `median_capacity` /
    `max_capacity` and the degradation ratios, so a liquidity squeeze inside
    the sample stays visible. `None` when impact is disabled or ADV is not
    estimable.
  - `oos_min_capacity`: The worst capacity seen in any out-of-sample fold.
    `None` when no fold produced a capacity trend.
  - `capacity_book` / `capacity_book_trend`: The capacity implied by the
    strategy's own trade sizes, reported in the `book` pricing mode next to
    the basket-based numbers above (see the walk-forward `summary` above).
    Each fold also carries its own `fold["capacity_book"]`.
  - `oos_min_capacity_book`: The worst book-based capacity seen in any
    out-of-sample fold. `None` when no fold produced a book capacity.
  - `book_diagnostic`: The panel book diagnostic aggregated over the
    out-of-sample folds (see the walk-forward `summary` above). Each fold
    also carries its own `fold["book_diagnostic"]`. `None` for a single asset
    or a strategy that does not expose a book.
  - `panel_pricing`: The pricing convention that produced the reported
    out-of-sample P&L: `"net-exposure"` (the default) or `"book"`. In `book`
    mode the costs are charged on the book as well. See `cost_models.md`,
    "Panel pricing modes (`--panel-pricing`)".
- `param_stability`: Per-parameter stability analysis with `unique_values`,
  `most_common`, and `stability_ratio`.

### Parameter Stability

For each parameter, compute:

```
stability_ratio = 1 - unique_values / total_folds
```

A high stability ratio (close to 1.0) means the same parameter value is
selected across most folds, suggesting robustness. A low ratio indicates
the optimizer is chasing noise.

### Overfitting Risk Classification

| Average Stability | Risk Level |
| ----------------- | ---------- |
| >= 0.5            | low        |
| 0.3 to 0.5        | medium     |
| < 0.3             | high       |

When no fold selected a parameter at all there is no stability to classify:
the verdict is `null` ("not applicable") with an
`overfitting_risk_reason`, not a categorical level. See "When No Parameter
Can Be Selected".

### The Warmup Bars of a Window

Every window (train or test) that the framework prices loses its first
**`latency + 2`** bars to the execution warmup, and the number of usable bars
is part of the reported result:

- the position series is `signal.shift(1 + latency)`, so it is undefined
  (`NaN`) on the first `1 + latency` bars of a window;
- the cost term is `positions.diff().abs() * (commission + slippage)`, and
  `positions.diff()` inherits that `NaN` on the bar after that as well.

All of those bars are therefore dropped from the return series. The drop is
*explicit* rather than emergent: `_calculate_strategy_returns` marks the first
`EXECUTION_WARMUP_BARS` (2) bars of the cost term as `NaN` explicitly, so the
warmup does not depend on `NaN` propagating through the cost model. On the
second bar the strategy is flat (its signal is still warming up), so the bar's
return would be `0.0` and it multiplies the compounded return by `1.0`. The
*return* is therefore insensitive to the warmup convention, while the *number
of usable bars* and the *training sample* are not.

Consequences to keep in mind when reproducing a number:

- a 25-bar test window contributes 23 usable bars;
- the training Sharpe that drives parameter selection is computed on a
  series that is missing that one flat bar, so it is not exactly the Sharpe
  of the strategy's own (longer) return series;
- the bar count is what pins the convention, not the compounded return.

The count above is the *execution* warmup only. A strategy's own indicator
warmup (a moving average needs `lookback - 1` bars before it produces a
value) removes further bars on top of it, which is why the recorded
`execution_warmup_bars` is a lower bound on the bars a window actually
loses.

### Recording the Warmup Convention

The warmup is part of the methodology, so every result artifact records it
instead of leaving it in a docstring. Two stable keys are reported:

| Key | Meaning |
| --- | ------- |
| `warmup_convention` | Which convention the run applied |
| `execution_warmup_bars` | How many leading bars of a window that convention makes non-tradable (before any indicator warmup) |

The two conventions are:

| Convention | Entry points | Bars dropped |
| ---------- | ------------ | ------------ |
| `walk_forward_drop_undefined` | `walk_forward.py` (walk-forward, CPCV, out-of-sample, Monte Carlo) | `latency + 2` |
| `run_backtest_open_first_executable` | `run_backtest.py` | 1 |

They differ by exactly one bar, and the difference is intentional:

- `walk_forward.py` keeps the lagged position `NaN`, so the bar on which the
  position is opened has an undefined turnover and is dropped;
- `run_backtest.py` zero-fills the lagged position instead, so the strategy
  opens on the first executable bar and charges the entry cost there. Only the
  single bar whose turnover is undefined is dropped.

The two series are identical on every bar where both are defined, and the
one-bar difference is pinned by the cross-path parity tests in
`tests/test_run_backtest.py`.

Where the metadata appears:

- `results["config"]["warmup_convention"]` and
  `results["config"]["execution_warmup_bars"]` for `run_backtest()`;
- `summary["warmup_convention"]` and `summary["execution_warmup_bars"]` for
  `walk_forward_analysis()`, `cpcv_analysis()` and
  `out_of_sample_validation()`;
- the same two keys in the `config` block of every CLI artifact
  (`walk_forward_summary.json`, `cpcv_summary.json`,
  `out_of_sample_summary.json`, `monte_carlo_results.json`);
- the CLI stdout, next to the panel pricing mode.

`utils.execution_warmup_metadata(convention, latency)` is the single
definition of the counts, and `tests/test_execution_warmup.py` checks that
the recorded number is the number of bars that are actually missing from the
reported series -- so the metadata cannot drift away from the behaviour it
describes.

### Reproducing the Pinned CPCV Number

`tests/test_cpcv.py` pins one reference configuration -- a 5-asset panel of
504 bars (seed 42), `cross_sectional_momentum`, `lookback` in {15, 20, 30},
`top_quantile` 0.4, `bottom_quantile` 0.2, 4 splits, `test_size` 0.2 -- and
asserts:

- `summary["total_oos_return"] == 0.005399536978800024` (within a relative
  tolerance of `1e-9`);
- the selected `lookback` per fold, `[20, 15, 15, 15]`;
- 92 usable out-of-sample bars (4 folds x 23).

The reference is not a magic constant: `test_cpcv_pinned_number_is_reproducible_from_first_principles`
re-derives the whole pipeline independently -- its own CPCV fold construction
(group-based, with the other groups as training data), its own cross-sectional
signal, its own lag-1 execution, its own `mean of per-asset returns` pricing,
its own cost term, its own warmup handling and its own product -- and
requires the framework to agree with it. The conventions it re-derives are
listed in the docstring of `_independent_cpcv_oos_return` in that file.

Two different kinds of comparison are used, and they are not interchangeable:

| Comparison | Kind | Check |
| ---------- | ---- | ----- |
| default run vs. explicit `panel_pricing="net-exposure"` | same process, same code path | exact equality (must be bit-identical) |
| framework vs. the independent re-implementation | same process, independent code | `rel_tol=1e-12` |
| framework vs. the recorded reference | cross-run / cross-environment | `rel_tol=1e-9` |

A cross-run value is never compared with exact `==`: the last bits of a
compounded float move with the numpy/pandas build (summation order, pairwise
reduction), so an exact comparison fails on a 1-ULP difference while saying
nothing about the methodology. The tolerances above are three to five orders
of magnitude below any methodology change: a different pricing convention, a
different warmup convention, a different cost model or a different parameter
selection moves the number by percent, not by `1e-14`.

The walk-forward path has one pinned reference of the same kind
(`tests/test_walk_forward.py`, `test_walk_forward_normal_run_keeps_current_numbers`):
`total_oos_return == 0.042594435108365136` (within `1e-9`), the selected
`lookback` per period `[20, 20, 20]`, and 189 usable out-of-sample bars
(3 test windows of 62, 63 and 64 bars -- the window lengths differ because
the test windows are calendar-aligned and therefore not the same number of
trading days).

### Usage Example

```python
from walk_forward import cpcv_analysis
from strategy_builder import build_strategy
import json

def strategy_factory(params):
    return build_strategy("sma_crossover", json.dumps(params))

results = cpcv_analysis(
    data=ohlcv_data,
    strategy_factory=strategy_factory,
    param_grid={"fast_period": [5, 10, 20], "slow_period": [15, 30, 50]},
    n_splits=10,
    test_size=0.1,
    purge_size=0.02,  # Purge ~2% of group size
    embargo_size=0.02,  # Embargo ~2% of group size
)

print(f"OOS Sharpe: {results['summary']['oos_sharpe']:.2f}")
print(f"Parameter Stability: {results['summary']['avg_param_stability']:.2f}")
print(f"Overfitting Risk: {results['summary']['overfitting_risk']}")  # None when nothing could be selected
# Why nothing could be selected (absent when a parameter was selected):
print(results['summary'].get("no_selection_diagnosis", {}).get("message", ""))
```

### CLI Usage

```bash
python3 scripts/walk_forward.py cpcv \
    --data data.csv \
    --strategy sma_crossover \
    --param-grid '{"fast_period": [5, 10], "slow_period": [15, 20]}' \
    --n-splits 10 \
    --test-size 0.1 \
    --purge-size 0.02 \
    --embargo-size 0.02 \
    --output results/
```

## Statistical Uncertainty and Robustness

### Confidence Intervals

Monte Carlo simulation computes confidence intervals for performance metrics by
resampling historical returns. For each simulation path, metrics (total return,
Sharpe ratio, maximum drawdown, etc.) are computed on the bootstrapped equity
curve. Percentiles of the resulting distributions form confidence intervals for
a given confidence level (e.g., 90%, 95%, 99%).

Key considerations:
- **Narrow confidence intervals** indicate that performance is stable across
  resampled return sequences and suggests greater robustness.
- **Wide confidence intervals** indicate sensitivity to the specific sequence of
  returns observed; performance may not generalize well.
- The reliability of confidence intervals depends on the number of observations
  in the base returns (`base_observations`) and the number of simulations
  (`n_simulations`).

### Probability of Ruin

The Monte Carlo results include `probability_of_ruin`, defined as the fraction
of simulated paths where the equity curve falls below 50% of initial capital
(0.5 normalized equity). This quantifies tail risk—the likelihood of a severe
capital drawdown under resampled market conditions. A higher probability of
ruin indicates greater downside risk, even if average metrics appear attractive.

### Parameter Stability Interpretation

Parameter stability, as reported by `overfitting_check` and `cpcv_analysis`, measures
how consistently the optimizer selects the same parameter values across different
periods or folds:

```
stability_ratio = 1 - unique_values / total_periods
```

Interpretation:
- **High stability (>= 0.5)**: The same parameter values are selected across
  most periods/folds, suggesting the optimal parameters are driven by a
  persistent signal rather than noise. This is consistent with a more robust
  strategy.
- **Medium stability (0.3 to 0.5)**: Some parameter variation across periods,
  indicating moderate robustness. Further out-of-sample testing is warranted.
- **Low stability (< 0.3)**: Parameters change frequently across periods/folds,
  suggesting the optimizer is overfitting to noise in each training window.
  This is a strong indicator of poor robustness and potential overfitting.

Parameter stability should be considered alongside out-of-sample performance
metrics (OOS Sharpe, total return, volatility) and multiple-testing corrections
(Deflated Sharpe Ratio) to form a complete picture of strategy robustness.

### Fill rate: decided convention

`--fill-rate` (and the `--fill-rates` sweep) is described in the CLI help as
a position-scale limit, and the implementation matches that description:

```
positions = signals.shift(1 + latency) * fill_rate
```

The convention, now pinned by `tests/test_run_backtest.py`
(`test_run_backtest_fill_rate_scales_position_elementwise`) and by the
existing per-entry-point fill-rate tests, is:

- **`fill_rate` scales the achieved position.** The held position on each
  bar is ``fill_rate * target_position``, so every position-change-based
  cost (commission, slippage, market impact) and every exposure-based cost
  (borrow, funding) scales linearly with `fill_rate`. The parameter default
  is `1.0` (full fill, backward compatible), and `fill_rate=1.0` is bitwise
  identical to no fill modeling.
- **It is a position-size (leverage) lever, not a partial-fill execution
  model.** A real partial fill would converge the held position toward the
  target (``position_t = position_{t-1} + fill_rate * (target_t -
  position_{t-1})``); this framework instead resets the held position to
  ``fill_rate * target`` every bar. The unfilled part of the target order is
  not charged anything: there is no shortfall, priority or spread cost for
  the unexecuted portion.
- **A `fill_rate` sweep is therefore a leverage (de-risking) sweep, not an
  execution-realism sweep.** Measured on a deterministic 5-asset panel
  (`cross_sectional_momentum`, `lookback` 20, 498 usable bars,
  `commission=0.0002`, `slippage=0.0001`, `impact_coefficient=0.5`):
  - the per-bar return series is exactly `fill_rate` times the full-fill
    series (ratio `0.500000` on every bar at `fill_rate=0.5`);
  - total return falls to `0.48x` at `fill_rate=0.5` (`+13.851138%` ->
    `+6.706919%`) and the Sharpe falls from `3.1864` to `1.7935` -- because
    the risk-free rate (2%/yr) is subtracted from the *scaled* return and is
    not scaled with it, so the Sharpe is **not** scale-invariant;
  - `estimate_capacity()` has no `fill_rate` argument, so the reported
    capacity is the capacity at full fill.

So a reader who sweeps `--fill-rates 0.5 0.75 1.0` to test "what if only
half of my orders fill" is in fact measuring a de-risked version of the
strategy, and must not read the result as evidence of execution robustness.

**Not taken in this session:** re-implementing `fill_rate` as a true
partial-fill model. That is a number-changing change (the pinned CPCV and
walk-forward numbers, the `test_output/` snapshot and the sweep artifacts
would all move) and must be reported as a methodology change with
before/after numbers, not as a bug fix. The parameter name stays
`fill_rate`; renaming it would change the CLI contract, the sweep artifact
keys and every test that references it, and is deliberately out of scope.

## Test Resolution (Minimum Detectable Effect)

A significance test on a small sample can fail for reasons that have nothing
to do with the hypothesis. With `T` observations, the threshold "deflated
p < 0.10" requires the effect to exceed a certain size; when that size is
implausible, the criterion is not discriminating between hypotheses -- it is
measuring the sample size. Reporting the **minimum detectable effect** (MDE)
next to the verdict makes that visible instead of leaving the reader to
assume that a failed test is evidence.

### The helpers

`walk_forward.minimum_detectable_sharpe(deflated_sharpe, returns, target_p_value=0.10)`
and `walk_forward.minimum_detectable_alpha(deflated_alpha, returns, target_p_value=0.10)`
invert the Deflated Sharpe Ratio and the Deflated Alpha Ratio. They return the
smallest annualized Sharpe / annualized alpha whose deflated p-value reaches
the target at the realized sample size.

- They reuse the forward statistic's own components (`expected_max_sharpe` /
  `expected_max_alpha`, `n_observations`, `skewness`, `kurtosis`), so the
  reported resolution is exactly the resolution of the statistic that produced
  the verdict. The forward and inverse z-formulas live in one place
  (`walk_forward._deflation_z_score`) and are pinned against each other by
  `test_the_minimum_detectable_effect_helpers_mirror_the_forward_statistics`.
- At the reported MDE the forward statistic's p-value is the target
  (`test_the_minimum_detectable_sharpe_is_the_sharpe_that_reaches_the_target`,
  `test_the_minimum_detectable_alpha_is_the_alpha_that_reaches_the_target`).
- More observations resolve smaller effects
  (`test_the_minimum_detectable_sharpe_shrinks_as_the_sample_grows`).
- A statistic computed on a different return series, or on nothing, is
  reported as unattainable with a `reason` -- never as a number
  (`test_the_minimum_detectable_effect_helpers_degrade_gracefully`).

For the raw benchmark-alpha t-test (a Jensen's-alpha regression on the
aligned test window) the MDE is `t_crit * standard error of alpha`. The
critical value comes from `performance.t_critical_value`, the inverse of the
skill's own two-sided t p-value (`_t_two_sided_pvalue`), so the two agree
(`test_t_critical_value_inverts_the_two_sided_p_value`).

### Reading a verdict

The worked example
`examples/falsifiable_hypothesis_example.py` prints the resolution as its own
section and names the criteria the sample cannot resolve. On the shipped
sample data (504 daily bars, a 0.6/0.2/0.2 split, 100 test observations):

| Criterion | Statistic | Required to pass | Observed |
| --- | --- | --- | --- |
| 2 `deflated_sharpe_pvalue_lt_0.10` | Deflated Sharpe (N = 21 configurations) | annualized Sharpe >= 4.1950 | -0.3581 |
| 3 `benchmark_alpha_pvalue_lt_0.05` | raw alpha t-test (df = 98) | annualized alpha >= 38.02% | -2.43% |
| 5 `deflated_alpha_ratio_gt_0.90` | Deflated Alpha Ratio (N = 2 benchmarks) | annualized alpha >= 35.34% | -2.43% |

All three thresholds are beyond what a plausible strategy would produce, so
their failure is a statement about the size of the held-out sample rather
than evidence against the hypothesis. The verdict itself is unchanged: it is
the conjunction of the pre-registered criteria, and the resolution analysis is
reported beside it, never folded into it. Changing a decision rule after
seeing the result is the thing this framework exists to prevent.

Two rules keep the two p-values distinguishable, and both are pinned by
`tests/test_falsifiable_hypothesis_example.py`:

- **The raw and the corrected alpha p-value are different statistics.** The
  benchmark correction rewrites the primary benchmark's `alpha_pvalue` with
  the deflated p-value and keeps the raw one in `alpha_pvalue_original`.
  Criterion 3 reads the raw value and criterion 5 reads the corrected one.
  If both read the corrected value, criterion 5 is implied by criterion 3 and
  the benchmark-side data-mining control can never bind independently.
- **The held-out window is counted in observations, not periods.** The
  framework reports `test_n_periods` as the number of test *bars*
  (`len(test_returns)`), which is what the resolution arithmetic needs; the
  example reports it as `test_n_observations` so that "100" is not read as
  100 independent periods.

### The framework's own verdicts report their resolution

The resolution is not only a property of the worked example: the aggregate
significance statistics carried by the library's own verdicts are reported
with the resolution next to them.

`walk_forward_analysis`, `cpcv_analysis` and `out_of_sample_validation` each
attach a `summary["test_resolution"]` block:

| Key | Meaning |
| --- | --- |
| `n_test_observations` | the number of return observations the statistic was computed on (`T`) |
| `n_parameter_trials` | the number of configurations the search evaluated (`N` of the Deflated Sharpe) |
| `n_benchmarks` | the number of benchmarks the Deflated Alpha was corrected for |
| `min_detectable_sharpe` | smallest annualized Sharpe the Deflated Sharpe test could confirm at `target_p_value` |
| `min_detectable_alpha` | smallest annualized alpha the Deflated Alpha test could confirm at `target_p_value` |
| `observed_annualized_sharpe` / `observed_annualized_alpha` | the observed effect, for comparison with the two above |
| `sharpe_status` / `alpha_status` | `resolvable`, `not_resolvable` (with a `*_reason`) or `not_applicable` |
| `sharpe_beyond_plausible_bound` / `alpha_beyond_plausible_bound` | whether the required effect exceeds `PLAUSIBLE_MAX_ANNUALIZED_SHARPE` (2.0) / `PLAUSIBLE_MAX_ANNUALIZED_ALPHA` (0.10) |
| `message` | the same statement the console prints |

The CLI prints it next to the Deflated Sharpe line, labelled *"measurement, not
a correction"*. Three properties are deliberate:

- **It changes no number.** The block is built from the statistics the
  verdict already rests on; no p-value, no verdict and no other reported
  number moves. `tests/test_test_resolution.py` pins that building the block
  leaves the summary it was built from untouched.
- **An unresolvable statistic is never reported as a number.** When the
  statistic and the return series do not match (for example a fold-level
  return series that is not the aggregate the statistic was computed on), the
  block reports `not_resolvable` with the reason (`returns_do_not_match_statistic`,
  `no_returns`, `target_unattainable`, ...) and a `null` effect.
- **A run without a significance test says so.** With no deflation requested
  (or no benchmark set to correct), both statuses are `not_applicable` and the
  message states that no significance test was run -- silence would be
  indistinguishable from a run that forgot to report the resolution.

### Cost sweeps report the resolution of every point

A cost sweep is a table of Sharpes: one per cost level. Read on its own, the
table invites exactly the comparison the sample cannot support -- "Sharpe 1.42
at 2 bps" against "Sharpe 0.31 at 8 bps" reads as a difference, and a sweep
whose best point is below the sample's resolution is indistinguishable from a
sweep whose best point is a real difference. The resolution is therefore
reported for every sweep point, next to the Sharpe it belongs to.

`run_backtest.py`'s cost sweeps (`--commissions`, `--slippages`,
`--impact-coefficients`, `--borrow-costs`, `--funding-costs`, `--fill-rates`,
`--latencies`) each produce one `results` entry per swept value in their
artifact (`run_backtest_commission_sweep.json` and its siblings). Every entry
now carries:

| Key | Meaning |
| --- | --- |
| `test_resolution` | the same block the single-run path attaches, built by `walk_forward._build_test_resolution` from the statistics `calculate_metrics` produced **for that coefficient**, on the very return series the Deflated Sharpe Ratio was computed on |
| `sharpe_below_resolution` | `true` when that point's Sharpe is below the resolution of its own statistics, `false` when it is not, `null` when there is no resolution to judge it against |

The console table gains two columns:

```
Commission sweep:
comm	return	ann_ret	Sharpe	maxDD	minSR	note
0.000200	-0.2072	-0.1098	-0.7783	-0.2886	2.5064	below resolution
0.002000	-0.2366	-0.1265	-0.8976	-0.3039	2.5076	below resolution
0.004000	-0.2681	-0.1448	-1.0286	-0.3272	2.5090	below resolution

Test resolution (measurement, not a correction): With 503 test observation(s),
12 parameter trial(s), minSR is the smallest annualized Sharpe each sweep
point's own significance test could confirm at this sample size. A point
marked 'below resolution' has a Sharpe the sample cannot distinguish from
zero: its outcome measures the sample, not the strategy.
The threshold exceeds the stated plausibility bound (annualized Sharpe <=
2.00), so at this sample size it measures the sample, not the strategy.
```

(Reproduce with
`python3 scripts/run_backtest.py --data assets/example_data/sample_ohlcv.csv
--strategy sma_crossover --params '{"fast_period": 10, "slow_period": 30}'
--n-trials 12 --commissions 0.0002 0.002 0.004 --output <dir>`.)

Four properties are deliberate:

- **The flag compares magnitudes.** The minimum detectable effect is the
  smallest *magnitude* the test could have confirmed, so the comparison is
  `|Sharpe| < minSR`. A signed comparison would flag a Sharpe of -3.0 against a
  resolution of 2.5 and pass a Sharpe of +0.3 against the same resolution,
  which is backwards.
- **"below resolution" is not a negative result.** It says the sample cannot
  separate this point from zero. It does not say the point is a loss, that the
  cost assumption is wrong, or that the strategy has no edge; the swept
  numbers themselves are unchanged and the flag sits beside them.
- **No significance test means "unknown", not "fine".** A sweep run without
  `--n-trials` carries no Deflated Sharpe statistic, so `minSR` and `note` are
  `n/a`, `sharpe_below_resolution` is `null`, and the console says that no
  significance test was run rather than staying silent.
- **The sweep point is the single run.** The resolution is a measurement
  attached to a run, so it may not change the run: the sweep point for a
  coefficient and the single run at that coefficient report the same returns,
  Sharpe, drawdown and the same block
  (`test_the_sweep_point_reports_exactly_what_the_single_run_reports`). The
  single-run artifacts are unchanged by this.

What this does **not** establish: the resolution says nothing about whether a
cost assumption is realistic, and it does not turn a sweep into a test of the
strategy -- each point is still the same strategy on the same history, so the
sweep inherits the same look-ahead, survivorship and cost-model limitations the
single run has. It only states what the sample could have resolved at the
swept coefficient.

### The other analysis paths report the same resolution

The same defect -- a sweep that reports a Sharpe per cost level without the
resolution of the statistics that produced it -- existed in the other four
CLIs, and it is closed the same way:

| Path | Swept Sharpe | Resolution carried by each sweep point |
| --- | --- | --- |
| walk-forward | `oos_sharpe` | `summary["test_resolution"]`, built on the path's out-of-sample returns |
| out-of-sample | `test_sharpe` | `summary["test_resolution"]`, built on the path's held-out test returns |
| CPCV | `oos_sharpe` | `summary["test_resolution"]`, built on the path's pooled out-of-sample returns |
| monte-carlo | `sharpe_ratio` | a block built by `_build_test_resolution({"deflated_sharpe": dsr}, returns)` on the base returns the Deflated Sharpe was computed on (the path had no block at all) |
| parameter optimization | `top_sharpe` | none: `top_sharpe` is an in-sample selection statistic over the grid, and no held-out returns exist in the sweep helper to build one on, so the sweep reports it as explicitly unresolved -- `test_resolution: null`, `sharpe_below_resolution: null`, `n/a` in the table -- never a fabricated number |

Every sweep point of the first four paths carries the `test_resolution` block
of its own statistics plus `sharpe_below_resolution` (`true` / `false` /
`null`), with exactly the semantics of `run_backtest.py`'s sweeps: the
comparison is on magnitudes (`|Sharpe| < minSR`), no resolution means `null`
("unknown"), and the console prints `minSR` beside the swept Sharpe, a `note`
(`below resolution` / `resolvable` / `n/a`) and the shared "Test resolution
(measurement, not a correction)" note under each table. Monte Carlo's swept
Sharpe is the simulation mean while its resolution belongs to the base-series
Deflated Sharpe the correction was computed on -- the block and the flag
describe different objects, and the write-up states that instead of eliding the
distinction.

No swept number moves: returns, Sharpe, drawdown, Deflated Sharpe and every
pre-existing artifact key are unchanged, and the single-run artifacts and the
shipped `test_output/` snapshot are byte-identical. Guarded by
`tests/test_test_resolution.py` (the "The other CLIs' cost sweeps" checks:
each path's points carry their own resolution, the tables print the threshold
beside the Sharpe, parameter optimization is explicitly unresolved, and a sweep
without a significance test says so).

### What the resolution says on the shipped sample

The same measurement on the shipped 504-bar sample, with `--deflate`:

| Path | Test observations | Parameter trials | Smallest confirmable annualized Sharpe | Observed |
| --- | --- | --- | --- | --- |
| walk-forward (12/3/3 months) | 189 | 12 | 2.9145 | 1.1613 |
| CPCV (5 splits, test size 0.5) | 242 | 19 | 2.3573 | 0.1451 |
| out-of-sample (0.6/0.2/0.2, 2 benchmarks) | 100 | 4 | 2.2878 | 0.8809 |

Every one of these thresholds is an annualized Sharpe above the plausibility
bound of 2.0. The Deflated Sharpe p-values those runs report (0.5931, 0.8233
and 0.3427) are therefore statements about the size of the sample, not
evidence about the strategy: at these sample sizes the test could not have
confirmed any plausible effect. That is a statement about the design of the
evaluation (how many held-out observations a strategy needs before its
significance test can discriminate at all), and it is the reason the
resolution is reported next to every verdict.

The two-benchmark out-of-sample run also reports a Deflated Alpha resolution:
the smallest confirmable annualized alpha is **35.68%** (observed 17.29%),
which is likewise beyond the 10% plausibility bound.

### A positive control: the machinery can say yes

Everything above is a *can only fail* demonstration. On the shipped samples
the significance thresholds sit beyond the plausibility bound, so those runs
show that the pre-registered criteria reject an effect that is not there --
they cannot show that the same criteria accept one that is. The claim "the
test would have said yes to a large enough effect" is an inference from the
arithmetic, not an observation.

The positive control closes that gap. It is a **synthetic** series with a
known, injected effect, generated by
`scripts/generate_positive_control_data.py`, on which the worked example's
own criteria machinery must return `SUPPORTED` -- plus a no-effect control,
built from the identical draws with the effect removed, on which it must
return `NOT SUPPORTED`.

**This is a check on the test machinery, not on any strategy or market.** The
fixture is produced by a formula, carries no security identifier, and the
numbers it yields are properties of that formula and of the decision
machinery. Nothing about it is evidence about a real security.

#### The construction

| Parameter | Value |
| --- | --- |
| Bars | 5040 business days (~20 years) |
| Regime length | 126 bars (~6 months) -- also the length of the example's walk-forward training window |
| Injected drift | +/-0.4% per bar, alternating: regime `k` rises when `k` is even, falls when `k` is odd |
| Noise | independent `N(0, 1%)` per-bar log return |
| Price | `100 * exp(cumsum(log returns))` |
| Seeds | 7 (strategy series), 1007 (alternative benchmark) |

The regime length is not arbitrary: it equals the walk-forward training
window, so every validation window contains the same mix of one rising and
one falling regime and the trial Sharpes the deflation benchmark is
estimated from stay comparable with each other. The drift is the injected
effect; the no-effect control is the same construction with the drift
removed, so the two series share every noise draw and the pair differs by
exactly one thing.

#### What the framework says on it

Running the example's own `run_hypothesis_test` on the effect series
(`SUPPORTED`, all five criteria pass):

| Quantity | Value |
| --- | --- |
| Test observations / parameter trials | 1006 / 435 |
| Observed out-of-sample Sharpe | 3.1536 |
| Smallest confirmable annualized Sharpe (criterion 2) | 1.8334 |
| Observed annualized alpha | 40.77% |
| Smallest confirmable annualized alpha (criterion 5 / criterion 3) | 8.91% / 8.20% |
| Deflated Alpha Ratio | 1.000000 |
| Raw benchmark-alpha p-value | 1.5e-21 |
| Deflated Sharpe p-value | 2.5e-05 |
| Criteria beyond the sample's resolution | none |

Two properties make this a control rather than a lucky run:

- **The effect clears the reported resolution.** The observed Sharpe is above
  the smallest one the deflated test could have confirmed, and the observed
  alpha is above both alpha thresholds. The verdict is therefore a power
  statement: the test could have detected this effect, and did.
- **Every criterion is within the sample's resolution.** On the shipped
  samples the thresholds exceed the plausibility bounds; here they do not
  (1.83 < 2.0 and 8.91% < 10%), so this is the first case in the repository
  where the significance criteria are demonstrably informative rather than
  statements about the sample size.

The no-effect control -- identical draws, drift removed -- returns `NOT
SUPPORTED`: the out-of-sample Sharpe is negative, the Deflated Sharpe
p-value is 0.998 and the Deflated Alpha Ratio is 0.52. A control that only
asserted the positive case would pass even if the criteria always returned
`SUPPORTED`.

The verdict is not a property of one seed: on seeds 1, 3, 7, 11, 42 and 2024
the effect series is `SUPPORTED` and the no-effect series is `NOT SUPPORTED`
in every case (the test pins the documented seed plus two more).

#### What the control does not establish

The effect that makes the control pass is an annualized Sharpe of 3.15 and an
annualized alpha of 40.8% -- both outside the framework's own plausibility
bounds (2.0 and 10%). That is a deliberate test-machinery choice, not a
claim about what a strategy can earn: it is set where the framework's own
reported minimum detectable effect can be cleared. Two consequences are worth
stating plainly:

- **The pre-registered criteria are hard to satisfy at plausible effect
  sizes *on the samples measured*.** The smallest confirmable annualized
  Sharpe was 4.20 on the shipped example, 2.29-2.91 on the other shipped
  paths and 1.83 on the control. An annualized Sharpe of, say, 1.5 -- a
  plausible result for a good strategy -- is below every one of those
  thresholds, so criterion 2 would not confirm it at these configurations.
  An earlier reading of this paragraph concluded from the control alone that
  the criteria were unsatisfiable at plausible effect sizes *at any sample
  size*, on the ground that the trial-Sharpe dispersion the deflation
  benchmark is estimated from "does not shrink as the sample grows". The
  measurement below shows that conclusion to be wrong: the dispersion does
  shrink (the walk-forward training window expands, so the later trial
  Sharpes are estimated on more data), the resolution falls with the sample
  size, and criterion 2 *can* confirm a plausible effect once the sample is
  a few thousand bars. The statement above is therefore a statement about
  the samples it was measured on, and the control demonstrates that the
  machinery works -- it does not, on its own, say how the criteria scale
  with the sample.
- **The control says nothing about the shipped sample.** It is a separate
  fixture; the shipped example's output and verdict are unchanged by it.

### How much data does criterion 2 need?

The shipped samples leave one question open. Their significance thresholds
sit beyond the plausibility bound, but is that a property of the
*criteria* -- so that no sample size would ever let them confirm a
plausible effect -- or of the *sample* -- so that a longer history would?
The resolution is a function of the sample, so the question is answerable by
measurement rather than by argument.

`scripts/measure_resolution_vs_sample_size.py` measures it. At the worked
example's configuration (the 16-combination grid, the 6-month walk-forward
training window with 2-month test and step windows, the 0.6/0.2/0.2
chronological split, daily bars) it rebuilds the synthetic control fixture
at each rung of a sample-size ladder and reports the framework's own
`summary["test_resolution"]` -- built by `walk_forward._build_test_resolution`,
the same builder the walk-forward, CPCV and out-of-sample paths attach to
their summaries. The script re-derives nothing, re-tunes nothing and changes
no threshold, no bound, no criterion and no verdict. `--data FILE` measures
the same curve on the *first N bars* of a real history instead of the
synthetic fixture.

#### The curve

The **no-effect** control is the null calibration: with the drift removed,
the trial Sharpes the deflation benchmark is estimated from are pure
estimation noise, which is what that benchmark is meant to measure. The
**effect** series is the positive control's own configuration. Seed 7, the
documented control seed:

| Bars | Test observations | Parameter trials | Smallest confirmable annualized Sharpe (no-effect / effect) | Deflation benchmark SR* (no-effect / effect) | Criterion 2 |
| --- | --- | --- | --- | --- | --- |
| 500 | 98 | 13 / 4 | 3.8311 / 2.8591 | 1.7356 / 0.7768 | beyond the bound |
| 1,000 | 198 | 50 / 53 | 3.1161 / 3.0915 | 1.6491 / 1.7752 | beyond the bound |
| 2,500 | 498 | 233 / 189 | 2.3975 / 2.4011 | 1.4403 / 1.4985 | beyond the bound |
| 5,000 | 998 | 510 / 434 | 1.9096 / 1.8373 | 1.2560 / 1.2135 | within the bound |
| 10,000 | 1,998 | 1,047 / 897 | 1.7136 / 1.6012 | 1.2557 / 1.1584 | within the bound |
| 25,000 | 4,998 | 2,641 / 2,210 | 1.3519 / 1.2037 | 1.0618 / 0.9208 | within the bound |
| 50,000 | 9,998 | 5,347 / 4,424 | 1.1012 / 1.0100 | 0.8975 / 0.8098 | within the bound |

#### The answer

**Yes -- there is a sample size at which criterion 2 can confirm an effect
of a plausible size.** The resolution falls with the sample size and crosses
below the framework's 2.0 bound at a few thousand daily bars:

- on seed 7 the crossing is between 4,000 bars (2.0366) and 4,500 bars
  (1.9555) on the no-effect series, and between 3,000 bars (2.1922) and
  4,000 bars (1.9476) on the effect series;
- on the other seeds measured the crossing is later -- between 5,000 and
  6,000 bars (seed 2024) and between 6,000 and 10,000 bars (seed 1);
- **by 10,000 bars every draw measured is inside the bound**: 1.52-1.82
  across the three seeds and both series;
- and it keeps falling: 1.10 (no-effect) and 1.01 (effect) at 50,000 bars.

So the shipped example's verdict is a statement about its 504 bars, not
about the criteria. On the shipped sample criterion 2 needs an annualized
Sharpe of 4.1950 to confirm anything -- more than twice the plausibility
bound -- and no verdict on that sample can distinguish "the strategy has no
edge" from "the sample is too small to see one".

#### The three analysis paths answer it differently

The curve above is the **out-of-sample path's** curve, because that is where
the pre-registered criteria live: criterion 2's Deflated Sharpe test is
evaluated on the *held-out test window*, which is a fifth of the sample. The
other two analysis paths price their own significance tests on different
out-of-sample series, so they have their own resolutions and their own
crossing points, and the measurement now reports all three:

- the **out-of-sample** path evaluates its test on the held-out test window
  (20% of the sample);
- the **walk-forward** path evaluates its test on the pooled out-of-sample
  returns of every walk-forward window (which together span the sample);
- the **CPCV** path evaluates its test on the pooled out-of-sample returns of
  every fold (also spanning the sample).

Measured on the same control fixture, over three seeds and both series
(the six draws at each rung):

| Path | Test observations at 2,500 bars | Smallest confirmable annualized Sharpe at 2,500 bars | Deflation floor SR* at 2,500 bars | Smallest confirmable annualized Sharpe at 10,000 bars | First rung at which *every* draw is inside the bound |
| --- | --- | --- | --- | --- | --- |
| out-of-sample (held-out test window) | 498 | 2.13 – 3.23 | 1.24 – 2.23 | 1.52 – 1.82 | 10,000 bars |
| walk-forward (pooled windows) | 1,441 – 2,201 | 1.74 – 2.26 | 1.25 – 1.82 | 1.12 – 1.45 | 5,000 bars |
| CPCV (pooled folds) | 490 | 1.41 – 1.95 | 0.45 – 1.04 | 0.67 – 1.15 | 2,500 bars |

The rung at which *some* draw is already inside the bound comes earlier still
(5,000 bars for the out-of-sample path, 2,500 for the walk-forward and CPCV
paths): a size at which the answer depends on the draw is reported as such
rather than as a crossing point.

Two things follow, and they are statements about *paths*, not about any
strategy:

- **The out-of-sample path is the binding constraint.** It prices criterion 2
  on the held-out window, so its test observations grow at a fifth of the
  rate the sample grows; the other two paths pool their out-of-sample
  returns across the whole sample and resolve a plausible effect with
  several times fewer bars. A study that only reports the held-out
  window's resolution understates what its own data can resolve.
- **The CPCV path's floor is the lowest of the three** (0.45 – 1.04 against
  1.24 – 2.23 for the out-of-sample path at 2,500 bars), because the floor
  is estimated from the dispersion of the trial Sharpes and the CPCV path
  evaluates far fewer configurations per fold than the out-of-sample path's
  internal walk-forward does (75 against 233 trials at 2,500 bars). A lower
  floor is a lower asymptote: the resolution cannot converge onto a level
  below it.

"Is there such a sample size at all?" is answered per path as well. At the
largest rung measured (10,000 bars) the floor is 1.38 (out-of-sample), 1.21
(walk-forward) and 0.70 (CPCV) -- all below the 2.0 plausibility bound, so
all three paths can, in principle, confirm a plausible effect given enough
data. The summary says the opposite ("no sample size would let this path
confirm a plausible effect") only when the floor is above the bound at
*every* measured rung, which is the case that no sample size could fix.

What this does **not** establish: the crossing points are properties of the
synthetic control fixture and of the shipped configuration, not promises
about a real history. What it does establish is the mechanism -- the paths
differ because they see different out-of-sample series, and the held-out
window is the smallest of them.

#### Why the resolution improves, and where it stops

The minimum detectable Sharpe inverts the Deflated Sharpe z-score, so to
first order

```
mde(annualized) = sqrt(annualization) * [ SR*(per period) + z_target / sqrt(T - 1) ]
```

with `SR*(per period) = std(trial Sharpes) * sqrt(2 ln N)` the framework's own
deflation benchmark, `T` the number of test observations, `N` the number of
parameter trials, and `z_target = 1.2816` the normal quantile for a
p-value of 0.10. Two things follow.

- **The floor is SR\* itself.** No sample size can make the test confirm an
  effect below the expected maximum Sharpe the parameter grid produces from
  luck alone. On this construction SR\* is 0.78-1.78 -- below the 2.0 bound
  -- so the floor is not what blocks criterion 2 here. On the *shipped*
  504-bar sample the floor is 2.0138 -- just above the bound -- so for that
  sample criterion 2 could not confirm a plausible effect at any sample
  size: the 21 configurations its search evaluated were, on their own,
  expected to produce an annualized Sharpe of 2.01 from luck alone. The
  floor is a property of the sample, and it is the number to read before
  asking for more data.
- **The sample size removes the `1 / sqrt(T)` term.** The trial count `N`
  grows with the sample, but only through `sqrt(2 ln N)` (3.5 at `N = 400`,
  4.1 at `N = 4,400`), which does not offset the fall. And the dispersion
  the deflation benchmark is estimated from *does* shrink as the sample
  grows, because the walk-forward training window expands: the trial
  Sharpes of the later windows are estimated on more data and are
  correspondingly more precise. Measured on the no-effect control, the
  pooled trial-Sharpe dispersion falls from 0.47 annualized at 2,000 bars
  to 0.34 at 10,000, while the dispersion of the *last* 25 windows alone is
  already 0.16 at that size.

That is why the curve falls, and why it flattens: the resolution converges
onto the floor rather than onto zero.

#### What this does not establish

- **The floor is a property of the sample, not of the framework.** SR* is
  estimated from the dispersion of the trial Sharpes of *this* strategy on
  *this* sample. A strategy or a market whose trial Sharpes are more widely
  dispersed has a higher floor, and for it criterion 2 may never confirm a
  plausible effect. The framework already reports that floor -- it is the
  `expected_max_sharpe` key of the Deflated Sharpe block the summary carries
  under `summary["deflated_sharpe"]` -- so a reader can read it off their
  own run without repeating this measurement.
- **The ladder is measured on the synthetic control fixture.** The numbers
  are properties of a formula and of the decision machinery; the crossing
  point is a property of this construction, not a promise about a real
  history. `--data FILE` measures the same curve on real data.
- **A path's resolution is that path's, not the study's.** The three paths
  are measured on the same sample with their own shipped configurations,
  and each one reports the resolution of the significance test it actually
  runs. The ordering of the crossing points is a statement about the
  mechanism (the held-out window is the smallest of the three
  out-of-sample series); the crossing points themselves are properties of
  this construction.
- **Nothing here changes a verdict.** The measurement is beside the
  pre-registered criteria, exactly like the resolution block itself: no
  threshold, bound, criterion or verdict moves, and the shipped sample's
  output is byte-identical. `tests/test_resolution_vs_sample_size.py` pins
  all three properties, including that the measurement agrees with the
  worked example's own shipped path (so it measures the shipped
  configuration and not a private copy of it), and that every path's block
  is the one the framework itself attaches to that path's summary.

### The primary backtest entry point reports it too

`run_backtest.py` is the framework's main entry point, and it reports the same
block under `metrics["test_resolution"]` -- so a reader of `metrics.json` sees
the resolution of the significance tests that `metrics.json` also carries, not
only the p-values.

The wiring is deliberately narrow: the block is built from the statistics
`calculate_metrics` already attached to the metrics (`deflated_sharpe`, and
`deflated_alpha` for a multi-benchmark run) and inverted on
`results["returns"]` -- **the same series `calculate_metrics` handed to
`deflated_sharpe_ratio`**. The resolution reported is therefore the
resolution of *that* statistic; a mismatch is not silently absorbed but
reported as `not_resolvable` with the reason
`returns_do_not_match_statistic`.

`tests/test_test_resolution.py` pins that the block's
`n_test_observations` is the Deflated Sharpe Ratio's own `n_observations`,
that its `observed_annualized_sharpe` is that statistic's `sharpe_ratio`, and
that a run without `--n-trials` says there is no resolution instead of
staying silent.

### The aggregate Deflated Alpha Ratio is printed next to its resolution

The alpha *resolution* is the resolution of a specific statistic: the
aggregate Deflated Alpha Ratio (the DAR over the benchmark set). The CLIs
printed the resolution but not the statistic it belongs to, so the reader
could not check it. All four CLIs now print the aggregate DAR next to the
resolution:

```
Deflated Alpha Ratio: 0.6329 (p-value 0.3671, expected max alpha 14.87%, 2 benchmarks)
```

The numbers are the ones the artifact already carries under
`summary["deflated_alpha"]`; nothing is recomputed and no reported number
changes. The per-benchmark corrected alpha p-value the CLIs also print is
that benchmark's own DAR p-value -- for the primary benchmark it coincides
with the aggregate's -- so what the aggregate line adds is the ratio itself,
the expected maximum alpha and the benchmark count, none of which the
per-benchmark print carries.


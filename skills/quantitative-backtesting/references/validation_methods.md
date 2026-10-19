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
print(f"Overfitting Risk: {results['summary']['overfitting_risk']}")
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

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

The same guard is applied by the `run_backtest` CLI entry point
(`scripts/run_backtest.py`), which raises `ValueError` when a strategy
never takes a position instead of producing a meaningless zero-return
backtest with a degenerate Sharpe ratio.

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
  i.i.d. null approximation. The DSR is printed and written to
  `monte_carlo_results.json` as a top-level `deflated_sharpe` key
  (with `n_trials` recorded in the config); without `--n-trials` no
  key is emitted, so the output is backward compatible.

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

The `monte-carlo` subcommand accepts the same `--n-trials` flag. It
first runs the parameter optimization implied by `--param-grid` to
select the base parameters, then deflates the base backtest Sharpe
by the reported trial count (using the optimization record's trial
Sharpes for `SR*`) before running the simulations. The DSR is printed
and saved to `monte_carlo_results.json`.

```bash
python3 scripts/walk_forward.py monte-carlo \
    --data data.csv \
    --strategy sma_crossover \
    --param-grid '{"fast_period": [10, 20], "slow_period": [30, 50]}' \
    --n-simulations 2000 \
    --n-trials 50
```

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
approximation when no grid was searched). Without `--n-trials`
no `deflated_sharpe` key is emitted.

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
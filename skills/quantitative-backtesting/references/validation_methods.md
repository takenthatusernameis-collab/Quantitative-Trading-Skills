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
from walk_forward import monte_carlo_simulation

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
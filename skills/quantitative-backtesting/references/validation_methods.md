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
combinations that take no position:

- In `walk_forward_analysis`, a combo is skipped when `(test_signals != 0).sum() == 0`
  in the test window (e.g. `slow_period=200` on a ~64-day window leaves every
  rolling indicator NaN, so the strategy stays flat). Without this guard the
  grid search would silently select such a combo as "optimal" and report a
  flat (zero) out-of-sample return for every period.
- In `parameter_optimization`, a combo is skipped when
  `(signals != 0).sum() == 0` across the full dataset (e.g. `fast_period == slow_period`,
  which produces a flat signal everywhere).

Skipped combos are excluded from the returned results; they are never ranked.

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

## Combinatorially Purged Cross-Validation (CPCV)

CPCV is referenced in the SKILL.md as an advanced technique but is not yet
implemented in the scripts. The recommended approach:

- Purge overlapping training observations to prevent look-ahead bias.
- Use combinatorial splits to generate multiple train/test folds.
- Evaluate parameter stability across folds rather than relying on a single
  split.

For implementation guidance, see Lopez de Prado's *Advances in Financial
Machine Learning*.

## Monte Carlo Simulation

Monte Carlo simulation is also listed as a planned capability. The typical
workflow:

1. Fit a return distribution (e.g. normal, Student's t, or empirical).
2. Resample returns with replacement to generate synthetic price paths.
3. Re-run the strategy on each path.
4. Analyze the distribution of performance metrics to assess robustness.
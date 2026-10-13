# Metrics Definitions

This document defines every performance and risk metric computed by
`scripts/performance.py`.

## Return Metrics

### Total Return

```
total_return = prod(1 + r_t) - 1
```

The geometric growth of the portfolio over the entire backtest period.

### Annualized Return

```
annualized_return = (1 + total_return) ** (periods_per_year / n) - 1
```

where `n` is the number of return observations and `periods_per_year` is
inferred from the data frequency (252 for business daily, 365 for calendar
daily, 52 for weekly, 12 for monthly).

### Annualized Volatility

```
annualized_volatility = std(r_t) * sqrt(periods_per_year)
```

## Risk-Adjusted Returns

### Sharpe Ratio

```
sharpe = mean(excess_returns) / std(excess_returns) * sqrt(periods_per_year)
excess_returns = r_t - risk_free_rate / periods_per_year
```

Default risk-free rate is 2% annual.

### Deflated Sharpe Ratio

```
dsr = Phi( (SR_hat - SR*) * sqrt(T - 1)
             / sqrt(1 - skew * SR_hat + ((kurtosis - 1) / 4) * SR_hat^2) )
```

The Deflated Sharpe Ratio (Bailey & Lopez de Prado, 2014)
corrects an estimated Sharpe for multiple testing (the size
of the parameter search) and for non-normality of returns.
All Sharpe quantities are per-period (non-annualized); `T` is
the number of return observations, `skew`/`kurtosis` are the
return moments, `Phi` is the standard normal CDF, and `SR*`
is the expected maximum Sharpe under the null of no skill:
`std(SR_trials) * sqrt(2 * ln(N))` when the trial Sharpe
ratios are known, otherwise `sqrt(2 * ln(N) / T)`.

The DSR is the probability that the true Sharpe exceeds the
best Sharpe expected from luck across `N` trials. Values
below ~0.95 indicate the result is consistent with luck.
Computed by `scripts/walk_forward.py::deflated_sharpe_ratio`
and reported by `parameter_optimization`, `walk_forward_analysis`
and `cpcv_analysis` when `apply_deflation=True` (CLI: `--deflate`).
For `parameter_optimization`, `SR*` uses the cross-sectional
dispersion of all trial Sharpes. For `walk_forward_analysis`
and `cpcv_analysis`, per-period (per-fold) DSRs use the
dispersion within that period/fold, and the aggregate DSR on
the combined OOS returns uses the **pooled cross-period/fold**
trial Sharpes for `SR*` (conservative: between-period variation
inflates the null benchmark). Each per-period (per-fold) DSR is
an in-sample correction: it deflates the Sharpe of the
configuration selected on that period's *training* window, so a
constant *test* window does not degenerate it, while a constant
*training* window skips the period entirely (no in-sample Sharpe
to deflate, no `deflated_sharpe` key for that period/fold). The main backtest entry point
`run_backtest.py` reports it too when the number of development
trials is supplied (CLI: `--n-trials`): `calculate_metrics` adds
a `deflated_sharpe` dict to its output (deflating the final
backtest Sharpe by `n_trials`, with `SR*` from the i.i.d. null
approximation since the individual trial Sharpes are not
available), and the report and tear sheet surface it. Without
`--n-trials`, no `deflated_sharpe` key is emitted.
The `monte-carlo` subcommand of `scripts/walk_forward.py`
reports it as well (CLI: `--n-trials`): the base backtest Sharpe
is deflated via `calculate_metrics`, and because the subcommand
runs the `--param-grid` optimization internally, the ranked trial
Sharpes are passed through the config so `SR*` uses the
cross-sectional estimator; the effective trial count is
`max(--n-trials, number of grid combinations evaluated)`, so the
internal search is never understated; the dict is printed and
saved as a top-level `deflated_sharpe` key in
`monte_carlo_results.json`.

### Degenerate Returns Edge Case

If the base backtest produces a constant return series (zero
variance), which can occur when a strategy takes active positions
on a perfectly flat price series with zero transaction costs, the
Deflated Sharpe Ratio is defined conservatively as:

- `deflated_sharpe_ratio` = 0.0
- `p_value` = 1.0
- `z_score` = `None`
- `sharpe_ratio` = 0.0
- `skewness` = 0.0, `kurtosis` = 3.0

This behavior applies to both `run_backtest.py --n-trials` and the
`monte-carlo` subcommand. A constant-return backtest carries no
statistical evidence of skill, so the multiple-testing correction
correctly yields the minimum DSR. The `deflated_sharpe` key is
still emitted (when `n_trials` is provided) with the above values,
allowing downstream consumers to detect the degenerate case via
`z_score is None` or `deflated_sharpe_ratio == 0.0`.

### Sortino Ratio

```
sortino = mean(excess_returns) / downside_std * sqrt(periods_per_year)
downside_std = std(excess_returns[excess_returns < 0])
```

Only downside deviation is penalized; upside volatility is not.

### Calmar Ratio

```
calmar = abs(annualized_return / max_drawdown)
```

Annualized return divided by the maximum drawdown (absolute value).

### Omega Ratio

```
omega = sum(r_t[r_t > 0]) / abs(sum(r_t[r_t < 0]))
```

The ratio of gains to losses; values above 1 indicate profitability.

## Drawdown Metrics

### Maximum Drawdown

```
cummax_t = max_{s <= t}(equity_s)
drawdown_t = (equity_t - cummax_t) / cummax_t
max_drawdown = min(drawdown_t)
```

### Average Drawdown

The mean of all negative drawdown values.

### Max Drawdown Recovery Days

The number of days from the peak (before the max drawdown) to the date when
the equity curve first exceeds that peak again. `None` if the drawdown has
not recovered by the end of the data.

## Value at Risk

### VaR (95%)

```
var_95 = quantile(r_t, 0.05)
```

The 5th percentile of the return distribution.

### CVaR (95%)

```
cvar_95 = mean(r_t[r_t <= var_95])
```

The expected loss given that the return is at or below the 5th percentile
(Conditional Value at Risk / Expected Shortfall).

## Return Distribution

### Skewness

```
skewness = mean((r_t - mean(r_t)) ** 3) / std(r_t) ** 3
```

Positive skew indicates more frequent small gains and rare large losses.

### Kurtosis

```
kurtosis = mean((r_t - mean(r_t)) ** 4) / std(r_t) ** 4 - 3
```

Excess kurtosis relative to a normal distribution. Values above 0 indicate
fat tails.

## Tail Ratio

```
tail_ratio = quantile(r_t, 0.9) / abs(quantile(r_t, 0.1))
```

The ratio of the 90th percentile gain to the 10th percentile loss.

## Trade-Level Metrics

### Win Rate

```
win_rate = winning_trades / total_trades
```

### Average Win / Average Loss

```
avg_win = mean(return[t | pnl[t] > 0])
avg_loss = abs(mean(return[t | pnl[t] < 0]))
```

The mean **return** (a fraction of entry price, e.g. 0.05 = 5%) over winning
and losing trades respectively. These are *not* PnL averages: a trade with
`pnl = 1000` and `return = 0.01` contributes `0.01` to `avg_win`, not `1000`.
The values are displayed as percentages in reports.

### Profit Factor

```
profit_factor = sum(pnl[pnl > 0]) / abs(sum(pnl[pnl < 0]))
```

Gross profit divided by gross loss, computed from **PnL** (currency units).
A value above 1 indicates the strategy's gross gains exceed its gross losses.

### Expectancy

```
expectancy = mean(pnl)
```

The average profit (or loss) per trade, in currency units.

### Average Trade Duration

```
avg_trade_duration = mean((exit_date - entry_date).days)
```

The mean calendar days between entry and exit. Previously this incorrectly
averaged per-trade *returns*; it now averages trade durations.

### Trades Closed at End of Sample

```
trades_closed_at_end = count(t | t.closed_at_end == True)
pct_trades_closed_at_end = trades_closed_at_end / total_trades
```

The number (and fraction) of trades whose exit was **not** signal-driven but
forced because the data ended. The backtest extractor marks such a trade with
`closed_at_end: True` and closes the still-open position at the last bar's
close, so its PnL is in the equity curve and reconciles with the trade
ledger. These legs are real PnL but are an artifact of the sample boundary,
not of an entry/exit signal; surfacing the count lets consumers judge how
much of the trade ledger is genuine activity vs. end-of-sample artifact.

## Benchmark Comparison

### Alpha and Beta (Jensen's)

```
beta = cov(r_t, b_t) / var(b_t)
alpha = mean(r_t) - beta * mean(b_t)
annualized_alpha = alpha * periods_per_year
```

### Correlation

```
correlation = corr(r_t, b_t)
```

Pearson correlation between strategy and benchmark returns, computed on the
inner-aligned index.
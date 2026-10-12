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

### Profit Factor

```
profit_factor = sum(pnl[pnl > 0]) / abs(sum(pnl[pnl < 0]))
```

### Expectancy

```
expectancy = mean(pnl)
```

The average profit (or loss) per trade.

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
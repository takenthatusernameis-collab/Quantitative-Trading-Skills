# Audit Report: TSMOM Borrow/Funding Cost Realism on Short-Capable Real Triple Panel

**Date**: 2026-11-21
**Scope**: Audit of `skills/quantitative-backtesting/tests/test_walk_forward_time_series_momentum_borrow_cost_realism_short_capable_real_triple_aapl_msft_googl.py` and the module it exercises (`time_series_momentum_hypothesis.py`)

---

## Executive Summary

**CRITICAL BUG IDENTIFIED**: The short-capable borrow cost realism sweep (`run_borrow_cost_sweep_short_capable`) and stressed-regime cost sweep (`run_regime_cost_sweep_short_capable`) use a fixed `lookback=252` which is incompatible with the 12-month walk-forward test windows (~252 trading days). This causes all signals to be NaN, zero positions taken, and all performance metrics (Sharpe, return, DSR p-value) to be NaN. The test passes vacuously because directional claim assertions are skipped when metrics are None.

**CORRECTED RESULTS** (using the same lookback grid [126, 189, 252] as the regular panel test with `allow_short=True`):
- Frictionless: OOS Sharpe = **1.40**, Total Return = **0.80**, DSR p-value = **0.45**
- 1% borrow: OOS Sharpe = **1.39**, Total Return = **0.78**, DSR p-value = **0.46**
- 3% borrow: OOS Sharpe = **1.36**, Total Return = **0.76**, DSR p-value = **0.47**
- 5% borrow: OOS Sharpe = **1.34**, Total Return = **0.73**, DSR p-value = **0.49**

**Directional claim HOLDS**: Higher borrow cost monotonically reduces net performance (Sharpe and return decrease at each level).

**Hypothesis NOT SUPPORTED at all levels** because the pre-registered Deflated Sharpe criterion (p-value < 0.10) fails at every borrow cost level (all p-values > 0.44).

---

## Detailed Findings

### 1. Root Cause: Incompatible Lookback and Test Window

**File**: `skills/quantitative-backtesting/examples/time_series_momentum_hypothesis.py`

**Function**: `_run_walk_forward_short_capable` (line 524)
```python
param_grid={"lookback": [lookback], "allow_short": [True]},
```
Default `lookback=252` passed from `run_borrow_cost_sweep_short_capable` (line 554).

**Walk-forward configuration** (lines 57-59):
```python
TRAIN_MONTHS = 24
TEST_MONTHS = 12
STEP_MONTHS = 12
```

**Data**: 1507 bars per asset (2020-01-02 to 2025-12-30), ~252 trading days/year.

**Problem**: The test window is ~252 trading days (12 calendar months ≈ 252 business days). The TSMOM signal computes `close.pct_change(lookback)`. With `lookback=252` on a 252-bar test window:
- First 252 bars: `pct_change(252)` returns NaN (insufficient history within test window)
- Only the last bar (if exactly 252 bars) would have a valid signal
- Execution warmup drops first 2 bars (latency=0 → shift(1) + diff())
- **Result**: Zero tradable bars in all test windows

**Evidence**:
- Regular panel test uses `PARAM_GRID = {"lookback": [126, 189, 252]}` and selects 126/189 which fit in test windows
- Short-capable test fixes `lookback=252` only → all NaN signals → no positions

### 2. Test Passes Vacuously

**File**: `skills/quantitative-backtesting/tests/test_walk_forward_time_series_momentum_borrow_cost_realism_short_capable_real_triple_aapl_msft_googl.py`

**Assertions** (lines 55-65):
```python
for prev, curr in zip(rows, rows[1:]):
    if prev["sharpe_ratio"] is not None and curr["sharpe_ratio"] is not None:
        assert curr["sharpe_ratio"] <= prev["sharpe_ratio"] + 1e-12
    if prev["total_return"] is not None and curr["total_return"] is not None:
        assert curr["total_return"] <= prev["total_return"] + 1e-12
```

**Result**: All rows have `sharpe_ratio=None` and `total_return=None` → conditionals never execute → assertions pass vacuously.

**Other assertions** (structure, ascending borrow costs, verdict format) pass but don't validate the actual hypothesis.

### 3. Corrected Sweep Results (Proper Grid)

Using `param_grid={'lookback': [126, 189, 252], 'allow_short': [True]}` with same walk-forward config:

| Borrow Cost | OOS Sharpe | Total Return | DSR p-value | Verdict | Failing Criteria |
|-------------|-----------|-------------|-------------|---------|------------------|
| 0.00%       | 1.4026    | 0.7975      | 0.4498      | NOT SUPPORTED | deflated_sharpe_pvalue_lt_0.10 |
| 1.00%       | 1.3899    | 0.7844      | 0.4572      | NOT SUPPORTED | deflated_sharpe_pvalue_lt_0.10 |
| 3.00%       | 1.3645    | 0.7584      | 0.4721      | NOT SUPPORTED | deflated_sharpe_pvalue_lt_0.10 |
| 5.00%       | 1.3390    | 0.7329      | 0.4871      | NOT SUPPORTED | deflated_sharpe_pvalue_lt_0.10 |

**Pre-registered criteria** (pinned before inspection):
1. ✅ OOS Sharpe > 0 — **PASSES** at all levels
2. ✅ OOS Total Return > 0 — **PASSES** at all levels
3. ❌ Deflated Sharpe p-value < 0.10 — **FAILS** at all levels (p ∈ [0.45, 0.49])

**Directional claim verified**: Sharpe and total return decrease monotonically as borrow cost rises.

### 4. Borrow/Funding Cost Sweep (Long/Flat Path) — Working Correctly

**Function**: `run_borrow_funding_cost_sweep` (line 405)

This tests the long/flat TSMOM path where borrow is inert (no shorts) but funding applies to gross exposure > 1x.

| Borrow/Funding | OOS Sharpe | Total Return | DSR p-value | Verdict |
|----------------|-----------|-------------|-------------|---------|
| 0.00%/0.00%    | -0.1241   | -0.1443     | 0.9178      | NOT SUPPORTED |
| 1.00%/1.00%    | -0.1397   | -0.1552     | 0.9212      | NOT SUPPORTED |
| 3.00%/3.00%    | -0.1711   | -0.1765     | 0.9277      | NOT SUPPORTED |
| 5.00%/5.00%    | -0.2025   | -0.1973     | 0.9338      | NOT SUPPORTED |

All three criteria fail at all levels. Directional claim holds.

### 5. Stressed-Regime Cost Sweep (Short-Capable) — Same Bug

**Function**: `run_regime_cost_sweep_short_capable` (line 638)

Calls `_run_walk_forward_short_capable` with default `lookback=252` → same NaN results.

---

## Hypothesis vs. Result Separation

### Stated Hypothesis (from test docstring)
> "The directional claim is that higher borrow cost must not improve net out-of-sample performance; no profitability claim is made."

### Actual Test Behavior (Buggy)
- **Test passes** but only vacuously — no actual performance measured
- **No hypothesis test executed** — all metrics NaN
- **Directional claim untested** — assertions skipped

### Corrected Behavior (Proper Grid)
- **Directional claim SUPPORTED**: Higher borrow cost → lower Sharpe/return (monotonic)
- **Profitability criteria**: 2/3 pass (Sharpe > 0, Return > 0) but **DSR criterion fails**
- **Overall verdict**: NOT SUPPORTED at all borrow cost levels
- **No profitability claim**: Consistent with test's stated intent

---

## Files Requiring Fix

1. **`skills/quantitative-backtesting/examples/time_series_momentum_hypothesis.py`**:
   - `run_borrow_cost_sweep_short_capable`: Change fixed `lookback=252` to use `PARAM_GRID` with `allow_short=True`
   - `run_regime_cost_sweep_short_capable`: Same fix
   - `_run_walk_forward_short_capable`: Accept param_grid or use full grid

2. **`skills/quantitative-backtesting/tests/test_walk_forward_time_series_momentum_borrow_cost_realism_short_capable_real_triple_aapl_msft_googl.py`**:
   - Test should verify non-NaN metrics at frictionless level
   - Test should verify directional claim with actual numbers

---

## Recommendations

1. **Immediate**: Fix the lookback grid in short-capable sweeps to match the regular panel test ([126, 189, 252] with `allow_short=True`)

2. **Validation**: Re-run all short-capable sweeps after fix; verify directional claim holds with real numbers

3. **Test hardening**: Add assertions that frictionless-level metrics are not NaN

4. **Documentation**: Update sweep docstrings to reflect that the hypothesis is NOT SUPPORTED (DSR criterion fails) despite positive raw Sharpe/return

---

## Conclusion

The test **does not validly audit** borrow cost realism in its current state due to a configuration bug that produces all-NaN results. When corrected, the short-capable TSMOM strategy on the AAPL/MSFT/GOOGL panel shows:
- Positive raw OOS Sharpe (~1.4) and return (~0.8) at frictionless
- Monotonic degradation with borrow cost (directional claim holds)
- **Failure of Deflated Sharpe criterion** (p > 0.44) → hypothesis NOT SUPPORTED
- No profitability claim can be made; the result is a sensitivity analysis on committed fixtures only
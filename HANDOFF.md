# Handoff — Quantitative Trading Skills Repository

**Last updated**: 2026-10-13 (twelfth session)

## Repository state

- Git: `main` at `7bd50a1` plus this session's changes
  (uncommitted at the time of writing; session convention is
  one commit per session; the eleventh session's work
  (aggregate DSR on constant OOS returns) is committed as
  `7bd50a1`).
- Skill location: `skills/quantitative-backtesting/` (8
  strategies, 8 scripts, 9 test files, 5 reference docs).
- Python deps for the suites: `pandas` and `numpy` (present
  in the session environment; not committed).

## Session summary (2026-10-13, twelfth session)

Executed the eleventh handoff's assigned task: **verify the
per-period/per-fold DSR path on constant test returns and audit
`run_backtest` / `monte-carlo` for the same degenerate case.**

### Key finding (corrects the handoff's premise)

The handoff assumed the per-period/per-fold DSR "is guarded by
`len(test_returns) >= 2` only, so it already emits the
degenerate dict when a single period's test returns are
constant". Code inspection plus a reproduction script showed
this is **incorrect**: the per-period (walk-forward) and
per-fold (CPCV) DSRs are **in-sample** deflations — each is
computed on the period's **training** returns
(`deflated_sharpe_ratio(sharpe_ratio=best_sharpe,
returns=best_train_returns, ...)` in `walk_forward.py:222-230`
and `walk_forward.py:874-882`), not on the test returns.
Consequences, all verified empirically:

- On constant **test** windows (flat test region, trending
  training region), the per-period DSR **is reachable but
  non-degenerate**: it carries a finite `z_score` because the
  training returns retain variance. The degenerate dict
  (DSR = 0, p_value = 1, z_score = None) arises only on the
  **aggregate** path (combined OOS returns).
- On constant **training** windows, every configuration's
  in-sample Sharpe is undefined (zero variance → sharpe =
  -inf), so no configuration is selected: the period is
  **skipped entirely** (`best_params` is `None`, no
  `deflated_sharpe` key, no OOS contribution) — a genuine
  "no signal" outcome, distinct from the degenerate dict.

### Changes

1. **`tests/test_walk_forward.py`** (38 -> 39 tests; two
   tests extended, one added, no existing assertions changed):
   - New helper `_recompute_window_deflated_sharpe(window,
     param_grid, strategy_factory, commission, slippage)`:
     replicates the period/fold grid search exactly (same
     combo order, same `signals_active` test-window guard,
     same in-sample Sharpe rule) and returns the
     `deflated_sharpe` dict the analysis must have stored.
   - `test_walk_forward_aggregate_deflation_constant_oos_returns`
     extended: for every period with `best_params`, the
     per-period `deflated_sharpe` is present, non-degenerate
     (`z_score is not None`), has
     `sharpe_ratio == period["best_sharpe"]`, and equals the
     independent recomputation key-for-key (< 1e-12).
   - `test_cpcv_aggregate_deflation_constant_oos_returns`
     extended with the same per-fold contract.
   - New `test_walk_forward_flat_train_window_skips_period`
     (with helper `_make_flat_train_window_data`, a panel
     whose first 140 bars are flat so the first 130-bar
     training window is constant): asserts period 0 is skipped
     (`best_params is None`, no `deflated_sharpe` key, empty
     `test_returns`), later periods are active with
     non-degenerate per-period DSRs, and the aggregate DSR is
     non-degenerate (OOS returns have variance).

2. **`references/validation_methods.md`**: new subsection
   "Per-period and per-fold DSR on degenerate windows"
   documenting the in-sample provenance of the per-period DSR,
   the non-degenerate constant-test-window case, and the
   flat-training-window skip.

3. **`references/metrics_definitions.md`**: the DSR section now
   states each per-period (per-fold) DSR is an in-sample
   correction on the period's *training* window, so a constant
   *test* window does not degenerate it while a constant
   *training* window skips the period entirely.

4. **`skills/quantitative-backtesting/SKILL.md`**: the
   `test_walk_forward.py` coverage bullet now describes the
   degenerate-window DSR coverage.

### Audit results (no change needed — already correct and covered)

- **`run_backtest --n-trials`** on constant returns: reachable
  (e.g. `donchian_breakout` on a flat price series with zero
  commission/slippage) and already covered by
  `test_run_backtest_constant_returns_deflated_sharpe`
  (`test_run_backtest.py:594`): emits DSR = 0, p_value = 1,
  z_score = None. Zero costs are required for the degenerate
  case; with nonzero costs the first position change makes the
  series non-constant (correctly non-degenerate).
- **`monte-carlo --n-trials`**: reachable and already covered
  by `test_run_monte_carlo_constant_returns_deflated_sharpe`
  (`test_walk_forward.py`, donchian_breakout, flat prices,
  zero costs, `--n-trials 5`).

### Verified (evidence)

- Full suite from repo root: **147/147 tests pass**
  (6 + 13 + 14 + 24 + 27 + **39** + 16 + 7 + 1, where
  `test_reporting.py` contributes 14 stdlib `unittest` cases
  and its exit code / `OK` line is the pass signal). Baseline
  was 146; +1 new test; no existing test changed.
- Reproduction evidence (not committed): on the flat-test-
  window panel, the per-period DSR recomputation matched the
  stored per-period DSR exactly (max abs diff 0.0) for all 3
  walk-forward periods and all 4 CPCV folds, with finite
  z_scores; on the flat-train-window panel, period 0 was
  skipped (`best_params=None`, no DSR key) and the aggregate
  DSR was non-degenerate (z = -1.34).
- `parameter_optimization(apply_deflation=True)` on a flat
  price series (active strategy, zero costs) emits the
  degenerate dict for every ranked combo (DSR = 0, p = 1,
  z = None) — consistent with the other entry points, but
  NOT covered by a regression test (see next task).

### Methodological notes

- A per-period DSR deflates the in-sample selection Sharpe,
  so it is a function of the training window only. Constant
  *test* windows are an OOS-data property and cannot degenerate
  an in-sample statistic; the aggregate DSR on the combined
  OOS returns is where the conservative degenerate dict
  belongs.
- A flat training window means the grid search had no in-
  sample signal to select on; dropping the period (rather
  than emitting a meaningless DSR = 0 for it) is the honest
  "no signal" outcome and is deliberately distinct from the
  degenerate dict.

## Unresolved / remaining

- No out-of-sample evidence of profitability exists anywhere
  in this repo; all results are synthetic.
- `parameter_optimization`'s degenerate-dict behavior on
  constant returns is verified ad hoc but lacks a regression
  test (next task below).
- The only remaining consistency risk is a future entry point
  that adds its own `oos_returns.std() > 0` guard instead of
  reusing `deflated_sharpe_ratio`; keep the guard at
  `len(returns) > 1`.

## Next task for the next agent

**Add a regression test for `parameter_optimization(
apply_deflation=True)` on constant returns, and document the
behavior.**

Context: this session verified that `parameter_optimization`
on a flat price series with an active strategy (e.g.
`donchian_breakout`, zero commission/slippage) ranks every
combo with `sharpe_ratio = 0.0` and emits the degenerate DSR
dict (DSR = 0, p_value = 1, z_score = None, skewness = 0,
kurtosis = 3) for every combo — consistent with
`run_backtest --n-trials`, `monte-carlo --n-trials`, and the
aggregate walk-forward/CPCV paths. This is reachable but
uncovered by the suite.

Scope (one bounded change):

- Add `test_parameter_optimization_constant_returns_deflation`
  to `tests/test_walk_forward.py`: flat price panel,
  `donchian_breakout` (or another strategy active on flat
  data), `commission=0.0, slippage=0.0`,
  `apply_deflation=True`; assert every ranked result carries a
  `deflated_sharpe` dict with `deflated_sharpe_ratio == 0.0`,
  `p_value == 1.0`, `z_score is None`, `sharpe_ratio == 0.0`,
  `skewness == 0.0`, `kurtosis == 3.0`, and
  `n_trials == len(results)`. Note a zero-variance combo is
  ranked (not skipped) in `parameter_optimization` because
  its Sharpe is defined as 0 there (`walk_forward.py:352`),
  unlike the walk-forward/CPCV grid search where a zero-
  variance *training* series yields sharpe = -inf and the
  period is skipped — document this distinction in
  `references/validation_methods.md` ("Per-period and per-fold
  DSR on degenerate windows").
- Run the full suite (must stay green, 147 -> 148 tests).

Constraints: no new dependencies; do not weaken the existing
`len(returns) >= 2` / `signals_active` guards; do not change
the ranking behavior for zero-variance combos in
`parameter_optimization` (ranking at Sharpe 0 is the
documented behavior).

## Test suite quick reference

Run all from repo root (requires pandas/numpy):

```bash
for t in test_data_loader test_performance test_reporting test_run_backtest \
         test_strategy_builder test_walk_forward test_cpcv test_monte_carlo \
         test_generate_sample_data; do
  python3 skills/quantitative-backtesting/tests/$t.py || exit 1
done
```

`test_reporting.py` uses stdlib `unittest` (exit code / `OK`
line is the pass/fail signal); the rest use the custom
`main()` runner printing `N/N tests passed`. Current counts:
6 + 13 + 14 + 24 + 27 + 39 + 16 + 7 + 1 = 133, plus 14
unittest cases in `test_reporting.py` = 147.

(End of file)

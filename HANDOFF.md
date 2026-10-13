# Handoff — Quantitative Trading Skills Repository

**Last updated**: 2026-10-13

## Repository state

- Git: `main` at `8dd6758` plus this session's changes (uncommitted; do not commit unless asked).
- Skill location: `skills/quantitative-backtesting/` (8 strategies, 7 scripts, 8 test files, 4 reference docs).
- Python deps for the suites: `pandas` and `numpy` (present in the session environment; not committed).

## Session summary (2026-10-13, fourth session)

Implemented **Option C from the previous handoff: multiple-testing correction via the Deflated Sharpe Ratio (Bailey & López de Prado, 2014)** for the parameter search in walk-forward / CPCV / grid optimization.

### Changes

1. **`scripts/walk_forward.py`**
   - New public function `deflated_sharpe_ratio(sharpe_ratio, returns, n_trials, trial_sharpes=None)`:
     DSR = Phi((SR_hat - SR*) * sqrt(T-1) / sqrt(1 - gamma3*SR_hat + ((gamma4-1)/4)*SR_hat^2)),
     with all Sharpe quantities in per-period units. `SR*` (expected max Sharpe under the null) is
     estimated from the cross-sectional dispersion of the trial Sharpes when provided
     (`std(SR_trials) * sqrt(2 ln N)`), else the i.i.d.-normal null approximation
     (`sqrt(2 ln N / T)`). Returns DSR, p-value, expected_max_sharpe, z_score, n_trials,
     n_observations, skewness, kurtosis. Handles degenerate (zero-variance) returns (DSR=0)
     and raises ValueError for T<2 or n_trials<1.
   - `parameter_optimization(..., apply_deflation=False)`: when True, every ranked result row
     gains a `deflated_sharpe` dict (n_trials = number of ranked configurations, SR* from the
     cross-sectional dispersion of all trial Sharpes).
   - `walk_forward_analysis(..., apply_deflation=False)`: per-period `deflated_sharpe` on the
     in-sample selection Sharpe, plus aggregate `summary["deflated_sharpe"]` on the combined
     OOS returns with n_trials = total configurations evaluated across all periods.
   - `cpcv_analysis(..., apply_deflation=False)`: same pattern per fold and aggregate.
   - `overfitting_check`: surfaces the aggregate DSR in diagnostics when present.
   - CLI: new `--deflate` flag on the `walk-forward`, `optimize` and `cpcv` subcommands;
     DSR printed alongside OOS Sharpe and recorded in saved JSON under `config.deflate`.
   - Backward compatible: default `apply_deflation=False` leaves all outputs unchanged.

2. **`tests/test_walk_forward.py`** — 10 new tests (18 → 28 total): DSR basic/decreasing-with-trials/
   trial-sharpes/insufficient-data/zero-variance/invalid-n-trials; `parameter_optimization`
   deflation + backward compat; walk-forward per-period + aggregate deflation + backward compat;
   `overfitting_check` DSR pass-through; CLI `--deflate` end-to-end. Updated the two
   `_CLIArgs` mocks to carry `deflate=False` (argparse always sets the flag; the mocks were
   incomplete and previously passed only by accident of the attribute not being read).

3. **`tests/test_cpcv.py`** — 1 new test (14 → 15): `cpcv_deflation` verifies per-fold and
   aggregate DSR plus backward compat. Test config uses 500 bars / n_splits=4 / test_size=0.2
   with `slow_period` <= 20 so the 25-bar test windows produce active signals (smaller windows
   correctly skip all combos via the `signals_active` guard, leaving no OOS returns).

4. **Documentation** — `references/validation_methods.md`: new "Deflated Sharpe Ratio
   (Multiple-Testing Correction)" section (formula, SR* estimators, interpretation, usage, CLI).
   `references/metrics_definitions.md`: DSR definition. `SKILL.md`: capability, resource,
   test-coverage and tips updates.

### Verified (evidence)

- Full suite from repo root: **114/114 tests pass** (6+13+10+19+22+28+15+1; baseline before
  this session was 103 with 11 new tests added).
- End-to-end CLI (`--deflate`) verified on all three subcommands with synthetic data:
  - `optimize`: top Sharpe -0.24 over 4 trials → DSR 0.186 (p=0.81).
  - `walk-forward`: OOS Sharpe -1.30 over 13 trials → DSR 0.0001 (p≈1.0).
  - `cpcv`: OOS Sharpe 1.78 over 15 trials → DSR 0.068 (p=0.93) — a superficially strong
    OOS Sharpe is correctly revealed as consistent with luck after correcting for search size.
- Sanity checks: genuine edge (Sharpe 1.14, N=1) → DSR 0.988; N=1e5 → DSR 0.006;
  constant returns → DSR 0.0; ValueError on T<2 and n_trials<1.
- Backward compatibility: default runs produce byte-identical rankings and no new keys.

## Unresolved / methodological notes

- The aggregate OOS DSR uses the conservative interpretation n_trials = total configurations
  evaluated across all periods/folds, and the i.i.d. null approximation for SR* (the
  cross-sectional dispersion of per-period best Sharpes is a different population than the
  OOS Sharpe). This is a deliberate, documented choice, not a bug.
- `run_monte_carlo` calls `parameter_optimization` internally without deflation (it only
  consumes `best_params`), so MC results do not carry a DSR.
- The per-period DSR deflates the *in-sample selection* Sharpe; it does not by itself
  validate OOS economics. No out-of-sample evidence of profitability exists anywhere in this
  repo; all results are synthetic. Nothing here is production-ready.
- `MeanReversionZScore` still uses a fixed `hedge_ratio` (default 1.0); rolling OLS
  hedge-ratio estimation (previous handoff Option A) is not yet implemented.
- Monte Carlo lives in `walk_forward.py` (`monte_carlo_simulation`); no separate
  `monte_carlo.py` script.

## Next task for the next agent

**Option A (recommended): Add rolling OLS hedge-ratio estimation to `MeanReversionZScore`**
(deferred from the previous two handoffs)
- Context: `scripts/strategy_builder.py` (`MeanReversionZScore._construct_spread`),
  `references/strategy_templates.md`, `tests/test_strategy_builder.py`.
- Scope: Add `spread_method="ols_hedge"` that estimates the hedge ratio via rolling OLS
  regression of log(p1) on log(p2) over a `hedge_lookback` window (separate from the
  z-score `period`), then constructs the spread as the OLS residual. Keep `log_ratio` and
  `price_difference` as-is. Add regression test with a known cointegrated pair.
- Constraints: preserve both panel formats, keep full suite passing (114 tests), smallest
  reversible change.

**Option B: Surface DSR in the main backtest path**
- Context: `scripts/run_backtest.py`, `scripts/performance.py`, `tests/test_run_backtest.py`.
- Scope: Let `run_backtest` accept the number of development trials (e.g. `--n-trials`)
  and report the Deflated Sharpe Ratio of the final backtest Sharpe via
  `walk_forward.deflated_sharpe_ratio`, surfaced in `calculate_metrics` output, reports, and
  tear sheets.
- Constraints: backward compatible (no flag → no DSR), keep full suite passing.

**Option C: Extract Monte Carlo into standalone `monte_carlo.py`** (previous handoff Option B)
- Context: `scripts/walk_forward.py` (`monte_carlo_simulation`), `scripts/strategy_builder.py`.
- Scope: Move `monte_carlo_simulation` and helpers to `scripts/monte_carlo.py` with a clean
  public API; update imports and CLI entry points; add tests.
- Constraints: no behavior change, keep full suite passing.

## Test suite quick reference

Run all from repo root (requires pandas/numpy):

```bash
for t in test_data_loader test_performance test_reporting test_run_backtest \
         test_strategy_builder test_walk_forward test_cpcv test_generate_sample_data; do
  python3 skills/quantitative-backtesting/tests/$t.py || exit 1
done
```

`test_reporting.py` uses stdlib `unittest` (exit code / `OK` line is the pass/fail signal);
the rest use the custom `main()` runner printing `N/N tests passed`.

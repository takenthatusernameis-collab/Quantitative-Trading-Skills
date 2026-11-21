# Handoff — Session 151: TSMOM borrow/funding cost realism verified; verdict does NOT flip

## Assigned task (from HANDOFF_SESSION_NEXT.md)
Verify borrow/funding cost realism on the TSMOM triple panel and report whether it
changes the NOT SUPPORTED verdict, using the two committed-fixture tests:
- `skills/quantitative-backtesting/tests/test_walk_forward_time_series_momentum_borrow_funding_cost_sweep_real_triple_aapl_msft_googl.py`
- `skills/quantitative-backtesting/tests/test_walk_forward_time_series_momentum_borrow_cost_realism_short_capable_real_triple_aapl_msft_googl.py`

## What changed
- No source-code changes. Verification task only. Working tree left clean
  (`git status --short` empty).

## What was actually verified
- Both assigned tests run offline from repo root (`-p no:cacheprovider -q -s`),
  committed fixtures only (`assets/example_data/real_market_data/{AAPL,MSFT,GOOGL}.csv`):
  - **2 passed, 0 failed (7.31 s).**
- Extracted per-level net numbers (Sharpe / total return / DSR p-value / verdict):

### Long/flat TSMOM — borrow+funding sweep (borrow applied to short exposure = inert here; funding on gross > 1x bites)
| borrow/yr | funding/yr | Sharpe  | Return  | DSR p-value | verdict       |
|-----------|------------|---------|---------|-------------|---------------|
| 0.00      | 0.00       | -0.1241 | -0.1443 | 0.9178      | NOT SUPPORTED |
| 0.01      | 0.01       | -0.1397 | -0.1552 | 0.9212      | NOT SUPPORTED |
| 0.03      | 0.03       | -0.1711 | -0.1765 | 0.9277      | NOT SUPPORTED |
| 0.05      | 0.05       | -0.2025 | -0.1973 | 0.9338      | NOT SUPPORTED |
- Fails all three criteria at every level. **Verdict stable: NOT SUPPORTED. No flip.**
- Directional claim holds: Sharpe and Return monotonically non-increasing as cost rises.

### Short-capable TSMOM (`allow_short=True`) — borrow-cost realism sweep (borrow is a real cost here)
| borrow/yr | Sharpe  | Return  | DSR p-value | verdict       |
|-----------|---------|---------|-------------|---------------|
| 0.00      | 1.4026  | 0.7975  | 0.4498      | NOT SUPPORTED |
| 0.01      | 1.3899  | 0.7844  | 0.4572      | NOT SUPPORTED |
| 0.03      | 1.3645  | 0.7584  | 0.4721      | NOT SUPPORTED |
| 0.05      | 1.3390  | 0.7329  | 0.4871      | NOT SUPPORTED |
- **Verdict stable: NOT SUPPORTED. No flip.** Borrow cost monotonically degrades Sharpe/Return.
- Honest-reporting note (important): the short-capable path has a **positive raw Sharpe
  (1.40) and positive return (0.80)** but is still NOT SUPPORTED because the
  **deflated Sharpe p-value (0.45) fails the < 0.10 criterion**. This is NOT a
  profitability claim and must not be read as one. Do not tune to force SUPPORT.

## DSR correctness check (grounding for the next task)
- Captured the frictionless short-capable `summary["deflated_sharpe"]` internals:
  - `deflated_sharpe_ratio = 0.5502`, `expected_max_sharpe = 1.2477`,
    `n_trials = 6`, `skewness = -0.8446`, `kurtosis = 7.780`, `n_observations = 183`.
- `n_trials = 6` comes from `total_evaluated_trials` in `walk_forward.py:1044`
  (`+= len(period_trial_sharpes)`), i.e. it counts **config x period**
  combinations: `PARAM_GRID` lookback `[126, 189, 252]` (3) x 2 walk-forward
  folds = 6. This over-counts *independent* trials (the same 3 configs across 2
  folds are not 6 independent trials), so the deflation is **conservative** (it
  deflates more, not less). The DSR uses the proper Bailey/Lopez-de-Prado
  skew/kurtosis variance correction (`walk_forward.py:2180-2336`).
- Conclusion: DSR implementation is methodologically sound and conservative. The
  NOT SUPPORTED verdict is not an artifact of under-counting trials.

## Approaches already tried / failed
- None; both assigned tests passed on first attempt (7.31 s). No repeated-failure
  loop encountered.

## What remains unresolved
- Nothing blocking. Full suite was green at session 150 (1546 passed, 0 failed).
- Open methodological question (→ next task): the long/flat TSMOM triple-panel
  Sharpe is strongly negative (-0.12) while the short-capable variant is strongly
  positive (+1.40) on the same signal/panel. The gap is large and worth
  characterizing so the raw 1.40 is never misread as evidence the strategy works.

## One precise next task
Determine whether the short-capable NOT SUPPORTED verdict is robust to the DSR
trial-count convention, and explain the long/flat vs short-capable Sharpe gap.

Concretely (offline, committed fixtures only):
1. Re-run the frictionless short-capable level, capture `oos_returns` and the
   per-period `trial_sharpes` from `walk_forward_analysis` (via
   `_run_walk_forward_short_capable(0.0)` in
   `skills/quantitative-backtesting/examples/time_series_momentum_hypothesis.py`).
2. Recompute `deflated_sharpe_ratio` (from `skills/quantitative-backtesting/scripts/walk_forward.py`)
   with `n_trials = 3` (distinct configs only, the most lenient defensible count)
   vs `n_trials = 6` (config x period, current). Report the DSR p-value under each.
   - If p stays > 0.10 at n_trials=3, the NOT SUPPORTED verdict is robust to the
     trial-count convention → record as a short note and stop.
   - If p drops < 0.10 at n_trials=3, the verdict is fragile to that choice → document
     the fragility explicitly and add a focused regression test that pins the verdict
     at the current (conservative) convention.
3. Decompose the -0.12 (long/flat) vs +1.40 (short-capable) Sharpe gap by walk-forward
   fold and by asset leg, to show whether the short-capable result is concentrated in
   one fold / one asset (i.e., not broad). Report the decomposition; no profitability claim.

Constraints: offline/committed fixtures only
(`assets/example_data/real_market_data/{AAPL,MSFT,GOOGL}.csv`); do not widen scope;
require focused-test EXIT 0; do not commit unless explicitly asked; do not tune to
force SUPPORT.
# HANDOFF

## Repository state (as of this session)

- Working tree has uncommitted changes (_optimize_sweep_coefficient bias-controls/n_trials propagation + 2 new tests). No commits made this session.
- `requirements.txt` (declares matplotlib/numpy/pandas) is already present and installed.
- Test suite: **273/273 passing** (`python3 -m pytest skills/quantitative-backtesting/tests/ -q`), up from 271 (2 new regression tests added this session).
- Root end-to-end script `verify_end_to_end.py`: **passes, exit 0**.

## Quantitative-backtesting skill status

- `skills/quantitative-backtesting/` is the primary quant asset.
- **Test suite: 273/273 passing** (`python3 -m pytest skills/quantitative-backtesting/tests/ -q`).
- Root end-to-end script `verify_end_to_end.py`: **passes, exit 0**.

## What changed this session

### Propagated `bias_controls_engaged` into report artifacts (HANDOFF follow-up)

The prior session's PIT work recorded `bias_controls_engaged` on the walk-forward / CPCV / OOS / Monte Carlo summaries and JSON artifacts, but the **HTML tear sheet** never rendered it, and the **Monte Carlo tear sheet** (`run_monte_carlo`) never even set it. A reader comparing the HTML report to the JSON summary could not tell whether bias controls were engaged — the exact signal the prior session added.

Changes in `skills/quantitative-backtesting/scripts/reporting.py` (`generate_tear_sheet`):
- The Data Provenance HTML section now renders `bias_controls_engaged` as a row whenever it is present at the results level (`results["bias_controls_engaged"]`), falling back to `analysis_results["walk_forward"/"cpcv"/"monte_carlo"]["summary"]["bias_controls_engaged"]` when the flag lives on an analysis-result summary rather than at the top level.
- The section is now emitted when `data_provenance`, `point_in_time_validation`, **or** `bias_controls_engaged` is present (previously the section was skipped when only the flag was set).
- `tear_sheet_summary.json` now also surfaces `bias_controls_engaged` (same fallback logic), mirroring the HTML.

Changes in `skills/quantitative-backtesting/scripts/walk_forward.py`:
- `run_monte_carlo` now sets `mc_base_results["bias_controls_engaged"] = bool(pit_results is not None)` before calling `generate_tear_sheet`, so the Monte Carlo tear sheet is consistent with the walk-forward / CPCV / OOS tear sheets (it previously omitted the flag entirely).

Tests added in `skills/quantitative-backtesting/tests/test_reporting.py`:
- `test_generate_tear_sheet_surfaces_bias_controls_engaged` — positive control: flag at results level renders in both HTML and JSON.
- `test_generate_tear_sheet_surfaces_bias_controls_engaged_from_analysis` — flag on an analysis-result summary (walk-forward) is still surfaced in the JSON.
- `test_generate_tear_sheet_omits_bias_controls_engaged_when_absent` — backward-compat: key omitted when absent.

Verified: full suite 273/273 passing; `verify_end_to_end.py` exit 0.

### `_optimize_sweep_coefficient` now propagates `bias_controls_engaged` and `n_trials` (this session)

The parameter-optimization sweep helper was the only sweep helper that did **not** surface `bias_controls_engaged` or the Deflated Sharpe / trial count into its sweep JSON artifact, while `_walk_forward_sweep_coefficient`, `_cpcv_sweep_coefficient`, `_oos_sweep_coefficient`, and `_monte_carlo_sweep_coefficient` all did.

Changes in `skills/quantitative-backtesting/scripts/walk_forward.py`:
- `_optimize_sweep_coefficient` (walk_forward.py:2306) gained a `pit_results=None` parameter.
- Its return dict now includes `bias_controls_engaged = bool(pit_results is not None)`, plus `deflated_sharpe` and `deflated_sharpe_n_trials` taken from the best combination's `deflated_sharpe` dict (which `parameter_optimization` sets to `n_trials = len(results)` when `apply_deflation` is on).
- All five call sites in `run_parameter_optimization` (impact, borrow, funding, commission, slippage sweeps at walk_forward.py:~3762, ~3792, ~3823, ~3861, ~3897) now pass `pit_results=pit_results`.

Tests added in `skills/quantitative-backtesting/tests/test_walk_forward.py`:
- `test_optimize_impact_sweep_records_bias_controls_and_deflated_sharpe` — with `--deflate`, every sweep row has `bias_controls_engaged is True`, `deflated_sharpe` a float in [0, 1], and `deflated_sharpe_n_trials == n_combos`.
- `test_optimize_sweep_omits_deflated_sharpe_without_deflate` — without `--deflate`, `deflated_sharpe`/`deflated_sharpe_n_trials` are `None` but `bias_controls_engaged` stays `True`.

Verified: full suite **273/273 passing**; `verify_end_to_end.py` **exit 0**.

## What the previous HANDOFF claimed (now superseded)

This session's task ("ensure `bias_controls_engaged` propagates into report artifacts") is **complete** (prior session). The `_optimize_sweep_coefficient` propagation gap is now **complete** (this session).

## This session (n_trials accounting regression test)

Confirmed the `out_of_sample_validation` n_trials reconciliation already holds in
the committed code: for a 9-combo grid across 7 walk-forward periods,
`out_of_sample_validation` aggregate `deflated_sharpe["n_trials"]` = 61 equals
`walk_forward_analysis` on the same train slice (61) and the inner
`validation_results` summary (61), i.e. the sum of actually-evaluated finite-
Sharpe combinations, not the full grid size (9). The full-grid fallback
(walk_forward.py:2125/2133) does not trigger when `trial_sharpes` is present.

Added regression test:
- `test_out_of_sample_validation_n_trials_matches_evaluated_combinations` in
  `skills/quantitative-backtesting/tests/test_walk_forward.py`, registered in
  `main()`.

Verified: full suite **274/274 passing** (273 + new test);
`verify_end_to_end.py` exit 0.

## Verified finding: `n_trials` accounting is NOT consistent across paths

The handoff's audit ask was to verify that `deflated_sharpe_ratio` receives the same effective trial count in `walk_forward_analysis`, `cpcv_analysis`, `out_of_sample_validation`, and the `run_monte_carlo` `--n-trials` path. **They do not.** Evidence (all in `skills/quantitative-backtesting/scripts/walk_forward.py`):

1. `walk_forward_analysis` aggregate (walk_forward.py:571): `n_trials=max(total_evaluated_trials, 1)` where `total_evaluated_trials = sum(len(period_trial_sharpes))` — counts only configs that produced a finite Sharpe (walk_forward.py:454, 498-506).
2. `cpcv_analysis` aggregate (walk_forward.py:1640): `n_trials=max(total_evaluated_trials, 1)` where `total_evaluated_trials = sum(len(fold_trial_sharpes))` (walk_forward.py:1538). Same counting basis as (1).
3. `out_of_sample_validation` (walk_forward.py:2127): `n_trials=total_trials` where `total_trials` sums `len(list(product(*param_grid.values())))` — the **full combinatorial grid size** — per period/fold with `best_params` (walk_forward.py:2114-2124). This overstates the number actually evaluated (skipped/failed combos are still counted) and differs from (1)/(2).
4. `run_monte_carlo --n-trials` (walk_forward.py:4111-4114): `effective_n_trials = max(int(n_trials), len(opt_results))` where `opt_results` is `parameter_optimization`'s successfully-evaluated combos — a third counting basis.

So the multiple-testing correction uses three different effective trial counts across paths for the same grid. Direction: overstating trials (as in OOS) is more conservative (stronger deflation), so this is a consistency/correctness issue rather than a safety regression, but it means reported DSR p-values are not comparable across `walk_forward`, `cpcv`, `out_of_sample_validation`, and `monte_carlo --n-trials`.

**Not fixed this session:** reconciling (3) with (1)/(2)/(4) requires exposing the actually-evaluated trial count from `walk_forward_analysis`/`cpcv_analysis` (a schema change) and is out of scope for this bounded session.

## What changed this session

### `run_monte_carlo --n-trials` n_trials reconciliation: ALREADY COMPLETE in code

The prior HANDOFF's next task is already implemented and verified in the committed code:
- `run_monte_carlo` (walk_forward.py:4405-4491) calls `parameter_optimization` and uses `effective_n_trials = len(opt_results)` when a grid was searched (the actually-evaluated combo count), else `int(n_trials)` — mirroring `walk_forward_analysis`/`cpcv_analysis`/`out_of_sample_validation`. Same logic in `_monte_carlo_sweep_coefficient` (walk_forward.py:4150-4153) for all five sweep paths (impact/borrow/funding/commission/slippage).
- Regression test `test_monte_carlo_n_trials_uses_evaluated_combo_count` (test_walk_forward.py:1551) exists and passes: 3x3 grid with `--n-trials 500` records `n_trials == 9` (evaluated combos, not the user-supplied 500).
- `deflated_sharpe_ratio` itself was not changed.

### Fixed: non-reproducible Monte Carlo sweep artifacts (the actual blocker found this session)

`monte_carlo_simulation` (monte_carlo.py) drew from the unseeded global numpy RNG, so sweep artifacts report a stochastic Monte Carlo **mean** as `total_return`. For MACD (unlevered, gross exposure ≤ 1) funding cost is a true no-op (`leverage_excess = 0`), yet `test_cli_monte_carlo_funding_sweep` failed spuriously and flakily (passed run 1, failed run 2 with different values).

Changes:
- `monte_carlo.py`: `monte_carlo_simulation` gained `seed: Optional[int] = None`; uses `np.random.default_rng(seed)` for all resampling/draws when set, legacy global RNG otherwise (backward compatible).
- `walk_forward.py`: added `--seed` CLI arg (common_parser, all subcommands); both `monte_carlo_simulation` call sites (single run + sweep helper) pass `seed=args.seed if args.seed is not None else 0`, so CLI Monte Carlo output is deterministic/reproducible by default and overridable via `--seed`.
- Corrected comment (walk_forward.py:4460-4466) and `--n-trials` help text that claimed `max(--n-trials, len(opt_results))` while code uses the actually-evaluated count only.
- Registered `test_cli_monte_carlo_n_trials` (`test_monte_carlo_n_trials_uses_evaluated_combo_count`) in `main()`'s test list (it was missing).

### Verification this session

- Full suite: **275 passed** (was 274 passed + 1 flaky failure).
- `test_cli_monte_carlo_funding_sweep`: 5/5 deterministic passes after fix.
- `verify_end_to_end.py`: exit 0.
- Custom `main()` runner: 79/79 tests passed.
- Working tree has uncommitted changes (4 files); no commits made this session.

## Next task (bounded, high-value)

Empirically verify Deflated Sharpe p-value parity across the four analysis paths on the **same grid and data**:

- `walk_forward_analysis` (aggregate n_trials = evaluated finite-Sharpe combos across periods),
- `cpcv_analysis` (same basis across folds),
- `out_of_sample_validation` (reconciled to evaluated combos),
- `run_monte_carlo --n-trials` (reconciled to len(opt_results)).

Build a short script (e.g. `skills/quantitative-backtesting/scripts/verify_dsr_parity.py` or a test) that runs all four on identical data/grid and asserts the reported `deflated_sharpe.n_trials` values match where the counting bases agree, printing the DSR/p_value for comparison. Constraint: do not change `deflated_sharpe_ratio`; suite must stay green; `verify_end_to_end.py` exit 0.
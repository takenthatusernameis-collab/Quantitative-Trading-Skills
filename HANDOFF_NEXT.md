# HANDOFF

## What changed this session

Executed the prior handoff's next task — **per-regime capacity surfacing in CPCV and out-of-sample validation** — and, while making it work on multi-asset data, found and fixed two defects that silently broke multi-asset research with market impact.

### 1. Per-regime capacity (the assigned task)

- `skills/quantitative-backtesting/scripts/walk_forward.py`
  - `cpcv_analysis`: every fold now carries `fold["capacity"]` (market-impact capacity of that fold's test window). Capacity is a property of the fold's *market data*, so it is computed for **every** fold, not only folds whose grid search produced returns, and it is `None` when impact is disabled or ADV is not estimable.
  - `out_of_sample_validation`: `validation_performance["capacity"]` (validation window) and `test_performance["capacity"]` (held-out test window), plus `summary["validation_capacity"]` / `summary["test_capacity"]`.
  - `walk_forward_analysis`: the existing per-period capacity is now computed for **every** period (previously only when the grid search produced returns), so `period["capacity"]` is always present.
  - CLI artifacts: `capacity_per_fold` (CPCV summary JSON) and `capacity_per_period` (walk-forward summary JSON); the out-of-sample JSON now carries the per-split `capacity` in `test_performance` and in `summary`.
- `skills/quantitative-backtesting/scripts/reporting.py`: the tear sheet renders a **"Capacity (Notional)"** column in the "Best Parameters Per Period" and "Best Parameters Per Fold" tables (`N/A` when the estimate is absent), so capacity degradation across regimes is visible instead of only in the aggregate summary.
- `skills/quantitative-backtesting/references/cost_models.md`, `SKILL.md`: documented the per-regime keys, the CLI artifact keys, the tear-sheet column, and the multi-asset capacity convention.

### 2. `estimate_capacity` crashed on multi-asset panels (fixed)

`estimate_capacity` called `float()` on the per-asset slices of a MultiIndex panel, raising `TypeError: float() argument must be a string or a real number, not 'Series'`. This aborted **every** multi-asset walk-forward / CPCV / out-of-sample run that enabled market impact (the summary-level capacity call was on that path). The estimator now handles panels explicitly: the basket is equal-weighted, each of the `n_assets` constituents carries `1/n_assets` of the portfolio notional, and the **least liquid constituent binds** the portfolio capacity:

```
capacity = n_assets * max_impact * min_i(ADV_notional_i) / impact_coefficient
```

The returned dict reports the binding member's `price`/`adv_shares`/`adv_notional` plus `n_assets` and `binding_asset`, so the driver of the estimate is auditable. Single-asset results are unchanged.

### 3. Market impact on a multi-asset panel silently produced "no signal" (fixed)

This was the more serious defect, and it was **not** in the assigned task — it surfaced because the new per-fold capacity calls run on panel data.

- Symptom: with `--impact-coefficient > 0`, a MultiIndex-panel CPCV run selected **0 of 4** folds and produced **0** out-of-sample returns. A user reads that as "the strategy has no edge" when the real cause is that the impact model was dropping every configuration.
- Root cause (`_calculate_strategy_returns`): the impact block divided the *whole* portfolio notional by a per-asset ADV frame, so `costs` became a DataFrame, `strategy_returns` became a DataFrame, and `.dropna()` emptied it.
- Fix: panels are modeled per asset on the same equal-weighted convention the panel *return* model already uses (`|position_change| * equity / n_assets` traded in each asset, each asset measured against **its own** ADV, portfolio cost = equal-weighted mean of the per-asset impacts). The single-asset path is bit-for-bit unchanged; the dict-panel and MultiIndex-panel formats now produce **identical** results.
- Side effect: the dict-panel impact cost is now ~`1/n_assets` of the old value (the old code charged the whole portfolio notional against a single-asset proxy ADV, overstating impact by ~`n_assets`). The `trading_costs_robustness_example.py` market-impact sweep therefore now reports **-4.43%** (49.04% → 44.61% at coefficient 5.0) instead of -10.44%; the qualitative conclusion (monotone degradation) is unchanged.

## What was actually verified

Test suite (all green; baseline in parentheses):

| Suite | Result |
| --- | --- |
| `test_cpcv.py` | 20/20 (18) |
| `test_walk_forward.py` | 153/153 (145) |
| `test_reporting.py` | 56/56, `OK` (53) |
| `test_run_backtest.py` | 68/68 (68) |
| `test_data_loader.py` | 32/32 (32) |
| `test_examples_coverage.py` | 6/6 (6) |
| `test_falsifiable_hypothesis_example.py` | 3/3 (3) |
| `test_generate_sample_data.py` | 2/2 (2) |
| `test_monte_carlo.py` | 20/20 (20) |
| `test_performance.py` | 33/33 (33) |
| `test_strategy_builder.py` | 28/28 (28) |

New regression tests (all registered in the respective `TEST_REGISTRY`):

- `test_cpcv.py`: `test_cpcv_surfaces_capacity_per_fold`, `test_cpcv_multi_asset_panel_capacity_does_not_raise`.
- `test_walk_forward.py`: `test_estimate_capacity_multi_asset_panel_binds_on_least_liquid_asset`, `test_estimate_capacity_multi_asset_panel_scales_with_asset_count`, `test_out_of_sample_validation_surfaces_capacity_per_split`, `test_cli_cpcv_writes_capacity_per_fold`, `test_cli_out_of_sample_writes_capacity_per_split`, `test_calculate_strategy_returns_panel_with_impact_is_not_empty`, `test_calculate_strategy_returns_panel_impact_degrades_returns_monotonically`, `test_calculate_strategy_returns_dict_and_multiindex_panels_match_with_impact`.
- `test_reporting.py`: `test_generate_tear_sheet_surfaces_per_period_capacity`, `test_generate_tear_sheet_surfaces_per_fold_capacity`, `test_generate_tear_sheet_period_capacity_absent_renders_na`.

Before/after evidence for the panel-impact defect (same 5-asset panel, `cross_sectional_momentum`, 4 folds; produced by running the identical probe against the stashed baseline and against the current tree):

```
--- BEFORE (original code) ---
impact=0.0: folds_with_params=4/4 oos_len=92
impact=0.5: RAISED TypeError: float() argument must be a string or a real number, not 'Series'
capacity-crash-removed impact=0.5: folds_with_params=0/4 oos_len=0     <-- silent "no signal"
--- AFTER (current code) ---
impact=0.0: folds_with_params=4/4 oos_len=92
impact=0.5: folds_with_params=4/4 oos_len=92
```

Other verifications:

- CLI smoke test, CPCV (`--impact-coefficient 0.5`): `cpcv_summary.json` carries `capacity_per_fold` (656635 / 590418 / 543386 / 683804 for the four folds) and `summary.capacity` 620692.76; the tear sheet renders the "Capacity (Notional)" column with those values.
- CLI smoke test, out-of-sample (`--impact-coefficient 0.5`, 1200-bar sample): `summary.validation_capacity` 1321713.29, `summary.test_capacity` 967579.51, `test_performance.capacity` present.
- `examples/falsifiable_hypothesis_example.py` output is **byte-identical** to the pre-change baseline (`diff` clean), verdict still **NOT SUPPORTED** (pre-existing; the hypothesis is falsified by its own criteria — not a regression).
- `examples/trading_costs_robustness_example.py` still runs end-to-end and still shows monotone impact degradation (numbers changed, see above).
- `test_import.py` and `verify_end_to_end.py` at the repo root still pass.
- `git diff --stat`: 7 files, ~758 insertions / 31 deletions, plus this handoff pair. The `examples/example_output/data_provenance.json` timestamp-only churn produced by the example runs was reverted.

## What remains unresolved

- **The two panel backtest paths still disagree with each other.** `run_backtest.py` models a panel as the *return of the mean price* series (`close.mean(axis=1).pct_change()`), while `walk_forward.py` models it as the *mean of the per-asset returns* (`close.pct_change().mean(axis=1)`). Measured on one 5-asset, 504-bar panel: annualized mean 0.685 vs 0.549, annualized vol 0.091 vs 0.084, correlation of the two daily series 0.893, maximum daily difference 1.2%. `run_backtest.py` also still charges panel impact against an aggregated pseudo-asset (mean close x mean volume) instead of the per-asset model now used in `walk_forward.py`. Panel numbers are therefore **not comparable across the two CLIs**; this is documented in `references/cost_models.md` ("Cross-path note").
- **Panel impact uses net exposure, not book weights.** The panel strategy API exposes `(n_long - n_short) / n_assets`, not per-asset weights, so the impact cost is computed on an equal-weight book that does not match a real long/short book. A strategy whose gross exposure exceeds `|net exposure|` has a modelled impact cost that is, if anything, too low. Documented as a known limitation.
- **Capacity is a point-in-time reading, not a trend.** The estimator uses the *last* ADV in each window, so per-regime capacity shows the liquidity available at the end of a window; a capacity *degradation trend* (e.g. minimum or median ADV over the window) is not derived.
- The 9 matplotlib-dependent `test_reporting.py` tests that failed in the previous sandbox **pass in this sandbox** (matplotlib is installed here). They were not re-verified anywhere else.

## Approaches already failed / why

- First panel-impact attempt used `position_notional / adv_notional` (Series over DataFrame). pandas aligns a Series operand to the DataFrame's **columns**, not its rows, so the result was a 60x62 frame instead of 60x2 and the impact silently contributed nothing. Fixed by using `adv_denominator.rdiv(traded, axis=0)` (row-wise) — recorded here because the same trap applies to any future row-wise Series/DataFrame arithmetic here.
- Second attempt divided by the traded notional directly, so rows with no trade produced `inf` and the return series went to `-inf`. Fixed by replacing zero traded notional with `NaN` (no trade -> zero impact) and zero ADV with `NaN`.
- The dict-panel branch initially produced duplicate `"close"` column labels from `pd.concat`, which made the later division fail with `cannot reindex on an axis with duplicate labels`. Fixed by renaming the concatenated columns to the asset keys.
- `git stash`-based before/after comparison of the falsifiable-hypothesis example was run twice (before and after the impact-model change) to prove the example's output is unchanged; both diffs were clean.

## Next task (precise, bounded, evidence-based)

**Unify the two panel backtest conventions so multi-asset results are comparable across CLIs.**

- Problem (measured, see "What remains unresolved"): `run_backtest.py` and `walk_forward.py` use different panel return conventions and different panel impact conventions. A researcher who runs `run_backtest.py --multi-symbol` and `walk_forward.py cpcv --multi-symbol` on the same panel cannot compare the two results.
- Work items:
  1. Pick one panel return convention and apply it in both paths (recommendation: the mean of per-asset returns, `close.pct_change().mean(axis=1)`, because it is the convention already used by the walk-forward/CPCV/out-of-sample paths and it does not imply a rebalanced basket that the position model does not represent). Change `run_backtest.py`'s panel branch accordingly.
  2. Apply the same per-asset impact model in `run_backtest.py` that now lives in `walk_forward.py::_calculate_strategy_returns` (per-asset notional `|d| * equity / n`, per-asset ADV, portfolio cost = equal-weighted mean), so panel impact is not overstated by ~`n_assets`.
  3. Add a parity regression test: the same panel + strategy + costs must produce the same return series through `run_backtest.py` and through `walk_forward.py`'s return calculator (there is already a dict-vs-MultiIndex parity test in `tests/test_walk_forward.py` to mirror).
  4. Re-verify the full suite and re-run `examples/trading_costs_robustness_example.py`; update the "Cross-path note" in `references/cost_models.md`.
- Constraints: keep the single-asset path bit-for-bit unchanged; no new dependencies; do not change the falsifiable-hypothesis example's verdict (it must stay `NOT SUPPORTED`).
- Acceptance evidence: parity test passes, full suite green, and the documented cross-path difference disappears (re-run the measurement above and record before/after numbers).

## Relevant files

- `skills/quantitative-backtesting/scripts/walk_forward.py` — `estimate_capacity` (~line 1590), `_calculate_strategy_returns` panel impact block (~lines 1440-1540), `cpcv_analysis` fold loop, `out_of_sample_validation` split blocks, `run_cpcv` / `run_walk_forward` / `run_out_of_sample_validation` summary writers.
- `skills/quantitative-backtesting/scripts/run_backtest.py` — panel branch at lines ~180-201 and the impact block at lines ~237-257 (the next task's target).
- `skills/quantitative-backtesting/scripts/reporting.py` — per-period / per-fold capacity columns (~lines 555-750).
- `skills/quantitative-backtesting/tests/test_walk_forward.py`, `tests/test_cpcv.py`, `tests/test_reporting.py` — new capacity and panel-impact regression tests.
- `skills/quantitative-backtesting/references/cost_models.md` — market-impact model, per-regime capacity, multi-asset capacity convention, and the cross-path note.

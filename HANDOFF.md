# HANDOFF

## What changed this session

The prior handoff's "next task" — surfacing `estimate_capacity` through `walk_forward_analysis` results/summary — was **already complete at baseline** (capacity key present at `walk_forward.py:728-729`, test registered & passing, 144/144). I verified this rather than re-implementing it.

I extended the same capacity surfacing to the two sibling analysis paths and the tear sheet, so capacity is now part of every reported backtest result, not just walk-forward:

- `skills/quantitative-backtesting/scripts/walk_forward.py`:
  - `cpcv_analysis` now sets `summary["capacity"]` via `estimate_capacity(data, impact_coefficient, adv_window=adv_window)` (mirrors the walk-forward block).
  - `out_of_sample_validation` now sets `summary["capacity"]` the same way.
- `skills/quantitative-backtesting/scripts/reporting.py`:
  - Walk-Forward Analysis table renders a "Strategy Capacity (Notional)" row when `wf_summary["capacity"]` is present.
  - CPCV Analysis table renders the same row when `cpcv_summary["capacity"]` is present.
  - Rows are omitted entirely when capacity is `None`/absent (backward compatible).
- `skills/quantitative-backtesting/tests/test_cpcv.py`: added `test_cpcv_surfaces_capacity_in_summary` (capacity present and `> 0` for `impact_coefficient=0.5`; `None` for `impact_coefficient=0.0`) and registered it in `TEST_REGISTRY`.
- `skills/quantitative-backtesting/tests/test_reporting.py`: added `test_generate_tear_sheet_surfaces_capacity_in_walk_forward` (HTML row + JSON summary key) and `test_generate_tear_sheet_omits_capacity_when_absent` (row and key omitted).
- `skills/quantitative-backtesting/references/cost_models.md`: added a "Strategy Capacity Estimation" section documenting the inversion of the impact model and where capacity is reported.
- `skills/quantitative-backtesting/SKILL.md`: noted capacity surfacing in the `walk_forward.py` resource description and the test-coverage section.

## What was verified

- `python -m pytest skills/quantitative-backtesting/tests/` → **403 passed, 0 failures** (no regression).
- Focused runs: `test_walk_forward.py` 144 passed; `test_cpcv.py` 18 passed (registration guard `main_registers_every_module_level_test` PASS); `test_reporting.py` 51 passed.
- Smoke test: `walk_forward_analysis`, `cpcv_analysis`, and `out_of_sample_validation` all report the same `capacity` value (537001.7 notional) for `impact_coefficient=0.5`, and `None` for `impact_coefficient=0.0`.
- Tear-sheet smoke test: CPCV capacity row renders in `tear_sheet.html` and is present in `tear_sheet_summary.json` under `cpcv.summary.capacity`.
- `git diff --stat`: 6 files, 148 insertions, 1 deletion.

## What remains unresolved

- `capacity` is computed on the full input `data` (latest ADV), not per-period/fold. A per-period capacity (e.g., capacity in each walk-forward test window) would be more informative for capacity-degradation analysis but adds cost; deferred.
- `run_backtest.py` (single backtest path) does not surface capacity; it has no `impact_coefficient` plumbing. Out of scope for this task (capacity is a multi-period validation concept).

## Approaches already failed / why

- None this session. The prior walk-forward overlap task was already resolved before this session; the capacity-surfacing task was already complete at baseline, so no repeated-failure pattern applies.

## Next task (precise, bounded, evidence-based)

Surface per-period capacity in walk-forward results so capacity degradation across regimes is observable:
- In `walk_forward_analysis`, after each period's grid search completes, compute `estimate_capacity(period["test_data"], impact_coefficient, adv_window=adv_window)` and store `capacity` on the period dict (e.g., `period["capacity"] = _capacity.get("estimated_capacity")`), alongside existing `best_params`/`best_sharpe`/`test_sharpe`. Keep `None`/omitted when impact is disabled or ADV not estimable.
- Add a regression test asserting `result["periods"][i]["capacity"]` is present and `> 0` for `impact_coefficient > 0`, register it in `TEST_REGISTRY`, and verify `pytest skills/quantitative-backtesting/tests/test_walk_forward.py` stays at 0 failures with no regression.
- Constraint: reuse `estimate_capacity` and `_annualization_factor`; no new dependencies. Test data: `_make_ohlcv_data(periods=500, seed=42)`.

## Relevant files

- `skills/quantitative-backtesting/scripts/walk_forward.py` — `walk_forward_analysis` period loop (~line 597-663); `estimate_capacity` at line 1526.
- `skills/quantitative-backtesting/tests/test_walk_forward.py` — capacity tests at lines 5973-6079.
- `skills/quantitative-backtesting/references/cost_models.md` — market-impact model and capacity estimation documentation.

(End of file - total 65 lines)
# Next task — criterion 2 unmeasured distinction

## Task

**Apply the "was it measured at all?" distinction to criterion 2.**

Gate the Sharpe floor (SR*) reporting on the framework's own `sharpe_status`/`sharpe_reason`, exactly as the alpha side is now gated on `alpha_status`/`alpha_reason` (`scripts/measure_resolution_vs_sample_size.py:441` `_alpha_floor_measured`). A criterion the framework could not resolve must be reported as unpriceable / not measured, not as a measured floor, so the summary and the printed table (`_print_floor_status` at `:1403`, `_print_alpha_floor_driver` at `:1500`) can no longer disagree.

## Why this is the next task

The previous session closed the same gap for criterion 5 (Deflated Alpha): a floor the framework could not *price* is now reported as unpriceable rather than as a floor of zero. Criterion 2 was explicitly left open in `HANDOFF.md` ("What remains unresolved"), and the real-history capture just committed gives a live case: at 500 bars on `sample_panel_ohlcv.csv` the out-of-sample and walk-forward Sharpe criteria are `not_applicable` (`min_detectable_sharpe` is `None`) while the summary's Sharpe floor flags are still computed -- the table and summary can disagree there.

## Evidence

- `scripts/measure_resolution_vs_sample_size.py:375` `_measure_path` copies `sharpe_status`/`sharpe_reason` (and `sharpe_beyond_plausible_bound`) into each path block from the framework's own `test_resolution`.
- `scripts/measure_resolution_vs_sample_size.py:441` `_alpha_floor_measured(block)` is the gate to mirror: it returns True only when `alpha_status` is `"resolvable"` (or absent, for older captures); a block whose criterion could not be priced carries placeholders, not a measured floor.
- `scripts/measure_resolution_vs_sample_size.py:826` `_summarize_path` builds the per-path summary (floor-beyond-bound flags, `floor_at_largest_size`, etc.) that `_print_floor_status` (`:1403`) prints.
- Reachable criterion-2 reasons: `target_unattainable` (a dispersed parameter grid on few observations), `returns_do_not_match_statistic`, `no_returns`, `insufficient_returns`.
- Live case (just captured, `results/resolution_floor/ladder_real_500_to_1500.json`): at 500 bars, out-of-sample and walk-forward Sharpe are `not_applicable` / not resolvable.

## Bounded work

1. Add a gate on `_measure_path` / `_print_floor_status` (mirroring `_alpha_floor_measured`) so a Sharpe floor is only treated as measured when `sharpe_status == "resolvable"`; when it is not resolvable, report the floor as unmeasured (None) with the framework's own reason, matching the alpha-side pattern (`floor_measured`, `draws_unmeasured`, `unmeasured_rungs`, `unmeasured_reason`).
2. Add tests mirroring the alpha side:
   - an unpriceable-Sharpe-floor pin (the live 500-bar real-history case reports the Sharpe floor as not measured, with `sharpe_reason`);
   - a measured-Sharpe-floor control (a resolvable draw still reports its floor and driver);
   - keep `test_every_test_in_this_file_is_registered` green (register every new `def test_`).
3. Update `references/validation_methods.md` to state the criterion-2 unmeasured distinction next to the criterion-5 one.

## Constraints

- No threshold, bound, criterion or verdict moves, and `scripts/walk_forward.py` is not in this task's diff.
- A measurement beside the verdict, never part of it.

## Subsequent options (after this task)

- Re-capture the 50,000-bar synthetic ladder so it carries the driver keys (its summary still says "not measurable on this ladder"; ~17 min for that rung alone).
- State explicitly in `references/validation_methods.md` why the held-out-fraction sweep is out-of-sample-path-only (the other paths are configured in months, not fractions).

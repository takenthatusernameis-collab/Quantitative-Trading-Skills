# HANDOFF_NEXT

## The one precise next task

**Fix the `out-of-sample` CLI failure "No valid parameters selected from validation phase" on the shipped `assets/example_data/sample_ohlcv.csv`.** The programmatic `out_of_sample_validation()` path works and is covered by tests, but the CLI always aborts before writing the artifact. This is a concrete, bounded defect that blocks the user-facing rigorous train/validation/test evaluation path — a core quant research objective (chronological train/validation/test separation, genuinely out-of-sample evaluation).

## Why (evidence)

- Reproduced directly on HEAD (this session): `walk_forward.py out-of-sample --data assets/example_data/sample_ohlcv.csv --strategy sma_crossover --validation-method walk_forward --train-frac 0.5 --val-frac 0.25 --test-frac 0.25 --param-grid '{"lookback": [5, 20]}'` prints the train/val/test split then exits 1 with "No valid parameters selected from validation phase."
- `HANDOFF.md` confirms it is pre-existing (identical on `HEAD` with `git stash`) across grids `{5,20}`, `{10,30}`, `{20,50}`, `{2,10}` — not a regression from this session.
- The CLI split logic lives in `scripts/walk_forward.py` (`run_walk_forward` / `out-of-sample` subcommand, around line 3825 where `_parse_param_grid` and `out_of_sample_validation` are invoked). The validation-phase selection that rejects every candidate is the likely root cause.

## Constraints for the next session

- Do not change the warmup metadata (guarded by `tests/test_execution_warmup.py`, 8 tests) or the fill-rate semantics pinned earlier.
- All pinned values must hold unless reported as a methodology change with before/after numbers.
- The full 13-file suite must stay green; pyflakes clean on changed files.
- Do not commit unless explicitly asked — leave the working tree inspectable.
- `matplotlib` must be installed before trusting a green suite; revert `examples/example_output/tear_sheet.{html,json}` after any suite run.

## Suggested first steps

1. Run the exact failing CLI command above and capture the full traceback/log.
2. Inspect `scripts/walk_forward.py` `out-of-sample` handling (around lines 3825-3200 region where `_parse_param_grid` + `out_of_sample_validation` are called) and the validation-phase parameter selection logic.
3. Determine why every grid candidate is rejected (e.g. validation window too short for the lookback, PIT validation dropping all candidates, or an empty metric set) and fix with the smallest change.
4. Verify the CLI now writes the out-of-sample artifact on `sample_ohlcv.csv` and report before/after numbers.
5. Add or extend a test (mirroring `test_out_of_sample_validation_*` in `tests/test_walk_forward.py`) that guards the CLI path so the bug cannot silently return.
6. Run the full suite + pyflakes; keep all pinned values unchanged.

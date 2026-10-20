# HANDOFF_NEXT

## The one precise next task

**Extend the inert-parameter-grid detection to the three remaining analysis paths: `walk_forward_analysis`, `cpcv_analysis` and `parameter_optimization`** (the `walk-forward`, `cpcv` and `optimize` CLI subcommands).

Today only the out-of-sample path detects a grid key that does not change the strategy's behaviour. The other three paths still present a **null experiment as a real parameter search**, and their artifacts are the ones a reader is most likely to quote.

## Why (evidence, reproduced on the current HEAD)

`walk_forward.py optimize --data assets/example_data/sample_ohlcv.csv --strategy sma_crossover --param-grid '{"lookback": [5, 20]}'` exits 0 and prints a ranked "Top 2 parameter combinations" table:

```
Rank  Sharpe     Total Return    Params
1     -0.4040    -10.72%         {'lookback': 5}
2     -0.4040    -10.72%         {'lookback': 20}
```

Both rows are **the same strategy**: `sma_crossover` reads `fast_period` and `slow_period`, so `lookback` is ignored and every combination runs the default 20/50 SMA crossover. The artifact (`parameter_optimization.json`) presents that ranking as the result of a parameter optimization.

`walk_forward.py walk-forward --data assets/example_data/sample_ohlcv.csv --strategy sma_crossover --param-grid '{"lookback": [5, 20]}'` exits 0 and writes `best_params_per_period: [{'lookback': 5}, {'lookback': 5}, None]` — a claim that a parameter was selected per period when nothing was searched.

`walk_forward.py cpcv --data assets/example_data/sample_ohlcv.csv --strategy sma_crossover --param-grid '{"lookback": [5, 20]}'` writes `best_params_per_fold: [None, None, None, ...]` (every fold's 2-bar test window admits no position) — the artifact does not say why.

The helper already exists and is regression-tested: `_inert_param_grid_keys(strategy_factory, param_grid, data)` in `scripts/walk_forward.py` (plus `_strategy_behaviour_fingerprint` / `_strategy_parameter_names`), used by the out-of-sample path, recorded as `summary["inert_grid_params"]` and documented in `references/validation_methods.md` ("Inert Parameter Grids") and `SKILL.md`.

## Scope

1. Call `_inert_param_grid_keys` from `walk_forward_analysis`, `cpcv_analysis` and `parameter_optimization`, on the data each path prices (the full sample for `walk_forward_analysis` / `parameter_optimization`; the training split for `cpcv_analysis` is *not* applicable — use the data passed in).
2. Record the finding in each path's summary (`summary["inert_grid_params"]`) and print a warning in the CLI next to the ranking / selected parameters, so the artifact and the console say the same thing.
3. Decide and document whether an **entirely** inert grid is a hard error or a warning. Recommendation: **warning**, not an error — the same grid may be non-inert on other data, and the current out-of-sample path already warns. Consistency across the four paths matters more than strictness.
4. Do **not** change any return, cost, impact, capacity or selection number. This is a measurement, exactly like the out-of-sample implementation.
5. Add tests in `tests/test_out_of_sample_window.py` (or a sibling file) that guard all three paths, and extend the `SKILL.md` / `references/validation_methods.md` notes to cover them.

## Constraints for the next session

- Do not change the warmup metadata (guarded by `tests/test_execution_warmup.py`, 8 tests) or the fill-rate semantics pinned earlier.
- All pinned values must hold unless reported as a methodology change with before/after numbers. The out-of-sample path's numeric parity with HEAD was verified this session (identical `selected_params`, `val_*` and `test_*` for a window that already fits) — keep it that way.
- The full 14-file suite must stay green; pyflakes must not add new warnings on the changed files (the 5 existing warnings on `scripts/walk_forward.py` are pre-existing and must stay at 5).
- `matplotlib` must be installed before trusting a green suite; revert `examples/example_output/tear_sheet.{html,json}` and `data_provenance.json` after any suite run.
- `scripts/generate_sample_data.py` rewrites `assets/example_data/sample_ohlcv.csv` when run (it is deterministic, so the file stays byte-identical — but do not run it with different arguments).
- Do not commit unless explicitly asked — leave the working tree inspectable.

## Useful context that is already settled (do not re-litigate)

- The `out-of-sample` CLI failure is **fixed**; the window now adapts on the training side only and the diagnosis names the cause. The remaining `out-of-sample` limitation is only that an explicitly requested window is adapted rather than enforced (no "fail instead of adapt" flag).
- The **CPCV fold test window is 2 bars** under the defaults (`--cpcv-test-size` is the fraction *of each group*, so the effective out-of-sample fraction is `test_size / n_splits`). That is a design question worth a separate look, not part of this task; the diagnosis now points at `--cpcv-test-size` / `--cpcv-n-splits` as the remedy.
- The impact model is still linear in the participation rate (no temporary/permanent split, no gap risk), and the parity harness (`baseline_capture.py` / `book_cap_probe.py`) still does not exist. Both are still open.

# HANDOFF_NEXT

## The one precise next task

**Extend the "no parameter could be selected" diagnosis to the two standalone analysis paths — `cpcv_analysis` and `walk_forward_analysis` — so every artifact says *why* nothing was selected, the way the out-of-sample path already does.**

## Why (evidence, reproduced on the current HEAD)

`walk_forward.py cpcv --data assets/example_data/sample_ohlcv.csv --strategy sma_crossover --param-grid '{"fast_period": [5, 10], "slow_period": [20, 30]}'` exits 0 and writes `cpcv_summary.json` containing:

```
best_params_per_fold: [None, None, None, None, None, None, None, None, None, None]
summary.n_folds            = 10
summary.total_oos_return   = null
summary.oos_sharpe         = null
summary.avg_param_stability = 0.0
summary.overfitting_risk   = "high"
```

Nothing in the artifact says **why**. The cause is visible in the fold windows — each fold's test window is **2 bars** (`2018-01-01 → 2018-01-05`, `2018-03-12 → 2018-03-16`, …) because `--cpcv-test-size` is the fraction *of each group*, so the effective out-of-sample fraction is `test_size / n_splits` = 0.1 / 10 = 1%. Two bars are shorter than the indicator warm-up, so **no combination can take a position** and no parameter can be selected. A reader of the artifact sees "overfitting risk: high" and ten `null` selections and has to guess.

The out-of-sample path already solved this: `_diagnose_no_selection` returns `{cause, message, details}` with `cause` in {`no_validation_windows`, `no_position_in_validation_window`}, the CLI prints it, and the failure artifact (`out_of_sample_summary.json`) carries it. The standalone paths have no equivalent.

## Scope

1. Reuse `_diagnose_no_selection` (do not write a second diagnosis vocabulary): call it from `cpcv_analysis` and `walk_forward_analysis` when **no** period / fold selected a parameter, and record the result in the summary, e.g. `summary["no_selection_diagnosis"]` (same key and same `cause` / `message` / `details` shape as the out-of-sample path, so one reader handles both).
2. Print the diagnosis in the CLI next to the period / fold count (`run_cpcv` after "Number of CPCV folds", `run_walk_forward` after "Number of walk-forward periods"), so the console and the artifact agree — the same "measure in the library, print in the CLI" split the inert-grid work just established.
3. Keep the existing summary keys unchanged (`total_oos_return: null`, `avg_param_stability: 0.0`, `overfitting_risk`, `best_params_per_fold: [None, …]`) — the diagnosis is an **addition**, not a redefinition. A "high overfitting risk" verdict on a run where nothing could trade is itself misleading; consider whether `overfitting_risk` should be `None` / "unknown" when no fold selected a parameter, and report that change with before/after numbers.
4. Add a regression test file (e.g. `tests/test_no_selection_diagnosis.py`) that pins: the cause is `no_position_in_validation_window` for the default CPCV configuration; the 2-bar window length and the `--cpcv-test-size` / `--cpcv-n-splits` remedy appear in the message; the summary key and the CLI output agree; a run where a parameter *is* selected carries no diagnosis.
5. Document it in `references/validation_methods.md` (extend "When No Parameter Can Be Selected") and in `SKILL.md` (tip + test inventory + coverage entry).

## Constraints for the next session

- **Do not change any return, cost, impact, capacity or selection number.** The diagnosis is a measurement, exactly like the inert-grid work.
- Do not change the warmup metadata (guarded by `tests/test_execution_warmup.py`, 8 tests) or the fill-rate semantics pinned earlier.
- **Do not "fix" the CPCV defaults as part of this task.** The 2-bar fold window is a *design* question (the effective out-of-sample fraction is `test_size / n_splits`, which is not what the flag name suggests). Changing the default changes every CPCV number and would need a before/after report plus pinned-value updates. Record the finding; treat the default as a separate, explicitly-scoped change.
- The full 15-file suite must stay green; pyflakes must not add new warnings on the changed files (the 5 on `scripts/walk_forward.py` are pre-existing and must stay at 5).
- `matplotlib` must be installed before trusting a green suite; revert `examples/example_output/tear_sheet.{html,json}` and `data_provenance.json` after any suite run.
- Do not commit unless explicitly asked — leave the working tree inspectable.

## Useful context that is already settled (do not re-litigate)

- **Inert parameter grids are now detected on all four paths** (`walk-forward`, `cpcv`, `optimize`, `out-of-sample`), recorded in the artifacts and printed once by the CLI. A grid key the strategy does not read (`lookback` for `sma_crossover`) is reported as the null experiment it is. Keep the split: the library measures (`_inert_grid_report`), the CLI prints (`_print_inert_grid_warning`).
- The out-of-sample CLI failure "No valid parameters selected from validation phase" is **fixed**; the window adapts on the training side only and the diagnosis names the cause.
- The remaining known limitation of the inert-grid detector: it varies one key while holding the other grid keys at their first value, so a key whose effect appears only in combination with another grid value can be reported as inert (a false accusation). Not demonstrated with the shipped strategies; the fix is to evaluate each key across every combination of the other keys.
- The `monte-carlo` path picks its "best params" from `parameter_optimization` and has the same null-experiment exposure, but records and prints nothing.
- The impact model is still linear in the participation rate (no temporary/permanent split, no gap risk), and the parity harness (`baseline_capture.py` / `book_cap_probe.py`) still does not exist. Both are still open.

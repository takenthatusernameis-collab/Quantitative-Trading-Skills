# HANDOFF

## What changed this session

**Completed the task assigned in `HANDOFF_NEXT.md`: inert-parameter-grid detection on all four analysis paths** (`walk-forward`, `cpcv`, `optimize`, `out-of-sample`).

The starting point was a control-marker commit (`904d281`) that already contained a *partial* implementation: it detected the inert grid in `walk_forward_analysis`, `cpcv_analysis` and `parameter_optimization` and printed a warning **from inside the analysis functions**. That left four defects, all of which this session fixed:

1. **The warning was printed from library code, so it appeared in the wrong places.** The out-of-sample CLI printed it **three times** (twice from the library — `out_of_sample_validation` and the `walk_forward_analysis` it calls — plus once from the CLI). The `monte-carlo` CLI printed *"The ranking over those parameters is a null experiment"* although that path has no ranking. `_optimize_sweep_coefficient` documents *"No file I/O or stdout"* while its callee printed, so a cost sweep repeated the warning once per coefficient.
2. **The optimize artifact recorded nothing.** `parameter_optimization.json` is a plain ranked list, so the finding existed only in the console.
3. **No test guarded any of the three paths.**
4. **No documentation covered them** (`references/validation_methods.md` said "the out-of-sample path detects this").

### Changes

`skills/quantitative-backtesting/scripts/walk_forward.py`

- **`_inert_grid_report` (new)** — the single measuring helper. Returns the inert grid keys, the parameter names the strategy actually reads, and one human-readable message. It *measures only*: it never changes a return, cost, impact, capacity or selection number, and it never prints.
- **`_print_inert_grid_warning` (new)** — the single CLI printer. The console now shows the warning exactly once, next to the ranking / selection it qualifies, and the console and the artifact carry the same string.
- `walk_forward_analysis` / `cpcv_analysis` — record `summary["inert_grid_params"]` **and** `summary["inert_grid_message"]`; the three duplicated print blocks are gone.
- `parameter_optimization` — new keyword `inert_grid_report` (an out-param) that receives the measurement, so the caller can record it in its artifact and print it next to the ranking. The function no longer prints.
- `out_of_sample_validation` — uses the shared helper and records `inert_grid_message` in **both** the success and the failure summary; its library print is removed (the CLI prints it once, next to the selection and next to the selection *failure*).
- CLI — the warning is printed next to the numbers it qualifies: `run_walk_forward` after "Number of walk-forward periods", `run_cpcv` after "Number of CPCV folds", `run_parameter_optimization` after the ranking table, `run_out_of_sample_validation` after "Selected Parameters" and after the "no valid parameters selected" failure.
- **Optimize artifact** — the new `parameter_optimization_inert_grid.json` (inert keys, message, parameter names the strategy reads, the grid, the strategy, the number of ranked combinations). `parameter_optimization.json` stays a plain ranked list, so the artifact schema is unchanged.
- **Sweep artifacts** — the four cost-sweep helpers carry `inert_grid_params` in their rows, so `*_sweep.json` records the finding too.

`skills/quantitative-backtesting/tests/test_inert_param_grid.py` (**new**, 16 tests) — the measurement (inert key flagged, live key not, mixed grid flags only the inert one, the report agrees with the key detector), the recording in all four paths, the single CLI warning on each CLI, the sweep artifact, and the invariant that the measurement changes no number.

`skills/quantitative-backtesting/references/validation_methods.md` — "Inert Parameter Grids" rewritten: the four paths and where each records the finding, the **warning-not-error** decision and its rationale, the scope of each measurement, and the honest statement that the check is a screen, not a proof.

`skills/quantitative-backtesting/SKILL.md` — the research-integrity tip rewritten for the four paths, the new test file added to the inventory, the run commands and the coverage entry.

## What was actually verified

- **Numeric parity with HEAD (`904d281`) on all four CLI paths, with a meaningful grid *and* an inert grid.** The artifacts are identical once the inert-grid keys are excluded: `optimize` → `parameter_optimization.json`, `walk-forward` → `walk_forward_summary.json`, `cpcv` → `cpcv_summary.json`, `out-of-sample` → `out_of_sample_summary.json`. Script and evidence: `/home/runner/work/_temp/kilo-tmp/kilo/parity_check.py` and the `parity-*` artifacts next to it (8/8 cases pass, "0 parity failure(s)").
- **Full suite green — 15 files** (the 14 previous + the new one): `test_cpcv` 29/29, `test_data_loader` 32/32, `test_examples_coverage` 7/7, `test_execution_warmup` 8/8, `test_falsifiable_hypothesis_example` 3/3, `test_generate_sample_data` 2/2, `test_inert_param_grid` 16/16, `test_monte_carlo` 20/20, `test_out_of_sample_window` 10/10, `test_panel_reference_pinned` 2/2, `test_performance` 33/33, `test_reporting` OK, `test_run_backtest` 104/104, `test_strategy_builder` 33/33, `test_walk_forward` 177/177.
- **pyflakes unchanged**: 5 warnings on `scripts/walk_forward.py` — the same ones as HEAD (1 unused import, 4 "f-string is missing placeholders"); 0 on the new test file.
- **The console** now shows the warning exactly once per path (it was three times on the out-of-sample path before), next to the ranking / selection, and the `monte-carlo` path no longer prints a misworded warning.
- **The artifacts** carry the finding: `summary["inert_grid_params"]` / `summary["inert_grid_message"]` in the walk-forward, CPCV and out-of-sample summaries; `parameter_optimization_inert_grid.json` next to the (unchanged) ranked list; `inert_grid_params` in every cost-sweep row.
- **Overhead is within noise**: a 16-combination grid on 3000 bars takes 0.30–0.32 s at HEAD and 0.32–0.37 s now (the measurement prices one behavioural fingerprint per grid value, the same order as the search itself).
- The suite rewrites `examples/example_output/tear_sheet.{html,json}` and `data_provenance.json` (timestamp + matplotlib plots); they were reverted, so the working tree holds no example-output changes.

## What remains unresolved

- **The detector is a screen, not a proof.** `_inert_param_grid_keys` varies one key while holding the other grid keys at their **first** value, so a key whose effect appears only in *combination* with another grid value can still be reported as inert — a false accusation. It was not demonstrated with the shipped strategies (four `sma_crossover` grids probed, no false positive), but it is a real limitation for custom strategies with interacting parameters. It is now stated as such in `references/validation_methods.md`; the fix (evaluate each key across every combination of the other keys) was deliberately **not** taken this session.
- **The optimize path's finding lives in a sidecar file**, not inside the ranking artifact, because `parameter_optimization.json` is a plain list and `tests/test_walk_forward.py::test_cli_optimize_multiple_benchmarks` reads `payload[0]`.
- **The `monte-carlo` path picks its "best params" from `parameter_optimization`** and therefore has the same null-experiment exposure, but records and prints nothing (it is not one of the four analysis paths; out of scope this session).
- **The standalone CPCV and walk-forward paths still do not say *why* no parameter was selected.** With the default `--cpcv-test-size 0.1 --n-splits 10` every fold's test window is **2 bars** (e.g. `2018-01-01 → 2018-01-05`), no combination can take a position, and `cpcv_summary.json` reports `best_params_per_fold: [None × 10]`, `total_oos_return: null`, `avg_param_stability: 0.0`, `overfitting_risk: high` — **with no explanation**. The out-of-sample path has this diagnosis (`_diagnose_no_selection`); the standalone paths do not. This is the next task.
- Unchanged from before: the impact model is still linear in the participation rate (no temporary/permanent split, no gap risk); the parity harness (`baseline_capture.py` / `book_cap_probe.py`) still does not exist; an explicitly requested walk-forward window is still adapted rather than enforced.

## Approaches that have already failed (do not repeat)

- **Printing the warning from inside the analysis functions** (the control-marker approach): it duplicated the CLI warning, broke the "no stdout" contract of the sweep helpers, and produced a misworded message in the `monte-carlo` path. Keep the measurement in the library and the printing in the CLI.
- **Making the optimize artifact a dict** (`{"results": [...], "inert_grid_params": [...]}`) to carry the finding inline: it breaks `test_cli_optimize_multiple_benchmarks` (reads `payload[0]`) and changes a published artifact schema. Use the sidecar file instead.
- **Hard-failing on an entirely inert grid**: rejected — the same grid can be inert on one sample and live on another, and the out-of-sample path has always warned. Warning + artifact record, consistent across the four paths.
- **Re-running the "no valid parameters" fix on the CPCV side by widening the generic message**: the causes need different remedies (window does not fit / every combination stayed flat), which is why the out-of-sample diagnosis is structured (`cause` + `message` + `details`).

## Git state

Working tree (not committed — the harness commits the session's work together with these handoff files, as in `d52ff8e`):

- modified: `skills/quantitative-backtesting/scripts/walk_forward.py`, `references/validation_methods.md`, `SKILL.md`
- new: `skills/quantitative-backtesting/tests/test_inert_param_grid.py`

HEAD is `904d281`; `main` is level with `origin/main` (0 commits ahead, 0 behind — the harness pushed the previous session's work and the control-marker commit).

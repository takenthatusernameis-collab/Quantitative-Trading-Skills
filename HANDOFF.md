# HANDOFF

## What changed this session

**Fixed the `out-of-sample` CLI failure "No valid parameters selected from validation phase"** (the task assigned in `HANDOFF_NEXT.md`), and made the same path state *why* it fails when it still cannot select a parameter.

### Root cause (confirmed by reproduction, not guessed)

The walk-forward **validation phase runs inside the training split**, so a single walk-forward period needs `train_months + test_months` of calendar span. The CLI's default window is 12 + 3 months, but the training split of the shipped `assets/example_data/sample_ohlcv.csv` (50% of 504 bars) spans **11.5 months** — the phase therefore produced **zero** periods, no parameter could be selected, and the run aborted with a message that named the symptom and hid the cause. The CPCV path failed for a second, independent reason: `--cpcv-test-size` is the fraction *of each group*, so the default `n_splits=10, test_size=0.1` puts a **2-bar** test window in every fold — too short for any strategy to take a position.

### Changes (all under `skills/quantitative-backtesting/`)

- `scripts/walk_forward.py`
  - `_walk_forward_window_periods` / `_resolve_walk_forward_window` (**new**): resolve the walk-forward window against the training split. A window that fits is used **unchanged**; a window that does not fit is shortened **on the training side only** (the validation phase's out-of-sample `test_months` and the out-of-sample framework's validation/test splits are never touched) to the largest value that still yields a period. A split too short for any window is reported, not guessed.
  - `out_of_sample_validation`: uses the resolved window, prints the adaptation, and records it in `summary["walk_forward_window"]` (`requested` / `effective` / `adapted` / `train_span_months` / `requested_periods` / `effective_periods` / `reason`).
  - `_diagnose_no_selection` (**new**) + `summary["no_selection_diagnosis"]`: a validation phase that selects nothing now reports its **cause** (`no_validation_windows` vs `no_position_in_validation_window`), the window length involved, and the concrete remedy, instead of one generic sentence.
  - `_inert_param_grid_keys` / `_strategy_behaviour_fingerprint` / `_strategy_parameter_names` (**new**): a grid key whose values do **not** change the strategy's behaviour (signals + book) on the training split is a **null experiment**. The out-of-sample path now warns and records it in `summary["inert_grid_params"]`. This matters for the shipped example: `sma_crossover` reads `fast_period` / `slow_period`, so the grid `{"lookback": [5, 20]}` in the old handoff searched nothing while the artifact still claimed a "selected parameter".
  - CLI (`run_out_of_sample_validation`): prints the effective window and the inert-parameter warning next to the selected parameters, prints the diagnosis on failure, and **writes the failure diagnosis to `out_of_sample_summary.json`** (a failed run now leaves a machine-readable record instead of nothing).
- `tests/test_out_of_sample_window.py` (**new**, 10 tests) — the regression guards listed below.
- `references/validation_methods.md` — three new sections: "The Walk-Forward Window Inside the Training Split", "When No Parameter Can Be Selected", "Inert Parameter Grids".
- `SKILL.md` — three new bullets in the research-integrity tips, the new test file in the test inventory and the run commands, and a coverage entry.

### No change to the numbers that already worked

The pricing, cost, warmup and selection logic is untouched. The window resolution only acts when the requested window cannot produce a single period, and the inert-grid check is a measurement (it changes no return, cost, impact or capacity value).

## What was actually verified

- **The failing command now completes** (exit 0, artifact written) on the shipped sample:
  `walk_forward.py out-of-sample --data assets/example_data/sample_ohlcv.csv --strategy sma_crossover --validation-method walk_forward --train-frac 0.5 --val-frac 0.25 --test-frac 0.25 --param-grid '{"fast_period": [5, 10], "slow_period": [20, 30]}'`
  → window adapted 12 → 8 months, 1 period, selected `{'fast_period': 10, 'slow_period': 20}`, validation Sharpe 2.3772, **held-out test total return -3.62%, test Sharpe -0.4653** (the framework's own out-of-sample evidence, net of commission/slippage).
- **Bit-for-bit numeric parity with HEAD** for a window that already fits (1500-bar sample, 60/20/20 split, same grid): identical `selected_params`, identical `val_total_return` / `val_sharpe`, identical `test_total_return` / `test_sharpe` / `test_n_periods` (checked by running the CLI on `HEAD` via `git stash` and diffing the artifacts).
- **New regression file green**: `tests/test_out_of_sample_window.py` 10/10 (window kept when it fits; shortened to the *largest* fitting window otherwise; infeasible split reported; adaptation recorded; diagnosis cause/message; CLI exit 0 + artifact; CLI exit 1 + diagnosis artifact; inert grid flagged; meaningful grid not flagged).
- **Full suite green**: all 14 test files exit 0 — `test_cpcv` 29/29, `test_data_loader` 32/32, `test_examples_coverage` 7/7, `test_execution_warmup` 8/8, `test_falsifiable_hypothesis_example` 3/3, `test_generate_sample_data` 2/2, `test_monte_carlo` 20/20, `test_out_of_sample_window` 10/10, `test_panel_reference_pinned` 2/2, `test_performance` 33/33, `test_reporting` OK (62 tests), `test_run_backtest` 104/104, `test_strategy_builder` 33/33, `test_walk_forward` 177/177.
- **pyflakes**: the 5 warnings on `scripts/walk_forward.py` are byte-identical to HEAD's (4 pre-existing "f-string is missing placeholders" + 1 unused import); the new test file is clean.
- **CPCV remedy verified**: the diagnosis's suggested fix works — `--cpcv-n-splits 4 --cpcv-test-size 0.5` completes the run on the same sample (test Sharpe -0.7958).

## What remains unresolved

- **The inert-grid check only covers the out-of-sample path.** `walk_forward_analysis`, `cpcv_analysis` and `parameter_optimization` still present a null experiment as a real search — see `HANDOFF_NEXT.md` for the reproduction. This is the next task.
- **The impact model is still linear** in the participation rate (no temporary/permanent split, no gap risk).
- **The parity harness** (`baseline_capture.py` / `book_cap_probe.py`) still does not exist; HEAD-vs-new parity cannot be run as specified.
- **The adapted window is a methodology choice that is only *reported*, not *enforced*.** A researcher who explicitly asks for `--wf-train-months 12` on a one-year training split gets 8 months with a loud message; there is no flag to make the run fail instead of adapting. Deliberate: a hard failure would reproduce the bug this session fixed.
- `matplotlib` must be installed before trusting a green suite (`tests/test_reporting.py` fails without it). Running the suite re-writes `examples/example_output/tear_sheet.{html,json}` and `data_provenance.json`; revert them after any suite run so they stay environment-neutral (done this session — the working tree holds no example-output changes).

## Approaches that have already failed (do not repeat)

- The **generic "no valid parameters" message** is a dead end for diagnosis: it collapses two unrelated causes (window does not fit / every combination stays flat) into one sentence. Do not try to fix the CPCV case by widening that message; the causes need different remedies, which is why the diagnosis is now structured (`cause` + `message` + `details`).
- **Shrinking the out-of-sample `test_months` of the validation phase** was rejected: it would shorten the very window that carries the out-of-sample evidence, while the training window (used only for in-sample selection inside the training split) is the safe axis to shorten.
- The **CPCV defaults cannot be fixed by the window resolver**: the problem there is the 2-bar fold test window, not the calendar span of the training split. It is reported with a remedy, not silently changed.

## Git state

Working tree (not committed; the harness commits the session's work together with these handoff files, as in `42b630d`):

- modified: `skills/quantitative-backtesting/scripts/walk_forward.py`, `references/validation_methods.md`, `SKILL.md`
- new: `skills/quantitative-backtesting/tests/test_out_of_sample_window.py`

HEAD is `42b630d` ("Pin panel book-pricing reference artifact with regression test"); the branch is ahead of `origin/main` by 2 commits.

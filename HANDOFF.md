# HANDOFF

## What changed this session

**Completed the task assigned in `HANDOFF_NEXT.md`: the "no parameter could be
selected" diagnosis now covers the two standalone analysis paths**
(`cpcv_analysis` and `walk_forward_analysis`), with the same vocabulary, the
same artifact key and the same console line the out-of-sample path already
used — and the overfitting-risk verdict on such a run is now *not applicable*
instead of a categorical "high" / "low" that contradicted itself across paths.

### Changes

`skills/quantitative-backtesting/scripts/walk_forward.py`

- **`_diagnose_no_selection`** — takes an optional `context` dict (the
  configuration of the path that asks: the analysis path, the split/window
  settings, and the CLI flags that path accepts). The context is recorded in
  `details`, and the **remedy is now built from the flags the path's own
  subcommand accepts** — the previous wording named `--cpcv-test-size` /
  `--cpcv-n-splits` / `--wf-test-months`, which only exist on the
  `out-of-sample` subcommand (the standalone subcommands spell them
  `--test-size` / `--n-splits` / `--train-months` / `--test-months`). For CPCV
  the message now also states the **effective out-of-sample fraction**
  (`test_size / n_splits`), which is the usual reason the window is too short.
  The wording changed from "validation phase" to "analysis", because the
  standalone paths are not a validation phase.
- **`cpcv_analysis` / `walk_forward_analysis`** — record
  `summary["no_selection_diagnosis"]` (`{cause, message, details}`, the same
  key and shape as the out-of-sample path) when **no** fold / period selected a
  parameter. A run that selected something carries no diagnosis. The
  diagnosis is a measurement: it changes no number.
- **`_calculate_cpcv_summary` / `overfitting_check`** — when no fold / period
  selected a parameter there is no parameter stability to classify, so
  `overfitting_risk` is now `null` with an `overfitting_risk_reason` that
  says so. **Before**: CPCV reported `high` and walk-forward reported `low`
  for the *same* state — two contradictory categorical verdicts on a run in
  which nothing could trade. A categorical verdict there is a category error:
  it reads as a finding about the strategy when it is a fact about the window.
  A run that *did* select keeps its categorical verdict, unchanged.
- **CLI** — `_print_no_selection_diagnosis` prints the diagnosis next to the
  fold / period count (`No parameter could be selected: <message>`), and
  `_print_overfitting_risk` / `_format_overfitting_risk` print
  `Overfitting Risk: unknown` plus the reason (and render `unknown` in the
  cost-sweep tables instead of `None`).

`skills/quantitative-backtesting/scripts/reporting.py` — the CPCV tear sheet
renders a `null` overfitting risk as `unknown` instead of `None`.

`skills/quantitative-backtesting/tests/test_no_selection_diagnosis.py`
(**new**, 12 tests) — the diagnosis on both standalone paths, the per-path
remedy flags, the not-applicable verdict, the CLI/artifact agreement, and the
invariant that the diagnosis changes no number.

`skills/quantitative-backtesting/tests/test_cpcv.py` — **one existing
expectation updated**: `cpcv_basic_structure` asserted
`summary["overfitting_risk"] in ("low", "medium", "high")` on a run in which
**no fold could select a parameter** (12-bar test window, shorter than the
indicator warm-up). It now pins the not-applicable verdict, the reason and
the diagnosis.

`skills/quantitative-backtesting/references/validation_methods.md` —
"When No Parameter Can Be Selected" extended (per-path table, per-path flag
table, the CPCV effective fraction, the not-applicable verdict); the two
risk-classification tables and the walk-forward / CPCV "Output" key lists
updated.

`skills/quantitative-backtesting/SKILL.md` — three new tips (every path says
why; the CPCV effective fraction; the not-applicable overfitting verdict), the
test-inventory entry, the run command and the coverage entry.

## What was actually verified

- **Numeric parity with HEAD (`5af0565`) on six CLI cases — 6/6.** The
  artifacts are byte-identical except for the *added* diagnosis subtrees and
  the overfitting verdict on the runs that could not select. **No return,
  Sharpe, stability, capacity or selection number changed anywhere.** Script
  and artifacts: `/home/runner/work/_temp/kilo-tmp/kilo/parity/parity_check.py`
  and `parity/{head_out,new_out}/` next to it.

  | Case | Difference found |
  | ---- | ---------------- |
  | `cpcv` (defaults, nothing selected) | `+ no_selection_diagnosis`, `+ overfitting_risk_reason`, `overfitting_risk: "high" → null` |
  | `cpcv --n-splits 4 --test-size 0.4` (selects) | **none** |
  | `walk-forward` (defaults, selects) | **none** |
  | `walk-forward` (slow_period 200, nothing selected) | `+ no_selection_diagnosis`, `+ overfitting_risk_reason`, `overfitting_risk: "low" → null` |
  | `out-of-sample` (walk-forward) | **none** |
  | `out-of-sample` (cpcv, fails) | failure **message text** only (adds the effective-fraction sentence, drops the word "validation phase") |

- **Full suite green — 16 files** (the 15 previous + the new one):
  `test_cpcv` 29/29, `test_data_loader` 32/32, `test_examples_coverage` 7/7,
  `test_execution_warmup` 8/8, `test_falsifiable_hypothesis_example` 3/3,
  `test_generate_sample_data` 2/2, `test_inert_param_grid` 16/16,
  `test_monte_carlo` 20/20, `test_no_selection_diagnosis` 12/12,
  `test_out_of_sample_window` 10/10, `test_panel_reference_pinned` 2/2,
  `test_performance` 33/33, `test_reporting` OK, `test_run_backtest` 104/104,
  `test_strategy_builder` 33/33, `test_walk_forward` 177/177.
- **pyflakes unchanged**: `scripts/walk_forward.py` 5 warnings (the same ones
  as HEAD: 1 unused import + 4 "f-string is missing placeholders"),
  `scripts/reporting.py` 2 (same as HEAD), the new test file 0,
  `tests/test_cpcv.py` 4 (same as HEAD).
- **The console** prints the diagnosis exactly once per path, next to the fold
  / period count, and `Overfitting Risk: unknown` + the reason instead of a
  categorical verdict that nothing could support.
- **Before/after numbers for the verdict** (the only value that changed):
  CPCV `high → null`, walk-forward `low → null`; `avg_param_stability` stays
  `0.0`, `total_oos_return` stays `null`, `best_params_per_fold` stays
  `[None × 10]`, `best_params_per_period` stays `[None × 3]`.
- The suite rewrites `examples/example_output/tear_sheet.{html,json}` and
  `data_provenance.json`; they were reverted, so the working tree holds no
  example-output changes.

## What remains unresolved

- **The CPCV default is still the 1% effective out-of-sample fraction.** At
  `--test-size 0.1 --n-splits 10` the effective fraction is `0.1/10 = 1%`
  and every fold's test window holds **5 bars** on the shipped 504-bar sample
  (the *out-of-sample* path, whose validation split is half the sample, gets
  **2-bar** windows). Nothing can be selected there. The default was
  deliberately **not** changed: it is a design question that changes every
  CPCV number and would need a before/after report plus pinned-value
  updates. It is now diagnosed and documented instead.
- **Partial selection is still undiagnosed.** When *some* folds select and
  others do not (verified: `--n-splits 5 --test-size 0.2` on the shipped
  sample selects in 2 of 5 folds), the artifact reports
  `folds_with_position: 2` but does not say why the other three folds stayed
  flat. The diagnosis is recorded only when **no** fold selected.
- **The inert-grid detector can still falsely accuse a live parameter**
  (`_inert_param_grid_keys` holds every other grid key at its *first* value
  while varying the key under test). Not demonstrated with the shipped
  strategies; this is the next task.
- The `monte-carlo` path picks its "best params" from
  `parameter_optimization` and therefore has the same null-experiment
  exposure, but records and prints nothing.
- Unchanged from before: the impact model is still linear in the participation
  rate (no temporary/permanent split, no gap risk); the parity harness
  (`baseline_capture.py` / `book_cap_probe.py`) still does not exist; an
  explicitly requested walk-forward window is still adapted rather than
  enforced.

## Approaches that have already failed (do not repeat)

- **Reusing the out-of-sample message wording verbatim on the standalone
  paths.** The remedy named `--cpcv-test-size` / `--cpcv-n-splits` /
  `--wf-test-months`; those flags exist only on the `out-of-sample`
  subcommand, so the standalone remedy was not applicable. The remedy is now
  built from the path's own flags, and
  `test_the_remedy_names_flags_the_path_actually_accepts` checks every flag
  named in a message against the subcommand's `--help` output.
- **Keeping `overfitting_risk` as "high" / "low" and only adding the
  diagnosis.** The two paths reported *contradictory* categorical verdicts for
  the same state (CPCV `high`, walk-forward `low`), and neither was
  supported by any measurement. The verdict is now `null` ("not applicable")
  plus a reason. One existing test pinned the old value and was updated.
- (unchanged from before) Printing the warning from inside the analysis
  functions; making the optimize artifact a dict; hard-failing on an inert
  grid; widening the generic "no valid parameters" message instead of
  structuring the causes.

## Git state

Working tree (not committed — the harness commits the session's work together
with these handoff files, as in `d52ff8e`):

- modified: `skills/quantitative-backtesting/scripts/walk_forward.py`,
  `scripts/reporting.py`, `references/validation_methods.md`, `SKILL.md`,
  `tests/test_cpcv.py`
- new: `skills/quantitative-backtesting/tests/test_no_selection_diagnosis.py`

HEAD is `5af0565`.

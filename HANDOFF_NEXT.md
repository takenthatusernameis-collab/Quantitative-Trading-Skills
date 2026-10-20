# HANDOFF_NEXT

## The one precise next task

**Diagnose the *partial* selection: when some folds / periods select a
parameter and others do not, say why the flat ones stayed flat — and say how
many windows the verdict rests on.**

## Why (evidence, on the current HEAD)

`cpcv --n-splits 5 --test-size 0.2` on the shipped sample selects in
**2 of 5** folds:

```
best_params_per_fold: [{'fast_period': 10, 'slow_period': 20}, None, None,
                        {'fast_period': 10, 'slow_period': 20}, None]
folds_with_position: 2
no_selection_diagnosis: None
overfitting_risk: low
```

The artifact reports the count and says nothing about the three flat folds.
The library shows they are **not** short-window folds: every fold carries the
same 20 test bars, and the flat folds simply produced no position
(`test_returns` empty, `test_sharpe: None`). So the cause is a *strategy*
fact (the signal never triggers on that window), not a window fact — and
those two call for completely different remedies, exactly as the
already-fixed "no selection at all" case showed.

Two concrete harms:

1. **A reader cannot interpret the count.** "2 of 5 folds selected" is
   compatible with "3 folds were too short to trade" (a design problem) and
   with "the strategy is flat on 60% of the sample" (a strategy finding).
   The artifact supports both readings.
2. **The categorical verdict is reported on a minority of the evidence.**
   `overfitting_risk: low` is derived from the parameter stability of the
   2 folds that selected, with no statement that 3 folds contributed
   nothing. The previous session already established the principle that a
   verdict which no measurement supports must not be categorical (CPCV said
   `high` and walk-forward said `low` for the same state; both became
   `null` with a reason).

## Scope

1. **Extend the existing vocabulary, do not invent a second one.**
   `_diagnose_no_selection` (`scripts/walk_forward.py:3601`) already
   distinguishes `no_validation_windows` from
   `no_position_in_validation_window` and names the flags the path's own
   subcommand accepts. Reuse it *per window* for the flat windows, and
   report the result as a **partial** diagnosis (a new key on the summary,
   e.g. `partial_selection_diagnosis`) only when **some** windows selected
   and **some** did not. The all-flat case must keep using
   `no_selection_diagnosis` unchanged.
2. **Say what the flat windows were.** For each flat fold / period, report
   the cause from the same vocabulary (window too short vs. no position) and
   the evidence for it (the window's bar count, the empty test returns).
   A per-window breakdown is the point: the count alone is what is missing
   today.
3. **Qualify the verdict.** When the verdict rests on fewer windows than
   exist, the artifact must say so — either by adding the count to the
   existing reason field or by extending the message. Do **not** remove the
   categorical verdict where a measurement supports it (a run in which every
   window selected keeps its verdict unchanged), and do not change the
   verdict's *value* on the runs that already have one: the constraint from
   the previous sessions was that no number moves, and the same reasoning
   applies here.
4. **Cover all four paths** the way the "no selection at all" diagnosis
   does: `walk_forward_analysis`, `cpcv_analysis`, and the out-of-sample
   path (whose validation phase runs inside the training split). The
   `optimize` path has no folds / periods, so it is out of scope.
5. **Demonstrate first**: a test that asserts the artifact says nothing
   about the flat folds today, and says why after the fix.
6. **Update the documentation**: `references/validation_methods.md`, "When
   No Parameter Can Be Selected" (add the partial case, the per-window
   causes, and the qualifying of the verdict) and `SKILL.md` (the
   research-integrity tip and the test-inventory entry).
7. **Extend the regression tests** (`tests/test_no_selection_diagnosis.py`):
   the demonstration, the partial diagnosis on the standalone paths, the
   per-path remedy flags (the existing helper
   `test_the_remedy_names_flags_the_path_actually_accepts` checks every
   flag named in a message against the subcommand's `--help` output — the
   partial message must pass it too), the CLI/artifact agreement, and the
   standing invariant that the diagnosis changes no number.

## Constraints for the next session

- **Do not change any return, cost, impact, capacity or selection number.**
  The diagnosis is a measurement.
- Keep the `no_selection_diagnosis` key, its shape
  (`{cause, message, details}`) and the all-flat behaviour exactly as they
  are. The new finding is an *addition* for the partial case.
- The full **16-file** suite must stay green; pyflakes must not add new
  warnings on the changed files (`scripts/walk_forward.py` is at 5,
  `scripts/reporting.py` at 2, `tests/test_cpcv.py` at 4, and
  `tests/test_inert_param_grid.py` at 0 — all pre-existing).
- **Do not "fix" the CPCV defaults.** The effective out-of-sample fraction
  (`test_size / n_splits` = 1% at the defaults, 5-bar fold windows on the
  shipped sample) is a design question that changes every CPCV number; it is
  now diagnosed and documented, not patched.
- `matplotlib` must be installed before trusting a green suite; revert
  `examples/example_output/tear_sheet.{html,json}` and `data_provenance.json`
  after any suite run.
- Do not commit unless explicitly asked — leave the working tree inspectable.

## Context that is already settled (do not re-litigate)

- **Every path that can select nothing now says why**, with one vocabulary:
  `summary["no_selection_diagnosis"]` (`{cause, message, details}`) on
  `cpcv_analysis`, `walk_forward_analysis` and the out-of-sample failure
  summary; the cause is `no_validation_windows` or
  `no_position_in_validation_window`. The remedy names the flags the path's
  own subcommand accepts, and the CPCV message states the effective
  out-of-sample fraction.
- **The overfitting-risk verdict is `null` ("not applicable") when nothing
  could be selected**, with an `overfitting_risk_reason`; a run that did
  select keeps its categorical verdict.
- **The inert-parameter-grid check is now exhaustive** over the
  combinations of the other grid keys' values, bounded at 16 combinations
  per key, with the bound stated in the finding. It accuses a key only when
  the key changes nothing in *every* combination, so a parameter that
  matters only in combination is never accused. The reporting surface did
  not change (same keys, same sidecar, same CLI warning position).
  See `HANDOFF.md` for the evidence.
- Inert parameter grids are detected on all four analysis paths
  (`walk-forward`, `cpcv`, `optimize`, `out-of-sample`), recorded in the
  artifacts and printed once by the CLI. Keep the split: the library
  measures (`_inert_grid_report`), the CLI prints
  (`_print_inert_grid_warning`).
- The impact model is still linear in the participation rate (no
  temporary/permanent split, no gap risk), and the parity harness does not
  exist. Both are still open.

## Alternative tasks, if the primary one is blocked

- **Measure the inert grid per window instead of over the full sample.** The
  selection happens inside each fold / period, so a key that is live over
  the whole sample but inert in every training window is reported as live
  although each fold's search over it is a null experiment. Not
  demonstrated; a per-window measurement changes the reporting surface.
- **Build the parity harness** (`baseline_capture.py` / `book_cap_probe.py`)
  that captures a baseline run and compares the framework against an
  independent re-implementation of the same methodology (the net-exposure vs
  book pricing gap). Larger scope; needs a precise definition of what
  "parity" means before any code is written.
- **The `monte-carlo` path** picks its "best params" from
  `parameter_optimization` and records and prints none of the findings the
  other paths record (inert grid, diagnosis). Small, but it is a
  consistency gap rather than a new measurement.

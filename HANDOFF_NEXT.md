# HANDOFF_NEXT

## The one precise next task

**Fix the false-accusation limitation of the inert-parameter-grid detector:
evaluate every grid key across *all* combinations of the other grid values,
not only the combination that holds them at their first value.**

## Why (evidence, on the current HEAD)

`_inert_param_grid_keys` (`skills/quantitative-backtesting/scripts/walk_forward.py:3251`)
varies one grid key at a time and holds **every other grid key at its first
value**:

```python
for other_key, other_values in (param_grid or {}).items():
    if other_key == key:
        continue
    if isinstance(other_values, (list, tuple)) and len(other_values) > 0:
        params[other_key] = other_values[0]     # <-- only the first value
```

So a key whose effect appears **only in combination** with a non-first value
of another key is reported as inert — a **false accusation** written into a
published artifact (`summary["inert_grid_params"]`, the
`parameter_optimization_inert_grid.json` sidecar) and printed as a
`WARNING:` on the CLI. A false accusation is worse than no accusation: it
teaches the reader to ignore the warning.

Concretely: a strategy that reads `threshold` **only when `mode == "b"`**
is inert with respect to `threshold` at `mode = "a"`, so varying `mode`
while holding `threshold` at its first value finds no behavioural difference
and flags `mode` as inert — even though `mode` changes everything at
`threshold = 0.2`.

The detector was probed against four `sma_crossover` grids in an earlier
session and produced no false positive, which is why the limitation was left
documented rather than fixed. It has **not** been demonstrated yet, because
the shipped strategies do not have interacting parameters.

## Scope

1. **Demonstrate first** (a failing test): a small custom strategy whose
   `threshold` only matters when `mode == "b"`, the grid
   `{"mode": ["a", "b"], "threshold": [0.1, 0.2]}`. Assert that today `mode`
   is reported as inert, and that after the fix it is not. The demonstration
   is the evidence the fix rests on — write it before the fix.
2. **Fix `_inert_param_grid_keys`**: for each key, compare its values across
   **every** combination of the other keys' values. A key is inert only when
   it changes the behaviour in *none* of those combinations. Use an **early
   exit**: as soon as one combination shows a difference, the key is live and
   the remaining combinations are skipped — that keeps the common (live key)
   case as cheap as it is today.
3. **Keep the cost bounded and state the bound.** The exhaustive evaluation
   costs `len(values) x prod(len(other values))` fingerprints per key. Cap it
   (e.g. a maximum number of evaluated combinations) and, when the cap is
   hit, fall back to the current first-value behaviour **and say so in the
   message** rather than silently reporting a partial answer.
4. **Update the reporting surface only as far as needed**: keep the keys
   `inert_grid_params` / `inert_grid_message`, the sidecar artifact and the
   position of the CLI warning exactly as they are. Extend the message only
   if the bound in (3) is actually reached.
5. **Update the documentation**: `references/validation_methods.md`,
   "Inert Parameter Grids" currently states that the check is a screen, not a
   proof — replace that paragraph with the new (stronger) statement and the
   bound that remains. `SKILL.md`: the research-integrity tip and the
   `test_inert_param_grid.py` inventory / coverage entries.
6. **Extend the regression tests** (`tests/test_inert_param_grid.py`): the
   demonstration from (1), the fix's behaviour on the shipped strategies (the
   four previously probed grids must not change), the bound in (3), and the
   standing invariant that the measurement changes no return, cost, impact,
   capacity or selection number.

## Constraints for the next session

- **Do not change any return, cost, impact, capacity or selection number.**
  The detector is a measurement; the fix must not move a single number.
- Do not change the reporting surface: the artifact keys, the sidecar file
  name and the CLI warning position stay as they are.
- The full **16-file** suite must stay green (the 15 previous + the new
  `test_no_selection_diagnosis.py`); pyflakes must not add new warnings on
  the changed files (`scripts/walk_forward.py` is at 5, `scripts/reporting.py`
  at 2, `tests/test_cpcv.py` at 4 — all pre-existing).
- **Do not "fix" the CPCV defaults.** The effective out-of-sample fraction
  (`test_size / n_splits` = 1% at the defaults, 5-bar fold windows on the
  shipped sample) is a design question that changes every CPCV number; it is
  now diagnosed and documented, not patched.
- `matplotlib` must be installed before trusting a green suite; revert
  `examples/example_output/tear_sheet.{html,json}` and `data_provenance.json`
  after any suite run.
- Do not commit unless explicitly asked — leave the working tree inspectable.

## Alternative tasks, if the primary one is blocked

- **Diagnose partial selection**: when *some* folds select and others do not
  (`--n-splits 5 --test-size 0.2` on the shipped sample selects in 2 of 5
  folds), the artifact reports `folds_with_position: 2` but not why the other
  folds stayed flat. The diagnosis vocabulary of this session
  (`_diagnose_no_selection`) could be extended to that case.
- **Build the parity harness** (`baseline_capture.py` / `book_cap_probe.py`)
  that captures a baseline run and compares the framework against an
  independent re-implementation of the same methodology (the net-exposure vs
  book pricing gap). Larger scope; needs a precise definition of what
  "parity" means before any code is written.

## Useful context that is already settled (do not re-litigate)

- **Every path that can select nothing now says why**, with one vocabulary:
  `summary["no_selection_diagnosis"]` (`{cause, message, details}`) on
  `cpcv_analysis`, `walk_forward_analysis` and the out-of-sample failure
  summary; the cause is `no_validation_windows` or
  `no_position_in_validation_window`. The remedy names the flags the path's
  own subcommand accepts, and the CPCV message states the effective
  out-of-sample fraction.
- **The overfitting-risk verdict is `null` ("not applicable") when nothing
  could be selected**, with an `overfitting_risk_reason`; a run that did
  select keeps its categorical verdict. Before this session CPCV said `high`
  and walk-forward said `low` for the same state.
- Inert parameter grids are detected on all four analysis paths
  (`walk-forward`, `cpcv`, `optimize`, `out-of-sample`), recorded in the
  artifacts and printed once by the CLI. Keep the split: the library measures
  (`_inert_grid_report`), the CLI prints (`_print_inert_grid_warning`).
- The impact model is still linear in the participation rate (no
  temporary/permanent split, no gap risk), and the parity harness does not
  exist. Both are still open.

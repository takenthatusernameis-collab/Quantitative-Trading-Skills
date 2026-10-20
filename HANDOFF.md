# HANDOFF

## What changed this session

**Completed the task assigned in `HANDOFF_NEXT.md`: the inert-parameter-grid
detector no longer falsely accuses a parameter that only matters in
combination with another parameter.** The check now compares each grid key
across *every* combination of the other grid keys' values instead of only
the combination that holds them at their first value, with a bounded cost
and an explicit statement in the finding when the bound was reached.

### The defect, demonstrated before it was fixed

A strategy that reads a parameter only inside a branch is the ordinary way a
parameter's effect becomes conditional on another parameter. The
demonstration strategy in the new test reads `threshold` only when
`mode == "b"`:

```python
mode "a": long when close > 3-bar mean
mode "b": long when (close - 3-bar mean) > threshold
```

On the six-bar fixture, the two modes agree at `threshold = 0.05` and
differ at `threshold = 0.1`. The old rule varied one key while holding the
other at its **first** value, so it compared `(mode=a, threshold=0.05)` with
`(mode=b, threshold=0.05)` — no difference — and accused `mode` of being
inert; and it compared `(mode=a, threshold=0.05)` with
`(mode=a, threshold=0.1)` — no difference — and accused `threshold` of being
inert. **Both live parameters were accused, twice over.** A false accusation
is worse than no accusation: it teaches the reader to ignore the warning.

The evidence is pinned in the test file itself: the old rule is re-implemented
verbatim in `tests/test_inert_param_grid.py` (`_first_value_inert_keys`) and
asserted to accuse `["mode", "threshold"]`, so the demonstration cannot rot
into a hypothetical.

### Changes

`skills/quantitative-backtesting/scripts/walk_forward.py`

- **`_inert_param_grid_keys_measured`** (new, `scripts/walk_forward.py:3334`) —
  the measurement, with the bound that shaped the answer. For each key it
  enumerates the combinations of the *other* keys' values and compares the
  key's values inside each combination. **Early exit**: the first
  combination that shows a behavioural difference proves the key is live,
  so the remaining combinations are skipped and a live key costs exactly
  what it cost before. A key is accused only when it is inert in *every*
  combination, so a parameter that matters only in combination is never
  accused. An *inconclusive* comparison (the strategy could not be built,
  or could not be fingerprinted) never produces an accusation — the same
  conservative direction the old rule took when the first value could not
  be built.
- **The bound** — `_INERT_GRID_MAX_COMBINATIONS = 16` combinations of the
  other values per key. The exhaustive comparison costs
  `len(values) x product(len(other values))` fingerprints per key, which is
  unbounded in the size of the grid. A grid that fits in the bound is
  checked exhaustively; a grid that does not **falls back to the first
  combination** (the old first-value behaviour) and the finding says so.
  The product is consumed lazily, so a large grid does not materialise
  millions of tuples.
  The bound can only weaken an *inert* verdict: a key that shows a
  behavioural difference is live whatever the bound (one difference is proof
  of liveness), so a bounded check never accuses a live key.
- **`_inert_param_grid_keys`** — the same signature plus an optional
  `max_combinations`; it is now a thin wrapper over the measured helper.
- **`_inert_grid_report`** (`scripts/walk_forward.py:3471`) — the same three
  keys (`inert_grid_params`, `strategy_parameters`, `message`) and the same
  wording, **plus** a caveat sentence when the check of an accused key was
  bounded: *"The check for X was bounded: the combinations of the other grid
  values exceed the bound of 16, so only the first was evaluated (the other
  grid keys held at their first value) and it may have missed an interaction
  between parameters."*
- **Nothing else moved.** The reporting surface is unchanged: the same
  summary keys, the same `parameter_optimization_inert_grid.json` sidecar,
  the same CLI warning position, and the same message text whenever the
  bound was not reached.

`skills/quantitative-backtesting/tests/test_inert_param_grid.py` — **11 new
tests (16 → 27)**: the behavioural fact behind the demonstration, the old
rule's false accusation, the exoneration of both keys, the continued
accusation of a key that is inert in *every* combination, the pinned
verdicts of the shipped strategies, the bound (message caveat, the fallback,
a bounded check that never accuses a live key), the unchanged report keys,
and the invariant that the measurement moves no number on the walk-forward
path (the summary differs only in the two keys that carry the finding).

`skills/quantitative-backtesting/references/validation_methods.md` — "Inert
Parameter Grids": the "screen, not a proof" paragraph replaced by the
exhaustive statement (a key is inert only when it changes nothing in *every*
combination) and a new "The bound" paragraph (16 combinations per key, the
fallback, the caveat, and why the bound can only weaken an inert verdict).

`skills/quantitative-backtesting/SKILL.md` — the research-integrity tip and
both `test_inert_param_grid.py` entries (inventory and coverage) describe
the exhaustive comparison and the bound.

## What was actually verified

- **The demonstration fails without the fix.** With the exhaustive
  comparison reverted to the first-value rule, `test_inert_param_grid.py`
  reports **25/27** — `test_a_key_that_matters_only_in_combination_is_not_accused`
  and `test_the_bound_is_a_bound_and_not_a_silent_truncation` fail. With the
  fix: **27/27**.
- **Numeric parity with HEAD (`75936b3`) on ten CLI cases — 10/10
  byte-identical.** Every artifact key of every artifact is equal, including
  the `inert_grid_params` and `inert_grid_message` of the runs that *do*
  find an inert grid. No return, Sharpe, stability, capacity or selection
  number changed anywhere. Script and artifacts:
  `/home/runner/work/_temp/kilo-tmp/kilo/parity2/parity_check.py` and
  `parity2/{head_out,new_out}/`.

  | Case | Difference found |
  | ---- | ---------------- |
  | `optimize` (live grid) | **none** |
  | `optimize` (inert grid) | **none** |
  | `optimize` (mixed grid) | **none** |
  | `optimize --impact-coefficients 0.0 0.0001` (inert grid, sweep) | **none** |
  | `walk-forward` (live grid) | **none** |
  | `walk-forward` (inert grid) | **none** |
  | `cpcv` (live grid) | **none** |
  | `cpcv` (inert grid) | **none** |
  | `out-of-sample` (walk-forward, inert grid) | **none** |
  | `out-of-sample` (walk-forward, live grid) | **none** |

- **The shipped strategies keep their verdicts.** The old rule (re-implemented
  verbatim) and the new exhaustive check agree on **78/78** comparisons
  (6 strategies x 13 grids): `/home/runner/work/_temp/kilo-tmp/kilo/parity_inert.py`.
  The reason is structural, not lucky: **no shipped strategy reads a
  parameter conditionally on another parameter** (checked by scanning
  `scripts/strategy_builder.py`), so no shipped grid can exhibit the
  interaction the fix is about. The fix therefore changes **no** shipped
  verdict — it removes a *latent* false-accusation capability.
- **The full suite is green — 16 files**:
  `test_cpcv` 29/29, `test_data_loader` 32/32, `test_examples_coverage` 7/7,
  `test_execution_warmup` 8/8, `test_falsifiable_hypothesis_example` 3/3,
  `test_generate_sample_data` 2/2, `test_inert_param_grid` **27/27**,
  `test_monte_carlo` 20/20, `test_no_selection_diagnosis` 12/12,
  `test_out_of_sample_window` 10/10, `test_panel_reference_pinned` 2/2,
  `test_performance` 33/33, `test_reporting` OK, `test_run_backtest` 104/104,
  `test_strategy_builder` 33/33, `test_walk_forward` 177/177.
- **pyflakes unchanged**: `scripts/walk_forward.py` 5 warnings (the same as
  HEAD: 1 unused import + 4 "f-string is missing placeholders"),
  `scripts/reporting.py` 2 (same as HEAD), `tests/test_cpcv.py` 4 (same as
  HEAD), the new test file **0**.
- **The bounded path was exercised end to end**: `optimize` with a six-key
  grid prints the caveat once, next to the ranking, and the sidecar carries
  the same message.
- The suite rewrites `examples/example_output/tear_sheet.{html,json}` and
  `data_provenance.json`; they were reverted, so the working tree holds no
  example-output changes.

## What remains unresolved

- **Partial selection is still undiagnosed.** Verified this session:
  `cpcv --n-splits 5 --test-size 0.2` on the shipped sample selects in
  **2 of 5** folds (`best_params_per_fold` =
  `[params, None, None, params, None]`, `folds_with_position: 2`), and the
  artifact says **nothing** about the three flat folds. The library shows
  the flat folds are *not* short-window folds: they carry the same 20 test
  bars as the selecting folds and simply produced no position
  (`test_returns` empty). `no_selection_diagnosis` is correctly absent (some
  fold selected), and `overfitting_risk: low` is reported on the basis of
  2 folds out of 5 with no caveat. This is the next task.
- **The `monte-carlo` path** picks its "best params" from
  `parameter_optimization` and therefore has the same null-experiment
  exposure, but records and prints nothing.
- **The inert check is measured over the full sample**, while the selection
  happens inside each fold / period. A key that is live over the whole
  sample but inert in *every* training window would therefore be reported
  as live, although each fold's search over it is a null experiment. Not
  demonstrated; a per-window measurement would change the reporting
  surface.
- Unchanged from before: the impact model is still linear in the
  participation rate (no temporary/permanent split, no gap risk); the parity
  harness (`baseline_capture.py` / `book_cap_probe.py`) does not exist; an
  explicitly requested walk-forward window is still adapted rather than
  enforced; the CPCV default is still the 1% effective out-of-sample
  fraction (diagnosed and documented, deliberately not changed).

## Approaches that have already failed (do not repeat)

- **Keeping the first-value comparison and only documenting the limitation.**
  That is what the previous session did: the limitation was described in
  `references/validation_methods.md` and left in place, because it had
  never been *demonstrated*. The demonstration (an interacting strategy) is
  cheap and settles it — the false accusation is real, and it fires on
  **both** keys of the grid at once.
- **Evaluating the first `cap` combinations and reporting the result.** That
  is a partial answer presented as a complete one, which is exactly what
  the handoff forbade. The fallback is the *whole* first combination (the
  old behaviour) plus an explicit statement that the check was bounded.
- **Materialising `itertools.product` before slicing it.** The combination
  count of a 8-key x 5-value grid is 5 ** 7 = 78 125 per key; building the
  list first is a memory blow-up on a large grid. The product is consumed
  lazily (`next(product(...), ())`).
- **Caching fingerprints across keys.** The same parameter set is evaluated
  once per key it belongs to, so a cache would help — but it changes the
  cost model and the bound's meaning for a saving that was never measured.
  Left alone; the bound makes the cost affordable without it.
- (unchanged from before) Printing the warning from inside the analysis
  functions; making the optimize artifact a dict; hard-failing on an inert
  grid; changing the CPCV defaults; adding a new artifact key to the
  reporting surface.

## Git state

Working tree (not committed — the harness commits the session's work together
with these handoff files, as in `75936b3`):

- modified: `skills/quantitative-backtesting/scripts/walk_forward.py`,
  `references/validation_methods.md`, `SKILL.md`,
  `tests/test_inert_param_grid.py`
- new: nothing (the new tests live in the existing test file)

HEAD is `75936b3`.

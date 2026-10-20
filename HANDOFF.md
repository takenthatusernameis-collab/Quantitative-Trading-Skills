# HANDOFF

## What changed this session

**Completed the task assigned in `HANDOFF_NEXT.md`: a run in which only
*some* windows selected a parameter now says which windows were flat, why
(measured in the search, not inferred), and how many windows the
overfitting-risk verdict rests on.**

### The defect, demonstrated before it was fixed

`cpcv --n-splits 5 --test-size 0.2` on the shipped sample selects a
parameter in **2 of 5** folds. Before this session the artifact said
exactly that much and nothing more:

```
$ python3 .../walk_forward.py cpcv --data assets/example_data/sample_ohlcv.csv \
      --strategy sma_crossover --param-grid '{"fast_period":[5,10],"slow_period":[20,30]}' \
      --n-splits 5 --test-size 0.2
...
folds_with_position: 2      overfitting_risk: low      (no reason, no cause)
```

Verified against the pre-fix code (`HEAD:skills/.../walk_forward.py`):
the summary carried **no key at all** that named a cause, a reason or a
per-window breakdown for the three flat folds. "2 of 5 folds selected" is
compatible with two opposite readings — "the three flat folds were too
short to trade" (a design problem) and "the strategy never triggers on
60% of the sample" (a finding about the strategy) — and the two need
opposite remedies. A categorical `overfitting_risk: low` was reported on
the basis of two folds out of five with no caveat.

The demonstration is pinned in the test file itself
(`test_the_pre_fix_artifact_named_no_cause_for_the_flat_folds`): the
summary with the new keys removed is asserted to contain no cause/reason/
diagnosis key and to contain the count, so the demonstration stays true
after the fix and fails loudly if the pre-fix information ever changes.

### The inference the handoff expected turned out to be wrong

The handoff recorded the library's reading of the flat folds as "no
position" (`test_returns` empty). That is **not** what the empty result
proves, and the session's own fixture shows why: a window can select
nothing because *no combination took a position in it* (the search's
position guard rejected every combination) **or** because *every
combination took a position but the training split produced a constant
return series*, so the in-sample Sharpe the selection ranks on is
undefined and nothing can be ranked. The two look identical from the
outside and need opposite remedies (lengthen the window vs. give the
training split more history).

So the cause is now **measured inside the search**: the grid search
records a tally of what happened to every combination
(`selection_outcomes` on the period / fold record), and the diagnosis
reports the cause that tally attributes to each window.

### Changes

`skills/quantitative-backtesting/scripts/walk_forward.py`

- **`_diagnose_partial_selection`** (new) — the per-window diagnosis. It
  returns `None` unless the run is in the partial state (some windows
  selected, some did not), so the all-flat case keeps using
  `no_selection_diagnosis` unchanged, and a run in which every window
  selected carries no partial diagnosis. Per flat window it reports the
  cause, the reason, the window's length, its training-split length, its
  empty out-of-sample record (`test_returns_bars`, `test_sharpe`), the
  most bars any combination could have held a position for, the calendar
  boundaries, the outcome tally and a one-line statement. The cause
  vocabulary is the one the "no parameter could be selected" diagnosis
  already uses, extended with the two causes it could not tell apart:
  `no_estimable_training_sharpe` (every combination took a position, the
  training Sharpe is not estimable) and `all_combinations_failed` (every
  combination raised).
- **The search now measures two things it used to throw away**
  (`walk_forward_analysis` and `cpcv_analysis`): `selection_outcomes`
  (the tally of `eligible` / `flat` / `degenerate_training` / `failed`
  combinations) and `position_bars` / `max_position_bars` (the bars the
  strategy actually held a position — the *amount of evidence* a window
  contributes). Both are pure measurements: they change no return, Sharpe,
  stability, capacity or selection number.
- **`_window_position_bars`** (new) / **`_window_takes_position`** (now a
  thin wrapper over it) — the position test now also reports *how many*
  bars the strategy held a position. The book-pricing branch keeps the
  original semantics exactly (a panel book that cannot be held is no
  position; the scalar signal test is not a fallback there).
- **The verdict is qualified, not changed.** The CPCV summary and the
  walk-forward `overfitting_check` keep the categorical verdict
  (`overfitting_risk: low`) and gain an `overfitting_risk_reason` that
  states how many of the windows it rests on and points at
  `summary["partial_selection_diagnosis"]`. A run that selected in every
  window keeps no reason at all, and the all-flat case keeps its "not
  applicable" reason.
- **`_selection_window_remedy` / `_selection_training_remedy` /
  `_effective_oos_fraction_sentence`** (new, shared) — the remedies and
  the CPCV effective-fraction sentence, extracted from
  `_diagnose_no_selection` so both diagnoses name the same knobs and the
  same flags. The `no_selection_diagnosis` message text is unchanged
  (byte-identical).
- **`_print_partial_selection_diagnosis`** (new) — the CLI prints the
  message and one line per flat window, next to the fold / period count,
  so the console and the artifact carry the same strings.

`skills/quantitative-backtesting/tests/test_no_selection_diagnosis.py` —
**12 new tests (12 → 24)**: the pinned facts of the partial run, the
pre-fix demonstration, the per-window breakdown, the "the flat folds are
not short windows" measurement, the qualified-but-unchanged verdict, the
walk-forward and out-of-sample paths (with a deterministic flat-then-rising
fixture that produces both causes), the remedy's flags against each
subcommand's `--help`, the all-selected and all-flat cases, the
"changes no number" invariant, and the CLI/artifact agreement.

`skills/quantitative-backtesting/references/validation_methods.md` — a new
section "When Only Some Windows Select a Parameter" (the partial key, the
cause table, the per-window record fields, the traded-window record, and
how "too short" and "never triggered" are separated by a measurement).

`skills/quantitative-backtesting/SKILL.md` — the research-integrity tip and
the `test_no_selection_diagnosis.py` inventory entry.

## What was actually verified

- **The demonstration is real.** Against the pre-fix code the partial
  CPCV run's summary keys were
  `['avg_fold_return', ..., 'folds_with_position', ..., 'overfitting_risk', ...]`
  — **no** key naming a cause, a reason or a diagnosis — and
  `overfitting_risk: low` with no reason. After the fix the same run
  carries `partial_selection_diagnosis` (per-window breakdown) and
  `overfitting_risk_reason`, and the verdict value is unchanged.
- **Numeric parity with HEAD (`62b67d3`) on ten CLI cases — 10/10
  identical.** Every artifact key that exists on both sides holds the same
  value; the only additions are the new diagnosis keys
  (`summary.partial_selection_diagnosis.*`,
  `summary.overfitting_risk_reason`, `diagnostics.overfitting_risk_reason`).
  Script: `/home/runner/work/_temp/kilo-tmp/kilo/partial_parity.py`.

  | Case | Difference found |
  | ---- | ---------------- |
  | `optimize` (live grid) | **none** |
  | `optimize` (inert grid) | **none** |
  | `walk-forward` (live grid) | **none** |
  | `walk-forward` (inert grid) | **none** (adds the diagnosis only) |
  | `cpcv` (live grid) | **none** |
  | `cpcv` (inert grid) | **none** |
  | `cpcv --n-splits 5 --test-size 0.2` (the partial case) | **none** (adds the diagnosis only) |
  | `out-of-sample` (walk-forward, inert grid) | **none** |
  | `out-of-sample` (walk-forward, live grid) | **none** |
  | `out-of-sample` (cpcv, partial configuration) | **none** |

- **The panel / book-pricing path is byte-identical to HEAD** for both
  pricing conventions on the committed panel fixture
  (`/home/runner/work/_temp/kilo-tmp/kilo/panel_parity.py`). This is the
  check that caught a real defect during the session: the first version of
  `_window_position_bars` fell back to the scalar signal test when the
  held book was `None`, which the original `_window_takes_position` did
  not do (it returned "no position"). The fix restored the original
  semantics; the pinned panel reference (`test_panel_reference_pinned.py`)
  passed either way, so the parity check is the one that mattered.
- **The full suite is green — 16 files**:
  `test_cpcv` 29/29, `test_data_loader` 32/32, `test_examples_coverage` 7/7,
  `test_execution_warmup` 8/8, `test_falsifiable_hypothesis_example` 3/3,
  `test_generate_sample_data` 2/2, `test_inert_param_grid` 27/27,
  `test_monte_carlo` 20/20, `test_no_selection_diagnosis` **24/24**,
  `test_out_of_sample_window` 10/10, `test_panel_reference_pinned` 2/2,
  `test_performance` 33/33, `test_reporting` OK, `test_run_backtest` 104/104,
  `test_strategy_builder` 33/33, `test_walk_forward` 177/177.
- **pyflakes unchanged**: `scripts/walk_forward.py` 5 warnings (the same as
  HEAD: 1 unused import + 4 "f-string is missing placeholders"),
  `scripts/reporting.py` 2 (same as HEAD), `scripts/strategy_builder.py` 2
  (same as HEAD), `scripts/monte_carlo.py` 1 (same as HEAD),
  `tests/test_cpcv.py` 4 (same as HEAD), `tests/test_no_selection_diagnosis.py`
  **0**.
- The suite rewrites `examples/example_output/tear_sheet.{html,json}` and
  `data_provenance.json`; they were reverted, so the working tree holds no
  example-output changes.

## What remains unresolved

- **The "too short" vs "never triggered" distinction is a comparison, not a
  mechanism.** The diagnosis compares a flat window's length with the
  shortest window in which the strategy traded; a window that is *one bar*
  shorter is reported as "the window length cannot be ruled out". The
  framework has no generic measure of a strategy's indicator warm-up, so
  it cannot say "the warm-up is longer than the window" the way the
  all-flat message does. Not demonstrated to be wrong, but the claim is
  weaker than the all-flat message's.
- **The all-flat message still asserts a cause it does not measure.**
  `no_selection_diagnosis.message` says "no parameter combination took a
  position in any of them", which the new tally shows is not always the
  reason (a window can also be unusable because its training split is
  degenerate). The handoff for this session required the all-flat case to
  stay exactly as it was, so it was left unchanged — deliberately, not
  overlooked. The fix now has the measurement needed to correct it
  (`selection_outcomes`).
- **The evidence the verdict rests on is thinner than the window count
  suggests.** In the canonical partial case the two selecting folds held
  the position for **1 bar out of 20** each, so the run's out-of-sample
  record is a flat one (`total_oos_return: 0.0`, `oos_sharpe: 0.0`). The
  new artifact reports this
  (`details["traded_windows"][*]["position_bars"]`,
  `details["min_traded_position_bars"]`), but nothing yet *acts* on it: a
  run whose evidence is a handful of bars is not flagged as such.
- **The `monte-carlo` path** still picks its "best params" from
  `parameter_optimization` and records and prints nothing; it inherits the
  same partial-selection exposure.
- **The inert check is still measured over the full sample**, while the
  selection happens inside each fold / period (unchanged from before).
- Unchanged from before: the impact model is still linear in the
  participation rate; the parity harness (`baseline_capture.py` /
  `book_cap_probe.py`) does not exist; an explicitly requested walk-forward
  window is still adapted rather than enforced; the CPCV default is still
  the 1% effective out-of-sample fraction (diagnosed and documented,
  deliberately not changed).

## Approaches that have already failed (do not repeat)

- **Inferring the per-window cause from the empty result.** The handoff's
  reading ("no position", because `test_returns` is empty) is not
  entailed: the session's own fixture has a window where every
  combination *did* take a position and the window still selected
  nothing, because the training split produced a constant return series.
  Any implementation that infers the cause from the empty result will
  mislabel that window. The cause has to be counted in the search.
- **Re-running the grid search for the flat windows to find out why.**
  This duplicates the selection logic, so the diagnosis would drift from
  the search whenever the search changes, and it would have to re-derive
  the cost model. Counting the outcome inside the search is both cheaper
  and exact.
- **Comparing the flat window's length with the traded windows' length
  only.** The comparison is necessary but not sufficient: it separates
  "shorter" from "not shorter", not "the length is the cause" from "the
  length is irrelevant". The window-length remedy is therefore stated as
  a knob to reach for, not as the fix, whenever the measurement does not
  support it.
- (unchanged from before) Printing the warning from inside the analysis
  functions; hard-failing on an inert grid; changing the CPCV defaults;
  adding a new artifact key to the reporting surface outside the
  diagnosis.

## Git state

Working tree (not committed — the harness commits the session's work together
with these handoff files, as in `62b67d3`):

- modified: `skills/quantitative-backtesting/scripts/walk_forward.py`,
  `references/validation_methods.md`, `SKILL.md`,
  `tests/test_no_selection_diagnosis.py`
- new: nothing (the new tests live in the existing test file)

HEAD is `62b67d3`.

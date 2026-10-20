# HANDOFF — next session

Read `HANDOFF.md` first: it records what the last session changed, what it
verified, and what it deliberately left alone.

## State of the work

The last session completed the **partial selection diagnosis** (the task
this file used to carry). A run in which only *some* windows selected a
parameter now records `summary["partial_selection_diagnosis"]` with a
per-window breakdown, and the overfitting-risk verdict keeps its
categorical value but gains a reason that states how many windows it
rests on. The cause of every flat window is **measured inside the search**
(`selection_outcomes` on the period / fold record), not inferred from the
empty result.

The all-flat case (`summary["no_selection_diagnosis"]`) is unchanged, as
the previous handoff required.

## The next task

**Flag a run whose evidence is too thin to support the verdict it
carries.**

The partial diagnosis now *reports* the amount of evidence
(`details["traded_windows"][*]["position_bars"]` and
`details["min_traded_position_bars"]`), but nothing acts on it. The
canonical case shows why this matters: in
`cpcv --n-splits 5 --test-size 0.2` on the shipped sample, the two folds
that selected a parameter held the position for **1 bar out of 20** each,
so the run's out-of-sample record is a flat one
(`total_oos_return: 0.0`, `oos_sharpe: 0.0`) and the `low`
overfitting-risk verdict rests on two bars of trading.

The task: decide, measure and state a **minimum evidence threshold** for a
selection to count as evidence, and report a run that falls below it as
what it is.

Constraints and evidence to build on:

- The measurement already exists: `position_bars` is recorded per window
  by the search (the selected combination's count, and the maximum over
  the grid). The out-of-sample path's *validation* and *test* windows do
  not carry it yet — `out_of_sample_validation` computes
  `val_returns` / `test_returns` directly, so the same count would have
  to be added there.
- Do **not** change any number: the threshold is a reporting statement,
  like the other diagnoses, not a filter that drops windows from a
  result. A run that fails the threshold must still report every number
  it produced.
- The threshold has to be *measured*, not chosen to look good: the natural
  candidate is the fraction of the window the strategy held a position
  for, and the natural reference is the execution warm-up the framework
  already reports (`execution_warmup_bars`,
  `summary["warmup_convention"]`), because a window in which the strategy
  is only tradable for a few bars after the warm-up cannot support a
  verdict about the strategy.
- Keep the same vocabulary discipline the last session used: a new finding
  gets a new key and an explicit cause, and the existing
  `no_selection_diagnosis` / `partial_selection_diagnosis` keys keep
  their meaning.
- The evidence the next session should produce: the threshold and the
  measurement behind it; the runs it fires on (the canonical partial CPCV
  run is the obvious one); a demonstration that the artifact says nothing
  today; and a numeric parity check against HEAD
  (`/home/runner/work/_temp/kilo-tmp/kilo/partial_parity.py` is the
  harness to extend — it compares every artifact key of ten CLI cases
  against the pre-fix code and fails on any value that moved).

## Also worth doing, in order of value

1. **Correct the all-flat message, which asserts a cause it does not
   measure.** `no_selection_diagnosis.message` says "no parameter
   combination took a position in any of them", but the new
   `selection_outcomes` tally shows that a window can also be unusable
   because its training split produced a constant return series (the
   in-sample Sharpe is not estimable). The previous session's handoff
   required the all-flat case to stay exactly as it was, so it was left
   alone deliberately; now that the measurement exists, the all-flat
   cause can be derived from it instead of assumed.
2. **Make the "too short" claim mechanism-based.** The diagnosis
   compares a flat window's length with the shortest window in which the
   strategy traded; a window one bar shorter is reported as "the window
   length cannot be ruled out". The framework has no generic measure of a
   strategy's indicator warm-up, so it cannot say "the warm-up is longer
   than the window" the way the all-flat message does. A warm-up
   measurement (e.g. the first bar at which a combination can hold a
   position) would make the claim mechanism-based instead of comparative.
3. **Extend the reporting surface to the `monte-carlo` path**, which
   inherits the same partial-selection exposure and records nothing.

## Constraints that carry over

- The `optimize` path stays out of scope for the selection diagnoses: it
  has no windows, so there is nothing to diagnose.
- The framework's "grid search" vocabulary is load-bearing: a grid whose
  values do not change the strategy's behaviour is a null experiment, and
  the inert-grid detector reports it on every path that selects
  (`summary["inert_grid_params"]`). A new finding must not be confused
  with it.
- The reporting surface is deliberately small. A new key is a change to
  the contract; the last session added exactly one key
  (`partial_selection_diagnosis`) and one reason field
  (`overfitting_risk_reason`).
- The example outputs under `skills/quantitative-backtesting/examples/`
  are regenerated by the test suite (the timestamp and the matplotlib
  plot files change on every run). Revert them before handing the work
  over: `git checkout -- skills/quantitative-backtesting/examples/`.

## Where the code is

- `skills/quantitative-backtesting/scripts/walk_forward.py`
  - `_diagnose_partial_selection` — the per-window diagnosis.
  - `_diagnose_no_selection` — the all-flat diagnosis (unchanged).
  - `_selection_window_remedy`, `_selection_training_remedy`,
    `_effective_oos_fraction_sentence` — the shared remedies.
  - `_window_position_bars` / `_window_takes_position` — the position test
    and the bar count.
  - `selection_outcomes`, `position_bars`, `max_position_bars` — the
    measurements recorded on the period / fold records.
  - `overfitting_check` — the walk-forward verdict and its reason.
- `skills/quantitative-backtesting/tests/test_no_selection_diagnosis.py` —
  24 tests, including the partial-selection ones and the pinned
  demonstration.
- `skills/quantitative-backtesting/references/validation_methods.md` —
  "When No Parameter Can Be Selected" and "When Only Some Windows Select
  a Parameter".

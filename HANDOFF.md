# Handoff — 2026-10-21 (session)

## What changed

This session completed the assigned task from `HANDOFF_NEXT.md`: **the reference document now states why the held-out-fraction sweep (`--test-fracs`) is measured on the out-of-sample path only** — and, in doing so, **corrects two factual errors the statement carried**.

The assigned task turned out to be *already implemented* in `references/validation_methods.md` (the paragraph was in the committed tree), but the paragraph was wrong in two places. The work this session was therefore to make the statement true, not to add it.

### 1. The correction (`skills/quantitative-backtesting/references/validation_methods.md`)

The sweep's section said:

> "the walk-forward and CPCV paths are configured in *months* (6-month training window, 2-month test window, **1-month step**)"

Both halves of that were wrong:

- **The step window is 2 months, not 1.** The shipped configuration is
  `WF_TRAIN_MONTHS, WF_TEST_MONTHS, WF_STEP_MONTHS = 6, 2, 2`
  (`scripts/measure_resolution_vs_sample_size.py:209`), and the worked
  example passes `walk_forward_step_months=2`
  (`examples/falsifiable_hypothesis_example.py:334`). The same document
  already said "2-month test and step windows" 120 lines above
  (`references/validation_methods.md:1685`), so the document contradicted
  itself.
- **The CPCV path is not month-configured.** It is configured in a number of
  splits and a per-group test fraction (`CPCV_N_SPLITS, CPCV_TEST_SIZE = 5,
  0.2`, `scripts/measure_resolution_vs_sample_size.py:214`): the sample is
  re-split into 5 sequential groups and the first 20% of each group is that
  group's test set. It has no month-based windows at all.

The paragraph now says the true reason, which is also the crisper one: **the
out-of-sample path is the only one of the three whose split is expressed as
fractions of the sample**, and the framework agrees — of the three analyses,
only `out_of_sample_validation` takes a `test_frac` at all
(`walk_forward_analysis` takes `train_months`/`test_months`/`step_months`,
`cpcv_analysis` takes `n_splits`/`test_size`).

No threshold, bound, criterion or verdict moved. `scripts/walk_forward.py`
and `scripts/measure_resolution_vs_sample_size.py` are **not in this
session's diff** — the diff is the reference document and one test file.

### 2. The configuration the cross-reference pointed at

The sweep's section refers the reader to "The three analysis paths answer it
differently" for the per-path configuration — but that section stated only
what each path *prices its test on*, not how each path is *configured*. It
now carries the three configurations explicitly (fractions / months /
splits), so the cross-reference resolves to a real statement.

### 3. The skill's entry point (`skills/quantitative-backtesting/SKILL.md`)

`SKILL.md` describes `--test-fracs` but did not say which path it measures,
so a reader who meets the flag in the skill's own summary could assume the
sweep covers all three paths. It now carries the same one-clause scope
statement as the reference document, and the pin checks it there too.

### 4. The pin (`skills/quantitative-backtesting/tests/test_resolution_vs_sample_size.py`)

New test `test_the_sweeps_scope_is_the_frameworks_own_and_the_docs_say_so`,
registered in `TEST_REGISTRY` (so `test_every_test_in_this_file_is_registered`
covers it). It pins the scope against three independent sources:

1. **the framework's own signatures** — `out_of_sample_validation` takes a
   `test_frac`; `walk_forward_analysis` and `cpcv_analysis` do not (and the
   latter two take `train_months`/`test_months`/`step_months` and
   `n_splits`/`test_size` respectively);
2. **the measurement's own default** — `measure_test_frac_sweep`'s `paths`
   default is `(out_of_sample,)`;
3. **the document's wording** — the sweep's section states that the sweep is
   measured on the "out-of-sample path only", says how the CPCV path is
   configured, does not credit the CPCV path with a month-based
   configuration, and names the *shipped* configuration: the walk-forward
   6/2/2 months, the CPCV 5 splits and 20% of each group, and the
   out-of-sample 0.6/0.2/0.2 split. The month numbers are read out of the
   document with a regex and compared to the code constants, so a stale
   number in the prose fails the pin rather than passing it.
4. **`SKILL.md`** says the same thing, so the two documents cannot drift
   apart on the sweep's scope.

## What was actually verified

- The new pin passes: `test_the_sweeps_scope_is_the_frameworks_own_and_the_docs_say_so`
  and `test_every_test_in_this_file_is_registered` are green.
- **The pin was negative-controlled.** Three mutations of the document were
  applied one at a time, and each one made the pin fail:
  - the step window changed back to "1-month step" → fails on the shipped
    walk-forward configuration;
  - the CPCV path credited with a month-based configuration → fails on the
    CPCV's own configuration;
  - the "out-of-sample path only" statement removed → fails on the scope
    statement.
  The document was restored byte-for-byte after the mutations
  (`restored: True`).
- The framework signatures quoted above were read from the code, not assumed:
  `inspect.signature` on `out_of_sample_validation`, `walk_forward_analysis`
  and `cpcv_analysis`; the constants were read from
  `scripts/measure_resolution_vs_sample_size.py` and cross-checked against
  `examples/falsifiable_hypothesis_example.py`.
- The full file `tests/test_resolution_vs_sample_size.py` was re-run end to
  end in this session: **40/40 tests passed** (the run includes the slow
  live re-measurements of the 25,000-bar and 50,000-bar rungs). It was then
  repeated on the final tree — with the `SKILL.md` clause and its assertion
  added — and that run is green too: `40 PASS`, `0 FAIL`, exit 0, including
  `test_the_sweeps_scope_is_the_frameworks_own_and_the_docs_say_so` and
  `test_every_test_in_this_file_is_registered`.
- No other test file reads `references/validation_methods.md` (checked:
  `grep -rn "read_text" tests/*.py`), so the document change cannot move a
  number anywhere else.

## What remains unresolved

- **The environment has no matplotlib.** numpy and pandas were installed in
  this session (`pip install numpy pandas`) because the skill's scripts
  import them; matplotlib is still absent, so `tests/test_reporting.py`
  (the figure-generating tests) could not be run here. This session's diff
  does not touch reporting, but the next session should install
  `skills/quantitative-backtesting/requirements.txt` in full before
  running the whole suite.
- **The pre-driver ladder fixture is still a second source of truth.**
  `tests/fixtures/resolution_ladder_2500_to_50000.json` keeps the 10-key
  path blocks (no driver, no status), so a summary built from *it* still
  says the alpha-floor driver "is not measurable on this ladder", while the
  re-capture fixture says it is. This was already flagged in the previous
  handoff and is unchanged here.
- The two paths the sweep does not cover (walk-forward, CPCV) still have no
  lever analysis at all. The document now says so; the next task measures
  the walk-forward path's own lever.

## Approaches that failed

- None material. The only environment friction was the missing numpy/pandas
  (installed), and the `background_process` tool for the long suite run
  (used; the earlier session's `nohup … &` capture failure did not recur).

## Next task (one, precise)

**Measure the walk-forward path's window lever: sweep the training window
(`train_months`) and the test window (`test_months`) at a fixed sample size
on the walk-forward path, and report the same resolution numbers the
out-of-sample fraction sweep reports.**

The sweep is out-of-sample-only because the other two paths are configured in
their own units (months and splits) rather than in sample fractions — which
means the walk-forward path has a lever of its own (`train_months`,
`test_months`) that has never been measured. The same trade-off the
out-of-sample sweep exposes is expected to appear there: a longer training
window gives a better-estimated parameter but fewer windows fit in the
sample, and a shorter test window gives more, shorter out-of-sample
observations.

Evidence:

- `skills/quantitative-backtesting/scripts/measure_resolution_vs_sample_size.py`
  — `_run_walk_forward` (line ~318) hard-codes `WF_TRAIN_MONTHS` /
  `WF_TEST_MONTHS` / `WF_STEP_MONTHS`, and `measure_test_frac_sweep`
  (line ~755) is the existing pattern for a fixed-sample-size sweep;
  `walk_forward_analysis` already accepts `train_months`, `test_months` and
  `step_months`.
- `skills/quantitative-backtesting/references/validation_methods.md` —
  "How much of the data should be held out?" (the fraction sweep, the
  pattern to follow) and "The three analysis paths answer it differently"
  (where the result belongs).
- `skills/quantitative-backtesting/tests/test_resolution_vs_sample_size.py` —
  `test_test_frac_sweep_keeps_val_frac_and_sums_to_one` and the sweep's
  other pins, the pattern for the new pins.
- Constraint carried from the framework's own tests: `step_months` must be
  `>= test_months` (`tests/test_walk_forward.py:1059`), so a test-window
  sweep must set the step with it.

Verification: the sweep's numbers are the framework's own blocks (as the
fraction sweep's are), the capture carries its provenance, no threshold,
bound, criterion or verdict moves, and the document says what the window
sweep does **not** establish.

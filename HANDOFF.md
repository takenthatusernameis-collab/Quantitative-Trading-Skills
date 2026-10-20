# Handoff — 2026-10-20 (session)

## What changed

Completed the assigned task in `HANDOFF_NEXT.md`: the walk-forward path's alpha floor was
measured out to 50,000 bars, and the tool's "no sample size would let this path confirm a
plausible alpha" message **does not survive** the measurement. The message is now scoped to
the rungs measured, and the summary reports the case the old code dropped.

### The measurement

`skills/quantitative-backtesting/scripts/measure_resolution_vs_sample_size.py --sizes
2500,5000,10000,25000,50000 --paths out_of_sample,walk_forward,cpcv --series both --seeds
7,1,2024 --json` — the full ladder (five rungs x three seeds x both series x three paths,
30 measured rows) on the synthetic positive-control fixture. The tool's own `--json` output
is committed as the raw record at `results/resolution_floor/ladder_2500_to_50000.json`; the
rows the tests read, trimmed to the framework's own blocks and stamped with provenance
(command, commit, environment, fixture construction), are at
`skills/quantitative-backtesting/tests/fixtures/resolution_ladder_2500_to_50000.json`.

Alpha floor (alpha\*, the worst of the six draws at each rung; the bound is 0.10):

| Path | 2,500 | 5,000 | 10,000 | 25,000 | 50,000 | First rung at which *every* draw is inside the alpha bound |
| --- | --- | --- | --- | --- | --- | --- |
| out-of-sample | 0.0133 | 0.0334 | 0.0361 | 0.0065 | 0.0108 | 10,000 bars |
| walk-forward | 0.1583 | 0.1150 | 0.1047 | 0.0872 | 0.0844 | 50,000 bars |
| CPCV | 0.4864 | 0.1228 | 0.0737 | 0.0073 | 0.0159 | 25,000 bars |

So the walk-forward path's alpha floor is above the 10% bound at every rung up to 10,000
bars and **under** it at 25,000; at 50,000 bars its minimum confirmable alpha is 0.0125 to
0.0936, inside the bound on every draw. Criterion 5 on that path *can* confirm a plausible
alpha at 50,000 bars. The CPCV path crosses at 25,000 and the out-of-sample path at 10,000
(the same rung at which it crosses criterion 2). The 25,000- and 50,000-bar rungs were
measured twice, in two independent runs, and the rows are byte-identical.

### The code fix (`scripts/measure_resolution_vs_sample_size.py`)

Three defects, all in how the tool *reports* the floor. No threshold, bound, criterion or
verdict moved: `PLAUSIBLE_MAX_ANNUALIZED_ALPHA == 0.10` and the 2.00 Sharpe bound are
untouched, and the shipped 0.6/0.2/0.2 split is unchanged.

1. **The conclusion was an absolute claim resting on a finite ladder.** The summary printed
   "no sample size would let this path confirm a plausible alpha" when the floor was above
   the bound at every *measured* rung. The floor falls as the sample grows (it is estimated
   from alphas/Sharpes that are themselves estimated on more data), so a ladder that stops
   before the crossing cannot support that claim — and the measurement shows the claim is
   false for the walk-forward path. The conclusion is now scoped ("no **measured** sample
   size would let this path confirm a plausible alpha (up to N bars)"), and N is named.
   The same scoping was applied to the Sharpe floor's message, which had the same defect.
2. **The case where the floor stops blocking the path printed nothing.** Both branches that
   reported the floor required it to be *above* the bound, so a floor that had come under
   it — the one case in which the floor is no longer the reason a criterion cannot be
   satisfied — was silently absent from the summary. A third branch now reports it ("the
   alpha (alpha\*) floor is at or under the plausibility bound at the largest measured
   sample size (N bars): the floor does not block criterion 5 at that size").
3. **The default ladder could not see the crossing.** `DEFAULT_SIZES` stopped at 10,000
   bars, which is before every criterion-5 crossing, so the default run reported "no
   measured sample size" for paths that have one. It now carries 25,000 and 50,000 as well
   (the two largest rungs are minutes per draw; the `--sizes` help text says so).

The summary also carries a new `largest_measured_size` key, so the range of any conclusion
drawn from the ladder is machine-readable and not only printed.

### Reconciliation with the parallel session's edits

A second session's uncommitted edits landed in the working tree during this one (a
`HANDOFF.md` and an eight-line paragraph in `references/validation_methods.md`, both at
21:49). Its **conclusion was right** — the message does not survive a larger sample — but
the numbers it reported were mislabelled: 0.0390 and 0.0183 are *minimum confirmable
alphas* (the MDE), not the alpha floor, and 0.8744 is the walk-forward path's minimum
confirmable Sharpe, not its floor (SR\* = 0.7681 on that draw). Its doc paragraph has been
replaced with the measured floors over three seeds and both series; its
`HANDOFF.md` is superseded by this one. Its claim that "the conditional message code
already handles this case" was half right: the *flag* flips, but the summary then printed
nothing at all about the floor (defect 2 above).

### Docs

`references/validation_methods.md`: the "Is there such a sample size at all?" subsection now
carries the per-path alpha-floor table over the full ladder, the measured crossings, the
scoped conclusion, and the provenance of the captured ladder. `SKILL.md`: the script's entry
and the "criteria are not unsatisfiable" bullet now state the criterion-5 crossings per path
(10,000 / 50,000 / 25,000 bars) and the scoped conclusion.

## What was actually verified

- `tests/test_resolution_vs_sample_size.py`: **27/27** (was 21; six new), ~10 min.
  `pytest` collects the same 27.
- **Negative controls**: four mutations applied one at a time, the pinned test required to
  fail, the file restored — 4/4 bit.
  1. the conclusion is unscoped again (absolute "no sample size") ->
     `..._the_floor_conclusion_is_scoped_to_the_measured_range` fails;
  2. the "floor no longer blocks" branch is removed ->
     `..._the_summary_reports_the_floor_when_it_stops_blocking_the_path` fails;
  3. the default ladder stops at 10,000 bars again ->
     `..._the_default_ladder_brackets_the_measured_alpha_crossing` fails;
  4. the summary drops the largest measured rung ->
     `..._the_measured_ladder_finds_the_alpha_crossing_the_shorter_ladder_missed` fails.
- **Live reproduction**: the 25,000-bar walk-forward rung is re-measured from scratch by
  `..._the_walk_forward_alpha_floor_is_under_the_bound_at_25000_bars` (102.7 s), so the
  captured fixture is checked against a fresh run of the framework, not against itself.
- Neighbouring suites, all re-run after the change: `test_falsifiable_hypothesis_example`
  14/14, `test_out_of_sample_window` 10/10, `test_examples_coverage` 7/7,
  `test_test_window_observations` 7/7, `test_walk_forward` 183/183, `test_test_resolution`
  38/38.
- `python3 -m py_compile` clean on both changed Python files.
- `skills-ref validate skills/quantitative-backtesting/` -> "Valid skill" (the CI validator
  used by `.github/workflows/validate-skills.yml`; installed from
  `git+https://github.com/agentskills/agentskills.git#subdirectory=skills-ref`).
- The summary was printed by hand for all three paths on the measured ladder, and the
  scoped message and the new branch were read off the output.

## What remains unresolved

- **What actually sets the alpha floor is now known but not yet reported.** The Deflated
  Alpha floor is `std(benchmark alphas, ddof=1) * sqrt(2 ln N)` with N the number of
  benchmarks, verified exactly (ratio 1.0000) on four measurements: walk-forward path,
  10,000 and 50,000 bars, seed 7, both series. With the shipped two-benchmark set,
  `alpha* = 0.8326 * |alpha_strategy - alpha_benchmark|`. Measured: effect series at 50,000
  bars, strategy alpha 4.70% against benchmark alpha 13.53% (gap 8.82pp) -> floor 7.35%;
  no-effect series, -2.71% against -1.49% (gap 1.23pp) -> floor 1.02%. So the alpha floor
  tracks the strategy's own edge over the benchmark set, not the size of the parameter
  search, and it does not go to zero with more data. The framework reports the number
  without saying what drives it. This is the next task.
- The resolution ladder is still measured only on the **synthetic** fixture. The longest
  real history in the repo is `assets/example_data/sample_panel_ohlcv.csv` (1,500 bars) and
  `sample_ohlcv.csv` (504 bars), far below the range where the crossing happens, so the
  `--data` path of the script has still never been exercised on a history long enough to
  say anything about the crossing. Measuring it needs a longer history than the repository
  carries.
- The framework's `summary["test_resolution"]` block still does not report the realized
  volatility its minimum detectable effect is conditional on, so a reader comparing two
  runs at the same T can misread a volatility difference as a sample-size difference.
  Measured on the held-out test window's own returns: the control's window is more volatile
  than the null's (12.08% against 10.98% annualized at 5,000 bars), which is why the two
  fixtures' alpha MDEs differ at the same T.
- `validation_performance["val_n_periods"]` (`scripts/walk_forward.py:5708`) still carries the
  mislabel the previous session removed from `test_performance`: it is `len(val_returns)`,
  not a period count. The recipe (capture a pre-rename baseline the way
  `tests/fixtures/test_performance_pre_rename_baseline.json` was captured, then extend
  `tests/test_test_window_observations.py`) is in `HANDOFF_NEXT.md`.
- The held-out-fraction sweep is defined only for the out-of-sample path (the path that
  prices criterion 2 on the held-out window). The other two paths are configured in months,
  not in fractions, so they have no held-out fraction to sweep.

## Approaches that failed

- None in this session. The measurement ran to completion on the first attempt, and the
  four negative controls all behaved as required. (The previous session reported that a
  large single `edit` call was rejected by the tool; this session's edits were small and
  went in one call each.)

## Next task (one, precise)

**Report what sets the alpha floor: make the Deflated Alpha floor's driver visible in the
resolution report and in the reference docs, and pin the identity with a test.**

Evidence: the Deflated Alpha floor is `std(benchmark alphas, ddof=1) * sqrt(2 ln N)` with N
the number of benchmarks — verified exactly (ratio 1.0000) on the four measurements listed
above. With the shipped two-benchmark set, `alpha* = 0.8326 * |alpha_strategy -
alpha_benchmark|`: on the control fixture the effect series' floor (7.35% at 50,000 bars)
is set by its 8.82pp alpha gap to the benchmark series, and the null's (1.02%) by its
1.23pp gap. The floor therefore tracks the strategy's own edge, not the size of the
parameter search, and it does not vanish with more data — which is why the walk-forward
path's criterion-5 crossing sits at 50,000 bars.

Bounded work:

1. `scripts/measure_resolution_vs_sample_size.py`: the per-path block (`_measure_path`)
   reads only `expected_max_alpha` from the framework's Deflated Alpha block. Add the
   driver — the strategy's alpha, the benchmark alphas' dispersion and the benchmark count
   — so the summary can say *why* the floor is where it is, and the JSON carries it.
2. `references/validation_methods.md`: a short subsection under the alpha-floor table
   giving the identity, the measured numbers, and what it means for reading the floor (a
   higher floor does not mean a worse search; it means a bigger edge relative to the
   benchmark set).
3. `tests/test_resolution_vs_sample_size.py`: pin the identity against the framework's own
   block (`expected_max_alpha == std(trial alphas, ddof=1) * sqrt(2 ln N)`), so the
   documented formula and the code cannot drift apart.

Constraint: change no threshold, bound, criterion or verdict — this is a reporting and
documentation task. The estimator itself is not to be touched; if the identity turns out to
be a defect rather than a design choice, that is a separate finding to report, not to fix
here.

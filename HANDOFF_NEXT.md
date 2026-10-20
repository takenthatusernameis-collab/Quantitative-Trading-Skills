# HANDOFF_NEXT

## Next task: report the test resolution next to every swept Sharpe

### Why

The resolution work (done in the last two sessions) established what a
significance test can and cannot resolve at a given sample size: the
framework reports the smallest annualized Sharpe / alpha each pre-registered
criterion could have confirmed, and flags the criteria whose threshold
exceeds the stated plausibility bound. A criterion the sample cannot resolve
is a statement about the sample, not evidence against the hypothesis.

That guarantee currently has one hole left. `run_backtest.py`'s **cost
sweeps** -- `--commissions`, `--slippages`, `--impact-coefficients`,
`--borrow-costs`, `--funding-costs`, `--fill-rates`, `--latencies` -- report a
`sharpe_ratio` for every sweep point and attach **no resolution** to it:

`skills/quantitative-backtesting/scripts/run_backtest.py:799`
(`_run_backtest_sweep_coefficient`) builds the per-coefficient metrics dict
and returns `sharpe_ratio`, `total_return`, `max_drawdown`, ... with no
`test_resolution` key, and the sweep artifacts
(`run_backtest_commission_sweep.json` and its siblings) carry the same dicts.
The single-run path of the same CLI *does* attach
`metrics["test_resolution"]` (added in an earlier session), so the same
number is resolvable in one place and unresolvable in the other.

The consequence is the exact defect the resolution reporting exists to
prevent: a reader comparing "Sharpe 1.42 at 2 bps" against "Sharpe 0.31 at
8 bps" sees a precision the sample cannot support, and a sweep whose best
point is below the sample's resolution is indistinguishable from a sweep
whose best point is a real difference.

### Scope

1. **Attach the resolution to every sweep point.** Each per-coefficient
   metrics dict in the sweep artifacts (and the console sweep tables) should
   carry the same `test_resolution` block the single-run path attaches, built
   from the statistics `calculate_metrics` already produced for that
   coefficient -- the framework's own `_build_test_resolution`, on the very
   return series the Deflated Sharpe Ratio was computed on. No new
   statistic, no re-derivation.
2. **Print the threshold next to the swept Sharpe** in the sweep tables, in
   the same wording the single-run path uses ("measurement, not a
   correction"), and flag a swept Sharpe that is *below* the reported
   minimum detectable effect -- the sweep point the sample cannot
   distinguish from zero.
3. **Pin it in an executable check** in `tests/test_test_resolution.py`
   (extend the existing guards; do not re-implement the block).
4. **Write it up** in `references/validation_methods.md`, in the
   "Test Resolution (Minimum Detectable Effect)" section, next to the
   existing description of the block.

### Constraints

- **No threshold, bound, criterion or verdict may change.**
  `minimum_detectable_sharpe` / `minimum_detectable_alpha` /
  `_build_test_resolution` are the single source of truth; the sweep path
  must *read* them.
- **The measurement stays beside the verdict.** The sweep's reported
  numbers (returns, Sharpe, drawdown) must not move: adding the block
  changes no return, cost or metric. The single-run artifacts and the
  shipped `test_output/` snapshot must stay byte-identical.
- **The sweep artifacts' shape may change** (a new key per sweep point) --
  that is the point of the task -- but the *existing* keys must not move,
  and any test that pins the sweep artifact's shape must be updated in the
  same change, with the before/after shown in `HANDOFF.md`.
- Keep the work inside `skills/quantitative-backtesting`; no MCP, plugin,
  marketplace or agent-tooling surface.

### Evidence to inspect first

- `skills/quantitative-backtesting/scripts/run_backtest.py:799`
  (`_run_backtest_sweep_coefficient`) -- the per-coefficient metrics dict
  and the sweep blocks that write it (`run_backtest_commission_sweep.json`
  and siblings).
- `skills/quantitative-backtesting/scripts/run_backtest.py` -- the
  single-run path, which already attaches `metrics["test_resolution"]`; its
  console wording is the model for the sweep tables.
- `skills/quantitative-backtesting/scripts/walk_forward.py:2254`
  (`_build_test_resolution`) -- the block builder, and
  `walk_forward.py:2060` / `walk_forward.py:2138` -- the two inversion
  helpers it is built from.
- `skills/quantitative-backtesting/tests/test_test_resolution.py` -- the
  existing guards on the block (agreement with the helpers, the
  `returns_do_not_match_statistic` degradation, the "changes nothing"
  invariant). Extend them.
- `skills/quantitative-backtesting/references/validation_methods.md`,
  "Test Resolution (Minimum Detectable Effect)" and "How much data does
  criterion 2 need?" -- what the block means and how it scales with the
  sample.

### Definition of done

- Every sweep point carries the resolution of its own statistics, and the
  sweep tables print the threshold next to the Sharpe.
- A swept Sharpe below the reported minimum detectable effect is flagged
  as such (not as a negative result).
- The single-run artifacts and the shipped `test_output/` snapshot are
  unchanged; no swept return, Sharpe or drawdown moved.
- The whole `skills/quantitative-backtesting` suite is green (except the
  pre-existing `test_reporting.py` failures, caused by `matplotlib` missing
  in this container -- 9 failures at HEAD, identical with and without
  changes).
- `HANDOFF.md` / `HANDOFF_NEXT.md` updated.

### The tasks after this one

1. **The resolution ladders of the walk-forward and CPCV paths.** The
   resolution-vs-sample-size curve measured this session covers the
   **out-of-sample** path only (the worked example's configuration). The
   walk-forward and CPCV paths build their own
   `summary["test_resolution"]` on a *different* return series -- the
   concatenated out-of-sample windows of the search itself, not the held-out
   window -- so their curves are unmeasured. The tool
   (`scripts/measure_resolution_vs_sample_size.py`) already has the
   machinery; the next session would extend it to those two paths and say
   whether the same "falls with the sample, converges onto the floor"
   behaviour holds there.
2. **The `test_n_periods` naming defect.** The framework's key counts test
   *observations* while claiming to count *periods*. Renaming it (or adding
   an alias) changes the artifact shape, so it needs a session that can also
   rebuild the parity harnesses (the recipe is in `HANDOFF.md`, "What was
   verified").
3. **The floor (SR\*) as a first-class reported number.** The resolution
   block reports the *minimum detectable effect* but not the floor it
   converges onto (the framework's `expected_max_sharpe`), even though the
   floor is the number that decides whether a criterion can *ever* confirm a
   plausible effect: on the shipped 504-bar sample the floor is 2.0138,
   just above the 2.0 bound, so no amount of data would let criterion 2
   confirm a plausible effect there. Surfacing the floor next to the
   resolution would let a reader see that without re-deriving it.

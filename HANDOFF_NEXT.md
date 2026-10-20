# HANDOFF_NEXT

## Next task: report the test resolution next to every swept Sharpe in the
## remaining CLIs (walk-forward, CPCV, out-of-sample, monte-carlo)

### Why

The resolution work now covers every place the framework reports a Sharpe
against a significance test -- the single backtest run, the three analysis
paths, and the cost sweeps of `run_backtest.py`. One surface is left, and it
is the same defect the last session closed for `run_backtest.py`: **a sweep
that reports a Sharpe per cost level without the resolution of the statistics
that produced it.**

`walk_forward.py` carries five sweep families, each with its own row builder
and its own artifact:

| Path | Row builder | Artifact | Sharpe it prints |
| --- | --- | --- | --- |
| walk-forward | `_walk_forward_sweep_coefficient` (`walk_forward.py:6245`) | `walk_forward_commission_sweep.json` and siblings | `oos_sharpe` + `deflated_sharpe` |
| out-of-sample | `_oos_sweep_coefficient` (`walk_forward.py:6476`) | `out_of_sample_commission_sweep.json` and siblings | `test_sharpe` + `deflated_sharpe` |
| CPCV | `_cpcv_sweep_coefficient` (`walk_forward.py:6600`) | `cpcv_commission_sweep.json` and siblings | `oos_sharpe` + `deflated_sharpe` |
| parameter optimization | `_optimize_sweep_coefficient` (`walk_forward.py:6358`) | `parameter_optimization_commission_sweep.json` and siblings | `top_sharpe` |
| monte-carlo | `_monte_carlo_sweep_coefficient` (`walk_forward.py:8796`) | `monte_carlo_commission_sweep.json` and siblings | `sharpe_ratio` + `deflated_sharpe` |

The consequence is the one the resolution reporting exists to prevent: a
reader comparing "OOS Sharpe 1.42 at 2 bps" against "OOS Sharpe 0.31 at 8 bps"
sees a precision the sample cannot support, and a sweep whose best point is
below the sample's resolution is indistinguishable from a sweep whose best
point is a real difference.

### The good news: three of the five paths already build the block

`walk_forward_analysis` (line 994), `out_of_sample_validation` (line 3673)
and `cpcv_analysis` (line 6075) each already attach
`summary["test_resolution"]`, built by `_build_test_resolution` on the very
return series their own Deflated Sharpe Ratio was computed on. The sweep row
builders simply do not copy it into the row dict. So for those three the work
is: read `summary.get("test_resolution")`, put it in the row, put the
threshold in the table.

**Monte-carlo** has no block at all: its row builder computes
`calculate_metrics(base_results).get("deflated_sharpe")` directly and never
builds a resolution. The block has to be built there
(`_build_test_resolution(metrics, base_results["returns"])`).

**Parameter optimization** needs a judgement, not a copy: its `top_sharpe` is
an *in-sample* selection statistic over the grid, and the resolution that
belongs to it is the resolution of that selection (the number of trials
searched), not of a held-out series. Either report the selection's own
resolution or say explicitly that the number is in-sample and unresolved.

### Scope

1. **Carry the resolution in every sweep row** (the five builders above): the
   `test_resolution` block of that point's own statistics, plus the
   `sharpe_below_resolution` flag, with exactly the semantics implemented
   last session in `run_backtest.py`:
   - the comparison is on **magnitudes** (`|Sharpe| < minSR`): a Sharpe of
     -3.0 against a resolution of 2.5 is resolvable, a Sharpe of +0.3 is
     not;
   - no resolution means **unknown** (`null`), never "not below";
   - the flag is a statement about the sample, not a negative result.
2. **Print the threshold beside the swept Sharpe** in the five sweep tables,
   in the single-run path's wording ("measurement, not a correction"), and
   mark the points the sample cannot distinguish from zero.
3. **Pin it in an executable check** -- `tests/test_test_resolution.py` already
   carries the seven checks for `run_backtest.py`'s sweeps; extend them to the
   other paths (do not re-implement the block; read it).
4. **Write it up** in `references/validation_methods.md`, next to the section
   added last session ("Cost sweeps report the resolution of every point"),
   and update the `SKILL.md` inventory.

### Constraints

- **No threshold, bound, criterion or verdict may change.**
  `minimum_detectable_sharpe` / `_build_test_resolution` /
  `PLAUSIBLE_MAX_ANNUALIZED_SHARPE` stay where they are; the sweep paths must
  *read* them.
- **The measurement stays beside the verdict.** No swept return, Sharpe, drawdown
  or Deflated Sharpe may move; the single-run artifacts and the shipped
  `test_output/` snapshot must stay byte-identical.
- **The sweep artifacts' shape may change** (a new key per sweep point) -- the
  existing keys must not move, and any test that pins a sweep artifact's shape
  must be updated in the same change, with the before/after shown in
  `HANDOFF.md`.
- Keep the work inside `skills/quantitative-backtesting`; no MCP, plugin,
  marketplace or agent-tooling surface.

### Evidence to inspect first

- `skills/quantitative-backtesting/scripts/run_backtest.py` -- the helpers
  written last session: `_sweep_sharpe_below_resolution`,
  `_sweep_resolution_fields`, `_print_sweep_table`,
  `_print_sweep_resolution_note`. **Reuse them** rather than writing a second
  copy: they are the reference implementation of the semantics, and
  `tests/test_test_resolution.py` already pins them.
- `skills/quantitative-backtesting/scripts/walk_forward.py:6245`,
  `:6476`, `:6600`, `:6358`, `:8796` -- the five row builders and the
  `summary`/`results` each of them already has in hand.
- `skills/quantitative-backtesting/scripts/walk_forward.py:994`, `:3673`,
  `:6075` -- where the three analysis paths build
  `summary["test_resolution"]`.
- `skills/quantitative-backtesting/scripts/walk_forward.py:6927`, `:8045`,
  `:8565`, `:9159`, `:9715` -- the five sweep tables and their headers.
- `skills/quantitative-backtesting/tests/test_test_resolution.py` -- the seven
  sweep checks added last session. Extend them.
- `skills/quantitative-backtesting/references/validation_methods.md`,
  "Cost sweeps report the resolution of every point" -- the wording and the
  four deliberate properties the other paths must match.

### Definition of done

- Every sweep point of the five paths carries the resolution of its own
  statistics, and the sweep tables print the threshold next to the Sharpe.
- A swept Sharpe below the reported minimum detectable effect is flagged as
  such (not as a negative result), on magnitudes.
- The single-run artifacts and the shipped `test_output/` snapshot are
  unchanged; no swept return, Sharpe or drawdown moved.
- The whole `skills/quantitative-backtesting` suite is green (except the
  pre-existing `test_reporting.py` failures, caused by `matplotlib` missing
  in this container -- 9 failures at HEAD, identical with and without
  changes).
- `HANDOFF.md` / `HANDOFF_NEXT.md` updated.

### The tasks after this one

1. **The floor (SR\*) as a first-class reported number.** The resolution
   block reports the *minimum detectable effect* but not the floor it
   converges onto (the framework's `expected_max_sharpe`), even though the
   floor is the number that decides whether a criterion can *ever* confirm a
   plausible effect: on the shipped 504-bar sample the floor is 2.0138, just
   above the 2.0 bound, so no amount of data would let criterion 2 confirm a
   plausible effect there. Surfacing the floor next to the resolution would
   let a reader see that without re-deriving it. Note that this would change
   the shared block, hence the `metrics.json` of every single run -- so it
   needs a session that can rebuild the parity harnesses.
2. **The resolution ladders of the walk-forward and CPCV paths.** The
   resolution-vs-sample-size curve measured two sessions ago covers the
   **out-of-sample** path only (the worked example's configuration). The
   walk-forward and CPCV paths build their own `summary["test_resolution"]` on
   a *different* return series -- the concatenated out-of-sample windows of
   the search itself, not the held-out window -- so their curves are
   unmeasured. The tool (`scripts/measure_resolution_vs_sample_size.py`)
   already has the machinery; the next session would extend it to those two
   paths and say whether the same "falls with the sample, converges onto the
   floor" behaviour holds there.
3. **The `test_n_periods` naming defect.** The framework's key counts test
   *observations* while claiming to count *periods*. Renaming it (or adding an
   alias) changes the artifact shape, so it needs a session that can also
   rebuild the parity harnesses.

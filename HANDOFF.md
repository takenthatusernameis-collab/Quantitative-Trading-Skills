# HANDOFF

## What changed this session

The HANDOFF_NEXT.md task ("report the test resolution next to every swept
Sharpe") is done. The cost sweeps of `run_backtest.py` now carry the
resolution of every sweep point, print that threshold beside the swept Sharpe,
and flag the points the sample cannot distinguish from zero. No threshold,
bound, criterion or verdict moved: the resolution is read from the framework's
own `_build_test_resolution` / `minimum_detectable_sharpe`, never re-derived.

### 0. What was already there when this session started

Commit `8a9b12e` (made just before this session opened, and not described in
the previous HANDOFF.md) had already attached the `test_resolution` block to
the per-coefficient metrics dict of `_run_backtest_sweep_coefficient`, so the
sweep *artifact* carried it. What was still missing -- and what this session
added -- was the console reporting, the below-resolution flag, the artifact
key that states the flag, the executable checks and the write-up.

### 1. The console

`skills/quantitative-backtesting/scripts/run_backtest.py`:

- `_sweep_sharpe_below_resolution(sharpe_ratio, resolution)` -- whether a
  sweep point's Sharpe is below the resolution of that point's own
  statistics. **The comparison is on magnitudes** (`|Sharpe| < minSR`): the
  minimum detectable effect is the smallest *magnitude* the test could have
  confirmed, so a Sharpe of -3.0 against a resolution of 2.5 is
  distinguishable from zero while a Sharpe of +0.3 is not. A signed
  comparison would flag the first and pass the second, which is backwards.
  It returns `None` ("unknown") when there is no resolution, never a silent
  "no".
- `_sweep_resolution_fields(result)` -- the two console fields of a sweep
  point: the threshold text and the note (`below resolution` / `resolvable` /
  `n/a`).
- `_print_sweep_table(title, first_header, leads, results)` -- one
  implementation of the sweep table, used by all seven sweeps. It replaces
  seven near-identical 4-line print blocks, so the two new columns cannot
  drift apart between sweeps.
- `_print_sweep_resolution_note(results)` -- the shared note under the table,
  in the single-run path's wording ("measurement, not a correction"), with the
  scope (test observations, parameter trials) and the plausibility-bound
  sentence.

Before / after on the shipped sample
(`--n-trials 12 --commissions 0.0002 0.002 0.004`):

```
before                                  after
comm  return  ann_ret  Sharpe  maxDD    comm  return  ann_ret  Sharpe  maxDD  minSR  note
0.000200  -0.2072  -0.1098  -0.7783  -0.2886
                                        0.000200  -0.2072  -0.1098  -0.7783  -0.2886  2.5064  below resolution
                                        0.002000  -0.2366  -0.1265  -0.8976  -0.3039  2.5076  below resolution
                                        0.004000  -0.2681  -0.1448  -1.0286  -0.3272  2.5090  below resolution
```

and under the table:

```
Test resolution (measurement, not a correction): With 503 test observation(s),
12 parameter trial(s), minSR is the smallest annualized Sharpe each sweep
point's own significance test could confirm at this sample size. A point
marked 'below resolution' has a Sharpe the sample cannot distinguish from
zero: its outcome measures the sample, not the strategy.
The threshold exceeds the stated plausibility bound (annualized Sharpe <=
2.00), so at this sample size it measures the sample, not the strategy.
```

A sweep run **without** `--n-trials` carries no significance test, so the
columns read `n/a` / `n/a` and the console says so explicitly ("no
significance test was run on these sweep points ..."), rather than staying
silent.

### 2. The artifact

Each sweep point in `run_backtest_commission_sweep.json` and its siblings now
carries one more key:

```json
"sharpe_below_resolution": true
```

`true` when the point's Sharpe is below its own resolution, `false` when it is
not, `null` when there is no resolution to judge it against. The block's
existing keys did not move.

**The artifact shape before and after the whole task** (the `results` entries
of `run_backtest_commission_sweep.json`, HEAD~1 -> now):

| key | before | after |
| --- | --- | --- |
| `impact_coefficient` ... `latency` | present | present (unchanged) |
| `total_return`, `annualized_return`, `sharpe_ratio`, `max_drawdown` | present | present (unchanged, same values) |
| `test_resolution` | **absent** | present (the block, built by `_build_test_resolution` on the very return series the Deflated Sharpe was computed on) |
| `sharpe_below_resolution` | **absent** | present (`true` / `false` / `null`) |

The existing sweep-shape assertions in `tests/test_run_backtest.py` only
check for the presence of the four metric keys, so none of them needed
updating; the whole file is 104/104 green.

### 3. The executable checks

`skills/quantitative-backtesting/tests/test_test_resolution.py` grew from 21
to 28 tests (28/28 pass). The seven new ones:

| Test | What it pins |
| --- | --- |
| `test_every_sweep_point_carries_its_own_test_resolution` | every sweep point carries a `test_resolution` block, `resolvable`, with a positive threshold, `n_parameter_trials` as given, and `observed_annualized_sharpe` equal to **that point's own** `sharpe_ratio` (so the block belongs to that coefficient, not to another) |
| `test_the_sweep_point_reports_exactly_what_the_single_run_reports` | the sweep point at commission 0.002 and the single run at `--commission 0.002` report the same `total_return` / `annualized_return` / `sharpe_ratio` / `max_drawdown` and the **same** `test_resolution` block |
| `test_the_sweep_table_prints_the_threshold_next_to_the_sharpe` | the console carries the `minSR` column, the "measurement, not a correction" wording, and the artifact's threshold and Sharpe numbers |
| `test_the_below_resolution_flag_compares_magnitudes` | `0.31` against a resolution of `2.0` is flagged, `2.5` is not, `-3.0` is **not** flagged, and "no resolution" is `None` (unknown), never `False` |
| `test_the_sweep_flags_the_points_the_sample_cannot_distinguish_from_zero` | the artifact's `sharpe_below_resolution` equals `abs(sharpe) < threshold` for every point, and the console says "below resolution" and "cannot distinguish from zero" |
| `test_a_sweep_without_a_significance_test_says_so` | no `--n-trials` -> `n/a` in the console, `not_applicable` in the block, `null` in the flag |
| `test_the_sweep_point_resolution_carries_no_verdict` | the sweep's block carries no verdict key, keeps `target_p_value == 0.10` and the framework's unmoved plausibility bounds |

### 4. The write-up

- `references/validation_methods.md`: new section **"Cost sweeps report the
  resolution of every point"** (in "Test Resolution (Minimum Detectable
  Effect)", just before "What the resolution says on the shipped sample"),
  with the artifact keys, the reproduced console output, the four deliberate
  properties (magnitude comparison, "below resolution" is not a negative
  result, no significance test means "unknown", the sweep point *is* the
  single run) and an explicit statement of what it does **not** establish.
- `SKILL.md`: the `test_test_resolution.py` inventory entry and a new pitfall
  bullet ("A swept Sharpe without its resolution is a comparison the sample
  may not support").

## What was verified

- **The whole skill suite**: 18/18 test files pass except the pre-existing
  `test_reporting.py` failures -- `test_cpcv` 29/29, `test_data_loader`
  32/32, `test_examples_coverage` 7/7, `test_execution_warmup` 8/8,
  `test_falsifiable_hypothesis_example` 14/14, `test_generate_sample_data`
  2/2, `test_inert_param_grid` 27/27, `test_monte_carlo` 20/20,
  `test_no_selection_diagnosis` 34/34, `test_out_of_sample_window` 10/10,
  `test_panel_reference_pinned` 2/2, `test_performance` 33/33,
  `test_resolution_vs_sample_size` 4/4, `test_run_backtest` 104/104,
  `test_strategy_builder` 33/33, **`test_test_resolution` 28/28 (7 new)**,
  `test_walk_forward` 183/183.
- `test_reporting.py` fails 9/62 -- **pre-existing and environmental**:
  `matplotlib` is not installed in this container, so the `save_plots=True`
  tear-sheet tests cannot create their PNGs. The nine failure names are the
  same as at HEAD, and `reporting.py` does not import `run_backtest.py`.
- **No swept number moved.** The sweep artifact produced by the new code and
  by the pre-change code (HEAD) differ **only** by the new
  `sharpe_below_resolution` key; `total_return`, `annualized_return`,
  `sharpe_ratio`, `max_drawdown` and the whole `test_resolution` block are
  byte-identical.
- **The single-run path is untouched.** A single run at HEAD~1 and at HEAD
  with this change produce byte-identical `metrics.json`, `report.txt` and
  `data_provenance.json`; `tear_sheet.html` and
  `tear_sheet_summary.json` differ only in their `load_timestamp`, and the
  console only in the output directory path.
- **The shipped `test_output/` snapshot is untouched** (`git status` shows no
  change under `skills/quantitative-backtesting/test_output/`). Its
  `metrics.json` numbers are the same ones the sweep point at commission
  0.0002 reports (`total_return -0.20722505075442543`,
  `sharpe_ratio -0.7783070851704361`), which is the same-run invariant in
  artifact form.
- **Lint**: `pyflakes` reports nothing for the two changed Python files;
  `py_compile` is clean. The CLI's `--commissions`, `--slippages`,
  `--impact-coefficients`, `--borrow-costs`, `--funding-costs`, `--fill-rates`
  and `--latencies` sweeps all run and print the new columns.
- The skill's frontmatter was not modified, so `skills/marketplace.yaml`
  needs no regeneration (it mirrors the frontmatter only).

## What remains unresolved

- **The other CLIs' cost sweeps still have no resolution.** `walk_forward.py`
  has its own per-path cost sweeps -- `walk_forward_commission_sweep.json`,
  `cpcv_commission_sweep.json`, `monte_carlo_commission_sweep.json`,
  `out_of_sample_commission_sweep.json`,
  `parameter_optimization_commission_sweep.json` and the matching impact
  sweeps -- and each prints a Sharpe (or an OOS Sharpe) and a Deflated Sharpe
  per sweep point **without** the resolution beside it. They are outside the
  scope of the task just completed (which was explicitly `run_backtest.py`'s
  sweeps), and their row builders (`_walk_forward_sweep_coefficient`,
  `_cpcv_sweep_coefficient`, `_monte_carlo_sweep_coefficient`,
  `_oos_sweep_coefficient`) return different row shapes per path. This is the
  natural next task.
- **The floor (SR\*) is still not a first-class reported number.** The
  resolution block reports the *minimum detectable effect* but not the floor
  it converges onto (`expected_max_sharpe`), even though the floor is the
  number that decides whether a criterion can *ever* confirm a plausible
  effect: on the shipped 504-bar sample the floor is 2.0138, just above the
  2.0 bound, so no amount of data would let criterion 2 confirm a plausible
  effect there.
- **The resolution ladders of the walk-forward and CPCV paths are still
  unmeasured.** The resolution-vs-sample-size curve measured earlier covers
  the out-of-sample path only.
- **The framework's own key `test_n_periods`** (in `test_performance`, and
  mirrored into summaries) still counts observations while claiming to count
  periods. Renaming it (or adding an alias) changes the artifact shape, so it
  is deliberately left for a session that can also rebuild the parity
  harnesses.
- **`matplotlib` is missing from this environment**, so the reporting tests
  and the tear-sheet figure paths cannot be exercised here.
- A `RuntimeWarning: invalid value encountered in divide` from numpy's
  correlation computation appears on some runs (including on the no-effect
  control). It comes from the framework's own correlation over a
  zero-variance window (the long-only strategy is flat for a whole window),
  not from the new code; the verdict is unaffected.

## Approaches that failed and why

- **The first draft of the flag compared the Sharpe *signed* against the
  threshold.** That flagged a Sharpe of -3.0 (which the sample resolves
  perfectly well) and passed a Sharpe of +0.3 (which it cannot), i.e. it was
  backwards for every negative point. Caught by the new unit test
  `test_the_below_resolution_flag_compares_magnitudes`, which now pins the
  magnitude semantics explicitly. The comparison is `|Sharpe| < minSR`.
- **The first draft of the shared note did not carry the single-run path's
  wording.** The task asked for the same wording ("measurement, not a
  correction"); the note began with the scope instead. Caught by
  `test_the_sweep_table_prints_the_threshold_next_to_the_sharpe`, which
  asserts the phrase is present. The note now starts with "Test resolution
  (measurement, not a correction): With ...".
- **The flag's input was taken from the block's `observed_annualized_sharpe`
  rather than from the sweep point's own `sharpe_ratio`.** They are the same
  number in the real path, but the function then could not be exercised with
  a synthetic block (a unit test with a different Sharpe had no effect on the
  answer), which is how the signed-comparison bug stayed invisible. The
  reported Sharpe is now the primary input and the block's observed value is
  only the fallback.
- **Seven copies of the sweep table were not kept.** The seven sweeps each
  had their own 4-line print block; adding two columns to each would have
  left seven places to forget the flag. They were replaced by one
  `_print_sweep_table` helper, which is the only way the columns and the note
  can stay consistent across sweeps.

## What was deliberately not done

- **No threshold, bound, criterion or verdict was changed.** The sweep path
  *reads* `minimum_detectable_sharpe` and the plausibility bounds through the
  framework's own `_build_test_resolution`; nothing is re-derived or
  re-tuned. `PLAUSIBLE_MAX_ANNUALIZED_SHARPE` (2.0) and
  `PLAUSIBLE_MAX_ANNUALIZED_ALPHA` (0.10) stay where they are, and the new
  test asserts it.
- **The shared `_build_test_resolution` block was not modified.** Adding a key
  to it would have changed the `metrics.json` of every single-run artifact
  and of the walk-forward / CPCV / out-of-sample summaries. The flag is
  therefore a sibling key of the sweep point, not a key of the block.
- **The other CLIs' cost sweeps were not touched** (see "What remains
  unresolved"): they are a separate surface with different row shapes, and
  the assigned task scoped this one to `run_backtest.py`.
- **The single-run path was not touched**, so the shipped `test_output/`
  snapshot and every single-run artifact stay byte-identical.
- **No MCP, plugin, marketplace or agent-tooling surface was touched.**

# HANDOFF

## What changed this session

**Made the execution warmup convention observable in every result artifact,
without changing a single number.** This was the task assigned in the
previous `HANDOFF_NEXT.md`.

The two entry points warm up differently on purpose (`walk_forward.py` drops
the first `latency + 2` bars of every window, `run_backtest.py` drops 1), and
until now that was only visible in a comment and a reference document. Every
result now *records* the convention it applied:

| Key | Meaning |
| --- | ------- |
| `warmup_convention` | `"walk_forward_drop_undefined"` or `"run_backtest_open_first_executable"` |
| `execution_warmup_bars` | leading bars of a window the convention makes non-tradable (before any indicator warmup) |

### Changes

- `scripts/utils.py` — new shared source of truth: `EXECUTION_WARMUP_BARS`
  (2), `RUN_BACKTEST_WARMUP_BARS` (1), `WARMUP_CONVENTION_WALK_FORWARD`,
  `WARMUP_CONVENTION_RUN_BACKTEST`, and
  `execution_warmup_metadata(convention, latency)` (the single definition of
  the counts; raises `ValueError` on an unknown convention).
- `scripts/walk_forward.py`
  - the local `EXECUTION_WARMUP_BARS = 2` is replaced by the imported shared
    constant (same value, one definition);
  - `walk_forward_analysis()`, `cpcv_analysis()` and
    `out_of_sample_validation()` now put both keys in `summary`;
  - the CLI artifacts (`walk_forward_summary.json`, `cpcv_summary.json`,
    `out_of_sample_summary.json`, `monte_carlo_results.json`) carry both keys
    in their `config` block;
  - new `_print_execution_warmup()` prints the convention next to the panel
    pricing mode on every subcommand.
- `scripts/run_backtest.py` — both keys are in `results["config"]`, and the
  CLI prints the convention next to the panel pricing mode.
- `tests/test_execution_warmup.py` (**new**, 8 tests) — the metadata contract
  across all entry points, and the invariant that the recorded bar count
  equals the number of leading bars that are actually missing from the
  reported return series.
- `references/validation_methods.md` — new section **"Recording the Warmup
  Convention"**; the "The Warmup Bars of a Window" section was corrected (the
  drop is `latency + 2`, not always 2, and it is explicit rather than
  emergent); new section **"Open: what `fill_rate` actually models"** (see
  below).
- `SKILL.md` — the warmup metadata is described in the `run_backtest.py` and
  `utils.py` bullets, a new Tips bullet explains the convention, the new
  test file is listed in the test-coverage section, and the two test files
  that were missing from the run list (`test_examples_coverage.py`,
  `test_falsifiable_hypothesis_example.py`) were added.

### No behaviour change

The dropping/reindexing logic was not touched. The only edit inside
`_calculate_strategy_returns` is that the local constant became an imported
one with the same value. No return series, cost, impact, capacity, metric or
pinned number moves.

## What was actually verified

- **Full suite green**: all 12 test files exit 0 —
  `test_cpcv` 29/29, `test_data_loader` 32/32, `test_examples_coverage` 7/7,
  `test_execution_warmup` 8/8, `test_falsifiable_hypothesis_example` 3/3,
  `test_generate_sample_data` 2/2, `test_monte_carlo` 20/20,
  `test_performance` 33/33, `test_reporting` OK (62 tests),
  `test_run_backtest` 103/103, `test_strategy_builder` 33/33,
  `test_walk_forward` 177/177.
- **The pinned CPCV number is unchanged**:
  `summary["total_oos_return"] == 0.005399536978800246` (reference
  `0.005399536978800024`; the 4.1e-14 relative difference is the known
  last-bit float artifact, inside the `rel_tol=1e-9` guard), 92 usable OOS
  bars, selected lookbacks `[20, 15, 15, 15]` — all as before.
- **The new guards actually bite** (mutations reverted afterwards):
  - `EXECUTION_WARMUP_BARS = 2 -> 3` fails 6 of the 8 new tests;
  - `RUN_BACKTEST_WARMUP_BARS = 1 -> 2` fails 3 of the 8 new tests.
  The tests use *literal* expected counts (2 and 1) rather than re-deriving
  them from the framework's constants, so a change to a constant cannot be
  mirrored by the assertions.
- **The metadata reaches the consumers**: verified end to end on the shipped
  sample data —
  - `run_backtest.py` prints
    `Execution warmup: run_backtest_open_first_executable (1 bar(s) dropped ...)`;
  - `walk_forward.py walk-forward` prints
    `Execution warmup: walk_forward_drop_undefined (2 bar(s) dropped ...)`
    and `walk_forward_summary.json` carries the keys in both `summary` and
    `config`;
  - the same holds for the `cpcv` and `monte-carlo` subcommands
    (`cpcv_summary.json`, `monte_carlo_results.json`).
- **No new lint findings**: `pyflakes` on the four changed/added files
  reports nothing new (the four `walk_forward.py` warnings are pre-existing
  and reproduce on `HEAD`).

## What remains unresolved

- **`--fill-rate` does not model a partial fill.** It scales the *target
  position*, so a fill-rate sweep is a leverage sweep. Measured this session
  on a deterministic 5-asset panel: the per-bar return series is exactly
  `0.5 x` the full-fill series at `fill_rate=0.5`; the Sharpe falls from
  3.19 to 1.79 (the 2%/yr risk-free rate is not scaled with the returns, so
  the Sharpe is not scale-invariant); the impact charge halves;
  `estimate_capacity()` has no `fill_rate` argument at all; and the unfilled
  part of the order is charged nothing. This is recorded durably in
  `references/validation_methods.md` ("Open: what `fill_rate` actually
  models") and in `SKILL.md` (Tips). It is the next task.
- There is still **no committed multi-asset panel fixture**
  (`assets/example_data/` has only a single-asset CSV), so the panel/book
  numbers in `SKILL.md` have no committed reference artifact.
- The **parity harness** from two sessions ago (`baseline_capture.py` /
  `book_cap_probe.py`) still does not exist; the HEAD-vs-new parity check
  cannot be run as specified.
- The **impact model is still linear** in the participation rate (no
  temporary/permanent split, no gap risk).
- The `out-of-sample` CLI cannot complete on the shipped
  `assets/example_data/sample_ohlcv.csv`: it always ends with
  "No valid parameters selected from validation phase" (verified identical on
  `HEAD` with `git stash`, so it is pre-existing and not caused by this
  session). The programmatic path is fine and is covered by the new test.

## Approaches that have already failed (and why)

- **Adding the warmup keys to `metrics.json`** (so the single-backtest CLI
  artifact would carry them): rejected. `metrics.json` is written by
  `calculate_metrics()`, which only copies `initial_capital` out of the
  config, and the committed `test_output/` snapshot plus
  `examples/example_output/` would have to be regenerated -- adding
  machine-specific absolute paths (`plot_files`) to a committed artifact for
  no methodological gain. The existing precedent (`panel_pricing`) also
  lives in `results["config"]` and the CLI stdout, not in `metrics.json`, so
  the warmup metadata follows it.
- **Changing `position_changes.iloc[:EXECUTION_WARMUP_BARS]` to
  `[: latency + EXECUTION_WARMUP_BARS]`** so the explicit drop matches the
  recorded count: it is provably a no-op (the `NaN` region of
  `positions.diff()` already covers exactly those bars) but the handoff
  constraint said "do not alter the dropping/reindexing logic", so the
  dropping logic was left untouched.
- **The first version of the new tests re-derived the expected bar counts
  from the framework's own constants** (`latency + EXECUTION_WARMUP_BARS`).
  A mutation of `EXECUTION_WARMUP_BARS` then passed 3 of the 8 tests, so the
  expectations were rewritten as literals and the assertions strengthened
  with an observed-bar-drop check per window/fold.
- **Running the out-of-sample CLI on the shipped sample data** to demo the
  metadata: it aborts before writing the artifact ("No valid parameters
  selected from validation phase"), for every parameter grid tried
  (`{5,20}`, `{10,30}`, `{20,50}`, `{2,10}`). Pre-existing, not a
  regression.

## Environment notes (not repository changes)

- `matplotlib` was **missing** from this session's environment, which made
  `tests/test_reporting.py` fail with 9 errors (all "plot file should be
  created"). It was installed with `python3 -m pip install matplotlib`; the
  suite is green with it and was green in the previous session with it.
  Without matplotlib that file fails, so any future session must install it
  before trusting a green suite.
- Running the suite in an environment *with* matplotlib re-writes
  `skills/quantitative-backtesting/examples/example_output/tear_sheet.html`
  and `tear_sheet_summary.json` (the committed copies were generated
  *without* matplotlib, so they have `plot_files: []`). Those two files were
  reverted after the test runs; expect them to re-appear as modified after
  any suite run here.

## Git state

The work is **not committed** (the user did not ask for a commit).
`git status` shows three modified files and one new file, all under
`skills/quantitative-backtesting/`:

- `scripts/utils.py`, `scripts/run_backtest.py`, `scripts/walk_forward.py`
  (modified)
- `tests/test_execution_warmup.py` (new)
- `SKILL.md`, `references/validation_methods.md` (modified)

The last commit is `86d28a9`.

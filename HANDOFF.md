# Handoff — 2026-10-21 (session)

## What changed

This session completed the assigned task from `HANDOFF_NEXT.md`: **the
walk-forward path's own lever — its training window and test window — is
now measured, documented and pinned.**

### 1. The measurement (`skills/quantitative-backtesting/scripts/measure_resolution_vs_sample_size.py`)

A new sweep, `--wf-windows`, measures the **walk-forward path** across its
own window configuration at a fixed sample size, exactly as `--test-fracs`
measures the out-of-sample path across its held-out fraction.

- `measure_wf_window_sweep` runs the framework's own `walk_forward_analysis`
  once per `(train_months, test_months)` configuration and records the
  framework's own resolution block, the number of windows, and the
  framework's own count of how many of those windows could price the
  strategy at all (`n_periods`, `periods_with_position`).
- **The step follows the test window.** The framework refuses
  `step_months < test_months` (overlapping out-of-sample windows
  double-count bars in the pooled record and bias the aggregate
  statistics), so the sweep sets `step_months = test_months` and the
  windows tile the sample without overlapping. The row records the step it
  used.
- `_summarize_wf_window_sweep` buckets the draws per configuration and
  reports the same numbers the fraction sweep reports (minimum confirmable
  Sharpe and alpha, the deflation floors SR\* and alpha\*, the observed
  statistics, the inside/outside-the-bound flags) plus the window counts.
- The sweep **names the series it measured** (the no-effect null
  calibration and the effect positive control), **refuses `inject_effect=None`**
  rather than silently measuring the null, **refuses `--data`** for the same
  reason the fraction sweep refuses it, and **refuses to run alongside
  `--test-fracs`** (two sweeps, two paths, measured one at a time).
- `_run_walk_forward` gained `train_months` / `test_months` / `step_months`
  parameters that **default to the shipped 6/2/2**, so the ladder is
  unchanged by the sweep's existence. `scripts/walk_forward.py` is **not in
  this session's diff**.
- One small refactor: the control fixture's construction moved out of
  `measure_synthetic` into `_control_sample`, so the sweep and the ladder
  build the identical fixture. The measurement is unchanged — the ladder's
  walk-forward block at 2,500 bars is still `1.7534313914902404` with 2,201
  out-of-sample observations, exactly as the committed capture records it.

### 2. The capture and the fixture

- `results/resolution_floor/wf_window_sweep_10000.json` — the tool's own
  `--json` output (10,000 bars x three seeds x both series x seven window
  configurations) with its provenance: command, description, environment,
  fixture construction, what was measured, the plausibility bounds and the
  script commit.
- `skills/quantitative-backtesting/tests/fixtures/wf_window_sweep_10000.json`
  — the trimmed fixture: provenance plus the 42 rows, keeping every key the
  sweep's summary reads.

### 3. The pins (`skills/quantitative-backtesting/tests/test_resolution_vs_sample_size.py`)

Thirteen new tests, all registered in `TEST_REGISTRY`:

- the sweep measures the walk-forward path and names it;
- the step follows the test window, and the framework still refuses an
  overlapping step (the sweep's choice is not a weakening of the check);
- each swept configuration's numbers equal the framework's own
  `test_resolution` / `deflated_sharpe` / `deflated_alpha` blocks, on a
  directly re-run analysis;
- the shipped 6/2/2 configuration is unchanged, and the sweep's `6:2` row
  is the same measurement the ladder reports;
- a longer training window leaves fewer windows and fewer out-of-sample
  observations in the sample;
- the sweep refuses to measure both series at once, refuses `--data`, and
  refuses to sweep two paths at once;
- the sweep moves no threshold, bound, criterion or verdict;
- the capture is the tool's own `--json` output, and the summary rebuilt
  from the captured rows equals the summary the tool printed for them;
- the trimmed fixture is a faithful trim of the capture;
- the document states what the sweep does **not** establish, names the
  shipped configuration, and `SKILL.md` carries the flag and the path it
  measures.

### 4. The documentation

- `references/validation_methods.md` gains "How long should the walk-forward
  windows be?", next to the fraction sweep: the measured numbers at 10,000
  and 5,000 bars, the trade-off they expose, **what the sweep does not
  establish**, and the fact that no threshold, bound, criterion or verdict
  moves with it.
- `SKILL.md` carries the flag, the path it measures, and the measured
  answer.

## What the measurement shows (the numbers, not a verdict)

On the synthetic control fixture, 10,000 bars, three seeds:

- **The training window is a resolution lever and it points one way.** The
  walk-forward path's training window is *expanding* — every window trains
  on everything before it — so a longer initial training window means every
  window's parameter selection is estimated on more data and the trial
  Sharpes the deflation floor is estimated from are less dispersed. On the
  null calibration, 3 months of training gives a worst-draw minimum
  confirmable Sharpe of 1.8497 and a worst-draw floor SR\* of 1.6250;
  24 months gives 1.2230 and 1.0016. The cost is that the walk-forward
  starts later (228 windows become 217).
- **The training window decides the criterion-2 crossing at 5,000 bars**:
  with 3 months of training the null's worst draw (2.4452) is outside the
  2.0 bound; with 6, 12 or 24 months every draw measured is inside it.
- **The test window is a lever on the record, not only on the resolution.**
  A test window shorter than the strategy's own indicator warmup leaves
  most windows unable to price the strategy at all — the grid's slowest
  moving average needs 50 bars and a month is about 21, so at a test
  window of 1 month only 240 to 259 of the 453 windows carry a position,
  against 156 to 164 of 226 at 2 months and 72 to 74 of 75 at 6 months.
- **A short test window also truncates the position repeatedly, and the
  observed statistic shows it**: on the control the observed annualized
  Sharpe is 0.68 to 0.84 at 1 month against 1.25 to 1.90 at 2 months and
  2.56 to 2.93 at 6 months, and the observed annualized alpha goes from
  -1.9% to -1.5% at 1 month to 28.3% to 32.4% at 6 months. The null moves
  the same way, so this is a property of the window configuration.
- **The Sharpe verdict is the same under all seven configurations** at
  10,000 bars; the **alpha bound is not** — on the control the minimum
  confirmable alpha is inside the 10% bound for every draw at test windows
  of 1 and 6 months and above it on the worst draw at every test window of
  2 and 3 months (12.65% at the shipped 6/2).

## What was actually verified

- **The full test file passes: 53/53, exit 0**
  (`python3 skills/quantitative-backtesting/tests/test_resolution_vs_sample_size.py`),
  including the 13 new pins and the two pre-existing pins that a first
  version of this session's helper name had broken (see "approaches that
  failed").
- **The new pins were negative-controlled**, one mutation at a time, with
  the file restored after each:
  - the new section's shipped test window changed from 2 to 3 months → the
    document pin fails;
  - "What this does not establish" removed from the new section → the
    document pin fails;
  - the sweep's step changed to follow the *training* window → the step
    pin fails;
  - the sweep's row path changed to the out-of-sample path → the scope pin
    fails;
  - the capture's command changed to a different sample size → the capture
    pin fails.
- The framework's own numbers the sweep reports were read from the code,
  not assumed: `walk_forward_analysis`'s signature and its
  `step_months >= test_months` refusal
  (`scripts/walk_forward.py:612`), the expanding training window
  (`scripts/walk_forward.py:630` — `train_data = data[data.index < train_end]`
  with `train_end` advancing), and the framework's own `periods_with_position`
  count.
- `skills-ref validate skills/quantitative-backtesting/` → "Valid skill".
- The skills marketplace was regenerated (`npx tsx generate-skill-marketplace.ts`
  in `bin/`) and **`skills/marketplace.yaml` is unchanged** — the generator
  reads only the frontmatter, which this session did not touch.
- The 10,000-bar capture was produced by the committed script at commit
  `48bb1fb`; the 5,000-bar numbers in the document come from the same
  command at `--sizes 5000` (that capture is not committed — the document
  quotes its numbers and the 10,000-bar capture is the pinned one).

## What remains unresolved

- **The environment has no matplotlib.** numpy and pandas are installed;
  `tests/test_reporting.py` (the figure-generating tests) could not be run
  here. This session's diff does not touch reporting, but the next session
  should install `skills/quantitative-backtesting/requirements.txt` in full
  before running the whole suite.
- **The pre-driver ladder fixture is still a second source of truth.**
  `tests/fixtures/resolution_ladder_2500_to_50000.json` keeps the 10-key
  path blocks (no driver, no status), so a summary built from *it* still
  says the alpha-floor driver "is not measurable on this ladder", while the
  re-capture fixture says it is. Flagged in the previous two handoffs and
  unchanged here.
- **The 5,000-bar window sweep is not captured.** The document quotes its
  numbers (the criterion-2 crossing depends on the training window there),
  but only the 10,000-bar capture is committed and pinned. A reader who
  wants to re-run the 5,000-bar table has to re-run the command.
- **The two sweeps refuse `--data`.** Both are defined on the synthetic
  control fixture, and the fixture's numbers must not be reported under a
  real history's name. A real-history version of either sweep is a
  separate piece of work.

## Approaches that failed

- **A helper-name collision, caught by the full-suite run.** The first
  version of this session added a `_framework_wf_block(bars, seed,
  inject_effect, train_months, test_months, step_months)` helper to the
  test file. The file already had a `_framework_wf_block(bars, seed,
  inject_effect)`, so the new definition shadowed the old one at module
  level and two pre-existing pins failed with
  `TypeError: _framework_wf_block() missing 3 required positional arguments`.
  Fixed by extending the *existing* helper with optional window parameters
  that default to the shipped configuration, and deleting the duplicate.
  The lesson worth keeping: a focused run of the new tests alone would
  not have caught it, because the two broken pins are older tests.
- Two negative controls in the first attempt were invalid rather than
  failing pins: one mutated the shipped configuration in the *other*
  section (the first occurrence in the file, not the new section), and one
  mutated the script but the mutated module was never re-imported because
  `sys.modules` still held the first import. Both were redone with the
  mutation targeted at the right text and `sys.modules` cleared; all five
  mutations then failed their pin as they should.

## Next task (one, precise)

**Measure the CPCV path's lever: sweep the number of splits and the
per-group test fraction at a fixed sample size on the CPCV path, and report
the same resolution numbers the two existing sweeps report.**

The three analysis paths are each configured in the units of their own
analysis. The out-of-sample path's lever (its held-out fraction) and the
walk-forward path's lever (its window configuration) are now measured; the
CPCV path's lever — `n_splits` and `test_size` — is the only one left.
`HANDOFF_NEXT.md` carries the full task, the evidence and the constraints.

The question it answers is sharp: the reference document says the CPCV
path has the *lowest* floor of the three (0.45 - 1.04 at 2,500 bars against
1.24 - 2.23 for the out-of-sample path), and that is currently a statement
about the path. This sweep asks whether it is a statement about the
path's *configuration* — how many splits, and how much of each group is
tested — which is the same question the two completed sweeps asked of
their own paths.


---

# Handoff — 2026-10-22 (session)

## What changed

Completed the assigned task from `HANDOFF_NEXT.md`: enabled `--data` for walk-forward window sweep and CPCV split sweep so resolution can be measured on real market history.

### Script changes (`skills/quantitative-backtesting/scripts/measure_resolution_vs_sample_size.py`)
- `measure_wf_window_sweep` and `measure_cpcv_sweep` now accept `data_path` (load from real history, resolve benchmarks from data file's directory, use single seed `None` for real data).
- `inject_effect` made optional where needed; when using `--data`, measure series `real_history_prefix` with no synthetic effect injection.
- Main dispatch updated to allow `--data` with sweeps and set appropriate series labeling.
- Help text updated to describe `--data` support.

### Captures and fixtures
- Added real-history sweep capture: `results/resolution_floor/wf_window_sweep_real_504.json` and copy under skill tree.
- Added trimmed fixture: `skills/quantitative-backtesting/tests/fixtures/wf_window_sweep_real_504.json`.

### Tests and docs
- Verified `test_the_window_sweep_refuses_to_report_a_real_history_it_did_not_measure` and `test_the_cpcv_sweep_refuses_to_report_a_real_history_it_did_not_measure` pass.
- Docs updated in `SKILL.md` and `references/validation_methods.md`.

## What was actually verified
- Ran the two real-history sweep tests directly with Python - both pass.
- Verified the implementation matches the pattern used by ladder on real history (benchmarks resolved from data dir).

## What remains unresolved
- Pre-driver vs recapture ladder fixtures are two sources of truth for same measurement; left as a task for next agent.

## Which approaches have already failed and why
- None in this session.

## One precise next task
- Resolve duplication between `tests/fixtures/resolution_ladder_2500_to_50000.json` (pre-driver baseline) and `tests/fixtures/resolution_ladder_2500_to_50000_recapture.json` (driver+status) - make single unambiguous source of truth, update tests/docs accordingly.

---

# Handoff — 2026-10-22 (second session)

## What changed

Completed the assigned task from `HANDOFF_NEXT.md`: **the full-ladder
measurement now has ONE source of truth, and the pre-driver capture is a
self-describing historical record rather than a second reading of it.**

### 1. The arrangement (one measurement, one fixture)

The ladder was measured twice — once before the alpha-floor driver existed
and once after — and both records were committed as *fixtures*. A summary
built from the older one reported the driver as "not measurable on this
ladder", which is a statement about that capture and not about the ladder.
So the older fixture was removed and the older capture was kept, in its
place, as the thing it always was: the historical baseline.

- **Removed** `skills/quantitative-backtesting/tests/fixtures/resolution_ladder_2500_to_50000.json`
  (the pre-driver trimmed fixture; 10-key path blocks, no driver, no
  status).
- **Now the only fixture for the full ladder**:
  `skills/quantitative-backtesting/tests/fixtures/resolution_ladder_2500_to_50000_recapture.json`
  (19-key path blocks: the driver `strategy_alpha` / `benchmark_alphas` /
  `benchmark_alpha_std` / `n_benchmarks` and the per-criterion
  `sharpe_status` / `alpha_status` + reasons).
- **Kept as the historical baseline**:
  `results/resolution_floor/ladder_2500_to_50000.json` — the pre-driver
  capture. It is what the re-capture is compared against to show that no
  number, no threshold, no bound, no crossing and no verdict moved while the
  driver and the status were added.
- **The baseline capture is now self-describing.** It used to be the tool's
  bare `--json` output with no provenance at all, and the *fixture* that
  was removed was the only place the pre-driver measurement's provenance
  (command, script commit, environment, fixture construction, measured
  sizes/seeds/series, `measured_at_utc`) was recorded. That provenance was
  moved into the baseline capture as a `provenance` block; its `rows` and
  its `summary` are byte-for-byte unchanged.
- **The re-capture's own provenance** now records the arrangement: the
  `baseline` block names the baseline capture, carries
  `capture_script_commit` and `measured_at_utc`, and sets `fixture: null`
  with a note saying what was removed and why. The capture in `results/` and
  the fixture in `tests/fixtures/` were updated identically, so the test
  that asserts `fixture["provenance"] == capture["provenance"]` still holds.

### 2. The pins (`skills/quantitative-backtesting/tests/test_resolution_vs_sample_size.py`)

- The two tests that read the ladder's numbers
  (`test_the_measured_ladder_finds_the_alpha_crossing_the_shorter_ladder_missed`,
  `test_the_measured_ladder_is_the_frameworks_own_numbers`) now read the
  single fixture. Their assertions are unchanged and still hold on it.
- The cheap 10,000-bar ladder's "same measurement" check now compares it
  against the full ladder's own capture instead of the removed fixture, and
  compares the driver keys too (they are present on both sides). The
  comparison helper `_assert_same_measured_value` handles a list of numbers
  (the per-path `benchmark_alphas`) element by element, so a float-noise
  difference is a difference and not a failure.
- The "nothing moved between the captures" check now also counts the values
  it compared: **1,080 shared values over 90 path blocks**, which is exactly
  the number the capture's own provenance states. That count is now pinned.
- **New registered test `test_the_full_ladder_has_one_fixture`** (69th test):
  - exactly one fixture in `tests/fixtures/` covers the full ladder, and it
    is the re-capture (structural: a future session that re-adds a second
    one fails here instead of quietly restoring the ambiguity);
  - that one fixture carries the driver and the status at every rung;
  - the pre-driver capture still exists, still lives with the other
    captures, and says what it is ("pre-driver" in its own description);
  - the re-capture's provenance names that capture, points at no fixture,
    and agrees with it on the commit and the timestamp;
  - `SKILL.md` and `references/validation_methods.md` name the same single
    source of truth, and `SKILL.md` no longer points a reader at the
    removed fixture.

### 3. The documentation

- `references/validation_methods.md`: the ladder's capture paragraph now
  names the single fixture and says why the pre-driver capture is kept
  (the historical baseline, not a second reading); a new "**One
  measurement, one fixture**" paragraph records what was removed and that
  no measurement and no provenance was lost.
- `SKILL.md`: the test-file description names the single fixture and the
  baseline capture.

## What was actually verified

- **`tests/test_resolution_vs_sample_size.py`: 69/69 passed, exit 0** (was
  68/68; the new pin is the 69th).
- **The whole skill suite: 19 test files, every one exit 0** —
  `test_cpcv` 29/29, `test_data_loader` 32/32, `test_examples_coverage`
  7/7, `test_execution_warmup` 8/8, `test_falsifiable_hypothesis_example`
  14/14, `test_generate_sample_data` 2/2, `test_inert_param_grid` 27/27,
  `test_monte_carlo` 20/20, `test_no_selection_diagnosis` 34/34,
  `test_out_of_sample_window` 11/11, `test_panel_reference_pinned` 2/2,
  `test_performance` 33/33, `test_reporting` (no summary line, exit 0),
  `test_resolution_vs_sample_size` 69/69, `test_run_backtest` 104/104,
  `test_strategy_builder` 33/33, `test_test_resolution` 39/39,
  `test_test_window_observations` 7/7, `test_walk_forward` 183/183.
- **The numbers were compared, not assumed.** Pre-driver fixture vs the
  baseline capture: 720 shared values, max absolute difference **0.0**.
  Baseline capture vs the re-capture: **1,080 shared values, max absolute
  difference 0.0** — the claim the provenance makes is now the number the
  test asserts. Cheap 10,000-bar ladder vs the full ladder at their shared
  rungs: 234 values, worst absolute difference 3.55e-15 (worst relative
  6.5e-14).
- **The new pins were negative-controlled**, one mutation at a time, with
  the tree restored after each: a duplicate fixture re-added → the
  one-fixture pin fails; the driver's `strategy_alpha` dropped from the
  fixture → the driver pins fail; a number moved in the fixture → the
  "nothing moved" and the framework's-own-numbers pins fail; the baseline's
  provenance removed → the provenance pin fails; the baseline pointer put
  back to a fixture path → the pointer pin fails; `SKILL.md` pointed at the
  removed fixture → the document pin fails; the document's "single source of
  truth" wording changed → the document pin fails.
- **matplotlib is available in this environment** (3.11.2), so the previous
  handoff's "the environment has no matplotlib" note is stale:
  `tests/test_reporting.py` runs and passes here.
- The skills marketplace generator **could not be run** here (`bin/node_modules`
  is absent and `pnpm`/`npm` cannot reach the network). The `SKILL.md`
  frontmatter is byte-identical to HEAD (the diff starts at line 320, in the
  body) and the generator reads only the frontmatter, so
  `skills/marketplace.yaml` cannot have drifted.

## What remains unresolved

- **No cost sensitivity exists for any of this.** Every number above is
  measured at the shipped cost assumptions (2 bps commission + 1 bps
  slippage per trade, and the framework's defaults `impact_coefficient=0`,
  `borrow_cost=0`, `funding_cost=0` — no impact, no borrow, no funding), and
  the trial Sharpes that set the floor are net of commission+slippage, so
  the floor itself moves with the cost assumptions. This is the next task.
- **The ladder is still a property of the synthetic control fixture.** The
  real-history ladder reaches 1,500 bars and does not reach the crossing;
  no longer real history is reachable from this environment (the public
  market-data endpoints tried were blocked: stooq serves a JS challenge,
  Yahoo returns HTTP 429).
- `results/resolution_floor/ladder_2500_to_50000.json` still has no
  `summary`-level provenance of its own beyond the new block; the block
  records the measurement's command, commit, environment, construction and
  timestamp, which is what the removed fixture held.

## Which approaches have already failed and why

- **A mutation harness that ran the whole suite per mutation was killed by
  the 40-minute command timeout** (six suite runs at ~7 minutes each). It
  left a mutated copy of the baseline capture and a duplicated fixture on
  disk; both were restored from the `.orig` backups it had written and the
  tree was re-verified against `git status` before any further work. The
  retry ran only the five affected test functions (they read committed
  artifacts and take 0.0s), which is what the negative controls needed.
- The skills marketplace generator cannot be run offline in this
  environment; the frontmatter was left untouched so the generated catalog
  cannot change.

## One precise next task

**Measure the resolution ladder under different cost assumptions, and report
which of its verdicts survive.**

`HANDOFF_NEXT.md` carries the full task, the exploratory evidence already
collected (the floors barely move with costs; the *observed* statistic moves
by an order of magnitude on the walk-forward path at 2,500 bars), the exact
build steps and the constraints.

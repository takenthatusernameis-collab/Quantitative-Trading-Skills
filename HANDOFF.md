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

# HANDOFF_NEXT

## Next task: quantify how large a sample the pre-registered criteria need -- and whether any sample size can confirm a plausible effect

### Why

The positive control (done last session) established that the machinery
*can* say yes: on a synthetic series with a known injected effect the
example's own criteria returned `SUPPORTED`, on the matched no-effect series
they returned `NOT SUPPORTED`, and on the effect series the observed effect
exceeded the framework's own reported minimum detectable effect.

It also produced a finding that the control could not resolve: **the effect
the criteria need is far larger than any plausible strategy's.** On the
control the smallest confirmable annualized Sharpe was **1.83** and the
smallest confirmable annualized alpha **8.91%**, but the effect that
actually cleared them was an annualized Sharpe of **3.15** and an annualized
alpha of **40.8%** -- outside the framework's own plausibility bounds (2.0 and
10%). The shipped paths are worse: 4.20 on the worked example, 2.29-2.91 on
the walk-forward / CPCV / out-of-sample paths.

The mechanism is identifiable: criterion 2 is a *deflated* Sharpe test, and
its deflation benchmark `SR*` is estimated from the **cross-sectional
dispersion of the trial Sharpes** (`deflated_sharpe_ratio`, `trial_sharpes`).
That dispersion is dominated by the estimation noise of a six-month window
(1/sqrt(126) per period) and by the number of trials, and **the number of
trials grows with the sample** (more validation windows -> more pooled trial
Sharpes -> `sqrt(2 ln N)` grows). The `1/sqrt(T-1)` term of the observed
effect shrinks with the sample; the `SR*` term grows. The minimum
confirmable effect therefore does not fall below ~1.8-2.4 annualized Sharpe
no matter how large the sample becomes -- and the plausibility bound is 2.0.

So the framework currently cannot state, for a given strategy, *how much data
would be needed* to confirm an effect of a given size -- and on the evidence
so far, for the pre-registered criteria, **no sample size may suffice at all**.

### Scope

1. **Measure the resolution as a function of sample size.** For the
   out-of-sample path (and the walk-forward path), compute the reported
   minimum detectable Sharpe / alpha at a ladder of sample sizes (e.g. 500,
   1000, 2500, 5000, 10000, 25000 bars) on data where the trial-Sharpe
   dispersion is representative, and report the curve.
2. **Answer the question explicitly**: at the shipped configuration (the
   example's 16-combination grid, 6-month walk-forward training window,
   0.6/0.2/0.2 split), is there *any* sample size at which criterion 2 can
   confirm an annualized Sharpe at or below the stated plausibility bound
   (2.0)? If yes, name the smallest such sample size; if no, say so and
   show the curve that says so.
3. **Pin the answer in an executable check** and write it up in
   `references/validation_methods.md` next to the positive control, so the
   next reader learns it from the documentation rather than by re-deriving
   it.
4. If the answer is "no sample size suffices", state what that implies for
   the framework's own use (e.g. the criteria are a statement about effect
   size, not about evidence) -- as a finding, in prose, **not** by changing
   a threshold, a bound or a verdict.

### Constraints

- **No threshold, bound, criterion or verdict may change.** `minimum_detectable_sharpe`
  / `minimum_detectable_alpha` and `_build_test_resolution` are the
  framework's single source of truth; the analysis reads them, it does not
  re-derive or re-tune them. `PLAUSIBLE_MAX_ANNUALIZED_SHARPE` /
  `PLAUSIBLE_MAX_ANNUALIZED_ALPHA` stay where they are.
- **Do not modify the positive control's fixture** to make a number look
  better. `scripts/generate_positive_control_data.py` and its documented
  construction are the reference point; the new analysis may use the same
  generator, and may add series, but the control's own verdicts and
  numbers must not move.
- **The shipped sample's output must stay byte-identical** (it is today;
  verify with a before/after `diff` of the example's stdout).
- Any new reporting must be a **measurement beside** the verdict, never
  folded into it.
- Keep the work inside `skills/quantitative-backtesting`; no MCP, plugin,
  marketplace or agent-tooling surface.

### Evidence to inspect first

- `skills/quantitative-backtesting/scripts/walk_forward.py` --
  `deflated_sharpe_ratio` (the `SR*` estimator: `std(trial_sr) *
  sqrt(2 ln N)`), `minimum_detectable_sharpe` / `minimum_detectable_alpha`
  (the inversion), and `_build_test_resolution` (what is reported).
- `skills/quantitative-backtesting/references/validation_methods.md`, "Test
  Resolution (Minimum Detectable Effect)" and "A positive control: the
  machinery can say yes" -- the resolution numbers on the shipped paths and
  on the control, and the curve that is missing.
- `skills/quantitative-backtesting/scripts/generate_positive_control_data.py`
  -- the fixture generator (its regime length equals the walk-forward
  training window on purpose, so the trial Sharpes stay comparable; a
  sample-size ladder must not silently inherit that convenience when the
  point is to measure a representative dispersion).
- `skills/quantitative-backtesting/tests/test_test_resolution.py` -- the
  existing guards on the resolution block; extend them rather than
  re-implementing the block.
- `HANDOFF.md`, "What remains unresolved" -- the measurement already taken
  this session (4.20 / 2.29-2.91 / 1.83-2.40) and where it came from.

### Definition of done

- The resolution-vs-sample-size curve is measured and reproduced by an
  executable check.
- The question "is there a sample size at which criterion 2 can confirm a
  plausible effect?" is answered explicitly, with the number or with the
  demonstration that there is none.
- The finding is written up in `references/validation_methods.md` (and, if
  it changes what a reader should expect, in `SKILL.md`) **without**
  changing a threshold, a bound, a criterion or a verdict.
- The positive control's own verdicts and numbers are unchanged, the
  shipped sample's stdout is byte-identical, and the whole
  `skills/quantitative-backtesting` suite is green (except the pre-existing
  `test_reporting.py` failures, caused by `matplotlib` missing in this
  container -- 9 failures at HEAD, identical with and without changes).
- `HANDOFF.md` / `HANDOFF_NEXT.md` updated.

### The tasks after this one

1. **The `test_n_periods` naming defect.** The framework's key counts test
   *observations* while claiming to count *periods*. Renaming it (or adding
   an alias) changes the artifact shape, so it needs a session that can also
   rebuild the parity harnesses (the recipe is in `HANDOFF.md`, "What was
   verified").
2. **The sweep paths.** `run_backtest.py`'s cost sweeps
   (`--commission`, `--slippage`, ...) call `calculate_metrics` per
   coefficient and report a Sharpe, but never a resolution; a sweep whose
   Sharpe is reported without the resolution has the same defect the
   `run_backtest.py` path had.

# HANDOFF_NEXT

## Next task: build a positive control for the falsifiable-hypothesis machinery

### Why

The framework now reports, next to every significance verdict, the smallest
effect that verdict's test could have confirmed at the sample size actually
available. On every shipped sample that threshold is beyond the plausibility
bound, so the verdicts are, in substance, statements about the size of the
sample.

That claim is currently supported **only by the formula**. Nothing has yet
*executed* the same machinery against a series with a known effect to show
that the criteria can be met when the effect is real and the sample is large
enough. The claim "the test would have said yes to a large enough effect" is
an inference from the arithmetic, not an observation.

A positive control closes that gap. It is the difference between "the
machinery can only fail" (which is what the resolution reporting shows) and
"the machinery *can* say yes when it should" (which is what has never been
shown).

### Scope

1. **Construct a synthetic series with a known, injected effect.** It must be
   long enough that the deflated thresholds are reachable at the sample size
   actually used, and structured so that the SMA-crossover strategy beats
   buy-and-hold **net of costs** (a trend/regime structure that a crossover
   can exploit, not just a drift the crossover cannot capture). The effect
   size has to be large enough to clear `minimum_detectable_sharpe` at the
   chosen `T`.
2. **Run the example's own criteria evaluation against it** and assert it
   returns SUPPORTED. Use
   `examples/falsifiable_hypothesis_example.py`'s criteria machinery -- do not
   re-implement a second copy of the criteria; the point is to exercise the
   shipped code.
3. **Assert the negative side too**: the same machinery against the same
   construction with the effect *removed* must return NOT SUPPORTED. A
   control that only asserts the positive case would pass even if the criteria
   always returned SUPPORTED.
4. **Label it unmistakably.** The fixture must be named and documented as a
   test-machinery check on synthetic data, never as evidence about a market.
   Nothing in the fixture, the test name or the output may read as a claim
   about real securities.

### Constraints

- **The shipped sample's numbers must not move.** The example's output on
  `assets/example_data/sample_ohlcv.csv` is byte-identical today; the new
  fixture must not touch it. Add a new fixture file rather than changing the
  shipped one, or generate it inside the test.
- **Do not weaken or re-threshold the criteria to make the control pass.**
  If the criteria as pre-registered cannot be met by any constructible
  series, that is a *finding*, and it must be reported as such rather than
  engineered away.
- **Do not change a verdict.** The control asserts; it does not decide.
- The example imports `PLAUSIBLE_MAX_ANNUALIZED_SHARPE` /
  `PLAUSIBLE_MAX_ANNUALIZED_ALPHA` from `walk_forward` -- keep that single
  source of truth.

### Evidence to inspect first

- `skills/quantitative-backtesting/examples/falsifiable_hypothesis_example.py`
  -- the criteria evaluation and the pre-registered thresholds. Read the
  criteria *before* choosing the synthetic series, so the fixture is built
  to exercise the shipped criteria rather than to fit them.
- `skills/quantitative-backtesting/tests/test_falsifiable_hypothesis_example.py`
  -- the existing test file; extend it rather than starting again.
- `skills/quantitative-backtesting/scripts/walk_forward.py` --
  `minimum_detectable_sharpe` / `minimum_detectable_alpha` (how large the
  effect must be for the test to be able to confirm it) and
  `_build_test_resolution` (what the control will report).
- `skills/quantitative-backtesting/references/validation_methods.md`, "The
  framework's own verdicts report their resolution" -- what the resolution
  says on the shipped sample, and what a control would have to show.

### Definition of done

- A synthetic fixture with a known injected effect, plus its no-effect
  control.
- Tests asserting SUPPORTED on the effect series and NOT SUPPORTED on the
  no-effect series, using the example's own criteria machinery.
- The fixture is documented as a machinery check, never as market evidence.
- The whole `skills/quantitative-backtesting` suite green (except the
  pre-existing `test_reporting.py` failures, which are caused by
  `matplotlib` missing in this container -- 9 failures at HEAD, identical
  with and without changes).
- Evidence documented (what changed, verified, unresolved), and
  `HANDOFF.md` / `HANDOFF_NEXT.md` updated.

### The task after this one

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

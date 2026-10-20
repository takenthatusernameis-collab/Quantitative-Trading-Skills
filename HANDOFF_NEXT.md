# HANDOFF_NEXT

## The one precise next task

**Decide what `--fill-rate` is supposed to mean, then make the code, the CLI
help and the docs agree — and pin the decision with an executable test.**

The parameter is documented as "the fraction of each targeted position change
that is filled", but the implementation **scales the target position**
(`positions = signals.shift(1 + latency) * fill_rate`). Those are different
models, and the difference changes what a fill-rate sweep means.

### Why (evidence, measured this session)

Measured on a deterministic 5-asset panel (`cross_sectional_momentum`,
`lookback` 20, 498 usable bars, `commission=0.0002`, `slippage=0.0001`):

| Quantity | `fill_rate=1.0` | `fill_rate=0.5` |
| --- | --- | --- |
| per-bar return series | base | **exactly** `0.5 x` base (ratio `0.500000` on every bar) |
| total return | `+13.851138%` | `+6.706919%` (ratio `0.4842`) |
| annualized Sharpe | `3.1864` | `1.7935` |
| total market-impact cost (`impact_coefficient=0.5`) | `4e-06` | `2e-06` |

- The Sharpe is **not** scale-invariant because the risk-free rate (2%/yr) is
  subtracted from the *scaled* return and is not scaled with it. So a
  fill-rate sweep moves the Sharpe even though the strategy is
  mathematically a smaller version of itself.
- `estimate_capacity(data, impact_coefficient, max_impact, adv_window)` has
  **no `fill_rate` parameter** — the reported capacity is the capacity at full
  fill.
- The unfilled part of the target order is charged nothing: there is no
  shortfall, priority or spread cost for the unexecuted portion.
- Under a real partial fill the held position converges toward the target
  (`position_t = position_{t-1} + f * delta_target`); the framework snaps to
  `f * target` instead, so the exposure path is different as well.

Consequence: a researcher who sweeps `--fill-rates 0.5 0.75 1.0` to test
"what if only half my orders fill" is in fact measuring a de-risked version of
the strategy, and may read the result as evidence of execution robustness.
This finding is already recorded durably in
`references/validation_methods.md` ("Open: what `fill_rate` actually models")
and in `SKILL.md` (Tips), so it is not lost if this handoff is.

### The decision to make

Two acceptable resolutions (pick one, deliberately):

1. **Keep the current semantics and label them honestly.** Rename/redocument
   the parameter as a participation or position-scale limit (it is *not* a
   fill model), fix the CLI help text, and pin the exact scaling with a test
   (`returns(fill_rate=f) == f * returns(fill_rate=1)` elementwise, plus the
   fact that the Sharpe is not scale-invariant because of the risk-free
   rate). No published number moves.
2. **Implement a true partial-fill model** (the held position converges
   toward the target). This is a **number-changing** change: the pinned CPCV
   number, the usable-bar counts, the `test_output/` snapshot and the
   walk-forward numbers must be re-derived and re-pinned in the same commit,
   and the change must be reported as a methodology change (with before/after
   numbers), not as a bug fix.

Option 1 is the smaller reversible change and is the recommended starting
point; option 2 is the more honest model but is a much larger commitment.

### Concrete steps

1. Read `scripts/utils.py::held_book_weights` and
   `scripts/walk_forward.py::_calculate_strategy_returns` for the two places
   `fill_rate` enters (the position series and the held book).
2. Decide per option 1 or 2 above.
3. If option 1: update the `--fill-rate` help text in
   `scripts/run_backtest.py` and `scripts/walk_forward.py`, update the
   `fill_rate` docstrings, update
   `references/validation_methods.md` ("Open: what `fill_rate` actually
   models" -> a decided convention) and the `SKILL.md` tip, and add the
   pinning test.
4. If option 2: re-derive and re-pin everything listed above, and record the
   before/after numbers in `HANDOFF.md`.

### Evidence to look at

- `skills/quantitative-backtesting/scripts/utils.py` — `held_book_weights`
  (`held = target.shift(lag) * fill_rate`)
- `skills/quantitative-backtesting/scripts/walk_forward.py` —
  `_calculate_strategy_returns` (`positions = signals.shift(1 + latency) * fill_rate`)
- `skills/quantitative-backtesting/scripts/utils.py` —
  `estimate_capacity(data, impact_coefficient, max_impact=0.0005, adv_window=20)`
  (no `fill_rate` argument)
- `skills/quantitative-backtesting/scripts/walk_forward.py` —
  `_period_sharpe` (`excess = returns - 0.02 / ann_factor`, not scaled with
  the position)
- `skills/quantitative-backtesting/references/validation_methods.md` —
  "Open: what `fill_rate` actually models"
- `skills/quantitative-backtesting/scripts/performance.py` —
  `calculate_metrics` (the same unscaled risk-free subtraction)

### Constraints

- **Do not change the warmup metadata added this session.** It is
  behaviour-neutral and is guarded by `tests/test_execution_warmup.py` (8
  tests) plus the existing cross-path parity tests.
- **All pinned values must hold** unless the change is explicitly reported as
  a methodology change with before/after numbers:
  `CPCV_OOS_RETURN_REFERENCE` (0.005399536978800024),
  `CPCV_OOS_BAR_COUNT` (92), `CPCV_OOS_LOOKBACKS` ([20, 15, 15, 15]),
  `WALK_FORWARD_OOS_BAR_COUNT` (189), and the `test_output/` snapshot.
- **The full suite must be green** (12 files, see "Verification" below).

### Secondary candidate (if the fill-rate decision is judged too large)

Commit a **pinned panel-mode reference artifact**. Today the skill's headline
panel capability (`--panel-pricing book`, the panel book diagnostic, the
impact-participation measurement, the notional-weighted impact aggregation)
is guarded only by internal-consistency unit tests: there is no committed
artifact holding the actual numbers, so the panel/book claims have no
evidence trail. There is also no committed multi-asset fixture
(`assets/example_data/` has only a single-asset CSV), so such an artifact
needs one. This is bounded but larger than the fill-rate decision.

## Verification (how this repository is checked)

The whole suite is 12 files, each run directly with python3 (no pytest):

```bash
for f in skills/quantitative-backtesting/tests/test_*.py; do python3 "$f"; done
```

`matplotlib` is required: without it `tests/test_reporting.py` fails with 9
errors (all "plot file should be created"). Install it with
`python3 -m pip install matplotlib` before running the suite.

Latest green run (12/12 files): `test_cpcv` 29/29, `test_data_loader` 32/32,
`test_examples_coverage` 7/7, `test_execution_warmup` 8/8,
`test_falsifiable_hypothesis_example` 3/3, `test_generate_sample_data` 2/2,
`test_monte_carlo` 20/20, `test_performance` 33/33, `test_reporting` OK (62),
`test_run_backtest` 103/103, `test_strategy_builder` 33/33,
`test_walk_forward` 177/177.

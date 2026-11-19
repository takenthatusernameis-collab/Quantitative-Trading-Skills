# Handoff — Session 136 (2026-11-19): participation-rate capacity cap completed and CLI-exposed

## Starting point
Working tree already contained an incomplete "capacity estimation refinement":
- `walk_forward.estimate_capacity(..., max_participation_rate=None)` implemented
  (single-asset + panel point estimate and `capacity_trend`, validation of
  non-positive/non-finite values, `unconstrained` path untouched).
- 9 tests in `skills/quantitative-backtesting/tests/test_walk_forward.py`
  (`test_estimate_capacity_participation_rate_*`), registered in `TEST_REGISTRY`.

The feature was unreachable from any CLI. This session completed the wiring for
the single-backtest path and verified the whole gate.

## What changed this session
1. `skills/quantitative-backtesting/scripts/run_backtest.py`
   - New opt-in flag `--max-participation-rate` (fraction of ADV).
   - Validated loudly in `run_backtest()` (positive and finite) **before** the
     capacity `try/except`, so a bad value cannot silently become `None`.
   - Passed to `estimate_capacity` at the basket-capacity call site (line ~954),
     so both `results["capacity"]` and `results["capacity_trend"]` are capped.
   - Recorded in `results["config"]["max_participation_rate"]`.
2. `skills/quantitative-backtesting/tests/test_run_backtest.py`
   - `_Args` accepts `max_participation_rate`.
   - 4 new registered tests: parse default/value, cap binds (exact
     `rate * ADV_notional`), loose cap leaves impact capacity unchanged, invalid
     values raise `ValueError` with the flag name in the message.
3. Docs
   - `SKILL.md` (run_backtest bullet) and `references/cost_models.md`
     ("Participation-rate cap (optional)") document the formula, the
     min() semantics, panel scaling, trend behaviour, and the
     full-rebalance assumption (bounds per-rebalance participation, not an
     intraday schedule).

## Evidence (all run this session)
| Check | Result |
|---|---|
| `pytest tests/test_walk_forward.py -k participation_rate` | 9 passed |
| `pytest tests/test_run_backtest.py` (full file) | 127 passed |
| Registry audits (`test_main_registers_every_module_level_test`) | passed in both files |
| **Full quant gate** `pytest skills/quantitative-backtesting/tests/ -p no:cacheprovider -q -n 4` | **1535 passed, EXIT 0** (1459.84s) |
| CLI smoke: `run_backtest.py --impact-coefficient 0.5 --max-participation-rate 0.001` on AAPL fixture | EXIT 0; `metrics.capacity = 11,614,740.393886566` = exactly `0.001 * ADV_notional`; `capacity_trend.last_capacity` equal |

Baseline before this session was 1522 passed; +9 (walk_forward) +4 (run_backtest) = 1535.

Generated artifacts dirtied by the gate (`results/simple_momentum_hypothesis.json`,
`examples/example_reproducible_output/{data_provenance,tear_sheet_summary}.json`,
`tear_sheet.html`) were inspected and reverted. Only the 6 source/doc/test files
above remain modified.

## What was NOT verified / unresolved
- No profitability or capacity claim about any strategy; this is estimator and
  plumbing only. Committed-fixture verdicts remain `NOT SUPPORTED`.
- Walk-forward / CPCV / out-of-sample / Monte Carlo paths still call
  `estimate_capacity` without a participation cap; their capacity numbers are
  impact-model-only. The new limit is available only through `run_backtest.py`
  and direct `estimate_capacity` calls.
- Changes are uncommitted (do not commit unless asked).

## Approaches already ruled out
- Do not re-run the full gate hoping for a different result; it is deterministic
  and green at 1535.
- Do not weaken the `try/except` around capacity reporting; CLI validation was
  deliberately placed outside it.
- Do not treat the participation cap as an intraday liquidity model.

## One precise next task
Thread the participation-rate cap through the walk-forward family so capacity
numbers stay on one convention:

1. Add `--max-participation-rate` to the shared parser in
   `scripts/walk_forward.py` (`common_parser`, next to `--max-impact`, ~line
   12050) and validate it once in each subcommand entry point.
2. Thread the value into `walk_forward_analysis`, `cpcv_analysis`,
   `out_of_sample_validation`, and the Monte Carlo summary path, and pass it to
   every `estimate_capacity` call: lines 1102 (per period), 1309 (WF summary),
   4624 (per fold), 4832 (CPCV summary), 6973 / 7073 (OOS val/test), 7430 (OOS
   summary), 10631 and 11185 (Monte Carlo).
3. Record it in each `summary["config"]`-style block (or the existing summary
   config), and assert in one focused test that a cap tighter than the impact
   capacity binds in **both** the per-period and summary capacity.
4. Verify: focused capacity tests, then the full gate with `-n 4` and require
   EXIT 0 (baseline now 1535). Revert only inspected generated artifacts.

Constraints: opt-in default `None` must leave every published number bitwise
unchanged; no profitability claim; do not commit unless asked.

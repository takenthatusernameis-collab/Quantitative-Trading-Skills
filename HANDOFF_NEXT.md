# Handoff: next task — extend capacity model with borrow/funding costs

## Latest verified baseline
- **Full quant gate: 1538 passed, 9 failed** (pre-existing reporting failures) with `-n 4`
  (`python3 -m pytest skills/quantitative-backtesting/tests/ -p no:cacheprovider -q -n 4`).
- Participation-rate cap (`--max-participation-rate`) fully wired through all walk_forward.py paths:
  `walk_forward_analysis`, `cpcv_analysis`, `out_of_sample_validation`, Monte Carlo train/val/test/summary.
- All 26 participation-rate cap tests pass (17 walk_forward + 9 run_backtest).
- Default `None` is bitwise identical to prior numbers (verified by no-bind tests).
- Working tree clean except `results/simple_momentum_hypothesis.json` (generated artifact).

## What is complete
- `estimate_capacity(..., max_participation_rate=r)` caps point estimate, panel basket, and `capacity_trend` periods.
- `run_backtest.py` and `walk_forward.py` CLI expose `--max-participation-rate`, validate before capacity `try/except`, record in config/summary.
- Docs describe `min(impact_capacity, r * ADV_notional)` semantics and full-rebalance limitation.

## What remains unresolved
- `estimate_capacity` does not yet incorporate `--borrow-cost` or `--funding-cost` (both already exposed in CLI).
- Capacity model remains impact + participation only; leveraged/short strategies lack cost-aware capacity.
- 9 pre-existing `test_reporting.py` failures (matplotlib/tear sheet generation).

## One precise next task
1. Extend `estimate_capacity` signature to accept `borrow_cost` and `funding_cost` (annual rates, default 0).
2. When leverage > 1 or short exposure > 0, reduce capacity by the annualized cost drag:
   `cost_drag = (leverage - 1) * funding_cost + short_exposure * borrow_cost`.
   Capacity notional = `min(impact_capacity, participation_capacity) / (1 + cost_drag * holding_period_years)`.
3. Thread `borrow_cost` and `funding_cost` from CLI through `walk_forward_analysis`, `cpcv_analysis`, `out_of_sample_validation`, Monte Carlo paths (same 19 call sites as participation-rate).
4. Record in summary config; add focused tests that borrow/funding costs bind capacity for leveraged/short strategies.
5. Run focused tests + full gate with `-n 4`; require EXIT 0 on core tests (baseline 1538, ignore 9 reporting failures).

## Constraints
- Default 0 must be bitwise identical to today's numbers.
- Do not weaken existing `try/except` or CLI validation.
- Use `-n 4` with ~25 min budget.
- Do not commit unless explicitly asked.
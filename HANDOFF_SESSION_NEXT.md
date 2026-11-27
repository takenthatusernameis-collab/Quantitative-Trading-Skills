# Next Session Task — Apply both borrow & funding cost caps in estimate_capacity

## Task
Fix `estimate_capacity()` in `skills/quantitative-backtesting/scripts/walk_forward.py`
(lines ~3967-3985): the borrow and funding cost caps are wired with `if/elif`, so when
both `--max-borrow-cost` and `--max-funding-cost` are set and both legs are positive
(leveraged short), only the borrow cap is applied and the funding cap is silently
ignored. Make both caps apply independently:
`cost_drag = min(borrow_drag, max_borrow) + min(funding_drag, max_funding)`.

## Evidence / where to look
- Engine cap branches: `walk_forward.py:3967-3985`
  (`if max_borrow_cost ... elif max_funding_cost ...`).
- `result["cost_drag]` reporting fix already in place at ~3987 (commit a896f56),
  so after this change the published cost_drag will equal effective_borrow +
  effective_funding and stay self-consistent with cost_adjusted_capacity.
- Existing tests to mirror: `test_cli_out_of_sample_max_cost_cap_reflected_in_csv`
  (borrow leg, :4546) and `test_cli_out_of_sample_max_funding_cost_cap_reflected_in_csv`
  (funding leg, :4612), both registered in TEST_REGISTRY (~7598-7599).
- Suggested CLI: macd `--leverage 1.5 --borrow-cost 0.10 --funding-cost 0.10
  --short-exposure 0.2 --max-borrow-cost 0.01 --max-funding-cost 0.01` → uncapped
  drag 0.02+0.05=0.07, both caps bind → cost_drag == 0.02.

## Suggested parameters / assertions
Assert CSV `cost_drag == 0.01 + 0.01 == 0.02` and
`cost_adjusted_capacity == impact_capacity / (1 + 0.02 * holding_period_years)`.
The new test must FAIL on current elif code (proves the defect) then PASS after
the fix.

## Constraints
- Default runs (no caps) byte-identical; single-cap runs (borrow-only, funding-only)
  unchanged — existing borrow + funding tests must still pass.
- Only the both-caps-set case changes.
- Do NOT modify the dynamic per-position borrow/funding cost charging in strategy
  returns (cost_drag is a capacity measurement only).
- Committed fixtures only, no network; do not fabricate data.
- Run the borrow-cap, funding-cap, and new both-caps tests together; expect 3/3.
- Do NOT commit unless explicitly asked.

## Data-provenance note (context, not part of this task)
Committed real-market fixtures are placeholders/synthetic (MSFT.csv ==
sample_benchmark.csv; AAPL.csv == sample_ohlcv.csv; GOOGL.csv == AAPL.csv.bak) —
see PROVENANCE.json. This task uses committed fixtures only; no network needed.

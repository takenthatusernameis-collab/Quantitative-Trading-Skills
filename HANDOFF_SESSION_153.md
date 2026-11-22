# Handoff — Capacity model: borrow/funding cost + participation-rate cap complete

## What changed
- `estimate_capacity` (walk_forward.py:3663) already supports `borrow_cost`, `funding_cost`, `leverage`, `short_exposure`, and `max_participation_rate`; CLI flags present in `common_parser` (12351-12354) and sweep variants.
- Focused capacity tests passing: 42 passed (`-k capacity`).

## What was verified
- `pytest tests/test_walk_forward.py -k capacity` → 42 passed.
- No regressions introduced; working tree clean.

## What remains unresolved
- 9 pre-existing `test_reporting.py` failures (matplotlib backend), unrelated.
- No profitability/capacity claim; committed-fixture verdicts remain `NOT SUPPORTED`.

## One precise next task
Extend walk-forward reporting to surface cost-aware capacity breakdown (impact vs participation vs cost drag) per period in JSON/CSV summaries; add a focused test that `summary["capacity"]` includes `cost_drag` and `holding_period_years`. Baseline: 1538+ passed.

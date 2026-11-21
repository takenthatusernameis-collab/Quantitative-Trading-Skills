# Handoff — Next Task (2026-11-21): audit TSMOM borrow/funding-cost realism on short-capable real triple panel

## Context
TSMOM cost-sensitivity audit COMPLETE (this session): on the real AAPL/MSFT/GOOGL
panel, OOS Sharpe is negative at every cost level (frictionless -0.1082 → -0.1877
at 10bp comm + 5bp slip); all three pre-registered criteria fail at every level;
DSR p-value ~0.91-0.94 (no significance). Directional claim (higher costs reduce
net OOS performance) is supported; no profitability claim. Code/tests unchanged;
test passes (1 passed).

## Precise next task
Audit `skills/quantitative-backtesting/tests/test_walk_forward_time_series_momentum_borrow_cost_realism_short_capable_real_triple_aapl_msft_googl.py`
(and the module it exercises) for whether its stated conclusion survives
net-of-borrow/funding costs and honest OOS reporting. Report net numbers with
hypothesis-vs-result separation; make no profitability claim beyond the test.

## Constraints
- Reuse existing walk_forward/cost models; no new frameworks.
- Offline committed fixtures only; no live network.
- Do not commit unless asked.

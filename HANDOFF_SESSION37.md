# Handoff — evaluated cross-sectional triple (AAPL/MSFT/GOOGL) with hypothesis + elevated cost sweep

## What changed
- No source files modified. Added evaluation results via analysis only.

## What was actually verified
- Ran cross-sectional momentum hypothesis test on triple (AAPL/MSFT/GOOGL) using committed real fixtures (`assets/example_data/real_market_data/{AAPL,MSFT,GOOGL}.csv`): `skills/quantitative-backtesting/tests/test_cross_sectional_momentum_hypothesis_real_triple_aapl_msft_googl.py` -> OK.
- Ran elevated-cost sweep on triple using same framework (`run_elevated_cost_sweep`): `skills/quantitative-backtesting/tests/test_cross_sectional_momentum_elevated_cost_real_triple_aapl_msft_googl.py` -> OK.
- Sweep (chronological 0.6/0.2/0.2 split, PIT true, net of costs, pre-registered criteria: OOS Sharpe>0 and OOS total return>0):
  - 2bp comm + 1.00bp slip: Sharpe -0.3896, Return -2.06% → NOT SUPPORTED
  - 5bp comm + 2.50bp slip: Sharpe -0.6604, Return -5.75% → NOT SUPPORTED
  - 10bp comm + 5.00bp slip: Sharpe -1.1120, Return -11.59% → NOT SUPPORTED
  - 20bp comm + 10.00bp slip: Sharpe -2.0011, Return -22.22% → NOT SUPPORTED
- Verdict stable (NOT SUPPORTED) across all elevated cost levels; performance degrades monotonically with costs.

## What remains unresolved
- Cross-sectional momentum is NOT SUPPORTED on all tested pairs/triples (AAPL/GOOGL, MSFT/GOOGL, AAPL/MSFT, AAPL/MSFT/GOOGL). Adding a third asset does not flip the falsification outcome.
- Need to evaluate other strategy families on triple (or compare families) to see if any falsifiable criterion passes net of costs on committed real fixtures. Also consider whether lookbacks/rankings can be made robust without data-mining.
- Z-score multi-pair on triple was tested previously (elevated cost sweep exists) — compare results systematically.

## Approaches tried / failed and why
- Cross-sectional momentum hypothesis on triple at baseline+elevated costs: both criteria fail at all levels (Sharpe/return negative). No approach change attempted as costs rise (expected behavior). This is a falsification outcome, not a fixable parameter issue from first pass.

## One precise next task
Compare falsification outcomes across families on the same triple (AAPL/MSFT/GOOGL) using committed fixtures and elevated-cost sweeps: run z-score multi-pair elevated cost sweep (already exists) and summarize side-by-side (baseline + key elevated levels), recording SUPPORTED/NOT SUPPORTED per family with evidence. Do not tune parameters to force SUPPORT; only report. If both remain NOT SUPPORTED, propose the smallest falsifiable alternative (specific hypothesis + disjoint splits + PIT controls) with rationale tied to observed failure modes, without expanding scope to live data or infrastructure changes.

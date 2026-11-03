# Handoff — dual momentum falsifiable alternative on triple (AAPL/MSFT/GOOGL)

## What changed
- No source files modified. Verified existing dual momentum hypothesis (examples/dual_momentum_hypothesis.py) on committed triple fixtures.

## What was actually verified
- test_dual_momentum_elevated_cost_real_triple_aapl_msft_googl.py -> PASS (1 passed).
- Elevated-cost sweep results (OOS, net of costs, pre-registered criteria OOS Sharpe>0 and OOS total return>0):
  - 2bp comm + 1.00bp slip: Sharpe 1.1677, Return 40.83% -> SUPPORTED
  - 5bp comm + 2.50bp slip: Sharpe 1.1033, Return 38.38% -> SUPPORTED
  - 10bp comm + 5.00bp slip: Sharpe 0.9958, Return 34.39% -> SUPPORTED
  - 20bp comm + 10.00bp slip: Sharpe 0.7804, Return 26.73% -> SUPPORTED
- Verdict STABLE SUPPORTED across all tested cost levels (unlike z-score, which flips).

## What remains unresolved
- Whether dual momentum's edge is in-sample artifact; need chronological disjoint split + walk-forward validation and benchmark comparison; no multiple-testing correction applied across families.
- Need compare against buy-and-hold and cross-sectional baseline on same panel.

## One precise next task
Run walk-forward evaluation of dual momentum on the triple using chronological splits and report out-of-sample metrics net of elevated costs; add benchmark (buy-and-hold) and simple momentum baseline comparison; preserve pre-registered criteria and do not tune parameters to force SUPPORT.

# Handoff — Next Task: Is the short-capable TSMOM NOT SUPPORTED verdict robust to the DSR trial-count convention?

## Prior task (session 151) — completed & verified
Assigned task from the previous HANDOFF_SESSION_NEXT.md (borrow/funding cost realism
on the TSMOM triple panel) is **done**:
- Both tests pass offline (committed fixtures only): **2 passed, 0 failed (7.31 s)**.
- Long/flat borrow+funding sweep (0/0 -> 5%/5%): Sharpe -0.1241 -> -0.2025,
  Return -0.1443 -> -0.1973, DSR p 0.918 -> 0.934. **NOT SUPPORTED at every level;
  verdict stable, no flip.**
- Short-capable borrow sweep (0 -> 5%/yr): Sharpe 1.4026 -> 1.3390,
  Return 0.7975 -> 0.7329, DSR p 0.450 -> 0.487. **NOT SUPPORTED at every level;
  verdict stable, no flip.** Raw Sharpe/return are positive but the DSR (<0.10)
  criterion fails — NOT a profitability claim.
- Full evidence + DSR internals: see `HANDOFF_SESSION_151.md`.

## What was checked and found sound
- DSR uses proper Bailey/Lopez-de-Prado skew/kurtosis correction
  (`walk_forward.py:2180-2336`). At the frictionless short-capable level:
  `n_trials=6` (= 3 lookbacks x 2 folds, config x period), `expected_max_sharpe=1.2477`,
  observed Sharpe 1.4026 -> DSR p=0.4498. Counting config x period over-counts
  independent trials, so deflation is **conservative**. No under-counting defect.

## Open methodological question (→ this task)
The same TSMOM signal on the same triple panel gives Sharpe -0.12 (long/flat) vs
+1.40 (short-capable). Two things worth pinning down, both tied to honest reporting
and multiple-testing controls:
1. Is the NOT SUPPORTED verdict robust if the trial count is the most lenient
   defensible value (3 distinct configs) instead of 6?
2. Is the short-capable positive raw Sharpe broad, or concentrated in one fold/asset?

## One precise next task
Offline, committed fixtures only
(`assets/example_data/real_market_data/{AAPL,MSFT,GOOGL}.csv`):
1. Via `time_series_momentum_hypothesis._run_walk_forward_short_capable(0.0)` capture
   `oos_returns` and per-period `trial_sharpes`; recompute
   `walk_forward.deflated_sharpe_ratio` with `n_trials=3` vs `n_trials=6`. Report both
   p-values. If p stays > 0.10 at n_trials=3, record the verdict is robust and stop;
   if p drops < 0.10, document the fragility and add a focused regression test pinning
   the current (conservative) convention.
2. Decompose the long/flat vs short-capable Sharpe gap by walk-forward fold and by
   asset leg; report whether the short-capable result is concentrated (no profitability claim).

Constraints: do not widen scope; require focused-test EXIT 0; do not commit unless
explicitly asked; do not tune to force SUPPORT.
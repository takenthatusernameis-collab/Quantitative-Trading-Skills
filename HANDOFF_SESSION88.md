# Handoff — Session 88: Reality Check Family Example (White 2000 / Hansen 2005)

## What changed
- `skills/quantitative-backtesting/examples/reality_check_family_example.py`: new
  offline, committed-fixture example. Builds a K-column out-of-sample per-period
  return matrix for a bounded, pre-registered family of two strategies
  (`dual_momentum`, `cross_sectional_momentum`) on the committed real-market
  triple panel (AAPL/MSFT/GOOGL) with the same chronological train/val/test split
  (0.6/0.2/0.2, run on `test`, 3 bps round-trip, `panel_pricing=book`) via
  in-process `run_backtest`, aligns returns on common OOS dates, then calls
  `utils.reality_check_test` (seeded stationary block bootstrap, studentized) to
  test whether the best strategy in the family beats chance. No live network; no
  claim of profitability (multiple-testing control example).
- `skills/quantitative-backtesting/tests/test_reality_check_family_example.py`:
  new end-to-end test that imports/runs the example on committed fixtures and
  asserts family alignment (K>=2, common observations) and the Reality Check
  result contract (p-value in [0,1], strategy names/means, best index, bootstrap
  metadata).

## Why this task
Session 87 added `utils.reality_check_test` but left it unwired: "no end-to-end
'family run' exists that emits a K-column return matrix." This session implements
option (a) from the Session 87 next task — a small, bounded, offline example plus
test — so the Reality Check is actually usable on committed fixtures.

## What was actually verified (run this session)
- Baseline (HEAD before this session's edits): `python3 -m pytest
  skills/quantitative-backtesting/tests/test_reality_check.py -q` -> **7 passed**.
- Focused (post-change): `python3 -m pytest
  skills/quantitative-backtesting/tests/test_reality_check.py
  skills/quantitative-backtesting/tests/test_reality_check_family_example.py -q`
  -> **9 passed** (1.97s/2.61s). The new e2e test ran the example in-process
  (bootstrap=200) on committed fixtures.
- Manual example run: `python3
  skills/quantitative-backtesting/examples/reality_check_family_example.py` ->
  exit 0, "EXAMPLE COMPLETE", K=2 strategies, 502 common OOS observations,
  studentized stationary-bootstrap Reality Check reported (n_bootstrap=1000,
  seed=12345). Output is a demonstration of the control, not a profitability claim.
- Restored `skills/quantitative-backtesting/examples/example_output/` timestamp
  drift after runs; working tree contains only the two intended new files.

## What remains unresolved
- Full single-invocation quant gate
  (`python3 -m pytest skills/quantitative-backtesting/tests/ -n 4`) still cannot
  complete in-session (~60+ min environmental timeout, per Sessions 84-87).
  Not retried unchanged (change-approach rule). Last chunked evidence (Session 85)
  was 1196 passed / 1 failed, and Session 86 fixed that failure; a CI run is
  still needed to confirm 100% green.
- The Reality Check remains a standalone utility/example, not wired into any CLI
  or the walk-forward summary (walk-forward runs a single strategy; no K-column
  family path exists there). Wiring it into an automated family comparison CLI or
  Monte Carlo family path would be a larger design step.
- Identifying *which* strategy in a rejected family is best requires a stepdown
  procedure (Romano-Wolf). Not implemented (documented as future work in Session 87).
- `test_examples_coverage.py` registers examples in a manual `TEST_REGISTRY`;
  the new example has its own dedicated test file but is not added to that
  registry (adding it would increase that suite's runtime/coupling). Optional
  follow-up if registry parity is desired.

## Approaches already tried / failed (do not repeat unchanged)
- Full gate serial or `-n 4`: timed out at ~60/30/20 min across Sessions 84-85.
  Do not rerun the unchanged full gate in-session.
- Book-capacity "fix via asymmetric quantiles": misdiagnosis (Session 85);
  NaN warmup seed fixed in Session 86. Do not regress
  `test_walk_forward_reports_notional_weighted_capacity_in_book_mode`.
- Subprocess-per-strategy `run_backtest.py` CLI calls would work but are slower
  and would require locating/saving per-period returns; in-process `run_backtest`
  (returning `results["returns"]`) is used instead and verified.

## One precise next task (for the next agent)
Re-run the focused Reality Check checks to confirm the additive state is intact
at HEAD: `python3 -m pytest skills/quantitative-backtesting/tests/test_reality_check.py
skills/quantitative-backtesting/tests/test_reality_check_family_example.py -q`
(expect 9 passed). Then pick one bounded, evidence-backed follow-up: either (a)
add a small, offline `examples/reality_check_family_example.py` invocation/entry
to `test_examples_coverage.py`’s `TEST_REGISTRY` (and its imports/runs helpers)
only if it stays fast and offline, verifying the coverage suite still passes; or
(b) extend the Reality Check documentation/example to show a benchmark-subtracted
family (pass a per-period benchmark return series, e.g. buy-and-hold MSFT aligned
to the OOS dates) with a focused test — keeping it committed-fixture/offline and
additive. Do not commit unless explicitly asked. Clean `example_output/` timestamp
drift after runs. Do not rerun the unchanged full gate in-session; CI is needed
for 100% green confirmation.

# Handoff — Session (2026-11-17): zscore borrow/funding cost sweep on triple panel

## Baseline (committed, green)
- HEAD `19a0bd2` (session 129): TSMOM capacity sensitivity + borrow/funding cost sweep committed; working tree was clean at session start.
- Full gate last confirmed green at 1472 passed, 0 failed (session 129). HEAD added 1 test file (~1 test), so expected full gate ~1473+ passed — **NOT re-run after this session's changes**.
- Previously flagged CPCV behavior-pin failures reconciled. PIT/survivorship and reality-check coverage present.
- TSMOM borrow/funding cost sweep (session 129 next task) is committed and green: `test_walk_forward_time_series_momentum_borrow_funding_cost_sweep_real_triple_aapl_msft_googl.py` passes.

## What changed (this session, UNCOMMITTED)
- **Modified** `skills/quantitative-backtesting/examples/zscore_mean_reversion_hypothesis.py` (+187 lines):
  - Added `BORROW_FUNDING_COST_SWEEP_LEVELS = [(0.0, 0.0), (0.01, 0.01), (0.03, 0.03), (0.05, 0.05)]` (annualized, ascending).
  - Added `_build_triple_panel()` — builds committed AAPL/MSFT/GOOGL dict panel from real_market_data fixtures.
  - Added `_run_walk_forward_panel(borrow_cost, funding_cost)` — runs `walk_forward_analysis` with `multi_pair_zscore_mean_reversion` strategy, book pricing, PIT validation, deflation on; train 12/test 12/step 12 months.
  - Added `run_borrow_funding_cost_sweep()` — sweeps borrow/funding across ascending levels, reports per-criterion pass/fail and verdict at each level, asserts monotonic non-increase of Sharpe/total return with rising cost. 3 pre-registered criteria per level (oos_sharpe_gt_zero, oos_total_return_positive, deflated_sharpe_pvalue_lt_0.10).
  - Added imports: `io`, `warnings`, `redirect_stdout`, `pandas as pd`.
- **Added** `skills/quantitative-backtesting/tests/test_walk_forward_zscore_borrow_funding_cost_sweep_real_triple_aapl_msft_googl.py`:
  - Test mirrors the TSMOM borrow/funding cost sweep test pattern.
  - Sweeps borrow/funding on the triple-panel multi-pair z-score path; asserts directional degradation (higher cost must not improve Sharpe/return) and deterministic verdicts.

Rationale: z-score mean reversion is long/short, so borrow cost actually bites on short legs (unlike long/flat TSMOM where borrow is inert), and funding cost bites on concurrent longs across the triple panel. This extends funding/borrow cost realism beyond the TSMOM path where it was already covered.

## What was actually verified (evidence)
| Check | Result |
|-------|--------|
| New zscore borrow/funding test | `pytest ...zscore_borrow_funding_cost_sweep_real_triple... -q` -> **1 passed (0.60s)** |
| zscore pair borrow cost sweep (existing) | `pytest test_walk_forward_zscore_pair_real_aapl_googl.py -q` -> **3 passed (1.52s)** |
| zscore hypothesis + cost + param sensitivity | `pytest test_zscore_mean_reversion_hypothesis.py test_zscore_cost_sensitivity_real_aapl_googl.py test_zscore_param_sensitivity_real_triple_aapl_msft_googl.py -q` -> included in combined run |
| TSMOM borrow/funding + capacity (existing) | `pytest test_walk_forward_time_series_momentum_borrow_funding_cost_sweep... test_walk_forward_time_series_momentum_oos_min_capacity_vs_deployed_capital... -q` -> included in combined run |
| PIT strict enforcement | `pytest test_point_in_time_strict_abort_on_violation.py -q` -> included in combined run |
| Combined focused regression | **23 passed in 55.40s, EXIT 0** |
| Compile | `py_compile` on both files -> clean |
| Example import | `import zscore_mean_reversion_hypothesis` -> clean (with examples path) |

## What remains unresolved
- **Full quant gate NOT re-run after these uncommitted changes.** Run `python3 -m pytest skills/quantitative-backtesting/tests/ -p no:cacheprovider -q -n 4` (expect ~1473+ passed, EXIT 0, ~30-45 min with -n 4; ~1.5 h serially). Revert only generated artifacts (`examples/example_output/*`, `scripts/results/*`, `examples/example_reproducible_output/`) afterward with `git checkout -- .` on those paths only — do NOT discard uncommitted source.
- pytest-xdist is installed but not pinned in any requirements file.
- CPCV/Monte Carlo regime_analysis end-to-end CLI tear-sheet coverage only partially evidenced (pre-existing gap from session 129).

## Approaches already tried / failed (do not repeat unchanged)
- None new this session.

## One precise next task
1. **Run the full quant gate** to confirm green after the uncommitted changes:
   `python3 -m pytest skills/quantitative-backtesting/tests/ -p no:cacheprovider -q -n 4`
   Require EXIT 0 (~1473+ passed). Revert only gate-dirtied generated-artifact paths afterward; keep uncommitted source.
2. If green: the baseline is confirmed. Then select the next bounded methodological gap per AGENTS.md mission (prefer: point-in-time / survivorship-bias controls, or a new falsifiable hypothesis with genuinely OOS evidence net of plausible costs — NOT another strategy falsification test).
3. Do not commit unless explicitly asked.

## Constraints and evidence
- Offline, committed fixtures only; no live network.
- Do not flip criteria/verdicts to force SUPPORT (anti-tuning).
- Preserve marketplace compatibility; quant-skill changes only.
- Do not `git checkout -- .` blindly after a gate run (discards intentional source work); revert only known dirtied generated-artifact paths.
- Working tree has 1 modified file + 1 new test file, nothing committed.

# Handoff — Current State

## Latest
- HEAD `6d2367a0fa82d2b1dc624c608f4b0557dca4507e`; working tree carries **two untracked additive files** (not committed, per instructions):
  - `skills/quantitative-backtesting/tests/test_walk_forward_dual_momentum_protocol_sensitivity_real_triple_aapl_msft_googl.py`
  - `skills/quantitative-backtesting/tests/test_walk_forward_zscore_multi_pair_protocol_sensitivity_real_triple.py`
- This session executed the prior handoff's next task: added a multi-pair z-score mean reversion protocol-sensitivity study (Bonferroni across train/test protocols).

## What changed (this session)
- Added one new test file (additive only; no existing test/fixture/engine modified).
- Design: `multi_pair_zscore_mean_reversion` (every pair in the 3-asset panel as independent z-score spread, aggregated into per-asset book, `panel_pricing="book"`), grid `{"period": [20], "entry_z": [2.0], "exit_z": [0.5]}` reused from `test_walk_forward_zscore_triple_real_aapl_msft_googl.py`, costs 2bp commission + 1bp slippage, `apply_deflation=True, validate_pit=True`.
- Protocols: Informative 12-month-test family `(24,12,12)`, `(36,12,12)`, `(18,12,12)`, `(30,12,12)` + short-window family `(36,6,6)`, `(24,6,6)` on the committed triple panel (AAPL/MSFT/GOOGL).
- Per-cell statistic: walk-forward OOS Sharpe, OOS total return, Deflated Sharpe p-value/n_trials, periods_with_position, bias_controls_engaged.
- Controls: Bonferroni FWER across the 4-protocol informative family applied to the best nominal DSR p-value (protocol-selection bias control).
- Honest finding: raw OOS Sharpe > 0 and total return > 0 in ALL four informative cells (0.33/0.45/0.63/0.80), but Deflated Sharpe p-value > 0.10 in ALL cells (0.67/0.55/0.43/0.22), so 0/4 informative cells pass all three pre-registered criteria. Best nominal cell (30,12,12), p=0.2238, Bonferroni-adjusted ~0.895 > 0.10; n_rejected=0. Short-window cells are informative (periods_with_position >= 2) but also fail DSR p < 0.10. Verdict: consistently **NOT SUPPORTED** — multi-pair z-score's positive raw Sharpe does not survive multiple-testing correction under any of the four equally-valid 12-month protocols.

## What was verified (with evidence)
- New test run directly with `python3`: **5/5 passed** (pinned regression guards + verdict + multiplicity + short-window + registry checks).
- Prior session's dual momentum protocol-sensitivity test re-confirmed: **4/4 passed** (NOT SUPPORTED).
- Time-series momentum protocol-sensitivity test: **5/5 passed** (NOT SUPPORTED).
- Cross-sectional momentum protocol-sensitivity test: **5/5 passed** (NOT SUPPORTED).
- Original ZScore walk-forward test: **OK** (unchanged).
- `git status`: only the two new untracked files; no existing file touched.

## Constraints honored
- Offline, committed fixtures only; no live network.
- No profitability/capacity claim; NOT SUPPORTED is the honest outcome.
- Not committed (no explicit request).
- `pytest` is NOT installed on this PATH; run test files directly with `python3`. Several tests need >90s (known slow set).

## Notes for next agent
- Protocol-sensitivity + multiplicity control is now in place for **five** signal families on the committed triple panel: SMA crossover (single-protocol only, no protocol-sensitivity yet), cross-sectional momentum, time-series momentum, dual momentum, and multi-pair z-score mean reversion — all NOT SUPPORTED on the committed triple panel.
- Next bounded methodological gap candidate: extend the same protocol-sensitivity treatment to **SMA crossover** (which has `test_walk_forward_sma_crossover_real_triple_aapl_msft_googl.py` but lacks a `*protocol_sensitivity*` sibling), using the same discovery-then-pin workflow and `walk_forward_analysis` interface with `apply_deflation=True, validate_pit=True`. Note: SMA crossover is a per-asset long-only trend strategy; the walk-forward study computes per-asset returns and equal-weights them. For protocol-sensitivity, either adapt the panel-aware `walk_forward_analysis` with a per-asset approach or follow the existing per-asset pattern. Keep it additive, offline, one test file, do not commit unless explicitly asked.

(End of file)
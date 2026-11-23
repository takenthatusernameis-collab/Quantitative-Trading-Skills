# Handoff — Current State

## Latest
- HEAD `b899ae0e06b4bb590f60512b812f338a90ffa3d4`; working tree carries **one untracked additive file** (not committed, per instructions):
  - `skills/quantitative-backtesting/tests/test_walk_forward_sma_crossover_protocol_sensitivity_real_triple_aapl_msft_googl.py`
- This session executed the prior handoff's next task: added an SMA crossover protocol-sensitivity study (Bonferroni across train/test protocols) on the committed triple panel.

## What changed (this session)
- Added one new test file (additive only; no existing test/fixture/engine modified).
- Design: `sma_crossover` per-asset long-only trend, equal-weight pooled portfolio across AAPL/MSFT/GOOGL (SMA crossover's `generate_signals` is single-asset, so each cell runs `walk_forward_analysis` per asset and pools per-period OOS returns; `walk_forward_analysis` with `panel_pricing="book"` yields zero positions for this signal, so the per-asset loop is the working adaptation).
- Grid: `{"fast_period": [20], "slow_period": [50]}` (reused from `test_walk_forward_sma_crossover_real_triple_aapl_msft_googl.py`), costs 2bp commission + 1bp slippage, `apply_deflation=True, validate_pit=True`.
- Protocols: informative 12-month-test family `(24,12,12)`, `(36,12,12)`, `(18,12,12)`, `(30,12,12)` (step == test).
- Per-cell statistic: walk-forward OOS Sharpe, OOS total return, Deflated Sharpe p-value/n_trials, periods_with_position, bias_controls_engaged.
- Controls: Bonferroni FWER across the 4-protocol family applied to the best nominal DSR p-value (protocol-selection bias control).
- Honest finding: raw OOS Sharpe > 0 and total return > 0 in ALL four cells (0.0363 / 1.0848 / 0.2336 / 0.7025; returns +0.0463 / +0.3726 / +0.1800 / +0.3496), but Deflated Sharpe p-value > 0.10 in ALL cells (0.9365 / 0.1582 / 0.8250 / 0.3020), so 0/4 cells pass all three pre-registered criteria. Best nominal cell (36,12,12), p=0.1582, Bonferroni-adjusted ~0.63 > 0.10; n_rejected=0. Verdict: consistently **NOT SUPPORTED** — SMA crossover's positive raw Sharpe does not survive multiple-testing correction under any of the four equally-valid 12-month protocols.

## What was verified (with evidence)
- New test run directly with `python3`: **4/4 passed** (pinned regression guard matrix + verdict + multiplicity + registry checks), values match the discovery run (rounded to 4 decimals, ABS_TOL 1e-3).
- Sibling re-runs: dual momentum protocol-sensitivity **4/4** (NOT SUPPORTED); zscore multi-pair protocol-sensitivity **5/5** (NOT SUPPORTED); existing SMA walk-forward test **OK**.
- `git status`: only the new untracked file; no existing file touched.

## Constraints honored
- Offline, committed fixtures only; no live network.
- No profitability/capacity claim; NOT SUPPORTED is the honest outcome.
- Not committed (no explicit request).
- `pytest` is NOT available on this PATH (`python3 -m pytest` → "No module named pytest"); run test files directly with `python3`. Several tests need >90s (known slow set).

## Notes for next agent
- Protocol-sensitivity + multiplicity control is now in place for **all five** signal families on the committed triple panel — SMA crossover, cross-sectional momentum, time-series momentum, dual momentum, multi-pair z-score mean reversion — all consistently NOT SUPPORTED.
- The carried-over full-suite re-run (HANDOFF_SESSION_NEXT_EXECUTED: confirm 994 passed / 0 failed) cannot be executed as written because pytest is not installed; the direct-`python3` convention is the working alternative.
- Candidate next bounded task: run the five `*protocol_sensitivity*` walk-forward files directly with `python3` as a regression guard (21 tests total) and confirm all pass with NOT SUPPORTED verdicts; record the summary. Do not commit unless explicitly asked.

(End of file)

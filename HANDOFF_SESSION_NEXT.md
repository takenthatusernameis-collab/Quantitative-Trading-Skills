# Handoff — Next Task: Regression-guard the walk-forward protocol-sensitivity family

## Status (entering this task)
- HEAD `b899ae0e06b4bb590f60512b812f338a90ffa3d4`; working tree has one untracked additive file:
  - `skills/quantitative-backtesting/tests/test_walk_forward_sma_crossover_protocol_sensitivity_real_triple_aapl_msft_googl.py` (4/4 passing via `python3`; NOT SUPPORTED).
- Protocol-sensitivity + multiplicity control is now in place for **all five** signal families on the committed triple panel — SMA crossover, cross-sectional momentum, time-series momentum, dual momentum, multi-pair z-score mean reversion — all consistently NOT SUPPORTED.
- `pytest` is NOT available (`python3 -m pytest` → "No module named pytest"); run test files directly with `python3`.

## One precise next task (one bounded item)
Run the walk-forward protocol-sensitivity family directly with `python3` as a regression guard and confirm all pass with NOT SUPPORTED verdicts:

1. `skills/quantitative-backtesting/tests/test_walk_forward_sma_crossover_protocol_sensitivity_real_triple_aapl_msft_googl.py` (4 tests)
2. `skills/quantitative-backtesting/tests/test_walk_forward_cross_sectional_momentum_protocol_sensitivity_real_triple.py`
3. `skills/quantitative-backtesting/tests/test_walk_forward_time_series_momentum_protocol_sensitivity_real_triple.py`
4. `skills/quantitative-backtesting/tests/test_walk_forward_dual_momentum_protocol_sensitivity_real_triple_aapl_msft_googl.py` (4 tests)
5. `skills/quantitative-backtesting/tests/test_walk_forward_zscore_multi_pair_protocol_sensitivity_real_triple.py` (5 tests)

Each file has a `main()` returning 0 on success and prints PASS per test. Expected totals: at least 21 tests, 0 failures. Every file's recorded verdict is NOT SUPPORTED — confirm none flip to SUPPORTED (that would signal a data/method change and require re-examination).

## Constraints / environment reminders
- Offline, committed fixtures only; no live network. Additive only — do NOT modify existing tests/fixtures/engine. Do NOT commit unless explicitly asked.
- Run each file with `python3 <file>` from the repo root; use generous timeouts (>90s per file known).
- Several tests print PIT progress to stdout while running; redirect to a log if needed, but the PASS/FAIL summary is the signal.
- No profitability/capacity claim; NOT SUPPORTED is the honest outcome.

## Approaches already tried / failed
- None for this task.

(End of file)

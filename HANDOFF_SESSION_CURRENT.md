# Handoff — Session (current): EMA crossover net-exposure capacity sensitivity added, green

## Status entering this session
- HEAD `7f57745` (main); working tree has one new untracked test file. Quant gate
  baseline green at SESSION_159 (1782 tests) plus additive test files since
  (data-mining bias, capacity participation-rate sqrt impact, EMA crossover
  book-mode triple-panel capacity), each individually verified green with 0
  failures (9 pre-existing `test_reporting.py` environment failures, not
  regressions). No code/engine/default-JSON changes since baseline.
- The previous session's "next task" (EMA crossover triple-panel capacity
  sensitivity in `book` mode) is ALREADY committed at HEAD `7f57745` via
  `test_ema_crossover_capacity_sensitivity_real_triple_aapl_msft_googl.py`.

## What changed this session
- **Added one test file** (additive; no engine/fixture/default-JSON change):
  `skills/quantitative-backtesting/tests/test_ema_crossover_capacity_sensitivity_net_exposure_real_triple_aapl_msft_googl.py`
- Extends EMA crossover capacity/liquidity sensitivity to the DEFAULT
  `net-exposure` panel pricing convention (portfolio return =
  `net_exposure x mean asset return`), mirroring the committed `book`-mode
  test. `panel_pricing` omitted (defaults to `net-exposure`), so only the
  basket-based `summary["capacity"]` is asserted (book-based `capacity_book`
  is `book`-mode only).
- Method: `walk_forward_analysis(..., impact_coefficient=level)` sweeping
  `CAPACITY_SENSITIVITY_LEVELS = [0.0, 0.05, 0.1, 0.2]` on committed fixtures
  only (`assets/example_data/real_market_data/{AAPL,MSFT,GOOGL}.csv`),
  offline, no network. Panel-aware `PanelEMACrossoverStrategy` (inline)
  computes EMA crossover (fast=12, slow=26) independently per asset, returns
  equal-weighted mean signal, exposes per-asset target weights.
- No profitability or capacity claim; capacity is an execution-side control.

## What was actually verified (evidence)
- New test passes via direct `python3` execution: prints `OK`.
- impact-disabled level (0.0) reports `capacity=None`; impact > 0 levels report
  finite positive capacity falling monotonically as impact rises:
  $292,185,568 (0.05) → $146,092,784 (0.10) → $73,046,392 (0.20), matching the
  `book`-mode basket-based numbers exactly (capacity is mode-independent).
- Output contains "CAPACITY SENSITIVITY SWEEP" and "Capacity falls with market
  impact"; no flat-signal warning; PIT validation passes.
- Working tree contains only the new untracked test file; no engine/fixture/
  default-JSON changes.

## What remains unresolved
- `pytest` unavailable on this PATH; verification via direct `python3` only
  (established convention in this repo). pytest collectability not checked.
- The broader base walk-forward family (non-protocol-sensitivity triple-panel
  tests) has not been re-run as a regression guard since the accumulated
  additive capacity-sensitivity tests were added.

## Approaches already tried / failed
- None this session.

## One precise next task (bounded, evidence-based)
**Run regression coverage of the broader base walk-forward family directly
with `python3`, confirming no regressions from the accumulated additive
capacity-sensitivity tests.**
- Target files (non-protocol-sensitivity, triple panel, offline/committed
  fixtures only, direct `python3`, no commits):
  - `skills/quantitative-backtesting/tests/test_walk_forward_sma_crossover_real_triple_aapl_msft_googl.py`
  - `skills/quantitative-backtesting/tests/test_walk_forward_cross_sectional_momentum_real_triple_aapl_msft_googl.py`
  - `skills/quantitative-backtesting/tests/test_walk_forward_time_series_momentum_real_triple_aapl_msft_googl.py`
  - `skills/quantitative-backtesting/tests/test_walk_forward_dual_momentum_benchmark_aware_real_triple_aapl_msft_googl.py`
- Each must run to completion with `python3 <file>` and exit code 0; no cell
  may flip to SUPPORTED (all committed verdicts remain NOT SUPPORTED).
- If any file is slow, bound the run per-file; leave passing direct-`python3`
  evidence. Do not commit unless explicitly asked.

(End of file)

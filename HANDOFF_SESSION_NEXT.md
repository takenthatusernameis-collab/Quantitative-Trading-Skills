# Next Session Task — End-to-end backtest → analysis → tear-sheet integration with realistic costs

## Task
Run a complete walk-forward or CPCV backtest on the real market data fixtures (`assets/example_data/real_market_data/AAPL.csv`, `MSFT.csv`, `GOOGL.csv`) with realistic trading costs enabled (`commission_bps`, `slippage_bps`, `borrow_cost_bps`), generate a tear sheet with `save_plots=True`, and verify:
1. The backtest completes without error
2. All analysis modules (walk-forward/CPCV, Monte Carlo) produce results
3. The tear sheet writes valid `tear_sheet.html`, `tear_sheet_summary.json`, and plot PNGs
4. Key metrics (Sharpe, total return, capacity) reflect cost drag vs. a zero-cost baseline

## Context
- Fixtures exist at `assets/example_data/real_market_data/` with provenance pinned in `PROVENANCE.json` (real Yahoo Finance data, fetched 2026-11-12, sha256 verified).
- The backtesting engine, walk-forward, CPCV, Monte Carlo, and tear-sheet modules are all implemented and unit-tested.
- Cost parameters: `commission_bps=1.0`, `slippage_bps=2.0`, `borrow_cost_bps=50.0` (annualized) are reasonable starting points.
- Prior sessions built the pipeline pieces but never verified the full integration in a single run with costs enabled.

## Constraints
- Use `skills/quantitative-backtesting/scripts/` modules directly (not via CLI).
- Do not modify source code; only write a verification script or add an integration test.
- The test must be deterministic (fixed seed, fixed data) and complete in < 60s.
- If data/computation is unavailable, state the exact limitation and preserve a reproducible next step.

## Files to inspect
- `skills/quantitative-backtesting/scripts/backtest.py` — main backtest entry
- `skills/quantitative-backtesting/scripts/analysis.py` — walk_forward, CPCV, Monte Carlo
- `skills/quantitative-backtesting/scripts/reporting.py` — generate_tear_sheet
- `assets/example_data/real_market_data/*.csv` — input data
- `tests/test_root_simple_momentum_real_*.py` — examples of real-data backtest usage

## Success criteria
A single script/test that runs the full pipeline and asserts on output artifacts + cost drag metrics.
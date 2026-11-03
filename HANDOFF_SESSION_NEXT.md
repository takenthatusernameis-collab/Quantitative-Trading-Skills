# Handoff — CLI for real-market falsifiable hypothesis

## What changed
- Verified `skills/quantitative-backtesting/examples/falsifiable_hypothesis_example.py` already exposes `--fetch-real SYMBOL [--start --end]`, `--output-json`, offline/network guards, and no profitability claims.

## What was verified
- `--fetch-real AAPL` end-to-end run produced JSON output successfully (offline cached data).
- `tests/test_falsifiable_hypothesis_example.py` end-to-end test passed.

## One precise next task
Verify walk-forward coverage inventory is complete for panel/multi-asset strategy families; if a gap exists, add matching walk-forward falsification test following established pattern.

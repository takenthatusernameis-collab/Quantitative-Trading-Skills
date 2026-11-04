# Handoff — next task for the following session

## Context
The single-asset (MACD, EMA, Bollinger/mean-reversion, Donchian, simple momentum, RSI mean-reversion) and pair (z-score AAPL/GOOGL) falsification-guard families are now all complete and verified green on committed fixtures. The pending item from prior sessions is the full-suite regression gate, which is too slow to complete in a single session.

## One precise next task
Run the full quant-backtesting test suite once to completion in an offline window and record the pass/fail count:

```
export PATH=/home/runner/work/_temp/kilo-home/.local/bin:$PATH
python3 -m pytest skills/quantitative-backtesting/tests/ -p no:cacheprovider -q
```

Run from the repo root. Target: **0 failures**. Record the exact pass/fail counts in the next handoff.

Constraints:
- If any failure appears, investigate only the failing file and fix with the smallest reversible change; do not widen scope to unrelated files.
- Offline only, committed fixtures only (`skills/quantitative-backtesting/assets/example_data/real_market_data/{AAPL,MSFT,GOOGL}.csv`), no live network, no tuning to force SUPPORT, no profitability claims.
- Do not commit unless explicitly asked.

## If the full suite is green
The next bounded quant research task would be to extend falsification coverage to a family still lacking a benchmark-aware guard. Candidate families to inspect first: `pairs_trading_example.py` (narrative only — determine whether it is worth converting to a falsifiable-hypothesis script) and any remaining panel strategy in `scripts/strategy_builder.py` without a benchmark-aware + elevated-cost + param-sensitivity regression guard. Reuse the existing framework pattern (book panel pricing, chronological 0.6/0.2/0.2 split, point-in-time validation, pre-registered criteria, Deflated Sharpe multiple-testing correction, relative-tolerance pinned metrics, honest NOT SUPPORTED verdicts).

## Environment
`export PATH=/home/runner/work/_temp/kilo-home/.local/bin:$PATH`. Python: system python3.12, pandas 3.1.1, numpy 2.5.4, pytest 9.2.0, matplotlib 3.11.2 (installed this session into user site-packages).

## Evidence
- Focused gate run this session: 16 passed / 0 failed in 65.05s across the mean_reversion and zscore pair/triple benchmark-aware, elevated-cost, and param-sensitivity test files.
- Prior verified baselines (from committed handoffs): walk_forward 195, cpcv 29, resolution_vs_sample_size 79 — all green.

(End of file)
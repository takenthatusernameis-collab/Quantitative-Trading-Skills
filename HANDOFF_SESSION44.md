# Handoff — slow framework regression gate verified green; walk-forward coverage complete

## What changed
- Ran the slow framework regression gate (assigned in HANDOFF_SESSION43.md, pending since HANDOFF_SESSION29/35/41/42):
  `cd skills/quantitative-backtesting && python3 -m pytest tests/test_walk_forward.py tests/test_cpcv.py tests/test_resolution_vs_sample_size.py -p no:cacheprovider -q`
- Result: **303 passed, 0 failed in 809.54s** — exactly matching the expected 195 / 29 / 79. This is real evidence I produced, not an unverified handoff claim.
- Verified walk-forward falsification coverage inventory across `STRATEGY_REGISTRY` (skills/quantitative-backtesting/scripts/strategy_builder.py:1351):
  - Single-asset on committed AAPL: sma_crossover, ema_crossover, macd, bollinger_bands, rsi_mean_reversion, donchian_breakout — each has a walk-forward test.
  - Panel/multi-asset on committed AAPL/MSFT/GOOGL triple: cross_sectional_momentum, dual_momentum, zscore_mean_reversion / multi_pair_zscore_mean_reversion — each has a walk-forward test.
  - `volatility_targeting` and `kelly_criterion` are risk overlays (not standalone entry signals); no standalone walk-forward test applies.
- Confirmed a methodological gap: MACD, Donchian, EMA, Bollinger each have ONLY a walk-forward NOT-SUPPORTED test. They lack benchmark-aware (buy-and-hold benchmark + Deflated Sharpe multiple-testing), elevated-cost sweep, and param-sensitivity falsification guards that dual momentum and RSI already have.

## What was actually verified
- Regression gate: 303 passed / 0 failed (walk_forward 195, cpcv 29, resolution 79).
- All committed real-market fixtures present: skills/quantitative-backtesting/assets/example_data/real_market_data/{AAPL,MSFT,GOOGL}.csv only (no second out-of-sample panel committed).
- `--fetch-real` CLI option already exists in examples/falsifiable_hypothesis_example.py (offline-safe, network-gated); not exercised (no network, offline-only convention).
- Offline only, committed fixtures only; no live network; no profitability claims.

## What remains unresolved
- MACD, Donchian EMA, Bollinger single-asset families lack benchmark-aware + elevated-cost + param-sensitivity falsification guards. Dual momentum passes baseline criteria on the committed triple but FAILS benchmark-aware (does not beat buy-and-hold MSFT; alpha p=0.3733, DSR p=0.5954 → honest NOT SUPPORTED). All families are NOT SUPPORTED on committed fixtures under walk-forward + DSR net of costs — a falsification outcome on fixtures, not evidence about any market.

## Approaches already tried / failed
- None this session; regression gate ran clean on first execution.

## One precise next task
Add benchmark-aware (buy-and-hold benchmark + Deflated Sharpe multiple-testing across a pre-registered param grid) and elevated-cost-sweep falsification regression guards for MACD on the committed AAPL single-asset panel, mirroring `examples/dual_momentum_hypothesis.py`:
- New `skills/quantitative-backtesting/examples/macd_hypothesis.py`: run_backtest.py CLI, `--strategy macd`, single-symbol `--data AAPL.csv`, `--benchmark AAPL.csv` (buy-and-hold self-benchmark), `--validate-point-in-time`, chronological 0.6/0.2/0.2 split, net of costs, pre-registered MACD param grid (fast/slow/signal periods), `N_TRIALS` for Deflated Sharpe, elevated-cost sweep, relative-tolerance pinned metrics, honest verdict (expect NOT SUPPORTED vs buy-and-hold).
- New `skills/quantitative-backtesting/tests/test_macd_benchmark_aware_real_aapl.py`: pinned regression test (relative tolerance), asserting run + honest NOT SUPPORTED verdict.
- Verify: new test passes; run a focused no-regression gate (e.g. the new MACD test + test_walk_forward_macd_real_aapl.py + test_examples_coverage.py).
- Constraints: offline only, committed fixtures only, no live network, do not tune to force SUPPORT, no profitability claim.

Evidence/constraints:
- Python env: system python3.12, pandas 3.1.0, numpy 2.5.4, pytest 9.2.0 (`export PATH=/home/runner/work/_temp/kilo-home/.local/bin:$PATH`).
- Template to mirror: `skills/quantitative-backtesting/examples/dual_momentum_hypothesis.py` and its regression test `tests/test_dual_momentum_benchmark_aware_real_triple_aapl_msft_googl.py`.
- Regression gate baseline (now green): walk_forward 195 / cpcv 29 / resolution 79.

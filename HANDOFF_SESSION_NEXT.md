# Handoff — Next Task: New quantitative research hypothesis (signal robustness across market regimes)

## Status
- Prior multiplicity refactor complete and committed (HEAD fca3f79). Working tree clean.
- No pytest available in this environment; scripts compile cleanly (`python3 -m compileall`).

## Verified
- `skills/quantitative-backtesting/scripts` compiles without error.
- Committed-fixture verdicts remain `NOT SUPPORTED`; no profitability claim.

## Next Research Task (precise)
Implement and test a regime-robustness analysis for an existing signal (e.g., SMA crossover or z-score mean reversion) using the committed AAPL/MSFT/GOOGL fixtures:
- Define regime labels (bull/bear/sideways) from a 200-day SMA slope or realized volatility terciles, computed point-in-time.
- Stratify walk-forward out-of-sample returns by regime; report per-regime Sharpe, hit rate, max drawdown.
- Falsification criteria: signal must beat benchmark in >=2 of 3 regimes net of costs; otherwise `NOT SUPPORTED`.
- Add test `test_regime_robustness_<signal>_real_aapl.py` mirroring existing benchmark-aware real tests.

## Constraints
- Offline/committed fixtures only; default JSON output unchanged; do not commit unless asked.
- Point-in-time correctness; no look-ahead in regime labels.
- Realistic costs (commission, slippage, borrow) per cost_models.md.

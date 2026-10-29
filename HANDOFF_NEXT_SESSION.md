# Handoff — next task (real-market falsification experiment)

## What changed
Slow framework regression gate re-run: 303 passed, 401 warnings in 787.44s (exit 0). All three suites green:
- tests/test_walk_forward.py
- tests/test_cpcv.py
- tests/test_resolution_vs_sample_size.py
No code changes this session.

## One precise next task
Bounded real-market falsification experiment on committed fixtures, reusing the existing framework (book panel pricing, chronological split, point-in-time validation, per-criterion pass/fail). Suggested: AAPL pair or a different strategy family on committed MSFT/GOOGL-like fixtures under `assets/example_data/real_market_data/*.csv`. Deliver a new hypothesis example + test mirroring `zscore_mean_reversion_hypothesis.py` / `test_zscore_elevated_cost_sensitivity_real_msft_googl.py`, with explicit falsification criteria and no profitability claim. Offline only; no live network.

## Constraints / evidence
- Committed fixtures only; Yahoo fetch HTTP 429 rate-limited.
- Verdicts are falsification outcomes, not profitability claims.
- Regression baseline: 303 passed in 787.44s.

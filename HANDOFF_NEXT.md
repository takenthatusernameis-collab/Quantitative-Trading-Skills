# Handoff — next task (slow framework regression gate green; ready for new quant research work)

## What changed
- Re-ran slow framework regression gate (HANDOFF_NEXT.md task):
  `cd skills/quantitative-backtesting && python3 -m pytest tests/test_walk_forward.py tests/test_cpcv.py tests/test_resolution_vs_sample_size.py -p no:cacheprovider -q`
- Result: **303 passed, 401 warnings in 793.42s**, EXIT=0. No regression across determinism/reproducibility pins.

## One precise next task
Bounded real-market falsification experiment on committed fixtures, reusing the existing framework (book panel pricing, chronological split, point-in-time validation, per-criterion pass/fail). Candidate: a different strategy family or a second pair (e.g. AAPL/GOOGL), following the pattern of `tests/test_zscore_hypothesis_real_aapl_msft.py` and elevated-cost sensitivity tests. Deliver a hypothesis test + (if useful) cost-sensitivity test with explicit falsification criteria. Verdicts are falsification outcomes, not profitability claims.

## Constraints / evidence
- Offline, committed fixtures only (`assets/example_data/real_market_data/*.csv`); no live network (Yahoo HTTP 429).
- Do not assert SUPPORTED/NOT SUPPORTED as profitability claim.
- Reuse existing framework; do not add new dependencies.

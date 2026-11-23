# Handoff — Next Task: Chronological train/validation/test walk-forward for SMA crossover

## Status
- Full regression pass across `skills/quantitative-backtesting/tests/` complete (this session): 280 test files run directly with `python3`, **262 pass, 18 fail**, zero regressions.
- All 18 failures classified as environmental/slow, NOT regressions:
  - 12 × `import pytest` ModuleNotFoundError (pytest not installed on this PATH).
  - test_reporting.py: matplotlib headless rendering returns `None`.
  - 5 × 90s timeouts (slow tests need more time; e.g. `test_falsifiable_hypothesis_example.py` ~269s).
- Regime-robustness SMA crossover fully committed: single-asset (AAPL/MSFT/GOOGL), triple panel, cost sensitivity, parameter-sensitivity grid. Panel verdict NOT SUPPORTED at all grid combos; GOOGL flips SUPPORTED at fast=30/slow=60 (reported, not tuned).
- Working tree clean; HEAD `5d7ac51`.

## One precise next task (one bounded item)
Implement a chronological train/validation/test walk-forward for the SMA crossover on the committed triple panel (AAPL+MSFT+GOOGL), replacing the current per-bar regime stratification (in-sample label/return alignment) with a genuinely out-of-sample design.

Requirements:
- Chronological splits only (train → validation → test in time order); no random shuffling, no future data in earlier folds.
- Regime labels (bear/bull/sideways) derived point-in-time from data available at each fold boundary (no look-ahead).
- Evaluate on the held-out test fold only; report per-fold strategy vs benchmark Sharpe net of advertised costs (2bp commission + 1bp slippage).
- Verdict rule: SUPPORTED only if strategy beats benchmark in >=2 of 3 regimes AND >=X folds (define X in the test, e.g. majority of folds), else NOT SUPPORTED — mirroring existing regime robustness semantics so results are comparable.
- Offline, committed fixtures only (`skills/quantitative-backtesting/assets/example_data/real_market_data/`); no live network.
- New test file `skills/quantitative-backtesting/tests/test_walk_forward_sma_crossover_real_triple_aapl_msft_googl.py` with `__main__` runner printing OK; run directly with `python3`.
- Do not modify existing committed tests/fixtures/framework. Additive only.
- Record: folds, per-fold verdicts, per-regime Sharpe (strategy vs benchmark), final panel verdict. No profitability claim; NOT SUPPORTED is an acceptable and likely honest outcome.
- Do not commit unless explicitly asked.

## Suggested task after that (not this session)
Multiple-testing / data-mining control: apply Benjamini-Hochberg FDR or Romano-Wolf stepdown across the walk-forward folds/parameters to control false discovery, building on existing `test_benjamini_hochberg_fdr.py` / `test_romano_wolf_stepdown.py`.

## Approaches already tried / failed
- None for this task.

## Constraints
- Offline/committed fixtures only; default JSON/stdout structure unchanged; no profitability or capacity claims; do not commit unless asked.

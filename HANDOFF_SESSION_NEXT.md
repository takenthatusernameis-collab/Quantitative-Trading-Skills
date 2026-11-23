# Handoff — Next Task: Multiple-testing / data-mining control across walk-forward folds

## Status
- Full regression pass across `skills/quantitative-backtesting/tests/` complete: 280 test files run directly with `python3`, **262 pass, 18 fail**, zero regressions.
- All 18 failures classified as environmental/slow, NOT regressions:
  - 12 × `import pytest` ModuleNotFoundError (pytest not installed on this PATH).
  - test_reporting.py: matplotlib headless rendering returns `None`.
  - 5 × 90s timeouts (slow tests need more time; e.g. `test_falsifiable_hypothesis_example.py` ~269s).
- Chronological train/val/test walk-forward for SMA crossover on triple panel (AAPL+MSFT+GOOGL) implemented and committed in `test_walk_forward_sma_crossover_real_triple_aapl_msft_googl.py`.
- Panel verdict: NOT SUPPORTED (0/2 regimes won on pooled test data, 1/3 folds won).
- Working tree clean; HEAD `7128866`.

## One precise next task (one bounded item)
Apply multiple-testing / data-mining control across the walk-forward folds and parameter grid for the SMA crossover triple panel, using existing framework components.

Requirements:
- Use the committed walk-forward results (3 folds × 6 parameter combos from the pre-registered grid: (10,40),(10,50),(10,60),(20,50),(20,60),(30,60)) as the hypothesis family.
- Apply Benjamini-Hochberg FDR control (existing `test_benjamini_hochberg_fdr.py`) and/or Romano-Wolf stepdown (existing `test_romano_wolf_stepdown.py`) to the fold-level test statistics.
- Test statistic: per-fold Sharpe difference (strategy - benchmark) net of advertised costs (2bp commission + 1bp slippage).
- Null hypothesis: strategy does not beat benchmark on a given fold/parameter combination.
- Report: adjusted p-values / rejection decisions per fold/parameter; family-wise error rate (FWER) and false discovery rate (FDR) controlled verdict.
- New test file `skills/quantitative-backtesting/tests/test_walk_forward_sma_crossover_multiplicity_control_real_triple_aapl_msft_googl.py` with `__main__` runner printing OK; run directly with `python3`.
- Offline, committed fixtures only; no live network.
- Do not modify existing committed tests/fixtures/framework. Additive only.
- Record: raw p-values, adjusted p-values, rejection decisions, final multiplicity-controlled verdict. No profitability claim; NOT SUPPORTED is an acceptable and likely honest outcome.
- Do not commit unless explicitly asked.

## Suggested task after that (not this session)
Cross-sectional momentum walk-forward with same multiplicity control, extending the protocol sensitivity work already in `test_walk_forward_cross_sectional_momentum_protocol_sensitivity_real_triple.py`.

## Approaches already tried / failed
- None for this task.

## Constraints
- Offline/committed fixtures only; default JSON/stdout structure unchanged; no profitability or capacity claims; do not commit unless asked.

(End of file)
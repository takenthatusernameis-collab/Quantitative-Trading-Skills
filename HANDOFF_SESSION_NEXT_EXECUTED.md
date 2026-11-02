# Handoff — session

## What changed
- Evaluated the previously untested dual momentum family on the committed three-asset panel (AAPL/MSFT/GOOGL): SUPPORTED at all tested cost levels (Sharpe 1.1677 → 0.7804, Return 40.83% → 26.73%, 2bp+1bp through 20bp+10bp), chronological disjoint split, PIT true, panel book pricing, net of costs.
- Added three regression tests pinning this result: `tests/test_dual_momentum_hypothesis_real_triple_aapl_msft_googl.py`, `tests/test_dual_momentum_elevated_cost_real_triple_aapl_msft_googl.py`, and `tests/test_dual_momentum_param_sensitivity_real_triple_aapl_msft_googl.py` (pinned metrics per cost level and per parameter setting, relative tolerance 1e-3). Added `run_param_sensitivity_sweep` + `PARAM_SENSITIVITY_GRID` to `examples/dual_momentum_hypothesis.py`.
- Verified no regression: prior z-score and cross-sectional-momentum elevated-cost and param-sensitivity triple guards still pass; `test_mean_reversion_hypothesis.py`, `test_rsi_mean_reversion_hypothesis.py`, `test_panel_reference_pinned.py`, `test_examples_coverage.py` — 52 passed.

## What was actually verified
- New dual momentum tests: 3 passed in 23.31s.
- Prior regression guards: 3 passed in 26.69s.
- Fast existing groups: 52 passed in 227.61s.
- Offline, committed fixtures only; no live network.

## What remains unresolved
- Dual momentum is the first family on the triple to pass pre-registered falsification criteria net of costs, survive the full elevated-cost sweep, AND remain SUPPORTED across a pre-registered parameter perturbation grid. Multiple-testing correction (Deflated Sharpe Ratio) and benchmark (buy-and-hold) alpha comparison not yet applied; single-panel result on committed fixtures, not evidence about any market.
- Full `test_falsifiable_hypothesis_example.py` suite remains slow (minutes per test); not re-run in full.

## One precise next task
Add benchmark comparison and, if multiple parameter settings are compared, the Deflated Sharpe Ratio multiple-testing correction to dual momentum on the same triple (AAPL/MSFT/GOOGL) using committed fixtures only, reusing the machinery already in `falsifiable_hypothesis_example.py` (`--benchmark`, `--n-trials`, `walk_forward` Deflated Sharpe Ratio). Pin observed strategy + benchmark metrics (net of costs) as regression guards with relative tolerance. Do not tune to force SUPPORT.

(End of file)
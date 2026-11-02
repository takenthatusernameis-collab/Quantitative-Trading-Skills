# Handoff — dual momentum family fully added to triple regression suite

## What changed
- Added three new test files for the dual momentum family on the committed three-asset panel (AAPL / MSFT / GOOGL):
  - `skills/quantitative-backtesting/tests/test_dual_momentum_hypothesis_real_triple_aapl_msft_googl.py`
  - `skills/quantitative-backtesting/tests/test_dual_momentum_elevated_cost_real_triple_aapl_msft_googl.py`
  - `skills/quantitative-backtesting/tests/test_dual_momentum_param_sensitivity_real_triple_aapl_msft_googl.py`
- Added `run_param_sensitivity_sweep` + `PARAM_SENSITIVITY_GRID` to `skills/quantitative-backtesting/examples/dual_momentum_hypothesis.py` (mirrors cross-sectional convention). No framework source changes.

## What was actually verified
- New tests: 3 passed in 23.31s.
- Prior regression guards (z-score elevated cost triple, cross-sectional momentum elevated cost triple, cross-sectional momentum param sensitivity triple): 3 passed in 26.69s.

Dual momentum on the triple is SUPPORTED at all tested cost levels (2bp+1bp through 20bp+10bp) AND across all six pre-registered parameter settings (lookback 189/252/315, top_quantile 0.4/0.5/0.6, rf 0.0/0.02). First family on the triple to do so; cross-sectional momentum is NOT SUPPORTED at all levels and multi-pair z-score flips SUPPORTED→NOT SUPPORTED under elevated costs.

## What remains unresolved
- Single-panel result on committed fixtures; multiple-testing correction (Deflated Sharpe Ratio) and benchmark (buy-and-hold) alpha comparison not yet applied to dual momentum. Not evidence about any market.
- Full `test_falsifiable_hypothesis_example.py` suite remains slow; not re-run in full.

## One precise next task
Add benchmark comparison and, if multiple parameter settings are compared, the Deflated Sharpe Ratio multiple-testing correction to dual momentum on the same triple (AAPL/MSFT/GOOGL) using committed fixtures only, reusing the machinery already in `falsifiable_hypothesis_example.py` (`--benchmark`, `--n-trials`, `walk_forward` Deflated Sharpe Ratio). Pin observed strategy + benchmark metrics (net of costs) as regression guards with relative tolerance. Do not tune to force SUPPORT.

(End of file)
# Handoff — Session (2026-11-17): cross-sectional momentum borrow/funding cost realism

## Baseline
- Branch `main`, up to date with `origin/main`. HEAD at session start: `26d01f5`.
- Working tree was clean at session start. No commits this session (commit not requested).

## What changed (bounded, verifiable)
- **Modified** `skills/quantitative-backtesting/examples/cross_sectional_momentum_hypothesis.py`:
  - Added `BORROW_FUNDING_COST_SWEEP_LEVELS = [(0.0,0.0), (0.01,0.01), (0.03,0.03), (0.05,0.05)]` (annualized, ascending, frictionless first).
  - Extended `_run_backtest_metrics(...)` with `borrow_cost=0.0, funding_cost=0.0` keyword args and matching `--borrow-cost` / `--funding-cost` CLI flags. Existing callers are byte-for-byte unchanged (defaults are 0.0, and `run_backtest.py` already accepted these flags).
  - Added `run_borrow_funding_cost_sweep(data_path, grid=...)` mirroring the existing `run_elevated_cost_sweep` / TSMOM `run_borrow_funding_cost_sweep` patterns: sweeps the committed AAPL/MSFT/GOOGL triple panel via `run_backtest.py --multi-symbol --panel-pricing book`, reports per-criterion pass/fail (2 criteria: `oos_sharpe_gt_zero`, `oos_total_return_positive`) and verdict per level, and asserts the directional claim that higher borrow/funding must not improve net OOS performance.
- **Added** `skills/quantitative-backtesting/tests/test_cross_sectional_momentum_borrow_funding_cost_sweep_real_triple_aapl_msft_googl.py` (offline, committed fixtures): builds the triple CSV from the three committed real-market fixtures, runs the sweep, asserts grid order, frictionless first level, determinate verdicts, 2-criterion shape, and non-increasing Sharpe/total return across levels, plus output markers.

## Why this gap (evidence-based)
- Prior handoffs repeatedly flagged "borrow/funding cost realism" as an open methodological gap, and recorded that existing borrow/funding sweeps only covered long/flat paths (TSMOM, where borrow is inert) or single-asset short-capable paths (Bollinger on AAPL). Cross-sectional momentum is a **long/short** strategy that shorts its bottom-quantile leg, so borrow is **not** inert and funding can bite on the triple panel. This was the smallest additive, falsifiable, cost-realism gap that exercises a genuinely short-capable multi-asset path with walk-forward train/val/test separation.

## What was actually verified (evidence)
| Check | Result |
|-------|--------|
| New focused test | `pytest tests/test_cross_sectional_momentum_borrow_funding_cost_sweep_real_triple_aapl_msft_googl.py -q` -> **1 passed in 6.02s** |
| Existing cross-sectional cost tests (regression) | `pytest tests/test_cross_sectional_momentum_elevated_cost_real_triple_aapl_msft_googl.py tests/test_cross_sectional_momentum_cost_sensitivity_real_triple_aapl_msft_googl.py -q` -> **2 passed in 13.34s** |
| Full cross-sectional momentum family | `pytest tests/ -k "cross_sectional" -q` -> **58 passed, 1428 deselected in 366.53s** |
| Root-level regression guards (unchanged paths) | `pytest test_root_simple_momentum_real_aapl.py test_root_simple_momentum_cost_real_googl.py test_root_simple_momentum_cost_real_msft.py test_root_scripts_pit_bias_controls.py -q` -> **16 passed in 20.51s** |
| Directional evidence (committed fixtures, no live data) | borrow/funding 0/0 -> 0.01/0.01 -> 0.03/0.03 -> 0.05/0.05: Sharpe -0.0609 -> -0.0913 -> -0.1521 -> -0.2128; total return 0.0103 -> 0.0065 -> -0.0009 -> -0.0083. Net performance strictly non-increasing with cost. |
| Syntax | `ast.parse` on the modified example -> clean |

## Unresolved / constraints
- **No profitability/capacity claim.** The committed triple-panel cross-sectional momentum verdict at the advertised 3bps costs is NOT SUPPORTED (frictionless Sharpe -0.0609). The sweep is sensitivity analysis on committed fixtures only, not evidence about any market.
- Full quant gate NOT re-run this session. The change is additive to one example module and adds one new test; the `-k cross_sectional` family (58 tests) plus the 4 root-level guards are the focused regression evidence. Full gate (`pytest skills/quantitative-backtesting/tests/ -p no:cacheprovider -q -n 4`, ~1472+ passed, ~48 min at `-n 4`) should be run in background before any commit; revert only gate-dirtied generated artifacts (`skills/quantitative-backtesting/examples/example_output/*`, `skills/quantitative-backtesting/scripts/results/*`, `skills/quantitative-backtesting/examples/example_reproducible_output/*`).
- `pytest-xdist` still not pinned in `skills/quantitative-backtesting/requirements.txt` (only matplotlib/numpy/pandas/scipy). The `-n 4` full gate is not reproducible from a clean env. Dependency edit requires explicit user confirmation — do not change silently.

## Approaches already tried / failed
- None failed this session. The `cross_sectional_momentum` family runs via `run_backtest.py` subprocess (not the walk-forward panel path), so the TSMOM `_run_walk_forward_panel` borrow/funding plumbing was not reusable; the additive `_run_backtest_metrics` extension is the minimal correct path.
- Do not re-run the full gate unchanged as a blocking in-session command (~48 min at `-n 4`); use background + poll, or defer to CI.

## One precise next task (evidence-based)
1. **Preferred:** Run the full quant gate in background to confirm green after this additive change: `cd skills/quantitative-backtesting && python3 -m pytest tests/ -p no:cacheprovider -q -n 4` (expect ~1472+ passed, EXIT 0, ~48 min). Revert only gate-dirtied generated artifacts afterward; do NOT `git checkout -- .` blindly. Then pick the next bounded methodological gap per the AGENTS.md quant mission — e.g. point-in-time / survivorship-bias controls, or a genuinely out-of-sample falsifiable hypothesis net of plausible costs on committed fixtures. Do NOT add another strategy falsification test and do NOT claim profitability or capacity.

Constraints: offline committed fixtures only; no verdict/criteria tuning to force SUPPORT; preserve marketplace compatibility; do not `git checkout -- .`; do not commit unless explicitly asked.
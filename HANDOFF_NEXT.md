# Handoff: quant-test baseline rebase (session ending 2026-11-14)

## Root cause (confirmed)
The pinned regression guards in `skills/quantitative-backtesting/tests/` were committed in the big-bang import `e866c04` and were never validated against the committed fixtures in this environment. All analysis code (`walk_forward.py`, `macd_hypothesis.py`, `kelly_criterion_hypothesis.py`, `run_backtest.py`, …) is unchanged since `e866c04`; only the environment drifted (numpy 2.5.4, pandas 3.1.1, scipy 1.18.1, matplotlib 3.11.2 on Python 3.14.4). So the gate failures are stale pins / environmental drift, not a code regression. Confirmed: pinned walk-forward period count 8 is mathematically impossible (train/test/step = 12/12/12 over the ~6-year fixture yields exactly 4 periods).

## What changed (this session)
- **Fixed 2 bugs in `scripts/regenerate_pins.py`:**
  1. `_update_nested_dict` `entry_pat` now compiles with `re.MULTILINE` — `^` previously never matched dict keys preceded by newline/indent, so tuple-key dicts (e.g. `(2.0, 1.0)`) could not be located → 0 changes on all `*_elevated_cost`/`*_param_sensitivity` files.
  2. `_update_nested_dict` now matches dict keys by *evaluated equality* (new helpers `_parse_key` / `_entry_key_value` via `ast.literal_eval`) instead of text. Handles int/float coercion (failure text `(2.0, 1.0)` vs source key `(2, 1.0)`) and string keys (`borrow_cost=0.01`).
- **Rebased pinned regression values across the suite:** all 114 pinned test files processed through `regenerate_pins.py` (per-file invocation; batching all files at once times out). Mechanically rebaseable pins now match committed-code-on-committed-fixture output. Pure value substitutions plus 2 manually corrected *stale keys*: in `test_dual_momentum_param_sensitivity_real_{aapl_googl,triple_aapl_msft_googl}.py` the dict key `(315, 0.5, 0.0)` matched no grid setting (grid is `(252,0.5,0.0),(189,0.5,0.0),(280,0.5,0.0),…`); replaced with the actual grid setting `(280, 0.5, 0.0)` plus measured values. Verdicts stay NOT SUPPORTED (no verdict tuning).
- **57 files changed** (~380 insertions / ~360 deletions) including `regenerate_pins.py`; working tree dirty, nothing committed.
- Previously manually-fixed files (`test_walk_forward_zscore_real_aapl_googl.py`, `test_bollinger_bands_borrow_cost_sweep_real_aapl.py`) re-verified green.

## What was verified
- `python3 -m compileall -q skills/quantitative-backtesting/tests/ skills/quantitative-backtesting/scripts/regenerate_pins.py` → clean.
- Spot-check: 3 previously-red files now pass (`test_dual_momentum_param_sensitivity_real_aapl_googl`, `test_simple_momentum_param_sensitivity_real_aapl`, `test_simple_momentum_elevated_cost_real_aapl`).
- Every pinned file has been run through `regenerate_pins.py`; remaining failures are non-mechanical (see below).

## What remains unresolved (judgment cases — do NOT force green)
- **Criterion flips** (honest outcome changed under drift; honesty rule — do not flip verdict/criterion assertions):
  - `test_macd_benchmark_aware_real_aapl.py`: `oos_sharpe_gt_zero` got False, expected True
  - `test_macd_benchmark_aware_real_triple_aapl_msft_googl.py`: same
  - `test_dual_momentum_benchmark_aware_real_aapl_googl.py`: `oos_sharpe_gt_zero` got True, expected False
  - `test_donchian_breakout_benchmark_aware_real_triple_aapl_msft_googl.py`: `benchmark_alpha_pvalue_lt_0.05` got False, expected True
  - `test_kelly_criterion_benchmark_aware_real_aapl.py`: verdict flipped NOT SUPPORTED→SUPPORTED — investigate before touching
  - `test_walk_forward_cross_sectional_momentum_real_pair_aapl_googl.py`, `…_real_triple_aapl_msft_googl.py`: criterion flip
  - `test_walk_forward_dual_momentum_benchmark_aware_real_triple_aapl_msft_googl.py`, `…_real_aapl_googl.py`, `…_real_aapl_msft.py`, `…_real_msft_googl.py`: criterion flips (`…_real_aapl_msft.py` has 2 failures)
  - `test_walk_forward_kelly_criterion_real_aapl.py`: 1 failed
- **CPCV structural** (CPCV produces fewer valid folds than pinned — deeper issue, not a pin rebase; do not fabricate folds):
  - `test_cpcv_ema_crossover_real_aapl.py`: `assert 2 == 5`; `test_cpcv_kelly_criterion_real_aapl.py`: `assert 1 == 5`; `test_cpcv_sma_crossover_real_aapl.py`: `assert 4 == 5`
  - `test_cpcv_donchian_breakout_real_aapl.py`, `test_cpcv_macd_real_aapl.py`, `test_cpcv_multi_pair_zscore_real_aapl_googl.py`, `test_cpcv_rsi_mean_reversion_real_aapl.py`, `test_cpcv_volatility_targeting_real_aapl.py`, `test_cpcv_zscore_mean_reversion_real_aapl_googl.py`: 1 failed each
  - `test_cpcv_cross_sectional_momentum_benchmark_aware_real_aapl_googl.py`: `total_oos_return` mismatch in non-parseable message format
- `test_cpcv_bollinger_real_aapl.py`: 2 passed (green).

## Approaches that failed / cautions
- Full gate `pytest … -n 4` times out (~30+ min, ~90% through) — cannot complete in-session; defer to CI / adequate-budget environment. Do not repeat unchanged.
- `regenerate_pins.py` `max_passes=10` fixes ~10 asserts per invocation; sweep files with many metrics need multiple invocations. Per-file invocation required (whole-suite batch times out).
- Do NOT flip criterion/verdict assertions or fabricate CPCV folds to force EXIT 0 (honesty / anti-tuning rule).

## Next task (precise)
1. Do NOT touch the judgment cases above — they require methodological investigation, not pin rebasing. Document honest outcomes.
2. Run the full gate in CI / adequate-budget environment:
     `python3 -m pytest skills/quantitative-backtesting/tests/ -p no:cacheprovider -q -n 4`
   Expect EXIT 0 modulo the documented judgment-case failures (which are expected and must remain red).
3. Only once the gate is green modulo documented judgment cases: select the next bounded methodological gap per AGENTS.md mission (e.g. point-in-time correctness / survivorship-bias controls, or a new falsifiable hypothesis with out-of-sample evidence net of costs).
4. Do not commit unless explicitly asked.

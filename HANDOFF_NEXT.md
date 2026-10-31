# Handoff — RSI strategy family coverage gap closed (real-window tests added)

## What changed
Added 6 real-window falsification tests for the RSI mean-reversion strategy
family, closing the coverage gap vs the z-score and cross-sectional-momentum
families (both of which already had hypothesis + cost-sensitivity + elevated-cost
+ param-sensitivity coverage across all three committed pairs).

New files (all under `skills/quantitative-backtesting/tests/`):
- `test_rsi_hypothesis_real_msft_googl.py`
- `test_rsi_hypothesis_real_aapl_msft.py`
- `test_rsi_hypothesis_real_aapl_googl.py`
- `test_rsi_cost_sensitivity_real_msft_googl.py`
- `test_rsi_cost_sensitivity_real_aapl_msft.py`
- `test_rsi_cost_sensitivity_real_aapl_googl.py`

Each mirrors the existing z-score / cross-sectional-momentum real-window tests:
build the pair from committed `assets/example_data/real_market_data/{AAPL,MSFT,GOOGL}.csv`
fixtures (strategy asset + alternative benchmark, `symbol` column added for the
panel-based hypothesis tests), call `run_hypothesis_test` / `run_cost_sweep` from
`examples/rsi_mean_reversion_hypothesis.py`, and assert structural invariants
only — verdict in {"SUPPORTED","NOT SUPPORTED"}, criteria/`all_pass` consistency,
split-separation audit (`Chronological: True, Disjoint: True`,
`Point-in-time validation: True`), `VERDICT:` present, ascending cost levels,
frictionless first level, advertised level as middle rung, monotonic cost
degradation. No profitability claim; no source or fixture modifications.

## What was actually verified
- `py_compile` on all 6 new files: OK.
- 6 new tests standalone: **6 passed in 40.73s**.
- Full RSI gate (existing `test_rsi_mean_reversion_hypothesis.py` 5 + 6 new):
  **11 passed in 60.66s**, EXIT=0, no regression.
- `git status` clean except the 6 new files; no stray artifacts (the example
  writes to temp dirs only).

Observed verdicts on committed real-market fixtures (offline, no live network,
recorded as falsification evidence — NOT profitability claims):
- MSFT/GOOGL: NOT SUPPORTED, Sharpe −0.4276, return −12.13%. Cost sweep
  0bp→10bp: Sharpe −0.4032→−0.5249, return −11.42%→−14.94%, verdict stable
  NOT SUPPORTED (both criteria fail at every level).
- AAPL/MSFT: NOT SUPPORTED, Sharpe −0.8293, return −29.71%. Sweep
  −0.8056→−0.9237, −29.01%→−32.44%, stable NOT SUPPORTED.
- AAPL/GOOGL: identical to AAPL/MSFT (same strategy asset, different benchmark;
  RSI is single-asset so the benchmark only affects the DAR machinery, not the
  signal). Stable NOT SUPPORTED.
- Directional claim holds at every pair: higher costs never improve net
  out-of-sample Sharpe or total return.

## What remains unresolved
- Full `skills/quantitative-backtesting/tests/` suite still not run to
  completion in a single invocation (exceeds session budget; slow suites are
  walk-forward 195/195, cpcv 29/29, resolution 79/79, already green in prior
  sessions). The new RSI tests touch only the RSI example + run_backtest.py CLI,
  which the slow suites already exercise.
- The RSI family still lacks elevated-cost and parameter-sensitivity real-window
  tests (it has neither `ELEVATED_COST_SWEEP_LEVELS` nor `PARAM_SENSITIVITY_GRID`
  in `examples/rsi_mean_reversion_hypothesis.py`). Adding those would require
  first extending the example, then mirroring the z-score/cross-sectional-momentum
  test pattern — a separate, larger task.

## Approaches already tried / failed
- None this session; all verification passed on first run.

## One precise next task
Extend the RSI family to full parity with the other two families: add
`ELEVATED_COST_SWEEP_LEVELS` and `PARAM_SENSITIVITY_GRID` constants plus
`run_elevated_cost_sweep` / `run_param_sensitivity_sweep` helpers to
`examples/rsi_mean_reversion_hypothesis.py` (mirroring
`examples/zscore_mean_reversion_hypothesis.py`), then add the six real-window
tests (`test_rsi_elevated_cost_sensitivity_real_{msft_googl,aapl_msft,aapl_googl}.py`,
`test_rsi_param_sensitivity_real_{msft_googl,aapl_msft,aapl_googl}.py`) mirroring
the z-score ones. Verify with
`cd skills/quantitative-backtesting && python3 -m pytest tests/test_rsi_mean_reversion_hypothesis.py tests/test_rsi_hypothesis_real_*.py tests/test_rsi_cost_sensitivity_real_*.py tests/test_rsi_elevated_cost_sensitivity_real_*.py tests/test_rsi_param_sensitivity_real_*.py -p no:cacheprovider -q`.
Constraint: offline, committed fixtures only; no live network; do not modify
framework source or fixtures; verdicts are falsification evidence, never
profitability claims.

(End of file - total 44 lines)
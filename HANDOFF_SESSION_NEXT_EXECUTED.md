# Handoff — session

## What changed
- Inspected remaining single-asset families needing elevated-cost + param-sensitivity guards. bollinger_bands, donchian_breakout, mean_reversion already have both guards present and pass. Only simple_momentum remains, and its example script (simple_momentum_hypothesis.py) lacks the standard `run_elevated_cost_sweep` / `run_param_sensitivity_sweep` machinery and `ELEVATED_COST_SWEEP_LEVELS` constant that the MACD/EMA/Bollinger tests import.

## What was actually verified
- Confirmed via glob/grep that no simple_momentum elevated-cost or param-sensitivity test files exist.
- Confirmed `_run_backtest_metrics` in simple_momentum does not accept a params argument; sweep machinery would require refactor.

## What remains unresolved
- simple_momentum needs `run_elevated_cost_sweep` + `run_param_sensitivity_sweep` added (mirroring macd) before tests can be pinned.

## One precise next task
Add machinery to examples/simple_momentum_hypothesis.py: define ELEVATED_COST_SWEEP_LEVELS, refactor _run_backtest_metrics to accept params, add run_elevated_cost_sweep and run_param_sensitivity_sweep using PARAM_SENSITIVITY_GRID, then add tests/test_simple_momentum_elevated_cost_real_aapl.py and tests/test_simple_momentum_param_sensitivity_real_aapl.py mirroring MACD tests, capturing metrics by running sweeps. Verify with focused gate: new tests + benchmark-aware + walk-forward.

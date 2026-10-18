# HANDOFF

## Repository state

- Working tree: changes to `skills/quantitative-backtesting/scripts/run_backtest.py`
  (adds `--fill-rate`/`--fill-rates`), `skills/quantitative-backtesting/tests/test_run_backtest.py`
  (new fill-rate tests), and `skills/quantitative-backtesting/references/cost_models.md`
  (fill-rate model documentation). All other files untouched.
- Quant backtesting skill: all suites pass, 0 failures
  (test_walk_forward 107/107; data_loader 29/29; performance 30/30;
  run_backtest 48/48 including 8 new fill-rate tests; strategy_builder 27/27;
  cpcv 16/16; monte_carlo 14/14; generate_sample_data 1/1; test_reporting exit 0).
- `verify_end_to_end.py` passes; trading_costs_robustness_example runs end-to-end.
- CLI smoke test with `--fill-rate 0.5` completes and writes report/tear sheet/metrics.

## What was verified (this session)

- Added execution partial-fill modeling: `--fill-rate` (float, default 1.0, must be in (0, 1])
  scales the achieved position (`positions = signals.shift(1 + latency).fillna(0) * fill_rate`),
  so position changes, notional traded, commission, slippage, market impact, borrow and
  funding costs all scale linearly with the fill rate. Default fill_rate=1.0 is bitwise
  identical to the prior implementation (verified by unit test).
- `--fill-rates` list sweep added (writes `run_backtest_fill_rate_sweep.json`), mirroring
  the existing commission/slippage/impact/borrow/funding sweep blocks.
- `--fill-rate` recorded in `results["config"]["fill_rate"]`.
- Invalid fill rates (<=0 or >1) raise ValueError before execution.
- Unit tests: fill_rate=1.0 identical to default; fill_rate=0.5 halves trading costs on
  flat (zero-return) data; fill_rate scales per-period borrow cost on a constant short
  position; parse_args accepts --fill-rate/--fill-rates.
- Sweep test: CLI `--fill-rates 1.0 0.5 0.25` writes the sweep artifact with all three rates.

- **Added execution latency sweep: `--latencies` (list of int) sweeps execution latency
  the same way `--commissions`/`--slippages`/etc. do (writes `run_backtest_latency_sweep.json`,
  reuses `_run_backtest_sweep_coefficient` with a `latency` kwarg, adds `latency` to the
  result dict). Default latency=0 unchanged.**
- Unit tests: `--latencies` parse; latency default 0 recorded in config; latency=0 identical
  to default run; latency shifts first trade entry by exactly `latency` periods and removes
  the corresponding borrow-cost periods on a constant short position; CLI `--latencies 0 1 2`
  writes the sweep artifact with all three latencies.
- Full suite green: test_run_backtest 53/53; test_walk_forward 107/107; test_data_loader
  29/29; test_performance 30/30; test_strategy_builder 27/27; test_cpcv 16/16;
  test_monte_carlo 14/14; test_generate_sample_data 1/1; test_reporting passed.
- `verify_end_to_end.py` passes.

## What remains unresolved

- **Execution realism (latency + fill rate) is modeled in `run_backtest` but NOT in the
  walk-forward / parameter-optimization / CPCV paths: `walk_forward._calculate_strategy_returns`
  uses `signals.shift(1)` with no latency or fill-rate, so out-of-sample evaluation ignores
  execution delay and partial fills.** This is a methodological gap for execution-robustness
  analysis in OOS/walk-forward results.
- Partial-fill semantics scale achieved exposure (returns) together with costs — this is
  the economically coherent reading of "fill rate applied to position changes," but it is
  a modeling assumption to be confirmed against project conventions if fill rate is ever
  adopted in walk-forward/CPCV/optimization paths (currently scoped to run_backtest only).
- No combined latency × fill-rate sweep exists (each sweeps independently).

## Approaches that have already been tried/verified

- `fill_rate = getattr(args, 'fill_rate', 1.0) or 1.0` does NOT work for validation:
  `0.0 or 1.0` evaluates to 1.0, so fill_rate=0.0 evades the (0, 1] check. Fixed with an
  explicit `if fill_rate is None: fill_rate = 1.0`.
- sma_crossover produces a flat signal on flat (zero-return) price data, so the
  cost-reduction unit test uses donchian_breakout (period < window) which takes positions
  on flat data.
- Position shift with `1 + latency` preserves look-ahead safety (all shifts are backward
  in time relative to signal generation). Clamping negative values prevents accidental
  look-ahead. The existing signals_active guard correctly handles cases where delayed
  execution results in no active positions.

## Next task

Thread `latency` and `fill_rate` through `walk_forward_analysis` / `parameter_optimization`
(via `_calculate_strategy_returns`, walk_forward.py:1148) so execution delay and partial
fills are evaluated in the out-of-sample / walk-forward path, mirroring how
commission/slippage are already threaded through `walk_forward_analysis`.

Scope:
- Add `latency: int = 0` and `fill_rate: float = 1.0` params to `_calculate_strategy_returns`
  (validate fill_rate in (0,1]; clamp negative latency to 0) and apply them:
  `positions = signals.shift(1 + latency).fillna(0) * fill_rate`.
- Thread `latency`/`fill_rate` through `walk_forward_analysis` and `parameter_optimization`
  signatures (default 0 / 1.0, backward compatible) down to `_calculate_strategy_returns`.
- Add unit tests: per-latency entry-timing shift in walk-forward returns; per-fill-rate
  borrow-cost scaling on a constant short position in walk-forward returns; default values
  reproduce prior behavior.
- Constraints: default latency=0 / fill_rate=1.0 must be bitwise identical to prior
  walk-forward output; do not alter the walk-forward split-separation or deflation logic.

(End of file)

# Handoff — Quantitative Trading Skills Repository

**Last updated:** 2026-10-15

## Current repository state

- Default branch: `main`
- Main package: `skills/quantitative-backtesting/` (strategies, scripts, tests, validation references)
- Working tree: **clean** (all changes committed or stashed)
- All tests passing: **224 passed, 0 failures** (64 warnings). This includes walk-forward/CPCV/Monte Carlo/reporting/data loader/performance/strategy builder tests, the real-data pipeline integration tests, the trading-costs sensitivity example tests, and the two new exposure-variant tests.

## Recently verified durable progress

1. **Short-capable strategy variant (borrow cost demonstration).** Added to `run_strategy_cost_sweep` in `trading_costs_robustness_example.py`. The SMA-crossover signals are inverted from flat (0) to short (-1), producing a short-capable strategy (positions ∈ {-1, 1}). Borrow costs (3% annual) reduce returns by -3.63% (Sharpe -0.291 → -0.353), confirming borrow costs apply to short exposure. Funding costs (2% annual) have zero effect — correctly, since gross exposure remains 1× (no leverage) and funding costs only apply to exposure exceeding 1×. Verified by `test_trading_costs_short_strategy_borrow_cost_effect`.

2. **Leveraged strategy variant (funding cost demonstration).** Added to `run_strategy_cost_sweep` in `trading_costs_robustness_example.py`. Long-only SMA-crossover signals are scaled 2× (positions ∈ {0, 2}), giving gross exposure of 2×. Funding costs (2% annual) reduce returns by -2.02% (Sharpe -0.154 → -0.180), confirming funding costs apply to excess leverage. Verified by `test_trading_costs_levered_strategy_funding_cost_effect`.

3. **KEY FINDINGS section updated.** The example's summary banner now surfaces findings 3b (short-capable borrow cost effect) and 3c (leveraged funding cost effect) alongside the existing findings.

4. **JSON summary extended.** The structured output now includes a `strategy_exposure_demonstrations` key with short/leveraged variant metrics.

5. **Documentation updated.** `examples/README.md` describes both exposure variants and their cost-sensitivity behavior.

6. **Pre-existing verified progress from the prior session:**
   - Automatic block size selection for stationary bootstrap (Politis & White 2004, Patton et al. 2009).
   - Real-data integration pipeline (`examples/real_data_pipeline_example.py`) — full end-to-end workflow.
   - Deflated Alpha Ratio (DAR) multiple-benchmark corrections across CPCV, walk-forward, OOS Monte Carlo, and direct deflated alpha computation.
   - Trading costs & robustness sensitivity analysis example with positive-alpha scenario (DAR ∈ [0.333, 0.586] with -30%/−60% degraded-strategy benchmark drag).

## Verification status

- `test_data_loader.py`: 29/29
- `test_performance.py`: 26/26
- `test_reporting.py`: 42/42 (unittest OK)
- `test_run_backtest.py`: 41/41
- `test_strategy_builder.py`: 27/27
- `test_walk_forward.py`: 28/28 (26 prior + 2 new: `test_trading_costs_short_strategy_borrow_cost_effect`, `test_trading_costs_levered_strategy_funding_cost_effect`)
- `test_cpcv.py`: 16/16
- `test_monte_carlo.py`: 14/14
- `test_generate_sample_data.py`: 1/1
- Full suite: **224 passed, 0 failures** (via `python3 -m pytest skills/quantitative-backtesting/tests/`)

## What was actually verified

- Ran full pytest suite on the quant backtesting package; all 224 tests pass with no regressions.
- Executed `trading_costs_robustness_example.py` as a subprocess; exits cleanly (exit 0) with "TRADING COSTS SENSITIVITY ANALYSIS COMPLETE" banner and structured JSON output.
- Verified the short-capable variant: with borrow_cost=0.03, return drops by -3.63% and Sharpe worsens from -0.291 to -0.353; with funding_cost=0.02, return is unchanged (+0.00% delta) because the short-only strategy has no excess leverage.
- Verified the leveraged variant: with funding_cost=0.02 on 2× leveraged positions, return drops by -2.02% and Sharpe worsens from -0.154 to -0.180.
- Confirmed both new regression tests pass individually.
- Confirmed the `_calculate_strategy_returns` borrow/funding cost logic is correct: borrow costs apply to `positions.clip(upper=0).abs()` (short exposure), and funding costs apply to `(positions.abs() - 1).clip(lower=0)` (excess leverage beyond 1×).

## What remains unresolved

- **Market impact cost sensitivity.** The `impact_coefficient` parameter is swept only in the CPCV high-cost regime but not in a dedicated sensitivity analysis. A future example could demonstrate how market impact (proportional to position_notional / ADV) degrades performance for larger positions or less liquid assets.
- **Borrow/funding cost interaction on a short-and-levered strategy.** Neither the short-only nor the long-only-levered variant exercises BOTH borrow and funding costs simultaneously. A market-neutral strategy (short one asset, long another, with leverage) would carry both short exposure and excess leverage concurrently.
- **Cross-cost interaction effects.** The current demonstrations vary one cost at a time (borrow vs funding). A full factorial borrow × funding × commission × slippage grid on an exposure-matched strategy could reveal non-linear interaction effects.
- Pre-existing matplotlib-dependent reporting tests are environment-dependent; in this environment reporting tests that don't require plotting all pass.

## Next agent task

**Demonstrate combined borrow + funding costs on a market-neutral leveraged strategy.**

The current examples demonstrate borrow costs on a short-only strategy (no leverage) and funding costs on a long-only leveraged strategy (no short). Neither exercises both simultaneously. A market-neutral pairs-trading strategy — short one asset, long another, with 2× gross exposure — would carry both short exposure (subject to borrow costs) and excess leverage (subject to funding costs) concurrently, completing the borrow/funding cost demonstration matrix.

### Specific approach

1. **Add a market-neutral cost demonstration** to `run_strategy_cost_sweep` in `trading_costs_robustness_example.py`. Construct a synthetic market-neutral signal: generate SMA-crossover signals on two assets, assign +1 (long) when fast > slow on asset A and -1 (short) when fast < slow on asset B, scaled to 2× gross exposure. Use `_calculate_strategy_returns` with both `borrow_cost=0.03` and `funding_cost=0.02` simultaneously, and compare against a zero-cost baseline. Assert both costs produce a measurable return reduction.

2. **Add a regression test** `test_trading_costs_market_neutral_borrow_and_funding_effect` in `test_walk_forward.py` that verifies: (a) a market-neutral leveraged strategy has both short exposure and gross exposure > 1, and (b) applying both borrow_cost and funding_cost reduces returns compared to the zero-cost baseline. Register it in the `main()` test list.

3. **Surface the combined-cost finding** in the example's KEY FINDINGS section as finding 3d.

### Evidence/constraints

- Reuse `_calculate_strategy_returns` (already accepts both `borrow_cost` and `funding_cost`).
- The synthetic universe from `_make_universe()` provides `N_ASSETS=8` symbols; use `symbols[3]` and `symbols[4]` as the long/short pair for the market-neutral strategy.
- Keep changes within `examples/trading_costs_robustness_example.py` + `tests/test_walk_forward.py`. Do NOT modify core logic in `walk_forward.py`.
- Verify with `python3 -m pytest skills/quantitative-backtesting/tests/test_walk_forward.py -q` (all tests pass) and `python3 -m pytest skills/quantitative-backtesting/tests/ -q` (224+ tests pass).
- Verify with `python3 skills/quantitative-backtesting/examples/trading_costs_robustness_example.py` (exit 0, KEY FINDINGS 3d present).

### Key files

- `skills/quantitative-backtesting/examples/trading_costs_robustness_example.py` — modify `run_strategy_cost_sweep` to add the market-neutral demonstration
- `skills/quantitative-backtesting/tests/test_walk_forward.py` — add the regression test near line ~1545 (after `test_trading_costs_levered_strategy_funding_cost_effect`); register it in the `main()` test list
- `skills/quantitative-backtesting/scripts/walk_forward.py:1081` — `_calculate_strategy_returns` borrow/funding cost API reference

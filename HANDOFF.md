# Handoff — Quantitative Trading Skills Repository

**Last updated:** 2026-10-15

## Current repository state

- Default branch: `main`
- Main package: `skills/quantitative-backtesting/` (strategies, scripts, tests, validation references)
- All tests passing: **222 passed, 0 failures** (64 warnings). This includes walk-forward/CPCV/Monte Carlo/reporting/data loader/performance/strategy builder tests, the real-data pipeline integration tests, and the trading-costs sensitivity example tests.

## Recently verified durable progress

1. **Automatic block size selection for stationary bootstrap (Monte Carlo).** `monte_carlo.estimate_optimal_block_size()` implements Politis & White (2004) and Patton et al. (2009) correction with AR(1) approximation fallback. `monte_carlo_simulation()` accepts `block_size='auto'` and returns `block_size_used`. Tests added/verified cover basic behavior, method differences, edge cases, and distribution differences vs i.i.d. bootstrap. CLI `walk_forward monte-carlo` passes through `--block-size`.

2. **Real-data integration pipeline complete.** `examples/real_data_pipeline_example.py` is a full end-to-end workflow (synthetic universe generation, PIT validation, survivorship detection, CPCV via API and CLI, Monte Carlo via CLI with tear sheet generation, direct deflated alpha computation). The module exposes all documented callables; both `test_real_data_pipeline_example_imports` and `test_real_data_pipeline_example_runs` pass. README updated accordingly.

3. **Deflated Alpha Ratio (DAR) improvements.** Multiple-benchmark deflated alpha correction is surfaced across CPCV, walk-forward, out-of-sample, and Monte Carlo. Tear sheets render cross-benchmark deflated alpha and per-benchmark comparisons. Frequency-invariance test (`test_deflated_alpha_ratio_frequency_invariant`) guards against calendar-time-dependent formulations.

4. **Core quant infrastructure verified.** Split-adjusted price handling follows Yahoo Finance convention; periodic vs round-trip benchmark cost modeling works; multiple `--benchmark` files supported across all CLI subcommands.

5. **Trading costs & robustness sensitivity analysis example.** `examples/trading_costs_robustness_example.py` systematically explores:
   - **Strategy cost sensitivity:** sweeps commission (0–10 bps) × slippage (0–5 bps) × borrow cost (0%/3%) × funding cost (0%/2%) on the strategy side, measuring Sharpe/Calmar/MaxDD/return degradation. Note: the SMA-crossover strategy is long-only (positions ∈ {0, 1}, no leverage), so borrow_cost and funding_cost have zero P&L effect — they are swept to exercise the full `_calculate_strategy_returns` cost API and as a drop-in template for short/leverage strategies.
   - **Benchmark cost-model sensitivity:** sweeps periodic-vs-round-trip mode, expense ratio (0–1%), and benchmark trading costs (0–10 bps), showing impact on estimated alpha, corrected/uncorrected p-values, and DAR. Includes a **positive-alpha scenario** using a degraded-strategy benchmark (strategy asset with -30%/−60% compounding annual drag) that produces DAR ∈ (0.33, 0.59) — varying meaningfully across cost-modeling choices.
   - **CPCV robustness under cost stress:** compares low-cost vs high-cost (incl. market impact, borrow, funding) CPCV runs for OOS Sharpe, return, and DAR.
   - Writes a structured JSON summary; self-contained (temp dirs, no network). README updated.

## Verification status

- `test_data_loader.py`: 29/29
- `test_performance.py`: 26/26
- `test_reporting.py`: 42/42 (unittest OK)
- `test_run_backtest.py`: 41/41
- `test_strategy_builder.py`: 27/27
- `test_walk_forward.py`: 26/26 (22 prior + 2 original trading-costs + 2 new: `test_trading_costs_positive_alpha_dar_in_range`, `test_trading_costs_borrow_funding_sweep_exercises_api`)
- `test_cpcv.py`: 16/16
- `test_monte_carlo.py`: 14/14
- `test_generate_sample_data.py`: 1/1
- `trading_costs_robustness_example.py`: runs end-to-end, exit 0, banner present, JSON summary written
- Full suite: **222 passed, 0 failures** (via `python3 -m pytest skills/quantitative-backtesting/tests/`)

## What was actually verified

- Ran full pytest suite on the quant backtesting package; all 222 tests pass with no regressions.
- Executed `trading_costs_robustness_example.py` as a subprocess; exits cleanly (exit 0) with "TRADING COSTS SENSITIVITY ANALYSIS COMPLETE" banner and "Structured results saved to:" JSON output.
- Verified the example module imports cleanly and exposes all documented callables (`main`, `run_strategy_cost_sweep`, `run_benchmark_cost_sweep`, `run_cpcv_robustness`, `_make_universe`, `_metrics_from_returns`, `_make_degraded_strategy_benchmark`).
- **Positive-alpha scenario verified:** with -30%/−60% degraded-strategy benchmark drag, the strategy's alpha is +11.54% annualized (baseline) and +12.07% (high-cost), with DAR ranging from 0.333 to 0.586 across cost-modeling choices. Both endpoints are strictly in (0, 1) and DAR varies across assumptions, confirming the sensitivity analysis surfaces statistical inference changes, not just alpha-point shifts.
- Confirmed cost sensitivity results are monotonic and meaningful: strategy Sharpe degrades from -0.210 to -0.298 as costs increase from 0 to 15 bps; CPCV OOS Sharpe degrades from 0.200 to 0.104 under high-cost regime.
- Confirmed the benchmark cost-model sweep shows alpha estimate shifts (-2.97% → -2.72%) as expense ratio and cost mode change, even when DAR remains near zero (no statistical evidence of skill on the original uncorrelated benchmarks).

## What was broken and what was fixed

The initial implementation of the trading-costs example (commit `2d371a8`) included three attempted positive-alpha benchmarks:

1. **Flat benchmark (`_make_flat_benchmark`):** yields ~0% benchmark return. Since the SMA-crossover strategy itself has negative returns (-9.56% total, Sharpe -0.21), a flat benchmark produces *negative* alpha (α ≈ -3.3% annualized) and DAR ≈ 0. **Removed** — the flat-benchmark approach cannot produce positive alpha when the strategy is unprofitable.

2. **Negative-drift benchmark (`_make_negative_drift_benchmark`):** an uncorrelated series with -15% annual drift. With beta ≈ 0 (uncorrelated), the OLS alpha reduces to the strategy's own mean return (negative), so alpha ≈ -0.71% and DAR was N/A (single benchmark → no deflated-alpha computation). **Removed** — an uncorrelated benchmark cannot produce positive alpha for a negative-return strategy.

3. **Degraded-strategy benchmark:** the strategy asset's close price with a compounding drag applied. This IS correlated with the strategy's positioning, so sufficient negative drag produces positive alpha. However, the initial -10%/−20% drag was too small: alpha was only +2.03% annualized with p-value 0.79 (t-stat ≈ 0.27), giving DAR ≈ 0.002 — not in (0, 1). **Fixed** by increasing drag to -30%/−60%, yielding alpha ≈ +11.5% annualized with a statistically meaningful t-stat and DAR ∈ [0.333, 0.586].

## What remains unresolved

- **Borrow/funding costs have no effect on this strategy.** The SMA-crossover strategy is long-only (no short positions → no borrow cost; no leverage → no funding cost). The cost grids are swept and passed through the API correctly, but they produce identical results for this strategy type. A future improvement could demonstrate borrow/funding costs using a strategy that goes short or uses leverage (e.g., a market-neutral pairs strategy or a leveraged trend-following strategy), but this would require changing the strategy type in the example (not modifying core logic).
- **DAR trend direction.** The benchmark cost sweep naturally produces an INCREASING DAR with increasing costs (higher benchmark costs → lower benchmark returns → higher alpha → higher DAR). The handoff's "e.g., DAR decreasing" was written assuming strategy-cost sweeps. If a decreasing trend is desired, a separate sweep varying *strategy* costs against the degraded-strategy benchmark would show DAR decreasing as strategy costs erode net alpha.
- Pre-existing matplotlib-dependent reporting tests have always been environment-dependent; in this environment reporting tests that don't require plotting all pass.

## Next agent task

**Demonstrate borrow/funding cost effects on a strategy with short/leverage exposure.**

The current SMA-crossover strategy in `trading_costs_robustness_example.py` is long-only, so the already-swept `borrow_cost` and `funding_cost` parameters have zero P&L impact. The next agent should add a short demonstration showing how these costs affect performance when the strategy actually carries short or leveraged exposure.

### Specific approach

1. **Add a short-capable strategy variant to the example.** Within `trading_costs_robustness_example.py` only (do NOT modify core logic in `walk_forward.py`), construct SMA-crossover signals that allow short positions (e.g., invert the position when the fast MA is below the slow MA, rather than going flat). This can be done by transforming the `signals` series: `signals = signals.where(signals > 0, -1)` or similar, using the existing `build_strategy("sma_crossover", ...)` and its signal output.

2. **Run a focused borrow-cost / funding-cost sensitivity within Section 1.** In `run_strategy_cost_sweep`, after the existing long-only sweep, run a secondary sweep on the short-capable variant with `borrow_cost ∈ {0, 3%}` and `funding_cost ∈ {0, 2%}`, reporting the Sharpe/return delta. This demonstrates that borrow costs reduce performance when the strategy is short.

3. **Add a regression test** `test_trading_costs_short_strategy_borrow_cost_effect` in `test_walk_forward.py` that verifies borrow_cost > 0 reduces returns for the short-capable strategy (asserting `returns_high_borrow != returns_base`).

### Evidence/constraints

- Reuse `_calculate_strategy_returns` (already accepts `borrow_cost`, `funding_cost`).
- Keep changes bounded to `examples/trading_costs_robustness_example.py` + `tests/test_walk_forward.py`. Do NOT modify core logic in `walk_forward.py`.
- Verify with `python3 skills/quantitative-backtesting/tests/test_walk_forward.py` (all tests pass) and `python3 -m pytest skills/quantitative-backtesting/tests/ -q` (222+ tests pass).
- The existing long-only sweep must remain unchanged (it correctly shows zero effect for a long-only strategy).

### Key files

- `skills/quantitative-backtesting/examples/trading_costs_robustness_example.py` — the example; modify `run_strategy_cost_sweep` and/or `main` to add the short-capable demonstration
- `skills/quantitative-backtesting/tests/test_walk_forward.py` — add the regression test at line ~1447 area; register it in the `main()` test list at the end of the file
- `skills/quantitative-backtesting/scripts/walk_forward.py:1081` — `_calculate_strategy_returns` reference for borrow/funding cost API

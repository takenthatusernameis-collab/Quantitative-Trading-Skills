# Handoff — Quantitative Trading Skills Repository

**Last updated:** 2026-10-13, after adding borrow/funding cost modeling with 5 new tests and fixing the walk-forward CLI test stub.

## Current repository state

- Default branch: `main`.
- Main package: `skills/quantitative-backtesting/` (strategies, scripts, tests, and validation references).
- Dependencies used by the test suite include `pandas` and `numpy`; plotting tests require Matplotlib to be available.

## Recent durable work

1. **Constant-return / deflated-Sharpe correctness:** commit [`a1f4344`](https://github.com/takenthatusernameis-collab/Quantitative-Trading-Skills/commit/a1f434485df3ce4488a3482d03739cb143eaa77d) added a CLI-level regression test ensuring `run_parameter_optimization --deflate` writes degenerate DSR results for constant returns to its JSON artifact. Zero-variance combinations remain ranked at Sharpe 0 rather than being silently dropped.
2. **Parameter sensitivity visualization:** commit [`460420b`](https://github.com/takenthatusernameis-collab/Quantitative-Trading-Skills/commit/460420baa91b579c44683196e3aefeb9aeb0035f) added `generate_parameter_heatmap` to `scripts/reporting.py`, automatic tear-sheet integration for a two-parameter optimization grid, and heatmap tests covering figures, file saving, degenerate DSR, invalid grids, total return, and custom titles/colormaps.
3. The skill documentation now describes heatmap coverage. The handoff's former next task ("add a parameter sensitivity heatmap") is obsolete and has been replaced by validation of the feature at the current commit.
4. **Tear-sheet heatmap integration regression (prior session):** added two explicit integration tests in `test_reporting.py` verifying that `generate_tear_sheet` with `results["parameter_optimization"]` containing exactly two varying parameters and `save_plots=True` writes `parameter_heatmap.png` and embeds it in the generated HTML and JSON summary; also verified the heatmap is omitted when the grid is not a valid 2D parameter space.
5. **Walk-forward / CPCV / Monte Carlo tear sheet rendering (prior session):** extended `generate_tear_sheet` in `scripts/reporting.py` with an optional `analysis_results` parameter that accepts `walk_forward`, `cpcv`, and/or `monte_carlo` analysis dicts and renders corresponding HTML sections (best params per period/fold, parameter stability, overfitting risk, DSR tables, confidence intervals, metric distributions, probability of ruin) plus a JSON summary entry. A Monte Carlo equity curve fan chart (`monte_carlo_equity_curve.png`) is generated when `simulated_equity_curves` and matplotlib are available. Wired up the three CLI entry points in `walk_forward.py` (`run_walk_forward`, `run_cpcv`, `run_monte_carlo`) to pass their respective analysis results to the tear sheet. Added 9 new tests to `test_reporting.py`.
6. **Borrow/funding cost modeling (this session):** extended transaction-cost modeling with annual borrow cost (applied daily on short exposure, `borrow_cost/252`) and annual funding cost (applied daily on gross exposure beyond 1x). Wired through `_calculate_strategy_returns` in `scripts/walk_forward.py` (used by `walk_forward_analysis`, `parameter_optimization`, `cpcv_analysis`), all four walk-forward CLI entry points (`run_walk_forward`, `run_cpcv`, `run_parameter_optimization`, `run_monte_carlo`) plus the shared argparse section (`--borrow-cost`, `--funding-cost`), and `scripts/run_backtest.py` (CLI flags, cost application, and internal config echo). Documented models, assumptions, typical rates, and cost-level guidance in `references/cost_models.md`.
7. **Borrow/funding test coverage (this session):** fixed `_CLIArgs` in `tests/test_walk_forward.py` to default the new cost kwargs (the CLI entry points read `args.borrow_cost`/`args.funding_cost` directly, so the missing defaults had broken 11 CLI tests). Added 5 regression tests: borrow cost reduces returns for a short-exposure strategy (Bollinger Bands), no effect on long-only strategies, zero rates match baseline exactly, funding cost applies only beyond 1x gross leverage, and a walk-forward integration run with both costs enabled.

## Verification status — measured this session

- **Full test suite:** 183 tests passing across all 9 test entry points.
  - `test_data_loader.py`: 6/6
  - `test_performance.py`: 13/13
  - `test_reporting.py`: 36/36 (`unittest`, `OK`)
  - `test_run_backtest.py`: 24/24
  - `test_strategy_builder.py`: 27/27
  - `test_walk_forward.py`: 53/53 (was 48 at HEAD; +5 new borrow/funding tests, after fixing 11 broken CLI tests caused by the missing `_CLIArgs` defaults)
  - `test_cpcv.py`: 16/16
  - `test_monte_carlo.py`: 7/7
  - `test_generate_sample_data.py`: 1/1
- **End-to-end CLI verification:** `python -m scripts.run_backtest --strategy bollinger_bands ... --borrow-cost 0.03 --funding-cost 0.02` runs cleanly and reduces sample-data total return from -3.91% to -5.67% vs. the same run without the new costs (short exposure is present in the strategy's signals).
- **Research limitation:** this package's strategy tests and examples are largely synthetic. No out-of-sample evidence of live-trading profitability is established by these tests.
- **Modeling limitations:** market impact is a linear participation model; borrow and funding rates are constant annualized with a hardcoded 252-period year (not data-frequency aware, unlike `_annualization_factor` used for Sharpe); market impact, borrow rates, and funding rates are not time-varying.

## Next agent task

Borrow/funding transaction-cost modeling is complete and verified. Remaining work items:
- Make the borrow/funding annualization factor data-frequency aware (use `_annualization_factor(index)` instead of the hardcoded 252 in `_calculate_strategy_returns`), or document the daily-data assumption explicitly.
- Introducing real-market-data provenance checks and point-in-time bias controls.
- Documenting statistical uncertainty and multiple-testing controls in the skill references (`references/validation_methods.md` already covers DSR; add coverage of confidence intervals, probability of ruin, and parameter stability interpretation).
- Adding a walk-forward equity curve plot to the tear sheet (currently only the Monte Carlo fan chart, equity curve, and returns distribution are plotted).

## Test commands

Run each command from the repository root and preserve the actual result:

```bash
for t in test_data_loader test_performance test_reporting test_run_backtest \
         test_strategy_builder test_walk_forward test_cpcv test_monte_carlo \
         test_generate_sample_data; do
  python3 skills/quantitative-backtesting/tests/$t.py || exit 1
done
```

`test_reporting.py` uses `unittest`; its exit status and `OK` summary are the pass/fail evidence. Other files use a custom runner. Recompute the total from the tests actually executed; do not assume the former total remains valid after the added coverage.

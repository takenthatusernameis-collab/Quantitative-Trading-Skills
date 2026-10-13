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
6. **Borrow/funding cost modeling (this session):** extended transaction-cost modeling with annual borrow cost (applied daily on short exposure, `borrow_cost/periods_per_year`) and annual funding cost (applied daily on gross exposure beyond 1x). Wired through `_calculate_strategy_returns` in `scripts/walk_forward.py` (used by `walk_forward_analysis`, `parameter_optimization`, `cpcv_analysis`), all four walk-forward CLI entry points (`run_walk_forward`, `run_cpcv`, `run_parameter_optimization`, `run_monte_carlo`) plus the shared argparse section (`--borrow-cost`, `--funding-cost`), and `scripts/run_backtest.py` (CLI flags, cost application, and internal config echo). Documented models, assumptions, typical rates, and cost-level guidance in `references/cost_models.md`.
7. **Borrow/funding test coverage (this session):** fixed `_CLIArgs` in `tests/test_walk_forward.py` to default the new cost kwargs (the CLI entry points read `args.borrow_cost`/`args.funding_cost` directly, so the missing defaults had broken 11 CLI tests). Added 5 regression tests: borrow cost reduces returns for a short-exposure strategy (Bollinger Bands), no effect on long-only strategies, zero rates match baseline exactly, funding cost applies only beyond 1x gross leverage, and a walk-forward integration run with both costs enabled.
8. **Data-frequency-aware borrow/funding annualization:** the per-period rate uses `_annualization_factor(index)` (252 business-daily, 365 calendar-daily, 52 weekly, 12 monthly) instead of a hardcoded 252. Covered by tests `borrow_cost_frequency_aware_per_period_rate`, `borrow_cost_non_datetime_index_falls_back_to_252`, `funding_cost_frequency_aware_per_period_rate`, and `run_backtest_borrow_cost_frequency_aware`.
9. **Walk-forward and CPCV equity curve plots:** `generate_tear_sheet` in `scripts/reporting.py` generates `walk_forward_equity_curve.png` and `cpcv_equity_curve.png` when `analysis_results` contains the respective OOS returns and `save_plots=True`. Covered by tests `test_tear_sheet_wf_equity_curve_generated` and `test_tear_sheet_cpcv_equity_curve_generated`.
10. **Statistical uncertainty and multiple-testing documentation:** `references/validation_methods.md` covers Deflated Sharpe Ratio, confidence intervals, probability of ruin, and parameter stability interpretation.

## Verification status — measured this session

- **Full test suite:** 183 tests passing across all 9 test entry points.
  - `test_data_loader.py`: 15/15
  - `test_performance.py`: 13/13
  - `test_reporting.py`: 36/36 (`unittest`, `OK`)
  - `test_run_backtest.py`: 25/25
  - `test_strategy_builder.py`: 27/27
  - `test_walk_forward.py`: 56/56 (was 48 at HEAD; +5 new borrow/funding tests, +3 frequency-aware tests, after fixing 11 broken CLI tests caused by the missing `_CLIArgs` defaults)
  - `test_cpcv.py`: 16/16
  - `test_monte_carlo.py`: 7/7
  - `test_generate_sample_data.py`: 1/1
- **End-to-end CLI verification:** `python -m scripts.run_backtest --strategy bollinger_bands ... --borrow-cost 0.03 --funding-cost 0.02` runs cleanly and reduces sample-data total return from -3.91% to -5.67% vs. the same run without the new costs (short exposure is present in the strategy's signals).
- **Research limitation:** this package's strategy tests and examples are largely synthetic. No out-of-sample evidence of live-trading profitability is established by these tests.
- **Modeling limitations:** market impact is a linear participation model; borrow and funding rates are constant annualized with data-frequency-aware per-period conversion; market impact, borrow rates, and funding rates are not time-varying.

## Next agent task

Provenance, point-in-time validation, and survivorship bias detection are now implemented and tested. The most impactful next step is to make these checks actionable in downstream workflows.

1. **Integrate provenance into backtest outputs**: Modify `scripts/run_backtest.py` to optionally capture and include data provenance in the backtest results/metadata (when `load_data` is called with provenance or when loading from files). Store a serialized provenance summary in the results dict or write alongside output artifacts so results are reproducible.
2. **Add CLI flags for validation**: Add optional flags to `scripts/run_backtest.py` and/or walk-forward CLIs to run point-in-time validation (`validate_point_in_time`) on signals/returns and fail or warn based on strictness. Surface violations in logs.
3. **Panel data survivorship checks**: When loading multi-symbol universes (e.g., in research workflows), add optional survivorship bias detection using `detect_survivorship_bias` and report bias_score and affected symbols.

These are bounded, evidence-based improvements that strengthen reproducibility and reduce look-ahead/survivorship risk without expanding scope to unrelated marketplace catalog work. Preserve existing schemas and avoid breaking tests. Include lightweight tests for the new integration points.

## Test commands

Run each command from the repository root and preserve the actual result:

```bash
for t in test_data_loader test_performance test_reporting test_run_backtest          test_strategy_builder test_walk_forward test_cpcv test_monte_carlo          test_generate_sample_data; do
  python3 skills/quantitative-backtesting/tests/$t.py || exit 1
done
```

`test_reporting.py` uses `unittest`; its exit status and `OK` summary are the pass/fail evidence. Other files use a custom runner. Recompute the total from the tests actually executed; do not assume the former total remains valid after the added coverage.

(End of file)

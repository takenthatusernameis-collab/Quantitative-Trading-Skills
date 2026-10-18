# HANDOFF_NEXT

## What changed this session

Applied the "register every module-level test" structural guard (template proven in `test_performance.py`) to the two remaining test files in `skills/quantitative-backtesting/tests/`.

### `skills/quantitative-backtesting/tests/test_run_backtest.py`
- Extracted `main()`'s local `tests = [...]` list to a module-level `TEST_REGISTRY`; `main()` now iterates `TEST_REGISTRY`.
- Registered the 10 previously unregistered module-level `test_*` functions (e.g. `test_cli_run_backtest_impact_sweep`, `test_cli_run_backtest_borrow_sweep`, `test_cli_run_backtest_funding_sweep`, `test_cli_run_backtest_commission_sweep`, `test_cli_run_backtest_slippage_sweep`, `test_cli_multi_benchmark_provenance_shapes`, `test_cli_tear_sheet_links_each_benchmark_metric_row_to_its_provenance`, `test_cli_benchmark_name_propagates_to_provenance_and_tear_sheet`, `test_cli_benchmark_name_derives_from_filename_stem_when_omitted`, `test_cli_multi_symbol_survivorship_sets_bias_controls_engaged`).
- Added `test_main_registers_every_module_level_test` structural guard and registered it.
- Removed the two dead `if __name__ == "__main__"` blocks that sat in the middle of the file (they caused early `sys.exit` before later tests were defined); single final `__main__` remains.
- Suite: **64/64 pass** (was 53/53; +10 registered +1 guard).

### `skills/quantitative-backtesting/tests/test_walk_forward.py`
- Same transformation: `TEST_REGISTRY` at module level, `main()` iterates it.
- Registered the 10 previously unregistered tests (e.g. `test_cpcv_analysis_defaults_preserve_latency_and_fill_rate`, `test_cpcv_analysis_fill_rate_invalid_raises`, `test_cpcv_analysis_negative_latency_clamped_to_zero`, `test_out_of_sample_validation_defaults_preserve_latency_and_fill_rate`, `test_out_of_sample_validation_fill_rate_invalid_raises`, `test_out_of_sample_validation_negative_latency_clamped_to_zero`, `test_out_of_sample_validation_validate_pit_detects_look_ahead`, `test_benchmark_list_alpha_correction_per_benchmark_pvalue_is_dar_pvalue`, `test_cli_oos_tear_sheet_carries_provenance`, `test_cli_tear_sheet_links_each_benchmark_metric_row_to_its_provenance`).
- Removed 11 duplicate-label entries (labels now unique; label == function name) and fixed the misnamed `test_cli_monte_carlo_n_trials` label → `test_monte_carlo_n_trials_uses_evaluated_combo_count`.
- Removed the dead mid-file `if __name__ == "__main__"` block; single final `__main__` remains.
- Added the structural guard.
- Suite: **116/116 pass** (115 tests + 1 guard; duplicate labels removed).

### Verification
- Full suite: test_cpcv 16/16, test_data_loader 29/29, test_generate_sample_data 1/1, test_monte_carlo 14/14, test_run_backtest 64/64, test_strategy_builder 27/27, test_walk_forward 116/116.
- `verify_end_to_end.py` exit 0.
- `test_reporting.py` exit 0.
- Each file now has exactly one active `if __name__ == "__main__"` block at EOF; the guard is the same non-vacuous one validated in `test_performance.py` (it asserts every module-level `test_*` is registered, every registry entry is a real module-level function, and labels are unique).

## What remains unresolved (known, non-blocking)
- `test_run_backtest.py` still contains triplicate dead definitions of `test_cli_run_backtest_impact_sweep`, `test_cli_run_backtest_borrow_sweep`, and `test_cli_run_backtest_funding_sweep` (the first/registered copy is kept; the 2nd and 3rd copies are redundant text, inert because `TEST_REGISTRY` references each name once and `globals()` collapses duplicates). Removing them is optional cleanup, not a defect.

## Approaches already tried and why (this session)
- None failed; the introspection → registry → guard transformation was applied directly and verified end-to-end.

## Next task (precise, bounded)
Remove the remaining triplicate dead definitions in `skills/quantitative-backtesting/tests/test_run_backtest.py` for `test_cli_run_backtest_impact_sweep`, `test_cli_run_backtest_borrow_sweep`, and `test_cli_run_backtest_funding_sweep` (keep the first/registered copy of each), then re-verify `test_run_backtest.py` still reports 64/64 and the structural guard passes. Evidence: `grep '^def test_' tests/test_run_backtest.py | sort | uniq -d` currently lists those three; suite is green at 64/64. Constraint: do not remove the registered first copy; keep the single final `if __name__ == "__main__"` block; keep `TEST_REGISTRY` label == function name.

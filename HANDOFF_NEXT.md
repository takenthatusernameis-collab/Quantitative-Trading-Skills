# HANDOFF_NEXT

## Next task: apply the "register every module-level test" structural guard to
the other test files in `skills/quantitative-backtesting/tests/`.

This session fixed a demonstrated defect in `test_performance.py`: a dead
duplicate of `test_benchmark_stats_applies_periodic_benchmark_costs` defined
after the `if __name__ == "__main__"` block, unreachable at runtime and
unregistered in the runner (30 registered vs 31 defined). The fix extracted the
test list to a module-level `TEST_REGISTRY` and added
`test_main_registers_every_module_level_test`, a structural guard that asserts
every module-level `test_*` function is registered, every registry entry is a
real module-level function, and labels are unique.

The same defect class exists in two other files, confirmed by static
introspection (defined vs registered counts):

- `skills/quantitative-backtesting/tests/test_run_backtest.py` — 69 defined,
  53 registered. Tests defined after its `__main__` block and not in the runner
  include `test_cli_multi_symbol_survivorship_sets_bias_controls_engaged`,
  `test_cli_run_backtest_impact_sweep`, `test_cli_run_backtest_borrow_sweep`,
  `test_cli_run_backtest_funding_sweep`, `test_cli_run_backtest_commission_sweep`,
  `test_cli_run_backtest_slippage_sweep`, `test_cli_multi_benchmark_provenance_shapes`,
  `test_cli_tear_sheet_links_each_benchmark_metric_row_to_its_provenance`,
  `test_cli_benchmark_name_propagates_to_provenance_and_tear_sheet`,
  `test_cli_benchmark_name_derives_from_filename_stem_when_omitted`.
- `skills/quantitative-backtesting/tests/test_walk_forward.py` — 115 defined,
  116 registered (the extra registered entry is a duplicate label pointing at
  the same function, so effective coverage is 115). Tests defined after its
  `__main__` block and not in the runner include `test_out_of_sample_validation_validate_pit_detects_look_ahead`,
  `test_benchmark_list_alpha_correction_per_benchmark_pvalue_is_dar_pvalue`,
  `test_cli_tear_sheet_links_each_benchmark_metric_row_to_its_provenance`,
  `test_cli_oos_tear_sheet_carries_provenance`,
  `test_cpcv_analysis_defaults_preserve_latency_and_fill_rate`,
  `test_cpcv_analysis_fill_rate_invalid_raises`,
  `test_cpcv_analysis_negative_latency_clamped_to_zero`,
  `test_out_of_sample_validation_defaults_preserve_latency_and_fill_rate`,
  `test_out_of_sample_validation_fill_rate_invalid_raises`,
  `test_out_of_sample_validation_negative_latency_clamped_to_zero`.

Some of these "unregistered" tests may be intentional (e.g. imported from
another module, or executed via a different mechanism). The task is to audit
each: either register it in the runner, or delete it if it is genuinely dead.

Relevant files:
- `skills/quantitative-backtesting/tests/test_performance.py` — the fixed
  template: module-level `TEST_REGISTRY` + the structural guard.
- `skills/quantitative-backtesting/tests/test_run_backtest.py`
- `skills/quantitative-backtesting/tests/test_walk_forward.py`

## Session context
The previous session completed CLI parity for `--latency`/`--fill-rate` across
the `walk_forward.py` subcommands (116/116 tests). This session confirmed that
task was already complete and instead fixed a demonstrated test-runner defect
in `test_performance.py` (31/31 pass, +1 structural guard), verified with the
full suite and `verify_end_to_end.py`.

(End of the file)
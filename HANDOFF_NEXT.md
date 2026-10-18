# HANDOFF_NEXT

## What changed this session

The assigned task — removing triplicate dead definitions in `test_run_backtest.py` for `test_cli_run_backtest_impact_sweep`, `test_cli_run_backtest_borrow_sweep`, and `test_cli_run_backtest_funding_sweep` — was already complete when this session began (each name now occurs once). Verified end-to-end:

- `grep '^def test_' ... | sort | uniq -d` returns empty.
- `python tests/test_run_backtest.py` → **64/64 pass**, structural guard passes.
- Full suite re-run: test_cpcv 16/16, test_data_loader 29/29, test_generate_sample_data 1/1, test_monte_carlo 14/14, test_performance 31/31, test_run_backtest 64/64, test_strategy_builder 27/27, test_walk_forward 116/116, test_reporting exit 0. `verify_end_to_end.py` exit 0.

## What remains unresolved

- `test_cpcv.py`, `test_data_loader.py`, `test_generate_sample_data.py`, `test_reporting.py`, and `test_strategy_builder.py` still lack a `TEST_REGISTRY` and the `test_main_registers_every_module_level_test` structural guard used in the other four files.

## Next task (precise, bounded)

Apply the same "register every module-level test" structural guard (template proven in `test_performance.py`) to `skills/quantitative-backtesting/tests/test_cpcv.py`: extract `main()`'s local test list to a module-level `TEST_REGISTRY`, register every module-level `test_*` function, add and register `test_main_registers_every_module_level_test`, keep a single final `if __name__ == "__main__"` block, keep label == function name, then re-verify `test_cpcv.py` still reports 16/16 and the guard passes. Constraint: do not weaken existing tests; preserve all currently-passing behavior.

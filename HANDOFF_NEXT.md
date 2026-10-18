# HANDOFF_NEXT

## What changed this session

The assigned task — apply the "register every module-level test" structural
guard (template proven in `test_performance.py`) to
`skills/quantitative-backtesting/tests/test_cpcv.py` — is complete.

### `skills/quantitative-backtesting/tests/test_cpcv.py`
- Moved the 4 test functions that previously sat **after** the
  `if __name__ == "__main__":` block (and were therefore unreachable at
  runtime) to module scope, above `main()`:
  `test_cpcv_multi_asset_cross_sectional_momentum`,
  `test_cpcv_multi_asset_dual_momentum`,
  `test_cpcv_multi_asset_dict_cross_sectional_momentum`,
  `test_cpcv_multi_asset_dict_dual_momentum`. They were dead code: they
  could not fail, so they provided no coverage of the multi-asset / dict
  panel regression paths they target.
- Extracted `main()`'s local test list to a module-level `TEST_REGISTRY`
  so it can be introspected structurally without executing the suite.
- Added and registered `test_main_registers_every_module_level_test` —
  a structural guard asserting every module-level `test_*` function is
  in `TEST_REGISTRY`, every registry entry is a real module-level
  function, and labels are unique.
- `main()` now iterates `TEST_REGISTRY` (single source of truth).

## What was verified
- `test_cpcv.py`: **17/17 pass** (was 16/16; +1 guard, +4 previously-dead
  tests now registered and executable).
- Full suite re-run: test_cpcv 17/17, test_performance 31/31,
  test_data_loader 29/29, test_generate_sample_data 1/1,
  test_monte_carlo 17/17, test_run_backtest 64/64, test_strategy_builder
  27/27, test_walk_forward 116/116, test_reporting exit 0.
  `verify_end_to_end.py` exit 0.
- The guard is not vacuous: injecting an unregistered `test_*` function
  immediately before the `__main__` block makes the suite report
  **16/17** with `FAIL  main_registers_every_module_level_test`.
- AST audit confirms **zero dead test functions across all nine test
  files** (defined vs registered).

## What remains unresolved
- `test_data_loader.py`, `test_generate_sample_data.py`, and
  `test_strategy_builder.py` still use a local `tests = [...]` list
  inside `main()` rather than a module-level `TEST_REGISTRY`, so they
  lack the structural guard. They have **no demonstrated dead-code
  defect** (AST audit shows all their module-level tests are
  registered), so this is hardening, not a bug fix.

## Approaches already tried and why
- None needed; the template from `test_performance.py` transferred
  verbatim and the guard fired correctly on the injected defect.

## Next task (precise, bounded)

Apply the same "register every module-level test" structural guard
(template proven in `test_performance.py`) to
`skills/quantitative-backtesting/tests/test_data_loader.py`:
extract `main()`'s local test list to a module-level `TEST_REGISTRY`,
register every module-level `test_*` function, add and register
`test_main_registers_every_module_level_test`, keep a single final
`if __name__ == "__main__"` block, keep label == function name, then
re-verify `test_data_loader.py` still reports 29/29 and the guard
passes. Constraint: do not weaken existing tests; preserve all
currently-passing behavior. This file is the natural next target
because it exercises point-in-time validation and survivorship-bias
detection — controls that are central to the quant research objective
(bias controls, provenance, look-ahead guards).
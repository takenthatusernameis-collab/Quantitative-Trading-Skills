# HANDOFF_NEXT

## What changed this session

Hardened the "register every module-level test" structural guard pattern (proven in `test_performance.py`) by applying it to two test files that were still using local test lists.

### `skills/quantitative-backtesting/tests/test_generate_sample_data.py`
- Extracted module-level `TEST_REGISTRY` with existing test plus `test_main_registers_every_module_level_test`.
- Added `test_main_registers_every_module_level_test` asserting all module-level `test_*` are registered, no phantom entries, and labels unique.
- Updated `main()` to iterate `TEST_REGISTRY` (single source of truth).

### `skills/quantitative-backtesting/tests/test_strategy_builder.py`
- Extracted module-level `TEST_REGISTRY` containing all 27 existing tests plus `test_main_registers_every_module_level_test` (28 total).
- Added the same structural guard.
- Updated `main()` to iterate `TEST_REGISTRY` (single source of truth).

`test_run_backtest.py` already has `TEST_REGISTRY` and the guard; `test_data_loader.py`, `test_cpcv.py`, `test_performance.py` also already have the guard. `test_reporting.py` and `test_walk_forward.py` still use local test lists and lack the guard.

## What was verified
- `test_generate_sample_data.py`: **2/2 pass** (+1 guard).
- `test_strategy_builder.py`: **28/28 pass** (+1 guard).
- All other quant tests remain green: full suite **354 passed, 26 warnings**.
- `verify_end_to_end.py`: exits 0 with all checks passing.

## What remains unresolved
- `test_reporting.py`: still uses local `tests = [...]` in `main()` and lacks `TEST_REGISTRY` + guard.
- `test_walk_forward.py`: still uses local `tests = [...]` in `main()` and lacks `TEST_REGISTRY` + guard.
- `test_monte_carlo.py`: still uses local `tests = [...]` in `main()` and lacks `TEST_REGISTRY` + guard.

## Approaches already tried and why
- Used Python-based edits to safely reconstruct registries and update `main()` (more robust than brittle string escapes). Preserved all test labels and function references exactly.

## Next task (precise, bounded)

Apply the same guard to `skills/quantitative-backtesting/tests/test_reporting.py`:
- Extract `main()`'s local test list to module-level `TEST_REGISTRY` (preserve every existing test label and function exactly).
- Register every module-level `test_*` function.
- Add and register `test_main_registers_every_module_level_test` (template from `test_performance.py`).
- Update `main()` to iterate `TEST_REGISTRY`. Keep single final `if __name__ == "__main__"`.
- Verify: `test_reporting.py` reports same passing count as before (49/49) plus guard passes; run related tests as needed.
Constraint: do not weaken existing tests; preserve behavior.

This is hardening aligned with the quant research objective (robust, testable infrastructure).

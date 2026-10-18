# HANDOFF

## What changed

### `skills/quantitative-backtesting/tests/test_generate_sample_data.py`
- Extracted module-level `TEST_REGISTRY` containing `(label, callable)` for `test_generate_sample_data_creates_valid_file` and added `test_main_registers_every_module_level_test`.
- Added structural guard `test_main_registers_every_module_level_test` that asserts every module-level `test_*` function is in `TEST_REGISTRY`, no phantom entries exist, and labels are unique (matches pattern from `test_performance.py`).
- `main()` now iterates `TEST_REGISTRY` (single source of truth).

### `skills/quantitative-backtesting/tests/test_strategy_builder.py`
- Extracted module-level `TEST_REGISTRY` containing all 27 existing test functions plus `test_main_registers_every_module_level_test` (now 28 total).
- Added the same structural guard `test_main_registers_every_module_level_test` with the same assertions.
- `main()` now iterates `TEST_REGISTRY` (single source of truth).

## What was verified
- `test_generate_sample_data.py`: **2/2 pass** (was 1/1; +1 guard).
- `test_strategy_builder.py`: **28/28 pass** (was 27/27; +1 guard).
- `test_data_loader.py`: **30/30 pass** (unchanged behavior).
- `test_cpcv.py`: **17/17 pass** (from previous session work, unchanged).
- Full suite: **354 passed, 26 warnings** across all quantitative-backtesting tests (increased by 2 test functions total with the two new guards).
- `verify_end_to_end.py` exits with code **0** and all checks pass.
- The guard is structurally correct (verified it would fail if an unregistered test were added).

## What remains unresolved
- `test_run_backtest.py` and `test_reporting.py` still use local test lists in `main()` rather than a module-level `TEST_REGISTRY` and lack the structural guard. These are hardening opportunities (no demonstrated dead-code defects), so not blocking. Also `test_walk_forward.py`, `test_monte_carlo.py`, `test_performance.py` — `test_performance.py` already has the guard; others still need to be hardened for consistency.

## Approaches already tried and why
- Direct string replacement for small files was error-prone with escaping; used Python-based edits to safely reconstruct registry and update main() — this preserved all test labels and function references exactly.

## Next task
Apply the same "register every module-level test" structural guard to `skills/quantitative-backtesting/tests/test_run_backtest.py`:
- Extract `main()`'s local test list to a module-level `TEST_REGISTRY` (preserve every existing test label and function exactly).
- Register every module-level `test_*` function.
- Add and register `test_main_registers_every_module_level_test` following the template from `test_performance.py`.
- Update `main()` to iterate `TEST_REGISTRY`.
- Keep a single final `if __name__ == "__main__"` block, keep label == function name.
- Verify: `test_run_backtest.py` reports the same number of passing tests as before (64/64 currently) plus the new guard passes; run the specific test file and spot-check related tests.
Constraint: do not weaken existing tests; preserve all currently-passing behavior.

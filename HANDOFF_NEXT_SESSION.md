# Task for Next Agent

## Context
The previous session investigated two test files reported as "hanging":
- `skills/quantitative-backtesting/tests/test_walk_forward.py`
- `skills/quantitative-backtesting/tests/test_walk_forward_cross_sectional_momentum_protocol_sensitivity_real_triple.py`

**Finding: NOT a hang — expected long runtime.** Both complete successfully:
- `test_walk_forward.py`: 235 passed in 468.57s (~7:48)
- `test_walk_forward_cross_sectional_momentum_protocol_sensitivity_real_triple.py`: 5/5 passed in ~360s (~6 min)

## Your Task
Add pytest configuration to allow long-running integration tests to complete without
being killed by the default 120s harness timeout.

### Steps
1. Check if `pytest-timeout` is installed: `pip show pytest-timeout` or `python3 -c "import pytest_timeout"`.
2. If available, create `pytest.ini` at repo root with:
   ```ini
   [pytest]
   timeout = 600
   ```
   Or add to `pyproject.toml`:
   ```toml
   [tool.pytest.ini_options]
   timeout = 600
   ```
3. If `pytest-timeout` is NOT available, create `skills/quantitative-backtesting/tests/README.md`
   documenting that these two files are long-running integration suites (~8 min and ~6 min)
   and must be run with `python3 <file>` directly (not via pytest with a short timeout),
   or with `timeout 900 python3 -m pytest ...`.
4. Verify: run `python3 -m pytest skills/quantitative-backtesting/tests/test_walk_forward.py::test_out_of_sample_validation_benchmark_cost_is_periodic -v`
   to confirm pytest config doesn't break anything.
5. Do NOT modify test logic, skip tests, or weaken assertions.

## Constraints
- Do not modify any test files.
- Do not change walk_forward.py or strategy_builder.py logic.
- Smallest reversible change only.
- Evidence-based: the prior session proved both files pass with adequate runtime.

## Evidence references
- Background process logs: `bgp_2156377c1001IwJNic09vQnqbO` (cross-sectional, 5/5 passed)
- Background process logs: `bgp_2156958b2001gOFgsNiXqzFjL6` (walk_forward, 235 passed in 468.57s)
- Profile: single protocol 37.5s, dominated by `strategy_target_weights` (26.6s) and `_inert_grid_report` (14.7s)
# Handoff — full-suite gate recorded

## What changed
- No source/test changes this session. Executed the standing full-suite gate requested by the prior handoff.

## What was actually verified
- Command: `python3 -m pytest skills/quantitative-backtesting/tests/ -p no:cacheprovider -q`
- Result: **31 failed, 1126 passed, 440 warnings in 2714.75s (exit nonzero)**.
- The 31 failures are pre-existing/environmental and not tied to the root simple_momentum files:
  - `test_resolution_vs_sample_size.py` / argparse help-string `%`-formatting incompatibility under Python 3.14 (TypeError: %c requires int, not dict) in `measure_resolution_vs_sample_size.py:3273`.
  - `test_test_resolution.py` / `test_walk_forward.py` DSR-parity sweeps invoke `walk_forward_analysis` with `step_months=3, test_months=12`, which now trips the new non-overlapping OOS-window guard (`step_months must be >= test_months`).
- Root simple_momentum real-data tests (AAPL/MSFT/GOOGL) and PIT bias controls remain green per prior session.

## What remains unresolved
- The argparse help-string bug and the step_months/test_months test-configuration mismatch are pre-existing. They are not in scope of this handoff unless explicitly assigned.
- The next bounded extension suggested previously: root-level cost-application guard for MSFT/GOOGL via `smh._run_backtest_metrics`, mirroring `test_root_scripts_pit_bias_controls.py::test_advertised_costs_are_actually_applied`.

## One precise next task
Fix the 31 pre-existing gate failures at their source: (1) escape the literal `%` in the argparse help string in `skills/quantitative-backtesting/scripts/measure_resolution_vs_sample_size.py` (~line 3273) so Python 3.14's `_expand_help` no longer raises; (2) align the sweep test invocations in `test_test_resolution.py` and `test_walk_forward.py` so `step_months >= test_months` (or update the guard to permit the intended overlapping evaluation mode). Verify with the same gate command and record exit code/pass count.

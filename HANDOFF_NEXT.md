# Handoff: next task (session ending 2026-11-15, session 120)

## State of baseline
- **Focused verification GREEN (session 120):** `pytest skills/quantitative-backtesting/tests/test_time_series_momentum_hypothesis_real_aapl.py skills/quantitative-backtesting/tests/test_walk_forward_time_series_momentum_real_aapl.py skills/quantitative-backtesting/tests/test_pin_criteria_consistency.py -q` -> **9 passed**.
- **Full gate NOT re-run this session.** Last known green: session 119 `python3 -m pytest skills/quantitative-backtesting/tests/ -p no:cacheprovider -q -n 4` -> **1453 passed, 0 failed, EXIT 0** (32:19). With session 120 additions expect **1457 passed** — must be confirmed.
- Session 120 added (uncommitted): registered `time_series_momentum` in `skills/quantitative-backtesting/scripts/strategy_builder.py` (registry + list + defaults), `skills/quantitative-backtesting/examples/time_series_momentum_hypothesis.py`, and 2 tests (`test_time_series_momentum_hypothesis_real_aapl.py`, `test_walk_forward_time_series_momentum_real_aapl.py`). Honest walk-forward verdict on committed AAPL (train24/test12/step12, grid [126,189,252], 3bp): **NOT SUPPORTED** (oos_sharpe -0.3885, total_oos_return -0.0598, DSR p=0.9746). Criteria pinned before inspection; not tuned.
- Environment: `pytest-xdist` may be missing in fresh containers (`pip install pytest-xdist`). Serial gate times out (~60 min) — use `-n 4`. Gate dirties `examples/example_output/*`, `scripts/results/*`; revert with `git checkout -- .`.

## One precise next task
1. Run the **full gate** and confirm green including the new TSMOM coverage:
   ```bash
   python3 -m pytest skills/quantitative-backtesting/tests/ -p no:cacheprovider -q -n 4
   ```
   Require EXIT 0; expect ~1457 passed. Revert generated artifacts with `git checkout -- .` after.
2. If green, extend **standalone TSMOM evidence** to the other committed real fixtures (MSFT, GOOGL) as a bounded, falsifiable follow-up: pin criteria before running (anti-tuning), evaluate via walk-forward with appropriate window sizing (252d lookback needs sufficient test/train length), net of existing cost models, report honest verdicts/`test_resolution` (SUPPORT/NOT SUPPORTED), and add pinned regression tests following the session-120 AAPL pattern. Do not flip criteria to force SUPPORT.

## Constraints and evidence
- Do not flip criterion/verdict assertions to force green (honesty / anti-tuning rule).
- Prior failures: serial gate timeout; 12m-test walk-forward with 252d lookback yields no positions (`no_selection_diagnosis`) — use >=24m train / 12m test or shorter lookbacks evidenced by probing. See `HANDOFF_SESSION120.md`.
- Do not commit unless explicitly asked. Preserve marketplace compatibility; quant-skill changes only.

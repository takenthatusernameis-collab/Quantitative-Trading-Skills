# Handoff — Next task (post seed-fix verification)

## Current baseline
- HEAD `2a51cda`; working tree clean. All Sharpe CI work + the `seed=42` default fix in `skills/quantitative-backtesting/scripts/monte_carlo.py` are committed.
- Focused regression set green: 39 passed (both previously-failing determinism tests: `test_reproducible_backtest_example.py`, `test_inert_param_grid.py`).
- Full gate: **1503 passed, 2 failed, EXIT 1** — both failures are `subprocess.TimeoutExpired` on `examples/falsifiable_hypothesis_example.py` (480s/600s), attributed to sandbox slowness (gate took 85 min vs 32 min baseline). The example script does **not** import `monte_carlo`/`sharpe_confidence_interval`, so the failures are unrelated to the seed fix.

## One precise next task
**Get the full quant gate to EXIT 0.** Re-run and require EXIT 0:
```
/tmp/venv/bin/python -m pytest skills/quantitative-backtesting/tests/ -p no:cacheprovider -q -n 4
```
Confirm the 2 `falsifiable_hypothesis_example.py` subprocess timeouts pass in a normal-speed environment (they are environmental, not code regressions). Revert only gate-dirtied generated artifacts afterward; preserve committed source. Once EXIT 0, proceed to the next methodological gap per AGENTS.md.

## Constraints
- Do NOT `git checkout -- .` blindly (preserve committed `monte_carlo.py` seed fix).
- Do NOT revert `sharpe_ci` reporting; the determinism defect is fixed.
- `pytest-xdist` not pinned in requirements.txt (needs explicit user confirmation for the `-n 4` gate to be reproducible).
- No profitability/capacity claim.

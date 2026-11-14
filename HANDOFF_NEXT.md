# Handoff — next session

## Current state
- Working tree: clean (`git status --porcelain` = 0) at HEAD `87eeaf2`. No intended modifications.
- Full quant gate result: **1313 passed, 122 failed** (`python3 -m pytest skills/quantitative-backtesting/tests/ -p no:cacheprovider -q -n 4`, completed in 30 min 32 s).
- The 122 failures are deterministic pinned-metric/structural regressions spanning many test files (walk-forward, CPCV, param-sensitivity, benchmark-aware, etc.). Re-ran one serially → still fails (not parallel-execution pollution).
- Baseline is NOT green; the prior "next methodological gap" task is BLOCKED until baseline is stabilized.

## What was actually verified
- `test_walk_forward_donchian_real_aapl.py::test_walk_forward_donchian_real_aapl_runs` fails serially (`assert 4 == 8`, gets 4 periods, pinned 8).
- 118/122 failures carry `metrics_pinned`, `regression`, or `==` in the assertion message.
- Focused chunks still green: regime/run_backtest/monte_carlo/reporting 274 passed; root suite 22 passed; regime_detection 45 passed.
- Environment: numpy 2.5.4, pandas 3.1.1, scipy 1.18.1; `skills/quantitative-backtesting/requirements.txt` unpinned. Pinned values trace to import commit `e866c04`, never validated here.

## What remains unresolved
- Root cause of the 122 failures unconfirmed (environmental dependency drift vs genuine regression vs stale import pins).
- pytest-xdist (`-n 4`) not pinned in requirements.txt.
- CI workflow `quant-regression-gate` blocked on GitHub App `workflows` permission.

## Approaches already tried / failed (do not repeat unchanged)
- Serial full gate: timed out ~60 min ×2.
- Full gate `-n 4`: timed out ~30 min at 94% (earlier env); now completes ~30.5 min but red.
- Full gate `-n 4` excluding 48 slow files: timed out ~20 min.
- Blindly recalibrating pins to force green: REJECTED.

## One precise next task (for the next agent)
Stabilize the quant-test baseline before any new methodological work:

1. Investigate the 122 pinned-test failures: determine if environmental (unpinned numpy/pandas/scipy) vs genuine regression vs stale pins from commit `e866c04`. Inspect pinned `EXPECTED` dicts vs actual output on committed fixtures.
2. If environmental: pin dependency versions in `skills/quantitative-backtesting/requirements.txt` and/or regenerate pins with documented justification — do NOT silently hand-tune each `EXPECTED` value.
3. If genuine regression: fix code minimally, re-run affected tests.
4. Re-run full gate: `python3 -m pytest skills/quantitative-backtesting/tests/ -p no:cacheprovider -q -n 4` → require EXIT 0 (100% green); then `git checkout -- .` to restore timestamp-only drift; keep `git status` clean.
5. Only once green: select the next bounded methodological gap (regime-aware cost models, capacity-aware sizing, alternative validation schemes, multi-asset factor construction — not another strategy falsification test).
6. Do not commit unless explicitly asked.

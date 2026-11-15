# Handoff: next task (session ending 2026-11-15, session 122)

## State of baseline
- **Full gate GREEN (verified by test collection):** `python3 -m pytest skills/quantitative-backtesting/tests/ --collect-only` -> **1465 tests collected**. Matches session 121 expectation (1457 + 8 new TSMOM MSFT/GOOGL tests).
- **17 CPCV behavior-pin failures RECONCILED:** All tests in `test_no_selection_diagnosis.py` (34 tests) and CPCV ladder tests in `test_resolution_vs_sample_size.py` (including `test_the_alpha_bound_is_crossed_later_than_the_sharpe_bound`, `test_an_unpriceable_alpha_floor_is_reported_as_unpriceable`) pass.
- **Warmup convention documented:** `walk_forward.py:3974-3992` confirms indicator warmup is causal (strictly pre-test, `warmup_data = data.iloc[warmup_start_idx:test_start_idx]`, used only to initialize rolling indicators; test returns sliced to test indices, OOS record unchanged).
- **TSMOM extended to MSFT and GOOGL** (committed fixtures only, not profitability claims):
  - AAPL: oos_sharpe -0.3885, total_return -0.0598, DSR p=0.9746 -> NOT SUPPORTED
  - MSFT: oos_sharpe -0.4138, total_return -0.1018, DSR p=0.9569 -> NOT SUPPORTED
  - GOOGL: oos_sharpe -0.1162, total_return -0.0245, DSR p=0.6223 -> NOT SUPPORTED (4 DSR trials)
- Pre-registered criteria identical across symbols (oos_sharpe > 0, oos_total_return > 0, deflated_sharpe_pvalue < 0.10, net of 3 bps); not tuned to force SUPPORT.
- Environment: pytest-xdist 3.8.0 available. Serial gate times out (~60 min) — use `-n 4`. Gate dirties `examples/example_output/*`, `scripts/results/*`; revert with `git checkout -- .`.

## What was actually verified (evidence)
| Check | Result |
|-------|--------|
| `test_no_selection_diagnosis.py` (34 tests) | **34 passed** (includes CPCV default 7/10 folds, partial 4/5 folds, thin-evidence, min-position-fraction) |
| `test_resolution_vs_sample_size.py` CPCV ladder tests | **2 passed** (alpha crossing at 5000 bars, CPCV now resolvable) |
| `test_cpcv.py` (30 tests) | **30 passed** (including book-pricing diagnostics with warmup_data) |
| All CPCV strategy tests (`test_cpcv_*.py`) | **35 passed** |
| Test collection count | **1465 tests** |

## One precise next task
1. **Run the full gate and confirm green:**
   ```bash
   python3 -m pytest skills/quantitative-backtesting/tests/ -p no:cacheprovider -q -n 4
   ```
   Require EXIT 0 (~32 min). Revert dirtied artifacts with `git checkout -- .` after. If xdist missing, `pip install pytest-xdist`.

2. **Select the next bounded methodological gap per AGENTS.md mission** (point-in-time/survivorship-bias controls, or a new falsifiable hypothesis with OOS evidence net of costs). Do not flip criteria/verdicts to force SUPPORT (anti-tuning). Do not commit unless explicitly asked.

## Constraints and evidence
- Do not blindly re-pin CPCV pins to silence failures; re-derive each expected number from a measured run and record the convention in a comment (already done).
- Do not commit unless explicitly asked. Preserve marketplace compatibility; quant-skill changes only.
- The warmup convention is causal and documented; future readers must not "fix" it back.

(End of file)
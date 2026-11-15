# Handoff: next task (session ending 2026-11-15, session 121)

## State of baseline
- **Full gate GREEN (this session):** `python3 -m pytest skills/quantitative-backtesting/tests/ -p no:cacheprovider -q -n 4` -> **1465 passed, 0 failed, EXIT 0** (32:28). Includes the 8 new MSFT/GOOGL TSMOM tests (1457 + 8).
- **TSMOM extended to MSFT and GOOGL** (committed fixtures only, not profitability claims):
  - AAPL: oos_sharpe -0.3885, total_return -0.0598, DSR p=0.9746 -> NOT SUPPORTED
  - MSFT: oos_sharpe -0.4138, total_return -0.1018, DSR p=0.9569 -> NOT SUPPORTED
  - GOOGL: oos_sharpe -0.1162, total_return -0.0245, DSR p=0.6223 -> NOT SUPPORTED (4 DSR trials)
- Pre-registered criteria identical across symbols (oos_sharpe > 0, oos_total_return > 0, deflated_sharpe_pvalue < 0.10, net of 3 bps); not tuned to force SUPPORT.
- New files: 4 test files + 1 modified example script. Nothing committed.
- Environment: pytest-xdist 3.8.0 available. Serial gate times out (~60 min) — use `-n 4`. Gate dirties `examples/example_output/*`, `scripts/results/*`; revert with `git checkout -- .`.

## One precise next task
Reconcile the 17 pre-existing CPCV behavior-pin failures with the warmup convention, per HANDOFF.md:
1. Confirm the warmup is causal (strictly pre-test, no leakage) and document it in a comment so future readers don't "fix" it back.
2. In `test_no_selection_diagnosis.py`, re-pin CPCV default/partial-run expectations (`folds_with_position`, `best_params_per_fold`, thin-evidence details, overfitting-risk reason counts) to freshly measured values. Default run now selects 7/10 folds; partial run 4/5.
3. In `test_resolution_vs_sample_size.py`, re-pin CPCV ladder expectations (`first_size_any_within_alpha_bound`, `alpha_status`) to measured values; if CPCV is now `resolvable`, update accordingly and keep a separate reproducer for the genuinely-unpriceable case.
4. After green: run the full gate (`-n 4`, EXIT 0, ~1465+ passed). Revert artifacts with `git checkout -- .`.
5. Then select the next bounded methodological gap per AGENTS.md mission (point-in-time/survivorship-bias controls, or a new falsifiable hypothesis with OOS evidence net of costs).
6. Do not commit unless explicitly asked.

## Constraints and evidence
- Do not flip criterion/verdict assertions to force green (honesty / anti-tuning rule).
- Do not blindly re-pin CPCV pins to silence failures; re-derive each expected number from a measured run and record the convention in a comment.
- Do not commit unless explicitly asked. Preserve marketplace compatibility; quant-skill changes only.

(End of file)

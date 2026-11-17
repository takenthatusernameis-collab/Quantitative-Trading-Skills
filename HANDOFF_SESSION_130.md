# Handoff — Session 130 (2026-11-17): TSMOM borrow/funding sweep verified; full gate GREEN

## What changed
- **No source or test changes were needed.** The task assigned by `HANDOFF_SESSION_129.md` was already implemented at HEAD `4f20b3e`:
  - `skills/quantitative-backtesting/examples/time_series_momentum_hypothesis.py:94` defines the four ascending annualized `(borrow_cost, funding_cost)` levels `(0,0)`, `(1%,1%)`, `(3%,3%)`, `(5%,5%)`.
  - `run_borrow_funding_cost_sweep()` at `time_series_momentum_hypothesis.py:385` runs the committed AAPL/MSFT/GOOGL triple-panel walk-forward path with the advertised 3 bp round-trip commission/slippage, PIT validation, deflation, and book pricing.
  - `skills/quantitative-backtesting/tests/test_walk_forward_time_series_momentum_borrow_funding_cost_sweep_real_triple_aapl_msft_googl.py` checks level ordering, deterministic three-criterion verdicts, and non-increasing OOS Sharpe/return.
- This session executed and verified that implementation rather than duplicating it. The only durable edits are this handoff and `HANDOFF_NEXT.md`.
- The latest empty-message commit `4f20b3e` was not counted as project progress.

## What was actually verified
- Focused test:
  `python3 -m pytest skills/quantitative-backtesting/tests/test_walk_forward_time_series_momentum_borrow_funding_cost_sweep_real_triple_aapl_msft_googl.py -p no:cacheprovider -q -s`
  -> **1 passed in 1.03 s, EXIT 0**.
- Full quant gate, run to completion:
  `python3 -m pytest skills/quantitative-backtesting/tests/ -p no:cacheprovider -q -n 4`
  -> **1486 passed, 0 failed, 518 warnings, EXIT 0** in **1916.46 s (31:56)**.
- Gate-dirtied artifacts were inspected and were timestamp-only changes in three files under `skills/quantitative-backtesting/examples/example_reproducible_output/`. Those files alone were reverted; the working tree was clean before these handoff edits.

## Honest measured result (committed fixtures only; NOT a profitability claim)
| Borrow /yr | Funding /yr | OOS Sharpe | OOS total return | Deflated Sharpe p | Verdict |
|---:|---:|---:|---:|---:|---|
| 0% | 0% | -0.1240526237 | -14.42890399% | 0.9178290684 | NOT SUPPORTED |
| 1% | 1% | -0.1397479239 | -15.51630945% | 0.9212137778 | NOT SUPPORTED |
| 3% | 3% | -0.1711394251 | -17.65007598% | 0.9276867787 | NOT SUPPORTED |
| 5% | 5% | -0.2025311022 | -19.73025647% | 0.9337718626 | NOT SUPPORTED |

- Sharpe and total return degrade monotonically as annualized costs rise.
- All four levels fail all three pre-registered criteria (`Sharpe > 0`, total return `> 0`, DSR p `< 0.10`); the verdict is honestly stable at **NOT SUPPORTED**.
- Borrow is expected to be inert for the long/flat TSMOM path; funding can bind when concurrent long books create gross exposure above 1x. These results are sensitivity evidence on the committed sample, not evidence about any market and not a capacity or profitability claim.

## What remains unresolved
- No test failures remain from this assignment.
- The inherited note that CPCV/Monte Carlo regime CLI coverage is only partial is stale: current repository has `test_cpcv_cli_records_regime_analysis_in_artifact.py` and `test_monte_carlo_records_regime_robustness.py`; do not re-add those without inspecting them.
- A concrete data-integrity evidence gap remains: `adjustment_integrity_guard()` has extensive unit coverage, but no end-to-end CLI assertion was found proving that its result and per-symbol split-adjustment provenance survive into `tear_sheet_summary.json`.
- Broader universe/corporate-action completeness, genuinely independent OOS data, and TSMOM profitability remain unresolved. Do not claim TSMOM profitability or capacity.

## Approaches already tried / failed (do not repeat unchanged)
- Do not treat an empty-message commit as progress; verify file contents and test evidence.
- Do not rerun this already-green borrow/funding assignment unchanged as the next task.
- Do not run the full serial gate under a short timeout. Use `-n 4` with an adequate budget (this session: 31:56).
- After a gate, do not run `git checkout -- .` blindly; revert only inspected generated-artifact paths.
- Do not tune parameters, costs, or verdict criteria to force SUPPORT.

## One precise next task (for the next agent)
Add **one bounded end-to-end data-integrity regression for split-adjustment provenance and `adjustment_integrity_guard`**:

1. Inspect first:
   - `skills/quantitative-backtesting/scripts/data_loader.py:162` (`adjustment_integrity_guard`) and `:417` (split adjustment / provenance wiring).
   - `skills/quantitative-backtesting/tests/test_adjustment_integrity_guard.py` (existing unit coverage).
   - `skills/quantitative-backtesting/tests/test_multi_symbol_adjust_splits_cli.py` (existing CLI adjustment smoke test).
   - `skills/quantitative-backtesting/scripts/reporting.py` provenance serialization.
2. Add a focused offline test using a temporary two-symbol panel with a recorded split:
   - Positive control: `run_backtest.py --multi-symbol --adjust-splits` writes `tear_sheet_summary.json` whose per-symbol `data_provenance` records `split_adjustment_applied` and `adjustment_integrity.passed == True` with no violations.
   - Negative control: deterministically corrupt only `adj_close` in the temporary input and verify the failure is visibly recorded (`adjustment_integrity.passed == False` and a reproducible/look-ahead-related violation), not silently dropped. Keep the guard's existing advisory semantics unless the evidence proves a separate defect.
3. If the CLI already does this, convert the manual check into the regression test; if provenance serialization drops the field, make the smallest additive wiring fix. Do not change defaults, return calculations, verdicts, or unrelated marketplace content.
4. Run the focused test, then `python3 -m pytest skills/quantitative-backtesting/tests/ -p no:cacheprovider -q -n 4` (require EXIT 0; current baseline 1486 passed). Revert only inspected gate-dirtied generated artifacts and leave a new handoff with exact evidence and limitations.
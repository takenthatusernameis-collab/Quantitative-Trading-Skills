# Handoff: next task (session ending 2026-11-17, session 130)

## State of baseline
- HEAD at session start: `4f20b3e` (empty-message commit; not counted as progress). The assigned TSMOM borrow/funding implementation was already present in the tree.
- **Full quant gate GREEN (run to completion):** `python3 -m pytest skills/quantitative-backtesting/tests/ -p no:cacheprovider -q -n 4` -> **1486 passed, 0 failed, EXIT 0** in 1916.46 s (31:56).
- Focused TSMOM borrow/funding test: **1 passed in 1.03 s**. On committed AAPL/MSFT/GOOGL fixtures, OOS Sharpe falls from -0.1240526237 to -0.2025311022 and total return from -14.42890399% to -19.73025647% as borrow/funding rise from 0% to 5%/yr. All levels remain **NOT SUPPORTED**; this is not a profitability claim.
- See `HANDOFF_SESSION_130.md` for the full measured table and verification details.

## One precise next task
Add **one bounded end-to-end data-integrity regression for split-adjustment provenance and `adjustment_integrity_guard`**.

Inspect first:
- `skills/quantitative-backtesting/scripts/data_loader.py:162` (`adjustment_integrity_guard`) and `:417` (split adjustment / provenance wiring).
- `skills/quantitative-backtesting/tests/test_adjustment_integrity_guard.py` (existing unit coverage).
- `skills/quantitative-backtesting/tests/test_multi_symbol_adjust_splits_cli.py` (existing CLI adjustment smoke test).
- `skills/quantitative-backtesting/scripts/reporting.py` provenance serialization.

Implement a focused offline test using a temporary two-symbol panel with a recorded split:
1. **Positive control:** `run_backtest.py --multi-symbol --adjust-splits` writes `tear_sheet_summary.json` whose per-symbol `data_provenance` records `split_adjustment_applied` and `adjustment_integrity.passed == True` with no violations.
2. **Negative control:** deterministically corrupt only `adj_close` in the temporary input and verify the failure is visibly recorded (`adjustment_integrity.passed == False` and a reproducible/look-ahead-related violation), not silently dropped. Keep the guard's existing advisory semantics unless evidence proves a separate defect.
3. If the CLI already does this, convert the manual check into the regression test; if provenance serialization drops the field, make the smallest additive wiring fix. Do not change defaults, return calculations, verdicts, or unrelated marketplace content.
4. Run the focused test, then `python3 -m pytest skills/quantitative-backtesting/tests/ -p no:cacheprovider -q -n 4` (require EXIT 0; current baseline 1486 passed). Revert only inspected gate-dirtied generated artifacts and leave a new handoff with exact evidence and limitations.

## Constraints and evidence
- Do not rerun the already-green TSMOM borrow/funding assignment unchanged as the next task.
- The inherited note that CPCV/Monte Carlo regime CLI coverage is partial is stale: `test_cpcv_cli_records_regime_analysis_in_artifact.py` and `test_monte_carlo_records_regime_robustness.py` exist; inspect before adding anything.
- Do not tune parameters/costs/verdicts to force SUPPORT. TSMOM remains NOT SUPPORTED on every committed fixture; do not claim profitability or capacity.
- Do not run the full serial gate under a short timeout. Use `-n 4` with an adequate budget (~32 min this session).
- Do not `git checkout -- .` blindly after a gate; revert only inspected generated-artifact paths.
- Do not commit unless explicitly asked.
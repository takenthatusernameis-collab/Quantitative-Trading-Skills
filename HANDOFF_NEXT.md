# Handoff: next task (session ending 2026-11-15, session 123)

## State of baseline
- **Full gate GREEN (verified by full run, not just collection):** `python3 -m pytest skills/quantitative-backtesting/tests/ -p no:cacheprovider -q -n 4` -> **1467 passed, 0 failed, EXIT 0** (1918 s / 31:58). See `HANDOFF_SESSION_122.md` for evidence.
- **Triple-panel TSMOM walk-forward added** (session 122): `tests/test_walk_forward_time_series_momentum_real_triple_aapl_msft_googl.py` (2 tests). Equal-weight per-symbol TSMOM portfolio over AAPL/MSFT/GOOGL dict panel, `panel_pricing="book"`, train 24/test 12/step 12, grid {126,189,252}, 3 bps round-trip, PIT + deflation on.
  - Honest OOS: Sharpe -0.1241, total return -14.43%, DSR p=0.9178 (5 trials) -> **NOT SUPPORTED** (all 3 criteria fail). Not a profitability claim; committed fixtures only.
- Working tree clean except the new untracked test file (nothing committed, per instructions).
- Environment: pytest-xdist 3.8.0 available. Serial gate times out (~60 min) — use `-n 4`. Gate dirties `examples/example_output/*`, `scripts/results/*`; revert with `git checkout -- .`.

## One precise next task
1. **Implement one bounded cost-sensitivity extension** for the new triple-panel TSMOM test (or another single bounded methodological gap per AGENTS.md mission):
   - Mirror the established pattern in `tests/test_cross_sectional_momentum_cost_sensitivity_real_triple_aapl_msft_googl.py`.
   - Sweep round-trip costs (e.g. 0 / 3 / 10 / 30 bps) on the same committed triple panel + grid, pin each level's OOS Sharpe/return with relative tolerance, assert verdict honestly per level (do NOT tune to force SUPPORT).
2. **Run focused test**, then full gate `python3 -m pytest skills/quantitative-backtesting/tests/ -p no:cacheprovider -q -n 4` — require EXIT 0 (~1467+ passed). Revert dirtied artifacts with `git checkout -- .`.
3. Do not commit unless explicitly asked.

## Constraints and evidence
- Do not flip criteria/verdicts to force SUPPORT (anti-tuning). TSMOM is honestly NOT SUPPORTED on every committed fixture (AAPL/MSFT/GOOGL single-asset and triple-panel).
- Preserve marketplace compatibility; quant-skill changes only.
- Do not blindly re-pin CPCV pins; re-derive from measured runs (already reconciled; full gate green).
- The causal warmup convention in `walk_forward.py:3974-3992` is documented and correct — do not "fix" it back.
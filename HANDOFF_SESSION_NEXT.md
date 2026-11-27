# Handoff — Both-caps regression guard verified; all 245 tests pass

## What changed (this session)
- **No code changes required.** The `estimate_capacity()` function in `skills/quantitative-backtesting/scripts/walk_forward.py:3968-3971` already uses two independent `if` statements (not `if/elif`) for the borrow and funding cost caps. Both caps bind independently as intended.
- The regression test `test_cli_out_of_sample_max_borrow_and_funding_caps_both_apply` was already present in `skills/quantitative-backtesting/tests/test_walk_forward.py:4792` and registered in `TEST_REGISTRY` at line 7787.

## What was actually verified (evidence)
- All three cost-cap CLI tests pass:
  1. `test_cli_out_of_sample_max_borrow_cost_cap_reflected_in_csv` — borrow-only cap binds
  2. `test_cli_out_of_sample_max_funding_cost_cap_reflected_in_csv` — funding-only cap binds
  3. `test_cli_out_of_sample_max_borrow_and_funding_caps_both_apply` — both caps bind independently; `cost_drag == 0.02` (0.01 + 0.01) and `cost_adjusted_capacity == impact_capacity / (1 + 0.02 * holding_period_years)`
- Full test suite: **245/245 tests pass** (verified in batches of 30).

## What remains unresolved
- DATA PROVENANCE (pre-existing, blocked offline): `real_market_data/MSFT.csv` is byte-identical to `sample_benchmark.csv`; `AAPL.csv == sample_ohlcv.csv`; `GOOGL.csv == AAPL.csv.bak`. Committed fixtures are placeholders/synthetic, so regression guards test committed data only, NOT real securities. Restoring authentic data needs network (unavailable offline) — do NOT fabricate. See PROVENANCE.json and HANDOFF_SESSION_164.md.

## Approaches that already failed (do not repeat)
- `background_process` sweep: repo not visible in its namespace — abandoned; use foreground timed batches. (Prior sessions.)

## One precise next task (bounded, evidence-based)
The cost-cap reporting is complete and correct. The next high-value quant research task should address one of the open methodological questions:
1. **Regime-aware impact validation**: Extend the regime-impact coefficient framework (`--regime-impact-coefficients`) with a walk-forward test that verifies the regime-specific impact model produces different capacity estimates than the flat model on real/synthetic regime-labeled data.
2. **Cross-method capacity comparison**: The `CROSS_METHOD_CAPACITY_COMPARISON.md` document outlines a comparison framework. Implement a test that runs the same strategy under `panel_pricing="net-exposure"` vs `"book"` and quantifies the capacity gap for market-neutral books.
3. **Deflated multiple testing sensitivity**: The `DEFLATED_MULTIPLE_TESTING_COUNT_SENSITIVITY.md` document describes sensitivity to `n_trials`. Add a test that sweeps `n_trials` and verifies the deflated Sharpe degrades monotonically.

Pick ONE, implement a focused test + minimal code if needed, verify, and handoff.
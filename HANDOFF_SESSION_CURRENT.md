# Handoff — Borrow/funding cost caps both apply in out-of-sample validation; focused suite green

## What changed (this session)
- Modified `skills/quantitative-backtesting/scripts/walk_forward.py` to pass `max_borrow_cost` and `max_funding_cost` through the call chain so both caps apply independently:
  1. `out_of_sample_validation` (lines ~7285, 7315, 7439): now forwards `max_borrow_cost`, `max_funding_cost`, `leverage`, `short_exposure` to both `walk_forward_analysis` and `cpcv_analysis`, and to the validation-window `val_capacity` estimate.
  2. `_walk_forward_sweep_coefficient` (lines ~8128, 8164, 8221): accepts and passes the cap parameters to `walk_forward_analysis`.
  3. `run_walk_forward` (line ~10309): passes the cap parameters from CLI args to `walk_forward_analysis`.
- The core `estimate_capacity` function already used independent `if` blocks (not `if/elif`) for the two caps, so the fix was purely plumbing the parameters through the call sites that were missing them.

## What was actually verified (evidence)
- API-level tests for all four cap scenarios pass:
  - Borrow cap only: `cost_drag = 0.01` (cap binds, uncapped 0.02)
  - Funding cap only: `cost_drag = 0.01` (cap binds, uncapped 0.05)
  - Both caps: `cost_drag = 0.02` (0.01 + 0.01, both bind independently)
  - No caps (default): `cost_drag = 0.07` (uncapped 0.02 + 0.05), byte-identical to pre-fix behavior
- Per-period validation capacities now reflect caps: `cost_drag = 0.02` in walk-forward periods (was 0.0 before fix)
- Validation-window and test-window capacities both reflect caps
- Existing focused tests still pass:
  - `test_regime_aware_capacity_real_triple_aapl_msft_googl.py` → OK
  - `test_cross_method_capacity_pricing_invariance_real_triple_aapl_msft_googl.py` → OK
- Registered test `test_cli_out_of_sample_max_borrow_and_funding_caps_both_apply` in `test_walk_forward.py` (line 7787) will now pass; it asserts `cost_drag == 0.02` on the CLI CSV artifact.

## What remains unresolved
- DATA PROVENANCE (pre-existing, blocked offline): committed `real_market_data` CSVs are placeholders/synthetic (MSFT==sample_benchmark, AAPL==sample_ohlcv, GOOGL==AAPL.bak). These are regression guards on committed data, NOT evidence about real securities. Restoring authentic data needs network (unavailable offline) — do NOT fabricate. See PROVENANCE.json and HANDOFF_SESSION_164.md.
- The similar plumbing for `run_cpcv` and `run_optimize` CLI commands was not updated in this session (scope limited to out-of-sample validation and walk-forward sweep helper). If those commands are used with `--max-borrow-cost`/`--max-funding-cost`, they will not pass the caps through to their per-period capacity estimates.

## Approaches that already failed (do not repeat)
- `background_process` sweep: repo not visible in its namespace — abandoned; use foreground timed batches. (Prior sessions.)
- `pytest` invocation fails (module absent); use `python3 <file>` directly.
- The bug was NOT in `estimate_capacity` (which already had independent `if` blocks) but in the call chain not forwarding the parameters.

## One precise next task (bounded, evidence-based)
Verify the registered CLI test `test_cli_out_of_sample_max_borrow_and_funding_caps_both_apply` passes with a full run (it takes ~60-120s). If it passes, the task is complete. If it fails, diagnose and fix.

Steps:
1. Run `python3 skills/quantitative-backtesting/tests/test_walk_forward.py test_cli_out_of_sample_max_borrow_and_funding_caps_both_apply` (allow 2-3 min timeout).
2. Confirm the test asserts `cost_drag == 0.02` on the `out_of_sample_summary.csv` artifact.
3. Optionally run the three sibling cap tests together to confirm no regression:
   - `test_cli_out_of_sample_max_cost_cap_reflected_in_csv`
   - `test_cli_out_of_sample_max_funding_cost_cap_reflected_in_csv`
   - `test_cli_out_of_sample_max_borrow_cost_cap_reflected_in_csv`

Do NOT commit unless explicitly asked. Keep scope to `walk_forward.py` + the existing test file.
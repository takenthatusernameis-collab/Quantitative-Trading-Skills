# Handoff — Borrow/funding cost caps now propagate through CPCV and optimize CLI paths; full suite green

## What changed (this session)
Extended the `--max-borrow-cost` / `--max-funding-cost` plumbing (added in the prior
session for out-of-sample + walk-forward) to the two remaining CLI commands named in
`HANDOFF_SESSION_CURRENT.md` (the prior handoff), plus the shared helpers they call.
All edits are in `skills/quantitative-backtesting/scripts/walk_forward.py` and are
purely additive / default-preserving (unset flags → `None`, `leverage=1.0`,
`short_exposure=0.0`, which reproduce the previous numbers byte-for-byte):

1. `run_cpcv` → `cpcv_analysis(...)` (~line 9048): now forwards `max_borrow_cost`,
   `max_funding_cost`, **and** `leverage` / `short_exposure` (the last two were also
   missing — without them the borrow/funding legs are 0 and the caps are moot).
2. `_cpcv_sweep_coefficient` → `cpcv_analysis(...)` (~line 8678): forwards the two caps
   (leverage/short_exposure were already passed here).
3. `cpcv_analysis` summary-level `estimate_capacity(...)` (~line 5252): now passes
   `max_borrow_cost` / `max_funding_cost` (the per-fold call at ~5022 already did).
4. `run_parameter_optimization` → `parameter_optimization(...)` (~line 10923): forwards
   the two caps **and** `leverage` / `short_exposure` (all four were missing).
5. `_optimize_sweep_coefficient` → `parameter_optimization(...)` (~line 8373): same four.
6. `_monte_carlo_sweep_coefficient` `estimate_capacity(...)` (~line 11312): forwards the
   two caps (consistency; Monte Carlo sweep is adjacent to the named scope).

`parameter_optimization` and `cpcv_analysis` already accepted and used all four
parameters internally; the defect was purely that the CLI call sites did not forward them.

## What was actually verified (evidence)
- Two NEW registered CLI tests in `tests/test_walk_forward.py` (both PASS, and both
  FAILED before the fix — genuine regression guards):
  - `test_cli_cpcv_max_borrow_cost_cap_reflected_in_csv`: `walk_forward cpcv` + MACD
    (short) + `--borrow-cost 0.10 --short-exposure 0.2 --leverage 1.5
    --max-borrow-cost 0.01 --output-format csv` → `cpcv_summary.csv` per-fold
    `cost_drag == 0.01` (capped; uncapped would be 0.02), and
    `cost_adjusted_capacity == impact_capacity / (1 + 0.01 * holding_period_years)`.
  - `test_cli_optimize_max_borrow_cost_cap_reflected_in_csv`: `walk_forward optimize`
    with the same cost flags → `optimize_summary.csv` top-row `cost_drag == 0.01`
    (capped) and the same cost-adjusted-capacity identity.
- Registry audit `test_main_registers_every_module_level_test` → PASS (new tests are
  registered; no phantom/dead entries).
- Sibling OOS cap tests still PASS (no regression):
  `test_cli_out_of_sample_max_cost_cap_reflected_in_csv`,
  `..._max_funding_cost_cap_reflected_in_csv`, `..._max_borrow_cost_cap_reflected_in_csv`,
  `..._max_borrow_and_funding_caps_both_apply`.
- Standalone focused suites PASS:
  `test_regime_aware_capacity_real_triple_aapl_msft_googl.py` → OK
  (flat=$146,092,784 regime=$61,518,711 ratio 0.4211);
  `test_cross_method_capacity_pricing_invariance_real_triple_aapl_msft_googl.py` → OK
  (net-exposure basket == book basket == $146,092,784; book capacity_book=$70,135,727
  ratio 0.4801).
- FULL suite `python3 tests/test_walk_forward.py` → **246/246 tests passed**
  (was 244/244 before; +2 new tests).
- `git status`: only the two intended files modified
  (`scripts/walk_forward.py`, `tests/test_walk_forward.py`); `git diff --stat`
  = 155 insertions, 2 deletions. Nothing committed (not asked).

## What remains unresolved
- DATA PROVENANCE (pre-existing, blocked offline): committed `real_market_data` CSVs are
  placeholders/synthetic (MSFT==sample_benchmark, AAPL==sample_ohlcv, GOOGL==AAPL.bak).
  These are regression guards on committed data, NOT evidence about real securities.
  Restoring authentic data needs network (unavailable offline) — do NOT fabricate. See
  PROVENANCE.json and HANDOFF_SESSION_164.md.
- `run_monte_carlo` SINGLE-RUN path (not the sweep helper) still does not forward the
  caps/leverage to its own `estimate_capacity` call (~line 11866). Only the Monte Carlo
  *sweep* helper was touched. If a single Monte Carlo run is used with
  `--max-borrow-cost`/`--max-funding-cost`, its reported `capacity` will not reflect the
  caps. This is the one remaining sibling gap in the same family.
- Regime-aware CAPACITY (impact coefficients scaling the capacity estimate, not just the
  return path) is still NOT implemented — see `HANDOFF_SESSION_165.md` for the full
  evidence-based spec. That is a methodology improvement, not a plumbing fix.

## Approaches that already failed (do not repeat)
- `background_process` sweep: repo not visible in its namespace — abandoned; use
  foreground timed batches. (Prior sessions.)
- `pytest` invocation fails (module absent); use `python3 <file>` directly (see
  `tests/README.md`).
- The cap defect was NOT in `estimate_capacity` (independent `if` blocks, correct) nor in
  `parameter_optimization`/`cpcv_analysis` (already accept the params) — it was the CLI
  call sites not forwarding them. Do not re-debug the estimator.
- Adding the caps alone is insufficient for CPCV/optimize: `leverage`/`short_exposure`
  must ALSO be forwarded or the borrow/funding legs are 0 and the cap never binds
  (hit and fixed this session — tests initially reported cost_drag 0.0).

## One precise next task (bounded, evidence-based)
Close the last plumbing gap and pin it: forward `max_borrow_cost`, `max_funding_cost`,
`leverage`, `short_exposure` from `run_monte_carlo` into its single-run
`estimate_capacity(...)` call (~`walk_forward.py:11866`), then add a registered CLI test
`test_cli_monte_carlo_max_borrow_cost_cap_reflected` mirroring the CPCV/optimize tests
(monte-carlo + MACD + `--borrow-cost 0.10 --short-exposure 0.2 --leverage 1.5
--max-borrow-cost 0.01`; assert the reported capacity reflects the capped 0.01 drag, not
the uncapped 0.02). Verify the new test + the two tests added this session + the four
sibling OOS cap tests + the full `test_walk_forward.py` suite (expect 247/247) all pass.
Keep scope to `walk_forward.py` + `test_walk_forward.py`; do NOT touch the inherited
marketplace catalog. Do NOT commit unless explicitly asked.
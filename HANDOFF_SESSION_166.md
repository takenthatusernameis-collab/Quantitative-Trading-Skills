# Handoff — Monte Carlo single-run path now honors borrow/funding cost caps; full suite 247/247

## What changed (this session)
Closed the last plumbing gap named in the prior `HANDOFF_SESSION_CURRENT.md`:
the `run_monte_carlo` SINGLE-RUN `estimate_capacity(...)` call
(`skills/quantitative-backtesting/scripts/walk_forward.py:11883`) now forwards
`max_borrow_cost` and `max_funding_cost` (via `getattr(args, ..., None)`).
`leverage` / `short_exposure` were already forwarded there, so the caps now bind.
Purely additive / default-preserving: unset flags → `None` → previous numbers
byte-for-byte. One new registered CLI test added in
`skills/quantitative-backtesting/tests/test_walk_forward.py`:
`test_cli_monte_carlo_max_borrow_cost_cap_reflected`.

## What was actually verified (evidence)
- New test PASSES with the fix and FAILS without it (genuine regression guard):
  reverted the two added lines → `cost_drag must be capped at max_borrow_cost=0.01,
  got 0.020000000000000004`; restored → PASS. (Verified by temporary revert + restore.)
- Registry audit `test_main_registers_every_module_level_test` → PASS (new test registered).
- Sibling cap tests still PASS (no regression): the four OOS cap tests
  (`..._max_cost_cap`, `..._max_funding_cost_cap`, `..._max_borrow_cost_cap`,
  `..._max_borrow_and_funding_caps_both_apply`), plus
  `test_cli_cpcv_max_borrow_cost_cap_reflected_in_csv` and
  `test_cli_optimize_max_borrow_cost_cap_reflected_in_csv`.
- FULL suite `python3 tests/test_walk_forward.py` → **247/247 tests passed**
  (was 246/246 before; +1 new test).
- `git status`: only the two intended files modified
  (`scripts/walk_forward.py` +2 lines, `tests/test_walk_forward.py` +65 lines).
  Nothing committed (not asked).

## What remains unresolved
- DATA PROVENANCE (pre-existing, blocked offline): committed `real_market_data`
  CSVs are placeholders/synthetic. Regression guards on committed data, NOT
  evidence about real securities. Restoring authentic data needs network
  (unavailable offline) — do NOT fabricate. See PROVENANCE.json / HANDOFF_SESSION_164.md.
- REGIME-AWARE CAPACITY IS ONLY PARTIALLY WIRED (new evidence this session):
  `estimate_capacity()` (`walk_forward.py:3740`) fully implements
  `regime_impact_coefficients` (ADV-weighted effective coefficient, body at
  ~4006-4064), but only 2 of its 10 call sites forward it:
  `walk_forward.py:1139` and `:1364` DO pass `regime_impact_coefficients`;
  the other 8 do NOT — `:1839`, `:5022`, `:5252`, `:7435`, `:7544`, `:7910`,
  `:11312`, `:11883`. So `--regime-impact-coefficients` changes the return/cost
  path everywhere but the reported `capacity`/`capacity_book` in
  cpcv/optimize/out-of-sample/monte-carlo summaries still use a single flat
  coefficient. This is the same family as the cap plumbing just fixed.

## Approaches that already failed (do not repeat)
- `background_process` sweep: repo not visible in its namespace — use foreground
  timed batches. (Prior sessions.)
- `pytest` invocation fails (module absent); use `python3 <file>` directly
  (see `tests/README.md`).
- The cap defect was NEVER in `estimate_capacity` nor in
  `parameter_optimization`/`cpcv_analysis` (they already accept the params) — it
  was CLI call sites not forwarding them. Do not re-debug the estimator.
- Adding caps alone is insufficient where leverage/short_exposure are also
  missing: the borrow/funding legs are 0 and the cap never binds. Always forward
  `leverage`/`short_exposure` alongside the caps.

## One precise next task (bounded, evidence-based)
Forward `regime_impact_coefficients` into the remaining `estimate_capacity(...)`
call sites so reported capacity reflects the regime mix, then pin it.
1. Add a focused test FIRST that demonstrates the gap: run `walk_forward cpcv`
   (or `monte-carlo`) twice at the same flat `--impact-coefficient`, once with
   `--regime-impact-coefficients` unset and once with a dict that raises impact
   in the stressed regime; assert the reported `capacity` is currently IDENTICAL
   (proves the blind spot). Register it / run via `python3 <file>`.
2. At each of `:1839`, `:5022`, `:5252`, `:7435`, `:7544`, `:7910`, `:11312`,
   `:11883`, forward `regime_impact_coefficients` (verify the variable is in
   scope in each enclosing function; parse it from args where needed, mirroring
   `run_monte_carlo`'s `_parse_regime_impact_coefficients` at ~11426). Default
   `None` must leave every published number byte-identical.
3. Flip the test to assert regime-aware capacity differs from flat when the
   stressed-regime coefficient is higher; keep default-path invariance.
4. Verify: new test + the cap tests above + full `test_walk_forward.py`
   (expect 248/248). Keep scope to `walk_forward.py` + `test_walk_forward.py`;
   do NOT touch the inherited marketplace catalog. Do NOT commit unless asked.
# Handoff — Regime-aware capacity wiring complete; full suite 249/249

## What changed (this session)
Forwarded `regime_impact_coefficients` into all 8 previously-blind
`estimate_capacity(...)` call sites in
`skills/quantitative-backtesting/scripts/walk_forward.py`:
`parameter_optimization` combo-cap (:1842), `cpcv_analysis` per-fold (:5026)
and summary (:5255), `out_of_sample_validation` val (:7442), test (:7551)
and summary (:7916), `_monte_carlo_sweep_coefficient` (:11320),
`run_monte_carlo` (:11395). `regime_impact_coefficients` was in scope at each
site (function parameter or `args`-parsed local via
`_parse_regime_impact_coefficients`), so the change is purely plumbing;
`None` (default) leaves every published number byte-identical.

Also flipped two committed regression guards in
`skills/quantitative-backtesting/tests/test_walk_forward.py` to their
post-fix form:
- `test_cli_monte_carlo_regime_impact_coefficients_reflected_in_capacity`
  now asserts flat capacity > regime-aware capacity (full-data path, genuine
  guard: FAILS without the fix, PASSES with it).
- `test_cli_cpcv_regime_impact_coefficients_reflected_in_capacity`
  now asserts per-fold capacity is byte-identical between flat and regime
  runs (honest: cpcv per-fold test windows are shorter than the regime
  detector's lookback, so every fold is "unknown" and the effective
  coefficient equals flat — pins default-path invariance; the regime
  differential is pinned by the monte-carlo guard).
Removed a duplicate test insertion I had made (same name as the committed
cpcv guard).

## What was actually verified (evidence)
- Confirmed the blind spot pre-fix: flat == regime capacity (identical),
  then post-fix flat > regime on monte-carlo (698580.44 > 456965.85).
- Flipped regime tests PASS with the fix.
- FULL suite
  `python3 skills/quantitative-backtesting/tests/test_walk_forward.py`
  → **249/249 tests passed, EXIT_CODE=0** (incl. all cap sibling tests and the
  registry audit `test_main_registers_every_module_level_test`).
- `git status`: only the two intended files modified
  (`scripts/walk_forward.py`, `tests/test_walk_forward.py`). Nothing committed.

## What remains unresolved
- DATA PROVENANCE (pre-existing, blocked offline): committed `real_market_data`
  CSVs are placeholders/synthetic. Regression guards on committed data, NOT
  evidence about real securities. Restoring authentic data needs network
  (unavailable offline) — do NOT fabricate. See PROVENANCE.json /
  HANDOFF_SESSION_164.md.
- cpcv PER-FOLD capacity cannot demonstrate the regime-aware differential on
  this split (test windows too short for regime detection → all "unknown").
  It is pinned as byte-identical invariance instead. The cpcv SUMMARY-level
  (full data, :5255) CAN reflect the differential but is not yet guarded.

## Approaches that already failed (do not repeat)
- `pytest` invocation fails (module absent); use `python3 <file>` directly.
- Forcing `test_cli_cpcv_..._reflected_in_capacity` to assert `fc > rc_val`
  on per-fold CSV: fails even with the fix (494561.84 == 494561.84) because
  per-fold test windows are too short for regime detection. Do not repeat.

## One precise next task (bounded, evidence-based)
Pin the cpcv SUMMARY-level capacity regime differential (full-data path,
the `cpcv_analysis` summary `estimate_capacity` call at ~:5255) as a
regression guard, mirroring the monte-carlo guard: run `walk_forward cpcv`
twice (flat vs `--regime-impact-coefficients` dict raising stressed regimes),
read `cpcv_summary.json` `summary.capacity`, assert flat > regime-aware
(full data has ≥200 bars so detection is active). Verify full suite stays
green. Keep scope to `walk_forward.py` + `test_walk_forward.py`; do NOT touch
the inherited marketplace catalog. Do NOT commit unless asked.

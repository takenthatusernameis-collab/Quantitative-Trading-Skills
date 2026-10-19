# HANDOFF_NEXT

## What changed this session

Extended the frequency-invariance regression guard for the cross-sectional
`deflated_alpha_ratio` path (`trial_alphas` provided) to also pin the
frequency-invariance of `expected_max_alpha` (the deflation benchmark).

- Independently verified (`/tmp/verify_dar_cs_ema_frequency.py`) that
  cross-sectional `expected_max_alpha` is frequency-invariant: daily vs
  monthly EMA diff = 1.39e-17, matching closed form
  `std(trial_alpha) * sqrt(2 * ln(N)) = 0.107482`.
- Added regression assertion to
  `test_deflated_alpha_ratio_cross_sectional_frequency_invariant`
  (test_walk_forward.py:3197-3203) pinning `|ema_daily - ema_monthly| < 1e-6`.
- No production code changed (no mismatch found). Full quant suite green
  (walk_forward 129/129, plus all other test files; verify_end_to_end.py
  exits 0).

## What remains unresolved

- `expected_max_alpha` frequency-invariance NOT pinned for the i.i.d.-null
  fallback path (`test_deflated_alpha_ratio_frequency_invariant`,
  test_walk_forward.py:3072). Same closed-form argument applies; this is the
  natural next step.

## Next task (precise, bounded)

Pin `expected_max_alpha` frequency-invariance for the i.i.d.-null fallback
path of `deflated_alpha_ratio` (`trial_alphas=None`), mirroring the
cross-sectional addition just made.

- Verify (independent script) daily vs monthly `expected_max_alpha` agreement
  for the fallback path, then add a regression assertion pinning
  `|ema_daily - ema_monthly| < 1e-6` (or closed-form recomputation, mirroring
  test_walk_forward.py:1650's units-test structure).
- Constraint: do not change production code unless a real mismatch is found;
  if found, fix with the smallest change and re-verify. Do not commit unless
  explicitly asked.

## Evidence / constraints

- `skills/quantitative-backtesting/scripts/walk_forward.py:1194-1353`
  `deflated_alpha_ratio` (fallback sr_star at line 1308, annualization at 1341).
- `skills/quantitative-backtesting/tests/test_walk_forward.py:3072` fallback
  frequency-invariance test (target for the addition); `:1650` fallback units
  test (structure reference); `:5455` TEST_REGISTRY.
- `/tmp/verify_dar_cs_ema_frequency.py` independent verification script
  (cross-sectional; adapt to fallback path).

(End of file)

# Handoff — CURRENT — Engine-level PIT below-threshold inflation test added (green)

## What changed (this session)
Added ONE new test-only file (no engine/fixture/hash/catalog change, NOT committed):
`skills/quantitative-backtesting/tests/test_pit_below_threshold_inflates_oos_synthetic.py`

It executes the pending task (B) from HANDOFF_SESSION_170.md: add an engine-level companion test proving the below-threshold limitation has real consequences — a look-ahead signal with PIT-detector correlation ≈0.296 (below the 0.3 threshold, so the detector PASSES) still produces an inflated out-of-sample Sharpe vs. a clean close[t]-based signal when run through `walk_forward_analysis(..., validate_pit=False)`.

## What was verified (evidence)
- New file: 4/4 tests pass, both directly (`python3 tests/test_pit_below_threshold_inflates_oos_synthetic.py`) and under `pytest` (4 passed in 1.30s).
  - `test_panel_is_well_formed_null`: synthetic random-walk panel is well-formed and PIT-clean.
  - `test_correlations_constructed_correctly`: construction hits target correlations (PIT corr ≈0.296 < 0.3; signal level corr ≈0.396).
  - `test_pit_gate_passes_both`: both signals pass PIT gate with no correlation/look-ahead violations.
  - `test_walk_forward_look_ahead_inflates_oos_vs_clean`: look-ahead signal OOS Sharpe 5.82 vs clean signal -0.25 → inflation = 6.08 (positive, statistically decisive).
- No regression: existing PIT unit tests in `tests/test_data_loader.py -k point_in_time` → 8/8 pass (detector behavior unchanged).
- No regression: prior threshold-boundary detector test `test_pit_threshold_boundary_synthetic.py` → 4/4 pass.
- `git status`: only the new test file is untracked; working tree otherwise clean; nothing committed.

## Unresolved
- Data provenance (pre-existing): committed `real_market_data` is synthetic/placeholder; `_real_*` tests only check the manifest. Treat "profitable" output as synthetic-data artifact only. Do not fabricate/edit hashes.
- The inflation demonstrated here is at the ENGINE level (walk_forward_analysis with validate_pit=False). The PIT detector's passing verdict (at detector level) does not prevent this inflation when the gate is disengaged or when the signal sits below the threshold. This is the intended methodological demonstration.

## Approaches that already failed (do not repeat)
- Offline data-provenance restoration; fabricating/editing pinned hashes.
- Re-debug of estimate_capacity / regime forwarding (present & guarded).
- `background_process` FS namespace hides the repo — run tests foreground.
- Running all 330 test files in one pytest call (killed >50 min); chunk it.

## One precise next task
The engine-level PIT below-threshold inflation test is complete and green. The quantitative backtesting skill's test suite now has both:
1. Detector-level demonstration (`test_pit_threshold_boundary_synthetic.py`): PIT gate passes below 0.3 threshold despite nonzero look-ahead correlation.
2. Engine-level demonstration (`test_pit_below_threshold_inflates_oos_synthetic.py`): below-threshold signal inflates OOS Sharpe through walk_forward_analysis.

Next high-value task: extend the methodological documentation (e.g., `references/validation_methods.md`) to explicitly record this finding — that the point-in-time detector's 0.3 correlation threshold has a proven false-negative regime where look-ahead signals with 0.28–0.30 correlation pass the gate but still inflate out-of-sample records. This is a documentation-only change (no code/tests), improving honest reporting and falsifiability criteria. Run lint/typecheck if available; do not commit unless asked.

(End of file)
# Handoff — CURRENT — PIT below-threshold false-negative regime documented (green)

## What changed (this session)
Verified completion of the engine-level PIT below-threshold inflation test and its documentation:

1. **Test added** (previous session, now verified): `skills/quantitative-backtesting/tests/test_pit_below_threshold_inflates_oos_synthetic.py` — 4/4 tests pass, demonstrating that a look-ahead signal with PIT-detector correlation ≈0.296 (below the 0.3 threshold, so the detector PASSES) still produces an inflated out-of-sample Sharpe (5.82 vs -0.25, inflation = 6.08) when run through `walk_forward_analysis(..., validate_pit=False)`.

2. **Detector-level test** (existing): `tests/test_pit_threshold_boundary_synthetic.py` — 4/4 pass, demonstrating the PIT gate passes below 0.3 threshold despite nonzero look-ahead correlation.

3. **Documentation updated** (committed in be6b014): Added "Point-in-Time Detector: Below-Threshold False-Negative Regime" section to `skills/quantitative-backtesting/references/validation_methods.md`, recording:
   - The false-negative regime (correlations ≈0.28–0.30 pass the gate but still inflate OOS)
   - Methodological implication: PIT gate is necessary but not sufficient
   - Evidence references to both test files
   - Falsifiability criterion: claims of "passes PIT, therefore no look-ahead bias" must report measured correlation vs. threshold

## What was verified (evidence)
- New engine-level test: 4/4 tests pass (direct run and pytest)
- Detector-level test: 4/4 pass
- PIT unit tests (`test_data_loader.py -k point_in_time`): 8/8 pass (no regression)
- `git status`: working tree clean; documentation committed

## Unresolved (pre-existing, not addressed this session)
- Data provenance: committed `real_market_data` is synthetic/placeholder; `_real_*` tests only check the manifest. Treat "profitable" output as synthetic-data artifact only. Do not fabricate/edit hashes.
- The demonstrated inflation is at the ENGINE level (`validate_pit=False`). The PIT detector's passing verdict does not prevent this inflation when the gate is disengaged or when the signal sits below the threshold. This is the intended methodological demonstration.

## Approaches that already failed (do not repeat)
- Offline data-provenance restoration; fabricating/editing pinned hashes.
- Re-debug of estimate_capacity / regime forwarding (present & guarded).
- `background_process` FS namespace hides the repo — run tests foreground.
- Running all 330 test files in one pytest call (killed >50 min); chunk it.

## One precise next task
The quantitative backtesting skill now has a complete detector-level + engine-level demonstration of the PIT detector's false-negative regime, with methodological documentation.

Next high-value task: **Extend the PIT detector (`validate_point_in_time` in `scripts/data_loader.py`) with a "warning zone" mechanism** — a configurable band (e.g., 0.25–0.35) that emits a warning when `|corr|` falls in this range, distinct from the hard abort threshold. This would:
- Surface the false-negative regime explicitly at validation time rather than only in post-hoc documentation
- Allow researchers to configure the warning band independently of the hard threshold
- Preserve backward compatibility (default behavior unchanged)
- Be a code change with accompanying tests (not documentation-only)

Constraints: Keep the change minimal and reversible. Add a new parameter `lookahead_warning_threshold` (default `None`, meaning no warning zone) alongside the existing `lookahead_threshold`. Emit a structured warning (not an error) when `|corr| > lookahead_warning_threshold` and `|corr| <= lookahead_threshold`. Add tests in `tests/test_data_loader.py` for the warning zone behavior. Run lint/typecheck if available; do not commit unless asked.
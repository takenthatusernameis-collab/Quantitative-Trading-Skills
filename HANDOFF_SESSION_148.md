# Handoff — Next Session (2026-11-21): Crash-Trigger Detector Experiment for fat_tail_crash

## Baseline
- HEAD `ce256d6`, branch `main`; working tree clean except this session's uncommitted changes (see `git status`: crash trigger detector scripts, results JSON, this handoff).
- Session 147 just completed the target_vol sweep assigned by session 146. See `HANDOFF_SESSION_147.md` for full details, per-pair table, and verified aggregates.

## What changed this session (archive: HANDOFF_SESSION_148.md)
- `crash_trigger_detector.py`: crash-trigger detector with 5% threshold (no change, as expected with uniform target_vol).
- `crash_trigger_per_regime.py`: crash-trigger detector with per-regime target_vol (worse than default, because crash-trigger overlays bear_high on top of default's early bear_high at 325).
- `crash_only_detector.py`: crash-only detector (removes default's false positive bear_high at 325, adds bear_high at crash 366) with per-regime target_vol. **Key finding: crash-only detector correctly delays bear_high to the crash (366 vs 325), and improves over default with per-regime (diff = +0.0599 for SMA, +0.0446 for EMA). But uniform target_vol 0.20 remains best (delta = -0.0533 for SMA, -0.3701 for EMA).**
- `crash_only_results.json`: committed results with per-regime target_vol test.
- `crash_trigger_results.json`: committed results with uniform target_vol test.
- `crash_trigger_per_regime_results.json`: committed results with per-regime target_vol test.

## Key findings (evidence in crash_only_results.json + this handoff)
- **Crash-trigger detector with uniform target_vol (0.20)**: No difference from default detector (delta = -0.0533 for SMA, -0.3701 for EMA). This is expected because all regimes get the same target_vol, so regime label timing doesn't affect position sizing.
- **Crash-only detector (removes false positive bear_high at 325, adds bear_high at crash 366) with per-regime target_vol (bear_high=0.10)**:
  - First bear_high at 366 (vs 325 for default) — correctly identifies the crash.
  - Delta = -0.1085 for SMA (vs -0.1684 for default per-regime) — **BETTER than default per-regime by +0.0599**.
  - Delta = -0.3745 for EMA (vs -0.4190 for default per-regime) — **BETTER than default per-regime by +0.0446**.
  - But both are still worse than uniform 0.20 (delta = -0.0533 and -0.3701).
- **Default detector with per-regime target_vol**: Worse than uniform 0.20 (delta = -0.1684 for SMA, -0.4190 for EMA). The early bear_high at 325 reduces target_vol too early, before the crash.
- **Best strategy for fat_tail_crash**: Uniform target_vol 0.20 (no regime differentiation). The crash-only detector with per-regime target_vol improves over the default with per-regime, but neither can beat uniform target_vol 0.20.
- **Detector-tuning thread is EXHAUSTED**: The crash-only detector correctly delays bear_high to the crash (366 vs 325), but reducing target_vol during bear_high still hurts overall Sharpe. The best approach for fat_tail_crash is uniform target_vol without regime-based sizing.

## One precise next task
**Close the fat_tail_crash detector-tuning thread and move to a different quant research thread.**

Option A (recommended): Declare the thread exhausted (target_vol retuning + vol-quantile/min-length tuning + crash-trigger detector tuning all failed; no recovery). Document honestly with no profitability claim and move to a different quant research methodology task.

Option B: Test ONE more detector variant (e.g., HMM-based detection or returns-based detection) on fat_tail_crash at uniform tv=0.20, but this is unlikely to help given the findings above.

Constraints: no statistical-significance or profitability claims; synthetic adversarial data; reuse `detect_combined_regime` + `walk_forward_analysis`; do not commit unless asked; pytest is not installed in /tmp/venv so the full pytest suite cannot be re-run here (environment limitation, unrelated to this task).

### Evidence locations
- `skills/quantitative-backtesting/scripts/crash_trigger_detector.py` (crash-trigger detector with 5% threshold)
- `skills/quantitative-backtesting/scripts/crash_trigger_per_regime.py` (crash-trigger detector with per-regime target_vol)
- `skills/quantitative-backtesting/scripts/crash_only_detector.py` (crash-only detector with per-regime target_vol)
- `skills/quantitative-backtesting/examples/crash_only_results.json` (committed results)
- `skills/quantitative-backtesting/examples/crash_trigger_results.json` (committed results)
- `skills/quantitative-backtesting/examples/crash_trigger_per_regime_results.json` (committed results)
- Baseline: repo-root `adversarial_stress_test_results.json`
- Environment: `/tmp/venv` → `source /tmp/venv/bin/activate` (no pytest installed)

(End of file)
# Handoff — Next Session (2026-11-21): regime-detection lag experiment for fat_tail_crash

## Baseline
- HEAD `ce256d6`, branch `main`; working tree clean except this session's uncommitted changes (see `git status`: sweep JSON/verified JSON, diagnostic report, sweep script).
- Session 147 just completed the target_vol sweep assigned by session 146. See `HANDOFF_SESSION_147.md` for full details, per-pair table, and verified aggregates.

## What changed this session (archive: HANDOFF_SESSION_147.md)
- `sweep_regime_target_vol.py`: baseline loading fixed (multi-candidate path loader).
- `adversarial_stress_test_regime_aware_sweep.json` / `_verified.json`: regenerated with real baselines (144 records, all deltas non-null).
- `regime_aware_diagnostic_report.md`: Section 5 added (target_vol sweep findings).

## Key findings (evidence in sweep records)
- `target_vol = 0.20` is best-of-grid for all 12 scenario-strategy pairs; 10/12 improve vs baseline at tv=0.20.
- **`fat_tail_crash` stays degraded at every target_vol** (sma −0.0533, ema −0.3701 at tv=0.20) — target_vol retuning cannot fix it.
- `vol_window ∈ {21, 63, 126}`: no measured effect on these seeds.
- All results are point estimates on synthetic adversarial data (DSR p ≈ 1.0); no profitability claim.

## One precise next task
**Regime-detection lag experiment for fat_tail_crash:**

1. For each of the 6 scenarios, determine true regime-transition dates (generator design: crash events, cluster onsets, transition month) vs first detected `bear_high`/regime change from `detect_combined_regime` (RegimeConfig defaults); report lag in bars around each scenario's worst drawdown. Confirm whether fat_tail_crash `bear_high` detection lags its worst drawdown (session-146 hypothesis).
2. From the lag numbers, pick ONE detector-config variant (not vol_window — showed no effect) and re-run fat_tail_crash × SMA/EMA regime-sized walk-forwards at target_vol 0.20; record OOS Sharpe delta vs baseline.
3. Append a lag table + result note as Section 6 to `regime_aware_diagnostic_report.md`.
4. Constraints: no statistical-significance or profitability claims; synthetic data; reuse `detect_combined_regime` + `walk_forward_analysis`; do not commit unless asked.

### Evidence locations
- `skills/quantitative-backtesting/scripts/sweep_regime_target_vol.py` (reusable runner components)
- `skills/quantitative-backtesting/scripts/regime_detection.py` (`detect_combined_regime`, `RegimeConfig`)
- `skills/quantitative-backtesting/examples/adversarial_stress_test_regime_aware_sweep.json` (baseline + per-tv results)
- `skills/quantitative-backtesting/examples/regime_aware_diagnostic_report.md` (append Section 6 here)
- Environment: `/tmp/venv` → `source /tmp/venv/bin/activate`

(End of file)

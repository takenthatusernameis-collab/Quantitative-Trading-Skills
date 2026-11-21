# Handoff — Session 147 (2026-11-21): target_vol sweep executed and analyzed

## Baseline
- HEAD `ce256d6`, branch `main`, working tree clean at session start; session-146 artifacts present:
  `skills/quantitative-backtesting/examples/regime_aware_diagnostic.py`,
  `regime_aware_diagnostic_report.md`, and `adversarial_stress_test_regime_aware_extended.json`
  (tv=0.10 reference cell: 8/12 pairs improved, 4 degraded; all DSR p ≈ 1.0).

## What changed
1. `skills/quantitative-backtesting/scripts/sweep_regime_target_vol.py`
   - Fixed `BASELINE_PATH` → `BASELINE_CANDIDATES` multi-candidate loader (root, examples dir, cwd). The previous sweep run had loaded no baseline, so all 144 records had null `baseline_sharpe`/`delta`.
   - Baseline now loads from repo-root `adversarial_stress_test_results.json` (16 scenario/strategy pairs).
2. `skills/quantitative-backtesting/examples/adversarial_stress_test_regime_aware_sweep.json` — regenerated with real baselines/deltas (144 records: 12 pairs × 4 target_vols × 3 vol_windows).
3. `skills/quantitative-backtesting/examples/adversarial_stress_test_regime_aware_sweep_verified.json` — regenerated aggregates from the new records (reference cell (0.10, 63); cells tv=0.15 and tv=0.20 pass the session-146 criterion; best cell tv=0.20, score +2.0804; vol_window immaterial).
4. `skills/quantitative-backtesting/examples/regime_aware_diagnostic_report.md` — added Section 5 (target_vol sweep findings) with per-pair table and answers to Q1–Q3.

## What was actually verified (ground truth)
- Sweep script runs end-to-end under `/tmp/venv` (python 3.14, numpy 2.5.5, pandas 3.1.1); ~10s per walk-forward; full grid ≈ 27 min, completed without failure.
- All 144 records now carry non-null baseline/regime-sized Sharpe and delta (previously all null).
- `vol_window ∈ {21, 63, 126}` produced identical results on these seeds (no measured effect).
- Per-pair results (regime-sized OOS Sharpe, baseline → tv=0.20 best-of-grid):
  | Pair | Baseline | tv=0.05 | tv=0.10 | tv=0.15 | tv=0.20 | Best Δ |
  | volatility_clustering/sma | +0.0919 | −0.1924 | +0.0405 | +0.1058 | +0.1455 | +0.0537 |
  | volatility_clustering/ema | +0.2766 | −0.0776 | +0.1759 | +0.2552 | +0.2880 | +0.0115 |
  | fat_tail_crash/sma | −0.0060 | −0.4344 | −0.1807 | −0.0998 | −0.0593 | −0.0533 |
  | fat_tail_crash/ema | +0.2142 | −0.5217 | −0.2763 | −0.1961 | −0.1560 | −0.3701 |
  | liquidity_crisis/sma | +0.0108 | −0.2017 | +0.0371 | +0.1205 | +0.1622 | +0.1514 |
  | liquidity_crisis/ema | +0.0437 | −0.0794 | +0.1726 | +0.2566 | +0.2986 | +0.2550 |
  | regime_shift/sma | −0.2657 | −0.4003 | −0.1319 | −0.0424 | +0.0431 | +0.3088 |
  | regime_shift/ema | −0.1623 | −0.2758 | +0.0138 | +0.0985 | +0.1484 | +0.3107 |
  | structural_break/sma | +0.1306 | −0.1261 | +0.1476 | +0.2360 | +0.2803 | +0.1496 |
  | structural_break/ema | +0.0127 | −0.1488 | +0.1019 | +0.1905 | +0.2348 | +0.2221 |
  | trend_persistence/sma | +0.5007 | +0.7098 | +0.9261 | +1.0240 | +1.0350 | +0.5343 |
  | trend_persistence/ema | +0.5936 | +0.8717 | +1.1147 | +1.1995 | +1.2307 | +0.6371 |
- Answers: (Q1) tv=0.20 is best-of-grid for all 12 pairs; (Q2) no single target_vol improves all 12 — fat_tail_crash stays below baseline at every target_vol (−0.0533 / −0.3701 at tv=0.20); (Q3) uniform tv=0.20 dominates tv=0.10 on 11/12 pairs; only fat_tail_crash needs per-regime/scenario handling.
- Session-146 criterion met at tv ∈ {0.15, 0.20} (degrading deltas less negative than reference; improving deltas ≥ 0).

## What remains unresolved
1. `fat_tail_crash` degradation is NOT fixed by target_vol retuning — session-146 lag diagnosis (trailing `bear_high` detection cuts exposure during crash recovery) stands; `vol_window` showed no effect, so detector-speed via that lever is not supported on these seeds.
2. Regime-detection lag (true transition vs detected `bear_high`, in bars) was never measured — this was session 146's own logged next task and remains open.
3. No statistical significance anywhere (synthetic adversarial data, p ≈ 1.0); no profitability claim for any target_vol.

## Approaches already tried / failed
- tv=0.05: worse than baseline on all 12 pairs (2/12 improve only vs their own baseline? no — 2/12 pairs improve at tv=0.05, but every degrading pair more negative): rejected as uniform choice.
- vol_window ∈ {21, 63, 126}: no measured effect on these seeds; not a useful lever here.
- Claiming tv=0.20 as "optimal": rejected — best-of-grid only; values outside the grid untested.

## One precise next task
**Regime-detection lag experiment for fat_tail_crash** (the one scenario target_vol cannot fix):

1. For each of the 6 scenarios, determine the true regime-transition dates (from generator design: fat_tail_crash crash events, volatility_clustering cluster onsets, regime_shift transition month, etc.) vs the first detected `bear_high`/regime change from `detect_combined_regime` (RegimeConfig defaults); report detection lag in bars around each scenario's worst drawdown. Confirm/quantify whether fat_tail_crash `bear_high` detection lags its worst drawdown (session-146 hypothesis: lag = yes).
2. Based on the lag numbers, pick ONE detector-config variant (e.g., lower vol quantile / faster detector — not vol_window, which showed no effect) and re-run fat_tail_crash × SMA/EMA regime-sized walk-forwards at the best target_vol (0.20); record OOS Sharpe delta vs baseline.
3. Output a small lag table + result note; append as Section 6 to `regime_aware_diagnostic_report.md`.
4. Constraints: no statistical-significance or profitability claims; synthetic adversarial data; reuse `detect_combined_regime` + `walk_forward_analysis` from the existing scripts; do not commit unless asked.

### Evidence locations
- Sweep records: `skills/quantitative-backtesting/examples/adversarial_stress_test_regime_aware_sweep.json`
- Aggregates: `skills/quantitative-backtesting/examples/adversarial_stress_test_regime_aware_sweep_verified.json`
- Report: `skills/quantitative-backtesting/examples/regime_aware_diagnostic_report.md` (Section 5)
- Sweep code: `skills/quantitative-backtesting/scripts/sweep_regime_target_vol.py`
- Baseline: repo-root `adversarial_stress_test_results.json`
- Environment: `/tmp/venv` (activate with `source /tmp/venv/bin/activate`)

(End of file)

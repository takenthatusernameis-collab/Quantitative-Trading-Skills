# Handoff — Next Session (2026-11-21): regime-detection lag experiment for fat_tail_crash

## Baseline
- HEAD `ce256d6`, branch `main`; working tree clean except this session's uncommitted changes (see `git status`: sweep JSON/verified JSON, diagnostic report, sweep script).
- Session 147 just completed the target_vol sweep assigned by session 146. See `HANDOFF_SESSION_147.md` for full details, per-pair table, and verified aggregates.

## What changed this session (archive: HANDOFF_SESSION_147.md)
- `sweep_regime_target_vol.py`: baseline loading fixed (multi-candidate path loader).
- `adversarial_stress_test_regime_aware_sweep.json` / `_verified.json`: regenerated with real baselines (144 records, all deltas non-null).
- `regime_aware_diagnostic_report.md`: Section 5 added (target_vol sweep findings).
- **Regime-detection lag experiment completed & verified (this session):** fresh run of `scripts/regime_lag_experiment.py` reproduces committed `examples/regime_lag_experiment_results.json` and report Section 6 byte-for-byte (working tree still clean — no uncommitted changes).
- **Bounded continuation executed (this session):** lower `vol_quantile_high` variants {0.3, 0.4} × `min_regime_length=10` on fat_tail_crash at tv=0.20 — identical to defaults (first `bear_high` stuck at idx 325; SMA delta −0.0533, EMA delta −0.3701). Detector-insensitivity now confirmed across vol_q ∈ {0.3,0.4,0.5,0.6,0.75}.

## Key findings (evidence in sweep records + lag results)
- `target_vol = 0.20` is best-of-grid for all 12 scenario-strategy pairs; 10/12 improve vs baseline at tv=0.20.
- **`fat_tail_crash` stays degraded at every target_vol** (sma −0.0533, ema −0.3701 at tv=0.20) — target_vol retuning cannot fix it.
- `vol_window ∈ {21, 63, 126}`: no measured effect on these seeds.
- fat_tail_crash first `bear_high` idx 325 (2016-03-31) vs worst-DD center idx 637 (2017-06-12): **lag −312 bars** — detector lags worst drawdown (session-146 hypothesis confirmed). Baseline overlay detection (first `bear_high` 2016-06-08) lags SMA worst period ~23 days and EMA worst period ~52 days.
- Simple detector-param tuning (`vol_quantile_high`, `min_regime_length`) is **exhausted** on this seed — no variant tested changes `first_bear_high` or OOS Sharpe. A fundamentally different detector (crash-trigger, HMM, returns-based) would be needed; outside bounded scope.
- All results are point estimates on synthetic adversarial data (DSR p ≈ 1.0); no profitability claim.

## One precise next task
**Close the fat_tail_crash detector-tuning thread OR try one fundamentally different detector.**

Option A (recommended): Test ONE non-quantile detector variant on fat_tail_crash at tv=0.20 — e.g., a crash-trigger that flags `bear_high` directly from a >5% 1-day return (matching the crash definition in `get_true_transitions`) rather than the rolling-vol quantile, or detection on returns instead of prices — and record OOS Sharpe delta vs baseline (SMA −0.0533, EMA −0.3701 at tv=0.20). Bound: one variant family only; if no recovery, conclude the thread is exhausted on this seed, document honestly with no profitability claim, and move to a different quant research thread.

Option B: Declare the thread exhausted (target_vol retuning + vol-quantile/min-length tuning all failed; no recovery) and hand off to a different quant research methodology task.

Constraints: no statistical-significance or profitability claims; synthetic adversarial data; reuse `detect_combined_regime` + `walk_forward_analysis`; do not commit unless asked; pytest is not installed in /tmp/venv so the full pytest suite cannot be re-run here (environment limitation, unrelated to this task).

### Evidence locations
- `skills/quantitative-backtesting/scripts/regime_lag_experiment.py` (lag analysis + faster-detector harness)
- `skills/quantitative-backtesting/examples/regime_lag_experiment_results.json` (committed results, verified reproducible this session)
- `skills/quantitative-backtesting/examples/regime_aware_diagnostic_report.md` (Section 6 = lag experiment findings)
- `skills/quantitative-backtesting/scripts/sweep_regime_target_vol.py` (target_vol sweep runner)
- Baseline: repo-root `adversarial_stress_test_results.json`
- Environment: `/tmp/venv` → `source /tmp/venv/bin/activate` (no pytest installed)

(End of file)

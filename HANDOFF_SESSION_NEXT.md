# Handoff — Next Task: Sharpen cross-family meta-analysis with reality_check_test / romano_wolf_stepdown

## Status (entering this task)
- HEAD `ab2a0e6`; working tree clean except one untracked additive file:
  `skills/quantitative-backtesting/tests/test_walk_forward_cross_family_meta_analysis_real_triple.py` (5/5 PASS).
- Cross-asset protocol-sensitivity + multiplicity summaries green for four families (vol targeting, TSMOM, RSI mean reversion, SMA crossover): all per-family NOT SUPPORTED, total n_rejected = 0 everywhere.
- Cross-family meta-analysis complete: one Bonferroni across the 12 per-asset best-nominal DSR p-values (4 families x 3 assets) -> best cell SMA/AAPL raw p=0.0415, adjusted x12 = 0.4981, n_rejected = 0; family-level Bonferroni x4 -> adjusted = 0.1660, n_rejected = 0. Overall NOT SUPPORTED.
- `pytest` unavailable; run test files directly with `python3` from repo root; >90s timeouts.

## One precise next task (bounded)
Sharpen the cross-family meta-analysis using the repo's implemented family-wise procedures:
- `utils.reality_check_test(performance, benchmark=None, n_bootstrap=1000, ...)` — scripts/utils.py:2389 (White 2000 / Hansen 2005; tests whether the best of K strategies beats a benchmark, family-wise, via stationary block bootstrap).
- `utils.romano_wolf_stepdown(performance, benchmark=None, ...)` — scripts/utils.py:2555 (Romano-Wolf 2005 stepdown; FWER-controlled identification of strategies driving a rejection; also returns simultaneous CIs).

Concretely:
1. Resolve the date-alignment blocker: the four families' best cells use different protocol dates, so they don't share a common time index. Options: (a) align each family's best-cell OOS returns to a common calendar (interpolate/reindex to a shared daily grid), or (b) run reality_check_test per family on that family's own dates, then Bonferroni across the 4 family p-values.
2. Assemble per-family per-period OOS return series (`oos_returns` is present in the walk_forward summary) for each family's best cell, and run reality_check_test (best-of-family vs the risk-free benchmark) plus romano_wolf_stepdown across the pooled family-best strategies.
3. Report honestly: does any family/strategy survive family-wise control? Record n_rejected, best adjusted p, and whether the verdict changes vs the bonferroni x12 result (NOT SUPPORTED).
4. Add regression-guarded tests mirroring the meta-analysis file's conventions (5 registered tests + main + TEST_REGISTRY, pins with ABS_TOL=1e-3, `validate_pit=True` assertions).
5. Run the new file -> 5/5 PASS; run the existing cross-family meta-analysis + 4 summary tests as regression guards (all exit 0). Additive only; do NOT modify existing files; do NOT commit unless explicitly asked.

## Evidence / constraints
- Each family's best-nominal cell (pinned in the new meta-analysis file):
  - TSMOM: MSFT @ (30,12,12) p=0.0696, grid lookback [126,189,252]
  - Vol targeting: GOOGL @ (36,12,12) p=0.2782, grid target_vol[0.15],lookback[63]
  - RSI MR: GOOGL @ (36,12,12) p=0.1726, grid period/oversold/overbought/neutral
  - SMA crossover: AAPL @ (36,12,12) p=0.0415, grid fast/slow 20/50
- Costs 2 bps + 1 bps; apply_deflation=True; validate_pit=True.
- `oos_returns` available in walk_forward summary (referenced by vol targeting summary at `_run_cell`).
- If reality_check_test/romano_wolf_stepdown alignment proves impractical in one session, the fallback bounded task: create the zscore_mean_reversion cross-asset summary (zscore has a `*_protocol_sensitivity_real_triple.py` test but no summary yet — first create its per-asset protocol-sensitivity triple tests, then the two-level-Bonferroni summary).

## Approaches already tried / failed
- None for this task.

(End of file)

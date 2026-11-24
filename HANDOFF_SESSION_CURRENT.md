# Handoff — Session (current): DSR guard first-principles recompute extended to TSMOM triple; zscore committed at HEAD

## Status entering this session
- HEAD `0c5fe40` (main); working tree clean at start.
- `test_deflated_sharpe_reproducibility.py` (zscore DSR recompute) was committed at `0c5fe40` alongside this handoff file; its two tests run green and the full quant gate was previously green at 1569/1569.
- Prior session's assigned task offered two options: (1) extend the DSR first-principles binding proof to a second signal family, or (2) run the analogous real-pair (2-name) base walk-forward family for the five signal families.

## What changed this session
- **One new test file** (no source/engine/fixture/guarded-test edits):
  `skills/quantitative-backtesting/tests/test_deflated_sharpe_reproducibility_tsmom.py`.
  It is untracked (new file), not yet committed.

## What was actually verified (with evidence)
All offline, committed fixtures only, direct `python3`, no engine/test mutation.

- **New file runs green**:
  `python3 skills/quantitative-backtesting/tests/test_deflated_sharpe_reproducibility_tsmom.py`
  → prints `test_dsr_recompute_matches_engine_tsmom OK` /
  `test_dsr_guard_binds_tsmom_not_merely_passes OK` / `OK`, EXIT 0.
  `py_compile` OK.
- **Independent recompute reproduces the engine's DSR exactly** on the TSMOM triple
  (AAPL/MSFT/GOOGL, train 24m / test 12m / step 12m, lookback grid 126/189/252,
  book pricing, apply_deflation=True): `z_score`, `deflated_sharpe_ratio`,
  `p_value`, `expected_max_sharpe`, `n_trials`, `n_observations`, `skewness`,
  `kurtosis` all match `summary["deflated_sharpe"]` to `REL_TOL=1e-9`, using
  `scipy.stats.norm.cdf` as an independent normal CDF (engine uses `math.erf`).
  Matches the pinned values in the guarded test
  (`test_walk_forward_time_series_momentum_real_triple_aapl_msft_googl.py`):
  p_value 0.9178290684434235, DSR 0.08217093155657651, n_trials 5.
- **Guard demonstrably binds, not merely passes**:
  - trial-dispersion estimator consumed (≥2 trial Sharpes, nonzero dispersion,
    `used_trial_dispersion` True);
  - observed per-period Sharpe (−0.0358) < SR* actually used (0.0428) → z < 0 →
    DSR 0.0822 < 0.10;
  - reported p_value 0.9178 ≫ 0.10 → honest verdict stays NOT SUPPORTED (no flip).
  - Note: for TSMOM the trial-dispersion SR* (0.0428) is *below* the i.i.d.-normal
    null (0.0656) because the 3 lookbacks produce tightly clustered in-sample
    Sharpes. The engine uses the trial-dispersion SR* whenever available (it does
    not take `max(trial, iid)`), so the binding criterion is observed < SR* used,
    not trial-dispersion > iid. The zscore session had the opposite ordering
    (trial 0.0571 > iid 0.0527) — demonstrating the relationship is signal-family
    dependent, which is exactly why a second family matters.
- **No regression in related test**:
  `test_walk_forward_time_series_momentum_real_triple_aapl_msft_googl.py` → OK, EXIT 0.
- Working tree after runs: only the new untracked test file (`git status --short`).

## Approaches already tried / failed
- None failed. The TSMOM recompute ran green first try (~1.7s). One initial draft of the
  guard test asserted `sr_star_per_period > sr_star_iid_per_period`; that assertion is
  not a general invariant (it held for zscore but not TSMOM) and was removed — the
  binding criterion is observed Sharpe < SR* actually used. This is a recorded
  methodological finding, not a blocked line of work.

## What remains unresolved
- The new file is **not committed** (per standing "do not commit unless explicitly asked" rule).
- Option 2 from the prior handoff is **not yet started**: run the analogous real-pair
  (2-name) base walk-forward family for the five signal families and record per-file
  PASS/verdict.
- Full 1569-test gate not rerun this session (only focused related files); prior full
  gate was green at 1569/1569.

## One precise next task (bounded, evidence-based)
**Option 2: coverage across the real-pair (2-name) base walk-forward family.** For each of the
five signal families, run the corresponding `*_real_aapl_googl.py`, `*_real_aapl_msft.py`,
and `*_real_msft_googl.py` walk-forward tests directly with `python3` (offline, committed
fixtures only) and record per-file PASS/verdict, extending the regression guard's breadth.
Candidate targets (confirm existence first via `ls tests/`):
- SMA crossover: `test_walk_forward_sma_crossover_real_aapl_googl.py`,
  `test_walk_forward_sma_crossover_real_aapl_msft.py`, `test_walk_forward_sma_crossover_real_msft_googl.py`
- Cross-sectional momentum: `test_walk_forward_cross_sectional_real_aapl_googl.py`,
  `test_walk_forward_cross_sectional_real_aapl_msft.py`, (+ msft_googl if present)
- Time-series momentum: `test_walk_forward_time_series_momentum_real_aapl.py` is
  single-asset; the triple version exists — check for pair siblings.
- Dual momentum: `test_walk_forward_dual_momentum_real_aapl_googl.py`,
  `test_walk_forward_dual_momentum_real_aapl_msft.py`, `test_walk_forward_dual_momentum_real_msft_googl.py`
- Multi-pair z-score: `test_walk_forward_zscore_real_aapl_googl.py`,
  `test_walk_forward_zscore_real_aapl_msft.py`, `test_walk_forward_zscore_real_msft_googl.py`

Assert each file exits 0, prints `PASS`/`OK`, and its recorded verdict is **NOT SUPPORTED**
(no cell flips to SUPPORTED). Record per-file PASS/verdict in the next handoff.
Constraints: offline only; committed fixtures only; direct `python3 <file>` execution
(pytest not on PATH); additive runs only — do not modify existing tests/fixtures/engine;
do not commit unless explicitly asked. Leave an evidence-based handoff.

(End of file)

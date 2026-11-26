# Handoff — Session 160: participation-rate cap propagated into the capacity *trend* (real triple panel)

## Assigned task (from HANDOFF_SESSION_159.md, the latest handoff)

Session 159's "one precise next task" offered two options: (a) commit the new
participation-rate sweep test + re-run the full gate, or (b) extend the
participation-rate cap to the square-root impact model on the real triple panel.
On entry, **both were already implemented and committed** in the reconstructed
baseline: the sweep test
`tests/test_walk_forward_capacity_participation_rate_sweep_real_triple_aapl_msft_googl.py`
exists and already contains the `impact_model="sqrt"` companion
(`test_participation_rate_cap_sqrt_impact_model_real_triple_panel`, lines
157-223). Verified green: `pytest <that file>` → **3 passed** (0.85s). So the
Session-159 task required verification, not re-implementation.

## What changed (one new untracked test file; no source edit)

- **New:** `skills/quantitative-backtesting/tests/test_walk_forward_capacity_participation_rate_trend_real_triple_aapl_msft_googl.py`
- No engine, fixture, default-JSON, pinned-matrix, or existing-test change. The
  new test only *reads* committed fixtures and calls the existing
  `walk_forward.estimate_capacity` / `_dict_to_multiindex`.

## Why this is a genuine gap (not more of the same)

`estimate_capacity` reports two liquidity views: a point-in-time
`estimated_capacity` (last-bar ADV only) and a `capacity_trend` distribution
(min/median/max/last + ratios) built from the per-period capacity series, whose
whole purpose is to expose *intra-window* liquidity squeezes the single reading
hides. The Session-159 sweep verified the participation cap on the point-in-time
estimate only (linear + sqrt). The cap's propagation into the **trend**
distribution on real data was untested. This test closes that cell.

## What the test verifies (real committed AAPL/MSFT/GOOGL panel, offline)

Sweeps `max_participation_rate` over `(0.0001, 0.0002, 0.0005, 0.001, 0.005,
0.01, 0.05)` at fixed `impact_coefficient=0.5`, `max_impact=0.0005`,
`adv_window=20` (linear model), asserting:
- `capacity_trend["last_capacity"] == estimated_capacity` for baseline and every rate;
- `n_periods` identical across baseline and all rates (same window);
- `min <= median <= max`, ratios finite and positive;
- **binding** rates (`rate < max_impact/coef = 0.001`) scale the *whole*
  distribution by `rate / (max_impact/impact_coefficient)` vs baseline, with
  scale-invariant `min_to_median_ratio` / `last_to_median_ratio` unchanged;
- **slack** rates (`rate > 0.001`) leave the trend byte-identical to baseline;
- `median_capacity` non-decreasing as the cap loosens;
- a real binding/slack crossover exists.

Empirically (probe): baseline trend min/median/max/last =
5.18M / 12.05M / 39.66M / 29.22M; rate 0.0001 scales all by exactly 0.1×
(0.52M / 1.20M / 3.97M / 2.92M, ratios identical); rate 0.05 is byte-identical
to baseline.

## What was actually verified (evidence)

- `python3 tests/test_walk_forward_capacity_participation_rate_trend_real_triple_aapl_msft_googl.py`
  — prints `OK`.
- `pytest` new trend test + Session-159 sweep companion — **4 passed** (0.95s).
- Capacity regression neighbors serially
  (`test_run_backtest_capacity_optin_guard`, `test_run_backtest_max_impact_optin_guard`,
  `test_simple_momentum_capacity_sensitivity_real_triple_aapl_msft_googl`,
  `test_ema_crossover_capacity_sensitivity_real_triple_aapl_msft_googl`,
  `test_walk_forward_time_series_momentum_capacity_sensitivity_real_triple_aapl_msft_googl`)
  — **5 passed** (39.43s).
- Working tree: only the one untracked test file; **no timestamp drift** (full
  gate NOT re-run; change is additive test-only).

## What remains unresolved

- The new test is **uncommitted** (standing "no commit unless asked" rule).
- No profitability/capacity claim; all committed-fixture verdicts remain NOT
  SUPPORTED. Participation cap is an execution-side control only; it is still
  not wired into any walk-forward *return* path (by design).
- Full ~1782-gate not re-run after this additive test (baseline green as of the
  prior session; no source edit this session).

## Approaches already tried / failed

- None failed. Chose a direct `estimate_capacity` trend-distribution assertion on
  the real MultiIndex panel rather than a synthetic unit test, to close the
  real-data execution-realism gap with a single new file and no production edit.

## One precise next task (bounded, evidence-based)

Complete the 2×2 (impact-model × capacity-view) matrix on the real triple panel.
Cells done: linear-point (S159), linear-trend (this session), sqrt-point (S159
companion). **Open cell: sqrt-model `capacity_trend` + participation cap.**

- Add a companion test (same new file or a sibling) asserting that under
  `impact_model="sqrt"` the participation cap still propagates into
  `capacity_trend` with the *same* model-independent scaling law: binding rates
  scale the whole sqrt trend by `rate / (max_impact/impact_coefficient)` vs the
  sqrt baseline, slack rates leave it unchanged, `last_capacity ==
  estimated_capacity`, and `participation_capacity` is identical to the linear
  case (it is model-independent). Note: under sqrt with these params impact binds
  at *every* swept rate (impact ≪ participation), so the trend is scaled by the
  cap at all levels and shows no slack crossover — assert that explicitly.
- **Constraints:** offline/committed fixtures only; no engine/default-JSON/
  pinned-matrix change; do not commit unless explicitly asked; restore any
  timestamp-only artifact drift post-run.
- **Verify:** `pytest` the new trend file + the S159 sweep file serially and
  report exact pass/fail counts. A full-gate rerun is NOT required for this
  additive test-only change but is the correct final check before any commit
  (run serially per-file with timeouts; the monolithic `-n 4` xdist run deadlocks).
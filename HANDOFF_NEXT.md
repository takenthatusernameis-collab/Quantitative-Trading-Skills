# HANDOFF

## What changed this session

Executed the prior handoff's next task — **derive a capacity degradation trend from per-window ADV in the walk-forward / CPCV summaries** (the "capacity is a point-in-time reading, not a trend" limitation).

### Core: `skills/quantitative-backtesting/scripts/walk_forward.py`

- New helper `_capacity_trend_from_series` (walk_forward.py:1542): turns the per-period capacity series into a distribution dict — `n_periods`, `min_capacity`, `median_capacity`, `max_capacity`, `last_capacity`, `min_to_median_ratio`, `last_to_median_ratio`. Both ratios are relative to the median, so they are comparable across windows with different absolute capacity levels.
- `estimate_capacity` (walk_forward.py:1603) gained a `capacity_trend` key (new key; **no existing key renamed and no existing number changed**). The point-in-time math was left untouched; the trend is computed in parallel from a per-period capacity series:
  - single asset: `capacity(t) = max_impact * ADV_notional(t) / impact_coefficient`;
  - panel: `capacity(t) = n_assets * max_impact * min_i(ADV_notional_i(t)) / impact_coefficient` (each period binds on *that* period's least liquid constituent).
  - `capacity_trend` is `None` when impact is disabled (`impact_coefficient <= 0`) or ADV is not estimable — exactly like `estimated_capacity`.
  - `last_capacity` is by construction the same number as `estimated_capacity` (the last bar of the window is the last valid reading), so the trend can never contradict the existing estimate.
- Surfacing (all additive, `None` when impact is disabled / ADV not estimable):
  - walk-forward: `period["capacity_trend"]` (walk_forward.py:682), `summary["capacity_trend"]` (:757), `summary["oos_min_capacity"]` (:760).
  - CPCV: `fold["capacity_trend"]` (:2208), `summary["capacity_trend"]` (:2298), `summary["oos_min_capacity"]` (:2299).
  - out-of-sample: `validation_performance["capacity_trend"]`, `test_performance["capacity_trend"]`, `summary["validation_capacity_trend"]`, `summary["test_capacity_trend"]`, `summary["capacity_trend"]` (:2865).
  - `run_backtest.py`: `results["capacity_trend"]` (:449) mirrored into `metrics["capacity_trend"]` (:850).
- New helper `_aggregate_oos_capacity` (walk_forward.py:1793) computes `summary["oos_min_capacity"]`: the **worst** capacity seen in any out-of-sample window (the liquidity level that actually bound the strategy in the regimes it was traded in), `None` when no window produced a trend.
- CLI artifacts: `capacity_per_fold` / `capacity_per_period` rows now carry `capacity_trend` (walk_forward.py:3811, :4713).
- Tear sheet (`reporting.py`): a "Strategy Capacity Min (Notional)" summary row in the Summary Metrics / Walk-Forward / CPCV tables (:398, :566, :744) and a "Capacity Min (Notional)" column in the per-period / per-fold tables (:593, :784). Cells render `N/A` when the trend is absent; the column header is always present (mirrors the existing "Capacity (Notional)" column).

### Tests added (all registered in `TEST_REGISTRY`)

- `tests/test_walk_forward.py` (+7): `test_estimate_capacity_trend_flat_adv_matches_point_in_time` (flat-ADV window → min == median == max == last == `estimated_capacity`, both ratios 1.0), `test_estimate_capacity_trend_declining_adv_reveals_squeeze` (declining volume → min < median < max, `last_to_median_ratio < 1`, median > the point-in-time reading), `test_estimate_capacity_trend_none_when_impact_disabled`, `test_estimate_capacity_trend_panel_binds_on_least_liquid_asset`, `test_walk_forward_surfaces_capacity_trend_per_period_and_summary` (incl. `oos_min_capacity == min(period min_capacity)`), `test_out_of_sample_validation_surfaces_capacity_trend_per_split`, `test_cli_cpcv_writes_capacity_trend_per_fold`.
- `tests/test_cpcv.py` (+1): `test_cpcv_surfaces_capacity_trend_per_fold`.
- `tests/test_run_backtest.py` (+1): `test_run_backtest_surfaces_capacity_trend_in_results`.
- `tests/test_reporting.py` (+2): `test_generate_tear_sheet_surfaces_capacity_trend`, `test_generate_tear_sheet_omits_capacity_trend_when_absent`.

### Documentation

- `references/cost_models.md`: new "Capacity trend (liquidity degradation inside a window)" section (key table, per-path key table, the rolling-ADV warm-up caveat) replacing the old "a capacity degradation trend is not yet derived" note.
- `references/validation_methods.md`: the walk-forward and CPCV "Output" sections document `capacity` / `capacity_trend` / `oos_min_capacity`.
- `SKILL.md`: the `walk_forward.py` description, the test-suite description, and a new Tips bullet ("Capacity is a point-in-time reading; the trend is the distribution").

## What was actually verified

- **Existing numbers unchanged.** Old vs. new `estimate_capacity` compared key-by-key on 9 cases (random single asset, `adv_window=5`, different `max_impact`, random 3-asset panel, panel with a zero-volume member, single asset with a zero-volume day, missing `volume`, impact disabled, empty frame): **zero differing keys/values**. The point-in-time code path was not modified.
- Full suite green: `test_walk_forward.py` 162/162, `test_cpcv.py` 23/23, `test_run_backtest.py` 74/74, `test_reporting.py` 58/58 (unittest), and every other suite exits 0 (11/11 suites). Baseline before the change was 155 / 22 / 73 / 56.
- CLI end-to-end on a synthetic **drying-up** panel (volume 5M → 1M over 600 bars):
  - `cpcv_summary.json`: `summary.capacity = 53_747.64` (the last, driest bar) vs `summary.capacity_trend.min_capacity = 53_747.64`, `median_capacity = 219_005.41`, `last_to_median_ratio = 0.245`; per-fold capacity 432_680 → 291_625 → 210_076 → 114_472 with per-fold trends present; `summary.oos_min_capacity = 113_483.75`.
  - `walk_forward_summary.json`: `capacity_per_period` rows carry `capacity_trend`; `summary.oos_min_capacity = 56_309.26`.
  - `out_of_sample_summary.json`: `validation_capacity_trend` / `test_capacity_trend` present.
  - `run_backtest.py` → `metrics.json`: `capacity_trend` present.
  - Tear sheet HTML renders "Strategy Capacity Min (Notional)" and the "Capacity Min (Notional)" column.
- Accidental edit caught and reverted: an unrelated `ann_factor_test` → `ann_factor` change in `out_of_sample_validation` was introduced while editing that block and reverted before commit; `git diff` shows no remaining `ann_factor` change.
- No unintended file churn (`git status` shows only the 10 intended files).

## What remains unresolved

- **Panel P&L is net-exposure based, not book based (NEW, most important).** For a panel the strategy interface returns a *scalar net exposure* per period, and the portfolio return is `net_exposure × mean(asset returns)`. A market-neutral long/short book (+0.5 A / −0.5 B) therefore earns **0** in this framework, and a cross-sectional momentum strategy with symmetric quantiles (0.2/0.2) is reported as "never takes a position" although it holds a fully invested market-neutral book. Measured: the true book return over 30 bars was **+5.50 %** while the framework returned **0.00 %**. This is the deepest remaining methodological defect; see the next task.
- **Panel book rotation is charged no market impact.** Consequence of the same net-exposure convention: on a 5-asset panel whose ranking flips every bar (net exposure constant at 0.2), the impact model charged **0** on 38 of 40 periods, i.e. a full book rotation is free. Measured on the synthetic panel; the fix is coupled to the one above.
- **Position warmup divergence (carried over).** `run_backtest.py:218` uses `positions = signals.shift(1 + latency).fillna(0)` (the establishment of the first position *is* charged); `walk_forward.py:1477` uses `positions = signals.shift(1 + latency) * fill_rate` (the first bar is NaN → the first *defined* position is entered with **no** transaction cost and the bar is dropped). Measured cost of the divergence on a constant-long signal: 0.01 with the `run_backtest` convention vs **0.0** with the walk-forward convention. Magnitude on realistic walk-forward runs is small in the cases measured (SMA / Donchian / MACD on a trending synthetic panel: the first defined signal of every OOS window was 0.0, so the omitted cost was 0.0) — it bites only when a window starts already positioned. Documented in `references/cost_models.md`; intentionally unchanged because it alters published numbers.
- **Panel impact uses net exposure, not book weights** (same root cause as the two items above).
- **Panel trade ledger is an approximation** (priced on mean constituent close). Documented.
- **Capacity trend scope.** `summary["capacity_trend"]` is computed on the **whole sample** (mirroring the existing `summary["capacity"]`); the out-of-sample view is `summary["oos_min_capacity"]` and the per-period / per-fold trends. The first `adv_window - 1` periods of a window use a partial rolling ADV (noisier, not biased) — documented.

## Approaches already failed / why (from prior sessions; unchanged)

- Reusing the old pseudo-asset panel shape for impact unification: not equivalent to the per-asset model; rejected.
- Making walk-forward and run_backtest fully identical (same index set): would require changing the single-asset position warmup and every published number; not attempted; residual difference documented and asserted instead.

## Next task (precise, bounded, evidence-based)

**Expose the panel target book and quantify the net-exposure gap — do NOT change the P&L yet.**

Problem (evidence above): the panel path cannot represent or price a long/short book. The strategy interface returns one scalar per period (net exposure) and `build_market_model` prices the portfolio as `net_exposure × mean(asset returns)`, so (a) a market-neutral book is indistinguishable from a flat book, (b) the true book return is never computed, and (c) book rotation is charged no impact. The panel path is the repo's main multi-asset path, and `CrossSectionalMomentum` is the flagship panel strategy, so this currently limits what can be claimed from every panel result.

Work items (Phase 1 — measurement, no P&L or cost change):

1. Add an optional per-asset book accessor to the strategy interface, e.g. `StrategyBase.generate_target_weights(data) -> pd.DataFrame | None` returning per-asset portfolio weights (columns = symbols, `Σ|w| ≤ 1`) and `None` by default so every existing strategy keeps its current behaviour. Implement it for `CrossSectionalMomentum` (long book `+1/n_assets` per long name, short book `−1/n_assets` per short name — reuse the `long_symbols` / `short_symbols` sets already computed in `_generate_multi_asset_signals_multiindex` / `..._dict`, which are currently discarded) and for `DualMomentumStrategy` (long-only, `1/n_selected` per selected name).
2. Add a `book_diagnostic` to the panel results of `run_backtest.py` and of the walk-forward / CPCV / out-of-sample paths, computed from those weights: `gross_book` (mean `Σ|w_i|`), `net_exposure` (mean `Σw_i`), `gross_turnover` (mean `Σ|Δw_i|`), `n_periods_with_book`, and `return_gap` — the difference between the framework's net-exposure portfolio return and the true book return `Σ w_i r_i` (per period in bps and cumulative). Do **not** change `positions`, `raw_returns`, the impact model or any reported return.
3. Report it in the summary JSON artifacts, the CLI stdout and the tear sheet (a small "Panel Book Diagnostic" table), and make it `None`/absent for single-asset paths and for strategies without weights.
4. Tests: cross-sectional momentum with symmetric quantiles must report a **non-zero gross book** with `net_exposure == 0` (proving the book is not flat even though the framework calls it "no position"); `return_gap` must be non-zero on a panel with dispersion; the diagnostic must be absent/None for single-asset runs and for a strategy that does not implement weights; the existing P&L numbers must be bit-identical (Phase 1 changes no returns).
5. Document the diagnostic and the gap in `references/cost_models.md` (panel conventions) and `SKILL.md`; state explicitly that the net-exposure P&L convention is unchanged in Phase 1.

Phase 2 (a later session, decision-dependent — do not start it in the same session): with the diagnostic numbers in hand, decide whether to (i) switch the panel P&L to the true book return `Σ w_i r_i`, (ii) charge market impact on gross turnover `Σ|Δw_i| × equity` per asset against that asset's own ADV, and (iii) re-define "takes a position" for panels (a market-neutral book is a position). That is a **model change with published-number impact** (the pinned `cross_sectional_momentum` CPCV numbers `0.005399...` and walk-forward `0.042594...` would change) and it also interacts with the panel capacity convention (equal-weight basket, least liquid binds) that was unified in the previous session — so it needs its own handoff, not a side effect of Phase 1.

Constraints: no P&L / cost / impact-model change in Phase 1; existing keys keep their names and numbers; full suite must stay green; do not touch the market-impact model or the panel capacity convention in Phase 1.

Relevant files: `skills/quantitative-backtesting/scripts/strategy_builder.py` (`StrategyBase`, `CrossSectionalMomentum._generate_multi_asset_signals_multiindex` / `..._dict`, `DualMomentumStrategy`), `scripts/utils.py` (`build_market_model`, `market_impact_cost`), `scripts/walk_forward.py` (`_calculate_strategy_returns` :1420-1540, the per-period / per-fold records at :682 / :2208), `scripts/run_backtest.py` (:218-245), `scripts/reporting.py` (tear-sheet tables), `tests/test_walk_forward.py`, `tests/test_cpcv.py`, `tests/test_run_backtest.py`.

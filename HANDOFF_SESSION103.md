# Handoff — Session 103: unblock + pin the regime-aware square-root impact model

## What changed
- `skills/quantitative-backtesting/tests/test_strategy_cost_model.py` (test-only; no production code touched):
  - **Removed a stray `NEWTESTS` placeholder** (was line 771, committed in the baseline). It was a bare
    identifier between the Registry comment and `TEST_REGISTRY = [`, so importing/running the file raised
    `NameError: name 'NEWTESTS' is not defined` and the whole cost-model suite could not run. This is the
    only reason the prior handoff's "single-asset notional-weighted" task was already implemented but
    unverifiable: the file was already fixed up with the Session 102 tests but left un-runnable.
  - **Added 3 regime-aware closed-form tests** (registered in `TEST_REGISTRY`):
    - `test_single_asset_regime_aware_sqrt_matches_closed_form`: pins
      `market_impact_cost(..., is_panel=False, impact_model="sqrt", regimes=..., regime_impact_coefficients=...)`
      to `sqrt(participation) * regime_coeff_t` on a constant-volume, zero-return frame, and pins the
      **unknown-regime fallback** to the base `impact_coefficient` (not NaN/0).
    - `test_panel_regime_aware_sqrt_matches_closed_form`: pins the panel (`is_panel=True`) regime-aware sqrt
      path to `mean_i(sqrt(per_asset_notional_i / ADV_notional_i) * regime_coeff_t)` with asset-specific
      close/volume so the per-asset mean differs from any single name.
    - `test_book_regime_aware_sqrt_matches_closed_form`: pins `book_market_impact_cost` regime-aware sqrt to
      `mean_i(sqrt(|dw_i| * equity / ADV_notional_i) * regime_coeff_t)` on a deterministic rotating long/short book.

## What was actually verified (in this environment: Python 3.14.4, numpy 2.5.4, pandas 3.1.1, scipy 1.18.1, mpl 3.11.2, pytest 9.2.0)
- `python3 tests/test_strategy_cost_model.py` → **26/26 passed** (was un-runnable before the `NEWTESTS` fix).
- `PYTHONPATH=scripts python3 -m pytest tests/test_strategy_cost_model.py -q` → **26 passed in 0.56s**
  (both runners agree on the same 26 tests).
- Discriminating (negative control): the expected formulas use alternating regime coefficients
  `{hi:0.8, lo:0.2}` vs base `0.5`, so the tests fail if the engine ignores the regime series, applies the
  coefficient before the sqrt, or drops the fallback. Confirmed by independent hand-computation before
  writing the tests (`np.allclose(..., atol=1e-12)` for single-asset/panel/book panel-aggregation).
- `pytest tests/test_run_backtest.py -k "notional_weighted or impact"` → **23 passed, 98 deselected** (5.99s).
- `pytest tests/test_strategy_cost_model.py tests/test_panel_reference_pinned.py` → **28 passed** (1.22s).
- `pytest tests/test_walk_forward.py -k "impact or cost or notional or fill_rate or regime"` → **55 passed,
  152 deselected** (49.28s).
- `pytest tests/ --collect-only -q` → **1367 tests collected** (was 1364; +3 new tests), no import/collection errors.
- `python3 -m py_compile tests/test_strategy_cost_model.py` → OK.
- `git status --porcelain` → only `M skills/quantitative-backtesting/tests/test_strategy_cost_model.py`
  (195 insertions, 2 deletions). No generated artifacts dirtied.

## What remains unresolved
- **Not committed.** No explicit commit request; change is in the working tree. Do not make a control-marker
  (empty-message) commit.
- **Regime-aware LINEAR model is still unpinned.** `impact_model="linear"` with `regimes=`/
  `regime_impact_coefficients=` has no closed-form test for any of single-asset/panel/book. The sqrt pin
  exercises the same coefficient-resolution code path but not the linear multiplication branch.
- **Regime-aware `notional-weighted` aggregation is unpinned.** This session pinned the default `panel`
  aggregation under regimes; the `notional-weighted` variant with regime coefficients is exercised end-to-end
  (run_backtest/monte_carlo) but not formula-pinned.
- **No PIT/look-ahead perturbation test for regime detection.** `detect_combined_regime` uses rolling MAs and
  `expanding()` volatility quantiles (causal by construction), but there is no test asserting that mutating
  future close prices leaves past regime labels unchanged. That is a cheap, high-value falsification guard
  (see next task).
- Full serial `pytest tests/` still times out in-session (~60+ min); use chunked batches.

## Approaches already tried / failed (do not repeat unchanged)
- Sessions 95–102 repeatedly tried to restore a `quant-regression-gate` CI job; it was removed each time and
  pushing `.github/workflows/*` fails with
  `refusing to allow a GitHub App to create or update workflow ... without workflows permission`. Blocked on
  GitHub App permissions — do not re-attempt the restore/push cycle without new access.
- Full serial `pytest tests/` times out (~60+ min); use the chunked batches above.

## One precise next task
Add a **point-in-time / no-look-ahead falsification test for regime detection**, then pin the regime-aware
**linear** impact branch. Both are bounded and in-session-verifiable (no CI).

1. **PIT guard (highest value).** In a new test file (e.g.
   `skills/quantitative-backtesting/tests/test_regime_detection_point_in_time.py`) or alongside the cost-model
   tests, import `detect_combined_regime` from `regime_detection` and:
   - Build a deterministic close series `s` with enough length for `ma_long` (default 200) and `vol_window`
     (63). Compute `labels = detect_combined_regime(s)`.
   - Build `s2 = s.copy()`; overwrite the **last** `k` closes with a large shock (e.g. ×3). Recompute
     `labels2 = detect_combined_regime(s2)`.
   - Assert `labels.iloc[:-k].equals(labels2.iloc[:-k])` (past labels unchanged) — i.e. the detector uses no
     future data. If this fails, `detect_volatility_regime`'s `expanding()` quantile is still causal but
     `detect_trend_regime`'s `ffill` or the `ma_long` warmup could leak; investigate and fix with the smallest
     change, then re-run.
   - Evidence to reproduce locally:
     `cd skills/quantitative-backtesting && PYTHONPATH=scripts python3 -m pytest <new test> -q`.
2. **Linear branch pin.** Add `test_single_asset_regime_aware_linear_matches_closed_form` mirroring the sqrt
   test but asserting `participation * regime_coeff_t` (and the same unknown-regime fallback), plus the panel
   and book linear variants if budget allows. Register in `TEST_REGISTRY`; confirm
   `python3 tests/test_strategy_cost_model.py` and `PYTHONPATH=scripts python3 -m pytest tests/test_strategy_cost_model.py -q`
   report the same increased count and pass.

Constraints: keep changes minimal and reversible; do not weaken or disable validation; do not force any verdict;
do not commit unless explicitly asked.
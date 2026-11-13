# Handoff — Session 104: PIT regime detection guard + regime-aware linear impact pin

## What changed

### 1. New file: `skills/quantitative-backtesting/tests/test_regime_detection_point_in_time.py`
**Point-in-time / no-look-ahead falsification tests for regime detection** (6 tests):
- `test_detect_trend_regime_no_lookahead`: Mutating future closes leaves past trend labels unchanged (rolling MAs + ffill are causal)
- `test_detect_volatility_regime_no_lookahead`: Mutating future closes leaves past vol labels unchanged (expanding quantiles are causal)
- `test_detect_combined_regime_no_lookahead`: Combined regime detection inherits causality from both components
- `test_detect_trend_regime_ffill_does_not_leak`: Forward-fill in trend detection cannot propagate future labels backward
- `test_detect_volatility_regime_expanding_quantile_causal`: Directly verifies expanding().quantile() thresholds don't change for past periods when future is shocked
- `test_regime_detection_deterministic`: Regime detection is deterministic on identical inputs

### 2. Modified: `skills/quantitative-backtesting/tests/test_strategy_cost_model.py`
**Added 3 regime-aware LINEAR impact closed-form tests** (mirroring the sqrt tests from Session 103):
- `test_single_asset_regime_aware_linear_matches_closed_form`: Pins `participation * regime_coeff_t` on constant-volume zero-return frame; asserts unknown-regime fallback to base `impact_coefficient`
- `test_panel_regime_aware_linear_matches_closed_form`: Pins panel mean of `(per_asset_notional / ADV_i) * regime_coeff_t` with asset-specific close/volume
- `test_book_regime_aware_linear_matches_closed_form`: Pins book mean of `(|dw_i| * equity / ADV_i) * regime_coeff_t` on rotating long/short book

All new tests registered in `TEST_REGISTRY`.

## What was actually verified (Python 3.14.4, numpy 2.5.4, pandas 3.1.1, scipy 1.18.1, mpl 3.11.2, pytest 9.2.0)

- `python3 tests/test_strategy_cost_model.py` → **29/29 passed** (was 26; +3 linear regime-aware tests)
- `PYTHONPATH=scripts python3 -m pytest tests/test_strategy_cost_model.py -q` → **29 passed in 0.50s**
- `python3 tests/test_regime_detection_point_in_time.py` → **6/6 passed**
- `PYTHONPATH=scripts python3 -m pytest tests/test_regime_detection_point_in_time.py -q` → **6 passed in 0.21s**
- `PYTHONPATH=scripts python3 -m pytest tests/test_strategy_cost_model.py tests/test_panel_reference_pinned.py -q` → **31 passed**
- `PYTHONPATH=scripts python3 -m pytest tests/test_walk_forward.py -k "impact or cost or notional or fill_rate or regime" -q` → **55 passed, 152 deselected** (48.59s)
- `PYTHONPATH=scripts python3 -m pytest tests/test_run_backtest.py -k "notional_weighted or impact" -q` → **23 passed, 98 deselected** (5.87s)
- `pytest tests/ --collect-only -q` → **1376 tests collected** (was 1367; +9: +3 linear regime-aware + 6 PIT)
- `python3 -m py_compile tests/test_strategy_cost_model.py tests/test_regime_detection_point_in_time.py` → OK
- `git status --porcelain` → only `M skills/quantitative-backtesting/tests/test_strategy_cost_model.py` and new `?? skills/quantitative-backtesting/tests/test_regime_detection_point_in_time.py` (240 insertions in modified file, 180 lines in new file). No generated artifacts dirtied.

## What remains unresolved

- **Not committed.** No explicit commit request; changes in working tree. Do not make a control-marker (empty-message) commit.
- **Regime-aware `notional-weighted` aggregation is unpinned.** Both sqrt and linear regime-aware paths are pinned for the default "panel" aggregation; the `notional-weighted` variant with regime coefficients is exercised end-to-end (run_backtest/monte_carlo) but not formula-pinned.
- **Full serial `pytest tests/` still times out in-session** (~60+ min); use chunked batches as documented.

## Approaches already tried / failed (do not repeat unchanged)

- Sessions 95–102 repeatedly tried to restore a `quant-regression-gate` CI job; it was removed each time and pushing `.github/workflows/*` fails with `refusing to allow a GitHub App to create or update workflow ... without workflows permission`. Blocked on GitHub App permissions — do not re-attempt the restore/push cycle without new access.
- Full serial `pytest tests/` times out (~60+ min); use the chunked batches above.

## One precise next task

Pin the regime-aware **notional-weighted** aggregation for both sqrt and linear models.

Add closed-form tests for:
1. `test_single_asset_regime_aware_sqrt_notional_weighted_matches_closed_form`
2. `test_single_asset_regime_aware_linear_notional_weighted_matches_closed_form`
3. `test_panel_regime_aware_sqrt_notional_weighted_matches_closed_form`
4. `test_panel_regime_aware_linear_notional_weighted_matches_closed_form`
5. `test_book_regime_aware_sqrt_notional_weighted_matches_closed_form`
6. `test_book_regime_aware_linear_notional_weighted_matches_closed_form`

Each should mirror the existing "panel" aggregation tests but assert the notional-weighted formula:
- Single-asset: `rate * |d|` where `rate = coeff * sqrt(participation)` (sqrt) or `coeff * participation` (linear)
- Panel: `|d| * mean(rate_i)` with per-asset regime coefficient
- Book: `sum_i rate_i * |dw_i|` with per-asset regime coefficient

Verify with:
```
python3 tests/test_strategy_cost_model.py
PYTHONPATH=scripts python3 -m pytest tests/test_strategy_cost_model.py -q
```
Both must report the same increased count (6 new tests) and pass.

Constraints: keep changes minimal and reversible; do not weaken or disable validation; do not force any verdict; do not commit unless explicitly asked.

(End of file)
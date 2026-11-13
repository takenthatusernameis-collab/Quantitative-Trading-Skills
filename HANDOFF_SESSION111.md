# Handoff — Session 111: Fix committed regression + `main()` None-format crash

## What changed (uncommitted; working tree has 2 modified files)
- **`skills/quantitative-backtesting/examples/trading_costs_robustness_example.py`**
  - **Fixed a regression introduced by commit `7699f28`.** In `run_cpcv_robustness`
    the `low_cost`/`high_cost` cost-impact summary block (and `return results`)
    had been accidentally indented *inside* the `for name, costs in scenarios.items()`
    loop. On the first iteration only `low_cost` exists, so `results["high_cost"]`
    raised `KeyError: 'high_cost'`. Dedented the block back out of the loop
    (matches the pre-`7699f28` structure).
  - **Fixed a second latent `None`-format crash in `main()` KEY FINDINGS.** The
    block formatted possibly-`None` CPCV/borrow/funding/impact values with
    `:.3f`, `:+.2%`, `:.2%`, raising
    `TypeError: unsupported format string passed to NoneType.__format__`
    on a short synthetic series (`N_PERIODS=320`). Added `_fmt_signed_pct(v)` and
    `_safe_diff(a, b)` helpers (next to the existing `_fmt_num`/`_fmt_pct`) and
    routed all KEY FINDINGS numeric output through them.
- **`skills/quantitative-backtesting/tests/test_trading_costs_robustness_example.py`**
  - Added `test_main_handles_none_cpcv_metrics`: stubs `run_cpcv_robustness` to
    return `None` OOS Sharpe and asserts `main()` renders
    `3. CPCV OOS Sharpe: low-cost=N/A vs high-cost=N/A.` without raising.
    Fast (~seconds) because the expensive CPCV sweep is stubbed; all other
    sections use the existing `_reduced_grids`.

## What was actually verified (evidence)
- **Before the fix** (clean tree at `7699f28`), `test_trading_costs_robustness_example.py`
  had **3 failures**, all `KeyError: 'high_cost'`:
  `test_regime_aware_flag_populates_metadata_and_cpcv`,
  `test_regime_coefficient_keys_match_detected_labels`,
  `test_regime_aware_changes_net_results_vs_constant`.
- **After the fix:**
  - `test_trading_costs_robustness_example.py` → **6/6 passed** (pytest) and **6/6**
    via the file's own `main()` runner.
  - Full example `--regime-aware` (default `N_PERIODS=756`) → **EXIT=0**, prints
    `TRADING COSTS SENSITIVITY ANALYSIS COMPLETE`.
  - Short-series `N_PERIODS=320` → **EXIT=0** (previously crashed); CPCV Sharpe
    correctly renders `N/A`.
  - `test_strategy_cost_model.py` → **35 passed**.
  - `test_regime_detection.py` + `test_regime_detection_point_in_time.py` → **53 passed**.
  - `test_hmm_regime_hypothesis_example.py` + `test_regime_concentration_diagnostic.py`
    + `test_trading_costs_robustness_example.py` → **18 passed**.
  - `test_examples_coverage.py -k trading_costs_robustness` → **3 passed** (the two
    subprocess full-example runs both EXIT=0).

## What remains unresolved
- **Not committed.** Per the standing "do not commit unless explicitly asked" rule
  and the prior handoff's "Do not commit unless explicitly asked." Two files are
  modified in the working tree. If committing is authorized, use a descriptive
  message (NOT an empty/control-marker message).
- Full serial `pytest skills/quantitative-backtesting/tests/` still exceeds the
  in-session budget (~60+ min). Continue with chunked/targeted batches.
- CI workflow `quant-regression-gate` remains blocked on the GitHub App
  `workflows` permission (sessions 95–110). Do not retry without new access.
- HMM regime hypothesis example verdict is **NOT SUPPORTED** because the
  concentration diagnostic classifies the pooled-OOS window as `fragile`
  (bull Sharpe ~1.37 vs sideways ~−0.29, bear ~0.00). This is an honest
  falsification outcome. **Do not** force it to `SUPPORTED` or re-register the
  criteria post-hoc to make it pass.

## Approaches already tried / failed (do not repeat unchanged)
- The prior session (110) claimed `test_trading_costs_robustness_example.py`
  was "5/5 passed" after `7699f28`. **That claim is contradicted by the committed
  tree**: the exact HEAD fails 3 tests. Lesson: run the tests against the exact
  committed tree before reporting green; do not trust a pre-edit test run.
- Re-registering/relaxing the HMM concentration criterion to flip the verdict is a
  methodological anti-pattern (post-hoc criterion selection). Rejected.
- Adding sklearn/hmmlearn as a dependency: deliberately avoided (HMM is
  numpy/scipy-only).

## One precise next task (for the next agent)
**Add a closed-form regression test for the single-asset `notional-weighted`
regime-aware impact path in `skills/quantitative-backtesting/tests/test_strategy_cost_model.py`.**

Evidence for the gap:
- `test_single_asset_regime_aware_sqrt_matches_closed_form` (line 767) and
  `test_single_asset_regime_aware_linear_matches_closed_form` (line 960) call
  `market_impact_cost(..., is_panel=False, ...)` **without** `impact_aggregation`,
  so they exercise the default `"panel"` branch (`market_impact = rate`).
- `test_single_asset_notional_weighted_sqrt_matches_closed_form` (line 568) covers
  `notional-weighted` **without** regimes.
- No test covers `is_panel=False` + `impact_aggregation="notional-weighted"` +
  `regimes`/`regime_impact_coefficients` together. That branch is
  `scripts/utils.py` ~448–455: `market_impact = rate * position_changes`, where
  `rate = sqrt(participation) * period_impact_coeff` (sqrt) or
  `participation * period_impact_coeff` (linear), with
  `participation = position_notional / adv_notional` and
  `period_impact_coeff = regimes.map(regime_impact_coefficients)`.

Deliverable: two fast tests (sqrt + linear) on a tiny constant-volume/zero-return
frame (mirror the existing single-asset regime-aware tests, ~6 periods) asserting:
1. `result == sqrt(participation) * period_impact_coeff * position_changes`
   (sqrt) and `participation * period_impact_coeff * position_changes` (linear),
   `atol=1e-12`;
2. an unknown regime label falls back to the base `impact_coefficient`.
Then run `python3 -m pytest skills/quantitative-backtesting/tests/test_strategy_cost_model.py -q`
and report the count. Do not change production code unless the test reveals a defect.

(End of file)
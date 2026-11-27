# Handoff — Cross-method capacity invariance test added; focused suite green

## What changed (this session)
- One new file:
  `skills/quantitative-backtesting/tests/test_cross_method_capacity_pricing_invariance_real_triple_aapl_msft_googl.py`
  (repo `skills/quantitative-backtesting/tests/`). No production code touched.
- Executes option 1 from `HANDOFF_SESSION_NEXT.md` (cross-method capacity
  comparison). Runs the SAME market-neutral cross-sectional momentum strategy
  (lookback 10/20, top_quantile 0.4, bottom_quantile 0.2) on the committed
  AAPL/MSFT/GOOGL triple panel under BOTH `panel_pricing="net-exposure"` and
  `panel_pricing="book"` at impact_coefficient=0.1, and pins:
  1. **Pricing invariance**: basket `summary["capacity"]` is IDENTICAL across
     the two pricing modes (it is a liquidity property, not a pricing one).
  2. `capacity_book` is `None` under net-exposure and positive under book.
  3. **Book/basket gap**: `capacity_book < capacity` for this concentrated
     cross-sectional book; ratio pinned (~0.4801).
  4. Exact pinned values (rel tol 1e-6) so a regression in either estimator is
     caught. Offline, committed fixtures only, no network.

## What was actually verified (evidence)
- `python3 skills/quantitative-backtesting/tests/test_cross_method_capacity_pricing_invariance_real_triple_aapl_msft_googl.py` → `OK`.
  Measured: net-exposure basket capacity = $146,092,784; book basket capacity =
  $146,092,784 (identical); book capacity_book = $70,135,727 (ratio 0.4801).
- Sibling baselines still pass (no regression, no prod change):
  - `test_cross_sectional_momentum_capacity_sensitivity_real_triple_aapl_msft_googl.py` → OK
  - `test_ema_crossover_capacity_sensitivity_net_exposure_real_triple_aapl_msft_googl.py` → OK
- Deterministic: repeated runs give identical pinned numbers.
- `pytest` is NOT installed in this env; used the repo's portable `python3 <file>`
  convention (see `tests/README.md`).
- `git status`: only the one new untracked test file; `git diff --stat` empty.

## What remains unresolved
- DATA PROVENANCE (pre-existing, blocked offline): committed `real_market_data`
  CSVs are placeholders/synthetic (MSFT==sample_benchmark, AAPL==sample_ohlcv,
  GOOGL==AAPL.bak). These are regression guards on committed data, NOT evidence
  about real securities. Restoring authentic data needs network (unavailable
  offline) — do NOT fabricate. See PROVENANCE.json and HANDOFF_SESSION_164.md.
- Option 2 from the prior handoff (regime-aware impact capacity) is NOT yet done
  and is NOT a pure test task — see next task.

## Approaches that already failed (do not repeat)
- `background_process` sweep: repo not visible in its namespace — abandoned; use
  foreground timed batches. (Prior sessions.)
- `pytest` invocation fails (module absent); use `python3 <file>` directly.
- Printing a marker inside a `contextlib.redirect_stdout(buffer)` block and then
  asserting it appears in `buffer` fails (the print is captured, not echoed);
  assert on returned values instead. (Hit and fixed this session.)

## One precise next task (bounded, evidence-based)
Implement **regime-aware capacity** so the capacity estimate reflects stressed
regimes, then pin it with a focused test. Evidence this is a real gap:
- `estimate_capacity()` (`skills/quantitative-backtesting/scripts/walk_forward.py:3738`)
  signature has NO `regime_impact_coefficients` parameter. Regime coefficients
  only scale the per-trade market-impact charge in the RETURN path
  (`_calculate_strategy_returns`, ~line 3486/3637/3688), never the CAPACITY
  estimate. So `--regime-impact-coefficients` changes returns/cost_drag but the
  reported `capacity`/`capacity_book` are computed from a single flat
  `impact_coefficient` and are blind to the regime mix.

Steps:
1. Add a focused test FIRST that demonstrates the gap: build a regime-labeled
   panel (use `regime_detection.detect_combined_regime` on the committed triple
   close series), run `walk_forward_analysis` twice at the same flat
   `impact_coefficient` — once with `regime_impact_coefficients=None`, once with
   a dict that raises impact in the stressed regime — and assert the reported
   `capacity` is currently IDENTICAL (proves the blind spot). Register it / run
   via `python3 <file>`.
2. Extend `estimate_capacity(...)` with an optional
   `regime_impact_coefficients` + the per-period regime labels (or a
   regime-weighted effective coefficient = ADV-weighted mean of per-regime
   coefficients over the window) so the capacity reflects the regime mix;
   default `None` must leave every published number byte-identical.
3. Flip the test to assert regime-aware capacity < flat capacity when the
   stressed-regime coefficient is higher; keep default-path invariance.
4. Verify: the new test + the existing borrow/funding cap tests +
   `test_cross_method_capacity_pricing_invariance_real_triple_aapl_msft_googl.py`
   all pass. Do NOT commit unless explicitly asked. Keep scope to
   `walk_forward.py` + one new test file; do not touch the inherited marketplace
   catalog.
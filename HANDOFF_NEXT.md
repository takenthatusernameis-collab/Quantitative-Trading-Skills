# HANDOFF

## What changed this session

- Added `estimate_capacity(data, impact_coefficient, max_impact=0.0005, adv_window=20)` to `skills/quantitative-backtesting/scripts/walk_forward.py` — a market-impact-based strategy capacity estimator (`capacity = max_impact * ADV_notional / impact_coefficient`), addressing the mission's liquidity/capacity priority (previously documented in cost_models.md but not implemented).
- Added 6 regression tests in `skills/quantitative-backtesting/tests/test_walk_forward.py` and registered them in `TEST_REGISTRY`.
- Verified: `pytest skills/quantitative-backtesting/tests/test_walk_forward.py` → 143 passed, 0 failures (baseline 137 + 6 new; no regression).

## Next task

Surface `estimate_capacity` through `walk_forward_analysis` results/summary (capacity key present and `> 0` when `impact_coefficient > 0`, omitted/`None` when impact disabled), add a focused regression test, register it in `TEST_REGISTRY`, and verify `pytest skills/quantitative-backtesting/tests/test_walk_forward.py` stays at 0 failures with no regression.

## Constraints / evidence

- Keep change backward compatible: capacity key omitted/`None` when `impact_coefficient <= 0` or ADV not estimable.
- Reuse existing `estimate_capacity` and `_annualization_factor`; do not add new dependencies.
- Test data: `_make_ohlcv_data(periods=300, seed=42)` (business-daily, volume 1M–10M, price ~100–165).
- Registration guard `test_main_registers_every_module_level_test` requires every module-level `test_*` to be in `TEST_REGISTRY`.

# Handoff — Session 101: verify the square-root market-impact model (fix dead test + add closed-form guard)

## What changed
- `skills/quantitative-backtesting/tests/test_strategy_cost_model.py` (test-only; no production code touched):
  - **Fixed a dead test.** `test_market_impact_sqrt_model_differs_from_linear_single_asset`
    was defined *after* the `if __name__ == "__main__": sys.exit(main())` block and was
    missing from `TEST_REGISTRY`. The documented per-file runner
    (`python3 tests/test_strategy_cost_model.py`) therefore ran **18/18** and silently
    skipped it, while pytest ran **19** (mismatch = a test outside the runner = dead code).
    Moved the function into the module body (before the Registry) and registered it.
  - **Added a closed-form formula guard** `test_sqrt_market_impact_matches_closed_form`:
    calls `utils.market_impact_cost(..., impact_model="sqrt")` on a constant-volume,
    zero-return frame where the closed form `coefficient * sqrt(position_notional / ADV_notional)`
    is exact, and asserts the engine matches it. The pre-existing test only proved the sqrt
    branch was *reachable* ("differs from linear"); this pins the formula so a silent
    regression in the empirically-grounded square-root law (missing coefficient, linear term,
    mis-scaled participation) is caught directly.
  - Added `market_impact_cost` to the `from utils import (...)` block.

## What was actually verified
- **Runner parity restored.** Before: script runner 18/18, pytest 19. After: script runner
  **20/20**, pytest **20 passed** — both runners now execute the same 20 tests.
- **New formula test is discriminating (negative control).** Independently computed the
  linear closed form and confirmed: sqrt output == sqrt closed form (pass), sqrt output !=
  linear closed form, and if the engine wrongly used `linear` under `impact_model="sqrt"`
  the new test *would* fail. So it is a genuine guard, not a tautology.
- `python3 -m py_compile tests/test_strategy_cost_model.py` → OK.
- Focused regression slice `tests/test_strategy_cost_model.py tests/test_benjamini_hochberg_fdr.py`
  → **24 passed in 0.63s**.
- Full tests/ directory still collects cleanly: **1361 tests collected in 0.81s**, no
  import/collection errors.
- `git status --porcelain` → only `M skills/quantitative-backtesting/tests/test_strategy_cost_model.py`
  (83 insertions, 38 deletions). No generated artifacts dirtied.

## What remains unresolved
- **Not committed.** No explicit commit request was given; change is left in the working tree.
  Do not make a control-marker (empty-message) commit.
- The sqrt impact model is verified on the **single-asset** path only. Panel and book-pricing
  sqrt paths (`is_panel=True`, `book_market_impact_cost`) are not pinned to a closed form the
  same way; they are exercised end-to-end by existing impact tests but not formula-checked.
- The full quant gate still cannot complete in one in-session invocation (~60+ min timeout;
  see prior handoffs). Use chunked batches or CI with adequate budget.

## Approaches already tried / failed (do not repeat unchanged)
- Sessions 95–100 repeatedly restored a `quant-regression-gate` CI job; it was removed again
  each time and pushing `.github/workflows/*` fails with
  `refusing to allow a GitHub App to create or update workflow ... without workflows permission`.
  That line is blocked on GitHub App permissions — do not re-attempt the restore/push cycle
  without new access. (This is why I picked a non-CI, in-session-verifiable task.)
- Full `pytest tests/` as a single serial run times out (~60+ min); use the chunked batches in
  prior handoffs.

## One precise next task
Pin the **panel** and **book-pricing** square-root impact paths to a closed form, mirroring
`test_sqrt_market_impact_matches_closed_form`:
- In `tests/test_strategy_cost_model.py`, add
  `test_panel_sqrt_market_impact_matches_closed_form` calling
  `market_impact_cost(..., is_panel=True, impact_model="sqrt")` on a constant-volume dict/panel
  and asserting the per-asset rate equals `mean_i( coeff * sqrt(per_asset_notional_i / ADV_i) )`
  under the default `impact_aggregation="panel"` (and, if desired, the `notional-weighted`
  variant).
- Add `test_book_sqrt_market_impact_matches_closed_form` using `book_market_impact_cost` with
  `impact_model="sqrt"` on a deterministic book, asserting the per-asset sqrt law.
- Register both in `TEST_REGISTRY` and confirm script runner == pytest count again.
Evidence to reproduce locally: `python3 tests/test_strategy_cost_model.py` and
`PYTHONPATH=scripts python3 -m pytest tests/test_strategy_cost_model.py -q` must both report the
same increased count and pass. This is test-only and in-session-verifiable (no CI needed).
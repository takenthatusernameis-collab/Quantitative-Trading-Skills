# Handoff — Session 75

## What changed
- `skills/quantitative-backtesting/tests/test_reporting.py`: added `test_generate_tear_sheet_surfaces_capacity_in_monte_carlo` regression test (30 insertions). Mirrors the existing walk-forward capacity test (`test_generate_tear_sheet_surfaces_capacity_in_walk_forward`) and asserts the tear-sheet JSON summary surfaces `summary.capacity` / `summary.capacity_trend` for the Monte Carlo path, matching the walk-forward / CPCV paths.
- Source side (already committed from Session 74, tree was clean at session start): `run_monte_carlo` writes `mc_results["summary"]["capacity"]` / `["capacity_trend"]` (walk_forward.py:~10096) and `_monte_carlo_sweep_coefficient` returns per-row `capacity` / `capacity_trend` (walk_forward.py:~9620). Measurement-only; no return/cost/impact/simulation logic changed.

## What was actually verified
- `cd skills/quantitative-backtesting && PYTHONPATH=scripts python3 -m pytest tests/test_reporting.py -k monte_carlo tests/test_walk_forward_records_regime_robustness.py` → 68 passed (includes full test_reporting.py + 2 regime-robustness tests), 7.26s.
- `test_reporting.py` alone after adding the regression → **67 passed** (includes the new test), 7.16s.
- `tests/test_monte_carlo.py` → **24 passed**, 3.44s (pre-existing numpy short-series warnings only).
- Working tree: only `tests/test_reporting.py` modified (+30 lines). No source/fixture changes this session.

## What remains unresolved
- **Full single-invocation quant gate not confirmed**: `python3 -m pytest skills/quantitative-backtesting/tests/ -n 4` (~1295 tests) exceeds the in-session/30-min environmental timeout (reached 94%, all dots, 0 failures in prior sessions). Chunked execution is the accepted substitute per HANDOFF.md / Sessions 63-68. Slow chunks not re-run this session: `cost_sweep`/`falsifiable` (~48 files) and `test_examples_coverage.py` (~hours sequentially).
- **Book-pricing Monte Carlo `capacity_book`**: inspected. `run_monte_carlo` always computes basket-based `estimate_capacity(data, ...)` even when `panel_pricing="book"`; walk-forward/CPCV already surface book-based capacity, but no test exercises Monte Carlo with book pricing and no failure demonstrates a gap. Per the "metadata-only / no speculative change" rule, no change made; noted as a possible follow-up only if evidence of a gap appears.

## Approaches already tried / failed (do not repeat unchanged)
- Full serial quant gate: timed out ~60 min twice (Sessions 63-68).
- Full gate `-n 4`: timed out at 30 min this session (reached 94%, all dots, 0 failures).
- Full gate `-n 4` excluding 48 slow cost-sweep/falsifiable files: timed out at 20 min.
- `test_examples_coverage.py` standalone: timed out at 5 min.

## One precise next task
Complete the full gate summary line via focused chunks in an environment with a longer timeout:
1. `python3 -m pytest skills/quantitative-backtesting/tests/ -p no:cacheprovider -q --tb=short -n 4 -k "cost_sweep or falsifiable"` (expect green, ~10-16 min).
2. `python3 -m pytest skills/quantitative-backtesting/tests/test_examples_coverage.py -p no:cacheprovider -q --tb=short -n 4` (slow; allow >5 min budget or accept as environmental).
3. Record collected/passed/failed for each. Do not commit unless explicitly asked. Keep working tree clean (`git checkout -- .` if any tracked artifacts are dirtied). Constraint: offline/committed fixtures only; no live network.
Relevant files: `skills/quantitative-backtesting/scripts/walk_forward.py` (`run_monte_carlo`, `_monte_carlo_sweep_coefficient`), `skills/quantitative-backtesting/scripts/reporting.py` (tear-sheet Monte Carlo JSON summary at reporting.py:1656-1665), `skills/quantitative-backtesting/tests/test_reporting.py`, `skills/quantitative-backtesting/tests/test_monte_carlo.py`.

# Handoff — next session

## Current state
- Working tree: modified, 4 files (30 insertions / 30 deletions), all intended:
  - `test_root_simple_momentum_cost_real_msft.py`
  - `test_root_simple_momentum_cost_real_googl.py`
  - `test_root_simple_momentum_real_msft.py`
  - `test_root_simple_momentum_real_googl.py`
- `skills/quantitative-backtesting/tests/` focused regression chunk: **32 passed** (romano_wolf, reality_check, reality_check_family_example).
- Root regression-guard suite: **21 passed, 1 failed** (`python3 -m pytest test_root_*.py -q`).

## What changed (this session)
- Re-baselined stale exact-float pinned metrics in 4 root regression-guard files to match the regenerated committed real-market fixtures (2020–2025).
- Root cause: commit `45db4fb` regenerated `real_market_data/*` (AAPL/GOOGL/MSFT/sample_benchmark/sample_ohlcv, 2010–2019 → 2020–2025) and updated docstrings but never re-baselined the pinned metrics. `run_backtest.py` and `simple_momentum_hypothesis.py` are unchanged — **not a backtest regression**.
- Structural guards (costed < frictionless, capacity identical across cost settings, PIT/split controls) all pass, confirming the regenerated-fixture output is methodologically sound, not buggy. Re-baselining pins restores the guards' ability to catch silent cost-model / backtest-wiring changes without weakening any control.

## What was actually verified
- `test_root_simple_momentum_cost_real_msft.py`, `cost_real_googl.py`, `real_msft.py`, `real_googl.py` now pass (exact-float pins + 1e-3 rel tolerance).
- `test_root_scripts_pit_bias_controls.py` (9 structural guards) passes; `test_root_debug_scripts.py` passes.
- Working tree contains only the 4 intended edits; `__pycache__`/`.pytest_cache` untracked/ignored.
- `python3 simple_momentum_hypothesis.py` (synthetic fixture) → exit 0, VERDICT: NOT SUPPORTED (pre-registered falsification on synthetic fixture).

## What remains unresolved
- `test_root_simple_momentum_real_aapl.py::test_root_simple_momentum_metrics_pinned_on_real_aapl_window` still **FAILS**: it asserts `verdict == "SUPPORTED"`, but the regenerated 2020–2025 AAPL fixture honestly yields `NOT SUPPORTED` (deflated-alpha criterion fails because 301 test observations can't resolve alpha beyond the plausibility bound — the script itself notes this measures sample size, not the strategy).
  - **Do not force the verdict to SUPPORTED** — that would be tuning to force an outcome, violating the test's own no-tuning rule and the mission's honesty principle.
  - Bounded fix (separate task): either (a) re-baseline the pins AND change the verdict assertion to reflect the honest `NOT SUPPORTED` outcome (with a comment), or (b) convert this pinned test to a structural guard like `test_root_scripts_pit_bias_controls.py` (verdict deliberately not asserted).
- Full single-invocation quant gate (`pytest skills/quantitative-backtesting/tests/ -q -n 4`) still cannot complete in-session (~60+ min env timeout); last known result 1196 passed / 1 failed (artifact-mutation test, resolved since).

## Approaches already tried / failed (do not repeat unchanged)
- None this session; investigation was conclusive on first pass (stale pins after fixture regen).

## One precise next task (for the next agent)
1. Run the full quant gate in CI / adequate budget: `python3 -m pytest skills/quantitative-backtesting/tests/ -p no:cacheprovider -q -n 4`, then `git checkout -- .` to restore any timestamp-only drift and keep `git status` clean.
   - If green (EXIT 0): baseline fully confirmed (1197/1197). Then select the next bounded methodological gap (coverage is extensive across all registered strategies) — e.g., regime-aware cost models, capacity-aware position sizing, alternative validation schemes, multi-asset factor construction — rather than another strategy falsification test.
   - If a test fails: isolate with evidence, fix minimally, rerun focused tests, re-attempt the full gate.
2. Resolve the `test_root_simple_momentum_real_aapl.py` pinned-verdict failure (option a or b above), re-run `test_root_*.py`, confirm 22/22.
3. Do not commit unless explicitly asked. Keep changes minimal and reversible.

(End of file)

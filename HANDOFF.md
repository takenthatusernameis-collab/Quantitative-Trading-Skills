# Handoff — regime-dependent performance disclosure in single backtest

## What changed (this session)
- `skills/quantitative-backtesting/scripts/run_backtest.py`: `run_backtest()` now discloses regime-dependent performance (`results["regime_analysis"]`) in the single-backtest results, mirroring the walk-forward path (`walk_forward.py:1198`). It calls `add_regime_analysis_to_results` from `regime_detection.py` on the strategy returns and market close, wrapped in try/except so it yields `None` when data has no close column or the computation cannot run. It changes no return, cost, impact, or capacity number.
- `skills/quantitative-backtesting/tests/test_run_backtest.py`: added `test_run_backtest_records_regime_analysis` (and registered it in `TEST_REGISTRY`) asserting `results["regime_analysis"]` is a dict with `trend_regime_performance`, `volatility_regime_performance`, `combined_regime_performance`, `regime_periods`, and `regime_distribution`.
- Working tree has exactly these 2 modified files, +43 insertions. No commit made.

## What was actually verified
- `python3 -m pytest test_run_backtest.py test_regime_detection.py -q -p no:cacheprovider --tb=short` → **133 passed** (offline, committed fixtures only), including the new `test_run_backtest_records_regime_analysis`.
- `run_backtest` imports cleanly after the new `regime_detection` import.

## What remains unresolved
- `regime_analysis` is computed in results but **not rendered** in the tear sheet (`reporting.py`) — walk_forward's `summary["regime_analysis"]` is also not rendered there. A consumer can read the key from `results`/JSON, but it is not displayed in the HTML tear sheet.
- Full quant gate `python3 -m pytest skills/quantitative-backtesting/tests -q -p no:cacheprovider --tb=short -n 4` has **not** been re-run this session (prior run: 1193 passed, 1 failed = the known artifact-mutation test `test_examples_coverage.py::test_scripts_results_untouched_after_examples`, which is self-inflicted by running the gate and reverted with `git checkout -- .`). Full gate times out as a single blocking run (~60+ min); use `pytest -n 4` with adequate budget.
- pytest-xdist is installed but not pinned in any requirements file.

## Approaches already tried / failed
- Serial full gate: timed out at ~60 min (twice). Do not repeat unchanged.
- This session's regime-analysis change: verified green with focused tests; no failure.

## One precise next task
Either (a) render `regime_analysis` in `reporting.py`'s tear sheet so regime-dependent performance is disclosed visually (honest reporting), following the existing `book_diagnostic_section` pattern, with a test in `test_reporting.py`; or (b) re-run the full quant gate with `pytest -n 4` and adequate budget, then `git checkout -- .` to restore artifacts, and confirm 1193/1194. Do not commit unless explicitly asked. To re-run the gate: `python3 -m pytest skills/quantitative-backtesting/tests -q -p no:cacheprovider --tb=short -n 4` then `git checkout -- .`.

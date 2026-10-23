# Handoff — Z-Score mean-reversion (pairs) hypothesis complete (2026-10-23)

## What changed

Executed the prior agent's HANDOFF_NEXT task: a bounded, pre-registered falsifiable hypothesis test for Z-Score mean reversion on a pair, using the same run_backtest.py pattern as the RSI example.

- Added `skills/quantitative-backtesting/scripts/generate_synthetic_pair.py`: deterministic generator for two synthetic fixtures with clear, documented provenance (formula written out, seeded, labelled "synthetic / test-machinery check, not evidence about any market"):
  - `sample_pair_ohlcv.csv` — cointegrated pair: two random-walk assets sharing a common trend with a stationary, mean-reverting AR(1) log-price spread (genuine cointegration; hedge ratio 1).
  - `sample_pair_no_effect_ohlcv.csv` — no-effect control: two independent random walks, no shared trend, no stationary spread (no cointegration edge).
  - Both are two-symbol panel CSVs (`ASSET_A`, `ASSET_B`, columns `date,open,high,low,close,volume,symbol`), loadable via `--multi-symbol`.
- Modified `skills/quantitative-backtesting/scripts/strategy_builder.py`:
  - Refactored pairs signal generation into a shared `_pairs_positions_from_two_series` (behavior-preserving).
  - Added `_pairs_weights_from_two_series` and a `generate_target_weights` book accessor on `MeanReversionZScore`, so the long/short market-neutral book is exposed. This is consistent with `CrossSectionalMomentum`/`DualMomentum` and is required for `--panel-pricing book` to price the true book return `sum_i w_i r_i` (net-exposure pricing would report a flat position for a market-neutral pair).
- Added `skills/quantitative-backtesting/examples/zscore_mean_reversion_hypothesis.py`: runs both fixtures through `run_backtest.py --multi-symbol --strategy zscore_mean_reversion --panel-pricing book --run-split test --train-frac 0.6 --val-frac 0.2 --test-frac 0.2 --validate-point-in-time`, with pre-registered falsification criteria (OOS Sharpe > 0, OOS total return > 0, net of 3 bps round-trip costs), chronological 0.6/0.2/0.2 split, point-in-time validation.
- Added `skills/quantitative-backtesting/tests/test_zscore_mean_reversion_hypothesis.py`: 7 tests (example declares criteria; fixtures are two-symbol panels; CLI produces results; example reports both verdicts; committed fixtures are byte-reproducible from `generate_synthetic_pair.py`; machinery SUPPORTED on cointegrated pair and NOT SUPPORTED on no-effect pair; verdict is the conjunction of criteria).
- Updated 2 existing tests in `tests/test_run_backtest.py` that used `zscore_mean_reversion` as the canonical "strategy with no book" example: they now assert the pairs strategy exposes a book and book pricing is effective (the old premise is obsolete now that zscore models a book, like the other multi-asset strategies).

## What was actually verified

- Cointegrated pair: SUPPORTED — OOS Sharpe 0.1748 (> 0), OOS total return +1.84% (> 0), split 600/200/200 chronological+disjoint, point-in-time validation passed.
- No-effect pair: NOT SUPPORTED — OOS Sharpe -0.7165 (< 0), OOS total return -2.79% (< 0).
  → The machinery distinguishes a genuine mean-reverting spread from noise (not a rubber stamp).
- `test_zscore_mean_reversion_hypothesis.py`: 7/7 pass.
- No regressions: `test_strategy_builder.py` 33/33; `test_rsi_mean_reversion_hypothesis.py` pass; `test_examples_coverage.py` 7/7; `test_run_backtest.py` 97/108 with only the 2 pre-existing split-metadata failures (also failing on clean baseline, unrelated to this change); `test_import.py` passes.
- Committed pair CSVs are exactly reproducible from `scripts/generate_synthetic_pair.py` (asserted in the test).

## What remains unresolved

- The open item from `HANDOFF.md` is still untouched: the committed `results/` artifacts (e.g. `results/metrics.json`) are stale/reproducibility is undecided (`splits_test_data.csv` absent; restore it and regenerate, or formally retire the legacy `results/` set). This is a separate task from the hypothesis work.

## Approaches already tried

- Pairs hypothesis under net-exposure pricing (`--panel-pricing net-exposure`, the default): rejected — a market-neutral pair has flat net exposure, so the engine prices ~0 and the result is meaningless (total return -9.9%, Sharpe -1.5). Fixed by adding `generate_target_weights` and using `--panel-pricing book` (verified meaningful: cointegrated +1.84% / Sharpe 0.17; no-effect -2.79% / Sharpe -0.72).
- No other approaches failed.

## One precise next task

Restore reproducibility of the committed `results/` artifacts (the open `HANDOFF.md` item): locate or restore `splits_test_data.csv` (referenced by `results/data_provenance.json` and `results/benchmark_provenance.json`, both dated 2026-10-14) and regenerate `results/metrics.json` (and the rest of `results/`) with current code, OR explicitly document/retire the legacy artifacts. Constraint: do not hand-edit committed result artifacts beyond timestamp/alignment; any regeneration must reproduce from input data. Relevant files: `results/metrics.json`, `results/data_provenance.json`, `results/benchmark_provenance.json`, `skills/quantitative-backtesting/scripts/run_backtest.py`.

(End of file)

# HANDOFF

## What changed this session

**Fixed a real, verifiable defect in a delivered example: the `full_pipeline_example.py`
stage-7 significance block never fired.**

`examples/full_pipeline_example.py:194` read `metrics.get('alpha_t_stat')` (with an
underscore between "alpha" and "tstat"), but `performance._benchmark_stats`
(`scripts/performance.py:220`) and the tear-sheet / text report (`reporting.py:650`)
emit the canonical key `alpha_tstat` (no underscore). The conditional was therefore
always falsy, so the pipeline printed "COMPUTING PERFORMANCE METRICS" while silently
omitting the alpha t-stat / p-value it was claiming to surface. Verified by running
the example: before the fix the two lines were absent; after, they print
`Alpha t-stat: -1.141` / `Alpha p-value: 0.2546`.

- `examples/full_pipeline_example.py:194-201`: read `alpha_tstat` / `alpha_pvalue`
  (the canonical keys), with a comment naming the source.
- `tests/test_examples_coverage.py`: added
  `test_full_pipeline_example_surfaces_single_benchmark_significance`, asserting the
  stage-7 stdout contains `Alpha t-stat:` and `Alpha p-value:`. Registered in
  `TEST_REGISTRY`.

## What was actually verified

- `test_examples_coverage` 7/7 (new test included).
- `test_run_backtest` 103/103, `test_performance` 33/33, `test_reporting` exit 0,
  `test_falsifiable_hypothesis_example` 3/3 — no regressions.
- `test_walk_forward` 177/177, `test_cpcv` 28/28, `test_monte_carlo` 20/20,
  `test_data_loader` 32/32, `test_strategy_builder` 33/33,
  `test_generate_sample_data` 2/2 — all green (re-confirmed this session after
  installing numpy/pandas/matplotlib, which were missing from the environment).
- The fix is a pure key-name correction; no charged number moves.

## What remains unresolved

- The parity harness from the prior handoff (`baseline_capture.py` /
  `book_cap_probe.py`) does not exist in `/home/runner/work/_temp/kilo-tmp/kilo/`
  (the directory is empty), so the HEAD-vs-new parity check cannot be run as
  specified. The prior session's evidence for the notional-weighted change rests on
  the test suite, not on that harness.
- The impact model is still linear in the participation rate (no temporary/permanent
  split, no gap risk).
- The `fill_rate` convention is still open (the framework scales position/book by
  fill rate; pinned by
  `test_run_backtest_book_pricing_market_impact_scales_with_the_fill_rate`).
- Reference artifacts in `test_output/` not regenerated (no panel-mode artifact set
  exists yet).

## Approaches that have already failed (and why)

- The prior session's rejected approaches still apply: the traded-only mean must not
  become the default (it overcharges by `n/k`); reporting the dilution without the
  notional-weighted third reading leads to the wrong decision.
- My own `replaceAll` edits initially cross-contaminated `book_weights` references in
  `walk_forward.py` (oos `val_book_weights` vs `parameter_optimization` `book_weights`),
  caught by the test suite (`name 'book_weights' is not defined`) and fixed by hand. Do
  not use blind `replaceAll` across call sites that use different variable names.
- **New this session:** scanning for a defect by grepping for `alpha_t_stat` (with
  underscore) matched nothing and produced a false "no defect" reading. The correct
  search is for the *delivered claim* (the printed stage list) and then checking whether
  each claim's stdout actually appears. Chasing key-name spellings in isolation misses
  mismatches where both sides use different-but-valid spellings.

## Next task (one precise, bounded item)

The prior handoff's next task (the parity harness) is unrunnable because the harness
files are absent. Pick the next highest-value bounded item from the unresolved list
above, or regenerate the canonical `test_output/` artifacts under the default `panel`
aggregation so the pinned regression snapshot matches the current code (the snapshot
in `skills/quantitative-backtesting/test_output/` predates the notional-weighted
addition and carries no `panel_pricing` / `impact_aggregation` fields).

## Git state

Work is **not committed** (the user did not ask for a commit). `git status` shows two
modified files under `skills/quantitative-backtesting/`:
`examples/full_pipeline_example.py`, `tests/test_examples_coverage.py`. The working
tree is the starting point for the next session; the last commit is `00a487e`.

(End of file - total 87 lines)

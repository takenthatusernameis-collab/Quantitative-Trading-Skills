# HANDOFF

## What changed this session

Executed the prior handoff's next task: **added the notional-weighted (dollar-consistent)
impact as an opt-in chargeable convention, with the matching capacity inversion, default
unchanged.** No published number moves under the default `"panel"` aggregation.

### Core: `skills/quantitative-backtesting/scripts/utils.py`

- Added `IMPACT_AGGREGATION_MODES = ("panel", "notional-weighted")`,
  `DEFAULT_IMPACT_AGGREGATION = "panel"` and `resolve_impact_aggregation(mode)`.
- `market_impact_cost(..., impact_aggregation="panel")`: panel mode is byte-for-byte the
  old behavior; notional-weighted mode charges `sum_i rate_i * notional_i / equity`
  (net-exposure path: `|d| x panel` since every constituent carries equal notional;
  single-asset path: `rate x |d|`).
- `book_market_impact_cost(..., impact_aggregation="panel")`: panel mode is the old
  equal-weighted mean; notional-weighted mode charges `sum_i rate_i * |dw_i|` (cost as a
  fraction of equity).
- `book_capacity_estimate(..., impact_aggregation="panel")`: panel rule is the old
  `max_impact * ADV_i / (|dw_i| * coeff)`; notional-weighted rule is
  `max_impact * ADV_i / (coeff * dw_i^2)`. Returns both
  `estimated_capacity` / `estimated_capacity_notional_weighted`,
  `capacity_trend` / `capacity_notional_weighted_trend`, plus the per-period series.
- `_impact_dilution_keys` / `compute_book_diagnostic`: `impact_charged_bps` now reflects
  the charging convention (panel mean under `panel`, the notional-weighted reading under
  `notional-weighted`); `impact_notional_weighted_bps` is convention-independent.

### Wiring

- `scripts/run_backtest.py`: new CLI flag `--impact-aggregation {panel,notional-weighted}`
  (default `panel`); `run_backtest()` threads it through `market_impact_cost` /
  `book_market_impact_cost` / `compute_book_diagnostic` / `book_capacity_estimate`; results
  surface `capacity_notional_weighted` and `capacity_notional_weighted_trend` next to
  `capacity_book` in book mode; `impact_aggregation` recorded in the run config.
- `scripts/walk_forward.py`: threaded `impact_aggregation` through
  `walk_forward_analysis`, `parameter_optimization`, `cpcv_analysis`,
  `out_of_sample_validation` (and their `_calculate_strategy_returns`,
  `_window_book_capacity`, `_window_book_diagnostic` call sites), the five CLI runners and
  all sweep helpers via `--impact-aggregation` on the shared parser. Summary keys
  `capacity_notional_weighted`, `capacity_notional_weighted_trend`,
  `oos_min_capacity_notional_weighted`, `impact_aggregation`.

### Tests (`tests/test_run_backtest.py`, +3; all recompute by hand from the strategy's
own weights; all registered in `TEST_REGISTRY`)

- `test_notional_weighted_charges_the_notional_weighted_measurement`: charged impact ==
  `impact_notional_weighted_bps` under nw mode; panel != nw; the notional-weighted reading
  is convention-independent.
- `test_notional_weighted_capacity_is_the_dw2_inverse`: reported
  `capacity_notional_weighted` equals a hand recomputation of
  `min_i(max_impact * ADV_i / (coeff * dw_i^2))` from the strategy's own weights.
- `test_default_impact_aggregation_is_panel`: default == explicit `panel` (identical
  returns and charged impact).

## What was actually verified

- Full suite green: `test_run_backtest` 103/103, `test_walk_forward` 177/177,
  `test_cpcv` 28/28, `test_monte_carlo` 20/20, `test_data_loader` 32/32,
  `test_performance` 33/33, `test_strategy_builder` 33/33,
  `test_generate_sample_data` 2/2, `test_examples_coverage` 6/6,
  `test_reporting` exit 0.
- Default aggregation produces zero changed numbers: every pre-existing test still passes
  with identical numbers; `test_default_impact_aggregation_is_panel` pins default ==
  explicit `panel`.
- CLI flag accepts `panel`/`notional-weighted`, rejects anything else (exit 2); default is
  `panel`.

## What remains unresolved

- The impact model is still linear in the participation rate (no temporary/permanent
  split, no gap risk).
- The `fill_rate` convention still open (the framework scales position/book by fill rate;
  pinned by `test_run_backtest_book_pricing_market_impact_scales_with_the_fill_rate`).
- Reference artifacts in `test_output/` not regenerated (no panel-mode artifact set exists
  yet).
- The HEAD-vs-new parity harness
  (`baseline_capture.py` / `book_cap_probe.py` in
  `/home/runner/work/_temp/kilo-tmp/kilo/`) was used by the prior session; running it again
  against this commit would close verification criterion (c) with the dedicated harness
  rather than the test suite.

## Approaches that have already failed (and why)

- None new this session. The prior session's rejected approaches still apply: the
  traded-only mean must not become the default (it overcharges by `n/k`); reporting the
  dilution without the notional-weighted third reading leads to the wrong decision.
- My own `replaceAll` edits initially cross-contaminated `book_weights` references in
  `walk_forward.py` (oos `val_book_weights` vs `parameter_optimization` `book_weights`),
  caught by the test suite (`name 'book_weights' is not defined`) and fixed by hand. Do not
  use blind `replaceAll` across call sites that use different variable names.

## Next task (one precise, bounded item)

Run the HEAD-vs-new parity harness: capture this commit's `run_backtest` /
`walk_forward` / `cpcv` outputs in both `net-exposure` and `book` modes with the default
`panel` aggregation and diff against the prior commit `65b8274` (via
`baseline_capture.py` / `book_cap_probe.py` in
`/home/runner/work/_temp/kilo-tmp/kilo/`). Expect zero changed numbers except the additive
`capacity_notional_weighted` / `capacity_notional_weighted_trend` keys, which are `None`
under the default. Then decide whether to keep the opt-in convention as-is or evaluate the
`fill_rate` convention next.

## Git state

Work is **not committed** (the user did not ask for a commit). `git status` shows four
modified files under `skills/quantitative-backtesting/`:
`scripts/run_backtest.py`, `scripts/utils.py`, `scripts/walk_forward.py`,
`tests/test_run_backtest.py`, plus this `HANDOFF.md` and `HANDOFF_NEXT.md`. The working tree
is the starting point for the next session; the last commit is `65b8274`
("Record the checkpoint commit in the handoff").

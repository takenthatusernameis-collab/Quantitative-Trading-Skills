# HANDOFF

## What changed this session

Executed the prior handoff's next task — **Phase 2 of the panel-book work: make the panel
path book-aware behind an explicit, opt-in `--panel-pricing {net-exposure,book}` mode, so
the market-neutral book is backtestable while every published number stays bit-identical.**

### Core: `skills/quantitative-backtesting/scripts/utils.py`

- `PANEL_PRICING_MODES = ("net-exposure", "book")`, `DEFAULT_PANEL_PRICING = "net-exposure"`,
  `resolve_panel_pricing(mode)`: normalizes/validates the mode (`None` -> the default).
- `held_book_weights(weights, market, lag, fill_rate)`: the book actually held — the target
  weights re-indexed onto the market model's grid, lagged by `1 + latency` and scaled by
  the fill rate (the same convention as the framework's position series). Returns `None`
  when there is no usable book (no weights, a single-asset path, or a book over a
  different universe). `compute_book_diagnostic` now uses it, so the diagnostic and the
  pricing read the *same* book (no second implementation).
- `book_return_series(weights, market, lag, fill_rate)`: the true book return
  `sum_i w_i r_i`. The first bar (no per-asset return) stays `NaN`
  (`.sum(axis=1, min_count=1)`), so the book-priced return series has exactly the same
  index as the net-exposure one.
- `book_is_active(weights, market, lag, fill_rate)`: the book-aware "does this strategy
  take a position?" test — a market-neutral book has a flat *net* exposure but a positive
  *gross* exposure, so it is a position.

### Core: `skills/quantitative-backtesting/scripts/run_backtest.py`

- New CLI flag `--panel-pricing {net-exposure,book}` (default `net-exposure`).
- In `book` mode the portfolio return per period is `sum_i w_i r_i` of the held book
  instead of `positions x mean(asset returns)`. The **cost series is identical in both
  modes** (commission, slippage, impact, borrow and funding still come from the scalar
  net-exposure position series) — see "What remains unresolved".
- The "never takes a position" guard is book-aware in `book` mode (`book_is_active`);
  `signals_active` is untouched for `net-exposure`.
- Fallback: a strategy that exposes no book (or a single-asset run) cannot be priced as
  a book -> the run falls back to net-exposure pricing, and the fallback is **recorded**
  (`results["config"]["panel_pricing_effective"]`), not silent.
- The mode is recorded in `results["panel_pricing"]`,
  `results["config"]["panel_pricing"]` / `["panel_pricing_effective"]`, printed by the
  CLI ("Panel pricing mode: ...") and rendered in the tear sheet ("Panel Pricing").

### Core: `skills/quantitative-backtesting/scripts/walk_forward.py`

- The same `--panel-pricing` flag on the `common_parser`, so it is accepted by every
  subcommand (`walk-forward`, `optimize`, `cpcv`, `monte-carlo`, `out-of-sample`).
- `_calculate_strategy_returns(..., panel_pricing="net-exposure", book_weights=None)`:
  in `book` mode the return term is the book return; the cost term is unchanged, so the
  two modes differ by exactly the exposure-convention gap.
- New `_window_takes_position(strategy, signals, data, panel_pricing, latency, fill_rate,
  book_weights)`: the book-aware position test used by the walk-forward, CPCV,
  `parameter_optimization` and out-of-sample grid searches (a market-neutral book is
  traded, not skipped). `signals_active` itself is unchanged.
- `panel_pricing` threaded through `walk_forward_analysis`, `cpcv_analysis`,
  `out_of_sample_validation`, `parameter_optimization` and the five cost-coefficient
  sweep helpers; the mode is recorded in `summary["panel_pricing"]` on all three
  validation paths and printed by the CLI.
- `scripts/reporting.py`: a "Panel Pricing" section in the tear sheet (main backtest,
  walk-forward, CPCV) and a top-level `panel_pricing` key in `tear_sheet_summary.json`.

### Also

- `scripts/strategy_builder.py`: the symmetric-quantile warning now names the way out
  (`--panel-pricing book` prices the long and short books separately), and no longer
  claims the strategy "never takes a position" in absolute terms.
- `references/cost_models.md`: new section "Panel pricing modes (`--panel-pricing`)"
  (the two conventions, what changes and what does not, the fallbacks, the
  configuration table entry).
- `references/validation_methods.md`: the `panel_pricing` summary key, and the
  book-aware position test in "Flat parameter sets".
- `SKILL.md`: the `run_backtest.py` / `utils.py` / `walk_forward.py` descriptions, a new
  Tips bullet, and the test-suite descriptions.

### Tests added (all registered in `TEST_REGISTRY`; 471 pytest cases, up from 459)

- `tests/test_run_backtest.py` (+5): the market-neutral book backtests in `book` mode
  (no raise) and its reported return equals the book return recomputed **by hand** from
  the strategy's own weights; the two modes differ by exactly the measured
  `return_gap` (per period and cumulative); the default mode is `net-exposure` and
  reproduces the explicit mode bit-for-bit; a strategy without a book falls back with
  the fallback recorded; a single asset is unaffected.
- `tests/test_walk_forward.py` (+4): the market-neutral book is traded in book mode
  (`periods_with_position > 0`, a non-null `total_oos_return`) while the net-exposure
  mode skips every combination; the two modes differ by exactly the measured
  `return_gap`; the summary records `panel_pricing`; the out-of-sample path prices the
  held-out window under the selected mode.
- `tests/test_cpcv.py` (+3): all four folds are traded in book mode (the net-exposure
  mode skips all of them); the two modes differ by exactly the measured `return_gap`;
  the pinned net-exposure number is unchanged (`0.005399536978800246`).

## What was actually verified

- **No published number changed.** Old (git `HEAD`) vs. new code compared key-by-key on a
  5-asset panel (900 bars) across the walk-forward, CPCV, out-of-sample **and** the
  single-backtest path (summaries, per-period / per-fold records, per-split
  performance, the full OOS return series, the equity curve, the trade ledger, the
  capacity block and the book diagnostic): the **only** differing keys are the three new
  additive `summary["panel_pricing"]` metadata keys. The harness extracts `HEAD` with
  `git archive` into a temp dir and never touches the working tree.
- The pinned values still hold: `cpcv total_oos_return == 0.005399536978800246`
  (asserted by an existing test and by a new one), the walk-forward pinned
  `0.042594435108365136`, and the `net-exposure` mode is bit-identical to the explicit
  `panel_pricing="net-exposure"` mode.
- Full suite green: `python -m pytest tests/ -q` -> **471 passed**; every standalone
  runner also green: `test_cpcv.py` 28/28, `test_data_loader.py` 32/32,
  `test_examples_coverage.py` 6/6, `test_falsifiable_hypothesis_example.py` 3/3,
  `test_generate_sample_data.py` 2/2, `test_monte_carlo.py` 20/20, `test_performance.py`
  33/33, `test_reporting.py` 60 (unittest, OK), `test_run_backtest.py` 84/84,
  `test_strategy_builder.py` 33/33, `test_walk_forward.py` 170/170.
- CLI end-to-end on a synthetic 5-asset panel (900 bars, `--multi-symbol`):
  - `run_backtest.py`, asymmetric cross-sectional momentum (lookback 20, 0.4/0.2):
    `net-exposure` -> total return **+19.12%** (Sharpe 1.92) with the diagnostic showing
    gross book **0.5867**, net exposure 0.1956, gross turnover **0.1751** vs charged
    turnover **0.0002**, return gap **-1.56 bps/period (-17.14% cumulative)**, book total
    **+36.27%**; `book` -> reported total return **+36.26%** (the book's), same gap.
  - Symmetric quantiles (a market-neutral book): `net-exposure` still raises
    ("never takes a position ... the strategy does hold a book"); `book` runs and reports
    gross book **0.3911**, net exposure **0.0000**, gross turnover **0.1437** vs charged
    **0.0000**, total return **+16.26%** (Sharpe 0.48).
  - `walk_forward.py cpcv`: `net-exposure` -> `folds_with_position` **0**,
    `total_oos_return` **null** (nothing could be traded); `book` -> `folds_with_position`
    **4**, `total_oos_return` **0.00044**, `oos_sharpe` **-1.43**, `summary.panel_pricing`
    `"book"`.
  - `walk_forward.py out-of-sample`: `book` -> held-out test window total return
    **+5.52%**, Sharpe **1.2244**, gross book 0.3573, 159/178 periods with a book.
  - `walk_forward.py monte-carlo --panel-pricing book` runs (base returns priced as the
    book).
- The book-mode return is checked against an **independent** hand computation
  (`test_run_backtest_book_pricing_backtests_a_market_neutral_book`), not against itself.

## What remains unresolved

- **The book is still priced with the net exposure's costs.** The cost and impact model
  is deliberately unchanged in this task, so in `book` mode: commission and slippage are
  charged on `abs(d net exposure)`, the impact model still sees `abs(d net exposure)`
  only, borrow and funding are still computed from the scalar net-exposure position
  series, and the trade ledger is still built from the net-exposure position series.
  Measured on the 5-asset panel: gross turnover **0.1751** vs charged turnover
  **0.0002** (~900x under-charge); for the market-neutral book the charged turnover is
  **0.0000** while the book rotates **0.1437** per period, and its short leg pays **no
  borrow cost** at all. **Book-mode results are therefore an upper bound** on what a
  fully costed book would earn. This is stated in the CLI, in the summary JSON and in
  the tear sheet.
- **The book-mode trade ledger is empty for a market-neutral book** (the ledger is built
  from the net-exposure position series), so the trade-level statistics (win rate,
  profit factor, expectancy) are absent from the metrics in that case. The return and
  risk metrics are unaffected.
- **The default is still `net-exposure`.** Flipping it would change every published
  number; it needs its own decision (out of scope here).
- **Position warmup divergence (carried over, unchanged).** `run_backtest.py` uses
  `positions = signals.shift(1 + latency).fillna(0)` (the first entry *is* charged);
  `walk_forward.py` uses `positions = signals.shift(1 + latency) * fill_rate` (the first
  defined position is entered for free and the bar is dropped). Documented in
  `references/cost_models.md`; intentionally unchanged because it alters published
  numbers.
- **Panel trade ledger is an approximation** (priced on the mean constituent close).
  Documented; unchanged.
- **Dual momentum is priced at a fraction of its own book** (book fully invested at
  `net_exposure` 0.92 vs the engine's 0.18). The `book` mode prices the book correctly;
  the *cost* understatement above still applies to it.

## Approaches already failed / why (this session and prior sessions)

- **A bulk string replacement over `walk_forward.py` matched the wrong call.** The
  pattern `benchmark_cost_is_periodic=...,\n)` also matched
  `_benchmark_list_alpha_correction(...)`, which does not take `panel_pricing`; two
  tests failed with `TypeError: _benchmark_list_alpha_correction() got an unexpected
  keyword argument 'panel_pricing'`. Fixed by reverting that one call and re-checking
  every insertion by mapping each `panel_pricing=` line back to the call that owns it
  (a small script that walks the parenthesis depth backwards). Lesson: after any bulk
  edit in this file, map each inserted argument to its call site.
- The same bulk replacement also clobbered the `_optimize_sweep_coefficient` body
  (`top = results[0] if results else None` became `summary = results["summary"]`),
  because `parameter_optimization` returns a **list**, not a dict. Fixed by restoring
  the two original lines; three optimize-sweep tests failed until then.
- **Asserting "the two modes differ by the return gap" on a multi-combination grid
  failed** (CPCV: observed difference 0.0255 vs the measured gap 0.0318). The grid
  search scores candidates *under the pricing mode it runs in*, so the two modes can
  select **different parameters** and the difference is then no longer the pricing
  convention alone. Fixed by using a single parameter combination in that test (and
  documenting why in the test docstring) — the same trap applies to any future
  cross-mode comparison.
- (Prior sessions, unchanged) Calling `compute_book_diagnostic` before the return series
  exists: the helper defines the measurement window from the framework's return index,
  so it returned `None`. Feeding a wide MultiIndex CSV to `--multi-symbol`:
  `load_multi_symbol` requires a long-format file with a `symbol` column. Re-running
  the quantile validation inside `generate_target_weights`: the warning was emitted
  twice per run. Printing the aggregate (validation + test) diagnostic in the
  out-of-sample CLI next to the held-out test performance: misleading; the CLI now
  prints the test window's own diagnostic. Reusing the old pseudo-asset panel shape for
  impact unification: not equivalent to the per-asset model; rejected. Making
  walk-forward and run_backtest fully identical: would change the single-asset position
  warmup and every published number; not attempted; the residual difference is
  documented and asserted.

## Next task (precise, bounded, evidence-based)

**Phase 2b: cost the book, not the net exposure — turn the `book` mode from an upper
bound into a costed result.**

Problem (measured above): the `book` mode prices the *return* correctly but still charges
the *costs* of the net exposure. On the 5-asset panel the book's gross turnover is 0.1751
against a charged turnover of 0.0002 (~900x under-charge); the market-neutral book rotates
0.1437 per period and is charged **nothing**, pays no borrow cost on its short leg, and
produces no trade records. So every book-mode number published so far is an upper bound
and cannot be quoted as a strategy result.

Work items:

1. In `book` mode only, charge commission + slippage on the book's **gross** turnover
   `sum_i |dw_i|` (per asset, each change scaled by the fill rate) instead of
   `abs(d net exposure)`, and compute borrow cost on the book's **short legs**
   (`sum_i max(-w_i, 0)`) and funding on the book's gross exposure instead of the scalar
   net exposure. The `net-exposure` mode must not change at all.
2. Market impact for a book: extend `market_impact_cost` (or add a book variant next to
   it) to charge `sum_i |dw_i| x equity` per asset against **that asset's own ADV**,
   keeping the panel convention "portfolio cost = mean of the per-asset impacts" that
   the current model uses. The impact model must remain a no-op when
   `--impact-coefficient 0`.
3. Re-check the panel **capacity** convention before touching the impact model: the
   current estimate assumes an equal-weight basket whose least liquid constituent
   binds. A book's capacity depends on the book's own per-asset weights. Decide and
   document whether the capacity estimate stays basket-based (flagged as an
   approximation for a book) or becomes book-based — and make the choice visible in the
   artifacts either way.
4. Derive the **trade ledger** from the book in `book` mode, so a market-neutral book
   produces trade records and the win rate / profit factor are meaningful.
5. Tests: the `net-exposure` path must stay bit-identical (all pinned values, the
   HEAD-vs-new harness); in `book` mode the charged turnover must equal the book's
   gross turnover; a book that rotates must be charged more than one that does not; the
   impact cost must scale with the fill rate and with each asset's own ADV; a
   market-neutral book must now show a borrow cost on its short leg.
6. Document the new cost basis in `references/cost_models.md` and `SKILL.md`, and
   replace the "upper bound" caveat with the residual approximations that remain.

Out of scope for this task: flipping the default to `book` (it changes every published
number and needs its own decision), the position warmup divergence, and the panel trade
ledger's mean-price approximation.

Constraints: the `net-exposure` mode must stay bit-identical; existing keys keep their
names and numbers; the full suite must stay green. The `book`-mode numbers **will**
change — they were introduced in this session and are not published, so say so in the
handoff and in the docs.

Relevant files: `skills/quantitative-backtesting/scripts/utils.py` (`market_impact_cost`,
`held_book_weights`, `book_return_series`, `book_is_active`),
`scripts/run_backtest.py` (the cost block and the trade extraction),
`scripts/walk_forward.py` (`_calculate_strategy_returns` and the grid-search skips),
`scripts/performance.py` (the trade metrics), `scripts/reporting.py` (the tear-sheet
tables), `references/cost_models.md`, `tests/test_run_backtest.py`,
`tests/test_walk_forward.py`, `tests/test_cpcv.py`.

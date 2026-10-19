# HANDOFF

## What changed this session

Executed the prior handoff's next task — **Phase 1 of the panel-book work: expose the
per-asset target book and quantify the net-exposure gap, without changing any reported
P&L, cost, impact or capacity number.**

### Core: `skills/quantitative-backtesting/scripts/strategy_builder.py`

- New optional strategy accessor `StrategyBase.generate_target_weights(data)`:
  returns a `DataFrame` of per-asset portfolio weights (rows = dates, columns = symbols,
  `sum(|w|) <= 1`) whose **net exposure matches the scalar signal** of
  `generate_signals`, or `None` by default so every other strategy (and every
  single-asset run) is unchanged.
- `CrossSectionalMomentum.generate_target_weights`: long book `+1/n_assets` per long name,
  short book `-1/n_assets` per short name. The book's net exposure is therefore exactly
  the scalar signal `(n_long - n_short) / n_assets`, and the gross book is
  `(n_long + n_short) / n_assets`. A name selected on both sides (the overlapping-quantile
  case the strategy already warns about) nets to zero, so the net exposure still matches.
- `DualMomentumStrategy.generate_target_weights`: `1/n_selected` per selected name — a
  fully invested long-only book. This book is *more* invested than the scalar signal
  (`n_selected / n_assets`), which the diagnostic reports explicitly (both net exposures).
- Refactor (behaviour-preserving): the long/short selection of
  `_generate_multi_asset_signals_dict` / `..._multiindex` and the selected-names
  selection of the dual-momentum paths are now shared helpers
  (`_cross_sectional_selection`, `_dual_momentum_selection`) that the signal path *and*
  the book accessor both use, so the book and the signal can never disagree.
  Verified bit-identical against verbatim copies of the pre-refactor code for
  4 cross-sectional and 3 dual-momentum parameter sets (dict and MultiIndex panels).

### Core: `skills/quantitative-backtesting/scripts/utils.py`

- `strategy_target_weights(strategy, data)`: reads the optional accessor, `None` when the
  strategy has no book.
- `compute_book_diagnostic(weights, market, positions, framework_returns, lag, fill_rate)`:
  the measurement itself. The book held in a period is the target book lagged by the
  execution convention (`1 + latency`) and scaled by the fill rate — the same convention
  as the framework's position series — so both are measured on the same bars. Reported
  keys: `n_periods`, `n_periods_with_book`, `n_assets`, `gross_book`, `net_exposure`,
  `framework_net_exposure`, `gross_turnover`, `framework_turnover`, `return_gap_bps`,
  `return_gap_total`, `book_total_return`, `framework_total_return`,
  `framework_total_return_after_costs`. The return gap compares the framework's
  **pre-cost** pricing (`net_exposure x mean asset return`) with the true book return
  `sum_i w_i r_i`, so it isolates the exposure-convention gap from the cost gap. Returns
  `None` for a single asset, a strategy without a book, or a panel with no per-asset data.
- `aggregate_book_diagnostics(diagnostics)`: the per-window aggregate (means weighted by
  the number of periods, cumulative returns compounded across the windows).

### Surfacing (all additive; `None` when there is no book)

- `scripts/run_backtest.py`: `results["book_diagnostic"]` and `metrics["book_diagnostic"]`,
  printed by the CLI as a "Panel Book Diagnostic" block.
- `scripts/walk_forward.py`: `period["book_diagnostic"]` (walk-forward),
  `fold["book_diagnostic"]` (CPCV), `validation_performance["book_diagnostic"]` /
  `test_performance["book_diagnostic"]` (out-of-sample), and `summary["book_diagnostic"]`
  on all three paths; plus `summary["validation_book_diagnostic"]` /
  `summary["test_book_diagnostic"]` on the out-of-sample path. The CLI artifacts persist
  the per-period / per-fold diagnostic rows and the out-of-sample test-window diagnostic.
- `scripts/reporting.py`: a "Panel Book Diagnostic" table in the tear sheet (main
  backtest, walk-forward, CPCV) and a top-level `book_diagnostic` key in
  `tear_sheet_summary.json`.
- `scripts/run_backtest.py`: the "never takes a position" guard now **explains** the
  case it used to hide: when the strategy does hold a book but its net exposure is flat
  (the symmetric-quantile market-neutral book), the error says so (gross book, periods
  with a book) instead of implying the strategy is flat.

### Tests added (all registered in `TEST_REGISTRY`; 459 pytest cases, up from 441)

- `tests/test_strategy_builder.py` (+5): the accessor is `None` by default; the
  cross-sectional book's net exposure equals the scalar signal exactly; the
  symmetric-quantile book is open (gross book > 0) while its net exposure is flat and
  both legs are present; single-asset data yields no book; the dual-momentum book is
  long-only, equally weighted and fully invested.
- `tests/test_run_backtest.py` (+5): the diagnostic is surfaced for a panel; the book
  return matches an **independent** hand computation (`sum_i w_i r_i` with a one-period
  lag); the diagnostic is `None` for a single asset and for a strategy without a book;
  the flat-net-exposure guard states that the strategy does hold a book.
- `tests/test_walk_forward.py` (+4): the per-period and summary diagnostics (with the
  net-exposure invariant and the aggregate's period counts); `None` for a single-asset
  walk-forward; the out-of-sample per-split diagnostics; the CLI `cpcv` artifact rows.
- `tests/test_cpcv.py` (+2): the per-fold and summary diagnostics; `None` for a
  single asset.
- `tests/test_reporting.py` (+2): the tear-sheet section and the JSON key are present
  when the diagnostic is, and absent when it is not.

### Documentation

- `references/cost_models.md`: new section "Panel book diagnostic (measurement only)"
  (key table, the accessor contract, what the diagnostic shows, the unchanged
  limitation) and a pointer from the existing "Known limitation" paragraph.
- `references/validation_methods.md`: the walk-forward and CPCV "Output" sections
  document the new `book_diagnostic` summary key.
- `SKILL.md`: the `strategy_builder.py` / `utils.py` / `run_backtest.py` /
  `walk_forward.py` descriptions, a new Tips bullet ("A panel backtest prices net
  exposure, not the book"), and the test-suite descriptions.

## What was actually verified

- **No reported number changed.** Old (git `HEAD`) vs. new code compared key-by-key on a
  4-asset panel across the walk-forward, CPCV and out-of-sample paths (summaries,
  per-period / per-fold records, per-split performance, and the full OOS return
  series): **zero differing keys/values**. The comparison harness extracts `HEAD` with
  `git archive` into a temp dir and never touches the working tree.
- The strategy refactor is behaviour-preserving: the new signal code matches verbatim
  copies of the pre-refactor code for 4 cross-sectional and 3 dual-momentum parameter
  sets, dict and MultiIndex panels (`pd.testing.assert_series_equal`, exact).
- Full suite green: `python -m pytest tests/ -q` -> **459 passed**; each standalone
  runner also green: `test_cpcv.py` 25/25, `test_data_loader.py` 32/32,
  `test_examples_coverage.py` 6/6, `test_falsifiable_hypothesis_example.py` 3/3,
  `test_generate_sample_data.py` 2/2, `test_monte_carlo.py` 20/20, `test_performance.py`
  33/33, `test_reporting.py` 60 (unittest), `test_run_backtest.py` 79/79,
  `test_strategy_builder.py` 33/33, `test_walk_forward.py` 166/166 (11/11 suites).
- CLI end-to-end on a synthetic 4-asset panel (900 bars, `--multi-symbol`):
  - `run_backtest.py` (asymmetric cross-sectional momentum, lookback 20, 0.4/0.2):
    gross book **0.7333**, net exposure (book) **0.2444** = net exposure (framework)
    **0.2444**, gross turnover **0.1883** vs turnover charged by the model **0.0003**,
    879/899 periods with a book, return gap **-1.51 bps/period (-15.19% cumulative)**,
    book total return **+29.01%** vs framework **+13.81%**.
  - `walk_forward.py cpcv`: `cpcv_summary.json` carries `summary.book_diagnostic` and
    per-fold `book_diagnostic` rows; the CLI prints the block.
  - Tear sheet HTML renders the "Panel Book Diagnostic" table; `metrics.json` and
    `tear_sheet_summary.json` carry the diagnostic.
- The diagnostic's arithmetic is checked against an independent computation, not against
  itself: `test_run_backtest_book_diagnostic_book_return_matches_manual_computation`
  recomputes `sum_i w_i r_i` from the strategy's weights and the close frame.

## What remains unresolved

- **Panel P&L is still net-exposure based, not book based (the defect Phase 1 measured,
  not fixed).** The engine still prices a panel as `net_exposure x mean(asset returns)`.
  Measured above: a book with gross exposure 0.73 earned **+29.0%** while the engine
  reported **+13.8%**; on the walk-forward summary the book earned **-2.2%** against a
  reported **+6.6%**; on the held-out out-of-sample window the book earned **-0.6%**
  against a reported **+4.4%**. The sign of the gap is not even stable, so the
  net-exposure convention is not a conservative approximation — it is a different
  strategy.
- **Panel book rotation is still charged no market impact.** Same root cause: the
  impact model sees `|d net exposure|` only. Measured: gross turnover 0.188 vs charged
  0.0003 (a ~600x under-charge) on the 4-asset panel; 0.169 vs 0.004 on the
  walk-forward aggregate.
- **A market-neutral book still cannot be backtested.** `run_backtest.py` raises
  ("never takes a position") for the symmetric-quantile cross-sectional momentum, and
  the walk-forward / CPCV grid search skips every such combination via `signals_active`.
  The error message now explains the situation, but the strategy still cannot run.
- **Dual momentum is priced at a fraction of its own book.** The book is fully invested
  (`net_exposure` 0.92) while the engine prices 0.18 — a 5x exposure understatement,
  reported by the diagnostic as `net_exposure` vs `framework_net_exposure`.
- **Position warmup divergence (carried over, unchanged).** `run_backtest.py` uses
  `positions = signals.shift(1 + latency).fillna(0)` (the first entry *is* charged);
  `walk_forward.py` uses `positions = signals.shift(1 + latency) * fill_rate` (the first
  defined position is entered for free and the bar is dropped). Documented in
  `references/cost_models.md`; intentionally unchanged because it alters published
  numbers.
- **Panel trade ledger is an approximation** (priced on the mean constituent close).
  Documented.
- **The diagnostic is a measurement, not a correction.** Any conclusion drawn from a
  panel backtest today must still be stated as "under the net-exposure convention",
  with the book numbers reported next to it.

## Approaches already failed / why (this session and prior sessions)

- Calling `compute_book_diagnostic` before the return series exists (with
  `framework_returns=None`): the helper defines the measurement window from the
  framework's return index, so it returned `None` and the guard's book note was empty.
  Fixed by computing the diagnostic *after* the returns and computing an
  exposure-only variant inside the guard branch.
- Leaving the "never takes a position" guard before the `--latency` / `--fill-rate`
  resolution: the fill-rate range check then ran after the guard. Reordered so the
  argument check comes first (the only behaviour change is *which* error a run with
  both problems reports).
- Feeding a wide MultiIndex CSV to the `--multi-symbol` CLI: `load_multi_symbol`
  requires a long-format file with a `symbol` / `ticker` column. The CLI test fixture
  was rewritten to long format.
- Re-running the quantile validation inside `generate_target_weights`: the symmetric-
  quantile warning was then emitted twice per run (attributed to two different frames
  by `stacklevel=3`). The validation call was removed from the accessor — it is a
  measurement helper, and the signal path already warns.
- Printing the *aggregate* (validation + test) diagnostic in the out-of-sample CLI next
  to the held-out test performance: misleading. The CLI now prints the test window's own
  diagnostic; both per-split diagnostics and the aggregate stay in the summary JSON.
- (Prior sessions, unchanged) Reusing the old pseudo-asset panel shape for impact
  unification: not equivalent to the per-asset model; rejected. Making walk-forward and
  run_backtest fully identical: would change the single-asset position warmup and every
  published number; not attempted; the residual difference is documented and asserted.

## Next task (precise, bounded, evidence-based)

**Phase 2: make the panel path book-aware — behind an explicit, opt-in mode so the
published numbers stay put.**

Problem (measured above): the panel path cannot represent or price a long/short book.
The strategy interface returns one scalar per period (net exposure) and
`build_market_model` prices the portfolio as `net_exposure x mean(asset returns)`, so
(a) a market-neutral book is indistinguishable from a flat book (the flagship
cross-sectional strategy cannot be backtested at its default parameters),
(b) the P&L reported is not the P&L of the book the strategy holds (measured: +29.0% vs
+13.8%, and the sign of the gap is not stable), and (c) book rotation is charged no
impact (~600x under-charge measured). Phase 1 made all three *visible*; this task
changes the *model*.

Work items:

1. Add an explicit panel pricing mode, e.g. `--panel-pricing {net-exposure,book}` on
   `run_backtest.py` and the `walk_forward.py` subcommands, with **`net-exposure` as the
   default** so every published number and every pinned test value stays identical.
   In `book` mode the portfolio return per period is the true book return
   `sum_i w_i r_i` from the strategy's `generate_target_weights` (falling back to
   `net-exposure` pricing, with an explicit message, for a strategy that exposes no
   book).
2. In `book` mode, the "takes a position" test must be **book-aware**: a market-neutral
   book is a position (`sum_i |w_i| > 0`), so the symmetric-quantile cross-sectional
   momentum becomes backtestable and is no longer skipped by the grid search. Keep
   `signals_active` untouched for the `net-exposure` mode.
3. Keep the cost and impact model unchanged in this task (the impact model still sees
   `|d net exposure|`), and **report the missing impact explicitly**: in `book` mode,
   also print/report the book's gross turnover next to the turnover the model charges
   (the Phase 1 diagnostic already computes both — reuse it, do not add a second
   implementation).
4. Tests: the `net-exposure` mode must stay bit-identical to today's numbers (assert
   against the pinned values `cpcv total_oos_return == 0.005399536978800246` and the
   walk-forward `0.042594...`); in `book` mode the symmetric-quantile cross-sectional
   momentum must backtest instead of raising, and its reported return must equal the
   book return recomputed by hand; the two modes must differ on a panel with
   dispersion, with the difference equal to the Phase 1 `return_gap`.
5. Document the mode and the measured difference in `references/cost_models.md` and
   `SKILL.md`, and state explicitly which mode produced which number.

Out of scope for this task (needs its own handoff, because it changes the pinned
numbers): flipping the default to `book`, and charging market impact on gross turnover
`sum_i |dw_i| x equity` per asset against that asset's own ADV (Phase 2b). The
interaction with the panel capacity convention (equal-weight basket, least liquid binds)
must be re-checked before the impact model is touched.

Constraints: the `net-exposure` mode must stay bit-identical; existing keys keep their
names and numbers; the full suite must stay green; the market-impact model and the
panel capacity convention must not change in this task.

Relevant files: `skills/quantitative-backtesting/scripts/strategy_builder.py`
(`generate_target_weights`, `CrossSectionalMomentum`, `DualMomentumStrategy`),
`scripts/utils.py` (`build_market_model`, `compute_book_diagnostic`,
`aggregate_book_diagnostics`), `scripts/run_backtest.py` (the guard and the position
convention), `scripts/walk_forward.py` (`_calculate_strategy_returns`, `signals_active`
skips in the grid search, the per-period / per-fold records),
`scripts/reporting.py` (tear-sheet tables), `tests/test_run_backtest.py`,
`tests/test_walk_forward.py`, `tests/test_cpcv.py`, `tests/test_strategy_builder.py`.

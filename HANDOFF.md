# HANDOFF

## What changed this session

Executed the prior handoff's next task — **Phase 2b: cost the book, not the net exposure.**
The `--panel-pricing book` mode no longer returns an *uncosted* book number: the
transaction, borrow, funding and market-impact costs of a book are now charged on the
book itself, the trade ledger is built from the book, and the "book-mode results are an
upper bound" caveat is gone. The `net-exposure` mode is **bit-identical** to the previous
commit (verified key by key against `HEAD`).

### Core: `skills/quantitative-backtesting/scripts/utils.py`

New shared book cost model (single source of truth for both CLI paths):

- `held_book_weights(..., warmup="zero"|"nan")`: the book actually held. The new
  `warmup="nan"` reproduces the walk-forward path's "the first defined position is
  entered for free and its bar is dropped" convention, so the book mode reports the
  same bars as the net-exposure mode in every path.
- `book_gross_turnover(held)`: `sum_i |dw_i|` (`.sum(axis=1, min_count=1)` so a
  NaN-warmup row stays `NaN` instead of collapsing to 0).
- `book_cost_components(held, commission, slippage, borrow_cost, funding_cost,
  ann_factor)`: transaction on the **gross turnover**, borrow on the **short legs**
  `sum_i max(-w_i, 0)`, funding on the **gross exposure** `sum_i |w_i|`.
- `book_market_impact_cost(held, raw_returns, close, volume, impact_coefficient,
  adv_window, initial_capital)`: per asset `|dw_i| x equity` against **that asset's own
  ADV**; the portfolio cost is the equal-weighted mean of the per-asset impacts (the
  same panel convention the net-exposure model uses, so the two modes stay on one scale).
- `book_trade_ledger(held, close)`: one round trip per asset and direction, priced at
  the asset's own close; a *size* change does not close a trade (the cross-sectional
  book resizes whenever the number of valid constituents changes). `pnl` is the average
  weight times the price move (the sign is carried by the weight, so a losing short
  records a negative P&L); `return` is that P&L over the entry price.
- `book_return_from_held(held, close)`: the book return `sum_i w_i r_i`
  (`book_return_series` is now a thin wrapper over it).
- `compute_book_diagnostic(..., pricing_mode=...)` now reports **`charged_turnover`**
  (the turnover the cost model actually charged) and **`cost_basis`**; the aggregate
  `aggregate_book_diagnostics` carries both, plus **`reported_total_return`** (the
  cumulative return the run actually reported — in `book` mode that is the *costed*
  book return, not the framework's).

### Core: `skills/quantitative-backtesting/scripts/run_backtest.py`

- The held book is computed **once** and is the single source of truth for the book-mode
  return *and* the book-mode cost basis (they can no longer disagree).
- The cost block branches: `book` mode uses `book_cost_components` +
  `book_market_impact_cost`; `net-exposure` mode keeps the previous code path
  unchanged, line for line.
- The trade ledger branches: `book` mode uses `book_trade_ledger`; `net-exposure` mode
  keeps the previous scalar extractor unchanged.
- CLI: the "Panel Book Diagnostic" block now prints the *charged* turnover and the cost
  basis, and the book-mode note states the residual approximations instead of the old
  "upper bound" warning. The `--panel-pricing` help text was rewritten.

### Core: `skills/quantitative-backtesting/scripts/walk_forward.py`

- `_calculate_strategy_returns` branches the same way. In `book` mode it uses the
  **NaN-warmup** book for the cost basis, which reproduces the path's warmup treatment
  exactly (the first book change is not charged and its bar is dropped), and it
  reindexes the result onto `positions.dropna().index` so the two modes report the
  same bars.
- The diagnostic call sites carry `panel_pricing=panel_pricing` (walk-forward periods,
  CPCV folds, out-of-sample validation/test splits).
- The CLI help and the book-diagnostic printer were updated as in `run_backtest.py`.

### Core: `skills/quantitative-backtesting/scripts/reporting.py`

- The tear sheet's "Panel Pricing" section and "Panel Book Diagnostic" table were
  rewritten: the book mode now states that the *costs* are charged on the book, and
  lists the residual approximations (mean-over-panel impact, basket-based capacity).
- The capacity row is labelled `Strategy Capacity (Notional, basket-based)` in book
  mode, so the approximation is visible where the number is read.

### Docs

- `references/cost_models.md`: new section **"The book cost basis"** (a per-cost table
  of the two bases, the impact model, and the size of the correction) and **"Residual
  approximations in `book` mode"** (mean-over-panel impact, basket-based capacity with
  the book-based formula written out, the ledger's non-reconciliation, the linear impact
  model). The "what does NOT change in `book` mode" paragraph was replaced.
- `references/validation_methods.md`, `SKILL.md`: the pricing-mode descriptions now say
  that the mode selects how a panel is priced **and costed**.

### Tests

- `tests/test_run_backtest.py`: 6 new tests
  (`..._charges_the_gross_turnover_of_the_book`, `..._charges_borrow_on_the_short_leg`,
  `..._market_impact_scales_with_the_fill_rate`, `..._builds_a_trade_ledger`,
  `test_book_trade_ledger_prices_each_leg_at_its_own_close`,
  `..._net_exposure_numbers_are_unchanged_by_the_book_cost_basis`).
- `tests/test_walk_forward.py`: 2 new tests
  (`test_calculate_strategy_returns_book_mode_charges_the_book_turnover`,
  `test_walk_forward_book_pricing_charges_the_book_costs`).
- The charged amounts are recomputed **by hand** from the strategy's own weights, so
  the tests do not compare the engine against itself.

## What was actually verified

- **Full suite green**: `python -m pytest skills/quantitative-backtesting/tests/ -q`
  -> **479 passed** (was 471; +8 new). The three standalone runners
  (`python tests/test_run_backtest.py` -> 90/90, `tests/test_walk_forward.py` -> 172/172,
  `tests/test_cpcv.py` -> 28/28) also pass.
- **Net-exposure bit-identity**: a HEAD-vs-new snapshot harness (a 5-asset panel with
  `impact_coefficient=0.5`, `borrow_cost=0.03`, `funding_cost=0.02`) compared the
  single-backtest, walk-forward, CPCV and out-of-sample paths key by key. The **only**
  differences are 3 *additive* diagnostic keys (`charged_turnover`, `cost_basis`,
  `reported_total_return`) in 14 diagnostic records. **No number moved.**
  The harness is at `/home/runner/work/_temp/kilo-tmp/kilo/` (outside the repo):
  `parity_probe.py` (dump), `compare_snapshots.py` (diff), `head_repo/` (the extracted
  `HEAD` tree).
- **The book mode now costs the book**: on a 900-bar 5-asset market-neutral
  cross-sectional book (commission 2bps + slippage 1bps, borrow 3%, impact 0.5):
  the reported total return moves from **+16.3% (uncosted book) to -15.7% (costed
  book)**; the charged turnover moves from `0.0000` (the flat net exposure) to
  `0.1437` (the book's gross turnover); the mean borrow charge is `2.3 bps/period`
  and the mean impact charge `0.6 bps/period`. The hand-recomputed
  `book return - (gross turnover x (commission + slippage) + borrow + impact)`
  reproduces the reported total return to `1e-12`.
- **CLI smoke tests**: `run_backtest.py --panel-pricing book --multi-symbol` and
  `walk_forward.py cpcv --panel-pricing book --multi-symbol` both run end to end and
  print the new diagnostic block; `verify_end_to_end.py` and `test_import.py` at the
  repo root still pass.

## What remains unresolved

1. **The impact model is still the mean over the whole panel.** A period in which only
   `k` of `n` names trade is charged the mean over `n` names, so the drag is diluted
   relative to the participation actually consumed. The convention was kept identical to
   the net-exposure path so the two modes stay comparable; the conservative alternative
   is the mean over the *traded* names (or a sum).
2. **The capacity estimate is still basket-based.** `estimate_capacity` assumes an
   equal-weight basket whose least liquid constituent binds. The book-based estimate is
   `min_i ( max_impact x ADV_i / (|dw_i| x impact_coefficient) )`; the two agree exactly
   for a book that rebalances `1/n` per constituent and differ for any other book (a
   concentrated book has a *lower* capacity than the basket rule reports). **Decision
   taken this session: keep the basket-based number (so no published number moves) and
   flag the approximation** in the CLI, the tear sheet and `cost_models.md`.
3. **The book trade ledger does not reconcile with the equity curve.** `pnl` is in
   price units scaled by the average weight, `return` is the leg's contribution to the
   portfolio return; the ledger ignores compounding and transaction costs.
4. **The book-mode numbers are not published anywhere yet.** They were introduced last
   session and are still unpublished, so the +16.3% -> -15.7% change breaks no
   published number — but it does mean any *pending* book-mode result in the repo must
   be recomputed.
5. Not attempted (out of scope, no evidence of a defect): the `mean-of-per-asset-
   impacts` convention itself, the walk-forward/CPCV *grid search* being scored on the
   book's costed returns (it is, in book mode, but the selection criterion was not
   re-examined), and a book-aware capacity estimator.

## Approaches that have already failed (do not repeat)

- **Charging the book's costs but keeping the net-exposure impact** is what the previous
  session left behind; it under-charges by ~900x on the turnover and is what Phase 2b
  fixed. Do not reintroduce a "the cost model is identical in both modes" note: it is
  false now.
- **A "second implementation" of the book model inside `run_backtest.py` /
  `walk_forward.py`** was avoided deliberately: both paths call the same `utils`
  functions, otherwise the two CLIs would drift (that drift is exactly what the
  cross-path parity tests exist to catch).
- **`book_trade_ledger` with the net-exposure "any change is a trade boundary" rule**
  was tried and rejected: the cross-sectional book resizes its weights whenever the
  number of valid constituents changes, which would bury the ledger in one-bar,
  zero-P&L records. The sign-based round trip is used instead.
- **`held_book_weights` with a single warmup convention** was tried and does not work:
  `run_backtest.py` charges the first entry (its position series is `fillna(0)`) while
  `walk_forward.py` drops that bar (its position series is `NaN`). The `warmup`
  parameter exists to reproduce each path's own convention.

## Next task (one precise, bounded item)

**Implement the book-based capacity estimate and report it next to the basket-based
one, without changing any existing number.**

- Evidence: `skills/quantitative-backtesting/scripts/utils.py::estimate_capacity` is
  the basket rule (`capacity = n_assets * max_impact * min_i(ADV_i) /
  impact_coefficient`); the book-based rule is
  `min_i ( max_impact * ADV_i / (|dw_i| x impact_coefficient) )`, i.e. the equity
  level at which rebalancing asset `i` hits the impact threshold. The formula and the
  reason are written out in `skills/quantitative-backtesting/references/cost_models.md`
  ("Residual approximations in `book` mode").
- Constraint: `results["capacity"]` / `summary["capacity"]` keep their meaning and
  their numbers in **both** modes (the net-exposure mode must stay bit-identical — see
  the verification method above). Add a *new* key (e.g. `capacity_book`) that is
  `None` in `net-exposure` mode and carries the book-based estimate (point in time +
  the existing `capacity_trend` distribution) in `book` mode, and surface it in the CLI
  and the tear sheet next to the basket-based number.
- The book is available where the capacity is computed: `run_backtest.py` has the held
  book; in `walk_forward.py` the per-window book is built by `_window_book_diagnostic`
  (the per-period capacity is computed per window from `period["test_data"]`), so the
  per-window held book has to be threaded to the per-window capacity computation.
- Verify: the new tests must recompute the book capacity by hand from the strategy's
  own weights (as the Phase 2b tests do), and the HEAD-vs-new harness must still show
  **zero** changed numbers in the `net-exposure` mode.

**Files touched this session** (all under `skills/quantitative-backtesting/`):
`scripts/utils.py`, `scripts/run_backtest.py`, `scripts/walk_forward.py`,
`scripts/reporting.py`, `references/cost_models.md`, `references/validation_methods.md`,
`SKILL.md`, `tests/test_run_backtest.py`, `tests/test_walk_forward.py`, plus
`HANDOFF.md` / `HANDOFF_NEXT.md` at the repo root.

**Git state: the work is in the working tree and is NOT committed** (the session did
not get an explicit instruction to commit, and mutating git commands need a separate
confirmation). `git status` shows 11 modified files, nothing untracked, no unrelated
edits. The next session should review the diff and commit it as one checkpoint, e.g.
`git add -A && git commit -m "Cost the book, not the net exposure, in book pricing mode"`.

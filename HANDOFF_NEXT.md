# HANDOFF

## What changed this session

Executed the prior handoff's next task — **Phase 2c: the book-based capacity estimate,
reported next to the basket-based one.** The `book` pricing mode now reports *two*
capacity numbers: the framework's basket-based estimate (unchanged, unchanged meaning,
unchanged numbers) and a new book-based estimate computed from the trade sizes the
strategy actually executes. The `net-exposure` mode is **bit-identical** to the previous
commit (verified key by key against `HEAD`, in both pricing modes).

### Core: `skills/quantitative-backtesting/scripts/utils.py`

- **`book_capacity_estimate(held_book, close, volume, impact_coefficient,
  max_impact=0.0005, adv_window=20)`** (new). The direct inversion of the impact model
  the book mode charges: the impact of asset `i` at equity `E` is
  `|dw_i| x E x impact_coefficient / ADV_i`, so the equity at which that trade hits the
  threshold is `max_impact x ADV_i / (|dw_i| x impact_coefficient)`, and the capacity of
  the book is
  `min_i ( max_impact x ADV_i / (|dw_i| x impact_coefficient) )`
  over the constituents that actually traded in that period. It returns the
  point-in-time reading (`estimated_capacity`), the per-period series
  (`capacity_series`), the distribution (`capacity_trend`), the `binding_asset` and
  `n_periods_measured`. It is `None` when impact is disabled, when there is no volume,
  or when the book never traded.
- **`_capacity_trend_from_series`** moved here from `walk_forward.py` (verbatim, no
  behaviour change) so the estimator and the analysis paths share one implementation
  instead of two copies. `walk_forward.py` re-imports it, so
  `walk_forward._capacity_trend_from_series` still resolves.

### Core: `skills/quantitative-backtesting/scripts/walk_forward.py`

- `_window_held_book(...)` (new): the book the selected strategy holds in one window
  (`lag = 1 + latency`, `fill_rate`), plus its market model — the same convention the
  book diagnostic and the book cost model measure.
- `_window_book_capacity(...)` (new): the book capacity of one window.
- `_merge_capacity_series(...)` (new): merges the per-window capacity series by
  timestamp. Each window's series is computed **inside its own window**, so merging
  creates no artificial trade at a window boundary.
- Wiring: `periods[i]["capacity_book"]` / `["capacity_book_trend"]` (walk-forward),
  `folds[i]["capacity_book"]` / `["capacity_book_trend"]` (CPCV),
  `validation_performance` / `test_performance` (out-of-sample), plus
  `summary["capacity_book"]`, `summary["capacity_book_trend"]` and
  `summary["oos_min_capacity_book"]` on the walk-forward and CPCV summaries. The
  CLI artifacts (`capacity_per_period`, `capacity_per_fold`) carry the new keys.
- CLI: a `Capacity (market impact):` block (basket-based and book-based, plus the
  worst reading and the worst out-of-sample window) — printed **only** when the
  book-based number exists, so the `net-exposure` output is unchanged.

### Core: `skills/quantitative-backtesting/scripts/run_backtest.py`

- `results["capacity_book"]` / `results["capacity_book_trend"]` (mirrored into
  `metrics`), computed from the held book the engine already builds. The CLI prints the
  two capacity numbers and the strategy's capital as a multiple of the book capacity.
- The book-mode note no longer claims the capacity stays basket-based.

### Core: `skills/quantitative-backtesting/scripts/reporting.py`

- Tear sheet: `Strategy Capacity (Notional, book-based)` and
  `Strategy Capacity Min (Notional, book-based)` rows (single backtest, walk-forward,
  CPCV), a `Capacity Book (Notional)` column in the per-period and per-fold tables
  (added **only** when at least one window produced a book capacity, so the default
  tear sheet is unchanged), and `capacity_book_trend` in `tear_sheet_summary.json`.

### Docs

`references/cost_models.md` (new section "Two capacity estimates"; the capacity is no
longer listed as a residual approximation of `book` mode), `references/validation_methods.md`
(the new summary keys), `SKILL.md` (the two capacity conventions, the new keys, the
test coverage).

## What was actually verified

- **Full suite**: `python -m pytest tests/ -q` -> **487 passed** (was 479; +8 new).
  The three standalone runners also pass: `python tests/test_run_backtest.py` ->
  95/95, `python tests/test_walk_forward.py` -> 175/175, `python tests/test_cpcv.py` ->
  28/28.
- **Bit-identity (the harness the previous session built)**: the HEAD-vs-new snapshot
  harness (`/home/runner/work/_temp/kilo-tmp/kilo/parity_probe.py` +
  `compare_snapshots.py`) was run in **both** pricing modes against the final tree.
  `head_repo2/` is the extracted `HEAD` tree (`5a8293f`, the Phase 2b commit);
  `head_repo/` is the older extraction the previous session used — use `head_repo2/`.
  The probe takes the pricing mode as a third argument (`net-exposure` or `book`):
  - `net-exposure`: **28 differing leaves, all of them the new `capacity_book*` keys**
    (all `None` in that mode). **No existing number moved.**
  - `book`: **30 differing leaves, all of them the new `capacity_book*` keys**.
    **No existing number moved.**
- **Methodological properties (new tests, recomputed by hand from the strategy's own
  weights, not from the engine)**:
  - The book capacity **equals the basket capacity exactly** for a book that trades
    `1 / n_assets` per constituent every period (the basket rule is that special
    case) — `test_book_capacity_equals_the_basket_capacity_for_a_one_over_n_book`.
  - A book that trades **more** per period supports **less** capital: a book that
    rotates the whole notional through the least liquid name supports exactly
    `n_assets` times less than the basket rule reports —
    `test_book_capacity_is_lower_for_a_book_that_trades_more`.
  - The reported number is the equity level at which the **worst** trade of the
    point-in-time bar reaches the 5 bps threshold and no other trade exceeds it —
    `test_run_backtest_reports_the_book_capacity_next_to_the_basket_one`.
  - The per-window number of the walk-forward path matches a hand recomputation from
    the strategy's own weights in that window —
    `test_walk_forward_reports_the_book_capacity_per_window_and_summary`; the CPCV
    path reports it per fold — `test_cpcv_reports_the_book_capacity_per_fold`.
  - The keys are `None` outside the `book` mode —
    `test_run_backtest_book_capacity_is_absent_in_the_net_exposure_mode`,
    `test_walk_forward_book_capacity_is_absent_in_the_net_exposure_mode` — and `None`
    when impact is disabled — `test_book_capacity_is_none_when_impact_is_disabled`.
- **End-to-end numbers** (900-bar 5-asset market-neutral cross-sectional book,
  commission 2 bps + slippage 1 bps, borrow 3 %, impact coefficient 0.5,
  `run_backtest.py --panel-pricing book --multi-symbol`):
  basket capacity `3,248,736.88` vs **book capacity `4,197,791.02`**, worst reading
  in the window `1,870,360.08`; the strategy trades `100,000` of equity, i.e.
  `0.02x` the book capacity. The book capacity is *higher* here because this book
  rotates less than the basket rule assumes (it only trades when its constituent set
  changes) — that is the honest reading, not an error.
  The walk-forward path on the same data: basket `3,248,736.88`, book `3,032,075.71`,
  worst out-of-sample window `1,870,360.08`.
- **CLI smoke tests**: `run_backtest.py --panel-pricing book --multi-symbol` and
  `walk_forward.py walk-forward --panel-pricing book --multi-symbol` both run end to
  end and print the new capacity block; the walk-forward artifact carries
  `capacity_book` / `capacity_book_trend` per period.

## What remains unresolved

1. **The impact model is still the mean over the whole panel.** A period in which only
   `k` of `n` names trade is charged the mean over `n` names, so the drag is diluted
   relative to the participation actually consumed. This is the largest remaining
   assumption in the book-mode numbers (the book-mode P&L is flattered by it) and it is
   *not* fixed by the new capacity estimate. See "Next task".
2. **The book-based capacity is reported in the `book` mode only.** The numbers would
   be identical in `net-exposure` mode (the weights and the ADV do not depend on the
   pricing mode), so it *could* be reported as a measurement in both modes. It was left
   out deliberately so the default path keeps a single capacity number and the default
   artifacts stay unchanged.
3. **The book capacity uses the `warmup="zero"` book** (the establishment of the book
   is a real trade), while the walk-forward *cost* basis uses the NaN-warmup book (the
   first book change is entered for free and its bar is dropped). The two therefore
   differ in the first bar of every window. The capacity reading is the *last* bar on
   which the book traded, so this only matters for a window with a single trade.
4. **The book trade ledger does not reconcile with the equity curve** (`pnl` is in
   price units scaled by the average weight; the ledger ignores compounding and
   transaction costs). Unchanged from last session.
5. **The book-mode numbers are still unpublished**, so the capacity addition breaks no
   published number.
6. Not attempted (out of scope, no evidence of a defect): the `mean-of-per-asset-
   impacts` convention itself, the walk-forward/CPCV *grid search* being scored on the
   book's costed returns (it is, in book mode, but the selection criterion was not
   re-examined), and a break-even-capital ("at what capital does the net edge
   disappear?") report.

## Approaches that have already failed (do not repeat)

- **"A constant 1/n book has the basket capacity."** Wrong assumption, and it fails
  silently: a *constant* book never trades after its establishment, so the estimator
  reports no capacity at all (`None` — "the book never traded"). The two rules agree
  only for a book that *trades* `1/n` per constituent every period. The test builds
  one deliberately (the book alternates between flat and `1/n`).
- **Asserting that the *minimum* impact over the traded assets equals the threshold.**
  At the reported capacity the *binding* (least liquid) asset has the **maximum**
  impact, exactly `max_impact`; the most liquid traded asset has the minimum. The
  test now asserts `max == max_impact` and `max <= max_impact`.
- **"A concentrated book has exactly `n_assets` times less capacity."** Only true when
  the name that trades is also the least liquid one: the basket rule binds on the
  least liquid *name*, the book rule on the name that *trades*. The test makes the
  traded name the least liquid so the factor is exact.
- **Building a whole-sample book by concatenating the per-window books.** Rejected: it
  creates an artificial unwind/establishment trade at every window boundary, and those
  bars would carry the *smallest* capacity readings (the strategy never faced them).
  The per-window series are computed inside their own window and merged by timestamp
  instead.
- **Duplicating the capacity-trend helper** in `utils.py` and `walk_forward.py` was
  avoided: the helper was *moved* (imported by `walk_forward.py`) so there is one
  implementation, otherwise the two would drift.

## Next task (one precise, bounded item)

**Quantify the participation dilution of the panel impact model — measure, do not
change the charged costs.**

- Evidence: `skills/quantitative-backtesting/scripts/utils.py::book_market_impact_cost`
  charges the **equal-weighted mean over the whole panel** of the per-asset impacts
  (over `n` names), so a period in which only `k` of `n` names trade is charged
  `1/n` of the participation it actually consumed. For the cross-sectional book the
  constituent set changes often, so many periods trade only some names. The same
  dilution applies to the net-exposure path (`market_impact_cost`). This is the
  largest remaining *assumption* in the book-mode numbers, and it is currently only
  flagged in prose ("Residual approximation: the impact stays the equal-weighted
  mean of the per-asset impacts over the whole panel").
- Scope: add a **measurement only** (the repo's established pattern, cf. the panel
  book diagnostic) that reports, next to the charged impact, the impact the *traded*
  names would have paid (the mean over the traded names only) and the difference in
  bps per period and as a fraction of the gross book return. Surface it in the book
  diagnostic (both pricing modes), the CLI block, the tear sheet and
  `references/cost_models.md`. **No charged cost, return, capacity or Sharpe number
  may move** — the net-exposure path must stay bit-identical.
- Decide from the measurement whether the conservative convention (the mean over the
  traded names) should become the *default*; if it does, that is a separate,
  number-changing change and must be flagged as such (it would change the published
  book-mode return of -15.7 %).
- Verify: the new tests must recompute the diluted impact by hand from the
  strategy's own weights, and the HEAD-vs-new harness must still show **zero**
  changed numbers in the `net-exposure` mode (the harness described above is at
  `/home/runner/work/_temp/kilo-tmp/kilo/`).

**Files touched this session** (all under `skills/quantitative-backtesting/`):
`scripts/utils.py`, `scripts/run_backtest.py`, `scripts/walk_forward.py`,
`scripts/reporting.py`, `references/cost_models.md`, `references/validation_methods.md`,
`SKILL.md`, `tests/test_run_backtest.py`, `tests/test_walk_forward.py`, plus
`HANDOFF.md` / `HANDOFF_NEXT.md` at the repo root.

**Git state: the work is in the working tree and is NOT committed** (the session did
not get an explicit instruction to commit, and mutating git commands need a separate
confirmation). `git status` shows 11 modified files, nothing untracked, no unrelated
edits. The next session should review the diff and commit it as one checkpoint, e.g.
`git add -A && git commit -m "Report the book-based capacity next to the basket-based one"`.

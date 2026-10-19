# HANDOFF

## What changed this session

Executed the prior handoff's next task — **quantify the participation dilution of
the panel impact model: measure, do not change the charged costs.** The panel impact
model charges the **equal-weighted mean over all `n` panel names** of the per-asset
impacts, so a period in which only `k` of `n` names trade is charged `1 / n` of the
participation its traded names consumed. That approximation used to be flagged in
prose only; it is now **measured and reported next to the impact the run charged**,
in both pricing modes, in the CLI output, in the tear sheet and in the artifacts.

**No charged cost, return, capacity or Sharpe number moved.** The HEAD-vs-new
parity harness shows **zero** changed numbers in the `net-exposure` mode *and* in the
`book` mode: the only differences are the 112 new additive `impact_*` keys (see
"Verification").

### Core: `skills/quantitative-backtesting/scripts/utils.py`

- **`impact_participation_dilution(held_book, raw_returns, close, volume,
  impact_coefficient, adv_window=20, initial_capital=100000.0, index=None)`**
  (rewritten; a partial version of it was left unused in commit `9a1db4d`). Measures
  three aggregations of the *same* per-asset impact model
  (`rate_i = |dw_i| x equity / ADV_i x coefficient`):
  - `panel` — the equal-weighted mean over all `n` names: the convention the engine
    charges in `book` mode (a name that did not trade contributes zero);
  - `traded_only` — the equal-weighted mean over the `k` names that actually traded:
    the participation the traded names consumed;
  - `notional_weighted` — `sum_i rate_i x notional_i / equity`: the *dollar-consistent*
    aggregation of a linear impact model (the impact rate of each name applied to
    the notional traded in that name).
  It also returns `n_traded`, `participation_ratio` (`k / n`), `traded_fraction`
  (`f`, the traded notional as a fraction of the equity) and `dilution`
  (`panel - traded_only`). Two identities make it auditable, and both are asserted
  by the tests: `panel == (k / n) x traded_only` (the dilution factor is exactly the
  fraction of names that traded) and `notional_weighted == f x traded_only` when the
  traded names trade equal notionals.
- **`_impact_dilution_keys(...)`** (new): turns the measurement into the diagnostic
  scalars, choosing the *charged* impact by pricing convention (the panel mean of
  the book's own impacts in `book` mode, the `|d net exposure|` model in
  `net-exposure` mode) and computing the "as a fraction of the gross book return"
  reading (only when the book earned a positive gross return, where the ratio would
  be a sign-flipping artifact).
- **`format_impact_dilution_lines(diagnostic, indent)`** (new): the shared CLI
  block, used by both entry points so the two CLIs print the same lines.
- **`compute_book_diagnostic(...)`** gains the optional `impact_coefficient`,
  `adv_window` and `initial_capital` arguments and reports the measurement:
  `impact_charged_bps`, `impact_traded_only_bps`, `impact_notional_weighted_bps`,
  `impact_dilution_bps`, `impact_panel_dilution_bps`, `impact_gross_book_return_bps`,
  `impact_dilution_fraction_of_gross_return`, `impact_participation_ratio` (all
  `None` when impact is disabled).
- **`aggregate_book_diagnostics(...)`** aggregates the new keys with the period
  weighting and recomputes the ratio from the aggregated bps values (the aggregate
  is the ratio of the aggregates, not an average of ratios). The keys are always
  present (`None` when the measurement does not apply), so a consumer never has to
  guess whether a missing key means "not measured" or "not reported".

### Wiring

- `scripts/run_backtest.py`: the diagnostic is called with the run's own impact
  parameters; the CLI prints the impact participation block under the panel book
  diagnostic.
- `scripts/walk_forward.py`: `_window_book_diagnostic(...)` takes the impact
  parameters and passes them through; the four call sites (walk-forward periods, CPCV
  folds, out-of-sample validation and test) pass the run's values; the shared
  `_print_book_diagnostic` prints the impact block.
- `scripts/reporting.py`: the tear sheet renders the impact rows (only when the
  measurement exists, so the default tear sheet is unchanged).

### Tests (all new tests recompute the numbers by hand from the strategy's own weights)

- `tests/test_run_backtest.py`:
  `test_impact_participation_dilution_matches_the_hand_computed_aggregations`
  (the three aggregations and both identities on a hand-built book),
  `test_run_backtest_reports_the_impact_participation_next_to_the_charged_impact`
  (the reported numbers vs a hand computation from the strategy's own weights, and
  the run's own charged impact), `test_impact_participation_is_reported_in_both_pricing_modes`
  (the traded-only reading is the same under both conventions, which is what makes
  the two comparable), `test_impact_participation_is_absent_when_impact_is_disabled`,
  and `test_impact_participation_does_not_move_any_charged_number` (the reported
  return equals the book return minus the hand-computed transaction, borrow, funding
  and impact costs).
- `tests/test_walk_forward.py`:
  `test_walk_forward_reports_the_impact_participation_per_window_and_summary` (per
  window vs a hand computation; the summary is the period-weighted aggregate) and
  `test_walk_forward_impact_participation_is_absent_when_impact_is_disabled`.
- `tests/test_reporting.py`:
  `test_tear_sheet_renders_the_impact_participation_measurement` and
  `test_tear_sheet_omits_the_impact_rows_without_an_impact_model`.

### Documentation

- `references/cost_models.md`: a new section **"Market-impact participation
  (measurement only)"** with the definitions, the identities, the key table, the
  reference numbers, the decision and the caveat; the "Residual approximations in
  `book` mode" bullet now points at the measurement.
- `SKILL.md`: the `utils.py` inventory, the "panel-pricing book" residual bullet, a
  new best-practice bullet and the test-coverage paragraph.
- `references/validation_methods.md`: the new summary keys.

## The measurement, and the decision it supports

On the reference panel used throughout the documentation (900 bars, 5 assets, 2 bps
commission, 1 bps slippage, 3 % borrow, impact coefficient 0.5, $100k of equity):

| Reading | `book` mode | `net-exposure` mode |
| --- | --- | --- |
| charged by the model | 0.058 bps/period | 0.00007 bps/period |
| traded names would have paid | 0.131 bps/period | 0.152 bps/period |
| understatement (dilution) | -0.073 bps/period | -0.152 bps/period |
| notional-weighted (dollar) cost | 0.058 bps/period | 0.073 bps/period |
| names trading per period | 2.21 of 5 (ratio 0.44) | 2.29 of 5 (ratio 0.46) |
| gross book return | -1.03 bps/period | +1.56 bps/period |

1. **The dilution is exactly `n / k`** (44 % of the participation, the `k / n`
   factor and nothing else).
2. **The *cost* of the trades is not understated.** The book trades only
   `f = 44 %` of its equity in the `k` names it touches (it enters or exits one
   name at `1 / n` of the equity at a time), so the dollar-consistent cost
   `f x traded_only` is 0.058 bps/period — the same number the panel convention
   charges. For this family of books the panel convention is *not* an
   approximation of the dollar cost: the `k / n` dilution and the "only a fraction
   of the equity was traded" factor cancel exactly.
3. **The conservative alternative would overcharge.** Charging the mean over the
   traded names would cost 0.131 bps/period instead of 0.058 (2.26x the
   dollar-consistent cost), i.e. about 0.66 percentage points of the reported
   book-mode return (-15.68 % -> about -16.2 %). It is a *rate* comparison, not a
   cost comparison.

**Decision: the traded-only mean does _not_ become the default.** It is the
conservative reading of the *participation rate*, but it is not a cost: it
implicitly charges the whole equity in every name the book touched. The
dimensionally consistent aggregation of a linear impact model is the
notional-weighted one, and switching to it is a separate, number-changing change.
The engine keeps charging the panel mean and now *reports* the measurement, so the
size of the convention is visible in every artifact.

**Correction to the prior handoff's premise.** The dilution was described as "the
largest remaining assumption in the book-mode numbers". The cost decomposition of
the reference run (899 bars) shows it is not: transaction 0.489 bps/period
(123 bps/yr), borrow 0.233 bps/period (59 bps/yr), impact 0.058 bps/period
(15 bps/yr) — the impact term is 7 % of the charged cost, and the understatement
is about 0.66 pp of the -15.68 % return. The *relative* error in the impact term
is large (2.26x), but the term itself is small next to the transaction and borrow
costs at this capital level.

**Where the convention does bite.** The cancellation in (2) is a property of a book
that trades `1 / n` of the equity in each name it touches. A book that
*concentrates* (the whole notional moving in and out of one name) trades `f ~ 1`
in `k = 1` name, so the panel convention undercharges it by a factor of `n` while
the notional-weighted aggregation stays correct. The measurement distinguishes the
three cases, so a reader always knows which one they are in.

**Caveat.** The `impact_coefficient` is read here as a price concession rate (the
cost is the rate applied to the traded notional), which is what the "price
elasticity of the order book" description of the model implies. If it is meant as a
portfolio-level cost rate per unit of participation, the panel convention is the
intended one and the notional-weighted reading does not apply.

## What was actually verified

- **Full test suite**: `python -m pytest tests/ -q` -> **496 passed** (487 before
  this session; 9 new tests). The standalone runners also pass
  (`test_run_backtest.py` 100/100, `test_walk_forward.py` 177/177, `test_cpcv.py`
  28/28, `test_reporting.py`).
- **Parity harness** (`/home/runner/work/_temp/kilo-tmp/kilo/`): `head_repo3` is
  `git archive HEAD` (commit `9a1db4d`) and `parity_probe.py` dumps the
  `run_backtest` / `walk_forward` / `cpcv` outputs of both trees. The diff is
  **112 leaves in each mode, every one of them a new `impact_*` key that is missing
  in HEAD**; there is **no other difference** — no return, cost, capacity, Sharpe or
  bar-count change. Checked in the `net-exposure` mode *and* in the `book` mode.
  (The walk-forward OOS return is bit-identical: 0.045572663211203235 in
  `net-exposure`, -0.027351524036712926 in `book`.)
- **The published book-mode number is unchanged**: the reference panel reproduces
  **-15.68 %** (the documentation quotes -15.7 %), and the uncosted book return is
  -9.56 % (the documentation quotes the +16.3 % -> -15.7 % pair for a *directional*
  quantile set; the market-neutral book's own pre-cost return is -9.56 %).
- **The cross-path warmup question is settled**: the walk-forward's NaN-warmup book
  and the single backtest's zero-warmup book charge the *same* trades (the turnover
  sums over a window are identical, 7.40 vs 7.40), because the target weights are
  0 (not NaN) before the strategy is defined, so the book is flat at the start of
  every window in both conventions. The prior handoff's unresolved item 3 is
  therefore inert; no change is needed.

## What remains unresolved

- The **impact model's aggregation convention is still the panel mean** (by
  decision, with the measurement now reported). A concentrated book is still
  undercharged by up to a factor `n` by the *charged* number — the measurement
  reports it, but the engine still charges the panel mean.
- The **impact model is linear in the participation rate** and has no temporary /
  permanent split, no gap risk and no fill model. It is a sizing guard.
- The **`fill_rate` convention** (from the prior handoff) is still open: the
  framework scales the *position* by the fill rate, and the book mode scales the
  *book* by it too, so a 50 % fill rate halves the book and the traded notional
  instead of delaying the fill. It is pinned by a test
  (`test_run_backtest_book_pricing_market_impact_scales_with_the_fill_rate`) and
  changing it moves numbers.
- The reference artifacts in `test_output/` are **not** regenerated by this session
  (the default single-asset path is unchanged, so there is nothing to regenerate);
  a panel-mode artifact set does not exist in the repo yet.

## Approaches that have already failed (and why)

- **The partial `impact_participation_dilution` in commit `9a1db4d`** (an empty
  commit message, a function nothing called, no tests): it measured only the
  "traded-only mean" and framed the gap as an under-charge. It was rewritten
  because the traded-only mean is *not* a cost, and reporting it alone would have
  led to the wrong decision (see below). Do not restore it.
- **Switching the default to the mean over the traded names** (the "conservative"
  alternative the prior handoff proposed to evaluate): rejected on the evidence
  above — it would overcharge the impact by `n / k` for the books this framework
  produces. The conservative-looking number is the wrong number.
- **Reporting the dilution without the notional-weighted third reading**: rejected
  — with only two readings ("charged" vs "traded only") the natural conclusion is
  "the model undercharges, switch to the conservative convention", which the
  measurement shows to be wrong. The dollar-consistent third reading is what makes
  the decision correct.

## Next task (one precise, bounded item)

**Add the notional-weighted (dollar-consistent) impact as an _opt-in_ chargeable
convention, with the capacity rule that is consistent with it — and compare.**

- Evidence: the measurement now proves the current panel convention is
  *accidentally* right for the books this framework produces (`f = k / n`, so
  `panel == notional_weighted`: 0.0579 vs 0.0581 bps/period on the reference panel)
  and *wrong by a factor `n`* for a concentrated book (`f ~ 1`, `k = 1`), where the
  charged impact is `1 / n` of what the trade costs. The number is already computed
  and reported (`impact_notional_weighted_bps`), so only the *charging* path and
  the capacity inversion are missing. A framework that lets a user run a
  concentrated book must be able to charge it correctly.
- Scope: add an impact-aggregation option (e.g. `impact_aggregation =
  "panel" | "notional-weighted"`) to the impact cost path
  (`utils.market_impact_cost` / `utils.book_market_impact_cost` and their call
  sites in `run_backtest.py` and `walk_forward.py`), exposed on the CLI
  (`--impact-aggregation`), with the **default unchanged** (`"panel"`), so no
  published number moves. Add the matching capacity inversion for the
  notional-weighted model: the drag of asset `i` is
  `coefficient x (|dw_i| x E / ADV_i) x (|dw_i| x E) / E =
  coefficient x dw_i^2 x E / ADV_i`, so the equity at which the trade hits
  `max_impact` is `max_impact x ADV_i / (coefficient x dw_i^2)` — a *different*
  capacity rule from the current `max_impact x ADV_i / (|dw_i| x coefficient)`.
  Report both capacity numbers side by side (as the basket/book pair is reported
  today) and both impact readings in the diagnostic.
- Verify: (a) the charged impact of the new mode equals the already-measured
  `impact_notional_weighted_bps` (the measurement is the oracle);
  (b) the new mode's capacity is the exact inverse of the new charge (recomputed
  by hand from the strategy's own weights, as the existing book-capacity test does);
  (c) the HEAD-vs-new harness shows **zero** changed numbers with the default
  aggregation, in **both** pricing modes; (d) the full suite stays green.
- Do **not** change the default aggregation, and do **not** re-quote the published
  book-mode return (-15.68 %) without re-running the parity harness.

**Files touched this session** (all under `skills/quantitative-backtesting/`):
`scripts/utils.py`, `scripts/run_backtest.py`, `scripts/walk_forward.py`,
`scripts/reporting.py`, `references/cost_models.md`,
`references/validation_methods.md`, `SKILL.md`, `tests/test_run_backtest.py`,
`tests/test_walk_forward.py`, `tests/test_reporting.py`, plus `HANDOFF.md` /
`HANDOFF_NEXT.md` at the repo root.

**Git state**: the work is **committed** as `289366a` ("Measure the participation
dilution of the panel impact model"). `git status` is clean; the commit contains
only the files listed above. The next session starts from that commit.

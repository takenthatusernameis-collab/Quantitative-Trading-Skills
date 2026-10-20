# HANDOFF_NEXT

## The one precise next task

**Commit a pinned panel-mode reference artifact.** Today the skill's headline panel capability (`--panel-pricing book`, the panel book diagnostic, the impact-participation measurement, the notional-weighted impact aggregation) is guarded only by internal-consistency unit tests: there is no committed artifact holding the actual numbers, so the panel/book claims have no evidence trail. There is also no committed multi-asset fixture (`assets/example_data/` has only a single-asset CSV), so such an artifact needs one.

This is bounded and directly serves the quant research objective: it pins the panel/book/impact numbers so a future session can detect any silent change to the pricing/cost model, and it gives reviewers a concrete artifact to audit instead of trusting "tests pass".

## Why (evidence)

- `skills/quantitative-backtesting/assets/example_data/` contains only `sample_ohlcv.csv` (single asset). `skills/quantitative-backtesting/SKILL.md` quotes panel/book numbers (impact dilution, participation ratio, book-vs-net-exposure return gap) that exist only in test assertions and live runs, never committed.
- The panel/book diagnostic, `impact_participation_dilution`, `book_market_impact_cost`, `compute_book_diagnostic`, and the `notional-weighted` vs `panel` impact aggregation all exist in `scripts/utils.py` and `scripts/walk_forward.py` and are exercised by `tests/test_run_backtest.py` (book-pricing tests) and `tests/test_walk_forward.py`, but none of them commit the produced numbers.
- Just completed (this session): the `--fill-rate` semantics are now decided and pinned (see below), so the fill-rate sweep no longer blocks a panel artifact.

## What changed this session (fill-rate: Option 1, done)

Decided convention: `--fill-rate` scales the *achieved position* (`positions = target * fill_rate`) — a position-size/leverage lever, **not** a partial-fill execution model. Held honest: parameter name unchanged (`--fill-rate` / `fill_rate`, default 1.0, backward compatible), but code, CLI help and docs now agree, pinned by an executable test.

Files changed (5, all under `skills/quantitative-backtesting/`):

- `scripts/run_backtest.py` — `--fill-rate` help text (line 89) and the inline comment (line ~231) now describe a position-scale limit, not a partial fill.
- `scripts/walk_forward.py` — `--fill-rate` help text (line ~7450) and all five `fill_rate` docstrings (lines ~427, ~989, ~1678, ~2341, ~2993) describe the position-scale/participation-limit semantics, including the non-scale-invariance of Sharpe (risk-free rate not scaled) and the unfilled part uncharged; inline comment at line ~1724 updated.
- `references/validation_methods.md` — "Open: what `fill_rate` actually models" replaced with a decided-convention section ("Fill rate: decided convention") recording the measured consequences (elementwise 0.5x returns at fill_rate=0.5, Sharpe 3.19 -> 1.79, impact halves, `estimate_capacity()` has no fill_rate argument) and explicitly declining the true partial-fill re-implementation as a number-changing methodology change.
- `SKILL.md` — the `--fill-rate` tip updated to the decided convention, pointing at the test and the doc section.
- `tests/test_run_backtest.py` — new `test_run_backtest_fill_rate_scales_position_elementwise` (registered in the module_tests registry): asserts `returns(fill_rate=0.5) == 0.5 * returns(fill_rate=1.0)` elementwise, linear cost scaling, and `sharpe(0.5) != 0.5 * sharpe(1.0)` (non-scale-invariance).

## What was actually verified

- Full suite green: all 12 test files exit 0 (`for f in skills/quantitative-backtesting/tests/test_*.py; do python3 "$f"; done`) — `test_run_backtest` now 104/104 (was 103/103), `test_cpcv` 29/29, `test_walk_forward` 177/177, `test_execution_warmup` 8/8, all others as before.
- Pinned values unchanged (all pinned assertions are inside the suite, which is green): `CPCV_OOS_RETURN_REFERENCE` (0.005399536978800024), `CPCV_OOS_BAR_COUNT` (92), `CPCV_OOS_LOOKBACKS` ([20, 15, 15, 15]), `WALK_FORWARD_OOS_BAR_COUNT` (189).
- Elementwise scaling re-confirmed end-to-end on the shipped `sample_ohlcv.csv`: max abs diff from `0.5 x` full-fill returns is `0.0`, ratio exactly `0.5`.
- pyflakes on the four changed/added script/test files: no new findings (the walk_forward.py and test_run_backtest.py warnings reproduce on HEAD).
- End-to-end CLI smoke test: `run_backtest.py` with `--fill-rate 0.5` and `--fill-rate 1.0` both exit 0; `fill_rate` is recorded in `results["config"]`.

## What remains unresolved (pre-existing, from HANDOFF.md; none caused by this session)

- No committed multi-asset panel fixture (`assets/example_data/` has only a single-asset CSV) — this task.
- No committed panel/book reference artifact holding actual impact-dilution / participation / book-gap numbers — this task.
- The parity harness (`baseline_capture.py` / `book_cap_probe.py`) does not exist; HEAD-vs-new parity cannot be run as specified.
- The impact model is still linear in the participation rate (no temporary/permanent split, no gap risk).
- The `out-of-sample` CLI cannot complete on the shipped `sample_ohlcv.csv` ("No valid parameters selected from validation phase", identical on HEAD) — pre-existing; the programmatic path is fine and covered by tests.
- `matplotlib` must be installed before trusting a green suite (`tests/test_reporting.py` fails with 9 errors without it). Running the suite with matplotlib re-writes `examples/example_output/tear_sheet.html` and `tear_sheet_summary.json`; revert them after any suite run so they stay environment-neutral.

## Approaches that have already failed (do not repeat)

- Renaming `--fill-rate` / `fill_rate` to a participation-limit name: rejected for this task — it breaks the CLI contract, the `--fill-rates` sweep artifact keys (`fill_rates`), the `config["fill_rate"]` key, and every test referencing it; out of scope for a bounded session. Honest redocumentation was chosen instead.
- A true partial-fill model (`position_t = position_{t-1} + f * (target_t - position_{t-1})`): explicitly declined — it is a number-changing change (pinned CPCV/walk-forward numbers, `test_output/` snapshot, sweep artifacts all move) and must be reported as a methodology change with before/after numbers, not as a bug fix.
- Adding `fill_rate` to `estimate_capacity()`: out of scope; capacity remains documented as "at full fill".

## Constraints for the next session

- Do not change the warmup metadata (guarded by `tests/test_execution_warmup.py`, 8 tests) or the fill-rate semantics just pinned.
- All pinned values must hold unless reported as a methodology change with before/after numbers.
- The full 12-file suite must stay green.
- Do not commit unless explicitly asked (working tree should be left inspectable; the 5 changed files above are uncommitted).

## Suggested first steps for the panel artifact

1. Add a multi-asset CSV fixture under `skills/quantitative-backtesting/assets/example_data/` (e.g. 4-5 assets, synthetic but deterministic, seeded).
2. Write a script (or extend a test) that runs `walk_forward.py`/`run_backtest.py` in `--panel-pricing book` and `--panel-pricing net-exposure` modes with `impact_coefficient > 0`, both `panel` and `notional-weighted` aggregation, and commits the resulting JSON: book vs net-exposure return, gross book, book turnover, impact_charged_bps / impact_traded_only_bps / impact_dilution_bps, participation ratio, capacity_book.
3. Add a test that re-runs the same command and requires the committed numbers to match within a tight tolerance (mirroring the CPCV pinned-number pattern in `tests/test_cpcv.py`).
4. Verify the full suite stays green and pyflakes is clean.

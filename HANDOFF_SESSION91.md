# Handoff — Session 91: Wire the Family Reality Check + Romano-Wolf Stepdown into the Walk-Forward Summary

## What changed
- `skills/quantitative-backtesting/scripts/walk_forward.py`
  - Added two helpers before `walk_forward_analysis`:
    - `_align_family_returns(family_returns, oos_returns)`: returns a `(T, K)`
      DataFrame. When both the family frame and `oos_returns` are
      `DatetimeIndex`-ed, it reindexes the family frame to the walk-forward OOS
      dates (so the family test covers exactly the same out-of-sample periods);
      otherwise the frame is used positionally; non-DataFrame input is wrapped.
    - `_family_multiple_testing_summary(...)`: runs `reality_check_test`
      (and `romano_wolf_stepdown` when `stepdown=True`) on the aligned matrix,
      tags the Reality Check result with `strategy_names`, and reports an
      unusable matrix under `error` instead of raising (opt-in diagnostic can
      never break the run).
  - `walk_forward_analysis(...)` (the summary-producing path) now runs the
    family diagnostics when `family_returns is not None` and writes
    `summary["family_reality_check"]` (plus `summary["family_stepdown"]` when
    `family_stepdown=True`, and `summary["family_reality_check_error"]` on an
    unusable matrix). Default `None`/`False` leaves the summary unchanged.
  - The `family_returns` / `family_stepdown` / `family_seed` /
    `family_n_bootstrap` keyword parameters and their docstrings were already
    added by the prior session's partial commit (`d36bef2`); this session added
    the missing computation and storage.
- `skills/quantitative-backtesting/tests/test_walk_forward.py`
  - New `_family_return_frame` and `_family_walk_forward_result` helpers.
  - 4 new tests (204 total now), registered in `TEST_REGISTRY`:
    - `..._family_reality_check_and_stepdown`: keys present, matrix aligned to
      OOS length, 3 strategies, CI brackets each ordered mean, adjusted
      p-values non-decreasing.
    - `..._family_diagnostics_are_reproducible`: same `family_seed` -> identical
      p-values, means, adjusted p-values, ordering.
    - `..._without_family_returns_keeps_summary_unchanged`: default adds no
      family keys.
    - `..._family_returns_too_short_records_error`: unusable matrix is reported
      (`family_reality_check is None`, `family_reality_check_error` set) and the
      run still completes.
- `skills/quantitative-backtesting/references/validation_methods.md` and
  `SKILL.md`: replaced the "not yet wired into a CLI summary" note with the
  additive opt-in walk-forward wiring (`family_returns`, `family_stepdown`).

## Why this task
Session 90's handoff's one precise next task was exactly this wiring, so the
family-level result was no longer standalone. It serves the mission's
"statistical uncertainty" and "honest reporting" criteria: the family test now
travels with the walk-forward summary instead of living only in an example.

## What was actually verified (run this session)
- `python3 -m pytest tests/test_walk_forward.py -q`
  -> **204 passed** (272.82 s).
- `python3 -m pytest tests/test_walk_forward.py -q -k "family or main_registers"`
  -> **5 passed** (includes the registry meta-test that requires every
  module-level test to be registered).
- `python3 -m pytest tests/test_romano_wolf_stepdown.py tests/test_reality_check.py
  tests/test_reality_check_family_example.py -q` -> **25 passed** (8.98 s).
- `python3 -m pytest tests/test_walk_forward.py -q -k
  "notional_weighted_capacity_in_book_mode"` -> **1 passed** (no regression of
  the Session 85/86 book-capacity fix).
- `python3 -m pytest tests/test_examples_coverage.py -q -k "reality_check"`
  -> **2 passed** (1.85 s).
- Manual run of the family path on a 500-bar `_make_ohlcv_data` sample:
  `family_reality_check.n_observations == 189 == len(oos_returns)`,
  `n_strategies == 3`, `strategy_names == ['strong_momentum','flat_signal',
  'negative_signal']`; `family_stepdown` ordered `[0, 1, 2]`, adjusted p-values
  `[0.0, 0.715, 1.0]`, CIs bracket each mean, `n_rejected == 1`. No profitability
  claim — this is a multiple-testing / effect-size demonstration on synthetic
  data.
- `python3 -m py_compile scripts/walk_forward.py` -> OK.
- `git diff --check` -> no whitespace errors.
- Reverted unrelated `examples/example_output/*` files that the coverage test
  regenerated, so the working tree contains only the 4 intended files.

## What remains unresolved
- Full single-invocation quant gate
  (`python3 -m pytest skills/quantitative-backtesting/tests/ -n 4`) still cannot
  complete in-session (Sessions 84-91, ~60+ min environmental timeout). Not
  retried unchanged. A CI run is needed for 100% green confirmation.
- The family wiring is a programmatic-API opt-in only: `run_walk_forward(args)`
  (CLI) does not expose a `--family-returns` flag. No committed CLI fixture
  exercises it end to end.
- Studentization still uses full-sample Newey-West HAC variances; a
  bootstrap-variance studentization variant / sensitivity check is not
  implemented.
- CIs remain marginal percentile intervals, not FWER-adjusted simultaneous bands.
- Changes are uncommitted in the working tree (per the no-commit-without-request
  rule). The harness/session commit step must persist them.

## Approaches already tried / failed (do not repeat unchanged)
- Full gate serial or `-n 4`: timed out at ~60/30/20 min across Sessions 84-91.
  Do not rerun the unchanged full gate in-session.
- The full `test_examples_coverage.py` suite exceeds the 120 s command timeout
  when combined with other files. Run `-k "reality_check"` subset instead.
- Do not regress
  `test_walk_forward_reports_notional_weighted_capacity_in_book_mode`
  (Session 85/86 book-capacity fix).
- Do not rerun the full `test_walk_forward.py` just to re-check docs; it costs
  ~4.5 min and the targeted `-k "family or main_registers"` subset is enough.

## One precise next task (for the next agent)
Add an end-to-end **CLI** path for the family diagnostics so the wiring is not
programmatic-only, using a committed fixture. Concretely:
- In `scripts/walk_forward.py` `run_walk_forward(args)` (and its argparse
  setup near the bottom of the file), add opt-in flags `--family-returns <csv>`
  (a CSV of per-period family returns, first column a date, remaining columns
  strategies) and `--family-stepdown`, plus optional `--family-seed` /
  `--family-bootstrap`. Load the CSV with `pd.read_csv(parse_dates=[0],
  index_col=0)` and pass it as `family_returns=` into the
  `walk_forward_analysis(...)` call(s) in that path, forwarding
  `family_stepdown`, `family_seed`, `family_n_bootstrap`.
- Add a small committed CSV fixture under
  `skills/quantitative-backtesting/tests/fixtures/` (deterministic, no network)
  with >=2 strategy columns and enough rows to cover the OOS window, and a
  focused CLI test (in `test_walk_forward.py` or a new `test_family_cli.py`)
  that runs the CLI on `_write_ohlcv_csv`-style data plus the fixture and
  asserts `summary["family_reality_check"]` / `summary["family_stepdown"]` are
  present in the written summary JSON.
- Keep default behavior unchanged (no flags -> no family keys). Verify with
  `python3 -m pytest skills/quantitative-backtesting/tests/test_walk_forward.py
  -q -k "family or main_registers"` and the `-k "reality_check"` coverage
  subset. Constraints: offline, committed fixtures only, do not change default
  outputs, do not rerun the full gate in-session, do not commit unless
  explicitly asked; CI is needed for 100% green confirmation.
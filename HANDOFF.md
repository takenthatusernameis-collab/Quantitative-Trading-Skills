# Handoff — Quantitative Trading Skills Repository

**Last updated**: 2026-10-13

## Repository state

- Git: `main` at `10248a5` plus this session's changes (uncommitted; do not
  commit unless asked). The previous handoff's `8dd6758` reference was stale;
  the Option A (ols_hedge) work was committed into `10248a5`/`cd79403`.
- Skill location: `skills/quantitative-backtesting/` (8 strategies, 7 scripts,
  8 test files, 4 reference docs).
- Python deps for the suites: `pandas` and `numpy` (present in the session
  environment; not committed).

## Session summary (2026-10-13, sixth session)

Implemented **Option B from the previous handoff: surface the Deflated Sharpe
Ratio (DSR) in the main backtest path** via a new `--n-trials` flag.

### Changes

1. **`scripts/run_backtest.py`**:
   - `parse_args()`: new `--n-trials` (type=int, default `None`) — the number
     of development trials (parameter configurations) behind the backtest.
   - `run_backtest(...)`: records `n_trials` in the results `config` dict via
     `getattr(args, "n_trials", None)` (so the test `_Args` stub, which lacks
     the attribute, still works). Backward compatible.
   - `main()`: echoes the DSR line (mirroring the `walk_forward.py` CLI) when
     `calculate_metrics` attached one.

2. **`scripts/performance.py`**:
   - `calculate_metrics(...)`: after the Sharpe is computed, reads
     `config["n_trials"]`; when it is an int `>= 1` and there are `>= 2`
     returns, it computes `metrics["deflated_sharpe"] =
     deflated_sharpe_ratio(sharpe_ratio=metrics["sharpe_ratio"], returns=returns,
     n_trials=int(n_trials))`. The import is **lazy** (inside the function)
     because `walk_forward` imports `performance` at module load — a top-level
     import would be circular. It tries `from walk_forward import ...` first
     and falls back to `from scripts.walk_forward import ...` so the function
     resolves whether `performance` was imported as a top-level module or as
     part of the `scripts` package. Without `n_trials`, no `deflated_sharpe`
     key is emitted.
   - `generate_report(...)`: prints a `--- Multiple-Testing Correction ---`
     section (DSR, p-value, expected max Sharpe, z-score, n_trials,
     observations) when `deflated_sharpe` is present; omitted otherwise.

3. **`scripts/reporting.py`**:
   - `generate_tear_sheet(...)`: renders a `Multiple-Testing Correction` HTML
     table when `deflated_sharpe` is present; omitted otherwise. Because the
     DSR is a dict and the JSON summary's `metrics` field is filtered to
     scalars, the DSR is also written as a top-level `deflated_sharpe` key in
     `tear_sheet_summary.json` when present.

4. **`tests/test_run_backtest.py`** — 4 new tests (19 → 23 total):
   - `run_backtest_n_trials_surfaces_deflated_sharpe`: `--n-trials=50` threads
     `n_trials` through config into a `deflated_sharpe` metrics key; checks the
     DSR is in [0, 1], `n_trials`/`n_observations` match, and
     `p_value == 1 - DSR`.
   - `run_backtest_without_n_trials_omits_deflated_sharpe`: default `_Args`
     (no `n_trials`) → no `deflated_sharpe` key (backward compat); config
     records `n_trials=None`.
   - `run_backtest_deflated_sharpe_matches_direct_call`: the surfaced DSR equals
     a direct `deflated_sharpe_ratio(...)` call on the same Sharpe and returns
     (guards against the metrics path and the standalone function drifting).
   - `parse_args_accepts_n_trials`: the real `parse_args` accepts `--n-trials`
     (via `unittest.mock.patch` on `sys.argv`) and defaults it to `None`.
   - `_Args` now accepts `n_trials=None`.

5. **`tests/test_reporting.py`** — 4 new tests (10 → 14 total):
   - `generate_report` surfaces/omits the `Multiple-Testing Correction` section.
   - `generate_tear_sheet` renders the DSR table and surfaces the DSR as a
     top-level `deflated_sharpe` key in the JSON summary; omits both when
     absent.

6. **Docs**: `SKILL.md` (run_backtest resource description, Tips, and the
   `test_run_backtest.py`/`test_reporting.py` coverage notes),
   `references/metrics_definitions.md` (DSR section) and
   `references/validation_methods.md` (Usage + CLI sections) updated to
   document the `--n-trials` path.

### Verified (evidence)

- Full suite from repo root: **127/127 tests pass**
  (6 + 13 + 14 + 23 + 27 + 28 + 15 + 1). Baseline before this session was
  119; 8 tests added → 127. No existing test changed.
- CLI end-to-end (`run_backtest.py --n-trials 50`): DSR computed and echoed
  (`Deflated Sharpe Ratio: 0.0164 (p-value 0.9836, expected max Sharpe
  1.9798, 50 trials)`), and rendered in `report.txt`, `tear_sheet.html`, and
  `tear_sheet_summary.json`. The low DSR is the honest result: the sample-data
  SMA Sharpe (~0.47) deflated by 50 trials is consistent with luck.
- Backward compatibility: running **without** `--n-trials` produces output
  **byte-identical** to the pinned `test_output/` snapshot (`metrics.json`,
  `report.txt`, `tear_sheet_summary.json` all `diff`-clean), and no
  `deflated_sharpe` key appears anywhere.
- Circular-import safety: `calculate_metrics` resolves the DSR via both the
  top-level import path (`from performance import ...`) and the
  package-qualified path (`from scripts.performance import ...`), and the
  `walk_forward.py` CLI (which imports `performance` as `scripts.performance`
  and calls `calculate_metrics` at runtime) still runs end-to-end.
- The surfaced DSR matches a direct `deflated_sharpe_ratio` call exactly
  (regression-guarded by test).

### Methodological notes

- The DSR deflates the **final backtest Sharpe** by `n_trials` using the
  i.i.d.-normal null approximation for `SR*` (`sqrt(2 ln N / T)`), because a
  single backtest does not have the cross-sectional dispersion of individual
  trial Sharpes. Passing `trial_sharpes` (the stronger estimator) would require
  the full grid-search record; that is available in the `walk_forward`/`optimize`
  `--deflate` paths, not here. This is documented in
  `references/metrics_definitions.md`.
- `n_trials` is opt-in and threaded through the results `config`, so
  `calculate_metrics` stays a pure function of its `results` argument; callers
  that do not set `n_trials` (e.g. the walk-forward/CPCV report paths) are
  unaffected.
- The DSR is a multiple-testing correction, not out-of-sample evidence. It
  does not validate the economics of a strategy and is not evidence of
  profitability.
- All results are synthetic; nothing here is production-ready.

## Unresolved / remaining

- `run_monte_carlo` calls `parameter_optimization` internally without deflation
  (it only consumes `best_params`), so MC results do not carry a DSR.
- Monte Carlo lives in `walk_forward.py` (`monte_carlo_simulation`); no
  separate `monte_carlo.py` script (previous handoff Option C).
- No out-of-sample evidence of profitability exists anywhere in this repo; all
  results are synthetic.

## Next task for the next agent

**Option C: Extract Monte Carlo into standalone `monte_carlo.py`**
- Context: `scripts/walk_forward.py` (`monte_carlo_simulation`, ~lines 652-815),
  `scripts/strategy_builder.py`, `scripts/run_backtest.py`.
- Scope: Move `monte_carlo_simulation` and its helpers to `scripts/monte_carlo.py`
  with a clean public API; update imports and the CLI entry points
  (`run_monte_carlo` in `walk_forward.py`); add tests (a new
  `tests/test_monte_carlo.py`); update `SKILL.md` resources and
  `references/validation_methods.md`.
- Constraints: no behavior change, keep the full suite passing (127 tests),
  no new dependencies. Watch the import graph: `monte_carlo_simulation` uses
  `_annualization_factor` (also in `walk_forward.py`, and independently in
  `performance.py`) — decide whether to import it or keep a local copy to avoid
  a new circular dependency.
- Alternative next tasks (if Option C is deferred): wire `trial_sharpes` into
  the `run_backtest --n-trials` path so `SR*` uses the cross-sectional
  estimator instead of the i.i.d. null (requires the grid-search record); or
  add DSR to the `run_monte_carlo` path.

## Test suite quick reference

Run all from repo root (requires pandas/numpy):

```bash
for t in test_data_loader test_performance test_reporting test_run_backtest \
         test_strategy_builder test_walk_forward test_cpcv test_generate_sample_data; do
  python3 skills/quantitative-backtesting/tests/$t.py || exit 1
done
```

`test_reporting.py` uses stdlib `unittest` (exit code / `OK` line is the
pass/fail signal); the rest use the custom `main()` runner printing `N/N tests
passed`. Current counts: 6 + 13 + 14 + 23 + 27 + 28 + 15 + 1 = 127.

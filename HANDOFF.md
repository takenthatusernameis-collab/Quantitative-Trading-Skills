# Handoff — Quantitative Trading Skills Repository

**Last updated**: 2026-10-13 (seventh session)

## Repository state

- Git: `main` at `5eaff1a` plus this session's changes (uncommitted; do not
  commit unless asked).
- Skill location: `skills/quantitative-backtesting/` (8 strategies, 8 scripts,
  9 test files, 4 reference docs).
- Python deps for the suites: `pandas` and `numpy` (present in the session
  environment; not committed).

## Session summary (2026-10-13, seventh session)

Implemented **Option C from the previous handoff: extract Monte Carlo into a
standalone `monte_carlo.py`**.

### Changes

1. **`scripts/monte_carlo.py`** (new, standalone):
   - Contains `monte_carlo_simulation` and a local copy of
     `_annualization_factor`. Depends only on pandas/numpy, so it imports
     cleanly without pulling in the walk-forward orchestration graph.
     A local copy (rather than importing from `walk_forward`) was chosen
     deliberately: it keeps the module self-contained and avoids any
     import-graph hazard, matching the repo's existing pattern where
     `performance.py` also keeps its own `_annualization_factor`.

2. **`scripts/walk_forward.py`**:
   - Added `from monte_carlo import monte_carlo_simulation` at the top.
   - Removed the old `monte_carlo_simulation` definition (was lines
     ~652-815). `run_monte_carlo` and the `monte-carlo` CLI subcommand are
     unchanged in behavior; they now call the imported function.
   - Module docstring updated to note the re-export.

3. **`tests/test_monte_carlo.py`** (new, 7 tests):
   - `standalone_module_structure` — the function is importable from
     `monte_carlo` directly.
   - `standalone_basic_structure` — structure, metrics, CIs, summary.
   - `standalone_block_bootstrap` — block bootstrap runs, no NaNs.
   - `standalone_probability_of_ruin` — ruin fraction in [0, 1].
   - `standalone_short_series_raises` — ValueError for < 2 observations.
   - `standalone_matches_walk_forward_re_export` — guards that
     `walk_forward.monte_carlo_simulation is monte_carlo.monte_carlo_simulation`
     (a re-export, not a divergent copy).
   - `standalone_reproducible_structure` — output shape is stable across
     runs (values differ because the global RNG is used; structure does not).

4. **Docs**: `SKILL.md` (scripts/ and tests/ resource lists, test-coverage
   run list), `references/validation_methods.md` (Monte Carlo section now
   documents the standalone module and shows `from monte_carlo import ...`).

### Verified (evidence)

- Full suite from repo root: **134/134 tests pass**
  (6 + 13 + 14 + 23 + 27 + 28 + 15 + 7 + 1). Baseline was 127; 7 new tests
  in `test_monte_carlo.py`; no existing test changed.
- Backward compatibility: `run_backtest.py` output is **byte-identical** to
  the pinned `test_output/` snapshot (`metrics.json`, `report.txt`,
  `tear_sheet_summary.json` all `diff`-clean).
- CLI end-to-end: `walk_forward.py monte-carlo ...` runs and writes
  `monte_carlo_results.json`; `walk_forward.py walk-forward ...` and
  `walk-forward ... --deflate` still run and echo the DSR line.
- Re-export identity holds: `walk_forward.monte_carlo_simulation is
  monte_carlo.monte_carlo_simulation`.

### Methodological notes

- This is a refactor, not a research change. No strategy, signal, metric, or
  validation methodology was altered; the Monte Carlo algorithm is
  byte-for-byte the same code, just relocated.
- All results are synthetic; nothing here is production-ready.

## Unresolved / remaining

- `run_monte_carlo` calls `parameter_optimization` internally without
  deflation (it only consumes `best_params`), so MC results do not carry a
  DSR. This was the alternative next task in the prior handoff and is still
  open.
- No out-of-sample evidence of profitability exists anywhere in this repo;
  all results are synthetic.

## Next task for the next agent

**Wire the Deflated Sharpe Ratio into the `run_monte_carlo` path.**

Context: `scripts/walk_forward.py` `run_monte_carlo` (CLI `monte-carlo`)
runs `parameter_optimization` internally to pick `best_params`, then
`monte_carlo_simulation` on the resulting returns. Neither step currently
deflates for multiple testing, so the Monte Carlo output inherits the
in-sample selection bias of the optimization.

Scope (one bounded change):
- Add an `--n-trials` flag (or reuse the optimization's trial count) to the
  `monte-carlo` CLI subcommand and thread it into the metrics/config so
  `calculate_metrics` surfaces a `deflated_sharpe` for the base backtest
  Sharpe (mirroring the `run_backtest --n-trials` path already in place).
- Alternatively, if the optimization record is available, pass
  `trial_sharpes` so `SR*` uses the cross-sectional estimator instead of
  the i.i.d. null.
- Add tests in `test_monte_carlo.py` (and/or `test_walk_forward.py`) for the
  new flag and the DSR key; update `SKILL.md` and
  `references/validation_methods.md`.

Constraints: no behavior change for callers that do not set the flag; keep
the full suite passing (134 tests); no new dependencies.

## Test suite quick reference

Run all from repo root (requires pandas/numpy):

```bash
for t in test_data_loader test_performance test_reporting test_run_backtest \
         test_strategy_builder test_walk_forward test_cpcv test_monte_carlo \
         test_generate_sample_data; do
  python3 skills/quantitative-backtesting/tests/$t.py || exit 1
done
```

`test_reporting.py` uses stdlib `unittest` (exit code / `OK` line is the
pass/fail signal); the rest use the custom `main()` runner printing
`N/N tests passed`. Current counts: 6 + 13 + 14 + 23 + 27 + 28 + 15 + 7 + 1 = 134.

(End of file)
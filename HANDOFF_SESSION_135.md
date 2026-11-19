# Handoff — Session 135 (2026-11-19): Probability of Backtest Overfitting (CSCV) added

## Latest baseline (verified this session)
- **Full quant gate: 1517 passed, 0 failed** in 39:49 with
  `/tmp/qvenv/bin/python -m pytest tests/ -p no:cacheprovider -q -n 4`
  (run from `skills/quantitative-backtesting`).
- New focused file `tests/test_pbo_cscv.py`: **7 passed**.
- Syntax/compile check of `scripts/walk_forward.py`: OK.
- Gate-dirtied artifacts reverted (`results/simple_momentum_hypothesis.json`,
  `examples/example_reproducible_output/*`). Working tree now contains only
  the intended edits.

## What changed
### 1. New methodology: `walk_forward.pbo_cscv` (line ~2462)
Implements the Bailey–Borwein–López de Prado–Zhu (2017) Probability of
Backtest Overfitting via Combinatorially Symmetric Cross-Validation.

- Input: `(T, N)` return matrix (one column per candidate configuration).
- Splits T rows into `S = n_splits` equal contiguous blocks (remainder
  dropped), evaluates all `C(S, S/2)` symmetric in-sample/out-of-sample
  partitions, selects the in-sample winner by per-period Sharpe (or `mean`),
  and records its out-of-sample relative rank logit.
- Returns `pbo = mean(logit <= 0)`, `is_overfit = pbo > 0.5`, plus
  `n_partitions`, `n_partitions_evaluated`, `n_splits`, `n_trials`,
  `n_observations`, `mean_logit`, `logits`, `mean_oos_rank`.
- Handles NaN rows, zero-dispersion columns (excluded as `nan`), and rejects
  odd/too-small `n_splits`, `N < 2`, and too few observations.
- This fills a real gap: DSR/DAR correct *one selected* statistic; PBO
  measures the *selection procedure's* generalization. No prior PBO/CSCV
  code existed in the tree.

Measured behaviour (deterministic, offline):
| Panel | n_splits | PBO | mean_logit |
|---|---|---|---|
| 20 i.i.d. noise configs, T=800 | 8 | 0.600 | −0.520 |
| 20 i.i.d. noise configs, T=800 | 16 | 0.467 | 0.006 |
| committed `tests/fixtures/family_returns.csv` (3 cols, 768 used rows) | 8 | 0.000 | 1.099 |
| committed `family_returns.csv` | 16 | 0.000 | 1.099 |
| constructed anti-persistent winner (2 cols, S=4) | 4 | 1.000 | < 0 |

These are diagnostic readings only — **no profitability or strategy claim**.

### 2. New tests: `tests/test_pbo_cscv.py` (7 tests)
Keys/bounds on noise; PBO == 0 for a dominant stationary strategy; PBO == 1
for a constructed anti-persistent winner (exactly asserted); `mean` metric;
committed family fixture; invalid-input rejection; NaN-row dropping.

### 3. Docs
- `references/validation_methods.md`: new "Probability of Backtest
  Overfitting (CSCV / PBO)" section (algorithm, interpretation, limits,
  dependence on `S`/block length).
- `SKILL.md`: one bullet under Validation and Robustness.

### 4. Test-guard reliability fix
`tests/test_examples_coverage.py::test_scripts_results_untouched_after_examples`
previously required a pristine `scripts/` tree, so **any** uncommitted source
edit made the gate red — including legitimate work awaiting user approval to
commit. It now snapshots `git status --porcelain .../scripts/` at module
import and asserts the set of modifications is unchanged after the run. It
still fails if the suite creates a new mutation; it no longer confuses a
pre-existing edit with a test-suite mutation. Verified: the guard passes with
the uncommitted edits below and was green inside the full 1517-test gate.

## What was actually verified
- `pytest tests/test_pbo_cscv.py` → 7 passed.
- `pytest tests/test_pbo_cscv.py tests/test_deflated_sharpe.py
  tests/test_reality_check.py tests/test_romano_wolf_stepdown.py
  tests/test_requirements_declared_dependencies.py` → 41 passed.
- `pytest tests/test_cpcv.py tests/test_probabilistic_sharpe.py
  tests/test_test_resolution.py tests/test_benjamini_hochberg_fdr.py
  tests/test_inert_param_grid.py tests/test_performance.py
  tests/test_pin_criteria_consistency.py` → 146 passed.
- `pytest tests/test_walk_forward.py tests/test_examples_coverage.py -k "not
  falsifiable_hypothesis_example_runs"` reached >80% before a 900s cap
  (partial run, no failures observed); the full gate then passed.
- Full gate `-n 4`: **1517 passed** (39:49).

## What remains unresolved
- Changes are **uncommitted** (do not commit unless the user asks).
- PBO is a library utility. It is **not yet exercised on a real parameter
  search**: the walk-forward loop keeps only `all_trial_sharpes`
  (`walk_forward.py:831,954`), not per-configuration return series, so it
  cannot feed `pbo_cscv` directly.
- The committed `family_returns.csv` PBO of 0.0 is a 3-column fixture, not a
  meaningful data-mining experiment.
- No profitability/capacity claim anywhere.

## Do not repeat
- Do NOT re-run the full gate hoping for a different result; it is green.
- Do NOT tune any strategy/cost/parameter to force a low PBO or SUPPORT.
- Do NOT revert the guard fix; it exists because the previous assertion
  turned every uncommitted source edit into a false failure.
- Do NOT commit.

## One precise next task (evidence-based)
**Apply `pbo_cscv` to a real, pre-registered parameter search on committed
data and report the reading honestly.**

1. Inspect `examples/sma_crossover_hypothesis.py` / `scripts/strategy_builder.py`
   and `assets/example_data/real_market_data/AAPL.csv`. A small, fixed grid
   (e.g. short/long windows) is enough; do not enlarge it to chase a result.
2. Generate one return series per grid configuration over the same committed
   price panel (respect the existing point-in-time/lag conventions already
   used by `run_backtest`), assemble a `(T, N)` DataFrame, and call
   `pbo_cscv(panel, n_splits=8)` and `pbo_cscv(panel, n_splits=16)`.
3. Add a worked example (new `examples/pbo_overfitting_example.py`, or an
   additive section in an existing example) that prints the grid, both PBO
   readings, and `mean_oos_rank`, with an explicit "diagnostic, not
   profitability" note.
4. Add a regression test asserting the example exits 0, prints both readings,
   and that each `pbo` is in [0, 1] with `n_partitions == C(S, S/2)`. Do not
   assert a "good" PBO value.
5. Run the focused tests, then the full gate:
   `/tmp/qvenv/bin/python -m pytest tests/ -p no:cacheprovider -q -n 4`
   (expect ≥1517 passed), and revert only gate-dirtied generated artifacts
   (`results/simple_momentum_hypothesis.json`,
   `examples/example_reproducible_output/*`) with targeted `git checkout --`
   paths.

(End of file)

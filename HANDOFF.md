# Handoff — 2026-10-20 (session)

## What changed

Completed the `test_n_periods` -> `test_n_observations` rename assigned in HANDOFF_NEXT.md, with the parity
harness that the breaking API change required. The held-out window was already counted in return
*observations*; only the *name* was wrong ("periods" implies independent periods, which daily bars are not).

Framework (`skills/quantitative-backtesting/scripts/walk_forward.py`):

- `out_of_sample_validation`'s `test_performance` block now emits `"test_n_observations": len(test_returns)`
  (was `"test_n_periods"`), with a comment recording that the walk-forward *period* count lives in
  `summary["n_periods"]` and that the observation count is what the resolution arithmetic needs.
- The CLI's saved artifact (`out_of_sample_summary.json`) re-projects the same renamed key
  (`walk_forward.py:10154`); the old key is gone from the artifact too.

Consumers updated:

- `examples/falsifiable_hypothesis_example.py:373` now reads `test_perf.get("test_n_observations")`. The
  example's own reported key was already `test_n_observations`, so the framework and the example now use one
  name for one number.
- `tests/test_out_of_sample_window.py:184` reads the renamed key.
- `references/validation_methods.md:1365-1370` documents the framework's key name, and now also states that
  the walk-forward period count is a *different* number living in `summary["n_periods"]`.

Not renamed (deliberately): `summary["n_periods"]` (walk_forward.py:1446, 3088 — the walk-forward *period*
count, correctly named) and `reporting.py:728`'s `("Number of Periods", "n_periods", ...)` row, which reads that
summary diagnostic. Both are pinned by the harness so an over-broad rename cannot happen silently.

New parity harness `skills/quantitative-backtesting/tests/test_test_window_observations.py` (7 tests) plus its
baseline fixture `tests/fixtures/test_performance_pre_rename_baseline.json` (captured from the pre-rename
source at commit `6074e3b`):

1. the framework emits `test_n_observations` and no longer emits `test_n_periods`; reading the old key raises
   `KeyError` (the break is explicit, not a silent `None`);
2. the count is the number of *return observations* (`len(test_returns)` = 100), which is strictly smaller than
   the held-out window's row count (102) because of warmup rows — so the key cannot be swapped for a window
   size unnoticed;
3. the rename moved nothing but the name: the key set, every scalar metric and the whole 100-element test
   return series are identical to the pre-rename baseline, and `summary["test_sharpe"] / ["test_total_return"]
   / ["test_volatility"]` are unchanged;
4. no production code (`scripts/*.py`, `examples/*.py`) reads or emits `test_n_periods` any more;
5. the walk-forward *period* count is untouched (`n_periods == len(periods)`) and the reporting row still reads
   `n_periods`;
6. the saved JSON artifact carries `test_n_observations` and not the old key, with the same value (100);
7. end-to-end parity: the worked example, the programmatic API and the artifact all report 100 under the same
   name.

Negative control: reverting the rename in `walk_forward.py` (both the emission and the CLI projection) makes
7/7 of the harness fail; restoring it makes 7/7 pass. The harness is an executable invariant, not a comment.

No threshold, bound, criterion, verdict or number moved. The shipped 0.6/0.2/0.2 split is unchanged.

## What was verified

- New harness: 7/7 (`python3 skills/quantitative-backtesting/tests/test_test_window_observations.py`), and 7
  passed under `pytest`.
- Negative control on the harness: 0/7 with the rename reverted, 7/7 restored.
- Neighbouring suites, all re-run after the change:
  `test_falsifiable_hypothesis_example.py` 14/14, `test_out_of_sample_window.py` 10/10,
  `test_examples_coverage.py` 7/7, `test_walk_forward.py` 183/183, `test_cpcv.py` 29/29,
  `test_run_backtest.py` 104/104, `test_reporting.py` 62 tests OK (unittest),
  `test_test_resolution.py` 38/38, `test_resolution_vs_sample_size.py` 16/16, `test_performance.py` 33/33,
  `test_monte_carlo.py` 20/20, `test_execution_warmup.py` 8/8, `test_inert_param_grid.py` 27/27,
  `test_no_selection_diagnosis.py` 34/34, `test_panel_reference_pinned.py` 2/2,
  `test_strategy_builder.py` 33/33, `test_generate_sample_data.py` 2/2, `test_data_loader.py` 32/32.
- `python3 -m py_compile` clean on all four changed/added Python files.
- `skills-ref validate skills/quantitative-backtesting/` -> "Valid skill" (the CI validator used by
  `.github/workflows/validate-skills.yml`).
- Direct old-vs-new comparison (pre-rename source loaded side by side from commit `6074e3b`): every
  `test_performance` value is bit-identical; the only difference is the key name.
- Determinism: the shipped-sample validation run is byte-stable across repeats, so the pinned baseline is a
  stable contract rather than a snapshot of a lucky run.

## What remains unresolved

- `validation_performance["val_n_periods"]` (`walk_forward.py:5708`) has the *same* mislabel as the key just
  fixed: it is `len(val_returns)` (100 validation bars on the shipped sample), not a period count. It was left
  alone because the assignment scoped the breaking change to `test_performance` only, and widening a breaking
  API change needs its own baseline capture. Evidence and a recipe are in HANDOFF_NEXT.md.
- The resolution ladder has only been measured on the *null* (no-effect) fixture. The effect-series
  measurement has now been taken as well (numbers below), and it shows the ladder is a property of the sample
  size and the trial distribution rather than of the hypothesis — but the held-out-fraction sweep on the effect
  series is still unmeasured. That is the next task.

## Approaches that failed

- None. The rename was mechanical; the parity baseline was captured from the pre-rename source on the first
  attempt, and the only test failure during development was my own key-set comparison in the harness (the
  baseline stores `test_returns` outside the metric dict), fixed in one edit.

## Next task (one, precise)

**Measure the held-out-fraction sweep on the *effect* series (positive control), at 5,000 and 10,000 bars, and
pin the control's discrimination in the test suite.**

The resolution ladder is calibrated on a synthetic fixture, and the ladder measured on the null fixture says
what a null sample can resolve. The positive control (`scripts/generate_positive_control_data.py`: the same
draws with a known injected effect) says whether a real edge is *confirmable* once the sample is large enough.
Measuring it turns the resolution analysis from "how big a sample would this null need" into "can this
framework confirm a real edge at all, and at what size".

Measured in this session (ladder, default 0.6/0.2/0.2 split, seed 7, `n_test_observations` 998 / 1998):

| series | bars | min detectable SR | SR* | min detectable alpha | alpha* | observed SR |
| --- | --- | --- | --- | --- | --- | --- |
| no_effect | 5,000 | 1.9096 | 1.2560 | 0.0930 | 0.0219 | -0.0448 |
| no_effect | 10,000 | 1.7136 | 1.2557 | 0.0689 | 0.0174 | -0.1806 |
| effect | 5,000 | 1.8373 | 1.2135 | 0.0952 | 0.0185 | 3.3798 |
| effect | 10,000 | 1.6012 | 1.1584 | 0.0779 | 0.0240 | 3.4834 |

What this shows: the minimum detectable effect is nearly the same on both fixtures (Sharpe 1.84 vs 1.91 at
5,000 bars; alpha 0.095 vs 0.093), so the ladder is a property of the *sample size, the number of trials and
the realized volatility* — not of whether the strategy has an edge. What separates the fixtures is the
*observed* statistic (Sharpe 3.38 on the effect series vs -0.04 on the null): the control's observed edge sits
above the 2.00 plausibility bound and is confirmable on every draw at 5,000 bars, while the null is never
confirmable at any size. The CPCV path remains the exception: at 10,000 bars its alpha floor (alpha* 0.1228)
stays above the 0.10 bound, so no sample size would let that path confirm a plausible alpha.


# Next task — 2026-10-20 (session)

## Task

**Measure the held-out-fraction sweep on the *effect* series (positive control), at 5,000 and 10,000 bars, and
pin the control's discrimination in the test suite.**

## Why this is the next thing

The `test_n_periods` -> `test_n_observations` rename is complete and pinned by a parity harness
(`tests/test_test_window_observations.py`, 7/7, with a negative control that fails 7/7 when the rename is
reverted). Every metric of the held-out window is bit-identical to the pre-rename output; the only difference
is the key name.

What remains open on the resolution work is a *measurement* gap, not a code gap: the sample-size ladder has
been measured on the null (no-effect) fixture, and only the ladder (default 0.6/0.2/0.2 split) — not the
held-out-fraction sweep — has been measured on the effect fixture. The positive control exists in the
framework (`scripts/generate_positive_control_data.py`: the same draws with a known injected effect) and is
what makes the resolution analysis a check on the *machinery* rather than a statement about one null path.
Without it, the ladder's numbers cannot be shown to be properties of the sample rather than of the null.

## Evidence and constraints

- Tool: `skills/quantitative-backtesting/scripts/measure_resolution_vs_sample_size.py`; `--series effect`
  selects the injected-effect fixture, `--sizes` the ladder, `--test-fracs` the held-out-fraction sweep
  (`val_frac` stays 0.2, `train_frac = 0.8 - test_frac`). The full 5,000/10,000-bar ladder takes ~25 s.
- Numbers already measured this session (ladder, default 0.6/0.2/0.2 split, seed 7; `n_test_observations`
  998 / 1998):

  | series | bars | min detectable SR | SR* | min detectable alpha | alpha* | observed SR |
  | --- | --- | --- | --- | --- | --- | --- |
  | no_effect | 5,000 | 1.9096 | 1.2560 | 0.0930 | 0.0219 | -0.0448 |
  | no_effect | 10,000 | 1.7136 | 1.2557 | 0.0689 | 0.0174 | -0.1806 |
  | effect | 5,000 | 1.8373 | 1.2135 | 0.0952 | 0.0185 | 3.3798 |
  | effect | 10,000 | 1.6012 | 1.1584 | 0.0779 | 0.0240 | 3.4834 |

  Reading: the minimum detectable effect is nearly identical on the two fixtures (Sharpe 1.84 vs 1.91 at
  5,000 bars; alpha 0.095 vs 0.093), so the ladder is a property of the sample size, the number of trials and
  the realized volatility — not of whether the strategy has an edge. What separates the fixtures is the
  *observed* statistic: the control's observed Sharpe (3.38) sits above the 2.00 plausibility bound and is
  confirmable on every draw at 5,000 bars, while the null's (~-0.04) is confirmable at no size. The CPCV path
  is the exception on the alpha side: at 10,000 bars its alpha floor (alpha* 0.1228) stays above the 0.10
  bound, so no sample size would let that path confirm a plausible alpha.
- What to add: the held-out-fraction sweep on the effect series (`--test-fracs 0.1,0.2,0.3` at 10,000 bars).
  On the null series the previous session measured the alpha bound crossing *later* than the Sharpe bound
  (10,000 bars: Sharpe at test_frac 0.1, alpha at 0.2); the control tells whether that trade-off is a
  property of the null or of the sample.
- Constraint: change no threshold, bound, criterion or verdict; `PLAUSIBLE_MAX_ANNUALIZED_ALPHA == 0.10` and
  the 2.00 Sharpe plausibility bound stay; the shipped 0.6/0.2/0.2 split remains the default and unchanged.
  Report the numbers; do not turn them into a performance claim — the fixture is a formula, not a market.
- Verification: extend `tests/test_resolution_vs_sample_size.py` with (a) a test pinning the effect-series
  crossing against the framework's own `test_resolution` / `deflated_alpha` blocks on a directly re-run
  analysis, and (b) a test that the control discriminates: the effect series' observed statistic must exceed
  the plausibility bound at a size where the null series' does not, and no verdict may move.

## Subsequent options (after this task)

- `validation_performance["val_n_periods"]` (`scripts/walk_forward.py:5708`) carries the same mislabel the
  just-completed rename removed: it is `len(val_returns)` (100 validation bars on the shipped sample), not a
  period count. It was deliberately left alone because the assignment scoped the breaking change to
  `test_performance`. If it is renamed to `val_n_observations`, capture a pre-rename baseline fixture the
  same way `tests/fixtures/test_performance_pre_rename_baseline.json` was captured (same data / grid / split,
  provenance in the fixture) and extend the existing harness rather than writing a new one.
- The framework's own `summary["test_resolution"]` block reports `n_test_observations`, the trial/benchmark
  counts, the minimum detectable effects and the plausibility bounds — but not the realized volatility the
  minimum detectable effect is conditional on (the two fixtures' alpha MDEs differ by ~10% at 10,000 bars
  because the effect fixture's held-out window is more volatile: 0.1746 vs 0.1622 annualized, and 0.1755 vs
  0.1593 at 5,000 bars). A reader comparing two runs at the same T could therefore misread a volatility
  difference as a sample-size difference. Whether to expose that conditioning in the block is a reporting
  question to settle with evidence, not a threshold change.

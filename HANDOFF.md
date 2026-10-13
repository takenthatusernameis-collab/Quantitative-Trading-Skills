# Handoff — Quantitative Trading Skills Repository

**Last updated**: 2026-10-13

## Repository state

- Git: `main` at `d2d0030` plus this session's changes (uncommitted; do not commit unless asked).
- Skill location: `skills/quantitative-backtesting/` (8 strategies, 7 scripts, 8 test files, 3 reference docs).
- Python deps for the suites: `pandas` and `numpy` (present in the session environment; not committed).

## Session summary (2026-10-13, second session)

Completed the HANDOFF's recommended option 1 for the cross-sectional momentum
portfolio-signal convention: kept the net-exposure semantics
(`(n_long - n_short) / n_assets`) and added validation/warnings, regression
tests, and docs around the parameter choices that make the signal flat or
ill-defined.

### Demonstrated problem (evidence)

- Default parameters are symmetric (`top_quantile=0.2, bottom_quantile=0.2`).
  On a 6-asset / 300-bar panel this yields **0 non-zero signals** (flat by
  construction), and `run_backtest` then raises the misleading
  `"Strategy never takes a position ... Reduce the lookback/period"` error —
  the real cause is the symmetric quantiles, not the lookback.
- Overlapping quantiles (`top + bottom > 1.0`, e.g. 0.5/0.8) place at least
  one asset in both the long and short book simultaneously.

### Changes

1. **`scripts/strategy_builder.py`** — added
   `CrossSectionalMomentum._validate_quantiles(top_quantile, bottom_quantile)`,
   called on the dict and MultiIndex panel paths only (not the single-asset
   fallback, where symmetric quantiles are valid rolling thresholds). It emits a
   `UserWarning` when `top_quantile == bottom_quantile` (flat net signal by
   construction, incl. the default) and when `top_quantile + bottom_quantile >
   1.0` (overlapping long/short books). No change to signal math or defaults.
2. **`tests/test_strategy_builder.py`** — 3 new regression tests:
   `cross_sectional_momentum_symmetric_quantiles_flat` (defaults are symmetric
   and produce an all-flat signal + warning),
   `cross_sectional_momentum_overlapping_quantiles_warn` (overlap warning; also
   checks the symmetric+overlap double-warning case and the asymmetric-overlap
   single-warning case), and `cross_sectional_momentum_asymmetric_no_warning`
   (asymmetric non-overlapping quantiles emit no warning and stay active).
   Strengthened `cross_sectional_momentum_respects_quantiles` to capture and
   assert the symmetric-quantile warning.
3. **`references/strategy_templates.md`** — documented the two validation
   warnings, the recommended asymmetric/non-overlapping configuration, and why
   the single-asset fallback is exempt.

### Verified (evidence)

- Full suite from repo root: **99/99** (was 96; +3 new). test_data_loader
  6/6, test_performance 13/13, test_reporting 10/10 (stdlib unittest, `OK`,
  exit 0), test_run_backtest 19/19, test_strategy_builder 18/18,
  test_walk_forward 18/18, test_cpcv 14/14, test_generate_sample_data 1/1.
- The cpcv/walk-forward param grids use asymmetric combos (top in {0.3,0.4} vs
  bottom in {0.2,0.1}), so the new warnings do not fire there.
- Manual check: default 0.2/0.2 -> warning + all-flat; 0.5/0.8 -> overlap
  warning; 0.4/0.2 -> no warning, 280/300 non-zero signals.

### Decision recorded

- **Portfolio-signal semantics**: kept net exposure `(n_long - n_short) /
  n_assets` (smallest reversible change). The deeper design question — gross
  exposure, per-leg signals, or a true market-neutral long/short book with
  separate cost/turnover modeling — remains open but is now guarded: symmetric
  and overlapping configurations warn instead of failing silently. Changing the
  interface (option 2/3 in the prior HANDOFF) would require updating
  `run_backtest`'s single-scalar-signal interpretation and is deliberately
  deferred.

## Unresolved / methodological notes

- `MeanReversionZScore` is still a single-asset placeholder: its docstring says
  "Pairs Trading style" but it z-scores a single asset's close price, not a
  two-asset spread. No hedge-ratio or spread construction exists.
- Monte Carlo lives in `walk_forward.py` (`monte_carlo_simulation`); no
  separate `monte_carlo.py` script.
- No out-of-sample evidence of profitability exists; all results are synthetic.
  Nothing here is production-ready.

## Next task for the next agent

**Implement a proper two-asset spread z-score mean reversion for
`MeanReversionZScore`** (currently a single-asset placeholder despite its
"Pairs Trading style" docstring).

- Context: `scripts/strategy_builder.py` (`MeanReversionZScore`,
  `STRATEGY_REGISTRY["zscore_mean_reversion"]`), `references/strategy_templates.md`,
  `tests/test_strategy_builder.py`.
- Scope (smallest reversible change, follow the CrossSectionalMomentum pattern):
  1. Accept multi-asset panel data (dict of DataFrames and MultiIndex columns)
     for exactly two assets; construct the spread as the log price ratio
     (or rolling OLS hedge-ratio residual) and z-score it over `period`.
  2. Entry/exit on `entry_z` / `exit_z` of the spread z-score (long the spread
     when z <= -entry_z, short when z >= +entry_z, exit at |z| <= exit_z).
  3. Keep single-asset backward compatibility (current behavior) or emit a
     `UserWarning` and fall back, matching the CrossSectionalMomentum /
     DualMomentum convention.
  4. Add regression tests (two-asset dict, MultiIndex, single-asset fallback,
     known-spread ordering) and update docs.
- Constraints: preserve both panel formats, keep the full suite passing (now
  99 tests), update docs and tests, smallest reversible change. Do not claim
  profitability; all tests remain synthetic.
- Alternative bounded tasks if pairs trading is out of scope: extract Monte
  Carlo into its own `monte_carlo.py` script, or add a multiple-testing /
  data-mining control (e.g. deflated Sharpe or Bonferroni-adjusted top-pick
  selection) to the walk-forward / CPCV parameter search, which currently
  ranks parameter sets without any multiple-comparison correction.

## Test suite quick reference

Run all from repo root (requires pandas/numpy):

```bash
for t in test_data_loader test_performance test_reporting test_run_backtest \
         test_strategy_builder test_walk_forward test_cpcv test_generate_sample_data; do
  python3 skills/quantitative-backtesting/tests/$t.py || exit 1
done
```

`test_reporting.py` uses stdlib `unittest` (exit code / `OK` line is the
pass/fail signal); the rest use the custom `main()` runner printing
`N/N tests passed`.

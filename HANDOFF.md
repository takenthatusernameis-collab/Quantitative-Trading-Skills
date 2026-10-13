# Handoff — Quantitative Trading Skills Repository

**Last updated**: 2026-10-13

## Repository state

- Git: 1 commit on `main` (`cbbfea7`), working tree dirty with this session's changes (uncommitted; do not commit unless asked).
- Skill location: `skills/quantitative-backtesting/` (8 strategies, 7 scripts, 8 test files, 3 reference docs).
- Python deps for the suites: `pandas` and `numpy` (installed into the session user site during this session; not committed).

## Session summary (2026-10-13)

Evaluated the cross-sectional momentum portfolio-signal convention. Verified baseline (96/96 tests passing). Clarified documentation about symmetric quantiles and the net-exposure convention without changing implementation or tests.

### Changes

1. **`references/strategy_templates.md` — Cross-Sectional Momentum notes.** Added clarification that with symmetric quantiles (top == bottom), net signal is 0 (flat) by construction; `run_backtest` applies the scalar portfolio signal to equal-weight portfolio returns; net-zero signal is flat, which differs from "equal long/short books" in cost/slippage realization depending on execution model. Test suite uses asymmetric quantiles.

### Verified (evidence)

- All 8 suites pass from the repo root (96/96 total): test_data_loader 6/6, test_performance 13/13, test_reporting 10/10 (stdlib unittest), test_run_backtest 19/19, test_strategy_builder 15/15, test_walk_forward 18/18, test_cpcv 14/14, test_generate_sample_data 1/1.
- Inspected implementation: `CrossSectionalMomentum` sets signal = `(n_long - n_short) / n_assets` for both dict and MultiIndex panel paths. With symmetric quantiles this is 0 (and overlapping selections can occur, but net count difference is zero); `run_backtest`'s `signals_active` correctly rejects flat signals.
- Confirmed asymmetric case produces non-flat signals and runs through backtest; symmetric case produces flat signals.

### Unresolved / methodological notes

- **Portfolio signal semantics (decision point remains)**: Current convention is net exposure `(n_long - n_short)/n_assets`. Alternative designs: gross exposure `(n_long + n_short)/n_assets` (treat long/short books separately), or emit per-leg allocations. With net-zero, the strategy is flat by construction (different from a market-neutral long/short book with equal gross exposure in terms of turnover/costs and how execution is modeled). The codebase currently models a single scalar portfolio signal applied to equal-weight portfolio returns.
- `MeanReversionZScore` is still a single-asset placeholder (no pairs/z-score implementation).
- Monte Carlo lives in `walk_forward.py` (`monte_carlo_simulation`); no separate `monte_carlo.py` script.
- No out-of-sample evidence of profitability exists; all results are synthetic. Nothing here is production-ready.

## Next task for the next agent

**Decide and implement (if warranted) the preferred cross-sectional momentum portfolio-signal semantics, or add configuration/validation around symmetric quantiles.**

- Context: `scripts/strategy_builder.py` (CrossSectionalMomentum), `references/strategy_templates.md`, `tests/test_strategy_builder.py` (`test_cross_sectional_momentum_respects_quantiles` asserts current behavior).
- Options (smallest reversible change preferred):
  1. Keep as-is (net exposure). Add explicit validation/warning when `top_quantile == bottom_quantile` (or when selections overlap in a way that produces unintended flatness), update docs to be even clearer, and add a regression test documenting this behavior.
  2. Change to gross exposure model (e.g. signal represents gross long+short fraction, or return per-leg signals). This changes semantics and will require updating tests and potentially `run_backtest`'s interpretation (and `DualMomentum` already returns portfolio allocation fraction; consistency matters).
  3. Emit separate long/short signals or a richer structure. But `run_backtest` currently expects a single Series of portfolio signals; changing the interface is a larger scope.
- Constraints: preserve both panel formats, keep full 96-test suite passing, update docs and tests if semantics change, smallest reversible change.
- If keeping semantics unchanged, the immediate concrete task is to add a guard/warning and an explicit regression test for symmetric quantiles (documenting that it produces flat signals). If changing semantics, justify with evidence and update all affected code/tests/docs.

## Test suite quick reference

Run all from repo root (requires pandas/numpy):

```bash
for t in test_data_loader test_performance test_reporting test_run_backtest \
         test_strategy_builder test_walk_forward test_cpcv test_generate_sample_data; do
  python3 skills/quantitative-backtesting/tests/$t.py || exit 1
done
```

`test_reporting.py` uses stdlib `unittest` (exit code is the pass/fail signal); the rest use the custom `main()` runner printing `N/N tests passed`.

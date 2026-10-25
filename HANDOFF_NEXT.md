# Handoff — slow framework suite re-run + bounded quant task (DONE 2026-10-25)

## Context
The prior session repaired three broken root-level scripts
(`debug_strategy.py`, `debug_walk_forward.py`, `simple_momentum_hypothesis.py`);
see `HANDOFF.md`. All five root scripts run end-to-end.

## What changed this session
- Re-ran the slow framework suite (no files touched by the root-script
  repairs are imported by the test suite):
  - `tests/test_walk_forward.py` → 183 passed (matches prior record)
  - `tests/test_cpcv.py` → 29 passed (matches prior record)
  - `tests/test_resolution_vs_sample_size.py` → 77 passed (matches prior record)
  Total 289 passed, 0 failed: no regression from the root-script repairs.
- Added a cost-sensitivity sweep to the root-level
  `simple_momentum_hypothesis.py` (`simple_momentum_hypothesis.py:1`):
  `COST_SWEEP_SETTINGS` (frictionless 0 bps vs advertised 2bp commission +
  1bp slippage), `_run_backtest_metrics`, and `run_cost_sweep`, invoked from
  `main()` after the hypothesis test. The sweep is a regression guard: it
  asserts the frictionless run beats the costed run on both net Sharpe and net
  total return, so a cost path that silently no-ops would fail.
  Verified: `python3 simple_momentum_hypothesis.py` exits 0; hypothesis
  verdict NOT SUPPORTED (OOS Sharpe −0.9042, total return −5.06% vs benchmark
  +8.09% — valid falsification); cost sweep shows frictionless Sharpe
  −0.8883/return −4.98% vs costed Sharpe −0.9042/return −5.06% (cost path
  live).
- Ran related fast tests: `test_simple_momentum_hypothesis.py`,
  `test_falsifiable_hypothesis_example.py`, `test_examples_coverage.py` →
  60 passed, 0 failed.

## What remains unresolved
- `debug_walk_forward.py` is a smoke test on synthetic data (OOS Sharpe −1.46
  on 300 bars); it says nothing about any market and is not a research
  artifact.
- The root-level `simple_momentum_hypothesis.py` reports alpha vs the shipped
  benchmark but has no multiple-benchmark/deflated-alpha output (the skill's
  `performance.py` already supports `--benchmark SPY QQQ IWM` with Deflated
  Alpha; see `IMPLEMENTATION_SUMMARY.md`).

## One precise next task (this session — DONE)
Extended section 8 of
`skills/quantitative-backtesting/examples/falsifiable_hypothesis_example.py`
to report `minimum_detectable_alpha`-vs-sample-size for all three validation
paths (out_of_sample, walk_forward, cpcv), pinned to the example's own
0.6/0.2/0.2 split and cost settings, instead of only the held-out window.
Added `PATH_WALK_FORWARD`/`PATH_CPCV` imports from
`scripts/measure_resolution_vs_sample_size.py`. Verified: example standalone
exit 0 (section 8 prints all three paths);
`test_falsifiable_hypothesis_example.py` → 17 passed, exit 0; diff scoped to
one file (42 insertions, 32 deletions).

## One precise next task (next session)
Extend the example's section 6 resolution block (and the returned `resolution`
dict) to carry per-path `minimum_detectable_alpha`/`minimum_detectable_sharpe`
for out_of_sample, walk_forward, and cpcv — additive to the existing
out-of-sample block — so the structured result, not just console section 8,
reflects each validation path's data requirement. Verify: example exits 0 and
`test_falsifiable_hypothesis_example.py` still 17/17 (the resolution-block test
asserts the out-of-sample keys; adding per-path keys is additive).

## Constraints
- Smallest reversible change; do not redesign orchestration or weaken
  permissions/safety controls.
- Verify with the focused test command, then the broader suite:
  `cd skills/quantitative-backtesting/tests && python3 -m pytest ...`
- Set `PYTHONPATH` to the skill's `scripts` dir when running scripts directly;
  deps (numpy/pandas/matplotlib/pytest) are in the user env
  (installed via `pip install --user numpy pandas pytest`).
- Do not commit unless explicitly asked.

(End of file - total 58 lines)

# Handoff — next task: slow framework suite re-run + bounded quant task

## Context
The current session repaired three broken root-level scripts
(`debug_strategy.py`, `debug_walk_forward.py`, `simple_momentum_hypothesis.py`);
see `HANDOFF.md` for the full change record. All five root scripts now run
end-to-end, and the fast test suite (104 tests across
`test_examples_coverage.py`, `test_falsifiable_hypothesis_example.py`,
`test_simple_momentum_hypothesis.py`, `test_performance.py`,
`test_out_of_sample_window.py`, `test_reproducible_backtest_example.py`)
passes. No skill source or test file was modified.

## One precise next task
Re-run the slow framework suite to confirm no regression from the root-script
repairs, then pick **one** bounded quant research task from
`skills/quantitative-backtesting/` with concrete verification.

Slow files to re-run (prior handoff recorded them passing: 183 / 29 / 77
tests):
- `skills/quantitative-backtesting/tests/test_walk_forward.py`
- `skills/quantitative-backtesting/tests/test_cpcv.py`
- `skills/quantitative-backtesting/tests/test_resolution_vs_sample_size.py`

If any fail, triage against this change first (it touched only the three root
scripts, none of which are imported by the test suite).

## Candidate bounded quant tasks (pick one, verify concretely)
1. **Cost-sensitivity sweep for `simple_momentum_hypothesis.py`** — the example
   advertises "3 bps round-trip" but has no regression guard that the cost
   path is live. Add a zero-cost vs costed comparison (like
   `test_falsifiable_hypothesis_example.py::test_the_advertised_costs_are_
   actually_applied`) and record the observed Sharpe/return at both settings.
2. **Extend the falsifiable example's resolution reporting** — it already
   reports minimum detectable effects; a natural next step is a
   `measure_resolution_vs_sample_size.py`-style curve for the *held-out*
   window specifically, so the example's "how much data do I need" guidance is
   pinned to its own configuration rather than the pooled-OOS paths.

## Constraints
- Smallest reversible change; do not redesign orchestration or weaken
  permissions/safety controls.
- Verify with the focused test command, then the broader suite:
  `cd skills/quantitative-backtesting/tests && python3 -m pytest ...`
- Set `PYTHONPATH` to the skill's `scripts` dir when running scripts directly;
  deps (numpy/pandas/matplotlib/pytest) are in the user env.
- Do not commit unless explicitly asked.

(End of file - total 37 lines)
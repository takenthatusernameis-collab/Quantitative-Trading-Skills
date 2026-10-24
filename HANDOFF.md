# Handoff — root-level research scripts repaired (2026-10-24)

## What changed
Three root-level scripts were broken (dead on import/run) and one had stale
parameters. All five root-level scripts now run end-to-end:

- `debug_strategy.py` — fixed the `SKILLS_DIR` path: it pointed at
  `Path(__file__).resolve().parent.parent` (the repo root), so
  `SKILLS_DIR / "scripts"` resolved to `<repo>/scripts`, which does not exist.
  It now points at `.../skills/quantitative-backtesting`. Verified: exit 0,
  signals/returns print for 4 parameter sets.
- `debug_walk_forward.py` — same `SKILLS_DIR` path bug, plus the synthetic
  sample was only 100 bars, which is below the walk-forward window's minimum
  (6+2 month train/test with 2-month step needs ~140+ bars). Bumped the sample
  to 300 bars. Verified: exit 0, 3 walk-forward periods produced, OOS Sharpe
  −1.46, params selected per period.
- `simple_momentum_hypothesis.py` — the whole body was a stale copy of an
  earlier API: it called `run_backtest(data_path=..., strategy_name=...)`,
  but the current signature is
  `run_backtest(data, strategy, args, data_provenance=None, benchmark=None,
  survivorship=None)` where `args` is an `argparse.Namespace` built by
  `parse_args()` in the same module. Rewrote it as a thin wrapper around the
  `run_backtest.py` CLI (subprocess), matching the sibling example
  `skills/quantitative-backtesting/examples/simple_momentum_hypothesis.py`,
  while keeping the root-level path resolution. Verified: exit 0, verdict
  `NOT SUPPORTED` (Sharpe −0.90, total return −5.06% vs benchmark +8.09% on
  the shipped sample — a valid falsification, not a script failure).

`verify_end_to_end.py` and `test_import.py` were already correct and are left
unchanged.

## What was actually verified
- All five root scripts exit 0:
  `simple_momentum_hypothesis.py`, `debug_strategy.py`, `debug_walk_forward.py`,
  `verify_end_to_end.py`, `test_import.py`.
- `skills/quantitative-backtesting/tests/test_examples_coverage.py` → 39 passed
  (covers `simple_momentum_hypothesis.py` end-to-end, imports, hypothesis/cost
  banner, PIT split, falsification verdict).
- `skills/quantitative-backtesting/tests/test_falsifiable_hypothesis_example.py`
  → 17 passed.
- `skills/quantitative-backtesting/tests/test_simple_momentum_hypothesis.py` →
  3 passed.
- `skills/quantitative-backtesting/tests/test_performance.py` → 33 passed.
- `skills/quantitative-backtesting/tests/test_out_of_sample_window.py` → 11
  passed.
- `skills/quantitative-backtesting/tests/test_reproducible_backtest_example.py`
  → passed.
- `skills/quantitative-backtesting/examples/falsifiable_hypothesis_example.py`
  standalone → exit 0, verdict `NOT SUPPORTED` (OOS Sharpe −0.3581, DAR
  0.4378), unchanged from the prior handoff's recorded values.
- No test file or skill source was modified; only the three root scripts.
- Regenerated `example_reproducible_output/*` artifacts (mtime-normalized
  timestamps) were reverted so the diff stays scoped to the root scripts.

## What remains unresolved
- The slow framework suite (`test_walk_forward.py`, `test_cpcv.py`,
  `test_resolution_vs_sample_size.py`) was not re-run this session; they were
  not touched by this change and are presumed unaffected. Prior handoff
  recorded them passing (183 / 29 / 77).
- `debug_walk_forward.py` runs `walk_forward_analysis` with `apply_deflation=
  False` and no benchmark cost sweep; it is a smoke test, not a research
  artifact. Its 3-period OOS Sharpe of −1.46 is on 300 bars of synthetic data
  and says nothing about any market.

## Approaches already tried
- Diagnosed by reproducing the failures directly rather than guessing:
  `python3 simple_momentum_hypothesis.py` raised
  `TypeError: run_backtest() got an unexpected keyword argument 'data_path'`;
  `debug_strategy.py` / `debug_walk_forward.py` raised
  `ModuleNotFoundError: No module named 'strategy_builder'` /
  `'walk_forward'`. Both traced to a single root cause — the scripts computed
  the skills directory from `parent.parent` (repo root) instead of
  `parent / "skills" / "quantitative-backtesting"`.
- Considered deleting the root scripts instead of fixing them. Rejected: they
  are tracked files and the simplest reversible change that restores them is a
  fix, not a deletion.

## One precise next task
- Re-run the slow framework suite to confirm no regression, then pick one
  bounded quant research task from `skills/quantitative-backtesting/` (e.g.
  extend the falsifiable example's resolution reporting, or add a
  cost-sensitivity sweep to `simple_momentum_hypothesis.py`) with concrete
  verification. Relevant slow files:
  `skills/quantitative-backtesting/tests/test_walk_forward.py`,
  `tests/test_cpcv.py`, `tests/test_resolution_vs_sample_size.py`.

(End of file - total 36 lines)
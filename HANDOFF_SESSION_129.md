# Handoff — Session 129 (2026-11-16T~21:00Z): zscore import bug fixed; full gate GREEN

## What changed
- One source change, one file, -113 lines: removed the dead, never-called
  `run_walk_forward_borrow_cost_sweep(...)` function from
  `skills/quantitative-backtesting/examples/zscore_mean_reversion_hypothesis.py:735-845`.
- Root cause of the gate failure: that function's default argument referenced
  `BORROW_COST_SWEEP_LEVELS`, a name that was **never defined anywhere in the
  module** (the module defines `COST_SWEEP_LEVELS` and
  `ELEVATED_COST_SWEEP_LEVELS`, but not a borrow-cost constant). Because the
  default is evaluated at function-definition time (module import), the whole
  module failed to import, which broke collection of **every** test that imports
  `zscore_mean_reversion_hypothesis` -- 104 collection errors across the zscore
  test family (`test_zscore_mean_reversion_hypothesis.py`,
  `test_zscore_param_sensitivity_real_*.py`,
  `test_zscore_mean_reversion_benchmark_*.py`, etc.).
- The function body also referenced three other names that do not exist in the
  module (`_run_walk_forward_metrics`, `RAW_SHARPE_THRESHOLD`,
  `TOTAL_RETURN_THRESHOLD`), so it could not have run even if called. It was
  unreferenced by any test, example, CLI or doc (verified by grep across the
  repo), so removal is a pure defect fix, not a feature removal.
- No test, constant, threshold, verdict, cost level, fixture, or marketplace
  asset was changed. No parameter was tuned to force a green result.

## What was actually verified
- `python3 -c "import zscore_mean_reversion_hypothesis"` -> clean (was a
  `NameError` before the fix).
- `python3 -m pytest skills/quantitative-backtesting/tests/test_zscore_mean_reversion_hypothesis.py -p no:cacheprovider -q` -> **9 passed**.
- Full quant gate, run to completion (not just collection):
  `cd skills/quantitative-backtesting && python3 -m pytest tests/ -p no:cacheprovider -q -rf --tb=line`
  -> **1472 passed, 0 failed, 0 errors, EXIT 0** (5405 s / 1:30:05).
- Root-level regression guards re-run directly (not via the full gate):
  `test_root_debug_scripts.py`, `test_root_scripts_pit_bias_controls.py`,
  `test_root_simple_momentum_real_{aapl,googl,msft}.py`,
  `test_root_simple_momentum_cost_real_{googl,msft}.py` -> all pass.
- Focused handoff tests re-run directly: `test_no_selection_diagnosis.py` and
  `test_resolution_vs_sample_size.py` -> **113 passed, 0 failed** (344 s).
- Prior-session book-pricing fix confirmed present in source:
  `walk_forward.py:4341` passes `warmup_data=fold.get("warmup_data")` to
  `_window_book_diagnostic` in the CPCV fold loop; the warmup convention at
  `walk_forward.py:3974-4002` is causal (`warmup_data =
  data.iloc[warmup_start_idx:test_start_idx]`, strictly pre-test, used only to
  initialize rolling indicators; test returns sliced to test indices) and is
  documented in a comment so it is not "fixed" back.
- Working tree: clean except the one intentional source change. Gate-dirtied
  generated artifacts under `examples/example_reproducible_output/` (only a
  `load_timestamp` field differs) were reverted with `git checkout --`.

## Environment / verification limits (not claimed)
- Dependencies (`pytest`, `pandas`, `numpy`, `scipy`, `matplotlib`) were **not**
  present in this environment at session start (`ModuleNotFoundError: No module
  named 'pytest'`); they were installed with `python3 -m pip install` into the
  user site. The full gate therefore ran here rather than in a direnv/nix
  shell. The 1:30:05 runtime is the real full-gate cost; do not re-run it as a
  blocking in-session command without adequate budget -- use `-n 4` and, if
  generated artifacts get dirtied, revert only `examples/example_output/*` and
  `scripts/results/*` (and `examples/example_reproducible_output/` here).
- No live market data was used; every test runs on committed synthetic or
  committed real fixtures. No strategy is claimed profitable or capacity-
  supported anywhere in this session's changes.

## What remains unresolved
- No test failures remain. Open methodological gaps carried over from prior
  handoffs, none of which this session touched:
  - CPCV/Monte Carlo `regime_analysis` end-to-end CLI tear-sheet coverage only
    partially evidenced.
  - Borrow/funding cost realism on committed fixtures still has no dedicated
    walk-forward/CPCV sensitivity test (only `run_backtest.py`-level and
    zscore-pair-level borrow sweeps exist).
  - No new falsifiable hypothesis with genuinely out-of-sample evidence net of
    plausible costs/impact was added this session.
- TSMOM verdicts remain sensitivity-only/falsified per prior sessions (triple
  panel OOS Sharpe -0.1241, total return -14.43%, DSR p=0.9178) -- do not claim
  profitability or capacity.

## Approaches already tried / failed (do not repeat unchanged)
- Re-running the full serial gate as a blocking in-session command with a short
  timeout: it exceeds any single in-session budget (1:30:05 at `-n 4`; longer
  serially). Run it in background and poll, or defer to CI.
- Blindly re-pinning expectations to silence failures: not applicable this
  session -- the 17 pre-existing CPCV behavior-pin failures named in
  `HANDOFF.md` are **already reconciled in the committed source**; re-running
  them green is verification, not re-pinning.
- Do not `git checkout -- .` blindly after a gate run (discards intentional
  source work); revert only the known dirtied generated-artifact paths.
- Do not tune parameters/costs/verdicts to force SUPPORT.

## One precise next task
Pick the next bounded methodological gap per the AGENTS.md quant mission --
prefer, in order: (a) a pre-registered **borrow/funding-cost sensitivity sweep**
for an existing long/flat TSMOM path on committed real fixtures, additive, with
fixed cost levels, no parameter tuning, and directional assertions consistent
with cost mechanics (higher borrow/funding must not improve net performance for
positions that incur it); or (b) point-in-time / survivorship-bias controls, or
(c) a new falsifiable hypothesis with genuinely OOS evidence net of plausible
costs. Do not add another strategy falsification test and do not claim
profitability. After the change, run the focused test, then the full gate
`python3 -m pytest skills/quantitative-backtesting/tests/ -p no:cacheprovider -q -n 4`
in background (expect ~1472+ passed, EXIT 0) and revert only gate-dirtied
generated artifacts. Do not commit unless explicitly asked.
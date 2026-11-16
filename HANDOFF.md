# Handoff — Session 129 (2026-11-16): zscore import bug fixed; full gate GREEN (1472 passed, 0 failed)

## What changed (this session)
- One source change, one file, -113 lines: removed the dead, never-called
  `run_walk_forward_borrow_cost_sweep(...)` function from
  `skills/quantitative-backtesting/examples/zscore_mean_reversion_hypothesis.py:735-845`.
- Root cause of the prior gate failure: that function's default argument referenced
  `BORROW_COST_SWEEP_LEVELS`, a name **never defined anywhere in the module** (the
  module defines `COST_SWEEP_LEVELS` and `ELEVATED_COST_SWEEP_LEVELS`, but no
  borrow-cost constant). Because the default is evaluated at function-definition time
  (module import), the whole module failed to import, breaking collection of **every**
  test that imports `zscore_mean_reversion_hypothesis` -- 104 collection errors across
  the zscore test family. The function body also referenced three other undefined names
  (`_run_walk_forward_metrics`, `RAW_SHARPE_THRESHOLD`, `TOTAL_RETURN_THRESHOLD`), so it
  could not have run even if called. It is unreferenced by any test, example, CLI or doc
  (verified by grep), so removal is a pure defect fix, not a feature removal.
- The 17 pre-existing CPCV behavior-pin failures named in the previous handoff are
  **already reconciled in the committed source**; this session verified them green by
  direct re-run, not by re-pinning. The warmup convention at
  `walk_forward.py:3974-4002` is causal and documented; the book-pricing fix at
  `walk_forward.py:4341` is present.
- NOT committed (per instructions). Working tree clean except the one intentional source
  change. Gate-dirtied generated artifacts under `examples/example_reproducible_output/`
  (only a `load_timestamp` field differs) were reverted with `git checkout --`.

## What was actually verified (this session)
- `python3 -c "import zscore_mean_reversion_hypothesis"` -> clean (was a `NameError`).
- `python3 -m pytest skills/quantitative-backtesting/tests/test_zscore_mean_reversion_hypothesis.py -p no:cacheprovider -q` -> **9 passed**.
- Full quant gate, run to completion (not just collection):
  `cd skills/quantitative-backtesting && python3 -m pytest tests/ -p no:cacheprovider -q -rf --tb=line`
  -> **1472 passed, 0 failed, 0 errors, EXIT 0** (5405 s / 1:30:05).
- Focused handoff tests re-run directly: `test_no_selection_diagnosis.py` and
  `test_resolution_vs_sample_size.py` -> **113 passed, 0 failed** (344 s).
- Root-level regression guards re-run directly: `test_root_debug_scripts.py`,
  `test_root_scripts_pit_bias_controls.py`, `test_root_simple_momentum_real_{aapl,googl,msft}.py`,
  `test_root_simple_momentum_cost_real_{googl,msft}.py` -> all pass.
- All `skills/quantitative-backtesting/examples/*.py` modules import cleanly.

## Environment / verification limits (not claimed)
- Dependencies (`pytest`, `pandas`, `numpy`, `scipy`, `matplotlib`) were **not** present at
  session start (`ModuleNotFoundError: No module named 'pytest'`); installed with
  `python3 -m pip install` into the user site. The full gate ran here, not in a direnv/nix
  shell. The 1:30:05 runtime is the real full-gate cost -- do not re-run it as a blocking
  in-session command; use `-n 4` in background and revert only gate-dirtied generated
  artifacts (`examples/example_output/*`, `scripts/results/*`,
  `examples/example_reproducible_output/`) afterward.
- No live market data used; every test runs on committed synthetic or committed real
  fixtures. No strategy is claimed profitable or capacity-supported.

## What remains unresolved
- No test failures remain. Open methodological gaps carried over, none touched this session:
  - CPCV/Monte Carlo `regime_analysis` end-to-end CLI tear-sheet coverage only partially evidenced.
  - Borrow/funding cost realism on committed fixtures still has no dedicated
    walk-forward/CPCV sensitivity test (only `run_backtest.py`-level and zscore-pair-level
    borrow sweeps exist).
  - No new falsifiable hypothesis with genuinely OOS evidence net of plausible costs/impact.
- TSMOM verdicts remain sensitivity-only/falsified (triple panel OOS Sharpe -0.1241, total
  return -14.43%, DSR p=0.9178) -- do not claim profitability or capacity.

## Approaches already tried / failed (do not repeat unchanged)
- Re-running the full serial gate as a blocking in-session command with a short timeout:
  exceeds any single in-session budget (1:30:05 at `-n 4`; longer serially). Run in
  background and poll, or defer to CI.
- Blindly re-pinning expectations to silence failures: REJECTED (weakens guards; not
  methodological progress). Not applicable this session -- the CPCV pins are already
  reconciled in source.
- Do not `git checkout -- .` blindly after a gate run (discards intentional source work);
  revert only the known dirtied generated-artifact paths.
- Do not tune parameters/costs/verdicts to force SUPPORT.

## One precise next task (for the next agent)
Pick the next bounded methodological gap per the AGENTS.md quant mission -- prefer, in
order: (a) a pre-registered **borrow/funding-cost sensitivity sweep** for an existing
long/flat TSMOM path on committed real fixtures, additive, with fixed cost levels, no
parameter tuning, and directional assertions consistent with cost mechanics (higher
borrow/funding must not improve net performance for positions that incur it); or (b)
point-in-time / survivorship-bias controls, or (c) a new falsifiable hypothesis with
genuinely OOS evidence net of plausible costs. Do not add another strategy falsification
test and do not claim profitability. After the change, run the focused test, then the full
gate `python3 -m pytest skills/quantitative-backtesting/tests/ -p no:cacheprovider -q -n 4`
in background (expect ~1472+ passed, EXIT 0) and revert only gate-dirtied generated
artifacts. Do not commit unless explicitly asked.
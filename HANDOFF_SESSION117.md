# Handoff — Session 117: pin/criteria consistency guard (full gate GREEN, 1451 passed)

## What changed (this session)
- The task assigned by `HANDOFF_SESSION116.md` (regime-conditional
  commission/slippage multipliers) was **already implemented and committed**
  in `8497210` before this session (2026-11-15 17:49). It was not repeated.
  Evidence: `utils.regime_cost_multiplier_series`, `--regime-cost-multipliers`
  in `run_backtest.py`, `regime_cost_multipliers` in `walk_forward.py`, and
  `tests/test_regime_cost_multiplier.py` (11/11 pass standalone).
- Implemented the handoff's fallback: a **static pin/criteria consistency
  guard** for the benchmark-aware falsification tests.
  - New file: `skills/quantitative-backtesting/tests/test_pin_criteria_consistency.py`
    (standard library + `ast` only, no backtests).
  - It parses every `test_*benchmark_aware*.py` file that pins both an
    `EXPECTED` metrics dict and an `expected_criteria` booleans dict, derives
    the four criteria from the pinned metrics (`oos_sharpe > 0`,
    `total_return > benchmark_total_return`, `deflated_sharpe_pvalue < 0.10`,
    `benchmark_alpha_pvalue < 0.05`), and fails on any mismatch.
  - It also fails if the statically checkable set drops below
    `MIN_CHECKABLE_FILES = 15`, so the guard cannot silently become vacuous.
  - It includes a self-test that injects the exact historical bug shape
    (`sharpe_ratio = 0.695` next to `oos_sharpe_gt_zero: False`) and asserts
    the guard flags it, plus a consistent-pair negative control.
- Documented the guard in
  `skills/quantitative-backtesting/references/validation_methods.md`
  ("Pin/criteria consistency guard for benchmark-aware tests").
- **No production code changed.** Working tree: one modified doc, one new test
  file; nothing committed (per instruction).

## What was actually verified (evidence)
- Full gate:
  `python3 -m pytest skills/quantitative-backtesting/tests/ -p no:cacheprovider -q -n 4`
  -> **1451 passed, 0 failed, 518 warnings, EXIT 0** (31 min 23 s).
  (1436 prior + 11 regime-cost tests from `8497210` + 4 new guard tests.)
- Focused run of the new guard + three benchmark-aware triple tests
  (bollinger / donchian / dual momentum) -> **9 passed** (19.1 s).
- Guard standalone -> 4/4 PASS; `19/33` benchmark-aware files statically
  checkable.
- Real-file mutation check: copied
  `test_bollinger_bands_benchmark_aware_real_triple_aapl_msft_googl.py`, flipped
  `"oos_sharpe_gt_zero": False` to `True`, and confirmed the guard reports
  `criterion 'oos_sharpe_gt_zero' pinned True but EXPECTED metrics imply False`.
- Environment: Python 3.14.4, numpy 2.5.4, pandas 3.1.1, scipy 1.18.1,
  pytest-xdist 3.8.0.

## What remains unresolved
- The guard covers the `expected_criteria` dict pattern only (19 of 33
  benchmark-aware files; 20 of 33 have `expected_criteria`, one of those pins
  metrics inline and is skipped). It does **not** yet cover the walk-forward /
  CPCV pattern where criteria are built at runtime and asserted individually
  (`assert criteria[...]` / `assert passes[...]`), nor non-benchmark-aware
  tests that pin `oos_sharpe` / `total_oos_return` with hardcoded booleans.
  That is the class of `test_walk_forward_kelly_criterion_real_aapl.py`.
- `regenerate_pins.py` still re-bases metric dicts and structural counts but
  never verdict criteria. The new guard catches the resulting contradiction
  after the fact; it does not prevent `regenerate_pins.py` from creating one.
- 518 warnings remain (pandas `set_index(inplace=True)` deprecation in the
  `*_structure.py` tests, cross-sectional-momentum flat-signal warnings, one
  Monte-Carlo dof warning). Non-fatal; not addressed.
- There is still **no CI workflow** that runs the quant gate; the gate is only
  reproducible locally (`-n 4`, ~31 min).

## Approaches already tried / failed (do not repeat unchanged)
- Re-running `regenerate_pins.py` and stopping: it updates metric dicts and
  structural counts but never criterion booleans or docstrings; that is how the
  session-116 contradictions were created.
- Full gate serial: timed out (~60 min). `-n 4` completes in ~31 min; use it.
- Flipping a criterion just to make the gate green without checking the pinned
  metric: rejected; every change must be derived from the measured/pinned value.
- Re-implementing the session-116 regime-cost-multiplier task: already done in
  `8497210`; repeating it would be wasted work.

## One precise next task (for the next agent)
Extend `test_pin_criteria_consistency.py` to the **runtime-criteria /
individual-assert pattern**, starting with the walk-forward tests that the
historical bug actually hit. Evidence and constraints:
1. `test_walk_forward_kelly_criterion_real_aapl.py:135` pins
   `EXPECTED = {"oos_sharpe": 0.695..., "total_oos_return": 0.799...}` and at
   `:161-170` asserts `passes["oos_sharpe_gt_zero"] is True`,
   `passes["oos_total_return_positive"] is True`,
   `passes["deflated_sharpe_pvalue_lt_0.10"] is False`. The DSR p-value
   (0.4455900094498011) is pinned inline at `:154`, not in `EXPECTED`.
2. `test_walk_forward_dual_momentum_benchmark_aware_real_triple_aapl_msft_googl.py:128-139`
   and
   `test_walk_forward_rsi_mean_reversion_benchmark_aware_real_pair_aapl_googl.py:131-142`
   build a `criteria = {...}` dict at runtime and assert each boolean with
   `assert criteria["..."] is <bool>`; both also pin `EXPECTED` later in the
   same test.
3. Add a parser for `assert <name>[...]` / `assert passes[...]` lines
   (AST or regex over the source), map criterion aliases
   (`oos_total_return_positive` = `total_oos_return > 0`), and compare the
   asserted boolean to the value derived from `EXPECTED`.
4. For criteria whose metric is not in `EXPECTED` (the kelly DSR p-value), skip
   with a recorded reason rather than guessing; optionally parse the inline
   `assert abs(dsr_p - <num>) <= ...` pin if it is unambiguous.
5. Add a self-test for the new pattern and keep the `MIN_CHECKABLE_FILES` floor
   honest (raise it if the covered set grows).
6. Re-run the focused files and then the full gate `-n 4`; require EXIT 0.
   Do not commit unless asked.
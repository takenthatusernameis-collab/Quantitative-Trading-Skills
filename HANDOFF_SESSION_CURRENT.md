# Handoff — Current State (session 155): TSMOM protocol-sensitivity study added

## Latest

- Full detail: see `HANDOFF_SESSION_155.md`.
- Prior baseline (session 154): clean full gate **1559 passed, 0 failed**
  (`pytest skills/quantitative-backtesting/tests/ -p no:cacheprovider -q -n 4`, ~29m).
  That full gate was **not re-run** this session; expected total ≈ 1564 (+5 new tests).

## What changed this session (session 155)

- Added `skills/quantitative-backtesting/tests/test_walk_forward_time_series_momentum_protocol_sensitivity_real_triple.py`
  (5 tests): a pre-registered walk-forward **protocol-sensitivity** study for
  standalone TSMOM across 4 informative 12-month-test protocols + 2 short-window
  protocols on AAPL/MSFT/GOOGL, with a pinned 18-cell matrix and honest
  protocol-dependence assertions.
- Added a "Evaluation-Protocol Sensitivity" subsection to
  `skills/quantitative-backtesting/references/validation_methods.md`.

## Key finding (honest, not a profitability claim)

The TSMOM OOS verdict is protocol-dependent: every symbol's OOS Sharpe flips sign
across equally-valid 12-month protocols (AAPL -0.39→+1.06, MSFT -0.41→+1.22,
GOOGL -0.21→+0.10); exactly 1 of 12 informative cells passes the pre-registered
criteria (MSFT 30/12/12) and that lone pass dies under a Bonferroni correction for
the 4 protocols tried. Single-protocol NOT SUPPORTED verdicts are therefore
protocol-conditional.

## Verified

- New test: 5/5 standalone, 5 passed under pytest, 11 passed alongside existing
  AAPL/MSFT/GOOGL TSMOM walk-forward tests; `py_compile` OK.
- Working tree: 1 new test file + validation_methods.md (+38 lines); no engine change.

## One precise next task

Generalize the protocol-sensitivity study to **cross-sectional momentum** on the
committed AAPL/MSFT/GOOGL triple panel (pre-register the same 4 protocols / grid /
costs / criteria; pin the matrix; assert whether the sign-flip / multiplicity
pattern generalizes). Constraints: offline fixtures, default JSON unchanged, no
profitability claim, do not commit unless asked. Fallback: wire
`utils.benjamini_hochberg`/Bonferroni across the protocol family for a
multiplicity-corrected pass count. Full context in `HANDOFF_SESSION_155.md`.

(End of file)
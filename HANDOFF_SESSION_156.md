# Handoff — Session 156: cross-sectional momentum protocol-sensitivity study

## What changed

- **New test file (test-only, no engine change):**
  `skills/quantitative-backtesting/tests/test_walk_forward_cross_sectional_momentum_protocol_sensitivity_real_triple.py`
  - 5 registered tests + `main()` + `TEST_REGISTRY` (follows repo convention).
  - Runs cross-sectional momentum (`cross_sectional_momentum`, long top-quantile / short bottom-quantile, `panel_pricing="book"`) walk-forward on the committed AAPL/MSFT/GOOGL triple panel across a pre-registered protocol matrix:
    - Informative 12-month-test protocols: (24,12,12), (36,12,12), (18,12,12), (30,12,12).
    - 6-month-test protocols: (36,6,6), (24,6,6).
    - Fixed lookback grid `{"lookback": [60,126,252], "top_quantile": [0.4], "bottom_quantile": [0.2]}`, fixed costs (2 bps commission + 1 bps slippage), within-protocol Deflated Sharpe, three pre-registered criteria (OOS Sharpe > 0, OOS total return > 0, DSR p < 0.10).
  - Pins the full 6-cell matrix (rounded to 4 dp, abs tol 1e-3) as a regression guard and asserts the honest protocol-dependence findings.
  - Diff is scoped: 1 untracked test file; working tree otherwise clean; no engine/fixture change; default JSON output untouched.

## The finding (evidence, not a profitability claim)

Cross-sectional momentum is a portfolio strategy over the whole panel, so there is one cell per protocol (not one per symbol):

| protocol | n_periods | positions | OOS Sharpe | total OOS return | DSR p-value | all criteria? |
|---|---:|---:|---:|---:|---:|---|
| (24,12,12) | 3 | 3 | -0.6737 | -0.1074 | 0.9988 | no |
| (36,12,12) | 2 | 2 | -0.9806 | -0.1085 | 0.9819 | no |
| (18,12,12) | 4 | 4 | -0.0789 | +0.0291 | 0.9661 | no |
| (30,12,12) | 3 | 3 | +0.3966 | +0.1744 | 0.5896 | no |
| (36,6,6) | 5 | 5 | +0.5903 | +0.1854 | 0.2794 | no |
| (24,6,6) | 7 | 7 | -0.1585 | +0.0003 | 0.9228 | no |

- **Sign flip generalizes:** panel-level OOS Sharpe flips sign across the four equally-valid 12-month protocols (-0.6737 → +0.3966), so the 24/12/12 NOT SUPPORTED verdict is protocol-conditional — same structural finding as time-series momentum.
- **No cell passes all three criteria.** The best nominal cell (30,12,12) clears Sharpe > 0 and return > 0 but fails on DSR p (0.5896); Bonferroni across 4 protocols → 2.36 > 0.10. Unlike TSMOM there is no "lone pass that dies under multiplicity" — the falsification is cleaner: NOT SUPPORTED across the board.
- Baseline (24,12,12) fails all criteria, matching the single-protocol test.
- Contrast with TSMOM: 6-month-test windows are NOT degenerate here (positions taken every period), since cross-sectional momentum ranks across assets with ample lookback history; they carry evidence but still fail criteria.

## What was actually verified

- New file standalone (`python3 .../test_walk_forward_cross_sectional_momentum_protocol_sensitivity_real_triple.py`): **5/5 passed**.
- Under pytest alongside the existing pinned test `test_walk_forward_cross_sectional_momentum_real_triple_aapl_msft_googl.py`: **7 passed in 165.5s**; existing pinned metrics (OOS Sharpe -0.3533, DSR p 0.9800) still reproduce — no regression.
- `python3 -m py_compile` on the new file: OK.
- Dependencies used for verification: numpy==2.5.4, pandas==3.1.1, scipy==1.18.1, matplotlib==3.11.2, pytest==9.2.0, pytest-xdist==3.8.0 (installed in `/tmp/quantvenv`; not committed).

## What remains unresolved

- The **full gate was NOT re-run** this session (~29 min). Prior baseline: 1559 passed (session 154), then session 155 added 5 (≈1564 expected). This session adds 5 more (≈1569 expected). The focused runs above are the only re-verification.
- No profitability/capacity claim; committed-fixture verdicts remain NOT SUPPORTED for every protocol.
- Framework still corrects multiplicity only within a protocol; no across-protocol multiplicity adjustment in aggregate reporting (building blocks exist: `utils.benjamini_hochberg`, Bonferroni fallback).

## Approaches already tried / failed

- None failed. Initial probe used the strategy's default symmetric quantiles (0.2/0.2), which emit a flat-signal warning and produce flat/negative results — corrected by pre-registering asymmetric quantiles (0.4/0.2) per the existing cross-sectional momentum test convention.

## One precise next task

Run the full gate `pytest skills/quantitative-backtesting/tests/ -p no:cacheprovider -q -n 4` (offline/committed fixtures, ~29m) from the repo root and confirm the only failures are the 9 pre-existing `test_reporting.py` ones, with no new failure introduced by the new protocol-sensitivity test file. Record pass/fail counts. Constraints: do not commit unless explicitly asked; do not treat a green subset as a full baseline. If the full gate is clean, the cross-sectional momentum protocol-sensitivity study is fully integrated; the follow-up research question (wire `utils.benjamini_hochberg`/Bonferroni across the protocol family for a multiplicity-corrected pass count, with a unit test) remains optional.

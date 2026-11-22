# Handoff — Session 155: TSMOM walk-forward protocol-sensitivity study (protocol-selection bias documented)

## What changed

- **New test file (test-only, no engine change):**
  `skills/quantitative-backtesting/tests/test_walk_forward_time_series_momentum_protocol_sensitivity_real_triple.py`
  - 5 registered tests + `main()` + `TEST_REGISTRY` (follows repo convention).
  - Runs standalone TSMOM (`time_series_momentum`, long/flat) walk-forward on the
    committed AAPL/MSFT/GOOGL fixtures across a **pre-registered** protocol matrix:
    - Informative 12-month-test protocols: (24,12,12), (36,12,12), (18,12,12), (30,12,12).
    - Short-window 6-month-test protocols: (36,6,6), (24,6,6).
    - Fixed lookback grid `{126,189,252}`, fixed costs (2 bps commission + 1 bps
      slippage), within-protocol Deflated Sharpe, three pre-registered criteria
      (OOS Sharpe > 0, OOS total return > 0, DSR p < 0.10).
  - Pins the full 18-cell matrix (rounded to 4 dp, abs tol 1e-3) as a regression
    guard and asserts the honest protocol-dependence findings.
- **Methodology note:** `skills/quantitative-backtesting/references/validation_methods.md`
  gained a new subsection **"Evaluation-Protocol Sensitivity (Window-Length Degrees
  of Freedom)"** (inserted before "Per-Period / Per-Fold `test_sharpe`") that
  explains protocol-selection bias, points at the new test, and records the
  concrete finding.

## The finding (evidence, not a profitability claim)

Across the four equally-valid 12-month-test protocols, the TSMOM OOS verdict is
strongly **protocol-dependent**:

| symbol | (24,12,12) | (36,12,12) | (18,12,12) | (30,12,12) | Sharpe sign flip? |
|--------|-----------|-----------|-----------|-----------|-------------------|
| AAPL   | -0.3885   | +1.0575   | -0.0288   | +0.5345   | yes (-0.39 -> +1.06) |
| MSFT   | -0.4138   | -0.3358   | +0.4950   | +1.2195   | yes (-0.41 -> +1.22) |
| GOOGL  | -0.1162   | -0.1162   | -0.2120   | +0.0979   | yes (-0.21 -> +0.10) |

- **Every symbol flips sign** across protocols; the widely-quoted 24/12/12
  `NOT SUPPORTED` verdicts are therefore *protocol-conditional*, not properties
  of the signal alone.
- **Exactly 1 of 12 informative cells passes all three criteria**: MSFT at
  (30,12,12). The other 11 fail; the 24/12/12 baseline fails for all symbols.
- **The lone pass is noise-consistent:** the within-protocol DSR corrects for the
  3 lookback values only. A Bonferroni correction for the 4 protocols tried on
  MSFT pushes p from 0.0696 to 0.278 (> 0.10), and the other MSFT protocols fail.
- **6-month test windows are uninformative:** shorter than the 189/252-day
  lookbacks, so `periods_with_position <= 1` (flat). They must not be counted as
  a `NOT SUPPORTED` verdict.

Implication (also in validation_methods.md): neither `SUPPORTED` nor
`NOT SUPPORTED` is warranted from a single protocol on these fixtures; future
claims must pre-register protocols on held-out data and report the full matrix.

## What was actually verified

- New file standalone: `python3 .../test_walk_forward_time_series_momentum_protocol_sensitivity_real_triple.py` -> **5/5 passed**.
- Under pytest: `pytest <new file> -p no:cacheprovider -q` -> **5 passed in 19.4s**.
- Coexistence + baseline: `pytest test_walk_forward_time_series_momentum_real_{aapl,msft,googl}.py <new file>` -> **11 passed in 23.1s** (existing pinned AAPL 24/12/12 sharpe -0.3885 / dsr_p 0.9746 still reproduce).
- `python3 -m py_compile <new file>` -> OK.
- Diff is scoped: 1 untracked test file + +38 lines in validation_methods.md; working tree otherwise clean.

## What remains unresolved

- The **full 1559-test gate was NOT re-run** this session (~29 min). Expected new
  total ≈ 1564 (1559 + 5). The focused runs above are the only re-verification.
- No profitability/capacity claim; committed-fixture verdicts remain `NOT SUPPORTED`
  for the pinned protocol and protocol-dependent elsewhere.
- The framework still corrects multiplicity only **within** a protocol (grid
  combos). There is **no across-protocol multiplicity adjustment** in
  walk-forward/CPCV aggregate reporting (building blocks exist:
  `utils.benjamini_hochberg`, Bonferroni fallback in `performance.py`/`walk_forward.py`).

## Approaches already tried / failed

- None failed. One prototype protocol `(24,12,6)` was rejected by the framework
  (`step_months (6) must be >= test_months (12)`) — a deliberate guardrail, not a
  defect; the study uses only `step_months == test_months` protocols.
- Note: handoff candidate "purged K-fold" is already covered by CPCV
  (`cpcv_analysis` has `purge_size`/`embargo_size`, tested in `test_cpcv.py`);
  and "slippage/spread in capacity" is largely covered (slippage is already a
  per-trade cost; capacity `cost_drag` is borrow/funding by design). Don't repeat those.

## One precise next task

**Generalize the protocol-sensitivity study to cross-sectional momentum on the
committed AAPL/MSFT/GOOGL triple panel**, to test whether protocol-dependence is
TSMOM-specific or a general property of the evaluation methodology.

- Evidence: this session showed sign-flips + lone-pass-dies-under-multiplicity for
  TSMOM. `skills/quantitative-backtesting/tests/test_walk_forward_cross_sectional_momentum_real_triple_aapl_msft_googl.py`
  currently pins a **single** protocol; cross-sectional momentum is the
  next-most-tested family and the natural generalization test.
- Do: pre-register the same 4 informative 12-month protocols + fixed lookback grid
  / costs / criteria, run all (symbol×protocol) cells on the panel, pin the matrix,
  and assert whether the sign-flip / multiplicity-robustness pattern holds.
- Constraints: offline committed fixtures only; default JSON output bitwise
  identical; do NOT claim profitability; do not commit unless explicitly asked.
- Fallback if the above is too large: wire the existing `utils.benjamini_hochberg`
  / Bonferroni across the protocol family inside the new study to report a
  multiplicity-corrected pass count (today only within-protocol trials are
  corrected), with a unit test.

(End of file)
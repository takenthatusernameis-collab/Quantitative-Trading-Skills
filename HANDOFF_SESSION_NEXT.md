# Handoff — Next Task: make TSMOM protocol-sensitivity use the shared Bonferroni helper

## What changed this session (verified)
- Session-157 multiplicity task completed and committed in `2ce6b65`:
  - `bonferroni_correction` helper in `skills/quantitative-backtesting/scripts/utils.py`.
  - `tests/test_protocol_multiplicity.py` (10 tests) → 11 passed.
  - Cross-sectional protocol-sensitivity test refactored to call `bonferroni_correction(dsr_p_values, alpha=DSR_PVALUE_THRESHOLD)` (`test_walk_forward_cross_sectional_momentum_protocol_sensitivity_real_triple.py:286-292`).
- Full gate on current HEAD: **1580 passed, 0 failed, 0 errors** (~30:36), including the new multiplicity test file. Baseline established.

## What remains unresolved
- The TSMOM protocol-sensitivity test still computes the across-protocol correction inline (`float(p) * n_protocols` at `test_walk_forward_time_series_momentum_protocol_sensitivity_real_triple.py:291-295`), while the cross-sectional study uses the shared `bonferroni_correction` helper — an inconsistency; no single source of truth for the protocol-family FWER control across the two studies.

## One precise next task
Refactor `test_walk_forward_time_series_momentum_protocol_sensitivity_real_triple.py` (`test_sole_pass_does_not_survive_protocol_multiplicity`) to use the shared `bonferroni_correction` helper, mirroring the cross-sectional call pattern:
- `from utils import bonferroni_correction  # noqa: E402`
- Collect the DSR p-values across the 4 MSFT informative protocols into a family, call `bonferroni_correction(dsr_p_values, alpha=DSR_PVALUE_THRESHOLD)`, and assert the sole-pass cell's adjusted p-value > `DSR_PVALUE_THRESHOLD` with `n_rejected == 0`.

## Constraints
- Offline/committed fixtures only; default JSON output unchanged; do not commit unless explicitly asked.
- Decision/measurement-only: the pinned `EXPECTED` matrix must stay **bit-identical** and the honest finding (protocol-dependent sign flip, NOT SUPPORTED across the board) must be unchanged — `p * 4 = 2.3584` (uncapped) and Bonferroni-capped `1.0` both exceed `0.10`, so the assertion outcome is identical.
- Verify: `test_walk_forward_time_series_momentum_protocol_sensitivity_real_triple.py` (5/5) plus `tests/test_protocol_multiplicity.py` (11/11); a focused rerun is sufficient since the full 1580-test gate is already green on current HEAD.

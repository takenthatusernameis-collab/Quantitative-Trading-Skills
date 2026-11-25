# Handoff — Session: selected next task (capacity/liquidity sensitivity)

## What changed this session
- Reviewed HANDOFF_SESSION_NEXT.md; multiplicity infrastructure complete and regression-guarded.
- Selected bounded next task: **capacity/liquidity sensitivity analysis** (candidate 1 from prior handoff).

## One precise next task (bounded, evidence-based)
Implement a participation-rate / ADV-window sweep that reports the capacity frontier per strategy family, reusing the per-period cost-drag already surfaced in `walk_forward_summary.json`.

**Files to touch (start here):**
- `skills/quantitative-backtesting/scripts/walk_forward.py` (cost-drag measurement, `regime_impact_coefficients`)
- `skills/quantitative-backtesting/scripts/utils.py` (`protocol_family_correction` for multiplicity across families)
- `skills/quantitative-backtesting/tests/test_walk_forward.py` (existing patterns for pinned outputs)

**Constraints:**
- Cost-drag is a measurement, never charged to returns/P&L/Sharpe.
- Offline on committed fixtures only; no live network.
- Do not weaken try/except or CLI validation.
- Do not commit unless explicitly asked.
- Leave pinned EXPECTED matrices untouched; add additive companion tests.

## What remains unresolved
- Artifact-mutation test (`test_examples_coverage.py::test_scripts_results_untouched_after_examples`) still timestamp-sensitive on full-suite runs.
- Other 4 protocol-sensitivity summary files still inline Bonferroni (deferred).
- No profitability/capacity claim; committed-fixture verdicts remain NOT SUPPORTED.

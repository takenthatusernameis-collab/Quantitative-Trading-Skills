# Handoff — Session (current): fixed xdist test-isolation defect in 5 protocol-sensitivity summary files

## Status entering this session
- HEAD `e8c7f47` (main); working tree clean at start.
- Prior session's assigned task (wire a non-breaking Holm companion assertion into
  the three remaining triple protocol-sensitivity tests) was **already executed and
  committed** in `e8c7f47` (additive, +15/-1 each; pinned EXPECTED matrices untouched).
  Verified present: `holm_stepdown` imported and asserted in
  `test_walk_forward_{dual_momentum,sma_crossover,rsi_mean_reversion}_protocol_sensitivity_real_triple_aapl_msft_googl.py`.
- Environment: system `python3` 3.14.4 with pinned requirements (numpy 2.5.4,
  pandas 3.1.1, scipy 1.18.1, pytest 9.2.0). No venv needed.

## What changed this session (one bounded reliability fix)
The prior handoff chain's "wire Holm into more tests" tasks had reached diminishing
returns, so I ran the **full regression gate** to establish a real baseline. It was
**NOT green**: `1 failed, 1758 passed` under `-n 4`. Root cause was a genuine,
deterministic **test-isolation defect**, not a control-marker or flake:

- `test_no_asset_survives_cross_asset_multiplicity` read `per_asset_results` via
  `getattr(test_no_cell_survives_protocol_multiplicity, "per_asset_results", None)` —
  a function attribute set by a *different* test. Under pytest-xdist (`-n 4`, the
  canonical gate) the two tests land on different workers, and in a standalone run the
  producer never runs, so the attribute is `None` → `AssertionError: per-asset results
  not available`.
- Same anti-pattern in **5** files (sma_crossover, rsi_mean_reversion,
  time_series_momentum, zscore_mean_reversion, volatility_targeting `_summary.py`).

Fix (smallest reversible, uniform): in each cross-asset test, recompute the per-asset
results in-process by invoking the per-asset test, then read the attribute — removing
the order/worker dependency. No test added/removed (TEST_REGISTRY unchanged), no engine,
fixture, default-JSON, or pinned-matrix change. Diff: **5 files, +30/-6**, comments only
otherwise. A repo-wide scan confirms this was the **only** `getattr(test_...)` /
`test_x.attr =` handoff class in the suite (0 remaining after the fix).

## What was actually verified (evidence)
- Each cross-asset test **in isolation** (the previously-failing condition): 5/5 passed
  (~7-8s each).
- All 5 summary files together: **25 passed** (147.68s).
- **Full regression gate** `pytest tests/ -p no:cacheprovider -q -n 4`:
  **1759 passed, 0 failed** in 1710.17s (28m30s). This is the fresh green baseline and
  resolves the handoff chain's 1747-vs-1759 discrepancy — the real current count is
  **1759** (do not "fix" a 1747 target).
- `results/simple_momentum_hypothesis.json` is regenerated timestamp-only by the gate;
  restored with `git checkout --`. Final `git diff --stat` = 5 files, +30/-6.

## Current diff (uncommitted, per standing "no commit unless asked" rule)
- `M skills/quantitative-backtesting/tests/test_walk_forward_{sma_crossover,rsi_mean_reversion,time_series_momentum,zscore_mean_reversion,volatility_targeting}_protocol_sensitivity_real_triple_summary.py`

## What remains unresolved
- Nothing blocking. The 5-file fix is verified green but uncommitted (standing rule).
- The "wire Holm into every protocol test" line of work is low-value now (Holm already
  has multiple consumers); do not continue it for its own sake.
- Multiplicity correction is still applied ad hoc per summary file (two-level Bonferroni
  written inline in each); there is no single shared, tested aggregate helper.

## Approaches already tried / failed
- The prior "add a Holm companion assertion to the next test file" approach reached
  diminishing returns (each step adds a near-identical assertion). Switched to running
  the full gate, which surfaced the real isolation defect — a materially different,
  higher-value approach.
- No fix attempts failed; the isolation fix was green first try (isolated + full gate).

## One precise next task (bounded, evidence-based)
Consolidate the ad-hoc two-level multiplicity correction into one shared, tested helper
and adopt it as a **non-breaking companion** in a single summary file (mirror how
`bonferroni_correction` / `holm_stepdown` were introduced):

- Add `utils.protocol_family_correction(p_value_matrix, alpha=0.05)` (or similar) that
  takes an (assets × protocols) matrix of DSR p-values and returns the two-level
  (within-protocol per-asset, then cross-asset) FWER summary in one auditable structure.
  Same return-contract/NaN/clamping conventions as `bonferroni_correction`.
- Add `tests/test_protocol_family_correction.py` unit tests (single asset, single
  protocol, monotone, NaN/None, n=1, cross-asset reduction equals nested Bonferroni).
- Adopt it in **one** summary file (e.g. sma_crossover) as an *additional* assertion
  alongside the existing inline Bonferroni; keep every existing assertion and the pinned
  `EXPECTED` matrix byte-identical — only ADD.
- **Constraints**: offline/committed fixtures only; do not renumber metrics, change
  default JSON, or modify the engine; do not commit unless explicitly asked.
- **Verify**: run the new unit test + the adopted summary file + `test_holm_stepdown.py`
  focused; a full 1759-gate rerun is the correct final check before any commit.
- Cheaper alternative if a new helper is deprioritized: run the full gate once more under
  a different `-n` (e.g. `-n 8`) and with `--dist loadfile` to further confirm no residual
  order dependence, then commit the 5-file isolation fix.
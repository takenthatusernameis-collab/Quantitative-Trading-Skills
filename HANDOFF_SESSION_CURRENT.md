# Handoff — Session (current): TSMOM cross-asset two-level multiplicity summary

## Task executed (from HANDOFF_SESSION_NEXT.md)
Extended the **two-level (per-asset + cross-asset) protocol-sensitivity +
multiplicity framework** — established for volatility targeting in
`test_walk_forward_volatility_targeting_protocol_sensitivity_real_triple_summary.py`
— to **standalone time-series momentum (TSMOM)**, the foundational momentum
family. This closes TSMOM's cross-asset loop the same way the volatility-targeting
summary closes volatility targeting's.

## What changed (additive only)
- **One new untracked test file** (no existing test/fixture/engine modified):
  `skills/quantitative-backtesting/tests/test_walk_forward_time_series_momentum_protocol_sensitivity_real_triple_summary.py`
- Mirrors the volatility-targeting triple-summary exactly:
  - Signal `time_series_momentum` (long/flat), single asset, on AAPL/MSFT/GOOGL.
  - `LOOKBACK_GRID={"lookback":[126,189,252]}`, costs 2 bps comm + 1 bps slip,
    within-protocol Deflated Sharpe (3 lookbacks x n_periods), 4 informative
    12-month-test protocols `(24,12,12),(36,12,12),(18,12,12),(30,12,12)`.
  - Two-level Bonferroni: per-asset (4 protocols) then cross-asset (3 assets).
  - 5 registered tests + `main()` + `TEST_REGISTRY`:
    1. `protocol_sensitivity_matrix_pinned` — 12-cell (symbol x protocol) pin
    2. `nominal_criteria_report_honestly` — honest nominal pass reporting
    3. `no_cell_survives_protocol_multiplicity` — per-asset Bonferroni
    4. `no_asset_survives_cross_asset_multiplicity` — cross-asset Bonferroni
    5. `main_registers_every_module_level_test` — registry completeness

## Honest findings (real numbers, verified by run — not a profitability claim)
- **Nominal**: exactly 1 of 12 informative cells passes all three criteria —
  MSFT @ (30,12,12) (DSR p = 0.0696). The (24,12,12) baseline fails for all assets.
- **Per-asset Bonferroni (4 protocols)**:
  - AAPL: best p = 0.1021 @ (36,12,12) -> adj 0.4084, n_rejected = 0
  - MSFT: best p = 0.0696 @ (30,12,12) -> adj 0.2782, n_rejected = 0
  - GOOGL: best p = 0.5814 @ (30,12,12) -> adj 1.0, n_rejected = 0
- **Cross-asset Bonferroni (3 assets)**: best p = 0.0696 (MSFT) -> adj 0.2087, n_rejected = 0
- **Total n_rejected = 0. Overall verdict: NOT SUPPORTED.** TSMOM does not
  survive multiplicity anywhere on the committed triple panel; no
  protocol-selection or asset-selection bias can rescue the lone MSFT nominal pass.

## What was verified (with evidence)
- `python3 .../test_walk_forward_time_series_momentum_protocol_sensitivity_real_triple_summary.py`
  -> **5/5 PASS**, exit 0, real 0m40s (matrix pinned exactly; per-asset + cross-asset
  n_rejected = 0; registry complete). Pinned EXPECTED sourced from the committed
  TSMOM triple test and re-verified by this run.
- `python3 -m py_compile` on the new file -> COMPILE_OK (before and after docstring fix).
- Regression guard: existing
  `test_walk_forward_time_series_momentum_protocol_sensitivity_real_triple.py`
  -> **5/5 PASS** (baseline intact; the per-asset pins reproduce).
- `git status`: only the one new untracked file; `git diff --stat` empty. Not committed
  (no explicit request).

## Notes for next agent
- The two-level cross-asset multiplicity framework now covers **two** signal
  families on the committed triple panel: volatility targeting and TSMOM. Both
  overall **NOT SUPPORTED** after correction.
- Protocol-sensitivity + multiplicity coverage total is now fourteen
  signal-family/asset groupings (prior thirteen + TSMOM cross-asset summary).
- `pytest` is NOT available on this PATH; run test files directly with `python3`
  from repo root. The summary runs ~12 cells x 3 test bodies (~40s). Use >90s timeouts.
- TSMOM's 6-month short-window protocols are excluded from this summary (degenerate:
  periods_with_position <= 1; documented in the per-asset TSMOM study). Do not add them.

## Approaches already tried / failed
- None for this task. The volatility-targeting triple-summary pattern worked on
  the first attempt for TSMOM (mirroring the established template).

## One precise next task (bounded)
Extend the **two-level cross-asset multiplicity summary** to a third family that
has (or can cheaply get) per-asset protocol-sensitivity cells on the committed
panel. Best candidates, in order of low compute / high additivity:

1. **`dual_momentum`** or **`cross_sectional_momentum`** are *panel* strategies
   (one cell per protocol, not per asset) — a cross-asset summary is NOT natural
   for them; skip.
2. **`rsi_mean_reversion`** and **`sma_crossover`** already have per-asset-then-
   equal-weight *triple* protocol-sensitivity tests (per-asset cells pooled into
   one portfolio) but NO two-level cross-asset summary. Creating a cross-asset
   summary for one of these (mirroring this file, but building per-asset cells
   and pooling) would add the asset-selection multiplicity layer that is
   currently missing for them. Verify the existing triple test's per-asset
   construction first (RSI/SMA per-asset long/short or long/flat + equal weight).
   Candidate file name:
   `test_walk_forward_rsi_mean_reversion_protocol_sensitivity_real_triple_summary.py`
   (or sma_crossover).

If cross-asset summaries are judged redundant (two families already NOT
SUPPORTED after two-level correction), the higher-value alternative is a
**cross-family meta-analysis**: pool the per-family best nominal p-values from
all protocol-sensitivity studies (TSMOM, cross-sectional mom, dual mom, RSI,
SMA, zscore, volatility targeting) and apply the repo's family-wise
`utils.reality_check_test` / `utils.romano_wolfe_stepdown` (both already
implemented) to ask "does ANY family survive when ALL are tested together?"
This needs per-period return series per family; check whether the walk-forward
summary exposes `oos_returns` in a form that can be assembled (it does — each
`_run_cell` summary carries `oos_returns`). This would be the most decision-
relevant artifact but is a larger, multi-step task.

(End of file)
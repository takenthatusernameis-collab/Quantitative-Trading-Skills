# Handoff — Session (current): RSI mean-reversion cross-asset two-level multiplicity summary

## Task executed (from HANDOFF_SESSION_CURRENT.md / HANDOFF_SESSION_NEXT.md)
Extended the **two-level (per-asset + cross-asset) protocol-sensitivity +
multiplicity framework** — established for volatility targeting and standalone
time-series momentum (TSMOM) — to **standalone RSI mean reversion**, the
per-asset long/short mean-reversion family on the committed triple panel
(AAPL, MSFT, GOOGL). This closes RSI mean reversion's cross-asset loop and adds
the explicit asset-selection multiplicity layer that the pooled triple test
cannot isolate.

## What changed (additive only)
- **One new untracked test file** (no existing test/fixture/engine modified):
  `skills/quantitative-backtesting/tests/test_walk_forward_rsi_mean_reversion_protocol_sensitivity_real_triple_summary.py`
- Mirrors the TSMOM cross-asset summary exactly, but adapted to RSI's per-asset
  construction:
  - Signal `rsi_mean_reversion` (long/short/flat), single asset per cell, on
    AAPL/MSFT/GOOGL.
  - `PARAM_GRID={"period":[14],"oversold":[30],"overbought":[70],"neutral":[50]}`
    (1 config, shipped defaults), costs 2 bps comm + 1 bps slip, within-protocol
    Deflated Sharpe (1 config x n_periods), 4 informative 12-month-test protocols
    `(24,12,12),(36,12,12),(18,12,12),(30,12,12)`.
  - Two-level Bonferroni: per-asset (4 protocols) then cross-asset (3 assets).
  - 5 registered tests + `main()` + `TEST_REGISTRY`:
    1. `protocol_sensitivity_matrix_pinned` — 12-cell (symbol x protocol) pin
    2. `nominal_criteria_report_honestly` — honest nominal pass reporting
    3. `no_cell_survives_protocol_multiplicity` — per-asset Bonferroni
    4. `no_asset_survives_cross_asset_multiplicity` — cross-asset Bonferroni
    5. `main_registers_every_module_level_test` — registry completeness

### Design note (why per-asset independent cells, not the pooled portfolio)
The existing triple test
(`test_walk_forward_rsi_mean_reversion_protocol_sensitivity_real_triple_aapl_msft_googl.py`)
runs each asset independently then **pools** per-asset OOS returns into one
equal-weight portfolio, computing one DSR per protocol with `n_trials = 3
assets x n_periods`. Pooling folds the asset-selection decision *into* the DSR's
trial count. This summary instead treats each asset as a **separate hypothesis**
with its own per-asset DSR and applies an explicit two-level Bonferroni, so the
asset-selection correction is separately auditable from the protocol
correction. Both reach NOT SUPPORTED; this summary is the one that isolates the
asset-selection layer. (The pooled-vs-per-asset distinction is documented in the
module docstring.)

## Honest findings (real numbers, verified by run — not a profitability claim)
- **Nominal**: zero of 12 informative cells pass all three criteria. Best nominal
  cell is **GOOGL @ (36,12,12)** (DSR p = 0.1726), which still exceeds 0.10; the
  raw OOS Sharpe (+0.9892) and total return (+0.5195) are positive there but do
  not survive deflation.
- **Per-asset Bonferroni (4 protocols)**:
  - AAPL: best p = 0.5335 @ (30,12,12) -> adj 1.0000, n_rejected = 0
  - MSFT: best p = 0.2090 @ (24,12,12) -> adj 0.8361, n_rejected = 0
  - GOOGL: best p = 0.1726 @ (36,12,12) -> adj 0.6902, n_rejected = 0
- **Cross-asset Bonferroni (3 assets)**: best p = 0.1726 (GOOGL) -> adj 0.5177, n_rejected = 0
- **Total n_rejected = 0. Overall verdict: NOT SUPPORTED.** RSI mean reversion
  does not survive multiplicity anywhere on the committed triple panel.

## What was verified (with evidence)
- `python3 .../test_walk_forward_rsi_mean_reversion_protocol_sensitivity_real_triple_summary.py`
  -> **5/5 PASS**, exit 0. Pinned EXPECTED sourced from a per-asset probe and
  re-verified by the run (12-cell matrix pins exactly; per-asset + cross-asset
  n_rejected = 0; registry complete). Runtime ~40s.
- `python3 -m py_compile` on the new file -> COMPILE_OK.
- Regression guard: existing
  `test_walk_forward_rsi_mean_reversion_protocol_sensitivity_real_triple_aapl_msft_googl.py`
  -> **4/4 PASS** (pooled baseline intact; per-asset cell construction reproduces).
- Regression guard: TSMOM template
  `test_walk_forward_time_series_momentum_protocol_sensitivity_real_triple_summary.py`
  -> **5/5 PASS** (shared framework intact).
- `git status`: only the one new untracked file; `git diff --stat` empty. Not
  committed (no explicit request). Prior session's files are already tracked in
  HEAD `677452f`.

## Notes for next agent
- The two-level cross-asset multiplicity framework now covers **three** signal
  families on the committed triple panel: volatility targeting, TSMOM, and RSI
  mean reversion. All overall **NOT SUPPORTED** after correction.
- Protocol-sensitivity + multiplicity coverage total is now fifteen
  signal-family/asset groupings (prior fourteen + RSI cross-asset summary).
- `pytest` is NOT available on this PATH; run test files directly with `python3`
  from repo root. Use >90s timeouts per file (cross-asset runs 12 cells).
- Each per-asset RSI DSR uses `n_trials = 1 config x n_periods` (1 config, so
  n_trials == n_periods per cell). Do not "fix" this to 3 assets — that is the
  whole point of the explicit cross-asset Bonferroni layer.

## Approaches already tried / failed
- None for this task. The TSMOM summary pattern worked on the first attempt for
  RSI (mirroring the established template, adapting to per-asset DSR).

## One precise next task (bounded)
Create the **SMA crossover cross-asset summary**, mirroring the file just added:

`skills/quantitative-backtesting/tests/test_walk_forward_sma_crossover_protocol_sensitivity_real_triple_summary.py`

Evidence / constraints (verified this session):
- The per-asset-then-equal-weight triple test already exists:
  `test_walk_forward_sma_crossover_protocol_sensitivity_real_triple_aapl_msft_googl.py`.
  It uses `PARAM_GRID = {"fast_period": [20], "slow_period": [50]}` (1 config,
  long-only trend), `build_strategy("sma_crossover", ...)`, same 4 informative
  protocols `(24,12,12),(36,12,12),(18,12,12),(30,12,12)`, costs 2 bps + 1 bps.
  Its pooled best nominal cell is (36,12,12) (DSR p = 0.1582).
- Copy the RSI summary file and adapt: change `_factory` to `"sma_crossover"`,
  set `PARAM_GRID={"fast_period":[20],"slow_period":[50]}`, drop the
  oversold/overbought/neutral keys, and re-probe per-asset numbers with
  `apply_deflation=True` before pinning `EXPECTED` / `BEST_NOMINAL_PROTOCOL` /
  `EXPECTED_NOMINAL_PASS` (likely zero nominal passes; report honestly, do not
  force a verdict).
- Run probe -> pin -> re-run to confirm 5/5 PASS; run the existing SMA triple
  test as a regression guard. Additive only; do NOT modify existing files; do
  NOT commit unless explicitly asked.

If SMA cross-asset summaries are judged redundant (three families already NOT
SUPPORTED), the higher-value alternative is the **cross-family meta-analysis**
described in the prior handoff: pool the per-family best nominal p-values from
all protocol-sensitivity studies (TSMOM, RSI, SMA, zscore, volatility targeting,
cross-sectional/dual momentum) and apply the repo's family-wise
`utils.reality_check_test` / `utils.romano_wolfe_stepdown` (both implemented) to
ask "does ANY family survive when ALL are tested together?" Each `_run_cell`
summary carries `oos_returns`, so per-family per-period return series can be
assembled. This is the most decision-relevant artifact but is a larger,
multi-step task.

(End of file)
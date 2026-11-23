# Handoff — Next Task: Protocol-sensitivity + multiplicity control for volatility targeting on the committed triple panel (cross-asset summary), or a new methodological study

## Status (entering this task)
- HEAD `d6215b2`; working tree has two untracked additive files:
  - `skills/quantitative-backtesting/tests/test_walk_forward_volatility_targeting_protocol_sensitivity_real_msft.py` (4/4 PASS via `python3`)
  - `skills/quantitative-backtesting/tests/test_walk_forward_volatility_targeting_protocol_sensitivity_real_googl.py` (4/4 PASS via `python3`)
  - Neither committed (per instructions).
- Volatility targeting protocol-sensitivity + multiplicity control now covers AAPL, MSFT, GOOGL single-asset — all overall NOT SUPPORTED after Bonferroni across 5 protocols.
  - AAPL best nominal p=0.4792 @ (30,12,12) → Bonferroni 1.0.
  - MSFT best nominal p=0.3918 @ (30,12,12) → Bonferroni 1.0.
  - GOOGL best nominal p=0.2782 @ (36,12,12) → Bonferroni 1.0.
- Protocol-sensitivity + multiplicity control covers thirteen signal-family/asset cells, all NOT SUPPORTED after protocol correction.
- `pytest` is NOT available (`python3 -m pytest` → "No module named pytest"); run test files directly with `python3`.

## One precise next task (one bounded item)
Write a **cross-asset protocol-sensitivity summary** for volatility targeting across the committed triple panel (AAPL, MSFT, GOOGL), mirroring the existing per-asset test files' methodology but aggregating the three assets into one reproducible summary artifact.

Why: three parallel per-asset studies now exist; a single summary that re-derives the three best-nominal DSR p-values and applies a **two-level multiplicity correction** (per-asset 5-protocol Bonferroni, plus a cross-asset correction across the 3 assets) would honestly report whether volatility targeting survives multiplicity anywhere on the committed panel. This is the natural next methodological step and closes the loop on the cross-asset robustness question the last two sessions opened.

Steps:
1. Read the three existing files for the exact convention:
   - `skills/quantitative-backtesting/tests/test_walk_forward_volatility_targeting_protocol_sensitivity_real_{aapl,msft,googl}.py`
   - Reuse `walk_forward_analysis`, `strategy_builder.build_strategy("volatility_targeting", ...)`, `utils.bonferroni_correction`.
2. Create one new additive file, e.g. `test_walk_forward_volatility_targeting_protocol_sensitivity_real_triple_summary.py`:
   - SYMBOLS = ["AAPL", "MSFT", "GOOGL"]; same PARAM_GRID, same 5 protocols, same costs, `apply_deflation=True, validate_pit=True`.
   - For each asset, run all 5 protocols, apply per-asset Bonferroni across the 5 protocols (FWER within asset).
   - Then apply a **second** Bonferroni across the 3 assets on the per-asset best nominal p-value (family-wise across assets).
   - Report per-asset best nominal p, per-asset Bonferroni-adjusted p, cross-asset Bonferroni-adjusted p, and total n_rejected at alpha=0.10.
   - Pin the observed numbers in EXPECTED after a probe run; do NOT hard-code guessed values.
   - Four `test_*` functions + `TEST_REGISTRY` + `main()` returning 0, mirroring the per-asset tests.
3. Run with `python3` to capture real numbers (probe), pin them, re-run to confirm PASS. Record the honest overall verdict (expected NOT SUPPORTED).
4. Run one existing per-asset file (e.g. AAPL) as a regression guard.

## Constraints / environment reminders
- Offline, committed fixtures only; no live network. Additive only — do NOT modify existing tests/fixtures/engine. Do NOT commit unless explicitly asked.
- Run each file with `python3 <file>` from repo root; use generous timeouts (>90s per file; the triple summary runs 15 cells so budget several minutes).
- `pytest` unavailable; direct `python3` execution is the verified convention.
- Do NOT force a predetermined verdict. If any asset/cell passes nominally but not after correction, report that honestly.

## Approaches already tried / failed
- None for this task.
- Note: a previous handoff claimed the AAPL protocol file was untracked; it is in fact committed in `d6215b2`. Verify git state with `git status` before assuming untracked files.

(End of file)
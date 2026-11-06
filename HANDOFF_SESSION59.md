# Handoff — Session 59: survivorship-bias positive control added

## What changed
- Added `skills/quantitative-backtesting/tests/test_survivorship_bias_positive_control_real_panel.py` (untracked, not committed; user did not request commit). This is the positive control for the survivorship-bias audit assigned in HANDOFF_SESSION58.md, complementing the negative control in `test_multi_symbol_pit_survivorship_real_panel.py`.
- The panel is deterministically corrupted from the committed AAPL/MSFT/GOOGL (2010-2019) fixtures: AAPL truncated at the start (first 63 bars dropped → simulates late entry/IPO), MSFT truncated at the end (last 63 bars dropped → simulates delisting/exit). Run via `run_backtest.py --multi-symbol --strategy cross_sectional_momentum --validate-point-in-time` (non-strict; focus is survivorship). Methodology audit, not a profitability claim.
  - `test_survivorship_bias_positive_control_on_real_data_derived_panel` asserts: sole survivor == GOOGL, AAPL reported in `entered_symbols`, MSFT in `exited_symbols`, `insufficient_data`/`large_gaps` empty, `bias_score > 0`, `data_provenance.json` has all 3 symbols with checksums, `tear_sheet_summary.json` has `bias_controls_engaged == True` and `survivorship_bias` matching the persisted `survivorship_bias.json`.
- No existing files modified.

## What was actually verified
- New test: `python3 -m pytest skills/quantitative-backtesting/tests/test_survivorship_bias_positive_control_real_panel.py -p no:cacheprovider -v` → **1 passed in 2.25s** (offline, committed fixtures only, CLI subprocess, temp outputs).
- Targeted regression (survivorship/multi-symbol/data_loader/run_backtest): `python3 -m pytest skills/quantitative-backtesting/tests/test_survivorship_bias_positive_control_real_panel.py skills/quantitative-backtesting/tests/test_multi_symbol_pit_survivorship_real_panel.py skills/quantitative-backtesting/tests/test_run_backtest.py skills/quantitative-backtesting/tests/test_data_loader.py -k "survivorship or multi_symbol" -p no:cacheprovider -q` → **12 passed, 136 deselected in 6.49s**.
- `python3 -py_compile` on the new file → OK.
- Verified the injected biases are detectable at both the detector level (`detect_survivorship_bias` directly) and end-to-end through the CLI + artifact persistence before writing the test, so the pinned expectations are reproducible (bias_score == 2/3, entered=AAPL, exited=MSFT, survivor=GOOGL).

## What remains unresolved
- The new test file is **untracked/not committed**.
- Full-suite gate was last run in Session 57/58 (1092 passed, EXIT 0). The new test is additive/independent (CLI subprocess, temp outputs, ~2.3s) with no shared-state impact; a full gate re-run was not repeated this session because the additive scope is small and the focused regression above is green.
- `AAPL.csv.bak` stray gitignored duplicate remains on disk (prior handoff).
- Slow-test runtime (~38 min full gate) is inherent (evidence-based, per prior handoffs); do not weaken.

## Approaches already tried / failed
- None failed. The positive control was straightforward: the detector already distinguishes entered/exited/surviving, and the truncation values (63 bars ≈ 3 months) exceed the default `max_gap_days=30` tolerance, so detection is unambiguous.

## One precise next task
No pending assigned quant task. Highest-value remaining bounded item: add a **survivorship-bias positive control for the "insufficient data" and "large gaps" branches** on a real-data-derived panel — e.g. truncate one symbol to fewer than the default `min_observations=252` (insufficient) and/or splice a synthetic gap into another symbol's history, then assert `detect_survivorship_bias` (via `run_backtest.py --multi-symbol`) reports it in `insufficient_data`/`large_gaps` with `bias_score > 0` and artifact persistence. Reuse the conventions in the new `test_survivorship_bias_positive_control_real_panel.py`. Verify with the focused test plus the `-k survivorship` subset. Do not commit unless explicitly asked.

(End of file - total 44 lines)
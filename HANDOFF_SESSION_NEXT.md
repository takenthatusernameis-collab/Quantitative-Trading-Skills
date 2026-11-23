# Handoff — Next Task: Cross-asset protocol-sensitivity + multiplicity for another signal family on the committed triple panel

## Status (entering this task)
- HEAD `d6215b2`; working tree has one untracked additive file:
  - `skills/quantitative-backtesting/tests/test_walk_forward_volatility_targeting_protocol_sensitivity_real_triple_summary.py` (5/5 PASS via `python3`)
- Volatility targeting cross-asset summary complete: two-level Bonferroni (per-asset 5-protocol, cross-asset 3-asset) applied; all n_rejected = 0; overall NOT SUPPORTED.
- Protocol-sensitivity + multiplicity control now covers thirteen signal-family/asset cells, all NOT SUPPORTED after correction.
- `pytest` is NOT available (`python3 -m pytest` → "No module named pytest"); run test files directly with `python3`.

## One precise next task (one bounded item)
Extend the **cross-asset protocol-sensitivity + multiplicity framework** to another signal family that has (or can get) per-asset coverage on the committed panel (AAPL, MSFT, GOOGL).

Steps:
1. Identify a signal family with existing per-asset protocol-sensitivity tests for all three assets, OR one where creating them is straightforward (mirroring the volatility targeting pattern).
2. If per-asset tests don't exist: create three per-asset protocol-sensitivity tests (AAPL, MSFT, GOOGL) for that signal family, using the same 5-protocol family, PARAM_GRID, costs, and falsification criteria.
3. Create a cross-asset summary test (mirroring `test_walk_forward_volatility_targeting_protocol_sensitivity_real_triple_summary.py`) that applies the two-level Bonferroni.
4. Run probe → pin EXPECTED → re-run to confirm PASS.
5. Run regression guards on the per-asset tests.

Candidate signal families to check (look for existing `*_protocol_sensitivity_real_{aapl,msft,googl}.py` files):
- `time_series_momentum`
- `cross_sectional_momentum`
- `dual_momentum`
- `rsi_mean_reversion`
- `zscore_mean_reversion`
- `sma_crossover`

## Constraints / environment reminders
- Offline, committed fixtures only; no live network. Additive only — do NOT modify existing tests/fixtures/engine. Do NOT commit unless explicitly asked.
- Run each file with `python3 <file>` from repo root; use generous timeouts (>90s per file; cross-asset runs 15 cells so budget several minutes).
- `pytest` unavailable; direct `python3` execution is the verified convention.
- Do NOT force a predetermined verdict. If any asset/cell passes nominally but not after correction, report that honestly.
- Follow the exact conventions established in the volatility targeting per-asset and cross-asset tests.

## Approaches already tried / failed
- None for this task.

(End of file)
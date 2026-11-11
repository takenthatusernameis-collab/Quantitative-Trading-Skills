# Handoff — Session 81: Regime-aware cost models in Monte Carlo path

## What changed
- **`skills/quantitative-backtesting/scripts/walk_forward.py`**: Fixed `run_monte_carlo()` to parse and pass `regime_impact_coefficients` to `_calculate_strategy_returns()` in both the single-run path and all 6 sweep paths (impact_coefficient, borrow_cost, funding_cost, latency/fill_rate, commission, slippage). The fix mirrors the existing behavior in `run_walk_forward()`.
- **`skills/quantitative-backtesting/tests/test_monte_carlo.py`**: Added two new tests:
  1. `test_monte_carlo_regime_impact_coefficients_parsing` — verifies `_parse_regime_impact_coefficients()` handles valid JSON, None, empty dict, integer-to-float conversion, invalid JSON, and non-numeric values.
  2. `test_monte_carlo_walk_forward_regime_impact_passes_through` — structural test confirming the Monte Carlo path now parses and passes the regime coefficients dict (previously the sweep paths passed the raw JSON string and the single-run path omitted it entirely).

## What was actually verified
- **All existing tests pass**: 26/26 Monte Carlo tests, 111/111 run_backtest tests, 8/8 execution_warmup tests, 2/2 regime robustness tests.
- **End-to-end behavior verified**: `_calculate_strategy_returns()` produces different results when `regime_impact_coefficients` is provided vs. omitted (empirical diff ≈ 0.045 on synthetic data with two regimes and 10× impact coefficient difference).
- **Parsing correctness**: `_parse_regime_impact_coefficients()` correctly handles all edge cases and is now called in `run_monte_carlo()` exactly as in `run_walk_forward()`.
- **All 7 call sites of `_monte_carlo_sweep_coefficient()`** now receive the parsed `regime_impact_coefficients` dict (previously 6 passed the raw string, 1 omitted it).
- **Single-run Monte Carlo path** now passes `regime_impact_coefficients` to `_calculate_strategy_returns()` (previously omitted).

## What remains unresolved
- No full quant gate run (environmentally blocked at ~60+ min serial). Chunked execution remains green.
- The regime detection itself (`detect_combined_regime`) is exercised by existing tests; this change only wires the CLI argument through to the cost model.

## Approaches already tried / failed (do not repeat unchanged)
- Do not pass the raw JSON string (`args.regime_impact_coefficients`) to sweep helpers — they expect a parsed `Dict[str, float]`.
- Do not omit `regime_impact_coefficients` from the single-run path — it must be passed for parity with `run_walk_forward()` and `run_backtest.py`.

## One precise next task
The regime-aware cost model gap for Monte Carlo is closed. Per the repository's quantitative-research objective, select the next **bounded methodological gap** from the documented candidates:
1. **Capacity/liquidity-aware position sizing** — `estimate_capacity` and `_window_book_capacity` exist as *measurement* tools but do not feed back into position sizing. Bounded task: add an opt-in `--max-impact` / capacity-aware position cap that scales the target position so estimated market impact stays below a threshold, with offline committed-fixture tests.
2. **Multiple-testing / data-mining controls beyond deflated alpha** — Bonferroni and block-bootstrap are implemented; a concrete gap is a **false-discovery-rate (Benjamini-Hochberg) control** across the registered strategy family, or a **combination-test / reality-check** (White's Reality Check / Romano-Wolf) over the full hypothesis family, reported in the walk-forward summary.

Relevant files: `skills/quantitative-backtesting/scripts/utils.py` (`estimate_capacity`, `book_capacity_estimate`), `skills/quantitative-backtesting/scripts/walk_forward.py`, `skills/quantitative-backtesting/tests/`. Constraint: offline/committed fixtures only; no live network; do not commit unless explicitly asked; keep the working tree clean.

(End of file - total 48 lines)
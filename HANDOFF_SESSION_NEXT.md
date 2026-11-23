# Handoff — Next Task: Regime-robustness on the committed triple panel (AAPL+MSFT+GOOGL)

## Status
- Regime-robustness SMA crossover analysis complete and verified for AAPL, MSFT, and GOOGL (all NOT SUPPORTED, 1 of 3 regimes won, sideways only).
- New test files are untracked; do not commit unless asked.
- Reusable module: `skills/quantitative-backtesting/scripts/regime_robustness.py:run_regime_robustness_analysis` (single-asset; call with `data_path=<csv>`, `label=<SYM>`).
- Fixtures: `skills/quantitative-backtesting/assets/example_data/real_market_data/{AAPL,MSFT,GOOGL}.csv`.
- AAPL/MSFT/GOOGL test pattern: `test_regime_robustness_sma_crossover_real_{aapl,msft,googl}.py`.
- No pytest available; run tests with `python3 <test_file>`.

## Next precise task (one bounded item)
Extend regime-robustness to the committed triple panel to confirm the NOT SUPPORTED verdict is not asset-specific:
- Add a panel runner (or per-asset aggregation) in `scripts/regime_robustness.py` (or a new script) that runs `run_regime_robustness_analysis` on AAPL+MSFT+GOOGL with the same pre-registered config and reports aggregate `n_regimes_won` across assets (expected: 1 of 3 per asset = NOT SUPPORTED for all three).
- Add a test `test_regime_robustness_sma_crossover_real_triple_aapl_msft_googl.py` mirroring the single-asset tests (run/structure, verdict NOT SUPPORTED pinned per asset, pinned Sharpe regression guards using the measured values above, PIT regime-label test per asset).
- Constraints: offline/committed fixtures only; default JSON output unchanged; point-in-time regime labels; realistic costs per cost_models.md; do not commit unless asked; no profitability claim.

## Measured values to pin (regression guards)
- MSFT: verdict NOT SUPPORTED, n_won=1/n_eval=3. bear strat -1.483717083197383 / bench -0.0048539210571094706; bull 0.6470929496470363 / 1.0539297073529; sideways 0.603684412831922 / 0.5927710661803279.
- GOOGL: verdict NOT SUPPORTED, n_won=1/n_eval=3. bear -0.4006175291370394 / -0.13438963976919285; bull 1.346657372150235 / 1.5549832709110525; sideways 2.0742415489313983 / 1.801497876702869.
- AAPL (existing): verdict NOT SUPPORTED, n_won=1/n_eval=3. bear -0.23627517020820568 / 1.451629801394141; bull 0.12058921157124423 / 0.4534496163975293; sideways 3.3251793689417615 / 0.10278059166467346.

## Approaches that failed / considerations
- None for this session. Fold-level (walk-forward) stratification was previously considered and deferred in favor of per-bar fixed-parameter returns; revisit only if required.

## Evidence & constraints for the next agent
- Measured per-asset Sharpe values listed above; use relative tolerance (1e-3), never exact equality; verdict pinned NOT SUPPORTED to enforce "do not tune to force SUPPORT".

(End of file)

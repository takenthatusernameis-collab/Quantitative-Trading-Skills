# Handoff — Next Task: Regime-robustness parameter-sensitivity grid on the triple panel

## Status
- Regime-robustness SMA crossover complete & verified for AAPL, MSFT, GOOGL (single + triple panel) and cost sensitivity (frictionless/advertised/elevated/high). All 5 test files pass; NOT SUPPORTED at every cost level, including zero cost.
- Reusable module: `skills/quantitative-backtesting/scripts/regime_robustness.py:run_regime_robustness_triple_panel(data_dir=SRC, fast_period=..., slow_period=..., commission=..., slippage=...)` and `run_regime_robustness_analysis(data_path, label, fast_period, slow_period, ...)`.
- Fixtures: `skills/quantitative-backtesting/assets/example_data/real_market_data/{AAPL,MSFT,GOOGL}.csv`.
- Advertised pre-registered config: fast=20 / slow=50, commission 2bp, slippage 1bp, 200-day MA regime, >=2 of 3 regimes to be SUPPORTED. All three assets NOT SUPPORTED (win 1 of 3, sideways only).
- No pytest available; run tests with `python3 <test_file>`. Offline/committed fixtures only; no live network.

## Next precise task (one bounded item)
Add a parameter-sensitivity regression test proving the NOT SUPPORTED verdict is robust to nearby SMA fast/slow periods (data-mining control): if the verdict only holds at exactly fast=20/slow=50, the result is an artifact of parameter choice; if it holds across a small grid, the falsification is stronger.

- New test: `skills/quantitative-backtesting/tests/test_regime_robustness_param_sensitivity_real_triple_aapl_msft_googl.py`, mirroring the cost-sensitivity test structure (contextlib.redirect_stdout, run per combo, `__main__` runner printing OK).
- Grid (fast_period, slow_period), fast < slow, advertised costs (2bp/1bp):
  (10,40), (10,50), (10,60), (20,50) [pre-registered], (20,60), (30,60).
- For each combo run `run_regime_robustness_triple_panel` on the triple panel and assert:
  * panel_verdict == "NOT SUPPORTED";
  * each asset verdict == "NOT SUPPORTED";
  * each asset n_regimes_won < min_regimes_won_per_asset (i.e., <= 1, since >=2 per asset required for SUPPORTED);
  * total_regimes_evaluated == 9; structure keys stable.
- Pin measured per-asset/per-regime strategy Sharpe + benchmark Sharpe at each combo with relative tolerance 1e-3 (real measured values — compute them first by running the analysis; do not invent numbers).
- Benchmark Sharpe is cost- and parameter-invariant (buy-and-hold raw returns); strategy Sharpe varies with the grid.
- Constraints: offline/committed fixtures only; default JSON output unchanged; point-in-time regime labels; realistic costs per cost_models.md; do not commit unless asked; no profitability claim; verdict pinned NOT SUPPORTED to enforce "do not tune to force SUPPORT."

## Evidence & constraints for the next agent
- Measured advertised-level values (already pinned in triple test): MSFT bear -1.483717083197383 / bench -0.0048539210571094706; bull 0.6470929496470363 / 1.0539297073529; sideways 0.603684412831922 / 0.5927710661803279. GOOGL bear -0.4006175291370394 / -0.13438963976919285; bull 1.346657372150235 / 1.5549832709110525; sideways 2.0742415489313983 / 1.801497876702869. AAPL bear -0.23627517020820568 / 1.451629801394141; bull 0.12058921157124423 / 0.4534496163975293; sideways 3.3251793689417615 / 0.10278059166467346.
- Use relative tolerance (1e-3), never exact equality.
- If any grid combo flips an asset to SUPPORTED, that is a genuine methodological finding to report honestly (parameter-specific support), not something to suppress — document it as the blocker/result rather than tuning to force NOT SUPPORTED.

## Approaches already tried / failed
- None for this task.

(End of file)

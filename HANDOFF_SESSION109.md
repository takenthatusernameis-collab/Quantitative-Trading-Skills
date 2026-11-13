# Handoff — Session 109: HMM-based Regime Detection with Point-in-Time Guarantees

## What changed

Added **Hidden Markov Model (HMM) regime detection** to `skills/quantitative-backtesting/scripts/regime_detection.py` with full point-in-time / no-look-ahead guarantees:

### New Core Components

1. **`HMMConfig` dataclass** — Configuration for HMM regime detection:
   - `n_states`: Number of hidden states (default 3: bear/sideways/bull)
   - `n_iter`, `tol`: EM algorithm convergence parameters
   - `covariance_type`: "diag" (default, stable) or "full"
   - `refit_window`: Optional periodic refitting for walk-forward simulation
   - `train_frac`: Training fraction for initial fit
   - Feature toggles: `use_returns`, `use_volatility`, `use_trend`

2. **`GaussianHMM` class** — Full Baum-Welch EM implementation:
   - `fit(X)`: EM algorithm with forward-backward E-step and M-step
   - `filter(X)`: **Forward filtering** for point-in-time inference — computes P(state_t | obs_1...obs_t) using only historical data
   - `predict(X)`: Viterbi decoding (NOT point-in-time, for reference only)
   - `score(X)`: Log-likelihood computation

3. **`build_hmm_features(close, config)`** — Causal feature construction:
   - Returns (pct_change)
   - Rolling volatility (expanding std of returns)
   - Trend (MA diff)
   - All features computed causally with no look-ahead

4. **`fit_hmm_walkforward(close, config)`** — Walk-forward HMM fitting:
   - Single fit mode (`refit_window=None`): fit on training data, filter full series
   - Periodic refit mode: refit every N bars, simulating real-time model updates
   - Returns `HMMResult` with regimes, state probabilities, model params, diagnostics

5. **High-level API functions**:
   - `detect_hmm_regime(close, config)` → regime labels Series
   - `detect_hmm_regime_with_probs(close, config)` → (labels, state_probs DataFrame)
   - `add_hmm_regime_analysis_to_results(results, data, config)` — integrates with backtest results

### Point-in-Time Guarantees

- **Forward filtering** (`GaussianHMM.filter`) computes P(state_t | obs_1...obs_t) — only historical data used
- **Walk-forward refitting** only uses data available up to each refit point
- **Feature construction** is fully causal (rolling/expanding windows only)
- **State-to-label mapping** is post-hoc (based on state mean returns) and explicitly documented as not point-in-time stable

## What was actually verified

All tests pass (Python 3.14.4, numpy 2.5.4, pandas 3.1.1, scipy 1.18.1):

### Unit Tests (`test_regime_detection.py` — 42 tests)
- `TestHMMConfig`: default and custom configuration
- `TestBuildHMMFeatures`: feature construction (returns only, returns+vol, all features, error on no features)
- `TestGaussianHMM`: fit/predict, forward filter, score, determinism
- `TestHMMRegimeDetection`: basic detection, with probabilities, single-fit walkforward, refit walkforward, index matching
- `TestAddHMMRegimeAnalysisToResults`: integration with backtest results, panel data, error handling

### Point-in-Time Falsification Tests (`test_regime_detection_point_in_time.py` — 11 tests)
- Original MA/volatility regime tests (6 tests) — still pass
- **New HMM point-in-time tests (5 tests)**:
  - `test_hmm_filter_point_in_time`: Forward filter probabilities unchanged when future observations mutated
  - `test_detect_hmm_regime_no_lookahead`: Filtered probabilities stable in single-fit mode
  - `test_fit_hmm_walkforward_no_lookahead`: Filtered probabilities stable in refit mode
  - `test_hmm_feature_construction_causal`: Features unchanged when future prices mutated
  - `test_hmm_deterministic`: Identical inputs produce identical outputs

### Related Tests (all pass)
- `test_regime_concentration_diagnostic.py` (9 tests)
- `test_real_market_data_provenance.py` (5 tests)
- `test_walk_forward_records_regime_robustness.py` (2 tests)
- `test_monte_carlo_records_regime_robustness.py` (1 test)
- `test_cpcv_records_regime_analysis.py` (1 test)

**Total: 71 regime-related tests pass**

## What remains unresolved

- **Latent bug in `trading_costs_robustness_example.py`** (from Session 108): `run_commission_slippage_sweeps` formats `None` values with `%` format specifier — only triggers with very short synthetic series (N_PERIODS≈320). Not related to HMM work.
- **CI workflow (`quant-regression-gate`)** remains blocked on GitHub App permissions (cannot push `.github/workflows/*` without `workflows` permission).
- **Full serial `pytest tests/`** still times out (~60+ min); continue using chunked/targeted batches.

## Approaches already tried / failed (do not repeat unchanged)

- Attempting to test **regime labels** for point-in-time stability: Labels are assigned post-hoc based on state mean returns, which change when the model is refit. The correct invariant is **filtered probabilities** (verified in tests).
- Adding sklearn/hmmlearn as dependency: **Deliberately avoided** — implemented GaussianHMM from scratch using only numpy/scipy to keep dependency footprint minimal.

## One precise next task

**Extend the HMM regime detection with a worked example demonstrating its use in a falsifiable hypothesis test.**

The HMM infrastructure is now complete and tested. A high-value next step would be to create an example (e.g., `examples/hmm_regime_hypothesis.py`) that:
1. Uses HMM regime detection on real market data (AAPL, GOOGL, MSFT from `assets/example_data/real_market_data/`)
2. Defines a falsifiable hypothesis (e.g., "Strategy X has positive Sharpe in HMM-identified bull regimes")
3. Runs walk-forward or CPCV validation with regime-dependent performance reporting
4. Includes explicit rejection criteria and test resolution reporting

This would demonstrate the HMM capability end-to-end and add to the library of worked examples for quantitative methodology research.

Alternative next tasks (if preferred):
- Add regime-dependent transaction cost modeling (e.g., higher impact in HMM high-vol regimes)
- Implement regime-aware position sizing (volatility targeting per HMM regime)
- Add HMM regime detection to the CLI (`run_backtest.py --regime-detector hmm`)
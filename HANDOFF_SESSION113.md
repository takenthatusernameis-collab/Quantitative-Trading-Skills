# Handoff — Session 113: Frequency-aware realized-volatility annualization in regime detection

## What changed (uncommitted; working tree has 2 modified files)

**`skills/quantitative-backtesting/scripts/regime_detection.py`** — fixed the same
defect class that commit `e866c04` fixed for `compute_regime_performance`: hardcoded
`sqrt(252)` volatility annualization. Two functions still annualized realized
volatility at 252 regardless of the return frequency:

1. **`detect_volatility_regime`** (`regime_detection.py:137`): `rolling_vol =
   returns.rolling(window).std() * np.sqrt(252)` → now infers
   `periods_per_year` from the close index via `utils._annualization_factor`
   (252 business-daily, 365 calendar-daily, 52 weekly, 12 monthly, …), falling
   back to 252 for a non-DatetimeIndex / un-inferable frequency. Verified
   impact: on weekly bars the reported annualized vol was overstated ~2.2x
   (sqrt(252/52)); e.g. true 0.162 vs reported 0.354 on a test series.

2. **`build_hmm_features`** (`regime_detection.py:~552`): the rolling-volatility
   HMM feature used the same hardcoded `sqrt(252)`; now uses the same inferred
   factor.

**Key correctness nuance (empirically verified):** the volatility *regime
classification* is **invariant** to this constant per-feature scale — both the
rolling-vol series and its expanding-quantile thresholds scale together, and the
Gaussian-emission EM (means/covariances re-estimated from data) is
location/scale-invariant, so regime labels are unchanged. What was wrong is the
reported **magnitude**: the annualized-vol level (in `detect_volatility_regime`'s
internal series and in the HMM `means`/`covars` model params surfaced by
`fit_hmm_walkforward`). The fix corrects the level without changing labels, and
matches the framework's established convention used elsewhere
(`performance.py`, `monte_carlo.py`, `walk_forward.py`, and the now-fixed
`compute_regime_performance`).

**`skills/quantitative-backtesting/tests/test_regime_detection.py`** — two new
regression tests:
- `TestVolatilityRegimeDetection::test_annualized_vol_uses_frequency_aware_factor`
  — pins that weekly data annualizes at 52 (not 252) and daily at 252, and that
  the sqrt(252) series is materially different on the weekly tail.
- `TestBuildHMMFeatures::test_volatility_feature_uses_frequency_aware_factor` —
  pins that the weekly volatility feature equals `std * sqrt(52)` (modulo the
  leading-NaN backfill), not `std * sqrt(252)`.

## What was actually verified (evidence)

- `tests/test_regime_detection.py` → **45 passed** (was 43; +2 new tests).
- Regression sweep on downstream consumers:
  - `tests/test_regime_aware_position_sizing.py` → **12 passed**
  - `tests/test_run_backtest.py` → **121 passed** (32s; only expected
    `UserWarning`s, no failures)
  - `tests/test_monte_carlo.py` → **26 passed**
  - `tests/test_walk_forward.py -k "regime or annualiz"` → **4 passed**
  - `tests/test_walk_forward_records_regime_robustness.py`,
    `test_monte_carlo_records_regime_robustness.py`,
    `test_regime_concentration_diagnostic.py` → **12 passed**
  - `tests/test_reporting.py` → **67 passed**
- Label-invariance empirically confirmed: monkeypatch comparison of HMM labels
  with sqrt(252) vs sqrt(52) gave **label agreement 1.0** on a regime-switching
  weekly series; `detect_volatility_regime` old-vs-new label agreement **1.0**.
- `git status --porcelain` shows exactly the two intended files; no drift, no new
  artifacts.

## What remains unresolved

- **Not committed.** Per the standing "do not commit unless explicitly asked" rule.
- Full single-invocation quant gate
  (`python3 -m pytest skills/quantitative-backtesting/tests/ -p no:cacheprovider -q -n 4`)
  exceeds the in-session 120s tool budget. Last documented full-gate state
  (`HANDOFF_FULL_GATE_RESULT.md`): **1196 passed, 1 failed** (the
  artifact-mutation test, now resolved per `HANDOFF.md`); that predates pandas
  3.1.1, so re-run in CI / adequate budget to confirm 100% green.
- `pytest-xdist` (`-n 4`) installed but not pinned in `requirements.txt`.
- CI workflow `quant-regression-gate` remains blocked on the GitHub App
  `workflows` permission. Do not retry without new access.

## Approaches already tried / failed (do not repeat unchanged)

- Treating `detect_volatility_regime`/`build_hmm_features`'s hardcoded 252 as
  label-changing and rewriting detection logic: rejected. The classification is
  scale-invariant; the defect is the reported magnitude only. Editing detection
  to chase label changes would be the anti-pattern the mission forbids.
- Serial full gate in-session: times out (120s tool cap); use chunked batches or CI.
- `test_walk_forward.py` in one shot: exceeds 120s; use `-k` filters or a CI budget.

## One precise next task (for the next agent)

Re-run the focused gate chunk to confirm the fix is green in the committed-tree
context, then select the next bounded methodological gap:

```bash
cd skills/quantitative-backtesting && PYTHONPATH=scripts python3 -m pytest \
  tests/test_regime_detection.py tests/test_regime_aware_position_sizing.py \
  tests/test_run_backtest.py tests/test_monte_carlo.py tests/test_reporting.py \
  -q -p no:cacheprovider
```

If green, the obvious next methodological targets (in priority order):

1. **`regime_aware_position_size` default `periods_per_year=252`** (`regime_detection.py:1131`)
   is still a hardcoded default. Unlike the two functions fixed here, it is
   explicitly parameterized and documented, but a caller passing weekly `close`
   with the default gets a ~2.2x under-sized position (verified: multiplier
   0.45x of correct). Consider defaulting to `None` and inferring from the
   `close` index, mirroring `compute_regime_performance`'s `Optional[float] =
   None` pattern, with a pinned test. This is the same defect class, one
   function over, and is the highest-value remaining instance because it sizes
   real positions.
2. Run the full gate in CI / adequate-budget env; `git checkout -- .` afterward
   to restore any timestamp-only drift in `results/`/`test_output/` artifacts.

Do not commit unless explicitly asked. Keep the working tree clean.

(End of file)
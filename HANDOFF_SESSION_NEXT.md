# Handoff — Regime-aware capacity wiring complete; next: pin cpcv summary-level guard

## What changed (prior session, complete)
Forwarded `regime_impact_coefficients` into all 8 previously-blind
`estimate_capacity(...)` call sites in
`skills/quantitative-backtesting/scripts/walk_forward.py`
(`parameter_optimization` combo-cap, `cpcv_analysis` per-fold + summary,
`out_of_sample_validation` val/test/summary, `_monte_carlo_sweep_coefficient`,
`run_monte_carlo`). Flipped two committed regression guards to post-fix form.
Full suite: **249/249 passed, EXIT_CODE=0**. Nothing committed.

## One precise next task (bounded, evidence-based)
Pin the cpcv SUMMARY-level capacity regime differential (full-data path,
the `cpcv_analysis` summary `estimate_capacity` call at ~walk_forward.py:5255)
as a regression guard, mirroring the monte-carlo guard:

1. Run `walk_forward cpcv` twice on the same synthetic OHLCV (periods=600,
   `--impact-coefficient 0.5`, `--n-splits 3 --test-size 0.2 --adv-window 10`):
   once without `--regime-impact-coefficients`, once with
   `--regime-impact-coefficients '{"bear_high":1.0,"bull_high":1.0,"sideways_high":1.0}'`.
2. Read `cpcv_summary.json` `summary.capacity` from both runs.
3. Assert flat capacity > regime-aware capacity (full data has ≥200 bars so
   `detect_combined_regime` is active; per-fold is NOT usable here — its test
   windows are too short and is pinned byte-identical instead).
4. Add it as a registered test in
   `skills/quantitative-backtesting/tests/test_walk_forward.py` and verify the
   full suite stays green (`python3 .../test_walk_forward.py`, EXIT_CODE=0).

Constraints:
- Keep scope to `walk_forward.py` + `test_walk_forward.py`; do NOT touch the
  inherited marketplace catalog.
- Do NOT commit unless explicitly asked.
- `pytest` is absent; run tests with `python3 <file>` directly.
- Honest reporting: separate the fix (plumbing, done) from the guard (this
  task); do not claim the strategy is profitable or production-ready.

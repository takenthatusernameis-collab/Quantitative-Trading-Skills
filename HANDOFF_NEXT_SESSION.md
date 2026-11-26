# Task for Next Agent

## What changed (this session)
- Executed the prior handoff (`HANDOFF_NEXT_SESSION.md`): regression coverage of the
  remaining single-asset walk-forward family test files, run directly with `python3`.
- **No code, engine, fixture, or default-JSON changes.** Verification-only session.
- Working tree stays clean apart from this handoff doc.

## What was actually verified (evidence)
All run from repo root with `python3 <file>` (offline, committed fixtures only).
Every file printed `OK` and exited 0.

Named targets from the prior handoff:
- `test_walk_forward_sma_crossover_real_aapl.py` — OK, exit 0
- `test_walk_forward_time_series_momentum_real_aapl.py` — OK, exit 0
- `test_walk_forward_zscore_real_aapl_msft.py` — OK, exit 0

Additional single-asset walk-forward files covered this cycle (loop, per-file `timeout 300`):
- `test_walk_forward_bollinger_real_aapl.py` — OK, exit 0
- `test_walk_forward_donchian_real_aapl.py` — OK, exit 0
- `test_walk_forward_ema_crossover_real_aapl.py` — OK, exit 0
- `test_walk_forward_kelly_criterion_real_aapl.py` — OK, exit 0
- `test_walk_forward_macd_real_aapl.py` — OK, exit 0
- `test_walk_forward_rsi_real_aapl.py` — OK, exit 0
- `test_walk_forward_rsi_mean_reversion_real_aapl.py` — OK, exit 0
- `test_walk_forward_simple_momentum_real_aapl.py` — OK, exit 0
- `test_walk_forward_volatility_targeting_real_aapl.py` — OK, exit 0
- `test_walk_forward_zscore_mean_reversion_real_aapl.py` — OK, exit 0
- `test_walk_forward_time_series_momentum_real_googl.py` — OK, exit 0
- `test_walk_forward_time_series_momentum_real_msft.py` — OK, exit 0

Total: 15 single-asset walk-forward files, all pass. No regressions from accumulated
additive tests. Verdicts remain NOT SUPPORTED where applicable — each file's internal
`assert all(passes.values()) is False` (and the specific
`deflated_sharpe_pvalue_lt_0.10 is False` / `oos_sharpe_gt_zero` /
`oos_total_return_positive` assertions) held, since the files printed OK.
`git status --short` shows only this handoff doc; HEAD unchanged (1deba4b).

## What remains unresolved
- `pytest` not on PATH; direct `python3 <file>` convention still required.
- Pair/triple and `protocol_sensitivity` walk-forward files were NOT re-run this cycle
  (targeted single-asset scope per handoff). They remain covered by prior sessions.
- Not committed (no explicit request).

## Approaches already tried / failed
- None this session. (Prior sessions proved the "hang" was expected runtime, not a defect;
  `pytest-timeout` is absent so an ini `timeout=` is inert — see tests/README.md.)

## One precise next task (bounded, evidence-based, high-value)
Move from "verdict is NOT SUPPORTED" to "is that a real absence of edge or an underpowered
test?" Produce a consolidated, reproducible **statistical-power assessment** of the
single-asset walk-forward family's NOT SUPPORTED verdicts.

Concretely:
1. For each of the 15 single-asset files above, capture from the walk-forward summary the
   observed OOS effect (pooled OOS Sharpe / mean excess return) and the reported
   `summary["test_resolution"]` (minimum detectable effect). `test_resolution` is
   implemented in `skills/quantitative-backtesting/scripts/walk_forward.py:3086`
   (`_build_test_resolution`) and attached to the summary; a dedicated helper exists at
   `skills/quantitative-backtesting/scripts/measure_resolution_vs_sample_size.py`.
2. Classify each NOT SUPPORTED verdict as (a) genuinely near-zero/negative OOS edge, or
   (b) underpowered (test_resolution exceeds the observed effect, so the held-out sample
   could not have detected the effect at all).
3. Deliverable: a short markdown artifact (e.g.
   `results/single_asset_power_assessment.md`) summarizing the table + conclusion, plus a
   small reproducible script if it aids regeneration.

Constraints: offline / committed fixtures only; do NOT tune strategies to force SUPPORTED;
do NOT weaken assertions or skip tests; keep engine/fixtures/default-JSON unchanged; do not
commit unless explicitly asked. This directly serves the mission's "statistical uncertainty
and honest reporting" goal and tells us whether the persistent NOT SUPPORTED results are a
power problem or a real edge problem.
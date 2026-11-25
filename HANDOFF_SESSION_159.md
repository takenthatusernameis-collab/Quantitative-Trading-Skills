# Handoff — Session 159: real-data participation-rate capacity cap sweep (triple panel)

## Assigned task (from HANDOFF_FULL_GATE_RESULT.md, the latest handoff)

The full quant gate was green (1782 tests, 0 failures). Its "one precise next
task" listed candidate methodological gaps on the committed AAPL/MSFT/GOOGL
triple panel, including **capacity/liquidity sensitivity** and noting the
"participation-rate leg is covered at unit level but not swept on the triple
panel." This session executed that bounded gap.

## What changed

- **New test file (uncommitted, untracked):**
  `skills/quantitative-backtesting/tests/test_walk_forward_capacity_participation_rate_sweep_real_triple_aapl_msft_googl.py`
- No engine, fixture, default-JSON, pinned-matrix, or existing-test change.
  The new test only *reads* committed fixtures and calls the existing
  `walk_forward.estimate_capacity` / `_dict_to_multiindex`.

## What the test verifies (evidence-based, real committed data)

Sweeps `max_participation_rate` over `(0.0001, 0.0002, 0.0005, 0.001, 0.005,
0.01, 0.05)` at fixed `impact_coefficient=0.5`, `max_impact=0.0005`,
`adv_window=20` on the real AAPL/MSFT/GOOGL panel:
- `participation_capacity == n_assets * rate * binding_adv_notional` (panel
  least-liquid-binds rule; binding asset = GOOGL here).
- `estimated_capacity == min(impact_capacity, participation_capacity)` (zero
  cost drag).
- Capacity is non-decreasing as the cap loosens.
- Real crossover: cap **binds** at the tightest rate (0.0001, cap≈2.92e6 ==
  participation limit) and is **slack** at the loosest (0.05, cap≈2.92e7 ==
  impact-based baseline 29,218,557); slack cap leaves baseline unchanged.
- Impact disabled (`coefficient=0`) ⇒ `unconstrained=True`, capacity None,
  participation ignored.

## What was actually verified

- `pytest tests/test_walk_forward_capacity_participation_rate_sweep_real_triple_aapl_msft_googl.py`
  — **2 passed** (0.57s); standalone `python3 <file>` prints `OK`.
- Regression neighbors serially: `test_run_backtest.py` +
  `test_walk_forward_time_series_momentum_capacity_sensitivity_real_triple_aapl_msft_googl.py`
  + `test_walk_forward_time_series_momentum_oos_min_capacity_vs_deployed_capital_real_triple_aapl_msft_googl.py`
  — **133 passed** (39.16s; warnings are pre-existing quantile warnings).
- Working tree: only the one untracked test file; no timestamp drift (full gate
  NOT re-run this session).

## What remains unresolved

- The new test is **uncommitted** (standing "no commit unless asked" rule).
- `max_participation_rate` is still not wired into any walk-forward *return*
  path or aggregate report — it remains a capacity-estimate-side control only
  (by design; returns derive leverage dynamically). No profitability/capacity
  claim; all committed-fixture verdicts remain NOT SUPPORTED.
- Full 1782-gate not re-run after this additive test (baseline was green as of
  the prior session; this change adds a test file only, no source edit).

## Approaches already tried / failed

- None failed. Chose a direct `estimate_capacity` sweep on a real MultiIndex
  panel (via `_dict_to_multiindex`) rather than adding another example-module
  helper, to keep the change to a single new test file with no production edit.

## One precise next task (bounded, evidence-based)

Commit the new test file (only if the user asks), then re-run the full gate
serially per-file to confirm the baseline is still green with the added test
(expected 1784 collected):
`cd skills/quantitative-backtesting && python3 -m pytest tests/ -p no:cacheprovider -q` (run per-file with timeouts; the monolithic `-n 4` xdist run deadlocks).

Alternative bounded methodological next step tied to real files: extend the
participation-rate cap to the **square-root impact model** on the same real
triple panel (current sweep uses the default linear model only) — add a
`impact_model="sqrt"` companion assertion in the same new test file, verifying
the cap still binds/slack-crossover and `participation_capacity` is unchanged
by the impact model (it is model-independent). Constraints: offline/committed
fixtures only; no engine/default-JSON/pinned-matrix change; restore any
timestamp-only artifact drift post-run; do not commit unless explicitly asked.
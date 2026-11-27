# Handoff — Cost-capacity reporting fixed & funded; AAPL cost-realism guard added

## What changed (this session)
- One new file: `test_root_simple_momentum_cost_real_aapl.py` (repo root).
  Mirrors the existing committed GOOGL (`test_root_simple_momentum_cost_real_googl.py`)
  and MSFT (`test_root_simple_momentum_cost_real_msft.py`) root cost-realism guards,
  filling the asymmetry: AAPL had a headline real test (`test_root_simple_momentum_real_aapl.py`)
  but NO advertised-cost regression guard on the committed AAPL fixture.
  - `test_root_cost_path_applies_advertised_costs_on_real_aapl`: runs
    `simple_motionum_hypothesis._run_backtest_metrics` at frictionless (0 bps) vs
    advertised (2bp comm + 1bp slip) on committed `real_market_data/AAPL.csv`;
    asserts costed Sharpe < frictionless Sharpe, costed return < frictionless
    return, and capacity identical across cost settings (capacity is impact-driven,
    not cost-driven). Pinned metrics with rel tol 1e-3.
  - `test_root_cost_path_metrics_pinned_on_real_aapl_window`: pins the two
    runs' sharpe_ratio/total_return/capacity.
  - Offline, committed fixtures only, no network.

## Prior committed work (baseline, already verified)
- `skills/quantitative-backtesting/scripts/walk_forward.py:3987` —
  `result["cost_drag"]` set to the EFFECTIVE (post-cap) drag so the published
  `cost_drag` is self-consistent with `cost_adjusted_capacity`
  (`cost_adjusted_capacity == impact_capacity / (1 + cost_drag * holding_period_years)`).
  Default runs byte-identical (cap block falls through).
- `skills/quantitative-backtesting/tests/test_walk_forward.py` — added
  `test_cli_out_of_sample_max_cost_cap_reflected_in_csv` (borrow leg) and
  `test_cli_out_of_sample_max_funding_cost_cap_reflected_in_csv` (funding leg,
  commit a25a628), both registered in TEST_REGISTRY.

## What was actually verified (evidence)
- New AAPL guard: `python3 test_root_simple_momentum_cost_real_aapl.py` → 2/2 PASS.
  Measured on AAPL.csv: frictionless Sharpe 0.16389499548305048 / return 0.04080578748526298 /
  capacity 58073701.96943283; costed Sharpe 0.1495367916686615 / return 0.037679766982581464 /
  capacity 58073701.96943283 (identical). Costs applied (costed < frictionless).
- Full root cost-realism set: AAPL + GOOGL + MSFT → 6/6 PASS.
- Funding-cap CLI test `test_cli_out_of_sample_max_funding_cost_cap_reflected_in_csv` → PASS
  (part of the earlier committed suite; borrow-cap + registry-integrity tests also PASS).

## What remains unresolved
- DATA PROVENANCE (pre-existing, blocked offline): `real_market_data/MSFT.csv` is
  byte-identical to `sample_benchmark.csv`; `AAPL.csv == sample_ohlcv.csv`;
  `GOOGL.csv == AAPL.csv.bak`. Committed fixtures are placeholders/synthetic, so
  these guards are regression guards on committed data, NOT evidence about real
  securities. Restoring authentic data needs network (unavailable offline) — do
  NOT fabricate. See PROVENANCE.json and HANDOFF_SESSION_164.md.

## Approaches that already failed (do not repeat)
- `background_process` sweep: repo not visible in its namespace — abandoned;
  use foreground timed batches. (Prior sessions.)

## One precise next task (bounded, evidence-based)
Fix the mutually-exclusive borrow/funding cost caps in `estimate_capacity()`
(`skills/quantitative-backtesting/scripts/walk_forward.py:3967-3985`). The engine
uses `if/elif`, so when BOTH `--max-borrow-cost` and `--max-funding-cost` are set
and both legs are positive (leveraged short), only the borrow cap is applied and
the funding cap is silently ignored. cost_drag should be
`min(borrow_drag, max_borrow) + min(funding_drag, max_funding)` so both caps bind
independently.

Steps:
1. Add regression test `test_cli_out_of_sample_max_borrow_and_funding_caps_both_apply`
   in test_walk_forward.py (register in TEST_REGISTRY): drive the FUNDING+borrow
   case — e.g. macd `--leverage 1.5 --funding-cost 0.10 --short-exposure 0.2
   --borrow-cost 0.10 --max-borrow-cost 0.01 --max-funding-cost 0.01` — and assert
   CSV `cost_drag == 0.02` (= 0.01 + 0.01) and
   `cost_adjusted_capacity == impact_capacity / (1 + 0.02 * holding_period_years)`.
   Confirm it FAILS on current elif code (demonstrates the defect), then PASSes
   after the fix.
2. Fix `estimate_capacity`: replace `elif` with independent `if` blocks so both
   legs are capped; `cost_drag = effective_borrow + effective_funding`; recompute
   `_drag_denominator = 1 + cost_drag * holding_period_years`.
3. Constraints: default runs (no caps) byte-identical; single-cap runs (borrow-only,
   funding-only) unchanged (existing borrow & funding tests must still pass);
   only the both-caps case changes; committed fixtures only, no network; do NOT
   touch the dynamic per-position borrow/funding cost charging in returns.
4. Verify: run the borrow-cap, funding-cap, and new both-caps tests together;
   expect 3/3. Do NOT commit unless explicitly asked.

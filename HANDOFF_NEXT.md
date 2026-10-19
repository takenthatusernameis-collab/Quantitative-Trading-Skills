# HANDOFF

## What changed this session

Executed the prior handoff's next task — **unify the two panel backtest conventions so multi-asset results are comparable across CLIs** — and verified the unification with before/after measurements and regression tests.

### 1. One shared market model (`scripts/utils.py`, new)

Two new shared helpers now define, in one place, how a single asset, a MultiIndex panel and a dict panel are priced:

- `build_market_model(data)` — normalizes the three input shapes into one representation and returns `raw_returns`, `close`, `volume`, `price` (a representative price series for trade ledgers) and `is_panel`.
  - **Panel return convention (now unified): the mean of the per-asset returns**, `close.pct_change().mean(axis=1)`. The return of the mean price series (`close.mean(axis=1).pct_change()`) is deliberately **not** used: it prices a price-weighted basket whose weights drift with the constituents' relative moves — a rebalancing rule the position model does not represent — while the mean-of-returns convention is the equal-weighted basket the impact and capacity models assume.
  - For a dict panel the per-asset volume frame is only built when **every** constituent carries a volume column, so the impact model never mixes a per-asset ADV with a portfolio-level notional.
- `market_impact_cost(...)` — the linear impact model `(position_notional / ADV_notional) * coefficient`, with the panel rule: a position change of `|d|` trades `|d| * equity / n_assets` in each constituent, each constituent is measured against **its own** ADV, and the portfolio cost is the equal-weighted mean of the per-asset impacts.

Both `run_backtest.py` and `walk_forward.py` now call these helpers, so the two entry points cannot drift apart again.

### 2. `run_backtest.py` aligned to the shared model

- The panel branch no longer builds a mean-price series for returns and no longer charges the whole portfolio notional against an aggregated pseudo-asset (mean close × mean volume) ADV. Panel impact was overstated by roughly `n_assets` there; it now uses the shared per-asset model.
- The trade ledger is priced on the market model's representative `price` series (close for a single asset, the equal-weighted mean of the per-asset closes for a panel) — the same values the ledger used before, now sourced from the shared model.
- The panel **capacity** estimate now passes a per-constituent frame to `estimate_capacity`, so the least-liquid constituent binds the portfolio capacity exactly as in the walk-forward paths. Previously the panel was collapsed into a pseudo-asset, which made the two CLIs report different capacities for the same panel.
- Removed the now-unused `import numpy as np`.

### 3. `walk_forward.py` refactored onto the shared helpers (bit-for-bit unchanged)

`_calculate_strategy_returns` now calls `build_market_model` / `market_impact_cost` instead of its own inline copies. **Its numerical output is unchanged**, verified against a pre-change snapshot over 24 configurations (single asset / MultiIndex panel / dict panel × impact coefficient ∈ {0, 0.5} × latency ∈ {0, 2} × fill_rate ∈ {1.0, 0.5}): all 24 cases identical to the last bit, same index, same dtype.

### 4. Documentation

- `references/cost_models.md`: the old "Cross-path note" (which described the divergence as open work) is replaced by a **Cross-path parity** section — a table of the three shared models, the reason for the mean-of-returns convention, the parity guarantee, and an explicit description of the one remaining difference (the position warmup, below). The panel-impact "Regression history" now also records the `run_backtest.py` pseudo-asset variant, and the capacity section states that the single-backtest path uses the same least-liquid-binds rule.
- `SKILL.md`: added the `utils.py` script entry, described the shared panel convention on the `run_backtest.py` entry, and listed the five new regression tests.

## What was actually verified

Test suite (all green; baseline in parentheses):

| Suite | Result |
| --- | --- |
| `test_run_backtest.py` | 73/73 (68) |
| `test_walk_forward.py` | 153/153 (153) |
| `test_cpcv.py` | 20/20 (20) |
| `test_reporting.py` | 56/56, `OK` (56) |
| `test_data_loader.py` | 32/32 (32) |
| `test_examples_coverage.py` | 6/6 (6) |
| `test_falsifiable_hypothesis_example.py` | 3/3 (3) |
| `test_generate_sample_data.py` | 2/2 (2) |
| `test_monte_carlo.py` | 20/20 (20) |
| `test_performance.py` | 33/33 (33) |
| `test_strategy_builder.py` | 28/28 (28) |

New regression tests (all registered in `TEST_REGISTRY` in `tests/test_run_backtest.py`):

- `test_run_backtest_panel_matches_walk_forward_return_calculator` — the same panel, strategy and costs produce **identical return values** through `run_backtest.py` and through `walk_forward.py`'s return calculator (MultiIndex panel; impact 0.0 and 0.5).
- `test_run_backtest_dict_panel_matches_walk_forward_return_calculator` — same parity for the dict panel format.
- `test_run_backtest_panel_uses_mean_of_per_asset_returns` — pins the return convention (and asserts it is *not* the mean-price return).
- `test_run_backtest_panel_impact_splits_notional_across_assets` — the panel impact drag is the per-asset model, not the whole-notional-against-one-ADV model.
- `test_run_backtest_panel_capacity_binds_on_least_liquid_constituent` — the panel capacity equals `estimate_capacity` on the same panel and equals `n_assets * max_impact * min_i(ADV_notional_i) / coefficient`.

Before/after evidence for the cross-path divergence (identical 5-asset, 504-bar panel, `cross_sectional_momentum`; produced by running the identical probe against the stashed baseline and against the current tree):

```
--- BEFORE (original code) ---
impact=0.0: run_backtest n=503 first=2020-01-02 ann_mean=0.1573 ann_vol=0.0225 total=0.3673
            walk_forward n=502 first=2020-01-03 ann_mean=0.1405 ann_vol=0.0216 total=0.3224
            max |diff| on common index = 1.728e-03   corr = 0.947716
impact=0.5: identical numbers (the pseudo-asset impact drag was too small to show at 4 dp)
--- AFTER (current code) ---
impact=0.0: run_backtest n=503 first=2020-01-02 ann_mean=0.1405 ann_vol=0.0216 total=0.3224
            walk_forward n=502 first=2020-01-03 ann_mean=0.1405 ann_vol=0.0216 total=0.3224
            max |diff| on common index = 0.000e+00   corr = 1.000000
impact=0.5: same (max |diff| = 0.000e+00)
```

CLI-level capacity parity on the same 5-asset panel (`--impact-coefficient 0.5`):

```
BEFORE: run_backtest panel capacity = 1620616.8717802505   (pseudo-asset)
        walk_forward cpcv capacity   = 3513695.2387903403   (per-asset)   -> 2.17x disagreement
AFTER:  run_backtest panel capacity = 3513695.2387903403
        walk_forward cpcv capacity   = 3513695.2387903403                  -> parity
```

Other verifications:

- `walk_forward._calculate_strategy_returns` is **bit-for-bit identical** to the pre-change baseline over 24 configurations (snapshot taken before the refactor, compared after).
- `examples/falsifiable_hypothesis_example.py` stdout is **byte-identical** to the pre-change baseline (`diff` clean); verdict still **NOT SUPPORTED** (pre-existing: the hypothesis is falsified by its own criteria, not a regression).
- `examples/trading_costs_robustness_example.py` stdout is byte-identical apart from its random temp-directory path.
- All six examples in `examples/` run to completion (exit 0).
- CLI panel CPCV smoke test: `run_backtest.py --multi-symbol` and `walk_forward.py cpcv --multi-symbol` on the same panel CSV now report the same aggregate capacity and the same fold-level results (identical before and after this change).
- `test_import.py` and `verify_end_to_end.py` at the repo root still pass.
- The `examples/example_output/data_provenance.json` timestamp-only churn produced by the example runs was reverted.
- `git diff --stat`: 6 files, ~591 insertions / ~144 deletions, plus this handoff pair.

## What remains unresolved

- **One cross-path difference remains: the position warmup.** It is a *position* convention, not a market-model convention, and it applies to single assets too. `run_backtest.py` fills the undefined first position with `0`, so the position is opened on the first executable bar and the **entry cost is charged**; `walk_forward.py` propagates it as `NaN`, so the first bar of the window is **dropped** from the evaluation and the entry cost is never charged. `run_backtest.py` therefore reports exactly one extra leading bar. This was left unchanged on purpose: changing it would alter the single-asset path and every published walk-forward / CPCV / out-of-sample number. It is now documented in `references/cost_models.md` ("Cross-path parity") and asserted by the parity tests.
- **Panel impact still uses net exposure, not book weights.** The panel strategy API exposes `(n_long - n_short) / n_assets`, not the per-asset weights of the book, so the impact cost is computed on an equal-weight book that the actual long/short composition does not match. A strategy whose gross exposure exceeds `|net exposure|` has a modelled impact cost that is, if anything, too low. Documented as a known limitation.
- **The panel trade ledger is an approximation.** For a panel it prices entries and exits on the mean price of the constituents, because the panel strategy API does not expose per-asset entries. The ledger's per-trade P&L therefore does not reconcile exactly with the panel equity curve (which is marked on the equal-weighted basket). Now documented in `references/cost_models.md`.
- **Capacity is a point-in-time reading, not a trend.** The estimator uses the *last* ADV in each window, so per-regime capacity shows the liquidity available at the end of a window; a capacity *degradation trend* (e.g. minimum or median ADV over the window) is not derived.
- **A "no position was ever taken" run still reports `total_oos_return: 0.0`** in the CPCV / walk-forward summary JSON (see the next task).

## Approaches already failed / why

- The first attempt at unifying the panel impact in `run_backtest.py` was to reuse the old pseudo-asset shape; it is not equivalent to the per-asset model and was rejected in favour of sharing `market_impact_cost` verbatim.
- Making the two paths *fully* identical (same index set, not just the same values) would have required changing `walk_forward.py`'s `NaN` position warmup to a `fillna(0)` warmup. That changes the **single-asset** path and every published walk-forward / CPCV / out-of-sample number, which the prior handoff's constraints forbid; it was therefore not attempted. The residual one-bar difference is documented and asserted instead.
- `git stash`-based before/after comparisons were run three times (falsifiable-hypothesis example, trading-costs example, CPCV panel CLI) to prove the unchanged behaviour; all diffs were as expected.

## Next task (precise, bounded, evidence-based)

**Make "the strategy never took a position" distinguishable from "the strategy made no money" in the CPCV / walk-forward summaries.**

- Problem (measured, see below): when no parameter configuration produces an active signal in a fold's test window, the fold is silently skipped and the summary reports `total_oos_return: 0.0` — indistinguishable from a strategy that traded and lost everything. A downstream reader (or a JSON consumer) would read "0.0% OOS return" as "no edge" when the truth is "no position was ever taken".
- Measured evidence: a 5-asset panel, `cross_sectional_momentum`, CPCV with 4 folds, `--param-grid '{"lookback": [15, 20, 30]}'` (the **default** `top_quantile = bottom_quantile = 0.2`) selects **0 of 4** folds and reports `total_oos_return: 0.0`, `avg_param_stability: 0.0`, `overfitting_risk: "high"`. The CLI text does print `OOS Sharpe Ratio: N/A` and the strategy emits a `UserWarning` about the flat signal (the warning is in stderr), but the JSON summary still says `total_oos_return: 0.0`. With asymmetric quantiles (`top_quantile 0.4 / bottom_quantile 0.2`) the same run selects 4/4 folds and reports `total_oos_return: 0.00048668575163635097`. This behaviour is **identical before and after this session's change** (verified with the stashed baseline), i.e. it is pre-existing, not a regression.
- Work items:
  1. In `walk_forward.py`, report `total_oos_return` as `None` (not `0.0`) when no fold produced an out-of-sample return, and add an explicit count of folds that actually produced a position (e.g. `folds_with_position`) to the CPCV and walk-forward summaries. The relevant code is `walk_forward.py:1684` (walk-forward) and `walk_forward.py:2159` (CPCV): `float((1 + oos_returns).prod() - 1) if len(oos_returns) > 0 else 0.0`.
  2. Check the consumers before changing the type: `walk_forward.py:2890`, `:3222` and the sweep writers at `:3310`, `:3416` coerce the value with `float(summary.get("total_oos_return", 0.0))` and format it with `:.2%` / `:.4f` — these must tolerate `None` (render `N/A`) instead of raising or silently printing `0.0000`.
  3. Apply the same treatment to `out_of_sample_validation` if it has the same pattern, and make the CPCV/walk-forward tear-sheet rows show the new count.
  4. Add regression tests: a CPCV run in which every parameter set is skipped must report `total_oos_return is None` (not `0.0`) and `folds_with_position == 0`; a normal run must keep the current numbers.
- Constraints: do not change the strategy's signal generation or the `_validate_quantiles` warning (they are correct); do not change the numbers of runs that *do* select parameters; keep the JSON keys backward compatible where possible (add keys rather than rename).
- Acceptance evidence: the failing case reports `None` / `0` instead of `0.0`; a healthy run's summary is byte-identical to its pre-change value; the full suite stays green; `references/validation_methods.md` and `SKILL.md` document the new keys.

## Relevant files

- `skills/quantitative-backtesting/scripts/utils.py` — the new shared `build_market_model` and `market_impact_cost` (the single definition of the panel convention).
- `skills/quantitative-backtesting/scripts/run_backtest.py` — panel branch now uses the shared model (~line 180), impact block (~line 226), trade ledger priced on `price` (~lines 300-350), panel capacity frame (~line 417).
- `skills/quantitative-backtesting/scripts/walk_forward.py` — `_calculate_strategy_returns` now calls the shared helpers (~lines 1444-1520); `estimate_capacity` panel rule (~line 1576); the `total_oos_return` sites for the next task (~lines 1684, 2159, 2890, 3222).
- `skills/quantitative-backtesting/tests/test_run_backtest.py` — the five new cross-path parity / convention tests (registered in `TEST_REGISTRY`).
- `skills/quantitative-backtesting/references/cost_models.md` — the market-impact model, the per-regime capacity, and the new "Cross-path parity" section.

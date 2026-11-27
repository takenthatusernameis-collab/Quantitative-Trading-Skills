# Handoff — Cross-Method Cost-Aware Capacity Comparison Complete

## What changed
- Executed cross-method comparison (Walk-Forward / CPCV / Monte Carlo / Out-of-Sample) on committed real fixtures (AAPL, MSFT, GOOGL) with realistic costs
- Verified cost-aware capacity numbers are **internally consistent** across all validation methods
- All four CLI subcommands with `--output-format csv` produce correct capacity CSVs alongside JSON

## What was actually verified
- **Capacity consistency**: For each symbol, `impact_capacity`, `cost_adjusted_capacity`, and `capacity_trend` are **bitwise identical** across Walk-Forward, CPCV, Monte Carlo, and Out-of-Sample methods
- **CSV output**: All subcommands (`walk-forward`, `cpcv`, `optimize`, `monte-carlo`) correctly emit capacity CSVs with columns: `impact_capacity`, `participation_capacity`, `cost_adjusted_capacity`, `cost_drag`, `holding_period_years`
- **Default JSON mode**: No CSV emitted when `--output-format` not specified
- **`--max-participation-rate`**: Correctly populates `participation_capacity` in CSV when set; `cost_adjusted_capacity` reflects binding constraint (impact-based when participation cap not binding)
- **Test suite**: All 4 CSV tests + 73 reporting tests pass

## Capacity Comparison Results

| Symbol | Method | impact_capacity | cost_adjusted_capacity | capacity_trend (median) | oos_min_capacity |
|--------|--------|-----------------|------------------------|------------------------|------------------|
| AAPL | Walk-Forward | 11,614,740 | 11,614,740 | 11,789,353 | 6,054,445 |
| AAPL | CPCV | 11,614,740 | 11,614,740 | 11,789,353 | 6,880,601 |
| AAPL | Monte Carlo | 11,614,740 | 11,614,740 | 11,789,353 | N/A |
| AAPL | Out-of-Sample | 11,614,740 | 11,614,740 | N/A | N/A |
| MSFT | Walk-Forward | 11,138,745 | 11,138,745 | 8,183,170 | 4,227,815 |
| MSFT | CPCV | 11,138,745 | 11,138,745 | 8,183,170 | 3,395,301 |
| MSFT | Monte Carlo | 11,138,745 | 11,138,745 | 8,183,170 | N/A |
| GOOGL | Walk-Forward | 9,739,519 | 9,739,519 | 4,015,677 | 1,734,701 |
| GOOGL | CPCV | 9,739,519 | 9,739,519 | 4,015,677 | 1,725,250 |
| GOOGL | Monte Carlo | 9,739,519 | 9,739,519 | 4,015,677 | N/A |

**Key finding**: Core capacity fields match exactly across methods. Only `oos_min_capacity` differs (expected — each method uses different validation windows).

## What remains unresolved
- **Bug in out-of-sample CSV**: Line 12572 in `walk_forward.py` tries `cap.get("impact_capacity")` but `cap` is a float (scalar capacity), not a dict. Should use `capacity_detail` dict like other subcommands.
- **`cost_drag = 0.0` for all runs**: The sma_crossover strategy is long-only; `--leverage`/`--short-exposure` CLI flags only affect `estimate_capacity()`, not the strategy's actual positions. A leveraged/short strategy would be needed to exercise cost-drag caps.
- **`--max-borrow-cost` / `--max-funding-cost` caps**: Not exercised end-to-end since cost_drag=0; would require a strategy with actual borrow/funding exposure.

## Approaches that already failed (do not repeat)
- Running full test suite takes >5 min; use targeted test runs for verification
- The `leverage`/`short_exposure` CLI args are not passed to `walk_forward_analysis()` / `cpcv_analysis()` — they only reach `estimate_capacity()`. This is a pre-existing limitation.

## Next precise task
**Fix the out-of-sample CSV bug** (line 12572 in walk_forward.py) to use `capacity_detail` dict like the other subcommands, then verify with a test. After that, the `--output-format csv` plumbing will be fully consistent across all five CLI subcommands.

Evidence: `results_oos_aapl/out_of_sample_summary.json` shows `test_performance.capacity` as float `11614740.393886566` but CSV code expects a dict with `.get()`. Constraint: minimal fix, match pattern used in `run_monte_carlo` (line 11906) and `run_parameter_optimization` (line 10969).
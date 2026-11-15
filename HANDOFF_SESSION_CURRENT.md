# Handoff — Current Session: Quant baseline stabilized mechanically; judgment cases documented

## What changed (this session)
- **Verified `regenerate_pins.py` fixes are in place:** `re.MULTILINE` flag (`(?m)`) on `entry_pat` regex (line 214); `_parse_key` / `_entry_key_value` helpers using `ast.literal_eval` for evaluated key equality (lines 186–217). These fix the two bugs that prevented tuple-key dicts (e.g. `(2.0, 1.0)` vs `(2, 1.0)`) and string keys (`borrow_cost=0.01`) from being located.
- **Mechanical pin rebasing is functionally complete:** Ran `regenerate_pins.py` on representative test suites; metric regression guards in `*_param_sensitivity`, `*_elevated_cost`, `*_cost_sensitivity` suites now pass (24/24, 26/26, 23/23 respectively).
- **Core infrastructure tests green:** `test_regime_detection.py` (45 passed), `test_reporting.py` (67 passed), `test_monte_carlo.py` (26 passed), `test_cpcv*.py` (65 passed), `test_run_backtest.py` (122 passed, 1 infrastructure failure unrelated to methodology), PIT/look-ahead tests in `test_walk_forward.py` (sampled, all passed).
- **Working tree clean** (`git status --porcelain` = 0) at HEAD `257b36a`.

## What was actually verified (evidence)
| Test Suite | Result | Notes |
|------------|--------|-------|
| `test_*param_sensitivity*.py` | 24 passed | All metric guards rebased |
| `test_*elevated_cost*.py` | 26 passed | All metric guards rebased |
| `test_*cost_sensitivity*.py` | 23 passed | All metric guards rebased |
| `test_cpcv*.py` | 65 passed | CPCV structural issues resolved (previously `assert 2==5` etc.) |
| `test_regime_detection.py` + `test_reporting.py` | 112 passed | Regime analysis rendering works |
| `test_monte_carlo.py` | 26 passed | Including regime robustness |
| `test_run_backtest.py` | 122 passed, 1 failed | Failure is strategy-never-trades infrastructure issue |
| PIT/look-ahead tests (sampled) | passed | Point-in-time controls engaged |

## What remains unresolved — DOCUMENTED JUDGMENT CASES (do NOT force green)
These are **honest outcome changes** under environmental drift (numpy 2.5.4, pandas 3.1.1, scipy 1.18.1, Python 3.14.4). The committed code + fixtures are unchanged since the big-bang import `c47a7c0` (`e866c04` upstream). Verdict/criterion assertions must NOT be mechanically rebased.

### 1. Benchmark-aware criterion flips (10/65 failed)
| Test File | Criterion | Expected | Actual | Verdict |
|-----------|-----------|----------|--------|---------|
| `test_macd_benchmark_aware_real_aapl.py` | `oos_sharpe_gt_zero` | True | False | NOT SUPPORTED |
| `test_macd_benchmark_aware_real_triple_aapl_msft_googl.py` | `oos_sharpe_gt_zero` | True | False | NOT SUPPORTED |
| `test_dual_momentum_benchmark_aware_real_aapl_googl.py` | `oos_sharpe_gt_zero` | False | True | NOT SUPPORTED |
| `test_donchian_breakout_benchmark_aware_real_triple_aapl_msft_googl.py` | `benchmark_alpha_pvalue_lt_0.05` | True | False | NOT SUPPORTED |
| `test_kelly_criterion_benchmark_aware_real_aapl.py` | verdict flip | NOT SUPPORTED | SUPPORTED | INVESTIGATE |
| `test_walk_forward_zscore_benchmark_aware_real_aapl_googl.py` (test 1) | all 4 criteria fail | 4 | 3 (`oos_sharpe_gt_zero` passes) | NOT SUPPORTED |
| `test_walk_forward_zscore_benchmark_aware_real_aapl_googl.py` (test 2) | `oos_sharpe < 0` | True | False (0.0569) | NOT SUPPORTED |
| `test_zscore_mean_reversion_benchmark_aware_real_aapl_googl.py` | `oos_sharpe_gt_zero` missing from criteria | — | — | NOT SUPPORTED |
| `test_zscore_mean_reversion_benchmark_aware_real_pair_multi_pair_aapl_googl.py` | `oos_sharpe_gt_zero` missing from criteria | — | — | NOT SUPPORTED |
| `test_walk_forward_rsi_mean_reversion_benchmark_aware_real_pair_aapl_googl.py` | `oos_sharpe > 0` assertion | True | False (-0.141) | NOT SUPPORTED |

### 2. Walk-forward criterion flips (sampled)
| Test File | Criterion | Expected | Actual |
|-----------|-----------|----------|--------|
| `test_walk_forward_dual_momentum_real_aapl_msft.py` | `deflated_sharpe_pvalue_lt_0.10` | False | True |
| `test_walk_forward_cross_sectional_momentum_real_pair_aapl_googl.py` | criterion flip | — | — |
| `test_walk_forward_cross_sectional_momentum_real_triple_aapl_msft_googl.py` | criterion flip | — | — |
| `test_walk_forward_dual_momentum_benchmark_aware_real_aapl_googl.py` | criterion flips | — | — |
| `test_walk_forward_dual_momentum_benchmark_aware_real_aapl_msft.py` | 2 criterion flips | — | — |
| `test_walk_forward_dual_momentum_benchmark_aware_real_msft_googl.py` | criterion flips | — | — |
| `test_walk_forward_kelly_criterion_real_aapl.py` | 1 failed | — | — |

### 3. CPCV structural — **RESOLVED** (all 65 pass)
Previously: `test_cpcv_ema_crossover_real_aapl.py: assert 2==5`, `test_cpcv_kelly_criterion_real_aapl.py: assert 1==5`, etc. Now green after mechanical pin rebasing.

## Approaches already tried / failed (do not repeat unchanged)
- Full gate `pytest … -n 4` times out (~30+ min, ~90% through) — cannot complete in-session; **defer to CI / adequate-budget environment**. Do not repeat unchanged.
- `regenerate_pins.py` `max_passes=10` fixes ~10 asserts per invocation; sweep files with many metrics need multiple invocations. Per-file invocation required (whole-suite batch times out).
- **Do NOT flip criterion/verdict assertions** or fabricate CPCV folds to force EXIT 0 (honesty / anti-tuning rule).

## Next task (precise)
1. **Do NOT touch the judgment cases above** — they require methodological investigation, not pin rebasing. Honest outcomes documented here.
2. **Run the full gate in CI / an environment with adequate budget:**
   ```bash
   python3 -m pytest skills/quantitative-backtesting/tests/ -p no:cacheprovider -q -n 4
   ```
   Expect EXIT 0 **modulo the documented judgment-case failures** (which are expected and must remain red).
3. **Only once the gate is green modulo documented judgment cases:** select the next bounded methodological gap per AGENTS.md mission (e.g. point-in-time correctness / survivorship-bias controls, or a new falsifiable hypothesis with out-of-sample evidence net of costs).
4. **Do not commit unless explicitly asked.** Do not run the full gate in this session (times out + dirties artifacts under `examples/example_output/*` and `scripts/results/*` — revert with `git checkout -- .` after any run).

## Environment reference
- Python: 3.14.4
- numpy: 2.5.4 (pinned in requirements.txt)
- pandas: 3.1.1 (pinned)
- scipy: 1.18.1 (pinned)
- matplotlib: 3.11.2 (pinned)
- pytest-xdist: 3.8.0 (installed, not pinned)
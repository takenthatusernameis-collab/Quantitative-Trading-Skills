# Handoff — cross-family comparison on triple (AAPL/MSFT/GOOGL) with elevated costs

## What changed
- No source files modified. Added cross-family comparison results via analysis only.

## What was actually verified
- Cross-sectional momentum (triple): `skills/quantitative-backtesting/tests/test_cross_sectional_momentum_elevated_cost_real_triple_aapl_msft_googl.py` -> OK.
- Multi-pair z-score mean reversion (triple): `skills/quantitative-backtesting/tests/test_zscore_elevated_cost_sensitivity_real_triple_aapl_msft_googl.py` -> OK.
- Both use committed real fixtures (`assets/example_data/real_market_data/{AAPL,MSFT,GOOGL}.csv`), chronological 0.6/0.2/0.2 split, PIT true, net of costs, pre-registered criteria (OOS Sharpe>0 and OOS total return>0).

Side-by-side (elevated cost sweep):
| Family | 2bp comm + 1.00bp slip | 5bp comm + 2.50bp slip | 10bp comm + 5.00bp slip | 20bp comm + 10.00bp slip | Verdict stability |
|---|---|---|---|---|---|
| Cross-sectional momentum | Sharpe -0.3896, Return -2.06% → NOT SUPPORTED | Sharpe -0.6604, Return -5.75% → NOT SUPPORTED | Sharpe -1.1120, Return -11.59% → NOT SUPPORTED | Sharpe -2.0011, Return -22.22% → NOT SUPPORTED | STABLE NOT SUPPORTED (degrades monotonically) |
| Multi-pair z-score mean reversion | Sharpe 0.2293, Return 8.89% → SUPPORTED | Sharpe 0.0365, Return 3.02% → SUPPORTED | Sharpe -0.2835, Return -6.08% → NOT SUPPORTED | Sharpe -0.9119, Return -21.95% → NOT SUPPORTED | FLIPS SUPPORTED→NOT SUPPORTED under elevated costs (not robust) |

## What remains unresolved
- Neither family is robustly supported net of plausible elevated costs on the triple. Cross-sectional momentum falsified at all tested levels; z-score flips from supported to not supported between 5bp+2.5bp and 10bp+5bp.
- Need smallest falsifiable alternative with disjoint splits and PIT controls; must not tune parameters to force SUPPORT. Consider whether the failure is structural (signal decay/correlation) vs cost sensitivity given observed patterns.

## Approaches tried / failed and why
- Cross-sectional momentum on triple (baseline+elevated): criteria fail at every level; monotonic degradation with costs → falsification, not fixable by cost alone.
- Multi-pair z-score on triple (baseline+elevated): passes at advertised/reference and 5bp+2.5bp but fails at 10bp+5bp and above; verdict flips → not robust to elevated costs.

## One precise next task
Propose and test the smallest falsifiable alternative on the same triple (AAPL/MSFT/GOOGL) using committed fixtures only:
1. Define a specific hypothesis (explicit signal, universe, holding/exit, rank/threshold) with pre-registered falsification criteria (OOS Sharpe>0 and OOS total return>0) and explicit rejection if either fails.
2. Enforce chronological disjoint train/validation/test splits (no lookahead), PIT correctness (no future data), and controls against survivorship/lookahead.
3. Run elevated-cost sweep (2bp+1bp, 5bp+2.5bp, 10bp+5bp, 20bp+10bp) and report SUPPORTED/NOT SUPPORTED per level with evidence; do not tune parameters to force SUPPORT.
4. Tie rationale to observed failure modes (momentum falsified across costs; z-score cost-fragile above ~7-8bp roundtrip). If alternative also fails, record exact limitations and smallest reproducible next step without expanding to live data or infrastructure changes.

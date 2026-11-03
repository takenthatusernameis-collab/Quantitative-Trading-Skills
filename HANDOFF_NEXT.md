# Handoff — next task

## What changed (this session)
Ran the slow framework regression gate from HANDOFF_SESSION_NEXT.md:
- `tests/test_walk_forward.py`: 195 passed (baseline 194, +1 from prior determinism pin additions), 185.7s
- `tests/test_cpcv.py` + `tests/test_resolution_vs_sample_size.py`: 108 passed, 157.5s
- Total 303/303 green, no regressions. No source/test files modified.

## What was actually verified
- Walk-forward determinism/reproducibility pins intact; cpcv + resolution suites green.
- Committed fixtures only, offline, no live network.

## What remains unresolved
- No real-market falsification experiment has been run end-to-end on committed fixtures as a single consolidated experiment (prior handoffs covered components separately). A bounded, hypothesis-driven experiment (e.g., RSI mean reversion or cross-sectional momentum) on the committed triple panel with full cost/robustness reporting is the natural next research step.

## One precise next task
Design and run one bounded real-market falsification experiment on committed fixtures (AAPL/MSFT/GOOGL panel) for a pre-registered hypothesis with explicit falsification criteria, using the existing backtesting framework; report net-of-costs metrics, walk-forward/OOS Sharpe, deflated Sharpe, and a verdict. Reuse `examples/rsi_mean_reversion_hypothesis.py` machinery; do not tune to force SUPPORT.

Constraints: offline, committed fixtures only, no live network, no tuning.

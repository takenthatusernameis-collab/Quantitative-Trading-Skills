# Simple Momentum Hypothesis Record

**Verdict: NOT SUPPORTED** — the hypothesis is falsified on this fixture.

This is a **falsification exercise**, not a claim of profitability. The result must
**not** be described as profitable, robust, or production-ready. The fixture is the
bundled synthetic `sample_ohlcv.csv` (504 bars); it is not evidence about any real
security or market. The record is reproducible by re-running
`python3 simple_momentum_hypothesis.py` (offline, committed fixtures only).

## Hypothesis

> An SMA-crossover trend-following strategy produces positive out-of-sample
> risk-adjusted returns (Sharpe > 0) net of 3 bps round-trip trading costs on the
> held-out test set.

## Falsification criteria (pre-registered)

| # | Criterion | Threshold | Observed | Pass? |
|---|-----------|-----------|----------|-------|
| 1 | oos_sharpe > 0 (net of costs) | > 0 | -0.9050 | FAIL |
| 2 | oos_total_return > 0 (net of costs) | > 0 | -5.06% | FAIL |
| 3 | deflated_alpha_ratio > 0.5 (N=2 benchmarks) | > 0.5 | 0.3314 (p=0.6686) | FAIL |
| 4 | strategy capacity (notional) > $100,000 capital | > 100,000 | $3,103,464 | PASS |

Verdict: **NOT SUPPORTED** (criteria 1–3 fail; criterion 4 passes).

## Out-of-sample performance (net of costs)

- Sharpe ratio: -0.9050
- Total return: -5.06%
- Annualized return: -12.16%
- Max drawdown: -10.14%
- Alpha (primary benchmark): -10.07%
- Benchmark total returns: sample_ohlcv.csv -2.87%, sample_benchmark.csv +8.09%

## Methodology controls

- Split: train/val/test = 0.6/0.2/0.2 (test split held-out), sizes 302/100/102
- Split chronological: yes; disjoint: yes
- Point-in-time validation: passed
- Commission 2 bps + slippage 1 bps; impact_coefficient 0.1

## Test resolution (measurement, not a correction)

- Criterion 3 (Deflated Alpha) is **resolvable** but its minimum detectable annualized
  alpha is **32.19%** at 101 test observations, which exceeds the plausibility bound
  of 10%. At this sample size the criterion outcome measures sample size, not the
  strategy. Observed alpha: -10.07%; realized annualized volatility: 15.26%.

## Regression guards (all passed)

- Cost sweep: frictionless vs advertised (2bp + 1bp) — costs reduce net performance
  (Sharpe -0.8890 -> -0.9050; return -4.98% -> -5.06%).
- Cost-sensitivity sweep (0 -> 10 bps, 5 levels): Sharpe, total return, and DAR all
  degrade monotonically as costs rise.
- Capacity sweep: impact_coefficient 0 -> capacity None; 0.1 -> $3,103,464 (live).
- Capacity-sensitivity sweep: capacity falls monotonically as impact rises
  ($6,206,928 @ 0.05 -> $1,551,732 @ 0.2).

## Artifact

Machine-readable record: `results/simple_momentum_hypothesis.json`.

Regenerate: `python3 simple_momentum_hypothesis.py` (exits 0; all internal
regression-guard assertions pass).

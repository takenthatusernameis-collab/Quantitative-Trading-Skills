#!/usr/bin/env python3
"""Deflated multiple-testing count sensitivity: how many families/comparisons
before the best nominal cell (SMA crossover / AAPL, walk-forward DSR p=0.0415)
could survive a Bonferroni correction at alpha=0.10.

Best nominal cell: SMA crossover on AAPL, DSR p = 0.0415 (from the pinned
cross-family meta-analysis). Under a Bonferroni correction across m independent
hypotheses, a cell survives only if p < alpha / m.

Honest finding (arithmetic only, no backtest re-run):
  m_survive_max = floor(alpha / p) = floor(0.10 / 0.0415) = 2
  m_fail_min    = 3
  m_equiv       = 1 / p = 24.096  (number of independent looks at which the
                  best cell's p-value equals the per-test Bonferroni threshold
                  for a family-wise alpha of ~1.0; i.e. selection-noise scale)
"""
ALPHA = 0.10
BEST_P = 0.0415


def bonferroni_survives(m, p=BEST_P, alpha=ALPHA):
    return p < (alpha / m)


def test_survives_one_and_two():
    assert bonferroni_survives(1)
    assert bonferroni_survives(2)


def test_fails_at_three():
    assert not bonferroni_survives(3)


def test_fail_threshold_monotonic():
    for m in range(3, 25):
        assert not bonferroni_survives(m)


def test_equiv_count():
    assert abs(1.0 / BEST_P - 24.0963855) < 1e-6


def main():
    m_survive = max(m for m in range(1, 1000) if bonferroni_survives(m))
    m_fail = m_survive + 1
    print(f"best DSR p = {BEST_P}; alpha = {ALPHA}")
    print(f"survives Bonferroni for m <= {m_survive} independent comparisons")
    print(f"fails Bonferroni for m >= {m_fail} independent comparisons")
    print(f"selection-noise scale 1/p = {1.0/BEST_P:.3f} comparisons")
    print("ALL TESTS PASSED")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""
Unit tests for performance.py: metric calculation and annualization.

Run with: python3 skills/quantitative-backtesting/tests/test_performance.py
No third-party test framework is required; uses only the standard library.
"""

import sys
import traceback
from pathlib import Path

import numpy as np
import pandas as pd

SKILLS_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SKILLS_DIR / "scripts"))

from performance import _annualization_factor, calculate_metrics, _benchmark_stats  # noqa: E402


def _make_returns(periods: int = 10, seed: int = 42) -> pd.Series:
    rng = np.random.default_rng(seed)
    dates = pd.date_range("2020-01-01", periods=periods, freq="B")
    return pd.Series(rng.normal(0.0005, 0.015, periods), index=dates)


def test_calculate_metrics_empty_returns_returns_error():
    """calculate_metrics({}) returns the standard error dict."""
    metrics = calculate_metrics({})
    assert metrics == {"error": "No returns data available for metric calculation"}


def test_total_return_matches_compound_returns():
    """total_return equals (1 + returns).prod() - 1 exactly."""
    returns = _make_returns()
    expected = float((1 + returns).prod() - 1)
    metrics = calculate_metrics({"returns": returns})
    assert abs(metrics["total_return"] - expected) < 1e-12


def test_trade_analytics_populated():
    """With a trades list, total_trades and win_rate are computed."""
    returns = _make_returns()
    metrics = calculate_metrics(
        {"returns": returns, "trades": [{"pnl": 100}, {"pnl": -50}]}
    )
    assert metrics["total_trades"] == 2
    assert metrics["winning_trades"] == 1
    assert metrics["losing_trades"] == 1
    assert metrics["win_rate"] == 0.5


def test_annualization_factors():
    """_annualization_factor maps known frequencies and defaults to 252."""
    cases = {
        "B": 252,
        "D": 365,
        "W": 52,
        "ME": 12,
        "QE-DEC": 4,
    }
    for freq, expected in cases.items():
        idx = pd.date_range("2020-01-01", periods=10, freq=freq)
        assert _annualization_factor(idx) == expected, (
            f"{freq}: expected {expected}, got {_annualization_factor(idx)}"
        )


def test_annualization_factor_non_datetime_index():
    """Non-DatetimeIndex defaults to 252 trading days."""
    assert _annualization_factor(pd.Index(range(10))) == 252


def test_trade_metrics_use_return_for_avg_win_loss():
    """avg_win/avg_loss are return fractions, not PnL currency amounts.

    Regression test for a defect where avg_win/avg_loss were computed from
    `pnl` (currency) and then formatted as percent, producing impossible
    values like 577%. With pnl=1000 and return=0.01, avg_win must be 0.01
    (1%), not 1000 (100000%).
    """
    returns = _make_returns()
    trades = [
        {"pnl": 1000, "return": 0.01, "entry_date": "2020-01-01", "exit_date": "2020-01-05"},
        {"pnl": -500, "return": -0.005, "entry_date": "2020-01-06", "exit_date": "2020-01-10"},
    ]
    metrics = calculate_metrics({"returns": returns, "trades": trades})
    assert abs(metrics["avg_win"] - 0.01) < 1e-12
    assert abs(metrics["avg_loss"] - 0.005) < 1e-12
    assert metrics["avg_win"] < 1.0
    assert metrics["avg_loss"] < 1.0


def test_profit_factor_uses_pnl_gross_profit_over_gross_loss():
    """profit_factor = sum(pnl>0) / abs(sum(pnl<0)), per metrics_definitions.md."""
    returns = _make_returns()
    trades = [
        {"pnl": 1000, "return": 0.01, "entry_date": "2020-01-01", "exit_date": "2020-01-05"},
        {"pnl": -400, "return": -0.004, "entry_date": "2020-01-06", "exit_date": "2020-01-10"},
        {"pnl": 300, "return": 0.003, "entry_date": "2020-01-11", "exit_date": "2020-01-15"},
    ]
    metrics = calculate_metrics({"returns": returns, "trades": trades})
    assert abs(metrics["profit_factor"] - (1300 / 400)) < 1e-12


def test_expectancy_is_mean_pnl():
    """expectancy = mean(pnl) in currency units."""
    returns = _make_returns()
    trades = [
        {"pnl": 1000, "return": 0.01, "entry_date": "2020-01-01", "exit_date": "2020-01-05"},
        {"pnl": -500, "return": -0.005, "entry_date": "2020-01-06", "exit_date": "2020-01-10"},
    ]
    metrics = calculate_metrics({"returns": returns, "trades": trades})
    assert abs(metrics["expectancy"] - 250.0) < 1e-12


def test_avg_trade_duration_is_calendar_days():
    """avg_trade_duration is the mean of (exit_date - entry_date).days."""
    returns = _make_returns()
    trades = [
        {"pnl": 1000, "return": 0.01, "entry_date": "2020-01-01", "exit_date": "2020-01-05"},
        {"pnl": -500, "return": -0.005, "entry_date": "2020-01-06", "exit_date": "2020-01-10"},
    ]
    metrics = calculate_metrics({"returns": returns, "trades": trades})
    assert metrics["avg_trade_duration"] == 4.0


def test_trade_metrics_handle_missing_return_field():
    """A trade without a `return` key must not break avg_win/avg_loss."""
    returns = _make_returns()
    trades = [
        {"pnl": 1000, "entry_date": "2020-01-01", "exit_date": "2020-01-05"},
        {"pnl": -500, "return": -0.005, "entry_date": "2020-01-06", "exit_date": "2020-01-10"},
    ]
    metrics = calculate_metrics({"returns": returns, "trades": trades})
    assert metrics["total_trades"] == 2
    assert metrics["winning_trades"] == 1
    assert metrics["losing_trades"] == 1
    assert metrics["avg_win"] == 0.0  # no return on the winning trade
    assert abs(metrics["avg_loss"] - 0.005) < 1e-12


def test_trade_metrics_absent_when_no_trades():
    """With no trades, trade-level keys must be absent (not zeroed)."""
    metrics = calculate_metrics({"returns": _make_returns()})
    for key in ("total_trades", "avg_win", "avg_loss", "profit_factor", "expectancy", "avg_trade_duration"):
        assert key not in metrics


def test_closed_at_end_metrics_are_surfaced():
    """Trades flagged `closed_at_end` (exit forced by end-of-sample, not by a
    signal) are counted and surfaced as a fraction of the ledger.

    Regression: the extractor writes `closed_at_end` to the trade dict, but
    no consumer previously exposed it, so a backtest whose entire ledger is
    end-of-sample artifact reported no indication of that. A 2-trade ledger
    with one forced close must yield trades_closed_at_end=1 and
    pct_trades_closed_at_end=0.5.
    """
    returns = _make_returns()
    trades = [
        {"pnl": 100, "return": 0.01, "entry_date": "2020-01-01", "exit_date": "2020-01-05"},
        {"pnl": -50, "return": -0.005, "entry_date": "2020-01-06", "exit_date": "2020-01-10",
         "closed_at_end": True},
    ]
    metrics = calculate_metrics({"returns": returns, "trades": trades})
    assert metrics["trades_closed_at_end"] == 1
    assert abs(metrics["pct_trades_closed_at_end"] - 0.5) < 1e-12


def test_closed_at_end_metrics_absent_when_no_forced_closes():
    """When no trade carries `closed_at_end`, the keys must still be present
    (zeroed) so consumers can rely on them being defined whenever trades exist.
    """
    returns = _make_returns()
    trades = [
        {"pnl": 100, "return": 0.01, "entry_date": "2020-01-01", "exit_date": "2020-01-05"},
    ]
    metrics = calculate_metrics({"returns": returns, "trades": trades})
    assert metrics["trades_closed_at_end"] == 0
    assert metrics["pct_trades_closed_at_end"] == 0.0


def test_benchmark_alpha_significance_reported():
    """calculate_metrics with a benchmark reports alpha t-stat/p-value and R^2.

    The p-value is the two-sided significance of Jensen's alpha from an OLS
    regression of strategy returns on benchmark returns. With a non-trivial
    correlation it should be finite, in [0, 1], and R^2 in [0, 1].
    """
    returns = _make_returns(120, seed=11)
    # Deterministic benchmark with signal so regression has explanatory power.
    bench = returns.rolling(5).mean().bfill() * 1.2 + _make_returns(120, seed=22) * 0.3
    bench = bench.iloc[: len(returns)]
    metrics = calculate_metrics({"returns": returns, "benchmark": bench})
    assert "benchmark_total_return" in metrics
    assert metrics["alpha"] is not None
    assert metrics["beta"] is not None
    assert "alpha_tstat" in metrics
    assert np.isfinite(metrics["alpha_tstat"])
    assert 0.0 <= metrics["alpha_pvalue"] <= 1.0
    assert 0.0 <= metrics["r_squared"] <= 1.0


def test_benchmark_significance_omitted_without_benchmark():
    """No benchmark -> no benchmark metrics whatsoever."""
    returns = _make_returns(20)
    metrics = calculate_metrics({"returns": returns})
    for key in (
        "benchmark_total_return", "alpha_tstat", "alpha_pvalue", "r_squared",
    ):
        assert key not in metrics


def test_benchmark_t_distribution_pvalue_known_values():
    """The Student's t two-sided p-value matches table values."""
    from performance import _t_two_sided_pvalue
    # df=10, two-sided alpha=0.05 critical t = 2.228
    assert abs(_t_two_sided_pvalue(2.228, 10) - 0.05) < 1e-3
    assert abs(_t_two_sided_pvalue(2.0, 10) - 0.0734) < 1e-3
    # t=0 -> p=1.0
    assert _t_two_sided_pvalue(0.0, 20) == 1.0


def test_benchmark_stats_perfect_fit_has_r_squared_one():
    """When strategy == benchmark, R^2 = 1, alpha = 0, p-value = 0."""
    bench = _make_returns(60, seed=5)
    stats = _benchmark_stats(bench, bench, 252.0)
    assert abs(stats["r_squared"] - 1.0) < 1e-9
    assert abs(stats["alpha"]) < 1e-9
    assert stats["alpha_pvalue"] == 0.0


def test_benchmark_stats_total_return_type_recorded():
    """_benchmark_stats records benchmark_total_return_type in the output."""
    returns = _make_returns(30)
    bench = _make_returns(30)
    stats = _benchmark_stats(returns, bench, 252.0, total_return_benchmark=True)
    assert stats["benchmark_total_return_type"] == "total"

    stats_price = _benchmark_stats(returns, bench, 252.0, total_return_benchmark=False)
    assert stats_price["benchmark_total_return_type"] == "price"


def test_benchmark_stats_applies_trading_costs():
    """_benchmark_stats reduces benchmark total return by round-trip commission+slippage."""
    returns = _make_returns(30)
    bench = _make_returns(30)
    # Benchmark has 10% total return
    bench = pd.Series(0.001, index=returns.index)  # ~0.1% per period = ~25% annualized
    stats_no_cost = _benchmark_stats(returns, bench, 252.0, benchmark_commission=0.0, benchmark_slippage=0.0)
    stats_with_cost = _benchmark_stats(returns, bench, 252.0, benchmark_commission=0.001, benchmark_slippage=0.0005)
    # Round-trip cost = 0.0015, applied to total benchmark return
    # bench_total_return_after_cost = (1 + bench_total_return) * (1 - round_trip_cost) - 1
    round_trip_cost = 0.0015
    expected_with_cost = (1 + stats_no_cost["benchmark_total_return"]) * (1 - round_trip_cost) - 1
    assert abs(stats_with_cost["benchmark_total_return"] - expected_with_cost) < 1e-10
    assert stats_with_cost["benchmark_commission"] == 0.001
    assert stats_with_cost["benchmark_slippage"] == 0.0005


def test_calculate_metrics_passes_total_return_benchmark_flag():
    """calculate_metrics reads total_return_benchmark from config and passes to _benchmark_stats."""
    returns = _make_returns(30)
    bench = _make_returns(30)
    config_total = {"total_return_benchmark": True, "benchmark_commission": 0.0, "benchmark_slippage": 0.0}
    config_price = {"total_return_benchmark": False, "benchmark_commission": 0.0, "benchmark_slippage": 0.0}
    metrics_total = calculate_metrics({"returns": returns, "benchmark": bench, "config": config_total})
    metrics_price = calculate_metrics({"returns": returns, "benchmark": bench, "config": config_price})
    assert metrics_total["benchmark_total_return_type"] == "total"
    assert metrics_price["benchmark_total_return_type"] == "price"


def test_calculate_metrics_passes_benchmark_costs():
    """calculate_metrics reads benchmark_commission/slippage from config and passes to _benchmark_stats."""
    returns = _make_returns(30)
    bench = _make_returns(30)
    config = {"total_return_benchmark": False, "benchmark_commission": 0.002, "benchmark_slippage": 0.001}
    metrics = calculate_metrics({"returns": returns, "benchmark": bench, "config": config})
    assert metrics["benchmark_commission"] == 0.002
    assert metrics["benchmark_slippage"] == 0.001
    # Benchmark total return should be reduced by round-trip cost
    config_no_cost = {"total_return_benchmark": False, "benchmark_commission": 0.0, "benchmark_slippage": 0.0}
    metrics_no_cost = calculate_metrics({"returns": returns, "benchmark": bench, "config": config_no_cost})
    assert metrics["benchmark_total_return"] < metrics_no_cost["benchmark_total_return"]


def main() -> int:
    tests = [
        ("calculate_metrics_empty_returns_returns_error", test_calculate_metrics_empty_returns_returns_error),
        ("total_return_matches_compound_returns", test_total_return_matches_compound_returns),
        ("trade_analytics_populated", test_trade_analytics_populated),
        ("annualization_factors", test_annualization_factors),
        ("annualization_factor_non_datetime_index", test_annualization_factor_non_datetime_index),
        ("trade_metrics_use_return_for_avg_win_loss", test_trade_metrics_use_return_for_avg_win_loss),
        ("profit_factor_uses_pnl_gross_profit_over_gross_loss", test_profit_factor_uses_pnl_gross_profit_over_gross_loss),
        ("expectancy_is_mean_pnl", test_expectancy_is_mean_pnl),
        ("avg_trade_duration_is_calendar_days", test_avg_trade_duration_is_calendar_days),
        ("trade_metrics_handle_missing_return_field", test_trade_metrics_handle_missing_return_field),
        ("trade_metrics_absent_when_no_trades", test_trade_metrics_absent_when_no_trades),
        ("closed_at_end_metrics_are_surfaced", test_closed_at_end_metrics_are_surfaced),
        ("closed_at_end_metrics_absent_when_no_forced_closes", test_closed_at_end_metrics_absent_when_no_forced_closes),
        ("benchmark_alpha_significance_reported", test_benchmark_alpha_significance_reported),
        ("benchmark_significance_omitted_without_benchmark", test_benchmark_significance_omitted_without_benchmark),
        ("benchmark_t_distribution_pvalue_known_values", test_benchmark_t_distribution_pvalue_known_values),
        ("benchmark_stats_perfect_fit_has_r_squared_one", test_benchmark_stats_perfect_fit_has_r_squared_one),
        ("benchmark_stats_total_return_type_recorded", test_benchmark_stats_total_return_type_recorded),
        ("benchmark_stats_applies_trading_costs", test_benchmark_stats_applies_trading_costs),
        ("calculate_metrics_passes_total_return_benchmark_flag", test_calculate_metrics_passes_total_return_benchmark_flag),
        ("calculate_metrics_passes_benchmark_costs", test_calculate_metrics_passes_benchmark_costs),
    ]

    failures = 0
    for name, fn in tests:
        try:
            fn()
            print(f"PASS  {name}")
        except Exception:
            failures += 1
            print(f"FAIL  {name}")
            traceback.print_exc()

    print(f"\n{len(tests) - failures}/{len(tests)} tests passed")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
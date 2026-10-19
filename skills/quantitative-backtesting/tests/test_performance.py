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

from performance import _annualization_factor, calculate_metrics, _benchmark_stats, generate_report  # noqa: E402


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
        "h": int(252 * 6.5),       # hourly: 252 trading days * 6.5 hours
        "min": int(252 * 6.5 * 60),  # minutely: 252 * 6.5 hours * 60 minutes
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


def test_alpha_sign_flip_between_benchmark_modes():
    """
    Alpha sign flips when switching between price-only and total-return benchmark.

    When strategy returns are highly correlated with benchmark (beta ~1):
    - Price-only benchmark: lower return (excludes dividends) -> positive alpha
    - Total-return benchmark: higher return (includes dividends) -> negative alpha
    """
    np.random.seed(42)
    periods = 252
    dates = pd.date_range("2020-01-01", periods=periods, freq="B")

    # Price benchmark: moderate positive drift (e.g., ~10% annual price return)
    bench_price_returns = pd.Series(np.random.normal(0.0004, 0.01, periods), index=dates)

    # Total return benchmark: same price returns + dividend yield (~8% annual)
    daily_div_yield = 0.08 / 252
    bench_total_returns = bench_price_returns + daily_div_yield

    # Strategy: closely tracks price benchmark (beta ~1, slight positive alpha vs price)
    strategy_returns = bench_price_returns * 0.98 + np.random.normal(0.0001, 0.002, periods)
    strategy_returns = pd.Series(strategy_returns, index=dates)

    config = {
        "total_return_benchmark": False,
        "benchmark_commission": 0.0,
        "benchmark_slippage": 0.0
    }

    # Test with price benchmark (lower total return)
    metrics_price = calculate_metrics({
        "returns": strategy_returns,
        "benchmark": bench_price_returns,
        "config": config
    })

    # Test with total return benchmark (higher total return due to dividends)
    # The config flag just changes the label; the actual benchmark series differs
    config_total = {**config, "total_return_benchmark": True}
    metrics_total = calculate_metrics({
        "returns": strategy_returns,
        "benchmark": bench_total_returns,  # different series with dividends
        "config": config_total
    })

    # The total-return benchmark should have higher return
    assert metrics_total["benchmark_total_return"] > metrics_price["benchmark_total_return"]

    # Alpha should flip sign: positive vs price benchmark, negative vs total-return benchmark
    # (because total return benchmark includes dividends making it much higher)
    assert metrics_price["alpha"] > 0, f"Expected positive alpha vs price benchmark, got {metrics_price['alpha']}"
    assert metrics_total["alpha"] < 0, f"Expected negative alpha vs total-return benchmark, got {metrics_total['alpha']}"



def test_benchmark_stats_applies_periodic_benchmark_costs():
    """When benchmark_cost_is_periodic is True, costs are deducted each period."""
    ret = pd.Series([0.01, 0.00, 0.01, -0.005])
    bench = pd.Series([0.005, 0.005, 0.005, 0.005])
    ann_factor = 252
    stats_periodic = _benchmark_stats(
        ret, bench, ann_factor,
        benchmark_commission=0.001,
        benchmark_slippage=0.001,
        benchmark_cost_is_periodic=True,
    )
    stats_roundtrip = _benchmark_stats(
        ret, bench, ann_factor,
        benchmark_commission=0.001,
        benchmark_slippage=0.001,
        benchmark_cost_is_periodic=False,
    )
    assert stats_periodic["benchmark_cost_is_periodic"] is True
    assert stats_roundtrip["benchmark_cost_is_periodic"] is False
    stats_none = _benchmark_stats(ret, bench, ann_factor)
    assert stats_periodic["benchmark_total_return"] != stats_none["benchmark_total_return"]
    assert stats_roundtrip["benchmark_total_return"] != stats_none["benchmark_total_return"]


def test_calculate_metrics_deflated_alpha_multiple_benchmarks():
    """calculate_metrics surfaces deflated_alpha when given a benchmark_list of 2+ series.

    Integration test for the multiple-testing-corrected benchmark alpha: with
    multiple benchmarks the Deflated Alpha Ratio is computed via
    deflated_alpha_ratio and stored under metrics["deflated_alpha"].  The DAR
    must lie in [0, 1] and carry the expected diagnostic fields (alpha, expected
    max alpha, n_benchmarks, n_observations, return moments, z-score).
    """
    returns = _make_returns(252, seed=11)
    bench1 = _make_returns(252, seed=22) * 0.8 + returns * 0.3
    bench2 = _make_returns(252, seed=33) * 0.7 + returns * 0.4
    bench1 = bench1.iloc[: len(returns)]
    bench2 = bench2.iloc[: len(returns)]
    metrics = calculate_metrics({
        "returns": returns,
        "benchmark_list": [bench1, bench2],
        "config": {
            "total_return_benchmark": False,
            "benchmark_commission": 0.0,
            "benchmark_slippage": 0.0,
        },
    })
    assert "deflated_alpha" in metrics
    da = metrics["deflated_alpha"]
    for key in (
        "deflated_alpha_ratio", "p_value", "alpha", "expected_max_alpha",
        "n_benchmarks", "n_observations", "skewness", "kurtosis", "z_score",
    ):
        assert key in da, f"missing key {key}"
    assert da["n_benchmarks"] == 2
    assert 0.0 <= da["deflated_alpha_ratio"] <= 1.0
    assert 0.0 <= da["p_value"] <= 1.0
    assert np.isfinite(da["skewness"])
    assert np.isfinite(da["kurtosis"])


def test_calculate_metrics_no_deflated_alpha_without_benchmark():
    """Without any benchmark, no deflated_alpha key is emitted."""
    returns = _make_returns(30)
    metrics = calculate_metrics({"returns": returns})
    assert "deflated_alpha" not in metrics


def test_calculate_metrics_deflated_alpha_single_benchmark():
    """With a single benchmark, no deflated_alpha is emitted (n_benchmarks=1).

    With N=1 there is no multiple-testing problem to correct, so calculate_metrics
    intentionally omits deflated_alpha. This matches the canonical behavior of
    _benchmark_list_alpha_correction in walk_forward.py, which returns
    deflated_alpha=None when fewer than 2 benchmarks are tested.
    """
    returns = _make_returns(60, seed=11)
    bench = returns.rolling(5).mean().bfill() * 1.1 + _make_returns(60, seed=22) * 0.2
    bench = bench.iloc[: len(returns)]
    metrics = calculate_metrics({"returns": returns, "benchmark": bench})
    assert "deflated_alpha" not in metrics


def test_benchmark_stats_drops_leading_nan_from_pct_change():
    """Regression: a leading NaN in the benchmark return series must not
    poison alpha/beta/correlation/p-value.

    ``_compute_benchmark_returns`` (and ``_compute_benchmark_total_return``)
    build the benchmark series with ``close.pct_change()``, which leaves a
    NaN at the first aligned observation.  Before this fix that NaN
    propagated through np.mean/sxx/sxy into alpha, beta, correlation and
    the t-statistic, so every benchmark whose return series started at the shared
    window start produced NaN alpha/beta and no p-value at all — a silent
    methodological defect that affected the non-splits path (the splits path
    was fixed separately in walk_forward.py).
    """
    dates = pd.date_range("2020-01-01", periods=60, freq="B")
    rng = np.random.default_rng(42)
    strat = pd.Series(rng.normal(0.001, 0.02, 60), index=dates)
    # Simulate _compute_benchmark_returns: pct_change leaves a leading NaN.
    bench = pd.Series(np.r_[np.nan, rng.normal(0.001, 0.02, 59)], index=dates)

    stats = _benchmark_stats(strat, bench, 252.0)
    assert np.isfinite(stats["alpha"]), f"alpha must be finite, got {stats['alpha']}"
    assert np.isfinite(stats["beta"]), f"beta must be finite, got {stats['beta']}"
    assert np.isfinite(stats["correlation_with_benchmark"])
    assert "alpha_pvalue" in stats
    assert np.isfinite(stats["alpha_pvalue"]), f"alpha_pvalue must be finite, got {stats['alpha_pvalue']}"
    assert np.isfinite(stats["alpha_tstat"])
    assert 0.0 <= stats["alpha_pvalue"] <= 1.0
    assert 0.0 <= stats["r_squared"] <= 1.0


def _make_two_benchmark_metrics() -> dict:
    """Build a metrics dict shaped like the run_backtest CLI multi-benchmark path.

    ``calculate_metrics`` emits per-benchmark stats for the multi-benchmark
    path as ``benchmark_{i}_*`` prefixed scalar keys plus an aggregate
    ``deflated_alpha`` dict. This helper reproduces that shape deterministically
    so the text-report regression tests do not depend on a full backtest run.
    """
    return {
        "total_return": 0.10,
        "total_trades": 5,
        "benchmark_0_alpha": 0.02,
        "benchmark_0_beta": 1.1,
        "benchmark_0_correlation_with_benchmark": 0.85,
        "benchmark_0_alpha_pvalue": 0.08,
        "benchmark_0_alpha_pvalue_original": 0.06,
        "benchmark_0_deflated_alpha": 0.5,
        "benchmark_0_expected_max_alpha": 0.04,
        "benchmark_1_alpha": 0.01,
        "benchmark_1_beta": 0.9,
        "benchmark_1_correlation_with_benchmark": 0.7,
        "benchmark_1_alpha_pvalue": 0.09,
        "benchmark_1_alpha_pvalue_original": 0.07,
        "benchmark_1_deflated_alpha": 0.6,
        "benchmark_1_expected_max_alpha": 0.05,
        "deflated_alpha": {
            "deflated_alpha_ratio": 0.5,
            "p_value": 0.08,
            "n_benchmarks": 2,
        },
    }


def test_generate_report_surfaces_per_benchmark_comparison_when_multiple_benchmarks():
    """The text report renders a Per-Benchmark Comparison section for 2+ benchmarks.

    The HTML tear sheet and JSON summary already surface per-benchmark Deflated
    Alpha metrics (alpha_pvalue, alpha_pvalue_original, deflated_alpha,
    expected_max_alpha) for the multi-benchmark run_backtest CLI path; the text
    report was the one consumer that only carried the aggregate DAR. This is a
    regression guard that the per-benchmark rows are rendered and that the
    corrected p-value fields are surfaced per benchmark.
    """
    import tempfile

    metrics = _make_two_benchmark_metrics()
    with tempfile.TemporaryDirectory() as tmpdir:
        generate_report(metrics, tmpdir, symbol="SPY", strategy_name="SMA")
        with open(Path(tmpdir) / "report.txt") as f:
            content = f.read()

    assert "Per-Benchmark Comparison" in content
    assert "Benchmark 0" in content
    assert "Benchmark 1" in content
    # Corrected p-value fields are surfaced per benchmark, not just the
    # aggregate deflated_alpha dict.
    assert "0.0800" in content  # benchmark_0 alpha_pvalue
    assert "0.0900" in content  # benchmark_1 alpha_pvalue
    assert "0.5000" in content  # benchmark_0 deflated_alpha
    assert "0.6000" in content  # benchmark_1 deflated_alpha
    assert "0.0400" in content  # benchmark_0 expected_max_alpha
    assert "0.0500" in content  # benchmark_1 expected_max_alpha


def test_generate_report_omits_per_benchmark_section_for_single_benchmark():
    """Without multiple benchmarks, no Per-Benchmark Comparison section renders.

    Backward compatible: single-benchmark runs keep the non-prefixed
    ``alpha`` / ``beta`` / ``correlation_with_benchmark`` keys in the existing
    Benchmark Comparison section and emit no per-benchmark rows.
    """
    import tempfile

    metrics = {
        "total_return": 0.10,
        "benchmark_total_return": 0.12,
        "benchmark_annualized_return": 0.18,
        "correlation_with_benchmark": 0.85,
        "alpha": 0.02,
        "beta": 1.1,
        "alpha_tstat": 1.9,
        "alpha_pvalue": 0.06,
        "r_squared": 0.72,
        "deflated_alpha": {
            "deflated_alpha_ratio": 0.5,
            "p_value": 0.08,
            "n_benchmarks": 1,
        },
    }
    with tempfile.TemporaryDirectory() as tmpdir:
        generate_report(metrics, tmpdir, symbol="SPY", strategy_name="SMA")
        with open(Path(tmpdir) / "report.txt") as f:
            content = f.read()

    assert "Benchmark Comparison" in content
    assert "Per-Benchmark Comparison" not in content
    assert "Benchmark 0" not in content


def test_generate_report_omits_per_benchmark_section_without_benchmarks():
    """Without any benchmark metrics, no benchmark sections render."""
    import tempfile

    metrics = {"total_return": 0.10, "total_trades": 5}
    with tempfile.TemporaryDirectory() as tmpdir:
        generate_report(metrics, tmpdir, symbol="SPY", strategy_name="SMA")
        with open(Path(tmpdir) / "report.txt") as f:
            content = f.read()

    assert "Per-Benchmark Comparison" not in content
    assert "Benchmark Comparison" not in content


def test_main_registers_every_module_level_test():
    """main() must register every module-level ``test_*`` function.

    Regression guard for a defect where a test function was defined after
    the ``if __name__ == "__main__"`` block (and therefore unreachable at
    runtime) yet omitted from the registry, so the suite reported a lower
    count than the number of tests actually defined. A test defined but
    never registered is dead code: it cannot fail, so it provides no
    coverage of the feature it targets.

    The check is structural: every callable named ``test_*`` at module
    scope must appear in ``TEST_REGISTRY``, and every registry entry must
    be a real module-level function. No test is executed here.
    """
    import inspect

    module_tests = {
        obj
        for name, obj in list(globals().items())
        if name.startswith("test_")
        and inspect.isfunction(obj)
        and obj.__module__ == __name__
    }
    registered = {fn for _, fn in TEST_REGISTRY}

    missing = module_tests - registered
    assert not missing, (
        f"test functions defined but not registered in TEST_REGISTRY: "
        f"{sorted(f.__name__ for f in missing)}. A test outside the "
        "runner is dead code and provides no coverage."
    )
    phantom = registered - module_tests
    assert not phantom, (
        f"entries in TEST_REGISTRY that are not module-level test_* "
        f"functions: {sorted(f.__name__ for f in phantom)}"
    )
    # Labels must be unique so the runner cannot silently skip a test
    # (duplicate labels would overwrite each other in a name->fn map).
    labels = [name for name, _ in TEST_REGISTRY]
    assert len(labels) == len(set(labels)), (
        f"TEST_REGISTRY has duplicate labels: "
        f"{[l for l in labels if labels.count(l) > 1]}"
    )


# Module-level registry of (label, callable) pairs. Kept at module scope
# (rather than a local inside main()) so structural checks like
# ``test_main_registers_every_module_level_test`` can introspect it
# without executing the suite.
TEST_REGISTRY = [
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
    ("alpha_sign_flip_between_benchmark_modes", test_alpha_sign_flip_between_benchmark_modes),
    ("benchmark_stats_applies_periodic_benchmark_costs", test_benchmark_stats_applies_periodic_benchmark_costs),
    ("calculate_metrics_deflated_alpha_multiple_benchmarks", test_calculate_metrics_deflated_alpha_multiple_benchmarks),
    ("calculate_metrics_no_deflated_alpha_without_benchmark", test_calculate_metrics_no_deflated_alpha_without_benchmark),
    ("calculate_metrics_deflated_alpha_single_benchmark", test_calculate_metrics_deflated_alpha_single_benchmark),
    ("benchmark_stats_drops_leading_nan_from_pct_change", test_benchmark_stats_drops_leading_nan_from_pct_change),
    ("generate_report_surfaces_per_benchmark_comparison_when_multiple_benchmarks", test_generate_report_surfaces_per_benchmark_comparison_when_multiple_benchmarks),
    ("generate_report_omits_per_benchmark_section_for_single_benchmark", test_generate_report_omits_per_benchmark_section_for_single_benchmark),
    ("generate_report_omits_per_benchmark_section_without_benchmarks", test_generate_report_omits_per_benchmark_section_without_benchmarks),
    ("main_registers_every_module_level_test", test_main_registers_every_module_level_test),
]


def main() -> int:
    tests = TEST_REGISTRY

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

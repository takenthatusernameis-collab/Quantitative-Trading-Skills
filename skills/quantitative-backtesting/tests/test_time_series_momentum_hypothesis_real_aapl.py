#!/usr/bin/env python3
"""Falsifiable hypothesis test for standalone time-series momentum (TSMOM) on
the committed single-asset panel (AAPL).

Runs run_hypothesis_test(...) as a walk-forward evaluation (train 24 / test 12
/ step 12 months) with a pre-registered lookback grid (126, 189, 252 trading
days, N=3 trials) at 3 bps round-trip costs.

PRE-REGISTERED FALSIFICATION CRITERIA (pinned before results were inspected):
1. oos_sharpe > 0 (net of costs)
2. oos_total_return > 0 (net of costs)
3. deflated_sharpe_pvalue < 0.10 (multiple-testing corrected)

METHODOLOGICAL FINDING (committed fixtures only, not evidence about any market):
the pooled out-of-sample Sharpe is negative (-0.3885), the total return is
negative (-5.98%), and the Deflated Sharpe p-value (0.9746, 5 trials) is far
above 0.10, so the hypothesis is NOT SUPPORTED. All three criteria fail. The
test does not tune parameters or criteria to force SUPPORT.

This test pins the observed out-of-sample metrics (net of costs) as regression
guards with relative tolerance so any silent change to the backtest numbers is
caught. It also asserts the verdict stays NOT SUPPORTED.

Offline, committed fixtures only; no live network.
"""
import contextlib
import io
import sys
from pathlib import Path

SKILLS_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SKILLS_DIR / "scripts"))
sys.path.insert(0, str(SKILLS_DIR / "examples"))

from time_series_momentum_hypothesis import (  # noqa: E402
    CRITERIA,
    run_hypothesis_test,
)

SRC = SKILLS_DIR / "assets" / "example_data" / "real_market_data"


def test_hypothesis_time_series_momentum_runs_on_aapl_real_window():
    assert (SRC / "AAPL.csv").exists()

    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        result = run_hypothesis_test(
            data_path=SRC / "AAPL.csv",
            label="TSMOM (12m lookback grid) on AAPL, walk-forward",
        )

    assert isinstance(result, dict)
    assert result["verdict"] in ("SUPPORTED", "NOT SUPPORTED")
    assert result["all_pass"] in (True, False)
    assert result["all_pass"] == all(c["passed"] for c in result["criteria"])
    assert result["verdict"] == ("SUPPORTED" if result["all_pass"] else "NOT SUPPORTED")
    assert len(result["criteria"]) == len(CRITERIA) == 3
    assert {c["name"] for c in result["criteria"]} == {
        "oos_sharpe_gt_zero",
        "oos_total_return_positive",
        "deflated_sharpe_pvalue_lt_0.10",
    }
    out = buffer.getvalue()
    assert "VERDICT:" in out
    assert "FALSIFIABLE HYPOTHESIS TEST" in out
    assert "Point-in-time validation passed" in out


def test_hypothesis_metrics_pinned_on_aapl_real_window():
    """Regression guard: the TSMOM walk-forward on committed AAPL must reproduce
    the pinned out-of-sample metrics (net of costs). Relative tolerance only.

    Honest outcome: all three criteria fail -> verdict NOT SUPPORTED.
    """
    assert (SRC / "AAPL.csv").exists()

    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        result = run_hypothesis_test(
            data_path=SRC / "AAPL.csv",
            label="TSMOM (12m lookback grid) on AAPL, walk-forward",
        )

    assert result["verdict"] == "NOT SUPPORTED"
    assert result["all_pass"] is False

    expected_criteria = {
        "oos_sharpe_gt_zero": False,
        "oos_total_return_positive": False,
        "deflated_sharpe_pvalue_lt_0.10": False,
    }
    for c in result["criteria"]:
        assert c["passed"] == expected_criteria[c["name"]], (
            f"criterion {c['name']} unexpected: got {c['passed']}, "
            f"expected {expected_criteria[c['name']]}"
        )

    observed = result.get("observed") or {}
    EXPECTED = {
        "oos_sharpe": -0.38851059506816554,
        "oos_volatility": 0.09366510608397208,
        "total_oos_return": -0.05984304746520375,
        "n_periods": 3,
        "periods_with_position": 3,
        "deflated_sharpe_ratio": 0.025448731470486596,
        "deflated_sharpe_pvalue": 0.9745512685295135,
        "n_trials": 5,
    }
    REL_TOL = 1e-6
    for key, exp in EXPECTED.items():
        assert key in observed, f"missing observed metric {key}"
        got = observed[key]
        assert got is not None, f"metric {key} unexpectedly None"
        if isinstance(exp, int):
            assert int(got) == exp, f"metric {key} drifted: got {got}, expected {exp}"
        else:
            assert abs(got - exp) <= REL_TOL * max(abs(exp), 1e-9), (
                f"metric {key} drifted: got {got}, expected {exp}"
            )

    out = buffer.getvalue()
    assert "Point-in-time validation passed" in out


if __name__ == "__main__":
    test_hypothesis_time_series_momentum_runs_on_aapl_real_window()
    test_hypothesis_metrics_pinned_on_aapl_real_window()
    print("OK")

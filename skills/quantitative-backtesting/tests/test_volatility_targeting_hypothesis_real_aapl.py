#!/usr/bin/env python3
"""Falsifiable hypothesis test for volatility targeting on the committed
single-asset panel (AAPL).

Runs run_hypothesis_test(...) (no benchmark) using the pre-registered
advertised costs (3 bps round-trip) and the two weak falsification criteria:
oos_sharpe > 0 and oos_total_return > 0 (net of costs).

METHODOLOGICAL FINDING (committed fixtures only, not evidence about any market):
volatility targeting beats a zero baseline (Sharpe 0.77, return 47.4% net of
3bp round-trip costs), so the weak two-criterion hypothesis is SUPPORTED.
This is consistent with the benchmark-aware guard
(test_volatility_targeting_benchmark_aware_real_aapl.py), which records NOT
SUPPORTED: the strategy does not beat buy-and-hold AAPL (return 47.4% vs
77.4%) and neither the benchmark alpha nor the Deflated Sharpe p-value is
significant. The two verdicts are reported honestly -- weak-criterion support
vs a zero baseline does not imply benchmark-beating performance.

This test pins the observed out-of-sample metrics (net of costs) as regression
guards with relative tolerance so any silent change to the backtest numbers is
caught. It also asserts the verdict stays SUPPORTED: any future change that
alters the pinned metrics or flips the verdict fails this test.

Offline, committed fixtures only; no live network.
"""
import contextlib
import io
import sys
from pathlib import Path

SKILLS_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SKILLS_DIR / "scripts"))
sys.path.insert(0, str(SKILLS_DIR / "examples"))

from volatility_targeting_hypothesis import (  # noqa: E402
    CRITERIA,
    run_hypothesis_test,
)

SRC = SKILLS_DIR / "assets" / "example_data" / "real_market_data"


def test_hypothesis_volatility_targeting_runs_on_aapl_real_window():
    assert (SRC / "AAPL.csv").exists()

    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        result = run_hypothesis_test(
            data_path=SRC / "AAPL.csv",
            label="volatility targeting on AAPL (real window, advertised 3bp costs)",
            benchmark_path=None,
            n_trials=None,
        )

    assert isinstance(result, dict)
    assert result["verdict"] in ("SUPPORTED", "NOT SUPPORTED")
    assert result["all_pass"] in (True, False)
    assert result["all_pass"] == all(c["passed"] for c in result["criteria"])
    assert result["verdict"] == ("SUPPORTED" if result["all_pass"] else "NOT SUPPORTED")
    assert len(result["criteria"]) == len(CRITERIA) == 2
    assert {c["name"] for c in result["criteria"]} == {
        "oos_sharpe_gt_zero",
        "oos_total_return_positive",
    }
    out = buffer.getvalue()
    assert "VERDICT:" in out
    assert "FALSIFIABLE HYPOTHESIS TEST" in out


def test_hypothesis_metrics_pinned_on_aapl_real_window():
    """Regression guard: the weak-criterion run on committed AAPL must
    reproduce the pinned out-of-sample metrics (net of costs) so a silent
    change to the backtest numbers is caught. Relative tolerance only, never
    exact equality (last decimals depend on the numpy/pandas build).

    The verdict is pinned as SUPPORTED (weak criteria vs a zero baseline).
    This is deliberately NOT the benchmark-aware verdict (NOT SUPPORTED):
    weak-criterion support is consistent with failing to beat buy-and-hold.
    """
    assert (SRC / "AAPL.csv").exists()

    result = run_hypothesis_test(
        data_path=SRC / "AAPL.csv",
        label="volatility targeting on AAPL (real window, advertised 3bp costs)",
        benchmark_path=None,
        n_trials=None,
    )

    assert result["verdict"] == "SUPPORTED"
    assert result["all_pass"] is True
    for c in result["criteria"]:
        assert c["passed"] is True, f"criterion {c['name']} unexpectedly failed"

    observed = result.get("observed") or {}
    EXPECTED = {
        "sharpe_ratio": 0.7710596325955302,
        "total_return": 0.4736842323382433,
        "benchmark_total_return": None,
        "benchmark_alpha": None,
        "benchmark_alpha_pvalue": None,
        "correlation_with_benchmark": None,
        "deflated_sharpe_pvalue": None,
        "n_trials": None,
        "benchmark_path": None,
    }
    REL_TOL = 1e-3
    for key, exp in EXPECTED.items():
        assert key in observed, f"missing observed metric {key}"
        got = observed[key]
        if exp is None:
            assert got is None, f"metric {key} should be None, got {got!r}"
            continue
        assert got is not None, f"metric {key} unexpectedly None"
        assert abs(got - exp) <= abs(exp) * REL_TOL, (
            f"metric {key} drifted: got {got}, expected {exp}"
        )

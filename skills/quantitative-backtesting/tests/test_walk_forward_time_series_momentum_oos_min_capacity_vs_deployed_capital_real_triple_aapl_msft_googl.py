#!/usr/bin/env python3
"""OOS-min-capacity vs deployed-capital sensitivity report for TSMOM on committed triple panel."""
import contextlib
import io
import sys
from pathlib import Path

SKILLS_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SKILLS_DIR / "examples"))

from time_series_momentum_hypothesis import (  # noqa: E402
    CAPACITY_SENSITIVITY_LEVELS,
    DEPLOYED_CAPITAL_REFERENCE,
    run_oos_min_capacity_vs_deployed_capital_report,
)


def test_report_runs_on_triple_real_window_time_series_momentum():
    for name in ("AAPL.csv", "MSFT.csv", "GOOGL.csv"):
        assert (SKILLS_DIR / "assets" / "example_data" / "real_market_data" / name).exists()

    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        report = run_oos_min_capacity_vs_deployed_capital_report()

    assert isinstance(report, list) and len(report) == len(CAPACITY_SENSITIVITY_LEVELS)
    assert report[0]["impact_coefficient"] == 0.0
    assert report[0]["oos_min_capacity"] is None
    assert report[0]["capacity_constrained"] is None
    assert report[0]["flag"] == "UNMEASURABLE (impact off)"
    for r in report[1:]:
        assert r["deployed_capital"] == DEPLOYED_CAPITAL_REFERENCE
        assert r["flag"] in ("CAPACITY-CONSTRAINED", "NOT CAPACITY-CONSTRAINED")
        assert r["capacity_constrained"] == (r["flag"] == "CAPACITY-CONSTRAINED")

    out = buffer.getvalue()
    assert "CAPACITY-CONSTRAINED" in out or "NOT CAPACITY-CONSTRAINED" in out


if __name__ == "__main__":
    test_report_runs_on_triple_real_window_time_series_momentum()
    print("OK")

#!/usr/bin/env python3
import contextlib
import io
import sys
import tempfile
from pathlib import Path

import pandas as pd

SKILLS_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SKILLS_DIR / "scripts"))
sys.path.insert(0, str(SKILLS_DIR / "examples"))

from zscore_mean_reversion_hypothesis import (  # noqa: E402
    COMMISSION,
    SLIPPAGE,
    PARAM_SENSITIVITY_GRID,
    run_param_sensitivity_sweep,
)

SRC = SKILLS_DIR / "assets" / "example_data" / "real_market_data"


def _build_pair_csv(dest: Path) -> Path:
    aapl = pd.read_csv(SRC / "AAPL.csv")
    googl = pd.read_csv(SRC / "GOOGL.csv")
    aapl["symbol"] = "AAPL"
    googl["symbol"] = "GOOGL"
    combined = pd.concat([aapl, googl], ignore_index=True)
    out = dest / "aapl_googl_pair.csv"
    combined.to_csv(out, index=False)
    return out


def test_param_sensitivity_runs_on_aapl_googl_real_window():
    assert (SRC / "AAPL.csv").exists()
    assert (SRC / "GOOGL.csv").exists()

    with tempfile.TemporaryDirectory() as td:
        d = Path(td)
        data_path = _build_pair_csv(d)
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            rows = run_param_sensitivity_sweep(data_path)

    assert isinstance(rows, list) and len(rows) == len(PARAM_SENSITIVITY_GRID)
    for r, (period, entry_z, exit_z) in zip(rows, PARAM_SENSITIVITY_GRID):
        assert r["period"] == period
        assert r["entry_z"] == entry_z
        assert r["exit_z"] == exit_z
        assert r["commission"] == COMMISSION
        assert r["slippage"] == SLIPPAGE
        assert r["commission_bps"] == COMMISSION * 10_000
        assert r["slippage_bps"] == SLIPPAGE * 10_000
        assert r["verdict"] in ("SUPPORTED", "NOT SUPPORTED")
        assert r["all_pass"] == all(c["passed"] for c in r["criteria"])
        assert r["verdict"] == ("SUPPORTED" if r["all_pass"] else "NOT SUPPORTED")
        assert len(r["criteria"]) == 2
        assert {c["name"] for c in r["criteria"]} == {
            "oos_sharpe_gt_zero",
            "oos_total_return_positive",
        }
    out = buffer.getvalue()
    assert "PARAMETER SENSITIVITY SWEEP" in out
    assert "VERDICT" in out

    # Regression guard: pin the observed out-of-sample metrics per parameter
    # setting so the robustness evidence is reproducible and any silent change
    # to the backtest numbers is caught. Compared with a relative tolerance.
    # NOTE: the advertised baseline (20, 2.0, 0.5) is NOT SUPPORTED on this
    # window, and one perturbed setting (20, 2.5, 0.5) happens to clear both
    # weak criteria. Verdict flips across the grid are the signal that the
    # result is not robust to small parameter changes -- this is sensitivity
    # evidence, not a profitability claim, and no setting is tuned to force a
    # particular outcome.
    EXPECTED_METRICS = {
        (20, 2.0, 0.5): {
            "sharpe_ratio": -0.4256114742108271,
            "total_return": -0.030959664968179257,
        },
        (20, 1.5, 0.5): {
            "sharpe_ratio": -0.8618415086703106,
            "total_return": -0.11133986900980664,
        },
        (20, 2.5, 0.5): {
            "sharpe_ratio": 0.7913836712709592,
            "total_return": 0.11160662522322795,
        },
        (20, 2.0, 0.3): {
            "sharpe_ratio": -0.40120821787504435,
            "total_return": -0.03128264779111278,
        },
        (20, 2.0, 0.7): {
            "sharpe_ratio": -0.23944584663140164,
            "total_return": -0.0006439866448758602,
        },
        (15, 2.0, 0.5): {
            "sharpe_ratio": -0.682529049918234,
            "total_return": -0.06780720583825284,
        },
    }
    REL_TOL = 1e-3
    for r in rows:
        key = (r["period"], r["entry_z"], r["exit_z"])
        assert key in EXPECTED_METRICS, f"unexpected parameter setting {key}"
        exp = EXPECTED_METRICS[key]
        for k, expv in exp.items():
            assert k in r, f"missing {k} at {key}"
            gotv = r[k]
            assert abs(gotv - expv) <= REL_TOL * max(abs(expv), 1e-9), (
                f"{k} regression at {key}: got {gotv}, expected {expv}"
            )


if __name__ == "__main__":
    test_param_sensitivity_runs_on_aapl_googl_real_window()
    print("OK")

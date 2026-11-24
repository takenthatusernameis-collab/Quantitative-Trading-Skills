"""Capacity-aware sizing opt-in guard for run_backtest.py.

Offline, committed single-asset fixture only (AAPL.csv). No live network.

Semantics verified here:
  (a) Opt-in: running WITHOUT --max-impact leaves published numbers
      (total_return, sharpe_ratio) unchanged relative to a loose, non-binding
      cap with identical other args. No published number moves unless the flag
      is set AND the cap actually binds.
  (b) Binding cap: a tight --max-impact (1e-5 at --impact-coefficient 1.0)
      scales realized position changes, so realized returns differ from the
      uncapped run. The reported capacity estimate is unchanged: --max-impact
      is a position-sizing cap, not a capacity modifier. Capacity is estimated
      from ADV / impact_coefficient / costs (see run_backtest.py estimate_capacity)
      independently of the realized, capped positions, so it must not move when
      the cap is tightened.

Historical note: an earlier revision of this test asserted
``capped_capacity < uncapped_capacity``. That is impossible by construction
(--max-impact never feeds estimate_capacity) and additionally used non-binding
parameters (1e-4 at ic=1.0 does not bind), so it failed. Corrected below.
"""
import json
import subprocess
import sys
import tempfile
from pathlib import Path

SKILLS_DIR = Path(__file__).resolve().parent.parent
SCRIPT = SKILLS_DIR / "scripts" / "run_backtest.py"
DATA = SKILLS_DIR / "assets" / "example_data" / "real_market_data" / "AAPL.csv"


def _run(out: Path, max_impact=None, impact_coefficient=1.0):
    cmd = [
        sys.executable, str(SCRIPT),
        "--data", str(DATA),
        "--strategy", "sma_crossover",
        "--symbol", "AAPL",
        "--impact-coefficient", str(impact_coefficient),
        "--commission", "0.0002",
        "--slippage", "0.0001",
        "--output", str(out),
    ]
    if max_impact is not None:
        cmd += ["--max-impact", str(max_impact)]
    return subprocess.run(cmd, capture_output=True, text=True)


def test_capacity_optin_guard():
    assert DATA.exists(), f"Committed fixture not found: {DATA}"

    with tempfile.TemporaryDirectory() as d1, \
         tempfile.TemporaryDirectory() as d2, \
         tempfile.TemporaryDirectory() as d3:

        # (a) Opt-in: loose cap (1.0, non-binding) must not move published
        # numbers relative to a run with no --max-impact at all.
        r_loose = _run(Path(d1), max_impact=1.0)
        r_unset = _run(Path(d2))
        assert r_loose.returncode == 0, r_loose.stderr
        assert r_unset.returncode == 0, r_unset.stderr
        s_loose = json.loads((Path(d1) / "tear_sheet_summary.json").read_text())
        s_unset = json.loads((Path(d2) / "tear_sheet_summary.json").read_text())
        assert s_loose["metrics"]["total_return"] == s_unset["metrics"]["total_return"]
        assert s_loose["metrics"]["sharpe_ratio"] == s_unset["metrics"]["sharpe_ratio"]

        # (b) Binding cap: 1e-5 at ic=1.0 binds (empirically: return
        # 1.089946 -> 1.030948, trades 17 -> 32). Realized returns must differ
        # from the uncapped run; the capacity estimate must not move.
        r_cap = _run(Path(d3), max_impact=1e-5, impact_coefficient=1.0)
        assert r_cap.returncode == 0, r_cap.stderr
        s_cap = json.loads((Path(d3) / "tear_sheet_summary.json").read_text())
        assert s_cap["metrics"]["total_return"] != s_unset["metrics"]["total_return"], (
            "binding cap did not change realized returns: "
            f"capped={s_cap['metrics']['total_return']} "
            f"uncapped={s_unset['metrics']['total_return']}"
        )
        # --max-impact is a position-sizing cap only: capacity is unchanged.
        assert s_cap["metrics"]["capacity"] == s_unset["metrics"]["capacity"], (
            "--max-impact must not alter the reported capacity estimate: "
            f"capped={s_cap['metrics']['capacity']} "
            f"uncapped={s_unset['metrics']['capacity']}"
        )

        print("OPT-IN GUARD PASSED: loose cap == unset (no published-number movement)")
        print(
            "BINDING CAP GUARD PASSED: realized return changed; "
            f"capacity unchanged={s_cap['metrics']['capacity']}"
        )


if __name__ == "__main__":
    test_capacity_optin_guard()
    print("OK")

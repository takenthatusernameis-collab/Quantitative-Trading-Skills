import contextlib, io, shutil, sys, tempfile
from pathlib import Path
SKILLS_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SKILLS_DIR / "examples"))
from rsi_mean_reversion_hypothesis import PARAM_SENSITIVITY_GRID, run_param_sensitivity_sweep
SRC = SKILLS_DIR / "assets" / "example_data" / "real_market_data"

def test_param_sensitivity_runs_on_msft_googl_real_window():
    assert (SRC / "MSFT.csv").exists()
    assert (SRC / "GOOGL.csv").exists()
    with tempfile.TemporaryDirectory() as td:
        d = Path(td)
        shutil.copyfile(SRC / "MSFT.csv", d / "sample_ohlcv.csv")
        shutil.copyfile(SRC / "GOOGL.csv", d / "sample_benchmark.csv")
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            rows = run_param_sensitivity_sweep(d / "sample_ohlcv.csv")
    assert isinstance(rows, list) and len(rows) == len(PARAM_SENSITIVITY_GRID)

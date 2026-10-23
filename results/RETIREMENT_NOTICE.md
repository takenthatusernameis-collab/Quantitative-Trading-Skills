# Retirement Notice - Legacy Results Artifacts

These artifacts in `/results/` (root) are **NOT REPRODUCIBLE** and are retained only for historical reference.

- Input data file `splits_test_data.csv` referenced by `data_provenance.json` and `benchmark_provenance.json` is not present in this repository and cannot be reconstructed from provenance metadata alone.
- The artifacts were generated on 2026-10-14 from that missing input file.
- Per the repository's quantitative research methodology requirements, unverified/incomplete artifacts must not be cited as evidence of strategy performance.
- `results/resolution_floor/*.json` cost sweeps are unaffected - they remain reproducible from their own scripts.
- Any future regeneration would require restoring the original `splits_test_data.csv` input data and running `skills/quantitative-backtesting/scripts/run_backtest.py` against it with the same parameters.

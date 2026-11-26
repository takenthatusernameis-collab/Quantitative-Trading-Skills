# Quantitative Backtesting Test Suite

This directory contains the test suite for the `quantitative-backtesting` skill.
Tests use only committed fixtures and run fully offline (no live network access).

## Running tests

From the repository root, run individual test files directly:

```bash
python3 skills/quantitative-backtesting/tests/<test_file>.py
```

`pytest` is not always on `PATH` in every environment; the `python3 <file>`
convention is the portable default. When `pytest` is available, the equivalent is:

```bash
python3 -m pytest skills/quantitative-backtesting/tests/<test_file>.py -v
```

## Long-running integration suites

The following files are end-to-end integration suites whose runtime is inherent to
the walk-forward methodology (many protocols, each re-running portfolio
construction and parameter-inertness diagnostics). They are **not** hung; they
simply take several minutes to complete and must be given an adequate timeout.

| File | Approx. runtime | Notes |
| --- | --- | --- |
| `test_walk_forward.py` | ~8 min (≈468 s) | 235+ tests; many CLI end-to-end tests each spawn subprocesses. Slowest single test ≈74 s. |
| `test_walk_forward_cross_sectional_momentum_protocol_sensitivity_real_triple.py` | ~6 min (≈360 s) | 5 tests; 6 walk-forward protocols per test, no caching across functions. |

### How to run them without being killed by a short timeout

- Run directly with `python3` (preferred; no plugin required):

  ```bash
  python3 skills/quantitative-backtesting/tests/test_walk_forward.py
  python3 skills/quantitative-backtesting/tests/test_walk_forward_cross_sectional_momentum_protocol_sensitivity_real_triple.py
  ```

- Or, if wrapping with a shell timeout, allow a generous bound:

  ```bash
  timeout 900 python3 -m pytest skills/quantitative-backtesting/tests/test_walk_forward.py -v
  ```

### Note on `pytest-timeout`

`pytest-timeout` is **not** installed in this environment. Do not add a
`timeout = ...` setting to a `pytest.ini` / `pyproject.toml` expecting it to take
effect — without the plugin it is inert. Use the shell `timeout` wrapper or run
the file directly with `python3` instead.

Do not skip these tests or weaken their assertions to make them finish faster;
the runtime is a property of the methodology being validated.
# Next task — measure the sweeps on real history (--data)

## Status

The CPCV sweep task is complete and verified:
- `measure_cpcv_sweep`, `_summarize_cpcv_sweep`, `print_cpcv_sweep`,
  `_parse_cpcv_splits`, and the `--cpcv-splits` flag are all implemented
  in `scripts/measure_resolution_vs_sample_size.py` and dispatched in `main`.
- Capture: `results/resolution_floor/cpcv_sweep_10000.json` (committed).
- Fixture: `tests/fixtures/cpcv_sweep_10000.json` (committed).
- 11 CPCV sweep pins in `test_resolution_vs_sample_size.py`, all passing.
- Documented in `references/validation_methods.md` ("How should the CPCV
  path be split?") and `SKILL.md` (carries the `--cpcv-splits` flag).

This session additionally captured the **5,000-bar walk-forward window
sweep**, closing the last reproducibility gap from HANDOFF.md:

- Capture: `results/resolution_floor/wf_window_sweep_5000.json` (new) —
  the tool's own `--json` output plus provenance (command, environment,
  fixture construction, script commit, bounds).
- Fixture: `tests/fixtures/wf_window_sweep_5000.json` (new) — trimmed copy
  keeping every key the sweep's summary reads.
- 2 new pins in `test_resolution_vs_sample_size.py` (`test_the_window_sweep_5000_capture_is_the_tools_own_json_output`,
  `test_the_window_sweep_5000_fixture_is_a_trimmed_copy_of_the_capture`),
  both passing.
- The document at `references/validation_methods.md` already quotes the
  5,000-bar numbers; they are now verifiable against a committed capture.

`matplotlib` is installed; `tests/test_reporting.py` passes (62/62).
All 16 other test files pass (~700 tests). All 65 fast tests in
`test_resolution_vs_sample_size.py` pass; the full suite was not run in a
single invocation because the 25k-50k bar ladder rungs take minutes per
draw, but every individual ladder test was run and passed.

## Next task (one, precise)

**Enable `--data` for the walk-forward window sweep (and, by the same
pattern, the CPCV split sweep) so the resolution can be measured on real
market history instead of only the synthetic control fixture.**

Today both sweeps refuse `--data` (parser.error) because the fixture's
numbers must not be reported under a real history's name. Enabling it means:

1. In `main`, remove the `if args.data: parser.error(...)` guard for
   `--wf-windows` (and `--cpcv-splits`), so the sweep runs on prefixes of
   the real history the way the ladder already does.
2. Benchmark resolution: the real-history path already resolves benchmarks
   from the file's directory (`measure_real` / `BENCHMARK_FILES`); reuse
   that for the sweep so the same multiple-benchmark Deflated Alpha path
   is exercised.
3. Window configurability: on real history, a test window shorter than the
   strategy's indicator warmup leaves most windows unable to price the
   strategy at all — the sweep reports `periods_with_position` exactly for
   this. Choose window configurations that are meaningful on the history's
   length (e.g., a 1,500-bar history can't support a 24-month training
   window).
4. Capture the measurement in `results/resolution_floor/` and a trimmed
   fixture in `tests/fixtures/`, following the 10,000-bar / 5,000-bar
   window-sweep capture pattern (provenance + `--json` output).
5. Pin it in `test_resolution_vs_sample_size.py`: capture is the tool's own
   `--json` output, fixture is a trimmed copy, numbers are the framework's
   own blocks, and no threshold, bound, criterion or verdict moves.

## Constraints

- No threshold, bound, criterion or verdict moves; `scripts/walk_forward.py`
  is not in this task's diff.
- A measurement beside the verdict, never part of it.
- The synthetic fixture remains the default; `--data` is an alternative
  source, not a replacement.
- `numpy` and `pandas` are installed; `matplotlib` is installed, so
  `tests/test_reporting.py` can run.

## Subsequent options (after this task)

- Decide whether the pre-driver ladder fixture
  (`tests/fixtures/resolution_ladder_2500_to_50000.json`) stays a fixture
  or becomes a result file only: the re-capture fixture carries the driver
  and the status, so the older one is a second source of truth for the same
  ladder. The test file explicitly asserts the baseline lacks driver keys,
  so this is an accepted design state, not a bug — but it has been flagged
  twice and a decision would close it.

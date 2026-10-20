# HANDOFF_NEXT

## Next task: make the thin-evidence measurement actionable

### Why

The `thin_evidence_warning` added this session (HANDOFF.md) is a measurement:
it tells a reader *how much evidence* a partial-selection verdict rests on, in
the artifact and the console, without changing a number. It is correct and
tested. But it is passive: a user who sees "the verdict rests on 2 folds that
each held a position for 6% of the executable bars" has to notice it, decide it
is too thin, and manually re-run with wider windows. Nothing enforces the
judgement.

The framework already has a fail-fast precedent for exactly this shape: invalid
`--latency` / `--fill-rate` values are rejected at the CLI boundary instead of
being swallowed by the per-combo try/except (`_resolve_latency_fill_rate`), and
the inert-grid measurement is surfaced as a warning next to the ranking it
qualifies. A run whose verdict rests on thin evidence should be able to be
*rejected* on the same basis, with a remedy that names the flags of the path
that produced it.

### The task

Add a `--min-position-fraction` flag (default `None`, no behaviour change) to
the three subcommands that can be in the partial state -- `cpcv`,
`walk-forward`, `out-of-sample` -- that fails the run when the
`thin_evidence_warning` it would emit has a
`details.min_position_fraction_of_executable` below the threshold, printing a
remedy that names the flags of the path that produced the windows.

Constraints:
- Default `None` must not change a single number on any existing case; the
  parity harnesses must still pass unchanged (the flag is opt-in).
- The failure must reuse `_selection_window_remedy` for the flag names, so the
  remedy is consistent with the partial-selection diagnosis's remedy.
- The failure must be written to the artifact too: the existing failure path
  (`out_of_sample_summary.json` / `walk_forward_summary.json` /
  `cpcv_summary.json`) already writes a `failure` record when a run cannot
  select parameters; the new failure should carry
  `summary["thin_evidence_warning"]` and a `thin_evidence_failure` key with the
  same `{cause, message, details}` shape, so a machine reader sees why the run
  was rejected.
- Guard with tests in `tests/test_no_selection_diagnosis.py`: a run whose
  verdict rests on the canonical 6%-of-executable-bars folds fails at
  `--min-position-fraction 0.1`, and the same run passes at the default; a run
  whose verdict rests on fully-traded windows (the shipped walk-forward run)
  passes at any threshold.

### Evidence to inspect first

- `skills/quantitative-backtesting/scripts/walk_forward.py`:
  - `_thin_evidence_warning` (added this session) -- the measurement to gate on.
  - `_selection_window_remedy` -- the shared remedy helper to reuse.
  - `_resolve_latency_fill_rate` -- the fail-fast precedent for flag validation.
  - The three CLI handlers `run_cpcv`, `run_walk_forward`, `run_out_of_sample`
    -- where the flag must be parsed and the check applied.
  - The existing failure-artifact writers (e.g. the `out_of_sample_summary.json`
    failure branch around line 8830) -- the shape to match.
- `skills/quantitative-backtesting/tests/test_no_selection_diagnosis.py` -- the
  seven tests for `thin_evidence_warning` that must keep passing, and the
  pattern the existing "no parameter could be selected" failure tests use.
- `/home/runner/work/_temp/kilo-tmp/kilo/parity_check.py`,
  `partial_parity.py`, `panel_parity.py` -- the parity harnesses; the new flag
  is opt-in so none of them should need changing, but re-run all three after.

### Definition of done

- `python3 skills/quantitative-backtesting/tests/test_no_selection_diagnosis.py`
  passes with the new tests added (30 + N).
- All 15 other test files in `skills/quantitative-backtesting/tests/` pass.
- `parity_check.py`, `partial_parity.py`, `panel_parity.py` and
  `parity_inert.py` all pass unchanged.
- The canonical partial case (`cpcv --n-splits 5 --test-size 0.2`) exits non-zero
  with `--min-position-fraction 0.1` and exits zero without it, and both write
  the same artifact numbers except for the new failure record.
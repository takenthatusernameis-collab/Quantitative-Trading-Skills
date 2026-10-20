# HANDOFF_NEXT

## Next task: report the test resolution in the framework's own verdicts (not
## only in the worked example)

### Why

This session proved the point in the worked example: with 100 test
observations, the Deflated Sharpe / Deflated Alpha thresholds require an
annualized Sharpe of ~4.20 and an annualized alpha of ~35-38%, so a
significance-style verdict on a small held-out window is mostly a statement
about the window, not about the strategy. The library's own aggregate
verdicts -- the walk-forward, CPCV and out-of-sample summaries that carry
`deflated_sharpe` and `deflated_alpha` -- still report those numbers with no
statement of what the sample could have detected at all. A reader of
`out_of_sample_summary.json` sees a p-value and a risk verdict and has no way
to tell an informative result from an unfalsifiable one.

The machinery already exists (this session added
`walk_forward.minimum_detectable_sharpe` / `minimum_detectable_alpha` /
`performance.t_critical_value`), so the remaining work is to wire it into the
three analysis paths and their CLI output.

### Scope (one path first, then the others)

Start with `out_of_sample_validation` (the path the example uses), then
`walk_forward_analysis` and `cpcv_analysis`:

1. In each path, compute a `summary["test_resolution"]` block from the
   aggregate `deflated_sharpe` / `deflated_alpha` and the test-window return
   series the statistic was computed on: `n_test_observations`,
   `n_parameter_trials` / `n_benchmarks`, `min_detectable_sharpe`,
   `min_detectable_alpha`, and the plausibility bounds used.
2. Print it next to the existing verdict in the CLI (`_print_*` helpers
   already exist for the partial-selection diagnosis and the thin-evidence
   warning -- follow that pattern, including the "measurement, not a
   correction" wording).
3. It must change **no** number. The block is reporting-only.

### Constraints

- The artifact shape changes (a new `summary` key). The previous session's
  parity harnesses lived in a temporary directory and are gone; rebuild them
  (HEAD vs working tree, ignoring reporting-only keys) before claiming
  parity, or state explicitly that the shape change is intentional and
  list every key added.
- `minimum_detectable_sharpe` / `minimum_detectable_alpha` return
  `attainable: False` with a `reason` when the statistic and the return
  series do not match (e.g. a CPCV path whose returns are not a single
  series). Handle that: report "not resolvable" rather than a number.
- Do not change the verdicts themselves, and do not re-threshold anything.

### Evidence to inspect first

- `skills/quantitative-backtesting/scripts/walk_forward.py`:
  `minimum_detectable_sharpe` (line ~2037), `minimum_detectable_alpha`
  (line ~2115), `_deflation_z_score` (line ~1969), and the three summary
  builders (`walk_forward_analysis`, `cpcv_analysis`,
  `out_of_sample_validation`).
- `skills/quantitative-backtesting/examples/falsifiable_hypothesis_example.py`:
  `_test_resolution` (line ~186) -- the reference implementation of the
  block and of the "beyond the sample's resolution" wording.
- `skills/quantitative-backtesting/references/validation_methods.md`: the new
  "Test Resolution (Minimum Detectable Effect)" section.
- `skills/quantitative-backtesting/tests/test_walk_forward.py`: the six new
  tests that pin the helpers.

### Alternative (if the above is too large for one session)

**A positive control for the falsifiable-hypothesis machinery.** The
resolution analysis shows analytically that the criteria need an annualized
Sharpe of ~4.2 at T=100, but nothing has yet *executed* the same machinery
against a series with a known effect to show the criteria can be met. Build
one: a synthetic series with a deliberately injected regime structure (so an
SMA crossover can beat buy-and-hold net of costs), long enough that T is
large enough for the deflated thresholds to be reachable, and assert that the
example's criteria evaluation returns SUPPORTED. Label it unmistakably as a
test-machinery check on synthetic data, never as evidence about a market.

### Definition of done

- One concrete change improving quant methodology quality, with the evidence
  that the change does what it claims.
- Tests updated/added and passing; the full `skills/quantitative-backtesting`
  suite green (except the pre-existing `test_reporting.py` failures, which
  are caused by `matplotlib` missing in this container -- 9 failures at HEAD,
  identical with and without changes).
- Evidence documented (what changed, verified, unresolved).
- No change to any reported number outside the new reporting-only key.

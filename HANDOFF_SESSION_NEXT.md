# Handoff — Documented two real-but-undocumented validation features; both verified green

## Prior assignment status: DONE (verified before this session)
The task in the previous `HANDOFF_SESSION_NEXT.md` was: (1) confirm the
provenance guard is green, then (2) pick a fresh bounded methodology gap from
`references/validation_methods.md` (an undocumented validation option or missing
falsification criterion) and verify with a focused `-k` subset.
- Step 1 VERIFIED: `python3 -m pytest
  skills/quantitative-backtesting/tests/test_real_market_data_provenance.py -q`
  -> `5 passed in 0.33s`.
- Step 2 EXECUTED this session (see below).

## What changed (this session) — documentation only, no engine/behavior change
Two real, tested CLI methodology features were completely undocumented in
`references/validation_methods.md` and `SKILL.md` (grep returned nothing for
either flag before this session). This mirrors the prior session's successful
"document an existing tested feature + keep SKILL.md consistent" approach.

1. `--family-pbo` / `--family-pbo-splits` (walk-forward subcommand): runs the
   CSCV probability of backtest overfitting (`pbo_cscv`) on the same OOS-aligned
   family matrix as `--family-returns`, recorded under `summary["family_pbo"]`
   (`pbo`, `is_overfit`, `mean_oos_rank`, `n_trials`, `n_observations`,
   `n_splits`, `n_partitions`, `n_partitions_evaluated`, `n_logits`,
   `strategy_names`); opt-in; unusable matrix -> `summary["family_pbo_error"]`
   with `family_pbo=null` (never raises); measurement only.
   - Doc: new bullet in `references/validation_methods.md` "Family-Wise Reality
     Check" section (after the `--family-returns` bullet, before "### Romano-Wolf
     Stepdown"); one-line addition to the family bullet in `SKILL.md`.
2. `--validation-method {walk_forward,cpcv}` + `--train-frac` / `--val-frac` /
   `--test-frac` (out-of-sample subcommand): the split fractions (defaults
   0.6/0.2/0.2, must sum to 1.0 within 1e-9 else `ValueError`) and the method
   that selects parameters *inside* the training split (`walk_forward` uses
   `--wf-*` months; `cpcv` uses `--cpcv-*`). Recorded under
   `summary["validation_method"]`.
   - Doc: new `###` subsection "The split fractions and the parameter-selection
     method (`--validation-method`)" in `references/validation_methods.md`
     (after the 3-phase intro, before "### The Walk-Forward Window Inside the
     Training Split"); one new Tips bullet in `SKILL.md`.

Files touched (2, +62/-1): `skills/quantitative-backtesting/SKILL.md`,
`skills/quantitative-backtesting/references/validation_methods.md`.
No code, no tests, no fixtures changed. Not committed (per "do not commit unless
explicitly asked").

## What was actually verified (evidence)
- Baseline green BEFORE edits: `test_walk_forward.py -k family_pbo` -> 4 passed;
  `test_out_of_sample_window.py` -> 12 passed.
- Doc-content guards AFTER edits: `test_resolution_vs_sample_size.py -k
  "docs_say_so or is_documented or one_fixture or source_of_truth or recapture
  or trimmed_copy"` -> 10 passed (these read `validation_methods.md` and require
  each referenced `####` heading to appear exactly once; my new headings are
  unique and do not collide).
- Feature tests AFTER edits: `test_walk_forward.py -k "family_diagnostics_end_to_end
  or print_family_pbo or family_pbo"` -> 5 passed (includes the end-to-end CLI
  `--family-pbo` run asserting `pbo["n_splits"]==8`, `n_partitions==comb(8,4)`).
- CLI help renders every documented flag (out-of-sample: `--train-frac`,
  `--val-frac`, `--test-frac`, `--validation-method {walk_forward,cpcv}`;
  walk-forward: `--family-returns`, `--family-pbo`, `--family-pbo-splits`).
- End-to-end smoke on committed data: `out-of-sample --validation-method cpcv
  --cpcv-n-splits 5 --cpcv-test-size 0.2` on `sample_ohlcv.csv` ->
  `out_of_sample_summary.json` has `summary.validation_method == "cpcv"` and a
  `test_resolution` block, exactly as documented.
- No trailing whitespace in edited files; `git status` shows only the 2 files.

## Why this task (high-value filter)
Both features are implemented, wired through the CLI, and covered by passing
tests, yet were invisible to any agent/reader of the skill docs. Documenting an
existing, tested methodology feature (and keeping SKILL.md consistent) improves
reproducibility and honesty of the quant methodology with zero new dependencies,
zero behavior change, and no fabricated data. Bounded and offline.

## What remains unresolved
- DATA PROVENANCE (pre-existing, BLOCKED offline — do NOT retry blindly):
  committed `real_market_data/{MSFT,AAPL,GOOGL}.csv` are byte-identical to
  `sample_benchmark.csv` / `sample_ohlcv.csv` / `AAPL.csv.bak`. `PROVENANCE.json`
  frames this as intentional shared-role and is guarded green by
  `test_real_market_data_provenance.py` (5 passed). Whether the bytes are
  authentic Yahoo data cannot be confirmed offline. Do NOT fabricate and do NOT
  re-flag as placeholder without evidence.
- Full `test_walk_forward.py` (239 tests) and the slow
  `test_falsifiable_hypothesis_example.py` (tens of minutes; cost sweeps ~16s
  each) were NOT swept end-to-end this cycle; only focused `-k` subsets were run.

## Approaches that already failed (do not repeat)
- `background_process` sweep: repo not visible in its namespace — use foreground
  timed `-k` subsets. (prior sessions)
- Restoring genuine market data offline: impossible without network; do not
  fabricate. (session 164 and earlier)
- Full `pytest test_walk_forward.py` in one shot: exceeds the 120s tool cap; use
  `-k` focused subsets (~2-7s for the subsets used here).

## One precise next task (bounded, evidence-based)
Pick the next undocumented-but-tested methodology option and document it the same
way. Concrete candidate: the `--impact-aggregation` / `--impact-model` flags on
the panel paths, and `--regime-cost-multipliers` / `--regime-impact-coefficients`,
are present in `walk_forward.py` argparse but are NOT described in
`references/validation_methods.md` (only `cost_models.md` covers some). Steps:
1. `python3 scripts/walk_forward.py walk-forward --help | grep -E "impact-aggregation|impact-model|regime-cost-multipliers|regime-impact-coefficients"`
   to confirm they render.
2. `grep -rln "impact_aggregation\|impact_model\|regime_cost_multiplier" tests/*.py`
   to confirm each is test-covered before documenting (do not document an
   untested path).
3. Add a focused subsection to `references/validation_methods.md` (unique `####`
   or `###` heading — must NOT duplicate the four `_doc_section` headings:
   "How much of the data should be held out?", "The three analysis paths answer
   it differently", "How long should the walk-forward windows be?", "How should
   the CPCV path be split?") and a one-line SKILL.md note.
4. Verify with `test_resolution_vs_sample_size.py -k "docs_say_so or
   is_documented or one_fixture"` (must stay green) plus the focused feature
   tests for the documented flags.
Do NOT commit unless explicitly asked.
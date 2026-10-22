# Next task — decide fate of the pre-driver ladder fixture (reduce to single source of truth)

## Status

The previous task is complete and verified:
- Enabled `--data` for `--wf-windows` and `--cpcv-splits` sweeps; measurements resolve benchmarks from the data file's directory and run on real-history prefixes.
- Captures and fixtures added:
  - `results/resolution_floor/wf_window_sweep_real_504.json` and `skills/quantitative-backtesting/results/resolution_floor/wf_window_sweep_real_504.json`
  - `skills/quantitative-backtesting/tests/fixtures/wf_window_sweep_real_504.json`
- Docs updated: `skills/quantitative-backtesting/SKILL.md`, `skills/quantitative-backtesting/references/validation_methods.md`
- Tests pass for the new real-history behavior (wf/cpcv sweep `--data` paths).

## Next task (one, precise)

**Resolve the duplication: the pre-driver ladder fixture and the recapture ladder fixture both measure the same full ladder (2,500/5,000/10,000/25,000/50,000 bars) with only different metadata/fields.**

The design is currently intentional per tests:
- `tests/fixtures/resolution_ladder_2500_to_50000.json` is the pre-driver baseline (no driver keys like `strategy_alpha`/`benchmark_alphas`/`alpha_status` etc.)
- `tests/fixtures/resolution_ladder_2500_to_50000_recapture.json` carries driver + status fields
- Tests assert: baseline must not carry driver keys; recapture carries driver/status; shared numbers between them agree to float noise.

Options:
1. **Keep both** (status quo) - document clearly, ensure no confusion. The recapture is the "driver-aware" source of truth.
2. **Replace baseline with recapture** and update tests to expect driver keys. But tests explicitly assert the opposite ("the baseline is the pre-driver capture, so it must not carry the driver's keys"). Changing this requires careful test updates.
3. **Move baseline to results/ only** (not a fixture) if not needed as fixture - check usages. Only used by `test_the_ladder_crossing_is_falsified_by_a_larger_rung` which loads via `_load_baseline_capture()` comparing against recapture. Also used in validation.

Pick ONE approach. Before changing anything, trace all usages:
- `_load_baseline_capture()` in tests
- References in docs (SKILL.md says "re-captured (the earlier capture remains the numerical baseline)")
- `results/resolution_floor/ladder_2500_to_50000.json` vs `results/resolution_floor/ladder_2500_to_50000_recapture.json`

Make the smallest reversible change that makes the source of truth unambiguous. Update tests/docs to match. Do not move/rename files blindly - follow existing patterns and attribution.

## Constraints
- No threshold/bound/criterion/verdict changes
- Preserve ability to verify "nothing moved between captures" if keeping comparison logic
- All resolution-vs-sample-size tests must still pass
- No changes to scripts/walk_forward.py

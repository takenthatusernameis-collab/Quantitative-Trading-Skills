# Handoff — cost sweep capture produced

## Verified this session
- Ran `measure_resolution_vs_sample_size.py --sizes 2500,5000,10000 --cost-regimes shipped,... --series both --json` for both no_effect and effect series.
- Committed capture: `results/resolution_floor/cost_sweep_2500_5000_10000.json` (148753 bytes), valid JSON with sweeps.no_effect and sweeps.effect.
- Trimmed fixture present: `skills/quantitative-backtesting/tests/fixtures/cost_sweep_2500_5000_10000.json` (matches the capture).
- Cost-sweep pins added and registered in TEST_REGISTRY (negative-controlled): capture-own-JSON, trimmed-copy-of-capture, negative-controlled, documented checks.
- Documentation: cost sweep referenced in `references/validation_methods.md` and `SKILL.md` (`test_the_cost_sweep_is_documented` passes).

## Remaining
- Cost sweep: none — all three items are complete and green.
- Full suite `skills/quantitative-backtesting/tests/test_resolution_vs_sample_size.py`: 77/77 pass (was 75/77; two cost-sweep tests fixed).

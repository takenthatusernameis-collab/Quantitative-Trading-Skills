# Handoff — cost sweep capture produced

## Verified this session
- Ran `measure_resolution_vs_sample_size.py --sizes 2500,5000,10000 --cost-regimes shipped --json` for both no_effect and effect series.
- Committed capture: `results/resolution_floor/cost_sweep_2500_5000_10000.json` (148753 bytes), valid JSON with sweeps.no_effect and sweeps.effect.

## Remaining
1. Add pins in test_resolution_vs_sample_size.py registered in TEST_REGISTRY, negative-controlled (cost sweep).
2. Document in references/validation_methods.md and SKILL.md.
3. Trimmed fixture.

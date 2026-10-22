# Handoff — cost sweep infrastructure verified; capture/pins/docs remain

## Verified this session
- `--cost-regimes` sweep runs end-to-end and emits rows carrying `cost_regime` + `costs`; shipped regime reproduces baseline.
- Sweep refuses combination with other sweeps (verified by argparse errors in code).

## Remaining (next task)
1. Run full cost sweep on shipped ladder for effect + no_effect series, produce committed capture `results/resolution_floor/cost_sweep_*.json` and trimmed fixture.
2. Add pins in test_resolution_vs_sample_size.py registered in TEST_REGISTRY, negative-controlled.
3. Document in references/validation_methods.md and SKILL.md.

## Note
Full ladder run takes ~7 min; run affected tests only during iteration.

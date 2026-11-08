# Handoff — root simple_momentum real-data coverage extended to MSFT + GOOGL

## What changed (this session)
- Added `test_root_simple_momentum_real_msft.py` (new): real-data regression guard for root `simple_momentum_hypothesis.py` on the committed MSFT.csv fixture.
- Added `test_root_simple_momentum_real_googl.py` (new): same for GOOGL.csv.
- Both mirror `test_root_simple_momentum_real_aapl.py` (already committed, AAPL only): import the root module (`import simple_momentum_hypothesis as smh`), run `smh.run_hypothesis_test(DATA)`, guard the advertised methodology controls (criteria structure, sharpe/total_return present, deflated_alpha n_benchmarks>=2, capacity finite & > initial capital, test_resolution block present), pin metrics with relative tolerance 1e-3 (never exact equality).
- Per the assigned instruction, the verdict is NOT asserted in the new tests (SUPPORTED and NOT SUPPORTED are both valid falsification outcomes). MSFT returns NOT SUPPORTED (deflated-alpha fails); GOOGL returns SUPPORTED.
- No existing source or test files modified. Working tree: only the two new files untracked.

## What was actually verified
- `test_root_simple_momentum_real_msft.py` + `test_root_simple_momentum_real_googl.py` + existing `test_root_simple_momentum_real_aapl.py`: **6 passed in 1.87s**.
- `-k simple_momentum` subset over the three root files: **6 passed**.
- Sibling `test_root_scripts_pit_bias_controls.py` (unchanged, guards the same root script on the synthetic control): **8 passed**.
- `python3 -m py_compile` on both new files: OK.
- Offline, committed fixtures only; no live network.
- Observed pinned values (regression baseline, not a profitability claim):
  - MSFT: sharpe 0.6853465301869522, total_return 0.28002040656752203, benchmark_total_return 0.9015402575236577, alpha -0.03871271312726847, capacity 16454953.518723998, deflated_alpha_ratio 0.06800420155125697 (p=0.931995798448743, n_benchmarks=2), test_resolution min_detectable_alpha 0.30525199531660735, n_test_observations 502, alpha_status resolvable, alpha_beyond_plausible_bound True.
  - GOOGL: sharpe 0.5143360018077565, total_return 0.2072115709436657, benchmark_total_return 0.2714240402506196, alpha 0.040455858408182485, capacity 457242.34985400003, deflated_alpha_ratio 0.5462152222600346 (p=0.4537847777399654, n_benchmarks=2), test_resolution min_detectable_alpha 0.18302207776218415, n_test_observations 502, alpha_status resolvable, alpha_beyond_plausible_bound True.

## What remains unresolved
- Full-suite gate exit code / exact pass-fail count was never observed (the `skills/quantitative-backtesting/tests/` run from the prior HANDOFF.md ran in a different session context; no background process in this session). Re-running it is the authoritative check before treating coverage as fully verified.
- `train_val_test_split` / `point_in_time_validation` are not carried in the returned `metrics` dict for any fixture (AAPL/MSFT/GOOGL); they print True in the run banner but read from the tear-sheet summary, so they are not asserted here. PIT/split engagement is already source-guarded by `test_root_scripts_pit_bias_controls.py::test_pit_and_split_are_pre_registered_in_source`.
- Existing committed `test_root_simple_momentum_real_aapl.py` asserts `verdict == "SUPPORTED"`, which contradicts the assigned instruction "do not assert the verdict." Left as-is (committed, passing) since changing it is out of scope; reconcile only if explicitly asked.

## Approaches already tried / failed
- None failed this session. No approach abandoned.

## One precise next task
Re-run the standing full-suite gate once to confirm green and record the exit code / pass count:
`python3 -m pytest skills/quantitative-backtesting/tests/ -p no:cacheprovider -q` (expects ~30-80 min; use `background_process` or a long timeout). If any failure appears, treat as pre-existing/environmental unless tied to these new root files (they are not in that directory), document it, and do not widen scope. Do not commit unless explicitly asked.
After the gate, the next bounded extension would be a root-level cost-application guard (frictionless vs advertised cost on MSFT/GOOGL via `smh._run_backtest_metrics`) mirroring `test_root_scripts_pit_bias_controls.py::test_advertised_costs_are_actually_applied`, if real-data cost-path coverage is desired.

(End of file)

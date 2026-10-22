# Next task — measure how the resolution ladder's verdicts move with the cost assumptions

## Status

The previous task is complete and verified:
- The full-ladder measurement has **one source of truth**:
  `skills/quantitative-backtesting/tests/fixtures/resolution_ladder_2500_to_50000_recapture.json`
  is the only fixture that covers the ladder.
- The pre-driver fixture was removed; the pre-driver *capture*
  (`results/resolution_floor/ladder_2500_to_50000.json`) stays committed as
  the historical baseline and now carries the provenance the removed fixture
  held (command, commit `d9f19aa`, environment, fixture construction,
  `measured_at_utc` 2026-10-20T21:56Z). Its numbers and its summary are
  unchanged.
- New pin `test_the_full_ladder_has_one_fixture` (69th test) keeps the
  arrangement unambiguous; seven mutations were negative-controlled.
- `tests/test_resolution_vs_sample_size.py` 69/69, and the whole skill suite
  (19 files) passes.

## Next task (one, precise)

**Measure the resolution ladder under different cost assumptions and report
which of its verdicts survive. Do not move any threshold, bound, criterion or
verdict — measure them under other costs and report what changes.**

### The question

Every resolution number in the repository is measured at the shipped cost
assumptions:

- `COMMISSION = 0.0002` (2 bps per trade) and `SLIPPAGE = 0.0001` (1 bps per
  trade), from `examples/falsifiable_hypothesis_example.py:122-123`, passed
  to the framework by `scripts/measure_resolution_vs_sample_size.py`
  (lines 304-309, 345-350, 382-387) — to the strategy *and* to its
  benchmarks (`benchmark_commission` / `benchmark_slippage` carry the same
  values);
- and the framework's defaults for everything else:
  `impact_coefficient = 0.0`, `borrow_cost = 0.0`, `funding_cost = 0.0`
  (`scripts/walk_forward.py:468-473`) — i.e. **no market impact, no borrow
  cost, no funding cost**. The measurement tool never passes those three.

The floor is not cost-independent: the trial Sharpes that set it are net of
commission+slippage (`scripts/walk_forward.py:737-765` computes each trial
Sharpe from `_calculate_strategy_returns(train_data, train_signals,
commission, slippage, ...)`), so SR\* = std(trial Sharpes) * sqrt(2 ln N)
moves when the costs move. And the *observed* statistic moves more.

### The evidence already collected (exploratory, in-memory, NOT committed)

Measured with `measure_resolution_vs_sample_size.measure_synthetic`, seed 7,
on the synthetic positive-control fixture, by overriding the module-level
`COMMISSION` / `SLIPPAGE` before the call:

**Out-of-sample path, 10,000 bars (the rung the control-discrimination test
uses):**

| costs | series | SR\* (floor) | min detectable Sharpe | observed Sharpe | alpha\* | min detectable alpha | observed alpha |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 0 bps | null | 1.2584 | 1.7163 | -0.156 | 0.01737 | 0.06888 | -0.0190 |
| 0 bps | effect | 1.1519 | 1.5964 | 3.314 | 0.02438 | 0.07883 | 0.3932 |
| 3 bps (shipped) | null | 1.2557 | 1.7136 | -0.181 | 0.01737 | 0.06889 | -0.0218 |
| 3 bps (shipped) | effect | 1.1584 | 1.6012 | 3.483 | 0.02404 | 0.07793 | 0.4103 |
| 15 bps | null | 1.2525 | 1.7100 | -0.298 | 0.01735 | 0.06875 | -0.0350 |
| 15 bps | effect | 1.1870 | 1.6299 | 3.448 | 0.02404 | 0.07794 | 0.4061 |

**Walk-forward path, 2,500 bars (a rung the walk-forward path's own floor is
measured at):**

| costs | series | SR\* | min detectable Sharpe | observed Sharpe | alpha\* | min detectable alpha | observed alpha |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 0 bps | null | 1.3144 | 1.7565 | -0.623 | 0.00586 | 0.04000 | -0.0219 |
| 0 bps | effect | 1.2453 | 1.7265 | 0.552 | 0.03426 | 0.06610 | 0.0043 |
| 3 bps (shipped) | null | 1.3087 | 1.7534 | -0.780 | 0.00554 | 0.03848 | -0.0325 |
| 3 bps (shipped) | effect | 1.2510 | 1.7405 | 0.069 | 0.03095 | 0.06136 | -0.0225 |
| 15 bps | null | 1.2930 | 1.7422 | -1.004 | 0.00507 | 0.03676 | -0.0469 |
| 15 bps | effect | 1.2758 | 1.7815 | -0.441 | 0.02751 | 0.05678 | -0.0480 |

**What that suggests, and what it does not yet establish:**

- The **floor moves very little** with costs (SR\* by ~2-3% from zero costs
  to 15 bps). So the resolution conclusions look cost-robust so far.
- The **observed statistic is not cost-robust on the walk-forward path at
  2,500 bars**: the effect series' observed annualized Sharpe falls 0.552 →
  0.069 → -0.441 (and its observed alpha turns negative) as the costs go
  0 → 3 → 15 bps. On the out-of-sample path at 10,000 bars the same
  treatment barely moves it (3.31 → 3.48 → 3.45).
- So the **path and the rung decide how much the costs matter**, and the
  shipped configuration's verdicts on the *short* walk-forward rungs may be
  a statement about the cost assumption. That is the question to settle
  properly — with committed captures, not with exploratory numbers.

### What to build

1. **A cost sweep in `scripts/measure_resolution_vs_sample_size.py`**,
   following the pattern of the existing sweeps (`--test-fracs`,
   `--wf-windows`, `--cpcv-splits`): a flag that names the cost regimes to
   measure (commission/slippage pairs at least; consider surfacing
   `impact_coefficient`, `borrow_cost` and `funding_cost` too, since the
   framework supports them and the tool currently leaves them at zero), each
   regime measured with the framework's own blocks and reported with the
   same numbers the other sweeps report (SR\*, alpha\*, the observed
   statistics, the inside/outside-the-bound flags, the crossing rungs).
   - The shipped configuration must be **unchanged by the sweep's
     existence**: the shipped regime has to reproduce today's numbers
     exactly.
   - The sweep must **refuse to run alongside another sweep**, and must say
     which series and which path it measured.
   - Costs are **not** a lever of the out-of-sample/walk-forward/CPCV
     *configuration*; they are a lever of the *measurement*, so they may
     belong in the ladder itself rather than in a sweep. Use judgement, but
     whichever way it is done, the tool must not be able to report a
     ladder measured at some costs under another name.
2. **A capture and a trimmed fixture** in the house style:
   `results/resolution_floor/<name>.json` (the tool's own `--json` output
   plus provenance: command, environment, script commit, what was measured,
   the plausibility bounds) and
   `skills/quantitative-backtesting/tests/fixtures/<name>.json` (provenance
   plus the rows).
3. **Pins** in `tests/test_resolution_vs_sample_size.py`, registered in
   `TEST_REGISTRY`: the capture is the tool's own output, the fixture is a
   faithful trim of it, the shipped regime reproduces the committed ladder,
   each regime's numbers equal the framework's own blocks, the crossings
   under each regime are stated (or stated as "not reached"), and the sweep
   moves no threshold, no bound, no criterion and no verdict. Negative-
   control each new pin by mutation, as the previous sessions did.
4. **Documentation** in `references/validation_methods.md` (next to the
   ladder section) and `SKILL.md` (the flag and what it measures): the
   measured numbers per regime, **what the sweep does not establish**, and
   the answer to the question the ladder exists to answer — *which of the
   ladder's verdicts are properties of the sample and which are properties
   of the cost assumptions*.

### Constraints

- No threshold / bound / criterion / verdict changes.
- No change to the shipped configuration's numbers: the shipped regime must
  reproduce the committed ladder exactly (it is the baseline every other
  capture is compared against).
- Preserve the "nothing moved between captures" check and the single
  source of truth for the ladder
  (`test_the_full_ladder_has_one_fixture`).
- Do not change `scripts/walk_forward.py`.
- Do not spend the session on the inherited marketplace catalogue.
- Keep the synthetic fixture labelled as synthetic: it is a formula, not a
  market.

## Notes for the next session

- `matplotlib` **is** available here (3.11.2) — the older handoff's claim
  that it was missing is stale, and `tests/test_reporting.py` runs.
- The skills marketplace generator (`bin/`) cannot run offline in this
  environment (`pnpm` cannot fetch its dependencies). The generator reads
  only `SKILL.md` frontmatter, so leaving the frontmatter alone is enough
  to keep `skills/marketplace.yaml` unchanged.
- Running the whole `test_resolution_vs_sample_size.py` suite takes ~7
  minutes; running only the affected test functions takes seconds. Negative
  controls should call the functions directly (import the test module and
  call them) rather than the whole suite.
- A mutation harness that mutates and restores files on disk must keep its
  backups and restore them in a `finally` — a 40-minute command timeout
  killed one mid-run earlier and left a mutated artifact behind.

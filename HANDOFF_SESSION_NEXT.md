# Handoff — Borrow/funding cap docs added; CLI help corrected (caps feature now documented)

## Prior assignment status: DONE (already committed before this session)
The handoff task in `HANDOFF_SESSION_CURRENT.md` / `HANDOFF_SESSION_NEXT.md`
(fix mutually-exclusive `if/elif` borrow/funding caps in `estimate_capacity`)
was ALREADY implemented and committed in `d0c6da7`:
- `skills/quantitative-backtesting/scripts/walk_forward.py:3965-3975` uses
  independent `if` blocks; `cost_drag = effective_borrow + effective_funding`.
- `test_cli_out_of_sample_max_borrow_and_funding_caps_both_apply` exists
  (test_walk_forward.py:4676) and is registered in TEST_REGISTRY (:7669).
- Verified this session: the 3 cap tests pass (3 passed in 5.34s).
No re-implementation needed; did not repeat that work.

## What changed (this session)
Documentation-only + help-text accuracy (no engine/behavior change):
1. `skills/quantitative-backtesting/references/cost_models.md` — added a
   "#### Per-leg drag caps (optional)" subsection after the cost-drag section
   (~line 709) documenting `--max-borrow-cost` / `--max-funding-cost` and the
   `--max-*-costs` sweep variants: the per-leg `min(...)` clamp, independent
   application (both caps bind when both legs positive), default = bitwise
   unchanged, ValueError on non-positive/non-finite, capacity-measurement-only.
   Also states accurately that `run_backtest.py` does NOT expose/apply the caps.
2. `skills/quantitative-backtesting/scripts/walk_forward.py:12711-12712` —
   corrected the `--max-borrow-cost` / `--max-funding-cost` help text. The old
   text said capacity is "further reduced proportionally", which was WRONG: the
   engine caps each leg with `min` (a clamp), not a proportional reduction. New
   text says "capped at this limit (min, not proportional)" and notes each cap
   is independent of the other.

## What was actually verified (evidence)
- `walk_forward.py out-of-sample --help` renders both flags, exit 0.
- 3 cap tests re-run after edits: `3 passed, 239 deselected in 5.34s`.
- Broader capacity/cost subset earlier in session: `51 passed, 191 deselected`
  (baseline green before edits).
- `git diff --stat`: cost_models.md +32, walk_forward.py +4/-2 (help strings only).

## Why this task (high-value filter)
The caps feature was implemented + tested but completely undocumented in
references/SKILL.md (grep returned nothing), and the CLI help was actively
misleading ("proportionally"). Documenting an existing, tested methodology
feature and removing a false statement is bounded, offline, and improves the
reproducibility/honesty of the quant methodology — no new dependencies, no
scope creep, no fabricated data.

## What remains unresolved
- DATA PROVENANCE (pre-existing, BLOCKED offline — do NOT retry blindly):
  committed `real_market_data/{MSFT,AAPL,GOOGL}.csv` are placeholders/synthetic
  (MSFT==sample_benchmark, AAPL==sample_ohlcv, GOOGL==AAPL.csv.bak). Restoring
  authentic OHLC needs network. See PROVENANCE.json + HANDOFF_SESSION_164.md.
  Do NOT fabricate. This has been the blocker for many sessions.
- Skill-level (non-root) full suite not swept end-to-end this cycle (only the
  capacity/cost subset + cap tests). Full `test_walk_forward.py` exceeds the
  120s tool cap in one run; use `-k` subsets.

## Approaches that already failed (do not repeat)
- `background_process` sweep: repo not visible in its namespace — use foreground
  timed `-k` subsets. (prior sessions)
- Restoring genuine market data offline: impossible without network; do not
  fabricate. (session 164 and earlier)
- Full `pytest test_walk_forward.py` in one shot: exceeds 120s tool cap; use
  `-k` focused subsets (~70s for ~50 tests).

## One precise next task (bounded, evidence-based)
CORRECTION to prior handoffs' data-provenance framing: PROVENANCE.json
(`skills/quantitative-backtesting/assets/example_data/real_market_data/PROVENANCE.json`)
ALREADY exists and is guarded by `tests/test_real_market_data_provenance.py`. It
claims the fixtures were "Fetched live from Yahoo Finance ... committed
real-market data, not synthetic" and frames the byte-identity (AAPL ==
sample_ohlcv.csv; MSFT == sample_benchmark.csv) as intentional shared-role, NOT
as placeholder fakery. This CONTRADICTS older handoffs (session 164 etc.) that
called them placeholders. The byte-identity itself is verifiable; whether the
bytes are authentic Yahoo data cannot be confirmed offline. Do NOT fabricate and
do NOT re-flag as placeholder without evidence.

Concrete next task: run the provenance guard to confirm it is green, then move
to a fresh methodology gap. Steps:
1. `timeout 110 python3 -m pytest
   skills/quantitative-backtesting/tests/test_real_market_data_provenance.py -q`
   → VERIFIED THIS SESSION: 5 passed in 0.35s (green). If it ever fails, that is
   a real, bounded bug to fix first.
2. If green, pick the next bounded gap from
   `skills/quantitative-backtesting/references/validation_methods.md` (e.g. an
   undocumented validation option or a missing falsification criterion) and
   verify with a focused `-k` test subset.
Do NOT commit unless explicitly asked.
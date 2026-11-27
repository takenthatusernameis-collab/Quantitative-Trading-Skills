# Next Session Task — Symmetric `--max-funding-cost` cap regression test

## Task
Add `test_cli_out_of_sample_max_funding_cost_cap_reflected_in_csv` to
`skills/quantitative-backtesting/tests/test_walk_forward.py` and register it in
`TEST_REGISTRY` (next to `test_cli_out_of_sample_max_cost_cap_reflected_in_csv`,
~line 7533). Mirror the borrow-cap test but exercise the FUNDING leg.

## Evidence / where to look
- Borrow-cap test to mirror: `test_cli_out_of_sample_max_cost_cap_reflected_in_csv`
  (test_walk_forward.py:4546). It now PASSES after the `result["cost_drag"]` fix.
- Engine funding-cap branch: `walk_forward.py:3977-3983`
  (`elif max_funding_cost is not None and funding_cost_drag > 0`).
- Reporting fix that makes cost_drag == capped value: `walk_forward.py:~3987`
  (`result["cost_drag"] = float(cost_drag)` after the cap block).
- CSV emission: `walk_forward.py:~12599` reads `capacity_detail.cost_drag`.

## Suggested parameters
`--strategy macd --leverage 1.5 --funding-cost 0.10 --short-exposure 0.0
--max-funding-cost 0.01 --impact-coefficient 0.5 --output-format csv`
(uncapped funding drag = (1.5-1)*0.10 = 0.05 > cap 0.01 → binds). Assert
`cost_drag == 0.01` and `cost_adjusted_capacity == impact_capacity /
(1 + cost_drag * holding_period_years)`.

## Constraints
- Committed fixtures only, no network. Minimal change; do NOT modify engine math.
- Run `python3 skills/quantitative-backtesting/tests/test_walk_forward.py`
  (expect 240/240). Do NOT commit unless explicitly asked.

## Note
Data-provenance issue (MSFT.csv is a placeholder) remains blocked offline — see
HANDOFF_SESSION_164.md / PROVENANCE.json. Do not fabricate data.
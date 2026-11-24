# Deflated multiple-testing count sensitivity

Best nominal cell: SMA crossover on AAPL, walk-forward DSR p = 0.0415 (per
`test_walk_forward_cross_family_meta_analysis_real_triple.py`).

Question: how many simultaneous comparisons would the best nominal cell
survive under a Bonferroni correction at alpha = 0.10?

- Bonferroni break-even: m < 0.10 / 0.0415 = 2.41. So the cell survives only
  if it is one of at most 2 hypotheses tested. It already fails at m = 3.
- Sidak break-even (independent tests): m < log(1-0.10)/log(1-0.0415) = 2.49.
  Same conclusion.
- The "1/0.0415 ≈ 24" figure is the number of independent looks at which a
  raw p of 0.0415 would be expected by chance alone under the null (i.e. the
  effective selection-noise multiplier). The study actually performed 12
  asset-family hypotheses plus within-asset protocol selection, so the true
  look count is at least 12 and plausibly ~24+.

Interpretation: the best nominal pass (p=0.0415) is consistent with selection
noise across protocols, assets, and families. It would require the true number
of independent looks to be <= 2 to be a genuine edge; the repository's actual
search (12+ asset-family cells, each a minimum over multiple protocols) far
exceeds that. Confirms the NOT SUPPORTED verdict of the cross-family
meta-analysis and the CPCV Reality Check / Romano-Wolf studies.
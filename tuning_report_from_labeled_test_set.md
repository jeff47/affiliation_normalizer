# Labeled Tuning Report

- Source file: `combined_affiliation_test_set_draft.csv`
- Labeled rows: `114`
- `ambiguous -> matched` rows: `98`
- Rows with review-only aliases involved: `1`

## High-Impact Observation

- A deterministic tie-breaker that prefers the candidate with the **unique longest matched alias** would fix `75/98` (`76.5%`) of `ambiguous -> matched` errors in labeled data.

## Top Expected Targets in Ambiguous Errors

- `us-tn-vanderbilt-university-medical-center` (Vanderbilt University Medical Center): 30
- `us-ma-harvard-university` (Harvard University): 19
- `us-ma-broad-institute` (Broad Institute): 13
- `us-co-university-of-colorado-anschutz-medical-campus` (University of Colorado Anschutz Medical Campus): 12
- `us-ma-brigham-and-women-s-hospital` (Brigham and Women's Hospital): 8
- `us-sc-medical-university-of-south-carolina` (Medical University of South Carolina): 5
- `us-dc-george-washington-university` (George Washington University): 4
- `us-ma-massachusetts-general-hospital` (Massachusetts General Hospital): 3
- `us-tx-university-of-texas-health-science-center-houston` (University of Texas Health Science Center Houston): 2
- `us-nj-rutgers-new-jersey-medical-school` (Rutgers New Jersey Medical School): 2

## Files Generated

- Rule candidates: `tuning_rule_candidates.tsv`
- Unresolved examples after longest-alias heuristic: `tuning_unresolved_examples.tsv`

## Suggested Next Tuning Step

- Implement longest-alias specificity tie-break for `ambiguous` allow-candidate conflicts.
- Then add low-risk pair-precedence rules from `tuning_rule_candidates.tsv` where `reverse_count=0` and `support_count>=5`.
- Keep high-risk bidirectional pairs (`reverse_count>0`) as context-driven/manual rules.

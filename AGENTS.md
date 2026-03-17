# Agent Instructions For This Repository

## Primary goal
Use the `affiliation_normalizer` package for institution matching from affiliation text and identifiers.

## When user says "use the module"
1. Import and call the runtime API directly:
   - `from affiliation_normalizer import match_affiliation`
   - `from affiliation_normalizer import match_record`
   - `from affiliation_normalizer import match_ror, match_grid, match_email_domain`
   - or instantiate `AffiliationNormalizer` if custom rules are needed.
2. Do not re-implement matching logic in ad hoc scripts unless explicitly requested.
3. Return the module output fields (`status`, `canonical_id`, `standardized_name`, etc.) to the caller.
4. If record-level identifiers are available, prefer `match_record(...)` for priority resolution.

## Runtime API contract
- `match_affiliation(text: str) -> MatchResult`
- `match_ror(ror_id: str) -> MatchResult`
- `match_grid(grid_id: str) -> MatchResult`
- `match_email_domain(email_domain: str) -> MatchResult`
- `match_record(*, affiliation_text: str = "", ror_id: str = "", grid_id: str = "", email: str = "") -> MatchResult`
- Priority policy in `match_record`: `ROR/GRID > email > text`.
- If `match_record(...)` receives only malformed identifier/email inputs and no later signal resolves, it returns the same `invalid_*` reasons as the direct lookup helpers.
- Alias policies:
  - `allow`: normal runtime matching
  - `allow_if_geo`: alias match requires geo evidence in text (city, or state+country)
  - `review_only`: never auto-resolved at runtime
  - `deny`: blocked alias
- `MatchResult.status`:
  - `matched`: single resolved institution
  - `ambiguous`: multiple unresolved candidates
  - `not_found`: no allow-policy match
- `MatchResult.reason` is intended for caller branching; treat the documented reason strings as part of the public runtime contract.
- `MatchResult.confidence` is a coarse heuristic score in `[0.0, 1.0]`, not a calibrated probability.
- For `matched`, use:
  - `canonical_id`
  - `canonical_name`
  - `standardized_name` (preferred display string, e.g. `Yale University, New Haven, CT`)
  - `city`, `state`, `country`, `ror_id`, `grid_id`, `openalex_id`
- For `ambiguous`/`not_found`, check:
  - `reason`
  - `candidate_ids`
  - common `not_found` reasons include:
    - `no_match`
    - `review_only_match`
    - `geo_policy_no_match`
    - `multi_author_input`
    - `empty_ror`, `invalid_ror`
    - `empty_grid`, `invalid_grid`
    - `empty_email_domain`, `invalid_email_domain`
    - `no_ror_match`, `no_grid_match`, `no_email_domain_match`
- For custom rules, prefer `AffiliationNormalizer.from_rules_json(...)`.
- Direct `AffiliationNormalizer(rules=...)` is for advanced use and expects the same payload shape emitted by `build_rules(...)`: top-level `institutions`, `alias_rules`, and `precedence_rules`.
- Malformed custom rule payloads now raise `ValueError` at construction time.

## Rule sources and rebuild
- Master data: `niaid_org_seed_master.csv`
- Email mapping input (for seed population): `ipf_to_email.csv`
- Alias policy: `alias_policy_review.tsv`
- Precedence rules: `canonical_precedence.tsv`
- Compiled runtime artifact: `affiliation_normalizer/data/rules.json`

Master seed fields now include:
- `ror_id`
- `grid_id`
- `email_domains` (pipe-delimited domains, e.g. `yale.edu|med.yale.edu`)

If any source changes, rebuild rules:

```bash
python -m affiliation_normalizer.build_rules \
  --master niaid_org_seed_master.csv \
  --alias-policy alias_policy_review.tsv \
  --precedence canonical_precedence.tsv \
  --output affiliation_normalizer/data/rules.json
```

## Current precedence behavior
- If both Harvard and Brigham are matched, prefer Brigham.
- If both Harvard and Massachusetts General Hospital are matched, prefer MGH.

## Known limitations
1. Coverage is curated and seed-bounded. Missing institutions or variants require seed/alias updates.
2. Coverage is still mostly US-focused, with selective non-US additions (for example, Imperial College London and Karolinska Institutet).
3. `review_only` aliases are not auto-matched at runtime.
4. `allow_if_geo` aliases intentionally fail when text omits location context (`geo_policy_no_match`).
5. Author-list narrative affiliation blobs are gated (`multi_author_input`).
6. Multi-institution AD strings may still produce `ambiguous` when no deterministic tie-break exists.
7. Email-domain mappings can be ambiguous for parent/subunit institutions; these return `ambiguous` unless other signals resolve them.
8. Regex is not the primary matcher; runtime behavior is alias/normalization-driven with precedence + specificity tie-breaks.

## Verification after matcher/rule changes
Run:

```bash
python -m pytest -q
python -m ruff check .
python -m mypy affiliation_normalizer tests/test_affiliation_normalizer.py
```

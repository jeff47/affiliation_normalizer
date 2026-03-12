# affiliation_normalizer

Normalize affiliation strings to a curated canonical institution record.

## Install from git

```bash
pip install git+https://github.com/jeff47/affiliation_normalizer.git@main
```

## Use as a dependency in another project

```toml
[project]
dependencies = [
  "affiliation_normalizer @ git+https://github.com/jeff47/affiliation_normalizer.git@main",
]
```

## Quick import check

```bash
python -c "from affiliation_normalizer import match_affiliation, match_record; print('ok')"
```

## Documentation

- Runtime usage and return contract: `affiliation_normalizer/README.md`
- Repository workflow and agent conventions: `AGENTS.md`

## Rule rebuild

```bash
python -m affiliation_normalizer.build_rules \
  --master niaid_org_seed_master.csv \
  --alias-policy alias_policy_review.tsv \
  --precedence canonical_precedence.tsv \
  --output affiliation_normalizer/data/rules.json
```

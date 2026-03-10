#!/usr/bin/env python3
"""Build a stratified draft affiliation test set from MEDLINE-style text."""

from __future__ import annotations

import argparse
import csv
import random
import re
import unicodedata
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path

FIELD_RE = re.compile(r"^[A-Z0-9]{2,4}  - ")
WHITESPACE_RE = re.compile(r"\s+")
TOKEN_RE = re.compile(r"[a-z0-9]+")
NON_ALNUM_RE = re.compile(r"[^a-z0-9\s]+")

STOPWORDS = {
    "of",
    "the",
    "and",
    "for",
    "at",
    "in",
    "on",
    "to",
    "a",
    "an",
}

# Manual precedence rules for known co-affiliation patterns.
# If both IDs are present as allow-candidates, prefer the first ID.
CANONICAL_PRECEDENCE_RULES: list[tuple[str, str]] = [
    (
        "us-ma-brigham-and-women-s-hospital",
        "us-ma-harvard-university",
    ),
    (
        "us-ma-massachusetts-general-hospital",
        "us-ma-harvard-university",
    ),
]


@dataclass(frozen=True)
class AliasRule:
    alias_raw: str
    alias_norm: str
    canonical_id: str
    canonical_name: str
    policy: str
    alias_type: str


@dataclass
class AffiliationStats:
    freq: int = 0
    pmid_example: str = ""


@dataclass(frozen=True)
class ClassifiedAffiliation:
    ad_text: str
    pmid_example: str
    freq: int
    suggested_status: str
    suggested_canonical_id: str
    suggested_canonical_name: str
    suggested_match_confidence: str
    matched_allow_aliases: str
    matched_review_aliases: str
    stratum: str


def normalize_text(text: str) -> str:
    folded = unicodedata.normalize("NFKD", text)
    folded = folded.encode("ascii", "ignore").decode("ascii")
    folded = folded.lower().replace("&", " and ")
    folded = NON_ALNUM_RE.sub(" ", folded)
    return WHITESPACE_RE.sub(" ", folded).strip()


def clean_affiliation(text: str) -> str:
    return WHITESPACE_RE.sub(" ", text).strip()


def acronym(name: str) -> str:
    words = re.findall(r"[A-Za-z0-9]+", name)
    sig = [w for w in words if w.lower() not in STOPWORDS]
    if len(sig) < 2:
        return ""
    return "".join(w[0] for w in sig).upper()


def generate_aliases(row: dict[str, str]) -> list[tuple[str, str]]:
    """Return (alias, alias_type) tuples."""
    aliases: set[tuple[str, str]] = set()
    canonical = (row.get("canonical_name") or "").strip()
    nih_name = (row.get("nih_reporter_name") or "").strip()

    if canonical:
        aliases.add((canonical, "canonical_name"))
        aliases.add((canonical.replace(",", " "), "canonical_name_nocomma"))
        ac = acronym(canonical)
        if 3 <= len(ac) <= 8:
            aliases.add((ac, "acronym"))

    if nih_name:
        aliases.add((nih_name, "nih_name"))
        aliases.add((nih_name.replace(",", " "), "nih_name_nocomma"))

    # UC campus convenience aliases (e.g., "UC San Francisco").
    low = canonical.lower()
    prefix = "university of california,"
    if low.startswith(prefix):
        campus = canonical[len(prefix) :].strip()
        if campus:
            aliases.add((f"UC {campus}", "uc_campus"))
            aliases.add((f"U.C. {campus}", "uc_campus"))

    out: list[tuple[str, str]] = []
    for alias, alias_type in sorted(aliases):
        if alias:
            out.append((alias, alias_type))
    return out


def load_alias_policy(path: Path) -> dict[str, str]:
    policy: dict[str, str] = {}
    with path.open("r", encoding="utf-8", newline="") as fh:
        reader = csv.DictReader(fh, delimiter="\t")
        for row in reader:
            alias = normalize_text((row.get("alias") or "").strip())
            if not alias:
                continue
            this_policy = (row.get("policy") or "").strip().lower() or "review_only"
            policy[alias] = this_policy
    return policy


def load_alias_rules(institutions_path: Path, policy_path: Path) -> list[AliasRule]:
    alias_policy = load_alias_policy(policy_path)
    rules: list[AliasRule] = []
    with institutions_path.open("r", encoding="utf-8", newline="") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            cid = (row.get("canonical_id") or "").strip()
            cname = (row.get("canonical_name") or "").strip()
            if not cid or not cname:
                continue
            for alias_raw, alias_type in generate_aliases(row):
                alias_norm = normalize_text(alias_raw)
                if not alias_norm:
                    continue
                policy = alias_policy.get(alias_norm, "allow")
                if policy == "deny":
                    continue
                rules.append(
                    AliasRule(
                        alias_raw=alias_raw,
                        alias_norm=alias_norm,
                        canonical_id=cid,
                        canonical_name=cname,
                        policy=policy,
                        alias_type=alias_type,
                    )
                )
    return rules


def parse_ad_affiliations(path: Path) -> dict[str, AffiliationStats]:
    stats: dict[str, AffiliationStats] = {}
    current_pmid = ""
    current_ad: list[str] | None = None
    current_ad_pmid = ""

    def flush_current() -> None:
        nonlocal current_ad, current_ad_pmid
        if current_ad is None:
            return
        ad_text = clean_affiliation(" ".join(current_ad))
        if ad_text:
            rec = stats.get(ad_text)
            if rec is None:
                rec = AffiliationStats(freq=0, pmid_example=current_ad_pmid)
                stats[ad_text] = rec
            rec.freq += 1
            if not rec.pmid_example:
                rec.pmid_example = current_ad_pmid
        current_ad = None
        current_ad_pmid = ""

    with path.open("r", encoding="utf-8", errors="replace") as fh:
        for raw in fh:
            line = raw.rstrip("\n")

            if line.startswith("PMID- "):
                current_pmid = line[6:].strip()

            if line.startswith("AD  - "):
                flush_current()
                current_ad = [line[6:].strip()]
                current_ad_pmid = current_pmid
                continue

            if current_ad is not None:
                if line.startswith("      ") and not FIELD_RE.match(line):
                    current_ad.append(line.strip())
                    continue
                flush_current()

        flush_current()

    return stats


def build_alias_index(alias_rules: list[AliasRule]) -> dict[str, list[AliasRule]]:
    index: dict[str, list[AliasRule]] = defaultdict(list)
    for rule in alias_rules:
        first = rule.alias_norm.split(" ", 1)[0]
        index[first].append(rule)
    return index


def apply_canonical_precedence(candidate_ids: set[str]) -> set[str]:
    """Apply manual pairwise precedence to candidate canonical IDs."""
    resolved = set(candidate_ids)
    for preferred, demoted in CANONICAL_PRECEDENCE_RULES:
        if preferred in resolved and demoted in resolved:
            resolved.discard(demoted)
    return resolved


def classify_affiliation(
    ad_text: str,
    pmid_example: str,
    freq: int,
    alias_index: dict[str, list[AliasRule]],
) -> ClassifiedAffiliation:
    # Conservative split for merged affiliations in one AD field.
    # We only split on semicolons to avoid breaking common institution names.
    if ";" in ad_text:
        segments = [clean_affiliation(part) for part in ad_text.split(";")]
        segments = [s for s in segments if s]
        if len(segments) > 1:
            segment_results = [
                classify_affiliation_single(
                    ad_text=seg,
                    pmid_example=pmid_example,
                    freq=freq,
                    alias_index=alias_index,
                )
                for seg in segments
            ]

            matched = [r for r in segment_results if r.suggested_status == "matched"]
            ambiguous = [r for r in segment_results if r.suggested_status == "ambiguous"]

            if ambiguous:
                return ClassifiedAffiliation(
                    ad_text=ad_text,
                    pmid_example=pmid_example,
                    freq=freq,
                    suggested_status="ambiguous",
                    suggested_canonical_id="",
                    suggested_canonical_name="",
                    suggested_match_confidence="low",
                    matched_allow_aliases="|".join(
                        sorted(
                            {
                                alias
                                for r in segment_results
                                for alias in (r.matched_allow_aliases.split("|") if r.matched_allow_aliases else [])
                            }
                        )
                    ),
                    matched_review_aliases="|".join(
                        sorted(
                            {
                                alias
                                for r in segment_results
                                for alias in (r.matched_review_aliases.split("|") if r.matched_review_aliases else [])
                            }
                        )
                    ),
                    stratum="ambiguous",
                )

            if matched:
                cids = {r.suggested_canonical_id for r in matched}
                if len(cids) == 1:
                    best = sorted(
                        matched,
                        key=lambda r: (
                            0 if r.suggested_match_confidence == "high" else 1,
                            -len(r.matched_allow_aliases),
                        ),
                    )[0]
                    return ClassifiedAffiliation(
                        ad_text=ad_text,
                        pmid_example=pmid_example,
                        freq=freq,
                        suggested_status="matched",
                        suggested_canonical_id=best.suggested_canonical_id,
                        suggested_canonical_name=best.suggested_canonical_name,
                        suggested_match_confidence=best.suggested_match_confidence,
                        matched_allow_aliases=best.matched_allow_aliases,
                        matched_review_aliases=best.matched_review_aliases,
                        stratum="matched",
                    )

                return ClassifiedAffiliation(
                    ad_text=ad_text,
                    pmid_example=pmid_example,
                    freq=freq,
                    suggested_status="ambiguous",
                    suggested_canonical_id="",
                    suggested_canonical_name="",
                    suggested_match_confidence="low",
                    matched_allow_aliases="|".join(
                        sorted(
                            {
                                alias
                                for r in matched
                                for alias in (r.matched_allow_aliases.split("|") if r.matched_allow_aliases else [])
                            }
                        )
                    ),
                    matched_review_aliases="",
                    stratum="ambiguous",
                )

    return classify_affiliation_single(
        ad_text=ad_text,
        pmid_example=pmid_example,
        freq=freq,
        alias_index=alias_index,
    )


def classify_affiliation_single(
    ad_text: str,
    pmid_example: str,
    freq: int,
    alias_index: dict[str, list[AliasRule]],
) -> ClassifiedAffiliation:
    norm = normalize_text(ad_text)
    if not norm:
        return ClassifiedAffiliation(
            ad_text=ad_text,
            pmid_example=pmid_example,
            freq=freq,
            suggested_status="not_found",
            suggested_canonical_id="",
            suggested_canonical_name="",
            suggested_match_confidence="low",
            matched_allow_aliases="",
            matched_review_aliases="",
            stratum="not_found",
        )

    wrapped = f" {norm} "
    text_tokens = set(TOKEN_RE.findall(norm))

    allow_hits: list[AliasRule] = []
    review_hits: list[AliasRule] = []
    seen = set()

    for token in text_tokens:
        for rule in alias_index.get(token, []):
            key = (rule.alias_norm, rule.canonical_id, rule.policy)
            if key in seen:
                continue
            if f" {rule.alias_norm} " in wrapped:
                seen.add(key)
                if rule.policy == "allow":
                    allow_hits.append(rule)
                else:
                    review_hits.append(rule)

    allow_cids = sorted({r.canonical_id for r in allow_hits})
    resolved_allow_cids = sorted(apply_canonical_precedence(set(allow_cids)))
    review_cids = sorted({r.canonical_id for r in review_hits})

    matched_allow_aliases = "|".join(
        sorted({f"{r.alias_raw} ({r.alias_type})" for r in allow_hits})
    )
    matched_review_aliases = "|".join(
        sorted({f"{r.alias_raw} ({r.alias_type})" for r in review_hits})
    )

    if len(resolved_allow_cids) == 1:
        cid = resolved_allow_cids[0]
        cname = next(r.canonical_name for r in allow_hits if r.canonical_id == cid)
        conflicting_review = any(rid != cid for rid in review_cids)
        if conflicting_review:
            return ClassifiedAffiliation(
                ad_text=ad_text,
                pmid_example=pmid_example,
                freq=freq,
                suggested_status="ambiguous",
                suggested_canonical_id="",
                suggested_canonical_name="",
                suggested_match_confidence="low",
                matched_allow_aliases=matched_allow_aliases,
                matched_review_aliases=matched_review_aliases,
                stratum="ambiguous",
            )
        confidence = "high"
        if any(r.alias_type == "acronym" for r in allow_hits):
            confidence = "medium"
        if len(allow_cids) > 1:
            confidence = "medium"
        return ClassifiedAffiliation(
            ad_text=ad_text,
            pmid_example=pmid_example,
            freq=freq,
            suggested_status="matched",
            suggested_canonical_id=cid,
            suggested_canonical_name=cname,
            suggested_match_confidence=confidence,
            matched_allow_aliases=matched_allow_aliases,
            matched_review_aliases=matched_review_aliases,
            stratum="matched",
        )

    if len(resolved_allow_cids) > 1 or review_hits:
        return ClassifiedAffiliation(
            ad_text=ad_text,
            pmid_example=pmid_example,
            freq=freq,
            suggested_status="ambiguous",
            suggested_canonical_id="",
            suggested_canonical_name="",
            suggested_match_confidence="low",
            matched_allow_aliases=matched_allow_aliases,
            matched_review_aliases=matched_review_aliases,
            stratum="ambiguous",
        )

    return ClassifiedAffiliation(
        ad_text=ad_text,
        pmid_example=pmid_example,
        freq=freq,
        suggested_status="not_found",
        suggested_canonical_id="",
        suggested_canonical_name="",
        suggested_match_confidence="low",
        matched_allow_aliases="",
        matched_review_aliases="",
        stratum="not_found",
    )


def stratified_selection(
    rows: list[ClassifiedAffiliation],
    target_matched: int,
    target_ambiguous: int,
    target_not_found: int,
    random_seed: int,
) -> list[ClassifiedAffiliation]:
    by_stratum: dict[str, list[ClassifiedAffiliation]] = defaultdict(list)
    for row in rows:
        by_stratum[row.stratum].append(row)

    for items in by_stratum.values():
        items.sort(key=lambda r: (-r.freq, r.ad_text))

    selected: list[ClassifiedAffiliation] = []
    selected.extend(by_stratum["matched"][:target_matched])
    selected.extend(by_stratum["ambiguous"][:target_ambiguous])

    # Keep a mix of frequent and long-tail not_found examples.
    not_found = by_stratum["not_found"]
    top_n = min(target_not_found // 2, len(not_found))
    selected.extend(not_found[:top_n])
    remaining_needed = target_not_found - top_n
    tail = not_found[top_n:]
    rng = random.Random(random_seed)
    if remaining_needed > 0 and tail:
        if len(tail) <= remaining_needed:
            selected.extend(tail)
        else:
            selected.extend(rng.sample(tail, remaining_needed))

    selected.sort(key=lambda r: (-r.freq, r.stratum, r.ad_text))
    return selected


def write_test_set(path: Path, rows: list[ClassifiedAffiliation]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(
            fh,
            fieldnames=[
                "test_id",
                "stratum",
                "pmid_example",
                "ad_frequency",
                "ad_text",
                "suggested_status",
                "suggested_canonical_id",
                "suggested_canonical_name",
                "suggested_match_confidence",
                "matched_allow_aliases",
                "matched_review_aliases",
                "expected_status",
                "expected_canonical_id",
                "expected_canonical_name",
                "review_notes",
            ],
        )
        writer.writeheader()
        for i, row in enumerate(rows, start=1):
            writer.writerow(
                {
                    "test_id": f"T{i:04d}",
                    "stratum": row.stratum,
                    "pmid_example": row.pmid_example,
                    "ad_frequency": row.freq,
                    "ad_text": row.ad_text,
                    "suggested_status": row.suggested_status,
                    "suggested_canonical_id": row.suggested_canonical_id,
                    "suggested_canonical_name": row.suggested_canonical_name,
                    "suggested_match_confidence": row.suggested_match_confidence,
                    "matched_allow_aliases": row.matched_allow_aliases,
                    "matched_review_aliases": row.matched_review_aliases,
                    "expected_status": "",
                    "expected_canonical_id": "",
                    "expected_canonical_name": "",
                    "review_notes": "",
                }
            )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--combined",
        type=Path,
        default=Path("combined.txt"),
        help="MEDLINE-style input containing AD fields.",
    )
    parser.add_argument(
        "--institutions",
        type=Path,
        default=Path("niaid_org_seed_master.csv"),
        help="Institution table with canonical IDs.",
    )
    parser.add_argument(
        "--alias-policy",
        type=Path,
        default=Path("alias_policy_review.tsv"),
        help="Alias policy TSV (allow/review_only/deny).",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=Path("combined_affiliation_test_set_draft.csv"),
        help="Output CSV path.",
    )
    parser.add_argument("--target-matched", type=int, default=200)
    parser.add_argument("--target-ambiguous", type=int, default=120)
    parser.add_argument("--target-not-found", type=int, default=80)
    parser.add_argument("--seed", type=int, default=42)
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    alias_rules = load_alias_rules(args.institutions, args.alias_policy)
    alias_index = build_alias_index(alias_rules)
    affiliation_stats = parse_ad_affiliations(args.combined)

    classified_rows = [
        classify_affiliation(
            ad_text=ad_text,
            pmid_example=stats.pmid_example,
            freq=stats.freq,
            alias_index=alias_index,
        )
        for ad_text, stats in affiliation_stats.items()
    ]

    selected = stratified_selection(
        rows=classified_rows,
        target_matched=args.target_matched,
        target_ambiguous=args.target_ambiguous,
        target_not_found=args.target_not_found,
        random_seed=args.seed,
    )
    write_test_set(args.out, selected)

    total = len(classified_rows)
    strat_counts = Counter(r.stratum for r in classified_rows)
    selected_counts = Counter(r.stratum for r in selected)
    print(f"Parsed unique AD affiliations: {total}")
    print(
        "Universe strata:",
        ", ".join(f"{k}={strat_counts.get(k, 0)}" for k in ["matched", "ambiguous", "not_found"]),
    )
    print(
        "Selected strata:",
        ", ".join(f"{k}={selected_counts.get(k, 0)}" for k in ["matched", "ambiguous", "not_found"]),
    )
    print(f"Wrote {len(selected)} rows to {args.out}")


if __name__ == "__main__":
    main()

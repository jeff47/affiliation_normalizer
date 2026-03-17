"""Data models for affiliation normalization."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, NotRequired, TypedDict


MatchStatus = Literal["matched", "ambiguous", "not_found"]
MatchReason = Literal[
    "precedence_or_direct_match",
    "longest_alias_tiebreak",
    "email_domain_match",
    "email_domain_disambiguation",
    "ror_match",
    "grid_match",
    "multiple_candidates",
    "email_domain_multiple_candidates",
    "ror_multiple_candidates",
    "grid_multiple_candidates",
    "no_match",
    "review_only_match",
    "geo_policy_no_match",
    "multi_author_input",
    "empty_input",
    "empty_ror",
    "invalid_ror",
    "no_ror_match",
    "empty_grid",
    "invalid_grid",
    "no_grid_match",
    "empty_email_domain",
    "invalid_email_domain",
    "no_email_domain_match",
]


class InstitutionRule(TypedDict):
    canonical_id: str
    canonical_name: str
    city: str
    state: str
    country: str
    ror_id: str
    grid_id: str
    email_domains: str
    openalex_id: str
    nih_reporter_name: NotRequired[str]
    nih_reporter_ipf_code: NotRequired[str]


class AliasRuleRecord(TypedDict):
    alias: str
    alias_norm: str
    canonical_id: str
    alias_type: str
    policy: str


class PrecedenceRuleRecord(TypedDict):
    preferred: str
    demoted: str
    reason: str


class RulesPayload(TypedDict):
    institutions: dict[str, InstitutionRule]
    alias_rules: list[AliasRuleRecord]
    precedence_rules: list[PrecedenceRuleRecord]


@dataclass(frozen=True)
class AliasHit:
    """Alias evidence for a candidate institution."""

    alias: str
    alias_type: str
    policy: str


@dataclass(frozen=True)
class MatchResult:
    """Normalized affiliation match output.

    ``reason`` is intended for caller branching and operational inspection.
    The string values used by the runtime API are documented in the package
    README and should be treated as part of the public contract.

    ``confidence`` is a coarse heuristic in the range ``0.0`` to ``1.0``.
    It is not a calibrated probability and should not be treated as stable for
    thresholding across releases unless the documentation says otherwise.
    """

    status: MatchStatus
    reason: MatchReason
    canonical_id: str | None = None
    canonical_name: str | None = None
    standardized_name: str | None = None
    city: str | None = None
    state: str | None = None
    country: str | None = None
    ror_id: str | None = None
    grid_id: str | None = None
    openalex_id: str | None = None
    confidence: float = 0.0
    matched_aliases: tuple[AliasHit, ...] = field(default_factory=tuple)
    candidate_ids: tuple[str, ...] = field(default_factory=tuple)

    @property
    def matched(self) -> bool:
        return self.status == "matched"

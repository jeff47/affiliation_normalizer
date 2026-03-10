#!/usr/bin/env python3
"""Resolve author affiliations from a PMID list via OpenAlex + ROR.

Workflow:
1) Resolve target OpenAlex author from ORCID.
2) For each PMID: fetch DOI from OpenAlex.
3) Fetch work by DOI from OpenAlex (fallback to PMID work if DOI lookup fails).
4) Keep authorships for the target author ID.
5) Extract institution ROR IDs and collapse to university-level parents when possible.

Outputs:
- <stem>.rows.tsv: one row per matched institution (plus explicit status rows for misses).
- <stem>.collapsed.tsv: collapsed institution counts for quick review.
"""

from __future__ import annotations

import argparse
import csv
import json
import logging
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

import simplify_affiliations as sa

LOGGER = logging.getLogger("openalex_affiliations")
OPENALEX_BASE = "https://api.openalex.org"


def normalize_orcid(orcid: str) -> str:
    value = orcid.strip()
    if value.lower().startswith("https://orcid.org/"):
        value = value.rsplit("/", 1)[-1]
    return value


def parse_ror_id(value: str | None) -> str:
    if not value:
        return ""
    text = value.strip()
    if not text:
        return ""
    if "ror.org/" in text:
        return text.rsplit("/", 1)[-1].lower()
    return text.lower()


def doi_short(doi_url_or_id: str | None) -> str:
    if not doi_url_or_id:
        return ""
    value = doi_url_or_id.strip()
    if not value:
        return ""
    if value.lower().startswith("https://doi.org/"):
        return value.split("/", 3)[-1]
    return value


def openalex_get_json(
    path: str,
    params: dict[str, str] | None,
    timeout_seconds: float,
    mailto: str | None,
    retries: int = 2,
) -> dict[str, Any]:
    query = dict(params or {})
    if mailto:
        query["mailto"] = mailto
    url = f"{OPENALEX_BASE}{path}"
    if query:
        url += "?" + urllib.parse.urlencode(query)

    attempt = 0
    while True:
        try:
            req = urllib.request.Request(url=url, headers={"Accept": "application/json"}, method="GET")
            with urllib.request.urlopen(req, timeout=timeout_seconds) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError):
            if attempt >= retries:
                raise
            sleep_s = 0.5 * (attempt + 1)
            time.sleep(sleep_s)
            attempt += 1


def resolve_openalex_author_from_orcid(
    orcid: str,
    timeout_seconds: float,
    mailto: str | None,
) -> tuple[str, str]:
    normalized = normalize_orcid(orcid)
    lookup = f"https://orcid.org/{normalized}"
    data = openalex_get_json(
        path="/authors",
        params={"filter": f"orcid:{lookup}", "select": "id,display_name,orcid"},
        timeout_seconds=timeout_seconds,
        mailto=mailto,
    )
    results = data.get("results", [])
    if not isinstance(results, list) or not results:
        raise RuntimeError(f"No OpenAlex author found for ORCID {lookup}")

    author = results[0]
    if not isinstance(author, dict):
        raise RuntimeError(f"Unexpected OpenAlex author payload for ORCID {lookup}")
    author_id_url = author.get("id")
    display_name = author.get("display_name", "")
    if not isinstance(author_id_url, str) or "/A" not in author_id_url:
        raise RuntimeError(f"OpenAlex author id missing/invalid for ORCID {lookup}")
    author_id = author_id_url.rsplit("/", 1)[-1]
    return author_id, str(display_name or "")


def openalex_work_by_pmid(
    pmid: str,
    timeout_seconds: float,
    mailto: str | None,
) -> dict[str, Any] | None:
    data = openalex_get_json(
        path="/works",
        params={"filter": f"pmid:{pmid}", "select": "id,doi,ids,authorships"},
        timeout_seconds=timeout_seconds,
        mailto=mailto,
    )
    results = data.get("results", [])
    if isinstance(results, list) and results:
        first = results[0]
        if isinstance(first, dict):
            return first
    return None


def openalex_work_by_doi(
    doi: str,
    timeout_seconds: float,
    mailto: str | None,
) -> dict[str, Any] | None:
    data = openalex_get_json(
        path="/works",
        params={"filter": f"doi:{doi}", "select": "id,doi,ids,authorships"},
        timeout_seconds=timeout_seconds,
        mailto=mailto,
    )
    results = data.get("results", [])
    if isinstance(results, list) and results:
        first = results[0]
        if isinstance(first, dict):
            return first
    return None


def ror_display_name(record: dict[str, Any]) -> str:
    names = record.get("names", [])
    if isinstance(names, list):
        for name in names:
            if isinstance(name, dict) and "ror_display" in (name.get("types") or []):
                value = str(name.get("value") or "").strip()
                if value:
                    return sa.tidy_label(value)
        for name in names:
            if isinstance(name, dict):
                value = str(name.get("value") or "").strip()
                if value:
                    return sa.tidy_label(value)
    fallback = str(record.get("name") or "").strip()
    return sa.tidy_label(fallback)


def ror_org_record(
    ror_id: str,
    timeout_seconds: float,
    cache: dict[str, dict[str, Any] | None],
) -> dict[str, Any] | None:
    rid = parse_ror_id(ror_id)
    if not rid:
        return None
    if rid in cache:
        return cache[rid]
    try:
        data = sa.ror_api_get_json(
            url=f"https://api.ror.org/v2/organizations/{rid}",
            client_id=None,
            timeout_seconds=timeout_seconds,
        )
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError):
        cache[rid] = None
        return None
    if not isinstance(data, dict):
        cache[rid] = None
        return None
    cache[rid] = data
    return data


def collapse_to_university(
    ror_id: str,
    timeout_seconds: float,
    cache: dict[str, dict[str, Any] | None],
) -> tuple[str, str, str]:
    rid = parse_ror_id(ror_id)
    if not rid:
        return "", "", "no-ror"

    start = ror_org_record(rid, timeout_seconds=timeout_seconds, cache=cache)
    if start is None:
        return "", "", "ror-fetch-failed"

    start_name = ror_display_name(start)
    start_types = {str(t).lower() for t in (start.get("types") or []) if isinstance(t, str)}
    if "education" in start_types:
        return start_name, rid, "self-education"

    # Walk parent links to find first education institution.
    visited = {rid}
    frontier = [start]
    depth = 0
    while frontier and depth < 5:
        next_frontier: list[dict[str, Any]] = []
        for node in frontier:
            relations = node.get("relationships", [])
            if not isinstance(relations, list):
                continue
            for rel in relations:
                if not isinstance(rel, dict):
                    continue
                rel_type = str(rel.get("type") or "").lower()
                if rel_type != "parent":
                    continue
                parent_id = parse_ror_id(str(rel.get("id") or ""))
                if not parent_id or parent_id in visited:
                    continue
                visited.add(parent_id)
                parent = ror_org_record(parent_id, timeout_seconds=timeout_seconds, cache=cache)
                if parent is None:
                    continue
                parent_types = {
                    str(t).lower() for t in (parent.get("types") or []) if isinstance(t, str)
                }
                parent_name = ror_display_name(parent)
                if "education" in parent_types:
                    return parent_name, parent_id, f"parent-education-depth-{depth+1}"
                next_frontier.append(parent)
        frontier = next_frontier
        depth += 1

    return start_name, rid, "no-education-parent"


def parse_pmid_file(path: Path) -> list[str]:
    out: list[str] = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        value = raw.strip()
        if not value:
            continue
        if value.startswith("#"):
            continue
        out.append(value)
    return out


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--orcid", required=True, help="Target author ORCID (URL or bare id).")
    parser.add_argument("--pmid-file", type=Path, required=True, help="File with one PMID per line.")
    parser.add_argument(
        "--output-stem",
        type=Path,
        default=None,
        help="Output stem. Defaults to <pmid file stem>.openalex_author_affiliations",
    )
    parser.add_argument(
        "--mailto",
        type=str,
        default=None,
        help="Optional email for OpenAlex polite pool parameter.",
    )
    parser.add_argument(
        "--timeout-seconds",
        type=float,
        default=8.0,
        help="HTTP timeout in seconds.",
    )
    parser.add_argument(
        "--pause-seconds",
        type=float,
        default=0.1,
        help="Pause between PMID iterations to avoid flooding APIs.",
    )
    parser.add_argument(
        "--max-pmids",
        type=int,
        default=-1,
        help="Process at most this many PMIDs (default: all).",
    )
    parser.add_argument(
        "--log-level",
        type=str,
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Log verbosity.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    logging.basicConfig(level=getattr(logging, args.log_level), format="%(levelname)s %(message)s")

    pmids = parse_pmid_file(args.pmid_file)
    if args.max_pmids >= 0:
        pmids = pmids[: args.max_pmids]
    if not pmids:
        raise RuntimeError(f"No PMIDs found in {args.pmid_file}")

    output_stem = (
        args.output_stem
        if args.output_stem is not None
        else args.pmid_file.with_name(f"{args.pmid_file.stem}.openalex_author_affiliations")
    )
    rows_path = output_stem.with_name(output_stem.name + ".rows.tsv")
    collapsed_path = output_stem.with_name(output_stem.name + ".collapsed.tsv")

    author_id, author_name = resolve_openalex_author_from_orcid(
        orcid=args.orcid,
        timeout_seconds=args.timeout_seconds,
        mailto=args.mailto,
    )
    LOGGER.info("Target author: %s (%s)", author_name, author_id)

    ror_cache: dict[str, dict[str, Any] | None] = {}
    out_rows: list[dict[str, str]] = []

    for idx, pmid in enumerate(pmids, start=1):
        pmid_work = openalex_work_by_pmid(
            pmid=pmid,
            timeout_seconds=args.timeout_seconds,
            mailto=args.mailto,
        )
        if pmid_work is None:
            out_rows.append(
                {
                    "pmid": pmid,
                    "doi": "",
                    "openalex_work_id": "",
                    "target_orcid": normalize_orcid(args.orcid),
                    "target_openalex_author_id": author_id,
                    "target_openalex_author_name": author_name,
                    "authorship_author_name": "",
                    "author_position": "",
                    "raw_affiliation_strings": "",
                    "openalex_institution_id": "",
                    "openalex_institution_name": "",
                    "openalex_institution_ror": "",
                    "openalex_institution_country": "",
                    "ror_official_name": "",
                    "collapsed_name": "",
                    "collapsed_ror_id": "",
                    "collapse_method": "",
                    "status": "pmid-not-found",
                }
            )
            continue

        doi = doi_short(str(pmid_work.get("doi") or ""))
        work = pmid_work
        if doi:
            doi_work = openalex_work_by_doi(
                doi=doi,
                timeout_seconds=args.timeout_seconds,
                mailto=args.mailto,
            )
            if doi_work is not None:
                work = doi_work

        work_id = str(work.get("id") or "")
        authorships = work.get("authorships", [])
        matched_authorships: list[dict[str, Any]] = []
        if isinstance(authorships, list):
            for auth in authorships:
                if not isinstance(auth, dict):
                    continue
                author_obj = auth.get("author") or {}
                if not isinstance(author_obj, dict):
                    continue
                aid = str(author_obj.get("id") or "")
                if aid.rsplit("/", 1)[-1] == author_id:
                    matched_authorships.append(auth)

        if not matched_authorships:
            out_rows.append(
                {
                    "pmid": pmid,
                    "doi": doi,
                    "openalex_work_id": work_id,
                    "target_orcid": normalize_orcid(args.orcid),
                    "target_openalex_author_id": author_id,
                    "target_openalex_author_name": author_name,
                    "authorship_author_name": "",
                    "author_position": "",
                    "raw_affiliation_strings": "",
                    "openalex_institution_id": "",
                    "openalex_institution_name": "",
                    "openalex_institution_ror": "",
                    "openalex_institution_country": "",
                    "ror_official_name": "",
                    "collapsed_name": "",
                    "collapsed_ror_id": "",
                    "collapse_method": "",
                    "status": "author-not-on-work",
                }
            )
            if args.pause_seconds > 0:
                time.sleep(args.pause_seconds)
            continue

        for auth in matched_authorships:
            author_obj = auth.get("author") or {}
            author_display = str(author_obj.get("display_name") or "")
            author_position = str(auth.get("author_position") or "")
            raw_affiliations = auth.get("raw_affiliation_strings") or []
            if isinstance(raw_affiliations, list):
                raw_aff = " | ".join(str(x).strip() for x in raw_affiliations if str(x).strip())
            else:
                raw_aff = ""

            institutions = auth.get("institutions") or []
            if not isinstance(institutions, list) or not institutions:
                out_rows.append(
                    {
                        "pmid": pmid,
                        "doi": doi,
                        "openalex_work_id": work_id,
                        "target_orcid": normalize_orcid(args.orcid),
                        "target_openalex_author_id": author_id,
                        "target_openalex_author_name": author_name,
                        "authorship_author_name": author_display,
                        "author_position": author_position,
                        "raw_affiliation_strings": raw_aff,
                        "openalex_institution_id": "",
                        "openalex_institution_name": "",
                        "openalex_institution_ror": "",
                        "openalex_institution_country": "",
                        "ror_official_name": "",
                        "collapsed_name": "",
                        "collapsed_ror_id": "",
                        "collapse_method": "",
                        "status": "author-has-no-institutions",
                    }
                )
                continue

            for inst in institutions:
                if not isinstance(inst, dict):
                    continue
                inst_id = str(inst.get("id") or "")
                inst_name = str(inst.get("display_name") or "")
                inst_ror = parse_ror_id(str(inst.get("ror") or ""))
                inst_country = str(inst.get("country_code") or "")

                ror_official = ""
                collapsed_name = ""
                collapsed_ror = ""
                collapse_method = "no-ror-on-openalex"
                if inst_ror:
                    record = ror_org_record(inst_ror, timeout_seconds=args.timeout_seconds, cache=ror_cache)
                    if record is not None:
                        ror_official = ror_display_name(record)
                    collapsed_name, collapsed_ror, collapse_method = collapse_to_university(
                        inst_ror,
                        timeout_seconds=args.timeout_seconds,
                        cache=ror_cache,
                    )

                if not collapsed_name:
                    collapsed_name = ror_official or inst_name
                if not collapsed_ror:
                    collapsed_ror = inst_ror

                out_rows.append(
                    {
                        "pmid": pmid,
                        "doi": doi,
                        "openalex_work_id": work_id,
                        "target_orcid": normalize_orcid(args.orcid),
                        "target_openalex_author_id": author_id,
                        "target_openalex_author_name": author_name,
                        "authorship_author_name": author_display,
                        "author_position": author_position,
                        "raw_affiliation_strings": raw_aff,
                        "openalex_institution_id": inst_id.rsplit("/", 1)[-1] if inst_id else "",
                        "openalex_institution_name": inst_name,
                        "openalex_institution_ror": inst_ror,
                        "openalex_institution_country": inst_country,
                        "ror_official_name": ror_official,
                        "collapsed_name": collapsed_name,
                        "collapsed_ror_id": collapsed_ror,
                        "collapse_method": collapse_method,
                        "status": "matched",
                    }
                )

        if idx % 25 == 0:
            LOGGER.info("Processed %d/%d PMIDs", idx, len(pmids))
        if args.pause_seconds > 0:
            time.sleep(args.pause_seconds)

    fieldnames = [
        "pmid",
        "doi",
        "openalex_work_id",
        "target_orcid",
        "target_openalex_author_id",
        "target_openalex_author_name",
        "authorship_author_name",
        "author_position",
        "raw_affiliation_strings",
        "openalex_institution_id",
        "openalex_institution_name",
        "openalex_institution_ror",
        "openalex_institution_country",
        "ror_official_name",
        "collapsed_name",
        "collapsed_ror_id",
        "collapse_method",
        "status",
    ]
    with rows_path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames, delimiter="\t")
        writer.writeheader()
        writer.writerows(out_rows)

    # Aggregate matched rows by collapsed institution.
    collapsed_counter: Counter[tuple[str, str]] = Counter()
    collapsed_pmids: defaultdict[tuple[str, str], set[str]] = defaultdict(set)
    for row in out_rows:
        if row["status"] != "matched":
            continue
        key = (row["collapsed_name"], row["collapsed_ror_id"])
        collapsed_counter[key] += 1
        collapsed_pmids[key].add(row["pmid"])

    collapsed_rows = []
    for (name, rid), n in collapsed_counter.most_common():
        collapsed_rows.append(
            {
                "collapsed_name": name,
                "collapsed_ror_id": rid,
                "rows_count": str(n),
                "pmid_count": str(len(collapsed_pmids[(name, rid)])),
                "example_pmids": ",".join(sorted(collapsed_pmids[(name, rid)])[:10]),
            }
        )
    with collapsed_path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(
            fh,
            fieldnames=[
                "collapsed_name",
                "collapsed_ror_id",
                "rows_count",
                "pmid_count",
                "example_pmids",
            ],
            delimiter="\t",
        )
        writer.writeheader()
        writer.writerows(collapsed_rows)

    status_counts = Counter(row["status"] for row in out_rows)
    LOGGER.info("Wrote rows: %s", rows_path)
    LOGGER.info("Wrote collapsed summary: %s", collapsed_path)
    LOGGER.info("Status counts: %s", dict(status_counts))


if __name__ == "__main__":
    main()

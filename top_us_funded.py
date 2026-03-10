#!/usr/bin/env python3

import collections
import csv
import time
import requests

URL = "https://api.reporter.nih.gov/v2/projects/search"
YEARS = [2020, 2021, 2022, 2023, 2024, 2025]
TOPX = 200

FULL_OUT = "top" + str(TOPX) + "_niaid_orgs_working_2021_2025.csv"
SEED_OUT = "niaid_org_seed.csv"

session = requests.Session()
session.headers.update({"User-Agent": "niaid-org-extractor/0.1"})

# Aggregate by NIH org_name. Keep city/state/IPF for review and downstream cleanup.
by_org = collections.defaultdict(
    lambda: {
        "awards": 0,
        "funding": 0,
        "projects": set(),
        "fiscal_years": set(),
        "org_city": None,
        "org_state": None,
        "org_ipf_code": None,
    }
)


def fetch_one_page(fiscal_year: int, offset: int, limit: int = 500) -> dict:
    payload = {
        "criteria": {
            "agencies": ["NIAID"],
            "org_countries": ["UNITED STATES"],
            "fiscal_years": [fiscal_year],
        },
        # "Organization" is needed here; OrgName alone was not returned in earlier tests.
        "include_fields": [
            "FiscalYear",
            "AwardAmount",
            "CoreProjectNum",
            "Organization",
        ],
        "offset": offset,
        "limit": limit,
    }

    r = session.post(URL, json=payload, timeout=60)
    if r.status_code != 200:
        print(f"HTTP {r.status_code} for FY {fiscal_year}, offset {offset}")
        print(r.text)
        r.raise_for_status()
    return r.json()


def update_aggregate(row: dict, default_fy: int) -> bool:
    org_obj = row.get("organization") or {}
    org_name = org_obj.get("org_name")
    if not org_name:
        return False

    rec = by_org[org_name]

    rec["awards"] += 1
    rec["funding"] += row.get("award_amount") or 0

    core = row.get("core_project_num")
    if core:
        rec["projects"].add(core)

    fiscal_year = row.get("fiscal_year") or default_fy
    rec["fiscal_years"].add(fiscal_year)

    # Keep first non-empty value seen. These should usually be stable for a given org.
    if not rec["org_city"] and org_obj.get("org_city"):
        rec["org_city"] = org_obj.get("org_city")
    if not rec["org_state"] and org_obj.get("org_state"):
        rec["org_state"] = org_obj.get("org_state")
    if not rec["org_ipf_code"] and org_obj.get("org_ipf_code"):
        rec["org_ipf_code"] = str(org_obj.get("org_ipf_code"))

    return True


def build_rows() -> list[dict]:
    rows = []
    for org_name, vals in by_org.items():
        rows.append(
            {
                "org_name": org_name,
                "org_city": vals["org_city"] or "",
                "org_state": vals["org_state"] or "",
                "org_ipf_code": vals["org_ipf_code"] or "",
                "awards": vals["awards"],
                "unique_projects": len(vals["projects"]),
                "funding": vals["funding"],
                "min_fy": min(vals["fiscal_years"]) if vals["fiscal_years"] else "",
                "max_fy": max(vals["fiscal_years"]) if vals["fiscal_years"] else "",
            }
        )

    # Rank by unique projects first, then total funding.
    rows.sort(key=lambda x: (-x["unique_projects"], -x["funding"], x["org_name"]))
    return rows


def write_working_csv(rows: list[dict], path: str) -> None:
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(
            f,
            fieldnames=[
                "org_name",
                "org_city",
                "org_state",
                "org_ipf_code",
                "awards",
                "unique_projects",
                "funding",
                "min_fy",
                "max_fy",
            ],
        )
        w.writeheader()
        w.writerows(rows)


def write_seed_csv(rows: list[dict], path: str, top_n: int = 100) -> None:
    # Final lightweight file requested: org_name, org_city, org_state, org_ipf_code
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(
            f,
            fieldnames=["org_name", "org_city", "org_state", "org_ipf_code"],
        )
        w.writeheader()
        for row in rows[:top_n]:
            w.writerow(
                {
                    "org_name": row["org_name"],
                    "org_city": row["org_city"],
                    "org_state": row["org_state"],
                    "org_ipf_code": row["org_ipf_code"],
                }
            )


def main() -> None:
    limit = 500

    for fy in YEARS:
        offset = 0

        while True:
            data = fetch_one_page(fy, offset, limit=limit)
            results = data.get("results", [])
            meta = data.get("meta", {})

            if not results:
                break

            added = 0
            for row in results:
                if update_aggregate(row, fy):
                    added += 1

            fetched = min(offset + limit, meta.get("total", 0))
            print(f"FY {fy}: fetched {fetched}/{meta.get('total', 0)} ; added={added}")

            offset += limit
            if offset >= meta.get("total", 0):
                break

            time.sleep(0.2)

    rows = build_rows()

    print(f"Distinct organizations found: {len(rows)}")
    for row in rows[:15]:
        print(row)

    total = sum(r["unique_projects"] for r in rows)

    running = 0
    for i, r in enumerate(rows[:TOPX], 1):
        running += r["unique_projects"]
        pct = running / total * 100
        print(i, r["org_name"], f"{pct:.1f}%")

    write_working_csv(rows, FULL_OUT)
    write_seed_csv(rows, SEED_OUT, top_n=TOPX)

    print(f"Wrote {FULL_OUT}")
    print(f"Wrote {SEED_OUT}")


if __name__ == "__main__":
    main()

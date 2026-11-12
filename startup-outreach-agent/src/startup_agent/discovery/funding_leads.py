"""Read recent early-stage technology leads from bharat.digital's CC BY 4.0 CSV."""

import csv
from datetime import date, datetime, timedelta
from io import StringIO
from urllib.parse import urlsplit

from startup_agent.utils.http_client import HttpClient

TRACKER_URL = "https://bharat.digital/startups/funding/"
CSV_URL = "https://bharat.digital/startups/funding.csv"
LICENSE_URL = "https://bharat.digital/license/"
STAGES = {"pre-seed", "seed", "angel", "series a"}
CATEGORIES = {"ai", "deep tech", "saas", "security", "climate tech", "fintech & payments", "govtech"}


def print_funding_leads(reviewed_companies: dict, *, portfolio_companies: list[dict] | None = None,
                        today: date | None = None) -> None:
    today = today or datetime.now().astimezone().date()
    cutoff = today - timedelta(days=30)
    response = HttpClient().get(CSV_URL)
    reader = csv.DictReader(StringIO(response.text.lstrip("\ufeff")))
    if not {"startup", "first_reported", "stage", "category", "url_1"}.issubset(reader.fieldnames or ()):
        raise ValueError("The funding CSV is missing expected columns.")
    leads = []
    for row in reader:
        name = (row["startup"] or "").strip()
        stage = (row["stage"] or "").strip()
        category = (row["category"] or "").strip()
        source = (row["url_1"] or "").strip()
        if not name or stage.casefold() not in STAGES or category.casefold() not in CATEGORIES:
            continue
        try:
            reported = date.fromisoformat(row["first_reported"] or "")
        except ValueError:
            continue
        if not cutoff <= reported <= today or urlsplit(source).scheme not in {"http", "https"}:
            continue
        leads.append((reported, name, stage, category, source))

    print(f"Funding leads from bharat.digital (CC BY 4.0)\n{TRACKER_URL}\nLicense: {LICENSE_URL}\n")
    seen = set()
    for reported, name, stage, category, source in sorted(leads, reverse=True):
        key = " ".join(name.casefold().split())
        if key in seen:
            continue
        seen.add(key)
        print(f"{reported} | {name} | {stage} | {category}\n  Funding report: {source}")
        reviewed = reviewed_companies.get(key)
        if reviewed:
            print(f"  Careers: {reviewed['careers_url']}")
            print(f"  Published size: {reviewed['employee_count']} ({reviewed['source_url']})")
            if reviewed.get("hiring_email"):
                print(f"  Hiring inbox listed on careers page: {reviewed['hiring_email']}")
        else:
            print("  Employer domain, size, and openings need review.")
    print(f"\n{len(seen)} funding leads from the past 30 days.")
    if portfolio_companies:
        print("\nReviewed portfolio employers")
        for company in portfolio_companies:
            print(f"  {company['company_name']} | {company['employee_count']} employees")
            print(f"    Portfolio: {company['discovery_url']}")
            print(f"    Careers: {company['careers_url']}")

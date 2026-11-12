"""Publish the locally ranked shortlist to the hosted review service."""

import hashlib
import hmac
import json
import os
import re
import time

import httpx
import yaml
from bs4 import BeautifulSoup
from sqlalchemy import select
from sqlalchemy.orm import Session

from startup_agent.config.settings import Settings
from startup_agent.database.models import CompanyModel, JobModel
from startup_agent.digest import format_digest
from startup_agent.routing import build_outreach_routes
from startup_agent.matching.profile import CandidateProfile
from startup_agent.matching.startup_filter import StartupEligibilityFilter, StartupEligibilityStatus
from startup_agent.utils.normalizers import normalize_website
from startup_agent.utils.http_client import HttpClient


def cold_enquiry_cards(session: Session, settings: Settings, companies_with_matches: set[str]) -> list[dict]:
    path = settings.config_dir / "hiring_contacts.yaml"
    contacts = (yaml.safe_load(path.read_text(encoding="utf-8")) or {}) if path.is_file() else {}
    profile = CandidateProfile.load(settings.config_dir / "candidate_profile.yaml")
    size_filter = StartupEligibilityFilter(max_employees=profile.preferences.small_startup_max_employees)
    companies = {
        company.normalized_website: company for company in session.scalars(select(CompanyModel))
    }
    client = HttpClient()
    cards = []
    seen_domains = set()
    for entry in contacts.values():
        if entry.get("accepts_enquiries") is not True:
            continue
        recipient = entry["email"].strip().lower()
        source = entry["source_url"]
        domain = recipient.rsplit("@", 1)[-1]
        if not re.fullmatch(r"[a-z0-9._+%-]+@[a-z0-9.-]+\.[a-z]{2,}", recipient):
            continue
        if not source.startswith("https://") or normalize_website(source).split("/", 1)[0] != domain:
            continue
        company = companies.get(domain)
        if not company or domain in seen_domains or company.normalized_name in companies_with_matches:
            continue
        if size_filter.evaluate(company.employee_count).status != StartupEligibilityStatus.ELIGIBLE:
            continue
        try:
            page = BeautifulSoup(client.get(source).text, "html.parser")
        except httpx.HTTPError:
            continue
        published = recipient in page.get_text(" ", strip=True).casefold() or any(
            str(link.get("href", "")).split("?", 1)[0].casefold() == f"mailto:{recipient}"
            for link in page.find_all("a", href=True)
        )
        if not published:
            continue
        seen_domains.add(domain)
        project = next((item for item in profile.projects if "full_stack" in item.outreach_roles), None)
        evidence = f" One of my recent projects is {project.title}. {project.description}" if project else ""
        cards.append({
            "job_url": f"https://{domain}/#outreach-enquiry",
            "text": f"Internship enquiry @ {company.company_name}",
            "draft": {
                "recipient": recipient,
                "subject": "Software engineering internship enquiry",
                "body": (
                    f"Hi {company.company_name} hiring team,\n\n"
                    f"I'm {profile.name}, a computer science student looking for a software engineering internship."
                    f"{evidence}\n\n"
                    "Are you open to internship enquiries for your engineering team? "
                    "I've attached my resume for context.\n\n"
                    f"Thanks,\n{profile.name}"
                ),
                "source_url": source,
            },
        })
    return cards


def publish_hosted_shortlist(session: Session, settings: Settings) -> int:
    endpoint = os.getenv("OUTREACH_WEB_APP_URL", "").strip()
    secret = os.getenv("OUTREACH_SYNC_SECRET", "").strip()
    run_id = os.getenv("GITHUB_RUN_ID") or f"local-{time.time_ns()}"
    if not re.fullmatch(r"https://script\.google\.com/macros/s/[\w-]+/exec", endpoint) or len(secret) < 32:
        raise ValueError("Set OUTREACH_WEB_APP_URL and an OUTREACH_SYNC_SECRET of at least 32 characters.")

    job_urls = dict(session.execute(select(JobModel.id, JobModel.normalized_job_url)).all())
    routes = [route for route in build_outreach_routes(session, settings) if route.job_id is not None and route.url]
    cards = [
        {"job_url": job_urls[route.job_id], "text": format_digest([route]).split("\n\n", 1)[1]}
        for route in routes
    ]
    matching_companies = set(session.scalars(
        select(CompanyModel.normalized_name).join(JobModel).where(JobModel.id.in_([route.job_id for route in routes]))
    ))
    cards.extend(cold_enquiry_cards(session, settings, matching_companies))
    cards = cards[:100]
    payload = json.dumps({"timestamp": int(time.time()), "run_id": run_id, "cards": cards}, ensure_ascii=True)
    signature = hmac.new(secret.encode(), payload.encode(), hashlib.sha256).hexdigest()
    try:
        response = httpx.post(
            endpoint, json={"payload": payload, "signature": signature}, follow_redirects=True, timeout=100.0,
        )
        response.raise_for_status()
        result = response.json()
    except (httpx.HTTPError, ValueError):
        raise RuntimeError("Hosted delivery could not be confirmed. Check Apps Script Executions.") from None
    if not isinstance(result, dict) or result.get("ok") is not True or type(result.get("sent")) is not int:
        raise RuntimeError("Apps Script rejected or did not finish the delivery. Check Apps Script Executions.")
    return result["sent"]

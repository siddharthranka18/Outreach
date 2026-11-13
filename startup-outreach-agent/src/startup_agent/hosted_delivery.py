"""Publish job and cold-enquiry cards to the hosted review service."""

import hashlib
import hmac
import ipaddress
import json
import logging
import os
import re
import socket
import time
from urllib.parse import urljoin, urlsplit

import httpx
import yaml
from bs4 import BeautifulSoup
from sqlalchemy import select
from sqlalchemy.orm import Session

from startup_agent.config.settings import Settings
from startup_agent.database.models import CompanyModel, JobModel
from startup_agent.database.repositories import CompanyRepository, JobRepository
from startup_agent.digest import format_digest
from startup_agent.discovery.direct_ats import DirectAtsDiscoverySource, extract_ats_target
from startup_agent.discovery.gallery_leads import gallery_leads
from startup_agent.email_drafts import generate_email_draft
from startup_agent.matching.profile import CandidateProfile
from startup_agent.matching.startup_filter import StartupEligibilityFilter, StartupEligibilityStatus
from startup_agent.models.company import Company
from startup_agent.routing import HIRING_INBOX, OutreachRoute, build_outreach_routes
from startup_agent.utils.http_client import HttpClient
from startup_agent.utils.normalizers import normalize_name

logger = logging.getLogger(__name__)
EMAIL = re.compile(r"[a-z0-9._+%-]+@[a-z0-9.-]+\.[a-z]{2,}")
EARLY_ROLE = re.compile(r"\b(?:intern(?:ship)?|junior|fresher|entry.level|new.grad|graduate|trainee)\b", re.I)
TECH_ROLE = re.compile(r"\b(?:software|developer|backend|frontend|full.stack|AI|ML|data|devops|mobile|platform)\b", re.I)
PROJECT_ROLES = {
    "ai": r"\b(?:artificial intelligence|machine learning|generative ai|computer vision|llms?)\b",
    "mobile": r"\b(?:mobile app(?:lication)?s?|android|ios|flutter)\b",
    "backend": r"\b(?:back.end|apis?|developer tools|infrastructure|data platform)\b",
}
MAX_NEW_DRAFTS = 5


def employer_domain(url: str) -> str:
    try:
        parsed = urlsplit(url)
        if parsed.scheme == "https" and not parsed.username and parsed.port in (None, 443):
            return (parsed.hostname or "").removeprefix("www.")
    except ValueError:
        pass
    return ""


def employer_page(url: str, domain: str) -> tuple[str, BeautifulSoup] | None:
    """Follow a few same-employer redirects, checking public addresses before requests."""
    for _ in range(4):
        host = employer_domain(url)
        if not host or (host != domain and not host.endswith("." + domain)):
            return None
        try:
            addresses = socket.getaddrinfo(urlsplit(url).hostname, 443, type=socket.SOCK_STREAM)
            if not addresses or any(not ipaddress.ip_address(item[4][0]).is_global for item in addresses):
                return None
            response = httpx.get(url, timeout=7, follow_redirects=False)
            if response.is_redirect:
                url = urljoin(url, response.headers.get("location", ""))
                continue
            response.raise_for_status()
        except (httpx.HTTPError, OSError, ValueError):
            return None
        if "html" not in response.headers.get("content-type", ""):
            return None
        return str(response.url), BeautifulSoup(response.text, "html.parser")
    return None


def early_tech_role(label: str) -> bool:
    return bool(len(label) <= 180 and EARLY_ROLE.search(label) and TECH_ROLE.search(label))


def hiring_email(page: BeautifulSoup, domain: str, reviewed_email: str = "") -> str | None:
    text = page.get_text(" ", strip=True)
    addresses = {match.group().lower() for match in HIRING_INBOX.finditer(text)}
    if reviewed_email:
        addresses.update(match.group().lower() for match in re.finditer(
            rf"(?<![\w.+-]){re.escape(reviewed_email)}(?![\w.+-])", text, re.I,
        ))
    for link in page.select('a[href^="mailto:" i]'):
        address = link["href"][7:].split("?", 1)[0].strip().lower()
        context = link.parent.get_text(" ", strip=True)
        if (HIRING_INBOX.fullmatch(address) or address == reviewed_email or (
            len(context) < 350 and re.search(
                r"\b(?:send (?:us )?your (?:resume|cv|application)|recruiter|talent acquisition|"
                r"hiring enquiries|email.{0,30}to apply)\b", context, re.I,
            )
        )):
            addresses.add(address)
    return next((address for address in sorted(addresses, key=lambda item: (item != reviewed_email, item))
                 if EMAIL.fullmatch(address) and address.rsplit("@", 1)[1] == domain), None)


def board_jobs(urls: list[str], name: str, website: str, size: str, client: HttpClient) -> list | None:
    targets = {}
    for url in urls:
        target = extract_ats_target(url, name, website, size)
        if target and re.fullmatch(r"[\w-]+", target["board_token"], re.ASCII):
            targets[target["platform"], target["board_token"]] = target
    if len(targets) > 3:
        return None
    adapter = DirectAtsDiscoverySource(http_client=client)
    jobs = []
    try:
        for target in targets.values():
            jobs.extend(adapter.fetch_board_jobs(target))
    except (httpx.HTTPError, ValueError, TypeError, AttributeError):
        return None
    return jobs


def enquiry_candidates(session: Session, settings: Settings, profile: CandidateProfile) -> list[dict]:
    size_filter = StartupEligibilityFilter(max_employees=profile.preferences.small_startup_max_employees)
    size_path = settings.config_dir / "company_sizes.yaml"
    reviewed = (yaml.safe_load(size_path.read_text(encoding="utf-8")) or {}) if size_path.is_file() else {}
    contacts_path = settings.config_dir / "hiring_contacts.yaml"
    contacts = yaml.safe_load(contacts_path.read_text(encoding="utf-8")) if contacts_path.is_file() else {}
    client = HttpClient(timeout=7, max_retries=0, rate_limit_delay=0.25)
    leads = {}
    for company in session.scalars(select(CompanyModel).order_by(CompanyModel.id)):
        domain = employer_domain(company.website)
        if domain and company.careers_url:
            leads[domain] = {
                "company_name": company.company_name, "website": company.website,
                "employee_count": company.employee_count, "careers_url": company.careers_url,
                "source_url": company.source_url, "location": company.location,
            }
    for lead in gallery_leads(client):
        domain = employer_domain(lead["website"])
        if domain:
            leads[domain] = {**leads.get(domain, {}), **lead, "location": "India"}
    for domain, entry in reviewed.items():
        if entry.get("careers_url") or domain in leads:
            leads[domain] = {"website": f"https://{domain}", **leads.get(domain, {}), **entry}
    for entry in (contacts or {}).values():
        domain = employer_domain(entry["source_url"])
        if domain in leads and entry.get("accepts_enquiries") is True:
            leads[domain].update(hiring_email=entry["email"], careers_url=entry["source_url"])

    companies = CompanyRepository(session)
    jobs = JobRepository(session)
    candidates = []
    # Prioritize reviewed leads and the India directory within a bounded hosted run.
    ordered = sorted(leads.items(), key=lambda item: (
        item[0] not in reviewed, not str(item[1].get("source_url", "")).startswith("https://startups.gallery/"),
    ))
    eligible = [
        (domain, lead) for domain, lead in ordered
        if lead.get("company_name") and lead.get("careers_url")
        and size_filter.evaluate(lead.get("employee_count")).status == StartupEligibilityStatus.ELIGIBLE
    ]
    for domain, lead in eligible[:20]:
        name, website, size = (lead[key] for key in ("company_name", "website", "employee_count"))
        careers_url = lead["careers_url"]
        urls = [careers_url, *lead.get("ats_urls", [])]
        if lead.get("ats_url"):
            urls.append(lead["ats_url"])
        result = employer_page(careers_url, domain)
        if result:
            source, page = result
            urls.extend(urljoin(source, node.get("href") or node.get("src"))
                        for node in page.select("a[href], iframe[src]"))
        current_jobs = board_jobs(urls, name, website, size, client)
        if current_jobs is None:
            continue
        if current_jobs:
            company = companies.upsert_company(Company(
                company_name=name, website=website, employee_count=size,
                source_name="hosted_careers", source_url=lead["source_url"],
                careers_url=careers_url, location=lead.get("location"),
            ))
            for job in current_jobs:
                job.company_id = company.id
                jobs.upsert_job(job)
        if not result or any(early_tech_role(job.job_title) for job in current_jobs):
            continue
        if any(early_tech_role(node.get_text(" ", strip=True))
               for node in page.select("h2, h3, h4, a[href], button")):
            continue
        recipient = hiring_email(page, domain, lead.get("hiring_email", "").lower())
        description = page.select_one('meta[name="description"], meta[property="og:description"]')
        context = lead.get("enquiry_interest") or (description.get("content", "") if description else "")
        context = " ".join(context.split())[:350]
        role = next((role for role, pattern in PROJECT_ROLES.items()
                     if re.search(pattern, context, re.I)), "full_stack")
        form = next((
            urljoin(source, link["href"]) for link in page.select("a[href]")
            if re.search(r"\b(?:general application|open application|speculative application|"
                         r"internship enquiry|submit your resume)\b", link.get_text(" ", strip=True), re.I)
            and employer_domain(urljoin(source, link["href"])) == domain
        ), None)
        if recipient or lead.get("enquiry_form") is True or (form and TECH_ROLE.search(context)):
            candidates.append({
                "domain": domain, "name": name, "source": source, "recipient": recipient,
                "context": context, "role": role,
                "form": form or (source if lead.get("enquiry_form") is True else None),
            })
    return candidates


def cold_enquiry_cards(candidates: list[dict], profile: CandidateProfile,
                       companies_with_matches: set[str], history: list[dict]) -> list[dict]:
    saved = {entry["url"]: entry for entry in history}
    blocked_recipients = {
        (entry.get("draft") or {}).get("recipient") for entry in history
        if entry.get("delivery") in {"sent", "sending", "uncertain"}
    }
    drafts_remaining = MAX_NEW_DRAFTS if os.getenv("GEMINI_API_KEY", "").strip() else 0
    cards = []
    for lead in candidates:
        name, domain, recipient = (lead[key] for key in ("name", "domain", "recipient"))
        if normalize_name(name) in companies_with_matches or domain in companies_with_matches:
            continue
        mail_url = f"https://{domain}/#outreach-enquiry"
        form_url = f"{mail_url}-form"
        if any(saved.get(url, {}).get("status") in {"skipped", "applied"} for url in (mail_url, form_url)):
            continue
        text = f"Internship enquiry @ {name}"
        if not recipient:
            if lead["form"]:
                cards.append({"job_url": form_url, "text": f"{text}\nGeneral careers form\n{lead['form']}"})
            continue
        entry = saved.get(mail_url, {})
        if recipient in blocked_recipients or entry.get("delivery") not in {None, "", "pending"}:
            continue
        draft = entry.get("draft") or {}
        if draft.get("recipient") != recipient:
            if not drafts_remaining:
                continue
            role = lead["role"].replace("_", " ")
            route = OutreachRoute(
                company=name, action="Internship enquiry", title=f"{role.title()} engineering internship enquiry",
                category=role, contact=recipient, url=lead["source"],
            )
            try:
                generated = generate_email_draft(route, profile, enquiry_context=lead["context"])
            except (ValueError, RuntimeError) as exc:
                logger.warning("Gemini enquiry drafting stopped for this digest: %s", exc)
                drafts_remaining = 0
                continue
            drafts_remaining -= 1
            draft = {"recipient": recipient, "subject": generated.subject, "body": generated.body}
        cards.append({"job_url": mail_url, "text": text, "draft": {**draft, "source_url": lead["source"]}})
    return cards


def hosted_request(endpoint: str, secret: str, run_id: str, cards: list[dict]) -> dict:
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
    if not isinstance(result, dict) or result.get("ok") is not True:
        raise RuntimeError("Apps Script rejected or did not finish the request. Check Apps Script Executions.")
    return result


def publish_hosted_shortlist(session: Session, settings: Settings) -> int:
    endpoint = os.getenv("OUTREACH_WEB_APP_URL", "").strip()
    secret = os.getenv("OUTREACH_SYNC_SECRET", "").strip()
    run_id = os.getenv("GITHUB_RUN_ID") or f"local-{time.time_ns()}"
    if not re.fullmatch(r"https://script\.google\.com/macros/s/[\w-]+/exec", endpoint) or len(secret) < 32:
        raise ValueError("Set OUTREACH_WEB_APP_URL and an OUTREACH_SYNC_SECRET of at least 32 characters.")

    profile = CandidateProfile.load(settings.config_dir / "candidate_profile.yaml")
    history = hosted_request(endpoint, secret, "enquiry-history", [])["entries"]
    candidates = enquiry_candidates(session, settings, profile)
    routes = [route for route in build_outreach_routes(session, settings) if route.job_id is not None and route.url]
    job_urls = dict(session.execute(select(JobModel.id, JobModel.normalized_job_url)).all())
    cards = [
        {"job_url": job_urls[route.job_id], "text": format_digest([route]).split("\n\n", 1)[1]}
        for route in routes
    ]
    matching_companies = set()
    for company in session.scalars(select(CompanyModel).join(JobModel).where(
        JobModel.id.in_([route.job_id for route in routes]),
    )):
        matching_companies.update((company.normalized_name, employer_domain(company.website)))
    enquiries = cold_enquiry_cards(candidates, profile, matching_companies, history)
    # Leave room in the 30-card Telegram delivery limit for enquiries.
    cards = [*cards[:20], *enquiries, *cards[20:]][:100]
    result = hosted_request(endpoint, secret, run_id, cards)
    if type(result.get("sent")) is not int:
        raise RuntimeError("Apps Script did not confirm the Telegram delivery count.")
    return result["sent"]

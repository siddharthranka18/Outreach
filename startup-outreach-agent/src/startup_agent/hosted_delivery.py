"""Publish job and cold-enquiry cards to the hosted review service."""

import hashlib
import hmac
import json
import logging
import os
import re
import time
from datetime import datetime, timedelta, timezone
from urllib.parse import urljoin, urlsplit

import httpx
import yaml
from bs4 import BeautifulSoup
from sqlalchemy import select
from sqlalchemy.orm import Session

from startup_agent.config.settings import Settings
from startup_agent.database.models import CompanyModel, JobModel
from startup_agent.database.repositories import CompanyRepository, JobRepository
from startup_agent.database.repositories import _is_indirect_company_url
from startup_agent.digest import format_digest
from startup_agent.discovery.direct_ats import DirectAtsDiscoverySource, extract_ats_target
from startup_agent.discovery.gallery_leads import gallery_leads
from startup_agent.discovery.funding_leads import funded_employers
from startup_agent.discovery.board_tracking import remember_boards
from startup_agent.funnel import source_funnel, format_funnel, format_heartbeat
from startup_agent.email_drafts import generate_email_draft
from startup_agent.matching.profile import CandidateProfile
from startup_agent.matching.startup_filter import StartupEligibilityFilter, StartupEligibilityStatus
from startup_agent.models.company import Company
from startup_agent.routing import HIRING_INBOX, OutreachRoute, build_outreach_routes
from startup_agent.utils.http_client import HttpClient
from startup_agent.utils.normalizers import normalize_name
from startup_agent.routing import junior_pitch_context

logger = logging.getLogger(__name__)
EMAIL = re.compile(r"[a-z0-9._+%-]+@[a-z0-9.-]+\.[a-z]{2,}")
EARLY_ROLE = re.compile(r"\b(?:intern(?:ship)?|junior|fresher|entry.level|new.grad|graduate|trainee)\b", re.I)
TECH_ROLE = re.compile(r"\b(?:software|developer|backend|frontend|full.stack|AI|ML|data|devops|mobile|platform)\b", re.I)
PROJECT_ROLES = {
    "ai": r"\b(?:artificial intelligence|machine learning|generative ai|computer vision|llms?)\b",
    "mobile": r"\b(?:mobile app(?:lication)?s?|android|ios|flutter)\b",
    "backend": r"\b(?:back.end|apis?|developer tools|infrastructure|data platform)\b",
}
MAX_NEW_DRAFTS = 15
SMALL_INBOXES = {"hello", "contact", "founders", "team", "apply", "internships", "engineering"}


def employer_domain(url: str) -> str:
    try:
        parsed = urlsplit(url)
        if parsed.scheme == "https" and not parsed.username and parsed.port in (None, 443):
            return (parsed.hostname or "").removeprefix("www.")
    except ValueError:
        pass
    return ""


def employer_page(url: str, domain: str, client=None) -> tuple[str, BeautifulSoup] | None:
    """Follow a few same-employer redirects, checking public addresses before requests."""
    client = client or HttpClient(timeout=7, max_retries=1, public_only=True)
    try:
        response = client.get(url, allowed_domain=domain)
        if "html" in response.headers.get("content-type", ""):
            return str(response.url), BeautifulSoup(response.text, "html.parser")
    except (httpx.HTTPError, OSError, ValueError):
        return None
    return None


def early_tech_role(label: str) -> bool:
    return bool(len(label) <= 180 and EARLY_ROLE.search(label) and TECH_ROLE.search(label))


def hiring_email(page: BeautifulSoup, domain: str, reviewed_email: str = "", *, allow_generic=False, employee_count=None, email_hints=()) -> str | None:
    text = page.get_text(" ", strip=True)
    addresses = {match.group().lower() for match in HIRING_INBOX.finditer(text)}
    hiring_context = re.compile(
        r"\b(?:send (?:us )?your (?:resume|cv|application)|recruiter|talent acquisition|"
        r"hiring enquiries|email.{0,30}to apply)\b", re.I)
    # Plain named addresses require a short, local recruiting context too.
    for node in page.find_all(["p", "li", "div"]):
        local = node.get_text(" ", strip=True)
        if len(local) < 350 and hiring_context.search(local):
            addresses.update(EMAIL.findall(local.lower()))
    size = StartupEligibilityFilter(50, False).evaluate(employee_count)
    generic_allowed = (allow_generic and size.status == StartupEligibilityStatus.ELIGIBLE
                       and size.estimated_min_employees is not None and size.estimated_min_employees >= 2)
    if generic_allowed:
        addresses.update(a for a in EMAIL.findall(text.lower()) if a.split("@")[0] in SMALL_INBOXES)
    if reviewed_email:
        addresses.update(match.group().lower() for match in re.finditer(
            rf"(?<![\w.+-]){re.escape(reviewed_email)}(?![\w.+-])", text, re.I,
        ))
    for link in page.select('a[href^="mailto:" i]'):
        address = link["href"][7:].split("?", 1)[0].strip().lower()
        context = link.parent.get_text(" ", strip=True)
        if (HIRING_INBOX.fullmatch(address) or address == reviewed_email or
            (generic_allowed and address.split("@")[0] in SMALL_INBOXES) or (
            len(context) < 350 and re.search(
                r"\b(?:send (?:us )?your (?:resume|cv|application)|recruiter|talent acquisition|"
                r"hiring enquiries|email.{0,30}to apply)\b", context, re.I,
            )
        )):
            addresses.add(address)
    return next((address for address in sorted(addresses, key=lambda item: (item != reviewed_email, item not in email_hints, item))
                 if EMAIL.fullmatch(address) and address.rsplit("@", 1)[1] == domain
                 and (address.split("@")[0] not in SMALL_INBOXES or generic_allowed)), None)


def contact_pages(careers_url, domain):
    """Five bounded employer pages, including the homepage/footer."""
    root = "https://" + domain
    host = employer_domain(careers_url)
    primary = careers_url if host and (host == domain or host.endswith("." + domain)) else root + "/careers"
    return list(dict.fromkeys([primary, root, root+"/contact", root+"/about", root+"/team"]))


def verified_contact(pages, domain, reviewed_email="", *, allow_generic=False, employee_count=None, hn_leads=(), trust_hn=False):
    """HN leads are accepted only if current employer hiring context independently verifies them."""
    for source, page in pages:
        hints = {h["email"] for h in hn_leads if h.get("domain") == domain and h.get("email", "").endswith("@" + domain)}
        address = hiring_email(page, domain, reviewed_email, allow_generic=allow_generic,
                               employee_count=employee_count, email_hints=hints)
        if address:
            return address, source
    if trust_hn and StartupEligibilityFilter(200, False).evaluate(employee_count).status == StartupEligibilityStatus.ELIGIBLE:
        from startup_agent.discovery.hn_hiring import current_hn_contact
        for hint in hn_leads:
            if current_hn_contact(hint, domain):
                return hint["email"], hint["evidence_url"]
    return None


def board_jobs(urls: list[str], name: str, website: str, size: str, client: HttpClient, platforms=None) -> list | None:
    targets = {}
    for url in urls:
        target = extract_ats_target(url, name, website, size)
        if target and re.fullmatch(r"[\w-]+", target["board_token"], re.ASCII):
            targets[target["platform"], target["board_token"]] = target
    if len(targets) > 3:
        return None
    adapter = DirectAtsDiscoverySource(http_client=client, platforms=platforms)
    jobs = []
    try:
        for target in targets.values():
            jobs.extend(adapter.fetch_board_jobs(target))
    except (httpx.HTTPError, ValueError, TypeError, AttributeError):
        return None
    return jobs


def enquiry_candidates(session: Session, settings: Settings, profile: CandidateProfile, history=None) -> list[dict]:
    if any(s.name == "enquiry_research" and not s.enabled for s in settings.sources):
        return []
    size_filter = StartupEligibilityFilter(max_employees=profile.preferences.small_startup_max_employees)
    size_path = settings.config_dir / "company_sizes.yaml"
    reviewed = (yaml.safe_load(size_path.read_text(encoding="utf-8")) or {}) if size_path.is_file() else {}
    contacts_path = settings.config_dir / "hiring_contacts.yaml"
    contacts = yaml.safe_load(contacts_path.read_text(encoding="utf-8")) if contacts_path.is_file() else {}
    client = HttpClient(timeout=7, max_retries=1, rate_limit_delay=0.5, public_only=True)
    options = next((s.options for s in settings.sources if s.name == "enquiry_research"), {})
    deadline=time.monotonic()+max(30,min(900,int(options.get('max_seconds',900))))
    client.deadline=deadline
    allow_generic = options.get("allow_generic_small_inboxes") is True
    platforms = {"greenhouse", "ashby", "lever", "recruitee"} | {
        s.name.removeprefix("ats_") for s in settings.sources if s.type == "ats_platform" and s.enabled}
    if not any(s.type == "ats_platform" for s in settings.sources):
        platforms |= {"workable", "breezy", "teamtailor", "bamboohr"}
    hn_path = settings.data_dir / "processed/hn_contact_leads.json"
    try:
        hn_leads = json.loads(hn_path.read_text(encoding="utf-8")) if hn_path.is_file() else []
        hn_leads = [h for h in hn_leads if isinstance(h, dict) and isinstance(h.get("email"), str)] if isinstance(hn_leads, list) else []
    except (OSError, ValueError):
        logger.warning("Optional HN contact research file unavailable; continuing without hints.")
        hn_leads = []
    leads = {}
    stored_companies = {}
    funding_evidence=dict(reviewed)
    for company in session.scalars(select(CompanyModel)):
        domain=employer_domain(company.website)
        if domain and company.employee_count:
            funding_evidence.setdefault(domain,{'company_name':company.company_name,'employee_count':company.employee_count,
                'source_url':company.source_url,'careers_url':company.careers_url or company.website+'/careers'})
    if os.getenv("OUTREACH_FUNDING_LEADS", "true").lower() == "true":
        for lead in funded_employers(funding_evidence):
            leads[employer_domain(lead["website"])] = lead
    for company in session.scalars(select(CompanyModel).order_by(CompanyModel.id)):
        domain = employer_domain(company.website)
        if domain and not _is_indirect_company_url(company.website):
            stored_companies[domain] = company
            leads[domain] = {
                "company_name": company.company_name, "website": company.website,
                "employee_count": company.employee_count, "careers_url": company.careers_url or company.website + "/careers",
                "source_url": company.source_url, "location": company.location,
            }
    # Gallery uses a separate rotating profile cursor; no repeated first-ten sample.
    gallery_cursor_path=settings.data_dir/'processed/gallery_cursor.txt'
    try:gallery_offset=int(gallery_cursor_path.read_text())
    except (OSError,ValueError):gallery_offset=0
    gallery_count=max(1,min(100,int(options.get('gallery_profiles',60))))
    try:
        gallery=gallery_leads(client, max_profiles=gallery_count,offset=gallery_offset)
    except (httpx.HTTPError,OSError,ValueError):
        logger.warning('Gallery research unavailable; continuing with stored employers.')
        gallery=[]
    for lead in gallery:
        domain = employer_domain(lead["website"])
        if domain:
            leads[domain] = {**leads.get(domain, {}), **lead, "location": "India"}
            companies_repo = CompanyRepository(session)
            model = companies_repo.upsert_company(Company(company_name=lead["company_name"],website=lead["website"],
                source_name="startups_gallery",source_url=lead["source_url"],employee_count=lead["employee_count"],
                careers_url=lead.get("careers_url"),location="India"))
            remember_boards(model, lead.get("ats_urls", []) + [lead.get("careers_url") or ""])
    gallery_cursor_path.parent.mkdir(parents=True,exist_ok=True)
    gallery_cursor_path.write_text(str(gallery_offset+gallery_count))
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
        and reviewed.get(domain, {}).get("public_board_only") is not True
        and size_filter.evaluate(lead.get("employee_count")).status == StartupEligibilityStatus.ELIGIBLE
    ]
    handled={entry.get('url') for entry in history or [] if entry.get('status') in {'skipped','applied'}
             or entry.get('delivery') in {'sent','sending','uncertain'}}
    eligible=[(domain,lead) for domain,lead in eligible if not any(
        f'https://{domain}/#outreach-enquiry'+suffix in handled for suffix in ('','-form'))]
    pitch_contexts = {}
    for job in session.scalars(select(JobModel).where(JobModel.status == "open")):
        context = junior_pitch_context(job, job.company, profile)
        if context:
            pitch_contexts[employer_domain(job.company.website)] = context
    # Rotate the bounded research window so newly discovered portfolios do not
    # remain behind the same reviewed employers on every daily run.
    cursor_path = settings.data_dir / "processed/enquiry_research_cursor.json"
    try:
        cursor = int(json.loads(cursor_path.read_text(encoding="utf-8")).get("offset", 0))
    except (OSError, ValueError, AttributeError):
        cursor = 0
    cached_candidates, research_queue = [], []
    now = datetime.now(timezone.utc)
    for domain, lead in eligible:
        company = stored_companies.get(domain)
        checked = company.last_researched_at if company else None
        status = company.research_status if company else None
        ttl = timedelta(days=21 if status in {"found_inbox", "no_inbox"} else 3)
        if checked and now - checked.replace(tzinfo=timezone.utc) < ttl:
            if status == "found_inbox" and company.research_contact:
                cached_candidates.append(json.loads(company.research_contact))
        else:
            research_queue.append((domain, lead))
    eligible = research_queue
    offset = cursor % len(eligible) if eligible else 0
    window = (eligible[offset:] + eligible[:offset])[:max(1,min(100,int(options.get("max_employers",80))))]
    cursor_path.parent.mkdir(parents=True, exist_ok=True)
    processed=0
    for domain, lead in window:
        if time.monotonic()>=deadline:
            logger.info('Enquiry research time budget reached after %d employers.',processed)
            break
        processed+=1
        name, website, size = (lead[key] for key in ("company_name", "website", "employee_count"))
        careers_url = lead["careers_url"]
        urls = [careers_url, *lead.get("ats_urls", [])]
        if lead.get("ats_url"):
            urls.append(lead["ats_url"])
        pages = []
        for contact_url in contact_pages(careers_url, domain):
            fetched = employer_page(contact_url, domain, client)
            if fetched:
                pages.append(fetched)
        result = pages[0] if pages else None
        for page_url, contact_page in pages:
            urls.extend(urljoin(page_url, node.get("href") or node.get("src"))
                        for node in contact_page.select("a[href], iframe[src]"))
        if result:
            source, page = result
        model = companies.upsert_company(Company(company_name=name,website=website,employee_count=size,
            source_name=lead.get("source_name") or "hosted_careers",source_url=lead["source_url"],careers_url=careers_url))
        remember_boards(model,urls)
        current_jobs = board_jobs(urls, name, website, size, client, platforms)
        if time.monotonic() >= deadline:
            break
        model.last_researched_at = datetime.now(timezone.utc)
        model.research_contact = None
        model.research_status = "no_inbox" if pages else "unreachable"
        if current_jobs is None:
            model.research_status = "unreachable"
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
        pitch_context = pitch_contexts.get(domain)
        for current in current_jobs:
            context = junior_pitch_context(current,model,profile)
            if context: pitch_context = context
        if any(early_tech_role(job.job_title) and not junior_pitch_context(job,model,profile) for job in current_jobs):
            model.research_status = "has_open_role"
            continue
        if not pitch_context and any(early_tech_role(node.get_text(" ", strip=True)) for _, contact_page in pages
               for node in contact_page.select("h2, h3, h4, a[href], button")):
            model.research_status = "has_open_role"
            continue
        contact = verified_contact(pages, domain, lead.get("hiring_email", "").lower(),
            allow_generic=allow_generic, employee_count=size,
            hn_leads=[h for h in hn_leads if h.get("domain") == domain], trust_hn=options.get("trust_hn_hiring_contacts") is True)
        if not contact:
            continue
        recipient, contact_source = contact
        description = page.select_one('meta[name="description"], meta[property="og:description"]') if result else None
        context = lead.get("enquiry_interest") or (description.get("content", "") if description else "")
        context = " ".join(context.split())[:350]
        if pitch_context:
            context = (context + " " + pitch_context)[:850]
        role = next((role for role, pattern in PROJECT_ROLES.items()
                     if re.search(pattern, context, re.I)), "full_stack")
        candidate = {
            "domain": domain, "name": name, "source": contact_source, "recipient": recipient,
            "context": context, "role": role,
        }
        candidates.append(candidate)
        model.research_status = "found_inbox"
        model.research_contact = json.dumps(candidate)
    cursor_path.write_text(json.dumps({"offset": offset + processed}), encoding="utf-8")
    return candidates + cached_candidates


def cold_enquiry_cards(candidates: list[dict], profile: CandidateProfile,
                       companies_with_matches: set[str], history: list[dict], *, max_new_drafts=MAX_NEW_DRAFTS) -> list[dict]:
    saved = {entry["url"]: entry for entry in history}
    blocked_recipients = {
        (entry.get("draft") or {}).get("recipient") for entry in history
        if entry.get("delivery") in {"sent", "sending", "uncertain"}
    }
    drafts_remaining = max(0,min(15,int(max_new_drafts))) if os.getenv("GEMINI_API_KEY", "").strip() else 0
    cards = []
    for lead in candidates:
        name, domain, recipient = (lead[key] for key in ("name", "domain", "recipient"))
        if not recipient or normalize_name(name) in companies_with_matches or domain in companies_with_matches:
            continue
        mail_url = f"https://{domain}/#outreach-enquiry"
        form_url = f"{mail_url}-form"
        if any(saved.get(url, {}).get("status") in {"skipped", "applied"} for url in (mail_url, form_url)):
            continue
        text = f"Internship enquiry @ {name}"
        entry = saved.get(mail_url, {})
        if recipient in blocked_recipients or entry.get("delivery") not in {None, "", "pending"}:
            continue
        draft = entry.get("draft") or {}
        if draft.get("recipient") != recipient:
            if not drafts_remaining:
                continue
            route = OutreachRoute(
                company=name, action="Internship enquiry", title="Software engineering internship enquiry",
                category="software", contact=recipient, url=lead["source"],
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


def hosted_request(endpoint: str, secret: str, run_id: str, cards: list[dict], *, summary=None) -> dict:
    batch = {"timestamp": int(time.time()), "run_id": run_id, "cards": cards}
    if summary is not None:
        batch["summary"] = summary[:3500]
    payload = json.dumps(batch, ensure_ascii=True)
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


def publish_hosted_shortlist(session: Session, settings: Settings, *, enquiries_only: bool = False, discovery_failed=False) -> int:
    endpoint = os.getenv("OUTREACH_WEB_APP_URL", "").strip()
    secret = os.getenv("OUTREACH_SYNC_SECRET", "").strip()
    run_id = os.getenv("OUTREACH_DELIVERY_SLOT") or os.getenv("GITHUB_RUN_ID") or f"local-{time.time_ns()}"
    if not os.getenv('OUTREACH_DELIVERY_SLOT') and os.getenv('INVOCATION_ID') and not os.getenv('GITHUB_RUN_ID'):
        from startup_agent.delivery_slots import oracle_delivery_slot
        run_id=oracle_delivery_slot()
    if not re.fullmatch(r"https://script\.google\.com/macros/s/[\w-]+/exec", endpoint) or len(secret) < 32:
        raise ValueError("Set OUTREACH_WEB_APP_URL and an OUTREACH_SYNC_SECRET of at least 32 characters.")
    if discovery_failed:
        summary = "Discovery failed: all sources failed.\n" + format_heartbeat(source_funnel(session, settings))
        hosted_request(endpoint, secret, run_id, [], summary=summary)
        return 0

    profile = CandidateProfile.load(settings.config_dir / "candidate_profile.yaml")
    history = hosted_request(endpoint, secret, "enquiry-history", [])["entries"]
    candidates = enquiry_candidates(session, settings, profile, history=history)
    routes = [route for route in build_outreach_routes(session, settings, internship_review=True)
              if route.job_id is not None and route.url]
    job_urls = {}
    aliases = {}
    for job_id, url, key in session.execute(select(
        JobModel.id, JobModel.normalized_job_url, JobModel.canonical_job_key,
    )):
        job_urls[job_id] = (url, key)
        if key:
            aliases.setdefault(key, []).append(url)
    route_cards = [
        {"job_url": url, "text": format_digest([route]).split("\n\n", 1)[1],
         **({"canonical_job_key": key,
             "alias_urls": [alias for alias in dict.fromkeys(aliases[key]) if alias != url][:5]} if key else {})}
        for route in routes
        for url, key in (job_urls[route.job_id],)
    ]
    cards = [card for route, card in zip(routes, route_cards) if not route.review_note]
    review_cards = [card for route, card in zip(routes, route_cards) if route.review_note]
    matching_companies = set()
    for company in session.scalars(select(CompanyModel).join(JobModel).where(
        JobModel.id.in_([route.job_id for route in routes]),
    )):
        matching_companies.update((company.normalized_name, employer_domain(company.website)))
    enquiry_options=next((s.options for s in settings.sources if s.name=='enquiry_research'),{})
    enquiries = cold_enquiry_cards(candidates, profile, matching_companies, history,
                                 max_new_drafts=enquiry_options.get('max_new_drafts',15))
    # Leave room in the 30-card Telegram delivery limit for enquiries.
    cards = (enquiries if enquiries_only else [*cards[:15], *enquiries[:15], *review_cards, *cards[15:]])[:100]
    logger.info("Prepared %d email enquiry card(s) for hosted review.", len(enquiries))
    logger.info("Prepared %d ranked application routes and %d total hosted cards.", len(routes), len(cards))
    logger.info("Prepared %d internship review cards with wider company-size criteria.", len(review_cards))
    funnel = source_funnel(session, settings, routes=routes)
    summary = format_funnel(funnel)
    logger.info("%s", summary)
    result = hosted_request(endpoint, secret, run_id, cards, summary=format_heartbeat(funnel))
    if type(result.get("sent")) is not int:
        raise RuntimeError("Apps Script did not confirm the Telegram delivery count.")
    logger.info("Hosted review accepted %d cards and delivered %d after saved-action checks.", len(cards), result["sent"])
    return result["sent"]

"""Build reviewable outreach routes from stored matches and their source data."""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import re
from urllib.parse import urlsplit

from sqlalchemy import select
from sqlalchemy.orm import Session
import yaml

from startup_agent.config.settings import Settings
from startup_agent.database.models import CompanyModel, JobModel
from startup_agent.matching.eligibility import EligibilityStatus
from startup_agent.matching.ranker import OpportunityRanker
from startup_agent.matching.startup_filter import StartupEligibilityStatus, StartupEligibilityFilter
from startup_agent.matching.scorer import OpportunityScorer
from startup_agent.matching.classifier import OpportunityType
from startup_agent.matching.profile import CandidateProfile
from startup_agent.utils.normalizers import normalize_job_url, normalize_website


HIRING_INBOX = re.compile(
    r"(?<![\w.+-])(?:careers?|jobs?|hiring|recruitment|recruiting|talent)"
    r"@[a-z0-9-]+(?:\.[a-z0-9-]+)+\b",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class OutreachRoute:
    company: str
    action: str
    title: str = ""
    url: str | None = None
    contact: str | None = None
    contact_source: str | None = None
    location: str | None = None
    match_score: float | None = None
    job_id: int | None = None
    relevant_projects: tuple[str, ...] = ()
    matching_skills: tuple[str, ...] = ()
    category: str = ""
    asks_for_internship: bool = False
    source_label: str = ""
    review_note: str = ""


def _public_link(value: str | None) -> str | None:
    if value:
        parsed = urlsplit(value)
        if parsed.scheme in {"https", "http"} and parsed.hostname and not parsed.username:
            return value
    return None


def junior_pitch_context(job, company, profile):
    """Separate internship enquiry intent; never promote a full-time role to a job card."""
    from startup_agent.discovery.portfolio import india_location
    if getattr(job, "status", "open") != "open": return None
    if StartupEligibilityFilter(50,False).evaluate(company.employee_count).status != StartupEligibilityStatus.ELIGIBLE:
        return None
    if not re.search(r"\b(?:junior|jr\.?|entry[- ]level|fresher)\b",job.job_title,re.I): return None
    location=job.location or ""
    if not india_location(location) and not re.search(r"\b(?:bengaluru|bangalore|delhi|mumbai|pune|hyderabad|chennai|gurugram|noida)\b", location,re.I):
        return None
    full=f"{job.job_title} {job.description or ''} {job.experience_level or ''}".replace('\u2013','-')
    # Explicit 0-1, zero experience or no experience; do not invent eligibility.
    if not re.search(r"\b0\s*(?:-|to)\s*1\s*(?:years?|yrs?)\b|\b(?:0|zero|no)\s+(?:years?\s+of\s+)?experience\b",full,re.I): return None
    if any(int(n)>1 for n in re.findall(r"\b(\d+)\s*\+?\s*(?:years?|yrs?)\b", full,re.I)): return None
    match=OpportunityScorer(profile).score(job_id=getattr(job,'id',None),job_title=job.job_title,
        company_name=company.company_name,job_url=job.job_url,description=job.description,location=job.location,
        employment_type=job.employment_type,experience_level=job.experience_level,employee_count=company.employee_count)
    if match.opportunity_type != OpportunityType.GRADUATE_ENTRY_LEVEL or match.eligibility_status != EligibilityStatus.POTENTIALLY_ELIGIBLE:
        return None
    return (f"Published junior role: {job.job_title} ({job.job_url}). This is a full-time role, not a confirmed internship. "
            "Ask whether the team would consider a current June 2028 B.Tech student for an internship or part-time engineering contribution. "
            "Do not claim to have graduated or to meet full-time availability.")


def build_outreach_routes(session: Session, settings: Settings, *, internship_review: bool = False) -> list[OutreachRoute]:
    from startup_agent.discovery.portfolio import india_location

    profile_path = settings.config_dir / "candidate_profile.yaml"
    profile = CandidateProfile.load(profile_path if profile_path.is_file() else None)
    normal_size = StartupEligibilityFilter(profile.preferences.small_startup_max_employees,
                                          profile.preferences.allow_unknown_company_size)
    review_size = StartupEligibilityFilter(max(500, normal_size.max_employees), allow_unknown=True)
    ranker = OpportunityRanker(session=session, settings=settings, profile=profile,
                               startup_filter=review_size if internship_review else normal_size)
    contacts_path = settings.config_dir / "hiring_contacts.yaml"
    reviewed_contacts = (
        yaml.safe_load(contacts_path.read_text(encoding="utf-8")) or {}
        if contacts_path.is_file() else {}
    )
    jobs = {job.id: job for job in session.scalars(select(JobModel))}
    routes = []
    review_routes = []
    cutoff = datetime.now(timezone.utc) - timedelta(days=14)
    seen_urls = {
        job.normalized_job_url for job in jobs.values() if job.status in {"skipped", "applied"}
    }
    handled_keys = {job.canonical_job_key for job in jobs.values()
                    if job.canonical_job_key and job.status in {"skipped", "applied"}}
    for match in ranker.rank_opportunities(limit=len(jobs)):
        job = jobs.get(match.job_id)
        if not job or job.status != "open":
            continue
        if job.canonical_job_key in handled_keys:
            continue
        review_note = ""
        if normal_size.evaluate(job.company.employee_count).status != StartupEligibilityStatus.ELIGIBLE:
            if not internship_review or match.opportunity_type not in {OpportunityType.INTERNSHIP, OpportunityType.COOP_STUDENT}:
                continue
            listed = job.posted_at or job.first_seen_at
            if not listed or listed.replace(tzinfo=timezone.utc) < cutoff or not india_location(job.location):
                continue
            if not _public_link(job.job_url):
                continue
            size = review_size.evaluate(job.company.employee_count)
            review_note = (f"Company size: {job.company.employee_count}" if size.estimated_max_employees is not None
                           else "Company size unlisted")
        needs_location_review = (
            job.source_name == "venomics_careers"
            and match.eligibility_status == EligibilityStatus.POTENTIALLY_ELIGIBLE
            and not job.location
        )
        if match.eligibility_status != EligibilityStatus.ELIGIBLE and not needs_location_review:
            continue
        if re.search(r"\b(?:this role is for one of our clients|on behalf of (?:one of )?our clients?)\b",
                     job.description or "", re.IGNORECASE):
            continue
        url = _public_link(job.job_url) or _public_link(match.careers_url)
        if not url:
            continue
        key = normalize_job_url(url)
        if key in seen_urls:
            continue
        if not review_note:
            seen_urls.add(key)

        # Accept only an explicitly published, employer-domain hiring inbox.
        domain = normalize_website(job.company.website).split("/", 1)[0]
        contact = next(
            (
                email.lower() for email in HIRING_INBOX.findall(job.description or "")
                if email.lower().rsplit("@", 1)[1] == domain
            ),
            None,
        )
        contact_source = job.job_url if contact else None
        reviewed = reviewed_contacts.get(normalize_job_url(job.job_url))
        if not contact and reviewed:
            email = reviewed["email"].strip().lower()
            source = _public_link(reviewed["source_url"])
            if source and email.rsplit("@", 1)[-1] == domain and normalize_website(source).split("/", 1)[0] == domain:
                contact, contact_source = email, source
        destination = review_routes if review_note else routes
        destination.append(OutreachRoute(
            company=match.company_name, title=match.job_title, url=url, contact=contact,
            contact_source=contact_source,
            action=("Review internship" if review_note else "Confirm location" if needs_location_review else
                    "Review email candidate" if contact else "Apply link"),
            location=match.location, match_score=match.match_score,
            job_id=job.id,
            relevant_projects=tuple(match.relevant_projects),
            matching_skills=tuple(match.matching_skills),
            category=match.category,
            review_note=review_note,
            source_label={"remotive": "Remotive", "himalayas": "Himalayas", "remoteok": "Remote OK",
                          "jobicy": "Jobicy", "freehire": "Freehire", "working_nomads": "Working Nomads", "hn_hiring": "Hacker News Who is hiring",
                          "vc_peakxv": "Peak XV portfolio", "vc_lightspeed": "Lightspeed portfolio",
                          "vc_bessemer": "Bessemer portfolio", "vc_nexus": "Nexus portfolio",
                          "vc_bain":"Bain Capital Ventures", "vc_courtside":"Courtside Ventures",
                          "cutshort":"Cutshort", "weekday":"Weekday", "simplify_summer2027":"SimplifyJobs / Pitt CSC",
                          "we_work_remotely":"We Work Remotely"}.get(job.source_name, ""),
            asks_for_internship=bool(re.search(
                r"\b(?:prior|previous|completed)\b[^.!?\n]{0,50}\binternship\b"
                r"|\binternship experience\b",
                job.description or "", re.IGNORECASE,
            )),
        ))

    for company in session.scalars(select(CompanyModel).order_by(CompanyModel.company_name)):
        if any(job.status in {"open", "skipped", "applied"} for job in company.jobs):
            continue
        if normal_size.evaluate(company.employee_count).status != StartupEligibilityStatus.ELIGIBLE:
            continue
        url = _public_link(company.careers_url) or _public_link(company.website)
        routes.append(OutreachRoute(company=company.company_name, action="Watchlist", url=url))

    seen_review_keys = {jobs[route.job_id].canonical_job_key for route in routes if route.job_id}
    added = 0
    for route in review_routes:
        url = normalize_job_url(route.url)
        key = jobs[route.job_id].canonical_job_key
        if url in seen_urls or (key and key in seen_review_keys):
            continue
        routes.append(route)
        seen_urls.add(url)
        seen_review_keys.add(key)
        added += 1
        if added == 6:
            break
    return routes

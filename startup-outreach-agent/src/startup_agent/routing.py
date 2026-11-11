"""Build reviewable outreach routes from stored matches and their source data."""

from dataclasses import dataclass
import re
from urllib.parse import urlsplit

from sqlalchemy import select
from sqlalchemy.orm import Session
import yaml

from startup_agent.config.settings import Settings
from startup_agent.database.models import CompanyModel, JobModel
from startup_agent.matching.eligibility import EligibilityStatus
from startup_agent.matching.ranker import OpportunityRanker
from startup_agent.matching.startup_filter import StartupEligibilityStatus
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


def _public_link(value: str | None) -> str | None:
    if value:
        parsed = urlsplit(value)
        if parsed.scheme in {"https", "http"} and parsed.hostname and not parsed.username:
            return value
    return None


def build_outreach_routes(session: Session, settings: Settings) -> list[OutreachRoute]:
    ranker = OpportunityRanker(session=session, settings=settings)
    contacts_path = settings.config_dir / "hiring_contacts.yaml"
    reviewed_contacts = (
        yaml.safe_load(contacts_path.read_text(encoding="utf-8")) or {}
        if contacts_path.is_file() else {}
    )
    jobs = {job.id: job for job in session.scalars(select(JobModel))}
    routes = []
    seen_urls = {
        job.normalized_job_url for job in jobs.values() if job.status in {"skipped", "applied"}
    }
    for match in ranker.rank_opportunities(limit=len(jobs)):
        job = jobs.get(match.job_id)
        if not job or job.status != "open" or match.eligibility_status != EligibilityStatus.ELIGIBLE:
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
        routes.append(OutreachRoute(
            company=match.company_name, title=match.job_title, url=url, contact=contact,
            contact_source=contact_source,
            action="Review email candidate" if contact else "Apply link",
            location=match.location, match_score=match.match_score,
            job_id=job.id,
            relevant_projects=tuple(match.relevant_projects),
            matching_skills=tuple(match.matching_skills),
            category=match.category,
            asks_for_internship=bool(re.search(
                r"\b(?:prior|previous|completed)\b[^.!?\n]{0,50}\binternship\b"
                r"|\binternship experience\b",
                job.description or "", re.IGNORECASE,
            )),
        ))

    for company in session.scalars(select(CompanyModel).order_by(CompanyModel.company_name)):
        if any(job.status in {"open", "skipped", "applied"} for job in company.jobs):
            continue
        if ranker.startup_filter.evaluate(company.employee_count).status != StartupEligibilityStatus.ELIGIBLE:
            continue
        url = _public_link(company.careers_url) or _public_link(company.website)
        routes.append(OutreachRoute(company=company.company_name, action="Watchlist", url=url))

    return routes

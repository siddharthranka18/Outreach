"""Build reviewable outreach routes from stored matches and their source data."""

from dataclasses import dataclass
import re
from urllib.parse import urlsplit

from sqlalchemy import select
from sqlalchemy.orm import Session

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
    location: str | None = None
    match_score: float | None = None


def _public_link(value: str | None) -> str | None:
    if value:
        parsed = urlsplit(value)
        if parsed.scheme in {"https", "http"} and parsed.hostname and not parsed.username:
            return value
    return None


def build_outreach_routes(session: Session, settings: Settings) -> list[OutreachRoute]:
    ranker = OpportunityRanker(session=session, settings=settings)
    jobs = {job.id: job for job in session.scalars(select(JobModel))}
    routes = []
    seen_urls = set()
    for match in ranker.rank_opportunities(limit=len(jobs)):
        job = jobs.get(match.job_id)
        if not job or job.status != "open" or match.eligibility_status != EligibilityStatus.ELIGIBLE:
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
        routes.append(OutreachRoute(
            company=match.company_name, title=match.job_title, url=url, contact=contact,
            action="Review email candidate" if contact else "Apply link",
            location=match.location, match_score=match.match_score,
        ))

    for company in session.scalars(select(CompanyModel).order_by(CompanyModel.company_name)):
        if any(job.status == "open" for job in company.jobs):
            continue
        if ranker.startup_filter.evaluate(company.employee_count).status != StartupEligibilityStatus.ELIGIBLE:
            continue
        url = _public_link(company.careers_url) or _public_link(company.website)
        routes.append(OutreachRoute(company=company.company_name, action="Watchlist", url=url))

    return routes

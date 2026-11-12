"""Check reviewed internship listings directly on employer sites."""

from dataclasses import dataclass
import logging

from bs4 import BeautifulSoup
import httpx

from startup_agent.discovery.base import BaseDiscoverySource, DiscoveryResult
from startup_agent.models.company import Company
from startup_agent.models.job import Job
from startup_agent.utils.http_client import HttpClient

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ReviewedInternship:
    company: str
    website: str
    careers: str
    title: str
    location: str
    selector: str
    summary: str
    fragment: str = ""
    hiring_email: str = ""


LIVINGAI = "https://livingai.in/careers/"
CURVVTECH = "https://www.curvvtech.com/careers"
INTERNSHIPS = (
    ReviewedInternship(
        "LivingAI", "https://livingai.in", LIVINGAI, "Applied AI Engineer Intern",
        "Bengaluru, India (onsite)", "article#applied-ai-intern",
        "Work on computer vision and NLP, prepare datasets, and evaluate or deploy models using Python.",
        "applied-ai-intern", "careers@livingai.in",
    ),
    ReviewedInternship(
        "LivingAI", "https://livingai.in", LIVINGAI, "Full-Stack Engineer Intern",
        "Bengaluru, India (onsite)", "article#fullstack-intern",
        "Build React and Next.js interfaces, integrate APIs including LLM services, and work with relational databases.",
        "fullstack-intern", "careers@livingai.in",
    ),
    ReviewedInternship(
        "Curvvtech", "https://curvvtech.com", CURVVTECH, "Backend Developer Intern",
        "Bengaluru, India (hybrid)", 'a[href="/careers/backend-developer-intern"]',
        "Build server-side logic, integrations, and REST APIs with Express.js, TypeScript, and PostgreSQL.",
    ),
    ReviewedInternship(
        "Curvvtech", "https://curvvtech.com", CURVVTECH, "Frontend Developer Intern",
        "Bengaluru, India (hybrid)", 'a[href="/careers/frontend-developer-intern"]',
        "Build user interfaces using React, Next.js, TypeScript, and Vite on client projects and admin tools.",
    ),
)


class ReviewedCareersDiscoverySource(BaseDiscoverySource):
    def __init__(self, name="reviewed_careers", enabled=True, http_client=None):
        super().__init__(name=name, enabled=enabled)
        self.http_client = http_client or HttpClient()

    def discover(self) -> DiscoveryResult:
        if not self.is_enabled():
            return DiscoveryResult()
        pages = {}
        for url in dict.fromkeys(role.careers for role in INTERNSHIPS):
            try:
                pages[url] = BeautifulSoup(self.http_client.get(url).text, "html.parser")
            except httpx.HTTPError as exc:
                logger.warning("Reviewed careers page unavailable: %s (%s)", url, type(exc).__name__)
        if not pages:
            raise RuntimeError("No reviewed employer careers pages could be reached.")
        companies, jobs = {}, []
        for role in INTERNSHIPS:
            page = pages.get(role.careers)
            card = page.select_one(role.selector) if page else None
            if not card:
                continue
            job_url = (
                f"{role.careers}#{role.fragment}" if role.fragment
                else f"{role.careers.rsplit('/careers', 1)[0]}{card['href']}"
            )
            description = role.summary
            if role.hiring_email and card.select_one(f'a[href^="mailto:{role.hiring_email}"]'):
                description += f" Apply with your resume and portfolio at {role.hiring_email}."
            companies.setdefault(role.website, Company(
                company_name=role.company, website=role.website, source_name=self.name,
                source_url=role.careers, careers_url=role.careers,
            ))
            jobs.append(Job(
                job_title=role.title, job_url=job_url, source_name=self.name,
                source_job_id=role.fragment or card["href"], company_name=role.company,
                company_website=role.website, location=role.location,
                employment_type="Internship", description=description, status="open",
            ))
        return DiscoveryResult(companies=list(companies.values()), jobs=jobs)

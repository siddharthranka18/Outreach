"""Andhra Startup Map verified fresher-job discovery adapter."""

from __future__ import annotations

import logging
from typing import List, Optional
from urllib.parse import parse_qs, urljoin, urlparse

from bs4 import BeautifulSoup, Tag

from startup_agent.discovery.base import BaseDiscoverySource, DiscoveryResult
from startup_agent.models.company import Company
from startup_agent.models.job import Job
from startup_agent.utils.http_client import HttpClient
from startup_agent.utils.normalizers import normalize_website


logger = logging.getLogger("startup_agent.discovery.andhra_startup_map")

ANDHRA_STARTUP_JOBS_URL = "https://www.andhrastartupmap.in/jobs"
ANDHRA_STARTUP_BASE_URL = "https://www.andhrastartupmap.in"

TARGET_TECHNICAL_MARKERS = (
    "software",
    "developer",
    "backend",
    "frontend",
    "full stack",
    "full-stack",
    "data engineer",
    "data scientist",
    "machine learning",
    "ai engineer",
    "ai research",
    "research engineer",
    "automation intern",
    "devops",
    "cloud engineer",
    "security engineer",
    "analytics engineer",
    "robotics engineer",
)

EXCLUDED_TITLE_MARKERS = (
    "mechanical",
    "electrical",
    "hardware",
    "design intern",
    "designer",
    "product manager",
    "marketing",
    "sales",
    "support engineer",
    "phd",
)


def _clean_text(value: str) -> str:
    return " ".join(value.split())


def _is_target_role(title: str) -> bool:
    normalized = title.lower()
    if any(marker in normalized for marker in EXCLUDED_TITLE_MARKERS):
        return False
    return any(marker in normalized for marker in TARGET_TECHNICAL_MARKERS)


GENERIC_ATS_HOSTS = {
    "jobs.ashbyhq.com",
    "jobs.lever.co",
    "boards.greenhouse.io",
    "job-boards.greenhouse.io",
    "jobs.smartrecruiters.com",
}


def _company_specific_ats_url(apply_url: str) -> Optional[str]:
    """Reduce a job URL to a stable company-specific public careers URL."""
    parsed = urlparse(apply_url)
    host = parsed.netloc.lower().removeprefix("www.")
    segments = [segment for segment in parsed.path.split("/") if segment]
    if host in GENERIC_ATS_HOSTS and segments:
        return f"{parsed.scheme or 'https'}://{host}/{segments[0]}"
    if host:
        return f"{parsed.scheme or 'https'}://{host}"
    return None


def _extract_company_website(card: Tag, apply_url: str) -> Optional[str]:
    """Prefer an official favicon domain, otherwise keep a unique ATS board."""
    logo = card.find("img", src=True)
    if logo:
        query = parse_qs(urlparse(str(logo.get("src", ""))).query)
        domain = (query.get("domain") or [None])[0]
        if domain:
            domain = str(domain).strip().lower().removeprefix("www.")
            if domain and domain not in GENERIC_ATS_HOSTS:
                return f"https://{domain}"
    return _company_specific_ats_url(apply_url)


def _extract_badge_texts(card: Tag) -> List[str]:
    """Return short card labels without relying on generated class ordering."""
    values: List[str] = []
    for span in card.find_all("span"):
        value = _clean_text(span.get_text(" ", strip=True))
        if value and len(value) <= 80:
            values.append(value)
    return values


class AndhraStartupMapDiscoverySource(BaseDiscoverySource):
    """Discover public, employer-verified India fresher technical roles."""

    def __init__(
        self,
        name: str = "andhra_startup_map",
        enabled: bool = True,
        url: str = ANDHRA_STARTUP_JOBS_URL,
        http_client: Optional[HttpClient] = None,
    ) -> None:
        super().__init__(name=name, enabled=enabled)
        self.url = url
        self.http_client = http_client or HttpClient(timeout=25.0, rate_limit_delay=1.0)

    def discover(self) -> DiscoveryResult:
        """Parse the public fresher catalog and retain profile-relevant roles."""
        if not self.is_enabled():
            return DiscoveryResult()

        response = self.http_client.get(self.url)
        soup = BeautifulSoup(response.text, "html.parser")
        companies_by_website: dict[str, Company] = {}
        jobs_by_url: dict[str, Job] = {}

        cards = soup.find_all(
            "div",
            class_=lambda value: bool(
                value and "rounded-2xl" in value and "justify-between" in value
            ),
        )
        for card in cards:
            title_container = card.find("h3")
            role_link = title_container.find("a", href=True) if title_container else None
            if role_link is None:
                continue
            title = _clean_text(role_link.get_text(" ", strip=True))
            if not title or not _is_target_role(title):
                continue

            company_badge = card.find("span", class_=lambda value: bool(value and "font-bold" in value))
            company_name = (
                _clean_text(company_badge.get_text(" ", strip=True))
                if company_badge
                else None
            )
            apply_link = next(
                (
                    link
                    for link in card.find_all("a", href=True)
                    if "apply on portal" in link.get_text(" ", strip=True).lower()
                ),
                None,
            )
            if not company_name or not apply_link:
                continue

            role_href = str(role_link.get("href", ""))
            internal_role_url = (
                urljoin(ANDHRA_STARTUP_BASE_URL, role_href)
                if role_href.startswith("/jobs/role/")
                else self.url
            )
            apply_url = str(apply_link.get("href", "")).strip()
            company_website = _extract_company_website(card, apply_url)
            if not company_website:
                continue
            badges = _extract_badge_texts(card)
            employment_type = next(
                (
                    value
                    for value in badges
                    if value.lower()
                    in {"internship", "apprenticeship", "full-time", "part-time"}
                ),
                None,
            )

            location_container = card.find(
                "div", class_=lambda value: bool(value and "mt-2" in value and "text-xs" in value)
            )
            location = (
                _clean_text(location_container.get_text(" ", strip=True))
                if location_container
                else None
            )
            id_source = role_href if role_href.startswith("/jobs/role/") else apply_url
            source_id = urlparse(id_source).path.rstrip("/").split("/")[-1]

            norm_site = normalize_website(company_website)
            companies_by_website.setdefault(
                norm_site,
                Company(
                    company_name=company_name,
                    website=company_website,
                    source_name=self.name,
                    source_url=internal_role_url,
                    employee_count=None,
                    location="India",
                    careers_url=internal_role_url,
                    hiring_status="Verified open by source",
                ),
            )
            job = Job(
                job_title=title,
                job_url=apply_url,
                source_name=self.name,
                company_name=company_name,
                company_website=company_website,
                description=(
                    "Employer-verified fresher listing indexed by Andhra Startup Map. "
                    f"Source detail: {internal_role_url}"
                ),
                location=location,
                employment_type=employment_type,
                experience_level="Fresher / internship",
                source_job_id=source_id,
                status="open",
            )
            jobs_by_url.setdefault(job.normalized_job_url, job)

        result = DiscoveryResult(
            companies=list(companies_by_website.values()),
            jobs=list(jobs_by_url.values()),
        )
        logger.info(
            "Andhra Startup Map discovery finished: %d companies and %d technical fresher roles.",
            len(result.companies),
            len(result.jobs),
        )
        return result

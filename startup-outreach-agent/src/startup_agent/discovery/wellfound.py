"""Wellfound India startup and early-career job discovery adapter."""

from __future__ import annotations

import logging
import json
import re
from datetime import datetime
from typing import List, Optional
from urllib.parse import urljoin

from bs4 import BeautifulSoup, Tag

from startup_agent.discovery.base import BaseDiscoverySource, DiscoveryResult
from startup_agent.models.company import Company
from startup_agent.models.job import Job
from startup_agent.utils.http_client import HttpClient
from startup_agent.utils.normalizers import normalize_website


logger = logging.getLogger("startup_agent.discovery.wellfound")

WELLFOUND_BASE_URL = "https://wellfound.com"
WELLFOUND_INDIA_URL = f"{WELLFOUND_BASE_URL}/location/india"

EARLY_CAREER_TITLE_MARKERS = (
    "intern",
    "junior",
    "fresh grad",
    "fresher",
    "new grad",
    "new graduate",
    "graduate",
    "entry level",
    "entry-level",
    "trainee",
    "apprentice",
)

SENIOR_TITLE_MARKERS = (
    "senior",
    "staff",
    "principal",
    "architect",
    "manager",
    "director",
    "head of",
    "chief ",
    "lead ",
)

TARGET_TECHNICAL_MARKERS = (
    "software",
    "backend",
    "front end",
    "frontend",
    "full stack",
    "full-stack",
    "developer",
    "data scientist",
    "data engineer",
    "machine learning",
    "ml engineer",
    "ai engineer",
    "artificial intelligence",
    "computer vision",
    "devops",
    "cloud engineer",
    "platform engineer",
    "security engineer",
    "automation engineer",
    "robotics",
)


def _clean_text(value: str) -> str:
    """Collapse page whitespace into a stable plain-text value."""
    return " ".join(value.split())


def _parse_employee_count(text: str) -> Optional[str]:
    """Extract a Wellfound employee band such as ``11-50 Employees``."""
    match = re.search(
        r"(\d[\d,]*\s*[-–]\s*\d[\d,]*|\d[\d,]*\+)\s*Employees",
        text,
        re.IGNORECASE,
    )
    if not match:
        return None
    return re.sub(r"\s+", "", match.group(1).replace("–", "-"))


def _employee_band_is_small(employee_count: Optional[str], maximum: int = 200) -> bool:
    """Accept only size bands whose published upper bound is within the limit."""
    if not employee_count:
        return False
    values = [int(value.replace(",", "")) for value in re.findall(r"\d[\d,]*", employee_count)]
    if not values or "+" in employee_count:
        return False
    return values[-1] <= maximum


def _extract_experience(text: str) -> tuple[Optional[str], Optional[float]]:
    """Return Wellfound's experience label and numeric year requirement."""
    match = re.search(r"(\d+(?:\.\d+)?)\s*years? of exp", text, re.IGNORECASE)
    if not match:
        return None, None
    years = float(match.group(1))
    return match.group(0), years


def _format_experience_requirement(value: object) -> Optional[str]:
    """Normalize Schema.org experience values into database-safe text."""
    if value is None:
        return None
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        months = value.get("monthsOfExperience")
        if isinstance(months, (int, float)):
            years = months / 12
            display_years = str(int(years)) if years.is_integer() else f"{years:.1f}"
            return f"{display_years} years of exp"
        return None
    if isinstance(value, list):
        normalized = [_format_experience_requirement(item) for item in value]
        return ", ".join(item for item in normalized if item) or None
    return str(value)


def _is_early_career(title: str, listing_text: str) -> bool:
    """Keep explicit early-career roles or listings requiring at most two years."""
    normalized_title = title.lower()
    explicitly_early = any(marker in normalized_title for marker in EARLY_CAREER_TITLE_MARKERS)
    _, years = _extract_experience(listing_text)

    if any(marker in normalized_title for marker in SENIOR_TITLE_MARKERS) and not explicitly_early:
        return False
    return explicitly_early or (years is not None and years <= 2)


def _is_target_technical_role(title: str) -> bool:
    """Avoid spending detail requests on non-technical early-career listings."""
    normalized_title = title.lower()
    return any(marker in normalized_title for marker in TARGET_TECHNICAL_MARKERS)


def _extract_location(text: str) -> Optional[str]:
    """Extract the location/workplace segment from a rendered job-card line."""
    pattern = re.compile(
        r"(?:Remote only|Onsite or remote|In office|Remote|Hybrid|Everywhere)"
        r"\s*(?:[\u2022·]\s*)?(.+?)"
        r"(?=\s+\d+(?:\.\d+)?\s*years? of exp|\s+(?:yesterday|today|\d+\s+(?:day|week|month)s? ago)|$)",
        re.IGNORECASE,
    )
    match = pattern.search(text)
    if match:
        prefix = text[match.start() : match.start(1)].strip()
        return _clean_text(f"{prefix} {match.group(1)}")

    india_match = re.search(
        r"\b(India|Bengaluru|Bangalore|Gurugram|Gurgaon|Delhi|Noida|Pune|Mumbai|Hyderabad|Ahmedabad)\b(?:\s*\+\s*\d+)?",
        text,
        re.IGNORECASE,
    )
    return india_match.group(0) if india_match else None


def _find_company_card(header: Tag) -> Optional[Tag]:
    """Find the outer listing card containing a startup header and all its jobs."""
    return header.find_parent(
        "div",
        class_=lambda value: bool(
            value and "rounded" in value and "border" in value and "w-full" in value
        ),
    )


class WellfoundDiscoverySource(BaseDiscoverySource):
    """Discover small-startup roles from Wellfound's public India directory."""

    def __init__(
        self,
        name: str = "wellfound_india",
        enabled: bool = True,
        base_url: str = WELLFOUND_BASE_URL,
        listing_url: str = WELLFOUND_INDIA_URL,
        max_pages: int = 5,
        max_employees: int = 200,
        http_client: Optional[HttpClient] = None,
    ) -> None:
        super().__init__(name=name, enabled=enabled)
        self.base_url = base_url.rstrip("/")
        self.listing_url = listing_url
        self.max_pages = max(1, max_pages)
        self.max_employees = max_employees
        self.http_client = http_client or HttpClient(timeout=25.0, rate_limit_delay=1.0)

    def _fetch_job_detail(self, job_url: str) -> dict:
        """Read Wellfound's public JobPosting JSON-LD for accurate role metadata."""
        try:
            response = self.http_client.get(job_url)
            soup = BeautifulSoup(response.text, "html.parser")
            for script in soup.find_all("script", type="application/ld+json"):
                if not script.string:
                    continue
                payload = json.loads(script.string)
                candidates = payload if isinstance(payload, list) else [payload]
                for candidate in candidates:
                    if not isinstance(candidate, dict) or candidate.get("@type") != "JobPosting":
                        continue

                    description_html = candidate.get("description") or ""
                    description = _clean_text(
                        BeautifulSoup(description_html, "html.parser").get_text(" ", strip=True)
                    )
                    organization = candidate.get("hiringOrganization") or {}
                    official_website = organization.get("sameAs")

                    location_parts: List[str] = []
                    if candidate.get("jobLocationType") == "TELECOMMUTE":
                        location_parts.append("Remote")
                    for restriction in candidate.get("applicantLocationRequirements") or []:
                        if isinstance(restriction, dict) and restriction.get("name"):
                            location_parts.append(str(restriction["name"]))
                    for place in candidate.get("jobLocation") or []:
                        address = place.get("address", {}) if isinstance(place, dict) else {}
                        for key in ("addressLocality", "addressRegion", "addressCountry"):
                            value = address.get(key)
                            if value and str(value) not in location_parts:
                                location_parts.append(str(value))

                    employment_type = candidate.get("employmentType")
                    if isinstance(employment_type, list):
                        employment_type = ", ".join(str(value) for value in employment_type)
                    if isinstance(employment_type, str):
                        employment_type = employment_type.replace("_", " ").title()

                    posted_at = None
                    if candidate.get("datePosted"):
                        try:
                            posted_at = datetime.fromisoformat(
                                str(candidate["datePosted"]).replace("Z", "+00:00")
                            )
                        except ValueError:
                            posted_at = None

                    return {
                        "description": description or None,
                        "official_website": official_website,
                        "location": " / ".join(location_parts) or None,
                        "employment_type": employment_type,
                        "experience_level": _format_experience_requirement(
                            candidate.get("experienceRequirements")
                        ),
                        "posted_at": posted_at,
                    }
        except Exception as exc:
            logger.warning("Could not enrich Wellfound job %s: %s", job_url, exc)
        return {}

    def discover(self) -> DiscoveryResult:
        """Fetch multiple India result pages and retain verifiable small startups."""
        if not self.is_enabled():
            return DiscoveryResult()

        companies_by_website: dict[str, Company] = {}
        jobs_by_url: dict[str, Job] = {}

        for page_number in range(1, self.max_pages + 1):
            page_url = f"{self.listing_url}?page={page_number}"
            logger.info("Fetching Wellfound India page %d/%d...", page_number, self.max_pages)
            response = self.http_client.get(page_url)
            soup = BeautifulSoup(response.text, "html.parser")
            headers = soup.select('[data-testid="startup-header"]')
            if not headers:
                logger.warning("No Wellfound startup cards found on page %d; stopping.", page_number)
                break

            for header in headers:
                card = _find_company_card(header)
                if card is None:
                    continue

                name_tag = header.find("h2")
                profile_link = header.find(
                    "a", href=lambda href: bool(href and href.startswith("/company/"))
                )
                if not name_tag or not profile_link:
                    continue

                company_name = _clean_text(name_tag.get_text(" ", strip=True))
                company_url = urljoin(self.base_url, profile_link.get("href", ""))
                employee_count = _parse_employee_count(header.get_text(" ", strip=True))
                if not _employee_band_is_small(employee_count, self.max_employees):
                    continue

                company_jobs: List[Job] = []
                official_website: Optional[str] = None
                for job_link in card.find_all(
                    "a", href=lambda href: bool(href and href.startswith("/jobs/"))
                ):
                    title = _clean_text(job_link.get_text(" ", strip=True))
                    job_block = job_link.find_parent(
                        "div",
                        class_=lambda value: bool(value and "min-h-[50px]" in value),
                    )
                    listing_text = _clean_text(
                        (job_block or job_link.parent).get_text(" ", strip=True)
                    )
                    if (
                        not title
                        or not _is_early_career(title, listing_text)
                        or not _is_target_technical_role(title)
                    ):
                        continue

                    # Location parsing must not mistake words such as "Remote" in
                    # the job title for the workplace metadata that follows it.
                    details_text = (
                        listing_text[len(title) :].strip()
                        if listing_text.startswith(title)
                        else listing_text
                    )

                    relative_job_url = job_link.get("href", "")
                    job_url = urljoin(self.base_url, relative_job_url)
                    detail = self._fetch_job_detail(job_url)
                    if detail.get("official_website"):
                        official_website = str(detail["official_website"])
                    source_id_match = re.match(r"/jobs/(\d+)", relative_job_url)
                    experience_label, _ = _extract_experience(details_text)
                    employment_match = re.search(
                        r"\b(Full-time|Part-time|Contract|Internship|Temporary)\b",
                        details_text,
                        re.IGNORECASE,
                    )

                    company_jobs.append(
                        Job(
                            job_title=title,
                            job_url=job_url,
                            source_name=self.name,
                            company_name=company_name,
                            company_website=official_website or company_url,
                            description=detail.get("description") or listing_text,
                            location=detail.get("location") or _extract_location(details_text),
                            employment_type=(
                                detail.get("employment_type")
                                or (employment_match.group(1) if employment_match else None)
                            ),
                            experience_level=(
                                detail.get("experience_level") or experience_label
                            ),
                            source_job_id=(
                                source_id_match.group(1) if source_id_match else relative_job_url
                            ),
                            posted_at=detail.get("posted_at"),
                            status="open",
                        )
                    )

                if not company_jobs:
                    continue

                resolved_website = official_website or company_url
                for company_job in company_jobs:
                    company_job.company_website = resolved_website
                normalized_website = normalize_website(resolved_website)
                companies_by_website.setdefault(
                    normalized_website,
                    Company(
                        company_name=company_name,
                        website=resolved_website,
                        source_name=self.name,
                        source_url=page_url,
                        employee_count=employee_count,
                        location="India",
                        careers_url=company_url,
                        hiring_status="Actively Hiring",
                    ),
                )
                for job in company_jobs:
                    jobs_by_url.setdefault(job.normalized_job_url, job)

        result = DiscoveryResult(
            companies=list(companies_by_website.values()),
            jobs=list(jobs_by_url.values()),
        )
        logger.info(
            "Wellfound discovery finished: %d small startups and %d early-career jobs.",
            len(result.companies),
            len(result.jobs),
        )
        return result

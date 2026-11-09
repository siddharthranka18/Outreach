"""Direct discovery from public applicant tracking system job boards."""

from datetime import datetime
import logging
import re
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse
from bs4 import BeautifulSoup
from startup_agent.discovery.base import BaseDiscoverySource, DiscoveryResult
from startup_agent.models.company import Company
from startup_agent.models.job import Job
from startup_agent.utils.http_client import HttpClient

logger = logging.getLogger("startup_agent.discovery.ats")

DEFAULT_ATS_TARGETS: List[Dict[str, str]] = []


def extract_ats_target(
    job_url: str,
    company_name: str,
    website: str,
    employee_count: Optional[str] = None,
) -> Optional[Dict[str, str]]:
    """Derive a public ATS board identifier from a discovered job URL."""
    parsed = urlparse(job_url)
    host = parsed.netloc.lower()
    path_parts = [part for part in parsed.path.split("/") if part]
    platform: Optional[str] = None
    board_token: Optional[str] = None

    if host in {"jobs.ashbyhq.com", "api.ashbyhq.com"} and path_parts:
        platform = "ashby"
        board_token = path_parts[0]
    elif host in {
        "boards.greenhouse.io",
        "job-boards.greenhouse.io",
        "boards-api.greenhouse.io",
    } and path_parts:
        platform = "greenhouse"
        if host == "boards-api.greenhouse.io" and "boards" in path_parts:
            board_index = path_parts.index("boards")
            if board_index + 1 < len(path_parts):
                board_token = path_parts[board_index + 1]
        else:
            board_token = path_parts[0]
    elif host in {"jobs.lever.co", "api.lever.co"} and path_parts:
        platform = "lever"
        if host == "api.lever.co" and "postings" in path_parts:
            postings_index = path_parts.index("postings")
            if postings_index + 1 < len(path_parts):
                board_token = path_parts[postings_index + 1]
        else:
            board_token = path_parts[0]

    if parsed.hostname and re.fullmatch(r"[a-z0-9-]+\.recruitee\.com", parsed.hostname):
        platform = "recruitee"
        board_token = parsed.hostname.split(".")[0]

    if not platform or not board_token:
        return None

    target = {
        "platform": platform,
        "board_token": board_token,
        "company_name": company_name,
        "website": website,
    }
    if employee_count:
        target["employee_count"] = employee_count
    return target


class DirectAtsDiscoverySource(BaseDiscoverySource):
    """Discovers advertised roles using public careers APIs."""

    def __init__(
        self,
        name: str = "direct_ats",
        enabled: bool = True,
        targets: Optional[List[Dict[str, str]]] = None,
        http_client: Optional[HttpClient] = None,
    ) -> None:
        super().__init__(name=name, enabled=enabled)
        self.targets = targets if targets is not None else DEFAULT_ATS_TARGETS
        self.http_client = http_client or HttpClient()

    def _discover_greenhouse(self, target: Dict[str, str]) -> List[Job]:
        """Fetch jobs from public Greenhouse boards API."""
        board = target["board_token"]
        company_name = target["company_name"]
        website = target["website"]
        url = f"https://boards-api.greenhouse.io/v1/boards/{board}/jobs?content=true"

        resp = self.http_client.get(url)
        data = resp.json()
        raw_jobs = data.get("jobs", [])

        jobs: List[Job] = []
        for raw in raw_jobs:
            title = raw.get("title")
            job_url = raw.get("absolute_url")
            if not title or not job_url:
                continue

            loc_data = raw.get("location")
            location = loc_data.get("name") if isinstance(loc_data, dict) else str(loc_data or "")

            posted_at = None
            if raw.get("updated_at"):
                try:
                    posted_at = datetime.fromisoformat(raw["updated_at"].replace("Z", "+00:00"))
                except Exception:
                    pass

            raw_content = raw.get("content")
            description = None
            if raw_content:
                description = BeautifulSoup(raw_content, "html.parser").get_text(" ", strip=True)

            jobs.append(
                Job(
                    job_title=title.strip(),
                    job_url=job_url.strip(),
                    source_name=f"greenhouse:{board}",
                    company_name=company_name,
                    company_website=website,
                    location=location or None,
                    description=description,
                    source_job_id=str(raw.get("id")) if raw.get("id") else None,
                    posted_at=posted_at,
                    status="open",
                )
            )
        return jobs

    def _discover_ashby(self, target: Dict[str, str]) -> List[Job]:
        """Fetch jobs from public Ashby posting API."""
        board = target["board_token"]
        company_name = target["company_name"]
        website = target["website"]
        url = f"https://api.ashbyhq.com/posting-api/job-board/{board}"

        resp = self.http_client.get(url)
        data = resp.json()
        raw_jobs = data.get("jobs", [])

        jobs: List[Job] = []
        for raw in raw_jobs:
            title = raw.get("title")
            job_url = raw.get("jobUrl") or raw.get("applyUrl")
            if not title or not job_url:
                continue

            posted_at = None
            if raw.get("publishedAt"):
                try:
                    posted_at = datetime.fromisoformat(raw["publishedAt"].replace("Z", "+00:00"))
                except Exception:
                    pass

            jobs.append(
                Job(
                    job_title=title.strip(),
                    job_url=job_url.strip(),
                    source_name=f"ashby:{board}",
                    company_name=company_name,
                    company_website=website,
                    location=raw.get("location"),
                    employment_type=raw.get("employmentType"),
                    description=raw.get("descriptionPlain") or raw.get("description"),
                    source_job_id=str(raw.get("id")) if raw.get("id") else None,
                    posted_at=posted_at,
                    status="open",
                )
            )
        return jobs

    def _discover_lever(self, target: Dict[str, str]) -> List[Job]:
        """Fetch jobs from public Lever postings API."""
        board = target["board_token"]
        company_name = target["company_name"]
        website = target["website"]
        url = f"https://api.lever.co/v0/postings/{board}?mode=json"

        resp = self.http_client.get(url)
        data = resp.json()
        if not isinstance(data, list):
            return []

        jobs: List[Job] = []
        for raw in data:
            title = raw.get("text")
            job_url = raw.get("hostedUrl") or raw.get("applyUrl")
            if not title or not job_url:
                continue

            cats = raw.get("categories", {})
            location = cats.get("location") if isinstance(cats, dict) else None
            commitment = cats.get("commitment") if isinstance(cats, dict) else None

            jobs.append(
                Job(
                    job_title=title.strip(),
                    job_url=job_url.strip(),
                    source_name=f"lever:{board}",
                    company_name=company_name,
                    company_website=website,
                    location=location,
                    employment_type=commitment,
                    description=(
                        raw.get("descriptionPlain")
                        or BeautifulSoup(raw.get("description") or "", "html.parser").get_text(" ", strip=True)
                        or None
                    ),
                    source_job_id=str(raw.get("id")) if raw.get("id") else None,
                    status="open",
                )
            )
        return jobs

    def _discover_recruitee(self, target: Dict[str, str]) -> List[Job]:
        board = target["board_token"]
        url = f"https://{board}.recruitee.com/api/offers"
        jobs = []
        for offer in self.http_client.get(url).json().get("offers", []):
            title = offer.get("title")
            job_url = offer.get("careers_url") or offer.get("careers_apply_url")
            if not title or not job_url or offer.get("status") not in (None, "published"):
                continue
            description = " ".join(
                BeautifulSoup(offer.get(field) or "", "html.parser").get_text(" ", strip=True)
                for field in ("description", "requirements")
            ).strip()
            jobs.append(
                Job(
                    job_title=title,
                    job_url=job_url,
                    source_name=f"recruitee:{board}",
                    company_name=target["company_name"],
                    company_website=target["website"],
                    location=offer.get("location"),
                    description=description or None,
                    employment_type=offer.get("employment_type_code"),
                    source_job_id=str(offer["id"]) if offer.get("id") else None,
                    status="open",
                )
            )
        return jobs

    def discover(self) -> DiscoveryResult:
        """Run discovery across all configured ATS board endpoints."""
        if not self.is_enabled():
            return DiscoveryResult()

        logger.info("Executing Direct ATS discovery across %d targets...", len(self.targets))
        companies: List[Company] = []
        jobs: List[Job] = []
        seen_companies = set()

        for target in self.targets:
            platform = target.get("platform", "").lower()
            company_name = target.get("company_name", "")
            website = target.get("website", "")
            board_token = target.get("board_token", "")

            if not company_name or not website or platform not in {"greenhouse", "ashby", "lever", "recruitee"}:
                continue
            if platform == "recruitee" and not re.fullmatch(r"[a-z0-9-]+", board_token):
                continue

            # Ensure company representation is included
            if website not in seen_companies:
                companies.append(
                    Company(
                        company_name=company_name,
                        website=website,
                        source_name=f"ats:{platform}",
                        source_url=target.get("source_url") or website,
                        employee_count=target.get("employee_count"),
                        hiring_status="Actively Hiring",
                    )
                )
                seen_companies.add(website)

            try:
                if platform == "greenhouse":
                    target_jobs = self._discover_greenhouse(target)
                elif platform == "ashby":
                    target_jobs = self._discover_ashby(target)
                elif platform == "lever":
                    target_jobs = self._discover_lever(target)
                elif platform == "recruitee":
                    target_jobs = self._discover_recruitee(target)
                else:
                    logger.warning("Unsupported ATS platform: %s", platform)
                    continue

                jobs.extend(target_jobs)
                logger.info("Discovered %d jobs for %s via %s", len(target_jobs), company_name, platform)
            except Exception as exc:
                logger.warning("Failed fetching ATS jobs for %s (%s): %s", company_name, platform, exc)

        return DiscoveryResult(companies=companies, jobs=jobs)


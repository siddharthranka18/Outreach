"""Direct ATS job board discovery adapter (Greenhouse, Ashby, Lever)."""

from datetime import datetime
import logging
from typing import Any, Dict, List, Optional
from startup_agent.discovery.base import BaseDiscoverySource, DiscoveryResult
from startup_agent.models.company import Company
from startup_agent.models.job import Job
from startup_agent.utils.http_client import HttpClient

logger = logging.getLogger("startup_agent.discovery.ats")

# Configured default ATS startup boards for official API ingestion
DEFAULT_ATS_TARGETS = [
    {
        "platform": "ashby",
        "board_token": "joinpogo",
        "company_name": "Pogo",
        "website": "https://www.joinpogo.com",
    },
    {
        "platform": "greenhouse",
        "board_token": "figma",
        "company_name": "Figma",
        "website": "https://www.figma.com",
    },
]


class DirectAtsDiscoverySource(BaseDiscoverySource):
    """Discovers advertised roles using public REST endpoints of Greenhouse, Ashby, and Lever."""

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
                    posted_at = datetime.fromisoformat(raw["updated_at"])
                except Exception:
                    pass

            jobs.append(
                Job(
                    job_title=title.strip(),
                    job_url=job_url.strip(),
                    source_name=f"greenhouse:{board}",
                    company_name=company_name,
                    company_website=website,
                    location=location or None,
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
                    description=raw.get("descriptionPlain"),
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
                    description=raw.get("descriptionPlain"),
                    source_job_id=str(raw.get("id")) if raw.get("id") else None,
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

            if not company_name or not website:
                continue

            # Ensure company representation is included
            if website not in seen_companies:
                companies.append(
                    Company(
                        company_name=company_name,
                        website=website,
                        source_name=f"ats:{platform}",
                        source_url=f"https://boards-api.{platform}.io/{board_token}",
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
                else:
                    logger.warning("Unsupported ATS platform: %s", platform)
                    continue

                jobs.extend(target_jobs)
                logger.info("Discovered %d jobs for %s via %s", len(target_jobs), company_name, platform)
            except Exception as exc:
                logger.warning("Failed fetching ATS jobs for %s (%s): %s", company_name, platform, exc)

        return DiscoveryResult(companies=companies, jobs=jobs)


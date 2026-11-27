"""Direct discovery from public applicant tracking system job boards."""

from datetime import datetime
import logging
import re
import time
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse
from bs4 import BeautifulSoup
from startup_agent.discovery.base import BaseDiscoverySource, DiscoveryResult
from startup_agent.models.company import Company
from startup_agent.models.job import Job
from startup_agent.utils.http_client import HttpClient
from startup_agent.discovery.public_ats import PLATFORMS, fetch_public_ats, workday_target

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

    workday = workday_target(job_url)
    if workday:
        platform, board_token = "workday", workday
    elif host in {"jobs.ashbyhq.com", "api.ashbyhq.com"} and path_parts:
        platform = "ashby"
        board_token = path_parts[-1] if path_parts[:2] == ["posting-api", "job-board"] else path_parts[0]
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
    elif host in {"jobs.lever.co", "api.lever.co", "jobs.eu.lever.co", "api.eu.lever.co"} and path_parts:
        platform = "lever"
        if host.startswith("api.") and "postings" in path_parts:
            postings_index = path_parts.index("postings")
            if postings_index + 1 < len(path_parts):
                board_token = path_parts[postings_index + 1]
        else:
            board_token = path_parts[0]

    if parsed.hostname and re.fullmatch(r"[a-z0-9-]+\.recruitee\.com", parsed.hostname):
        platform = "recruitee"
        board_token = parsed.hostname.split(".")[0]

    if host == "apply.workable.com" and path_parts and path_parts[0] not in {"j", "api"}:
        platform, board_token = "workable", path_parts[0]
    for suffix, kind in (("breezy.hr", "breezy"), ("teamtailor.com", "teamtailor"),
                         ("bamboohr.com", "bamboohr"), ("jobs.personio.de", "personio"), ("freshteam.com", "freshteam")):
        if parsed.hostname and re.fullmatch(r"[a-z0-9-]+\." + re.escape(suffix), parsed.hostname):
            platform, board_token = kind, parsed.hostname.split(".")[0]

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
    if platform == "lever" and ".eu." in host:
        target["source_url"] = job_url
    return target


class DirectAtsDiscoverySource(BaseDiscoverySource):
    """Discovers advertised roles using public careers APIs."""

    def __init__(
        self,
        name: str = "direct_ats",
        enabled: bool = True,
        targets: Optional[List[Dict[str, str]]] = None,
        http_client: Optional[HttpClient] = None,
        platforms=None,
    ) -> None:
        super().__init__(name=name, enabled=enabled)
        self.targets = targets if targets is not None else DEFAULT_ATS_TARGETS
        self.http_client = http_client or HttpClient(public_only=True)
        self.platforms = set(platforms) if platforms is not None else {"greenhouse", "ashby", "lever", "recruitee", "workable", "breezy", "teamtailor", "bamboohr", "freshteam"}
        self.successful_polls = []
        self.attempted_boards = 0
        self.board_health = None

    def _discover_greenhouse(self, target: Dict[str, str]) -> List[Job]:
        """Fetch jobs from public Greenhouse boards API."""
        board = target["board_token"]
        company_name = target["company_name"]
        website = target["website"]
        url = f"https://boards-api.greenhouse.io/v1/boards/{board}/jobs?content=true"

        resp = self.http_client.get(url)
        data = resp.json()
        raw_jobs = data["jobs"]
        if not isinstance(raw_jobs,list):raise ValueError('Greenhouse jobs shape changed')

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
        raw_jobs = data["jobs"]
        if not isinstance(raw_jobs,list):raise ValueError('Ashby jobs shape changed')

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
        host = urlparse(target.get("source_url") or "").hostname
        api = "api.eu.lever.co" if host in {"jobs.eu.lever.co", "api.eu.lever.co"} else "api.lever.co"
        url = f"https://{api}/v0/postings/{board}?mode=json"

        resp = self.http_client.get(url)
        data = resp.json()
        if not isinstance(data, list):
            raise ValueError('Lever jobs shape changed')

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
        offers=self.http_client.get(url).json()["offers"]
        if not isinstance(offers,list):raise ValueError('Recruitee offers shape changed')
        for offer in offers:
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

    def fetch_board_jobs(self, target: Dict[str, str]) -> List[Job]:
        platform = target["platform"].lower()
        if platform not in self.platforms:
            return []
        if platform != "workday" and not re.fullmatch(r"[A-Za-z0-9_-]+", target["board_token"]):
            raise ValueError("Unsafe ATS board token")
        if platform in PLATFORMS:
            return fetch_public_ats(target, self.http_client)
        fetch = {
            "greenhouse": self._discover_greenhouse,
            "ashby": self._discover_ashby,
            "lever": self._discover_lever,
            "recruitee": self._discover_recruitee,
        }
        return fetch[target["platform"].lower()](target)

    def poll_board(self, target):
        if self.board_health and not self.board_health.allows(target):
            return None
        try:
            jobs = self.fetch_board_jobs(target)
        except Exception as exc:
            if self.board_health:
                self.board_health.outcome(target, error=exc)
            raise
        if self.board_health:
            self.board_health.outcome(target, jobs=jobs)
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
            deadline=getattr(self.http_client,'deadline',None)
            if isinstance(deadline,(int,float)) and time.monotonic()>=deadline:
                logger.info('ATS time budget reached after %d boards.',self.attempted_boards)
                break
            self.attempted_boards+=1
            platform = target.get("platform", "").lower()
            company_name = target.get("company_name", "")
            website = target.get("website", "")
            board_token = target.get("board_token", "")

            if not company_name or not website or platform not in self.platforms:
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
                target_jobs = self.poll_board(target)
                if target_jobs is None:
                    continue
                jobs.extend(target_jobs)
                # Only protocols returning a complete, unpaginated snapshot may count absence.
                if platform in {"greenhouse", "ashby", "lever", "recruitee", "workable", "personio"}:
                    self.successful_polls.append((target, target_jobs))
                logger.info("Discovered %d jobs for %s via %s", len(target_jobs), company_name, platform)
            except Exception as exc:
                logger.warning("Failed fetching ATS jobs for %s (%s): %s", company_name, platform, exc)

        return DiscoveryResult(companies=companies, jobs=jobs)


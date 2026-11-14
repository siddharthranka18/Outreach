"""Trial Remotive's public feed for technical fresher roles open to India."""

import logging
import re
from urllib.parse import urlsplit

from bs4 import BeautifulSoup

from startup_agent.discovery.andhra_startup_map import _is_target_role
from startup_agent.discovery.base import BaseDiscoverySource, DiscoveryResult
from startup_agent.discovery.hasjob import EARLY_CAREER
from startup_agent.models.company import Company
from startup_agent.models.job import Job
from startup_agent.utils.http_client import HttpClient
from startup_agent.utils.normalizers import normalize_job_url, normalize_name

FEED_URL = "https://remotive.com/api/remote-jobs"
logger = logging.getLogger(__name__)


class RemotiveDiscoverySource(BaseDiscoverySource):
    def __init__(self, employers, name="remotive", enabled=True, http_client=None):
        super().__init__(name=name, enabled=enabled)
        self.employers = employers
        self.http_client = http_client or HttpClient()

    def discover(self) -> DiscoveryResult:
        if not self.is_enabled():
            return DiscoveryResult()
        companies = {}
        jobs = {}
        location_matches = 0
        for listing in self.http_client.get(FEED_URL).json()["jobs"]:
            title = listing.get("title") or ""
            job_type = listing.get("job_type") or ""
            internship = job_type == "internship"
            if not _is_target_role(title) or not (internship or EARLY_CAREER.search(title)):
                continue
            location = (listing.get("candidate_required_location") or "").strip().casefold()
            if location in {"worldwide", "anywhere", "anywhere in the world"}:
                label = "Remote / Worldwide"
            elif re.search(r"(?:^|[,;/|])\s*india(?: only)?\s*(?:$|[,;/|])", location):
                label = "Remote / India"
            else:
                continue
            location_matches += 1
            name = listing.get("company_name") or ""
            employer = self.employers.get(normalize_name(name))
            url = listing.get("url") or ""
            if not employer or urlsplit(url).scheme != "https" or urlsplit(url).netloc != "remotive.com":
                continue
            domain, evidence = employer
            website = f"https://{domain}"
            companies.setdefault(domain, Company(
                company_name=name, website=website, employee_count=evidence["employee_count"],
                source_name=self.name, source_url=evidence["source_url"],
            ))
            jobs[normalize_job_url(url)] = Job(
                job_title=title, job_url=url, source_name=self.name, company_name=name,
                company_website=website, location=label,
                employment_type="Internship" if internship else job_type,
                description=BeautifulSoup(listing.get("description") or "", "html.parser").get_text(" ", strip=True),
                status="open",
            )
        logger.info("Remotive trial: %d India-eligible early-career listings, %d unique with reviewed employers.",
                    location_matches, len(jobs))
        return DiscoveryResult(companies=list(companies.values()), jobs=list(jobs.values()))

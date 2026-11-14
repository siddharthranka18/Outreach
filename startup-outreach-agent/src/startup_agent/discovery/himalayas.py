"""Discover India-eligible remote technical internships via Himalayas."""

from datetime import datetime, timezone
import logging

import httpx

from bs4 import BeautifulSoup

from startup_agent.discovery.andhra_startup_map import _is_target_role
from startup_agent.discovery.base import BaseDiscoverySource, DiscoveryResult
from startup_agent.discovery.hasjob import EARLY_CAREER
from startup_agent.models.company import Company
from startup_agent.models.job import Job
from startup_agent.utils.http_client import HttpClient
from startup_agent.utils.normalizers import normalize_job_url, normalize_name


SEARCH_URL = "https://himalayas.app/jobs/api/search"
logger = logging.getLogger(__name__)


class HimalayasDiscoverySource(BaseDiscoverySource):
    def __init__(self, employers, name="himalayas", enabled=True, http_client=None, *, employers_by_name=None):
        super().__init__(name=name, enabled=enabled)
        self.employers = employers
        self.employers_by_name = employers_by_name or {}
        self.http_client = http_client or HttpClient()

    def _listings(self):
        queries = ({"employment_type": "Intern"}, {"seniority": "Entry-level"})
        for query in queries:
            for page in range(1, 4):
                try:
                    listings = self.http_client.get(
                        SEARCH_URL, params={"country": "IN", "page": page, **query},
                    ).json()["jobs"]
                except (httpx.HTTPError, ValueError, KeyError):
                    if query == queries[0] and page == 1:
                        raise
                    logger.warning("Himalayas search failed for %s, page %d.", query, page)
                    break
                if not listings:
                    break
                yield from listings

    def discover(self) -> DiscoveryResult:
        if not self.is_enabled():
            return DiscoveryResult()

        companies = {}
        jobs = {}
        now = datetime.now(timezone.utc).timestamp()
        for listing in self._listings():
            title = listing.get("title") or ""
            slug = listing.get("companySlug")
            url = listing.get("applicationLink")
            name = listing.get("companyName") or ""
            employer = self.employers.get(slug) or self.employers_by_name.get(normalize_name(name))
            internship = listing.get("employmentType") == "Intern"
            seniority = listing.get("seniority") or []
            entry_level = seniority == ["Entry-level"]
            if not (employer and name and url and _is_target_role(title)
                    and (internship or EARLY_CAREER.search(title) or entry_level)):
                continue
            if (listing.get("expiryDate") or 0) <= now:
                continue
            locations = listing.get("locationRestrictions")
            if not isinstance(locations, list) or (locations and not any(
                (location.get("alpha2") == "IN" or location.get("name") == "India")
                if isinstance(location, dict) else location in {"India", "IN"}
                for location in locations
            )):
                continue
            timezones = listing.get("timezoneRestrictions") or []
            if timezones and "UTC+5:30" not in timezones and "UTC+05:30" not in timezones:
                continue

            domain, evidence = employer
            website = f"https://{domain}"
            companies.setdefault(domain, Company(
                company_name=name, website=website, source_name=self.name,
                source_url=evidence["source_url"], employee_count=evidence["employee_count"],
            ))
            jobs[normalize_job_url(url)] = Job(
                job_title=title, job_url=url, source_name=self.name,
                company_name=name, company_website=website,
                location="Remote / India" if locations else "Remote / Worldwide",
                employment_type="Internship" if internship else listing.get("employmentType"),
                experience_level="Entry-level" if entry_level else None,
                description=BeautifulSoup(listing.get("description") or "", "html.parser").get_text(" ", strip=True),
                status="open",
            )
        return DiscoveryResult(companies=list(companies.values()), jobs=list(jobs.values()))

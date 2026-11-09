"""Discover India-eligible remote technical internships via Himalayas."""

from datetime import datetime, timezone

from bs4 import BeautifulSoup

from startup_agent.discovery.andhra_startup_map import _is_target_role
from startup_agent.discovery.base import BaseDiscoverySource, DiscoveryResult
from startup_agent.discovery.hasjob import EARLY_CAREER
from startup_agent.models.company import Company
from startup_agent.models.job import Job
from startup_agent.utils.http_client import HttpClient


SEARCH_URL = "https://himalayas.app/jobs/api/search?country=IN&employment_type=Intern"


class HimalayasDiscoverySource(BaseDiscoverySource):
    def __init__(self, employers, name="himalayas", enabled=True, http_client=None):
        super().__init__(name=name, enabled=enabled)
        self.employers = employers
        self.http_client = http_client or HttpClient()

    def discover(self) -> DiscoveryResult:
        if not self.is_enabled():
            return DiscoveryResult()

        companies = {}
        jobs = []
        now = datetime.now(timezone.utc).timestamp()
        for listing in self.http_client.get(SEARCH_URL).json().get("jobs", []):
            title = listing.get("title") or ""
            slug = listing.get("companySlug")
            employer = self.employers.get(slug)
            url = listing.get("applicationLink")
            name = listing.get("companyName")
            if not (employer and name and url and _is_target_role(title) and EARLY_CAREER.search(title)):
                continue
            if (listing.get("expiryDate") or 0) <= now:
                continue
            locations = listing.get("locationRestrictions") or []
            if locations and "India" not in locations:
                continue

            domain, evidence = employer
            website = f"https://{domain}"
            companies.setdefault(domain, Company(
                company_name=name, website=website, source_name=self.name,
                source_url=evidence["source_url"], employee_count=evidence["employee_count"],
            ))
            jobs.append(Job(
                job_title=title, job_url=url, source_name=self.name,
                company_name=name, company_website=website,
                location="Remote / India" if locations else "Remote / Worldwide",
                employment_type="Internship",
                description=BeautifulSoup(listing.get("description") or "", "html.parser").get_text(" ", strip=True),
                status="open",
            ))
        return DiscoveryResult(companies=list(companies.values()), jobs=jobs)
